#!/usr/bin/env python3
"""Read-only compatibility preflight for the HolyROG HyFusER shadow runtime.

The probe reads process/platform metadata and one fixed ``nvidia-smi`` query.
It never imports PyTorch, writes files, installs packages, opens listeners, or
loads checkpoints. Unknown evidence fails closed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from typing import Callable, Sequence


REPORT_SCHEMA = "alpecca.rog-hyfuser-runtime-preflight.v1"
EXPECTED_HOST = "JASON_HOLYROG"
EXPECTED_SYSTEM = "Windows"
EXPECTED_MACHINE = "AMD64"
TARGET_PYTHON = "3.11.9"
TARGET_TORCH = "2.7.0"
TARGET_CUDA = "12.8"
EXPECTED_GPU_NAME = "NVIDIA GeForce RTX 4060 Laptop GPU"
MIN_DRIVER = (570, 65)
MIN_VRAM_MIB = 7_000
COMMAND_TIMEOUT_SECONDS = 5.0
MAX_CAPTURE_CHARS = 8_192
NVIDIA_QUERY = (
    "--query-gpu=name,driver_version,memory.total",
    "--format=csv,noheader,nounits",
)
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?(?:\D.*)?$")


@dataclass(frozen=True, slots=True)
class HostFacts:
    hostname: str
    system: str
    machine: str
    python_version: str
    python_implementation: str
    python_bits: str


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    status: str = "ok"


@dataclass(frozen=True, slots=True)
class GpuFacts:
    name: str
    driver_version: str
    memory_mib: int


CommandRunner = Callable[[Sequence[str], float], CommandResult]


def collect_host_facts() -> HostFacts:
    return HostFacts(
        hostname=socket.gethostname(),
        system=platform.system(),
        machine=platform.machine(),
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        python_bits=platform.architecture()[0],
    )


def _bounded(value: object) -> str:
    return str(value or "")[:MAX_CAPTURE_CHARS]


def run_nvidia_query(command: Sequence[str], timeout_seconds: float) -> CommandResult:
    expected_names = {"nvidia-smi", "nvidia-smi.exe"}
    if not command or os.path.basename(str(command[0])).lower() not in expected_names:
        raise ValueError("only the fixed nvidia-smi preflight query is allowed")
    if tuple(str(part) for part in command[1:]) != NVIDIA_QUERY:
        raise ValueError("nvidia-smi arguments are outside the read-only allowlist")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            tuple(command),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.1, min(float(timeout_seconds), COMMAND_TIMEOUT_SECONDS)),
            check=False,
            shell=False,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(returncode=124, status="timeout")
    except OSError:
        return CommandResult(returncode=127, status="unavailable")
    return CommandResult(
        returncode=int(completed.returncode),
        stdout=_bounded(completed.stdout),
        status="ok" if completed.returncode == 0 else "failed",
    )


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    if match is None:
        return None
    return tuple(int(part or 0) for part in match.groups())


def parse_gpu_rows(result: CommandResult) -> tuple[GpuFacts, ...]:
    if result.status != "ok" or result.returncode != 0:
        return ()
    parsed: list[GpuFacts] = []
    for line in result.stdout.splitlines():
        columns = [part.strip() for part in line.split(",")]
        if len(columns) != 3:
            continue
        name, driver, memory = columns
        if _version_tuple(driver) is None:
            continue
        try:
            memory_mib = int(memory)
        except ValueError:
            continue
        if name and memory_mib > 0:
            parsed.append(GpuFacts(name, driver, memory_mib))
    return tuple(parsed)


def _check(check_id: str, passed: bool, observed: object) -> dict[str, object]:
    return {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "observed": observed,
    }


def evaluate_preflight(
    host: HostFacts,
    gpu_result: CommandResult,
) -> dict[str, object]:
    rows = parse_gpu_rows(gpu_result)
    matching = next((row for row in rows if row.name == EXPECTED_GPU_NAME), None)
    driver = _version_tuple(matching.driver_version) if matching else None
    checks = [
        _check(
            "assigned_host",
            host.hostname.casefold() == EXPECTED_HOST.casefold(),
            host.hostname,
        ),
        _check("windows", host.system == EXPECTED_SYSTEM, host.system),
        _check("x64_machine", host.machine.upper() == EXPECTED_MACHINE, host.machine),
        _check(
            "cpython",
            host.python_implementation == "CPython",
            host.python_implementation,
        ),
        _check(
            "python_3_11_9",
            host.python_version == TARGET_PYTHON,
            host.python_version,
        ),
        _check("python_64_bit", host.python_bits == "64bit", host.python_bits),
        _check(
            "nvidia_query",
            gpu_result.status == "ok" and gpu_result.returncode == 0,
            gpu_result.status,
        ),
        _check("rtx_4060_laptop", matching is not None, matching.name if matching else None),
        _check(
            "driver_cuda_12_8",
            driver is not None and driver[:2] >= MIN_DRIVER,
            matching.driver_version if matching else None,
        ),
        _check(
            "vram_capacity",
            matching is not None and matching.memory_mib >= MIN_VRAM_MIB,
            matching.memory_mib if matching else None,
        ),
    ]
    ready = all(item["status"] == "pass" for item in checks)
    return {
        "schema": REPORT_SCHEMA,
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "shadow_only": True,
        "authorizes_activation": False,
        "target": {
            "python": TARGET_PYTHON,
            "torch": TARGET_TORCH,
            "cuda": TARGET_CUDA,
            "requirements": "requirements-rog-hyfuser-cu128.txt",
        },
        "checks": checks,
        "gpu_count": len(rows),
        "installation_performed": False,
    }


def run_preflight(
    *,
    host_facts: HostFacts | None = None,
    tool_finder: Callable[[str], str | None] = shutil.which,
    command_runner: CommandRunner = run_nvidia_query,
) -> dict[str, object]:
    host = host_facts or collect_host_facts()
    executable = tool_finder("nvidia-smi.exe") or tool_finder("nvidia-smi")
    if executable is None:
        result = CommandResult(returncode=127, status="unavailable")
    else:
        result = command_runner((executable, *NVIDIA_QUERY), COMMAND_TIMEOUT_SECONDS)
    return evaluate_preflight(host, result)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only HolyROG HyFusER runtime compatibility preflight.",
        epilog="After a ready report, use the documented commands in "
        "requirements-rog-hyfuser-cu128.txt. This command installs nothing.",
    )
    parser.parse_args(argv)
    report = run_preflight()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
