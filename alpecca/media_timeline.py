"""Pure planning over caller-supplied media metadata and descriptors.

This module performs no media acquisition, file access, decoding, or network
requests. It validates already-derived metadata and plans timestamped work.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Mapping, Sequence


MAX_DURATION_SECONDS = 7 * 24 * 60 * 60
MAX_STREAMS = 64
MAX_DESCRIPTORS = 100_000
MAX_WINDOWS = 4_096
MAX_TEXT_CHARS = 4_000
MAX_ID_CHARS = 256
MAX_DIMENSION = 32_768
MAX_SAMPLE_RATE = 768_000
MAX_CHANNELS = 64
MAX_MEDIA_BYTES = 16 * 1024**4


class MediaTimelineError(ValueError):
    """Caller-supplied metadata or a planning request was rejected."""


@dataclass(frozen=True, slots=True)
class MediaSource:
    """Opaque source provenance shared by every media ingress surface."""

    source_id: str
    adapter: str
    session_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(self, "adapter", _identifier(self.adapter, "adapter"))
        if self.session_id is not None:
            object.__setattr__(
                self,
                "session_id",
                _identifier(self.session_id, "session_id"),
            )


@dataclass(frozen=True, slots=True)
class MediaStreamMetadata:
    index: int
    kind: str
    codec_name: str | None
    duration_seconds: float | None
    frame_rate: float | None
    width: int | None
    height: int | None
    sample_rate: int | None
    channels: int | None


@dataclass(frozen=True, slots=True)
class MediaMetadata:
    source: MediaSource
    duration_seconds: float
    format_name: str | None
    byte_size: int | None
    bit_rate: int | None
    streams: tuple[MediaStreamMetadata, ...]

    @property
    def video_frame_rate(self) -> float | None:
        rates = [
            stream.frame_rate
            for stream in self.streams
            if stream.kind == "video" and stream.frame_rate is not None
        ]
        return max(rates) if rates else None


@dataclass(frozen=True, slots=True)
class TranscriptDescriptor:
    event_id: str
    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None
    meaningful: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        start = _number(self.start_seconds, "start_seconds")
        end = _number(self.end_seconds, "end_seconds")
        if end < start:
            raise MediaTimelineError("transcript end precedes its start")
        object.__setattr__(self, "start_seconds", start)
        object.__setattr__(self, "end_seconds", end)
        object.__setattr__(self, "text", _text(self.text, "text"))
        if self.speaker is not None:
            object.__setattr__(self, "speaker", _text(self.speaker, "speaker", 256))
        if not isinstance(self.meaningful, bool):
            raise MediaTimelineError("meaningful must be boolean")


@dataclass(frozen=True, slots=True)
class FrameDescriptor:
    event_id: str
    timestamp_seconds: float
    description: str
    exact_sha256: str | None = None
    motion_score: float = 0.0
    scene_change: bool = False
    meaningful: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        object.__setattr__(
            self,
            "timestamp_seconds",
            _number(self.timestamp_seconds, "timestamp_seconds"),
        )
        object.__setattr__(
            self,
            "description",
            _text(self.description, "description"),
        )
        if self.exact_sha256 is not None:
            object.__setattr__(
                self,
                "exact_sha256",
                _sha256(self.exact_sha256, "exact_sha256"),
            )
        motion = _number(self.motion_score, "motion_score")
        if motion > 1.0:
            raise MediaTimelineError("motion_score must not exceed 1")
        object.__setattr__(self, "motion_score", motion)
        if not isinstance(self.scene_change, bool):
            raise MediaTimelineError("scene_change must be boolean")
        if not isinstance(self.meaningful, bool):
            raise MediaTimelineError("meaningful must be boolean")


class TimelineEventKind(str, Enum):
    TRANSCRIPT = "transcript"
    FRAME = "frame"
    UNCHANGED_FRAME_RANGE = "unchanged_frame_range"


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    kind: TimelineEventKind
    start_seconds: float
    end_seconds: float
    first_event_id: str
    last_event_id: str
    text: str
    meaningful: bool
    speaker: str | None = None
    exact_sha256: str | None = None
    sample_count: int = 1


@dataclass(frozen=True, slots=True)
class TimestampWindow:
    index: int
    start_seconds: float
    end_seconds: float
    events: tuple[TimelineEvent, ...]


@dataclass(frozen=True, slots=True)
class TimelinePlan:
    metadata: MediaMetadata
    window_seconds: float
    windows: tuple[TimestampWindow, ...]

    @property
    def events(self) -> tuple[TimelineEvent, ...]:
        return tuple(event for window in self.windows for event in window.events)


@dataclass(frozen=True, slots=True)
class SamplingDecision:
    event_id: str
    observed_at: float
    interval_seconds: float
    next_sample_at: float
    reason: str
    meaningful: bool


@dataclass(frozen=True, slots=True)
class AdaptiveSamplingPlan:
    source: MediaSource
    initial_sample_at: float
    min_interval_seconds: float
    max_interval_seconds: float
    decisions: tuple[SamplingDecision, ...]


_SHA256 = re.compile(r"[0-9a-f]{64}")
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_WINDOWS_PATH = re.compile(r"^[a-z]:[\\/]", re.IGNORECASE)


def parse_ffprobe_metadata(
    source: MediaSource,
    probe: Mapping[str, object],
) -> MediaMetadata:
    """Normalize ffprobe-like data without opening the identified source."""

    if not isinstance(source, MediaSource):
        raise MediaTimelineError("source must be MediaSource")
    if not isinstance(probe, Mapping):
        raise MediaTimelineError("probe metadata must be a mapping")
    format_value = probe.get("format", {})
    if not isinstance(format_value, Mapping):
        raise MediaTimelineError("probe format must be a mapping")
    streams_value = probe.get("streams", ())
    if isinstance(streams_value, (str, bytes)) or not isinstance(
        streams_value, Sequence
    ):
        raise MediaTimelineError("probe streams must be a sequence")
    if len(streams_value) > MAX_STREAMS:
        raise MediaTimelineError(f"probe exceeds {MAX_STREAMS} streams")

    streams = tuple(_parse_stream(item, position) for position, item in enumerate(
        streams_value
    ))
    stream_indices = [stream.index for stream in streams]
    if len(set(stream_indices)) != len(stream_indices):
        raise MediaTimelineError("probe stream indices must be unique")
    format_duration = _optional_number(format_value.get("duration"), "duration")
    stream_durations = [
        stream.duration_seconds
        for stream in streams
        if stream.duration_seconds is not None
    ]
    duration = format_duration
    if duration is None and stream_durations:
        duration = max(stream_durations)
    if duration is None or duration <= 0:
        raise MediaTimelineError("media duration must be supplied and positive")
    if duration > MAX_DURATION_SECONDS:
        raise MediaTimelineError(
            f"media duration exceeds {MAX_DURATION_SECONDS} seconds"
        )
    format_name = _optional_text(format_value.get("format_name"), "format_name", 128)
    byte_size = _optional_integer(format_value.get("size"), "size", MAX_MEDIA_BYTES)
    bit_rate = _optional_integer(format_value.get("bit_rate"), "bit_rate", 10**12)
    return MediaMetadata(
        source=source,
        duration_seconds=duration,
        format_name=format_name,
        byte_size=byte_size,
        bit_rate=bit_rate,
        streams=streams,
    )


def plan_timeline(
    metadata: MediaMetadata,
    *,
    transcripts: Sequence[TranscriptDescriptor] = (),
    frames: Sequence[FrameDescriptor] = (),
    window_seconds: float = 30.0,
) -> TimelinePlan:
    """Build complete ordered windows while retaining all meaningful events."""

    _require_metadata(metadata)
    transcript_values = _descriptor_sequence(
        transcripts,
        TranscriptDescriptor,
        "transcripts",
    )
    frame_values = _descriptor_sequence(frames, FrameDescriptor, "frames")
    if len(transcript_values) + len(frame_values) > MAX_DESCRIPTORS:
        raise MediaTimelineError(
            f"timeline exceeds {MAX_DESCRIPTORS} descriptors"
        )
    window = _number(window_seconds, "window_seconds", positive=True)
    window_count = math.ceil(metadata.duration_seconds / window)
    if window_count > MAX_WINDOWS:
        raise MediaTimelineError(
            f"timeline exceeds {MAX_WINDOWS} timestamp windows"
        )
    _validate_event_ids(transcript_values, frame_values)
    _validate_timestamps(metadata, transcript_values, frame_values)

    events = [_transcript_event(item) for item in transcript_values]
    events.extend(_frame_events(frame_values))
    events.sort(key=_event_order)
    grouped: list[list[TimelineEvent]] = [[] for _ in range(window_count)]
    for event in events:
        index = min(int(event.start_seconds // window), window_count - 1)
        grouped[index].append(event)
    windows = tuple(
        TimestampWindow(
            index=index,
            start_seconds=index * window,
            end_seconds=min((index + 1) * window, metadata.duration_seconds),
            events=tuple(grouped[index]),
        )
        for index in range(window_count)
    )
    return TimelinePlan(metadata, window, windows)


def plan_adaptive_sampling(
    metadata: MediaMetadata,
    frames: Sequence[FrameDescriptor],
    *,
    min_interval_seconds: float = 1.0,
    max_interval_seconds: float = 12.0,
    stable_growth: float = 1.5,
    motion_threshold: float = 0.6,
) -> AdaptiveSamplingPlan:
    """Return one uncapped decision for every caller-supplied frame event."""

    _require_metadata(metadata)
    frame_values = _descriptor_sequence(frames, FrameDescriptor, "frames")
    if len(frame_values) > MAX_DESCRIPTORS:
        raise MediaTimelineError(
            f"sampling exceeds {MAX_DESCRIPTORS} frame descriptors"
        )
    _validate_event_ids((), frame_values)
    _validate_timestamps(metadata, (), frame_values)
    minimum = _number(
        min_interval_seconds,
        "min_interval_seconds",
        positive=True,
    )
    maximum = _number(
        max_interval_seconds,
        "max_interval_seconds",
        positive=True,
    )
    if minimum > maximum:
        raise MediaTimelineError("minimum sample interval exceeds maximum")
    growth = _number(stable_growth, "stable_growth", positive=True)
    if growth <= 1.0:
        raise MediaTimelineError("stable_growth must exceed 1")
    threshold = _number(motion_threshold, "motion_threshold")
    if threshold > 1.0:
        raise MediaTimelineError("motion_threshold must not exceed 1")
    if metadata.video_frame_rate:
        minimum = max(minimum, 1.0 / metadata.video_frame_rate)
    if minimum > maximum:
        maximum = minimum

    interval = minimum
    prior_fingerprint: str | None = None
    decisions: list[SamplingDecision] = []
    for frame in sorted(frame_values, key=_frame_order):
        if frame.meaningful:
            interval = minimum
            reason = "meaningful_event"
        elif frame.scene_change:
            interval = minimum
            reason = "scene_change"
        elif frame.motion_score >= threshold:
            interval = minimum
            reason = "motion"
        elif (
            frame.exact_sha256 is not None
            and frame.exact_sha256 == prior_fingerprint
        ):
            interval = min(maximum, interval * growth)
            reason = "exact_unchanged_frame"
        else:
            interval = max(minimum, interval * 0.75)
            reason = "observed_frame"
        decisions.append(
            SamplingDecision(
                event_id=frame.event_id,
                observed_at=frame.timestamp_seconds,
                interval_seconds=interval,
                next_sample_at=min(
                    metadata.duration_seconds,
                    frame.timestamp_seconds + interval,
                ),
                reason=reason,
                meaningful=frame.meaningful,
            )
        )
        prior_fingerprint = frame.exact_sha256
    return AdaptiveSamplingPlan(
        source=metadata.source,
        initial_sample_at=0.0,
        min_interval_seconds=minimum,
        max_interval_seconds=maximum,
        decisions=tuple(decisions),
    )


def _parse_stream(value: object, position: int) -> MediaStreamMetadata:
    if not isinstance(value, Mapping):
        raise MediaTimelineError("each probe stream must be a mapping")
    index = _integer(value.get("index", position), "stream index", 1_000_000)
    kind = _text(value.get("codec_type", "unknown"), "codec_type", 32).lower()
    codec_name = _optional_text(value.get("codec_name"), "codec_name", 128)
    duration = _optional_number(value.get("duration"), "stream duration")
    if duration is not None and duration > MAX_DURATION_SECONDS:
        raise MediaTimelineError("stream duration exceeds media bound")
    frame_rate = _parse_rate(
        value.get("avg_frame_rate", value.get("r_frame_rate"))
    )
    width = _optional_integer(value.get("width"), "width", MAX_DIMENSION)
    height = _optional_integer(value.get("height"), "height", MAX_DIMENSION)
    sample_rate = _optional_integer(
        value.get("sample_rate"),
        "sample_rate",
        MAX_SAMPLE_RATE,
    )
    channels = _optional_integer(value.get("channels"), "channels", MAX_CHANNELS)
    return MediaStreamMetadata(
        index=index,
        kind=kind,
        codec_name=codec_name,
        duration_seconds=duration,
        frame_rate=frame_rate,
        width=width,
        height=height,
        sample_rate=sample_rate,
        channels=channels,
    )


def _frame_events(frames: Sequence[FrameDescriptor]) -> list[TimelineEvent]:
    ordered = sorted(frames, key=_frame_order)
    events: list[TimelineEvent] = []
    for frame in ordered:
        if (
            events
            and not frame.meaningful
            and frame.exact_sha256 is not None
            and events[-1].kind
            in {TimelineEventKind.FRAME, TimelineEventKind.UNCHANGED_FRAME_RANGE}
            and not events[-1].meaningful
            and events[-1].exact_sha256 == frame.exact_sha256
            and events[-1].text == frame.description
        ):
            previous = events[-1]
            events[-1] = TimelineEvent(
                kind=TimelineEventKind.UNCHANGED_FRAME_RANGE,
                start_seconds=previous.start_seconds,
                end_seconds=frame.timestamp_seconds,
                first_event_id=previous.first_event_id,
                last_event_id=frame.event_id,
                text=frame.description,
                meaningful=False,
                exact_sha256=frame.exact_sha256,
                sample_count=previous.sample_count + 1,
            )
            continue
        events.append(
            TimelineEvent(
                kind=TimelineEventKind.FRAME,
                start_seconds=frame.timestamp_seconds,
                end_seconds=frame.timestamp_seconds,
                first_event_id=frame.event_id,
                last_event_id=frame.event_id,
                text=frame.description,
                meaningful=frame.meaningful,
                exact_sha256=frame.exact_sha256,
            )
        )
    return events


def _transcript_event(item: TranscriptDescriptor) -> TimelineEvent:
    return TimelineEvent(
        kind=TimelineEventKind.TRANSCRIPT,
        start_seconds=item.start_seconds,
        end_seconds=item.end_seconds,
        first_event_id=item.event_id,
        last_event_id=item.event_id,
        text=item.text,
        meaningful=item.meaningful,
        speaker=item.speaker,
    )


def _validate_timestamps(
    metadata: MediaMetadata,
    transcripts: Sequence[TranscriptDescriptor],
    frames: Sequence[FrameDescriptor],
) -> None:
    duration = metadata.duration_seconds
    for item in transcripts:
        if item.end_seconds > duration:
            raise MediaTimelineError(
                f"transcript {item.event_id!r} exceeds media duration"
            )
    for item in frames:
        if item.timestamp_seconds > duration:
            raise MediaTimelineError(
                f"frame {item.event_id!r} exceeds media duration"
            )


def _validate_event_ids(
    transcripts: Sequence[TranscriptDescriptor],
    frames: Sequence[FrameDescriptor],
) -> None:
    identifiers = [item.event_id for item in transcripts]
    identifiers.extend(item.event_id for item in frames)
    if len(set(identifiers)) != len(identifiers):
        raise MediaTimelineError("event_id values must be unique")


def _descriptor_sequence(
    values: Sequence[object],
    expected: type,
    name: str,
) -> tuple:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise MediaTimelineError(f"{name} must be a sequence")
    if any(not isinstance(item, expected) for item in values):
        raise MediaTimelineError(f"{name} contain invalid descriptors")
    return tuple(values)


def _require_metadata(value: object) -> MediaMetadata:
    if not isinstance(value, MediaMetadata):
        raise MediaTimelineError("metadata must be MediaMetadata")
    return value


def _event_order(event: TimelineEvent) -> tuple[float, float, str, str]:
    return (
        event.start_seconds,
        event.end_seconds,
        event.kind.value,
        event.first_event_id,
    )


def _frame_order(frame: FrameDescriptor) -> tuple[float, str]:
    return frame.timestamp_seconds, frame.event_id


def _parse_rate(value: object) -> float | None:
    if value in (None, "", "0/0"):
        return None
    if isinstance(value, str) and "/" in value:
        numerator, denominator = value.split("/", 1)
        top = _number(numerator, "frame rate numerator")
        bottom = _number(denominator, "frame rate denominator", positive=True)
        rate = top / bottom
    else:
        rate = _number(value, "frame_rate", positive=True)
    if not 0 < rate <= 1_000:
        raise MediaTimelineError("frame_rate must be between 0 and 1000")
    return rate


def _identifier(value: object, name: str) -> str:
    result = _text(value, name, MAX_ID_CHARS)
    if (
        _URL.match(result)
        or _WINDOWS_PATH.match(result)
        or result.startswith(("file:", "\\\\", "/"))
    ):
        raise MediaTimelineError(f"{name} must be opaque, not a URL or path")
    return result


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value.lower()) is None:
        raise MediaTimelineError(f"{name} must be a hexadecimal SHA-256 digest")
    return value.lower()


def _text(value: object, name: str, maximum: int = MAX_TEXT_CHARS) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)) or not isinstance(value, str):
        raise MediaTimelineError(f"{name} must be text")
    result = " ".join(value.split())
    if not result:
        raise MediaTimelineError(f"{name} must not be empty")
    if len(result) > maximum:
        raise MediaTimelineError(f"{name} exceeds {maximum} characters")
    return result


def _optional_text(value: object, name: str, maximum: int) -> str | None:
    if value in (None, ""):
        return None
    return _text(value, name, maximum)


def _number(value: object, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise MediaTimelineError(f"{name} must be a finite number")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise MediaTimelineError(f"{name} must be a finite number") from None
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        qualifier = "positive " if positive else "non-negative "
        raise MediaTimelineError(f"{name} must be a finite {qualifier}number")
    return result


def _optional_number(value: object, name: str) -> float | None:
    if value in (None, "", "N/A"):
        return None
    return _number(value, name)


def _integer(value: object, name: str, maximum: int) -> int:
    if isinstance(value, bool):
        raise MediaTimelineError(f"{name} must be a non-negative integer")
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise MediaTimelineError(f"{name} must be a non-negative integer") from None
    if str(value).strip() not in {str(result), f"{result}.0"}:
        raise MediaTimelineError(f"{name} must be a non-negative integer")
    if not 0 <= result <= maximum:
        raise MediaTimelineError(f"{name} exceeds its supported bound")
    return result


def _optional_integer(value: object, name: str, maximum: int) -> int | None:
    if value in (None, "", "N/A"):
        return None
    return _integer(value, name, maximum)


__all__ = [
    "AdaptiveSamplingPlan",
    "FrameDescriptor",
    "MediaMetadata",
    "MediaSource",
    "MediaStreamMetadata",
    "MediaTimelineError",
    "SamplingDecision",
    "TimelineEvent",
    "TimelineEventKind",
    "TimelinePlan",
    "TimestampWindow",
    "TranscriptDescriptor",
    "parse_ffprobe_metadata",
    "plan_adaptive_sampling",
    "plan_timeline",
]
