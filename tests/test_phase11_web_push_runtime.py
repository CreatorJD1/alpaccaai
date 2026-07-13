from __future__ import annotations

import base64
import json
import sqlite3
import subprocess
import sys
import textwrap
import threading
import types
from pathlib import Path

import pytest

from alpecca import notification_anchor as anchor_mod
from alpecca import notification_outbox as outbox_mod
from alpecca import web_push_adapter as push_mod
from alpecca import web_push_runtime as runtime_mod


SEAL_KEY = b"phase11-web-push-runtime-test-seal-key"
EVENT_ID = "out_" + "1" * 32
OTHER_EVENT_ID = "out_" + "2" * 32
TRANSPORT_KEY = "txi_" + "3" * 64
ENDPOINT = "https://fcm.googleapis.com/fcm/send/runtime-test"
P256DH = "B" * 87
AUTH = "C" * 22


class FakeCredentialRecord:
    def __init__(self, value: object = None) -> None:
        self.value = value
        self.read_count = 0
        self.writes: list[str] = []

    def read(self) -> str | None:
        self.read_count += 1
        return self.value  # type: ignore[return-value]

    def write(self, value: str) -> None:
        self.writes.append(value)
        self.value = value


class CorruptingCredentialRecord(FakeCredentialRecord):
    def write(self, value: str) -> None:
        self.writes.append(value)
        parsed = json.loads(value)
        if parsed["subscriptions"]:
            parsed["subscriptions"][0]["auth"] = "tampered_auth"
            self.value = json.dumps(parsed)
        else:
            self.value = value


class _FakeMutexHandle:
    def __init__(self, lock: threading.Lock) -> None:
        self.lock = lock


class _FakeNamedMutexKernel:
    WAIT_OBJECT_0 = 0
    WAIT_ABANDONED = 0x80
    WAIT_TIMEOUT = 0x102

    def __init__(self) -> None:
        self._registry_lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def CreateMutex(self, _security, _initial_owner: bool, name: str):
        with self._registry_lock:
            lock = self._locks.setdefault(name, threading.Lock())
        return _FakeMutexHandle(lock)

    def WaitForSingleObject(
        self, handle: _FakeMutexHandle, timeout_ms: int
    ) -> int:
        if handle.lock.acquire(timeout=timeout_ms / 1000):
            return self.WAIT_OBJECT_0
        return self.WAIT_TIMEOUT

    @staticmethod
    def ReleaseMutex(handle: _FakeMutexHandle) -> None:
        handle.lock.release()


class _FakeWin32Api:
    @staticmethod
    def CloseHandle(_handle: _FakeMutexHandle) -> None:
        return None


class FailOnceCommitAnchor(outbox_mod.InMemoryMonotonicAnchor):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_commit = False

    def commit(self, candidate: outbox_mod.LedgerCheckpoint) -> None:
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise outbox_mod.OutboxAnchorError("synthetic interrupted commit")
        super().commit(candidate)


class MutableClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _store(
    tmp_path: Path,
    *,
    record: FakeCredentialRecord | None = None,
    clock: MutableClock | None = None,
    seal_key: bytes = SEAL_KEY,
    anchor: outbox_mod.MonotonicAnchor | None = None,
    name: str = "web-push-runtime.db",
) -> runtime_mod.WebPushPrivateStore:
    return runtime_mod.WebPushPrivateStore(
        tmp_path / name,
        subscription_record=record or FakeCredentialRecord(),
        seal_key=seal_key,
        subscription_anchor=anchor,
        clock=clock or MutableClock(),
    )


def _subscription_payload(number: int = 1) -> dict[str, object]:
    return {
        "endpoint": (
            f"https://fcm.googleapis.com/fcm/send/runtime-subscription-{number}"
        ),
        "keys": {"p256dh": P256DH, "auth": f"auth_key_{number}"},
    }


def _push_subscription(number: int = 1) -> push_mod.PushSubscription:
    return push_mod.PushSubscription(
        subscription_id=f"wps_{number:032x}",
        endpoint=f"https://fcm.googleapis.com/fcm/send/transport-{number}",
        p256dh=P256DH,
        auth=AUTH,
    )


def _payload_ref(number: int = 1) -> outbox_mod.OpaquePayloadRef:
    return outbox_mod.OpaquePayloadRef(
        f"pref_{number:032x}_{number + 1:032x}"
    )


def _record_json(subscriptions: list[dict[str, object]]) -> str:
    body: dict[str, object] = {
        "version": runtime_mod.STORE_VERSION,
        "generation": 0,
        "subscriptions": subscriptions,
    }
    return runtime_mod._canonical(
        {**body, "seal": runtime_mod._record_seal(SEAL_KEY, body)}
    )


