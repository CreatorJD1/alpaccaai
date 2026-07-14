from __future__ import annotations

import asyncio
import threading

from fastapi.testclient import TestClient

from alpecca import discord_autonomy
from alpecca import mind as mind_mod
from alpecca import turn_context
import server


def _guest_mind(responses: list[str]):
    calls: list[dict[str, object]] = []

    class FakeLLM:
        def generate(self, system_prompt, user_msg, history, **kwargs):
            calls.append({
                "system_prompt": system_prompt,
                "user_msg": user_msg,
                "history": list(history),
                "kwargs": kwargs,
            })
            return responses.pop(0)

    value = object.__new__(mind_mod.CoreMind)
    value._guest_llm = FakeLLM()
    value._guest_llm_init_lock = threading.Lock()
    return value, calls


def _turn(phase: str) -> turn_context.TurnContext:
    return turn_context.TurnContext.create(
        f"discord-{phase}",
        principal="guest",
        surface="discord",
        privacy_scope="guest-discord-room-test",
        portal_epoch=phase,
    )


def test_decision_parser_is_strict_and_accepts_think_wrappers():
    decision = discord_autonomy.parse_decision(
        '<think>private</think>{"speak":true,"pick":3}'
    )

    assert decision == discord_autonomy.Decision(speak=True, pick=2)
    assert decision.intent == discord_autonomy.INTENTS[2]
    assert discord_autonomy.parse_decision('{"speak":true,"pick":1}') is None
    assert discord_autonomy.parse_decision('{"speak":false,"pick":2}') is None
    assert discord_autonomy.parse_decision('{"speak":true}') is None
    assert discord_autonomy.parse_decision(
        '{"speak":true,"pick":2,"draft":"skip the second pass"}'
    ) is None
    assert discord_autonomy.parse_decision("I think she should speak") is None


def test_autonomous_draft_rejects_generic_assistant_self_descriptions():
    assert discord_autonomy.publishable_draft(
        "That animation detail connects to what you noticed earlier."
    ) is True
    assert discord_autonomy.publishable_draft(
        "Since I'm a text-based AI, I cannot join voice."
    ) is False
    assert discord_autonomy.publishable_draft(
        "I can't join voice, but I can reply here."
    ) is False
    assert discord_autonomy.publishable_draft(
        "Hello! I'm here and ready to help."
    ) is False
    assert discord_autonomy.publishable_draft(
        "How can I assist with that?"
    ) is False
    assert discord_autonomy.publishable_draft("[pass]") is False


def test_decision_context_keeps_recent_tail_under_hard_bound():
    context = "old-marker " + ("x" * 9_000) + " latest-human-cue"
    prompt = discord_autonomy.decision_prompt(context)

    assert len(prompt) < 8_000
    assert "[older context elided]" in prompt
    assert "old-marker" in prompt
    assert "latest-human-cue" in prompt


def test_hidden_decision_and_composition_use_distinct_local_prompts():
    decision_mind, decision_calls = _guest_mind(['{"speak":true,"pick":4}'])
    decision_result = decision_mind._conversation_only_chat(
        "bounded room context",
        turn=_turn("discord-autonomy-deliberation"),
    )

    composition_mind, composition_calls = _guest_mind(["A grounded observation."])
    composition_result = composition_mind._conversation_only_chat(
        "selected intent and bounded context",
        turn=_turn("discord-autonomy-composition"),
    )

    assert decision_result["reply"] == '{"speak":true,"pick":4}'
    assert decision_calls[0]["system_prompt"] == discord_autonomy.DECISION_SYSTEM_PROMPT
    assert decision_calls[0]["kwargs"] == {
        "tools": None,
        "on_tool": None,
        "tier": "fast",
        "local_only": True,
    }
    assert composition_result["reply"] == "A grounded observation."
    assert composition_calls[0]["system_prompt"] == discord_autonomy.COMPOSITION_SYSTEM_PROMPT
    assert composition_calls[0]["kwargs"] == {
        "tools": None,
        "on_tool": None,
        "tier": "reason",
        "local_only": True,
    }


