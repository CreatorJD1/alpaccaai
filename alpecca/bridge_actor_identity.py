"""Model-free signed guest identity for one trusted Discord bridge boundary.

The store instance is the issuer/verifier capability.  Its service, platform,
adapter boundary, clock, policy, key version, database, and external monotonic
anchor are fixed at construction.  Public issue and verify operations accept
the actual bounded request bytes and server-derived Discord identifiers; they
do not accept identity, service, platform, principal, timestamp, or digest
assertions.

Only domain-separated HMACs of request bytes and external identifiers cross the
transport or persistence boundary.  Every verified actor is structurally a
guest.  This module does not enable guild participation or Discord voice.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from alpecca.db import connect


SCHEMA_VERSION = 2
ENVELOPE_VERSION = 2
EVIDENCE_VERSION = 2
SUPPORTED_POLICY_VERSION = 1
MIN_KEY_BYTES = 32
GUILD_PARTICIPATION_ENABLED = False
VOICE_ENABLED = False

_LABEL_RE = re.compile(r"[a-z0-9](?:[a-z0-9_-]{0,63})\Z")
_HMAC_RE = re.compile(r"[0-9a-f]{64}\Z")
_DECISIONS = frozenset({"accept", "deny"})
_REASONS = frozenset(
    {
        "accepted",
        "malformed_envelope",
        "unsupported_version",
        "invalid_lifetime",
        "invalid_seal",
        "boundary_mismatch",
        "subject_mismatch",
        "guild_scope_mismatch",
        "channel_scope_mismatch",
        "thread_scope_mismatch",
        "event_mismatch",
        "body_mismatch",
        "not_yet_valid",
        "expired",
        "unknown_envelope",
        "replay",
    }
)

_BOUNDARY_DOMAIN = b"alpecca.bridge-actor.boundary.v2"
_SUBJECT_DOMAIN = b"alpecca.bridge-actor.subject.v2"
_GUILD_DOMAIN = b"alpecca.bridge-actor.guild.v2"
_CHANNEL_DOMAIN = b"alpecca.bridge-actor.channel.v2"
_THREAD_DOMAIN = b"alpecca.bridge-actor.thread.v2"
_EVENT_DOMAIN = b"alpecca.bridge-actor.discord-event.v2"
_BODY_DOMAIN = b"alpecca.bridge-actor.request-body.v2"
_NONCE_DOMAIN = b"alpecca.bridge-actor.nonce.v2"
_ENVELOPE_ID_DOMAIN = b"alpecca.bridge-actor.envelope-id.v2"
_ENVELOPE_SEAL_DOMAIN = b"alpecca.bridge-actor.envelope-seal.v2"
_CANDIDATE_DOMAIN = b"alpecca.bridge-actor.candidate.v2"
_EVIDENCE_ID_DOMAIN = b"alpecca.bridge-actor.evidence-id.v2"
_EVIDENCE_SEAL_DOMAIN = b"alpecca.bridge-actor.evidence-seal.v2"
_GENESIS_DOMAIN = b"alpecca.bridge-actor.audit-genesis.v2"
_AUDIT_RECORD_DOMAIN = b"alpecca.bridge-actor.audit-record.v2"
_AUDIT_CHAIN_DOMAIN = b"alpecca.bridge-actor.audit-chain.v2"
_AUDIT_SEAL_DOMAIN = b"alpecca.bridge-actor.audit-seal.v2"
_STATE_SEAL_DOMAIN = b"alpecca.bridge-actor.state-seal.v2"
_ANCHOR_NAMESPACE_DOMAIN = b"alpecca.bridge-actor.anchor-namespace.v2"

_STATE_TABLE = "bridge_actor_identity_state"
_ENVELOPE_TABLE = "bridge_actor_identity_envelopes"
_EVIDENCE_TABLE = "bridge_actor_identity_evidence"
_AUDIT_TABLE = "bridge_actor_identity_audit"

_MAIN_SCHEMA_MANIFEST: Mapping[str, tuple[str, str, str]] = {
    "bridge_actor_identity_state": (
        "table", "bridge_actor_identity_state",
        "ea86624314f88413024e76cd3e286f3541d4b88776396b39cec577b7bf024987",
    ),
    "bridge_actor_identity_envelopes": (
        "table", "bridge_actor_identity_envelopes",
        "e0b1fb8494dd40ea484d4f541790db57d224a39097ada3a369bcaa978090b556",
    ),
    "bridge_actor_identity_evidence": (
        "table", "bridge_actor_identity_evidence",
        "70bab47e22e6bb0209d8c3fbbc519fa560ff8e59548ffe29459bfcb1f5d174b6",
    ),
    "bridge_actor_identity_audit": (
        "table", "bridge_actor_identity_audit",
        "8af4a1644b1a937ba2c48a6d9832086788912a6aea00db507c6daec2f0c4355c",
    ),
    "bridge_actor_v2_envelope_expiry_idx": (
        "index", "bridge_actor_identity_envelopes",
        "3cc5102055e2bf4e44a607452fbc107895260bff351b878fd8a27484a4cf5923",
    ),
    "bridge_actor_v2_evidence_time_idx": (
        "index", "bridge_actor_identity_evidence",
        "b5821bc0a7851afa25ca332ab6135ab0d8b9a86aeda92f4c4db6ee4fa2a29b6e",
    ),
    "bridge_actor_v2_one_accept_idx": (
        "index", "bridge_actor_identity_evidence",
        "20c43e57c58862d87361e80f608b996d53ebf6c23d2d7e0f5891afe8c1cee7f7",
    ),
    "bridge_actor_v2_state_identity_immutable": (
        "trigger", "bridge_actor_identity_state",
        "f28c5567afc3fb5af5d5eb52af2e4bc6d61d0b1abd6775f3d30e16249f0b1a5b",
    ),
    "bridge_actor_v2_state_monotonic": (
        "trigger", "bridge_actor_identity_state",
        "e6cd597ac4584c253e13d8911981e3aee1e5ca79cadf029d48a6d46949471856",
    ),
    "bridge_actor_v2_state_no_delete": (
        "trigger", "bridge_actor_identity_state",
        "4595d767802ffab8c5cea124fcb092ee9dff1b61feb4592a06d07ffcf9f4504e",
    ),
    "bridge_actor_v2_envelope_immutable": (
        "trigger", "bridge_actor_identity_envelopes",
        "19bbc191bf393658859fa70c0e760294201aae1c0830e25808b0320893d136db",
    ),
    "bridge_actor_v2_nonce_once": (
        "trigger", "bridge_actor_identity_envelopes",
        "45cb211cd1c5e1c38a4f7292877e7bf5cc3fcb0abd43b01a6b16f06305298441",
    ),
    "bridge_actor_v2_envelope_no_delete": (
        "trigger", "bridge_actor_identity_envelopes",
        "4a339806967b81a8ccee16ddaf8f784d3467ac94bdd66dfcbb93259c456f77b0",
    ),
    "bridge_actor_v2_evidence_no_update": (
        "trigger", "bridge_actor_identity_evidence",
        "c5a8b0dcb98894975c88a8e196d3b44e2e1b759ca9f35c77e64ceb761d460f4c",
    ),
    "bridge_actor_v2_evidence_no_delete": (
        "trigger", "bridge_actor_identity_evidence",
        "a648d341d05bad185a33ce55583ecb223fcb7104c035c56f8ea046d1316d02b4",
    ),
    "bridge_actor_v2_audit_no_update": (
        "trigger", "bridge_actor_identity_audit",
        "f13f07d9d5894e6dc2632d36202a7893366399d16dee6e0a8f6ccb88855f61b8",
    ),
    "bridge_actor_v2_audit_no_delete": (
        "trigger", "bridge_actor_identity_audit",
        "bd775e5073f89cc6f175a4336a248c1e427a212f10582f9f054b0f5a126601c8",
    ),
}

_ANCHOR_SCHEMA_MANIFEST: Mapping[str, tuple[str, str, str]] = {
    "bridge_actor_monotonic_anchor": (
        "table", "bridge_actor_monotonic_anchor",
        "d3075618decd2ce32d455f250a5807652770b9a6760cdf6fcd304633d20db8b7",
    ),
    "bridge_actor_anchor_monotonic": (
        "trigger", "bridge_actor_monotonic_anchor",
        "98633f6c798343c3a0089ba80f2c216041943da6cbb15d080d949510eb301668",
    ),
    "bridge_actor_anchor_no_delete": (
        "trigger", "bridge_actor_monotonic_anchor",
        "4bb543be3b6a818f91dfc2c241661a122a00d131b4cee275996124686bed579e",
    ),
}

_ENVELOPE_FIELDS = frozenset(
    {
        "envelope_version",
        "schema_version",
        "policy_version",
        "key_version",
        "service",
        "platform",
        "boundary_hmac",
        "actor_subject_hmac",
        "guild_scope_hmac",
        "channel_scope_hmac",
        "thread_scope_hmac",
        "event_id_hmac",
        "body_hmac",
        "nonce_hmac",
        "issued_at_ms",
        "expires_at_ms",
        "envelope_id",
        "seal",
    }
)


class BridgeActorIdentityError(ValueError):
    """Invalid construction or caller input."""


class BridgeActorIntegrityError(RuntimeError):
    """Persisted or transported sealed state failed verification."""


class BridgeActorSchemaError(BridgeActorIntegrityError):
    """A required SQLite object is missing or differs from its canonical form."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason.replace("_", " "))


class BridgeActorEventReplayError(BridgeActorIdentityError):
    """The trusted adapter attempted to issue the same Discord event twice."""


class BridgeActorClockError(BridgeActorIdentityError):
    """The injected trusted clock cannot safely advance stored time."""


class BridgeActorClockRollbackError(BridgeActorClockError):
    """The trusted clock moved behind its sealed high-water mark."""


class BridgeActorFutureClockError(BridgeActorClockError):
    """The trusted clock jumped farther than the explicit policy permits."""


class BridgeActorNotReadyError(BridgeActorIntegrityError):
    """The external anchor has not passed the recovery gate."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason.replace("_", " "))


class BridgeActorQuarantinedError(BridgeActorIntegrityError):
    """The store detected rollback, truncation, or sealed-state corruption."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason.replace("_", " "))


def _schema_fingerprint(sql: object) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise BridgeActorSchemaError("schema_definition_mismatch")
    normalized = re.sub(r"\bIF\s+NOT\s+EXISTS\b", "", sql, flags=re.IGNORECASE)
    normalized = " ".join(normalized.strip().rstrip(";").split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _verify_schema_manifest(
    conn: sqlite3.Connection,
    manifest: Mapping[str, tuple[str, str, str]],
    *,
    allow_missing: bool,
) -> None:
    names = tuple(manifest)
    placeholders = ",".join("?" for _name in names)
    rows = conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        f"WHERE name IN ({placeholders})",
        names,
    ).fetchall()
    found = {str(row["name"]): row for row in rows}
    for name, (expected_type, expected_table, expected_fingerprint) in manifest.items():
        row = found.get(name)
        if row is None:
            if allow_missing:
                continue
            raise BridgeActorSchemaError("schema_object_missing")
        if (
            str(row["type"]) != expected_type
            or str(row["tbl_name"]) != expected_table
            or _schema_fingerprint(row["sql"]) != expected_fingerprint
        ):
            raise BridgeActorSchemaError("schema_definition_mismatch")


def _schema_manifest_has_objects(
    conn: sqlite3.Connection,
    manifest: Mapping[str, tuple[str, str, str]],
) -> bool:
    names = tuple(manifest)
    placeholders = ",".join("?" for _name in names)
    row = conn.execute(
        "SELECT 1 FROM sqlite_master "
        f"WHERE name IN ({placeholders}) LIMIT 1",
        names,
    ).fetchone()
    return row is not None


@dataclass(frozen=True, slots=True)
class BridgeActorPolicy:
    """Explicit bounded policy signed into every envelope and decision."""

    version: int
    envelope_ttl_ms: int = 30_000
    max_body_bytes: int = 1_048_576
    max_external_id_bytes: int = 256
    max_transport_bytes: int = 4096
    max_clock_advance_ms: int = 2_592_000_000
    max_incremental_audit_rows: int = 64

    def __post_init__(self) -> None:
        if self.version != SUPPORTED_POLICY_VERSION:
            raise BridgeActorIdentityError("unsupported bridge actor policy version")
        limits = (
            (self.envelope_ttl_ms, 1, 120_000, "envelope ttl"),
            (self.max_body_bytes, 1, 6 * 1024 * 1024, "body byte limit"),
            (self.max_external_id_bytes, 1, 1024, "external id byte limit"),
            (self.max_transport_bytes, 512, 16_384, "transport byte limit"),
            (self.max_clock_advance_ms, 1, 31_536_000_000, "clock advance limit"),
            (
                self.max_incremental_audit_rows,
                1,
                4096,
                "incremental audit limit",
            ),
        )
        for value, minimum, maximum, name in limits:
            if isinstance(value, bool) or not isinstance(value, int):
                raise BridgeActorIdentityError(f"{name} must be an integer")
            if value < minimum or value > maximum:
                raise BridgeActorIdentityError(f"{name} is out of range")


