"""Focused integration coverage for the Phase 8 runtime trial controller."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading

import pytest

from alpecca import behavior_trial_controller as controller_mod
from alpecca import experiment_trials
from alpecca import proactive
from alpecca import trial_ledger
from config import Proactive


SCOPE = controller_mod.CREATOR_PERSONAL_SCOPE
DEFAULT_CHANCE = float(Proactive.CHATTER_CHANCE)
TRIAL_CHANCE = 0.22
APPROVED_AT = 100.0
STARTED_AT = 110.0
AUTHORIZATION_ISSUED_AT = 90.0
AUTHORIZATION_EXPIRES_AT = 200.0
AUTHORIZATION_MECHANISM = "creator-session"
APPROVAL_SEAL_KEY = b"phase8c1-test-only-approval-seal-key"


class _Clock:
    """A shared, fixed clock for deterministic controller timing tests."""

    def __init__(self, value: float = STARTED_AT) -> None:
        self._value = value
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._value

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value


def _validated_chatter_trial(
    proposal_id: int,
    *,
    old_value: float = DEFAULT_CHANCE,
    trial_value: float = TRIAL_CHANCE,
):
    return experiment_trials.validate_trial_spec(
        experiment_trials.TrialSpecification(
            proposal_id=proposal_id,
            parameter="chatter_chance",
            hypothesis="A lower chatter chance will reduce ignored outreach.",
            metric="ignored_outreach_rate",
            baseline=0.35,
            exposure=experiment_trials.ExposureWindow(300, 5),
            change=experiment_trials.ParameterChange(old_value, trial_value),
            rollback_value=old_value,
        )
    )


def _validated_reflect_trial(proposal_id: int):
    return experiment_trials.validate_trial_spec(
        experiment_trials.TrialSpecification(
            proposal_id=proposal_id,
            parameter="reflect_chance",
            hypothesis="A bounded reflection change will be measured safely.",
            metric="ignored_outreach_rate",
            baseline=0.35,
            exposure=experiment_trials.ExposureWindow(300, 5),
            change=experiment_trials.ParameterChange(0.15, 0.18),
            rollback_value=0.15,
        )
    )


def _approval(proposal_id: int) -> trial_ledger.ProposalApprovalProof:
    return trial_ledger.ProposalApprovalProof(
        proposal_id=proposal_id,
        scope=SCOPE,
        proof_id=f"approval-{proposal_id}",
        authority="creator-session",
        approved_at=APPROVED_AT,
    )


def _controller(
    tmp_path,
    *,
    clock: _Clock | None = None,
    db_path=None,
    approval_seal_key=APPROVAL_SEAL_KEY,
):
    return controller_mod.BehaviorTrialController(
        db_path=tmp_path / "behavior-trials.db" if db_path is None else db_path,
        default_chatter_chance=DEFAULT_CHANCE,
        clock=_Clock() if clock is None else clock,
        approval_seal_key=approval_seal_key,
    )


def _approved_trial(controller, proposal_id: int, **spec_values):
    registered = controller.register(
        _validated_chatter_trial(proposal_id, **spec_values)
    )
    controller.approve_creator(
        registered["id"],
        principal="creator",
        authorization_mechanism=AUTHORIZATION_MECHANISM,
        authorization_issued_at=AUTHORIZATION_ISSUED_AT,
        authorization_expires_at=AUTHORIZATION_EXPIRES_AT,
        approved_at=APPROVED_AT,
    )
    return registered


def _running_trial(controller, proposal_id: int = 1, **spec_values):
    registered = _approved_trial(controller, proposal_id, **spec_values)
    return controller.start(registered["id"])


def _runtime_rows(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT trial_id, preimage_value, override_value "
            "FROM behavior_trial_runtime_overrides ORDER BY trial_id"
        ).fetchall()


def _creator_binding_row(db_path, trial_id):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            """
            SELECT trial_id, scope, proof_id, spec_sha256, principal,
                   authorization_mechanism, approved_at,
                   authorization_issued_at, authorization_expires_at,
                   approval_seal
            FROM behavior_trial_creator_approval_bindings
            WHERE trial_id=?
            """,
            (trial_id,),
        ).fetchone()


def _eligible_chatter_args() -> dict[str, float]:
    return {
        "now": 10_000.0,
        "last_user_ts": 0.0,
        "last_unprompted_ts": 0.0,
    }


def test_unapproved_start_leaves_no_runtime_override(tmp_path):
    controller = _controller(tmp_path)
    registered = controller.register(_validated_chatter_trial(1))

    with pytest.raises(trial_ledger.ApprovalRequired):
        controller.start(registered["id"])

    assert controller.chatter_chance() == DEFAULT_CHANCE
    assert controller.get(registered["id"])["state"] == trial_ledger.REGISTERED
    assert _runtime_rows(controller.db_path) == []


def test_approved_chatter_trial_changes_effective_gate_without_mutating_config(tmp_path):
    controller = _controller(tmp_path)
    running = _running_trial(controller)
    gate_roll = (DEFAULT_CHANCE + TRIAL_CHANCE) / 2
    with sqlite3.connect(controller.db_path) as conn:
        raw_spec_json = conn.execute(
            "SELECT spec_json FROM experiment_trial_ledger WHERE id=?",
            (running["id"],),
        ).fetchone()[0]

    assert running["state"] == trial_ledger.RUNNING
    binding = _creator_binding_row(controller.db_path, running["id"])
    assert binding is not None
    assert binding[:9] == (
        running["id"],
        SCOPE,
        running["approval_proof"]["proof_id"],
        hashlib.sha256(raw_spec_json.encode("utf-8")).hexdigest(),
        "creator",
        AUTHORIZATION_MECHANISM,
        APPROVED_AT,
        AUTHORIZATION_ISSUED_AT,
        AUTHORIZATION_EXPIRES_AT,
    )
    assert isinstance(binding[9], str)
    assert len(binding[9]) == 64
    assert controller.chatter_chance() == TRIAL_CHANCE
    assert proactive.should_chatter(**_eligible_chatter_args(), roll=gate_roll)
    assert not proactive.should_chatter(
        **_eligible_chatter_args(),
        roll=gate_roll,
        chance=controller.chatter_chance(),
    )
    assert Proactive.CHATTER_CHANCE == DEFAULT_CHANCE
    assert _runtime_rows(controller.db_path) == [(running["id"], DEFAULT_CHANCE, TRIAL_CHANCE)]


def test_generic_approval_remains_compatible_but_cannot_start_without_creator_binding(
    tmp_path,
):
    controller = _controller(tmp_path)
    registered = controller.register(_validated_chatter_trial(1))
    approved = controller.approve(registered["id"], _approval(1))

    assert approved["state"] == trial_ledger.APPROVED
    assert _creator_binding_row(controller.db_path, registered["id"]) is None
    with pytest.raises(controller_mod.CreatorApprovalBindingError, match="binding"):
        controller.start(registered["id"])

    assert controller.get(registered["id"])["state"] == trial_ledger.APPROVED
    assert controller.chatter_chance() == DEFAULT_CHANCE
    assert _runtime_rows(controller.db_path) == []


def test_creator_approval_requires_a_held_seal_key_and_can_be_enabled_later(tmp_path):
    controller = _controller(tmp_path, approval_seal_key=None)
    registered = controller.register(_validated_chatter_trial(1))

    with pytest.raises(controller_mod.CreatorApprovalBindingError, match="seal key"):
        controller.approve_creator(
            registered["id"],
            principal="creator",
            authorization_mechanism=AUTHORIZATION_MECHANISM,
            approved_at=APPROVED_AT,
        )

    assert controller.get(registered["id"])["state"] == trial_ledger.REGISTERED
    assert _creator_binding_row(controller.db_path, registered["id"]) is None

    controller.set_approval_seal_key(APPROVAL_SEAL_KEY)
    approved = controller.approve_creator(
        registered["id"],
        principal="creator",
        authorization_mechanism=AUTHORIZATION_MECHANISM,
        authorization_issued_at=AUTHORIZATION_ISSUED_AT,
        authorization_expires_at=AUTHORIZATION_EXPIRES_AT,
        approved_at=APPROVED_AT,
    )

    assert approved["state"] == trial_ledger.APPROVED
    assert controller.start(registered["id"])["state"] == trial_ledger.RUNNING


def test_unbound_generic_approval_is_superseded_by_server_creator_approval(tmp_path):
    controller = _controller(tmp_path)
    registered = controller.register(_validated_chatter_trial(1))
    generic = controller.approve(
        registered["id"],
        trial_ledger.ProposalApprovalProof(
            proposal_id=1,
            scope=SCOPE,
            proof_id="client-issued-proof",
            authority="Creator Session",
            approved_at=APPROVED_AT - 1.0,
        ),
    )

    assert generic["approval_proof"]["authority"] == "Creator Session"
    upgraded = controller.approve_creator(
        registered["id"],
        principal="creator",
        authorization_mechanism=AUTHORIZATION_MECHANISM,
        authorization_issued_at=AUTHORIZATION_ISSUED_AT,
        authorization_expires_at=AUTHORIZATION_EXPIRES_AT,
        approved_at=APPROVED_AT,
    )

    assert upgraded["state"] == trial_ledger.APPROVED
    assert upgraded["approval_proof"]["authority"] == AUTHORIZATION_MECHANISM
    assert upgraded["approval_proof"]["proof_id"] != "client-issued-proof"
    assert upgraded["approval_proof"]["proof_id"].startswith("creator-approval-")
    assert controller.start(registered["id"])["state"] == trial_ledger.RUNNING


def test_bad_approval_seal_refuses_start_without_an_override(tmp_path):
    controller = _controller(tmp_path)
    approved = _approved_trial(controller, 1)

    with sqlite3.connect(controller.db_path) as conn:
        conn.execute(
            "UPDATE behavior_trial_creator_approval_bindings "
            "SET approval_seal=? WHERE trial_id=?",
            ("0" * 64, approved["id"]),
        )

    with pytest.raises(controller_mod.CreatorApprovalBindingError, match="seal"):
        controller.start(approved["id"])

    assert controller.get(approved["id"])["state"] == trial_ledger.APPROVED
    assert _runtime_rows(controller.db_path) == []


def test_legacy_binding_migration_adds_a_missing_seal_that_fails_closed(tmp_path):
    db_path = tmp_path / "legacy-behavior-trials.db"
    trial_ledger.init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE behavior_trial_creator_approval_bindings (
                trial_id                   INTEGER PRIMARY KEY,
                scope                      TEXT NOT NULL,
                proof_id                   TEXT NOT NULL,
                spec_sha256                TEXT NOT NULL,
                principal                  TEXT NOT NULL,
                authorization_mechanism    TEXT NOT NULL,
                approved_at                REAL NOT NULL,
                authorization_issued_at    REAL,
                authorization_expires_at   REAL
            )
            """
        )

    controller = _controller(tmp_path, db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        columns = [
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(behavior_trial_creator_approval_bindings)"
            ).fetchall()
        ]
    assert "approval_seal" in columns

    approved = _approved_trial(controller, 1)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE behavior_trial_creator_approval_bindings "
            "SET approval_seal=NULL WHERE trial_id=?",
            (approved["id"],),
        )

    with pytest.raises(controller_mod.CreatorApprovalBindingError, match="approval seal"):
        controller.start(approved["id"])
    assert _runtime_rows(db_path) == []


