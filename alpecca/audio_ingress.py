"""Pure, bounded local ingress validation for raw audio bytes.

The guard accepts only already-provided ``bytes``. It never opens a path,
contacts a network service, writes to disk, or invokes a model. Successful
results retain audio bytes only in memory for a later local consumer; their
serializable form is metadata from the scoped attachment envelope.
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
import hashlib
import io
import math
from typing import Any, Literal
import wave

from alpecca.attachment_perception import (
    AttachmentEnvelopeRejected,
    AttachmentPerceptionEnvelope,
    AttachmentRejectionReason,
    create_attachment_envelope,
)


MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_AUDIO_DURATION_SECONDS = 60.0

AudioMimeType = Literal["audio/webm", "audio/ogg", "audio/wav", "audio/x-wav"]
_SUPPORTED_AUDIO_MIMES = frozenset({
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
})
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"
_OGG_MAGIC = b"OggS"

AudioIngressRejectionReason = (
    Literal[
        "invalid-bytes",
        "unsupported-mime",
        "mime-mismatch",
        "malformed-audio",
        "duration-unavailable",
        "duration-limit",
    ]
    | AttachmentRejectionReason
)


class AudioIngressRejected(ValueError):
    """A stable fail-closed rejection for untrusted audio ingress."""

    def __init__(self, reason: AudioIngressRejectionReason, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: AudioIngressRejectionReason, message: str) -> None:
    raise AudioIngressRejected(reason, message)


def _effective_max_bytes(value: int) -> int:
    """Permit a caller to tighten, but never raise, the hard ingress cap."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("max_bytes must be a positive integer")
    return min(value, MAX_AUDIO_BYTES)


def _normalize_declared_mime(value: object) -> AudioMimeType:
    if not isinstance(value, str):
        _reject("unsupported-mime", "declared MIME type is not supported")
    mime_type = value.strip().lower()
    if mime_type not in _SUPPORTED_AUDIO_MIMES:
        _reject("unsupported-mime", "declared MIME type is not supported")
    return mime_type  # type: ignore[return-value]


def _require_matching_magic(audio_bytes: bytes, mime_type: AudioMimeType) -> None:
    if mime_type == "audio/webm":
        matched = audio_bytes.startswith(_EBML_MAGIC)
    elif mime_type == "audio/ogg":
        matched = audio_bytes.startswith(_OGG_MAGIC)
    else:
        matched = (
            len(audio_bytes) >= 12
            and audio_bytes[:4] == b"RIFF"
            and audio_bytes[8:12] == b"WAVE"
        )
    if not matched:
        _reject("mime-mismatch", "declared MIME type does not match audio bytes")


def _validated_duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _reject("duration-unavailable", "audio duration is unavailable")
    duration = float(value)
    if not math.isfinite(duration) or duration <= 0.0:
        _reject("malformed-audio", "audio duration is invalid")
    if duration > MAX_AUDIO_DURATION_SECONDS:
        _reject("duration-limit", "audio duration exceeds the 60-second limit")
    return duration


def _wav_duration(audio_bytes: bytes) -> float:
    """Measure RIFF/WAVE duration from bounded in-memory bytes only."""
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as reader:
            frame_count = reader.getnframes()
            frame_rate = reader.getframerate()
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            frame_size = channels * sample_width
            expected_data_bytes = frame_count * frame_size
            if (
                frame_count <= 0
                or frame_rate <= 0
                or frame_size <= 0
                or expected_data_bytes > len(audio_bytes)
            ):
                _reject("malformed-audio", "RIFF/WAVE audio has invalid frame metadata")
            reader.setpos(frame_count - 1)
            if len(reader.readframes(1)) != frame_size:
                _reject("malformed-audio", "RIFF/WAVE audio data is truncated")
    except (EOFError, OSError, ValueError, wave.Error):
        _reject("malformed-audio", "RIFF/WAVE audio could not be parsed")
    return _validated_duration(frame_count / frame_rate)


def _optional_av_module() -> Any | None:
    """Return PyAV when locally available without making it a dependency."""
    try:
        import av
    except (ImportError, OSError):
        return None
    return av


def _stream_duration_seconds(stream: object) -> float | None:
    duration = getattr(stream, "duration", None)
    time_base = getattr(stream, "time_base", None)
    if duration is None or time_base is None:
        return None
    try:
        return float(duration * time_base)
    except (TypeError, ValueError, OverflowError):
        return None


