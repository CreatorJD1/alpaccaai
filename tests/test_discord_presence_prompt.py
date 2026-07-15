from alpecca.prompts import discord_presence_prompt


def test_connected_presence_prevents_text_only_claim_and_lists_confirmed_voice_facts():
    prompt = discord_presence_prompt(
        connected=True,
        voice_output=True,
        voice_receive=True,
    )

    assert "currently connected to Discord voice" in prompt
    assert "text-only" in prompt
    assert "can speak replies" in prompt
    assert "can receive bounded participant speech" in prompt


def test_connected_presence_omits_voice_capabilities_not_confirmed_by_runtime_state():
    prompt = discord_presence_prompt(connected=True)

    assert "currently connected to Discord voice" in prompt
    assert "text-only" in prompt
    assert "can speak replies" not in prompt
    assert "can receive bounded participant speech" not in prompt


def test_disconnected_presence_does_not_invent_voice_capabilities():
    prompt = discord_presence_prompt(
        connected=False,
        voice_output=True,
        voice_receive=True,
    )

    assert prompt == (
        "Discord runtime fact for this turn: Alpecca is not currently "
        "connected to Discord voice."
    )
    assert "can speak replies" not in prompt
    assert "can receive bounded participant speech" not in prompt
