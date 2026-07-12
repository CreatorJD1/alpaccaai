"""Adversarial coverage for the constructor-bound bridge actor core."""
from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import inspect
import json
import multiprocessing
import shutil
import sqlite3
import threading
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from alpecca import bridge_actor_identity as actor_mod
from alpecca.db import connect


NOW_MS = 1_900_000_000_000
SEAL_KEY = b"phase10-dedicated-actor-envelope-key-v2"
BODY = b'{"message":"bounded request bytes"}'
EVENT_ID = "discord-event-10001"
ACTOR_ID = "discord-actor-20002"
GUILD_ID = "discord-guild-30003"
CHANNEL_ID = "discord-channel-40004"
THREAD_ID = "discord-thread-50005"
BOUNDARY = actor_mod.TrustedBridgeBoundary(
    service="discord-bridge",
    platform="discord",
    boundary_id="server-discord-adapter",
)
POLICY = actor_mod.BridgeActorPolicy(
    version=1,
    envelope_ttl_ms=30_000,
    max_body_bytes=1024,
    max_external_id_bytes=256,
    max_transport_bytes=4096,
    max_clock_advance_ms=60_000,
    max_incremental_audit_rows=16,
)

STATE_TABLE = "bridge_actor_identity_state"
ENVELOPE_TABLE = "bridge_actor_identity_envelopes"
EVIDENCE_TABLE = "bridge_actor_identity_evidence"
AUDIT_TABLE = "bridge_actor_identity_audit"


class MutableClock:
    def __init__(self, value: int = NOW_MS) -> None:
        self.value = value
        self.calls = 0
        self._lock = threading.Lock()

    def now_ms(self) -> int:
        with self._lock:
            self.calls += 1
            return self.value


class FixedClock:
    def __init__(self, value: int) -> None:
        self.value = value

    def now_ms(self) -> int:
        return self.value


class MemoryAnchor:
    """Test double showing that the external anchor contract is pluggable."""

    def __init__(self) -> None:
        self._values: dict[str, actor_mod.AnchorState] = {}
        self._lock = threading.Lock()

    def read(self, namespace: str) -> actor_mod.AnchorState | None:
        with self._lock:
            return self._values.get(namespace)

    def compare_and_swap(
        self,
        namespace: str,
        expected: actor_mod.AnchorState | None,
        replacement: actor_mod.AnchorState,
    ) -> bool:
        with self._lock:
            current = self._values.get(namespace)
            if current != expected:
                return False
            if current is not None and replacement.revision <= current.revision:
                return False
            self._values[namespace] = replacement
            return True

    def snapshot(self) -> dict[str, actor_mod.AnchorState]:
        with self._lock:
            return dict(self._values)

    def force_snapshot(self, values: dict[str, actor_mod.AnchorState]) -> None:
        with self._lock:
            self._values = dict(values)


def _store(
    tmp_path: Path,
    *,
    clock: MutableClock | FixedClock | None = None,
    policy: actor_mod.BridgeActorPolicy = POLICY,
    boundary: actor_mod.TrustedBridgeBoundary = BOUNDARY,
    anchor: actor_mod.MonotonicAnchor | None = None,
    db_name: str = "bridge-actors.sqlite3",
    anchor_name: str = "bridge-anchor.sqlite3",
    key: bytes = SEAL_KEY,
    key_version: int = 7,
) -> actor_mod.BridgeActorIdentityStore:
    if clock is None:
        clock = MutableClock()
    if anchor is None:
        anchor = actor_mod.SQLiteMonotonicAnchor(tmp_path / anchor_name)
    return actor_mod.BridgeActorIdentityStore(
        tmp_path / db_name,
        seal_key=key,
        key_version=key_version,
        policy=policy,
        boundary=boundary,
        clock=clock,
        monotonic_anchor=anchor,
    )


def _request_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "request_body": BODY,
        "discord_event_id": EVENT_ID,
        "external_actor_id": ACTOR_ID,
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "thread_id": THREAD_ID,
    }
    values.update(overrides)
    return values


def _issue(
    store: actor_mod.BridgeActorIdentityStore,
    **overrides: object,
) -> actor_mod.BridgeActorEnvelope:
    return store.issue_envelope(**_request_values(**overrides))  # type: ignore[arg-type]


def _verify(
    store: actor_mod.BridgeActorIdentityStore,
    envelope: actor_mod.BridgeActorEnvelope | dict[str, object] | str,
    **overrides: object,
) -> actor_mod.BridgeActorVerification:
    return store.verify_and_consume(  # type: ignore[arg-type]
        envelope,
        **_request_values(**overrides),
    )


