"""Deterministic, in-memory controls for bounded initiative.

The policy accepts explicit timestamps and performs no I/O.  Only externally
observed events create epochs; policy-generated initiatives are intentionally
ignored as observations.  A follow-up can be reserved once for each event
epoch, while quiet check-ins use an independent long-quiet threshold and
cooldown.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal


EventOrigin = Literal["external", "initiative"]
ObservationReason = Literal["observed", "duplicate_event", "initiative_origin"]
ReservationKind = Literal["follow_up", "check_in"]
ReservationReason = Literal[
    "reserved",
    "unknown_event",
    "event_epoch_mismatch",
    "event_already_reserved",
    "no_observed_activity",
    "quiet_period",
    "check_in_cooldown",
]
OutcomeKind = Literal["passed", "failed"]
OutcomeReason = Literal[
    "recorded",
    "already_recorded",
    "outcome_conflict",
    "unknown_reservation",
]

_STATE_VERSION = 1
_DEFAULT_SCOPE = "default"
_MAX_SCOPE_LENGTH = 160
_MAX_EVENT_ID_LENGTH = 256
_MAX_RESERVATION_ID_LENGTH = 96


@dataclass(frozen=True, slots=True)
class ObservedEvent:
    """The stable epoch assigned to one externally observed event."""

    accepted: bool
    reason: ObservationReason
    scope: str
    event_id: str
    epoch: int | None
    observed_at: float | None

    @property
    def is_new(self) -> bool:
        """Whether this call created a new externally observed event epoch."""
        return self.accepted


@dataclass(frozen=True, slots=True)
class InitiativeReservation:
    """The result of attempting to reserve one bounded initiative."""

    granted: bool
    reason: ReservationReason
    kind: ReservationKind
    scope: str
    reservation_id: str | None
    event_id: str | None
    event_epoch: int | None
    reserved_at: float
    retry_at: float | None


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    """The idempotent outcome state for a previously created reservation."""

    recorded: bool
    consumed: bool
    reason: OutcomeReason
    reservation_id: str
    outcome: OutcomeKind | None
    recorded_at: float


@dataclass(frozen=True, slots=True)
class InitiativeStatus:
    """A content-free snapshot of one initiative scope."""

    scope: str
    event_epoch: int
    observed_event_count: int
    reserved_follow_up_count: int
    pending_follow_up_count: int
    passed_follow_up_count: int
    failed_follow_up_count: int
    check_in_count: int
    pending_check_in_count: int
    passed_check_in_count: int
    failed_check_in_count: int
    last_observed_at: float | None
    quiet_for_seconds: float | None
    quiet_eligible_at: float | None
    last_check_in_at: float | None
    check_in_cooldown_until: float | None
    next_check_in_at: float | None
    check_in_eligible: bool

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe form for diagnostics or persistence receipts."""
        return {
            "scope": self.scope,
            "event_epoch": self.event_epoch,
            "observed_event_count": self.observed_event_count,
            "reserved_follow_up_count": self.reserved_follow_up_count,
            "pending_follow_up_count": self.pending_follow_up_count,
            "passed_follow_up_count": self.passed_follow_up_count,
            "failed_follow_up_count": self.failed_follow_up_count,
            "check_in_count": self.check_in_count,
            "pending_check_in_count": self.pending_check_in_count,
            "passed_check_in_count": self.passed_check_in_count,
            "failed_check_in_count": self.failed_check_in_count,
            "last_observed_at": self.last_observed_at,
            "quiet_for_seconds": self.quiet_for_seconds,
            "quiet_eligible_at": self.quiet_eligible_at,
            "last_check_in_at": self.last_check_in_at,
            "check_in_cooldown_until": self.check_in_cooldown_until,
            "next_check_in_at": self.next_check_in_at,
            "check_in_eligible": self.check_in_eligible,
        }


@dataclass(slots=True)
class _EventState:
    event_id: str
    epoch: int
    observed_at: float
    reservation_id: str | None = None


@dataclass(slots=True)
class _ReservationState:
    reservation_id: str
    kind: ReservationKind
    scope: str
    event_id: str | None
    event_epoch: int | None
    reserved_at: float
    outcome: OutcomeKind | None = None
    outcome_at: float | None = None


