"""Bounded, read-only evidence evaluation for the P14 release soak.

This module deliberately does not import Alpecca runtime modules. Importing
``server.py`` constructs CoreMind, while this harness must remain an observer.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Callable, Mapping, Sequence
import urllib.error
import urllib.request
from urllib.parse import urlsplit


REPORT_SCHEMA = "alpecca.release-soak.report.v1"
STATUS_CAPTURE_SCHEMA = "alpecca.release-soak.status-capture.v1"
PROCESS_STATUS_SCHEMA = "alpecca.release-soak.process-status.v1"
RESULT_SCHEMA = "alpecca.release-soak.result.v1"
APPROVED_REASON_MODEL = "qwen3.5:9b"
DEFAULT_MOBILE_DISCOVERY_URL = (
    "https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/alpecca-endpoint.json"
)
DEFAULT_MOBILE_APK_URL = (
    "https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/"
    "AlpeccaLauncher-v2.1.2.apk"
)
MOBILE_DISCOVERY_SERVICE = "alpecca-mobile-discovery"
MOBILE_DISCOVERY_VERSION = 1
LOCALTUNNEL_BYPASS_HEADER = "bypass-tunnel-reminder"
LOCALTUNNEL_BYPASS_VALUE = "alpecca-release-soak"

CHECK_IDS = (
    "one_instance_evidence",
    "endpoint_health",
    "model_availability",
    "vault_freshness",
    "discord_process_presence",
    "mobile_discovery_continuity",
    "mobile_apk_metadata",
    "test_result_ingestion",
    "build_result_ingestion",
)
VALID_CHECK_STATUSES = frozenset({"pass", "fail", "unknown"})

MAX_OBSERVATIONS = 1_440
MAX_INTERVAL_SECONDS = 3_600.0
MAX_TOTAL_SECONDS = 7 * 24 * 60 * 60
MAX_INPUT_FILES_PER_KIND = 16
MAX_INPUT_BYTES = 256 * 1024
MAX_HEALTH_BYTES = 512
MAX_MOBILE_DISCOVERY_BYTES = 16 * 1024
MAX_MOBILE_DISCOVERY_ROWS = 4
MAX_MOBILE_QUICK_TTL_SECONDS = 24 * 60 * 60
MAX_APK_BYTES = 128 * 1024 * 1024
MAX_PUBLIC_ETAG_LENGTH = 256
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 20_000
MAX_CLOCK_SKEW_SECONDS = 300.0
MAX_PROCESS_COUNT = 64

_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/\\-]{0,127}$")
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
)
_SENSITIVE_SUFFIXES = ("_api_key", "_password", "_secret", "_token")
_RESULT_COUNT_KEYS = frozenset(
    {"passed", "failed", "errors", "skipped", "warnings", "xfailed", "xpassed"}
)


@dataclass(frozen=True)
class CheckResult:
    """One compact check result with only curated, content-free evidence."""

    check: str
    status: str
    summary: str
    evidence: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        status = self.status if self.status in VALID_CHECK_STATUSES else "unknown"
        return {
            "check": self.check,
            "status": status,
            "summary": self.summary,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class SoakConfig:
    """Inputs and hard bounds for one release-soak observation run."""

    health_url: str | None = "http://127.0.0.1:8765/healthz"
    mobile_discovery_url: str | None = None
    mobile_apk_url: str | None = None
    process_status_path: Path | None = None
    runtime_status_path: Path | None = None
    brain_graph_path: Path | None = None
    vault_status_path: Path | None = None
    instance_lock_path: Path | None = None
    test_result_paths: tuple[Path, ...] = ()
    build_result_paths: tuple[Path, ...] = ()
    observations: int = 1
    interval_seconds: float = 0.0
    endpoint_timeout_seconds: float = 2.0
    public_timeout_seconds: float = 5.0
    status_max_age_seconds: float = 300.0
    vault_snapshot_max_age_seconds: float = 900.0
    vault_archive_max_age_seconds: float = 8 * 60 * 60.0
    result_max_age_seconds: float = 24 * 60 * 60.0
    vault_max_pending: int = 0

    def __post_init__(self) -> None:
        if type(self.observations) is not int or not 1 <= self.observations <= MAX_OBSERVATIONS:
            raise ValueError(f"observations must be between 1 and {MAX_OBSERVATIONS}")
        _bounded_number(
            "interval_seconds", self.interval_seconds, minimum=0.0, maximum=MAX_INTERVAL_SECONDS
        )
        if (self.observations - 1) * float(self.interval_seconds) > MAX_TOTAL_SECONDS:
            raise ValueError(f"observation window cannot exceed {MAX_TOTAL_SECONDS} seconds")
        _bounded_number(
            "endpoint_timeout_seconds", self.endpoint_timeout_seconds, minimum=0.05, maximum=10.0
        )
        _bounded_number(
            "public_timeout_seconds", self.public_timeout_seconds, minimum=0.05, maximum=10.0
        )
        for name, value in (
            ("status_max_age_seconds", self.status_max_age_seconds),
            ("vault_snapshot_max_age_seconds", self.vault_snapshot_max_age_seconds),
            ("vault_archive_max_age_seconds", self.vault_archive_max_age_seconds),
            ("result_max_age_seconds", self.result_max_age_seconds),
        ):
            _bounded_number(name, value, minimum=1.0, maximum=MAX_TOTAL_SECONDS)
        if type(self.vault_max_pending) is not int or not 0 <= self.vault_max_pending <= 1_000:
            raise ValueError("vault_max_pending must be between 0 and 1000")
        if len(self.test_result_paths) > MAX_INPUT_FILES_PER_KIND:
            raise ValueError(f"at most {MAX_INPUT_FILES_PER_KIND} test result files are allowed")
        if len(self.build_result_paths) > MAX_INPUT_FILES_PER_KIND:
            raise ValueError(f"at most {MAX_INPUT_FILES_PER_KIND} build result files are allowed")
        if self.health_url is not None:
            _validate_health_url(self.health_url)
        if self.mobile_discovery_url is not None:
            _validate_public_https_url(
                self.mobile_discovery_url,
                field="mobile_discovery_url",
                required_suffix=".json",
            )
        if self.mobile_apk_url is not None:
            _validate_public_https_url(
                self.mobile_apk_url,
                field="mobile_apk_url",
                required_suffix=".apk",
            )


@dataclass(frozen=True)
class _JsonRead:
    value: Mapping[str, object] | None
    modified_at: float | None
    error: str | None


@dataclass(frozen=True)
class _StatusSource:
    provided: bool
    payload: Mapping[str, object] | None = None
    observed_at: float | None = None
    time_basis: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class _LockEvidence:
    provided: bool
    state: str
    owner_pid: int | None = None
    owner_live: bool | None = None


@dataclass(frozen=True)
class _ResultReceipt:
    kind: str
    name: str
    started_at: float
    finished_at: float
    exit_code: int
    counts: Mapping[str, int]


@dataclass(frozen=True)
class _MobileEndpointCandidate:
    url: str
    kind: str
    priority: int
    expires_at: int


def _bounded_number(name: str, value: object, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    numeric = float(value)
    if not math.isfinite(numeric) or not minimum <= numeric <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return numeric


def _utc_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) and result >= 0.0 else None
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    result = parsed.timestamp()
    return result if math.isfinite(result) and result >= 0.0 else None


def _safe_text(value: object, *, limit: int = 128) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = "".join(character for character in value if character >= " " and character != "\x7f")
    return cleaned[:limit]


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _json_shape_error(value: object) -> str | None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES:
            return "json_node_limit"
        if depth > MAX_JSON_DEPTH:
            return "json_depth_limit"
        if isinstance(current, Mapping):
            if len(current) > 4_096:
                return "json_mapping_limit"
            for key, item in current.items():
                if not isinstance(key, str) or len(key) > 128:
                    return "invalid_json_key"
                if _is_sensitive_key(key):
                    return "sensitive_field_rejected"
                stack.append((item, depth + 1))
        elif isinstance(current, list):
            if len(current) > 4_096:
                return "json_list_limit"
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, str):
            if len(current) > 8_192:
                return "json_string_limit"
        elif isinstance(current, float) and not math.isfinite(current):
            return "non_finite_json_number"
        elif current is not None and not isinstance(current, (str, int, float, bool)):
            return "unsupported_json_value"
    return None


def _read_json_mapping(path: Path | None) -> _JsonRead:
    if path is None:
        return _JsonRead(None, None, "not_configured")
    candidate = Path(path)
    try:
        with candidate.open("rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            if opened_stat.st_size > MAX_INPUT_BYTES:
                return _JsonRead(None, opened_stat.st_mtime, "input_too_large")
            raw = handle.read(MAX_INPUT_BYTES + 1)
    except IsADirectoryError:
        return _JsonRead(None, None, "not_a_file")
    except OSError:
        return _JsonRead(None, None, "unavailable")
    if len(raw) > MAX_INPUT_BYTES:
        return _JsonRead(None, opened_stat.st_mtime, "input_too_large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        return _JsonRead(None, opened_stat.st_mtime, "invalid_json")
    if not isinstance(value, Mapping):
        return _JsonRead(None, opened_stat.st_mtime, "root_not_object")
    shape_error = _json_shape_error(value)
    if shape_error:
        return _JsonRead(None, opened_stat.st_mtime, shape_error)
    return _JsonRead(value, opened_stat.st_mtime, None)


def _load_status_source(path: Path | None, expected_kind: str) -> _StatusSource:
    if path is None:
        return _StatusSource(False)
    loaded = _read_json_mapping(path)
    if loaded.error:
        return _StatusSource(True, error=loaded.error)
    assert loaded.value is not None
    root = loaded.value
    if root.get("schema") == STATUS_CAPTURE_SCHEMA:
        if set(root) != {"schema", "kind", "observed_at", "payload"}:
            return _StatusSource(True, error="invalid_capture_fields")
        if root.get("kind") != expected_kind or not isinstance(root.get("payload"), Mapping):
            return _StatusSource(True, error="invalid_capture_kind")
        observed_at = _parse_timestamp(root.get("observed_at"))
        if observed_at is None:
            return _StatusSource(True, error="invalid_capture_timestamp")
        return _StatusSource(
            True,
            payload=root["payload"],
            observed_at=observed_at,
            time_basis="capture_envelope",
        )

    timestamp_value = root.get("observed_at", root.get("observedAt"))
    if timestamp_value is not None:
        observed_at = _parse_timestamp(timestamp_value)
        if observed_at is None:
            return _StatusSource(True, error="invalid_status_timestamp")
        basis = "payload"
    else:
        observed_at = loaded.modified_at
        basis = "file_mtime"
    return _StatusSource(True, payload=root, observed_at=observed_at, time_basis=basis)


def _validate_process_entry(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping) or set(value) != {"count", "pids"}:
        return None
    count = value.get("count")
    pids = value.get("pids")
    if type(count) is not int or not 0 <= count <= MAX_PROCESS_COUNT or not isinstance(pids, list):
        return None
    if len(pids) != count or any(type(pid) is not int or pid <= 0 for pid in pids):
        return None
    if len(set(pids)) != len(pids):
        return None
    return {"count": count, "pids": list(pids)}


def _load_process_status(path: Path | None) -> _StatusSource:
    if path is None:
        return _StatusSource(False)
    loaded = _read_json_mapping(path)
    if loaded.error:
        return _StatusSource(True, error=loaded.error)
    assert loaded.value is not None
    root = loaded.value
    allowed = {"schema", "observed_at", "coremind", "discord_bridge"}
    if not {"schema", "observed_at"}.issubset(root) or not set(root).issubset(allowed):
        return _StatusSource(True, error="invalid_process_status_fields")
    if root.get("schema") != PROCESS_STATUS_SCHEMA:
        return _StatusSource(True, error="unsupported_process_status_schema")
    observed_at = _parse_timestamp(root.get("observed_at"))
    if observed_at is None:
        return _StatusSource(True, error="invalid_process_status_timestamp")
    payload: dict[str, object] = {}
    for key in ("coremind", "discord_bridge"):
        if key in root:
            entry = _validate_process_entry(root[key])
            if entry is None:
                return _StatusSource(True, error=f"invalid_{key}_entry")
            payload[key] = entry
    if not payload:
        return _StatusSource(True, error="empty_process_status")
    return _StatusSource(
        True,
        payload=payload,
        observed_at=observed_at,
        time_basis="payload",
    )


def _load_result_receipt(path: Path, expected_kind: str) -> tuple[_ResultReceipt | None, str | None]:
    loaded = _read_json_mapping(path)
    if loaded.error:
        return None, loaded.error
    assert loaded.value is not None
    root = loaded.value
    required = {"schema", "kind", "name", "started_at", "finished_at", "exit_code", "counts"}
    if set(root) != required:
        return None, "invalid_result_fields"
    if root.get("schema") != RESULT_SCHEMA or root.get("kind") != expected_kind:
        return None, "invalid_result_schema_or_kind"
    name = root.get("name")
    if not isinstance(name, str) or not _LABEL_RE.fullmatch(name):
        return None, "invalid_result_name"
    started_at = _parse_timestamp(root.get("started_at"))
    finished_at = _parse_timestamp(root.get("finished_at"))
    if started_at is None or finished_at is None or finished_at < started_at:
        return None, "invalid_result_timestamps"
    exit_code = root.get("exit_code")
    if type(exit_code) is not int or not -255 <= exit_code <= 255:
        return None, "invalid_result_exit_code"
    raw_counts = root.get("counts")
    if not isinstance(raw_counts, Mapping) or not set(raw_counts).issubset(_RESULT_COUNT_KEYS):
        return None, "invalid_result_counts"
    counts: dict[str, int] = {}
    for key, value in raw_counts.items():
        if type(value) is not int or not 0 <= value <= 10_000_000:
            return None, "invalid_result_counts"
        counts[str(key)] = value
    return _ResultReceipt(expected_kind, name, started_at, finished_at, exit_code, counts), None


def _pid_live_readonly(pid: int) -> bool | None:
    """Query liveness without signals, locks, or process command-line reads."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            open_process = kernel32.OpenProcess
            open_process.argtypes = (ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong)
            open_process.restype = ctypes.c_void_p
            get_exit_code = kernel32.GetExitCodeProcess
            get_exit_code.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
            get_exit_code.restype = ctypes.c_bool
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = (ctypes.c_void_p,)
            close_handle.restype = ctypes.c_bool
            handle = open_process(query_limited_information, False, pid)
            if not handle:
                return False if ctypes.get_last_error() == 87 else None
            try:
                exit_code = ctypes.c_ulong()
                if not get_exit_code(handle, ctypes.byref(exit_code)):
                    return None
                return exit_code.value == still_active
            finally:
                close_handle(handle)
        except (AttributeError, OSError):
            return None
    proc = Path("/proc")
    if proc.is_dir():
        return (proc / str(pid)).exists()
    return None


