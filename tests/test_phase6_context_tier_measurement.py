"""Focused contracts for the evidence-only Phase 6 context-tier harness."""
from __future__ import annotations

import json
import threading
from typing import Any

import pytest

from alpecca import context_tier_measurement as measurement


class _Response:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self._status = status

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> bool:
        return False

    def getcode(self) -> int:
        return self._status

    def read(self) -> bytes:
        return self._body


class _RecordingOpener:
    def __init__(self, response: dict[str, Any], release_response: threading.Event) -> None:
        self._body = json.dumps(response).encode("utf-8")
        self._release_response = release_response
        self.requests: list[tuple[Any, float | None]] = []

    def open(self, request: Any, timeout: float | None = None) -> _Response:
        self.requests.append((request, timeout))
        if not self._release_response.wait(timeout=1.0):
            raise AssertionError("the during sample did not release the injected opener")
        return _Response(self._body)


class _Sampler:
    def __init__(self, release_response: threading.Event) -> None:
        self._release_response = release_response
        self.force_values: list[bool] = []

    def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        self.force_values.append(force)
        sequence = len(self.force_values)
        if sequence == 2:
            self._release_response.set()
        return {"sequence": sequence, "unknowns": []}


class _TickClock:
    def __init__(self, initial: float = 0.0) -> None:
        self.value = initial

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


def _assert_explicit_evidence_only_fields(report: dict[str, Any]) -> None:
    assert report["automatic_promotion"] is False
    assert report["system_settings_mutated"] is False
    assert report["pagefile_mutated"] is False
    assert report["manual_review_only"] is True
    assert report["manual_review"]["required"] is True
    assert report["manual_review"]["decision"] == "manual_review_only"
    assert report["side_effects"] == {
        "downloads_requested": False,
        "files_written": False,
        "system_settings_mutated": False,
        "pagefile_mutated": False,
    }


@pytest.mark.parametrize("tier", measurement.ALLOWED_CONTEXT_TIERS)
def test_validate_context_tier_accepts_each_explicitly_allowed_tier(tier: int):
    assert measurement.validate_context_tier(tier) == tier
    assert measurement.validate_context_tier(str(tier)) == tier


@pytest.mark.parametrize("value", (0, 8191, 49153, "8192.0", True))
def test_validate_context_tier_rejects_values_outside_the_allowlist(value: object):
    with pytest.raises(measurement.ContextTierValidationError):
        measurement.validate_context_tier(value)  # type: ignore[arg-type]


def test_default_dry_run_uses_no_network_or_sampler_and_reports_no_mutation(monkeypatch):
    opener_calls: list[tuple[object, ...]] = []
    release_response = threading.Event()
    sampler = _Sampler(release_response)

    def unexpected_build_opener(*handlers):
        opener_calls.append(handlers)
        raise AssertionError("dry run must not construct an HTTP opener")

    monkeypatch.setattr(measurement, "build_opener", unexpected_build_opener)

    report = measurement.run_context_tier_measurement(tier=8192, sampler=sampler)

    assert opener_calls == []
    assert sampler.force_values == []
    assert report["status"] == "dry_run"
    assert report["mode"] == "dry_run"
    assert report["request"] == {
        "allowed": False,
        "attempted": False,
        "method": "POST",
        "endpoint": "http://127.0.0.1:11434/api/generate",
        "http_request_count": 0,
        "http_request_count_limit": 1,
        "stream": False,
        "think": False,
        "options": {"num_ctx": 8192, "num_predict": measurement.SMALL_OUTPUT_CAP_TOKENS},
    }
    assert report["resources"] == {
        "sampler_source": "not_started",
        "before": None,
        "during": None,
        "after": None,
    }
    assert report["marker_verification"]["checked"] is False
    assert report["marker_verification"]["verified"] is None
    assert "Dry run: no Ollama request was made." in report["unknowns"]
    _assert_explicit_evidence_only_fields(report)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    (
        ({"model": f"{measurement.LOCAL_QWEN_MODEL}:cloud"}, "cloud models are forbidden"),
        ({"host": "http://198.51.100.8:11434"}, "nonloopback Ollama hosts are forbidden"),
    ),
)
def test_unsafe_model_or_host_is_rejected_before_sampling_or_request(
    kwargs: dict[str, str], error: str
):
    sampler = _Sampler(threading.Event())
    request_calls: list[tuple[str, object, float]] = []

    def unexpected_request(host: str, payload: object, timeout: float) -> object:
        request_calls.append((host, payload, timeout))
        raise AssertionError("unsafe configuration must not issue a request")

    with pytest.raises(measurement.ContextTierValidationError, match=error):
        measurement.run_context_tier_measurement(
            tier=8192,
            execute=True,
            sampler=sampler,
            request_fn=unexpected_request,
            **kwargs,
        )

    assert sampler.force_values == []
    assert request_calls == []


