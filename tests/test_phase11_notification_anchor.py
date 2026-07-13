from __future__ import annotations

import hashlib
import hmac
import json
import threading
from contextlib import contextmanager
from dataclasses import replace

import pytest

from alpecca import notification_anchor as anchor_mod
from alpecca import notification_outbox as outbox_mod


ANCHOR_KEY = b"phase11-notification-anchor-test-key"
_NO_OVERRIDE = object()


class InMemoryAtomicCredentialBackend:
    def __init__(self, value: str | None = None) -> None:
        self._lock = threading.RLock()
        self.value = value
        self.write_count = 0
        self.read_count = 0
        self.read_override: object | str | None = _NO_OVERRIDE
        self.read_override_after_write: object | str | None = _NO_OVERRIDE
        self.read_error: BaseException | None = None

    @contextmanager
    def locked(self):
        with self._lock:
            yield self

    def read(self) -> str | None:
        self.read_count += 1
        if self.read_error is not None:
            raise self.read_error
        if self.read_override is not _NO_OVERRIDE:
            value = self.read_override
            self.read_override = _NO_OVERRIDE
            return value  # type: ignore[return-value]
        return self.value

    def write(self, value: str) -> None:
        self.write_count += 1
        self.value = value
        if self.read_override_after_write is not _NO_OVERRIDE:
            self.read_override = self.read_override_after_write
            self.read_override_after_write = _NO_OVERRIDE

    def replace_out_of_band(self, value: str | None) -> None:
        with self._lock:
            self.value = value


def _checkpoint(
    sequence: int,
    *,
    event_count: int | None = None,
    head_character: str = "a",
    meta_character: str = "b",
) -> outbox_mod.LedgerCheckpoint:
    return outbox_mod.LedgerCheckpoint(
        ledger_id="ledger_" + "1" * 32,
        contract_version=outbox_mod.CONTRACT_VERSION,
        policy_id="phase11_anchor_test",
        policy_version=1,
        policy_digest="2" * 64,
        sequence=sequence,
        event_count=sequence if event_count is None else event_count,
        receipt_count=sequence,
        global_head_seal="" if sequence == 0 else head_character * 64,
        meta_seal=meta_character * 64,
    )


