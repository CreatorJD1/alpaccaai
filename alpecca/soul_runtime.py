"""Pure runtime adapter between compact Soul plans and selective deliberation.

The adapter owns no model client and performs no action.  A caller may inject a
textual deliberator, but only when deterministic compact evidence passes the
selective gate.  Every failure preserves the focus chosen by ``soul.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import json
from types import MappingProxyType
from typing import Any

from alpecca import selective_soul


RUNTIME_SCHEMA = "alpecca.soul-runtime-decision.v1"
REQUEST_SCHEMA = "alpecca.soul-textual-deliberation-request.v1"
MAX_OBSERVATION_CHARS = 2_048


class RuntimeOutcome(str, Enum):
    NOT_ELIGIBLE = "not_eligible"
    CALLBACK_UNAVAILABLE = "callback_unavailable"
    CALLBACK_FAILED = "callback_failed"
    RESPONSE_REJECTED = "response_rejected"
    TEXTUAL_SELECTION = "textual_selection"
    INVALID_PLAN = "invalid_plan"


class PlanError(str, Enum):
    NOT_A_MAPPING = "not_a_mapping"
    NOT_COMPACT = "not_compact"
    INVALID_AGENTS = "invalid_agents"
    INVALID_VECTOR = "invalid_vector"
    INVALID_FOCUS = "invalid_focus"


@dataclass(frozen=True, slots=True)
class RoleScore:
    role: str
    score: float
    active: bool


@dataclass(frozen=True, slots=True)
class TextualDeliberationRequest:
    schema: str
    trigger: selective_soul.DeliberationReason
    deterministic_role: str | None
    roles: tuple[RoleScore, ...]
    response_contract: str = '{"selected_role":"<active role>","reason":"<brief reason>"}'


TextualDeliberator = Callable[[TextualDeliberationRequest], str]


@dataclass(frozen=True, slots=True)
class SoulRuntimeRecord:
    deterministic_role: str | None
    selected_role: str | None
    roles: tuple[RoleScore, ...]
    decision: selective_soul.DeliberationDecision
    escalation_eligible: bool
    callback_invoked: bool
    outcome: RuntimeOutcome
    resolution: selective_soul.DeliberationResolution | None = None
    plan_error: PlanError | None = None

    def observation_metadata(self) -> Mapping[str, Any]:
        """Return fixed, prose-free metadata suitable for an observation log."""

        response_error = (
            self.resolution.error.value
            if self.resolution is not None and self.resolution.error is not None
            else None
        )
        evidence = self.decision.evidence
        metadata = {
            "schema": RUNTIME_SCHEMA,
            "roles": tuple(item.role for item in self.roles),
            "scores": tuple(item.score for item in self.roles),
            "active": tuple(int(item.active) for item in self.roles),
            "deterministic_role": self.deterministic_role,
            "selected_role": self.selected_role,
            "escalation_eligible": self.escalation_eligible,
            "callback_invoked": self.callback_invoked,
            "decision_reason": self.decision.reason.value,
            "outcome": self.outcome.value,
            "response_error": response_error,
            "plan_error": self.plan_error.value if self.plan_error else None,
            "contradiction": evidence.contradiction,
            "affect_role": evidence.affect_role,
            "affect_score": evidence.affect_score,
            "top_margin": evidence.top_margin,
            "advisory_only": True,
        }
        encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        if len(encoded) > MAX_OBSERVATION_CHARS:
            # The fixed seven-role shape should never reach this branch.  Keep a
            # deterministic content-free receipt if its contract later expands.
            metadata = {
                "schema": RUNTIME_SCHEMA,
                "outcome": "metadata_cap_exceeded",
                "advisory_only": True,
            }
        return MappingProxyType(metadata)


def evaluate_compact_plan(
    compact_plan: Mapping[str, Any],
    *,
    textual_deliberator: TextualDeliberator | None = None,
) -> SoulRuntimeRecord:
    """Evaluate one compact Soul plan and optionally call a textual tie-breaker."""

    plan_error, vector, deterministic_role = _bridge_plan(compact_plan)
    decision = selective_soul.decide_deliberation(vector)
    roles = _role_scores(decision)
    if plan_error is not None or decision.reason is selective_soul.DeliberationReason.INVALID_EVIDENCE:
        return SoulRuntimeRecord(
            deterministic_role=deterministic_role,
            selected_role=deterministic_role,
            roles=roles,
            decision=decision,
            escalation_eligible=False,
            callback_invoked=False,
            outcome=RuntimeOutcome.INVALID_PLAN,
            plan_error=plan_error or PlanError.INVALID_VECTOR,
        )

    eligible = decision.warranted
    if not eligible:
        return SoulRuntimeRecord(
            deterministic_role=deterministic_role,
            selected_role=deterministic_role,
            roles=roles,
            decision=decision,
            escalation_eligible=False,
            callback_invoked=False,
            outcome=RuntimeOutcome.NOT_ELIGIBLE,
        )
    if textual_deliberator is None:
        return SoulRuntimeRecord(
            deterministic_role=deterministic_role,
            selected_role=deterministic_role,
            roles=roles,
            decision=decision,
            escalation_eligible=True,
            callback_invoked=False,
            outcome=RuntimeOutcome.CALLBACK_UNAVAILABLE,
        )

    request = TextualDeliberationRequest(
        schema=REQUEST_SCHEMA,
        trigger=decision.reason,
        deterministic_role=deterministic_role,
        roles=roles,
    )
    try:
        response = textual_deliberator(request)
    except Exception:
        return SoulRuntimeRecord(
            deterministic_role=deterministic_role,
            selected_role=deterministic_role,
            roles=roles,
            decision=decision,
            escalation_eligible=True,
            callback_invoked=True,
            outcome=RuntimeOutcome.CALLBACK_FAILED,
        )

    resolution = selective_soul.resolve_textual_deliberation(response, decision)
    if not resolution.ok:
        return SoulRuntimeRecord(
            deterministic_role=deterministic_role,
            selected_role=deterministic_role,
            roles=roles,
            decision=decision,
            escalation_eligible=True,
            callback_invoked=True,
            outcome=RuntimeOutcome.RESPONSE_REJECTED,
            resolution=resolution,
        )
    return SoulRuntimeRecord(
        deterministic_role=deterministic_role,
        selected_role=resolution.selected_role,
        roles=roles,
        decision=decision,
        escalation_eligible=True,
        callback_invoked=True,
        outcome=RuntimeOutcome.TEXTUAL_SELECTION,
        resolution=resolution,
    )


def _bridge_plan(
    compact_plan: Mapping[str, Any],
) -> tuple[PlanError | None, Mapping[str, Any], str | None]:
    if not isinstance(compact_plan, Mapping):
        return PlanError.NOT_A_MAPPING, {}, None
    if compact_plan.get("deliberation_mode") != "compact":
        return PlanError.NOT_COMPACT, {}, _focus_role(compact_plan)

    agents = compact_plan.get("agents")
    if not isinstance(agents, Mapping) or tuple(agents) != selective_soul.ROLE_ORDER:
        return PlanError.INVALID_AGENTS, {}, _focus_role(compact_plan)
    vector = compact_plan.get("perspective_vector")
    if not isinstance(vector, Mapping):
        return PlanError.INVALID_VECTOR, {}, _focus_role(compact_plan)

    deterministic_role = _focus_role(compact_plan)
    active = vector.get("active")
    if deterministic_role is None:
        focus = compact_plan.get("focus")
        if focus is not None:
            return PlanError.INVALID_FOCUS, vector, None
        if (
            isinstance(active, (list, tuple))
            and len(active) == len(selective_soul.ROLE_ORDER)
            and all(
                isinstance(value, int)
                and not isinstance(value, bool)
                and value in (0, 1)
                for value in active
            )
            and any(active)
        ):
            return PlanError.INVALID_FOCUS, vector, None
    elif (
        deterministic_role not in selective_soul.ROLE_ORDER
        or not isinstance(active, (list, tuple))
        or len(active) != len(selective_soul.ROLE_ORDER)
        or active[selective_soul.ROLE_ORDER.index(deterministic_role)] != 1
    ):
        return PlanError.INVALID_FOCUS, vector, deterministic_role
    return None, vector, deterministic_role


def _focus_role(compact_plan: Mapping[str, Any]) -> str | None:
    focus = compact_plan.get("focus")
    if focus is None:
        return None
    if not isinstance(focus, Mapping):
        return None
    role = focus.get("subagent")
    return role if isinstance(role, str) else None


def _role_scores(
    decision: selective_soul.DeliberationDecision,
) -> tuple[RoleScore, ...]:
    scores = dict(decision.evidence.scores)
    active = set(decision.evidence.active_roles)
    if tuple(scores) != selective_soul.ROLE_ORDER:
        return ()
    return tuple(
        RoleScore(role=role, score=scores[role], active=role in active)
        for role in selective_soul.ROLE_ORDER
    )


__all__ = [
    "MAX_OBSERVATION_CHARS",
    "PlanError",
    "REQUEST_SCHEMA",
    "RUNTIME_SCHEMA",
    "RoleScore",
    "RuntimeOutcome",
    "SoulRuntimeRecord",
    "TextualDeliberationRequest",
    "TextualDeliberator",
    "evaluate_compact_plan",
]
