"""Pure pressure telemetry mapping for the existing seven-role Soul.

Inputs are the dictionaries already emitted by Mindpage and resource_signals.
Outputs are bounded numbers and machine-readable operational hints only.  This
module does not alter ``soul.Snapshot``, call a model, generate prompt text, or
describe telemetry as a feeling.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


VECTOR_ORDER = ("context", "eviction", "page_store", "overflow", "host")
EXISTING_SOUL_ROLES = frozenset({
    "Feeler", "Expressor", "Carer", "Doer", "Wanderer", "Reflector", "Improver"
})
MAX_HINTS = 4
EVICTION_BACKLOG_CAP = 8
_RESOURCE_ORDER = ("cpu", "ram", "commit", "vram", "disk", "battery", "thermal")


@dataclass(frozen=True, slots=True)
class PressureSignalVector:
    """Fixed-order optional numeric signals; ``None`` means unknown."""

    context: float | None
    eviction: float | None
    page_store: float | None
    overflow: float | None
    host: float | None
    overall: float | None
    known_fraction: float

    @property
    def values(self) -> tuple[float | None, ...]:
        return (self.context, self.eviction, self.page_store, self.overflow, self.host)

    @property
    def known_mask(self) -> tuple[int, ...]:
        return tuple(1 if value is not None else 0 for value in self.values)

    def as_dict(self) -> dict[str, object]:
        return {
            "order": list(VECTOR_ORDER),
            "values": list(self.values),
            "known_mask": list(self.known_mask),
            "overall": self.overall,
            "known_fraction": self.known_fraction,
        }


@dataclass(frozen=True, slots=True)
class OperationalIntentionHint:
    """Bounded code-shaped hint compatible with an existing Soul role."""

    subagent: Literal["Reflector"]
    category: Literal["self_care"]
    action: str
    rank: int
    urgency: float
    evidence_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "subagent": self.subagent,
            "category": self.category,
            "action": self.action,
            "rank": self.rank,
            "urgency": self.urgency,
            "evidence_codes": list(self.evidence_codes),
        }


@dataclass(frozen=True, slots=True)
class SoulPressureSignal:
    """Compact vector plus zero to four deterministic operational hints."""

    vector: PressureSignalVector
    hints: tuple[OperationalIntentionHint, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "signal_vector": self.vector.as_dict(),
            "intention_hints": [hint.as_dict() for hint in self.hints],
        }

    def as_snapshot_memory_pressure(self) -> dict[str, object]:
        """Return a payload that can later occupy ``Snapshot.memory_pressure``."""
        return {
            "context_fill": self.vector.context,
            "pressure_score": self.vector.overall,
            **self.as_dict(),
        }


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _bounded(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(max(0.0, min(1.0, number)), 4)


def _count_pressure(value: object, *, cap: int) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(max(0.0, min(1.0, number / max(1, cap))), 4)


def _memory_available(memory: Mapping[str, Any] | None) -> bool:
    if not memory:
        return False
    if memory.get("enabled") is False:
        return False
    if str(memory.get("source") or "").lower() == "disabled":
        return False
    if str(memory.get("pressure") or "").lower() == "unavailable":
        return False
    return True


def _memory_vector(
    memory: Mapping[str, Any] | None,
) -> tuple[float | None, float | None, float | None, float | None, bool]:
    if not _memory_available(memory):
        return None, None, None, None, False
    assert memory is not None
    context = _bounded(
        memory.get("context_fill")
        if "context_fill" in memory else memory.get("pressure_score")
    )
    eviction = _count_pressure(
        memory.get("unsummarized_eviction_backlog"), cap=EVICTION_BACKLOG_CAP
    ) if "unsummarized_eviction_backlog" in memory else None
    page_store = _bounded(memory.get("disk_fill")) if "disk_fill" in memory else None
    if memory.get("disk_over_budget") is True:
        page_store = 1.0

    overflow_keys_present = any(key in memory for key in (
        "overflow", "fixed_overflow", "unshrinkable", "context_fits",
        "overflow_tokens", "fixed_overflow_tokens",
    ))
    overflowed = (
        memory.get("overflow") is True
        or memory.get("fixed_overflow") is True
        or memory.get("unshrinkable") is True
        or memory.get("context_fits") is False
        or (_bounded(memory.get("overflow_tokens")) or 0.0) > 0.0
        or (_bounded(memory.get("fixed_overflow_tokens")) or 0.0) > 0.0
    )
    overflow = 1.0 if overflowed else 0.0 if overflow_keys_present else None
    paging_failed = bool(str(memory.get("paging_error") or "").strip())
    return context, eviction, page_store, overflow, paging_failed


def _resource_pressure(resource: Mapping[str, Any] | None) -> float | None:
    if not resource:
        return None
    direct = _bounded(
        resource.get("pressure") if "pressure" in resource else resource.get("score")
    )
    if direct is not None:
        return direct
    readings = _mapping(resource.get("readings")) or resource
    pressures: list[float] = []
    for name in _RESOURCE_ORDER:
        reading = _mapping(readings.get(name))
        if reading is None:
            continue
        pressure = _bounded(reading.get("pressure"))
        if pressure is not None and reading.get("state") != "invalid":
            pressures.append(pressure)
    return max(pressures) if pressures else None


def _resource_evidence_codes(resource: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not resource:
        return ("host_pressure",)
    found: list[str] = []
    reasons = resource.get("reasons")
    if isinstance(reasons, (list, tuple)):
        for reason in reasons:
            item = _mapping(reason)
            name = str((item or {}).get("resource") or "")
            if name in _RESOURCE_ORDER and name not in found:
                found.append(f"{name}_pressure")
    if not found:
        readings = _mapping(resource.get("readings")) or resource
        for name in _RESOURCE_ORDER:
            reading = _mapping(readings.get(name))
            pressure = _bounded((reading or {}).get("pressure"))
            if pressure is not None and pressure >= 0.7:
                found.append(f"{name}_pressure")
    return tuple(found[:3] or ["host_pressure"])


def _hint(
    action: str,
    urgency: float,
    evidence_codes: tuple[str, ...],
) -> OperationalIntentionHint:
    return OperationalIntentionHint(
        subagent="Reflector",
        category="self_care",
        action=action,
        rank=4,
        urgency=_bounded(urgency) or 0.0,
        evidence_codes=tuple(evidence_codes[:4]),
    )


def _hints(
    *,
    vector: PressureSignalVector,
    paging_failed: bool,
    resource: Mapping[str, Any] | None,
) -> tuple[OperationalIntentionHint, ...]:
    candidates: list[tuple[int, OperationalIntentionHint]] = []
    if vector.overflow == 1.0:
        candidates.append((0, _hint(
            "resolve_context_overflow", 1.0, ("context_overflow",)
        )))
    if vector.host is not None and vector.host >= 0.7:
        candidates.append((1, _hint(
            "defer_optional_work", vector.host, _resource_evidence_codes(resource)
        )))
    if paging_failed:
        candidates.append((2, _hint(
            "inspect_paging_failure", 0.9, ("paging_error",)
        )))
    if vector.context is not None and vector.context >= 0.75:
        candidates.append((3, _hint(
            "consolidate_working_memory", vector.context, ("context_fill",)
        )))
    if vector.eviction is not None and vector.eviction >= 0.25:
        candidates.append((4, _hint(
            "summarize_eviction_backlog", vector.eviction,
            ("unsummarized_eviction_backlog",)
        )))
    if vector.page_store is not None and vector.page_store >= 0.85:
        candidates.append((5, _hint(
            "compact_page_store", vector.page_store, ("mindpage_disk_fill",)
        )))
    candidates.sort(key=lambda item: (-item[1].urgency, item[0], item[1].action))
    return tuple(item[1] for item in candidates[:MAX_HINTS])


def build_soul_pressure_signal(
    memory_pressure: Mapping[str, Any] | None = None,
    resource_signal: Mapping[str, Any] | None = None,
) -> SoulPressureSignal:
    """Map current telemetry shapes into bounded Soul-facing operations data."""
    memory = _mapping(memory_pressure)
    resource = _mapping(resource_signal)
    context, eviction, page_store, overflow, paging_failed = _memory_vector(memory)
    host = _resource_pressure(resource)
    values = (context, eviction, page_store, overflow, host)
    known = [value for value in values if value is not None]
    overall = max(known) if known else None
    vector = PressureSignalVector(
        context=context,
        eviction=eviction,
        page_store=page_store,
        overflow=overflow,
        host=host,
        overall=overall,
        known_fraction=round(len(known) / len(VECTOR_ORDER), 4),
    )
    return SoulPressureSignal(
        vector=vector,
        hints=_hints(vector=vector, paging_failed=paging_failed, resource=resource),
    )


def map_pressure_signals(
    memory_pressure: Mapping[str, Any] | None = None,
    resource_signal: Mapping[str, Any] | None = None,
) -> SoulPressureSignal:
    """Short alias for :func:`build_soul_pressure_signal`."""
    return build_soul_pressure_signal(memory_pressure, resource_signal)


__all__ = [
    "EVICTION_BACKLOG_CAP",
    "EXISTING_SOUL_ROLES",
    "MAX_HINTS",
    "OperationalIntentionHint",
    "PressureSignalVector",
    "SoulPressureSignal",
    "VECTOR_ORDER",
    "build_soul_pressure_signal",
    "map_pressure_signals",
]
