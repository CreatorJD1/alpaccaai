from __future__ import annotations

from hashlib import sha256
import json
import sqlite3
from pathlib import Path

import pytest

from alpecca.temporal_derivation import ExtractedFact
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


def test_failed_item_retries_without_blocking_later_observation(
    tmp_path: Path,
) -> None:
    attempts: dict[str, int] = {}

    def selective_extractor(observation):
        attempts[observation.text] = attempts.get(observation.text, 0) + 1
        if observation.text == "private malformed payload":
            return ["not-an-extracted-fact"]
        return [
            ExtractedFact(
                subject="project",
                predicate="status",
                object_text="healthy",
                confidence=0.9,
            )
        ]

    adapter = runtime(
        tmp_path,
        max_batch=2,
        max_derivation_attempts=2,
        extractor=selective_extractor,
    )
    ingest(adapter, "private malformed payload", uid="invalid", observed_at=1.0)
    ingest(adapter, "healthy observation", uid="healthy", observed_at=2.0)

    first = adapter.process_batch()

    status = adapter.status()
    assert first.observation_uids == ("healthy",)
    assert first.retried_observation_uids == ("invalid",)
    assert first.dead_lettered_observation_uids == ()
    assert status.pending_observations == 1
    assert status.retrying_observations == 1
    assert status.observations_processed == 1
    assert status.facts_derived == 1
    assert status.batches_completed == 1
    assert status.batches_failed == 1
    assert attempts == {
        "private malformed payload": 1,
        "healthy observation": 1,
    }


def test_retry_exhaustion_dead_letters_redacted_evidence_and_recovers_capacity(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "temporal-runtime.db"

    def invalid_extractor(observation):
        return ["not-an-extracted-fact"]

    adapter = TemporalRuntime(
        TemporalMemoryStore(db_path),
        max_pending=1,
        max_derivation_attempts=2,
        extractor=invalid_extractor,
    )
    secret = "private malformed payload that must not enter dead-letter metadata"
    source = ingest(adapter, secret, uid="private-source")
    assert source.observation is not None

    first = adapter.process_batch()
    second = adapter.process_batch()

    assert first.retried_observation_uids == ("private-source",)
    assert second.dead_lettered_observation_uids == ("private-source",)
    status = adapter.status()
    assert status.pending_observations == 0
    assert status.retrying_observations == 0
    assert status.observations_retried == 1
    assert status.observations_dead_lettered == 1
    assert status.recent_dead_letters == 1
    assert status.dead_letter_persistence_failures == 0
    assert status.batches_failed == 2

    dead_letter = adapter.dead_letters()[0]
    assert dead_letter.source_observation_id == source.observation.id
    assert dead_letter.source_content_sha256 == sha256(secret.encode()).hexdigest()
    assert dead_letter.source_observation_uid_sha256 == sha256(
        b"private-source"
    ).hexdigest()
    assert dead_letter.attempts == 2
    assert dead_letter.error_type == "TemporalDerivationError"
    assert dead_letter.evidence_persisted
    assert dead_letter.evidence_observation_uid is not None

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            f"SELECT raw_reference, metadata_json FROM {OBSERVATIONS_TABLE} "
            "WHERE source='temporal-derivation-dead-letter'"
        ).fetchone()
    assert row is not None
    assert row[0] == ""
    assert secret not in row[1]
    assert "private-source" not in row[1]
    metadata = json.loads(row[1])
    assert metadata == {
        "attempts": 2,
        "error_type": "TemporalDerivationError",
        "kind": "temporal_derivation_dead_letter",
        "pending_replay_on_restart": False,
        "raw_content_retained": False,
        "retry_limit": 2,
        "source_content_sha256": sha256(secret.encode()).hexdigest(),
        "source_observation_id": source.observation.id,
        "source_observation_uid_sha256": sha256(b"private-source").hexdigest(),
    }

    accepted_after_exhaustion = ingest(
        adapter,
        "another malformed observation",
        uid="replacement",
        observed_at=200.0,
    )
    assert accepted_after_exhaustion.accepted
    assert accepted_after_exhaustion.queued


def test_restart_does_not_claim_to_rehydrate_unstored_pending_text(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "temporal-runtime.db"

    def invalid_extractor(observation):
        return ["not-an-extracted-fact"]

    first_runtime = TemporalRuntime(
        TemporalMemoryStore(db_path),
        max_derivation_attempts=1,
        extractor=invalid_extractor,
    )
    ingest(first_runtime, "private source text", uid="source")
    first_runtime.process_batch()
    assert first_runtime.status().observations_dead_lettered == 1

    restarted = TemporalRuntime(TemporalMemoryStore(db_path))
    status = restarted.status()

    assert status.pending_observations == 0
    assert not status.pending_queue_rehydrated
    assert "not rehydrated" in status.restart_policy
    assert "submitted again" in status.restart_policy
    assert status.observations_dead_lettered == 0
    assert restarted.dead_letters() == ()
    with sqlite3.connect(db_path) as conn:
        persisted = conn.execute(
            f"SELECT count(*) FROM {OBSERVATIONS_TABLE} "
            "WHERE source='temporal-derivation-dead-letter'"
        ).fetchone()
    assert persisted == (1,)


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "3"])
def test_max_derivation_attempts_must_be_a_positive_integer(
    tmp_path: Path,
    value: object,
) -> None:
    with pytest.raises(ValueError, match="max_derivation_attempts"):
        runtime(tmp_path, max_derivation_attempts=value)


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
