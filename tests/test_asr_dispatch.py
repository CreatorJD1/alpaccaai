from __future__ import annotations

import copy
import importlib
import sys

import pytest

from alpecca import asr_dispatch


def _numeric_gate(name: str, actual: float, limit: float) -> dict[str, object]:
    return {
        "name": name,
        "actual": actual,
        "limit": limit,
        "required": True,
        "passed": actual <= limit,
        "reason": "within-limit" if actual <= limit else "limit-exceeded",
    }


def _benchmark_result(*, mode: str = "live") -> dict[str, object]:
    gates = [
        _numeric_gate("first_partial_latency_ms", 180.0, 800.0),
        _numeric_gate("final_latency_ms", 920.0, 3_000.0),
        _numeric_gate("transcript_error_proxy", 0.08, 0.25),
        _numeric_gate("cpu_peak_percent_estimate", 75.0, 200.0),
        _numeric_gate("interruption_recovery_ms", 340.0, 1_500.0),
        {
            "name": "interruption_trace_consistent",
            "actual": True,
            "limit": True,
            "required": True,
            "passed": True,
            "reason": "consistent",
        },
        {
            "name": "stale_output_after_interrupt",
            "actual": False,
            "limit": False,
            "required": True,
            "passed": True,
            "reason": "none",
        },
    ]
    case = {
        "case_id": "interrupted-command",
        "backend": "moonshine",
        "passed": True,
        "metrics": {
            "first_partial_latency_ms": 180.0,
            "final_latency_ms": 920.0,
            "transcript_error_proxy": 0.08,
            "cpu_peak_percent_estimate": 75.0,
            "interruption_recovery_ms": 340.0,
        },
        "interruption": {
            "required": True,
            "trace_consistent": True,
            "stale_output_after_interrupt": False,
        },
        "gates": gates,
    }
    return {
        "schema": "alpecca.streaming-asr.benchmark-result.v1",
        "mode": mode,
        "production_selection_changed": False,
        "gates": {
            "schema": "alpecca.streaming-asr.gates.v1",
            "max_first_partial_latency_ms": 800.0,
            "max_final_latency_ms": 3_000.0,
            "max_transcript_error_proxy": 0.25,
            "max_cpu_peak_percent": 200.0,
            "max_interruption_recovery_ms": 1_500.0,
            "require_partial": True,
            "require_interruption_recovery": True,
        },
        "case_ids": ["interrupted-command"],
        "backends": [
            {
                "name": "moonshine",
                "status": {"available": True, "loaded": True, "device": "cpu"},
                "passed": True,
                "summary": {
                    "case_count": 1,
                    "passed_count": 1,
                    "failed_count": 0,
                    "all_passed": True,
                },
                "cases": [case],
                "errors": [],
            }
        ],
        "comparison": {
            "baseline": "faster-whisper",
            "candidate": "moonshine",
            "baseline_passed": True,
            "candidate_passed": True,
            "candidate_eligible_for_separate_review": True,
            "recommendation": "review-candidate-evidence",
        },
    }


def _capabilities() -> dict[str, object]:
    return {
        "faster-whisper": {"available": True, "ready": True},
        "moonshine": {"available": True, "ready": True},
    }


def _gate(result: dict[str, object], name: str) -> dict[str, object]:
    candidate = result["backends"][0]
    return next(gate for gate in candidate["cases"][0]["gates"] if gate["name"] == name)


def test_production_default_remains_faster_whisper_even_with_passing_evidence():
    decision = asr_dispatch.select_backend(_benchmark_result(), capabilities=_capabilities())

    assert decision.selected_backend == "faster-whisper"
    assert decision.fallback_order == ("faster-whisper",)
    assert decision.reason == "production-default"
    assert decision.moonshine_eligible is True


def test_explicit_request_permits_moonshine_only_after_all_named_gates_pass():
    decision = asr_dispatch.select_backend(
        _benchmark_result(),
        requested_backend="moonshine",
        capabilities=_capabilities(),
    )

    assert decision.selected_backend == "moonshine"
    assert decision.fallback_order == ("moonshine", "faster-whisper")
    assert decision.reason == "explicit-moonshine-request-approved"


