from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from alpecca import temporal_memory


def _store(tmp_path: Path) -> temporal_memory.TemporalMemoryStore:
    return temporal_memory.TemporalMemoryStore(tmp_path / "temporal.db")


def _observation(
    store: temporal_memory.TemporalMemoryStore,
    *,
    uid: str = "observation-1",
    scope: str = "creator",
    content: str = "Jason works in California",
) -> temporal_memory.EvidenceObservation:
    return store.record_observation(
        observation_uid=uid,
        source="authenticated_input",
        actor_id="creator-jd",
        surface="house-hq",
        scope=scope,
        observed_at=100.0,
        content=content,
        raw_reference="turn:abc123",
        metadata={"transport": "typed"},
        recorded_at=101.0,
    )


def _fact(
    store: temporal_memory.TemporalMemoryStore,
    observation_id: int,
    *,
    uid: str = "fact-1",
    object_text: str = "California",
    valid_from: float = 100.0,
    scope: str = "creator",
) -> temporal_memory.TemporalFact:
    return store.record_fact(
        fact_uid=uid,
        subject="Jason",
        predicate="works_in",
        object_text=object_text,
        confidence=0.82,
        actor_id="creator-jd",
        surface="house-hq",
        scope=scope,
        valid_from=valid_from,
        evidence_observation_ids=[observation_id],
        recorded_at=101.0,
    )


def test_schema_is_idempotent_and_contains_temporal_provenance_tables(tmp_path: Path):
    db_path = tmp_path / "temporal.db"
    temporal_memory.init_db(db_path)
    temporal_memory.init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        fact_columns = {
            row[1] for row in conn.execute(
                f"PRAGMA table_info({temporal_memory.FACTS_TABLE})"
            )
        }

    assert {
        temporal_memory.FACTS_TABLE,
        temporal_memory.OBSERVATIONS_TABLE,
        temporal_memory.EVIDENCE_TABLE,
        temporal_memory.CONTRADICTIONS_TABLE,
    } <= tables
    assert {
        "subject", "predicate", "object_text", "confidence", "actor_id",
        "surface", "scope", "valid_from", "valid_to", "invalidated_at",
        "primary_observation_id",
    } <= fact_columns


def test_fact_retains_hashed_source_provenance_and_validity_window(tmp_path: Path):
    store = _store(tmp_path)
    observation = _observation(store)
    fact = _fact(store, observation.id)

    assert observation.content_sha256 == hashlib.sha256(
        b"Jason works in California"
    ).hexdigest()
    assert observation.metadata == {"transport": "typed"}
    assert fact.primary_observation_id == observation.id
    assert store.evidence_for_fact(fact.id) == [observation]
    assert store.facts_valid_at(100.0, scope="creator") == [fact]
    assert store.facts_valid_at(99.999, scope="creator") == []
    assert store.facts_valid_at(100.0, scope="guest") == []

    closed = store.close_validity(fact.id, valid_to=200.0, invalidated_at=201.0)
    assert closed.valid_to == 200.0
    assert closed.invalidated_at == 201.0
    assert store.facts_valid_at(199.999, scope="creator") == [closed]
    assert store.facts_valid_at(200.0, scope="creator") == []
    repeated = store.close_validity(
        fact.id, valid_to=200.0, invalidated_at=202.0
    )
    assert repeated.valid_to == 200.0
    assert repeated.invalidated_at == 201.0
    with pytest.raises(temporal_memory.TemporalMemoryConflict):
        store.close_validity(fact.id, valid_to=300.0)


def test_observation_idempotency_rejects_uid_rebinding(tmp_path: Path):
    store = _store(tmp_path)
    first = _observation(store)
    assert _observation(store) == first

    with pytest.raises(temporal_memory.TemporalMemoryConflict):
        _observation(store, content="different evidence")


