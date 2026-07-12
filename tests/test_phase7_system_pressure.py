"""Read-only Phase 7 system-pressure and pagefile-proposal contracts."""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import inspect

import pytest

from alpecca import host_resources, system_pressure


GiB = 1024**3
PAGE_BYTES = 4096


class _StaticSampler:
    def __init__(self, value: object = None, *, error: Exception | None = None):
        self.value = value
        self.error = error
        self.calls: list[bool] = []

    def snapshot(self, force: bool = False):
        self.calls.append(force)
        if self.error is not None:
            raise self.error
        return self.value


def _snapshot(
    *,
    state: str = "ready",
    commit_used_bytes: int | None = 90 * GiB,
    commit_limit_bytes: int | None = 100 * GiB,
    disk_free_bytes: int | None = 100 * GiB,
    disk_total_bytes: int | None = 500 * GiB,
) -> dict:
    commit_known = commit_used_bytes is not None and commit_limit_bytes is not None
    disk_known = disk_free_bytes is not None and disk_total_bytes is not None
    return {
        "state": state,
        "timestamp": 123.0,
        "commit": {
            "state": "known" if commit_known else "unknown",
            "used_bytes": commit_used_bytes,
            "limit_bytes": commit_limit_bytes,
            "headroom_bytes": (
                commit_limit_bytes - commit_used_bytes if commit_known else None
            ),
            "headroom_fraction": (
                round((commit_limit_bytes - commit_used_bytes) / commit_limit_bytes, 4)
                if commit_known
                else None
            ),
        },
        "disk": {
            "state": "known" if disk_known else "unknown",
            "free_bytes": disk_free_bytes,
            "total_bytes": disk_total_bytes,
            "headroom_bytes": disk_free_bytes,
            "headroom_fraction": (
                round(disk_free_bytes / disk_total_bytes, 4) if disk_known else None
            ),
        },
        "assessment": {
            "pressure": 0.9 if commit_known else None,
            "severity": "high" if commit_known else "unknown",
        },
    }


def _pagefile(maximum_mib: int | None = 38000, *, state: str = "known") -> dict:
    return {"state": state, "maximum_mib": maximum_mib}


def test_measurement_uses_fresh_phase6_sample_and_returns_an_independent_copy():
    source = _snapshot()
    sampler = _StaticSampler(source)

    measured = system_pressure.measure_host_pressure(sampler)

    assert sampler.calls == [True]
    assert measured == source
    assert measured is not source
    measured["commit"]["used_bytes"] = 1
    assert source["commit"]["used_bytes"] == 90 * GiB


@pytest.mark.parametrize("telemetry_available", (True, False))
def test_default_measurement_cannot_reach_transitive_command_probe(
    monkeypatch,
    telemetry_available: bool,
):
    command_attempts: list[str] = []

    def forbidden_command(*_args, **_kwargs):
        command_attempts.append("command")
        raise AssertionError("Phase 7 default measurement reached a command probe")

    performance = (
        {
            "ram_total_bytes": 24 * GiB,
            "ram_available_bytes": 8 * GiB,
            "commit_used_bytes": 40 * GiB,
            "commit_limit_bytes": 64 * GiB,
        }
        if telemetry_available
        else None
    )
    disk = (
        {"disk_free_bytes": 100 * GiB, "disk_total_bytes": 500 * GiB}
        if telemetry_available
        else None
    )
    monkeypatch.setattr(
        host_resources.HostResourceSampler,
        "_read_performance_info",
        lambda _self: performance,
    )
    monkeypatch.setattr(
        host_resources.HostResourceSampler,
        "_read_disk_usage",
        lambda _self: disk,
    )
    monkeypatch.setattr(
        host_resources.HostResourceSampler,
        "_read_gpu_status",
        forbidden_command,
    )
    monkeypatch.setattr(host_resources.shutil, "which", forbidden_command)
    monkeypatch.setattr(host_resources.subprocess, "run", forbidden_command)

    measured = system_pressure.measure_host_pressure()

    assert command_attempts == []
    expected_state = "known" if telemetry_available else "unknown"
    assert measured["commit"]["state"] == expected_state
    assert measured["disk"]["state"] == expected_state
    if telemetry_available:
        assert measured["commit"]["used_bytes"] == 40 * GiB
        assert measured["commit"]["limit_bytes"] == 64 * GiB
        assert measured["disk"]["free_bytes"] == 100 * GiB
        assert measured["disk"]["total_bytes"] == 500 * GiB
    else:
        assert measured["commit"]["used_bytes"] is None
        assert measured["commit"]["limit_bytes"] is None
        assert measured["disk"]["free_bytes"] is None
        assert measured["disk"]["total_bytes"] is None


def test_partial_host_telemetry_keeps_unknowns_but_can_use_known_required_evidence():
    snapshot = _snapshot(state="partial")
    snapshot["cpu"] = {"state": "unknown", "percent": None}
    snapshot["assessment"]["unknown_resources"] = ["cpu", "battery", "vram"]

    result = system_pressure.propose_pagefile_plan(snapshot, _pagefile())

    assert result["host_snapshot_state"] == "partial"
    assert snapshot["cpu"] == {"state": "unknown", "percent": None}
    assert result["evidence_state"] == "known"
    assert result["state"] == "proposed"