def _legacy_record_json(subscriptions: list[dict[str, object]]) -> str:
    body: dict[str, object] = {
        "version": runtime_mod.STORE_VERSION,
        "subscriptions": subscriptions,
    }
    return runtime_mod._canonical(
        {**body, "seal": runtime_mod._record_seal(SEAL_KEY, body)}
    )


def _sqlite_dump(db_path: Path) -> str:
    with sqlite3.connect(db_path) as conn:
        return "\n".join(conn.iterdump())


def test_import_is_inert_and_does_not_load_platform_or_transport_dependencies():
    repo_root = Path(__file__).resolve().parents[1]
    code = textwrap.dedent(
        """
        import builtins
        import sqlite3
        import sys

        real_import = builtins.__import__
        forbidden = {"cryptography", "pywebpush", "requests", "win32cred"}

        def guarded_import(name, *args, **kwargs):
            if name.split(".", 1)[0] in forbidden:
                raise AssertionError(f"eager dependency import: {name}")
            return real_import(name, *args, **kwargs)

        def forbidden_connect(*args, **kwargs):
            raise AssertionError("runtime import opened SQLite")

        builtins.__import__ = guarded_import
        sqlite3.connect = forbidden_connect
        import alpecca.web_push_runtime

        assert forbidden.isdisjoint(sys.modules)
        """
    )

    subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


def test_protected_subscription_record_roundtrips_and_rejects_tampering(
    tmp_path: Path,
):
    record = FakeCredentialRecord()
    first_store = _store(tmp_path, record=record)
    result = first_store.register_subscription(_subscription_payload())

    assert result["subscribed"] is True
    assert len(record.writes) == 1
    first = first_store.subscriptions()[0]
    reloaded = _store(tmp_path, record=record).subscriptions()[0]
    assert reloaded == first
    assert reloaded.endpoint == _subscription_payload()["endpoint"]

    parsed = json.loads(str(record.value))
    parsed["subscriptions"][0]["endpoint"] = (
        "https://fcm.googleapis.com/fcm/send/tampered"
    )
    record.value = json.dumps(parsed)
    with pytest.raises(runtime_mod.WebPushRuntimeError, match="seal is invalid"):
        first_store.subscriptions()

    record.value = record.writes[0]
    wrong_key_store = _store(
        tmp_path, record=record, seal_key=b"different-runtime-seal-key-material"
    )
    with pytest.raises(runtime_mod.WebPushRuntimeError, match="seal is invalid"):
        wrong_key_store.subscriptions()


def test_protected_subscription_record_rejects_wrong_shapes_and_cap(
    tmp_path: Path,
):
    valid_item = {
        "subscription_id": "wps_" + "a" * 32,
        "endpoint": ENDPOINT,
        "p256dh": P256DH,
        "auth": AUTH,
    }
    wrong_top_shape = json.dumps(
        {"version": 1, "subscriptions": [], "seal": "x", "extra": True}
    )
    wrong_entry_shape = _record_json([{**valid_item, "extra": "field"}])
    over_cap = _record_json(
        [
            {**valid_item, "subscription_id": f"wps_{number:032x}"}
            for number in range(runtime_mod.MAX_SUBSCRIPTIONS + 1)
        ]
    )

    cases = (
        (wrong_top_shape, "wrong shape"),
        (wrong_entry_shape, "entry is invalid"),
        (over_cap, "exceeds its cap"),
    )
    for ordinal, (raw, message) in enumerate(cases):
        store = runtime_mod.WebPushPrivateStore(
            tmp_path / f"shape-{ordinal}.db",
            subscription_record=FakeCredentialRecord(raw),
            seal_key=SEAL_KEY,
            clock=MutableClock(),
        )
        with pytest.raises(runtime_mod.WebPushRuntimeError, match=message):
            store.subscriptions()


def test_subscription_write_is_verified_by_readback(tmp_path: Path):
    record = CorruptingCredentialRecord()
    store = _store(tmp_path, record=record)

    with pytest.raises(runtime_mod.WebPushRuntimeError, match="seal is invalid"):
        store.register_subscription(_subscription_payload())


def test_anchored_subscription_write_verifies_readback_before_commit(tmp_path: Path):
    record = CorruptingCredentialRecord()
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    store = _store(tmp_path, record=record, anchor=anchor)

    with pytest.raises(runtime_mod.WebPushRuntimeError, match="seal is invalid"):
        store.register_subscription(_subscription_payload())

    snapshot = anchor.snapshot()
    assert snapshot.current is not None
    assert snapshot.current.sequence == 0
    assert snapshot.pending is None


