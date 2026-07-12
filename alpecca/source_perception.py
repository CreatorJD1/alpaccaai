"""Bounded, local-only inspection of files beneath explicit allowed roots."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import mimetypes
from pathlib import Path
import struct
from typing import Literal, Mapping


MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_EXCERPT_CHARS = 4_000
MAX_WAV_HEADER_BYTES = 64 * 1024
MAX_WAV_CHUNKS = 64

_TEXT_MIME_BY_SUFFIX = {
    ".cfg": "text/plain",
    ".conf": "text/plain",
    ".csv": "text/csv",
    ".css": "text/css",
    ".html": "text/html",
    ".ini": "text/plain",
    ".js": "text/javascript",
    ".json": "application/json",
    ".log": "text/plain",
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".toml": "application/toml",
    ".ts": "text/typescript",
    ".txt": "text/plain",
    ".xml": "application/xml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}
_TEXT_APPLICATION_MIMES = frozenset({
    "application/json",
    "application/toml",
    "application/xml",
    "application/yaml",
    "text/typescript",
})


ImageMimeType = Literal["image/png", "image/jpeg", "image/gif"]


@dataclass(frozen=True, slots=True)
class ImageHeader:
    """Bounded header facts for a supported image without retaining pixels."""

    mime_type: ImageMimeType
    width: int | None
    height: int | None


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    root_id: str
    relative_path: str
    size_bytes: int | None
    sha256: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "root_id": self.root_id,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class SourceInspection:
    """A local observation; no source bytes are retained for image results."""

    ok: bool
    status: str
    reason: str
    mime_type: str
    provenance: SourceProvenance
    encoding: str = ""
    excerpt: str = ""
    excerpt_truncated: bool = False
    image_metadata: tuple[tuple[str, int | float | str], ...] = ()
    audio_metadata: tuple[tuple[str, int | float | str], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status,
            "reason": self.reason,
            "mime_type": self.mime_type,
            "provenance": self.provenance.as_dict(),
            "encoding": self.encoding,
            "excerpt": self.excerpt,
            "excerpt_truncated": self.excerpt_truncated,
            "image_metadata": dict(self.image_metadata),
            "audio_metadata": dict(self.audio_metadata),
        }


def _bounded_limit(value: int, maximum: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return min(value, maximum)


def _relative_text(value: str | Path) -> str:
    return str(value).replace("\\", "/")[:512]


def _result(
    *,
    ok: bool,
    status: str,
    reason: str,
    root_id: str,
    relative_path: str,
    size_bytes: int | None = None,
    sha256: str = "",
    mime_type: str = "",
    encoding: str = "",
    excerpt: str = "",
    excerpt_truncated: bool = False,
    image_metadata: Mapping[str, int | float | str] | None = None,
    audio_metadata: Mapping[str, int | float | str] | None = None,
) -> SourceInspection:
    return SourceInspection(
        ok=ok,
        status=status,
        reason=reason,
        mime_type=mime_type,
        provenance=SourceProvenance(root_id, relative_path, size_bytes, sha256),
        encoding=encoding,
        excerpt=excerpt,
        excerpt_truncated=excerpt_truncated,
        image_metadata=tuple(sorted((image_metadata or {}).items())),
        audio_metadata=tuple(sorted((audio_metadata or {}).items())),
    )


def _resolve_target(
    root_id: str,
    relative_path: str | Path,
    allowed_roots: Mapping[str, Path],
) -> tuple[Path | None, SourceInspection | None]:
    relative_text = _relative_text(relative_path)
    root = allowed_roots.get(root_id)
    if root is None:
        return None, _result(
            ok=False, status="rejected", reason="root-not-allowed",
            root_id=root_id, relative_path=relative_text,
        )
    try:
        base = Path(root).resolve(strict=True)
    except (OSError, RuntimeError):
        return None, _result(
            ok=False, status="rejected", reason="root-unavailable",
            root_id=root_id, relative_path=relative_text,
        )
    if not base.is_dir():
        return None, _result(
            ok=False, status="rejected", reason="root-not-directory",
            root_id=root_id, relative_path=relative_text,
        )
    try:
        requested = Path(relative_path)
    except (TypeError, ValueError):
        return None, _result(
            ok=False, status="rejected", reason="invalid-path",
            root_id=root_id, relative_path=relative_text,
        )
    if not requested.parts or requested.is_absolute() or requested.drive:
        return None, _result(
            ok=False, status="rejected", reason="path-not-relative",
            root_id=root_id, relative_path=relative_text,
        )
    if any(part == ".." for part in requested.parts):
        return None, _result(
            ok=False, status="rejected", reason="traversal",
            root_id=root_id, relative_path=relative_text,
        )
    unresolved = base
    try:
        for part in requested.parts:
            unresolved = unresolved / part
            if unresolved.is_symlink():
                return None, _result(
                    ok=False, status="rejected", reason="symlink-not-allowed",
                    root_id=root_id, relative_path=relative_text,
                )
        target = unresolved.resolve(strict=False)
        target.relative_to(base)
    except (OSError, RuntimeError, ValueError):
        return None, _result(
            ok=False, status="rejected", reason="path-escape",
            root_id=root_id, relative_path=relative_text,
        )
    return target, None


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return _TEXT_MIME_BY_SUFFIX.get(suffix) or mimetypes.guess_type(path.name)[0] or ""


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SOF_MARKERS = frozenset({
    0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
    0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
})


def _jpeg_dimensions(data: bytes) -> tuple[int | None, int | None]:
    """Read a JPEG SOF segment without decoding compressed image data."""

    index = 2
    while index < len(data):
        while index < len(data) and data[index] != 0xFF:
            index += 1
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            return None, None
        marker = data[index]
        index += 1
        if marker in {0x00, 0x01, 0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            return None, None
        segment_length = struct.unpack(">H", data[index:index + 2])[0]
        if segment_length < 2 or index + segment_length > len(data):
            return None, None
        if marker in _JPEG_SOF_MARKERS:
            if segment_length < 8:
                return None, None
            height, width = struct.unpack(">HH", data[index + 3:index + 7])
            return width, height
        index += segment_length
    return None, None


def parse_image_header(data: bytes) -> ImageHeader | None:
    """Return supported image MIME and dimensions from bytes already in memory.

    This parser does not decode pixels, open paths, write files, call models, or
    perform network I/O. A recognized but incomplete image returns its MIME with
    missing dimensions so callers can reject it without guessing.
    """

    if not isinstance(data, bytes):
        return None
    if data.startswith(_PNG_SIGNATURE):
        if (
            len(data) < 24
            or data[8:12] != b"\x00\x00\x00\r"
            or data[12:16] != b"IHDR"
        ):
            return ImageHeader("image/png", None, None)
        width, height = struct.unpack(">II", data[16:24])
        return ImageHeader("image/png", width, height)
    if data.startswith((b"GIF87a", b"GIF89a")):
        if len(data) < 10:
            return ImageHeader("image/gif", None, None)
        width, height = struct.unpack("<HH", data[6:10])
        return ImageHeader("image/gif", width, height)
    if data.startswith(b"\xff\xd8"):
        width, height = _jpeg_dimensions(data)
        return ImageHeader("image/jpeg", width, height)
    return None


def _image_metadata(data: bytes) -> tuple[str, dict[str, int | str]] | None:
    header = parse_image_header(data)
    if header is None:
        return None
    if header.width is None or header.height is None:
        # Preserve the legacy source-inspection result for a recognizable but
        # incomplete JPEG. The stricter ingress guard rejects it separately.
        if header.mime_type == "image/jpeg":
            return "image/jpeg", {"format": "jpeg"}
        return None
    return header.mime_type, {
        "format": header.mime_type.split("/", 1)[1],
        "width": header.width,
        "height": header.height,
    }


def _wav_metadata(data: bytes) -> dict[str, int | float | str] | None:
    """Parse bounded RIFF/WAVE metadata without decoding sample data."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    riff_size = struct.unpack("<I", data[4:8])[0]
    declared_end = 8 + riff_size
    if declared_end < 12 or declared_end > len(data):
        return None

    scan_end = min(declared_end, len(data), MAX_WAV_HEADER_BYTES)
    index = 12
    chunk_count = 0
    format_fields: tuple[int, int, int, int, int, int] | None = None
    sample_bytes: int | None = None
    while index + 8 <= scan_end and chunk_count < MAX_WAV_CHUNKS:
        chunk_count += 1
        chunk_id = data[index:index + 4]
        chunk_size = struct.unpack("<I", data[index + 4:index + 8])[0]
        payload_start = index + 8
        payload_end = payload_start + chunk_size
        if payload_end > declared_end or payload_end > len(data):
            return None
        if chunk_id == b"fmt ":
            if chunk_size < 16 or payload_start + 16 > scan_end:
                return None
            format_fields = struct.unpack("<HHIIHH", data[payload_start:payload_start + 16])
        elif chunk_id == b"data":
            sample_bytes = chunk_size
        if format_fields is not None and sample_bytes is not None:
            break
        next_index = payload_end + (chunk_size & 1)
        if next_index <= index or next_index > declared_end:
            return None
        index = next_index

    if format_fields is None or sample_bytes is None:
        return None
    _audio_format, channels, sample_rate, byte_rate, block_align, _bits = format_fields
    if channels <= 0 or sample_rate <= 0 or byte_rate <= 0 or block_align <= 0:
        return None
    return {
        "format": "wav",
        "duration_seconds": round(sample_bytes / byte_rate, 6),
        "sample_rate_hz": sample_rate,
        "channels": channels,
    }


