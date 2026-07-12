"""Security, recovery, privacy, and race tests for Phase 9M egress consent."""
from __future__ import annotations

import concurrent.futures
import inspect
import json
import shutil
import sqlite3
import threading
from collections import deque
from contextlib import contextmanager
from pathlib import Path

import pytest

from alpecca import egress_consent as consent_mod
from alpecca.db import connect


NOW = 10_000.0
SEAL_KEY = b"phase9-egress-main-seal-key"
ANCHOR_KEY = b"phase9-egress-external-anchor-key"
SEAL_VERSION = "egress-seal-v2"
ANCHOR_KEY_VERSION = "anchor-seal-v1"
PRIMARY_ROUTE = "vision-primary"
FALLBACK_ROUTE = "vision-fallback"
OPERATION_A = "op_" + "A" * 24
OPERATION_B = "op_" + "B" * 24
METADATA = b'{"mime":"image/png","sha256":"PRIVATE-DIGEST-MARKER"}'


class ManualClock:
    def __init__(self, value: float = NOW) -> None:
        self.value = value

    def now(self) -> float:
        return self.value


class FakeAuthority:
    authority_id = "trusted-creator-ui"
    version = 1
    creator_scope = "creator-private"

    def __init__(self) -> None:
        self.decisions: deque[consent_mod.CreatorDecision] = deque()
        self.requests: list[consent_mod.AuthorityRequest] = []
        self._counter = 0

    def queue(self, allowed: bool, *, decision_id: str | None = None) -> str:
        self._counter += 1
        identifier = decision_id or (
            "decision_" + f"{self._counter:024d}"
        )
        self.decisions.append(consent_mod.CreatorDecision(identifier, allowed))
        return identifier

    def decide(
        self, request: consent_mod.AuthorityRequest
    ) -> consent_mod.CreatorDecision:
        self.requests.append(request)
        if not self.decisions:
            raise RuntimeError("test authority has no queued creator decision")
        return self.decisions.popleft()


class MemoryAnchor:
    def __init__(self) -> None:
        self.state: consent_mod.AnchorState | None = None

    def load(self) -> consent_mod.AnchorState | None:
        return self.state

    def initialize(self, state: consent_mod.AnchorState) -> None:
        if self.state is not None:
            raise RuntimeError("already initialized")
        self.state = state

    def advance(
        self,
        expected: consent_mod.AnchorState,
        updated: consent_mod.AnchorState,
    ) -> None:
        if self.state != expected:
            raise RuntimeError("compare-and-swap failed")
        self.state = updated


def _policy(
    *,
    version: int = 1,
    primary_ttl: int = 30,
    primary_uses: int = 2,
    primary_deployment: str = "vision-deployment-a",
    primary_model: str = "acme/private-vision-v2",
) -> consent_mod.EgressPolicy:
    return consent_mod.EgressPolicy(
        policy_id="private-perception-egress",
        version=version,
        routes=(
            consent_mod.AllowedEgressRoute(
                route_id=PRIMARY_ROUTE,
                provider="provider-a",
                deployment=primary_deployment,
                model=primary_model,
                capability="private-image-description",
                purpose="describe-private-image",
                processing_location="us-west-2",
                destination_class="managed-model-api",
                transport_route="https://vision.example.test/v1/infer",
                ttl_seconds=primary_ttl,
                max_uses=primary_uses,
                max_bytes_per_use=2048,
            ),
            consent_mod.AllowedEgressRoute(
                route_id=FALLBACK_ROUTE,
                provider="provider-b",
                deployment="vision-deployment-b",
                model="other/private-vision-v1",
                capability="private-image-description",
                purpose="describe-private-image",
                processing_location="eu-west-1",
                destination_class="managed-model-api",
                transport_route="https://fallback.example.test/v2/infer",
                ttl_seconds=20,
                max_uses=1,
                max_bytes_per_use=1024,
            ),
        ),
    )


def _anchor(path: Path) -> consent_mod.SQLiteMonotonicAnchor:
    return consent_mod.SQLiteMonotonicAnchor(
        path,
        anchor_key=ANCHOR_KEY,
        anchor_key_version=ANCHOR_KEY_VERSION,
    )