def test_subscription_anchor_migrates_legacy_record(tmp_path: Path):
    item = {
        "subscription_id": "wps_" + "a" * 32,
        "endpoint": ENDPOINT,
        "p256dh": P256DH,
        "auth": AUTH,
    }
    record = FakeCredentialRecord(_legacy_record_json([item]))
    anchor = outbox_mod.InMemoryMonotonicAnchor()

    store = _store(tmp_path, record=record, anchor=anchor)

    assert store.subscriptions() == (push_mod.PushSubscription(**item),)
    persisted = json.loads(str(record.value))
    assert persisted["generation"] == 0
    assert frozenset(persisted) == {
        "version",
        "generation",
        "subscriptions",
        "seal",
    }
    checkpoint = anchor.snapshot().current
    assert checkpoint is not None
    assert checkpoint.sequence == 0

    record.value = _legacy_record_json([])
    with pytest.raises(runtime_mod.WebPushRuntimeError, match="monotonic anchor"):
        store.subscriptions()


def test_subscription_anchor_detects_protected_record_rollback(tmp_path: Path):
    record = FakeCredentialRecord()
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    store = _store(tmp_path, record=record, anchor=anchor)
    store.register_subscription(_subscription_payload(1))
    first_generation = str(record.value)
    store.register_subscription(_subscription_payload(2))
    assert json.loads(str(record.value))["generation"] == 2

    record.value = first_generation

    with pytest.raises(runtime_mod.WebPushRuntimeError, match="monotonic anchor"):
        store.subscriptions()
    with pytest.raises(runtime_mod.WebPushRuntimeError, match="monotonic anchor"):
        _store(tmp_path, record=record, anchor=anchor)


def test_initialized_subscription_state_rejects_missing_anchor(tmp_path: Path):
    record = FakeCredentialRecord()
    original_anchor = outbox_mod.InMemoryMonotonicAnchor()
    store = _store(tmp_path, record=record, anchor=original_anchor)
    store.register_subscription(_subscription_payload())

    with pytest.raises(runtime_mod.WebPushRuntimeError, match="anchor is missing"):
        _store(
            tmp_path,
            record=record,
            anchor=outbox_mod.InMemoryMonotonicAnchor(),
        )


def test_subscription_anchor_recovers_write_before_commit(tmp_path: Path):
    record = FakeCredentialRecord()
    anchor = FailOnceCommitAnchor()
    store = _store(tmp_path, record=record, anchor=anchor)
    anchor.fail_next_commit = True

    with pytest.raises(outbox_mod.OutboxAnchorError, match="interrupted commit"):
        store.register_subscription(_subscription_payload())

    assert anchor.snapshot().pending is not None
    recovered = _store(tmp_path, record=record, anchor=anchor)
    assert len(recovered.subscriptions()) == 1
    assert anchor.snapshot().pending is None


@pytest.mark.parametrize(
    ("subscription", "message"),
    (
        ({"endpoint": ENDPOINT}, "wrong shape"),
        (
            {
                "endpoint": ENDPOINT,
                "keys": {"p256dh": P256DH, "auth": AUTH},
                "extra": True,
            },
            "wrong shape",
        ),
        (
            {"endpoint": ENDPOINT, "keys": {"p256dh": P256DH}},
            "keys have wrong shape",
        ),
        (
            {
                "endpoint": "http://fcm.googleapis.com/fcm/send/insecure",
                "keys": {"p256dh": P256DH, "auth": AUTH},
            },
            "HTTPS",
        ),
        (
            {
                "endpoint": ENDPOINT,
                "keys": {"p256dh": "not+base64url", "auth": AUTH},
            },
            "p256dh is invalid",
        ),
    ),
)
def test_subscription_registration_requires_exact_valid_shape(
    tmp_path: Path,
    subscription: dict[str, object],
    message: str,
):
    with pytest.raises(push_mod.WebPushAdapterError, match=message):
        _store(tmp_path).register_subscription(subscription)


def test_subscription_upsert_cap_and_strict_revoke(tmp_path: Path):
    record = FakeCredentialRecord()
    store = _store(tmp_path, record=record)
    first_payload = _subscription_payload(1)
    first_result = store.register_subscription(first_payload)

    replacement = _subscription_payload(1)
    replacement["keys"] = {"p256dh": "D" * 87, "auth": "replacement_auth"}
    replacement_result = store.register_subscription(replacement)
    assert replacement_result["subscription_id"] == first_result["subscription_id"]
    assert len(store.subscriptions()) == 1
    assert store.subscriptions()[0].auth == "replacement_auth"

    store.register_subscription(_subscription_payload(2))
    before_cap_failure = record.value
    with pytest.raises(runtime_mod.WebPushRuntimeError, match="cap reached"):
        store.register_subscription(_subscription_payload(3))
    assert record.value == before_cap_failure
    assert len(store.subscriptions()) == runtime_mod.MAX_SUBSCRIPTIONS

    endpoint = str(first_payload["endpoint"])
    assert store.revoke_endpoint(endpoint) is True
    assert store.revoke_endpoint(endpoint) is False
    with pytest.raises(push_mod.WebPushAdapterError, match="allowlisted"):
        store.revoke_endpoint("https://example.com/not-a-push-service")


