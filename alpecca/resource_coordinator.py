"""Thread-safe, in-memory single-flight coordinator for optional work.

This module deliberately owns no threads and starts no work itself. Callers
provide the worker function or drive a lease manually, checking its cancellation
event at their own safe interruption points.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Literal


OptionalCategory = Literal["reflection", "backfill", "routine"]
JobState = Literal["rejected", "finished", "cancelled", "error", "stale"]

OPTIONAL_CATEGORIES = frozenset({"reflection", "backfill", "routine"})
MAX_TELEMETRY = 200
MAX_DETAIL_CHARS = 240


@dataclass(frozen=True, slots=True)
class OptionalWorkLease:
    """One accepted optional-work slot and its cooperative cancellation signal."""

    job_id: int
    category: OptionalCategory
    cancellation_event: threading.Event
    _owner: object

    @property
    def cancelled(self) -> bool:
        return self.cancellation_event.is_set()

    def allow_work(self) -> bool:
        return not self.cancelled


@dataclass(frozen=True, slots=True)
class StartDecision:
    accepted: bool
    reason: str
    lease: OptionalWorkLease | None = None


@dataclass(frozen=True, slots=True)
class WorkOutcome:
    state: JobState
    job_id: int | None
    value: Any = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class CoordinatorTelemetry:
    sequence: int
    timestamp: float
    event: Literal["start", "finish", "cancel", "error", "rejected"]
    job_id: int | None
    category: str
    detail: str = ""


def _detail(value: object) -> str:
    return " ".join(str(value or "").strip().split())[:MAX_DETAIL_CHARS]


class ResourceCoordinator:
    """Reject optional work that would contend with foreground work or itself."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._owner = object()
        self._next_job_id = 1
        self._next_sequence = 1
        self._active: OptionalWorkLease | None = None
        self._chat_active = False
        self._tts_active = False
        self._telemetry: list[CoordinatorTelemetry] = []

    def _record(
        self,
        event: Literal["start", "finish", "cancel", "error", "rejected"],
        *,
        lease: OptionalWorkLease | None = None,
        category: str = "",
        detail: object = "",
    ) -> None:
        item = CoordinatorTelemetry(
            sequence=self._next_sequence,
            timestamp=float(self._clock()),
            event=event,
            job_id=lease.job_id if lease is not None else None,
            category=lease.category if lease is not None else category,
            detail=_detail(detail),
        )
        self._next_sequence += 1
        self._telemetry.append(item)
        del self._telemetry[:-MAX_TELEMETRY]

    def set_foreground(self, *, chat_active: bool, tts_active: bool) -> None:
        """Set foreground pressure and request cancellation of active optional work."""

        with self._lock:
            self._chat_active = bool(chat_active)
            self._tts_active = bool(tts_active)
            if self._active is not None and (self._chat_active or self._tts_active):
                reason = "chat-active" if self._chat_active else "tts-active"
                self._cancel_locked(self._active, reason)

    def start(self, category: OptionalCategory) -> StartDecision:
        """Acquire the only optional-work slot, or return a non-starting reason."""

        if category not in OPTIONAL_CATEGORIES:
            raise ValueError(f"unknown optional category: {category!r}")
        with self._lock:
            if self._chat_active:
                self._record("rejected", category=category, detail="chat-active")
                return StartDecision(False, "chat-active")
            if self._tts_active:
                self._record("rejected", category=category, detail="tts-active")
                return StartDecision(False, "tts-active")
            if self._active is not None:
                self._record("rejected", category=category, detail="optional-work-active")
                return StartDecision(False, "optional-work-active")
            lease = OptionalWorkLease(
                job_id=self._next_job_id,
                category=category,
                cancellation_event=threading.Event(),
                _owner=self._owner,
            )
            self._next_job_id += 1
            self._active = lease
            self._record("start", lease=lease)
            return StartDecision(True, "", lease)

    def _is_active_locked(self, lease: OptionalWorkLease) -> bool:
        return lease._owner is self._owner and self._active is lease

    def _cancel_locked(self, lease: OptionalWorkLease, reason: object) -> bool:
        if not self._is_active_locked(lease) or lease.cancelled:
            return False
        lease.cancellation_event.set()
        self._record("cancel", lease=lease, detail=reason)
        return True

    def cancel(self, lease: OptionalWorkLease, reason: str = "cancelled") -> bool:
        """Request cancellation; the active lease remains reserved until acknowledged."""

        with self._lock:
            return self._cancel_locked(lease, reason)

    def finish(self, lease: OptionalWorkLease) -> WorkOutcome:
        """Acknowledge successful completion or a previously requested cancellation."""

        with self._lock:
            if not self._is_active_locked(lease):
                return WorkOutcome("stale", lease.job_id, reason="lease-not-active")
            self._active = None
            if lease.cancelled:
                return WorkOutcome("cancelled", lease.job_id, reason="cancellation-requested")
            self._record("finish", lease=lease)
            return WorkOutcome("finished", lease.job_id)

    def fail(self, lease: OptionalWorkLease, error: BaseException | str) -> WorkOutcome:
        """Acknowledge a worker failure, unless cancellation already won the race."""

        with self._lock:
            if not self._is_active_locked(lease):
                return WorkOutcome("stale", lease.job_id, reason="lease-not-active")
            self._active = None
            if lease.cancelled:
                return WorkOutcome("cancelled", lease.job_id, reason="cancellation-requested")
            detail = f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else error
            self._record("error", lease=lease, detail=detail)
            return WorkOutcome("error", lease.job_id, reason=_detail(detail))

    def run(
        self,
        category: OptionalCategory,
        worker: Callable[[OptionalWorkLease], Any],
    ) -> WorkOutcome:
        """Run a synchronous worker through the coordinator's lifecycle.

        The worker receives a lease and must periodically check
        ``lease.allow_work()`` or ``lease.cancellation_event`` to cooperate with
        cancellation. This wrapper never creates a thread or force-stops one.
        """

        decision = self.start(category)
        if not decision.accepted or decision.lease is None:
            return WorkOutcome("rejected", None, reason=decision.reason)
        lease = decision.lease
        try:
            value = worker(lease)
        except BaseException as exc:
            return self.fail(lease, exc)
        outcome = self.finish(lease)
        return WorkOutcome(outcome.state, outcome.job_id, value=value, reason=outcome.reason)

    def active(self) -> OptionalWorkLease | None:
        with self._lock:
            return self._active

    def telemetry(self) -> tuple[CoordinatorTelemetry, ...]:
        with self._lock:
            return tuple(self._telemetry)

    def snapshot(self) -> dict[str, object]:
        """Return a read-only operational view without exposing mutable internals."""

        with self._lock:
            return {
                "chat_active": self._chat_active,
                "tts_active": self._tts_active,
                "active_job_id": self._active.job_id if self._active else None,
                "active_category": self._active.category if self._active else "",
                "active_cancelled": self._active.cancelled if self._active else False,
                "telemetry_count": len(self._telemetry),
            }


__all__ = [
    "CoordinatorTelemetry",
    "JobState",
    "MAX_DETAIL_CHARS",
    "MAX_TELEMETRY",
    "OPTIONAL_CATEGORIES",
    "OptionalCategory",
    "OptionalWorkLease",
    "ResourceCoordinator",
    "StartDecision",
    "WorkOutcome",
]
