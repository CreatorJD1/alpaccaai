"""Pure Phase 8 policy gate for bounded self-improvement trials.

The gate accepts a normalized validator result or the dictionary shape returned
by ``trial_ledger.get_trial``.  It performs no I/O and changes no parameter.  A
failure at any boundary returns an evidence-backed denial instead of raising or
trying to repair untrusted input.
"""
from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from alpecca.experiment_trials import (
    ALLOWED_PARAMETERS,
    ExposureWindow,
    ParameterChange,
    TrialSpecification,
    ValidatedTrialSpecification,
    validate_trial_spec,
)


DecisionReason = Literal[
    "allowed",
    "unvalidated_spec",
    "forbidden_target",
    "parameter_not_allowed",
    "invalid_metric_plan",
    "rollback_mismatch",
    "approval_required",
    "scope_mismatch",
    "conflicting_trial",
]

_ACTIVE_TRIAL_STATES = frozenset({"approved", "running"})
_VALIDATED_FIELDS = tuple(
    field.name for field in dataclasses.fields(ValidatedTrialSpecification)
)
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
})


@dataclass(frozen=True, slots=True)
class PolicyEvidence:
    """One auditable policy check."""

    check: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class SelfImprovementDecision:
    """Final allow/deny result with ordered supporting evidence."""

    decision: Literal["allow", "deny"]
    reason: DecisionReason
    evidence: tuple[PolicyEvidence, ...]

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


def _evidence(check: str, passed: bool, detail: str) -> PolicyEvidence:
    return PolicyEvidence(check=check, passed=passed, detail=detail)


def _deny(reason: DecisionReason, evidence: list[PolicyEvidence]) -> SelfImprovementDecision:
    return SelfImprovementDecision("deny", reason, tuple(evidence))


