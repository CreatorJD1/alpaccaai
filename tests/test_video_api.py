from __future__ import annotations

import json

import pytest

from alpecca.video_api import (
    Actor,
    ActorKind,
    AuthorizationMetadata,
    AuthorizationState,
    CreateSessionRequest,
    CreateSessionResponse,
    MediaReference,
    PlaybackControl,
    PlaybackControlRequest,
    PlaybackControlResponse,
    PlaybackEvent,
    PlaybackState,
    SessionState,
    SourceKind,
    StatusRequest,
    StatusResponse,
    Surface,
    TranscriptEvent,
    VideoAPIError,
    VisualDescriptorEvent,
    contract_from_dict,
)


def actor(kind: ActorKind = ActorKind.CREATOR) -> Actor:
    return Actor(actor_id="actor-1", kind=kind, display_name="Creator")


def authorization(
    state: AuthorizationState = AuthorizationState.AUTHORIZED,
) -> AuthorizationMetadata:
    if state is AuthorizationState.AUTHORIZED:
        return AuthorizationMetadata(
            state=state,
            principal="creator",
            mechanism="signed-session",
            scopes=("video.session.create", "video.playback.control", "video.status.read"),
            evidence_ids=("session-proof-1",),
            expires_at=20_000.0,
        )
    return AuthorizationMetadata(
        state=state,
        principal=None,
        mechanism="public-observation",
    )


def event_fields(
    *, surface: Surface = Surface.HOUSE_HQ, seq: int = 1, timestamp: float = 12.5
) -> dict[str, object]:
    return {
        "session_id": "video-session-1",
        "seq": seq,
        "turn_id": "turn-7",
        "media_timestamp": timestamp,
        "source_kind": SourceKind.FILE,
        "surface": surface,
        "actor": actor(),
    }


def assert_event_envelope(payload: dict[str, object]) -> None:
    assert {
        "session_id",
        "seq",
        "turn_id",
        "media_timestamp",
        "source_kind",
        "surface",
        "actor",
    } <= payload.keys()


def test_create_session_house_hq_is_a_first_class_surface_and_round_trips():
    request = CreateSessionRequest(
        request_id="create-1",
        source=MediaReference(
            source_id="movie-1",
            source_kind=SourceKind.FILE,
            label="Local movie",
        ),
        surface=Surface.HOUSE_HQ,
        actor=actor(),
        authorization=authorization(),
    )
    restored = contract_from_dict(json.loads(request.to_json()))

    assert restored == request
    assert restored.surface is Surface.HOUSE_HQ
    assert restored.source.source_kind is SourceKind.FILE
    assert restored.authorization.allows("video.session.create", now=19_999.0)


def test_create_session_response_has_explicit_authorization_metadata():
    response = CreateSessionResponse(
        request_id="create-1",
        accepted=True,
        session_id="video-session-1",
        source_kind=SourceKind.LIVE,
        surface=Surface.HOUSE_HQ,
        actor=actor(ActorKind.ALPECCA),
        status=SessionState.ACTIVE,
        authorization=authorization(),
    )

    payload = response.as_dict()
    assert payload["accepted"] is True
    assert payload["authorization"]["principal"] == "creator"
    assert "token" not in json.dumps(payload).lower()


def test_discord_uses_the_same_source_neutral_event_contract_as_an_adapter():
    house = TranscriptEvent(
        **event_fields(surface=Surface.HOUSE_HQ),
        text="Welcome back",
        final=True,
        language="en-US",
    )
    discord = TranscriptEvent(
        **event_fields(surface=Surface.DISCORD),
        text="Welcome back",
        final=True,
        language="en-US",
    )

    assert type(house) is type(discord)
    assert house.surface is Surface.HOUSE_HQ
    assert discord.surface is Surface.DISCORD
    assert house.as_dict().keys() == discord.as_dict().keys()


def test_transcript_and_visual_events_carry_complete_envelopes():
    transcript = TranscriptEvent(
        **event_fields(seq=1), text="A line of dialogue", final=False
    )
    visual = VisualDescriptorEvent(
        **event_fields(seq=2),
        descriptor="Two people enter the room",
        confidence=0.82,
        labels=("person", "room"),
    )

    for event in (transcript, visual):
        payload = event.as_dict()
        assert_event_envelope(payload)
        assert contract_from_dict(payload) == event


def test_playback_position_and_state_are_explicit_and_consistent():
    playback = PlaybackEvent(
        **event_fields(timestamp=48.25),
        position=48.25,
        state=PlaybackState.PLAYING,
        duration=120.0,
    )

    payload = playback.as_dict()
    assert_event_envelope(payload)
    assert payload["position"] == 48.25
    assert payload["state"] == "playing"
    assert contract_from_dict(payload) == playback

    with pytest.raises(VideoAPIError, match="must match"):
        PlaybackEvent(
            **event_fields(timestamp=48.25),
            position=49.0,
            state=PlaybackState.PLAYING,
        )