def _container_duration_seconds(container: object, av_module: Any) -> float | None:
    streams = tuple(getattr(container, "streams", ()) or ())
    audio_streams = tuple(
        stream for stream in streams if getattr(stream, "type", None) == "audio"
    )
    if not audio_streams:
        _reject("malformed-audio", "container does not contain an audio stream")

    duration = getattr(container, "duration", None)
    if duration is not None:
        time_base = getattr(av_module, "time_base", None)
        try:
            return float(duration / time_base)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            return None

    for stream in audio_streams:
        stream_duration = _stream_duration_seconds(stream)
        if stream_duration is not None:
            return stream_duration
    return None


def _optional_container_duration(
    audio_bytes: bytes,
    mime_type: Literal["audio/webm", "audio/ogg"],
) -> float:
    """Use PyAV only against a ``BytesIO`` buffer and never decode media."""
    av_module = _optional_av_module()
    if av_module is None:
        _reject("duration-unavailable", "local WebM/Ogg duration probing is unavailable")

    container = None
    try:
        container_format = "webm" if mime_type == "audio/webm" else "ogg"
        container = av_module.open(
            io.BytesIO(audio_bytes),
            mode="r",
            format=container_format,
        )
        duration = _container_duration_seconds(container, av_module)
    except AudioIngressRejected:
        raise
    except Exception:
        _reject("malformed-audio", "audio container could not be parsed")
    finally:
        if container is not None:
            try:
                container.close()
            except Exception:
                pass

    if duration is None:
        _reject("duration-unavailable", "audio duration is unavailable")
    return _validated_duration(duration)


def _measure_duration(audio_bytes: bytes, mime_type: AudioMimeType) -> float:
    if mime_type in {"audio/wav", "audio/x-wav"}:
        return _wav_duration(audio_bytes)
    return _optional_container_duration(audio_bytes, mime_type)


def _create_envelope(
    *,
    scope: str,
    authorized_scopes: Collection[str],
    source: str,
    mime_type: AudioMimeType,
    audio_bytes: bytes,
    duration_seconds: float,
) -> AttachmentPerceptionEnvelope:
    try:
        return create_attachment_envelope(
            scope=scope,
            authorized_scopes=authorized_scopes,
            source=source,
            mime_type=mime_type,
            attachment_type="audio",
            sha256=hashlib.sha256(audio_bytes).hexdigest(),
            size_bytes=len(audio_bytes),
            duration_seconds=duration_seconds,
            processing_location="local-only",
            cloud_egress="denied",
        )
    except AttachmentEnvelopeRejected as exc:
        raise AudioIngressRejected(exc.reason, str(exc)) from None


@dataclass(frozen=True, slots=True)
class AudioIngress:
    """Immutable in-memory audio plus its local-only perception envelope."""

    audio_bytes: bytes = field(repr=False)
    envelope: AttachmentPerceptionEnvelope

    @property
    def mime_type(self) -> str:
        return self.envelope.mime_type

    @property
    def duration_seconds(self) -> float:
        assert self.envelope.duration_seconds is not None
        return self.envelope.duration_seconds

    def as_dict(self) -> dict[str, object]:
        """Return serializable metadata without raw audio bytes."""
        return self.envelope.as_dict()


def inspect_audio_bytes(
    audio_bytes: bytes,
    *,
    scope: str,
    authorized_scopes: Collection[str],
    source: str,
    declared_mime_type: str,
    max_bytes: int = MAX_AUDIO_BYTES,
) -> AudioIngress:
    """Validate one raw in-memory audio payload for local scoped perception.

    ``declared_mime_type`` is mandatory and must match the corresponding
    container magic. No file path, URL, caller-supplied hash, network call, or
    disk operation is accepted by this entry point.
    """
    maximum = _effective_max_bytes(max_bytes)
    if not isinstance(audio_bytes, bytes) or not audio_bytes:
        _reject("invalid-bytes", "audio bytes must be a nonempty bytes value")
    if len(audio_bytes) > maximum:
        _reject("size-limit", "audio bytes exceed the byte limit")

    mime_type = _normalize_declared_mime(declared_mime_type)
    _require_matching_magic(audio_bytes, mime_type)
    duration_seconds = _measure_duration(audio_bytes, mime_type)
    envelope = _create_envelope(
        scope=scope,
        authorized_scopes=authorized_scopes,
        source=source,
        mime_type=mime_type,
        audio_bytes=audio_bytes,
        duration_seconds=duration_seconds,
    )
    return AudioIngress(audio_bytes=audio_bytes, envelope=envelope)


ingest_audio = inspect_audio_bytes


__all__ = [
    "AudioIngress",
    "AudioIngressRejected",
    "AudioIngressRejectionReason",
    "AudioMimeType",
    "MAX_AUDIO_BYTES",
    "MAX_AUDIO_DURATION_SECONDS",
    "ingest_audio",
    "inspect_audio_bytes",
]
