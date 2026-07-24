"""Bounded HyFusER-inspired text and speech affect evidence fusion.

HyFusER is useful here as an architectural cue, not as a deployable Alpecca
model.  This module implements a tiny, dependency-free shadow evaluator over
emotion score vectors produced elsewhere.  It preserves two modality branches,
lets each branch observe the other, and then performs confidence-weighted late
fusion.  It never reads raw text or audio, changes emotional state, selects a
Soul focus, or authorizes an action.

One fused vector is projected into advisory scores for all seven Soul
perspectives.  This is deliberately one shared signal, not seven encoder model
instances.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from numbers import Real
from typing import Literal, Mapping, Protocol, runtime_checkable

from alpecca.soul import PERSPECTIVE_ORDER


SCHEMA = "alpecca.multimodal-affect-fusion.v1"
SOUL_ADVISORY_SCHEMA = "alpecca.soul-affect-advisory.v1"
SHARED_BACKBONE_ID = "alpecca.hyfuser-shared-text-speech.v1"
HEAD_ARCHITECTURE = "lightweight-transformer-perspective-head.v1"
DETERMINISTIC_FALLBACK_ID = "deterministic-perspective-projection.v1"
EMOTION_ORDER = (
    "neutral",
    "joy",
    "sadness",
    "fear",
    "anger",
    "surprise",
    "disgust",
)
EXPECTED_PERSPECTIVE_ORDER = (
    "Feeler",
    "Expressor",
    "Carer",
    "Doer",
    "Wanderer",
    "Reflector",
    "Improver",
)
if PERSPECTIVE_ORDER != EXPECTED_PERSPECTIVE_ORDER:
    raise RuntimeError("Soul perspective order changed; affect adapter requires review")

VECTOR_SIZE = len(EMOTION_ORDER)
MAX_PROVENANCE_ITEMS = 4
MAX_REFERENCE_CHARS = 96
FALLBACK_CONFIDENCE_FACTOR = 0.85
FALLBACK_HEAD_CONFIDENCE_FACTOR = 0.75
_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$")

Modality = Literal["text", "speech"]
FusionMode = Literal["dual_cross_late", "text_only", "speech_only"]


def _unit(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


def _vector(values: object, *, name: str) -> tuple[float, ...]:
    if not isinstance(values, (tuple, list)):
        raise TypeError(f"{name} must be a list or tuple")
    if len(values) != VECTOR_SIZE:
        raise ValueError(f"{name} must contain exactly {VECTOR_SIZE} scores")
    checked = tuple(_unit(value, name=f"{name}[{index}]") for index, value in enumerate(values))
    total = sum(checked)
    if total <= 0.0:
        raise ValueError(f"{name} must contain positive evidence")
    return tuple(value / total for value in checked)


def _rounded(values: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(round(value, 6) for value in values)


def _reference(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("provenance references must be strings")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > MAX_REFERENCE_CHARS:
        raise ValueError("provenance reference has an invalid length")
    if not _REFERENCE_RE.fullmatch(cleaned):
        raise ValueError("provenance reference contains unsupported characters")
    return cleaned


@dataclass(frozen=True, slots=True)
class ModalityAffectEvidence:
    """One bounded score vector from an upstream text or speech evaluator."""

    modality: Modality
    scores: tuple[float, ...]
    confidence: float
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.modality not in ("text", "speech"):
            raise ValueError("modality must be 'text' or 'speech'")
        scores = _vector(self.scores, name="scores")
        confidence = _unit(self.confidence, name="confidence")
        if not isinstance(self.provenance, (tuple, list)):
            raise TypeError("provenance must be a tuple or list")
        if not 1 <= len(self.provenance) <= MAX_PROVENANCE_ITEMS:
            raise ValueError(
                f"provenance must contain 1 to {MAX_PROVENANCE_ITEMS} references"
            )
        provenance = tuple(_reference(item) for item in self.provenance)
        if len(set(provenance)) != len(provenance):
            raise ValueError("provenance references must be unique")
        object.__setattr__(self, "scores", scores)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "provenance", provenance)

    def as_dict(self) -> dict[str, object]:
        return {
            "modality": self.modality,
            "order": list(EMOTION_ORDER),
            "scores": list(_rounded(self.scores)),
            "confidence": round(self.confidence, 6),
            "provenance": list(self.provenance),
        }


@dataclass(frozen=True, slots=True)
class PerspectiveHeadSpec:
    """Deployment contract for one distinct head on the shared backbone."""

    perspective: str
    head_id: str
    shared_backbone_id: str = SHARED_BACKBONE_ID
    output_size: int = 1

    def __post_init__(self) -> None:
        if self.perspective not in PERSPECTIVE_ORDER:
            raise ValueError("head perspective is not registered in the Soul")
        if self.head_id != f"hyfuser-head:{self.perspective.lower()}":
            raise ValueError("head_id must be stable and perspective-specific")
        if self.shared_backbone_id != SHARED_BACKBONE_ID:
            raise ValueError("all perspective heads must share the canonical backbone")
        if self.output_size != 1:
            raise ValueError("perspective heads must emit one bounded advisory score")

    def as_dict(self) -> dict[str, object]:
        return {
            "perspective": self.perspective,
            "head_id": self.head_id,
            "architecture": HEAD_ARCHITECTURE,
            "shared_backbone_id": self.shared_backbone_id,
            "output_size": self.output_size,
        }


PERSPECTIVE_HEAD_SPECS = tuple(
    PerspectiveHeadSpec(name, f"hyfuser-head:{name.lower()}")
    for name in PERSPECTIVE_ORDER
)


@runtime_checkable
class PerspectiveHeadBackend(Protocol):
    """Optional future ROG backend; importing this protocol never imports torch."""

    backend_id: str

    def infer_heads(
        self,
        *,
        shared_representation: tuple[float, ...],
        source_confidence: float,
        provenance: tuple[str, ...],
        head_specs: tuple[PerspectiveHeadSpec, ...],
    ) -> object:
        """Return seven records in exact ``PERSPECTIVE_ORDER``."""


@dataclass(frozen=True, slots=True)
class PerspectiveHeadAdvisory:
    """One unqualified head result with explicit evidence lineage."""

    perspective: str
    head_id: str
    score: float
    confidence: float
    provenance: tuple[str, ...]
    evaluator_id: str
    mode: Literal["deterministic_fallback", "transformer_shadow"]

    def __post_init__(self) -> None:
        expected = f"hyfuser-head:{self.perspective.lower()}"
        if self.perspective not in PERSPECTIVE_ORDER or self.head_id != expected:
            raise ValueError("head identity does not match PERSPECTIVE_ORDER")
        object.__setattr__(self, "score", _unit(self.score, name="head score"))
        object.__setattr__(self, "confidence", _unit(self.confidence, name="head confidence"))
        provenance = tuple(_reference(item) for item in self.provenance)
        if not 1 <= len(provenance) <= MAX_PROVENANCE_ITEMS:
            raise ValueError("head provenance exceeds its bounds")
        if not self.evaluator_id or len(self.evaluator_id) > MAX_REFERENCE_CHARS:
            raise ValueError("evaluator_id has an invalid length")
        if self.mode not in ("deterministic_fallback", "transformer_shadow"):
            raise ValueError("unsupported head evaluation mode")
        object.__setattr__(self, "provenance", provenance)

    def as_dict(self) -> dict[str, object]:
        return {
            "perspective": self.perspective,
            "head_id": self.head_id,
            "score": round(self.score, 6),
            "confidence": round(self.confidence, 6),
            "provenance": list(self.provenance),
            "evaluator_id": self.evaluator_id,
            "mode": self.mode,
            "qualified": False,
            "advisory_only": True,
            "authorizes_action": False,
        }


@dataclass(frozen=True, slots=True)
class SoulAffectAdvisory:
    """Seven distinct heads over one shared representation, with no authority."""

    heads: tuple[PerspectiveHeadAdvisory, ...]
    source_confidence: float

    def __post_init__(self) -> None:
        if tuple(head.perspective for head in self.heads) != PERSPECTIVE_ORDER:
            raise ValueError("advisory heads must match exact PERSPECTIVE_ORDER")
        if len({head.head_id for head in self.heads}) != len(PERSPECTIVE_ORDER):
            raise ValueError("perspective heads must have distinct identities")
        object.__setattr__(
            self, "source_confidence", _unit(self.source_confidence, name="source_confidence")
        )

    @property
    def scores(self) -> tuple[float, ...]:
        return tuple(head.score for head in self.heads)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SOUL_ADVISORY_SCHEMA,
            "order": list(PERSPECTIVE_ORDER),
            "scores": list(_rounded(self.scores)),
            "heads": [head.as_dict() for head in self.heads],
            "head_specs": [spec.as_dict() for spec in PERSPECTIVE_HEAD_SPECS],
            "source_confidence": round(self.source_confidence, 6),
            "shared_backbone_id": SHARED_BACKBONE_ID,
            "shared_encoder_count": 1,
            "perspective_head_count": len(self.heads),
            "qualified": False,
            "advisory_only": True,
            "authorizes_action": False,
        }


@dataclass(frozen=True, slots=True)
class FusedAffectEvidence:
    """Shared multimodal evidence vector and its bounded Soul adapter."""

    mode: FusionMode
    scores: tuple[float, ...]
    confidence: float
    agreement: float | None
    modalities: tuple[Modality, ...]
    provenance: tuple[str, ...]
    text_branch: tuple[float, ...] | None
    speech_branch: tuple[float, ...] | None
    soul_advisory: SoulAffectAdvisory

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "mode": self.mode,
            "order": list(EMOTION_ORDER),
            "scores": list(_rounded(self.scores)),
            "confidence": round(self.confidence, 6),
            "agreement": None if self.agreement is None else round(self.agreement, 6),
            "modalities": list(self.modalities),
            "provenance": list(self.provenance),
            "branches": {
                "text": None if self.text_branch is None else list(_rounded(self.text_branch)),
                "speech": None if self.speech_branch is None else list(_rounded(self.speech_branch)),
            },
            "soul_advisory": self.soul_advisory.as_dict(),
            "shadow_only": True,
            "changes_emotional_state": False,
            "authorizes_action": False,
        }


def _blend(
    first: tuple[float, ...],
    second: tuple[float, ...],
    second_weight: float,
) -> tuple[float, ...]:
    own_weight = 1.0
    total = own_weight + second_weight
    return tuple(
        (own_weight * own + second_weight * other) / total
        for own, other in zip(first, second)
    )


def _agreement(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    # Total variation similarity: 1 means identical distributions, 0 means
    # disjoint evidence.  It is bounded and does not need a tensor runtime.
    return max(0.0, min(1.0, 1.0 - 0.5 * sum(abs(a - b) for a, b in zip(first, second))))


# Rows follow PERSPECTIVE_ORDER; columns follow EMOTION_ORDER.  These weights
# only indicate how relevant a shared affect signal may be to each perspective.
# They cannot change directive rank, select focus, or authorize execution.
_PERSPECTIVE_WEIGHTS = (
    (0.15, 0.75, 0.90, 1.00, 0.85, 0.65, 0.75),  # Feeler
    (0.10, 1.00, 0.70, 0.85, 0.90, 0.85, 0.70),  # Expressor
    (0.10, 0.45, 1.00, 1.00, 0.65, 0.50, 0.80),  # Carer
    (0.20, 0.55, 0.35, 0.75, 0.75, 0.70, 0.60),  # Doer
    (0.15, 0.90, 0.25, 0.35, 0.30, 1.00, 0.35),  # Wanderer
    (0.20, 0.40, 0.90, 0.90, 0.70, 0.55, 0.85),  # Reflector
    (0.20, 0.45, 0.70, 0.80, 0.75, 0.75, 0.90),  # Improver
)


def project_for_soul(
    scores: tuple[float, ...] | list[float],
    *,
    confidence: float,
    provenance: tuple[str, ...] = ("fusion:deterministic-fallback",),
) -> SoulAffectAdvisory:
    """Run the deterministic fallback for seven future transformer heads."""

    vector = _vector(scores, name="scores")
    certainty = _unit(confidence, name="confidence")
    projected = tuple(
        max(0.0, min(1.0, sum(value * weight for value, weight in zip(vector, row)) * certainty))
        for row in _PERSPECTIVE_WEIGHTS
    )
    head_confidence = certainty * FALLBACK_HEAD_CONFIDENCE_FACTOR
    heads = tuple(
        PerspectiveHeadAdvisory(
            perspective=spec.perspective,
            head_id=spec.head_id,
            score=score,
            confidence=head_confidence,
            provenance=provenance,
            evaluator_id=DETERMINISTIC_FALLBACK_ID,
            mode="deterministic_fallback",
        )
        for spec, score in zip(PERSPECTIVE_HEAD_SPECS, projected)
    )
    return SoulAffectAdvisory(heads=heads, source_confidence=certainty)


def parse_shadow_head_output(
    payload: object,
    *,
    backend_id: str,
    source_confidence: float,
    provenance: tuple[str, ...],
) -> SoulAffectAdvisory:
    """Validate future ROG head output without granting it runtime authority."""

    if not isinstance(payload, (tuple, list)) or len(payload) != len(PERSPECTIVE_ORDER):
        raise ValueError("backend must return exactly seven head records")
    evaluator_id = _reference(backend_id)
    certainty = _unit(source_confidence, name="source_confidence")
    lineage = tuple(_reference(item) for item in provenance)
    if not 1 <= len(lineage) <= MAX_PROVENANCE_ITEMS:
        raise ValueError("provenance exceeds the hard cap")
    heads: list[PerspectiveHeadAdvisory] = []
    for spec, record in zip(PERSPECTIVE_HEAD_SPECS, payload):
        if not isinstance(record, Mapping):
            raise TypeError("each backend head record must be a mapping")
        allowed = {"perspective", "head_id", "score", "confidence", "provenance"}
        if set(record) != allowed:
            raise ValueError("backend head record has missing or extra fields")
        if record.get("perspective") != spec.perspective or record.get("head_id") != spec.head_id:
            raise ValueError("backend head order or identity does not match the contract")
        record_provenance = record.get("provenance")
        if not isinstance(record_provenance, (tuple, list)):
            raise TypeError("backend provenance must be a tuple or list")
        if tuple(record_provenance) != lineage:
            raise ValueError("backend cannot replace source provenance")
        backend_confidence = _unit(record.get("confidence"), name="head confidence")
        heads.append(
            PerspectiveHeadAdvisory(
                perspective=spec.perspective,
                head_id=spec.head_id,
                score=_unit(record.get("score"), name="head score"),
                confidence=min(certainty, backend_confidence),
                provenance=lineage,
                evaluator_id=evaluator_id,
                mode="transformer_shadow",
            )
        )
    return SoulAffectAdvisory(heads=tuple(heads), source_confidence=certainty)


def fuse_affect_evidence(
    *,
    text: ModalityAffectEvidence | None = None,
    speech: ModalityAffectEvidence | None = None,
) -> FusedAffectEvidence:
    """Fuse zero raw content: accepts only bounded upstream score evidence."""

    if text is None and speech is None:
        raise ValueError("at least one modality is required")
    if text is not None and not isinstance(text, ModalityAffectEvidence):
        raise TypeError("text must be ModalityAffectEvidence or None")
    if speech is not None and not isinstance(speech, ModalityAffectEvidence):
        raise TypeError("speech must be ModalityAffectEvidence or None")
    if text is not None and text.modality != "text":
        raise ValueError("text evidence has the wrong modality")
    if speech is not None and speech.modality != "speech":
        raise ValueError("speech evidence has the wrong modality")

    agreement: float | None = None
    text_branch: tuple[float, ...] | None = None
    speech_branch: tuple[float, ...] | None = None
    if text is None:
        assert speech is not None
        mode: FusionMode = "speech_only"
        fused = speech.scores
        confidence = speech.confidence * FALLBACK_CONFIDENCE_FACTOR
        speech_branch = speech.scores
        modalities: tuple[Modality, ...] = ("speech",)
        provenance = speech.provenance
    elif speech is None:
        mode = "text_only"
        fused = text.scores
        confidence = text.confidence * FALLBACK_CONFIDENCE_FACTOR
        text_branch = text.scores
        modalities = ("text",)
        provenance = text.provenance
    else:
        mode = "dual_cross_late"
        agreement = _agreement(text.scores, speech.scores)
        # Each branch sees the other in proportion to measured agreement.  Low
        # agreement preserves the independent branches instead of forcing one
        # modality to overwrite the other.
        text_branch = _blend(text.scores, speech.scores, agreement * speech.confidence)
        speech_branch = _blend(speech.scores, text.scores, agreement * text.confidence)
        branch_weight = text.confidence + speech.confidence
        if branch_weight <= 0.0:
            fused = tuple((a + b) * 0.5 for a, b in zip(text_branch, speech_branch))
        else:
            fused = tuple(
                (text.confidence * a + speech.confidence * b) / branch_weight
                for a, b in zip(text_branch, speech_branch)
            )
        fused = _vector(fused, name="fused scores")
        mean_confidence = (text.confidence + speech.confidence) * 0.5
        confidence = mean_confidence * (0.5 + 0.5 * agreement)
        modalities = ("text", "speech")
        provenance = tuple(dict.fromkeys((*text.provenance, *speech.provenance)))
        if len(provenance) > MAX_PROVENANCE_ITEMS:
            raise ValueError("combined provenance exceeds the hard cap")

    confidence = max(0.0, min(1.0, confidence))
    advisory = project_for_soul(
        fused,
        confidence=confidence,
        provenance=provenance,
    )
    return FusedAffectEvidence(
        mode=mode,
        scores=fused,
        confidence=confidence,
        agreement=agreement,
        modalities=modalities,
        provenance=provenance,
        text_branch=text_branch,
        speech_branch=speech_branch,
        soul_advisory=advisory,
    )


__all__ = [
    "EMOTION_ORDER",
    "EXPECTED_PERSPECTIVE_ORDER",
    "FALLBACK_CONFIDENCE_FACTOR",
    "FALLBACK_HEAD_CONFIDENCE_FACTOR",
    "FusedAffectEvidence",
    "HEAD_ARCHITECTURE",
    "MAX_PROVENANCE_ITEMS",
    "ModalityAffectEvidence",
    "PERSPECTIVE_HEAD_SPECS",
    "PERSPECTIVE_ORDER",
    "PerspectiveHeadAdvisory",
    "PerspectiveHeadBackend",
    "PerspectiveHeadSpec",
    "SCHEMA",
    "SHARED_BACKBONE_ID",
    "SOUL_ADVISORY_SCHEMA",
    "SoulAffectAdvisory",
    "VECTOR_SIZE",
    "fuse_affect_evidence",
    "parse_shadow_head_output",
    "project_for_soul",
]
