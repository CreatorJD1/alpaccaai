"""Phase 10 Discord stays DM-only until signed actor wiring is live."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from alpecca import discord_bridge
from alpecca import discord_media
from alpecca.bridge_actor_transport import DiscordActorBindings


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate_room_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        discord_bridge,
        "DISCORD_ROOM_REGISTRY",
        tmp_path / "discord_social_rooms.json",
    )


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


class _HistoryChannel(_Channel):
    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self.guild = SimpleNamespace(id=777)
        self.sent: list[str] = []
        self._history_lines = list(lines)

    def history(self, *, limit: int, oldest_first: bool):
        del limit, oldest_first

        async def records():
            for index, content in enumerate(self._history_lines, start=1):
                yield SimpleNamespace(
                    author=_Author(user_id=100 + index, name=f"person{index}"),
                    clean_content=content,
                )

        return records()

    async def send(self, content: str) -> None:
        self.sent.append(content)


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


def test_social_presence_and_voice_output_can_be_enabled(tmp_path):
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
        "voice": True,
        "debug": False,
        "voice_states": True,
    }


def test_discord_voice_output_defaults_off_without_explicit_flag(tmp_path):
    env = os.environ.copy()
    env.pop("ALPECCA_DISCORD_VOICE", None)
    env["ALPECCA_HOME"] = str(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from alpecca import discord_bridge as bridge; "
                "client = bridge.build_client(); "
                "print(json.dumps({'voice': bridge.VOICE_ENABLED, "
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
    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {
        "voice": False,
        "voice_states": False,
    }


def test_voice_readiness_command_is_secret_free(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "ALPECCA_HOME": str(tmp_path),
            "ALPECCA_DISCORD_VOICE": "1",
            "DISCORD_BOT_TOKEN": "voice-secret-must-not-appear",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_discord_bridge.py",
            "--voice-readiness",
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
    assert readiness["enabled"] is True
    assert readiness["mode"] == "output-only"
    assert readiness["status"] in {"ready", "unavailable"}
    serialized = completed.stdout.casefold()
    assert "voice-secret-must-not-appear" not in serialized
    assert "discord_bot_token" not in serialized


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


def test_creator_mention_claims_a_discord_room(monkeypatch, tmp_path):
    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    monkeypatch.setattr(discord_bridge, "DISCORD_ROOM_REGISTRY", tmp_path / "rooms.json")
    monkeypatch.setattr(discord_bridge, "RECURSIVE_ENABLED", False)

    class Guild:
        id = 777

    class Channel(_Channel):
        id = 3001

    message = _Message(content="@Alpecca_ai room on")
    message.guild = Guild()
    message.channel = Channel()
    message.mentions = [client.user]
    message.clean_content = "@Alpecca_ai room on"

    asyncio.run(client.on_message(message))

    stored = json.loads((tmp_path / "rooms.json").read_text(encoding="utf-8"))
    assert stored == {"777:3001": {"channel_id": "3001", "guild_id": "777"}}
    assert message.replies and "present in this room" in message.replies[0][0]


def test_real_discord_raw_mention_claims_room_without_clean_content_or_object_identity(
    monkeypatch,
    tmp_path,
):
    client = _client(monkeypatch)
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", set())
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", {"realcreatorjd"})
    monkeypatch.setattr(discord_bridge, "DISCORD_ROOM_REGISTRY", tmp_path / "rooms.json")
    monkeypatch.setattr(discord_bridge, "RECURSIVE_ENABLED", False)

    message = _Message(content="<@9001> room on")
    message.author = _Author(name="realcreatorjd")
    message.guild = SimpleNamespace(id=777)
    message.channel = _Channel()
    message.clean_content = ""
    message.mentions = [SimpleNamespace(id=9001)]

    asyncio.run(client.on_message(message))

    stored = json.loads((tmp_path / "rooms.json").read_text(encoding="utf-8"))
    assert stored == {"777:3001": {"channel_id": "3001", "guild_id": "777"}}
    assert discord_bridge.DM_ALLOW_IDS == {"42"}
    assert message.replies and "present in this room" in message.replies[0][0]


@pytest.mark.parametrize(
    "raw",
    (
        "<@9001> room on",
        "<@!9001> room on.",
        "<@9001> room on\n<@9001> room on",
        "<@9001> room on\nHello\n<@9001>",
    ),
)
def test_room_command_parser_accepts_discord_protocol_mentions(raw):
    message = SimpleNamespace(content=raw, clean_content="", mentions=[])

    assert discord_bridge._room_control_action(message, 9001) == "on"
    assert discord_bridge._message_mentions_user(message, 9001) is True


def test_room_command_parser_rejects_conflicting_multiline_actions():
    message = SimpleNamespace(
        content="<@9001> room on\n<@9001> room off",
        clean_content="@Alpecca room on\n@Alpecca room off",
        mentions=[SimpleNamespace(id=9001)],
    )

    assert discord_bridge._room_control_action(message, 9001) is None


def test_mobile_multiline_creator_message_claims_room(monkeypatch, tmp_path):
    client = _client(monkeypatch)
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", set())
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", {"realcreatorjd"})
    monkeypatch.setattr(discord_bridge, "DISCORD_ROOM_REGISTRY", tmp_path / "rooms.json")
    monkeypatch.setattr(discord_bridge, "RECURSIVE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", False)

    message = _Message(content="<@9001> room on\nHello\n<@9001>")
    message.author = _Author(name="realcreatorjd")
    message.guild = SimpleNamespace(id=777)
    message.channel = _Channel()
    message.clean_content = "@Alpecca_ai room on\nHello\n@Alpecca_ai"
    message.mentions = [SimpleNamespace(id=9001)]

    asyncio.run(client.on_message(message))

    stored = json.loads((tmp_path / "rooms.json").read_text(encoding="utf-8"))
    assert stored == {"777:3001": {"channel_id": "3001", "guild_id": "777"}}
    assert message.replies and "present in this room" in message.replies[0][0]


def test_room_command_without_message_content_fails_closed():
    message = SimpleNamespace(
        content="",
        clean_content="",
        mentions=[SimpleNamespace(id=9001)],
    )

    assert discord_bridge._room_control_action(message, 9001) is None


def test_proactive_backoff_is_bounded(monkeypatch):
    monkeypatch.setattr(discord_bridge, "PROACTIVE_COOLDOWN", 10.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_GLOBAL_COOLDOWN", 0.0)

    assert discord_bridge._proactive_backoff_seconds(0) == 10.0
    assert discord_bridge._proactive_backoff_seconds(1) == 20.0
    assert discord_bridge._proactive_backoff_seconds(3) == 80.0
    assert discord_bridge._proactive_backoff_seconds(999) == 80.0


def test_claimed_quiet_room_can_start_one_grounded_conversation(monkeypatch):
    room = {"guild_id": "777", "channel_id": "3001"}
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: {"777:3001": room})
    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_COOLDOWN", 10.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_GLOBAL_COOLDOWN", 0.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_QUIET_MIN", 5.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_MIN_LEN", 1)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_CHANCE", 1.0)
    monkeypatch.setattr(discord_bridge.random, "random", lambda: 0.0)
    calls: list[tuple[str, str]] = []

    def ask(prompt: str, room_scope: str) -> str:
        calls.append((prompt, room_scope))
        return "What part of the model should we improve next?"

    monkeypatch.setattr(discord_bridge, "_ask_room_autonomy", ask)
    client = _client(monkeypatch)
    channel = _HistoryChannel(["We were comparing the current model textures."])
    monkeypatch.setattr(client, "get_channel", lambda channel_id: channel if channel_id == 3001 else None)
    sweep = getattr(client, "_alpecca_proactive_sweep_once")

    asyncio.run(sweep(now=100.0))
    asyncio.run(sweep(now=111.0))
    asyncio.run(sweep(now=122.0))

    assert channel.sent == ["What part of the model should we improve next?"]
    assert len(calls) == 1
    assert "current model textures" in calls[0][0]
    assert len(calls[0][1]) == 64


def test_unclaimed_room_never_runs_a_proactive_decision(monkeypatch):
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: {})
    backend_calls: list[str] = []
    random_calls: list[str] = []
    monkeypatch.setattr(
        discord_bridge,
        "_ask_room_autonomy",
        lambda *_args: backend_calls.append("backend") or "unexpected",
    )
    monkeypatch.setattr(
        discord_bridge.random,
        "random",
        lambda: random_calls.append("random") or 0.0,
    )
    client = _client(monkeypatch)
    channel = _HistoryChannel(["This channel was never claimed."])
    monkeypatch.setattr(client, "get_channel", lambda _channel_id: channel)

    asyncio.run(getattr(client, "_alpecca_proactive_sweep_once")(now=999.0))

    assert backend_calls == []
    assert random_calls == []
    assert channel.sent == []


def test_one_proactive_sweep_cannot_burst_across_claimed_rooms(monkeypatch):
    rooms = {
        "777:3001": {"guild_id": "777", "channel_id": "3001"},
        "777:3002": {"guild_id": "777", "channel_id": "3002"},
    }
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: rooms)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_COOLDOWN", 10.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_GLOBAL_COOLDOWN", 0.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_QUIET_MIN", 5.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_MIN_LEN", 1)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_CHANCE", 1.0)
    monkeypatch.setattr(discord_bridge.random, "random", lambda: 0.0)
    calls: list[str] = []
    monkeypatch.setattr(
        discord_bridge,
        "_ask_room_autonomy",
        lambda _prompt, scope: calls.append(scope) or "One bounded opener.",
    )
    client = _client(monkeypatch)
    channels = {
        3001: _HistoryChannel(["First claimed room has enough context."]),
        3002: _HistoryChannel(["Second claimed room has enough context."]),
    }
    channels[3002].id = 3002
    monkeypatch.setattr(client, "get_channel", channels.get)
    sweep = getattr(client, "_alpecca_proactive_sweep_once")

    asyncio.run(sweep(now=100.0))
    asyncio.run(sweep(now=111.0))

    assert len(calls) == 1
    assert sum(len(channel.sent) for channel in channels.values()) == 1


def test_quiet_room_proactive_turn_yields_when_a_human_speaks(monkeypatch):
    room = {"guild_id": "777", "channel_id": "3001"}
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: {"777:3001": room})
    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_COOLDOWN", 10.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_GLOBAL_COOLDOWN", 0.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_QUIET_MIN", 5.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_MIN_LEN", 1)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_CHANCE", 1.0)
    monkeypatch.setattr(discord_bridge, "PARTICIPATE", False)
    monkeypatch.setattr(discord_bridge.random, "random", lambda: 0.0)
    started = threading.Event()
    release = threading.Event()

    def ask(_prompt: str, _room_scope: str) -> str:
        started.set()
        assert release.wait(timeout=2.0)
        return "This stale question must not be sent."

    monkeypatch.setattr(discord_bridge, "_ask_room_autonomy", ask)
    client = _client(monkeypatch)
    channel = _HistoryChannel(["We were discussing animation timing."])
    monkeypatch.setattr(client, "get_channel", lambda channel_id: channel if channel_id == 3001 else None)
    sweep = getattr(client, "_alpecca_proactive_sweep_once")

    message = _Message(content="I have a new thought while you are deciding.")
    message.guild = SimpleNamespace(id=777)
    message.channel = channel
    message.clean_content = message.content
    message.mentions = []
    message.reference = None

    async def scenario() -> None:
        await sweep(now=100.0)
        proactive = asyncio.create_task(sweep(now=111.0))
        assert await asyncio.to_thread(started.wait, 2.0)
        await client.on_message(message)
        release.set()
        await proactive

    asyncio.run(scenario())

    assert channel.sent == []


def test_quiet_room_proactive_turn_yields_if_creator_turns_room_off(
    monkeypatch,
    tmp_path,
):
    room = {"guild_id": "777", "channel_id": "3001"}
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: {"777:3001": room})
    monkeypatch.setattr(discord_bridge, "DISCORD_ROOM_REGISTRY", tmp_path / "rooms.json")
    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_COOLDOWN", 10.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_GLOBAL_COOLDOWN", 0.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_QUIET_MIN", 5.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_MIN_LEN", 1)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_CHANCE", 1.0)
    monkeypatch.setattr(discord_bridge.random, "random", lambda: 0.0)
    started = threading.Event()
    release = threading.Event()

    def ask(_prompt: str, _room_scope: str) -> str:
        started.set()
        assert release.wait(timeout=2.0)
        return "This revoked-room question must not be sent."

    monkeypatch.setattr(discord_bridge, "_ask_room_autonomy", ask)
    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    channel = _HistoryChannel(["This room is currently approved."])
    monkeypatch.setattr(client, "get_channel", lambda channel_id: channel if channel_id == 3001 else None)
    sweep = getattr(client, "_alpecca_proactive_sweep_once")

    room_off = _Message(content="<@9001> room off")
    room_off.guild = SimpleNamespace(id=777)
    room_off.channel = channel
    room_off.clean_content = "@Alpecca room off"
    room_off.mentions = [SimpleNamespace(id=9001)]

    async def scenario() -> None:
        await sweep(now=100.0)
        proactive = asyncio.create_task(sweep(now=111.0))
        assert await asyncio.to_thread(started.wait, 2.0)
        await client.on_message(room_off)
        release.set()
        await proactive

    asyncio.run(scenario())

    assert channel.sent == []
    assert json.loads((tmp_path / "rooms.json").read_text(encoding="utf-8")) == {}


def test_room_registry_failure_rolls_back_in_memory_claim(monkeypatch, tmp_path):
    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    monkeypatch.setattr(discord_bridge, "DISCORD_ROOM_REGISTRY", tmp_path / "rooms.json")
    monkeypatch.setattr(discord_bridge, "RECURSIVE_ENABLED", False)
    monkeypatch.setattr(
        discord_bridge,
        "_save_social_rooms",
        lambda _rooms: (_ for _ in ()).throw(OSError("read only")),
    )
    backend_calls: list[str] = []
    monkeypatch.setattr(
        discord_bridge,
        "_ask_alpecca",
        lambda *_args, **_kwargs: backend_calls.append("called") or "unexpected",
    )

    message = _Message(content="<@9001> room on")
    message.guild = SimpleNamespace(id=777)
    message.channel = _Channel()
    message.clean_content = "@Alpecca room on"
    message.mentions = [SimpleNamespace(id=9001)]

    asyncio.run(client.on_message(message))

    assert not (tmp_path / "rooms.json").exists()
    assert message.replies == [
        ("I could not save this room setting.", {"mention_author": False})
    ]

    followup = _Message(content="ordinary room message")
    followup.guild = SimpleNamespace(id=777)
    followup.channel = _Channel()
    followup.clean_content = followup.content
    followup.mentions = []
    asyncio.run(client.on_message(followup))
    assert backend_calls == []


def test_room_claim_survives_missing_discord_send_permission(monkeypatch, tmp_path):
    client = _client(monkeypatch)
    _allow_dm(monkeypatch)
    monkeypatch.setattr(discord_bridge, "DISCORD_ROOM_REGISTRY", tmp_path / "rooms.json")
    monkeypatch.setattr(discord_bridge, "RECURSIVE_ENABLED", False)

    message = _Message(content="<@9001> room on")
    message.guild = SimpleNamespace(id=777)
    message.channel = _Channel()
    message.clean_content = "@Alpecca room on"
    message.mentions = [SimpleNamespace(id=9001)]

    async def forbidden_reply(*_args, **_kwargs):
        raise RuntimeError("missing send permission")

    message.reply = forbidden_reply
    asyncio.run(client.on_message(message))

    stored = json.loads((tmp_path / "rooms.json").read_text(encoding="utf-8"))
    assert stored == {"777:3001": {"channel_id": "3001", "guild_id": "777"}}


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


def test_voice_synthesis_accepts_only_bounded_audio(monkeypatch):
    class Response:
        status = 200

        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit: int) -> bytes:
            return self.payload[:limit]

    payloads = [b"w" * 2048, b"x" * 2049]
    monkeypatch.setattr(discord_bridge, "VOICE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "MAX_VOICE_RESPONSE_BYTES", 2048)
    monkeypatch.setattr(
        discord_bridge,
        "_open_backend_request",
        lambda *_args, **_kwargs: Response(payloads.pop(0)),
    )

    assert discord_bridge._synth_voice_wav("speak this") == b"w" * 2048
    assert discord_bridge._synth_voice_wav("oversized") is None


def test_voice_playback_uses_local_tts_and_cleans_temp_file(monkeypatch):
    monkeypatch.setattr(discord_bridge, "VOICE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "PHASE10_GUILD_MODES_LOCKED", False)
    monkeypatch.setattr(discord_bridge, "_synth_voice_wav", lambda _text: b"w" * 2048)
    monkeypatch.setattr(discord_bridge, "_ffmpeg_exe", lambda: "ffmpeg-test")
    monkeypatch.setattr(discord_bridge.discord.opus, "is_loaded", lambda: True)
    source_paths: list[Path] = []

    def fake_audio(path: str, *, executable: str):
        assert executable == "ffmpeg-test"
        source_paths.append(Path(path))
        assert source_paths[-1].exists()
        return SimpleNamespace(path=path)

    monkeypatch.setattr(discord_bridge.discord, "FFmpegPCMAudio", fake_audio)

    class VoiceClient:
        def __init__(self) -> None:
            self.played: list[object] = []

        def is_connected(self) -> bool:
            return True

        def is_playing(self) -> bool:
            return False

        def play(self, source: object, *, after) -> None:
            self.played.append(source)
            after(None)

    voice_client = VoiceClient()
    client = _client(monkeypatch)
    guild = SimpleNamespace(id=777, voice_client=voice_client)

    asyncio.run(getattr(client, "_alpecca_speak_in_voice")(guild, "Hello from Alpecca."))

    assert len(voice_client.played) == 1
    assert len(source_paths) == 1
    assert not source_paths[0].exists()
