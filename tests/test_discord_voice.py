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


def _reset_dave_stats(monkeypatch) -> None:
    monkeypatch.setattr(
        discord_voice,
        "_dave_stats",
        {
            "decrypted_packets": 0,
            "passthrough_packets": 0,
            "dropped_packets": 0,
        },
    )


def test_dave_compat_decrypts_mapped_sender_before_opus(monkeypatch):
    _reset_dave_stats(monkeypatch)
    calls: list[tuple[object, object, bytes]] = []

    class Session:
        ready = True

        def decrypt(self, user_id, media_type, payload):
            calls.append((user_id, media_type, payload))
            return b"opus-frame"

    class MediaType:
        audio = object()

    voice_client = SimpleNamespace(
        _connection=SimpleNamespace(
            dave_session=Session(),
            dave_protocol_version=1,
        ),
        _get_id_from_ssrc=lambda _ssrc: 42,
    )
    decoder = SimpleNamespace(
        sink=SimpleNamespace(voice_client=voice_client),
        ssrc=123,
        _cached_id=None,
    )
    packet = SimpleNamespace(decrypted_data=b"dave-ciphertext")

    result = discord_voice._decrypt_dave_packet(
        decoder,
        packet,
        SimpleNamespace(MediaType=MediaType),
    )

    assert result == "decrypted"
    assert decoder._cached_id == 42
    assert packet.decrypted_data == b"opus-frame"
    assert calls == [(42, MediaType.audio, b"dave-ciphertext")]
    assert discord_voice.dave_receive_status()["decrypted_packets"] == 1


def test_dave_compat_preserves_plaintext_transition_packet(monkeypatch):
    _reset_dave_stats(monkeypatch)

    class Session:
        ready = True

        def decrypt(self, _user_id, _media_type, _payload):
            raise RuntimeError("not a DAVE frame")

    voice_client = SimpleNamespace(
        _connection=SimpleNamespace(
            dave_session=Session(),
            dave_protocol_version=1,
        ),
    )
    decoder = SimpleNamespace(
        sink=SimpleNamespace(voice_client=voice_client),
        ssrc=123,
        _cached_id=42,
    )
    packet = SimpleNamespace(decrypted_data=b"plaintext-transition")

    result = discord_voice._decrypt_dave_packet(
        decoder,
        packet,
        SimpleNamespace(MediaType=SimpleNamespace(audio=object())),
    )

    assert result == "passthrough"
    assert packet.decrypted_data == b"plaintext-transition"
    assert discord_voice.dave_receive_status()["passthrough_packets"] == 1


def test_opus_guard_drops_one_bad_frame_without_stopping_receiver(monkeypatch):
    _reset_dave_stats(monkeypatch)

    class FakeOpusError(Exception):
        pass

    def decode(_decoder, _packet):
        raise FakeOpusError("corrupted stream")

    packet = SimpleNamespace(decrypted_data=b"bad-frame")
    result = discord_voice._decode_with_opus_guard(
        SimpleNamespace(),
        packet,
        decode,
        FakeOpusError,
    )

    assert result == (packet, b"")
    assert discord_voice.dave_receive_status()["dropped_packets"] == 1


def test_dave_compat_installs_idempotently_on_current_receiver():
    from discord.ext.voice_recv import opus as voice_recv_opus

    assert discord_voice.install_dave_receive_compat() is True
    first_process = voice_recv_opus.PacketDecoder._process_packet
    first_decode = voice_recv_opus.PacketDecoder._decode_packet
    assert discord_voice.install_dave_receive_compat() is True

    status = discord_voice.dave_receive_status()
    assert status["ready"] is True
    assert status["mode"] in {"native", "patched"}
    assert voice_recv_opus.PacketDecoder._process_packet is first_process
    assert voice_recv_opus.PacketDecoder._decode_packet is first_decode
    assert voice_recv_opus.PacketDecoder._alpecca_opus_guard is True


def test_live_voice_context_is_factual_and_denial_is_replaced():
    context = discord_bridge._voice_live_context(
        connected=True,
        channel_name="General",
        listener_active=True,
    )
    assert "currently connected to voice channel General" in context
    assert "listener is active" in context

    corrected = discord_bridge._enforce_voice_live_state(
        "I'm text-based AI, so I can't join voice chat.",
        connected=True,
        channel_name="General",
        listener_active=True,
    )
    assert corrected == (
        "I'm in **General** with you now, and my voice listener is active. "
        "I can hear short utterances, transcribe them locally, and answer in text and voice."
    )


