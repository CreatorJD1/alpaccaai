"""Focused Phase 3 coverage for scoped innate-tool execution."""
from __future__ import annotations

import json

from alpecca import toolkit as toolkit_mod
from alpecca import turn_context


class _Mind:
    pass


def _toolkit(monkeypatch):
    monkeypatch.setattr(toolkit_mod.ActionsCfg, "INNATE_TOOLS", True)
    return toolkit_mod.InnateToolkit(_Mind())


def test_scoped_retrieval_tools_exclude_shared_and_other_scopes(monkeypatch):
    toolkit = _toolkit(monkeypatch)
    turn = turn_context.TurnContext.create(
        "creator-chat",
        principal="creator",
        surface="websocket",
        privacy_scope="creator-private",
    )
    memory_calls = []
    page_calls = []

    def recall_memory(query, **kwargs):
        memory_calls.append((query, kwargs))
        return [{
            "id": 1,
            "kind": "episodic",
            "content": "guest-private marker",
            "recall_score": 0.9,
            "recall_method": "keyword",
        }]

    def recall_page(topic, **kwargs):
        page_calls.append((topic, kwargs))
        return [{
            "id": 2,
            "kind": "episode",
            "topic": "guest-private marker",
            "summary": "guest-private marker",
            "content": "guest-only page body",
            "score": 0.8,
        }]

    monkeypatch.setattr(toolkit_mod.memory_store, "recall", recall_memory)
    monkeypatch.setattr(toolkit_mod.mindpage_mod, "recall_page", recall_page)

    memory_result = json.loads(
        toolkit.execute("memory_search", {"query": "marker", "limit": 3}, turn=turn)
    )
    page_result = json.loads(
        toolkit.execute("recall_page", {"topic": "marker"}, turn=turn)
    )

    assert memory_result["results"][0]["content"] == "guest-private marker"
    assert page_result["pages"][0]["content"] == "guest-only page body"
    assert memory_calls == [(
        "marker",
        {"top_k": 3, "scope": "creator-private", "include_shared": False},
    )]
    assert page_calls == [(
        "marker",
        {"limit": 3, "scope": "creator-private", "include_shared": False},
    )]


def test_contextless_and_cancelled_calls_do_not_reach_tool_backends(monkeypatch):
    toolkit = _toolkit(monkeypatch)
    calls = []
    monkeypatch.setattr(
        toolkit_mod.memory_store,
        "recall",
        lambda *_args, **_kwargs: calls.append("memory") or [],
    )
    turn = turn_context.TurnContext.create("cancelled", principal="creator")
    turn.cancel("timeout")

    assert toolkit.execute("memory_search", {"query": "secret"}) == (
        "error: innate tools require an active TurnContext"
    )
    assert toolkit.execute("memory_search", {"query": "secret"}, turn=turn) == (
        "error: turn was cancelled before the innate tool could run"
    )
    assert calls == []


def test_self_status_is_limited_to_the_current_turn_and_creator_tools_execute(monkeypatch):
    toolkit = _toolkit(monkeypatch)
    turn = turn_context.TurnContext.create(
        "app-chat",
        principal="creator",
        surface="app",
        privacy_scope="creator-app-private",
        portal_epoch="lease-4",
    )

    status = json.loads(toolkit.execute("self_status", {}, turn=turn))

    assert status == {
        "turn": {
            "turn_id": turn.turn_id,
            "conversation_id": "app-chat",
            "principal": "creator",
            "surface": "app",
            "privacy_scope": "creator-app-private",
            "portal_epoch": "lease-4",
            "commit_state": "pending",
        }
    }
    monkeypatch.setattr(toolkit_mod.journal_mod, "recent", lambda **_kwargs: [])
    assert json.loads(toolkit.execute("journal_read", {}, turn=turn))["entries"] == []


def test_creator_side_effect_tools_dispatch_and_log_without_private_payload(monkeypatch):
    mind = _Mind()
    mind.state = type("State", (), {"mood_label": lambda self: "steady"})()
    mind._location = "parlor"
    mind._last_roam_ts = 0.0
    mind.plan_goal = lambda goal: {"ok": True, "created": 1, "proposals": [{"id": 7}]}
    toolkit = _toolkit(monkeypatch)
    toolkit.mind = mind
    turn = turn_context.TurnContext.create("creator-tools", principal="creator")
    observations = []

    monkeypatch.setattr(toolkit_mod.journal_mod, "write", lambda **_kwargs: 11)
    monkeypatch.setattr(toolkit_mod.desires_mod, "form", lambda **_kwargs: 12)
    monkeypatch.setattr(toolkit_mod.cognition_mod, "record_observation", observations.append)
    monkeypatch.setattr(toolkit_mod.ActionsCfg, "PLANNER", True)

    assert "entry 11" in toolkit.execute(
        "journal_write", {"text": "private journal body"}, turn=turn,
    )
    assert "desire 12" in toolkit.execute(
        "note_to_self", {"text": "private intention"}, turn=turn,
    )
    assert "proposal_ids" in toolkit.execute(
        "make_plan", {"goal": "private goal"}, turn=turn,
    )

    assert [item.metadata["tool"] for item in observations] == [
        "journal_write", "note_to_self", "make_plan",
    ]
    serialized = json.dumps([item.metadata for item in observations])
    assert "private journal body" not in serialized
    assert "private intention" not in serialized
    assert "private goal" not in serialized
