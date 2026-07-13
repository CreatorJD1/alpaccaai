"""Client-side coverage for server-minted Discord guest actor proofs."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from alpecca import bridge_actor_transport as transport
from alpecca import discord_bridge
from alpecca import discord_media
from alpecca.auth import BRIDGE_AUTHORIZATION_HEADER


DM_BINDINGS = transport.DiscordActorBindings(
    event_id="1001",
    actor_id="42",
    channel_id="3001",
)


class _Response:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]


class _FakeOpener:
    def __init__(self, open_request) -> None:
        self._open_request = open_request

    def open(self, request, timeout):
        return self._open_request(request, timeout)


def _patch_backend_open(monkeypatch, open_request) -> list[bool]:
    direct_modes: list[bool] = []

    def build_opener(*, direct: bool):
        direct_modes.append(direct)
        return _FakeOpener(open_request)

    monkeypatch.setattr(discord_bridge, "_build_backend_opener", build_opener)
    return direct_modes


@contextmanager
def _serve_http(responder):
    calls: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def _handle(self, body: bytes):
            calls.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": {
                        key.casefold(): value
                        for key, value in self.headers.items()
                    },
                    "body": body,
                }
            )
            status, headers, response_body = responder(self)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            if response_body:
                self.wfile.write(response_body)

        def do_GET(self):
            self._handle(b"")

        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", "0"))
            self._handle(self.rfile.read(content_length))

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _headers(request) -> dict[str, str]:
    return {key.casefold(): value for key, value in request.header_items()}


def test_signed_guest_posts_one_byte_exact_body_with_bound_headers(monkeypatch):
    requests: list[tuple[object, float]] = []
    responses = iter(
        (
            b'{"envelope":"signed-actor-envelope"}',
            b'{"reply":"bounded reply","ignored":"not returned"}',
        )
    )
    original_dumps = json.dumps
    dump_calls = 0

    def counting_dumps(*args, **kwargs):
        nonlocal dump_calls
        dump_calls += 1
        return original_dumps(*args, **kwargs)

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response(next(responses))

    monkeypatch.setattr(discord_bridge.json, "dumps", counting_dumps)
    direct_modes = _patch_backend_open(monkeypatch, fake_urlopen)
    monkeypatch.setattr(discord_bridge, "BACKEND_URL", "https://bridge.invalid")
    monkeypatch.setattr(discord_bridge, "_BRIDGE_AUTHORIZATION_SECRET", "service-secret")

    reply = discord_bridge._ask_alpecca(
        "h\N{LATIN SMALL LETTER E WITH ACUTE}llo",
        "raw actor label is ignored",
        "discord-dm",
        speaker="creator",
        context="guest conversation",
        room="discord",
        actor_bindings=DM_BINDINGS,
    )

    expected_body = (
        b'{"channel":"discord-dm","context":"guest conversation","room":"discord",'
        b'"sender":"Discord guest","situation":"guest conversation","speaker":"guest",'
        b'"text":"h\\u00e9llo"}'
    )
    assert reply == "bounded reply"
    assert dump_calls == 1
    assert len(requests) == 2
    mint_request, mint_timeout = requests[0]
    final_request, final_timeout = requests[1]
    assert mint_request.full_url == (
        "https://bridge.invalid/channel/discord/actor-envelope"
    )
    assert final_request.full_url == "https://bridge.invalid/channel/discord"
    assert mint_request.data is final_request.data
    assert mint_request.data == expected_body
    assert all(raw_id.encode("ascii") not in expected_body for raw_id in ("1001", "42", "3001"))
    assert mint_timeout == final_timeout == discord_bridge.INBOUND_TIMEOUT
    assert direct_modes == [False, False]

    mint_headers = _headers(mint_request)
    final_headers = _headers(final_request)
    for name, value in DM_BINDINGS.as_headers().items():
        assert mint_headers[name.casefold()] == value
        assert final_headers[name.casefold()] == value
    assert mint_headers[BRIDGE_AUTHORIZATION_HEADER.casefold()] == "service-secret"
    assert final_headers[BRIDGE_AUTHORIZATION_HEADER.casefold()] == "service-secret"
    assert transport.ENVELOPE_HEADER.casefold() not in mint_headers
    assert final_headers[transport.ENVELOPE_HEADER.casefold()] == "signed-actor-envelope"


def test_signed_image_mint_and_delivery_both_stay_on_loopback(monkeypatch):
    requests: list[tuple[object, float]] = []
    responses = iter(
        (
            b'{"envelope":"signed-image-envelope"}',
            (
                b'{"perception":{"status":"described"},'
                b'"reply":"I can see it."}'
            ),
        )
    )

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response(next(responses))

    direct_modes = _patch_backend_open(monkeypatch, fake_urlopen)
    monkeypatch.setattr(discord_bridge, "BACKEND_URL", "https://public.invalid")
    monkeypatch.setattr(discord_bridge, "LOCAL_BACKEND_URL", "http://127.0.0.1:8765")

    reply = discord_bridge._ask_alpecca(
        "inspect this",
        "Discord guest",
        "discord-dm",
        image="data:image/png;base64,AAAA",
        actor_bindings=DM_BINDINGS,
    )

    assert reply == "I can see it."
    assert [request.full_url for request, _timeout in requests] == [
        "http://127.0.0.1:8765/channel/discord/actor-envelope",
        "http://127.0.0.1:8765/channel/discord",
    ]
    assert requests[0][0].data is requests[1][0].data
    assert json.loads(requests[1][0].data)["image"] == "data:image/png;base64,AAAA"
    assert requests[0][1] == discord_bridge.INBOUND_TIMEOUT
    assert requests[1][1] == discord_bridge.IMAGE_INBOUND_TIMEOUT
    assert direct_modes == [True, True]


@pytest.mark.parametrize("redirect_code", (301, 302, 303, 307, 308))
@pytest.mark.parametrize("redirect_stage", ("mint", "delivery"))
def test_actor_redirects_never_reach_a_second_destination(
    monkeypatch,
    redirect_code,
    redirect_stage,
):
    def responder(handler):
        should_redirect = (
            redirect_stage == "mint"
            and handler.path == "/channel/discord/actor-envelope"
        ) or (
            redirect_stage == "delivery"
            and handler.path == "/channel/discord"
        )
        if should_redirect:
            return (
                redirect_code,
                {
                    "Location": (
                        f"http://127.0.0.1:{handler.server.server_port}"
                        "/redirect-target"
                    )
                },
                b"",
            )
        if handler.path == "/channel/discord/actor-envelope":
            return 200, {"Content-Type": "application/json"}, (
                b'{"envelope":"signed-actor-envelope"}'
            )
        return 200, {"Content-Type": "application/json"}, b'{"reply":"leaked"}'

    with _serve_http(responder) as (backend_url, calls):
        monkeypatch.setattr(discord_bridge, "LOCAL_BACKEND_URL", backend_url)
        with pytest.raises(RuntimeError, match=rf"rejected the request \({redirect_code}\)"):
            discord_bridge._ask_alpecca(
                "inspect this",
                "Discord guest",
                "discord-dm",
                image="data:image/png;base64,AAAA",
                actor_bindings=DM_BINDINGS,
            )

    expected_paths = ["/channel/discord/actor-envelope"]
    if redirect_stage == "delivery":
        expected_paths.append("/channel/discord")
    assert [call["path"] for call in calls] == expected_paths
    assert all(call["path"] != "/redirect-target" for call in calls)


def test_backend_openers_always_install_redirect_rejection():
    remote_opener = discord_bridge._build_backend_opener(direct=False)
    direct_opener = discord_bridge._build_backend_opener(direct=True)

    assert any(
        isinstance(handler, discord_bridge._RejectRedirectHandler)
        for handler in remote_opener.handlers
    )
    assert any(
        isinstance(handler, discord_bridge._RejectRedirectHandler)
        for handler in direct_opener.handlers
    )


def test_loopback_image_transport_never_loads_system_proxies(monkeypatch):
    proxy_lookups: list[bool] = []

    def configured_system_proxy():
        proxy_lookups.append(True)
        return {"http": "http://127.0.0.1:1"}

    def responder(handler):
        if handler.path == "/channel/discord/actor-envelope":
            return 200, {"Content-Type": "application/json"}, (
                b'{"envelope":"signed-actor-envelope"}'
            )
        return 200, {"Content-Type": "application/json"}, (
            b'{"perception":{"status":"described"},"reply":"direct"}'
        )

    monkeypatch.setattr(discord_bridge.urllib.request, "getproxies", configured_system_proxy)
    with _serve_http(responder) as (backend_url, calls):
        monkeypatch.setattr(discord_bridge, "LOCAL_BACKEND_URL", backend_url)
        reply = discord_bridge._ask_alpecca(
            "inspect this",
            "Discord guest",
            "discord-dm",
            image="data:image/png;base64,AAAA",
            actor_bindings=DM_BINDINGS,
        )

    assert reply == "direct"
    assert proxy_lookups == []
    assert [call["path"] for call in calls] == [
        "/channel/discord/actor-envelope",
        "/channel/discord",
    ]


def test_backend_response_reads_are_bounded(monkeypatch):
    requests: list[object] = []

    def oversized_response(request, timeout):
        del timeout
        requests.append(request)
        return _Response(b"x" * (discord_bridge.MAX_BACKEND_RESPONSE_BYTES + 1))

    _patch_backend_open(monkeypatch, oversized_response)

    with pytest.raises(RuntimeError, match="bounded byte limit"):
        discord_bridge._post_json_once(
            "https://bridge.invalid/channel/discord/actor-envelope",
            body=b"{}",
            headers={"Content-Type": "application/json"},
            timeout=1,
        )

    assert len(requests) == 1


def test_deeply_nested_json_recursion_fails_closed_as_malformed(monkeypatch):
    nested_json = b"[" * 10_000 + b"0" + b"]" * 10_000
    _patch_backend_open(
        monkeypatch,
        lambda _request, _timeout: _Response(nested_json),
    )

    with pytest.raises(RuntimeError, match="malformed JSON"):
        discord_bridge._post_json_once(
            "https://bridge.invalid/channel/discord/actor-envelope",
            body=b"{}",
            headers={"Content-Type": "application/json"},
            timeout=1,
        )


@pytest.mark.parametrize(
    "responses",
    (
        (b'{"envelope":""}',),
        (b'{"unexpected":"signed-actor-envelope"}',),
        (b'{"envelope":"signed-actor-envelope"}', b'{"reply":7}'),
    ),
    ids=("empty-envelope", "malformed-mint-result", "malformed-reply"),
)
def test_malformed_backend_results_fail_closed_without_fallback(monkeypatch, responses):
    requests: list[object] = []
    queued = iter(responses)

    def fake_urlopen(request, timeout):
        del timeout
        requests.append(request)
        return _Response(next(queued))

    _patch_backend_open(monkeypatch, fake_urlopen)

    with pytest.raises(RuntimeError):
        discord_bridge._ask_alpecca(
            "hello",
            "Discord guest",
            "discord-dm",
            actor_bindings=DM_BINDINGS,
        )

    assert len(requests) == len(responses)


def test_transport_errors_are_never_retried_or_replayed(monkeypatch):
    requests: list[object] = []

    def fail_mint(request, timeout):
        del timeout
        requests.append(request)
        raise urllib.error.URLError("network unavailable")

    _patch_backend_open(monkeypatch, fail_mint)
    with pytest.raises(RuntimeError):
        discord_bridge._ask_alpecca(
            "hello",
            "Discord guest",
            "discord-dm",
            actor_bindings=DM_BINDINGS,
        )
    assert len(requests) == 1

    requests.clear()

    def reject_delivery(request, timeout):
        del timeout
        requests.append(request)
        if len(requests) == 1:
            return _Response(b'{"envelope":"single-use-envelope"}')
        raise urllib.error.HTTPError(request.full_url, 409, "replay", {}, None)

    _patch_backend_open(monkeypatch, reject_delivery)
    with pytest.raises(RuntimeError):
        discord_bridge._ask_alpecca(
            "hello",
            "Discord guest",
            "discord-dm",
            actor_bindings=DM_BINDINGS,
        )
    assert len(requests) == 2


@pytest.mark.parametrize("missing", ("event", "actor", "channel"))
def test_missing_message_ids_fail_before_media_or_backend_work(monkeypatch, missing):
    effects: list[str] = []
    monkeypatch.setattr(discord_bridge, "DEBUG", False)
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", {"42"})
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", set())
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "looks_like_image_attachment",
        lambda *_args: effects.append("media") or True,
    )
    monkeypatch.setattr(
        discord_bridge,
        "_ask_alpecca",
        lambda *_args, **_kwargs: effects.append("backend") or "reply",
    )
    client = discord_bridge.build_client()
    client._connection.user = SimpleNamespace(id=9001, name="Alpecca")
    message = SimpleNamespace(
        id=None if missing == "event" else 1001,
        author=SimpleNamespace(
            id=None if missing == "actor" else 42,
            name="creatorjd",
            bot=False,
        ),
        guild=None,
        channel=SimpleNamespace(id=None if missing == "channel" else 3001),
        content="inspect this",
        attachments=[SimpleNamespace(filename="photo.png", content_type="image/png")],
    )

    asyncio.run(client.on_message(message))

    assert effects == []


def test_missing_direct_bindings_never_attempt_an_unsigned_request(monkeypatch):
    opener_calls: list[object] = []
    monkeypatch.setattr(
        discord_bridge,
        "_build_backend_opener",
        lambda **kwargs: opener_calls.append(kwargs),
    )

    with pytest.raises(RuntimeError, match="bindings are required"):
        discord_bridge._ask_alpecca(
            "hello",
            "Discord guest",
            "discord-dm",
        )

    assert opener_calls == []


def test_allowlisted_dm_image_passes_only_header_bindings_to_transport(monkeypatch):
    class Typing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Channel:
        id = 3001

        def typing(self):
            return Typing()

    class Attachment:
        filename = "photo.png"
        content_type = "image/png"
        size = len(b"validated-image")

        async def read(self):
            return b"validated-image"

    class Message:
        id = 1001
        author = SimpleNamespace(id=42, name="creatorjd", bot=False)
        guild = None
        channel = Channel()
        content = "what is here?"
        attachments = [Attachment()]

        def __init__(self):
            self.replies: list[tuple[str, dict[str, object]]] = []

        async def reply(self, content, **kwargs):
            self.replies.append((content, kwargs))

    prepared = discord_media.PreparedInboundImage(
        data_url="data:image/png;base64,dmFsaWRhdGVk",
        mime_type="image/png",
        size_bytes=15,
        width=3,
        height=2,
        sha256="a" * 64,
    )
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(discord_bridge, "DEBUG", False)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", {"42"})
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", set())
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "prepare_inbound_image",
        lambda *_args, **_kwargs: prepared,
    )
    monkeypatch.setattr(discord_bridge.discord_media, "record_media_event", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(discord_bridge.discord_media, "resolve_outbound_media", lambda _text: None)

    def fake_ask(*args, **kwargs):
        calls.append((args, kwargs))
        return "image reply"

    monkeypatch.setattr(discord_bridge, "_ask_alpecca", fake_ask)
    client = discord_bridge.build_client()
    client._connection.user = SimpleNamespace(id=9001, name="Alpecca")
    message = Message()

    asyncio.run(client.on_message(message))

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert kwargs["actor_bindings"] == DM_BINDINGS
    assert kwargs["image"] == prepared.data_url
    prompt_surface = json.dumps({"args": args, "context": kwargs["context"]})
    assert all(raw_id not in prompt_surface for raw_id in ("1001", "42", "3001"))
    assert message.replies == [("image reply", {"mention_author": False})]


def test_thread_bindings_use_parent_channel_and_preserve_thread_and_guild_ids():
    bindings = discord_bridge._message_actor_bindings(
        SimpleNamespace(
            id=1001,
            author=SimpleNamespace(id=42),
            guild=SimpleNamespace(id=5001),
            channel=SimpleNamespace(id=7001, parent_id=6001),
        )
    )

    assert bindings == transport.DiscordActorBindings(
        event_id="1001",
        actor_id="42",
        guild_id="5001",
        channel_id="6001",
        thread_id="7001",
    )
