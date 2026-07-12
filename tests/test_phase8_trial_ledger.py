"""Focused lifecycle tests for the scoped Phase 8 trial ledger."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sqlite3

import pytest

from alpecca import experiment_trials
from alpecca import trial_ledger
from alpecca.db import connect


SCOPE = "creator-private"


def validated_trial(proposal_id: int = 42, trial_value: float = 0.22):
    return experiment_trials.validate_trial_spec(
        experiment_trials.TrialSpecification(
            proposal_id=proposal_id,
            parameter="chatter_chance",
            hypothesis="Reducing chatter will lower ignored outreach.",
            metric="ignored_outreach_rate",
            baseline=0.35,
            exposure=experiment_trials.ExposureWindow(300, 5),
            change=experiment_trials.ParameterChange(0.25, trial_value),
            rollback_value=0.25,
        )
    )


def approval(proposal_id: int = 42, scope: str = SCOPE, proof_id: str = "approval-1"):
    return trial_ledger.ProposalApprovalProof(
        proposal_id=proposal_id,
        scope=scope,
        proof_id=proof_id,
        authority="creator-session",
        approved_at=100.0,
    )


def running_trial(db_path, proposal_id: int = 42):
    registered = trial_ledger.register_trial(
        validated_trial(proposal_id), scope=SCOPE, created_at=90, db_path=db_path
    )
    trial_ledger.approve_trial(
        registered["id"], approval(proposal_id), scope=SCOPE, db_path=db_path
    )
    return trial_ledger.start_trial(
        registered["id"], scope=SCOPE, started_at=100, db_path=db_path
    )


def test_registration_requires_validated_spec_and_replays_idempotently(tmp_path):
    db_path = tmp_path / "trials.db"
    normalized = validated_trial()

    first = trial_ledger.register_trial(
        normalized, scope=SCOPE, created_at=90, db_path=db_path
    )
    second = trial_ledger.register_trial(
        normalized, scope=SCOPE, created_at=999, db_path=db_path
    )

    assert first == second
    assert first["state"] == trial_ledger.REGISTERED
    assert first["created_at"] == 90
    assert first["spec"]["proposal_id"] == 42
    assert first["spec"]["rollback_value"] == 0.25

    raw = experiment_trials.TrialSpecification(
        proposal_id=43,
        parameter="chatter_chance",
        hypothesis="Raw spec",
        metric="ignored_outreach_rate",
        baseline=0.4,
        exposure=experiment_trials.ExposureWindow(300, 5),
        change=experiment_trials.ParameterChange(0.25, 0.22),
        rollback_value=0.25,
    )
    with pytest.raises(trial_ledger.UnvalidatedExperimentTrial):
        trial_ledger.register_trial(raw, scope=SCOPE, db_path=db_path)
    forged = dataclasses.replace(normalized, consumer="forged.consumer")
    with pytest.raises(trial_ledger.UnvalidatedExperimentTrial):
        trial_ledger.register_trial(forged, scope=SCOPE, db_path=db_path)


def test_spec_sha256_uses_exact_persisted_json_object_bytes(tmp_path):
    db_path = tmp_path / "trials.db"
    raw_spec = '{\n  "label": "caf' + chr(0xE9) + '",\n  "values": [2, 1]\n}'
    trial_ledger.init_db(db_path)
    with connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO experiment_trial_ledger
                (scope, proposal_id, state, spec_json, approval_json,
                 created_at, updated_at, started_at, planned_end_at, ended_at)
            VALUES (?, ?, 'registered', ?, NULL, ?, ?, NULL, NULL, NULL)
            """,
            (SCOPE, 84, raw_spec, 90, 90),
        )
        trial_id = int(cursor.lastrowid)
        persisted = conn.execute(
            "SELECT spec_json FROM experiment_trial_ledger WHERE id=?", (trial_id,)
        ).fetchone()["spec_json"]

    expected = hashlib.sha256(persisted.encode("utf-8")).hexdigest()
    reconstructed = json.dumps(
        json.loads(persisted), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    assert expected != hashlib.sha256(reconstructed.encode("utf-8")).hexdigest()
    assert trial_ledger.spec_sha256(persisted) == expected
    assert trial_ledger.get_trial(trial_id, scope=SCOPE, db_path=db_path)["spec_sha256"] == expected
    with pytest.raises(trial_ledger.TrialLedgerError, match="not an object"):
        trial_ledger.spec_sha256('["not", "a", "trial", "spec"]')


def test_same_proposal_cannot_register_conflicting_spec(tmp_path):
    db_path = tmp_path / "trials.db"
    trial_ledger.register_trial(validated_trial(), scope=SCOPE, db_path=db_path)

    with pytest.raises(trial_ledger.TrialStateError, match="different"):
        trial_ledger.register_trial(
            validated_trial(trial_value=0.21), scope=SCOPE, db_path=db_path
        )


def test_start_strictly_requires_matching_approval_proof(tmp_path):
    db_path = tmp_path / "trials.db"
    item = trial_ledger.register_trial(
        validated_trial(), scope=SCOPE, created_at=90, db_path=db_path
    )

    with pytest.raises(trial_ledger.ApprovalRequired):
        trial_ledger.start_trial(item["id"], scope=SCOPE, started_at=100, db_path=db_path)
    with pytest.raises(trial_ledger.ApprovalRequired, match="scope"):
        trial_ledger.approve_trial(
            item["id"], approval(scope="guest-private"), scope=SCOPE, db_path=db_path
        )
    with pytest.raises(trial_ledger.ApprovalRequired, match="proposal_id"):
        trial_ledger.approve_trial(
            item["id"], approval(proposal_id=999), scope=SCOPE, db_path=db_path
        )

    approved = trial_ledger.approve_trial(
        item["id"], approval(), scope=SCOPE, db_path=db_path
    )
    started = trial_ledger.start_trial(
        item["id"], scope=SCOPE, started_at=100, db_path=db_path
    )
    assert approved["state"] == trial_ledger.APPROVED
    assert approved["approval_proof"]["proof_id"] == "approval-1"
    assert started["state"] == trial_ledger.RUNNING
    assert started["started_at"] == 100
    assert started["planned_end_at"] == 400


def test_approval_and_start_are_idempotent_but_conflicts_fail(tmp_path):
    db_path = tmp_path / "trials.db"
    item = trial_ledger.register_trial(validated_trial(), scope=SCOPE, db_path=db_path)
    first_approval = trial_ledger.approve_trial(
        item["id"], approval(), scope=SCOPE, db_path=db_path
    )
    second_approval = trial_ledger.approve_trial(
        item["id"], approval(), scope=SCOPE, db_path=db_path
    )
    first_start = trial_ledger.start_trial(
        item["id"], scope=SCOPE, started_at=100, db_path=db_path
    )
    second_start = trial_ledger.start_trial(
        item["id"], scope=SCOPE, started_at=100, db_path=db_path
    )

    assert first_approval == second_approval
    assert first_start == second_start
    with pytest.raises(trial_ledger.TrialStateError, match="different approval"):
        trial_ledger.approve_trial(
            item["id"], approval(proof_id="other"), scope=SCOPE, db_path=db_path
        )
    with pytest.raises(trial_ledger.TrialStateError, match="different timestamp"):
        trial_ledger.start_trial(
            item["id"], scope=SCOPE, started_at=101, db_path=db_path
        )


def test_transactional_approval_helper_preserves_generic_wrapper_behavior(tmp_path):
    db_path = tmp_path / "trials.db"
    item = trial_ledger.register_trial(validated_trial(), scope=SCOPE, db_path=db_path)

    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        approved_id = trial_ledger.approve_trial_in_transaction(
            conn, item["id"], approval(), scope=SCOPE
        )
        assert approved_id == item["id"]
        row = conn.execute(
            "SELECT state, approval_json FROM experiment_trial_ledger WHERE id=?",
            (item["id"],),
        ).fetchone()
        assert row["state"] == trial_ledger.APPROVED
        assert json.loads(row["approval_json"])["proof_id"] == "approval-1"
        conn.execute("ROLLBACK")

    assert trial_ledger.get_trial(item["id"], scope=SCOPE, db_path=db_path) == item
    approved = trial_ledger.approve_trial(
        item["id"], approval(), scope=SCOPE, db_path=db_path
    )
    assert approved["state"] == trial_ledger.APPROVED
    assert approved["approval_proof"]["proof_id"] == "approval-1"
    assert trial_ledger.approve_trial(
        item["id"], approval(), scope=SCOPE, db_path=db_path
    ) == approved


def test_metric_observations_and_completion_enforce_exposure(tmp_path):
    db_path = tmp_path / "trials.db"
    item = running_trial(db_path)
    observations = []
    for index, stamp in enumerate((100, 175, 250, 325, 400), start=1):
        observations.append(trial_ledger.record_metric_observation(
            item["id"],
            scope=SCOPE,
            observation_key=f"sample-{index}",
            value=0.35 - index * 0.01,
            observed_at=stamp,
            evidence={"sample": index},
            db_path=db_path,
        ))
    replay = trial_ledger.record_metric_observation(
        item["id"],
        scope=SCOPE,
        observation_key="sample-1",
        value=0.35 - 0.01,
        observed_at=100,
        evidence={"sample": 1},
        db_path=db_path,
    )
    assert replay == observations[0]

    with pytest.raises(trial_ledger.TrialStateError, match="replayed"):
        trial_ledger.record_metric_observation(
            item["id"],
            scope=SCOPE,
            observation_key="sample-1",
            value=0.99,
            observed_at=100,
            evidence={"sample": 1},
            db_path=db_path,
        )
    with pytest.raises(trial_ledger.TrialStateError, match="exposure window"):
        trial_ledger.record_metric_observation(
            item["id"],
            scope=SCOPE,
            observation_key="too-late",
            value=0.2,
            observed_at=401,
            db_path=db_path,
        )
    with pytest.raises(trial_ledger.TrialStateError, match="has not ended"):
        trial_ledger.complete_trial(
            item["id"], scope=SCOPE, ended_at=399, db_path=db_path
        )

    completed = trial_ledger.complete_trial(
        item["id"], scope=SCOPE, ended_at=400, db_path=db_path
    )
    assert completed["state"] == trial_ledger.COMPLETED
    assert completed["ended_at"] == 400
    assert len(completed["observations"]) == 5
    assert trial_ledger.complete_trial(
        item["id"], scope=SCOPE, ended_at=400, db_path=db_path
    ) == completed


def test_completion_requires_minimum_samples(tmp_path):
    db_path = tmp_path / "trials.db"
    item = running_trial(db_path)
    for index in range(4):
        trial_ledger.record_metric_observation(
            item["id"],
            scope=SCOPE,
            observation_key=f"sample-{index}",
            value=0.3,
            observed_at=100 + index,
            db_path=db_path,
        )

    with pytest.raises(trial_ledger.TrialStateError, match="fewer"):
        trial_ledger.complete_trial(
            item["id"], scope=SCOPE, ended_at=400, db_path=db_path
        )


def test_exact_rollback_record_is_required_and_idempotent(tmp_path):
    db_path = tmp_path / "trials.db"
    item = running_trial(db_path)

    with pytest.raises(trial_ledger.TrialLedgerError, match="exactly equal"):
        trial_ledger.record_rollback(
            item["id"],
            scope=SCOPE,
            restored_value=0.2500000001,
            reason="Metric worsened.",
            recorded_at=200,
            db_path=db_path,
        )
    rolled_back = trial_ledger.record_rollback(
        item["id"],
        scope=SCOPE,
        restored_value=0.25,
        reason="Metric worsened.",
        recorded_at=200,
        evidence={"decision": "revert"},
        db_path=db_path,
    )
    replay = trial_ledger.record_rollback(
        item["id"],
        scope=SCOPE,
        restored_value=0.25,
        reason="Metric worsened.",
        recorded_at=200,
        evidence={"decision": "revert"},
        db_path=db_path,
    )

    assert rolled_back == replay
    assert rolled_back["state"] == trial_ledger.ROLLED_BACK
    assert rolled_back["ended_at"] == 200
    assert rolled_back["rollback"] == {
        "id": rolled_back["rollback"]["id"],
        "recorded_at": 200.0,
        "expected_value": 0.25,
        "restored_value": 0.25,
        "reason": "Metric worsened.",
        "evidence": {"decision": "revert"},
    }


def test_scope_isolation_applies_to_reads_and_mutations(tmp_path):
    db_path = tmp_path / "trials.db"
    item = trial_ledger.register_trial(validated_trial(), scope=SCOPE, db_path=db_path)

    assert trial_ledger.get_trial(
        item["id"], scope="guest-private", db_path=db_path
    ) is None
    with pytest.raises(trial_ledger.TrialNotFound):
        trial_ledger.approve_trial(
            item["id"],
            approval(scope="guest-private"),
            scope="guest-private",
            db_path=db_path,
        )
    assert trial_ledger.get_trial(item["id"], scope=SCOPE, db_path=db_path) == item


def test_database_trigger_rejects_direct_state_jump(tmp_path):
    db_path = tmp_path / "trials.db"
    item = trial_ledger.register_trial(validated_trial(), scope=SCOPE, db_path=db_path)

    with connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="illegal experiment"):
            conn.execute(
                "UPDATE experiment_trial_ledger SET state='running' WHERE id=?",
                (item["id"],),
            )
    assert trial_ledger.get_trial(item["id"], scope=SCOPE, db_path=db_path) == item


