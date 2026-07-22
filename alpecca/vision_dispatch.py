"""Event-driven, serialized dispatch for vision processors.

Raw frames live only in the bounded pending handoff or the active processor
call. Scheduler history and public task snapshots contain descriptors only.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from threading import RLock
import time
from types import MappingProxyType
from typing import Callable, Generic, Mapping, TypeVar

from alpecca.inference_scheduler import (
    InferenceScheduler,
    PriorityLane,
    TaskSnapshot,
    TaskState,
)


R = TypeVar("R")


class VisionEventKind(str, Enum):
    DIRECT_UPLOAD = "direct_upload"
    AMBIENT_FRAME = "ambient_frame"


@dataclass(frozen=True, slots=True)
class VisionEvent:
    """A persistable frame descriptor that intentionally excludes pixels."""

    event_id: str
    kind: VisionEventKind
    source: str
    stream_id: str | None
    content_type: str
    byte_length: int
    sha256: str
    metadata: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class VisionProcessorInput:
    """Ephemeral input passed to one callable processor."""

    task_id: str
    event: VisionEvent
    frame_bytes: bytes


@dataclass(frozen=True, slots=True)
class VisionSubmission:
    accepted: bool
    task: TaskSnapshot[VisionEvent] | None
    reason: str | None = None
    coalesced: bool = False
    duplicate_of: str | None = None
    displaced: TaskSnapshot[VisionEvent] | None = None


@dataclass(frozen=True, slots=True)
class VisionDispatchResult(Generic[R]):
    task: TaskSnapshot[VisionEvent]
    value: R | None
    succeeded: bool
    error_type: str | None = None
    error_message: str | None = None


class VisionDispatcher:
    """A bounded, single-flight lane for direct and ambient vision events."""

    def __init__(
        self,
        *,
        max_queued: int = 8,
        max_frame_bytes: int = 10 * 1024 * 1024,
        dedupe_window: int = 64,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_queued <= 0:
            raise ValueError("max_queued must be positive")
        if max_frame_bytes <= 0:
            raise ValueError("max_frame_bytes must be positive")
        if dedupe_window <= 0:
            raise ValueError("dedupe_window must be positive")
        self._max_queued = max_queued
        self._max_frame_bytes = max_frame_bytes
        self._dedupe_window = dedupe_window
        self._scheduler = InferenceScheduler[VisionEvent](
            max_queued=max_queued,
            max_per_lane=max_queued,
            starvation_after=2**63 - 1,
            clock=clock,
        )
        self._pending_frames: dict[str, bytes] = {}
        self._dedupe: dict[tuple[str, str, str], str] = {}
        self._dedupe_order: deque[
            tuple[str, tuple[tuple[str, str, str], ...]]
        ] = deque()
        self._lock = RLock()

    def submit_direct_upload(
        self,
        frame: bytes | bytearray | memoryview,
        *,
        source: str,
        event_id: str,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> VisionSubmission:
        event, frame_bytes = self._prepare_event(
            frame,
            kind=VisionEventKind.DIRECT_UPLOAD,
            source=source,
            event_id=event_id,
            stream_id=None,
            content_type=content_type,
            metadata=metadata,
        )
        identities = ((event.source, "direct_event_id", event.event_id),)
        with self._lock:
            duplicate_of = next(
                (self._dedupe[item] for item in identities if item in self._dedupe),
                None,
            )
            if duplicate_of is not None:
                return VisionSubmission(
                    False,
                    None,
                    reason="duplicate_frame_event",
                    duplicate_of=duplicate_of,
                )
            displaced = None
            if self._scheduler.queued_count >= self._max_queued:
                displaced = self._displace_oldest_ambient()
            admission = self._scheduler.submit(
                event,
                PriorityLane.P0_DIRECT_CONVERSATION,
                source=event.source,
                metadata=self._scheduler_metadata(event),
            )
            if not admission.accepted or admission.task is None:
                return VisionSubmission(
                    False,
                    None,
                    reason=admission.reason,
                    displaced=displaced,
                )
            self._pending_frames[admission.task.task_id] = frame_bytes
            self._remember_dedupe(admission.task.task_id, identities)
            return VisionSubmission(
                True,
                admission.task,
                displaced=displaced,
            )

    def submit_ambient_frame(
        self,
        frame: bytes | bytearray | memoryview,
        *,
        source: str,
        event_id: str,
        stream_id: str,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> VisionSubmission:
        event, frame_bytes = self._prepare_event(
            frame,
            kind=VisionEventKind.AMBIENT_FRAME,
            source=source,
            event_id=event_id,
            stream_id=stream_id,
            content_type=content_type,
            metadata=metadata,
        )
        identities = self._dedupe_identities(event)
        with self._lock:
            duplicate_of = next(
                (self._dedupe[item] for item in identities if item in self._dedupe),
                None,
            )
            if duplicate_of is not None:
                return VisionSubmission(
                    False,
                    None,
                    reason="duplicate_frame_event",
                    duplicate_of=duplicate_of,
                )

            admission = self._scheduler.submit(
                event,
                PriorityLane.P2_BACKGROUND,
                source=event.source,
                coalesce_key=f"ambient:{event.source}:{event.stream_id}",
                metadata=self._scheduler_metadata(event),
            )
            if not admission.accepted or admission.task is None:
                return VisionSubmission(False, None, reason=admission.reason)
            self._pending_frames[admission.task.task_id] = frame_bytes
            self._remember_dedupe(admission.task.task_id, identities)
            return VisionSubmission(
                True,
                admission.task,
                coalesced=admission.coalesced,
            )

    def process_next(
        self,
        processor: Callable[[VisionProcessorInput], R],
    ) -> VisionDispatchResult[R] | None:
        if not callable(processor):
            raise TypeError("processor must be callable")
        with self._lock:
            task = self._scheduler.dispatch_next()
            if task is None:
                return None
            frame_bytes = self._pending_frames.pop(task.task_id, None)
            if frame_bytes is None:
                failed = self._scheduler.interrupt_running(
                    reason="frame_handoff_missing",
                    requested_by="vision_dispatch",
                )
                return VisionDispatchResult(
                    task=failed,
                    value=None,
                    succeeded=False,
                    error_type="FrameHandoffMissing",
                    error_message="pending frame was unavailable",
                )

        processor_input = VisionProcessorInput(
            task_id=task.task_id,
            event=task.payload,
            frame_bytes=frame_bytes,
        )
        try:
            value = processor(processor_input)
        except Exception as exc:
            with self._lock:
                current = self._scheduler.snapshot(task.task_id)
                if current.state is TaskState.RUNNING:
                    current = self._scheduler.interrupt_running(
                        reason="processor_failed",
                        requested_by="vision_dispatch",
                    )
            return VisionDispatchResult(
                task=current,
                value=None,
                succeeded=False,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        finally:
            del processor_input
            del frame_bytes

        with self._lock:
            current = self._scheduler.snapshot(task.task_id)
            if current.state is TaskState.RUNNING:
                current = self._scheduler.complete(task.task_id)
                return VisionDispatchResult(current, value, True)
            return VisionDispatchResult(current, None, False)

    def cancel(
        self,
        task_id: str,
        *,
        reason: str,
        requested_by: str,
    ) -> TaskSnapshot[VisionEvent]:
        with self._lock:
            cancelled = self._scheduler.cancel(
                task_id,
                reason=reason,
                requested_by=requested_by,
            )
            self._pending_frames.pop(task_id, None)
            self._forget_dedupe(task_id)
            return cancelled

    def snapshot(self, task_id: str) -> TaskSnapshot[VisionEvent]:
        return self._scheduler.snapshot(task_id)

    def pending(self) -> tuple[TaskSnapshot[VisionEvent], ...]:
        return self._scheduler.pending()

    @property
    def queued_count(self) -> int:
        return self._scheduler.queued_count

    @property
    def retained_frame_count(self) -> int:
        with self._lock:
            return len(self._pending_frames)

    def _displace_oldest_ambient(self) -> TaskSnapshot[VisionEvent] | None:
        ambient = next(
            (
                task
                for task in self._scheduler.pending()
                if task.payload.kind is VisionEventKind.AMBIENT_FRAME
            ),
            None,
        )
        if ambient is None:
            return None
        cancelled = self._scheduler.cancel(
            ambient.task_id,
            reason="displaced_by_direct_upload",
            requested_by="vision_dispatch",
        )
        self._pending_frames.pop(ambient.task_id, None)
        self._forget_dedupe(ambient.task_id)
        return cancelled

    def _prepare_event(
        self,
        frame: bytes | bytearray | memoryview,
        *,
        kind: VisionEventKind,
        source: str,
        event_id: str,
        stream_id: str | None,
        content_type: str,
        metadata: Mapping[str, str] | None,
    ) -> tuple[VisionEvent, bytes]:
        source = self._required_text(source, "source")
        event_id = self._required_text(event_id, "event_id")
        content_type = self._required_text(content_type, "content_type").lower()
        if stream_id is not None:
            stream_id = self._required_text(stream_id, "stream_id")
        if not isinstance(frame, (bytes, bytearray, memoryview)):
            raise TypeError("frame must be bytes-like")
        byte_length = memoryview(frame).nbytes
        if byte_length == 0:
            raise ValueError("frame must not be empty")
        if byte_length > self._max_frame_bytes:
            raise ValueError("frame exceeds max_frame_bytes")
        copied_metadata = self._metadata(metadata)
        frame_bytes = bytes(frame)
        if len(frame_bytes) != byte_length:
            raise ValueError("frame byte length changed during normalization")
        event = VisionEvent(
            event_id=event_id,
            kind=kind,
            source=source,
            stream_id=stream_id,
            content_type=content_type,
            byte_length=byte_length,
            sha256=sha256(frame_bytes).hexdigest(),
            metadata=MappingProxyType(copied_metadata),
        )
        return event, frame_bytes

    @staticmethod
    def _scheduler_metadata(event: VisionEvent) -> Mapping[str, str]:
        return {
            "event_id": event.event_id,
            "event_kind": event.kind.value,
            "content_type": event.content_type,
            "sha256": event.sha256,
        }

    @staticmethod
    def _dedupe_identities(
        event: VisionEvent,
    ) -> tuple[tuple[str, str, str], ...]:
        stream = f"{event.source}:{event.stream_id}"
        return (
            (stream, "event_id", event.event_id),
            (stream, "sha256", event.sha256),
        )

    def _remember_dedupe(
        self,
        task_id: str,
        identities: tuple[tuple[str, str, str], ...],
    ) -> None:
        for identity in identities:
            self._dedupe[identity] = task_id
        self._dedupe_order.append((task_id, identities))
        while len(self._dedupe_order) > self._dedupe_window:
            old_task_id, old_identities = self._dedupe_order.popleft()
            for identity in old_identities:
                if self._dedupe.get(identity) == old_task_id:
                    self._dedupe.pop(identity, None)

    def _forget_dedupe(self, task_id: str) -> None:
        retained = deque()
        for remembered_task_id, identities in self._dedupe_order:
            if remembered_task_id == task_id:
                for identity in identities:
                    if self._dedupe.get(identity) == task_id:
                        self._dedupe.pop(identity, None)
            else:
                retained.append((remembered_task_id, identities))
        self._dedupe_order = retained

    @staticmethod
    def _metadata(metadata: Mapping[str, str] | None) -> dict[str, str]:
        copied: dict[str, str] = {}
        for key, value in (metadata or {}).items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("metadata keys must be non-empty strings")
            if not isinstance(value, str):
                raise TypeError("metadata values must be strings")
            copied[key.strip()] = value
        return copied

    @staticmethod
    def _required_text(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be non-empty")
        return value.strip()
