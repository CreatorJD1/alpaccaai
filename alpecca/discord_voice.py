"""Bounded, creator-only Discord voice receive helpers.

Decoded Discord PCM is held in memory only long enough to form one short WAV
utterance. The bridge validates and transcribes that WAV locally, then drops it.
This module never opens a path, contacts Discord, invokes a model, or stores raw
audio/transcripts.
"""
from __future__ import annotations

import importlib.util
import io
import threading
import time
import wave
from dataclasses import dataclass, field
from typing import Callable, Literal

from alpecca import cognition as cognition_mod


PCM_SAMPLE_RATE = 48_000
PCM_CHANNELS = 2
PCM_SAMPLE_WIDTH = 2
PCM_BYTES_PER_SECOND = PCM_SAMPLE_RATE * PCM_CHANNELS * PCM_SAMPLE_WIDTH
MIN_UTTERANCE_SECONDS = 0.35
MAX_UTTERANCE_SECONDS = 12.0
MAX_UTTERANCE_PCM_BYTES = int(PCM_BYTES_PER_SECOND * MAX_UTTERANCE_SECONDS)
MAX_PCM_PACKET_BYTES = int(PCM_BYTES_PER_SECOND * 0.2)
SILENCE_FLUSH_SECONDS = 0.7

VoiceEventStatus = Literal[
    "accepted",
    "transcribed",
    "no-transcript",
    "dropped",
    "failed",
]


@dataclass(frozen=True, slots=True)
class VoiceUtterance:
    wav_bytes: bytes = field(repr=False)
    pcm_bytes: int
    duration_seconds: float


def receive_readiness(*, enabled: bool) -> dict[str, object]:
    """Return secret-free local dependency posture without loading a model."""
    if type(enabled) is not bool:
        raise TypeError("enabled must be bool")
    extension = importlib.util.find_spec("discord.ext.voice_recv") is not None
    whisper = importlib.util.find_spec("faster_whisper") is not None
    ready = enabled and extension and whisper
    return {
        "enabled": enabled,
        "status": "ready" if ready else "unavailable" if enabled else "disabled",
        "scope": "creator-only",
        "processing": "local-only",
        "raw_audio_persistence": "none",
        "max_utterance_seconds": MAX_UTTERANCE_SECONDS,
        "voice_recv": extension,
        "faster_whisper": whisper,
    }


