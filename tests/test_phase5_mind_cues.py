"""Focused Phase 5 CoreMind cue-affect and initiative wiring coverage."""
from __future__ import annotations

from dataclasses import replace

from alpecca import cues, turn_context
from alpecca.homeostasis import EmotionalState


def _core_mind(monkeypatch, generate):
    """Build CoreMind without shared database or external-system effects."""
    from alpecca import mind as mind_mod

    class FakeLLM:
        online = True

        def generate(self, *args, **kwargs):
            return generate(*args, **kwargs)

        def last_call(self):
            return {
                "requested_tier": "reason",
                "used_tier": "reason",
                "backend": "test",
                "model": "fake",
                "ok": True,
                "fallback": False,
                "error": "",
            }

        def is_cloud(self):
            return False

    class FakePortraitWorker:
        def request(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(mind_mod, "_LLM", FakeLLM)
    monkeypatch.setattr(mind_mod, "PortraitWorker", FakePortraitWorker)
    monkeypatch.setattr(mind_mod.state_store, "init_db", lambda: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "init_db", lambda: None)
    monkeypatch.setattr(mind_mod.turn_context_mod, "ensure_history_schema", lambda: None)
    monkeypatch.setattr(mind_mod.state_store, "load_state", lambda: EmotionalState())
    monkeypatch.setattr(mind_mod.state_store, "load_appearance_seed", lambda: 7)
    monkeypatch.setattr(mind_mod.state_store, "load_location", lambda: "parlor")
    monkeypatch.setattr(mind_mod.state_store, "save_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.state_store, "save_location", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.state_store, "mood_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.cognition_mod, "set_intent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "current_intent", lambda: {"name": "waiting"})
    monkeypatch.setattr(mind_mod.cognition_mod, "record_observation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "record_chat_turn", lambda *_args, **_kwargs: 81)
    monkeypatch.setattr(
        mind_mod.cognition_mod,
        "mark_observation_remembered",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(mind_mod.memory_store, "count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(mind_mod.memory_store, "recent", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.memory_store, "recall", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        mind_mod.memory_store,
        "remember_with_id",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(mind_mod.mindpage_mod, "prefault_pages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        mind_mod.mindpage_mod,
        "pressure_snapshot",
        lambda *args, **kwargs: dict(kwargs.get("ledger") or {}),
    )
    monkeypatch.setattr(mind_mod.journal_mod, "open_questions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.people_mod, "who_prompt", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mind_mod.core_mem, "prompt_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        mind_mod.speech_mod,
        "spoken_performance_text",
        lambda text, _state: text,
    )
    monkeypatch.setattr(mind_mod.speech_mod, "speech_cues", lambda _state: {})
    monkeypatch.setattr(mind_mod.turn_context_mod, "load_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.turn_context_mod, "save_history", lambda *_args, **_kwargs: None)

    mind = mind_mod.CoreMind()
    monkeypatch.setattr(mind, "try_go_to_room", lambda _message: False)
    monkeypatch.setattr(mind, "_tool_schema", lambda *_args, **_kwargs: None)
    return mind, mind_mod


def _turn(scope: str = "guest-phase5") -> turn_context.TurnContext:
    return turn_context.TurnContext.create(
        "phase5-chat",
        principal="guest",
        surface="app",
        privacy_scope=scope,
        portal_epoch="phase5-test",
    )


def test_chat_returns_bounded_operational_affect_with_cue_provenance(monkeypatch):
    prompts = []

    def generate(system_prompt, *_args, **_kwargs):
        prompts.append(system_prompt)
        return "I will keep this response concise and grounded."

    mind, _mind_mod = _core_mind(
        monkeypatch,
        generate,
    )
    active_turn = _turn()

    result = mind.chat(
        "Please help me right now! I'm overwhelmed.",
        turn=active_turn,
    )

    metadata = result["affect_evidence"]
    assert metadata["eligible"] is True
    assert metadata["state_changed"] is False
    assert metadata["strategy_changed"] is True
    assert metadata["reason"] == "eligible_evidence"
    assert metadata["provenance"]["source"] == "cue_parser"
    assert metadata["provenance"]["turn_id"] == active_turn.turn_id
    assert metadata["provenance"]["scope"] == active_turn.memory_scope
    kinds = {event["cue_kind"] for event in metadata["events"]}
    assert {"urgency", "distress", "action_intent"} <= kinds
    distress = next(
        event for event in metadata["events"] if event["cue_kind"] == "distress"
    )
    assert distress["decision"]["evidence"]["source"] == "chat_cue"
    assert distress["decision"]["evidence"]["confidence"] >= 0.9
    assert distress["cue_evidence"]
    assert all(len(item) <= 120 for item in distress["cue_evidence"])
    assert "calm, support-focused response strategy" in metadata["response_strategy"]
    assert any(
        "Response strategy from current, confidence-gated message cues" in prompt
        and "calm, support-focused response strategy" in prompt
        for prompt in prompts
    )
    rendered = str(metadata).lower()
    assert "i feel" not in rendered
    assert "conscious" not in rendered
    assert "sentient" not in rendered


def test_weak_and_unknown_cues_are_metadata_only_noops(monkeypatch):
    mind, mind_mod = _core_mind(
        monkeypatch,
        lambda *_args, **_kwargs: "I need a clearer reference before relying on it.",
    )
    active_turn = _turn("guest-weak")

    weak_result = mind.chat("it", turn=active_turn)["affect_evidence"]

    assert weak_result["eligible"] is False
    assert weak_result["state_changed"] is False
    assert weak_result["strategy_changed"] is False
    assert weak_result["response_strategy"] == ""
    assert weak_result["reason"] == "no_eligible_evidence"
    assert weak_result["operational_states"] == []
    assert weak_result["events"][0]["decision"]["reason"] == "weak_evidence"

    unknown_signal = cues.CueSignal(
        kind="unknown",  # type: ignore[arg-type]
        detected=True,
        confidence=0.99,
        evidence=("unrecognized marker",),
    )
    unknown_envelope = replace(cues.parse_cues(""), reference=unknown_signal)
    unknown = mind_mod.CoreMind._phase5_affect_metadata(
        unknown_envelope,
        _turn("guest-unknown"),
        observed_at=100.0,
    )

    assert unknown["eligible"] is False
    assert unknown["state_changed"] is False
    assert unknown["reason"] == "unknown_or_invalid_cue"
    assert unknown["events"] == []
    assert unknown["ignored_kinds"] == ["unknown"]


def test_no_cue_keeps_affect_metadata_at_noop_defaults(monkeypatch):
    mind, _mind_mod = _core_mind(
        monkeypatch,
        lambda *_args, **_kwargs: "Hello.",
    )

    metadata = mind.chat("hello", turn=_turn("guest-empty"))["affect_evidence"]

    assert metadata["eligible"] is False
    assert metadata["state_changed"] is False
    assert metadata["reason"] == "no_grounded_cue"
    assert metadata["events"] == []
    assert metadata["operational_states"] == []


def test_direct_reply_never_consults_initiative_budget(monkeypatch):
    mind, _mind_mod = _core_mind(
        monkeypatch,
        lambda *_args, **_kwargs: "This is a direct reply.",
    )

    class FailIfConsulted:
        def decide(self, **_kwargs):
            raise AssertionError("direct replies must bypass initiative")

    mind._initiative_budget = FailIfConsulted()

    result = mind.chat("How does this work?", turn=_turn("guest-direct"))

    assert result["reply"] == "This is a direct reply."
    assert result["affect_evidence"]["provenance"]["scope"] == "guest-direct"


def test_proactive_compose_uses_independent_scope_budgets(monkeypatch):
    generated = []

    def generate(*_args, **_kwargs):
        generated.append(True)
        return "A bounded proactive line."

    mind, mind_mod = _core_mind(monkeypatch, generate)
    mind._initiative_budget = mind_mod.initiative_mod.InitiativeBudget(
        mind_mod.initiative_mod.InitiativePolicy(
            cooldown_seconds=0.0,
            window_seconds=3600.0,
            max_per_window=10,
            dedupe_seconds=3600.0,
            activity_quiet_seconds=0.0,
        ),
        clock=lambda: 100.0,
    )

    first = mind.compose_volunteer("check in about the terminal", scope="scope-a")
    duplicate = mind.compose_volunteer("check in about the terminal", scope="scope-a")
    duplicate_metadata = dict(mind._last_initiative_decision or {})
    other_scope = mind.compose_volunteer(
        "check in about the terminal", scope="scope-b"
    )

    assert first == "A bounded proactive line."
    assert duplicate == ""
    assert duplicate_metadata["decision"] == "defer"
    assert duplicate_metadata["reason"] == "awaiting_response"
    assert other_scope == "A bounded proactive line."
    assert mind._last_initiative_decision["decision"] == "allow"
    assert mind._last_initiative_decision["scope"] == "scope-b"
    assert len(generated) == 2


def test_proactive_compose_writes_only_its_turn_history(monkeypatch):
    mind, _mind_mod = _core_mind(
        monkeypatch,
        lambda *_args, **_kwargs: "A scoped proactive line.",
    )
    first_turn = _turn("scope-first")
    second_turn = _turn("scope-second")

    assert mind.compose_volunteer("first reason", turn=first_turn)
    assert mind.compose_volunteer("second reason", turn=second_turn)

    assert mind._get_history(turn=first_turn) == [
        {"role": "assistant", "content": "A scoped proactive line."}
    ]
    assert mind._get_history(turn=second_turn) == [
        {"role": "assistant", "content": "A scoped proactive line."}
    ]
    assert mind._history == []


def test_empty_proactive_reason_preserves_legacy_no_budget_path(monkeypatch):
    mind, _mind_mod = _core_mind(
        monkeypatch,
        lambda *_args, **_kwargs: "Legacy empty-reason output.",
    )

    class FailIfConsulted:
        def decide(self, **_kwargs):
            raise AssertionError("empty reason has no initiative budget event")

    mind._initiative_budget = FailIfConsulted()

    result = mind.compose_volunteer("", scope="scope-empty")

    assert result == "Legacy empty-reason output."
    assert mind._last_initiative_decision is None
