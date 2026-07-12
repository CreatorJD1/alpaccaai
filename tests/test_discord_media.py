"""Focused coverage for bounded Discord image ingress and egress."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from alpecca import discord_bridge
from alpecca import discord_media
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

        def read(self):
            return b'{"reply":"I can see it."}'

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(discord_bridge.urllib.request, "urlopen", fake_urlopen)

    reply = discord_bridge._ask_alpecca(
        "Who is this?",
        "CreatorJD",
        "discord-dm",
        speaker="creator",
        image="data:image/png;base64,AAAA",
    )

    assert reply == "I can see it."
    request, timeout = calls[0]
    body = json.loads(request.data)
    assert request.full_url.endswith("/channel/discord")
    assert body["image"] == "data:image/png;base64,AAAA"
    assert "file_name" not in body
    assert "file_data" not in body
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
