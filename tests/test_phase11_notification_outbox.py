from __future__ import annotations

import inspect
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest

from alpecca import notification_outbox as outbox_mod


SEAL_KEY = b"phase11-hardened-notification-outbox-test-seal-key"


class MutableClock:
    def __init__(self, value: float = 100.0) -> None:
        self._value = value
        self._sequence: list[float] = []
        self._calls = 0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            self._calls += 1
            if self._sequence:
                self._value = self._sequence.pop(0)
            return self._value

    @property
    def value(self) -> float:
        with self._lock:
            return self._value

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value
            self._sequence.clear()

    def set_sequence(self, values: list[float]) -> None:
        if not values:
            raise ValueError("clock sequence must not be empty")
        with self._lock:
            self._sequence = list(values)

    def reset_calls(self) -> None:
        with self._lock:
            self._calls = 0


class AdvancingCommitAnchor(outbox_mod.InMemoryMonotonicAnchor):
    def __init__(self, clock: MutableClock) -> None:
        super().__init__()
        self._clock = clock
        self.advance_on_commit = False

    def commit(self, candidate: outbox_mod.LedgerCheckpoint) -> None:
        super().commit(candidate)
        if self.advance_on_commit:
            self.advance_on_commit = False
            self._clock.set(self._clock.value + 11.0)


class PausingPrepareAnchor(outbox_mod.InMemoryMonotonicAnchor):
    def __init__(self) -> None:
        super().__init__()
        self.pause_next_prepare = False
        self.prepared = threading.Event()
        self.release = threading.Event()

    def prepare(
        self,
        expected: outbox_mod.LedgerCheckpoint | None,
        candidate: outbox_mod.LedgerCheckpoint,
    ) -> None:
        super().prepare(expected, candidate)
        if self.pause_next_prepare:
            self.pause_next_prepare = False
            self.prepared.set()
            if not self.release.wait(timeout=5.0):
                raise RuntimeError("test anchor prepare was not released")


class FailOnceCommitAnchor(outbox_mod.InMemoryMonotonicAnchor):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_commit = False

    def commit(self, candidate: outbox_mod.LedgerCheckpoint) -> None:
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise RuntimeError("simulated anchor commit interruption")
        super().commit(candidate)


class PausingStrictCommitAnchor(outbox_mod.InMemoryMonotonicAnchor):
    """Simulate an anchor whose commit is not itself idempotent."""

    def __init__(self) -> None:
        super().__init__()
        self.pause_next_commit = False
        self.original_waiting = threading.Event()
        self.release_original = threading.Event()

    def commit(self, candidate: outbox_mod.LedgerCheckpoint) -> None:
        if self.pause_next_commit:
            self.pause_next_commit = False
            self.original_waiting.set()
            if not self.release_original.wait(timeout=5.0):
                raise RuntimeError("test anchor commit was not released")
        with self._lock:
            if self._pending != candidate:
                raise outbox_mod.OutboxAnchorError(
                    "strict anchor pending checkpoint does not match"
                )
            self._current = candidate
            self._pending = None


def _policy(**overrides) -> outbox_mod.OutboxPolicy:
    values = {
        "policy_id": "phase11_test",
        "policy_version": 1,
        "category_registry": frozenset({"alert", "reminder", "routine"}),
        "adapter_registry": frozenset(
            {"app_push", "discord_dm", "non_idempotent_sms"}
        ),
        "category_quotas": {
            "alert": None,
            "reminder": None,
            "routine": None,
        },
        "channel_quotas": {
            "app_push": None,
            "discord_dm": None,
            "non_idempotent_sms": None,
        },
        "channel_costs": {
            "app_push": 0,
            "discord_dm": 0,
            "non_idempotent_sms": 1,
        },
        "adapter_transport_idempotency": {
            "app_push": True,
            "discord_dm": True,
            "non_idempotent_sms": False,
        },
        "max_attempts": 3,
        "lease_seconds": 10.0,
        "backoff_initial_seconds": 5.0,
        "backoff_multiplier": 2.0,
        "backoff_max_seconds": 60.0,
        "quota_window_seconds": 100.0,
        "accounting_timezone": "America/Los_Angeles",
    }
    values.update(overrides)
    return outbox_mod.OutboxPolicy(**values)


def _store(
    tmp_path: Path,
    *,
    anchor: outbox_mod.MonotonicAnchor | None = None,
    clock=None,
    policy: outbox_mod.OutboxPolicy | None = None,
    name: str = "outbox.db",
):
    return outbox_mod.NotificationOutbox(
        tmp_path / name,
        seal_key=SEAL_KEY,
        policy=policy or _policy(),
        anchor=anchor or outbox_mod.InMemoryMonotonicAnchor(),
        clock=clock or MutableClock(),
    )


def _idem(number: int) -> str:
    return f"idem_{number:032x}"


def _enqueue(
    store: outbox_mod.NotificationOutbox,
    number: int = 1,
    *,
    category: str = "reminder",
    adapter_name: str = "app_push",
    payload_ref: outbox_mod.OpaquePayloadRef | None = None,
):
    return store.enqueue(
        idempotency_key=_idem(number),
        category=category,
        adapter_name=adapter_name,
        payload_ref=payload_ref or store.mint_payload_ref(),
    )


def _receipt_rows(db_path: Path) -> list[dict[str, object]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM notification_outbox_receipts ORDER BY global_sequence"
            )
        ]


def _receipts(
    store: outbox_mod.NotificationOutbox,
    event_id: str,
) -> list[dict[str, object]]:
    receipts: list[dict[str, object]] = []
    cursor = None
    seen_cursors: set[str] = set()
    while True:
        page = store.transition_receipts(event_id, cursor=cursor)
        assert set(page) == {"event_id", "receipts", "next_cursor"}
        assert page["event_id"] == event_id
        receipts.extend(page["receipts"])
        cursor = page["next_cursor"]
        if cursor is None:
            return receipts
        assert cursor not in seen_cursors
        seen_cursors.add(cursor)


def _tamper_rows(
    db_path: Path,
    *,
    drop_triggers: tuple[str, ...],
    statements: list[tuple[str, tuple[object, ...]]],
    disable_foreign_keys: bool = False,
) -> None:
    with sqlite3.connect(db_path) as conn:
        if disable_foreign_keys:
            conn.execute("PRAGMA foreign_keys=OFF")
        definitions = {
            name: conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
                (name,),
            ).fetchone()[0]
            for name in drop_triggers
        }
        for name in drop_triggers:
            conn.execute(f"DROP TRIGGER {name}")
        for statement, parameters in statements:
            conn.execute(statement, parameters)
        for name in drop_triggers:
            conn.execute(definitions[name])


