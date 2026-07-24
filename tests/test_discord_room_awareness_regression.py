from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from alpecca import discord_bridge
from alpecca import discord_media


_BOT_ID = 9001
_ROOM = {"guild_id": "777", "channel_id": "3001"}


class _Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _Channel:
    def __init__(self, history: list[object] | None = None) -> None:
        self.id = 3001
        self.guild = SimpleNamespace(
            id=777,
            me=SimpleNamespace(display_name="Alpecca"),
            voice_client=None,
        )
        self.sent: list[str] = []
        self._history = list(history or [])

    def typing(self) -> _Typing:
        return _Typing()

    def history(self, *, limit: int, oldest_first: bool):
        del limit, oldest_first

        async def records():
            for entry in self._history:
                yield entry

        return records()

    async def send(self, content: str) -> None:
        self.sent.append(content)


class _Message:
    def __init__(
        self,
        *,
        event_id: int,
        channel: _Channel,
        content: str,
        clean_content: str,
    ) -> None:
        self.id = event_id
        self.author = SimpleNamespace(
            id=42,
            name="realcreatorjd",
            display_name="CreatorJD",
            bot=False,
        )
        self.guild = channel.guild
        self.channel = channel
        self.content = content
        self.clean_content = clean_content
        self.mentions = [SimpleNamespace(id=_BOT_ID)]
        self.attachments: list[object] = []
        self.reference = None
        self.replies: list[tuple[str, dict[str, object]]] = []

    async def reply(self, content: str, **kwargs: object) -> None:
        self.replies.append((content, kwargs))


def _history_entry(
    *,
    author_id: int,
    display_name: str,
    content: str,
    bot: bool,
) -> object:
    return SimpleNamespace(
        author=SimpleNamespace(
            id=author_id,
            display_name=display_name,
            bot=bot,
        ),
        clean_content=content,
    )


def _claimed_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    voice_enabled: bool = False,
):
    room = dict(_ROOM)
    monkeypatch.setattr(discord_bridge, "DEBUG", False)
    monkeypatch.setattr(
        discord_bridge,
        "_load_social_rooms",
        lambda: {"777:3001": room},
    )
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", {"42"})
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", set())
    monkeypatch.setattr(discord_bridge, "VOICE_ENABLED", voice_enabled)
    monkeypatch.setattr(discord_bridge, "PARTICIPATE", False)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "RECURSIVE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "CHANNEL_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(discord_bridge, "_recent_voice_context", lambda *_args: [])

    client = discord_bridge.build_client()
    client._connection.user = SimpleNamespace(
        id=_BOT_ID,
        name="Alpecca",
        display_name="Alpecca",
    )
    return client, room


def test_proactive_turn_cannot_start_a_self_monologue_without_new_human_message(
    monkeypatch: pytest.MonkeyPatch,
):
    client, room = _claimed_client(monkeypatch)
    channel = _Channel(
        [
            _history_entry(
                author_id=42,
                display_name="CreatorJD",
                content="The animation timing still feels a little uneven.",
                bot=False,
            )
        ]
    )
    calls: list[str] = []

    def ask(prompt: str, _room_scope: str) -> str:
        calls.append(prompt)
        return "I noticed the same timing edge in the latest motion pass."

    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_COOLDOWN", 1.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_GLOBAL_COOLDOWN", 0.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_QUIET_MIN", 1.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_MIN_LEN", 1)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_CHANCE", 1.0)
    monkeypatch.setattr(discord_bridge, "RECURSIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "RECURSIVE_DELAY", 1.0)
    monkeypatch.setattr(discord_bridge, "RECURSIVE_MAX", 1)
    monkeypatch.setattr(discord_bridge.random, "random", lambda: 0.0)
    monkeypatch.setattr(discord_bridge, "_ask_room_autonomy", ask)

    async def scenario() -> None:
        await client._alpecca_seed_room_history(channel, room, observed_at=1.0)
        await client._alpecca_proactive_sweep_once(now=100.0)
        await client._alpecca_recursive_sweep_once(now=200.0)

    asyncio.run(scenario())

    assert channel.sent == [
        "I noticed the same timing edge in the latest motion pass."
    ]
    assert len(calls) == 1
    assert "Initiative kind: quiet-room opener after a new human turn." in calls[0]


def test_stale_restored_history_is_context_but_not_a_live_autonomy_cue(
    monkeypatch: pytest.MonkeyPatch,
):
    client, room = _claimed_client(monkeypatch)
    stale = _history_entry(
        author_id=42,
        display_name="CreatorJD",
        content="This old line should remain readable without being answered again.",
        bot=False,
    )
    stale.created_at = SimpleNamespace(timestamp=lambda: 0.0)
    channel = _Channel([stale])
    calls: list[str] = []

    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_COOLDOWN", 1.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_GLOBAL_COOLDOWN", 0.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_QUIET_MIN", 1.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_MIN_LEN", 1)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_CHANCE", 1.0)
    monkeypatch.setattr(
        discord_bridge,
        "_ask_room_autonomy",
        lambda prompt, _scope: calls.append(prompt) or "Anyone there?",
    )

    async def scenario() -> None:
        await client._alpecca_seed_room_history(channel, room, observed_at=1.0)
        await client._alpecca_proactive_sweep_once(now=10_000.0)

    asyncio.run(scenario())

    assert "This old line should remain readable" in client._alpecca_recent_context(3001)
    assert calls == []
    assert channel.sent == []


