"""Focused contract tests for Discord's approved Alpecca self portrait."""
from __future__ import annotations

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


def test_self_portrait_resolver_has_one_fixed_local_catalog_entry(
    monkeypatch,
    tmp_path: Path,
):
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
    avatar_dir = tmp_path / "avatar"
    monkeypatch.setattr(discord_media, "AVATAR_DIR", avatar_dir)

    assert discord_media.resolve_self_portrait() is None

    portrait = avatar_dir / "portraits" / "idle.png"
    portrait.parent.mkdir(parents=True)
    portrait.write_bytes(b"not an image")
    assert discord_media.resolve_self_portrait() is None
