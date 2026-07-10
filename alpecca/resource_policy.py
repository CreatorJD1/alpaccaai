"""Pure, bounded workload-shedding policy for observed pressure snapshots.

The policy is advisory only. It does not probe the host or initiate any work;
callers supply already-observed resource and Mindpage measurements.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Real
from typing import Any, Literal


Action = Literal[
    "allow_normal_work",
    "defer_optional_work",
    "reduce_context",
    "recovery_notice",
]

MAX_REASONS = 4

_ACTION_BY_LEVEL: tuple[Action, ...] = (
    "allow_normal_work",
    "defer_optional_work",
    "reduce_context",
    "recovery_notice",
)
_RESOURCE_LEVELS = {
    "normal": 0,
    "elevated": 1,
    "warning": 1,
    "high": 2,
    "critical": 3,
}
_MEMORY_LEVELS = {
    "low": 0,
    "normal": 0,
    "medium": 1,
    "elevated": 1,
    "warning": 1,
    "high": 2,
}


def _unit(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        return None
    return round(normalized, 4)


def _flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _label_level(value: Any, levels: Mapping[str, int]) -> int | None:
    if not isinstance(value, str):
        return None
    return levels.get(value.strip().lower())


def _resource_evidence(assessment: Mapping[str, Any]) -> tuple[int, dict, list[str]]:
    pressure = _unit(assessment.get("pressure"))
    if pressure is None:
        return 0, {"state": "unknown", "pressure": None, "severity": "unknown"}, []

    derived_level = 3 if pressure >= 0.95 else 2 if pressure >= 0.85 else 1 if pressure >= 0.70 else 0
    stated_level = _label_level(assessment.get("severity"), _RESOURCE_LEVELS)
    level = max(derived_level, stated_level if stated_level is not None else 0)
    severity = ("normal", "warning", "high", "critical")[level]
    reason = [] if level == 0 else [f"resource_{severity}"]
    return level, {"state": "known", "pressure": pressure, "severity": severity}, reason


def _memory_evidence(snapshot: Mapping[str, Any]) -> tuple[int, dict, list[str]]:
    enabled = _flag(snapshot.get("enabled"))
    if enabled is False:
        return 0, {
            "state": "unknown",
            "context_fill": None,
            "overflow": None,
            "fixed_overflow": None,
            "severity": "unknown",
        }, []

    context_fill = _unit(snapshot.get("context_fill"))
    overflow = _flag(snapshot.get("overflow"))
    fixed_overflow = _flag(snapshot.get("fixed_overflow"))
    unshrinkable = _flag(snapshot.get("unshrinkable"))
    context_fits = _flag(snapshot.get("context_fits"))
    if context_fits is False:
        overflow = True
    if fixed_overflow is True or unshrinkable is True:
        fixed_overflow = True
        overflow = True

    stated_level = _label_level(snapshot.get("pressure"), _MEMORY_LEVELS)
    metric_level = (
        2 if context_fill is not None and context_fill >= 0.85
        else 1 if context_fill is not None and context_fill >= 0.70
        else 0
    )
    known = any(value is not None for value in (
        context_fill, overflow, fixed_overflow, unshrinkable, context_fits, stated_level,
    ))
    if not known:
        return 0, {
            "state": "unknown",
            "context_fill": None,
            "overflow": None,
            "fixed_overflow": None,
            "severity": "unknown",
        }, []

    if fixed_overflow is True:
        return 3, {
            "state": "known",
            "context_fill": context_fill,
            "overflow": True,
            "fixed_overflow": True,
            "severity": "critical",
        }, ["memory_fixed_overflow"]
    if overflow is True:
        return 2, {
            "state": "known",
            "context_fill": context_fill,
            "overflow": True,
            "fixed_overflow": False,
            "severity": "high",
        }, ["memory_overflow"]

    level = max(metric_level, stated_level if stated_level is not None else 0)
    severity = ("normal", "warning", "high")[level]
    reason = [] if level == 0 else [f"memory_{severity}"]
    return level, {
        "state": "known",
        "context_fill": context_fill,
        "overflow": overflow,
        "fixed_overflow": fixed_overflow,
        "severity": severity,
    }, reason


def decide(
    resource_assessment: Mapping[str, Any] | None = None,
    memory_pressure: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Choose the least disruptive action supported by known input evidence.

    Unknown data cannot increase pressure. A normal-work decision with unknown
    evidence means only that this policy has no observed reason to shed work;
    it does not assert that host or memory pressure is normal.
    """
    resource_input = resource_assessment if isinstance(resource_assessment, Mapping) else {}
    memory_input = memory_pressure if isinstance(memory_pressure, Mapping) else {}
    resource_level, resource, resource_reasons = _resource_evidence(resource_input)
    memory_level, memory, memory_reasons = _memory_evidence(memory_input)
    level = max(resource_level, memory_level)
    action = _ACTION_BY_LEVEL[level]
    evidence_state = (
        "unknown" if resource["state"] == memory["state"] == "unknown"
        else "partial" if "unknown" in (resource["state"], memory["state"])
        else "observed"
    )
    reasons = tuple((memory_reasons + resource_reasons)[:MAX_REASONS])
    return {
        "action": action,
        "allow_normal_work": level == 0,
        "defer_optional_work": level >= 1,
        "reduce_context": level >= 2,
        "require_recovery_notice": level >= 3,
        "evidence_state": evidence_state,
        "resource": resource,
        "memory": memory,
        "reasons": reasons,
    }


__all__ = ["Action", "MAX_REASONS", "decide"]
