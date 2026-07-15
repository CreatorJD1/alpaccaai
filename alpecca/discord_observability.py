"""Content-free, fail-closed Discord voice runtime evidence."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import copy
import threading
import time


SCHEMA = "alpecca.discord.voice-observability.v1"

READINESS_STATUSES = frozenset({
    "ready",
    "unavailable",
    "unverified",
    "disabled",
})
ALLOWLIST_STATUSES = frozenset({"ready", "unresolved", "missing"})
TTS_ENGINES = frozenset({"auto", "kokoro", "f5", "f5-tts"})
RECEIVE_OUTCOMES = frozenset({
    "never",
    "listener_started",
    "listener_stopped",
    "decoder_not_authorized",
    "dependencies_unavailable",
    "room_unavailable",
    "connection_unavailable",
    "queue_full",
    "invalid_audio",
    "audit_unavailable",
    "no_transcript",
    "transcribed",
    "encrypted_memory_failed",
    "backend_failed",
    "empty_reply",
    "discord_send_failed",
    "reply_sent",
    "listener_failed",
})
SEND_OUTCOMES = frozenset({
    "never",
    "not_connected",
    "synthesis_unavailable",
    "busy",
    "playback_failed",
    "playback_started",
})
_UNAVAILABLE_REASONS = frozenset({
    "bridge-unavailable",
    "provider-unavailable",
    "invalid-response",
})
_GATE_STATUSES = frozenset({
    "ready",
    "blocked",
    "disabled",
    "unavailable",
    "unverified",
    "unresolved",
    "missing",
    "unknown",
})


def _bounded_count(value: object, name: str) -> int:
    if type(value) is not int or value < 0 or value > 1_000_000:
        raise ValueError(f"{name} must be a bounded non-negative integer")
    return value


def _readiness(value: object, name: str) -> str:
    if type(value) is not str or value not in READINESS_STATUSES:
        raise ValueError(f"{name} has an invalid readiness status")
    return value


def _gate(enabled: bool, status: str) -> str:
    if not enabled:
        return "disabled"
    return "ready" if status == "ready" else status


class DiscordVoiceEvidence:
    """Thread-safe runtime facts and bounded last-outcome evidence."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._clock = clock
        self._lock = threading.Lock()
        self._gateway_logged_in = False
        self._outcomes: dict[str, dict[str, object]] = {
            "receive": {"status": "never", "at_unix": None},
            "send": {"status": "never", "at_unix": None},
        }

    def set_gateway_logged_in(self, value: bool) -> None:
        if type(value) is not bool:
            raise TypeError("gateway state must be bool")
        with self._lock:
            self._gateway_logged_in = value

    def record_outcome(
        self,
        direction: str,
        status: str,
        *,
        at_unix: int | None = None,
    ) -> None:
        allowed = RECEIVE_OUTCOMES if direction == "receive" else SEND_OUTCOMES
        if direction not in {"receive", "send"}:
            raise ValueError("direction must be receive or send")
        if type(status) is not str or status not in allowed:
            raise ValueError("voice outcome is not allowlisted")
        observed = int(self._clock()) if at_unix is None else at_unix
        if type(observed) is not int or observed < 0:
            raise ValueError("at_unix must be a non-negative integer")
        with self._lock:
            self._outcomes[direction] = {
                "status": status,
                "at_unix": observed,
            }

    def snapshot(
        self,
        *,
        claimed_room_count: int,
        voice_output_enabled: bool,
        voice_output_dependency_status: str,
        voice_receiver_enabled: bool,
        voice_receiver_dependency_status: str,
        connected_guild_count: int,
        connected_channel_count: int,
        active_listener_count: int,
        allowlist_status: str,
        allowlist_configured_count: int,
        allowlist_resolved_count: int,
        transcription_status: str,
        tts_engine: str,
        tts_status: str,
        f5_worker_status: str,
    ) -> dict[str, object]:
        """Build one exact-schema snapshot from content-free runtime facts."""

        if type(voice_output_enabled) is not bool:
            raise TypeError("voice_output_enabled must be bool")
        if type(voice_receiver_enabled) is not bool:
            raise TypeError("voice_receiver_enabled must be bool")
        output_status = _readiness(
            voice_output_dependency_status,
            "voice_output_dependency_status",
        )
        receiver_status = _readiness(
            voice_receiver_dependency_status,
            "voice_receiver_dependency_status",
        )
        transcription = _readiness(transcription_status, "transcription_status")
        tts = _readiness(tts_status, "tts_status")
        f5 = _readiness(f5_worker_status, "f5_worker_status")
        if type(allowlist_status) is not str or allowlist_status not in ALLOWLIST_STATUSES:
            raise ValueError("allowlist_status is invalid")
        if type(tts_engine) is not str or tts_engine not in TTS_ENGINES:
            raise ValueError("tts_engine is invalid")

        rooms = _bounded_count(claimed_room_count, "claimed_room_count")
        connected_guilds = _bounded_count(
            connected_guild_count,
            "connected_guild_count",
        )
        connected_channels = _bounded_count(
            connected_channel_count,
            "connected_channel_count",
        )
        listeners = _bounded_count(active_listener_count, "active_listener_count")
        allow_configured = _bounded_count(
            allowlist_configured_count,
            "allowlist_configured_count",
        )
        allow_resolved = _bounded_count(
            allowlist_resolved_count,
            "allowlist_resolved_count",
        )
        if allow_resolved > allow_configured:
            raise ValueError("resolved allowlist count exceeds configured count")

        with self._lock:
            gateway_logged_in = self._gateway_logged_in
            outcomes = copy.deepcopy(self._outcomes)

        effective_tts = (
            "ready"
            if outcomes["send"]["status"] == "playback_started"
            else tts
        )
        gates = {
            "gateway": "ready" if gateway_logged_in else "blocked",
            "claimed_room": "ready" if rooms > 0 else "blocked",
            "voice_connected": (
                "ready"
                if connected_guilds > 0 and connected_channels > 0
                else "blocked"
            ),
            "voice_output": _gate(voice_output_enabled, output_status),
            "receiver_dependency": _gate(voice_receiver_enabled, receiver_status),
            "listener": "ready" if listeners > 0 else "blocked",
            "creator_decoder_allowlist": allowlist_status,
            "local_transcription": transcription,
            "local_tts": effective_tts,
        }
        gates_ready = all(value == "ready" for value in gates.values())
        receive_proven = outcomes["receive"]["status"] == "reply_sent"
        send_proven = outcomes["send"]["status"] == "playback_started"
        live_ready = gates_ready and receive_proven and send_proven
        live_status = (
            "live-proven"
            if live_ready
            else "awaiting-live-evidence"
            if gates_ready
            else "blocked"
        )

        return {
            "schema": SCHEMA,
            "available": True,
            "gateway": {
                "logged_in": gateway_logged_in,
                "status": "logged-in" if gateway_logged_in else "disconnected",
            },
            "claimed_rooms": {"count": rooms},
            "voice_output": {
                "enabled": voice_output_enabled,
                "dependency_status": output_status,
            },
            "voice_receiver": {
                "enabled": voice_receiver_enabled,
                "dependency_status": receiver_status,
                "active_listener_count": listeners,
            },
            "connections": {
                "guild_count": connected_guilds,
                "channel_count": connected_channels,
            },
            "creator_decoder_allowlist": {
                "status": allowlist_status,
                "configured_count": allow_configured,
                "resolved_count": allow_resolved,
            },
            "transcription": {
                "status": transcription,
                "processing": "local-only",
            },
            "tts": {
                "configured_engine": tts_engine,
                "status": effective_tts,
                "f5_worker_status": f5,
                "processing": "local-only",
            },
            "outcomes": outcomes,
            "live_duplex": {
                "ready": live_ready,
                "status": live_status,
                "gates_ready": gates_ready,
                "gates": gates,
                "receive_proven": receive_proven,
                "send_proven": send_proven,
            },
        }