def _ledger(
    tmp_path: Path,
    *,
    clock: ManualClock | None = None,
    authority: FakeAuthority | None = None,
    policy: consent_mod.EgressPolicy | None = None,
    seal_key: bytes = SEAL_KEY,
    seal_key_version: str = SEAL_VERSION,
    db_name: str = "egress.db",
    anchor_name: str = "egress-anchor.db",
    anchor: consent_mod.MonotonicAnchor | None = None,
) -> tuple[
    consent_mod.EgressConsentLedger,
    ManualClock,
    FakeAuthority,
    consent_mod.MonotonicAnchor,
]:
    active_clock = clock or ManualClock()
    active_authority = authority or FakeAuthority()
    active_anchor = anchor or _anchor(tmp_path / anchor_name)
    ledger = consent_mod.EgressConsentLedger(
        tmp_path / db_name,
        seal_key=seal_key,
        seal_key_version=seal_key_version,
        authority=active_authority,
        policy=policy or _policy(),
        clock=active_clock,
        anchor=active_anchor,
    )
    return ledger, active_clock, active_authority, active_anchor


def _request(
    ledger: consent_mod.EgressConsentLedger,
    *,
    operation_id: str = OPERATION_A,
    route_id: str = PRIMARY_ROUTE,
    payload_metadata: bytes = METADATA,
    byte_count: int = 512,
) -> dict[str, object]:
    return ledger.request_consent(
        operation_id=operation_id,
        route_id=route_id,
        payload_metadata=payload_metadata,
        byte_count=byte_count,
    )


def _consume_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "operation_id": OPERATION_A,
        "route_id": PRIMARY_ROUTE,
        "payload_metadata": METADATA,
        "byte_count": 512,
    }
    values.update(overrides)
    return values


def _grant_row(db_path: Path, consent_id: object) -> dict[str, object]:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM egress_consents WHERE consent_id=?", (consent_id,)
        ).fetchone()
    assert row is not None
    return dict(row)


def _receipts(db_path: Path) -> list[dict[str, object]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM egress_consent_receipts ORDER BY receipt_sequence"
        ).fetchall()
    return [dict(row) for row in rows]


def _meta(db_path: Path) -> dict[str, object]:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM egress_consent_meta WHERE singleton=1"
        ).fetchone()
    assert row is not None
    return dict(row)


def _snapshot(db_path: Path) -> str:
    with connect(db_path) as conn:
        value = {
            "meta": [
                dict(row)
                for row in conn.execute("SELECT * FROM egress_consent_meta").fetchall()
            ],
            "grants": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM egress_consents ORDER BY id"
                ).fetchall()
            ],
            "receipts": [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM egress_consent_receipts ORDER BY receipt_sequence"
                ).fetchall()
            ],
        }
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _generation(anchor: consent_mod.MonotonicAnchor) -> int:
    state = anchor.load()
    assert state is not None
    return state.generation