def test_live_voice_guard_preserves_noncontradictory_reply():
    reply = "Yes, I'm with you in General and listening."
    assert discord_bridge._enforce_voice_live_state(
        reply,
        connected=True,
        channel_name="General",
        listener_active=True,
    ) == reply


def test_disconnected_voice_guard_corrects_false_capability_denial():
    corrected = discord_bridge._enforce_voice_live_state(
        "Since I'm a text-based AI, I can't join voice chat.",
        connected=False,
        channel_name="General",
        listener_active=False,
        voice_enabled=True,
    )

    assert corrected == (
        "I'm not connected to Discord voice right now, but voice is enabled. "
        "I can join an approved claimed room when CreatorJD asks from a voice channel."
    )
    assert discord_bridge._enforce_voice_live_state(
        "I can't join voice chat.",
        connected=False,
        channel_name="General",
        listener_active=False,
        voice_enabled=False,
    ) == "I can't join voice chat."


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


def test_room_sink_keeps_human_speakers_separate_and_ignores_bots():
    utterances: list[discord_voice.SpeakerVoiceUtterance] = []
    collector = discord_voice.RoomPcmCollector(utterances.append)
    sink = discord_voice.build_sink(collector)
    creator = SimpleNamespace(
        id=42,
        name="realcreatorjd",
        display_name="CreatorJD",
        bot=False,
    )
    guest = SimpleNamespace(
        id=77,
        name="guest",
        display_name="Guest One",
        bot=False,
    )
    bot = SimpleNamespace(id=99, name="bot", display_name="Bot", bot=True)
    data = SimpleNamespace(pcm=_packet())

    for _ in range(20):
        sink.write(creator, data)
        sink.write(guest, data)
        sink.write(bot, data)
    sink.on_voice_member_speaking_stop(creator)
    sink.on_voice_member_speaking_stop(guest)
    sink.on_voice_member_speaking_stop(bot)

    assert [(item.user_id, item.speaker_name) for item in utterances] == [
        (42, "CreatorJD"),
        (77, "Guest One"),
    ]
    assert all(item.duration_seconds >= 0.39 for item in utterances)


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
    monkeypatch.setattr(discord_bridge, "VOICE_MEMORY_ENABLED", True)
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
    encrypted_memories: list[tuple[str, dict[str, object]]] = []

    class VoiceMemoryStore:
        def remember(self, transcript: str, **kwargs: object) -> int:
            encrypted_memories.append((transcript, kwargs))
            return 11

    monkeypatch.setattr(
        discord_bridge,
        "_voice_memory_store",
        lambda: VoiceMemoryStore(),
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
    assert audit_statuses == ["accepted", "transcribed", "remembered"]
    assert encrypted_memories == [(
        "Can you tell me what changed today?",
        {
            "guild_id": 777,
            "channel_id": 3001,
            "speaker_id": 42,
            "speaker_name": "CreatorJD",
            "duration_seconds": 0.4,
        },
    )]
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


def test_voice_memory_failure_prevents_transcript_model_request(monkeypatch):
    room = {"guild_id": "777", "channel_id": "3001"}
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: {"777:3001": room})
    monkeypatch.setattr(discord_bridge, "VOICE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "VOICE_RECEIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "VOICE_MEMORY_ENABLED", True)
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
    monkeypatch.setattr(discord_bridge.hearing, "transcribe", lambda _audio: "private words")
    audit_statuses: list[str] = []
    monkeypatch.setattr(
        discord_bridge.discord_voice,
        "record_voice_event",
        lambda status, **_kwargs: audit_statuses.append(status) or len(audit_statuses),
    )

    class FailingStore:
        def remember(self, *_args, **_kwargs):
            raise OSError("disk unavailable")

    monkeypatch.setattr(discord_bridge, "_voice_memory_store", lambda: FailingStore())
    model_calls: list[str] = []
    monkeypatch.setattr(
        discord_bridge,
        "_ask_alpecca",
        lambda *_args, **_kwargs: model_calls.append("called") or "must not send",
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
        for _ in range(100):
            if "failed" in audit_statuses:
                break
            await asyncio.sleep(0.01)
        await getattr(client, "_alpecca_stop_voice_receive")(guild)

    asyncio.run(scenario())

    assert audit_statuses == ["accepted", "transcribed", "failed"]
    assert model_calls == []
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
        # Discord may hydrate an equivalent mention object instead of reusing
        # client.user; command routing must compare the numeric id.
        mentions=[SimpleNamespace(id=9001)],
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
    assert any("I can hear human participants here" in item for item in replies)
