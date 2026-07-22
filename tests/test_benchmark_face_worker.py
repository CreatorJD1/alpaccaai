from __future__ import annotations

import json
import sys

import pytest

from scripts import benchmark_face_worker as bench


def samples() -> list[bench.BenchmarkSample]:
    return [
        bench.BenchmarkSample("known", bench.OutcomeKind.MATCH),
        bench.BenchmarkSample("unknown", bench.OutcomeKind.NO_MATCH),
        bench.BenchmarkSample("empty", bench.OutcomeKind.NO_FACE),
        bench.BenchmarkSample("crowd", bench.OutcomeKind.MULTIPLE_FACES),
    ]


def outcome_for(sample: bench.BenchmarkSample, *, memory: int = 32_000_000):
    values = {
        "known": bench.SampleOutcome(bench.OutcomeKind.MATCH, 1, 0.91, memory),
        "unknown": bench.SampleOutcome(bench.OutcomeKind.NO_MATCH, 1, 0.12, memory),
        "empty": bench.SampleOutcome(bench.OutcomeKind.NO_FACE, 0, None, memory),
        "crowd": bench.SampleOutcome(
            bench.OutcomeKind.MULTIPLE_FACES, 2, None, memory
        ),
    }
    return values[sample.sample_id]


def metadata(*, approved: bool = True) -> bench.CandidateMetadata:
    return bench.CandidateMetadata(
        name="opencv-yunet-sface-cpu",
        detector_component="yunet",
        recognizer_component="sface",
        device="cpu",
        memory_estimate_method="caller-measured-peak-rss",
        licenses=(
            bench.LicenseMetadata(
                "yunet", "MIT", "opencv-model-zoo-yunet", True, approved
            ),
            bench.LicenseMetadata(
                "sface", "Apache-2.0", "opencv-model-zoo-sface", True, approved
            ),
            bench.LicenseMetadata(
                "opencv", "Apache-2.0", "opencv-runtime", True, approved
            ),
        ),
    )


def clock(step_ns: int = 2_000_000):
    current = -step_ns

    def read() -> int:
        nonlocal current
        current += step_ns
        return current

    return read


def test_module_loads_without_optional_face_packages():
    source_names = set(bench.__dict__)
    assert "cv2" not in source_names
    assert "numpy" not in source_names
    assert "requests" not in source_names
    assert "urllib3" not in source_names
    assert not any(name == "cv2" and value is bench for name, value in sys.modules.items())


def test_passing_candidate_compares_against_disabled_baseline_and_emits_policy():
    result = bench.run_benchmark(
        samples(), outcome_for, metadata(), cpu_clock_ns=clock()
    )

    assert result["schema"] == bench.RESULT_SCHEMA
    assert result["baseline"]["name"] == "disabled-noop"
    assert result["baseline"]["disabled"] is True
    assert result["baseline"]["summary"]["outcome_accuracy"] == 0.0
    assert result["baseline"]["summary"]["peak_memory_estimate_bytes"] == 0
    assert result["candidate"]["summary"] == {
        "sample_count": 4,
        "correct_count": 4,
        "outcome_accuracy": 1.0,
        "deterministic_outcomes": True,
        "mean_cpu_latency_ms": 2.0,
        "p95_cpu_latency_ms": 2.0,
        "peak_memory_estimate_bytes": 32_000_000,
        "memory_estimate_source": "caller-reported",
        "error_count": 0,
    }
    assert result["face_worker_policy"] == {
        "schema": bench.POLICY_SCHEMA,
        "candidate_backend": "opencv-yunet-sface-cpu",
        "eligible": True,
        "purpose": "familiarity-only",
        "may_authenticate": False,
        "may_authorize_creator": False,
        "decision": "eligible-for-familiarity-review",
        "reasons": [],
    }
    assert result["comparison"]["candidate_accuracy_gain"] == 1.0


def test_results_are_json_safe_and_contain_no_biometric_authority():
    result = bench.run_benchmark(
        samples(), outcome_for, metadata(), cpu_clock_ns=clock()
    )
    encoded = bench.stable_json(result)
    restored = json.loads(encoded)

    assert restored == result
    assert restored["network_used"] is False
    assert restored["camera_used"] is False
    assert restored["models_downloaded"] is False
    assert restored["biometric_authentication_performed"] is False
    assert restored["may_authenticate"] is False
    assert restored["may_authorize_creator"] is False


def test_candidate_outcomes_are_repeated_and_must_be_deterministic():
    calls = {}

    def alternating(sample):
        calls[sample.sample_id] = calls.get(sample.sample_id, 0) + 1
        if sample.sample_id == "known" and calls[sample.sample_id] % 2 == 0:
            return bench.SampleOutcome(bench.OutcomeKind.NO_MATCH, 1, 0.1, 10)
        return outcome_for(sample, memory=10)

    result = bench.run_benchmark(
        samples(), alternating, metadata(), cpu_clock_ns=clock()
    )

    assert calls == {sample.sample_id: 2 for sample in samples()}
    assert result["candidate"]["summary"]["deterministic_outcomes"] is False
    assert result["face_worker_policy"]["eligible"] is False
    assert "deterministic_outcomes" in result["face_worker_policy"]["reasons"]


