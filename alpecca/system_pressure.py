"""Read-only Phase 7 host-pressure measurement and pagefile planning.

This module can observe through the established Phase 6 sampler and derive one
bounded proposal from explicitly supplied pagefile-configuration evidence.  It
contains no persistence, approval, elevation, command construction, or system
mutation capability.  A later, separately reviewed boundary must authenticate
one-use creator approval, remeasure live state, perform any elevated write, and
verify the result.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from numbers import Integral
from typing import Any

from .host_resources import HostResourceSampler


MEBIBYTE = 1024**2
GIBIBYTE = 1024**3

# Phase 7 safety policy is intentionally code-owned.  Configuration and
# environment values cannot widen these limits in this module.
PAGEFILE_STEP_MIB = 4096
PAGEFILE_ABSOLUTE_MAX_MIB = 55296
MIN_PROJECTED_SYSTEM_DISK_FREE_BYTES = 40 * GIBIBYTE
COMMIT_HEADROOM_TRIGGER_NUMERATOR = 1
COMMIT_HEADROOM_TRIGGER_DENOMINATOR = 5
COMMIT_HEADROOM_TRIGGER_FRACTION = (
    COMMIT_HEADROOM_TRIGGER_NUMERATOR / COMMIT_HEADROOM_TRIGGER_DENOMINATOR
)

PROPOSAL_SCHEMA = "alpecca.phase7.pagefile-proposal.v1"
FUTURE_EXECUTION_REQUIREMENTS = (
    "fresh_live_remeasurement",
    "separate_authenticated_one_use_creator_approval",
    "separate_minimal_elevated_helper",
    "single_bounded_write",
    "post_write_readback",
)


def _unknown_host_measurement() -> dict[str, Any]:
    """Return an explicit unknown result when the Phase 6 sampler cannot run."""
    return {
        "state": "unknown",
        "timestamp": None,
        "age": None,
        "age_seconds": None,
        "commit": {
            "state": "unknown",
            "used_bytes": None,
            "limit_bytes": None,
            "headroom_bytes": None,
            "headroom_fraction": None,
        },
        "disk": {
            "state": "unknown",
            "free_bytes": None,
            "total_bytes": None,
            "headroom_bytes": None,
            "headroom_fraction": None,
        },
        "raw": {
            "commit_used_bytes": None,
            "commit_limit_bytes": None,
            "disk_free_bytes": None,
            "disk_total_bytes": None,
        },
        "headroom": {
            "commit_bytes": None,
            "commit_fraction": None,
            "disk_bytes": None,
            "disk_fraction": None,
        },
        "assessment": {
            "pressure": None,
            "severity": "unknown",
            "reasons": [],
            "readings": {},
            "known_resources": [],
            "unknown_resources": ["commit", "disk"],
            "invalid_resources": [],
            "complete": False,
        },
        "unknown_fields": [
            "commit_used_bytes",
            "commit_limit_bytes",
            "disk_free_bytes",
            "disk_total_bytes",
        ],
        "unknown_reasons": {"host_resources": "probe_unavailable"},
    }


def _unavailable_probe() -> None:
    return None


def _command_free_host_sampler() -> HostResourceSampler:
    """Keep Phase 7 on Phase 6's commit/disk probes without command probes."""
    return HostResourceSampler(
        _cpu_probe=_unavailable_probe,
        _battery_probe=_unavailable_probe,
        _gpu_probe=_unavailable_probe,
    )


def measure_host_pressure(
    sampler: HostResourceSampler | None = None,
) -> dict[str, Any]:
    """Take one fresh read-only measurement through the Phase 6 sampler.

    No sampler is retained globally.  Probe failure remains explicit unknown
    evidence and is never converted to zero utilization or critical pressure.
    """
    current_sampler = sampler if sampler is not None else _command_free_host_sampler()
    try:
        observed = current_sampler.snapshot(force=True)
        if not isinstance(observed, Mapping):
            return _unknown_host_measurement()
        return deepcopy(dict(observed))
    except Exception:
        return _unknown_host_measurement()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nonnegative_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, Integral):
        return None
    normalized = int(value)
    return normalized if normalized >= 0 else None


