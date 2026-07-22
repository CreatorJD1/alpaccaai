from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

import server
from alpecca import egress_consent as consent_mod
from alpecca import interactive_egress
from alpecca import vision


class Clock:
    def now(self) -> float:
        return 10_000.0


def _runtime(tmp_path: Path):
    authority = interactive_egress.InteractiveCreatorAuthority(
        tmp_path / "requests.sqlite3"
    )
    policy = consent_mod.EgressPolicy(
        policy_id="private-perception-egress",
        version=1,
        routes=(
            consent_mod.AllowedEgressRoute(
                route_id="vision-ollama-cloud",
                provider="ollama-cloud",
                deployment="creator-cloud-vision",
                model="qwen3.5-vl:cloud",
                capability="private-image-description",
                purpose="describe-private-image",
                processing_location="provider-managed",
                destination_class="managed-model-api",
                transport_route="https://example.invalid/api/chat",
                max_uses=1,
            ),
        ),
    )
    anchor = consent_mod.SQLiteMonotonicAnchor(
        tmp_path / "anchor.sqlite3",
        anchor_key=b"anchor-key",
        anchor_key_version="test-v1",
    )
    ledger = consent_mod.EgressConsentLedger(
        tmp_path / "ledger.sqlite3",
        seal_key=b"ledger-key",
        seal_key_version="test-v1",
        authority=authority,
        policy=policy,
        clock=Clock(),
        anchor=anchor,
    )
    return {
        "authority": authority,
        "ledger": ledger,
        "gate": consent_mod.PerceptionEgressGate(ledger),
    }


def _png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x03\x00\x00\x00\x02"
        b"\x08\x02\x00\x00\x00\x00\x00\x00\x00"
    )


def _data_url(payload: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")


def _headers() -> dict[str, str]:
    return {server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET}


def test_authority_requires_stage_approval_and_consumes_once(tmp_path: Path):
    runtime = _runtime(tmp_path)
    gate = runtime["gate"]
    authority = runtime["authority"]
    operation_id = "op_" + "A" * 24
    payload = b"private pixels"

    try:
        gate.authorize_attempt(
            operation_id=operation_id,
            route_id="vision-ollama-cloud",
            payload=payload,
        )
        raise AssertionError("an unstaged operation must be denied")
    except consent_mod.EgressConsentDenied:
        pass


    pending = authority.list_requests()
    assert len(pending) == 1
    assert pending[0]["state"] == "pending"
    assert authority.resolve(pending[0]["request_id"], allowed=True)["state"] == "approved"

    allowed = gate.authorize_attempt(
        operation_id=operation_id,
        route_id="vision-ollama-cloud",
        payload=payload,
    )
    assert allowed.provider == "ollama-cloud"
    assert authority.get(pending[0]["request_id"])["state"] == "consumed"

    try:
        gate.authorize_attempt(
            operation_id=operation_id,
            route_id="vision-ollama-cloud",
            payload=payload,
        )
        raise AssertionError("a consumed decision must not replay")
    except consent_mod.EgressConsentDenied:
        pass


def test_signed_creator_discord_upload_uses_exact_single_use_vision_grant(
    tmp_path: Path, monkeypatch,
):
    runtime = _runtime(tmp_path)
    calls: list[bytes] = []
    monkeypatch.setattr(server, "_PERCEPTION_EGRESS_RUNTIME", runtime)
    monkeypatch.setattr(server, "DISCORD_CREATOR_CLOUD_VISION", True)

    def remote(payload: bytes, _prompt: str):
        calls.append(payload)
        return "A Discord screenshot showing an image continuity error.\nSELF: no"

    monkeypatch.setattr(vision, "_describe_ollama_cloud", remote)

    result = server._describe_verified_creator_discord_upload(_png())

    assert result is not None
    assert result.text == "A Discord screenshot showing an image continuity error."
    assert result.processing_location == "provider-managed"
    assert result.cloud_egress == "managed-model-api"
    assert calls == [_png()]
    with sqlite3.connect(tmp_path / "requests.sqlite3") as conn:
        states = conn.execute(
            "SELECT state FROM interactive_egress_requests"
        ).fetchall()
    assert states == [("consumed",)]
    assert _png() not in (tmp_path / "requests.sqlite3").read_bytes()


def test_server_flow_is_creator_only_exact_and_payload_free(
    tmp_path: Path, monkeypatch
):
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(server, "_PERCEPTION_EGRESS_RUNTIME", runtime)
    calls: list[bytes] = []

    def remote(payload: bytes, _prompt: str) -> str:
        calls.append(payload)
        return "three blue squares"

    monkeypatch.setattr(vision, "_describe_ollama_cloud", remote)
    image = _png()
    client = TestClient(server.app)
    try:
        assert client.get("/perception/egress/consents").status_code == 401
        staged = client.post(
            "/perception/egress/stage",
            headers=_headers(),
            json={"route_id": "vision-ollama-cloud", "image": _data_url(image)},
        )
        assert staged.status_code == 202, staged.text
        stage_body = staged.json()
        assert stage_body["payload_retained"] is False
        request_id = stage_body["request"]["request_id"]
        operation_id = stage_body["operation_id"]
        assert base64.b64encode(image).decode("ascii") not in staged.text
        assert calls == []

        approved = client.post(
            f"/perception/egress/consents/{request_id}",
            headers=_headers(),
            json={"allowed": True},
        )
        assert approved.status_code == 200, approved.text

        changed = client.post(
            "/perception/egress/execute",
            headers=_headers(),
            json={
                "request_id": request_id,
                "operation_id": operation_id,
                "route_id": "vision-ollama-cloud",
                "image": _data_url(_png() + b"changed"),
            },
        )
        assert changed.status_code == 409
        assert calls == []

        executed = client.post(
            "/perception/egress/execute",
            headers=_headers(),
            json={
                "request_id": request_id,
                "operation_id": operation_id,
                "route_id": "vision-ollama-cloud",
                "image": _data_url(image),
            },
        )
        assert executed.status_code == 200, executed.text
        assert executed.json()["description"] == "three blue squares"
        assert executed.json()["payload_retained"] is False
        assert calls == [image]

        replay = client.post(
            "/perception/egress/execute",
            headers=_headers(),
            json={
                "request_id": request_id,
                "operation_id": operation_id,
                "route_id": "vision-ollama-cloud",
                "image": _data_url(image),
            },
        )
        assert replay.status_code == 403
        assert calls == [image]
    finally:
        client.close()