@pytest.mark.parametrize(
    "thresholds, memory, failed_gate",
    [
        (
            bench.AcceptanceThresholds(max_mean_cpu_latency_ms=1.0),
            10,
            "mean_cpu_latency_ms",
        ),
        (
            bench.AcceptanceThresholds(max_p95_cpu_latency_ms=1.0),
            10,
            "p95_cpu_latency_ms",
        ),
        (
            bench.AcceptanceThresholds(max_memory_estimate_bytes=9),
            10,
            "peak_memory_estimate_bytes",
        ),
    ],
)
def test_latency_and_memory_thresholds_fail_independently(
    thresholds, memory, failed_gate
):
    result = bench.run_benchmark(
        samples(),
        lambda sample: outcome_for(sample, memory=memory),
        metadata(),
        thresholds=thresholds,
        cpu_clock_ns=clock(),
    )

    failed = {
        gate["name"] for gate in result["acceptance_gates"] if gate["passed"] is False
    }
    assert failed_gate in failed
    assert result["face_worker_policy"]["eligible"] is False


def test_incorrect_deterministic_outcome_fails_accuracy_gate():
    def candidate(sample):
        if sample.sample_id == "unknown":
            return bench.SampleOutcome(bench.OutcomeKind.MATCH, 1, 0.8, 10)
        return outcome_for(sample, memory=10)

    result = bench.run_benchmark(
        samples(), candidate, metadata(), cpu_clock_ns=clock()
    )

    assert result["candidate"]["summary"]["outcome_accuracy"] == 0.75
    assert result["face_worker_policy"]["eligible"] is False
    assert "outcome_accuracy" in result["face_worker_policy"]["reasons"]


def test_unapproved_or_incomplete_license_metadata_fails_closed():
    result = bench.run_benchmark(
        samples(), outcome_for, metadata(approved=False), cpu_clock_ns=clock()
    )
    gate = next(
        item for item in result["acceptance_gates"] if item["name"] == "license_metadata"
    )

    assert gate["passed"] is False
    assert gate["actual"]["complete"] is True
    assert gate["actual"]["reviewed_and_approved"] is False
    assert result["face_worker_policy"]["decision"] == "keep-disabled"


def test_candidate_error_is_bounded_and_does_not_leak_exception_text():
    def failing(sample):
        if sample.sample_id == "known":
            raise RuntimeError("secret model path and token")
        return outcome_for(sample)

    result = bench.run_benchmark(
        samples(), failing, metadata(), cpu_clock_ns=clock()
    )
    known = next(
        item for item in result["candidate"]["cases"] if item["sample_id"] == "known"
    )

    assert known["error"] == "candidate-error"
    assert "secret model path" not in bench.stable_json(result)
    assert result["face_worker_policy"]["eligible"] is False


def test_candidate_failure_on_every_sample_still_emits_json_safe_report():
    def failing(_sample):
        raise RuntimeError("unavailable")

    result = bench.run_benchmark(
        samples(), failing, metadata(), cpu_clock_ns=clock()
    )

    assert result["candidate"]["summary"]["mean_cpu_latency_ms"] is None
    assert (
        result["comparison"]["candidate_minus_baseline_mean_cpu_latency_ms"]
        is None
    )
    assert result["face_worker_policy"]["decision"] == "keep-disabled"
    json.loads(bench.stable_json(result))


def test_cpu_only_and_outcome_bounds_are_enforced():
    with pytest.raises(bench.BenchmarkValidationError, match="device must be cpu"):
        bench.CandidateMetadata(
            name="gpu-candidate",
            detector_component="yunet",
            recognizer_component="sface",
            device="cuda",
            memory_estimate_method="estimate",
            licenses=metadata().licenses,
        )
    with pytest.raises(bench.BenchmarkValidationError, match="bounded score"):
        bench.SampleOutcome(bench.OutcomeKind.MATCH, 1, None, 10)
    with pytest.raises(bench.BenchmarkValidationError, match="memory_estimate"):
        bench.SampleOutcome(bench.OutcomeKind.NO_FACE, 0, None, -1)
    with pytest.raises(bench.BenchmarkValidationError, match="uses_network"):
        bench.CandidateMetadata(
            name="network-candidate",
            detector_component="yunet",
            recognizer_component="sface",
            device="cpu",
            memory_estimate_method="estimate",
            licenses=metadata().licenses,
            uses_network=True,
        )


def test_benchmark_order_and_output_are_deterministic_with_injected_clock():
    first = bench.run_benchmark(
        list(reversed(samples())), outcome_for, metadata(), cpu_clock_ns=clock()
    )
    second = bench.run_benchmark(
        samples(), outcome_for, metadata(), cpu_clock_ns=clock()
    )

    assert first["sample_ids"] == ["crowd", "empty", "known", "unknown"]
    assert bench.stable_json(first) == bench.stable_json(second)
