from __future__ import annotations

import importlib
import json

import pytest

from scripts import benchmark_streaming_asr as bench


def _case(case_id: str = "clean", *, interrupt: float | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "case_id": case_id,
        "reference_text": "Hello Alpecca, start the quiet room check",
        "audio_duration_ms": 1_800,
    }
    if interrupt is not None:
        value["interrupt_at_ms"] = interrupt
    return value


def _run(
    *,
    partial_ms: float = 240,
    final_ms: float = 900,
    transcript: str = "Hello Alpecca, start the quiet room check",
    cpu: float = 48,
    interruption: dict[str, object] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "events": [
            {
                "kind": "partial",
                "at_ms": partial_ms,
                "text": "hello alpecca",
                "cpu_percent_estimate": cpu / 2,
            },
            {
                "kind": "final",
                "at_ms": final_ms,
                "text": transcript,
                "cpu_percent_estimate": cpu,
            },
        ]
    }
    if interruption is not None:
        value["interruption"] = interruption
    return value


def _fixture(*, interrupted: bool = False) -> dict[str, object]:
    case = _case("interrupt", interrupt=500) if interrupted else _case()
    case_id = str(case["case_id"])
    interruption = (
        {
            "requested_at_ms": 500,
            "acknowledged_at_ms": 540,
            "recovered_final_at_ms": 1_100,
            "stale_output_after_interrupt": False,
        }
        if interrupted
        else None
    )
    return {
        "schema": bench.FIXTURE_SCHEMA,
        "gates": {
            "max_first_partial_latency_ms": 600,
            "max_final_latency_ms": 2_000,
            "max_transcript_error_proxy": 0.2,
            "max_cpu_peak_percent": 100,
            "max_interruption_recovery_ms": 800,
            "require_partial": True,
            "require_interruption_recovery": True,
        },
        "cases": [case],
        "backends": {
            "faster-whisper": {
                "available": True,
                "runs": {
                    case_id: _run(
                        interruption=dict(interruption) if interruption is not None else None
                    )
                },
            },
            "moonshine": {
                "available": True,
                "runs": {
                    case_id: _run(
                        partial_ms=180,
                        final_ms=760,
                        cpu=42,
                        interruption=dict(interruption) if interruption is not None else None,
                    )
                },
            },
        },
    }


def _load(tmp_path, document):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return bench.load_fixture(path)


def test_transcript_error_proxy_is_normalized_deterministic_and_capped():
    assert bench.normalize_transcript("Hello, ALPECCA! It's me.") == (
        "hello",
        "alpecca",
        "it's",
        "me",
    )
    assert bench.transcript_error_proxy("one two three four", "one two tree four") == 0.25
    assert bench.transcript_error_proxy("one", "many unrelated inserted words") == 1.0
    assert bench.transcript_error_proxy("same words", "same words") == 0.0


def test_dry_run_fixture_produces_complete_deterministic_pass_schema(tmp_path):
    cases, backends, gates = _load(tmp_path, _fixture())

    first = bench.run_benchmark(cases, backends, gates=gates)
    second = bench.run_benchmark(cases, backends, gates=gates)

    assert bench.stable_json(first) == bench.stable_json(second)
    assert first["schema"] == bench.RESULT_SCHEMA
    assert first["production_selection_changed"] is False
    assert first["case_ids"] == ["clean"]
    assert [item["name"] for item in first["backends"]] == ["faster-whisper", "moonshine"]
    assert all(item["passed"] is True for item in first["backends"])
    assert first["comparison"] == {
        "baseline": "faster-whisper",
        "candidate": "moonshine",
        "baseline_passed": True,
        "candidate_passed": True,
        "candidate_eligible_for_separate_review": True,
        "recommendation": "review-candidate-evidence",
    }
    metrics = first["backends"][1]["cases"][0]["metrics"]
    assert metrics == {
        "first_partial_latency_ms": 180.0,
        "final_latency_ms": 760.0,
        "transcript_error_proxy": 0.0,
        "cpu_peak_percent_estimate": 42.0,
        "interruption_recovery_ms": None,
    }


def test_interruption_recovery_and_stale_output_have_explicit_gates(tmp_path):
    document = _fixture(interrupted=True)
    moonshine = document["backends"]["moonshine"]["runs"]["interrupt"]
    moonshine["interruption"]["stale_output_after_interrupt"] = True
    cases, backends, gates = _load(tmp_path, document)

    result = bench.run_benchmark(cases, backends, gates=gates)
    by_name = {item["name"]: item for item in result["backends"]}

    assert by_name["faster-whisper"]["passed"] is True
    assert by_name["faster-whisper"]["cases"][0]["metrics"]["interruption_recovery_ms"] == 600.0
    assert by_name["moonshine"]["passed"] is False
    stale_gate = next(
        gate
        for gate in by_name["moonshine"]["cases"][0]["gates"]
        if gate["name"] == "stale_output_after_interrupt"
    )
    assert stale_gate["passed"] is False
    assert result["comparison"]["recommendation"] == "keep-current-production-selection"


