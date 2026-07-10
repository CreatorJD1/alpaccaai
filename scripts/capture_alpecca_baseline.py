"""Capture and verify an encrypted, non-destructive Alpecca baseline.

The baseline is deliberately separate from the normal rotating startup copy:

* SQLite is copied with its online backup API, so WAL state is consistent.
* Published database/avatar payloads exist only in an AES-256-GCM archive.
  Transactional capture and restore require transient plaintext in the current
  user's local OS temp directory; normal exits remove it and later runs report
  possible stale scratch without deleting unknown paths. Full-disk encryption
  remains advisable.
* The generated inventory contains configuration state, never secret values.
* Verification and restore drills write to new temporary/output directories;
  they never overwrite the live ``data`` tree.

On Windows the default encryption key is wrapped with the current user's DPAPI
identity. Set ``ALPECCA_BASELINE_PASSPHRASE`` for a portable archive instead.
"""
from __future__ import annotations

import argparse
import ast
import base64
import ctypes
import hmac
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows inventory support
    winreg = None  # type: ignore[assignment]

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
except ImportError as exc:  # pragma: no cover - exercised by the CLI environment
    raise SystemExit(
        "Stage 0 baseline capture requires cryptography>=43.0; "
        "run: python -m pip install cryptography"
    ) from exc


MAGIC = b"ALPECCA-BASELINE\x01"
TAG_SIZE = 16
CHUNK_SIZE = 4 * 1024 * 1024
MAX_HEADER_SIZE = 64 * 1024
MAX_METADATA_SIZE = 16 * 1024 * 1024
MAX_PAYLOAD_FILES = 64
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024 * 1024
MAX_ENCRYPTED_BYTES = MAX_PAYLOAD_BYTES + 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
MAX_GLB_JSON_BYTES = 32 * 1024 * 1024
MAX_CENTRAL_DIRECTORY_BYTES = 16 * 1024 * 1024
STALE_SCRATCH_AGE_S = 24 * 60 * 60
DPAPI_ENTROPY = b"Alpecca Stage 0 baseline key v1"
ALLOWED_SCRYPT_PARAMS = {(2**15, 8, 1), (2**17, 8, 1)}
NEW_SCRYPT_PARAMS = {"n": 2**17, "r": 8, "p": 1}
DEFAULT_PAYLOADS = (
    "data/alpecca.db",
    "data/avatar/vrm/alpecca.vrm",
    "data/avatar/vrm/alpecca_vroid_prototype_v4_20260709.vrm",
    "data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v0.vroid",
    "data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v13_base_view_170cm.vroid",
)
SAFE_ENV_VALUES = {
    "ALPECCA_MODEL",
    "ALPECCA_FAST_MODEL",
    "ALPECCA_REFLECT_MODEL",
    "ALPECCA_CHAT_CLOUD_MODEL",
    "ALPECCA_OLLAMA_CLOUD_MODEL",
    "ALPECCA_DEEP_LOCAL_MODEL",
    "ALPECCA_DEEP_BACKEND",
    "ALPECCA_VISION_BACKEND",
    "ALPECCA_VISION_MODEL",
    "ALPECCA_VISION_CLOUD_MODEL",
    "ALPECCA_TTS_BACKEND",
    "ALPECCA_TOOL_MODE",
    "ALPECCA_LLM_BACKEND",
    "ALPECCA_NUM_CTX",
    "ALPECCA_CLOUD_NUM_CTX",
    "ALPECCA_OLLAMA_TIMEOUT",
    "ALPECCA_HISTORY_MESSAGES",
    "ALPECCA_CHAT_ZEROGPU",
    "ALPECCA_REMOTE",
    "ALPECCA_TUNNEL",
    "ALPECCA_COMPUTER_USE",
    "ALPECCA_FILES",
}
SECRET_NAME_RE = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PASSCODE|API_KEY|PRIVATE_KEY|CREDENTIAL)", re.I
)
MODEL_ENV_NAMES = {
    "ALPECCA_MODEL",
    "ALPECCA_FAST_MODEL",
    "ALPECCA_REFLECT_MODEL",
    "ALPECCA_CHAT_CLOUD_MODEL",
    "ALPECCA_OLLAMA_CLOUD_MODEL",
    "ALPECCA_DEEP_LOCAL_MODEL",
    "ALPECCA_VISION_MODEL",
    "ALPECCA_VISION_CLOUD_MODEL",
}
CREDENTIAL_VALUE_RE = re.compile(
    r"(?i)^(?:hf_|ghp_|github_pat_|sk-|eyJ)[A-Za-z0-9._-]{10,}"
)
DOTTED_CREDENTIAL_RE = re.compile(
    r"^[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{20,}$"
)
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CLOCK$",
    "CONIN$",
    "CONOUT$",
    "COM¹",
    "COM²",
    "COM³",
    "LPT¹",
    "LPT²",
    "LPT³",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
SCRATCH_PREFIXES = (
    "alpecca-stage0-capture-",
    "alpecca-baseline-verify-",
    "alpecca-baseline-db-",
)
SECRET_PATTERNS = (
    (
        "named_secret_assignment",
        re.compile(
            rb"(?i)(?:ALPECCA_ACCESS_TOKEN|MINDSCAPE_TOKEN|HF_TOKEN|"
            rb"HUGGING_FACE_HUB_TOKEN|CLOUDFLARE_API_TOKEN|DISCORD_TOKEN)"
            rb"\s*(?:=|:)\s*[\"']?([A-Za-z0-9._~+/=-]{12,})"
        ),
    ),
    ("hugging_face_token", re.compile(rb"\b(hf_[A-Za-z0-9]{20,})\b")),
    (
        "jwt",
        re.compile(
            rb"\b(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
            rb"[A-Za-z0-9_-]{10,})\b"
        ),
    ),
    (
        "private_key",
        re.compile(rb"(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"),
    ),
)