def test_coordinated_spec_and_digest_mutation_fails_before_hmac(tmp_path, monkeypatch):
    controller = _controller(tmp_path)
    approved = _approved_trial(controller, 1)
    with sqlite3.connect(controller.db_path) as conn:
        conn.execute("DROP TRIGGER experiment_trial_spec_immutable")
        raw_spec = json.loads(
            conn.execute(
                "SELECT spec_json FROM experiment_trial_ledger WHERE id=?",
                (approved["id"],),
            ).fetchone()[0]
        )
        raw_spec["hypothesis"] = "A coordinated spec rewrite must never run."
        raw_spec_json = json.dumps(
            raw_spec,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        conn.execute(
            "UPDATE experiment_trial_ledger SET spec_json=? WHERE id=?",
            (raw_spec_json, approved["id"]),
        )
        conn.execute(
            "UPDATE behavior_trial_creator_approval_bindings SET spec_sha256=? "
            "WHERE trial_id=?",
            (hashlib.sha256(raw_spec_json.encode("utf-8")).hexdigest(), approved["id"]),
        )

    def unexpected_hmac(*_args, **_kwargs):
        raise AssertionError("derived proof verification must precede HMAC verification")

    monkeypatch.setattr(controller_mod.hmac, "compare_digest", unexpected_hmac)
    with pytest.raises(controller_mod.CreatorApprovalBindingError, match="proof id"):
        controller.start(approved["id"])


def test_coordinated_generic_proof_and_binding_mutation_fails_before_hmac(
    tmp_path, monkeypatch
):
    controller = _controller(tmp_path)
    approved = _approved_trial(controller, 1)
    tampered_proof_id = "creator-approval-" + ("0" * 64)
    with sqlite3.connect(controller.db_path) as conn:
        raw_proof = conn.execute(
            "SELECT approval_json FROM experiment_trial_ledger WHERE id=?",
            (approved["id"],),
        ).fetchone()[0]
        proof = json.loads(raw_proof)
        proof["proof_id"] = tampered_proof_id
        conn.execute(
            "UPDATE experiment_trial_ledger SET approval_json=? WHERE id=?",
            (
                json.dumps(proof, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
                approved["id"],
            ),
        )
        conn.execute(
            "UPDATE behavior_trial_creator_approval_bindings SET proof_id=? "
            "WHERE trial_id=?",
            (tampered_proof_id, approved["id"]),
        )

    def unexpected_hmac(*_args, **_kwargs):
        raise AssertionError("derived proof verification must precede HMAC verification")

    monkeypatch.setattr(controller_mod.hmac, "compare_digest", unexpected_hmac)
    with pytest.raises(controller_mod.CreatorApprovalBindingError, match="proof id"):
        controller.start(approved["id"])


def test_coordinated_spec_proof_and_binding_rewrite_requires_the_hmac_seal(tmp_path):
    controller = _controller(tmp_path)
    approved = _approved_trial(controller, 1)
    with sqlite3.connect(controller.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM experiment_trial_ledger WHERE id=?", (approved["id"],)
        ).fetchone()
        assert row is not None
        conn.execute("DROP TRIGGER experiment_trial_spec_immutable")
        raw_spec = json.loads(row["spec_json"])
        raw_spec["hypothesis"] = "A fully coordinated rewrite must fail its seal."
        raw_spec_json = json.dumps(
            raw_spec,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        spec_sha256 = hashlib.sha256(raw_spec_json.encode("utf-8")).hexdigest()
        proof = json.loads(row["approval_json"])
        proof_id = controller._creator_proof_id(row, spec_sha256)
        proof["proof_id"] = proof_id
        conn.execute(
            "UPDATE experiment_trial_ledger SET spec_json=?, approval_json=? WHERE id=?",
            (
                raw_spec_json,
                json.dumps(proof, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
                approved["id"],
            ),
        )
        conn.execute(
            """
            UPDATE behavior_trial_creator_approval_bindings
            SET spec_sha256=?, proof_id=?
            WHERE trial_id=?
            """,
            (spec_sha256, proof_id, approved["id"]),
        )

    with pytest.raises(controller_mod.CreatorApprovalBindingError, match="seal does not verify"):
        controller.start(approved["id"])


def test_creator_approval_rolls_back_the_generic_proof_when_binding_write_fails(
    tmp_path, monkeypatch
):
    controller = _controller(tmp_path)
    registered = controller.register(_validated_chatter_trial(1))

    def fail_binding_write(*_args, **_kwargs):
        raise RuntimeError("sidecar unavailable")

    monkeypatch.setattr(
        controller, "_write_creator_binding_in_transaction", fail_binding_write
    )
    with pytest.raises(RuntimeError, match="sidecar unavailable"):
        controller.approve_creator(
            registered["id"],
            principal="creator",
            authorization_mechanism=AUTHORIZATION_MECHANISM,
            approved_at=APPROVED_AT,
        )

    record = controller.get(registered["id"])
    assert record is not None
    assert record["state"] == trial_ledger.REGISTERED
    assert record["approval_proof"] is None
    assert _creator_binding_row(controller.db_path, registered["id"]) is None


def test_tampered_creator_binding_refuses_start_without_an_override(tmp_path):
    controller = _controller(tmp_path)
    approved = _approved_trial(controller, 1)

    with sqlite3.connect(controller.db_path) as conn:
        conn.execute(
            "UPDATE behavior_trial_creator_approval_bindings "
            "SET proof_id='tampered-proof' WHERE trial_id=?",
            (approved["id"],),
        )

    with pytest.raises(controller_mod.CreatorApprovalBindingError, match="proof"):
        controller.start(approved["id"])

    assert controller.get(approved["id"])["state"] == trial_ledger.APPROVED
    assert controller.chatter_chance() == DEFAULT_CHANCE
    assert _runtime_rows(controller.db_path) == []


def test_altered_raw_spec_breaks_the_creator_binding_before_start(tmp_path):
    controller = _controller(tmp_path)
    approved = _approved_trial(controller, 1)
    with sqlite3.connect(controller.db_path) as conn:
        # Simulate on-disk/database corruption after the ledger's normal
        # immutability trigger has done its job.
        conn.execute("DROP TRIGGER experiment_trial_spec_immutable")
        raw_spec = json.loads(conn.execute(
            "SELECT spec_json FROM experiment_trial_ledger WHERE id=?",
            (approved["id"],),
        ).fetchone()[0])
        raw_spec["hypothesis"] = "A tampered hypothesis must never run."
        conn.execute(
            "UPDATE experiment_trial_ledger SET spec_json=? WHERE id=?",
            (
                json.dumps(
                    raw_spec,
                    ensure_ascii=True,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                approved["id"],
            ),
        )

    with pytest.raises(controller_mod.CreatorApprovalBindingError, match="raw stored"):
        controller.start(approved["id"])

    assert controller.get(approved["id"])["state"] == trial_ledger.APPROVED
    assert controller.chatter_chance() == DEFAULT_CHANCE
    assert _runtime_rows(controller.db_path) == []


def test_foreign_scope_and_non_chatter_trials_are_rejected(tmp_path):
    db_path = tmp_path / "behavior-trials.db"
    controller = controller_mod.BehaviorTrialController(
        db_path=db_path,
        default_chatter_chance=DEFAULT_CHANCE,
        clock=_Clock(),
        approval_seal_key=APPROVAL_SEAL_KEY,
    )

    with pytest.raises(controller_mod.ForeignBehaviorTrialScope):
        controller_mod.BehaviorTrialController(
            db_path=db_path,
            scope="guest-private",
            clock=_Clock(),
            approval_seal_key=APPROVAL_SEAL_KEY,
        )
    with pytest.raises(controller_mod.UnsupportedBehaviorTrial):
        controller.register(_validated_reflect_trial(2))

    foreign = trial_ledger.register_trial(
        _validated_chatter_trial(3),
        scope="guest-private",
        db_path=db_path,
    )
    with pytest.raises(trial_ledger.TrialNotFound):
        controller.start(foreign["id"])

    assert controller.chatter_chance() == DEFAULT_CHANCE
    assert _runtime_rows(db_path) == []


def test_stale_preimage_is_rejected_without_an_override(tmp_path):
    controller = _controller(tmp_path)
    stale = _approved_trial(
        controller,
        1,
        old_value=DEFAULT_CHANCE - 0.01,
        trial_value=DEFAULT_CHANCE - 0.04,
    )

    with pytest.raises(controller_mod.RuntimeOverrideError, match="old_value"):
        controller.start(stale["id"])
    assert controller.chatter_chance() == DEFAULT_CHANCE
    assert _runtime_rows(controller.db_path) == []


def test_second_creator_approval_is_rejected_by_the_database_one_active_constraint(tmp_path):
    controller = _controller(tmp_path)
    first = _approved_trial(controller, proposal_id=2)
    second = controller.register(_validated_chatter_trial(3))

    with sqlite3.connect(controller.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE experiment_trial_ledger SET state='approved' WHERE id=?",
                (second["id"],),
            )

    assert controller.get(first["id"])["state"] == trial_ledger.APPROVED
    assert controller.get(second["id"])["state"] == trial_ledger.REGISTERED
    assert controller.chatter_chance() == DEFAULT_CHANCE
    assert _runtime_rows(controller.db_path) == []


def test_concurrent_controller_starts_share_one_running_override(tmp_path):
    clock = _Clock()
    first_controller = _controller(tmp_path, clock=clock)
    approved = _approved_trial(first_controller, proposal_id=2)
    second_controller = _controller(
        tmp_path,
        db_path=first_controller.db_path,
        clock=clock,
    )
    barrier = threading.Barrier(3)
    results: list[dict] = []
    errors: list[Exception] = []
    result_lock = threading.Lock()

    def start(controller):
        try:
            barrier.wait(timeout=2)
            result = controller.start(approved["id"])
        except Exception as exc:  # pragma: no cover - assertions below expose it
            with result_lock:
                errors.append(exc)
        else:
            with result_lock:
                results.append(result)

    first = threading.Thread(target=start, args=(first_controller,))
    second = threading.Thread(target=start, args=(second_controller,))
    first.start()
    second.start()
    barrier.wait(timeout=2)
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert len(results) == 2
    assert {result["id"] for result in results} == {approved["id"]}
    assert {result["state"] for result in results} == {trial_ledger.RUNNING}
    assert {result["started_at"] for result in results} == {STARTED_AT}
    assert _runtime_rows(first_controller.db_path) == [
        (approved["id"], DEFAULT_CHANCE, TRIAL_CHANCE)
    ]
    assert first_controller.chatter_chance() == TRIAL_CHANCE


def test_due_trial_reads_as_default_until_off_lock_maintenance_rolls_it_back(tmp_path):
    clock = _Clock()
    controller = _controller(tmp_path, clock=clock)
    running = _running_trial(controller)
    assert controller.chatter_chance() == TRIAL_CHANCE

    clock.set(running["planned_end_at"])

    assert controller.chatter_chance() == DEFAULT_CHANCE
    pending = controller.get(running["id"])
    assert pending is not None
    assert pending["state"] == trial_ledger.RUNNING
    controller.maintain_runtime_state()
    rolled_back = controller.get(running["id"])
    assert rolled_back is not None
    assert rolled_back["state"] == trial_ledger.ROLLED_BACK
    assert rolled_back["ended_at"] == running["planned_end_at"]
    assert rolled_back["rollback"]["recorded_at"] == running["planned_end_at"]
    assert _runtime_rows(controller.db_path) == []


def test_chatter_chance_fails_closed_and_receipts_a_tampered_running_binding(tmp_path):
    clock = _Clock()
    controller = _controller(tmp_path, clock=clock)
    running = _running_trial(controller)

    with sqlite3.connect(controller.db_path) as conn:
        conn.execute(
            "UPDATE behavior_trial_creator_approval_bindings "
            "SET proof_id='tampered-proof' WHERE trial_id=?",
            (running["id"],),
        )

    assert controller.chatter_chance() == DEFAULT_CHANCE
    pending = controller.get(running["id"])
    assert pending is not None
    assert pending["state"] == trial_ledger.RUNNING
    controller.maintain_runtime_state()
    rolled_back = controller.get(running["id"])
    assert rolled_back is not None
    assert rolled_back["state"] == trial_ledger.ROLLED_BACK
    assert rolled_back["rollback"]["reason"] == (
        controller_mod.CREATOR_BINDING_VERIFICATION_FAILURE_REASON
    )
    assert rolled_back["rollback"]["evidence"] == {
        "creator_approval_binding": {"verified": False},
        "runtime_override": {
            "parameter": "chatter_chance",
            "trial_id": running["id"],
            "removed": True,
            "was_present": True,
        },
    }
    assert _runtime_rows(controller.db_path) == []
    assert Proactive.CHATTER_CHANCE == DEFAULT_CHANCE


def test_generic_ledger_running_record_with_override_is_receipted_fail_closed(tmp_path):
    controller = _controller(tmp_path)
    registered = trial_ledger.register_trial(
        _validated_chatter_trial(1), scope=SCOPE, db_path=controller.db_path
    )
    trial_ledger.approve_trial(
        registered["id"], _approval(1), scope=SCOPE, db_path=controller.db_path
    )
    running = trial_ledger.start_trial(
        registered["id"],
        scope=SCOPE,
        started_at=STARTED_AT,
        db_path=controller.db_path,
    )
    with sqlite3.connect(controller.db_path) as conn:
        conn.execute(
            """
            INSERT INTO behavior_trial_runtime_overrides
                (trial_id, scope, parameter, preimage_value, override_value, applied_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                running["id"],
                SCOPE,
                controller_mod.CHATTER_CHANCE_PARAMETER,
                DEFAULT_CHANCE,
                TRIAL_CHANCE,
                STARTED_AT,
            ),
        )

    assert controller.chatter_chance() == DEFAULT_CHANCE
    pending = controller.get(running["id"])
    assert pending is not None
    assert pending["state"] == trial_ledger.RUNNING
    controller.maintain_runtime_state()
    rolled_back = controller.get(running["id"])
    assert rolled_back is not None
    assert rolled_back["state"] == trial_ledger.ROLLED_BACK
    assert rolled_back["rollback"]["reason"] == (
        controller_mod.CREATOR_BINDING_VERIFICATION_FAILURE_REASON
    )
    assert rolled_back["rollback"]["evidence"]["runtime_override"]["was_present"]
    assert _runtime_rows(controller.db_path) == []


def test_expire_due_receipts_an_invalid_running_binding_as_a_verification_failure(
    tmp_path,
):
    clock = _Clock()
    controller = _controller(tmp_path, clock=clock)
    running = _running_trial(controller)
    with sqlite3.connect(controller.db_path) as conn:
        conn.execute(
            "UPDATE behavior_trial_creator_approval_bindings "
            "SET approval_seal=? WHERE trial_id=?",
            ("0" * 64, running["id"]),
        )

    clock.set(running["planned_end_at"])
    expired = controller.expire_due()

    assert len(expired) == 1
    assert expired[0]["state"] == trial_ledger.ROLLED_BACK
    assert expired[0]["rollback"]["reason"] == (
        controller_mod.CREATOR_BINDING_VERIFICATION_FAILURE_REASON
    )
    assert _runtime_rows(controller.db_path) == []


def test_recovery_receipts_an_unbound_running_trial_as_a_verification_failure(tmp_path):
    controller = _controller(tmp_path)
    running = _running_trial(controller)
    with sqlite3.connect(controller.db_path) as conn:
        conn.execute(
            "DELETE FROM behavior_trial_creator_approval_bindings WHERE trial_id=?",
            (running["id"],),
        )

    recovered = controller.recover_interrupted(recorded_at=200.0)

    assert len(recovered) == 1
    assert recovered[0]["state"] == trial_ledger.ROLLED_BACK
    assert recovered[0]["rollback"]["reason"] == (
        controller_mod.CREATOR_BINDING_VERIFICATION_FAILURE_REASON
    )
    assert _runtime_rows(controller.db_path) == []


def test_missing_seal_key_receipts_a_running_override_before_consuming_it(tmp_path):
    clock = _Clock()
    controller = _controller(tmp_path, clock=clock)
    running = _running_trial(controller)
    restarted = _controller(
        tmp_path,
        db_path=controller.db_path,
        clock=clock,
        approval_seal_key=None,
    )

    assert restarted.chatter_chance() == DEFAULT_CHANCE
    pending = restarted.get(running["id"])
    assert pending is not None
    assert pending["state"] == trial_ledger.RUNNING
    restarted.maintain_runtime_state()
    rolled_back = restarted.get(running["id"])
    assert rolled_back is not None
    assert rolled_back["state"] == trial_ledger.ROLLED_BACK
    assert rolled_back["rollback"]["reason"] == (
        controller_mod.CREATOR_BINDING_VERIFICATION_FAILURE_REASON
    )
    assert _runtime_rows(controller.db_path) == []


def test_exact_rollback_restores_default_and_records_receipt(tmp_path):
    controller = _controller(tmp_path)
    running = _running_trial(controller)

    rolled_back = controller.rollback(
        running["id"],
        "The fixed metric evidence calls for rollback.",
        recorded_at=200.0,
    )

    assert rolled_back["state"] == trial_ledger.ROLLED_BACK
    assert controller.chatter_chance() == DEFAULT_CHANCE
    assert Proactive.CHATTER_CHANCE == DEFAULT_CHANCE
    assert rolled_back["rollback"]["expected_value"] == DEFAULT_CHANCE
    assert rolled_back["rollback"]["restored_value"] == DEFAULT_CHANCE
    assert rolled_back["rollback"]["reason"] == (
        "The fixed metric evidence calls for rollback."
    )
    assert rolled_back["rollback"]["evidence"] == {
        "runtime_override": {
            "parameter": "chatter_chance",
            "trial_id": running["id"],
            "removed": True,
            "was_present": True,
        }
    }
    assert _runtime_rows(controller.db_path) == []


def test_restart_recovery_restores_default_without_resuming_trial(tmp_path):
    clock = _Clock()
    controller = _controller(tmp_path, clock=clock)
    running = _running_trial(controller)

    restarted = controller_mod.BehaviorTrialController(
        db_path=controller.db_path,
        default_chatter_chance=DEFAULT_CHANCE,
        clock=clock,
        approval_seal_key=APPROVAL_SEAL_KEY,
    )
    assert restarted.chatter_chance() == TRIAL_CHANCE

    recovered = restarted.recover_interrupted(recorded_at=200.0)

    assert len(recovered) == 1
    assert recovered[0]["id"] == running["id"]
    assert recovered[0]["state"] == trial_ledger.ROLLED_BACK
    assert recovered[0]["started_at"] == STARTED_AT
    assert recovered[0]["rollback"]["recorded_at"] == 200.0
    assert recovered[0]["rollback"]["reason"] == controller_mod.INTERRUPTED_RECOVERY_REASON
    assert restarted.chatter_chance() == DEFAULT_CHANCE
    assert restarted.recover_interrupted(recorded_at=201.0) == []
    assert _runtime_rows(restarted.db_path) == []


def test_status_snapshot_is_read_only_and_omits_approval_material(tmp_path, monkeypatch):
    clock = _Clock()
    controller = _controller(tmp_path, clock=clock)
    running = _running_trial(controller)
    before = controller.get(running["id"])
    assert before is not None
    original_connect = controller_mod.sqlite3.connect
    statements: list[str] = []

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    def unexpected_mutator(*_args, **_kwargs):
        raise AssertionError("status_snapshot must not invoke a runtime mutator")

    for method_name in (
        "chatter_chance",
        "expire_due",
        "recover_interrupted",
        "start",
        "rollback",
    ):
        monkeypatch.setattr(controller, method_name, unexpected_mutator)
    monkeypatch.setattr(controller_mod.sqlite3, "connect", traced_connect)

    snapshot = controller.status_snapshot()

    assert snapshot == {
        "active_trial": {
            "id": running["id"],
            "scope": SCOPE,
            "proposal_id": 1,
            "state": trial_ledger.RUNNING,
            "parameter": "chatter_chance",
            "started_at": STARTED_AT,
            "planned_end_at": running["planned_end_at"],
            "creator_binding_present": True,
        },
        "runtime_override": {
            "trial_id": running["id"],
            "scope": SCOPE,
            "parameter": "chatter_chance",
            "preimage_value": DEFAULT_CHANCE,
            "override_value": TRIAL_CHANCE,
            "applied_at": STARTED_AT,
        },
    }
    assert statements
    assert len(statements) == 1
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert snapshot["active_trial"]["id"] == snapshot["runtime_override"]["trial_id"]
    snapshot_json = json.dumps(snapshot, sort_keys=True)
    assert "proof_id" not in snapshot_json
    assert "approval-" not in snapshot_json
    assert AUTHORIZATION_MECHANISM not in snapshot_json

    with original_connect(controller.db_path) as conn:
        after = conn.execute(
            "SELECT state, started_at, planned_end_at, approval_json "
            "FROM experiment_trial_ledger WHERE id=?",
            (running["id"],),
        ).fetchone()
        runtime_after = conn.execute(
            "SELECT trial_id, preimage_value, override_value, applied_at "
            "FROM behavior_trial_runtime_overrides"
        ).fetchall()
    assert after == (
        before["state"],
        before["started_at"],
        before["planned_end_at"],
        json.dumps(
            before["approval_proof"], separators=(",", ":"), sort_keys=True
        ),
    )
    assert runtime_after == [
        (running["id"], DEFAULT_CHANCE, TRIAL_CHANCE, STARTED_AT)
    ]


def test_due_status_snapshot_uses_one_consistent_read_only_snapshot_until_consumed(
    tmp_path, monkeypatch
):
    clock = _Clock()
    controller = _controller(tmp_path, clock=clock)
    running = _running_trial(controller)
    clock.set(running["planned_end_at"])
    before = controller.get(running["id"])
    assert before is not None
    original_connect = controller_mod.sqlite3.connect
    statements: list[str] = []

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(controller_mod.sqlite3, "connect", traced_connect)
    first = controller.status_snapshot()
    second = controller.status_snapshot()
    monkeypatch.undo()

    assert first == second
    assert first["active_trial"]["id"] == running["id"]
    assert first["active_trial"]["state"] == trial_ledger.RUNNING
    assert first["runtime_override"]["trial_id"] == running["id"]
    assert len(statements) == 2
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    unchanged = controller.get(running["id"])
    assert unchanged is not None
    assert unchanged["state"] == before["state"]
    assert unchanged["rollback"] is None
    assert _runtime_rows(controller.db_path) == [
        (running["id"], DEFAULT_CHANCE, TRIAL_CHANCE)
    ]

    assert controller.chatter_chance() == DEFAULT_CHANCE
    pending = controller.get(running["id"])
    assert pending is not None
    assert pending["state"] == trial_ledger.RUNNING
    controller.maintain_runtime_state()
    rolled_back = controller.get(running["id"])
    assert rolled_back is not None
    assert rolled_back["state"] == trial_ledger.ROLLED_BACK
    assert _runtime_rows(controller.db_path) == []


def test_chatter_chance_is_read_only_when_a_trial_is_due(tmp_path, monkeypatch):
    clock = _Clock()
    controller = _controller(tmp_path, clock=clock)
    running = _running_trial(controller)
    clock.set(running["planned_end_at"])
    original_connect = controller_mod.sqlite3.connect
    statements: list[str] = []

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(controller_mod.sqlite3, "connect", traced_connect)
    assert controller.chatter_chance() == DEFAULT_CHANCE
    monkeypatch.undo()

    assert statements
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    pending = controller.get(running["id"])
    assert pending is not None
    assert pending["state"] == trial_ledger.RUNNING
    assert _runtime_rows(controller.db_path) == [
        (running["id"], DEFAULT_CHANCE, TRIAL_CHANCE)
    ]


def test_maintenance_receipts_malformed_spec_with_a_runtime_override(tmp_path):
    controller = _controller(tmp_path)
    running = _running_trial(controller)
    with sqlite3.connect(controller.db_path) as conn:
        conn.execute("DROP TRIGGER experiment_trial_spec_immutable")
        conn.execute(
            "UPDATE experiment_trial_ledger SET spec_json=? WHERE id=?",
            ("{not-json", running["id"]),
        )

    closed = controller.maintain_runtime_state()

    assert closed == [{
        "id": running["id"],
        "scope": SCOPE,
        "state": trial_ledger.ROLLED_BACK,
        "rollback": {"reason": controller_mod.CREATOR_BINDING_VERIFICATION_FAILURE_REASON},
    }]
    with sqlite3.connect(controller.db_path) as conn:
        state = conn.execute(
            "SELECT state FROM experiment_trial_ledger WHERE id=?", (running["id"],)
        ).fetchone()[0]
        reason = conn.execute(
            "SELECT reason FROM experiment_trial_rollbacks WHERE trial_id=?",
            (running["id"],),
        ).fetchone()[0]
    assert state == trial_ledger.ROLLED_BACK
    assert reason == controller_mod.CREATOR_BINDING_VERIFICATION_FAILURE_REASON
    assert _runtime_rows(controller.db_path) == []


def test_maintenance_receipts_a_corrupt_runtime_override(tmp_path):
    controller = _controller(tmp_path)
    running = _running_trial(controller)
    with sqlite3.connect(controller.db_path) as conn:
        conn.execute(
            "UPDATE behavior_trial_runtime_overrides SET override_value=? WHERE trial_id=?",
            ("not-a-number", running["id"]),
        )

    closed = controller.maintain_runtime_state()

    assert len(closed) == 1
    assert closed[0]["id"] == running["id"]
    assert closed[0]["state"] == trial_ledger.ROLLED_BACK
    assert closed[0]["rollback"]["reason"] == (
        controller_mod.CREATOR_BINDING_VERIFICATION_FAILURE_REASON
    )
    assert _runtime_rows(controller.db_path) == []


def test_recovery_receipts_a_completed_trial_with_corrupted_binding(tmp_path):
    controller = _controller(tmp_path)
    running = _running_trial(controller)
    with sqlite3.connect(controller.db_path) as conn:
        conn.execute(
            "UPDATE experiment_trial_ledger SET state='completed' WHERE id=?",
            (running["id"],),
        )
        conn.execute(
            "UPDATE behavior_trial_creator_approval_bindings "
            "SET approval_seal=? WHERE trial_id=?",
            ("0" * 64, running["id"]),
        )

    recovered = controller.recover_interrupted(recorded_at=200.0)

    assert len(recovered) == 1
    assert recovered[0]["id"] == running["id"]
    assert recovered[0]["state"] == trial_ledger.ROLLED_BACK
    assert recovered[0]["rollback"]["reason"] == (
        controller_mod.CREATOR_BINDING_VERIFICATION_FAILURE_REASON
    )
    assert _runtime_rows(controller.db_path) == []


def test_controller_mutates_only_the_supplied_temporary_database(tmp_path):
    db_path = tmp_path / "behavior-trials.db"
    sentinel = tmp_path / "outside-controller-db.txt"
    sentinel.write_text("must remain unchanged", encoding="utf-8")
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and not path.name.startswith(db_path.name)
    }

    controller = _controller(tmp_path, db_path=db_path)
    running = _running_trial(controller)
    controller.rollback(running["id"], "Temporary-db confinement check.", recorded_at=200.0)

    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and not path.name.startswith(db_path.name)
    }
    assert before == after
    assert db_path.is_file()
    assert controller.db_path == db_path
    assert Proactive.CHATTER_CHANCE == DEFAULT_CHANCE


def test_coremind_supplier_reuses_one_override_for_both_chatter_gates(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca.homeostasis import EmotionalState

    supplied: list[float] = []
    chances: list[float] = []
    mind = mind_mod.CoreMind.__new__(mind_mod.CoreMind)
    mind.state = EmotionalState(love=0.55, social_hunger=0.35)
    mind._last_user_ts = 0.0
    mind._last_volunteer_ts = 0.0
    mind._last_situation = ""

    def supplier() -> float:
        supplied.append(TRIAL_CHANCE)
        return TRIAL_CHANCE

    def should_chatter(*_args, **kwargs) -> bool:
        chances.append(kwargs["chance"])
        return True

    mind.set_chatter_chance_supplier(supplier)
    monkeypatch.setattr(mind_mod.ProactiveCfg, "ENABLED", True)
    monkeypatch.setattr(mind_mod, "PROACTIVE_LLM", False)
    monkeypatch.setattr(mind, "_prompt_situation", lambda _base: "")
    monkeypatch.setattr(mind_mod.proactive_mod, "should_speak", lambda *_args: None)
    monkeypatch.setattr(mind_mod.proactive_mod, "should_chatter", should_chatter)
    monkeypatch.setattr(mind_mod.proactive_mod, "chatter_reasons", lambda **_kwargs: ["seed"])
    monkeypatch.setattr(mind_mod.memory_store, "recent", lambda **_kwargs: [])

    assert mind.volunteer_reason() == "seed"
    assert supplied == [TRIAL_CHANCE]
    assert chances == [TRIAL_CHANCE, TRIAL_CHANCE]