def _scope(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip()
    if not clean or len(clean) > 160 or any(ord(char) < 32 for char in clean):
        return None
    return clean


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _spec_and_ledger(
    candidate: object,
) -> tuple[dict[str, Any] | None, Mapping[str, Any] | None, str | None]:
    if isinstance(candidate, ValidatedTrialSpecification):
        return dataclasses.asdict(candidate), None, None
    if isinstance(candidate, TrialSpecification):
        return None, None, "raw TrialSpecification has not crossed the validator boundary"
    record = _mapping(candidate)
    if record is None:
        return None, None, "candidate is neither a validated specification nor a ledger record"
    if "spec" in record:
        spec = _mapping(record.get("spec"))
        if spec is None:
            return None, record, "ledger record has no object-shaped validated spec"
        return dict(spec), record, None
    return dict(record), None, None


def _forbidden_parameter(parameter: object) -> str | None:
    if not isinstance(parameter, str):
        return None
    words = set(re.findall(r"[a-z0-9]+", parameter.lower()))
    forbidden = sorted(words & _FORBIDDEN_TARGET_WORDS)
    return forbidden[0] if forbidden else None


def _rollback_exact(spec: Mapping[str, Any]) -> bool:
    old_value = _finite(spec.get("old_value"))
    rollback_value = _finite(spec.get("rollback_value"))
    return (
        old_value is not None
        and rollback_value is not None
        and rollback_value == old_value
    )


def _positive_metric_plan(spec: Mapping[str, Any]) -> bool:
    baseline = _finite(spec.get("baseline"))
    exposure = _finite(spec.get("exposure_seconds"))
    samples = spec.get("min_samples")
    return (
        baseline is not None
        and baseline > 0.0
        and isinstance(spec.get("metric"), str)
        and bool(str(spec.get("metric")).strip())
        and isinstance(spec.get("hypothesis"), str)
        and bool(str(spec.get("hypothesis")).strip())
        and exposure is not None
        and exposure > 0.0
        and isinstance(samples, int)
        and not isinstance(samples, bool)
        and samples > 0
    )


def _revalidate(spec: Mapping[str, Any]) -> ValidatedTrialSpecification | None:
    if any(name not in spec for name in _VALIDATED_FIELDS):
        return None
    try:
        normalized = ValidatedTrialSpecification(
            **{name: spec[name] for name in _VALIDATED_FIELDS}
        )
        expected = validate_trial_spec(TrialSpecification(
            proposal_id=normalized.proposal_id,
            parameter=normalized.parameter,
            hypothesis=normalized.hypothesis,
            metric=normalized.metric,
            baseline=normalized.baseline,
            exposure=ExposureWindow(
                normalized.exposure_seconds, normalized.min_samples
            ),
            change=ParameterChange(normalized.old_value, normalized.trial_value),
            rollback_value=normalized.rollback_value,
        ))
    except (TypeError, ValueError, KeyError):
        return None
    return normalized if normalized == expected else None


def _approval_check(
    proof_value: object,
    *,
    scope: str,
    proposal_id: int,
) -> tuple[bool, str]:
    proof = _mapping(proof_value)
    if proof is None:
        return False, "no proposal approval proof is attached"
    proof_scope = _scope(proof.get("scope"))
    if proof_scope != scope:
        return False, "approval proof is not bound to the requested scope"
    proof_proposal = proof.get("proposal_id")
    if (
        isinstance(proof_proposal, bool)
        or not isinstance(proof_proposal, int)
        or proof_proposal != proposal_id
    ):
        return False, "approval proof is not bound to the trial proposal"
    if proof.get("decision") != "approved":
        return False, "proposal decision is not approved"
    if not isinstance(proof.get("proof_id"), str) or not str(proof["proof_id"]).strip():
        return False, "approval proof has no proof_id"
    if not isinstance(proof.get("authority"), str) or not str(proof["authority"]).strip():
        return False, "approval proof has no authority"
    approved_at = _finite(proof.get("approved_at"))
    if approved_at is None or approved_at < 0.0:
        return False, "approval proof has no valid approval timestamp"
    return True, "approval proof matches scope and proposal"


def _trial_identity(record: Mapping[str, Any]) -> tuple[object, object]:
    return record.get("id"), record.get("proposal_id")


def _find_conflict(
    active_trials: object,
    *,
    scope: str,
    candidate_record: Mapping[str, Any] | None,
    proposal_id: int,
) -> str | None:
    if isinstance(active_trials, (str, bytes)) or not isinstance(active_trials, Sequence):
        return "active trial inventory is not a sequence"
    candidate_id = candidate_record.get("id") if candidate_record is not None else None
    for item in active_trials:
        record = _mapping(item)
        if record is None:
            return "active trial inventory contains an unstructured record"
        state = str(record.get("state") or "").strip().lower()
        if state not in _ACTIVE_TRIAL_STATES:
            continue
        item_scope = _scope(record.get("scope"))
        if item_scope != scope:
            continue
        item_id, item_proposal = _trial_identity(record)
        if candidate_id is not None and item_id == candidate_id:
            continue
        if item_proposal == proposal_id:
            continue
        return (
            f"scope already has active trial "
            f"{item_id if item_id is not None else '<unknown>'}"
        )
    return None


def evaluate_self_improvement_trial(
    candidate: object,
    *,
    scope: str,
    approval_proof: Mapping[str, Any] | None = None,
    active_trials: Sequence[Mapping[str, Any]] = (),
) -> SelfImprovementDecision:
    """Return a pure, evidence-backed policy decision for one proposed trial."""
    evidence: list[PolicyEvidence] = []
    clean_scope = _scope(scope)
    if clean_scope is None:
        evidence.append(_evidence("scoped_approval", False, "requested scope is invalid"))
        return _deny("scope_mismatch", evidence)

    spec, ledger, shape_error = _spec_and_ledger(candidate)
    if spec is None:
        evidence.append(_evidence("validated_spec", False, shape_error or "missing spec"))
        return _deny("unvalidated_spec", evidence)

    parameter = spec.get("parameter")
    forbidden_word = _forbidden_parameter(parameter)
    if forbidden_word is not None:
        evidence.append(_evidence(
            "target_boundary",
            False,
            f"parameter targets forbidden {forbidden_word} capability",
        ))
        return _deny("forbidden_target", evidence)
    evidence.append(_evidence("target_boundary", True, "target is behavioral only"))

    if not isinstance(parameter, str) or parameter not in ALLOWED_PARAMETERS:
        evidence.append(_evidence(
            "allowed_parameter", False, "parameter has no allowlisted consumed behavior"
        ))
        return _deny("parameter_not_allowed", evidence)
    evidence.append(_evidence(
        "allowed_parameter",
        True,
        f"{parameter} is consumed by {ALLOWED_PARAMETERS[parameter].consumer}",
    ))

    missing_fields = [name for name in _VALIDATED_FIELDS if name not in spec]
    if missing_fields:
        evidence.append(_evidence(
            "validated_spec",
            False,
            f"normalized spec is missing {missing_fields[0]}",
        ))
        return _deny("unvalidated_spec", evidence)

    metric_ok = _positive_metric_plan(spec)
    evidence.append(_evidence(
        "metric_plan",
        metric_ok,
        "positive baseline, named metric, hypothesis, exposure, and sample plan"
        if metric_ok else
        "metric plan needs a positive baseline, metric, hypothesis, exposure, and samples",
    ))
    if not metric_ok:
        return _deny("invalid_metric_plan", evidence)

    rollback_ok = _rollback_exact(spec)
    evidence.append(_evidence(
        "exact_rollback",
        rollback_ok,
        "rollback exactly matches the old consumed value"
        if rollback_ok else "rollback does not exactly match the old consumed value",
    ))
    if not rollback_ok:
        return _deny("rollback_mismatch", evidence)

    normalized = _revalidate(spec)
    if normalized is None:
        evidence.append(_evidence(
            "validated_spec", False, "spec does not replay through the Phase 8 validator"
        ))
        return _deny("unvalidated_spec", evidence)
    evidence.append(_evidence(
        "validated_spec", True, "spec exactly matches validator-normalized policy"
    ))

    embedded_proof: object = None
    if ledger is not None:
        ledger_scope = _scope(ledger.get("scope"))
        if ledger_scope != clean_scope:
            evidence.append(_evidence(
                "scoped_approval", False, "ledger record belongs to another scope"
            ))
            return _deny("scope_mismatch", evidence)
        if ledger.get("proposal_id") != normalized.proposal_id:
            evidence.append(_evidence(
                "scoped_approval", False, "ledger proposal does not match the spec"
            ))
            return _deny("approval_required", evidence)
        if str(ledger.get("state") or "").lower() != "approved":
            evidence.append(_evidence(
                "scoped_approval", False, "ledger trial is not in approved state"
            ))
            return _deny("approval_required", evidence)
        embedded_proof = ledger.get("approval_proof")

    if embedded_proof is not None and approval_proof is not None:
        if dict(_mapping(embedded_proof) or {}) != dict(approval_proof):
            evidence.append(_evidence(
                "scoped_approval", False, "embedded and supplied approval proofs conflict"
            ))
            return _deny("approval_required", evidence)
    proof = embedded_proof if embedded_proof is not None else approval_proof
    approval_ok, approval_detail = _approval_check(
        proof, scope=clean_scope, proposal_id=normalized.proposal_id
    )
    evidence.append(_evidence("scoped_approval", approval_ok, approval_detail))
    if not approval_ok:
        reason: DecisionReason = (
            "scope_mismatch" if "scope" in approval_detail else "approval_required"
        )
        return _deny(reason, evidence)

    conflict = _find_conflict(
        active_trials,
        scope=clean_scope,
        candidate_record=ledger,
        proposal_id=normalized.proposal_id,
    )
    evidence.append(_evidence(
        "active_conflict",
        conflict is None,
        "no other approved or running trial exists in scope"
        if conflict is None else conflict,
    ))
    if conflict is not None:
        return _deny("conflicting_trial", evidence)

    return SelfImprovementDecision("allow", "allowed", tuple(evidence))


def evaluate_trial(
    candidate: object,
    *,
    scope: str,
    approval_proof: Mapping[str, Any] | None = None,
    active_trials: Sequence[Mapping[str, Any]] = (),
) -> SelfImprovementDecision:
    """Short alias for :func:`evaluate_self_improvement_trial`."""
    return evaluate_self_improvement_trial(
        candidate,
        scope=scope,
        approval_proof=approval_proof,
        active_trials=active_trials,
    )


__all__ = [
    "DecisionReason",
    "PolicyEvidence",
    "SelfImprovementDecision",
    "evaluate_self_improvement_trial",
    "evaluate_trial",
]
