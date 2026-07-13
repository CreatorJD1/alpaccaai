"""Durable creator decision and retained-profile coverage for bounded RSI."""
from __future__ import annotations

from copy import deepcopy

import pytest

from alpecca import behavior_trial_profile as profile_mod
from alpecca import experiment_trials as trials_mod
from alpecca import qualified_response_ledger as outcomes_mod
from alpecca import trial_ledger
from alpecca.db import connect


def _closed_trial(
    db_path,
    *,
    old_value: float = 0.25,
    trial_value: float = 0.23,
    proposal_id: int = 91,
    created_at: float | None = None,
):
    created_stamp = 80.0 if created_at is None else created_at
    validated = trials_mod.validate_trial_spec(trials_mod.TrialSpecification(
        proposal_id=proposal_id,
        parameter="chatter_chance",
        hypothesis="A bounded change may improve qualified creator responses.",
        metric=outcomes_mod.METRIC_NAME,
        baseline=0.4,
        exposure=trials_mod.ExposureWindow(5400.0, 5),
        change=trials_mod.ParameterChange(old_value, trial_value),
        rollback_value=old_value,
    ))
    record = trial_ledger.register_trial(
        validated,
        scope=profile_mod.CREATOR_PERSONAL_SCOPE,
        db_path=db_path,
        created_at=created_stamp,
    )
    approved_at = created_stamp + 5.0
    started_at = created_stamp + 10.0
    ended_at = created_stamp + 60.0
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE experiment_trial_ledger SET state='approved', updated_at=? "
            "WHERE id=?",
            (approved_at, record["id"]),
        )
        conn.execute(
            "UPDATE experiment_trial_ledger SET state='running', started_at=?, "
            "planned_end_at=?, updated_at=? WHERE id=?",
            (started_at, ended_at, started_at, record["id"]),
        )
        conn.execute(
            "UPDATE experiment_trial_ledger SET state='rolled_back', ended_at=?, "
            "updated_at=? WHERE id=?",
            (ended_at, ended_at, record["id"]),
        )
    return {**record, "state": "rolled_back"}


def _binding(trial, *, eligible: bool = True, outcome: str = "improved"):
    return {
        "contract_version": 1,
        "trial_id": trial["id"],
        "scope": profile_mod.CREATOR_PERSONAL_SCOPE,
        "parameter": profile_mod.PROFILE_PARAMETER,
        "metric": outcomes_mod.METRIC_NAME,
        "definition_version": outcomes_mod.DEFINITION_VERSION,
        "spec_sha256": trial["spec_sha256"],
        "settled_at": max(210.0, float(trial["created_at"]) + 70.0),
        "status": (
            "ready_for_creator_review"
            if outcome != "inconclusive"
            else "inconclusive_insufficient_samples"
        ),
        "recommendation": (
            "creator_review_required"
            if outcome != "inconclusive"
            else "no_automatic_change"
        ),
        "outcome": outcome,
        "creator_retention_eligible": eligible,
        "creator_retention_reason": (
            "improvement_meets_threshold" if eligible else "insufficient_evidence"
        ),
        "evidence_sha256": "e" * 64,
        "review_sha256": "f" * 64,
    }


def _patch_binding(monkeypatch, binding):
    monkeypatch.setattr(
        profile_mod.settlement_mod,
        "get_settlement_binding",
        lambda trial_id, _db_path: deepcopy(binding)
        if trial_id == binding["trial_id"]
        else None,
    )