class BaselineError(RuntimeError):
    """A baseline could not be captured, authenticated, or restored."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _stale_scratch_candidates() -> list[str]:
    temp_root = Path(tempfile.gettempdir()).resolve()
    cutoff = time.time() - STALE_SCRATCH_AGE_S
    stale: list[str] = []
    try:
        candidates = list(temp_root.iterdir())
    except OSError:
        return stale
    for candidate in candidates:
        if not any(candidate.name.startswith(prefix) for prefix in SCRATCH_PREFIXES):
            continue
        try:
            if (
                candidate.is_symlink()
                or candidate.resolve().parent != temp_root
                or candidate.stat().st_mtime > cutoff
            ):
                continue
            stale.append(candidate.name)
        except OSError:
            continue
    return sorted(stale)


def _stale_restore_candidates(destination: Path) -> list[str]:
    parent = destination.parent.resolve()
    prefix = f".{destination.name}.staging-"
    cutoff = time.time() - STALE_SCRATCH_AGE_S
    stale: list[str] = []
    try:
        candidates = list(parent.glob(f"{prefix}*"))
    except OSError:
        return stale
    for candidate in candidates:
        try:
            if (
                candidate.is_symlink()
                or candidate.resolve().parent != parent
                or not candidate.name.startswith(prefix)
                or candidate.stat().st_mtime > cutoff
            ):
                continue
            stale.append(candidate.name)
        except OSError:
            continue
    return sorted(stale)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _windows_known_paths() -> tuple[Path, list[Path], Path]:
    if os.name != "nt" or winreg is None:
        raise BaselineError("Windows known folders are unavailable")
    windows_buffer = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetWindowsDirectoryW(windows_buffer, len(windows_buffer)):
        raise BaselineError("Windows directory lookup failed")
    local_buffer = ctypes.create_unicode_buffer(32768)
    # CSIDL_LOCAL_APPDATA resolves through the shell, not a spoofable environment value.
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x001C, None, 0, local_buffer) != 0:
        raise BaselineError("Local AppData known-folder lookup failed")
    program_files: set[Path] = set()
    registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion"
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                registry_path,
                0,
                winreg.KEY_READ | view,
            ) as key:
                for value_name in ("ProgramFilesDir", "ProgramFilesDir (x86)"):
                    try:
                        value, _ = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue
                    if value:
                        program_files.add(Path(str(value)).resolve())
        except OSError:
            continue
    if not program_files:
        raise BaselineError("Program Files registry lookup failed")
    return Path(windows_buffer.value).resolve(), sorted(program_files), Path(local_buffer.value).resolve()


def _resolve_trusted_executable(name: str, cwd: Path, _environ: dict[str, str]) -> Path:
    if Path(name).name != name:
        raise BaselineError(f"subprocess executable must be an unqualified name: {name}")
    if os.name == "nt":
        windows_dir, program_files, local_app_data = _windows_known_paths()
        explicit: dict[str, list[Path]] = {
            "powershell": [
                windows_dir
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            ],
            "nvidia-smi": [windows_dir / "System32" / "nvidia-smi.exe"],
            "ollama": [
                local_app_data / "Programs" / "Ollama" / "ollama.exe",
                *(root / "Ollama" / "ollama.exe" for root in program_files),
            ],
            "git": [root / "Git" / "cmd" / "git.exe" for root in program_files],
        }
        candidates = explicit.get(name.lower(), [])
        trusted_roots = [windows_dir, local_app_data / "Programs" / "Ollama", *program_files]
    else:  # pragma: no cover - this repository's authoritative host is Windows
        trusted_roots = [Path("/usr/bin"), Path("/usr/local/bin")]
        candidates = [root / name for root in trusted_roots]
    cwd_resolved = cwd.resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if not resolved.is_file() or resolved.is_relative_to(cwd_resolved):
            continue
        if any(resolved.is_relative_to(root) for root in trusted_roots):
            return resolved
    raise BaselineError(f"trusted executable was not found: {name}")


def _run(command: list[str], cwd: Path, timeout: float = 10.0) -> dict[str, Any]:
    allowed_names = {
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "COMMONPROGRAMFILES",
        "COMMONPROGRAMFILES(X86)",
        "COMMONPROGRAMW6432",
        "DRIVERDATA",
        "NUMBER_OF_PROCESSORS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    child_env = {
        name: value for name, value in os.environ.items() if name.upper() in allowed_names
    }
    child_env.update(
        {
            name: value
            for name, value in os.environ.items()
            if name.upper().startswith(("CUDA_", "NVIDIA_"))
            and not SECRET_NAME_RE.search(name)
        }
    )
    ollama_host = os.environ.get("OLLAMA_HOST", "")
    if re.match(r"^https?://(?:127\.0\.0\.1|localhost)(?::\d+)?$", ollama_host, re.I):
        child_env["OLLAMA_HOST"] = ollama_host
    try:
        executable = _resolve_trusted_executable(command[0], cwd, dict(os.environ))
        completed = subprocess.run(
            [str(executable), *command[1:]],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except (BaselineError, OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": type(exc).__name__}


def _sqlite_integrity(path: Path) -> str:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10.0)) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    return str(row[0] if row else "missing result")


def _sqlite_backup(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise BaselineError(f"required database is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    uri = f"file:{source.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30.0)) as src:
        with closing(sqlite3.connect(destination, timeout=30.0)) as dst:
            src.backup(dst, pages=2048, sleep=0.01)
    result = _sqlite_integrity(destination)
    if result.lower() != "ok":
        raise BaselineError(f"SQLite snapshot failed integrity_check: {result}")


def _copy_stable(source: Path, destination: Path) -> None:
    before = source.stat()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        destination.unlink(missing_ok=True)
        raise BaselineError(f"source changed during capture: {source}")


def _database_inventory(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False, "path": str(path)}
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    result: dict[str, Any] = {
        "present": True,
        "path": str(path),
        "bytes": path.stat().st_size,
    }
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=10.0)) as conn:
            result["integrity_check"] = str(
                conn.execute("PRAGMA integrity_check").fetchone()[0]
            )
            result["journal_mode"] = str(
                conn.execute("PRAGMA journal_mode").fetchone()[0]
            )
            tables = [
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            counts: dict[str, int] = {}
            for table in tables:
                escaped = table.replace('"', '""')
                try:
                    counts[table] = int(
                        conn.execute(f'SELECT COUNT(*) FROM "{escaped}"').fetchone()[0]
                    )
                except sqlite3.DatabaseError:
                    continue
            result["table_counts"] = counts
    except sqlite3.DatabaseError as exc:
        result["error"] = type(exc).__name__
    return result


def _git_inventory(root: Path) -> dict[str, Any]:
    head = _run(["git", "rev-parse", "HEAD"], root)
    branch = _run(["git", "branch", "--show-current"], root)
    status = _run(["git", "status", "--short"], root)
    return {
        "head": head.get("stdout") if head.get("ok") else None,
        "branch": branch.get("stdout") if branch.get("ok") else None,
        "dirty": bool(status.get("stdout")),
        "status": status.get("stdout", "").splitlines(),
    }


def _route_inventory(server_path: Path) -> list[dict[str, str]]:
    if not server_path.is_file():
        return []
    try:
        tree = ast.parse(server_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    routes: set[tuple[str, str, str]] = set()
    methods = {"get", "post", "put", "patch", "delete", "websocket"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not decorator.args:
                continue
            func = decorator.func
            if not isinstance(func, ast.Attribute) or func.attr not in methods:
                continue
            route = decorator.args[0]
            if isinstance(route, ast.Constant) and isinstance(route.value, str):
                routes.add((func.attr.upper(), route.value, node.name))
    return [
        {"method": method, "path": path, "handler": handler}
        for method, path, handler in sorted(routes)
    ]


def _powershell_hardware(root: Path) -> dict[str, Any]:
    if os.name != "nt":
        return {"platform": platform.platform()}
    command = (
        "$os=Get-CimInstance Win32_OperatingSystem;"
        "$cs=Get-CimInstance Win32_ComputerSystem;"
        "$cpu=Get-CimInstance Win32_Processor|Select-Object -First 1;"
        "$mem=Get-CimInstance Win32_PhysicalMemory;"
        "$disk=Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='C:'\";"
        "$pf=Get-CimInstance Win32_PageFileSetting;"
        "$pu=Get-CimInstance Win32_PageFileUsage;"
        "[ordered]@{"
        "computer_model=$cs.Model;"
        "cpu=$cpu.Name;"
        "automatic_pagefile=[bool]$cs.AutomaticManagedPagefile;"
        "total_ram_gib=[math]::Round($os.TotalVisibleMemorySize/1MB,2);"
        "free_ram_gib=[math]::Round($os.FreePhysicalMemory/1MB,2);"
        "commit_limit_gib=[math]::Round($os.TotalVirtualMemorySize/1MB,2);"
        "free_commit_gib=[math]::Round($os.FreeVirtualMemory/1MB,2);"
        "system_disk=@{capacity_gib=[math]::Round($disk.Size/1GB,2);"
        "free_gib=[math]::Round($disk.FreeSpace/1GB,2)};"
        "memory_modules=@($mem|ForEach-Object{"
        "$memoryType=switch([int]$_.SMBIOSMemoryType){34{'DDR5'}26{'DDR4'}"
        "24{'DDR3'}default{'SMBIOS-'+[string]$_.SMBIOSMemoryType}};"
        "[ordered]@{capacity_gib=[math]::Round($_.Capacity/1GB,2);"
        "speed_mts=$_.Speed;configured_speed_mts=$_.ConfiguredClockSpeed;"
        "memory_type=$memoryType;manufacturer=$_.Manufacturer}});"
        "pagefiles=@($pf|ForEach-Object{[ordered]@{name=$_.Name;"
        "initial_mib=$_.InitialSize;maximum_mib=$_.MaximumSize}});"
        "pagefile_usage=@($pu|ForEach-Object{[ordered]@{name=$_.Name;"
        "allocated_mib=$_.AllocatedBaseSize;current_mib=$_.CurrentUsage;"
        "peak_mib=$_.PeakUsage}})"
        "}|ConvertTo-Json -Compress -Depth 5"
    )
    result = _run(["powershell", "-NoProfile", "-Command", command], root)
    if not result.get("ok"):
        return {"platform": platform.platform(), "error": result.get("error", "query_failed")}
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError:
        return {"platform": platform.platform(), "error": "invalid_hardware_json"}


def _gpu_inventory(root: Path) -> list[dict[str, Any]]:
    result = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,temperature.gpu,driver_version",
            "--format=csv,noheader,nounits",
        ],
        root,
    )
    if not result.get("ok"):
        return []
    gpus = []
    for line in result.get("stdout", "").splitlines():
        values = [part.strip() for part in line.split(",")]
        if len(values) != 5:
            continue
        gpus.append(
            {
                "name": values[0],
                "memory_total_mib": int(values[1]),
                "memory_used_mib": int(values[2]),
                "temperature_c": int(values[3]),
                "driver_version": values[4],
            }
        )
    return gpus


def _ollama_show(model: str) -> dict[str, Any]:
    if not model:
        return {}
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    if not re.match(r"^https?://(?:127\.0\.0\.1|localhost)(?::\d+)?$", host, re.I):
        return {"model": model, "error": "non_local_ollama_host_not_queried"}
    request = urllib.request.Request(
        f"{host}/api/show",
        data=_canonical_json({"model": model}),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            payload = json.load(response)
    except Exception as exc:
        return {"model": model, "error": type(exc).__name__}
    details = payload.get("details") or {}
    model_info = payload.get("model_info") or {}
    projector_info = payload.get("projector_info") or {}
    architecture = str(model_info.get("general.architecture") or details.get("family") or "")
    return {
        "model": model,
        "family": details.get("family"),
        "parameter_size": details.get("parameter_size"),
        "quantization": details.get("quantization_level"),
        "capabilities": sorted(str(item) for item in payload.get("capabilities") or []),
        "context_length": model_info.get(f"{architecture}.context_length"),
        "embedding_length": model_info.get(f"{architecture}.embedding_length"),
        "vision_projector_parameters": projector_info.get("general.parameter_count"),
    }


def _parse_ollama_table(output: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    lines = output.splitlines()
    if not lines:
        return rows
    headings = [field.lower() for field in re.split(r"\s{2,}", lines[0].strip())]
    for line in lines[1:]:
        fields = re.split(r"\s{2,}", line.strip())
        if fields and fields[0]:
            rows.append(
                {
                    heading: fields[index] if index < len(fields) else ""
                    for index, heading in enumerate(headings)
                }
            )
    return rows


def _ollama_inventory(root: Path, primary_model: str = "qwen3.5:9b") -> dict[str, Any]:
    version = _run(["ollama", "--version"], root)
    listing = _run(["ollama", "list"], root, timeout=20.0)
    loaded = _run(["ollama", "ps"], root)
    return {
        "available": bool(version.get("ok")),
        "version": version.get("stdout") if version.get("ok") else None,
        "models": _parse_ollama_table(listing.get("stdout", ""))
        if listing.get("ok")
        else [],
        "loaded_models": _parse_ollama_table(loaded.get("stdout", ""))
        if loaded.get("ok")
        else [],
        "primary_model": _ollama_show(primary_model) if version.get("ok") else {},
    }


def _glb_inventory(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        actual_size = path.stat().st_size
        with path.open("rb") as handle:
            header = handle.read(12)
            if len(header) != 12:
                return {"error": "truncated_glb"}
            magic, version, declared_size = struct.unpack("<4sII", header)
            if magic != b"glTF":
                return {"error": "not_glb"}
            if declared_size != actual_size or declared_size < 20:
                return {"error": "invalid_declared_size"}
            result.update({"glb_version": version, "declared_bytes": declared_size})
            document: dict[str, Any] | None = None
            while handle.tell() < declared_size:
                chunk_header = handle.read(8)
                if len(chunk_header) != 8:
                    break
                chunk_size, chunk_type = struct.unpack("<II", chunk_header)
                remaining = declared_size - handle.tell()
                if chunk_size > remaining:
                    return {**result, "error": "invalid_chunk_size"}
                if chunk_type == 0x4E4F534A:
                    if chunk_size > MAX_GLB_JSON_BYTES:
                        return {**result, "error": "json_chunk_too_large"}
                    chunk = handle.read(chunk_size)
                    document = json.loads(chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
                    break
                handle.seek(chunk_size, os.SEEK_CUR)
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"error": type(exc).__name__}
    if document is None:
        return {**result, "error": "missing_json_chunk"}
    spring_bone = (document.get("extensions") or {}).get("VRMC_springBone") or {}
    springs = spring_bone.get("springs") or []
    joint_references = [
        joint
        for spring in springs
        for joint in spring.get("joints") or []
        if isinstance(joint, dict) and isinstance(joint.get("node"), int)
    ]
    result.update(
        {
            "node_count": len(document.get("nodes") or []),
            "spring_count": len(springs),
            # three-vrm creates one simulated joint per parent->child segment;
            # the final tail node in each spring is a reference, not a joint.
            "spring_joint_count": sum(
                max(0, len(spring.get("joints") or []) - 1) for spring in springs
            ),
            "spring_joint_references": len(joint_references),
            "collider_count": len(spring_bone.get("colliders") or []),
        }
    )
    return result


def _asset_inventory(root: Path) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for relative in DEFAULT_PAYLOADS:
        if relative == "data/alpecca.db":
            continue
        path = root / relative
        if not path.is_file():
            assets.append({"path": relative, "present": False})
            continue
        stat = path.stat()
        item: dict[str, Any] = {
            "path": relative,
            "present": True,
            "bytes": stat.st_size,
            "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "sha256": _sha256_file(path),
        }
        if path.suffix.lower() == ".vrm":
            item["vrm"] = _glb_inventory(path)
        assets.append(item)
    return assets


def _package_inventory() -> dict[str, str | None]:
    packages = ("cryptography", "fastapi", "huggingface-hub", "ollama", "sqlite-vec")
    result: dict[str, str | None] = {}
    for package in packages:
        try:
            result[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            result[package] = None
    return result


def _validated_safe_value(name: str, value: str) -> str | None:
    if not value:
        return ""
    if CREDENTIAL_VALUE_RE.match(value) or DOTTED_CREDENTIAL_RE.fullmatch(value) or (
        len(value) >= 24
        and re.fullmatch(r"[A-Za-z0-9_=+-]+", value)
        and not any(separator in value for separator in (":", "/", ","))
    ):
        return None
    if name in {
        "ALPECCA_NUM_CTX",
        "ALPECCA_CLOUD_NUM_CTX",
        "ALPECCA_OLLAMA_TIMEOUT",
        "ALPECCA_HISTORY_MESSAGES",
    }:
        return value if re.fullmatch(r"[0-9]{1,7}", value) else None
    if name in {
        "ALPECCA_REMOTE",
        "ALPECCA_COMPUTER_USE",
        "ALPECCA_FILES",
        "ALPECCA_CHAT_ZEROGPU",
    }:
        return value if re.fullmatch(r"(?i:0|1|true|false|on|off)", value) else None
    if name == "ALPECCA_TUNNEL":
        return value if value.lower() in {"none", "cloudflare", "ngrok"} else None
    if name == "ALPECCA_TOOL_MODE":
        return value if value.lower() in {"keyword", "smart", "always"} else None
    if name == "ALPECCA_LLM_BACKEND":
        return value if value.lower() in {"ollama", "llamacpp", "hf"} else None
    if name in {"ALPECCA_DEEP_BACKEND", "ALPECCA_VISION_BACKEND"}:
        parts = {part.strip().lower() for part in value.split(",") if part.strip()}
        allowed = {"auto", "local", "ollama", "ollama-cloud", "zerogpu", "none"}
        return value if parts and parts <= allowed else None
    if name == "ALPECCA_TTS_BACKEND":
        return value if value.lower() in {"auto", "f5", "kokoro", "opentts", "edge"} else None
    if name in MODEL_ENV_NAMES:
        if (
            len(value) <= 160
            and "://" not in value
            and ".." not in value
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+-]*", value)
        ):
            return value
    return None


def _redacted_env(environ: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in sorted(key for key in environ if key.startswith("ALPECCA_")):
        value = environ.get(name, "")
        if name in SAFE_ENV_VALUES and not SECRET_NAME_RE.search(name):
            safe_value = _validated_safe_value(name, value)
            result[name] = {
                "set": bool(value),
                "value": safe_value if safe_value is not None else "<redacted>",
            }
        else:
            result[name] = {"set": bool(value), "value": "<redacted>" if value else ""}
    return result


def _launcher_inventory(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False}
    assignments: dict[str, Any] = {}
    assignment_re = re.compile(
        r"^\s*(?:set\s+)?[\"']?(ALPECCA_[A-Za-z0-9_]+)=(.*?)[\"']?\s*$", re.I
    )
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = assignment_re.match(raw_line)
        if not match:
            continue
        name = match.group(1).upper()
        value = match.group(2).strip().strip('"')
        if name in SAFE_ENV_VALUES and not SECRET_NAME_RE.search(name):
            safe_value = _validated_safe_value(name, value)
            assignments[name] = {
                "set": bool(value),
                "value": safe_value if safe_value is not None else "<redacted>",
            }
        else:
            assignments[name] = {"set": bool(value), "value": "<redacted>" if value else ""}
    return {
        "present": True,
        "sha256": _sha256_file(path),
        "assignments": assignments,
    }


def _candidate_source_files(root: Path) -> list[Path]:
    result = _run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"], root
    )
    paths: set[Path] = set()
    if result.get("ok"):
        for item in result.get("stdout", "").splitlines():
            candidate = (root / item).resolve()
            if candidate.is_file():
                paths.add(candidate)
    else:
        for candidate in root.rglob("*"):
            if candidate.is_file() and not any(
                part in {".git", "data", "node_modules", "vendor", "tmp"}
                for part in candidate.relative_to(root).parts
            ):
                paths.add(candidate.resolve())
    dist = root / "apps" / "house-hq" / "dist"
    if dist.is_dir():
        paths.update(path.resolve() for path in dist.rglob("*") if path.is_file())
    return sorted(paths)


def _secret_findings(root: Path) -> list[dict[str, Any]]:
    findings: list[tuple[str, str, int, bytes]] = []
    for path in _candidate_source_files(root):
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in data[:4096]:
            continue
        for rule, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(data):
                secret = match.group(1)
                findings.append(
                    (
                        rule,
                        path.relative_to(root).as_posix(),
                        data.count(b"\n", 0, match.start()) + 1,
                        secret,
                    )
                )
    scan_key = os.urandom(32)
    unique: dict[tuple[str, str, int, bytes], dict[str, Any]] = {}
    for rule, path, line, secret in findings:
        digest = hmac.new(scan_key, secret, hashlib.sha256).digest()
        key = (rule, path, line, digest)
        unique[key] = {"rule": rule, "path": path, "line": line}
    return [
        {"finding_id": f"F{index:03d}", **unique[key]}
        for index, key in enumerate(sorted(unique), start=1)
    ]


def collect_inventory(root: Path, *, include_runtime: bool = True) -> dict[str, Any]:
    root = root.resolve()
    launcher = _launcher_inventory(root / "START_HERE.bat")
    inventory: dict[str, Any] = {
        "schema": "alpecca.stage0.inventory.v1",
        "captured_at": _utc_now(),
        "project": "Alpecca",
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "git": _git_inventory(root),
        "database": _database_inventory(root / "data" / "alpecca.db"),
        "assets": _asset_inventory(root),
        "routes": _route_inventory(root / "server.py"),
        "environment": _redacted_env(dict(os.environ)),
        "launcher": launcher,
        "secret_scan_scope": (
            "Best-effort tracked/untracked text scan plus House HQ dist; "
            "ignored, binary, and files over 8 MiB are not exhaustively scanned."
        ),
        "scratch_policy": (
            "Published payload is encrypted; capture/verification uses transient "
            "plaintext only under the current user's local OS temp directory; "
            "possible stale paths are reported and never deleted automatically."
        ),
        "secret_findings": _secret_findings(root),
    }
    if include_runtime:
        primary_model = (
            ((launcher.get("assignments") or {}).get("ALPECCA_MODEL") or {}).get("value")
            or "qwen3.5:9b"
        )
        inventory.update(
            {
                "hardware": _powershell_hardware(root),
                "gpus": _gpu_inventory(root),
                "ollama": _ollama_inventory(root, str(primary_model)),
                "packages": _package_inventory(),
            }
        )
    return inventory


def _dpapi_wrap(key: bytes) -> bytes:
    if os.name != "nt":
        raise BaselineError("DPAPI key wrapping is available only on Windows")
    try:
        import win32crypt
    except ImportError as exc:  # pragma: no cover - Windows dependency guard
        raise BaselineError("DPAPI mode requires pywin32") from exc
    return bytes(
        win32crypt.CryptProtectData(
            key, "Alpecca Stage 0 baseline", DPAPI_ENTROPY, None, None, 0
        )
    )


def _dpapi_unwrap(wrapped: bytes) -> bytes:
    if os.name != "nt":
        raise BaselineError("this DPAPI archive must be opened by its Windows user")
    try:
        import win32crypt
    except ImportError as exc:  # pragma: no cover - Windows dependency guard
        raise BaselineError("DPAPI mode requires pywin32") from exc
    try:
        return bytes(
            win32crypt.CryptUnprotectData(
                wrapped, DPAPI_ENTROPY, None, None, 0
            )[1]
        )
    except Exception as exc:
        raise BaselineError("DPAPI could not unlock this baseline key") from exc


def _derive_passphrase_key(passphrase: str, salt: bytes, params: dict[str, int]) -> bytes:
    if not passphrase:
        raise BaselineError("portable baseline passphrase is empty")
    return Scrypt(
        salt=salt,
        length=32,
        n=int(params["n"]),
        r=int(params["r"]),
        p=int(params["p"]),
    ).derive(passphrase.encode("utf-8"))


def _validate_new_passphrase(passphrase: str) -> None:
    if len(passphrase) < 16 or len(set(passphrase)) < 4:
        raise BaselineError(
            "portable baseline passphrase must contain at least 16 characters "
            "and four distinct characters"
        )


def _write_key_file(path: Path, archive_id: str, wrapped_key: bytes) -> None:
    payload = {
        "schema": "alpecca.stage0.dpapi-key.v1",
        "archive_id": archive_id,
        "protected_key": base64.b64encode(wrapped_key).decode("ascii"),
    }
    _atomic_write_bytes(path, _canonical_json(payload) + b"\n")


def _load_key_file(path: Path, archive_id: str) -> bytes:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineError(f"invalid DPAPI key file: {path}") from exc
    if payload.get("archive_id") != archive_id:
        raise BaselineError("DPAPI key file belongs to a different archive")
    try:
        wrapped = base64.b64decode(payload["protected_key"], validate=True)
    except (KeyError, ValueError) as exc:
        raise BaselineError("DPAPI key file has invalid key material") from exc
    return _dpapi_unwrap(wrapped)


def _encrypt_file(source: Path, destination: Path, key: bytes, header: dict[str, Any]) -> None:
    nonce = os.urandom(12)
    header = dict(header)
    header["nonce"] = base64.b64encode(nonce).decode("ascii")
    encoded = _canonical_json(header)
    if len(encoded) > MAX_HEADER_SIZE:
        raise BaselineError("baseline encryption header is unexpectedly large")
    aad = MAGIC + struct.pack(">I", len(encoded)) + encoded
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as src, temporary.open("wb") as dst:
            dst.write(aad)
            for chunk in iter(lambda: src.read(CHUNK_SIZE), b""):
                dst.write(encryptor.update(chunk))
            dst.write(encryptor.finalize())
            dst.write(encryptor.tag)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _read_encrypted_header(path: Path) -> tuple[dict[str, Any], bytes, int]:
    with path.open("rb") as handle:
        if handle.read(len(MAGIC)) != MAGIC:
            raise BaselineError("not an Alpecca Stage 0 baseline archive")
        packed = handle.read(4)
        if len(packed) != 4:
            raise BaselineError("truncated baseline header")
        length = struct.unpack(">I", packed)[0]
        if length <= 0 or length > MAX_HEADER_SIZE:
            raise BaselineError("invalid baseline header length")
        encoded = handle.read(length)
        if len(encoded) != length:
            raise BaselineError("truncated baseline metadata")
    try:
        header = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineError("invalid baseline metadata") from exc
    if header.get("schema") != "alpecca.stage0.envelope.v1":
        raise BaselineError("unsupported baseline envelope schema")
    if header.get("project") not in {None, "Alpecca"}:
        raise BaselineError("baseline envelope belongs to another project")
    return header, MAGIC + packed + encoded, len(MAGIC) + 4 + length


def _resolve_archive_key(
    header: dict[str, Any], *, key_file: Path | None, passphrase: str | None
) -> bytes:
    mode = header.get("key_mode")
    if mode == "dpapi":
        if key_file is None:
            raise BaselineError("DPAPI archive requires its .key.json file")
        return _load_key_file(key_file, str(header.get("archive_id") or ""))
    if mode == "passphrase":
        if passphrase is None:
            raise BaselineError("portable archive requires its passphrase")
        try:
            kdf = header["kdf"]
            if not isinstance(kdf, dict):
                raise TypeError("KDF metadata must be an object")
            if kdf.get("name") != "scrypt":
                raise ValueError("unsupported KDF")
            salt = base64.b64decode(kdf["salt"], validate=True)
            params = {name: int(kdf[name]) for name in ("n", "r", "p")}
        except (KeyError, TypeError, ValueError) as exc:
            raise BaselineError("portable archive has invalid KDF parameters") from exc
        if len(salt) != 16 or (params["n"], params["r"], params["p"]) not in ALLOWED_SCRYPT_PARAMS:
            raise BaselineError("portable archive KDF parameters exceed the allowed policy")
        return _derive_passphrase_key(passphrase, salt, params)
    raise BaselineError(f"unsupported baseline key mode: {mode!r}")


def _decrypt_file(
    source: Path, destination: Path, *, key_file: Path | None, passphrase: str | None
) -> dict[str, Any]:
    header, aad, ciphertext_offset = _read_encrypted_header(source)
    key = _resolve_archive_key(header, key_file=key_file, passphrase=passphrase)
    size = source.stat().st_size
    ciphertext_size = size - ciphertext_offset - TAG_SIZE
    if ciphertext_size < 0:
        raise BaselineError("truncated encrypted baseline")
    with source.open("rb") as src:
        src.seek(size - TAG_SIZE)
        tag = src.read(TAG_SIZE)
    try:
        nonce = base64.b64decode(header["nonce"], validate=True)
    except (KeyError, ValueError) as exc:
        raise BaselineError("baseline nonce is invalid") from exc
    def decrypt_pass(output: Path | None = None) -> str:
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(aad)
        digest = hashlib.sha256()
        destination_handle: BinaryIO | None = output.open("xb") if output else None
        try:
            with source.open("rb") as src:
                src.seek(ciphertext_offset)
                remaining = ciphertext_size
                while remaining:
                    chunk = src.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise BaselineError("truncated encrypted baseline payload")
                    remaining -= len(chunk)
                    plaintext = decryptor.update(chunk)
                    digest.update(plaintext)
                    if destination_handle is not None:
                        destination_handle.write(plaintext)
                plaintext = decryptor.finalize()
                digest.update(plaintext)
                if destination_handle is not None:
                    destination_handle.write(plaintext)
                    destination_handle.flush()
                    os.fsync(destination_handle.fileno())
        finally:
            if destination_handle is not None:
                destination_handle.close()
        return digest.hexdigest()

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        expected = str(header.get("plaintext_sha256") or "")
        authenticated_digest = decrypt_pass()
        if not expected or authenticated_digest != expected:
            raise BaselineError("baseline plaintext checksum mismatch")
        written_digest = decrypt_pass(temporary)
        if not hmac.compare_digest(authenticated_digest, written_digest):
            raise BaselineError("baseline changed during authenticated decryption")
        os.replace(temporary, destination)
    except BaselineError:
        raise
    except Exception as exc:
        raise BaselineError("baseline authentication failed") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return header


def _safe_member_path(name: str) -> PurePosixPath:
    if (
        not name
        or "\\" in name
        or "\x00" in name
        or re.match(r"^[A-Za-z]:", name)
        or any(ord(character) < 32 for character in name)
        or any(character in '<>:"|?*' for character in name)
        or any(not component for component in name.split("/"))
    ):
        raise BaselineError(f"unsafe archive path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts:
        raise BaselineError(f"unsafe archive path: {name!r}")
    for component in path.parts:
        basename = component.split(".", 1)[0].upper()
        if (
            component in {".", ".."}
            or component.endswith((" ", "."))
            or basename in WINDOWS_RESERVED_NAMES
        ):
            raise BaselineError(f"unsafe archive path: {name!r}")
    return path


def _preflight_zip_entry_count(path: Path) -> int:
    size = path.stat().st_size
    if size < 22 or size > MAX_ENCRYPTED_BYTES:
        raise BaselineError("decrypted ZIP size is outside policy")
    tail_size = min(size, 65_557)
    with path.open("rb") as handle:
        handle.seek(size - tail_size)
        tail = handle.read(tail_size)
        offset = tail.rfind(b"PK\x05\x06")
        if offset < 0 or len(tail) - offset < 22:
            raise BaselineError("ZIP end-of-central-directory record is missing")
        fields = struct.unpack("<4sHHHHIIH", tail[offset : offset + 22])
        total_entries = int(fields[4])
        central_size = int(fields[5])
        eocd_absolute = size - tail_size + offset
        if total_entries == 0xFFFF:
            locator_offset = eocd_absolute - 20
            if locator_offset < 0:
                raise BaselineError("ZIP64 locator is missing")
            handle.seek(locator_offset)
            locator = handle.read(20)
            if len(locator) != 20 or locator[:4] != b"PK\x06\x07":
                raise BaselineError("ZIP64 locator is invalid")
            _, _, zip64_offset, _ = struct.unpack("<4sIQI", locator)
            if zip64_offset > size - 56:
                raise BaselineError("ZIP64 end record offset is invalid")
            handle.seek(zip64_offset)
            record = handle.read(56)
            if len(record) != 56 or record[:4] != b"PK\x06\x06":
                raise BaselineError("ZIP64 end record is invalid")
            zip64 = struct.unpack("<4sQHHIIQQQQ", record)
            total_entries = int(zip64[7])
            central_size = int(zip64[8])
    if total_entries > MAX_PAYLOAD_FILES + 2:
        raise BaselineError("baseline ZIP entry count exceeds policy")
    if central_size > MAX_CENTRAL_DIRECTORY_BYTES:
        raise BaselineError("baseline ZIP central directory exceeds policy")
    return total_entries


def _verify_zip(zip_path: Path, *, restore_to: Path | None = None) -> dict[str, Any]:
    if restore_to is not None:
        if not restore_to.is_dir() or any(restore_to.iterdir()):
            raise BaselineError(f"restore directory is not empty: {restore_to}")
    preflight_entries = _preflight_zip_entry_count(zip_path)
    try:
        archive = zipfile.ZipFile(zip_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise BaselineError("decrypted baseline is not a valid ZIP archive") from exc
    with archive:
        zip_entries = archive.infolist()
        if len(zip_entries) != preflight_entries or any(
            item.is_dir() for item in zip_entries
        ):
            raise BaselineError("baseline ZIP entry count or type exceeds policy")
        try:
            manifest_info = archive.getinfo("manifest.json")
            inventory_info = archive.getinfo("inventory.json")
            if (
                manifest_info.file_size > MAX_METADATA_SIZE
                or inventory_info.file_size > MAX_METADATA_SIZE
            ):
                raise BaselineError("baseline metadata exceeds the size limit")
            manifest = json.loads(archive.read(manifest_info))
            inventory = json.loads(archive.read(inventory_info))
        except (KeyError, json.JSONDecodeError) as exc:
            raise BaselineError("baseline manifest or inventory is missing or invalid") from exc
        if (
            manifest.get("schema") != "alpecca.stage0.manifest.v1"
            or manifest.get("project") != "Alpecca"
        ):
            raise BaselineError("baseline manifest schema or project is invalid")
        inventory_digest = hashlib.sha256(_canonical_json(inventory)).hexdigest()
        if inventory_digest != manifest.get("inventory_sha256"):
            raise BaselineError("baseline inventory checksum mismatch")
        expected_files = manifest.get("files") or []
        if not isinstance(expected_files, list) or len(expected_files) > MAX_PAYLOAD_FILES:
            raise BaselineError("baseline manifest has too many payload files")
        if not all(isinstance(item, dict) for item in expected_files):
            raise BaselineError("baseline manifest payload entries are invalid")
        expected_names = [str(item.get("archive_path") or "") for item in expected_files]
        if len(expected_names) != len(set(expected_names)):
            raise BaselineError("baseline manifest contains duplicate payload paths")
        if "data/alpecca.db" not in expected_names:
            raise BaselineError("baseline does not contain data/alpecca.db")
        archive_names = [item.filename for item in zip_entries]
        allowed_names = {"manifest.json", "inventory.json", *expected_names}
        if len(archive_names) != len(set(archive_names)) or set(archive_names) != allowed_names:
            raise BaselineError("baseline ZIP entries do not match its manifest")
        try:
            expected_total = sum(int(item.get("bytes", -1)) for item in expected_files)
        except (TypeError, ValueError) as exc:
            raise BaselineError("baseline manifest contains invalid payload sizes") from exc
        if expected_total < 0 or expected_total > MAX_PAYLOAD_BYTES:
            raise BaselineError("baseline payload exceeds the size limit")
        verified: list[dict[str, Any]] = []
        db_restore: Path | None = None
        for item in expected_files:
            name = str(item.get("archive_path") or "")
            safe = _safe_member_path(name)
            try:
                info = archive.getinfo(name)
                source: BinaryIO = archive.open(info, "r")
            except KeyError as exc:
                raise BaselineError(f"baseline payload is missing {name}") from exc
            try:
                expected_size = int(item.get("bytes", -1))
            except (TypeError, ValueError) as exc:
                raise BaselineError(f"invalid payload size in manifest: {name}") from exc
            if expected_size < 0 or expected_size > MAX_PAYLOAD_BYTES:
                raise BaselineError(f"invalid payload size in manifest: {name}")
            if info.file_size != expected_size:
                raise BaselineError(f"ZIP and manifest sizes disagree: {name}")
            if info.compress_size == 0 and info.file_size:
                raise BaselineError(f"invalid compressed payload: {name}")
            if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise BaselineError(f"payload compression ratio exceeds policy: {name}")
            digest = hashlib.sha256()
            size = 0
            target = restore_to.joinpath(*safe.parts) if restore_to is not None else None
            if target is not None:
                restore_root = restore_to.resolve()
                target_resolved = target.resolve(strict=False)
                if not target_resolved.is_relative_to(restore_root):
                    raise BaselineError(f"unsafe restore destination: {name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                output: BinaryIO | None = target.open("xb")
            else:
                output = None
            try:
                with source:
                    for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
                        size += len(chunk)
                        if size > expected_size:
                            raise BaselineError(f"payload exceeds its declared size: {name}")
                        digest.update(chunk)
                        if output is not None:
                            output.write(chunk)
            finally:
                if output is not None:
                    output.close()
            if size != expected_size or digest.hexdigest() != item.get("sha256"):
                raise BaselineError(f"payload checksum mismatch: {name}")
            if name == "data/alpecca.db" and target is not None:
                db_restore = target
            verified.append({"path": name, "bytes": size, "sha256": digest.hexdigest()})
        if restore_to is None:
            with tempfile.TemporaryDirectory(prefix="alpecca-baseline-db-") as temp_dir:
                target = Path(temp_dir) / "alpecca.db"
                try:
                    with archive.open("data/alpecca.db", "r") as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst, CHUNK_SIZE)
                except KeyError as exc:
                    raise BaselineError("baseline does not contain data/alpecca.db") from exc
                integrity = _sqlite_integrity(target)
        elif db_restore is not None:
            integrity = _sqlite_integrity(db_restore)
        else:
            raise BaselineError("baseline does not contain data/alpecca.db")
        if integrity.lower() != "ok":
            raise BaselineError(f"restored SQLite integrity_check failed: {integrity}")
    return {
        "ok": True,
        "schema": "alpecca.stage0.verification.v1",
        "verified_at": _utc_now(),
        "archive_id": manifest.get("archive_id"),
        "files": verified,
        "database_integrity": integrity,
        "restore_drill": restore_to is not None,
    }


def verify_archive(
    archive: Path,
    *,
    key_file: Path | None = None,
    passphrase: str | None = None,
    restore_to: Path | None = None,
) -> dict[str, Any]:
    stale_scratch = _stale_scratch_candidates()
    archive = archive.resolve()
    if not archive.is_file():
        raise BaselineError(f"baseline archive does not exist: {archive}")
    if archive.stat().st_size > MAX_ENCRYPTED_BYTES:
        raise BaselineError("encrypted baseline exceeds the size limit")
    restore_destination = restore_to.resolve() if restore_to is not None else None
    if restore_destination is not None:
        stale_restore = _stale_restore_candidates(restore_destination)
        if restore_destination.exists():
            raise BaselineError(f"restore directory is not empty: {restore_destination}")
        restore_destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="alpecca-baseline-verify-") as temp_dir:
        decrypted = Path(temp_dir) / "baseline.zip"
        header = _decrypt_file(
            archive,
            decrypted,
            key_file=key_file.resolve() if key_file else None,
            passphrase=passphrase,
        )
        staging: Path | None = None
        if restore_destination is not None:
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".{restore_destination.name}.staging-",
                    dir=restore_destination.parent,
                )
            )
        try:
            result = _verify_zip(decrypted, restore_to=staging)
            if result.get("archive_id") != header.get("archive_id"):
                raise BaselineError("baseline manifest and envelope IDs do not match")
            if staging is not None:
                os.replace(staging, restore_destination)
                staging = None
        finally:
            if staging is not None and staging.exists():
                expected_parent = restore_destination.parent.resolve()
                if staging.resolve().parent != expected_parent:
                    raise BaselineError("refusing to clean an unexpected staging path")
                shutil.rmtree(staging)
        result["archive_id"] = header.get("archive_id")
        result["key_mode"] = header.get("key_mode")
        result["encrypted_bytes"] = archive.stat().st_size
        result["stale_scratch_candidates"] = stale_scratch
        result["stale_restore_candidates"] = (
            stale_restore if restore_destination is not None else []
        )
        return result


def _prepare_payload(
    root: Path, work: Path, inventory: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    payload_root = work / "payload"
    payload_root.mkdir(parents=True)
    files: list[dict[str, Any]] = []
    for relative in DEFAULT_PAYLOADS:
        source = root / relative
        if relative == "data/alpecca.db":
            target = payload_root / relative
            _sqlite_backup(source, target)
            archived_database = _database_inventory(target)
            archived_database["path"] = relative
            archived_database["source"] = "archived_snapshot"
            inventory["database"] = archived_database
        else:
            if not source.is_file():
                continue
            target = payload_root / relative
            _copy_stable(source, target)
        stat = target.stat()
        files.append(
            {
                "source_path": relative,
                "archive_path": relative,
                "bytes": stat.st_size,
                "mtime_utc": datetime.fromtimestamp(
                    stat.st_mtime, timezone.utc
                ).replace(microsecond=0).isoformat(),
                "sha256": _sha256_file(target),
            }
        )
    inventory["assets"] = _asset_inventory(payload_root)
    archive_id = str(uuid.uuid4())
    manifest = {
        "schema": "alpecca.stage0.manifest.v1",
        "archive_id": archive_id,
        "project": "Alpecca",
        "created_at": _utc_now(),
        "files": files,
        "inventory_sha256": hashlib.sha256(_canonical_json(inventory)).hexdigest(),
    }
    _atomic_write_bytes(
        payload_root / "manifest.json", _canonical_json(manifest) + b"\n"
    )
    _atomic_write_bytes(
        payload_root / "inventory.json", _canonical_json(inventory) + b"\n"
    )
    zip_path = work / "baseline.zip"
    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        archive.write(payload_root / "manifest.json", "manifest.json")
        archive.write(payload_root / "inventory.json", "inventory.json")
        for item in files:
            archive.write(
                payload_root / item["archive_path"], item["archive_path"]
            )
    return zip_path, manifest


def capture_baseline(
    root: Path,
    output_root: Path,
    *,
    passphrase: str | None = None,
    include_runtime: bool = True,
) -> dict[str, Any]:
    stale_scratch = _stale_scratch_candidates()
    if passphrase is not None:
        _validate_new_passphrase(passphrase)
    root = root.resolve()
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_root / run_name
    if run_dir.exists():
        run_name = f"{run_name}-{uuid.uuid4().hex[:8]}"
        run_dir = output_root / run_name
    staging_run = output_root / f".incomplete-{run_name}-{uuid.uuid4().hex[:8]}"
    staging_run.mkdir(mode=0o700)
    archive_name = f"alpecca-stage0-{run_name}.apb"
    key_name = f"alpecca-stage0-{run_name}.key.json"
    try:
        inventory = collect_inventory(root, include_runtime=include_runtime)
        inventory["stale_scratch_candidates"] = stale_scratch
        with tempfile.TemporaryDirectory(prefix="alpecca-stage0-capture-") as temp_dir:
            zip_path, manifest = _prepare_payload(root, Path(temp_dir), inventory)
            archive_staging = staging_run / archive_name
            key_file_staging: Path | None = None
            header: dict[str, Any] = {
                "schema": "alpecca.stage0.envelope.v1",
                "project": "Alpecca",
                "archive_id": manifest["archive_id"],
                "created_at": manifest["created_at"],
                "plaintext_sha256": _sha256_file(zip_path),
            }
            if passphrase is not None:
                salt = os.urandom(16)
                params = dict(NEW_SCRYPT_PARAMS)
                key = _derive_passphrase_key(passphrase, salt, params)
                header["key_mode"] = "passphrase"
                header["kdf"] = {
                    **params,
                    "name": "scrypt",
                    "salt": base64.b64encode(salt).decode("ascii"),
                }
            else:
                key = os.urandom(32)
                header["key_mode"] = "dpapi"
                key_file_staging = staging_run / key_name
                _write_key_file(
                    key_file_staging, manifest["archive_id"], _dpapi_wrap(key)
                )
            _encrypt_file(zip_path, archive_staging, key, header)
            verify_dir = Path(temp_dir) / "restore-drill"
            verification = verify_archive(
                archive_staging,
                key_file=key_file_staging,
                passphrase=passphrase,
                restore_to=verify_dir,
            )
        archive = run_dir / archive_name
        key_file = run_dir / key_name if key_file_staging is not None else None
        verification_path = run_dir / "verification.json"
        summary = {
            "ok": True,
            "schema": "alpecca.stage0.capture-result.v1",
            "captured_at": manifest["created_at"],
            "archive_id": manifest["archive_id"],
            "run_dir": str(run_dir),
            "archive": str(archive),
            "key_file": str(key_file) if key_file else None,
            "key_mode": header["key_mode"],
            "inventory": str(run_dir / "inventory.json"),
            "verification": str(verification_path),
            "files": manifest["files"],
            "database_integrity": verification["database_integrity"],
            "restore_drill": verification["restore_drill"],
        }
        _atomic_write_bytes(
            staging_run / "inventory.json", _canonical_json(inventory) + b"\n"
        )
        _atomic_write_bytes(
            staging_run / "verification.json",
            _canonical_json(verification) + b"\n",
        )
        _atomic_write_bytes(
            staging_run / "capture.json", _canonical_json(summary) + b"\n"
        )
        os.replace(staging_run, run_dir)
    finally:
        if staging_run.exists():
            if staging_run.resolve().parent != output_root:
                raise BaselineError("refusing to clean an unexpected capture path")
            shutil.rmtree(staging_run)
    latest = output_root / "latest.json"
    _atomic_write_bytes(
        latest,
        _canonical_json(
            {
                "schema": "alpecca.stage0.latest.v1",
                "run_dir": run_dir.name,
                "archive": archive.name,
                "key_file": key_file.name if key_file else None,
                "updated_at": _utc_now(),
            }
        )
        + b"\n",
    )
    return summary


def _passphrase_from_env(name: str) -> str | None:
    value = os.environ.pop(name, None)
    return value if value else None


def _default_key_file(archive: Path) -> Path | None:
    candidates = sorted(archive.parent.glob("*.key.json"))
    return candidates[0] if len(candidates) == 1 else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture", help="capture and verify a new baseline")
    capture.add_argument("--root", type=Path, default=Path.cwd())
    capture.add_argument(
        "--output-root", type=Path, default=Path("data/baselines/stage0")
    )
    capture.add_argument(
        "--passphrase-env",
        default="ALPECCA_BASELINE_PASSPHRASE",
        help="use this environment variable for a portable archive; DPAPI otherwise",
    )

    inventory = subparsers.add_parser("inventory", help="print sanitized inventory")
    inventory.add_argument("--root", type=Path, default=Path.cwd())

    for name in ("verify", "restore"):
        command = subparsers.add_parser(name)
        command.add_argument("archive", type=Path)
        command.add_argument("--key-file", type=Path)
        command.add_argument(
            "--passphrase-env", default="ALPECCA_BASELINE_PASSPHRASE"
        )
        if name == "restore":
            command.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "inventory":
            result = collect_inventory(args.root)
        elif args.command == "capture":
            result = capture_baseline(
                args.root,
                args.output_root,
                passphrase=_passphrase_from_env(args.passphrase_env),
            )
        else:
            key_file = args.key_file or _default_key_file(args.archive)
            result = verify_archive(
                args.archive,
                key_file=key_file,
                passphrase=_passphrase_from_env(args.passphrase_env),
                restore_to=args.output_dir.resolve()
                if args.command == "restore"
                else None,
            )
    except BaselineError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
