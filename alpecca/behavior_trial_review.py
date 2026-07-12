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
    return trial_id, planned_end_at, ended_at, TRIAL_EXPIRATION_REASON


def review_closed_qualified_response_trial(
    trial_record: object,
    outcome_evidence: object,
) -> dict[str, Any]:
    """Return a fixed read-only creator-review snapshot for one closed trial.

    A valid elapsed trial may still have pending response windows. In that case
    it remains explicitly awaiting settlement. If all windows settle below the
    immutable minimum sample count, the result is inconclusive rather than an
    instruction to alter behavior. Only settled evidence at or above the fixed
    threshold becomes ready for creator review.
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
    min_samples = int(evaluation["min_samples"])
    if outstanding:
        status = "awaiting_settlement"
        recommendation = "wait_for_settlement"
    elif completed < min_samples:
        status = "inconclusive_insufficient_samples"
        recommendation = "no_automatic_change"
    elif evaluation["readiness"] == "ready_for_creator_review":
        status = "ready_for_creator_review"
        recommendation = "creator_review_required"
    else:  # pragma: no cover - evaluator's fixed contract covers all cases above
        raise BehaviorTrialReviewIntegrityError("review evaluation has an invalid readiness")

    return {
        "trial_id": trial_id,
        "spec_sha256": str(evaluation["spec_sha256"]),
        "terminal_state": trial_ledger.ROLLED_BACK,
        "planned_end_at": planned_end_at,
        "ended_at": ended_at,
        "closure_reason": closure_reason,
        "status": status,
        "recommendation": recommendation,
        "evaluation": evaluation,
    }


__all__ = [
    "BehaviorTrialReviewEligibilityError",
    "BehaviorTrialReviewError",
    "BehaviorTrialReviewIntegrityError",
    "review_closed_qualified_response_trial",
]