def _rows(db_path: Path, table: str) -> list[dict[str, object]]:
    assert table in {STATE_TABLE, ENVELOPE_TABLE, EVIDENCE_TABLE, AUDIT_TABLE}
    with connect(db_path) as conn:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]


def _state(db_path: Path) -> dict[str, object]:
    return _rows(db_path, STATE_TABLE)[0]


def _is_hmac(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value) <= set("0123456789abcdef")
    )


def _process_consume(arguments: tuple[str, str, str, bytes, str, str, str, str, str]):
    (
        db_path,
        anchor_path,
        encoded,
        body,
        event_id,
        actor_id,
        guild_id,
        channel_id,
        thread_id,
    ) = arguments
    store = actor_mod.BridgeActorIdentityStore(
        Path(db_path),
        seal_key=SEAL_KEY,
        key_version=7,
        policy=POLICY,
        boundary=BOUNDARY,
        clock=FixedClock(NOW_MS + 1_000),
        monotonic_anchor=actor_mod.SQLiteMonotonicAnchor(Path(anchor_path)),
    )
    result = store.verify_and_consume(
        encoded,
        request_body=body,
        discord_event_id=event_id,
        external_actor_id=actor_id,
        guild_id=guild_id,
        channel_id=channel_id,
        thread_id=thread_id,
    )
    return result.accepted, result.evidence.reason, result.evidence.evidence_id


def test_constructor_owns_all_assertions_and_phase10_remains_disabled(tmp_path: Path):
    constructor = inspect.signature(actor_mod.BridgeActorIdentityStore)
    for name in (
        "db_path",
        "seal_key",
        "key_version",
        "policy",
        "boundary",
        "clock",
        "monotonic_anchor",
    ):
        assert constructor.parameters[name].default is inspect.Parameter.empty

    forbidden = {"now", "request_digest", "digest", "service", "platform", "principal"}
    issue_parameters = set(inspect.signature(actor_mod.BridgeActorIdentityStore.issue_envelope).parameters)
    verify_parameters = set(
        inspect.signature(actor_mod.BridgeActorIdentityStore.verify_and_consume).parameters
    )
    assert issue_parameters.isdisjoint(forbidden | {"ttl_seconds"})
    assert verify_parameters.isdisjoint(forbidden | {"expected_expires_at_ms"})
    assert {"request_body", "discord_event_id"} <= issue_parameters
    assert {"request_body", "discord_event_id"} <= verify_parameters

    store = _store(tmp_path)
    assert store.ready is True
    assert store.status_reason == "ready"
    assert actor_mod.GUILD_PARTICIPATION_ENABLED is False
    assert actor_mod.VOICE_ENABLED is False
    assert store.guild_participation_enabled is False
    assert store.voice_enabled is False


def test_constructor_dependencies_are_frozen_snapshots_and_cannot_be_rebound(
    tmp_path: Path,
):
    policy = actor_mod.BridgeActorPolicy(
        version=1,
        envelope_ttl_ms=30_000,
        max_body_bytes=1024,
        max_external_id_bytes=256,
        max_transport_bytes=4096,
        max_clock_advance_ms=60_000,
        max_incremental_audit_rows=16,
    )
    boundary = actor_mod.TrustedBridgeBoundary(
        service="discord-bridge",
        platform="discord",
        boundary_id="frozen-adapter",
    )
    clock = MutableClock()
    anchor = actor_mod.SQLiteMonotonicAnchor(tmp_path / "frozen-anchor.sqlite3")
    store = _store(
        tmp_path,
        clock=clock,
        policy=policy,
        boundary=boundary,
        anchor=anchor,
        anchor_name="unused.sqlite3",
    )
    replacement_policy = actor_mod.BridgeActorPolicy(
        version=1,
        max_body_bytes=6 * 1024 * 1024,
    )
    replacement_boundary = actor_mod.TrustedBridgeBoundary(
        service="other-bridge",
        platform="discord",
        boundary_id="other-adapter",
    )
    replacement_clock = FixedClock(NOW_MS + 50_000)
    replacement_anchor = MemoryAnchor()
    assignments = (
        ("db_path", tmp_path / "other.sqlite3"),
        ("key_version", 99),
        ("policy", replacement_policy),
        ("boundary", replacement_boundary),
        ("clock", replacement_clock),
        ("monotonic_anchor", replacement_anchor),
        ("_db_path", tmp_path / "other-private.sqlite3"),
        ("_key", b"z" * 32),
        ("_key_version", 99),
        ("_policy", replacement_policy),
        ("_boundary", replacement_boundary),
        ("_clock_ref", replacement_clock),
        ("_anchor_ref", replacement_anchor),
        ("_boundary_hmac", "0" * 64),
        ("_genesis_head", "0" * 64),
        ("_anchor_namespace", "0" * 64),
        ("_dependencies_frozen", False),
    )
    for name, value in assignments:
        with pytest.raises(AttributeError):
            setattr(store, name, value)
    with pytest.raises(AttributeError):
        anchor.db_path = tmp_path / "moved-anchor.sqlite3"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        anchor._db_path = tmp_path / "moved-private-anchor.sqlite3"  # type: ignore[misc]

    object.__setattr__(policy, "max_body_bytes", 6 * 1024 * 1024)
    object.__setattr__(boundary, "service", "mutated-source-bridge")
    exposed_policy = store.policy
    exposed_boundary = store.boundary
    object.__setattr__(exposed_policy, "max_body_bytes", 6 * 1024 * 1024)
    object.__setattr__(exposed_boundary, "service", "mutated-copy-bridge")

    assert store.policy.max_body_bytes == 1024
    assert store.boundary.service == "discord-bridge"
    assert store.clock is clock
    assert store.monotonic_anchor is anchor
    calls = clock.calls
    with pytest.raises(actor_mod.BridgeActorIdentityError, match="byte limit"):
        _issue(store, request_body=b"x" * 1025)
    assert clock.calls == calls
    envelope = _issue(store, discord_event_id="frozen-dependency-event")
    assert envelope.service == "discord-bridge"
    assert envelope.policy_version == 1


