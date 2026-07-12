"""Pure, bounded local ingress validation for base64 and raw image payloads.

This module accepts already-provided data only. It performs no path access,
network I/O, disk writes, or model calls. Successful results retain image bytes
in memory for a later local consumer; their serializable form is metadata only.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Literal

from alpecca.attachment_perception import (
    AttachmentEnvelopeRejected,
    AttachmentPerceptionEnvelope,
    AttachmentRejectionReason,
    MAX_BYTES_BY_TYPE,
    create_attachment_envelope,
)
from alpecca.source_perception import ImageMimeType, parse_image_header


ATTACHMENT_IMAGE_MAX_BYTES = int(MAX_BYTES_BY_TYPE["image"])
DEFAULT_MAX_IMAGE_BYTES = min(2 * 1024 * 1024, ATTACHMENT_IMAGE_MAX_BYTES)
_MAX_DATA_URL_HEADER_CHARS = 64
_SUPPORTED_IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/gif"})

ImageIngressRejectionReason = (
    Literal[
        "invalid-bytes",
        "malformed-data-url",
        "malformed-base64",
        "unsupported-mime",
        "mime-mismatch",
    ]
    | AttachmentRejectionReason
)


class ImageIngressRejected(ValueError):
    """A stable fail-closed rejection for untrusted image ingress."""

    def __init__(self, reason: ImageIngressRejectionReason, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _reject(reason: ImageIngressRejectionReason, message: str) -> None:
    raise ImageIngressRejected(reason, message)


def _effective_max_bytes(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("max_bytes must be a positive integer")
    return min(value, ATTACHMENT_IMAGE_MAX_BYTES)


def _max_base64_chars(max_bytes: int) -> int:
    return ((max_bytes + 2) // 3) * 4


def _normalize_declared_mime(value: str | None) -> ImageMimeType | None:
    if value is None:
        return None
    if not isinstance(value, str):
        _reject("unsupported-mime", "declared MIME type is not supported")
    mime_type = value.strip().lower()
    if mime_type not in _SUPPORTED_IMAGE_MIMES:
        _reject("unsupported-mime", "declared MIME type is not supported")
    return mime_type  # type: ignore[return-value]


def _split_base64_payload(value: str) -> tuple[ImageMimeType | None, str]:
    if not isinstance(value, str):
        _reject("malformed-base64", "image payload must be a base64 string")
    if not value.startswith("data:"):
        return None, value
    header, separator, encoded = value.partition(",")
    if not separator or len(header) > _MAX_DATA_URL_HEADER_CHARS:
        _reject("malformed-data-url", "data URL header is malformed")
    suffix = ";base64"
    if not header.endswith(suffix):
        _reject("malformed-data-url", "data URL must use canonical base64 encoding")
    mime_type = header[len("data:"):-len(suffix)]
    if not mime_type or header != f"data:{mime_type}{suffix}":
        _reject("malformed-data-url", "data URL header is malformed")
    return _normalize_declared_mime(mime_type), encoded


def _decode_base64(encoded: str, max_bytes: int) -> bytes:
    if not encoded:
        _reject("malformed-base64", "base64 image payload is empty")
    try:
        encoded_bytes = encoded.encode("ascii")
    except UnicodeEncodeError:
        _reject("malformed-base64", "base64 image payload must be ASCII")
    if len(encoded_bytes) > _max_base64_chars(max_bytes):
        _reject("size-limit", "encoded image payload exceeds the byte limit")
    try:
        decoded = base64.b64decode(encoded_bytes, validate=True)
    except (binascii.Error, ValueError):
        _reject("malformed-base64", "base64 image payload is malformed")
    if not decoded:
        _reject("malformed-base64", "base64 image payload is empty")
    if len(decoded) > max_bytes:
        _reject("size-limit", "decoded image payload exceeds the byte limit")
    return decoded


def _create_envelope(
    *,
    scope: str,
    authorized_scopes: Collection[str],
    source: str,
    mime_type: ImageMimeType,
    image_bytes: bytes,
    width: int,
    height: int,
) -> AttachmentPerceptionEnvelope:
    try:
        sha256 = hashlib.sha256(image_bytes).hexdigest()
        return create_attachment_envelope(
            scope=scope,
            authorized_scopes=authorized_scopes,
            source=source,
            mime_type=mime_type,
            attachment_type="image",
            sha256=sha256,
            size_bytes=len(image_bytes),
            width=width,
            height=height,
            processing_location="local-only",
            cloud_egress="denied",
        )
    except AttachmentEnvelopeRejected as exc:
        raise ImageIngressRejected(exc.reason, str(exc)) from None


@dataclass(frozen=True, slots=True)
class ImageIngress:
    """An immutable in-memory image plus its local-only perception envelope."""

    image_bytes: bytes = field(repr=False)
    envelope: AttachmentPerceptionEnvelope

    @property
    def mime_type(self) -> str:
        return self.envelope.mime_type

    @property
    def width(self) -> int:
        assert self.envelope.width is not None
        return self.envelope.width

    @property
    def height(self) -> int:
        assert self.envelope.height is not None
        return self.envelope.height

    def as_dict(self) -> dict[str, object]:
        """Return serializable metadata without raw image bytes."""

        return self.envelope.as_dict()


def inspect_image_bytes(
    image_bytes: bytes,
    *,
    scope: str,
    authorized_scopes: Collection[str],
    source: str,
    declared_mime_type: str | None = None,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> ImageIngress:
    """Validate raw in-memory image bytes for a locally scoped later consumer.

    This is the raw-byte entry point for callers such as a screen-share route.
    It accepts no file path or URL, performs no egress, and returns metadata only
    from ``as_dict()``. ``declared_mime_type`` is optional but, when supplied,
    must exactly match the locally sniffed header MIME type.
    """

    maximum = _effective_max_bytes(max_bytes)
    if not isinstance(image_bytes, bytes) or not image_bytes:
        _reject("invalid-bytes", "image bytes must be a nonempty bytes value")
    if len(image_bytes) > maximum:
        _reject("size-limit", "image bytes exceed the byte limit")
    declared = _normalize_declared_mime(declared_mime_type)
    header = parse_image_header(image_bytes)
    if header is None:
        if declared is None:
            _reject("unsupported-mime", "image header is not a supported image type")
        _reject("mime-mismatch", "declared MIME type does not match image bytes")
    if header.width is None or header.height is None:
        _reject("invalid-dimensions", "image header does not contain dimensions")
    if declared is not None and declared != header.mime_type:
        _reject("mime-mismatch", "declared MIME type does not match image bytes")
    envelope = _create_envelope(
        scope=scope,
        authorized_scopes=authorized_scopes,
        source=source,
        mime_type=header.mime_type,
        image_bytes=image_bytes,
        width=header.width,
        height=header.height,
    )
    return ImageIngress(image_bytes=image_bytes, envelope=envelope)


def ingest_image(
    value: str,
    *,
    scope: str,
    authorized_scopes: Collection[str],
    source: str,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
) -> ImageIngress:
    """Decode one strict base64 image value and inspect it locally in memory."""

    maximum = _effective_max_bytes(max_bytes)
    declared_mime_type, encoded = _split_base64_payload(value)
    image_bytes = _decode_base64(encoded, maximum)
    return inspect_image_bytes(
        image_bytes,
        scope=scope,
        authorized_scopes=authorized_scopes,
        source=source,
        declared_mime_type=declared_mime_type,
        max_bytes=maximum,
    )


__all__ = [
    "ATTACHMENT_IMAGE_MAX_BYTES",
    "DEFAULT_MAX_IMAGE_BYTES",
    "ImageIngress",
    "ImageIngressRejected",
    "ImageIngressRejectionReason",
    "ingest_image",
    "inspect_image_bytes",
]
