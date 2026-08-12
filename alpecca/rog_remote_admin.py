"""Creator-operated remote development access to ``Jason_HOLYROG``.

This module deliberately uses Windows OpenSSH over the private Tailscale path
instead of adding a shell endpoint to Alpecca's HTTP worker.  The House server
may submit arbitrary PowerShell only after its normal creator authentication.
Discord callers are mapped to the fixed read-only commands below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Mapping


HOST_ENV = "ALPECCA_ROG_SSH_HOST"
USER_ENV = "ALPECCA_ROG_SSH_USER"
KEY_ENV = "ALPECCA_ROG_SSH_KEY"
KNOWN_HOSTS_ENV = "ALPECCA_ROG_SSH_KNOWN_HOSTS"
ENABLED_ENV = "ALPECCA_ROG_SSH_ENABLED"
REPO_ENV = "ALPECCA_ROG_REPO_ROOT"

DEFAULT_HOST = "Jason_HOLYROG"
DEFAULT_USER = "Jason"
DEFAULT_REPO = r"C:\Users\Jason\Documents\GitHub\alpaccaai"
MAX_COMMAND_BYTES = 32 * 1024
MAX_OUTPUT_BYTES = 512 * 1024
MAX_TIMEOUT_SECONDS = 3_600
# Windows computer names observed through Tailscale may retain underscores.
_SAFE_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_USER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class RemoteDevelopmentError(RuntimeError):
    """A remote development operation could not be completed."""


@dataclass(frozen=True, slots=True)
class RemoteCommandResult:
    request_id: str
    host: str
    exit_code: int
    stdout: str
    stderr: str
    elapsed_ms: int
    truncated: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "alpecca.remote-development.result.v1",
            "ok": self.exit_code == 0,
            "request_id": self.request_id,
            "host": self.host,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "elapsed_ms": self.elapsed_ms,
            "truncated": self.truncated,
        }


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _data_dir(environment: Mapping[str, str]) -> Path:
    base = str(environment.get("LOCALAPPDATA", "")).strip()
    if base:
        return Path(base) / "Alpecca" / "rog-admin"
    return Path.home() / "AppData" / "Local" / "Alpecca" / "rog-admin"


def _settings(environment: Mapping[str, str]) -> tuple[str, str, Path, Path]:
    host = str(environment.get(HOST_ENV, DEFAULT_HOST)).strip()
    user = str(environment.get(USER_ENV, DEFAULT_USER)).strip()
    root = _data_dir(environment)
    key = Path(str(environment.get(KEY_ENV, root / "id_ed25519"))).expanduser()
    known_hosts = Path(
        str(environment.get(KNOWN_HOSTS_ENV, root / "known_hosts"))
    ).expanduser()
    if not _SAFE_HOST.fullmatch(host):
        raise RemoteDevelopmentError("remote development host is invalid")
    if not _SAFE_USER.fullmatch(user):
        raise RemoteDevelopmentError("remote development user is invalid")
    return host, user, key, known_hosts


def _ssh_executable() -> str:
    executable = shutil.which("ssh.exe") or shutil.which("ssh")
    if not executable:
        raise RemoteDevelopmentError("Windows OpenSSH client is unavailable")
    return executable


def _validate_command(command: object) -> str:
    if not isinstance(command, str) or not command.strip() or "\x00" in command:
        raise RemoteDevelopmentError("command is empty or invalid")
    if len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
        raise RemoteDevelopmentError("command exceeds the development limit")
    return command


def _encoded_powershell(command: str, cwd: str) -> str:
    prefix = "$ProgressPreference='SilentlyContinue';"
    if cwd:
        escaped = cwd.replace("'", "''")
        prefix += f"Set-Location -LiteralPath '{escaped}';"
    return base64.b64encode((prefix + command).encode("utf-16-le")).decode("ascii")


def _audit(environment: Mapping[str, str], record: Mapping[str, object]) -> None:
    path = _data_dir(environment) / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(record), ensure_ascii=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")


def status(environment: Mapping[str, str] | None = None) -> dict[str, object]:
    env = os.environ if environment is None else environment
    enabled = _truthy(env.get(ENABLED_ENV, "0"))
    try:
        host, user, key, known_hosts = _settings(env)
        executable = _ssh_executable()
    except RemoteDevelopmentError as exc:
        return {
            "schema": "alpecca.remote-development.status.v1",
            "enabled": enabled,
            "ready": False,
            "state": "unavailable",
            "reason": type(exc).__name__,
        }
    configured = key.is_file() and known_hosts.is_file()
    return {
        "schema": "alpecca.remote-development.status.v1",
        "enabled": enabled,
        "configured": configured,
        "ready": enabled and configured,
        "state": "ready" if enabled and configured else "setup-required",
        "host": host,
        "user": user,
        "transport": "openssh-over-tailscale",
        "ssh_client": Path(executable).name,
        "house_access": "creator-unrestricted" if enabled and configured else "offline",
        "discord_access": "creator-low-risk" if enabled and configured else "offline",
        "reason": "" if enabled and configured else "OpenSSH enrollment is incomplete",
    }


def execute(
    command: object,
    *,
    cwd: object = "",
    timeout_seconds: object = 300,
    request_id: str = "",
    environment: Mapping[str, str] | None = None,
) -> RemoteCommandResult:
    env = os.environ if environment is None else environment
    if not _truthy(env.get(ENABLED_ENV, "0")):
        raise RemoteDevelopmentError("remote development is disabled")
    clean_command = _validate_command(command)
    clean_cwd = str(cwd or "").strip()
    if "\x00" in clean_cwd or len(clean_cwd.encode("utf-8")) > 2_048:
        raise RemoteDevelopmentError("working directory is invalid")
    if isinstance(timeout_seconds, bool):
        raise RemoteDevelopmentError("timeout is invalid")
    try:
        timeout = int(timeout_seconds)
    except (TypeError, ValueError) as exc:
        raise RemoteDevelopmentError("timeout is invalid") from exc
    if not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise RemoteDevelopmentError("timeout is outside the supported range")
    host, user, key, known_hosts = _settings(env)
    if not key.is_file() or not known_hosts.is_file():
        raise RemoteDevelopmentError("OpenSSH enrollment is incomplete")
    request_ref = request_id.strip() or hashlib.sha256(
        f"{time.time_ns()}:{clean_command}".encode("utf-8")
    ).hexdigest()[:24]
    encoded = _encoded_powershell(clean_command, clean_cwd)
    argv = [
        _ssh_executable(),
        "-T",
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}",
        "-o", "ConnectTimeout=8",
        "-i", str(key),
        f"{user}@{host}",
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-EncodedCommand", encoded,
    ]
    started = time.monotonic()
    command_digest = hashlib.sha256(clean_command.encode("utf-8")).hexdigest()
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        _audit(env, {
            "at": datetime.now(timezone.utc).isoformat(),
            "request_id": request_ref,
            "command_sha256": command_digest,
            "status": "timeout",
            "timeout_seconds": timeout,
        })
        raise RemoteDevelopmentError("remote command timed out") from exc
    elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
    stdout_raw = bytes(completed.stdout or b"")
    stderr_raw = bytes(completed.stderr or b"")
    truncated = len(stdout_raw) + len(stderr_raw) > MAX_OUTPUT_BYTES
    remaining = MAX_OUTPUT_BYTES
    stdout_kept = stdout_raw[:remaining]
    remaining -= len(stdout_kept)
    stderr_kept = stderr_raw[:remaining]
    result = RemoteCommandResult(
        request_id=request_ref,
        host=host,
        exit_code=int(completed.returncode),
        stdout=stdout_kept.decode("utf-8", errors="replace"),
        stderr=stderr_kept.decode("utf-8", errors="replace"),
        elapsed_ms=elapsed_ms,
        truncated=truncated,
    )
    _audit(env, {
        "at": datetime.now(timezone.utc).isoformat(),
        "request_id": request_ref,
        "command_sha256": command_digest,
        "status": "completed",
        "exit_code": result.exit_code,
        "elapsed_ms": elapsed_ms,
        "stdout_sha256": hashlib.sha256(stdout_raw).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr_raw).hexdigest(),
        "truncated": truncated,
    })
    return result


def execute_low_risk(
    action: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> RemoteCommandResult:
    env = os.environ if environment is None else environment
    repo = str(env.get(REPO_ENV, DEFAULT_REPO)).strip()
    commands = {
        "health": "$env:COMPUTERNAME; Get-Date -Format o; Get-Process -Name ollama -ErrorAction SilentlyContinue | Select-Object -First 1 Id,ProcessName",
        "branch": "git branch --show-current; git status --short",
        "log": "git log -5 --oneline --decorate",
        "resources": "Get-CimInstance Win32_OperatingSystem | Select-Object FreePhysicalMemory,TotalVisibleMemorySize; Get-PSDrive -PSProvider FileSystem | Select-Object Name,Free,Used",
    }
    command = commands.get(str(action).strip().casefold())
    if command is None:
        raise RemoteDevelopmentError("Discord development action is not allowed")
    return execute(command, cwd=repo if action != "health" else "", timeout_seconds=30, environment=env)


__all__ = [
    "RemoteCommandResult",
    "RemoteDevelopmentError",
    "execute",
    "execute_low_risk",
    "status",
]
