from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from alpecca import turn_context
import server


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.fail_sends = False

    async def send_json(self, payload: dict) -> None:
        if self.fail_sends:
            raise RuntimeError("socket closed")
        self.sent.append(payload)


@pytest.fixture(autouse=True)
def isolated_portal_registry():
    clients = set(server.ws_clients)
    epochs = dict(server._ws_portal_epochs)
    turns = dict(server._ws_portal_turns)
    active = server._active_ws_portal
    server.ws_clients.clear()
    server._ws_portal_epochs.clear()
    server._ws_portal_turns.clear()
    server._active_ws_portal = None
    yield
    for turn in server._ws_portal_turns.values():
        turn.cancel("test_cleanup")
    server.ws_clients.clear()
    server.ws_clients.update(clients)
    server._ws_portal_epochs.clear()
    server._ws_portal_epochs.update(epochs)
    server._ws_portal_turns.clear()
    server._ws_portal_turns.update(turns)
    server._active_ws_portal = active


def _turn(epoch: str, conversation: str = "conversation") -> turn_context.TurnContext:
    return turn_context.TurnContext.create(
        conversation,
        principal="creator",
        surface="websocket",
        portal_epoch=epoch,
    )


def test_new_epoch_fences_stale_turn_send_broadcast_and_finalizer():
    async def exercise() -> None:
        old_socket = FakeSocket()
        old_epoch = server._open_ws_portal(old_socket, "epoch-old")
        old_turn = _turn(old_epoch, "old-conversation")
        assert server._begin_ws_portal_turn(old_socket, old_turn) is True
        assert await server._send_ws_json(
            old_socket, {"type": "reply", "value": "current"}, turn=old_turn
        ) is True

        new_socket = FakeSocket()
        new_epoch = server._open_ws_portal(new_socket, "epoch-new")
        assert old_turn.cancelled.is_set()
        assert old_turn.barrier.reason == "portal_epoch_replaced"
        assert await server._send_ws_json(
            old_socket, {"type": "reply", "value": "late"}, turn=old_turn
        ) is False
        await server._broadcast({"type": "activity", "value": "late"}, turn=old_turn)

        new_turn = _turn(new_epoch, "new-conversation")
        assert server._begin_ws_portal_turn(new_socket, new_turn) is True
        await server._broadcast(
            {"type": "activity", "value": "current"}, turn=new_turn
        )
        assert server._retire_ws_portal(
            old_socket, portal_epoch=old_epoch, reason="stale_finalizer"
        ) is False
        assert server._ws_portal_epoch_current(new_socket, new_epoch) is True
        assert old_socket.sent == [{"type": "reply", "value": "current"}]
        assert new_socket.sent == [{"type": "activity", "value": "current"}]

    asyncio.run(exercise())


def test_disconnect_fences_queued_tokens_and_late_broadcasts():
    async def exercise() -> None:
        socket = FakeSocket()
        epoch = server._open_ws_portal(socket, "epoch-disconnect")
        turn = _turn(epoch)
        assert server._begin_ws_portal_turn(socket, turn) is True
        assert server._retire_ws_portal(
            socket, portal_epoch=epoch, reason="disconnect"
        ) is True

        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait("late token")
        queue.put_nowait(None)
        await server._pump_reply_tokens(socket, queue, "request-1", "house-chat", turn)
        await server._broadcast({"type": "reply", "value": "late"}, turn=turn)

        assert turn.cancelled.is_set()
        assert turn.barrier.reason == "disconnect"
        assert socket.sent == []
        assert socket not in server.ws_clients

    asyncio.run(exercise())


def test_send_failure_retires_epoch_and_cancels_active_turn():
    async def exercise() -> None:
        socket = FakeSocket()
        epoch = server._open_ws_portal(socket, "epoch-failed-send")
        turn = _turn(epoch)
        assert server._begin_ws_portal_turn(socket, turn) is True
        socket.fail_sends = True

        assert await server._send_ws_json(
            socket, {"type": "reply"}, turn=turn
        ) is False
        assert turn.cancelled.is_set()
        assert turn.barrier.reason == "send_failed"
        assert socket not in server._ws_portal_epochs
        assert socket not in server.ws_clients

    asyncio.run(exercise())


def test_timeout_fallback_sends_once_without_cancelled_cognition_writes(monkeypatch):
    writes: list[str] = []
    monkeypatch.setattr(
        server.cognition_mod, "record_chat_turn",
        lambda *_args, **_kwargs: writes.append("chat"),
    )
    monkeypatch.setattr(
        server.cognition_mod, "set_intent",
        lambda *_args, **_kwargs: writes.append("intent"),
    )
    monkeypatch.setattr(server.cognition_mod, "current_intent", lambda: {})

    async def exercise() -> None:
        socket = FakeSocket()
        epoch = server._open_ws_portal(socket, "epoch-timeout")
        turn = _turn(epoch)
        assert server._begin_ws_portal_turn(socket, turn) is True
        assert turn.cancel("timeout") is True
        result = server._ws_chat_timeout_result("hello", turn=turn)

        assert writes == []
        assert result["reply"]
        assert result["turn"]["cancel_reason"] == "timeout"
        assert await server._send_ws_json(
            socket, {"type": "reply", **result}, turn=turn
        ) is False
        assert await server._send_ws_json(
            socket, {"type": "reply", **result}, turn=turn,
            allow_cancelled=True,
        ) is True
        assert server._finish_ws_portal_turn(socket, turn) is True
        assert await server._send_ws_json(
            socket, {"type": "reply", **result}, turn=turn,
            allow_cancelled=True,
        ) is False
        assert len(socket.sent) == 1

    asyncio.run(exercise())


def test_scoped_fallback_audit_passes_memory_scope_when_supported(monkeypatch):
    captured: dict = {}

    class ScopedChatTurn:
        __dataclass_fields__ = {"scope": object()}

        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(server.cognition_mod, "ChatTurn", ScopedChatTurn)
    monkeypatch.setattr(
        server.cognition_mod, "record_chat_turn", lambda value: value
    )
    monkeypatch.setattr(server.cognition_mod, "set_intent", lambda value: value)
    monkeypatch.setattr(server.cognition_mod, "current_intent", lambda: {})
    turn = turn_context.TurnContext.create(
        "scoped-fallback",
        principal="guest",
        surface="websocket",
        privacy_scope="guest-private-scope",
        portal_epoch="epoch-scope",
    )

    server._ws_chat_timeout_result("echo repair", turn=turn)

    assert captured["scope"] == turn.memory_scope
    assert captured["privacy_class"] == turn.memory_scope


def test_model_chat_runs_after_mind_lock_is_released(monkeypatch):
    lock_state = {"held": False}

    class TrackingLock:
        async def __aenter__(self):
            assert lock_state["held"] is False
            lock_state["held"] = True

        async def __aexit__(self, *_args):
            lock_state["held"] = False

    def perceive(_observation) -> None:
        assert lock_state["held"] is True

    def chat(_text, **_kwargs) -> dict:
        assert lock_state["held"] is False
        return {"reply": "model result"}

    monkeypatch.setattr(server, "mind_lock", TrackingLock())
    monkeypatch.setattr(
        server, "_observe", lambda: SimpleNamespace(window_title="focused test")
    )
    monkeypatch.setattr(server.mind, "perceive", perceive)
    monkeypatch.setattr(server.mind, "chat", chat)
    turn = _turn("epoch-lock")

    result = asyncio.run(server._locked_ws_chat_turn(turn, "hello"))

    assert result["reply"] == "model result"
    assert lock_state["held"] is False
