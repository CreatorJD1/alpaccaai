from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from alpecca import discord_bridge


class _VoiceClient:
    def __init__(self, *, playing: bool = False, human_count: int = 1) -> None:
        self.channel = SimpleNamespace(
            name="General",
            members=[
                SimpleNamespace(id=100 + index, bot=False)
                for index in range(human_count)
            ],
        )
        self.playing = playing

    def is_connected(self) -> bool:
        return True

    def is_playing(self) -> bool:
        return self.playing

    def listen(self, _sink: object, *, after: object) -> None:
        del after

    def play(self, _source: object, *, after: object) -> None:
        del after

    def stop_playing(self) -> None:
        self.playing = False


def _ready_voice_posture(*, output_ready: bool = True) -> dict[str, object]:
    return {
        "enabled": True,
        "status": "ready" if output_ready else "unavailable",
        "receive": {"enabled": True, "status": "ready"},
    }


def _build_voice_client(monkeypatch, *, output_ready: bool = True):
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: {})
    monkeypatch.setattr(discord_bridge, "VOICE_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "VOICE_RECEIVE_ENABLED", True)
    monkeypatch.setattr(
        discord_bridge,
        "voice_readiness",
        lambda: _ready_voice_posture(output_ready=output_ready),
    )
    return discord_bridge.build_client()


def test_presence_omits_transcription_until_the_local_model_is_loaded(monkeypatch):
    monkeypatch.setattr(discord_bridge.hearing, "_ready", None)
    monkeypatch.setattr(discord_bridge.hearing, "_model", None)
    client = _build_voice_client(monkeypatch)
    guild = SimpleNamespace(id=77, voice_client=_VoiceClient())

    context = getattr(client, "_alpecca_voice_presence_context")(guild)
    corrected = getattr(client, "_alpecca_ground_voice_presence_reply")(
        "I'm text-only, so I can't join voice.",
        guild,
    )

    assert "Confirmed current capability: she can speak replies" in context
    assert "can receive bounded participant speech" not in context
    assert "Voice receive is available but its inbound listener is not active." in context
    assert "hear short utterances after local transcription" not in context
    assert "I can speak here." in corrected
    assert "Voice receive is available, but my listener is not active." in corrected


def test_new_human_input_interrupts_active_discord_voice_playback(monkeypatch):
    client = _build_voice_client(monkeypatch)
    voice_client = _VoiceClient(playing=True)
    guild = SimpleNamespace(id=77, voice_client=voice_client)

    getattr(client, "_alpecca_interrupt_voice_playback")(guild, reason="text_input")

    assert voice_client.playing is False


def test_vad_onset_interrupts_playback_without_invalidating_committed_reply(
    monkeypatch,
):
    client = _build_voice_client(monkeypatch)
    voice_client = _VoiceClient(playing=True)
    guild = SimpleNamespace(id=77, voice_client=voice_client)
    generations = getattr(client, "_alpecca_voice_generation")

    interrupt = getattr(client, "_alpecca_interrupt_voice_playback")
    interrupt(
        guild,
        reason="voice_input",
        invalidate_generation=False,
    )
    interrupt(
        guild,
        reason="duplicate_vad_start",
        invalidate_generation=False,
    )

    assert voice_client.playing is False
    assert generations.get(77, 0) == 0

    interrupt(guild, reason="text_input")
    assert generations[77] == 1


def test_same_channel_voice_state_change_does_not_restart_listener(monkeypatch):
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", {"42"})
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", set())
    client = _build_voice_client(monkeypatch)
    voice_client = _VoiceClient()
    voice_client.channel.id = 4001
    guild = SimpleNamespace(id=77, voice_client=voice_client)
    member = SimpleNamespace(
        id=42,
        name="realcreatorjd",
        display_name="CreatorJD",
        bot=False,
        guild=guild,
    )
    session = {"listener_active": True}
    getattr(client, "_alpecca_voice_receive_sessions")[77] = session
    before = SimpleNamespace(channel=voice_client.channel, self_mute=False)
    after = SimpleNamespace(channel=voice_client.channel, self_mute=True)

    asyncio.run(client.on_voice_state_update(member, before, after))

    assert getattr(client, "_alpecca_voice_receive_sessions")[77] is session


def test_presence_distinguishes_connected_from_having_a_human_audience(monkeypatch):
    client = _build_voice_client(monkeypatch)
    guild = SimpleNamespace(
        id=77,
        voice_client=_VoiceClient(human_count=0),
    )

    context = getattr(client, "_alpecca_voice_presence_context")(guild)
    corrected = getattr(client, "_alpecca_ground_voice_presence_reply")(
        "Try saying hello in the voice channel again.",
        guild,
    )

    assert "no human is currently in that voice channel" in context
    assert "alone there" in context
    assert "no human is currently in that voice channel with me" in corrected
    assert "with you now" not in corrected


def test_presence_and_correction_use_active_listener_and_loaded_transcriber(monkeypatch):
    prompt_calls: list[dict[str, bool]] = []

    def presence_prompt(**kwargs: bool) -> str:
        prompt_calls.append(kwargs)
        return "runtime prompt"

    monkeypatch.setattr(discord_bridge, "discord_presence_prompt", presence_prompt)
    monkeypatch.setattr(discord_bridge.hearing, "_ready", True)
    monkeypatch.setattr(discord_bridge.hearing, "_model", object())
    client = _build_voice_client(monkeypatch)
    guild = SimpleNamespace(id=77, voice_client=_VoiceClient(playing=True))
    getattr(client, "_alpecca_voice_receive_sessions")[77] = {
        "listener_active": True,
    }

    context = getattr(client, "_alpecca_voice_presence_context")(guild)
    corrected = getattr(client, "_alpecca_ground_voice_presence_reply")(
        "I'm text-only, so I can't join voice.",
        guild,
    )

    assert prompt_calls == [
        {"connected": True, "voice_output": True, "voice_receive": True},
    ]
    assert "currently speaking through Discord voice" in context
    assert "runtime prompt" in context
    assert "currently speaking through Discord voice" in corrected
    assert "can hear short utterances after local transcription" in corrected


@pytest.mark.parametrize(
    "claim",
    [
        "I can only communicate through text, so I'm not actually present in voice.",
        "I'm absent from the voice channel because I don't have a voice presence.",
        "I only exist as text and cannot be in the call with you.",
    ],
)
def test_live_voice_replaces_broader_text_only_and_absence_claims(
    monkeypatch,
    claim: str,
):
    monkeypatch.setattr(discord_bridge.hearing, "_ready", True)
    monkeypatch.setattr(discord_bridge.hearing, "_model", object())
    client = _build_voice_client(monkeypatch)
    guild = SimpleNamespace(id=77, voice_client=_VoiceClient())
    getattr(client, "_alpecca_voice_receive_sessions")[77] = {
        "listener_active": True,
    }

    corrected = getattr(client, "_alpecca_ground_voice_presence_reply")(
        claim,
        guild,
    )

    assert corrected.startswith("I'm in **General** with you now.")
    assert "can hear short utterances after local transcription" in corrected
    assert "text-only" not in corrected.casefold()
    assert "absent" not in corrected.casefold()
    assert "cannot be in" not in corrected.casefold()
