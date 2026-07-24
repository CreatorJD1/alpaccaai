from __future__ import annotations

import sqlite3
from pathlib import Path

from alpecca.temporal_memory import (
    OBSERVATIONS_TABLE,
    TemporalMemoryStore,
)
from alpecca.temporal_runtime import TemporalRuntime


def _source_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                room TEXT,
                user_text TEXT NOT NULL,
                reply TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'shared'
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'shared'
            );
            """
        )


def test_committed_evidence_derivation_is_bounded_and_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "activation.db"
    store = TemporalMemoryStore(db)
    _source_db(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO chat_turns(ts,room,user_text,reply,scope) VALUES(?,?,?,?,?)",
            (1.0, "house", "ordinary conversation", "ordinary reply", "creator"),
        )
        conn.execute(
            "INSERT INTO chat_turns(ts,room,user_text,reply,scope) VALUES(?,?,?,?,?)",
            (2.0, "house", "fact: Alpecca | home | House HQ", "noted", "creator"),
        )
        conn.execute(
            "INSERT INTO memories(ts,kind,content,scope) VALUES(?,?,?,?)",
            (3.0, "semantic", "fact: Jason | role | creator", "creator"),
        )

    runtime = TemporalRuntime(store)
    first = runtime.derive_committed_evidence(max_rows=8)
    replay = runtime.derive_committed_evidence(max_rows=8)

    assert first.scanned_rows == 3
    assert first.eligible_rows == 2
    assert first.ingested_rows == 2
    assert first.facts_derived == 2
    assert first.exhausted
    assert replay.scanned_rows == 0
    assert replay.facts_derived == 0
    assert len(store.facts_valid_at(3.0, scope="creator")) == 2
    with sqlite3.connect(db) as conn:
        observations = conn.execute(
            f"SELECT count(*) FROM {OBSERVATIONS_TABLE}"
        ).fetchone()
    assert observations == (2,)


def test_uncommitted_source_row_is_not_derived(tmp_path: Path) -> None:
    db = tmp_path / "uncommitted.db"
    store = TemporalMemoryStore(db)
    _source_db(db)
    writer = sqlite3.connect(db)
    try:
        writer.execute("BEGIN")
        writer.execute(
            "INSERT INTO memories(ts,kind,content,scope) VALUES(?,?,?,?)",
            (1.0, "semantic", "fact: hidden | state | uncommitted", "creator"),
        )
        result = TemporalRuntime(store).derive_committed_evidence(max_rows=4)
        assert result.scanned_rows == 0
        assert result.facts_derived == 0
    finally:
        writer.rollback()
        writer.close()


def test_cancelled_scan_checkpoints_only_completed_rows_then_resumes(
    tmp_path: Path,
) -> None:
    db = tmp_path / "cancel.db"
    store = TemporalMemoryStore(db)
    _source_db(db)
    with sqlite3.connect(db) as conn:
        for index in range(1, 4):
            conn.execute(
                "INSERT INTO memories(ts,kind,content,scope) VALUES(?,?,?,?)",
                (float(index), "semantic", f"fact: item{index} | state | kept", "creator"),
            )

    checks = 0

    def cancel_after_one() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    runtime = TemporalRuntime(store)
    partial = runtime.derive_committed_evidence(
        max_rows=8,
        cancelled=cancel_after_one,
    )
    resumed = runtime.derive_committed_evidence(max_rows=8)

    assert partial.cancelled
    assert partial.scanned_rows == 1
    assert partial.source_cursors["committed_memory"] == 1
    assert resumed.scanned_rows == 2
    assert resumed.facts_derived == 2
    assert len(store.facts_valid_at(3.0, scope="creator")) == 3


def test_retention_removes_only_old_unreferenced_observations(tmp_path: Path) -> None:
    store = TemporalMemoryStore(tmp_path / "retention.db")
    runtime = TemporalRuntime(store)
    linked = runtime.ingest_observation(
        "fact: Alpecca | status | learning",
        source="test",
        channel="house",
        actor_id="creator",
        scope="creator",
        observed_at=1.0,
        observation_uid="linked",
    )
    runtime.process_batch(limit=1)
    unlinked = store.record_observation(
        source="test",
        actor_id="creator",
        surface="house",
        scope="creator",
        observed_at=1.0,
        content="ordinary old evidence",
        observation_uid="unlinked",
        recorded_at=1.0,
    )

    assert store.prune_unreferenced_observations(before=10.0, limit=1) == 1
    assert store.evidence_for_fact(
        store.facts_valid_at(2.0, scope="creator")[0].id
    )[0].id == linked.observation.id
    with sqlite3.connect(store.db_path) as conn:
        remaining = {
            row[0]
            for row in conn.execute(f"SELECT id FROM {OBSERVATIONS_TABLE}")
        }
    assert linked.observation.id in remaining
    assert unlinked.id not in remaining
