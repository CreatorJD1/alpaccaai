"""Deterministic temporal-fact derivation over verified observations.

The built-in extractor recognizes a deliberately narrow line protocol. An
optional callback may provide richer extraction, but it cannot supply or alter
source provenance: actor, surface, scope, time, and evidence IDs always come
from the bound :class:`~alpecca.temporal_memory.EvidenceObservation`.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from alpecca.temporal_memory import (
    ContradictionLink,
    EvidenceObservation,
    TemporalFact,
    TemporalMemoryError,
    TemporalMemoryStore,
)


Relation = Literal["assertion", "correction", "supersession", "contradiction"]
Extractor = Callable[["BoundedObservation"], Iterable["ExtractedFact"]]

MAX_OBSERVATIONS = 16
MAX_OBSERVATION_CHARS = 4_000
MAX_TOTAL_CHARS = 16_000
MAX_CANDIDATES = 64
MAX_FACT_PART_CHARS = 4_000
_RELATIONS = frozenset({"assertion", "correction", "supersession", "contradiction"})
_LINE = re.compile(
    r"^\s*(fact|assertion|correction|supersession|contradiction)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)


def contains_explicit_temporal_statement(text: object) -> bool:
    """Whether persisted text contains a statement the safe extractor accepts."""

    if not isinstance(text, str):
        return False
    return any(_LINE.fullmatch(line) is not None for line in text.splitlines())


class TemporalDerivationError(ValueError):
    """A bounded input or extraction candidate was rejected."""


@dataclass(frozen=True, slots=True)
class BoundedObservation:
    observation: EvidenceObservation
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.observation, EvidenceObservation):
            raise TemporalDerivationError(
                "observation must be a temporal-memory EvidenceObservation"
            )
        if not isinstance(self.text, str):
            raise TemporalDerivationError("observation text must be a string")
        if not self.text.strip():
            raise TemporalDerivationError("observation text must not be empty")
        if len(self.text) > MAX_OBSERVATION_CHARS:
            raise TemporalDerivationError(
                f"observation text exceeds {MAX_OBSERVATION_CHARS} characters"
            )
        digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if digest != self.observation.content_sha256:
            raise TemporalDerivationError(
                "observation text does not match its stored provenance hash"
            )


@dataclass(frozen=True, slots=True)
class ExtractedFact:
    subject: str
    predicate: str
    object_text: str
    confidence: float = 0.6
    relation: Relation = "assertion"


@dataclass(frozen=True, slots=True)
class FactCandidate:
    subject: str
    predicate: str
    object_text: str
    confidence: float
    relation: Relation
    actor_id: str
    surface: str
    scope: str
    valid_from: float
    evidence_observation_ids: tuple[int, ...]
    source_observation_uid: str


@dataclass(frozen=True, slots=True)
class DerivationOutcome:
    candidate: FactCandidate
    fact: TemporalFact
    closed_fact_ids: tuple[int, ...]
    contradiction_links: tuple[ContradictionLink, ...]


@dataclass(frozen=True, slots=True)
class ShadowRecallComparison:
    legacy_count: int
    temporal_count: int
    overlap: tuple[str, ...]
    legacy_only: tuple[str, ...]
    temporal_only: tuple[str, ...]
    agreement_ratio: float
    temporal_fact_ids: tuple[int, ...]


def _text(value: object, *, name: str, maximum: int = MAX_FACT_PART_CHARS) -> str:
    result = " ".join(str(value or "").split())
    if not result:
        raise TemporalDerivationError(f"{name} must not be empty")
    if len(result) > maximum:
        raise TemporalDerivationError(f"{name} exceeds {maximum} characters")
    return result


def _confidence(value: object) -> float:
    if isinstance(value, bool):
        raise TemporalDerivationError("confidence must be between 0 and 1")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise TemporalDerivationError("confidence must be between 0 and 1") from None
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise TemporalDerivationError("confidence must be between 0 and 1")
    return result


def _relation(value: object) -> Relation:
    result = str(value or "").strip().lower()
    if result == "fact":
        result = "assertion"
    if result not in _RELATIONS:
        raise TemporalDerivationError(f"unsupported temporal relation: {result!r}")
    return result  # type: ignore[return-value]


def deterministic_extractor(observation: BoundedObservation) -> tuple[ExtractedFact, ...]:
    """Extract facts from ``kind: subject | predicate | object | confidence``.

    Confidence is optional and defaults to 0.6. Lines outside this explicit
    protocol are ignored rather than guessed from natural language.
    """

    extracted: list[ExtractedFact] = []
    for line in observation.text.splitlines():
        match = _LINE.fullmatch(line)
        if match is None:
            continue
        parts = [part.strip() for part in match.group(2).split("|")]
        if len(parts) not in {3, 4}:
            raise TemporalDerivationError(
                "fact lines require subject | predicate | object [| confidence]"
            )
        extracted.append(ExtractedFact(
            subject=parts[0],
            predicate=parts[1],
            object_text=parts[2],
            confidence=_confidence(parts[3]) if len(parts) == 4 else 0.6,
            relation=_relation(match.group(1)),
        ))
    return tuple(extracted)


def derive_candidates(
    observations: Sequence[BoundedObservation],
    *,
    extractor: Extractor | None = None,
) -> tuple[FactCandidate, ...]:
    """Build bounded, source-bound candidates without calling an LLM."""

    if isinstance(observations, (str, bytes)) or not isinstance(observations, Sequence):
        raise TemporalDerivationError("observations must be a bounded sequence")
    if len(observations) > MAX_OBSERVATIONS:
        raise TemporalDerivationError(f"at most {MAX_OBSERVATIONS} observations are allowed")
    if any(not isinstance(item, BoundedObservation) for item in observations):
        raise TemporalDerivationError("all observations must be BoundedObservation values")
    if sum(len(item.text) for item in observations) > MAX_TOTAL_CHARS:
        raise TemporalDerivationError(
            f"observation batch exceeds {MAX_TOTAL_CHARS} characters"
        )
    selected_extractor = extractor or deterministic_extractor
    if not callable(selected_extractor):
        raise TemporalDerivationError("extractor must be callable")

    candidates: list[FactCandidate] = []
    for bounded in observations:
        raw_candidates = selected_extractor(bounded)
        if raw_candidates is None:
            raise TemporalDerivationError("extractor must return an iterable")
        try:
            extracted_values = tuple(raw_candidates)
        except TypeError:
            raise TemporalDerivationError("extractor must return an iterable") from None
        for extracted in extracted_values:
            if not isinstance(extracted, ExtractedFact):
                raise TemporalDerivationError(
                    "extractor output must contain ExtractedFact values"
                )
            candidates.append(FactCandidate(
                subject=_text(extracted.subject, name="subject"),
                predicate=_text(extracted.predicate, name="predicate"),
                object_text=_text(extracted.object_text, name="object_text"),
                confidence=_confidence(extracted.confidence),
                relation=_relation(extracted.relation),
                actor_id=bounded.observation.actor_id,
                surface=bounded.observation.surface,
                scope=bounded.observation.scope,
                valid_from=bounded.observation.observed_at,
                evidence_observation_ids=(bounded.observation.id,),
                source_observation_uid=bounded.observation.observation_uid,
            ))
            if len(candidates) > MAX_CANDIDATES:
                raise TemporalDerivationError(
                    f"extraction exceeds {MAX_CANDIDATES} candidates"
                )
    return tuple(sorted(
        candidates,
        key=lambda item: (
            item.valid_from,
            item.evidence_observation_ids,
            item.subject.casefold(),
            item.predicate.casefold(),
            item.object_text.casefold(),
            item.relation,
        ),
    ))


def _candidate_uid(candidate: FactCandidate) -> str:
    canonical = json.dumps({
        "actor_id": candidate.actor_id,
        "confidence": candidate.confidence,
        "evidence": candidate.evidence_observation_ids,
        "object": candidate.object_text,
        "predicate": candidate.predicate,
        "relation": candidate.relation,
        "scope": candidate.scope,
        "source_observation_uid": candidate.source_observation_uid,
        "subject": candidate.subject,
        "surface": candidate.surface,
        "valid_from": candidate.valid_from,
    }, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return "derived-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def apply_candidates(
    store: TemporalMemoryStore,
    candidates: Sequence[FactCandidate],
) -> tuple[DerivationOutcome, ...]:
    """Persist ordered candidates and apply explicit temporal relationships.

    Assertions that disagree with an active fact are linked as contradictions
    but do not close history. Corrections and supersessions additionally close
    differing active facts at the new fact's validity start.
    """

    if not isinstance(store, TemporalMemoryStore):
        raise TemporalDerivationError("store must be a TemporalMemoryStore")
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise TemporalDerivationError("candidates must be a bounded sequence")
    if len(candidates) > MAX_CANDIDATES:
        raise TemporalDerivationError(f"at most {MAX_CANDIDATES} candidates are allowed")
    if any(not isinstance(item, FactCandidate) for item in candidates):
        raise TemporalDerivationError("all candidates must be FactCandidate values")

    outcomes: list[DerivationOutcome] = []
    ordered = sorted(
        candidates,
        key=lambda item: (item.valid_from, item.evidence_observation_ids, _candidate_uid(item)),
    )
    # One observation may derive several related facts. Keep all writes,
    # closures, and contradiction links atomic so a failed later candidate
    # cannot leave a partial fact set that is then retried or dead-lettered.
    with store.transaction():
        for candidate in ordered:
            active = store.facts_valid_at(
                candidate.valid_from,
                scope=candidate.scope,
                subject=candidate.subject,
                predicate=candidate.predicate,
            )
            differing = [
                fact for fact in active
                if fact.object_text.casefold() != candidate.object_text.casefold()
            ]
            if candidate.relation in {"correction", "supersession"}:
                same_start = [fact.id for fact in differing if fact.valid_from >= candidate.valid_from]
                if same_start:
                    raise TemporalDerivationError(
                        "correction cannot close a differing fact with the same validity start"
                    )
            try:
                fact = store.record_fact(
                    fact_uid=_candidate_uid(candidate),
                    subject=candidate.subject,
                    predicate=candidate.predicate,
                    object_text=candidate.object_text,
                    confidence=candidate.confidence,
                    actor_id=candidate.actor_id,
                    surface=candidate.surface,
                    scope=candidate.scope,
                    valid_from=candidate.valid_from,
                    evidence_observation_ids=candidate.evidence_observation_ids,
                    derivation_kind=candidate.relation,
                    recorded_at=candidate.valid_from,
                )
            except TemporalMemoryError as exc:
                raise TemporalDerivationError(str(exc)) from exc

            closed: list[int] = []
            links: list[ContradictionLink] = []
            for prior in differing:
                if prior.id == fact.id:
                    continue
                if candidate.relation in {"correction", "supersession"}:
                    try:
                        store.close_validity(
                            prior.id,
                            valid_to=candidate.valid_from,
                            invalidated_at=candidate.valid_from,
                        )
                    except TemporalMemoryError as exc:
                        raise TemporalDerivationError(str(exc)) from exc
                    closed.append(prior.id)
                try:
                    links.append(store.link_contradiction(
                        prior.id,
                        fact.id,
                        reason=f"derived-{candidate.relation}",
                        observation_id=candidate.evidence_observation_ids[0],
                        linked_at=candidate.valid_from,
                    ))
                except TemporalMemoryError as exc:
                    raise TemporalDerivationError(str(exc)) from exc
            outcomes.append(DerivationOutcome(
                candidate=candidate,
                fact=fact,
                closed_fact_ids=tuple(sorted(closed)),
                contradiction_links=tuple(links),
            ))
    return tuple(outcomes)


def derive_and_apply(
    store: TemporalMemoryStore,
    observations: Sequence[BoundedObservation],
    *,
    extractor: Extractor | None = None,
) -> tuple[DerivationOutcome, ...]:
    return apply_candidates(store, derive_candidates(observations, extractor=extractor))


def _normalize_signature(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _legacy_signature(value: object) -> str:
    if isinstance(value, Mapping):
        subject = value.get("subject")
        predicate = value.get("predicate")
        object_text = value.get("object_text", value.get("object"))
        if all(item is not None and str(item).strip() for item in (
            subject, predicate, object_text,
        )):
            return _normalize_signature(f"{subject} | {predicate} | {object_text}")
        for key in ("text", "content", "fact"):
            if value.get(key):
                text = str(value[key]).strip()
                match = _LINE.fullmatch(text)
                if match is not None:
                    parts = [part.strip() for part in match.group(2).split("|")]
                    if len(parts) in {3, 4} and all(parts[:3]):
                        return _normalize_signature(
                            f"{parts[0]} | {parts[1]} | {parts[2]}"
                        )
                return _normalize_signature(text)
    return _normalize_signature(value)


def _temporal_signature(fact: TemporalFact) -> str:
    return _normalize_signature(
        f"{fact.subject} | {fact.predicate} | {fact.object_text}"
    )


def compare_shadow_recall(
    store: TemporalMemoryStore,
    legacy_results: Sequence[object],
    *,
    at: float,
    scope: str,
    subject: str | None = None,
    predicate: str | None = None,
    actor_id: str | None = None,
    surface: str | None = None,
    limit: int = 20,
) -> ShadowRecallComparison:
    """Compare legacy output with temporal facts without changing either path."""

    if not isinstance(store, TemporalMemoryStore):
        raise TemporalDerivationError("store must be a TemporalMemoryStore")
    if isinstance(legacy_results, (str, bytes)) or not isinstance(legacy_results, Sequence):
        raise TemporalDerivationError("legacy_results must be a bounded sequence")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise TemporalDerivationError("limit must be between 1 and 100")
    legacy_values = tuple(
        signature
        for value in legacy_results[:limit]
        if (signature := _legacy_signature(value))
    )
    temporal_facts = store.facts_valid_at(
        at,
        scope=scope,
        subject=subject,
        predicate=predicate,
        actor_id=actor_id,
        surface=surface,
    )[:limit]
    temporal_values = tuple(_temporal_signature(fact) for fact in temporal_facts)
    legacy_set = set(legacy_values)
    temporal_set = set(temporal_values)
    union = legacy_set | temporal_set
    overlap = legacy_set & temporal_set
    return ShadowRecallComparison(
        legacy_count=len(legacy_values),
        temporal_count=len(temporal_values),
        overlap=tuple(sorted(overlap)),
        legacy_only=tuple(sorted(legacy_set - temporal_set)),
        temporal_only=tuple(sorted(temporal_set - legacy_set)),
        agreement_ratio=round(len(overlap) / len(union), 6) if union else 1.0,
        temporal_fact_ids=tuple(fact.id for fact in temporal_facts),
    )


__all__ = [
    "BoundedObservation",
    "DerivationOutcome",
    "ExtractedFact",
    "Extractor",
    "FactCandidate",
    "MAX_CANDIDATES",
    "MAX_OBSERVATIONS",
    "MAX_OBSERVATION_CHARS",
    "MAX_TOTAL_CHARS",
    "Relation",
    "ShadowRecallComparison",
    "TemporalDerivationError",
    "apply_candidates",
    "compare_shadow_recall",
    "derive_and_apply",
    "derive_candidates",
    "deterministic_extractor",
]
