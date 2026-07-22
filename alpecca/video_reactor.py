"""Pure, source-neutral policy for reacting to derived video events.

The policy has no clock, counters, model client, or mutable state.  It consumes
bounded event metadata, conversational context, and the deterministic compact
Soul vector.  Meaningful events are acted on, retained, deferred, or compacted
with an explicit receipt; they are never silently discarded.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import json
import math
import re
from types import MappingProxyType
from typing import Any

from alpecca import selective_soul


POLICY_SCHEMA = "alpecca.video-reaction-policy.v1"
MAX_ID_CHARS = 256
MAX_BACKPRESSURE_REASON_CHARS = 160
MAX_OBSERVATION_CHARS = 2_048
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]*\Z")


class VideoReactionError(ValueError):
    """A bounded policy input is invalid."""


class ReactionAction(str, Enum):
    REACT = "react"
    SPEAK = "speak"
    QUESTION = "question"
    SILENT = "silent"


class EventDisposition(str, Enum):
    OBSERVED = "observed"
    RETAINED = "retained"
    DEFERRED = "deferred"
    COMPACTED = "compacted"
    IGNORED = "ignored"


class Novelty(str, Enum):
    UNCHANGED = "unchanged"
    FAMILIAR = "familiar"
    NOVEL = "novel"
    SURPRISING = "surprising"


class ConversationMode(str, Enum):
    QUIET = "quiet"
    WATCHING = "watching"
    ENGAGED = "engaged"
    DIRECTED = "directed"


class DecisionReason(str, Enum):
    NOT_MEANINGFUL = "not_meaningful"
    EXACT_DUPLICATE_RANGE = "exact_duplicate_unchanged_range"
    USER_INTERRUPTION = "user_interruption"
    TECHNICAL_BACKPRESSURE = "technical_backpressure"
    INVALID_SOUL_EVIDENCE = "invalid_soul_evidence"
    QUIET_CONTEXT = "quiet_context_retained"
    FAMILIAR_CONTEXT = "familiar_event_retained"
    CURIOSITY_QUESTION = "curiosity_question"
    DIRECTED_RESPONSE = "directed_response"
    EXPRESSIVE_RESPONSE = "expressive_response"
    MEANINGFUL_REACTION = "meaningful_reaction"


@dataclass(frozen=True, slots=True)
class EventProvenance:
    event_id: str
    source_id: str
    surface: str
    adapter_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _safe_id(self.event_id, "event_id"))
        object.__setattr__(self, "source_id", _safe_id(self.source_id, "source_id"))
        object.__setattr__(self, "surface", _safe_id(self.surface, "surface"))
        if self.adapter_id is not None:
            object.__setattr__(
                self, "adapter_id", _safe_id(self.adapter_id, "adapter_id")
            )


@dataclass(frozen=True, slots=True)
class MeaningfulEvent:
    provenance: EventProvenance
    start_seconds: float
    end_seconds: float
    fingerprint: str
    meaningful: bool
    novelty: Novelty

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, EventProvenance):
            raise VideoReactionError("provenance must be EventProvenance")
        start = _finite_time(self.start_seconds, "start_seconds")
        end = _finite_time(self.end_seconds, "end_seconds")
        if end < start:
            raise VideoReactionError("event end precedes its start")
        object.__setattr__(self, "start_seconds", start)
        object.__setattr__(self, "end_seconds", end)
        object.__setattr__(self, "fingerprint", _safe_id(self.fingerprint, "fingerprint"))
        if not isinstance(self.meaningful, bool):
            raise VideoReactionError("meaningful must be boolean")
        object.__setattr__(self, "novelty", _enum(Novelty, self.novelty, "novelty"))


@dataclass(frozen=True, slots=True)
class PriorEventRange:
    event_id: str
    source_id: str
    start_seconds: float
    end_seconds: float
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _safe_id(self.event_id, "event_id"))
        object.__setattr__(self, "source_id", _safe_id(self.source_id, "source_id"))
        start = _finite_time(self.start_seconds, "start_seconds")
        end = _finite_time(self.end_seconds, "end_seconds")
        if end < start:
            raise VideoReactionError("prior event end precedes its start")
        object.__setattr__(self, "start_seconds", start)
        object.__setattr__(self, "end_seconds", end)
        object.__setattr__(self, "fingerprint", _safe_id(self.fingerprint, "fingerprint"))


@dataclass(frozen=True, slots=True)
class ConversationContext:
    mode: ConversationMode = ConversationMode.WATCHING
    user_interrupted: bool = False
    question_pending: bool = False
    technical_backpressure: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", _enum(ConversationMode, self.mode, "mode"))
        if not isinstance(self.user_interrupted, bool):
            raise VideoReactionError("user_interrupted must be boolean")
        if not isinstance(self.question_pending, bool):
            raise VideoReactionError("question_pending must be boolean")
        if self.technical_backpressure is not None:
            if not isinstance(self.technical_backpressure, str):
                raise VideoReactionError("technical_backpressure must be text")
            reason = " ".join(self.technical_backpressure.split())
            if not reason or len(reason) > MAX_BACKPRESSURE_REASON_CHARS:
                raise VideoReactionError("technical_backpressure must name a bounded reason")
            object.__setattr__(self, "technical_backpressure", reason)


@dataclass(frozen=True, slots=True)
class PerspectiveScore:
    role: str
    score: float
    active: bool


@dataclass(frozen=True, slots=True)
class ReactionEvidence:
    provenance: EventProvenance
    novelty: Novelty
    conversation_mode: ConversationMode
    perspectives: tuple[PerspectiveScore, ...]
    leading_role: str | None
    soul_fallback: bool
    backpressure_reason: str | None


@dataclass(frozen=True, slots=True)
class ReactionDecision:
    action: ReactionAction
    disposition: EventDisposition
    reason: DecisionReason
    meaningful_event_retained: bool
    evidence: ReactionEvidence
    compacted_into_event_id: str | None = None

    def observation_metadata(self) -> Mapping[str, Any]:
        """Return fixed metadata without frame descriptions or transcript text."""

        metadata = {
            "schema": POLICY_SCHEMA,
            "event_id": self.evidence.provenance.event_id,
            "source_id": self.evidence.provenance.source_id,
            "surface": self.evidence.provenance.surface,
            "adapter_id": self.evidence.provenance.adapter_id,
            "action": self.action.value,
            "disposition": self.disposition.value,
            "reason": self.reason.value,
            "meaningful_event_retained": self.meaningful_event_retained,
            "compacted_into_event_id": self.compacted_into_event_id,
            "novelty": self.evidence.novelty.value,
            "conversation_mode": self.evidence.conversation_mode.value,
            "roles": tuple(item.role for item in self.evidence.perspectives),
            "scores": tuple(item.score for item in self.evidence.perspectives),
            "active": tuple(int(item.active) for item in self.evidence.perspectives),
            "leading_role": self.evidence.leading_role,
            "soul_fallback": self.evidence.soul_fallback,
            "backpressure_reason": self.evidence.backpressure_reason,
            "model_calls": 0,
        }
        encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
        if len(encoded) > MAX_OBSERVATION_CHARS:
            metadata = {
                "schema": POLICY_SCHEMA,
                "event_id": self.evidence.provenance.event_id,
                "reason": "metadata_cap_exceeded",
                "meaningful_event_retained": self.meaningful_event_retained,
                "model_calls": 0,
            }
        return MappingProxyType(metadata)


_QUESTION_ROLES = frozenset(("Wanderer", "Reflector", "Improver"))
_SPEAK_ROLES = frozenset(("Expressor", "Carer", "Doer"))
_INQUIRY_NOVELTY = frozenset((Novelty.NOVEL, Novelty.SURPRISING))


def decide_video_reaction(
    event: MeaningfulEvent,
    context: ConversationContext,
    soul_vector: Mapping[str, Any],
    *,
    prior_event: PriorEventRange | None = None,
) -> ReactionDecision:
    """Choose a reaction without clocks, quotas, mutable state, or model calls."""

    if not isinstance(event, MeaningfulEvent):
        raise VideoReactionError("event must be MeaningfulEvent")
    if not isinstance(context, ConversationContext):
        raise VideoReactionError("context must be ConversationContext")
    if prior_event is not None and not isinstance(prior_event, PriorEventRange):
        raise VideoReactionError("prior_event must be PriorEventRange")

    perspectives, leading_role, soul_fallback = _perspectives(soul_vector)
    evidence = ReactionEvidence(
        provenance=event.provenance,
        novelty=event.novelty,
        conversation_mode=context.mode,
        perspectives=perspectives,
        leading_role=leading_role,
        soul_fallback=soul_fallback,
        backpressure_reason=context.technical_backpressure,
    )

    if not event.meaningful:
        return ReactionDecision(
            ReactionAction.SILENT,
            EventDisposition.IGNORED,
            DecisionReason.NOT_MEANINGFUL,
            False,
            evidence,
        )
    if _is_exact_unchanged_duplicate(event, prior_event):
        return ReactionDecision(
            ReactionAction.SILENT,
            EventDisposition.COMPACTED,
            DecisionReason.EXACT_DUPLICATE_RANGE,
            True,
            evidence,
            compacted_into_event_id=prior_event.event_id if prior_event else None,
        )
    if context.user_interrupted:
        return ReactionDecision(
            ReactionAction.SILENT,
            EventDisposition.DEFERRED,
            DecisionReason.USER_INTERRUPTION,
            True,
            evidence,
        )
    if context.technical_backpressure is not None:
        return ReactionDecision(
            ReactionAction.SILENT,
            EventDisposition.DEFERRED,
            DecisionReason.TECHNICAL_BACKPRESSURE,
            True,
            evidence,
        )
    if soul_fallback:
        return ReactionDecision(
            ReactionAction.SILENT,
            EventDisposition.DEFERRED,
            DecisionReason.INVALID_SOUL_EVIDENCE,
            True,
            evidence,
        )
    if context.mode is ConversationMode.QUIET:
        return ReactionDecision(
            ReactionAction.SILENT,
            EventDisposition.RETAINED,
            DecisionReason.QUIET_CONTEXT,
            True,
            evidence,
        )

    may_question = (
        not context.question_pending
        and event.novelty in _INQUIRY_NOVELTY
        and leading_role in _QUESTION_ROLES
    )
    if may_question:
        return ReactionDecision(
            ReactionAction.QUESTION,
            EventDisposition.OBSERVED,
            DecisionReason.CURIOSITY_QUESTION,
            True,
            evidence,
        )
    if context.mode is ConversationMode.DIRECTED:
        return ReactionDecision(
            ReactionAction.SPEAK,
            EventDisposition.OBSERVED,
            DecisionReason.DIRECTED_RESPONSE,
            True,
            evidence,
        )
    if (
        context.mode is ConversationMode.ENGAGED
        and leading_role in _SPEAK_ROLES
    ) or (
        event.novelty is Novelty.SURPRISING
        and leading_role in _SPEAK_ROLES
    ):
        return ReactionDecision(
            ReactionAction.SPEAK,
            EventDisposition.OBSERVED,
            DecisionReason.EXPRESSIVE_RESPONSE,
            True,
            evidence,
        )
    if event.novelty in _INQUIRY_NOVELTY:
        return ReactionDecision(
            ReactionAction.REACT,
            EventDisposition.OBSERVED,
            DecisionReason.MEANINGFUL_REACTION,
            True,
            evidence,
        )
    return ReactionDecision(
        ReactionAction.SILENT,
        EventDisposition.RETAINED,
        DecisionReason.FAMILIAR_CONTEXT,
        True,
        evidence,
    )


def _perspectives(
    soul_vector: Mapping[str, Any],
) -> tuple[tuple[PerspectiveScore, ...], str | None, bool]:
    decision = selective_soul.decide_deliberation(soul_vector)
    evidence = decision.evidence
    if evidence.validation_error is not None:
        return (), None, True
    score_map = dict(evidence.scores)
    active = set(evidence.active_roles)
    perspectives = tuple(
        PerspectiveScore(role, score_map[role], role in active)
        for role in selective_soul.ROLE_ORDER
    )
    ranked = sorted(
        (item for item in perspectives if item.active),
        key=lambda item: (-item.score, selective_soul.ROLE_ORDER.index(item.role)),
    )
    if not ranked:
        return perspectives, None, True
    return perspectives, ranked[0].role, False


def _is_exact_unchanged_duplicate(
    event: MeaningfulEvent,
    prior: PriorEventRange | None,
) -> bool:
    return bool(
        prior is not None
        and event.novelty is Novelty.UNCHANGED
        and event.provenance.source_id == prior.source_id
        and event.start_seconds == prior.start_seconds
        and event.end_seconds == prior.end_seconds
        and event.fingerprint == prior.fingerprint
    )


def _safe_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_ID_CHARS:
        raise VideoReactionError(f"{name} must be bounded text")
    if _SAFE_ID_RE.fullmatch(value) is None or "://" in value:
        raise VideoReactionError(f"{name} must be an opaque identifier")
    return value


def _finite_time(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise VideoReactionError(f"{name} must be a finite non-negative number")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise VideoReactionError(f"{name} must be a finite non-negative number") from None
    if not math.isfinite(number) or number < 0:
        raise VideoReactionError(f"{name} must be a finite non-negative number")
    return number


def _enum(enum_type: type[Enum], value: object, name: str) -> Any:
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        raise VideoReactionError(f"invalid {name}: {value!r}") from None


__all__ = [
    "ConversationContext",
    "ConversationMode",
    "DecisionReason",
    "EventDisposition",
    "EventProvenance",
    "MAX_OBSERVATION_CHARS",
    "MeaningfulEvent",
    "Novelty",
    "POLICY_SCHEMA",
    "PerspectiveScore",
    "PriorEventRange",
    "ReactionAction",
    "ReactionDecision",
    "ReactionEvidence",
    "VideoReactionError",
    "decide_video_reaction",
]