def test_database_trigger_rejects_trial_spec_mutation(tmp_path):
    db_path = tmp_path / "trials.db"
    item = trial_ledger.register_trial(validated_trial(), scope=SCOPE, db_path=db_path)

    with connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="specification is immutable"):
            conn.execute(
                "UPDATE experiment_trial_ledger SET spec_json=? WHERE id=?",
                ('{"different":true}', item["id"]),
            )
    assert trial_ledger.get_trial(item["id"], scope=SCOPE, db_path=db_path) == item


def test_retrieval_is_idempotent_and_returns_fresh_payloads(tmp_path):
    db_path = tmp_path / "trials.db"
    item = running_trial(db_path)
    trial_ledger.record_metric_observation(
        item["id"],
        scope=SCOPE,
        observation_key="sample",
        value=0.3,
        observed_at=100,
        evidence={"source": "test"},
        db_path=db_path,
    )

    first = trial_ledger.get_trial(item["id"], scope=SCOPE, db_path=db_path)
    second = trial_ledger.get_trial(item["id"], scope=SCOPE, db_path=db_path)
    assert first == second
    assert first is not second
    first["spec"]["parameter"] = "mutated-return"
    first["observations"].clear()
    assert trial_ledger.get_trial(item["id"], scope=SCOPE, db_path=db_path) == second
