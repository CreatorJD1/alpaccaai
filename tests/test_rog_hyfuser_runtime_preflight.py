from __future__ import annotations

from pathlib import Path

import pytest

from scripts import preflight_rog_hyfuser_runtime as preflight


ROOT = Path(__file__).resolve().parents[1]


def _host(**overrides: str) -> preflight.HostFacts:
    values = {
        "hostname": "JASON_HOLYROG",
        "system": "Windows",
        "machine": "AMD64",
        "python_version": "3.11.9",
        "python_implementation": "CPython",
        "python_bits": "64bit",
    }
    values.update(overrides)
    return preflight.HostFacts(**values)


def _gpu(
    row: str = "NVIDIA GeForce RTX 4060 Laptop GPU, 572.83, 8188\n",
) -> preflight.CommandResult:
    return preflight.CommandResult(returncode=0, stdout=row, status="ok")


def _states(report: dict[str, object]) -> dict[str, str]:
    return {item["id"]: item["status"] for item in report["checks"]}


def test_exact_holyrog_runtime_is_ready_but_never_authorizes_activation() -> None:
    report = preflight.evaluate_preflight(_host(), _gpu())

    assert report["status"] == "ready"
    assert report["ready"] is True
    assert report["shadow_only"] is True
    assert report["authorizes_activation"] is False
    assert report["installation_performed"] is False
    assert set(_states(report).values()) == {"pass"}


@pytest.mark.parametrize(
    ("host_overrides", "gpu_result", "failed_check"),
    [
        ({"hostname": "RygenART"}, _gpu(), "assigned_host"),
        ({"python_version": "3.13.5"}, _gpu(), "python_3_11_9"),
        ({}, _gpu("NVIDIA GeForce RTX 4060 Laptop GPU, 528.33, 8188\n"), "driver_cuda_12_8"),
        ({}, _gpu("NVIDIA GeForce RTX 4060 Laptop GPU, 572.83, 4096\n"), "vram_capacity"),
        ({}, preflight.CommandResult(127, status="unavailable"), "nvidia_query"),
    ],
)
def test_missing_or_incompatible_evidence_fails_closed(
    host_overrides: dict[str, str],
    gpu_result: preflight.CommandResult,
    failed_check: str,
) -> None:
    report = preflight.evaluate_preflight(_host(**host_overrides), gpu_result)

    assert report["status"] == "blocked"
    assert report["ready"] is False
    assert report["authorizes_activation"] is False
    assert _states(report)[failed_check] == "fail"


def test_preflight_runs_only_the_fixed_read_only_nvidia_query() -> None:
    observed: list[tuple[tuple[str, ...], float]] = []

    def runner(command, timeout):
        observed.append((tuple(command), timeout))
        return _gpu()

    report = preflight.run_preflight(
        host_facts=_host(),
        tool_finder=lambda name: "nvidia-smi.exe" if name.endswith(".exe") else None,
        command_runner=runner,
    )

    assert report["ready"] is True
    assert observed == [
        (("nvidia-smi.exe", *preflight.NVIDIA_QUERY), preflight.COMMAND_TIMEOUT_SECONDS)
    ]


def test_command_runner_rejects_any_command_outside_allowlist() -> None:
    with pytest.raises(ValueError, match="read-only allowlist"):
        preflight.run_nvidia_query(("nvidia-smi.exe", "--gpu-reset"), 1.0)


def test_requirements_lock_is_exact_and_does_not_add_unneeded_packages() -> None:
    contents = (ROOT / "requirements-rog-hyfuser-cu128.txt").read_text(encoding="utf-8")

    assert "--index-url https://download.pytorch.org/whl/cu128" in contents
    assert "torch==2.7.0;" in contents
    assert "python_version == \"3.11\"" in contents
    assert "torchvision" not in contents
    assert "torchaudio" not in contents


def test_preflight_source_never_imports_torch_or_mutates_the_machine() -> None:
    source = (ROOT / "scripts" / "preflight_rog_hyfuser_runtime.py").read_text(
        encoding="utf-8"
    )

    assert "import torch" not in source
    assert "pip install" not in source
    assert "subprocess.run" in source
    assert "shell=False" in source
