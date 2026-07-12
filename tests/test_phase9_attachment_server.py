"""Focused server integration coverage for Phase 9 image attachments."""
from __future__ import annotations

import base64
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

import server
from alpecca import openclaw_bridge
from alpecca.attachment_ingress import DEFAULT_MAX_IMAGE_BYTES


def _png(width: int = 3, height: int = 2) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def _data_url(payload: bytes, mime_type: str = "image/png") -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _auth_headers() -> dict[str, str]:
    return {server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET}


def _assert_png_perception(
    perception: dict[str, object],
    payload: bytes,
    *,
    source: str,
    scope_prefix: str,
    status: str = "described",
) -> None:
    assert perception["status"] == status
    assert perception["source"] == source
    assert perception["mime_type"] == "image/png"
    assert perception["attachment_type"] == "image"
    assert str(perception["scope"]).startswith(scope_prefix)
    digest = hashlib.sha256(payload).hexdigest()
    assert perception["sha256"] == digest
    assert perception["provenance"] == f"sha256:{digest}"
    assert perception["metadata"] == {
        "size_bytes": len(payload),
        "width": 3,
        "height": 2,
        "duration_seconds": None,
    }
    assert perception["classification"] == {
        "processing_location": "local-only",
        "cloud_egress": "denied",
    }
    serialized = json.dumps(perception, sort_keys=True)
    assert "image_bytes" not in serialized
    assert base64.b64encode(payload).decode("ascii") not in serialized


@pytest.fixture
def client():
    test_client = TestClient(server.app)
    try:
        yield test_client
    finally:
        test_client.close()


