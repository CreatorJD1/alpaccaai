"""Focused pure-policy coverage for bounded Phase 8 trials."""
from __future__ import annotations

import dataclasses

import pytest

from alpecca import experiment_trials
from alpecca import self_improvement_policy as policy


SCOPE = "creator-private"


def validated_trial(
    *,
    proposal_id: int = 42,
    parameter: str = "chatter_chance",
    baseline: float = 0.35,
):
    values = {
        "chatter_chance": (0.25, 0.22),
        "curiosity_gain": (0.9, 1.0),
    }
    old_value, trial_value = values.get(parameter, (0.25, 0.22))
    return experiment_trials.validate_trial_spec(
        experiment_trials.TrialSpecification(
            proposal_id=proposal_id,
            parameter=parameter,
            hypothesis="The bounded change will improve the named metric.",
            metric="ignored_outreach_rate",
            baseline=baseline,
            exposure=experiment_trials.ExposureWindow(300, 5),
            change=experiment_trials.ParameterChange(old_value, trial_value),
            rollback_value=old_value,
        )
    )


def approval(*, proposal_id: int = 42, scope: str = SCOPE, decision="approved"):
    return {
        "proposal_id": proposal_id,
        "scope": scope,
        "proof_id": "approval-1",
        "authority": "creator-session",
        "approved_at": 100.0,
        "decision": decision,
    }


def ledger_record(*, state: str = "approved", scope: str = SCOPE, trial_id: int = 7):
    spec = validated_trial()
    return {
        "id": trial_id,
        "scope": scope,
        "proposal_id": spec.proposal_id,
        "state": state,
        "spec": dataclasses.asdict(spec),
        "approval_proof": approval(),
    }


def evidence_by_check(decision):
    return {item.check: item for item in decision.evidence}


def test_valid_normalized_spec_with_scoped_approval_is_allowed():
    decision = policy.evaluate_self_improvement_trial(
        validated_trial(),
        scope=SCOPE,
        approval_proof=approval(),
        active_trials=(),
    )

    assert decision.allowed
    assert decision.decision == "allow"
    assert decision.reason == "allowed"
    evidence = evidence_by_check(decision)
    assert set(evidence) == {
        "target_boundary",
        "allowed_parameter",
        "metric_plan",
        "exact_rollback",
        "validated_spec",
        "scoped_approval",
        "active_conflict",
    }
    assert all(item.passed for item in decision.evidence)
    assert "proactive.should_chatter" in evidence["allowed_parameter"].detail


def test_approved_ledger_shape_is_accepted_and_its_own_active_row_is_ignored():
    record = ledger_record()
    decision = policy.evaluate_trial(
        record,
        scope=SCOPE,
        active_trials=[record],
    )

    assert decision.allowed
    assert decision.evidence[-1].check == "active_conflict"


def test_raw_or_malformed_spec_is_denied_as_unvalidated():
    normalized = validated_trial()
    raw = experiment_trials.TrialSpecification(
        proposal_id=normalized.proposal_id,
        parameter=normalized.parameter,
        hypothesis=normalized.hypothesis,
        metric=normalized.metric,
        baseline=normalized.baseline,
        exposure=experiment_trials.ExposureWindow(
            normalized.exposure_seconds, normalized.min_samples
        ),
        change=experiment_trials.ParameterChange(
            normalized.old_value, normalized.trial_value
        ),
        rollback_value=normalized.rollback_value,
    )

    for candidate in (raw, {"parameter": "chatter_chance"}, object()):
        decision = policy.evaluate_trial(
            candidate, scope=SCOPE, approval_proof=approval()
        )
        assert not decision.allowed
        assert decision.reason == "unvalidated_spec"


@pytest.mark.parametrize(
    ("proof", "reason"),
    [
        (None, "approval_required"),
        (approval(scope="guest-private"), "scope_mismatch"),
        (approval(proposal_id=99), "approval_required"),
        (approval(decision="rejected"), "approval_required"),
        ({**approval(), "proof_id": ""}, "approval_required"),
    ],
)
def test_scoped_approved_proposal_proof_is_mandatory(proof, reason):
    decision = policy.evaluate_trial(
        validated_trial(), scope=SCOPE, approval_proof=proof
    )

    assert not decision.allowed
    assert decision.reason == reason
    assert evidence_by_check(decision)["scoped_approval"].passed is False


