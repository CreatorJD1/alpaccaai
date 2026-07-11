"""Focused runtime baselines for Phase 8 behavior-review wiring."""
from __future__ import annotations

import pytest

from alpecca import proactive
from alpecca.homeostasis import EmotionalState


def _eligible_chatter_args(now: float = 10_000.0) -> dict[str, float]:
    return {
        "now": now,
        "last_user_ts": 0.0,
        "last_unprompted_ts": 0.0,
    }


def _bare_mind():
    """Build only the state the reviewed tick paths need; avoid shared DB setup."""
    from alpecca import mind as mind_mod

    mind = mind_mod.CoreMind.__new__(mind_mod.CoreMind)
    mind.state = EmotionalState(love=0.55, social_hunger=0.35)
    mind._location = "workshop"
    return mind, mind_mod


def _forbid_legacy_selfmod(monkeypatch, mind_mod) -> None:
    def unexpected(name):
        def fail(*_args, **_kwargs):
            pytest.fail(f"legacy selfmod.{name} must not run from a CoreMind tick")

        return fail

    for name in ("propose", "evaluate", "choose_experiment"):
        monkeypatch.setattr(mind_mod.selfmod, name, unexpected(name))


def test_chatter_chance_override_changes_only_probability_and_default_uses_config(
    monkeypatch,
):
    monkeypatch.setattr(proactive.ProactiveCfg, "CHATTER_CHANCE", 0.40)
    eligible = _eligible_chatter_args()

    assert proactive.should_chatter(**eligible, roll=0.39)
    assert not proactive.should_chatter(**eligible, roll=0.40)

    assert not proactive.should_chatter(**eligible, roll=0.39, chance=0.20)
    assert proactive.should_chatter(**eligible, roll=0.19, chance=0.20)
    assert proactive.should_chatter(**eligible, roll=0.39)
    assert proactive.ProactiveCfg.CHATTER_CHANCE == 0.40

    now = eligible["now"]
    assert not proactive.should_chatter(
        now,
        now - proactive.ProactiveCfg.CHATTER_SILENCE_S + 1,
        0.0,
        roll=0.0,
        chance=1.0,
    )
    assert not proactive.should_chatter(
        now,
        0.0,
        now - proactive.ProactiveCfg.CHATTER_MIN_GAP_S + 1,
        roll=0.0,
        chance=1.0,
    )


@pytest.mark.parametrize(
    ("chance", "error"),
    [
        (-0.01, ValueError),
        (1.01, ValueError),
        (float("nan"), ValueError),
        (float("inf"), ValueError),
        (None, TypeError),
        (True, TypeError),
        ("0.2", TypeError),
    ],
)
def test_chatter_rejects_invalid_explicit_chance_override(chance, error):
    with pytest.raises(error):
        proactive.should_chatter(**_eligible_chatter_args(), roll=0.0, chance=chance)


def test_learned_behavior_lesson_reaches_review_card_without_legacy_selfmod(monkeypatch):
    mind, mind_mod = _bare_mind()
    _forbid_legacy_selfmod(monkeypatch, mind_mod)

    analysis = {
        "warmth_now": 0.55,
        "warmth_trend": -0.11,
        "stability": 0.82,
        "kept_changes": 1,
        "reverted_changes": 0,
    }
    lesson = {
        "kind": "connection",
        "confidence": 0.72,
        "evidence": "warmth 0.55 (trend -0.11), stability 0.82",
        "text": "A recent warmth decline warrants a bounded behavior review.",
        "suggestion": "chatter_chance:+1",
    }
    recorded: list[dict] = []
    reviews: list[dict] = []

    monkeypatch.setattr(
        mind_mod.state_store,
        "mood_history",
        lambda **_kwargs: [{"love": 0.55}],
    )
    monkeypatch.setattr(mind_mod.selfmod, "history", lambda **_kwargs: [])
    monkeypatch.setattr(mind_mod.memory_store, "count", lambda: 3)
    monkeypatch.setattr(mind_mod.memory_store, "remember", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.learning_mod, "analyze", lambda *_args: analysis)
    monkeypatch.setattr(mind_mod.learning_mod, "derive", lambda _analysis: lesson)
    monkeypatch.setattr(
        mind_mod.learning_mod,
        "_has_similar_recent",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        mind_mod.learning_mod,
        "record",
        lambda value: recorded.append(value) or 17,
    )
    monkeypatch.setattr(mind_mod.cognition_mod, "set_intent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind, "form_desire", lambda: None)
    monkeypatch.setattr(mind, "soul_state", lambda **_kwargs: {"focus": {}})
    monkeypatch.setattr(mind, "_enact_focus", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(mind, "_activity_note", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind, "consolidate_observations", lambda **_kwargs: None)

    def review_behavior_improvement(learned=None):
        review = {
            "proposal": {
                "id": 73,
                "action": "Review one behavior improvement",
                "status": "testing",
            },
            "lesson": (learned or {}).get("lesson"),
        }
        reviews.append(review)
        return review

    monkeypatch.setattr(mind, "review_behavior_improvement", review_behavior_improvement)

    result = mind.idle_self_direct()

    assert result["learned"] == {"analysis": analysis, "lesson": lesson}
    assert recorded == [lesson]
    assert reviews[0]["lesson"] == lesson
    assert reviews[0]["proposal"]["action"] == "Review one behavior improvement"
    assert reviews[0]["proposal"]["status"] == "testing"


def test_self_improve_tick_refreshes_review_without_legacy_selfmod(monkeypatch):
    mind, mind_mod = _bare_mind()
    _forbid_legacy_selfmod(monkeypatch, mind_mod)
    calls: list[object] = []
    review = {
        "proposal": {
            "id": 74,
            "action": "Review one behavior improvement",
            "status": "testing",
        }
    }

    def review_behavior_improvement(learned=None):
        calls.append(learned)
        return review

    monkeypatch.setattr(mind, "review_behavior_improvement", review_behavior_improvement)

    result = mind.self_improve_tick()

    assert calls == [None]
    assert result == {**review, "phase": "review_required"}
