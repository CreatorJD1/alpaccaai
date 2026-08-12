"""Content-free benchmark for an injected speaker-familiarity candidate.

The harness imports only the Python standard library. It does not load audio,
models, enrolled profiles, or speaker embeddings. A caller injects a CPU
candidate callable whose private fixture lookup stays outside this module. The
result measures bounded semantic behavior, CPU latency, and caller-reported
memory without authenticating a person or granting authority.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import json
import math
import re
import time


RESULT_SCHEMA = "alpecca.speaker-worker.benchmark-result.v1"
POLICY_SCHEMA = "alpecca.speaker-worker.benchmark-policy.v1"
BASELINE_NAME = "disabled-noop"
PURPOSE = "familiarity-only"
MAX_SAMPLES = 64
MAX_REPETITIONS = 8
MAX_MEMORY_ESTIMATE_BYTES = 16 * 1024 * 1024 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")

CpuClock = Callable[[], int]


class BenchmarkValidationError(ValueError):
    """The benchmark definition or injected result is invalid."""


class ScenarioKind(str, Enum):
    """Content-free fixture category supplied to the injected candidate."""

    CLEAN = "clean"
    NOISY = "noisy"
    AMBIGUOUS = "ambiguous"
    REPLAY = "replay"


class OutcomeKind(str, Enum):
    """Bounded semantic result; none of these outcomes proves identity."""

    FAMILIAR = "familiar"
    UNFAMILIAR = "unfamiliar"
    AMBIGUOUS = "ambiguous"
    REPLAY_REJECTED = "replay_rejected"
    DISABLED = "disabled"
    ERROR = "error"


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise BenchmarkValidationError(f"{name} is invalid")
    return value


def _number(
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


def _strict_bool(value: object, *, name: str) -> bool:
    if type(value) is not bool:
        raise BenchmarkValidationError(f"{name} must be boolean")
    return value


@dataclass(frozen=True, slots=True)
class BenchmarkSample:
    """Opaque fixture label and expected familiarity semantics.

    The callable may use ``sample_id`` to resolve private audio in its own
    process. This object deliberately carries no audio, identity, transcript,
    profile, or embedding.
    """

    sample_id: str
    expected_outcome: OutcomeKind
    scenario: ScenarioKind = ScenarioKind.CLEAN

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _identifier(self.sample_id, name="sample_id"))
        try:
            outcome = OutcomeKind(self.expected_outcome)
        except (TypeError, ValueError):
            raise BenchmarkValidationError("expected_outcome is invalid") from None
        try:
            scenario = ScenarioKind(self.scenario)
        except (TypeError, ValueError):
            raise BenchmarkValidationError("scenario is invalid") from None
        if outcome in {OutcomeKind.DISABLED, OutcomeKind.ERROR}:
            raise BenchmarkValidationError(
                "sample expected_outcome must describe familiarity evaluation"
            )
        if scenario is ScenarioKind.AMBIGUOUS and outcome is not OutcomeKind.AMBIGUOUS:
            raise BenchmarkValidationError(
                "ambiguous scenarios must expect an ambiguous outcome"
            )
        if scenario is ScenarioKind.REPLAY and outcome is OutcomeKind.FAMILIAR:
            raise BenchmarkValidationError("replay scenarios cannot expect familiar")
        if outcome is OutcomeKind.REPLAY_REJECTED and scenario is not ScenarioKind.REPLAY:
            raise BenchmarkValidationError(
                "replay_rejected is valid only for replay scenarios"
            )
        object.__setattr__(self, "expected_outcome", outcome)
        object.__setattr__(self, "scenario", scenario)

    @property
    def is_ambiguous_case(self) -> bool:
        return (
            self.scenario is ScenarioKind.AMBIGUOUS
            or self.expected_outcome is OutcomeKind.AMBIGUOUS
        )

    @property
    def is_replay_case(self) -> bool:
        return self.scenario is ScenarioKind.REPLAY


@dataclass(frozen=True, slots=True)
class SampleOutcome:
    """One content-free candidate result with a process-memory estimate."""

    outcome: OutcomeKind
    score: float | None
    memory_estimate_bytes: int

    def __post_init__(self) -> None:
        try:
            outcome = OutcomeKind(self.outcome)
        except (TypeError, ValueError):
            raise BenchmarkValidationError("outcome is invalid") from None
        score = (
            None
            if self.score is None
            else _number(self.score, name="score", maximum=1.0)
        )
        if type(self.memory_estimate_bytes) is not int or not (
            0 <= self.memory_estimate_bytes <= MAX_MEMORY_ESTIMATE_BYTES
        ):
            raise BenchmarkValidationError("memory_estimate_bytes is invalid")
        if outcome in {
            OutcomeKind.FAMILIAR,
            OutcomeKind.UNFAMILIAR,
            OutcomeKind.AMBIGUOUS,
        }:
            if score is None:
                raise BenchmarkValidationError(
                    "familiarity outcomes require a bounded score"
                )
        elif score is not None:
            raise BenchmarkValidationError(
                "replay_rejected, disabled, and error outcomes require no score"
            )
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "score", score)

    def semantic_tuple(self) -> tuple[str, float | None]:
        return self.outcome.value, self.score

    def as_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "score": self.score,
            "memory_estimate_bytes": self.memory_estimate_bytes,
        }


@dataclass(frozen=True, slots=True)
class CandidateMetadata:
    """Safety declarations for one injected CPU familiarity candidate."""

    name: str
    backend_component: str
    device: str
    memory_estimate_method: str
    uses_network: bool = False
    retains_audio: bool = False
    performs_authentication: bool = False
    grants_authority: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, name="candidate name"))
        object.__setattr__(
            self,
            "backend_component",
            _identifier(self.backend_component, name="backend_component"),
        )
        object.__setattr__(
            self,
            "memory_estimate_method",
            _identifier(self.memory_estimate_method, name="memory_estimate_method"),
        )
        if self.device != "cpu":
            raise BenchmarkValidationError("candidate device must be cpu")
        for field_name in (
            "uses_network",
            "retains_audio",
            "performs_authentication",
            "grants_authority",
        ):
            declared = _strict_bool(getattr(self, field_name), name=field_name)
            if declared:
                raise BenchmarkValidationError(
                    f"candidate {field_name} must be false for this harness"
                )

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "family": "speaker-embedding",
            "backend_component": self.backend_component,
            "device": self.device,
            "memory_estimate_method": self.memory_estimate_method,
            "uses_network": self.uses_network,
            "retains_audio": self.retains_audio,
            "performs_authentication": self.performs_authentication,
            "grants_authority": self.grants_authority,
        }


@dataclass(frozen=True, slots=True)
class AcceptanceThresholds:
    max_mean_cpu_latency_ms: float = 150.0
    max_p95_cpu_latency_ms: float = 300.0
    max_memory_estimate_bytes: int = 512 * 1024 * 1024
    min_semantic_accuracy: float = 1.0
    min_ambiguous_accuracy: float = 1.0
    min_replay_safe_rate: float = 1.0
    repetitions: int = 2
    require_deterministic_outcomes: bool = True
    require_ambiguous_fixture: bool = True
    require_replay_fixture: bool = True

    def __post_init__(self) -> None:
        for name in ("max_mean_cpu_latency_ms", "max_p95_cpu_latency_ms"):
            object.__setattr__(self, name, _number(getattr(self, name), name=name))
        if type(self.max_memory_estimate_bytes) is not int or not (
            0 <= self.max_memory_estimate_bytes <= MAX_MEMORY_ESTIMATE_BYTES
        ):
            raise BenchmarkValidationError("max_memory_estimate_bytes is invalid")
        for name in (
            "min_semantic_accuracy",
            "min_ambiguous_accuracy",
            "min_replay_safe_rate",
        ):
            object.__setattr__(
                self,
                name,
                _number(getattr(self, name), name=name, maximum=1.0),
            )
        if type(self.repetitions) is not int or not 2 <= self.repetitions <= MAX_REPETITIONS:
            raise BenchmarkValidationError(
                f"repetitions must be an integer from 2 to {MAX_REPETITIONS}"
            )
        for name in (
            "require_deterministic_outcomes",
            "require_ambiguous_fixture",
            "require_replay_fixture",
        ):
            object.__setattr__(
                self, name, _strict_bool(getattr(self, name), name=name)
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "max_mean_cpu_latency_ms": self.max_mean_cpu_latency_ms,
            "max_p95_cpu_latency_ms": self.max_p95_cpu_latency_ms,
            "max_memory_estimate_bytes": self.max_memory_estimate_bytes,
            "min_semantic_accuracy": self.min_semantic_accuracy,
            "min_ambiguous_accuracy": self.min_ambiguous_accuracy,
            "min_replay_safe_rate": self.min_replay_safe_rate,
            "repetitions": self.repetitions,
            "require_deterministic_outcomes": self.require_deterministic_outcomes,
            "require_ambiguous_fixture": self.require_ambiguous_fixture,
            "require_replay_fixture": self.require_replay_fixture,
        }


class DisabledBaseline:
    """No-op baseline with no model, audio, storage, or authority."""

    name = BASELINE_NAME

    def __call__(self, sample: BenchmarkSample) -> SampleOutcome:
        del sample
        return SampleOutcome(OutcomeKind.DISABLED, None, 0)


def _timed_call(
    callback: Callable[[BenchmarkSample], SampleOutcome],
    sample: BenchmarkSample,
    clock: CpuClock,
) -> tuple[SampleOutcome, float]:
    started = clock()
    if type(started) is not int or started < 0:
        raise BenchmarkValidationError(
            "cpu clock must return non-negative integer nanoseconds"
        )
    outcome = callback(sample)
    finished = clock()
    if type(finished) is not int or finished < started:
        raise BenchmarkValidationError(
            "cpu clock must be monotonic integer nanoseconds"
        )
    if not isinstance(outcome, SampleOutcome):
        raise BenchmarkValidationError("candidate must return SampleOutcome")
    return outcome, round((finished - started) / 1_000_000.0, 6)


def _percentile_95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return round(ordered[index], 6)


def _run_backend(
    name: str,
    samples: Sequence[BenchmarkSample],
    callback: Callable[[BenchmarkSample], SampleOutcome],
    *,
    repetitions: int,
    clock: CpuClock,
) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    all_latencies: list[float] = []
    all_memory: list[int] = []
    error_count = 0
    for sample in samples:
        outcomes: list[SampleOutcome] = []
        latencies: list[float] = []
        error_code: str | None = None
        for _ in range(repetitions):
            try:
                outcome, latency = _timed_call(callback, sample, clock)
            except BenchmarkValidationError:
                error_code = "invalid-candidate-outcome"
                break
            except Exception:
                error_code = "candidate-error"
                break
            outcomes.append(outcome)
            latencies.append(latency)
            all_latencies.append(latency)
            all_memory.append(outcome.memory_estimate_bytes)

        deterministic = bool(outcomes) and all(
            item.semantic_tuple() == outcomes[0].semantic_tuple()
            for item in outcomes[1:]
        )
        observed = (
            outcomes[0]
            if outcomes
            else SampleOutcome(OutcomeKind.ERROR, None, 0)
        )
        correct = error_code is None and observed.outcome is sample.expected_outcome
        ambiguous_handled = (
            observed.outcome is OutcomeKind.AMBIGUOUS
            if sample.is_ambiguous_case and error_code is None
            else None
        )
        replay_safe = (
            observed.outcome
            in {
                OutcomeKind.UNFAMILIAR,
                OutcomeKind.AMBIGUOUS,
                OutcomeKind.REPLAY_REJECTED,
            }
            if sample.is_replay_case and error_code is None
            else None
        )
        if error_code is not None:
            error_count += 1
        cases.append(
            {
                "sample_id": sample.sample_id,
                "scenario": sample.scenario.value,
                "expected_outcome": sample.expected_outcome.value,
                "observed_outcome": observed.as_dict(),
                "correct": correct,
                "deterministic": deterministic,
                "ambiguous_handled": ambiguous_handled,
                "replay_safe": replay_safe,
                "cpu_latency_ms": latencies,
                "mean_cpu_latency_ms": (
                    round(sum(latencies) / len(latencies), 6)
                    if latencies
                    else None
                ),
                "error": error_code,
            }
        )

    correct_count = sum(item["correct"] is True for item in cases)
    ambiguous_cases = [
        item for item in cases if item["ambiguous_handled"] is not None
    ]
    replay_cases = [item for item in cases if item["replay_safe"] is not None]
    ambiguous_correct = sum(
        item["ambiguous_handled"] is True for item in ambiguous_cases
    )
    replay_safe = sum(item["replay_safe"] is True for item in replay_cases)
    replay_rejected = sum(
        item["observed_outcome"]["outcome"] == OutcomeKind.REPLAY_REJECTED.value
        for item in replay_cases
    )
    deterministic = bool(cases) and all(item["deterministic"] is True for item in cases)
    return {
        "name": name,
        "available": name != BASELINE_NAME,
        "disabled": name == BASELINE_NAME,
        "cases": cases,
        "summary": {
            "sample_count": len(cases),
            "correct_count": correct_count,
            "semantic_accuracy": round(correct_count / len(cases), 6),
            "deterministic_outcomes": deterministic,
            "mean_cpu_latency_ms": (
                round(sum(all_latencies) / len(all_latencies), 6)
                if all_latencies
                else None
            ),
            "p95_cpu_latency_ms": _percentile_95(all_latencies),
            "peak_memory_estimate_bytes": max(all_memory, default=0),
            "memory_estimate_source": (
                "disabled-zero" if name == BASELINE_NAME else "caller-reported"
            ),
            "ambiguous_case_count": len(ambiguous_cases),
            "ambiguous_correct_count": ambiguous_correct,
            "ambiguous_accuracy": (
                round(ambiguous_correct / len(ambiguous_cases), 6)
                if ambiguous_cases
                else None
            ),
            "replay_case_count": len(replay_cases),
            "replay_safe_count": replay_safe,
            "replay_safe_rate": (
                round(replay_safe / len(replay_cases), 6) if replay_cases else None
            ),
            "replay_rejected_count": replay_rejected,
            "error_count": error_count,
        },
    }


def _gate(
    name: str,
    actual: object,
    limit: object,
    passed: bool,
    reason: str,
) -> dict[str, object]:
    return {
        "name": name,
        "actual": actual,
        "limit": limit,
        "passed": passed,
        "reason": reason,
    }


def _numeric_delta(left: object, right: object) -> float | None:
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return round(float(left) - float(right), 6)
    return None


def run_benchmark(
    samples: Sequence[BenchmarkSample],
    candidate: Callable[[BenchmarkSample], SampleOutcome],
    metadata: CandidateMetadata,
    *,
    thresholds: AcceptanceThresholds | None = None,
    cpu_clock_ns: CpuClock = time.process_time_ns,
) -> dict[str, object]:
    """Compare an injected CPU candidate with a disabled no-op baseline."""

    if not isinstance(metadata, CandidateMetadata):
        raise BenchmarkValidationError("metadata must be CandidateMetadata")
    if not callable(candidate):
        raise BenchmarkValidationError("candidate must be callable")
    if not 1 <= len(samples) <= MAX_SAMPLES:
        raise BenchmarkValidationError("benchmark sample count is invalid")
    if not all(isinstance(item, BenchmarkSample) for item in samples):
        raise BenchmarkValidationError("samples contains invalid entries")
    ordered = sorted(samples, key=lambda item: item.sample_id)
    if len({item.sample_id for item in ordered}) != len(ordered):
        raise BenchmarkValidationError("sample_id values must be unique")
    policy = thresholds or AcceptanceThresholds()
    if not isinstance(policy, AcceptanceThresholds):
        raise BenchmarkValidationError("thresholds must be AcceptanceThresholds")
    if not callable(cpu_clock_ns):
        raise BenchmarkValidationError("cpu_clock_ns must be callable")

    baseline = _run_backend(
        BASELINE_NAME,
        ordered,
        DisabledBaseline(),
        repetitions=policy.repetitions,
        clock=cpu_clock_ns,
    )
    candidate_result = _run_backend(
        metadata.name,
        ordered,
        candidate,
        repetitions=policy.repetitions,
        clock=cpu_clock_ns,
    )
    summary = candidate_result["summary"]
    if not isinstance(summary, Mapping):
        raise AssertionError("candidate summary is not a mapping")

    mean_latency = summary["mean_cpu_latency_ms"]
    p95_latency = summary["p95_cpu_latency_ms"]
    peak_memory = summary["peak_memory_estimate_bytes"]
    semantic_accuracy = summary["semantic_accuracy"]
    ambiguous_count = summary["ambiguous_case_count"]
    ambiguous_accuracy = summary["ambiguous_accuracy"]
    replay_count = summary["replay_case_count"]
    replay_safe_rate = summary["replay_safe_rate"]
    deterministic = summary["deterministic_outcomes"] is True
    no_errors = summary["error_count"] == 0

    gates = [
        _gate(
            "mean_cpu_latency_ms",
            mean_latency,
            policy.max_mean_cpu_latency_ms,
            isinstance(mean_latency, (int, float))
            and mean_latency <= policy.max_mean_cpu_latency_ms,
            "within-limit"
            if isinstance(mean_latency, (int, float))
            and mean_latency <= policy.max_mean_cpu_latency_ms
            else "limit-exceeded-or-missing",
        ),
        _gate(
            "p95_cpu_latency_ms",
            p95_latency,
            policy.max_p95_cpu_latency_ms,
            isinstance(p95_latency, (int, float))
            and p95_latency <= policy.max_p95_cpu_latency_ms,
            "within-limit"
            if isinstance(p95_latency, (int, float))
            and p95_latency <= policy.max_p95_cpu_latency_ms
            else "limit-exceeded-or-missing",
        ),
        _gate(
            "peak_memory_estimate_bytes",
            peak_memory,
            policy.max_memory_estimate_bytes,
            isinstance(peak_memory, int)
            and peak_memory <= policy.max_memory_estimate_bytes,
            "within-limit"
            if isinstance(peak_memory, int)
            and peak_memory <= policy.max_memory_estimate_bytes
            else "limit-exceeded-or-missing",
        ),
        _gate(
            "semantic_accuracy",
            semantic_accuracy,
            policy.min_semantic_accuracy,
            isinstance(semantic_accuracy, (int, float))
            and semantic_accuracy >= policy.min_semantic_accuracy,
            "threshold-met"
            if isinstance(semantic_accuracy, (int, float))
            and semantic_accuracy >= policy.min_semantic_accuracy
            else "below-threshold",
        ),
        _gate(
            "ambiguous_fixture_coverage",
            ambiguous_count,
            1 if policy.require_ambiguous_fixture else 0,
            isinstance(ambiguous_count, int)
            and (ambiguous_count >= 1 or not policy.require_ambiguous_fixture),
            "covered"
            if isinstance(ambiguous_count, int) and ambiguous_count >= 1
            else "missing",
        ),
        _gate(
            "ambiguous_accuracy",
            ambiguous_accuracy,
            policy.min_ambiguous_accuracy,
            (
                not policy.require_ambiguous_fixture and ambiguous_count == 0
            )
            or (
                isinstance(ambiguous_accuracy, (int, float))
                and ambiguous_accuracy >= policy.min_ambiguous_accuracy
            ),
            "not-required"
            if not policy.require_ambiguous_fixture and ambiguous_count == 0
            else
            "threshold-met"
            if isinstance(ambiguous_accuracy, (int, float))
            and ambiguous_accuracy >= policy.min_ambiguous_accuracy
            else "below-threshold-or-missing",
        ),
        _gate(
            "replay_fixture_coverage",
            replay_count,
            1 if policy.require_replay_fixture else 0,
            isinstance(replay_count, int)
            and (replay_count >= 1 or not policy.require_replay_fixture),
            "covered"
            if isinstance(replay_count, int) and replay_count >= 1
            else "missing",
        ),
        _gate(
            "replay_safe_rate",
            replay_safe_rate,
            policy.min_replay_safe_rate,
            (not policy.require_replay_fixture and replay_count == 0)
            or (
                isinstance(replay_safe_rate, (int, float))
                and replay_safe_rate >= policy.min_replay_safe_rate
            ),
            "not-required"
            if not policy.require_replay_fixture and replay_count == 0
            else
            "threshold-met"
            if isinstance(replay_safe_rate, (int, float))
            and replay_safe_rate >= policy.min_replay_safe_rate
            else "below-threshold-or-missing",
        ),
        _gate(
            "deterministic_outcomes",
            deterministic,
            policy.require_deterministic_outcomes,
            deterministic or not policy.require_deterministic_outcomes,
            "deterministic" if deterministic else "nondeterministic",
        ),
        _gate(
            "candidate_errors",
            summary["error_count"],
            0,
            no_errors,
            "none" if no_errors else "errors-observed",
        ),
    ]
    accepted = all(gate["passed"] is True for gate in gates)
    failed_reasons = [
        str(gate["name"]) for gate in gates if gate["passed"] is not True
    ]
    baseline_summary = baseline["summary"]
    if not isinstance(baseline_summary, Mapping):
        raise AssertionError("baseline summary is not a mapping")
    comparison = {
        "baseline": BASELINE_NAME,
        "candidate": metadata.name,
        "candidate_minus_baseline_mean_cpu_latency_ms": _numeric_delta(
            mean_latency, baseline_summary["mean_cpu_latency_ms"]
        ),
        "candidate_minus_baseline_peak_memory_estimate_bytes": (
            int(peak_memory)
            - int(baseline_summary["peak_memory_estimate_bytes"])
        ),
        "candidate_semantic_accuracy_gain": _numeric_delta(
            semantic_accuracy, baseline_summary["semantic_accuracy"]
        ),
        "candidate_ambiguous_accuracy_gain": _numeric_delta(
            ambiguous_accuracy, baseline_summary["ambiguous_accuracy"]
        ),
        "candidate_replay_safe_rate_gain": _numeric_delta(
            replay_safe_rate, baseline_summary["replay_safe_rate"]
        ),
    }
    return {
        "schema": RESULT_SCHEMA,
        "purpose": PURPOSE,
        "mode": "caller-injected",
        "content_free": True,
        "audio_loaded_by_harness": False,
        "network_used": metadata.uses_network,
        "audio_retained": metadata.retains_audio,
        "optional_packages_imported_by_harness": False,
        "biometric_authentication_performed": metadata.performs_authentication,
        "authority_granted": metadata.grants_authority,
        "may_authenticate": False,
        "may_grant_authority": False,
        "thresholds": policy.as_dict(),
        "candidate_metadata": metadata.as_dict(),
        "sample_ids": [item.sample_id for item in ordered],
        "baseline": baseline,
        "candidate": candidate_result,
        "comparison": comparison,
        "acceptance_gates": gates,
        "speaker_worker_policy": {
            "schema": POLICY_SCHEMA,
            "candidate_backend": metadata.name,
            "eligible": accepted,
            "purpose": PURPOSE,
            "may_authenticate": False,
            "may_grant_authority": False,
            "decision": (
                "eligible-for-familiarity-review" if accepted else "keep-disabled"
            ),
            "reasons": failed_reasons,
        },
    }


def stable_json(value: object) -> str:
    """Serialize the content-free report without non-JSON values."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def dry_run_samples() -> tuple[BenchmarkSample, ...]:
    """Return fixed metadata-only fixtures for validating the harness itself."""

    return (
        BenchmarkSample("fixture-001", OutcomeKind.FAMILIAR),
        BenchmarkSample("fixture-002", OutcomeKind.UNFAMILIAR),
        BenchmarkSample("fixture-003", OutcomeKind.FAMILIAR, ScenarioKind.NOISY),
        BenchmarkSample("fixture-004", OutcomeKind.AMBIGUOUS, ScenarioKind.AMBIGUOUS),
        BenchmarkSample(
            "fixture-005", OutcomeKind.REPLAY_REJECTED, ScenarioKind.REPLAY
        ),
    )


