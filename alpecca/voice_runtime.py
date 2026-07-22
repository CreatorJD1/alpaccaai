"""Pure aggregation of content-free, observed voice runtime status.

Inputs are mappings or zero-argument callables supplied by runtime owners. This
module imports no voice engines, probes no files, starts no services, and never
infers readiness from installation. Only explicit live/runtime evidence can set
a capability to ready.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import math
import re
from typing import TypeAlias


SCHEMA = "alpecca.voice-runtime.v1"
MAX_REASONS = 32
MAX_COMPONENT_REASONS = 8
MAX_REASON_CHARS = 96
MAX_SNAPSHOT_CHARS = 16_384

CANONICAL_SYNTHESIS_ROUTES = ("cloud", "f5", "kokoro")
_ROUTE_ALIASES = {
    "cloud": "cloud",
    "cloud-tts": "cloud",
    "hosted": "cloud",
    "f5": "f5",
    "f5-tts": "f5",
    "f5-tts-worker": "f5",
    "open-tts": "f5",
    "kokoro": "kokoro",
}
_REASON_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,95}$")
_FORBIDDEN_KEYS = frozenset(
    {
        "audio",
        "raw_audio",
        "raw_audio_bytes",
        "bytes",
        "content",
        "text",
        "transcript",
        "payload",
        "secret",
        "token",
        "password",
        "credential",
        "authorization",
        "url",
    }
)

StatusSource: TypeAlias = Mapping[str, object] | Callable[[], Mapping[str, object]] | None


class VoiceRuntimeError(ValueError):
    """The aggregate could not be represented by the bounded public schema."""


def _contains_unsafe_input(value: object) -> bool:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return True
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or key.casefold() in _FORBIDDEN_KEYS:
                return True
            if _contains_unsafe_input(item):
                return True
    elif isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_unsafe_input(item) for item in value)
    return False


def _resolve(source: StatusSource, component: str) -> tuple[Mapping[str, object], list[str]]:
    if source is None:
        return {}, [f"{component}-status-unavailable"]
    try:
        value = source() if callable(source) else source
    except Exception:
        return {}, [f"{component}-status-source-error"]
    if not isinstance(value, Mapping):
        return {}, [f"{component}-status-invalid"]
    if _contains_unsafe_input(value):
        return {}, [f"{component}-unsafe-input-rejected"]
    return value, []


def _strict_bool(value: object) -> bool | None:
    return value if type(value) is bool else None


def _reason_codes(value: object) -> list[str]:
    if value is None:
        return []
    candidates: Sequence[object]
    if isinstance(value, str):
        candidates = (value,)
    elif isinstance(value, (list, tuple)):
        candidates = value
    else:
        return ["invalid-reason-redacted"]
    reasons: list[str] = []
    invalid = False
    for candidate in candidates[:MAX_COMPONENT_REASONS]:
        if (
            not isinstance(candidate, str)
            or len(candidate) > MAX_REASON_CHARS
            or _REASON_RE.fullmatch(candidate) is None
        ):
            invalid = True
            continue
        if candidate not in reasons:
            reasons.append(candidate)
    if invalid and "invalid-reason-redacted" not in reasons:
        reasons.append("invalid-reason-redacted")
    return reasons[:MAX_COMPONENT_REASONS]


def _input_reasons(record: Mapping[str, object]) -> list[str]:
    value = record.get("reasons") if "reasons" in record else record.get("reason")
    return _reason_codes(value)


def _append_reason(reasons: list[str], code: str) -> None:
    if code not in reasons and len(reasons) < MAX_COMPONENT_REASONS:
        reasons.append(code)


def _house_snapshot(source: StatusSource) -> dict[str, object]:
    record, source_reasons = _resolve(source, "house")
    reasons = source_reasons + _input_reasons(record)
    state_value = record.get("state")
    state = state_value if isinstance(state_value, str) else ""

    mic_live = _strict_bool(record.get("mic_live"))
    listening = _strict_bool(record.get("listening"))
    thinking = _strict_bool(record.get("thinking"))
    speaking = _strict_bool(record.get("speaking"))
    degraded_signal = _strict_bool(record.get("degraded"))

    if state in {"idle", "listening", "thinking", "speaking"}:
        listening = (state == "listening") if listening is None else listening
        thinking = (state == "thinking") if thinking is None else thinking
        speaking = (state == "speaking") if speaking is None else speaking
    elif state == "degraded":
        degraded_signal = True

    active = [
        name
        for name, value in (
            ("listening", listening),
            ("thinking", thinking),
            ("speaking", speaking),
        )
        if value is True
    ]
    if len(active) > 1:
        _append_reason(reasons, "house-activity-conflict")
    if listening is True and mic_live is False:
        _append_reason(reasons, "listening-without-live-mic")
    if degraded_signal is True and not reasons:
        _append_reason(reasons, "house-reported-degraded")

    degraded = degraded_signal is True or bool(
        {"house-activity-conflict", "listening-without-live-mic"} & set(reasons)
    ) or bool(source_reasons)
    known = any(
        value is not None
        for value in (mic_live, listening, thinking, speaking, degraded_signal)
    ) or state in {"idle", "listening", "thinking", "speaking", "degraded"}
    if degraded:
        effective_state = "degraded"
    elif speaking is True:
        effective_state = "speaking"
    elif thinking is True:
        effective_state = "thinking"
    elif listening is True:
        effective_state = "listening"
    elif known:
        effective_state = "idle"
    else:
        effective_state = "unknown"
    return {
        "state": effective_state,
        "mic_live": mic_live,
        "listening": listening,
        "thinking": thinking,
        "speaking": speaking,
        "degraded": degraded,
        "reasons": reasons[:MAX_COMPONENT_REASONS],
    }


def _canonical_route(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return _ROUTE_ALIASES.get(value.strip().casefold())


def _route_record(record: Mapping[str, object], name: str) -> Mapping[str, object]:
    routes = record.get("routes")
    if isinstance(routes, Mapping) and isinstance(routes.get(name), Mapping):
        return routes[name]  # type: ignore[return-value]
    direct = record.get(name)
    if isinstance(direct, Mapping):
        return direct
    if name == "f5":
        for key in ("f5_worker", "open_tts"):
            value = record.get(key)
            if isinstance(value, Mapping):
                return value
        engines = record.get("engines")
        if isinstance(engines, Mapping):
            for key in ("f5", "f5_worker", "open_tts"):
                value = engines.get(key)
                if isinstance(value, Mapping):
                    return value
    if name == "kokoro":
        value = record.get("kokoro_status")
        if isinstance(value, Mapping):
            return value
        engines = record.get("engines")
        if isinstance(engines, Mapping) and isinstance(engines.get("kokoro_status"), Mapping):
            return engines["kokoro_status"]  # type: ignore[return-value]
    return {}


def _explicit_ready(record: Mapping[str, object], *aliases: str) -> bool | None:
    for key in ("ready", "live", *aliases):
        value = _strict_bool(record.get(key))
        if value is not None:
            return value
    return None


def _synthesis_snapshot(source: StatusSource) -> dict[str, object]:
    record, source_reasons = _resolve(source, "synthesis")
    reasons = source_reasons + _input_reasons(record)
    selected = _canonical_route(
        record.get("active_route")
        or record.get("selected_route")
        or record.get("active_engine")
        or record.get("last_engine")
    )
    raw_selected = (
        record.get("active_route")
        or record.get("selected_route")
        or record.get("active_engine")
        or record.get("last_engine")
    )
    if raw_selected and selected is None:
        _append_reason(reasons, "synthesis-route-unknown")

    route_records = {name: _route_record(record, name) for name in CANONICAL_SYNTHESIS_ROUTES}
    explicit_active = [
        name for name, route in route_records.items() if _strict_bool(route.get("active")) is True
    ]
    if selected is None and len(explicit_active) == 1:
        selected = explicit_active[0]
    elif len(explicit_active) > 1:
        _append_reason(reasons, "multiple-synthesis-routes-active")

    routes: dict[str, dict[str, object]] = {}
    for name in CANONICAL_SYNTHESIS_ROUTES:
        route = route_records[name]
        enabled = _strict_bool(route.get("enabled"))
        ready = _explicit_ready(route)
        active = name == selected or _strict_bool(route.get("active")) is True
        route_reasons = _input_reasons(route)
        if enabled is False:
            route_state = "disabled"
        elif active and ready is True:
            route_state = "active"
        elif active and ready is not True:
            route_state = "degraded"
            _append_reason(route_reasons, "active-route-unverified" if ready is None else "active-route-not-ready")
        elif ready is True:
            route_state = "ready"
        elif ready is False:
            route_state = "degraded" if enabled is True else "unavailable"
            if enabled is True:
                _append_reason(route_reasons, "enabled-route-not-ready")
        else:
            route_state = "unknown"
            if route and any(key in route for key in ("installed", "available", "model_available", "path")):
                _append_reason(route_reasons, "runtime-evidence-missing")
        routes[name] = {
            "state": route_state,
            "enabled": enabled,
            "ready": ready,
            "active": active,
            "reasons": route_reasons[:MAX_COMPONENT_REASONS],
        }

    selected_state = routes[selected]["state"] if selected else None
    degraded_routes = [
        name for name, route in routes.items() if route["state"] == "degraded"
    ]
    degraded = bool(source_reasons) or "multiple-synthesis-routes-active" in reasons or bool(
        degraded_routes
    )
    for name in degraded_routes:
        _append_reason(reasons, f"{name}-route-degraded")
    if selected is not None and selected_state == "degraded":
        _append_reason(reasons, f"{selected}-route-degraded")
    any_ready = any(route["ready"] is True for route in routes.values())
    any_evidence = bool(record) and any(
        route["ready"] is not None or route["enabled"] is not None for route in routes.values()
    )
    if degraded:
        state = "degraded"
    elif selected is not None and selected_state == "active":
        state = "active"
    elif any_ready:
        state = "ready"
    elif any_evidence:
        state = "unavailable"
    else:
        state = "unknown"
    return {
        "state": state,
        "selected_route": selected,
        "routes": routes,
        "degraded": degraded,
        "reasons": reasons[:MAX_COMPONENT_REASONS],
    }


def _discord_part(record: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = record.get(name)
    if isinstance(value, Mapping):
        return value
    if name == "send" and any(key in record for key in ("can_speak", "speaking")):
        return record
    if name == "receive" and any(key in record for key in ("can_receive", "receiving")):
        return record
    if name == "vad":
        receive = record.get("receive")
        if isinstance(receive, Mapping) and isinstance(receive.get("vad"), Mapping):
            return receive["vad"]  # type: ignore[return-value]
    return {}


def _discord_channel(
    record: Mapping[str, object], name: str, *, connected: bool | None
) -> dict[str, object]:
    enabled = _strict_bool(record.get("enabled"))
    ready_alias = "can_speak" if name == "send" else "can_receive" if name == "receive" else ""
    ready = _explicit_ready(record, *(alias for alias in (ready_alias,) if alias))
    active_alias = "speaking" if name == "send" else "receiving" if name == "receive" else "active"
    active = _strict_bool(record.get("active"))
    if active is None:
        active = _strict_bool(record.get(active_alias))
    reasons = _input_reasons(record)

    if enabled is False:
        state = "disabled"
        if active is True:
            state = "degraded"
            _append_reason(reasons, f"{name}-active-while-disabled")
    elif connected is False and name in {"send", "receive"}:
        state = "disconnected"
        if active is True:
            state = "degraded"
            _append_reason(reasons, f"{name}-active-while-disconnected")
    elif active is True and ready is True:
        state = "active"
    elif active is True:
        state = "degraded"
        _append_reason(reasons, f"{name}-active-without-readiness")
    elif ready is True:
        state = "ready"
    elif ready is False:
        state = "degraded" if enabled is True else "unavailable"
        if enabled is True:
            _append_reason(reasons, f"{name}-enabled-not-ready")
    else:
        state = "unknown"
        if any(key in record for key in ("installed", "available", "model_available", "path")):
            _append_reason(reasons, "runtime-evidence-missing")
    return {
        "state": state,
        "enabled": enabled,
        "ready": ready,
        "active": active,
        "reasons": reasons[:MAX_COMPONENT_REASONS],
    }


def _discord_snapshot(source: StatusSource) -> dict[str, object]:
    record, source_reasons = _resolve(source, "discord")
    reasons = source_reasons + _input_reasons(record)
    connected = _strict_bool(record.get("connected"))
    send = _discord_channel(_discord_part(record, "send"), "send", connected=connected)
    receive_record = _discord_part(record, "receive")
    receive = _discord_channel(receive_record, "receive", connected=connected)
    vad = _discord_channel(_discord_part(record, "vad"), "vad", connected=connected)

    degraded_parts = [
        name
        for name, part in (("send", send), ("receive", receive), ("vad", vad))
        if part["state"] == "degraded"
    ]
    for name in degraded_parts:
        _append_reason(reasons, f"discord-{name}-degraded")
    if receive["active"] is True and vad["ready"] is not True:
        _append_reason(reasons, "discord-vad-unverified-during-receive")
        degraded_parts.append("vad")

    degraded_signal = _strict_bool(record.get("degraded"))
    if degraded_signal is True and not reasons:
        _append_reason(reasons, "discord-reported-degraded")
    degraded = bool(source_reasons or degraded_parts or degraded_signal is True)
    channel_states = {send["state"], receive["state"], vad["state"]}
    if degraded:
        state = "degraded"
    elif connected is False:
        state = "disconnected"
    elif "active" in channel_states:
        state = "active"
    elif "ready" in channel_states:
        state = "ready"
    elif record:
        state = "unavailable" if "unavailable" in channel_states else "unknown"
    else:
        state = "unknown"
    return {
        "state": state,
        "connected": connected,
        "send": send,
        "receive": receive,
        "vad": vad,
        "degraded": degraded,
        "reasons": reasons[:MAX_COMPONENT_REASONS],
    }


def voice_runtime_snapshot(
    *,
    house: StatusSource = None,
    synthesis: StatusSource = None,
    discord: StatusSource = None,
) -> dict[str, object]:
    """Build one bounded JSON-safe snapshot from explicit runtime evidence."""

    house_status = _house_snapshot(house)
    synthesis_status = _synthesis_snapshot(synthesis)
    discord_status = _discord_snapshot(discord)
    components = {
        "house": house_status,
        "synthesis": synthesis_status,
        "discord": discord_status,
    }
    reasons = [
        {"component": component, "code": reason}
        for component, status in components.items()
        for reason in status["reasons"]  # type: ignore[index]
    ][:MAX_REASONS]
    degraded = any(status["degraded"] is True for status in components.values())
    house_live = (
        house_status["state"] == "listening"
        and house_status["listening"] is True
        and house_status["mic_live"] is True
    ) or (
        house_status["state"] == "thinking" and house_status["thinking"] is True
    ) or (
        house_status["state"] == "speaking" and house_status["speaking"] is True
    )
    synthesis_live = synthesis_status["state"] in {"active", "ready"}
    discord_live = discord_status["state"] in {"active", "ready"}
    live = house_live or synthesis_live or discord_live
    all_routes_disabled = all(
        route["enabled"] is False and route["state"] == "disabled"
        for route in synthesis_status["routes"].values()  # type: ignore[union-attr]
    )
    all_discord_disabled = all(
        discord_status[name]["enabled"] is False  # type: ignore[index]
        and discord_status[name]["state"] == "disabled"  # type: ignore[index]
        for name in ("send", "receive", "vad")
    )
    house_inactive = (
        house_status["state"] == "idle"
        and house_status["mic_live"] is False
        and house_status["listening"] is False
        and house_status["thinking"] is False
        and house_status["speaking"] is False
    )
    if degraded:
        state = "degraded"
    elif house_inactive and all_routes_disabled and all_discord_disabled:
        state = "disabled"
    elif live:
        state = "healthy"
    else:
        state = "unknown"
    snapshot = {
        "schema": SCHEMA,
        "state": state,
        "ready": state == "healthy",
        "degraded": degraded,
        "reasons": reasons,
        "house": house_status,
        "synthesis": synthesis_status,
        "discord": discord_status,
        "safety": {
            "contains_secrets": False,
            "contains_content": False,
            "contains_raw_audio": False,
            "readiness_from_installed_files": False,
        },
    }
    try:
        encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise VoiceRuntimeError("voice runtime snapshot is not JSON-safe") from exc
    if len(encoded) > MAX_SNAPSHOT_CHARS:
        raise VoiceRuntimeError("voice runtime snapshot exceeds its bound")
    return snapshot


class VoiceRuntimeAggregator:
    """Reusable holder for injected status providers; it owns no services."""

    def __init__(
        self,
        *,
        house: StatusSource = None,
        synthesis: StatusSource = None,
        discord: StatusSource = None,
    ) -> None:
        self._house = house
        self._synthesis = synthesis
        self._discord = discord

    def snapshot(self) -> dict[str, object]:
        return voice_runtime_snapshot(
            house=self._house,
            synthesis=self._synthesis,
            discord=self._discord,
        )


__all__ = [
    "CANONICAL_SYNTHESIS_ROUTES",
    "MAX_SNAPSHOT_CHARS",
    "SCHEMA",
    "VoiceRuntimeAggregator",
    "VoiceRuntimeError",
    "voice_runtime_snapshot",
]