def test_secrets_are_absent_from_repr_public_status_and_sqlite(tmp_path: Path):
    record = FakeCredentialRecord()
    store = _store(tmp_path, record=record)
    registered = store.register_subscription(
        {"endpoint": ENDPOINT, "keys": {"p256dh": P256DH, "auth": AUTH}}
    )
    payload_ref = _payload_ref()
    store.bind_test_template(payload_ref)
    receipt = store.issue_ack_receipt(
        event_id=EVENT_ID,
        subscription_id=str(registered["subscription_id"]),
        transport_idempotency_key=TRANSPORT_KEY,
    )

    subscription_repr = repr(store.subscriptions())
    vapid = runtime_mod.VapidMaterial(
        private_key="private-vapid-material", public_key="public-vapid-material"
    )
    assert ENDPOINT not in subscription_repr
    assert P256DH not in subscription_repr
    assert AUTH not in subscription_repr
    assert "private-vapid-material" not in repr(vapid)
    assert SEAL_KEY.decode("ascii") not in repr(store)
    assert store.public_status() == {
        "subscription_count": 1,
        "subscription_cap": runtime_mod.MAX_SUBSCRIPTIONS,
        "template_scope": runtime_mod.TEST_TEMPLATE,
    }

    database_text = _sqlite_dump(store.db_path)
    for secret in (
        ENDPOINT,
        P256DH,
        AUTH,
        payload_ref.value,
        receipt,
        TRANSPORT_KEY,
        SEAL_KEY.decode("ascii"),
    ):
        assert secret not in database_text


def test_fixed_template_binding_resolves_and_cleans_up(tmp_path: Path):
    store = _store(tmp_path)
    payload_ref = _payload_ref()

    assert store.resolve_template(payload_ref) is None
    store.bind_test_template(payload_ref)
    assert store.resolve_template(payload_ref) == push_mod.PushTemplate(
        title=runtime_mod.TEST_TITLE,
        body=runtime_mod.TEST_BODY,
        url="/house-hq",
    )

    store.discard_template(payload_ref)
    assert store.resolve_template(payload_ref) is None
    store.discard_template(payload_ref)


def test_template_binding_rejects_tamper_and_resealed_non_allowlisted_template(
    tmp_path: Path,
):
    store = _store(tmp_path)
    first_ref = _payload_ref(1)
    store.bind_test_template(first_ref)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE notification_push_templates SET created_at=created_at+1"
        )
    with pytest.raises(runtime_mod.WebPushRuntimeError, match="binding is corrupt"):
        store.resolve_template(first_ref)

    second_ref = _payload_ref(10)
    store.bind_test_template(second_ref)
    second_ref_hmac = runtime_mod._domain_hmac(
        SEAL_KEY, runtime_mod._REF_DOMAIN, second_ref.value
    )
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT ref_hmac,created_at FROM notification_push_templates "
            "WHERE ref_hmac=?",
            (second_ref_hmac,),
        ).fetchone()
        assert row is not None
        material = {
            "ref_hmac": row["ref_hmac"],
            "template_id": "creator_supplied_text",
            "created_at": row["created_at"],
        }
        row_seal = runtime_mod._domain_hmac(
            SEAL_KEY,
            runtime_mod._ROW_DOMAIN,
            runtime_mod._canonical(material),
        )
        conn.execute(
            "UPDATE notification_push_templates SET template_id=?,row_seal=? "
            "WHERE ref_hmac=?",
            ("creator_supplied_text", row_seal, row["ref_hmac"]),
        )
    with pytest.raises(runtime_mod.WebPushRuntimeError, match="not allowlisted"):
        store.resolve_template(second_ref)