@pytest.mark.parametrize("key", [b"", b"x" * 16, b"x" * 31])
def test_key_material_must_be_at_least_32_bytes(tmp_path: Path, key: bytes):
    with pytest.raises(ValueError, match="at least 32 bytes"):
        _store(tmp_path, key=key)


def test_text_keys_and_same_database_anchor_are_rejected(tmp_path: Path):
    anchor_path = tmp_path / "same.sqlite3"
    anchor = actor_mod.SQLiteMonotonicAnchor(anchor_path)
    with pytest.raises(TypeError, match="bytes-like"):
        actor_mod.BridgeActorIdentityStore(
            tmp_path / "text.sqlite3",
            seal_key="x" * 32,  # type: ignore[arg-type]
            key_version=1,
            policy=POLICY,
            boundary=BOUNDARY,
            clock=MutableClock(),
            monotonic_anchor=anchor,
        )
    with pytest.raises(ValueError, match="external"):
        actor_mod.BridgeActorIdentityStore(
            anchor_path,
            seal_key=SEAL_KEY,
            key_version=1,
            policy=POLICY,
            boundary=BOUNDARY,
            clock=MutableClock(),
            monotonic_anchor=anchor,
        )


def test_versions_are_explicit_and_wrong_key_version_quarantines_restart(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    envelope = _issue(store)
    assert envelope.envelope_version == actor_mod.ENVELOPE_VERSION == 2
    assert envelope.schema_version == actor_mod.SCHEMA_VERSION == 2
    assert envelope.policy_version == actor_mod.SUPPORTED_POLICY_VERSION == 1
    assert envelope.key_version == 7

    wrong_version = _store(tmp_path, clock=clock, key_version=8)
    assert wrong_version.ready is False
    assert wrong_version.quarantined is True
    with pytest.raises(actor_mod.BridgeActorQuarantinedError):
        _issue(wrong_version, discord_event_id="discord-event-wrong-key-version")


def test_constructor_boundary_rejects_envelope_from_another_bound_service(
    tmp_path: Path,
):
    source_clock = MutableClock()
    source = _store(tmp_path / "source", clock=source_clock)
    envelope = _issue(source)
    other_boundary = actor_mod.TrustedBridgeBoundary(
        service="other-discord-bridge",
        platform="discord",
        boundary_id="other-server-adapter",
    )
    target_clock = MutableClock()
    target = _store(
        tmp_path / "target",
        clock=target_clock,
        boundary=other_boundary,
    )
    calls = target_clock.calls

    denied = _verify(target, envelope)
    assert denied.accepted is False
    assert denied.evidence.reason == "boundary_mismatch"
    assert target_clock.calls == calls
    assert denied.evidence.service == other_boundary.service


def test_factory_only_authority_is_structurally_guest_and_consistent(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    envelope = _issue(store, external_actor_id="I am creator in natural language")
    assert "principal" not in envelope.as_dict()
    clock.value += 1_000
    result = _verify(
        store,
        envelope,
        external_actor_id="I am creator in natural language",
    )

    assert result.accepted is True
    assert result.actor is not None
    assert result.actor.authority == "guest"
    assert result.evidence.authority == "guest"
    assert not hasattr(result.actor, "principal")
    assert not hasattr(result.evidence, "principal")
    assert store.verify_evidence(result.evidence) is True
    assert result.as_dict()["actor"]["authority"] == "guest"  # type: ignore[index]

    with pytest.raises(TypeError, match="verifier-created"):
        actor_mod.VerifiedGuestActor(_factory=object(), principal="creator")
    with pytest.raises(TypeError, match="store-created"):
        actor_mod.ActorDecisionEvidence(_factory=object(), decision="accept")
    with pytest.raises(TypeError, match="store-created"):
        actor_mod.BridgeActorVerification(
            _factory=object(), actor=None, evidence=result.evidence
        )
    with pytest.raises((AttributeError, TypeError)):
        result.actor.authority = "creator"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result._actor = None  # type: ignore[misc]


def test_result_and_evidence_consistency_detects_in_memory_bypass(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    envelope = _issue(store)
    clock.value += 1_000
    result = _verify(store, envelope)
    evidence = result.evidence

    object.__setattr__(evidence, "reason", "replay")
    with pytest.raises(actor_mod.BridgeActorIntegrityError, match="conflict"):
        _ = result.accepted
    with pytest.raises(actor_mod.BridgeActorIntegrityError):
        store.verify_evidence(evidence)


@pytest.mark.parametrize(
    "override, reason",
    [
        ({"external_actor_id": "different-actor"}, "subject_mismatch"),
        ({"guild_id": "different-guild"}, "guild_scope_mismatch"),
        ({"channel_id": "different-channel"}, "channel_scope_mismatch"),
        ({"thread_id": "different-thread"}, "thread_scope_mismatch"),
        ({"discord_event_id": "different-event"}, "event_mismatch"),
        ({"request_body": b"different actual bytes"}, "body_mismatch"),
    ],
)
def test_actual_body_event_and_scope_mismatches_do_not_consume(
    tmp_path: Path,
    override: dict[str, object],
    reason: str,
):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    envelope = _issue(store)
    clock.value += 1_000

    denied = _verify(store, envelope, **override)
    assert denied.accepted is False
    assert denied.actor is None
    assert denied.evidence.reason == reason
    assert _rows(store.db_path, ENVELOPE_TABLE)[0]["consumed_at_ms"] is None

    clock.value += 1_000
    accepted = _verify(store, envelope)
    assert accepted.accepted is True


def test_duplicate_body_with_distinct_event_ids_is_independently_valid(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    first = _issue(store, discord_event_id="discord-event-one")
    clock.value += 1_000
    second = _issue(store, discord_event_id="discord-event-two")

    assert first.body_hmac == second.body_hmac
    assert first.event_id_hmac != second.event_id_hmac
    assert first.envelope_id != second.envelope_id
    with pytest.raises(actor_mod.BridgeActorEventReplayError):
        _issue(store, discord_event_id="discord-event-one")

    clock.value += 1_000
    assert _verify(store, first, discord_event_id="discord-event-one").accepted
    clock.value += 1_000
    assert _verify(store, second, discord_event_id="discord-event-two").accepted


def test_request_bytes_and_external_ids_are_bounded_before_clock_or_storage(
    tmp_path: Path,
):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    calls = clock.calls
    state = dict(_state(store.db_path))

    with pytest.raises(actor_mod.BridgeActorIdentityError, match="byte limit"):
        _issue(store, request_body=b"x" * (POLICY.max_body_bytes + 1))
    with pytest.raises(actor_mod.BridgeActorIdentityError, match="event id is invalid"):
        _issue(
            store,
            discord_event_id="x" * (POLICY.max_external_id_bytes + 1),
        )
    assert clock.calls == calls
    assert _state(store.db_path) == state
    assert _rows(store.db_path, ENVELOPE_TABLE) == []


def test_explicit_six_mib_policy_signs_json_body_over_two_mib_and_rejects_above(
    tmp_path: Path,
):
    assert actor_mod.BridgeActorPolicy(version=1).max_body_bytes == 1_048_576
    six_mib = 6 * 1024 * 1024
    policy = actor_mod.BridgeActorPolicy(
        version=1,
        envelope_ttl_ms=30_000,
        max_body_bytes=six_mib,
        max_external_id_bytes=256,
        max_transport_bytes=4096,
        max_clock_advance_ms=60_000,
        max_incremental_audit_rows=16,
    )
    with pytest.raises(actor_mod.BridgeActorIdentityError, match="out of range"):
        actor_mod.BridgeActorPolicy(
            version=1,
            max_body_bytes=six_mib + 1,
        )
    encoded_image = base64.b64encode(b"\xff" * (2 * 1024 * 1024))
    body = b'{"image":"' + encoded_image + b'"}'
    assert len(body) > 2 * 1024 * 1024
    clock = MutableClock()
    store = _store(tmp_path, clock=clock, policy=policy)
    envelope = _issue(
        store,
        request_body=body,
        discord_event_id="large-json-image-event",
    )
    clock.value += 1_000
    accepted = _verify(
        store,
        envelope,
        request_body=body,
        discord_event_id="large-json-image-event",
    )
    assert accepted.accepted is True
    assert accepted.actor is not None
    assert accepted.actor.body_hmac == envelope.body_hmac

    before = dict(_state(store.db_path))
    calls = clock.calls
    with pytest.raises(actor_mod.BridgeActorIdentityError, match="byte limit"):
        _issue(
            store,
            request_body=b"x" * (six_mib + 1),
            discord_event_id="oversized-json-image-event",
        )
    assert clock.calls == calls
    assert _state(store.db_path) == before


def test_malformed_or_tampered_envelopes_never_read_or_advance_clock(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    envelope = _issue(store)
    high_water = int(_state(store.db_path)["high_water_ms"])
    calls = clock.calls
    clock.value = NOW_MS + POLICY.max_clock_advance_ms * 100

    malformed = _verify(store, "not-json RAW-UNTRUSTED-TOKEN")
    changed = envelope.as_dict()
    changed["body_hmac"] = "0" * 64
    tampered = _verify(store, changed)

    assert malformed.evidence.reason == "malformed_envelope"
    assert tampered.evidence.reason == "invalid_seal"
    assert clock.calls == calls
    assert int(_state(store.db_path)["high_water_ms"]) == high_water
    assert "RAW-UNTRUSTED-TOKEN" not in json.dumps(malformed.as_dict())

    clock.value = NOW_MS + 1_000
    assert _verify(store, envelope).accepted is True


def test_future_clock_poisoning_and_rollback_leave_state_unchanged(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    first = _issue(store)
    before = dict(_state(store.db_path))

    clock.value = NOW_MS + POLICY.max_clock_advance_ms + 1
    with pytest.raises(actor_mod.BridgeActorFutureClockError):
        _issue(store, discord_event_id="future-poison-event")
    assert _state(store.db_path) == before

    clock.value = NOW_MS + 1_000
    second = _issue(store, discord_event_id="future-poison-event")
    assert second.issued_at_ms == NOW_MS + 1_000

    clock.value = NOW_MS
    with pytest.raises(actor_mod.BridgeActorClockRollbackError):
        _issue(store, discord_event_id="rollback-event")
    assert len(_rows(store.db_path, ENVELOPE_TABLE)) == 2

    clock.value = NOW_MS + 2_000
    assert _verify(store, first).accepted is True


def test_restart_preserves_replay_and_stable_guest_subject(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    envelope = _issue(store)
    clock.value += 1_000
    assert _verify(store, envelope).accepted is True

    restarted = _store(tmp_path, clock=clock)
    clock.value += 1_000
    replay = _verify(restarted, envelope)
    assert replay.accepted is False
    assert replay.evidence.reason == "replay"
    clock.value += 1_000
    next_envelope = _issue(restarted, discord_event_id="next-discord-event")
    assert next_envelope.actor_subject_hmac == envelope.actor_subject_hmac


def test_valid_database_snapshot_rollback_is_quarantined(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    envelope = _issue(store)
    snapshot = tmp_path / "valid-old-snapshot.sqlite3"
    shutil.copy2(store.db_path, snapshot)

    clock.value += 1_000
    assert _verify(store, envelope).accepted is True
    assert store.full_audit().ok is True
    shutil.copy2(snapshot, store.db_path)

    rolled_back = _store(tmp_path, clock=clock)
    assert rolled_back.ready is False
    assert rolled_back.quarantined is True
    assert rolled_back.status_reason == "database_snapshot_rollback"
    with pytest.raises(actor_mod.BridgeActorQuarantinedError):
        _issue(rolled_back, discord_event_id="blocked-after-rollback")
    report = rolled_back.full_audit()
    assert report.ok is False
    assert report.reason == "database_snapshot_rollback"


def test_database_truncation_is_quarantined_by_automatic_gate(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    envelope = _issue(store)
    clock.value += 1_000
    result = _verify(store, envelope)
    with connect(store.db_path) as conn:
        conn.execute("DROP TRIGGER bridge_actor_v2_evidence_no_delete")
        conn.execute(
            f"DELETE FROM {EVIDENCE_TABLE} WHERE evidence_id=?",
            (result.evidence.evidence_id,),
        )
        conn.execute(
            f"""
            CREATE TRIGGER bridge_actor_v2_evidence_no_delete
            BEFORE DELETE ON {EVIDENCE_TABLE}
            BEGIN
                SELECT RAISE(ABORT, 'bridge actor evidence is immutable');
            END
            """
        )

    truncated = _store(tmp_path, clock=clock)
    assert truncated.ready is False
    assert truncated.quarantined is True
    assert truncated.status_reason == "sealed_state_integrity_failure"
    with pytest.raises(actor_mod.BridgeActorQuarantinedError):
        _verify(truncated, envelope)
    report = truncated.full_audit()
    assert report.ok is False
    assert report.reason == "sealed_state_integrity_failure"


def test_same_name_noop_trigger_quarantines_at_startup_before_issue(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    _issue(store)
    with connect(store.db_path) as conn:
        conn.execute("DROP TRIGGER bridge_actor_v2_nonce_once")
        conn.execute(
            f"""
            CREATE TRIGGER bridge_actor_v2_nonce_once
            AFTER UPDATE ON {ENVELOPE_TABLE}
            BEGIN
                SELECT 1;
            END
            """
        )
    calls = clock.calls

    restarted = _store(tmp_path, clock=clock)
    assert restarted.ready is False
    assert restarted.quarantined is True
    assert restarted.status_reason == "schema_definition_mismatch"
    assert clock.calls == calls
    with pytest.raises(actor_mod.BridgeActorQuarantinedError) as quarantined:
        _issue(restarted, discord_event_id="blocked-by-noop-trigger")
    assert quarantined.value.reason == "schema_definition_mismatch"
    assert len(_rows(store.db_path, ENVELOPE_TABLE)) == 1


def test_dropped_required_index_quarantines_runtime_and_restart_before_consume(
    tmp_path: Path,
):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    envelope = _issue(store)
    with connect(store.db_path) as conn:
        conn.execute("DROP INDEX bridge_actor_v2_one_accept_idx")
    clock.value += 1_000
    calls = clock.calls

    with pytest.raises(actor_mod.BridgeActorQuarantinedError) as quarantined:
        _verify(store, envelope)
    assert quarantined.value.reason == "schema_object_missing"
    assert store.quarantined is True
    assert store.status_reason == "schema_object_missing"
    assert clock.calls == calls
    assert _rows(store.db_path, ENVELOPE_TABLE)[0]["consumed_at_ms"] is None
    assert _rows(store.db_path, EVIDENCE_TABLE) == []
    report = store.full_audit()
    assert report.ok is False
    assert report.reason == "schema_object_missing"

    restarted = _store(tmp_path, clock=clock)
    assert restarted.quarantined is True
    assert restarted.status_reason == "schema_object_missing"


def test_anchor_schema_substitution_quarantines_before_issue(tmp_path: Path):
    clock = MutableClock()
    anchor = actor_mod.SQLiteMonotonicAnchor(tmp_path / "anchor-schema.sqlite3")
    store = _store(
        tmp_path,
        clock=clock,
        anchor=anchor,
        anchor_name="unused.sqlite3",
    )
    with connect(anchor.db_path) as conn:
        conn.execute("DROP TRIGGER bridge_actor_anchor_monotonic")
        conn.execute(
            """
            CREATE TRIGGER bridge_actor_anchor_monotonic
            AFTER UPDATE ON bridge_actor_monotonic_anchor
            BEGIN
                SELECT 1;
            END
            """
        )
    calls = clock.calls

    with pytest.raises(actor_mod.BridgeActorQuarantinedError) as quarantined:
        _issue(store, discord_event_id="blocked-by-anchor-schema")
    assert quarantined.value.reason == "anchor_schema_definition_mismatch"
    assert store.quarantined is True
    assert clock.calls == calls
    assert _rows(store.db_path, ENVELOPE_TABLE) == []


def test_routine_issue_and_consume_do_not_run_exhaustive_count_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("routine gate invoked exhaustive count scan")

    monkeypatch.setattr(
        actor_mod.BridgeActorIdentityStore,
        "_check_counts",
        fail_if_called,
    )
    envelope = _issue(store)
    clock.value += 1_000
    assert _verify(store, envelope).accepted is True


def test_explicit_full_audit_verifies_every_record_and_seal(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    first = _issue(store, discord_event_id="audit-event-one")
    clock.value += 1_000
    second = _issue(store, discord_event_id="audit-event-two")
    clock.value += 1_000
    assert _verify(store, first, discord_event_id="audit-event-one").accepted
    clock.value += 1_000
    denied = _verify(
        store,
        second,
        discord_event_id="audit-event-two",
        request_body=b"wrong-body",
    )
    assert denied.evidence.reason == "body_mismatch"

    report = store.full_audit()
    assert report.ok is True
    assert report.revision == 4
    assert report.rows_verified == 4
    assert report.anchor_revision == 4

    with connect(store.db_path) as conn:
        conn.execute("DROP TRIGGER bridge_actor_v2_audit_no_update")
        conn.execute(
            f"UPDATE {AUDIT_TABLE} SET record_hmac=? WHERE revision=1",
            ("0" * 64,),
        )
        conn.execute(
            f"""
            CREATE TRIGGER bridge_actor_v2_audit_no_update
            BEFORE UPDATE ON {AUDIT_TABLE}
            BEGIN
                SELECT RAISE(ABORT, 'bridge actor audit is immutable');
            END
            """
        )
    tampered = store.full_audit()
    assert tampered.ok is False
    assert tampered.reason == "sealed_state_integrity_failure"
    assert store.quarantined is True


def test_bounded_recovery_requires_then_accepts_explicit_full_audit(tmp_path: Path):
    policy = actor_mod.BridgeActorPolicy(
        version=1,
        envelope_ttl_ms=30_000,
        max_body_bytes=1024,
        max_external_id_bytes=256,
        max_transport_bytes=4096,
        max_clock_advance_ms=60_000,
        max_incremental_audit_rows=1,
    )
    anchor = MemoryAnchor()
    clock = MutableClock()
    store = _store(tmp_path, clock=clock, policy=policy, anchor=anchor)
    genesis = anchor.snapshot()
    envelope = _issue(store)
    clock.value += 1_000
    assert _verify(store, envelope).accepted
    anchor.force_snapshot(genesis)

    pending = _store(tmp_path, clock=clock, policy=policy, anchor=anchor)
    assert pending.ready is False
    assert pending.quarantined is False
    assert pending.status_reason == "full_audit_required"
    with pytest.raises(actor_mod.BridgeActorNotReadyError):
        _issue(pending, discord_event_id="blocked-until-full-audit")

    report = pending.full_audit(reconcile_anchor=True)
    assert report.ok is True
    assert pending.ready is True
    clock.value += 1_000
    assert _issue(pending, discord_event_id="after-full-audit")


def test_pluggable_anchor_automatically_recovers_bounded_lag(tmp_path: Path):
    anchor = MemoryAnchor()
    clock = MutableClock()
    store = _store(tmp_path, clock=clock, anchor=anchor)
    genesis = anchor.snapshot()
    _issue(store)
    anchor.force_snapshot(genesis)

    recovered = _store(tmp_path, clock=clock, anchor=anchor)
    assert recovered.ready is True
    assert recovered.status_reason == "ready"
    assert recovered.full_audit().ok is True


def test_thread_contention_has_one_atomic_winner(tmp_path: Path):
    issue_clock = MutableClock()
    first_store = _store(tmp_path, clock=issue_clock)
    envelope = _issue(first_store)
    first_clock = FixedClock(NOW_MS + 1_000)
    second_clock = FixedClock(NOW_MS + 1_000)
    first_store = _store(tmp_path, clock=first_clock)
    second_store = _store(tmp_path, clock=second_clock)
    barrier = threading.Barrier(2)

    def consume(store: actor_mod.BridgeActorIdentityStore):
        barrier.wait(timeout=5)
        return _verify(store, envelope)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(consume, item) for item in (first_store, second_store)]
        outcomes = [future.result(timeout=15) for future in futures]

    assert sum(result.accepted for result in outcomes) == 1
    assert sorted(result.evidence.reason for result in outcomes) == ["accepted", "replay"]
    assert len({result.evidence.evidence_id for result in outcomes}) == 2
    assert first_store.full_audit().ok is True


def test_spawned_process_contention_has_one_atomic_winner(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    envelope = _issue(store)
    anchor_path = tmp_path / "bridge-anchor.sqlite3"
    arguments = (
        str(store.db_path),
        str(anchor_path),
        envelope.encode(),
        BODY,
        EVENT_ID,
        ACTOR_ID,
        GUILD_ID,
        CHANNEL_ID,
        THREAD_ID,
    )
    context = multiprocessing.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=2,
        mp_context=context,
    ) as executor:
        futures = [executor.submit(_process_consume, arguments) for _ in range(2)]
        outcomes = [future.result(timeout=30) for future in futures]

    assert sum(accepted for accepted, _reason, _evidence_id in outcomes) == 1
    assert sorted(reason for _accepted, reason, _evidence_id in outcomes) == [
        "accepted",
        "replay",
    ]
    assert len({evidence_id for _accepted, _reason, evidence_id in outcomes}) == 2
    restarted = _store(tmp_path, clock=FixedClock(NOW_MS + 2_000))
    assert restarted.full_audit().ok is True


def test_plaintext_ids_content_digest_keys_and_boundary_never_leak(tmp_path: Path):
    raw_event = "raw-discord-event-marker-94857"
    raw_actor = "raw-discord-actor-marker-83746"
    raw_guild = "raw-discord-guild-marker-72635"
    raw_channel = "raw-discord-channel-marker-61524"
    raw_thread = "raw-discord-thread-marker-50413"
    raw_name = "Raw Display Name Marker"
    raw_message = "private message marker 7f45"
    raw_token = "discord.bot.token.raw.marker"
    raw_phone = "+1-555-0109 raw phone marker"
    raw_url = "https://private.example.invalid/raw-url-marker"
    raw_secret = "creator-secret-raw-marker"
    body = "|".join(
        (raw_name, raw_message, raw_token, raw_phone, raw_url, raw_secret)
    ).encode("utf-8")
    plain_sha256 = hashlib.sha256(body).hexdigest()
    boundary = actor_mod.TrustedBridgeBoundary(
        service="discord-bridge",
        platform="discord",
        boundary_id="private-adapter-marker",
    )
    key = b"K" * 32
    clock = MutableClock()
    store = _store(tmp_path, clock=clock, boundary=boundary, key=key)
    envelope = _issue(
        store,
        request_body=body,
        discord_event_id=raw_event,
        external_actor_id=raw_actor,
        guild_id=raw_guild,
        channel_id=raw_channel,
        thread_id=raw_thread,
    )
    clock.value += 1_000
    result = _verify(
        store,
        envelope,
        request_body=body,
        discord_event_id=raw_event,
        external_actor_id=raw_actor,
        guild_id=raw_guild,
        channel_id=raw_channel,
        thread_id=raw_thread,
    )
    report = store.full_audit()
    public = json.dumps(
        {
            "envelope": envelope.as_dict(),
            "result": result.as_dict(),
            "evidence": [item.as_dict() for item in store.list_evidence()],
            "audit": asdict(report),
        },
        sort_keys=True,
    )
    with connect(tmp_path / "bridge-anchor.sqlite3") as conn:
        anchor_rows = [
            dict(row)
            for row in conn.execute("SELECT * FROM bridge_actor_monotonic_anchor")
        ]
    persisted = json.dumps(
        {
            "state": _rows(store.db_path, STATE_TABLE),
            "envelopes": _rows(store.db_path, ENVELOPE_TABLE),
            "evidence": _rows(store.db_path, EVIDENCE_TABLE),
            "audit": _rows(store.db_path, AUDIT_TABLE),
            "anchor": anchor_rows,
        },
        sort_keys=True,
    )
    raw_values = (
        raw_event,
        raw_actor,
        raw_guild,
        raw_channel,
        raw_thread,
        raw_name,
        raw_message,
        raw_token,
        raw_phone,
        raw_url,
        raw_secret,
        body.decode("utf-8"),
        plain_sha256,
        boundary.boundary_id,
        key.decode("ascii"),
    )
    database_files = [
        path for path in tmp_path.glob("*.sqlite3*") if path.is_file()
    ]
    assert database_files
    for raw in raw_values:
        assert raw not in public
        assert raw not in persisted
        assert all(raw.encode("utf-8") not in path.read_bytes() for path in database_files)
    assert "request_digest" not in public
    assert "request_digest" not in persisted
    for field in (
        "boundary_hmac",
        "actor_subject_hmac",
        "guild_scope_hmac",
        "channel_scope_hmac",
        "thread_scope_hmac",
        "event_id_hmac",
        "body_hmac",
        "nonce_hmac",
        "envelope_id",
        "seal",
    ):
        assert _is_hmac(envelope.as_dict()[field])


def test_database_immutability_triggers_remain_enforced(tmp_path: Path):
    clock = MutableClock()
    store = _store(tmp_path, clock=clock)
    envelope = _issue(store)
    clock.value += 1_000
    evidence = _verify(store, envelope).evidence

    with connect(store.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="envelope is immutable"):
            conn.execute(
                f"UPDATE {ENVELOPE_TABLE} SET body_hmac=? WHERE envelope_id=?",
                ("0" * 64, envelope.envelope_id),
            )
    with connect(store.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="evidence is immutable"):
            conn.execute(
                f"UPDATE {EVIDENCE_TABLE} SET reason='replay' WHERE evidence_id=?",
                (evidence.evidence_id,),
            )
    with connect(store.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="single-use"):
            conn.execute(
                f"UPDATE {ENVELOPE_TABLE} SET consumed_at_ms=NULL WHERE envelope_id=?",
                (envelope.envelope_id,),
            )
    with connect(store.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="audit is immutable"):
            conn.execute(f"DELETE FROM {AUDIT_TABLE} WHERE revision=1")