def _collect_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(_collect_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(_collect_keys(item))
        return keys
    return set()


def test_public_api_removes_caller_asserted_trust_routes_and_clock(tmp_path: Path):
    ledger, _clock, authority, anchor = _ledger(tmp_path)
    request_parameters = set(inspect.signature(ledger.request_consent).parameters)
    consume_parameters = set(inspect.signature(ledger.consume).parameters)
    internal_parameters = set(inspect.signature(ledger.consume_active).parameters)

    forbidden = {
        "decision",
        "principal",
        "creator_scope",
        "provider",
        "deployment",
        "model",
        "capability",
        "purpose",
        "processing_location",
        "destination_class",
        "transport_route",
        "ttl_seconds",
        "max_uses",
        "max_bytes_per_use",
        "now",
    }
    assert request_parameters.isdisjoint(forbidden)
    assert consume_parameters.isdisjoint(forbidden)
    assert internal_parameters.isdisjoint(forbidden | {"token"})

    generation = _generation(anchor)
    with pytest.raises(TypeError):
        ledger.request_consent(
            **_consume_values(), principal="creator"  # type: ignore[arg-type]
        )
    assert not authority.requests
    assert _generation(anchor) == generation

    with pytest.raises(consent_mod.EgressConsentDenied) as unknown:
        _request(ledger, route_id="unknown-cloud-route")
    assert unknown.value.reason == "route_not_allowed"
    assert not authority.requests
    assert _generation(anchor) == generation


def test_constructor_dependencies_are_frozen_and_reassignment_is_rejected(
    tmp_path: Path,
):
    ledger, _clock, _authority, _anchor_store = _ledger(tmp_path)
    replacements = {
        "policy": _policy(version=2),
        "authority": FakeAuthority(),
        "clock": ManualClock(NOW + 10),
        "anchor": MemoryAnchor(),
    }
    originals = {name: getattr(ledger, name) for name in replacements}

    for name, replacement in replacements.items():
        with pytest.raises(AttributeError, match="read-only"):
            setattr(ledger, name, replacement)
        assert getattr(ledger, name) is originals[name]

    for name, replacement in {
        "_policy": replacements["policy"],
        "_authority": replacements["authority"],
        "_clock": replacements["clock"],
        "_anchor": replacements["anchor"],
    }.items():
        with pytest.raises(AttributeError, match="read-only"):
            setattr(ledger, name, replacement)
        with pytest.raises(AttributeError, match="read-only"):
            delattr(ledger, name)

def test_injected_authority_owns_creator_decision_and_exact_route_identity(
    tmp_path: Path,
):
    ledger, _clock, authority, _anchor_store = _ledger(tmp_path)
    authority.queue(True)

    grant = _request(ledger)

    assert grant["granted"] is True
    assert grant["creator_scope"] == authority.creator_scope
    request = authority.requests[-1]
    assert request.action == "private_cloud_egress"
    assert request.provider == "provider-a"
    assert request.deployment == "vision-deployment-a"
    assert request.model == "acme/private-vision-v2"
    assert request.purpose == "describe-private-image"
    assert request.destination_class == "managed-model-api"
    assert request.transport_route == "https://vision.example.test/v1/infer"
    assert request.operation_hmac != OPERATION_A
    assert request.payload_hmac not in METADATA.decode("ascii")
    assert grant["route"]["deployment"] == "vision-deployment-a"
    assert grant["route"]["model"] == "acme/private-vision-v2"


def test_creator_denial_is_authority_issued_and_receipted(tmp_path: Path):
    ledger, _clock, authority, _anchor_store = _ledger(tmp_path)
    decision_id = authority.queue(False)

    result = _request(ledger)

    assert result["granted"] is False
    assert result["decision"] == "deny"
    assert "token" not in result
    assert result["receipt"]["event"] == "deny"
    assert result["receipt"]["reason"] == "creator_denied"
    persisted = ledger.db_path.read_bytes()
    assert decision_id.encode("ascii") not in persisted
    assert OPERATION_A.encode("ascii") not in persisted


@pytest.mark.parametrize(
    "override,reason",
    [
        ({"operation_id": OPERATION_B}, "operation_mismatch"),
        ({"payload_metadata": b'{"different":"metadata"}'}, "payload_mismatch"),
        ({"byte_count": 511}, "byte_count_mismatch"),
        ({"route_id": FALLBACK_ROUTE}, "route_mismatch"),
    ],
)
def test_operation_payload_bytes_and_route_are_exact_hmac_bindings(
    tmp_path: Path, override: dict[str, object], reason: str
):
    ledger, _clock, authority, anchor = _ledger(tmp_path)
    authority.queue(True)
    grant = _request(ledger)
    before_grant = _grant_row(ledger.db_path, grant["consent_id"])
    before_receipts = len(_receipts(ledger.db_path))
    generation = _generation(anchor)

    with pytest.raises(consent_mod.EgressConsentDenied) as denied:
        ledger.consume(str(grant["token"]), **_consume_values(**override))
    assert denied.value.reason == reason

    assert _grant_row(ledger.db_path, grant["consent_id"]) == before_grant
    assert len(_receipts(ledger.db_path)) == before_receipts
    assert _generation(anchor) == generation + 1


def test_tokenless_internal_consume_is_atomic_and_returns_ordered_attempt_evidence(
    tmp_path: Path,
):
    ledger, clock, authority, _anchor_store = _ledger(tmp_path)
    authority.queue(True)
    grant = _request(ledger)
    clock.value += 1

    first = ledger.consume_active(**_consume_values())
    clock.value += 1
    second = ledger.consume_active(**_consume_values())

    assert first["uses"] == 1
    assert second["uses"] == 2
    assert second["state"] == "stopped"
    assert first["attempt_evidence"] == {
        "attempt_id": first["use_receipt"]["receipt_id"],
        "order": first["use_receipt"]["order"],
        "attempt_ordinal": 1,
        "consent_id": grant["consent_id"],
        "route": {
            "route_id": PRIMARY_ROUTE,
            "provider": "provider-a",
            "deployment": "vision-deployment-a",
            "model": "acme/private-vision-v2",
            "capability": "private-image-description",
            "purpose": "describe-private-image",
            "processing_location": "us-west-2",
            "destination_class": "managed-model-api",
            "transport": "https",
        },
        "byte_count": 512,
        "authorized_at": NOW + 1,
        "outcome": "authorized_before_outbound",
    }
    assert second["attempt_evidence"]["order"] > first["attempt_evidence"]["order"]
    assert second["attempt_evidence"]["attempt_ordinal"] == 2
    assert _collect_keys(first).isdisjoint(
        {"token", "token_hmac", "operation_hmac", "payload_hmac", "route_hmac"}
    )


def test_each_tokenless_call_consumes_at_most_one_use_under_concurrency(
    tmp_path: Path,
):
    policy = _policy(primary_uses=3)
    ledger, clock, authority, anchor = _ledger(tmp_path, policy=policy)
    authority.queue(True)
    grant = _request(ledger)
    clock.value += 1
    initial_generation = _generation(anchor)
    workers = 8
    barrier = threading.Barrier(workers)

    def consume_once() -> tuple[str, int | str]:
        barrier.wait(timeout=5)
        try:
            result = ledger.consume_active(**_consume_values())
        except consent_mod.EgressConsentDenied as exc:
            return "denied", exc.reason
        return "allowed", int(result["uses"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        outcomes = [
            future.result(timeout=20)
            for future in [executor.submit(consume_once) for _ in range(workers)]
        ]

    assert sorted(value for kind, value in outcomes if kind == "allowed") == [1, 2, 3]
    assert [kind for kind, _value in outcomes].count("denied") == 5
    row = _grant_row(ledger.db_path, grant["consent_id"])
    assert row["uses"] == 3
    assert row["state"] == "stopped"
    assert [item["event"] for item in _receipts(ledger.db_path)] == [
        "grant",
        "use",
        "use",
        "use",
        "stop",
    ]
    assert _generation(anchor) == initial_generation + workers


def test_raw_operation_metadata_token_decision_and_transport_never_persist_or_publish(
    tmp_path: Path,
):
    ledger, clock, authority, anchor = _ledger(tmp_path)
    decision_id = authority.queue(True)
    raw_metadata = (
        b"RAW-PAYLOAD PRIVATE-PROMPT C:/private/photo.png "
        b"https://private.invalid/upload digest=0123456789abcdef"
    )
    grant = _request(ledger, payload_metadata=raw_metadata)
    token = str(grant["token"])
    clock.value += 1
    ledger.consume_active(**_consume_values(payload_metadata=raw_metadata))
    status = ledger.status()

    public_json = json.dumps(status, sort_keys=True)
    persisted = ledger.db_path.read_bytes()
    anchor_path = anchor.path
    anchor_bytes = anchor_path.read_bytes()
    for raw in (
        raw_metadata,
        OPERATION_A.encode("ascii"),
        token.encode("ascii"),
        decision_id.encode("ascii"),
        b"https://vision.example.test/v1/infer",
    ):
        assert raw not in persisted
        assert raw not in anchor_bytes
        assert raw.decode("ascii") not in public_json
    assert _collect_keys(status).isdisjoint(
        {
            "token",
            "token_hmac",
            "operation_hmac",
            "payload_hmac",
            "decision_hmac",
            "route_hmac",
            "transport_route",
            "grant_seal",
            "receipt_seal",
        }
    )


def test_main_database_snapshot_rollback_is_detected_and_quarantined(tmp_path: Path):
    ledger, clock, authority, anchor = _ledger(tmp_path)
    authority.queue(True)
    grant = _request(ledger)
    old_db = tmp_path / "old-main-snapshot.db"
    shutil.copy2(ledger.db_path, old_db)
    clock.value += 1
    ledger.consume_active(**_consume_values())
    assert _generation(anchor) == 3

    shutil.copy2(old_db, ledger.db_path)
    restored, _clock, _authority, _anchor_store = _ledger(
        tmp_path,
        clock=clock,
        authority=authority,
        policy=ledger.policy,
    )

    assert restored.ready is False
    assert restored.quarantined is True
    assert restored.quarantine_reason == "database_rollback_detected"
    assert restored.status()["reason"] == "database_rollback_detected"
    with pytest.raises(consent_mod.EgressConsentQuarantined):
        restored.consume(str(grant["token"]), **_consume_values())
    assert [row["event"] for row in _receipts(restored.db_path)] == ["grant"]


def test_external_anchor_snapshot_rollback_is_detected(tmp_path: Path):
    ledger, clock, authority, anchor = _ledger(tmp_path)
    authority.queue(True)
    _request(ledger)
    old_anchor = tmp_path / "old-anchor-snapshot.db"
    shutil.copy2(anchor.path, old_anchor)
    clock.value += 1
    ledger.consume_active(**_consume_values())

    shutil.copy2(old_anchor, anchor.path)
    restored, _clock, _authority, _anchor_store = _ledger(
        tmp_path,
        clock=clock,
        authority=authority,
        policy=ledger.policy,
    )

    assert restored.ready is False
    assert restored.quarantine_reason == "external_anchor_rollback_detected"


def test_noop_clock_observations_advance_external_high_water(tmp_path: Path):
    ledger, clock, authority, anchor = _ledger(tmp_path)
    assert _generation(anchor) == 1

    ledger.status()
    assert _generation(anchor) == 2
    ledger.audit()
    assert _generation(anchor) == 3

    with pytest.raises(consent_mod.EgressConsentDenied) as invalid:
        ledger.consume("ec2_" + "x" * 43, **_consume_values())
    assert invalid.value.reason == "consent_not_found"
    assert _generation(anchor) == 4

    repeated = authority.queue(False, decision_id="decision_" + "9" * 24)
    _request(ledger, operation_id=OPERATION_A)
    assert _generation(anchor) == 5
    authority.queue(False, decision_id=repeated)
    with pytest.raises(consent_mod.EgressConsentDenied) as replay:
        _request(ledger, operation_id=OPERATION_B)
    assert replay.value.reason == "authority_decision_replay"
    assert _generation(anchor) == 6
    assert clock.value == NOW


def test_trusted_clock_rollback_quarantines_without_mutating_grant(tmp_path: Path):
    ledger, clock, authority, anchor = _ledger(tmp_path)
    authority.queue(True)
    grant = _request(ledger)
    before = _snapshot(ledger.db_path)
    generation = _generation(anchor)
    clock.value = NOW - 1

    with pytest.raises(consent_mod.EgressConsentQuarantined) as rollback:
        ledger.consume(str(grant["token"]), **_consume_values())

    assert rollback.value.reason == "trusted_clock_rollback"
    assert ledger.ready is False
    assert ledger.quarantine_reason == "trusted_clock_rollback"
    assert _snapshot(ledger.db_path) == before
    assert _generation(anchor) == generation
    for method in (ledger.request_consent, ledger.consume, ledger.consume_active):
        assert "now" not in inspect.signature(method).parameters


def test_constructor_automatically_stops_active_pre_restart_consent(tmp_path: Path):
    ledger, clock, authority, anchor = _ledger(tmp_path)
    authority.queue(True)
    grant = _request(ledger)
    before_restart = _generation(anchor)

    restarted, _clock, _authority, _anchor_store = _ledger(
        tmp_path,
        clock=clock,
        authority=authority,
        policy=ledger.policy,
    )

    assert restarted.ready is True
    assert _generation(anchor) == before_restart + 1
    row = _grant_row(restarted.db_path, grant["consent_id"])
    assert row["state"] == "stopped"
    assert row["stop_reason"] == "server_restart"
    assert row["uses"] == 0
    with pytest.raises(consent_mod.EgressConsentDenied) as stopped:
        restarted.consume(str(grant["token"]), **_consume_values())
    assert stopped.value.reason == "consent_stopped"
    assert _grant_row(restarted.db_path, grant["consent_id"])["uses"] == 0


def test_stale_grants_expire_before_duplicate_issue_and_status(tmp_path: Path):
    policy = _policy(primary_ttl=5, primary_uses=1)
    ledger, clock, authority, _anchor_store = _ledger(tmp_path, policy=policy)
    authority.queue(True)
    first = _request(ledger)
    clock.value += 5
    authority.queue(True)

    replacement = _request(ledger)

    assert replacement["consent_id"] != first["consent_id"]
    first_row = _grant_row(ledger.db_path, first["consent_id"])
    assert first_row["state"] == "stopped"
    assert first_row["stop_reason"] == "expired"
    assert [row["event"] for row in _receipts(ledger.db_path)] == [
        "grant",
        "stop",
        "grant",
    ]

    clock.value += 5
    status = ledger.status()
    assert status["active"] == []
    assert status["counts"]["active"] == 0
    assert _grant_row(ledger.db_path, replacement["consent_id"])[
        "stop_reason"
    ] == "expired"


def test_legacy_schema_fails_closed_without_implicit_migration(tmp_path: Path):
    db_path = tmp_path / "egress.db"
    with connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE egress_consents "
            "(consent_id TEXT PRIMARY KEY, contract_version INTEGER)"
        )
        conn.execute(
            "CREATE TABLE egress_consent_receipts "
            "(receipt_sequence INTEGER PRIMARY KEY)"
        )

    ledger, _clock, _authority, _anchor_store = _ledger(tmp_path)

    assert ledger.ready is False
    assert ledger.quarantine_reason == "unsupported_schema"
    with connect(db_path) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='egress_consent_meta'"
        ).fetchone() is None


@pytest.mark.parametrize(
    "change,reason",
    [
        ("key_version", "seal_key_version_mismatch"),
        ("wrong_key", "metadata_seal_invalid"),
        ("policy_version", "policy_version_mismatch"),
        ("deployment", "policy_version_mismatch"),
        ("authority_version", "authority_version_mismatch"),
    ],
)
def test_key_policy_route_and_authority_version_changes_fail_closed(
    tmp_path: Path, change: str, reason: str
):
    ledger, clock, authority, anchor = _ledger(tmp_path)
    changed_authority = authority
    changed_policy = ledger.policy
    seal_key = SEAL_KEY
    seal_version = SEAL_VERSION
    if change == "key_version":
        seal_version = "egress-seal-v3"
    elif change == "wrong_key":
        seal_key = b"different-main-seal-key"
    elif change == "policy_version":
        changed_policy = _policy(version=2)
    elif change == "deployment":
        changed_policy = _policy(primary_deployment="different-deployment")
    else:
        changed_authority = FakeAuthority()
        changed_authority.version = 2

    restored, _clock, _authority, _anchor_store = _ledger(
        tmp_path,
        clock=clock,
        authority=changed_authority,
        policy=changed_policy,
        seal_key=seal_key,
        seal_key_version=seal_version,
        anchor=anchor,
    )

    assert restored.ready is False
    assert restored.quarantine_reason == reason


def test_status_and_audit_use_explicit_consistent_transactions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    ledger, _clock, _authority, _anchor_store = _ledger(tmp_path)
    real_connect = consent_mod.connect
    statements: list[str] = []

    @contextmanager
    def traced(path: Path):
        with real_connect(path) as conn:
            if Path(path) == ledger.db_path:
                conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(consent_mod, "connect", traced)
    ledger.status()
    ledger.audit()

    begins = [
        statement
        for statement in statements
        if statement.strip().upper() == "BEGIN IMMEDIATE"
    ]
    assert len(begins) == 2


def test_concurrent_status_and_consume_return_one_consistent_snapshot(
    tmp_path: Path,
):
    ledger, _clock, authority, _anchor_store = _ledger(
        tmp_path, policy=_policy(primary_uses=16)
    )
    authority.queue(True)
    grant = _request(ledger)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        for expected_use in range(1, 9):
            barrier = threading.Barrier(2)

            def read_status() -> dict[str, object]:
                barrier.wait(timeout=5)
                return ledger.status(receipt_limit=100)

            def consume_once() -> dict[str, object]:
                barrier.wait(timeout=5)
                return ledger.consume_active(**_consume_values())

            status_future = executor.submit(read_status)
            consume_future = executor.submit(consume_once)
            status = status_future.result(timeout=20)
            consumed = consume_future.result(timeout=20)

            assert consumed["uses"] == expected_use
            assert len(status["active"]) == 1
            visible = status["active"][0]
            assert visible["consent_id"] == grant["consent_id"]
            visible_uses = int(visible["uses"])
            assert visible_uses in {expected_use - 1, expected_use}
            visible_use_receipts = sum(
                receipt["event"] == "use"
                and receipt["consent_id"] == grant["consent_id"]
                for receipt in status["receipts"]
            )
            assert visible_use_receipts == visible_uses


def test_mutations_use_incremental_checks_while_audit_is_explicit_full_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    ledger, _clock, authority, _anchor_store = _ledger(tmp_path)
    original = consent_mod.EgressConsentLedger._full_audit_conn
    calls = 0

    def counted(
        self: consent_mod.EgressConsentLedger,
        conn: sqlite3.Connection,
        meta: sqlite3.Row,
    ):
        nonlocal calls
        calls += 1
        return original(self, conn, meta)

    monkeypatch.setattr(consent_mod.EgressConsentLedger, "_full_audit_conn", counted)
    for index in range(20):
        authority.queue(False)
        operation_id = "op_" + f"{index:024d}"
        result = _request(ledger, operation_id=operation_id)
        assert result["granted"] is False
    ledger.status()
    assert calls == 0

    audit = ledger.audit()
    assert calls == 1
    assert audit["verified"] is True
    assert audit["receipts"] == 20


def test_target_state_tampering_is_detected_by_incremental_consume(tmp_path: Path):
    ledger, _clock, authority, _anchor_store = _ledger(tmp_path)
    authority.queue(True)
    grant = _request(ledger)
    with connect(ledger.db_path) as conn:
        trigger_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='egress_consents_state_monotonic'"
        ).fetchone()[0]
        conn.execute("DROP TRIGGER egress_consents_state_monotonic")
        conn.execute(
            "UPDATE egress_consents SET uses=1,last_used_at=? WHERE consent_id=?",
            (NOW, grant["consent_id"]),
        )
        conn.execute(str(trigger_sql))

    with pytest.raises(consent_mod.EgressConsentQuarantined) as tampered:
        ledger.consume(str(grant["token"]), **_consume_values())

    assert tampered.value.reason == "use_receipt_state_invalid"
    assert ledger.quarantined is True


