"""Pure normalization and assessment for explicitly supplied host readings.

This module performs no operating-system or hardware probing. Callers provide
every reading, and ``None`` always means unknown rather than zero.
"""

from __future__ import annotations

import math
from numbers import Real
from typing import Any


RESOURCE_ORDER = ("cpu", "ram", "commit", "vram", "disk", "battery", "thermal")
SEVERITY_THRESHOLDS = (
    (0.95, "critical"),
    (0.85, "high"),
    (0.70, "elevated"),
)


def _number(value: Any, *, maximum: float | None = None) -> tuple[float | None, str]:
    if value is None:
        return None, "unknown"
    if isinstance(value, bool) or not isinstance(value, Real):
        return None, "invalid"
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        return None, "invalid"
    if maximum is not None and normalized > maximum:
        return None, "invalid"
    return normalized, "known"


def _bounded(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)


def _severity(pressure: float | None) -> str:
    if pressure is None:
        return "unknown"
    for threshold, severity in SEVERITY_THRESHOLDS:
        if pressure >= threshold:
            return severity
    return "normal"


def _percent_reading(value: Any, *, invert: bool = False) -> dict:
    percent, state = _number(value, maximum=100.0)
    pressure = None
    if state == "known":
        fraction = percent / 100.0
        pressure = _bounded(1.0 - fraction if invert else fraction)
    return {
        "state": state,
        "known": state == "known",
        "percent": percent,
        "pressure": pressure,
    }


def _used_capacity_reading(used: Any, total: Any) -> dict:
    used_bytes, used_state = _number(used)
    total_bytes, total_state = _number(total)
    if "invalid" in (used_state, total_state):
        state = "invalid"
    elif total_state == "known" and total_bytes == 0:
        state = "invalid"
    elif used_state != "known" or total_state != "known":
        state = "unknown"
    elif used_bytes > total_bytes:
        state = "invalid"
    else:
        state = "known"

    fraction = None
    pressure = None
    if state == "known":
        fraction = _bounded(used_bytes / total_bytes)
        pressure = fraction
    return {
        "state": state,
        "known": state == "known",
        "used_bytes": used_bytes,
        "total_bytes": total_bytes,
        "used_fraction": fraction,
        "used_percent": round(fraction * 100.0, 2) if fraction is not None else None,
        "pressure": pressure,
    }


def _disk_reading(free: Any, total: Any) -> dict:
    free_bytes, free_state = _number(free)
    total_bytes, total_state = _number(total)
    if "invalid" in (free_state, total_state):
        state = "invalid"
    elif total_state == "known" and total_bytes == 0:
        state = "invalid"
    elif free_state != "known" or total_state != "known":
        state = "unknown"
    elif free_bytes > total_bytes:
        state = "invalid"
    else:
        state = "known"

    free_fraction = None
    pressure = None
    if state == "known":
        free_fraction = _bounded(free_bytes / total_bytes)
        pressure = _bounded(1.0 - free_fraction)
    return {
        "state": state,
        "known": state == "known",
        "free_bytes": free_bytes,
        "total_bytes": total_bytes,
        "free_fraction": free_fraction,
        "free_percent": round(free_fraction * 100.0, 2) if free_fraction is not None else None,
        "pressure": pressure,
    }


def _battery_reading(percent_value: Any, charging_value: Any) -> dict:
    reading = _percent_reading(percent_value, invert=True)
    if charging_value is None:
        charging = None
        charging_state = "unknown"
    elif isinstance(charging_value, bool):
        charging = charging_value
        charging_state = "known"
    else:
        charging = None
        charging_state = "invalid"
    reading.update({"charging": charging, "charging_state": charging_state})
    return reading


def _thermal_reading(value: Any) -> dict:
    celsius, state = _number(value)
    pressure = _bounded(celsius / 100.0) if state == "known" else None
    return {
        "state": state,
        "known": state == "known",
        "celsius": celsius,
        "pressure": pressure,
    }