def unavailable_status(reason: str = "bridge-unavailable") -> dict[str, object]:
    """Return an exact-schema fail-closed result when no live provider answers."""

    if type(reason) is not str or reason not in _UNAVAILABLE_REASONS:
        raise ValueError("unavailable status reason is invalid")
    unknown_gates = {
        "gateway": "unknown",
        "claimed_room": "unknown",
        "voice_connected": "unknown",
        "voice_output": "unknown",
        "receiver_dependency": "unknown",
        "listener": "unknown",
        "creator_decoder_allowlist": "unknown",
        "local_transcription": "unknown",
        "local_tts": "unknown",
    }
    return {
        "schema": SCHEMA,
        "available": False,
        "reason": reason,
        "gateway": {"logged_in": False, "status": "unknown"},
        "claimed_rooms": {"count": 0},
        "voice_output": {"enabled": None, "dependency_status": "unknown"},
        "voice_receiver": {
            "enabled": None,
            "dependency_status": "unknown",
            "active_listener_count": 0,
        },
        "connections": {"guild_count": 0, "channel_count": 0},
        "creator_decoder_allowlist": {
            "status": "unknown",
            "configured_count": 0,
            "resolved_count": 0,
        },
        "transcription": {"status": "unknown", "processing": "local-only"},
        "tts": {
            "configured_engine": "unknown",
            "status": "unknown",
            "f5_worker_status": "unknown",
            "processing": "local-only",
        },
        "outcomes": {
            "receive": {"status": "never", "at_unix": None},
            "send": {"status": "never", "at_unix": None},
        },
        "live_duplex": {
            "ready": False,
            "status": "unavailable",
            "gates_ready": False,
            "gates": unknown_gates,
            "receive_proven": False,
            "send_proven": False,
        },
    }


