"""Server wiring coverage for signed Discord guest actor envelopes."""
from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from alpecca import bridge_actor_identity as actor_identity
from alpecca import bridge_actor_transport as actor_transport


ACTOR_SEAL = "phase10-server-actor-seal-secret-with-enough-entropy"


def _bindings(
    event_id: str = "100000000000000001",
    *,
    actor_id: str = "200000000000000002",
    guild_id: str | None = None,
    channel_id: str = "300000000000000003",
    thread_id: str | None = None,
) -> actor_transport.DiscordActorBindings:
    return actor_transport.DiscordActorBindings(
        event_id=event_id,
        actor_id=actor_id,
        guild_id=guild_id,
        channel_id=channel_id,
        thread_id=thread_id,
    )


def _body(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "channel": "discord-dm",
        "sender": "Discord guest",
        "speaker": "guest",
        "text": "hello",
    }
    payload.update(overrides)
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _headers(
    bindings: actor_transport.DiscordActorBindings,
    envelope: str | None = None,
) -> dict[str, str]:
    headers = {
        server.auth_mod.BRIDGE_AUTHORIZATION_HEADER:
            server._DISCORD_BRIDGE_SECRET,
        "Content-Type": "application/json",
        **bindings.as_headers(),
    }
    if envelope is not None:
        headers[actor_transport.ENVELOPE_HEADER] = envelope
    return headers


def _mint(
    client: TestClient,
    body: bytes,
    bindings: actor_transport.DiscordActorBindings,
) -> str:
    response = client.post(
        "/channel/discord/actor-envelope",
        headers=_headers(bindings),
        content=body,
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()) == {"envelope"}
    return response.json()["envelope"]


def _post_signed(
    client: TestClient,
    body: bytes,
    bindings: actor_transport.DiscordActorBindings,
    envelope: str,
):
    return client.post(
        "/channel/discord",
        headers=_headers(bindings, envelope),
        content=body,
    )


@pytest.fixture
def client():
    with TestClient(server.app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def isolated_actor_server(tmp_path, monkeypatch):
    calls: list[dict[str, object]] = []
    store = actor_transport.build_actor_store(tmp_path, ACTOR_SEAL)
    monkeypatch.setattr(server, "_DISCORD_ACTOR_STORE", store)

    async def fake_turn(text: str, **kwargs):
        calls.append({"text": text, **kwargs})
        return {"reply": "bounded actor reply"}

    monkeypatch.setattr(server, "_ws_chat_turn_with_timeout", fake_turn)
    monkeypatch.setattr(server, "_mindscape_request_event_sync", lambda *_args: None)
    return {"calls": calls, "home": tmp_path}


def _assert_denied_without_turn(response, calls: list[dict[str, object]]) -> None:
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"] == {"code": "discord_actor_denied"}
    assert calls == []


def test_mint_and_channel_accept_only_the_exact_raw_body(
    client, isolated_actor_server
):
    bindings = _bindings()
    body = b'{ "text" : "same JSON, exact bytes" }'
    envelope = _mint(client, body, bindings)

    response = _post_signed(client, body, bindings, envelope)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "reply": "bounded actor reply",
        "delivered": False,
        "source": "discord",
    }
    assert isolated_actor_server["calls"][0]["text"] == "same JSON, exact bytes"


def test_allowlisted_signed_actor_uses_shared_creator_memory_scope(
    client, monkeypatch, isolated_actor_server
):
    bindings = _bindings(actor_id="200000000000000777")
    body = _body(
        sender="CreatorJD",
        speaker="creator",
        text="What did I last say in House HQ?",
    )
    monkeypatch.setattr(
        server.discord_creator_identity_mod,
        "is_creator_actor_id",
        lambda actor_id: actor_id == bindings.actor_id,
    )

    response = _post_signed(client, body, bindings, _mint(client, body, bindings))

    assert response.status_code == 200
    turn = isolated_actor_server["calls"][0]["turn"]
    assert turn.principal == "creator"
    assert turn.surface == "discord"
    assert turn.memory_scope == "creator-personal"


