"""One real SQLite cycle for bounded recursive behavior improvement."""
from __future__ import annotations

from alpecca import behavior_trial_candidates as candidates_mod
from alpecca import behavior_trial_profile as profile_mod
from alpecca import behavior_trial_settlement as settlement_mod
from alpecca import cognition
from alpecca.behavior_trial_controller import BehaviorTrialController
from alpecca.qualified_response_ledger import QualifiedResponseLedger


class _Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _outcome(
    ledger: QualifiedResponseLedger,
    delivery_id: str,
    *,
    at: float,
    trial_id: int | None,
    responded: bool,
) -> None:
    ledger.begin_dispatch(
        delivery_id=delivery_id,
        scope_key="creator:house-hq",
        surface="house-hq",
        proactive_turn_id=f"proactive-{delivery_id}",
        response_window_seconds=10.0,
        trial_id=trial_id,
        dispatched_at=at,
    )
    ledger.confirm_delivery(delivery_id, delivered_at=at + 1.0)
    if responded:
        ledger.record_creator_response(
            scope_key="creator:house-hq",
            surface="house-hq",
            response_turn_id=f"response-{delivery_id}",
            received_at=at + 2.0,
        )


def test_creator_reviewed_cycle_retains_value_and_generates_successor(tmp_path):
    db_path = tmp_path / "bounded-rsi.db"
    seal_key = b"phase8-end-to-end-seal-key"
    clock = _Clock(100.0)
    outcomes = QualifiedResponseLedger(db_path)
    candidates = candidates_mod.BehaviorTrialCandidateStore(
        db_path,
        seal_key=seal_key,
    )
    controller = BehaviorTrialController(
        db_path,
        default_chatter_chance=0.25,
        clock=clock,
        approval_seal_key=seal_key,
    )
    profile = profile_mod.BehaviorTrialProfileStore(db_path, seal_key=seal_key)

    for index, responded in enumerate((True, True, False, False, False)):
        _outcome(
            outcomes,
            f"baseline-{index}",
            at=10.0 + index * 20.0,
            trial_id=None,
            responded=responded,
        )
    outcomes.expire_due(now=110.0)
    baseline = outcomes.baseline_summary()
    assert baseline["completed"] == 5
    assert baseline["rate"] == 0.4

    issued = candidates.issue_from_baseline(
        baseline,
        preimage_value=controller.default_chatter_chance,
        issued_at=120.0,
    )
    proposal_id = int(issued["proposal"]["id"])
    cognition.update_action_proposal(
        proposal_id,
        status="accepted",
        result="Creator accepted bounded trial plan.",
        approved_by_user=True,
        db_path=db_path,
    )
    details = candidates.registration_details(
        proposal_id,
        default_chatter_chance=controller.default_chatter_chance,
    )
    first_trial = controller.register(details["spec"])
    candidates.mark_registered(
        proposal_id,
        trial_id=first_trial["id"],
        principal="creator",
        mechanism="trusted_device",
        registered_at=121.0,
    )
    controller.approve_creator(
        first_trial["id"],
        principal="creator",
        authorization_mechanism="trusted_device",
        authorization_issued_at=115.0,
        authorization_expires_at=10_000.0,
        approved_at=130.0,
    )
    clock.value = 140.0
    running = controller.start(first_trial["id"], started_at=140.0)
    assert controller.chatter_chance() == 0.23

    for index, responded in enumerate((True, True, True, False, False)):
        _outcome(
            outcomes,
            f"trial-{index}",
            at=150.0 + index * 20.0,
            trial_id=running["id"],
            responded=responded,
        )
    outcomes.expire_due(now=250.0)
    clock.value = float(running["planned_end_at"])
    closed = controller.maintain_runtime_state()
    assert closed[0]["id"] == running["id"]
    assert controller.chatter_chance() == 0.25

    settlements = settlement_mod.settle_closed_trials(
        db_path,
        settled_at=clock.value + 1.0,
    )
    assert settlements[0]["outcome"] == "improved"
    assert settlements[0]["creator_retention_eligible"] is True

    decision, created = profile.decide(
        running["id"],
        decision=profile_mod.RETAIN_TRIAL_VALUE,
        expected_current_value=controller.default_chatter_chance,
        principal="creator",
        authorization_mechanism="trusted_device",
        decided_at=clock.value + 2.0,
    )
    assert created is True
    assert decision["applied_value"] == 0.23
    controller.adopt_profile_chatter_chance(decision["applied_value"])
    assert controller.chatter_chance() == 0.23

    epoch_start = float(profile.active_profile(0.25)["updated_at"])
    for index, responded in enumerate((True, True, False, False, False)):
        _outcome(
            outcomes,
            f"next-baseline-{index}",
            at=epoch_start + 10.0 + index * 20.0,
            trial_id=None,
            responded=responded,
        )
    outcomes.expire_due(now=epoch_start + 110.0)
    fresh_baseline = outcomes.baseline_summary(since=epoch_start)
    assert fresh_baseline["completed"] == 5
    assert fresh_baseline["rate"] == 0.4

    successor = candidates.issue_from_baseline(
        fresh_baseline,
        preimage_value=controller.default_chatter_chance,
        issued_at=epoch_start + 120.0,
    )
    assert successor["issued"] is True
    assert successor["reused"] is False
    assert successor["candidate"]["payload"]["preimage_value"] == 0.23
    assert successor["candidate"]["payload"]["trial_value"] == 0.21
    assert successor["candidate"]["payload"]["exposure_seconds"] == 7200.0
