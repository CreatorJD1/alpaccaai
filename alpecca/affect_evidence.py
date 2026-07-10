"""Pure evidence gating for grounded affect updates.

This module does not change emotional state. It validates one bounded cue
observation and decides whether that evidence is current and strong enough for
a later caller to consider. Descriptions report observable strategy/state only;
they never assert subjective experience or consciousness.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Literal

from alpecca.cues import CueKind


DEFAULT_MIN_CONFIDENCE = 0.60
DEFAULT_DECAY_SECONDS = 120.0
DEFAULT_TTL_SECONDS = 300.0
MAX_DECAY_SECONDS = 3600.0
MAX_TTL_SECONDS = 3600.0
MAX_SOURCE_CHARS = 80
MAX_STATE_DESCRIPTION_CHARS = 240

_CUE_KINDS: frozenset[str] = frozenset({
    "correction",
    "confirmation",
    "reference",
    "urgency",
    "distress",
    "question",
    "action_intent",
})
_SOURCE_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_LITERAL_INNER_CLAIM_RE = re.compile(
    r"\b(?:i\s+(?:feel|felt|am\s+feeling)|"
    r"alpecca\s+(?:feels|felt|is\s+feeling)|"
    r"she\s+(?:feels|felt|is\s+feeling)|"
    r"i\s+am\s+(?:conscious|sentient)|"
    r"alpecca\s+is\s+(?:conscious|sentient))\b",
    re.IGNORECASE,
)

AffectEvidenceReason = Literal[
    "eligible",
    "missing_evidence",
    "not_yet_observed",
    "expired",
    "weak_evidence",
]


def _finite_number(value: float, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _confidence(value: float, *, name: str = "confidence") -> float:
    number = _finite_number(value, name=name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


def _bounded_text(value: str, *, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError(f"{name} is required")
    if len(cleaned) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    if any(ord(char) < 32 for char in cleaned):
        raise ValueError(f"{name} contains control characters")
    return cleaned


@dataclass(frozen=True, slots=True)
class AffectEvidenceEnvelope:
    """One immutable, expiring observation that may justify an affect update."""

    source: str
    cue_kind: CueKind
    confidence: float
    timestamp: float
    decay_seconds: float
    expires_at: float
    observable_state: str

    def __post_init__(self) -> None:
        source = _bounded_text(
            self.source, name="source", maximum=MAX_SOURCE_CHARS
        )
        if not _SOURCE_RE.fullmatch(source):
            raise ValueError(
                "source may contain only letters, digits, '.', '_', ':', and '-'"
            )
        if not isinstance(self.cue_kind, str) or self.cue_kind not in _CUE_KINDS:
            raise ValueError("cue_kind is not a supported conversational cue")
        confidence = _confidence(self.confidence)
        timestamp = _finite_number(self.timestamp, name="timestamp")
        decay = _finite_number(self.decay_seconds, name="decay_seconds")
        expires = _finite_number(self.expires_at, name="expires_at")
        state = _bounded_text(
            self.observable_state,
            name="observable_state",
            maximum=MAX_STATE_DESCRIPTION_CHARS,
        )
        if timestamp < 0.0:
            raise ValueError("timestamp cannot be negative")
        if not 0.0 < decay <= MAX_DECAY_SECONDS:
            raise ValueError(
                f"decay_seconds must be greater than 0 and at most {MAX_DECAY_SECONDS:g}"
            )
        lifetime = expires - timestamp
        if not 0.0 < lifetime <= MAX_TTL_SECONDS:
            raise ValueError(
                f"expires_at must be after timestamp and within {MAX_TTL_SECONDS:g} seconds"
            )
        if _LITERAL_INNER_CLAIM_RE.search(state):
            raise ValueError(
                "observable_state must describe operational behavior, not literal feelings"
            )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "decay_seconds", decay)
        object.__setattr__(self, "expires_at", expires)
        object.__setattr__(self, "observable_state", state)

    @classmethod
    def create(
        cls,
        *,
        source: str,
        cue_kind: CueKind,
        confidence: float,
        timestamp: float,
        observable_state: str,
        decay_seconds: float = DEFAULT_DECAY_SECONDS,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> "AffectEvidenceEnvelope":
        """Build an envelope while deriving the expiry from a bounded TTL."""

        observed = _finite_number(timestamp, name="timestamp")
        ttl = _finite_number(ttl_seconds, name="ttl_seconds")
        if not 0.0 < ttl <= MAX_TTL_SECONDS:
            raise ValueError(
                f"ttl_seconds must be greater than 0 and at most {MAX_TTL_SECONDS:g}"
            )
        return cls(
            source=source,
            cue_kind=cue_kind,
            confidence=confidence,
            timestamp=observed,
            decay_seconds=decay_seconds,
            expires_at=observed + ttl,
            observable_state=observable_state,
        )

    def is_expired(self, now: float) -> bool:
        current = _finite_number(now, name="now")
        return current >= self.expires_at

    def effective_confidence(self, now: float) -> float:
        """Return exponentially decayed confidence, or zero outside validity."""

        current = _finite_number(now, name="now")
        if current < self.timestamp or current >= self.expires_at:
            return 0.0
        age = current - self.timestamp
        decayed = self.confidence * math.exp(
            -math.log(2.0) * age / self.decay_seconds
        )
        return max(0.0, min(1.0, decayed))

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "cue_kind": self.cue_kind,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "decay_seconds": self.decay_seconds,
            "expires_at": self.expires_at,
            "observable_state": self.observable_state,
        }


# Short compatibility name for callers that do not need the word "Envelope".
AffectEvidence = AffectEvidenceEnvelope


@dataclass(frozen=True, slots=True)
class AffectUpdateDecision:
    """Explain whether one envelope is sufficient for a later state update."""

    should_update: bool
    reason: AffectEvidenceReason
    assessed_at: float
    threshold: float
    effective_confidence: float
    evidence: AffectEvidenceEnvelope | None = None

    def observable_description(self) -> str:
        """Describe evidence and response posture without subjective claims."""

        if self.evidence is None:
            return "No affect update: no grounded cue evidence was supplied."
        if not self.should_update:
            return (
                f"No affect update: {self.reason}; effective evidence confidence "
                f"{self.effective_confidence:.3f}, threshold {self.threshold:.3f}."
            )
        return (
            f"Observed {self.evidence.cue_kind} cue from {self.evidence.source}; "
            f"effective confidence {self.effective_confidence:.3f}. "
            f"Operational state: {self.evidence.observable_state}."
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "should_update": self.should_update,
            "reason": self.reason,
            "assessed_at": self.assessed_at,
            "threshold": self.threshold,
            "effective_confidence": self.effective_confidence,
            "observable_description": self.observable_description(),
            "evidence": self.evidence.as_dict() if self.evidence else None,
        }


def assess_affect_evidence(
    evidence: AffectEvidenceEnvelope | None,
    *,
    now: float,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> AffectUpdateDecision:
    """Purely gate one evidence envelope by presence, time, and confidence."""

    current = _finite_number(now, name="now")
    if current < 0.0:
        raise ValueError("now cannot be negative")
    threshold = _confidence(min_confidence, name="min_confidence")
    if evidence is not None and not isinstance(evidence, AffectEvidenceEnvelope):
        raise TypeError("evidence must be an AffectEvidenceEnvelope or None")

    reason: AffectEvidenceReason
    effective = 0.0
    if evidence is None:
        reason = "missing_evidence"
    elif current < evidence.timestamp:
        reason = "not_yet_observed"
    elif evidence.is_expired(current):
        reason = "expired"
    else:
        effective = evidence.effective_confidence(current)
        reason = "eligible" if effective >= threshold else "weak_evidence"

    return AffectUpdateDecision(
        should_update=reason == "eligible",
        reason=reason,
        assessed_at=current,
        threshold=threshold,
        effective_confidence=effective,
        evidence=evidence,
    )


def evaluate_affect_evidence(
    evidence: AffectEvidenceEnvelope | None,
    *,
    now: float,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> AffectUpdateDecision:
    """Alias for :func:`assess_affect_evidence`."""

    return assess_affect_evidence(
        evidence, now=now, min_confidence=min_confidence
    )


__all__ = [
    "AffectEvidence",
    "AffectEvidenceEnvelope",
    "AffectEvidenceReason",
    "AffectUpdateDecision",
    "DEFAULT_DECAY_SECONDS",
    "DEFAULT_MIN_CONFIDENCE",
    "DEFAULT_TTL_SECONDS",
    "MAX_DECAY_SECONDS",
    "MAX_SOURCE_CHARS",
    "MAX_STATE_DESCRIPTION_CHARS",
    "MAX_TTL_SECONDS",
    "assess_affect_evidence",
    "evaluate_affect_evidence",
]
