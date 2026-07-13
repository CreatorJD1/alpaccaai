"""Read-only Phase 8C7 review for a durably closed behavior trial.

The controller already closes a valid elapsed trial by restoring its exact
runtime preimage and writing a rollback receipt. This module turns that closed
record and aggregate qualified-response evidence into a fixed creator-review
snapshot. It never starts, completes, rolls back, retunes, or writes a trial.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from alpecca.behavior_trial_controller import TRIAL_EXPIRATION_REASON
from alpecca.behavior_trial_evaluation import (
    BehaviorTrialEvaluationError,
    evaluate_qualified_response_trial,
)
from alpecca import trial_ledger


class BehaviorTrialReviewError(ValueError):
    """A closed trial does not meet the fixed creator-review contract."""


class BehaviorTrialReviewEligibilityError(BehaviorTrialReviewError):
    """The trial did not close through its valid planned-exposure path."""


class BehaviorTrialReviewIntegrityError(BehaviorTrialReviewError):
    """The aggregate evidence failed the fixed evaluation contract."""


def _mapping(value: object, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BehaviorTrialReviewEligibilityError(f"{name} must be a mapping")
    return value


def _timestamp(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BehaviorTrialReviewEligibilityError(f"{name} must be numeric")
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0.0:
        raise BehaviorTrialReviewEligibilityError(
            f"{name} must be a finite non-negative timestamp"
        )
    return stamp


def _rate(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BehaviorTrialReviewEligibilityError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise BehaviorTrialReviewEligibilityError(
            f"{name} must be a finite rate in [0, 1]"
        )
    return result


def _closed_trial_contract(record: object) -> tuple[int, float, float, str]:
    trial = _mapping(record, name="trial record")
    trial_id = trial.get("id")
    if isinstance(trial_id, bool) or not isinstance(trial_id, int) or trial_id <= 0:
        raise BehaviorTrialReviewEligibilityError("trial id must be a positive integer")
    if trial.get("state") != trial_ledger.ROLLED_BACK:
        raise BehaviorTrialReviewEligibilityError(
            "creator review requires a durably rolled-back trial"
        )
    planned_end_at = _timestamp(trial.get("planned_end_at"), name="planned_end_at")
    ended_at = _timestamp(trial.get("ended_at"), name="ended_at")
    if ended_at < planned_end_at:
        raise BehaviorTrialReviewEligibilityError(
            "trial closure predates its planned exposure end"
        )
    spec = _mapping(trial.get("spec"), name="trial spec")
    parameter = spec.get("parameter")
    if not isinstance(parameter, str) or not parameter:
        raise BehaviorTrialReviewEligibilityError("trial parameter is required")
    old_value = _rate(spec.get("old_value"), name="trial old_value")
    rollback_value = _rate(
        spec.get("rollback_value"), name="trial rollback_value"
    )
    if rollback_value != old_value:
        raise BehaviorTrialReviewEligibilityError(
            "trial rollback value does not match its immutable old value"
        )
    rollback = _mapping(trial.get("rollback"), name="trial rollback")
    if rollback.get("reason") != TRIAL_EXPIRATION_REASON:
        raise BehaviorTrialReviewEligibilityError(
            "creator review requires the planned-exposure rollback receipt"
        )
    recorded_at = _timestamp(rollback.get("recorded_at"), name="rollback recorded_at")
    if recorded_at != ended_at:
        raise BehaviorTrialReviewEligibilityError(
            "rollback receipt does not match the durable trial closure"
        )
    expected_value = _rate(
        rollback.get("expected_value"), name="rollback expected_value"
    )
    restored_value = _rate(
        rollback.get("restored_value"), name="rollback restored_value"
    )
    if expected_value != old_value or restored_value != old_value:
        raise BehaviorTrialReviewEligibilityError(
            "rollback receipt does not prove restoration of the immutable old value"
        )
    rollback_evidence = _mapping(
        rollback.get("evidence"), name="rollback evidence"
    )
    if set(rollback_evidence) != {"runtime_override"}:
        raise BehaviorTrialReviewEligibilityError(
            "rollback evidence must contain only the runtime override receipt"
        )
    runtime_override = _mapping(
        rollback_evidence.get("runtime_override"),
        name="rollback runtime override evidence",
    )
    if (
        set(runtime_override)
        != {"parameter", "trial_id", "removed", "was_present"}
        or runtime_override.get("parameter") != parameter
        or runtime_override.get("trial_id") != trial_id
        or runtime_override.get("removed") is not True
        or not isinstance(runtime_override.get("was_present"), bool)
    ):
        raise BehaviorTrialReviewEligibilityError(
            "rollback evidence does not prove removal of the trial runtime override"
        )
    return trial_id, planned_end_at, ended_at, TRIAL_EXPIRATION_REASON


def review_closed_qualified_response_trial(
    trial_record: object,
    outcome_evidence: object,
) -> dict[str, Any]:
    """Return a fixed read-only creator-review snapshot for one closed trial.

    A valid elapsed trial may still have pending response windows. In that case
    it remains explicitly awaiting settlement. If all windows settle below the
    effective minimum sample count, the result is inconclusive rather than an
    instruction to alter behavior. Sufficient evidence is still inconclusive
    unless its absolute effect clears the code-owned conservative threshold.
    """
    trial_id, planned_end_at, ended_at, closure_reason = _closed_trial_contract(
        trial_record
    )
    try:
        evaluation = evaluate_qualified_response_trial(trial_record, outcome_evidence)
    except BehaviorTrialEvaluationError as exc:
        raise BehaviorTrialReviewIntegrityError(
            "qualified-response evidence is not eligible for creator review"
        ) from exc
    if int(evaluation["trial_id"]) != trial_id:  # defensive evaluator invariant
        raise BehaviorTrialReviewIntegrityError("review evidence belongs to another trial")

    outstanding = int(evaluation["dispatching"]) + int(evaluation["pending"])
    completed = int(evaluation["completed"])
    required_samples = int(evaluation["required_samples"])
    if outstanding:
        status = "awaiting_settlement"
        recommendation = "wait_for_settlement"
        outcome = None
        retention_reason = "outcomes_not_settled"
    elif completed < required_samples:
        status = "inconclusive_insufficient_samples"
        recommendation = "no_automatic_change"
        outcome = "inconclusive"
        retention_reason = "insufficient_evidence"
    elif evaluation["readiness"] == "ready_for_creator_review":
        status = "ready_for_creator_review"
        recommendation = "creator_review_required"
        outcome = evaluation["comparison"]
        if outcome not in {"improved", "degraded", "inconclusive"}:
            raise BehaviorTrialReviewIntegrityError(
                "review evaluation has an invalid settled outcome"
            )
        retention_reason = {
            "improved": "improvement_meets_threshold",
            "degraded": "degraded_outcome",
            "inconclusive": "effect_below_threshold",
        }[outcome]
    else:  # pragma: no cover - evaluator's fixed contract covers all cases above
        raise BehaviorTrialReviewIntegrityError("review evaluation has an invalid readiness")

    creator_retention_eligible = outcome == "improved"
    if bool(evaluation["creator_retention_eligible"]) != creator_retention_eligible:
        raise BehaviorTrialReviewIntegrityError(
            "review evaluation has inconsistent creator retention eligibility"
        )

    return {
        "trial_id": trial_id,
        "spec_sha256": str(evaluation["spec_sha256"]),
        "terminal_state": trial_ledger.ROLLED_BACK,
        "planned_end_at": planned_end_at,
        "ended_at": ended_at,
        "closure_reason": closure_reason,
        "status": status,
        "recommendation": recommendation,
        "outcome": outcome,
        # Eligibility concerns retaining the trial value after a separate future
        # creator decision. The exact baseline is already restored here.
        "creator_retention_eligible": creator_retention_eligible,
        "creator_retention_reason": retention_reason,
        "evaluation": evaluation,
    }


__all__ = [
    "BehaviorTrialReviewEligibilityError",
    "BehaviorTrialReviewError",
    "BehaviorTrialReviewIntegrityError",
    "review_closed_qualified_response_trial",
]
