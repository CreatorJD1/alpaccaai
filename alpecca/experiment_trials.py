"""Pure specification validation for bounded Phase 8 behavior trials.

This module neither starts experiments nor reads policy from a database.  It
defines the only behavioral parameters eligible for future trials and validates
that a proposed trial is measurable, time-bounded, reversible, and confined to
that surface.  Code, files, accounts, networking, and system configuration are
categorically outside the allowlist.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping


MIN_EXPOSURE_SECONDS = 300.0
MAX_EXPOSURE_SECONDS = 7 * 24 * 60 * 60.0
MIN_EXPOSURE_SAMPLES = 5
MAX_EXPOSURE_SAMPLES = 10_000

_MAX_HYPOTHESIS_LENGTH = 1000
_MAX_METRIC_LENGTH = 160


class TrialValidationError(ValueError):
    """A trial specification is incomplete, unbounded, or unsafe."""


class ForbiddenTrialTarget(TrialValidationError):
    """A trial targets a category autonomous improvement may never change."""


class UnknownBehavioralParameter(TrialValidationError):
    """A trial targets a parameter with no approved, proven consumer."""


@dataclass(frozen=True, slots=True)
class ParameterRule:
    """Static bounds for one behavioral parameter consumed by current code."""

    minimum: float
    maximum: float
    max_delta: float
    consumer: str


# These four values are read by the named behavior paths today.  The validator
# intentionally does not import selfmod/config or infer new knobs from a DB.
# Chatter/reflection bounds include their current consumed defaults (0.25/0.15),
# unlike the stale narrower selfmod ranges that predate those defaults.
_RULES = {
    "curiosity_gain": ParameterRule(
        minimum=0.4,
        maximum=1.4,
        max_delta=0.2,
        consumer="homeostasis.EmotionalState.update_curiosity",
    ),
    "social_hunger_rate": ParameterRule(
        minimum=0.3,
        maximum=0.9,
        max_delta=0.12,
        consumer="homeostasis.EmotionalState.update_social_hunger",
    ),
    "chatter_chance": ParameterRule(
        minimum=0.05,
        maximum=0.35,
        max_delta=0.05,
        consumer="proactive.should_chatter",
    ),
    "reflect_chance": ParameterRule(
        minimum=0.03,
        maximum=0.25,
        max_delta=0.04,
        consumer="proactive.should_reflect",
    ),
}

ALLOWED_PARAMETERS: Mapping[str, ParameterRule] = MappingProxyType(_RULES)

_FORBIDDEN_TARGET_WORDS = frozenset({
    "account",
    "accounts",
    "api",
    "code",
    "command",
    "credential",
    "credentials",
    "directory",
    "file",
    "files",
    "filesystem",
    "hardware",
    "network",
    "os",
    "pagefile",
    "password",
    "path",
    "process",
    "registry",
    "service",
    "shell",
    "socket",
    "source",
    "system",
    "token",
    "user",
    "users",
})


@dataclass(frozen=True, slots=True)
class ExposureWindow:
    """Minimum observation time and sample count before evaluation."""

    duration_seconds: float
    min_samples: int


@dataclass(frozen=True, slots=True)
class ParameterChange:
    """The currently consumed value and the bounded value to trial."""

    old_value: float
    trial_value: float


@dataclass(frozen=True, slots=True)
class TrialSpecification:
    """Untrusted trial description accepted by :func:`validate_trial_spec`."""

    proposal_id: int
    parameter: str
    hypothesis: str
    metric: str
    baseline: float
    exposure: ExposureWindow
    change: ParameterChange
    rollback_value: float


@dataclass(frozen=True, slots=True)
class ValidatedTrialSpecification:
    """Normalized specification safe for a later approval/execution layer."""

    proposal_id: int
    parameter: str
    hypothesis: str
    metric: str
    baseline: float
    exposure_seconds: float
    min_samples: int
    old_value: float
    trial_value: float
    change: float
    rollback_value: float
    parameter_minimum: float
    parameter_maximum: float
    max_change: float
    consumer: str


def _required_text(value: object, *, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TrialValidationError(f"{name} must be a string")
    cleaned = " ".join(value.split())
    if not cleaned:
        raise TrialValidationError(f"{name} is required")
    if len(cleaned) > maximum:
        raise TrialValidationError(f"{name} exceeds {maximum} characters")
    return cleaned


def _finite_number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrialValidationError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise TrialValidationError(f"{name} must be finite")
    return result


def _parameter(value: object) -> tuple[str, ParameterRule]:
    if not isinstance(value, str):
        raise TrialValidationError("parameter must be a string")
    name = value.strip().lower()
    if name in ALLOWED_PARAMETERS:
        return name, ALLOWED_PARAMETERS[name]
    words = set(re.findall(r"[a-z0-9]+", name))
    forbidden = sorted(words & _FORBIDDEN_TARGET_WORDS)
    if forbidden:
        raise ForbiddenTrialTarget(
            f"trial target {name!r} is categorically forbidden ({forbidden[0]})"
        )
    raise UnknownBehavioralParameter(
        f"trial target {name or '<empty>'!r} is not an allowlisted consumed parameter"
    )


def _proposal_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TrialValidationError("proposal_id must be a positive integer")
    return value


def _exposure(value: object) -> tuple[float, int]:
    if not isinstance(value, ExposureWindow):
        raise TrialValidationError("exposure must be an ExposureWindow")
    seconds = _finite_number(value.duration_seconds, name="exposure duration")
    samples = value.min_samples
    if not MIN_EXPOSURE_SECONDS <= seconds <= MAX_EXPOSURE_SECONDS:
        raise TrialValidationError(
            "exposure duration must be between "
            f"{MIN_EXPOSURE_SECONDS:g} and {MAX_EXPOSURE_SECONDS:g} seconds"
        )
    if (
        isinstance(samples, bool)
        or not isinstance(samples, int)
        or not MIN_EXPOSURE_SAMPLES <= samples <= MAX_EXPOSURE_SAMPLES
    ):
        raise TrialValidationError(
            "exposure min_samples must be between "
            f"{MIN_EXPOSURE_SAMPLES} and {MAX_EXPOSURE_SAMPLES}"
        )
    return seconds, samples


def validate_trial_spec(spec: TrialSpecification) -> ValidatedTrialSpecification:
    """Validate and normalize one bounded, exactly reversible behavior trial."""
    if not isinstance(spec, TrialSpecification):
        raise TypeError("spec must be a TrialSpecification")

    proposal_id = _proposal_id(spec.proposal_id)
    parameter, rule = _parameter(spec.parameter)
    hypothesis = _required_text(
        spec.hypothesis, name="hypothesis", maximum=_MAX_HYPOTHESIS_LENGTH
    )
    metric = _required_text(spec.metric, name="metric", maximum=_MAX_METRIC_LENGTH)
    baseline = _finite_number(spec.baseline, name="baseline")
    exposure_seconds, min_samples = _exposure(spec.exposure)
    if not isinstance(spec.change, ParameterChange):
        raise TrialValidationError("change must be a ParameterChange")
    old_value = _finite_number(spec.change.old_value, name="change.old_value")
    trial_value = _finite_number(spec.change.trial_value, name="change.trial_value")
    rollback_value = _finite_number(spec.rollback_value, name="rollback_value")

    if not rule.minimum <= old_value <= rule.maximum:
        raise TrialValidationError(
            f"old value for {parameter} is outside [{rule.minimum}, {rule.maximum}]"
        )
    if not rule.minimum <= trial_value <= rule.maximum:
        raise TrialValidationError(
            f"trial value for {parameter} is outside [{rule.minimum}, {rule.maximum}]"
        )
    delta = trial_value - old_value
    if delta == 0.0:
        raise TrialValidationError("bounded change must be non-zero")
    if abs(delta) > rule.max_delta:
        raise TrialValidationError(
            f"change for {parameter} exceeds maximum delta {rule.max_delta}"
        )
    if rollback_value != old_value:
        raise TrialValidationError(
            "rollback_value must exactly equal change.old_value"
        )

    return ValidatedTrialSpecification(
        proposal_id=proposal_id,
        parameter=parameter,
        hypothesis=hypothesis,
        metric=metric,
        baseline=baseline,
        exposure_seconds=exposure_seconds,
        min_samples=min_samples,
        old_value=old_value,
        trial_value=trial_value,
        change=delta,
        rollback_value=rollback_value,
        parameter_minimum=rule.minimum,
        parameter_maximum=rule.maximum,
        max_change=rule.max_delta,
        consumer=rule.consumer,
    )


def validate_trial(spec: TrialSpecification) -> ValidatedTrialSpecification:
    """Short alias for :func:`validate_trial_spec`."""
    return validate_trial_spec(spec)


def allowed_parameter_names() -> tuple[str, ...]:
    """Return the fixed allowlist in stable order."""
    return tuple(ALLOWED_PARAMETERS)


__all__ = [
    "ALLOWED_PARAMETERS",
    "ExposureWindow",
    "ForbiddenTrialTarget",
    "MAX_EXPOSURE_SAMPLES",
    "MAX_EXPOSURE_SECONDS",
    "MIN_EXPOSURE_SAMPLES",
    "MIN_EXPOSURE_SECONDS",
    "ParameterChange",
    "ParameterRule",
    "TrialSpecification",
    "TrialValidationError",
    "UnknownBehavioralParameter",
    "ValidatedTrialSpecification",
    "allowed_parameter_names",
    "validate_trial",
    "validate_trial_spec",
]
