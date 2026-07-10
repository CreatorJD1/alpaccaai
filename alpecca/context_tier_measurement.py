"""Evidence-only local Ollama context-tier measurements.

This module deliberately does not read or change application settings, pagefile
configuration, model inventory, or files. A model request is possible only when
the caller explicitly passes ``execute=True``. That request is one direct,
loopback-only POST to Ollama's ``/api/generate`` endpoint.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, is_dataclass
from hashlib import sha256
import ipaddress
import inspect
import json
import math
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


ALLOWED_CONTEXT_TIERS: tuple[int, ...] = (8192, 16384, 24576, 32768, 49152)
LOCAL_QWEN_MODEL = "qwen3.5:9b"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
SMALL_OUTPUT_CAP_TOKENS = 32
DEFAULT_REQUEST_TIMEOUT_SECONDS = 180.0
_PROMPT_TOKEN_BUDGET_CAP = 12_288


class ContextTierValidationError(ValueError):
    """Raised before any request when a measurement is outside the safe scope."""


class HostResourceSampler:
    """Fallback seam while the project-level sampler is unavailable.

    The active Phase 6 sampler lives outside this file's ownership. The fallback
    makes missing telemetry explicit instead of inventing measurements. A later
    project-level ``alpecca.host_resources.HostResourceSampler`` is preferred at
    execution time.
    """

    def sample(self) -> dict[str, Any]:
        return {
            "available": False,
            "unknowns": [
                "Project HostResourceSampler is unavailable; host resources were not measured."
            ],
        }


def validate_context_tier(value: int | str) -> int:
    """Return one explicitly allowed context tier and reject all other values."""
    if isinstance(value, bool):
        raise ContextTierValidationError("context tier must be an exact integer")
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate or not candidate.isdecimal():
            raise ContextTierValidationError("context tier must be an exact integer")
        tier = int(candidate)
    elif isinstance(value, int):
        tier = value
    else:
        raise ContextTierValidationError("context tier must be an exact integer")
    if tier not in ALLOWED_CONTEXT_TIERS:
        allowed = ", ".join(str(item) for item in ALLOWED_CONTEXT_TIERS)
        raise ContextTierValidationError(f"unsupported context tier {tier}; allowed: {allowed}")
    return tier


def validate_local_model(model: str) -> str:
    """Restrict the harness to the approved local Qwen model."""
    candidate = str(model or "").strip()
    lowered = candidate.lower()
    if ":cloud" in lowered:
        raise ContextTierValidationError("cloud models are forbidden for context-tier measurement")
    if candidate != LOCAL_QWEN_MODEL:
        raise ContextTierValidationError(
            f"only the local model {LOCAL_QWEN_MODEL!r} is permitted"
        )
    return candidate


def validate_loopback_ollama_host(host: str) -> str:
    """Return a direct loopback HTTP Ollama base URL or reject it."""
    candidate = str(host or "").strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ContextTierValidationError("Ollama host has an invalid port") from exc
    if parsed.scheme.lower() != "http":
        raise ContextTierValidationError("Ollama host must use direct loopback HTTP")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ContextTierValidationError("Ollama host must not contain credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ContextTierValidationError("Ollama host must be a bare loopback base URL")
    if port is not None and not 0 < port < 65536:
        raise ContextTierValidationError("Ollama host has an invalid port")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost":
        hostname = "127.0.0.1"
    else:
        try:
            if not ipaddress.ip_address(hostname).is_loopback:
                raise ContextTierValidationError("nonloopback Ollama hosts are forbidden")
        except ValueError as exc:
            raise ContextTierValidationError("nonloopback Ollama hosts are forbidden") from exc
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    rendered_port = f":{port}" if port is not None else ""
    return f"http://{rendered_host}{rendered_port}"


def is_loopback_ollama_host(host: str) -> bool:
    """Return whether ``host`` passes the same direct-loopback validation."""
    try:
        validate_loopback_ollama_host(host)
    except ContextTierValidationError:
        return False
    return True


def marker_for_tier(tier: int | str) -> str:
    """Build a deterministic, non-private marker for a synthetic prompt."""
    return f"ALPECCA_CONTEXT_TIER_{validate_context_tier(tier)}_MARKER_7F3C8D19"


def planned_prompt_token_budget(tier: int | str) -> int:
    """Return a conservative, tokenizer-independent synthetic prompt budget."""
    validated = validate_context_tier(tier)
    return min(max(1024, validated // 4), _PROMPT_TOKEN_BUDGET_CAP)


def _synthetic_record_count(tier: int | str) -> int:
    # Each record is intentionally plain public text, roughly twelve word tokens.
    return max(64, math.ceil(planned_prompt_token_budget(tier) / 12))


def build_synthetic_needle_prompt(tier: int | str) -> str:
    """Create a deterministic public-data needle prompt for a single tier."""
    validated = validate_context_tier(tier)
    marker = marker_for_tier(validated)
    count = _synthetic_record_count(validated)
    midpoint = count // 2
    records: list[str] = []
    for index in range(count):
        if index == midpoint:
            records.append(f"synthetic-needle: {marker}")
        records.append(
            "synthetic-row "
            f"{index:05d}: cedar vector amber lattice public benchmark datum."
        )
    return "\n".join(
        [
            "This is a synthetic Alpecca context-tier benchmark.",
            "Every row is non-private public test data.",
            "Read the full payload. Return only the exact uppercase synthetic needle marker.",
            *records,
            "Return only the exact uppercase synthetic needle marker shown in the payload.",
        ]
    )


def synthetic_prompt_metadata(tier: int | str, prompt: str) -> dict[str, Any]:
    """Expose auditable prompt facts without writing the large prompt to stdout."""
    validated = validate_context_tier(tier)
    marker = marker_for_tier(validated)
    return {
        "synthetic_non_private": True,
        "marker": marker,
        "marker_occurrences_in_prompt": prompt.count(marker),
        "synthetic_filler_record_count": _synthetic_record_count(validated),
        "planned_prompt_token_budget": planned_prompt_token_budget(validated),
        "planned_token_budget_is_not_tokenizer_measurement": True,
        "prompt_characters": len(prompt),
        "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
    }


def build_ollama_payload(*, model: str, tier: int, prompt: str) -> dict[str, Any]:
    """Build the only allowed request payload for this harness."""
    return {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "num_ctx": tier,
            "num_predict": SMALL_OUTPUT_CAP_TOKENS,
        },
    }


class _NoRedirectHandler(HTTPRedirectHandler):
    """Treat redirects as the original request's error, never as a new request."""

    def http_error_30x(self, request, response, code, message, headers):
        raise HTTPError(request.full_url, code, "redirects are forbidden", headers, response)

    http_error_301 = http_error_302 = http_error_303 = http_error_307 = http_error_308 = (
        http_error_30x
    )