def test_server_deliberation_passes_without_composition(monkeypatch):
    calls: list[dict[str, object]] = []

    async def chat(text: str, **kwargs):
        calls.append({"text": text, **kwargs})
        return {"reply": '{"speak":false,"pick":1}'}

    outcomes: list[str] = []
    monkeypatch.setattr(server, "_ws_chat_turn_with_timeout", chat)
    monkeypatch.setattr(
        server,
        "_record_discord_autonomy_outcome",
        lambda _scope, outcome, **_kwargs: outcomes.append(outcome) or True,
    )

    reply = asyncio.run(server._deliberated_discord_autonomy("room context", "a" * 64))

    assert reply == "[pass]"
    assert len(calls) == 1
    assert calls[0]["turn"].portal_epoch == "discord-autonomy-deliberation"
    assert outcomes == ["deliberate-pass"]


def test_server_composes_only_after_valid_decision_and_audit(monkeypatch):
    replies = [
        {"reply": '{"speak":true,"pick":3}'},
        {"reply": "Which part of the motion still feels least natural to you?"},
    ]
    calls: list[dict[str, object]] = []

    async def chat(text: str, **kwargs):
        calls.append({"text": text, **kwargs})
        return replies.pop(0)

    outcomes: list[tuple[str, int]] = []
    monkeypatch.setattr(server, "_ws_chat_turn_with_timeout", chat)
    monkeypatch.setattr(
        server,
        "_record_discord_autonomy_outcome",
        lambda _scope, outcome, *, calls, **_kwargs: outcomes.append((outcome, calls)) or True,
    )

    reply = asyncio.run(server._deliberated_discord_autonomy("room context", "b" * 64))

    assert reply == "Which part of the motion still feels least natural to you?"
    assert len(calls) == 2
    assert calls[0]["turn"].portal_epoch == "discord-autonomy-deliberation"
    assert calls[1]["turn"].portal_epoch == "discord-autonomy-composition"
    assert "ask one new question" in calls[1]["text"]
    assert outcomes == [("approved", 2)]


def test_server_rejects_generic_draft_and_fails_closed_without_audit(monkeypatch):
    async def generic_chat(_text: str, **kwargs):
        if kwargs["turn"].portal_epoch == "discord-autonomy-deliberation":
            return {"reply": '{"speak":true,"pick":2}'}
        return {"reply": "I'm here and ready to help. How can I assist?"}

    monkeypatch.setattr(server, "_ws_chat_turn_with_timeout", generic_chat)
    monkeypatch.setattr(server, "_record_discord_autonomy_outcome", lambda *_a, **_k: True)
    assert asyncio.run(
        server._deliberated_discord_autonomy("room context", "c" * 64)
    ) == "[pass]"

    async def grounded_chat(_text: str, **kwargs):
        if kwargs["turn"].portal_epoch == "discord-autonomy-deliberation":
            return {"reply": '{"speak":true,"pick":2}'}
        return {"reply": "That answers the unresolved point from earlier."}

    monkeypatch.setattr(server, "_ws_chat_turn_with_timeout", grounded_chat)
    monkeypatch.setattr(server, "_record_discord_autonomy_outcome", lambda *_a, **_k: False)
    assert asyncio.run(
        server._deliberated_discord_autonomy("room context", "d" * 64)
    ) == "[pass]"


def test_autonomy_route_requires_bridge_auth_and_uses_deliberation(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def deliberate(text: str, room_scope: str) -> str:
        calls.append((text, room_scope))
        return "One reviewed message."

    monkeypatch.setattr(server, "_deliberated_discord_autonomy", deliberate)
    payload = {"text": "bounded context", "room_scope": "e" * 64}
    with TestClient(server.app) as client:
        anonymous = client.post("/channel/discord/autonomy", json=payload)
        authorized = client.post(
            "/channel/discord/autonomy",
            headers={
                server.auth_mod.BRIDGE_AUTHORIZATION_HEADER:
                    server._DISCORD_BRIDGE_SECRET,
            },
            json=payload,
        )

    assert anonymous.status_code in {401, 403}
    assert authorized.status_code == 200
    assert authorized.json() == {"reply": "One reviewed message."}
    assert calls == [("bounded context", "e" * 64)]
