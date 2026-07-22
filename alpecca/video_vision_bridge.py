"""Serialized, source-neutral bridge for video vision descriptor events.

Raw frame bytes are accepted only by ``handoff_frame`` and exist in bridge code
only for one synchronous ``VisionProcessorInput`` callback. Bridge state,
timeline entries, snapshots, and status contain derived metadata only. The
bridge performs no acquisition, network access, or model inference itself.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from enum import Enum
from hashlib import sha256
import json
import math
import re
from threading import RLock
from types import MappingProxyType

from alpecca import video_api, video_companion, video_reactor, vision_dispatch


BRIDGE_SCHEMA = "alpecca.video-vision-bridge.v1"
SNAPSHOT_SCHEMA = "alpecca.video-vision-bridge.snapshot.v1"
STATUS_SCHEMA = "alpecca.video-vision-bridge.status.v1"
MAX_ID_CHARS = 256
MAX_CONTENT_TYPE_CHARS = 128
MAX_FRAME_BYTES = 10 * 1024 * 1024

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_CONTENT_TYPE_RE = re.compile(r"^image/[A-Za-z0-9.+-]{1,96}$")


class VideoVisionBridgeError(ValueError):
    """A bridge descriptor or state transition is invalid."""


class BridgePriority(str, Enum):
    P1_INTERACTIVE = "P1"
    P2_AMBIENT = "P2"


class FrameIntent(str, Enum):
    DIRECT_QUESTION = "direct_question"
    AMBIENT = "ambient"


@dataclass(frozen=True, slots=True)
class FrameRequest:
    event_id: str
    session_id: str
    source_id: str
    source_kind: video_api.SourceKind
    surface: video_api.Surface = video_api.Surface.HOUSE_HQ
    adapter_id: str | None = None
    media_timestamp: float = 0.0
    content_type: str = "image/jpeg"
    intent: FrameIntent = FrameIntent.AMBIENT
    question_id: str | None = None
    meaningful_hint: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        object.__setattr__(self, "session_id", _identifier(self.session_id, "session_id"))
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(self, "source_kind", _enum(video_api.SourceKind, self.source_kind, "source_kind"))
        object.__setattr__(self, "surface", _enum(video_api.Surface, self.surface, "surface"))
        if self.adapter_id is not None:
            object.__setattr__(self, "adapter_id", _identifier(self.adapter_id, "adapter_id"))
        object.__setattr__(
            self, "media_timestamp", _finite_number(self.media_timestamp, "media_timestamp")
        )
        if not isinstance(self.content_type, str):
            raise VideoVisionBridgeError("content_type must be text")
        content_type = self.content_type.strip().lower()
        if len(content_type) > MAX_CONTENT_TYPE_CHARS or _CONTENT_TYPE_RE.fullmatch(content_type) is None:
            raise VideoVisionBridgeError("content_type must identify bounded image media")
        object.__setattr__(self, "content_type", content_type)
        intent = _enum(FrameIntent, self.intent, "frame intent")
        object.__setattr__(self, "intent", intent)
        if intent is FrameIntent.DIRECT_QUESTION:
            if self.question_id is None:
                raise VideoVisionBridgeError("direct questions require question_id")
            object.__setattr__(self, "question_id", _identifier(self.question_id, "question_id"))
        elif self.question_id is not None:
            raise VideoVisionBridgeError("ambient frames must not claim a question_id")
        if type(self.meaningful_hint) is not bool:
            raise VideoVisionBridgeError("meaningful_hint must be boolean")

    @property
    def priority(self) -> BridgePriority:
        return (
            BridgePriority.P1_INTERACTIVE
            if self.intent is FrameIntent.DIRECT_QUESTION
            else BridgePriority.P2_AMBIENT
        )


@dataclass(frozen=True, slots=True)
class VisionObservation:
    event: video_api.VisualDescriptorEvent
    meaningful: bool
    novelty: video_reactor.Novelty
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event, video_api.VisualDescriptorEvent):
            raise VideoVisionBridgeError("event must be a VisualDescriptorEvent")
        if type(self.meaningful) is not bool:
            raise VideoVisionBridgeError("meaningful must be boolean")
        object.__setattr__(self, "novelty", _enum(video_reactor.Novelty, self.novelty, "novelty"))
        if self.fingerprint is not None:
            object.__setattr__(
                self, "fingerprint", _identifier(self.fingerprint, "fingerprint")
            )


@dataclass(frozen=True, slots=True)
class BridgeTimelineEvent:
    sequence: int
    event_id: str
    session_id: str
    source_id: str
    source_kind: str
    surface: str
    adapter_id: str | None
    start_seconds: float
    end_seconds: float
    descriptor: str
    fingerprint: str
    meaningful: bool
    novelty: str
    priority: str
    disposition: str
    defer_reason: str | None
    reaction_action: str
    compacted_duplicates: int = 0


@dataclass(frozen=True, slots=True)
class BridgeReceipt:
    sequence: int
    event_id: str
    priority: str
    disposition: str
    reason: str
    retained: bool
    compacted_into_event_id: str | None = None
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class BridgeOutcome:
    receipt: BridgeReceipt
    timeline_event: BridgeTimelineEvent | None
    reaction: video_reactor.ReactionDecision | None

    def as_dict(self) -> dict[str, object]:
        return {
            "receipt": asdict(self.receipt),
            "timeline_event": None if self.timeline_event is None else asdict(self.timeline_event),
            "reaction": (
                None
                if self.reaction is None
                else dict(self.reaction.observation_metadata())
            ),
        }


VisionHandoff = Callable[[vision_dispatch.VisionProcessorInput], VisionObservation]


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) > MAX_ID_CHARS or _ID_RE.fullmatch(value) is None:
        raise VideoVisionBridgeError(f"{name} must be a bounded opaque identifier")
    if "://" in value:
        raise VideoVisionBridgeError(f"{name} must not be a URL")
    return value


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VideoVisionBridgeError(f"{name} must be a finite non-negative number")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise VideoVisionBridgeError(f"{name} must be a finite non-negative number")
    return number


def _enum(enum_type: type[Enum], value: object, name: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        raise VideoVisionBridgeError(f"invalid {name}") from None


def _contains_bytes(value: object) -> bool:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return True
    if isinstance(value, Mapping):
        return any(_contains_bytes(key) or _contains_bytes(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_bytes(item) for item in value)
    return False


class VideoVisionBridge:
    """One serialized descriptor pipeline shared by House and adapters."""

    def __init__(self, companion: video_companion.VideoCompanionSession) -> None:
        if not isinstance(companion, video_companion.VideoCompanionSession):
            raise TypeError("companion must be a VideoCompanionSession")
        self._companion = companion
        self._timeline: list[BridgeTimelineEvent] = []
        self._receipts: list[BridgeReceipt] = []
        self._sequence = 0
        self._handoff_active = False
        self._lock = RLock()

    @property
    def timeline(self) -> tuple[BridgeTimelineEvent, ...]:
        with self._lock:
            return tuple(self._timeline)

    @property
    def receipts(self) -> tuple[BridgeReceipt, ...]:
        with self._lock:
            return tuple(self._receipts)

    def handoff_frame(
        self,
        request: FrameRequest,
        frame: bytes | bytearray | memoryview,
        dispatcher: VisionHandoff,
        *,
        context: video_reactor.ConversationContext,
        soul_vector: Mapping[str, object],
    ) -> BridgeOutcome:
        """Perform exactly one synchronous frame handoff, then retain metadata only."""

        if not isinstance(request, FrameRequest):
            raise TypeError("request must be FrameRequest")
        if not callable(dispatcher):
            raise TypeError("dispatcher must be callable")
        if not isinstance(context, video_reactor.ConversationContext):
            raise TypeError("context must be ConversationContext")
        if not isinstance(frame, (bytes, bytearray, memoryview)):
            raise TypeError("frame must be bytes-like")
        frame_view = memoryview(frame)
        byte_length = frame_view.nbytes
        if not 1 <= byte_length <= MAX_FRAME_BYTES:
            raise VideoVisionBridgeError("frame byte length is outside the bridge bound")
        frame_bytes = bytes(frame_view)
        frame_digest = sha256(frame_bytes).hexdigest()

        with self._lock:
            self._validate_request_source(request)
            if self._handoff_active:
                del frame_bytes
                return self._defer_request(request, frame_digest, "serialized_handoff_active")
            self._handoff_active = True
            event = vision_dispatch.VisionEvent(
                event_id=request.event_id,
                kind=(
                    vision_dispatch.VisionEventKind.DIRECT_UPLOAD
                    if request.intent is FrameIntent.DIRECT_QUESTION
                    else vision_dispatch.VisionEventKind.AMBIENT_FRAME
                ),
                source=request.source_id,
                stream_id=(request.source_id if request.intent is FrameIntent.AMBIENT else None),
                content_type=request.content_type,
                byte_length=byte_length,
                sha256=frame_digest,
                metadata=MappingProxyType(
                    {
                        "session_id": request.session_id,
                        "surface": request.surface.value,
                        "adapter_id": request.adapter_id or "",
                        "priority": request.priority.value,
                        "question_id": request.question_id or "",
                    }
                ),
            )
            processor_input = vision_dispatch.VisionProcessorInput(
                task_id=f"bridge:{request.event_id}",
                event=event,
                frame_bytes=frame_bytes,
            )
            try:
                observation = dispatcher(processor_input)
                if not isinstance(observation, VisionObservation):
                    raise VideoVisionBridgeError("dispatcher must return VisionObservation")
            except Exception as exc:
                return self._defer_request(
                    request,
                    frame_digest,
                    "dispatcher_handoff_failed",
                    error_type=type(exc).__name__,
                )
            finally:
                self._handoff_active = False
                del processor_input
                del frame_bytes

            try:
                self._validate_observation(request, observation)
            except VideoVisionBridgeError as exc:
                return self._defer_request(
                    request,
                    frame_digest,
                    "dispatcher_descriptor_mismatch",
                    error_type=type(exc).__name__,
                )
            fingerprint = observation.fingerprint or frame_digest
            return self._record_observation(
                observation,
                source_id=request.source_id,
                adapter_id=request.adapter_id,
                fingerprint=fingerprint,
                priority=request.priority,
                context=context,
                soul_vector=soul_vector,
            )

    def accept_descriptor(
        self,
        observation: VisionObservation | Mapping[str, object],
        *,
        source_id: str,
        adapter_id: str | None,
        fingerprint: str,
        intent: FrameIntent,
        context: video_reactor.ConversationContext,
        soul_vector: Mapping[str, object],
    ) -> BridgeOutcome:
        """Accept a JSON/API descriptor from House, Discord, or a file adapter."""

        parsed = self._observation(observation)
        source = _identifier(source_id, "source_id")
        adapter = None if adapter_id is None else _identifier(adapter_id, "adapter_id")
        frame_intent = _enum(FrameIntent, intent, "frame intent")
        priority = (
            BridgePriority.P1_INTERACTIVE
            if frame_intent is FrameIntent.DIRECT_QUESTION
            else BridgePriority.P2_AMBIENT
        )
        if not isinstance(context, video_reactor.ConversationContext):
            raise TypeError("context must be ConversationContext")
        with self._lock:
            self._validate_event_source(parsed.event, source)
            return self._record_observation(
                parsed,
                source_id=source,
                adapter_id=adapter,
                fingerprint=_identifier(fingerprint, "fingerprint"),
                priority=priority,
                context=context,
                soul_vector=soul_vector,
            )

    @staticmethod
    def _observation(value: VisionObservation | Mapping[str, object]) -> VisionObservation:
        if isinstance(value, VisionObservation):
            return value
        if not isinstance(value, Mapping):
            raise VideoVisionBridgeError("observation must be VisionObservation or an object")
        allowed = {"event", "meaningful", "novelty", "fingerprint"}
        if set(value) != allowed:
            raise VideoVisionBridgeError("observation fields are invalid")
        raw_event = value.get("event")
        if isinstance(raw_event, video_api.VisualDescriptorEvent):
            event = raw_event
        elif isinstance(raw_event, Mapping):
            parsed = video_api.contract_from_dict(raw_event)
            if not isinstance(parsed, video_api.VisualDescriptorEvent):
                raise VideoVisionBridgeError("event is not a visual descriptor")
            event = parsed
        else:
            raise VideoVisionBridgeError("event is not a visual descriptor")
        return VisionObservation(
            event=event,
            meaningful=value.get("meaningful"),  # type: ignore[arg-type]
            novelty=value.get("novelty"),  # type: ignore[arg-type]
            fingerprint=value.get("fingerprint"),  # type: ignore[arg-type]
        )

    def _validate_request_source(self, request: FrameRequest) -> None:
        if request.session_id != self._companion.session_id:
            raise VideoVisionBridgeError("request session does not match companion")
        if request.source_id != self._companion.source.source_id:
            raise VideoVisionBridgeError("request source does not match companion")
        if request.source_kind.value != self._companion.source.kind.value:
            raise VideoVisionBridgeError("request source kind does not match companion")
        if request.surface.value != self._companion.source.surface:
            raise VideoVisionBridgeError("request surface does not match companion")

    def _validate_observation(self, request: FrameRequest, observation: VisionObservation) -> None:
        event = observation.event
        if event.session_id != request.session_id or event.media_timestamp != request.media_timestamp:
            raise VideoVisionBridgeError("observation does not match frame request")
        if event.source_kind is not request.source_kind or event.surface is not request.surface:
            raise VideoVisionBridgeError("observation provenance does not match frame request")

    def _validate_event_source(self, event: video_api.VisualDescriptorEvent, source_id: str) -> None:
        if event.session_id != self._companion.session_id:
            raise VideoVisionBridgeError("descriptor session does not match companion")
        if source_id != self._companion.source.source_id:
            raise VideoVisionBridgeError("descriptor source does not match companion")
        if event.source_kind.value != self._companion.source.kind.value:
            raise VideoVisionBridgeError("descriptor source kind does not match companion")
        if event.surface.value != self._companion.source.surface:
            raise VideoVisionBridgeError("descriptor surface does not match companion")

    def _record_observation(
        self,
        observation: VisionObservation,
        *,
        source_id: str,
        adapter_id: str | None,
        fingerprint: str,
        priority: BridgePriority,
        context: video_reactor.ConversationContext,
        soul_vector: Mapping[str, object],
    ) -> BridgeOutcome:
        event = observation.event
        self._validate_event_source(event, source_id)

        companion_backpressure = None
        try:
            self._companion.record_frame(
                timestamp=event.media_timestamp,
                descriptor=event.descriptor,
                fingerprint=fingerprint,
                turn_owned=not context.user_interrupted,
                host_pressure=context.technical_backpressure is not None,
            )
        except video_companion.VideoCompanionError:
            companion_backpressure = "video_companion_rejected_descriptor"

        effective_context = context
        if companion_backpressure and context.technical_backpressure is None:
            effective_context = video_reactor.ConversationContext(
                mode=context.mode,
                user_interrupted=context.user_interrupted,
                question_pending=context.question_pending,
                technical_backpressure=companion_backpressure,
            )
        reaction_event = video_reactor.MeaningfulEvent(
            provenance=video_reactor.EventProvenance(
                event_id=f"{event.session_id}:{event.seq}",
                source_id=source_id,
                surface=event.surface.value,
                adapter_id=adapter_id,
            ),
            start_seconds=event.media_timestamp,
            end_seconds=event.media_timestamp,
            fingerprint=fingerprint,
            meaningful=observation.meaningful,
            novelty=observation.novelty,
        )
        reaction = video_reactor.decide_video_reaction(
            reaction_event, effective_context, soul_vector
        )

        if not reaction.meaningful_event_retained:
            receipt = self._new_receipt(
                event_id=reaction_event.provenance.event_id,
                priority=priority,
                disposition="ignored",
                reason=reaction.reason.value,
                retained=False,
            )
            return BridgeOutcome(receipt, None, reaction)

        duplicate = self._exact_duplicate(
            event,
            source_id=source_id,
            fingerprint=fingerprint,
            meaningful=observation.meaningful,
            novelty=observation.novelty,
            priority=priority,
            disposition=reaction.disposition.value,
        )
        if duplicate is not None:
            extended = replace(
                duplicate,
                end_seconds=max(duplicate.end_seconds, event.media_timestamp),
                compacted_duplicates=duplicate.compacted_duplicates + 1,
            )
            self._timeline[-1] = extended
            receipt = self._new_receipt(
                event_id=reaction_event.provenance.event_id,
                priority=priority,
                disposition="compacted",
                reason="exact_duplicate_timestamp_range",
                retained=True,
                compacted_into_event_id=duplicate.event_id,
            )
            return BridgeOutcome(receipt, extended, reaction)

        timeline_event = BridgeTimelineEvent(
            sequence=len(self._timeline) + 1,
            event_id=reaction_event.provenance.event_id,
            session_id=event.session_id,
            source_id=source_id,
            source_kind=event.source_kind.value,
            surface=event.surface.value,
            adapter_id=adapter_id,
            start_seconds=event.media_timestamp,
            end_seconds=event.media_timestamp,
            descriptor=event.descriptor,
            fingerprint=fingerprint,
            meaningful=observation.meaningful,
            novelty=observation.novelty.value,
            priority=priority.value,
            disposition=reaction.disposition.value,
            defer_reason=(
                reaction.reason.value
                if reaction.disposition is video_reactor.EventDisposition.DEFERRED
                else None
            ),
            reaction_action=reaction.action.value,
        )
        self._timeline.append(timeline_event)
        receipt = self._new_receipt(
            event_id=timeline_event.event_id,
            priority=priority,
            disposition=timeline_event.disposition,
            reason=reaction.reason.value,
            retained=True,
        )
        return BridgeOutcome(receipt, timeline_event, reaction)

    def _exact_duplicate(
        self,
        event: video_api.VisualDescriptorEvent,
        *,
        source_id: str,
        fingerprint: str,
        meaningful: bool,
        novelty: video_reactor.Novelty,
        priority: BridgePriority,
        disposition: str,
    ) -> BridgeTimelineEvent | None:
        if not self._timeline:
            return None
        prior = self._timeline[-1]
        return prior if (
            prior.session_id == event.session_id
            and prior.source_id == source_id
            and prior.source_kind == event.source_kind.value
            and prior.surface == event.surface.value
            and prior.descriptor == event.descriptor
            and prior.fingerprint == fingerprint
            and prior.meaningful is meaningful
            and prior.novelty == novelty.value
            and prior.priority == priority.value
            and prior.disposition == disposition
            and event.media_timestamp >= prior.end_seconds
        ) else None

    def _defer_request(
        self,
        request: FrameRequest,
        fingerprint: str,
        reason: str,
        *,
        error_type: str | None = None,
    ) -> BridgeOutcome:
        event_id = f"{request.session_id}:{request.event_id}"
        if not request.meaningful_hint:
            receipt = self._new_receipt(
                event_id=event_id,
                priority=request.priority,
                disposition="ignored",
                reason=reason,
                retained=False,
                error_type=error_type,
            )
            return BridgeOutcome(receipt, None, None)
        timeline_event = BridgeTimelineEvent(
            sequence=len(self._timeline) + 1,
            event_id=event_id,
            session_id=request.session_id,
            source_id=request.source_id,
            source_kind=request.source_kind.value,
            surface=request.surface.value,
            adapter_id=request.adapter_id,
            start_seconds=request.media_timestamp,
            end_seconds=request.media_timestamp,
            descriptor="vision descriptor deferred",
            fingerprint=fingerprint,
            meaningful=True,
            novelty="unknown",
            priority=request.priority.value,
            disposition="deferred",
            defer_reason=reason,
            reaction_action="silent",
        )
        self._timeline.append(timeline_event)
        receipt = self._new_receipt(
            event_id=event_id,
            priority=request.priority,
            disposition="deferred",
            reason=reason,
            retained=True,
            error_type=error_type,
        )
        return BridgeOutcome(receipt, timeline_event, None)

    def _new_receipt(
        self,
        *,
        event_id: str,
        priority: BridgePriority,
        disposition: str,
        reason: str,
        retained: bool,
        compacted_into_event_id: str | None = None,
        error_type: str | None = None,
    ) -> BridgeReceipt:
        self._sequence += 1
        receipt = BridgeReceipt(
            sequence=self._sequence,
            event_id=event_id,
            priority=priority.value,
            disposition=disposition,
            reason=reason,
            retained=retained,
            compacted_into_event_id=compacted_into_event_id,
            error_type=error_type,
        )
        self._receipts.append(receipt)
        return receipt

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            snapshot = {
                "schema": SNAPSHOT_SCHEMA,
                "session_id": self._companion.session_id,
                "source_id": self._companion.source.source_id,
                "surface": self._companion.source.surface,
                "timeline": [asdict(event) for event in self._timeline],
                "receipts": [asdict(receipt) for receipt in self._receipts],
            }
            if _contains_bytes(snapshot):
                raise AssertionError("bridge snapshot contains raw frame bytes")
            return snapshot

    def status(self) -> dict[str, object]:
        with self._lock:
            dispositions = {
                name: sum(event.disposition == name for event in self._timeline)
                for name in ("observed", "retained", "deferred")
            }
            return {
                "schema": STATUS_SCHEMA,
                "session_id": self._companion.session_id,
                "source_id": self._companion.source.source_id,
                "surface": self._companion.source.surface,
                "handoff_active": self._handoff_active,
                "serialized": True,
                "network_calls": 0,
                "model_calls": 0,
                "stores_raw_frames": False,
                "owns_p0_conversation": False,
                "direct_question_priority": BridgePriority.P1_INTERACTIVE.value,
                "ambient_frame_priority": BridgePriority.P2_AMBIENT.value,
                "timeline_events": len(self._timeline),
                "receipts": len(self._receipts),
                "dispositions": dispositions,
            }

    def serialized_snapshot_json(self) -> str:
        return json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"))


__all__ = [
    "BRIDGE_SCHEMA",
    "MAX_FRAME_BYTES",
    "SNAPSHOT_SCHEMA",
    "STATUS_SCHEMA",
    "BridgeOutcome",
    "BridgePriority",
    "BridgeReceipt",
    "BridgeTimelineEvent",
    "FrameIntent",
    "FrameRequest",
    "VideoVisionBridge",
    "VideoVisionBridgeError",
    "VisionObservation",
]