def post_ollama_generate(
    host: str, payload: Mapping[str, Any], timeout_seconds: float
) -> dict[str, Any]:
    """Make exactly one direct HTTP POST and return Ollama's JSON response.

    Proxy handling is disabled so a loopback URL cannot be redirected through a
    configured remote HTTP proxy. This function performs no retry, preflight, or
    model inventory request.
    """
    endpoint = f"{host.rstrip('/')}/api/generate"
    body = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            status = int(response.getcode())
            raw = response.read()
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read()
    except URLError as exc:
        raise RuntimeError(f"Ollama HTTP request failed: {exc.reason}") from exc

    try:
        decoded = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "_http_status": status,
            "_response_parse_error": type(exc).__name__,
            "_response_body_characters": len(raw),
        }
    if not isinstance(decoded, dict):
        return {
            "_http_status": status,
            "_response_parse_error": "response was not a JSON object",
        }
    decoded["_http_status"] = status
    return decoded


def _json_safe(value: Any) -> Any:
    """Convert injected sampler values to JSON-compatible evidence."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _json_safe(to_dict())
        except Exception:
            pass
    return str(value)


def _sampler_method(sampler: Any) -> tuple[Callable[..., Any], bool] | None:
    snapshot = getattr(sampler, "snapshot", None)
    if callable(snapshot):
        try:
            parameters = inspect.signature(snapshot).parameters.values()
            supports_force = any(
                parameter.name == "force"
                or parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
        except (TypeError, ValueError):
            supports_force = False
        return snapshot, supports_force
    for name in ("sample", "collect"):
        candidate = getattr(sampler, name, None)
        if callable(candidate):
            return candidate, False
    return (sampler, False) if callable(sampler) else None


def _capture_sample(
    sampler: Any, phase: str, wall_clock: Callable[[], float]
) -> tuple[dict[str, Any], list[str]]:
    evidence: dict[str, Any] = {
        "phase": phase,
        "captured_at_unix_s": round(float(wall_clock()), 3),
        "collected": False,
        "data": None,
    }
    selected = _sampler_method(sampler)
    if selected is None:
        return evidence, [f"{phase} resource sample unavailable: sampler has no sample method."]
    method, supports_force = selected
    evidence["force_refresh_requested"] = supports_force
    try:
        data = _json_safe(method(force=True) if supports_force else method())
    except Exception as exc:
        return evidence, [f"{phase} resource sample failed: {type(exc).__name__}."]
    evidence["collected"] = True
    evidence["data"] = data
    unknowns: list[str] = []
    if data is None:
        unknowns.append(f"{phase} resource sampler returned no snapshot.")
    if isinstance(data, dict):
        declared = data.get("unknowns")
        if isinstance(declared, list):
            unknowns.extend(f"{phase} resource sample: {item}" for item in declared)
        reasons = data.get("unknown_reasons")
        if isinstance(reasons, Mapping):
            unknowns.extend(
                f"{phase} resource sample: {name} is unknown ({reason})."
                for name, reason in reasons.items()
            )
        assessment = data.get("assessment")
        if isinstance(assessment, Mapping):
            unavailable = assessment.get("unknown_resources")
            if isinstance(unavailable, list):
                unknowns.extend(
                    f"{phase} resource sample: {name} is unknown."
                    for name in unavailable
                )
    return evidence, unknowns


def _default_sampler() -> tuple[Any, str, list[str]]:
    """Use the read-only project sampler, or preserve an explicit unknown state."""
    try:
        from alpecca.host_resources import HostResourceSampler as ProjectHostResourceSampler
    except (ImportError, AttributeError):
        ProjectHostResourceSampler = None
    if ProjectHostResourceSampler is not None:
        try:
            return ProjectHostResourceSampler(), "project:alpecca.host_resources", []
        except Exception as exc:
            return HostResourceSampler(), "fallback", [
                "Project HostResourceSampler could not be initialized: "
                f"{type(exc).__name__}."
            ]

    return HostResourceSampler(), "fallback", [
        "Project HostResourceSampler is not available in this checkout."
    ]


def _resolve_sampler(
    sampler: Any | None, sampler_factory: Callable[[], Any] | None
) -> tuple[Any, str, list[str]]:
    if sampler is not None:
        return sampler, "injected", []
    if sampler_factory is not None:
        try:
            return sampler_factory(), "injected_factory", []
        except Exception as exc:
            return HostResourceSampler(), "fallback", [
                f"Injected resource sampler factory failed: {type(exc).__name__}."
            ]
    return _default_sampler()


def _positive_duration_ms(started: float | None, finished: float | None) -> float | None:
    if started is None or finished is None:
        return None
    return round(max(0.0, (finished - started) * 1000.0), 3)


def _ollama_duration_ms(response: Mapping[str, Any], field: str) -> float | None:
    value = response.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or value < 0:
        return None
    return round(float(value) / 1_000_000.0, 3)


def _ollama_count(response: Mapping[str, Any], field: str) -> int | None:
    value = response.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _extract_response(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    response = dict(result)
    body = response.get("body")
    if isinstance(body, Mapping):
        unpacked = dict(body)
        if "http_status" in response:
            unpacked["_http_status"] = response["http_status"]
        return unpacked
    return response


def _empty_report(
    *,
    tier: int,
    model: str,
    host: str,
    prompt: str,
    execute: bool,
) -> dict[str, Any]:
    metadata = synthetic_prompt_metadata(tier, prompt)
    return {
        "schema_version": 1,
        "kind": "alpecca_context_tier_measurement",
        "status": "pending" if execute else "dry_run",
        "mode": "execute" if execute else "dry_run",
        "tier": tier,
        "allowed_tiers": list(ALLOWED_CONTEXT_TIERS),
        "model": model,
        "ollama_host": host,
        "automatic_promotion": False,
        "system_settings_mutated": False,
        "pagefile_mutated": False,
        "manual_review_only": True,
        "manual_review": {
            "required": True,
            "decision": "manual_review_only",
            "reason": "The harness records evidence and never promotes a context tier.",
        },
        "request": {
            "allowed": execute,
            "attempted": False,
            "method": "POST",
            "endpoint": f"{host}/api/generate",
            "http_request_count": 0,
            "http_request_count_limit": 1,
            "stream": False,
            "think": False,
            "options": {
                "num_ctx": tier,
                "num_predict": SMALL_OUTPUT_CAP_TOKENS,
            },
        },
        "side_effects": {
            "downloads_requested": False,
            "files_written": False,
            "system_settings_mutated": False,
            "pagefile_mutated": False,
        },
        "prompt": metadata,
        "marker_verification": {
            "marker": metadata["marker"],
            "checked": False,
            "response_contains_marker": None,
            "verified": None,
        },
        "durations_ms": {
            "request_wall": None,
            "ollama_total": None,
            "ollama_load": None,
            "ollama_prompt_eval": None,
            "ollama_eval": None,
        },
        "tokens": {
            "requested_context": tier,
            "planned_prompt_budget": metadata["planned_prompt_token_budget"],
            "output_cap": SMALL_OUTPUT_CAP_TOKENS,
            "prompt_eval_count": None,
            "eval_count": None,
            "prompt_context_fill_ratio": None,
        },
        "resources": {
            "sampler_source": "not_started",
            "before": None,
            "during": None,
            "after": None,
        },
        "unknowns": [],
    }


def rejected_measurement_report(
    error: str,
    *,
    tier: int | str | None = None,
    model: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe rejection report without issuing a request."""
    accepted_tier = tier if isinstance(tier, int) and tier in ALLOWED_CONTEXT_TIERS else None
    safe_model = model if model == LOCAL_QWEN_MODEL else None
    safe_host = host if host and is_loopback_ollama_host(host) else None
    return {
        "schema_version": 1,
        "kind": "alpecca_context_tier_measurement",
        "status": "rejected",
        "mode": "dry_run",
        "tier": accepted_tier,
        "allowed_tiers": list(ALLOWED_CONTEXT_TIERS),
        "model": safe_model,
        "ollama_host": safe_host,
        "automatic_promotion": False,
        "system_settings_mutated": False,
        "pagefile_mutated": False,
        "manual_review_only": True,
        "manual_review": {
            "required": True,
            "decision": "manual_review_only",
            "reason": "Rejected requests require manual correction; no execution occurred.",
        },
        "request": {
            "allowed": False,
            "attempted": False,
            "method": "POST",
            "endpoint": None,
            "http_request_count": 0,
            "http_request_count_limit": 1,
            "stream": False,
            "think": False,
            "options": {"num_ctx": accepted_tier, "num_predict": SMALL_OUTPUT_CAP_TOKENS},
        },
        "side_effects": {
            "downloads_requested": False,
            "files_written": False,
            "system_settings_mutated": False,
            "pagefile_mutated": False,
        },
        "prompt": None,
        "marker_verification": {
            "marker": None,
            "checked": False,
            "response_contains_marker": None,
            "verified": None,
        },
        "durations_ms": {
            "request_wall": None,
            "ollama_total": None,
            "ollama_load": None,
            "ollama_prompt_eval": None,
            "ollama_eval": None,
        },
        "tokens": {
            "requested_context": accepted_tier,
            "planned_prompt_budget": None,
            "output_cap": SMALL_OUTPUT_CAP_TOKENS,
            "prompt_eval_count": None,
            "eval_count": None,
            "prompt_context_fill_ratio": None,
        },
        "resources": {
            "sampler_source": "not_started",
            "before": None,
            "during": None,
            "after": None,
        },
        "unknowns": [str(error)],
    }