def _dry_run_candidate(sample: BenchmarkSample) -> SampleOutcome:
    scores = {
        OutcomeKind.FAMILIAR: 0.91,
        OutcomeKind.UNFAMILIAR: 0.17,
        OutcomeKind.AMBIGUOUS: 0.71,
    }
    return SampleOutcome(
        sample.expected_outcome,
        scores.get(sample.expected_outcome),
        32 * 1024 * 1024,
    )


def _stepped_clock(step_ns: int = 1_000_000) -> CpuClock:
    current = -step_ns

    def read() -> int:
        nonlocal current
        current += step_ns
        return current

    return read


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the metadata-only speaker benchmark harness self-check."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="use fixed content-free fixtures and a deterministic injected candidate",
    )
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("--dry-run is required; real candidates must be injected in Python")

    result = run_benchmark(
        dry_run_samples(),
        _dry_run_candidate,
        CandidateMetadata(
            name="deterministic-dry-run",
            backend_component="fixture-only",
            device="cpu",
            memory_estimate_method="fixed-fixture-estimate",
        ),
        cpu_clock_ns=_stepped_clock(),
    )
    if args.pretty:
        print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True))
    else:
        print(stable_json(result))
    return 0 if result["speaker_worker_policy"]["eligible"] is True else 1


__all__ = [
    "AcceptanceThresholds",
    "BASELINE_NAME",
    "BenchmarkSample",
    "BenchmarkValidationError",
    "CandidateMetadata",
    "DisabledBaseline",
    "OutcomeKind",
    "POLICY_SCHEMA",
    "PURPOSE",
    "RESULT_SCHEMA",
    "SampleOutcome",
    "ScenarioKind",
    "dry_run_samples",
    "main",
    "run_benchmark",
    "stable_json",
]


if __name__ == "__main__":
    raise SystemExit(main())