@dataclass(slots=True)
class _ScopeState:
    epoch: int = 0
    last_observed_at: float | None = None
    last_check_in_at: float | None = None
    events_by_id: dict[str, _EventState] = field(default_factory=dict)
    events_by_epoch: dict[int, _EventState] = field(default_factory=dict)
    reservation_ids: list[str] = field(default_factory=list)


class InitiativePolicy:
    """Pure state machine for general, bounded initiative control.

    The caller owns time and supplies a monotonic, restart-comparable ``now``
    value on every stateful operation.  This makes decisions deterministic and
    allows :meth:`to_dict` / :meth:`from_dict` to preserve the same limits over
    a restart without relying on a local process clock.
    """

    def __init__(
        self,
        *,
        long_quiet_seconds: float = 6 * 60 * 60,
        check_in_cooldown_seconds: float = 2 * 60 * 60,
    ) -> None:
        self.long_quiet_seconds = self._duration(
            long_quiet_seconds,
            name="long_quiet_seconds",
        )
        self.check_in_cooldown_seconds = self._duration(
            check_in_cooldown_seconds,
            name="check_in_cooldown_seconds",
        )
        self._scopes: dict[str, _ScopeState] = {}
        self._reservations: dict[str, _ReservationState] = {}
        self._next_reservation_index = 1
        self._last_now: float | None = None

    @staticmethod
    def _number(value: object, *, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be numeric")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{name} must be finite")
        return numeric

    @classmethod
    def _duration(cls, value: object, *, name: str) -> float:
        duration = cls._number(value, name=name)
        if duration < 0.0:
            raise ValueError(f"{name} cannot be negative")
        return duration

    @staticmethod
    def _identifier(value: object, *, name: str, maximum: int) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{name} is required")
        if len(cleaned) > maximum:
            raise ValueError(f"{name} exceeds {maximum} characters")
        if any(ord(character) < 32 for character in cleaned):
            raise ValueError(f"{name} contains control characters")
        return cleaned

    @classmethod
    def _scope(cls, value: object) -> str:
        return cls._identifier(value, name="scope", maximum=_MAX_SCOPE_LENGTH)

    @classmethod
    def _event_id(cls, value: object) -> str:
        return cls._identifier(value, name="event_id", maximum=_MAX_EVENT_ID_LENGTH)

    @classmethod
    def _reservation_id(cls, value: object) -> str:
        return cls._identifier(
            value,
            name="reservation_id",
            maximum=_MAX_RESERVATION_ID_LENGTH,
        )

    @staticmethod
    def _epoch(value: object, *, name: str = "event_epoch") -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
        return value

    @staticmethod
    def _nonnegative_integer(value: object, *, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
        return value

    @staticmethod
    def _origin(value: object) -> EventOrigin:
        if value not in ("external", "initiative"):
            raise ValueError("origin must be 'external' or 'initiative'")
        return value  # type: ignore[return-value]

    @staticmethod
    def _outcome(value: object) -> OutcomeKind:
        if not isinstance(value, str):
            raise TypeError("outcome must be a string")
        normalized = value.strip().lower()
        aliases: dict[str, OutcomeKind] = {
            "pass": "passed",
            "passed": "passed",
            "success": "passed",
            "failure": "failed",
            "fail": "failed",
            "failed": "failed",
        }
        try:
            return aliases[normalized]
        except KeyError as error:
            raise ValueError("outcome must be passed or failed") from error

    def _now(self, value: object) -> float:
        now = self._number(value, name="now")
        if self._last_now is not None and now < self._last_now:
            raise ValueError("now moved backwards")
        self._last_now = now
        return now

    def _state(self, scope: str) -> _ScopeState:
        return self._scopes.setdefault(scope, _ScopeState())

    def observe_event(
        self,
        event_id: str,
        *,
        now: float,
        scope: str = _DEFAULT_SCOPE,
        origin: EventOrigin = "external",
    ) -> ObservedEvent:
        """Record one external event or ignore a policy-generated echo.

        Repeating an external event ID is idempotent: it returns the original
        epoch and does not make the scope appear newly active.  Callers should
        therefore use a stable event ID from their input source.
        """
        clean_scope = self._scope(scope)
        clean_event_id = self._event_id(event_id)
        clean_origin = self._origin(origin)
        current = self._now(now)
        state = self._state(clean_scope)

        if clean_origin == "initiative":
            return ObservedEvent(
                accepted=False,
                reason="initiative_origin",
                scope=clean_scope,
                event_id=clean_event_id,
                epoch=None,
                observed_at=None,
            )

        existing = state.events_by_id.get(clean_event_id)
        if existing is not None:
            return ObservedEvent(
                accepted=False,
                reason="duplicate_event",
                scope=clean_scope,
                event_id=existing.event_id,
                epoch=existing.epoch,
                observed_at=existing.observed_at,
            )

        state.epoch += 1
        event = _EventState(
            event_id=clean_event_id,
            epoch=state.epoch,
            observed_at=current,
        )
        state.events_by_id[event.event_id] = event
        state.events_by_epoch[event.epoch] = event
        state.last_observed_at = current
        return ObservedEvent(
            accepted=True,
            reason="observed",
            scope=clean_scope,
            event_id=event.event_id,
            epoch=event.epoch,
            observed_at=event.observed_at,
        )

    def _new_reservation(
        self,
        *,
        state: _ScopeState,
        scope: str,
        kind: ReservationKind,
        now: float,
        event: _EventState | None,
    ) -> InitiativeReservation:
        while True:
            reservation_id = f"r{self._next_reservation_index}"
            self._next_reservation_index += 1
            if reservation_id not in self._reservations:
                break
        reservation = _ReservationState(
            reservation_id=reservation_id,
            kind=kind,
            scope=scope,
            event_id=None if event is None else event.event_id,
            event_epoch=None if event is None else event.epoch,
            reserved_at=now,
        )
        self._reservations[reservation_id] = reservation
        state.reservation_ids.append(reservation_id)
        if event is not None:
            event.reservation_id = reservation_id
        if kind == "check_in":
            state.last_check_in_at = now
        return InitiativeReservation(
            granted=True,
            reason="reserved",
            kind=kind,
            scope=scope,
            reservation_id=reservation_id,
            event_id=reservation.event_id,
            event_epoch=reservation.event_epoch,
            reserved_at=now,
            retry_at=None,
        )

    def reserve_follow_up(
        self,
        *,
        event_epoch: int,
        now: float,
        scope: str = _DEFAULT_SCOPE,
        event_id: str | None = None,
    ) -> InitiativeReservation:
        """Reserve the single normal follow-up allowed for an event epoch."""
        clean_scope = self._scope(scope)
        clean_epoch = self._epoch(event_epoch)
        clean_event_id = None if event_id is None else self._event_id(event_id)
        current = self._now(now)
        state = self._state(clean_scope)
        event = state.events_by_epoch.get(clean_epoch)

        if event is None:
            return InitiativeReservation(
                granted=False,
                reason="unknown_event",
                kind="follow_up",
                scope=clean_scope,
                reservation_id=None,
                event_id=clean_event_id,
                event_epoch=clean_epoch,
                reserved_at=current,
                retry_at=None,
            )
        if clean_event_id is not None and clean_event_id != event.event_id:
            return InitiativeReservation(
                granted=False,
                reason="event_epoch_mismatch",
                kind="follow_up",
                scope=clean_scope,
                reservation_id=None,
                event_id=clean_event_id,
                event_epoch=clean_epoch,
                reserved_at=current,
                retry_at=None,
            )
        if event.reservation_id is not None:
            return InitiativeReservation(
                granted=False,
                reason="event_already_reserved",
                kind="follow_up",
                scope=clean_scope,
                reservation_id=event.reservation_id,
                event_id=event.event_id,
                event_epoch=event.epoch,
                reserved_at=current,
                retry_at=None,
            )
        return self._new_reservation(
            state=state,
            scope=clean_scope,
            kind="follow_up",
            now=current,
            event=event,
        )

    def reserve_for_event(
        self,
        *,
        event_epoch: int,
        now: float,
        scope: str = _DEFAULT_SCOPE,
        event_id: str | None = None,
    ) -> InitiativeReservation:
        """Alias for :meth:`reserve_follow_up` for generic callers."""
        return self.reserve_follow_up(
            event_epoch=event_epoch,
            now=now,
            scope=scope,
            event_id=event_id,
        )

    def reserve_quiet_check_in(
        self,
        *,
        now: float,
        scope: str = _DEFAULT_SCOPE,
    ) -> InitiativeReservation:
        """Reserve a check-in only after a long quiet period and cooldown."""
        clean_scope = self._scope(scope)
        current = self._now(now)
        state = self._state(clean_scope)

        if state.last_observed_at is None:
            return InitiativeReservation(
                granted=False,
                reason="no_observed_activity",
                kind="check_in",
                scope=clean_scope,
                reservation_id=None,
                event_id=None,
                event_epoch=None,
                reserved_at=current,
                retry_at=None,
            )

        quiet_eligible_at = state.last_observed_at + self.long_quiet_seconds
        if current < quiet_eligible_at:
            return InitiativeReservation(
                granted=False,
                reason="quiet_period",
                kind="check_in",
                scope=clean_scope,
                reservation_id=None,
                event_id=None,
                event_epoch=None,
                reserved_at=current,
                retry_at=quiet_eligible_at,
            )

        if state.last_check_in_at is not None:
            cooldown_until = state.last_check_in_at + self.check_in_cooldown_seconds
            if current < cooldown_until:
                return InitiativeReservation(
                    granted=False,
                    reason="check_in_cooldown",
                    kind="check_in",
                    scope=clean_scope,
                    reservation_id=None,
                    event_id=None,
                    event_epoch=None,
                    reserved_at=current,
                    retry_at=cooldown_until,
                )

        return self._new_reservation(
            state=state,
            scope=clean_scope,
            kind="check_in",
            now=current,
            event=None,
        )

    def reserve_check_in(
        self,
        *,
        now: float,
        scope: str = _DEFAULT_SCOPE,
    ) -> InitiativeReservation:
        """Alias for :meth:`reserve_quiet_check_in`."""
        return self.reserve_quiet_check_in(now=now, scope=scope)

    def record_outcome(
        self,
        reservation_id: str,
        outcome: OutcomeKind | str,
        *,
        now: float,
    ) -> OutcomeRecord:
        """Record a terminal outcome without releasing the consumed allowance.

        A matching repeat is idempotent.  A different repeat is rejected, and
        neither result reopens an event epoch or shortens a check-in cooldown.
        """
        clean_reservation_id = self._reservation_id(reservation_id)
        clean_outcome = self._outcome(outcome)
        current = self._now(now)
        reservation = self._reservations.get(clean_reservation_id)
        if reservation is None:
            return OutcomeRecord(
                recorded=False,
                consumed=False,
                reason="unknown_reservation",
                reservation_id=clean_reservation_id,
                outcome=None,
                recorded_at=current,
            )
        if reservation.outcome is None:
            reservation.outcome = clean_outcome
            reservation.outcome_at = current
            return OutcomeRecord(
                recorded=True,
                consumed=True,
                reason="recorded",
                reservation_id=reservation.reservation_id,
                outcome=reservation.outcome,
                recorded_at=current,
            )
        if reservation.outcome == clean_outcome:
            return OutcomeRecord(
                recorded=False,
                consumed=True,
                reason="already_recorded",
                reservation_id=reservation.reservation_id,
                outcome=reservation.outcome,
                recorded_at=current,
            )
        return OutcomeRecord(
            recorded=False,
            consumed=True,
            reason="outcome_conflict",
            reservation_id=reservation.reservation_id,
            outcome=reservation.outcome,
            recorded_at=current,
        )

    def snapshot(
        self,
        *,
        now: float,
        scope: str = _DEFAULT_SCOPE,
    ) -> InitiativeStatus:
        """Return current, content-free status for one scope."""
        clean_scope = self._scope(scope)
        current = self._now(now)
        state = self._state(clean_scope)

        follow_up_count = 0
        pending_follow_up_count = 0
        passed_follow_up_count = 0
        failed_follow_up_count = 0
        check_in_count = 0
        pending_check_in_count = 0
        passed_check_in_count = 0
        failed_check_in_count = 0
        for reservation_id in state.reservation_ids:
            reservation = self._reservations[reservation_id]
            if reservation.kind == "follow_up":
                follow_up_count += 1
                if reservation.outcome is None:
                    pending_follow_up_count += 1
                elif reservation.outcome == "passed":
                    passed_follow_up_count += 1
                else:
                    failed_follow_up_count += 1
            else:
                check_in_count += 1
                if reservation.outcome is None:
                    pending_check_in_count += 1
                elif reservation.outcome == "passed":
                    passed_check_in_count += 1
                else:
                    failed_check_in_count += 1

        quiet_for_seconds: float | None = None
        quiet_eligible_at: float | None = None
        cooldown_until: float | None = None
        next_check_in_at: float | None = None
        check_in_eligible = False
        if state.last_observed_at is not None:
            quiet_for_seconds = current - state.last_observed_at
            quiet_eligible_at = state.last_observed_at + self.long_quiet_seconds
            if state.last_check_in_at is not None:
                cooldown_until = (
                    state.last_check_in_at + self.check_in_cooldown_seconds
                )
            next_check_in_at = quiet_eligible_at
            if cooldown_until is not None:
                next_check_in_at = max(next_check_in_at, cooldown_until)
            check_in_eligible = current >= next_check_in_at

        return InitiativeStatus(
            scope=clean_scope,
            event_epoch=state.epoch,
            observed_event_count=len(state.events_by_epoch),
            reserved_follow_up_count=follow_up_count,
            pending_follow_up_count=pending_follow_up_count,
            passed_follow_up_count=passed_follow_up_count,
            failed_follow_up_count=failed_follow_up_count,
            check_in_count=check_in_count,
            pending_check_in_count=pending_check_in_count,
            passed_check_in_count=passed_check_in_count,
            failed_check_in_count=failed_check_in_count,
            last_observed_at=state.last_observed_at,
            quiet_for_seconds=quiet_for_seconds,
            quiet_eligible_at=quiet_eligible_at,
            last_check_in_at=state.last_check_in_at,
            check_in_cooldown_until=cooldown_until,
            next_check_in_at=next_check_in_at,
            check_in_eligible=check_in_eligible,
        )

    def status_snapshot(
        self,
        *,
        now: float,
        scope: str = _DEFAULT_SCOPE,
    ) -> InitiativeStatus:
        """Alias for :meth:`snapshot`."""
        return self.snapshot(now=now, scope=scope)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe, restart-safe representation of policy state."""
        scopes: dict[str, object] = {}
        for scope in sorted(self._scopes):
            state = self._scopes[scope]
            scopes[scope] = {
                "epoch": state.epoch,
                "last_observed_at": state.last_observed_at,
                "last_check_in_at": state.last_check_in_at,
                "events": [
                    {
                        "event_id": event.event_id,
                        "epoch": event.epoch,
                        "observed_at": event.observed_at,
                        "reservation_id": event.reservation_id,
                    }
                    for event in sorted(
                        state.events_by_epoch.values(),
                        key=lambda event: event.epoch,
                    )
                ],
            }
        reservations: list[dict[str, object]] = []
        for reservation_id in sorted(self._reservations):
            reservation = self._reservations[reservation_id]
            reservations.append({
                "reservation_id": reservation.reservation_id,
                "kind": reservation.kind,
                "scope": reservation.scope,
                "event_id": reservation.event_id,
                "event_epoch": reservation.event_epoch,
                "reserved_at": reservation.reserved_at,
                "outcome": reservation.outcome,
                "outcome_at": reservation.outcome_at,
            })
        return {
            "version": _STATE_VERSION,
            "long_quiet_seconds": self.long_quiet_seconds,
            "check_in_cooldown_seconds": self.check_in_cooldown_seconds,
            "last_now": self._last_now,
            "next_reservation_index": self._next_reservation_index,
            "scopes": scopes,
            "reservations": reservations,
        }

    def export_state(self) -> dict[str, object]:
        """Alias for :meth:`to_dict` for persistence-oriented callers."""
        return self.to_dict()

    @staticmethod
    def _mapping(value: object, *, name: str) -> Mapping[object, object]:
        if not isinstance(value, Mapping):
            raise ValueError(f"{name} must be a mapping")
        return value

    @staticmethod
    def _sequence(value: object, *, name: str) -> list[object]:
        if not isinstance(value, list):
            raise ValueError(f"{name} must be a list")
        return value

    @staticmethod
    def _required(mapping: Mapping[object, object], key: str, *, name: str) -> object:
        if key not in mapping:
            raise ValueError(f"{name} is missing {key}")
        return mapping[key]

    @classmethod
    def _optional_number(cls, value: object, *, name: str) -> float | None:
        if value is None:
            return None
        return cls._number(value, name=name)

    @classmethod
    def _serialized_epoch(cls, value: object, *, name: str) -> int:
        return cls._epoch(value, name=name)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "InitiativePolicy":
        """Restore a policy state after validating its complete invariants."""
        raw = cls._mapping(payload, name="payload")
        version = cls._serialized_epoch(
            cls._required(raw, "version", name="payload"),
            name="version",
        )
        if version != _STATE_VERSION:
            raise ValueError(f"unsupported initiative policy state version: {version}")
        policy = cls(
            long_quiet_seconds=cls._duration(
                cls._required(raw, "long_quiet_seconds", name="payload"),
                name="long_quiet_seconds",
            ),
            check_in_cooldown_seconds=cls._duration(
                cls._required(raw, "check_in_cooldown_seconds", name="payload"),
                name="check_in_cooldown_seconds",
            ),
        )
        next_reservation_index = cls._serialized_epoch(
            cls._required(raw, "next_reservation_index", name="payload"),
            name="next_reservation_index",
        )
        raw_last_now = cls._optional_number(
            cls._required(raw, "last_now", name="payload"),
            name="last_now",
        )
        scopes = cls._mapping(
            cls._required(raw, "scopes", name="payload"),
            name="scopes",
        )
        timestamps: list[float] = []

        for raw_scope, raw_state in scopes.items():
            clean_scope = cls._scope(raw_scope)
            if clean_scope != raw_scope:
                raise ValueError("serialized scope must already be normalized")
            if clean_scope in policy._scopes:
                raise ValueError(f"duplicate serialized scope: {clean_scope}")
            state_data = cls._mapping(raw_state, name=f"scope {clean_scope}")
            epoch = cls._nonnegative_integer(
                cls._required(state_data, "epoch", name=f"scope {clean_scope}"),
                name=f"scope {clean_scope} epoch",
            )
            last_observed_at = cls._optional_number(
                cls._required(
                    state_data,
                    "last_observed_at",
                    name=f"scope {clean_scope}",
                ),
                name=f"scope {clean_scope} last_observed_at",
            )
            last_check_in_at = cls._optional_number(
                cls._required(
                    state_data,
                    "last_check_in_at",
                    name=f"scope {clean_scope}",
                ),
                name=f"scope {clean_scope} last_check_in_at",
            )
            state = _ScopeState(
                epoch=epoch,
                last_observed_at=last_observed_at,
                last_check_in_at=last_check_in_at,
            )
            event_rows = cls._sequence(
                cls._required(state_data, "events", name=f"scope {clean_scope}"),
                name=f"scope {clean_scope} events",
            )
            if len(event_rows) != state.epoch:
                raise ValueError(f"scope {clean_scope} event count does not match epoch")
            for raw_event in event_rows:
                event_data = cls._mapping(raw_event, name=f"scope {clean_scope} event")
                event_id = cls._event_id(
                    cls._required(event_data, "event_id", name="event")
                )
                event_epoch = cls._serialized_epoch(
                    cls._required(event_data, "epoch", name="event"),
                    name="event epoch",
                )
                observed_at = cls._number(
                    cls._required(event_data, "observed_at", name="event"),
                    name="event observed_at",
                )
                raw_reservation_id = cls._required(
                    event_data,
                    "reservation_id",
                    name="event",
                )
                reservation_id = (
                    None
                    if raw_reservation_id is None
                    else cls._reservation_id(raw_reservation_id)
                )
                if event_id in state.events_by_id or event_epoch in state.events_by_epoch:
                    raise ValueError(f"duplicate serialized event in scope {clean_scope}")
                event = _EventState(
                    event_id=event_id,
                    epoch=event_epoch,
                    observed_at=observed_at,
                    reservation_id=reservation_id,
                )
                state.events_by_id[event_id] = event
                state.events_by_epoch[event_epoch] = event
                timestamps.append(observed_at)
            if set(state.events_by_epoch) != set(range(1, state.epoch + 1)):
                raise ValueError(f"scope {clean_scope} has non-contiguous event epochs")
            if state.events_by_epoch:
                expected_last_observed_at = max(
                    event.observed_at for event in state.events_by_epoch.values()
                )
                if last_observed_at != expected_last_observed_at:
                    raise ValueError(f"scope {clean_scope} has inconsistent last_observed_at")
            elif last_observed_at is not None:
                raise ValueError(f"scope {clean_scope} has activity without an event")
            policy._scopes[clean_scope] = state

        reservations = cls._sequence(
            cls._required(raw, "reservations", name="payload"),
            name="reservations",
        )
        for raw_reservation in reservations:
            reservation_data = cls._mapping(raw_reservation, name="reservation")
            reservation_id = cls._reservation_id(
                cls._required(reservation_data, "reservation_id", name="reservation")
            )
            if reservation_id in policy._reservations:
                raise ValueError(f"duplicate serialized reservation: {reservation_id}")
            raw_kind = cls._required(reservation_data, "kind", name="reservation")
            if raw_kind not in ("follow_up", "check_in"):
                raise ValueError("reservation kind must be follow_up or check_in")
            kind: ReservationKind = raw_kind  # type: ignore[assignment]
            scope = cls._scope(
                cls._required(reservation_data, "scope", name="reservation")
            )
            state = policy._scopes.get(scope)
            if state is None:
                raise ValueError(f"reservation {reservation_id} has an unknown scope")
            raw_event_id = cls._required(
                reservation_data,
                "event_id",
                name="reservation",
            )
            raw_event_epoch = cls._required(
                reservation_data,
                "event_epoch",
                name="reservation",
            )
            event_id = None if raw_event_id is None else cls._event_id(raw_event_id)
            event_epoch = (
                None
                if raw_event_epoch is None
                else cls._serialized_epoch(
                    raw_event_epoch,
                    name="reservation event_epoch",
                )
            )
            reserved_at = cls._number(
                cls._required(reservation_data, "reserved_at", name="reservation"),
                name="reservation reserved_at",
            )
            raw_outcome = cls._required(reservation_data, "outcome", name="reservation")
            outcome = None if raw_outcome is None else cls._outcome(raw_outcome)
            outcome_at = cls._optional_number(
                cls._required(reservation_data, "outcome_at", name="reservation"),
                name="reservation outcome_at",
            )
            if (outcome is None) != (outcome_at is None):
                raise ValueError("reservation outcome and outcome_at must appear together")
            if outcome_at is not None and outcome_at < reserved_at:
                raise ValueError("reservation outcome_at cannot precede reserved_at")
            if kind == "follow_up":
                if event_id is None or event_epoch is None:
                    raise ValueError("follow_up reservations require an event")
                event = state.events_by_epoch.get(event_epoch)
                if event is None or event.event_id != event_id:
                    raise ValueError("follow_up reservation does not match its event")
                if event.reservation_id != reservation_id:
                    raise ValueError("event reservation pointer does not match")
            elif event_id is not None or event_epoch is not None:
                raise ValueError("check_in reservations cannot reference an event")
            reservation = _ReservationState(
                reservation_id=reservation_id,
                kind=kind,
                scope=scope,
                event_id=event_id,
                event_epoch=event_epoch,
                reserved_at=reserved_at,
                outcome=outcome,
                outcome_at=outcome_at,
            )
            policy._reservations[reservation_id] = reservation
            state.reservation_ids.append(reservation_id)
            timestamps.append(reserved_at)
            if outcome_at is not None:
                timestamps.append(outcome_at)

        for scope, state in policy._scopes.items():
            for event in state.events_by_epoch.values():
                if event.reservation_id is None:
                    continue
                reservation = policy._reservations.get(event.reservation_id)
                if (
                    reservation is None
                    or reservation.kind != "follow_up"
                    or reservation.scope != scope
                    or reservation.event_epoch != event.epoch
                    or reservation.event_id != event.event_id
                ):
                    raise ValueError(f"scope {scope} has an invalid event reservation")
            check_in_times = [
                policy._reservations[reservation_id].reserved_at
                for reservation_id in state.reservation_ids
                if policy._reservations[reservation_id].kind == "check_in"
            ]
            expected_last_check_in_at = max(check_in_times, default=None)
            if state.last_check_in_at != expected_last_check_in_at:
                raise ValueError(f"scope {scope} has inconsistent last_check_in_at")

        if timestamps and raw_last_now is None:
            raise ValueError("serialized state with activity requires last_now")
        if raw_last_now is not None and timestamps and raw_last_now < max(timestamps):
            raise ValueError("last_now cannot precede recorded policy state")
        policy._last_now = raw_last_now
        policy._next_reservation_index = next_reservation_index
        return policy

    @classmethod
    def from_state(cls, payload: Mapping[str, object]) -> "InitiativePolicy":
        """Alias for :meth:`from_dict` for persistence-oriented callers."""
        return cls.from_dict(payload)


InitiativeControlPolicy = InitiativePolicy


__all__ = [
    "EventOrigin",
    "InitiativeControlPolicy",
    "InitiativePolicy",
    "InitiativeReservation",
    "InitiativeStatus",
    "ObservationReason",
    "ObservedEvent",
    "OutcomeKind",
    "OutcomeRecord",
    "OutcomeReason",
    "ReservationKind",
    "ReservationReason",
]