def test_stale_restored_exchange_can_earn_one_empty_room_check_in(
    monkeypatch: pytest.MonkeyPatch,
):
    client, room = _claimed_client(monkeypatch)
    human = _history_entry(
        author_id=42,
        display_name="CreatorJD",
        content="We were checking whether you can start conversations yourself.",
        bot=False,
    )
    alpecca = _history_entry(
        author_id=9001,
        display_name="Alpecca_ai",
        content="I want to follow up when I have a grounded reason.",
        bot=True,
    )
    human.created_at = SimpleNamespace(timestamp=lambda: 0.0)
    alpecca.created_at = SimpleNamespace(timestamp=lambda: 0.0)
    channel = _Channel([human, alpecca])
    prompts: list[str] = []

    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_COOLDOWN", 1.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_GLOBAL_COOLDOWN", 0.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_QUIET_MIN", 1.0)
    monkeypatch.setattr(discord_bridge, "EMPTY_ROOM_NUDGE_QUIET", 5.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_MIN_LEN", 1)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_CHANCE", 1.0)
    monkeypatch.setattr(discord_bridge.random, "random", lambda: 0.0)
    monkeypatch.setattr(
        discord_bridge,
        "_ask_room_autonomy",
        lambda prompt, _scope: prompts.append(prompt) or "Jason? I had one follow-up thought.",
    )

    async def scenario() -> None:
        await client._alpecca_seed_room_history(channel, room, observed_at=1.0)
        await client._alpecca_proactive_sweep_once(now=10.0)
        await client._alpecca_proactive_sweep_once(now=20.0)

    asyncio.run(scenario())

    assert channel.sent == ["Jason? I had one follow-up thought."]
    assert len(prompts) == 1
    assert "Initiative kind: deliberate empty-room check-in." in prompts[0]


def test_creator_dm_can_receive_one_bounded_unprompted_follow_up(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(discord_bridge, "DEBUG", False)
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: {})
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", {"42"})
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", set())
    monkeypatch.setattr(discord_bridge, "PUBLIC_DMS", False)
    monkeypatch.setattr(discord_bridge, "VOICE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "PARTICIPATE", False)
    monkeypatch.setattr(discord_bridge, "RECURSIVE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_COOLDOWN", 0.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_GLOBAL_COOLDOWN", 0.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_QUIET_MIN", 1.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_MIN_LEN", 1)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_CHANCE", 1.0)
    monkeypatch.setattr(
        discord_bridge.random,
        "random",
        lambda: (_ for _ in ()).throw(
            AssertionError("an established DM must not use a random initiative gate")
        ),
    )
    monkeypatch.setattr(discord_bridge, "_ask_alpecca", lambda *_a, **_k: "I heard you.")
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "resolve_outbound_media",
        lambda _text: None,
    )
    prompts: list[str] = []
    monkeypatch.setattr(
        discord_bridge,
        "_ask_room_autonomy",
        lambda prompt, _scope: prompts.append(prompt) or "One more thought: how are you doing?",
    )

    client = discord_bridge.build_client()
    client._connection.user = SimpleNamespace(
        id=_BOT_ID,
        name="Alpecca",
        display_name="Alpecca",
    )
    channel = _Channel()
    channel.guild = None
    message = _Message(
        event_id=5001,
        channel=channel,
        content="I have had a long day.",
        clean_content="I have had a long day.",
    )
    message.guild = None
    message.mentions = []

    async def scenario() -> None:
        await client.on_message(message)
        later = discord_bridge.time.monotonic() + 10.0
        await client._alpecca_proactive_sweep_once(now=later)
        await client._alpecca_proactive_sweep_once(now=later + 10.0)

    asyncio.run(scenario())

    assert message.replies == [("I heard you.", {"mention_author": False})]
    assert channel.sent == ["One more thought: how are you doing?"]
    assert len(prompts) == 1
    assert "Initiative kind: quiet-room opener after a new human turn." in prompts[0]


