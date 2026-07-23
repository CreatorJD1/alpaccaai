"""Additive runtime adapter for source-provenanced temporal memory.

This module ingests bounded observations, applies deterministic temporal
derivation in batches, and compares temporal recall with caller-owned legacy
results. It never selects or replaces the legacy recall path.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from threading import RLock
import time
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from alpecca.temporal_derivation import (
    BoundedObservation,
    DerivationOutcome,
    Extractor,
    MAX_OBSERVATIONS,
    MAX_OBSERVATION_CHARS,
    MAX_TOTAL_CHARS,
    ShadowRecallComparison,
    TemporalDerivationError,
    compare_shadow_recall,
    derive_and_apply,
)
from alpecca.temporal_memory import EvidenceObservation, TemporalMemoryStore


@dataclass(frozen=True, slots=True)
class ObservationProvenance:
    source: str
    channel: str
    actor_id: str
    scope: str


@dataclass(frozen=True, slots=True)
class ObservationIngestion:
    accepted: bool
    observation: EvidenceObservation | None
    provenance: ObservationProvenance
    queued: bool
    duplicate: bool = False
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class TemporalBatchResult:
    observation_uids: tuple[str, ...]
    outcomes: tuple[DerivationOutcome, ...]
    corrections: int
    supersessions: int
    contradictions: int
    closed_facts: int
    retried_observation_uids: tuple[str, ...] = ()
    dead_lettered_observation_uids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TemporalDeadLetter:
    """Redacted evidence that derivation exhausted its bounded retries."""

    source_observation_id: int
    source_content_sha256: str
    source_observation_uid_sha256: str
    attempts: int
    error_type: str
    evidence_observation_uid: str | None
    evidence_persisted: bool


@dataclass(frozen=True, slots=True)
class TemporalRuntimeStatus:
    pending_observations: int
    pending_capacity: int
    observations_ingested: int
    duplicate_observations: int
    rejected_observations: int
    observations_processed: int
    facts_derived: int
    corrections_applied: int
    supersessions_applied: int
    contradictions_linked: int
    facts_closed: int
    batches_completed: int
    batches_failed: int
    observations_retried: int
    observations_dead_lettered: int
    dead_letter_persistence_failures: int
    shadow_comparisons: int
    shadow_exact_agreements: int
    shadow_differences: int
    retrying_observations: int
    recent_dead_letters: int
    max_derivation_attempts: int
    pending_queue_rehydrated: bool
    restart_policy: str


class TemporalRuntime:
    """Pure orchestration over temporal storage and derivation APIs."""

    RESTART_POLICY = (
        "pending observation text is process-local and is not rehydrated after "
        "restart; hash-only dead-letter evidence persists, and retry requires "
        "the source observation to be submitted again"
    )

    def __init__(
        self,
        store: TemporalMemoryStore,
        *,
        max_pending: int = 64,
        max_batch: int = MAX_OBSERVATIONS,
        max_derivation_attempts: int = 3,
        extractor: Extractor | None = None,
    ) -> None:
        if not isinstance(store, TemporalMemoryStore):
            raise TypeError("store must be a TemporalMemoryStore")
        if type(max_pending) is not int or max_pending <= 0:
            raise ValueError("max_pending must be a positive integer")
        if type(max_batch) is not int or not 1 <= max_batch <= MAX_OBSERVATIONS:
            raise ValueError(
                f"max_batch must be between 1 and {MAX_OBSERVATIONS}"
            )
        if type(max_derivation_attempts) is not int or max_derivation_attempts <= 0:
            raise ValueError("max_derivation_attempts must be a positive integer")
        if extractor is not None and not callable(extractor):
            raise TypeError("extractor must be callable")
        self._store = store
        self._max_pending = max_pending
        self._max_batch = max_batch
        self._max_derivation_attempts = max_derivation_attempts
        self._extractor = extractor
        self._pending: deque[BoundedObservation] = deque()
        self._queued_observation_ids: set[int] = set()
        self._derivation_attempts: dict[int, int] = {}
        self._dead_letters: deque[TemporalDeadLetter] = deque(maxlen=max_pending)
        self._counts = {
            "observations_ingested": 0,
            "duplicate_observations": 0,
            "rejected_observations": 0,
            "observations_processed": 0,
            "facts_derived": 0,
            "corrections_applied": 0,
            "supersessions_applied": 0,
            "contradictions_linked": 0,
            "facts_closed": 0,
            "batches_completed": 0,
            "batches_failed": 0,
            "observations_retried": 0,
            "observations_dead_lettered": 0,
            "dead_letter_persistence_failures": 0,
            "shadow_comparisons": 0,
            "shadow_exact_agreements": 0,
            "shadow_differences": 0,
        }
        self._lock = RLock()

    def ingest_observation(
        self,
        text: str,
        *,
        source: str,
        channel: str,
        actor_id: str,
        scope: str,
        observed_at: float,
        observation_uid: str | None = None,
        raw_reference: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> ObservationIngestion:
        provenance = ObservationProvenance(
            source=self._text(source, "source"),
            channel=self._text(channel, "channel"),
            actor_id=self._text(actor_id, "actor_id"),
            scope=self._text(scope, "scope"),
        )
        clean_text = self._observation_text(text)
        observed = self._timestamp(observed_at, "observed_at")
        uid = (
            self._text(observation_uid, "observation_uid")
            if observation_uid is not None
            else self._observation_uid(clean_text, provenance, observed)
        )
        copied_metadata = MappingProxyType(dict(metadata or {}))

        with self._lock:
            if len(self._pending) >= self._max_pending:
                self._counts["rejected_observations"] += 1
                return ObservationIngestion(
                    accepted=False,
                    observation=None,
                    provenance=provenance,
                    queued=False,
                    reason="pending_capacity",
                )
            observation = self._store.record_observation(
                source=provenance.source,
                actor_id=provenance.actor_id,
                surface=provenance.channel,
                scope=provenance.scope,
                observed_at=observed,
                content=clean_text,
                observation_uid=uid,
                raw_reference=raw_reference,
                metadata=copied_metadata,
                recorded_at=observed,
            )
            if observation.id in self._queued_observation_ids:
                self._counts["duplicate_observations"] += 1
                return ObservationIngestion(
                    accepted=True,
                    observation=observation,
                    provenance=provenance,
                    queued=False,
                    duplicate=True,
                )
            bounded = BoundedObservation(observation, clean_text)
            self._pending.append(bounded)
            self._queued_observation_ids.add(observation.id)
            self._counts["observations_ingested"] += 1
            return ObservationIngestion(
                accepted=True,
                observation=observation,
                provenance=provenance,
                queued=True,
            )

    def process_batch(self, *, limit: int | None = None) -> TemporalBatchResult:
        selected_limit = self._max_batch if limit is None else limit
        if (
            type(selected_limit) is not int
            or not 1 <= selected_limit <= self._max_batch
        ):
            raise ValueError(f"limit must be between 1 and {self._max_batch}")

        with self._lock:
            batch = self._peek_batch(selected_limit)
            if not batch:
                return TemporalBatchResult((), (), 0, 0, 0, 0)

            processed: list[BoundedObservation] = []
            outcomes: list[DerivationOutcome] = []
            retried_uids: list[str] = []
            dead_lettered_uids: list[str] = []
            batch_had_failure = False

            # Isolate derivation per item. A poison observation is rotated behind
            # healthy work, then removed after a bounded number of attempts.
            for bounded in batch:
                removed = self._pending.popleft()
                assert removed is bounded
                observation_id = bounded.observation.id
                try:
                    item_outcomes = derive_and_apply(
                        self._store,
                        (bounded,),
                        extractor=self._extractor,
                    )
                except Exception as exc:
                    batch_had_failure = True
                    attempts = self._derivation_attempts.get(observation_id, 0) + 1
                    if attempts < self._max_derivation_attempts:
                        self._derivation_attempts[observation_id] = attempts
                        self._pending.append(bounded)
                        retried_uids.append(bounded.observation.observation_uid)
                        self._counts["observations_retried"] += 1
                    else:
                        self._derivation_attempts.pop(observation_id, None)
                        self._queued_observation_ids.remove(observation_id)
                        self._dead_letters.append(
                            self._dead_letter(bounded, attempts=attempts, error=exc)
                        )
                        dead_lettered_uids.append(
                            bounded.observation.observation_uid
                        )
                        self._counts["observations_dead_lettered"] += 1
                    continue

                self._derivation_attempts.pop(observation_id, None)
                self._queued_observation_ids.remove(observation_id)
                processed.append(bounded)
                outcomes.extend(item_outcomes)

            if batch_had_failure:
                self._counts["batches_failed"] += 1

            corrections = sum(
                outcome.candidate.relation == "correction" for outcome in outcomes
            )
            supersessions = sum(
                outcome.candidate.relation == "supersession" for outcome in outcomes
            )
            contradictions = sum(
                len(outcome.contradiction_links) for outcome in outcomes
            )
            closed_facts = sum(len(outcome.closed_fact_ids) for outcome in outcomes)
            self._counts["observations_processed"] += len(processed)
            self._counts["facts_derived"] += len(outcomes)
            self._counts["corrections_applied"] += corrections
            self._counts["supersessions_applied"] += supersessions
            self._counts["contradictions_linked"] += contradictions
            self._counts["facts_closed"] += closed_facts
            if processed:
                self._counts["batches_completed"] += 1
            return TemporalBatchResult(
                observation_uids=tuple(
                    item.observation.observation_uid for item in processed
                ),
                outcomes=tuple(outcomes),
                corrections=corrections,
                supersessions=supersessions,
                contradictions=contradictions,
                closed_facts=closed_facts,
                retried_observation_uids=tuple(retried_uids),
                dead_lettered_observation_uids=tuple(dead_lettered_uids),
            )

    def dead_letters(self) -> tuple[TemporalDeadLetter, ...]:
        """Return bounded, redacted dead letters observed by this runtime."""

        with self._lock:
            return tuple(self._dead_letters)

    def compare_shadow_recall(
        self,
        legacy_results: Sequence[object],
        *,
        at: float,
        scope: str,
        subject: str | None = None,
        predicate: str | None = None,
        actor_id: str | None = None,
        channel: str | None = None,
        limit: int = 20,
    ) -> ShadowRecallComparison:
        """Compare recall paths without mutating or selecting legacy results."""

        with self._lock:
            comparison = compare_shadow_recall(
                self._store,
                legacy_results,
                at=at,
                scope=scope,
                subject=subject,
                predicate=predicate,
                actor_id=actor_id,
                surface=channel,
                limit=limit,
            )
            self._counts["shadow_comparisons"] += 1
            if comparison.agreement_ratio == 1.0:
                self._counts["shadow_exact_agreements"] += 1
            else:
                self._counts["shadow_differences"] += 1
            return comparison

    def status(self) -> TemporalRuntimeStatus:
        with self._lock:
            return TemporalRuntimeStatus(
                pending_observations=len(self._pending),
                pending_capacity=self._max_pending,
                retrying_observations=len(self._derivation_attempts),
                recent_dead_letters=len(self._dead_letters),
                max_derivation_attempts=self._max_derivation_attempts,
                pending_queue_rehydrated=False,
                restart_policy=self.RESTART_POLICY,
                **self._counts,
            )

    def _dead_letter(
        self,
        bounded: BoundedObservation,
        *,
        attempts: int,
        error: Exception,
    ) -> TemporalDeadLetter:
        observation = bounded.observation
        error_type = type(error).__name__[:200] or "Exception"
        uid_digest = sha256(observation.observation_uid.encode("utf-8")).hexdigest()
        stamp = time.time()
        evidence_key = json.dumps(
            {
                "attempts": attempts,
                "error_type": error_type,
                "source_observation_id": observation.id,
                "stamp": stamp,
            },
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        evidence_uid = "temporal-dead-letter-" + sha256(
            evidence_key.encode("utf-8")
        ).hexdigest()
        persisted = True
        try:
            self._store.record_observation(
                source="temporal-derivation-dead-letter",
                actor_id="temporal-runtime",
                surface="temporal-runtime",
                scope=observation.scope,
                observed_at=stamp,
                content="temporal derivation dead-letter evidence",
                observation_uid=evidence_uid,
                metadata={
                    "attempts": attempts,
                    "error_type": error_type,
                    "kind": "temporal_derivation_dead_letter",
                    "pending_replay_on_restart": False,
                    "raw_content_retained": False,
                    "retry_limit": self._max_derivation_attempts,
                    "source_content_sha256": observation.content_sha256,
                    "source_observation_id": observation.id,
                    "source_observation_uid_sha256": uid_digest,
                },
                recorded_at=stamp,
            )
        except Exception:
            persisted = False
            evidence_uid = None
            self._counts["dead_letter_persistence_failures"] += 1
        return TemporalDeadLetter(
            source_observation_id=observation.id,
            source_content_sha256=observation.content_sha256,
            source_observation_uid_sha256=uid_digest,
            attempts=attempts,
            error_type=error_type,
            evidence_observation_uid=evidence_uid,
            evidence_persisted=persisted,
        )

    def _peek_batch(self, limit: int) -> tuple[BoundedObservation, ...]:
        selected: list[BoundedObservation] = []
        total_chars = 0
        for bounded in self._pending:
            if len(selected) >= limit:
                break
            next_total = total_chars + len(bounded.text)
            if next_total > MAX_TOTAL_CHARS:
                break
            selected.append(bounded)
            total_chars = next_total
        return tuple(selected)

    @staticmethod
    def _observation_uid(
        text: str,
        provenance: ObservationProvenance,
        observed_at: float,
    ) -> str:
        canonical = json.dumps(
            {
                "actor_id": provenance.actor_id,
                "channel": provenance.channel,
                "observed_at": observed_at,
                "scope": provenance.scope,
                "source": provenance.source,
                "text_sha256": sha256(text.encode("utf-8")).hexdigest(),
            },
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return "runtime-" + sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _observation_text(value: str) -> str:
        if not isinstance(value, str):
            raise TemporalDerivationError("observation text must be a string")
        if not value.strip():
            raise TemporalDerivationError("observation text must not be empty")
        if len(value) > MAX_OBSERVATION_CHARS:
            raise TemporalDerivationError(
                f"observation text exceeds {MAX_OBSERVATION_CHARS} characters"
            )
        return value

    @staticmethod
    def _text(value: object, name: str) -> str:
        result = " ".join(str(value or "").split())
        if not result:
            raise ValueError(f"{name} must not be empty")
        return result

    @staticmethod
    def _timestamp(value: object, name: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a finite timestamp")
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a finite timestamp") from None
        if not math.isfinite(result):
            raise ValueError(f"{name} must be a finite timestamp")
        return result


TemporalRuntimeAdapter = TemporalRuntime


__all__ = [
    "ObservationIngestion",
    "ObservationProvenance",
    "TemporalBatchResult",
    "TemporalDeadLetter",
    "TemporalRuntime",
    "TemporalRuntimeAdapter",
    "TemporalRuntimeStatus",
]