def test_receipt_binds_event_subscription_and_transport_without_storing_bearers(
    tmp_path: Path,
):
    store = _store(tmp_path)
    subscription_id = "wps_" + "a" * 32
    receipt = store.issue_ack_receipt(
        event_id=EVENT_ID,
        subscription_id=subscription_id,
        transport_idempotency_key=TRANSPORT_KEY,
    )
    second_receipt = store.issue_ack_receipt(
        event_id=EVENT_ID,
        subscription_id=subscription_id,
        transport_idempotency_key="txi_" + "4" * 64,
    )

    assert receipt.startswith("wpa_") and len(receipt) == 47
    assert receipt != second_receipt
    assert store.verify_ack_receipt(event_id=EVENT_ID, receipt=receipt) is True
    assert store.verify_ack_receipt(event_id=OTHER_EVENT_ID, receipt=receipt) is False
    assert store.verify_ack_receipt(event_id=EVENT_ID, receipt="invalid") is False

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM notification_push_ack_receipts ORDER BY rowid"
        ).fetchall()
    assert rows[0]["event_id"] == EVENT_ID
    assert rows[0]["subscription_id"] == subscription_id
    assert rows[0]["receipt_hmac"] != receipt
    assert rows[0]["transport_hmac"] != TRANSPORT_KEY
    assert rows[0]["transport_hmac"] != rows[1]["transport_hmac"]


def test_receipt_is_expiring_and_one_use(tmp_path: Path):
    clock = MutableClock(500.0)
    store = _store(tmp_path, clock=clock)
    subscription_id = "wps_" + "b" * 32
    receipt = store.issue_ack_receipt(
        event_id=EVENT_ID,
        subscription_id=subscription_id,
        transport_idempotency_key=TRANSPORT_KEY,
    )

    clock.value = 500.0 + runtime_mod.ACK_TTL_SECONDS - 0.001
    assert store.verify_ack_receipt(event_id=EVENT_ID, receipt=receipt) is True
    assert store.reserve_ack_receipt(event_id=EVENT_ID, receipt=receipt) is True
    assert store.consume_ack_receipt(event_id=EVENT_ID, receipt=receipt) is True
    assert store.verify_ack_receipt(event_id=EVENT_ID, receipt=receipt) is False
    assert store.reserve_ack_receipt(event_id=EVENT_ID, receipt=receipt) is False
    assert store.consume_ack_receipt(event_id=EVENT_ID, receipt=receipt) is False

    clock.value = 1_000.0
    expired = store.issue_ack_receipt(
        event_id=OTHER_EVENT_ID,
        subscription_id=subscription_id,
        transport_idempotency_key="txi_" + "5" * 64,
    )
    clock.value = 1_000.0 + runtime_mod.ACK_TTL_SECONDS
    assert store.verify_ack_receipt(event_id=OTHER_EVENT_ID, receipt=expired) is False
    assert store.reserve_ack_receipt(event_id=OTHER_EVENT_ID, receipt=expired) is False
    assert store.consume_ack_receipt(event_id=OTHER_EVENT_ID, receipt=expired) is False


def test_reserved_receipt_recovers_after_reopen_and_original_expiry(tmp_path: Path):
    clock = MutableClock(1_000.0)
    store = _store(tmp_path, clock=clock)
    receipt = store.issue_ack_receipt(
        event_id=EVENT_ID,
        subscription_id="wps_" + "e" * 32,
        transport_idempotency_key=TRANSPORT_KEY,
    )
    assert store.reserve_ack_receipt(event_id=EVENT_ID, receipt=receipt) is True

    clock.value += runtime_mod.ACK_TTL_SECONDS + 1.0
    recovered = _store(tmp_path, clock=clock)

    assert recovered.verify_ack_receipt(event_id=EVENT_ID, receipt=receipt) is True
    assert recovered.reserve_ack_receipt(event_id=EVENT_ID, receipt=receipt) is True
    assert recovered.consume_ack_receipt(event_id=EVENT_ID, receipt=receipt) is True
    assert recovered.verify_ack_receipt(event_id=EVENT_ID, receipt=receipt) is False
    assert recovered.consume_ack_receipt(event_id=EVENT_ID, receipt=receipt) is False


def test_pre_reservation_receipt_row_is_upgraded_when_reserved(tmp_path: Path):
    store = _store(tmp_path)
    receipt = store.issue_ack_receipt(
        event_id=EVENT_ID,
        subscription_id="wps_" + "f" * 32,
        transport_idempotency_key=TRANSPORT_KEY,
    )
    receipt_hmac = runtime_mod._domain_hmac(
        SEAL_KEY, runtime_mod._RECEIPT_DOMAIN, receipt
    )
    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM notification_push_ack_receipts WHERE receipt_hmac=?",
            (receipt_hmac,),
        ).fetchone()
        assert row is not None
        legacy_material = {
            "receipt_hmac": row["receipt_hmac"],
            "event_id": row["event_id"],
            "subscription_id": row["subscription_id"],
            "transport_hmac": row["transport_hmac"],
            "expires_at": row["expires_at"],
            "consumed_at": row["consumed_at"],
        }
        legacy_seal = runtime_mod._domain_hmac(
            SEAL_KEY,
            runtime_mod._ROW_DOMAIN,
            runtime_mod._canonical(legacy_material),
        )
        conn.execute(
            "UPDATE notification_push_ack_receipts SET row_seal=? "
            "WHERE receipt_hmac=?",
            (legacy_seal, receipt_hmac),
        )

    assert store.verify_ack_receipt(event_id=EVENT_ID, receipt=receipt) is True
    assert store.reserve_ack_receipt(event_id=EVENT_ID, receipt=receipt) is True
    assert store.consume_ack_receipt(event_id=EVENT_ID, receipt=receipt) is True


