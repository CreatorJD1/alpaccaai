"""Isolated ASR selection policy with a faster-whisper production default.

This module does not import, configure, or select a production voice backend at
module load. Optional ASR implementations are supplied as factories by a
caller. Moonshine is usable only when explicitly requested and supported by a
complete live benchmark result from ``scripts/benchmark_streaming_asr.py``.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any, Protocol


BENCHMARK_RESULT_SCHEMA = "alpecca.streaming-asr.benchmark-result.v1"
BENCHMARK_GATE_SCHEMA = "alpecca.streaming-asr.gates.v1"
ASSESSMENT_SCHEMA = "alpecca.asr-benchmark-assessment.v1"
SELECTION_SCHEMA = "alpecca.asr-selection.v1"
STATUS_SCHEMA = "alpecca.asr-dispatch-status.v1"

DEFAULT_BACKEND = "faster-whisper"
CANDIDATE_BACKEND = "moonshine"
KNOWN_BACKENDS = (DEFAULT_BACKEND, CANDIDATE_BACKEND)

_ALWAYS_REQUIRED_GATES = (
    "first_partial_latency_ms",
    "final_latency_ms",
    "transcript_error_proxy",
)
_INTERRUPTION_REQUIRED_GATES = (
    "interruption_recovery_ms",
    "interruption_trace_consistent",
    "stale_output_after_interrupt",
)


class AsrBackend(Protocol):
    def transcribe(self, request: object) -> object: ...


BackendFactory = Callable[[], AsrBackend | Callable[[object], object]]


class AsrDispatchError(RuntimeError):
    """Raised after every backend in the bounded fallback order fails."""

    def __init__(self, attempted_backends: Sequence[str]) -> None:
        self.attempted_backends = tuple(attempted_backends)
        super().__init__("ASR dispatch failed for: " + ", ".join(self.attempted_backends))


@dataclass(frozen=True, slots=True)
class BenchmarkAssessment:
    eligible: bool
    reasons: tuple[str, ...]
    case_count: int = 0
    interruption_case_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ASSESSMENT_SCHEMA,
            "candidate": CANDIDATE_BACKEND,
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "case_count": self.case_count,
            "interruption_case_count": self.interruption_case_count,
        }


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    requested_backend: str
    selected_backend: str
    fallback_order: tuple[str, ...]
    reason: str
    moonshine_eligible: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SELECTION_SCHEMA,
            "production_default": DEFAULT_BACKEND,
            "requested_backend": self.requested_backend,
            "selected_backend": self.selected_backend,
            "fallback_order": list(self.fallback_order),
            "reason": self.reason,
            "moonshine_eligible": self.moonshine_eligible,
        }


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    backend: str
    value: object
    fallback_used: bool
    attempted_backends: tuple[str, ...]


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _gate_passes(gate: object, *, name: str) -> bool:
    record = _mapping(gate)
    if record is None or record.get("name") != name:
        return False
    if record.get("required") is not True or record.get("passed") is not True:
        return False
    actual = record.get("actual")
    limit = record.get("limit")
    if name == "interruption_trace_consistent":
        return actual is True and limit is True
    if name == "stale_output_after_interrupt":
        return actual is False and limit is False
    actual_number = _finite_number(actual)
    limit_number = _finite_number(limit)
    return (
        actual_number is not None
        and limit_number is not None
        and actual_number >= 0.0
        and limit_number >= 0.0
        and actual_number <= limit_number
    )


def _backend_entry(result: Mapping[str, object], name: str) -> Mapping[str, object] | None:
    backends = result.get("backends")
    if not isinstance(backends, list):
        return None
    matches = [item for item in backends if _mapping(item) and item.get("name") == name]
    return matches[0] if len(matches) == 1 else None


def assess_moonshine_benchmark(result: object) -> BenchmarkAssessment:
    """Conservatively assess a benchmark object without trusting aggregate flags."""

    document = _mapping(result)
    if document is None or document.get("schema") != BENCHMARK_RESULT_SCHEMA:
        return BenchmarkAssessment(False, ("benchmark-invalid",))
    if document.get("mode") != "live":
        return BenchmarkAssessment(False, ("live-benchmark-required",))
    if document.get("production_selection_changed") is not False:
        return BenchmarkAssessment(False, ("benchmark-selection-boundary-invalid",))

    gate_policy = _mapping(document.get("gates"))
    if (
        gate_policy is None
        or gate_policy.get("schema") != BENCHMARK_GATE_SCHEMA
        or gate_policy.get("require_partial") is not True
        or gate_policy.get("require_interruption_recovery") is not True
    ):
        return BenchmarkAssessment(False, ("benchmark-gate-policy-invalid",))

    candidate = _backend_entry(document, CANDIDATE_BACKEND)
    if candidate is None:
        return BenchmarkAssessment(False, ("moonshine-result-missing",))
    status = _mapping(candidate.get("status"))
    if status is None or status.get("available") is not True:
        return BenchmarkAssessment(False, ("moonshine-benchmark-unavailable",))
    if candidate.get("passed") is not True or candidate.get("errors") != []:
        return BenchmarkAssessment(False, ("moonshine-benchmark-failed",))

    cases = candidate.get("cases")
    if not isinstance(cases, list) or not cases:
        return BenchmarkAssessment(False, ("moonshine-cases-missing",))
    summary = _mapping(candidate.get("summary"))
    if (
        summary is None
        or summary.get("all_passed") is not True
        or summary.get("case_count") != len(cases)
        or summary.get("passed_count") != len(cases)
        or summary.get("failed_count") != 0
    ):
        return BenchmarkAssessment(False, ("moonshine-summary-invalid",), len(cases))

    interruption_count = 0
    for case in cases:
        case_record = _mapping(case)
        if case_record is None or case_record.get("passed") is not True:
            return BenchmarkAssessment(False, ("moonshine-case-failed",), len(cases))
        raw_gates = case_record.get("gates")
        if not isinstance(raw_gates, list):
            return BenchmarkAssessment(False, ("moonshine-case-gates-missing",), len(cases))
        gates: dict[str, object] = {}
        for gate in raw_gates:
            gate_record = _mapping(gate)
            name = gate_record.get("name") if gate_record else None
            if not isinstance(name, str) or name in gates:
                return BenchmarkAssessment(False, ("moonshine-case-gates-invalid",), len(cases))
            gates[name] = gate
        if not all(_gate_passes(gates.get(name), name=name) for name in _ALWAYS_REQUIRED_GATES):
            return BenchmarkAssessment(False, ("moonshine-latency-or-error-gate-failed",), len(cases))

        interruption = _mapping(case_record.get("interruption"))
        if interruption is None or type(interruption.get("required")) is not bool:
            return BenchmarkAssessment(False, ("moonshine-interruption-state-invalid",), len(cases))
        if interruption["required"]:
            interruption_count += 1
            if not all(
                _gate_passes(gates.get(name), name=name)
                for name in _INTERRUPTION_REQUIRED_GATES
            ):
                return BenchmarkAssessment(
                    False,
                    ("moonshine-interruption-gate-failed",),
                    len(cases),
                    interruption_count,
                )

    if interruption_count == 0:
        return BenchmarkAssessment(False, ("interruption-case-required",), len(cases), 0)

    comparison = _mapping(document.get("comparison"))
    if (
        comparison is None
        or comparison.get("candidate") != CANDIDATE_BACKEND
        or comparison.get("candidate_passed") is not True
        or comparison.get("candidate_eligible_for_separate_review") is not True
    ):
        return BenchmarkAssessment(
            False, ("benchmark-comparison-invalid",), len(cases), interruption_count
        )
    return BenchmarkAssessment(True, ("explicit-gates-passed",), len(cases), interruption_count)


def _capability_record(value: object) -> dict[str, object]:
    if type(value) is bool:
        return {"available": value, "ready": value}
    record = _mapping(value)
    if record is None:
        return {"available": False, "ready": False}
    available = record.get("available") is True
    ready = available and record.get("ready", available) is True
    return {"available": available, "ready": ready}


def capability_snapshot(capabilities: Mapping[str, object] | None = None) -> dict[str, object]:
    supplied = capabilities or {}
    return {
        name: _capability_record(supplied.get(name))
        for name in KNOWN_BACKENDS
    }


def select_backend(
    benchmark_result: object = None,
    *,
    requested_backend: str | None = None,
    capabilities: Mapping[str, object] | None = None,
) -> SelectionDecision:
    """Select deterministically; an absent request always preserves the default."""

    requested = requested_backend or DEFAULT_BACKEND
    assessment = assess_moonshine_benchmark(benchmark_result)
    capability = capability_snapshot(capabilities)
    moonshine_ready = (
        capability[CANDIDATE_BACKEND]["available"] is True
        and capability[CANDIDATE_BACKEND]["ready"] is True
    )
    eligible = assessment.eligible and moonshine_ready

    if requested == CANDIDATE_BACKEND and eligible:
        return SelectionDecision(
            requested,
            CANDIDATE_BACKEND,
            (CANDIDATE_BACKEND, DEFAULT_BACKEND),
            "explicit-moonshine-request-approved",
            True,
        )
    if requested == CANDIDATE_BACKEND:
        reason = "moonshine-capability-unavailable" if assessment.eligible else assessment.reasons[0]
    elif requested == DEFAULT_BACKEND:
        reason = "production-default"
    else:
        reason = "unknown-backend-request"
    return SelectionDecision(
        requested,
        DEFAULT_BACKEND,
        (DEFAULT_BACKEND,),
        reason,
        eligible,
    )


class AsrDispatcher:
    """Factory-injected executor; optional backends load only on first use."""

    def __init__(
        self,
        factories: Mapping[str, BackendFactory],
        *,
        benchmark_result: object = None,
        capabilities: Mapping[str, object] | None = None,
    ) -> None:
        self._factories = {name: factory for name, factory in factories.items() if name in KNOWN_BACKENDS}
        self._instances: dict[str, AsrBackend | Callable[[object], object]] = {}
        self._benchmark_result = benchmark_result
        configured = {name: name in self._factories for name in KNOWN_BACKENDS}
        self._capabilities = {
            name: (capabilities or {}).get(name, configured[name]) for name in KNOWN_BACKENDS
        }
        self._last_attempted: tuple[str, ...] = ()
        self._last_backend: str | None = None
        self._last_fallback_used = False

    def _load(self, name: str) -> AsrBackend | Callable[[object], object]:
        if name not in self._instances:
            factory = self._factories.get(name)
            if factory is None:
                raise RuntimeError("backend factory unavailable")
            self._instances[name] = factory()
        return self._instances[name]

    @staticmethod
    def _invoke(backend: AsrBackend | Callable[[object], object], request: object) -> object:
        transcribe = getattr(backend, "transcribe", None)
        if callable(transcribe):
            return transcribe(request)
        if callable(backend):
            return backend(request)
        raise TypeError("ASR backend must be callable or expose transcribe")

    def dispatch(
        self, request: object, *, requested_backend: str | None = None
    ) -> DispatchOutcome:
        decision = select_backend(
            self._benchmark_result,
            requested_backend=requested_backend,
            capabilities=self._capabilities,
        )
        attempted: list[str] = []
        for index, name in enumerate(decision.fallback_order):
            attempted.append(name)
            try:
                value = self._invoke(self._load(name), request)
            except Exception:
                continue
            self._last_attempted = tuple(attempted)
            self._last_backend = name
            self._last_fallback_used = index > 0
            return DispatchOutcome(name, value, index > 0, tuple(attempted))
        self._last_attempted = tuple(attempted)
        self._last_backend = None
        self._last_fallback_used = False
        raise AsrDispatchError(attempted)

    def status_snapshot(self, *, requested_backend: str | None = None) -> dict[str, object]:
        assessment = assess_moonshine_benchmark(self._benchmark_result)
        decision = select_backend(
            self._benchmark_result,
            requested_backend=requested_backend,
            capabilities=self._capabilities,
        )
        capabilities = capability_snapshot(self._capabilities)
        for name in KNOWN_BACKENDS:
            capabilities[name]["configured"] = name in self._factories
            capabilities[name]["loaded"] = name in self._instances
        return {
            "schema": STATUS_SCHEMA,
            "production_default": DEFAULT_BACKEND,
            "selection": decision.as_dict(),
            "benchmark": assessment.as_dict(),
            "capabilities": capabilities,
            "last_dispatch": {
                "attempted_backends": list(self._last_attempted),
                "completed_backend": self._last_backend,
                "fallback_used": self._last_fallback_used,
            },
        }


__all__ = [
    "ASSESSMENT_SCHEMA",
    "BENCHMARK_RESULT_SCHEMA",
    "CANDIDATE_BACKEND",
    "DEFAULT_BACKEND",
    "STATUS_SCHEMA",
    "AsrDispatchError",
    "AsrDispatcher",
    "BenchmarkAssessment",
    "DispatchOutcome",
    "SelectionDecision",
    "assess_moonshine_benchmark",
    "capability_snapshot",
    "select_backend",
]