def test_proactive_voice_contradiction_is_corrected_once_without_self_repeat(
    monkeypatch: pytest.MonkeyPatch,
):
    client, room = _claimed_client(monkeypatch, voice_enabled=True)
    channel = _Channel(
        [
            _history_entry(
                author_id=42,
                display_name="CreatorJD",
                content="The live voice timing sounds better now.",
                bot=False,
            )
        ]
    )

    class VoiceClient:
        channel = SimpleNamespace(
            name="General",
            members=[SimpleNamespace(id=42, bot=False)],
        )

        @staticmethod
        def is_connected() -> bool:
            return True

        @staticmethod
        def is_playing() -> bool:
            return False

        @staticmethod
        def listen(_sink: object, *, after: object) -> None:
            del after

        @staticmethod
        def play(_source: object, *, after: object) -> None:
            del after

    channel.guild.voice_client = VoiceClient()
    calls: list[str] = []

    def ask(prompt: str, _room_scope: str) -> str:
        calls.append(prompt)
        return "I only exist as text, so I'm absent from the voice channel."

    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_COOLDOWN", 1.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_GLOBAL_COOLDOWN", 0.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_QUIET_MIN", 1.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_MIN_LEN", 1)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_CHANCE", 1.0)
    monkeypatch.setattr(discord_bridge.random, "random", lambda: 0.0)
    monkeypatch.setattr(discord_bridge, "_ask_room_autonomy", ask)
    monkeypatch.setattr(
        discord_bridge,
        "voice_readiness",
        lambda: {
            "enabled": True,
            "status": "ready",
            "receive": {"enabled": True, "status": "ready"},
        },
    )
    monkeypatch.setattr(discord_bridge.hearing, "_ready", True)
    monkeypatch.setattr(discord_bridge.hearing, "_model", object())
    getattr(client, "_alpecca_voice_receive_sessions")[777] = {
        "listener_active": True,
    }
    monkeypatch.setattr(discord_bridge, "_synth_voice_wav", lambda _text: None)

    async def scenario() -> None:
        await client._alpecca_seed_room_history(channel, room, observed_at=1.0)
        await client._alpecca_proactive_sweep_once(now=100.0)
        await asyncio.sleep(0)
        await client._alpecca_proactive_sweep_once(now=200.0)

    asyncio.run(scenario())

    assert len(calls) == 1
    assert len(channel.sent) == 1
    assert channel.sent[0].startswith("I'm in **General** with you now.")
    assert "absent" not in channel.sent[0].casefold()
    assert "only exist as text" not in channel.sent[0].casefold()


def test_bot_alias_counts_as_alpecca_for_recent_reply_dedupe():
    repeated = "I already shared the relevant motion detail above."

    assert discord_bridge._room_reply_repeats_self(
        repeated,
        [("Alpecca_ai", repeated)],
    ) is True


def test_plain_room_message_does_not_reemit_stale_media_disabled_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
):
    client, _room = _claimed_client(monkeypatch)
    channel = _Channel()
    model_inputs: list[str] = []
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", False)
    monkeypatch.setattr(
        discord_bridge,
        "_ask_alpecca",
        lambda text, *_args, **_kwargs: model_inputs.append(text)
        or "I can help with the next room topic.",
    )

    image_request = _Message(
        event_id=1001,
        channel=channel,
        content="<@9001> Can you send me an image of yourself?",
        clean_content="@Alpecca Can you send me an image of yourself?",
    )
    plain_message = _Message(
        event_id=1002,
        channel=channel,
        content="<@9001> What should we check next?",
        clean_content="@Alpecca What should we check next?",
    )

    async def scenario() -> None:
        await client.on_message(image_request)
        await client.on_message(plain_message)

    asyncio.run(scenario())

    media_disabled = discord_media.media_diagnostic("media-disabled")
    assert image_request.replies == [(media_disabled, {"mention_author": False})]
    assert plain_message.replies == [
        ("I can help with the next room topic.", {"mention_author": False})
    ]
    assert media_disabled not in [reply for reply, _kwargs in plain_message.replies]
    assert len(model_inputs) == 1


