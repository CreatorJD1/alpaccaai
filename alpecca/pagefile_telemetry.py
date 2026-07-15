"""Bounded, read-only Windows pagefile telemetry for Phase 7.

The public collector has no arguments and can run only one code-owned
PowerShell/CIM query. It returns aggregate MiB facts and source availability;
pagefile paths, host names, command input, stderr, and exception text never
cross the module boundary. No setting, registry value, service, or process
privilege is changed.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import subprocess
from ctypes import wintypes
from pathlib import Path
from typing import Any


SCHEMA = "alpecca.phase7.pagefile-telemetry.v1"
POWERSHELL_TIMEOUT_SECONDS = 5.0
WMI_OPERATION_TIMEOUT_SECONDS = 3
MAX_PAGEFILE_ROWS = 16
MAX_POWERSHELL_OUTPUT_BYTES = 8 * 1024

_QUERY_SCHEMA = "alpecca.phase7.pagefile-wmi.v1"
_RAW_KEYS = frozenset(
    {
        "schema",
        "management_available",
        "automatic_managed",
        "settings_available",
        "settings_truncated",
        "settings_count",
        "configured_initial_mib",
        "configured_maximum_mib",
        "usage_available",
        "usage_truncated",
        "usage_count",
        "allocated_mib",
        "used_mib",
        "peak_used_mib",
    }
)

# This script selects no Name, path, device, host, user, or process property.
# Each provider is independently optional, and provider errors remain
# content-free booleans instead of crossing into Python as error text.
_POWERSHELL_QUERY = rf"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$limit = {MAX_PAGEFILE_ROWS}
$operationTimeout = {WMI_OPERATION_TIMEOUT_SECONDS}
$result = [ordered]@{{
    schema = '{_QUERY_SCHEMA}'
    management_available = $false
    automatic_managed = $null
    settings_available = $false
    settings_truncated = $false
    settings_count = 0
    configured_initial_mib = $null
    configured_maximum_mib = $null
    usage_available = $false
    usage_truncated = $false
    usage_count = 0
    allocated_mib = $null
    used_mib = $null
    peak_used_mib = $null
}}

try {{
    $computer = Get-CimInstance -ClassName Win32_ComputerSystem `
        -Property AutomaticManagedPagefile -OperationTimeoutSec $operationTimeout `
        -ErrorAction Stop | Select-Object -First 1
    if ($null -ne $computer -and $null -ne $computer.AutomaticManagedPagefile) {{
        $result.management_available = $true
        $result.automatic_managed = [bool]$computer.AutomaticManagedPagefile
    }}
}} catch {{}}

try {{
    $settings = @(Get-CimInstance -ClassName Win32_PageFileSetting `
        -Property InitialSize,MaximumSize -OperationTimeoutSec $operationTimeout `
        -ErrorAction Stop | Select-Object -First ($limit + 1))
    $result.settings_available = $true
    $result.settings_truncated = $settings.Count -gt $limit
    $boundedSettings = @($settings | Select-Object -First $limit)
    $result.settings_count = $boundedSettings.Count
    if (-not $result.settings_truncated) {{
        [int64]$initial = 0
        [int64]$maximum = 0
        foreach ($setting in $boundedSettings) {{
            if ($null -eq $setting.InitialSize -or $null -eq $setting.MaximumSize) {{
                throw 'invalid setting evidence'
            }}
            $initial += [Convert]::ToInt64($setting.InitialSize)
            $maximum += [Convert]::ToInt64($setting.MaximumSize)
        }}
        $result.configured_initial_mib = $initial
        $result.configured_maximum_mib = $maximum
    }}
}} catch {{}}

try {{
    $usage = @(Get-CimInstance -ClassName Win32_PageFileUsage `
        -Property AllocatedBaseSize,CurrentUsage,PeakUsage `
        -OperationTimeoutSec $operationTimeout -ErrorAction Stop |
        Select-Object -First ($limit + 1))
    $result.usage_available = $true
    $result.usage_truncated = $usage.Count -gt $limit
    $boundedUsage = @($usage | Select-Object -First $limit)
    $result.usage_count = $boundedUsage.Count
    if (-not $result.usage_truncated) {{
        [int64]$allocated = 0
        [int64]$used = 0
        [int64]$peak = 0
        foreach ($item in $boundedUsage) {{
            if ($null -eq $item.AllocatedBaseSize -or $null -eq $item.CurrentUsage `
                -or $null -eq $item.PeakUsage) {{
                throw 'invalid usage evidence'
            }}
            $allocated += [Convert]::ToInt64($item.AllocatedBaseSize)
            $used += [Convert]::ToInt64($item.CurrentUsage)
            $peak += [Convert]::ToInt64($item.PeakUsage)
        }}
        $result.allocated_mib = $allocated
        $result.used_mib = $used
        $result.peak_used_mib = $peak
    }}
}} catch {{}}

[Console]::Out.Write(($result | ConvertTo-Json -Compress -Depth 2))
""".strip()
_ENCODED_QUERY = base64.b64encode(
    _POWERSHELL_QUERY.encode("utf-16-le")
).decode("ascii")


