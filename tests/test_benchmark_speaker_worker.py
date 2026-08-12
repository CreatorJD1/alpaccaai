from __future__ import annotations

import json
import sys

import pytest

from scripts import benchmark_speaker_worker as bench


def samples() -> list[bench.BenchmarkSample]:
    return [
        bench.BenchmarkSample("known-clean", bench.OutcomeKind.FAMILIAR),
        bench.BenchmarkSample("unknown-clean", bench.OutcomeKind.UNFAMILIAR),
        bench.BenchmarkSample(
            "overlap", bench.OutcomeKind.AMBIGUOUS, bench.ScenarioKind.AMBIGUOUS
        ),
        bench.BenchmarkSample(
            "replay",
            bench.OutcomeKind.REPLAY_REJECTED,
            bench.ScenarioKind.REPLAY,
        ),
    ]


def outcome_for(
    sample: bench.BenchmarkSample, *, memory: int = 24_000_000
) -> bench.SampleOutcome:
    values = {
        "known-clean": bench.SampleOutcome(
            bench.OutcomeKind.FAMILIAR, 0.93, memory
        ),
        "unknown-clean": bench.SampleOutcome(
            bench.OutcomeKind.UNFAMILIAR, 0.14, memory
        ),
        "overlap": bench.SampleOutcome(
            bench.OutcomeKind.AMBIGUOUS, 0.70, memory
        ),
        "replay": bench.SampleOutcome(
            bench.OutcomeKind.REPLAY_REJECTED, None, memory
        ),
    }
    return values[sample.sample_id]


def metadata() -> bench.CandidateMetadata:
    return bench.CandidateMetadata(
        name="sherpa-onnx-cpu-candidate",
        backend_component="sherpa-onnx",
        device="cpu",
        memory_estimate_method="caller-measured-peak-rss",
    )


def clock(step_ns: int = 3_000_000):
    current = -step_ns

    def read() -> int:
        nonlocal current
        current += step_ns
        return current

    return read


def failed_gates(result: dict[str, object]) -> set[str]:
    return {
        str(gate["name"])
        for gate in result["acceptance_gates"]
        if gate["passed"] is False
    }


def test_module_loads_without_optional_audio_or_model_packages():
    source_names = set(bench.__dict__)
    assert "numpy" not in source_names
    assert "torch" not in source_names
    assert "sherpa_onnx" not in source_names
    assert "soundfile" not in source_names
    assert "requests" not in source_names
    assert not any(
        name == "sherpa_onnx" and value is bench for name, value in sys.modules.items()
    )


def test_passing_candidate_measures_required_semantics_and_policy():
    result = bench.run_benchmark(
        samples(), outcome_for, metadata(), cpu_clock_ns=clock()
    )

    assert result["schema"] == bench.RESULT_SCHEMA
    assert result["purpose"] == "familiarity-only"
    assert result["baseline"]["name"] == "disabled-noop"
    assert result["baseline"]["summary"]["peak_memory_estimate_bytes"] == 0
    assert result["candidate"]["summary"] == {
        "sample_count": 4,
        "correct_count": 4,
        "semantic_accuracy": 1.0,
        "deterministic_outcomes": True,
        "mean_cpu_latency_ms": 3.0,
        "p95_cpu_latency_ms": 3.0,
        "peak_memory_estimate_bytes": 24_000_000,
        "memory_estimate_source": "caller-reported",
        "ambiguous_case_count": 1,
        "ambiguous_correct_count": 1,
        "ambiguous_accuracy": 1.0,
        "replay_case_count": 1,
        "replay_safe_count": 1,
        "replay_safe_rate": 1.0,
        "replay_rejected_count": 1,
        "error_count": 0,
    }
    assert result["speaker_worker_policy"] == {
        "schema": bench.POLICY_SCHEMA,
        "candidate_backend": "sherpa-onnx-cpu-candidate",
        "eligible": True,
        "purpose": "familiarity-only",
        "may_authenticate": False,
        "may_grant_authority": False,
        "decision": "eligible-for-familiarity-review",
        "reasons": [],
    }


