"""Focused coverage for bounded Discord image ingress and egress."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from alpecca import discord_bridge
from alpecca import discord_media
from alpecca.bridge_actor_transport import DiscordActorBindings
from alpecca import vision


def _png(width: int = 3, height: int = 2) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png())


def test_prepare_inbound_image_sniffs_bytes_and_emits_canonical_data_url():
    prepared = discord_media.prepare_inbound_image(
        _png(),
        declared_mime_type="image/png",
    )

    assert prepared.mime_type == "image/png"
    assert prepared.size_bytes == len(_png())
    assert prepared.width == 3
    assert prepared.height == 2
    assert prepared.data_url.startswith("data:image/png;base64,")
    assert len(prepared.sha256) == 64


@pytest.mark.parametrize(
    ("payload", "declared", "reason"),
    (
        (_png(), "image/jpeg", "mime-mismatch"),
        (b"not an image", "image/png", "mime-mismatch"),
        (b"A" * (discord_media.INBOUND_MAX_BYTES + 1), None, "size-limit"),
    ),
    ids=("mime-mismatch", "invalid-bytes", "size-limit"),
)
def test_prepare_inbound_image_rejects_mismatch_invalid_bytes_and_oversize(
    payload: bytes,
    declared: str | None,
    reason: str,
):
    with pytest.raises(discord_media.DiscordImageRejected) as caught:
        discord_media.prepare_inbound_image(
            payload,
            declared_mime_type=declared,
        )

    assert caught.value.reason == reason


def test_attachment_candidate_metadata_never_substitutes_for_byte_validation():
    assert discord_media.looks_like_image_attachment("photo.png", None) is True
    assert discord_media.looks_like_image_attachment("payload.bin", "image/png") is True
    assert discord_media.looks_like_image_attachment("notes.txt", "text/plain") is False

    with pytest.raises(discord_media.DiscordImageRejected):
        discord_media.prepare_inbound_image(
            b"not a PNG",
            declared_mime_type="image/png",
        )


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("send your portrait", "portrait"),
        ("show me your base model", "base"),
        ("share your character sheet", "reference"),
        ("!image gallery", "gallery"),
        ("can you see this image?", None),
        ("open C:/private/secret.png", None),
    ),
)
def test_requested_media_kind_requires_an_explicit_closed_catalog_request(
    text: str,
    expected: str | None,
):
    assert discord_media.requested_media_kind(text) == expected


def test_outbound_catalog_returns_only_owned_bytes_and_generic_filename(tmp_path):
    avatar_dir = tmp_path / "avatar"
    character_dir = tmp_path / "character"
    _write_png(avatar_dir / "portraits" / "idle.png")
    _write_png(character_dir / "reference" / "base-model.png")
    _write_png(character_dir / "reference" / "master-character-sheet.png")
    older = character_dir / "gallery" / "self-20260712-100000.png"
    newer = character_dir / "gallery" / "self-20260712-110000.png"
    _write_png(older)
    _write_png(newer)
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    portrait = discord_media.resolve_outbound_media(
        "send your portrait",
        avatar_dir=avatar_dir,
        character_dir=character_dir,
    )
    reference = discord_media.resolve_outbound_media(
        "share your character sheet",
        avatar_dir=avatar_dir,
        character_dir=character_dir,
    )
    gallery = discord_media.resolve_outbound_media(
        "!image gallery",
        avatar_dir=avatar_dir,
        character_dir=character_dir,
    )

    assert portrait is not None
    assert portrait.filename == "alpecca-portrait.png"
    assert portrait.image_bytes == _png()
    assert reference is not None and reference.filename == "alpecca-reference.png"
    assert gallery is not None and gallery.filename == "alpecca-gallery.png"
    assert b"private" not in portrait.image_bytes


def test_outbound_catalog_fails_closed_for_missing_or_invalid_assets(tmp_path):
    avatar_dir = tmp_path / "avatar"
    character_dir = tmp_path / "character"

    assert discord_media.resolve_outbound_media(
        "send your portrait",
        avatar_dir=avatar_dir,
        character_dir=character_dir,
    ) is None

    bad = avatar_dir / "portraits" / "idle.png"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"not an image")
    assert discord_media.resolve_outbound_media(
        "send your portrait",
        avatar_dir=avatar_dir,
        character_dir=character_dir,
    ) is None


def test_bridge_posts_only_image_field_and_uses_extended_image_timeout(monkeypatch):
    calls: list[tuple[object, float]] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, *_args):
            if len(calls) == 1:
                return b'{"envelope":"signed-actor-envelope"}'
            return (
                b'{"perception":{"status":"described"},'
                b'"reply":"I can see it."}'
            )

    def fake_open_backend(request, *, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(
        discord_bridge,
        "_open_backend_request",
        fake_open_backend,
    )

    reply = discord_bridge._ask_alpecca(
        "Who is this?",
        "CreatorJD",
        "discord-dm",
        speaker="creator",
        image="data:image/png;base64,AAAA",
        actor_bindings=DiscordActorBindings(
            event_id="1001",
            actor_id="42",
            channel_id="3001",
        ),
    )

    assert reply == "I can see it."
    assert len(calls) == 2
    mint_request, mint_timeout = calls[0]
    request, timeout = calls[1]
    body = json.loads(request.data)
    assert mint_request.full_url.endswith("/channel/discord/actor-envelope")
    assert mint_request.data is request.data
    assert request.full_url.endswith("/channel/discord")
    assert body["image"] == "data:image/png;base64,AAAA"
    assert "file_name" not in body
    assert "file_data" not in body
    assert mint_timeout == discord_bridge.INBOUND_TIMEOUT
    assert timeout == discord_bridge.IMAGE_INBOUND_TIMEOUT
    assert timeout > discord_bridge.INBOUND_TIMEOUT


def test_vision_result_reports_verified_local_metadata_when_cloud_is_configured(
    monkeypatch,
):
    import config

    def reject_cloud(*_args):
        raise AssertionError("generic vision must not call a cloud provider")

    monkeypatch.setattr(config, "VISION_BACKEND", "ollama-cloud")
    monkeypatch.setattr(vision, "_describe_ollama_cloud", reject_cloud)
    monkeypatch.setattr(vision, "_describe_zerogpu", reject_cloud)
    monkeypatch.setattr(vision, "_describe_local", lambda *_args: "local view")

    default_result = vision.describe_image_result(_png())
    ambient_result = vision.describe_image_result(_png(), ambient=True)

    expected = vision.VisionDescription(
        "local view",
        "local-ollama",
        "local-only",
        "denied",
    )
    assert default_result == expected
    assert ambient_result == expected


def test_creator_dm_username_check_never_trusts_spoofable_display_name(monkeypatch):
    class Author:
        id = 42
        name = "someone-else"
        global_name = "realcreatorjd"

    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", set())
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", {"realcreatorjd"})

    assert discord_bridge._dm_author_allowed(Author()) is False
    Author.name = "realcreatorjd"
    assert discord_bridge._dm_author_allowed(Author()) is True
    assert discord_bridge.DM_ALLOW_IDS == {"42"}


def test_media_audit_contains_metadata_but_not_image_bytes(monkeypatch):
    seen = []
    monkeypatch.setattr(
        discord_media.cognition_mod,
        "record_observation",
        lambda observation: seen.append(observation) or 17,
    )

    observation_id = discord_media.record_media_event(
        "outbound",
        status="sent",
        mime_type="image/png",
        size_bytes=123,
        sha256="a" * 64,
        kind="portrait",
    )

    assert observation_id == 17
    assert seen[0].scope == "creator:discord"
    assert seen[0].metadata == {
        "event": "discord_image",
        "direction": "outbound",
        "status": "sent",
        "mime_type": "image/png",
        "size_bytes": 123,
        "sha256": "a" * 64,
        "kind": "portrait",
    }
    assert "base64" not in json.dumps(seen[0].metadata)


def test_media_readiness_is_truthful_bounded_and_secret_free():
    disabled = discord_media.media_readiness(media_enabled=False)
    unverified = discord_media.media_readiness(media_enabled=True)
    ready = discord_media.media_readiness(
        media_enabled=True,
        server_status="ready",
        local_vision_status="ready",
    )

    assert disabled["ready"] is False
    assert disabled["receive"]["image"]["status"] == "disabled"
    assert disabled["send"]["image"]["status"] == "disabled"
    assert unverified["receive"]["image"]["status"] == "unverified"
    assert ready["ready"] is True
    assert ready["receive"]["image"] == {
        "status": "ready",
        "max_bytes": discord_media.INBOUND_MAX_BYTES,
        "mime_types": ["image/gif", "image/jpeg", "image/png"],
        "processing": "verified-local-only",
        "cloud_egress": "denied",
    }
    serialized = json.dumps(ready, sort_keys=True).casefold()
    assert all(
        forbidden not in serialized
        for forbidden in ("token", "secret", "authorization", "endpoint", "path")
    )
    assert ready["receive"]["file"] == {"status": "disabled"}
    assert ready["receive"]["audio"] == {"status": "disabled"}
    assert ready["send"]["file"] == {"status": "disabled"}
    assert ready["send"]["audio"] == {"status": "disabled"}


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    (
        ("photo.png", "application/octet-stream", "image"),
        ("voice.ogg", "application/octet-stream", "audio"),
        ("notes.pdf", "application/pdf", "file"),
    ),
)
def test_attachment_metadata_classification_never_claims_file_or_audio_support(
    filename: str,
    content_type: str,
    expected: str,
):
    assert discord_media.attachment_media_kind(filename, content_type) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("send me an audio recording", "audio"),
        ("!audio voice-note", "audio"),
        ("attach that PDF document", "file"),
        ("!file report", "file"),
        ("tell me about audio", None),
    ),
)
def test_disabled_outbound_payload_requests_are_explicit_only(
    text: str,
    expected: str | None,
):
    assert discord_media.requested_disabled_media_kind(text) == expected


def test_image_backend_requires_verified_local_perception_metadata(monkeypatch):
    calls = 0

    def fake_post(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"envelope": "signed-actor-envelope"}
        return {
            "reply": "I can definitely see private details.",
            "perception": {"status": "vision-unavailable"},
        }

    monkeypatch.setattr(discord_bridge, "_post_json_once", fake_post)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "_SERVER_MEDIA_STATUS", "unknown")
    monkeypatch.setattr(discord_bridge, "_LOCAL_VISION_STATUS", "unknown")

    with pytest.raises(discord_bridge.DiscordMediaUnavailable) as caught:
        discord_bridge._ask_alpecca(
            "inspect this",
            "Discord guest",
            "discord-dm",
            image="data:image/png;base64,AAAA",
            actor_bindings=DiscordActorBindings(
                event_id="1001",
                actor_id="42",
                channel_id="3001",
            ),
        )

    assert caught.value.reason == "vision-unavailable"
    assert "private details" not in str(caught.value)
    assert discord_bridge.media_readiness()["receive"]["image"]["status"] == (
        "vision-unavailable"
    )


def test_server_media_disablement_maps_only_the_exact_fixed_error(monkeypatch):
    calls = 0

    def fake_post(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"envelope": "signed-actor-envelope"}
        raise discord_bridge._BackendRequestRejected(
            403,
            error_code="capability_disabled",
            capability="discord_media",
        )

    monkeypatch.setattr(discord_bridge, "_post_json_once", fake_post)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "_SERVER_MEDIA_STATUS", "unknown")
    monkeypatch.setattr(discord_bridge, "_LOCAL_VISION_STATUS", "unknown")

    with pytest.raises(discord_bridge.DiscordMediaUnavailable) as caught:
        discord_bridge._ask_alpecca(
            "inspect this",
            "Discord guest",
            "discord-dm",
            image="data:image/png;base64,AAAA",
            actor_bindings=DiscordActorBindings(
                event_id="1001",
                actor_id="42",
                channel_id="3001",
            ),
        )

    assert caught.value.reason == "media-disabled"
    assert discord_bridge.media_readiness()["receive"]["image"]["status"] == (
        "disabled"
    )
