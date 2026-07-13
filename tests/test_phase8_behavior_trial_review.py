"""Pure Phase 8C7 closed-trial creator-review contract."""
from __future__ import annotations

import copy

import pytest

from alpecca import behavior_trial_review as review_mod
from alpecca import qualified_response_ledger as ledger_mod


def _trial_record(*, baseline: float = 0.5, min_samples: int = 5) -> dict:
    return {
        "id": 7,
        "state": "rolled_back",
        "spec_sha256": "a" * 64,
        "spec": {
            "parameter": "chatter_chance",
            "metric": ledger_mod.METRIC_NAME,
            "baseline": baseline,
            "min_samples": min_samples,
            "old_value": 0.25,
            "rollback_value": 0.25,
        },
        "planned_end_at": 200.0,
        "ended_at": 200.0,
        "rollback": {
            "recorded_at": 200.0,
            "expected_value": 0.25,
            "restored_value": 0.25,
            "reason": "planned behavior trial exposure elapsed",
            "evidence": {
                "runtime_override": {
                    "parameter": "chatter_chance",
                    "trial_id": 7,
                    "removed": True,
                    "was_present": True,
                }
            },
        },
    }


def _evidence(
    *,
    qualified_responses: int = 0,
    unanswered: int = 0,
    dispatching: int = 0,
    pending: int = 0,
    cancelled: int = 0,
) -> dict:
    completed = qualified_responses + unanswered
    return {
        "metric": ledger_mod.METRIC_NAME,
        "definition_version": ledger_mod.DEFINITION_VERSION,
        "trial_id": 7,
        "qualified_responses": qualified_responses,
        "unanswered": unanswered,
        "completed": completed,
        "dispatching": dispatching,
        "pending": pending,
        "cancelled": cancelled,
        "rate": None if completed == 0 else qualified_responses / completed,
    }


def test_closed_settled_trial_is_ready_for_creator_review_without_action():
    result = review_mod.review_closed_qualified_response_trial(
        _trial_record(),
        _evidence(qualified_responses=3, unanswered=2),
    )

    assert result["terminal_state"] == "rolled_back"
    assert result["closure_reason"] == "planned behavior trial exposure elapsed"
    assert result["status"] == "ready_for_creator_review"
    assert result["recommendation"] == "creator_review_required"
    assert result["outcome"] == "improved"
    assert result["creator_retention_eligible"] is True
    assert result["creator_retention_reason"] == "improvement_meets_threshold"
    assert result["evaluation"]["comparison"] == "improved"
    assert result["evaluation"]["recommendation"] == "creator_review_required"


def test_closed_trial_waits_for_outcome_settlement_before_review():
    result = review_mod.review_closed_qualified_response_trial(
        _trial_record(),
        _evidence(qualified_responses=5, pending=1),
    )

    assert result["status"] == "awaiting_settlement"
    assert result["recommendation"] == "wait_for_settlement"
    assert result["outcome"] is None
    assert result["creator_retention_eligible"] is False
    assert result["creator_retention_reason"] == "outcomes_not_settled"
    assert result["evaluation"]["readiness"] == "awaiting_settlement"


def test_closed_trial_with_too_few_settled_samples_is_inconclusive():
    result = review_mod.review_closed_qualified_response_trial(
        _trial_record(min_samples=5),
        _evidence(qualified_responses=2, unanswered=2),
    )

    assert result["status"] == "inconclusive_insufficient_samples"
    assert result["recommendation"] == "no_automatic_change"
    assert result["outcome"] == "inconclusive"
    assert result["creator_retention_eligible"] is False
    assert result["creator_retention_reason"] == "insufficient_evidence"
    assert result["evaluation"]["readiness"] == "collecting"


@pytest.mark.parametrize(
    ("baseline", "responses", "unanswered", "outcome", "reason"),
    [
        (0.5, 2, 3, "degraded", "degraded_outcome"),
        (0.55, 3, 2, "inconclusive", "effect_below_threshold"),
    ],
)
def test_closed_review_separates_non_improving_outcomes_from_retention(
    baseline, responses, unanswered, outcome, reason
):
    result = review_mod.review_closed_qualified_response_trial(
        _trial_record(baseline=baseline),
        _evidence(qualified_responses=responses, unanswered=unanswered),
    )

    assert result["status"] == "ready_for_creator_review"
    assert result["outcome"] == outcome
    assert result["creator_retention_eligible"] is False
    assert result["creator_retention_reason"] == reason
    assert result["evaluation"]["comparison"] == outcome


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record, evidence: record.update(state="running"),
        lambda record, evidence: record["rollback"].update(reason="manual rollback"),
        lambda record, evidence: record.update(ended_at=199.0),
        lambda record, evidence: record["rollback"].update(recorded_at=201.0),
    ],
)
def test_review_rejects_trials_without_a_valid_elapsed_closure(mutate):
    record = _trial_record()
    evidence = _evidence(qualified_responses=3, unanswered=1)
    mutate(record, evidence)

    with pytest.raises(review_mod.BehaviorTrialReviewEligibilityError):
        review_mod.review_closed_qualified_response_trial(record, evidence)


def test_review_rejects_invalid_outcome_evidence_and_is_pure():
    record = _trial_record()
    evidence = _evidence(qualified_responses=3, unanswered=1)
    evidence["trial_id"] = 8
    original_record = copy.deepcopy(record)
    original_evidence = copy.deepcopy(evidence)

    with pytest.raises(review_mod.BehaviorTrialReviewIntegrityError):
        review_mod.review_closed_qualified_response_trial(record, evidence)

    assert record == original_record
    assert evidence == original_evidence


def test_review_rejects_false_rollback_value_and_empty_evidence():
    record = _trial_record()
    record["rollback"]["restored_value"] = 0.99
    record["rollback"]["evidence"] = {}

    with pytest.raises(
        review_mod.BehaviorTrialReviewEligibilityError,
        match="immutable old value",
    ):
        review_mod.review_closed_qualified_response_trial(
            record,
            _evidence(qualified_responses=3, unanswered=2),
        )
