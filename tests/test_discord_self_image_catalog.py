"""Focused contract tests for Discord's approved Alpecca self portrait."""
from __future__ import annotations

import hashlib
from pathlib import Path

from alpecca import discord_media


def _png(width: int = 3, height: int = 2) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def _approve_fixture_catalog(monkeypatch) -> None:
    digest = hashlib.sha256(_png()).hexdigest()
    monkeypatch.setattr(
        discord_media,
        "APPROVED_SELF_IMAGE_SHA256",
        {kind: digest for kind in discord_media.APPROVED_SELF_IMAGE_KINDS},
    )


def test_self_portrait_resolver_has_one_fixed_local_catalog_entry(
    monkeypatch,
    tmp_path: Path,
):
    _approve_fixture_catalog(monkeypatch)
    avatar_dir = tmp_path / "avatar"
    portrait = avatar_dir / "portraits" / "idle.png"
    portrait.parent.mkdir(parents=True)
    portrait.write_bytes(_png())
    (portrait.parent / "unapproved.png").write_bytes(_png(4, 4))
    monkeypatch.setattr(discord_media, "AVATAR_DIR", avatar_dir)

    resolved = discord_media.resolve_self_portrait()

    assert resolved is not None
    assert resolved.kind == "portrait"
    assert resolved.filename == "alpecca-portrait.png"
    assert resolved.mime_type == "image/png"
    assert resolved.size_bytes == len(_png())
    assert resolved.image_bytes == _png()
    assert len(resolved.sha256) == 64


def test_self_portrait_resolver_fails_closed_when_approved_asset_is_missing_or_invalid(
    monkeypatch,
    tmp_path: Path,
):
    _approve_fixture_catalog(monkeypatch)
    avatar_dir = tmp_path / "avatar"
    monkeypatch.setattr(discord_media, "AVATAR_DIR", avatar_dir)

    assert discord_media.resolve_self_portrait() is None

    portrait = avatar_dir / "portraits" / "idle.png"
    portrait.parent.mkdir(parents=True)
    portrait.write_bytes(b"not an image")
    assert discord_media.resolve_self_portrait() is None


def test_catalog_allows_only_named_approved_alpecca_variants(monkeypatch, tmp_path: Path):
    _approve_fixture_catalog(monkeypatch)
    avatar_dir = tmp_path / "avatar"
    character_dir = tmp_path / "character"
    portraits = avatar_dir / "portraits"
    reference = character_dir / "reference"
    portraits.mkdir(parents=True)
    reference.mkdir(parents=True)
    (portraits / "thinking.png").write_bytes(_png())
    (portraits / "speaking.png").write_bytes(_png())
    (avatar_dir / "poses").mkdir(parents=True)
    (avatar_dir / "poses" / "reach.png").write_bytes(_png())
    (reference / "poses").mkdir(parents=True)
    (reference / "poses" / "pose-5.png").write_bytes(_png())
    (reference / "poses" / "pose-6.png").write_bytes(_png())
    (reference / "unapproved.png").write_bytes(_png())
    monkeypatch.setattr(discord_media, "AVATAR_DIR", avatar_dir)
    monkeypatch.setattr(discord_media, "CHARACTER_DIR", character_dir)

    assert discord_media.requested_media_kind("!image thinking") == "thinking"
    assert discord_media.requested_media_kind("!image focused") == "thinking"
    assert discord_media.requested_media_kind("!image active") == "speaking"
    assert discord_media.requested_media_kind("Alpecca, show your speaking picture") == "speaking"
    assert discord_media.requested_media_kind("Alpecca, show your focused pose") == "thinking"
    assert discord_media.requested_media_kind("Alpecca, show another image of yourself") == "reach"
    assert discord_media.requested_media_kind("Please share an outfit image") == "rear"
    assert discord_media.requested_media_kind("!image unapproved") is None
    assert discord_media.resolve_outbound_media(
        "!image thinking", avatar_dir=avatar_dir, character_dir=character_dir,
    ) is not None
    assert discord_media.resolve_outbound_media(
        "!image active", avatar_dir=avatar_dir, character_dir=character_dir,
    ) is not None
    assert discord_media.resolve_outbound_media(
        "!image gallery", avatar_dir=avatar_dir, character_dir=character_dir,
    ) is not None
    assert discord_media.resolve_outbound_media(
        "!image wardrobe", avatar_dir=avatar_dir, character_dir=character_dir,
    ) is not None


def test_runtime_catalog_matches_the_immutable_manifest() -> None:
    assert discord_media.APPROVED_SELF_IMAGE_KINDS == (
        "portrait", "speaking", "thinking", "reach", "rest", "shy",
        "confirmation", "sleeping", "running", "balance", "ready", "rear",
    )
    assert set(discord_media.APPROVED_SELF_IMAGE_SHA256) == set(
        discord_media.APPROVED_SELF_IMAGE_KINDS
    )
    assert len(set(discord_media.APPROVED_SELF_IMAGE_SHA256.values())) == 12
    assert discord_media.OUTBOUND_MAX_BYTES == 2 * 1024 * 1024


def test_catalog_reader_is_bounded_before_image_inspection(monkeypatch, tmp_path: Path) -> None:
    _approve_fixture_catalog(monkeypatch)
    avatar_dir = tmp_path / "avatar"
    character_dir = tmp_path / "character"
    portrait = avatar_dir / "portraits" / "idle.png"
    portrait.parent.mkdir(parents=True)
    portrait.write_bytes(_png())

    def forbidden_read_bytes(_path: Path) -> bytes:
        raise AssertionError("outbound catalog must not use unbounded Path.read_bytes")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    assert discord_media.resolve_outbound_media(
        "send your portrait", avatar_dir=avatar_dir, character_dir=character_dir,
    ) is not None

    portrait.write_bytes(_png() + b"x" * discord_media.OUTBOUND_MAX_BYTES)
    assert discord_media.resolve_outbound_media(
        "send your portrait", avatar_dir=avatar_dir, character_dir=character_dir,
    ) is None
