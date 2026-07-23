#!/usr/bin/env python3
"""Emit a read-only, content-free qualification report for Jason_HOLYROG.

This utility inventories one Windows worker candidate. It does not inspect
application data, environment variables, credential stores, or file contents;
it does not start services; and it never changes repository or system state.
Primary-host qualification is intentionally outside this utility because it
requires separately witnessed continuity failover and failback evidence.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
from typing import Callable, Sequence


EXPECTED_HOST = "Jason_HOLYROG"
REPORT_SCHEMA = "alpecca.rog-worker-qualification.v1"
COMMAND_TIMEOUT_SECONDS = 5.0
PORT_PROBE_TIMEOUT_SECONDS = 0.35
MAX_CAPTURE_CHARS = 32 * 1024
CURRENT_PYTHON = "__current_python__"
DEFAULT_OLLAMA_HOST = "127.0.0.1"
DEFAULT_OLLAMA_PORT = 11434
DEFAULT_WORKER_BIND_HOST = "127.0.0.1"
DEFAULT_WORKER_PORT = 8788
RESERVED_ALPECCA_PORTS = frozenset({8765, 8776, 8779, DEFAULT_OLLAMA_PORT})

REQUIRED_TOOLS: tuple[str, ...] = (
    "python",
    "git",
    "node",
    "npm",
    "ffmpeg",
)
OPTIONAL_TOOLS: tuple[str, ...] = (
    "ollama",
    "blender",
    "nvidia_smi",
    "powershell",
)
TOOL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "python": (CURRENT_PYTHON, "python.exe", "python"),
    "git": ("git.exe", "git"),
    "node": ("node.exe", "node"),
    "npm": ("npm.cmd", "npm.exe", "npm"),
    "ffmpeg": ("ffmpeg.exe", "ffmpeg"),
    "ollama": ("ollama.exe", "ollama"),
    "blender": ("blender.exe", "blender"),
    "nvidia_smi": ("nvidia-smi.exe", "nvidia-smi"),
    "powershell": ("pwsh.exe", "powershell.exe", "pwsh", "powershell"),
}

NVIDIA_QUERY = (
    "--query-gpu=name,memory.total",
    "--format=csv,noheader,nounits",
)
GPU_POWERSHELL_QUERY = (
    "$ErrorActionPreference='Stop';"
    "@(Get-CimInstance -ClassName Win32_VideoController | "
    "Select-Object -Property Name,AdapterRAM) | ConvertTo-Json -Compress"
)
POWERSHELL_QUERY_ARGS = (
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    GPU_POWERSHELL_QUERY,
)
GIT_HEAD_ARGS = ("rev-parse", "--verify", "HEAD")
GIT_STATUS_ARGS = (
    "--no-optional-locks",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.untrackedCache=false",
    "status",
    "--porcelain=v1",
    "--untracked-files=normal",
    "--ignore-submodules=all",
)
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    status: str = "ok"
    truncated: bool = False


@dataclass(frozen=True)
class HostFacts:
    hostname: str
    os_name: str
    os_release: str
    os_version: str
    machine: str
    cpu_count: int | None
    total_ram_bytes: int | None
    python_version: str
    python_implementation: str


@dataclass(frozen=True)
class DiskFacts:
    total_bytes: int
    free_bytes: int


CommandRunner = Callable[[Sequence[str], Path, float], CommandResult]
ToolFinder = Callable[[str], str | None]
FactsProvider = Callable[[], HostFacts]
DiskProvider = Callable[[Path], DiskFacts]
PortProbe = Callable[[str, int, float], bool]


def _executable_key(value: str) -> str:
    name = Path(value).name.lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _assert_read_only_command(command: Sequence[str]) -> None:
    if not command:
        raise ValueError("empty command is not allowed")
    executable = _executable_key(str(command[0]))
    args = tuple(str(part) for part in command[1:])
    allowed = (
        (executable == "git" and args in {GIT_HEAD_ARGS, GIT_STATUS_ARGS})
        or (executable == "nvidia-smi" and args == NVIDIA_QUERY)
        or (
            executable in {"powershell", "pwsh"}
            and args == POWERSHELL_QUERY_ARGS
        )
    )
    if not allowed:
        raise ValueError("command is outside the read-only qualification allowlist")


def _bounded_text(value: object) -> tuple[str, bool]:
    if value is None:
        return "", False
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    return text[:MAX_CAPTURE_CHARS], len(text) > MAX_CAPTURE_CHARS


class BoundedReadOnlyCommandRunner:
    """Run only the fixed inventory commands above, with no shell."""

    def __call__(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: float,
    ) -> CommandResult:
        _assert_read_only_command(command)
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                tuple(command),
                cwd=str(cwd),
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
        except subprocess.TimeoutExpired as exc:
            stdout, stdout_truncated = _bounded_text(exc.stdout)
            stderr, stderr_truncated = _bounded_text(exc.stderr)
            return CommandResult(
                returncode=124,
                stdout=stdout,
                stderr=stderr,
                status="timeout",
                truncated=stdout_truncated or stderr_truncated,
            )
        except OSError:
            return CommandResult(returncode=127, status="unavailable")

        stdout, stdout_truncated = _bounded_text(completed.stdout)
        stderr, stderr_truncated = _bounded_text(completed.stderr)
        return CommandResult(
            returncode=int(completed.returncode),
            stdout=stdout,
            stderr=stderr,
            status="ok" if completed.returncode == 0 else "failed",
            truncated=stdout_truncated or stderr_truncated,
        )


def _default_tool_finder(candidate: str) -> str | None:
    if candidate == CURRENT_PYTHON:
        return sys.executable
    return shutil.which(candidate)


def _find_tools(tool_finder: ToolFinder) -> tuple[dict[str, bool], dict[str, str]]:
    presence: dict[str, bool] = {}
    executables: dict[str, str] = {}
    for logical_name, candidates in TOOL_CANDIDATES.items():
        found: str | None = None
        for candidate in candidates:
            try:
                found = tool_finder(candidate)
            except OSError:
                found = None
            if found:
                break
        presence[logical_name] = found is not None
        if found is not None:
            executables[logical_name] = found
    return presence, executables


def _windows_total_ram_bytes() -> int | None:
    if os.name != "nt":
        return None

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    try:
        succeeded = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError):
        return None
    return int(status.ullTotalPhys) if succeeded else None


def _default_host_facts() -> HostFacts:
    return HostFacts(
        hostname=socket.gethostname(),
        os_name=platform.system(),
        os_release=platform.release(),
        os_version=platform.version(),
        machine=platform.machine(),
        cpu_count=os.cpu_count(),
        total_ram_bytes=_windows_total_ram_bytes(),
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
    )


def _default_disk_provider(repo_root: Path) -> DiskFacts:
    usage = shutil.disk_usage(repo_root)
    return DiskFacts(total_bytes=int(usage.total), free_bytes=int(usage.free))


def _default_port_probe(host: str, port: int, timeout_seconds: float) -> bool:
    """Check listener presence only; send no application data."""

    try:
        with socket.create_connection(
            (host, port),
            timeout=max(0.05, min(float(timeout_seconds), PORT_PROBE_TIMEOUT_SECONDS)),
        ):
            return True
    except OSError:
        return False


def _is_loopback_host(host: str) -> bool:
    candidate = str(host or "").strip().lower()
    if candidate == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _probe_loopback_service(
    *,
    host: str,
    port: int,
    executable_present: bool,
    port_probe: PortProbe,
) -> dict[str, object]:
    normalized_host = str(host or "").strip()
    valid_port = isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535
    loopback_only = _is_loopback_host(normalized_host)
    listening = False
    probe_status = "not-run"
    if loopback_only and valid_port:
        try:
            listening = bool(
                port_probe(normalized_host, port, PORT_PROBE_TIMEOUT_SECONDS)
            )
            probe_status = "listening" if listening else "not-listening"
        except OSError:
            probe_status = "unavailable"
    elif not loopback_only:
        probe_status = "rejected-non-loopback"
    else:
        probe_status = "invalid-port"

    return {
        "status": "ready" if executable_present and listening else "needs-attention",
        "ready": bool(executable_present and listening),
        "executable_present": executable_present,
        "host": normalized_host,
        "port": port,
        "loopback_only": loopback_only,
        "probe": probe_status,
        "application_request_sent": False,
    }


def _worker_endpoint_sanity(
    host: str,
    port: int,
    *,
    expected_host: str = EXPECTED_HOST,
) -> dict[str, object]:
    normalized_host = str(host or "").strip()
    reasons: list[str] = []
    if not normalized_host or any(character.isspace() for character in normalized_host):
        reasons.append("invalid_bind_host")

    valid_port = isinstance(port, int) and not isinstance(port, bool) and 1024 <= port <= 65535
    if not valid_port:
        reasons.append("worker_port_out_of_range")
    elif port in RESERVED_ALPECCA_PORTS:
        reasons.append("worker_port_conflict")

    if _is_loopback_host(normalized_host):
        exposure = "loopback-only"
    elif normalized_host in {"0.0.0.0", "::"}:
        exposure = "all-interfaces"
    else:
        try:
            address = ipaddress.ip_address(normalized_host)
            exposure = "private-interface" if address.is_private else "public-interface"
            if not address.is_private:
                reasons.append("public_bind_not_allowed")
        except ValueError:
            exposure = "named-interface"
            if normalized_host.casefold() != str(expected_host or "").strip().casefold():
                reasons.append("unverified_named_bind_host")

    sane = not reasons
    return {
        "status": "sane" if sane else "invalid",
        "sane": sane,
        "bind_host": normalized_host,
        "port": port,
        "exposure": exposure,
        "reasons": reasons,
        "listener_probed": False,
    }


def _clean_hardware_name(value: object) -> str:
    text = " ".join(str(value or "").split())
    return "".join(character for character in text if character.isprintable())[:160]


def _parse_nvidia_output(output: str) -> list[dict[str, object]]:
    devices: list[dict[str, object]] = []
    for line in output.splitlines()[:16]:
        if "," not in line:
            continue
        name, memory_text = line.rsplit(",", 1)
        name = _clean_hardware_name(name)
        try:
            memory_mib = int(float(memory_text.strip()))
        except ValueError:
            continue
        if name and memory_mib > 0:
            devices.append({"name": name, "vram_mib": memory_mib})
    return devices


def _parse_powershell_gpu_output(output: str) -> list[dict[str, object]]:
    try:
        decoded = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return []
    rows = decoded if isinstance(decoded, list) else [decoded]
    devices: list[dict[str, object]] = []
    for row in rows[:16]:
        if not isinstance(row, dict):
            continue
        name = _clean_hardware_name(row.get("Name"))
        try:
            adapter_bytes = int(row.get("AdapterRAM") or 0)
        except (TypeError, ValueError):
            adapter_bytes = 0
        if name:
            devices.append(
                {
                    "name": name,
                    "vram_mib": adapter_bytes // (1024 * 1024) or None,
                }
            )
    return devices


def _probe_gpu(
    executables: dict[str, str],
    command_runner: CommandRunner,
    repo_root: Path,
) -> dict[str, object]:
    attempts = {"nvidia_smi": "unavailable", "powershell": "unavailable"}
    nvidia_smi = executables.get("nvidia_smi")
    if nvidia_smi:
        result = command_runner(
            (nvidia_smi, *NVIDIA_QUERY), repo_root, COMMAND_TIMEOUT_SECONDS
        )
        attempts["nvidia_smi"] = result.status
        devices = _parse_nvidia_output(result.stdout) if result.returncode == 0 else []
        if devices:
            return {
                "status": "available",
                "source": "nvidia-smi",
                "devices": devices,
                "attempts": attempts,
            }

    powershell = executables.get("powershell")
    if powershell:
        result = command_runner(
            (powershell, *POWERSHELL_QUERY_ARGS),
            repo_root,
            COMMAND_TIMEOUT_SECONDS,
        )
        attempts["powershell"] = result.status
        devices = (
            _parse_powershell_gpu_output(result.stdout)
            if result.returncode == 0
            else []
        )
        if devices:
            return {
                "status": "available",
                "source": "powershell-cim",
                "devices": devices,
                "attempts": attempts,
            }

    return {
        "status": "unavailable",
        "source": None,
        "devices": [],
        "attempts": attempts,
    }


def _probe_source(
    git_executable: str | None,
    command_runner: CommandRunner,
    repo_root: Path,
) -> dict[str, object]:
    if not git_executable:
        return {
            "status": "unavailable",
            "commit": None,
            "dirty": None,
            "dirty_scope": "superproject_worktree_excluding_submodules",
            "head_probe": "unavailable",
            "dirty_probe": "unavailable",
        }

    head_result = command_runner(
        (git_executable, *GIT_HEAD_ARGS), repo_root, COMMAND_TIMEOUT_SECONDS
    )
    status_result = command_runner(
        (git_executable, *GIT_STATUS_ARGS), repo_root, COMMAND_TIMEOUT_SECONDS
    )
    candidate = head_result.stdout.strip().splitlines()[0] if head_result.stdout.strip() else ""
    commit = candidate.lower() if COMMIT_RE.fullmatch(candidate) else None
    dirty = bool(status_result.stdout) if status_result.returncode == 0 else None
    ready = commit is not None and dirty is not None
    return {
        "status": "ready" if ready else "incomplete",
        "commit": commit,
        "dirty": dirty,
        "dirty_scope": "superproject_worktree_excluding_submodules",
        "head_probe": head_result.status,
        "dirty_probe": status_result.status,
    }


def _gib(value: int | None) -> float | None:
    return round(value / (1024**3), 2) if value is not None else None


def collect_qualification(
    repo_root: Path,
    *,
    expected_host: str = EXPECTED_HOST,
    worker_bind_host: str = DEFAULT_WORKER_BIND_HOST,
    worker_port: int = DEFAULT_WORKER_PORT,
    ollama_host: str = DEFAULT_OLLAMA_HOST,
    ollama_port: int = DEFAULT_OLLAMA_PORT,
    facts_provider: FactsProvider = _default_host_facts,
    disk_provider: DiskProvider = _default_disk_provider,
    tool_finder: ToolFinder = _default_tool_finder,
    command_runner: CommandRunner | None = None,
    port_probe: PortProbe = _default_port_probe,
) -> dict[str, object]:
    """Collect metadata-only evidence without changing or starting anything."""

    root = Path(repo_root).resolve()
    runner = command_runner or BoundedReadOnlyCommandRunner()
    facts = facts_provider()
    presence, executables = _find_tools(tool_finder)

    try:
        disk = disk_provider(root)
        disk_report: dict[str, object] = {
            "status": "available",
            "scope": "repository_volume",
            "total_bytes": max(0, disk.total_bytes),
            "free_bytes": max(0, disk.free_bytes),
            "total_gib": _gib(max(0, disk.total_bytes)),
            "free_gib": _gib(max(0, disk.free_bytes)),
        }
    except OSError:
        disk_report = {
            "status": "unavailable",
            "scope": "repository_volume",
            "total_bytes": None,
            "free_bytes": None,
            "total_gib": None,
            "free_gib": None,
        }

    source = _probe_source(executables.get("git"), runner, root)
    gpu = _probe_gpu(executables, runner, root)
    host_matches = facts.hostname.casefold() == expected_host.casefold()
    required_presence = {name: presence[name] for name in REQUIRED_TOOLS}
    optional_presence = {name: presence[name] for name in OPTIONAL_TOOLS}
    required_tools_ready = all(required_presence.values())
    worker_endpoint = _worker_endpoint_sanity(
        worker_bind_host,
        worker_port,
        expected_host=expected_host,
    )
    ollama = _probe_loopback_service(
        host=ollama_host,
        port=ollama_port,
        executable_present=presence["ollama"],
        port_probe=port_probe,
    )
    blender = {
        "status": "available" if presence["blender"] else "unavailable",
        "executable_present": presence["blender"],
        "executable_started": False,
    }
    source_clean = source["status"] == "ready" and source["dirty"] is False
    capabilities = {
        "reasoning": {
            "status": "ready" if ollama["ready"] else "needs-attention",
            "ready": ollama["ready"],
            "evidence": {
                "ollama_executable": (
                    "present" if presence["ollama"] else "missing"
                ),
                "ollama_loopback": ollama["probe"],
            },
        },
        "build": {
            "status": (
                "ready"
                if required_tools_ready and source_clean
                else "needs-attention"
            ),
            "ready": bool(required_tools_ready and source_clean),
            "evidence": {
                "required_tools": "ready" if required_tools_ready else "missing",
                "source_checkpoint": source["status"],
                "source_clean": source["dirty"] is False,
            },
        },
        "render": {
            "status": (
                "ready"
                if presence["blender"] and source_clean
                else "needs-attention"
            ),
            "ready": bool(presence["blender"] and source_clean),
            "evidence": {
                "blender_executable": (
                    "present" if presence["blender"] else "missing"
                ),
                "source_checkpoint": source["status"],
                "source_clean": source["dirty"] is False,
            },
        },
    }

    reasons: list[str] = []
    if not host_matches:
        reasons.append("expected_host_mismatch")
    if facts.os_name.casefold() != "windows":
        reasons.append("windows_required")
    if not facts.cpu_count or facts.cpu_count < 1:
        reasons.append("cpu_inventory_unavailable")
    if not facts.total_ram_bytes or facts.total_ram_bytes < 1:
        reasons.append("ram_inventory_unavailable")
    if disk_report["status"] != "available":
        reasons.append("disk_inventory_unavailable")
    if source["status"] != "ready":
        reasons.append("source_inventory_incomplete")
    elif source["dirty"]:
        reasons.append("source_dirty")
    if not required_tools_ready:
        reasons.append("required_tools_missing")
    if gpu["status"] != "available":
        reasons.append("gpu_inventory_unavailable")
    if not worker_endpoint["sane"]:
        reasons.append("worker_endpoint_invalid")

    blocking_worker_reasons = {
        "expected_host_mismatch",
        "windows_required",
        "cpu_inventory_unavailable",
        "ram_inventory_unavailable",
        "disk_inventory_unavailable",
        "source_inventory_incomplete",
        "source_dirty",
        "required_tools_missing",
        "worker_endpoint_invalid",
    }
    worker_ready = not any(reason in blocking_worker_reasons for reason in reasons)
    worker_status = "qualified-worker-only" if worker_ready else "worker-only-needs-attention"

    continuity_gates = {
        "exact_source_checkpoint_match": "not_evidenced",
        "encrypted_memory_restore": "not_evidenced",
        "single_continuity_lease_owner": "not_evidenced",
        "local_model_and_voice_readiness": "not_evidenced",
        "controlled_failover": "not_evidenced",
        "controlled_failback": "not_evidenced",
        "lease_loss_stops_speaking_and_writes": "not_evidenced",
    }

    return {
        "schema": REPORT_SCHEMA,
        "target_host": expected_host,
        "collection": {
            "mode": "read-only",
            "evidence": "content-free-metadata",
            "application_files_opened": False,
            "application_data_opened": False,
            "secret_stores_queried": False,
            "environment_dumped": False,
            "system_state_mutated": False,
            "services_started": [],
            "network_probe_scope": "loopback-listener-metadata-only",
            "application_requests_sent": 0,
        },
        "host": {
            "observed_name": facts.hostname,
            "matches_target": host_matches,
            "os": {
                "name": facts.os_name,
                "release": facts.os_release,
                "version": facts.os_version,
                "machine": facts.machine,
            },
        },
        "hardware": {
            "cpu_logical_count": facts.cpu_count,
            "total_ram_bytes": facts.total_ram_bytes,
            "total_ram_gib": _gib(facts.total_ram_bytes),
            "gpu": gpu,
            "disk": disk_report,
        },
        "runtime": {
            "python": {
                "version": facts.python_version,
                "implementation": facts.python_implementation,
            },
            "required_tools": required_presence,
            "required_tools_ready": required_tools_ready,
            "optional_tools": optional_presence,
            "ollama": ollama,
            "blender": blender,
            "compute_worker_endpoint": worker_endpoint,
        },
        "source": source,
        "capabilities": capabilities,
        "qualification": {
            "assigned_role": "worker-only",
            "worker_status": worker_status,
            "worker_ready": worker_ready,
            "primary_status": "not-qualified",
            "primary_qualified": False,
            "primary_reason": "continuity_failover_gates_require_separate_evidence",
            "allowed_uses": [
                "builds",
                "tests",
                "VRoid_VRM_work",
                "video_processing",
                "bounded_model_benchmarks",
            ],
            "live_roles_not_authorized": ["CoreMind", "Discord_bridge"],
            "continuity_failover_evidence_in_scope": False,
            "continuity_failover_gates": continuity_gates,
            "capability_statuses": {
                name: details["status"] for name, details in capabilities.items()
            },
            "attention_reasons": reasons,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit read-only JSON qualification evidence for Jason_HOLYROG."
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository whose Git metadata and volume capacity are checked.",
    )
    parser.add_argument("--expected-host", default=EXPECTED_HOST)
    parser.add_argument("--worker-bind-host", default=DEFAULT_WORKER_BIND_HOST)
    parser.add_argument("--worker-port", type=int, default=DEFAULT_WORKER_PORT)
    parser.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST)
    parser.add_argument("--ollama-port", type=int, default=DEFAULT_OLLAMA_PORT)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = collect_qualification(
        args.repo,
        expected_host=args.expected_host,
        worker_bind_host=args.worker_bind_host,
        worker_port=args.worker_port,
        ollama_host=args.ollama_host,
        ollama_port=args.ollama_port,
    )
    if args.compact:
        json.dump(report, sys.stdout, sort_keys=True, separators=(",", ":"))
    else:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
