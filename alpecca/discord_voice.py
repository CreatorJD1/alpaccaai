"""Bounded Discord voice receive helpers for explicitly joined rooms.

Decoded Discord PCM is held in memory only long enough to form one short WAV
utterance. The bridge validates and transcribes that WAV locally, then drops it.
This module never opens a path, contacts Discord, invokes a model, or stores raw
audio/transcripts. The bridge owns the separate encrypted transcript store.
"""
from __future__ import annotations

import importlib.util
import io
import math
import os
import threading
import time
import wave
from contextvars import ContextVar
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Callable, Literal

from alpecca import cognition as cognition_mod
from alpecca import silero_vad as silero_vad_mod


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
VAD_PRE_ROLL_SECONDS = max(
    0.0,
    min(1.5, float(os.environ.get("ALPECCA_DISCORD_VAD_PRE_ROLL_SECONDS", "0.8"))),
)
VAD_PRE_ROLL_BYTES = int(PCM_BYTES_PER_SECOND * VAD_PRE_ROLL_SECONDS)
VAD_THRESHOLD = max(
    0.05,
    min(0.95, float(os.environ.get("ALPECCA_DISCORD_VAD_THRESHOLD", "0.5"))),
)
VAD_START_FRAMES = max(
    1,
    min(5, int(os.environ.get("ALPECCA_DISCORD_VAD_START_FRAMES", "2"))),
)
VAD_END_FRAMES = max(1, math.ceil(SILENCE_FLUSH_SECONDS / silero_vad_mod.FRAME_SECONDS))

