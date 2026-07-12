"""Focused adversarial coverage for pure Phase 9 trusted file ingress."""
from __future__ import annotations

from contextlib import contextmanager
import dataclasses
import hashlib
import inspect
import json
from pathlib import Path
import struct

import pytest

from alpecca import file_ingress as ingress_mod
from alpecca.file_ingress import (
    MAX_TEXT_EXCERPT_CHARS,
    MAX_TEXT_FILE_BYTES,
    FileIngressRejected,
    ingest_file,
    ingest_text_file,
)
from alpecca.source_perception import SourceInspection, SourceProvenance


ROOT_ID = "workspace"
SCOPE = "creator-private"


def _roots(root: Path) -> dict[str, Path]:
    return {ROOT_ID: root}


def _ingest(root: Path, relative_path: str | Path, **overrides):
    values = {
        "allowed_roots": _roots(root),
        "scope": SCOPE,
    }
    values.update(overrides)
    return ingest_file(ROOT_ID, relative_path, **values)


@contextmanager
def _rejected(reason: str):
    with pytest.raises(FileIngressRejected) as caught:
        yield caught
    assert caught.value.reason == reason


def _png(width: int = 3, height: int = 2) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )


def _wav() -> bytes:
    channels = 1
    sample_rate = 8_000
    bits_per_sample = 16
    block_align = channels * bits_per_sample // 8
    byte_rate = sample_rate * block_align
    fmt = struct.pack(
        "<HHIIHH",
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
    )
    samples = b"\x00" * 160
    body = (
        b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", len(samples)) + samples
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


@pytest.mark.parametrize(
    ("relative_path", "payload", "mime_type", "encoding", "text"),
    (
        ("notes/status.txt", b"plain local note\n", "text/plain", "utf-8", "plain local note\n"),
        ("README.md", b"# Local status\n", "text/markdown", "utf-8", "# Local status\n"),
        ("worker.py", b"def run():\n    return 1\n", "text/x-python", "utf-8", "def run():\n    return 1\n"),
        ("config.json", b'{"enabled": true}\n', "application/json", "utf-8", '{"enabled": true}\n'),
        ("wide.txt", "local unicode text\n".encode("utf-16"), "text/plain", "utf-16", "local unicode text\n"),
    ),
)
def test_text_code_and_markdown_are_locally_derived_and_enveloped(
    tmp_path, relative_path, payload, mime_type, encoding, text
):
    root = tmp_path / "allowed"
    root.mkdir()
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    result = _ingest(root, relative_path)

    digest = hashlib.sha256(payload).hexdigest()
    assert result.excerpt == text
    assert result.excerpt_truncated is False
    assert result.encoding == encoding
    assert result.mime_type == mime_type
    assert result.sha256 == digest
    assert result.size_bytes == len(payload)
    assert result.scope == SCOPE
    assert result.source == f"{ROOT_ID}:{relative_path}"
    assert result.provenance == SourceProvenance(
        ROOT_ID,
        relative_path,
        len(payload),
        digest,
    )
    assert result.envelope.attachment_type == "text"
    assert result.envelope.processing_location == "local-only"
    assert result.envelope.cloud_egress == "denied"


def test_excerpt_and_serialization_are_bounded_and_never_retain_raw_bytes(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    payload = b"visible-prefix|private-tail-that-must-not-be-returned"
    (root / "note.txt").write_bytes(payload)

    result = _ingest(root, "note.txt", max_excerpt_chars=14)
    serialized = json.dumps(result.as_dict(), sort_keys=True)
    provenance = json.dumps(result.provenance_dict(), sort_keys=True)

    assert result.excerpt == payload.decode("utf-8")[:14]
    assert result.excerpt_truncated is True
    assert "excerpt" not in result.as_dict()
    assert "private-tail-that-must-not-be-returned" not in serialized
    assert "excerpt" not in provenance
    assert str(root) not in serialized
    assert result.as_dict()["source"] == {
        "root_id": ROOT_ID,
        "relative_path": "note.txt",
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    assert result.as_dict()["envelope"] == result.envelope.as_dict()
    assert all(
        not isinstance(getattr(result, field.name), bytes)
        for field in dataclasses.fields(result)
    )
    assert not hasattr(result, "file_bytes")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.excerpt = "changed"  # type: ignore[misc]


def test_api_accepts_no_caller_hash_mime_source_scope_set_or_egress_override(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "note.txt").write_text("local", encoding="utf-8")
    parameters = inspect.signature(ingest_file).parameters

    assert ingest_text_file is ingest_file
    assert {
        "sha256",
        "mime_type",
        "source",
        "authorized_scopes",
        "processing_location",
        "cloud_egress",
        "file_bytes",
    }.isdisjoint(parameters)
    with pytest.raises(TypeError, match="unexpected keyword argument 'sha256'"):
        ingest_file(
            ROOT_ID,
            "note.txt",
            allowed_roots=_roots(root),
            scope=SCOPE,
            sha256="0" * 64,  # type: ignore[call-arg]
        )
    with _rejected("invalid-scope"):
        _ingest(root, "note.txt", scope="*")


def test_adapter_delegates_the_only_inspection_to_source_perception(monkeypatch):
    digest = hashlib.sha256(b"derived elsewhere").hexdigest()
    calls: list[tuple[object, ...]] = []

    def inspected(root_id, relative_path, **kwargs):
        calls.append((root_id, relative_path, kwargs))
        return SourceInspection(
            ok=True,
            status="ok",
            reason="text-excerpt",
            mime_type="text/markdown",
            provenance=SourceProvenance(
                ROOT_ID,
                "notes/delegated.md",
                17,
                digest,
            ),
            encoding="utf-8",
            excerpt="# delegated\n",
        )

    monkeypatch.setattr(ingress_mod, "inspect_local_source", inspected)

    result = ingest_file(
        ROOT_ID,
        "notes/delegated.md",
        allowed_roots={ROOT_ID: Path("server-owned-root")},
        scope=SCOPE,
        max_bytes=99,
        max_excerpt_chars=5,
    )

    assert len(calls) == 1
    root_id, relative_path, kwargs = calls[0]
    assert (root_id, relative_path) == (ROOT_ID, "notes/delegated.md")
    assert kwargs["allowed_roots"] == {ROOT_ID: Path("server-owned-root")}
    assert kwargs["max_bytes"] == 99
    assert kwargs["max_excerpt_chars"] <= MAX_TEXT_EXCERPT_CHARS
    assert result.excerpt == "# del"
    assert result.excerpt_truncated is True
    assert result.sha256 == digest
    assert result.mime_type == "text/markdown"


def test_unknown_root_absolute_path_and_traversal_fail_closed(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    with _rejected("root-not-allowed"):
        ingest_file(
            "other",
            "outside.txt",
            allowed_roots=_roots(root),
            scope=SCOPE,
        )
    with _rejected("path-not-relative"):
        _ingest(root, outside)
    with _rejected("traversal"):
        _ingest(root, "../outside.txt")


def test_symlink_file_and_symlink_directory_components_are_rejected(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    file_link = root / "file-link.txt"
    directory_link = root / "directory-link"
    try:
        file_link.symlink_to(outside / "secret.txt")
        directory_link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable in this test environment")

    with _rejected("symlink-not-allowed"):
        _ingest(root, "file-link.txt")
    with _rejected("symlink-not-allowed"):
        _ingest(root, "directory-link/secret.txt")


@pytest.mark.parametrize(
    ("name", "payload", "reason"),
    (
        ("binary.bin", b"\x00\x01binary", "binary"),
        ("controls.txt", b"text\x01binary", "binary"),
        ("report.pdf", b"%PDF-1.7\nnot admitted", "unsupported-mime"),
        ("disguised-pdf.txt", b"%PDF-1.7\nnot admitted", "unsupported-mime"),
        ("disguised-image.txt", _png(), "unsupported-mime"),
        ("disguised-audio.txt", _wav(), "unsupported-mime"),
        ("disguised-svg.txt", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "unsupported-mime"),
        ("disguised-mp3.txt", b"ID3audio container", "unsupported-mime"),
    ),
)
def test_binary_pdf_image_and_audio_files_are_rejected(tmp_path, name, payload, reason):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / name).write_bytes(payload)

    with _rejected(reason):
        _ingest(root, name, max_excerpt_chars=1)


def test_size_cap_is_hard_and_empty_files_cannot_create_false_provenance(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "large.txt").write_bytes(b"x" * 33)
    (root / "empty.txt").write_bytes(b"")

    with _rejected("size-limit"):
        _ingest(root, "large.txt", max_bytes=32)
    with _rejected("invalid-size"):
        _ingest(root, "empty.txt")
    with pytest.raises(ValueError, match="max_bytes must be a positive integer"):
        _ingest(root, "large.txt", max_bytes=0)
    with pytest.raises(ValueError, match="max_excerpt_chars must be a positive integer"):
        _ingest(root, "large.txt", max_excerpt_chars=True)


def test_requested_limits_can_tighten_but_never_raise_the_hard_caps(monkeypatch):
    seen: list[dict[str, object]] = []

    def oversized(_root_id, _relative_path, **kwargs):
        seen.append(kwargs)
        return SourceInspection(
            ok=False,
            status="too-large",
            reason="file-size-cap",
            mime_type="",
            provenance=SourceProvenance(ROOT_ID, "large.txt", MAX_TEXT_FILE_BYTES + 1),
        )

    monkeypatch.setattr(ingress_mod, "inspect_local_source", oversized)

    with _rejected("size-limit"):
        ingest_file(
            ROOT_ID,
            "large.txt",
            allowed_roots={ROOT_ID: Path("server-owned-root")},
            scope=SCOPE,
            max_bytes=MAX_TEXT_FILE_BYTES + 1,
            max_excerpt_chars=MAX_TEXT_EXCERPT_CHARS + 1,
        )

    assert seen == [{
        "allowed_roots": {ROOT_ID: Path("server-owned-root")},
        "max_bytes": MAX_TEXT_FILE_BYTES,
        "max_excerpt_chars": MAX_TEXT_EXCERPT_CHARS,
    }]