def _decode_text(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            text = data.decode("utf-16")
            return text.replace("\r\n", "\n").replace("\r", "\n"), "utf-16"
        except UnicodeDecodeError:
            return None
    try:
        text = data.decode("utf-8-sig")
        return text.replace("\r\n", "\n").replace("\r", "\n"), "utf-8"
    except UnicodeDecodeError:
        return None


def inspect_local_source(
    root_id: str,
    relative_path: str | Path,
    *,
    allowed_roots: Mapping[str, Path],
    max_bytes: int = MAX_FILE_BYTES,
    max_excerpt_chars: int = MAX_EXCERPT_CHARS,
) -> SourceInspection:
    """Inspect one local file beneath an explicitly named allowed root.

    The function performs no network, cloud, model, or write operation. Image
    results retain only parsed header metadata; text results retain a bounded
    excerpt and provenance hash.
    """

    file_limit = _bounded_limit(max_bytes, MAX_FILE_BYTES, "max_bytes")
    excerpt_limit = _bounded_limit(max_excerpt_chars, MAX_EXCERPT_CHARS, "max_excerpt_chars")
    root_name = str(root_id or "").strip()[:160]
    target, rejected = _resolve_target(root_name, relative_path, allowed_roots)
    if rejected is not None:
        return rejected
    assert target is not None
    relative_text = _relative_text(relative_path)
    try:
        stat = target.stat()
    except FileNotFoundError:
        return _result(
            ok=False, status="missing", reason="file-not-found",
            root_id=root_name, relative_path=relative_text,
        )
    except OSError:
        return _result(
            ok=False, status="unreadable", reason="stat-failed",
            root_id=root_name, relative_path=relative_text,
        )
    if not target.is_file():
        return _result(
            ok=False, status="unsupported", reason="not-a-regular-file",
            root_id=root_name, relative_path=relative_text,
        )
    size = int(stat.st_size)
    if size > file_limit:
        return _result(
            ok=False, status="too-large", reason="file-size-cap",
            root_id=root_name, relative_path=relative_text, size_bytes=size,
        )
    try:
        with target.open("rb") as handle:
            data = handle.read(file_limit + 1)
    except OSError:
        return _result(
            ok=False, status="unreadable", reason="read-failed",
            root_id=root_name, relative_path=relative_text, size_bytes=size,
        )
    if len(data) > file_limit:
        return _result(
            ok=False, status="too-large", reason="file-size-cap",
            root_id=root_name, relative_path=relative_text, size_bytes=len(data),
        )
    sha256 = hashlib.sha256(data).hexdigest()
    image = _image_metadata(data)
    if image is not None:
        mime_type, metadata = image
        return _result(
            ok=True, status="ok", reason="image-metadata-only",
            root_id=root_name, relative_path=relative_text, size_bytes=len(data),
            sha256=sha256, mime_type=mime_type, image_metadata=metadata,
        )
    audio = _wav_metadata(data)
    if audio is not None:
        return _result(
            ok=True, status="ok", reason="audio-metadata-only",
            root_id=root_name, relative_path=relative_text, size_bytes=len(data),
            sha256=sha256, mime_type="audio/wav", audio_metadata=audio,
        )
    mime_type = _mime_type(target)
    if b"\x00" in data and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return _result(
            ok=False, status="binary", reason="nul-byte-detected",
            root_id=root_name, relative_path=relative_text, size_bytes=len(data),
            sha256=sha256, mime_type=mime_type or "application/octet-stream",
        )
    known_text = mime_type.startswith("text/") or mime_type in _TEXT_APPLICATION_MIMES
    if not known_text and mime_type:
        return _result(
            ok=False, status="unsupported", reason="mime-not-supported",
            root_id=root_name, relative_path=relative_text, size_bytes=len(data),
            sha256=sha256, mime_type=mime_type,
        )
    decoded = _decode_text(data)
    if decoded is None:
        return _result(
            ok=False, status="binary", reason="text-decode-failed",
            root_id=root_name, relative_path=relative_text, size_bytes=len(data),
            sha256=sha256, mime_type=mime_type or "application/octet-stream",
        )
    text, encoding = decoded
    excerpt = text[:excerpt_limit]
    return _result(
        ok=True, status="ok", reason="text-excerpt",
        root_id=root_name, relative_path=relative_text, size_bytes=len(data),
        sha256=sha256, mime_type=mime_type or "text/plain", encoding=encoding,
        excerpt=excerpt, excerpt_truncated=len(text) > excerpt_limit,
    )


__all__ = [
    "ImageHeader",
    "ImageMimeType",
    "MAX_EXCERPT_CHARS",
    "MAX_FILE_BYTES",
    "MAX_WAV_CHUNKS",
    "MAX_WAV_HEADER_BYTES",
    "SourceInspection",
    "SourceProvenance",
    "inspect_local_source",
    "parse_image_header",
]
