"""Pure Phase 8C3 evaluation and per-trial aggregate coverage."""
from __future__ import annotations

import copy

import pytest

from alpecca import behavior_trial_evaluation as evaluation_mod
from alpecca import experiment_trials as trials_mod
from alpecca import qualified_response_ledger as ledger_mod
from alpecca import trial_ledger


def _trial_record(*, baseline: float = 0.5, min_samples: int = 5) -> dict:
    return {
        "id": 7,
        "spec_sha256": "a" * 64,
        "spec": {
            "metric": ledger_mod.METRIC_NAME,
            "baseline": baseline,
            "min_samples": min_samples,
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


@pytest.mark.parametrize(
    ("responses", "unanswered", "comparison", "retention_eligible"),
    [
        (7, 3, "improved", True),
        (5, 5, "inconclusive", False),
        (3, 7, "degraded", False),
    ],
)
def test_settled_minimum_sample_evaluation_is_fixed_and_creator_review_only(
    responses, unanswered, comparison, retention_eligible
):
    result = evaluation_mod.evaluate_qualified_response_trial(
        _trial_record(baseline=0.5, min_samples=5),
        _evidence(qualified_responses=responses, unanswered=unanswered),
    )

    assert result["readiness"] == "ready_for_creator_review"
    assert result["comparison"] == comparison
    assert result["recommendation"] == "creator_review_required"
    assert result["creator_retention_eligible"] is retention_eligible
    assert result["minimum_evidence_met"] is True
    assert result["required_samples"] == 5
    assert result["effect_threshold"] == evaluation_mod.MIN_EFFECT_DELTA
    assert result["completed"] == responses + unanswered
    assert result["delta_from_baseline"] == pytest.approx(result["rate"] - 0.5)


def test_evaluation_waits_for_minimum_samples_and_outstanding_exposures():
    collecting = evaluation_mod.evaluate_qualified_response_trial(
        _trial_record(min_samples=6),
        _evidence(qualified_responses=3, unanswered=2),
    )
    awaiting = evaluation_mod.evaluate_qualified_response_trial(
        _trial_record(min_samples=5),
        _evidence(qualified_responses=3, unanswered=2, pending=1),
    )

    assert collecting["readiness"] == "collecting"
    assert collecting["comparison"] is None
    assert collecting["recommendation"] == "continue_observation"
    assert collecting["creator_retention_eligible"] is False
    assert awaiting["readiness"] == "awaiting_settlement"
    assert awaiting["comparison"] is None
    assert awaiting["recommendation"] == "continue_observation"
    assert awaiting["creator_retention_eligible"] is False


def test_evaluation_never_treats_a_tiny_positive_all_time_delta_as_improvement():
    result = evaluation_mod.evaluate_qualified_response_trial(
        _trial_record(baseline=0.5, min_samples=5),
        _evidence(qualified_responses=51, unanswered=49),
    )

    assert result["readiness"] == "ready_for_creator_review"
    assert result["delta_from_baseline"] == pytest.approx(0.01)
    assert result["comparison"] == "inconclusive"
    assert result["creator_retention_eligible"] is False


def test_evaluation_enforces_the_code_owned_evidence_floor():
    result = evaluation_mod.evaluate_qualified_response_trial(
        _trial_record(min_samples=2),
        _evidence(qualified_responses=2, unanswered=2),
    )

    assert result["min_samples"] == 2
    assert result["required_samples"] == evaluation_mod.MIN_EVIDENCE_SAMPLES
    assert result["minimum_evidence_met"] is False
    assert result["readiness"] == "collecting"
    assert result["comparison"] is None
    assert result["creator_retention_eligible"] is False


@pytest.mark.parametrize(
    ("responses", "unanswered", "comparison"),
    [(3, 2, "improved"), (2, 3, "degraded")],
)
def test_effect_threshold_boundary_is_inclusive(responses, unanswered, comparison):
    result = evaluation_mod.evaluate_qualified_response_trial(
        _trial_record(baseline=0.5, min_samples=5),
        _evidence(qualified_responses=responses, unanswered=unanswered),
    )

    assert abs(result["delta_from_baseline"]) == pytest.approx(
        evaluation_mod.MIN_EFFECT_DELTA
    )
    assert result["comparison"] == comparison


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record, evidence: record["spec"].update(metric="other_metric"),
        lambda record, evidence: record.update(spec_sha256="upper"),
        lambda record, evidence: evidence.update(trial_id=8),
        lambda record, evidence: evidence.update(completed=99),
        lambda record, evidence: evidence.update(rate=0.8),
    ],
)
def test_evaluation_rejects_noncanonical_contracts(mutate):
    record = _trial_record(min_samples=2)
    evidence = _evidence(qualified_responses=1, unanswered=1)
    mutate(record, evidence)

    with pytest.raises(evaluation_mod.BehaviorTrialEvaluationError):
        evaluation_mod.evaluate_qualified_response_trial(record, evidence)


