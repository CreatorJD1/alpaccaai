from __future__ import annotations

from types import SimpleNamespace

from alpecca import discord_voice, vision


def _pcm_packet(seconds: float = 0.02) -> bytes:
    return b"\x00\x00" * int(
        discord_voice.PCM_SAMPLE_RATE * discord_voice.PCM_CHANNELS * seconds
    )


def test_receive_state_uses_live_transport_instead_of_cached_listener_flag():
    class VoiceClient:
        def is_connected(self) -> bool:
            return True

        def is_playing(self) -> bool:
            return False

        def is_listening(self) -> bool:
            return False

        def listen(self, _sink, *, after) -> None:
            del after

        def play(self, _source, *, after) -> None:
            del after

    state = discord_voice.voice_runtime_state(
        voice_client=VoiceClient(),
        voice_enabled=True,
        output_ready=True,
        receive_enabled=True,
        receive_status={"status": "ready"},
        listener_active=True,
        transcriber_ready=True,
    )

    assert state["can_receive"] is True
    assert state["receiving"] is False
    assert state["can_transcribe"] is True


def test_one_room_collector_accepts_consecutive_utterances_and_fences_old_turn():
    utterances: list[discord_voice.SpeakerVoiceUtterance] = []
    collector = discord_voice.RoomPcmCollector(utterances.append)
    speaker = SimpleNamespace(id=42, bot=False, display_name="CreatorJD")

    for _ in range(20):
        assert collector.push(speaker, _pcm_packet()) in {"buffered", "vad-waiting"}
    assert collector.finish(speaker) is True
    first = utterances[-1]
    first_fence = discord_voice.VoiceTurnToken(
        first.listener_epoch, first.turn_sequence
    )

    for _ in range(20):
        collector.push(speaker, _pcm_packet())
    assert collector.finish(speaker) is True
    second = utterances[-1]
    second_fence = discord_voice.VoiceTurnToken(
        second.listener_epoch, second.turn_sequence
    )

    assert len(utterances) == 2
    assert second.listener_epoch == first.listener_epoch
    assert second.turn_sequence == first.turn_sequence + 1
    assert collector.turn_fence.is_current(first_fence) is False
    assert collector.turn_fence.is_current(second_fence) is True

    collector.cleanup()
    assert collector.turn_fence.is_current(second_fence) is False


def test_stale_video_frame_is_rejected_without_invoking_vision(monkeypatch):
    calls: list[bytes] = []
    monkeypatch.setattr(
        vision,
        "_describe_local",
        lambda image, _prompt: calls.append(image) or "visible frame",
    )
    frame = vision.EventFrame(
        image_bytes=b"\xff\xd8\xffframe\xff\xd9",
        source="video-frame",
        source_id="discord-video-17",
        captured_at=10.0,
    )

    result = vision.describe_event_frame(frame, now=30.0)

    assert result.status == "stale"
    assert result.reason == "stale-frame"
    assert result.description is None
    assert calls == []


def test_attachment_pixels_are_visible_only_after_verified_description(monkeypatch):
    payload = b"\x89PNG\r\n\x1a\n" + b"bounded attachment"
    monkeypatch.setattr(vision, "_describe_local", lambda image, _prompt: "a screenshot")
    frame = vision.EventFrame(
        image_bytes=payload,
        source="attachment",
        source_id="discord-attachment-22",
        captured_at=100.0,
    )

    result = vision.describe_event_frame(frame, now=101.0)

    assert result.status == "visible"
    assert result.source == "attachment"
    assert result.source_id == "discord-attachment-22"
    assert result.description == vision.VisionDescription(
        text="a screenshot",
        backend="local-ollama",
        processing_location="local-only",
        cloud_egress="denied",
    )


def test_frame_does_not_claim_visibility_when_backend_did_not_see_pixels(monkeypatch):
    monkeypatch.setattr(vision, "_describe_local", lambda *_args: None)
    frame = vision.EventFrame(
        image_bytes=b"\xff\xd8\xffframe\xff\xd9",
        source="video-frame",
        source_id="house-frame-3",
        captured_at=50.0,
    )

    result = vision.describe_event_frame(frame, now=51.0)

    assert result.status == "unavailable"
    assert result.description is None
    assert result.reason == "vision-backend-unavailable"