@pytest.mark.parametrize(
    "missing_resource",
    ("commit", "disk"),
)
def test_partial_required_telemetry_remains_unknown_and_cannot_propose(
    missing_resource: str,
):
    kwargs = (
        {"commit_used_bytes": None, "commit_limit_bytes": None}
        if missing_resource == "commit"
        else {"disk_free_bytes": None, "disk_total_bytes": None}
    )
    snapshot = _snapshot(state="partial", **kwargs)

    result = system_pressure.propose_pagefile_plan(snapshot, _pagefile())

    assert result["state"] == "unknown"
    assert result["evidence_state"] == "partial"
    assert result["observations"][missing_resource]["state"] == "unknown"
    assert result["checks"][
        "commit_headroom_below_trigger"
        if missing_resource == "commit"
        else "projected_system_disk_floor"
    ]["state"] == "unknown"
    assert result["plan"] is None


def test_unknown_measurement_and_plan_never_fabricate_zero_full_or_critical():
    sampler = _StaticSampler(error=OSError("unavailable"))

    measured = system_pressure.measure_host_pressure(sampler)
    result = system_pressure.propose_pagefile_plan(
        measured,
        _pagefile(None, state="unknown"),
    )

    assert measured["state"] == "unknown"
    assert measured["assessment"]["pressure"] is None
    assert measured["assessment"]["severity"] == "unknown"
    assert measured["commit"]["headroom_fraction"] is None
    assert measured["disk"]["free_bytes"] is None
    assert result["state"] == "unknown"
    assert result["evidence_state"] == "unknown"
    assert result["plan"] is None
    assert result["observations"]["commit"]["headroom_fraction"] is None
    assert result["observations"]["disk"]["free_bytes"] is None


def test_estimated_phase6_capacity_cannot_replace_measured_configured_maximum():
    snapshot = _snapshot()
    snapshot["pagefile"] = {
        "state": "estimated",
        "estimated_capacity_bytes": 38000 * 1024**2,
        "configuration_read": False,
    }

    result = system_pressure.propose_pagefile_plan(
        snapshot,
        _pagefile(None, state="unknown"),
    )

    assert result["state"] == "unknown"
    assert result["observations"]["pagefile"] == {
        "state": "unknown",
        "maximum_mib": None,
    }
    assert result["checks"]["absolute_maximum"]["state"] == "unknown"
    assert result["plan"] is None


def test_exactly_one_4096_mib_step_is_proposed_from_measured_current_maximum():
    result = system_pressure.propose_pagefile_plan(_snapshot(), _pagefile(38000))

    assert result["state"] == "proposed"
    assert result["checks"]["commit_headroom_below_trigger"]["state"] == "pass"
    assert result["checks"]["absolute_maximum"]["state"] == "pass"
    assert result["checks"]["projected_system_disk_floor"]["state"] == "pass"
    assert result["plan"] == {
        "schema": system_pressure.PROPOSAL_SCHEMA,
        "operation": "pagefile_maximum_increase",
        "execution_state": "proposal_only",
        "current_maximum_mib": 38000,
        "proposed_maximum_mib": 42096,
        "increase_mib": 4096,
        "future_requirements": (
            "fresh_live_remeasurement",
            "separate_authenticated_one_use_creator_approval",
            "separate_minimal_elevated_helper",
            "single_bounded_write",
            "post_write_readback",
        ),
    }


@pytest.mark.parametrize("commit_used_bytes", (70 * GiB, 80 * GiB))
def test_sufficient_commit_headroom_does_not_recommend_an_increase(
    commit_used_bytes: int,
):
    snapshot = _snapshot(
        commit_used_bytes=commit_used_bytes,
        commit_limit_bytes=100 * GiB,
    )

    result = system_pressure.propose_pagefile_plan(snapshot, _pagefile())

    assert result["state"] == "not_recommended"
    assert result["decision_codes"] == ("commit_headroom_at_or_above_trigger",)
    assert result["checks"]["commit_headroom_below_trigger"]["state"] == "fail"
    assert result["plan"] is None


@pytest.mark.parametrize(
    ("headroom_delta", "expected_state", "expected_check"),
    (
        (-PAGE_BYTES, "proposed", "pass"),
        (0, "not_recommended", "fail"),
        (PAGE_BYTES, "not_recommended", "fail"),
    ),
)
def test_commit_headroom_uses_exact_strict_integer_boundary(
    headroom_delta: int,
    expected_state: str,
    expected_check: str,
):
    limit = 100 * GiB
    headroom = limit // 5 + headroom_delta
    snapshot = _snapshot(
        commit_used_bytes=limit - headroom,
        commit_limit_bytes=limit,
    )

    result = system_pressure.propose_pagefile_plan(snapshot, _pagefile())

    assert result["observations"]["commit"]["headroom_bytes"] == headroom
    # All three display values round to 0.2; the decision must not use them.
    assert result["observations"]["commit"]["headroom_fraction"] == 0.2
    assert result["checks"]["commit_headroom_below_trigger"]["state"] == (
        expected_check
    )
    assert result["state"] == expected_state


