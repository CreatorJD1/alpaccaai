from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from alpecca.temporal_derivation import ExtractedFact, TemporalDerivationError
from alpecca.temporal_memory import (
    OBSERVATIONS_TABLE,
    TemporalMemoryStore,
)
from alpecca.temporal_runtime import TemporalRuntime


def runtime(tmp_path: Path, **kwargs: object) -> TemporalRuntime:
    store = TemporalMemoryStore(tmp_path / "temporal-runtime.db")
    return TemporalRuntime(store, **kwargs)


def ingest(
    adapter: TemporalRuntime,
    text: str,
    *,
    observed_at: float = 100.0,
    uid: str | None = None,
    source: str = "discord-message",
    channel: str = "creator-dm",
    actor_id: str = "creator-jason",
    scope: str = "creator",
):
    return adapter.ingest_observation(
        text,
        source=source,
        channel=channel,
        actor_id=actor_id,
        scope=scope,
        observed_at=observed_at,
        observation_uid=uid,
    )


def test_ingestion_preserves_source_channel_actor_and_scope(tmp_path: Path) -> None:
    adapter = runtime(tmp_path)
    result = adapter.ingest_observation(
        "fact: Jason | works_in | California",
        source="discord-attachment-caption",
        channel="creator-dm",
        actor_id="creator-jason",
        scope="creator",
        observed_at=900.0,
        raw_reference="discord-message:42",
        metadata={"guild": "direct"},
    )

    assert result.accepted and result.queued
    assert result.observation is not None
    assert result.provenance.source == "discord-attachment-caption"
    assert result.provenance.channel == "creator-dm"
    assert result.provenance.actor_id == "creator-jason"
    assert result.observation.source == "discord-attachment-caption"
    assert result.observation.surface == "creator-dm"
    assert result.observation.actor_id == "creator-jason"
    assert result.observation.scope == "creator"
    assert result.observation.raw_reference == "discord-message:42"
    assert result.observation.metadata == {"guild": "direct"}
    assert result.observation.recorded_at == 900.0


def test_default_observation_uid_is_deterministic_and_queued_once(
    tmp_path: Path,
) -> None:
    adapter = runtime(tmp_path)
    first = ingest(adapter, "fact: project | status | active")
    duplicate = ingest(adapter, "fact: project | status | active")

    assert first.observation is not None and duplicate.observation is not None
    assert first.observation.observation_uid.startswith("runtime-")
    assert duplicate.observation.id == first.observation.id
    assert duplicate.accepted and duplicate.duplicate
    assert not duplicate.queued
    assert adapter.status().pending_observations == 1
    assert adapter.status().duplicate_observations == 1


def test_pending_capacity_rejects_before_recording_evidence(tmp_path: Path) -> None:
    db_path = tmp_path / "temporal-runtime.db"
    adapter = TemporalRuntime(TemporalMemoryStore(db_path), max_pending=1)
    accepted = ingest(adapter, "fact: one | state | ready", uid="one")
    rejected = ingest(adapter, "fact: two | state | waiting", uid="two")

    assert accepted.accepted
    assert not rejected.accepted
    assert rejected.reason == "pending_capacity"
    assert rejected.observation is None
    with sqlite3.connect(db_path) as conn:
        count = conn.execute(f"SELECT count(*) FROM {OBSERVATIONS_TABLE}").fetchone()
    assert count == (1,)
    assert adapter.status().rejected_observations == 1


def test_batch_limit_processes_fifo_and_updates_counters(tmp_path: Path) -> None:
    adapter = runtime(tmp_path, max_batch=2)
    ingest(adapter, "fact: one | state | ready", uid="one", observed_at=1.0)
    ingest(adapter, "fact: two | state | ready", uid="two", observed_at=2.0)
    ingest(adapter, "fact: three | state | ready", uid="three", observed_at=3.0)

    first = adapter.process_batch()
    second = adapter.process_batch()

    assert first.observation_uids == ("one", "two")
    assert second.observation_uids == ("three",)
    assert len(first.outcomes) == 2
    assert len(second.outcomes) == 1
    status = adapter.status()
    assert status.pending_observations == 0
    assert status.observations_ingested == 3
    assert status.observations_processed == 3
    assert status.facts_derived == 3
    assert status.batches_completed == 2


def test_batch_respects_derivation_total_character_bound(tmp_path: Path) -> None:
    adapter = runtime(tmp_path, max_pending=8)
    for index in range(5):
        ingest(
            adapter,
            "x" * 4_000,
            uid=f"long-{index}",
            observed_at=float(index + 1),
        )

    first = adapter.process_batch()
    second = adapter.process_batch()

    assert len(first.observation_uids) == 4
    assert len(second.observation_uids) == 1
    assert first.outcomes == ()
    assert adapter.status().observations_processed == 5


