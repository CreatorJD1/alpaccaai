"""Bounded Discord voice receive helpers for explicitly joined rooms.

Decoded Discord PCM is held in memory only long enough to form one short WAV
utterance. The bridge validates and transcribes that WAV locally, then drops it.
This module never opens a path, contacts Discord, invokes a model, or stores raw
audio/transcripts. The bridge owns the separate encrypted transcript store.
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
MAX_ROOM_SPEAKERS = 8

_dave_compat_lock = threading.Lock()
_dave_stats_lock = threading.Lock()
_dave_compat_mode = "uninitialized"
_dave_stats = {
    "decrypted_packets": 0,
    "passthrough_packets": 0,
    "dropped_packets": 0,
}

VoiceEventStatus = Literal[
    "accepted",
    "transcribed",
    "remembered",
    "no-transcript",
    "dropped",
    "failed",
]


@dataclass(frozen=True, slots=True)
class VoiceUtterance:
    wav_bytes: bytes = field(repr=False)
    pcm_bytes: int
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class SpeakerVoiceUtterance:
    user_id: int
    speaker_name: str
    wav_bytes: bytes = field(repr=False)
    pcm_bytes: int
    duration_seconds: float


def _increment_dave_stat(name: str) -> None:
    with _dave_stats_lock:
        _dave_stats[name] = int(_dave_stats.get(name, 0)) + 1


def dave_receive_status() -> dict[str, object]:
    with _dave_stats_lock:
        stats = dict(_dave_stats)
    return {
        "mode": _dave_compat_mode,
        "ready": _dave_compat_mode in {"native", "patched"},
        **stats,
    }


def _decrypt_dave_packet(decoder, packet, davey_mod) -> str:
    """Decrypt one inbound DAVE frame after transport decryption.

    discord-ext-voice-recv 0.5.2a179 predates Discord.py 2.7's inbound DAVE
    requirement. This is the bounded equivalent of upstream PR #58; it uses
    the DaveSession already maintained by Discord.py and never stores audio.
    """
    payload = getattr(packet, "decrypted_data", None)
    if not packet or not payload:
        return "skipped"
    voice_client = getattr(getattr(decoder, "sink", None), "voice_client", None)
    if voice_client is None:
        return "unavailable"
    user_id = getattr(decoder, "_cached_id", None)
    if user_id is None:
        lookup = getattr(voice_client, "_get_id_from_ssrc", None)
        if callable(lookup):
            user_id = lookup(getattr(decoder, "ssrc", 0))
            if type(user_id) is int and user_id > 0:
                decoder._cached_id = user_id
    if type(user_id) is not int or user_id <= 0:
        return "unmapped"
    state = getattr(voice_client, "_connection", None)
    session = getattr(state, "dave_session", None)
    if (
        session is None
        or not bool(getattr(session, "ready", False))
        or int(getattr(state, "dave_protocol_version", 0) or 0) == 0
    ):
        return "inactive"
    try:
        decrypted = session.decrypt(
            user_id,
            davey_mod.MediaType.audio,
            bytes(payload),
        )
    except Exception:
        # Discord also emits plaintext silence/transition packets. DaveSession
        # rejects those; leaving them unchanged lets Opus handle them normally.
        _increment_dave_stat("passthrough_packets")
        return "passthrough"
    if not isinstance(decrypted, (bytes, bytearray, memoryview)) or not decrypted:
        _increment_dave_stat("passthrough_packets")
        return "passthrough"
    packet.decrypted_data = bytes(decrypted)
    _increment_dave_stat("decrypted_packets")
    return "decrypted"


def _decode_with_opus_guard(decoder, packet, original_decode, opus_error_type):
    try:
        return original_decode(decoder, packet)
    except opus_error_type:
        # One early packet commonly arrives before its SSRC mapping. Drop that
        # frame instead of allowing the alpha extension's router thread to die.
        _increment_dave_stat("dropped_packets")
        return packet, b""


def install_dave_receive_compat() -> bool:
    """Install the reviewed Discord.py 2.7 receive bridge once per process."""
    global _dave_compat_mode
    with _dave_compat_lock:
        try:
            import davey
            from discord.opus import OpusError
            from discord.ext.voice_recv import opus as voice_recv_opus
        except (ImportError, OSError):
            _dave_compat_mode = "unavailable"
            return False

        decoder_type = getattr(voice_recv_opus, "PacketDecoder", None)
        if decoder_type is None:
            _dave_compat_mode = "unavailable"
            return False

        native = callable(getattr(decoder_type, "_dave_decrypt", None))
        if not native and not getattr(decoder_type, "_alpecca_dave_process", False):
            original_process = decoder_type._process_packet

            def process_with_dave(decoder, packet):
                _decrypt_dave_packet(decoder, packet, davey)
                return original_process(decoder, packet)

            process_with_dave.__name__ = original_process.__name__
            process_with_dave.__doc__ = original_process.__doc__
            decoder_type._process_packet = process_with_dave
            decoder_type._alpecca_dave_process = True

        if not getattr(decoder_type, "_alpecca_opus_guard", False):
            original_decode = decoder_type._decode_packet

            def decode_with_guard(decoder, packet):
                return _decode_with_opus_guard(
                    decoder,
                    packet,
                    original_decode,
                    OpusError,
                )

            decode_with_guard.__name__ = original_decode.__name__
            decode_with_guard.__doc__ = original_decode.__doc__
            decoder_type._decode_packet = decode_with_guard
            decoder_type._alpecca_opus_guard = True

        _dave_compat_mode = "native" if native else "patched"
        return True


def receive_readiness(*, enabled: bool) -> dict[str, object]:
    """Return secret-free local dependency posture without loading a model."""
    if type(enabled) is not bool:
        raise TypeError("enabled must be bool")
    extension = importlib.util.find_spec("discord.ext.voice_recv") is not None
    whisper = importlib.util.find_spec("faster_whisper") is not None
    davey = importlib.util.find_spec("davey") is not None
    dave_compat = bool(
        enabled and extension and davey and install_dave_receive_compat()
    )
    ready = enabled and extension and whisper and davey and dave_compat
    return {
        "enabled": enabled,
        "status": "ready" if ready else "unavailable" if enabled else "disabled",
        "scope": "claimed-room-human-participants",
        "processing": "local-only",
        "raw_audio_persistence": "none",
        "max_utterance_seconds": MAX_UTTERANCE_SECONDS,
        "voice_recv": extension,
        "faster_whisper": whisper,
        "davey": davey,
        "dave_receive": dave_receive_status(),
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


class RoomPcmCollector:
    """Bounded per-speaker PCM buffers for one explicitly joined voice room."""

    def __init__(
        self,
        on_utterance: Callable[[SpeakerVoiceUtterance], None],
        *,
        on_speech_start: Callable[[], None] | None = None,
        max_speakers: int = MAX_ROOM_SPEAKERS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(on_utterance):
            raise TypeError("on_utterance must be callable")
        self._on_utterance = on_utterance
        self._on_speech_start = on_speech_start
        self._clock = clock
        self._max_speakers = max(1, min(MAX_ROOM_SPEAKERS, int(max_speakers)))
        self._lock = threading.Lock()
        self._collectors: dict[int, CreatorPcmCollector] = {}
        self._speaker_names: dict[int, str] = {}

    @staticmethod
    def _speaker(user: object) -> tuple[int, str] | None:
        user_id = getattr(user, "id", None)
        if type(user_id) is not int or user_id <= 0 or bool(getattr(user, "bot", False)):
            return None
        name = " ".join(
            str(
                getattr(user, "display_name", None)
                or getattr(user, "name", None)
                or "Discord participant"
            ).split()
        )[:80]
        return user_id, name or "Discord participant"

    def _emit(self, user_id: int, utterance: VoiceUtterance) -> None:
        with self._lock:
            name = self._speaker_names.get(user_id, "Discord participant")
        self._on_utterance(
            SpeakerVoiceUtterance(
                user_id=user_id,
                speaker_name=name,
                wav_bytes=utterance.wav_bytes,
                pcm_bytes=utterance.pcm_bytes,
                duration_seconds=utterance.duration_seconds,
            )
        )

    def _collector_for(self, user: object) -> tuple[int, CreatorPcmCollector] | None:
        speaker = self._speaker(user)
        if speaker is None:
            return None
        user_id, name = speaker
        with self._lock:
            collector = self._collectors.get(user_id)
            if collector is None:
                if len(self._collectors) >= self._max_speakers:
                    return None
                collector = CreatorPcmCollector(
                    user_id,
                    lambda utterance, uid=user_id: self._emit(uid, utterance),
                    on_speech_start=self._on_speech_start,
                    clock=self._clock,
                )
                self._collectors[user_id] = collector
            self._speaker_names[user_id] = name
        return user_id, collector

    def push(self, user: object, pcm: object) -> str:
        resolved = self._collector_for(user)
        if resolved is None:
            return "ignored-user"
        user_id, collector = resolved
        return collector.push(user_id, pcm)

    def finish(self, user: object) -> bool:
        speaker = self._speaker(user)
        if speaker is None:
            return False
        user_id, _name = speaker
        with self._lock:
            collector = self._collectors.get(user_id)
        return bool(collector and collector.finish(user_id))

    def flush_stale(self, *, now: float | None = None) -> int:
        with self._lock:
            collectors = list(self._collectors.values())
        return sum(1 for collector in collectors if collector.flush_stale(now=now))

    def cleanup(self) -> None:
        with self._lock:
            collectors = list(self._collectors.values())
            self._collectors.clear()
            self._speaker_names.clear()
        for collector in collectors:
            collector.cleanup()


def build_sink(collector: CreatorPcmCollector | RoomPcmCollector):
    """Build the optional discord-ext-voice-recv sink lazily."""
    if type(collector) not in {CreatorPcmCollector, RoomPcmCollector}:
        raise TypeError("collector must be CreatorPcmCollector or RoomPcmCollector")
    try:
        from discord.ext import voice_recv
    except (ImportError, OSError) as exc:
        raise RuntimeError("Discord voice receive dependency is unavailable") from exc
    if not install_dave_receive_compat():
        raise RuntimeError("Discord DAVE voice receive compatibility is unavailable")

    class CreatorVoiceSink(voice_recv.AudioSink):
        def __init__(self) -> None:
            super().__init__()

        def wants_opus(self) -> bool:
            return False

        def write(self, user, data) -> None:
            if user is None:
                return
            if type(collector) is RoomPcmCollector:
                collector.push(user, getattr(data, "pcm", None))
            else:
                collector.push(getattr(user, "id", None), getattr(data, "pcm", None))

        @voice_recv.AudioSink.listener()
        def on_voice_member_speaking_stop(self, member) -> None:
            if type(collector) is RoomPcmCollector:
                collector.finish(member)
            else:
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
    if not install_dave_receive_compat():
        raise RuntimeError("Discord DAVE voice receive compatibility is unavailable")
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
        "accepted", "transcribed", "remembered", "no-transcript", "dropped", "failed",
    }:
        raise ValueError("unknown Discord voice event status")
    try:
        return cognition_mod.record_observation(
            cognition_mod.CognitionObservation(
                source="discord_voice",
                content=f"Discord voice utterance was {status}.",
                confidence=1.0,
                room="discord",
                privacy_class="local",
                scope="discord:claimed-room",
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
    "MAX_ROOM_SPEAKERS",
    "MAX_UTTERANCE_PCM_BYTES",
    "MAX_UTTERANCE_SECONDS",
    "MIN_UTTERANCE_SECONDS",
    "PCM_BYTES_PER_SECOND",
    "RoomPcmCollector",
    "SILENCE_FLUSH_SECONDS",
    "SpeakerVoiceUtterance",
    "VoiceUtterance",
    "build_sink",
    "dave_receive_status",
    "install_dave_receive_compat",
    "next_voice_event_id",
    "receive_readiness",
    "record_voice_event",
    "voice_client_class",
]