@pytest.mark.parametrize(
    ("column", "tampered_value", "verified_event"),
    (
        ("event_id", OTHER_EVENT_ID, OTHER_EVENT_ID),
        ("subscription_id", "wps_" + "c" * 32, EVENT_ID),
        ("transport_hmac", "0" * 64, EVENT_ID),
        ("reserved_at", 123.0, EVENT_ID),
        ("row_seal", "0" * 64, EVENT_ID),
    ),
)
def test_receipt_row_tampering_fails_closed(
    tmp_path: Path,
    column: str,
    tampered_value: str,
    verified_event: str,
):
    store = _store(tmp_path)
    receipt = store.issue_ack_receipt(
        event_id=EVENT_ID,
        subscription_id="wps_" + "d" * 32,
        transport_idempotency_key=TRANSPORT_KEY,
    )
    assert column in {
        "event_id",
        "subscription_id",
        "transport_hmac",
        "reserved_at",
        "row_seal",
    }
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            f"UPDATE notification_push_ack_receipts SET {column}=?",
            (tampered_value,),
        )

    with pytest.raises(runtime_mod.WebPushRuntimeError, match="row is corrupt"):
        store.verify_ack_receipt(event_id=verified_event, receipt=receipt)


def test_vapid_material_is_created_reloaded_and_kept_out_of_repr():
    record = FakeCredentialRecord()
    created = runtime_mod.load_or_create_vapid(record)

    assert record.writes == [created.private_key]
    assert len(base64.urlsafe_b64decode(created.private_key + "=")) == 32
    public = base64.urlsafe_b64decode(created.public_key + "=")
    assert len(public) == 65 and public[0] == 4
    assert created.private_key not in repr(created)

    reloaded = runtime_mod.load_or_create_vapid(record)
    assert reloaded == created
    assert len(record.writes) == 1


@pytest.mark.parametrize("malformed", ("", "short", "not-base64!!!", "\ud800"))
def test_vapid_material_rejects_malformed_protected_values(malformed: str):
    with pytest.raises(runtime_mod.WebPushRuntimeError, match="VAPID key is malformed"):
        runtime_mod.load_or_create_vapid(FakeCredentialRecord(malformed))


def test_protected_secret_is_created_persisted_and_reloaded():
    record = FakeCredentialRecord()
    created = runtime_mod.load_or_create_protected_secret(record)

    assert len(created.encode("utf-8")) >= 32
    assert record.writes == [created]
    assert record.read() == created
    assert runtime_mod.load_or_create_protected_secret(record) == created
    assert record.writes == [created]


@pytest.mark.parametrize(
    "create",
    (
        runtime_mod.load_or_create_protected_secret,
        runtime_mod.load_or_create_vapid,
    ),
    ids=("credential-secret", "vapid-key"),
)
def test_named_mutex_serializes_first_use_creation_across_instances(create):
    kernel = _FakeNamedMutexKernel()
    api = _FakeWin32Api()
    name = "Local\\Alpecca.NotificationRuntimeInitialization.Test"
    mutexes = (
        anchor_mod.WindowsNamedMutex(
            name,
            win32event_module=kernel,
            win32api_module=api,
        ),
        anchor_mod.WindowsNamedMutex(
            name,
            win32event_module=kernel,
            win32api_module=api,
        ),
    )
    first_read = threading.Event()
    release_first_read = threading.Event()
    second_attempted = threading.Event()
    second_finished = threading.Event()

    class BlockingFirstReadRecord(FakeCredentialRecord):
        def read(self) -> str | None:
            self.read_count += 1
            if self.value is None and not first_read.is_set():
                first_read.set()
                assert release_first_read.wait(timeout=5.0)
            return self.value  # type: ignore[return-value]

    record = BlockingFirstReadRecord()
    results: list[object] = []
    failures: list[BaseException] = []

    def initialize(mutex, *, attempted=None, finished=None) -> None:
        if attempted is not None:
            attempted.set()
        try:
            with mutex.locked(timeout_ms=2_000):
                results.append(create(record))
        except BaseException as exc:
            failures.append(exc)
        finally:
            if finished is not None:
                finished.set()

    first = threading.Thread(target=initialize, args=(mutexes[0],))
    second = threading.Thread(
        target=initialize,
        args=(mutexes[1],),
        kwargs={"attempted": second_attempted, "finished": second_finished},
    )
    first.start()
    assert first_read.wait(timeout=2.0)
    second.start()
    assert second_attempted.wait(timeout=2.0)
    try:
        assert not second_finished.wait(timeout=0.05)
    finally:
        release_first_read.set()
    for thread in (first, second):
        thread.join(timeout=5.0)
        assert not thread.is_alive()

    assert failures == []
    assert len(record.writes) == 1
    assert results[0] == results[1]