def test_json_report_is_content_free_and_never_authenticates():
    result = bench.run_benchmark(
        samples(), outcome_for, metadata(), cpu_clock_ns=clock()
    )
    restored = json.loads(bench.stable_json(result))

    assert restored == result
    assert restored["content_free"] is True
    assert restored["audio_loaded_by_harness"] is False
    assert restored["audio_retained"] is False
    assert restored["network_used"] is False
    assert restored["biometric_authentication_performed"] is False
    assert restored["authority_granted"] is False
    assert restored["may_authenticate"] is False
    assert restored["may_grant_authority"] is False
    forbidden_keys = {
        "audio",
        "audio_b64",
        "embedding",
        "embedding_b64",
        "identity",
        "profile_id",
        "speaker_id",
        "transcript",
    }

    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield key
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    assert forbidden_keys.isdisjoint(keys(restored))


def test_candidate_outcomes_repeat_and_nondeterminism_fails_closed():
    calls: dict[str, int] = {}

    def alternating(sample):
        calls[sample.sample_id] = calls.get(sample.sample_id, 0) + 1
        if sample.sample_id == "known-clean" and calls[sample.sample_id] % 2 == 0:
            return bench.SampleOutcome(bench.OutcomeKind.UNFAMILIAR, 0.1, 10)
        return outcome_for(sample, memory=10)

    result = bench.run_benchmark(
        samples(), alternating, metadata(), cpu_clock_ns=clock()
    )

    assert calls == {sample.sample_id: 2 for sample in samples()}
    assert result["candidate"]["summary"]["deterministic_outcomes"] is False
    assert "deterministic_outcomes" in failed_gates(result)
    assert result["speaker_worker_policy"]["eligible"] is False