def _append_unknowns(report: dict[str, Any], values: list[str]) -> None:
    known = report["unknowns"]
    for value in values:
        if value and value not in known:
            known.append(value)


def run_context_tier_measurement(
    *,
    tier: int | str,
    execute: bool = False,
    host: str = DEFAULT_OLLAMA_HOST,
    model: str = LOCAL_QWEN_MODEL,
    sampler: Any | None = None,
    sampler_factory: Callable[[], Any] | None = None,
    request_fn: Callable[[str, Mapping[str, Any], float], Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Measure one validated tier, or return a side-effect-free dry-run report.

    ``sampler``, ``sampler_factory``, ``request_fn``, and clocks are injectable so
    tests can verify the evidence contract without a model or host dependency.
    """
    validated_tier = validate_context_tier(tier)
    validated_model = validate_local_model(model)
    validated_host = validate_loopback_ollama_host(host)
    timeout = float(request_timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ContextTierValidationError("request timeout must be a positive finite number")

    prompt = build_synthetic_needle_prompt(validated_tier)
    report = _empty_report(
        tier=validated_tier,
        model=validated_model,
        host=validated_host,
        prompt=prompt,
        execute=bool(execute),
    )
    if not execute:
        _append_unknowns(
            report,
            [
                "Dry run: no Ollama request was made.",
                "Dry run: before, during, and after host-resource samples were not collected.",
                "Dry run: marker verification and Ollama duration/token telemetry are unavailable.",
            ],
        )
        return report

    sampler_instance, sampler_source, sampler_unknowns = _resolve_sampler(
        sampler, sampler_factory
    )
    report["resources"]["sampler_source"] = sampler_source
    _append_unknowns(report, sampler_unknowns)

    before, unknowns = _capture_sample(sampler_instance, "before", wall_clock)
    report["resources"]["before"] = before
    _append_unknowns(report, unknowns)

    payload = build_ollama_payload(
        model=validated_model, tier=validated_tier, prompt=prompt
    )
    invoke = request_fn or post_ollama_generate
    started = threading.Event()
    completed = threading.Event()
    state: dict[str, Any] = {
        "request_count": 0,
        "started_at": None,
        "finished_at": None,
        "response": None,
        "error": None,
    }

    def invoke_once() -> None:
        state["started_at"] = clock()
        state["request_count"] = 1
        started.set()
        try:
            state["response"] = invoke(validated_host, payload, timeout)
        except Exception as exc:
            state["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            state["finished_at"] = clock()
            completed.set()

    worker = threading.Thread(target=invoke_once, name="context-tier-ollama", daemon=False)
    try:
        worker.start()
    except RuntimeError as exc:
        state["error"] = f"RuntimeError: {exc}"
        completed.set()

    started.wait(timeout=min(1.0, timeout))
    in_flight = started.is_set() and not completed.is_set()
    during, unknowns = _capture_sample(sampler_instance, "during", wall_clock)
    during["request_in_flight"] = in_flight
    report["resources"]["during"] = during
    _append_unknowns(report, unknowns)
    if not in_flight:
        _append_unknowns(
            report,
            ["During resource sample was not observed while the request was in flight."],
        )

    if started.is_set():
        worker.join()
    after, unknowns = _capture_sample(sampler_instance, "after", wall_clock)
    report["resources"]["after"] = after
    _append_unknowns(report, unknowns)

    report["request"]["attempted"] = bool(started.is_set())
    report["request"]["http_request_count"] = int(state["request_count"])
    report["durations_ms"]["request_wall"] = _positive_duration_ms(
        state["started_at"], state["finished_at"]
    )

    if state["error"]:
        report["status"] = "failed"
        _append_unknowns(report, [f"Ollama request did not complete: {state['error']}"])
        return report
    if state["request_count"] != 1:
        report["status"] = "failed"
        _append_unknowns(report, ["Execution did not make exactly one Ollama HTTP request."])
        return report

    response = _extract_response(state["response"])
    http_status = response.get("_http_status")
    http_failed = isinstance(http_status, int) and not 200 <= http_status < 300
    model_failed = "error" in response
    response_parse_failed = "_response_parse_error" in response
    if http_failed:
        _append_unknowns(report, [f"Ollama returned HTTP status {http_status}."])
    if model_failed:
        _append_unknowns(report, ["Ollama returned an error response."])
    if response_parse_failed:
        _append_unknowns(report, ["Ollama response could not be parsed as a JSON object."])

    response_text = response.get("response")
    if isinstance(response_text, str):
        marker = report["marker_verification"]["marker"]
        contains_marker = marker in response_text
        report["marker_verification"] = {
            "marker": marker,
            "checked": True,
            "response_contains_marker": contains_marker,
            "verified": contains_marker,
            "response_characters": len(response_text),
            "response_excerpt": response_text[:512],
        }
        if not contains_marker:
            _append_unknowns(report, ["Model response did not verify the synthetic needle marker."])
    else:
        _append_unknowns(report, ["Ollama response text was unavailable for marker verification."])

    prompt_eval_count = _ollama_count(response, "prompt_eval_count")
    eval_count = _ollama_count(response, "eval_count")
    report["tokens"]["prompt_eval_count"] = prompt_eval_count
    report["tokens"]["eval_count"] = eval_count
    if prompt_eval_count is not None:
        report["tokens"]["prompt_context_fill_ratio"] = round(
            prompt_eval_count / validated_tier, 6
        )
    else:
        _append_unknowns(report, ["Ollama did not report prompt_eval_count."])
    if eval_count is None:
        _append_unknowns(report, ["Ollama did not report eval_count."])

    report["durations_ms"]["ollama_total"] = _ollama_duration_ms(
        response, "total_duration"
    )
    report["durations_ms"]["ollama_load"] = _ollama_duration_ms(
        response, "load_duration"
    )
    report["durations_ms"]["ollama_prompt_eval"] = _ollama_duration_ms(
        response, "prompt_eval_duration"
    )
    report["durations_ms"]["ollama_eval"] = _ollama_duration_ms(
        response, "eval_duration"
    )
    report["status"] = "failed" if (http_failed or model_failed or response_parse_failed) else "completed"
    return report
