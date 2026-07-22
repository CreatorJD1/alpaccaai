from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "apps" / "agentic-frontier"
sys.path.insert(0, str(APP_ROOT))

from agentic_frontier.app import ACCOUNT_COOKIE, create_app  # noqa: E402


def register(client: TestClient, username: str, display_name: str = "Dome Player") -> dict:
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "displayName": display_name,
            "password": "frontier-pass-2044",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["account"]


def minimal_vrm1() -> bytes:
    document = json.dumps(
        {"asset": {"version": "2.0"}, "extensionsUsed": ["VRMC_vrm"]},
        separators=(",", ":"),
    ).encode("utf-8")
    document += b" " * ((4 - len(document) % 4) % 4)
    total = 12 + 8 + len(document)
    return b"glTF" + struct.pack("<II", 2, total) + struct.pack("<II", len(document), 0x4E4F534A) + document


def test_registration_login_cookie_and_logout_are_server_side(tmp_path: Path) -> None:
    app = create_app(db_path=tmp_path / "frontier.db", access_token="")
    with TestClient(app) as client:
        account = register(client, "CreatorJD", "Creator JD")
        assert account["selectedAvatar"] == "silhouette"
        assert account["worldId"].startswith("world_")
        cookie = client.cookies.get(ACCOUNT_COOKIE)
        assert cookie and len(cookie) >= 32

        set_cookie = client.post(
            "/api/auth/login",
            json={"username": "creatorjd", "password": "frontier-pass-2044"},
        ).headers["set-cookie"]
        assert "HttpOnly" in set_cookie
        assert "SameSite=strict" in set_cookie
        assert client.get("/api/auth/me").json()["account"]["displayName"] == "Creator JD"

        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/auth/me").status_code == 401


def test_duplicate_invalid_and_wrong_credentials_are_rejected(tmp_path: Path) -> None:
    app = create_app(db_path=tmp_path / "frontier.db", access_token="")
    with TestClient(app) as client:
        register(client, "VesperOne")
        duplicate = client.post(
            "/api/auth/register",
            json={"username": "vesperone", "displayName": "Other", "password": "another-pass-2044"},
        )
        assert duplicate.status_code == 409
        assert client.post(
            "/api/auth/login", json={"username": "VesperOne", "password": "wrong-password"}
        ).status_code == 401
        assert client.post(
            "/api/auth/register",
            json={"username": "bad name", "displayName": "Bad", "password": "another-pass-2044"},
        ).status_code == 400
        malformed = client.post(
            "/api/auth/register",
            content=b"{bad-json",
            headers={"content-type": "application/json"},
        )
        assert malformed.status_code == 400


def test_account_can_only_access_its_own_persistent_world(tmp_path: Path) -> None:
    app = create_app(db_path=tmp_path / "frontier.db", access_token="")
    with TestClient(app) as first, TestClient(app) as second:
        first_account = register(first, "FirstPlayer", "First")
        second_account = register(second, "SecondPlayer", "Second")
        created = first.post("/api/sessions", json={"session_id": first_account["worldId"]})
        assert created.status_code == 200
        assert second.get(
            f"/api/sessions/{first_account['worldId']}/perception/Jason"
        ).status_code == 403
        assert second.post(
            "/api/sessions", json={"session_id": first_account["worldId"]}
        ).status_code == 403
        own = second.post("/api/sessions", json={"session_id": second_account["worldId"]})
        assert own.status_code == 200
        impersonation = second.post(
            "/api/actions",
            json={
                "contract_version": "agentic_frontier.action.v1",
                "session_id": second_account["worldId"],
                "actor_id": "Alpecca",
                "action_id": "browser_impersonation",
                "expected_revision": 0,
                "action": "companion_motion",
                "parameters": {"to": [0, 2], "mode": "walk"},
            },
        )
        assert impersonation.status_code == 403
        assert second.get(
            f"/api/sessions/{second_account['worldId']}/perception/Alpecca"
        ).status_code == 403


def test_player_avatar_catalog_selection_and_private_vrm_upload(tmp_path: Path) -> None:
    app = create_app(db_path=tmp_path / "frontier.db", access_token="")
    with TestClient(app) as client:
        register(client, "AvatarPlayer")
        catalog = client.get("/api/avatars")
        assert catalog.status_code == 200
        assert catalog.json()["selectedAvatar"] == "silhouette"
        assert catalog.json()["avatars"][1]["available"] is False
        assert client.put("/api/account/avatar", json={"avatarId": "custom"}).status_code == 400
        assert client.put(
            "/api/account/avatar/custom",
            content=b"not a model",
            headers={"content-type": "model/gltf-binary"},
        ).status_code == 400

        uploaded = client.put(
            "/api/account/avatar/custom",
            content=minimal_vrm1(),
            headers={"content-type": "model/gltf-binary"},
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["selectedAvatar"] == "custom"
        assert uploaded.json()["avatars"][1]["available"] is True
        model = client.get("/api/account/avatar/model")
        assert model.status_code == 200
        assert model.content.startswith(b"glTF")
        assert model.headers["cache-control"] == "private, no-store"


def test_game_ui_has_account_gate_and_no_player_model_url_field() -> None:
    template = (APP_ROOT / "web" / "src" / "index.template.html").read_text(encoding="utf-8")
    source = (APP_ROOT / "web" / "src" / "main.js").read_text(encoding="utf-8")
    api = (APP_ROOT / "web" / "src" / "api.js").read_text(encoding="utf-8")
    assert 'id="auth-form"' in template
    assert 'data-auth-mode="login"' in template
    assert 'data-auth-mode="register"' in template
    assert 'id="avatar-selector"' in template
    assert 'id="avatar-file"' in template
    assert "RUNTIME MODEL URL" not in template
    assert 'id="vrm-url"' not in template
    assert 'id="access-token"' not in template
    assert "loadPlayerAvatar" in source
    assert "actAs(" not in api
    assert 'credentials: "same-origin"' in api
