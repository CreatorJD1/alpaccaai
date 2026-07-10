"""Pure Mindpage-snapshot adapter for operational memory-pressure signals."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import Literal, Mapping


MemoryPressureSeverity = Literal["unknown", "normal", "elevated", "high", "critical"]

MAX_EVICTION_BACKLOG = 1_000_000
ELEVATED_FILL = 0.75
HIGH_FILL = 0.90

_SEVERITY_RANK = {
    "unknown": -1,
    "normal": 0,
    "elevated": 1,
    "high": 2,
    "critical": 3,
}


@dataclass(frozen=True, slots=True)
class MemoryPressureSignal:
    """Bounded facts derived from one supplied Mindpage snapshot."""

    enabled: bool | None
    fill_ratio: float | None
    pressure_score: float | None
    overflow: bool | None
    unshrinkable: bool | None
    eviction_backlog: int | None
    severity: MemoryPressureSeverity
    reasons: tuple[str, ...]
    description: str
    evidence: tuple[tuple[str, bool | float | int], ...]
    invalid_fields: tuple[str, ...]
    complete: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "fill_ratio": self.fill_ratio,
            "pressure_score": self.pressure_score,
            "overflow": self.overflow,
            "unshrinkable": self.unshrinkable,
            "eviction_backlog": self.eviction_backlog,
            "severity": self.severity,
            "reasons": list(self.reasons),
            "description": self.description,
            "evidence": dict(self.evidence),
            "invalid_fields": list(self.invalid_fields),
            "complete": self.complete,
        }


def _bool_field(snapshot: Mapping[str, object], key: str) -> tuple[bool | None, str]:
    if key not in snapshot or snapshot[key] is None:
        return None, "unknown"
    if isinstance(snapshot[key], bool):
        return snapshot[key], "known"
    return None, "invalid"


def _fill_field(snapshot: Mapping[str, object]) -> tuple[float | None, str]:
    value = snapshot.get("context_fill")
    if value is None:
        return None, "unknown"
    if isinstance(value, bool) or not isinstance(value, Real):
        return None, "invalid"
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        return None, "invalid"
    return round(normalized, 4), "known"


def _backlog_field(snapshot: Mapping[str, object]) -> tuple[int | None, str]:
    value = snapshot.get("unsummarized_eviction_backlog")
    if value is None:
        return None, "unknown"
    if isinstance(value, bool) or not isinstance(value, Integral):
        return None, "invalid"
    normalized = int(value)
    if normalized < 0 or normalized > MAX_EVICTION_BACKLOG:
        return None, "invalid"
    return normalized, "known"


def _severity_for_fill(fill_ratio: float) -> MemoryPressureSeverity:
    if fill_ratio >= HIGH_FILL:
        return "high"
    if fill_ratio >= ELEVATED_FILL:
        return "elevated"
    return "normal"


def _stronger(
    current: MemoryPressureSeverity,
    candidate: MemoryPressureSeverity,
) -> MemoryPressureSeverity:
    return candidate if _SEVERITY_RANK[candidate] > _SEVERITY_RANK[current] else current


def _unknown_signal(*, enabled: bool | None = None,
                    invalid_fields: tuple[str, ...] = ()) -> MemoryPressureSignal:
    if enabled is False:
        description = "Mindpage telemetry is disabled; memory pressure is unknown."
    elif invalid_fields:
        description = "Memory-pressure telemetry is unavailable because supplied fields are invalid."
    else:
        description = "Memory-pressure telemetry is unavailable."
    return MemoryPressureSignal(
        enabled=enabled,
        fill_ratio=None,
        pressure_score=None,
        overflow=None,
        unshrinkable=None,
        eviction_backlog=None,
        severity="unknown",
        reasons=(),
        description=description,
        evidence=(),
        invalid_fields=invalid_fields,
        complete=False,
    )


def adapt_memory_pressure(
    snapshot: Mapping[str, object] | None,
) -> MemoryPressureSignal:
    """Project supplied Mindpage telemetry into bounded operational facts.

    Missing and malformed fields never become zero or ``False``. The function
    performs no sampling, storage access, model call, or state mutation.
    """
    if snapshot is None:
        return _unknown_signal()
    if not isinstance(snapshot, Mapping):
        return _unknown_signal(invalid_fields=("snapshot",))

    enabled, enabled_state = _bool_field(snapshot, "enabled")
    if enabled is False:
        return _unknown_signal(enabled=False)

    fill_ratio, fill_state = _fill_field(snapshot)
    overflow, overflow_state = _bool_field(snapshot, "overflow")
    unshrinkable, unshrinkable_state = _bool_field(snapshot, "unshrinkable")
    unshrinkable_key = "unshrinkable"
    if unshrinkable_state == "unknown":
        fallback, fallback_state = _bool_field(snapshot, "fixed_overflow")
        if fallback_state != "unknown":
            unshrinkable = fallback
            unshrinkable_state = fallback_state
            unshrinkable_key = "fixed_overflow"
    backlog, backlog_state = _backlog_field(snapshot)

    states = {
        "enabled": enabled_state,
        "context_fill": fill_state,
        "overflow": overflow_state,
        unshrinkable_key: unshrinkable_state,
        "unsummarized_eviction_backlog": backlog_state,
    }
    invalid_fields = tuple(key for key, state in states.items() if state == "invalid")
    evidence: list[tuple[str, bool | float | int]] = []
    if enabled_state == "known":
        evidence.append(("enabled", enabled))
    if fill_state == "known":
        evidence.append(("context_fill", fill_ratio))
    if overflow_state == "known":
        evidence.append(("overflow", overflow))
    if unshrinkable_state == "known":
        evidence.append((unshrinkable_key, unshrinkable))
    if backlog_state == "known":
        evidence.append(("unsummarized_eviction_backlog", backlog))

    severity: MemoryPressureSeverity = "unknown"
    pressure_candidates: list[float] = []
    reasons: list[str] = []
    if fill_ratio is not None:
        severity = _severity_for_fill(fill_ratio)
        pressure_candidates.append(fill_ratio)
        if fill_ratio >= HIGH_FILL:
            reasons.append("context-fill-high")
        elif fill_ratio >= ELEVATED_FILL:
            reasons.append("context-fill-elevated")
    if backlog is not None and backlog > 0:
        severity = _stronger(severity, "elevated")
        pressure_candidates.append(ELEVATED_FILL)
        reasons.append("eviction-backlog")
    if overflow is True:
        severity = _stronger(severity, "high")
        pressure_candidates.append(HIGH_FILL)
        reasons.append("request-overflow")
    if unshrinkable is True:
        severity = "critical"
        pressure_candidates.append(1.0)
        reasons.append("fixed-context-overflow")

    description_parts = []
    if fill_ratio is not None:
        description_parts.append(f"Context utilization is {round(fill_ratio * 100)}%.")
    if overflow is True:
        description_parts.append("The request exceeds the configured context limit.")
    elif overflow is False:
        description_parts.append("No request overflow is reported.")
    if unshrinkable is True:
        description_parts.append("Optional context removal cannot make the request fit.")
    if backlog is not None:
        if backlog:
            noun = "message" if backlog == 1 else "messages"
            verb = "remains" if backlog == 1 else "remain"
            description_parts.append(f"{backlog} {noun} {verb} in the eviction backlog.")
        else:
            description_parts.append("The eviction backlog is empty.")
    if invalid_fields:
        description_parts.append("Invalid snapshot fields were ignored.")
    if not description_parts:
        description_parts.append("Memory-pressure telemetry is unavailable.")

    complete = all(
        value is not None
        for value in (fill_ratio, overflow, unshrinkable, backlog)
    )
    return MemoryPressureSignal(
        enabled=enabled,
        fill_ratio=fill_ratio,
        pressure_score=max(pressure_candidates) if pressure_candidates else None,
        overflow=overflow,
        unshrinkable=unshrinkable,
        eviction_backlog=backlog,
        severity=severity,
        reasons=tuple(reasons),
        description=" ".join(description_parts),
        evidence=tuple(evidence),
        invalid_fields=invalid_fields,
        complete=complete,
    )


__all__ = [
    "ELEVATED_FILL",
    "HIGH_FILL",
    "MAX_EVICTION_BACKLOG",
    "MemoryPressureSeverity",
    "MemoryPressureSignal",
    "adapt_memory_pressure",
]