def test_evaluation_is_pure_and_does_not_mutate_inputs():
    record = _trial_record(min_samples=2)
    evidence = _evidence(qualified_responses=1, unanswered=1)
    original_record = copy.deepcopy(record)
    original_evidence = copy.deepcopy(evidence)

    evaluation_mod.evaluate_qualified_response_trial(record, evidence)

    assert record == original_record
    assert evidence == original_evidence


def test_evaluation_accepts_a_real_validated_trial_ledger_record(tmp_path):
    db_path = tmp_path / "shared-trials-and-outcomes.db"
    validated = trials_mod.validate_trial_spec(trials_mod.TrialSpecification(
        proposal_id=91,
        parameter="chatter_chance",
        hypothesis="A bounded change will improve qualified creator responses.",
        metric=ledger_mod.METRIC_NAME,
        baseline=0.5,
        exposure=trials_mod.ExposureWindow(300.0, 5),
        change=trials_mod.ParameterChange(0.25, 0.22),
        rollback_value=0.25,
    ))
    record = trial_ledger.register_trial(
        validated,
        scope=ledger_mod.CREATOR_PERSONAL_SCOPE,
        db_path=db_path,
    )
    outcomes = ledger_mod.QualifiedResponseLedger(db_path).trial_summary(record["id"])

    evaluation = evaluation_mod.evaluate_qualified_response_trial(record, outcomes)

    assert evaluation["trial_id"] == record["id"]
    assert evaluation["spec_sha256"] == record["spec_sha256"]
    assert evaluation["readiness"] == "collecting"
    assert evaluation["recommendation"] == "continue_observation"


def _dispatch(ledger, delivery_id: str, *, trial_id: int | None, at: float):
    return ledger.begin_dispatch(
        delivery_id=delivery_id,
        scope_key="creator:house-hq",
        surface="house-hq",
        proactive_turn_id=f"proactive-{delivery_id}",
        response_window_seconds=30.0,
        trial_id=trial_id,
        dispatched_at=at,
    )


def test_trial_summary_is_read_only_and_confined_to_one_trial(tmp_path, monkeypatch):
    ledger = ledger_mod.QualifiedResponseLedger(tmp_path / "outcomes.db")
    _dispatch(ledger, "baseline", trial_id=None, at=100.0)
    ledger.confirm_delivery("baseline", delivered_at=101.0)
    ledger.record_creator_response(
        scope_key="creator:house-hq",
        surface="house-hq",
        response_turn_id="baseline-response",
        received_at=102.0,
    )
    _dispatch(ledger, "trial-seven-response", trial_id=7, at=103.0)
    ledger.confirm_delivery("trial-seven-response", delivered_at=104.0)
    ledger.record_creator_response(
        scope_key="creator:house-hq",
        surface="house-hq",
        response_turn_id="trial-seven-response-turn",
        received_at=105.0,
    )
    _dispatch(ledger, "trial-seven-unanswered", trial_id=7, at=106.0)
    ledger.confirm_delivery("trial-seven-unanswered", delivered_at=107.0)
    _dispatch(ledger, "trial-eight", trial_id=8, at=108.0)
    ledger.confirm_delivery("trial-eight", delivered_at=109.0)
    ledger.expire_due(now=140.0)

    original_connect = ledger_mod.sqlite3.connect
    statements: list[str] = []

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(ledger_mod.sqlite3, "connect", traced_connect)
    summary = ledger.trial_summary(7)

    assert summary == {
        "metric": ledger_mod.METRIC_NAME,
        "definition_version": ledger_mod.DEFINITION_VERSION,
        "trial_id": 7,
        "dispatching": 0,
        "pending": 0,
        "qualified_responses": 1,
        "unanswered": 1,
        "cancelled": 0,
        "completed": 2,
        "rate": 0.5,
    }
    assert ledger.trial_summary(8)["unanswered"] == 1
    assert ledger.summary()["baseline"]["qualified_responses"] == 1
    assert statements
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    with pytest.raises(ledger_mod.QualifiedResponseLedgerError):
        ledger.trial_summary(0)


def test_baseline_summary_starts_fresh_after_profile_decision(tmp_path):
    ledger = ledger_mod.QualifiedResponseLedger(tmp_path / "outcomes.db")
    _dispatch(ledger, "old-baseline", trial_id=None, at=100.0)
    ledger.confirm_delivery("old-baseline", delivered_at=101.0)
    ledger.record_creator_response(
        scope_key="creator:house-hq",
        surface="house-hq",
        response_turn_id="old-response",
        received_at=102.0,
    )
    _dispatch(ledger, "new-baseline", trial_id=None, at=201.0)
    ledger.confirm_delivery("new-baseline", delivered_at=202.0)
    ledger.expire_due(now=233.0)

    assert ledger.baseline_summary()["completed"] == 2
    assert ledger.baseline_summary(since=200.0) == {
        "metric": ledger_mod.METRIC_NAME,
        "definition_version": ledger_mod.DEFINITION_VERSION,
        "since": 200.0,
        "dispatching": 0,
        "pending": 0,
        "qualified_responses": 0,
        "unanswered": 1,
        "cancelled": 0,
        "completed": 1,
        "rate": 0.0,
    }
