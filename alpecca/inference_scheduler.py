"""Deterministic, dependency-free scheduling for inference work."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum, IntEnum
import math
from threading import RLock
import time
from types import MappingProxyType
from typing import Any, Callable, Deque, Generic, Mapping, TypeVar


T = TypeVar("T")


class PriorityLane(IntEnum):
    """Inference lanes ordered from most to least urgent."""

    P0_DIRECT_CONVERSATION = 0
    P1_INTERACTIVE = 1
    P2_BACKGROUND = 2
    P3_REFLECTION = 3
    P4_MAINTENANCE = 4


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class CancellationMetadata:
    reason: str
    requested_by: str
    requested_at: float


@dataclass(frozen=True, slots=True)
class InterruptionMetadata:
    reason: str
    requested_by: str
    requested_at: float
    preempting_task_id: str | None = None
    preempting_lane: PriorityLane | None = None


@dataclass(frozen=True, slots=True)
class TaskSnapshot(Generic[T]):
    task_id: str
    lane: PriorityLane
    payload: T
    source: str
    state: TaskState
    submitted_at: float
    started_at: float | None
    finished_at: float | None
    coalesce_key: str | None
    coalesced_count: int
    bypass_count: int
    metadata: Mapping[str, Any]
    cancellation: CancellationMetadata | None
    interruption: InterruptionMetadata | None


@dataclass(frozen=True, slots=True)
class AdmissionResult(Generic[T]):
    accepted: bool
    task: TaskSnapshot[T] | None
    reason: str | None = None
    coalesced: bool = False
    interruption_requested_for: str | None = None


@dataclass(frozen=True, slots=True)
class SchedulerStats:
    queued: int
    running_task_id: str | None
    accepted: int
    rejected: int
    coalesced: int
    completed: int
    cancelled: int
    interrupted: int


@dataclass(slots=True)
class _TaskEntry(Generic[T]):
    task_id: str
    lane: PriorityLane
    payload: T
    source: str
    state: TaskState
    submitted_at: float
    sequence: int
    coalesce_key: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    started_at: float | None = None
    finished_at: float | None = None
    coalesced_count: int = 0
    bypass_count: int = 0
    cancellation: CancellationMetadata | None = None
    interruption: InterruptionMetadata | None = None


class InferenceScheduler(Generic[T]):
    """A bounded priority scheduler with cooperative interruption metadata.

    The scheduler does not execute work. Callers submit tasks, dispatch one task,
    and then mark that task complete, cancelled, or interrupted.
    """

    def __init__(
        self,
        *,
        max_queued: int = 128,
        max_per_lane: int = 64,
        starvation_after: int = 8,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_queued <= 0:
            raise ValueError("max_queued must be positive")
        if max_per_lane <= 0:
            raise ValueError("max_per_lane must be positive")
        if starvation_after <= 0:
            raise ValueError("starvation_after must be positive")
        self._max_queued = max_queued
        self._max_per_lane = max_per_lane
        self._starvation_after = starvation_after
        self._clock = clock
        self._queues: dict[PriorityLane, Deque[_TaskEntry[T]]] = {
            lane: deque() for lane in PriorityLane
        }
        self._tasks: dict[str, _TaskEntry[T]] = {}
        self._coalesced: dict[tuple[PriorityLane, str], _TaskEntry[T]] = {}
        self._running: _TaskEntry[T] | None = None
        self._sequence = 0
        self._counts = {
            "accepted": 0,
            "rejected": 0,
            "coalesced": 0,
            "completed": 0,
            "cancelled": 0,
            "interrupted": 0,
        }
        self._lock = RLock()

    def submit(
        self,
        payload: T,
        lane: PriorityLane,
        *,
        source: str,
        coalesce_key: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AdmissionResult[T]:
        lane = self._coerce_lane(lane)
        source = self._required_text(source, "source")
        if coalesce_key is not None:
            coalesce_key = self._required_text(coalesce_key, "coalesce_key")
        now = self._now()
        copied_metadata = dict(metadata or {})

        with self._lock:
            if coalesce_key is not None:
                existing = self._coalesced.get((lane, coalesce_key))
                if existing is not None and existing.state is TaskState.QUEUED:
                    existing.payload = payload
                    existing.source = source
                    existing.metadata = copied_metadata
                    existing.submitted_at = now
                    existing.coalesced_count += 1
                    self._counts["coalesced"] += 1
                    return AdmissionResult(
                        accepted=True,
                        task=self._snapshot(existing),
                        coalesced=True,
                    )

            if self.queued_count >= self._max_queued:
                self._counts["rejected"] += 1
                return AdmissionResult(False, None, "queue_capacity")
            if len(self._queues[lane]) >= self._max_per_lane:
                self._counts["rejected"] += 1
                return AdmissionResult(False, None, "lane_capacity")

            self._sequence += 1
            entry = _TaskEntry(
                task_id=f"task-{self._sequence:06d}",
                lane=lane,
                payload=payload,
                source=source,
                state=TaskState.QUEUED,
                submitted_at=now,
                sequence=self._sequence,
                coalesce_key=coalesce_key,
                metadata=copied_metadata,
            )
            self._queues[lane].append(entry)
            self._tasks[entry.task_id] = entry
            if coalesce_key is not None:
                self._coalesced[(lane, coalesce_key)] = entry
            self._counts["accepted"] += 1

            interrupted_task_id = None
            if self._running is not None and lane < self._running.lane:
                interrupted_task_id = self._running.task_id
                self._running.interruption = InterruptionMetadata(
                    reason="higher_priority_task_queued",
                    requested_by="inference_scheduler",
                    requested_at=now,
                    preempting_task_id=entry.task_id,
                    preempting_lane=lane,
                )
            return AdmissionResult(
                accepted=True,
                task=self._snapshot(entry),
                interruption_requested_for=interrupted_task_id,
            )

    def dispatch_next(self) -> TaskSnapshot[T] | None:
        with self._lock:
            if self._running is not None:
                return None
            heads = [queue[0] for queue in self._queues.values() if queue]
            if not heads:
                return None

            starved = [
                entry
                for entry in heads
                if entry.bypass_count >= self._starvation_after
            ]
            if starved:
                selected = min(
                    starved,
                    key=lambda entry: (
                        -entry.bypass_count,
                        entry.submitted_at,
                        entry.sequence,
                        int(entry.lane),
                    ),
                )
            else:
                selected = min(
                    heads, key=lambda entry: (int(entry.lane), entry.sequence)
                )

            for entry in heads:
                if entry is not selected:
                    entry.bypass_count += 1
            self._queues[selected.lane].popleft()
            self._remove_coalesce_index(selected)
            selected.state = TaskState.RUNNING
            selected.started_at = self._now()
            self._running = selected
            return self._snapshot(selected)

    def complete(self, task_id: str) -> TaskSnapshot[T]:
        with self._lock:
            entry = self._require_running(task_id)
            entry.state = TaskState.COMPLETED
            entry.finished_at = self._now()
            self._running = None
            self._counts["completed"] += 1
            return self._snapshot(entry)

    def cancel(
        self,
        task_id: str,
        *,
        reason: str,
        requested_by: str,
    ) -> TaskSnapshot[T]:
        reason = self._required_text(reason, "reason")
        requested_by = self._required_text(requested_by, "requested_by")
        with self._lock:
            entry = self._require_active(task_id)
            if entry.state is TaskState.QUEUED:
                self._queues[entry.lane].remove(entry)
                self._remove_coalesce_index(entry)
            else:
                self._running = None
            now = self._now()
            entry.state = TaskState.CANCELLED
            entry.finished_at = now
            entry.cancellation = CancellationMetadata(reason, requested_by, now)
            self._counts["cancelled"] += 1
            return self._snapshot(entry)

    def interrupt_running(
        self,
        *,
        reason: str,
        requested_by: str,
    ) -> TaskSnapshot[T]:
        reason = self._required_text(reason, "reason")
        requested_by = self._required_text(requested_by, "requested_by")
        with self._lock:
            if self._running is None:
                raise RuntimeError("no task is running")
            entry = self._running
            now = self._now()
            previous = entry.interruption
            entry.interruption = InterruptionMetadata(
                reason=reason,
                requested_by=requested_by,
                requested_at=now,
                preempting_task_id=(previous.preempting_task_id if previous else None),
                preempting_lane=(previous.preempting_lane if previous else None),
            )
            entry.state = TaskState.INTERRUPTED
            entry.finished_at = now
            self._running = None
            self._counts["interrupted"] += 1
            return self._snapshot(entry)

    def snapshot(self, task_id: str) -> TaskSnapshot[T]:
        with self._lock:
            try:
                return self._snapshot(self._tasks[task_id])
            except KeyError as exc:
                raise KeyError(f"unknown task_id: {task_id}") from exc

    def pending(self) -> tuple[TaskSnapshot[T], ...]:
        with self._lock:
            return tuple(
                self._snapshot(entry)
                for lane in PriorityLane
                for entry in self._queues[lane]
            )

    @property
    def queued_count(self) -> int:
        with self._lock:
            return sum(len(queue) for queue in self._queues.values())

    def stats(self) -> SchedulerStats:
        with self._lock:
            return SchedulerStats(
                queued=self.queued_count,
                running_task_id=self._running.task_id if self._running else None,
                accepted=self._counts["accepted"],
                rejected=self._counts["rejected"],
                coalesced=self._counts["coalesced"],
                completed=self._counts["completed"],
                cancelled=self._counts["cancelled"],
                interrupted=self._counts["interrupted"],
            )

    def _require_active(self, task_id: str) -> _TaskEntry[T]:
        try:
            entry = self._tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"unknown task_id: {task_id}") from exc
        if entry.state not in (TaskState.QUEUED, TaskState.RUNNING):
            raise ValueError(f"task is not active: {task_id}")
        return entry

    def _require_running(self, task_id: str) -> _TaskEntry[T]:
        if self._running is None or self._running.task_id != task_id:
            raise ValueError(f"task is not running: {task_id}")
        return self._running

    def _remove_coalesce_index(self, entry: _TaskEntry[T]) -> None:
        if entry.coalesce_key is not None:
            self._coalesced.pop((entry.lane, entry.coalesce_key), None)

    @staticmethod
    def _snapshot(entry: _TaskEntry[T]) -> TaskSnapshot[T]:
        return TaskSnapshot(
            task_id=entry.task_id,
            lane=entry.lane,
            payload=entry.payload,
            source=entry.source,
            state=entry.state,
            submitted_at=entry.submitted_at,
            started_at=entry.started_at,
            finished_at=entry.finished_at,
            coalesce_key=entry.coalesce_key,
            coalesced_count=entry.coalesced_count,
            bypass_count=entry.bypass_count,
            metadata=MappingProxyType(dict(entry.metadata)),
            cancellation=entry.cancellation,
            interruption=entry.interruption,
        )

    def _now(self) -> float:
        value = float(self._clock())
        if not math.isfinite(value) or value < 0:
            raise ValueError("clock must return a finite, non-negative value")
        return value

    @staticmethod
    def _coerce_lane(lane: PriorityLane) -> PriorityLane:
        try:
            return PriorityLane(lane)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid priority lane: {lane!r}") from exc

    @staticmethod
    def _required_text(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be non-empty")
        return value.strip()
