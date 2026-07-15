"""Focused tests for bounded, read-only Phase 7 pagefile telemetry."""
from __future__ import annotations

import base64
import inspect
import json
import subprocess

import pytest

from alpecca import pagefile_telemetry


def _raw(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema": "alpecca.phase7.pagefile-wmi.v1",
        "management_available": True,
        "automatic_managed": False,
        "settings_available": True,
        "settings_truncated": False,
        "settings_count": 1,
        "configured_initial_mib": 4096,
        "configured_maximum_mib": 42096,
        "usage_available": True,
        "usage_truncated": False,
        "usage_count": 1,
        "allocated_mib": 38000,
        "used_mib": 2048,
        "peak_used_mib": 4096,
    }
    value.update(overrides)
    return value


def _install_windows_result(
    monkeypatch: pytest.MonkeyPatch,
    raw: object,
    *,
    returncode: int = 0,
) -> list[tuple[tuple[str, ...], dict[str, object]]]:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    executable = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    monkeypatch.setattr(pagefile_telemetry, "_is_windows", lambda: True)
    monkeypatch.setattr(
        pagefile_telemetry,
        "_windows_powershell_executable",
        lambda: executable,
    )

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append((command, kwargs))
        stdout = raw if isinstance(raw, bytes) else json.dumps(raw).encode("utf-8")
        return subprocess.CompletedProcess(command, returncode, stdout, b"private stderr")

    monkeypatch.setattr(pagefile_telemetry.subprocess, "run", run)
    return calls


def test_non_windows_is_deterministic_and_never_spawns(monkeypatch):
    monkeypatch.setattr(pagefile_telemetry, "_is_windows", lambda: False)

    def forbidden_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("non-Windows telemetry must not spawn PowerShell")

    monkeypatch.setattr(pagefile_telemetry.subprocess, "run", forbidden_run)
    first = pagefile_telemetry.collect_pagefile_telemetry()
    second = pagefile_telemetry.collect_pagefile_telemetry()

    assert first == second
    assert first["state"] == "unavailable"
    assert first["platform"] == "non_windows"
    assert first["evidence"]["powershell"] == {
        "available": False,
        "state": "unavailable",
        "reason": "non_windows",
    }
    assert first["evidence"]["wmi"]["available"] is False
    assert first["configured"]["maximum_mib"] is None
    assert first["usage"]["free_mib"] is None