def _read_lock_evidence(path: Path | None) -> _LockEvidence:
    if path is None:
        return _LockEvidence(False, "not_configured")
    candidate = Path(path)
    try:
        with candidate.open("rb") as handle:
            raw = handle.read(4_097)
    except FileNotFoundError:
        return _LockEvidence(True, "missing")
    except OSError:
        return _LockEvidence(True, "unavailable")
    if len(raw) > 4_096:
        return _LockEvidence(True, "invalid")
    raw = raw.rstrip(b"\0\r\n \t")
    if not raw:
        return _LockEvidence(True, "empty")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return _LockEvidence(True, "invalid")
    if (
        not isinstance(value, Mapping)
        or set(value) != {"version", "pid", "started_at", "hostname"}
        or value.get("version") != 1
        or type(value.get("pid")) is not int
        or isinstance(value.get("started_at"), bool)
        or not isinstance(value.get("started_at"), (int, float))
        or not isinstance(value.get("hostname"), str)
    ):
        return _LockEvidence(True, "invalid")
    pid = int(value["pid"])
    try:
        owner_live = _pid_live_readonly(pid)
    except Exception:
        owner_live = None
    return _LockEvidence(True, "owner_metadata", owner_pid=pid, owner_live=owner_live)


def _source_freshness(
    source: _StatusSource, now: float, max_age_seconds: float
) -> tuple[str, float | None]:
    if source.observed_at is None:
        return "missing_timestamp", None
    if source.observed_at > now + MAX_CLOCK_SKEW_SECONDS:
        return "future_timestamp", source.observed_at - now
    age = max(0.0, now - source.observed_at)
    return ("fresh" if age <= max_age_seconds else "stale"), age


