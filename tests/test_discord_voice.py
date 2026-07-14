from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace
import wave

from alpecca import discord_bridge, discord_voice
from alpecca.bridge_actor_transport import DiscordActorBindings


def _packet(seconds: float = 0.02) -> bytes:
    size = int(discord_voice.PCM_BYTES_PER_SECOND * seconds)
    size -= size % 4
    return b"\x00" * size


def test_collector_filters_user_and_emits_bounded_memory_wav():
    utterances: list[discord_voice.VoiceUtterance] = []
    starts: list[str] = []
    collector = discord_voice.CreatorPcmCollector(
        42,
        utterances.append,
        on_speech_start=lambda: starts.append("start"),
    )

    assert collector.push(99, _packet()) == "ignored-user"
    for _ in range(20):
        assert collector.push(42, _packet()) == "buffered"
    assert collector.finish(42) is True

    assert starts == ["start"]
    assert len(utterances) == 1
    utterance = utterances[0]
    assert 0.39 <= utterance.duration_seconds <= 0.41
    assert utterance.pcm_bytes == len(_packet()) * 20
    with wave.open(io.BytesIO(utterance.wav_bytes), "rb") as reader:
        assert reader.getframerate() == 48_000
        assert reader.getnchannels() == 2
        assert reader.getsampwidth() == 2
        assert reader.getnframes() == utterance.pcm_bytes // 4


def test_short_noise_is_discarded_and_cleanup_never_emits():
    utterances: list[discord_voice.VoiceUtterance] = []
    collector = discord_voice.CreatorPcmCollector(42, utterances.append)

    for _ in range(5):
        collector.push(42, _packet())
    assert collector.finish(42) is False
    for _ in range(20):
        collector.push(42, _packet())
    collector.cleanup()

    assert utterances == []


def test_collector_caps_long_utterance_and_ignores_until_speaking_stop():
    utterances: list[discord_voice.VoiceUtterance] = []
    collector = discord_voice.CreatorPcmCollector(42, utterances.append)
    packet = _packet(0.2)

    disposition = ""
    for _ in range(100):
        disposition = collector.push(42, packet)
        if disposition == "emitted-cap":
            break

    assert disposition == "emitted-cap"
    assert collector.push(42, packet) == "capped"
    assert collector.finish(42) is False
    assert len(utterances) == 1
    assert utterances[0].pcm_bytes == discord_voice.MAX_UTTERANCE_PCM_BYTES
    assert utterances[0].duration_seconds == discord_voice.MAX_UTTERANCE_SECONDS


def test_stale_flush_segments_when_speaking_stop_is_missing():
    now = [100.0]
    utterances: list[discord_voice.VoiceUtterance] = []
    collector = discord_voice.CreatorPcmCollector(
        42,
        utterances.append,
        clock=lambda: now[0],
    )
    for _ in range(20):
        collector.push(42, _packet())

    now[0] += discord_voice.SILENCE_FLUSH_SECONDS - 0.01
    assert collector.flush_stale() is False
    now[0] += 0.02
    assert collector.flush_stale() is True
    assert len(utterances) == 1


def test_sink_forwards_only_decoded_creator_pcm():
    utterances: list[discord_voice.VoiceUtterance] = []
    collector = discord_voice.CreatorPcmCollector(42, utterances.append)
    sink = discord_voice.build_sink(collector)
    creator = SimpleNamespace(id=42)
    stranger = SimpleNamespace(id=99)
    data = SimpleNamespace(pcm=_packet())

    sink.write(stranger, data)
    for _ in range(20):
        sink.write(creator, data)
    sink.on_voice_member_speaking_stop(creator)

    assert sink.wants_opus() is False
    assert len(utterances) == 1


def test_voice_event_ids_are_unique_uint64_values(monkeypatch):
    monkeypatch.setattr(discord_voice, "_last_event_id", 0)

    first = discord_voice.next_voice_event_id(time_ns=1000)
    second = discord_voice.next_voice_event_id(time_ns=1000)

    assert first == "1000"
    assert second == "1001"
    assert 0 < int(second) < 1 << 64


def test_voice_audit_is_content_free(monkeypatch):
    observations: list[object] = []
    monkeypatch.setattr(
        discord_voice.cognition_mod,
        "record_observation",
        lambda observation: observations.append(observation) or 7,
    )

    observation_id = discord_voice.record_voice_event(
        "transcribed",
        duration_seconds=1.23456,
        size_bytes=1234,
    )

    assert observation_id == 7
    assert len(observations) == 1
    observation = observations[0]
    assert observation.source == "discord_voice"
    assert observation.metadata == {
        "event": "discord_voice",
        "status": "transcribed",
        "duration_seconds": 1.235,
        "size_bytes": 1234,
        "reason": "",
        "processing": "local-only",
        "raw_audio_persisted": False,
    }
    assert "transcript" not in str(observation.metadata).casefold()