@pytest.mark.parametrize("malformed", ("too-short", b"x" * 64, 42))
def test_protected_secret_rejects_malformed_values(malformed: object):
    with pytest.raises(runtime_mod.WebPushRuntimeError, match="secret is malformed"):
        runtime_mod.load_or_create_protected_secret(
            FakeCredentialRecord(malformed)
        )


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeWebPushException(Exception):
    def __init__(self, response: FakeResponse | None = None) -> None:
        super().__init__("synthetic Web Push failure")
        self.response = response


class FakeRequestsSession:
    instances: list["FakeRequestsSession"] = []

    def __init__(self) -> None:
        self.trust_env = True
        self.posts: list[dict[str, object]] = []
        self.instances.append(self)

    def post(self, url: str, *args: object, **kwargs: object) -> FakeResponse:
        self.posts.append({"url": url, "args": args, **kwargs})
        return FakeResponse(302)


def _install_transport_fakes(monkeypatch, webpush):
    FakeRequestsSession.instances.clear()
    requests_module = types.ModuleType("requests")
    requests_module.Session = FakeRequestsSession  # type: ignore[attr-defined]
    pywebpush_module = types.ModuleType("pywebpush")
    pywebpush_module.WebPushException = FakeWebPushException  # type: ignore[attr-defined]
    pywebpush_module.webpush = webpush  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "requests", requests_module)
    monkeypatch.setitem(sys.modules, "pywebpush", pywebpush_module)


def _transport(timeout_seconds: float = 8.0) -> runtime_mod.PyWebPushTransport:
    return runtime_mod.PyWebPushTransport(
        runtime_mod.VapidMaterial(
            private_key="private-vapid-key", public_key="public-vapid-key"
        ),
        timeout_seconds=timeout_seconds,
    )


@pytest.mark.parametrize("status_code", (201, 202))
def test_transport_accepts_provider_success_and_uses_bounded_fixed_request(
    monkeypatch,
    status_code: int,
):
    calls: list[dict[str, object]] = []

    def webpush(**kwargs):
        calls.append(kwargs)
        return FakeResponse(status_code)

    _install_transport_fakes(monkeypatch, webpush)
    payload = {"version": 1, "title": "Alpecca", "body": "Connected"}
    result = _transport(timeout_seconds=7.5).send(
        subscription=_push_subscription(),
        payload=payload,
        transport_idempotency_key=TRANSPORT_KEY,
    )

    assert result == push_mod.PushTransportResult(push_mod.ACCEPTED)
    assert len(calls) == 1
    call = calls[0]
    assert json.loads(str(call["data"])) == payload
    assert call["timeout"] == 7.5
    assert call["ttl"] == 300
    assert call["vapid_claims"] == {"sub": "mailto:creator@alpecca.local"}
    assert call["headers"]["Urgency"] == "normal"  # type: ignore[index]
    assert TRANSPORT_KEY not in str(call["headers"])
    session = call["requests_session"]
    assert isinstance(session, FakeRequestsSession)
    assert session.trust_env is False


@pytest.mark.parametrize(
    ("status_code", "outcome", "stale"),
    (
        (400, push_mod.REJECTED, False),
        (404, push_mod.REJECTED, True),
        (410, push_mod.REJECTED, True),
        (302, push_mod.UNKNOWN, False),
        (408, push_mod.UNKNOWN, False),
        (425, push_mod.UNKNOWN, False),
        (429, push_mod.UNKNOWN, False),
        (500, push_mod.UNKNOWN, False),
        (503, push_mod.UNKNOWN, False),
    ),
)
def test_transport_classifies_only_definitive_client_rejections_as_rejected(
    monkeypatch,
    status_code: int,
    outcome: str,
    stale: bool,
):
    _install_transport_fakes(monkeypatch, lambda **_kwargs: FakeResponse(status_code))

    result = _transport().send(
        subscription=_push_subscription(),
        payload={"version": 1},
        transport_idempotency_key=TRANSPORT_KEY,
    )

    assert result.outcome == outcome
    assert result.stale_subscription is stale