def _timestamp_freshness(
    timestamp: object, now: float, max_age_seconds: float
) -> tuple[str, float | None]:
    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return "missing_or_invalid", None
    if parsed == 0.0:
        return "never", None
    if parsed > now + MAX_CLOCK_SKEW_SECONDS:
        return "future_timestamp", parsed - now
    age = max(0.0, now - parsed)
    return ("fresh" if age <= max_age_seconds else "stale"), age


def _is_loopback_host(hostname: str) -> bool:
    normalized = hostname.strip().rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _split_bounded_url(url: str, field: str):
    if not isinstance(url, str) or len(url) > 2_048:
        raise ValueError(f"{field} must be a bounded URL")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field} has an invalid port") from exc
    return parsed


def _validate_health_url(url: str) -> None:
    parsed = _split_bounded_url(url, "health_url")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("health_url must use HTTP(S) and include a hostname")
    if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
        raise ValueError("health_url permits HTTP only for a loopback host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("health_url cannot contain credentials, query parameters, or fragments")
    if parsed.path != "/healthz":
        raise ValueError("health_url path must be exactly /healthz")


def _validate_public_https_url(url: str, *, field: str, required_suffix: str) -> None:
    parsed = _split_bounded_url(url, field)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{field} must use HTTPS and include a hostname")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{field} cannot contain credentials, query parameters, or fragments")
    if not parsed.path.lower().endswith(required_suffix):
        raise ValueError(f"{field} path must end with {required_suffix}")


