"""Selective, advisory escalation for compact Soul perspective scores.

This module does not call a model and does not replace deterministic Soul
arbitration.  It only decides whether a separately governed textual tie-break is
worth requesting, then validates the small JSON answer if one is supplied.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import json
import math
from numbers import Real
import re
from typing import Any


VECTOR_SCHEMA = "alpecca.soul-perspective-vector.v1"
ROLE_ORDER = (
    "Feeler",
    "Expressor",
    "Carer",
    "Doer",
    "Wanderer",
    "Reflector",
    "Improver",
)
AFFECT_ROLES = ("Feeler", "Expressor")
HIGH_AFFECT_SCORE = 0.80
CLOSE_TOP_MARGIN = 0.05
MAX_RESPONSE_CHARS = 4_096
MAX_REASON_CHARS = 256

_LEADING_THINK_RE = re.compile(
    r"\A\s*<think\s*>.*?</think\s*>", re.IGNORECASE | re.DOTALL
)


class DeliberationReason(str, Enum):
    CONTRADICTION = "contradiction"
    HIGH_AFFECT = "high_affect"
    CLOSE_MARGIN = "close_margin"
    NOT_WARRANTED = "not_warranted"
    INVALID_EVIDENCE = "invalid_evidence"


class EvidenceError(str, Enum):
    NOT_A_MAPPING = "not_a_mapping"
    INVALID_SCHEMA = "invalid_schema"
    INVALID_ORDER = "invalid_order"
    INVALID_SCORES = "invalid_scores"
    INVALID_ACTIVE = "invalid_active"
    INVALID_CONTRADICTION = "invalid_contradiction"
    INVALID_PROVENANCE = "invalid_provenance"


class ResolutionSource(str, Enum):
    LLM = "llm"
    DETERMINISTIC = "deterministic"


class ResponseError(str, Enum):
    NOT_WARRANTED = "not_warranted"
    INPUT_TOO_LARGE = "input_too_large"
    MALFORMED_JSON = "malformed_json"
    EXTRA_FIELDS = "extra_fields"
    INVALID_ROLE = "invalid_role"
    INVALID_REASON = "invalid_reason"


@dataclass(frozen=True, slots=True)
class DeliberationEvidence:
    scores: tuple[tuple[str, float], ...]
    active_roles: tuple[str, ...]
    top_role: str | None
    top_score: float | None
    runner_up_role: str | None
    runner_up_score: float | None
    top_margin: float | None
    affect_role: str | None
    affect_score: float
    contradiction: bool
    high_affect_threshold: float = HIGH_AFFECT_SCORE
    close_margin_threshold: float = CLOSE_TOP_MARGIN
    validation_error: EvidenceError | None = None


@dataclass(frozen=True, slots=True)
class DeliberationDecision:
    warranted: bool
    reason: DeliberationReason
    evidence: DeliberationEvidence


@dataclass(frozen=True, slots=True)
class DeliberationResolution:
    selected_role: str | None
    explanation: str
    source: ResolutionSource
    decision_reason: DeliberationReason
    evidence: DeliberationEvidence
    error: ResponseError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def decide_deliberation(vector: Mapping[str, Any]) -> DeliberationDecision:
    """Decide whether compact deterministic evidence warrants model text.

    Trigger priority is stable: contradiction, high affect, then close margin.
    The input is the existing compact Soul vector, not prose or a model claim.
    """

    validated = _validate_vector(vector)
    if isinstance(validated, EvidenceError):
        return DeliberationDecision(
            warranted=False,
            reason=DeliberationReason.INVALID_EVIDENCE,
            evidence=_empty_evidence(validated),
        )

    scores, active, contradiction = validated
    ranked = sorted(
        ((scores[index], index, ROLE_ORDER[index]) for index in range(len(ROLE_ORDER)) if active[index]),
        key=lambda item: (-item[0], item[1]),
    )
    top = ranked[0] if ranked else None
    runner_up = ranked[1] if len(ranked) > 1 else None
    margin = round(top[0] - runner_up[0], 6) if top and runner_up else None

    affect_ranked = sorted(
        (
            (scores[ROLE_ORDER.index(role)], ROLE_ORDER.index(role), role)
            for role in AFFECT_ROLES
            if active[ROLE_ORDER.index(role)]
        ),
        key=lambda item: (-item[0], item[1]),
    )
    affect_score, _affect_index, affect_role = (
        affect_ranked[0] if affect_ranked else (0.0, -1, None)
    )
    evidence = DeliberationEvidence(
        scores=tuple(zip(ROLE_ORDER, scores)),
        active_roles=tuple(ROLE_ORDER[index] for index, flag in enumerate(active) if flag),
        top_role=top[2] if top else None,
        top_score=top[0] if top else None,
        runner_up_role=runner_up[2] if runner_up else None,
        runner_up_score=runner_up[0] if runner_up else None,
        top_margin=margin,
        affect_role=affect_role,
        affect_score=affect_score,
        contradiction=contradiction,
    )

    if contradiction:
        return DeliberationDecision(True, DeliberationReason.CONTRADICTION, evidence)
    if affect_score >= HIGH_AFFECT_SCORE:
        return DeliberationDecision(True, DeliberationReason.HIGH_AFFECT, evidence)
    if margin is not None and margin <= CLOSE_TOP_MARGIN:
        return DeliberationDecision(True, DeliberationReason.CLOSE_MARGIN, evidence)
    return DeliberationDecision(False, DeliberationReason.NOT_WARRANTED, evidence)


def resolve_textual_deliberation(
    response: str,
    decision: DeliberationDecision,
) -> DeliberationResolution:
    """Validate ``{"selected_role": ..., "reason": ...}`` or fall back.

    A model may only select one of the active deterministic perspectives.  Every
    parse or validation failure returns the pre-existing top role and stable
    metadata; no malformed response can create a role or force escalation.
    """

    fallback_role = decision.evidence.top_role
    if not decision.warranted:
        return _fallback_resolution(
            decision, fallback_role, ResponseError.NOT_WARRANTED
        )
    if not isinstance(response, str):
        return _fallback_resolution(
            decision, fallback_role, ResponseError.MALFORMED_JSON
        )
    if len(response) > MAX_RESPONSE_CHARS:
        return _fallback_resolution(
            decision, fallback_role, ResponseError.INPUT_TOO_LARGE
        )

    text = _strip_think(response)
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (TypeError, ValueError, RecursionError):
        return _fallback_resolution(
            decision, fallback_role, ResponseError.MALFORMED_JSON
        )
    if not isinstance(payload, dict):
        return _fallback_resolution(
            decision, fallback_role, ResponseError.MALFORMED_JSON
        )
    if set(payload) != {"selected_role", "reason"}:
        return _fallback_resolution(
            decision, fallback_role, ResponseError.EXTRA_FIELDS
        )

    selected_role = payload["selected_role"]
    if (
        not isinstance(selected_role, str)
        or selected_role not in decision.evidence.active_roles
    ):
        return _fallback_resolution(
            decision, fallback_role, ResponseError.INVALID_ROLE
        )
    reason = payload["reason"]
    if (
        not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > MAX_REASON_CHARS
        or any(ord(char) < 0x20 for char in reason)
    ):
        return _fallback_resolution(
            decision, fallback_role, ResponseError.INVALID_REASON
        )
    return DeliberationResolution(
        selected_role=selected_role,
        explanation=reason.strip(),
        source=ResolutionSource.LLM,
        decision_reason=decision.reason,
        evidence=decision.evidence,
    )


def _validate_vector(
    vector: Mapping[str, Any],
) -> tuple[tuple[float, ...], tuple[bool, ...], bool] | EvidenceError:
    if not isinstance(vector, Mapping):
        return EvidenceError.NOT_A_MAPPING
    if vector.get("schema") != VECTOR_SCHEMA:
        return EvidenceError.INVALID_SCHEMA
    order = vector.get("order")
    if (
        not isinstance(order, Sequence)
        or isinstance(order, (str, bytes, bytearray))
        or tuple(order) != ROLE_ORDER
    ):
        return EvidenceError.INVALID_ORDER

    raw_scores = vector.get("scores")
    if (
        not isinstance(raw_scores, Sequence)
        or isinstance(raw_scores, (str, bytes, bytearray))
        or len(raw_scores) != len(ROLE_ORDER)
    ):
        return EvidenceError.INVALID_SCORES
    scores: list[float] = []
    for value in raw_scores:
        if isinstance(value, bool) or not isinstance(value, Real):
            return EvidenceError.INVALID_SCORES
        number = float(value)
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            return EvidenceError.INVALID_SCORES
        scores.append(round(number, 6))

    raw_active = vector.get("active")
    if (
        not isinstance(raw_active, Sequence)
        or isinstance(raw_active, (str, bytes, bytearray))
        or len(raw_active) != len(ROLE_ORDER)
        or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value not in (0, 1)
            for value in raw_active
        )
    ):
        return EvidenceError.INVALID_ACTIVE
    active = tuple(value == 1 for value in raw_active)

    contradiction = vector.get("contradiction")
    if not isinstance(contradiction, bool):
        return EvidenceError.INVALID_CONTRADICTION
    model_calls = vector.get("model_calls")
    if (
        vector.get("source") != "deterministic"
        or isinstance(model_calls, bool)
        or model_calls != 0
        or vector.get("independent_transformers") is not False
    ):
        return EvidenceError.INVALID_PROVENANCE
    return tuple(scores), active, contradiction


def _empty_evidence(error: EvidenceError) -> DeliberationEvidence:
    return DeliberationEvidence(
        scores=(),
        active_roles=(),
        top_role=None,
        top_score=None,
        runner_up_role=None,
        runner_up_score=None,
        top_margin=None,
        affect_role=None,
        affect_score=0.0,
        contradiction=False,
        validation_error=error,
    )


def _strip_think(response: str) -> str:
    text = response
    while True:
        match = _LEADING_THINK_RE.match(text)
        if not match:
            return text.strip()
        text = text[match.end():]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _fallback_resolution(
    decision: DeliberationDecision,
    fallback_role: str | None,
    error: ResponseError,
) -> DeliberationResolution:
    return DeliberationResolution(
        selected_role=fallback_role,
        explanation=f"deterministic fallback: {error.value}",
        source=ResolutionSource.DETERMINISTIC,
        decision_reason=decision.reason,
        evidence=decision.evidence,
        error=error,
    )


__all__ = [
    "AFFECT_ROLES",
    "CLOSE_TOP_MARGIN",
    "DeliberationDecision",
    "DeliberationEvidence",
    "DeliberationReason",
    "DeliberationResolution",
    "EvidenceError",
    "HIGH_AFFECT_SCORE",
    "MAX_REASON_CHARS",
    "MAX_RESPONSE_CHARS",
    "ROLE_ORDER",
    "ResolutionSource",
    "ResponseError",
    "VECTOR_SCHEMA",
    "decide_deliberation",
    "resolve_textual_deliberation",
]