def test_full_audit_detects_deleted_interior_receipt(tmp_path: Path):
    ledger, _clock, authority, _anchor_store = _ledger(tmp_path)
    authority.queue(False)
    _request(ledger, operation_id=OPERATION_A)
    authority.queue(False)
    _request(ledger, operation_id=OPERATION_B)
    with connect(ledger.db_path) as conn:
        conn.execute("DROP TRIGGER egress_consent_receipts_immutable_delete")
        conn.execute(
            "DELETE FROM egress_consent_receipts WHERE receipt_sequence=1"
        )
        conn.execute(
            """
            CREATE TRIGGER egress_consent_receipts_immutable_delete
            BEFORE DELETE ON egress_consent_receipts
            BEGIN
                SELECT RAISE(ABORT, 'egress consent receipts are immutable');
            END
            """
        )

    with pytest.raises(consent_mod.EgressConsentQuarantined) as tampered:
        ledger.audit()

    assert tampered.value.reason == "receipt_count_invalid"


def test_same_name_noop_trigger_quarantines_before_consume(tmp_path: Path):
    ledger, _clock, authority, _anchor_store = _ledger(tmp_path)
    authority.queue(True)
    grant = _request(ledger)
    before = _grant_row(ledger.db_path, grant["consent_id"])
    with connect(ledger.db_path) as conn:
        conn.execute("DROP TRIGGER egress_consent_meta_append_only")
        conn.execute(
            """
            CREATE TRIGGER egress_consent_meta_append_only
            BEFORE UPDATE ON egress_consent_meta
            BEGIN
                SELECT 1;
            END
            """
        )

    with pytest.raises(consent_mod.EgressConsentQuarantined) as schema_error:
        ledger.consume(str(grant["token"]), **_consume_values())

    assert schema_error.value.reason == "schema_manifest_mismatch"
    assert _grant_row(ledger.db_path, grant["consent_id"]) == before