def test_policy_maps_exactly_cover_closed_registries_and_aliases_are_rejected(tmp_path):
    with pytest.raises(outbox_mod.NotificationOutboxError, match="exactly cover"):
        _policy(
            category_quotas={"alert": None, "reminder": None},
        )
    with pytest.raises(outbox_mod.NotificationOutboxError, match="exactly cover"):
        _policy(
            adapter_transport_idempotency={
                "app_push": True,
                "discord_dm": True,
                "non_idempotent_sms": False,
                "alias": True,
            }
        )

    store = _store(tmp_path)
    ref = store.mint_payload_ref()
    event = store.enqueue(
        idempotency_key=_idem(1),
        category="reminder",
        adapter_name="app_push",
        payload_ref=ref,
    )
    assert event["state"] == outbox_mod.QUEUED

    for category in ("Reminder", "unknown", "reminder-v2"):
        with pytest.raises(outbox_mod.NotificationOutboxError):
            store.enqueue(
                idempotency_key=_idem(10 + len(category)),
                category=category,
                adapter_name="app_push",
                payload_ref=store.mint_payload_ref(),
            )
    for adapter in ("APP_PUSH", "push", "app-push"):
        with pytest.raises(outbox_mod.NotificationOutboxError):
            store.enqueue(
                idempotency_key=_idem(20 + len(adapter)),
                category="reminder",
                adapter_name=adapter,
                payload_ref=store.mint_payload_ref(),
            )


def test_constructor_dependencies_and_cached_policy_identity_are_read_only(tmp_path):
    policy = _policy()
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    clock = MutableClock(100.0)
    store = _store(tmp_path, policy=policy, anchor=anchor, clock=clock)
    digest = store._policy_digest

    replacements = {
        "policy": replace(policy, policy_version=2),
        "_policy_digest": "0" * 64,
        "_anchor": outbox_mod.InMemoryMonotonicAnchor(),
        "_clock": MutableClock(500.0),
    }
    for attribute, replacement in replacements.items():
        with pytest.raises(AttributeError):
            setattr(store, attribute, replacement)

    assert store.policy is policy
    assert store._policy_digest == digest == policy.digest
    assert store._anchor is anchor
    assert store._clock is clock
    assert {"policy", "_policy_digest", "_anchor", "_clock"}.isdisjoint(
        store.__dict__
    )
    assert _enqueue(store)["state"] == outbox_mod.QUEUED


def test_same_name_noop_table_quarantines_during_construction(tmp_path):
    db_path = tmp_path / "noop-table.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE notification_outbox_meta(singleton INTEGER)")

    with pytest.raises(outbox_mod.OutboxQuarantined, match="schema definitions"):
        outbox_mod.NotificationOutbox(
            db_path,
            seal_key=SEAL_KEY,
            policy=_policy(),
            anchor=outbox_mod.InMemoryMonotonicAnchor(),
            clock=MutableClock(),
        )


@pytest.mark.parametrize(
    ("drop_sql", "replacement_sql"),
    [
        (
            "DROP INDEX notification_outbox_due_idx",
            "CREATE INDEX notification_outbox_due_idx "
            "ON notification_outbox_events(event_id)",
        ),
        (
            "DROP TRIGGER notification_outbox_state_guard",
            "CREATE TRIGGER notification_outbox_state_guard "
            "AFTER INSERT ON notification_outbox_events BEGIN SELECT 1; END",
        ),
    ],
    ids=("index", "trigger"),
)
def test_same_name_noop_runtime_schema_object_quarantines_before_transition(
    tmp_path, drop_sql, replacement_sql
):
    store = _store(tmp_path)
    payload_ref = store.mint_payload_ref()
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(drop_sql)
        conn.execute(replacement_sql)

    with pytest.raises(outbox_mod.OutboxQuarantined, match="schema definitions"):
        store.enqueue(
            idempotency_key=_idem(1),
            category="reminder",
            adapter_name="app_push",
            payload_ref=payload_ref,
        )
    assert store.quarantined is True
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM notification_outbox_events"
        ).fetchone()[0] == 0


def test_reopen_with_missing_required_schema_object_fails_without_repair(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    policy = _policy()
    store = _store(tmp_path, anchor=anchor, policy=policy)
    _enqueue(store)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DROP INDEX notification_outbox_due_idx")

    with pytest.raises(outbox_mod.OutboxQuarantined, match="schema definitions"):
        _store(tmp_path, anchor=anchor, policy=policy)

    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='notification_outbox_due_idx'"
        ).fetchone() is None


def test_only_server_minted_content_free_refs_are_accepted_and_public_dtos_redact(tmp_path):
    store = _store(tmp_path)
    rejected = (
        "https://example.test/private?id=1",
        r"C:\private\note.txt",
        "cHJpdmF0ZS1wYXlsb2Fk",
        "+15551234567",
        "secret_api_key_value",
    )
    for index, raw in enumerate(rejected, start=1):
        with pytest.raises(outbox_mod.NotificationOutboxError, match="minted"):
            store.enqueue(
                idempotency_key=_idem(index),
                category="reminder",
                adapter_name="app_push",
                payload_ref=raw,  # type: ignore[arg-type]
            )
    with pytest.raises(outbox_mod.NotificationOutboxError, match="minted"):
        store.enqueue(
            idempotency_key=_idem(9),
            category="reminder",
            adapter_name="app_push",
            payload_ref=outbox_mod.OpaquePayloadRef(
                "pref_" + "1" * 32 + "_" + "2" * 32
            ),
        )
    with pytest.raises(outbox_mod.NotificationOutboxError, match="opaque idem"):
        store.enqueue(
            idempotency_key="private-user-identifier",
            category="reminder",
            adapter_name="app_push",
            payload_ref=store.mint_payload_ref(),
        )

    other_store = _store(tmp_path, name="other-ledger.db")
    with pytest.raises(outbox_mod.NotificationOutboxError, match="not minted"):
        other_store.enqueue(
            idempotency_key=_idem(99),
            category="reminder",
            adapter_name="app_push",
            payload_ref=store.mint_payload_ref(),
        )

    payload_ref = store.mint_payload_ref()
    event = _enqueue(store, 100, payload_ref=payload_ref)
    claim = store.claim_next(adapter_name="app_push")
    assert claim is not None
    public_event = store.get_event(event["event_id"])
    public_status = store.public_status()
    receipts = _receipts(store, event["event_id"])
    rendered = json.dumps(
        {"event": public_event, "status": public_status, "receipts": receipts},
        sort_keys=True,
    )
    assert payload_ref.value not in rendered
    assert claim.claim_handle not in rendered
    assert claim.transport_idempotency_key not in rendered
    assert payload_ref.value not in repr(claim)
    assert claim.claim_handle not in repr(claim)

    with sqlite3.connect(store.db_path) as conn:
        event_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(notification_outbox_events)")
        }
        receipt_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(notification_outbox_receipts)")
        }
        stored_lease = conn.execute(
            "SELECT lease_hmac FROM notification_outbox_events WHERE event_id=?",
            (event["event_id"],),
        ).fetchone()[0]
    forbidden = {
        "destination",
        "phone",
        "credential",
        "provider_token",
        "external_id",
        "message",
        "content",
        "lease_handle",
    }
    assert forbidden.isdisjoint(event_columns | receipt_columns)
    assert stored_lease != claim.claim_handle
    assert len(stored_lease) == 64
    assert all("lease_hmac" not in receipt for receipt in receipts)
    assert all("transport_key_hmac" not in receipt for receipt in receipts)