def test_voice_readiness_reports_duplex_only_when_receive_is_ready(monkeypatch):
    monkeypatch.setattr(discord_bridge, "VOICE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "VOICE_RECEIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge.discord.opus, "is_loaded", lambda: True)
    monkeypatch.setattr(discord_bridge, "_ffmpeg_exe", lambda: "ffmpeg-test")
    monkeypatch.setattr(
        discord_bridge.importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(),
    )
    monkeypatch.setattr(
        discord_bridge.discord_voice,
        "receive_readiness",
        lambda *, enabled: {
            "enabled": enabled,
            "status": "ready",
            "scope": "creator-only",
        },
    )

    readiness = discord_bridge.voice_readiness()

    assert readiness["status"] == "ready"
    assert readiness["mode"] == "duplex"
    assert readiness["receive"] == {
        "enabled": True,
        "status": "ready",
        "scope": "creator-only",
    }


class _ReceiveVoiceClient:
    def __init__(self) -> None:
        self.sink = None
        self.after = None
        self.stop_listening_calls = 0
        self.stop_playing_calls = 0
        self.playing = True

    def is_connected(self) -> bool:
        return True

    def is_playing(self) -> bool:
        return self.playing

    def stop_playing(self) -> None:
        self.stop_playing_calls += 1
        self.playing = False

    def listen(self, sink, *, after) -> None:
        self.sink = sink
        self.after = after

    def stop_listening(self) -> None:
        self.stop_listening_calls += 1


class _ReceiveTextChannel:
    id = 3001

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content: str) -> None:
        self.sent.append(content)


