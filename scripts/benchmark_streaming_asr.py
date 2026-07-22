"""Offline Moonshine versus faster-whisper streaming ASR benchmark harness.

This module is evaluation-only. It does not import production voice modules,
select an ASR backend, retain audio, or change runtime defaults. Backends emit a
small stream of benchmark observations; dry-run fixtures exercise the complete
schema and gate path without installing or loading either model family.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import importlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
from typing import Protocol


FIXTURE_SCHEMA = "alpecca.streaming-asr.fixture.v1"
RESULT_SCHEMA = "alpecca.streaming-asr.benchmark-result.v1"
BACKEND_STATUS_SCHEMA = "alpecca.streaming-asr.backend-status.v1"
GATE_SCHEMA = "alpecca.streaming-asr.gates.v1"

BASELINE_BACKEND = "faster-whisper"
CANDIDATE_BACKEND = "moonshine"
MAX_CASES = 128
MAX_EVENTS_PER_RUN = 512
MAX_REFERENCE_CHARS = 8_000
MAX_TRANSCRIPT_CHARS = 16_000
MAX_AUDIO_DURATION_MS = 120_000.0
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")


class BenchmarkValidationError(ValueError):
    pass


class BackendUnavailable(RuntimeError):
    pass


def _finite_number(
    value: object,
    *,
    name: str,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkValidationError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise BenchmarkValidationError(f"{name} is outside its allowed range")
    if maximum is not None and number > maximum:
        raise BenchmarkValidationError(f"{name} is outside its allowed range")
    return number


def _optional_number(
    value: object,
    *,
    name: str,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float | None:
    if value is None:
        return None
    return _finite_number(value, name=name, minimum=minimum, maximum=maximum)


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise BenchmarkValidationError(f"{name} is invalid")
    return value


def _text(value: object, *, name: str, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise BenchmarkValidationError(f"{name} must be text")
    clean = " ".join(value.split())
    if (not clean and not allow_empty) or len(clean) > maximum:
        raise BenchmarkValidationError(f"{name} is invalid")
    return clean


@dataclass(frozen=True, slots=True)
class GatePolicy:
    max_first_partial_latency_ms: float = 800.0
    max_final_latency_ms: float = 3_000.0
    max_transcript_error_proxy: float = 0.25
    max_cpu_peak_percent: float = 200.0
    max_interruption_recovery_ms: float = 1_500.0
    require_partial: bool = True
    require_interruption_recovery: bool = True

    @classmethod
    def from_mapping(cls, value: object) -> "GatePolicy":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise BenchmarkValidationError("gates must be an object")
        return cls(
            max_first_partial_latency_ms=_finite_number(
                value.get("max_first_partial_latency_ms", 800.0),
                name="max_first_partial_latency_ms",
            ),
            max_final_latency_ms=_finite_number(
                value.get("max_final_latency_ms", 3_000.0), name="max_final_latency_ms"
            ),
            max_transcript_error_proxy=_finite_number(
                value.get("max_transcript_error_proxy", 0.25),
                name="max_transcript_error_proxy",
                maximum=1.0,
            ),
            max_cpu_peak_percent=_finite_number(
                value.get("max_cpu_peak_percent", 200.0), name="max_cpu_peak_percent"
            ),
            max_interruption_recovery_ms=_finite_number(
                value.get("max_interruption_recovery_ms", 1_500.0),
                name="max_interruption_recovery_ms",
            ),
            require_partial=_strict_bool(value.get("require_partial", True), "require_partial"),
            require_interruption_recovery=_strict_bool(
                value.get("require_interruption_recovery", True),
                "require_interruption_recovery",
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": GATE_SCHEMA,
            "max_first_partial_latency_ms": self.max_first_partial_latency_ms,
            "max_final_latency_ms": self.max_final_latency_ms,
            "max_transcript_error_proxy": self.max_transcript_error_proxy,
            "max_cpu_peak_percent": self.max_cpu_peak_percent,
            "max_interruption_recovery_ms": self.max_interruption_recovery_ms,
            "require_partial": self.require_partial,
            "require_interruption_recovery": self.require_interruption_recovery,
        }


def _strict_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise BenchmarkValidationError(f"{name} must be a boolean")
    return value


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    reference_text: str
    audio_duration_ms: float
    audio_path: Path | None = None
    interrupt_at_ms: float | None = None

    @classmethod
    def from_mapping(cls, value: object, *, fixture_root: Path | None = None) -> "BenchmarkCase":
        if not isinstance(value, Mapping):
            raise BenchmarkValidationError("case must be an object")
        case_id = _identifier(value.get("case_id"), name="case_id")
        duration = _finite_number(
            value.get("audio_duration_ms"),
            name=f"case {case_id} audio_duration_ms",
            minimum=1.0,
            maximum=MAX_AUDIO_DURATION_MS,
        )
        interrupt = _optional_number(
            value.get("interrupt_at_ms"),
            name=f"case {case_id} interrupt_at_ms",
            minimum=0.0,
            maximum=duration,
        )
        raw_path = value.get("audio_path")
        audio_path = None
        if raw_path is not None:
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise BenchmarkValidationError(f"case {case_id} audio_path is invalid")
            path = Path(raw_path)
            audio_path = (fixture_root / path).resolve() if fixture_root else path.resolve()
        return cls(
            case_id=case_id,
            reference_text=_text(
                value.get("reference_text"),
                name=f"case {case_id} reference_text",
                maximum=MAX_REFERENCE_CHARS,
            ),
            audio_duration_ms=duration,
            audio_path=audio_path,
            interrupt_at_ms=interrupt,
        )


@dataclass(frozen=True, slots=True)
class AsrEvent:
    kind: str
    at_ms: float
    text: str
    cpu_percent_estimate: float

    @classmethod
    def from_mapping(cls, value: object, *, run_name: str) -> "AsrEvent":
        if not isinstance(value, Mapping):
            raise BenchmarkValidationError(f"{run_name} event must be an object")
        kind = str(value.get("kind") or "")
        if kind not in {"partial", "final"}:
            raise BenchmarkValidationError(f"{run_name} event kind is invalid")
        return cls(
            kind=kind,
            at_ms=_finite_number(value.get("at_ms"), name=f"{run_name} event at_ms"),
            text=_text(
                value.get("text", ""),
                name=f"{run_name} event text",
                maximum=MAX_TRANSCRIPT_CHARS,
                allow_empty=True,
            ),
            cpu_percent_estimate=_finite_number(
                value.get("cpu_percent_estimate", 0.0),
                name=f"{run_name} event cpu_percent_estimate",
                maximum=10_000.0,
            ),
        )


@dataclass(frozen=True, slots=True)
class InterruptionTrace:
    requested_at_ms: float
    acknowledged_at_ms: float
    recovered_final_at_ms: float
    stale_output_after_interrupt: bool

    @classmethod
    def from_mapping(cls, value: object, *, run_name: str) -> "InterruptionTrace | None":
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise BenchmarkValidationError(f"{run_name} interruption must be an object")
        requested = _finite_number(
            value.get("requested_at_ms"), name=f"{run_name} interruption requested_at_ms"
        )
        acknowledged = _finite_number(
            value.get("acknowledged_at_ms"),
            name=f"{run_name} interruption acknowledged_at_ms",
            minimum=requested,
        )
        recovered = _finite_number(
            value.get("recovered_final_at_ms"),
            name=f"{run_name} interruption recovered_final_at_ms",
            minimum=acknowledged,
        )
        return cls(
            requested_at_ms=requested,
            acknowledged_at_ms=acknowledged,
            recovered_final_at_ms=recovered,
            stale_output_after_interrupt=_strict_bool(
                value.get("stale_output_after_interrupt", False),
                f"{run_name} stale_output_after_interrupt",
            ),
        )


@dataclass(frozen=True, slots=True)
class BackendRun:
    events: tuple[AsrEvent, ...]
    interruption: InterruptionTrace | None = None

    @classmethod
    def from_mapping(cls, value: object, *, run_name: str) -> "BackendRun":
        if not isinstance(value, Mapping):
            raise BenchmarkValidationError(f"{run_name} must be an object")
        raw_events = value.get("events")
        if not isinstance(raw_events, list) or not 1 <= len(raw_events) <= MAX_EVENTS_PER_RUN:
            raise BenchmarkValidationError(f"{run_name} events are invalid")
        events = tuple(AsrEvent.from_mapping(item, run_name=run_name) for item in raw_events)
        if any(right.at_ms < left.at_ms for left, right in zip(events, events[1:])):
            raise BenchmarkValidationError(f"{run_name} events are not chronological")
        return cls(
            events=events,
            interruption=InterruptionTrace.from_mapping(
                value.get("interruption"), run_name=run_name
            ),
        )


class BenchmarkBackend(Protocol):
    name: str

    def status(self) -> Mapping[str, object]: ...

    def run(self, case: BenchmarkCase) -> BackendRun: ...


class DryRunBackend:
    def __init__(self, name: str, runs: Mapping[str, BackendRun], *, available: bool = True) -> None:
        self.name = _identifier(name, name="backend name")
        self._runs = dict(runs)
        self._available = bool(available)

    def status(self) -> Mapping[str, object]:
        return {
            "available": self._available,
            "loaded": True,
            "mode": "dry-run",
            "device": "cpu",
        }

    def run(self, case: BenchmarkCase) -> BackendRun:
        if not self._available:
            raise BackendUnavailable(f"{self.name} is unavailable")
        try:
            return self._runs[case.case_id]
        except KeyError as exc:
            raise BackendUnavailable(f"{self.name} has no run for {case.case_id}") from exc


class LazyOptionalBackend:
    """Load an optional backend only when its first benchmark case runs."""

    def __init__(
        self,
        name: str,
        module_names: Sequence[str],
        factory: Callable[[object], BenchmarkBackend],
    ) -> None:
        self.name = _identifier(name, name="backend name")
        if not module_names or not all(isinstance(item, str) and item for item in module_names):
            raise ValueError("module_names must be non-empty strings")
        if not callable(factory):
            raise TypeError("factory must be callable")
        self._module_names = tuple(module_names)
        self._factory = factory
        self._delegate: BenchmarkBackend | None = None
        self._load_error = ""

    def _discover(self) -> str | None:
        for name in self._module_names:
            try:
                if importlib.util.find_spec(name) is not None:
                    return name
            except (ImportError, ValueError):
                continue
        return None

    def status(self) -> Mapping[str, object]:
        module = self._discover()
        return {
            "available": module is not None,
            "loaded": self._delegate is not None,
            "mode": "optional-lazy",
            "device": "cpu",
            "module": module or "",
            "load_error": self._load_error,
        }

    def _load(self) -> BenchmarkBackend:
        if self._delegate is not None:
            return self._delegate
        module_name = self._discover()
        if module_name is None:
            raise BackendUnavailable(f"{self.name} package is not installed")
        try:
            module = importlib.import_module(module_name)
            delegate = self._factory(module)
            if delegate.name != self.name:
                raise ValueError("backend factory returned the wrong backend name")
            status = delegate.status()
            if status.get("device") != "cpu":
                raise ValueError("benchmark backend must be CPU-only")
            self._delegate = delegate
            return delegate
        except Exception as exc:
            self._load_error = type(exc).__name__
            raise BackendUnavailable(f"{self.name} could not be loaded") from exc

    def run(self, case: BenchmarkCase) -> BackendRun:
        return self._load().run(case)


def optional_backend_status() -> dict[str, object]:
    def discover(names: Sequence[str]) -> str:
        for name in names:
            try:
                if importlib.util.find_spec(name) is not None:
                    return name
            except (ImportError, ValueError):
                continue
        return ""

    faster = discover(("faster_whisper",))
    moonshine = discover(("moonshine_onnx", "moonshine"))
    return {
        "schema": BACKEND_STATUS_SCHEMA,
        "production_selection_changed": False,
        "backends": [
            {
                "name": BASELINE_BACKEND,
                "available": bool(faster),
                "module": faster,
                "loaded": False,
                "device": "cpu",
            },
            {
                "name": CANDIDATE_BACKEND,
                "available": bool(moonshine),
                "module": moonshine,
                "loaded": False,
                "device": "cpu",
            },
        ],
    }


def normalize_transcript(value: str) -> tuple[str, ...]:
    return tuple(_WORD_RE.findall(value.casefold()))


def transcript_error_proxy(reference: str, transcript: str) -> float:
    """Return a deterministic, capped word-edit-distance proxy in [0, 1]."""

    expected = normalize_transcript(reference)
    observed = normalize_transcript(transcript)
    if not expected:
        return 0.0 if not observed else 1.0
    previous = list(range(len(observed) + 1))
    for row, expected_word in enumerate(expected, start=1):
        current = [row]
        for column, observed_word in enumerate(observed, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected_word != observed_word),
                )
            )
        previous = current
    return round(min(1.0, previous[-1] / len(expected)), 6)


def _gate(
    *, name: str, actual: float | None, limit: float, required: bool = True
) -> dict[str, object]:
    if actual is None:
        return {
            "name": name,
            "actual": None,
            "limit": limit,
            "required": required,
            "passed": not required,
            "reason": "missing" if required else "not-applicable",
        }
    passed = actual <= limit
    return {
        "name": name,
        "actual": actual,
        "limit": limit,
        "required": required,
        "passed": passed,
        "reason": "within-limit" if passed else "limit-exceeded",
    }


def evaluate_run(
    case: BenchmarkCase, backend_name: str, run: BackendRun, gates: GatePolicy
) -> dict[str, object]:
    partial = next((event for event in run.events if event.kind == "partial" and event.text), None)
    finals = [event for event in run.events if event.kind == "final" and event.text]
    final = finals[-1] if finals else None
    cpu_peak = max((event.cpu_percent_estimate for event in run.events), default=0.0)
    error = transcript_error_proxy(case.reference_text, final.text) if final else None

    interruption_required = case.interrupt_at_ms is not None and gates.require_interruption_recovery
    recovery_ms = None
    interruption_consistent = True
    stale_output = False
    if run.interruption is not None:
        recovery_ms = round(
            run.interruption.recovered_final_at_ms - run.interruption.requested_at_ms, 6
        )
        stale_output = run.interruption.stale_output_after_interrupt
        if case.interrupt_at_ms is None:
            interruption_consistent = False
        else:
            interruption_consistent = math.isclose(
                run.interruption.requested_at_ms, case.interrupt_at_ms, abs_tol=0.001
            )
    elif case.interrupt_at_ms is not None:
        interruption_consistent = False

    checks = [
        _gate(
            name="first_partial_latency_ms",
            actual=partial.at_ms if partial else None,
            limit=gates.max_first_partial_latency_ms,
            required=gates.require_partial,
        ),
        _gate(
            name="final_latency_ms",
            actual=final.at_ms if final else None,
            limit=gates.max_final_latency_ms,
        ),
        _gate(
            name="transcript_error_proxy",
            actual=error,
            limit=gates.max_transcript_error_proxy,
        ),
        _gate(
            name="cpu_peak_percent_estimate",
            actual=round(cpu_peak, 6),
            limit=gates.max_cpu_peak_percent,
        ),
        _gate(
            name="interruption_recovery_ms",
            actual=recovery_ms,
            limit=gates.max_interruption_recovery_ms,
            required=interruption_required,
        ),
    ]
    if case.interrupt_at_ms is not None:
        checks.extend(
            [
                {
                    "name": "interruption_trace_consistent",
                    "actual": interruption_consistent,
                    "limit": True,
                    "required": True,
                    "passed": interruption_consistent,
                    "reason": "consistent" if interruption_consistent else "missing-or-mismatched",
                },
                {
                    "name": "stale_output_after_interrupt",
                    "actual": stale_output,
                    "limit": False,
                    "required": True,
                    "passed": not stale_output,
                    "reason": "none" if not stale_output else "stale-output-observed",
                },
            ]
        )
    passed = all(bool(check["passed"]) for check in checks)
    return {
        "case_id": case.case_id,
        "backend": backend_name,
        "passed": passed,
        "metrics": {
            "first_partial_latency_ms": partial.at_ms if partial else None,
            "final_latency_ms": final.at_ms if final else None,
            "transcript_error_proxy": error,
            "cpu_peak_percent_estimate": round(cpu_peak, 6),
            "interruption_recovery_ms": recovery_ms,
        },
        "interruption": {
            "required": case.interrupt_at_ms is not None,
            "trace_consistent": interruption_consistent,
            "stale_output_after_interrupt": stale_output,
        },
        "gates": checks,
    }


def _summary(cases: Sequence[Mapping[str, object]]) -> dict[str, object]:
    metric_names = (
        "first_partial_latency_ms",
        "final_latency_ms",
        "transcript_error_proxy",
        "cpu_peak_percent_estimate",
        "interruption_recovery_ms",
    )
    maxima: dict[str, float | None] = {}
    means: dict[str, float | None] = {}
    for name in metric_names:
        values = [
            float(metrics[name])
            for case in cases
            if isinstance((metrics := case.get("metrics")), Mapping)
            and isinstance(metrics.get(name), (int, float))
            and not isinstance(metrics.get(name), bool)
        ]
        maxima[name] = round(max(values), 6) if values else None
        means[name] = round(sum(values) / len(values), 6) if values else None
    return {
        "case_count": len(cases),
        "passed_count": sum(1 for case in cases if case.get("passed") is True),
        "failed_count": sum(1 for case in cases if case.get("passed") is not True),
        "all_passed": bool(cases) and all(case.get("passed") is True for case in cases),
        "metric_maxima": maxima,
        "metric_means": means,
    }


def run_benchmark(
    cases: Sequence[BenchmarkCase],
    backends: Mapping[str, BenchmarkBackend],
    *,
    gates: GatePolicy | None = None,
    mode: str = "fixture",
) -> dict[str, object]:
    if not 1 <= len(cases) <= MAX_CASES:
        raise BenchmarkValidationError("benchmark case count is invalid")
    if mode not in {"fixture", "live"}:
        raise BenchmarkValidationError("benchmark mode is invalid")
    policy = gates or GatePolicy()
    ordered_cases = sorted(cases, key=lambda item: item.case_id)
    if len({case.case_id for case in ordered_cases}) != len(ordered_cases):
        raise BenchmarkValidationError("case_id values must be unique")

    backend_results: list[dict[str, object]] = []
    for backend_name in sorted(backends):
        backend = backends[backend_name]
        if backend.name != backend_name:
            raise BenchmarkValidationError("backend mapping name does not match backend")
        status = dict(backend.status())
        case_results: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        if status.get("available") is True:
            for case in ordered_cases:
                try:
                    case_results.append(evaluate_run(case, backend_name, backend.run(case), policy))
                except BackendUnavailable:
                    errors.append({"case_id": case.case_id, "code": "backend-unavailable"})
                except BenchmarkValidationError:
                    errors.append({"case_id": case.case_id, "code": "invalid-backend-run"})
        summary = _summary(case_results)
        if errors:
            summary["all_passed"] = False
        backend_results.append(
            {
                "name": backend_name,
                "status": status,
                "passed": bool(summary["all_passed"]) and not errors,
                "summary": summary,
                "cases": case_results,
                "errors": errors,
            }
        )

    by_name = {str(item["name"]): item for item in backend_results}
    baseline = by_name.get(BASELINE_BACKEND)
    candidate = by_name.get(CANDIDATE_BACKEND)
    candidate_passed = bool(candidate and candidate.get("passed") is True)
    return {
        "schema": RESULT_SCHEMA,
        "mode": mode,
        "production_selection_changed": False,
        "gates": policy.as_dict(),
        "case_ids": [case.case_id for case in ordered_cases],
        "backends": backend_results,
        "comparison": {
            "baseline": BASELINE_BACKEND,
            "candidate": CANDIDATE_BACKEND,
            "baseline_passed": bool(baseline and baseline.get("passed") is True),
            "candidate_passed": candidate_passed,
            "candidate_eligible_for_separate_review": candidate_passed,
            "recommendation": (
                "review-candidate-evidence" if candidate_passed else "keep-current-production-selection"
            ),
        },
    }


def load_fixture(path: Path) -> tuple[list[BenchmarkCase], dict[str, DryRunBackend], GatePolicy]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkValidationError("fixture could not be read") from exc
    if not isinstance(document, Mapping) or document.get("schema") != FIXTURE_SCHEMA:
        raise BenchmarkValidationError("fixture schema is unsupported")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= MAX_CASES:
        raise BenchmarkValidationError("fixture cases are invalid")
    cases = [BenchmarkCase.from_mapping(item, fixture_root=Path(path).parent) for item in raw_cases]
    case_ids = {case.case_id for case in cases}
    raw_backends = document.get("backends")
    if not isinstance(raw_backends, Mapping) or not raw_backends:
        raise BenchmarkValidationError("fixture backends are invalid")
    backends: dict[str, DryRunBackend] = {}
    for raw_name, raw_backend in raw_backends.items():
        name = _identifier(raw_name, name="backend name")
        if not isinstance(raw_backend, Mapping):
            raise BenchmarkValidationError(f"backend {name} is invalid")
        available = _strict_bool(raw_backend.get("available", True), f"backend {name} available")
        raw_runs = raw_backend.get("runs", {})
        if not isinstance(raw_runs, Mapping):
            raise BenchmarkValidationError(f"backend {name} runs are invalid")
        unknown = set(raw_runs) - case_ids
        if unknown:
            raise BenchmarkValidationError(f"backend {name} has unknown case runs")
        runs = {
            _identifier(case_id, name="run case_id"): BackendRun.from_mapping(
                run, run_name=f"{name}/{case_id}"
            )
            for case_id, run in raw_runs.items()
        }
        backends[name] = DryRunBackend(name, runs, available=available)
    return cases, backends, GatePolicy.from_mapping(document.get("gates"))


def stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline Moonshine versus faster-whisper benchmark harness."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fixture", type=Path, help="Run a deterministic dry-run fixture.")
    group.add_argument("--probe", action="store_true", help="Report lazy package availability only.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.probe:
            result = optional_backend_status()
        else:
            cases, backends, gates = load_fixture(args.fixture)
            result = run_benchmark(cases, backends, gates=gates, mode="fixture")
    except BenchmarkValidationError as exc:
        print(
            stable_json(
                {
                    "schema": RESULT_SCHEMA,
                    "mode": "fixture",
                    "production_selection_changed": False,
                    "error": {"code": "invalid-fixture", "message": str(exc)},
                }
            )
        )
        return 2
    print(stable_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
