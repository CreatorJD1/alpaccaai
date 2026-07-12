"""Discord transport authentication must never become creator authority."""
from __future__ import annotations

import json
import urllib.request
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from alpecca import auth as auth_mod
from alpecca import discord_bridge
from alpecca import openclaw_bridge


ROOT_SECRET = "creator-root-secret-with-enough-entropy-for-tests"
BRIDGE_SECRET = "discord-service-secret-with-enough-entropy-for-tests"
ACTOR_SEAL_SECRET = "discord-actor-seal-secret-with-enough-entropy-for-tests"
BOT_TOKEN = "discord-bot-token-kept-separate-from-actor-seals"


def test_bridge_service_credential_is_separate_and_guest_only() -> None:
    authority = auth_mod.SessionAuthority(
        ROOT_SECRET,
        service_secrets={"discord-bridge": BRIDGE_SECRET},
    )

    accepted = authority.validate_bridge_service(
        {auth_mod.BRIDGE_AUTHORIZATION_HEADER: BRIDGE_SECRET}
    )
    root_rejected = authority.validate_bridge_service(
        {auth_mod.BRIDGE_AUTHORIZATION_HEADER: ROOT_SECRET}
    )
    creator_rejected = authority.validate_bearer(
        {auth_mod.AUTHORIZATION_HEADER: BRIDGE_SECRET}
    )

    assert accepted.allowed is True
    assert accepted.mechanism == "service_bearer"
    assert accepted.principal == "service:discord-bridge"
    assert root_rejected.allowed is False
    assert creator_rejected.allowed is False

    with pytest.raises(ValueError, match="at least 32 bytes"):
        auth_mod.SessionAuthority(
            ROOT_SECRET,
            service_secrets={"discord-bridge": "short"},
        )


def test_discord_authorization_and_actor_credentials_remain_distinct(tmp_path) -> None:
    environ = {
        auth_mod.AUTH_ENV_NAME: ROOT_SECRET,
        auth_mod.BRIDGE_AUTH_ENV_NAME: BRIDGE_SECRET,
        auth_mod.BRIDGE_ACTOR_IDENTITY_SEAL_ENV_NAME: ACTOR_SEAL_SECRET,
        "DISCORD_BOT_TOKEN": BOT_TOKEN,
    }
    creator = auth_mod.load_or_create_authorization_secret(
        tmp_path,
        environ,
    )
    bridge = auth_mod.load_or_create_bridge_authorization_secret(
        tmp_path,
        environ,
    )
    actor_seal = auth_mod.load_or_create_bridge_actor_identity_seal_secret(
        tmp_path,
        environ,
    )

    assert creator == ROOT_SECRET
    assert bridge == BRIDGE_SECRET
    assert actor_seal == ACTOR_SEAL_SECRET
    assert len({creator, bridge, actor_seal, environ["DISCORD_BOT_TOKEN"]}) == 4


def test_actor_identity_seal_requires_32_explicit_utf8_bytes(tmp_path) -> None:
    for short_value in ("x" * 31, "\u00e9" * 15 + "x"):
        with pytest.raises(ValueError, match="at least 32 UTF-8 bytes"):
            auth_mod.load_or_create_bridge_actor_identity_seal_secret(
                tmp_path,
                {auth_mod.BRIDGE_ACTOR_IDENTITY_SEAL_ENV_NAME: short_value},
            )

    exact_multibyte_value = "\u00e9" * 16
    assert auth_mod.load_or_create_bridge_actor_identity_seal_secret(
        tmp_path,
        {auth_mod.BRIDGE_ACTOR_IDENTITY_SEAL_ENV_NAME: exact_multibyte_value},
    ) == exact_multibyte_value


def test_actor_seal_validation_does_not_change_existing_loader_contracts(
    tmp_path,
) -> None:
    assert auth_mod.load_or_create_authorization_secret(
        tmp_path,
        {auth_mod.AUTH_ENV_NAME: "root"},
    ) == "root"
    assert auth_mod.load_or_create_bridge_authorization_secret(
        tmp_path,
        {auth_mod.BRIDGE_AUTH_ENV_NAME: "bridge"},
    ) == "bridge"