_dave_compat_lock = threading.Lock()
_dave_stats_lock = threading.Lock()
_dave_compat_mode = "uninitialized"
_dave_stats = {
    "decrypted_packets": 0,
    "passthrough_packets": 0,
    "dropped_packets": 0,
}
_vad_runtime_lock = threading.Lock()
_vad_runtime_stats = {
    "detector_failures": 0,
    "packet_fallback_activations": 0,
    "active_packet_fallbacks": 0,
    "last_failure": "",
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


def _activate_vad_fallback(reason: str) -> None:
    with _vad_runtime_lock:
        _vad_runtime_stats["detector_failures"] += 1
        _vad_runtime_stats["packet_fallback_activations"] += 1
        _vad_runtime_stats["active_packet_fallbacks"] += 1
        _vad_runtime_stats["last_failure"] = str(reason or "detector")[:32]


def _release_vad_fallback() -> None:
    with _vad_runtime_lock:
        _vad_runtime_stats["active_packet_fallbacks"] = max(
            0,
            int(_vad_runtime_stats["active_packet_fallbacks"]) - 1,
        )


def _vad_receive_status() -> dict[str, object]:
    posture = dict(silero_vad_mod.readiness())
    with _vad_runtime_lock:
        stats = dict(_vad_runtime_stats)
    configured_status = str(posture.get("status") or "fallback")
    runtime_degraded = int(stats["detector_failures"]) > 0
    posture.update(
        {
            "configured_status": configured_status,
            "status": "degraded" if runtime_degraded else configured_status,
            "detector_failures": int(stats["detector_failures"]),
            "packet_fallback_activations": int(
                stats["packet_fallback_activations"]
            ),
            "active_packet_fallbacks": int(stats["active_packet_fallbacks"]),
            "packet_fallback_available": True,
            "last_failure": str(stats["last_failure"]),
        }
    )
    return posture


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
    vad_status = _vad_receive_status()
    availability_status = (
        "ready" if ready else "unavailable" if enabled else "disabled"
    )
    operational_status = (
        "degraded"
        if ready and vad_status.get("status") != "ready"
        else availability_status
    )
    return {
        "enabled": enabled,
        # ``status`` is transport availability. Packet fallback keeps reception
        # available while ``operational_status`` exposes reduced endpointing.
        "status": availability_status,
        "operational_status": operational_status,
        "degraded": operational_status == "degraded",
        "scope": "claimed-room-human-participants",
        "processing": "local-only",
        "raw_audio_persistence": "none",
        "max_utterance_seconds": MAX_UTTERANCE_SECONDS,
        "voice_recv": extension,
        "faster_whisper": whisper,
        "davey": davey,
        "dave_receive": dave_receive_status(),
        "vad": vad_status,
    }


def silero_vad_factory():
    """Return a per-speaker detector factory or ``None`` for packet fallback."""
    return silero_vad_mod.detector_factory()


def _voice_client_flag(voice_client: object | None, method_name: str) -> bool:
    """Read one Discord voice-client boolean without leaking transport errors."""
    if voice_client is None:
        return False
    method = getattr(voice_client, method_name, None)
    if not callable(method):
        return False
    try:
        return bool(method())
    except Exception:
        return False


def voice_runtime_state(
    *,
    voice_client: object | None,
    voice_enabled: bool,
    output_ready: bool,
    receive_enabled: bool,
    receive_status: Mapping[str, object] | None,
    listener_active: bool,
    transcriber_ready: bool | None,
    speak_allowed: bool = True,
) -> dict[str, object]:
    """Return a content-free, fail-closed snapshot of one Discord voice runtime.

    ``transcriber_ready`` must mean that the local transcriber has already loaded
    successfully. A dependency being installed is deliberately reported as
    ``unverified`` rather than treated as an ability to transcribe.
    """
    connected = _voice_client_flag(voice_client, "is_connected")
    playback_busy = connected and _voice_client_flag(voice_client, "is_playing")
    receive_dependencies_ready = bool(
        receive_status is not None and receive_status.get("status") == "ready"
    )
    receive_capable = bool(
        connected
        and receive_enabled is True
        and receive_dependencies_ready
        and callable(getattr(voice_client, "listen", None))
    )
    transcription_status = (
        "ready"
        if transcriber_ready is True
        else "unavailable"
        if transcriber_ready is False
        else "unverified"
    )
    can_transcribe = receive_capable and transcriber_ready is True
    can_speak = bool(
        connected
        and voice_enabled is True
        and output_ready is True
        and speak_allowed is True
        and callable(getattr(voice_client, "play", None))
    )
    return {
        "connected": connected,
        "can_receive": receive_capable,
        "receiving": receive_capable and listener_active is True,
        "can_transcribe": can_transcribe,
        "transcription_status": transcription_status,
        "can_speak": can_speak,
        "can_speak_now": can_speak and not playback_busy,
        "speaking": can_speak and playback_busy,
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
        vad: object | None = None,
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
        self._vad = vad
        self._vad_fallback_active = False
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._pre_roll = bytearray()
        self._last_packet_at = 0.0
        self._muted_until_stop = False
        self._speech_active = False
        self._positive_frames = 0
        self._negative_frames = 0

    def _reset_vad_locked(self) -> None:
        self._speech_active = False
        self._positive_frames = 0
        self._negative_frames = 0
        self._pre_roll.clear()
        reset = getattr(self._vad, "reset", None)
        if callable(reset):
            try:
                reset()
            except Exception:
                self._degrade_vad_locked("reset")

    def _degrade_vad_locked(self, reason: str) -> None:
        self._vad = None
        self._pre_roll.clear()
        if not self._vad_fallback_active:
            self._vad_fallback_active = True
            _activate_vad_fallback(reason)

    def _append_pre_roll_locked(self, pcm: bytes) -> None:
        if VAD_PRE_ROLL_BYTES <= 0:
            return
        self._pre_roll.extend(pcm)
        overflow = len(self._pre_roll) - VAD_PRE_ROLL_BYTES
        if overflow > 0:
            del self._pre_roll[:overflow]

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
            probabilities: tuple[float, ...] = ()
            if self._vad is not None:
                self._append_pre_roll_locked(pcm)
                try:
                    probabilities = tuple(self._vad.accept_pcm(pcm))
                except Exception:
                    self._degrade_vad_locked("inference")

            if self._vad is not None and not self._speech_active:
                for probability in probabilities:
                    if probability >= VAD_THRESHOLD:
                        self._positive_frames += 1
                    else:
                        self._positive_frames = 0
                    if self._positive_frames >= VAD_START_FRAMES:
                        self._speech_active = True
                        self._negative_frames = 0
                        started = True
                        self._buffer.extend(self._pre_roll)
                        self._pre_roll.clear()
                        break
                self._last_packet_at = self._clock()
                if not self._speech_active:
                    return "vad-waiting"
            elif self._vad is None and not self._buffer:
                started = True

            remaining = MAX_UTTERANCE_PCM_BYTES - len(self._buffer)
            # The activation packet is already present in pre-roll.
            if not (started and self._vad is not None):
                self._buffer.extend(pcm[:remaining])
            self._last_packet_at = self._clock()

            if self._vad is not None and self._speech_active:
                for probability in probabilities:
                    if probability < VAD_THRESHOLD:
                        self._negative_frames += 1
                    else:
                        self._negative_frames = 0
                if self._negative_frames >= VAD_END_FRAMES:
                    completed = bytes(self._buffer)
                    self._buffer.clear()
                    self._reset_vad_locked()

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
            return "emitted-cap" if self._muted_until_stop else "emitted-vad"
        return "buffered"

    def finish(self, user_id: object) -> bool:
        """Finish the creator's current utterance on Discord speaking-stop."""
        if user_id != self.allowed_user_id:
            return False
        with self._lock:
            if self._muted_until_stop:
                self._muted_until_stop = False
                self._last_packet_at = 0.0
                self._reset_vad_locked()
                return False
            completed = bytes(self._buffer)
            self._buffer.clear()
            self._last_packet_at = 0.0
            self._reset_vad_locked()
        return self._emit(completed)

    def flush_stale(self, *, now: float | None = None) -> bool:
        """Fallback segmentation when Discord's speaking-stop event is absent."""
        observed = self._clock() if now is None else float(now)
        with self._lock:
            if (
                not self._buffer and not self._pre_roll
                or self._last_packet_at <= 0.0
                or observed - self._last_packet_at < SILENCE_FLUSH_SECONDS
            ):
                return False
            completed = bytes(self._buffer)
            self._buffer.clear()
            self._last_packet_at = 0.0
            self._reset_vad_locked()
        return self._emit(completed)

    def cleanup(self) -> None:
        """Discard all in-memory PCM without emitting a partial utterance."""
        with self._lock:
            self._buffer.clear()
            self._pre_roll.clear()
            self._last_packet_at = 0.0
            self._muted_until_stop = False
            self._reset_vad_locked()
            if self._vad_fallback_active:
                self._vad_fallback_active = False
                _release_vad_fallback()

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
        vad_factory: Callable[[], object] | None = None,
        max_speakers: int = MAX_ROOM_SPEAKERS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(on_utterance):
            raise TypeError("on_utterance must be callable")
        self._on_utterance = on_utterance
        self._on_speech_start = on_speech_start
        self._vad_factory = vad_factory
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
                    vad=self._vad_factory() if self._vad_factory is not None else None,
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
_active_voice_event_id: ContextVar[str | None] = ContextVar(
    "discord_voice_event_id",
    default=None,
)


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
        event_id = str(candidate)
        _active_voice_event_id.set(event_id)
        return event_id


def _validated_voice_event_id(event_id: str | None) -> str | None:
    if event_id is None:
        return None
    if type(event_id) is not str or not event_id.isascii() or not event_id.isdigit():
        raise ValueError("event_id must be a positive uint64 string")
    value = int(event_id)
    if value <= 0 or value >= (1 << 64) or str(value) != event_id:
        raise ValueError("event_id must be a positive uint64 string")
    return event_id


def record_voice_event(
    status: VoiceEventStatus,
    *,
    event_id: str | None = None,
    duration_seconds: float = 0.0,
    size_bytes: int = 0,
    reason: str = "",
) -> int | None:
    """Write content-free Discord voice evidence into the cognition ledger."""
    if status not in {
        "accepted", "transcribed", "remembered", "no-transcript", "dropped", "failed",
    }:
        raise ValueError("unknown Discord voice event status")
    resolved_event_id = _validated_voice_event_id(
        event_id if event_id is not None else _active_voice_event_id.get()
    )
    metadata: dict[str, object] = {
        "event": "discord_voice",
        "status": status,
        "duration_seconds": round(max(0.0, float(duration_seconds)), 3),
        "size_bytes": max(0, int(size_bytes)),
        "reason": str(reason or "")[:48],
        "processing": "local-only",
        "raw_audio_persisted": False,
    }
    if resolved_event_id is not None:
        metadata["voice_event_id"] = resolved_event_id
    try:
        return cognition_mod.record_observation(
            cognition_mod.CognitionObservation(
                source="discord_voice",
                content=f"Discord voice utterance was {status}.",
                confidence=1.0,
                room="discord",
                privacy_class="local",
                scope="discord:claimed-room",
                metadata=metadata,
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
    "VAD_END_FRAMES",
    "VAD_PRE_ROLL_BYTES",
    "VAD_START_FRAMES",
    "VAD_THRESHOLD",
    "SpeakerVoiceUtterance",
    "VoiceUtterance",
    "build_sink",
    "dave_receive_status",
    "install_dave_receive_compat",
    "next_voice_event_id",
    "receive_readiness",
    "silero_vad_factory",
    "record_voice_event",
    "voice_runtime_state",
    "voice_client_class",
]
