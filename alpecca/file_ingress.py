"""Pure, bounded ingress for trusted local text-file references.

The caller supplies a server-owned allowed-root mapping, one root identifier,
one relative path, and the exact server-derived scope.  Source inspection owns
the only file read and derives the MIME type, SHA-256 digest, and bounded text
excerpt.  This adapter accepts only text/code/markdown outcomes and turns their
metadata into the common local-only, cloud-denied attachment envelope.

No raw file bytes are retained or represented by the serializable result.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from alpecca.attachment_perception import (
    AttachmentEnvelopeRejected,
    AttachmentPerceptionEnvelope,
    AttachmentRejectionReason,
    MAX_BYTES_BY_TYPE,
    create_attachment_envelope,
)
from alpecca.source_perception import (
    MAX_EXCERPT_CHARS as SOURCE_MAX_EXCERPT_CHARS,
    MAX_FILE_BYTES as SOURCE_MAX_FILE_BYTES,
    SourceInspection,
    SourceProvenance,
    inspect_local_source,
)


MAX_TEXT_FILE_BYTES = min(
    SOURCE_MAX_FILE_BYTES,
    int(MAX_BYTES_BY_TYPE["text"]),
)
MAX_TEXT_EXCERPT_CHARS = SOURCE_MAX_EXCERPT_CHARS

# Keep enough of the already-bounded source excerpt to recognize container
# signatures even when a caller asks for a very short returned excerpt.
_CONTENT_CLASSIFICATION_CHARS = min(512, MAX_TEXT_EXCERPT_CHARS)
_TEXT_APPLICATION_MIMES = frozenset({
    "application/json",
    "application/toml",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
})

SourceFileRejectionReason = Literal[
    "invalid-root-id",
    "root-not-allowed",
    "root-unavailable",
    "root-not-directory",
    "invalid-path",
    "path-not-relative",
    "traversal",
    "symlink-not-allowed",
    "path-escape",
    "file-not-found",
    "stat-failed",
    "read-failed",
    "not-a-regular-file",
    "binary",
    "unsupported-mime",
    "size-limit",
    "source-rejected",
]
FileIngressRejectionReason = SourceFileRejectionReason | AttachmentRejectionReason

_PASSTHROUGH_SOURCE_REASONS = frozenset({
    "root-not-allowed",
    "root-unavailable",
    "root-not-directory",
    "invalid-path",
    "path-not-relative",
    "traversal",
    "symlink-not-allowed",
    "path-escape",
    "file-not-found",
    "stat-failed",
    "read-failed",
    "not-a-regular-file",
})


class FileIngressRejected(ValueError):
    """A stable fail-closed rejection for trusted file ingress."""

    def __init__(
        self,
        reason: FileIngressRejectionReason,
        message: str,
    ) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: FileIngressRejectionReason, message: str) -> None:
    raise FileIngressRejected(reason, message)


def _bounded_limit(value: int, maximum: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return min(value, maximum)


def _reject_source_failure(inspection: SourceInspection) -> None:
    if inspection.status == "too-large":
        _reject("size-limit", "file exceeds the trusted text ingress byte limit")
    if inspection.status == "binary":
        _reject("binary", "file is not decodable bounded text")
    if inspection.status == "unsupported":
        if inspection.reason == "not-a-regular-file":
            _reject("not-a-regular-file", "source is not a regular file")
        _reject("unsupported-mime", "file MIME type is not allowed for text ingress")
    if inspection.reason in _PASSTHROUGH_SOURCE_REASONS:
        _reject(
            cast(FileIngressRejectionReason, inspection.reason),
            "local source inspection rejected the file reference",
        )
    _reject("source-rejected", "local source inspection rejected the file")


def _is_allowed_text_mime(mime_type: str) -> bool:
    return mime_type.startswith("text/") or mime_type in _TEXT_APPLICATION_MIMES


def _has_binary_controls(text: str) -> bool:
    return any(
        (ord(character) < 32 and character not in {"\n", "\t"})
        or ord(character) == 127
        for character in text
    )


def _has_disallowed_container_signature(text: str) -> bool:
    head = text.lstrip("\ufeff \t\n")[:_CONTENT_CLASSIFICATION_CHARS]
    lowered = head.lower()
    if head.startswith(("%PDF-", "GIF87a", "GIF89a", "OggS", "fLaC", "MThd")):
        return True
    if head.startswith("ID3"):
        return True
    if head.startswith("RIFF") and any(
        marker in head[8:20] for marker in ("WAVE", "WEBP", "AVI ")
    ):
        return True
    if lowered.startswith("<svg"):
        return True
    return lowered.startswith("<?xml") and "<svg" in lowered


def _require_text_outcome(inspection: SourceInspection) -> None:
    if not inspection.ok:
        _reject_source_failure(inspection)
    if (
        inspection.reason != "text-excerpt"
        or inspection.image_metadata
        or inspection.audio_metadata
        or not _is_allowed_text_mime(inspection.mime_type)
    ):
        _reject("unsupported-mime", "only text, code, and markdown files are allowed")
    if inspection.encoding not in {"utf-8", "utf-16"}:
        _reject("binary", "file does not have a supported text encoding")
    if _has_binary_controls(inspection.excerpt):
        _reject("binary", "file excerpt contains binary control characters")
    if _has_disallowed_container_signature(inspection.excerpt):
        _reject("unsupported-mime", "file content identifies a disallowed media type")


@dataclass(frozen=True, slots=True)
class FileIngress:
    """A bounded text excerpt and metadata-only scoped provenance."""

    excerpt: str
    excerpt_truncated: bool
    encoding: str
    provenance: SourceProvenance
    envelope: AttachmentPerceptionEnvelope

    @property
    def scope(self) -> str:
        return self.envelope.scope

    @property
    def source(self) -> str:
        return self.envelope.source

    @property
    def mime_type(self) -> str:
        return self.envelope.mime_type

    @property
    def sha256(self) -> str:
        return self.envelope.sha256

    @property
    def size_bytes(self) -> int:
        return self.envelope.size_bytes

    def provenance_dict(self) -> dict[str, object]:
        """Return citation metadata without source bytes or absolute paths."""

        return {
            "source": self.provenance.as_dict(),
            "envelope": self.envelope.as_dict(),
        }

    def as_dict(self) -> dict[str, object]:
        """Return metadata only; callers read ``excerpt`` explicitly in memory."""

        return {
            "excerpt_truncated": self.excerpt_truncated,
            "encoding": self.encoding,
            **self.provenance_dict(),
        }


def ingest_file(
    root_id: str,
    relative_path: str | Path,
    *,
    allowed_roots: Mapping[str, Path],
    scope: str,
    max_bytes: int = MAX_TEXT_FILE_BYTES,
    max_excerpt_chars: int = MAX_TEXT_EXCERPT_CHARS,
) -> FileIngress:
    """Inspect one server-resolved local file and admit only bounded text.

    ``root_id``, ``allowed_roots``, and ``scope`` are server-owned policy input.
    The API intentionally accepts no absolute path, bytes, caller-supplied MIME,
    digest, source label, cloud classification, or egress override.
    """

    if not isinstance(root_id, str):
        _reject("invalid-root-id", "root_id must be a server-resolved string")
    if not isinstance(allowed_roots, Mapping):
        raise TypeError("allowed_roots must be a mapping")

    file_limit = _bounded_limit(max_bytes, MAX_TEXT_FILE_BYTES, "max_bytes")
    excerpt_limit = _bounded_limit(
        max_excerpt_chars,
        MAX_TEXT_EXCERPT_CHARS,
        "max_excerpt_chars",
    )
    inspection = inspect_local_source(
        root_id,
        relative_path,
        allowed_roots=allowed_roots,
        max_bytes=file_limit,
        max_excerpt_chars=max(excerpt_limit, _CONTENT_CLASSIFICATION_CHARS),
    )
    _require_text_outcome(inspection)

    provenance = inspection.provenance
    source = f"{provenance.root_id}:{provenance.relative_path}"
    try:
        envelope = create_attachment_envelope(
            scope=scope,
            authorized_scopes=(scope,),
            source=source,
            mime_type=inspection.mime_type,
            attachment_type="text",
            sha256=provenance.sha256,
            size_bytes=provenance.size_bytes,  # type: ignore[arg-type]
            processing_location="local-only",
            cloud_egress="denied",
        )
    except AttachmentEnvelopeRejected as exc:
        raise FileIngressRejected(exc.reason, str(exc)) from None

    excerpt = inspection.excerpt[:excerpt_limit]
    return FileIngress(
        excerpt=excerpt,
        excerpt_truncated=(
            inspection.excerpt_truncated
            or len(inspection.excerpt) > excerpt_limit
        ),
        encoding=inspection.encoding,
        provenance=provenance,
        envelope=envelope,
    )


ingest_text_file = ingest_file
TextFileIngress = FileIngress


__all__ = [
    "FileIngress",
    "FileIngressRejected",
    "FileIngressRejectionReason",
    "MAX_TEXT_EXCERPT_CHARS",
    "MAX_TEXT_FILE_BYTES",
    "SourceFileRejectionReason",
    "TextFileIngress",
    "ingest_file",
    "ingest_text_file",
]
