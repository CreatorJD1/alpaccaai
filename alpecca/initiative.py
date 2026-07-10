"""Pure per-scope initiative pacing for Phase 5.

The budget has no I/O and performs no action.  Callers present a candidate;
an allowed decision atomically reserves its cooldown, dedupe, and window slot.
All time comes from the injected monotonic clock, which makes the policy fully
deterministic in tests and independent from wall-clock changes.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal


DecisionReason = Literal[
    "allowed",
    "user_active",
    "activity_quiet_period",
    "low_relevance",
    "duplicate",
    "cooldown",
    "window_cap",
]

_MAX_SCOPE_LENGTH = 160
_MAX_DEDUPE_KEY_LENGTH = 256


@dataclass(frozen=True, slots=True)
class InitiativePolicy:
    """Deterministic limits shared by every independently budgeted scope."""

    min_relevance: float = 0.6
    cooldown_seconds: float = 60.0
    window_seconds: float = 3600.0
    max_per_window: int = 3
    dedupe_seconds: float = 3600.0
    activity_quiet_seconds: float = 30.0
    ignored_backoff_factor: float = 2.0
    max_ignored_backoff_seconds: float = 3600.0

    def __post_init__(self) -> None:
        numeric = {
            "min_relevance": self.min_relevance,
            "cooldown_seconds": self.cooldown_seconds,
            "window_seconds": self.window_seconds,
            "dedupe_seconds": self.dedupe_seconds,
            "activity_quiet_seconds": self.activity_quiet_seconds,
            "ignored_backoff_factor": self.ignored_backoff_factor,
            "max_ignored_backoff_seconds": self.max_ignored_backoff_seconds,
        }
        for name, value in numeric.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not 0.0 <= float(self.min_relevance) <= 1.0:
            raise ValueError("min_relevance must be between 0 and 1")
        if float(self.cooldown_seconds) < 0.0:
            raise ValueError("cooldown_seconds cannot be negative")
        if float(self.window_seconds) <= 0.0:
            raise ValueError("window_seconds must be positive")
        if float(self.dedupe_seconds) <= 0.0:
            raise ValueError("dedupe_seconds must be positive")
        if float(self.activity_quiet_seconds) < 0.0:
            raise ValueError("activity_quiet_seconds cannot be negative")
        if float(self.ignored_backoff_factor) < 1.0:
            raise ValueError("ignored_backoff_factor must be at least 1")
        if float(self.max_ignored_backoff_seconds) < float(self.cooldown_seconds):
            raise ValueError(
                "max_ignored_backoff_seconds cannot be shorter than cooldown_seconds"
            )
        if (
            isinstance(self.max_per_window, bool)
            or not isinstance(self.max_per_window, int)
            or self.max_per_window <= 0
        ):
            raise ValueError("max_per_window must be a positive integer")


@dataclass(frozen=True, slots=True)
class InitiativeDecision:
    """One explainable allow/defer result."""

    decision: Literal["allow", "defer"]
    reason: DecisionReason
    scope: str
    dedupe_key: str
    relevance: float
    decided_at: float
    retry_at: float | None
    retry_after: float | None
    window_used: int
    window_cap: int
    ignored_streak: int

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


@dataclass(slots=True)
class _ScopeBudget:
    allowed_at: list[float] = field(default_factory=list)
    dedupe_at: dict[str, float] = field(default_factory=dict)
    last_allowed_at: float | None = None
    last_user_activity_at: float | None = None
    ignored_streak: int = 0
    last_ignored_at: float | None = None
    pending_outreach_key: str | None = None


class InitiativeBudget:
    """In-memory, per-scope limiter for autonomous initiative candidates."""

    def __init__(
        self,
        policy: InitiativePolicy | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.policy = policy or InitiativePolicy()
        self._clock = clock
        self._scopes: dict[str, _ScopeBudget] = {}
        self._last_now: float | None = None

    @staticmethod
    def _clean_identifier(value: str, *, name: str, maximum: int) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string")
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{name} is required")
        if len(cleaned) > maximum:
            raise ValueError(f"{name} exceeds {maximum} characters")
        if any(ord(char) < 32 for char in cleaned):
            raise ValueError(f"{name} contains control characters")
        return cleaned

    @classmethod
    def _scope(cls, value: str) -> str:
        return cls._clean_identifier(
            value, name="scope", maximum=_MAX_SCOPE_LENGTH
        )

    @classmethod
    def _dedupe_key(cls, value: str) -> str:
        return cls._clean_identifier(
            value, name="dedupe_key", maximum=_MAX_DEDUPE_KEY_LENGTH
        )

    @staticmethod
    def _relevance(value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("relevance must be numeric")
        relevance = float(value)
        if not math.isfinite(relevance) or not 0.0 <= relevance <= 1.0:
            raise ValueError("relevance must be finite and between 0 and 1")
        return relevance

    def _now(self) -> float:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("clock returned a non-finite value")
        if self._last_now is not None and now < self._last_now:
            raise ValueError("clock moved backwards")
        self._last_now = now
        return now

    def _state(self, scope: str) -> _ScopeBudget:
        return self._scopes.setdefault(scope, _ScopeBudget())

    def _prune(self, state: _ScopeBudget, now: float) -> None:
        window_cutoff = now - float(self.policy.window_seconds)
        state.allowed_at[:] = [stamp for stamp in state.allowed_at if stamp > window_cutoff]
        dedupe_cutoff = now - float(self.policy.dedupe_seconds)
        stale = [key for key, stamp in state.dedupe_at.items() if stamp <= dedupe_cutoff]
        for key in stale:
            del state.dedupe_at[key]

    def _effective_cooldown(self, state: _ScopeBudget, outreach: bool) -> float:
        cooldown = float(self.policy.cooldown_seconds)
        if not outreach or state.ignored_streak <= 0 or cooldown <= 0.0:
            return cooldown
        maximum = float(self.policy.max_ignored_backoff_seconds)
        factor = float(self.policy.ignored_backoff_factor)
        try:
            return min(maximum, cooldown * (factor ** state.ignored_streak))
        except OverflowError:
            return maximum

    def _decision(
        self,
        *,
        allowed: bool,
        reason: DecisionReason,
        scope: str,
        dedupe_key: str,
        relevance: float,
        now: float,
        state: _ScopeBudget,
        retry_at: float | None = None,
    ) -> InitiativeDecision:
        retry_after = None if retry_at is None else max(0.0, retry_at - now)
        return InitiativeDecision(
            decision="allow" if allowed else "defer",
            reason=reason,
            scope=scope,
            dedupe_key=dedupe_key,
            relevance=relevance,
            decided_at=now,
            retry_at=retry_at,
            retry_after=retry_after,
            window_used=len(state.allowed_at),
            window_cap=self.policy.max_per_window,
            ignored_streak=state.ignored_streak,
        )

    def decide(
        self,
        *,
        scope: str,
        relevance: float,
        dedupe_key: str,
        user_active: bool = False,
        outreach: bool = True,
    ) -> InitiativeDecision:
        """Decide and reserve one candidate, or return a grounded defer reason.

        ``user_active`` means the caller observed explicit user activity on this
        attempt.  That attempt is deferred, starts the quiet period, and resets
        ignored-outreach backoff for the scope.  ``outreach`` marks candidates
        that expect a response and are therefore eligible for ignored backoff.
        """
        clean_scope = self._scope(scope)
        clean_key = self._dedupe_key(dedupe_key)
        clean_relevance = self._relevance(relevance)
        if not isinstance(user_active, bool):
            raise TypeError("user_active must be a bool")
        if not isinstance(outreach, bool):
            raise TypeError("outreach must be a bool")

        now = self._now()
        state = self._state(clean_scope)
        self._prune(state, now)

        if user_active:
            self._record_user_activity(state, now)
            retry_at = now + float(self.policy.activity_quiet_seconds)
            return self._decision(
                allowed=False,
                reason="user_active",
                scope=clean_scope,
                dedupe_key=clean_key,
                relevance=clean_relevance,
                now=now,
                state=state,
                retry_at=retry_at,
            )

        if state.last_user_activity_at is not None:
            retry_at = state.last_user_activity_at + float(
                self.policy.activity_quiet_seconds
            )
            if now < retry_at:
                return self._decision(
                    allowed=False,
                    reason="activity_quiet_period",
                    scope=clean_scope,
                    dedupe_key=clean_key,
                    relevance=clean_relevance,
                    now=now,
                    state=state,
                    retry_at=retry_at,
                )

        if clean_relevance < float(self.policy.min_relevance):
            return self._decision(
                allowed=False,
                reason="low_relevance",
                scope=clean_scope,
                dedupe_key=clean_key,
                relevance=clean_relevance,
                now=now,
                state=state,
            )

        duplicate_at = state.dedupe_at.get(clean_key)
        if duplicate_at is not None:
            return self._decision(
                allowed=False,
                reason="duplicate",
                scope=clean_scope,
                dedupe_key=clean_key,
                relevance=clean_relevance,
                now=now,
                state=state,
                retry_at=duplicate_at + float(self.policy.dedupe_seconds),
            )

        cooldown = self._effective_cooldown(state, outreach)
        if state.last_allowed_at is not None:
            anchor = state.last_allowed_at
            if outreach and state.last_ignored_at is not None:
                anchor = max(anchor, state.last_ignored_at)
            retry_at = anchor + cooldown
            if now < retry_at:
                return self._decision(
                    allowed=False,
                    reason="cooldown",
                    scope=clean_scope,
                    dedupe_key=clean_key,
                    relevance=clean_relevance,
                    now=now,
                    state=state,
                    retry_at=retry_at,
                )

        if len(state.allowed_at) >= self.policy.max_per_window:
            retry_at = state.allowed_at[0] + float(self.policy.window_seconds)
            return self._decision(
                allowed=False,
                reason="window_cap",
                scope=clean_scope,
                dedupe_key=clean_key,
                relevance=clean_relevance,
                now=now,
                state=state,
                retry_at=retry_at,
            )

        state.allowed_at.append(now)
        state.last_allowed_at = now
        state.dedupe_at[clean_key] = now
        if outreach:
            state.pending_outreach_key = clean_key
        return self._decision(
            allowed=True,
            reason="allowed",
            scope=clean_scope,
            dedupe_key=clean_key,
            relevance=clean_relevance,
            now=now,
            state=state,
        )

    @staticmethod
    def _record_user_activity(state: _ScopeBudget, now: float) -> None:
        state.last_user_activity_at = now
        state.ignored_streak = 0
        state.last_ignored_at = None
        state.pending_outreach_key = None

    def note_user_activity(self, scope: str) -> None:
        """Record explicit activity without evaluating an initiative candidate."""
        clean_scope = self._scope(scope)
        self._record_user_activity(self._state(clean_scope), self._now())

    def mark_ignored(self, *, scope: str, dedupe_key: str) -> bool:
        """Back off once for the matching unanswered outreach.

        Returns ``False`` for an unknown, superseded, or already-recorded key,
        making repeated delivery/outcome reports idempotent.
        """
        clean_scope = self._scope(scope)
        clean_key = self._dedupe_key(dedupe_key)
        now = self._now()
        state = self._scopes.get(clean_scope)
        if state is None or state.pending_outreach_key != clean_key:
            return False
        state.pending_outreach_key = None
        state.ignored_streak += 1
        state.last_ignored_at = now
        return True

    def snapshot(self, scope: str) -> dict[str, object]:
        """Return bounded diagnostic state for tests and future observability."""
        clean_scope = self._scope(scope)
        now = self._now()
        state = self._state(clean_scope)
        self._prune(state, now)
        return {
            "scope": clean_scope,
            "window_used": len(state.allowed_at),
            "window_cap": self.policy.max_per_window,
            "dedupe_count": len(state.dedupe_at),
            "last_allowed_at": state.last_allowed_at,
            "last_user_activity_at": state.last_user_activity_at,
            "ignored_streak": state.ignored_streak,
            "pending_outreach_key": state.pending_outreach_key,
        }


__all__ = [
    "DecisionReason",
    "InitiativeBudget",
    "InitiativeDecision",
    "InitiativePolicy",
]