def test_unbound_actor_cannot_claim_creator_authority(
    client, monkeypatch, isolated_actor_server
):
    bindings = _bindings(actor_id="200000000000000778")
    body = _body(sender="CreatorJD", speaker="creator")
    monkeypatch.setattr(
        server.discord_creator_identity_mod,
        "is_creator_actor_id",
        lambda _actor_id: False,
    )

    response = _post_signed(client, body, bindings, _mint(client, body, bindings))

    assert response.status_code == 200
    turn = isolated_actor_server["calls"][0]["turn"]
    assert turn.principal == "guest"
    assert turn.memory_scope.startswith("alpecca-lived-discord-")


@pytest.mark.parametrize(
    ("binding_field", "replacement_value"),
    (
        ("event_id", "100000000000000009"),
        ("actor_id", "200000000000000009"),
        ("guild_id", "400000000000000009"),
        ("channel_id", "300000000000000009"),
        ("thread_id", "500000000000000009"),
    ),
)
def test_binding_mismatch_is_denied_before_image_audit_or_turn(
    client,
    monkeypatch,
    isolated_actor_server,
    binding_field,
    replacement_value,
):
    original = _bindings(
        guild_id="400000000000000004",
        thread_id="500000000000000005",
    )
    body = _body(image="data:image/png;base64,AAAA")
    envelope = _mint(client, body, original)
    changed = replace(original, **{binding_field: replacement_value})
    monkeypatch.setattr(
        server.attachment_ingress_mod,
        "ingest_image",
        lambda *_args, **_kwargs: pytest.fail("image ingress ran before actor accept"),
    )
    monkeypatch.setattr(
        server,
        "_record_capability_use",
        lambda *_args, **_kwargs: pytest.fail("audit ran before actor accept"),
    )

    response = _post_signed(client, body, changed, envelope)

    _assert_denied_without_turn(response, isolated_actor_server["calls"])


def test_body_mismatch_and_forged_envelope_are_denied_preaccept(
    client, isolated_actor_server
):
    body = _body(text="exact")
    bindings = _bindings()
    envelope = _mint(client, body, bindings)

    mismatch = _post_signed(client, _body(text="changed"), bindings, envelope)
    _assert_denied_without_turn(mismatch, isolated_actor_server["calls"])

    second_bindings = _bindings("100000000000000010")
    second_envelope = _mint(client, body, second_bindings)
    forged = second_envelope[:-1] + ("0" if second_envelope[-1] != "0" else "1")
    response = _post_signed(client, body, second_bindings, forged)
    _assert_denied_without_turn(response, isolated_actor_server["calls"])


@pytest.mark.parametrize(
    "headers",
    (
        {},
        {actor_transport.EVENT_ID_HEADER: "01"},
        {
            actor_transport.EVENT_ID_HEADER: "100000000000000001",
            actor_transport.ACTOR_ID_HEADER: "not-a-discord-id",
            actor_transport.CHANNEL_ID_HEADER: "300000000000000003",
        },
    ),
)
def test_missing_or_malformed_actor_headers_are_denied_without_store_or_turn(
    client, monkeypatch, isolated_actor_server, headers
):
    monkeypatch.setattr(
        server,
        "_verify_discord_actor_envelope",
        lambda *_args, **_kwargs: pytest.fail("store verification was reached"),
    )
    response = client.post(
        "/channel/discord",
        headers={
            server.auth_mod.BRIDGE_AUTHORIZATION_HEADER:
                server._DISCORD_BRIDGE_SECRET,
            actor_transport.ENVELOPE_HEADER: "{}",
            **headers,
        },
        content=_body(),
    )

    _assert_denied_without_turn(response, isolated_actor_server["calls"])


def test_replay_is_single_use_under_concurrency(client, isolated_actor_server):
    bindings = _bindings()
    body = _body(text="concurrent replay")
    envelope = _mint(client, body, bindings)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_post_signed, client, body, bindings, envelope)
            for _index in range(2)
        ]
        responses = [future.result(timeout=10) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 403]
    assert all(response.headers["cache-control"] == "no-store" for response in responses)
    assert len(isolated_actor_server["calls"]) == 1


def test_duplicate_event_cannot_mint_a_second_envelope(
    client, isolated_actor_server
):
    bindings = _bindings()
    body = _body(text="duplicate mint")
    assert _mint(client, body, bindings)

    replay = client.post(
        "/channel/discord/actor-envelope",
        headers=_headers(bindings),
        content=body,
    )

    _assert_denied_without_turn(replay, isolated_actor_server["calls"])