def test_correction_closes_prior_fact_and_is_counted(tmp_path: Path) -> None:
    adapter = runtime(tmp_path)
    ingest(
        adapter,
        "fact: Jason | works_in | California | 0.8",
        uid="original",
        observed_at=10.0,
    )
    original = adapter.process_batch().outcomes[0]
    ingest(
        adapter,
        "correction: Jason | works_in | Oregon | 0.95",
        uid="correction",
        observed_at=20.0,
    )
    correction = adapter.process_batch()

    assert correction.corrections == 1
    assert correction.contradictions == 1
    assert correction.closed_facts == 1
    assert correction.outcomes[0].closed_fact_ids == (original.fact.id,)
    status = adapter.status()
    assert status.corrections_applied == 1
    assert status.contradictions_linked == 1
    assert status.facts_closed == 1


def test_asserted_contradiction_links_without_closing_prior_fact(
    tmp_path: Path,
) -> None:
    store = TemporalMemoryStore(tmp_path / "temporal-runtime.db")
    adapter = TemporalRuntime(store)
    ingest(
        adapter,
        "fact: Jason | works_in | California",
        uid="original",
        observed_at=10.0,
    )
    original = adapter.process_batch().outcomes[0]
    ingest(
        adapter,
        "contradiction: Jason | works_in | Oregon",
        uid="conflict",
        observed_at=20.0,
    )
    conflict = adapter.process_batch()

    assert conflict.contradictions == 1
    assert conflict.closed_facts == 0
    active = store.facts_valid_at(
        20.0,
        scope="creator",
        subject="Jason",
        predicate="works_in",
    )
    assert {fact.id for fact in active} == {
        original.fact.id,
        conflict.outcomes[0].fact.id,
    }


def test_custom_extractor_cannot_replace_observation_provenance(
    tmp_path: Path,
) -> None:
    def extractor(observation):
        return [
            ExtractedFact(
                subject="project",
                predicate="status",
                object_text="active",
                confidence=0.9,
            )
        ]

    store = TemporalMemoryStore(tmp_path / "temporal-runtime.db")
    adapter = TemporalRuntime(store, extractor=extractor)
    ingest(
        adapter,
        "unstructured statement",
        source="house-observer",
        channel="house-library",
        actor_id="creator-jason",
        scope="creator",
    )
    outcome = adapter.process_batch().outcomes[0]

    assert outcome.fact.actor_id == "creator-jason"
    assert outcome.fact.surface == "house-library"
    assert outcome.fact.scope == "creator"
    evidence = store.evidence_for_fact(outcome.fact.id)[0]
    assert evidence.source == "house-observer"


def test_failed_batch_remains_pending_and_increments_failure_counter(
    tmp_path: Path,
) -> None:
    def invalid_extractor(observation):
        return ["not-an-extracted-fact"]

    adapter = runtime(tmp_path, extractor=invalid_extractor)
    ingest(adapter, "unstructured statement", uid="invalid")

    with pytest.raises(TemporalDerivationError, match="ExtractedFact"):
        adapter.process_batch()

    status = adapter.status()
    assert status.pending_observations == 1
    assert status.observations_processed == 0
    assert status.batches_completed == 0
    assert status.batches_failed == 1


def test_shadow_comparison_is_read_only_and_never_replaces_legacy(
    tmp_path: Path,
) -> None:
    adapter = runtime(tmp_path)
    ingest(
        adapter,
        "fact: Jason | works_in | California",
        observed_at=100.0,
    )
    adapter.process_batch()
    legacy = [
        {"subject": "Jason", "predicate": "works_in", "object": "California"},
        {"subject": "Alpecca", "predicate": "room", "object": "Library"},
    ]
    original = [dict(item) for item in legacy]

    comparison = adapter.compare_shadow_recall(
        legacy,
        at=100.0,
        scope="creator",
        subject="Jason",
        predicate="works_in",
        channel="creator-dm",
    )

    assert comparison.overlap == ("jason | works_in | california",)
    assert comparison.legacy_only == ("alpecca | room | library",)
    assert comparison.temporal_only == ()
    assert comparison.agreement_ratio == 0.5
    assert legacy == original
    status = adapter.status()
    assert status.shadow_comparisons == 1
    assert status.shadow_exact_agreements == 0
    assert status.shadow_differences == 1


def test_empty_batch_is_a_noop_and_does_not_increment_counters(
    tmp_path: Path,
) -> None:
    adapter = runtime(tmp_path)
    result = adapter.process_batch()

    assert result.observation_uids == ()
    assert result.outcomes == ()
    assert adapter.status().batches_completed == 0
