"""Bounded, model-free state for observing file and live video sources.

Media acquisition, decoding, transcription, and model inference deliberately
live outside this module. Callers may submit only derived descriptors and
transcript text tied to an opaque, non-fetchable source identifier.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


MAX_TIMELINE_ENTRIES = 512
MAX_TEXT_CHARS = 2_000
MAX_ID_CHARS = 256
SNAPSHOT_VERSION = 2


class VideoCompanionError(ValueError):
    """A video-companion input or state transition was rejected."""


class SourceKind(str, Enum):
    FILE = "file"
    LIVE = "live"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    STOPPED = "stopped"


class SchedulerPriority(str, Enum):
    DIRECT_CONVERSATION = "P0"
    VIDEO_COMPANION = "P2"


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    source_id: str
    kind: SourceKind
    origin: str
    surface: str = "house_hq"
    adapter_id: str | None = None
    label: str | None = None
    content_sha256: str | None = None
    duration_seconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _opaque_id(self.source_id, "source_id"))
        object.__setattr__(self, "kind", _enum(SourceKind, self.kind, "kind"))
        allowed_origin = {
            SourceKind.FILE: "local_file_reference",
            SourceKind.LIVE: "live_capture",
        }[self.kind]
        if self.origin != allowed_origin:
            raise VideoCompanionError(
                f"{self.kind.value} source origin must be {allowed_origin!r}"
            )
        object.__setattr__(self, "surface", _opaque_id(self.surface, "surface"))
        if self.adapter_id is not None:
            object.__setattr__(
                self, "adapter_id", _opaque_id(self.adapter_id, "adapter_id")
            )
        if self.label is not None:
            object.__setattr__(self, "label", _safe_text(self.label, "label"))

        if self.kind is SourceKind.FILE:
            digest = _sha256(self.content_sha256, "content_sha256")
            duration = _number(self.duration_seconds, "duration_seconds", positive=True)
            object.__setattr__(self, "content_sha256", digest)
            object.__setattr__(self, "duration_seconds", duration)
        elif self.content_sha256 is not None or self.duration_seconds is not None:
            raise VideoCompanionError(
                "live sources must not claim a file digest or fixed duration"
            )


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    sequence: int
    kind: str
    start_seconds: float
    end_seconds: float
    text: str
    fingerprint: str | None = None
    speaker: str | None = None
    disposition: str = "observed"
    defer_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SamplingDecision:
    accepted: bool
    reason: str
    interval_seconds: float
    next_sample_at: float


@dataclass(frozen=True, slots=True)
class TranscriptDecision:
    accepted: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ReactionEligibility:
    eligible: bool
    reason: str
    deferred: bool


@dataclass(frozen=True, slots=True)
class CompactionSummary:
    entry_count: int
    start_seconds: float | None
    end_seconds: float | None
    digest_sha256: str | None


@dataclass(frozen=True, slots=True)
class SchedulerMetadata:
    priority: SchedulerPriority
    work_kind: str
    preemptible: bool
    session_id: str
    source_id: str


@dataclass(frozen=True, slots=True)
class Progress:
    mode: SourceKind
    processed_until: float
    duration_seconds: float | None
    fraction: float | None
    complete: bool


_URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^\s<>\"']+", re.IGNORECASE)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _contains_bytes(value: object) -> bool:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return True
    if isinstance(value, Mapping):
        return any(_contains_bytes(key) or _contains_bytes(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_bytes(item) for item in value)
    return False


def _safe_text(value: object, name: str, *, maximum: int = MAX_TEXT_CHARS) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)) or not isinstance(value, str):
        raise VideoCompanionError(f"{name} must be text, never raw media bytes")
    cleaned = " ".join(value.split())
    if not cleaned:
        raise VideoCompanionError(f"{name} must not be empty")
    # URLs are unnecessary for derived companion state and may carry secrets in
    # provider-specific locations, so retain neither signed nor ordinary URLs.
    cleaned = _URL_RE.sub("[redacted-url]", cleaned)
    if len(cleaned) > maximum:
        raise VideoCompanionError(f"{name} exceeds {maximum} characters")
    return cleaned


def _opaque_id(value: object, name: str) -> str:
    result = _safe_text(value, name, maximum=MAX_ID_CHARS)
    if "://" in result or result.startswith(("file:", "\\\\")):
        raise VideoCompanionError(f"{name} must be an opaque identifier, not a URL")
    if "[redacted-url]" in result:
        raise VideoCompanionError(f"{name} must not contain a URL")
    return result


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value.lower()) is None:
        raise VideoCompanionError(f"{name} must be a hexadecimal SHA-256 digest")
    return value.lower()


def _number(value: object, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise VideoCompanionError(f"{name} must be a finite number")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise VideoCompanionError(f"{name} must be a finite number") from None
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        qualifier = "positive " if positive else "non-negative "
        raise VideoCompanionError(f"{name} must be a finite {qualifier}number")
    return result


def _enum(enum_type: type[Enum], value: object, name: str) -> Any:
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        raise VideoCompanionError(f"invalid {name}: {value!r}") from None


class VideoCompanionSession:
    """Resumable bounded state for one file or live companion session."""

    def __init__(
        self,
        *,
        session_id: str,
        source: SourceProvenance,
        max_timeline: int = 128,
        min_sample_interval: float = 1.0,
        max_sample_interval: float = 12.0,
    ) -> None:
        self.session_id = _opaque_id(session_id, "session_id")
        if not isinstance(source, SourceProvenance):
            raise VideoCompanionError("source must be SourceProvenance")
        self.source = source
        if isinstance(max_timeline, bool) or not isinstance(max_timeline, int):
            raise VideoCompanionError("max_timeline must be an integer")
        if not 1 <= max_timeline <= MAX_TIMELINE_ENTRIES:
            raise VideoCompanionError(
                f"max_timeline must be between 1 and {MAX_TIMELINE_ENTRIES}"
            )
        self.max_timeline = max_timeline
        self.min_sample_interval = _number(
            min_sample_interval, "min_sample_interval", positive=True
        )
        self.max_sample_interval = _number(
            max_sample_interval, "max_sample_interval", positive=True
        )
        if self.min_sample_interval > self.max_sample_interval:
            raise VideoCompanionError("minimum sample interval exceeds maximum")
        self.status = SessionStatus.ACTIVE
        self.processed_until = 0.0
        self.current_sample_interval = self.min_sample_interval
        self.last_frame_at: float | None = None
        self.last_frame_fingerprint: str | None = None
        self.last_frame_sequence: int | None = None
        self.last_transcript_key: str | None = None
        self.last_transcript_sequence: int | None = None
        self.interrupted_at: float | None = None
        self._resume_status: SessionStatus | None = None
        self._sequence = 0
        self._timeline: deque[TimelineEntry] = deque(maxlen=max_timeline)
        self._compacted_count = 0
        self._compacted_start: float | None = None
        self._compacted_end: float | None = None
        self._compacted_digest: str | None = None

    @classmethod
    def for_file(
        cls,
        *,
        session_id: str,
        source_id: str,
        content_sha256: str,
        duration_seconds: float,
        label: str | None = None,
        surface: str = "house_hq",
        adapter_id: str | None = None,
        **options: Any,
    ) -> "VideoCompanionSession":
        return cls(
            session_id=session_id,
            source=SourceProvenance(
                source_id=source_id,
                kind=SourceKind.FILE,
                origin="local_file_reference",
                surface=surface,
                adapter_id=adapter_id,
                label=label,
                content_sha256=content_sha256,
                duration_seconds=duration_seconds,
            ),
            **options,
        )

    @classmethod
    def for_live(
        cls,
        *,
        session_id: str,
        source_id: str,
        label: str | None = None,
        surface: str = "house_hq",
        adapter_id: str | None = None,
        **options: Any,
    ) -> "VideoCompanionSession":
        return cls(
            session_id=session_id,
            source=SourceProvenance(
                source_id=source_id,
                kind=SourceKind.LIVE,
                origin="live_capture",
                surface=surface,
                adapter_id=adapter_id,
                label=label,
            ),
            **options,
        )

    @property
    def timeline(self) -> tuple[TimelineEntry, ...]:
        return tuple(self._timeline)

    @property
    def compaction_summary(self) -> CompactionSummary:
        return CompactionSummary(
            self._compacted_count,
            self._compacted_start,
            self._compacted_end,
            self._compacted_digest,
        )

    @property
    def deferred_timeline(self) -> tuple[TimelineEntry, ...]:
        return tuple(entry for entry in self._timeline if entry.disposition == "deferred")

    @property
    def progress(self) -> Progress:
        duration = self.source.duration_seconds
        fraction = None if duration is None else min(1.0, self.processed_until / duration)
        return Progress(
            mode=self.source.kind,
            processed_until=self.processed_until,
            duration_seconds=duration,
            fraction=fraction,
            complete=self.status is SessionStatus.COMPLETED,
        )

    def scheduler_metadata(self, *, direct_conversation: bool = False) -> SchedulerMetadata:
        return SchedulerMetadata(
            priority=(
                SchedulerPriority.DIRECT_CONVERSATION
                if direct_conversation
                else SchedulerPriority.VIDEO_COMPANION
            ),
            work_kind="direct_conversation" if direct_conversation else "video_companion",
            preemptible=not direct_conversation,
            session_id=self.session_id,
            source_id=self.source.source_id,
        )

    def advance_progress(self, timestamp: float) -> Progress:
        self._require_processable()
        value = _number(timestamp, "timestamp")
        if value < self.processed_until:
            raise VideoCompanionError("progress must be monotonic")
        duration = self.source.duration_seconds
        if duration is not None:
            self.processed_until = min(value, duration)
            if self.processed_until >= duration:
                self.status = SessionStatus.COMPLETED
        else:
            self.processed_until = value
        return self.progress

    def record_frame(
        self,
        *,
        timestamp: float,
        descriptor: str,
        fingerprint: str | None = None,
        motion_score: float = 0.0,
        turn_owned: bool = True,
        host_pressure: bool = False,
    ) -> SamplingDecision:
        self._require_recordable()
        at = _number(timestamp, "timestamp")
        text = _safe_text(descriptor, "descriptor")
        motion = _number(motion_score, "motion_score")
        if motion > 1:
            raise VideoCompanionError("motion_score must not exceed 1")
        if fingerprint is None:
            frame_key = hashlib.sha256(text.casefold().encode("utf-8")).hexdigest()
        else:
            frame_key = _opaque_id(fingerprint, "fingerprint")

        if self.last_frame_at is not None:
            if at < self.last_frame_at:
                raise VideoCompanionError("frame timestamps must be monotonic")

        if frame_key == self.last_frame_fingerprint:
            self.last_frame_at = at
            self.current_sample_interval = min(
                self.max_sample_interval,
                self.current_sample_interval * 1.5,
            )
            compacted = self._extend_entry(self.last_frame_sequence, at)
            self._advance_seen_time(at)
            if not compacted:
                disposition, defer_reason = self._recording_disposition(
                    turn_owned=turn_owned, host_pressure=host_pressure
                )
                entry = self._append(
                    "frame", at, at, text, fingerprint=frame_key,
                    disposition=disposition, defer_reason=defer_reason,
                )
                self.last_frame_sequence = entry.sequence
                return SamplingDecision(
                    True, defer_reason or "accepted", self.current_sample_interval,
                    at + self.current_sample_interval,
                )
            return SamplingDecision(
                False,
                "compacted_unchanged_run",
                self.current_sample_interval,
                at + self.current_sample_interval,
            )

        self.last_frame_at = at
        self.last_frame_fingerprint = frame_key
        if motion >= 0.6:
            self.current_sample_interval = self.min_sample_interval
        else:
            self.current_sample_interval = max(
                self.min_sample_interval,
                self.current_sample_interval * 0.75,
            )
        disposition, defer_reason = self._recording_disposition(
            turn_owned=turn_owned, host_pressure=host_pressure
        )
        entry = self._append(
            "frame", at, at, text, fingerprint=frame_key,
            disposition=disposition, defer_reason=defer_reason,
        )
        self.last_frame_sequence = entry.sequence
        self._advance_seen_time(at)
        return SamplingDecision(
            True,
            defer_reason or "accepted",
            self.current_sample_interval,
            at + self.current_sample_interval,
        )

    def record_transcript(
        self,
        *,
        start_seconds: float,
        end_seconds: float,
        text: str,
        speaker: str | None = None,
        turn_owned: bool = True,
        host_pressure: bool = False,
    ) -> TranscriptDecision:
        self._require_recordable()
        start = _number(start_seconds, "start_seconds")
        end = _number(end_seconds, "end_seconds")
        if end < start:
            raise VideoCompanionError("transcript end precedes its start")
        content = _safe_text(text, "transcript text")
        safe_speaker = None if speaker is None else _safe_text(
            speaker, "speaker", maximum=128
        )
        key = hashlib.sha256(
            f"{safe_speaker or ''}\0{content.casefold()}".encode("utf-8")
        ).hexdigest()
        if key == self.last_transcript_key:
            compacted = self._extend_entry(self.last_transcript_sequence, end)
            self._advance_seen_time(end)
            if compacted:
                return TranscriptDecision(False, "compacted_duplicate_range")
        self.last_transcript_key = key
        disposition, defer_reason = self._recording_disposition(
            turn_owned=turn_owned, host_pressure=host_pressure
        )
        entry = self._append(
            "transcript", start, end, content, fingerprint=key, speaker=safe_speaker,
            disposition=disposition, defer_reason=defer_reason,
        )
        self.last_transcript_sequence = entry.sequence
        self._advance_seen_time(end)
        return TranscriptDecision(True, defer_reason or "accepted")

    def reaction_eligibility(
        self,
        *,
        meaningful_event: bool = True,
        turn_owned: bool = True,
        host_pressure: bool = False,
    ) -> ReactionEligibility:
        if not meaningful_event:
            return ReactionEligibility(False, "not_meaningful", False)
        if self.status in {SessionStatus.COMPLETED, SessionStatus.STOPPED}:
            return ReactionEligibility(False, f"session_{self.status.value}", False)
        disposition, reason = self._recording_disposition(
            turn_owned=turn_owned, host_pressure=host_pressure
        )
        if disposition == "deferred":
            return ReactionEligibility(False, reason or "deferred", True)
        return ReactionEligibility(True, "eligible", False)

    def record_reaction(
        self,
        *,
        now: float,
        cue: str,
        meaningful_event: bool = True,
        turn_owned: bool = True,
        host_pressure: bool = False,
    ) -> TimelineEntry:
        eligibility = self.reaction_eligibility(
            meaningful_event=meaningful_event,
            turn_owned=turn_owned,
            host_pressure=host_pressure,
        )
        if not meaningful_event:
            raise VideoCompanionError("reaction cue is not tied to a meaningful event")
        at = _number(now, "now")
        return self._append(
            "reaction", at, at, _safe_text(cue, "cue"),
            disposition="deferred" if eligibility.deferred else "observed",
            defer_reason=eligibility.reason if eligibility.deferred else None,
        )

    def resolve_deferred(self, sequence: int) -> TimelineEntry:
        """Mark retained deferred work complete without changing its provenance."""

        for index, entry in enumerate(self._timeline):
            if entry.sequence != sequence:
                continue
            if entry.disposition != "deferred":
                raise VideoCompanionError("timeline entry is not deferred")
            resolved = TimelineEntry(
                sequence=entry.sequence,
                kind=entry.kind,
                start_seconds=entry.start_seconds,
                end_seconds=entry.end_seconds,
                text=entry.text,
                fingerprint=entry.fingerprint,
                speaker=entry.speaker,
                disposition="resolved",
                defer_reason=entry.defer_reason,
            )
            self._timeline[index] = resolved
            return resolved
        raise VideoCompanionError("deferred timeline entry is not retained")

    def interrupt_for_direct_conversation(self, *, now: float) -> SchedulerMetadata:
        at = _number(now, "now")
        if self.status is SessionStatus.INTERRUPTED:
            return self.scheduler_metadata(direct_conversation=True)
        if self.status not in {SessionStatus.ACTIVE, SessionStatus.PAUSED}:
            raise VideoCompanionError(f"cannot interrupt a {self.status.value} session")
        self._resume_status = self.status
        self.status = SessionStatus.INTERRUPTED
        self.interrupted_at = at
        self._append("interruption", at, at, "direct conversation")
        return self.scheduler_metadata(direct_conversation=True)

    def resume_after_direct_conversation(self, *, now: float) -> SchedulerMetadata:
        at = _number(now, "now")
        if self.status is not SessionStatus.INTERRUPTED:
            raise VideoCompanionError("session is not interrupted")
        self.status = self._resume_status or SessionStatus.ACTIVE
        self._resume_status = None
        self.interrupted_at = None
        self._append("resume", at, at, "video companion")
        return self.scheduler_metadata()

    def pause(self) -> None:
        if self.status is not SessionStatus.ACTIVE:
            raise VideoCompanionError("only an active session can be paused")
        self.status = SessionStatus.PAUSED

    def resume(self) -> None:
        if self.status is not SessionStatus.PAUSED:
            raise VideoCompanionError("only a paused session can be resumed")
        self.status = SessionStatus.ACTIVE

    def stop(self) -> None:
        if self.status is SessionStatus.COMPLETED:
            return
        self.status = SessionStatus.STOPPED

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": SNAPSHOT_VERSION,
            "session_id": self.session_id,
            "source": {
                **asdict(self.source),
                "kind": self.source.kind.value,
            },
            "settings": {
                "max_timeline": self.max_timeline,
                "min_sample_interval": self.min_sample_interval,
                "max_sample_interval": self.max_sample_interval,
            },
            "state": {
                "status": self.status.value,
                "processed_until": self.processed_until,
                "current_sample_interval": self.current_sample_interval,
                "last_frame_at": self.last_frame_at,
                "last_frame_fingerprint": self.last_frame_fingerprint,
                "last_frame_sequence": self.last_frame_sequence,
                "last_transcript_key": self.last_transcript_key,
                "last_transcript_sequence": self.last_transcript_sequence,
                "interrupted_at": self.interrupted_at,
                "resume_status": self._resume_status.value if self._resume_status else None,
                "sequence": self._sequence,
            },
            "compaction": asdict(self.compaction_summary),
            "timeline": [asdict(entry) for entry in self._timeline],
        }

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "VideoCompanionSession":
        if not isinstance(snapshot, Mapping) or _contains_bytes(snapshot):
            raise VideoCompanionError("snapshot must be a mapping without raw media bytes")
        if snapshot.get("version") != SNAPSHOT_VERSION:
            raise VideoCompanionError("unsupported snapshot version")
        try:
            source_data = snapshot["source"]
            settings = snapshot["settings"]
            state = snapshot["state"]
            compaction = snapshot["compaction"]
            timeline = snapshot["timeline"]
            if not all(
                isinstance(item, Mapping)
                for item in (source_data, settings, state, compaction)
            ):
                raise TypeError
            if not isinstance(timeline, list):
                raise TypeError
            source = SourceProvenance(
                source_id=source_data["source_id"],
                kind=source_data["kind"],
                origin=source_data["origin"],
                surface=source_data["surface"],
                adapter_id=source_data.get("adapter_id"),
                label=source_data.get("label"),
                content_sha256=source_data.get("content_sha256"),
                duration_seconds=source_data.get("duration_seconds"),
            )
            session = cls(
                session_id=snapshot["session_id"],
                source=source,
                max_timeline=settings["max_timeline"],
                min_sample_interval=settings["min_sample_interval"],
                max_sample_interval=settings["max_sample_interval"],
            )
            session.status = _enum(SessionStatus, state["status"], "status")
            session.processed_until = _number(state["processed_until"], "processed_until")
            session.current_sample_interval = _number(
                state["current_sample_interval"], "current_sample_interval", positive=True
            )
            session.last_frame_at = _optional_number(state.get("last_frame_at"), "last_frame_at")
            session.last_frame_fingerprint = _optional_id(
                state.get("last_frame_fingerprint"), "last_frame_fingerprint"
            )
            session.last_frame_sequence = _optional_int(
                state.get("last_frame_sequence"), "last_frame_sequence"
            )
            session.last_transcript_key = _optional_id(
                state.get("last_transcript_key"), "last_transcript_key"
            )
            session.last_transcript_sequence = _optional_int(
                state.get("last_transcript_sequence"), "last_transcript_sequence"
            )
            session.interrupted_at = _optional_number(
                state.get("interrupted_at"), "interrupted_at"
            )
            resume_status = state.get("resume_status")
            session._resume_status = (
                None if resume_status is None else _enum(SessionStatus, resume_status, "resume_status")
            )
            session._sequence = int(state["sequence"])
            if session._sequence < 0:
                raise VideoCompanionError("sequence must be non-negative")
            session._compacted_count = int(compaction["entry_count"])
            if session._compacted_count < 0:
                raise VideoCompanionError("compacted entry count must be non-negative")
            session._compacted_start = _optional_number(
                compaction.get("start_seconds"), "compacted start"
            )
            session._compacted_end = _optional_number(
                compaction.get("end_seconds"), "compacted end"
            )
            session._compacted_digest = (
                None if compaction.get("digest_sha256") is None
                else _sha256(compaction["digest_sha256"], "compacted digest")
            )
            if len(timeline) > session.max_timeline:
                raise VideoCompanionError("snapshot timeline exceeds its bound")
            for raw in timeline:
                if not isinstance(raw, Mapping):
                    raise TypeError
                entry = TimelineEntry(
                    sequence=int(raw["sequence"]),
                    kind=_safe_text(raw["kind"], "timeline kind", maximum=32),
                    start_seconds=_number(raw["start_seconds"], "timeline start"),
                    end_seconds=_number(raw["end_seconds"], "timeline end"),
                    text=_safe_text(raw["text"], "timeline text"),
                    fingerprint=_optional_id(raw.get("fingerprint"), "timeline fingerprint"),
                    speaker=(
                        None if raw.get("speaker") is None
                        else _safe_text(raw["speaker"], "timeline speaker", maximum=128)
                    ),
                    disposition=_safe_text(
                        raw.get("disposition", "observed"),
                        "timeline disposition",
                        maximum=16,
                    ),
                    defer_reason=(
                        None if raw.get("defer_reason") is None
                        else _safe_text(raw["defer_reason"], "defer reason", maximum=64)
                    ),
                )
                if entry.end_seconds < entry.start_seconds:
                    raise VideoCompanionError("timeline entry ends before it starts")
                if entry.disposition not in {"observed", "deferred", "resolved"}:
                    raise VideoCompanionError("invalid timeline disposition")
                if (entry.disposition == "deferred") != (entry.defer_reason is not None):
                    if entry.disposition != "resolved" or entry.defer_reason is None:
                        raise VideoCompanionError("invalid timeline deferral provenance")
                session._timeline.append(entry)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            if isinstance(exc, VideoCompanionError):
                raise
            raise VideoCompanionError("malformed video companion snapshot") from None
        session._validate_restored_state()
        return session

    def _require_processable(self) -> None:
        if self.status is not SessionStatus.ACTIVE:
            raise VideoCompanionError(f"session is {self.status.value}")

    def _require_recordable(self) -> None:
        if self.status in {SessionStatus.COMPLETED, SessionStatus.STOPPED}:
            raise VideoCompanionError(f"session is {self.status.value}")

    def _recording_disposition(
        self, *, turn_owned: bool, host_pressure: bool
    ) -> tuple[str, str | None]:
        if self.status is SessionStatus.INTERRUPTED or not turn_owned:
            return "deferred", "turn_ownership"
        if host_pressure:
            return "deferred", "host_pressure"
        if self.status is SessionStatus.PAUSED:
            return "deferred", "session_paused"
        return "observed", None

    def _advance_seen_time(self, timestamp: float) -> None:
        if timestamp < self.processed_until:
            return
        duration = self.source.duration_seconds
        self.processed_until = timestamp if duration is None else min(timestamp, duration)
        if duration is not None and self.processed_until >= duration:
            if self.status is SessionStatus.INTERRUPTED:
                self._resume_status = SessionStatus.COMPLETED
            else:
                self.status = SessionStatus.COMPLETED

    def _append(
        self,
        kind: str,
        start: float,
        end: float,
        text: str,
        *,
        fingerprint: str | None = None,
        speaker: str | None = None,
        disposition: str = "observed",
        defer_reason: str | None = None,
    ) -> TimelineEntry:
        if len(self._timeline) >= self.max_timeline:
            retained = list(self._timeline)
            compact_index = next(
                (index for index, item in enumerate(retained)
                 if item.disposition != "deferred"),
                None,
            )
            if compact_index is None:
                raise VideoCompanionError(
                    "timeline capacity is occupied by unresolved deferred events"
                )
            self._compact_entry(retained.pop(compact_index))
            self._timeline = deque(retained, maxlen=self.max_timeline)
        self._sequence += 1
        entry = TimelineEntry(
            sequence=self._sequence,
            kind=kind,
            start_seconds=start,
            end_seconds=end,
            text=text,
            fingerprint=fingerprint,
            speaker=speaker,
            disposition=disposition,
            defer_reason=defer_reason,
        )
        self._timeline.append(entry)
        return entry

    def _extend_entry(self, sequence: int | None, end: float) -> bool:
        if sequence is None:
            return False
        for index, entry in enumerate(self._timeline):
            if entry.sequence != sequence:
                continue
            self._timeline[index] = TimelineEntry(
                sequence=entry.sequence,
                kind=entry.kind,
                start_seconds=entry.start_seconds,
                end_seconds=max(entry.end_seconds, end),
                text=entry.text,
                fingerprint=entry.fingerprint,
                speaker=entry.speaker,
                disposition=entry.disposition,
                defer_reason=entry.defer_reason,
            )
            return True
        return False

    def _compact_entry(self, entry: TimelineEntry) -> None:
        payload = json.dumps(
            {"previous": self._compacted_digest, "entry": asdict(entry)},
            sort_keys=True,
            separators=(",", ":"),
        )
        self._compacted_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self._compacted_count += 1
        self._compacted_start = min(
            self._compacted_start
            if self._compacted_start is not None
            else entry.start_seconds,
            entry.start_seconds,
        )
        self._compacted_end = max(self._compacted_end or entry.end_seconds, entry.end_seconds)

    def _validate_restored_state(self) -> None:
        if not self.min_sample_interval <= self.current_sample_interval <= self.max_sample_interval:
            raise VideoCompanionError("sample interval is outside configured bounds")
        duration = self.source.duration_seconds
        if duration is not None and self.processed_until > duration:
            raise VideoCompanionError("file progress exceeds source duration")
        if self.status is SessionStatus.COMPLETED and (
            duration is None or self.processed_until != duration
        ):
            raise VideoCompanionError("completed state requires complete file progress")
        if self.status is SessionStatus.INTERRUPTED:
            if self.interrupted_at is None or self._resume_status not in {
                SessionStatus.ACTIVE, SessionStatus.PAUSED, SessionStatus.COMPLETED
            }:
                raise VideoCompanionError("interrupted state lacks resume provenance")
        elif self.interrupted_at is not None or self._resume_status is not None:
            raise VideoCompanionError("non-interrupted state contains interruption metadata")
        if self._timeline and self._sequence < self._timeline[-1].sequence:
            raise VideoCompanionError("sequence precedes timeline entries")
        has_compaction = self._compacted_count > 0
        if has_compaction != all(
            value is not None
            for value in (
                self._compacted_start,
                self._compacted_end,
                self._compacted_digest,
            )
        ):
            raise VideoCompanionError("incomplete compacted-history provenance")


def _optional_number(value: object, name: str) -> float | None:
    return None if value is None else _number(value, name)


def _optional_id(value: object, name: str) -> str | None:
    return None if value is None else _opaque_id(value, name)


def _optional_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise VideoCompanionError(f"{name} must be a non-negative integer")
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        raise VideoCompanionError(f"{name} must be a non-negative integer") from None
    if result < 0 or result != value:
        raise VideoCompanionError(f"{name} must be a non-negative integer")
    return result
