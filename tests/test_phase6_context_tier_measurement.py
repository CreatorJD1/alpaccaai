"""Focused contracts for the evidence-only Phase 6 context-tier harness."""
from __future__ import annotations

from copy import deepcopy
import json
import threading
from typing import Any

import pytest

from alpecca import context_tier_measurement as measurement
from alpecca import resource_signals


GiB = 1024**3


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


class _StaticSnapshotSampler:
    """Return one deterministic HostResourceSampler-shaped snapshot."""

    def __init__(
        self,
        snapshot: dict[str, Any],
        release_response: threading.Event | None = None,
    ) -> None:
        self._snapshot = deepcopy(snapshot)
        self._release_response = release_response
        self.force_values: list[bool] = []

    def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        self.force_values.append(force)
        if len(self.force_values) == 2 and self._release_response is not None:
            self._release_response.set()
        return deepcopy(self._snapshot)


class _SequenceSnapshotSampler:
    """Return deterministic snapshots in order while recording forced reads."""

    def __init__(
        self,
        *snapshots: dict[str, Any],
        release_response: threading.Event | None = None,
        release_on_call: int | None = None,
    ) -> None:
        if not snapshots:
            raise ValueError("at least one snapshot is required")
        self._snapshots = tuple(deepcopy(snapshot) for snapshot in snapshots)
        self._release_response = release_response
        self._release_on_call = release_on_call
        self.force_values: list[bool] = []

    def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        self.force_values.append(force)
        call_count = len(self.force_values)
        if (
            self._release_response is not None
            and self._release_on_call is not None
            and call_count == self._release_on_call
        ):
            self._release_response.set()
        index = min(call_count - 1, len(self._snapshots) - 1)
        return deepcopy(self._snapshots[index])


class _TickClock:
    def __init__(self, initial: float = 0.0) -> None:
        self.value = initial

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


def _remaining(used: object, total: object) -> tuple[int | None, float | None]:
    if not isinstance(used, int) or not isinstance(total, int) or used > total:
        return None, None
    headroom = total - used
    return headroom, round(headroom / total, 4) if total else None