@dataclass(frozen=True, slots=True)
class TrustedBridgeBoundary:
    """Server-owned bridge capability established after service auth."""

    service: str
    platform: str
    boundary_id: str

    def __post_init__(self) -> None:
        _public_label(self.service, "service")
        _public_label(self.platform, "platform")
        _public_label(self.boundary_id, "boundary id")


class TrustedClock(Protocol):
    def now_ms(self) -> int:
        """Return trusted Unix wall time in integer milliseconds."""


class SystemTrustedClock:
    """Production wall clock implementation for explicit injection."""

    __slots__ = ()

    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000


@dataclass(frozen=True, slots=True)
class AnchorState:
    revision: int
    chain_head: str

    def __post_init__(self) -> None:
        _nonnegative_int(self.revision, "anchor revision")
        _hmac_value(self.chain_head, "anchor chain head")


class MonotonicAnchor(Protocol):
    """External rollback anchor. Implementations must provide atomic CAS."""

    def read(self, namespace: str) -> AnchorState | None:
        ...

    def compare_and_swap(
        self,
        namespace: str,
        expected: AnchorState | None,
        replacement: AnchorState,
    ) -> bool:
        ...


class SQLiteMonotonicAnchor:
    """Multi-process-safe external anchor in a separate SQLite database."""

    __slots__ = ("_db_path",)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("SQLite monotonic anchor dependencies are immutable")

    def __init__(self, db_path: str | Path) -> None:
        object.__setattr__(self, "_db_path", Path(db_path))
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect(self._db_path) as conn:
            existing_schema = _schema_manifest_has_objects(
                conn, _ANCHOR_SCHEMA_MANIFEST
            )
            _verify_schema_manifest(
                conn,
                _ANCHOR_SCHEMA_MANIFEST,
                allow_missing=not existing_schema,
            )
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bridge_actor_monotonic_anchor (
                    namespace   TEXT PRIMARY KEY,
                    revision    INTEGER NOT NULL CHECK(revision>=0),
                    chain_head  TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS bridge_actor_anchor_monotonic
                BEFORE UPDATE ON bridge_actor_monotonic_anchor
                WHEN NEW.revision <= OLD.revision
                BEGIN
                    SELECT RAISE(ABORT, 'bridge actor anchor must advance');
                END;
                CREATE TRIGGER IF NOT EXISTS bridge_actor_anchor_no_delete
                BEFORE DELETE ON bridge_actor_monotonic_anchor
                BEGIN
                    SELECT RAISE(ABORT, 'bridge actor anchor is monotonic');
                END;
                """
            )
            _verify_schema_manifest(
                conn, _ANCHOR_SCHEMA_MANIFEST, allow_missing=False
            )

    @property
    def db_path(self) -> Path:
        return self._db_path

    def read(self, namespace: str) -> AnchorState | None:
        key = _hmac_value(namespace, "anchor namespace")
        with connect(self._db_path) as conn:
            _verify_schema_manifest(
                conn, _ANCHOR_SCHEMA_MANIFEST, allow_missing=False
            )
            row = conn.execute(
                "SELECT revision,chain_head FROM bridge_actor_monotonic_anchor "
                "WHERE namespace=?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return AnchorState(
            revision=_nonnegative_int(row["revision"], "anchor revision"),
            chain_head=_hmac_value(row["chain_head"], "anchor chain head"),
        )

    def compare_and_swap(
        self,
        namespace: str,
        expected: AnchorState | None,
        replacement: AnchorState,
    ) -> bool:
        key = _hmac_value(namespace, "anchor namespace")
        if not isinstance(replacement, AnchorState):
            raise TypeError("replacement must be AnchorState")
        with connect(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            _verify_schema_manifest(
                conn, _ANCHOR_SCHEMA_MANIFEST, allow_missing=False
            )
            row = conn.execute(
                "SELECT revision,chain_head FROM bridge_actor_monotonic_anchor "
                "WHERE namespace=?",
                (key,),
            ).fetchone()
            if expected is None:
                if row is not None:
                    return False
                conn.execute(
                    "INSERT INTO bridge_actor_monotonic_anchor "
                    "(namespace,revision,chain_head) VALUES (?,?,?)",
                    (key, replacement.revision, replacement.chain_head),
                )
                return True
            if row is None:
                return False
            current = AnchorState(int(row["revision"]), str(row["chain_head"]))
            if current != expected or replacement.revision <= current.revision:
                return False
            updated = conn.execute(
                "UPDATE bridge_actor_monotonic_anchor "
                "SET revision=?,chain_head=? "
                "WHERE namespace=? AND revision=? AND chain_head=?",
                (
                    replacement.revision,
                    replacement.chain_head,
                    key,
                    current.revision,
                    current.chain_head,
                ),
            )
            return updated.rowcount == 1


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
        raise BridgeActorIdentityError("bridge actor material is not canonical JSON") from exc


def _public_label(value: object, name: str) -> str:
    if not isinstance(value, str) or _LABEL_RE.fullmatch(value) is None:
        raise BridgeActorIdentityError(f"{name} must be a bounded public label")
    return value


def _hmac_value(value: object, name: str) -> str:
    if not isinstance(value, str) or _HMAC_RE.fullmatch(value) is None:
        raise BridgeActorIdentityError(f"{name} must be a keyed HMAC")
    return value


def _nonnegative_int(value: object, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BridgeActorIdentityError(f"{name} must be an integer")
    minimum = 1 if positive else 0
    if value < minimum:
        raise BridgeActorIdentityError(f"{name} is out of range")
    return value


def _body_bytes(value: object, maximum: int) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise BridgeActorIdentityError("request_body must be bytes-like")
    body = bytes(value)
    if len(body) > maximum:
        raise BridgeActorIdentityError("request_body exceeds the bounded byte limit")
    return body


def _external_id(
    value: object,
    name: str,
    *,
    maximum: int,
    optional: bool,
) -> tuple[bool, str]:
    if value is None:
        if optional:
            return False, ""
        raise BridgeActorIdentityError(f"{name} is required")
    if isinstance(value, bool):
        raise BridgeActorIdentityError(f"{name} is invalid")
    if isinstance(value, int):
        if value < 0:
            raise BridgeActorIdentityError(f"{name} is invalid")
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise BridgeActorIdentityError(f"{name} is invalid")
    encoded = text.encode("utf-8")
    if (
        not encoded
        or len(encoded) > maximum
        or any(ord(char) < 32 or ord(char) == 127 for char in text)
    ):
        raise BridgeActorIdentityError(f"{name} is invalid")
    return True, text


def _without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class BridgeActorEnvelope:
    """Signed transport object containing only public labels and keyed HMACs."""

    envelope_version: int
    schema_version: int
    policy_version: int
    key_version: int
    service: str
    platform: str
    boundary_hmac: str
    actor_subject_hmac: str
    guild_scope_hmac: str
    channel_scope_hmac: str
    thread_scope_hmac: str
    event_id_hmac: str
    body_hmac: str
    nonce_hmac: str
    issued_at_ms: int
    expires_at_ms: int
    envelope_id: str
    seal: str

    def as_dict(self) -> dict[str, object]:
        return {
            "envelope_version": self.envelope_version,
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "key_version": self.key_version,
            "service": self.service,
            "platform": self.platform,
            "boundary_hmac": self.boundary_hmac,
            "actor_subject_hmac": self.actor_subject_hmac,
            "guild_scope_hmac": self.guild_scope_hmac,
            "channel_scope_hmac": self.channel_scope_hmac,
            "thread_scope_hmac": self.thread_scope_hmac,
            "event_id_hmac": self.event_id_hmac,
            "body_hmac": self.body_hmac,
            "nonce_hmac": self.nonce_hmac,
            "issued_at_ms": self.issued_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "envelope_id": self.envelope_id,
            "seal": self.seal,
        }

    def encode(self) -> str:
        return _canonical(self.as_dict())


_FACTORY = object()


@dataclass(frozen=True, slots=True, init=False)
class VerifiedGuestActor:
    """Factory-only authority result with no principal input or writable role."""

    envelope_version: int
    schema_version: int
    policy_version: int
    key_version: int
    service: str
    platform: str
    boundary_hmac: str
    actor_subject_hmac: str
    guild_scope_hmac: str
    channel_scope_hmac: str
    thread_scope_hmac: str
    event_id_hmac: str
    body_hmac: str
    envelope_id: str
    expires_at_ms: int

    def __init__(self, *, _factory: object, **values: object) -> None:
        if _factory is not _FACTORY:
            raise TypeError("VerifiedGuestActor is verifier-created only")
        for field in self.__dataclass_fields__:
            object.__setattr__(self, field, values[field])

    @property
    def authority(self) -> str:
        return "guest"

    def as_dict(self) -> dict[str, object]:
        return {
            "authority": "guest",
            **{field: getattr(self, field) for field in self.__dataclass_fields__},
        }


@dataclass(frozen=True, slots=True, init=False)
class ActorDecisionEvidence:
    """Factory-only immutable HMAC-sealed accept/deny evidence."""

    evidence_id: str
    evidence_version: int
    schema_version: int
    policy_version: int
    key_version: int
    decision: str
    reason: str
    service: str
    platform: str
    boundary_hmac: str
    envelope_id: str
    actor_subject_hmac: str
    guild_scope_hmac: str
    channel_scope_hmac: str
    thread_scope_hmac: str
    event_id_hmac: str
    body_hmac: str
    expires_at_ms: int
    occurred_at_ms: int
    seal: str

    def __init__(self, *, _factory: object, **values: object) -> None:
        if _factory is not _FACTORY:
            raise TypeError("ActorDecisionEvidence is store-created only")
        for field in self.__dataclass_fields__:
            object.__setattr__(self, field, values[field])

    @property
    def authority(self) -> str:
        return "guest"

    def as_dict(self) -> dict[str, object]:
        return {
            "authority": "guest",
            **{field: getattr(self, field) for field in self.__dataclass_fields__},
        }


def _assert_result_structure(
    actor: VerifiedGuestActor | None,
    evidence: ActorDecisionEvidence,
) -> None:
    if type(evidence) is not ActorDecisionEvidence:
        raise BridgeActorIntegrityError("verification evidence is not factory-created")
    accepted = evidence.decision == "accept"
    if accepted != (evidence.reason == "accepted"):
        raise BridgeActorIntegrityError("verification decision and reason conflict")
    if accepted:
        if type(actor) is not VerifiedGuestActor:
            raise BridgeActorIntegrityError("accepted verification lacks a verified guest")
        if actor.authority != "guest" or evidence.authority != "guest":
            raise BridgeActorIntegrityError("verification authority is not guest-only")
        pairs = (
            (actor.envelope_version, ENVELOPE_VERSION),
            (actor.schema_version, evidence.schema_version),
            (actor.policy_version, evidence.policy_version),
            (actor.key_version, evidence.key_version),
            (actor.service, evidence.service),
            (actor.platform, evidence.platform),
            (actor.boundary_hmac, evidence.boundary_hmac),
            (actor.envelope_id, evidence.envelope_id),
            (actor.actor_subject_hmac, evidence.actor_subject_hmac),
            (actor.guild_scope_hmac, evidence.guild_scope_hmac),
            (actor.channel_scope_hmac, evidence.channel_scope_hmac),
            (actor.thread_scope_hmac, evidence.thread_scope_hmac),
            (actor.event_id_hmac, evidence.event_id_hmac),
            (actor.body_hmac, evidence.body_hmac),
            (actor.expires_at_ms, evidence.expires_at_ms),
        )
        if any(left != right for left, right in pairs):
            raise BridgeActorIntegrityError("verified guest and evidence conflict")
    elif actor is not None:
        raise BridgeActorIntegrityError("denied verification exposed actor authority")


@dataclass(frozen=True, slots=True, init=False)
class BridgeActorVerification:
    """Factory-only result whose acceptance is derived, never caller supplied."""

    _actor: VerifiedGuestActor | None
    _evidence: ActorDecisionEvidence

    def __init__(
        self,
        *,
        _factory: object,
        actor: VerifiedGuestActor | None,
        evidence: ActorDecisionEvidence,
    ) -> None:
        if _factory is not _FACTORY:
            raise TypeError("BridgeActorVerification is store-created only")
        _assert_result_structure(actor, evidence)
        object.__setattr__(self, "_actor", actor)
        object.__setattr__(self, "_evidence", evidence)

    @property
    def accepted(self) -> bool:
        _assert_result_structure(self._actor, self._evidence)
        return self._evidence.decision == "accept"

    @property
    def actor(self) -> VerifiedGuestActor | None:
        _assert_result_structure(self._actor, self._evidence)
        return self._actor

    @property
    def evidence(self) -> ActorDecisionEvidence:
        _assert_result_structure(self._actor, self._evidence)
        return self._evidence

    def as_dict(self) -> dict[str, object]:
        _assert_result_structure(self._actor, self._evidence)
        return {
            "accepted": self.accepted,
            "actor": None if self._actor is None else self._actor.as_dict(),
            "evidence": self._evidence.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class AuditReport:
    ok: bool
    reason: str
    schema_version: int
    policy_version: int
    key_version: int
    revision: int
    rows_verified: int
    anchor_revision: int | None
    ready: bool
    quarantined: bool


@dataclass(frozen=True, slots=True)
class _Bindings:
    actor_subject_hmac: str
    guild_scope_hmac: str
    channel_scope_hmac: str
    thread_scope_hmac: str
    event_id_hmac: str
    body_hmac: str


@dataclass(frozen=True, slots=True)
class _StoreState:
    schema_version: int
    policy_version: int
    key_version: int
    service: str
    platform: str
    boundary_hmac: str
    revision: int
    chain_head: str
    envelope_count: int
    evidence_count: int
    consumed_count: int
    high_water_ms: int
    state_seal: str


@dataclass(frozen=True, slots=True)
class _AuditRow:
    revision: int
    previous_head: str
    operation: str
    object_id: str
    envelope_id: str
    record_hmac: str
    occurred_at_ms: int
    chain_head: str
    audit_seal: str


def _parse_envelope(
    value: BridgeActorEnvelope | Mapping[str, object] | str,
    *,
    max_transport_bytes: int,
) -> BridgeActorEnvelope:
    if isinstance(value, BridgeActorEnvelope):
        data = value.as_dict()
    elif isinstance(value, str):
        if len(value.encode("utf-8")) > max_transport_bytes:
            raise BridgeActorIdentityError("actor envelope is malformed")
        try:
            parsed = json.loads(value, object_pairs_hook=_without_duplicate_keys)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise BridgeActorIdentityError("actor envelope is malformed") from exc
        if not isinstance(parsed, dict):
            raise BridgeActorIdentityError("actor envelope is malformed")
        data = parsed
    elif isinstance(value, Mapping):
        try:
            data = dict(value)
        except (TypeError, ValueError) as exc:
            raise BridgeActorIdentityError("actor envelope is malformed") from exc
        if len(_canonical(data).encode("utf-8")) > max_transport_bytes:
            raise BridgeActorIdentityError("actor envelope is malformed")
    else:
        raise BridgeActorIdentityError("actor envelope is malformed")
    if set(data) != _ENVELOPE_FIELDS:
        raise BridgeActorIdentityError("actor envelope is malformed")
    try:
        return BridgeActorEnvelope(
            envelope_version=_nonnegative_int(
                data["envelope_version"], "envelope version", positive=True
            ),
            schema_version=_nonnegative_int(
                data["schema_version"], "schema version", positive=True
            ),
            policy_version=_nonnegative_int(
                data["policy_version"], "policy version", positive=True
            ),
            key_version=_nonnegative_int(data["key_version"], "key version", positive=True),
            service=_public_label(data["service"], "service"),
            platform=_public_label(data["platform"], "platform"),
            boundary_hmac=_hmac_value(data["boundary_hmac"], "boundary HMAC"),
            actor_subject_hmac=_hmac_value(
                data["actor_subject_hmac"], "actor subject HMAC"
            ),
            guild_scope_hmac=_hmac_value(data["guild_scope_hmac"], "guild HMAC"),
            channel_scope_hmac=_hmac_value(
                data["channel_scope_hmac"], "channel HMAC"
            ),
            thread_scope_hmac=_hmac_value(data["thread_scope_hmac"], "thread HMAC"),
            event_id_hmac=_hmac_value(data["event_id_hmac"], "event HMAC"),
            body_hmac=_hmac_value(data["body_hmac"], "body HMAC"),
            nonce_hmac=_hmac_value(data["nonce_hmac"], "nonce HMAC"),
            issued_at_ms=_nonnegative_int(data["issued_at_ms"], "issued timestamp"),
            expires_at_ms=_nonnegative_int(
                data["expires_at_ms"], "expiry timestamp", positive=True
            ),
            envelope_id=_hmac_value(data["envelope_id"], "envelope id"),
            seal=_hmac_value(data["seal"], "envelope seal"),
        )
    except (KeyError, TypeError, ValueError, BridgeActorIdentityError) as exc:
        raise BridgeActorIdentityError("actor envelope is malformed") from exc


class BridgeActorIdentityStore:
    """Constructor-bound issuer/verifier with durable rollback detection."""

    __slots__ = (
        "_db_path",
        "_key",
        "_key_version",
        "_policy",
        "_boundary",
        "_clock_ref",
        "_anchor_ref",
        "_schema_lock",
        "_schema_ready",
        "_status_lock",
        "_ready",
        "_quarantined",
        "_status_reason",
        "_boundary_hmac",
        "_genesis_head",
        "_anchor_namespace",
        "_dependencies_frozen",
    )
    _FROZEN_DEPENDENCY_SLOTS = frozenset(
        {
            "_db_path",
            "_key",
            "_key_version",
            "_policy",
            "_boundary",
            "_clock_ref",
            "_anchor_ref",
            "_boundary_hmac",
            "_genesis_head",
            "_anchor_namespace",
            "_dependencies_frozen",
        }
    )
    guild_participation_enabled = False
    voice_enabled = False

    def __setattr__(self, name: str, value: object) -> None:
        if (
            name in self._FROZEN_DEPENDENCY_SLOTS
            and getattr(self, "_dependencies_frozen", False)
        ):
            raise AttributeError("bridge actor constructor dependencies are immutable")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        db_path: str | Path,
        *,
        seal_key: bytes | bytearray | memoryview,
        key_version: int,
        policy: BridgeActorPolicy,
        boundary: TrustedBridgeBoundary,
        clock: TrustedClock,
        monotonic_anchor: MonotonicAnchor,
    ) -> None:
        object.__setattr__(self, "_dependencies_frozen", False)
        self._db_path = Path(db_path)
        if not isinstance(seal_key, (bytes, bytearray, memoryview)):
            raise TypeError("seal_key must be bytes-like key material")
        key = bytes(seal_key)
        if len(key) < MIN_KEY_BYTES:
            raise ValueError("seal_key must contain at least 32 bytes")
        self._key = key
        self._key_version = _nonnegative_int(key_version, "key version", positive=True)
        if type(policy) is not BridgeActorPolicy:
            raise TypeError("policy must be BridgeActorPolicy")
        if type(boundary) is not TrustedBridgeBoundary:
            raise TypeError("boundary must be TrustedBridgeBoundary")
        if not callable(getattr(clock, "now_ms", None)):
            raise TypeError("clock must provide now_ms()")
        if not callable(getattr(monotonic_anchor, "read", None)) or not callable(
            getattr(monotonic_anchor, "compare_and_swap", None)
        ):
            raise TypeError("monotonic_anchor must provide read() and compare_and_swap()")
        self._policy = BridgeActorPolicy(
            version=policy.version,
            envelope_ttl_ms=policy.envelope_ttl_ms,
            max_body_bytes=policy.max_body_bytes,
            max_external_id_bytes=policy.max_external_id_bytes,
            max_transport_bytes=policy.max_transport_bytes,
            max_clock_advance_ms=policy.max_clock_advance_ms,
            max_incremental_audit_rows=policy.max_incremental_audit_rows,
        )
        self._boundary = TrustedBridgeBoundary(
            service=boundary.service,
            platform=boundary.platform,
            boundary_id=boundary.boundary_id,
        )
        self._clock_ref = clock
        self._anchor_ref = monotonic_anchor
        if isinstance(monotonic_anchor, SQLiteMonotonicAnchor):
            if monotonic_anchor.db_path.resolve() == self._db_path.resolve():
                raise ValueError("monotonic anchor must be external to the actor database")
        self._schema_lock = threading.Lock()
        self._schema_ready = False
        self._status_lock = threading.Lock()
        self._ready = False
        self._quarantined = False
        self._status_reason = "initializing"
        self._boundary_hmac = self._hmac(
            _BOUNDARY_DOMAIN,
            {
                "service": self._boundary.service,
                "platform": self._boundary.platform,
                "boundary_id": self._boundary.boundary_id,
                "schema_version": SCHEMA_VERSION,
                "policy_version": self._policy.version,
                "key_version": self._key_version,
            },
        )
        self._genesis_head = self._hmac(
            _GENESIS_DOMAIN,
            {
                "schema_version": SCHEMA_VERSION,
                "policy_version": self._policy.version,
                "key_version": self._key_version,
                "service": self._boundary.service,
                "platform": self._boundary.platform,
                "boundary_hmac": self._boundary_hmac,
            },
        )
        self._anchor_namespace = self._hmac(
            _ANCHOR_NAMESPACE_DOMAIN,
            {
                "schema_version": SCHEMA_VERSION,
                "policy_version": self._policy.version,
                "key_version": self._key_version,
                "service": self._boundary.service,
                "platform": self._boundary.platform,
                "boundary_hmac": self._boundary_hmac,
            },
        )
        object.__setattr__(self, "_dependencies_frozen", True)
        try:
            self._ensure_schema()
        except BridgeActorSchemaError as exc:
            self._set_quarantined(exc.reason)
            return
        self._automatic_recovery_gate()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def key_version(self) -> int:
        return self._key_version

    @property
    def policy(self) -> BridgeActorPolicy:
        policy = self._policy
        return BridgeActorPolicy(
            version=policy.version,
            envelope_ttl_ms=policy.envelope_ttl_ms,
            max_body_bytes=policy.max_body_bytes,
            max_external_id_bytes=policy.max_external_id_bytes,
            max_transport_bytes=policy.max_transport_bytes,
            max_clock_advance_ms=policy.max_clock_advance_ms,
            max_incremental_audit_rows=policy.max_incremental_audit_rows,
        )

    @property
    def boundary(self) -> TrustedBridgeBoundary:
        boundary = self._boundary
        return TrustedBridgeBoundary(
            service=boundary.service,
            platform=boundary.platform,
            boundary_id=boundary.boundary_id,
        )

    @property
    def clock(self) -> TrustedClock:
        return self._clock_ref

    @property
    def monotonic_anchor(self) -> MonotonicAnchor:
        return self._anchor_ref

    @property
    def ready(self) -> bool:
        with self._status_lock:
            return self._ready

    @property
    def quarantined(self) -> bool:
        with self._status_lock:
            return self._quarantined

    @property
    def status_reason(self) -> str:
        with self._status_lock:
            return self._status_reason

    def _set_ready(self) -> None:
        with self._status_lock:
            if not self._quarantined:
                self._ready = True
                self._status_reason = "ready"

    def _set_not_ready(self, reason: str) -> None:
        with self._status_lock:
            if not self._quarantined:
                self._ready = False
                self._status_reason = reason

    def _set_quarantined(self, reason: str) -> None:
        with self._status_lock:
            self._ready = False
            self._quarantined = True
            self._status_reason = reason

    def _hmac_bytes(self, domain: bytes, payload: bytes) -> str:
        prefix = domain + b"\x00" + str(self._key_version).encode("ascii") + b"\x00"
        return hmac.new(self._key, prefix + payload, hashlib.sha256).hexdigest()

    def _hmac(self, domain: bytes, value: object) -> str:
        return self._hmac_bytes(domain, _canonical(value).encode("utf-8"))

    def _clock_now(self) -> int:
        try:
            value = self._clock_ref.now_ms()
        except Exception as exc:
            raise BridgeActorClockError("trusted clock unavailable") from exc
        milliseconds = _nonnegative_int(value, "trusted clock timestamp")
        if milliseconds > 9_223_372_036_854_775_807:
            raise BridgeActorClockError("trusted clock timestamp is out of range")
        return milliseconds

    def _ensure_schema(self) -> None:
        with self._schema_lock:
            if self._schema_ready:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with connect(self._db_path) as conn:
                existing_schema = _schema_manifest_has_objects(
                    conn, _MAIN_SCHEMA_MANIFEST
                )
                _verify_schema_manifest(
                    conn,
                    _MAIN_SCHEMA_MANIFEST,
                    allow_missing=not existing_schema,
                )
                conn.executescript(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_STATE_TABLE} (
                        singleton          INTEGER PRIMARY KEY CHECK(singleton=1),
                        schema_version     INTEGER NOT NULL,
                        policy_version     INTEGER NOT NULL,
                        key_version        INTEGER NOT NULL,
                        service            TEXT NOT NULL,
                        platform           TEXT NOT NULL,
                        boundary_hmac      TEXT NOT NULL,
                        revision           INTEGER NOT NULL CHECK(revision>=0),
                        chain_head         TEXT NOT NULL,
                        envelope_count     INTEGER NOT NULL CHECK(envelope_count>=0),
                        evidence_count     INTEGER NOT NULL CHECK(evidence_count>=0),
                        consumed_count     INTEGER NOT NULL CHECK(consumed_count>=0),
                        high_water_ms      INTEGER NOT NULL CHECK(high_water_ms>=0),
                        state_seal         TEXT NOT NULL
                    );
                    CREATE TRIGGER IF NOT EXISTS bridge_actor_v2_state_identity_immutable
                    BEFORE UPDATE OF
                        schema_version,policy_version,key_version,service,platform,
                        boundary_hmac
                    ON {_STATE_TABLE}
                    BEGIN
                        SELECT RAISE(ABORT, 'bridge actor state identity is immutable');
                    END;
                    CREATE TRIGGER IF NOT EXISTS bridge_actor_v2_state_monotonic
                    BEFORE UPDATE ON {_STATE_TABLE}
                    WHEN NEW.revision != OLD.revision + 1
                        OR NEW.envelope_count < OLD.envelope_count
                        OR NEW.envelope_count > OLD.envelope_count + 1
                        OR NEW.evidence_count < OLD.evidence_count
                        OR NEW.evidence_count > OLD.evidence_count + 1
                        OR NEW.consumed_count < OLD.consumed_count
                        OR NEW.consumed_count > OLD.consumed_count + 1
                        OR NEW.high_water_ms < OLD.high_water_ms
                    BEGIN
                        SELECT RAISE(ABORT, 'bridge actor state must advance monotonically');
                    END;
                    CREATE TRIGGER IF NOT EXISTS bridge_actor_v2_state_no_delete
                    BEFORE DELETE ON {_STATE_TABLE}
                    BEGIN
                        SELECT RAISE(ABORT, 'bridge actor state is durable');
                    END;

                    CREATE TABLE IF NOT EXISTS {_ENVELOPE_TABLE} (
                        envelope_id         TEXT PRIMARY KEY,
                        envelope_version    INTEGER NOT NULL,
                        schema_version      INTEGER NOT NULL,
                        policy_version      INTEGER NOT NULL,
                        key_version         INTEGER NOT NULL,
                        service             TEXT NOT NULL,
                        platform            TEXT NOT NULL,
                        boundary_hmac       TEXT NOT NULL,
                        actor_subject_hmac  TEXT NOT NULL,
                        guild_scope_hmac    TEXT NOT NULL,
                        channel_scope_hmac  TEXT NOT NULL,
                        thread_scope_hmac   TEXT NOT NULL,
                        event_id_hmac       TEXT NOT NULL UNIQUE,
                        body_hmac           TEXT NOT NULL,
                        nonce_hmac          TEXT NOT NULL UNIQUE,
                        issued_at_ms        INTEGER NOT NULL,
                        expires_at_ms       INTEGER NOT NULL,
                        consumed_at_ms      INTEGER,
                        envelope_seal       TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS bridge_actor_v2_envelope_expiry_idx
                        ON {_ENVELOPE_TABLE}(expires_at_ms);
                    CREATE TRIGGER IF NOT EXISTS bridge_actor_v2_envelope_immutable
                    BEFORE UPDATE OF
                        envelope_id,envelope_version,schema_version,policy_version,
                        key_version,service,platform,boundary_hmac,
                        actor_subject_hmac,guild_scope_hmac,channel_scope_hmac,
                        thread_scope_hmac,event_id_hmac,body_hmac,nonce_hmac,
                        issued_at_ms,expires_at_ms,envelope_seal
                    ON {_ENVELOPE_TABLE}
                    BEGIN
                        SELECT RAISE(ABORT, 'bridge actor envelope is immutable');
                    END;
                    CREATE TRIGGER IF NOT EXISTS bridge_actor_v2_nonce_once
                    BEFORE UPDATE OF consumed_at_ms ON {_ENVELOPE_TABLE}
                    WHEN OLD.consumed_at_ms IS NOT NULL
                        OR NEW.consumed_at_ms IS NULL
                        OR NEW.consumed_at_ms < OLD.issued_at_ms
                    BEGIN
                        SELECT RAISE(ABORT, 'bridge actor nonce is single-use');
                    END;
                    CREATE TRIGGER IF NOT EXISTS bridge_actor_v2_envelope_no_delete
                    BEFORE DELETE ON {_ENVELOPE_TABLE}
                    BEGIN
                        SELECT RAISE(ABORT, 'bridge actor envelopes preserve replay state');
                    END;

                    CREATE TABLE IF NOT EXISTS {_EVIDENCE_TABLE} (
                        evidence_seq         INTEGER PRIMARY KEY AUTOINCREMENT,
                        evidence_id          TEXT NOT NULL UNIQUE,
                        evidence_version     INTEGER NOT NULL,
                        schema_version       INTEGER NOT NULL,
                        policy_version       INTEGER NOT NULL,
                        key_version          INTEGER NOT NULL,
                        decision             TEXT NOT NULL CHECK(decision IN ('accept','deny')),
                        reason               TEXT NOT NULL,
                        service              TEXT NOT NULL,
                        platform             TEXT NOT NULL,
                        boundary_hmac        TEXT NOT NULL,
                        envelope_id          TEXT NOT NULL,
                        actor_subject_hmac   TEXT NOT NULL,
                        guild_scope_hmac     TEXT NOT NULL,
                        channel_scope_hmac   TEXT NOT NULL,
                        thread_scope_hmac    TEXT NOT NULL,
                        event_id_hmac        TEXT NOT NULL,
                        body_hmac            TEXT NOT NULL,
                        expires_at_ms        INTEGER NOT NULL,
                        occurred_at_ms       INTEGER NOT NULL,
                        evidence_seal        TEXT NOT NULL
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS bridge_actor_v2_one_accept_idx
                        ON {_EVIDENCE_TABLE}(envelope_id)
                        WHERE decision='accept';
                    CREATE INDEX IF NOT EXISTS bridge_actor_v2_evidence_time_idx
                        ON {_EVIDENCE_TABLE}(evidence_seq DESC);
                    CREATE TRIGGER IF NOT EXISTS bridge_actor_v2_evidence_no_update
                    BEFORE UPDATE ON {_EVIDENCE_TABLE}
                    BEGIN
                        SELECT RAISE(ABORT, 'bridge actor evidence is immutable');
                    END;
                    CREATE TRIGGER IF NOT EXISTS bridge_actor_v2_evidence_no_delete
                    BEFORE DELETE ON {_EVIDENCE_TABLE}
                    BEGIN
                        SELECT RAISE(ABORT, 'bridge actor evidence is immutable');
                    END;

                    CREATE TABLE IF NOT EXISTS {_AUDIT_TABLE} (
                        revision             INTEGER PRIMARY KEY,
                        previous_head        TEXT NOT NULL,
                        operation            TEXT NOT NULL
                            CHECK(operation IN ('issue','accept','deny')),
                        object_id            TEXT NOT NULL,
                        envelope_id          TEXT NOT NULL,
                        record_hmac          TEXT NOT NULL,
                        occurred_at_ms       INTEGER NOT NULL,
                        chain_head           TEXT NOT NULL UNIQUE,
                        audit_seal           TEXT NOT NULL
                    );
                    CREATE TRIGGER IF NOT EXISTS bridge_actor_v2_audit_no_update
                    BEFORE UPDATE ON {_AUDIT_TABLE}
                    BEGIN
                        SELECT RAISE(ABORT, 'bridge actor audit is immutable');
                    END;
                    CREATE TRIGGER IF NOT EXISTS bridge_actor_v2_audit_no_delete
                    BEFORE DELETE ON {_AUDIT_TABLE}
                    BEGIN
                        SELECT RAISE(ABORT, 'bridge actor audit is immutable');
                    END;
                    """
                )
                _verify_schema_manifest(
                    conn, _MAIN_SCHEMA_MANIFEST, allow_missing=False
                )
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    f"SELECT singleton FROM {_STATE_TABLE} WHERE singleton=1"
                ).fetchone()
                if row is None:
                    initial = _StoreState(
                        schema_version=SCHEMA_VERSION,
                        policy_version=self._policy.version,
                        key_version=self._key_version,
                        service=self._boundary.service,
                        platform=self._boundary.platform,
                        boundary_hmac=self._boundary_hmac,
                        revision=0,
                        chain_head=self._genesis_head,
                        envelope_count=0,
                        evidence_count=0,
                        consumed_count=0,
                        high_water_ms=self._clock_now(),
                        state_seal="",
                    )
                    initial = self._with_state_seal(initial)
                    conn.execute(
                        f"""
                        INSERT INTO {_STATE_TABLE}
                            (singleton,schema_version,policy_version,key_version,
                             service,platform,boundary_hmac,revision,chain_head,
                             envelope_count,evidence_count,consumed_count,
                             high_water_ms,state_seal)
                        VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            initial.schema_version,
                            initial.policy_version,
                            initial.key_version,
                            initial.service,
                            initial.platform,
                            initial.boundary_hmac,
                            initial.revision,
                            initial.chain_head,
                            initial.envelope_count,
                            initial.evidence_count,
                            initial.consumed_count,
                            initial.high_water_ms,
                            initial.state_seal,
                        ),
                    )
            self._schema_ready = True

    def _state_material(self, state: _StoreState) -> dict[str, object]:
        return {
            "schema_version": state.schema_version,
            "policy_version": state.policy_version,
            "key_version": state.key_version,
            "service": state.service,
            "platform": state.platform,
            "boundary_hmac": state.boundary_hmac,
            "revision": state.revision,
            "chain_head": state.chain_head,
            "envelope_count": state.envelope_count,
            "evidence_count": state.evidence_count,
            "consumed_count": state.consumed_count,
            "high_water_ms": state.high_water_ms,
        }

    def _with_state_seal(self, state: _StoreState) -> _StoreState:
        return _StoreState(
            **{
                **self._state_material(state),
                "state_seal": self._hmac(_STATE_SEAL_DOMAIN, self._state_material(state)),
            }
        )

    def _read_state(self, conn: sqlite3.Connection) -> _StoreState:
        row = conn.execute(f"SELECT * FROM {_STATE_TABLE} WHERE singleton=1").fetchone()
        if row is None:
            raise BridgeActorIntegrityError("bridge actor state is missing")
        try:
            state = _StoreState(
                schema_version=int(row["schema_version"]),
                policy_version=int(row["policy_version"]),
                key_version=int(row["key_version"]),
                service=str(row["service"]),
                platform=str(row["platform"]),
                boundary_hmac=str(row["boundary_hmac"]),
                revision=int(row["revision"]),
                chain_head=str(row["chain_head"]),
                envelope_count=int(row["envelope_count"]),
                evidence_count=int(row["evidence_count"]),
                consumed_count=int(row["consumed_count"]),
                high_water_ms=int(row["high_water_ms"]),
                state_seal=str(row["state_seal"]),
            )
            _public_label(state.service, "stored service")
            _public_label(state.platform, "stored platform")
            _hmac_value(state.boundary_hmac, "stored boundary HMAC")
            _hmac_value(state.chain_head, "stored chain head")
            _hmac_value(state.state_seal, "stored state seal")
            for value, name in (
                (state.revision, "stored revision"),
                (state.envelope_count, "stored envelope count"),
                (state.evidence_count, "stored evidence count"),
                (state.consumed_count, "stored consumed count"),
                (state.high_water_ms, "stored clock high-water mark"),
            ):
                _nonnegative_int(value, name)
        except (KeyError, TypeError, ValueError, BridgeActorIdentityError) as exc:
            raise BridgeActorIntegrityError("bridge actor state is malformed") from exc
        expected_identity = (
            SCHEMA_VERSION,
            self._policy.version,
            self._key_version,
            self._boundary.service,
            self._boundary.platform,
            self._boundary_hmac,
        )
        actual_identity = (
            state.schema_version,
            state.policy_version,
            state.key_version,
            state.service,
            state.platform,
            state.boundary_hmac,
        )
        if actual_identity != expected_identity:
            raise BridgeActorIntegrityError("bridge actor state binding does not match")
        if (
            state.revision != state.envelope_count + state.evidence_count
            or state.consumed_count > state.envelope_count
            or (state.revision == 0 and state.chain_head != self._genesis_head)
        ):
            raise BridgeActorIntegrityError("bridge actor state counters are invalid")
        expected_seal = self._hmac(_STATE_SEAL_DOMAIN, self._state_material(state))
        if not hmac.compare_digest(expected_seal, state.state_seal):
            raise BridgeActorIntegrityError("bridge actor state seal does not verify")
        return state

    def _check_counts(self, conn: sqlite3.Connection, state: _StoreState) -> None:
        row = conn.execute(
            f"""
            SELECT
                (SELECT COUNT(*) FROM {_ENVELOPE_TABLE}) AS envelopes,
                (SELECT COUNT(*) FROM {_EVIDENCE_TABLE}) AS evidence,
                (SELECT COUNT(*) FROM {_AUDIT_TABLE}) AS audit_rows,
                (SELECT COUNT(*) FROM {_ENVELOPE_TABLE}
                  WHERE consumed_at_ms IS NOT NULL) AS consumed,
                (SELECT COUNT(*) FROM {_EVIDENCE_TABLE}
                  WHERE decision='accept') AS accepts,
                (SELECT COUNT(*) FROM {_ENVELOPE_TABLE} e
                  WHERE e.consumed_at_ms IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM {_EVIDENCE_TABLE} d
                         WHERE d.envelope_id=e.envelope_id AND d.decision='accept'
                    )) AS consumed_without_accept,
                (SELECT COUNT(*) FROM {_EVIDENCE_TABLE} d
                  WHERE d.decision='accept'
                    AND NOT EXISTS (
                        SELECT 1 FROM {_ENVELOPE_TABLE} e
                         WHERE e.envelope_id=d.envelope_id
                           AND e.consumed_at_ms IS NOT NULL
                    )) AS accept_without_consumed
            """
        ).fetchone()
        if row is None:
            raise BridgeActorIntegrityError("bridge actor count evidence is missing")
        actual = (
            int(row["envelopes"]),
            int(row["evidence"]),
            int(row["audit_rows"]),
            int(row["consumed"]),
            int(row["accepts"]),
        )
        expected = (
            state.envelope_count,
            state.evidence_count,
            state.revision,
            state.consumed_count,
            state.consumed_count,
        )
        if actual != expected or int(row["consumed_without_accept"]) or int(
            row["accept_without_consumed"]
        ):
            raise BridgeActorIntegrityError("bridge actor database was truncated or diverged")

    def _check_bounded_state(
        self,
        conn: sqlite3.Connection,
        state: _StoreState,
    ) -> None:
        latest = conn.execute(
            f"SELECT revision,chain_head FROM {_AUDIT_TABLE} "
            "ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        if state.revision == 0:
            if latest is not None:
                raise BridgeActorIntegrityError(
                    "bridge actor audit exists before the first revision"
                )
            return
        if (
            latest is None
            or int(latest["revision"]) != state.revision
            or not hmac.compare_digest(str(latest["chain_head"]), state.chain_head)
        ):
            raise BridgeActorIntegrityError(
                "bridge actor latest audit state does not match"
            )

    def _anchor_state(self, state: _StoreState) -> AnchorState:
        return AnchorState(state.revision, state.chain_head)

    def _read_anchor(self) -> AnchorState | None:
        try:
            value = self._anchor_ref.read(self._anchor_namespace)
        except BridgeActorSchemaError as exc:
            raise BridgeActorQuarantinedError(
                "anchor_schema_definition_mismatch"
            ) from exc
        except Exception as exc:
            raise BridgeActorNotReadyError("monotonic_anchor_unavailable") from exc
        if value is not None and not isinstance(value, AnchorState):
            raise BridgeActorNotReadyError("monotonic_anchor_invalid")
        return value

    def _anchor_cas(
        self,
        expected: AnchorState | None,
        replacement: AnchorState,
    ) -> bool:
        try:
            return bool(
                self._anchor_ref.compare_and_swap(
                    self._anchor_namespace, expected, replacement
                )
            )
        except BridgeActorSchemaError as exc:
            raise BridgeActorQuarantinedError(
                "anchor_schema_definition_mismatch"
            ) from exc
        except Exception as exc:
            raise BridgeActorNotReadyError("monotonic_anchor_unavailable") from exc

    def _automatic_recovery_gate(self) -> None:
        if self.quarantined:
            return
        try:
            with connect(self._db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                self._gate_locked(conn, verify_full_counts=True)
        except BridgeActorQuarantinedError as exc:
            self._set_quarantined(exc.reason)
            return
        except BridgeActorNotReadyError as exc:
            self._set_not_ready(exc.reason)
            return
        except BridgeActorIntegrityError:
            self._set_quarantined("sealed_state_integrity_failure")
            return
        self._set_ready()

    def _ensure_ready(self) -> None:
        if self.quarantined:
            raise BridgeActorQuarantinedError(self.status_reason)
        if not self.ready:
            self._automatic_recovery_gate()
        if self.quarantined:
            raise BridgeActorQuarantinedError(self.status_reason)
        if not self.ready:
            raise BridgeActorNotReadyError(self.status_reason)

    def _gate_locked(
        self,
        conn: sqlite3.Connection,
        *,
        verify_full_counts: bool = False,
    ) -> _StoreState:
        try:
            _verify_schema_manifest(
                conn, _MAIN_SCHEMA_MANIFEST, allow_missing=False
            )
        except BridgeActorSchemaError as exc:
            raise BridgeActorQuarantinedError(exc.reason) from exc
        state = self._read_state(conn)
        if verify_full_counts:
            self._check_counts(conn, state)
        else:
            self._check_bounded_state(conn, state)
        target = self._anchor_state(state)
        for _attempt in range(5):
            anchor = self._read_anchor()
            if anchor is None:
                if state.revision != 0:
                    raise BridgeActorQuarantinedError("monotonic_anchor_missing")
                if self._anchor_cas(None, target):
                    anchor = target
                else:
                    continue
            if anchor.revision > state.revision:
                raise BridgeActorQuarantinedError("database_snapshot_rollback")
            if anchor.revision == state.revision:
                if not hmac.compare_digest(anchor.chain_head, state.chain_head):
                    raise BridgeActorQuarantinedError("database_snapshot_divergence")
                self._verify_incremental_tail(conn, state)
                return state
            gap = state.revision - anchor.revision
            if gap > self._policy.max_incremental_audit_rows:
                raise BridgeActorNotReadyError("full_audit_required")
            self._verify_chain_range(
                conn,
                start_revision=anchor.revision + 1,
                end_revision=state.revision,
                expected_previous_head=anchor.chain_head,
                expected_final_head=state.chain_head,
            )
            if self._anchor_cas(anchor, target):
                return state
        raise BridgeActorNotReadyError("monotonic_anchor_race")

    def _verify_incremental_tail(
        self,
        conn: sqlite3.Connection,
        state: _StoreState,
    ) -> None:
        if state.revision == 0:
            return
        start = max(1, state.revision - self._policy.max_incremental_audit_rows + 1)
        first = conn.execute(
            f"SELECT previous_head FROM {_AUDIT_TABLE} WHERE revision=?",
            (start,),
        ).fetchone()
        if first is None:
            raise BridgeActorIntegrityError("incremental audit row is missing")
        previous = _hmac_value(first["previous_head"], "audit previous head")
        self._verify_chain_range(
            conn,
            start_revision=start,
            end_revision=state.revision,
            expected_previous_head=previous,
            expected_final_head=state.chain_head,
        )

    def _audit_base(self, row: _AuditRow) -> dict[str, object]:
        return {
            "revision": row.revision,
            "previous_head": row.previous_head,
            "operation": row.operation,
            "object_id": row.object_id,
            "envelope_id": row.envelope_id,
            "record_hmac": row.record_hmac,
            "occurred_at_ms": row.occurred_at_ms,
        }

    def _audit_sealed_material(self, row: _AuditRow) -> dict[str, object]:
        return {**self._audit_base(row), "chain_head": row.chain_head}

    def _row_audit(self, row: sqlite3.Row) -> _AuditRow:
        try:
            audit = _AuditRow(
                revision=int(row["revision"]),
                previous_head=str(row["previous_head"]),
                operation=str(row["operation"]),
                object_id=str(row["object_id"]),
                envelope_id=str(row["envelope_id"]),
                record_hmac=str(row["record_hmac"]),
                occurred_at_ms=int(row["occurred_at_ms"]),
                chain_head=str(row["chain_head"]),
                audit_seal=str(row["audit_seal"]),
            )
            _nonnegative_int(audit.revision, "audit revision", positive=True)
            _hmac_value(audit.previous_head, "audit previous head")
            _hmac_value(audit.object_id, "audit object id")
            _hmac_value(audit.envelope_id, "audit envelope id")
            _hmac_value(audit.record_hmac, "audit record HMAC")
            _nonnegative_int(audit.occurred_at_ms, "audit timestamp")
            _hmac_value(audit.chain_head, "audit chain head")
            _hmac_value(audit.audit_seal, "audit seal")
        except (KeyError, TypeError, ValueError, BridgeActorIdentityError) as exc:
            raise BridgeActorIntegrityError("bridge actor audit row is malformed") from exc
        if audit.operation not in {"issue", "accept", "deny"}:
            raise BridgeActorIntegrityError("bridge actor audit operation is invalid")
        expected_head = self._hmac(_AUDIT_CHAIN_DOMAIN, self._audit_base(audit))
        expected_seal = self._hmac(
            _AUDIT_SEAL_DOMAIN, self._audit_sealed_material(audit)
        )
        if not hmac.compare_digest(expected_head, audit.chain_head) or not hmac.compare_digest(
            expected_seal, audit.audit_seal
        ):
            raise BridgeActorIntegrityError("bridge actor audit seal does not verify")
        return audit

    def _verify_chain_range(
        self,
        conn: sqlite3.Connection,
        *,
        start_revision: int,
        end_revision: int,
        expected_previous_head: str,
        expected_final_head: str,
    ) -> int:
        if start_revision > end_revision:
            if not hmac.compare_digest(expected_previous_head, expected_final_head):
                raise BridgeActorIntegrityError("empty audit range head mismatch")
            return 0
        rows = conn.execute(
            f"SELECT * FROM {_AUDIT_TABLE} WHERE revision BETWEEN ? AND ? "
            "ORDER BY revision",
            (start_revision, end_revision),
        ).fetchall()
        expected_count = end_revision - start_revision + 1
        if len(rows) != expected_count:
            raise BridgeActorIntegrityError("bridge actor audit range is truncated")
        previous = expected_previous_head
        for expected_revision, raw in enumerate(rows, start=start_revision):
            audit = self._row_audit(raw)
            if audit.revision != expected_revision or not hmac.compare_digest(
                audit.previous_head, previous
            ):
                raise BridgeActorIntegrityError("bridge actor audit chain is discontinuous")
            self._verify_audit_record(conn, audit)
            previous = audit.chain_head
        if not hmac.compare_digest(previous, expected_final_head):
            raise BridgeActorIntegrityError("bridge actor audit chain head does not match")
        return len(rows)

    def _verify_audit_record(self, conn: sqlite3.Connection, audit: _AuditRow) -> None:
        if audit.operation == "issue":
            row = conn.execute(
                f"SELECT * FROM {_ENVELOPE_TABLE} WHERE envelope_id=?",
                (audit.object_id,),
            ).fetchone()
            if row is None or audit.envelope_id != audit.object_id:
                raise BridgeActorIntegrityError("audit envelope record is missing")
            envelope = self._row_envelope(row)
            expected = self._envelope_record_hmac(envelope)
        else:
            row = conn.execute(
                f"SELECT * FROM {_EVIDENCE_TABLE} WHERE evidence_id=?",
                (audit.object_id,),
            ).fetchone()
            if row is None:
                raise BridgeActorIntegrityError("audit evidence record is missing")
            evidence = self._row_evidence(row)
            if evidence.decision != audit.operation or evidence.envelope_id != audit.envelope_id:
                raise BridgeActorIntegrityError("audit evidence binding does not match")
            expected = self._evidence_record_hmac(evidence)
        if not hmac.compare_digest(expected, audit.record_hmac):
            raise BridgeActorIntegrityError("audit record HMAC does not verify")

    def _append_audit(
        self,
        conn: sqlite3.Connection,
        state: _StoreState,
        *,
        operation: str,
        object_id: str,
        envelope_id: str,
        record_hmac: str,
        occurred_at_ms: int,
        envelope_delta: int,
        evidence_delta: int,
        consumed_delta: int,
        high_water_ms: int,
    ) -> _StoreState:
        revision = state.revision + 1
        provisional = _AuditRow(
            revision=revision,
            previous_head=state.chain_head,
            operation=operation,
            object_id=object_id,
            envelope_id=envelope_id,
            record_hmac=record_hmac,
            occurred_at_ms=occurred_at_ms,
            chain_head="",
            audit_seal="",
        )
        chain_head = self._hmac(_AUDIT_CHAIN_DOMAIN, self._audit_base(provisional))
        with_head = _AuditRow(
            **{
                **self._audit_base(provisional),
                "chain_head": chain_head,
                "audit_seal": "",
            }
        )
        audit = _AuditRow(
            **{
                **self._audit_sealed_material(with_head),
                "audit_seal": self._hmac(
                    _AUDIT_SEAL_DOMAIN, self._audit_sealed_material(with_head)
                ),
            }
        )
        conn.execute(
            f"""
            INSERT INTO {_AUDIT_TABLE}
                (revision,previous_head,operation,object_id,envelope_id,
                 record_hmac,occurred_at_ms,chain_head,audit_seal)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                audit.revision,
                audit.previous_head,
                audit.operation,
                audit.object_id,
                audit.envelope_id,
                audit.record_hmac,
                audit.occurred_at_ms,
                audit.chain_head,
                audit.audit_seal,
            ),
        )
        next_state = self._with_state_seal(
            _StoreState(
                schema_version=state.schema_version,
                policy_version=state.policy_version,
                key_version=state.key_version,
                service=state.service,
                platform=state.platform,
                boundary_hmac=state.boundary_hmac,
                revision=revision,
                chain_head=audit.chain_head,
                envelope_count=state.envelope_count + envelope_delta,
                evidence_count=state.evidence_count + evidence_delta,
                consumed_count=state.consumed_count + consumed_delta,
                high_water_ms=high_water_ms,
                state_seal="",
            )
        )
        updated = conn.execute(
            f"""
            UPDATE {_STATE_TABLE}
               SET revision=?,chain_head=?,envelope_count=?,evidence_count=?,
                   consumed_count=?,high_water_ms=?,state_seal=?
             WHERE singleton=1 AND revision=? AND chain_head=?
            """,
            (
                next_state.revision,
                next_state.chain_head,
                next_state.envelope_count,
                next_state.evidence_count,
                next_state.consumed_count,
                next_state.high_water_ms,
                next_state.state_seal,
                state.revision,
                state.chain_head,
            ),
        )
        if updated.rowcount != 1:
            raise BridgeActorIntegrityError("bridge actor state advance lost serialization")
        return next_state

    def _synchronize_anchor(self, target: AnchorState) -> None:
        try:
            for _attempt in range(8):
                current = self._read_anchor()
                if current is None:
                    raise BridgeActorQuarantinedError("monotonic_anchor_missing")
                if current.revision > target.revision:
                    return
                if current.revision == target.revision:
                    if not hmac.compare_digest(current.chain_head, target.chain_head):
                        raise BridgeActorQuarantinedError(
                            "database_snapshot_divergence"
                        )
                    self._set_ready()
                    return
                if self._anchor_cas(current, target):
                    self._set_ready()
                    return
        except BridgeActorQuarantinedError as exc:
            self._set_quarantined(exc.reason)
            raise
        except BridgeActorNotReadyError as exc:
            self._set_not_ready(exc.reason)
            raise
        self._set_not_ready("monotonic_anchor_race")
        raise BridgeActorNotReadyError("monotonic_anchor_race")

    def _observed_time(self, state: _StoreState) -> int:
        now_ms = self._clock_now()
        if now_ms < state.high_water_ms:
            raise BridgeActorClockRollbackError("trusted clock moved backward")
        if now_ms - state.high_water_ms > self._policy.max_clock_advance_ms:
            raise BridgeActorFutureClockError("trusted clock jump exceeds policy")
        return now_ms

    def _derive_bindings(
        self,
        *,
        request_body: object,
        discord_event_id: object,
        external_actor_id: object,
        guild_id: object,
        channel_id: object,
        thread_id: object,
    ) -> _Bindings:
        body = _body_bytes(request_body, self._policy.max_body_bytes)
        _event_present, event = _external_id(
            discord_event_id,
            "Discord event id",
            maximum=self._policy.max_external_id_bytes,
            optional=False,
        )
        _actor_present, actor = _external_id(
            external_actor_id,
            "external actor id",
            maximum=self._policy.max_external_id_bytes,
            optional=False,
        )
        guild_present, guild = _external_id(
            guild_id,
            "guild id",
            maximum=self._policy.max_external_id_bytes,
            optional=True,
        )
        _channel_present, channel = _external_id(
            channel_id,
            "channel id",
            maximum=self._policy.max_external_id_bytes,
            optional=False,
        )
        thread_present, thread = _external_id(
            thread_id,
            "thread id",
            maximum=self._policy.max_external_id_bytes,
            optional=True,
        )
        context = {
            "service": self._boundary.service,
            "platform": self._boundary.platform,
            "boundary_hmac": self._boundary_hmac,
        }
        guild_binding = {"present": guild_present, "value": guild}
        thread_binding = {"present": thread_present, "value": thread}
        body_context = _canonical(context).encode("utf-8") + b"\x00" + body
        return _Bindings(
            actor_subject_hmac=self._hmac(
                _SUBJECT_DOMAIN, {**context, "actor": actor}
            ),
            guild_scope_hmac=self._hmac(
                _GUILD_DOMAIN, {**context, "guild": guild_binding}
            ),
            channel_scope_hmac=self._hmac(
                _CHANNEL_DOMAIN,
                {**context, "guild": guild_binding, "channel": channel},
            ),
            thread_scope_hmac=self._hmac(
                _THREAD_DOMAIN,
                {
                    **context,
                    "guild": guild_binding,
                    "channel": channel,
                    "thread": thread_binding,
                },
            ),
            event_id_hmac=self._hmac(
                _EVENT_DOMAIN, {**context, "discord_event_id": event}
            ),
            body_hmac=self._hmac_bytes(_BODY_DOMAIN, body_context),
        )

    @staticmethod
    def _unsigned_envelope(envelope: BridgeActorEnvelope) -> dict[str, object]:
        return {
            "envelope_version": envelope.envelope_version,
            "schema_version": envelope.schema_version,
            "policy_version": envelope.policy_version,
            "key_version": envelope.key_version,
            "service": envelope.service,
            "platform": envelope.platform,
            "boundary_hmac": envelope.boundary_hmac,
            "actor_subject_hmac": envelope.actor_subject_hmac,
            "guild_scope_hmac": envelope.guild_scope_hmac,
            "channel_scope_hmac": envelope.channel_scope_hmac,
            "thread_scope_hmac": envelope.thread_scope_hmac,
            "event_id_hmac": envelope.event_id_hmac,
            "body_hmac": envelope.body_hmac,
            "nonce_hmac": envelope.nonce_hmac,
            "issued_at_ms": envelope.issued_at_ms,
            "expires_at_ms": envelope.expires_at_ms,
        }

    @classmethod
    def _sealed_envelope(cls, envelope: BridgeActorEnvelope) -> dict[str, object]:
        return {**cls._unsigned_envelope(envelope), "envelope_id": envelope.envelope_id}

    def _authenticity_reason(self, envelope: BridgeActorEnvelope) -> str | None:
        versions = (
            envelope.envelope_version,
            envelope.schema_version,
            envelope.policy_version,
            envelope.key_version,
        )
        expected_versions = (
            ENVELOPE_VERSION,
            SCHEMA_VERSION,
            self._policy.version,
            self._key_version,
        )
        if versions != expected_versions:
            return "unsupported_version"
        if envelope.expires_at_ms - envelope.issued_at_ms != self._policy.envelope_ttl_ms:
            return "invalid_lifetime"
        expected_id = self._hmac(_ENVELOPE_ID_DOMAIN, self._unsigned_envelope(envelope))
        expected_seal = self._hmac(
            _ENVELOPE_SEAL_DOMAIN, self._sealed_envelope(envelope)
        )
        if not hmac.compare_digest(expected_id, envelope.envelope_id) or not hmac.compare_digest(
            expected_seal, envelope.seal
        ):
            return "invalid_seal"
        if (
            envelope.service != self._boundary.service
            or envelope.platform != self._boundary.platform
            or not hmac.compare_digest(envelope.boundary_hmac, self._boundary_hmac)
        ):
            return "boundary_mismatch"
        return None

    def _envelope_record_hmac(self, envelope: BridgeActorEnvelope) -> str:
        return self._hmac(
            _AUDIT_RECORD_DOMAIN,
            {"kind": "envelope", "record": envelope.as_dict()},
        )

    def issue_envelope(
        self,
        *,
        request_body: bytes | bytearray | memoryview,
        discord_event_id: str | int,
        external_actor_id: str | int,
        guild_id: str | int | None,
        channel_id: str | int,
        thread_id: str | int | None,
    ) -> BridgeActorEnvelope:
        """Issue one event-bound envelope from actual adapter-derived inputs."""
        self._ensure_ready()
        bindings = self._derive_bindings(
            request_body=request_body,
            discord_event_id=discord_event_id,
            external_actor_id=external_actor_id,
            guild_id=guild_id,
            channel_id=channel_id,
            thread_id=thread_id,
        )
        anchor_advanced = False
        try:
            with connect(self._db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                state = self._gate_locked(conn)
                duplicate = conn.execute(
                    f"SELECT 1 FROM {_ENVELOPE_TABLE} WHERE event_id_hmac=?",
                    (bindings.event_id_hmac,),
                ).fetchone()
                if duplicate is not None:
                    raise BridgeActorEventReplayError("Discord event was already issued")
                issued_at_ms = self._observed_time(state)
                provisional = BridgeActorEnvelope(
                    envelope_version=ENVELOPE_VERSION,
                    schema_version=SCHEMA_VERSION,
                    policy_version=self._policy.version,
                    key_version=self._key_version,
                    service=self._boundary.service,
                    platform=self._boundary.platform,
                    boundary_hmac=self._boundary_hmac,
                    actor_subject_hmac=bindings.actor_subject_hmac,
                    guild_scope_hmac=bindings.guild_scope_hmac,
                    channel_scope_hmac=bindings.channel_scope_hmac,
                    thread_scope_hmac=bindings.thread_scope_hmac,
                    event_id_hmac=bindings.event_id_hmac,
                    body_hmac=bindings.body_hmac,
                    nonce_hmac=self._hmac_bytes(_NONCE_DOMAIN, secrets.token_bytes(32)),
                    issued_at_ms=issued_at_ms,
                    expires_at_ms=issued_at_ms + self._policy.envelope_ttl_ms,
                    envelope_id="",
                    seal="",
                )
                envelope_id = self._hmac(
                    _ENVELOPE_ID_DOMAIN, self._unsigned_envelope(provisional)
                )
                with_id = BridgeActorEnvelope(
                    **{**provisional.as_dict(), "envelope_id": envelope_id}
                )
                envelope = BridgeActorEnvelope(
                    **{
                        **with_id.as_dict(),
                        "seal": self._hmac(
                            _ENVELOPE_SEAL_DOMAIN, self._sealed_envelope(with_id)
                        ),
                    }
                )
                conn.execute(
                    f"""
                    INSERT INTO {_ENVELOPE_TABLE}
                        (envelope_id,envelope_version,schema_version,policy_version,
                         key_version,service,platform,boundary_hmac,
                         actor_subject_hmac,guild_scope_hmac,channel_scope_hmac,
                         thread_scope_hmac,event_id_hmac,body_hmac,nonce_hmac,
                         issued_at_ms,expires_at_ms,consumed_at_ms,envelope_seal)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?)
                    """,
                    (
                        envelope.envelope_id,
                        envelope.envelope_version,
                        envelope.schema_version,
                        envelope.policy_version,
                        envelope.key_version,
                        envelope.service,
                        envelope.platform,
                        envelope.boundary_hmac,
                        envelope.actor_subject_hmac,
                        envelope.guild_scope_hmac,
                        envelope.channel_scope_hmac,
                        envelope.thread_scope_hmac,
                        envelope.event_id_hmac,
                        envelope.body_hmac,
                        envelope.nonce_hmac,
                        envelope.issued_at_ms,
                        envelope.expires_at_ms,
                        envelope.seal,
                    ),
                )
                next_state = self._append_audit(
                    conn,
                    state,
                    operation="issue",
                    object_id=envelope.envelope_id,
                    envelope_id=envelope.envelope_id,
                    record_hmac=self._envelope_record_hmac(envelope),
                    occurred_at_ms=issued_at_ms,
                    envelope_delta=1,
                    evidence_delta=0,
                    consumed_delta=0,
                    high_water_ms=issued_at_ms,
                )
                self._synchronize_anchor(self._anchor_state(next_state))
                anchor_advanced = True
            return envelope
        except BridgeActorQuarantinedError as exc:
            self._set_quarantined(exc.reason)
            raise
        except BridgeActorNotReadyError:
            raise
        except BridgeActorIntegrityError as exc:
            self._set_quarantined("sealed_state_integrity_failure")
            raise BridgeActorQuarantinedError("sealed_state_integrity_failure") from exc
        except sqlite3.DatabaseError as exc:
            if anchor_advanced:
                self._set_quarantined("database_commit_uncertain")
                raise BridgeActorQuarantinedError("database_commit_uncertain") from exc
            raise

    def _candidate_reference(
        self,
        value: BridgeActorEnvelope | Mapping[str, object] | str,
    ) -> str:
        try:
            if isinstance(value, BridgeActorEnvelope):
                payload = value.encode().encode("utf-8")
            elif isinstance(value, str):
                payload = value.encode("utf-8")
            elif isinstance(value, Mapping):
                payload = _canonical(dict(value)).encode("utf-8")
            else:
                payload = type(value).__name__.encode("ascii", errors="replace")
        except (TypeError, ValueError, BridgeActorIdentityError):
            payload = b"unserializable"
        if len(payload) > self._policy.max_transport_bytes:
            payload = payload[: self._policy.max_transport_bytes]
        return self._hmac_bytes(_CANDIDATE_DOMAIN, payload)

    def _row_envelope(self, row: sqlite3.Row) -> BridgeActorEnvelope:
        try:
            envelope = BridgeActorEnvelope(
                envelope_version=int(row["envelope_version"]),
                schema_version=int(row["schema_version"]),
                policy_version=int(row["policy_version"]),
                key_version=int(row["key_version"]),
                service=str(row["service"]),
                platform=str(row["platform"]),
                boundary_hmac=str(row["boundary_hmac"]),
                actor_subject_hmac=str(row["actor_subject_hmac"]),
                guild_scope_hmac=str(row["guild_scope_hmac"]),
                channel_scope_hmac=str(row["channel_scope_hmac"]),
                thread_scope_hmac=str(row["thread_scope_hmac"]),
                event_id_hmac=str(row["event_id_hmac"]),
                body_hmac=str(row["body_hmac"]),
                nonce_hmac=str(row["nonce_hmac"]),
                issued_at_ms=int(row["issued_at_ms"]),
                expires_at_ms=int(row["expires_at_ms"]),
                envelope_id=str(row["envelope_id"]),
                seal=str(row["envelope_seal"]),
            )
            _parse_envelope(
                envelope, max_transport_bytes=self._policy.max_transport_bytes
            )
        except (KeyError, TypeError, ValueError, BridgeActorIdentityError) as exc:
            raise BridgeActorIntegrityError("stored bridge actor envelope is malformed") from exc
        if self._authenticity_reason(envelope) is not None:
            raise BridgeActorIntegrityError("stored bridge actor envelope seal does not verify")
        consumed = row["consumed_at_ms"]
        if consumed is not None:
            try:
                consumed_at = _nonnegative_int(consumed, "consumed timestamp")
            except BridgeActorIdentityError as exc:
                raise BridgeActorIntegrityError("stored nonce state is malformed") from exc
            if consumed_at < envelope.issued_at_ms:
                raise BridgeActorIntegrityError("stored nonce state is invalid")
        return envelope

    def _evidence_material(self, evidence: ActorDecisionEvidence) -> dict[str, object]:
        return {
            field: getattr(evidence, field)
            for field in evidence.__dataclass_fields__
            if field != "seal"
        }

    def _evidence_record_hmac(self, evidence: ActorDecisionEvidence) -> str:
        return self._hmac(
            _AUDIT_RECORD_DOMAIN,
            {"kind": "evidence", "record": evidence.as_dict()},
        )

    def _new_evidence(
        self,
        *,
        decision: str,
        reason: str,
        envelope_id: str,
        bindings: _Bindings,
        expires_at_ms: int,
        occurred_at_ms: int,
    ) -> ActorDecisionEvidence:
        if decision not in _DECISIONS or reason not in _REASONS:
            raise BridgeActorIntegrityError("bridge actor evidence decision is invalid")
        values: dict[str, object] = {
            "evidence_id": self._hmac_bytes(
                _EVIDENCE_ID_DOMAIN, secrets.token_bytes(32)
            ),
            "evidence_version": EVIDENCE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "policy_version": self._policy.version,
            "key_version": self._key_version,
            "decision": decision,
            "reason": reason,
            "service": self._boundary.service,
            "platform": self._boundary.platform,
            "boundary_hmac": self._boundary_hmac,
            "envelope_id": envelope_id,
            "actor_subject_hmac": bindings.actor_subject_hmac,
            "guild_scope_hmac": bindings.guild_scope_hmac,
            "channel_scope_hmac": bindings.channel_scope_hmac,
            "thread_scope_hmac": bindings.thread_scope_hmac,
            "event_id_hmac": bindings.event_id_hmac,
            "body_hmac": bindings.body_hmac,
            "expires_at_ms": expires_at_ms,
            "occurred_at_ms": occurred_at_ms,
            "seal": "",
        }
        provisional = ActorDecisionEvidence(_factory=_FACTORY, **values)
        values["seal"] = self._hmac(
            _EVIDENCE_SEAL_DOMAIN, self._evidence_material(provisional)
        )
        return ActorDecisionEvidence(_factory=_FACTORY, **values)

    def _validate_evidence(self, evidence: ActorDecisionEvidence) -> None:
        if type(evidence) is not ActorDecisionEvidence:
            raise BridgeActorIntegrityError("bridge actor evidence is not factory-created")
        try:
            for field in (
                "evidence_id",
                "boundary_hmac",
                "envelope_id",
                "actor_subject_hmac",
                "guild_scope_hmac",
                "channel_scope_hmac",
                "thread_scope_hmac",
                "event_id_hmac",
                "body_hmac",
                "seal",
            ):
                _hmac_value(getattr(evidence, field), f"evidence {field}")
            _public_label(evidence.service, "evidence service")
            _public_label(evidence.platform, "evidence platform")
            _nonnegative_int(evidence.expires_at_ms, "evidence expiry")
            _nonnegative_int(evidence.occurred_at_ms, "evidence timestamp")
        except BridgeActorIdentityError as exc:
            raise BridgeActorIntegrityError("bridge actor evidence is malformed") from exc
        if (
            evidence.evidence_version != EVIDENCE_VERSION
            or evidence.schema_version != SCHEMA_VERSION
            or evidence.policy_version != self._policy.version
            or evidence.key_version != self._key_version
            or evidence.service != self._boundary.service
            or evidence.platform != self._boundary.platform
            or not hmac.compare_digest(evidence.boundary_hmac, self._boundary_hmac)
            or evidence.decision not in _DECISIONS
            or evidence.reason not in _REASONS
            or (evidence.decision == "accept") != (evidence.reason == "accepted")
        ):
            raise BridgeActorIntegrityError("bridge actor evidence binding is invalid")
        expected = self._hmac(
            _EVIDENCE_SEAL_DOMAIN, self._evidence_material(evidence)
        )
        if not hmac.compare_digest(expected, evidence.seal):
            raise BridgeActorIntegrityError("bridge actor evidence seal does not verify")

    def _row_evidence(self, row: sqlite3.Row) -> ActorDecisionEvidence:
        try:
            evidence = ActorDecisionEvidence(
                _factory=_FACTORY,
                evidence_id=str(row["evidence_id"]),
                evidence_version=int(row["evidence_version"]),
                schema_version=int(row["schema_version"]),
                policy_version=int(row["policy_version"]),
                key_version=int(row["key_version"]),
                decision=str(row["decision"]),
                reason=str(row["reason"]),
                service=str(row["service"]),
                platform=str(row["platform"]),
                boundary_hmac=str(row["boundary_hmac"]),
                envelope_id=str(row["envelope_id"]),
                actor_subject_hmac=str(row["actor_subject_hmac"]),
                guild_scope_hmac=str(row["guild_scope_hmac"]),
                channel_scope_hmac=str(row["channel_scope_hmac"]),
                thread_scope_hmac=str(row["thread_scope_hmac"]),
                event_id_hmac=str(row["event_id_hmac"]),
                body_hmac=str(row["body_hmac"]),
                expires_at_ms=int(row["expires_at_ms"]),
                occurred_at_ms=int(row["occurred_at_ms"]),
                seal=str(row["evidence_seal"]),
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise BridgeActorIntegrityError("stored bridge actor evidence is malformed") from exc
        self._validate_evidence(evidence)
        return evidence

    def _insert_decision(
        self,
        conn: sqlite3.Connection,
        state: _StoreState,
        *,
        decision: str,
        reason: str,
        envelope_id: str,
        bindings: _Bindings,
        expires_at_ms: int,
        occurred_at_ms: int,
        consume: bool,
        high_water_ms: int,
    ) -> tuple[ActorDecisionEvidence, _StoreState]:
        if consume:
            updated = conn.execute(
                f"UPDATE {_ENVELOPE_TABLE} SET consumed_at_ms=? "
                "WHERE envelope_id=? AND consumed_at_ms IS NULL",
                (occurred_at_ms, envelope_id),
            )
            if updated.rowcount != 1:
                raise BridgeActorIntegrityError("atomic nonce consumption failed")
        evidence = self._new_evidence(
            decision=decision,
            reason=reason,
            envelope_id=envelope_id,
            bindings=bindings,
            expires_at_ms=expires_at_ms,
            occurred_at_ms=occurred_at_ms,
        )
        conn.execute(
            f"""
            INSERT INTO {_EVIDENCE_TABLE}
                (evidence_id,evidence_version,schema_version,policy_version,
                 key_version,decision,reason,service,platform,boundary_hmac,
                 envelope_id,actor_subject_hmac,guild_scope_hmac,
                 channel_scope_hmac,thread_scope_hmac,event_id_hmac,body_hmac,
                 expires_at_ms,occurred_at_ms,evidence_seal)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                evidence.evidence_id,
                evidence.evidence_version,
                evidence.schema_version,
                evidence.policy_version,
                evidence.key_version,
                evidence.decision,
                evidence.reason,
                evidence.service,
                evidence.platform,
                evidence.boundary_hmac,
                evidence.envelope_id,
                evidence.actor_subject_hmac,
                evidence.guild_scope_hmac,
                evidence.channel_scope_hmac,
                evidence.thread_scope_hmac,
                evidence.event_id_hmac,
                evidence.body_hmac,
                evidence.expires_at_ms,
                evidence.occurred_at_ms,
                evidence.seal,
            ),
        )
        next_state = self._append_audit(
            conn,
            state,
            operation=decision,
            object_id=evidence.evidence_id,
            envelope_id=envelope_id,
            record_hmac=self._evidence_record_hmac(evidence),
            occurred_at_ms=occurred_at_ms,
            envelope_delta=0,
            evidence_delta=1,
            consumed_delta=1 if consume else 0,
            high_water_ms=high_water_ms,
        )
        return evidence, next_state

    def _guest_actor(self, envelope: BridgeActorEnvelope) -> VerifiedGuestActor:
        return VerifiedGuestActor(
            _factory=_FACTORY,
            envelope_version=envelope.envelope_version,
            schema_version=envelope.schema_version,
            policy_version=envelope.policy_version,
            key_version=envelope.key_version,
            service=envelope.service,
            platform=envelope.platform,
            boundary_hmac=envelope.boundary_hmac,
            actor_subject_hmac=envelope.actor_subject_hmac,
            guild_scope_hmac=envelope.guild_scope_hmac,
            channel_scope_hmac=envelope.channel_scope_hmac,
            thread_scope_hmac=envelope.thread_scope_hmac,
            event_id_hmac=envelope.event_id_hmac,
            body_hmac=envelope.body_hmac,
            envelope_id=envelope.envelope_id,
            expires_at_ms=envelope.expires_at_ms,
        )

    def _result(
        self,
        evidence: ActorDecisionEvidence,
        envelope: BridgeActorEnvelope | None,
    ) -> BridgeActorVerification:
        actor = self._guest_actor(envelope) if evidence.decision == "accept" and envelope else None
        return BridgeActorVerification(
            _factory=_FACTORY,
            actor=actor,
            evidence=evidence,
        )

    def _deny_untrusted(
        self,
        *,
        reason: str,
        candidate_reference: str,
        bindings: _Bindings,
    ) -> BridgeActorVerification:
        anchor_advanced = False
        try:
            with connect(self._db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                state = self._gate_locked(conn)
                evidence, next_state = self._insert_decision(
                    conn,
                    state,
                    decision="deny",
                    reason=reason,
                    envelope_id=candidate_reference,
                    bindings=bindings,
                    expires_at_ms=0,
                    occurred_at_ms=state.high_water_ms,
                    consume=False,
                    high_water_ms=state.high_water_ms,
                )
                self._synchronize_anchor(self._anchor_state(next_state))
                anchor_advanced = True
            return self._result(evidence, None)
        except BridgeActorQuarantinedError as exc:
            self._set_quarantined(exc.reason)
            raise
        except BridgeActorNotReadyError:
            raise
        except BridgeActorIntegrityError as exc:
            self._set_quarantined("sealed_state_integrity_failure")
            raise BridgeActorQuarantinedError("sealed_state_integrity_failure") from exc
        except sqlite3.DatabaseError as exc:
            if anchor_advanced:
                self._set_quarantined("database_commit_uncertain")
                raise BridgeActorQuarantinedError("database_commit_uncertain") from exc
            raise

    def verify_and_consume(
        self,
        envelope: BridgeActorEnvelope | Mapping[str, object] | str,
        *,
        request_body: bytes | bytearray | memoryview,
        discord_event_id: str | int,
        external_actor_id: str | int,
        guild_id: str | int | None,
        channel_id: str | int,
        thread_id: str | int | None,
    ) -> BridgeActorVerification:
        """Verify actual bytes and exact event/scope bindings, then consume once."""
        self._ensure_ready()
        bindings = self._derive_bindings(
            request_body=request_body,
            discord_event_id=discord_event_id,
            external_actor_id=external_actor_id,
            guild_id=guild_id,
            channel_id=channel_id,
            thread_id=thread_id,
        )
        candidate_reference = self._candidate_reference(envelope)
        try:
            parsed = _parse_envelope(
                envelope, max_transport_bytes=self._policy.max_transport_bytes
            )
        except BridgeActorIdentityError:
            return self._deny_untrusted(
                reason="malformed_envelope",
                candidate_reference=candidate_reference,
                bindings=bindings,
            )
        authenticity_reason = self._authenticity_reason(parsed)
        if authenticity_reason is not None:
            return self._deny_untrusted(
                reason=authenticity_reason,
                candidate_reference=candidate_reference,
                bindings=bindings,
            )

        mismatch: str | None = None
        for actual, expected, reason in (
            (parsed.actor_subject_hmac, bindings.actor_subject_hmac, "subject_mismatch"),
            (parsed.guild_scope_hmac, bindings.guild_scope_hmac, "guild_scope_mismatch"),
            (
                parsed.channel_scope_hmac,
                bindings.channel_scope_hmac,
                "channel_scope_mismatch",
            ),
            (parsed.thread_scope_hmac, bindings.thread_scope_hmac, "thread_scope_mismatch"),
            (parsed.event_id_hmac, bindings.event_id_hmac, "event_mismatch"),
            (parsed.body_hmac, bindings.body_hmac, "body_mismatch"),
        ):
            if not hmac.compare_digest(actual, expected):
                mismatch = reason
                break

        anchor_advanced = False
        try:
            with connect(self._db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                state = self._gate_locked(conn)
                now_ms = self._observed_time(state)
                reason = mismatch
                if reason is None and now_ms < parsed.issued_at_ms:
                    reason = "not_yet_valid"
                if reason is None and now_ms >= parsed.expires_at_ms:
                    reason = "expired"
                row = None
                if reason is None:
                    row = conn.execute(
                        f"SELECT * FROM {_ENVELOPE_TABLE} WHERE envelope_id=?",
                        (parsed.envelope_id,),
                    ).fetchone()
                    if row is None:
                        reason = "unknown_envelope"
                if row is not None:
                    stored = self._row_envelope(row)
                    if stored != parsed:
                        raise BridgeActorIntegrityError(
                            "stored envelope differs from signed transport"
                        )
                    accepted_row = conn.execute(
                        f"SELECT * FROM {_EVIDENCE_TABLE} "
                        "WHERE envelope_id=? AND decision='accept' LIMIT 1",
                        (parsed.envelope_id,),
                    ).fetchone()
                    if accepted_row is not None:
                        self._row_evidence(accepted_row)
                    consumed = row["consumed_at_ms"] is not None
                    if consumed != (accepted_row is not None):
                        raise BridgeActorIntegrityError(
                            "nonce state conflicts with sealed accept evidence"
                        )
                    if reason is None and consumed:
                        reason = "replay"
                accepted = reason is None
                evidence, next_state = self._insert_decision(
                    conn,
                    state,
                    decision="accept" if accepted else "deny",
                    reason="accepted" if accepted else str(reason),
                    envelope_id=parsed.envelope_id,
                    bindings=bindings,
                    expires_at_ms=parsed.expires_at_ms,
                    occurred_at_ms=now_ms,
                    consume=accepted,
                    high_water_ms=now_ms,
                )
                self._synchronize_anchor(self._anchor_state(next_state))
                anchor_advanced = True
            return self._result(evidence, parsed if accepted else None)
        except BridgeActorQuarantinedError as exc:
            self._set_quarantined(exc.reason)
            raise
        except BridgeActorNotReadyError:
            raise
        except BridgeActorIntegrityError as exc:
            self._set_quarantined("sealed_state_integrity_failure")
            raise BridgeActorQuarantinedError("sealed_state_integrity_failure") from exc
        except sqlite3.DatabaseError as exc:
            if anchor_advanced:
                self._set_quarantined("database_commit_uncertain")
                raise BridgeActorQuarantinedError("database_commit_uncertain") from exc
            raise

    def verify_evidence(self, evidence: ActorDecisionEvidence) -> bool:
        self._validate_evidence(evidence)
        return True

    def get_evidence(self, evidence_id: str) -> ActorDecisionEvidence | None:
        self._ensure_ready()
        key = _hmac_value(evidence_id, "evidence id")
        try:
            with connect(self._db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                self._gate_locked(conn)
                row = conn.execute(
                    f"SELECT * FROM {_EVIDENCE_TABLE} WHERE evidence_id=?",
                    (key,),
                ).fetchone()
            return None if row is None else self._row_evidence(row)
        except BridgeActorQuarantinedError:
            raise
        except BridgeActorNotReadyError:
            raise
        except BridgeActorIntegrityError as exc:
            self._set_quarantined("sealed_state_integrity_failure")
            raise BridgeActorQuarantinedError("sealed_state_integrity_failure") from exc

    def list_evidence(self, *, limit: int = 100) -> tuple[ActorDecisionEvidence, ...]:
        self._ensure_ready()
        count = _nonnegative_int(limit, "evidence limit", positive=True)
        if count > 1000:
            raise BridgeActorIdentityError("evidence limit is too large")
        try:
            with connect(self._db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                self._gate_locked(conn)
                rows = conn.execute(
                    f"SELECT * FROM {_EVIDENCE_TABLE} "
                    "ORDER BY evidence_seq DESC LIMIT ?",
                    (count,),
                ).fetchall()
            return tuple(self._row_evidence(row) for row in rows)
        except BridgeActorQuarantinedError:
            raise
        except BridgeActorNotReadyError:
            raise
        except BridgeActorIntegrityError as exc:
            self._set_quarantined("sealed_state_integrity_failure")
            raise BridgeActorQuarantinedError("sealed_state_integrity_failure") from exc

    def full_audit(self, *, reconcile_anchor: bool = False) -> AuditReport:
        """Explicitly verify every sealed row and optionally repair a lagging anchor."""
        revision = 0
        rows_verified = 0
        anchor_revision: int | None = None
        reason = "ok"
        try:
            with connect(self._db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                _verify_schema_manifest(
                    conn, _MAIN_SCHEMA_MANIFEST, allow_missing=False
                )
                state = self._read_state(conn)
                revision = state.revision
                self._check_counts(conn, state)
                rows_verified = self._verify_chain_range(
                    conn,
                    start_revision=1,
                    end_revision=state.revision,
                    expected_previous_head=self._genesis_head,
                    expected_final_head=state.chain_head,
                )
                anchor = self._read_anchor()
                anchor_revision = None if anchor is None else anchor.revision
                target = self._anchor_state(state)
                if anchor is None:
                    if reconcile_anchor and state.revision == 0:
                        if not self._anchor_cas(None, target):
                            raise BridgeActorNotReadyError("monotonic_anchor_race")
                        anchor = target
                        anchor_revision = 0
                    else:
                        reason = "monotonic_anchor_missing"
                elif anchor.revision > state.revision:
                    reason = "database_snapshot_rollback"
                elif anchor.revision == state.revision:
                    if not hmac.compare_digest(anchor.chain_head, state.chain_head):
                        reason = "database_snapshot_divergence"
                else:
                    if anchor.revision == 0:
                        anchored_head = self._genesis_head
                    else:
                        anchored_row = conn.execute(
                            f"SELECT chain_head FROM {_AUDIT_TABLE} WHERE revision=?",
                            (anchor.revision,),
                        ).fetchone()
                        if anchored_row is None:
                            raise BridgeActorIntegrityError(
                                "anchored audit revision is missing"
                            )
                        anchored_head = _hmac_value(
                            anchored_row["chain_head"], "anchored audit head"
                        )
                    if not hmac.compare_digest(anchor.chain_head, anchored_head):
                        reason = "database_snapshot_divergence"
                    elif reconcile_anchor:
                        if not self._anchor_cas(anchor, target):
                            current = self._read_anchor()
                            if current != target:
                                raise BridgeActorNotReadyError(
                                    "monotonic_anchor_race"
                                )
                        anchor_revision = state.revision
                    else:
                        reason = "monotonic_anchor_behind"
        except BridgeActorNotReadyError as exc:
            reason = exc.reason
        except BridgeActorQuarantinedError as exc:
            reason = exc.reason
        except BridgeActorSchemaError as exc:
            reason = exc.reason
        except BridgeActorIntegrityError:
            reason = "sealed_state_integrity_failure"

        ok = reason == "ok"
        if ok:
            self._set_ready()
        elif reason in {
            "database_snapshot_rollback",
            "database_snapshot_divergence",
            "sealed_state_integrity_failure",
            "monotonic_anchor_missing",
        }:
            self._set_quarantined(reason)
        else:
            self._set_not_ready(reason)
        return AuditReport(
            ok=ok,
            reason=reason,
            schema_version=SCHEMA_VERSION,
            policy_version=self._policy.version,
            key_version=self._key_version,
            revision=revision,
            rows_verified=rows_verified,
            anchor_revision=anchor_revision,
            ready=self.ready,
            quarantined=self.quarantined,
        )


__all__ = [
    "ActorDecisionEvidence",
    "AnchorState",
    "AuditReport",
    "BridgeActorClockError",
    "BridgeActorClockRollbackError",
    "BridgeActorEnvelope",
    "BridgeActorEventReplayError",
    "BridgeActorFutureClockError",
    "BridgeActorIdentityError",
    "BridgeActorIdentityStore",
    "BridgeActorIntegrityError",
    "BridgeActorNotReadyError",
    "BridgeActorPolicy",
    "BridgeActorQuarantinedError",
    "BridgeActorSchemaError",
    "BridgeActorVerification",
    "ENVELOPE_VERSION",
    "EVIDENCE_VERSION",
    "GUILD_PARTICIPATION_ENABLED",
    "MIN_KEY_BYTES",
    "MonotonicAnchor",
    "SCHEMA_VERSION",
    "SQLiteMonotonicAnchor",
    "SUPPORTED_POLICY_VERSION",
    "SystemTrustedClock",
    "TrustedBridgeBoundary",
    "TrustedClock",
    "VOICE_ENABLED",
    "VerifiedGuestActor",
]