def test_altered_decision_index_quarantines_before_authority_replay(
    tmp_path: Path,
):
    ledger, _clock, authority, _anchor_store = _ledger(tmp_path)
    repeated = "decision_" + "7" * 24
    authority.queue(False, decision_id=repeated)
    _request(ledger, operation_id=OPERATION_A)
    before_requests = len(authority.requests)
    before_receipts = len(_receipts(ledger.db_path))
    with connect(ledger.db_path) as conn:
        conn.execute("DROP INDEX egress_consent_decision_once")
        conn.execute(
            "CREATE INDEX egress_consent_decision_once "
            "ON egress_consent_receipts(receipt_id)"
        )
    authority.queue(False, decision_id=repeated)

    with pytest.raises(consent_mod.EgressConsentQuarantined) as schema_error:
        _request(ledger, operation_id=OPERATION_B)

    assert schema_error.value.reason == "schema_manifest_mismatch"
    assert len(authority.requests) == before_requests
    assert len(_receipts(ledger.db_path)) == before_receipts


def test_missing_required_index_quarantines_before_request(tmp_path: Path):
    ledger, _clock, authority, _anchor_store = _ledger(tmp_path)
    with connect(ledger.db_path) as conn:
        conn.execute("DROP INDEX egress_consents_expiry_idx")
    authority.queue(True)

    with pytest.raises(consent_mod.EgressConsentQuarantined) as schema_error:
        _request(ledger)

    assert schema_error.value.reason == "unsupported_schema"
    assert authority.requests == []


