from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

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
    surfaces = dict(server._ws_portal_surfaces)
    active = server._active_ws_portal
    server.ws_clients.clear()
    server._ws_portal_epochs.clear()
    server._ws_portal_turns.clear()
    server._ws_portal_surfaces.clear()
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
    server._ws_portal_surfaces.clear()
    server._ws_portal_surfaces.update(surfaces)
    server._active_ws_portal = active


def _turn(epoch: str, conversation: str = "conversation") -> turn_context.TurnContext:
    return turn_context.TurnContext.create(
        conversation,
        principal="creator",
        surface="websocket",
        portal_epoch=epoch,
    )


def test_server_owned_conversation_identity_survives_creator_reconnects():
    first = server._server_conversation_id(
        "creator", "websocket", ephemeral_seed="portal-one"
    )
    reconnected = server._server_conversation_id(
        "creator", "websocket", ephemeral_seed="portal-two"
    )
    other_surface = server._server_conversation_id(
        "creator", "channel", ephemeral_seed="portal-two"
    )

    assert first == reconnected == "creator-websocket-primary"
    assert other_surface == "creator-channel-primary"
    assert other_surface != first


def test_guest_conversation_identity_is_ephemeral_without_server_subject():
    first = server._server_conversation_id(
        "guest", "websocket", ephemeral_seed="portal-one"
    )
    second = server._server_conversation_id(
        "guest", "websocket", ephemeral_seed="portal-two"
    )

    assert first == "guest-websocket-portal-one"
    assert second == "guest-websocket-portal-two"
    assert first != second


def test_house_hq_has_server_owned_transport_routes():
    routes = {getattr(route, "path", "") for route in server.app.routes}

    assert "/channel/house-hq" in routes
    assert "/ws/house-hq" in routes


def test_android_webview_socket_requires_device_bound_mobile_provenance():
    android = SimpleNamespace(
        url=SimpleNamespace(path="/ws"),
        headers={"user-agent": "Mozilla/5.0 AlpeccaAndroid/2.2.21"},
    )
    browser = SimpleNamespace(
        url=SimpleNamespace(path="/ws"),
        headers={"user-agent": "Mozilla/5.0"},
    )
    house = SimpleNamespace(
        url=SimpleNamespace(path="/ws/house-hq"),
        headers={"user-agent": "Mozilla/5.0 AlpeccaAndroid/2.2.21"},
    )

    assert server._websocket_route_surface(android) == "websocket"
    assert server._websocket_route_surface(
        android,
        trusted_native_device=True,
    ) == "mobile"
    assert server._websocket_route_surface(browser) == "websocket"
    assert server._websocket_route_surface(house) == "house-hq"
    assert server._websocket_route_surface(
        house,
        trusted_native_device=True,
    ) == "mobile"


def test_verified_mobile_surface_is_retained_only_for_the_live_portal():
    socket = FakeSocket()
    socket.url = SimpleNamespace(path="/ws")
    socket.headers = {"user-agent": "Mozilla/5.0 AlpeccaAndroid/2.2.21"}

    epoch = server._open_ws_portal(
        socket,
        "epoch-mobile",
        verified_surface="mobile",
    )

    assert server._websocket_route_surface(socket) == "mobile"
    assert server._retire_ws_portal(
        socket,
        portal_epoch=epoch,
        reason="test_complete",
    ) is True
    assert server._websocket_route_surface(socket) == "websocket"


def test_house_http_fallback_requires_verified_device_and_android_identity():
    origin = "https://creatorjd-alpecca-survival-core.hf.space"
    android_request = SimpleNamespace(
        url=SimpleNamespace(
            scheme="https",
            netloc="creatorjd-alpecca-survival-core.hf.space",
            hostname="creatorjd-alpecca-survival-core.hf.space",
        ),
        headers={"user-agent": "Mozilla/5.0 AlpeccaAndroid/2.2.21"},
        client=SimpleNamespace(host="198.51.100.50"),
    )
    browser_request = SimpleNamespace(
        url=android_request.url,
        headers={"user-agent": "Mozilla/5.0"},
        client=android_request.client,
    )
    device_session = server.auth_mod.AuthDecision(
        True,
        "session_cookie",
        "ok",
        principal="creator",
        device_id="device-id-12345",
        session_origin=origin,
    )
    password_session = server.auth_mod.AuthDecision(
        True,
        "session_cookie",
        "ok",
        principal="creator",
        session_origin="",
    )

    assert server._authenticated_request_surface(
        android_request,
        "house-hq",
        device_session,
    ) == "mobile"
    assert server._authenticated_request_surface(
        browser_request,
        "house-hq",
        device_session,
    ) == "house-hq"
    assert server._authenticated_request_surface(
        android_request,
        "house-hq",
        password_session,
    ) == "house-hq"
    assert server._authenticated_request_surface(
        android_request,
        "channel",
        device_session,
    ) == "channel"


