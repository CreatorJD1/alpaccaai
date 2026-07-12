"""Focused Phase 3 CoreMind turn-context integration coverage."""
from __future__ import annotations

from alpecca import turn_context
from alpecca.homeostasis import EmotionalState


def _core_mind(monkeypatch, generate):
    """Build CoreMind without opening or writing the shared development DB."""
    from alpecca import mind as mind_mod

    class FakeLLM:
        def __init__(self):
            self._last_call = {
                "requested_tier": "reason",
                "used_tier": "reason",
                "backend": "test",
                "model": "fake",
                "ok": True,
                "fallback": False,
                "error": "",
            }
            self.online = True

        def generate(self, *args, **kwargs):
            return generate(*args, **kwargs)

        def last_call(self):
            return dict(self._last_call)

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
    monkeypatch.setattr(mind_mod.cognition_mod, "record_chat_turn", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "mark_observation_remembered", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.memory_store, "count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(mind_mod.memory_store, "recent", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.memory_store, "recall", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.memory_store, "remember_with_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.mindpage_mod, "prefault_pages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        mind_mod.mindpage_mod,
        "pressure_snapshot",
        lambda *args, **kwargs: dict(kwargs.get("ledger") or {}),
    )
    monkeypatch.setattr(mind_mod.journal_mod, "open_questions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.people_mod, "who_prompt", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mind_mod.core_mem, "prompt_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mind_mod.speech_mod, "spoken_performance_text", lambda text, _state: text)
    monkeypatch.setattr(mind_mod.speech_mod, "speech_cues", lambda _state: {})
    monkeypatch.setattr(mind_mod.turn_context_mod, "load_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.turn_context_mod, "save_history", lambda *_args, **_kwargs: None)

    mind = mind_mod.CoreMind()
    monkeypatch.setattr(mind, "try_go_to_room", lambda _message: False)
    return mind


def test_explicit_turn_reaches_tool_callback_with_private_retrieval(monkeypatch):
    from alpecca import mind as mind_mod
    from config import Actions as ActionsCfg

    monkeypatch.setattr(ActionsCfg, "INNATE_TOOLS", True)
    monkeypatch.setattr(ActionsCfg, "TOOL_MODE", "always")
    calls = {"tool_turns": [], "memory": [], "pages": []}

    def fake_generate(_system, _message, _history=None, *, tools=None, on_tool=None, **_kwargs):
        assert tools is not None
        assert on_tool is not None
        on_tool("memory_search", {"query": "tool-private-memory"})
        on_tool("recall_page", {"topic": "tool-private-page"})
        return "Scoped tool reply."

    mind = _core_mind(monkeypatch, fake_generate)
    original_execute = mind.toolkit.execute

    def capture_execute(tool_name, args, *, turn=None):
        calls["tool_turns"].append((tool_name, turn))
        return original_execute(tool_name, args, turn=turn)

    def recall_memory(query, **kwargs):
        if query == "tool-private-memory":
            calls["memory"].append(kwargs)
            return [{
                "id": 1,
                "kind": "episodic",
                "content": "guest-private memory",
                "recall_score": 0.9,
                "recall_method": "keyword",
            }]
        return []

    def recall_page(topic, **kwargs):
        calls["pages"].append((topic, kwargs))
        return [{
            "id": 2,
            "kind": "episode",
            "topic": "guest-private page",
            "summary": "guest-private page",
            "content": "guest-private page body",
            "score": 0.8,
        }]

    monkeypatch.setattr(mind.toolkit, "execute", capture_execute)
    monkeypatch.setattr(mind_mod.memory_store, "recall", recall_memory)
    monkeypatch.setattr(mind_mod.mindpage_mod, "recall_page", recall_page)
    turn = turn_context.TurnContext.create(
        "creator-chat",
        principal="creator",
        surface="websocket",
        privacy_scope="creator-private",
    )

    result = mind.chat("Use the scoped innate tools.", turn=turn)

    assert result["reply"] == "Scoped tool reply."
    assert [tool_name for tool_name, _turn in calls["tool_turns"]] == [
        "memory_search", "recall_page"
    ]
    assert all(seen_turn is turn for _tool_name, seen_turn in calls["tool_turns"])
    assert calls["memory"] == [{
        "top_k": 8,
        "scope": "creator-private",
        "include_shared": False,
    }]
    assert calls["pages"] == [(
        "tool-private-page",
        {"limit": 3, "scope": "creator-private", "include_shared": False},
    )]


def test_cancelled_turn_writes_no_chat_observation_or_history_records(monkeypatch):
    from alpecca import mind as mind_mod

    turn = turn_context.TurnContext.create(
        "cancelled-chat",
        principal="guest",
        surface="app",
        privacy_scope="guest-private",
    )
    writes = {"chat": [], "observation": [], "history": []}

    def fake_generate(*_args, **_kwargs):
        turn.cancel("test cancellation")
        return "Late reply that must not commit."

    mind = _core_mind(monkeypatch, fake_generate)
    monkeypatch.setattr(
        mind_mod.cognition_mod,
        "record_chat_turn",
        lambda *args, **kwargs: writes["chat"].append((args, kwargs)),
    )
    monkeypatch.setattr(
        mind_mod.cognition_mod,
        "record_observation",
        lambda *args, **kwargs: writes["observation"].append((args, kwargs)),
    )
    monkeypatch.setattr(
        mind_mod.turn_context_mod,
        "save_history",
        lambda *args, **kwargs: writes["history"].append((args, kwargs)),
    )

    result = mind.chat("This turn will be cancelled.", turn=turn)

    assert result["cancelled"] is True
    assert result["turn"]["commit_state"] == "cancelled"
    assert writes == {"chat": [], "observation": [], "history": []}