def test_creator_can_retain_eligible_trial_value_and_restart_verifies_it(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "profile.db"
    trial = _closed_trial(db_path)
    binding = _binding(trial)
    _patch_binding(monkeypatch, binding)
    store = profile_mod.BehaviorTrialProfileStore(db_path, seal_key=b"profile-key")

    receipt, created = store.decide(
        trial["id"],
        decision=profile_mod.RETAIN_TRIAL_VALUE,
        expected_current_value=0.25,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=220.0,
    )

    assert created is True
    assert receipt["applied_value"] == 0.23
    assert receipt["creator_retention_eligible"] is True
    assert store.active_profile(0.25) == {
        "parameter": "chatter_chance",
        "value": 0.23,
        "source_trial_id": trial["id"],
        "updated_at": 220.0,
        "decision": "retain_trial_value",
    }
    restarted = profile_mod.BehaviorTrialProfileStore(
        db_path, seal_key=b"profile-key"
    )
    assert restarted.active_profile(0.25)["value"] == 0.23

    replay, replay_created = restarted.decide(
        trial["id"],
        decision=profile_mod.RETAIN_TRIAL_VALUE,
        expected_current_value=0.23,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=999.0,
    )
    assert replay_created is False
    assert replay == receipt

    with pytest.raises(
        profile_mod.ProfileDecisionNotEligible, match="current chatter profile"
    ):
        restarted.decide(
            trial["id"],
            decision=profile_mod.RETAIN_TRIAL_VALUE,
            expected_current_value=0.25,
            principal="creator",
            authorization_mechanism="trusted_device",
        )


def test_inconclusive_trial_can_only_keep_its_preimage(tmp_path, monkeypatch):
    db_path = tmp_path / "profile.db"
    trial = _closed_trial(db_path)
    binding = _binding(trial, eligible=False, outcome="inconclusive")
    _patch_binding(monkeypatch, binding)
    store = profile_mod.BehaviorTrialProfileStore(db_path, seal_key=b"profile-key")

    with pytest.raises(profile_mod.ProfileDecisionNotEligible):
        store.decide(
            trial["id"],
            decision=profile_mod.RETAIN_TRIAL_VALUE,
            expected_current_value=0.25,
            principal="creator",
            authorization_mechanism="trusted_device",
        )

    receipt, created = store.decide(
        trial["id"],
        decision=profile_mod.REVERT_TO_BASELINE,
        expected_current_value=0.25,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=220.0,
    )
    assert created is True
    assert receipt["applied_value"] == 0.25
    assert store.active_profile(0.25)["value"] == 0.25


def test_profile_decision_rejects_stale_branch_and_conflicting_replay(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "profile.db"
    trial = _closed_trial(db_path)
    _patch_binding(monkeypatch, _binding(trial))
    store = profile_mod.BehaviorTrialProfileStore(db_path, seal_key=b"profile-key")

    with pytest.raises(profile_mod.ProfileDecisionNotEligible):
        store.decide(
            trial["id"],
            decision=profile_mod.REVERT_TO_BASELINE,
            expected_current_value=0.24,
            principal="creator",
            authorization_mechanism="trusted_device",
        )

    store.decide(
        trial["id"],
        decision=profile_mod.RETAIN_TRIAL_VALUE,
        expected_current_value=0.25,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=220.0,
    )
    with pytest.raises(profile_mod.ProfileDecisionNotEligible):
        store.decide(
            trial["id"],
            decision=profile_mod.REVERT_TO_BASELINE,
            expected_current_value=0.23,
            principal="creator",
            authorization_mechanism="trusted_device",
        )


def test_superseded_profile_decision_cannot_regress_live_generation(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "profile.db"
    first = _closed_trial(db_path, proposal_id=91, created_at=100.0)
    bindings = {first["id"]: _binding(first)}
    monkeypatch.setattr(
        profile_mod.settlement_mod,
        "get_settlement_binding",
        lambda trial_id, _db_path: deepcopy(bindings.get(trial_id)),
    )
    store = profile_mod.BehaviorTrialProfileStore(db_path, seal_key=b"profile-key")
    store.decide(
        first["id"],
        decision=profile_mod.RETAIN_TRIAL_VALUE,
        expected_current_value=0.25,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=220.0,
    )

    second = _closed_trial(
        db_path,
        old_value=0.23,
        trial_value=0.21,
        proposal_id=92,
        created_at=230.0,
    )
    bindings[second["id"]] = _binding(second)
    store.decide(
        second["id"],
        decision=profile_mod.RETAIN_TRIAL_VALUE,
        expected_current_value=0.23,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=320.0,
    )
    assert store.active_profile(0.25)["value"] == 0.21

    with pytest.raises(profile_mod.ProfileDecisionNotEligible, match="superseded"):
        store.decide(
            first["id"],
            decision=profile_mod.RETAIN_TRIAL_VALUE,
            expected_current_value=0.21,
            principal="creator",
            authorization_mechanism="trusted_device",
        )
    assert store.active_profile(0.25)["value"] == 0.21


def test_revert_receipt_idempotency_is_bound_to_active_generation(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "profile.db"
    first = _closed_trial(db_path, proposal_id=91, created_at=100.0)
    bindings = {first["id"]: _binding(first)}
    monkeypatch.setattr(
        profile_mod.settlement_mod,
        "get_settlement_binding",
        lambda trial_id, _db_path: deepcopy(bindings.get(trial_id)),
    )
    store = profile_mod.BehaviorTrialProfileStore(db_path, seal_key=b"profile-key")
    receipt, created = store.decide(
        first["id"],
        decision=profile_mod.REVERT_TO_BASELINE,
        expected_current_value=0.25,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=220.0,
    )
    replay, replay_created = store.decide(
        first["id"],
        decision=profile_mod.REVERT_TO_BASELINE,
        expected_current_value=0.25,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=999.0,
    )
    assert created is True
    assert replay_created is False
    assert replay == receipt

    second = _closed_trial(
        db_path,
        old_value=0.25,
        trial_value=0.27,
        proposal_id=92,
        created_at=230.0,
    )
    bindings[second["id"]] = _binding(second)
    store.decide(
        second["id"],
        decision=profile_mod.REVERT_TO_BASELINE,
        expected_current_value=0.25,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=320.0,
    )
    active = store.active_profile(0.25)
    assert active["source_trial_id"] == second["id"]
    assert active["value"] == 0.25

    with pytest.raises(profile_mod.ProfileDecisionNotEligible, match="superseded"):
        store.decide(
            first["id"],
            decision=profile_mod.REVERT_TO_BASELINE,
            expected_current_value=0.25,
            principal="creator",
            authorization_mechanism="trusted_device",
        )


def test_valid_older_profile_row_cannot_replace_latest_generation(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "profile.db"
    first = _closed_trial(db_path, proposal_id=91, created_at=100.0)
    bindings = {first["id"]: _binding(first)}
    monkeypatch.setattr(
        profile_mod.settlement_mod,
        "get_settlement_binding",
        lambda trial_id, _db_path: deepcopy(bindings.get(trial_id)),
    )
    store = profile_mod.BehaviorTrialProfileStore(db_path, seal_key=b"profile-key")
    store.decide(
        first["id"],
        decision=profile_mod.RETAIN_TRIAL_VALUE,
        expected_current_value=0.25,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=220.0,
    )
    with connect(db_path) as conn:
        older = conn.execute(
            f"SELECT * FROM {profile_mod.ACTIVE_PROFILE_TABLE} "
            "WHERE parameter='chatter_chance'"
        ).fetchone()
        assert older is not None
        older_profile = dict(older)

    second = _closed_trial(
        db_path,
        old_value=0.23,
        trial_value=0.21,
        proposal_id=92,
        created_at=230.0,
    )
    bindings[second["id"]] = _binding(second)
    store.decide(
        second["id"],
        decision=profile_mod.RETAIN_TRIAL_VALUE,
        expected_current_value=0.23,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=320.0,
    )
    with connect(db_path) as conn:
        conn.execute(
            f"UPDATE {profile_mod.ACTIVE_PROFILE_TABLE} "
            "SET value=?, source_trial_id=?, updated_at=?, profile_seal=? "
            "WHERE parameter='chatter_chance'",
            (
                older_profile["value"],
                older_profile["source_trial_id"],
                older_profile["updated_at"],
                older_profile["profile_seal"],
            ),
        )

    with pytest.raises(
        profile_mod.ProfileDecisionIntegrityError, match="latest decision generation"
    ):
        store.active_profile(0.25)


def test_new_profile_generation_requires_advancing_decision_timestamp(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "profile.db"
    first = _closed_trial(db_path, proposal_id=91, created_at=100.0)
    bindings = {first["id"]: _binding(first)}
    monkeypatch.setattr(
        profile_mod.settlement_mod,
        "get_settlement_binding",
        lambda trial_id, _db_path: deepcopy(bindings.get(trial_id)),
    )
    store = profile_mod.BehaviorTrialProfileStore(db_path, seal_key=b"profile-key")
    store.decide(
        first["id"],
        decision=profile_mod.RETAIN_TRIAL_VALUE,
        expected_current_value=0.25,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=220.0,
    )
    second = _closed_trial(
        db_path,
        old_value=0.23,
        trial_value=0.21,
        proposal_id=92,
        created_at=230.0,
    )
    bindings[second["id"]] = _binding(second)

    with pytest.raises(profile_mod.ProfileDecisionNotEligible, match="timestamp"):
        store.decide(
            second["id"],
            decision=profile_mod.RETAIN_TRIAL_VALUE,
            expected_current_value=0.23,
            principal="creator",
            authorization_mechanism="trusted_device",
            decided_at=220.0,
        )
    assert store.get(second["id"]) is None
    assert store.active_profile(0.25)["source_trial_id"] == first["id"]


def test_active_profile_fails_closed_on_tampering(tmp_path, monkeypatch):
    db_path = tmp_path / "profile.db"
    trial = _closed_trial(db_path)
    _patch_binding(monkeypatch, _binding(trial))
    store = profile_mod.BehaviorTrialProfileStore(db_path, seal_key=b"profile-key")
    store.decide(
        trial["id"],
        decision=profile_mod.RETAIN_TRIAL_VALUE,
        expected_current_value=0.25,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=220.0,
    )
    with connect(db_path) as conn:
        conn.execute(
            f"UPDATE {profile_mod.ACTIVE_PROFILE_TABLE} SET value=0.9 "
            "WHERE parameter='chatter_chance'"
        )

    with pytest.raises(profile_mod.ProfileDecisionIntegrityError):
        store.active_profile(0.25)


def test_active_profile_fails_closed_when_singleton_is_deleted(tmp_path, monkeypatch):
    db_path = tmp_path / "profile.db"
    trial = _closed_trial(db_path)
    _patch_binding(monkeypatch, _binding(trial))
    store = profile_mod.BehaviorTrialProfileStore(db_path, seal_key=b"profile-key")
    store.decide(
        trial["id"],
        decision=profile_mod.RETAIN_TRIAL_VALUE,
        expected_current_value=0.25,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=220.0,
    )
    with connect(db_path) as conn:
        conn.execute(f"DELETE FROM {profile_mod.ACTIVE_PROFILE_TABLE}")

    with pytest.raises(profile_mod.ProfileDecisionIntegrityError, match="missing"):
        store.active_profile(0.25)
    with pytest.raises(profile_mod.ProfileDecisionIntegrityError, match="missing"):
        store.decide(
            trial["id"],
            decision=profile_mod.RETAIN_TRIAL_VALUE,
            expected_current_value=0.23,
            principal="creator",
            authorization_mechanism="trusted_device",
        )


def test_profile_store_without_a_decision_reports_explicit_fallback(tmp_path):
    store = profile_mod.BehaviorTrialProfileStore(
        tmp_path / "profile.db", seal_key=b"profile-key"
    )
    assert store.active_profile(0.25) == {
        "parameter": "chatter_chance",
        "value": 0.25,
        "source_trial_id": None,
        "updated_at": None,
    }


def test_legacy_baseline_receipt_cannot_conflict_with_trial_retention(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "profile.db"
    trial = _closed_trial(db_path)
    _patch_binding(monkeypatch, _binding(trial))
    store = profile_mod.BehaviorTrialProfileStore(db_path, seal_key=b"profile-key")
    with connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE behavior_trial_review_decisions "
            "(trial_id INTEGER PRIMARY KEY, decision TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO behavior_trial_review_decisions (trial_id, decision) "
            "VALUES (?, 'retain_baseline')",
            (trial["id"],),
        )

    with pytest.raises(profile_mod.ProfileDecisionNotEligible, match="legacy"):
        store.decide(
            trial["id"],
            decision=profile_mod.RETAIN_TRIAL_VALUE,
            expected_current_value=0.25,
            principal="creator",
            authorization_mechanism="trusted_device",
        )

    receipt, created = store.decide(
        trial["id"],
        decision=profile_mod.REVERT_TO_BASELINE,
        expected_current_value=0.25,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=220.0,
    )
    assert created is True
    assert receipt["decision"] == profile_mod.REVERT_TO_BASELINE
