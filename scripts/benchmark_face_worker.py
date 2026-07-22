"""Dependency-safe benchmark harness for an injected YuNet/SFace candidate.

The harness imports only the Python standard library. It does not discover or
load models, import OpenCV/NumPy, access cameras, use the network, or perform
biometric authentication. A caller injects a CPU candidate callable and
deterministic sample metadata. Results are suitable for a separate
``face_worker`` familiarity policy decision only.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import json
import math
import re
import time


RESULT_SCHEMA = "alpecca.face-worker.benchmark-result.v1"
POLICY_SCHEMA = "alpecca.face-worker.benchmark-policy.v1"
BASELINE_NAME = "disabled-noop"
PURPOSE = "familiarity-only"
MAX_SAMPLES = 64
MAX_REPETITIONS = 8
MAX_MEMORY_ESTIMATE_BYTES = 16 * 1024 * 1024 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_SPDX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+()-]{0,95}$")

CpuClock = Callable[[], int]


class BenchmarkValidationError(ValueError):
    """The benchmark definition or injected result is invalid."""


class OutcomeKind(str, Enum):
    MATCH = "match"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"
    NO_FACE = "no_face"
    MULTIPLE_FACES = "multiple_faces"
    DISABLED = "disabled"
    ERROR = "error"


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise BenchmarkValidationError(f"{name} is invalid")
    return value


def _text(value: object, *, name: str, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise BenchmarkValidationError(f"{name} must be text")
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > maximum:
        raise BenchmarkValidationError(f"{name} is invalid")
    return cleaned


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
    """Opaque deterministic fixture identity and expected semantic result."""

    sample_id: str
    expected_outcome: OutcomeKind

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_id", _identifier(self.sample_id, name="sample_id"))
        try:
            outcome = OutcomeKind(self.expected_outcome)
        except (TypeError, ValueError):
            raise BenchmarkValidationError("expected_outcome is invalid") from None
        if outcome in {OutcomeKind.DISABLED, OutcomeKind.ERROR}:
            raise BenchmarkValidationError("sample expected_outcome must describe face analysis")
        object.__setattr__(self, "expected_outcome", outcome)


@dataclass(frozen=True, slots=True)
class SampleOutcome:
    """One injected candidate outcome without images, templates, or identities."""

    outcome: OutcomeKind
    face_count: int
    score: float | None
    memory_estimate_bytes: int

    def __post_init__(self) -> None:
        try:
            outcome = OutcomeKind(self.outcome)
        except (TypeError, ValueError):
            raise BenchmarkValidationError("outcome is invalid") from None
        if type(self.face_count) is not int or not 0 <= self.face_count <= 64:
            raise BenchmarkValidationError("face_count must be an integer from 0 to 64")
        score = (
            None
            if self.score is None
            else _number(self.score, name="score", maximum=1.0)
        )
        if type(self.memory_estimate_bytes) is not int or not (
            0 <= self.memory_estimate_bytes <= MAX_MEMORY_ESTIMATE_BYTES
        ):
            raise BenchmarkValidationError("memory_estimate_bytes is invalid")
        if outcome in {OutcomeKind.MATCH, OutcomeKind.NO_MATCH, OutcomeKind.AMBIGUOUS}:
            if self.face_count != 1 or score is None:
                raise BenchmarkValidationError(
                    "similarity outcomes require one face and a bounded score"
                )
        elif outcome is OutcomeKind.NO_FACE:
            if self.face_count != 0 or score is not None:
                raise BenchmarkValidationError("no_face requires zero faces and no score")
        elif outcome is OutcomeKind.MULTIPLE_FACES:
            if self.face_count < 2 or score is not None:
                raise BenchmarkValidationError(
                    "multiple_faces requires at least two faces and no score"
                )
        elif outcome in {OutcomeKind.DISABLED, OutcomeKind.ERROR}:
            if self.face_count != 0 or score is not None:
                raise BenchmarkValidationError(
                    "disabled/error outcomes must not claim faces or similarity"
                )
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "score", score)

    def semantic_tuple(self) -> tuple[str, int, float | None]:
        return self.outcome.value, self.face_count, self.score

    def as_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "face_count": self.face_count,
            "score": self.score,
            "memory_estimate_bytes": self.memory_estimate_bytes,
        }


@dataclass(frozen=True, slots=True)
class LicenseMetadata:
    component: str
    spdx_id: str
    source_reference: str
    reviewed: bool
    approved_for_use: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "component", _identifier(self.component, name="component"))
        if not isinstance(self.spdx_id, str) or _SPDX_RE.fullmatch(self.spdx_id) is None:
            raise BenchmarkValidationError("spdx_id is invalid")
        object.__setattr__(
            self,
            "source_reference",
            _text(self.source_reference, name="source_reference", maximum=512),
        )
        object.__setattr__(self, "reviewed", _strict_bool(self.reviewed, name="reviewed"))
        object.__setattr__(
            self,
            "approved_for_use",
            _strict_bool(self.approved_for_use, name="approved_for_use"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "spdx_id": self.spdx_id,
            "source_reference": self.source_reference,
            "reviewed": self.reviewed,
            "approved_for_use": self.approved_for_use,
        }


@dataclass(frozen=True, slots=True)
class CandidateMetadata:
    name: str
    detector_component: str
    recognizer_component: str
    device: str
    memory_estimate_method: str
    licenses: tuple[LicenseMetadata, ...]
    uses_network: bool = False
    uses_camera: bool = False
    downloads_models: bool = False
    performs_biometric_authentication: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, name="candidate name"))
        detector = _identifier(self.detector_component, name="detector_component")
        recognizer = _identifier(self.recognizer_component, name="recognizer_component")
        if detector == recognizer:
            raise BenchmarkValidationError("detector and recognizer components must differ")
        if self.device != "cpu":
            raise BenchmarkValidationError("candidate device must be cpu")
        method = _identifier(self.memory_estimate_method, name="memory_estimate_method")
        if not isinstance(self.licenses, tuple) or not self.licenses:
            raise BenchmarkValidationError("licenses must be a non-empty tuple")
        if not all(isinstance(item, LicenseMetadata) for item in self.licenses):
            raise BenchmarkValidationError("licenses contains invalid metadata")
        components = [item.component for item in self.licenses]
        if len(components) != len(set(components)):
            raise BenchmarkValidationError("license components must be unique")
        object.__setattr__(self, "detector_component", detector)
        object.__setattr__(self, "recognizer_component", recognizer)
        object.__setattr__(self, "memory_estimate_method", method)
        for field_name in (
            "uses_network",
            "uses_camera",
            "downloads_models",
            "performs_biometric_authentication",
        ):
            declared = _strict_bool(getattr(self, field_name), name=field_name)
            if declared:
                raise BenchmarkValidationError(
                    f"candidate {field_name} must be false for this harness"
                )

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "family": "yunet-sface",
            "detector_component": self.detector_component,
            "recognizer_component": self.recognizer_component,
            "device": self.device,
            "memory_estimate_method": self.memory_estimate_method,
            "licenses": [item.as_dict() for item in self.licenses],
            "uses_network": self.uses_network,
            "uses_camera": self.uses_camera,
            "downloads_models": self.downloads_models,
            "performs_biometric_authentication": (
                self.performs_biometric_authentication
            ),
        }


@dataclass(frozen=True, slots=True)
class AcceptanceThresholds:
    max_mean_cpu_latency_ms: float = 100.0
    max_p95_cpu_latency_ms: float = 200.0
    max_memory_estimate_bytes: int = 512 * 1024 * 1024
    min_outcome_accuracy: float = 1.0
    repetitions: int = 2
    require_deterministic_outcomes: bool = True
    require_reviewed_licenses: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_mean_cpu_latency_ms",
            _number(self.max_mean_cpu_latency_ms, name="max_mean_cpu_latency_ms"),
        )
        object.__setattr__(
            self,
            "max_p95_cpu_latency_ms",
            _number(self.max_p95_cpu_latency_ms, name="max_p95_cpu_latency_ms"),
        )
        if type(self.max_memory_estimate_bytes) is not int or not (
            0 <= self.max_memory_estimate_bytes <= MAX_MEMORY_ESTIMATE_BYTES
        ):
            raise BenchmarkValidationError("max_memory_estimate_bytes is invalid")
        object.__setattr__(
            self,
            "min_outcome_accuracy",
            _number(self.min_outcome_accuracy, name="min_outcome_accuracy", maximum=1.0),
        )
        if type(self.repetitions) is not int or not 2 <= self.repetitions <= MAX_REPETITIONS:
            raise BenchmarkValidationError(
                f"repetitions must be an integer from 2 to {MAX_REPETITIONS}"
            )
        object.__setattr__(
            self,
            "require_deterministic_outcomes",
            _strict_bool(
                self.require_deterministic_outcomes,
                name="require_deterministic_outcomes",
            ),
        )
        object.__setattr__(
            self,
            "require_reviewed_licenses",
            _strict_bool(
                self.require_reviewed_licenses,
                name="require_reviewed_licenses",
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "max_mean_cpu_latency_ms": self.max_mean_cpu_latency_ms,
            "max_p95_cpu_latency_ms": self.max_p95_cpu_latency_ms,
            "max_memory_estimate_bytes": self.max_memory_estimate_bytes,
            "min_outcome_accuracy": self.min_outcome_accuracy,
            "repetitions": self.repetitions,
            "require_deterministic_outcomes": self.require_deterministic_outcomes,
            "require_reviewed_licenses": self.require_reviewed_licenses,
        }


class DisabledBaseline:
    """True no-op baseline: no model, image access, inference, or authority."""

    name = BASELINE_NAME

    def __call__(self, sample: BenchmarkSample) -> SampleOutcome:
        del sample
        return SampleOutcome(OutcomeKind.DISABLED, 0, None, 0)


def _timed_call(
    callback: Callable[[BenchmarkSample], SampleOutcome],
    sample: BenchmarkSample,
    clock: CpuClock,
) -> tuple[SampleOutcome, float]:
    started = clock()
    if type(started) is not int or started < 0:
        raise BenchmarkValidationError("cpu clock must return non-negative integer nanoseconds")
    outcome = callback(sample)
    finished = clock()
    if type(finished) is not int or finished < started:
        raise BenchmarkValidationError("cpu clock must be monotonic integer nanoseconds")
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
            item.semantic_tuple() == outcomes[0].semantic_tuple() for item in outcomes[1:]
        )
        observed = outcomes[0] if outcomes else SampleOutcome(OutcomeKind.ERROR, 0, None, 0)
        correct = error_code is None and observed.outcome is sample.expected_outcome
        if error_code is not None:
            error_count += 1
        cases.append(
            {
                "sample_id": sample.sample_id,
                "expected_outcome": sample.expected_outcome.value,
                "observed_outcome": observed.as_dict(),
                "correct": correct,
                "deterministic": deterministic,
                "cpu_latency_ms": latencies,
                "mean_cpu_latency_ms": (
                    round(sum(latencies) / len(latencies), 6) if latencies else None
                ),
                "error": error_code,
            }
        )
    correct_count = sum(1 for item in cases if item["correct"] is True)
    deterministic = bool(cases) and all(item["deterministic"] is True for item in cases)
    return {
        "name": name,
        "available": name != BASELINE_NAME,
        "disabled": name == BASELINE_NAME,
        "cases": cases,
        "summary": {
            "sample_count": len(cases),
            "correct_count": correct_count,
            "outcome_accuracy": round(correct_count / len(cases), 6),
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
            "error_count": error_count,
        },
    }


def _gate(name: str, actual: object, limit: object, passed: bool, reason: str) -> dict[str, object]:
    return {
        "name": name,
        "actual": actual,
        "limit": limit,
        "passed": passed,
        "reason": reason,
    }


def _license_gate(metadata: CandidateMetadata) -> tuple[bool, dict[str, object]]:
    by_component = {item.component: item for item in metadata.licenses}
    required = (metadata.detector_component, metadata.recognizer_component)
    complete = all(component in by_component for component in required)
    approved = complete and all(
        by_component[component].reviewed
        and by_component[component].approved_for_use
        and by_component[component].spdx_id != "NOASSERTION"
        for component in required
    )
    return approved, {
        "required_components": list(required),
        "covered_components": sorted(by_component),
        "complete": complete,
        "reviewed_and_approved": approved,
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
    accuracy = summary["outcome_accuracy"]
    deterministic = summary["deterministic_outcomes"] is True
    no_errors = summary["error_count"] == 0
    licenses_approved, license_assessment = _license_gate(metadata)

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
            isinstance(peak_memory, int) and peak_memory <= policy.max_memory_estimate_bytes,
            "within-limit"
            if isinstance(peak_memory, int) and peak_memory <= policy.max_memory_estimate_bytes
            else "limit-exceeded-or-missing",
        ),
        _gate(
            "outcome_accuracy",
            accuracy,
            policy.min_outcome_accuracy,
            isinstance(accuracy, (int, float)) and accuracy >= policy.min_outcome_accuracy,
            "threshold-met"
            if isinstance(accuracy, (int, float)) and accuracy >= policy.min_outcome_accuracy
            else "below-threshold",
        ),
        _gate(
            "deterministic_outcomes",
            deterministic,
            policy.require_deterministic_outcomes,
            deterministic or not policy.require_deterministic_outcomes,
            "deterministic" if deterministic else "nondeterministic",
        ),
        _gate(
            "license_metadata",
            license_assessment,
            "reviewed-and-approved"
            if policy.require_reviewed_licenses
            else "metadata-only",
            licenses_approved or not policy.require_reviewed_licenses,
            "approved" if licenses_approved else "incomplete-or-unapproved",
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
    failed_reasons = [str(gate["name"]) for gate in gates if gate["passed"] is not True]
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
            int(peak_memory) - int(baseline_summary["peak_memory_estimate_bytes"])
        ),
        "candidate_accuracy_gain": _numeric_delta(
            accuracy, baseline_summary["outcome_accuracy"]
        ),
    }
    return {
        "schema": RESULT_SCHEMA,
        "purpose": PURPOSE,
        "mode": "caller-injected",
        "network_used": metadata.uses_network,
        "camera_used": metadata.uses_camera,
        "models_downloaded": metadata.downloads_models,
        "optional_packages_imported_by_harness": False,
        "biometric_authentication_performed": (
            metadata.performs_biometric_authentication
        ),
        "may_authenticate": False,
        "may_authorize_creator": False,
        "thresholds": policy.as_dict(),
        "candidate_metadata": metadata.as_dict(),
        "sample_ids": [item.sample_id for item in ordered],
        "baseline": baseline,
        "candidate": candidate_result,
        "comparison": comparison,
        "acceptance_gates": gates,
        "face_worker_policy": {
            "schema": POLICY_SCHEMA,
            "candidate_backend": metadata.name,
            "eligible": accepted,
            "purpose": PURPOSE,
            "may_authenticate": False,
            "may_authorize_creator": False,
            "decision": "eligible-for-familiarity-review" if accepted else "keep-disabled",
            "reasons": failed_reasons,
        },
    }


def stable_json(value: object) -> str:
    """Serialize a benchmark result without non-JSON values."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = [
    "AcceptanceThresholds",
    "BASELINE_NAME",
    "BenchmarkSample",
    "BenchmarkValidationError",
    "CandidateMetadata",
    "DisabledBaseline",
    "LicenseMetadata",
    "OutcomeKind",
    "POLICY_SCHEMA",
    "PURPOSE",
    "RESULT_SCHEMA",
    "SampleOutcome",
    "run_benchmark",
    "stable_json",
]
