"""Anchored, model-free notification outbox core.

This module has no transport client, destination, credential, callback route,
or autonomous trigger. A server-owned policy supplies closed category and
adapter registries. Payloads are represented only by HMAC-authenticated opaque
references minted by this store.

SQLite serializes lifecycle mutations. A required external monotonic anchor
binds the ledger identity, frozen policy, counts, and global receipt-chain head
outside the database so valid-prefix truncation and snapshot rollback fail
closed. Ordinary mutations verify constant-size metadata and chain tails; the
constructor and :meth:`NotificationOutbox.audit` perform a linear full audit.
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
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from alpecca.db import connect


CONTRACT_VERSION = 2
RECEIPT_VERSION = 2

QUEUED = "queued"
LEASED = "leased"
INDETERMINATE = "indeterminate"
SENT = "sent"
ACKNOWLEDGED = "acknowledged"
FAILED = "failed"
CANCELLED = "cancelled"
STATES = (
    QUEUED,
    LEASED,
    INDETERMINATE,
    SENT,
    ACKNOWLEDGED,
    FAILED,
    CANCELLED,
)
_STATE_SET = frozenset(STATES)

_ENQUEUED = "enqueued"
_CLAIMED = "claimed"
_QUIET_DEFERRED = "quiet_deferred"
_POLICY_DEFERRED = "policy_deferred"
_POLICY_FAILED = "policy_failed"
_CLAIM_ABANDONED = "claim_abandoned"
_RETRY_SCHEDULED = "retry_scheduled"
_DELIVERY_FAILED = "delivery_failed"
_DELIVERY_INDETERMINATE = "delivery_indeterminate"
_LEASE_EXPIRED = "lease_expired"
_SENT = "sent"
_RECONCILED_SENT = "reconciled_sent"
_RECONCILED_RETRY = "reconciled_retry"
_RECONCILED_FAILED = "reconciled_failed"
_IDEMPOTENT_RETRY = "idempotent_retry"
_ACKNOWLEDGED = "acknowledged"
_CANCELLED = "cancelled"
_KINDS = frozenset(
    {
        _ENQUEUED,
        _CLAIMED,
        _QUIET_DEFERRED,
        _POLICY_DEFERRED,
        _POLICY_FAILED,
        _CLAIM_ABANDONED,
        _RETRY_SCHEDULED,
        _DELIVERY_FAILED,
        _DELIVERY_INDETERMINATE,
        _LEASE_EXPIRED,
        _SENT,
        _RECONCILED_SENT,
        _RECONCILED_RETRY,
        _RECONCILED_FAILED,
        _IDEMPOTENT_RETRY,
        _ACKNOWLEDGED,
        _CANCELLED,
    }
)

_META_DOMAIN = "alpecca.notification-outbox-meta.v2"
_EVENT_DOMAIN = "alpecca.notification-outbox-event.v2"
_RECEIPT_DOMAIN = "alpecca.notification-outbox-transition.v2"
_IDEMPOTENCY_DOMAIN = b"alpecca.notification-outbox-idempotency.v2\x00"
_PAYLOAD_REF_DOMAIN = b"alpecca.notification-outbox-payload-ref.v2\x00"
_LEASE_DOMAIN = b"alpecca.notification-outbox-lease.v2\x00"
_TRANSPORT_KEY_DOMAIN = b"alpecca.notification-outbox-transport-key.v2\x00"
_TRANSPORT_PROOF_DOMAIN = b"alpecca.notification-outbox-transport-proof.v2\x00"
_TRANSITION_ID_DOMAIN = b"alpecca.notification-outbox-transition-id.v2\x00"
_RECEIPT_CURSOR_DOMAIN = b"alpecca.notification-outbox-receipt-cursor.v2\x00"

_REGISTRY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_POLICY_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_IDEMPOTENCY_RE = re.compile(r"^idem_[0-9a-f]{32,64}$")
_PAYLOAD_REF_RE = re.compile(r"^pref_([0-9a-f]{32})_([0-9a-f]{32})$")
_EVENT_ID_RE = re.compile(r"^out_[0-9a-f]{32}$")
_LEASE_RE = re.compile(r"^lease_[0-9a-f]{64}$")
_TRANSPORT_KEY_RE = re.compile(r"^txi_[0-9a-f]{64}$")
_TRANSITION_ID_RE = re.compile(r"^tr_[0-9a-f]{32}$")
_RECEIPT_CURSOR_RE = re.compile(r"^rc_([1-9][0-9]{0,19})_([0-9a-f]{64})$")
_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SQL_LITERAL_RE = re.compile(r"'(?:''|[^'])*'")
_MAX_CANDIDATES_PER_CLAIM = 256
_EXPIRED_RECOVERY_BATCH_SIZE = 64
_RECEIPT_PAGE_SIZE = 64

_OUTBOX_TABLES = (
    "notification_outbox_meta",
    "notification_outbox_events",
    "notification_outbox_receipts",
)
# SHA-256 fingerprints of canonical sqlite_master DDL created below.
_REQUIRED_SCHEMA = MappingProxyType(
    {
        "notification_outbox_category_idx": (
            "index",
            "notification_outbox_events",
            "adce210a6c15d0bbb1f2484e56f0c002c217cab60db406840f92178f4bf97411",
        ),
        "notification_outbox_claim_policy_idx": (
            "index",
            "notification_outbox_receipts",
            "6e7233f6f1b2347340ca718716d16373b41a465ab12b45a8a6b6a19b272887b4",
        ),
        "notification_outbox_due_idx": (
            "index",
            "notification_outbox_events",
            "77474b515c20f64f6ddf1ad42d6f9afe9ba05e3b3794f2eebb63303781188c7f",
        ),
        "notification_outbox_lease_idx": (
            "index",
            "notification_outbox_events",
            "3dd6ad87720f83aa088e15769db397b3dcb8932970ba6cfd0e35202e87dd373e",
        ),
        "notification_outbox_receipt_event_idx": (
            "index",
            "notification_outbox_receipts",
            "52822db6e3c48f601842de7f28a75e448ed47b20cb09b3c298aad0eb99a3c95b",
        ),
        "notification_outbox_events": (
            "table",
            "notification_outbox_events",
            "621eb5dc9b33c63752e0c9053cf5d38f245d984cd93ecc54eff6d07174b241d7",
        ),
        "notification_outbox_meta": (
            "table",
            "notification_outbox_meta",
            "68f3252e53b576b0282a968336e768d853ed6696a42a5ddca33db9519455f981",
        ),
        "notification_outbox_receipts": (
            "table",
            "notification_outbox_receipts",
            "675bc2096b3be4d1a8cbad1ffa5eef76b65e7d526009710be8b3fa6cf32a9931",
        ),
        "notification_outbox_attempt_guard": (
            "trigger",
            "notification_outbox_events",
            "53a12c288b8d67b65dd75d0fea9033fda8fa86de128b5d1e33742f7d3e9fab9b",
        ),
        "notification_outbox_event_delete_guard": (
            "trigger",
            "notification_outbox_events",
            "544e52461250cd1221fcb27e7363305446fd1fb9143b4feab3a0a9fa8f531944",
        ),
        "notification_outbox_event_facts_immutable": (
            "trigger",
            "notification_outbox_events",
            "f7ffbdbad79a7f3401a8c749676cb27026457676d1704562431ef5df88b036b4",
        ),
        "notification_outbox_lease_shape_guard": (
            "trigger",
            "notification_outbox_events",
            "bb01dcf92a0532f0dbd6ac21680ef2756b317d5c9625372890bd0a31cf8e44de",
        ),
        "notification_outbox_meta_delete_guard": (
            "trigger",
            "notification_outbox_meta",
            "6ca9c5c951d83c113a5001e203361583ad9ee5ae5d79e6c9132879bcc9afce06",
        ),
        "notification_outbox_meta_identity_immutable": (
            "trigger",
            "notification_outbox_meta",
            "791a1b58fcba1d1fa3da6b807e82111be0ad940fd0a64ffc56f2e29827766c7d",
        ),
        "notification_outbox_meta_monotonic": (
            "trigger",
            "notification_outbox_meta",
            "a2fca420f18867b81f72ae11c461197d932f07cef58b4bdcd380e71690c71d42",
        ),
        "notification_outbox_receipt_delete_guard": (
            "trigger",
            "notification_outbox_receipts",
            "1e9f2723ffc49ec43a6a297a072429f0edb664c5f39564c5bfd6d5024d1c63d2",
        ),
        "notification_outbox_receipt_update_guard": (
            "trigger",
            "notification_outbox_receipts",
            "5ad60505abb22bd5e1b36843503e632b103a9e1def3bd58a776bfc5b1f294b98",
        ),
        "notification_outbox_state_guard": (
            "trigger",
            "notification_outbox_events",
            "807344898cbb14277f16aace627fa047c1323863d54b771469cf0dbf7759afd0",
        ),
    }
)


class NotificationOutboxError(ValueError):
    """Base error for malformed or rejected outbox operations."""


class OutboxConflict(NotificationOutboxError):
    """An idempotent replay conflicts with already sealed facts."""


class OutboxNotFound(NotificationOutboxError):
    """No event has the requested outbox-generated identifier."""


class OutboxStateError(NotificationOutboxError):
    """The requested transition is invalid from the current state."""


class OutboxLeaseLost(OutboxStateError):
    """A claim handle is absent, replaced, mismatched, or expired."""


class OutboxPolicyMismatch(NotificationOutboxError):
    """The database was opened with a different policy identity or manifest."""


class OutboxAnchorError(NotificationOutboxError):
    """The required external monotonic anchor rejected an operation."""


class OutboxIntegrityError(NotificationOutboxError):
    """Stored evidence is malformed, missing, orphaned, or unsealed."""


class OutboxQuarantined(OutboxIntegrityError):
    """The store detected rollback or corruption and now fails closed."""


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
        raise NotificationOutboxError("outbox evidence is not canonical JSON") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _schema_fingerprint(sql: str) -> str:
    source = sql.strip().rstrip(";")
    pieces: list[str] = []
    cursor = 0
    for literal in _SQL_LITERAL_RE.finditer(source):
        pieces.append(re.sub(r"\s+", " ", source[cursor : literal.start()]))
        pieces.append(literal.group(0))
        cursor = literal.end()
    pieces.append(re.sub(r"\s+", " ", source[cursor:]))
    normalized = "".join(pieces).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _is_sha256(value: object, *, allow_empty: bool = False) -> bool:
    if allow_empty and value == "":
        return True
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _timestamp(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NotificationOutboxError(f"{name} must be numeric")
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0.0:
        raise NotificationOutboxError(f"{name} must be finite and non-negative")
    return stamp


def _seconds(
    value: object,
    *,
    name: str,
    allow_zero: bool = False,
    maximum: float = 7 * 24 * 60 * 60,
) -> float:
    number = _timestamp(value, name=name)
    if (number == 0.0 and not allow_zero) or number > maximum:
        lower = "zero or greater" if allow_zero else "greater than zero"
        raise NotificationOutboxError(
            f"{name} must be {lower} and at most {maximum:g} seconds"
        )
    return number


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise NotificationOutboxError(f"{name} must be a positive integer")
    return value


def _nonnegative_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NotificationOutboxError(f"{name} must be a non-negative integer")
    return value


def _registry_name(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _REGISTRY_RE.fullmatch(value) is None:
        raise NotificationOutboxError(f"{name} is not a canonical registry key")
    return value


def _policy_id(value: object) -> str:
    if not isinstance(value, str) or _POLICY_ID_RE.fullmatch(value) is None:
        raise NotificationOutboxError("policy_id is invalid")
    return value


def _event_id(value: object) -> str:
    if not isinstance(value, str) or _EVENT_ID_RE.fullmatch(value) is None:
        raise NotificationOutboxError("event_id is invalid")
    return value


def _idempotency_key(value: object) -> str:
    if not isinstance(value, str) or _IDEMPOTENCY_RE.fullmatch(value) is None:
        raise NotificationOutboxError(
            "idempotency_key must be an opaque idem_ key with 32-64 lowercase hex digits"
        )
    return value


def _lease_handle(value: object) -> str:
    if not isinstance(value, str) or _LEASE_RE.fullmatch(value) is None:
        raise OutboxLeaseLost("claim handle is invalid")
    return value


def _transport_key(value: object) -> str:
    if not isinstance(value, str) or _TRANSPORT_KEY_RE.fullmatch(value) is None:
        raise OutboxConflict("transport idempotency key is invalid")
    return value


def _reason(value: object) -> str:
    if not isinstance(value, str) or _REASON_RE.fullmatch(value) is None:
        raise NotificationOutboxError("receipt reason is invalid")
    return value


def _zone(name: object, *, field_name: str) -> ZoneInfo:
    if not isinstance(name, str) or not name or len(name) > 80:
        raise NotificationOutboxError(f"{field_name} must be an IANA timezone name")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise NotificationOutboxError(
            f"{field_name} must be an installed IANA timezone name"
        ) from exc


@dataclass(frozen=True, slots=True)
class OpaquePayloadRef:
    """Server-minted, content-free handle to caller-owned payload storage."""

    value: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    """Private adapter claim; its bearer is intentionally absent from public DTOs."""

    event_id: str
    category: str
    adapter_name: str
    payload_ref: OpaquePayloadRef = field(repr=False)
    transport_idempotency_key: str
    claim_handle: str = field(repr=False)
    lease_expires_at: float
    attempt_count: int


@dataclass(frozen=True, slots=True)
class LedgerCheckpoint:
    """Exact external anchor value for one committed ledger checkpoint."""

    ledger_id: str
    contract_version: int
    policy_id: str
    policy_version: int
    policy_digest: str
    sequence: int
    event_count: int
    receipt_count: int
    global_head_seal: str
    meta_seal: str


@dataclass(frozen=True, slots=True)
class AnchorSnapshot:
    current: LedgerCheckpoint | None
    pending: LedgerCheckpoint | None


@runtime_checkable
class MonotonicAnchor(Protocol):
    """External two-phase anchor; implementations must persist outside SQLite."""

    def snapshot(self) -> AnchorSnapshot: ...

    def prepare(
        self,
        expected: LedgerCheckpoint | None,
        candidate: LedgerCheckpoint,
    ) -> None: ...

    def commit(self, candidate: LedgerCheckpoint) -> None: ...

    def abort(self, candidate: LedgerCheckpoint) -> None: ...


class InMemoryMonotonicAnchor:
    """Thread-safe process-local anchor for deterministic tests, not deployment."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current: LedgerCheckpoint | None = None
        self._pending: LedgerCheckpoint | None = None

    def snapshot(self) -> AnchorSnapshot:
        with self._lock:
            return AnchorSnapshot(self._current, self._pending)

    @staticmethod
    def _validate_progress(
        expected: LedgerCheckpoint | None,
        candidate: LedgerCheckpoint,
    ) -> None:
        if candidate.sequence != candidate.receipt_count:
            raise OutboxAnchorError("anchor sequence and receipt count differ")
        if expected is None:
            if candidate.sequence != 0 or candidate.event_count != 0:
                raise OutboxAnchorError("initial anchor checkpoint is not empty")
            return
        immutable = (
            "ledger_id",
            "contract_version",
            "policy_id",
            "policy_version",
            "policy_digest",
        )
        if any(getattr(candidate, name) != getattr(expected, name) for name in immutable):
            raise OutboxAnchorError("anchor identity or policy changed")
        if (
            candidate.sequence <= expected.sequence
            or candidate.receipt_count <= expected.receipt_count
            or candidate.event_count < expected.event_count
        ):
            raise OutboxAnchorError("anchor checkpoint did not advance monotonically")

    def prepare(
        self,
        expected: LedgerCheckpoint | None,
        candidate: LedgerCheckpoint,
    ) -> None:
        with self._lock:
            if self._pending is not None:
                raise OutboxAnchorError("anchor already has a pending checkpoint")
            if self._current != expected:
                raise OutboxAnchorError("anchor current checkpoint changed")
            self._validate_progress(expected, candidate)
            self._pending = candidate

    def commit(self, candidate: LedgerCheckpoint) -> None:
        with self._lock:
            if self._pending is None and self._current == candidate:
                return
            if self._pending != candidate:
                raise OutboxAnchorError("anchor pending checkpoint does not match")
            self._current = candidate
            self._pending = None

    def abort(self, candidate: LedgerCheckpoint) -> None:
        with self._lock:
            if self._pending == candidate:
                self._pending = None
            elif self._pending is not None:
                raise OutboxAnchorError("cannot abort a different anchor checkpoint")


