"""Server wiring for short-lived, House-bound private capability leases."""
from __future__ import annotations

import asyncio
import base64
import io
import threading
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from alpecca import capability_leases as leases_mod
from alpecca import desktop as desktop_mod
from alpecca import openclaw_bridge
from alpecca import people


class _HouseSocket:
    class _Url:
        path = "/ws/house-hq"

    url = _Url()


class _ClassicSocket:
    class _Url:
        path = "/ws"

    url = _Url()


def _auth_headers() -> dict[str, str]:
    return {server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET}


def _png(width: int = 3, height: int = 2) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def _data_url(payload: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")


def _wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(100)
        writer.writeframes(b"\x00\x00" * 50)
    return buffer.getvalue()


def _lease_headers(lease: dict[str, object], purpose: str, epoch: str) -> dict[str, str]:
    return {
        **_auth_headers(),
        leases_mod.TOKEN_HEADER: str(lease["token"]),
        leases_mod.PURPOSE_HEADER: purpose,
        leases_mod.CONNECTION_HEADER: epoch,
    }


@pytest.fixture
def lease_server(tmp_path: Path, monkeypatch):
    store = leases_mod.CapabilityLeaseStore(
        tmp_path / "capability-leases.db",
        seal_key=b"phase9-server-test-key",
    )
    ready = threading.Event()
    ready.set()
    socket = _HouseSocket()
    epoch = "house-epoch-test"
    monkeypatch.setattr(server, "_capability_lease_store", store)
    monkeypatch.setattr(server, "_capability_lease_recovery_ready", ready)
    monkeypatch.setattr(server, "_ws_portal_epochs", {socket: epoch})
    monkeypatch.setattr(server, "_ws_portal_turns", {})
    monkeypatch.setattr(server, "_active_ws_portal", (socket, epoch))
    monkeypatch.setattr(server, "ws_clients", {socket})
    for name in ("ALPECCA_FACE", "ALPECCA_SIGHT", "ALPECCA_VOICE", "ALPECCA_FILES"):
        monkeypatch.setenv(name, "1")

    client = TestClient(server.app)
    try:
        yield client, store, socket, epoch
    finally:
        client.close()


def _issue(
    client: TestClient,
    epoch: str,
    purpose: str,
    *,
    source_ref: dict[str, str] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {"connection_id": epoch, "purpose": purpose}
    if source_ref is not None:
        body["source_ref"] = source_ref
    response = client.post(
        "/security/capability-leases",
        headers=_auth_headers(),
        json=body,
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_issue_requires_creator_and_live_supported_connection(lease_server):
    client, _store, _socket, epoch = lease_server
    anonymous = client.post(
        "/security/capability-leases",
        json={"connection_id": epoch, "purpose": "camera_frame"},
    )
    assert anonymous.status_code == 401

    stale = client.post(
        "/security/capability-leases",
        headers=_auth_headers(),
        json={"connection_id": "stale-epoch", "purpose": "camera_frame"},
    )
    assert stale.status_code == 403
    assert stale.json()["detail"]["reason"] == "connection_not_active"

    issued = _issue(client, epoch, "camera_frame")
    assert issued["surface"] == "house-hq"


def test_screen_lease_validates_start_consumes_frames_and_rejects_missing_lease(
    lease_server, monkeypatch
):
    client, store, _socket, epoch = lease_server
    lease = _issue(client, epoch, "screen_share")
    headers = {
        **_lease_headers(lease, "screen_share", epoch),
        "Content-Type": "image/png",
    }
    calls: list[bytes] = []
    sharing_states: list[bool] = []

    monkeypatch.setattr(
        server.mind,
        "set_screen_sharing",
        lambda active: sharing_states.append(bool(active)) or None,
    )
    monkeypatch.setattr(server.mind, "see", lambda description: None)
    monkeypatch.setattr(
        server.vision,
        "describe_image",
        lambda image, _prompt, ambient=False: calls.append(image) or "screen",
    )

    async def audit(*_args, **_kwargs):
        return True

    monkeypatch.setattr(server, "_record_capability_use", audit)

    start = client.post("/observatory/screen/start", headers=headers)
    assert start.status_code == 200
    assert store.status()["active"][0]["uses"] == 0

    pushed = client.post("/sight/push", headers=headers, content=_png())
    assert pushed.status_code == 200
    assert calls == [_png()]
    assert store.status()["active"][0]["uses"] == 1

    stopped = client.post("/observatory/screen/stop", headers=headers)
    assert stopped.status_code == 200
    assert stopped.json()["lease_stopped"] is True
    assert store.status()["active"] == []
    assert sharing_states == [True, False]

    body_reads: list[bool] = []

    async def unexpected_read(*_args, **_kwargs):
        body_reads.append(True)
        raise AssertionError("lease denial must happen before screen body ingress")

    monkeypatch.setattr(server, "_read_bounded_body", unexpected_read)
    denied = client.post(
        "/sight/push",
        headers={**_auth_headers(), "Content-Type": "image/png"},
        content=_png(),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["reason"] == "lease_required"
    assert body_reads == []


def test_audio_leases_are_separate_one_use_grants(lease_server, monkeypatch):
    client, store, _socket, epoch = lease_server
    payload = _wav()
    heard: list[bytes] = []
    enrolled: list[bytes] = []

    monkeypatch.setattr(
        server.hearing,
        "transcribe",
        lambda audio: heard.append(audio) or "hello",
    )
    monkeypatch.setattr(people, "identify_voice", lambda _audio: None)
    monkeypatch.setattr(
        people,
        "enroll_creator_voice",
        lambda audio: enrolled.append(audio) or True,
    )

    async def audit(*_args, **_kwargs):
        return True

    monkeypatch.setattr(server, "_record_capability_use", audit)

    push = _issue(client, epoch, "push_to_talk")
    response = client.post(
        "/listen",
        headers={
            **_lease_headers(push, "push_to_talk", epoch),
            "Content-Type": "audio/wav",
        },
        content=payload,
    )
    assert response.status_code == 200
    assert response.json()["text"] == "hello"
    assert heard == [payload]

    replay = client.post(
        "/listen",
        headers={
            **_lease_headers(push, "push_to_talk", epoch),
            "Content-Type": "audio/wav",
        },
        content=payload,
    )
    assert replay.status_code == 409
    assert replay.json()["detail"]["reason"] == "lease_stopped"
    assert heard == [payload]

    enrollment = _issue(client, epoch, "voice_enrollment")
    response = client.post(
        "/people/enroll_voice",
        headers={
            **_lease_headers(enrollment, "voice_enrollment", epoch),
            "Content-Type": "audio/wav",
        },
        content=payload,
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert enrolled == [payload]
    assert store.status()["active"] == []


def test_camera_and_file_leases_bind_effect_to_connection_and_resource(
    lease_server, monkeypatch, tmp_path
):
    client, store, _socket, epoch = lease_server
    payload = _png()
    vision_calls: list[bytes] = []
    chat_calls: list[dict[str, object]] = []

    async def fake_chat(text: str, **kwargs):
        chat_calls.append({"text": text, **kwargs})
        return {"reply": "grounded reply"}

    async def audit(*_args, **_kwargs):
        return True

    monkeypatch.setattr(server, "_ws_chat_turn_with_timeout", fake_chat)
    monkeypatch.setattr(server, "_record_capability_use", audit)
    monkeypatch.setattr(server, "_mindscape_request_event_sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server.mind, "note_initiative_user_activity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(openclaw_bridge, "try_deliver", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        server.vision,
        "describe_and_recognize",
        lambda image, local_only=False: vision_calls.append(image) or "camera image",
    )

    camera = _issue(client, epoch, "camera_frame")
    camera_response = client.post(
        "/channel/house-hq",
        headers={
            **_lease_headers(camera, "camera_frame", epoch),
            "Content-Type": "application/json",
        },
        json={"text": "look", "image": _data_url(payload)},
    )
    assert camera_response.status_code == 200
    assert vision_calls == [payload]
    assert chat_calls[-1]["image_desc"] == "camera image"

    root = tmp_path / "source-root"
    root.mkdir()
    (root / "notes.md").write_text("bounded local note", encoding="utf-8")
    monkeypatch.setattr(desktop_mod, "inspection_roots", lambda: {"general": root})
    source_ref = {"root": "general", "rel": "notes.md"}
    file_lease = _issue(
        client,
        epoch,
        "file_source_ref",
        source_ref=source_ref,
    )
    file_response = client.post(
        "/channel/house-hq",
        headers={
            **_lease_headers(file_lease, "file_source_ref", epoch),
            "Content-Type": "application/json",
        },
        json={"text": "read", "source_ref": source_ref},
    )
    assert file_response.status_code == 200
    assert "bounded local note" in str(chat_calls[-1]["attachment_context"])

    wrong_ref = {"root": "general", "rel": "other.md"}
    second = _issue(client, epoch, "file_source_ref", source_ref=source_ref)
    read_calls: list[bool] = []

    def unexpected_file_read(*_args, **_kwargs):
        read_calls.append(True)
        raise AssertionError("resource mismatch must fail before file ingress")

    monkeypatch.setattr(server.file_ingress_mod, "ingest_file", unexpected_file_read)
    mismatch = client.post(
        "/channel/house-hq",
        headers={
            **_lease_headers(second, "file_source_ref", epoch),
            "Content-Type": "application/json",
        },
        json={"text": "read", "source_ref": wrong_ref},
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["detail"]["reason"] == "resource_mismatch"
    assert read_calls == []
    active_ids = {row["lease_id"] for row in store.status()["active"]}
    assert second["lease_id"] in active_ids


def test_house_camera_missing_lease_fails_before_image_ingress(
    lease_server,
    monkeypatch,
):
    client, _store, _socket, _epoch = lease_server
    ingress_calls: list[bool] = []

    def unexpected_ingress(*_args, **_kwargs):
        ingress_calls.append(True)
        raise AssertionError("camera ingress must not run before lease validation")

    monkeypatch.setattr(server.attachment_ingress_mod, "ingest_image", unexpected_ingress)
    response = client.post(
        "/channel/house-hq",
        headers=_auth_headers(),
        json={"text": "look", "image": _data_url(_png())},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "lease_required"
    assert ingress_calls == []


def test_generic_channel_cannot_bypass_scoped_image_routes(
    lease_server,
    monkeypatch,
):
    client, _store, _socket, _epoch = lease_server
    ingress_calls: list[bool] = []
    monkeypatch.setattr(
        server.attachment_ingress_mod,
        "ingest_image",
        lambda *_args, **_kwargs: ingress_calls.append(True),
    )
    response = client.post(
        "/channel/inbound",
        headers=_auth_headers(),
        json={"text": "look", "image": _data_url(_png())},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "attachment_rejected",
        "reason": "image-route-not-authorized",
    }
    assert ingress_calls == []


def test_websocket_camera_consume_and_disconnect_revocation(lease_server):
    _client, store, socket, epoch = lease_server
    lease = store.issue(
        connection_id=epoch,
        principal="creator",
        privacy_scope="creator-personal",
        surface="house-hq",
        purpose="camera_frame",
        auth_mechanism="test",
    )
    consumed = asyncio.run(
        server._consume_ws_capability_lease(
            {
                "capability_lease": lease["token"],
                "capability_purpose": "camera_frame",
                "capability_connection": epoch,
            },
            portal_epoch=epoch,
            purpose="camera_frame",
            bytes_used=10,
        )
    )
    assert consumed["uses"] == 1

    screen = store.issue(
        connection_id=epoch,
        principal="creator",
        privacy_scope="creator-personal",
        surface="house-hq",
        purpose="screen_share",
        auth_mechanism="test",
    )
    assert server._retire_ws_portal(
        socket,
        portal_epoch=epoch,
        reason="disconnect",
    ) is True
    status = store.status()
    assert status["active"] == []
    stop = next(
        receipt for receipt in status["receipts"]
        if receipt["lease_id"] == screen["lease_id"] and receipt["event"] == "stop"
    )
    assert stop["reason"] == "disconnect"


def test_lease_cors_headers_and_status_are_no_store(lease_server):
    client, _store, _socket, _epoch = lease_server
    preflight = client.options(
        "/security/capability-leases",
        headers={
            "Origin": "http://127.0.0.1:8765",
            "Access-Control-Request-Method": "POST",
        },
    )
    allowed = preflight.headers.get("access-control-allow-headers", "")
    assert leases_mod.TOKEN_HEADER in allowed
    assert leases_mod.PURPOSE_HEADER in allowed
    assert leases_mod.CONNECTION_HEADER in allowed

    status = client.get(
        "/security/capability-leases",
        headers=_auth_headers(),
    )
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert "policies" in status.json()


def test_classic_portal_can_issue_media_but_not_house_only_leases(
    lease_server,
    monkeypatch,
):
    client, _store, _socket, _epoch = lease_server
    socket = _ClassicSocket()
    epoch = "classic-epoch-test"
    monkeypatch.setattr(server, "_ws_portal_epochs", {socket: epoch})
    monkeypatch.setattr(server, "_active_ws_portal", (socket, epoch))

    camera = _issue(client, epoch, "camera_frame")
    assert camera["surface"] == "websocket"

    screen = client.post(
        "/security/capability-leases",
        headers=_auth_headers(),
        json={"connection_id": epoch, "purpose": "screen_share"},
    )
    assert screen.status_code == 403
    assert screen.json()["detail"]["reason"] == "surface_mismatch"