@pytest.mark.parametrize(
    "gate_name",
    [
        "first_partial_latency_ms",
        "final_latency_ms",
        "transcript_error_proxy",
        "interruption_recovery_ms",
        "interruption_trace_consistent",
        "stale_output_after_interrupt",
    ],
)
def test_each_explicit_candidate_gate_blocks_moonshine(gate_name):
    result = _benchmark_result()
    gate = _gate(result, gate_name)
    gate["passed"] = False
    if isinstance(gate["actual"], bool):
        gate["actual"] = not gate["limit"]
    else:
        gate["actual"] = float(gate["limit"]) + 1.0

    assessment = asr_dispatch.assess_moonshine_benchmark(result)
    decision = asr_dispatch.select_backend(
        result, requested_backend="moonshine", capabilities=_capabilities()
    )

    assert assessment.eligible is False
    assert decision.selected_backend == "faster-whisper"
    assert decision.fallback_order == ("faster-whisper",)


def test_aggregate_pass_flags_cannot_override_a_failed_actual_limit():
    result = _benchmark_result()
    gate = _gate(result, "transcript_error_proxy")
    gate["actual"] = 0.9
    gate["passed"] = True

    assessment = asr_dispatch.assess_moonshine_benchmark(result)

    assert assessment.eligible is False
    assert assessment.reasons == ("moonshine-latency-or-error-gate-failed",)


def test_fixture_results_and_results_without_interruption_evidence_are_not_promotable():
    fixture_assessment = asr_dispatch.assess_moonshine_benchmark(
        _benchmark_result(mode="fixture")
    )
    result = _benchmark_result()
    case = result["backends"][0]["cases"][0]
    case["interruption"]["required"] = False

    assert fixture_assessment.reasons == ("live-benchmark-required",)
    assert asr_dispatch.assess_moonshine_benchmark(result).reasons == (
        "interruption-case-required",
    )


def test_missing_capability_forces_default_despite_passing_benchmark():
    capabilities = _capabilities()
    capabilities["moonshine"] = {"available": True, "ready": False}

    decision = asr_dispatch.select_backend(
        _benchmark_result(),
        requested_backend="moonshine",
        capabilities=capabilities,
    )

    assert decision.selected_backend == "faster-whisper"
    assert decision.reason == "moonshine-capability-unavailable"
    assert decision.moonshine_eligible is False


def test_unknown_request_fails_closed_to_production_default():
    decision = asr_dispatch.select_backend(
        _benchmark_result(), requested_backend="other-asr", capabilities=_capabilities()
    )

    assert decision.selected_backend == "faster-whisper"
    assert decision.reason == "unknown-backend-request"


def test_moonshine_factory_is_lazy_and_runtime_failure_falls_back_deterministically():
    loaded: list[str] = []

    def moonshine_factory():
        loaded.append("moonshine")

        def fail(_request):
            raise RuntimeError("candidate failed")

        return fail

    def faster_factory():
        loaded.append("faster-whisper")
        return lambda request: {"transcript": str(request)}

    dispatcher = asr_dispatch.AsrDispatcher(
        {"moonshine": moonshine_factory, "faster-whisper": faster_factory},
        benchmark_result=_benchmark_result(),
        capabilities=_capabilities(),
    )
    assert loaded == []

    outcome = dispatcher.dispatch("hello", requested_backend="moonshine")

    assert loaded == ["moonshine", "faster-whisper"]
    assert outcome.backend == "faster-whisper"
    assert outcome.value == {"transcript": "hello"}
    assert outcome.fallback_used is True
    assert outcome.attempted_backends == ("moonshine", "faster-whisper")


def test_default_dispatch_never_loads_moonshine_without_an_explicit_request():
    loaded: list[str] = []
    dispatcher = asr_dispatch.AsrDispatcher(
        {
            "faster-whisper": lambda: (lambda _request: "baseline"),
            "moonshine": lambda: loaded.append("moonshine") or (lambda _request: "candidate"),
        },
        benchmark_result=_benchmark_result(),
        capabilities=_capabilities(),
    )

    outcome = dispatcher.dispatch(object())

    assert outcome.backend == "faster-whisper"
    assert outcome.value == "baseline"
    assert loaded == []