def _host_snapshot(
    *,
    cpu_percent: float = 18.0,
    ram_headroom_bytes: int = 12 * GiB,
    commit_headroom_bytes: int = 24 * GiB,
    disk_headroom_bytes: int = 256 * GiB,
    battery_percent: float = 90.0,
    battery_charging: bool = True,
    unknown_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build a complete, read-only HostResourceSampler-shaped test sample."""
    ram_total = 24 * GiB
    commit_limit = 48 * GiB
    disk_total = 512 * GiB
    raw: dict[str, Any] = {
        "cpu_percent": cpu_percent,
        "ram_used_bytes": ram_total - ram_headroom_bytes,
        "ram_total_bytes": ram_total,
        "commit_used_bytes": commit_limit - commit_headroom_bytes,
        "commit_limit_bytes": commit_limit,
        "vram_used_bytes": GiB,
        "vram_total_bytes": 4 * GiB,
        "disk_free_bytes": disk_headroom_bytes,
        "disk_total_bytes": disk_total,
        "battery_percent": battery_percent,
        "battery_charging": battery_charging,
        "thermal_celsius": 45.0,
    }
    for field in unknown_fields:
        raw[field] = None

    ram_bytes, ram_fraction = _remaining(raw["ram_used_bytes"], raw["ram_total_bytes"])
    commit_bytes, commit_fraction = _remaining(
        raw["commit_used_bytes"], raw["commit_limit_bytes"]
    )
    vram_bytes, vram_fraction = _remaining(raw["vram_used_bytes"], raw["vram_total_bytes"])
    disk_free = raw["disk_free_bytes"]
    disk_bytes = disk_free if isinstance(disk_free, int) else None
    disk_fraction = (
        round(disk_free / raw["disk_total_bytes"], 4)
        if isinstance(disk_free, int) and isinstance(raw["disk_total_bytes"], int)
        else None
    )
    assessment = resource_signals.assess_resources(**raw)
    headroom = {
        "ram_bytes": ram_bytes,
        "ram_fraction": ram_fraction,
        "commit_bytes": commit_bytes,
        "commit_fraction": commit_fraction,
        "vram_bytes": vram_bytes,
        "vram_fraction": vram_fraction,
        "disk_bytes": disk_bytes,
        "disk_fraction": disk_fraction,
        "ram": {"bytes": ram_bytes, "fraction": ram_fraction},
        "commit": {"bytes": commit_bytes, "fraction": commit_fraction},
        "vram": {"bytes": vram_bytes, "fraction": vram_fraction},
        "disk": {"bytes": disk_bytes, "fraction": disk_fraction},
    }
    return {
        "state": "ready" if not unknown_fields else "partial",
        "raw": raw,
        "headroom": headroom,
        "assessment": assessment,
        "unknowns": list(unknown_fields),
        "unknown_fields": list(unknown_fields),
        "unknown_reasons": {field: "not_available" for field in unknown_fields},
    }


def _successful_response(tier: int) -> dict[str, Any]:
    return {
        "response": measurement.marker_for_tier(tier),
        "prompt_eval_count": tier // 4,
        "eval_count": 1,
    }


def _assert_preflight_blocked(
    report: dict[str, Any],
    request_calls: list[tuple[str, object, float]],
    expected_reason_code: str,
) -> None:
    assert report["status"] == "blocked"
    assert report["mode"] == "execute"
    assert report["preflight"]["performed"] is True
    assert report["preflight"]["status"] == "blocked"
    assert report["preflight"]["request_permitted"] is False
    assert report["preflight"]["evidence_state"] == "observed"
    assert expected_reason_code in {
        reason["code"] for reason in report["preflight"]["reasons"]
    }
    assert report["request"]["allowed"] is False
    assert report["request"]["attempted"] is False
    assert report["request"]["http_request_count"] == 0
    assert report["marker_verification"]["checked"] is False
    assert request_calls == []
    _assert_explicit_evidence_only_fields(report)


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


@pytest.mark.parametrize(
    ("sample", "sample_unknowns", "expected_evidence_state"),
    (
        (_host_snapshot(), (), "observed"),
        (
            _host_snapshot(unknown_fields=("cpu_percent",)),
            ("before resource sample: cpu_percent is unknown (warming).",),
            "partial",
        ),
        (None, (), "unknown"),
    ),
)
def test_execution_preflight_reports_the_evidence_it_actually_has(
    sample: dict[str, Any] | None,
    sample_unknowns: tuple[str, ...],
    expected_evidence_state: str,
):
    preflight = measurement.evaluate_execution_preflight(
        sample,
        sample_unknowns=sample_unknowns,
    )

    assert preflight["evidence_state"] == expected_evidence_state


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
        "warmup": None,
        "before": None,
        "during": None,
        "after": None,
    }
    assert report["marker_verification"]["checked"] is False
    assert report["marker_verification"]["verified"] is None
    assert "Dry run: no Ollama request was made." in report["unknowns"]
    assert report["preflight"]["performed"] is False
    assert report["preflight"]["status"] == "not_run"
    assert report["preflight"]["request_permitted"] is False
    assert report["preflight"]["evidence_state"] == "unknown"
    assert report["preflight"]["reasons"] == []
    assert report["preflight"]["unknowns"] == []
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


@pytest.mark.parametrize(
    ("cpu_percent", "severity"),
    (
        (86.0, "high"),
        (96.0, "critical"),
    ),
)
def test_execute_preflight_blocks_high_or_critical_host_pressure_before_http(
    cpu_percent: float, severity: str
):
    sample = _host_snapshot(cpu_percent=cpu_percent)
    sampler = _StaticSnapshotSampler(sample)
    request_calls: list[tuple[str, object, float]] = []

    def unexpected_request(host: str, payload: object, timeout: float) -> object:
        request_calls.append((host, payload, timeout))
        raise AssertionError("preflight-blocked execution must not issue an HTTP request")

    assert sample["assessment"]["severity"] == severity
    report = measurement.run_context_tier_measurement(
        tier=8192,
        execute=True,
        sampler=sampler,
        request_fn=unexpected_request,
    )

    assert report["resources"]["before"]["data"] == sample
    _assert_preflight_blocked(report, request_calls, f"host_assessment_{severity}")


@pytest.mark.parametrize(
    ("resource", "snapshot_kwargs"),
    (
        ("ram", {"ram_headroom_bytes": GiB}),
        ("commit", {"commit_headroom_bytes": GiB}),
        ("disk", {"disk_headroom_bytes": GiB}),
    ),
)
def test_execute_preflight_blocks_insufficient_known_headroom_before_http(
    resource: str, snapshot_kwargs: dict[str, int]
):
    sample = _host_snapshot(**snapshot_kwargs)
    sampler = _StaticSnapshotSampler(sample)
    request_calls: list[tuple[str, object, float]] = []

    def unexpected_request(host: str, payload: object, timeout: float) -> object:
        request_calls.append((host, payload, timeout))
        raise AssertionError("insufficient headroom must stop before an HTTP request")

    assert sample["headroom"][f"{resource}_bytes"] == GiB
    report = measurement.run_context_tier_measurement(
        tier=8192,
        execute=True,
        sampler=sampler,
        request_fn=unexpected_request,
    )

    assert report["resources"]["before"]["data"]["headroom"][f"{resource}_bytes"] == GiB
    _assert_preflight_blocked(
        report,
        request_calls,
        f"{resource}_headroom_below_safe_threshold",
    )


def test_execute_preflight_blocks_low_unplugged_battery_before_http():
    sample = _host_snapshot(battery_percent=5.0, battery_charging=False)
    sampler = _StaticSnapshotSampler(sample)
    request_calls: list[tuple[str, object, float]] = []

    def unexpected_request(host: str, payload: object, timeout: float) -> object:
        request_calls.append((host, payload, timeout))
        raise AssertionError("low discharging battery must stop before an HTTP request")

    assert sample["raw"]["battery_percent"] == 5.0
    assert sample["raw"]["battery_charging"] is False
    report = measurement.run_context_tier_measurement(
        tier=8192,
        execute=True,
        sampler=sampler,
        request_fn=unexpected_request,
    )

    assert report["resources"]["before"]["data"] == sample
    _assert_preflight_blocked(report, request_calls, "battery_low_not_charging")


def test_execute_preflight_allows_a_safe_known_sample_and_makes_exactly_one_request():
    tier = 8192
    sample = _host_snapshot()
    release_response = threading.Event()
    sampler = _StaticSnapshotSampler(sample, release_response)
    request_calls: list[tuple[str, object, float]] = []

    def request_once(host: str, payload: object, timeout: float) -> object:
        request_calls.append((host, payload, timeout))
        if not release_response.wait(timeout=1.0):
            raise AssertionError("the during sample did not release the injected request")
        return _successful_response(tier)

    assert sample["assessment"]["severity"] == "normal"
    assert sample["assessment"]["unknown_resources"] == []
    report = measurement.run_context_tier_measurement(
        tier=tier,
        execute=True,
        sampler=sampler,
        request_fn=request_once,
    )

    assert len(request_calls) == 1
    assert report["status"] == "completed"
    assert report["preflight"]["performed"] is True
    assert report["preflight"]["status"] == "passed"
    assert report["preflight"]["request_permitted"] is True
    assert report["preflight"]["evidence_state"] == "observed"
    assert report["preflight"]["reasons"] == []
    assert report["preflight"]["unknowns"] == []
    assert report["request"]["allowed"] is True
    assert report["request"]["attempted"] is True
    assert report["request"]["http_request_count"] == 1
    assert report["resources"]["before"]["data"] == sample
    _assert_explicit_evidence_only_fields(report)


def test_execute_preflight_reports_unknown_fields_without_fabricating_a_block():
    tier = 8192
    unknown_fields = (
        "ram_used_bytes",
        "ram_total_bytes",
        "commit_used_bytes",
        "commit_limit_bytes",
        "disk_free_bytes",
        "disk_total_bytes",
        "battery_percent",
        "battery_charging",
    )
    sample = _host_snapshot(unknown_fields=unknown_fields)
    release_response = threading.Event()
    sampler = _StaticSnapshotSampler(sample, release_response)
    request_calls: list[tuple[str, object, float]] = []

    def request_once(host: str, payload: object, timeout: float) -> object:
        request_calls.append((host, payload, timeout))
        if not release_response.wait(timeout=1.0):
            raise AssertionError("the during sample did not release the injected request")
        return _successful_response(tier)

    assert sample["assessment"]["severity"] == "normal"
    assert set(sample["assessment"]["unknown_resources"]) == {
        "ram",
        "commit",
        "disk",
        "battery",
    }
    report = measurement.run_context_tier_measurement(
        tier=tier,
        execute=True,
        sampler=sampler,
        request_fn=request_once,
    )

    assert len(request_calls) == 1
    assert report["status"] == "completed"
    assert report["preflight"]["status"] == "passed"
    assert report["preflight"]["request_permitted"] is True
    assert report["preflight"]["evidence_state"] == "partial"
    assert report["preflight"]["reasons"] == []
    for message in (
        "RAM headroom bytes are unknown or invalid.",
        "COMMIT headroom bytes are unknown or invalid.",
        "DISK headroom bytes are unknown or invalid.",
        "Battery percentage is unknown or invalid.",
        "Battery charging state is unknown or invalid.",
    ):
        assert message in report["preflight"]["unknowns"]
    assert report["request"]["attempted"] is True
    assert report["request"]["http_request_count"] == 1
    assert report["resources"]["before"]["data"]["unknown_fields"] == list(unknown_fields)
    assert "before resource sample: ram_used_bytes" in report["unknowns"]
    assert "before resource sample: ram_used_bytes is unknown (not_available)." in report["unknowns"]
    _assert_explicit_evidence_only_fields(report)


def test_project_sampler_warms_cpu_before_preflight_and_blocks_on_second_sample(
    monkeypatch,
):
    warming_cpu = _host_snapshot(unknown_fields=("cpu_percent",))
    critical_cpu = _host_snapshot(cpu_percent=96.0)
    sampler = _SequenceSnapshotSampler(warming_cpu, critical_cpu)
    request_calls: list[tuple[str, object, float]] = []

    def project_sampler() -> tuple[object, str, list[str]]:
        return sampler, "project:alpecca.host_resources", []

    def unexpected_request(host: str, payload: object, timeout: float) -> object:
        request_calls.append((host, payload, timeout))
        raise AssertionError("the warmed project preflight must block before HTTP")

    monkeypatch.setattr(measurement, "_default_sampler", project_sampler)

    report = measurement.run_context_tier_measurement(
        tier=8192,
        execute=True,
        request_fn=unexpected_request,
    )

    assert sampler.force_values == [True, True]
    assert report["resources"]["sampler_source"] == "project:alpecca.host_resources"
    assert report["resources"]["warmup"]["data"] == warming_cpu
    assert report["resources"]["before"]["data"] == critical_cpu
    assert report["preflight"]["evidence_state"] == "observed"
    assert report["preflight"]["observed"]["assessment_severity"]["value"] == "critical"
    _assert_preflight_blocked(report, request_calls, "host_assessment_critical")


def test_injected_sampler_does_not_receive_the_project_cpu_warmup_sample():
    tier = 8192
    release_response = threading.Event()
    sampler = _SequenceSnapshotSampler(
        _host_snapshot(unknown_fields=("cpu_percent",)),
        _host_snapshot(cpu_percent=96.0),
        _host_snapshot(),
        release_response=release_response,
        release_on_call=2,
    )
    request_calls: list[tuple[str, object, float]] = []

    def request_once(host: str, payload: object, timeout: float) -> object:
        request_calls.append((host, payload, timeout))
        if not release_response.wait(timeout=1.0):
            raise AssertionError("the during sample did not release the injected request")
        return _successful_response(tier)

    report = measurement.run_context_tier_measurement(
        tier=tier,
        execute=True,
        sampler=sampler,
        request_fn=request_once,
    )

    assert len(request_calls) == 1
    assert sampler.force_values == [True, True, True]
    assert report["resources"]["sampler_source"] == "injected"
    assert report["resources"]["warmup"] is None
    assert report["preflight"]["evidence_state"] == "partial"
    assert report["preflight"]["request_permitted"] is True
    assert report["request"]["http_request_count"] == 1
    assert report["status"] == "completed"
    _assert_explicit_evidence_only_fields(report)


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
    assert report["preflight"]["evidence_state"] == "unknown"
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
