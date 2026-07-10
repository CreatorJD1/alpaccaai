"""Focused contract tests for Phase 6 host-resource snapshot sampling."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from types import SimpleNamespace

import pytest

from alpecca import host_resources


GiB = 1024**3


class _Clock:
    def __init__(self, value: float = 100.0):
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _sampler(
    *,
    cpu_samples: tuple[dict[str, int], ...] = (
        {"idle": 100, "kernel": 200, "user": 100},
        {"idle": 200, "kernel": 300, "user": 100},
    ),
    performance: dict[str, int] | None = None,
    battery: dict[str, object] | None = None,
    disk: dict[str, int] | None = None,
    gpu: dict[str, object] | None = None,
    clock: _Clock | None = None,
    use_default_gpu_probe: bool = False,
) -> tuple[host_resources.HostResourceSampler, dict[str, int]]:
    """Build a sampler entirely from its documented private test seams."""
    current_clock = clock or _Clock()
    samples = deque(deepcopy(cpu_samples))
    calls = {name: 0 for name in ("cpu", "memory", "battery", "disk", "gpu")}
    performance = performance or {
        "ram_total_bytes": 16 * GiB,
        "ram_available_bytes": 4 * GiB,
        "commit_used_bytes": 20 * GiB,
        "commit_limit_bytes": 32 * GiB,
    }
    disk = disk or {"disk_free_bytes": 400 * GiB, "disk_total_bytes": 512 * GiB}

    def cpu_probe():
        calls["cpu"] += 1
        return samples.popleft() if samples else None

    def performance_probe():
        calls["memory"] += 1
        return deepcopy(performance)

    def battery_probe():
        calls["battery"] += 1
        return deepcopy(battery)

    def disk_probe():
        calls["disk"] += 1
        return deepcopy(disk)

    def gpu_probe():
        calls["gpu"] += 1
        return deepcopy(gpu)

    kwargs: dict[str, object] = {
        "_clock": current_clock,
        "_monotonic": current_clock,
        "_cpu_probe": cpu_probe,
        "_performance_probe": performance_probe,
        "_battery_probe": battery_probe,
        "_disk_probe": disk_probe,
        "_is_windows": False,
    }
    if not use_default_gpu_probe:
        kwargs["_gpu_probe"] = gpu_probe
    return host_resources.HostResourceSampler(**kwargs), calls


def test_first_cpu_sample_is_warming_unknown_not_zero():
    sampler, _calls = _sampler()

    snapshot = sampler.snapshot()
    cpu = snapshot["assessment"]["readings"]["cpu"]

    assert snapshot["state"] == "warming"
    assert snapshot["source_states"]["cpu"] == "warming"
    assert snapshot["raw"]["cpu_percent"] is None
    assert snapshot["unknown_reasons"]["cpu_percent"] == "warming"
    assert cpu["state"] == "unknown"
    assert cpu["percent"] is None
    assert cpu["pressure"] is None


def test_explicit_zero_cpu_reading_is_known_after_warmup():
    sampler, _calls = _sampler()

    sampler.snapshot()
    snapshot = sampler.snapshot(force=True)
    cpu = snapshot["assessment"]["readings"]["cpu"]

    assert snapshot["source_states"]["cpu"] == "known"
    assert snapshot["raw"]["cpu_percent"] == 0.0
    assert cpu["state"] == "known"
    assert cpu["percent"] == 0.0
    assert cpu["pressure"] == 0.0


def test_ram_and_commit_headroom_math_feeds_resource_assessment():
    sampler, _calls = _sampler(
        performance={
            "ram_total_bytes": 16 * GiB,
            "ram_available_bytes": 4 * GiB,
            "commit_used_bytes": 24 * GiB,
            "commit_limit_bytes": 32 * GiB,
        },
    )

    snapshot = sampler.snapshot()
    headroom = snapshot["headroom"]
    readings = snapshot["assessment"]["readings"]

    assert snapshot["raw"]["ram_used_bytes"] == 12 * GiB
    assert headroom["ram"] == {"bytes": 4 * GiB, "fraction": 0.25}
    assert headroom["commit"] == {"bytes": 8 * GiB, "fraction": 0.25}
    assert headroom["ram_bytes"] == 4 * GiB
    assert headroom["commit_bytes"] == 8 * GiB
    assert snapshot["pagefile"]["estimated_capacity_bytes"] == 16 * GiB
    assert snapshot["pagefile"]["commit_headroom_bytes"] == 8 * GiB
    assert readings["ram"]["used_bytes"] == 12 * GiB
    assert readings["ram"]["pressure"] == pytest.approx(0.75)
    assert readings["commit"]["used_bytes"] == 24 * GiB
    assert readings["commit"]["pressure"] == pytest.approx(0.75)


def test_unavailable_battery_gpu_and_thermal_remain_unknown():
    sampler, _calls = _sampler(battery=None, gpu=None)

    snapshot = sampler.snapshot()
    readings = snapshot["assessment"]["readings"]

    for resource in ("battery", "vram", "thermal"):
        assert readings[resource]["state"] == "unknown"
        assert readings[resource]["known"] is False
        assert readings[resource]["pressure"] is None
    assert snapshot["raw"]["battery_percent"] is None
    assert snapshot["raw"]["vram_used_bytes"] is None
    assert snapshot["raw"]["thermal_celsius"] is None
    assert snapshot["source_states"]["battery"] == "unknown"
    assert snapshot["source_states"]["gpu"] == "unknown"


def test_nvidia_smi_uses_list_command_without_shell_and_short_timeout(monkeypatch):
    calls: list[tuple[object, dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(host_resources.shutil, "which", lambda _name: "nvidia-smi")
    monkeypatch.setattr(host_resources.subprocess, "run", fake_run)
    sampler, _probe_calls = _sampler(use_default_gpu_probe=True)

    snapshot = sampler.snapshot()

    assert snapshot["assessment"]["readings"]["vram"]["state"] == "unknown"
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert isinstance(command, list)
    assert command[0] == "nvidia-smi"
    assert kwargs["shell"] is False
    assert 0 < kwargs["timeout"] <= 3.0


def test_cached_snapshots_avoid_duplicate_probes():
    sampler, calls = _sampler()

    first = sampler.snapshot()
    second = sampler.snapshot()

    assert first == second
    assert first is not second
    assert calls == {"cpu": 1, "memory": 1, "battery": 1, "disk": 1, "gpu": 1}


def test_snapshot_contains_assessment_and_advisory_policy_without_mutation(monkeypatch):
    assessment_calls: list[dict[str, object]] = []
    policy_calls: list[dict[str, object]] = []
    assessment = {
        "pressure": 0.91,
        "severity": "high",
        "readings": {},
        "known_resources": ["ram"],
        "unknown_resources": [],
        "invalid_resources": [],
    }
    policy = {
        "action": "reduce_context",
        "defer_optional_work": True,
        "reduce_context": True,
        "require_recovery_notice": False,
    }

    def fake_assess_resources(**kwargs):
        assessment_calls.append(kwargs)
        return assessment

    def fake_decide(*, resource_assessment=None, memory_pressure=None):
        policy_calls.append({
            "resource_assessment": resource_assessment,
            "memory_pressure": memory_pressure,
        })
        return policy

    monkeypatch.setattr(host_resources.resource_signals, "assess_resources", fake_assess_resources)
    monkeypatch.setattr(host_resources.resource_policy, "decide", fake_decide)
    sampler, _calls = _sampler()

    snapshot = sampler.snapshot()

    assert snapshot["assessment"] == assessment
    assert snapshot["advisory"] == policy
    assert assessment_calls == [snapshot["raw"]]
    assert policy_calls == [{
        "resource_assessment": assessment,
        "memory_pressure": None,
    }]
    assert snapshot["pagefile"]["configuration_read"] is False
    assert "mutation" not in snapshot
