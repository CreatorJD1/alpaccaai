"""Focused validation tests for bounded Phase 8 experiment specifications."""
from __future__ import annotations

import dataclasses

import pytest

from alpecca import experiment_trials as trials


def valid_spec(**overrides) -> trials.TrialSpecification:
    values = {
        "proposal_id": 42,
        "parameter": "chatter_chance",
        "hypothesis": "Reducing chatter slightly will lower ignored outreach.",
        "metric": "ignored_outreach_rate",
        "baseline": 0.35,
        "exposure": trials.ExposureWindow(duration_seconds=1800, min_samples=20),
        "change": trials.ParameterChange(old_value=0.25, trial_value=0.22),
        "rollback_value": 0.25,
    }
    values.update(overrides)
    return trials.TrialSpecification(**values)


def test_valid_spec_is_normalized_and_names_a_real_consumer():
    validated = trials.validate_trial_spec(valid_spec(
        hypothesis="  Reducing   chatter slightly will lower ignored outreach.  ",
    ))

    assert validated.proposal_id == 42
    assert validated.parameter == "chatter_chance"
    assert validated.hypothesis == (
        "Reducing chatter slightly will lower ignored outreach."
    )
    assert validated.metric == "ignored_outreach_rate"
    assert validated.baseline == 0.35
    assert validated.exposure_seconds == 1800
    assert validated.min_samples == 20
    assert validated.old_value == 0.25
    assert validated.trial_value == 0.22
    assert validated.change == pytest.approx(-0.03)
    assert validated.rollback_value == 0.25
    assert validated.consumer == "proactive.should_chatter"
    with pytest.raises(dataclasses.FrozenInstanceError):
        validated.trial_value = 0.3


@pytest.mark.parametrize(
    ("parameter", "old_value", "trial_value", "consumer"),
    [
        ("curiosity_gain", 0.9, 1.0, "homeostasis.EmotionalState.update_curiosity"),
        (
            "social_hunger_rate",
            0.6,
            0.66,
            "homeostasis.EmotionalState.update_social_hunger",
        ),
        ("chatter_chance", 0.25, 0.2, "proactive.should_chatter"),
        ("reflect_chance", 0.15, 0.18, "proactive.should_reflect"),
    ],
)
def test_every_allowlisted_parameter_has_a_consumed_behavior_path(
    parameter, old_value, trial_value, consumer
):
    result = trials.validate_trial(valid_spec(
        parameter=parameter,
        change=trials.ParameterChange(old_value, trial_value),
        rollback_value=old_value,
    ))

    assert result.consumer == consumer
    assert parameter in trials.allowed_parameter_names()


@pytest.mark.parametrize("proposal_id", [None, True, 0, -1, 1.5, "12"])
def test_proposal_id_must_be_a_positive_integer(proposal_id):
    with pytest.raises(trials.TrialValidationError, match="proposal_id"):
        trials.validate_trial(valid_spec(proposal_id=proposal_id))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hypothesis", ""),
        ("hypothesis", "   "),
        ("metric", ""),
        ("metric", None),
    ],
)
def test_hypothesis_and_metric_are_required(field, value):
    with pytest.raises(trials.TrialValidationError, match=field):
        trials.validate_trial(valid_spec(**{field: value}))


@pytest.mark.parametrize(
    "exposure",
    [
        trials.ExposureWindow(299, 20),
        trials.ExposureWindow(trials.MAX_EXPOSURE_SECONDS + 1, 20),
        trials.ExposureWindow(1800, 4),
        trials.ExposureWindow(1800, trials.MAX_EXPOSURE_SAMPLES + 1),
        trials.ExposureWindow(float("nan"), 20),
    ],
)
def test_exposure_requires_bounded_time_and_sample_count(exposure):
    with pytest.raises(trials.TrialValidationError, match="exposure"):
        trials.validate_trial(valid_spec(exposure=exposure))


@pytest.mark.parametrize(
    "change",
    [
        trials.ParameterChange(0.25, 0.25),
        trials.ParameterChange(0.25, 0.31),
        trials.ParameterChange(0.01, 0.06),
        trials.ParameterChange(0.25, 0.5),
        trials.ParameterChange(float("inf"), 0.2),
        trials.ParameterChange(0.25, float("nan")),
    ],
)
def test_change_must_be_finite_nonzero_and_within_rule_bounds(change):
    with pytest.raises(trials.TrialValidationError):
        trials.validate_trial(valid_spec(change=change))


def test_rollback_value_must_exactly_match_old_value():
    with pytest.raises(trials.TrialValidationError, match="exactly equal"):
        trials.validate_trial(valid_spec(rollback_value=0.2500000001))


@pytest.mark.parametrize(
    "parameter",
    [
        "source.code",
        "files.delete_allowed",
        "os.pagefile_mb",
        "account.password",
        "network.port",
        "system.ram_limit",
        "shell_command",
        "registry.value",
    ],
)
def test_code_files_os_accounts_network_and_system_targets_are_forbidden(parameter):
    with pytest.raises(trials.ForbiddenTrialTarget):
        trials.validate_trial(valid_spec(parameter=parameter))


def test_unknown_behavioral_knob_is_rejected_by_default():
    with pytest.raises(trials.UnknownBehavioralParameter, match="not an allowlisted"):
        trials.validate_trial(valid_spec(parameter="personality_creativity"))


@pytest.mark.parametrize("baseline", [True, float("nan"), float("inf"), "0.3"])
def test_metric_baseline_must_be_a_finite_number(baseline):
    with pytest.raises(trials.TrialValidationError, match="baseline"):
        trials.validate_trial(valid_spec(baseline=baseline))


def test_validation_is_pure_deterministic_and_allowlist_is_immutable():
    spec = valid_spec()

    assert trials.validate_trial(spec) == trials.validate_trial(spec)
    with pytest.raises(TypeError):
        trials.ALLOWED_PARAMETERS["new_parameter"] = trials.ParameterRule(
            0.0, 1.0, 0.1, "invented.consumer"
        )
    with pytest.raises(TypeError, match="TrialSpecification"):
        trials.validate_trial({"proposal_id": 42})
