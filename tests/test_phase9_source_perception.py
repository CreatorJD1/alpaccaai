"""Focused local-only tests for Phase 9 source perception groundwork."""
from __future__ import annotations

import hashlib
import struct

import pytest

from alpecca.source_perception import inspect_local_source


def _roots(root):
    return {"workspace": root}


def _wav_payload(*, sample_rate: int, channels: int, duration: float) -> bytes:
    bits_per_sample = 16
    block_align = channels * (bits_per_sample // 8)
    byte_rate = sample_rate * block_align
    sample_data = b"\x00" * int(byte_rate * duration)
    fmt = struct.pack(
        "<HHIIHH", 1, channels, sample_rate, byte_rate, block_align, bits_per_sample
    )
    junk = b"JUNK" + struct.pack("<I", 3) + b"abc" + b"\x00"
    chunks = (
        junk
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", len(sample_data)) + sample_data
    )
    body = b"WAVE" + chunks
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_text_excerpt_mime_and_sha256_provenance_stay_under_allowed_root(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    source = root / "notes" / "status.md"
    source.parent.mkdir()
    payload = "# Status\nAll work is local.\n"
    source.write_text(payload, encoding="utf-8")

    result = inspect_local_source(
        "workspace", "notes/status.md", allowed_roots=_roots(root), max_excerpt_chars=12
    )

    assert result.ok is True
    assert result.status == "ok"
    assert result.mime_type == "text/markdown"
    assert result.encoding == "utf-8"
    assert result.excerpt == payload[:12]
    assert result.excerpt_truncated is True
    assert result.provenance.root_id == "workspace"
    assert result.provenance.relative_path == "notes/status.md"
    assert result.provenance.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()


def test_traversal_and_symlink_escape_are_rejected_inside_temp_roots(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    traversal = inspect_local_source("workspace", "../outside.txt", allowed_roots=_roots(root))

    assert traversal.ok is False
    assert traversal.status == "rejected"
    assert traversal.reason == "traversal"
    assert traversal.provenance.sha256 == ""

    link = root / "escaped-link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable in this test environment")
    escaped = inspect_local_source("workspace", "escaped-link.txt", allowed_roots=_roots(root))

    assert escaped.ok is False
    assert escaped.status == "rejected"
    assert escaped.reason == "symlink-not-allowed"


def test_binary_unsupported_and_size_capped_files_have_safe_outcomes(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "payload.bin").write_bytes(b"\x00\x01binary")
    (root / "document.pdf").write_bytes(b"%PDF-1.7\nnot parsed")
    (root / "large.txt").write_text("x" * 33, encoding="utf-8")

    binary = inspect_local_source("workspace", "payload.bin", allowed_roots=_roots(root))
    unsupported = inspect_local_source("workspace", "document.pdf", allowed_roots=_roots(root))
    too_large = inspect_local_source(
        "workspace", "large.txt", allowed_roots=_roots(root), max_bytes=32
    )

    assert (binary.ok, binary.status, binary.excerpt) == (False, "binary", "")
    assert binary.provenance.sha256
    assert (unsupported.ok, unsupported.status, unsupported.mime_type) == (
        False, "unsupported", "application/pdf"
    )
    assert unsupported.provenance.sha256
    assert (too_large.ok, too_large.status, too_large.provenance.sha256) == (
        False, "too-large", ""
    )


def test_png_returns_header_metadata_without_text_content(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    png = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (3).to_bytes(4, "big")
        + (2).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    (root / "preview.dat").write_bytes(png)

    result = inspect_local_source("workspace", "preview.dat", allowed_roots=_roots(root))

    assert result.ok is True
    assert result.reason == "image-metadata-only"
    assert result.mime_type == "image/png"
    assert dict(result.image_metadata) == {"format": "png", "height": 2, "width": 3}
    assert result.excerpt == ""
    assert result.encoding == ""


@pytest.mark.parametrize(
    ("sample_rate", "channels", "duration"),
    [(8_000, 1, 0.125), (48_000, 2, 0.025)],
)
def test_wav_header_returns_bounded_audio_metadata_only(
    tmp_path, sample_rate, channels, duration
):
    root = tmp_path / "allowed"
    root.mkdir()
    payload = _wav_payload(
        sample_rate=sample_rate, channels=channels, duration=duration
    )
    (root / "recording.dat").write_bytes(payload)

    result = inspect_local_source(
        "workspace", "recording.dat", allowed_roots=_roots(root)
    )

    assert result.ok is True
    assert result.status == "ok"
    assert result.reason == "audio-metadata-only"
    assert result.mime_type == "audio/wav"
    assert dict(result.audio_metadata) == {
        "channels": channels,
        "duration_seconds": duration,
        "format": "wav",
        "sample_rate_hz": sample_rate,
    }
    assert result.excerpt == ""
    assert result.encoding == ""
    assert dict(result.image_metadata) == {}
    assert result.provenance.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.as_dict()["audio_metadata"] == dict(result.audio_metadata)


def test_truncated_wav_header_does_not_fabricate_audio_metadata(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    truncated = (
        b"RIFF" + struct.pack("<I", 1_000) + b"WAVE"
        + b"fmt " + struct.pack("<I", 16) + b"\x00" * 16
    )
    (root / "truncated.wav").write_bytes(truncated)

    result = inspect_local_source(
        "workspace", "truncated.wav", allowed_roots=_roots(root)
    )

    assert result.ok is False
    assert result.status == "binary"
    assert result.reason == "nul-byte-detected"
    assert dict(result.audio_metadata) == {}
    assert result.excerpt == ""


def test_unknown_roots_and_invalid_limits_fail_without_reading(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "note.txt").write_text("hello", encoding="utf-8")

    unknown = inspect_local_source("other", "note.txt", allowed_roots=_roots(root))

    assert (unknown.ok, unknown.reason) == (False, "root-not-allowed")
    with pytest.raises(ValueError, match="max_bytes must be a positive integer"):
        inspect_local_source("workspace", "note.txt", allowed_roots=_roots(root), max_bytes=0)
