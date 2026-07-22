"""Content-free, observation-only evidence for one live Alpecca stack snapshot.

This module deliberately has no process-control, command-execution, credential,
or message-delivery surface. Network observations are bounded, proxy-disabled,
redirect-free GET/HEAD requests to fixed read-only contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import struct
import time
from typing import Callable, Mapping
import urllib.error
import urllib.request
from urllib.parse import urlsplit


RECEIPT_SCHEMA = "alpecca.release-soak.live-stack-receipt.v1"
CAPTURE_SCHEMA = "alpecca.release-soak.live-stack-capture.v1"
DEFAULT_LOCAL_HEALTH_URL = "http://127.0.0.1:8765/healthz"
DEFAULT_BRAIN_GARDEN_URL = "http://127.0.0.1:8765/brain/graph"
DEFAULT_F5_HEALTH_URL = "http://127.0.0.1:8776/health"
DEFAULT_DISCOVERY_URL = (
    "https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/"
    "alpecca-endpoint.json"
)
DEFAULT_APK_URL = (
    "https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/"
    "AlpeccaLauncher-v2.1.2.apk"
)
REVIEWED_APK_VERSION = "2.1.2"
REVIEWED_APK_BYTES = 1_211_336
REVIEWED_V4_NAME = "alpecca_vroid_prototype_v4_20260709.vrm"
REVIEWED_VRM_SPEC_VERSION = "1.0"
DISCOVERY_SERVICE = "alpecca-mobile-discovery"
DISCOVERY_VERSION = 1
LOCALTUNNEL_BYPASS_HEADER = "bypass-tunnel-reminder"
LOCALTUNNEL_BYPASS_VALUE = "alpecca-release-soak"

MAX_HEALTH_BYTES = 512
MAX_F5_BYTES = 2 * 1024
MAX_DISCOVERY_BYTES = 16 * 1024
MAX_CAPTURE_BYTES = 16 * 1024
MAX_VRM_BYTES = 128 * 1024 * 1024
MAX_VRM_JSON_BYTES = 1024 * 1024
MAX_DISCOVERY_ROWS = 4
MAX_QUICK_TTL_SECONDS = 24 * 60 * 60
MAX_CLOCK_SKEW_SECONDS = 30
CHECK_IDS = (
    "local_coremind_identity_health",
    "brain_garden_protected_availability",
    "discord_bridge_control_readiness",
    "f5_voice_worker_readiness",
    "public_relay_identity_match",
    "r2_endpoint_discovery_consistency",
    "reviewed_android_artifact_metadata",
    "v4_asset_presence_manifest",
)


@dataclass(frozen=True)
class LiveStackConfig:
    """Inputs for exactly one bounded observation snapshot."""

    observer_capture_path: Path | None = None
    local_health_url: str = DEFAULT_LOCAL_HEALTH_URL
    brain_garden_url: str = DEFAULT_BRAIN_GARDEN_URL
    f5_health_url: str = DEFAULT_F5_HEALTH_URL
    discovery_url: str = DEFAULT_DISCOVERY_URL
    apk_url: str = DEFAULT_APK_URL
    v4_asset_path: Path = Path("data/avatar/vrm") / REVIEWED_V4_NAME
    promoted_vrm_path: Path = Path("data/avatar/vrm/alpecca.vrm")
    network_enabled: bool = True
    timeout_seconds: float = 2.0
    capture_max_age_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not 0.05 <= float(self.timeout_seconds) <= 5.0:
            raise ValueError("timeout_seconds must be between 0.05 and 5")
        if not 1.0 <= float(self.capture_max_age_seconds) <= 3_600.0:
            raise ValueError("capture_max_age_seconds must be between 1 and 3600")
        _validate_loopback_url(self.local_health_url, "/healthz", "local_health_url")
        _validate_loopback_url(self.brain_garden_url, "/brain/graph", "brain_garden_url")
        _validate_loopback_url(self.f5_health_url, "/health", "f5_health_url")
        _validate_public_url(self.discovery_url, "/mobile/alpecca-endpoint.json", "discovery_url")
        _validate_public_url(
            self.apk_url,
            f"/mobile/AlpeccaLauncher-v{REVIEWED_APK_VERSION}.apk",
            "apk_url",
        )


@dataclass(frozen=True)
class _Candidate:
    url: str
    kind: str
    priority: int
    expires_at: int


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _default_open(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RejectRedirects())
    return opener.open(request, timeout=timeout)


def _is_loopback(hostname: str) -> bool:
    normalized = hostname.strip().rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _split_url(value: str, field: str):
    if not isinstance(value, str) or not value or len(value) > 2_048:
        raise ValueError(f"{field} must be a bounded URL")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field} is invalid") from exc
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{field} must not contain credentials, query parameters, or fragments")
    return parsed


def _validate_loopback_url(value: str, path: str, field: str) -> None:
    parsed = _split_url(value, field)
    if parsed.scheme != "http" or not parsed.hostname or not _is_loopback(parsed.hostname):
        raise ValueError(f"{field} must use loopback HTTP")
    if parsed.path != path:
        raise ValueError(f"{field} has an invalid path")


def _validate_public_url(value: str, path: str, field: str) -> None:
    parsed = _split_url(value, field)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{field} must use HTTPS")
    if parsed.path != path:
        raise ValueError(f"{field} has an invalid path")


def _response_status(response: object) -> int:
    status = getattr(response, "status", None)
    return int(status if status is not None else response.getcode())  # type: ignore[attr-defined]


def _response_url(response: object) -> str:
    return str(response.geturl())  # type: ignore[attr-defined]


def _header(response: object, name: str) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    value = getter(name) if callable(getter) else None
    return str(value).strip() if value is not None else ""


def _check(
    check_id: str,
    status: str,
    summary: str,
    evidence: Mapping[str, object],
    unknowns: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "check": check_id,
        "status": status,
        "summary": summary,
        "evidence": dict(evidence),
        "unknowns": list(unknowns),
    }


def _identity_probe(
    url: str,
    timeout: float,
    opener: Callable[[urllib.request.Request, float], object],
    *,
    localtunnel_bypass: bool = False,
) -> dict[str, object]:
    headers = {"Accept": "application/json", "User-Agent": "alpecca-live-stack-observer/1"}
    if localtunnel_bypass:
        headers[LOCALTUNNEL_BYPASS_HEADER] = LOCALTUNNEL_BYPASS_VALUE
    request = urllib.request.Request(url, method="GET", headers=headers)
    started = time.perf_counter()
    try:
        with opener(request, timeout) as response:  # type: ignore[attr-defined]
            status = _response_status(response)
            redirected = _response_url(response) != url
            raw = response.read(MAX_HEALTH_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return {"status": "fail", "http_status": int(exc.code), "error": "http_status"}
    except Exception as exc:
        return {"status": "fail", "error": type(exc).__name__}
    evidence = {
        "http_status": status,
        "redirected": redirected,
        "response_bytes": len(raw),
        "latency_ms": round((time.perf_counter() - started) * 1_000.0, 3),
    }
    if status != 200 or redirected or not raw or len(raw) > MAX_HEALTH_BYTES:
        return {"status": "fail", **evidence, "error": "transport_contract"}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        return {"status": "fail", **evidence, "error": "invalid_json"}
    if payload != {"service": "alpecca", "version": 1}:
        return {"status": "fail", **evidence, "error": "identity_mismatch"}
    return {
        "status": "pass",
        **evidence,
        "identity": {"service": "alpecca", "version": 1},
    }


def _brain_boundary_probe(
    url: str,
    timeout: float,
    opener: Callable[[urllib.request.Request, float], object],
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "alpecca-live-stack-observer/1"},
    )
    started = time.perf_counter()
    try:
        with opener(request, timeout) as response:  # type: ignore[attr-defined]
            status = _response_status(response)
            redirected = _response_url(response) != url
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        redirected = str(exc.geturl()) != url
    except Exception as exc:
        return {"status": "fail", "error": type(exc).__name__, "body_read": False}
    protected = status in {401, 403} and not redirected
    return {
        "status": "pass" if protected else "fail",
        "http_status": status,
        "redirected": redirected,
        "protected": protected,
        "body_read": False,
        "latency_ms": round((time.perf_counter() - started) * 1_000.0, 3),
    }


def _f5_probe(
    url: str,
    timeout: float,
    opener: Callable[[urllib.request.Request, float], object],
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "alpecca-live-stack-observer/1"},
    )
    started = time.perf_counter()
    try:
        with opener(request, timeout) as response:  # type: ignore[attr-defined]
            status = _response_status(response)
            redirected = _response_url(response) != url
            raw = response.read(MAX_F5_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return {"status": "fail", "http_status": int(exc.code), "error": "http_status"}
    except Exception as exc:
        return {"status": "fail", "error": type(exc).__name__}
    evidence = {
        "http_status": status,
        "redirected": redirected,
        "response_bytes": len(raw),
        "latency_ms": round((time.perf_counter() - started) * 1_000.0, 3),
    }
    if status != 200 or redirected or not raw or len(raw) > MAX_F5_BYTES:
        return {"status": "fail", **evidence, "error": "transport_contract"}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        return {"status": "fail", **evidence, "error": "invalid_json"}
    ready = isinstance(payload, Mapping) and payload.get("ok") is True and payload.get("ready") is True
    return {
        "status": "pass" if ready else "fail",
        **evidence,
        "ready": ready,
    }


def _normalize_endpoint(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2_048:
        return ""
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/", "/house-hq"}
    ):
        return ""
    host = parsed.hostname.lower().rstrip(".")
    authority = f"[{host}]" if ":" in host else host
    if port is not None and port != 443:
        authority += f":{port}"
    return f"https://{authority}"


def _parse_discovery(payload: object, now: float) -> tuple[_Candidate | None, dict[str, object]]:
    evidence: dict[str, object] = {
        "service": None,
        "version": None,
        "document_age_seconds": None,
        "endpoint_count": 0,
        "selected_kind": None,
    }
    if not isinstance(payload, Mapping) or set(payload) != {
        "service", "version", "updatedAt", "endpoints"
    }:
        return None, {**evidence, "schema_error": "invalid_document_fields"}
    evidence["service"] = payload.get("service")
    evidence["version"] = payload.get("version")
    if payload.get("service") != DISCOVERY_SERVICE or payload.get("version") != DISCOVERY_VERSION:
        return None, {**evidence, "schema_error": "invalid_service_or_version"}
    updated_at = payload.get("updatedAt")
    rows = payload.get("endpoints")
    if type(updated_at) is not int or not isinstance(rows, list) or not 1 <= len(rows) <= MAX_DISCOVERY_ROWS:
        return None, {**evidence, "schema_error": "invalid_bounds"}
    current = math.floor(now)
    if updated_at <= 0 or updated_at > current + MAX_CLOCK_SKEW_SECONDS:
        return None, {**evidence, "schema_error": "invalid_updated_at"}
    evidence["document_age_seconds"] = max(0, current - updated_at)
    evidence["endpoint_count"] = len(rows)
    candidates: list[_Candidate] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {"url", "kind", "priority", "expiresAt"}:
            return None, {**evidence, "schema_error": "invalid_endpoint_fields"}
        endpoint = _normalize_endpoint(row.get("url"))
        kind = row.get("kind")
        priority = row.get("priority")
        expires_at = row.get("expiresAt")
        if (
            not endpoint
            or endpoint in seen
            or kind not in {"named", "quick"}
            or type(priority) is not int
            or not 0 <= priority <= 100
            or type(expires_at) is not int
            or expires_at < 0
        ):
            return None, {**evidence, "schema_error": "invalid_endpoint_value"}
        seen.add(endpoint)
        if kind == "named" and expires_at != 0:
            return None, {**evidence, "schema_error": "invalid_named_expiry"}
        if kind == "quick":
            if expires_at <= updated_at or expires_at - updated_at > MAX_QUICK_TTL_SECONDS:
                return None, {**evidence, "schema_error": "invalid_quick_expiry"}
            if expires_at <= current:
                return None, {**evidence, "schema_error": "expired_endpoint"}
        candidates.append(_Candidate(endpoint, str(kind), priority, expires_at))
    candidates.sort(key=lambda item: (item.priority, item.kind != "named", item.url))
    selected = candidates[0]
    evidence["selected_kind"] = selected.kind
    evidence["selected_priority"] = selected.priority
    evidence["selected_expires_in_seconds"] = (
        None if selected.expires_at == 0 else max(0, selected.expires_at - current)
    )
    return selected, evidence


def _origin_id(origin: str) -> str:
    return "sha256:" + hashlib.sha256(origin.encode("utf-8")).hexdigest()[:16]


def _discovery_probe(
    url: str,
    timeout: float,
    now: float,
    opener: Callable[[urllib.request.Request, float], object],
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "alpecca-live-stack-observer/1"},
    )
    started = time.perf_counter()
    try:
        with opener(request, timeout) as response:  # type: ignore[attr-defined]
            status = _response_status(response)
            redirected = _response_url(response) != url
            content_type = _header(response, "Content-Type")
            raw = response.read(MAX_DISCOVERY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return {"status": "fail", "http_status": int(exc.code), "error": "http_status"}
    except Exception as exc:
        return {"status": "fail", "error": type(exc).__name__}
    evidence: dict[str, object] = {
        "http_status": status,
        "redirected": redirected,
        "response_bytes": len(raw),
        "latency_ms": round((time.perf_counter() - started) * 1_000.0, 3),
    }
    media_type = content_type.split(";", 1)[0].strip().lower()
    if (
        status != 200
        or redirected
        or not raw
        or len(raw) > MAX_DISCOVERY_BYTES
        or media_type != "application/json"
    ):
        return {"status": "fail", **evidence, "error": "transport_contract"}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        return {"status": "fail", **evidence, "error": "invalid_json"}
    selected, parsed_evidence = _parse_discovery(payload, now)
    evidence.update(parsed_evidence)
    if selected is None:
        return {"status": "fail", **evidence}
    return {
        "status": "pass",
        **evidence,
        "selected_origin_id": _origin_id(selected.url),
        "_selected_url": selected.url,
    }


def _apk_probe(
    url: str,
    timeout: float,
    opener: Callable[[urllib.request.Request, float], object],
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={
            "Accept": "application/vnd.android.package-archive",
            "User-Agent": "alpecca-live-stack-observer/1",
        },
    )
    started = time.perf_counter()
    try:
        with opener(request, timeout) as response:  # type: ignore[attr-defined]
            status = _response_status(response)
            redirected = _response_url(response) != url
            content_type = _header(response, "Content-Type").split(";", 1)[0].strip().lower()
            content_length_raw = _header(response, "Content-Length")
            etag = _header(response, "ETag")
            last_modified = _header(response, "Last-Modified")
    except urllib.error.HTTPError as exc:
        return {"status": "fail", "http_status": int(exc.code), "error": "http_status"}
    except Exception as exc:
        return {"status": "fail", "error": type(exc).__name__}
    try:
        content_length = int(content_length_raw)
    except (TypeError, ValueError):
        content_length = -1
    etag_valid = 0 < len(etag) <= 256 and all(32 <= ord(char) < 127 for char in etag)
    valid = (
        status == 200
        and not redirected
        and content_type == "application/vnd.android.package-archive"
        and content_length == REVIEWED_APK_BYTES
        and etag_valid
    )
    return {
        "status": "pass" if valid else "fail",
        "http_status": status,
        "redirected": redirected,
        "artifact_version": REVIEWED_APK_VERSION,
        "content_type_match": content_type == "application/vnd.android.package-archive",
        "content_length": content_length,
        "reviewed_content_length": REVIEWED_APK_BYTES,
        "etag_present": etag_valid,
        "last_modified_present": bool(last_modified),
        "body_read": False,
        "latency_ms": round((time.perf_counter() - started) * 1_000.0, 3),
    }


def _parse_timestamp(value: object) -> float | None:
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.timestamp()


def _load_capture(path: Path | None, now: float, max_age: float) -> dict[str, object]:
    if path is None:
        return {"status": "missing"}
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_CAPTURE_BYTES:
            return {"status": "invalid", "error": "file_policy"}
        raw = path.read_bytes()
    except OSError as exc:
        return {"status": "invalid", "error": type(exc).__name__}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        return {"status": "invalid", "error": "invalid_json"}
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema", "observed_at", "coremind", "brain_garden", "discord_bridge"
    }:
        return {"status": "invalid", "error": "invalid_fields"}
    if payload.get("schema") != CAPTURE_SCHEMA:
        return {"status": "invalid", "error": "invalid_schema"}
    coremind = payload.get("coremind")
    brain = payload.get("brain_garden")
    discord = payload.get("discord_bridge")
    if (
        not isinstance(coremind, Mapping)
        or set(coremind) != {"count"}
        or type(coremind.get("count")) is not int
        or not 0 <= coremind["count"] <= 16
        or not isinstance(brain, Mapping)
        or set(brain) != {"authenticated_http_status", "response_body_observed"}
        or type(brain.get("authenticated_http_status")) is not int
        or not 100 <= brain["authenticated_http_status"] <= 599
        or type(brain.get("response_body_observed")) is not bool
        or not isinstance(discord, Mapping)
        or set(discord) != {"count", "control_ready"}
        or type(discord.get("count")) is not int
        or not 0 <= discord["count"] <= 16
        or type(discord.get("control_ready")) is not bool
    ):
        return {"status": "invalid", "error": "invalid_evidence_shape"}
    observed = _parse_timestamp(payload.get("observed_at"))
    if observed is None or observed > now + MAX_CLOCK_SKEW_SECONDS:
        return {"status": "invalid", "error": "invalid_observation_time"}
    age = max(0.0, now - observed)
    if age > max_age:
        return {"status": "stale", "age_seconds": round(age, 3)}
    return {
        "status": "fresh",
        "age_seconds": round(age, 3),
        "coremind_count": coremind["count"],
        "brain_http_status": brain["authenticated_http_status"],
        "brain_body_observed": brain["response_body_observed"],
        "discord_count": discord["count"],
        "discord_control_ready": discord["control_ready"],
    }


def _inspect_vrm(path: Path, expected_name: str) -> dict[str, object]:
    evidence: dict[str, object] = {
        "present": False,
        "regular_file": False,
        "expected_name": path.name == expected_name,
        "byte_length": None,
        "glb_version": None,
        "vrm_spec_version": None,
    }
    try:
        if not path.is_file() or path.is_symlink():
            return {"status": "fail", **evidence, "error": "missing_or_disallowed_file"}
        size = path.stat().st_size
        evidence.update({"present": True, "regular_file": True, "byte_length": size})
        if not 20 <= size <= MAX_VRM_BYTES:
            return {"status": "fail", **evidence, "error": "file_size_bound"}
        with path.open("rb") as handle:
            header = handle.read(20)
            if len(header) != 20:
                return {"status": "fail", **evidence, "error": "truncated_header"}
            magic, glb_version, declared_size, chunk_size, chunk_type = struct.unpack(
                "<IIIII", header
            )
            evidence["glb_version"] = glb_version
            if (
                magic != 0x46546C67
                or glb_version != 2
                or declared_size != size
                or chunk_type != 0x4E4F534A
                or not 1 <= chunk_size <= MAX_VRM_JSON_BYTES
                or chunk_size > size - 20
            ):
                return {"status": "fail", **evidence, "error": "invalid_glb_manifest"}
            raw = handle.read(chunk_size)
    except OSError as exc:
        return {"status": "fail", **evidence, "error": type(exc).__name__}
    try:
        document = json.loads(raw.rstrip(b" \t\r\n\x00").decode("utf-8"))
        spec_version = document["extensions"]["VRMC_vrm"]["specVersion"]
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError, RecursionError):
        return {"status": "fail", **evidence, "error": "invalid_vrm_manifest"}
    evidence["vrm_spec_version"] = spec_version if isinstance(spec_version, str) else None
    valid = evidence["expected_name"] and spec_version == REVIEWED_VRM_SPEC_VERSION
    return {"status": "pass" if valid else "fail", **evidence}


def _public_evidence(value: Mapping[str, object]) -> dict[str, object]:
    return {key: item for key, item in value.items() if not key.startswith("_") and key != "identity"}


class LiveStackCollector:
    """Collect one passive live-stack receipt without exercising behavior."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        open_request: Callable[[urllib.request.Request, float], object] = _default_open,
    ) -> None:
        self._clock = clock
        self._open = open_request

    def collect(self, config: LiveStackConfig) -> dict[str, object]:
        now = float(self._clock())
        capture = _load_capture(
            config.observer_capture_path, now, float(config.capture_max_age_seconds)
        )
        if config.network_enabled:
            local = _identity_probe(
                config.local_health_url, float(config.timeout_seconds), self._open
            )
            boundary = _brain_boundary_probe(
                config.brain_garden_url, float(config.timeout_seconds), self._open
            )
            f5 = _f5_probe(config.f5_health_url, float(config.timeout_seconds), self._open)
            discovery = _discovery_probe(
                config.discovery_url, float(config.timeout_seconds), now, self._open
            )
            if discovery.get("status") == "pass":
                selected_url = str(discovery["_selected_url"])
                relay = _identity_probe(
                    selected_url + "/healthz",
                    float(config.timeout_seconds),
                    self._open,
                    localtunnel_bypass=(urlsplit(selected_url).hostname or "").endswith(".loca.lt"),
                )
            else:
                relay = {"status": "unknown", "error": "no_valid_discovery_candidate"}
            apk = _apk_probe(config.apk_url, float(config.timeout_seconds), self._open)
        else:
            local = boundary = f5 = discovery = relay = apk = {
                "status": "unknown", "configured": False
            }

        checks: list[dict[str, object]] = []
        capture_status = str(capture.get("status"))
        capture_meta = {
            "capture_status": capture_status,
            "capture_age_seconds": capture.get("age_seconds"),
        }

        if local.get("status") == "fail":
            local_status = "fail"
        elif capture_status != "fresh":
            local_status = "unknown"
        elif capture.get("coremind_count") != 1:
            local_status = "fail"
        else:
            local_status = "pass"
        local_unknowns = () if local_status != "unknown" else ("exact_process_count_not_observed",)
        checks.append(_check(
            CHECK_IDS[0],
            local_status,
            "Exact sparse local identity and a single CoreMind require independent fresh evidence.",
            {
                **_public_evidence(local),
                **capture_meta,
                "coremind_count": capture.get("coremind_count"),
                "identity_match": local.get("status") == "pass",
            },
            local_unknowns,
        ))

        boundary_ok = boundary.get("status") == "pass"
        authenticated_ok = (
            capture_status == "fresh"
            and capture.get("brain_http_status") == 200
            and capture.get("brain_body_observed") is False
        )
        if not boundary_ok:
            brain_status = "fail" if boundary.get("status") == "fail" else "unknown"
        elif capture_status != "fresh":
            brain_status = "unknown"
        else:
            brain_status = "pass" if authenticated_ok else "fail"
        checks.append(_check(
            CHECK_IDS[1],
            brain_status,
            "Protection and authenticated availability are recorded without retaining a graph payload.",
            {
                **_public_evidence(boundary),
                **capture_meta,
                "authenticated_http_status": capture.get("brain_http_status"),
                "authenticated_body_observed": capture.get("brain_body_observed"),
            },
            () if brain_status != "unknown" else ("authenticated_brain_garden_availability_not_observed",),
        ))

        if capture_status != "fresh":
            discord_status = "unknown"
        elif capture.get("discord_count") == 1 and capture.get("discord_control_ready") is True:
            discord_status = "pass"
        else:
            discord_status = "fail"
        checks.append(_check(
            CHECK_IDS[2],
            discord_status,
            "Discord bridge control readiness is accepted only from a fresh content-free observer capture.",
            {
                **capture_meta,
                "bridge_count": capture.get("discord_count"),
                "control_ready": capture.get("discord_control_ready"),
            },
            () if discord_status != "unknown" else ("discord_control_readiness_not_observed",),
        ))

        checks.append(_check(
            CHECK_IDS[3],
            str(f5.get("status")),
            "F5 readiness is observed through its read-only local health contract.",
            _public_evidence(f5),
            () if f5.get("status") != "unknown" else ("f5_readiness_not_observed",),
        ))

        identities_match = (
            local.get("status") == "pass"
            and relay.get("status") == "pass"
            and local.get("identity") == relay.get("identity")
        )
        if local.get("status") == "unknown" or relay.get("status") == "unknown":
            relay_status = "unknown"
        else:
            relay_status = "pass" if identities_match else "fail"
        checks.append(_check(
            CHECK_IDS[4],
            relay_status,
            "The selected public relay must return the same exact sparse identity as local health.",
            {
                "local_identity_match": local.get("status") == "pass",
                "relay_identity_match": relay.get("status") == "pass",
                "identities_equal": identities_match,
                "selected_origin_id": discovery.get("selected_origin_id"),
                **_public_evidence(relay),
            },
            () if relay_status != "unknown" else ("public_relay_identity_not_observed",),
        ))

        checks.append(_check(
            CHECK_IDS[5],
            str(discovery.get("status")),
            "The public discovery document must pass exact schema, expiry, and selection rules.",
            _public_evidence(discovery),
            () if discovery.get("status") != "unknown" else ("r2_discovery_not_observed",),
        ))

        checks.append(_check(
            CHECK_IDS[6],
            str(apk.get("status")),
            "The reviewed Android artifact is checked with HEAD metadata only.",
            _public_evidence(apk),
            ("apk_sha256_not_recomputed",),
        ))

        v4 = _inspect_vrm(config.v4_asset_path, REVIEWED_V4_NAME)
        promoted = _inspect_vrm(config.promoted_vrm_path, "alpecca.vrm")
        v4_status = "pass" if v4.get("status") == promoted.get("status") == "pass" else "fail"
        checks.append(_check(
            CHECK_IDS[7],
            v4_status,
            "The named V4 and promoted runtime body are parsed only through their bounded embedded manifests.",
            {
                "reviewed_v4": _public_evidence(v4),
                "promoted_runtime_vrm": _public_evidence(promoted),
                "required_vrm_spec_version": REVIEWED_VRM_SPEC_VERSION,
            },
            ("v4_visual_design_and_motion_not_observed",),
        ))

        counts = {status: sum(check["status"] == status for check in checks) for status in (
            "pass", "fail", "unknown"
        )}
        if counts["fail"]:
            assessment_status = "snapshot_checks_failed"
        elif counts["unknown"]:
            assessment_status = "snapshot_incomplete"
        else:
            assessment_status = "snapshot_observed"
        unknown_codes = [
            "single_snapshot_has_no_soak_duration_or_stability_evidence",
            "no_chat_model_call_or_response_content_observed",
            "no_speech_discord_post_or_message_delivery_exercised",
            "no_restart_failover_restore_or_process_control_exercised",
            "apk_sha256_not_recomputed",
            "v4_visual_design_motion_and_physics_not_observed",
        ]
        for check in checks:
            unknown_codes.extend(str(item) for item in check["unknowns"])
        unknowns = list(dict.fromkeys(unknown_codes))
        return {
            "schema": RECEIPT_SCHEMA,
            "observed_at": datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z"),
            "phase": {
                "id": "P14",
                "mode": "observation_only",
                "snapshot_count": 1,
                "completion_claim": False,
            },
            "policy": {
                "process_control": "none",
                "command_execution": "none",
                "credentials": "not accepted or loaded",
                "outbound_behavior": "none",
                "network_methods": ["GET", "HEAD"] if config.network_enabled else [],
                "response_content_retained": False,
                "maximum_network_requests": 6 if config.network_enabled else 0,
            },
            "checks": checks,
            "assessment": {
                "status": assessment_status,
                "counts": counts,
                "all_snapshot_checks_passed": counts == {"pass": len(CHECK_IDS), "fail": 0, "unknown": 0},
                "p14_completion_claim": False,
                "full_soak_complete": False,
            },
            "unknowns": unknowns,
        }


def render_receipt(receipt: Mapping[str, object], *, pretty: bool = True) -> str:
    return json.dumps(
        receipt,
        ensure_ascii=True,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
        sort_keys=True,
    ) + "\n"


__all__ = [
    "CAPTURE_SCHEMA",
    "CHECK_IDS",
    "DEFAULT_APK_URL",
    "DEFAULT_BRAIN_GARDEN_URL",
    "DEFAULT_DISCOVERY_URL",
    "DEFAULT_F5_HEALTH_URL",
    "DEFAULT_LOCAL_HEALTH_URL",
    "LiveStackCollector",
    "LiveStackConfig",
    "RECEIPT_SCHEMA",
    "REVIEWED_APK_BYTES",
    "REVIEWED_APK_VERSION",
    "REVIEWED_V4_NAME",
    "render_receipt",
]