def _pcm_to_wav(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(PCM_CHANNELS)
        writer.setsampwidth(PCM_SAMPLE_WIDTH)
        writer.setframerate(PCM_SAMPLE_RATE)
        writer.writeframes(pcm)
    return output.getvalue()


class CreatorPcmCollector:
    """Thread-safe PCM collector that ignores every non-creator packet."""

    def __init__(
        self,
        allowed_user_id: int,
        on_utterance: Callable[[VoiceUtterance], None],
        *,
        on_speech_start: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(allowed_user_id) is not int or allowed_user_id <= 0:
            raise ValueError("allowed_user_id must be a positive integer")
        if not callable(on_utterance):
            raise TypeError("on_utterance must be callable")
        self.allowed_user_id = allowed_user_id
        self._on_utterance = on_utterance
        self._on_speech_start = on_speech_start
        self._clock = clock
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._last_packet_at = 0.0
        self._muted_until_stop = False

    def push(self, user_id: object, pcm: object) -> str:
        """Accept one decoded PCM packet and return a content-free disposition."""
        if user_id != self.allowed_user_id:
            return "ignored-user"
        if (
            type(pcm) is not bytes
            or not pcm
            or len(pcm) > MAX_PCM_PACKET_BYTES
            or len(pcm) % (PCM_CHANNELS * PCM_SAMPLE_WIDTH) != 0
        ):
            return "invalid-packet"

        started = False
        completed: bytes | None = None
        with self._lock:
            if self._muted_until_stop:
                return "capped"
            if not self._buffer:
                started = True
            remaining = MAX_UTTERANCE_PCM_BYTES - len(self._buffer)
            self._buffer.extend(pcm[:remaining])
            self._last_packet_at = self._clock()
            if len(self._buffer) >= MAX_UTTERANCE_PCM_BYTES:
                completed = bytes(self._buffer)
                self._buffer.clear()
                self._muted_until_stop = True

        if started and self._on_speech_start is not None:
            try:
                self._on_speech_start()
            except Exception:
                pass
        if completed is not None:
            self._emit(completed)
            return "emitted-cap"
        return "buffered"

    def finish(self, user_id: object) -> bool:
        """Finish the creator's current utterance on Discord speaking-stop."""
        if user_id != self.allowed_user_id:
            return False
        with self._lock:
            if self._muted_until_stop:
                self._muted_until_stop = False
                self._last_packet_at = 0.0
                return False
            completed = bytes(self._buffer)
            self._buffer.clear()
            self._last_packet_at = 0.0
        return self._emit(completed)

    def flush_stale(self, *, now: float | None = None) -> bool:
        """Fallback segmentation when Discord's speaking-stop event is absent."""
        observed = self._clock() if now is None else float(now)
        with self._lock:
            if (
                not self._buffer
                or self._last_packet_at <= 0.0
                or observed - self._last_packet_at < SILENCE_FLUSH_SECONDS
            ):
                return False
            completed = bytes(self._buffer)
            self._buffer.clear()
            self._last_packet_at = 0.0
        return self._emit(completed)

    def cleanup(self) -> None:
        """Discard all in-memory PCM without emitting a partial utterance."""
        with self._lock:
            self._buffer.clear()
            self._last_packet_at = 0.0
            self._muted_until_stop = False

    def _emit(self, pcm: bytes) -> bool:
        duration = len(pcm) / PCM_BYTES_PER_SECOND
        if duration < MIN_UTTERANCE_SECONDS:
            return False
        utterance = VoiceUtterance(
            wav_bytes=_pcm_to_wav(pcm),
            pcm_bytes=len(pcm),
            duration_seconds=duration,
        )
        try:
            self._on_utterance(utterance)
        except Exception:
            return False
        return True


def build_sink(collector: CreatorPcmCollector):
    """Build the optional discord-ext-voice-recv sink lazily."""
    if type(collector) is not CreatorPcmCollector:
        raise TypeError("collector must be CreatorPcmCollector")
    try:
        from discord.ext import voice_recv
    except (ImportError, OSError) as exc:
        raise RuntimeError("Discord voice receive dependency is unavailable") from exc

    class CreatorVoiceSink(voice_recv.AudioSink):
        def __init__(self) -> None:
            super().__init__()

        def wants_opus(self) -> bool:
            return False

        def write(self, user, data) -> None:
            if user is None:
                return
            collector.push(getattr(user, "id", None), getattr(data, "pcm", None))

        @voice_recv.AudioSink.listener()
        def on_voice_member_speaking_stop(self, member) -> None:
            collector.finish(getattr(member, "id", None))

        def cleanup(self) -> None:
            collector.cleanup()

    return CreatorVoiceSink()


def voice_client_class():
    """Return the optional receive-capable VoiceClient class."""
    try:
        from discord.ext import voice_recv
    except (ImportError, OSError) as exc:
        raise RuntimeError("Discord voice receive dependency is unavailable") from exc
    return voice_recv.VoiceRecvClient


_event_lock = threading.Lock()
_last_event_id = 0


def next_voice_event_id(*, time_ns: int | None = None) -> str:
    """Mint a unique uint64 transport event id for a voice utterance."""
    global _last_event_id
    candidate = time.time_ns() if time_ns is None else time_ns
    if type(candidate) is not int or candidate <= 0 or candidate >= (1 << 64):
        raise ValueError("time_ns must fit a positive uint64")
    with _event_lock:
        candidate = max(candidate, _last_event_id + 1)
        if candidate >= (1 << 64):
            raise RuntimeError("Discord voice event id space is exhausted")
        _last_event_id = candidate
        return str(candidate)


def record_voice_event(
    status: VoiceEventStatus,
    *,
    duration_seconds: float = 0.0,
    size_bytes: int = 0,
    reason: str = "",
) -> int | None:
    """Write content-free Discord voice evidence into the cognition ledger."""
    if status not in {
        "accepted", "transcribed", "no-transcript", "dropped", "failed",
    }:
        raise ValueError("unknown Discord voice event status")
    try:
        return cognition_mod.record_observation(
            cognition_mod.CognitionObservation(
                source="discord_voice",
                content=f"Discord creator voice utterance was {status}.",
                confidence=1.0,
                room="discord",
                privacy_class="local",
                scope="creator:discord",
                metadata={
                    "event": "discord_voice",
                    "status": status,
                    "duration_seconds": round(max(0.0, float(duration_seconds)), 3),
                    "size_bytes": max(0, int(size_bytes)),
                    "reason": str(reason or "")[:48],
                    "processing": "local-only",
                    "raw_audio_persisted": False,
                },
            )
        )
    except Exception:
        return None


__all__ = [
    "CreatorPcmCollector",
    "MAX_UTTERANCE_PCM_BYTES",
    "MAX_UTTERANCE_SECONDS",
    "MIN_UTTERANCE_SECONDS",
    "PCM_BYTES_PER_SECOND",
    "SILENCE_FLUSH_SECONDS",
    "VoiceUtterance",
    "build_sink",
    "next_voice_event_id",
    "receive_readiness",
    "record_voice_event",
    "voice_client_class",
]