@pytest.mark.parametrize(
    ("maximum_mib", "expected_state", "expected_candidate"),
    (
        (51200, "proposed", 55296),
        (54384, "blocked", 58480),
        (55296, "blocked", 59392),
    ),
)
def test_absolute_cap_is_fixed_and_checked_before_proposal(
    maximum_mib: int,
    expected_state: str,
    expected_candidate: int,
):
    result = system_pressure.propose_pagefile_plan(
        _snapshot(),
        _pagefile(maximum_mib),
    )

    assert result["state"] == expected_state
    assert result["checks"]["absolute_maximum"]["candidate_maximum_mib"] == (
        expected_candidate
    )
    if expected_state == "blocked":
        assert result["plan"] is None


@pytest.mark.parametrize(
    ("disk_free_bytes", "expected_state"),
    (
        (44 * GiB, "proposed"),
        (44 * GiB - 1, "blocked"),
    ),
)
def test_projected_disk_floor_is_an_exact_hard_boundary(
    disk_free_bytes: int,
    expected_state: str,
):
    result = system_pressure.propose_pagefile_plan(
        _snapshot(disk_free_bytes=disk_free_bytes),
        _pagefile(),
    )

    assert result["state"] == expected_state
    assert result["observations"]["disk"]["projected_free_bytes"] == (
        disk_free_bytes - 4 * GiB
    )
    if expected_state == "blocked":
        assert result["decision_codes"] == (
            "projected_system_disk_floor_would_be_violated",
        )
        assert result["plan"] is None


def test_policy_limits_are_not_read_from_environment(monkeypatch):
    monkeypatch.setenv("ALPECCA_PAGEFILE_STEP_MB", "1")
    monkeypatch.setenv("ALPECCA_PAGEFILE_MAX_MB", "999999")
    monkeypatch.setenv("ALPECCA_PAGEFILE_MIN_FREE_GB", "0")
    monkeypatch.setenv("ALPECCA_PAGEFILE_TARGET_COMMIT_HEADROOM", "1")

    result = system_pressure.propose_pagefile_plan(_snapshot(), _pagefile())

    assert result["policy"] == {
        "step_mib": 4096,
        "absolute_maximum_mib": 55296,
        "minimum_projected_system_disk_free_bytes": 40 * GiB,
        "commit_headroom_trigger_fraction": 0.20,
    }
    assert result["plan"]["proposed_maximum_mib"] == 42096


def test_module_contains_no_command_cim_persistence_or_approval_consumer():
    source = inspect.getsource(system_pressure)
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(
                alias.name.split(".", 1)[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }

    assert imported_roots.isdisjoint(
        {"ctypes", "os", "secrets", "sqlite3", "subprocess"}
    )
    assert "Set-CimInstance" not in source
    assert "Win32_PageFileSetting" not in source
    assert function_names.isdisjoint(
        {
            "approve_pagefile_request",
            "apply_pagefile_request",
            "create_pagefile_request",
            "init_db",
            "_apply_pagefile_max",
        }
    )
    assert not hasattr(system_pressure, "approve_pagefile_request")
    assert not hasattr(system_pressure, "apply_pagefile_request")
    sampler_source = inspect.getsource(system_pressure._command_free_host_sampler)
    assert "_gpu_probe=_unavailable_probe" in sampler_source


def test_plan_is_content_free_and_exposes_only_a_future_execution_boundary():
    result = system_pressure.propose_pagefile_plan(_snapshot(), _pagefile())
    plan = result["plan"]

    assert plan["execution_state"] == "proposal_only"
    assert not set(plan).intersection(
        {"approval_code", "command", "content", "credential", "path", "script", "token"}
    )
    assert "separate_authenticated_one_use_creator_approval" in plan[
        "future_requirements"
    ]
    assert "separate_minimal_elevated_helper" in plan["future_requirements"]


def test_concurrent_planning_is_pure_deterministic_and_input_preserving():
    snapshot = _snapshot(state="partial")
    snapshot["cpu"] = {"state": "unknown", "percent": None}
    pagefile = _pagefile()
    original_snapshot = deepcopy(snapshot)
    original_pagefile = deepcopy(pagefile)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(
            pool.map(
                lambda _index: system_pressure.propose_pagefile_plan(
                    snapshot,
                    pagefile,
                ),
                range(96),
            )
        )

    assert all(result == results[0] for result in results)
    assert all(result is not results[0] for result in results[1:])
    results[0]["plan"]["proposed_maximum_mib"] = 1
    assert all(result["plan"]["proposed_maximum_mib"] == 42096 for result in results[1:])
    assert snapshot == original_snapshot
    assert pagefile == original_pagefile