def test_missing_partial_and_final_fail_required_gates(tmp_path):
    document = _fixture()
    document["backends"]["moonshine"]["runs"]["clean"]["events"] = [
        {"kind": "partial", "at_ms": 100, "text": "", "cpu_percent_estimate": 10}
    ]
    cases, backends, gates = _load(tmp_path, document)

    result = bench.run_benchmark(cases, backends, gates=gates)
    moonshine = next(item for item in result["backends"] if item["name"] == "moonshine")
    checks = {gate["name"]: gate for gate in moonshine["cases"][0]["gates"]}

    assert moonshine["passed"] is False
    assert checks["first_partial_latency_ms"]["reason"] == "missing"
    assert checks["final_latency_ms"]["reason"] == "missing"
    assert checks["transcript_error_proxy"]["reason"] == "missing"


def test_each_metric_can_fail_its_own_limit(tmp_path):
    document = _fixture()
    document["backends"]["moonshine"]["runs"]["clean"] = _run(
        partial_ms=900,
        final_ms=3_500,
        transcript="completely different words",
        cpu=250,
    )
    cases, backends, gates = _load(tmp_path, document)

    result = bench.run_benchmark(cases, backends, gates=gates)
    moonshine = next(item for item in result["backends"] if item["name"] == "moonshine")
    failed = {
        gate["name"] for gate in moonshine["cases"][0]["gates"] if gate["passed"] is False
    }

    assert failed == {
        "first_partial_latency_ms",
        "final_latency_ms",
        "transcript_error_proxy",
        "cpu_peak_percent_estimate",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda document: document.update(schema="wrong"),
        lambda document: document["cases"][0].update(audio_duration_ms=-1),
        lambda document: document["backends"]["moonshine"]["runs"]["clean"]["events"].reverse(),
        lambda document: document["gates"].update(require_partial="yes"),
    ],
)
def test_invalid_fixture_contract_is_rejected(tmp_path, mutate):
    document = _fixture()
    mutate(document)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(bench.BenchmarkValidationError):
        bench.load_fixture(path)


def test_unavailable_fixture_backend_is_reported_without_running_models(tmp_path):
    document = _fixture()
    document["backends"]["moonshine"] = {"available": False, "runs": {}}
    cases, backends, gates = _load(tmp_path, document)

    result = bench.run_benchmark(cases, backends, gates=gates)
    moonshine = next(item for item in result["backends"] if item["name"] == "moonshine")

    assert moonshine["status"]["available"] is False
    assert moonshine["cases"] == []
    assert moonshine["passed"] is False
    assert result["production_selection_changed"] is False


def test_optional_backend_is_discovered_without_import_and_loaded_on_first_run(monkeypatch):
    imported = []
    delegate = bench.DryRunBackend(
        "moonshine",
        {"clean": bench.BackendRun.from_mapping(_run(), run_name="moonshine/clean")},
    )
    monkeypatch.setattr(
        bench.importlib.util,
        "find_spec",
        lambda name: object() if name == "moonshine_onnx" else None,
    )
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: imported.append(name) or object(),
    )
    backend = bench.LazyOptionalBackend(
        "moonshine", ("moonshine_onnx", "moonshine"), lambda _module: delegate
    )

    assert backend.status()["loaded"] is False
    assert imported == []
    run = backend.run(bench.BenchmarkCase.from_mapping(_case()))
    assert run.events[-1].kind == "final"
    assert imported == ["moonshine_onnx"]
    assert backend.status()["loaded"] is True


def test_missing_optional_backend_never_imports(monkeypatch):
    imported = []
    monkeypatch.setattr(bench.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(importlib, "import_module", lambda name: imported.append(name))
    backend = bench.LazyOptionalBackend(
        "faster-whisper",
        ("faster_whisper",),
        lambda _module: pytest.fail("factory must not run"),
    )

    assert backend.status()["available"] is False
    with pytest.raises(bench.BackendUnavailable):
        backend.run(bench.BenchmarkCase.from_mapping(_case()))
    assert imported == []


def test_cli_fixture_writes_one_stable_json_result(tmp_path, capsys):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(_fixture()), encoding="utf-8")

    assert bench.main(["--fixture", str(path)]) == 0
    output = capsys.readouterr().out.strip()
    result = json.loads(output)

    assert output == bench.stable_json(result)
    assert result["schema"] == bench.RESULT_SCHEMA
    assert result["mode"] == "fixture"
    assert result["production_selection_changed"] is False


def test_probe_schema_never_claims_or_changes_production_selection(monkeypatch):
    monkeypatch.setattr(bench.importlib.util, "find_spec", lambda _name: None)

    result = bench.optional_backend_status()

    assert result["schema"] == bench.BACKEND_STATUS_SCHEMA
    assert result["production_selection_changed"] is False
    assert [item["name"] for item in result["backends"]] == [
        "faster-whisper",
        "moonshine",
    ]
    assert all(item["loaded"] is False for item in result["backends"])