def _declared_state(value: Mapping[str, Any]) -> str:
    state = value.get("state")
    if state in {"unknown", "warming"} or state is None:
        return "unknown"
    return "known" if state == "known" else "invalid"


def _pagefile_observation(value: object) -> dict[str, Any]:
    observation = _mapping(value)
    state = _declared_state(observation)
    maximum = _nonnegative_integer(observation.get("maximum_mib"))
    if state == "known" and (maximum is None or maximum == 0):
        state = "invalid"
    return {
        "state": state,
        "maximum_mib": maximum if state == "known" else None,
    }


def _commit_observation(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    reading = _mapping(snapshot.get("commit"))
    state = _declared_state(reading)
    used = _nonnegative_integer(reading.get("used_bytes"))
    limit = _nonnegative_integer(reading.get("limit_bytes"))
    if state == "known" and (
        used is None or limit is None or limit == 0 or used > limit
    ):
        state = "invalid"
    if state != "known":
        return {
            "state": state,
            "used_bytes": None,
            "limit_bytes": None,
            "headroom_bytes": None,
            "headroom_fraction": None,
        }
    headroom = limit - used
    return {
        "state": "known",
        "used_bytes": used,
        "limit_bytes": limit,
        "headroom_bytes": headroom,
        "headroom_fraction": round(headroom / limit, 4),
    }


def _disk_observation(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    reading = _mapping(snapshot.get("disk"))
    state = _declared_state(reading)
    free = _nonnegative_integer(reading.get("free_bytes"))
    total = _nonnegative_integer(reading.get("total_bytes"))
    if state == "known" and (
        free is None or total is None or total == 0 or free > total
    ):
        state = "invalid"
    if state != "known":
        return {
            "state": state,
            "free_bytes": None,
            "total_bytes": None,
            "projected_free_bytes": None,
        }
    return {
        "state": "known",
        "free_bytes": free,
        "total_bytes": total,
        "projected_free_bytes": free - PAGEFILE_STEP_MIB * MEBIBYTE,
    }


def _evidence_state(*states: str) -> str:
    if "invalid" in states:
        return "invalid"
    known = states.count("known")
    if known == len(states):
        return "known"
    if known:
        return "partial"
    return "unknown"


def _check(state: str, **evidence: Any) -> dict[str, Any]:
    return {"state": state, **evidence}


def propose_pagefile_plan(
    host_snapshot: Mapping[str, Any] | object,
    pagefile_observation: Mapping[str, Any] | object,
) -> dict[str, Any]:
    """Derive a content-free, non-executable one-step pagefile proposal.

    ``pagefile_observation`` must describe a separately measured configured
    maximum as ``{"state": "known", "maximum_mib": N}``.  The Phase 6
    estimated pagefile capacity is deliberately not treated as configuration.
    Unknown required evidence prevents a proposal; unrelated partial host
    telemetry does not erase known commit and disk evidence.
    """
    snapshot = _mapping(host_snapshot)
    current = _pagefile_observation(pagefile_observation)
    commit = _commit_observation(snapshot)
    disk = _disk_observation(snapshot)

    candidate = None
    if current["state"] == "known":
        candidate = current["maximum_mib"] + PAGEFILE_STEP_MIB
        cap_state = (
            "pass"
            if current["maximum_mib"] <= PAGEFILE_ABSOLUTE_MAX_MIB
            and candidate <= PAGEFILE_ABSOLUTE_MAX_MIB
            else "fail"
        )
    else:
        cap_state = current["state"]

    if commit["state"] == "known":
        commit_state = (
            "pass"
            if (
                commit["headroom_bytes"] * COMMIT_HEADROOM_TRIGGER_DENOMINATOR
                < commit["limit_bytes"] * COMMIT_HEADROOM_TRIGGER_NUMERATOR
            )
            else "fail"
        )
    else:
        commit_state = commit["state"]

    if disk["state"] == "known":
        disk_state = (
            "pass"
            if disk["projected_free_bytes"] >= MIN_PROJECTED_SYSTEM_DISK_FREE_BYTES
            else "fail"
        )
    else:
        disk_state = disk["state"]

    checks = {
        "commit_headroom_below_trigger": _check(
            commit_state,
            trigger_fraction=COMMIT_HEADROOM_TRIGGER_FRACTION,
        ),
        "absolute_maximum": _check(
            cap_state,
            candidate_maximum_mib=candidate,
            absolute_maximum_mib=PAGEFILE_ABSOLUTE_MAX_MIB,
        ),
        "projected_system_disk_floor": _check(
            disk_state,
            minimum_free_bytes=MIN_PROJECTED_SYSTEM_DISK_FREE_BYTES,
        ),
    }
    evidence_state = _evidence_state(
        current["state"], commit["state"], disk["state"]
    )

    plan = None
    if commit_state == "fail":
        state = "not_recommended"
        decision_codes = ("commit_headroom_at_or_above_trigger",)
    elif "invalid" in (current["state"], commit["state"], disk["state"]):
        state = "blocked"
        decision_codes = ("invalid_required_evidence",)
    elif cap_state == "fail":
        state = "blocked"
        decision_codes = ("absolute_maximum_would_be_exceeded",)
    elif disk_state == "fail":
        state = "blocked"
        decision_codes = ("projected_system_disk_floor_would_be_violated",)
    elif "unknown" in (current["state"], commit["state"], disk["state"]):
        state = "unknown"
        decision_codes = tuple(
            f"{name}_unknown"
            for name, observation in (
                ("pagefile_maximum", current),
                ("commit", commit),
                ("disk", disk),
            )
            if observation["state"] == "unknown"
        )
    elif (commit_state, cap_state, disk_state) == ("pass", "pass", "pass"):
        state = "proposed"
        decision_codes = ("one_step_proposal_ready",)
        plan = {
            "schema": PROPOSAL_SCHEMA,
            "operation": "pagefile_maximum_increase",
            "execution_state": "proposal_only",
            "current_maximum_mib": current["maximum_mib"],
            "proposed_maximum_mib": candidate,
            "increase_mib": PAGEFILE_STEP_MIB,
            "future_requirements": FUTURE_EXECUTION_REQUIREMENTS,
        }
    else:
        state = "unknown"
        decision_codes = ("required_evidence_unresolved",)

    host_state = snapshot.get("state")
    if host_state not in {"ready", "partial", "warming", "unknown"}:
        host_state = "unknown"
    return {
        "schema": PROPOSAL_SCHEMA,
        "state": state,
        "evidence_state": evidence_state,
        "host_snapshot_state": host_state,
        "decision_codes": decision_codes,
        "policy": {
            "step_mib": PAGEFILE_STEP_MIB,
            "absolute_maximum_mib": PAGEFILE_ABSOLUTE_MAX_MIB,
            "minimum_projected_system_disk_free_bytes": (
                MIN_PROJECTED_SYSTEM_DISK_FREE_BYTES
            ),
            "commit_headroom_trigger_fraction": COMMIT_HEADROOM_TRIGGER_FRACTION,
        },
        "observations": {
            "pagefile": current,
            "commit": commit,
            "disk": disk,
        },
        "checks": checks,
        "plan": plan,
    }


__all__ = [
    "COMMIT_HEADROOM_TRIGGER_FRACTION",
    "FUTURE_EXECUTION_REQUIREMENTS",
    "MIN_PROJECTED_SYSTEM_DISK_FREE_BYTES",
    "PAGEFILE_ABSOLUTE_MAX_MIB",
    "PAGEFILE_STEP_MIB",
    "PROPOSAL_SCHEMA",
    "measure_host_pressure",
    "propose_pagefile_plan",
]