def _anchor(
    backend: InMemoryAtomicCredentialBackend,
) -> anchor_mod.CredentialMonotonicAnchor:
    return anchor_mod.CredentialMonotonicAnchor(
        backend,
        anchor_key=ANCHOR_KEY,
    )


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _reseal(document: dict[str, object]) -> str:
    material = {
        "format_version": document["format_version"],
        "current": document["current"],
        "pending": document["pending"],
    }
    sealed = {
        **document,
        "seal": hmac.new(
            ANCHOR_KEY,
            _canonical(
                {"domain": anchor_mod._ANCHOR_DOMAIN, **material}
            ).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest(),
    }
    return _canonical(sealed)


def _initialize_current(
    anchor: anchor_mod.CredentialMonotonicAnchor,
) -> outbox_mod.LedgerCheckpoint:
    initial = _checkpoint(0)
    anchor.prepare(None, initial)
    anchor.commit(initial)
    return initial


def test_empty_record_initializes_once_as_exact_canonical_sealed_json():
    backend = InMemoryAtomicCredentialBackend()
    anchor = _anchor(backend)

    assert isinstance(anchor, outbox_mod.MonotonicAnchor)
    assert anchor.snapshot() == outbox_mod.AnchorSnapshot(None, None)
    assert backend.write_count == 1
    assert backend.value is not None
    document = json.loads(backend.value)
    assert set(document) == {"format_version", "current", "pending", "seal"}
    assert document["format_version"] == anchor_mod.ANCHOR_FORMAT_VERSION
    assert document["current"] is None
    assert document["pending"] is None
    assert len(document["seal"]) == 64
    assert backend.value == _canonical(document)

    reopened = _anchor(backend)
    assert reopened.snapshot() == outbox_mod.AnchorSnapshot(None, None)
    assert backend.write_count == 1


def test_existing_non_anchor_credential_is_never_overwritten():
    backend = InMemoryAtomicCredentialBackend("existing unrelated credential")

    with pytest.raises(
        anchor_mod.NotificationAnchorUnavailable,
        match="refusing overwrite",
    ):
        _anchor(backend)

    assert backend.value == "existing unrelated credential"
    assert backend.write_count == 0


@pytest.mark.parametrize("mutation", ["root_key", "checkpoint_key", "bool_count"])
def test_validly_resealed_records_still_require_exact_keys_and_types(mutation: str):
    backend = InMemoryAtomicCredentialBackend()
    anchor = _anchor(backend)
    _initialize_current(anchor)
    assert backend.value is not None
    document = json.loads(backend.value)

    if mutation == "root_key":
        document["extra"] = "not allowed"
    elif mutation == "checkpoint_key":
        document["current"]["extra"] = "not allowed"
    else:
        document["current"]["sequence"] = False
        document["current"]["receipt_count"] = False
    backend.replace_out_of_band(_reseal(document))
    writes_before = backend.write_count

    with pytest.raises(anchor_mod.NotificationAnchorUnavailable, match="corrupt"):
        _anchor(backend)

    assert backend.write_count == writes_before


@pytest.mark.parametrize("tamper", ["hmac", "noncanonical"])
def test_tamper_fails_closed_and_remains_closed_after_record_restore(tamper: str):
    backend = InMemoryAtomicCredentialBackend()
    anchor = _anchor(backend)
    _initialize_current(anchor)
    original = backend.value
    assert original is not None
    if tamper == "hmac":
        document = json.loads(original)
        document["current"]["meta_seal"] = "f" * 64
        backend.replace_out_of_band(_canonical(document))
    else:
        backend.replace_out_of_band(original + " ")

    with pytest.raises(anchor_mod.NotificationAnchorUnavailable, match="corrupt"):
        anchor.snapshot()

    backend.replace_out_of_band(original)
    with pytest.raises(anchor_mod.NotificationAnchorUnavailable, match="unavailable"):
        anchor.snapshot()


@pytest.mark.parametrize("failure", ["missing", "unavailable"])
def test_missing_or_unavailable_record_after_initialization_fails_closed(
    failure: str,
):
    backend = InMemoryAtomicCredentialBackend()
    anchor = _anchor(backend)
    if failure == "missing":
        backend.replace_out_of_band(None)
    else:
        backend.read_error = OSError("credential service offline")

    with pytest.raises(anchor_mod.NotificationAnchorUnavailable):
        anchor.snapshot()

    if failure == "missing":
        backend.replace_out_of_band(_canonical({}))
    else:
        backend.read_error = None
    with pytest.raises(anchor_mod.NotificationAnchorUnavailable, match="unavailable"):
        anchor.snapshot()


def test_pending_state_recovers_across_instances_and_commit_abort_are_idempotent():
    backend = InMemoryAtomicCredentialBackend()
    first = _anchor(backend)
    initial = _checkpoint(0)
    first.prepare(None, initial)

    recovering = _anchor(backend)
    assert recovering.snapshot() == outbox_mod.AnchorSnapshot(None, initial)
    recovering.commit(initial)
    recovering.commit(initial)
    recovering.abort(initial)
    assert recovering.snapshot() == outbox_mod.AnchorSnapshot(initial, None)

    successor = _checkpoint(1, head_character="c", meta_character="d")
    recovering.prepare(initial, successor)
    another_process = _anchor(backend)
    assert another_process.snapshot().pending == successor
    another_process.abort(successor)
    another_process.abort(successor)
    assert another_process.snapshot() == outbox_mod.AnchorSnapshot(initial, None)


def test_credential_anchor_initializes_advances_and_reopens_real_outbox(tmp_path):
    backend = InMemoryAtomicCredentialBackend()
    anchor = _anchor(backend)
    policy = outbox_mod.OutboxPolicy(
        policy_id="phase11_anchor_integration",
        policy_version=1,
        category_registry=frozenset({"reminder"}),
        adapter_registry=frozenset({"app_push"}),
        category_quotas={"reminder": None},
        channel_quotas={"app_push": None},
        channel_costs={"app_push": 0},
        adapter_transport_idempotency={"app_push": True},
    )
    db_path = tmp_path / "notification-outbox.sqlite3"
    store = outbox_mod.NotificationOutbox(
        db_path,
        seal_key=b"notification-outbox-integration-seal-key",
        policy=policy,
        anchor=anchor,
    )
    store.enqueue(
        idempotency_key="idem_" + "1" * 32,
        category="reminder",
        adapter_name="app_push",
        payload_ref=store.mint_payload_ref(),
    )

    snapshot = anchor.snapshot()
    assert snapshot.pending is None
    assert snapshot.current is not None
    assert snapshot.current.sequence == 1
    assert snapshot.current.event_count == 1
    reopened_anchor = _anchor(backend)
    reopened = outbox_mod.NotificationOutbox(
        db_path,
        seal_key=b"notification-outbox-integration-seal-key",
        policy=policy,
        anchor=reopened_anchor,
    )
    assert reopened.audit() == {"verified": True, "events": 1, "receipts": 1}


def test_monotonic_validation_matches_outbox_identity_and_counter_contract():
    backend = InMemoryAtomicCredentialBackend()
    anchor = _anchor(backend)
    initial = _initialize_current(anchor)
    unchanged = backend.value

    invalid = (
        replace(initial, meta_seal="c" * 64),
        replace(initial, contract_version=2.0),
        replace(
            _checkpoint(1),
            ledger_id="ledger_" + "9" * 32,
        ),
        replace(_checkpoint(1), receipt_count=0),
    )
    for candidate in invalid:
        with pytest.raises(outbox_mod.OutboxAnchorError):
            anchor.prepare(initial, candidate)
        assert backend.value == unchanged
        assert anchor.snapshot() == outbox_mod.AnchorSnapshot(initial, None)


def test_concurrent_prepare_is_compare_under_one_backend_lock():
    backend = InMemoryAtomicCredentialBackend()
    first = _anchor(backend)
    second = _anchor(backend)
    initial = _initialize_current(first)
    candidates = (
        _checkpoint(1, head_character="3", meta_character="4"),
        _checkpoint(1, head_character="5", meta_character="6"),
    )
    barrier = threading.Barrier(3)
    results: list[tuple[str, outbox_mod.LedgerCheckpoint]] = []
    result_lock = threading.Lock()

    def prepare(
        anchor: anchor_mod.CredentialMonotonicAnchor,
        candidate: outbox_mod.LedgerCheckpoint,
    ) -> None:
        barrier.wait()
        try:
            anchor.prepare(initial, candidate)
        except outbox_mod.OutboxAnchorError:
            result = ("rejected", candidate)
        else:
            result = ("prepared", candidate)
        with result_lock:
            results.append(result)

    threads = [
        threading.Thread(target=prepare, args=(first, candidates[0])),
        threading.Thread(target=prepare, args=(second, candidates[1])),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert sorted(result for result, _candidate in results) == [
        "prepared",
        "rejected",
    ]
    winner = next(candidate for result, candidate in results if result == "prepared")
    assert first.snapshot() == outbox_mod.AnchorSnapshot(initial, winner)
    assert second.snapshot() == outbox_mod.AnchorSnapshot(initial, winner)


def test_observed_sealed_rollback_is_rejected():
    backend = InMemoryAtomicCredentialBackend()
    anchor = _anchor(backend)
    initial = _initialize_current(anchor)
    old_record = backend.value
    successor = _checkpoint(1, head_character="7", meta_character="8")
    anchor.prepare(initial, successor)
    anchor.commit(successor)
    assert anchor.snapshot().current == successor

    backend.replace_out_of_band(old_record)
    with pytest.raises(anchor_mod.NotificationAnchorUnavailable, match="rolled back"):
        anchor.snapshot()


def test_write_readback_mismatch_fails_closed():
    backend = InMemoryAtomicCredentialBackend()
    anchor = _anchor(backend)
    initial = _initialize_current(anchor)
    successor = _checkpoint(1, head_character="9", meta_character="a")
    backend.read_override_after_write = "{}"

    with pytest.raises(anchor_mod.NotificationAnchorUnavailable, match="readback"):
        anchor.prepare(initial, successor)
    with pytest.raises(anchor_mod.NotificationAnchorUnavailable, match="unavailable"):
        anchor.snapshot()


class FakeWindowsError(Exception):
    def __init__(self, winerror: int, message: str) -> None:
        super().__init__(winerror, message)
        self.winerror = winerror


class FakeWin32Cred:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.read_targets: list[str] = []
        self.writes: list[dict[str, object]] = []

    def CredRead(self, target: str, cred_type: int, flags: int = 0) -> dict:
        self.read_targets.append(target)
        if target not in self.store:
            raise FakeWindowsError(1168, "Element not found")
        return {"CredentialBlob": self.store[target]}

    def CredWrite(self, credential: dict, flags: int = 0) -> None:
        blob = credential["CredentialBlob"]
        if type(blob) is not str:
            raise TypeError("pywin32 requires a string credential blob")
        self.writes.append(dict(credential))
        self.store[credential["TargetName"]] = blob.encode("utf-16-le")


class FakeMutexHandle:
    def __init__(self, name: str, lock: threading.RLock) -> None:
        self.name = name
        self.lock = lock


class FakeWin32Event:
    def __init__(self) -> None:
        self._registry_lock = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}
        self.created_names: list[str] = []

    def CreateMutex(self, security, initial_owner: bool, name: str):
        with self._registry_lock:
            lock = self._locks.setdefault(name, threading.RLock())
        self.created_names.append(name)
        return FakeMutexHandle(name, lock)

    @staticmethod
    def WaitForSingleObject(handle: FakeMutexHandle, timeout_ms: int) -> int:
        if handle.lock.acquire(timeout=timeout_ms / 1000):
            return 0
        return 0x102

    @staticmethod
    def ReleaseMutex(handle: FakeMutexHandle) -> None:
        handle.lock.release()


class FakeWin32Api:
    def __init__(self) -> None:
        self.closed: list[FakeMutexHandle] = []

    def CloseHandle(self, handle: FakeMutexHandle) -> None:
        self.closed.append(handle)


def _windows_backend(
    target: str,
    credential: FakeWin32Cred,
    event: FakeWin32Event,
    api: FakeWin32Api,
) -> anchor_mod.WindowsCredentialManagerBackend:
    return anchor_mod.WindowsCredentialManagerBackend(
        target,
        win32cred_module=credential,
        win32event_module=event,
        win32api_module=api,
    )


def test_windows_backend_is_constructor_inert_and_uses_only_exact_target():
    credential = FakeWin32Cred()
    event = FakeWin32Event()
    api = FakeWin32Api()
    target = "Alpecca/NotificationAnchor/TestDedicatedTarget"
    backend = _windows_backend(target, credential, event, api)

    assert credential.read_targets == []
    assert credential.writes == []
    assert event.created_names == []
    anchor = anchor_mod.CredentialMonotonicAnchor(
        backend,
        anchor_key=ANCHOR_KEY,
    )

    assert anchor.snapshot() == outbox_mod.AnchorSnapshot(None, None)
    assert credential.read_targets and set(credential.read_targets) == {target}
    assert len(credential.writes) == 1
    assert credential.writes[0]["TargetName"] == target
    assert type(credential.writes[0]["CredentialBlob"]) is str
    assert all(name == backend.mutex_name for name in event.created_names)
    assert backend.mutex_name.startswith("Local\\Alpecca.NotificationAnchor.")
    assert len(api.closed) == len(event.created_names)


def test_windows_backend_reuses_named_mutex_across_instances_for_prepare_race():
    credential = FakeWin32Cred()
    event = FakeWin32Event()
    api = FakeWin32Api()
    target = "Alpecca/NotificationAnchor/MutexRace"
    backend_one = _windows_backend(target, credential, event, api)
    backend_two = _windows_backend(target, credential, event, api)
    assert backend_one.mutex_name == backend_two.mutex_name
    first = anchor_mod.CredentialMonotonicAnchor(
        backend_one, anchor_key=ANCHOR_KEY
    )
    second = anchor_mod.CredentialMonotonicAnchor(
        backend_two, anchor_key=ANCHOR_KEY
    )
    initial = _initialize_current(first)
    candidates = (
        _checkpoint(1, head_character="b", meta_character="c"),
        _checkpoint(1, head_character="d", meta_character="e"),
    )
    barrier = threading.Barrier(3)
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def race(anchor, candidate) -> None:
        barrier.wait()
        try:
            anchor.prepare(initial, candidate)
        except outbox_mod.OutboxAnchorError:
            outcome = "rejected"
        else:
            outcome = "prepared"
        with outcomes_lock:
            outcomes.append(outcome)

    threads = [
        threading.Thread(target=race, args=(first, candidates[0])),
        threading.Thread(target=race, args=(second, candidates[1])),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()

    assert sorted(outcomes) == ["prepared", "rejected"]
    assert first.snapshot().pending in candidates


def test_windows_existing_malformed_target_is_read_but_never_changed():
    credential = FakeWin32Cred()
    event = FakeWin32Event()
    api = FakeWin32Api()
    target = "Alpecca/NotificationAnchor/ExistingMalformed"
    credential.store[target] = "unrelated data".encode("utf-16-le")
    original = credential.store[target]
    backend = _windows_backend(target, credential, event, api)

    with pytest.raises(anchor_mod.NotificationAnchorUnavailable):
        anchor_mod.CredentialMonotonicAnchor(
            backend,
            anchor_key=ANCHOR_KEY,
        )

    assert credential.store[target] == original
    assert credential.writes == []
    assert set(credential.read_targets) == {target}
