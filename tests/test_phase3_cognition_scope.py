"""Focused Phase 3 persistence boundaries for chat and cognition records."""

from __future__ import annotations

from alpecca import cognition


def test_cognition_records_are_filtered_to_their_turn_scope(tmp_path):
    db_path = tmp_path / "alpecca.db"
    cognition.init_db(db_path)

    creator_observation = cognition.record_observation(
        cognition.CognitionObservation(
            source="chat",
            content="creator-only observation",
            scope="creator-personal",
            privacy_class="creator-personal",
        ),
        db_path=db_path,
    )
    guest_observation = cognition.record_observation(
        cognition.CognitionObservation(
            source="chat",
            content="guest-only observation",
            scope="guest-conversation-a",
            privacy_class="guest-conversation-a",
        ),
        db_path=db_path,
    )
    creator_turn = cognition.record_chat_turn(
        cognition.ChatTurn(
            user_text="creator question",
            reply="creator reply",
            observation_id=creator_observation,
            scope="creator-personal",
            privacy_class="creator-personal",
        ),
        db_path=db_path,
    )
    guest_turn = cognition.record_chat_turn(
        cognition.ChatTurn(
            user_text="guest question",
            reply="guest reply",
            observation_id=guest_observation,
            scope="guest-conversation-a",
            privacy_class="guest-conversation-a",
        ),
        db_path=db_path,
    )

    assert creator_observation and guest_observation and creator_turn and guest_turn
    assert [row["content"] for row in cognition.recent_observations(
        db_path=db_path, scope="creator-personal"
    )] == ["creator-only observation"]
    assert [row["content"] for row in cognition.recent_observations(
        db_path=db_path, scope="guest-conversation-a"
    )] == ["guest-only observation"]
    assert [row["user_text"] for row in cognition.recent_chat_turns(
        db_path=db_path, scope="creator-personal"
    )] == ["creator question"]
    assert [row["user_text"] for row in cognition.recent_chat_turns(
        db_path=db_path, scope="guest-conversation-a"
    )] == ["guest question"]
    assert cognition.recent_observations(db_path=db_path) == []
    assert cognition.recent_chat_turns(db_path=db_path) == []


def test_old_cognition_rows_migrate_to_shared_scope(tmp_path):
    db_path = tmp_path / "legacy.db"
    cognition.init_db(db_path)

    observation_id = cognition.record_observation(
        cognition.CognitionObservation(source="system", content="shared observation"),
        db_path=db_path,
    )
    cognition.record_chat_turn(
        cognition.ChatTurn(
            user_text="shared question",
            reply="shared reply",
            observation_id=observation_id,
        ),
        db_path=db_path,
    )

    assert cognition.recent_observations(db_path=db_path)[0]["scope"] == "shared"
    assert cognition.recent_chat_turns(db_path=db_path)[0]["scope"] == "shared"


def test_recent_chat_turns_filters_surface_before_applying_limit(tmp_path):
    db_path = tmp_path / "surfaces.db"
    cognition.init_db(db_path)
    cognition.record_chat_turn(
        cognition.ChatTurn(
            user_text="older house message",
            reply="house reply",
            scope="creator-personal",
            model_use={"turn": {"surface": "house-hq"}},
        ),
        db_path=db_path,
    )
    for index in range(60):
        cognition.record_chat_turn(
            cognition.ChatTurn(
                user_text=f"discord message {index}",
                reply="discord reply",
                scope="creator-personal",
                model_use={"turn": {"surface": "discord"}},
            ),
            db_path=db_path,
        )

    turns = cognition.recent_chat_turns(
        limit=4,
        scope="creator-personal",
        surface="house-hq",
        db_path=db_path,
    )

    assert [turn["user_text"] for turn in turns] == ["older house message"]
