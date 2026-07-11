"""Focused integration coverage for the Phase 8 runtime trial controller."""
from __future__ import annotations

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


def _controller(tmp_path, *, clock: _Clock | None = None, db_path=None):
    return controller_mod.BehaviorTrialController(
        db_path=tmp_path / "behavior-trials.db" if db_path is None else db_path,
        default_chatter_chance=DEFAULT_CHANCE,
        clock=_Clock() if clock is None else clock,
    )


def _approved_trial(controller, proposal_id: int, **spec_values):
    registered = controller.register(
        _validated_chatter_trial(proposal_id, **spec_values)
    )
    controller.approve(registered["id"], _approval(proposal_id))
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

    assert running["state"] == trial_ledger.RUNNING
    assert controller.chatter_chance() == TRIAL_CHANCE
    assert proactive.should_chatter(**_eligible_chatter_args(), roll=gate_roll)
    assert not proactive.should_chatter(
        **_eligible_chatter_args(),
        roll=gate_roll,
        chance=controller.chatter_chance(),
    )
    assert Proactive.CHATTER_CHANCE == DEFAULT_CHANCE
    assert _runtime_rows(controller.db_path) == [(running["id"], DEFAULT_CHANCE, TRIAL_CHANCE)]


def test_foreign_scope_and_non_chatter_trials_are_rejected(tmp_path):
    db_path = tmp_path / "behavior-trials.db"
    controller = controller_mod.BehaviorTrialController(
        db_path=db_path,
        default_chatter_chance=DEFAULT_CHANCE,
        clock=_Clock(),
    )

    with pytest.raises(controller_mod.ForeignBehaviorTrialScope):
        controller_mod.BehaviorTrialController(
            db_path=db_path,
            scope="guest-private",
            clock=_Clock(),
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


def test_due_trial_rolls_back_before_chatter_chance_returns(tmp_path):
    clock = _Clock()
    controller = _controller(tmp_path, clock=clock)
    running = _running_trial(controller)
    assert controller.chatter_chance() == TRIAL_CHANCE

    clock.set(running["planned_end_at"])

    assert controller.chatter_chance() == DEFAULT_CHANCE
    rolled_back = controller.get(running["id"])
    assert rolled_back is not None
    assert rolled_back["state"] == trial_ledger.ROLLED_BACK
    assert rolled_back["ended_at"] == running["planned_end_at"]
    assert rolled_back["rollback"]["recorded_at"] == running["planned_end_at"]
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
