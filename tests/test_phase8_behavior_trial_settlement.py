"""Durable Phase 8C7 settlement coverage."""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from alpecca import behavior_trial_settlement as settlement_mod
from alpecca import experiment_trials as trials_mod
from alpecca import qualified_response_ledger as outcome_mod
from alpecca import trial_ledger
from alpecca.behavior_trial_controller import TRIAL_EXPIRATION_REASON


SCOPE = outcome_mod.CREATOR_PERSONAL_SCOPE


def _closed_trial(
    db_path,
    *,
    proposal_id: int = 71,
    min_samples: int = 5,
    baseline: float = 0.5,
) -> dict:
    validated = trials_mod.validate_trial_spec(trials_mod.TrialSpecification(
        proposal_id=proposal_id,
        parameter="chatter_chance",
        hypothesis="A bounded chance change may improve qualified creator responses.",
        metric=outcome_mod.METRIC_NAME,
        baseline=baseline,
        exposure=trials_mod.ExposureWindow(300.0, min_samples),
        change=trials_mod.ParameterChange(0.25, 0.22),
        rollback_value=0.25,
    ))
    registered = trial_ledger.register_trial(
        validated,
        scope=SCOPE,
        created_at=50.0,
        db_path=db_path,
    )
    trial_ledger.approve_trial(
        registered["id"],
        trial_ledger.ProposalApprovalProof(
            proposal_id=proposal_id,
            scope=SCOPE,
            proof_id=f"proof-{proposal_id}",
            authority="test",
            approved_at=90.0,
        ),
        scope=SCOPE,
        db_path=db_path,
    )
    running = trial_ledger.start_trial(
        registered["id"],
        scope=SCOPE,
        started_at=100.0,
        db_path=db_path,
    )
    return trial_ledger.record_rollback(
        running["id"],
        scope=SCOPE,
        restored_value=0.25,
        reason=TRIAL_EXPIRATION_REASON,
        recorded_at=400.0,
        evidence={
            "runtime_override": {
                "parameter": "chatter_chance",
                "trial_id": running["id"],
                "removed": True,
                "was_present": True,
            }
        },
        db_path=db_path,
    )


def _begin(ledger, delivery_id: str, *, trial_id: int, at: float) -> None:
    ledger.begin_dispatch(
        delivery_id=delivery_id,
        scope_key="creator:house-hq",
        surface="house-hq",
        proactive_turn_id=f"turn-{delivery_id}",
        response_window_seconds=30.0,
        trial_id=trial_id,
        dispatched_at=at,
    )


def _respond(ledger, delivery_id: str, *, trial_id: int, at: float) -> None:
    _begin(ledger, delivery_id, trial_id=trial_id, at=at)
    ledger.confirm_delivery(delivery_id, delivered_at=at + 1.0)
    ledger.record_creator_response(
        scope_key="creator:house-hq",
        surface="house-hq",
        response_turn_id=f"response-{delivery_id}",
        received_at=at + 2.0,
    )


def _leave_unanswered(ledger, delivery_id: str, *, trial_id: int, at: float) -> None:
    _begin(ledger, delivery_id, trial_id=trial_id, at=at)
    ledger.confirm_delivery(delivery_id, delivered_at=at + 1.0)


def test_settlement_freezes_trial_evidence_and_blocks_new_trial_outcomes(tmp_path):
    db_path = tmp_path / "settlement.db"
    trial = _closed_trial(db_path)
    ledger = outcome_mod.QualifiedResponseLedger(db_path)
    settlement_mod.init_db(db_path)
    for index in range(3):
        _respond(ledger, f"response-{index}", trial_id=trial["id"], at=120.0 + index * 10.0)
    for index in range(2):
        delivery_id = f"unanswered-{index}"
        _begin(ledger, delivery_id, trial_id=trial["id"], at=160.0 + index * 10.0)
        ledger.confirm_delivery(delivery_id, delivered_at=161.0 + index * 10.0)
    ledger.expire_due(now=250.0)

    created = settlement_mod.settle_closed_trials(db_path, settled_at=500.0)

    assert len(created) == 1
    settled = created[0]
    assert settled["trial_id"] == trial["id"]
    assert settled["settled_at"] == 500.0
    assert settled["status"] == "ready_for_creator_review"
    assert settled["recommendation"] == "creator_review_required"
    assert settled["outcome"] == "improved"
    assert settled["creator_retention_eligible"] is True
    assert settled["creator_retention_reason"] == "improvement_meets_threshold"
    assert settled["review"]["outcome"] == "improved"
    assert settled["review"]["evaluation"]["effect_threshold"] == 0.1
    assert settled["evidence"] == {
        "metric": outcome_mod.METRIC_NAME,
        "definition_version": outcome_mod.DEFINITION_VERSION,
        "trial_id": trial["id"],
        "dispatching": 0,
        "pending": 0,
        "qualified_responses": 3,
        "unanswered": 2,
        "cancelled": 0,
        "completed": 5,
        "rate": 0.6,
    }
    assert settlement_mod.get_settlement(trial["id"], db_path) == settled
    assert settlement_mod.list_settlements(db_path, limit=5) == [settled]
    assert settlement_mod.settle_closed_trials(db_path, settled_at=501.0) == []

    with pytest.raises(sqlite3.IntegrityError, match="settled behavior trial"):
        _begin(ledger, "late-outcome", trial_id=trial["id"], at=600.0)