def test_creator_voice_session_transcribes_replies_and_discards_audio(monkeypatch):
    room = {"guild_id": "777", "channel_id": "3001"}
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: {"777:3001": room})
    monkeypatch.setattr(discord_bridge, "VOICE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "VOICE_RECEIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", {"42"})
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", set())
    monkeypatch.setattr(
        discord_bridge,
        "voice_readiness",
        lambda: {
            "enabled": True,
            "mode": "duplex",
            "status": "ready",
            "receive": {"enabled": True, "status": "ready"},
        },
    )
    monkeypatch.setattr(
        discord_bridge.hearing,
        "transcribe",
        lambda _audio: "Can you tell me what changed today?",
    )
    audit_statuses: list[str] = []

    def record(status: str, **_kwargs: object) -> int:
        audit_statuses.append(status)
        return len(audit_statuses)

    monkeypatch.setattr(discord_bridge.discord_voice, "record_voice_event", record)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def ask(*args: object, **kwargs: object) -> str:
        calls.append((args, kwargs))
        return "The duplex voice path is active."

    monkeypatch.setattr(discord_bridge, "_ask_alpecca", ask)
    monkeypatch.setattr(discord_bridge, "_synth_voice_wav", lambda _text: None)
    client = discord_bridge.build_client()
    voice_client = _ReceiveVoiceClient()
    guild = SimpleNamespace(id=777, voice_client=voice_client)
    channel = _ReceiveTextChannel()
    creator = SimpleNamespace(id=42, name="realcreatorjd", display_name="CreatorJD")

    async def scenario() -> None:
        started = await getattr(client, "_alpecca_start_voice_receive")(
            guild,
            channel,
            creator,
        )
        assert started is True
        assert voice_client.sink is not None
        data = SimpleNamespace(pcm=_packet())
        for _ in range(20):
            voice_client.sink.write(creator, data)
        voice_client.sink.on_voice_member_speaking_stop(creator)
        for _ in range(100):
            if channel.sent:
                break
            await asyncio.sleep(0.01)
        await getattr(client, "_alpecca_stop_voice_receive")(guild)

    asyncio.run(scenario())

    assert voice_client.stop_playing_calls == 1
    assert voice_client.stop_listening_calls == 1
    assert channel.sent == ["The duplex voice path is active."]
    assert audit_statuses == ["accepted", "transcribed"]
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[1:4] == ("Discord guest", "discord", "guest")
    assert "Can you tell me what changed today?" in str(args[0])
    assert kwargs["room"] == "discord"
    assert kwargs["actor_bindings"] == DiscordActorBindings(
        event_id=kwargs["actor_bindings"].event_id,
        actor_id="42",
        guild_id="777",
        channel_id="3001",
    )
    assert getattr(client, "_alpecca_voice_receive_sessions") == {}


def test_creator_voice_session_fails_closed_when_audit_is_unavailable(monkeypatch):
    room = {"guild_id": "777", "channel_id": "3001"}
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: {"777:3001": room})
    monkeypatch.setattr(discord_bridge, "VOICE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "VOICE_RECEIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", {"42"})
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", set())
    monkeypatch.setattr(
        discord_bridge,
        "voice_readiness",
        lambda: {
            "enabled": True,
            "mode": "duplex",
            "status": "ready",
            "receive": {"enabled": True, "status": "ready"},
        },
    )
    monkeypatch.setattr(
        discord_bridge.discord_voice,
        "record_voice_event",
        lambda *_args, **_kwargs: None,
    )
    transcriptions: list[bytes] = []
    monkeypatch.setattr(
        discord_bridge.hearing,
        "transcribe",
        lambda audio: transcriptions.append(audio) or "must not run",
    )
    client = discord_bridge.build_client()
    voice_client = _ReceiveVoiceClient()
    voice_client.playing = False
    guild = SimpleNamespace(id=777, voice_client=voice_client)
    channel = _ReceiveTextChannel()
    creator = SimpleNamespace(id=42, name="realcreatorjd", display_name="CreatorJD")

    async def scenario() -> None:
        assert await getattr(client, "_alpecca_start_voice_receive")(
            guild,
            channel,
            creator,
        )
        data = SimpleNamespace(pcm=_packet())
        for _ in range(20):
            voice_client.sink.write(creator, data)
        voice_client.sink.on_voice_member_speaking_stop(creator)
        await asyncio.sleep(0.1)
        await getattr(client, "_alpecca_stop_voice_receive")(guild)

    asyncio.run(scenario())

    assert transcriptions == []
    assert channel.sent == []


def test_creator_join_command_uses_receive_client_and_starts_listener(monkeypatch):
    room = {"guild_id": "777", "channel_id": "3001"}
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: {"777:3001": room})
    monkeypatch.setattr(discord_bridge, "VOICE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "VOICE_RECEIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", {"42"})
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", set())
    monkeypatch.setattr(discord_bridge, "RECURSIVE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "_synth_voice_wav", lambda _text: None)
    monkeypatch.setattr(
        discord_bridge,
        "voice_readiness",
        lambda: {
            "enabled": True,
            "mode": "duplex",
            "status": "ready",
            "receive": {"enabled": True, "status": "ready"},
        },
    )
    receive_client_class = object()
    monkeypatch.setattr(
        discord_bridge.discord_voice,
        "voice_client_class",
        lambda: receive_client_class,
    )
    client = discord_bridge.build_client()
    client._connection.user = SimpleNamespace(
        id=9001,
        name="Alpecca",
        display_name="Alpecca",
    )
    voice_client = _ReceiveVoiceClient()
    voice_client.playing = False
    guild = SimpleNamespace(
        id=777,
        voice_client=None,
        me=SimpleNamespace(display_name="Alpecca"),
    )

    class VoiceChannel:
        name = "General"

        def __init__(self) -> None:
            self.client_class = None

        def permissions_for(self, _member):
            return SimpleNamespace(connect=True, speak=True)

        async def connect(self, *, cls=None):
            self.client_class = cls
            guild.voice_client = voice_client
            return voice_client

    voice_channel = VoiceChannel()
    channel = _ReceiveTextChannel()
    creator = SimpleNamespace(
        id=42,
        name="realcreatorjd",
        display_name="CreatorJD",
        bot=False,
        voice=SimpleNamespace(channel=voice_channel),
    )
    replies: list[str] = []

    async def reply(content: str, **_kwargs: object) -> None:
        replies.append(content)

    message = SimpleNamespace(
        id=1001,
        author=creator,
        guild=guild,
        channel=channel,
        content="<@9001> join voice",
        clean_content="@Alpecca join voice",
        mentions=[client.user],
        attachments=[],
        reference=None,
        reply=reply,
    )

    async def scenario() -> None:
        await client.on_message(message)
        await asyncio.sleep(0.05)
        assert getattr(client, "_alpecca_voice_receive_sessions")
        await getattr(client, "_alpecca_stop_voice_receive")(guild)

    asyncio.run(scenario())

    assert voice_channel.client_class is receive_client_class
    assert voice_client.sink is not None
    assert any("I can hear CreatorJD here" in item for item in replies)
