"""Bounded, content-free evidence probe for Alpecca's 8,192-token context.

The CLI writes one JSON receipt to stdout and never writes files. Execution is
explicit, local-only, observation-only, and limited to one synthetic Ollama
request after the existing Phase 6 host-resource preflight permits it.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any


sys.dont_write_bytecode = True
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from alpecca.context_tier_measurement import (  # noqa: E402
    DEFAULT_OLLAMA_HOST,
    LOCAL_QWEN_MODEL,
    ContextTierValidationError,
    build_synthetic_needle_prompt,
    evaluate_execution_preflight,
    marker_for_tier,
    post_ollama_generate,
    validate_loopback_ollama_host,
)
from alpecca.host_resources import HostResourceSampler  # noqa: E402


RECEIPT_SCHEMA = "alpecca.phase6.context-8192.observation-receipt"
RECEIPT_SCHEMA_VERSION = 1
CONTEXT_TOKENS = 8192
OUTPUT_TOKEN_CAP = 32
MAX_HTTP_REQUESTS = 1
MAX_WALL_TIME_SECONDS = 120.0
REQUEST_TIMEOUT_SECONDS = 90.0
RESOURCE_SAMPLE_TIMEOUT_SECONDS = 4.0

_SAFE_SEVERITIES = frozenset({"normal", "elevated", "high", "critical"})
_SAFE_HTTP_CLASSES = frozenset({"2xx", "3xx", "4xx", "5xx", "unknown"})
_FORBIDDEN_RECEIPT_KEYS = frozenset(
    {
        "prompt",
        "response",
        "response_excerpt",
        "host",
        "ollama_host",
        "endpoint",
        "environment",
        "path",
        "process",
        "command",
        "error_message",
    }
)


def _finite_number(value: Any, *, minimum: float = 0.0, maximum: float | None = None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _headroom(snapshot: Mapping[str, Any], resource: str) -> dict[str, Any]:
    headroom = _mapping(snapshot.get("headroom"))
    nested = _mapping(headroom.get(resource))
    bytes_value = nested.get("bytes", headroom.get(f"{resource}_bytes"))
    fraction = nested.get("fraction", headroom.get(f"{resource}_fraction"))
    return {
        "bytes": _integer(bytes_value),
        "fraction": _finite_number(fraction, maximum=1.0),
    }


def _resource_summary(snapshot: Any) -> dict[str, Any]:
    """Select numeric/coarse telemetry only; never retain a raw host snapshot."""
    if not isinstance(snapshot, Mapping):
        return {
            "available": False,
            "assessment_severity": None,
            "overall_pressure": None,
            "cpu_percent": None,
            "headroom": {
                name: {"bytes": None, "fraction": None}
                for name in ("ram", "commit", "disk")
            },
            "vram": {"used_bytes": None, "total_bytes": None},
        }
    raw = _mapping(snapshot.get("raw"))
    assessment = _mapping(snapshot.get("assessment"))
    severity = assessment.get("severity")
    if not isinstance(severity, str) or severity not in _SAFE_SEVERITIES:
        severity = None
    return {
        "available": True,
        "assessment_severity": severity,
        "overall_pressure": _finite_number(
            assessment.get("overall_pressure"), maximum=1.0
        ),
        "cpu_percent": _finite_number(raw.get("cpu_percent"), maximum=100.0),
        "headroom": {
            name: _headroom(snapshot, name) for name in ("ram", "commit", "disk")
        },
        "vram": {
            "used_bytes": _integer(raw.get("vram_used_bytes")),
            "total_bytes": _integer(raw.get("vram_total_bytes")),
        },
    }


def _capture_sample(sampler: Any, timeout_seconds: float) -> tuple[Any, str | None]:
    """Bound one read-only sampler call without retaining exception text."""
    state: dict[str, Any] = {"value": None, "error": False}
    finished = threading.Event()

    def collect() -> None:
        try:
            method = getattr(sampler, "snapshot", None)
            if callable(method):
                state["value"] = method(force=True)
            else:
                method = getattr(sampler, "sample", None)
                if not callable(method):
                    state["error"] = True
                else:
                    state["value"] = method()
        except Exception:
            state["error"] = True
        finally:
            finished.set()

    worker = threading.Thread(target=collect, name="p6-resource-sample", daemon=True)
    worker.start()
    if not finished.wait(timeout=max(0.001, timeout_seconds)):
        return None, "resource_sample_timeout"
    if state["error"]:
        return None, "resource_sample_error"
    if not isinstance(state["value"], Mapping):
        return None, "resource_sample_unavailable"
    return state["value"], None


def _preflight_receipt(preflight: Mapping[str, Any]) -> dict[str, Any]:
    reasons = preflight.get("reasons")
    reason_codes = []
    if isinstance(reasons, list):
        for reason in reasons:
            code = reason.get("code") if isinstance(reason, Mapping) else None
            if isinstance(code, str) and code:
                reason_codes.append(code)
    unknowns = preflight.get("unknowns")
    return {
        "status": preflight.get("status")
        if preflight.get("status") in {"not_run", "passed", "blocked"}
        else "unknown",
        "request_permitted": bool(preflight.get("request_permitted")),
        "evidence_state": preflight.get("evidence_state")
        if preflight.get("evidence_state") in {"observed", "partial", "unknown"}
        else "unknown",
        "reason_codes": sorted(set(reason_codes)),
        "unknown_count": len(unknowns) if isinstance(unknowns, list) else 0,
    }


def _base_receipt(*, execute: bool, prompt: str) -> dict[str, Any]:
    return {
        "schema": RECEIPT_SCHEMA,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "pending" if execute else "dry_run",
        "reason_codes": [],
        "observation_only": True,
        "manual_review_required": True,
        "target": {
            "model": LOCAL_QWEN_MODEL,
            "context_tokens": CONTEXT_TOKENS,
            "output_token_cap": OUTPUT_TOKEN_CAP,
            "stream": False,
            "think": False,
            "loopback_only": True,
        },
        "bounds": {
            "http_request_limit": MAX_HTTP_REQUESTS,
            "wall_time_limit_ms": int(MAX_WALL_TIME_SECONDS * 1000),
            "request_timeout_ms": int(REQUEST_TIMEOUT_SECONDS * 1000),
            "resource_sample_timeout_ms": int(RESOURCE_SAMPLE_TIMEOUT_SECONDS * 1000),
        },
        "execution": {
            "requested": bool(execute),
            "request_attempted": False,
            "http_request_count": 0,
            "wall_time_ms": 0.0,
        },
        "synthetic_input": {
            "content_class": "deterministic_synthetic",
            "contains_user_content": False,
            "contains_secret_content": False,
            "characters": len(prompt),
            "sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        },
        "preflight": {
            "status": "not_run",
            "request_permitted": False,
            "evidence_state": "unknown",
            "reason_codes": [],
            "unknown_count": 0,
        },
        "resources": {
            "before": _resource_summary(None),
            "during": _resource_summary(None),
            "after": _resource_summary(None),
        },
        "result": {
            "http_status_class": "unknown",
            "marker_checked": False,
            "marker_verified": None,
            "response_characters": None,
            "prompt_eval_count": None,
            "generated_token_count": None,
            "context_fill_ratio": None,
            "ollama_total_ms": None,
            "ollama_load_ms": None,
            "ollama_prompt_eval_ms": None,
            "ollama_generate_ms": None,
        },
        "side_effects": {
            "files_written": False,
            "configuration_changed": False,
            "pagefile_changed": False,
            "system_settings_changed": False,
            "model_downloaded": False,
            "stack_processes_changed": False,
            "automatic_promotion": False,
        },
    }


def _duration_ms(response: Mapping[str, Any], key: str) -> float | None:
    value = _finite_number(response.get(key))
    return round(value / 1_000_000.0, 3) if value is not None else None


def _http_status_class(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        return "unknown"
    result = f"{value // 100}xx"
    return result if result in _SAFE_HTTP_CLASSES else "unknown"


def _add_reason(receipt: dict[str, Any], code: str) -> None:
    if code not in receipt["reason_codes"]:
        receipt["reason_codes"].append(code)


def _finish(receipt: dict[str, Any], started_at: float, monotonic: Callable[[], float]):
    receipt["reason_codes"].sort()
    receipt["execution"]["wall_time_ms"] = round(
        max(0.0, monotonic() - started_at) * 1000.0, 3
    )
    validate_content_free_receipt(receipt)
    return receipt


def validate_content_free_receipt(receipt: Mapping[str, Any]) -> None:
    """Reject schema drift that could accidentally retain content or identifiers."""
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("unexpected receipt schema")

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key).lower() in _FORBIDDEN_RECEIPT_KEYS:
                    raise ValueError("receipt contains a forbidden content-bearing field")
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
        elif value is not None and not isinstance(value, (str, bool, int, float)):
            raise ValueError("receipt contains a non-JSON value")

    visit(receipt)


def run_probe(
    *,
    execute: bool = False,
    configured_model: str | None = None,
    configured_host: str | None = None,
    sampler: Any | None = None,
    request_fn: Callable[[str, Mapping[str, Any], float], Any] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    wall_time_limit_seconds: float = MAX_WALL_TIME_SECONDS,
    request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
    resource_sample_timeout_seconds: float = RESOURCE_SAMPLE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Return one content-free receipt for a dry run or one bounded real probe."""
    started_at = monotonic()
    prompt = build_synthetic_needle_prompt(CONTEXT_TOKENS)
    receipt = _base_receipt(execute=execute, prompt=prompt)
    wall_limit = min(MAX_WALL_TIME_SECONDS, max(0.001, wall_time_limit_seconds))
    request_timeout = min(REQUEST_TIMEOUT_SECONDS, max(0.001, request_timeout_seconds))
    sample_timeout = min(
        RESOURCE_SAMPLE_TIMEOUT_SECONDS, max(0.001, resource_sample_timeout_seconds)
    )
    receipt["bounds"]["wall_time_limit_ms"] = int(wall_limit * 1000)
    receipt["bounds"]["request_timeout_ms"] = int(request_timeout * 1000)
    receipt["bounds"]["resource_sample_timeout_ms"] = int(sample_timeout * 1000)

    if not execute:
        _add_reason(receipt, "execution_not_requested")
        return _finish(receipt, started_at, monotonic)

    model = configured_model
    if model is None:
        model = os.environ.get("ALPECCA_MODEL", LOCAL_QWEN_MODEL)
    if model != LOCAL_QWEN_MODEL:
        receipt["status"] = "blocked"
        _add_reason(receipt, "configured_model_mismatch")
        return _finish(receipt, started_at, monotonic)

    host = configured_host
    if host is None:
        host = os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST)
    try:
        host = validate_loopback_ollama_host(host)
    except ContextTierValidationError:
        receipt["status"] = "blocked"
        _add_reason(receipt, "ollama_host_not_direct_loopback")
        return _finish(receipt, started_at, monotonic)

    if sampler is None:
        try:
            sampler = HostResourceSampler()
        except Exception:
            receipt["status"] = "blocked"
            _add_reason(receipt, "resource_sampler_initialization_failed")
            return _finish(receipt, started_at, monotonic)

        _, warmup_error = _capture_sample(sampler, sample_timeout)
        if warmup_error == "resource_sample_timeout":
            receipt["status"] = "blocked"
            _add_reason(receipt, "resource_warmup_timeout")
            return _finish(receipt, started_at, monotonic)

    before, before_error = _capture_sample(sampler, sample_timeout)
    receipt["resources"]["before"] = _resource_summary(before)
    preflight = evaluate_execution_preflight(
        before,
        sample_unknowns=([before_error] if before_error else []),
    )
    receipt["preflight"] = _preflight_receipt(preflight)
    if before_error:
        _add_reason(receipt, before_error)
    for code in receipt["preflight"]["reason_codes"]:
        _add_reason(receipt, code)
    if not preflight.get("request_permitted"):
        receipt["status"] = "blocked"
        return _finish(receipt, started_at, monotonic)

    elapsed = max(0.0, monotonic() - started_at)
    remaining = wall_limit - elapsed
    if remaining <= 0:
        receipt["status"] = "timed_out"
        _add_reason(receipt, "wall_time_exhausted_before_request")
        return _finish(receipt, started_at, monotonic)

    payload = {
        "model": LOCAL_QWEN_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"num_ctx": CONTEXT_TOKENS, "num_predict": OUTPUT_TOKEN_CAP},
    }
    invoke = request_fn or post_ollama_generate
    state: dict[str, Any] = {"response": None, "failed": False}
    completed = threading.Event()

    def request_once() -> None:
        try:
            state["response"] = invoke(host, payload, min(request_timeout, remaining))
        except Exception:
            state["failed"] = True
        finally:
            completed.set()

    worker = threading.Thread(target=request_once, name="p6-context-8192", daemon=True)
    receipt["execution"]["request_attempted"] = True
    receipt["execution"]["http_request_count"] = 1
    worker.start()

    during, during_error = _capture_sample(
        sampler, min(sample_timeout, max(0.001, wall_limit - (monotonic() - started_at)))
    )
    receipt["resources"]["during"] = _resource_summary(during)
    if during_error:
        _add_reason(receipt, f"during_{during_error}")

    wait_remaining = max(0.0, wall_limit - (monotonic() - started_at))
    if not completed.wait(wait_remaining):
        receipt["status"] = "timed_out"
        _add_reason(receipt, "wall_time_limit_reached")
        return _finish(receipt, started_at, monotonic)

    after, after_error = _capture_sample(
        sampler, min(sample_timeout, max(0.001, wall_limit - (monotonic() - started_at)))
    )
    receipt["resources"]["after"] = _resource_summary(after)
    if after_error:
        _add_reason(receipt, f"after_{after_error}")

    if state["failed"] or not isinstance(state["response"], Mapping):
        receipt["status"] = "failed"
        _add_reason(receipt, "ollama_request_failed")
        return _finish(receipt, started_at, monotonic)

    response = state["response"]
    http_status = response.get("_http_status")
    receipt["result"]["http_status_class"] = _http_status_class(http_status)
    response_text = response.get("response")
    marker = marker_for_tier(CONTEXT_TOKENS)
    if isinstance(response_text, str):
        receipt["result"]["marker_checked"] = True
        receipt["result"]["marker_verified"] = marker in response_text
        receipt["result"]["response_characters"] = len(response_text)
    prompt_eval_count = _integer(response.get("prompt_eval_count"))
    generated_count = _integer(response.get("eval_count"))
    receipt["result"]["prompt_eval_count"] = prompt_eval_count
    receipt["result"]["generated_token_count"] = generated_count
    if prompt_eval_count is not None:
        receipt["result"]["context_fill_ratio"] = round(
            prompt_eval_count / CONTEXT_TOKENS, 6
        )
    receipt["result"]["ollama_total_ms"] = _duration_ms(response, "total_duration")
    receipt["result"]["ollama_load_ms"] = _duration_ms(response, "load_duration")
    receipt["result"]["ollama_prompt_eval_ms"] = _duration_ms(
        response, "prompt_eval_duration"
    )
    receipt["result"]["ollama_generate_ms"] = _duration_ms(response, "eval_duration")

    failed_http = receipt["result"]["http_status_class"] not in {"2xx", "unknown"}
    if failed_http or "error" in response:
        receipt["status"] = "failed"
        _add_reason(receipt, "ollama_error_response")
    elif receipt["result"]["marker_verified"] is not True:
        receipt["status"] = "failed"
        _add_reason(receipt, "synthetic_marker_not_verified")
    elif prompt_eval_count is None or generated_count is None:
        receipt["status"] = "failed"
        _add_reason(receipt, "ollama_token_telemetry_missing")
    elif generated_count > OUTPUT_TOKEN_CAP:
        receipt["status"] = "failed"
        _add_reason(receipt, "generated_token_cap_exceeded")
    else:
        receipt["status"] = "completed"
        _add_reason(receipt, "measurement_completed")
    return _finish(receipt, started_at, monotonic)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Emit a content-free receipt for one fixed local qwen3.5:9b "
            "8,192-context observation. Dry-run is the default."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Permit one bounded synthetic request after read-only preflight.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = run_probe(execute=args.execute)
    print(json.dumps(receipt, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    if receipt["status"] in {"dry_run", "completed"}:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
