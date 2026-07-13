"""Preparatory Phase 7 pagefile-broker prerequisite checks."""
from __future__ import annotations

from copy import deepcopy

import pytest

from alpecca import system_pressure


GiB = 1024**3


def _sample(phase: str, *, severity: str = "normal") -> dict:
    sample = {
        "phase": phase,
        "captured_at_unix_s": 100.0,
        "collected": True,
        "data": {
            "assessment": {
                "severity": severity,
                "unknown_resources": [],
            }
        },
    }
    if phase == "during":
        sample["request_in_flight"] = True
    return sample


def _completed_report() -> dict:
    return {
        "schema_version": 1,
        "kind": "alpecca_context_tier_measurement",
        "status": "completed",
        "mode": "execute",
        "tier": 8192,
        "model": "qwen3.5:9b",
        "automatic_promotion": False,
        "system_settings_mutated": False,
        "pagefile_mutated": False,
        "manual_review_only": True,
        "manual_review": {
            "required": True,
            "decision": "manual_review_only",
        },
        "preflight": {
            "performed": True,
            "status": "passed",
            "request_permitted": True,
            "evidence_state": "observed",
            "sample_collected": True,
            "reasons": [],
            "unknowns": [],
        },
        "request": {
            "allowed": True,
            "attempted": True,
            "http_request_count": 1,
            "http_request_count_limit": 1,
        },
        "marker_verification": {
            "checked": True,
            "response_contains_marker": True,
            "verified": True,
        },
        "resources": {
            phase: _sample(phase) for phase in ("before", "during", "after")
        },
        "side_effects": {
            "downloads_requested": False,
            "files_written": False,
            "system_settings_mutated": False,
            "pagefile_mutated": False,
        },
        "unknowns": [],
    }


def _documented_blocked_report() -> dict:
    report = _completed_report()
    report["status"] = "blocked"
    report["preflight"].update(
        {
            "status": "blocked",
            "request_permitted": False,
            "reasons": [{"code": "host_assessment_high"}],
        }
    )
    report["request"].update(
        {"allowed": False, "attempted": False, "http_request_count": 0}
    )
    report["marker_verification"].update(
        {
            "checked": False,
            "response_contains_marker": None,
            "verified": None,
        }
    )
    report["resources"]["before"] = _sample("before", severity="high")
    report["resources"]["during"] = None
    report["resources"]["after"] = None
    report["unknowns"] = ["Execution preflight blocked the Ollama request."]
    return report


def test_documented_blocked_8k_run_cannot_open_the_broker_gate():
    result = system_pressure.assess_pagefile_broker_prerequisite(
        _documented_blocked_report()
    )

    assert result["state"] == "blocked"
    assert result["execution_state"] == "preparation_only"
    assert result["broker_authorized"] is False
    assert result["host_mutation_capability"] is False
    assert result["checks"]["completed_execute_measurement"]["state"] == "fail"
    assert result["checks"]["fully_observed_safe_preflight"]["state"] == "fail"
    assert result["checks"]["exactly_one_request"]["state"] == "fail"
    assert result["checks"]["marker_verified"]["state"] == "fail"


def test_structurally_complete_report_still_requires_manual_review():
    report = _completed_report()
    original = deepcopy(report)

    result = system_pressure.assess_pagefile_broker_prerequisite(report)

    assert result["state"] == "review_required"
    assert result["decision_codes"] == (
        "manual_safe_8192_measurement_review_required",
    )
    assert result["broker_authorized"] is False
    assert result["required_creator_principal"] == "CreatorJD"
    assert all(check["state"] == "pass" for check in result["checks"].values())
    assert report == original


@pytest.mark.parametrize(
    ("field", "value", "failed_check"),
    (
        ("tier", 16384, "measurement_identity"),
        ("model", "qwen3.5:4b", "measurement_identity"),
        ("pagefile_mutated", True, "measurement_side_effect_free"),
    ),
)
def test_wrong_identity_or_any_reported_mutation_blocks_preparation(
    field: str,
    value: object,
    failed_check: str,
):
    report = _completed_report()
    report[field] = value

    result = system_pressure.assess_pagefile_broker_prerequisite(report)

    assert result["state"] == "blocked"
    assert result["checks"][failed_check]["state"] == "fail"
    assert result["broker_authorized"] is False


@pytest.mark.parametrize("severity", ("high", "critical", "unknown"))
def test_unsafe_or_unknown_during_or_after_sample_blocks_preparation(
    severity: str,
):
    report = _completed_report()
    report["resources"]["during"] = _sample("during", severity=severity)

    result = system_pressure.assess_pagefile_broker_prerequisite(report)

    assert result["state"] == "blocked"
    assert result["checks"]["complete_nonblocking_resource_samples"][
        "state"
    ] == "fail"


def test_preparation_exposes_exact_deferred_policy_without_execution_material():
    result = system_pressure.assess_pagefile_broker_prerequisite(
        _completed_report()
    )

    assert result["policy"] == {
        "step_mib": 4096,
        "absolute_maximum_mib": 55296,
        "minimum_projected_system_disk_free_bytes": 40 * GiB,
        "uac_required": True,
        "fresh_live_readback_required": True,
        "post_write_readback_required": True,
    }
    assert result["deferred_execution_requirements"] == (
        "documented_safe_8192_measurement",
        "fresh_live_pagefile_commit_disk_readback",
        "authenticated_one_use_creatorjd_approval",
        "uac_elevation",
        "separate_minimal_elevated_helper",
        "single_bounded_write",
        "post_write_readback",
    )
    assert not set(result).intersection(
        {"approval", "command", "credential", "script", "token"}
    )