def test_restart_preserves_unconsumed_acceptance_and_consumed_replay(
    client, monkeypatch, isolated_actor_server
):
    bindings = _bindings()
    body = _body(text="restart-safe")
    envelope = _mint(client, body, bindings)
    home = isolated_actor_server["home"]

    monkeypatch.setattr(
        server,
        "_DISCORD_ACTOR_STORE",
        actor_transport.build_actor_store(home, ACTOR_SEAL),
    )
    accepted = _post_signed(client, body, bindings, envelope)
    assert accepted.status_code == 200

    monkeypatch.setattr(
        server,
        "_DISCORD_ACTOR_STORE",
        actor_transport.build_actor_store(home, ACTOR_SEAL),
    )
    replay = _post_signed(client, body, bindings, envelope)
    assert replay.status_code == 403
    assert replay.headers["cache-control"] == "no-store"
    assert len(isolated_actor_server["calls"]) == 1


def test_verified_actor_produces_stable_opaque_scopes_without_raw_ids(
    client, isolated_actor_server
):
    raw_actor = "200000000000000002"
    raw_channel = "300000000000000003"
    body = _body(
        text="scope test",
        sender=raw_actor,
        situation=f"channel={raw_channel}",
    )
    for event_id in ("100000000000000011", "100000000000000012"):
        bindings = _bindings(
            event_id,
            actor_id=raw_actor,
            channel_id=raw_channel,
        )
        envelope = _mint(client, body, bindings)
        response = _post_signed(client, body, bindings, envelope)
        assert response.status_code == 200
        serialized_result = json.dumps(response.json(), sort_keys=True)
        assert raw_actor not in serialized_result
        assert raw_channel not in serialized_result

    first = isolated_actor_server["calls"][0]
    second = isolated_actor_server["calls"][1]
    first_turn = first["turn"]
    second_turn = second["turn"]
    assert first_turn.conversation_id == second_turn.conversation_id
    assert first_turn.privacy_scope == second_turn.privacy_scope
    assert first_turn.conversation_id.startswith("discord-guest-")
    assert first_turn.privacy_scope.startswith("alpecca-lived-discord-")
    assert raw_actor not in repr(first)
    assert raw_channel not in repr(first)


def test_six_mib_boundary_is_exact_and_oversize_never_reaches_store(
    client, monkeypatch, isolated_actor_server
):
    prefix = b'{"text":"'
    suffix = b'"}'
    exact = prefix + b"x" * (
        actor_transport.MAX_DISCORD_BODY_BYTES - len(prefix) - len(suffix)
    ) + suffix
    bindings = _bindings("100000000000000020")
    envelope = _mint(client, exact, bindings)
    accepted = _post_signed(client, exact, bindings, envelope)
    assert accepted.status_code == 200

    oversized = exact + b" "
    monkeypatch.setattr(
        server,
        "_issue_discord_actor_envelope",
        lambda *_args, **_kwargs: pytest.fail("oversized mint reached the store"),
    )
    mint_rejected = client.post(
        "/channel/discord/actor-envelope",
        headers=_headers(_bindings("100000000000000021")),
        content=oversized,
    )
    assert mint_rejected.status_code == 413
    assert mint_rejected.headers["cache-control"] == "no-store"

    monkeypatch.setattr(
        server,
        "_verify_discord_actor_envelope",
        lambda *_args, **_kwargs: pytest.fail("oversized delivery reached the store"),
    )
    delivery_rejected = client.post(
        "/channel/discord",
        headers=_headers(_bindings("100000000000000022"), "{}"),
        content=oversized,
    )
    assert delivery_rejected.status_code == 413
    assert delivery_rejected.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "path",
    ("/channel/discord/actor-envelope", "/channel/discord"),
)
def test_service_auth_precedes_actor_headers_body_and_store(
    client, monkeypatch, isolated_actor_server, path
):
    monkeypatch.setattr(
        server.bridge_actor_transport_mod,
        "parse_binding_headers",
        lambda *_args: pytest.fail("actor headers parsed before service auth"),
    )
    monkeypatch.setattr(
        server,
        "_discord_actor_store",
        lambda: pytest.fail("actor store opened before service auth"),
    )
    response = client.post(
        path,
        headers={server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET},
        content=b"not JSON",
    )

    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert isolated_actor_server["calls"] == []