def test_request_expiration_is_exact_target_plus_fixed_unrelated_batch(
    tmp_path: Path,
):
    total = consent_mod.MAINTENANCE_BATCH_SIZE * 2 + 5
    ledger, clock, authority, _anchor_store = _ledger(
        tmp_path, policy=_policy(primary_ttl=1, primary_uses=1)
    )
    operations = ["op_" + f"{index:024d}" for index in range(total)]
    grants: list[dict[str, object]] = []
    for operation_id in operations:
        authority.queue(True)
        grants.append(_request(ledger, operation_id=operation_id))
    target = grants[-1]
    clock.value += 1
    authority.queue(True)

    replacement = _request(ledger, operation_id=operations[-1])

    old_rows = [
        _grant_row(ledger.db_path, grant["consent_id"]) for grant in grants
    ]
    stopped_after_issue = sum(row["state"] == "stopped" for row in old_rows)
    assert stopped_after_issue == consent_mod.MAINTENANCE_BATCH_SIZE + 1
    assert _grant_row(ledger.db_path, target["consent_id"])["stop_reason"] == "expired"
    assert replacement["state"] == "active"
    assert sum(row["event"] == "stop" for row in _receipts(ledger.db_path)) == (
        consent_mod.MAINTENANCE_BATCH_SIZE + 1
    )

    status = ledger.status(receipt_limit=100)
    assert status["counts"]["active"] == 1
    assert status["active"][0]["consent_id"] == replacement["consent_id"]
    assert status["counts"]["stale_pending"] == total - (
        consent_mod.MAINTENANCE_BATCH_SIZE * 2 + 1
    )


