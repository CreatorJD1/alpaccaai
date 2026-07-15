"""Focused contracts for the fixed, content-free Phase 6 context probe."""
from __future__ import annotations

import json
import threading
import time

import pytest

from scripts import measure_context_8192 as probe


GiB = 1024 * 1024 * 1024


def _safe_snapshot(*, severity: str = "normal") -> dict:
    return {
        "raw": {
            "cpu_percent": 12.5,
            "vram_used_bytes": GiB,
            "vram_total_bytes": 4 * GiB,
        },
        "headroom": {
            "ram_bytes": 8 * GiB,
            "ram_fraction": 0.40,
            "commit_bytes": 16 * GiB,
            "commit_fraction": 0.40,
            "disk_bytes": 80 * GiB,
            "disk_fraction": 0.40,
        },
        "battery": {"percent": 90.0, "charging": True},
        "assessment": {
            "severity": severity,
            "overall_pressure": 0.20,
            "readings": {},
            "unknown_resources": [],
        },
    }


class _Sampler:
    def __init__(self, snapshot: dict | None = None):
        self.snapshot_value = snapshot or _safe_snapshot()
        self.calls = 0

    def snapshot(self, force: bool = False):
        assert force is True
        self.calls += 1
        return self.snapshot_value


def _success_response() -> dict:
    return {
        "_http_status": 200,
        "response": "ALPECCA_CONTEXT_TIER_8192_MARKER_7F3C8D19",
        "prompt_eval_count": 2054,
        "eval_count": 15,
        "total_duration": 2_000_000,
        "load_duration": 100_000,
        "prompt_eval_duration": 1_500_000,
        "eval_duration": 400_000,
    }


def _walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def test_dry_run_is_fixed_bounded_and_makes_no_observation_or_request():
    sampler = _Sampler()
    requests = []

    receipt = probe.run_probe(
        sampler=sampler,
        request_fn=lambda *args: requests.append(args),
    )

    assert receipt["status"] == "dry_run"
    assert receipt["target"] == {
        "model": "qwen3.5:9b",
        "context_tokens": 8192,
        "output_token_cap": 32,
        "stream": False,
        "think": False,
        "loopback_only": True,
    }
    assert receipt["execution"]["http_request_count"] == 0
    assert sampler.calls == 0
    assert requests == []
    assert receipt["side_effects"]["pagefile_changed"] is False
    assert receipt["side_effects"]["system_settings_changed"] is False


@pytest.mark.parametrize("model", ["qwen3:8b", "qwen3.5:4b", "qwen3.5:9b-cloud"])
def test_any_model_other_than_configured_qwen35_9b_blocks_before_sampling(model):
    sampler = _Sampler()
    requests = []

    receipt = probe.run_probe(
        execute=True,
        configured_model=model,
        sampler=sampler,
        request_fn=lambda *args: requests.append(args),
    )

    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["configured_model_mismatch"]
    assert receipt["target"]["model"] == "qwen3.5:9b"
    assert model not in json.dumps(receipt)
    assert sampler.calls == 0
    assert requests == []


def test_nonloopback_or_credentialed_host_blocks_without_echoing_it():
    secret_host = "http://user:secret@example.test:11434"
    receipt = probe.run_probe(
        execute=True,
        configured_host=secret_host,
        configured_model="qwen3.5:9b",
        sampler=_Sampler(),
    )

    encoded = json.dumps(receipt)
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["ollama_host_not_direct_loopback"]
    assert "user:secret" not in encoded
    assert "example.test" not in encoded


def test_known_high_pressure_blocks_before_the_only_http_request():
    sampler = _Sampler(_safe_snapshot(severity="high"))
    requests = []

    receipt = probe.run_probe(
        execute=True,
        configured_model="qwen3.5:9b",
        configured_host="http://127.0.0.1:11434",
        sampler=sampler,
        request_fn=lambda *args: requests.append(args),
    )

    assert receipt["status"] == "blocked"
    assert "host_assessment_high" in receipt["reason_codes"]
    assert receipt["preflight"]["request_permitted"] is False
    assert receipt["execution"]["http_request_count"] == 0
    assert sampler.calls == 1
    assert requests == []


def test_success_uses_one_fixed_request_and_receipt_retains_no_content():
    sampler = _Sampler()
    calls = []

    def request_once(host, payload, timeout):
        calls.append((host, payload, timeout))
        return _success_response()

    receipt = probe.run_probe(
        execute=True,
        configured_model="qwen3.5:9b",
        configured_host="http://127.0.0.1:11434",
        sampler=sampler,
        request_fn=request_once,
    )

    assert receipt["status"] == "completed"
    assert receipt["reason_codes"] == ["measurement_completed"]
    assert len(calls) == 1
    host, payload, timeout = calls[0]
    assert host == "http://127.0.0.1:11434"
    assert timeout <= probe.REQUEST_TIMEOUT_SECONDS
    assert payload["model"] == "qwen3.5:9b"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["options"] == {"num_ctx": 8192, "num_predict": 32}
    assert payload["prompt"].count("ALPECCA_CONTEXT_TIER_8192_MARKER_7F3C8D19") == 1

    serialized = json.dumps(receipt, sort_keys=True)
    assert "ALPECCA_CONTEXT_TIER_8192_MARKER_7F3C8D19" not in serialized
    assert "synthetic-row" not in serialized
    assert "127.0.0.1" not in serialized
    assert not (set(_walk_keys(receipt)) & probe._FORBIDDEN_RECEIPT_KEYS)
    assert receipt["result"]["marker_verified"] is True
    assert receipt["result"]["prompt_eval_count"] == 2054
    assert receipt["result"]["generated_token_count"] == 15
    assert receipt["execution"]["http_request_count"] == 1
    probe.validate_content_free_receipt(receipt)


def test_wall_time_cap_returns_without_waiting_for_a_stuck_request():
    release = threading.Event()

    def stuck_request(*_args):
        release.wait(timeout=1.0)
        return _success_response()

    started = time.monotonic()
    try:
        receipt = probe.run_probe(
            execute=True,
            configured_model="qwen3.5:9b",
            configured_host="http://127.0.0.1:11434",
            sampler=_Sampler(),
            request_fn=stuck_request,
            wall_time_limit_seconds=0.05,
            request_timeout_seconds=0.04,
            resource_sample_timeout_seconds=0.01,
        )
    finally:
        release.set()

    elapsed = time.monotonic() - started
    assert receipt["status"] == "timed_out"
    assert receipt["reason_codes"] == ["wall_time_limit_reached"]
    assert receipt["execution"]["http_request_count"] == 1
    assert receipt["bounds"]["wall_time_limit_ms"] == 50
    assert elapsed < 0.5


def test_validator_rejects_future_content_bearing_schema_drift():
    receipt = probe.run_probe()
    receipt["result"]["response_excerpt"] = "should never be retained"

    with pytest.raises(ValueError, match="content-bearing"):
        probe.validate_content_free_receipt(receipt)