def test_settlement_waits_for_pending_outcomes_then_records_final_inconclusive_result(tmp_path):
    db_path = tmp_path / "pending-settlement.db"
    trial = _closed_trial(db_path, min_samples=5)
    ledger = outcome_mod.QualifiedResponseLedger(db_path)
    settlement_mod.init_db(db_path)
    _begin(ledger, "pending", trial_id=trial["id"], at=120.0)
    ledger.confirm_delivery("pending", delivered_at=121.0)

    assert settlement_mod.settle_closed_trials(db_path, settled_at=500.0) == []

    ledger.expire_due(now=500.0)
    settled = settlement_mod.settle_closed_trials(db_path, settled_at=501.0)

    assert len(settled) == 1
    assert settled[0]["status"] == "inconclusive_insufficient_samples"
    assert settled[0]["recommendation"] == "no_automatic_change"
    assert settled[0]["outcome"] == "inconclusive"
    assert settled[0]["creator_retention_eligible"] is False
    assert settled[0]["creator_retention_reason"] == "insufficient_evidence"
    assert settled[0]["review"]["evaluation"]["readiness"] == "collecting"


@pytest.mark.parametrize(
    ("baseline", "responses", "unanswered", "outcome", "reason"),
    [
        (0.5, 2, 3, "degraded", "degraded_outcome"),
        (0.55, 3, 2, "inconclusive", "effect_below_threshold"),
    ],
)
def test_settlement_separates_non_improving_outcomes_from_creator_retention(
    tmp_path, baseline, responses, unanswered, outcome, reason
):
    db_path = tmp_path / f"{outcome}.db"
    trial = _closed_trial(db_path, baseline=baseline)
    ledger = outcome_mod.QualifiedResponseLedger(db_path)
    settlement_mod.init_db(db_path)
    for index in range(responses):
        _respond(ledger, f"response-{index}", trial_id=trial["id"], at=120.0 + index * 5.0)
    for index in range(unanswered):
        _leave_unanswered(
            ledger,
            f"unanswered-{index}",
            trial_id=trial["id"],
            at=200.0 + index * 5.0,
        )
    ledger.expire_due(now=300.0)

    settled = settlement_mod.settle_closed_trials(db_path, settled_at=500.0)[0]
    binding = settlement_mod.get_settlement_binding(trial["id"], db_path)

    assert settled["status"] == "ready_for_creator_review"
    assert settled["outcome"] == outcome
    assert settled["creator_retention_eligible"] is False
    assert settled["creator_retention_reason"] == reason
    assert settled["review"]["outcome"] == outcome
    assert settled["review"]["evaluation"]["comparison"] == outcome
    assert binding is not None
    assert binding["outcome"] == outcome
    assert binding["creator_retention_eligible"] is False
    assert binding["creator_retention_reason"] == reason