def test_newer_human_room_turn_supersedes_an_older_inflight_direct_reply(
    monkeypatch: pytest.MonkeyPatch,
):
    """A slow first model call may never speak after a newer human line."""

    client, _room = _claimed_client(monkeypatch)
    channel = _Channel()
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def ask(_text: str, *_args, **_kwargs) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            assert release.wait(timeout=2.0)
            return "This stale answer must not be delivered."
        return "This is the current answer."

    monkeypatch.setattr(discord_bridge, "_ask_alpecca", ask)
    first = _Message(
        event_id=1101,
        channel=channel,
        content="<@9001> first question",
        clean_content="@Alpecca first question",
    )
    second = _Message(
        event_id=1102,
        channel=channel,
        content="<@9001> second question",
        clean_content="@Alpecca second question",
    )

    async def scenario() -> None:
        older = asyncio.create_task(client.on_message(first))
        assert await asyncio.to_thread(started.wait, 2.0)
        await client.on_message(second)
        release.set()
        await older

    asyncio.run(scenario())

    assert first.replies == []
    assert second.replies == [("This is the current answer.", {"mention_author": False})]


def test_stale_media_candidate_becomes_a_sent_current_text_turn_correction(
    monkeypatch: pytest.MonkeyPatch,
):
    client, _room = _claimed_client(monkeypatch)
    channel = _Channel()
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", False)
    monkeypatch.setattr(
        discord_bridge,
        "_ask_alpecca",
        lambda *_args, **_kwargs: discord_media.media_diagnostic("media-disabled"),
    )
    message = _Message(
        event_id=1004,
        channel=channel,
        content="<@9001> What should we check next?",
        clean_content="@Alpecca What should we check next?",
    )

    asyncio.run(client.on_message(message))

    assert message.replies == [(
        discord_media.stale_media_turn_correction(),
        {"mention_author": False},
    )]
    assert "media" not in message.replies[0][0].casefold()


def test_media_transport_reply_consumes_cue_before_proactive_sweep(
    monkeypatch: pytest.MonkeyPatch,
):
    client, room = _claimed_client(monkeypatch)
    channel = _Channel()
    autonomy_calls: list[str] = []
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_COOLDOWN", 1.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_GLOBAL_COOLDOWN", 0.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_QUIET_MIN", 1.0)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_MIN_LEN", 1)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_CHANCE", 1.0)
    monkeypatch.setattr(discord_bridge.random, "random", lambda: 0.0)
    monkeypatch.setattr(
        discord_bridge,
        "_ask_room_autonomy",
        lambda prompt, _scope: autonomy_calls.append(prompt) or "Do not send this.",
    )
    message = _Message(
        event_id=1006,
        channel=channel,
        content="<@9001> Can you send me an image of yourself?",
        clean_content="@Alpecca Can you send me an image of yourself?",
    )

    async def scenario() -> None:
        await client._alpecca_seed_room_history(channel, room, observed_at=1.0)
        await client.on_message(message)
        await client._alpecca_proactive_sweep_once(
            now=discord_bridge.time.monotonic() + 100.0
        )

    asyncio.run(scenario())

    assert message.replies == [(
        discord_media.media_diagnostic("media-disabled"),
        {"mention_author": False},
    )]
    assert autonomy_calls == []
    assert channel.sent == []


def test_live_voice_truth_correction_preserves_normal_room_reply_delivery(
    monkeypatch: pytest.MonkeyPatch,
):
    client, _room = _claimed_client(monkeypatch, voice_enabled=True)
    monkeypatch.setattr(discord_bridge, "VOICE_RECEIVE_ENABLED", True)
    channel = _Channel()

    class VoiceClient:
        channel = SimpleNamespace(
            name="General",
            members=[SimpleNamespace(id=42, bot=False)],
        )

        @staticmethod
        def is_connected() -> bool:
            return True

        @staticmethod
        def is_playing() -> bool:
            return False

        @staticmethod
        def listen(_sink: object, *, after: object) -> None:
            del after

        @staticmethod
        def play(_source: object, *, after: object) -> None:
            del after

    channel.guild.voice_client = VoiceClient()
    monkeypatch.setattr(
        discord_bridge,
        "voice_readiness",
        lambda: {
            "enabled": True,
            "status": "ready",
            "receive": {"enabled": True, "status": "ready"},
        },
    )
    monkeypatch.setattr(discord_bridge.hearing, "_ready", True)
    monkeypatch.setattr(discord_bridge.hearing, "_model", object())
    getattr(client, "_alpecca_voice_receive_sessions")[777] = {
        "listener_active": True,
    }
    monkeypatch.setattr(discord_bridge, "_synth_voice_wav", lambda _text: None)
    monkeypatch.setattr(
        discord_bridge,
        "_ask_alpecca",
        lambda *_args, **_kwargs: (
            "I can only communicate through text, so I'm absent from voice."
        ),
    )
    message = _Message(
        event_id=1005,
        channel=channel,
        content="<@9001> Are you here with me?",
        clean_content="@Alpecca Are you here with me?",
    )

    asyncio.run(client.on_message(message))

    assert len(message.replies) == 1
    reply = message.replies[0][0]
    assert reply.startswith("I'm in **General** with you now.")
    assert "can hear short utterances after local transcription" in reply
    assert "text" not in reply.casefold()
    assert "absent" not in reply.casefold()