_provider_lock = threading.Lock()
_provider: Callable[[], Mapping[str, object]] | None = None


def register_status_provider(provider: Callable[[], Mapping[str, object]]) -> None:
    """Replace the in-process provider used by the loopback control socket."""

    if not callable(provider):
        raise TypeError("status provider must be callable")
    global _provider
    with _provider_lock:
        _provider = provider


def clear_status_provider() -> None:
    global _provider
    with _provider_lock:
        _provider = None


def _validate_live_status(payload: object) -> dict[str, object]:
    """Reject provider payloads that are not produced by the exact schema."""

    if type(payload) is not dict or payload.get("schema") != SCHEMA:
        raise ValueError("voice status schema is invalid")
    expected_top = {
        "schema",
        "available",
        "gateway",
        "claimed_rooms",
        "voice_output",
        "voice_receiver",
        "connections",
        "creator_decoder_allowlist",
        "transcription",
        "tts",
        "outcomes",
        "live_duplex",
    }
    if set(payload) != expected_top or payload.get("available") is not True:
        raise ValueError("voice status fields are invalid")

    nested_keys = {
        "gateway": {"logged_in", "status"},
        "claimed_rooms": {"count"},
        "voice_output": {"enabled", "dependency_status"},
        "voice_receiver": {
            "enabled",
            "dependency_status",
            "active_listener_count",
        },
        "connections": {"guild_count", "channel_count"},
        "creator_decoder_allowlist": {
            "status",
            "configured_count",
            "resolved_count",
        },
        "transcription": {"status", "processing"},
        "tts": {"configured_engine", "status", "f5_worker_status", "processing"},
        "outcomes": {"receive", "send"},
        "live_duplex": {
            "ready",
            "status",
            "gates_ready",
            "gates",
            "receive_proven",
            "send_proven",
        },
    }
    for name, keys in nested_keys.items():
        value = payload.get(name)
        if type(value) is not dict or set(value) != keys:
            raise ValueError(f"voice status {name} fields are invalid")

    gateway = payload["gateway"]
    if type(gateway["logged_in"]) is not bool or gateway["status"] not in {
        "logged-in",
        "disconnected",
    }:
        raise ValueError("gateway status is invalid")
    for parent, key in (
        ("claimed_rooms", "count"),
        ("voice_receiver", "active_listener_count"),
        ("connections", "guild_count"),
        ("connections", "channel_count"),
        ("creator_decoder_allowlist", "configured_count"),
        ("creator_decoder_allowlist", "resolved_count"),
    ):
        _bounded_count(payload[parent][key], f"{parent}.{key}")
    if type(payload["voice_output"]["enabled"]) is not bool:
        raise ValueError("voice output enabled state is invalid")
    if type(payload["voice_receiver"]["enabled"]) is not bool:
        raise ValueError("voice receiver enabled state is invalid")
    _readiness(payload["voice_output"]["dependency_status"], "voice output")
    _readiness(payload["voice_receiver"]["dependency_status"], "voice receiver")
    if payload["creator_decoder_allowlist"]["status"] not in ALLOWLIST_STATUSES:
        raise ValueError("creator decoder allowlist status is invalid")
    _readiness(payload["transcription"]["status"], "transcription")
    _readiness(payload["tts"]["status"], "tts")
    _readiness(payload["tts"]["f5_worker_status"], "f5")
    if payload["tts"]["configured_engine"] not in TTS_ENGINES:
        raise ValueError("configured TTS engine is invalid")
    if payload["transcription"]["processing"] != "local-only":
        raise ValueError("transcription processing is invalid")
    if payload["tts"]["processing"] != "local-only":
        raise ValueError("TTS processing is invalid")

    outcomes = payload["outcomes"]
    for direction, allowed in (
        ("receive", RECEIVE_OUTCOMES),
        ("send", SEND_OUTCOMES),
    ):
        outcome = outcomes[direction]
        if type(outcome) is not dict or set(outcome) != {"status", "at_unix"}:
            raise ValueError("voice outcome fields are invalid")
        if outcome["status"] not in allowed:
            raise ValueError("voice outcome status is invalid")
        observed = outcome["at_unix"]
        if observed is not None and (type(observed) is not int or observed < 0):
            raise ValueError("voice outcome timestamp is invalid")

    live = payload["live_duplex"]
    if any(
        type(live[key]) is not bool
        for key in ("ready", "gates_ready", "receive_proven", "send_proven")
    ):
        raise ValueError("live duplex booleans are invalid")
    if live["status"] not in {"live-proven", "awaiting-live-evidence", "blocked"}:
        raise ValueError("live duplex status is invalid")
    gates = live["gates"]
    expected_gates = {
        "gateway",
        "claimed_room",
        "voice_connected",
        "voice_output",
        "receiver_dependency",
        "listener",
        "creator_decoder_allowlist",
        "local_transcription",
        "local_tts",
    }
    if type(gates) is not dict or set(gates) != expected_gates:
        raise ValueError("live duplex gates are invalid")
    if any(value not in _GATE_STATUSES for value in gates.values()):
        raise ValueError("live duplex gate status is invalid")
    return copy.deepcopy(payload)


def current_status() -> dict[str, object]:
    """Read the registered live provider without exposing provider exceptions."""

    with _provider_lock:
        provider = _provider
    if provider is None:
        return unavailable_status()
    try:
        return _validate_live_status(provider())
    except Exception:
        return unavailable_status("provider-unavailable")


__all__ = [
    "ALLOWLIST_STATUSES",
    "DiscordVoiceEvidence",
    "READINESS_STATUSES",
    "RECEIVE_OUTCOMES",
    "SCHEMA",
    "SEND_OUTCOMES",
    "TTS_ENGINES",
    "clear_status_provider",
    "current_status",
    "register_status_provider",
    "unavailable_status",
]
