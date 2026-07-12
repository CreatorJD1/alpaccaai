"""Focused coverage for typed proactive candidate provenance."""
from __future__ import annotations

import dataclasses

import pytest

from alpecca.homeostasis import EmotionalState


def _bare_mind():
    from alpecca import mind as mind_mod

    mind = mind_mod.CoreMind.__new__(mind_mod.CoreMind)
    mind.state = EmotionalState(love=0.55, social_hunger=0.35)
    mind._last_user_ts = 0.0
    mind._last_volunteer_ts = 0.0
    mind._last_situation = ""
    mind._chatter_chance_supplier = None
    return mind, mind_mod


def test_volunteer_candidate_marks_mood_speech_and_is_frozen(monkeypatch):
    mind, mind_mod = _bare_mind()
    monkeypatch.setattr(mind_mod.ProactiveCfg, "ENABLED", True)
    monkeypatch.setattr(mind_mod.time, "time", lambda: 1000.0)
    monkeypatch.setattr(
        mind_mod.proactive_mod, "should_speak", lambda *_args: "A mood shift matters."
    )

    def unexpected_chatter(*_args, **_kwargs):
        pytest.fail("mood speech must bypass chatter eligibility")

    monkeypatch.setattr(mind_mod.proactive_mod, "should_chatter", unexpected_chatter)

    candidate = mind.volunteer_candidate()

    assert candidate == mind_mod.ProactiveCandidate(
        origin="mood_speech", reason="A mood shift matters."
    )
    assert mind._last_volunteer_ts == 1000.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        candidate.reason = "Changed"


def test_volunteer_candidate_marks_chatter_after_existing_fallback_gates(monkeypatch):
    mind, mind_mod = _bare_mind()
    chatter_rolls: list[float] = []
    monkeypatch.setattr(mind_mod.ProactiveCfg, "ENABLED", True)
    monkeypatch.setattr(mind_mod, "PROACTIVE_LLM", False)
    monkeypatch.setattr(mind_mod.time, "time", lambda: 1000.0)
    monkeypatch.setattr(mind_mod.proactive_mod, "should_speak", lambda *_args: None)
    monkeypatch.setattr(mind, "_prompt_situation", lambda _base: "")

    def should_chatter(*_args, **_kwargs):
        chatter_rolls.append(_args[3])
        return True

    monkeypatch.setattr(mind_mod.proactive_mod, "should_chatter", should_chatter)
    monkeypatch.setattr(mind_mod.memory_store, "recent", lambda **_kwargs: [])
    monkeypatch.setattr(
        mind_mod.proactive_mod, "chatter_reasons", lambda **_kwargs: ["Say hello."]
    )
    monkeypatch.setattr(mind_mod.random, "random", lambda: 0.25)

    candidate = mind.volunteer_candidate()

    assert candidate == mind_mod.ProactiveCandidate(
        origin="chatter", reason="Say hello."
    )
    assert chatter_rolls == [0.0, 0.25]
    assert mind._last_volunteer_ts == 1000.0


def test_volunteer_reason_compatibility_wrapper_unwraps_candidate(monkeypatch):
    mind, mind_mod = _bare_mind()
    candidates = iter((
        mind_mod.ProactiveCandidate(origin="chatter", reason="Say hello."),
        None,
    ))
    monkeypatch.setattr(mind, "volunteer_candidate", lambda: next(candidates))

    assert mind.volunteer_reason() == "Say hello."
    assert mind.volunteer_reason() is None