@pytest.mark.parametrize(
    "thresholds, memory, failed_gate",
    [
        (
            bench.AcceptanceThresholds(max_mean_cpu_latency_ms=2.0),
            10,
            "mean_cpu_latency_ms",
        ),
        (
            bench.AcceptanceThresholds(max_p95_cpu_latency_ms=2.0),
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

    assert failed_gate in failed_gates(result)
    assert result["speaker_worker_policy"]["eligible"] is False


def test_incorrect_semantic_result_fails_accuracy_gate():
    def candidate(sample):
        if sample.sample_id == "unknown-clean":
            return bench.SampleOutcome(bench.OutcomeKind.FAMILIAR, 0.88, 10)
        return outcome_for(sample, memory=10)

    result = bench.run_benchmark(
        samples(), candidate, metadata(), cpu_clock_ns=clock()
    )

    assert result["candidate"]["summary"]["semantic_accuracy"] == 0.75
    assert "semantic_accuracy" in failed_gates(result)


def test_ambiguous_case_must_remain_ambiguous():
    def candidate(sample):
        if sample.sample_id == "overlap":
            return bench.SampleOutcome(bench.OutcomeKind.FAMILIAR, 0.83, 10)
        return outcome_for(sample, memory=10)

    result = bench.run_benchmark(
        samples(), candidate, metadata(), cpu_clock_ns=clock()
    )

    assert result["candidate"]["summary"]["ambiguous_accuracy"] == 0.0
    assert "ambiguous_accuracy" in failed_gates(result)
    assert result["may_authenticate"] is False


def test_replay_reported_as_familiar_fails_replay_safety():
    def candidate(sample):
        if sample.sample_id == "replay":
            return bench.SampleOutcome(bench.OutcomeKind.FAMILIAR, 0.99, 10)
        return outcome_for(sample, memory=10)

    result = bench.run_benchmark(
        samples(), candidate, metadata(), cpu_clock_ns=clock()
    )

    assert result["candidate"]["summary"]["replay_safe_rate"] == 0.0
    assert result["candidate"]["summary"]["replay_rejected_count"] == 0
    assert "replay_safe_rate" in failed_gates(result)
    assert result["speaker_worker_policy"]["decision"] == "keep-disabled"


def test_missing_ambiguous_or_replay_coverage_fails_closed():
    simple = [bench.BenchmarkSample("known", bench.OutcomeKind.FAMILIAR)]
    result = bench.run_benchmark(
        simple,
        lambda _sample: bench.SampleOutcome(bench.OutcomeKind.FAMILIAR, 0.9, 10),
        metadata(),
        cpu_clock_ns=clock(),
    )

    failed = failed_gates(result)
    assert "ambiguous_fixture_coverage" in failed
    assert "ambiguous_accuracy" in failed
    assert "replay_fixture_coverage" in failed
    assert "replay_safe_rate" in failed


def test_reduced_fixture_set_is_allowed_only_when_explicitly_configured():
    simple = [bench.BenchmarkSample("known", bench.OutcomeKind.FAMILIAR)]
    result = bench.run_benchmark(
        simple,
        lambda _sample: bench.SampleOutcome(bench.OutcomeKind.FAMILIAR, 0.9, 10),
        metadata(),
        thresholds=bench.AcceptanceThresholds(
            require_ambiguous_fixture=False,
            require_replay_fixture=False,
        ),
        cpu_clock_ns=clock(),
    )

    assert result["speaker_worker_policy"]["eligible"] is True
    assert failed_gates(result) == set()


def test_candidate_error_is_bounded_and_exception_text_is_not_reported():
    def failing(sample):
        if sample.sample_id == "known-clean":
            raise RuntimeError("private audio path and credential")
        return outcome_for(sample)

    result = bench.run_benchmark(
        samples(), failing, metadata(), cpu_clock_ns=clock()
    )
    encoded = bench.stable_json(result)
    known = next(
        item
        for item in result["candidate"]["cases"]
        if item["sample_id"] == "known-clean"
    )

    assert known["error"] == "candidate-error"
    assert "private audio path" not in encoded
    assert result["speaker_worker_policy"]["eligible"] is False


def test_cpu_only_and_non_authoritative_metadata_are_enforced():
    with pytest.raises(bench.BenchmarkValidationError, match="device must be cpu"):
        bench.CandidateMetadata(
            "gpu", "sherpa-onnx", "cuda", "estimate"
        )
    with pytest.raises(bench.BenchmarkValidationError, match="grants_authority"):
        bench.CandidateMetadata(
            "unsafe", "sherpa-onnx", "cpu", "estimate", grants_authority=True
        )
    with pytest.raises(bench.BenchmarkValidationError, match="retains_audio"):
        bench.CandidateMetadata(
            "unsafe", "sherpa-onnx", "cpu", "estimate", retains_audio=True
        )
    with pytest.raises(bench.BenchmarkValidationError, match="bounded score"):
        bench.SampleOutcome(bench.OutcomeKind.FAMILIAR, None, 10)
    with pytest.raises(bench.BenchmarkValidationError, match="memory_estimate"):
        bench.SampleOutcome(bench.OutcomeKind.UNFAMILIAR, 0.1, -1)


def test_order_and_output_are_deterministic_with_injected_clock():
    first = bench.run_benchmark(
        list(reversed(samples())), outcome_for, metadata(), cpu_clock_ns=clock()
    )
    second = bench.run_benchmark(
        samples(), outcome_for, metadata(), cpu_clock_ns=clock()
    )

    assert first["sample_ids"] == [
        "known-clean",
        "overlap",
        "replay",
        "unknown-clean",
    ]
    assert bench.stable_json(first) == bench.stable_json(second)


def test_dry_run_cli_emits_a_passing_content_free_report(capsys):
    assert bench.main(["--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["mode"] == "caller-injected"
    assert result["content_free"] is True
    assert result["candidate"]["summary"]["sample_count"] == 5
    assert result["candidate"]["summary"]["ambiguous_case_count"] == 1
    assert result["candidate"]["summary"]["replay_case_count"] == 1
    assert result["speaker_worker_policy"]["eligible"] is True
