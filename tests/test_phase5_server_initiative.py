"""Server integration coverage for the Phase 5 initiative boundary."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from alpecca import turn_context
import server


def _turn(scope: str = "creator-house-hq-primary") -> turn_context.TurnContext:
    return turn_context.TurnContext.create(
        "creator-house-hq-primary",
        principal="creator",
        surface="house-hq",
        privacy_scope=scope,
        portal_epoch="phase5-server-test",
    )


def test_deferred_routine_stops_before_optional_work(monkeypatch):
    calls: list[dict] = []

    def reserve(**kwargs):
        calls.append(kwargs)
        return {
            "allowed": False,
            "decision": "defer",
            "reason": "cooldown",
            "scope": kwargs["scope_key"],
        }

    async def accepted(_category, _label, fn, *args, **kwargs):
        kwargs.pop("timeout", None)
        return fn(*args, **kwargs)

    monkeypatch.setattr(server, "_proactive_turn_context", _turn)
    monkeypatch.setattr(server.mind, "reserve_initiative", reserve)
    monkeypatch.setattr(server, "_optional_bounded_thread", accepted)

    result = asyncio.run(server._run_routine({
        "id": 12,
        "name": "Daily recap",
        "kind": "daily_recap",
    }))

    assert result["status"] == "deferred"
    assert result["initiative"]["reason"] == "cooldown"
    assert calls == [{
        "event_kind": "routine",
        "evidence_key": calls[0]["evidence_key"],
        "scope_key": _turn().scope_key,
        "relevance": 0.7,
        "user_active": False,
        "outreach": False,
    }]
    assert calls[0]["evidence_key"].startswith("12:")
    assert calls[0]["evidence_key"].endswith(":daily_recap")


def test_morning_greeting_uses_scoped_proactive_turn(monkeypatch):
    proactive_turn = _turn("creator-morning")
    captured: dict = {}
    observations: list[object] = []

    async def completed(_category, _label, fn, *args, **kwargs):
        kwargs.pop("timeout", None)
        return fn(*args, **kwargs)

    def compose_event(_reason, *, turn):
        captured.update({"turn": turn})
        return {"status": "generated", "text": "Good morning.", "initiative": {"allowed": True}}

    monkeypatch.setattr(server, "_proactive_turn_context", lambda: proactive_turn)
    monkeypatch.setattr(server, "_optional_bounded_thread", completed)
    monkeypatch.setattr(
        server.mind, "compose_volunteer_event", compose_event,
    )
    monkeypatch.setattr(
        server.cognition_mod,
        "record_observation",
        lambda observation: observations.append(observation),
    )
    monkeypatch.setattr(
        server,
        "_deliver_proactive_once",
        lambda *_args, **_kwargs: asyncio.sleep(
            0, result={"surface": "portal", "delivered": True, "count": 1}
        ),
    )
    monkeypatch.setattr(server.mind, "record_proactive_delivery", lambda *_args, **_kwargs: None)

    result = asyncio.run(server._run_routine({
        "id": 14,
        "name": "Morning greeting",
        "kind": "morning_greeting",
    }))

    assert result["status"] == "ok"
    assert captured["turn"] is proactive_turn
    assert len(observations) == 1


def test_direct_server_turn_records_activity_before_chat(monkeypatch):
    active_turn = _turn("creator-active")
    order: list[str] = []

    monkeypatch.setattr(server, "_observe", lambda: SimpleNamespace(window_title=""))
    monkeypatch.setattr(server.mind, "perceive", lambda _obs: None)

    def note(scope_key: str):
        order.append(f"activity:{scope_key}")
        return {"scope": scope_key}

    def chat(_text, **_kwargs):
        order.append("chat")
        return {"reply": "Direct answer.", "cancelled": False}

    monkeypatch.setattr(server.mind, "note_initiative_user_activity", note)
    monkeypatch.setattr(server.mind, "chat", chat)

    result = asyncio.run(server._locked_ws_chat_turn(active_turn, "Hello"))

    assert result["reply"] == "Direct answer."
    assert order == [f"activity:{active_turn.scope_key}", "chat"]


def test_proactive_delivery_uses_portal_without_channel_duplicate(monkeypatch):
    broadcasts: list[dict] = []

    async def broadcast(payload):
        broadcasts.append(payload)
        return 1

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("portal delivery must not also use the channel")

    monkeypatch.setattr(server, "ws_clients", {object()})
    monkeypatch.setattr(server, "_broadcast", broadcast)
    monkeypatch.setattr(server, "_bounded_thread", forbidden)

    result = asyncio.run(server._deliver_proactive_once("One line."))

    assert result == {"surface": "portal", "delivered": True, "count": 1}
    assert [payload["reply"] for payload in broadcasts] == ["One line."]


def test_proactive_delivery_falls_back_to_channel_once(monkeypatch):
    calls: list[tuple] = []

    async def deliver(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True}

    async def forbidden(_payload):
        raise AssertionError("channel fallback must not also broadcast")

    monkeypatch.setattr(server, "ws_clients", set())
    monkeypatch.setattr(server, "_bounded_thread", deliver)
    monkeypatch.setattr(server, "_broadcast", forbidden)

    result = asyncio.run(server._deliver_proactive_once("Fallback line."))

    assert result["surface"] == "channel"
    assert result["delivered"] is True
    assert len(calls) == 1
    assert calls[0][0][0] == "openclaw_deliver"
    assert calls[0][0][2] == "Fallback line."