def test_policy_identifiers_are_strict_and_exact_deployment_is_required():
    with pytest.raises(consent_mod.EgressConsentError):
        consent_mod.AllowedEgressRoute(
            route_id="RAW-PAYLOAD-MARKER",
            provider="provider-a",
            deployment="deployment-a",
            model="acme/model",
            capability="private-vision",
            purpose="describe-image",
            processing_location="us-west",
            destination_class="managed-api",
            transport_route="https://example.test/v1/infer",
        )
    with pytest.raises(consent_mod.EgressConsentError):
        consent_mod.AllowedEgressRoute(
            route_id="valid-route",
            provider="provider-a",
            deployment="",
            model="acme/model",
            capability="private-vision",
            purpose="describe-image",
            processing_location="us-west",
            destination_class="managed-api",
            transport_route="https://example.test/v1/infer",
        )
    with pytest.raises(consent_mod.EgressConsentError):
        consent_mod.AllowedEgressRoute(
            route_id="valid-route",
            provider="provider-a",
            deployment="deployment-a",
            model="acme/model",
            capability="private-vision",
            purpose="describe-image",
            processing_location="us-west",
            destination_class="managed-api",
            transport_route="http://example.test/v1/infer",
        )
    with pytest.raises(
        consent_mod.EgressConsentError, match="unknown_route_identity"
    ):
        consent_mod.AllowedEgressRoute(
            route_id="valid-route",
            provider="provider-a",
            deployment="unknown",
            model="acme/model",
            capability="private-vision",
            purpose="describe-image",
            processing_location="us-west",
            destination_class="managed-api",
            transport_route="https://example.test/v1/infer",
        )