def _rewrite_review(db_path, trial_id: int, mutate) -> None:
    with sqlite3.connect(db_path) as conn:
        raw = conn.execute(
            "SELECT review_json FROM behavior_trial_settlements WHERE trial_id=?",
            (trial_id,),
        ).fetchone()[0]
        review = json.loads(raw)
        mutate(review)
        rewritten = json.dumps(
            review,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        conn.execute(
            """
            UPDATE behavior_trial_settlements
            SET review_json=?, review_sha256=?
            WHERE trial_id=?
            """,
            (
                rewritten,
                hashlib.sha256(rewritten.encode("utf-8")).hexdigest(),
                trial_id,
            ),
        )


def _rewrite_evidence(db_path, trial_id: int, mutate) -> None:
    with sqlite3.connect(db_path) as conn:
        raw = conn.execute(
            "SELECT evidence_json FROM behavior_trial_settlements WHERE trial_id=?",
            (trial_id,),
        ).fetchone()[0]
        evidence = json.loads(raw)
        mutate(evidence)
        rewritten = json.dumps(
            evidence,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        conn.execute(
            """
            UPDATE behavior_trial_settlements
            SET evidence_json=?, evidence_sha256=?
            WHERE trial_id=?
            """,
            (
                rewritten,
                hashlib.sha256(rewritten.encode("utf-8")).hexdigest(),
                trial_id,
            ),
        )


def test_settlement_rejects_rehashed_mutable_review_baseline(tmp_path):
    db_path = tmp_path / "forged-baseline.db"
    trial = _closed_trial(db_path, baseline=0.55)
    ledger = outcome_mod.QualifiedResponseLedger(db_path)
    settlement_mod.init_db(db_path)
    for index in range(3):
        _respond(ledger, f"response-{index}", trial_id=trial["id"], at=120.0 + index)
    for index in range(2):
        _leave_unanswered(
            ledger,
            f"unanswered-{index}",
            trial_id=trial["id"],
            at=140.0 + index,
        )
    ledger.expire_due(now=300.0)
    settlement_mod.settle_closed_trials(db_path, settled_at=500.0)

    def forge_lower_baseline(review):
        evaluation = review["evaluation"]
        evaluation["baseline"] = 0.4
        evaluation["delta_from_baseline"] = 0.2
        evaluation["comparison"] = "improved"
        evaluation["creator_retention_eligible"] = True
        review["outcome"] = "improved"
        review["creator_retention_eligible"] = True
        review["creator_retention_reason"] = "improvement_meets_threshold"

    _rewrite_review(db_path, trial["id"], forge_lower_baseline)

    with pytest.raises(settlement_mod.BehaviorTrialSettlementError, match="invalid"):
        settlement_mod.get_settlement(trial["id"], db_path)


def test_settlement_rejects_rehashed_evidence_not_in_outcome_ledger(tmp_path):
    db_path = tmp_path / "forged-evidence.db"
    trial = _closed_trial(db_path)
    ledger = outcome_mod.QualifiedResponseLedger(db_path)
    settlement_mod.init_db(db_path)
    _respond(ledger, "response", trial_id=trial["id"], at=120.0)
    settlement_mod.settle_closed_trials(db_path, settled_at=500.0)

    def forge_extra_response(evidence):
        evidence["qualified_responses"] = 2
        evidence["completed"] = 2
        evidence["rate"] = 1.0

    _rewrite_evidence(db_path, trial["id"], forge_extra_response)

    with pytest.raises(
        settlement_mod.BehaviorTrialSettlementError,
        match="outcome ledger",
    ):
        settlement_mod.get_settlement(trial["id"], db_path)


def test_settlement_rejects_substituted_spec_digest(tmp_path):
    db_path = tmp_path / "forged-spec.db"
    trial = _closed_trial(db_path)
    settlement_mod.init_db(db_path)
    settlement_mod.settle_closed_trials(db_path, settled_at=500.0)
    forged_digest = "b" * 64

    def forge_review_binding(review):
        review["spec_sha256"] = forged_digest
        review["evaluation"]["spec_sha256"] = forged_digest

    _rewrite_review(db_path, trial["id"], forge_review_binding)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE behavior_trial_settlements SET spec_sha256=? WHERE trial_id=?",
            (forged_digest, trial["id"]),
        )

    with pytest.raises(
        settlement_mod.BehaviorTrialSettlementError,
        match="immutable trial specification",
    ):
        settlement_mod.get_settlement(trial["id"], db_path)


def test_settlement_rejects_false_rollback_row_and_empty_evidence(tmp_path):
    db_path = tmp_path / "forged-rollback.db"
    trial = _closed_trial(db_path)
    settlement_mod.init_db(db_path)
    settlement_mod.settle_closed_trials(db_path, settled_at=500.0)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE experiment_trial_rollbacks
            SET expected_value=0.99, restored_value=0.99, evidence_json='{}'
            WHERE trial_id=?
            """,
            (trial["id"],),
        )

    with pytest.raises(
        settlement_mod.BehaviorTrialSettlementError,
        match="rollback contract",
    ):
        settlement_mod.get_settlement(trial["id"], db_path)


def test_settlement_rejects_rehashed_retention_eligibility_without_effect(tmp_path):
    db_path = tmp_path / "false-retention.db"
    trial = _closed_trial(db_path, baseline=0.55)
    ledger = outcome_mod.QualifiedResponseLedger(db_path)
    settlement_mod.init_db(db_path)
    for index in range(3):
        _respond(ledger, f"response-{index}", trial_id=trial["id"], at=120.0 + index * 5.0)
    for index in range(2):
        _leave_unanswered(
            ledger,
            f"unanswered-{index}",
            trial_id=trial["id"],
            at=200.0 + index * 5.0,
        )
    ledger.expire_due(now=300.0)
    settlement_mod.settle_closed_trials(db_path, settled_at=500.0)

    def claim_improvement(review):
        review["outcome"] = "improved"
        review["creator_retention_eligible"] = True
        review["creator_retention_reason"] = "improvement_meets_threshold"
        review["evaluation"]["comparison"] = "improved"
        review["evaluation"]["creator_retention_eligible"] = True

    _rewrite_review(db_path, trial["id"], claim_improvement)

    with pytest.raises(settlement_mod.BehaviorTrialSettlementError, match="invalid"):
        settlement_mod.get_settlement(trial["id"], db_path)


def test_legacy_tiny_positive_settlement_is_readable_but_ineligible(tmp_path):
    db_path = tmp_path / "legacy-tiny-positive.db"
    trial = _closed_trial(db_path, baseline=0.55)
    ledger = outcome_mod.QualifiedResponseLedger(db_path)
    settlement_mod.init_db(db_path)
    for index in range(3):
        _respond(ledger, f"response-{index}", trial_id=trial["id"], at=120.0 + index * 5.0)
    for index in range(2):
        _leave_unanswered(
            ledger,
            f"unanswered-{index}",
            trial_id=trial["id"],
            at=200.0 + index * 5.0,
        )
    ledger.expire_due(now=300.0)
    settlement_mod.settle_closed_trials(db_path, settled_at=500.0)

    def convert_to_legacy(review):
        review.pop("outcome")
        review.pop("creator_retention_eligible")
        review.pop("creator_retention_reason")
        evaluation = review["evaluation"]
        evaluation.pop("required_samples")
        evaluation.pop("minimum_evidence_met")
        evaluation.pop("effect_threshold")
        evaluation.pop("creator_retention_eligible")
        evaluation["comparison"] = "improved"

    _rewrite_review(db_path, trial["id"], convert_to_legacy)

    stored = settlement_mod.get_settlement(trial["id"], db_path)

    assert stored is not None
    assert stored["review"]["evaluation"]["comparison"] == "improved"
    assert stored["outcome"] == "inconclusive"
    assert stored["creator_retention_eligible"] is False
    assert stored["creator_retention_reason"] == "effect_below_threshold"


def test_only_planned_expiry_rollbacks_can_be_settled(tmp_path):
    db_path = tmp_path / "manual-rollback.db"
    trial = _closed_trial(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE experiment_trial_rollbacks SET reason='manual close' WHERE trial_id=?",
            (trial["id"],),
        )
        conn.commit()
    settlement_mod.init_db(db_path)

    assert settlement_mod.settle_closed_trials(db_path, settled_at=500.0) == []
    assert settlement_mod.get_settlement(trial["id"], db_path) is None


def test_settlement_read_is_select_only_and_detects_digest_tampering(tmp_path, monkeypatch):
    db_path = tmp_path / "read-only-settlement.db"
    trial = _closed_trial(db_path, min_samples=5)
    ledger = outcome_mod.QualifiedResponseLedger(db_path)
    settlement_mod.init_db(db_path)
    _respond(ledger, "response", trial_id=trial["id"], at=120.0)
    settlement_mod.settle_closed_trials(db_path, settled_at=500.0)

    original_connect = settlement_mod.sqlite3.connect
    statements: list[str] = []

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(settlement_mod.sqlite3, "connect", traced_connect)
    stored = settlement_mod.get_settlement(trial["id"], db_path)

    assert stored is not None
    assert statements
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)

    monkeypatch.setattr(settlement_mod.sqlite3, "connect", original_connect)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE behavior_trial_settlements SET evidence_json='{}' WHERE trial_id=?",
            (trial["id"],),
        )
        conn.commit()
    with pytest.raises(settlement_mod.BehaviorTrialSettlementError, match="digest"):
        settlement_mod.get_settlement(trial["id"], db_path)


@pytest.mark.parametrize("limit", [0, 26, True, "5"])
def test_settlement_list_rejects_invalid_limits(tmp_path, limit):
    with pytest.raises(settlement_mod.BehaviorTrialSettlementError, match="limit"):
        settlement_mod.list_settlements(tmp_path / "missing.db", limit=limit)
