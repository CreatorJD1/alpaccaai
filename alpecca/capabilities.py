"""Grounded capability inventory and audit records for Alpecca.

Risky surfaces are disabled unless their own environment flag explicitly opts
in. This module reports state without exposing configured paths, commands,
destinations, credentials, or communication identifiers.
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from config import DB_PATH
from alpecca import cognition as cognition_mod


FALSE_VALUES = {"", "0", "false", "off", "none", "no"}


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    environment: str
    risk: str
    mode: str = "boolean"


@dataclass(frozen=True)
class CapabilityState:
    name: str
    enabled: bool
    explicit_opt_in: bool
    risk: str
    source: str


CAPABILITY_SPECS = (
    CapabilitySpec("remote_access", "ALPECCA_REMOTE", "network"),
    CapabilitySpec("public_tunnel", "ALPECCA_TUNNEL", "network", "choice"),
    CapabilitySpec("screen_sight", "ALPECCA_SIGHT", "private_sensor"),
    CapabilitySpec("webcam", "ALPECCA_FACE", "private_sensor"),
    CapabilitySpec("microphone", "ALPECCA_VOICE", "private_sensor"),
    CapabilitySpec("file_access", "ALPECCA_FILES", "filesystem"),
    CapabilitySpec("app_control", "ALPECCA_APPS", "process_control", "choice"),
    CapabilitySpec("computer_control", "ALPECCA_COMPUTER_USE", "computer_control"),
    CapabilitySpec("directory_watchers", "ALPECCA_WATCH_DIRS", "filesystem", "choice"),
    CapabilitySpec("discord_media", "ALPECCA_DISCORD_MEDIA", "network"),
)

_AUDIT_ACTIONS = frozenset({
    "capture", "connect", "disable", "enable", "execute", "observe",
    "open", "read", "request", "scan", "use", "write",
})
_AUDIT_PRINCIPALS = frozenset({"alpecca", "creator", "system", "unknown"})
_AUDIT_SOURCES = frozenset({
    "api", "background", "discord_bridge", "launcher", "runtime",
    "server", "server_start", "startup", "websocket",
})


def _owned_label(value: str, allowed: frozenset[str], fallback: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized if normalized in allowed else fallback


def _enabled(value: str, mode: str) -> bool:
    normalized = str(value or "").strip().lower()
    if mode == "boolean":
        return normalized not in FALSE_VALUES
    return bool(normalized) and normalized not in FALSE_VALUES


def snapshot(environ: Mapping[str, str] | None = None) -> list[CapabilityState]:
    values = os.environ if environ is None else environ
    states: list[CapabilityState] = []
    for spec in CAPABILITY_SPECS:
        present = spec.environment in values
        value = str(values.get(spec.environment, ""))
        states.append(
            CapabilityState(
                name=spec.name,
                enabled=present and _enabled(value, spec.mode),
                explicit_opt_in=present and _enabled(value, spec.mode),
                risk=spec.risk,
                source="explicit_environment" if present else "safe_default",
            )
        )
    return states


def public_snapshot(environ: Mapping[str, str] | None = None) -> dict:
    states = snapshot(environ)
    return {
        "generated_at": time.time(),
        "safe_by_default": True,
        "capabilities": [asdict(state) for state in states],
        "enabled": [state.name for state in states if state.enabled],
    }


def record_snapshot(
    environ: Mapping[str, str] | None = None,
    *,
    source: str = "runtime_start",
    db_path: Path = DB_PATH,
) -> list[int]:
    audit_source = _owned_label(source, _AUDIT_SOURCES, "runtime")
    observation_ids: list[int] = []
    for state in snapshot(environ):
        observation_id = cognition_mod.record_observation(
            cognition_mod.CognitionObservation(
                source="capability_audit",
                content=(
                    f"Capability {state.name} is "
                    f"{'enabled by explicit opt-in' if state.enabled else 'disabled'}."
                ),
                confidence=1.0,
                privacy_class="local",
                metadata={
                    "event": "capability_snapshot",
                    "capability": state.name,
                    "enabled": state.enabled,
                    "explicit_opt_in": state.explicit_opt_in,
                    "risk": state.risk,
                    "source": audit_source,
                },
            ),
            db_path=db_path,
        )
        if observation_id is not None:
            observation_ids.append(int(observation_id))
    return observation_ids


def record_use(
    capability: str,
    *,
    action: str,
    allowed: bool,
    principal_role: str = "unknown",
    source: str = "runtime",
    db_path: Path = DB_PATH,
) -> int | None:
    known = {spec.name: spec for spec in CAPABILITY_SPECS}
    spec = known.get(str(capability or ""))
    if spec is None:
        raise ValueError(f"unknown capability: {capability!r}")
    audit_action = _owned_label(action, _AUDIT_ACTIONS, "use")
    audit_principal = _owned_label(
        principal_role, _AUDIT_PRINCIPALS, "unknown"
    )
    audit_source = _owned_label(source, _AUDIT_SOURCES, "runtime")
    return cognition_mod.record_observation(
        cognition_mod.CognitionObservation(
            source="capability_audit",
            content=(
                f"Capability {spec.name} action {audit_action} was "
                f"{'allowed' if allowed else 'denied'}."
            ),
            confidence=1.0,
            privacy_class="local",
            metadata={
                "event": "capability_use",
                "capability": spec.name,
                "action": audit_action,
                "allowed": bool(allowed),
                "principal_role": audit_principal,
                "risk": spec.risk,
                "source": audit_source,
            },
        ),
        db_path=db_path,
    )
