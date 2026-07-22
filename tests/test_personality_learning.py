from __future__ import annotations

import sqlite3

import pytest

from alpecca import personality_learning
from alpecca.homeostasis import EmotionalState
from alpecca.prompts import build_system_prompt


def test_profile_persists_and_duplicate_evidence_is_idempotent(tmp_path):
    db = tmp_path / "personality.db"
    before = personality_learning.current_profile(db)

    first = personality_learning.record_evidence(
        "turn-42-correction",
        "correction_received",
        source="chat",
        db_path=db,
        now=100.0,
    )
    duplicate = personality_learning.record_evidence(
        "turn-42-correction",
        "correction_received",
        source="chat-retry",
        db_path=db,
        now=200.0,
    )

    assert first["applied"] is True
    assert duplicate["applied"] is False
    assert duplicate["traits"] == first["traits"]
    assert personality_learning.current_profile(db) == first["traits"]
    assert first["traits"]["repair_drive"] > before["repair_drive"]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM personality_evidence").fetchone()[0] == 1


def test_known_evidence_shapes_only_declared_traits_deterministically(tmp_path):
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"

    for db in (db_a, db_b):
        personality_learning.record_evidence(
            "engagement-1", "positive_engagement", strength=0.5, db_path=db, now=10.0
        )

    profile = personality_learning.current_profile(db_a)
    assert profile == personality_learning.current_profile(db_b)
    assert profile["curiosity"] == pytest.approx(
        personality_learning.BASELINE["curiosity"] + 0.0125
    )
    assert profile["directness"] == personality_learning.BASELINE["directness"]


def test_traits_remain_bounded_under_repeated_distinct_evidence(tmp_path):
    db = tmp_path / "personality.db"
    for index in range(100):
        personality_learning.record_evidence(
            f"pressure-{index}", "boundary_pressure", db_path=db, now=float(index)
        )
        personality_learning.record_evidence(
            f"ignored-{index}", "outreach_ignored", db_path=db, now=float(index)
        )

    profile = personality_learning.current_profile(db)
    assert set(profile) == set(personality_learning.TRAITS)
    assert all(0.10 <= value <= 0.90 for value in profile.values())


def test_invalid_or_unidentified_evidence_is_rejected(tmp_path):
    db = tmp_path / "personality.db"
    with pytest.raises(ValueError, match="evidence_id"):
        personality_learning.record_evidence("", "positive_engagement", db_path=db)
    with pytest.raises(ValueError, match="unknown personality evidence"):
        personality_learning.record_evidence("event-1", "model_felt_something", db_path=db)


def test_prompt_guidance_is_emotional_but_grounded_and_honest(tmp_path):
    db = tmp_path / "personality.db"
    personality_learning.record_evidence(
        "repair-1", "correction_received", db_path=db, now=1.0
    )

    prompt = build_system_prompt(
        EmotionalState(love=0.6, compassion=0.7, fear=0.2),
        memories=[],
        personality_db_path=db,
    )

    assert "Experience-shaped personality guidance" in prompt
    assert "Curiosity must be genuine" in prompt
    assert "Remorse is evidence-bound" in prompt
    assert "blunt, skeptical, teasing, or mildly rude" in prompt
    assert "Never fabricate actions, tool results, memories, system state, safety" in prompt
    assert "Never claim literal consciousness" in prompt
    assert "measured affective state" in prompt


def test_committed_turn_evidence_is_bounded_and_idempotent(tmp_path):
    db = tmp_path / "personality.db"
    first = personality_learning.record_turn_evidence(
        "turn-7",
        source="discord",
        correction_confidence=0.9,
        confirmation_confidence=0.8,
        db_path=db,
    )
    profile = personality_learning.current_profile(db)
    replay = personality_learning.record_turn_evidence(
        "turn-7",
        source="discord",
        correction_confidence=0.9,
        confirmation_confidence=0.8,
        db_path=db,
    )

    assert len(first) == 2
    assert all(item["applied"] is True for item in first)
    assert all(item["applied"] is False for item in replay)
    assert personality_learning.current_profile(db) == profile