def _normalize_mobile_endpoint(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2_048:
        return ""
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    if parsed.path not in {"", "/", "/house-hq"}:
        return ""
    host = parsed.hostname.lower().rstrip(".")
    if not host:
        return ""
    authority = f"[{host}]" if ":" in host else host
    if port is not None and port != 443:
        authority += f":{port}"
    return f"https://{authority}"


def _response_status(response: object) -> int:
    value = getattr(response, "status", None)
    if value is None:
        value = response.getcode()  # type: ignore[attr-defined]
    return int(value)


def _response_url(response: object) -> str:
    return str(response.geturl())  # type: ignore[attr-defined]


def _response_header(response: object, name: str) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(name)
        if value is not None:
            return str(value).strip()
    if isinstance(headers, Mapping):
        for key, value in headers.items():
            if isinstance(key, str) and key.lower() == name.lower():
                return str(value).strip()
    return ""


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _default_health_open(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RejectRedirects())
    return opener.open(request, timeout=timeout)


def probe_healthz(
    url: str | None,
    timeout: float,
    *,
    open_request: Callable[[urllib.request.Request, float], object] | None = None,
) -> CheckResult:
    """Perform one bounded, credential-free, redirect-free ``GET /healthz``."""
    if url is None:
        return CheckResult(
            "endpoint_health",
            "unknown",
            "No health endpoint was configured for this observation.",
            {"configured": False},
        )
    try:
        _validate_health_url(url)
    except ValueError:
        return CheckResult(
            "endpoint_health",
            "unknown",
            "The configured health endpoint was rejected by the inert probe policy.",
            {"configured": True, "policy_valid": False},
        )
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "alpecca-release-soak/1"},
    )
    started = time.perf_counter()
    opener = open_request or _default_health_open
    try:
        with opener(request, float(timeout)) as response:  # type: ignore[attr-defined]
            status = _response_status(response)
            final_url = _response_url(response)
            raw = response.read(MAX_HEALTH_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return CheckResult(
            "endpoint_health",
            "fail",
            "The health endpoint returned a non-success HTTP status.",
            {"configured": True, "http_status": int(exc.code)},
        )
    except Exception as exc:  # Network libraries expose platform-specific errors.
        return CheckResult(
            "endpoint_health",
            "fail",
            "The health endpoint did not produce bounded Alpecca health evidence.",
            {"configured": True, "error": type(exc).__name__},
        )
    latency_ms = round((time.perf_counter() - started) * 1_000.0, 3)
    evidence: dict[str, object] = {
        "configured": True,
        "http_status": status,
        "latency_ms": latency_ms,
        "response_bytes": len(raw),
    }
    if status != 200 or final_url != url:
        evidence["redirected"] = final_url != url
        return CheckResult(
            "endpoint_health",
            "fail",
            "The health endpoint status or final URL did not match the required contract.",
            evidence,
        )
    if not raw or len(raw) > MAX_HEALTH_BYTES:
        return CheckResult(
            "endpoint_health",
            "fail",
            "The health response was empty or exceeded the response bound.",
            evidence,
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return CheckResult(
            "endpoint_health", "fail", "The health response was not valid JSON.", evidence
        )
    valid = (
        isinstance(payload, dict)
        and set(payload) == {"service", "version"}
        and payload.get("service") == "alpecca"
        and type(payload.get("version")) is int
        and payload.get("version") == 1
    )
    if not valid:
        return CheckResult(
            "endpoint_health",
            "fail",
            "The endpoint answered, but not with the exact Alpecca health identity.",
            evidence,
        )
    evidence.update({"service": "alpecca", "version": 1})
    return CheckResult(
        "endpoint_health", "pass", "The exact Alpecca health endpoint contract passed.", evidence
    )


def _mobile_discovery_candidate(
    payload: object, now: float
) -> tuple[_MobileEndpointCandidate | None, dict[str, object], str | None]:
    evidence: dict[str, object] = {
        "service": None,
        "version": None,
        "updated_at": None,
        "candidate_count": 0,
        "expired_endpoint_count": 0,
    }
    required_root = {"service", "version", "updatedAt", "endpoints"}
    if not isinstance(payload, Mapping) or set(payload) != required_root:
        return None, evidence, "invalid_document_fields"
    evidence["service"] = payload.get("service")
    evidence["version"] = payload.get("version")
    if (
        payload.get("service") != MOBILE_DISCOVERY_SERVICE
        or type(payload.get("version")) is not int
        or payload.get("version") != MOBILE_DISCOVERY_VERSION
    ):
        return None, evidence, "invalid_service_or_version"
    updated_at = payload.get("updatedAt")
    endpoints = payload.get("endpoints")
    if (
        type(updated_at) is not int
        or not 0 < updated_at <= 9_007_199_254_740_991
        or not isinstance(endpoints, list)
        or not 1 <= len(endpoints) <= MAX_MOBILE_DISCOVERY_ROWS
    ):
        return None, evidence, "invalid_update_or_endpoint_bounds"
    timestamp = math.floor(now)
    if updated_at > timestamp + MAX_CLOCK_SKEW_SECONDS:
        return None, evidence, "future_updated_at"
    evidence["updated_at"] = updated_at
    evidence["document_age_seconds"] = max(0, timestamp - updated_at)

    candidates: list[_MobileEndpointCandidate] = []
    seen: set[str] = set()
    expired = 0
    required_row = {"url", "kind", "priority", "expiresAt"}
    for row in endpoints:
        if not isinstance(row, Mapping) or set(row) != required_row:
            return None, evidence, "invalid_endpoint_fields"
        url = _normalize_mobile_endpoint(row.get("url"))
        kind = row.get("kind")
        priority = row.get("priority")
        expires_at = row.get("expiresAt")
        if (
            not url
            or kind not in {"named", "quick"}
            or type(priority) is not int
            or not 0 <= priority <= 100
            or type(expires_at) is not int
            or not 0 <= expires_at <= 9_007_199_254_740_991
            or url in seen
        ):
            return None, evidence, "invalid_endpoint_value"
        seen.add(url)
        if kind == "named":
            if expires_at != 0:
                return None, evidence, "invalid_named_expiry"
        else:
            if (
                expires_at <= updated_at
                or expires_at - updated_at > MAX_MOBILE_QUICK_TTL_SECONDS
            ):
                return None, evidence, "invalid_quick_expiry"
            if expires_at <= timestamp:
                expired += 1
                continue
        candidates.append(_MobileEndpointCandidate(url, str(kind), priority, expires_at))

    evidence["candidate_count"] = len(candidates)
    evidence["expired_endpoint_count"] = expired
    if expired:
        return None, evidence, "expired_endpoint"
    if not candidates:
        return None, evidence, "no_current_endpoint"
    candidates.sort(key=lambda item: (item.priority, item.kind != "named", item.url))
    return candidates[0], evidence, None


def probe_mobile_discovery(
    url: str | None,
    timeout: float,
    now: float,
    *,
    open_request: Callable[[urllib.request.Request, float], object] | None = None,
) -> CheckResult:
    """Read the public discovery document and health-check its current endpoint."""
    check = "mobile_discovery_continuity"
    if url is None:
        return CheckResult(
            check,
            "unknown",
            "No public mobile discovery URL was configured for this observation.",
            {"configured": False},
        )
    try:
        _validate_public_https_url(url, field="mobile_discovery_url", required_suffix=".json")
    except ValueError:
        return CheckResult(
            check,
            "unknown",
            "The mobile discovery URL was rejected by the HTTPS-only probe policy.",
            {"configured": True, "policy_valid": False},
        )

    opener = open_request or _default_health_open
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "alpecca-release-soak/1"},
    )
    started = time.perf_counter()
    try:
        with opener(request, float(timeout)) as response:  # type: ignore[attr-defined]
            status = _response_status(response)
            final_url = _response_url(response)
            content_type_raw = _response_header(response, "Content-Type")
            raw = response.read(MAX_MOBILE_DISCOVERY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return CheckResult(
            check,
            "fail",
            "The public discovery object returned a non-success HTTP status.",
            {"configured": True, "discovery_http_status": int(exc.code)},
        )
    except Exception as exc:
        return CheckResult(
            check,
            "fail",
            "The public discovery object did not produce bounded evidence.",
            {"configured": True, "error": type(exc).__name__},
        )
    content_type_valid = (
        len(content_type_raw) <= 128
        and all(32 <= ord(character) < 127 for character in content_type_raw)
    )
    content_type = content_type_raw if content_type_valid else ""
    evidence: dict[str, object] = {
        "configured": True,
        "discovery_http_status": status,
        "discovery_response_bytes": len(raw),
        "discovery_content_type": content_type or None,
        "discovery_content_type_valid": content_type_valid,
        "discovery_latency_ms": round((time.perf_counter() - started) * 1_000.0, 3),
        "discovery_redirected": final_url != url,
    }
    if status != 200 or final_url != url:
        return CheckResult(
            check,
            "fail",
            "The public discovery status or final URL did not match the required contract.",
            evidence,
        )
    if not raw or len(raw) > MAX_MOBILE_DISCOVERY_BYTES:
        return CheckResult(
            check, "fail", "The discovery JSON was empty or exceeded its body bound.", evidence
        )
    if not content_type_valid or (
        content_type and content_type.split(";", 1)[0].strip().lower() != "application/json"
    ):
        return CheckResult(
            check, "fail", "The discovery object did not report a JSON content type.", evidence
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        return CheckResult(check, "fail", "The discovery body was not valid JSON.", evidence)
    shape_error = _json_shape_error(payload)
    if shape_error:
        evidence["schema_error"] = shape_error
        return CheckResult(
            check, "fail", "The discovery JSON failed bounded public-field validation.", evidence
        )
    candidate, document_evidence, schema_error = _mobile_discovery_candidate(payload, now)
    evidence.update(document_evidence)
    if schema_error or candidate is None:
        evidence["schema_error"] = schema_error
        return CheckResult(
            check,
            "fail",
            "The discovery schema, endpoint bounds, or expiry contract did not pass.",
            evidence,
        )

    endpoint_host = urlsplit(candidate.url).hostname or ""
    bypass_used = endpoint_host.lower().endswith(".loca.lt")
    health_headers = {"Accept": "application/json", "User-Agent": "alpecca-release-soak/1"}
    if bypass_used:
        health_headers[LOCALTUNNEL_BYPASS_HEADER] = LOCALTUNNEL_BYPASS_VALUE
    health_url = candidate.url + "/healthz"
    health_request = urllib.request.Request(health_url, method="GET", headers=health_headers)
    health_started = time.perf_counter()
    try:
        with opener(health_request, float(timeout)) as response:  # type: ignore[attr-defined]
            health_status = _response_status(response)
            health_final_url = _response_url(response)
            health_raw = response.read(MAX_HEALTH_BYTES + 1)
    except urllib.error.HTTPError as exc:
        health_status = int(exc.code)
        health_final_url = health_url
        health_raw = b""
    except Exception as exc:
        evidence.update(
            {
                "current_endpoint": candidate.url,
                "current_endpoint_kind": candidate.kind,
                "localtunnel_bypass_header_used": bypass_used,
                "endpoint_health_error": type(exc).__name__,
            }
        )
        return CheckResult(
            check, "fail", "The discovered current endpoint did not return health evidence.", evidence
        )
    evidence.update(
        {
            "current_endpoint": candidate.url,
            "current_endpoint_kind": candidate.kind,
            "current_endpoint_priority": candidate.priority,
            "current_endpoint_expires_at": candidate.expires_at,
            "current_endpoint_expires_in_seconds": (
                None if candidate.expires_at == 0 else max(0, candidate.expires_at - math.floor(now))
            ),
            "localtunnel_bypass_header_used": bypass_used,
            "endpoint_health_http_status": health_status,
            "endpoint_health_response_bytes": len(health_raw),
            "endpoint_health_latency_ms": round(
                (time.perf_counter() - health_started) * 1_000.0, 3
            ),
            "endpoint_health_redirected": health_final_url != health_url,
        }
    )
    if (
        health_status != 200
        or health_final_url != health_url
        or not health_raw
        or len(health_raw) > MAX_HEALTH_BYTES
    ):
        return CheckResult(
            check,
            "fail",
            "The discovered current endpoint failed the bounded health transport contract.",
            evidence,
        )
    try:
        health_payload = json.loads(health_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        health_payload = None
    if health_payload != {"service": "alpecca", "version": 1}:
        return CheckResult(
            check,
            "fail",
            "The discovered endpoint did not return the exact Alpecca health identity.",
            evidence,
        )
    return CheckResult(
        check,
        "pass",
        "The public discovery schema, expiry, selection, and current endpoint health passed.",
        evidence,
    )


def probe_mobile_apk_metadata(
    url: str | None,
    timeout: float,
    *,
    open_request: Callable[[urllib.request.Request, float], object] | None = None,
) -> CheckResult:
    """Read bounded public APK metadata with one credential-free HEAD request."""
    check = "mobile_apk_metadata"
    if url is None:
        return CheckResult(
            check,
            "unknown",
            "No public mobile APK URL was configured for this observation.",
            {"configured": False},
        )
    try:
        _validate_public_https_url(url, field="mobile_apk_url", required_suffix=".apk")
    except ValueError:
        return CheckResult(
            check,
            "unknown",
            "The mobile APK URL was rejected by the HTTPS-only probe policy.",
            {"configured": True, "policy_valid": False},
        )
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={
            "Accept": "application/vnd.android.package-archive",
            "User-Agent": "alpecca-release-soak/1",
        },
    )
    opener = open_request or _default_health_open
    started = time.perf_counter()
    try:
        with opener(request, float(timeout)) as response:  # type: ignore[attr-defined]
            status = _response_status(response)
            final_url = _response_url(response)
            content_type = _response_header(response, "Content-Type")
            content_length_raw = _response_header(response, "Content-Length")
            etag_raw = _response_header(response, "ETag")
            last_modified_raw = _response_header(response, "Last-Modified")
    except urllib.error.HTTPError as exc:
        return CheckResult(
            check,
            "fail",
            "The public APK HEAD request returned a non-success HTTP status.",
            {"configured": True, "http_status": int(exc.code)},
        )
    except Exception as exc:
        return CheckResult(
            check,
            "fail",
            "The public APK HEAD request did not produce bounded metadata.",
            {"configured": True, "error": type(exc).__name__},
        )
    content_type_valid = (
        len(content_type) <= 128
        and all(32 <= ord(character) < 127 for character in content_type)
    )
    media_type = content_type.split(";", 1)[0].strip().lower() if content_type_valid else ""
    content_length = (
        int(content_length_raw)
        if 1 <= len(content_length_raw) <= 20
        and content_length_raw.isascii()
        and content_length_raw.isdigit()
        else None
    )
    etag_valid = (
        1 <= len(etag_raw) <= MAX_PUBLIC_ETAG_LENGTH
        and all(32 <= ord(character) < 127 for character in etag_raw)
    )
    last_modified = (
        last_modified_raw
        if len(last_modified_raw) <= 128
        and all(32 <= ord(character) < 127 for character in last_modified_raw)
        else ""
    )
    evidence: dict[str, object] = {
        "configured": True,
        "artifact": Path(urlsplit(url).path).name,
        "http_status": status,
        "redirected": final_url != url,
        "content_type": content_type if content_type_valid else None,
        "content_type_valid": content_type_valid,
        "content_length": content_length,
        "etag": etag_raw if etag_valid else None,
        "last_modified": last_modified or None,
        "latency_ms": round((time.perf_counter() - started) * 1_000.0, 3),
    }
    if status != 200 or final_url != url:
        return CheckResult(
            check, "fail", "The public APK status or final URL did not match the contract.", evidence
        )
    if media_type != "application/vnd.android.package-archive":
        return CheckResult(
            check, "fail", "The public APK content type was not the Android package media type.", evidence
        )
    if content_length is None or not 0 < content_length <= MAX_APK_BYTES:
        return CheckResult(
            check, "fail", "The public APK content length was missing or outside its bound.", evidence
        )
    if not etag_valid:
        return CheckResult(
            check, "fail", "The public APK did not expose a bounded ETag.", evidence
        )
    return CheckResult(
        check, "pass", "The public APK HEAD metadata passed without downloading the artifact.", evidence
    )


def _check_one_instance(
    process: _StatusSource, lock: _LockEvidence, now: float, max_age: float
) -> CheckResult:
    evidence: dict[str, object] = {
        "process_status_provided": process.provided,
        "lock_metadata_state": lock.state,
    }
    if lock.owner_pid is not None:
        evidence["lock_owner_pid"] = lock.owner_pid
        evidence["lock_owner_live"] = lock.owner_live
    if not process.provided:
        return CheckResult(
            "one_instance_evidence",
            "unknown",
            "Lock owner metadata alone cannot prove that exactly one CoreMind process exists.",
            evidence,
        )
    if process.error:
        evidence["process_status_error"] = process.error
        return CheckResult(
            "one_instance_evidence",
            "unknown",
            "The supplied process inventory was not valid one-instance evidence.",
            evidence,
        )
    freshness, age = _source_freshness(process, now, max_age)
    evidence.update({"process_status_freshness": freshness, "process_status_age_seconds": age})
    if freshness != "fresh":
        return CheckResult(
            "one_instance_evidence",
            "unknown",
            "The process inventory is not fresh enough to establish the current instance count.",
            evidence,
        )
    core = process.payload.get("coremind") if process.payload else None
    if not isinstance(core, Mapping):
        return CheckResult(
            "one_instance_evidence",
            "unknown",
            "The process inventory did not include a CoreMind count.",
            evidence,
        )
    count = int(core["count"])
    pids = list(core["pids"])
    evidence.update({"active_coremind_count": count, "coremind_pids": pids})
    if count != 1:
        summary = (
            "More than one CoreMind process was reported."
            if count > 1
            else "No CoreMind process was reported."
        )
        return CheckResult("one_instance_evidence", "fail", summary, evidence)
    if lock.owner_pid is not None and lock.owner_live is False:
        return CheckResult(
            "one_instance_evidence",
            "fail",
            "The reported CoreMind conflicts with dead singleton owner metadata.",
            evidence,
        )
    if lock.owner_pid is not None and lock.owner_pid not in pids:
        return CheckResult(
            "one_instance_evidence",
            "fail",
            "The process inventory and singleton owner metadata identify different processes.",
            evidence,
        )
    return CheckResult(
        "one_instance_evidence",
        "pass",
        "Fresh process evidence reports exactly one CoreMind process.",
        evidence,
    )


def _graph_probe_state(source: _StatusSource, probe: str) -> tuple[str | None, str | None]:
    if source.payload is None:
        return None, "missing_graph_payload"
    nodes = source.payload.get("nodes")
    if not isinstance(nodes, list):
        return None, "missing_graph_nodes"
    matching = [node for node in nodes if isinstance(node, Mapping) and node.get("probe") == probe]
    if len(matching) != 1:
        return None, "ambiguous_graph_probe"
    state = matching[0].get("state")
    return (state, None) if isinstance(state, str) else (None, "invalid_graph_state")


def _check_model(
    runtime: _StatusSource, graph: _StatusSource, now: float, max_age: float
) -> CheckResult:
    evidence: dict[str, object] = {}
    readings: list[bool] = []
    unusable_sources: list[str] = []
    model_mismatch = False
    evidence["approved_reason_model"] = APPROVED_REASON_MODEL

    if runtime.provided:
        if runtime.error:
            unusable_sources.append("runtime_invalid")
            evidence["runtime_error"] = runtime.error
        else:
            freshness, age = _source_freshness(runtime, now, max_age)
            evidence.update(
                {
                    "runtime_freshness": freshness,
                    "runtime_age_seconds": age,
                    "runtime_time_basis": runtime.time_basis,
                }
            )
            if freshness != "fresh":
                unusable_sources.append("runtime_not_fresh")
            else:
                models = runtime.payload.get("models") if runtime.payload else None
                if isinstance(models, Mapping) and type(models.get("chat_ready")) is bool:
                    ready = bool(models["chat_ready"])
                    readings.append(ready)
                    evidence["runtime_chat_ready"] = ready
                    model = _safe_text(models.get("reason"))
                    if model:
                        evidence["reason_model"] = model
                        model_mismatch = ready and model != APPROVED_REASON_MODEL
                    elif ready:
                        unusable_sources.append("runtime_missing_reason_model")
                else:
                    unusable_sources.append("runtime_missing_chat_ready")

    if graph.provided:
        if graph.error:
            unusable_sources.append("brain_graph_invalid")
            evidence["brain_graph_error"] = graph.error
        else:
            freshness, age = _source_freshness(graph, now, max_age)
            evidence.update(
                {
                    "brain_graph_freshness": freshness,
                    "brain_graph_age_seconds": age,
                    "brain_graph_time_basis": graph.time_basis,
                }
            )
            if freshness != "fresh":
                unusable_sources.append("brain_graph_not_fresh")
            else:
                state, error = _graph_probe_state(graph, "model")
                if error:
                    unusable_sources.append(error)
                else:
                    evidence["brain_graph_model_state"] = state
                    if state == "healthy":
                        readings.append(True)
                    elif state in {"degraded", "disabled"}:
                        readings.append(False)
                    else:
                        unusable_sources.append("brain_graph_model_unknown")

    evidence["unusable_sources"] = unusable_sources
    if model_mismatch:
        return CheckResult(
            "model_availability",
            "fail",
            "The ready runtime reports a reason model other than the approved release model.",
            evidence,
        )
    if True in readings and False in readings:
        return CheckResult(
            "model_availability", "fail", "Model availability evidence conflicts across sources.", evidence
        )
    if False in readings:
        return CheckResult(
            "model_availability", "fail", "A fresh status source reports the chat model unavailable.", evidence
        )
    if unusable_sources:
        return CheckResult(
            "model_availability",
            "unknown",
            "Model readiness could not be established from every configured status source.",
            evidence,
        )
    if True in readings:
        return CheckResult(
            "model_availability", "pass", "Fresh status evidence reports the chat model ready.", evidence
        )
    return CheckResult(
        "model_availability",
        "unknown",
        "No model availability status evidence was provided.",
        evidence,
    )


def _check_vault(source: _StatusSource, now: float, config: SoakConfig) -> CheckResult:
    evidence: dict[str, object] = {"status_provided": source.provided}
    if not source.provided:
        return CheckResult(
            "vault_freshness", "unknown", "No content-free Vault status evidence was provided.", evidence
        )
    if source.error:
        evidence["status_error"] = source.error
        return CheckResult(
            "vault_freshness", "unknown", "The supplied Vault status evidence was invalid.", evidence
        )
    freshness, age = _source_freshness(source, now, config.status_max_age_seconds)
    evidence.update(
        {
            "status_freshness": freshness,
            "status_age_seconds": age,
            "status_time_basis": source.time_basis,
        }
    )
    if freshness != "fresh":
        return CheckResult(
            "vault_freshness", "unknown", "The Vault status capture itself is not fresh.", evidence
        )
    root = source.payload or {}
    if isinstance(root.get("vault"), Mapping):
        root = root["vault"]  # type: ignore[assignment]
    configured = root.get("configured")
    auto_sync = root.get("ready_for_auto_sync")
    evidence.update({"configured": configured, "ready_for_auto_sync": auto_sync})
    if configured is False:
        return CheckResult(
            "vault_freshness", "fail", "Vault status explicitly reports that recovery is not configured.", evidence
        )
    if configured is not True:
        return CheckResult(
            "vault_freshness", "unknown", "Vault configuration state is missing from the status evidence.", evidence
        )
    if auto_sync is False:
        return CheckResult(
            "vault_freshness", "fail", "Vault status reports that automatic snapshot sync is not ready.", evidence
        )
    if auto_sync is not True:
        return CheckResult(
            "vault_freshness",
            "unknown",
            "Vault automatic snapshot-sync readiness is missing from the status evidence.",
            evidence,
        )
    local = root.get("local_status")
    if not isinstance(local, Mapping):
        return CheckResult(
            "vault_freshness", "unknown", "Vault local freshness counters are unavailable.", evidence
        )
    snapshot_state, snapshot_age = _timestamp_freshness(
        local.get("last_success_ts"), now, config.vault_snapshot_max_age_seconds
    )
    archive_state, archive_age = _timestamp_freshness(
        local.get("last_archive_ts"), now, config.vault_archive_max_age_seconds
    )
    pending_snapshots = local.get("pending_snapshots")
    pending_archives = local.get("pending_archives")
    evidence.update(
        {
            "snapshot_freshness": snapshot_state,
            "snapshot_age_seconds": snapshot_age,
            "snapshot_max_age_seconds": config.vault_snapshot_max_age_seconds,
            "archive_freshness": archive_state,
            "archive_age_seconds": archive_age,
            "archive_max_age_seconds": config.vault_archive_max_age_seconds,
            "pending_snapshots": pending_snapshots,
            "pending_archives": pending_archives,
            "max_pending_each": config.vault_max_pending,
        }
    )
    pending_valid = (
        type(pending_snapshots) is int
        and pending_snapshots >= 0
        and type(pending_archives) is int
        and pending_archives >= 0
    )
    if not pending_valid:
        return CheckResult(
            "vault_freshness", "unknown", "Vault pending-outbox counts are missing or invalid.", evidence
        )
    if snapshot_state in {"never", "stale"} or archive_state in {"never", "stale"}:
        return CheckResult(
            "vault_freshness", "fail", "A required Vault snapshot or recovery archive is stale or absent.", evidence
        )
    if snapshot_state != "fresh" or archive_state != "fresh":
        return CheckResult(
            "vault_freshness", "unknown", "Vault freshness timestamps are invalid or future-dated.", evidence
        )
    if pending_snapshots > config.vault_max_pending or pending_archives > config.vault_max_pending:
        return CheckResult(
            "vault_freshness", "fail", "The Vault outbox exceeds the configured pending-item bound.", evidence
        )
    return CheckResult(
        "vault_freshness",
        "pass",
        "Vault snapshot and recovery archive evidence are fresh and within outbox bounds.",
        evidence,
    )


def _check_discord(
    process: _StatusSource, graph: _StatusSource, now: float, max_age: float
) -> CheckResult:
    evidence: dict[str, object] = {}
    readings: list[bool] = []
    unusable_sources: list[str] = []

    if process.provided:
        if process.error:
            unusable_sources.append("process_status_invalid")
            evidence["process_status_error"] = process.error
        else:
            freshness, age = _source_freshness(process, now, max_age)
            evidence.update(
                {"process_status_freshness": freshness, "process_status_age_seconds": age}
            )
            if freshness != "fresh":
                unusable_sources.append("process_status_not_fresh")
            else:
                discord = process.payload.get("discord_bridge") if process.payload else None
                if isinstance(discord, Mapping):
                    count = int(discord["count"])
                    evidence.update(
                        {"discord_bridge_count": count, "discord_bridge_pids": list(discord["pids"])}
                    )
                    if count > 1:
                        return CheckResult(
                            "discord_process_presence",
                            "fail",
                            "More than one Discord bridge process was reported.",
                            evidence,
                        )
                    readings.append(count == 1)
                else:
                    unusable_sources.append("process_status_missing_discord")

    if graph.provided:
        if graph.error:
            unusable_sources.append("brain_graph_invalid")
            evidence["brain_graph_error"] = graph.error
        else:
            freshness, age = _source_freshness(graph, now, max_age)
            evidence.update(
                {"brain_graph_freshness": freshness, "brain_graph_age_seconds": age}
            )
            if freshness != "fresh":
                unusable_sources.append("brain_graph_not_fresh")
            else:
                state, error = _graph_probe_state(graph, "discord")
                if error:
                    unusable_sources.append(error)
                else:
                    evidence["brain_graph_discord_state"] = state
                    if state == "healthy":
                        readings.append(True)
                    elif state in {"degraded", "disabled"}:
                        readings.append(False)
                    else:
                        unusable_sources.append("brain_graph_discord_unknown")

    evidence["unusable_sources"] = unusable_sources
    if True in readings and False in readings:
        return CheckResult(
            "discord_process_presence",
            "fail",
            "Discord process-presence evidence conflicts across sources.",
            evidence,
        )
    if False in readings:
        return CheckResult(
            "discord_process_presence",
            "fail",
            "Fresh evidence reports that the Discord bridge process is absent.",
            evidence,
        )
    if unusable_sources:
        return CheckResult(
            "discord_process_presence",
            "unknown",
            "Discord presence could not be established from every configured source.",
            evidence,
        )
    if True in readings:
        return CheckResult(
            "discord_process_presence",
            "pass",
            "Fresh evidence reports exactly one running Discord bridge.",
            evidence,
        )
    return CheckResult(
        "discord_process_presence",
        "unknown",
        "No Discord process-presence evidence was provided.",
        evidence,
    )


def _check_results(kind: str, paths: Sequence[Path], now: float, max_age: float) -> CheckResult:
    check_id = f"{kind}_result_ingestion"
    if not paths:
        return CheckResult(
            check_id,
            "unknown",
            f"No {kind} result receipts were provided.",
            {"receipt_count": 0},
        )
    valid_names: list[str] = []
    failed_names: list[str] = []
    stale_names: list[str] = []
    duplicate_names: list[str] = []
    seen_names: set[str] = set()
    invalid_count = 0
    total_passed = 0
    for path in paths:
        receipt, error = _load_result_receipt(Path(path), kind)
        if error or receipt is None:
            invalid_count += 1
            continue
        if receipt.name in seen_names:
            duplicate_names.append(receipt.name)
            continue
        seen_names.add(receipt.name)
        age_state, age = _timestamp_freshness(receipt.finished_at, now, max_age)
        if age_state != "fresh":
            stale_names.append(receipt.name)
            continue
        valid_names.append(receipt.name)
        failed = receipt.exit_code != 0 or receipt.counts.get("failed", 0) > 0 or receipt.counts.get("errors", 0) > 0
        if kind == "test":
            passed = receipt.counts.get("passed", 0)
            total_passed += passed
            failed = failed or passed < 1
        if failed:
            failed_names.append(receipt.name)
    evidence: dict[str, object] = {
        "receipt_count": len(paths),
        "valid_names": valid_names,
        "failed_names": failed_names,
        "stale_names": stale_names,
        "duplicate_names": duplicate_names,
        "invalid_receipt_count": invalid_count,
    }
    if kind == "test":
        evidence["reported_passed_tests"] = total_passed
    if failed_names:
        return CheckResult(
            check_id, "fail", f"At least one fresh {kind} result receipt reports failure.", evidence
        )
    if invalid_count or stale_names or duplicate_names:
        return CheckResult(
            check_id,
            "unknown",
            f"Configured {kind} evidence includes invalid or stale receipts.",
            evidence,
        )
    return CheckResult(
        check_id,
        "pass",
        f"All supplied fresh {kind} result receipts report success.",
        evidence,
    )


class ReleaseSoakHarness:
    """Collect a capped series of observations without operating Alpecca."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
        health_probe: Callable[[str | None, float], CheckResult] = probe_healthz,
        public_open: Callable[[urllib.request.Request, float], object] = _default_health_open,
    ) -> None:
        self._clock = clock
        self._sleeper = sleeper
        self._health_probe = health_probe
        self._public_open = public_open

    def _observe(self, config: SoakConfig, sequence: int, now: float) -> dict[str, object]:
        process = _load_process_status(config.process_status_path)
        runtime = _load_status_source(config.runtime_status_path, "runtime")
        graph = _load_status_source(config.brain_graph_path, "brain_graph")
        vault = _load_status_source(config.vault_status_path, "vault")
        lock = _read_lock_evidence(config.instance_lock_path)
        endpoint = self._health_probe(config.health_url, config.endpoint_timeout_seconds)
        mobile_discovery = probe_mobile_discovery(
            config.mobile_discovery_url,
            config.public_timeout_seconds,
            now,
            open_request=self._public_open,
        )
        mobile_apk = probe_mobile_apk_metadata(
            config.mobile_apk_url,
            config.public_timeout_seconds,
            open_request=self._public_open,
        )
        checks = [
            _check_one_instance(process, lock, now, config.status_max_age_seconds),
            endpoint,
            _check_model(runtime, graph, now, config.status_max_age_seconds),
            _check_vault(vault, now, config),
            _check_discord(process, graph, now, config.status_max_age_seconds),
            mobile_discovery,
            mobile_apk,
            _check_results("test", config.test_result_paths, now, config.result_max_age_seconds),
            _check_results("build", config.build_result_paths, now, config.result_max_age_seconds),
        ]
        statuses = Counter(check.status for check in checks)
        return {
            "sequence": sequence,
            "observed_at": _utc_iso(now),
            "counts": {status: statuses.get(status, 0) for status in sorted(VALID_CHECK_STATUSES)},
            "checks": [check.as_dict() for check in checks],
        }

    def run(self, config: SoakConfig) -> dict[str, object]:
        observations: list[dict[str, object]] = []
        started_at = self._clock()
        for index in range(config.observations):
            observed_at = self._clock()
            observations.append(self._observe(config, index + 1, observed_at))
            if index + 1 < config.observations and config.interval_seconds > 0:
                self._sleeper(float(config.interval_seconds))
        generated_at = self._clock()

        summaries: list[dict[str, object]] = []
        all_statuses: list[str] = []
        for check_id in CHECK_IDS:
            statuses = [
                next(
                    check["status"]
                    for check in observation["checks"]  # type: ignore[index]
                    if check["check"] == check_id
                )
                for observation in observations
            ]
            all_statuses.extend(statuses)
            counts = Counter(statuses)
            summaries.append(
                {
                    "check": check_id,
                    "latest_status": statuses[-1],
                    "stable_pass": all(status == "pass" for status in statuses),
                    "counts": {
                        status: counts.get(status, 0) for status in sorted(VALID_CHECK_STATUSES)
                    },
                }
            )
        aggregate = Counter(all_statuses)
        if aggregate.get("fail", 0):
            assessment_status = "checks_failed"
        elif aggregate.get("unknown", 0):
            assessment_status = "insufficient_evidence"
        else:
            assessment_status = "observed_checks_passed"
        all_observed_checks_passed = assessment_status == "observed_checks_passed"

        return {
            "schema": REPORT_SCHEMA,
            "generated_at": _utc_iso(generated_at),
            "phase": {
                "id": "P14",
                "status": "observation_only",
                "completion_claim": False,
                "statement": (
                    "This report covers only the listed observations. It does not establish "
                    "P14 completion, deployment, failover, canary, embodiment, or documentation gates."
                ),
            },
            "policy": {
                "runtime_mutation": "none",
                "network": (
                    "optional credential-free redirect-free GET/HEAD; public requests require HTTPS "
                    "and HTTP is limited to loopback /healthz"
                ),
                "credentials": "not accepted or loaded",
                "commands": "tests and builds are ingested as receipts, never executed",
                "bounds": {
                    "max_observations": MAX_OBSERVATIONS,
                    "max_total_seconds": MAX_TOTAL_SECONDS,
                    "max_input_bytes": MAX_INPUT_BYTES,
                    "max_health_bytes": MAX_HEALTH_BYTES,
                    "max_mobile_discovery_bytes": MAX_MOBILE_DISCOVERY_BYTES,
                    "max_mobile_requests_per_observation": 3,
                    "max_apk_bytes": MAX_APK_BYTES,
                    "max_result_files_per_kind": MAX_INPUT_FILES_PER_KIND,
                },
            },
            "inputs": {
                "health_endpoint_configured": config.health_url is not None,
                "mobile_discovery_configured": config.mobile_discovery_url is not None,
                "mobile_apk_configured": config.mobile_apk_url is not None,
                "process_status_configured": config.process_status_path is not None,
                "runtime_status_configured": config.runtime_status_path is not None,
                "brain_graph_configured": config.brain_graph_path is not None,
                "vault_status_configured": config.vault_status_path is not None,
                "instance_lock_metadata_configured": config.instance_lock_path is not None,
                "test_receipt_count": len(config.test_result_paths),
                "build_receipt_count": len(config.build_result_paths),
            },
            "window": {
                "requested_observations": config.observations,
                "recorded_observations": len(observations),
                "interval_seconds": config.interval_seconds,
                "started_at": _utc_iso(started_at),
                "ended_at": observations[-1]["observed_at"],
            },
            "assessment": {
                "status": assessment_status,
                "all_observed_checks_passed": all_observed_checks_passed,
                "p14_completion_claim": False,
                "counts": {
                    status: aggregate.get(status, 0) for status in sorted(VALID_CHECK_STATUSES)
                },
            },
            "check_summary": summaries,
            "observations": observations,
        }


def render_report(report: Mapping[str, object], *, pretty: bool = True) -> str:
    """Serialize a report deterministically without embedding source payloads."""
    if pretty:
        return json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    return json.dumps(report, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"


__all__ = [
    "APPROVED_REASON_MODEL",
    "CHECK_IDS",
    "DEFAULT_MOBILE_APK_URL",
    "DEFAULT_MOBILE_DISCOVERY_URL",
    "LOCALTUNNEL_BYPASS_HEADER",
    "LOCALTUNNEL_BYPASS_VALUE",
    "MAX_APK_BYTES",
    "MAX_INPUT_BYTES",
    "MAX_MOBILE_DISCOVERY_BYTES",
    "MAX_OBSERVATIONS",
    "PROCESS_STATUS_SCHEMA",
    "REPORT_SCHEMA",
    "RESULT_SCHEMA",
    "STATUS_CAPTURE_SCHEMA",
    "CheckResult",
    "ReleaseSoakHarness",
    "SoakConfig",
    "probe_healthz",
    "probe_mobile_apk_metadata",
    "probe_mobile_discovery",
    "render_report",
]
