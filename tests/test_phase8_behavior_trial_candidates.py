from __future__ import annotations

import json
import sqlite3

import pytest

from alpecca import cognition
from alpecca import behavior_trial_candidates as candidates
from alpecca.behavior_trial_controller import (
    BehaviorTrialController,
    ChatterTrialPacing,
)


SEAL_KEY = b"phase8c8-test-only-candidate-seal-key"


def _baseline(
    *,
    completed: int = 5,
    qualified: int = 2,
    pending: int = 0,
    dispatching: int = 0,
    rate: float | None = 0.4,
) -> dict[str, object]:
    return {
        "completed": completed,
        "qualified_responses": qualified,
        "pending": pending,
        "dispatching": dispatching,
        "rate": rate,
    }


def _store(tmp_path, *, chatter_trial_pacing=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return candidates.BehaviorTrialCandidateStore(
        tmp_path / "candidates.db",
        seal_key=SEAL_KEY,
        chatter_trial_pacing=chatter_trial_pacing,
    )


def _issue(store, *, baseline=None):
    return store.issue_from_baseline(
        _baseline() if baseline is None else baseline,
        preimage_value=0.25,
        issued_at=100.0,
    )


def _accept(proposal_id: int, db_path):
    return cognition.update_action_proposal(
        proposal_id,
        "accepted",
        result="Accepted as a plan.",
        approved_by_user=True,
        db_path=db_path,
    )


@pytest.mark.parametrize(
    "baseline, reason",
    [
        (_baseline(completed=4), "baseline_not_settled"),
        (_baseline(pending=1), "baseline_not_settled"),
        (_baseline(dispatching=1), "baseline_not_settled"),
        (_baseline(qualified=0, rate=0.0), "baseline_does_not_support_lowering"),
        (_baseline(rate=0.5), "baseline_does_not_support_lowering"),
        (_baseline(rate=None), "baseline_unavailable"),
    ],
)
def test_candidate_issues_only_from_settled_low_response_baseline(tmp_path, baseline, reason):
    store = _store(tmp_path)

    result = _issue(store, baseline=baseline)

    assert result == {"issued": False, "reason": reason}
    assert store.public_status() is None


def test_candidate_is_sealed_and_derives_one_fixed_validated_spec(tmp_path):
    store = _store(tmp_path)

    issued = _issue(store)
    proposal_id = issued["proposal"]["id"]
    reused = _issue(store, baseline=_baseline(completed=20, qualified=1, rate=0.05))

    assert issued["issued"] is True
    assert issued["reused"] is False
    assert reused["issued"] is True
    assert reused["reused"] is True
    assert reused["proposal"]["id"] == proposal_id
    assert store.public_status() == {
        "proposal_id": proposal_id,
        "state": "pending_creator_plan",
    }

    _accept(proposal_id, store.db_path)
    details = store.registration_details(
        proposal_id,
        default_chatter_chance=0.25,
    )
    spec = details["spec"]

    assert spec.proposal_id == proposal_id
    assert spec.parameter == "chatter_chance"
    assert spec.metric == "qualified_response_rate"
    assert spec.baseline == 0.4
    assert spec.exposure_seconds == 7200.0
    assert spec.min_samples == 5
    assert spec.old_value == 0.25
    assert spec.trial_value == 0.23
    assert spec.rollback_value == 0.25
    assert store.public_status() == {
        "proposal_id": proposal_id,
        "state": "ready_for_registration",
    }


def test_generic_workshop_proposal_is_not_a_behavior_trial_candidate(tmp_path):
    store = _store(tmp_path)
    proposal_id = cognition.propose_action(cognition.ActionProposal(
        action="Consider any browser supplied behavior change",
        reason="A generic proposal must not become a behavior trial.",
        approval=cognition.APPROVAL_ASK_FIRST,
        risk="low",
        status="accepted",
        payload={
            "parameter": "chatter_chance",
            "trial_value": 0.05,
            "metric": "qualified_response_rate",
        },
    ), db_path=store.db_path)

    with pytest.raises(candidates.CandidateNotFound):
        store.registration_details(proposal_id, default_chatter_chance=0.25)


def test_candidate_rejects_mutated_sealed_payload_or_source_snapshot(tmp_path):
    store = _store(tmp_path)
    issued = _issue(store)
    proposal_id = issued["proposal"]["id"]
    _accept(proposal_id, store.db_path)

    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE behavior_trial_candidates SET candidate_json=? WHERE proposal_id=?",
            (
                json.dumps(
                    {
                        "baseline_rate": 0.4,
                        "exposure_seconds": candidates.EXPOSURE_SECONDS,
                        "kind": candidates.CANDIDATE_KIND,
                        "min_samples": candidates.MIN_SAMPLES,
                        "preimage_value": 0.25,
                        "trial_value": 0.22,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                proposal_id,
            ),
        )
    with pytest.raises(candidates.CandidateIntegrityError, match="seal"):
        store.registration_details(proposal_id, default_chatter_chance=0.25)

    fresh = _store(tmp_path / "other")
    fresh_issued = _issue(fresh)
    fresh_id = fresh_issued["proposal"]["id"]
    _accept(fresh_id, fresh.db_path)
    with sqlite3.connect(fresh.db_path) as conn:
        conn.execute(
            "UPDATE action_proposals SET evidence='changed after issue' WHERE id=?",
            (fresh_id,),
        )
    with pytest.raises(candidates.CandidateIntegrityError, match="snapshot"):
        fresh.registration_details(fresh_id, default_chatter_chance=0.25)


def test_candidate_registration_receipt_is_idempotent_and_does_not_need_runtime(tmp_path):
    store = _store(tmp_path)
    issued = _issue(store)
    proposal_id = issued["proposal"]["id"]
    _accept(proposal_id, store.db_path)

    details = store.registration_details(proposal_id, default_chatter_chance=0.25)
    assert details["candidate"]["state"] == "issued"
    assert store.mark_registered(
        proposal_id,
        trial_id=17,
        principal="creator",
        mechanism="session_cookie",
        registered_at=110.0,
    ) is True
    assert store.mark_registered(
        proposal_id,
        trial_id=17,
        principal="creator",
        mechanism="session_cookie",
        registered_at=111.0,
    ) is False
    assert store.public_status() == {
        "proposal_id": proposal_id,
        "state": "registered",
        "registered_trial_id": 17,
    }
    assert store.registration_details(proposal_id, default_chatter_chance=0.25)["candidate"]["state"] == "registered"


def test_sealed_candidate_registers_with_the_controller_without_starting_runtime(tmp_path):
    store = _store(tmp_path)
    issued = _issue(store)
    proposal_id = issued["proposal"]["id"]
    _accept(proposal_id, store.db_path)
    controller = BehaviorTrialController(
        db_path=store.db_path,
        default_chatter_chance=0.25,
        approval_seal_key=SEAL_KEY,
    )

    details = store.registration_details(proposal_id, default_chatter_chance=0.25)
    registered = controller.register(details["spec"])
    changed = store.mark_registered(
        proposal_id,
        trial_id=registered["id"],
        principal="creator",
        mechanism="test",
        registered_at=120.0,
    )

    assert changed is True
    assert registered["state"] == "registered"
    assert controller.chatter_chance() == 0.25
    assert controller.get(registered["id"])["state"] == "registered"


def test_candidate_cannot_register_before_plan_acceptance_or_after_rejection(tmp_path):
    store = _store(tmp_path)
    issued = _issue(store)
    proposal_id = issued["proposal"]["id"]

    with pytest.raises(candidates.CandidateNotEligible, match="not been accepted"):
        store.registration_details(proposal_id, default_chatter_chance=0.25)

    cognition.update_action_proposal(
        proposal_id,
        "rejected",
        result="No.",
        db_path=store.db_path,
    )
    with pytest.raises(candidates.CandidateNotEligible):
        store.registration_details(proposal_id, default_chatter_chance=0.25)

    replacement = _issue(store)
    assert replacement["issued"] is True
    assert replacement["reused"] is False
    assert replacement["proposal"]["id"] != proposal_id


def test_impossible_profile_is_rejected_before_candidate_issue(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(candidates, "EXPOSURE_SECONDS", 300.0)

    assert _issue(store) == {
        "issued": False,
        "reason": candidates.TRIAL_PROFILE_NOT_FEASIBLE_REASON,
    }
    assert store.public_status() is None


def test_registration_rechecks_candidate_against_current_pacing(tmp_path):
    store = _store(tmp_path)
    issued = _issue(store)
    proposal_id = issued["proposal"]["id"]
    _accept(proposal_id, store.db_path)
    stricter = _store(
        tmp_path,
        chatter_trial_pacing=ChatterTrialPacing(
            enabled=True,
            effective_cooldown_seconds=100.0,
            rate_window_seconds=10_000.0,
            rate_cap=1,
        ),
    )

    with pytest.raises(candidates.CandidateNotEligible, match="not feasible"):
        stricter.registration_details(
            proposal_id,
            default_chatter_chance=0.25,
        )

    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='experiment_trial_ledger'"
        ).fetchone() is None
