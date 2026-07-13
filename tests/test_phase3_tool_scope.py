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
        {
            "limit": 3,
            "scope": "creator-private",
            "include_shared": False,
            "max_tokens": 220,
        },
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


def test_self_status_is_limited_to_the_current_turn_and_unscoped_tools_refuse(monkeypatch):
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
    assert toolkit.execute("journal_read", {}, turn=turn) == (
        "error: journal_read is unavailable in a scoped turn because its "
        "storage or side effects are not scope-partitioned"
    )
