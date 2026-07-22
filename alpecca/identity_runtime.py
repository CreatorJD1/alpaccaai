"""Pure runtime adapter for identity evidence and familiarity signals.

The adapter is deliberately stateless and performs no I/O. It accepts only
the concrete verified authentication and familiarity evidence types from
``identity_evidence``. Familiarity may select Creator-oriented personalization,
but it can never authenticate a caller or authorize Creator actions.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable

from alpecca.identity_evidence import (
    AuthorizationReason,
    AuthenticatedAccountEvidence,
    AuthenticatedDeviceEvidence,
    AuthenticatedSessionEvidence,
    Contradiction,
    DEFAULT_AUTHORIZATION_CONFIDENCE,
    EvidenceType,
    FaceFamiliarityEvidence,
    IdentityClaim,
    IdentityEvidence,
    TextFamiliarityEvidence,
    VoiceFamiliarityEvidence,
    authorize_creator,
    fuse_identity_evidence,
)


DEFAULT_PERSONALIZATION_CONFIDENCE = 0.60
MAX_AUTHENTICATION_EVIDENCE = 32
MAX_FAMILIARITY_EVIDENCE = 32
MAX_RUNTIME_EVIDENCE = MAX_AUTHENTICATION_EVIDENCE + MAX_FAMILIARITY_EVIDENCE

_AUTHENTICATION_TYPES = (
    AuthenticatedAccountEvidence,
    AuthenticatedDeviceEvidence,
    AuthenticatedSessionEvidence,
)
_FAMILIARITY_TYPES = (
    FaceFamiliarityEvidence,
    VoiceFamiliarityEvidence,
    TextFamiliarityEvidence,
)


class RuntimeIdentityStatus(str, Enum):
    """Bounded top-level runtime states for user-facing status surfaces."""

    AUTHENTICATED_CREATOR = "authenticated_creator"
    AUTHENTICATION_DENIED = "authentication_denied"
    CONTRADICTORY = "contradictory"
    FAMILIAR_CREATOR = "familiar_creator"
    UNRECOGNIZED = "unrecognized"
    NO_EVIDENCE = "no_evidence"


class PersonalizationReason(str, Enum):
    """Stable reasons for the separate personalization decision."""

    AUTHENTICATED_CREATOR = "authenticated_creator"
    FAMILIARITY_THRESHOLD_MET = "familiarity_threshold_met"
    NO_CREATOR_FAMILIARITY = "no_creator_familiarity"
    INSUFFICIENT_FAMILIARITY = "insufficient_familiarity"
    FAMILIARITY_CONTRADICTION = "familiarity_contradiction"
    AUTHENTICATION_CONTRADICTION = "authentication_contradiction"
    AUTHENTICATED_NOT_CREATOR = "authenticated_not_creator"


def _confidence(value: float, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")
    return number


def _materialize_channel(
    values: Iterable[IdentityEvidence],
    *,
    name: str,
    accepted_types: tuple[type[IdentityEvidence], ...],
    maximum: int,
) -> tuple[IdentityEvidence, ...]:
    try:
        items = tuple(values)
    except TypeError as exc:
        raise TypeError(f"{name} must be an iterable of identity evidence") from exc
    if len(items) > maximum:
        raise ValueError(f"{name} exceeds the {maximum}-record runtime limit")
    for item in items:
        if type(item) not in accepted_types:
            expected = "authentication" if name == "authentication_evidence" else "familiarity"
            raise TypeError(f"{name} contains non-{expected} evidence")
    return items


@dataclass(frozen=True, slots=True)
class RuntimeProvenance:
    """Bounded, secret-free provenance for one active runtime signal."""

    evidence_id: str
    evidence_type: EvidenceType
    channel: str
    claim: IdentityClaim
    confidence: float
    source: str
    mechanism: str
    reference: str
    expires_at: float

    @classmethod
    def from_evidence(cls, evidence: IdentityEvidence) -> "RuntimeProvenance":
        return cls(
            evidence_id=evidence.evidence_id,
            evidence_type=evidence.evidence_type,
            channel=(
                "verified_authentication"
                if evidence.authorization_capable
                else "familiarity"
            ),
            claim=evidence.claim,
            confidence=evidence.confidence,
            source=evidence.provenance.source,
            mechanism=evidence.provenance.mechanism,
            reference=evidence.provenance.reference,
            expires_at=evidence.expires_at,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type.value,
            "channel": self.channel,
            "claim": self.claim.value,
            "confidence": self.confidence,
            "source": self.source,
            "mechanism": self.mechanism,
            "reference": self.reference,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class IdentityRuntimeResult:
    """Explainable runtime identity status with independent policy decisions."""

    status: RuntimeIdentityStatus
    assessed_at: float
    creator_actions_authorized: bool
    creator_authenticated: bool
    personalization_allowed: bool
    personalization_target: str | None
    authorization_reason: AuthorizationReason
    personalization_reason: PersonalizationReason
    authentication_confidence: float
    familiarity_confidence: float
    identity_confidence: float
    authentication_threshold: float
    personalization_threshold: float
    authorization_expires_at: float | None
    personalization_expires_at: float | None
    contradictions: tuple[Contradiction, ...]
    provenance: tuple[RuntimeProvenance, ...]
    expired_evidence_ids: tuple[str, ...]
    future_evidence_ids: tuple[str, ...]
    duplicate_evidence_ids: tuple[str, ...]
    explanations: tuple[str, ...]
    submitted_evidence_count: int

    @property
    def authorized(self) -> bool:
        """Compatibility alias; always mirrors Creator-action authorization."""

        return self.creator_actions_authorized

    @property
    def active_evidence_count(self) -> int:
        return len(self.provenance)

    @property
    def status_expires_at(self) -> float | None:
        expiries = (
            expiry
            for expiry in (
                self.authorization_expires_at,
                self.personalization_expires_at,
            )
            if expiry is not None
        )
        return min(expiries, default=None)

    def may_execute_creator_action(self) -> bool:
        """Explicit action gate; familiarity is never consulted here."""

        return self.creator_actions_authorized

    def may_personalize_for_creator(self) -> bool:
        return self.personalization_allowed and self.personalization_target == "creator"

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "assessed_at": self.assessed_at,
            "creator_actions_authorized": self.creator_actions_authorized,
            "creator_authenticated": self.creator_authenticated,
            "personalization_allowed": self.personalization_allowed,
            "personalization_target": self.personalization_target,
            "authorization_reason": self.authorization_reason.value,
            "personalization_reason": self.personalization_reason.value,
            "authentication_confidence": self.authentication_confidence,
            "familiarity_confidence": self.familiarity_confidence,
            "identity_confidence": self.identity_confidence,
            "authentication_threshold": self.authentication_threshold,
            "personalization_threshold": self.personalization_threshold,
            "authorization_expires_at": self.authorization_expires_at,
            "personalization_expires_at": self.personalization_expires_at,
            "status_expires_at": self.status_expires_at,
            "contradictions": [item.value for item in self.contradictions],
            "provenance": [item.as_dict() for item in self.provenance],
            "expired_evidence_ids": list(self.expired_evidence_ids),
            "future_evidence_ids": list(self.future_evidence_ids),
            "duplicate_evidence_ids": list(self.duplicate_evidence_ids),
            "explanations": list(self.explanations),
            "submitted_evidence_count": self.submitted_evidence_count,
            "active_evidence_count": self.active_evidence_count,
        }


def _personalization_decision(
    *,
    authorization_allowed: bool,
    authorization_reason: AuthorizationReason,
    familiarity_confidence: float,
    familiarity_not_creator_confidence: float,
    contradictions: tuple[Contradiction, ...],
    threshold: float,
) -> tuple[bool, PersonalizationReason]:
    if authorization_allowed:
        return True, PersonalizationReason.AUTHENTICATED_CREATOR
    if authorization_reason in {
        AuthorizationReason.AUTHENTICATION_CONTRADICTION,
        AuthorizationReason.AUTHENTICATION_INTEGRITY_CONFLICT,
    }:
        return False, PersonalizationReason.AUTHENTICATION_CONTRADICTION
    if authorization_reason is AuthorizationReason.AUTHENTICATED_NOT_CREATOR:
        return False, PersonalizationReason.AUTHENTICATED_NOT_CREATOR
    if (
        Contradiction.FAMILIARITY_CLAIM_CONFLICT in contradictions
        or Contradiction.DUPLICATE_EVIDENCE_ID in contradictions
    ):
        return False, PersonalizationReason.FAMILIARITY_CONTRADICTION
    if familiarity_not_creator_confidence > 0.0:
        return False, PersonalizationReason.FAMILIARITY_CONTRADICTION
    if familiarity_confidence <= 0.0:
        return False, PersonalizationReason.NO_CREATOR_FAMILIARITY
    if familiarity_confidence < threshold:
        return False, PersonalizationReason.INSUFFICIENT_FAMILIARITY
    return True, PersonalizationReason.FAMILIARITY_THRESHOLD_MET


def _runtime_status(
    *,
    authorization_allowed: bool,
    authorization_reason: AuthorizationReason,
    personalization_allowed: bool,
    submitted_count: int,
) -> RuntimeIdentityStatus:
    if authorization_allowed:
        return RuntimeIdentityStatus.AUTHENTICATED_CREATOR
    if authorization_reason in {
        AuthorizationReason.AUTHENTICATION_CONTRADICTION,
        AuthorizationReason.AUTHENTICATION_INTEGRITY_CONFLICT,
    }:
        return RuntimeIdentityStatus.CONTRADICTORY
    if authorization_reason is AuthorizationReason.AUTHENTICATED_NOT_CREATOR:
        return RuntimeIdentityStatus.AUTHENTICATION_DENIED
    if personalization_allowed:
        return RuntimeIdentityStatus.FAMILIAR_CREATOR
    if submitted_count == 0:
        return RuntimeIdentityStatus.NO_EVIDENCE
    return RuntimeIdentityStatus.UNRECOGNIZED


def _explanations(
    *,
    authorization_allowed: bool,
    authorization_reason: AuthorizationReason,
    personalization_allowed: bool,
    personalization_reason: PersonalizationReason,
    contradictions: tuple[Contradiction, ...],
) -> tuple[str, ...]:
    authorization_text = (
        "Creator actions are authorized by active verified authentication evidence."
        if authorization_allowed
        else "Creator actions are denied; authorization reason: "
        f"{authorization_reason.value}."
    )
    personalization_text = (
        "Creator personalization is allowed; basis: "
        f"{personalization_reason.value}."
        if personalization_allowed
        else "Creator personalization is not selected; reason: "
        f"{personalization_reason.value}."
    )
    values = [authorization_text, personalization_text]
    if contradictions:
        values.append(
            "Contradictions: " + ",".join(item.value for item in contradictions) + "."
        )
    values.append("Familiarity evidence never authenticates or authorizes Creator actions.")
    return tuple(values)


def evaluate_identity_runtime(
    *,
    authentication_evidence: Iterable[IdentityEvidence] = (),
    familiarity_evidence: Iterable[IdentityEvidence] = (),
    now: float,
    min_authentication_confidence: float = DEFAULT_AUTHORIZATION_CONFIDENCE,
    min_personalization_confidence: float = DEFAULT_PERSONALIZATION_CONFIDENCE,
) -> IdentityRuntimeResult:
    """Combine verified authentication and familiarity under separate policies."""

    authentication = _materialize_channel(
        authentication_evidence,
        name="authentication_evidence",
        accepted_types=_AUTHENTICATION_TYPES,
        maximum=MAX_AUTHENTICATION_EVIDENCE,
    )
    familiarity = _materialize_channel(
        familiarity_evidence,
        name="familiarity_evidence",
        accepted_types=_FAMILIARITY_TYPES,
        maximum=MAX_FAMILIARITY_EVIDENCE,
    )
    authentication_threshold = _confidence(
        min_authentication_confidence,
        name="min_authentication_confidence",
    )
    personalization_threshold = _confidence(
        min_personalization_confidence,
        name="min_personalization_confidence",
    )
    submitted_count = len(authentication) + len(familiarity)
    if submitted_count > MAX_RUNTIME_EVIDENCE:
        raise ValueError(
            f"identity evidence exceeds the {MAX_RUNTIME_EVIDENCE}-record runtime limit"
        )

    fusion = fuse_identity_evidence((*authentication, *familiarity), now=now)
    authorization = authorize_creator(
        fusion,
        min_authentication_confidence=authentication_threshold,
    )
    personalization_allowed, personalization_reason = _personalization_decision(
        authorization_allowed=authorization.allowed,
        authorization_reason=authorization.reason,
        familiarity_confidence=fusion.familiarity_creator_confidence,
        familiarity_not_creator_confidence=fusion.familiarity_not_creator_confidence,
        contradictions=fusion.contradictions,
        threshold=personalization_threshold,
    )

    familiarity_support = tuple(
        item
        for item in fusion.active_evidence
        if type(item) in _FAMILIARITY_TYPES
        and item.claim is IdentityClaim.CREATOR
        and item.confidence > 0.0
    )
    if authorization.allowed:
        personalization_expires_at = authorization.expires_at
    elif personalization_allowed and familiarity_support:
        personalization_expires_at = min(
            item.expires_at for item in familiarity_support
        )
    else:
        personalization_expires_at = None

    status = _runtime_status(
        authorization_allowed=authorization.allowed,
        authorization_reason=authorization.reason,
        personalization_allowed=personalization_allowed,
        submitted_count=submitted_count,
    )
    provenance = tuple(
        RuntimeProvenance.from_evidence(item) for item in fusion.active_evidence
    )
    return IdentityRuntimeResult(
        status=status,
        assessed_at=fusion.assessed_at,
        creator_actions_authorized=authorization.allowed,
        creator_authenticated=authorization.allowed,
        personalization_allowed=personalization_allowed,
        personalization_target="creator" if personalization_allowed else None,
        authorization_reason=authorization.reason,
        personalization_reason=personalization_reason,
        authentication_confidence=fusion.authentication_creator_confidence,
        familiarity_confidence=fusion.familiarity_creator_confidence,
        identity_confidence=fusion.creator_confidence,
        authentication_threshold=authentication_threshold,
        personalization_threshold=personalization_threshold,
        authorization_expires_at=authorization.expires_at,
        personalization_expires_at=personalization_expires_at,
        contradictions=fusion.contradictions,
        provenance=provenance,
        expired_evidence_ids=fusion.expired_evidence_ids,
        future_evidence_ids=fusion.future_evidence_ids,
        duplicate_evidence_ids=fusion.duplicate_evidence_ids,
        explanations=_explanations(
            authorization_allowed=authorization.allowed,
            authorization_reason=authorization.reason,
            personalization_allowed=personalization_allowed,
            personalization_reason=personalization_reason,
            contradictions=fusion.contradictions,
        ),
        submitted_evidence_count=submitted_count,
    )


@dataclass(frozen=True, slots=True)
class IdentityRuntimeAdapter:
    """Configured stateless facade for repeated pure runtime evaluations."""

    min_authentication_confidence: float = DEFAULT_AUTHORIZATION_CONFIDENCE
    min_personalization_confidence: float = DEFAULT_PERSONALIZATION_CONFIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "min_authentication_confidence",
            _confidence(
                self.min_authentication_confidence,
                name="min_authentication_confidence",
            ),
        )
        object.__setattr__(
            self,
            "min_personalization_confidence",
            _confidence(
                self.min_personalization_confidence,
                name="min_personalization_confidence",
            ),
        )

    def evaluate(
        self,
        *,
        authentication_evidence: Iterable[IdentityEvidence] = (),
        familiarity_evidence: Iterable[IdentityEvidence] = (),
        now: float,
    ) -> IdentityRuntimeResult:
        return evaluate_identity_runtime(
            authentication_evidence=authentication_evidence,
            familiarity_evidence=familiarity_evidence,
            now=now,
            min_authentication_confidence=self.min_authentication_confidence,
            min_personalization_confidence=self.min_personalization_confidence,
        )


__all__ = [
    "DEFAULT_PERSONALIZATION_CONFIDENCE",
    "IdentityRuntimeAdapter",
    "IdentityRuntimeResult",
    "MAX_AUTHENTICATION_EVIDENCE",
    "MAX_FAMILIARITY_EVIDENCE",
    "MAX_RUNTIME_EVIDENCE",
    "PersonalizationReason",
    "RuntimeIdentityStatus",
    "RuntimeProvenance",
    "evaluate_identity_runtime",
]