@pytest.mark.parametrize(
    ("response", "outcome", "stale"),
    (
        (None, push_mod.UNKNOWN, False),
        (FakeResponse(400), push_mod.REJECTED, False),
        (FakeResponse(410), push_mod.REJECTED, True),
        (FakeResponse(408), push_mod.UNKNOWN, False),
        (FakeResponse(425), push_mod.UNKNOWN, False),
        (FakeResponse(429), push_mod.UNKNOWN, False),
        (FakeResponse(500), push_mod.UNKNOWN, False),
    ),
)
def test_transport_classifies_pywebpush_exceptions(
    monkeypatch,
    response: FakeResponse | None,
    outcome: str,
    stale: bool,
):
    def webpush(**_kwargs):
        raise FakeWebPushException(response)

    _install_transport_fakes(monkeypatch, webpush)
    result = _transport().send(
        subscription=_push_subscription(),
        payload={"version": 1},
        transport_idempotency_key=TRANSPORT_KEY,
    )

    assert result.outcome == outcome
    assert result.stale_subscription is stale


@pytest.mark.parametrize("response", (None, object(), FakeResponse(204)))
def test_transport_treats_missing_or_nondefinitive_response_as_unknown(
    monkeypatch,
    response: object,
):
    _install_transport_fakes(monkeypatch, lambda **_kwargs: response)

    result = _transport().send(
        subscription=_push_subscription(),
        payload={"version": 1},
        transport_idempotency_key=TRANSPORT_KEY,
    )

    assert result == push_mod.PushTransportResult(push_mod.UNKNOWN)


def test_transport_disables_redirects_and_proxy_environment(monkeypatch):
    captured: dict[str, object] = {}

    def webpush(**kwargs):
        session = kwargs["requests_session"]
        captured["session"] = session
        return session.post(
            "https://fcm.googleapis.com/redirect",
            data="ciphertext",
            allow_redirects=True,
        )

    _install_transport_fakes(monkeypatch, webpush)
    result = _transport().send(
        subscription=_push_subscription(),
        payload={"version": 1},
        transport_idempotency_key=TRANSPORT_KEY,
    )

    assert result == push_mod.PushTransportResult(push_mod.UNKNOWN)
    session = captured["session"]
    assert isinstance(session, FakeRequestsSession)
    assert session.trust_env is False
    assert session.posts == [
        {
            "url": "https://fcm.googleapis.com/redirect",
            "args": (),
            "data": "ciphertext",
            "allow_redirects": False,
        }
    ]


def test_transport_timeout_is_indeterminate_and_does_not_retry(monkeypatch):
    calls = 0

    def webpush(**kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["timeout"] == 6.0
        assert kwargs["requests_session"].trust_env is False
        raise TimeoutError("synthetic timeout")

    _install_transport_fakes(monkeypatch, webpush)
    result = _transport(timeout_seconds=6.0).send(
        subscription=_push_subscription(),
        payload={"version": 1},
        transport_idempotency_key=TRANSPORT_KEY,
    )

    assert result == push_mod.PushTransportResult(push_mod.UNKNOWN)
    assert calls == 1


def test_transport_rejects_oversized_payload_before_loading_network_clients(
    monkeypatch,
):
    monkeypatch.setitem(sys.modules, "requests", None)
    monkeypatch.setitem(sys.modules, "pywebpush", None)
    with pytest.raises(runtime_mod.WebPushRuntimeError, match="payload exceeds"):
        _transport().send(
            subscription=_push_subscription(),
            payload={"body": "x" * 2048},
            transport_idempotency_key=TRANSPORT_KEY,
        )


def test_enqueue_connection_test_discards_template_when_enqueue_fails(
    tmp_path: Path,
):
    payload_ref = _payload_ref()

    class FailingOutbox:
        def __init__(self) -> None:
            self.enqueue_kwargs: dict[str, object] | None = None

        def mint_payload_ref(self) -> outbox_mod.OpaquePayloadRef:
            return payload_ref

        def enqueue(self, **kwargs: object) -> dict[str, object]:
            self.enqueue_kwargs = kwargs
            raise RuntimeError("synthetic enqueue failure")

    outbox = FailingOutbox()
    store = _store(tmp_path)
    with pytest.raises(RuntimeError, match="synthetic enqueue failure"):
        runtime_mod.enqueue_connection_test(outbox, store)  # type: ignore[arg-type]

    assert store.resolve_template(payload_ref) is None
    assert outbox.enqueue_kwargs is not None
    assert outbox.enqueue_kwargs["category"] == runtime_mod.TEST_TEMPLATE
    assert outbox.enqueue_kwargs["adapter_name"] == push_mod.ADAPTER_NAME
    assert outbox.enqueue_kwargs["payload_ref"] is payload_ref
    assert str(outbox.enqueue_kwargs["idempotency_key"]).startswith("idem_")