def test_fact_uid_cannot_be_rebound_to_different_provenance(tmp_path: Path):
    store = _store(tmp_path)
    first_observation = _observation(store)
    second_observation = _observation(
        store, uid="observation-2", content="corroborating evidence",
    )
    first = _fact(store, first_observation.id)
    assert _fact(store, first_observation.id) == first

    with pytest.raises(temporal_memory.TemporalMemoryConflict, match="provenance"):
        store.record_fact(
            fact_uid="fact-1",
            subject="Jason",
            predicate="works_in",
            object_text="California",
            confidence=0.82,
            actor_id="creator-jd",
            surface="house-hq",
            scope="creator",
            valid_from=100.0,
            evidence_observation_ids=[first_observation.id, second_observation.id],
            recorded_at=101.0,
        )


def test_fact_requires_same_scope_evidence_and_valid_values(tmp_path: Path):
    store = _store(tmp_path)
    guest_observation = _observation(store, scope="guest")

    with pytest.raises(temporal_memory.TemporalMemoryError, match="same scope"):
        _fact(store, guest_observation.id, scope="creator")
    with pytest.raises(temporal_memory.TemporalMemoryError, match="between 0 and 1"):
        store.record_fact(
            subject="Jason", predicate="works_in", object_text="California",
            confidence=1.1, actor_id="creator-jd", surface="house-hq",
            scope="guest", valid_from=100.0,
            evidence_observation_ids=[guest_observation.id],
        )
    with pytest.raises(temporal_memory.TemporalMemoryError, match="later"):
        store.record_fact(
            subject="Jason", predicate="works_in", object_text="California",
            confidence=0.5, actor_id="creator-jd", surface="house-hq",
            scope="guest", valid_from=100.0, valid_to=100.0,
            evidence_observation_ids=[guest_observation.id],
        )


def test_contradictions_are_canonical_idempotent_and_scope_bounded(tmp_path: Path):
    store = _store(tmp_path)
    first_observation = _observation(store)
    second_observation = _observation(
        store,
        uid="observation-2",
        content="Jason now works in Oregon",
    )
    first = _fact(store, first_observation.id)
    second = _fact(
        store,
        second_observation.id,
        uid="fact-2",
        object_text="Oregon",
        valid_from=200.0,
    )

    link = store.link_contradiction(
        second.id,
        first.id,
        reason="new location conflicts with prior location",
        observation_id=second_observation.id,
        linked_at=202.0,
    )
    repeated = store.link_contradiction(
        first.id,
        second.id,
        reason="new location conflicts with prior location",
        observation_id=second_observation.id,
        linked_at=999.0,
    )

    assert repeated == link
    assert (link.fact_id, link.contradicts_fact_id) == (first.id, second.id)
    assert store.contradictions_for_fact(first.id) == [link]
    assert store.contradictions_for_fact(second.id) == [link]

    guest_observation = _observation(
        store, uid="guest-observation", scope="guest", content="guest claim",
    )
    guest_fact = _fact(
        store, guest_observation.id, uid="guest-fact", scope="guest",
    )
    with pytest.raises(temporal_memory.TemporalMemoryError, match="scopes"):
        store.link_contradiction(first.id, guest_fact.id)


def test_partial_legacy_schema_is_migrated_additively(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"CREATE TABLE {temporal_memory.FACTS_TABLE} "
            "(id INTEGER PRIMARY KEY, subject TEXT NOT NULL)"
        )
        conn.execute(
            f"INSERT INTO {temporal_memory.FACTS_TABLE} (id, subject) "
            "VALUES (7, 'preserved legacy subject')"
        )

    temporal_memory.init_db(db_path)
    temporal_memory.init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT * FROM {temporal_memory.FACTS_TABLE} WHERE id=7"
        ).fetchone()
        assert row is not None
        assert row["subject"] == "preserved legacy subject"
        assert row["fact_uid"] == "legacy-fact-7"
        columns = {
            item["name"] for item in conn.execute(
                f"PRAGMA table_info({temporal_memory.FACTS_TABLE})"
            )
        }
        assert "valid_from" in columns
        assert "primary_observation_id" in columns
