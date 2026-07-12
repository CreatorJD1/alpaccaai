"""Short-lived, connection-bound grants for private local capabilities.

Creator authentication establishes who is present; it does not itself grant
camera, screen, microphone, or file use. Tokens are returned once, retained
only by the client, and stored here only as HMACs. Connection and optional file
bindings are HMAC-only as well.

The store is deliberately model-free and content-free. It never receives or
records media, paths, transcripts, prompts, request ids, or content digests.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from alpecca.db import connect
from config import DB_PATH


CONTRACT_VERSION = 1
RECEIPT_VERSION = 2
TOKEN_HEADER = "X-Alpecca-Capability-Lease"
PURPOSE_HEADER = "X-Alpecca-Capability-Purpose"
CONNECTION_HEADER = "X-Alpecca-Capability-Connection"
_TOKEN_DOMAIN = b"alpecca.capability-lease-token.v1"
_CONNECTION_DOMAIN = b"alpecca.capability-lease-connection.v1"
_RESOURCE_DOMAIN = b"alpecca.capability-lease-resource.v1"
_LEASE_DOMAIN = "alpecca.capability-lease-grant.v1"
_RECEIPT_DOMAIN_V1 = "alpecca.capability-lease-receipt.v1"
_RECEIPT_DOMAIN_V2 = "alpecca.capability-lease-receipt.v2"
# Kept as a private compatibility alias for old tests and migration helpers.
_RECEIPT_DOMAIN = _RECEIPT_DOMAIN_V1
_EVENTS = frozenset({"grant", "deny", "use", "stop"})
_STATES = frozenset({"active", "stopped"})
_BYTE_ACCOUNTING_MODES = frozenset({"measured", "reserved"})


@dataclass(frozen=True, slots=True)
class LeasePolicy:
    purpose: str
    capability: str
    ttl_seconds: int
    max_uses: int
    max_bytes_per_use: int
    resource_bound: bool = False


POLICIES: Mapping[str, LeasePolicy] = {
    "camera_frame": LeasePolicy("camera_frame", "webcam", 60, 1, 2 * 1024 * 1024),
    "screen_share": LeasePolicy(
        "screen_share", "screen_sight", 300, 30, 2 * 1024 * 1024
    ),
    "push_to_talk": LeasePolicy(
        "push_to_talk", "microphone", 90, 1, 8 * 1024 * 1024
    ),
    "voice_enrollment": LeasePolicy(
        "voice_enrollment", "microphone", 90, 1, 8 * 1024 * 1024
    ),
    "file_source_ref": LeasePolicy(
        "file_source_ref",
        "file_access",
        120,
        1,
        2 * 1024 * 1024,
        resource_bound=True,
    ),
}


class CapabilityLeaseError(ValueError):
    """Base error for malformed lease operations."""


class CapabilityLeaseDenied(CapabilityLeaseError):
    """A lease was absent, expired, mismatched, or exhausted."""

    def __init__(self, reason: str, *, receipt_id: int | None = None) -> None:
        clean = str(reason or "").strip()
        if (
            not clean
            or len(clean) > 80
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_" for char in clean)
        ):
            clean = "lease_denied"
        public_receipt_id = (
            receipt_id
            if isinstance(receipt_id, int)
            and not isinstance(receipt_id, bool)
            and receipt_id > 0
            else None
        )
        self.reason = clean
        self.receipt_id = public_receipt_id
        self.denial_receipt_id = public_receipt_id
        super().__init__(clean.replace("_", " "))


class CapabilityLeaseIntegrityError(CapabilityLeaseError):
    """Stored grant, receipt, or mutable lifecycle evidence is invalid."""


def policy_for(purpose: str) -> LeasePolicy:
    policy = POLICIES.get(str(purpose or "").strip())
    if policy is None:
        raise CapabilityLeaseDenied("purpose_not_allowed")
    return policy


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CapabilityLeaseError("lease evidence is not canonical JSON") from exc


def _timestamp(value: float | int | None = None) -> float:
    if isinstance(value, bool):
        raise CapabilityLeaseError("timestamp must be finite and non-negative")
    stamp = float(time.time() if value is None else value)
    if not math.isfinite(stamp) or stamp < 0:
        raise CapabilityLeaseError("timestamp must be finite and non-negative")
    return stamp


def _optional_timestamp(value: float | int | None) -> float | None:
    return None if value is None else _timestamp(value)


def _identifier(value: object, name: str, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise CapabilityLeaseError(f"{name} must be text")
    clean = value.strip()
    if not clean or len(clean) > maximum or any(ord(char) < 32 for char in clean):
        raise CapabilityLeaseError(f"{name} is invalid")
    return clean


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CapabilityLeaseError(f"{name} must be a non-negative integer")
    return value


def _byte_accounting(value: object) -> str:
    if not isinstance(value, str) or value not in _BYTE_ACCOUNTING_MODES:
        raise CapabilityLeaseError("byte_accounting must be measured or reserved")
    return value


def _is_sha256(value: object, *, allow_empty: bool = False) -> bool:
    if allow_empty and value == "":
        return True
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


class CapabilityLeaseStore:
    """Issue and atomically consume sealed private-capability leases."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        seal_key: bytes | bytearray | memoryview | str,
    ) -> None:
        self.db_path = Path(db_path)
        if isinstance(seal_key, str):
            seal_key = seal_key.encode("utf-8")
        if not isinstance(seal_key, (bytes, bytearray, memoryview)):
            raise TypeError("seal_key must be bytes or text")
        self._key = bytes(seal_key)
        if not self._key:
            raise ValueError("seal_key must not be empty")
        self._schema_lock = threading.Lock()
        self._schema_ready = False
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._schema_lock:
            if self._schema_ready:
                return
            with connect(self.db_path) as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS capability_leases (
                        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                        lease_id              TEXT NOT NULL UNIQUE,
                        contract_version      INTEGER NOT NULL CHECK(contract_version=1),
                        token_hmac            TEXT NOT NULL UNIQUE,
                        connection_hmac       TEXT NOT NULL,
                        resource_hmac         TEXT NOT NULL DEFAULT '',
                        principal             TEXT NOT NULL CHECK(principal='creator'),
                        privacy_scope         TEXT NOT NULL,
                        surface               TEXT NOT NULL,
                        capability            TEXT NOT NULL,
                        purpose               TEXT NOT NULL,
                        auth_mechanism        TEXT NOT NULL,
                        auth_expires_at       REAL,
                        issued_at             REAL NOT NULL,
                        expires_at            REAL NOT NULL,
                        max_uses              INTEGER NOT NULL CHECK(max_uses>0),
                        max_bytes_per_use     INTEGER NOT NULL CHECK(max_bytes_per_use>0),
                        uses                  INTEGER NOT NULL DEFAULT 0 CHECK(uses>=0),
                        state                 TEXT NOT NULL CHECK(state IN ('active','stopped')),
                        stopped_at            REAL,
                        stop_reason           TEXT NOT NULL DEFAULT '',
                        grant_seal            TEXT NOT NULL
                    );

                    CREATE UNIQUE INDEX IF NOT EXISTS capability_leases_one_active_idx
                    ON capability_leases(connection_hmac, capability)
                    WHERE state='active';
                    CREATE INDEX IF NOT EXISTS capability_leases_expiry_idx
                    ON capability_leases(state, expires_at);

                    CREATE TRIGGER IF NOT EXISTS capability_leases_grant_immutable
                    BEFORE UPDATE OF
                        lease_id,contract_version,token_hmac,connection_hmac,
                        resource_hmac,principal,privacy_scope,surface,capability,
                        purpose,auth_mechanism,auth_expires_at,issued_at,
                        expires_at,max_uses,max_bytes_per_use,grant_seal
                    ON capability_leases
                    BEGIN
                        SELECT RAISE(ABORT, 'capability lease grant is immutable');
                    END;
                    CREATE TRIGGER IF NOT EXISTS capability_leases_monotonic
                    BEFORE UPDATE OF uses,state,stopped_at,stop_reason
                    ON capability_leases
                    WHEN
                        NEW.uses < OLD.uses
                        OR (OLD.state='stopped' AND NEW.state!='stopped')
                        OR (
                            OLD.state='stopped'
                            AND (
                                NEW.uses != OLD.uses
                                OR NEW.stopped_at IS NOT OLD.stopped_at
                                OR NEW.stop_reason != OLD.stop_reason
                            )
                        )
                        OR (
                            NEW.state='active'
                            AND (
                                NEW.stopped_at IS NOT NULL
                                OR NEW.stop_reason != ''
                            )
                        )
                        OR (
                            NEW.state='stopped'
                            AND (
                                NEW.stopped_at IS NULL
                                OR NEW.stop_reason = ''
                            )
                        )
                    BEGIN
                        SELECT RAISE(ABORT, 'capability lease state is not monotonic');
                    END;
                    CREATE TRIGGER IF NOT EXISTS capability_leases_immutable_delete
                    BEFORE DELETE ON capability_leases
                    BEGIN
                        SELECT RAISE(ABORT, 'capability leases are immutable evidence');
                    END;

                    CREATE TABLE IF NOT EXISTS capability_lease_receipts (
                        receipt_id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        receipt_version       INTEGER NOT NULL DEFAULT 1
                            CHECK(receipt_version IN (1,2)),
                        event_id              TEXT,
                        lease_id              TEXT,
                        event                 TEXT NOT NULL
                            CHECK(event IN ('grant','deny','use','stop')),
                        capability            TEXT NOT NULL,
                        purpose               TEXT NOT NULL,
                        principal             TEXT NOT NULL,
                        privacy_scope         TEXT NOT NULL,
                        surface               TEXT NOT NULL,
                        occurred_at           REAL NOT NULL,
                        expires_at            REAL NOT NULL,
                        max_uses              INTEGER NOT NULL,
                        max_bytes_per_use     INTEGER NOT NULL,
                        use_ordinal           INTEGER,
                        bytes_used            INTEGER CHECK(bytes_used IS NULL OR bytes_used>=0),
                        byte_accounting       TEXT NOT NULL DEFAULT ''
                            CHECK(byte_accounting IN ('','measured','reserved')),
                        reason                TEXT NOT NULL,
                        connection_hmac       TEXT NOT NULL,
                        resource_hmac         TEXT NOT NULL DEFAULT '',
                        receipt_seal          TEXT NOT NULL,
                        FOREIGN KEY(lease_id) REFERENCES capability_leases(lease_id)
                            ON DELETE RESTRICT
                    );

                    CREATE UNIQUE INDEX IF NOT EXISTS capability_lease_one_grant_idx
                    ON capability_lease_receipts(lease_id)
                    WHERE event='grant';
                    CREATE UNIQUE INDEX IF NOT EXISTS capability_lease_one_stop_idx
                    ON capability_lease_receipts(lease_id)
                    WHERE event='stop';
                    CREATE UNIQUE INDEX IF NOT EXISTS capability_lease_use_ordinal_idx
                    ON capability_lease_receipts(lease_id, use_ordinal)
                    WHERE event='use';
                    CREATE INDEX IF NOT EXISTS capability_lease_receipt_time_idx
                    ON capability_lease_receipts(receipt_id DESC);

                    CREATE TRIGGER IF NOT EXISTS capability_lease_receipts_immutable_update
                    BEFORE UPDATE ON capability_lease_receipts
                    BEGIN
                        SELECT RAISE(ABORT, 'capability lease receipts are immutable');
                    END;
                    CREATE TRIGGER IF NOT EXISTS capability_lease_receipts_immutable_delete
                    BEFORE DELETE ON capability_lease_receipts
                    BEGIN
                        SELECT RAISE(ABORT, 'capability lease receipts are immutable');
                    END;
                    """
                )
                columns = {
                    str(row["name"])
                    for row in conn.execute(
                        "PRAGMA table_info(capability_lease_receipts)"
                    ).fetchall()
                }
                migrations = (
                    (
                        "receipt_version",
                        "ALTER TABLE capability_lease_receipts "
                        "ADD COLUMN receipt_version INTEGER NOT NULL DEFAULT 1 "
                        "CHECK(receipt_version IN (1,2))",
                    ),
                    (
                        "event_id",
                        "ALTER TABLE capability_lease_receipts ADD COLUMN event_id TEXT",
                    ),
                    (
                        "bytes_used",
                        "ALTER TABLE capability_lease_receipts ADD COLUMN bytes_used "
                        "INTEGER CHECK(bytes_used IS NULL OR bytes_used>=0)",
                    ),
                    (
                        "byte_accounting",
                        "ALTER TABLE capability_lease_receipts ADD COLUMN byte_accounting "
                        "TEXT NOT NULL DEFAULT '' "
                        "CHECK(byte_accounting IN ('','measured','reserved'))",
                    ),
                )
                for name, statement in migrations:
                    if name not in columns:
                        conn.execute(statement)
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS capability_lease_event_id_idx "
                    "ON capability_lease_receipts(event_id) WHERE event_id IS NOT NULL"
                )
            self._schema_ready = True

    def _hmac(self, domain: bytes, value: str) -> str:
        return hmac.new(
            self._key,
            domain + b"\x00" + value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _token_hmac(self, token: str) -> str:
        if not isinstance(token, str) or not token.startswith("cl1_") or len(token) > 128:
            return self._hmac(_TOKEN_DOMAIN, "invalid")
        return self._hmac(_TOKEN_DOMAIN, token)

    def _connection_hmac(self, connection_id: str) -> str:
        return self._hmac(
            _CONNECTION_DOMAIN, _identifier(connection_id, "connection id", 200)
        )

    def _resource_hmac(self, resource_binding: str | None) -> str:
        if resource_binding is None:
            return ""
        return self._hmac(
            _RESOURCE_DOMAIN,
            _identifier(resource_binding, "resource binding", 1024),
        )

    def _seal(self, domain: str, value: Mapping[str, object]) -> str:
        material = _canonical({"domain": domain, **dict(value)})
        return hmac.new(
            self._key, material.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _grant_material(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "lease_id": str(row["lease_id"]),
            "contract_version": int(row["contract_version"]),
            "token_hmac": str(row["token_hmac"]),
            "connection_hmac": str(row["connection_hmac"]),
            "resource_hmac": str(row["resource_hmac"]),
            "principal": str(row["principal"]),
            "privacy_scope": str(row["privacy_scope"]),
            "surface": str(row["surface"]),
            "capability": str(row["capability"]),
            "purpose": str(row["purpose"]),
            "auth_mechanism": str(row["auth_mechanism"]),
            "auth_expires_at": (
                None
                if row["auth_expires_at"] is None
                else float(row["auth_expires_at"])
            ),
            "issued_at": float(row["issued_at"]),
            "expires_at": float(row["expires_at"]),
            "max_uses": int(row["max_uses"]),
            "max_bytes_per_use": int(row["max_bytes_per_use"]),
        }

    @staticmethod
    def _receipt_material_v1(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "lease_id": None if row["lease_id"] is None else str(row["lease_id"]),
            "event": str(row["event"]),
            "capability": str(row["capability"]),
            "purpose": str(row["purpose"]),
            "principal": str(row["principal"]),
            "privacy_scope": str(row["privacy_scope"]),
            "surface": str(row["surface"]),
            "occurred_at": float(row["occurred_at"]),
            "expires_at": float(row["expires_at"]),
            "max_uses": int(row["max_uses"]),
            "max_bytes_per_use": int(row["max_bytes_per_use"]),
            "use_ordinal": (
                None if row["use_ordinal"] is None else int(row["use_ordinal"])
            ),
            "reason": str(row["reason"]),
            "connection_hmac": str(row["connection_hmac"]),
            "resource_hmac": str(row["resource_hmac"]),
        }

    @classmethod
    def _receipt_material_v2(cls, row: Mapping[str, object]) -> dict[str, object]:
        return {
            **cls._receipt_material_v1(row),
            "receipt_version": RECEIPT_VERSION,
            "event_id": str(row["event_id"]),
            "bytes_used": (
                None if row["bytes_used"] is None else int(row["bytes_used"])
            ),
            "byte_accounting": str(row["byte_accounting"]),
        }

    @staticmethod
    def _receipt_version(row: Mapping[str, object]) -> int:
        value = row["receipt_version"]
        return 1 if value is None else int(value)

    @staticmethod
    def _lease_receipt_context(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "capability": str(row["capability"]),
            "purpose": str(row["purpose"]),
            "principal": str(row["principal"]),
            "privacy_scope": str(row["privacy_scope"]),
            "surface": str(row["surface"]),
            "expires_at": float(row["expires_at"]),
            "max_uses": int(row["max_uses"]),
            "max_bytes_per_use": int(row["max_bytes_per_use"]),
            "connection_hmac": str(row["connection_hmac"]),
            "resource_hmac": str(row["resource_hmac"]),
        }

    @staticmethod
    def _policy_receipt_context(
        policy: LeasePolicy,
        *,
        principal: str,
        privacy_scope: str,
        surface: str,
        expires_at: float,
        connection_hmac: str,
        resource_hmac: str,
    ) -> dict[str, object]:
        return {
            "capability": policy.capability,
            "purpose": policy.purpose,
            "principal": principal,
            "privacy_scope": privacy_scope,
            "surface": surface,
            "expires_at": expires_at,
            "max_uses": policy.max_uses,
            "max_bytes_per_use": policy.max_bytes_per_use,
            "connection_hmac": connection_hmac,
            "resource_hmac": resource_hmac,
        }

    def _verify_sealed_grant(self, row: sqlite3.Row) -> None:
        """Verify immutable grant evidence without consulting current policy."""
        try:
            material = self._grant_material(row)
            expected = self._seal(_LEASE_DOMAIN, material)
        except (KeyError, TypeError, ValueError, OverflowError, CapabilityLeaseError) as exc:
            raise CapabilityLeaseIntegrityError(
                "capability lease grant evidence is malformed"
            ) from exc
        if not hmac.compare_digest(expected, str(row["grant_seal"])):
            raise CapabilityLeaseIntegrityError("capability lease grant seal is invalid")

        issued_at = material["issued_at"]
        expires_at = material["expires_at"]
        auth_expires_at = material["auth_expires_at"]
        try:
            for field in (
                "lease_id",
                "privacy_scope",
                "surface",
                "capability",
                "purpose",
                "auth_mechanism",
            ):
                _identifier(material[field], field.replace("_", " "))
        except CapabilityLeaseError as exc:
            raise CapabilityLeaseIntegrityError(
                "capability lease grant evidence is malformed"
            ) from exc
        if (
            material["contract_version"] != CONTRACT_VERSION
            or material["principal"] != "creator"
            or not _is_sha256(material["token_hmac"])
            or not _is_sha256(material["connection_hmac"])
            or not _is_sha256(material["resource_hmac"], allow_empty=True)
            or not isinstance(issued_at, float)
            or not math.isfinite(issued_at)
            or issued_at < 0
            or not isinstance(expires_at, float)
            or not math.isfinite(expires_at)
            or expires_at <= issued_at
            or material["max_uses"] <= 0
            or material["max_bytes_per_use"] <= 0
        ):
            raise CapabilityLeaseIntegrityError("capability lease grant evidence is invalid")
        if auth_expires_at is not None and (
            not math.isfinite(auth_expires_at)
            or auth_expires_at <= issued_at
            or expires_at > auth_expires_at
        ):
            raise CapabilityLeaseIntegrityError(
                "capability lease authorization evidence is invalid"
            )

    def _verify_receipt(self, row: sqlite3.Row) -> None:
        try:
            version = self._receipt_version(row)
            event = str(row["event"])
            occurred_at = float(row["occurred_at"])
            expires_at = float(row["expires_at"])
            max_uses = int(row["max_uses"])
            max_bytes = int(row["max_bytes_per_use"])
            use_ordinal = (
                None if row["use_ordinal"] is None else int(row["use_ordinal"])
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise CapabilityLeaseIntegrityError(
                "capability lease receipt evidence is malformed"
            ) from exc
        if (
            event not in _EVENTS
            or not math.isfinite(occurred_at)
            or occurred_at < 0
            or not math.isfinite(expires_at)
            or expires_at < 0
            or max_uses <= 0
            or max_bytes <= 0
            or not _is_sha256(row["connection_hmac"])
            or not _is_sha256(row["resource_hmac"], allow_empty=True)
            or not _is_sha256(row["receipt_seal"])
        ):
            raise CapabilityLeaseIntegrityError(
                "capability lease receipt evidence is invalid"
            )
        try:
            for field in (
                "capability",
                "purpose",
                "principal",
                "privacy_scope",
                "surface",
                "reason",
            ):
                _identifier(row[field], f"receipt {field.replace('_', ' ')}")
        except CapabilityLeaseError as exc:
            raise CapabilityLeaseIntegrityError(
                "capability lease receipt evidence is malformed"
            ) from exc
        if event == "use":
            if use_ordinal is None or use_ordinal <= 0 or use_ordinal > max_uses:
                raise CapabilityLeaseIntegrityError(
                    "capability lease use receipt ordinal is invalid"
                )
        elif use_ordinal is not None:
            raise CapabilityLeaseIntegrityError(
                "capability lease non-use receipt has a use ordinal"
            )

        try:
            if version == 1:
                if (
                    row["event_id"] not in (None, "")
                    or row["bytes_used"] is not None
                    or str(row["byte_accounting"] or "") != ""
                ):
                    raise CapabilityLeaseIntegrityError(
                        "legacy capability lease receipt has unsigned v2 evidence"
                    )
                material = self._receipt_material_v1(row)
                expected = self._seal(_RECEIPT_DOMAIN_V1, material)
            elif version == RECEIPT_VERSION:
                event_id = str(row["event_id"] or "")
                if (
                    not event_id.startswith("evt_")
                    or len(event_id) > 96
                    or any(
                        char
                        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                        for char in event_id
                    )
                ):
                    raise CapabilityLeaseIntegrityError(
                        "capability lease receipt event id is invalid"
                    )
                bytes_used = (
                    None if row["bytes_used"] is None else int(row["bytes_used"])
                )
                accounting = str(row["byte_accounting"] or "")
                if bytes_used is None:
                    if accounting:
                        raise CapabilityLeaseIntegrityError(
                            "capability lease receipt byte evidence is invalid"
                        )
                elif (
                    bytes_used < 0
                    or accounting not in _BYTE_ACCOUNTING_MODES
                    or event not in {"use", "deny"}
                ):
                    raise CapabilityLeaseIntegrityError(
                        "capability lease receipt byte evidence is invalid"
                    )
                if event == "use" and bytes_used is None:
                    raise CapabilityLeaseIntegrityError(
                        "capability lease use receipt lacks byte evidence"
                    )
                material = self._receipt_material_v2(row)
                expected = self._seal(_RECEIPT_DOMAIN_V2, material)
            else:
                raise CapabilityLeaseIntegrityError(
                    "capability lease receipt version is unsupported"
                )
        except (KeyError, TypeError, ValueError, OverflowError, CapabilityLeaseError) as exc:
            if isinstance(exc, CapabilityLeaseIntegrityError):
                raise
            raise CapabilityLeaseIntegrityError(
                "capability lease receipt evidence is malformed"
            ) from exc
        if not hmac.compare_digest(expected, str(row["receipt_seal"])):
            raise CapabilityLeaseIntegrityError("capability lease receipt seal is invalid")

    def _verify_mutable_state(self, conn: sqlite3.Connection, row: sqlite3.Row) -> None:
        lease_id = str(row["lease_id"])
        receipts = conn.execute(
            "SELECT * FROM capability_lease_receipts WHERE lease_id=? "
            "ORDER BY receipt_id",
            (lease_id,),
        ).fetchall()
        if not receipts:
            raise CapabilityLeaseIntegrityError(
                "capability lease receipt chain is missing"
            )
        expected_context = self._lease_receipt_context(row)
        issued_at = float(row["issued_at"])
        expires_at = float(row["expires_at"])
        event_ids: list[str] = []
        for receipt in receipts:
            self._verify_receipt(receipt)
            if str(receipt["lease_id"]) != lease_id:
                raise CapabilityLeaseIntegrityError(
                    "capability lease receipt link is invalid"
                )
            actual_context = self._lease_receipt_context(receipt)
            if actual_context != expected_context:
                raise CapabilityLeaseIntegrityError(
                    "capability lease receipt context does not match its grant"
                )
            if float(receipt["occurred_at"]) < issued_at:
                raise CapabilityLeaseIntegrityError(
                    "capability lease receipt predates its grant"
                )
            if self._receipt_version(receipt) == RECEIPT_VERSION:
                event_ids.append(str(receipt["event_id"]))
        if len(event_ids) != len(set(event_ids)):
            raise CapabilityLeaseIntegrityError(
                "capability lease receipt event id was cloned"
            )

        grants = [receipt for receipt in receipts if receipt["event"] == "grant"]
        uses = [receipt for receipt in receipts if receipt["event"] == "use"]
        stops = [receipt for receipt in receipts if receipt["event"] == "stop"]
        if (
            len(grants) != 1
            or receipts[0]["event"] != "grant"
            or str(grants[0]["reason"]) != "granted"
            or float(grants[0]["occurred_at"]) != issued_at
        ):
            raise CapabilityLeaseIntegrityError(
                "capability lease grant receipt is invalid"
            )
        ordinals = [int(receipt["use_ordinal"]) for receipt in uses]
        if ordinals != list(range(1, len(uses) + 1)):
            raise CapabilityLeaseIntegrityError(
                "capability lease use receipt chain is invalid"
            )
        if any(str(receipt["reason"]) != "allowed" for receipt in uses):
            raise CapabilityLeaseIntegrityError(
                "capability lease use receipt reason is invalid"
            )
        if any(float(receipt["occurred_at"]) >= expires_at for receipt in uses):
            raise CapabilityLeaseIntegrityError(
                "capability lease use receipt is outside the grant window"
            )

        try:
            mutable_uses = int(row["uses"])
            max_uses = int(row["max_uses"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise CapabilityLeaseIntegrityError(
                "capability lease mutable use count is malformed"
            ) from exc
        if mutable_uses != len(uses) or mutable_uses < 0 or mutable_uses > max_uses:
            raise CapabilityLeaseIntegrityError(
                "capability lease use count does not match sealed receipts"
            )

        state = str(row["state"])
        if state not in _STATES:
            raise CapabilityLeaseIntegrityError("capability lease state is invalid")
        if state == "active":
            if (
                stops
                or row["stopped_at"] is not None
                or str(row["stop_reason"]) != ""
                or mutable_uses >= max_uses
            ):
                raise CapabilityLeaseIntegrityError(
                    "active capability lease state does not match sealed receipts"
                )
            return

        if len(stops) != 1 or row["stopped_at"] is None:
            raise CapabilityLeaseIntegrityError(
                "stopped capability lease lacks sealed stop evidence"
            )
        try:
            stopped_at = float(row["stopped_at"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise CapabilityLeaseIntegrityError(
                "capability lease stop time is malformed"
            ) from exc
        stop_reason = str(row["stop_reason"])
        stop_receipt = stops[0]
        if (
            not math.isfinite(stopped_at)
            or stopped_at < issued_at
            or not stop_reason
            or float(stop_receipt["occurred_at"]) != stopped_at
            or str(stop_receipt["reason"]) != stop_reason
            or any(int(receipt["receipt_id"]) > int(stop_receipt["receipt_id"]) for receipt in uses)
            or any(float(receipt["occurred_at"]) > stopped_at for receipt in uses)
        ):
            raise CapabilityLeaseIntegrityError(
                "capability lease stop state does not match sealed receipts"
            )

    def _verify_lease(self, conn: sqlite3.Connection, row: sqlite3.Row) -> None:
        self._verify_sealed_grant(row)
        self._verify_mutable_state(conn, row)

    @staticmethod
    def _public_lease(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "lease_id": str(row["lease_id"]),
            "contract_version": int(row["contract_version"]),
            "principal": str(row["principal"]),
            "privacy_scope": str(row["privacy_scope"]),
            "surface": str(row["surface"]),
            "capability": str(row["capability"]),
            "purpose": str(row["purpose"]),
            "issued_at": float(row["issued_at"]),
            "expires_at": float(row["expires_at"]),
            "max_uses": int(row["max_uses"]),
            "max_bytes_per_use": int(row["max_bytes_per_use"]),
            "uses": int(row["uses"]),
            "state": str(row["state"]),
            "stopped_at": (
                None if row["stopped_at"] is None else float(row["stopped_at"])
            ),
            "stop_reason": str(row["stop_reason"]),
        }

    @classmethod
    def _public_receipt(cls, row: Mapping[str, object]) -> dict[str, object]:
        accounting = str(row["byte_accounting"] or "")
        return {
            "receipt_id": int(row["receipt_id"]),
            "receipt_version": cls._receipt_version(row),
            "event_id": None if row["event_id"] is None else str(row["event_id"]),
            "lease_id": None if row["lease_id"] is None else str(row["lease_id"]),
            "event": str(row["event"]),
            "capability": str(row["capability"]),
            "purpose": str(row["purpose"]),
            "principal": str(row["principal"]),
            "privacy_scope": str(row["privacy_scope"]),
            "surface": str(row["surface"]),
            "occurred_at": float(row["occurred_at"]),
            "expires_at": float(row["expires_at"]),
            "max_uses": int(row["max_uses"]),
            "max_bytes_per_use": int(row["max_bytes_per_use"]),
            "use_ordinal": (
                None if row["use_ordinal"] is None else int(row["use_ordinal"])
            ),
            "bytes_used": (
                None if row["bytes_used"] is None else int(row["bytes_used"])
            ),
            "byte_accounting": accounting or None,
            "reason": str(row["reason"]),
            "verified": True,
        }

    @staticmethod
    def _receipt_id(row: sqlite3.Row | None) -> int | None:
        return None if row is None else int(row["receipt_id"])

    def _record_receipt(
        self,
        conn: sqlite3.Connection,
        *,
        lease_id: str | None,
        event: str,
        context: Mapping[str, object],
        occurred_at: float,
        reason: str,
        use_ordinal: int | None = None,
        bytes_used: int | None = None,
        byte_accounting: str = "",
    ) -> sqlite3.Row:
        if event not in _EVENTS:
            raise CapabilityLeaseError("receipt event is invalid")
        clean_reason = _identifier(reason, "receipt reason", 80)
        if bytes_used is not None:
            used_bytes = _nonnegative_int(bytes_used, "bytes_used")
            accounting = _byte_accounting(byte_accounting)
        else:
            used_bytes = None
            accounting = ""
        if event == "use":
            if use_ordinal is None or use_ordinal <= 0 or used_bytes is None:
                raise CapabilityLeaseError("use receipt evidence is incomplete")
        elif use_ordinal is not None:
            raise CapabilityLeaseError("non-use receipt cannot have a use ordinal")
        if event not in {"use", "deny"} and used_bytes is not None:
            raise CapabilityLeaseError("receipt event cannot have byte evidence")

        base = {
            "lease_id": lease_id,
            "event": event,
            "capability": str(context["capability"]),
            "purpose": str(context["purpose"]),
            "principal": str(context["principal"]),
            "privacy_scope": str(context["privacy_scope"]),
            "surface": str(context["surface"]),
            "occurred_at": float(occurred_at),
            "expires_at": float(context["expires_at"]),
            "max_uses": int(context["max_uses"]),
            "max_bytes_per_use": int(context["max_bytes_per_use"]),
            "use_ordinal": use_ordinal,
            "bytes_used": used_bytes,
            "byte_accounting": accounting,
            "reason": clean_reason,
            "connection_hmac": str(context["connection_hmac"]),
            "resource_hmac": str(context["resource_hmac"]),
        }
        last_collision: sqlite3.IntegrityError | None = None
        for _attempt in range(4):
            event_id = "evt_" + secrets.token_urlsafe(18)
            material = {
                **base,
                "receipt_version": RECEIPT_VERSION,
                "event_id": event_id,
            }
            seal = self._seal(_RECEIPT_DOMAIN_V2, material)
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO capability_lease_receipts
                        (receipt_version,event_id,lease_id,event,capability,purpose,
                         principal,privacy_scope,surface,occurred_at,expires_at,
                         max_uses,max_bytes_per_use,use_ordinal,bytes_used,
                         byte_accounting,reason,connection_hmac,resource_hmac,
                         receipt_seal)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        RECEIPT_VERSION,
                        event_id,
                        lease_id,
                        event,
                        base["capability"],
                        base["purpose"],
                        base["principal"],
                        base["privacy_scope"],
                        base["surface"],
                        base["occurred_at"],
                        base["expires_at"],
                        base["max_uses"],
                        base["max_bytes_per_use"],
                        use_ordinal,
                        used_bytes,
                        accounting,
                        clean_reason,
                        base["connection_hmac"],
                        base["resource_hmac"],
                        seal,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if "capability_lease_receipts.event_id" not in str(exc):
                    raise
                last_collision = exc
                continue
            row = conn.execute(
                "SELECT * FROM capability_lease_receipts WHERE receipt_id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
            assert row is not None
            self._verify_receipt(row)
            return row
        raise CapabilityLeaseError("could not allocate a unique receipt event id") from last_collision

    def _record_receipt_for_lease(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        event: str,
        occurred_at: float,
        reason: str,
        use_ordinal: int | None = None,
        bytes_used: int | None = None,
        byte_accounting: str = "",
    ) -> sqlite3.Row:
        return self._record_receipt(
            conn,
            lease_id=str(row["lease_id"]),
            event=event,
            context=self._lease_receipt_context(row),
            occurred_at=occurred_at,
            reason=reason,
            use_ordinal=use_ordinal,
            bytes_used=bytes_used,
            byte_accounting=byte_accounting,
        )

    def _find_stop_receipt(
        self, conn: sqlite3.Connection, lease_id: str
    ) -> sqlite3.Row | None:
        receipt = conn.execute(
            "SELECT * FROM capability_lease_receipts "
            "WHERE lease_id=? AND event='stop'",
            (lease_id,),
        ).fetchone()
        if receipt is not None:
            self._verify_receipt(receipt)
        return receipt

    def _public_lease_with_stop(
        self, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> dict[str, object]:
        public = self._public_lease(row)
        if str(row["state"]) == "stopped":
            receipt = self._find_stop_receipt(conn, str(row["lease_id"]))
            if receipt is not None:
                public["stop_receipt"] = self._public_receipt(receipt)
        return public

    def _stop_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        reason: str,
        stopped_at: float,
    ) -> tuple[sqlite3.Row, sqlite3.Row | None, bool]:
        if str(row["state"]) != "active":
            return (
                row,
                self._find_stop_receipt(conn, str(row["lease_id"])),
                False,
            )
        clean_reason = _identifier(reason, "stop reason", 80)
        stamp = _timestamp(stopped_at)
        if stamp < float(row["issued_at"]):
            raise CapabilityLeaseError("stop timestamp predates lease issue")
        cursor = conn.execute(
            "UPDATE capability_leases SET state='stopped', stopped_at=?, stop_reason=? "
            "WHERE lease_id=? AND state='active'",
            (stamp, clean_reason, str(row["lease_id"])),
        )
        if cursor.rowcount != 1:
            stored = conn.execute(
                "SELECT * FROM capability_leases WHERE lease_id=?",
                (str(row["lease_id"]),),
            ).fetchone()
            if stored is None:
                raise CapabilityLeaseIntegrityError("capability lease disappeared")
            return stored, self._find_stop_receipt(conn, str(row["lease_id"])), False
        receipt = self._record_receipt_for_lease(
            conn,
            row,
            event="stop",
            occurred_at=stamp,
            reason=clean_reason,
        )
        stored = conn.execute(
            "SELECT * FROM capability_leases WHERE lease_id=?",
            (str(row["lease_id"]),),
        ).fetchone()
        assert stored is not None
        self._verify_lease(conn, stored)
        return stored, receipt, True

    @staticmethod
    def _safe_stop_stamp(row: Mapping[str, object], stamp: float) -> float:
        try:
            issued_at = float(row["issued_at"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return stamp
        return max(stamp, issued_at) if math.isfinite(issued_at) else stamp

    def _quarantine_active_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        stamp: float,
    ) -> bool:
        if str(row["state"]) != "active":
            return False
        stopped_at = self._safe_stop_stamp(row, stamp)
        cursor = conn.execute(
            "UPDATE capability_leases SET state='stopped', stopped_at=?, "
            "stop_reason='integrity_failure' WHERE id=? AND state='active'",
            (stopped_at, int(row["id"])),
        )
        if cursor.rowcount != 1:
            return False

        # A quarantine must commit even when old-key or corrupt context prevents
        # a trustworthy linked receipt. Keep receipt creation in its own savepoint.
        conn.execute("SAVEPOINT capability_quarantine_receipt")
        try:
            self._record_receipt_for_lease(
                conn,
                row,
                event="stop",
                occurred_at=stopped_at,
                reason="integrity_failure",
            )
        except (CapabilityLeaseError, sqlite3.Error, KeyError, TypeError, ValueError):
            conn.execute("ROLLBACK TO capability_quarantine_receipt")
        finally:
            conn.execute("RELEASE capability_quarantine_receipt")
        return True

    def _verify_for_operation(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        stamp: float,
    ) -> CapabilityLeaseIntegrityError | None:
        try:
            self._verify_lease(conn, row)
        except CapabilityLeaseIntegrityError as exc:
            self._quarantine_active_row(conn, row, stamp=stamp)
            return exc
        return None

    @staticmethod
    def _context_reason(
        row: sqlite3.Row,
        *,
        connection_hmac: str,
        resource_hmac: str,
        principal: str,
        privacy_scope: str,
        surface: str,
        purpose: str,
    ) -> str:
        if str(row["connection_hmac"]) != connection_hmac:
            return "connection_mismatch"
        if str(row["principal"]) != principal:
            return "principal_mismatch"
        if str(row["privacy_scope"]) != privacy_scope:
            return "scope_mismatch"
        if str(row["surface"]) != surface:
            return "surface_mismatch"
        if str(row["purpose"]) != purpose:
            return "purpose_mismatch"
        if str(row["resource_hmac"]) != resource_hmac:
            return "resource_mismatch"
        return ""

    @staticmethod
    def _lifecycle_reason(row: sqlite3.Row, *, stamp: float) -> str:
        if stamp < float(row["issued_at"]):
            return "clock_rollback"
        if str(row["state"]) != "active":
            return (
                "lease_expired"
                if str(row["stop_reason"]) == "expired"
                else "lease_stopped"
            )
        if stamp >= float(row["expires_at"]):
            return "lease_expired"
        if int(row["uses"]) >= int(row["max_uses"]):
            return "use_cap_reached"
        return ""

    def _record_policy_denial(
        self,
        conn: sqlite3.Connection,
        *,
        policy: LeasePolicy,
        principal: str,
        privacy_scope: str,
        surface: str,
        occurred_at: float,
        expires_at: float,
        connection_hmac: str,
        resource_hmac: str,
        reason: str,
        bytes_used: int | None = None,
        byte_accounting: str = "",
    ) -> sqlite3.Row:
        return self._record_receipt(
            conn,
            lease_id=None,
            event="deny",
            context=self._policy_receipt_context(
                policy,
                principal=principal,
                privacy_scope=privacy_scope,
                surface=surface,
                expires_at=expires_at,
                connection_hmac=connection_hmac,
                resource_hmac=resource_hmac,
            ),
            occurred_at=occurred_at,
            reason=reason,
            bytes_used=bytes_used,
            byte_accounting=byte_accounting,
        )

    def _transition_active_id(
        self,
        row_id: int,
        *,
        reason: str,
        stamp: float,
    ) -> bool:
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM capability_leases WHERE id=? AND state='active'",
                (row_id,),
            ).fetchone()
            if row is None:
                return False
            try:
                self._verify_lease(conn, row)
            except CapabilityLeaseIntegrityError:
                return self._quarantine_active_row(conn, row, stamp=stamp)

            stop_reason = "clock_rollback" if stamp < float(row["issued_at"]) else reason
            stop_stamp = self._safe_stop_stamp(row, stamp)
            conn.execute("SAVEPOINT capability_transition")
            try:
                _stored, _receipt, changed = self._stop_row(
                    conn, row, reason=stop_reason, stopped_at=stop_stamp
                )
            except (CapabilityLeaseError, sqlite3.Error):
                conn.execute("ROLLBACK TO capability_transition")
                conn.execute("RELEASE capability_transition")
                current = conn.execute(
                    "SELECT * FROM capability_leases WHERE id=?", (row_id,)
                ).fetchone()
                if current is None:
                    return False
                return self._quarantine_active_row(conn, current, stamp=stamp)
            conn.execute("RELEASE capability_transition")
            return changed

    def issue(
        self,
        *,
        connection_id: str,
        principal: str,
        privacy_scope: str,
        surface: str,
        purpose: str,
        auth_mechanism: str,
        auth_expires_at: float | int | None = None,
        resource_binding: str | None = None,
        now: float | int | None = None,
    ) -> dict[str, object]:
        """Mint one opaque token and a content-free sealed grant receipt."""
        policy = policy_for(purpose)
        principal = _identifier(principal, "principal")
        if principal != "creator":
            raise CapabilityLeaseDenied("creator_required")
        privacy_scope = _identifier(privacy_scope, "privacy scope")
        surface = _identifier(surface, "surface")
        auth_mechanism = _identifier(auth_mechanism, "authorization mechanism")
        stamp = _timestamp(now)
        auth_expiry = _optional_timestamp(auth_expires_at)
        if auth_expiry is not None and auth_expiry <= stamp:
            raise CapabilityLeaseDenied("authorization_expired")
        expires_at = min(
            stamp + policy.ttl_seconds,
            auth_expiry if auth_expiry is not None else math.inf,
        )
        connection_hmac = self._connection_hmac(connection_id)
        resource_hmac = self._resource_hmac(resource_binding)
        if policy.resource_bound and not resource_hmac:
            raise CapabilityLeaseDenied("resource_binding_required")
        if not policy.resource_bound and resource_hmac:
            raise CapabilityLeaseDenied("resource_binding_not_allowed")

        with connect(self.db_path) as conn:
            clock_rollback = conn.execute(
                "SELECT 1 FROM capability_leases "
                "WHERE state='active' AND issued_at>? LIMIT 1",
                (stamp,),
            ).fetchone() is not None
        self.expire_due(now=stamp)
        token = "cl1_" + secrets.token_urlsafe(32)
        token_hmac = self._token_hmac(token)
        lease_id = "lease_" + secrets.token_urlsafe(18)
        denied = "clock_rollback" if clock_rollback else ""
        denial_receipt: sqlite3.Row | None = None
        receipt: sqlite3.Row | None = None
        stored: sqlite3.Row | None = None
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM capability_leases "
                "WHERE connection_hmac=? AND capability=? AND state='active'",
                (connection_hmac, policy.capability),
            ).fetchone()
            if existing is not None and not denied:
                integrity = self._verify_for_operation(conn, existing, stamp=stamp)
                if integrity is not None:
                    existing = None
                elif stamp < float(existing["issued_at"]):
                    self._stop_row(
                        conn,
                        existing,
                        reason="clock_rollback",
                        stopped_at=float(existing["issued_at"]),
                    )
                    denied = "clock_rollback"
                elif float(existing["expires_at"]) <= stamp:
                    self._stop_row(
                        conn, existing, reason="expired", stopped_at=stamp
                    )
                    existing = None
                else:
                    denied = "active_lease_exists"
            if denied:
                denial_receipt = self._record_policy_denial(
                    conn,
                    policy=policy,
                    principal=principal,
                    privacy_scope=privacy_scope,
                    surface=surface,
                    occurred_at=stamp,
                    expires_at=expires_at,
                    connection_hmac=connection_hmac,
                    resource_hmac=resource_hmac,
                    reason=denied,
                )
            elif existing is None:
                grant = {
                    "lease_id": lease_id,
                    "contract_version": CONTRACT_VERSION,
                    "token_hmac": token_hmac,
                    "connection_hmac": connection_hmac,
                    "resource_hmac": resource_hmac,
                    "principal": principal,
                    "privacy_scope": privacy_scope,
                    "surface": surface,
                    "capability": policy.capability,
                    "purpose": policy.purpose,
                    "auth_mechanism": auth_mechanism,
                    "auth_expires_at": auth_expiry,
                    "issued_at": stamp,
                    "expires_at": expires_at,
                    "max_uses": policy.max_uses,
                    "max_bytes_per_use": policy.max_bytes_per_use,
                }
                grant_seal = self._seal(_LEASE_DOMAIN, grant)
                conn.execute(
                    """
                    INSERT INTO capability_leases
                        (lease_id,contract_version,token_hmac,connection_hmac,
                         resource_hmac,principal,privacy_scope,surface,capability,
                         purpose,auth_mechanism,auth_expires_at,issued_at,
                         expires_at,max_uses,max_bytes_per_use,uses,state,
                         stopped_at,stop_reason,grant_seal)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,'active',NULL,'',?)
                    """,
                    (
                        lease_id,
                        CONTRACT_VERSION,
                        token_hmac,
                        connection_hmac,
                        resource_hmac,
                        principal,
                        privacy_scope,
                        surface,
                        policy.capability,
                        policy.purpose,
                        auth_mechanism,
                        auth_expiry,
                        stamp,
                        expires_at,
                        policy.max_uses,
                        policy.max_bytes_per_use,
                        grant_seal,
                    ),
                )
                stored = conn.execute(
                    "SELECT * FROM capability_leases WHERE lease_id=?", (lease_id,)
                ).fetchone()
                assert stored is not None
                receipt = self._record_receipt_for_lease(
                    conn,
                    stored,
                    event="grant",
                    occurred_at=stamp,
                    reason="granted",
                )
                self._verify_lease(conn, stored)
        if denied:
            raise CapabilityLeaseDenied(
                denied, receipt_id=self._receipt_id(denial_receipt)
            )
        assert stored is not None and receipt is not None
        return {
            **self._public_lease(stored),
            "token": token,
            "receipt": self._public_receipt(receipt),
        }

    def consume(
        self,
        token: str,
        *,
        connection_id: str,
        principal: str,
        privacy_scope: str,
        surface: str,
        purpose: str,
        bytes_used: int,
        byte_accounting: str = "measured",
        resource_binding: str | None = None,
        now: float | int | None = None,
    ) -> dict[str, object]:
        """Consume one use atomically before a private capability proceeds."""
        requested_purpose = _identifier(purpose, "purpose")
        used_bytes = _nonnegative_int(bytes_used, "bytes_used")
        accounting = _byte_accounting(byte_accounting)
        principal = _identifier(principal, "principal")
        privacy_scope = _identifier(privacy_scope, "privacy scope")
        surface = _identifier(surface, "surface")
        stamp = _timestamp(now)
        connection_hmac = self._connection_hmac(connection_id)
        resource_hmac = self._resource_hmac(resource_binding)
        token_hmac = self._token_hmac(token)
        denied = ""
        denial_receipt: sqlite3.Row | None = None
        integrity_error: CapabilityLeaseIntegrityError | None = None
        result: dict[str, object] | None = None
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM capability_leases WHERE token_hmac=?",
                (token_hmac,),
            ).fetchone()
            if row is None:
                policy = policy_for(requested_purpose)
                denied = "invalid_token"
                denial_receipt = self._record_policy_denial(
                    conn,
                    policy=policy,
                    principal=principal,
                    privacy_scope=privacy_scope,
                    surface=surface,
                    occurred_at=stamp,
                    expires_at=stamp,
                    connection_hmac=connection_hmac,
                    resource_hmac=resource_hmac,
                    reason=denied,
                    bytes_used=used_bytes,
                    byte_accounting=accounting,
                )
            else:
                integrity_error = self._verify_for_operation(conn, row, stamp=stamp)
                if integrity_error is None:
                    denied = self._context_reason(
                        row,
                        connection_hmac=connection_hmac,
                        resource_hmac=resource_hmac,
                        principal=principal,
                        privacy_scope=privacy_scope,
                        surface=surface,
                        purpose=requested_purpose,
                    )
                if integrity_error is None and not denied:
                    denied = self._lifecycle_reason(row, stamp=stamp)
                if integrity_error is None and not denied:
                    if used_bytes > int(row["max_bytes_per_use"]):
                        denied = "byte_cap_exceeded"
                if integrity_error is None and denied:
                    event_stamp = self._safe_stop_stamp(row, stamp)
                    if denied in {
                        "clock_rollback",
                        "lease_expired",
                        "byte_cap_exceeded",
                    } and str(row["state"]) == "active":
                        stop_reason = "expired" if denied == "lease_expired" else denied
                        row, _stop_receipt, _changed = self._stop_row(
                            conn,
                            row,
                            reason=stop_reason,
                            stopped_at=event_stamp,
                        )
                    denial_receipt = self._record_receipt_for_lease(
                        conn,
                        row,
                        event="deny",
                        occurred_at=event_stamp,
                        reason=denied,
                        bytes_used=used_bytes,
                        byte_accounting=accounting,
                    )
                elif integrity_error is None:
                    ordinal = int(row["uses"]) + 1
                    cursor = conn.execute(
                        "UPDATE capability_leases SET uses=? "
                        "WHERE lease_id=? AND state='active' AND uses=?",
                        (ordinal, str(row["lease_id"]), int(row["uses"])),
                    )
                    if cursor.rowcount != 1:
                        raise CapabilityLeaseIntegrityError(
                            "capability lease use transition was not atomic"
                        )
                    use_receipt = self._record_receipt_for_lease(
                        conn,
                        row,
                        event="use",
                        occurred_at=stamp,
                        reason="allowed",
                        use_ordinal=ordinal,
                        bytes_used=used_bytes,
                        byte_accounting=accounting,
                    )
                    stored = conn.execute(
                        "SELECT * FROM capability_leases WHERE lease_id=?",
                        (str(row["lease_id"]),),
                    ).fetchone()
                    assert stored is not None
                    stop_receipt: sqlite3.Row | None = None
                    if ordinal >= int(row["max_uses"]):
                        stored, stop_receipt, _changed = self._stop_row(
                            conn,
                            stored,
                            reason="use_cap_reached",
                            stopped_at=stamp,
                        )
                    else:
                        self._verify_lease(conn, stored)
                    result = {
                        **self._public_lease(stored),
                        "use_receipt": self._public_receipt(use_receipt),
                    }
                    if stop_receipt is not None:
                        result["stop_receipt"] = self._public_receipt(stop_receipt)
        if integrity_error is not None:
            raise integrity_error
        if denied:
            raise CapabilityLeaseDenied(
                denied, receipt_id=self._receipt_id(denial_receipt)
            )
        assert result is not None
        return result

    def validate_active(
        self,
        token: str,
        *,
        connection_id: str,
        principal: str,
        privacy_scope: str,
        surface: str,
        purpose: str,
        resource_binding: str | None = None,
        now: float | int | None = None,
    ) -> dict[str, object]:
        """Verify a lease without consuming a use (for start-state controls)."""
        requested_purpose = _identifier(purpose, "purpose")
        stamp = _timestamp(now)
        connection_hmac = self._connection_hmac(connection_id)
        resource_hmac = self._resource_hmac(resource_binding)
        principal = _identifier(principal, "principal")
        privacy_scope = _identifier(privacy_scope, "privacy scope")
        surface = _identifier(surface, "surface")
        denied = ""
        denial_receipt: sqlite3.Row | None = None
        integrity_error: CapabilityLeaseIntegrityError | None = None
        public: dict[str, object] | None = None
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM capability_leases WHERE token_hmac=?",
                (self._token_hmac(token),),
            ).fetchone()
            if row is None:
                policy = policy_for(requested_purpose)
                denied = "invalid_token"
                denial_receipt = self._record_policy_denial(
                    conn,
                    policy=policy,
                    principal=principal,
                    privacy_scope=privacy_scope,
                    surface=surface,
                    occurred_at=stamp,
                    expires_at=stamp,
                    connection_hmac=connection_hmac,
                    resource_hmac=resource_hmac,
                    reason=denied,
                )
            else:
                integrity_error = self._verify_for_operation(conn, row, stamp=stamp)
                if integrity_error is None:
                    denied = self._context_reason(
                        row,
                        connection_hmac=connection_hmac,
                        resource_hmac=resource_hmac,
                        principal=principal,
                        privacy_scope=privacy_scope,
                        surface=surface,
                        purpose=requested_purpose,
                    )
                if integrity_error is None and not denied:
                    denied = self._lifecycle_reason(row, stamp=stamp)
                if integrity_error is None and denied:
                    event_stamp = self._safe_stop_stamp(row, stamp)
                    if denied in {"clock_rollback", "lease_expired"} and str(
                        row["state"]
                    ) == "active":
                        stop_reason = "expired" if denied == "lease_expired" else denied
                        row, _stop_receipt, _changed = self._stop_row(
                            conn,
                            row,
                            reason=stop_reason,
                            stopped_at=event_stamp,
                        )
                    denial_receipt = self._record_receipt_for_lease(
                        conn,
                        row,
                        event="deny",
                        occurred_at=event_stamp,
                        reason=denied,
                    )
                elif integrity_error is None:
                    public = self._public_lease(row)
        if integrity_error is not None:
            raise integrity_error
        if denied:
            raise CapabilityLeaseDenied(
                denied, receipt_id=self._receipt_id(denial_receipt)
            )
        assert public is not None
        return public

    def stop(
        self,
        lease_id: str,
        *,
        connection_id: str,
        reason: str = "client_stop",
        now: float | int | None = None,
    ) -> tuple[dict[str, object], bool]:
        clean_id = _identifier(lease_id, "lease id")
        clean_reason = _identifier(reason, "stop reason", 80)
        connection_hmac = self._connection_hmac(connection_id)
        stamp = _timestamp(now)
        denied = ""
        denial_receipt: sqlite3.Row | None = None
        integrity_error: CapabilityLeaseIntegrityError | None = None
        changed = False
        public: dict[str, object] | None = None
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM capability_leases WHERE lease_id=?", (clean_id,)
            ).fetchone()
            if row is None:
                denied = "lease_not_found"
            else:
                integrity_error = self._verify_for_operation(conn, row, stamp=stamp)
                if integrity_error is None and str(row["connection_hmac"]) != connection_hmac:
                    denied = "connection_mismatch"
                elif integrity_error is None and stamp < float(row["issued_at"]):
                    denied = "clock_rollback"
                    if str(row["state"]) == "active":
                        row, _stop_receipt, changed = self._stop_row(
                            conn,
                            row,
                            reason=denied,
                            stopped_at=float(row["issued_at"]),
                        )
                elif integrity_error is None and str(row["state"]) == "active":
                    row, _stop_receipt, changed = self._stop_row(
                        conn, row, reason=clean_reason, stopped_at=stamp
                    )
                if integrity_error is None and denied:
                    denial_receipt = self._record_receipt_for_lease(
                        conn,
                        row,
                        event="deny",
                        occurred_at=self._safe_stop_stamp(row, stamp),
                        reason=denied,
                    )
                elif integrity_error is None:
                    public = self._public_lease_with_stop(conn, row)
        if integrity_error is not None:
            raise integrity_error
        if denied:
            raise CapabilityLeaseDenied(
                denied, receipt_id=self._receipt_id(denial_receipt)
            )
        assert public is not None
        return public, changed

    def stop_purpose(
        self,
        connection_id: str,
        *,
        purpose: str,
        reason: str,
        now: float | int | None = None,
    ) -> tuple[dict[str, object] | None, bool]:
        """Stop the current connection/purpose lease without trusting a token."""
        connection_hmac = self._connection_hmac(connection_id)
        clean_purpose = _identifier(purpose, "purpose")
        clean_reason = _identifier(reason, "stop reason", 80)
        stamp = _timestamp(now)
        denied = ""
        denial_receipt: sqlite3.Row | None = None
        integrity_error: CapabilityLeaseIntegrityError | None = None
        changed = False
        public: dict[str, object] | None = None
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM capability_leases "
                "WHERE connection_hmac=? AND purpose=? AND state='active' "
                "ORDER BY id DESC LIMIT 1",
                (connection_hmac, clean_purpose),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM capability_leases "
                    "WHERE connection_hmac=? AND purpose=? "
                    "ORDER BY id DESC LIMIT 1",
                    (connection_hmac, clean_purpose),
                ).fetchone()
            if row is not None:
                integrity_error = self._verify_for_operation(conn, row, stamp=stamp)
                if integrity_error is None and stamp < float(row["issued_at"]):
                    denied = "clock_rollback"
                    if str(row["state"]) == "active":
                        row, _stop_receipt, changed = self._stop_row(
                            conn,
                            row,
                            reason=denied,
                            stopped_at=float(row["issued_at"]),
                        )
                    denial_receipt = self._record_receipt_for_lease(
                        conn,
                        row,
                        event="deny",
                        occurred_at=float(row["issued_at"]),
                        reason=denied,
                    )
                elif integrity_error is None:
                    if str(row["state"]) == "active":
                        row, _stop_receipt, changed = self._stop_row(
                            conn, row, reason=clean_reason, stopped_at=stamp
                        )
                    public = self._public_lease_with_stop(conn, row)
        if integrity_error is not None:
            raise integrity_error
        if denied:
            raise CapabilityLeaseDenied(
                denied, receipt_id=self._receipt_id(denial_receipt)
            )
        return public, changed

    def stop_connection(
        self,
        connection_id: str,
        *,
        reason: str,
        now: float | int | None = None,
    ) -> int:
        connection_hmac = self._connection_hmac(connection_id)
        clean_reason = _identifier(reason, "stop reason", 80)
        stamp = _timestamp(now)
        with connect(self.db_path) as conn:
            row_ids = [
                int(row["id"])
                for row in conn.execute(
                    "SELECT id FROM capability_leases "
                    "WHERE connection_hmac=? AND state='active' ORDER BY id",
                    (connection_hmac,),
                ).fetchall()
            ]
        return sum(
            self._transition_active_id(row_id, reason=clean_reason, stamp=stamp)
            for row_id in row_ids
        )

    def expire_due(self, *, now: float | int | None = None) -> int:
        stamp = _timestamp(now)
        with connect(self.db_path) as conn:
            row_ids = [
                int(row["id"])
                for row in conn.execute(
                    "SELECT id FROM capability_leases "
                    "WHERE state='active' AND (expires_at<=? OR issued_at>?) "
                    "ORDER BY id",
                    (stamp, stamp),
                ).fetchall()
            ]
        return sum(
            self._transition_active_id(row_id, reason="expired", stamp=stamp)
            for row_id in row_ids
        )

    def recover_active(self, *, now: float | int | None = None) -> int:
        """Revoke active rows independently; invalid evidence is quarantined."""
        stamp = _timestamp(now)
        with connect(self.db_path) as conn:
            row_ids = [
                int(row["id"])
                for row in conn.execute(
                    "SELECT id FROM capability_leases WHERE state='active' ORDER BY id"
                ).fetchall()
            ]
        return sum(
            self._transition_active_id(
                row_id, reason="server_restart", stamp=stamp
            )
            for row_id in row_ids
        )

    def status(self, *, receipt_limit: int = 50) -> dict[str, object]:
        if (
            isinstance(receipt_limit, bool)
            or not isinstance(receipt_limit, int)
            or not 1 <= receipt_limit <= 100
        ):
            raise CapabilityLeaseError("receipt_limit must be between 1 and 100")
        self.expire_due()
        with connect(self.db_path) as conn:
            leases = conn.execute(
                "SELECT * FROM capability_leases ORDER BY id"
            ).fetchall()
            duplicate_event = conn.execute(
                "SELECT event_id FROM capability_lease_receipts "
                "WHERE event_id IS NOT NULL GROUP BY event_id "
                "HAVING COUNT(*)>1 LIMIT 1"
            ).fetchone()
            if duplicate_event is not None:
                raise CapabilityLeaseIntegrityError(
                    "capability lease receipt event id was cloned"
                )
            receipts = conn.execute(
                "SELECT * FROM capability_lease_receipts "
                "ORDER BY receipt_id DESC LIMIT ?",
                (receipt_limit,),
            ).fetchall()
            for row in leases:
                self._verify_lease(conn, row)
            for row in receipts:
                self._verify_receipt(row)
            active = [row for row in leases if str(row["state"]) == "active"]
            public_active = [self._public_lease(row) for row in active]
            public_receipts = [self._public_receipt(row) for row in receipts]
        return {
            "active": public_active,
            "receipts": public_receipts,
            "policies": [
                {
                    "purpose": item.purpose,
                    "capability": item.capability,
                    "ttl_seconds": item.ttl_seconds,
                    "max_uses": item.max_uses,
                    "max_bytes_per_use": item.max_bytes_per_use,
                    "resource_bound": item.resource_bound,
                }
                for item in POLICIES.values()
            ],
        }


__all__ = [
    "CONNECTION_HEADER",
    "CONTRACT_VERSION",
    "POLICIES",
    "PURPOSE_HEADER",
    "RECEIPT_VERSION",
    "TOKEN_HEADER",
    "CapabilityLeaseDenied",
    "CapabilityLeaseError",
    "CapabilityLeaseIntegrityError",
    "CapabilityLeaseStore",
    "LeasePolicy",
    "policy_for",
]
