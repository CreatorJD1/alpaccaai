"""Focused Phase 4 CoreMind cue and commitment wiring coverage."""
from __future__ import annotations

from alpecca import turn_context
from alpecca.homeostasis import EmotionalState


def _core_mind(monkeypatch, generate):
    """Build CoreMind without touching the shared development database."""
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
    monkeypatch.setattr(mind_mod.cognition_mod, "record_chat_turn", lambda *_args, **_kwargs: 41)
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


def _turn(name: str = "phase4") -> turn_context.TurnContext:
    return turn_context.TurnContext.create(
        name,
        principal="guest",
        surface="app",
        privacy_scope="guest-private",
    )


def test_parse_generate_commit_and_rewrite_order_is_transactional(monkeypatch):
    events: list[str] = []
    active_turn = _turn("ordered")

    def generate(*_args, **_kwargs):
        events.append("generate")
        assert active_turn.barrier.state == "pending"
        return "I'll inspect the requested source files."

    mind, mind_mod = _core_mind(monkeypatch, generate)
    real_parse = mind_mod.cues_mod.parse_cue_envelope

    def parse(message):
        events.append("parse")
        return real_parse(message)

    captured = {}

    def create(action, *, scope, evidence):
        events.append("create")
        assert active_turn.barrier.state == "committing"
        captured.update(action=action, scope=scope, evidence=evidence)
        return {
            "id": 17,
            "state": "proposed",
            "scope": scope,
            "action": action,
            "receipt": None,
            "receipts": [],
        }

    monkeypatch.setattr(mind_mod.cues_mod, "parse_cue_envelope", parse)
    monkeypatch.setattr(
        mind_mod.turn_context_mod,
        "load_history",
        lambda *_args, **_kwargs: events.append("history") or [],
    )
    monkeypatch.setattr(mind_mod.commitments_mod, "create_commitment", create)

    result = mind.chat(
        "Please inspect the previous file right now.",
        turn=active_turn,
    )

    assert events.index("parse") < events.index("history") < events.index("generate")
    assert events.index("generate") < events.index("create")
    assert result["reply"] != "I'll inspect the requested source files."
    assert "proposed" in result["reply"].lower()
    assert result["commitment"]["created"] is True
    assert result["commitment"]["state"] == "proposed"
    assert result["commitment"]["id"] == 17
    assert result["cues"]["active_kinds"] == ["reference", "urgency", "action_intent"]
    assert captured["scope"] == "guest-private"
    assert captured["action"] == "inspect the requested source files"
    assert captured["evidence"]["source"] == "assistant_future_action"
    assert captured["evidence"]["turn"]["turn_id"] == active_turn.turn_id
    assert captured["evidence"]["turn"]["commit_state"] == "committing"
    assert len(captured["evidence"]["cues"]) <= 7
    assert all(
        len(snippet) <= 120
        for cue in captured["evidence"]["cues"]
        for snippet in cue["evidence"]
    )


def test_completion_without_receipt_is_rewritten_and_persisted_as_rewritten(monkeypatch):
    saved_history = []

    def generate(*_args, **_kwargs):
        return "Done. I completed the upload."

    mind, mind_mod = _core_mind(monkeypatch, generate)
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "create_commitment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("completion claims must not create commitments")
        ),
    )
    monkeypatch.setattr(
        mind_mod.turn_context_mod,
        "save_history",
        lambda _turn, history: saved_history.extend(history),
    )

    result = mind.chat("Did you finish the upload?", turn=_turn("completion"))

    assert result["commitment"]["created"] is False
    assert result["commitment"]["state"] == "unavailable"
    assert result["commitment"]["language_rewritten"] is True
    assert result["reply"] != "Done. I completed the upload."
    assert "unavailable" in result["reply"].lower()
    assert saved_history[-1] == {"role": "assistant", "content": result["reply"]}


def test_failed_commitment_write_rewrites_future_promise(monkeypatch):
    def generate(*_args, **_kwargs):
        return "I'll upload the report."

    mind, mind_mod = _core_mind(monkeypatch, generate)
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "create_commitment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("ledger offline")),
    )

    result = mind.chat("Please upload the report.", turn=_turn("ledger-failure"))

    assert result["commitment"]["created"] is False
    assert result["commitment"]["state"] == "unavailable"
    assert result["commitment"]["language_rewritten"] is True
    assert result["commitment"]["error"] == "RuntimeError: ledger offline"
    assert "unavailable" in result["reply"].lower()
    assert "I'll upload" not in result["reply"]


def test_user_action_cue_alone_does_not_create_commitment(monkeypatch):
    def generate(*_args, **_kwargs):
        return "That request needs approval before anything can run."

    mind, mind_mod = _core_mind(monkeypatch, generate)
    calls = []
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "create_commitment",
        lambda *_args, **_kwargs: calls.append(True),
    )

    result = mind.chat("Please delete the report.", turn=_turn("user-only"))

    assert calls == []
    assert result["cues"]["cues"]["action_intent"]["detected"] is True
    assert result["commitment"]["created"] is False
    assert result["commitment"]["state"] == "none"
    assert result["commitment"]["language_rewritten"] is False


def test_cancelled_generation_creates_no_commitment(monkeypatch):
    active_turn = _turn("cancelled")

    def generate(*_args, **_kwargs):
        active_turn.cancel("test cancellation")
        return "I'll do that later."

    mind, mind_mod = _core_mind(monkeypatch, generate)
    calls = []
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "create_commitment",
        lambda *_args, **_kwargs: calls.append(True),
    )

    result = mind.chat("Please continue.", turn=active_turn)

    assert result["cancelled"] is True
    assert result["turn"]["commit_state"] == "cancelled"
    assert calls == []