def test_addressed_reply_does_not_repeat_alpecca_recent_content(
    monkeypatch: pytest.MonkeyPatch,
):
    client, room = _claimed_client(monkeypatch)
    repeated = "The current motion pass still needs a slower settle."
    channel = _Channel(
        [
            _history_entry(
                author_id=42,
                display_name="CreatorJD",
                content="What should we change in this pass?",
                bot=False,
            ),
            _history_entry(
                author_id=_BOT_ID,
                display_name="Alpecca_ai",
                content=repeated,
                bot=True,
            ),
        ]
    )
    model_inputs: list[str] = []
    monkeypatch.setattr(
        discord_bridge,
        "_ask_alpecca",
        lambda text, *_args, **_kwargs: model_inputs.append(text) or repeated,
    )
    message = _Message(
        event_id=1003,
        channel=channel,
        content="<@9001> You already said that.",
        clean_content="@Alpecca You already said that.",
    )

    async def scenario() -> None:
        await client._alpecca_seed_room_history(channel, room, observed_at=1.0)
        await client.on_message(message)

    asyncio.run(scenario())

    assert len(model_inputs) == 1
    assert message.replies == []
    assert channel.sent == []


def test_direct_room_turn_keeps_latest_message_separate_from_live_transcript(
    monkeypatch: pytest.MonkeyPatch,
):
    client, room = _claimed_client(monkeypatch)
    channel = _Channel(
        [
            _history_entry(
                author_id=42,
                display_name="CreatorJD",
                content="I want to ask something personal.",
                bot=False,
            ),
            _history_entry(
                author_id=_BOT_ID,
                display_name="Alpecca_ai",
                content="I'm listening.",
                bot=True,
            ),
        ]
    )
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def ask(*args: object, **kwargs: object) -> str:
        calls.append((args, kwargs))
        return "I can answer that directly."

    monkeypatch.setattr(discord_bridge, "_ask_alpecca", ask)
    message = _Message(
        event_id=1006,
        channel=channel,
        content="<@9001> do you feel lonely?",
        clean_content="@Alpecca do you feel lonely?",
    )

    async def scenario() -> None:
        await client._alpecca_seed_room_history(channel, room, observed_at=1.0)
        await client.on_message(message)

    asyncio.run(scenario())

    assert calls[0][0][0] == "do you feel lonely?"
    context = str(calls[0][1]["context"])
    assert "Recent Discord room transcript" in context
    assert "I want to ask something personal." in context
    assert "do you feel lonely?" in context


def test_stalled_room_reply_is_retained_in_short_term_context(
    monkeypatch: pytest.MonkeyPatch,
):
    client, room = _claimed_client(monkeypatch)
    channel = _Channel()

    def stalled(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("local timeout")

    monkeypatch.setattr(discord_bridge, "_ask_alpecca", stalled)
    first = _Message(
        event_id=1007,
        channel=channel,
        content="<@9001> do you feel lonely?",
        clean_content="@Alpecca do you feel lonely?",
    )
    asyncio.run(client.on_message(first))

    assert first.replies == [(
        "I still have your last message in this room's short context, "
        "but my local reply timed out. I won't pretend I answered it.",
        {"mention_author": False},
    )]

    calls: list[dict[str, object]] = []

    def recovered(*_args: object, **kwargs: object) -> str:
        calls.append(kwargs)
        return "I am back with the room context."

    monkeypatch.setattr(discord_bridge, "_ask_alpecca", recovered)
    second = _Message(
        event_id=1008,
        channel=channel,
        content="<@9001> please answer it now",
        clean_content="@Alpecca please answer it now",
    )
    asyncio.run(client.on_message(second))

    context = str(calls[0]["context"])
    assert "do you feel lonely?" in context
    assert "I won't pretend I answered it." in context