def test_fixed_encoded_query_reports_aggregate_configured_used_and_free(monkeypatch):
    calls = _install_windows_result(monkeypatch, _raw())

    result = pagefile_telemetry.collect_pagefile_telemetry()

    assert result["state"] == "ready"
    assert result["configured"] == {
        "state": "known",
        "mode": "custom",
        "initial_mib": 4096,
        "maximum_mib": 42096,
        "entry_count": 1,
    }
    assert result["usage"] == {
        "state": "known",
        "allocated_mib": 38000,
        "used_mib": 2048,
        "free_mib": 35952,
        "peak_used_mib": 4096,
        "entry_count": 1,
    }
    assert result["evidence"]["powershell"]["available"] is True
    assert result["evidence"]["wmi"]["available"] is True

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[0].endswith(r"WindowsPowerShell\v1.0\powershell.exe")
    assert command[1:-1] == (
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
    )
    decoded = base64.b64decode(command[-1]).decode("utf-16-le")
    assert "Win32_ComputerSystem" in decoded
    assert "Win32_PageFileSetting" in decoded
    assert "Win32_PageFileUsage" in decoded
    assert "InitialSize,MaximumSize" in decoded
    assert "AllocatedBaseSize,CurrentUsage,PeakUsage" in decoded
    assert kwargs == {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "timeout": pagefile_telemetry.POWERSHELL_TIMEOUT_SECONDS,
        "check": False,
        "shell": False,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def test_system_managed_configuration_does_not_invent_fixed_sizes(monkeypatch):
    _install_windows_result(
        monkeypatch,
        _raw(
            automatic_managed=True,
            settings_count=0,
            configured_initial_mib=0,
            configured_maximum_mib=0,
        ),
    )

    result = pagefile_telemetry.collect_pagefile_telemetry()

    assert result["configured"] == {
        "state": "known",
        "mode": "system_managed",
        "initial_mib": None,
        "maximum_mib": None,
        "entry_count": None,
    }
    assert result["state"] == "ready"


def test_disabled_pagefile_is_reported_as_known_zero_not_unknown(monkeypatch):
    _install_windows_result(
        monkeypatch,
        _raw(
            settings_count=0,
            configured_initial_mib=0,
            configured_maximum_mib=0,
            usage_count=0,
            allocated_mib=0,
            used_mib=0,
            peak_used_mib=0,
        ),
    )

    result = pagefile_telemetry.collect_pagefile_telemetry()

    assert result["configured"]["mode"] == "none"
    assert result["configured"]["maximum_mib"] == 0
    assert result["usage"]["used_mib"] == 0
    assert result["usage"]["free_mib"] == 0


def test_partial_wmi_evidence_preserves_known_facts_and_marks_missing_source(monkeypatch):
    _install_windows_result(
        monkeypatch,
        _raw(
            automatic_managed=True,
            settings_available=False,
            settings_count=0,
            configured_initial_mib=None,
            configured_maximum_mib=None,
        ),
    )

    result = pagefile_telemetry.collect_pagefile_telemetry()

    assert result["state"] == "partial"
    assert result["configured"]["mode"] == "system_managed"
    assert result["usage"]["state"] == "known"
    assert result["evidence"]["wmi"] == {
        "available": False,
        "state": "partial",
        "management": "available",
        "configuration": "unavailable",
        "usage": "available",
        "reason": "partial_wmi_evidence",
    }


def test_all_wmi_providers_unavailable_is_explicit_and_content_free(monkeypatch):
    _install_windows_result(
        monkeypatch,
        _raw(
            management_available=False,
            automatic_managed=None,
            settings_available=False,
            settings_count=0,
            configured_initial_mib=None,
            configured_maximum_mib=None,
            usage_available=False,
            usage_count=0,
            allocated_mib=None,
            used_mib=None,
            peak_used_mib=None,
        ),
    )

    result = pagefile_telemetry.collect_pagefile_telemetry()

    assert result["state"] == "unavailable"
    assert result["evidence"]["powershell"]["available"] is True
    assert result["evidence"]["wmi"]["state"] == "unavailable"
    assert result["evidence"]["wmi"]["reason"] == "wmi_unavailable"
    assert result["configured"]["state"] == "unknown"
    assert result["usage"]["state"] == "unknown"
    assert "private stderr" not in json.dumps(result)


@pytest.mark.parametrize(
    ("mode", "expected_state", "expected_reason"),
    (
        ("missing", "unavailable", "powershell_unavailable"),
        ("timeout", "timeout", "powershell_timeout"),
        ("failed", "failed", "powershell_failed"),
    ),
)
def test_powershell_failures_are_bounded_and_do_not_expose_errors(
    monkeypatch,
    mode: str,
    expected_state: str,
    expected_reason: str,
):
    monkeypatch.setattr(pagefile_telemetry, "_is_windows", lambda: True)
    monkeypatch.setattr(
        pagefile_telemetry,
        "_windows_powershell_executable",
        lambda: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    )

    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess:
        if mode == "missing":
            raise FileNotFoundError("private path")
        if mode == "timeout":
            raise subprocess.TimeoutExpired("private command", 5, stderr=b"secret")
        return subprocess.CompletedProcess([], 1, b"", b"private failure")

    monkeypatch.setattr(pagefile_telemetry.subprocess, "run", run)

    result = pagefile_telemetry.collect_pagefile_telemetry()

    assert result["state"] == "unavailable"
    assert result["evidence"]["powershell"]["state"] == expected_state
    assert result["evidence"]["powershell"]["reason"] == expected_reason
    assert "private" not in json.dumps(result)


def test_missing_system_powershell_path_does_not_fall_back_to_path_search(monkeypatch):
    monkeypatch.setattr(pagefile_telemetry, "_is_windows", lambda: True)
    monkeypatch.setattr(
        pagefile_telemetry,
        "_windows_powershell_executable",
        lambda: None,
    )
    monkeypatch.setattr(
        pagefile_telemetry.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("must not run a PATH executable"),
    )

    result = pagefile_telemetry.collect_pagefile_telemetry()

    assert result["evidence"]["powershell"]["reason"] == "powershell_unavailable"


@pytest.mark.parametrize(
    "raw",
    (
        b"not-json",
        b"{}",
        b"x" * (pagefile_telemetry.MAX_POWERSHELL_OUTPUT_BYTES + 1),
        {**_raw(), "Name": r"C:\pagefile.sys"},
    ),
)
def test_malformed_oversized_or_identifier_bearing_output_is_rejected(
    monkeypatch,
    raw: object,
):
    _install_windows_result(monkeypatch, raw)

    result = pagefile_telemetry.collect_pagefile_telemetry()

    assert result["state"] == "unavailable"
    assert result["evidence"]["wmi"]["state"] == "invalid"
    assert result["configured"]["maximum_mib"] is None
    assert result["usage"]["used_mib"] is None
    assert "pagefile.sys" not in json.dumps(result)


def test_inconsistent_usage_never_produces_negative_free_space(monkeypatch):
    _install_windows_result(
        monkeypatch,
        _raw(allocated_mib=100, used_mib=101, peak_used_mib=101),
    )

    result = pagefile_telemetry.collect_pagefile_telemetry()

    assert result["state"] == "partial"
    assert result["evidence"]["wmi"]["usage"] == "invalid"
    assert result["usage"]["free_mib"] is None


def test_row_cap_truncation_discards_incomplete_aggregates(monkeypatch):
    _install_windows_result(
        monkeypatch,
        _raw(
            settings_truncated=True,
            settings_count=pagefile_telemetry.MAX_PAGEFILE_ROWS,
            configured_initial_mib=None,
            configured_maximum_mib=None,
            usage_truncated=True,
            usage_count=pagefile_telemetry.MAX_PAGEFILE_ROWS,
            allocated_mib=None,
            used_mib=None,
            peak_used_mib=None,
        ),
    )

    result = pagefile_telemetry.collect_pagefile_telemetry()

    assert result["state"] == "unavailable"
    assert result["evidence"]["wmi"]["configuration"] == "truncated"
    assert result["evidence"]["wmi"]["usage"] == "truncated"
    assert result["configured"]["maximum_mib"] is None
    assert result["usage"]["free_mib"] is None


def test_public_surface_has_no_command_elevation_mutation_or_identifier_input():
    source = inspect.getsource(pagefile_telemetry)
    assert not inspect.signature(
        pagefile_telemetry.collect_pagefile_telemetry
    ).parameters
    for forbidden in (
        "Invoke-Expression",
        "Remove-CimInstance",
        "Set-CimInstance",
        "Start-Process",
        "Win32_PageFileSetting).Delete",
        "-Verb RunAs",
    ):
        assert forbidden not in source
    assert "shutil.which" not in source
    assert "SystemRoot" not in source
    assert "Name,InitialSize" not in source
    assert "Name,AllocatedBaseSize" not in source
