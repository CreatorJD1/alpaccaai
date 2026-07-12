"""Focused lifecycle and integrity tests for Phase 9 capability leases."""
from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from alpecca import capability_leases as lease_mod
from alpecca.db import connect


NOW = 1_000.0
SEAL_KEY = b"phase9-test-only-capability-lease-seal-key"
CONNECTION = "house-connection-a"
SCOPE = "creator-private"
SURFACE = "house-hq"


def _store(tmp_path: Path, name: str = "capability-leases.db") -> lease_mod.CapabilityLeaseStore:
    return lease_mod.CapabilityLeaseStore(tmp_path / name, seal_key=SEAL_KEY)


def _issue(store: lease_mod.CapabilityLeaseStore, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "connection_id": CONNECTION,
        "principal": "creator",
        "privacy_scope": SCOPE,
        "surface": SURFACE,
        "purpose": "camera_frame",
        "auth_mechanism": "trusted-device-session",
        "now": NOW,
    }
    values.update(overrides)
    return store.issue(**values)


def _request_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "connection_id": CONNECTION,
        "principal": "creator",
        "privacy_scope": SCOPE,
        "surface": SURFACE,
        "purpose": "camera_frame",
        "now": NOW + 1,
    }
    values.update(overrides)
    return values


def _lease_row(db_path: Path, lease_id: object) -> dict[str, object]:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM capability_leases WHERE lease_id=?", (lease_id,)
        ).fetchone()
    assert row is not None
    return dict(row)