@pytest.mark.parametrize("state", ["registered", "running", "completed", "rolled_back"])
def test_ledger_candidate_must_be_at_approved_gate_state(state):
    decision = policy.evaluate_trial(ledger_record(state=state), scope=SCOPE)

    assert not decision.allowed
    assert decision.reason == "approval_required"


def test_positive_metric_baseline_and_plan_are_required():
    zero = policy.evaluate_trial(
        validated_trial(baseline=0.0), scope=SCOPE, approval_proof=approval()
    )
    negative = policy.evaluate_trial(
        validated_trial(baseline=-0.1), scope=SCOPE, approval_proof=approval()
    )

    assert zero.reason == "invalid_metric_plan"
    assert negative.reason == "invalid_metric_plan"
    assert evidence_by_check(zero)["metric_plan"].passed is False


def test_exact_rollback_is_checked_before_validator_replay():
    forged = dataclasses.asdict(validated_trial())
    forged["rollback_value"] = 0.2500000001

    decision = policy.evaluate_trial(
        forged, scope=SCOPE, approval_proof=approval()
    )

    assert decision.reason == "rollback_mismatch"
    assert evidence_by_check(decision)["exact_rollback"].passed is False


@pytest.mark.parametrize(
    "parameter",
    [
        "source.code",
        "files.delete_allowed",
        "os.pagefile_mb",
        "account.password",
        "network.port",
        "system.service",
    ],
)
def test_code_file_os_account_network_and_system_targets_are_categorically_denied(
    parameter,
):
    forged = dataclasses.asdict(validated_trial())
    forged["parameter"] = parameter

    decision = policy.evaluate_trial(
        forged, scope=SCOPE, approval_proof=approval()
    )

    assert decision.reason == "forbidden_target"
    assert evidence_by_check(decision)["target_boundary"].passed is False


def test_unknown_behavioral_parameter_is_not_allowlisted():
    forged = dataclasses.asdict(validated_trial())
    forged["parameter"] = "personality_creativity"

    decision = policy.evaluate_trial(
        forged, scope=SCOPE, approval_proof=approval()
    )

    assert decision.reason == "parameter_not_allowed"
    assert evidence_by_check(decision)["allowed_parameter"].passed is False


def test_other_active_trial_in_same_scope_denies_but_closed_or_other_scope_does_not():
    candidate = ledger_record(trial_id=7)
    conflict = {
        **ledger_record(trial_id=8),
        "proposal_id": 99,
        "state": "running",
    }
    denied = policy.evaluate_trial(candidate, scope=SCOPE, active_trials=[conflict])
    closed = policy.evaluate_trial(
        candidate,
        scope=SCOPE,
        active_trials=[{**conflict, "state": "completed"}],
    )
    other_scope = policy.evaluate_trial(
        candidate,
        scope=SCOPE,
        active_trials=[{**conflict, "scope": "guest-private"}],
    )

    assert denied.reason == "conflicting_trial"
    assert not evidence_by_check(denied)["active_conflict"].passed
    assert closed.allowed
    assert other_scope.allowed


def test_malformed_active_inventory_fails_closed():
    decision = policy.evaluate_trial(
        validated_trial(),
        scope=SCOPE,
        approval_proof=approval(),
        active_trials=[object()],
    )

    assert decision.reason == "conflicting_trial"
    assert "unstructured" in decision.evidence[-1].detail


def test_decision_is_deterministic_immutable_and_does_not_mutate_inputs():
    candidate = ledger_record()
    before = dataclasses.asdict(validated_trial())
    active = []

    first = policy.evaluate_trial(candidate, scope=SCOPE, active_trials=active)
    second = policy.evaluate_trial(candidate, scope=SCOPE, active_trials=active)

    assert first == second
    assert candidate["spec"] == before
    assert active == []
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.reason = "forged"