def test_actor_identity_seal_process_fallback_is_stable_and_process_only(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        auth_mod,
        "_PROCESS_BRIDGE_ACTOR_IDENTITY_SEAL_SECRET",
        None,
    )
    monkeypatch.setattr(auth_mod, "_new_secret", lambda: ACTOR_SEAL_SECRET)
    environ = {
        "PYTEST_CURRENT_TEST": "actor seal process fallback",
        "DISCORD_BOT_TOKEN": BOT_TOKEN,
    }

    first = auth_mod.load_or_create_bridge_actor_identity_seal_secret(
        tmp_path,
        environ,
    )
    second = auth_mod.load_or_create_bridge_actor_identity_seal_secret(
        tmp_path,
        environ,
    )

    assert first == second == ACTOR_SEAL_SECRET
    assert first != environ["DISCORD_BOT_TOKEN"]
    assert list(tmp_path.iterdir()) == []


def test_actor_identity_seal_uses_only_its_windows_credential_target(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def fake_load(target: str, *, comment: str) -> str:
        calls.append((target, comment))
        return ACTOR_SEAL_SECRET

    monkeypatch.setattr(auth_mod, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(auth_mod, "_test_environment", lambda _env: False)
    monkeypatch.setattr(
        auth_mod,
        "_load_or_create_named_windows_credential",
        fake_load,
    )

    loaded = auth_mod.load_or_create_bridge_actor_identity_seal_secret(
        tmp_path,
        {},
    )

    assert loaded == ACTOR_SEAL_SECRET
    assert calls == [
        (
            auth_mod.BRIDGE_ACTOR_IDENTITY_SEAL_CREDENTIAL_TARGET,
            "Alpecca Discord actor-identity seal credential",
        )
    ]
    assert auth_mod.BRIDGE_ACTOR_IDENTITY_SEAL_CREDENTIAL_TARGET not in {
        auth_mod.CREDENTIAL_TARGET,
        auth_mod.BRIDGE_CREDENTIAL_TARGET,
        auth_mod.CREATOR_PASSWORD_CREDENTIAL_TARGET,
    }


def test_discord_route_rejects_creator_bearer_and_runs_service_as_guest(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    deliveries: list[str] = []

    async def fake_turn(*_args, **kwargs):
        captured["turn"] = kwargs["turn"]
        return {"reply": "bounded guest reply"}

    monkeypatch.setattr(server, "_ws_chat_turn_with_timeout", fake_turn)
    monkeypatch.setattr(
        server.mind,
        "note_initiative_user_activity",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(server, "_mindscape_request_event_sync", lambda *_args: None)
    monkeypatch.setattr(
        openclaw_bridge,
        "try_deliver",
        lambda text, **_kwargs: deliveries.append(text),
    )

    client = TestClient(server.app)
    creator = client.post(
        "/channel/discord",
        headers={auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET},
        json={"text": "hello"},
    )
    service = client.post(
        "/channel/discord",
        headers={
            auth_mod.BRIDGE_AUTHORIZATION_HEADER: server._DISCORD_BRIDGE_SECRET,
        },
        json={"text": "hello", "speaker": "creator"},
    )

    assert creator.status_code == 401
    assert service.status_code == 200
    assert service.json()["reply"] == "bounded guest reply"
    turn = captured["turn"]
    assert getattr(turn, "principal") == "guest"
    assert getattr(turn, "surface") == "discord"
    assert deliveries == []


def test_bridge_service_header_cannot_open_creator_routes() -> None:
    client = TestClient(server.app)
    response = client.get(
        "/growth",
        headers={
            auth_mod.BRIDGE_AUTHORIZATION_HEADER: server._DISCORD_BRIDGE_SECRET,
        },
    )

    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


def test_image_bridge_uses_service_header_and_loopback_transport(monkeypatch) -> None:
    calls: list[urllib.request.Request] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"reply": "I can see it."}).encode("utf-8")

    def fake_urlopen(request, timeout):
        del timeout
        calls.append(request)
        return FakeResponse()

    monkeypatch.setattr(discord_bridge.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(discord_bridge, "BACKEND_URL", "https://example.invalid")
    monkeypatch.setattr(discord_bridge, "LOCAL_BACKEND_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(discord_bridge, "_BRIDGE_AUTHORIZATION_SECRET", BRIDGE_SECRET)

    reply = discord_bridge._ask_alpecca(
        "Who is this?",
        "creator",
        "discord-dm",
        image="data:image/png;base64,AAAA",
    )

    assert reply == "I can see it."
    request = calls[0]
    assert request.full_url == "http://127.0.0.1:8765/channel/discord"
    headers = {key.casefold(): value for key, value in request.header_items()}
    assert headers[auth_mod.BRIDGE_AUTHORIZATION_HEADER.casefold()] == BRIDGE_SECRET
    assert auth_mod.AUTHORIZATION_HEADER.casefold() not in headers