@dataclass(frozen=True, slots=True)
class QuietHours:
    """Quiet interval evaluated in an IANA timezone, including DST transitions."""

    timezone_name: str
    start_minute: int
    end_minute: int

    def __post_init__(self) -> None:
        _zone(self.timezone_name, field_name="quiet-hours timezone")
        for name, value in (
            ("start_minute", self.start_minute),
            ("end_minute", self.end_minute),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 1440:
                raise NotificationOutboxError(f"{name} must be between 0 and 1439")
        if self.start_minute == self.end_minute:
            raise NotificationOutboxError("quiet hours cannot be an ambiguous full day")

    def _is_quiet_minute(self, minute: int) -> bool:
        if self.start_minute < self.end_minute:
            return self.start_minute <= minute < self.end_minute
        return minute >= self.start_minute or minute < self.end_minute

    def defer_until(self, timestamp: float) -> float | None:
        stamp = _timestamp(timestamp, name="quiet-hours timestamp")
        zone = _zone(self.timezone_name, field_name="quiet-hours timezone")
        current_utc = datetime.fromtimestamp(stamp, timezone.utc)
        local = current_utc.astimezone(zone)
        minute = local.hour * 60 + local.minute
        if not self._is_quiet_minute(minute):
            return None

        # Search UTC minute boundaries. Local arithmetic is wrong at DST gaps
        # and folds; UTC progression with local projection handles both.
        candidate = current_utc.replace(second=0, microsecond=0)
        if candidate <= current_utc:
            candidate += timedelta(minutes=1)
        for _ in range(27 * 60):
            projected = candidate.astimezone(zone)
            projected_minute = projected.hour * 60 + projected.minute
            if not self._is_quiet_minute(projected_minute):
                return candidate.timestamp()
            candidate += timedelta(minutes=1)
        raise NotificationOutboxError("quiet-hours interval did not terminate")

    def manifest(self) -> dict[str, object]:
        return {
            "timezone_name": self.timezone_name,
            "start_minute": self.start_minute,
            "end_minute": self.end_minute,
        }


def _registry(value: object, *, name: str) -> frozenset[str]:
    if isinstance(value, (str, bytes)):
        raise NotificationOutboxError(f"{name} must be a set of canonical keys")
    try:
        clean = frozenset(_registry_name(item, name=f"{name} entry") for item in value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise NotificationOutboxError(f"{name} must be iterable") from exc
    if not clean:
        raise NotificationOutboxError(f"{name} must not be empty")
    return clean


def _exact_map(
    value: object,
    *,
    registry: frozenset[str],
    name: str,
    value_kind: Literal["limit", "cost", "bool"],
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise NotificationOutboxError(f"{name} must be a mapping")
    if set(value) != set(registry):
        raise NotificationOutboxError(f"{name} must exactly cover its registry")
    clean: dict[str, object] = {}
    for key in sorted(registry):
        raw = value[key]
        if value_kind == "limit":
            clean[key] = None if raw is None else _positive_int(raw, name=f"{name}[{key!r}]")
        elif value_kind == "cost":
            clean[key] = _nonnegative_int(raw, name=f"{name}[{key!r}]")
        else:
            if not isinstance(raw, bool):
                raise NotificationOutboxError(f"{name}[{key!r}] must be boolean")
            clean[key] = raw
    return MappingProxyType(clean)


@dataclass(frozen=True, slots=True)
class OutboxPolicy:
    """Frozen server-owned registry and scheduling policy."""

    policy_id: str
    policy_version: int
    category_registry: frozenset[str]
    adapter_registry: frozenset[str]
    category_quotas: Mapping[str, int | None]
    channel_quotas: Mapping[str, int | None]
    channel_costs: Mapping[str, int]
    adapter_transport_idempotency: Mapping[str, bool]
    max_attempts: int = 3
    lease_seconds: float = 60.0
    backoff_initial_seconds: float = 30.0
    backoff_multiplier: float = 2.0
    backoff_max_seconds: float = 3600.0
    quota_window_seconds: float = 3600.0
    global_quota: int | None = None
    daily_cost_cap: int | None = None
    quiet_hours: QuietHours | None = None
    accounting_timezone: str = "UTC"

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _policy_id(self.policy_id))
        object.__setattr__(
            self,
            "policy_version",
            _positive_int(self.policy_version, name="policy_version"),
        )
        categories = _registry(self.category_registry, name="category_registry")
        adapters = _registry(self.adapter_registry, name="adapter_registry")
        object.__setattr__(self, "category_registry", categories)
        object.__setattr__(self, "adapter_registry", adapters)
        object.__setattr__(
            self,
            "category_quotas",
            _exact_map(
                self.category_quotas,
                registry=categories,
                name="category_quotas",
                value_kind="limit",
            ),
        )
        object.__setattr__(
            self,
            "channel_quotas",
            _exact_map(
                self.channel_quotas,
                registry=adapters,
                name="channel_quotas",
                value_kind="limit",
            ),
        )
        object.__setattr__(
            self,
            "channel_costs",
            _exact_map(
                self.channel_costs,
                registry=adapters,
                name="channel_costs",
                value_kind="cost",
            ),
        )
        object.__setattr__(
            self,
            "adapter_transport_idempotency",
            _exact_map(
                self.adapter_transport_idempotency,
                registry=adapters,
                name="adapter_transport_idempotency",
                value_kind="bool",
            ),
        )
        object.__setattr__(
            self, "max_attempts", _positive_int(self.max_attempts, name="max_attempts")
        )
        object.__setattr__(
            self,
            "lease_seconds",
            _seconds(self.lease_seconds, name="lease_seconds", maximum=86400),
        )
        initial = _seconds(
            self.backoff_initial_seconds,
            name="backoff_initial_seconds",
            allow_zero=True,
        )
        maximum = _seconds(
            self.backoff_max_seconds,
            name="backoff_max_seconds",
            allow_zero=True,
        )
        if initial > maximum:
            raise NotificationOutboxError(
                "backoff_initial_seconds must not exceed backoff_max_seconds"
            )
        object.__setattr__(self, "backoff_initial_seconds", initial)
        object.__setattr__(self, "backoff_max_seconds", maximum)
        if (
            isinstance(self.backoff_multiplier, bool)
            or not isinstance(self.backoff_multiplier, (int, float))
            or not math.isfinite(float(self.backoff_multiplier))
            or not 1.0 <= float(self.backoff_multiplier) <= 100.0
        ):
            raise NotificationOutboxError(
                "backoff_multiplier must be finite and between 1 and 100"
            )
        object.__setattr__(self, "backoff_multiplier", float(self.backoff_multiplier))
        object.__setattr__(
            self,
            "quota_window_seconds",
            _seconds(self.quota_window_seconds, name="quota_window_seconds"),
        )
        if self.global_quota is not None:
            object.__setattr__(
                self,
                "global_quota",
                _positive_int(self.global_quota, name="global_quota"),
            )
        if self.daily_cost_cap is not None:
            object.__setattr__(
                self,
                "daily_cost_cap",
                _nonnegative_int(self.daily_cost_cap, name="daily_cost_cap"),
            )
        if self.quiet_hours is not None and not isinstance(self.quiet_hours, QuietHours):
            raise NotificationOutboxError("quiet_hours must be QuietHours or null")
        _zone(self.accounting_timezone, field_name="accounting_timezone")

    def manifest(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "category_registry": sorted(self.category_registry),
            "adapter_registry": sorted(self.adapter_registry),
            "category_quotas": dict(self.category_quotas),
            "channel_quotas": dict(self.channel_quotas),
            "channel_costs": dict(self.channel_costs),
            "adapter_transport_idempotency": dict(
                self.adapter_transport_idempotency
            ),
            "max_attempts": self.max_attempts,
            "lease_seconds": self.lease_seconds,
            "backoff_initial_seconds": self.backoff_initial_seconds,
            "backoff_multiplier": self.backoff_multiplier,
            "backoff_max_seconds": self.backoff_max_seconds,
            "quota_window_seconds": self.quota_window_seconds,
            "global_quota": self.global_quota,
            "daily_cost_cap": self.daily_cost_cap,
            "quiet_hours": (
                None if self.quiet_hours is None else self.quiet_hours.manifest()
            ),
            "accounting_timezone": self.accounting_timezone,
        }

    @property
    def digest(self) -> str:
        return _sha256(self.manifest())

    def require_category(self, value: object) -> str:
        clean = _registry_name(value, name="category")
        if clean not in self.category_registry:
            raise NotificationOutboxError("category is not in the server registry")
        return clean

    def require_adapter(self, value: object) -> str:
        clean = _registry_name(value, name="adapter_name")
        if clean not in self.adapter_registry:
            raise NotificationOutboxError("adapter_name is not in the server registry")
        return clean

    def cost_for(self, adapter_name: str) -> int:
        return int(self.channel_costs[adapter_name])

    def supports_transport_idempotency(self, adapter_name: str) -> bool:
        return bool(self.adapter_transport_idempotency[adapter_name])

    def backoff_seconds(self, attempt_count: int) -> float:
        attempt = _positive_int(attempt_count, name="attempt_count")
        if self.backoff_initial_seconds == 0.0:
            return 0.0
        try:
            delay = self.backoff_initial_seconds * (
                self.backoff_multiplier ** (attempt - 1)
            )
        except OverflowError:
            delay = self.backoff_max_seconds
        return float(min(delay, self.backoff_max_seconds))

    def day_bounds(self, timestamp: float) -> tuple[float, float]:
        stamp = _timestamp(timestamp, name="accounting timestamp")
        zone = _zone(self.accounting_timezone, field_name="accounting_timezone")
        local = datetime.fromtimestamp(stamp, timezone.utc).astimezone(zone)
        start_local = datetime.combine(local.date(), datetime_time.min, tzinfo=zone)
        end_local = datetime.combine(
            local.date() + timedelta(days=1), datetime_time.min, tzinfo=zone
        )
        return start_local.timestamp(), end_local.timestamp()


class NotificationOutbox:
    """Anchored SQLite outbox with private lease and transport contracts."""

    _DEPENDENCY_ALIASES = frozenset(
        {"policy", "_policy_digest", "_anchor", "_clock"}
    )
    _DEPENDENCY_STORAGE = frozenset(
        {
            "_NotificationOutbox__policy",
            "_NotificationOutbox__policy_digest",
            "_NotificationOutbox__anchor",
            "_NotificationOutbox__clock",
        }
    )

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._DEPENDENCY_ALIASES or (
            name in self._DEPENDENCY_STORAGE and name in self.__dict__
        ):
            raise AttributeError(f"{name} is a read-only constructor dependency")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if name in self._DEPENDENCY_ALIASES or name in self._DEPENDENCY_STORAGE:
            raise AttributeError(f"{name} is a read-only constructor dependency")
        object.__delattr__(self, name)

    def __init__(
        self,
        db_path: Path,
        *,
        seal_key: bytes | bytearray | memoryview | str,
        policy: OutboxPolicy,
        anchor: MonotonicAnchor,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db_path = Path(db_path)
        if isinstance(seal_key, str):
            seal_key = seal_key.encode("utf-8")
        if not isinstance(seal_key, (bytes, bytearray, memoryview)):
            raise TypeError("seal_key must be bytes or text")
        self._key = bytes(seal_key)
        if not self._key:
            raise NotificationOutboxError("seal_key must not be empty")
        if not isinstance(policy, OutboxPolicy):
            raise NotificationOutboxError("policy must be OutboxPolicy")
        if not isinstance(anchor, MonotonicAnchor):
            raise NotificationOutboxError("anchor must implement MonotonicAnchor")
        if not callable(clock):
            raise NotificationOutboxError("clock must be callable")
        self.__policy = policy
        self.__policy_digest = policy.digest
        self.__anchor = anchor
        self.__clock = clock
        self._quarantined = False
        self._ledger_id = ""
        try:
            self._ensure_schema()
        except sqlite3.DatabaseError as exc:
            self._fail_closed("database schema is incompatible or corrupt", exc)
        self._open_or_initialize()

    @property
    def policy(self) -> OutboxPolicy:
        return self.__policy

    @property
    def _policy_digest(self) -> str:
        return self.__policy_digest

    @property
    def _anchor(self) -> MonotonicAnchor:
        return self.__anchor

    @property
    def _clock(self) -> Callable[[], float]:
        return self.__clock

    @property
    def quarantined(self) -> bool:
        return self._quarantined

    def _fail_closed(self, reason: str, cause: BaseException | None = None) -> None:
        self._quarantined = True
        error = OutboxQuarantined(f"notification outbox quarantined: {reason}")
        if cause is None:
            raise error
        raise error from cause

    def _require_available(self) -> None:
        if self._quarantined:
            raise OutboxQuarantined("notification outbox is quarantined")

    def _seal(self, domain: str, material: Mapping[str, object]) -> str:
        encoded = _canonical({"domain": domain, **dict(material)}).encode("utf-8")
        return hmac.new(self._key, encoded, hashlib.sha256).hexdigest()

    def _domain_hmac(self, domain: bytes, value: str) -> str:
        return hmac.new(
            self._key, domain + value.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def mint_payload_ref(self) -> OpaquePayloadRef:
        """Mint a content-free reference; it conveys no path, URL, or identifier."""
        self._require_available()
        if not self._ledger_id:
            raise OutboxIntegrityError("outbox ledger identity is unavailable")
        nonce = secrets.token_hex(16)
        tag = self._domain_hmac(
            _PAYLOAD_REF_DOMAIN, f"{self._ledger_id}\x00{nonce}"
        )[:32]
        return OpaquePayloadRef(f"pref_{nonce}_{tag}")

    def _validate_payload_ref(self, value: object) -> str:
        if not isinstance(value, OpaquePayloadRef):
            raise NotificationOutboxError(
                "payload_ref must be an OpaquePayloadRef minted by this store"
            )
        match = _PAYLOAD_REF_RE.fullmatch(value.value)
        if match is None:
            raise NotificationOutboxError("payload_ref is not an opaque server reference")
        nonce, supplied = match.groups()
        expected = self._domain_hmac(
            _PAYLOAD_REF_DOMAIN, f"{self._ledger_id}\x00{nonce}"
        )[:32]
        if not hmac.compare_digest(expected, supplied):
            raise NotificationOutboxError("payload_ref was not minted by this store")
        return value.value

    def _idempotency_hmac(self, key: str) -> str:
        return self._domain_hmac(_IDEMPOTENCY_DOMAIN, key)

    def _lease_hmac(self, handle: str) -> str:
        return self._domain_hmac(_LEASE_DOMAIN, handle)

    def _transport_idempotency_key(self, event_id: str) -> str:
        return "txi_" + self._domain_hmac(
            _TRANSPORT_KEY_DOMAIN, f"{self._ledger_id}\x00{event_id}"
        )

    def _transport_key_hmac(self, key: str) -> str:
        return self._domain_hmac(_TRANSPORT_PROOF_DOMAIN, key)

    def _receipt_cursor(
        self,
        event_id: str,
        event_sequence: int,
        receipt_seal: str,
    ) -> str:
        value = (
            f"{self._ledger_id}\x00{event_id}\x00{event_sequence}\x00{receipt_seal}"
        )
        return f"rc_{event_sequence}_{self._domain_hmac(_RECEIPT_CURSOR_DOMAIN, value)}"

    @staticmethod
    def _receipt_cursor_sequence(cursor: object) -> int:
        if not isinstance(cursor, str):
            raise OutboxConflict("receipt cursor is invalid")
        match = _RECEIPT_CURSOR_RE.fullmatch(cursor)
        if match is None:
            raise OutboxConflict("receipt cursor is invalid")
        return int(match.group(1))

    def _ensure_schema(self) -> None:
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            required_names = tuple(_REQUIRED_SCHEMA)
            slots = ",".join("?" for _name in required_names)
            existing = conn.execute(
                f"SELECT 1 FROM sqlite_master WHERE name IN ({slots}) LIMIT 1",
                required_names,
            ).fetchone()
            if existing is not None:
                self._verify_schema_locked(conn)
                return
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS notification_outbox_meta (
                    singleton          INTEGER PRIMARY KEY CHECK(singleton=1),
                    contract_version   INTEGER NOT NULL CHECK(contract_version=2),
                    ledger_id          TEXT NOT NULL UNIQUE,
                    policy_id          TEXT NOT NULL,
                    policy_version     INTEGER NOT NULL CHECK(policy_version>0),
                    policy_digest      TEXT NOT NULL,
                    sequence           INTEGER NOT NULL CHECK(sequence>=0),
                    event_count        INTEGER NOT NULL CHECK(event_count>=0),
                    receipt_count      INTEGER NOT NULL CHECK(receipt_count>=0),
                    global_head_seal   TEXT NOT NULL,
                    meta_seal          TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notification_outbox_events (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    contract_version      INTEGER NOT NULL CHECK(contract_version=2),
                    event_id              TEXT NOT NULL UNIQUE,
                    idempotency_hmac      TEXT NOT NULL UNIQUE,
                    policy_id             TEXT NOT NULL,
                    policy_version        INTEGER NOT NULL,
                    policy_digest         TEXT NOT NULL,
                    category              TEXT NOT NULL,
                    adapter_name          TEXT NOT NULL,
                    payload_ref           TEXT NOT NULL,
                    transport_key_hmac    TEXT NOT NULL,
                    state                 TEXT NOT NULL CHECK(state IN (
                        'queued','leased','indeterminate','sent',
                        'acknowledged','failed','cancelled'
                    )),
                    created_at            REAL NOT NULL,
                    updated_at            REAL NOT NULL,
                    next_attempt_at       REAL NOT NULL,
                    attempt_count         INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
                    max_attempts          INTEGER NOT NULL CHECK(max_attempts>0),
                    cost_units            INTEGER NOT NULL CHECK(cost_units>=0),
                    lease_hmac            TEXT,
                    lease_expires_at      REAL,
                    indeterminate_at      REAL,
                    sent_at               REAL,
                    acknowledged_at       REAL,
                    failed_at             REAL,
                    cancelled_at          REAL,
                    event_receipt_count   INTEGER NOT NULL DEFAULT 0 CHECK(event_receipt_count>=0),
                    event_head_seal       TEXT NOT NULL DEFAULT '',
                    event_seal            TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notification_outbox_receipts (
                    receipt_id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_version       INTEGER NOT NULL CHECK(receipt_version=2),
                    global_sequence       INTEGER NOT NULL UNIQUE CHECK(global_sequence>0),
                    transition_id         TEXT NOT NULL UNIQUE,
                    event_id              TEXT NOT NULL,
                    event_sequence        INTEGER NOT NULL CHECK(event_sequence>0),
                    policy_id             TEXT NOT NULL,
                    policy_version        INTEGER NOT NULL,
                    policy_digest         TEXT NOT NULL,
                    kind                  TEXT NOT NULL CHECK(kind IN (
                        'enqueued','claimed','quiet_deferred','policy_deferred',
                        'policy_failed','claim_abandoned','retry_scheduled','delivery_failed',
                        'delivery_indeterminate','lease_expired','sent',
                        'reconciled_sent','reconciled_retry','reconciled_failed',
                        'idempotent_retry','acknowledged','cancelled'
                    )),
                    from_state            TEXT CHECK(from_state IS NULL OR from_state IN (
                        'queued','leased','indeterminate','sent',
                        'acknowledged','failed','cancelled'
                    )),
                    to_state              TEXT NOT NULL CHECK(to_state IN (
                        'queued','leased','indeterminate','sent',
                        'acknowledged','failed','cancelled'
                    )),
                    occurred_at           REAL NOT NULL,
                    created_at            REAL NOT NULL,
                    attempt_count         INTEGER NOT NULL CHECK(attempt_count>=0),
                    lease_hmac            TEXT,
                    lease_expires_at      REAL,
                    next_attempt_at       REAL NOT NULL,
                    indeterminate_at      REAL,
                    sent_at               REAL,
                    acknowledged_at       REAL,
                    failed_at             REAL,
                    cancelled_at          REAL,
                    cost_units            INTEGER NOT NULL CHECK(cost_units>=0),
                    reason_code           TEXT NOT NULL,
                    transport_key_hmac    TEXT NOT NULL,
                    previous_event_seal   TEXT NOT NULL,
                    previous_global_seal  TEXT NOT NULL,
                    receipt_seal          TEXT NOT NULL,
                    UNIQUE(event_id, event_sequence),
                    FOREIGN KEY(event_id) REFERENCES notification_outbox_events(event_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS notification_outbox_due_idx
                    ON notification_outbox_events(adapter_name, state, next_attempt_at, id);
                CREATE INDEX IF NOT EXISTS notification_outbox_lease_idx
                    ON notification_outbox_events(state, lease_expires_at);
                CREATE INDEX IF NOT EXISTS notification_outbox_category_idx
                    ON notification_outbox_events(category, state, created_at);
                CREATE INDEX IF NOT EXISTS notification_outbox_receipt_event_idx
                    ON notification_outbox_receipts(event_id, event_sequence);
                CREATE INDEX IF NOT EXISTS notification_outbox_claim_policy_idx
                    ON notification_outbox_receipts(kind, occurred_at, cost_units);

                CREATE TRIGGER IF NOT EXISTS notification_outbox_meta_identity_immutable
                BEFORE UPDATE OF
                    contract_version,ledger_id,policy_id,policy_version,policy_digest
                ON notification_outbox_meta
                BEGIN
                    SELECT RAISE(ABORT, 'notification outbox policy identity is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS notification_outbox_meta_monotonic
                BEFORE UPDATE OF sequence,event_count,receipt_count ON notification_outbox_meta
                WHEN
                    NEW.sequence < OLD.sequence OR
                    NEW.event_count < OLD.event_count OR
                    NEW.receipt_count < OLD.receipt_count OR
                    NEW.sequence != NEW.receipt_count
                BEGIN
                    SELECT RAISE(ABORT, 'notification outbox metadata is not monotonic');
                END;
                CREATE TRIGGER IF NOT EXISTS notification_outbox_meta_delete_guard
                BEFORE DELETE ON notification_outbox_meta
                BEGIN
                    SELECT RAISE(ABORT, 'notification outbox metadata is durable evidence');
                END;

                CREATE TRIGGER IF NOT EXISTS notification_outbox_event_facts_immutable
                BEFORE UPDATE OF
                    contract_version,event_id,idempotency_hmac,policy_id,policy_version,
                    policy_digest,category,adapter_name,payload_ref,transport_key_hmac,
                    created_at,max_attempts,cost_units,event_seal
                ON notification_outbox_events
                BEGIN
                    SELECT RAISE(ABORT, 'notification outbox event facts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS notification_outbox_state_guard
                BEFORE UPDATE OF state ON notification_outbox_events
                WHEN OLD.state != NEW.state AND NOT (
                    (OLD.state='queued' AND NEW.state IN ('leased','failed','cancelled')) OR
                    (OLD.state='leased' AND NEW.state IN (
                        'queued','indeterminate','sent','failed'
                    )) OR
                    (OLD.state='indeterminate' AND NEW.state IN (
                        'queued','sent','failed','cancelled'
                    )) OR
                    (OLD.state='sent' AND NEW.state='acknowledged')
                )
                BEGIN
                    SELECT RAISE(ABORT, 'illegal notification outbox transition');
                END;
                CREATE TRIGGER IF NOT EXISTS notification_outbox_attempt_guard
                BEFORE UPDATE OF attempt_count ON notification_outbox_events
                WHEN
                    NEW.attempt_count < OLD.attempt_count OR
                    NEW.attempt_count > OLD.attempt_count + 1 OR
                    (NEW.attempt_count = OLD.attempt_count + 1 AND NEW.state != 'leased')
                BEGIN
                    SELECT RAISE(ABORT, 'notification outbox attempts are not monotonic');
                END;
                CREATE TRIGGER IF NOT EXISTS notification_outbox_lease_shape_guard
                BEFORE UPDATE OF state,lease_hmac,lease_expires_at ON notification_outbox_events
                WHEN
                    (NEW.state='leased' AND (
                        NEW.lease_hmac IS NULL OR NEW.lease_expires_at IS NULL
                    )) OR
                    (NEW.state!='leased' AND (
                        NEW.lease_hmac IS NOT NULL OR NEW.lease_expires_at IS NOT NULL
                    ))
                BEGIN
                    SELECT RAISE(ABORT, 'notification outbox lease shape is invalid');
                END;
                CREATE TRIGGER IF NOT EXISTS notification_outbox_event_delete_guard
                BEFORE DELETE ON notification_outbox_events
                BEGIN
                    SELECT RAISE(ABORT, 'notification outbox events are durable evidence');
                END;

                CREATE TRIGGER IF NOT EXISTS notification_outbox_receipt_update_guard
                BEFORE UPDATE ON notification_outbox_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'notification outbox receipts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS notification_outbox_receipt_delete_guard
                BEFORE DELETE ON notification_outbox_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'notification outbox receipts are immutable');
                END;
                """
            )
            self._verify_schema_locked(conn)

    def _verify_schema_locked(self, conn: sqlite3.Connection) -> None:
        required_names = tuple(_REQUIRED_SCHEMA)
        name_slots = ",".join("?" for _name in required_names)
        table_slots = ",".join("?" for _table in _OUTBOX_TABLES)
        rows = conn.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE "
            f"name IN ({name_slots}) OR ("
            "type IN ('index','trigger') AND "
            f"tbl_name IN ({table_slots}) AND sql IS NOT NULL)",
            required_names + _OUTBOX_TABLES,
        ).fetchall()
        actual: dict[str, tuple[str, str, str]] = {}
        for row in rows:
            name = str(row["name"])
            sql = row["sql"]
            if name in actual or not isinstance(sql, str):
                self._fail_closed("database schema object set is invalid")
            actual[name] = (
                str(row["type"]),
                str(row["tbl_name"]),
                _schema_fingerprint(sql),
            )
        if actual != dict(_REQUIRED_SCHEMA):
            self._fail_closed(
                "database schema definitions do not match the outbox contract"
            )

    @staticmethod
    def _meta_material(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "contract_version": int(row["contract_version"]),
            "ledger_id": str(row["ledger_id"]),
            "policy_id": str(row["policy_id"]),
            "policy_version": int(row["policy_version"]),
            "policy_digest": str(row["policy_digest"]),
            "sequence": int(row["sequence"]),
            "event_count": int(row["event_count"]),
            "receipt_count": int(row["receipt_count"]),
            "global_head_seal": str(row["global_head_seal"]),
        }

    @staticmethod
    def _event_material(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "contract_version": int(row["contract_version"]),
            "event_id": str(row["event_id"]),
            "idempotency_hmac": str(row["idempotency_hmac"]),
            "policy_id": str(row["policy_id"]),
            "policy_version": int(row["policy_version"]),
            "policy_digest": str(row["policy_digest"]),
            "category": str(row["category"]),
            "adapter_name": str(row["adapter_name"]),
            "payload_ref": str(row["payload_ref"]),
            "transport_key_hmac": str(row["transport_key_hmac"]),
            "created_at": float(row["created_at"]),
            "max_attempts": int(row["max_attempts"]),
            "cost_units": int(row["cost_units"]),
        }

    @staticmethod
    def _receipt_material(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "receipt_version": int(row["receipt_version"]),
            "global_sequence": int(row["global_sequence"]),
            "transition_id": str(row["transition_id"]),
            "event_id": str(row["event_id"]),
            "event_sequence": int(row["event_sequence"]),
            "policy_id": str(row["policy_id"]),
            "policy_version": int(row["policy_version"]),
            "policy_digest": str(row["policy_digest"]),
            "kind": str(row["kind"]),
            "from_state": None if row["from_state"] is None else str(row["from_state"]),
            "to_state": str(row["to_state"]),
            "occurred_at": float(row["occurred_at"]),
            "created_at": float(row["created_at"]),
            "attempt_count": int(row["attempt_count"]),
            "lease_hmac": None if row["lease_hmac"] is None else str(row["lease_hmac"]),
            "lease_expires_at": (
                None
                if row["lease_expires_at"] is None
                else float(row["lease_expires_at"])
            ),
            "next_attempt_at": float(row["next_attempt_at"]),
            "indeterminate_at": (
                None
                if row["indeterminate_at"] is None
                else float(row["indeterminate_at"])
            ),
            "sent_at": None if row["sent_at"] is None else float(row["sent_at"]),
            "acknowledged_at": (
                None
                if row["acknowledged_at"] is None
                else float(row["acknowledged_at"])
            ),
            "failed_at": None if row["failed_at"] is None else float(row["failed_at"]),
            "cancelled_at": (
                None
                if row["cancelled_at"] is None
                else float(row["cancelled_at"])
            ),
            "cost_units": int(row["cost_units"]),
            "reason_code": str(row["reason_code"]),
            "transport_key_hmac": str(row["transport_key_hmac"]),
            "previous_event_seal": str(row["previous_event_seal"]),
            "previous_global_seal": str(row["previous_global_seal"]),
        }

    def _verify_meta(self, row: sqlite3.Row) -> LedgerCheckpoint:
        try:
            material = self._meta_material(row)
            expected = self._seal(_META_DOMAIN, material)
        except Exception as exc:
            self._fail_closed("metadata is malformed", exc)
        if (
            material["contract_version"] != CONTRACT_VERSION
            or material["sequence"] != material["receipt_count"]
            or material["sequence"] < 0
            or material["event_count"] < 0
            or not _is_sha256(material["policy_digest"])
            or not _is_sha256(material["global_head_seal"], allow_empty=True)
            or not _is_sha256(row["meta_seal"])
            or not hmac.compare_digest(expected, str(row["meta_seal"]))
        ):
            self._fail_closed("metadata seal or counters are invalid")
        if (
            material["policy_id"] != self.policy.policy_id
            or material["policy_version"] != self.policy.policy_version
            or material["policy_digest"] != self._policy_digest
        ):
            self._quarantined = True
            raise OutboxPolicyMismatch(
                "notification outbox policy identity, version, or manifest differs"
            )
        return LedgerCheckpoint(
            ledger_id=str(material["ledger_id"]),
            contract_version=CONTRACT_VERSION,
            policy_id=self.policy.policy_id,
            policy_version=self.policy.policy_version,
            policy_digest=self._policy_digest,
            sequence=int(material["sequence"]),
            event_count=int(material["event_count"]),
            receipt_count=int(material["receipt_count"]),
            global_head_seal=str(material["global_head_seal"]),
            meta_seal=str(row["meta_seal"]),
        )

    def _get_checkpoint(self, conn: sqlite3.Connection) -> LedgerCheckpoint:
        row = conn.execute(
            "SELECT * FROM notification_outbox_meta WHERE singleton=1"
        ).fetchone()
        if row is None:
            self._fail_closed("metadata row is missing")
        return self._verify_meta(row)

    def _anchor_snapshot(self) -> AnchorSnapshot:
        try:
            snapshot = self._anchor.snapshot()
        except Exception as exc:
            self._fail_closed("external anchor snapshot failed", exc)
        if not isinstance(snapshot, AnchorSnapshot):
            self._fail_closed("external anchor returned an invalid snapshot")
        return snapshot

    def _reconcile_anchor_locked(self, conn: sqlite3.Connection) -> LedgerCheckpoint:
        self._verify_schema_locked(conn)
        checkpoint = self._get_checkpoint(conn)
        snapshot = self._anchor_snapshot()
        if snapshot.pending is not None:
            try:
                if snapshot.pending == checkpoint:
                    self._finalize_anchor(
                        checkpoint,
                        reason="external anchor reconciliation failed",
                    )
                elif snapshot.current == checkpoint:
                    self._anchor.abort(snapshot.pending)
                else:
                    self._fail_closed("database does not match either anchor checkpoint")
            except OutboxQuarantined:
                raise
            except Exception as exc:
                self._fail_closed("external anchor reconciliation failed", exc)
            snapshot = self._anchor_snapshot()
        if snapshot.current != checkpoint or snapshot.pending is not None:
            self._fail_closed("database checkpoint does not match external anchor")
        return checkpoint

    def _verify_global_tail_locked(
        self, conn: sqlite3.Connection, checkpoint: LedgerCheckpoint
    ) -> None:
        tail = conn.execute(
            "SELECT * FROM notification_outbox_receipts "
            "ORDER BY global_sequence DESC LIMIT 1"
        ).fetchone()
        if checkpoint.receipt_count == 0:
            if tail is not None or checkpoint.global_head_seal != "":
                self._fail_closed("empty ledger has receipt evidence")
            return
        if (
            tail is None
            or int(tail["global_sequence"]) != checkpoint.receipt_count
            or str(tail["receipt_seal"]) != checkpoint.global_head_seal
        ):
            self._fail_closed("global receipt tail was truncated or replaced")
        self._verify_receipt(tail)

    def _preflight_locked(self, conn: sqlite3.Connection) -> LedgerCheckpoint:
        self._require_available()
        checkpoint = self._reconcile_anchor_locked(conn)
        self._verify_global_tail_locked(conn, checkpoint)
        return checkpoint

    def _sample_clock_locked(
        self,
        conn: sqlite3.Connection,
        *,
        not_before: float | None = None,
    ) -> float:
        if not conn.in_transaction:
            raise OutboxIntegrityError("trusted clock sampled outside a write transaction")
        try:
            value = self._clock()
            stamp = _timestamp(value, name="trusted clock")
        except Exception as exc:
            self._fail_closed("trusted clock failed", exc)
        tail = conn.execute(
            "SELECT occurred_at FROM notification_outbox_receipts "
            "ORDER BY global_sequence DESC LIMIT 1"
        ).fetchone()
        floor = -1.0 if not_before is None else float(not_before)
        if tail is not None:
            floor = max(floor, float(tail["occurred_at"]))
        if stamp < floor:
            self._fail_closed(
                "trusted clock regressed below transaction or anchored receipt time"
            )
        return stamp

    def _write_meta(
        self,
        conn: sqlite3.Connection,
        *,
        checkpoint: LedgerCheckpoint,
        sequence: int,
        event_count: int,
        receipt_count: int,
        global_head_seal: str,
    ) -> LedgerCheckpoint:
        material = {
            "contract_version": CONTRACT_VERSION,
            "ledger_id": checkpoint.ledger_id,
            "policy_id": self.policy.policy_id,
            "policy_version": self.policy.policy_version,
            "policy_digest": self._policy_digest,
            "sequence": sequence,
            "event_count": event_count,
            "receipt_count": receipt_count,
            "global_head_seal": global_head_seal,
        }
        meta_seal = self._seal(_META_DOMAIN, material)
        conn.execute(
            """
            UPDATE notification_outbox_meta
            SET sequence=?,event_count=?,receipt_count=?,global_head_seal=?,meta_seal=?
            WHERE singleton=1
            """,
            (sequence, event_count, receipt_count, global_head_seal, meta_seal),
        )
        return LedgerCheckpoint(
            ledger_id=checkpoint.ledger_id,
            contract_version=CONTRACT_VERSION,
            policy_id=self.policy.policy_id,
            policy_version=self.policy.policy_version,
            policy_digest=self._policy_digest,
            sequence=sequence,
            event_count=event_count,
            receipt_count=receipt_count,
            global_head_seal=global_head_seal,
            meta_seal=meta_seal,
        )

    def _append_receipt(
        self,
        conn: sqlite3.Connection,
        *,
        event: sqlite3.Row,
        kind: str,
        from_state: str | None,
        to_state: str,
        occurred_at: float,
        attempt_count: int,
        next_attempt_at: float,
        reason_code: str,
        lease_hmac: str | None = None,
        lease_expires_at: float | None = None,
        cost_units: int = 0,
        new_event: bool = False,
    ) -> sqlite3.Row:
        if kind not in _KINDS or to_state not in _STATE_SET:
            raise NotificationOutboxError("transition kind or state is invalid")
        reason = _reason(reason_code)
        current = self._get_checkpoint(conn)
        state_snapshot = conn.execute(
            "SELECT created_at,indeterminate_at,sent_at,acknowledged_at,"
            "failed_at,cancelled_at FROM notification_outbox_events "
            "WHERE event_id=?",
            (str(event["event_id"]),),
        ).fetchone()
        if state_snapshot is None:
            self._fail_closed("receipt event disappeared before transition sealing")
        event_sequence = int(event["event_receipt_count"]) + 1
        global_sequence = current.sequence + 1
        material = {
            "receipt_version": RECEIPT_VERSION,
            "global_sequence": global_sequence,
            "transition_id": "tr_"
            + self._domain_hmac(
                _TRANSITION_ID_DOMAIN,
                f"{self._ledger_id}\x00{global_sequence}\x00{secrets.token_hex(16)}",
            )[:32],
            "event_id": str(event["event_id"]),
            "event_sequence": event_sequence,
            "policy_id": self.policy.policy_id,
            "policy_version": self.policy.policy_version,
            "policy_digest": self._policy_digest,
            "kind": kind,
            "from_state": from_state,
            "to_state": to_state,
            "occurred_at": float(occurred_at),
            "created_at": float(state_snapshot["created_at"]),
            "attempt_count": int(attempt_count),
            "lease_hmac": lease_hmac,
            "lease_expires_at": lease_expires_at,
            "next_attempt_at": float(next_attempt_at),
            "indeterminate_at": (
                None
                if state_snapshot["indeterminate_at"] is None
                else float(state_snapshot["indeterminate_at"])
            ),
            "sent_at": (
                None
                if state_snapshot["sent_at"] is None
                else float(state_snapshot["sent_at"])
            ),
            "acknowledged_at": (
                None
                if state_snapshot["acknowledged_at"] is None
                else float(state_snapshot["acknowledged_at"])
            ),
            "failed_at": (
                None
                if state_snapshot["failed_at"] is None
                else float(state_snapshot["failed_at"])
            ),
            "cancelled_at": (
                None
                if state_snapshot["cancelled_at"] is None
                else float(state_snapshot["cancelled_at"])
            ),
            "cost_units": int(cost_units),
            "reason_code": reason,
            "transport_key_hmac": str(event["transport_key_hmac"]),
            "previous_event_seal": str(event["event_head_seal"]),
            "previous_global_seal": current.global_head_seal,
        }
        receipt_seal = self._seal(_RECEIPT_DOMAIN, material)
        cursor = conn.execute(
            """
            INSERT INTO notification_outbox_receipts
                (receipt_version,global_sequence,transition_id,event_id,event_sequence,
                 policy_id,policy_version,policy_digest,kind,from_state,to_state,
                 occurred_at,created_at,attempt_count,lease_hmac,lease_expires_at,
                 next_attempt_at,indeterminate_at,sent_at,acknowledged_at,failed_at,
                 cancelled_at,cost_units,reason_code,transport_key_hmac,
                 previous_event_seal,previous_global_seal,receipt_seal)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                RECEIPT_VERSION,
                global_sequence,
                material["transition_id"],
                material["event_id"],
                event_sequence,
                self.policy.policy_id,
                self.policy.policy_version,
                self._policy_digest,
                kind,
                from_state,
                to_state,
                occurred_at,
                material["created_at"],
                attempt_count,
                lease_hmac,
                lease_expires_at,
                next_attempt_at,
                material["indeterminate_at"],
                material["sent_at"],
                material["acknowledged_at"],
                material["failed_at"],
                material["cancelled_at"],
                cost_units,
                reason,
                material["transport_key_hmac"],
                material["previous_event_seal"],
                current.global_head_seal,
                receipt_seal,
            ),
        )
        conn.execute(
            "UPDATE notification_outbox_events "
            "SET event_receipt_count=?,event_head_seal=? WHERE event_id=?",
            (event_sequence, receipt_seal, str(event["event_id"])),
        )
        self._write_meta(
            conn,
            checkpoint=current,
            sequence=global_sequence,
            event_count=current.event_count + (1 if new_event else 0),
            receipt_count=current.receipt_count + 1,
            global_head_seal=receipt_seal,
        )
        row = conn.execute(
            "SELECT * FROM notification_outbox_receipts WHERE receipt_id=?",
            (int(cursor.lastrowid),),
        ).fetchone()
        assert row is not None
        self._verify_receipt(row)
        return row

    def _prepare_anchor(
        self,
        expected: LedgerCheckpoint,
        candidate: LedgerCheckpoint,
    ) -> None:
        try:
            self._anchor.prepare(expected, candidate)
        except Exception as exc:
            self._fail_closed("external anchor prepare failed", exc)

    def _abort_anchor(self, candidate: LedgerCheckpoint) -> None:
        try:
            self._anchor.abort(candidate)
        except Exception as exc:
            self._fail_closed("external anchor abort failed", exc)

    @staticmethod
    def _is_checkpoint_successor(
        candidate: LedgerCheckpoint,
        successor: LedgerCheckpoint | None,
    ) -> bool:
        if successor is None:
            return False
        immutable = (
            "ledger_id",
            "contract_version",
            "policy_id",
            "policy_version",
            "policy_digest",
        )
        return (
            all(
                getattr(successor, field_name) == getattr(candidate, field_name)
                for field_name in immutable
            )
            and successor.sequence == successor.receipt_count
            and successor.sequence > candidate.sequence
            and successor.receipt_count > candidate.receipt_count
            and successor.event_count >= candidate.event_count
        )

    def _confirm_committed_successor(self, candidate: LedgerCheckpoint) -> bool:
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            checkpoint = self._reconcile_anchor_locked(conn)
            self._verify_global_tail_locked(conn, checkpoint)
            accepted = self._is_checkpoint_successor(candidate, checkpoint)
            conn.rollback()
            return accepted

    def _finalize_anchor(
        self,
        candidate: LedgerCheckpoint,
        *,
        reason: str,
        allow_successor: bool = False,
    ) -> None:
        try:
            self._anchor.commit(candidate)
            return
        except Exception as exc:
            snapshot = self._anchor_snapshot()
            if snapshot.current == candidate and snapshot.pending is None:
                return
            successor_visible = self._is_checkpoint_successor(
                candidate, snapshot.current
            ) or self._is_checkpoint_successor(candidate, snapshot.pending)
            if allow_successor and successor_visible:
                try:
                    if self._confirm_committed_successor(candidate):
                        return
                except OutboxQuarantined:
                    raise
                except Exception as confirmation_exc:
                    self._fail_closed(reason, confirmation_exc)
            self._fail_closed(reason, exc)

    def _commit_locked(
        self,
        conn: sqlite3.Connection,
        before: LedgerCheckpoint,
        *,
        live_until: float | None = None,
    ) -> bool:
        after = self._get_checkpoint(conn)
        if after == before:
            conn.commit()
            return True
        self._prepare_anchor(before, after)
        if live_until is not None and self._sample_clock_locked(conn) >= live_until:
            self._abort_anchor(after)
            conn.rollback()
            return False
        try:
            conn.commit()
        except Exception:
            self._abort_anchor(after)
            raise
        self._finalize_anchor(
            after,
            reason="database committed but external anchor commit failed",
            allow_successor=True,
        )
        return True

    def _open_or_initialize(self) -> None:
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._verify_schema_locked(conn)
            row = conn.execute(
                "SELECT * FROM notification_outbox_meta WHERE singleton=1"
            ).fetchone()
            if row is None:
                event_count = int(
                    conn.execute(
                        "SELECT COUNT(*) AS count FROM notification_outbox_events"
                    ).fetchone()["count"]
                )
                receipt_count = int(
                    conn.execute(
                        "SELECT COUNT(*) AS count FROM notification_outbox_receipts"
                    ).fetchone()["count"]
                )
                snapshot = self._anchor_snapshot()
                if (
                    not event_count
                    and not receipt_count
                    and snapshot.current is None
                    and snapshot.pending is not None
                    and snapshot.pending.contract_version == CONTRACT_VERSION
                    and snapshot.pending.policy_id == self.policy.policy_id
                    and snapshot.pending.policy_version == self.policy.policy_version
                    and snapshot.pending.policy_digest == self._policy_digest
                    and snapshot.pending.sequence == 0
                    and snapshot.pending.event_count == 0
                    and snapshot.pending.receipt_count == 0
                ):
                    try:
                        self._anchor.abort(snapshot.pending)
                    except Exception as exc:
                        self._fail_closed(
                            "abandoned initial anchor checkpoint could not be aborted",
                            exc,
                        )
                    snapshot = self._anchor_snapshot()
                if event_count or receipt_count or snapshot.current or snapshot.pending:
                    self._fail_closed("database or anchor is not empty during initialization")
                material = {
                    "contract_version": CONTRACT_VERSION,
                    "ledger_id": "ledger_" + secrets.token_hex(16),
                    "policy_id": self.policy.policy_id,
                    "policy_version": self.policy.policy_version,
                    "policy_digest": self._policy_digest,
                    "sequence": 0,
                    "event_count": 0,
                    "receipt_count": 0,
                    "global_head_seal": "",
                }
                meta_seal = self._seal(_META_DOMAIN, material)
                conn.execute(
                    """
                    INSERT INTO notification_outbox_meta
                        (singleton,contract_version,ledger_id,policy_id,policy_version,
                         policy_digest,sequence,event_count,receipt_count,
                         global_head_seal,meta_seal)
                    VALUES(1,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        CONTRACT_VERSION,
                        material["ledger_id"],
                        self.policy.policy_id,
                        self.policy.policy_version,
                        self._policy_digest,
                        0,
                        0,
                        0,
                        "",
                        meta_seal,
                    ),
                )
                checkpoint = self._get_checkpoint(conn)
                self._ledger_id = checkpoint.ledger_id
                prepared = False
                database_committed = False
                try:
                    self._anchor.prepare(None, checkpoint)
                    prepared = True
                    conn.commit()
                    database_committed = True
                    self._finalize_anchor(
                        checkpoint,
                        reason="initial external anchor commit failed",
                        allow_successor=True,
                    )
                except OutboxQuarantined:
                    raise
                except Exception as exc:
                    conn.rollback()
                    if prepared and not database_committed:
                        try:
                            self._anchor.abort(checkpoint)
                        except Exception as abort_exc:
                            self._fail_closed(
                                "initial database commit and anchor abort failed",
                                abort_exc,
                            )
                    self._fail_closed("initial external anchor commit failed", exc)
                return
            checkpoint = self._preflight_locked(conn)
            self._ledger_id = checkpoint.ledger_id
            self._full_audit_locked(conn)
            conn.commit()

    def _verify_event_seal(self, row: sqlite3.Row) -> None:
        try:
            material = self._event_material(row)
            expected = self._seal(_EVENT_DOMAIN, material)
        except Exception as exc:
            self._fail_closed("event evidence is malformed", exc)
        if (
            material["contract_version"] != CONTRACT_VERSION
            or _EVENT_ID_RE.fullmatch(str(material["event_id"])) is None
            or material["policy_id"] != self.policy.policy_id
            or material["policy_version"] != self.policy.policy_version
            or material["policy_digest"] != self._policy_digest
            or not _is_sha256(material["idempotency_hmac"])
            or not _is_sha256(material["transport_key_hmac"])
            or int(material["max_attempts"]) <= 0
            or int(material["cost_units"]) < 0
            or not _is_sha256(row["event_seal"])
            or not hmac.compare_digest(expected, str(row["event_seal"]))
        ):
            self._fail_closed("event seal or policy evidence is invalid")
        try:
            self.policy.require_category(material["category"])
            self.policy.require_adapter(material["adapter_name"])
            self._validate_payload_ref(OpaquePayloadRef(str(material["payload_ref"])))
            _timestamp(material["created_at"], name="stored created_at")
        except NotificationOutboxError as exc:
            self._fail_closed("event registry or payload evidence is invalid", exc)

    def _verify_receipt(self, row: sqlite3.Row) -> None:
        try:
            material = self._receipt_material(row)
            expected = self._seal(_RECEIPT_DOMAIN, material)
        except Exception as exc:
            self._fail_closed("transition receipt is malformed", exc)
        if (
            material["receipt_version"] != RECEIPT_VERSION
            or int(material["global_sequence"]) <= 0
            or int(material["event_sequence"]) <= 0
            or _TRANSITION_ID_RE.fullmatch(str(material["transition_id"])) is None
            or _EVENT_ID_RE.fullmatch(str(material["event_id"])) is None
            or material["policy_id"] != self.policy.policy_id
            or material["policy_version"] != self.policy.policy_version
            or material["policy_digest"] != self._policy_digest
            or material["kind"] not in _KINDS
            or material["to_state"] not in _STATE_SET
            or (
                material["from_state"] is not None
                and material["from_state"] not in _STATE_SET
            )
            or int(material["attempt_count"]) < 0
            or int(material["cost_units"]) < 0
            or not _is_sha256(material["transport_key_hmac"])
            or (
                material["lease_hmac"] is not None
                and not _is_sha256(material["lease_hmac"], allow_empty=False)
            )
            or not _is_sha256(material["previous_event_seal"], allow_empty=True)
            or not _is_sha256(material["previous_global_seal"], allow_empty=True)
            or not _is_sha256(row["receipt_seal"])
        ):
            self._fail_closed("transition receipt fields are invalid")
        try:
            _timestamp(material["occurred_at"], name="receipt occurred_at")
            _timestamp(material["created_at"], name="receipt created_at")
            _timestamp(material["next_attempt_at"], name="receipt next_attempt_at")
            if material["lease_expires_at"] is not None:
                _timestamp(material["lease_expires_at"], name="receipt lease_expires_at")
            for field_name in (
                "indeterminate_at",
                "sent_at",
                "acknowledged_at",
                "failed_at",
                "cancelled_at",
            ):
                if material[field_name] is not None:
                    _timestamp(
                        material[field_name],
                        name=f"receipt {field_name}",
                    )
            _reason(material["reason_code"])
        except NotificationOutboxError as exc:
            self._fail_closed("transition receipt values are invalid", exc)
        if not hmac.compare_digest(expected, str(row["receipt_seal"])):
            self._fail_closed("transition receipt seal is invalid")

    @staticmethod
    def _same_optional_float(left: object, right: float | None) -> bool:
        if right is None:
            return left is None
        return left is not None and float(left) == right

    def _load_event_tail_locked(
        self, conn: sqlite3.Connection, event_id: str
    ) -> tuple[sqlite3.Row, sqlite3.Row]:
        row = conn.execute(
            "SELECT * FROM notification_outbox_events WHERE event_id=?", (event_id,)
        ).fetchone()
        if row is None:
            raise OutboxNotFound(f"notification event {event_id!r} was not found")
        self._verify_event_seal(row)
        tail = conn.execute(
            "SELECT * FROM notification_outbox_receipts WHERE event_id=? "
            "ORDER BY event_sequence DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        if (
            tail is None
            or int(tail["event_sequence"]) != int(row["event_receipt_count"])
            or str(tail["receipt_seal"]) != str(row["event_head_seal"])
        ):
            self._fail_closed("event receipt tail was truncated or replaced")
        self._verify_receipt(tail)
        final_lease_hmac = tail["lease_hmac"] if str(tail["to_state"]) == LEASED else None
        final_lease_expiry = (
            float(tail["lease_expires_at"])
            if str(tail["to_state"]) == LEASED
            else None
        )
        if (
            str(row["state"]) != str(tail["to_state"])
            or float(row["created_at"]) != float(tail["created_at"])
            or float(row["updated_at"]) != float(tail["occurred_at"])
            or float(row["next_attempt_at"]) != float(tail["next_attempt_at"])
            or int(row["attempt_count"]) != int(tail["attempt_count"])
            or row["lease_hmac"] != final_lease_hmac
            or not self._same_optional_float(row["lease_expires_at"], final_lease_expiry)
            or not self._same_optional_float(
                row["indeterminate_at"],
                None
                if tail["indeterminate_at"] is None
                else float(tail["indeterminate_at"]),
            )
            or not self._same_optional_float(
                row["sent_at"],
                None if tail["sent_at"] is None else float(tail["sent_at"]),
            )
            or not self._same_optional_float(
                row["acknowledged_at"],
                None
                if tail["acknowledged_at"] is None
                else float(tail["acknowledged_at"]),
            )
            or not self._same_optional_float(
                row["failed_at"],
                None if tail["failed_at"] is None else float(tail["failed_at"]),
            )
            or not self._same_optional_float(
                row["cancelled_at"],
                None
                if tail["cancelled_at"] is None
                else float(tail["cancelled_at"]),
            )
        ):
            self._fail_closed(
                "event state or lifecycle timestamps do not match its sealed tail"
            )
        return row, tail

    def _status(
        self,
        conn: sqlite3.Connection,
        row: Mapping[str, object],
    ) -> dict[str, object]:
        row, _tail = self._load_event_tail_locked(conn, str(row["event_id"]))
        return {
            "event_id": str(row["event_id"]),
            "category": str(row["category"]),
            "adapter_name": str(row["adapter_name"]),
            "state": str(row["state"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "next_attempt_at": float(row["next_attempt_at"]),
            "attempt_count": int(row["attempt_count"]),
            "max_attempts": int(row["max_attempts"]),
            "indeterminate_at": (
                None
                if row["indeterminate_at"] is None
                else float(row["indeterminate_at"])
            ),
            "sent_at": None if row["sent_at"] is None else float(row["sent_at"]),
            "acknowledged_at": (
                None
                if row["acknowledged_at"] is None
                else float(row["acknowledged_at"])
            ),
            "failed_at": (
                None if row["failed_at"] is None else float(row["failed_at"])
            ),
            "cancelled_at": (
                None if row["cancelled_at"] is None else float(row["cancelled_at"])
            ),
        }

    @staticmethod
    def _public_receipt(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "receipt_id": int(row["receipt_id"]),
            "receipt_version": int(row["receipt_version"]),
            "global_sequence": int(row["global_sequence"]),
            "transition_id": str(row["transition_id"]),
            "event_id": str(row["event_id"]),
            "event_sequence": int(row["event_sequence"]),
            "kind": str(row["kind"]),
            "from_state": None if row["from_state"] is None else str(row["from_state"]),
            "to_state": str(row["to_state"]),
            "occurred_at": float(row["occurred_at"]),
            "attempt_count": int(row["attempt_count"]),
            "next_attempt_at": float(row["next_attempt_at"]),
            "cost_units": int(row["cost_units"]),
            "reason_code": str(row["reason_code"]),
            "verified": True,
        }

    def _full_audit_locked(self, conn: sqlite3.Connection) -> dict[str, int]:
        checkpoint = self._reconcile_anchor_locked(conn)
        orphan = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM notification_outbox_receipts r
            LEFT JOIN notification_outbox_events e ON e.event_id=r.event_id
            WHERE e.event_id IS NULL
            """
        ).fetchone()
        if orphan is not None and int(orphan["count"]) != 0:
            self._fail_closed("orphan transition receipts exist")

        events = conn.execute(
            "SELECT * FROM notification_outbox_events ORDER BY id"
        ).fetchall()
        receipts = conn.execute(
            "SELECT * FROM notification_outbox_receipts ORDER BY global_sequence"
        ).fetchall()
        if len(events) != checkpoint.event_count:
            self._fail_closed("global event count does not match anchored metadata")
        if len(receipts) != checkpoint.receipt_count:
            self._fail_closed("global receipt count does not match anchored metadata")

        event_map = {str(row["event_id"]): row for row in events}
        by_event: dict[str, list[sqlite3.Row]] = {event_id: [] for event_id in event_map}
        previous_global = ""
        previous_global_time = -1.0
        for expected_sequence, receipt in enumerate(receipts, start=1):
            self._verify_receipt(receipt)
            event_id = str(receipt["event_id"])
            if event_id not in event_map:
                self._fail_closed("orphan transition receipt was found")
            if (
                int(receipt["global_sequence"]) != expected_sequence
                or str(receipt["previous_global_seal"]) != previous_global
                or float(receipt["occurred_at"]) < previous_global_time
            ):
                self._fail_closed("global receipt chain is truncated or discontinuous")
            by_event[event_id].append(receipt)
            previous_global = str(receipt["receipt_seal"])
            previous_global_time = float(receipt["occurred_at"])
        if previous_global != checkpoint.global_head_seal:
            self._fail_closed("global receipt head does not match anchored metadata")

        for event_id, event in event_map.items():
            self._verify_event_seal(event)
            chain = by_event[event_id]
            if not chain:
                self._fail_closed("event has no transition receipts")
            self._audit_event_chain(event, chain)
        return {"events": len(events), "receipts": len(receipts)}

    def _audit_event_chain(
        self, event: sqlite3.Row, receipts: list[sqlite3.Row]
    ) -> None:
        state: str | None = None
        attempt = 0
        previous_event = ""
        previous_time = -1.0
        expected_lease_hmac: str | None = None
        expected_lease_expiry: float | None = None
        indeterminate_at: float | None = None
        sent_at: float | None = None
        acknowledged_at: float | None = None
        failed_at: float | None = None
        cancelled_at: float | None = None

        for expected_sequence, receipt in enumerate(receipts, start=1):
            material = self._receipt_material(receipt)
            kind = str(material["kind"])
            from_state = material["from_state"]
            to_state = str(material["to_state"])
            occurred = float(material["occurred_at"])
            receipt_attempt = int(material["attempt_count"])
            lease_hmac = material["lease_hmac"]
            lease_expiry = material["lease_expires_at"]
            cost = int(material["cost_units"])
            if (
                int(material["event_sequence"]) != expected_sequence
                or str(material["previous_event_seal"]) != previous_event
                or from_state != state
                or occurred < previous_time
                or str(material["transport_key_hmac"])
                != str(event["transport_key_hmac"])
            ):
                self._fail_closed("event receipt chain is discontinuous")

            valid = True
            if kind == _ENQUEUED:
                valid = (
                    expected_sequence == 1
                    and state is None
                    and to_state == QUEUED
                    and receipt_attempt == 0
                    and lease_hmac is None
                    and lease_expiry is None
                    and cost == 0
                    and occurred == float(event["created_at"])
                )
            elif kind == _CLAIMED:
                valid = (
                    state == QUEUED
                    and to_state == LEASED
                    and receipt_attempt == attempt + 1
                    and lease_hmac is not None
                    and lease_expiry is not None
                    and occurred < float(lease_expiry)
                    and cost == int(event["cost_units"])
                )
            else:
                valid = receipt_attempt == attempt and cost == 0
                if kind in {_QUIET_DEFERRED, _POLICY_DEFERRED}:
                    valid = valid and state == QUEUED and to_state == QUEUED and lease_hmac is None
                elif kind == _POLICY_FAILED:
                    valid = valid and state == QUEUED and to_state == FAILED and lease_hmac is None
                elif kind == _CLAIM_ABANDONED:
                    valid = (
                        valid
                        and state == LEASED
                        and to_state in {QUEUED, FAILED}
                        and lease_hmac is not None
                        and lease_expiry is not None
                        and occurred >= float(lease_expiry)
                    )
                elif kind == _RETRY_SCHEDULED:
                    valid = valid and state == LEASED and to_state == QUEUED and lease_hmac is not None
                elif kind == _DELIVERY_FAILED:
                    valid = valid and state == LEASED and to_state == FAILED and lease_hmac is not None
                elif kind == _DELIVERY_INDETERMINATE:
                    valid = valid and state == LEASED and to_state == INDETERMINATE and lease_hmac is not None
                elif kind == _LEASE_EXPIRED:
                    valid = (
                        valid
                        and state == LEASED
                        and to_state == INDETERMINATE
                        and lease_hmac is not None
                        and lease_expiry is not None
                        and occurred >= float(lease_expiry)
                    )
                elif kind == _SENT:
                    valid = (
                        valid
                        and state == LEASED
                        and to_state == SENT
                        and lease_hmac is not None
                        and lease_expiry is not None
                        and occurred < float(lease_expiry)
                    )
                elif kind == _RECONCILED_SENT:
                    valid = valid and state == INDETERMINATE and to_state == SENT and lease_hmac is None
                elif kind in {_RECONCILED_RETRY, _IDEMPOTENT_RETRY}:
                    valid = valid and state == INDETERMINATE and to_state == QUEUED and lease_hmac is None
                elif kind == _RECONCILED_FAILED:
                    valid = valid and state == INDETERMINATE and to_state == FAILED and lease_hmac is None
                elif kind == _ACKNOWLEDGED:
                    valid = valid and state == SENT and to_state == ACKNOWLEDGED and lease_hmac is None
                elif kind == _CANCELLED:
                    valid = valid and state in {QUEUED, INDETERMINATE} and to_state == CANCELLED and lease_hmac is None
                else:
                    valid = False
            if not valid:
                self._fail_closed("event transition receipt shape is invalid")

            if kind == _CLAIMED:
                attempt = receipt_attempt
                expected_lease_hmac = str(lease_hmac)
                expected_lease_expiry = float(lease_expiry)
            elif to_state != LEASED:
                expected_lease_hmac = None
                expected_lease_expiry = None
            if to_state == INDETERMINATE:
                indeterminate_at = occurred
            if to_state == SENT:
                sent_at = occurred
            if to_state == ACKNOWLEDGED:
                acknowledged_at = occurred
            if to_state == FAILED:
                failed_at = occurred
            if to_state == CANCELLED:
                cancelled_at = occurred
            if (
                float(material["created_at"]) != float(event["created_at"])
                or not self._same_optional_float(
                    material["indeterminate_at"], indeterminate_at
                )
                or not self._same_optional_float(material["sent_at"], sent_at)
                or not self._same_optional_float(
                    material["acknowledged_at"], acknowledged_at
                )
                or not self._same_optional_float(material["failed_at"], failed_at)
                or not self._same_optional_float(
                    material["cancelled_at"], cancelled_at
                )
            ):
                self._fail_closed(
                    "receipt lifecycle snapshot does not match its transition chain"
                )
            state = to_state
            previous_event = str(receipt["receipt_seal"])
            previous_time = occurred

        tail = receipts[-1]
        if (
            int(event["event_receipt_count"]) != len(receipts)
            or str(event["event_head_seal"]) != previous_event
            or str(event["state"]) != state
            or int(event["attempt_count"]) != attempt
            or float(event["updated_at"]) != float(tail["occurred_at"])
            or float(event["next_attempt_at"]) != float(tail["next_attempt_at"])
            or event["lease_hmac"] != expected_lease_hmac
            or not self._same_optional_float(event["lease_expires_at"], expected_lease_expiry)
            or not self._same_optional_float(event["indeterminate_at"], indeterminate_at)
            or not self._same_optional_float(event["sent_at"], sent_at)
            or not self._same_optional_float(event["acknowledged_at"], acknowledged_at)
            or not self._same_optional_float(event["failed_at"], failed_at)
            or not self._same_optional_float(event["cancelled_at"], cancelled_at)
        ):
            self._fail_closed("event mutable state does not match its full receipt chain")

    def audit(self) -> dict[str, object]:
        """Run the explicit linear whole-ledger audit and quarantine on any gap."""
        self._require_available()
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._reconcile_anchor_locked(conn)
            counts = self._full_audit_locked(conn)
            conn.commit()
        return {
            "verified": True,
            "events": counts["events"],
            "receipts": counts["receipts"],
        }

    def enqueue(
        self,
        *,
        idempotency_key: str,
        category: str,
        adapter_name: str,
        payload_ref: OpaquePayloadRef,
    ) -> dict[str, object]:
        """Create one event from closed registry keys and a server-minted ref."""
        clean_key = _idempotency_key(idempotency_key)
        clean_category = self.policy.require_category(category)
        clean_adapter = self.policy.require_adapter(adapter_name)
        clean_ref = self._validate_payload_ref(payload_ref)
        key_hmac = self._idempotency_hmac(clean_key)

        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self._preflight_locked(conn)
            existing = conn.execute(
                "SELECT * FROM notification_outbox_events WHERE idempotency_hmac=?",
                (key_hmac,),
            ).fetchone()
            if existing is not None:
                event, _tail = self._load_event_tail_locked(
                    conn, str(existing["event_id"])
                )
                if (
                    str(event["category"]) != clean_category
                    or str(event["adapter_name"]) != clean_adapter
                    or str(event["payload_ref"]) != clean_ref
                ):
                    raise OutboxConflict(
                        "idempotency key was replayed with different sealed facts"
                    )
                status = self._status(conn, event)
                conn.commit()
                return status

            now = self._sample_clock_locked(conn)
            event_id = ""
            for _attempt in range(8):
                candidate_id = "out_" + secrets.token_hex(16)
                if conn.execute(
                    "SELECT 1 FROM notification_outbox_events WHERE event_id=?",
                    (candidate_id,),
                ).fetchone() is None:
                    event_id = candidate_id
                    break
            if not event_id:
                raise NotificationOutboxError(
                    "could not allocate a unique notification event identifier"
                )
            transport_key = self._transport_idempotency_key(event_id)
            transport_hmac = self._transport_key_hmac(transport_key)
            material = {
                "contract_version": CONTRACT_VERSION,
                "event_id": event_id,
                "idempotency_hmac": key_hmac,
                "policy_id": self.policy.policy_id,
                "policy_version": self.policy.policy_version,
                "policy_digest": self._policy_digest,
                "category": clean_category,
                "adapter_name": clean_adapter,
                "payload_ref": clean_ref,
                "transport_key_hmac": transport_hmac,
                "created_at": now,
                "max_attempts": self.policy.max_attempts,
                "cost_units": self.policy.cost_for(clean_adapter),
            }
            event_seal = self._seal(_EVENT_DOMAIN, material)
            conn.execute(
                """
                INSERT INTO notification_outbox_events
                    (contract_version,event_id,idempotency_hmac,policy_id,
                     policy_version,policy_digest,category,adapter_name,payload_ref,
                     transport_key_hmac,state,created_at,updated_at,next_attempt_at,
                     attempt_count,max_attempts,cost_units,lease_hmac,
                     lease_expires_at,indeterminate_at,sent_at,acknowledged_at,
                     failed_at,cancelled_at,event_receipt_count,event_head_seal,event_seal)
                VALUES(?,?,?,?,?,?,?,?,?,?,'queued',?,?,?,0,?,?,NULL,NULL,NULL,NULL,
                       NULL,NULL,NULL,0,'',?)
                """,
                (
                    CONTRACT_VERSION,
                    event_id,
                    key_hmac,
                    self.policy.policy_id,
                    self.policy.policy_version,
                    self._policy_digest,
                    clean_category,
                    clean_adapter,
                    clean_ref,
                    transport_hmac,
                    now,
                    now,
                    now,
                    self.policy.max_attempts,
                    self.policy.cost_for(clean_adapter),
                    event_seal,
                ),
            )
            event = conn.execute(
                "SELECT * FROM notification_outbox_events WHERE event_id=?", (event_id,)
            ).fetchone()
            assert event is not None
            self._append_receipt(
                conn,
                event=event,
                kind=_ENQUEUED,
                from_state=None,
                to_state=QUEUED,
                occurred_at=now,
                attempt_count=0,
                next_attempt_at=now,
                reason_code="queued",
                new_event=True,
            )
            status = self._status(
                conn,
                conn.execute(
                    "SELECT * FROM notification_outbox_events WHERE event_id=?",
                    (event_id,),
                ).fetchone()
            )
            self._commit_locked(conn, before)
            return status

    def _quota_retry_at_locked(
        self,
        conn: sqlite3.Connection,
        *,
        since: float,
        limit: int,
        category: str | None = None,
        adapter_name: str | None = None,
    ) -> float | None:
        clauses = ["r.kind='claimed'", "r.occurred_at>?"]
        values: list[object] = [since]
        if category is not None:
            clauses.append("e.category=?")
            values.append(category)
        if adapter_name is not None:
            clauses.append("e.adapter_name=?")
            values.append(adapter_name)
        source = (
            "FROM notification_outbox_receipts r "
            "JOIN notification_outbox_events e ON e.event_id=r.event_id WHERE "
            + " AND ".join(clauses)
        )
        stats = conn.execute(
            "SELECT COUNT(*) AS count,MIN(r.occurred_at) AS oldest " + source,
            tuple(values),
        ).fetchone()
        count = int(stats["count"])
        if count < limit:
            return None
        if count > limit:
            self._fail_closed("quota history exceeds its frozen policy limit")
        oldest = stats["oldest"]
        if oldest is None:
            self._fail_closed("quota count has no matching receipt boundary")
        return float(oldest) + self.policy.quota_window_seconds

    def _policy_block_locked(
        self, conn: sqlite3.Connection, event: sqlite3.Row, now: float
    ) -> tuple[str, float] | None:
        since = now - self.policy.quota_window_seconds
        blocks: list[tuple[str, float]] = []

        def check(
            reason: str,
            limit: int | None,
            *,
            category: str | None = None,
            adapter_name: str | None = None,
        ) -> None:
            if limit is None:
                return
            retry_at = self._quota_retry_at_locked(
                conn,
                since=since,
                limit=limit,
                category=category,
                adapter_name=adapter_name,
            )
            if retry_at is not None:
                blocks.append((reason, retry_at))

        category = str(event["category"])
        adapter = str(event["adapter_name"])
        check("global_quota", self.policy.global_quota)
        check(
            "category_quota",
            self.policy.category_quotas[category],
            category=category,
        )
        check(
            "channel_quota",
            self.policy.channel_quotas[adapter],
            adapter_name=adapter,
        )
        if self.policy.daily_cost_cap is not None:
            start, end = self.policy.day_bounds(now)
            spent = int(
                conn.execute(
                    "SELECT COALESCE(SUM(cost_units),0) AS spent "
                    "FROM notification_outbox_receipts "
                    "WHERE kind='claimed' AND occurred_at>=? AND occurred_at<?",
                    (start, end),
                ).fetchone()["spent"]
            )
            cost = int(event["cost_units"])
            if cost > self.policy.daily_cost_cap:
                return "cost_exceeds_daily_cap", -1.0
            if spent + cost > self.policy.daily_cost_cap:
                blocks.append(("daily_cost_cap", end))
        if not blocks:
            return None
        retry_at = max(value for _reason_code, value in blocks)
        reasons = {reason_code for reason_code, _value in blocks}
        return (blocks[0][0] if len(reasons) == 1 else "policy_limits", retry_at)

    def _transition_event_locked(
        self,
        conn: sqlite3.Connection,
        event: sqlite3.Row,
        *,
        state: str,
        now: float,
        next_attempt_at: float,
        lease_hmac: str | None = None,
        lease_expires_at: float | None = None,
        indeterminate_at: float | None | object = ...,
        sent_at: float | None | object = ...,
        acknowledged_at: float | None | object = ...,
        failed_at: float | None | object = ...,
        cancelled_at: float | None | object = ...,
        attempt_count: int | None = None,
    ) -> sqlite3.Row:
        if now < float(event["updated_at"]):
            raise OutboxStateError("trusted clock moved backwards for this event")
        assignments = [
            "state=?",
            "updated_at=?",
            "next_attempt_at=?",
            "lease_hmac=?",
            "lease_expires_at=?",
        ]
        values: list[object] = [
            state,
            now,
            next_attempt_at,
            lease_hmac,
            lease_expires_at,
        ]
        optional = (
            ("indeterminate_at", indeterminate_at),
            ("sent_at", sent_at),
            ("acknowledged_at", acknowledged_at),
            ("failed_at", failed_at),
            ("cancelled_at", cancelled_at),
        )
        for column, value in optional:
            if value is not ...:
                assignments.append(f"{column}=?")
                values.append(value)
        if attempt_count is not None:
            assignments.append("attempt_count=?")
            values.append(attempt_count)
        values.append(str(event["event_id"]))
        conn.execute(
            "UPDATE notification_outbox_events SET "
            + ",".join(assignments)
            + " WHERE event_id=?",
            tuple(values),
        )
        row = conn.execute(
            "SELECT * FROM notification_outbox_events WHERE event_id=?",
            (str(event["event_id"]),),
        ).fetchone()
        assert row is not None
        return row

    def _recover_expired_locked(self, conn: sqlite3.Connection, now: float) -> int:
        rows = conn.execute(
            "SELECT event_id FROM notification_outbox_events "
            "WHERE state='leased' AND lease_expires_at<=? "
            "ORDER BY lease_expires_at,id LIMIT ?",
            (now, _EXPIRED_RECOVERY_BATCH_SIZE),
        ).fetchall()
        recovered = 0
        for item in rows:
            event, _tail = self._load_event_tail_locked(conn, str(item["event_id"]))
            old_lease_hmac = str(event["lease_hmac"])
            old_expiry = float(event["lease_expires_at"])
            updated = self._transition_event_locked(
                conn,
                event,
                state=INDETERMINATE,
                now=now,
                next_attempt_at=now,
                indeterminate_at=now,
            )
            self._append_receipt(
                conn,
                event=event,
                kind=_LEASE_EXPIRED,
                from_state=LEASED,
                to_state=INDETERMINATE,
                occurred_at=now,
                attempt_count=int(event["attempt_count"]),
                lease_hmac=old_lease_hmac,
                lease_expires_at=old_expiry,
                next_attempt_at=now,
                reason_code="lease_expired",
            )
            recovered += 1
            event = updated
        return recovered

    def recover_expired(self) -> int:
        """Move one fixed batch of expired claims to indeterminate."""
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self._preflight_locked(conn)
            now = self._sample_clock_locked(conn)
            count = self._recover_expired_locked(conn, now)
            self._commit_locked(conn, before)
            return count

    def claim_next(self, *, adapter_name: str) -> DeliveryClaim | None:
        """Atomically claim one due event and return a live private claim object."""
        clean_adapter = self.policy.require_adapter(adapter_name)
        for _liveness_retry in range(8):
            with connect(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                before = self._preflight_locked(conn)
                now = self._sample_clock_locked(conn)
                clock_floor = now
                self._recover_expired_locked(conn, now)
                candidates = conn.execute(
                    """
                    SELECT event_id FROM notification_outbox_events
                    WHERE adapter_name=? AND state='queued' AND next_attempt_at<=?
                    ORDER BY next_attempt_at,created_at,id LIMIT ?
                    """,
                    (clean_adapter, now, _MAX_CANDIDATES_PER_CLAIM),
                ).fetchall()
                claim: DeliveryClaim | None = None
                live_until: float | None = None
                for candidate in candidates:
                    event, _tail = self._load_event_tail_locked(
                        conn, str(candidate["event_id"])
                    )
                    decision_time = self._sample_clock_locked(
                        conn,
                        not_before=clock_floor,
                    )
                    clock_floor = decision_time
                    if int(event["attempt_count"]) >= int(event["max_attempts"]):
                        self._transition_event_locked(
                            conn,
                            event,
                            state=FAILED,
                            now=decision_time,
                            next_attempt_at=decision_time,
                            failed_at=decision_time,
                        )
                        self._append_receipt(
                            conn,
                            event=event,
                            kind=_POLICY_FAILED,
                            from_state=QUEUED,
                            to_state=FAILED,
                            occurred_at=decision_time,
                            attempt_count=int(event["attempt_count"]),
                            next_attempt_at=decision_time,
                            reason_code="attempts_exhausted",
                        )
                        continue
                    quiet_until = (
                        None
                        if self.policy.quiet_hours is None
                        else self.policy.quiet_hours.defer_until(decision_time)
                    )
                    if quiet_until is not None:
                        self._transition_event_locked(
                            conn,
                            event,
                            state=QUEUED,
                            now=decision_time,
                            next_attempt_at=quiet_until,
                        )
                        self._append_receipt(
                            conn,
                            event=event,
                            kind=_QUIET_DEFERRED,
                            from_state=QUEUED,
                            to_state=QUEUED,
                            occurred_at=decision_time,
                            attempt_count=int(event["attempt_count"]),
                            next_attempt_at=quiet_until,
                            reason_code="quiet_hours",
                        )
                        continue
                    blocked = self._policy_block_locked(conn, event, decision_time)
                    if blocked is not None:
                        reason_code, retry_at = blocked
                        if retry_at < 0:
                            self._transition_event_locked(
                                conn,
                                event,
                                state=FAILED,
                                now=decision_time,
                                next_attempt_at=decision_time,
                                failed_at=decision_time,
                            )
                            self._append_receipt(
                                conn,
                                event=event,
                                kind=_POLICY_FAILED,
                                from_state=QUEUED,
                                to_state=FAILED,
                                occurred_at=decision_time,
                                attempt_count=int(event["attempt_count"]),
                                next_attempt_at=decision_time,
                                reason_code=reason_code,
                            )
                        else:
                            self._transition_event_locked(
                                conn,
                                event,
                                state=QUEUED,
                                now=decision_time,
                                next_attempt_at=retry_at,
                            )
                            self._append_receipt(
                                conn,
                                event=event,
                                kind=_POLICY_DEFERRED,
                                from_state=QUEUED,
                                to_state=QUEUED,
                                occurred_at=decision_time,
                                attempt_count=int(event["attempt_count"]),
                                next_attempt_at=retry_at,
                                reason_code=reason_code,
                            )
                        continue

                    claim_time = decision_time
                    attempt_count = int(event["attempt_count"]) + 1
                    lease_nonce = secrets.token_hex(32)
                    handle = "lease_" + self._domain_hmac(
                        _LEASE_DOMAIN,
                        f"{self._ledger_id}\x00{event['event_id']}\x00"
                        f"{attempt_count}\x00{lease_nonce}",
                    )
                    lease_hmac = self._lease_hmac(handle)
                    lease_expires_at = claim_time + self.policy.lease_seconds
                    self._transition_event_locked(
                        conn,
                        event,
                        state=LEASED,
                        now=claim_time,
                        next_attempt_at=lease_expires_at,
                        lease_hmac=lease_hmac,
                        lease_expires_at=lease_expires_at,
                        attempt_count=attempt_count,
                    )
                    self._append_receipt(
                        conn,
                        event=event,
                        kind=_CLAIMED,
                        from_state=QUEUED,
                        to_state=LEASED,
                        occurred_at=claim_time,
                        attempt_count=attempt_count,
                        lease_hmac=lease_hmac,
                        lease_expires_at=lease_expires_at,
                        next_attempt_at=lease_expires_at,
                        cost_units=int(event["cost_units"]),
                        reason_code="claimed",
                    )
                    transport_key = self._transport_idempotency_key(str(event["event_id"]))
                    claim = DeliveryClaim(
                        event_id=str(event["event_id"]),
                        category=str(event["category"]),
                        adapter_name=str(event["adapter_name"]),
                        payload_ref=OpaquePayloadRef(str(event["payload_ref"])),
                        transport_idempotency_key=transport_key,
                        claim_handle=handle,
                        lease_expires_at=lease_expires_at,
                        attempt_count=attempt_count,
                    )
                    live_until = lease_expires_at
                    break
                if self._commit_locked(conn, before, live_until=live_until):
                    if claim is None or self._claim_is_live_for_return(claim):
                        return claim
        raise OutboxLeaseLost("could not return a live lease before its expiry boundary")

    def _claim_is_live_for_return(self, claim: DeliveryClaim) -> bool:
        """Recheck after external anchor commit, still under a fresh write lock."""
        expected_lease_hmac = self._lease_hmac(claim.claim_handle)
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self._preflight_locked(conn)
            event, tail = self._load_event_tail_locked(conn, claim.event_id)
            now = self._sample_clock_locked(conn)
            state = str(event["state"])
            if (
                state == LEASED
                and event["lease_hmac"] is not None
                and hmac.compare_digest(
                    str(event["lease_hmac"]), expected_lease_hmac
                )
                and now < float(event["lease_expires_at"])
            ):
                conn.rollback()
                return True

            # The claim was never returned to an adapter, so provider
            # acceptance is impossible. Convert it to a definitive internal
            # abandonment instead of leaving a false indeterminate result.
            if state == LEASED and event["lease_hmac"] is not None and hmac.compare_digest(
                str(event["lease_hmac"]), expected_lease_hmac
            ):
                old_expiry = float(event["lease_expires_at"])
                if now < old_expiry:  # pragma: no cover - handled above
                    conn.rollback()
                    return True
                terminal = int(event["attempt_count"]) >= int(event["max_attempts"])
                next_state = FAILED if terminal else QUEUED
                self._transition_event_locked(
                    conn,
                    event,
                    state=next_state,
                    now=now,
                    next_attempt_at=now,
                    failed_at=now if terminal else None,
                )
                self._append_receipt(
                    conn,
                    event=event,
                    kind=_CLAIM_ABANDONED,
                    from_state=LEASED,
                    to_state=next_state,
                    occurred_at=now,
                    attempt_count=int(event["attempt_count"]),
                    lease_hmac=expected_lease_hmac,
                    lease_expires_at=old_expiry,
                    next_attempt_at=now,
                    reason_code="expired_before_return",
                )
                self._commit_locked(conn, before)
                return False

            if (
                state == INDETERMINATE
                and str(tail["kind"]) == _LEASE_EXPIRED
                and tail["lease_hmac"] is not None
                and hmac.compare_digest(
                    str(tail["lease_hmac"]), expected_lease_hmac
                )
            ):
                terminal = int(event["attempt_count"]) >= int(event["max_attempts"])
                next_state = FAILED if terminal else QUEUED
                kind = _RECONCILED_FAILED if terminal else _RECONCILED_RETRY
                self._transition_event_locked(
                    conn,
                    event,
                    state=next_state,
                    now=now,
                    next_attempt_at=now,
                    failed_at=now if terminal else None,
                )
                self._append_receipt(
                    conn,
                    event=event,
                    kind=kind,
                    from_state=INDETERMINATE,
                    to_state=next_state,
                    occurred_at=now,
                    attempt_count=int(event["attempt_count"]),
                    next_attempt_at=now,
                    reason_code="not_dispatched_before_return",
                )
                self._commit_locked(conn, before)
                return False

            conn.rollback()
            return False

    def _require_transport_proof(
        self, event: sqlite3.Row, transport_idempotency_key: str
    ) -> str:
        clean = _transport_key(transport_idempotency_key)
        expected = self._transport_idempotency_key(str(event["event_id"]))
        if not hmac.compare_digest(expected, clean):
            raise OutboxConflict("transport idempotency key does not match event identity")
        if not hmac.compare_digest(
            self._transport_key_hmac(clean), str(event["transport_key_hmac"])
        ):
            self._fail_closed("stored transport idempotency proof is invalid")
        return clean

    def _require_live_claim(
        self,
        event: sqlite3.Row,
        *,
        claim_handle: str,
        transport_idempotency_key: str,
        now: float,
    ) -> tuple[str, float]:
        handle = _lease_handle(claim_handle)
        self._require_transport_proof(event, transport_idempotency_key)
        if str(event["state"]) != LEASED:
            raise OutboxStateError(f"event is {event['state']}, not leased")
        lease_hmac = self._lease_hmac(handle)
        if not hmac.compare_digest(lease_hmac, str(event["lease_hmac"] or "")):
            raise OutboxLeaseLost("claim handle does not own the active lease")
        expiry = float(event["lease_expires_at"])
        if now >= expiry:
            raise OutboxLeaseLost("claim expired before the adapter outcome was recorded")
        return lease_hmac, expiry

    def mark_sent(
        self,
        event_id: str,
        *,
        claim_handle: str,
        transport_idempotency_key: str,
    ) -> dict[str, object]:
        """Record durable provider acceptance; this method performs no network send."""
        clean_event_id = _event_id(event_id)
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self._preflight_locked(conn)
            now = self._sample_clock_locked(conn)
            event, tail = self._load_event_tail_locked(conn, clean_event_id)
            supplied_hmac = self._lease_hmac(_lease_handle(claim_handle))
            self._require_transport_proof(event, transport_idempotency_key)
            if (
                str(event["state"]) == SENT
                and str(tail["kind"]) == _SENT
                and tail["lease_hmac"] is not None
                and hmac.compare_digest(str(tail["lease_hmac"]), supplied_hmac)
            ):
                status = self._status(conn, event)
                conn.commit()
                return status
            lease_hmac, expiry = self._require_live_claim(
                event,
                claim_handle=claim_handle,
                transport_idempotency_key=transport_idempotency_key,
                now=now,
            )
            self._transition_event_locked(
                conn,
                event,
                state=SENT,
                now=now,
                next_attempt_at=now,
                sent_at=now,
            )
            self._append_receipt(
                conn,
                event=event,
                kind=_SENT,
                from_state=LEASED,
                to_state=SENT,
                occurred_at=now,
                attempt_count=int(event["attempt_count"]),
                lease_hmac=lease_hmac,
                lease_expires_at=expiry,
                next_attempt_at=now,
                reason_code="provider_accepted",
            )
            updated = conn.execute(
                "SELECT * FROM notification_outbox_events WHERE event_id=?",
                (clean_event_id,),
            ).fetchone()
            status = self._status(conn, updated)
            self._commit_locked(conn, before)
            return status

    def record_failure(
        self,
        event_id: str,
        *,
        claim_handle: str,
        transport_idempotency_key: str,
    ) -> dict[str, object]:
        """Record a definitive no-acceptance result and apply frozen backoff."""
        clean_event_id = _event_id(event_id)
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self._preflight_locked(conn)
            now = self._sample_clock_locked(conn)
            event, tail = self._load_event_tail_locked(conn, clean_event_id)
            supplied_hmac = self._lease_hmac(_lease_handle(claim_handle))
            self._require_transport_proof(event, transport_idempotency_key)
            if (
                str(event["state"]) in {QUEUED, FAILED}
                and str(tail["kind"]) in {_RETRY_SCHEDULED, _DELIVERY_FAILED}
                and tail["lease_hmac"] is not None
                and hmac.compare_digest(str(tail["lease_hmac"]), supplied_hmac)
            ):
                status = self._status(conn, event)
                conn.commit()
                return status
            lease_hmac, expiry = self._require_live_claim(
                event,
                claim_handle=claim_handle,
                transport_idempotency_key=transport_idempotency_key,
                now=now,
            )
            terminal = int(event["attempt_count"]) >= int(event["max_attempts"])
            state = FAILED if terminal else QUEUED
            next_attempt = (
                now
                if terminal
                else now + self.policy.backoff_seconds(int(event["attempt_count"]))
            )
            self._transition_event_locked(
                conn,
                event,
                state=state,
                now=now,
                next_attempt_at=next_attempt,
                failed_at=now if terminal else None,
            )
            self._append_receipt(
                conn,
                event=event,
                kind=_DELIVERY_FAILED if terminal else _RETRY_SCHEDULED,
                from_state=LEASED,
                to_state=state,
                occurred_at=now,
                attempt_count=int(event["attempt_count"]),
                lease_hmac=lease_hmac,
                lease_expires_at=expiry,
                next_attempt_at=next_attempt,
                reason_code="provider_rejected",
            )
            updated = conn.execute(
                "SELECT * FROM notification_outbox_events WHERE event_id=?",
                (clean_event_id,),
            ).fetchone()
            status = self._status(conn, updated)
            self._commit_locked(conn, before)
            return status

    def mark_indeterminate(
        self,
        event_id: str,
        *,
        claim_handle: str,
        transport_idempotency_key: str,
    ) -> dict[str, object]:
        """Record an unknown provider outcome without making it retryable."""
        clean_event_id = _event_id(event_id)
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self._preflight_locked(conn)
            now = self._sample_clock_locked(conn)
            event, tail = self._load_event_tail_locked(conn, clean_event_id)
            supplied_hmac = self._lease_hmac(_lease_handle(claim_handle))
            self._require_transport_proof(event, transport_idempotency_key)
            if (
                str(event["state"]) == INDETERMINATE
                and str(tail["kind"]) == _DELIVERY_INDETERMINATE
                and tail["lease_hmac"] is not None
                and hmac.compare_digest(str(tail["lease_hmac"]), supplied_hmac)
            ):
                status = self._status(conn, event)
                conn.commit()
                return status
            lease_hmac, expiry = self._require_live_claim(
                event,
                claim_handle=claim_handle,
                transport_idempotency_key=transport_idempotency_key,
                now=now,
            )
            self._transition_event_locked(
                conn,
                event,
                state=INDETERMINATE,
                now=now,
                next_attempt_at=now,
                indeterminate_at=now,
            )
            self._append_receipt(
                conn,
                event=event,
                kind=_DELIVERY_INDETERMINATE,
                from_state=LEASED,
                to_state=INDETERMINATE,
                occurred_at=now,
                attempt_count=int(event["attempt_count"]),
                lease_hmac=lease_hmac,
                lease_expires_at=expiry,
                next_attempt_at=now,
                reason_code="provider_outcome_unknown",
            )
            updated = conn.execute(
                "SELECT * FROM notification_outbox_events WHERE event_id=?",
                (clean_event_id,),
            ).fetchone()
            status = self._status(conn, updated)
            self._commit_locked(conn, before)
            return status

    def reconcile_indeterminate(
        self,
        event_id: str,
        *,
        transport_idempotency_key: str,
        outcome: Literal["accepted", "not_accepted"],
    ) -> dict[str, object]:
        """Resolve an indeterminate provider outcome without external IDs."""
        clean_event_id = _event_id(event_id)
        if outcome not in {"accepted", "not_accepted"}:
            raise NotificationOutboxError("outcome must be accepted or not_accepted")
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self._preflight_locked(conn)
            now = self._sample_clock_locked(conn)
            event, tail = self._load_event_tail_locked(conn, clean_event_id)
            self._require_transport_proof(event, transport_idempotency_key)
            replay_kinds = (
                {_RECONCILED_SENT}
                if outcome == "accepted"
                else {_RECONCILED_RETRY, _RECONCILED_FAILED}
            )
            if str(tail["kind"]) in replay_kinds:
                status = self._status(conn, event)
                conn.commit()
                return status
            if str(event["state"]) != INDETERMINATE:
                raise OutboxStateError(
                    f"cannot reconcile a {event['state']} notification"
                )
            if outcome == "accepted":
                state = SENT
                next_attempt = now
                kind = _RECONCILED_SENT
                reason = "reconciled_accepted"
                self._transition_event_locked(
                    conn,
                    event,
                    state=state,
                    now=now,
                    next_attempt_at=next_attempt,
                    sent_at=now,
                )
            else:
                terminal = int(event["attempt_count"]) >= int(event["max_attempts"])
                state = FAILED if terminal else QUEUED
                next_attempt = (
                    now
                    if terminal
                    else now + self.policy.backoff_seconds(int(event["attempt_count"]))
                )
                kind = _RECONCILED_FAILED if terminal else _RECONCILED_RETRY
                reason = "reconciled_not_accepted"
                self._transition_event_locked(
                    conn,
                    event,
                    state=state,
                    now=now,
                    next_attempt_at=next_attempt,
                    failed_at=now if terminal else None,
                )
            self._append_receipt(
                conn,
                event=event,
                kind=kind,
                from_state=INDETERMINATE,
                to_state=state,
                occurred_at=now,
                attempt_count=int(event["attempt_count"]),
                next_attempt_at=next_attempt,
                reason_code=reason,
            )
            updated = conn.execute(
                "SELECT * FROM notification_outbox_events WHERE event_id=?",
                (clean_event_id,),
            ).fetchone()
            status = self._status(conn, updated)
            self._commit_locked(conn, before)
            return status

    def retry_indeterminate(
        self,
        event_id: str,
        *,
        transport_idempotency_key: str,
    ) -> dict[str, object]:
        """Queue an unknown outcome only when transport idempotency makes retry safe."""
        clean_event_id = _event_id(event_id)
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self._preflight_locked(conn)
            now = self._sample_clock_locked(conn)
            event, tail = self._load_event_tail_locked(conn, clean_event_id)
            self._require_transport_proof(event, transport_idempotency_key)
            if str(tail["kind"]) == _IDEMPOTENT_RETRY:
                status = self._status(conn, event)
                conn.commit()
                return status
            if str(event["state"]) != INDETERMINATE:
                raise OutboxStateError(f"event is {event['state']}, not indeterminate")
            adapter = str(event["adapter_name"])
            if not self.policy.supports_transport_idempotency(adapter):
                raise OutboxStateError(
                    "non-idempotent adapter requires accepted/not_accepted reconciliation"
                )
            if int(event["attempt_count"]) >= int(event["max_attempts"]):
                raise OutboxStateError(
                    "indeterminate event exhausted attempts and requires reconciliation"
                )
            next_attempt = now + self.policy.backoff_seconds(
                int(event["attempt_count"])
            )
            self._transition_event_locked(
                conn,
                event,
                state=QUEUED,
                now=now,
                next_attempt_at=next_attempt,
            )
            self._append_receipt(
                conn,
                event=event,
                kind=_IDEMPOTENT_RETRY,
                from_state=INDETERMINATE,
                to_state=QUEUED,
                occurred_at=now,
                attempt_count=int(event["attempt_count"]),
                next_attempt_at=next_attempt,
                reason_code="transport_idempotency_retry",
            )
            updated = conn.execute(
                "SELECT * FROM notification_outbox_events WHERE event_id=?",
                (clean_event_id,),
            ).fetchone()
            status = self._status(conn, updated)
            self._commit_locked(conn, before)
            return status

    def acknowledge(self, event_id: str) -> dict[str, object]:
        """Acknowledge only an event whose current sealed tail proves it was sent."""
        clean_event_id = _event_id(event_id)
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self._preflight_locked(conn)
            event, tail = self._load_event_tail_locked(conn, clean_event_id)
            if str(event["state"]) == ACKNOWLEDGED:
                status = self._status(conn, event)
                conn.commit()
                return status
            if str(event["state"]) != SENT or str(tail["kind"]) not in {
                _SENT,
                _RECONCILED_SENT,
            }:
                raise OutboxStateError(
                    "acknowledgement requires current durable sent evidence"
                )
            now = self._sample_clock_locked(conn)
            self._transition_event_locked(
                conn,
                event,
                state=ACKNOWLEDGED,
                now=now,
                next_attempt_at=now,
                acknowledged_at=now,
            )
            self._append_receipt(
                conn,
                event=event,
                kind=_ACKNOWLEDGED,
                from_state=SENT,
                to_state=ACKNOWLEDGED,
                occurred_at=now,
                attempt_count=int(event["attempt_count"]),
                next_attempt_at=now,
                reason_code="acknowledged",
            )
            updated = conn.execute(
                "SELECT * FROM notification_outbox_events WHERE event_id=?",
                (clean_event_id,),
            ).fetchone()
            status = self._status(conn, updated)
            self._commit_locked(conn, before)
            return status

    def cancel(self, event_id: str) -> dict[str, object]:
        """Cancel queued/indeterminate work; active leases fail instead of racing."""
        clean_event_id = _event_id(event_id)
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            before = self._preflight_locked(conn)
            event, _tail = self._load_event_tail_locked(conn, clean_event_id)
            state = str(event["state"])
            if state == CANCELLED:
                status = self._status(conn, event)
                conn.commit()
                return status
            if state == LEASED:
                raise OutboxStateError("cannot cancel while an adapter lease is active")
            if state not in {QUEUED, INDETERMINATE}:
                raise OutboxStateError(f"cannot cancel a {state} notification")
            now = self._sample_clock_locked(conn)
            self._transition_event_locked(
                conn,
                event,
                state=CANCELLED,
                now=now,
                next_attempt_at=now,
                cancelled_at=now,
            )
            self._append_receipt(
                conn,
                event=event,
                kind=_CANCELLED,
                from_state=state,
                to_state=CANCELLED,
                occurred_at=now,
                attempt_count=int(event["attempt_count"]),
                next_attempt_at=now,
                reason_code="cancelled",
            )
            updated = conn.execute(
                "SELECT * FROM notification_outbox_events WHERE event_id=?",
                (clean_event_id,),
            ).fetchone()
            status = self._status(conn, updated)
            self._commit_locked(conn, before)
            return status

    def get_event(self, event_id: str) -> dict[str, object]:
        """Return content-free event status after anchored tail verification."""
        clean_event_id = _event_id(event_id)
        self._require_available()
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            checkpoint = self._reconcile_anchor_locked(conn)
            self._verify_global_tail_locked(conn, checkpoint)
            event, _tail = self._load_event_tail_locked(conn, clean_event_id)
            status = self._status(conn, event)
            conn.commit()
            return status

    def transition_receipts(
        self,
        event_id: str,
        *,
        cursor: str | None = None,
    ) -> dict[str, object]:
        """Return one fixed-size verified receipt page."""
        clean_event_id = _event_id(event_id)
        self._require_available()
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            checkpoint = self._reconcile_anchor_locked(conn)
            self._verify_global_tail_locked(conn, checkpoint)
            event, _tail = self._load_event_tail_locked(conn, clean_event_id)
            after_sequence = 0
            previous_event_seal = ""
            previous_state: str | None = None
            previous_time = -1.0
            if cursor is not None:
                after_sequence = self._receipt_cursor_sequence(cursor)
                if after_sequence > int(event["event_receipt_count"]):
                    raise OutboxConflict("receipt cursor is beyond the event tail")
                boundary = conn.execute(
                    "SELECT * FROM notification_outbox_receipts "
                    "WHERE event_id=? AND event_sequence=?",
                    (clean_event_id, after_sequence),
                ).fetchone()
                if boundary is None:
                    self._fail_closed("receipt cursor boundary is missing")
                self._verify_receipt(boundary)
                expected_cursor = self._receipt_cursor(
                    clean_event_id,
                    after_sequence,
                    str(boundary["receipt_seal"]),
                )
                if not hmac.compare_digest(expected_cursor, cursor):
                    raise OutboxConflict("receipt cursor does not match its boundary")
                previous_event_seal = str(boundary["receipt_seal"])
                previous_state = str(boundary["to_state"])
                previous_time = float(boundary["occurred_at"])
            rows = conn.execute(
                "SELECT r.*,gp.receipt_seal AS linked_global_seal "
                "FROM notification_outbox_receipts r "
                "LEFT JOIN notification_outbox_receipts gp "
                "ON gp.global_sequence=r.global_sequence-1 "
                "WHERE r.event_id=? AND r.event_sequence>? "
                "ORDER BY r.event_sequence LIMIT ?",
                (clean_event_id, after_sequence, _RECEIPT_PAGE_SIZE + 1),
            ).fetchall()
            expected_sequence = after_sequence + 1
            for row in rows:
                self._verify_receipt(row)
                global_sequence = int(row["global_sequence"])
                linked_global_seal = (
                    "" if global_sequence == 1 else row["linked_global_seal"]
                )
                if (
                    int(row["event_sequence"]) != expected_sequence
                    or str(row["previous_event_seal"]) != previous_event_seal
                    or row["from_state"] != previous_state
                    or float(row["occurred_at"]) < previous_time
                    or str(row["transport_key_hmac"])
                    != str(event["transport_key_hmac"])
                    or linked_global_seal is None
                    or str(row["previous_global_seal"])
                    != str(linked_global_seal)
                ):
                    self._fail_closed("receipt page boundary or chain is discontinuous")
                previous_event_seal = str(row["receipt_seal"])
                previous_state = str(row["to_state"])
                previous_time = float(row["occurred_at"])
                expected_sequence += 1

            has_more = len(rows) > _RECEIPT_PAGE_SIZE
            visible = rows[:_RECEIPT_PAGE_SIZE]
            if not has_more:
                final_sequence = (
                    after_sequence
                    if not rows
                    else int(rows[-1]["event_sequence"])
                )
                if (
                    final_sequence != int(event["event_receipt_count"])
                    or previous_event_seal != str(event["event_head_seal"])
                ):
                    self._fail_closed("receipt page does not terminate at the event tail")
            next_cursor = None
            if has_more:
                page_tail = visible[-1]
                next_cursor = self._receipt_cursor(
                    clean_event_id,
                    int(page_tail["event_sequence"]),
                    str(page_tail["receipt_seal"]),
                )
            page = {
                "event_id": clean_event_id,
                "receipts": [self._public_receipt(row) for row in visible],
                "next_cursor": next_cursor,
            }
            conn.commit()
            return page

    def public_status(self) -> dict[str, object]:
        """Return anchored aggregate counts with no payload, claim, or adapter facts."""
        self._require_available()
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            checkpoint = self._reconcile_anchor_locked(conn)
            self._verify_global_tail_locked(conn, checkpoint)
            counts = {state: 0 for state in STATES}
            for row in conn.execute(
                "SELECT state,COUNT(*) AS count FROM notification_outbox_events GROUP BY state"
            ).fetchall():
                counts[str(row["state"])] = int(row["count"])
            if sum(counts.values()) != checkpoint.event_count:
                self._fail_closed(
                    "public event counts do not match anchored metadata"
                )
            conn.commit()
            return {
                "contract_version": CONTRACT_VERSION,
                "policy_id": self.policy.policy_id,
                "policy_version": self.policy.policy_version,
                "anchored_sequence": checkpoint.sequence,
                "total": checkpoint.event_count,
                "states": counts,
                "transition_receipts": checkpoint.receipt_count,
                "quarantined": False,
            }


__all__ = [
    "ACKNOWLEDGED",
    "AnchorSnapshot",
    "CANCELLED",
    "CONTRACT_VERSION",
    "DeliveryClaim",
    "FAILED",
    "INDETERMINATE",
    "InMemoryMonotonicAnchor",
    "LEASED",
    "LedgerCheckpoint",
    "MonotonicAnchor",
    "NotificationOutbox",
    "NotificationOutboxError",
    "OpaquePayloadRef",
    "OutboxAnchorError",
    "OutboxConflict",
    "OutboxIntegrityError",
    "OutboxLeaseLost",
    "OutboxNotFound",
    "OutboxPolicy",
    "OutboxPolicyMismatch",
    "OutboxQuarantined",
    "OutboxStateError",
    "QUEUED",
    "QuietHours",
    "SENT",
    "STATES",
]