def test_external_anchor_is_required_but_pluggable(tmp_path: Path):
    anchor = MemoryAnchor()
    ledger, _clock, authority, active_anchor = _ledger(tmp_path, anchor=anchor)
    authority.queue(True)

    grant = _request(ledger)

    assert ledger.ready is True
    assert active_anchor is anchor
    assert anchor.state is not None
    assert anchor.state.generation == 2
    assert grant["granted"] is True


def test_database_triggers_keep_grants_receipts_and_metadata_monotonic(tmp_path: Path):
    ledger, _clock, authority, _anchor_store = _ledger(tmp_path)
    authority.queue(True)
    grant = _request(ledger)
    receipt_id = grant["receipt"]["receipt_id"]

    with connect(ledger.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="grant is immutable"):
            conn.execute(
                "UPDATE egress_consents SET route_id='changed-route' "
                "WHERE consent_id=?",
                (grant["consent_id"],),
            )
    with connect(ledger.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="receipts are immutable"):
            conn.execute(
                "UPDATE egress_consent_receipts SET reason='tampered' "
                "WHERE receipt_id=?",
                (receipt_id,),
            )
    with connect(ledger.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="metadata is not monotonic"):
            conn.execute(
                "UPDATE egress_consent_meta SET anchor_generation=anchor_generation-1 "
                "WHERE singleton=1"
            )


def test_byte_cap_fails_before_authority_or_clock_observation(tmp_path: Path):
    ledger, _clock, authority, anchor = _ledger(tmp_path)
    generation = _generation(anchor)

    with pytest.raises(consent_mod.EgressConsentError) as oversized:
        _request(ledger, byte_count=2049)

    assert str(oversized.value) == "invalid_byte_count"
    assert not authority.requests
    assert _generation(anchor) == generation
