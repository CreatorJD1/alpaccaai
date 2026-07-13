"""Read-only Phase 7 host-pressure measurement and pagefile preparation.

This module can observe through the established Phase 6 sampler and derive one
bounded proposal from explicitly supplied pagefile-configuration evidence. It
can also assess whether a supplied Phase 6 report is structurally eligible for
manual safe-8K review. It contains no persistence, approval, elevation, command
construction, or system mutation capability. A later, separately reviewed
boundary must authenticate one-use creator approval, remeasure live state,
perform any elevated write, and verify the result.
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
BROKER_PREREQUISITE_SCHEMA = (
    "alpecca.phase7.pagefile-broker-prerequisite.v1"
)
BROKER_REQUIRED_CONTEXT_TIER = 8192
BROKER_REQUIRED_CONTEXT_MODEL = "qwen3.5:9b"
BROKER_REQUIRED_CREATOR_PRINCIPAL = "CreatorJD"
FUTURE_EXECUTION_REQUIREMENTS = (
    "documented_safe_8192_measurement",
    "fresh_live_pagefile_commit_disk_readback",
    "authenticated_one_use_creatorjd_approval",
    "uac_elevation",
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


def _empty_json_list(value: object) -> bool:
    return type(value) is list and not value


def _measurement_sample_summary(value: object) -> dict[str, Any]:
    sample = _mapping(value)
    data = _mapping(sample.get("data"))
    assessment = _mapping(data.get("assessment"))
    severity = assessment.get("severity")
    if severity not in {"normal", "elevated"}:
        severity = None
    return {
        "collected": sample.get("collected") is True,
        "severity": severity,
        "request_in_flight": sample.get("request_in_flight") is True,
    }


def assess_pagefile_broker_prerequisite(
    measurement_report: Mapping[str, Any] | object,
) -> dict[str, Any]:
    """Assess a Phase 6 report without authorizing or constructing a broker.

    Passing this structural assessment means only that the report is eligible
    for manual safe-8K review. It is not evidence authentication, CreatorJD
    approval, UAC consent, fresh live readback, or authority to change the host.
    """
    report = _mapping(measurement_report)
    preflight = _mapping(report.get("preflight"))
    request = _mapping(report.get("request"))
    marker = _mapping(report.get("marker_verification"))
    resources = _mapping(report.get("resources"))
    manual_review = _mapping(report.get("manual_review"))
    side_effects = _mapping(report.get("side_effects"))

    samples = {
        phase: _measurement_sample_summary(resources.get(phase))
        for phase in ("before", "during", "after")
    }
    identity_ok = (
        type(report.get("schema_version")) is int
        and report.get("schema_version") == 1
        and report.get("kind") == "alpecca_context_tier_measurement"
        and type(report.get("tier")) is int
        and report.get("tier") == BROKER_REQUIRED_CONTEXT_TIER
        and report.get("model") == BROKER_REQUIRED_CONTEXT_MODEL
    )
    completion_ok = (
        report.get("status") == "completed"
        and report.get("mode") == "execute"
    )
    preflight_ok = (
        preflight.get("performed") is True
        and preflight.get("status") == "passed"
        and preflight.get("request_permitted") is True
        and preflight.get("evidence_state") == "observed"
        and preflight.get("sample_collected") is True
        and _empty_json_list(preflight.get("reasons"))
        and _empty_json_list(preflight.get("unknowns"))
    )
    request_ok = (
        request.get("allowed") is True
        and request.get("attempted") is True
        and type(request.get("http_request_count")) is int
        and request.get("http_request_count") == 1
        and type(request.get("http_request_count_limit")) is int
        and request.get("http_request_count_limit") == 1
    )
    marker_ok = (
        marker.get("checked") is True
        and marker.get("response_contains_marker") is True
        and marker.get("verified") is True
    )
    resources_ok = (
        all(
            sample["collected"] and sample["severity"] is not None
            for sample in samples.values()
        )
        and samples["during"]["request_in_flight"]
        and _empty_json_list(report.get("unknowns"))
    )
    manual_review_ok = (
        report.get("manual_review_only") is True
        and manual_review.get("required") is True
        and manual_review.get("decision") == "manual_review_only"
    )
    side_effects_ok = (
        report.get("automatic_promotion") is False
        and report.get("system_settings_mutated") is False
        and report.get("pagefile_mutated") is False
        and side_effects
        == {
            "downloads_requested": False,
            "files_written": False,
            "system_settings_mutated": False,
            "pagefile_mutated": False,
        }
    )

    checks = {
        "measurement_identity": _check(
            "pass" if identity_ok else "fail",
            required_tier=BROKER_REQUIRED_CONTEXT_TIER,
            required_model=BROKER_REQUIRED_CONTEXT_MODEL,
        ),
        "completed_execute_measurement": _check(
            "pass" if completion_ok else "fail"
        ),
        "fully_observed_safe_preflight": _check(
            "pass" if preflight_ok else "fail"
        ),
        "exactly_one_request": _check("pass" if request_ok else "fail"),
        "marker_verified": _check("pass" if marker_ok else "fail"),
        "complete_nonblocking_resource_samples": _check(
            "pass" if resources_ok else "fail",
            samples=samples,
        ),
        "manual_review_contract": _check(
            "pass" if manual_review_ok else "fail"
        ),
        "measurement_side_effect_free": _check(
            "pass" if side_effects_ok else "fail"
        ),
    }
    failed = tuple(
        f"{name}_failed"
        for name, check in checks.items()
        if check["state"] != "pass"
    )
    if failed:
        state = "blocked"
        decision_codes = failed
    else:
        state = "review_required"
        decision_codes = ("manual_safe_8192_measurement_review_required",)

    return {
        "schema": BROKER_PREREQUISITE_SCHEMA,
        "state": state,
        "execution_state": "preparation_only",
        "broker_authorized": False,
        "host_mutation_capability": False,
        "manual_review_required": True,
        "required_creator_principal": BROKER_REQUIRED_CREATOR_PRINCIPAL,
        "decision_codes": decision_codes,
        "checks": checks,
        "deferred_execution_requirements": FUTURE_EXECUTION_REQUIREMENTS,
        "policy": {
            "step_mib": PAGEFILE_STEP_MIB,
            "absolute_maximum_mib": PAGEFILE_ABSOLUTE_MAX_MIB,
            "minimum_projected_system_disk_free_bytes": (
                MIN_PROJECTED_SYSTEM_DISK_FREE_BYTES
            ),
            "uac_required": True,
            "fresh_live_readback_required": True,
            "post_write_readback_required": True,
        },
    }


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
    "BROKER_PREREQUISITE_SCHEMA",
    "BROKER_REQUIRED_CONTEXT_MODEL",
    "BROKER_REQUIRED_CONTEXT_TIER",
    "BROKER_REQUIRED_CREATOR_PRINCIPAL",
    "COMMIT_HEADROOM_TRIGGER_FRACTION",
    "FUTURE_EXECUTION_REQUIREMENTS",
    "MIN_PROJECTED_SYSTEM_DISK_FREE_BYTES",
    "PAGEFILE_ABSOLUTE_MAX_MIB",
    "PAGEFILE_STEP_MIB",
    "PROPOSAL_SCHEMA",
    "assess_pagefile_broker_prerequisite",
    "measure_host_pressure",
    "propose_pagefile_plan",
]