@pytest.mark.parametrize(
    "field_name",
    (
        "created_at",
        "updated_at",
        "next_attempt_at",
        "indeterminate_at",
        "sent_at",
        "acknowledged_at",
        "failed_at",
        "cancelled_at",
    ),
)
def test_every_public_lifecycle_timestamp_is_authenticated_by_sealed_tail(
    tmp_path, field_name
):
    store = _store(
        tmp_path,
        name=f"timestamp-{field_name}.db",
        policy=_policy(max_attempts=1),
    )
    event = _enqueue(store)
    if field_name == "indeterminate_at":
        claim = store.claim_next(adapter_name="app_push")
        store.mark_indeterminate(
            event["event_id"],
            claim_handle=claim.claim_handle,
            transport_idempotency_key=claim.transport_idempotency_key,
        )
    elif field_name in {"sent_at", "acknowledged_at"}:
        claim = store.claim_next(adapter_name="app_push")
        store.mark_sent(
            event["event_id"],
            claim_handle=claim.claim_handle,
            transport_idempotency_key=claim.transport_idempotency_key,
        )
        if field_name == "acknowledged_at":
            store.acknowledge(event["event_id"])
    elif field_name == "failed_at":
        claim = store.claim_next(adapter_name="app_push")
        store.record_failure(
            event["event_id"],
            claim_handle=claim.claim_handle,
            transport_idempotency_key=claim.transport_idempotency_key,
        )
    elif field_name == "cancelled_at":
        store.cancel(event["event_id"])

    status = store.get_event(event["event_id"])
    assert status[field_name] is not None
    with sqlite3.connect(store.db_path) as conn:
        original = conn.execute(
            f"SELECT {field_name} FROM notification_outbox_events WHERE event_id=?",
            (event["event_id"],),
        ).fetchone()[0]
    guards = (
        ("notification_outbox_event_facts_immutable",)
        if field_name == "created_at"
        else ()
    )
    _tamper_rows(
        store.db_path,
        drop_triggers=guards,
        statements=[
            (
                f"UPDATE notification_outbox_events SET {field_name}=? WHERE event_id=?",
                (float(original) + 0.25, event["event_id"]),
            )
        ],
    )

    with pytest.raises(outbox_mod.OutboxQuarantined, match="seal|lifecycle"):
        store.get_event(event["event_id"])


def test_transition_receipts_use_bounded_verified_cursor_pages_and_exact_dto(tmp_path):
    policy = _policy(
        max_attempts=30,
        backoff_initial_seconds=0.0,
        backoff_max_seconds=0.0,
    )
    store = _store(tmp_path, policy=policy)
    event = _enqueue(store)
    for _attempt in range(22):
        claim = store.claim_next(adapter_name="app_push")
        store.mark_indeterminate(
            event["event_id"],
            claim_handle=claim.claim_handle,
            transport_idempotency_key=claim.transport_idempotency_key,
        )
        store.retry_indeterminate(
            event["event_id"],
            transport_idempotency_key=claim.transport_idempotency_key,
        )

    first_page = store.transition_receipts(event["event_id"])
    assert set(first_page) == {"event_id", "receipts", "next_cursor"}
    assert len(first_page["receipts"]) == 64
    assert isinstance(first_page["next_cursor"], str)
    receipt_keys = {
        "receipt_id",
        "receipt_version",
        "global_sequence",
        "transition_id",
        "event_id",
        "event_sequence",
        "kind",
        "from_state",
        "to_state",
        "occurred_at",
        "attempt_count",
        "next_attempt_at",
        "cost_units",
        "reason_code",
        "verified",
    }
    assert all(set(receipt) == receipt_keys for receipt in first_page["receipts"])

    cursor = first_page["next_cursor"]
    second_page = store.transition_receipts(event["event_id"], cursor=cursor)
    assert len(second_page["receipts"]) == 3
    assert second_page["next_cursor"] is None
    sequences = [
        receipt["event_sequence"]
        for receipt in first_page["receipts"] + second_page["receipts"]
    ]
    assert sequences == list(range(1, 68))

    changed = "0" if cursor[-1] != "0" else "1"
    with pytest.raises(outbox_mod.OutboxConflict, match="cursor"):
        store.transition_receipts(
            event["event_id"],
            cursor=cursor[:-1] + changed,
        )
    other = _enqueue(store, 999, adapter_name="discord_dm")
    with pytest.raises(outbox_mod.OutboxConflict, match="cursor"):
        store.transition_receipts(other["event_id"], cursor=cursor)

    pagination_source = inspect.getsource(store.transition_receipts)
    assert "_RECEIPT_PAGE_SIZE + 1" in pagination_source
    assert "LIMIT ?" in pagination_source

    _tamper_rows(
        store.db_path,
        drop_triggers=("notification_outbox_receipt_update_guard",),
        statements=[
            (
                "UPDATE notification_outbox_receipts SET receipt_seal=? "
                "WHERE event_id=? AND event_sequence=64",
                ("0" * 64, event["event_id"]),
            )
        ],
    )
    with pytest.raises(outbox_mod.OutboxQuarantined, match="receipt seal"):
        store.transition_receipts(event["event_id"], cursor=cursor)


