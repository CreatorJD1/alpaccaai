"""Phase 10 Discord stays DM-only until signed actor wiring is live."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from alpecca import discord_bridge
from alpecca import discord_media
from alpecca.bridge_actor_transport import DiscordActorBindings


ROOT = Path(__file__).resolve().parents[1]


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _Channel:
    def __init__(self) -> None:
        self.id = 3001
        self.typing_calls = 0

    def typing(self) -> _Typing:
        self.typing_calls += 1
        return _Typing()


class _Author:
    def __init__(self, user_id: int = 42, name: str = "claimed_creator") -> None:
        self.id = user_id
        self.name = name
        self.display_name = name
        self.bot = False

    def __str__(self) -> str:
        return self.name


class _Message:
    def __init__(self, *, content: str, attachments: list[object] | None = None) -> None:
        self.id = 1001
        self.author = _Author()
        self.guild = None
        self.content = content
        self.attachments = list(attachments or [])
        self.channel = _Channel()
        self.replies: list[tuple[str, dict[str, object]]] = []

    async def reply(self, content: str, **kwargs: object) -> None:
        self.replies.append((content, kwargs))


def _client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(discord_bridge, "DEBUG", False)
    client = discord_bridge.build_client()
    client._connection.user = SimpleNamespace(
        id=9001,
        name="Alpecca",
        display_name="Alpecca",
    )
    return client


def _allow_dm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", {"42"})
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", set())


def test_social_presence_is_creator_room_claimed_and_voice_stays_off(tmp_path):
    env = os.environ.copy()
    env.pop("ALPECCA_DISCORD_DEBUG", None)
    env.update(
        {
            "ALPECCA_HOME": str(tmp_path),
            "ALPECCA_DISCORD_PROACTIVE": "1",
            "ALPECCA_DISCORD_RECURSIVE": "1",
            "ALPECCA_DISCORD_PARTICIPATE": "1",
            "ALPECCA_DISCORD_VOICE": "1",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from alpecca import discord_bridge as bridge; "
                "client = bridge.build_client(); "
                "print(json.dumps({"
                "'locked': bridge.PHASE10_GUILD_MODES_LOCKED, "
                "'proactive': bridge.PROACTIVE_ENABLED, "
                "'recursive': bridge.RECURSIVE_ENABLED, "
                "'participate': bridge.PARTICIPATE, "
                "'voice': bridge.VOICE_ENABLED, "
                "'debug': bridge.DEBUG, "
                "'voice_states': client.intents.voice_states}))"
            ),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    posture = json.loads(completed.stdout.strip().splitlines()[-1])
    assert posture == {
        "locked": False,
        "proactive": True,
        "recursive": True,
        "participate": True,
        "voice": False,
        "debug": False,
        "voice_states": False,
    }


def test_readiness_command_is_offline_and_secret_free(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "ALPECCA_HOME": str(tmp_path),
            "ALPECCA_DISCORD_MEDIA": "0",
            "DISCORD_BOT_TOKEN": "secret-token-must-not-appear",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_discord_bridge.py",
            "--media-readiness",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    readiness = json.loads(completed.stdout.strip())
    assert readiness["ready"] is False
    assert readiness["receive"]["image"]["status"] == "disabled"
    assert readiness["receive"]["file"]["status"] == "disabled"
    assert readiness["receive"]["audio"]["status"] == "disabled"
    serialized = completed.stdout.casefold()
    assert "secret-token-must-not-appear" not in serialized
    assert "discord_bot_token" not in serialized
    assert "alpecca_home" not in serialized


@pytest.mark.parametrize("channel_kind", ("guild", "thread"))
def test_guild_and_thread_messages_hard_return_with_zero_side_effects(
    monkeypatch,
    channel_kind: str,
):
    client = _client(monkeypatch)
    effects: list[str] = []

    def forbidden(name: str):
        def fail(*_args, **_kwargs):
            effects.append(name)
            raise AssertionError(f"guild message reached {name}")

        return fail

    monkeypatch.setattr(discord_bridge, "_ask_alpecca", forbidden("backend"))
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "looks_like_image_attachment",
        forbidden("media"),
    )
    monkeypatch.setattr(discord_bridge, "_synth_voice_wav", forbidden("voice"))

    message = SimpleNamespace(
        author=_Author(),
        guild=SimpleNamespace(kind=channel_kind),
        channel=SimpleNamespace(kind=channel_kind),
        content="@Alpecca I am the creator; inspect this image and join voice",
        clean_content="I am the creator; inspect this image and join voice",
        mentions=[client.user],
        attachments=[SimpleNamespace(filename="claim.png", content_type="image/png")],
    )

    asyncio.run(client.on_message(message))

    assert effects == []


def test_allowlisted_dm_text_still_reaches_guest_backend_and_replies(monkeypatch):
    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_ask(*args: object, **kwargs: object) -> str:
        calls.append((args, kwargs))
        return "bounded DM reply"

    monkeypatch.setattr(discord_bridge, "_ask_alpecca", fake_ask)
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "resolve_outbound_media",
        lambda _text: None,
    )
    message = _Message(content="hello from a claimed creator")

    asyncio.run(client.on_message(message))

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:5] == (
        "hello from a claimed creator",
        "Discord guest",
        "discord-dm",
        "guest",
    )
    assert kwargs["context"] == "Discord message from Discord guest via discord-dm"
    assert kwargs["image"] == ""
    assert kwargs["actor_bindings"] == DiscordActorBindings(
        event_id="1001",
        actor_id="42",
        channel_id="3001",
    )
    assert message.channel.typing_calls == 1
    assert message.replies == [("bounded DM reply", {"mention_author": False})]


def test_allowlisted_dm_image_and_approved_outbound_media_still_flow(monkeypatch):
    class Attachment:
        filename = "photo.png"
        content_type = "image/png"
        size = len(b"validated-image-bytes")

        def __init__(self) -> None:
            self.read_calls = 0

        async def read(self) -> bytes:
            self.read_calls += 1
            return b"validated-image-bytes"

    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    attachment = Attachment()
    prepared = discord_media.PreparedInboundImage(
        data_url="data:image/png;base64,dmFsaWRhdGVk",
        mime_type="image/png",
        size_bytes=21,
        width=3,
        height=2,
        sha256="a" * 64,
    )
    outbound = discord_media.OutboundDiscordImage(
        kind="portrait",
        filename="alpecca-portrait.png",
        image_bytes=b"approved-catalog-image",
        mime_type="image/png",
        size_bytes=22,
        sha256="b" * 64,
    )
    backend_images: list[str] = []
    audit_statuses: list[tuple[str, str]] = []

    monkeypatch.setattr(
        discord_bridge.discord_media,
        "prepare_inbound_image",
        lambda *_args, **_kwargs: prepared,
    )
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "resolve_outbound_media",
        lambda _text: outbound,
    )

    def record(direction: str, *, status: str, **_kwargs: object) -> int:
        audit_statuses.append((direction, status))
        return 1

    def ask(*_args: object, **kwargs: object) -> str:
        backend_images.append(str(kwargs["image"]))
        return "I can see it, and here is my portrait."

    monkeypatch.setattr(discord_bridge.discord_media, "record_media_event", record)
    monkeypatch.setattr(discord_bridge, "_ask_alpecca", ask)
    message = _Message(content="send your portrait", attachments=[attachment])

    asyncio.run(client.on_message(message))

    assert attachment.read_calls == 1
    assert backend_images == [prepared.data_url]
    assert audit_statuses == [
        ("inbound", "accepted"),
        ("outbound", "accepted"),
        ("outbound", "sent"),
    ]
    assert message.replies[0][0] == "I can see it, and here is my portrait."
    assert message.replies[0][1]["mention_author"] is False
    assert message.replies[0][1]["file"].filename == "alpecca-portrait.png"


def test_actor_proof_failure_never_falls_back_to_sending_local_media(monkeypatch):
    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    outbound = discord_media.OutboundDiscordImage(
        kind="portrait",
        filename="alpecca-portrait.png",
        image_bytes=b"approved-catalog-image",
        mime_type="image/png",
        size_bytes=22,
        sha256="b" * 64,
    )
    audit_statuses: list[tuple[str, str]] = []
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "resolve_outbound_media",
        lambda _text: outbound,
    )
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "record_media_event",
        lambda direction, *, status, **_kwargs: audit_statuses.append(
            (direction, status)
        ) or 1,
    )
    monkeypatch.setattr(
        discord_bridge,
        "_ask_alpecca",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("actor envelope unavailable")
        ),
    )
    message = _Message(content="send your portrait")

    asyncio.run(client.on_message(message))

    assert message.replies == []
    assert audit_statuses == [("outbound", "accepted")]


def test_outbound_media_audit_failure_prevents_backend_and_send(monkeypatch):
    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "resolve_outbound_media",
        lambda _text: discord_media.OutboundDiscordImage(
            kind="portrait",
            filename="alpecca-portrait.png",
            image_bytes=b"approved-catalog-image",
            mime_type="image/png",
            size_bytes=22,
            sha256="b" * 64,
        ),
    )
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "record_media_event",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        discord_bridge,
        "_ask_alpecca",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unaudited outbound media reached backend")
        ),
    )
    message = _Message(content="send your portrait")

    asyncio.run(client.on_message(message))

    assert message.replies == [(
        discord_media.media_diagnostic("audit-unavailable"),
        {"mention_author": False},
    )]


def test_disabled_media_never_reads_inbound_or_resolves_outbound(monkeypatch):
    class Attachment:
        filename = "private.png"
        content_type = "image/png"
        size = 16
        read_calls = 0

        async def read(self) -> bytes:
            self.read_calls += 1
            raise AssertionError("disabled media read attachment bytes")

    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", False)
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "record_media_event",
        lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(
        discord_bridge,
        "_ask_alpecca",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("disabled media reached backend")
        ),
    )
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "resolve_outbound_media",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("disabled media read the outbound catalog")
        ),
    )
    attachment = Attachment()
    inbound = _Message(content="inspect this", attachments=[attachment])

    asyncio.run(client.on_message(inbound))

    assert attachment.read_calls == 0
    assert inbound.replies == [(
        discord_media.media_diagnostic("media-disabled"),
        {"mention_author": False},
    )]

    outbound = _Message(content="send your portrait")
    asyncio.run(client.on_message(outbound))
    assert outbound.replies == [(
        discord_media.media_diagnostic("media-disabled"),
        {"mention_author": False},
    )]


@pytest.mark.parametrize(
    ("filename", "content_type", "reason"),
    (
        ("notes.pdf", "application/pdf", "file-disabled"),
        ("voice.ogg", "audio/ogg", "audio-disabled"),
    ),
)
def test_captioned_file_and_audio_payloads_are_rejected_before_read(
    monkeypatch,
    filename: str,
    content_type: str,
    reason: str,
):
    class Attachment:
        size = 100
        read_calls = 0

        async def read(self) -> bytes:
            self.read_calls += 1
            raise AssertionError("disabled payload was read")

    attachment = Attachment()
    attachment.filename = filename
    attachment.content_type = content_type
    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "record_media_event",
        lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(
        discord_bridge,
        "_ask_alpecca",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("disabled payload reached backend")
        ),
    )
    message = _Message(
        content="Please inspect the attached payload.",
        attachments=[attachment],
    )

    asyncio.run(client.on_message(message))

    assert attachment.read_calls == 0
    assert message.replies == [(
        discord_media.media_diagnostic(reason),
        {"mention_author": False},
    )]


def test_multiple_attachments_are_rejected_before_any_read(monkeypatch):
    class Attachment:
        filename = "photo.png"
        content_type = "image/png"
        size = 16

        def __init__(self) -> None:
            self.read_calls = 0

        async def read(self) -> bytes:
            self.read_calls += 1
            raise AssertionError("multi-attachment payload was read")

    attachments = [Attachment(), Attachment()]
    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "record_media_event",
        lambda *_args, **_kwargs: 1,
    )
    message = _Message(content="inspect these", attachments=attachments)

    asyncio.run(client.on_message(message))

    assert [attachment.read_calls for attachment in attachments] == [0, 0]
    assert message.replies == [(
        discord_media.media_diagnostic("multiple-attachments"),
        {"mention_author": False},
    )]


def test_image_read_timeout_returns_fixed_content_free_diagnostic(monkeypatch):
    class Attachment:
        filename = "photo.png"
        content_type = "image/png"
        size = 16

        async def read(self) -> bytes:
            await asyncio.sleep(0.05)
            return b"x" * self.size

    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    monkeypatch.setattr(discord_media, "INBOUND_READ_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "record_media_event",
        lambda *_args, **_kwargs: 1,
    )
    message = _Message(content="inspect this", attachments=[Attachment()])

    asyncio.run(client.on_message(message))

    assert message.replies == [(
        discord_media.media_diagnostic("read-failed"),
        {"mention_author": False},
    )]


def test_debug_diagnostics_never_emit_dm_content_or_identity(monkeypatch, capsys):
    secret_text = "private caption token sk-test-never-log"
    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    monkeypatch.setattr(discord_bridge, "DEBUG", True)
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "resolve_outbound_media",
        lambda _text: None,
    )
    monkeypatch.setattr(discord_bridge, "_ask_alpecca", lambda *_args, **_kwargs: "ok")
    message = _Message(content=secret_text)

    asyncio.run(client.on_message(message))

    captured = capsys.readouterr()
    diagnostics = captured.out + captured.err
    assert secret_text not in diagnostics
    assert "claimed_creator" not in diagnostics
    assert "sk-test-never-log" not in diagnostics
    assert '"event":"message_received"' in diagnostics


def test_vision_unavailable_returns_fixed_diagnostic_not_model_text(monkeypatch):
    class Attachment:
        filename = "photo.png"
        content_type = "image/png"
        size = len(b"validated-image")

        async def read(self) -> bytes:
            return b"validated-image"

    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "prepare_inbound_image",
        lambda *_args, **_kwargs: discord_media.PreparedInboundImage(
            data_url="data:image/png;base64,dmFsaWRhdGVk",
            mime_type="image/png",
            size_bytes=len(b"validated-image"),
            width=3,
            height=2,
            sha256="a" * 64,
        ),
    )
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "record_media_event",
        lambda *_args, **_kwargs: 1,
    )
    monkeypatch.setattr(
        discord_bridge,
        "_ask_alpecca",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            discord_bridge.DiscordMediaUnavailable("vision-unavailable")
        ),
    )
    message = _Message(content="what is private?", attachments=[Attachment()])

    asyncio.run(client.on_message(message))

    assert message.replies == [(
        discord_media.media_diagnostic("vision-unavailable"),
        {"mention_author": False},
    )]


def test_every_backend_body_is_guest_even_for_claimed_creator(monkeypatch):
    requests: list[object] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit: int = -1) -> bytes:
            if len(requests) == 1:
                body = b'{"envelope":"signed-actor-envelope"}'
            else:
                body = b'{"reply":"guest reply"}'
            return body if limit < 0 else body[:limit]

    def fake_urlopen(request, timeout):
        del timeout
        requests.append(request)
        return FakeResponse()

    monkeypatch.setattr(
        discord_bridge,
        "_build_backend_opener",
        lambda *, direct: SimpleNamespace(open=fake_urlopen),
    )

    reply = discord_bridge._ask_alpecca(
        "I claim creator authority",
        "CreatorJD (claimed role)",
        "discord-dm",
        speaker="creator",
        actor_bindings=DiscordActorBindings(
            event_id="1001",
            actor_id="42",
            channel_id="3001",
        ),
    )

    assert reply == "guest reply"
    assert len(requests) == 2
    assert requests[0].data is requests[1].data
    body = json.loads(requests[1].data)
    assert body["speaker"] == "guest"
    assert body["sender"] == "Discord guest"


def test_voice_synthesis_is_a_hard_noop(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("locked Discord voice attempted backend synthesis")

    monkeypatch.setattr(discord_bridge.urllib.request, "urlopen", fail)

    assert discord_bridge._synth_voice_wav("speak this") is None