def _is_windows() -> bool:
    return os.name == "nt"


def _windows_powershell_executable() -> str | None:
    """Resolve Windows PowerShell from the kernel-owned system directory."""
    if not _is_windows():
        return None
    buffer = ctypes.create_unicode_buffer(32768)
    try:
        function = ctypes.windll.kernel32.GetSystemDirectoryW
        function.argtypes = (wintypes.LPWSTR, wintypes.UINT)
        function.restype = wintypes.UINT
        length = int(function(buffer, len(buffer)))
    except Exception:
        return None
    if length <= 0 or length >= len(buffer):
        return None
    candidate = (
        Path(buffer.value)
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    try:
        return str(candidate) if candidate.is_file() else None
    except OSError:
        return None


def _unknown_configured() -> dict[str, object]:
    return {
        "state": "unknown",
        "mode": "unknown",
        "initial_mib": None,
        "maximum_mib": None,
        "entry_count": None,
    }


def _unknown_usage() -> dict[str, object]:
    return {
        "state": "unknown",
        "allocated_mib": None,
        "used_mib": None,
        "free_mib": None,
        "peak_used_mib": None,
        "entry_count": None,
    }


def _unavailable(
    reason: str,
    *,
    platform: str,
    powershell_state: str = "unavailable",
    powershell_available: bool = False,
    wmi_state: str = "unavailable",
) -> dict[str, object]:
    component_state = "invalid" if wmi_state == "invalid" else "unavailable"
    return {
        "schema": SCHEMA,
        "state": "unavailable",
        "platform": platform,
        "evidence": {
            "powershell": {
                "available": powershell_available,
                "state": powershell_state,
                "reason": None if powershell_available else reason,
            },
            "wmi": {
                "available": False,
                "state": wmi_state,
                "management": component_state,
                "configuration": component_state,
                "usage": component_state,
                "reason": reason,
            },
        },
        "configured": _unknown_configured(),
        "usage": _unknown_usage(),
    }


def _nonnegative_int(value: object) -> int | None:
    if type(value) is not int or value < 0:
        return None
    return value


def _bounded_count(value: object) -> int | None:
    parsed = _nonnegative_int(value)
    if parsed is None or parsed > MAX_PAGEFILE_ROWS:
        return None
    return parsed


def _management_state(raw: dict[str, Any]) -> str:
    available = raw["management_available"]
    automatic = raw["automatic_managed"]
    if available is True and type(automatic) is bool:
        return "available"
    if available is False and automatic is None:
        return "unavailable"
    return "invalid"


def _settings_state(raw: dict[str, Any]) -> str:
    available = raw["settings_available"]
    truncated = raw["settings_truncated"]
    count = _bounded_count(raw["settings_count"])
    initial = _nonnegative_int(raw["configured_initial_mib"])
    maximum = _nonnegative_int(raw["configured_maximum_mib"])
    if available is False:
        if (
            truncated is False
            and count == 0
            and raw["configured_initial_mib"] is None
            and raw["configured_maximum_mib"] is None
        ):
            return "unavailable"
        return "invalid"
    if available is not True or type(truncated) is not bool or count is None:
        return "invalid"
    if truncated:
        return (
            "truncated"
            if count == MAX_PAGEFILE_ROWS
            and raw["configured_initial_mib"] is None
            and raw["configured_maximum_mib"] is None
            else "invalid"
        )
    if initial is None or maximum is None:
        return "invalid"
    if count == 0:
        return "available" if initial == 0 and maximum == 0 else "invalid"
    return "available" if 0 <= initial <= maximum and maximum > 0 else "invalid"


def _usage_state(raw: dict[str, Any]) -> str:
    available = raw["usage_available"]
    truncated = raw["usage_truncated"]
    count = _bounded_count(raw["usage_count"])
    allocated = _nonnegative_int(raw["allocated_mib"])
    used = _nonnegative_int(raw["used_mib"])
    peak = _nonnegative_int(raw["peak_used_mib"])
    if available is False:
        if (
            truncated is False
            and count == 0
            and raw["allocated_mib"] is None
            and raw["used_mib"] is None
            and raw["peak_used_mib"] is None
        ):
            return "unavailable"
        return "invalid"
    if available is not True or type(truncated) is not bool or count is None:
        return "invalid"
    if truncated:
        return (
            "truncated"
            if count == MAX_PAGEFILE_ROWS
            and raw["allocated_mib"] is None
            and raw["used_mib"] is None
            and raw["peak_used_mib"] is None
            else "invalid"
        )
    if allocated is None or used is None or peak is None:
        return "invalid"
    if count == 0:
        return (
            "available"
            if allocated == 0 and used == 0 and peak == 0
            else "invalid"
        )
    return "available" if used <= allocated and peak >= used else "invalid"


def _configured_facts(
    raw: dict[str, Any],
    management_state: str,
    settings_state: str,
) -> dict[str, object]:
    if management_state == "available" and raw["automatic_managed"] is True:
        return {
            "state": "known",
            "mode": "system_managed",
            "initial_mib": None,
            "maximum_mib": None,
            "entry_count": None,
        }
    if settings_state != "available":
        return _unknown_configured()
    count = int(raw["settings_count"])
    if count == 0:
        if management_state == "available" and raw["automatic_managed"] is False:
            return {
                "state": "known",
                "mode": "none",
                "initial_mib": 0,
                "maximum_mib": 0,
                "entry_count": 0,
            }
        return _unknown_configured()
    return {
        "state": "known",
        "mode": "custom",
        "initial_mib": int(raw["configured_initial_mib"]),
        "maximum_mib": int(raw["configured_maximum_mib"]),
        "entry_count": count,
    }


def _usage_facts(raw: dict[str, Any], usage_state: str) -> dict[str, object]:
    if usage_state != "available":
        return _unknown_usage()
    allocated = int(raw["allocated_mib"])
    used = int(raw["used_mib"])
    return {
        "state": "known",
        "allocated_mib": allocated,
        "used_mib": used,
        "free_mib": allocated - used,
        "peak_used_mib": int(raw["peak_used_mib"]),
        "entry_count": int(raw["usage_count"]),
    }


def _wmi_state(component_states: tuple[str, str, str]) -> tuple[str, str | None]:
    if "invalid" in component_states:
        return "invalid", "invalid_wmi_evidence"
    if all(state == "available" for state in component_states):
        return "available", None
    if all(state == "unavailable" for state in component_states):
        return "unavailable", "wmi_unavailable"
    return "partial", "partial_wmi_evidence"


def _normalize(raw: object) -> dict[str, object]:
    if (
        type(raw) is not dict
        or frozenset(raw) != _RAW_KEYS
        or raw.get("schema") != _QUERY_SCHEMA
        or any(
            type(raw.get(name)) is not bool
            for name in (
                "management_available",
                "settings_available",
                "settings_truncated",
                "usage_available",
                "usage_truncated",
            )
        )
    ):
        return _unavailable(
            "invalid_wmi_evidence",
            platform="windows",
            powershell_state="available",
            powershell_available=True,
            wmi_state="invalid",
        )

    typed_raw = raw
    management = _management_state(typed_raw)
    configuration = _settings_state(typed_raw)
    usage_state = _usage_state(typed_raw)
    component_states = (management, configuration, usage_state)
    wmi_state, reason = _wmi_state(component_states)
    configured = _configured_facts(typed_raw, management, configuration)
    usage = _usage_facts(typed_raw, usage_state)

    known_facts = sum(
        reading["state"] == "known" for reading in (configured, usage)
    )
    if wmi_state == "available" and known_facts == 2:
        state = "ready"
    elif known_facts:
        state = "partial"
    else:
        state = "unavailable"

    return {
        "schema": SCHEMA,
        "state": state,
        "platform": "windows",
        "evidence": {
            "powershell": {
                "available": True,
                "state": "available",
                "reason": None,
            },
            "wmi": {
                "available": wmi_state == "available",
                "state": wmi_state,
                "management": management,
                "configuration": configuration,
                "usage": usage_state,
                "reason": reason,
            },
        },
        "configured": configured,
        "usage": usage,
    }


def collect_pagefile_telemetry() -> dict[str, object]:
    """Collect one bounded aggregate snapshot without accepting command input."""
    if not _is_windows():
        return _unavailable("non_windows", platform="non_windows")

    executable = _windows_powershell_executable()
    if executable is None:
        return _unavailable("powershell_unavailable", platform="windows")

    command = (
        executable,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        _ENCODED_QUERY,
    )
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=POWERSHELL_TIMEOUT_SECONDS,
            check=False,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return _unavailable(
            "powershell_timeout",
            platform="windows",
            powershell_state="timeout",
        )
    except (OSError, subprocess.SubprocessError):
        return _unavailable("powershell_unavailable", platform="windows")

    if completed.returncode != 0:
        return _unavailable(
            "powershell_failed",
            platform="windows",
            powershell_state="failed",
        )
    stdout = completed.stdout
    if (
        not isinstance(stdout, bytes)
        or not stdout
        or len(stdout) > MAX_POWERSHELL_OUTPUT_BYTES
    ):
        return _unavailable(
            "invalid_wmi_evidence",
            platform="windows",
            powershell_state="available",
            powershell_available=True,
            wmi_state="invalid",
        )
    try:
        raw = json.loads(stdout.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _unavailable(
            "invalid_wmi_evidence",
            platform="windows",
            powershell_state="available",
            powershell_available=True,
            wmi_state="invalid",
        )
    return _normalize(raw)


__all__ = [
    "MAX_PAGEFILE_ROWS",
    "MAX_POWERSHELL_OUTPUT_BYTES",
    "POWERSHELL_TIMEOUT_SECONDS",
    "SCHEMA",
    "WMI_OPERATION_TIMEOUT_SECONDS",
    "collect_pagefile_telemetry",
]
