"""Fail-closed consent ledger for private perception cloud egress.

The ledger is deliberately model-free and is not connected to HTTP, Discord,
or any model client. Its public mutation API accepts only an opaque operation
identifier, one code-owned route identifier, byte count, and transient payload
metadata used to derive a keyed HMAC. Raw operation ids, metadata, payloads,
paths, prompts, request content, URLs, and content digests are never persisted.

Trust is constructor-injected: a creator decision authority, immutable route
policy, trusted clock, seal-key version, and external monotonic anchor are all
required. Schema/key/policy/authority changes fail closed. Version-1 databases
are intentionally not migrated because their caller-asserted trust contract is
unsafe; they enter quarantine until an explicit offline migration is supplied.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit

from alpecca.db import connect
from config import DB_PATH


SCHEMA_VERSION = 2
CONTRACT_VERSION = 2
ANCHOR_FORMAT_VERSION = 1
MAX_PAYLOAD_METADATA_BYTES = 4096
MAX_TTL_SECONDS = 300
MAX_USES = 16
MAX_BYTES_PER_USE = 16 * 1024 * 1024
MAX_MODEL_IDENTIFIER_LENGTH = 160
MAINTENANCE_BATCH_SIZE = 8

_META_DOMAIN = "alpecca.egress-consent-meta.v2"
_GRANT_DOMAIN = "alpecca.egress-consent-grant.v2"
_RECEIPT_DOMAIN = "alpecca.egress-consent-receipt.v2"
_POLICY_DOMAIN = "alpecca.egress-consent-policy.v2"
_ROUTE_DOMAIN = "alpecca.egress-consent-route.v2"
_SCHEMA_MANIFEST_DOMAIN = "alpecca.egress-consent-schema-manifest.v2"
_TOKEN_DOMAIN = b"alpecca.egress-consent-token.v2"
_OPERATION_DOMAIN = b"alpecca.egress-consent-operation.v2"
_PAYLOAD_DOMAIN = b"alpecca.egress-consent-payload.v2"
_DECISION_DOMAIN = b"alpecca.egress-consent-decision.v2"
_ANCHOR_DOMAIN = "alpecca.egress-consent-external-anchor.v1"

_SAFE_ID_RE = re.compile(r"[a-z][a-z0-9._-]{1,79}\Z")
_MODEL_COMPONENT = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_MODEL_IDENTIFIER_RE = re.compile(
    rf"{_MODEL_COMPONENT}(?:/{_MODEL_COMPONENT})*(?::{_MODEL_COMPONENT})?\Z"
)
_URL_SCHEME_PREFIXES = ("http:", "https:", "ws:", "wss:", "ftp:", "file:", "data:")
_OPERATION_RE = re.compile(r"op_[A-Za-z0-9_-]{22,86}\Z")
_DECISION_RE = re.compile(r"decision_[A-Za-z0-9_-]{22,86}\Z")
_TOKEN_RE = re.compile(r"ec2_[A-Za-z0-9_-]{40,86}\Z")
_LEDGER_ID_RE = re.compile(r"ledger_[A-Za-z0-9_-]{22,86}\Z")
_CONSENT_ID_RE = re.compile(r"consent_[A-Za-z0-9_-]{22,86}\Z")
_RECEIPT_ID_RE = re.compile(r"receipt_[A-Za-z0-9_-]{22,86}\Z")
_HMAC_RE = re.compile(r"[0-9a-f]{64}\Z")
_EVENTS = frozenset({"grant", "deny", "use", "stop"})
_STATES = frozenset({"active", "stopped"})
_STOP_REASONS = frozenset({"expired", "server_restart", "use_cap_reached"})
_DENY_REASONS = frozenset({"creator_denied", "active_consent_exists"})
_UNKNOWN_ROUTE_IDENTITIES = frozenset(
    {"unknown", "unset", "default", "auto", "none"}
)
_SCHEMA_LOCK = threading.Lock()
_READ_ONLY_DEPENDENCY_NAMES = frozenset(
    {
        "db_path",
        "seal_key_version",
        "authority",
        "policy",
        "clock",
        "anchor",
        "_db_path",
        "_key",
        "_seal_key_version",
        "_authority",
        "_policy",
        "_clock",
        "_anchor",
        "_authority_id",
        "_authority_version",
        "_creator_scope",
        "_route_hmacs",
        "_policy_hmac",
        "_expected_schema_manifest_hmac",
    }
)

_META_TABLE = "egress_consent_meta"
_GRANTS_TABLE = "egress_consents"
_RECEIPTS_TABLE = "egress_consent_receipts"
_LEGACY_TABLES = frozenset(
    {"egress_consents", "egress_consent_receipts", "egress_consent_clock"}
)
_REQUIRED_TABLES = frozenset({_META_TABLE, _GRANTS_TABLE, _RECEIPTS_TABLE})
_REQUIRED_TRIGGERS = frozenset(
    {
        "egress_consent_meta_append_only",
        "egress_consent_meta_immutable_delete",
        "egress_consents_grant_immutable",
        "egress_consents_state_monotonic",
        "egress_consents_immutable_delete",
        "egress_consent_receipts_immutable_update",
        "egress_consent_receipts_immutable_delete",
    }
)
_REQUIRED_INDEXES = frozenset(
    {
        "egress_consents_one_active_operation_route",
        "egress_consents_expiry_idx",
        "egress_consent_one_grant",
        "egress_consent_one_stop",
        "egress_consent_use_ordinal",
        "egress_consent_decision_once",
    }
)

_EXPECTED_COLUMNS: Mapping[str, frozenset[str]] = {
    _META_TABLE: frozenset(
        {
            "singleton",
            "schema_version",
            "contract_version",
            "ledger_id",
            "seal_key_version",
            "policy_id",
            "policy_version",
            "policy_hmac",
            "schema_manifest_hmac",
            "authority_id",
            "authority_version",
            "creator_scope",
            "anchor_generation",
            "receipt_count",
            "receipt_head",
            "last_clock",
            "meta_seal",
        }
    ),
    _GRANTS_TABLE: frozenset(
        {
            "id",
            "consent_id",
            "contract_version",
            "schema_version",
            "seal_key_version",
            "policy_id",
            "policy_version",
            "authority_id",
            "authority_version",
            "creator_scope",
            "route_id",
            "destination_class",
            "route_hmac",
            "operation_hmac",
            "payload_hmac",
            "decision_hmac",
            "token_hmac",
            "byte_count",
            "issued_at",
            "expires_at",
            "ttl_seconds",
            "max_uses",
            "max_bytes_per_use",
            "uses",
            "last_used_at",
            "state",
            "stopped_at",
            "stop_reason",
            "grant_seal",
        }
    ),
    _RECEIPTS_TABLE: frozenset(
        {
            "receipt_sequence",
            "receipt_id",
            "consent_id",
            "contract_version",
            "schema_version",
            "seal_key_version",
            "policy_id",
            "policy_version",
            "authority_id",
            "authority_version",
            "creator_scope",
            "event",
            "route_id",
            "destination_class",
            "route_hmac",
            "operation_hmac",
            "payload_hmac",
            "decision_hmac",
            "byte_count",
            "issued_at",
            "expires_at",
            "ttl_seconds",
            "max_uses",
            "max_bytes_per_use",
            "use_ordinal",
            "occurred_at",
            "reason",
            "previous_seal",
            "receipt_seal",
        }
    ),
}


class EgressConsentError(ValueError):
    """Base error for invalid configuration or malformed operations."""


class EgressConsentDenied(EgressConsentError):
    """The operation is not authorized to egress."""

    def __init__(self, reason: str) -> None:
        self.reason = _reason(reason)
        super().__init__(self.reason.replace("_", " "))


class EgressConsentIntegrityError(EgressConsentError):
    """Persistent or externally anchored evidence did not verify."""

    def __init__(self, reason: str) -> None:
        self.reason = _reason(reason, fallback="integrity_failure")
        super().__init__(self.reason.replace("_", " "))


class EgressConsentQuarantined(EgressConsentDenied):
    """The ledger is not ready because a fail-closed check quarantined it."""


class ExternalAnchorError(EgressConsentError):
    """The required external monotonic anchor could not be verified or advanced."""


def _reason(value: object, *, fallback: str = "consent_denied") -> str:
    clean = str(value or "")
    if not clean or len(clean) > 80 or any(
        char not in "abcdefghijklmnopqrstuvwxyz0123456789_" for char in clean
    ):
        return fallback
    return clean


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
        raise EgressConsentError("evidence_not_canonical") from exc


def _safe_id(value: object, name: str) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise EgressConsentError(f"invalid_{name}")
    return value


def _model_identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= MAX_MODEL_IDENTIFIER_LENGTH
        or not value.isascii()
        or value.lower().startswith(_URL_SCHEME_PREFIXES)
        or _MODEL_IDENTIFIER_RE.fullmatch(value) is None
    ):
        raise EgressConsentError("invalid_model")
    return value


def _positive_int(value: object, name: str, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > maximum
    ):
        raise EgressConsentError(f"invalid_{name}")
    return value


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EgressConsentError(f"invalid_{name}")
    return value


def _timestamp(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EgressConsentError("invalid_trusted_clock")
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0:
        raise EgressConsentError("invalid_trusted_clock")
    return stamp


def _is_hmac(value: object, *, allow_empty: bool = False) -> bool:
    return bool((allow_empty and value == "") or (
        isinstance(value, str) and _HMAC_RE.fullmatch(value) is not None
    ))


def _opaque(value: object, regex: re.Pattern[str], name: str) -> str:
    if not isinstance(value, str) or regex.fullmatch(value) is None:
        raise EgressConsentError(f"invalid_{name}")
    return value


def _payload_metadata(value: object) -> bytes:
    if not isinstance(value, bytes) or not 1 <= len(value) <= MAX_PAYLOAD_METADATA_BYTES:
        raise EgressConsentError("invalid_payload_metadata")
    return value


def _https_route(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not 1 <= len(value) <= 512
        or value != value.strip()
    ):
        raise EgressConsentError("invalid_transport_route")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise EgressConsentError("invalid_transport_route") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname != parsed.hostname.lower()
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path.startswith("/")
        or parsed.query
        or parsed.fragment
        or any(part in {".", ".."} for part in parsed.path.split("/"))
    ):
        raise EgressConsentError("invalid_transport_route")
    return value


@dataclass(frozen=True, slots=True)
class AllowedEgressRoute:
    """One immutable, code-owned cloud transport route."""

    route_id: str
    provider: str
    deployment: str
    model: str
    capability: str
    purpose: str
    processing_location: str
    destination_class: str
    transport_route: str
    ttl_seconds: int = 60
    max_uses: int = 1
    max_bytes_per_use: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        for field_name in (
            "route_id",
            "provider",
            "deployment",
            "capability",
            "purpose",
            "processing_location",
            "destination_class",
        ):
            _safe_id(getattr(self, field_name), field_name)
        _model_identifier(self.model)
        if (
            self.provider in _UNKNOWN_ROUTE_IDENTITIES
            or self.deployment in _UNKNOWN_ROUTE_IDENTITIES
            or self.model in _UNKNOWN_ROUTE_IDENTITIES
        ):
            raise EgressConsentError("unknown_route_identity")
        _https_route(self.transport_route)
        _positive_int(self.ttl_seconds, "ttl_seconds", MAX_TTL_SECONDS)
        _positive_int(self.max_uses, "max_uses", MAX_USES)
        _positive_int(
            self.max_bytes_per_use, "max_bytes_per_use", MAX_BYTES_PER_USE
        )

    def material(self) -> dict[str, object]:
        return {
            "route_id": self.route_id,
            "provider": self.provider,
            "deployment": self.deployment,
            "model": self.model,
            "capability": self.capability,
            "purpose": self.purpose,
            "processing_location": self.processing_location,
            "destination_class": self.destination_class,
            "transport_route": self.transport_route,
            "ttl_seconds": self.ttl_seconds,
            "max_uses": self.max_uses,
            "max_bytes_per_use": self.max_bytes_per_use,
        }


@dataclass(frozen=True, slots=True)
class EgressPolicy:
    """Immutable exact-route allowlist supplied by trusted server code."""

    policy_id: str
    version: int
    routes: tuple[AllowedEgressRoute, ...]
    _routes_by_id: Mapping[str, AllowedEgressRoute] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        _safe_id(self.policy_id, "policy_id")
        _positive_int(self.version, "policy_version", 2**31 - 1)
        if not isinstance(self.routes, tuple) or not self.routes:
            raise EgressConsentError("invalid_route_allowlist")
        by_id: dict[str, AllowedEgressRoute] = {}
        for route in self.routes:
            if not isinstance(route, AllowedEgressRoute):
                raise EgressConsentError("invalid_route_allowlist")
            if route.route_id in by_id:
                raise EgressConsentError("duplicate_route_id")
            by_id[route.route_id] = route
        object.__setattr__(self, "_routes_by_id", MappingProxyType(by_id))

    def resolve(self, route_id: object) -> AllowedEgressRoute:
        clean = _safe_id(route_id, "route_id")
        route = self._routes_by_id.get(clean)
        if route is None:
            raise EgressConsentDenied("route_not_allowed")
        return route

    def material(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "routes": [
                route.material()
                for route in sorted(self.routes, key=lambda item: item.route_id)
            ],
        }


@dataclass(frozen=True, slots=True)
class AuthorityRequest:
    """Content-free decision request sent only to the injected authority."""

    action: str
    route_id: str
    provider: str
    deployment: str
    model: str
    capability: str
    purpose: str
    processing_location: str
    destination_class: str
    transport_route: str
    operation_hmac: str
    payload_hmac: str
    byte_count: int
    ttl_seconds: int
    max_uses: int
    max_bytes_per_use: int


@dataclass(frozen=True, slots=True)
class CreatorDecision:
    decision_id: str
    allowed: bool


class CreatorConsentAuthority(Protocol):
    authority_id: str
    version: int
    creator_scope: str

    def decide(self, request: AuthorityRequest) -> CreatorDecision: ...


class TrustedClock(Protocol):
    def now(self) -> float: ...


@dataclass(frozen=True, slots=True)
class AnchorState:
    ledger_id: str
    generation: int
    receipt_count: int
    receipt_head: str
    schema_version: int
    seal_key_version: str
    policy_id: str
    policy_version: int
    policy_hmac: str
    schema_manifest_hmac: str
    authority_id: str
    authority_version: int
    creator_scope: str
    last_clock: float


class MonotonicAnchor(Protocol):
    def load(self) -> AnchorState | None: ...

    def initialize(self, state: AnchorState) -> None: ...

    def advance(self, expected: AnchorState, updated: AnchorState) -> None: ...


def _anchor_material(state: AnchorState) -> dict[str, object]:
    return {
        "ledger_id": state.ledger_id,
        "generation": state.generation,
        "receipt_count": state.receipt_count,
        "receipt_head": state.receipt_head,
        "schema_version": state.schema_version,
        "seal_key_version": state.seal_key_version,
        "policy_id": state.policy_id,
        "policy_version": state.policy_version,
        "policy_hmac": state.policy_hmac,
        "schema_manifest_hmac": state.schema_manifest_hmac,
        "authority_id": state.authority_id,
        "authority_version": state.authority_version,
        "creator_scope": state.creator_scope,
        "last_clock": state.last_clock,
    }


def _validate_anchor_state(state: object) -> AnchorState:
    if not isinstance(state, AnchorState):
        raise ExternalAnchorError("invalid_anchor_state")
    _opaque(state.ledger_id, _LEDGER_ID_RE, "ledger_id")
    _nonnegative_int(state.generation, "anchor_generation")
    _nonnegative_int(state.receipt_count, "receipt_count")
    if state.receipt_count == 0:
        if state.receipt_head:
            raise ExternalAnchorError("invalid_anchor_head")
    elif not _is_hmac(state.receipt_head):
        raise ExternalAnchorError("invalid_anchor_head")
    if state.schema_version != SCHEMA_VERSION:
        raise ExternalAnchorError("anchor_schema_mismatch")
    _safe_id(state.seal_key_version, "seal_key_version")
    _safe_id(state.policy_id, "policy_id")
    _positive_int(state.policy_version, "policy_version", 2**31 - 1)
    if not _is_hmac(state.policy_hmac):
        raise ExternalAnchorError("invalid_anchor_policy")
    if not _is_hmac(state.schema_manifest_hmac):
        raise ExternalAnchorError("invalid_anchor_schema_manifest")
    _safe_id(state.authority_id, "authority_id")
    _positive_int(state.authority_version, "authority_version", 2**31 - 1)
    _safe_id(state.creator_scope, "creator_scope")
    _timestamp(state.last_clock)
    return state


class SQLiteMonotonicAnchor:
    """HMAC-sealed SQLite sidecar kept outside the main DB snapshot domain."""

    def __init__(
        self,
        path: Path,
        *,
        anchor_key: bytes | bytearray | memoryview | str,
        anchor_key_version: str,
    ) -> None:
        self.path = Path(path)
        if isinstance(anchor_key, str):
            anchor_key = anchor_key.encode("utf-8")
        if not isinstance(anchor_key, (bytes, bytearray, memoryview)):
            raise TypeError("anchor_key must be bytes or text")
        self._key = bytes(anchor_key)
        if not self._key:
            raise ValueError("anchor_key must not be empty")
        self.anchor_key_version = _safe_id(
            anchor_key_version, "anchor_key_version"
        )
        self._ensure_schema()

    def _seal(self, state: AnchorState) -> str:
        material = {
            "format_version": ANCHOR_FORMAT_VERSION,
            "anchor_key_version": self.anchor_key_version,
            **_anchor_material(state),
        }
        return hmac.new(
            self._key,
            _canonical({"domain": _ANCHOR_DOMAIN, **material}).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _ensure_schema(self) -> None:
        with connect(self.path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS egress_monotonic_anchor (
                    singleton           INTEGER PRIMARY KEY CHECK(singleton=1),
                    format_version      INTEGER NOT NULL CHECK(format_version=1),
                    anchor_key_version  TEXT NOT NULL,
                    ledger_id           TEXT NOT NULL,
                    generation          INTEGER NOT NULL CHECK(generation>=0),
                    receipt_count       INTEGER NOT NULL CHECK(receipt_count>=0),
                    receipt_head        TEXT NOT NULL,
                    schema_version      INTEGER NOT NULL,
                    seal_key_version    TEXT NOT NULL,
                    policy_id           TEXT NOT NULL,
                    policy_version      INTEGER NOT NULL,
                    policy_hmac         TEXT NOT NULL,
                    schema_manifest_hmac TEXT NOT NULL,
                    authority_id        TEXT NOT NULL,
                    authority_version   INTEGER NOT NULL,
                    creator_scope       TEXT NOT NULL,
                    last_clock          REAL NOT NULL,
                    anchor_seal         TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS egress_monotonic_anchor_forward_only
                BEFORE UPDATE ON egress_monotonic_anchor
                WHEN NEW.generation != OLD.generation + 1
                  OR NEW.receipt_count < OLD.receipt_count
                  OR NEW.last_clock < OLD.last_clock
                  OR NEW.ledger_id != OLD.ledger_id
                BEGIN
                    SELECT RAISE(ABORT, 'external anchor is not monotonic');
                END;
                CREATE TRIGGER IF NOT EXISTS egress_monotonic_anchor_no_delete
                BEFORE DELETE ON egress_monotonic_anchor
                BEGIN
                    SELECT RAISE(ABORT, 'external anchor is immutable evidence');
                END;
                """
            )

    def _decode(self, row: sqlite3.Row) -> AnchorState:
        try:
            if int(row["format_version"]) != ANCHOR_FORMAT_VERSION:
                raise ExternalAnchorError("anchor_format_mismatch")
            if str(row["anchor_key_version"]) != self.anchor_key_version:
                raise ExternalAnchorError("anchor_key_version_mismatch")
            state = AnchorState(
                ledger_id=str(row["ledger_id"]),
                generation=int(row["generation"]),
                receipt_count=int(row["receipt_count"]),
                receipt_head=str(row["receipt_head"]),
                schema_version=int(row["schema_version"]),
                seal_key_version=str(row["seal_key_version"]),
                policy_id=str(row["policy_id"]),
                policy_version=int(row["policy_version"]),
                policy_hmac=str(row["policy_hmac"]),
                schema_manifest_hmac=str(row["schema_manifest_hmac"]),
                authority_id=str(row["authority_id"]),
                authority_version=int(row["authority_version"]),
                creator_scope=str(row["creator_scope"]),
                last_clock=float(row["last_clock"]),
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ExternalAnchorError("invalid_anchor_state") from exc
        _validate_anchor_state(state)
        if not hmac.compare_digest(self._seal(state), str(row["anchor_seal"])):
            raise ExternalAnchorError("anchor_seal_invalid")
        return state

    def load(self) -> AnchorState | None:
        with connect(self.path) as conn:
            row = conn.execute(
                "SELECT * FROM egress_monotonic_anchor WHERE singleton=1"
            ).fetchone()
        return None if row is None else self._decode(row)

    def initialize(self, state: AnchorState) -> None:
        _validate_anchor_state(state)
        with connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM egress_monotonic_anchor WHERE singleton=1"
            ).fetchone() is not None:
                raise ExternalAnchorError("anchor_already_initialized")
            material = _anchor_material(state)
            conn.execute(
                """
                INSERT INTO egress_monotonic_anchor
                    (singleton,format_version,anchor_key_version,ledger_id,
                     generation,receipt_count,receipt_head,schema_version,
                     seal_key_version,policy_id,policy_version,policy_hmac,
                     schema_manifest_hmac,authority_id,authority_version,
                     creator_scope,last_clock,anchor_seal)
                VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    ANCHOR_FORMAT_VERSION,
                    self.anchor_key_version,
                    material["ledger_id"],
                    material["generation"],
                    material["receipt_count"],
                    material["receipt_head"],
                    material["schema_version"],
                    material["seal_key_version"],
                    material["policy_id"],
                    material["policy_version"],
                    material["policy_hmac"],
                    material["schema_manifest_hmac"],
                    material["authority_id"],
                    material["authority_version"],
                    material["creator_scope"],
                    material["last_clock"],
                    self._seal(state),
                ),
            )

    def advance(self, expected: AnchorState, updated: AnchorState) -> None:
        _validate_anchor_state(expected)
        _validate_anchor_state(updated)
        if (
            updated.ledger_id != expected.ledger_id
            or updated.generation != expected.generation + 1
            or updated.receipt_count < expected.receipt_count
            or updated.last_clock < expected.last_clock
        ):
            raise ExternalAnchorError("anchor_advance_invalid")
        with connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM egress_monotonic_anchor WHERE singleton=1"
            ).fetchone()
            if row is None or self._decode(row) != expected:
                raise ExternalAnchorError("anchor_compare_and_swap_failed")
            material = _anchor_material(updated)
            changed = conn.execute(
                """
                UPDATE egress_monotonic_anchor
                SET generation=?,receipt_count=?,receipt_head=?,schema_version=?,
                    seal_key_version=?,policy_id=?,policy_version=?,policy_hmac=?,
                    schema_manifest_hmac=?,authority_id=?,authority_version=?,
                    creator_scope=?,last_clock=?,anchor_seal=?
                WHERE singleton=1 AND generation=? AND receipt_head=?
                """,
                (
                    material["generation"],
                    material["receipt_count"],
                    material["receipt_head"],
                    material["schema_version"],
                    material["seal_key_version"],
                    material["policy_id"],
                    material["policy_version"],
                    material["policy_hmac"],
                    material["schema_manifest_hmac"],
                    material["authority_id"],
                    material["authority_version"],
                    material["creator_scope"],
                    material["last_clock"],
                    self._seal(updated),
                    expected.generation,
                    expected.receipt_head,
                ),
            )
            if changed.rowcount != 1:
                raise ExternalAnchorError("anchor_compare_and_swap_failed")


class EgressConsentLedger:
    """Provider/deployment/model-specific private-egress consent ledger."""

    __slots__ = (
        "_db_path",
        "_key",
        "_seal_key_version",
        "_authority",
        "_policy",
        "_clock",
        "_anchor",
        "_authority_id",
        "_authority_version",
        "_creator_scope",
        "_route_hmacs",
        "_policy_hmac",
        "_expected_schema_manifest_hmac",
        "_state_lock",
        "_ready",
        "_quarantine_reason",
    )

    def __setattr__(self, name: str, value: object) -> None:
        if name in _READ_ONLY_DEPENDENCY_NAMES and (
            name in {"db_path", "seal_key_version", "authority", "policy", "clock", "anchor"}
            or hasattr(self, name)
        ):
            raise AttributeError(f"{name} is read-only")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if name in _READ_ONLY_DEPENDENCY_NAMES:
            raise AttributeError(f"{name} is read-only")
        object.__delattr__(self, name)

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        seal_key: bytes | bytearray | memoryview | str,
        seal_key_version: str,
        authority: CreatorConsentAuthority,
        policy: EgressPolicy,
        clock: TrustedClock,
        anchor: MonotonicAnchor,
    ) -> None:
        self._db_path = Path(db_path)
        if isinstance(seal_key, str):
            seal_key = seal_key.encode("utf-8")
        if not isinstance(seal_key, (bytes, bytearray, memoryview)):
            raise TypeError("seal_key must be bytes or text")
        self._key = bytes(seal_key)
        if not self._key:
            raise ValueError("seal_key must not be empty")
        self._seal_key_version = _safe_id(
            seal_key_version, "seal_key_version"
        )
        if not isinstance(policy, EgressPolicy):
            raise TypeError("policy must be EgressPolicy")
        self._policy = policy
        self._authority = authority
        self._clock = clock
        self._anchor = anchor
        if not callable(getattr(authority, "decide", None)):
            raise TypeError("authority must provide decide()")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock must provide now()")
        for method in ("load", "initialize", "advance"):
            if not callable(getattr(anchor, method, None)):
                raise TypeError(f"anchor must provide {method}()")
        self._authority_id = _safe_id(
            getattr(authority, "authority_id", None), "authority_id"
        )
        self._authority_version = _positive_int(
            getattr(authority, "version", None), "authority_version", 2**31 - 1
        )
        self._creator_scope = _safe_id(
            getattr(authority, "creator_scope", None), "creator_scope"
        )
        if isinstance(anchor, SQLiteMonotonicAnchor):
            if anchor.path.resolve() == self._db_path.resolve():
                raise EgressConsentError("anchor_must_be_external")

        self._route_hmacs = MappingProxyType(
            {
                route.route_id: self._seal(_ROUTE_DOMAIN, route.material())
                for route in policy.routes
            }
        )
        self._policy_hmac = self._seal(_POLICY_DOMAIN, policy.material())
        self._expected_schema_manifest_hmac = (
            self._build_expected_schema_manifest_hmac()
        )
        self._state_lock = threading.Lock()
        self._ready = False
        self._quarantine_reason = ""
        self._bootstrap()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def seal_key_version(self) -> str:
        return self._seal_key_version

    @property
    def authority(self) -> CreatorConsentAuthority:
        return self._authority

    @property
    def policy(self) -> EgressPolicy:
        return self._policy

    @property
    def clock(self) -> TrustedClock:
        return self._clock

    @property
    def anchor(self) -> MonotonicAnchor:
        return self._anchor

    @property
    def ready(self) -> bool:
        with self._state_lock:
            return self._ready and not self._quarantine_reason

    @property
    def quarantined(self) -> bool:
        with self._state_lock:
            return bool(self._quarantine_reason)

    @property
    def quarantine_reason(self) -> str:
        with self._state_lock:
            return self._quarantine_reason

    def _set_ready(self) -> None:
        with self._state_lock:
            if not self._quarantine_reason:
                self._ready = True

    def _quarantine(self, reason: str) -> None:
        with self._state_lock:
            self._ready = False
            if not self._quarantine_reason:
                self._quarantine_reason = _reason(
                    reason, fallback="integrity_failure"
                )

    def _require_ready(self) -> None:
        if not self.ready:
            raise EgressConsentQuarantined(
                self.quarantine_reason or "recovery_not_ready"
            )

    def _hmac(self, domain: bytes, value: str) -> str:
        return hmac.new(
            self._key, domain + b"\x00" + value.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _seal(self, domain: str, value: Mapping[str, object]) -> str:
        return hmac.new(
            self._key,
            _canonical({"domain": domain, **dict(value)}).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _token_hmac(self, token: object) -> str:
        if not isinstance(token, str) or _TOKEN_RE.fullmatch(token) is None:
            return self._hmac(_TOKEN_DOMAIN, "invalid")
        return self._hmac(_TOKEN_DOMAIN, token)

    def _operation_hmac(self, operation_id: object) -> str:
        clean = _opaque(operation_id, _OPERATION_RE, "operation_id")
        return self._hmac(_OPERATION_DOMAIN, clean)

    def _decision_hmac(self, decision_id: object) -> str:
        clean = _opaque(decision_id, _DECISION_RE, "decision_id")
        return self._hmac(_DECISION_DOMAIN, clean)

    def _payload_binding_hmac(
        self,
        *,
        operation_hmac: str,
        route_hmac: str,
        byte_count: int,
        payload_metadata: bytes,
    ) -> str:
        prefix = _canonical(
            {
                "operation_hmac": operation_hmac,
                "route_hmac": route_hmac,
                "byte_count": byte_count,
            }
        ).encode("ascii")
        return hmac.new(
            self._key,
            _PAYLOAD_DOMAIN + b"\x00" + prefix + b"\x00" + payload_metadata,
            hashlib.sha256,
        ).hexdigest()

    def _trusted_now(self, meta: sqlite3.Row | None = None) -> float:
        try:
            stamp = _timestamp(self.clock.now())
        except EgressConsentError:
            raise
        except Exception as exc:
            raise EgressConsentIntegrityError("trusted_clock_unavailable") from exc
        if meta is not None and stamp < float(meta["last_clock"]):
            raise EgressConsentIntegrityError("trusted_clock_rollback")
        return stamp

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE egress_consent_meta (
                singleton             INTEGER PRIMARY KEY CHECK(singleton=1),
                schema_version        INTEGER NOT NULL CHECK(schema_version=2),
                contract_version      INTEGER NOT NULL CHECK(contract_version=2),
                ledger_id             TEXT NOT NULL,
                seal_key_version      TEXT NOT NULL,
                policy_id             TEXT NOT NULL,
                policy_version        INTEGER NOT NULL,
                policy_hmac           TEXT NOT NULL CHECK(length(policy_hmac)=64),
                schema_manifest_hmac  TEXT NOT NULL CHECK(length(schema_manifest_hmac)=64),
                authority_id          TEXT NOT NULL,
                authority_version     INTEGER NOT NULL,
                creator_scope         TEXT NOT NULL,
                anchor_generation     INTEGER NOT NULL CHECK(anchor_generation>=0),
                receipt_count         INTEGER NOT NULL CHECK(receipt_count>=0),
                receipt_head          TEXT NOT NULL,
                last_clock            REAL NOT NULL,
                meta_seal             TEXT NOT NULL CHECK(length(meta_seal)=64),
                CHECK((receipt_count=0 AND receipt_head='')
                    OR (receipt_count>0 AND length(receipt_head)=64))
            );

            CREATE TABLE egress_consents (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                consent_id            TEXT NOT NULL UNIQUE,
                contract_version      INTEGER NOT NULL CHECK(contract_version=2),
                schema_version        INTEGER NOT NULL CHECK(schema_version=2),
                seal_key_version      TEXT NOT NULL,
                policy_id             TEXT NOT NULL,
                policy_version        INTEGER NOT NULL,
                authority_id          TEXT NOT NULL,
                authority_version     INTEGER NOT NULL,
                creator_scope         TEXT NOT NULL,
                route_id              TEXT NOT NULL,
                destination_class     TEXT NOT NULL,
                route_hmac            TEXT NOT NULL CHECK(length(route_hmac)=64),
                operation_hmac        TEXT NOT NULL CHECK(length(operation_hmac)=64),
                payload_hmac          TEXT NOT NULL CHECK(length(payload_hmac)=64),
                decision_hmac         TEXT NOT NULL CHECK(length(decision_hmac)=64),
                token_hmac            TEXT NOT NULL UNIQUE CHECK(length(token_hmac)=64),
                byte_count            INTEGER NOT NULL CHECK(byte_count>0),
                issued_at             REAL NOT NULL,
                expires_at            REAL NOT NULL,
                ttl_seconds           INTEGER NOT NULL CHECK(ttl_seconds BETWEEN 1 AND 300),
                max_uses              INTEGER NOT NULL CHECK(max_uses BETWEEN 1 AND 16),
                max_bytes_per_use     INTEGER NOT NULL CHECK(max_bytes_per_use BETWEEN 1 AND 16777216),
                uses                  INTEGER NOT NULL DEFAULT 0 CHECK(uses>=0 AND uses<=max_uses),
                last_used_at          REAL,
                state                 TEXT NOT NULL CHECK(state IN ('active','stopped')),
                stopped_at            REAL,
                stop_reason           TEXT NOT NULL DEFAULT '',
                grant_seal            TEXT NOT NULL CHECK(length(grant_seal)=64),
                CHECK((uses=0 AND last_used_at IS NULL)
                    OR (uses>0 AND last_used_at IS NOT NULL)),
                CHECK((state='active' AND uses<max_uses AND stopped_at IS NULL AND stop_reason='')
                    OR (state='stopped' AND stopped_at IS NOT NULL
                        AND stop_reason IN ('expired','server_restart','use_cap_reached')))
            );
            CREATE UNIQUE INDEX egress_consents_one_active_operation_route
            ON egress_consents(operation_hmac,route_id) WHERE state='active';
            CREATE INDEX egress_consents_expiry_idx
            ON egress_consents(state,expires_at);

            CREATE TABLE egress_consent_receipts (
                receipt_sequence      INTEGER PRIMARY KEY,
                receipt_id            TEXT NOT NULL UNIQUE,
                consent_id            TEXT,
                contract_version      INTEGER NOT NULL CHECK(contract_version=2),
                schema_version        INTEGER NOT NULL CHECK(schema_version=2),
                seal_key_version      TEXT NOT NULL,
                policy_id             TEXT NOT NULL,
                policy_version        INTEGER NOT NULL,
                authority_id          TEXT NOT NULL,
                authority_version     INTEGER NOT NULL,
                creator_scope         TEXT NOT NULL,
                event                 TEXT NOT NULL CHECK(event IN ('grant','deny','use','stop')),
                route_id              TEXT NOT NULL,
                destination_class     TEXT NOT NULL,
                route_hmac            TEXT NOT NULL CHECK(length(route_hmac)=64),
                operation_hmac        TEXT NOT NULL CHECK(length(operation_hmac)=64),
                payload_hmac          TEXT NOT NULL CHECK(length(payload_hmac)=64),
                decision_hmac         TEXT NOT NULL CHECK(length(decision_hmac)=64),
                byte_count            INTEGER NOT NULL CHECK(byte_count>0),
                issued_at             REAL NOT NULL,
                expires_at            REAL NOT NULL,
                ttl_seconds           INTEGER NOT NULL CHECK(ttl_seconds BETWEEN 1 AND 300),
                max_uses              INTEGER NOT NULL CHECK(max_uses BETWEEN 1 AND 16),
                max_bytes_per_use     INTEGER NOT NULL CHECK(max_bytes_per_use BETWEEN 1 AND 16777216),
                use_ordinal           INTEGER,
                occurred_at           REAL NOT NULL,
                reason                TEXT NOT NULL,
                previous_seal         TEXT NOT NULL,
                receipt_seal          TEXT NOT NULL CHECK(length(receipt_seal)=64),
                FOREIGN KEY(consent_id) REFERENCES egress_consents(consent_id)
                    ON DELETE RESTRICT,
                CHECK((event='deny' AND consent_id IS NULL)
                    OR (event IN ('grant','use','stop') AND consent_id IS NOT NULL)),
                CHECK((event='use' AND use_ordinal IS NOT NULL AND use_ordinal>0)
                    OR (event!='use' AND use_ordinal IS NULL))
            );
            CREATE UNIQUE INDEX egress_consent_one_grant
            ON egress_consent_receipts(consent_id) WHERE event='grant';
            CREATE UNIQUE INDEX egress_consent_one_stop
            ON egress_consent_receipts(consent_id) WHERE event='stop';
            CREATE UNIQUE INDEX egress_consent_use_ordinal
            ON egress_consent_receipts(consent_id,use_ordinal) WHERE event='use';
            CREATE UNIQUE INDEX egress_consent_decision_once
            ON egress_consent_receipts(decision_hmac) WHERE event IN ('grant','deny');

            CREATE TRIGGER egress_consent_meta_append_only
            BEFORE UPDATE ON egress_consent_meta
            WHEN
                NEW.schema_version != OLD.schema_version
                OR NEW.contract_version != OLD.contract_version
                OR NEW.ledger_id != OLD.ledger_id
                OR NEW.seal_key_version != OLD.seal_key_version
                OR NEW.policy_id != OLD.policy_id
                OR NEW.policy_version != OLD.policy_version
                OR NEW.policy_hmac != OLD.policy_hmac
                OR NEW.schema_manifest_hmac != OLD.schema_manifest_hmac
                OR NEW.authority_id != OLD.authority_id
                OR NEW.authority_version != OLD.authority_version
                OR NEW.creator_scope != OLD.creator_scope
                OR NEW.last_clock < OLD.last_clock
                OR NOT (
                    (NEW.anchor_generation=OLD.anchor_generation
                        AND NEW.receipt_count=OLD.receipt_count+1
                        AND NEW.last_clock=OLD.last_clock)
                    OR
                    (NEW.anchor_generation=OLD.anchor_generation+1
                        AND NEW.receipt_count=OLD.receipt_count
                        AND NEW.receipt_head=OLD.receipt_head)
                )
            BEGIN
                SELECT RAISE(ABORT, 'egress consent metadata is not monotonic');
            END;
            CREATE TRIGGER egress_consent_meta_immutable_delete
            BEFORE DELETE ON egress_consent_meta
            BEGIN
                SELECT RAISE(ABORT, 'egress consent metadata is immutable');
            END;

            CREATE TRIGGER egress_consents_grant_immutable
            BEFORE UPDATE OF
                consent_id,contract_version,schema_version,seal_key_version,
                policy_id,policy_version,authority_id,authority_version,
                creator_scope,route_id,destination_class,route_hmac,
                operation_hmac,payload_hmac,decision_hmac,token_hmac,byte_count,
                issued_at,expires_at,ttl_seconds,max_uses,max_bytes_per_use,grant_seal
            ON egress_consents
            BEGIN
                SELECT RAISE(ABORT, 'egress consent grant is immutable');
            END;
            CREATE TRIGGER egress_consents_state_monotonic
            BEFORE UPDATE OF uses,last_used_at,state,stopped_at,stop_reason
            ON egress_consents
            WHEN
                NEW.uses < OLD.uses OR NEW.uses > OLD.uses+1
                OR (NEW.uses=OLD.uses AND NEW.last_used_at IS NOT OLD.last_used_at)
                OR (NEW.uses=OLD.uses+1 AND
                    (NEW.last_used_at IS NULL
                     OR NEW.last_used_at<COALESCE(OLD.last_used_at,OLD.issued_at)))
                OR (OLD.state='stopped' AND
                    (NEW.uses!=OLD.uses OR NEW.last_used_at IS NOT OLD.last_used_at
                     OR NEW.state!=OLD.state OR NEW.stopped_at IS NOT OLD.stopped_at
                     OR NEW.stop_reason!=OLD.stop_reason))
                OR (NEW.state='active' AND
                    (NEW.uses>=NEW.max_uses OR NEW.stopped_at IS NOT NULL OR NEW.stop_reason!=''))
                OR (NEW.state='stopped' AND
                    (NEW.stopped_at IS NULL OR NEW.stopped_at<NEW.issued_at
                     OR NEW.stop_reason NOT IN ('expired','server_restart','use_cap_reached')))
            BEGIN
                SELECT RAISE(ABORT, 'egress consent state is not monotonic');
            END;
            CREATE TRIGGER egress_consents_immutable_delete
            BEFORE DELETE ON egress_consents
            BEGIN
                SELECT RAISE(ABORT, 'egress consents are immutable evidence');
            END;
            CREATE TRIGGER egress_consent_receipts_immutable_update
            BEFORE UPDATE ON egress_consent_receipts
            BEGIN
                SELECT RAISE(ABORT, 'egress consent receipts are immutable');
            END;
            CREATE TRIGGER egress_consent_receipts_immutable_delete
            BEFORE DELETE ON egress_consent_receipts
            BEGIN
                SELECT RAISE(ABORT, 'egress consent receipts are immutable');
            END;
            """
        )

    def _schema_names(self, conn: sqlite3.Connection, object_type: str) -> set[str]:
        return {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type=?", (object_type,)
            ).fetchall()
        }

    @staticmethod
    def _normalize_schema_sql(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise EgressConsentIntegrityError("schema_manifest_invalid")
        return " ".join(value.strip().rstrip(";").split())

    def _schema_manifest_material(
        self, conn: sqlite3.Connection
    ) -> dict[str, object]:
        required = {
            "table": _REQUIRED_TABLES,
            "index": _REQUIRED_INDEXES,
            "trigger": _REQUIRED_TRIGGERS,
        }
        objects: list[dict[str, str]] = []
        for object_type, names in required.items():
            rows = conn.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE type=? "
                "ORDER BY name",
                (object_type,),
            ).fetchall()
            selected = [row for row in rows if str(row["name"]) in names]
            if {str(row["name"]) for row in selected} != set(names):
                raise EgressConsentIntegrityError("schema_manifest_invalid")
            for row in selected:
                objects.append(
                    {
                        "type": object_type,
                        "name": str(row["name"]),
                        "sql": self._normalize_schema_sql(row["sql"]),
                    }
                )
        objects.sort(key=lambda item: (item["type"], item["name"]))
        return {
            "schema_version": SCHEMA_VERSION,
            "objects": objects,
        }

    def _schema_manifest_hmac(self, conn: sqlite3.Connection) -> str:
        return self._seal(
            _SCHEMA_MANIFEST_DOMAIN, self._schema_manifest_material(conn)
        )

    def _build_expected_schema_manifest_hmac(self) -> str:
        memory = sqlite3.connect(":memory:")
        memory.row_factory = sqlite3.Row
        try:
            self._create_schema(memory)
            return self._schema_manifest_hmac(memory)
        finally:
            memory.close()

    def _verify_schema_manifest(
        self, conn: sqlite3.Connection, meta: sqlite3.Row
    ) -> None:
        actual = self._schema_manifest_hmac(conn)
        stored = str(meta["schema_manifest_hmac"])
        if (
            not hmac.compare_digest(actual, self._expected_schema_manifest_hmac)
            or not hmac.compare_digest(stored, self._expected_schema_manifest_hmac)
        ):
            raise EgressConsentIntegrityError("schema_manifest_mismatch")

    def _verify_schema_objects(self, conn: sqlite3.Connection) -> None:
        tables = self._schema_names(conn, "table")
        owned_tables = {
            name for name in tables if name.startswith("egress_consent")
        }
        placeholders = ",".join("?" for _name in _REQUIRED_TABLES)
        table_names = tuple(sorted(_REQUIRED_TABLES))
        triggers = {
            str(row["name"])
            for row in conn.execute(
                f"SELECT name FROM sqlite_master WHERE type='trigger' "
                f"AND tbl_name IN ({placeholders})",
                table_names,
            ).fetchall()
        }
        indexes = {
            str(row["name"])
            for row in conn.execute(
                f"SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL "
                f"AND tbl_name IN ({placeholders})",
                table_names,
            ).fetchall()
        }
        if (
            owned_tables != set(_REQUIRED_TABLES)
            or triggers != set(_REQUIRED_TRIGGERS)
            or indexes != set(_REQUIRED_INDEXES)
        ):
            raise EgressConsentIntegrityError("unsupported_schema")
        for table, expected in _EXPECTED_COLUMNS.items():
            actual = {
                str(row["name"])
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if actual != expected:
                raise EgressConsentIntegrityError("unsupported_schema")

    @staticmethod
    def _meta_row(conn: sqlite3.Connection) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM egress_consent_meta WHERE singleton=1"
        ).fetchone()

    @staticmethod
    def _meta_material(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "schema_version": int(row["schema_version"]),
            "contract_version": int(row["contract_version"]),
            "ledger_id": str(row["ledger_id"]),
            "seal_key_version": str(row["seal_key_version"]),
            "policy_id": str(row["policy_id"]),
            "policy_version": int(row["policy_version"]),
            "policy_hmac": str(row["policy_hmac"]),
            "schema_manifest_hmac": str(row["schema_manifest_hmac"]),
            "authority_id": str(row["authority_id"]),
            "authority_version": int(row["authority_version"]),
            "creator_scope": str(row["creator_scope"]),
            "anchor_generation": int(row["anchor_generation"]),
            "receipt_count": int(row["receipt_count"]),
            "receipt_head": str(row["receipt_head"]),
            "last_clock": float(row["last_clock"]),
        }

    def _verify_meta(self, row: sqlite3.Row | None) -> sqlite3.Row:
        if row is None:
            raise EgressConsentIntegrityError("metadata_missing")
        try:
            material = self._meta_material(row)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise EgressConsentIntegrityError("metadata_invalid") from exc
        if material["schema_version"] != SCHEMA_VERSION:
            raise EgressConsentIntegrityError("unsupported_schema")
        if material["contract_version"] != CONTRACT_VERSION:
            raise EgressConsentIntegrityError("contract_version_mismatch")
        if material["seal_key_version"] != self.seal_key_version:
            raise EgressConsentIntegrityError("seal_key_version_mismatch")
        if not _LEDGER_ID_RE.fullmatch(material["ledger_id"]):
            raise EgressConsentIntegrityError("metadata_invalid")
        if not hmac.compare_digest(
            self._seal(_META_DOMAIN, material), str(row["meta_seal"])
        ):
            raise EgressConsentIntegrityError("metadata_seal_invalid")
        if (
            material["policy_id"] != self.policy.policy_id
            or material["policy_version"] != self.policy.version
            or not hmac.compare_digest(material["policy_hmac"], self._policy_hmac)
        ):
            raise EgressConsentIntegrityError("policy_version_mismatch")
        if not hmac.compare_digest(
            material["schema_manifest_hmac"],
            self._expected_schema_manifest_hmac,
        ):
            raise EgressConsentIntegrityError("schema_manifest_mismatch")
        if (
            material["authority_id"] != self._authority_id
            or material["authority_version"] != self._authority_version
            or material["creator_scope"] != self._creator_scope
        ):
            raise EgressConsentIntegrityError("authority_version_mismatch")
        if material["anchor_generation"] < 0 or material["receipt_count"] < 0:
            raise EgressConsentIntegrityError("metadata_invalid")
        if material["receipt_count"] == 0:
            if material["receipt_head"]:
                raise EgressConsentIntegrityError("metadata_invalid")
        elif not _is_hmac(material["receipt_head"]):
            raise EgressConsentIntegrityError("metadata_invalid")
        _timestamp(material["last_clock"])
        return row

    def _anchor_state(self, meta: Mapping[str, object]) -> AnchorState:
        return AnchorState(
            ledger_id=str(meta["ledger_id"]),
            generation=int(meta["anchor_generation"]),
            receipt_count=int(meta["receipt_count"]),
            receipt_head=str(meta["receipt_head"]),
            schema_version=int(meta["schema_version"]),
            seal_key_version=str(meta["seal_key_version"]),
            policy_id=str(meta["policy_id"]),
            policy_version=int(meta["policy_version"]),
            policy_hmac=str(meta["policy_hmac"]),
            schema_manifest_hmac=str(meta["schema_manifest_hmac"]),
            authority_id=str(meta["authority_id"]),
            authority_version=int(meta["authority_version"]),
            creator_scope=str(meta["creator_scope"]),
            last_clock=float(meta["last_clock"]),
        )

    def _verify_external_anchor(self, meta: sqlite3.Row) -> AnchorState:
        try:
            external = self.anchor.load()
        except Exception as exc:
            raise EgressConsentIntegrityError("external_anchor_unavailable") from exc
        if external is None:
            raise EgressConsentIntegrityError("external_anchor_missing")
        expected = self._anchor_state(meta)
        if external == expected:
            return external
        if external.ledger_id != expected.ledger_id:
            raise EgressConsentIntegrityError("database_rollback_detected")
        if external.generation > expected.generation:
            raise EgressConsentIntegrityError("database_rollback_detected")
        if external.generation < expected.generation:
            raise EgressConsentIntegrityError("external_anchor_rollback_detected")
        raise EgressConsentIntegrityError("external_anchor_mismatch")

    @staticmethod
    def _grant_material(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "consent_id": str(row["consent_id"]),
            "contract_version": int(row["contract_version"]),
            "schema_version": int(row["schema_version"]),
            "seal_key_version": str(row["seal_key_version"]),
            "policy_id": str(row["policy_id"]),
            "policy_version": int(row["policy_version"]),
            "authority_id": str(row["authority_id"]),
            "authority_version": int(row["authority_version"]),
            "creator_scope": str(row["creator_scope"]),
            "route_id": str(row["route_id"]),
            "destination_class": str(row["destination_class"]),
            "route_hmac": str(row["route_hmac"]),
            "operation_hmac": str(row["operation_hmac"]),
            "payload_hmac": str(row["payload_hmac"]),
            "decision_hmac": str(row["decision_hmac"]),
            "token_hmac": str(row["token_hmac"]),
            "byte_count": int(row["byte_count"]),
            "issued_at": float(row["issued_at"]),
            "expires_at": float(row["expires_at"]),
            "ttl_seconds": int(row["ttl_seconds"]),
            "max_uses": int(row["max_uses"]),
            "max_bytes_per_use": int(row["max_bytes_per_use"]),
        }

    @staticmethod
    def _receipt_material(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "receipt_sequence": int(row["receipt_sequence"]),
            "receipt_id": str(row["receipt_id"]),
            "consent_id": None if row["consent_id"] is None else str(row["consent_id"]),
            "contract_version": int(row["contract_version"]),
            "schema_version": int(row["schema_version"]),
            "seal_key_version": str(row["seal_key_version"]),
            "policy_id": str(row["policy_id"]),
            "policy_version": int(row["policy_version"]),
            "authority_id": str(row["authority_id"]),
            "authority_version": int(row["authority_version"]),
            "creator_scope": str(row["creator_scope"]),
            "event": str(row["event"]),
            "route_id": str(row["route_id"]),
            "destination_class": str(row["destination_class"]),
            "route_hmac": str(row["route_hmac"]),
            "operation_hmac": str(row["operation_hmac"]),
            "payload_hmac": str(row["payload_hmac"]),
            "decision_hmac": str(row["decision_hmac"]),
            "byte_count": int(row["byte_count"]),
            "issued_at": float(row["issued_at"]),
            "expires_at": float(row["expires_at"]),
            "ttl_seconds": int(row["ttl_seconds"]),
            "max_uses": int(row["max_uses"]),
            "max_bytes_per_use": int(row["max_bytes_per_use"]),
            "use_ordinal": None if row["use_ordinal"] is None else int(row["use_ordinal"]),
            "occurred_at": float(row["occurred_at"]),
            "reason": str(row["reason"]),
            "previous_seal": str(row["previous_seal"]),
        }

    def _verify_grant(self, row: sqlite3.Row) -> AllowedEgressRoute:
        try:
            material = self._grant_material(row)
            _opaque(material["consent_id"], _CONSENT_ID_RE, "consent_id")
            route = self.policy.resolve(material["route_id"])
            if (
                material["contract_version"] != CONTRACT_VERSION
                or material["schema_version"] != SCHEMA_VERSION
                or material["seal_key_version"] != self.seal_key_version
                or material["policy_id"] != self.policy.policy_id
                or material["policy_version"] != self.policy.version
                or material["authority_id"] != self._authority_id
                or material["authority_version"] != self._authority_version
                or material["creator_scope"] != self._creator_scope
                or material["destination_class"] != route.destination_class
                or not hmac.compare_digest(
                    material["route_hmac"], self._route_hmacs[route.route_id]
                )
                or material["ttl_seconds"] != route.ttl_seconds
                or material["max_uses"] != route.max_uses
                or material["max_bytes_per_use"] != route.max_bytes_per_use
                or material["byte_count"] < 1
                or material["byte_count"] > route.max_bytes_per_use
                or any(
                    not _is_hmac(material[field])
                    for field in (
                        "route_hmac",
                        "operation_hmac",
                        "payload_hmac",
                        "decision_hmac",
                        "token_hmac",
                    )
                )
                or material["expires_at"]
                != material["issued_at"] + material["ttl_seconds"]
            ):
                raise EgressConsentIntegrityError("grant_binding_invalid")
            if not hmac.compare_digest(
                self._seal(_GRANT_DOMAIN, material), str(row["grant_seal"])
            ):
                raise EgressConsentIntegrityError("grant_seal_invalid")
            uses = int(row["uses"])
            state = str(row["state"])
            last_used_at = row["last_used_at"]
            if uses < 0 or uses > route.max_uses or state not in _STATES:
                raise EgressConsentIntegrityError("grant_state_invalid")
            if (uses == 0) != (last_used_at is None):
                raise EgressConsentIntegrityError("grant_state_invalid")
            if state == "active":
                if uses >= route.max_uses or row["stopped_at"] is not None or row["stop_reason"]:
                    raise EgressConsentIntegrityError("grant_state_invalid")
            else:
                if str(row["stop_reason"]) not in _STOP_REASONS or row["stopped_at"] is None:
                    raise EgressConsentIntegrityError("grant_state_invalid")
            return route
        except EgressConsentIntegrityError:
            raise
        except (EgressConsentError, KeyError, TypeError, ValueError, OverflowError) as exc:
            raise EgressConsentIntegrityError("grant_binding_invalid") from exc

    def _verify_receipt(self, row: sqlite3.Row) -> AllowedEgressRoute:
        try:
            material = self._receipt_material(row)
            _opaque(material["receipt_id"], _RECEIPT_ID_RE, "receipt_id")
            route = self.policy.resolve(material["route_id"])
            event = material["event"]
            if (
                material["receipt_sequence"] < 1
                or event not in _EVENTS
                or material["contract_version"] != CONTRACT_VERSION
                or material["schema_version"] != SCHEMA_VERSION
                or material["seal_key_version"] != self.seal_key_version
                or material["policy_id"] != self.policy.policy_id
                or material["policy_version"] != self.policy.version
                or material["authority_id"] != self._authority_id
                or material["authority_version"] != self._authority_version
                or material["creator_scope"] != self._creator_scope
                or material["destination_class"] != route.destination_class
                or not hmac.compare_digest(
                    material["route_hmac"], self._route_hmacs[route.route_id]
                )
                or material["ttl_seconds"] != route.ttl_seconds
                or material["max_uses"] != route.max_uses
                or material["max_bytes_per_use"] != route.max_bytes_per_use
                or not 1 <= material["byte_count"] <= route.max_bytes_per_use
                or material["expires_at"]
                != material["issued_at"] + material["ttl_seconds"]
                or material["occurred_at"] < material["issued_at"]
                or any(
                    not _is_hmac(material[field])
                    for field in (
                        "route_hmac",
                        "operation_hmac",
                        "payload_hmac",
                        "decision_hmac",
                    )
                )
                or not _is_hmac(material["previous_seal"], allow_empty=True)
            ):
                raise EgressConsentIntegrityError("receipt_binding_invalid")
            if event == "deny":
                if material["consent_id"] is not None or material["reason"] not in _DENY_REASONS:
                    raise EgressConsentIntegrityError("receipt_binding_invalid")
            else:
                _opaque(material["consent_id"], _CONSENT_ID_RE, "consent_id")
            if event == "grant" and (
                material["reason"] != "creator_granted"
                or material["use_ordinal"] is not None
                or material["occurred_at"] != material["issued_at"]
            ):
                raise EgressConsentIntegrityError("receipt_binding_invalid")
            if event == "use" and (
                material["reason"] != "consumed_before_egress"
                or material["use_ordinal"] is None
                or not 1 <= material["use_ordinal"] <= route.max_uses
            ):
                raise EgressConsentIntegrityError("receipt_binding_invalid")
            if event == "stop" and (
                material["reason"] not in _STOP_REASONS
                or material["use_ordinal"] is not None
            ):
                raise EgressConsentIntegrityError("receipt_binding_invalid")
            if not hmac.compare_digest(
                self._seal(_RECEIPT_DOMAIN, material), str(row["receipt_seal"])
            ):
                raise EgressConsentIntegrityError("receipt_seal_invalid")
            return route
        except EgressConsentIntegrityError:
            raise
        except (EgressConsentError, KeyError, TypeError, ValueError, OverflowError) as exc:
            raise EgressConsentIntegrityError("receipt_binding_invalid") from exc

    def _verify_head(self, conn: sqlite3.Connection, meta: sqlite3.Row) -> None:
        count = int(meta["receipt_count"])
        latest = conn.execute(
            "SELECT * FROM egress_consent_receipts "
            "ORDER BY receipt_sequence DESC LIMIT 1"
        ).fetchone()
        if count == 0:
            if latest is not None or meta["receipt_head"]:
                raise EgressConsentIntegrityError("receipt_head_invalid")
            return
        if latest is None or int(latest["receipt_sequence"]) != count:
            raise EgressConsentIntegrityError("receipt_head_invalid")
        self._verify_receipt(latest)
        if (
            not hmac.compare_digest(
                str(latest["receipt_seal"]), str(meta["receipt_head"])
            )
            or float(latest["occurred_at"]) > float(meta["last_clock"])
        ):
            raise EgressConsentIntegrityError("receipt_head_invalid")

    def _verify_runtime(self, conn: sqlite3.Connection) -> tuple[sqlite3.Row, AnchorState]:
        meta = self._verify_meta(self._meta_row(conn))
        self._verify_schema_objects(conn)
        self._verify_schema_manifest(conn, meta)
        external = self._verify_external_anchor(meta)
        self._verify_head(conn, meta)
        return meta, external

    def _advance_observation(
        self, conn: sqlite3.Connection, meta: sqlite3.Row, stamp: float
    ) -> sqlite3.Row:
        material = self._meta_material(meta)
        material["anchor_generation"] = int(material["anchor_generation"]) + 1
        material["last_clock"] = stamp
        changed = conn.execute(
            """
            UPDATE egress_consent_meta
            SET anchor_generation=?,last_clock=?,meta_seal=?
            WHERE singleton=1 AND anchor_generation=? AND receipt_count=?
              AND receipt_head=?
            """,
            (
                material["anchor_generation"],
                stamp,
                self._seal(_META_DOMAIN, material),
                int(meta["anchor_generation"]),
                int(meta["receipt_count"]),
                str(meta["receipt_head"]),
            ),
        )
        if changed.rowcount != 1:
            raise EgressConsentIntegrityError("metadata_advance_failed")
        stored = self._meta_row(conn)
        return self._verify_meta(stored)

    def _append_receipt(
        self,
        conn: sqlite3.Connection,
        *,
        consent_id: str | None,
        event: str,
        binding: Mapping[str, object],
        occurred_at: float,
        reason: str,
        use_ordinal: int | None = None,
    ) -> sqlite3.Row:
        meta = self._verify_meta(self._meta_row(conn))
        if occurred_at < float(meta["last_clock"]):
            raise EgressConsentIntegrityError("trusted_clock_rollback")
        sequence = int(meta["receipt_count"]) + 1
        receipt_id = "receipt_" + secrets.token_urlsafe(24)
        material: dict[str, object] = {
            "receipt_sequence": sequence,
            "receipt_id": receipt_id,
            "consent_id": consent_id,
            "contract_version": CONTRACT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "seal_key_version": self.seal_key_version,
            "policy_id": self.policy.policy_id,
            "policy_version": self.policy.version,
            "authority_id": self._authority_id,
            "authority_version": self._authority_version,
            "creator_scope": self._creator_scope,
            "event": event,
            "route_id": binding["route_id"],
            "destination_class": binding["destination_class"],
            "route_hmac": binding["route_hmac"],
            "operation_hmac": binding["operation_hmac"],
            "payload_hmac": binding["payload_hmac"],
            "decision_hmac": binding["decision_hmac"],
            "byte_count": binding["byte_count"],
            "issued_at": binding["issued_at"],
            "expires_at": binding["expires_at"],
            "ttl_seconds": binding["ttl_seconds"],
            "max_uses": binding["max_uses"],
            "max_bytes_per_use": binding["max_bytes_per_use"],
            "use_ordinal": use_ordinal,
            "occurred_at": occurred_at,
            "reason": reason,
            "previous_seal": str(meta["receipt_head"]),
        }
        seal = self._seal(_RECEIPT_DOMAIN, material)
        conn.execute(
            """
            INSERT INTO egress_consent_receipts
                (receipt_sequence,receipt_id,consent_id,contract_version,
                 schema_version,seal_key_version,policy_id,policy_version,
                 authority_id,authority_version,creator_scope,event,route_id,
                 destination_class,route_hmac,operation_hmac,payload_hmac,
                 decision_hmac,byte_count,issued_at,expires_at,ttl_seconds,
                 max_uses,max_bytes_per_use,use_ordinal,occurred_at,reason,
                 previous_seal,receipt_seal)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sequence,
                receipt_id,
                consent_id,
                CONTRACT_VERSION,
                SCHEMA_VERSION,
                self.seal_key_version,
                self.policy.policy_id,
                self.policy.version,
                self._authority_id,
                self._authority_version,
                self._creator_scope,
                event,
                material["route_id"],
                material["destination_class"],
                material["route_hmac"],
                material["operation_hmac"],
                material["payload_hmac"],
                material["decision_hmac"],
                material["byte_count"],
                material["issued_at"],
                material["expires_at"],
                material["ttl_seconds"],
                material["max_uses"],
                material["max_bytes_per_use"],
                use_ordinal,
                occurred_at,
                reason,
                material["previous_seal"],
                seal,
            ),
        )
        next_meta = self._meta_material(meta)
        next_meta["receipt_count"] = sequence
        next_meta["receipt_head"] = seal
        changed = conn.execute(
            """
            UPDATE egress_consent_meta
            SET receipt_count=?,receipt_head=?,meta_seal=?
            WHERE singleton=1 AND receipt_count=? AND receipt_head=?
            """,
            (
                sequence,
                seal,
                self._seal(_META_DOMAIN, next_meta),
                sequence - 1,
                str(meta["receipt_head"]),
            ),
        )
        if changed.rowcount != 1:
            raise EgressConsentIntegrityError("receipt_head_advance_failed")
        row = conn.execute(
            "SELECT * FROM egress_consent_receipts WHERE receipt_sequence=?",
            (sequence,),
        ).fetchone()
        assert row is not None
        self._verify_receipt(row)
        return row

    @staticmethod
    def _binding_from_grant(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "route_id": str(row["route_id"]),
            "destination_class": str(row["destination_class"]),
            "route_hmac": str(row["route_hmac"]),
            "operation_hmac": str(row["operation_hmac"]),
            "payload_hmac": str(row["payload_hmac"]),
            "decision_hmac": str(row["decision_hmac"]),
            "byte_count": int(row["byte_count"]),
            "issued_at": float(row["issued_at"]),
            "expires_at": float(row["expires_at"]),
            "ttl_seconds": int(row["ttl_seconds"]),
            "max_uses": int(row["max_uses"]),
            "max_bytes_per_use": int(row["max_bytes_per_use"]),
        }

    def _target_receipts(
        self, conn: sqlite3.Connection, consent_id: str
    ) -> list[sqlite3.Row]:
        rows = conn.execute(
            "SELECT * FROM egress_consent_receipts WHERE consent_id=? "
            "ORDER BY receipt_sequence LIMIT ?",
            (consent_id, MAX_USES + 4),
        ).fetchall()
        if len(rows) > MAX_USES + 2:
            raise EgressConsentIntegrityError("target_receipt_count_invalid")
        return list(rows)

    def _verify_target_rows(
        self, row: sqlite3.Row, receipts: list[sqlite3.Row]
    ) -> None:
        self._verify_grant(row)
        if not receipts or str(receipts[0]["event"]) != "grant":
            raise EgressConsentIntegrityError("grant_receipt_missing")
        immutable = (
            "contract_version",
            "schema_version",
            "seal_key_version",
            "policy_id",
            "policy_version",
            "authority_id",
            "authority_version",
            "creator_scope",
            "route_id",
            "destination_class",
            "route_hmac",
            "operation_hmac",
            "payload_hmac",
            "decision_hmac",
            "byte_count",
            "issued_at",
            "expires_at",
            "ttl_seconds",
            "max_uses",
            "max_bytes_per_use",
        )
        uses: list[sqlite3.Row] = []
        stops: list[sqlite3.Row] = []
        previous_at = float(row["issued_at"])
        for receipt in receipts:
            self._verify_receipt(receipt)
            if str(receipt["consent_id"]) != str(row["consent_id"]):
                raise EgressConsentIntegrityError("target_receipt_binding_invalid")
            if any(receipt[field] != row[field] for field in immutable):
                raise EgressConsentIntegrityError("target_receipt_binding_invalid")
            if float(receipt["occurred_at"]) < previous_at:
                raise EgressConsentIntegrityError("target_receipt_order_invalid")
            previous_at = float(receipt["occurred_at"])
            if receipt["event"] == "use":
                if stops:
                    raise EgressConsentIntegrityError("target_receipt_order_invalid")
                uses.append(receipt)
            elif receipt["event"] == "stop":
                stops.append(receipt)
            elif receipt["event"] != "grant":
                raise EgressConsentIntegrityError("target_receipt_event_invalid")
        if sum(receipt["event"] == "grant" for receipt in receipts) != 1:
            raise EgressConsentIntegrityError("grant_receipt_invalid")
        if [int(item["use_ordinal"]) for item in uses] != list(
            range(1, int(row["uses"]) + 1)
        ):
            raise EgressConsentIntegrityError("use_receipt_state_invalid")
        if uses:
            if float(row["last_used_at"]) != float(uses[-1]["occurred_at"]):
                raise EgressConsentIntegrityError("use_receipt_state_invalid")
        elif row["last_used_at"] is not None:
            raise EgressConsentIntegrityError("use_receipt_state_invalid")
        if row["state"] == "active":
            if stops:
                raise EgressConsentIntegrityError("stop_receipt_state_invalid")
            return
        if len(stops) != 1 or receipts[-1]["event"] != "stop":
            raise EgressConsentIntegrityError("stop_receipt_state_invalid")
        stop = stops[0]
        if (
            float(stop["occurred_at"]) != float(row["stopped_at"])
            or str(stop["reason"]) != str(row["stop_reason"])
        ):
            raise EgressConsentIntegrityError("stop_receipt_state_invalid")
        if row["stop_reason"] == "use_cap_reached" and int(row["uses"]) != int(
            row["max_uses"]
        ):
            raise EgressConsentIntegrityError("stop_receipt_state_invalid")

    def _verify_target(self, conn: sqlite3.Connection, row: sqlite3.Row) -> None:
        self._verify_target_rows(
            row, self._target_receipts(conn, str(row["consent_id"]))
        )

    def _stop_active(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        reason: str,
        stamp: float,
    ) -> sqlite3.Row:
        if reason not in _STOP_REASONS:
            raise EgressConsentError("invalid_stop_reason")
        changed = conn.execute(
            """
            UPDATE egress_consents
            SET state='stopped',stopped_at=?,stop_reason=?
            WHERE consent_id=? AND state='active' AND uses=?
            """,
            (stamp, reason, str(row["consent_id"]), int(row["uses"])),
        )
        if changed.rowcount != 1:
            raise EgressConsentIntegrityError("grant_state_changed")
        self._append_receipt(
            conn,
            consent_id=str(row["consent_id"]),
            event="stop",
            binding=self._binding_from_grant(row),
            occurred_at=stamp,
            reason=reason,
        )
        stored = conn.execute(
            "SELECT * FROM egress_consents WHERE consent_id=?",
            (str(row["consent_id"]),),
        ).fetchone()
        assert stored is not None
        self._verify_target(conn, stored)
        return stored

    def _expire_exact_binding(
        self,
        conn: sqlite3.Connection,
        stamp: float,
        *,
        operation_hmac: str,
        route_id: str,
    ) -> int:
        row = conn.execute(
            "SELECT * FROM egress_consents "
            "WHERE state='active' AND operation_hmac=? AND route_id=?",
            (operation_hmac, route_id),
        ).fetchone()
        if row is None or float(row["expires_at"]) > stamp:
            return 0
        self._verify_target(conn, row)
        self._stop_active(conn, row, reason="expired", stamp=stamp)
        return 1

    def _expire_due_batch(self, conn: sqlite3.Connection, stamp: float) -> int:
        rows = conn.execute(
            "SELECT * FROM egress_consents "
            "WHERE state='active' AND expires_at<=? ORDER BY expires_at,id LIMIT ?",
            (stamp, MAINTENANCE_BATCH_SIZE),
        ).fetchall()
        for row in rows:
            self._verify_target(conn, row)
            self._stop_active(conn, row, reason="expired", stamp=stamp)
        return len(rows)

    def _advance_anchor(
        self, expected: AnchorState, updated: AnchorState
    ) -> None:
        try:
            self.anchor.advance(expected, updated)
        except Exception as exc:
            raise EgressConsentIntegrityError("external_anchor_failure") from exc

    def _run_transaction(
        self,
        callback: Callable[[sqlite3.Connection, sqlite3.Row, float], object],
    ) -> object:
        self._require_ready()
        anchor_attempted = False
        result: object | None = None
        try:
            with connect(self.db_path) as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                old_meta, expected_anchor = self._verify_runtime(conn)
                stamp = self._trusted_now(old_meta)
                result = callback(conn, old_meta, stamp)
                current_meta = self._verify_meta(self._meta_row(conn))
                current_meta = self._advance_observation(conn, current_meta, stamp)
                self._verify_head(conn, current_meta)
                updated_anchor = self._anchor_state(current_meta)
                anchor_attempted = True
                self._advance_anchor(expected_anchor, updated_anchor)
            return result
        except EgressConsentQuarantined:
            raise
        except EgressConsentIntegrityError as exc:
            self._quarantine(
                "anchor_commit_uncertain" if anchor_attempted else exc.reason
            )
            raise EgressConsentQuarantined(self.quarantine_reason) from exc
        except Exception as exc:
            if anchor_attempted:
                self._quarantine("anchor_commit_uncertain")
                raise EgressConsentQuarantined(self.quarantine_reason) from exc
            raise

    def _preflight_runtime_gate(self) -> None:
        """Verify schema/head/anchor before invoking an external authority."""
        self._require_ready()
        try:
            with connect(self.db_path) as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
                self._verify_runtime(conn)
        except EgressConsentIntegrityError as exc:
            self._quarantine(exc.reason)
            raise EgressConsentQuarantined(self.quarantine_reason) from exc
        except Exception as exc:
            self._quarantine("runtime_gate_failed")
            raise EgressConsentQuarantined(self.quarantine_reason) from exc

    def _full_audit_conn(
        self, conn: sqlite3.Connection, meta: sqlite3.Row
    ) -> dict[str, int]:
        self._verify_schema_objects(conn)
        self._verify_schema_manifest(conn, meta)
        receipts = conn.execute(
            "SELECT * FROM egress_consent_receipts ORDER BY receipt_sequence"
        ).fetchall()
        grants = conn.execute("SELECT * FROM egress_consents ORDER BY id").fetchall()
        if len(receipts) != int(meta["receipt_count"]):
            raise EgressConsentIntegrityError("receipt_count_invalid")
        previous_seal = ""
        previous_at = 0.0
        grouped: dict[str, list[sqlite3.Row]] = {}
        for sequence, receipt in enumerate(receipts, start=1):
            self._verify_receipt(receipt)
            if int(receipt["receipt_sequence"]) != sequence:
                raise EgressConsentIntegrityError("receipt_sequence_invalid")
            if str(receipt["previous_seal"]) != previous_seal:
                raise EgressConsentIntegrityError("receipt_chain_invalid")
            if float(receipt["occurred_at"]) < previous_at:
                raise EgressConsentIntegrityError("receipt_clock_invalid")
            previous_at = float(receipt["occurred_at"])
            previous_seal = str(receipt["receipt_seal"])
            if receipt["consent_id"] is not None:
                grouped.setdefault(str(receipt["consent_id"]), []).append(receipt)
        if previous_seal != str(meta["receipt_head"]):
            raise EgressConsentIntegrityError("receipt_head_invalid")
        grant_ids = {str(row["consent_id"]) for row in grants}
        if set(grouped) != grant_ids:
            raise EgressConsentIntegrityError("grant_receipt_membership_invalid")
        for row in grants:
            self._verify_target_rows(row, grouped[str(row["consent_id"])])
        active = sum(str(row["state"]) == "active" for row in grants)
        return {
            "consents": len(grants),
            "active": active,
            "stopped": len(grants) - active,
            "receipts": len(receipts),
        }

    def _bootstrap(self) -> None:
        anchor_attempted = False
        try:
            with _SCHEMA_LOCK:
                with connect(self.db_path) as conn:
                    conn.execute("PRAGMA foreign_keys=ON")
                    tables = self._schema_names(conn, "table")
                    has_meta = _META_TABLE in tables
                    if not has_meta:
                        owned = {
                            name
                            for name in tables
                            if name.startswith("egress_consent")
                            or name in _LEGACY_TABLES
                        }
                        if owned:
                            raise EgressConsentIntegrityError("unsupported_schema")
                        try:
                            if self.anchor.load() is not None:
                                raise EgressConsentIntegrityError(
                                    "database_rollback_detected"
                                )
                        except EgressConsentIntegrityError:
                            raise
                        except Exception as exc:
                            raise EgressConsentIntegrityError(
                                "external_anchor_unavailable"
                            ) from exc
                        self._create_schema(conn)
                        self._verify_schema_objects(conn)
                        if not hmac.compare_digest(
                            self._schema_manifest_hmac(conn),
                            self._expected_schema_manifest_hmac,
                        ):
                            raise EgressConsentIntegrityError(
                                "schema_manifest_mismatch"
                            )
                        conn.execute("BEGIN IMMEDIATE")
                        stamp = self._trusted_now()
                        material = {
                            "schema_version": SCHEMA_VERSION,
                            "contract_version": CONTRACT_VERSION,
                            "ledger_id": "ledger_" + secrets.token_urlsafe(24),
                            "seal_key_version": self.seal_key_version,
                            "policy_id": self.policy.policy_id,
                            "policy_version": self.policy.version,
                            "policy_hmac": self._policy_hmac,
                            "schema_manifest_hmac": self._expected_schema_manifest_hmac,
                            "authority_id": self._authority_id,
                            "authority_version": self._authority_version,
                            "creator_scope": self._creator_scope,
                            "anchor_generation": 1,
                            "receipt_count": 0,
                            "receipt_head": "",
                            "last_clock": stamp,
                        }
                        conn.execute(
                            """
                            INSERT INTO egress_consent_meta
                                (singleton,schema_version,contract_version,ledger_id,
                                 seal_key_version,policy_id,policy_version,policy_hmac,
                                 schema_manifest_hmac,authority_id,authority_version,creator_scope,
                                 anchor_generation,receipt_count,receipt_head,
                                 last_clock,meta_seal)
                            VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                material["schema_version"],
                                material["contract_version"],
                                material["ledger_id"],
                                material["seal_key_version"],
                                material["policy_id"],
                                material["policy_version"],
                                material["policy_hmac"],
                                material["schema_manifest_hmac"],
                                material["authority_id"],
                                material["authority_version"],
                                material["creator_scope"],
                                material["anchor_generation"],
                                material["receipt_count"],
                                material["receipt_head"],
                                material["last_clock"],
                                self._seal(_META_DOMAIN, material),
                            ),
                        )
                        meta = self._verify_meta(self._meta_row(conn))
                        anchor_attempted = True
                        self.anchor.initialize(self._anchor_state(meta))
                    else:
                        conn.execute("BEGIN IMMEDIATE")
                        self._verify_schema_objects(conn)
                        old_meta, expected_anchor = self._verify_runtime(conn)
                        stamp = self._trusted_now(old_meta)
                        self._full_audit_conn(conn, old_meta)
                        active = conn.execute(
                            "SELECT * FROM egress_consents "
                            "WHERE state='active' ORDER BY id"
                        ).fetchall()
                        for row in active:
                            self._verify_target(conn, row)
                            self._stop_active(
                                conn, row, reason="server_restart", stamp=stamp
                            )
                        current = self._verify_meta(self._meta_row(conn))
                        current = self._advance_observation(conn, current, stamp)
                        self._verify_head(conn, current)
                        anchor_attempted = True
                        self._advance_anchor(
                            expected_anchor, self._anchor_state(current)
                        )
            self._set_ready()
        except EgressConsentIntegrityError as exc:
            self._quarantine(
                "anchor_commit_uncertain" if anchor_attempted else exc.reason
            )
        except Exception:
            self._quarantine(
                "anchor_commit_uncertain" if anchor_attempted else "bootstrap_failed"
            )

    def _route_public(self, route: AllowedEgressRoute) -> dict[str, object]:
        return {
            "route_id": route.route_id,
            "provider": route.provider,
            "deployment": route.deployment,
            "model": route.model,
            "capability": route.capability,
            "purpose": route.purpose,
            "processing_location": route.processing_location,
            "destination_class": route.destination_class,
            "transport": "https",
        }

    def _public_consent(self, row: Mapping[str, object]) -> dict[str, object]:
        route = self.policy.resolve(row["route_id"])
        return {
            "consent_id": str(row["consent_id"]),
            "creator_scope": self._creator_scope,
            "route": self._route_public(route),
            "byte_count": int(row["byte_count"]),
            "issued_at": float(row["issued_at"]),
            "expires_at": float(row["expires_at"]),
            "ttl_seconds": int(row["ttl_seconds"]),
            "max_uses": int(row["max_uses"]),
            "max_bytes_per_use": int(row["max_bytes_per_use"]),
            "uses": int(row["uses"]),
            "state": str(row["state"]),
            "stopped_at": (
                None if row["stopped_at"] is None else float(row["stopped_at"])
            ),
            "stop_reason": str(row["stop_reason"]),
        }

    def _public_receipt(self, row: Mapping[str, object]) -> dict[str, object]:
        route = self.policy.resolve(row["route_id"])
        return {
            "receipt_id": str(row["receipt_id"]),
            "order": int(row["receipt_sequence"]),
            "consent_id": None if row["consent_id"] is None else str(row["consent_id"]),
            "event": str(row["event"]),
            "creator_scope": self._creator_scope,
            "route": self._route_public(route),
            "byte_count": int(row["byte_count"]),
            "occurred_at": float(row["occurred_at"]),
            "expires_at": float(row["expires_at"]),
            "use_ordinal": (
                None if row["use_ordinal"] is None else int(row["use_ordinal"])
            ),
            "reason": str(row["reason"]),
            "verified": True,
        }

    def _attempt_evidence(self, use_receipt: Mapping[str, object]) -> dict[str, object]:
        route = self.policy.resolve(use_receipt["route_id"])
        return {
            "attempt_id": str(use_receipt["receipt_id"]),
            "order": int(use_receipt["receipt_sequence"]),
            "attempt_ordinal": int(use_receipt["use_ordinal"]),
            "consent_id": str(use_receipt["consent_id"]),
            "route": self._route_public(route),
            "byte_count": int(use_receipt["byte_count"]),
            "authorized_at": float(use_receipt["occurred_at"]),
            "outcome": "authorized_before_outbound",
        }

    def request_consent(
        self,
        *,
        operation_id: str,
        route_id: str,
        payload_metadata: bytes,
        byte_count: int,
    ) -> dict[str, object]:
        """Ask the injected authority and record its exact creator decision."""
        self._require_ready()
        route = self.policy.resolve(route_id)
        operation_hmac = self._operation_hmac(operation_id)
        metadata = _payload_metadata(payload_metadata)
        count = _positive_int(byte_count, "byte_count", route.max_bytes_per_use)
        route_hmac = self._route_hmacs[route.route_id]
        payload_hmac = self._payload_binding_hmac(
            operation_hmac=operation_hmac,
            route_hmac=route_hmac,
            byte_count=count,
            payload_metadata=metadata,
        )
        self._preflight_runtime_gate()
        request = AuthorityRequest(
            action="private_cloud_egress",
            route_id=route.route_id,
            provider=route.provider,
            deployment=route.deployment,
            model=route.model,
            capability=route.capability,
            purpose=route.purpose,
            processing_location=route.processing_location,
            destination_class=route.destination_class,
            transport_route=route.transport_route,
            operation_hmac=operation_hmac,
            payload_hmac=payload_hmac,
            byte_count=count,
            ttl_seconds=route.ttl_seconds,
            max_uses=route.max_uses,
            max_bytes_per_use=route.max_bytes_per_use,
        )
        try:
            decision = self.authority.decide(request)
        except Exception as exc:
            raise EgressConsentDenied("authority_unavailable") from exc
        if (
            not isinstance(decision, CreatorDecision)
            or type(decision.allowed) is not bool
        ):
            raise EgressConsentDenied("authority_response_invalid")
        decision_hmac = self._decision_hmac(decision.decision_id)

        def operation(
            conn: sqlite3.Connection, _meta: sqlite3.Row, stamp: float
        ) -> dict[str, object]:
            self._expire_exact_binding(
                conn,
                stamp,
                operation_hmac=operation_hmac,
                route_id=route.route_id,
            )
            self._expire_due_batch(conn, stamp)
            if conn.execute(
                "SELECT 1 FROM egress_consent_receipts "
                "WHERE decision_hmac=? AND event IN ('grant','deny')",
                (decision_hmac,),
            ).fetchone() is not None:
                return {"denied_reason": "authority_decision_replay"}
            binding = {
                "route_id": route.route_id,
                "destination_class": route.destination_class,
                "route_hmac": route_hmac,
                "operation_hmac": operation_hmac,
                "payload_hmac": payload_hmac,
                "decision_hmac": decision_hmac,
                "byte_count": count,
                "issued_at": stamp,
                "expires_at": stamp + route.ttl_seconds,
                "ttl_seconds": route.ttl_seconds,
                "max_uses": route.max_uses,
                "max_bytes_per_use": route.max_bytes_per_use,
            }
            if not decision.allowed:
                receipt = self._append_receipt(
                    conn,
                    consent_id=None,
                    event="deny",
                    binding=binding,
                    occurred_at=stamp,
                    reason="creator_denied",
                )
                return {
                    "granted": False,
                    "decision": "deny",
                    "receipt": self._public_receipt(receipt),
                }
            existing = conn.execute(
                "SELECT * FROM egress_consents "
                "WHERE operation_hmac=? AND route_id=? AND state='active'",
                (operation_hmac, route.route_id),
            ).fetchone()
            if existing is not None:
                self._verify_target(conn, existing)
                receipt = self._append_receipt(
                    conn,
                    consent_id=None,
                    event="deny",
                    binding=binding,
                    occurred_at=stamp,
                    reason="active_consent_exists",
                )
                return {
                    "denied_reason": "active_consent_exists",
                    "receipt": self._public_receipt(receipt),
                }
            token = "ec2_" + secrets.token_urlsafe(32)
            consent_id = "consent_" + secrets.token_urlsafe(24)
            grant = {
                "consent_id": consent_id,
                "contract_version": CONTRACT_VERSION,
                "schema_version": SCHEMA_VERSION,
                "seal_key_version": self.seal_key_version,
                "policy_id": self.policy.policy_id,
                "policy_version": self.policy.version,
                "authority_id": self._authority_id,
                "authority_version": self._authority_version,
                "creator_scope": self._creator_scope,
                **binding,
                "token_hmac": self._token_hmac(token),
            }
            conn.execute(
                """
                INSERT INTO egress_consents
                    (consent_id,contract_version,schema_version,seal_key_version,
                     policy_id,policy_version,authority_id,authority_version,
                     creator_scope,route_id,destination_class,route_hmac,
                     operation_hmac,payload_hmac,decision_hmac,token_hmac,
                     byte_count,issued_at,expires_at,ttl_seconds,max_uses,
                     max_bytes_per_use,uses,last_used_at,state,stopped_at,
                     stop_reason,grant_seal)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,NULL,
                       'active',NULL,'',?)
                """,
                (
                    consent_id,
                    CONTRACT_VERSION,
                    SCHEMA_VERSION,
                    self.seal_key_version,
                    self.policy.policy_id,
                    self.policy.version,
                    self._authority_id,
                    self._authority_version,
                    self._creator_scope,
                    route.route_id,
                    route.destination_class,
                    route_hmac,
                    operation_hmac,
                    payload_hmac,
                    decision_hmac,
                    grant["token_hmac"],
                    count,
                    stamp,
                    stamp + route.ttl_seconds,
                    route.ttl_seconds,
                    route.max_uses,
                    route.max_bytes_per_use,
                    self._seal(_GRANT_DOMAIN, grant),
                ),
            )
            stored = conn.execute(
                "SELECT * FROM egress_consents WHERE consent_id=?", (consent_id,)
            ).fetchone()
            assert stored is not None
            receipt = self._append_receipt(
                conn,
                consent_id=consent_id,
                event="grant",
                binding=binding,
                occurred_at=stamp,
                reason="creator_granted",
            )
            self._verify_target(conn, stored)
            return {
                "granted": True,
                "decision": "grant",
                **self._public_consent(stored),
                "token": token,
                "receipt": self._public_receipt(receipt),
            }

        result = self._run_transaction(operation)
        assert isinstance(result, dict)
        if result.get("denied_reason"):
            raise EgressConsentDenied(str(result["denied_reason"]))
        return result

    def _consume_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row | None,
        *,
        route: AllowedEgressRoute,
        operation_hmac: str,
        payload_hmac: str,
        byte_count: int,
        stamp: float,
    ) -> dict[str, object]:
        if row is None:
            return {"denied_reason": "consent_not_found"}
        self._verify_target(conn, row)
        if str(row["route_id"]) != route.route_id:
            return {"denied_reason": "route_mismatch"}
        if not hmac.compare_digest(str(row["operation_hmac"]), operation_hmac):
            return {"denied_reason": "operation_mismatch"}
        if int(row["byte_count"]) != byte_count:
            return {"denied_reason": "byte_count_mismatch"}
        if not hmac.compare_digest(str(row["payload_hmac"]), payload_hmac):
            return {"denied_reason": "payload_mismatch"}
        if str(row["state"]) != "active":
            return {
                "denied_reason": (
                    "replay"
                    if row["stop_reason"] == "use_cap_reached"
                    else "consent_expired"
                    if row["stop_reason"] == "expired"
                    else "consent_stopped"
                )
            }
        if stamp >= float(row["expires_at"]):
            self._stop_active(conn, row, reason="expired", stamp=stamp)
            return {"denied_reason": "consent_expired"}
        ordinal = int(row["uses"]) + 1
        at_cap = ordinal == int(row["max_uses"])
        changed = conn.execute(
            """
            UPDATE egress_consents
            SET uses=?,last_used_at=?,state=?,stopped_at=?,stop_reason=?
            WHERE consent_id=? AND state='active' AND uses=?
            """,
            (
                ordinal,
                stamp,
                "stopped" if at_cap else "active",
                stamp if at_cap else None,
                "use_cap_reached" if at_cap else "",
                str(row["consent_id"]),
                int(row["uses"]),
            ),
        )
        if changed.rowcount != 1:
            raise EgressConsentIntegrityError("atomic_consume_failed")
        binding = self._binding_from_grant(row)
        use_receipt = self._append_receipt(
            conn,
            consent_id=str(row["consent_id"]),
            event="use",
            binding=binding,
            occurred_at=stamp,
            reason="consumed_before_egress",
            use_ordinal=ordinal,
        )
        stop_receipt: sqlite3.Row | None = None
        if at_cap:
            stop_receipt = self._append_receipt(
                conn,
                consent_id=str(row["consent_id"]),
                event="stop",
                binding=binding,
                occurred_at=stamp,
                reason="use_cap_reached",
            )
        stored = conn.execute(
            "SELECT * FROM egress_consents WHERE consent_id=?",
            (str(row["consent_id"]),),
        ).fetchone()
        assert stored is not None
        self._verify_target(conn, stored)
        return {
            **self._public_consent(stored),
            "use_receipt": self._public_receipt(use_receipt),
            "stop_receipt": (
                None if stop_receipt is None else self._public_receipt(stop_receipt)
            ),
            "attempt_evidence": self._attempt_evidence(use_receipt),
        }

    def _binding_inputs(
        self,
        *,
        operation_id: str,
        route_id: str,
        payload_metadata: bytes,
        byte_count: int,
    ) -> tuple[AllowedEgressRoute, str, str, int]:
        route = self.policy.resolve(route_id)
        operation_hmac = self._operation_hmac(operation_id)
        metadata = _payload_metadata(payload_metadata)
        count = _positive_int(byte_count, "byte_count", route.max_bytes_per_use)
        payload_hmac = self._payload_binding_hmac(
            operation_hmac=operation_hmac,
            route_hmac=self._route_hmacs[route.route_id],
            byte_count=count,
            payload_metadata=metadata,
        )
        return route, operation_hmac, payload_hmac, count

    def consume(
        self,
        token: str,
        *,
        operation_id: str,
        route_id: str,
        payload_metadata: bytes,
        byte_count: int,
    ) -> dict[str, object]:
        """Consume one bearer-bound use immediately before one outbound attempt."""
        route, operation_hmac, payload_hmac, count = self._binding_inputs(
            operation_id=operation_id,
            route_id=route_id,
            payload_metadata=payload_metadata,
            byte_count=byte_count,
        )
        token_hmac = self._token_hmac(token)

        def operation(
            conn: sqlite3.Connection, _meta: sqlite3.Row, stamp: float
        ) -> dict[str, object]:
            row = conn.execute(
                "SELECT * FROM egress_consents WHERE token_hmac=?", (token_hmac,)
            ).fetchone()
            return self._consume_row(
                conn,
                row,
                route=route,
                operation_hmac=operation_hmac,
                payload_hmac=payload_hmac,
                byte_count=count,
                stamp=stamp,
            )

        result = self._run_transaction(operation)
        assert isinstance(result, dict)
        if result.get("denied_reason"):
            raise EgressConsentDenied(str(result["denied_reason"]))
        return result

    def consume_active(
        self,
        *,
        operation_id: str,
        route_id: str,
        payload_metadata: bytes,
        byte_count: int,
    ) -> dict[str, object]:
        """Server-internal atomic consume without exposing a bearer token."""
        route, operation_hmac, payload_hmac, count = self._binding_inputs(
            operation_id=operation_id,
            route_id=route_id,
            payload_metadata=payload_metadata,
            byte_count=byte_count,
        )

        def operation(
            conn: sqlite3.Connection, _meta: sqlite3.Row, stamp: float
        ) -> dict[str, object]:
            rows = conn.execute(
                "SELECT * FROM egress_consents "
                "WHERE operation_hmac=? AND route_id=? AND state='active' "
                "ORDER BY id LIMIT 2",
                (operation_hmac, route.route_id),
            ).fetchall()
            if len(rows) > 1:
                raise EgressConsentIntegrityError("active_binding_not_unique")
            return self._consume_row(
                conn,
                None if not rows else rows[0],
                route=route,
                operation_hmac=operation_hmac,
                payload_hmac=payload_hmac,
                byte_count=count,
                stamp=stamp,
            )

        result = self._run_transaction(operation)
        assert isinstance(result, dict)
        if result.get("denied_reason"):
            raise EgressConsentDenied(str(result["denied_reason"]))
        return result

    def _quarantine_status(self) -> dict[str, object]:
        return {
            "ready": False,
            "quarantined": self.quarantined,
            "reason": self.quarantine_reason or "recovery_not_ready",
            "schema_version": SCHEMA_VERSION,
            "contract_version": CONTRACT_VERSION,
            "active": [],
            "receipts": [],
        }

    def status(self, *, receipt_limit: int = 50) -> dict[str, object]:
        """Expire stale grants and return a content-free consistent snapshot."""
        if (
            isinstance(receipt_limit, bool)
            or not isinstance(receipt_limit, int)
            or not 1 <= receipt_limit <= 100
        ):
            raise EgressConsentError("invalid_receipt_limit")
        if not self.ready:
            return self._quarantine_status()

        def operation(
            conn: sqlite3.Connection, _meta: sqlite3.Row, stamp: float
        ) -> dict[str, object]:
            self._expire_due_batch(conn, stamp)
            active = conn.execute(
                "SELECT * FROM egress_consents "
                "WHERE state='active' AND expires_at>? ORDER BY expires_at,id",
                (stamp,),
            ).fetchall()
            for row in active:
                self._verify_target(conn, row)
            receipts = conn.execute(
                "SELECT * FROM egress_consent_receipts "
                "ORDER BY receipt_sequence DESC LIMIT ?",
                (receipt_limit,),
            ).fetchall()
            for row in receipts:
                self._verify_receipt(row)
            count_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS consents,
                    SUM(CASE WHEN state='active' AND expires_at>? THEN 1 ELSE 0 END)
                        AS active,
                    SUM(CASE WHEN state='active' AND expires_at<=? THEN 1 ELSE 0 END)
                        AS stale_pending,
                    SUM(CASE WHEN state='stopped' THEN 1 ELSE 0 END) AS stopped
                FROM egress_consents
                """,
                (stamp, stamp),
            ).fetchone()
            assert count_row is not None
            meta = self._verify_meta(self._meta_row(conn))
            return {
                "ready": True,
                "quarantined": False,
                "reason": "",
                "schema_version": SCHEMA_VERSION,
                "contract_version": CONTRACT_VERSION,
                "seal_key_version": self.seal_key_version,
                "policy": {
                    "policy_id": self.policy.policy_id,
                    "version": self.policy.version,
                },
                "authority": {
                    "authority_id": self._authority_id,
                    "version": self._authority_version,
                    "creator_scope": self._creator_scope,
                },
                "counts": {
                    "consents": int(count_row["consents"]),
                    "active": int(count_row["active"] or 0),
                    "stale_pending": int(count_row["stale_pending"] or 0),
                    "stopped": int(count_row["stopped"] or 0),
                    "receipts": int(meta["receipt_count"]),
                },
                "active": [self._public_consent(row) for row in active],
                "receipts": [self._public_receipt(row) for row in receipts],
            }

        try:
            result = self._run_transaction(operation)
        except EgressConsentQuarantined:
            return self._quarantine_status()
        assert isinstance(result, dict)
        return result

    def audit(self) -> dict[str, object]:
        """Run the explicit linear full-history verification pass."""
        self._require_ready()

        def operation(
            conn: sqlite3.Connection, meta: sqlite3.Row, _stamp: float
        ) -> dict[str, object]:
            counts = self._full_audit_conn(conn, meta)
            return {
                "ready": True,
                "verified": True,
                "schema_version": SCHEMA_VERSION,
                "contract_version": CONTRACT_VERSION,
                **counts,
            }

        result = self._run_transaction(operation)
        assert isinstance(result, dict)
        return result


# ---------------------------------------------------------------------------
# Perception-egress gate: the single fail-closed chokepoint every private
# perception provider attempt must pass through before any pixels/audio leave
# the laptop. It wraps one EgressConsentLedger so a caller cannot forget to
# both (a) obtain a fresh interactive creator decision and (b) atomically
# consume exactly one bounded use immediately before the outbound attempt.
# ---------------------------------------------------------------------------


def _perception_payload_metadata(payload: bytes) -> bytes:
    """Derive content-free binding metadata for one exact outbound payload."""
    digest = hashlib.sha256(payload).hexdigest()
    return json.dumps(
        {"sha256": digest, "byte_count": len(payload)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


@dataclass(frozen=True, slots=True)
class PerceptionEgressAuthorization:
    """Attested facts for one permitted remote perception attempt."""

    route_id: str
    provider: str
    deployment: str
    model: str
    capability: str
    purpose: str
    processing_location: str
    destination_class: str
    transport_route: str
    byte_count: int
    attempt_evidence: Mapping[str, object] = field(default_factory=dict)


class PerceptionEgressGate:
    """Fail closed unless an exact route and exact payload receive fresh consent."""

    __slots__ = ("_ledger",)

    def __init__(self, ledger: EgressConsentLedger) -> None:
        if not isinstance(ledger, EgressConsentLedger):
            raise EgressConsentError("invalid_consent_ledger")
        object.__setattr__(self, "_ledger", ledger)

    @property
    def ledger(self) -> EgressConsentLedger:
        return self._ledger

    def authorize_attempt(
        self,
        *,
        operation_id: str,
        route_id: str,
        payload: bytes,
    ) -> PerceptionEgressAuthorization:
        if isinstance(payload, (bytearray, memoryview)):
            payload = bytes(payload)
        if not isinstance(payload, bytes) or not payload:
            raise EgressConsentDenied("payload_missing")
        byte_count = len(payload)
        metadata = _perception_payload_metadata(payload)
        try:
            grant = self._ledger.request_consent(
                operation_id=operation_id,
                route_id=route_id,
                payload_metadata=metadata,
                byte_count=byte_count,
            )
            token = grant.get("token")
            if not grant.get("granted") or not token:
                raise EgressConsentDenied("creator_denied")
            use = self._ledger.consume(
                str(token),
                operation_id=operation_id,
                route_id=route_id,
                payload_metadata=metadata,
                byte_count=byte_count,
            )
        except EgressConsentIntegrityError:
            raise
        except EgressConsentDenied:
            raise
        except EgressConsentError as exc:
            raise EgressConsentDenied(
                _reason(str(exc), fallback="consent_unavailable")
            ) from exc
        route = self._ledger.policy.resolve(route_id)
        evidence = use.get("attempt_evidence")
        return PerceptionEgressAuthorization(
            route_id=route.route_id,
            provider=route.provider,
            deployment=route.deployment,
            model=route.model,
            capability=route.capability,
            purpose=route.purpose,
            processing_location=route.processing_location,
            destination_class=route.destination_class,
            transport_route=route.transport_route,
            byte_count=byte_count,
            attempt_evidence=MappingProxyType(
                dict(evidence) if isinstance(evidence, Mapping) else {}
            ),
        )


__all__ = [
    "ANCHOR_FORMAT_VERSION",
    "CONTRACT_VERSION",
    "MAINTENANCE_BATCH_SIZE",
    "MAX_BYTES_PER_USE",
    "MAX_PAYLOAD_METADATA_BYTES",
    "MAX_TTL_SECONDS",
    "MAX_USES",
    "SCHEMA_VERSION",
    "AllowedEgressRoute",
    "AnchorState",
    "AuthorityRequest",
    "CreatorConsentAuthority",
    "CreatorDecision",
    "EgressConsentDenied",
    "EgressConsentError",
    "EgressConsentIntegrityError",
    "EgressConsentLedger",
    "EgressConsentQuarantined",
    "EgressPolicy",
    "ExternalAnchorError",
    "MonotonicAnchor",
    "PerceptionEgressAuthorization",
    "PerceptionEgressGate",
    "SQLiteMonotonicAnchor",
    "TrustedClock",
]