@pytest.mark.parametrize("action", list(PlaybackControl))
def test_pause_resume_and_stop_request_response_contracts(action):
    request = PlaybackControlRequest(
        **event_fields(timestamp=30.0),
        request_id=f"control-{action.value}",
        action=action,
        authorization=authorization(),
    )
    response = PlaybackControlResponse(
        **event_fields(seq=2, timestamp=30.0),
        request_id=f"control-{action.value}",
        action=action,
        accepted=True,
        state=(PlaybackState.PAUSED if action is PlaybackControl.PAUSE else PlaybackState.STOPPED if action is PlaybackControl.STOP else PlaybackState.PLAYING),
        authorization=authorization(),
    )

    assert contract_from_dict(request.as_dict()) == request
    assert contract_from_dict(response.as_dict()) == response
    assert request.authorization.allows("video.playback.control", now=10.0)
    assert_event_envelope(request.as_dict())
    assert_event_envelope(response.as_dict())


def test_status_request_and_response_use_the_event_envelope():
    request = StatusRequest(
        **event_fields(timestamp=61.0), authorization=authorization()
    )
    response = StatusResponse(
        **event_fields(seq=2, timestamp=61.0),
        session_state=SessionState.PAUSED,
        playback_state=PlaybackState.PAUSED,
        position=61.0,
        authorization=authorization(),
        detail="Paused by Creator",
    )

    assert contract_from_dict(request.as_dict()) == request
    assert contract_from_dict(response.as_dict()) == response
    assert_event_envelope(request.as_dict())
    assert_event_envelope(response.as_dict())


def test_media_url_removes_query_and_fragment_but_keeps_safe_https_location():
    source = MediaReference(
        source_id="stream-1",
        source_kind=SourceKind.STREAM,
        url="https://Media.Example.test/watch/episode.mp4?signature=sensitive#chapter",
    )

    assert source.url == "https://media.example.test/watch/episode.mp4"
    assert source.url_redacted is True
    assert "sensitive" not in json.dumps(source.__dict__ if hasattr(source, "__dict__") else {"url": source.url})


@pytest.mark.parametrize(
    "url",
    [
        "http://media.example.test/video.mp4",
        "https://user:password@media.example.test/video.mp4",
        "file:///private/video.mp4",
        "https://media.example.test/access_token=secret/video.mp4",
    ],
)
def test_unsafe_media_urls_are_rejected(url):
    with pytest.raises(VideoAPIError):
        MediaReference(
            source_id="stream-1",
            source_kind=SourceKind.STREAM,
            url=url,
        )


def test_text_urls_are_redacted_and_secret_tokens_are_rejected():
    transcript = TranscriptEvent(
        **event_fields(),
        text="Open https://example.test/watch?q=private now",
        final=True,
    )
    assert transcript.text == "Open [redacted-url] now"

    with pytest.raises(VideoAPIError, match="secret-like"):
        TranscriptEvent(
            **event_fields(),
            text="Authorization: Bearer abcdefghijklmnop",
            final=True,
        )


def test_raw_bytes_are_rejected_at_construction_and_parse_boundaries():
    with pytest.raises(VideoAPIError, match="raw bytes"):
        TranscriptEvent(**event_fields(), text=b"raw media", final=True)

    payload = TranscriptEvent(
        **event_fields(), text="safe", final=True
    ).as_dict()
    payload["extra"] = {"frame": b"raw"}
    with pytest.raises(VideoAPIError, match="raw bytes"):
        contract_from_dict(payload)


@pytest.mark.parametrize(
    "field",
    ["cooldown_seconds", "rate_limit", "reaction_cap", "token", "data_b64"],
)
def test_unknown_caps_and_sensitive_transport_fields_are_rejected(field):
    payload = TranscriptEvent(
        **event_fields(), text="safe", final=True
    ).as_dict()
    payload[field] = "not-allowed"

    with pytest.raises(VideoAPIError, match="forbidden field"):
        contract_from_dict(payload)


def test_authorization_metadata_is_bounded_and_never_carries_credentials():
    with pytest.raises(VideoAPIError, match="requires"):
        AuthorizationMetadata(
            state=AuthorizationState.AUTHORIZED,
            principal="creator",
            mechanism="signed-session",
        )
    with pytest.raises(VideoAPIError, match="secret-like"):
        AuthorizationMetadata(
            state=AuthorizationState.DENIED,
            principal=None,
            mechanism="Bearer abcdefghijklmnop",
        )

    metadata = authorization()
    assert metadata.allows("video.status.read", now=19_999.0)
    assert not metadata.allows("video.status.read", now=20_000.0)
    assert metadata.as_dict()["evidence_ids"] == ["session-proof-1"]


def test_parser_does_not_coerce_array_or_boolean_fields():
    request = CreateSessionRequest(
        request_id="create-1",
        source=MediaReference(
            source_id="stream-1",
            source_kind=SourceKind.STREAM,
            url="https://media.example.test/video.mp4",
        ),
        surface=Surface.HOUSE_HQ,
        actor=actor(),
        authorization=authorization(),
    ).as_dict()
    request["authorization"]["scopes"] = "video.session.create"
    with pytest.raises(VideoAPIError, match="must be a list"):
        contract_from_dict(request)

    request = CreateSessionRequest(
        request_id="create-2",
        source=MediaReference(
            source_id="stream-2",
            source_kind=SourceKind.STREAM,
            url="https://media.example.test/video.mp4",
        ),
        surface=Surface.HOUSE_HQ,
        actor=actor(),
        authorization=authorization(),
    ).as_dict()
    request["source"]["url_redacted"] = "false"
    with pytest.raises(VideoAPIError, match="must be boolean"):
        contract_from_dict(request)