@pytest.fixture(autouse=True)
def isolated_server(monkeypatch):
    chat_calls: list[dict[str, object]] = []

    async def fake_chat(text: str, **kwargs):
        chat_calls.append({"text": text, **kwargs})
        return {"reply": "stubbed attachment reply", "model_use": {"backend": "test"}}

    async def ignore_qualified_response(*_args, **_kwargs):
        return None

    async def ignore_capability_audit(*_args, **_kwargs):
        return True

    monkeypatch.setattr(server, "_ws_chat_turn_with_timeout", fake_chat)
    monkeypatch.setattr(server, "_record_qualified_creator_response", ignore_qualified_response)
    monkeypatch.setattr(server, "_record_capability_use", ignore_capability_audit)
    monkeypatch.setattr(server, "_mindscape_request_event_sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server.mind, "note_initiative_user_activity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server.mind, "see", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(openclaw_bridge, "try_deliver", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(server, "ws_clients", set())
    monkeypatch.setattr(server, "_ws_portal_epochs", {})
    monkeypatch.setattr(server, "_ws_portal_turns", {})
    monkeypatch.setattr(server, "_active_ws_portal", None)
    return chat_calls


def test_authenticated_house_channel_png_uses_one_local_vision_call_and_metadata(
    client, monkeypatch, isolated_server
):
    payload = _png()
    vision_calls: list[tuple[bytes, bool]] = []
    audit_calls: list[tuple[str, dict[str, str]]] = []

    def fake_vision(image_bytes: bytes, *, local_only: bool = False) -> str:
        vision_calls.append((image_bytes, local_only))
        return "A small PNG supplied by the creator."

    async def fake_audit(capability: str, **kwargs: str) -> bool:
        audit_calls.append((capability, kwargs))
        return True

    monkeypatch.setattr(server.vision, "describe_and_recognize", fake_vision)
    monkeypatch.setattr(server, "_record_capability_use", fake_audit)

    response = client.post(
        "/channel/house-hq",
        headers=_auth_headers(),
        json={"text": "What is in this image?", "image": _data_url(payload)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "stubbed attachment reply"
    assert vision_calls == [(payload, True)]
    assert audit_calls == [(
        "webcam",
        {"action": "capture", "principal": "creator", "source": "api"},
    )]
    assert len(isolated_server) == 1
    assert isolated_server[0]["image_desc"] == "A small PNG supplied by the creator."
    assert isolated_server[0]["private_context"] is True
    _assert_png_perception(
        body["perception"],
        payload,
        source="house-hq:chat-image",
        scope_prefix="turn:",
    )


def test_only_creator_house_sensor_marker_forces_private_chat_context(
    client, isolated_server
):
    response = client.post(
        "/channel/house-hq",
        headers=_auth_headers(),
        json={"text": "locally transcribed words", "private_perception": "microphone"},
    )
    assert response.status_code == 200
    assert isolated_server[-1]["private_context"] is True

    response = client.post(
        "/channel/inbound",
        headers=_auth_headers(),
        json={"text": "bridge words", "private_perception": "microphone"},
    )
    assert response.status_code == 200
    assert isolated_server[-1]["private_context"] is False


@pytest.mark.parametrize(
    ("image", "expected_status", "expected_reason"),
    (
        ("%%%%", 400, "malformed-base64"),
        (_data_url(_png(), "image/jpeg"), 415, "mime-mismatch"),
        (
            "A" * ((((DEFAULT_MAX_IMAGE_BYTES + 2) // 3) * 4) + 4),
            413,
            "size-limit",
        ),
    ),
    ids=("malformed-base64", "mime-mismatch", "size-limit"),
)
def test_house_channel_rejects_invalid_images_before_vision_or_chat(
    client,
    monkeypatch,
    isolated_server,
    image,
    expected_status,
    expected_reason,
):
    vision_calls = []
    monkeypatch.setattr(
        server.vision,
        "describe_and_recognize",
        lambda *_args, **_kwargs: vision_calls.append(True),
    )

    response = client.post(
        "/channel/house-hq",
        headers=_auth_headers(),
        json={"text": "Inspect this", "image": image},
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == {
        "code": "attachment_rejected",
        "reason": expected_reason,
    }
    assert vision_calls == []
    assert isolated_server == []


@pytest.mark.parametrize(
    ("content", "expected_detail"),
    (
        (b"{not-json", "body must be JSON"),
        (b"[]", "body must be a JSON object"),
        (
            json.dumps({"text": ["not", "a", "string"], "image": {"bad": True}}).encode(),
            "text or image required",
        ),
    ),
)
def test_house_channel_malformed_json_values_fail_cleanly(
    client, monkeypatch, isolated_server, content, expected_detail
):
    vision_calls = []
    monkeypatch.setattr(
        server.vision,
        "describe_and_recognize",
        lambda *_args, **_kwargs: vision_calls.append(True),
    )

    response = client.post(
        "/channel/house-hq",
        headers={**_auth_headers(), "Content-Type": "application/json"},
        content=content,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == expected_detail
    assert vision_calls == []
    assert isolated_server == []


def test_sight_push_requires_creator_before_image_or_vision_validation(
    client, monkeypatch
):
    vision_calls = []
    monkeypatch.setattr(
        server.vision,
        "describe_image",
        lambda *_args, **_kwargs: vision_calls.append(True),
    )

    response = client.post(
        "/sight/push",
        headers={"Content-Type": "image/png"},
        content=b"not even an image",
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "authorization required"
    assert vision_calls == []


def test_sight_push_fails_closed_when_capability_receipt_cannot_commit(
    client, monkeypatch
):
    vision_calls = []

    async def failed_audit(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(server, "_record_capability_use", failed_audit)
    monkeypatch.setattr(
        server.vision,
        "describe_image",
        lambda *_args, **_kwargs: vision_calls.append(True),
    )

    response = client.post(
        "/sight/push",
        headers={**_auth_headers(), "Content-Type": "image/png"},
        content=_png(),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "capability_audit_unavailable"}
    assert vision_calls == []


def test_sight_push_validates_png_and_uses_ambient_local_vision(
    client, monkeypatch
):
    payload = _png()
    vision_calls: list[tuple[bytes, str, bool]] = []
    audit_calls: list[tuple[str, dict[str, str]]] = []

    def fake_describe(
        image_bytes: bytes, prompt: str, *, ambient: bool = False
    ) -> str:
        vision_calls.append((image_bytes, prompt, ambient))
        return "The creator is reviewing a small test image."

    async def fake_audit(capability: str, **kwargs: str) -> bool:
        audit_calls.append((capability, kwargs))
        return True

    monkeypatch.setattr(server.vision, "describe_image", fake_describe)
    monkeypatch.setattr(server, "_record_capability_use", fake_audit)

    response = client.post(
        "/sight/push",
        headers={**_auth_headers(), "Content-Type": "image/png"},
        content=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "The creator is reviewing a small test image."
    assert vision_calls == [(payload, server.vision._SCREEN_PROMPT, True)]
    assert audit_calls == [(
        "screen_sight",
        {"action": "capture", "principal": "creator", "source": "api"},
    )]
    _assert_png_perception(
        body["perception"],
        payload,
        source="house-hq:screen-share",
        scope_prefix="sight:",
    )


@pytest.mark.parametrize(
    ("payload", "content_type", "expected_status", "expected_reason"),
    (
        (_png(), "image/jpeg", 415, "mime-mismatch"),
        (_png(0, 2), "image/png", 422, "invalid-dimensions"),
    ),
)
def test_sight_push_rejects_raw_mime_or_dimensions_before_vision(
    client,
    monkeypatch,
    payload,
    content_type,
    expected_status,
    expected_reason,
):
    vision_calls = []
    monkeypatch.setattr(
        server.vision,
        "describe_image",
        lambda *_args, **_kwargs: vision_calls.append(True),
    )

    response = client.post(
        "/sight/push",
        headers={**_auth_headers(), "Content-Type": content_type},
        content=payload,
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == {
        "code": "attachment_rejected",
        "reason": expected_reason,
    }
    assert vision_calls == []


def test_websocket_png_uses_one_local_combined_vision_call_and_returns_metadata(
    client, monkeypatch, isolated_server
):
    payload = _png()
    vision_calls: list[tuple[bytes, bool]] = []

    def fake_vision(image_bytes: bytes, *, local_only: bool = False) -> str:
        vision_calls.append((image_bytes, local_only))
        return "A websocket PNG."

    monkeypatch.setattr(server.vision, "describe_and_recognize", fake_vision)

    with client.websocket_connect(
        "/ws/house-hq", headers=_auth_headers()
    ) as websocket:
        assert websocket.receive_json()["type"] == "state"
        websocket.send_json(["malformed", "but", "nonfatal"])
        websocket.send_json({
            "source": "house-chat",
            "text": "Look at this",
            "image": _data_url(payload),
            "request_id": "phase9-ws-valid",
        })
        message = websocket.receive_json()

    assert message["type"] == "reply"
    assert message["request_id"] == "phase9-ws-valid"
    assert vision_calls == [(payload, True)]
    assert len(isolated_server) == 1
    assert isolated_server[0]["image_desc"] == "A websocket PNG."
    assert isolated_server[0]["private_context"] is True
    _assert_png_perception(
        message["perception"],
        payload,
        source="house-hq:websocket-image",
        scope_prefix="turn:",
    )


def test_creator_virtual_app_microphone_marker_forces_private_context(
    client, isolated_server
):
    with client.websocket_connect("/ws", headers=_auth_headers()) as websocket:
        assert websocket.receive_json()["type"] == "state"
        websocket.send_json({
            "source": "chat",
            "text": "locally transcribed virtual-app words",
            "private_perception": "microphone",
            "request_id": "phase9-ws-microphone",
        })
        message = websocket.receive_json()

    assert message["type"] == "reply"
    assert isolated_server[-1]["private_context"] is True


def test_websocket_rejects_malformed_image_without_vision_or_chat(
    client, monkeypatch, isolated_server
):
    vision_calls = []
    monkeypatch.setattr(
        server.vision,
        "describe_and_recognize",
        lambda *_args, **_kwargs: vision_calls.append(True),
    )

    with client.websocket_connect(
        "/ws/house-hq", headers=_auth_headers()
    ) as websocket:
        assert websocket.receive_json()["type"] == "state"
        websocket.send_json({
            "source": "house-chat",
            "text": "This must fail closed",
            "image": "%%%%",
            "request_id": "phase9-ws-invalid",
        })
        message = websocket.receive_json()

    assert message == {
        "type": "error",
        "request_id": "phase9-ws-invalid",
        "source": "house-chat",
        "code": "attachment_rejected",
        "reason": "malformed-base64",
    }
    assert vision_calls == []
    assert isolated_server == []
