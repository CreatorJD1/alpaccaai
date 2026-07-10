"""Pure, local-only provenance envelope for inspected attachments.

Callers must inspect a file locally before constructing this envelope. This
module validates only bounded metadata and authorization; it never reads a
file, stores raw content, invokes a model, or permits cloud egress.
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import InitVar, dataclass
import math
import re
from types import MappingProxyType
from typing import Literal


AttachmentType = Literal["text", "image", "audio", "video", "document"]
ProcessingLocation = Literal["local-only"]
CloudEgress = Literal["denied"]
AttachmentRejectionReason = Literal[
    "invalid-scope",
    "unauthorized-scope",
    "invalid-source",
    "invalid-mime",
    "unsupported-mime",
    "type-mismatch",
    "missing-provenance",
    "invalid-size",
    "size-limit",
    "invalid-dimensions",
    "pixel-limit",
    "invalid-duration",
    "classification-not-local",
    "cloud-egress-not-denied",
]

MAX_SCOPE_CHARS = 160
MAX_SOURCE_CHARS = 512
MAX_MIME_CHARS = 127
MAX_DIMENSION_PIXELS = 8192
MAX_IMAGE_PIXELS = 40_000_000
MAX_DURATION_SECONDS = 30 * 60.0

MAX_BYTES_BY_TYPE = MappingProxyType({
    "text": 2 * 1024 * 1024,
    "image": 12 * 1024 * 1024,
    "audio": 25 * 1024 * 1024,
    "video": 50 * 1024 * 1024,
    "document": 12 * 1024 * 1024,
})

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_MIME_RE = re.compile(
    r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_NONLOCAL_SCHEME_RE = re.compile(
    r"^(?:blob|data|file|ftp|ftps|gs|http|https|s3):", re.IGNORECASE
)
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[/\\]")

_TEXT_APPLICATION_MIMES = frozenset({
    "application/json",
    "application/toml",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
})
_DOCUMENT_MIMES = frozenset({
    "application/pdf",
    "application/msword",
    "application/rtf",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
})


class AttachmentEnvelopeRejected(ValueError):
    """A stable rejection code for malformed or unauthorized metadata."""

    def __init__(self, reason: AttachmentRejectionReason, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: AttachmentRejectionReason, message: str) -> None:
    raise AttachmentEnvelopeRejected(reason, message)


def _bounded_identifier(value: str, *, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        _reject("invalid-scope", f"{name} must be a string")
    cleaned = value.strip()
    if (
        not cleaned
        or len(cleaned) > maximum
        or not _IDENTIFIER_RE.fullmatch(cleaned)
    ):
        _reject("invalid-scope", f"{name} is not a bounded identifier")
    return cleaned


def _authorized_scope(scope: str, authorized_scopes: Collection[str]) -> str:
    clean_scope = _bounded_identifier(
        scope, name="scope", maximum=MAX_SCOPE_CHARS
    )
    if isinstance(authorized_scopes, (str, bytes)) or not isinstance(
        authorized_scopes, Collection
    ):
        _reject("unauthorized-scope", "authorized_scopes must be a collection")
    clean_authorized: set[str] = set()
    for candidate in authorized_scopes:
        clean_authorized.add(
            _bounded_identifier(
                candidate, name="authorized scope", maximum=MAX_SCOPE_CHARS
            )
        )
    if clean_scope not in clean_authorized:
        _reject("unauthorized-scope", "scope is not authorized for this result")
    return clean_scope


def _local_source(value: str) -> str:
    if not isinstance(value, str):
        _reject("invalid-source", "source must be a string")
    source = value.strip().replace("\\", "/")
    parts = source.split("/")
    if (
        not source
        or len(source) > MAX_SOURCE_CHARS
        or source.startswith(("/", "//"))
        or _WINDOWS_ABSOLUTE_RE.match(source)
        or _URI_SCHEME_RE.match(source)
        or _NONLOCAL_SCHEME_RE.match(source)
        or any(part in {"", ".", ".."} for part in parts)
        or any(ord(char) < 32 for char in source)
    ):
        _reject("invalid-source", "source must be a bounded local identifier")
    return source


def _mime(value: str) -> str:
    if not isinstance(value, str):
        _reject("invalid-mime", "mime_type must be a string")
    mime = value.strip().lower()
    if len(mime) > MAX_MIME_CHARS or not _MIME_RE.fullmatch(mime):
        _reject("invalid-mime", "mime_type is malformed")
    return mime


def _type_for_mime(mime_type: str) -> AttachmentType | None:
    major = mime_type.split("/", 1)[0]
    if major in {"text", "image", "audio", "video"}:
        return major  # type: ignore[return-value]
    if mime_type in _TEXT_APPLICATION_MIMES:
        return "text"
    if mime_type in _DOCUMENT_MIMES:
        return "document"
    return None


def _provenance(value: str) -> str:
    if not isinstance(value, str):
        _reject("missing-provenance", "sha256 must be a string")
    digest = value.strip().lower()
    if not _SHA256_RE.fullmatch(digest) or digest == "0" * 64:
        _reject(
            "missing-provenance",
            "sha256 must be a non-placeholder 64-character digest",
        )
    return digest


def _positive_int(value: int | None, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _reject("invalid-dimensions", f"{name} must be a positive integer")
    return value


def _media_dimensions(
    attachment_type: AttachmentType,
    width: int | None,
    height: int | None,
) -> tuple[int | None, int | None]:
    needs_dimensions = attachment_type in {"image", "video"}
    if not needs_dimensions:
        if width is not None or height is not None:
            _reject(
                "invalid-dimensions",
                "dimensions are only valid for image or video attachments",
            )
        return None, None
    clean_width = _positive_int(width, name="width")
    clean_height = _positive_int(height, name="height")
    if (
        clean_width > MAX_DIMENSION_PIXELS
        or clean_height > MAX_DIMENSION_PIXELS
    ):
        _reject("invalid-dimensions", "dimensions exceed the per-axis limit")
    if clean_width * clean_height > MAX_IMAGE_PIXELS:
        _reject("pixel-limit", "dimensions exceed the total pixel limit")
    return clean_width, clean_height


def _media_duration(
    attachment_type: AttachmentType, duration_seconds: float | None
) -> float | None:
    needs_duration = attachment_type in {"audio", "video"}
    if not needs_duration:
        if duration_seconds is not None:
            _reject(
                "invalid-duration",
                "duration is only valid for audio or video attachments",
            )
        return None
    if (
        isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, (int, float))
    ):
        _reject("invalid-duration", "duration_seconds must be numeric")
    duration = float(duration_seconds)
    if (
        not math.isfinite(duration)
        or duration <= 0.0
        or duration > MAX_DURATION_SECONDS
    ):
        _reject("invalid-duration", "duration_seconds is outside the limit")
    return duration


@dataclass(frozen=True, slots=True)
class AttachmentPerceptionEnvelope:
    """Provenanced attachment metadata authorized for one exact scope."""

    scope: str
    source: str
    mime_type: str
    attachment_type: AttachmentType
    sha256: str
    size_bytes: int
    authorized_scopes: InitVar[Collection[str]]
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    processing_location: ProcessingLocation = "local-only"
    cloud_egress: CloudEgress = "denied"

    def __post_init__(self, authorized_scopes: Collection[str]) -> None:
        scope = _authorized_scope(self.scope, authorized_scopes)
        source = _local_source(self.source)
        mime = _mime(self.mime_type)
        inferred_type = _type_for_mime(mime)
        if inferred_type is None:
            _reject("unsupported-mime", "mime_type is not supported")
        if self.attachment_type not in MAX_BYTES_BY_TYPE:
            _reject("type-mismatch", "attachment_type is not supported")
        if self.attachment_type != inferred_type:
            _reject("type-mismatch", "attachment_type does not match mime_type")
        digest = _provenance(self.sha256)
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes <= 0
        ):
            _reject("invalid-size", "size_bytes must be a positive integer")
        size_limit = MAX_BYTES_BY_TYPE[self.attachment_type]
        if self.size_bytes > size_limit:
            _reject("size-limit", "size_bytes exceeds the attachment type limit")
        width, height = _media_dimensions(
            self.attachment_type, self.width, self.height
        )
        duration = _media_duration(
            self.attachment_type, self.duration_seconds
        )
        if self.processing_location != "local-only":
            _reject(
                "classification-not-local",
                "processing_location must remain local-only",
            )
        if self.cloud_egress != "denied":
            _reject(
                "cloud-egress-not-denied",
                "cloud_egress must remain denied",
            )
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "mime_type", mime)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "height", height)
        object.__setattr__(self, "duration_seconds", duration)

    @property
    def provenance(self) -> str:
        return f"sha256:{self.sha256}"

    def as_dict(self) -> dict[str, object]:
        """Return metadata only; raw attachment bytes are never represented."""

        return {
            "scope": self.scope,
            "source": self.source,
            "mime_type": self.mime_type,
            "attachment_type": self.attachment_type,
            "provenance": self.provenance,
            "sha256": self.sha256,
            "metadata": {
                "size_bytes": self.size_bytes,
                "width": self.width,
                "height": self.height,
                "duration_seconds": self.duration_seconds,
            },
            "classification": {
                "processing_location": self.processing_location,
                "cloud_egress": self.cloud_egress,
            },
        }


AttachmentEnvelope = AttachmentPerceptionEnvelope


def create_attachment_envelope(
    *,
    scope: str,
    authorized_scopes: Collection[str],
    source: str,
    mime_type: str,
    attachment_type: AttachmentType,
    sha256: str,
    size_bytes: int,
    width: int | None = None,
    height: int | None = None,
    duration_seconds: float | None = None,
    processing_location: ProcessingLocation = "local-only",
    cloud_egress: CloudEgress = "denied",
) -> AttachmentPerceptionEnvelope:
    """Validate metadata and return a local-only attachment envelope."""

    return AttachmentPerceptionEnvelope(
        scope=scope,
        authorized_scopes=authorized_scopes,
        source=source,
        mime_type=mime_type,
        attachment_type=attachment_type,
        sha256=sha256,
        size_bytes=size_bytes,
        width=width,
        height=height,
        duration_seconds=duration_seconds,
        processing_location=processing_location,
        cloud_egress=cloud_egress,
    )


__all__ = [
    "AttachmentEnvelope",
    "AttachmentEnvelopeRejected",
    "AttachmentPerceptionEnvelope",
    "AttachmentRejectionReason",
    "AttachmentType",
    "CloudEgress",
    "MAX_BYTES_BY_TYPE",
    "MAX_DIMENSION_PIXELS",
    "MAX_DURATION_SECONDS",
    "MAX_IMAGE_PIXELS",
    "MAX_MIME_CHARS",
    "MAX_SCOPE_CHARS",
    "MAX_SOURCE_CHARS",
    "ProcessingLocation",
    "create_attachment_envelope",
]
