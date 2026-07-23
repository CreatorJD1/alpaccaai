from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import benchmark_research_runtime as bench


def stepped_clock(step_ms: float = 0.5):
    step_ns = int(step_ms * 1_000_000)
    current = -step_ns

    def read() -> int:
        nonlocal current
        current += step_ns
        return current

    return read


def small_config(**overrides: object) -> bench.BenchmarkConfig:
    values: dict[str, object] = {
        "seed": 42,
        "correction_cases": 2,
        "supersession_cases": 2,
        "retrieval_scales": (4, 16),
        "retrieval_queries": 3,
        "observer_updates": 5,
        "stale_attempts": 3,
        "max_retrieval_latency_ms": 2.0,
    }
    values.update(overrides)
    return bench.BenchmarkConfig(**values)  # type: ignore[arg-type]


def run_small(**config_overrides: object) -> dict[str, object]:
    return bench.run_benchmark(
        small_config(**config_overrides),
        latency_clock_ns=stepped_clock(),
    )


def test_temporal_accuracy_provenance_and_no_invention_gates_pass() -> None:
    result = run_small()
    temporal = result["temporal_memory"]
    assert isinstance(temporal, dict)
    relations = temporal["relation_accuracy"]

    assert result["schema"] == bench.RESULT_SCHEMA
    assert result["mode"] == "evaluation-only"
    assert result["passed"] is True
    assert relations["correction"] == {
        "expected": 2,
        "correct": 2,
        "accuracy": 1.0,
        "passed": True,
    }
    assert relations["supersession"] == {
        "expected": 2,
        "correct": 2,
        "accuracy": 1.0,
        "passed": True,
    }
    assert temporal["provenance"] == {
        "facts_checked": 8,
        "missing_evidence": 0,
        "provenance_mismatches": 0,
        "passed": True,
    }
    assert temporal["no_invention"]["invented_fact_count"] == 0
    assert temporal["no_invention"]["observed_fact_count"] == 8
    assert temporal["no_invention"]["passed"] is True


def test_retrieval_is_measured_at_each_seeded_scale_and_is_gateable() -> None:
    result = run_small()
    retrieval = result["temporal_memory"]["retrieval"]
    scales = retrieval["scales"]

    assert [item["seeded_fact_count"] for item in scales] == [4, 16]
    assert [item["query_count"] for item in scales] == [3, 3]
    assert all(item["accuracy"] == 1.0 for item in scales)
    assert all(item["latency_ms"] == {"mean": 0.5, "p95": 0.5, "max": 0.5} for item in scales)
    assert retrieval["all_scales_passed"] is True

    failed = bench.run_benchmark(
        small_config(max_retrieval_latency_ms=0.25),
        latency_clock_ns=stepped_clock(),
    )
    failed_gate = next(
        gate
        for gate in failed["acceptance_gates"]
        if gate["name"] == "bounded_retrieval_latency"
    )
    assert failed_gate["passed"] is False
    assert failed["passed"] is False


def test_observer_coalescing_keeps_latest_value_and_bounds_queue() -> None:
    observers = run_small()["observer_runtime"]
    coalescing = observers["coalescing"]

    assert coalescing == {
        "updates": 5,
        "queued_tasks": 1,
        "new_tasks_accepted": 1,
        "coalesced_updates": 4,
        "latest_value": 4,
        "passed": True,
    }


def test_stale_observer_results_are_rejected_without_replacing_latest() -> None:
    stale = run_small()["observer_runtime"]["stale_result_rejection"]

    assert stale == {
        "attempts": 3,
        "rejected": 3,
        "latest_preserved": True,
        "passed": True,
    }


def test_duplicate_suppression_reports_queue_scope_and_durable_idempotency() -> None:
    duplicate = run_small()["temporal_memory"]["duplicate_suppression"]

    assert duplicate["scope"] == "pending-queue-and-durable-storage"
    assert duplicate["queued_duplicate_suppressed"] is True
    assert duplicate["pending_after_duplicate"] == 1
    assert duplicate["durable_replay_requeued_for_idempotent_processing"] is True
    assert duplicate["durable_replay_idempotent"] is True
    assert duplicate["facts_before_replay"] == duplicate["facts_after_replay"] == 1
    assert duplicate["passed"] is True


def test_every_database_is_owned_by_one_deleted_temporary_root(monkeypatch) -> None:
    created: list[Path] = []
    original_store = bench.TemporalMemoryStore

    class RecordingStore(original_store):
        def __init__(self, db_path: Path) -> None:
            created.append(Path(db_path))
            super().__init__(db_path)

    monkeypatch.setattr(bench, "TemporalMemoryStore", RecordingStore)
    result = run_small()

    assert len(created) == 4
    roots = {path.parent for path in created}
    assert len(roots) == 1
    root = roots.pop()
    assert root.name.startswith("alpecca-research-runtime-")
    assert not root.exists()
    assert all(not path.exists() for path in created)
    assert result["safeguards"] == {
        "temporary_databases_only": True,
        "temporary_databases_removed_after_run": True,
        "production_database_used": False,
        "production_defaults_changed": False,
        "network_used": False,
        "model_calls": 0,
        "optional_packages_imported_by_harness": False,
    }
    assert str(root) not in bench.stable_json(result)


def test_seeded_result_is_stable_with_an_injected_clock() -> None:
    first = bench.run_benchmark(
        small_config(retrieval_scales=(16, 4)),
        latency_clock_ns=stepped_clock(),
    )
    second = run_small()

    assert bench.stable_json(first) == bench.stable_json(second)
    assert json.loads(bench.stable_json(first)) == first


def test_bounds_and_clock_contract_fail_closed() -> None:
    with pytest.raises(bench.BenchmarkValidationError, match="retrieval scales"):
        small_config(retrieval_scales=(bench.MAX_RETRIEVAL_SCALE + 1,))
    with pytest.raises(bench.BenchmarkValidationError, match="observer_updates"):
        small_config(observer_updates=1)

    def backwards_clock() -> int:
        backwards_clock.value -= 1
        return backwards_clock.value

    backwards_clock.value = 10
    with pytest.raises(bench.BenchmarkValidationError, match="monotonic"):
        bench.run_benchmark(small_config(), latency_clock_ns=backwards_clock)


def test_harness_has_no_optional_runtime_dependency_or_external_side_effect() -> None:
    names = set(bench.__dict__)
    assert not names.intersection(
        {"requests", "httpx", "numpy", "torch", "cv2", "state_store", "config"}
    )
    result = run_small()
    assert result["safeguards"]["network_used"] is False
    assert result["safeguards"]["model_calls"] == 0
    assert result["safeguards"]["production_defaults_changed"] is False


def test_direct_script_entrypoint_runs_from_the_repository_root() -> None:
    script = Path(bench.__file__).resolve()
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--seed",
            "42",
            "--correction-cases",
            "1",
            "--supersession-cases",
            "1",
            "--scales",
            "2",
            "--queries",
            "1",
            "--observer-updates",
            "2",
            "--stale-attempts",
            "1",
            "--max-retrieval-ms",
            "10000",
        ],
        cwd=script.parents[1],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["schema"] == bench.RESULT_SCHEMA
    assert result["passed"] is True