def test_execute_uses_one_injected_opener_request_and_verifies_the_synthetic_marker(
    monkeypatch,
):
    tier = 16384
    marker = measurement.marker_for_tier(tier)
    release_response = threading.Event()
    sampler = _Sampler(release_response)
    opener = _RecordingOpener(
        {
            "response": marker,
            "prompt_eval_count": tier // 4,
            "eval_count": 5,
            "total_duration": 5_000_000,
            "load_duration": 1_000_000,
            "prompt_eval_duration": 3_000_000,
            "eval_duration": 1_000_000,
        },
        release_response,
    )
    build_calls: list[tuple[object, ...]] = []

    def injected_build_opener(*handlers):
        build_calls.append(handlers)
        return opener

    monkeypatch.setattr(measurement, "build_opener", injected_build_opener)

    report = measurement.run_context_tier_measurement(
        tier=tier,
        execute=True,
        sampler=sampler,
        clock=_TickClock(10.0),
        wall_clock=_TickClock(100.0),
        request_timeout_seconds=7.5,
    )

    assert len(build_calls) == 1
    assert len(opener.requests) == 1
    request, timeout = opener.requests[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert timeout == 7.5
    assert request.full_url == "http://127.0.0.1:11434/api/generate"
    assert request.get_method() == "POST"
    assert payload["model"] == measurement.LOCAL_QWEN_MODEL
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["options"] == {
        "num_ctx": tier,
        "num_predict": measurement.SMALL_OUTPUT_CAP_TOKENS,
    }
    assert payload["prompt"].count(marker) == 1
    assert sampler.force_values == [True, True, True]

    assert report["status"] == "completed"
    assert report["request"]["allowed"] is True
    assert report["request"]["attempted"] is True
    assert report["request"]["http_request_count"] == 1
    assert report["request"]["http_request_count_limit"] == 1
    assert report["request"]["options"] == payload["options"]
    assert [report["resources"][phase]["data"]["sequence"] for phase in ("before", "during", "after")] == [
        1,
        2,
        3,
    ]
    assert report["resources"]["sampler_source"] == "injected"
    assert report["resources"]["during"]["request_in_flight"] is True
    assert report["prompt"]["marker"] == marker
    assert report["prompt"]["marker_occurrences_in_prompt"] == 1
    assert report["marker_verification"] == {
        "marker": marker,
        "checked": True,
        "response_contains_marker": True,
        "verified": True,
        "response_characters": len(marker),
        "response_excerpt": marker,
    }
    assert report["tokens"] == {
        "requested_context": tier,
        "planned_prompt_budget": measurement.planned_prompt_token_budget(tier),
        "output_cap": measurement.SMALL_OUTPUT_CAP_TOKENS,
        "prompt_eval_count": tier // 4,
        "eval_count": 5,
        "prompt_context_fill_ratio": 0.25,
    }
    _assert_explicit_evidence_only_fields(report)