def normalize_readings(
    *,
    cpu_percent: Any = None,
    ram_used_bytes: Any = None,
    ram_total_bytes: Any = None,
    commit_used_bytes: Any = None,
    commit_limit_bytes: Any = None,
    vram_used_bytes: Any = None,
    vram_total_bytes: Any = None,
    disk_free_bytes: Any = None,
    disk_total_bytes: Any = None,
    battery_percent: Any = None,
    battery_charging: Any = None,
    thermal_celsius: Any = None,
) -> dict:
    """Normalize caller-supplied readings without filling missing values."""
    return {
        "cpu": _percent_reading(cpu_percent),
        "ram": _used_capacity_reading(ram_used_bytes, ram_total_bytes),
        "commit": _used_capacity_reading(commit_used_bytes, commit_limit_bytes),
        "vram": _used_capacity_reading(vram_used_bytes, vram_total_bytes),
        "disk": _disk_reading(disk_free_bytes, disk_total_bytes),
        "battery": _battery_reading(battery_percent, battery_charging),
        "thermal": _thermal_reading(thermal_celsius),
    }


_OBSERVED_FIELDS = {
    "cpu": ("percent",),
    "ram": ("used_bytes", "total_bytes"),
    "commit": ("used_bytes", "total_bytes"),
    "vram": ("used_bytes", "total_bytes"),
    "disk": ("free_bytes", "total_bytes"),
    "battery": ("percent", "charging"),
    "thermal": ("celsius",),
}


def _reason(resource: str, reading: dict, severity: str) -> dict:
    observed = {
        field: reading[field]
        for field in _OBSERVED_FIELDS[resource]
        if reading.get(field) is not None
    }
    return {
        "resource": resource,
        "code": f"{resource}_pressure",
        "severity": severity,
        "pressure": reading["pressure"],
        "observed": observed,
    }


def assess_resources(
    *,
    cpu_percent: Any = None,
    ram_used_bytes: Any = None,
    ram_total_bytes: Any = None,
    commit_used_bytes: Any = None,
    commit_limit_bytes: Any = None,
    vram_used_bytes: Any = None,
    vram_total_bytes: Any = None,
    disk_free_bytes: Any = None,
    disk_total_bytes: Any = None,
    battery_percent: Any = None,
    battery_charging: Any = None,
    thermal_celsius: Any = None,
) -> dict:
    """Derive bounded resource pressure from supplied readings only.

    Overall pressure is the strongest known signal. If no resource can be
    assessed, pressure remains ``None`` and severity remains ``unknown``.
    """
    normalized = normalize_readings(
        cpu_percent=cpu_percent,
        ram_used_bytes=ram_used_bytes,
        ram_total_bytes=ram_total_bytes,
        commit_used_bytes=commit_used_bytes,
        commit_limit_bytes=commit_limit_bytes,
        vram_used_bytes=vram_used_bytes,
        vram_total_bytes=vram_total_bytes,
        disk_free_bytes=disk_free_bytes,
        disk_total_bytes=disk_total_bytes,
        battery_percent=battery_percent,
        battery_charging=battery_charging,
        thermal_celsius=thermal_celsius,
    )

    readings = {}
    reasons = []
    known_resources = []
    unknown_resources = []
    invalid_resources = []
    known_pressures = []
    for resource in RESOURCE_ORDER:
        reading = dict(normalized[resource])
        severity = _severity(reading["pressure"])
        reading["severity"] = severity
        readings[resource] = reading
        if reading["state"] == "known":
            known_resources.append(resource)
            known_pressures.append(reading["pressure"])
            if severity != "normal":
                reasons.append(_reason(resource, reading, severity))
        elif reading["state"] == "invalid":
            invalid_resources.append(resource)
        else:
            unknown_resources.append(resource)

    pressure = max(known_pressures) if known_pressures else None
    invalid_fields = []
    if readings["battery"]["charging_state"] == "invalid":
        invalid_fields.append("battery_charging")
    return {
        "pressure": pressure,
        "severity": _severity(pressure),
        "reasons": reasons,
        "readings": readings,
        "known_resources": known_resources,
        "unknown_resources": unknown_resources,
        "invalid_resources": invalid_resources,
        "invalid_fields": invalid_fields,
        "complete": len(known_resources) == len(RESOURCE_ORDER),
    }


__all__ = [
    "RESOURCE_ORDER",
    "SEVERITY_THRESHOLDS",
    "assess_resources",
    "normalize_readings",
]
