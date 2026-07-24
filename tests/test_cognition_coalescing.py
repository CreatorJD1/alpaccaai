from __future__ import annotations

import json

from alpecca import cognition


def test_identical_sensor_polls_coalesce_without_losing_occurrence_count(tmp_path):
    db = tmp_path / "cognition.db"
    cognition.init_db(db)
    first = cognition.CognitionObservation(
        source="senses",
        content="Battery state is unchanged.",
        room="system",
        metadata={"battery_percent": 80},
        ts=100.0,
    )
    second = cognition.CognitionObservation(
        source="senses",
        content="Battery state is unchanged.",
        room="system",
        metadata={"battery_percent": 80},
        ts=120.0,
    )

    first_id = cognition.record_observation(first, db)
    second_id = cognition.record_observation(second, db)

    assert second_id == first_id
    with cognition._connect(db) as conn:
        rows = conn.execute("SELECT ts,metadata FROM cognition_observations").fetchall()
    assert len(rows) == 1
    metadata = json.loads(rows[0]["metadata"])
    assert rows[0]["ts"] == 120.0
    assert metadata["coalesced_occurrences"] == 2
    assert metadata["coalesced_first_ts"] == 100.0
    assert metadata["coalesced_last_ts"] == 120.0


def test_changed_sensor_evidence_and_human_chat_remain_distinct(tmp_path):
    db = tmp_path / "cognition.db"
    cognition.init_db(db)
    observations = (
        cognition.CognitionObservation(
            source="senses",
            content="Battery state is unchanged.",
            metadata={"battery_percent": 80},
            ts=100.0,
        ),
        cognition.CognitionObservation(
            source="senses",
            content="Battery state is unchanged.",
            metadata={"battery_percent": 79},
            ts=110.0,
        ),
        cognition.CognitionObservation(source="chat", content="Hello", ts=120.0),
        cognition.CognitionObservation(source="chat", content="Hello", ts=121.0),
    )
    ids = [cognition.record_observation(obs, db) for obs in observations]

    assert len(set(ids)) == 4


def test_sensor_poll_after_coalesce_window_is_a_new_observation(tmp_path):
    db = tmp_path / "cognition.db"
    cognition.init_db(db)
    first = cognition.CognitionObservation(source="host_resources", content="Stable", ts=10.0)
    later = cognition.CognitionObservation(
        source="host_resources",
        content="Stable",
        ts=10.0 + cognition.OBSERVATION_COALESCE_SECONDS + 0.1,
    )

    assert cognition.record_observation(first, db) != cognition.record_observation(later, db)
