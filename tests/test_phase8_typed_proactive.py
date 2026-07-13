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


def test_volunteer_candidate_marks_chatter_after_one_probability_gate(monkeypatch):
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
        origin="chatter",
        reason="Say hello.",
        gate_chance=float(mind_mod.ProactiveCfg.CHATTER_CHANCE),
        gate_draw=0.25,
        gated_at=1000.0,
    )
    assert chatter_rolls == [0.25]
    assert mind._last_volunteer_ts == 1000.0


def test_behavior_trial_chance_gates_default_llm_proactive_path(monkeypatch):
    _mind, mind_mod = _bare_mind()
    monkeypatch.setattr(mind_mod.ProactiveCfg, "ENABLED", True)
    monkeypatch.setattr(mind_mod.ProactiveCfg, "CHATTER_ENABLED", True)
    monkeypatch.setattr(mind_mod, "PROACTIVE_LLM", True)
    monkeypatch.setattr(mind_mod.time, "time", lambda: 1000.0)
    monkeypatch.setattr(mind_mod.proactive_mod, "should_speak", lambda *_args: None)
    monkeypatch.setattr(mind_mod.memory_store, "recent", lambda **_kwargs: [])
    monkeypatch.setattr(
        mind_mod.proactive_mod, "chatter_reasons", lambda **_kwargs: ["Say hello."]
    )
    monkeypatch.setattr(mind_mod.random, "random", lambda: 0.24)
    decisions: list[float] = []

    def pick(*_args, **_kwargs):
        decisions.append(1.0)
        return {"speak": True, "pick": 0}

    monkeypatch.setattr(mind_mod.choice_mod, "constrained_pick", pick)

    trial_mind, _ = _bare_mind()
    trial_mind._chatter_chance_supplier = lambda: {
        "chance": 0.23,
        "trial_id": 7,
        "profile_generation": "profile-a",
        "gated_at": 999.5,
    }
    trial_mind._prompt_situation = lambda _base: ""
    trial_mind.llm = object()
    assert trial_mind.volunteer_candidate() is None
    assert decisions == []

    baseline_mind, _ = _bare_mind()
    baseline_mind._chatter_chance_supplier = lambda: {
        "chance": 0.25,
        "trial_id": None,
        "profile_generation": "profile-a",
        "gated_at": 999.5,
    }
    baseline_mind._prompt_situation = lambda _base: ""
    baseline_mind.llm = object()
    assert baseline_mind.volunteer_candidate() == mind_mod.ProactiveCandidate(
        origin="chatter",
        reason="Say hello.",
        profile_generation="profile-a",
        gate_chance=0.25,
        gate_draw=0.24,
        gated_at=999.5,
    )
    assert decisions == [1.0]


def test_volunteer_reason_compatibility_wrapper_unwraps_candidate(monkeypatch):
    mind, mind_mod = _bare_mind()
    candidates = iter((
        mind_mod.ProactiveCandidate(origin="chatter", reason="Say hello."),
        None,
    ))
    monkeypatch.setattr(mind, "volunteer_candidate", lambda: next(candidates))

    assert mind.volunteer_reason() == "Say hello."
    assert mind.volunteer_reason() is None
