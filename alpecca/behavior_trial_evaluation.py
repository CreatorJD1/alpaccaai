"""Pure Phase 8C3 evaluation for qualified-response behavior evidence.

This module never starts, completes, rolls back, or changes a trial. It turns a
validated trial record plus one aggregate-only outcome snapshot into a fixed
creator-review recommendation. Future route/controller work must still enforce
approval, timing, and exact rollback before it can act on the result.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from alpecca.qualified_response_ledger import DEFINITION_VERSION, METRIC_NAME


class BehaviorTrialEvaluationError(ValueError):
    """A trial record or aggregate evidence snapshot is not evaluable."""


_SHA256_RE = re.compile(r"[0-9a-f]{64}")
MIN_EVIDENCE_SAMPLES = 5
MIN_EFFECT_DELTA = 0.10
_RATE_TOLERANCE = 1e-12
_COUNT_FIELDS = (
    "dispatching",
    "pending",
    "qualified_responses",
    "unanswered",
    "cancelled",
    "completed",
)


def _mapping(value: object, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BehaviorTrialEvaluationError(f"{name} must be a mapping")
    return value


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BehaviorTrialEvaluationError(f"{name} must be a positive integer")
    return value


def _count(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BehaviorTrialEvaluationError(f"{name} must be a non-negative integer")
    return value


def _finite_rate(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BehaviorTrialEvaluationError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise BehaviorTrialEvaluationError(f"{name} must be a finite rate in [0, 1]")
    return result


def _trial_contract(record: object) -> tuple[int, str, float, int]:
    trial = _mapping(record, name="trial record")
    trial_id = _positive_int(trial.get("id"), name="trial id")
    spec_sha256 = trial.get("spec_sha256")
    if not isinstance(spec_sha256, str) or _SHA256_RE.fullmatch(spec_sha256) is None:
        raise BehaviorTrialEvaluationError("trial record needs an exact spec_sha256")
    spec = _mapping(trial.get("spec"), name="trial spec")
    if spec.get("metric") != METRIC_NAME:
        raise BehaviorTrialEvaluationError(
            f"trial metric must be {METRIC_NAME!r} for this evaluator"
        )
    return (
        trial_id,
        spec_sha256,
        _finite_rate(spec.get("baseline"), name="trial baseline"),
        _positive_int(spec.get("min_samples"), name="trial min_samples"),
    )


def _evidence_contract(
    evidence: object,
    *,
    expected_trial_id: int,
) -> dict[str, int | float | None]:
    snapshot = _mapping(evidence, name="outcome evidence")
    if snapshot.get("metric") != METRIC_NAME:
        raise BehaviorTrialEvaluationError("outcome evidence has the wrong metric")
    if snapshot.get("definition_version") != DEFINITION_VERSION:
        raise BehaviorTrialEvaluationError("outcome evidence has the wrong definition version")
    if _positive_int(snapshot.get("trial_id"), name="outcome trial_id") != expected_trial_id:
        raise BehaviorTrialEvaluationError("outcome evidence belongs to another trial")
    values: dict[str, int | float | None] = {
        name: _count(snapshot.get(name), name=f"outcome {name}")
        for name in _COUNT_FIELDS
    }
    completed = int(values["completed"])
    responses = int(values["qualified_responses"])
    unanswered = int(values["unanswered"])
    if completed != responses + unanswered:
        raise BehaviorTrialEvaluationError(
            "outcome completed count must equal responses plus unanswered"
        )
    raw_rate = snapshot.get("rate")
    if completed == 0:
        if raw_rate is not None:
            raise BehaviorTrialEvaluationError("empty outcome evidence must have a null rate")
        values["rate"] = None
    else:
        rate = _finite_rate(raw_rate, name="outcome rate")
        expected_rate = float(responses) / completed
        if not math.isclose(rate, expected_rate, rel_tol=0.0, abs_tol=1e-12):
            raise BehaviorTrialEvaluationError("outcome rate does not match its counts")
        values["rate"] = rate
    return values


def classify_effect_delta(delta: object) -> str:
    """Classify a settled rate delta using the code-owned effect threshold."""
    if isinstance(delta, bool) or not isinstance(delta, (int, float)):
        raise BehaviorTrialEvaluationError("effect delta must be numeric")
    effect = float(delta)
    if not math.isfinite(effect) or not -1.0 <= effect <= 1.0:
        raise BehaviorTrialEvaluationError("effect delta must be a finite rate delta")
    if effect > MIN_EFFECT_DELTA or math.isclose(
        effect,
        MIN_EFFECT_DELTA,
        rel_tol=0.0,
        abs_tol=_RATE_TOLERANCE,
    ):
        return "improved"
    if effect < -MIN_EFFECT_DELTA or math.isclose(
        effect,
        -MIN_EFFECT_DELTA,
        rel_tol=0.0,
        abs_tol=_RATE_TOLERANCE,
    ):
        return "degraded"
    return "inconclusive"


def evaluate_qualified_response_trial(
    trial_record: object,
    outcome_evidence: object,
) -> dict[str, Any]:
    """Return a fixed, non-mutating evaluation for one qualified-response trial.

    Evidence becomes reviewable only after both the code-owned evidence floor
    and the trial's immutable minimum sample count are met, and every confirmed
    exposure has settled. `comparison` requires a conservative absolute effect;
    it is descriptive, never an instruction to change a parameter automatically.
    """
    trial_id, spec_sha256, baseline, min_samples = _trial_contract(trial_record)
    evidence = _evidence_contract(outcome_evidence, expected_trial_id=trial_id)
    completed = int(evidence["completed"])
    outstanding = int(evidence["dispatching"]) + int(evidence["pending"])
    rate = evidence["rate"]
    required_samples = max(min_samples, MIN_EVIDENCE_SAMPLES)
    minimum_evidence_met = completed >= required_samples
    delta = None if rate is None else float(rate) - baseline
    if not minimum_evidence_met:
        readiness = "collecting"
        comparison = None
        recommendation = "continue_observation"
    elif outstanding:
        readiness = "awaiting_settlement"
        comparison = None
        recommendation = "continue_observation"
    else:
        readiness = "ready_for_creator_review"
        assert isinstance(rate, float)  # completed > 0 when min_samples is met
        assert isinstance(delta, float)
        comparison = classify_effect_delta(delta)
        recommendation = "creator_review_required"
    creator_retention_eligible = (
        readiness == "ready_for_creator_review" and comparison == "improved"
    )
    return {
        "metric": METRIC_NAME,
        "definition_version": DEFINITION_VERSION,
        "trial_id": trial_id,
        "spec_sha256": spec_sha256,
        "baseline": baseline,
        "min_samples": min_samples,
        "required_samples": required_samples,
        "minimum_evidence_met": minimum_evidence_met,
        "effect_threshold": MIN_EFFECT_DELTA,
        "qualified_responses": int(evidence["qualified_responses"]),
        "unanswered": int(evidence["unanswered"]),
        "completed": completed,
        "dispatching": int(evidence["dispatching"]),
        "pending": int(evidence["pending"]),
        "cancelled": int(evidence["cancelled"]),
        "rate": rate,
        "delta_from_baseline": delta,
        "readiness": readiness,
        "comparison": comparison,
        "recommendation": recommendation,
        # This is eligibility for a future creator-only decision to retain the
        # trial value. Evaluation itself never reapplies the rolled-back value.
        "creator_retention_eligible": creator_retention_eligible,
    }


__all__ = [
    "BehaviorTrialEvaluationError",
    "MIN_EFFECT_DELTA",
    "MIN_EVIDENCE_SAMPLES",
    "classify_effect_delta",
    "evaluate_qualified_response_trial",
]