def test_all_backend_failures_have_bounded_content_free_error():
    def fail_factory():
        return lambda _request: (_ for _ in ()).throw(ValueError("sensitive detail"))

    dispatcher = asr_dispatch.AsrDispatcher(
        {"faster-whisper": fail_factory}, capabilities={"faster-whisper": True}
    )

    with pytest.raises(asr_dispatch.AsrDispatchError) as caught:
        dispatcher.dispatch("private audio metadata")

    assert caught.value.attempted_backends == ("faster-whisper",)
    assert "sensitive" not in str(caught.value)


def test_status_snapshot_is_deterministic_and_reports_capability_load_state():
    dispatcher = asr_dispatch.AsrDispatcher(
        {
            "faster-whisper": lambda: (lambda _request: "baseline"),
            "moonshine": lambda: (lambda _request: "candidate"),
        },
        benchmark_result=_benchmark_result(),
        capabilities=_capabilities(),
    )

    before = dispatcher.status_snapshot(requested_backend="moonshine")
    dispatcher.dispatch("audio", requested_backend="moonshine")
    after = dispatcher.status_snapshot(requested_backend="moonshine")

    assert before["schema"] == "alpecca.asr-dispatch-status.v1"
    assert before["production_default"] == "faster-whisper"
    assert before["selection"]["selected_backend"] == "moonshine"
    assert before["capabilities"]["moonshine"] == {
        "available": True,
        "ready": True,
        "configured": True,
        "loaded": False,
    }
    assert after["capabilities"]["moonshine"]["loaded"] is True
    assert after["last_dispatch"] == {
        "attempted_backends": ["moonshine"],
        "completed_backend": "moonshine",
        "fallback_used": False,
    }
    assert after == dispatcher.status_snapshot(requested_backend="moonshine")


def test_module_reload_does_not_import_optional_asr_packages(monkeypatch):
    real_import = importlib.import_module
    attempted: list[str] = []

    def guarded_import(name, package=None):
        if name in {"faster_whisper", "moonshine", "moonshine_onnx"}:
            attempted.append(name)
            raise AssertionError("optional backend imported at module load")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", guarded_import)
    before = {name for name in sys.modules if name in {"faster_whisper", "moonshine", "moonshine_onnx"}}

    importlib.reload(asr_dispatch)

    after = {name for name in sys.modules if name in {"faster_whisper", "moonshine", "moonshine_onnx"}}
    assert attempted == []
    assert after == before


def test_assessment_does_not_mutate_supplied_benchmark_object():
    result = _benchmark_result()
    original = copy.deepcopy(result)

    asr_dispatch.assess_moonshine_benchmark(result)

    assert result == original


def test_consumes_result_emitted_by_benchmark_harness():
    from scripts import benchmark_streaming_asr as benchmark

    case = benchmark.BenchmarkCase(
        case_id="actual-contract",
        reference_text="turn on the studio lights",
        audio_duration_ms=1_200.0,
        interrupt_at_ms=300.0,
    )
    run = benchmark.BackendRun(
        events=(
            benchmark.AsrEvent("partial", 150.0, "turn on", 60.0),
            benchmark.AsrEvent("final", 780.0, "turn on the studio lights", 72.0),
        ),
        interruption=benchmark.InterruptionTrace(300.0, 320.0, 780.0, False),
    )

    class LiveBackend:
        def __init__(self, name):
            self.name = name

        def status(self):
            return {"available": True, "loaded": True, "mode": "live", "device": "cpu"}

        def run(self, _case):
            return run

    result = benchmark.run_benchmark(
        [case],
        {
            "faster-whisper": LiveBackend("faster-whisper"),
            "moonshine": LiveBackend("moonshine"),
        },
        mode="live",
    )

    assessment = asr_dispatch.assess_moonshine_benchmark(result)

    assert assessment.eligible is True
    assert assessment.case_count == 1
    assert assessment.interruption_case_count == 1