def test_concurrent_enqueue_and_claim_converge_to_one_event_and_one_live_lease(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    clock = MutableClock(100.0)
    policy = _policy()
    stores = [
        _store(tmp_path, anchor=anchor, clock=clock, policy=policy) for _ in range(10)
    ]
    payload_ref = stores[0].mint_payload_ref()
    enqueue_barrier = Barrier(len(stores))

    def enqueue(store):
        enqueue_barrier.wait()
        return store.enqueue(
            idempotency_key=_idem(1),
            category="reminder",
            adapter_name="app_push",
            payload_ref=payload_ref,
        )

    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        events = list(pool.map(enqueue, stores))
    assert len({event["event_id"] for event in events}) == 1

    claim_barrier = Barrier(len(stores))

    def claim(store):
        claim_barrier.wait()
        return store.claim_next(adapter_name="app_push")

    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        results = list(pool.map(claim, stores))
    claims = [result for result in results if result is not None]
    assert len(claims) == 1
    assert claims[0].lease_expires_at > clock.value
    assert [row["kind"] for row in _receipt_rows(stores[0].db_path)] == [
        "enqueued",
        "claimed",
    ]
    assert anchor.snapshot().current.sequence == 2


def test_clock_is_not_sampled_until_write_lock_and_contention_time_wins(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    clock = MutableClock(100.0)
    store = _store(tmp_path, anchor=anchor, clock=clock)
    assert clock.calls == 0
    _enqueue(store)
    clock.reset_calls()

    blocker = sqlite3.connect(store.db_path, timeout=5.0)
    blocker.execute("BEGIN IMMEDIATE")
    started = threading.Event()

    def claim():
        started.set()
        return store.claim_next(adapter_name="app_push")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(claim)
        assert started.wait(timeout=2.0)
        time.sleep(0.1)
        assert clock.calls == 0
        clock.set(500.0)
        blocker.commit()
        blocker.close()
        result = future.result(timeout=5.0)

    assert result is not None
    assert result.lease_expires_at == 510.0
    assert result.lease_expires_at > clock.value
    claimed_receipt = _receipts(store, result.event_id)[-1]
    assert claimed_receipt["occurred_at"] == 500.0


def test_anchored_read_waits_for_prepared_writer_instead_of_aborting_it(tmp_path):
    anchor = PausingPrepareAnchor()
    store = _store(tmp_path, anchor=anchor)
    _enqueue(store)
    anchor.pause_next_prepare = True

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(store.claim_next, adapter_name="app_push")
        assert anchor.prepared.wait(timeout=2.0)
        reader = pool.submit(store.public_status)
        time.sleep(0.1)
        assert reader.done() is False
        assert anchor.snapshot().pending is not None
        anchor.release.set()
        claim = writer.result(timeout=5.0)
        status = reader.result(timeout=5.0)

    assert claim is not None
    assert status["states"][outbox_mod.LEASED] == 1
    assert anchor.snapshot().pending is None


def test_claim_accepts_exact_checkpoint_reconciled_during_anchor_commit(tmp_path):
    anchor = PausingStrictCommitAnchor()
    clock = MutableClock(100.0)
    policy = _policy()
    claimant = _store(tmp_path, anchor=anchor, clock=clock, policy=policy)
    reconciler = _store(tmp_path, anchor=anchor, clock=clock, policy=policy)
    event = _enqueue(claimant)
    anchor.pause_next_commit = True

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(claimant.claim_next, adapter_name="app_push")
        assert anchor.original_waiting.wait(timeout=2.0)
        status = reconciler.public_status()
        assert status["states"][outbox_mod.LEASED] == 1
        assert anchor.snapshot().pending is None
        anchor.release_original.set()
        claim = future.result(timeout=5.0)

    assert claim is not None
    assert claim.event_id == event["event_id"]
    assert claim.lease_expires_at > clock.value
    assert claimant.quarantined is False
    assert [
        receipt["kind"] for receipt in _receipts(claimant, event["event_id"])
    ] == ["enqueued", "claimed"]


def test_claim_accepts_reconciled_successor_checkpoint_from_second_store(tmp_path):
    anchor = PausingStrictCommitAnchor()
    clock = MutableClock(100.0)
    policy = _policy()
    claimant = _store(tmp_path, anchor=anchor, clock=clock, policy=policy)
    successor_writer = _store(tmp_path, anchor=anchor, clock=clock, policy=policy)
    claimed_event = _enqueue(claimant, 1)
    anchor.pause_next_commit = True

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(claimant.claim_next, adapter_name="app_push")
        assert anchor.original_waiting.wait(timeout=2.0)
        successor_writer.public_status()
        successor_event = _enqueue(
            successor_writer,
            2,
            adapter_name="discord_dm",
        )
        assert anchor.snapshot().current.sequence == 3
        anchor.release_original.set()
        claim = future.result(timeout=5.0)

    assert claim is not None
    assert claim.event_id == claimed_event["event_id"]
    assert claimant.quarantined is False
    assert successor_writer.get_event(successor_event["event_id"])["state"] == outbox_mod.QUEUED
    assert claimant.audit() == {"verified": True, "events": 2, "receipts": 3}


def test_claim_rejects_within_transaction_clock_regression_5_to_1(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    clock = MutableClock(0.0)
    store = _store(tmp_path, anchor=anchor, clock=clock)
    _enqueue(store)
    clock.set_sequence([5.0, 1.0])

    with pytest.raises(outbox_mod.OutboxQuarantined, match="clock regressed"):
        store.claim_next(adapter_name="app_push")

    assert store.quarantined is True
    assert [row["kind"] for row in _receipt_rows(store.db_path)] == ["enqueued"]
    assert anchor.snapshot().current.sequence == 1


def test_claim_rejects_time_older_than_cross_event_anchored_tail(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    clock = MutableClock(100.0)
    store = _store(tmp_path, anchor=anchor, clock=clock)
    first = _enqueue(store, 1)
    clock.set(101.0)
    second = _enqueue(store, 2)
    clock.set(110.0)
    assert store.claim_next(adapter_name="app_push").event_id == first["event_id"]

    clock.set(105.0)
    with pytest.raises(outbox_mod.OutboxQuarantined, match="clock regressed"):
        store.claim_next(adapter_name="app_push")

    with sqlite3.connect(store.db_path) as conn:
        state = conn.execute(
            "SELECT state FROM notification_outbox_events WHERE event_id=?",
            (second["event_id"],),
        ).fetchone()[0]
    assert state == outbox_mod.QUEUED
    assert [row["occurred_at"] for row in _receipt_rows(store.db_path)] == [
        100.0,
        101.0,
        110.0,
    ]


def test_claim_retries_transaction_when_clock_crosses_expiry_before_commit(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    clock = MutableClock(100.0)
    store = _store(tmp_path, anchor=anchor, clock=clock)
    event = _enqueue(store)
    clock.reset_calls()
    clock.set_sequence([100.0, 100.0, 111.0, 111.0, 111.0, 111.0])

    claim = store.claim_next(adapter_name="app_push")
    assert claim is not None
    assert claim.event_id == event["event_id"]
    assert claim.lease_expires_at == 121.0
    assert claim.lease_expires_at > 111.0
    assert clock.calls == 7
    assert [
        receipt["kind"] for receipt in _receipts(store, event["event_id"])
    ] == ["enqueued", "claimed"]
    assert anchor.snapshot().current.sequence == 2


def test_claim_time_policy_sample_defers_when_boundary_enters_quiet_hours(tmp_path):
    zone = ZoneInfo("America/Los_Angeles")
    before_quiet = datetime(2026, 1, 1, 21, 59, tzinfo=zone).timestamp()
    quiet_start = datetime(2026, 1, 1, 22, 0, tzinfo=zone).timestamp()
    setup_clock = MutableClock(before_quiet)
    policy = _policy(
        quiet_hours=outbox_mod.QuietHours(
            "America/Los_Angeles", 22 * 60, 7 * 60
        )
    )
    store = _store(tmp_path, clock=setup_clock, policy=policy)
    event = _enqueue(store)
    setup_clock.set_sequence([before_quiet, quiet_start])

    assert store.claim_next(adapter_name="app_push") is None
    status = store.get_event(event["event_id"])
    assert status["state"] == outbox_mod.QUEUED
    assert status["attempt_count"] == 0
    assert _receipts(store, event["event_id"])[-1]["kind"] == "quiet_deferred"


def test_claim_rechecks_liveness_after_slow_external_anchor_commit(tmp_path):
    clock = MutableClock(100.0)
    anchor = AdvancingCommitAnchor(clock)
    store = _store(tmp_path, anchor=anchor, clock=clock)
    event = _enqueue(store)
    anchor.advance_on_commit = True

    claim = store.claim_next(adapter_name="app_push")
    assert claim is not None
    assert claim.event_id == event["event_id"]
    assert claim.attempt_count == 2
    assert claim.lease_expires_at == 121.0
    assert claim.lease_expires_at > clock.value
    assert [
        receipt["kind"] for receipt in _receipts(store, event["event_id"])
    ] == ["enqueued", "claimed", "claim_abandoned", "claimed"]


def test_claim_samples_clock_after_delayed_final_event_load(tmp_path, monkeypatch):
    clock = MutableClock(100.0)
    store = _store(tmp_path, clock=clock)
    event = _enqueue(store)
    original_load = store._load_event_tail_locked
    load_calls = 0

    def delayed_load(conn, event_id):
        nonlocal load_calls
        load_calls += 1
        result = original_load(conn, event_id)
        if load_calls == 2:
            clock.set(111.0)
        return result

    monkeypatch.setattr(store, "_load_event_tail_locked", delayed_load)
    claim = store.claim_next(adapter_name="app_push")

    assert claim is not None
    assert claim.event_id == event["event_id"]
    assert claim.attempt_count == 2
    assert claim.lease_expires_at == 121.0
    assert claim.lease_expires_at > clock.value
    assert [
        receipt["kind"] for receipt in _receipts(store, event["event_id"])
    ] == ["enqueued", "claimed", "claim_abandoned", "claimed"]


def test_transport_key_is_event_derived_and_idempotent_retry_reuses_it(tmp_path):
    clock = MutableClock(100.0)
    store = _store(tmp_path, clock=clock)
    event = _enqueue(store, adapter_name="app_push")
    first = store.claim_next(adapter_name="app_push")
    assert first is not None
    assert first.transport_idempotency_key.startswith("txi_")

    with pytest.raises(outbox_mod.OutboxConflict, match="does not match"):
        store.mark_sent(
            event["event_id"],
            claim_handle=first.claim_handle,
            transport_idempotency_key="txi_" + "0" * 64,
        )
    indeterminate = store.mark_indeterminate(
        event["event_id"],
        claim_handle=first.claim_handle,
        transport_idempotency_key=first.transport_idempotency_key,
    )
    assert indeterminate["state"] == outbox_mod.INDETERMINATE
    queued = store.retry_indeterminate(
        event["event_id"],
        transport_idempotency_key=first.transport_idempotency_key,
    )
    assert queued["state"] == outbox_mod.QUEUED
    assert queued["next_attempt_at"] == 105.0
    assert store.claim_next(adapter_name="app_push") is None

    clock.set(105.0)
    second = store.claim_next(adapter_name="app_push")
    assert second is not None
    assert second.claim_handle != first.claim_handle
    assert second.transport_idempotency_key == first.transport_idempotency_key
    sent = store.mark_sent(
        event["event_id"],
        claim_handle=second.claim_handle,
        transport_idempotency_key=second.transport_idempotency_key,
    )
    assert sent["state"] == outbox_mod.SENT
    assert store.acknowledge(event["event_id"])["state"] == outbox_mod.ACKNOWLEDGED


def test_expired_non_idempotent_claim_stays_indeterminate_until_reconciled(tmp_path):
    clock = MutableClock(100.0)
    store = _store(tmp_path, clock=clock)
    event = _enqueue(store, adapter_name="non_idempotent_sms")
    claim = store.claim_next(adapter_name="non_idempotent_sms")
    assert claim is not None

    clock.set(110.0)
    assert store.recover_expired() == 1
    status = store.get_event(event["event_id"])
    assert status["state"] == outbox_mod.INDETERMINATE
    assert store.claim_next(adapter_name="non_idempotent_sms") is None
    with pytest.raises(outbox_mod.OutboxStateError, match="non-idempotent"):
        store.retry_indeterminate(
            event["event_id"],
            transport_idempotency_key=claim.transport_idempotency_key,
        )
    assert store.get_event(event["event_id"])["state"] == outbox_mod.INDETERMINATE

    reconciled = store.reconcile_indeterminate(
        event["event_id"],
        transport_idempotency_key=claim.transport_idempotency_key,
        outcome="accepted",
    )
    assert reconciled["state"] == outbox_mod.SENT
    assert store.acknowledge(event["event_id"])["state"] == outbox_mod.ACKNOWLEDGED


def test_reopen_recovers_an_outstanding_expired_lease(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    policy = _policy(lease_seconds=10.0)
    initial_clock = MutableClock(100.0)
    store = _store(
        tmp_path,
        anchor=anchor,
        policy=policy,
        clock=initial_clock,
    )
    event = _enqueue(store)
    claim = store.claim_next(adapter_name="app_push")
    assert claim.lease_expires_at == 110.0

    reopened = _store(
        tmp_path,
        anchor=anchor,
        policy=policy,
        clock=MutableClock(111.0),
    )
    assert reopened.get_event(event["event_id"])["state"] == outbox_mod.LEASED
    assert reopened.recover_expired() == 1
    assert reopened.get_event(event["event_id"])["state"] == outbox_mod.INDETERMINATE
    assert [receipt["kind"] for receipt in _receipts(reopened, event["event_id"])] == [
        "enqueued",
        "claimed",
        "lease_expired",
    ]


def test_provider_outcome_and_expiry_recovery_race_serializes_at_boundary(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    policy = _policy(lease_seconds=10.0)
    clock = MutableClock(100.0)
    outcome_store = _store(
        tmp_path,
        anchor=anchor,
        policy=policy,
        clock=clock,
    )
    recovery_store = _store(
        tmp_path,
        anchor=anchor,
        policy=policy,
        clock=clock,
    )
    event = _enqueue(outcome_store)
    claim = outcome_store.claim_next(adapter_name="app_push")
    clock.set(110.0)
    barrier = Barrier(2)

    def record_outcome():
        barrier.wait()
        try:
            outcome_store.mark_sent(
                event["event_id"],
                claim_handle=claim.claim_handle,
                transport_idempotency_key=claim.transport_idempotency_key,
            )
        except outbox_mod.OutboxStateError:
            return False
        return True

    def recover():
        barrier.wait()
        return recovery_store.recover_expired()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcome_future = pool.submit(record_outcome)
        recovery_future = pool.submit(recover)
        outcome_recorded = outcome_future.result(timeout=5.0)
        recovered = recovery_future.result(timeout=5.0)

    assert outcome_recorded is False
    assert recovered == 1
    assert recovery_store.get_event(event["event_id"])["state"] == outbox_mod.INDETERMINATE
    assert [
        receipt["kind"] for receipt in _receipts(recovery_store, event["event_id"])
    ] == ["enqueued", "claimed", "lease_expired"]


def test_expired_recovery_is_fixed_batch_and_claim_result_remains_correct(tmp_path):
    clock = MutableClock(100.0)
    store = _store(tmp_path, clock=clock, policy=_policy(lease_seconds=1.0))

    for number in range(1, 262):
        event = _enqueue(store, number, adapter_name="app_push")
        claim = store.claim_next(adapter_name="app_push")
        assert claim is not None
        assert claim.event_id == event["event_id"]

    fresh = _enqueue(store, 10_000, adapter_name="discord_dm")
    clock.set(101.0)
    fresh_claim = store.claim_next(adapter_name="discord_dm")
    assert fresh_claim is not None
    assert fresh_claim.event_id == fresh["event_id"]
    assert fresh_claim.lease_expires_at == 102.0

    status = store.public_status()
    assert status["states"][outbox_mod.INDETERMINATE] == 64
    assert status["states"][outbox_mod.LEASED] == 198
    assert [store.recover_expired() for _attempt in range(5)] == [64, 64, 64, 5, 0]

    status = store.public_status()
    assert status["states"][outbox_mod.INDETERMINATE] == 261
    assert status["states"][outbox_mod.LEASED] == 1
    assert store.audit() == {"verified": True, "events": 262, "receipts": 785}


def test_definitive_failure_uses_frozen_backoff_and_max_attempts(tmp_path):
    clock = MutableClock(100.0)
    policy = _policy(max_attempts=2)
    store = _store(tmp_path, clock=clock, policy=policy)
    event = _enqueue(store)
    first = store.claim_next(adapter_name="app_push")
    assert first is not None
    clock.set(101.0)
    retry = store.record_failure(
        event["event_id"],
        claim_handle=first.claim_handle,
        transport_idempotency_key=first.transport_idempotency_key,
    )
    assert retry["state"] == outbox_mod.QUEUED
    assert retry["next_attempt_at"] == 106.0
    clock.set(106.0)
    second = store.claim_next(adapter_name="app_push")
    assert second is not None
    clock.set(107.0)
    failed = store.record_failure(
        event["event_id"],
        claim_handle=second.claim_handle,
        transport_idempotency_key=second.transport_idempotency_key,
    )
    assert failed["state"] == outbox_mod.FAILED
    assert failed["attempt_count"] == 2


def test_ack_requires_sent_evidence_and_cancel_fails_while_lease_is_active(tmp_path):
    store = _store(tmp_path)
    queued = _enqueue(store, 1)
    with pytest.raises(outbox_mod.OutboxStateError, match="sent evidence"):
        store.acknowledge(queued["event_id"])

    claim = store.claim_next(adapter_name="app_push")
    assert claim is not None
    with pytest.raises(outbox_mod.OutboxStateError, match="sent evidence"):
        store.acknowledge(queued["event_id"])
    with pytest.raises(outbox_mod.OutboxStateError, match="lease is active"):
        store.cancel(queued["event_id"])
    assert store.get_event(queued["event_id"])["state"] == outbox_mod.LEASED

    sent = store.mark_sent(
        queued["event_id"],
        claim_handle=claim.claim_handle,
        transport_idempotency_key=claim.transport_idempotency_key,
    )
    assert sent["state"] == outbox_mod.SENT
    acknowledged = store.acknowledge(queued["event_id"])
    assert acknowledged["state"] == outbox_mod.ACKNOWLEDGED
    kinds = [item["kind"] for item in _receipts(store, queued["event_id"])]
    assert kinds[-2:] == ["sent", "acknowledged"]

    cancellable = _enqueue(store, 2)
    assert store.cancel(cancellable["event_id"])["state"] == outbox_mod.CANCELLED


def test_claim_cancel_race_never_cancels_an_active_lease(tmp_path):
    for iteration in range(5):
        anchor = outbox_mod.InMemoryMonotonicAnchor()
        store = _store(tmp_path, anchor=anchor, name=f"race-{iteration}.db")
        event = _enqueue(store, iteration + 1)
        barrier = Barrier(2)

        def claim():
            barrier.wait()
            return store.claim_next(adapter_name="app_push")

        def cancel():
            barrier.wait()
            try:
                return store.cancel(event["event_id"])
            except outbox_mod.OutboxStateError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            claim_future = pool.submit(claim)
            cancel_future = pool.submit(cancel)
            claim_result = claim_future.result()
            cancel_result = cancel_future.result()
        final = store.get_event(event["event_id"])
        if claim_result is not None:
            assert cancel_result is None
            assert final["state"] == outbox_mod.LEASED
        else:
            assert cancel_result is not None
            assert final["state"] == outbox_mod.CANCELLED


def test_exact_policy_identity_version_and_manifest_are_required_on_reopen(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    policy = _policy()
    store = _store(tmp_path, anchor=anchor, policy=policy)
    _enqueue(store)
    assert _store(tmp_path, anchor=anchor, policy=policy).audit()["verified"] is True

    changed_policies = [
        replace(policy, policy_version=2),
        replace(policy, backoff_initial_seconds=6.0),
        replace(
            policy,
            channel_costs={
                "app_push": 1,
                "discord_dm": 0,
                "non_idempotent_sms": 1,
            },
        ),
        replace(
            policy,
            quiet_hours=outbox_mod.QuietHours(
                "America/Los_Angeles", 22 * 60, 7 * 60
            ),
        ),
    ]
    for changed in changed_policies:
        with pytest.raises(outbox_mod.OutboxPolicyMismatch):
            _store(tmp_path, anchor=anchor, policy=changed)
    assert _store(tmp_path, anchor=anchor, policy=policy).public_status()[
        "policy_version"
    ] == 1

    with sqlite3.connect(store.db_path) as conn:
        stored = conn.execute(
            "SELECT policy_id,policy_version,policy_digest,meta_seal "
            "FROM notification_outbox_meta"
        ).fetchone()
    assert stored[0:2] == (policy.policy_id, policy.policy_version)
    assert stored[2] == policy.digest
    assert len(stored[3]) == 64


def test_abandoned_initial_anchor_prepare_is_aborted_before_initialization(tmp_path):
    policy = _policy()
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    abandoned = outbox_mod.LedgerCheckpoint(
        ledger_id="ledger_" + "a" * 32,
        contract_version=outbox_mod.CONTRACT_VERSION,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_digest=policy.digest,
        sequence=0,
        event_count=0,
        receipt_count=0,
        global_head_seal="",
        meta_seal="0" * 64,
    )
    anchor.prepare(None, abandoned)

    store = _store(tmp_path, anchor=anchor, policy=policy)
    snapshot = anchor.snapshot()
    assert snapshot.pending is None
    assert snapshot.current is not None
    assert snapshot.current.ledger_id != abandoned.ledger_id
    assert store.audit()["events"] == 0


def test_pending_anchor_checkpoint_recovers_database_commit_on_reopen(tmp_path):
    policy = _policy()
    anchor = FailOnceCommitAnchor()
    store = _store(tmp_path, anchor=anchor, policy=policy)
    anchor.fail_next_commit = True

    with pytest.raises(outbox_mod.OutboxQuarantined, match="anchor commit failed"):
        _enqueue(store)
    assert anchor.snapshot().pending is not None

    recovered = _store(tmp_path, anchor=anchor, policy=policy)
    assert anchor.snapshot().pending is None
    assert recovered.audit() == {"verified": True, "events": 1, "receipts": 1}


def test_valid_prefix_receipt_truncation_quarantines_and_fails_closed(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    store = _store(tmp_path, anchor=anchor)
    event = _enqueue(store)
    store.claim_next(adapter_name="app_push")
    rows = _receipt_rows(store.db_path)
    assert len(rows) == 2

    _tamper_rows(
        store.db_path,
        drop_triggers=("notification_outbox_receipt_delete_guard",),
        statements=[
            (
                "DELETE FROM notification_outbox_receipts WHERE global_sequence=?",
                (rows[-1]["global_sequence"],),
            )
        ],
    )
    with pytest.raises(outbox_mod.OutboxQuarantined, match="count|truncated"):
        store.audit()
    assert store.quarantined is True
    with pytest.raises(outbox_mod.OutboxQuarantined):
        store.get_event(event["event_id"])


def test_tail_receipt_tamper_is_detected_without_linear_audit(tmp_path):
    store = _store(tmp_path)
    _enqueue(store)
    with sqlite3.connect(store.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="receipts are immutable"):
            conn.execute(
                "UPDATE notification_outbox_receipts SET reason_code='tampered'"
            )
    _tamper_rows(
        store.db_path,
        drop_triggers=("notification_outbox_receipt_update_guard",),
        statements=[
            (
                "UPDATE notification_outbox_receipts SET reason_code='tampered'",
                (),
            )
        ],
    )
    with pytest.raises(outbox_mod.OutboxQuarantined, match="receipt seal"):
        store.public_status()


def test_full_event_and_chain_deletion_is_detected_on_reopen(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    policy = _policy()
    store = _store(tmp_path, anchor=anchor, policy=policy)
    first = _enqueue(store, 1)
    _enqueue(store, 2)

    _tamper_rows(
        store.db_path,
        drop_triggers=(
            "notification_outbox_receipt_delete_guard",
            "notification_outbox_event_delete_guard",
        ),
        statements=[
            (
                "DELETE FROM notification_outbox_receipts WHERE event_id=?",
                (first["event_id"],),
            ),
            (
                "DELETE FROM notification_outbox_events WHERE event_id=?",
                (first["event_id"],),
            ),
        ],
        disable_foreign_keys=True,
    )
    with pytest.raises(outbox_mod.OutboxQuarantined, match="count"):
        _store(tmp_path, anchor=anchor, policy=policy)


def test_database_snapshot_rollback_is_rejected_by_external_anchor(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    policy = _policy()
    store = _store(tmp_path, anchor=anchor, policy=policy)
    _enqueue(store, 1)
    snapshot_path = tmp_path / "prefix-snapshot.db"
    with sqlite3.connect(store.db_path) as source, sqlite3.connect(snapshot_path) as target:
        source.backup(target)

    _enqueue(store, 2)
    assert anchor.snapshot().current.sequence == 2
    with sqlite3.connect(snapshot_path) as source, sqlite3.connect(store.db_path) as target:
        source.backup(target)
    with pytest.raises(outbox_mod.OutboxQuarantined, match="anchor"):
        _store(tmp_path, anchor=anchor, policy=policy)


def test_orphan_receipt_is_detected_even_when_global_counts_and_tail_match(tmp_path):
    anchor = outbox_mod.InMemoryMonotonicAnchor()
    store = _store(tmp_path, anchor=anchor)
    _enqueue(store)
    original = _receipt_rows(store.db_path)[0]
    orphan_event_id = "out_" + "f" * 32

    columns = [
        "receipt_version",
        "global_sequence",
        "transition_id",
        "event_id",
        "event_sequence",
        "policy_id",
        "policy_version",
        "policy_digest",
        "kind",
        "from_state",
        "to_state",
        "occurred_at",
        "created_at",
        "attempt_count",
        "lease_hmac",
        "lease_expires_at",
        "next_attempt_at",
        "indeterminate_at",
        "sent_at",
        "acknowledged_at",
        "failed_at",
        "cancelled_at",
        "cost_units",
        "reason_code",
        "transport_key_hmac",
        "previous_event_seal",
        "previous_global_seal",
        "receipt_seal",
    ]
    values = [original[column] for column in columns]
    values[3] = orphan_event_id
    _tamper_rows(
        store.db_path,
        drop_triggers=("notification_outbox_receipt_delete_guard",),
        statements=[
            ("DELETE FROM notification_outbox_receipts", ()),
            (
                "INSERT INTO notification_outbox_receipts ("
                + ",".join(columns)
                + ") VALUES ("
                + ",".join("?" for _ in columns)
                + ")",
                tuple(values),
            ),
        ],
        disable_foreign_keys=True,
    )
    with pytest.raises(outbox_mod.OutboxQuarantined, match="orphan"):
        store.audit()


def test_iana_quiet_hours_handle_spring_gap_and_fall_fold():
    zone = ZoneInfo("America/Los_Angeles")
    spring = outbox_mod.QuietHours(
        timezone_name="America/Los_Angeles",
        start_minute=22 * 60,
        end_minute=2 * 60 + 30,
    )
    before_gap = datetime(2026, 3, 8, 1, 59, tzinfo=zone).timestamp()
    first_nonquiet = datetime(2026, 3, 8, 3, 0, tzinfo=zone).timestamp()
    assert spring.defer_until(before_gap) == first_nonquiet

    fall = outbox_mod.QuietHours(
        timezone_name="America/Los_Angeles",
        start_minute=22 * 60,
        end_minute=2 * 60 + 30,
    )
    first_0130 = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0).timestamp()
    second_0130 = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1).timestamp()
    end = datetime(2026, 11, 1, 2, 30, tzinfo=zone).timestamp()
    assert fall.defer_until(first_0130) == end
    assert fall.defer_until(second_0130) == end


def test_quiet_hours_quotas_and_cost_cap_defer_without_attempt(tmp_path):
    clock = MutableClock(
        datetime(2026, 1, 1, 23, 0, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
    )
    policy = _policy(
        category_quotas={"alert": 1, "reminder": None, "routine": None},
        channel_quotas={
            "app_push": 2,
            "discord_dm": None,
            "non_idempotent_sms": None,
        },
        global_quota=3,
        daily_cost_cap=1,
        quiet_hours=outbox_mod.QuietHours(
            "America/Los_Angeles", 22 * 60, 7 * 60
        ),
    )
    store = _store(tmp_path, clock=clock, policy=policy)
    event = _enqueue(store, category="alert", adapter_name="app_push")
    assert store.claim_next(adapter_name="app_push") is None
    deferred = store.get_event(event["event_id"])
    assert deferred["attempt_count"] == 0
    assert _receipts(store, event["event_id"])[-1]["kind"] == "quiet_deferred"

    clock.set(
        datetime(2026, 1, 2, 7, 0, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
    )
    assert store.claim_next(adapter_name="app_push") is not None


def test_frozen_policy_enforces_category_channel_global_and_daily_cost_limits(tmp_path):
    clock = MutableClock(100.0)
    policy = _policy(
        category_quotas={"alert": 1, "reminder": None, "routine": None},
        channel_quotas={
            "app_push": 2,
            "discord_dm": None,
            "non_idempotent_sms": None,
        },
        channel_costs={
            "app_push": 1,
            "discord_dm": 0,
            "non_idempotent_sms": 2,
        },
        global_quota=4,
        daily_cost_cap=3,
    )
    store = _store(tmp_path, clock=clock, policy=policy)

    first = _enqueue(store, 1, category="alert", adapter_name="app_push")
    assert store.claim_next(adapter_name="app_push").event_id == first["event_id"]

    category_blocked = _enqueue(
        store, 2, category="alert", adapter_name="discord_dm"
    )
    assert store.claim_next(adapter_name="discord_dm") is None

    second = _enqueue(store, 3, category="reminder", adapter_name="app_push")
    assert store.claim_next(adapter_name="app_push").event_id == second["event_id"]

    cost_blocked = _enqueue(
        store, 4, category="routine", adapter_name="non_idempotent_sms"
    )
    assert store.claim_next(adapter_name="non_idempotent_sms") is None

    channel_blocked = _enqueue(
        store, 5, category="routine", adapter_name="app_push"
    )
    assert store.claim_next(adapter_name="app_push") is None

    third = _enqueue(store, 6, category="routine", adapter_name="discord_dm")
    assert store.claim_next(adapter_name="discord_dm").event_id == third["event_id"]
    fourth = _enqueue(store, 7, category="reminder", adapter_name="discord_dm")
    assert store.claim_next(adapter_name="discord_dm").event_id == fourth["event_id"]
    global_blocked = _enqueue(
        store, 8, category="routine", adapter_name="discord_dm"
    )
    assert store.claim_next(adapter_name="discord_dm") is None

    expected_reasons = {
        category_blocked["event_id"]: "category_quota",
        cost_blocked["event_id"]: "daily_cost_cap",
        channel_blocked["event_id"]: "channel_quota",
        global_blocked["event_id"]: "global_quota",
    }
    for event_id, reason in expected_reasons.items():
        status = store.get_event(event_id)
        receipt = _receipts(store, event_id)[-1]
        assert status["state"] == outbox_mod.QUEUED
        assert status["attempt_count"] == 0
        assert receipt["kind"] == "policy_deferred"
        assert receipt["reason_code"] == reason


def test_mutation_apis_have_no_caller_timestamps_and_skip_linear_audit(tmp_path, monkeypatch):
    clock = MutableClock(100.0)
    store = _store(tmp_path, clock=clock)
    timestamp_names = {
        "now",
        "created_at",
        "sent_at",
        "failed_at",
        "acknowledged_at",
        "cancelled_at",
        "occurred_at",
    }
    for method in (
        store.enqueue,
        store.claim_next,
        store.recover_expired,
        store.mark_sent,
        store.record_failure,
        store.mark_indeterminate,
        store.reconcile_indeterminate,
        store.retry_indeterminate,
        store.acknowledge,
        store.cancel,
    ):
        assert timestamp_names.isdisjoint(inspect.signature(method).parameters)

    quota_source = inspect.getsource(store._quota_retry_at_locked)
    recovery_source = inspect.getsource(store._recover_expired_locked)
    assert "COUNT(*)" in quota_source
    assert "MIN(r.occurred_at)" in quota_source
    assert ".fetchall()" not in quota_source
    assert "LIMIT ?" in recovery_source

    def forbidden_full_audit(_conn):
        raise AssertionError("ordinary mutation called the linear full audit")

    monkeypatch.setattr(store, "_full_audit_locked", forbidden_full_audit)
    event = _enqueue(store)
    claim = store.claim_next(adapter_name="app_push")
    assert claim is not None
    store.mark_indeterminate(
        event["event_id"],
        claim_handle=claim.claim_handle,
        transport_idempotency_key=claim.transport_idempotency_key,
    )
    store.retry_indeterminate(
        event["event_id"],
        transport_idempotency_key=claim.transport_idempotency_key,
    )
    store.public_status()