@pytest.mark.parametrize(
    "error",
    (
        actor_identity.BridgeActorQuarantinedError("test_quarantine"),
        actor_identity.BridgeActorClockError("test clock failure"),
        sqlite3.OperationalError("test database unavailable"),
    ),
)
def test_store_quarantine_clock_and_database_failures_are_503_preaccept(
    client, monkeypatch, isolated_actor_server, error
):
    bindings = _bindings()
    monkeypatch.setattr(
        server,
        "_verify_discord_actor_envelope",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    response = client.post(
        "/channel/discord",
        headers=_headers(bindings, "{}"),
        content=_body(image="data:image/png;base64,AAAA"),
    )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"] == {
        "code": "discord_actor_identity_unavailable"
    }
    assert isolated_actor_server["calls"] == []


def test_lazy_store_loads_only_the_dedicated_seal_after_service_auth(
    client, monkeypatch, isolated_actor_server
):
    calls: list[tuple[object, ...]] = []
    real_store = server._DISCORD_ACTOR_STORE
    monkeypatch.setattr(server, "_DISCORD_ACTOR_STORE", None)

    def load_seal(home):
        calls.append(("seal", home))
        return ACTOR_SEAL

    def build_store(home, seal):
        calls.append(("store", home, seal))
        return real_store

    monkeypatch.setattr(
        server.auth_mod,
        "load_or_create_bridge_actor_identity_seal_secret",
        load_seal,
    )
    monkeypatch.setattr(server.bridge_actor_transport_mod, "build_actor_store", build_store)

    unauthorized = client.post(
        "/channel/discord/actor-envelope",
        headers={server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET},
        content=_body(),
    )
    assert unauthorized.status_code == 401
    assert calls == []

    first = _mint(client, _body(), _bindings())
    assert first
    second = _mint(client, _body(), _bindings("100000000000000030"))
    assert second
    assert calls == [
        ("seal", server.HOME),
        ("store", server.HOME, ACTOR_SEAL),
    ]


def test_lazy_store_failure_is_503_and_remains_retryable(
    client, monkeypatch, isolated_actor_server
):
    monkeypatch.setattr(server, "_DISCORD_ACTOR_STORE", None)
    attempts: list[object] = []

    def unavailable(home):
        attempts.append(home)
        raise OSError("dedicated actor seal unavailable")

    monkeypatch.setattr(
        server.auth_mod,
        "load_or_create_bridge_actor_identity_seal_secret",
        unavailable,
    )
    response = client.post(
        "/channel/discord/actor-envelope",
        headers=_headers(_bindings()),
        content=_body(),
    )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"] == {
        "code": "discord_actor_identity_unavailable"
    }
    assert attempts == [server.HOME]
    assert server._DISCORD_ACTOR_STORE is None
    assert isolated_actor_server["calls"] == []


def test_malformed_json_does_not_issue_an_envelope(
    client, monkeypatch, isolated_actor_server
):
    monkeypatch.setattr(
        server,
        "_issue_discord_actor_envelope",
        lambda *_args, **_kwargs: pytest.fail("malformed JSON reached the store"),
    )
    response = client.post(
        "/channel/discord/actor-envelope",
        headers=_headers(_bindings()),
        content=b"not-json",
    )

    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert isolated_actor_server["calls"] == []


@pytest.mark.parametrize(
    ("path", "envelope"),
    (
        ("/channel/discord/actor-envelope", None),
        ("/channel/discord", "{}"),
    ),
)
def test_deeply_nested_json_is_bounded_400_before_actor_store(
    client, monkeypatch, isolated_actor_server, path, envelope
):
    bindings = _bindings()
    deeply_nested = (
        b'{"value":'
        + (b"[" * 10_000)
        + b"0"
        + (b"]" * 10_000)
        + b"}"
    )
    store_calls: list[str] = []
    monkeypatch.setattr(
        server,
        "_issue_discord_actor_envelope",
        lambda *_args, **_kwargs: (
            store_calls.append("issue")
            or SimpleNamespace(encode=lambda: "{}")
        ),
    )
    monkeypatch.setattr(
        server,
        "_verify_discord_actor_envelope",
        lambda *_args, **_kwargs: (
            store_calls.append("verify")
            or SimpleNamespace(actor=None, accepted=False)
        ),
    )

    response = client.post(
        path,
        headers=_headers(bindings, envelope),
        content=deeply_nested,
    )

    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"] == "body must be JSON"
    assert store_calls == []
    assert isolated_actor_server["calls"] == []
