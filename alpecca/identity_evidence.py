"""Pure identity-evidence fusion and Creator authorization policy.

Familiarity is probabilistic context, not authentication.  Voice, face, and
text evidence can inform an identity-confidence estimate, but only active,
internally consistent account, device, or session authentication evidence can
authorize the Creator principal.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import ClassVar, Iterable


CREATOR_PRINCIPAL = "creator"
DEFAULT_AUTHORIZATION_CONFIDENCE = 0.90
MAX_FAMILIARITY_FUSION_CONFIDENCE = 0.95
MAX_PROVENANCE_TEXT_CHARS = 160
MAX_EVIDENCE_ID_CHARS = 128

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class IdentityClaim(str, Enum):
    """The identity proposition supported by one evidence record."""

    CREATOR = "creator"
    NOT_CREATOR = "not_creator"


class EvidenceType(str, Enum):
    """Supported authentication and probabilistic familiarity channels."""

    AUTHENTICATED_ACCOUNT = "authenticated_account"
    AUTHENTICATED_DEVICE = "authenticated_device"
    AUTHENTICATED_SESSION = "authenticated_session"
    VOICE_FAMILIARITY = "voice_familiarity"
    FACE_FAMILIARITY = "face_familiarity"
    TEXT_FAMILIARITY = "text_familiarity"


class Contradiction(str, Enum):
    """Contradictions retained in fusion results for callers and audit logs."""

    DUPLICATE_EVIDENCE_ID = "duplicate_evidence_id"
    AUTHENTICATION_CLAIM_CONFLICT = "authentication_claim_conflict"
    FAMILIARITY_CLAIM_CONFLICT = "familiarity_claim_conflict"
    CROSS_CHANNEL_CLAIM_CONFLICT = "cross_channel_claim_conflict"


class AuthorizationReason(str, Enum):
    """Stable reason codes for explicit Creator authorization decisions."""

    AUTHORIZED_BY_AUTHENTICATION = "authorized_by_authentication"
    NO_ACTIVE_AUTHENTICATION = "no_active_authentication"
    AUTHENTICATED_NOT_CREATOR = "authenticated_not_creator"
    INSUFFICIENT_AUTHENTICATION_CONFIDENCE = (
        "insufficient_authentication_confidence"
    )
    AUTHENTICATION_CONTRADICTION = "authentication_contradiction"
    AUTHENTICATION_INTEGRITY_CONFLICT = "authentication_integrity_conflict"


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
class EvidenceProvenance:
    """Secret-free origin metadata retained through fusion and decisions."""

    source: str
    mechanism: str
    reference: str

    def __post_init__(self) -> None:
        for field_name in ("source", "mechanism", "reference"):
            value = _bounded_text(
                getattr(self, field_name),
                name=field_name,
                maximum=MAX_PROVENANCE_TEXT_CHARS,
            )
            object.__setattr__(self, field_name, value)

    def as_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "mechanism": self.mechanism,
            "reference": self.reference,
        }


@dataclass(frozen=True, slots=True)
class IdentityEvidence:
    """One immutable, directional, expiring identity observation."""

    evidence_id: str
    claim: IdentityClaim
    confidence: float
    observed_at: float
    expires_at: float
    provenance: EvidenceProvenance

    evidence_type: ClassVar[EvidenceType]
    authorization_capable: ClassVar[bool] = False
    max_ttl_seconds: ClassVar[float] = 3600.0

    def __post_init__(self) -> None:
        evidence_id = _bounded_text(
            self.evidence_id,
            name="evidence_id",
            maximum=MAX_EVIDENCE_ID_CHARS,
        )
        if not _IDENTIFIER_RE.fullmatch(evidence_id):
            raise ValueError(
                "evidence_id may contain only letters, digits, '.', '_', ':', and '-'"
            )
        try:
            claim = IdentityClaim(self.claim)
        except (TypeError, ValueError) as exc:
            raise ValueError("claim must be creator or not_creator") from exc
        confidence = _confidence(self.confidence)
        observed_at = _finite_number(self.observed_at, name="observed_at")
        expires_at = _finite_number(self.expires_at, name="expires_at")
        if observed_at < 0.0:
            raise ValueError("observed_at cannot be negative")
        lifetime = expires_at - observed_at
        if not 0.0 < lifetime <= self.max_ttl_seconds:
            raise ValueError(
                "expires_at must be after observed_at and within "
                f"{self.max_ttl_seconds:g} seconds for {self.evidence_type.value}"
            )
        if not isinstance(self.provenance, EvidenceProvenance):
            raise TypeError("provenance must be EvidenceProvenance")
        object.__setattr__(self, "evidence_id", evidence_id)
        object.__setattr__(self, "claim", claim)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "expires_at", expires_at)

    @classmethod
    def create(
        cls,
        *,
        evidence_id: str,
        claim: IdentityClaim,
        confidence: float,
        observed_at: float,
        ttl_seconds: float,
        provenance: EvidenceProvenance,
    ) -> "IdentityEvidence":
        observed = _finite_number(observed_at, name="observed_at")
        ttl = _finite_number(ttl_seconds, name="ttl_seconds")
        return cls(
            evidence_id=evidence_id,
            claim=claim,
            confidence=confidence,
            observed_at=observed,
            expires_at=observed + ttl,
            provenance=provenance,
        )

    def is_active(self, now: float) -> bool:
        current = _finite_number(now, name="now")
        return self.observed_at <= current < self.expires_at

    def is_expired(self, now: float) -> bool:
        return _finite_number(now, name="now") >= self.expires_at

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type.value,
            "claim": self.claim.value,
            "confidence": self.confidence,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "authorization_capable": self.authorization_capable,
            "provenance": self.provenance.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class AuthenticatedAccountEvidence(IdentityEvidence):
    evidence_type: ClassVar[EvidenceType] = EvidenceType.AUTHENTICATED_ACCOUNT
    authorization_capable: ClassVar[bool] = True
    max_ttl_seconds: ClassVar[float] = 86400.0


@dataclass(frozen=True, slots=True)
class AuthenticatedDeviceEvidence(IdentityEvidence):
    evidence_type: ClassVar[EvidenceType] = EvidenceType.AUTHENTICATED_DEVICE
    authorization_capable: ClassVar[bool] = True
    max_ttl_seconds: ClassVar[float] = 30.0 * 86400.0


@dataclass(frozen=True, slots=True)
class AuthenticatedSessionEvidence(IdentityEvidence):
    evidence_type: ClassVar[EvidenceType] = EvidenceType.AUTHENTICATED_SESSION
    authorization_capable: ClassVar[bool] = True
    max_ttl_seconds: ClassVar[float] = 86400.0


@dataclass(frozen=True, slots=True)
class VoiceFamiliarityEvidence(IdentityEvidence):
    evidence_type: ClassVar[EvidenceType] = EvidenceType.VOICE_FAMILIARITY


@dataclass(frozen=True, slots=True)
class FaceFamiliarityEvidence(IdentityEvidence):
    evidence_type: ClassVar[EvidenceType] = EvidenceType.FACE_FAMILIARITY


@dataclass(frozen=True, slots=True)
class TextFamiliarityEvidence(IdentityEvidence):
    evidence_type: ClassVar[EvidenceType] = EvidenceType.TEXT_FAMILIARITY


def _noisy_or(confidences: Iterable[float], *, cap: float = 1.0) -> float:
    remaining = 1.0
    for confidence in confidences:
        remaining *= 1.0 - confidence
    return max(0.0, min(cap, 1.0 - remaining))


@dataclass(frozen=True, slots=True)
class IdentityFusionResult:
    """Bounded confidence summary; it is not itself an authorization grant."""

    assessed_at: float
    active_evidence: tuple[IdentityEvidence, ...]
    expired_evidence_ids: tuple[str, ...]
    future_evidence_ids: tuple[str, ...]
    duplicate_evidence_ids: tuple[str, ...]
    contradictions: tuple[Contradiction, ...]
    authentication_creator_confidence: float
    authentication_not_creator_confidence: float
    familiarity_creator_confidence: float
    familiarity_not_creator_confidence: float
    creator_confidence: float
    not_creator_confidence: float
    authentication_integrity_conflict: bool = False

    @property
    def has_contradiction(self) -> bool:
        return bool(self.contradictions)

    @property
    def provenance(self) -> tuple[EvidenceProvenance, ...]:
        return tuple(item.provenance for item in self.active_evidence)

    def as_dict(self) -> dict[str, object]:
        return {
            "assessed_at": self.assessed_at,
            "active_evidence": [item.as_dict() for item in self.active_evidence],
            "expired_evidence_ids": list(self.expired_evidence_ids),
            "future_evidence_ids": list(self.future_evidence_ids),
            "duplicate_evidence_ids": list(self.duplicate_evidence_ids),
            "contradictions": [item.value for item in self.contradictions],
            "authentication_creator_confidence": (
                self.authentication_creator_confidence
            ),
            "authentication_not_creator_confidence": (
                self.authentication_not_creator_confidence
            ),
            "familiarity_creator_confidence": self.familiarity_creator_confidence,
            "familiarity_not_creator_confidence": (
                self.familiarity_not_creator_confidence
            ),
            "creator_confidence": self.creator_confidence,
            "not_creator_confidence": self.not_creator_confidence,
            "authentication_integrity_conflict": (
                self.authentication_integrity_conflict
            ),
        }


def fuse_identity_evidence(
    evidence: Iterable[IdentityEvidence], *, now: float
) -> IdentityFusionResult:
    """Fuse current evidence while preserving channel and contradiction boundaries."""

    current = _finite_number(now, name="now")
    if current < 0.0:
        raise ValueError("now cannot be negative")

    by_id: dict[str, IdentityEvidence] = {}
    conflicted: dict[str, list[IdentityEvidence]] = {}
    for item in evidence:
        if not isinstance(item, IdentityEvidence):
            raise TypeError("evidence must contain only IdentityEvidence instances")
        existing = by_id.get(item.evidence_id)
        if existing is None and item.evidence_id not in conflicted:
            by_id[item.evidence_id] = item
        elif existing == item:
            continue
        else:
            conflict_items = conflicted.setdefault(item.evidence_id, [])
            if existing is not None:
                conflict_items.append(existing)
                del by_id[item.evidence_id]
            conflict_items.append(item)

    active: list[IdentityEvidence] = []
    expired_ids: list[str] = []
    future_ids: list[str] = []
    for item in by_id.values():
        if current < item.observed_at:
            future_ids.append(item.evidence_id)
        elif item.is_expired(current):
            expired_ids.append(item.evidence_id)
        else:
            active.append(item)

    auth_creator = [
        item.confidence
        for item in active
        if item.authorization_capable and item.claim is IdentityClaim.CREATOR
    ]
    auth_not_creator = [
        item.confidence
        for item in active
        if item.authorization_capable and item.claim is IdentityClaim.NOT_CREATOR
    ]
    familiar_creator = [
        item.confidence
        for item in active
        if not item.authorization_capable and item.claim is IdentityClaim.CREATOR
    ]
    familiar_not_creator = [
        item.confidence
        for item in active
        if not item.authorization_capable and item.claim is IdentityClaim.NOT_CREATOR
    ]

    auth_creator_score = _noisy_or(auth_creator)
    auth_not_creator_score = _noisy_or(auth_not_creator)
    familiar_creator_score = _noisy_or(
        familiar_creator, cap=MAX_FAMILIARITY_FUSION_CONFIDENCE
    )
    familiar_not_creator_score = _noisy_or(
        familiar_not_creator, cap=MAX_FAMILIARITY_FUSION_CONFIDENCE
    )

    contradictions: list[Contradiction] = []
    if conflicted:
        contradictions.append(Contradiction.DUPLICATE_EVIDENCE_ID)
    if auth_creator_score > 0.0 and auth_not_creator_score > 0.0:
        contradictions.append(Contradiction.AUTHENTICATION_CLAIM_CONFLICT)
    if familiar_creator_score > 0.0 and familiar_not_creator_score > 0.0:
        contradictions.append(Contradiction.FAMILIARITY_CLAIM_CONFLICT)
    if (
        auth_creator_score > 0.0 and familiar_not_creator_score > 0.0
    ) or (
        auth_not_creator_score > 0.0 and familiar_creator_score > 0.0
    ):
        contradictions.append(Contradiction.CROSS_CHANNEL_CLAIM_CONFLICT)

    all_creator = _noisy_or((auth_creator_score, familiar_creator_score))
    all_not_creator = _noisy_or(
        (auth_not_creator_score, familiar_not_creator_score)
    )
    authentication_integrity_conflict = any(
        item.authorization_capable
        for items in conflicted.values()
        for item in items
    )
    return IdentityFusionResult(
        assessed_at=current,
        active_evidence=tuple(active),
        expired_evidence_ids=tuple(sorted(expired_ids)),
        future_evidence_ids=tuple(sorted(future_ids)),
        duplicate_evidence_ids=tuple(sorted(conflicted)),
        contradictions=tuple(contradictions),
        authentication_creator_confidence=auth_creator_score,
        authentication_not_creator_confidence=auth_not_creator_score,
        familiarity_creator_confidence=familiar_creator_score,
        familiarity_not_creator_confidence=familiar_not_creator_score,
        creator_confidence=all_creator * (1.0 - all_not_creator),
        not_creator_confidence=all_not_creator * (1.0 - all_creator),
        authentication_integrity_conflict=authentication_integrity_conflict,
    )


@dataclass(frozen=True, slots=True)
class CreatorAuthorizationDecision:
    """Secret-free, expiring result of the Creator authorization policy."""

    allowed: bool
    reason: AuthorizationReason
    assessed_at: float
    threshold: float
    authentication_confidence: float
    identity_confidence: float
    authorizing_evidence_ids: tuple[str, ...]
    provenance: tuple[EvidenceProvenance, ...]
    expires_at: float | None
    contradictions: tuple[Contradiction, ...]
    principal: str | None = None

    @property
    def authorized(self) -> bool:
        return self.allowed

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "reason": self.reason.value,
            "principal": self.principal,
            "assessed_at": self.assessed_at,
            "threshold": self.threshold,
            "authentication_confidence": self.authentication_confidence,
            "identity_confidence": self.identity_confidence,
            "authorizing_evidence_ids": list(self.authorizing_evidence_ids),
            "provenance": [item.as_dict() for item in self.provenance],
            "expires_at": self.expires_at,
            "contradictions": [item.value for item in self.contradictions],
        }


def authorize_creator(
    fusion: IdentityFusionResult,
    *,
    min_authentication_confidence: float = DEFAULT_AUTHORIZATION_CONFIDENCE,
) -> CreatorAuthorizationDecision:
    """Authorize Creator from a fusion result using authentication only."""

    if not isinstance(fusion, IdentityFusionResult):
        raise TypeError("fusion must be IdentityFusionResult")
    threshold = _confidence(
        min_authentication_confidence,
        name="min_authentication_confidence",
    )
    creator_auth = [
        item
        for item in fusion.active_evidence
        if item.authorization_capable
        and item.claim is IdentityClaim.CREATOR
        and item.confidence > 0.0
    ]

    if fusion.authentication_integrity_conflict:
        reason = AuthorizationReason.AUTHENTICATION_INTEGRITY_CONFLICT
    elif Contradiction.AUTHENTICATION_CLAIM_CONFLICT in fusion.contradictions:
        reason = AuthorizationReason.AUTHENTICATION_CONTRADICTION
    elif (
        fusion.authentication_not_creator_confidence > 0.0
        and fusion.authentication_creator_confidence == 0.0
    ):
        reason = AuthorizationReason.AUTHENTICATED_NOT_CREATOR
    elif not creator_auth:
        reason = AuthorizationReason.NO_ACTIVE_AUTHENTICATION
    elif fusion.authentication_creator_confidence < threshold:
        reason = AuthorizationReason.INSUFFICIENT_AUTHENTICATION_CONFIDENCE
    else:
        reason = AuthorizationReason.AUTHORIZED_BY_AUTHENTICATION

    allowed = reason is AuthorizationReason.AUTHORIZED_BY_AUTHENTICATION
    authorizing = tuple(creator_auth) if allowed else ()
    return CreatorAuthorizationDecision(
        allowed=allowed,
        reason=reason,
        principal=CREATOR_PRINCIPAL if allowed else None,
        assessed_at=fusion.assessed_at,
        threshold=threshold,
        authentication_confidence=fusion.authentication_creator_confidence,
        identity_confidence=fusion.creator_confidence,
        authorizing_evidence_ids=tuple(
            item.evidence_id for item in authorizing
        ),
        provenance=tuple(item.provenance for item in authorizing),
        expires_at=(
            min(item.expires_at for item in authorizing) if authorizing else None
        ),
        contradictions=fusion.contradictions,
    )


def decide_creator_authorization(
    evidence: Iterable[IdentityEvidence],
    *,
    now: float,
    min_authentication_confidence: float = DEFAULT_AUTHORIZATION_CONFIDENCE,
) -> CreatorAuthorizationDecision:
    """Fuse evidence and return one explicit Creator authorization decision."""

    return authorize_creator(
        fuse_identity_evidence(evidence, now=now),
        min_authentication_confidence=min_authentication_confidence,
    )


__all__ = [
    "AuthorizationReason",
    "AuthenticatedAccountEvidence",
    "AuthenticatedDeviceEvidence",
    "AuthenticatedSessionEvidence",
    "CREATOR_PRINCIPAL",
    "Contradiction",
    "CreatorAuthorizationDecision",
    "DEFAULT_AUTHORIZATION_CONFIDENCE",
    "EvidenceProvenance",
    "EvidenceType",
    "FaceFamiliarityEvidence",
    "IdentityClaim",
    "IdentityEvidence",
    "IdentityFusionResult",
    "MAX_EVIDENCE_ID_CHARS",
    "MAX_FAMILIARITY_FUSION_CONFIDENCE",
    "MAX_PROVENANCE_TEXT_CHARS",
    "TextFamiliarityEvidence",
    "VoiceFamiliarityEvidence",
    "authorize_creator",
    "decide_creator_authorization",
    "fuse_identity_evidence",
]