def _receipt_rows(db_path: Path, lease_id: object) -> list[dict[str, object]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM capability_lease_receipts WHERE lease_id=? "
            "ORDER BY receipt_id",
            (lease_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _legacy_v1_database(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    seed = _store(tmp_path, "legacy-seed.db")
    grant = _issue(seed, connection_id="legacy-connection")
    lease = _lease_row(seed.db_path, grant["lease_id"])
    receipt = _receipt_rows(seed.db_path, grant["lease_id"])[0]
    legacy_receipt = {
        key: receipt[key]
        for key in (
            "receipt_id",
            "lease_id",
            "event",
            "capability",
            "purpose",
            "principal",
            "privacy_scope",
            "surface",
            "occurred_at",
            "expires_at",
            "max_uses",
            "max_bytes_per_use",
            "use_ordinal",
            "reason",
            "connection_hmac",
            "resource_hmac",
        )
    }
    legacy_receipt["receipt_seal"] = seed._seal(
        lease_mod._RECEIPT_DOMAIN_V1,
        seed._receipt_material_v1(legacy_receipt),
    )
    legacy_denial = {
        **legacy_receipt,
        "receipt_id": int(legacy_receipt["receipt_id"]) + 1,
        "lease_id": None,
        "event": "deny",
        "occurred_at": NOW + 0.5,
        "expires_at": NOW + 0.5,
        "reason": "invalid_token",
    }
    legacy_denial["receipt_seal"] = seed._seal(
        lease_mod._RECEIPT_DOMAIN_V1,
        seed._receipt_material_v1(legacy_denial),
    )

    db_path = tmp_path / "legacy-v1.db"
    lease_columns = (
        "id",
        "lease_id",
        "contract_version",
        "token_hmac",
        "connection_hmac",
        "resource_hmac",
        "principal",
        "privacy_scope",
        "surface",
        "capability",
        "purpose",
        "auth_mechanism",
        "auth_expires_at",
        "issued_at",
        "expires_at",
        "max_uses",
        "max_bytes_per_use",
        "uses",
        "state",
        "stopped_at",
        "stop_reason",
        "grant_seal",
    )
    receipt_columns = tuple(legacy_receipt)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE capability_leases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lease_id TEXT NOT NULL UNIQUE,
                contract_version INTEGER NOT NULL,
                token_hmac TEXT NOT NULL UNIQUE,
                connection_hmac TEXT NOT NULL,
                resource_hmac TEXT NOT NULL DEFAULT '',
                principal TEXT NOT NULL,
                privacy_scope TEXT NOT NULL,
                surface TEXT NOT NULL,
                capability TEXT NOT NULL,
                purpose TEXT NOT NULL,
                auth_mechanism TEXT NOT NULL,
                auth_expires_at REAL,
                issued_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                max_uses INTEGER NOT NULL,
                max_bytes_per_use INTEGER NOT NULL,
                uses INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL,
                stopped_at REAL,
                stop_reason TEXT NOT NULL DEFAULT '',
                grant_seal TEXT NOT NULL
            );
            CREATE TABLE capability_lease_receipts (
                receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                lease_id TEXT,
                event TEXT NOT NULL,
                capability TEXT NOT NULL,
                purpose TEXT NOT NULL,
                principal TEXT NOT NULL,
                privacy_scope TEXT NOT NULL,
                surface TEXT NOT NULL,
                occurred_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                max_uses INTEGER NOT NULL,
                max_bytes_per_use INTEGER NOT NULL,
                use_ordinal INTEGER,
                reason TEXT NOT NULL,
                connection_hmac TEXT NOT NULL,
                resource_hmac TEXT NOT NULL DEFAULT '',
                receipt_seal TEXT NOT NULL,
                FOREIGN KEY(lease_id) REFERENCES capability_leases(lease_id)
            );
            """
        )
        conn.execute(
            f"INSERT INTO capability_leases ({','.join(lease_columns)}) "
            f"VALUES ({','.join('?' for _ in lease_columns)})",
            tuple(lease[column] for column in lease_columns),
        )
        conn.execute(
            f"INSERT INTO capability_lease_receipts ({','.join(receipt_columns)}) "
            f"VALUES ({','.join('?' for _ in receipt_columns)})",
            tuple(legacy_receipt[column] for column in receipt_columns),
        )
        conn.execute(
            f"INSERT INTO capability_lease_receipts ({','.join(receipt_columns)}) "
            f"VALUES ({','.join('?' for _ in receipt_columns)})",
            tuple(legacy_denial[column] for column in receipt_columns),
        )
    return db_path, grant


@pytest.mark.parametrize(
    "purpose, capability, resource_binding",
    [
        ("camera_frame", "webcam", None),
        ("push_to_talk", "microphone", None),
        ("voice_enrollment", "microphone", None),
        ("file_source_ref", "file_access", "workspace:notes/status.txt"),
    ],
)
def test_one_use_leases_issue_and_stop_after_exactly_one_consume(
    tmp_path: Path,
    purpose: str,
    capability: str,
    resource_binding: str | None,
):
    store = _store(tmp_path)
    issue_values: dict[str, object] = {"purpose": purpose}
    request_values: dict[str, object] = {"purpose": purpose}
    if resource_binding is not None:
        issue_values["resource_binding"] = resource_binding
        request_values["resource_binding"] = resource_binding

    grant = _issue(store, **issue_values)

    assert grant["capability"] == capability
    assert grant["max_uses"] == 1
    assert grant["uses"] == 0
    assert grant["state"] == "active"
    assert grant["receipt"]["event"] == "grant"
    assert grant["receipt"]["receipt_version"] == 2
    assert str(grant["receipt"]["event_id"]).startswith("evt_")
    assert grant["receipt"]["verified"] is True

    consumed = store.consume(
        str(grant["token"]), **_request_values(bytes_used=1, **request_values)
    )

    assert consumed["uses"] == 1
    assert consumed["state"] == "stopped"
    assert consumed["stop_reason"] == "use_cap_reached"
    assert consumed["use_receipt"]["event"] == "use"
    assert consumed["use_receipt"]["use_ordinal"] == 1
    assert consumed["use_receipt"]["bytes_used"] == 1
    assert consumed["use_receipt"]["byte_accounting"] == "measured"
    assert consumed["use_receipt"]["verified"] is True
    assert consumed["stop_receipt"]["event"] == "stop"

    with pytest.raises(lease_mod.CapabilityLeaseDenied) as denied:
        store.consume(
            str(grant["token"]),
            **_request_values(now=NOW + 2, bytes_used=1, **request_values),
        )
    assert denied.value.reason == "lease_stopped"


def test_screen_share_allows_thirty_atomic_uses_and_no_more(tmp_path: Path):
    store = _store(tmp_path)
    grant = _issue(store, purpose="screen_share")

    assert grant["max_uses"] == 30
    assert grant["expires_at"] == NOW + 300

    for ordinal in range(1, 31):
        result = store.consume(
            str(grant["token"]),
            **_request_values(
                purpose="screen_share", now=NOW + ordinal, bytes_used=1
            ),
        )
        assert result["uses"] == ordinal
        assert result["use_receipt"]["use_ordinal"] == ordinal
        assert result["state"] == ("stopped" if ordinal == 30 else "active")

    assert result["stop_reason"] == "use_cap_reached"
    with pytest.raises(lease_mod.CapabilityLeaseDenied) as denied:
        store.consume(
            str(grant["token"]),
            **_request_values(
                purpose="screen_share", now=NOW + 31, bytes_used=1
            ),
        )
    assert denied.value.reason == "lease_stopped"

    receipts = _receipt_rows(store.db_path, grant["lease_id"])
    use_ordinals = [row["use_ordinal"] for row in receipts if row["event"] == "use"]
    assert use_ordinals == list(range(1, 31))
    assert sum(row["event"] == "stop" for row in receipts) == 1


def test_validate_active_is_non_consuming(tmp_path: Path):
    store = _store(tmp_path)
    grant = _issue(store, purpose="screen_share")

    first = store.validate_active(
        str(grant["token"]),
        **_request_values(purpose="screen_share", now=NOW + 1),
    )
    second = store.validate_active(
        str(grant["token"]),
        **_request_values(purpose="screen_share", now=NOW + 2),
    )

    assert first["uses"] == second["uses"] == 0
    assert first["state"] == second["state"] == "active"
    assert [
        row["event"] for row in _receipt_rows(store.db_path, grant["lease_id"])
    ] == ["grant"]

    consumed = store.consume(
        str(grant["token"]),
        **_request_values(purpose="screen_share", now=NOW + 3, bytes_used=1),
    )
    assert consumed["uses"] == 1
    assert consumed["use_receipt"]["use_ordinal"] == 1


def test_lease_is_valid_before_but_not_at_exact_expiry(tmp_path: Path):
    store = _store(tmp_path)
    grant = _issue(store)
    expiry = NOW + 60

    assert grant["expires_at"] == expiry
    assert store.validate_active(
        str(grant["token"]), **_request_values(now=expiry - 0.001)
    )["state"] == "active"

    with pytest.raises(lease_mod.CapabilityLeaseDenied) as denied:
        store.validate_active(
            str(grant["token"]), **_request_values(now=expiry)
        )
    assert denied.value.reason == "lease_expired"

    row = _lease_row(store.db_path, grant["lease_id"])
    assert row["uses"] == 0
    assert row["state"] == "stopped"
    assert row["stopped_at"] == expiry
    assert row["stop_reason"] == "expired"


def test_auth_expiry_clamps_ttl_and_expired_auth_cannot_issue(tmp_path: Path):
    store = _store(tmp_path)

    short_auth = _issue(
        store,
        connection_id="short-auth-connection",
        purpose="screen_share",
        auth_expires_at=NOW + 17.25,
    )
    long_auth = _issue(
        store,
        connection_id="long-auth-connection",
        purpose="screen_share",
        auth_expires_at=NOW + 999,
    )

    assert short_auth["expires_at"] == NOW + 17.25
    assert long_auth["expires_at"] == NOW + 300

    with pytest.raises(lease_mod.CapabilityLeaseDenied) as denied:
        _issue(
            store,
            connection_id="expired-auth-connection",
            auth_expires_at=NOW,
        )
    assert denied.value.reason == "authorization_expired"
    with connect(store.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM capability_leases").fetchone()[0]
    assert count == 2


def test_resource_binding_is_required_exact_and_mismatches_do_not_mutate_lease(
    tmp_path: Path,
):
    store = _store(tmp_path)
    resource = "workspace:private/creator-notes.txt"

    with pytest.raises(lease_mod.CapabilityLeaseDenied) as missing:
        _issue(store, purpose="file_source_ref")
    assert missing.value.reason == "resource_binding_required"
    with pytest.raises(lease_mod.CapabilityLeaseDenied) as forbidden:
        _issue(store, resource_binding=resource)
    assert forbidden.value.reason == "resource_binding_not_allowed"

    grant = _issue(store, purpose="file_source_ref", resource_binding=resource)
    with pytest.raises(lease_mod.CapabilityLeaseDenied) as absent:
        store.validate_active(
            str(grant["token"]),
            **_request_values(purpose="file_source_ref", now=NOW + 1),
        )
    assert absent.value.reason == "resource_mismatch"
    with pytest.raises(lease_mod.CapabilityLeaseDenied) as wrong:
        store.consume(
            str(grant["token"]),
            **_request_values(
                purpose="file_source_ref",
                resource_binding="workspace:private/other.txt",
                now=NOW + 2,
                bytes_used=1,
            ),
        )
    assert wrong.value.reason == "resource_mismatch"

    row = _lease_row(store.db_path, grant["lease_id"])
    assert (row["uses"], row["state"], row["stopped_at"], row["stop_reason"]) == (
        0,
        "active",
        None,
        "",
    )
    assert store.validate_active(
        str(grant["token"]),
        **_request_values(
            purpose="file_source_ref", resource_binding=resource, now=NOW + 3
        ),
    )["uses"] == 0
    assert store.consume(
        str(grant["token"]),
        **_request_values(
            purpose="file_source_ref",
            resource_binding=resource,
            now=NOW + 4,
            bytes_used=1,
        ),
    )["uses"] == 1


@pytest.mark.parametrize(
    "override, reason",
    [
        ({"connection_id": "wrong-connection"}, "connection_mismatch"),
        ({"principal": "guest"}, "principal_mismatch"),
        ({"privacy_scope": "guest-private"}, "scope_mismatch"),
        ({"surface": "virtual-app"}, "surface_mismatch"),
        ({"purpose": "screen_share"}, "purpose_mismatch"),
    ],
)
def test_context_mismatches_do_not_consume_or_stop_legitimate_lease(
    tmp_path: Path, override: dict[str, object], reason: str
):
    store = _store(tmp_path)
    grant = _issue(store)

    with pytest.raises(lease_mod.CapabilityLeaseDenied) as denied:
        store.consume(
            str(grant["token"]), **_request_values(bytes_used=1, **override)
        )
    assert denied.value.reason == reason

    row = _lease_row(store.db_path, grant["lease_id"])
    assert (row["uses"], row["state"], row["stopped_at"], row["stop_reason"]) == (
        0,
        "active",
        None,
        "",
    )
    assert store.validate_active(
        str(grant["token"]), **_request_values(now=NOW + 2)
    )["uses"] == 0
    assert store.consume(
        str(grant["token"]), **_request_values(now=NOW + 3, bytes_used=1)
    )["uses"] == 1


def test_byte_cap_is_inclusive_and_oversize_use_stops_without_consuming(tmp_path: Path):
    store = _store(tmp_path)
    cap = lease_mod.POLICIES["screen_share"].max_bytes_per_use
    exact = _issue(store, connection_id="exact-byte-connection", purpose="screen_share")
    oversized = _issue(
        store, connection_id="oversized-byte-connection", purpose="screen_share"
    )

    accepted = store.consume(
        str(exact["token"]),
        **_request_values(
            connection_id="exact-byte-connection",
            purpose="screen_share",
            bytes_used=cap,
        ),
    )
    assert accepted["uses"] == 1
    assert accepted["state"] == "active"

    with pytest.raises(lease_mod.CapabilityLeaseDenied) as denied:
        store.consume(
            str(oversized["token"]),
            **_request_values(
                connection_id="oversized-byte-connection",
                purpose="screen_share",
                bytes_used=cap + 1,
            ),
        )
    assert denied.value.reason == "byte_cap_exceeded"
    assert denied.value.receipt_id is not None

    row = _lease_row(store.db_path, oversized["lease_id"])
    assert row["uses"] == 0
    assert row["state"] == "stopped"
    assert row["stop_reason"] == "byte_cap_exceeded"
    assert [
        receipt["event"] for receipt in _receipt_rows(store.db_path, oversized["lease_id"])
    ] == ["grant", "stop", "deny"]
    deny_receipt = next(
        receipt
        for receipt in _receipt_rows(store.db_path, oversized["lease_id"])
        if receipt["receipt_id"] == denied.value.receipt_id
    )
    assert deny_receipt["bytes_used"] == cap + 1
    assert deny_receipt["byte_accounting"] == "measured"


def test_stop_rejects_wrong_connection_and_is_idempotent(tmp_path: Path):
    store = _store(tmp_path)
    grant = _issue(store, purpose="screen_share")

    with pytest.raises(lease_mod.CapabilityLeaseDenied) as denied:
        store.stop(
            str(grant["lease_id"]),
            connection_id="wrong-connection",
            now=NOW + 1,
        )
    assert denied.value.reason == "connection_mismatch"
    assert _lease_row(store.db_path, grant["lease_id"])["state"] == "active"

    first, first_changed = store.stop(
        str(grant["lease_id"]),
        connection_id=CONNECTION,
        reason="client_stop",
        now=NOW + 2,
    )
    second, second_changed = store.stop(
        str(grant["lease_id"]),
        connection_id=CONNECTION,
        reason="different_retry_reason",
        now=NOW + 3,
    )

    assert first_changed is True
    assert second_changed is False
    assert second == first
    assert first["state"] == "stopped"
    assert first["stopped_at"] == NOW + 2
    assert first["stop_reason"] == "client_stop"
    assert first["stop_receipt"]["event"] == "stop"
    assert first["stop_receipt"]["reason"] == "client_stop"
    assert sum(
        row["event"] == "stop"
        for row in _receipt_rows(store.db_path, grant["lease_id"])
    ) == 1


def test_stop_connection_stops_only_that_connections_active_leases(tmp_path: Path):
    store = _store(tmp_path)
    camera = _issue(store)
    screen = _issue(store, purpose="screen_share")
    file_grant = _issue(
        store,
        purpose="file_source_ref",
        resource_binding="workspace:private/notes.txt",
    )
    other = _issue(store, connection_id="other-connection")

    assert store.stop_connection(
        CONNECTION, reason="connection_closed", now=NOW + 5
    ) == 3
    assert store.stop_connection(
        CONNECTION, reason="connection_closed", now=NOW + 6
    ) == 0

    for grant in (camera, screen, file_grant):
        row = _lease_row(store.db_path, grant["lease_id"])
        assert row["state"] == "stopped"
        assert row["stopped_at"] == NOW + 5
        assert row["stop_reason"] == "connection_closed"
    assert store.validate_active(
        str(other["token"]),
        **_request_values(connection_id="other-connection", now=NOW + 7),
    )["state"] == "active"


def test_startup_recovery_stops_active_leases_once_across_store_instances(tmp_path: Path):
    store = _store(tmp_path)
    first = _issue(store)
    second = _issue(store, connection_id="second-connection", purpose="screen_share")

    assert store.recover_active(now=NOW + 10) == 2
    restarted = lease_mod.CapabilityLeaseStore(store.db_path, seal_key=SEAL_KEY)
    assert restarted.recover_active(now=NOW + 11) == 0

    for grant in (first, second):
        row = _lease_row(store.db_path, grant["lease_id"])
        assert row["state"] == "stopped"
        assert row["stopped_at"] == NOW + 10
        assert row["stop_reason"] == "server_restart"
        assert sum(
            receipt["event"] == "stop"
            for receipt in _receipt_rows(store.db_path, grant["lease_id"])
        ) == 1


def test_duplicate_issue_is_denied_per_connection_and_capability(tmp_path: Path):
    store = _store(tmp_path)
    first = _issue(store, purpose="push_to_talk")

    with pytest.raises(lease_mod.CapabilityLeaseDenied) as denied:
        _issue(store, purpose="voice_enrollment", now=NOW + 1)
    assert denied.value.reason == "active_lease_exists"

    with connect(store.db_path) as conn:
        leases = conn.execute("SELECT lease_id FROM capability_leases").fetchall()
        receipts = conn.execute(
            "SELECT lease_id,event,purpose,reason FROM capability_lease_receipts "
            "ORDER BY receipt_id"
        ).fetchall()
    assert [row["lease_id"] for row in leases] == [first["lease_id"]]
    assert [tuple(row) for row in receipts] == [
        (first["lease_id"], "grant", "push_to_talk", "granted"),
        (None, "deny", "voice_enrollment", "active_lease_exists"),
    ]

    store.stop(str(first["lease_id"]), connection_id=CONNECTION, now=NOW + 2)
    replacement = _issue(store, purpose="voice_enrollment", now=NOW + 3)
    assert replacement["capability"] == "microphone"
    assert replacement["state"] == "active"


def test_database_triggers_preserve_grants_state_and_receipts(tmp_path: Path):
    store = _store(tmp_path)
    grant = _issue(store, purpose="screen_share")
    store.consume(
        str(grant["token"]),
        **_request_values(purpose="screen_share", now=NOW + 1, bytes_used=1),
    )
    receipt_id = grant["receipt"]["receipt_id"]

    with connect(store.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="grant is immutable"):
            conn.execute(
                "UPDATE capability_leases SET surface='tampered' WHERE lease_id=?",
                (grant["lease_id"],),
            )
    with connect(store.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="state is not monotonic"):
            conn.execute(
                "UPDATE capability_leases SET uses=0 WHERE lease_id=?",
                (grant["lease_id"],),
            )
    with connect(store.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable evidence"):
            conn.execute(
                "DELETE FROM capability_leases WHERE lease_id=?", (grant["lease_id"],)
            )
    with connect(store.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="receipts are immutable"):
            conn.execute(
                "UPDATE capability_lease_receipts SET reason='tampered' "
                "WHERE receipt_id=?",
                (receipt_id,),
            )
    with connect(store.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="receipts are immutable"):
            conn.execute(
                "DELETE FROM capability_lease_receipts WHERE receipt_id=?", (receipt_id,)
            )

    verified = store.validate_active(
        str(grant["token"]),
        **_request_values(purpose="screen_share", now=NOW + 2),
    )
    assert verified["uses"] == 1
    assert verified["surface"] == SURFACE


def test_tampered_grant_fails_seal_verification_after_trigger_bypass(tmp_path: Path):
    store = _store(tmp_path)
    grant = _issue(store, purpose="screen_share")
    with connect(store.db_path) as conn:
        conn.execute("DROP TRIGGER capability_leases_grant_immutable")
        conn.execute(
            "UPDATE capability_leases SET surface='tampered' WHERE lease_id=?",
            (grant["lease_id"],),
        )

    with pytest.raises(lease_mod.CapabilityLeaseIntegrityError, match="grant seal"):
        store.validate_active(
            str(grant["token"]),
            **_request_values(purpose="screen_share", now=NOW + 1),
        )


def test_tampered_receipt_fails_seal_verification_in_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _store(tmp_path)
    grant = _issue(store, purpose="screen_share")
    with connect(store.db_path) as conn:
        conn.execute("DROP TRIGGER capability_lease_receipts_immutable_update")
        conn.execute(
            "UPDATE capability_lease_receipts SET reason='tampered' "
            "WHERE receipt_id=?",
            (grant["receipt"]["receipt_id"],),
        )
    monkeypatch.setattr(lease_mod.time, "time", lambda: NOW + 1)

    with pytest.raises(lease_mod.CapabilityLeaseIntegrityError, match="receipt seal"):
        store.status()


def test_raw_token_connection_and_resource_never_enter_database_or_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _store(tmp_path)
    connection = "RAW-CONNECTION-MARKER-7f45b3"
    resource = "RAW-RESOURCE-MARKER/private/creator-file-9c2a.txt"
    grant = _issue(
        store,
        connection_id=connection,
        purpose="file_source_ref",
        resource_binding=resource,
    )
    token = str(grant["token"])

    with connect(store.db_path) as conn:
        lease_rows = [
            dict(row) for row in conn.execute("SELECT * FROM capability_leases").fetchall()
        ]
        receipt_rows = [
            dict(row)
            for row in conn.execute("SELECT * FROM capability_lease_receipts").fetchall()
        ]
    persisted = json.dumps({"leases": lease_rows, "receipts": receipt_rows})
    assert len(lease_rows[0]["token_hmac"]) == 64
    assert len(lease_rows[0]["connection_hmac"]) == 64
    assert len(lease_rows[0]["resource_hmac"]) == 64

    monkeypatch.setattr(lease_mod.time, "time", lambda: NOW + 1)
    status = store.status()
    status_json = json.dumps(status, sort_keys=True)
    assert set(status["active"][0]).isdisjoint(
        {"token", "token_hmac", "connection_hmac", "resource_hmac"}
    )
    assert set(status["receipts"][0]).isdisjoint(
        {"token", "token_hmac", "connection_hmac", "resource_hmac"}
    )

    for raw_value in (token, connection, resource):
        assert raw_value not in persisted
        assert raw_value not in status_json
        assert raw_value.encode("utf-8") not in store.db_path.read_bytes()


def test_concurrent_one_use_consumers_have_exactly_one_winner(tmp_path: Path):
    store = _store(tmp_path)
    grant = _issue(store)
    second_store = lease_mod.CapabilityLeaseStore(store.db_path, seal_key=SEAL_KEY)
    barrier = threading.Barrier(2)

    def consume_once(active_store: lease_mod.CapabilityLeaseStore):
        barrier.wait(timeout=5)
        try:
            result = active_store.consume(
                str(grant["token"]),
                **_request_values(now=NOW + 1, bytes_used=1),
            )
        except lease_mod.CapabilityLeaseDenied as exc:
            return "denied", exc.reason
        return "allowed", result

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(consume_once, item) for item in (store, second_store)]
        outcomes = [future.result(timeout=10) for future in futures]

    assert [kind for kind, _value in outcomes].count("allowed") == 1
    assert [kind for kind, _value in outcomes].count("denied") == 1
    allowed = next(value for kind, value in outcomes if kind == "allowed")
    denied = next(value for kind, value in outcomes if kind == "denied")
    assert allowed["uses"] == 1
    assert allowed["state"] == "stopped"
    assert denied == "lease_stopped"

    row = _lease_row(store.db_path, grant["lease_id"])
    assert row["uses"] == 1
    assert row["state"] == "stopped"
    receipts = _receipt_rows(store.db_path, grant["lease_id"])
    assert sum(receipt["event"] == "use" for receipt in receipts) == 1
    assert sum(receipt["event"] == "stop" for receipt in receipts) == 1


def test_consume_requires_explicit_byte_evidence(tmp_path: Path):
    store = _store(tmp_path)
    grant = _issue(store)

    with pytest.raises(TypeError, match="bytes_used"):
        store.consume(str(grant["token"]), **_request_values())

    assert _lease_row(store.db_path, grant["lease_id"])["uses"] == 0


def test_mismatch_denial_uses_stored_lease_context_and_does_not_mutate(
    tmp_path: Path,
):
    store = _store(tmp_path)
    grant = _issue(store)
    attempted_bytes = lease_mod.POLICIES["camera_frame"].max_bytes_per_use + 1

    with pytest.raises(lease_mod.CapabilityLeaseDenied) as denied:
        store.consume(
            str(grant["token"]),
            **_request_values(
                purpose="push_to_talk",
                bytes_used=attempted_bytes,
            ),
        )

    assert denied.value.reason == "purpose_mismatch"
    assert denied.value.receipt_id == denied.value.denial_receipt_id
    assert denied.value.receipt_id is not None
    receipts = _receipt_rows(store.db_path, grant["lease_id"])
    deny_receipt = next(
        receipt
        for receipt in receipts
        if receipt["receipt_id"] == denied.value.receipt_id
    )
    assert deny_receipt["lease_id"] == grant["lease_id"]
    assert deny_receipt["purpose"] == "camera_frame"
    assert deny_receipt["capability"] == "webcam"
    assert deny_receipt["max_uses"] == grant["max_uses"]
    assert deny_receipt["max_bytes_per_use"] == grant["max_bytes_per_use"]
    assert deny_receipt["bytes_used"] == attempted_bytes
    assert deny_receipt["byte_accounting"] == "measured"

    row = _lease_row(store.db_path, grant["lease_id"])
    assert (row["uses"], row["state"], row["stopped_at"], row["stop_reason"]) == (
        0,
        "active",
        None,
        "",
    )
    assert store.consume(
        str(grant["token"]),
        **_request_values(now=NOW + 2, bytes_used=1),
    )["uses"] == 1


def test_v2_event_id_prevents_cloned_receipts(tmp_path: Path):
    store = _store(tmp_path)
    grant = _issue(store)
    receipt_id = int(grant["receipt"]["receipt_id"])

    with connect(store.db_path) as conn:
        columns = [
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(capability_lease_receipts)"
            ).fetchall()
            if str(row["name"]) != "receipt_id"
        ]
        column_sql = ",".join(columns)
        with pytest.raises(sqlite3.IntegrityError, match="event_id"):
            conn.execute(
                f"INSERT INTO capability_lease_receipts ({column_sql}) "
                f"SELECT {column_sql} FROM capability_lease_receipts "
                "WHERE receipt_id=?",
                (receipt_id,),
            )

    assert len(_receipt_rows(store.db_path, grant["lease_id"])) == 1


def test_recovery_isolates_corrupt_rows_and_ignores_current_policy_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _store(tmp_path)
    corrupt = _issue(store)
    valid = _issue(
        store,
        connection_id="recovery-valid-connection",
        purpose="screen_share",
    )
    with connect(store.db_path) as conn:
        conn.execute("DROP TRIGGER capability_leases_grant_immutable")
        conn.execute(
            "UPDATE capability_leases SET surface='tampered' WHERE lease_id=?",
            (corrupt["lease_id"],),
        )
    monkeypatch.setattr(lease_mod, "POLICIES", {})

    assert store.recover_active(now=NOW + 10) == 2

    corrupt_row = _lease_row(store.db_path, corrupt["lease_id"])
    valid_row = _lease_row(store.db_path, valid["lease_id"])
    assert corrupt_row["state"] == "stopped"
    assert corrupt_row["stop_reason"] == "integrity_failure"
    assert valid_row["state"] == "stopped"
    assert valid_row["stop_reason"] == "server_restart"
    assert any(
        receipt["event"] == "stop"
        for receipt in _receipt_rows(store.db_path, corrupt["lease_id"])
    )
    assert any(
        receipt["event"] == "stop"
        for receipt in _receipt_rows(store.db_path, valid["lease_id"])
    )


def test_recovery_with_unavailable_old_key_still_revokes_active_token(
    tmp_path: Path,
):
    original = _store(tmp_path)
    grant = _issue(original)
    restarted = lease_mod.CapabilityLeaseStore(
        original.db_path,
        seal_key=b"replacement-key-without-access-to-the-old-key",
    )

    assert restarted.recover_active(now=NOW + 5) == 1
    row = _lease_row(original.db_path, grant["lease_id"])
    assert row["state"] == "stopped"
    assert row["stop_reason"] == "integrity_failure"


def test_sql_use_increment_without_receipt_is_detected_and_quarantined(
    tmp_path: Path,
):
    store = _store(tmp_path)
    grant = _issue(store, purpose="screen_share")
    with connect(store.db_path) as conn:
        conn.execute(
            "UPDATE capability_leases SET uses=1 WHERE lease_id=?",
            (grant["lease_id"],),
        )

    with pytest.raises(
        lease_mod.CapabilityLeaseIntegrityError, match="use count"
    ):
        store.validate_active(
            str(grant["token"]),
            **_request_values(purpose="screen_share", now=NOW + 1),
        )

    row = _lease_row(store.db_path, grant["lease_id"])
    assert row["uses"] == 1
    assert row["state"] == "stopped"
    assert row["stop_reason"] == "integrity_failure"


def test_sql_stop_without_receipt_is_detected(tmp_path: Path):
    store = _store(tmp_path)
    grant = _issue(store, purpose="screen_share")
    with connect(store.db_path) as conn:
        conn.execute(
            "UPDATE capability_leases SET state='stopped', stopped_at=?, "
            "stop_reason='sql_stop' WHERE lease_id=?",
            (NOW + 1, grant["lease_id"]),
        )

    with pytest.raises(
        lease_mod.CapabilityLeaseIntegrityError, match="stop"
    ):
        store.validate_active(
            str(grant["token"]),
            **_request_values(purpose="screen_share", now=NOW + 2),
        )

    assert not any(
        receipt["event"] == "stop"
        for receipt in _receipt_rows(store.db_path, grant["lease_id"])
    )


def test_clock_rollback_stops_fail_closed_but_mismatch_does_not(
    tmp_path: Path,
):
    store = _store(tmp_path)
    grant = _issue(store, purpose="screen_share")

    with pytest.raises(lease_mod.CapabilityLeaseDenied) as rollback:
        store.consume(
            str(grant["token"]),
            **_request_values(
                purpose="screen_share",
                now=NOW - 1,
                bytes_used=17,
            ),
        )
    assert rollback.value.reason == "clock_rollback"
    assert rollback.value.receipt_id is not None
    row = _lease_row(store.db_path, grant["lease_id"])
    assert (row["uses"], row["state"], row["stopped_at"], row["stop_reason"]) == (
        0,
        "stopped",
        NOW,
        "clock_rollback",
    )
    rollback_receipt = next(
        receipt
        for receipt in _receipt_rows(store.db_path, grant["lease_id"])
        if receipt["receipt_id"] == rollback.value.receipt_id
    )
    assert rollback_receipt["bytes_used"] == 17
    assert rollback_receipt["byte_accounting"] == "measured"

    mismatch = _issue(store, connection_id="rollback-mismatch-connection")
    with pytest.raises(lease_mod.CapabilityLeaseDenied) as mismatched:
        store.consume(
            str(mismatch["token"]),
            **_request_values(
                connection_id="wrong-connection",
                now=NOW - 1,
                bytes_used=1,
            ),
        )
    assert mismatched.value.reason == "connection_mismatch"
    mismatch_row = _lease_row(store.db_path, mismatch["lease_id"])
    assert (mismatch_row["uses"], mismatch_row["state"]) == (0, "active")


def test_measured_and_reserved_byte_evidence_is_sealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _store(tmp_path)
    measured = _issue(
        store,
        connection_id="measured-byte-connection",
        purpose="screen_share",
    )
    measured_use = store.consume(
        str(measured["token"]),
        **_request_values(
            connection_id="measured-byte-connection",
            purpose="screen_share",
            bytes_used=321,
        ),
    )["use_receipt"]
    assert measured_use["receipt_version"] == 2
    assert str(measured_use["event_id"]).startswith("evt_")
    assert measured_use["bytes_used"] == 321
    assert measured_use["byte_accounting"] == "measured"

    resource = "workspace:private/reserved.txt"
    reserved = _issue(
        store,
        connection_id="reserved-byte-connection",
        purpose="file_source_ref",
        resource_binding=resource,
    )
    cap = int(reserved["max_bytes_per_use"])
    reserved_use = store.consume(
        str(reserved["token"]),
        **_request_values(
            connection_id="reserved-byte-connection",
            purpose="file_source_ref",
            resource_binding=resource,
            bytes_used=cap,
            byte_accounting="reserved",
        ),
    )["use_receipt"]
    assert reserved_use["bytes_used"] == cap
    assert reserved_use["byte_accounting"] == "reserved"

    with connect(store.db_path) as conn:
        conn.execute("DROP TRIGGER capability_lease_receipts_immutable_update")
        conn.execute(
            "UPDATE capability_lease_receipts SET bytes_used=322 "
            "WHERE receipt_id=?",
            (measured_use["receipt_id"],),
        )
    monkeypatch.setattr(lease_mod.time, "time", lambda: NOW + 2)
    with pytest.raises(
        lease_mod.CapabilityLeaseIntegrityError, match="receipt seal"
    ):
        store.status()


def test_legacy_v1_receipts_migrate_and_remain_verifiable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db_path, grant = _legacy_v1_database(tmp_path)
    store = lease_mod.CapabilityLeaseStore(db_path, seal_key=SEAL_KEY)

    with connect(db_path) as conn:
        columns = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA table_info(capability_lease_receipts)"
            ).fetchall()
        }
        indexes = {
            str(row["name"])
            for row in conn.execute(
                "PRAGMA index_list(capability_lease_receipts)"
            ).fetchall()
        }
        legacy = conn.execute(
            "SELECT * FROM capability_lease_receipts WHERE event='grant'"
        ).fetchone()
    assert {
        "receipt_version",
        "event_id",
        "bytes_used",
        "byte_accounting",
    }.issubset(columns)
    assert "capability_lease_event_id_idx" in indexes
    assert legacy is not None
    assert legacy["receipt_version"] == 1
    assert legacy["event_id"] is None
    assert legacy["bytes_used"] is None
    assert legacy["byte_accounting"] == ""

    assert store.validate_active(
        str(grant["token"]),
        **_request_values(connection_id="legacy-connection", now=NOW + 1),
    )["state"] == "active"
    consumed = store.consume(
        str(grant["token"]),
        **_request_values(
            connection_id="legacy-connection",
            now=NOW + 2,
            bytes_used=9,
        ),
    )
    assert consumed["state"] == "stopped"
    rows = _receipt_rows(db_path, grant["lease_id"])
    assert [row["event"] for row in rows] == ["grant", "use", "stop"]
    assert [row["receipt_version"] for row in rows] == [1, 2, 2]
    assert rows[0]["event_id"] is None
    assert rows[1]["bytes_used"] == 9

    monkeypatch.setattr(lease_mod.time, "time", lambda: NOW + 3)
    status = store.status()
    assert sum(
        receipt["receipt_version"] == 1 and receipt["event_id"] is None
        for receipt in status["receipts"]
    ) == 2
    assert any(
        receipt["receipt_version"] == 1 and receipt["verified"] is True
        for receipt in status["receipts"]
    )


def test_stop_purpose_is_scoped_idempotent_and_returns_stop_evidence(
    tmp_path: Path,
):
    store = _store(tmp_path)
    screen = _issue(store, purpose="screen_share")
    camera = _issue(store)

    stopped, changed = store.stop_purpose(
        CONNECTION,
        purpose="screen_share",
        reason="screen_share_stopped",
        now=NOW + 1,
    )
    retried, retry_changed = store.stop_purpose(
        CONNECTION,
        purpose="screen_share",
        reason="different_retry_reason",
        now=NOW + 2,
    )

    assert changed is True
    assert retry_changed is False
    assert stopped is not None
    assert retried == stopped
    assert stopped["lease_id"] == screen["lease_id"]
    assert stopped["state"] == "stopped"
    assert stopped["stop_reason"] == "screen_share_stopped"
    assert stopped["stop_receipt"]["event"] == "stop"
    assert set(stopped).isdisjoint(
        {"token", "token_hmac", "connection_hmac", "resource_hmac"}
    )
    assert store.validate_active(
        str(camera["token"]), **_request_values(now=NOW + 3)
    )["state"] == "active"
    assert store.stop_purpose(
        "connection-with-no-lease",
        purpose="screen_share",
        reason="screen_share_stopped",
        now=NOW + 3,
    ) == (None, False)