def test_websocket_handshake_labels_mobile_only_for_active_device_session(monkeypatch):
    from fastapi.testclient import TestClient

    class ActiveDeviceRegistry:
        @staticmethod
        def session_valid(device_id, issued_at):
            return device_id == "device-id-12345" and isinstance(issued_at, int)

    monkeypatch.setattr(server, "_TRUSTED_DEVICE_REGISTRY", ActiveDeviceRegistry())
    app_user_agent = "Mozilla/5.0 AlpeccaAndroid/2.2.21"

    local_client = TestClient(
        server.app,
        client=("127.0.0.1", 50109),
    )
    with local_client.websocket_connect(
        "/ws/house-hq",
        headers={
            server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET,
            "user-agent": app_user_agent,
        },
    ) as websocket:
        state = websocket.receive_json()
        assert state["capability_connection"]["surface"] == "house-hq"

    device_cookie = server._AUTHORITY.issue_session_cookie(
        secure=False,
        device_id="device-id-12345",
        origin="http://testserver",
    )
    with local_client.websocket_connect(
        "/ws/house-hq",
        headers={
            "cookie": (
                f"{server.auth_mod.SESSION_COOKIE_NAME}={device_cookie.value}"
            ),
            "origin": "http://testserver",
            "user-agent": app_user_agent,
        },
    ) as websocket:
        state = websocket.receive_json()
        assert state["capability_connection"]["surface"] == "mobile"


def test_hugging_face_private_proxy_preserves_mobile_websocket_session(monkeypatch):
    from fastapi.testclient import TestClient

    class ActiveDeviceRegistry:
        @staticmethod
        def session_valid(device_id, issued_at):
            return device_id == "device-id-12345" and isinstance(issued_at, int)

    space_host = "creatorjd-alpecca-survival-core.hf.space"
    monkeypatch.setattr(server, "_TRUSTED_DEVICE_REGISTRY", ActiveDeviceRegistry())
    monkeypatch.setenv("SPACE_HOST", space_host)
    device_cookie = server._AUTHORITY.issue_session_cookie(
        secure=True,
        device_id="device-id-12345",
        origin=f"https://{space_host}",
    )
    client = TestClient(
        server.app,
        base_url=f"http://{space_host}",
        client=("10.112.73.211", 50110),
    )

    with client.websocket_connect(
        f"ws://{space_host}/ws/house-hq",
        headers={
            "cookie": (
                f"{server.auth_mod.SESSION_COOKIE_NAME}={device_cookie.value}"
            ),
            "origin": f"https://{space_host}",
            "x-forwarded-proto": "https",
            "user-agent": "Mozilla/5.0 AlpeccaAndroid/2.2.21",
        },
    ) as websocket:
        state = websocket.receive_json()
        assert state["capability_connection"]["surface"] == "mobile"


def test_websocket_forwarded_https_requires_exact_space_proxy_boundary(monkeypatch):
    from fastapi.testclient import TestClient

    class ActiveDeviceRegistry:
        @staticmethod
        def session_valid(_device_id, _issued_at):
            return True

    space_host = "creatorjd-alpecca-survival-core.hf.space"
    monkeypatch.setattr(server, "_TRUSTED_DEVICE_REGISTRY", ActiveDeviceRegistry())
    monkeypatch.setenv("SPACE_HOST", space_host)
    device_cookie = server._AUTHORITY.issue_session_cookie(
        secure=True,
        device_id="device-id-12345",
        origin=f"https://{space_host}",
    )
    client = TestClient(
        server.app,
        base_url=f"http://{space_host}",
        client=("198.51.100.50", 50111),
    )

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"ws://{space_host}/ws/house-hq",
            headers={
                "cookie": (
                    f"{server.auth_mod.SESSION_COOKIE_NAME}={device_cookie.value}"
                ),
                "origin": f"https://{space_host}",
                "x-forwarded-proto": "https",
                "user-agent": "Mozilla/5.0 AlpeccaAndroid/2.2.21",
            },
        ):
            pass


def test_android_house_http_fallback_uses_mobile_turn_context(monkeypatch):
    from fastapi.testclient import TestClient
    from alpecca import openclaw_bridge

    captured: dict[str, object] = {}

    class ActiveDeviceRegistry:
        @staticmethod
        def session_valid(device_id, issued_at):
            return device_id == "device-id-12345" and isinstance(issued_at, int)

    async def fake_chat(_text, **kwargs):
        captured["turn"] = kwargs["turn"]
        return {"reply": "mobile reply"}

    monkeypatch.setattr(server, "_TRUSTED_DEVICE_REGISTRY", ActiveDeviceRegistry())
    monkeypatch.setattr(server, "_ws_chat_turn_with_timeout", fake_chat)
    monkeypatch.setattr(server.mind, "note_initiative_user_activity", lambda *_args: None)
    monkeypatch.setattr(server, "_mindscape_request_event_sync", lambda *_args: None)
    monkeypatch.setattr(openclaw_bridge, "try_deliver", lambda *_args, **_kwargs: False)
    origin = "https://testserver"
    device_cookie = server._AUTHORITY.issue_session_cookie(
        secure=True,
        device_id="device-id-12345",
        origin=origin,
    )
    client = TestClient(
        server.app,
        base_url=origin,
        client=("198.51.100.50", 50112),
    )

    response = client.post(
        "/channel/house-hq",
        headers={
            "cookie": (
                f"{server.auth_mod.SESSION_COOKIE_NAME}={device_cookie.value}"
            ),
            "origin": origin,
            "user-agent": "Mozilla/5.0 AlpeccaAndroid/2.2.21",
        },
        json={"text": "hello from the signed app", "channel": "house-chat"},
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "mobile reply"
    turn = captured["turn"]
    assert isinstance(turn, turn_context.TurnContext)
    assert turn.surface == "mobile"
    assert turn.conversation_id == "creator-mobile-primary"


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


def test_creator_scoped_fallback_audit_passes_memory_scope_when_supported(monkeypatch):
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
        principal="creator",
        surface="websocket",
        privacy_scope="creator-private-scope",
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
