from __future__ import annotations

import sqlite3

import pytest

from alpecca import behavior_trial_review_decisions as decisions_mod
from alpecca import behavior_trial_settlement as settlement_mod
from alpecca import experiment_trials as trials_mod
from alpecca import qualified_response_ledger as outcome_mod
from alpecca import trial_ledger
from alpecca.behavior_trial_controller import TRIAL_EXPIRATION_REASON


SEAL_KEY = b"phase8c9-test-only-review-decision-seal-key"
SCOPE = outcome_mod.CREATOR_PERSONAL_SCOPE


def _closed_trial(db_path, *, proposal_id: int, min_samples: int = 5) -> dict:
    spec = trials_mod.validate_trial_spec(trials_mod.TrialSpecification(
        proposal_id=proposal_id,
        parameter="chatter_chance",
        hypothesis="A bounded chance change may improve qualified creator responses.",
        metric=outcome_mod.METRIC_NAME,
        baseline=0.5,
        exposure=trials_mod.ExposureWindow(300.0, min_samples),
        change=trials_mod.ParameterChange(0.25, 0.22),
        rollback_value=0.25,
    ))
    registered = trial_ledger.register_trial(
        spec,
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


def _respond(ledger, delivery_id: str, *, trial_id: int, at: float) -> None:
    ledger.begin_dispatch(
        delivery_id=delivery_id,
        scope_key="creator:house-hq",
        surface="house-hq",
        proactive_turn_id=f"turn-{delivery_id}",
        response_window_seconds=30.0,
        trial_id=trial_id,
        dispatched_at=at,
    )
    ledger.confirm_delivery(delivery_id, delivered_at=at + 1.0)
    ledger.record_creator_response(
        scope_key="creator:house-hq",
        surface="house-hq",
        response_turn_id=f"response-{delivery_id}",
        received_at=at + 2.0,
    )


def _ready_settlement(db_path, *, proposal_id: int = 71, min_samples: int = 5) -> dict:
    trial = _closed_trial(db_path, proposal_id=proposal_id, min_samples=min_samples)
    ledger = outcome_mod.QualifiedResponseLedger(db_path)
    settlement_mod.init_db(db_path)
    for index in range(min_samples):
        _respond(ledger, f"response-{proposal_id}-{index}", trial_id=trial["id"], at=120.0 + index * 10.0)
    settled = settlement_mod.settle_closed_trials(db_path, settled_at=500.0)
    assert len(settled) == 1
    return settled[0]


def _store(db_path):
    return decisions_mod.BehaviorTrialReviewDecisionStore(db_path, seal_key=SEAL_KEY)


def test_frozen_settlement_binding_exposes_only_digest_metadata(tmp_path):
    db_path = tmp_path / "binding.db"
    settled = _ready_settlement(db_path)

    binding = settlement_mod.get_settlement_binding(settled["trial_id"], db_path)

    assert binding is not None
    assert binding["trial_id"] == settled["trial_id"]
    assert binding["spec_sha256"] == settled["spec_sha256"]
    assert len(binding["evidence_sha256"]) == 64
    assert len(binding["review_sha256"]) == 64
    assert "evidence" not in binding
    assert "review" not in binding


def test_creator_can_record_one_idempotent_baseline_retention_decision(tmp_path):
    db_path = tmp_path / "decision.db"
    settled = _ready_settlement(db_path)
    store = _store(db_path)

    first, created = store.acknowledge(
        settled["trial_id"],
        principal="creator",
        authorization_mechanism="session_cookie",
        authorization_issued_at=100.0,
        authorization_expires_at=200.0,
        decided_at=600.0,
    )
    retry, created_retry = store.acknowledge(
        settled["trial_id"],
        principal="creator",
        authorization_mechanism="bearer",
        decided_at=601.0,
    )

    assert created is True
    assert created_retry is False
    assert first == retry == {
        "trial_id": settled["trial_id"],
        "decision": decisions_mod.RETAIN_BASELINE,
        "decided_at": 600.0,
        "settlement_status": "ready_for_creator_review",
    }
    assert store.get(settled["trial_id"]) == first
    assert store.list(limit=5) == [first]


def test_inconclusive_frozen_review_can_only_record_baseline_retention(tmp_path):
    db_path = tmp_path / "inconclusive.db"
    trial = _closed_trial(db_path, proposal_id=72, min_samples=5)
    settlement_mod.init_db(db_path)
    settled = settlement_mod.settle_closed_trials(db_path, settled_at=500.0)
    assert settled[0]["status"] == "inconclusive_insufficient_samples"
    store = _store(db_path)

    decision, created = store.acknowledge(
        trial["id"],
        principal="creator",
        authorization_mechanism="bearer",
        decided_at=600.0,
    )

    assert created is True
    assert decision["decision"] == decisions_mod.RETAIN_BASELINE
    assert decision["settlement_status"] == "inconclusive_insufficient_samples"


def test_decision_fails_closed_without_frozen_settlement_or_creator(tmp_path):
    db_path = tmp_path / "missing.db"
    store = _store(db_path)

    with pytest.raises(decisions_mod.ReviewDecisionNotEligible):
        store.acknowledge(
            1,
            principal="creator",
            authorization_mechanism="bearer",
            decided_at=600.0,
        )
    settled = _ready_settlement(db_path, proposal_id=73)
    with pytest.raises(decisions_mod.ReviewDecisionNotEligible):
        store.acknowledge(
            settled["trial_id"],
            principal="guest",
            authorization_mechanism="bearer",
            decided_at=600.0,
        )


def test_decision_detects_settlement_or_receipt_tampering(tmp_path):
    db_path = tmp_path / "tamper.db"
    settled = _ready_settlement(db_path)
    store = _store(db_path)
    store.acknowledge(
        settled["trial_id"],
        principal="creator",
        authorization_mechanism="bearer",
        decided_at=600.0,
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE behavior_trial_review_decisions SET decision_seal=? WHERE trial_id=?",
            ("0" * 64, settled["trial_id"]),
        )
        conn.commit()
    with pytest.raises(decisions_mod.ReviewDecisionIntegrityError, match="seal"):
        store.get(settled["trial_id"])


@pytest.mark.parametrize("limit", [0, 26, True, "5"])
def test_decision_list_rejects_invalid_limits(tmp_path, limit):
    store = _store(tmp_path / "missing.db")

    with pytest.raises(decisions_mod.BehaviorTrialReviewDecisionError, match="limit"):
        store.list(limit=limit)
