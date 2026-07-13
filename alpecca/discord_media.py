"""Bounded image ingress and approved image sharing for Alpecca's Discord bridge.

Discord attachments are untrusted bytes.  They are locally sniffed and measured
before the bridge forwards a canonical data URL to the authenticated backend.
Outbound images come only from a closed catalog of Alpecca-owned local assets;
neither a Discord message nor model output can supply a path or URL.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from alpecca import cognition as cognition_mod
from alpecca.attachment_ingress import (
    ATTACHMENT_IMAGE_MAX_BYTES,
    DEFAULT_MAX_IMAGE_BYTES,
    ImageIngressRejected,
    inspect_image_bytes,
)
from config import AVATAR_DIR, CHARACTER_DIR


InboundRejection = Literal[
    "not-an-image",
    "size-limit",
    "read-failed",
    "audit-unavailable",
]
MediaKind = Literal["portrait", "base", "reference", "gallery"]
DisabledMediaKind = Literal["file", "audio"]
MediaDiagnostic = Literal[
    "media-disabled",
    "vision-unavailable",
    "file-disabled",
    "audio-disabled",
    "multiple-attachments",
    "read-failed",
    "catalog-unavailable",
    "audit-unavailable",
]
ServerMediaStatus = Literal["unknown", "ready", "disabled"]
LocalVisionStatus = Literal["unknown", "ready", "unavailable"]

INBOUND_MAX_BYTES = DEFAULT_MAX_IMAGE_BYTES
OUTBOUND_MAX_BYTES = min(8 * 1024 * 1024, ATTACHMENT_IMAGE_MAX_BYTES)
INBOUND_READ_TIMEOUT_SECONDS = 20.0
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif"})
IMAGE_MIME_TYPES = ("image/gif", "image/jpeg", "image/png")
AUDIO_EXTENSIONS = frozenset(
    {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}
)

_COMMAND_RE = re.compile(
    r"^\s*!image(?:\s+(portrait|base|reference|gallery))?\s*$",
    re.IGNORECASE,
)
_SEND_RE = re.compile(r"\b(?:send|show|share|post|attach)\b", re.IGNORECASE)
_IMAGE_RE = re.compile(
    r"\b(?:image|picture|photo|portrait|character\s+sheet|design\s+sheet|"
    r"reference\s+sheet|base\s+model|gallery)\b",
    re.IGNORECASE,
)
_DISABLED_COMMAND_RE = re.compile(
    r"^\s*!(file|audio)(?:\s+.*)?$",
    re.IGNORECASE,
)
_FILE_RE = re.compile(
    r"\b(?:file|document|pdf|source\s+file|text\s+file)\b",
    re.IGNORECASE,
)
_AUDIO_RE = re.compile(
    r"\b(?:audio|voice\s+(?:clip|message|note)|recording|sound|wav|mp3)\b",
    re.IGNORECASE,
)
_GALLERY_NAME_RE = re.compile(r"^self-[0-9-]+\.(?:png|jpg|jpeg)$", re.IGNORECASE)

_DIAGNOSTICS = MappingProxyType({
    "media-disabled": (
        "Discord media is disabled. I did not read or send an attachment."
    ),
    "vision-unavailable": (
        "I validated the image locally, but verified local vision is unavailable. "
        "I did not infer any visual details."
    ),
    "file-disabled": (
        "Discord file payloads are disabled. I did not read or send that file."
    ),
    "audio-disabled": (
        "Discord audio payloads are disabled. I did not read, transcribe, or send audio."
    ),
    "multiple-attachments": (
        "I can inspect exactly one image in a direct message. I did not read any "
        "of those attachments."
    ),
    "read-failed": (
        "I could not read that image within the bounded local media window. "
        "Please send it again."
    ),
    "catalog-unavailable": (
        "That approved local image is unavailable, so I did not attach anything."
    ),
    "audit-unavailable": (
        "Discord media audit is unavailable. I did not read or send an attachment."
    ),
})


class DiscordImageRejected(ValueError):
    """Stable fail-closed error for an image the Discord bridge cannot accept."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PreparedInboundImage:
    data_url: str = field(repr=False)
    mime_type: str
    size_bytes: int
    width: int
    height: int
    sha256: str


@dataclass(frozen=True, slots=True)
class OutboundDiscordImage:
    kind: MediaKind
    filename: str
    image_bytes: bytes = field(repr=False)
    mime_type: str
    size_bytes: int
    sha256: str


def media_diagnostic(reason: MediaDiagnostic) -> str:
    """Return one code-owned diagnostic that cannot echo Discord content."""

    if type(reason) is not str or reason not in _DIAGNOSTICS:
        raise ValueError("unknown Discord media diagnostic")
    return _DIAGNOSTICS[reason]


def media_readiness(
    *,
    media_enabled: bool,
    server_status: ServerMediaStatus = "unknown",
    local_vision_status: LocalVisionStatus = "unknown",
) -> dict[str, object]:
    """Return deterministic media posture without paths, URLs, IDs, or secrets."""

    if type(media_enabled) is not bool:
        raise TypeError("media_enabled must be bool")
    if type(server_status) is not str or server_status not in {
        "unknown", "ready", "disabled",
    }:
        raise ValueError("server_status is invalid")
    if type(local_vision_status) is not str or local_vision_status not in {
        "unknown", "ready", "unavailable",
    }:
        raise ValueError("local_vision_status is invalid")

    if not media_enabled or server_status == "disabled":
        inbound_status = "disabled"
    elif local_vision_status == "ready":
        inbound_status = "ready"
    elif local_vision_status == "unavailable":
        inbound_status = "vision-unavailable"
    else:
        inbound_status = "unverified"

    outbound_status = "explicit-closed-catalog" if media_enabled else "disabled"
    return {
        "version": 1,
        "ready": inbound_status == "ready",
        "receive": {
            "image": {
                "status": inbound_status,
                "max_bytes": INBOUND_MAX_BYTES,
                "mime_types": list(IMAGE_MIME_TYPES),
                "processing": "verified-local-only",
                "cloud_egress": "denied",
            },
            "file": {"status": "disabled"},
            "audio": {"status": "disabled"},
        },
        "send": {
            "image": {
                "status": outbound_status,
                "max_bytes": OUTBOUND_MAX_BYTES,
                "source": "closed-local-catalog",
            },
            "file": {"status": "disabled"},
            "audio": {"status": "disabled"},
        },
    }


def looks_like_image_attachment(filename: str, content_type: str | None) -> bool:
    """Use Discord metadata only to choose a candidate; bytes remain authoritative."""

    declared = str(content_type or "").split(";", 1)[0].strip().lower()
    return declared.startswith("image/") or Path(str(filename or "")).suffix.lower() in IMAGE_EXTENSIONS


def attachment_media_kind(
    filename: str,
    content_type: str | None,
) -> Literal["image", "file", "audio"]:
    """Classify Discord metadata only for routing; bytes remain authoritative."""

    if looks_like_image_attachment(filename, content_type):
        return "image"
    declared = str(content_type or "").split(";", 1)[0].strip().lower()
    suffix = Path(str(filename or "")).suffix.lower()
    if declared.startswith("audio/") or suffix in AUDIO_EXTENSIONS:
        return "audio"
    return "file"


def validate_inbound_attachment_size(value: object) -> int:
    """Require Discord's authoritative size before any CDN read begins."""

    if type(value) is not int or value <= 0:
        raise DiscordImageRejected(
            "invalid-size",
            "Discord image size metadata is invalid",
        )
    if value > INBOUND_MAX_BYTES:
        raise DiscordImageRejected(
            "size-limit",
            "Discord image exceeds the local perception byte limit",
        )
    return value


def prepare_inbound_image(
    image_bytes: bytes,
    *,
    declared_mime_type: str | None,
) -> PreparedInboundImage:
    """Validate one Discord image and return a canonical bounded data URL."""

    declared = str(declared_mime_type or "").split(";", 1)[0].strip().lower() or None
    try:
        inspected = inspect_image_bytes(
            image_bytes,
            scope="discord:creator-dm-image",
            authorized_scopes={"discord:creator-dm-image"},
            source="discord:creator-dm-image",
            declared_mime_type=declared,
            max_bytes=INBOUND_MAX_BYTES,
        )
    except ImageIngressRejected as exc:
        raise DiscordImageRejected(str(exc.reason), str(exc)) from None
    encoded = base64.b64encode(inspected.image_bytes).decode("ascii")
    return PreparedInboundImage(
        data_url=f"data:{inspected.mime_type};base64,{encoded}",
        mime_type=inspected.mime_type,
        size_bytes=len(inspected.image_bytes),
        width=inspected.width,
        height=inspected.height,
        sha256=inspected.envelope.sha256,
    )


def requested_media_kind(text: str) -> MediaKind | None:
    """Recognize only an explicit request to attach one of Alpecca's own images."""

    clean = str(text or "").strip()
    command = _COMMAND_RE.fullmatch(clean)
    if command:
        return (command.group(1) or "portrait").lower()  # type: ignore[return-value]
    if not (_SEND_RE.search(clean) and _IMAGE_RE.search(clean)):
        return None
    low = clean.casefold()
    if "base model" in low:
        return "base"
    if "reference" in low or "character sheet" in low or "design sheet" in low:
        return "reference"
    if "gallery" in low or "latest art" in low or "latest image" in low:
        return "gallery"
    return "portrait"


def requested_disabled_media_kind(text: str) -> DisabledMediaKind | None:
    """Recognize explicit outbound file/audio requests that remain disabled."""

    clean = str(text or "").strip()
    command = _DISABLED_COMMAND_RE.fullmatch(clean)
    if command:
        return command.group(1).lower()  # type: ignore[return-value]
    if not _SEND_RE.search(clean):
        return None
    if _AUDIO_RE.search(clean):
        return "audio"
    if _FILE_RE.search(clean):
        return "file"
    return None


def _latest_gallery_image(character_dir: Path) -> Path | None:
    gallery = character_dir / "gallery"
    if not gallery.is_dir():
        return None
    candidates = [
        path for path in gallery.iterdir()
        if path.is_file() and _GALLERY_NAME_RE.fullmatch(path.name)
    ]
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name), default=None)


def _catalog_path(kind: MediaKind, avatar_dir: Path, character_dir: Path) -> Path | None:
    if kind == "portrait":
        return avatar_dir / "portraits" / "idle.png"
    if kind == "base":
        return character_dir / "reference" / "base-model.png"
    if kind == "reference":
        return character_dir / "reference" / "master-character-sheet.png"
    return _latest_gallery_image(character_dir)


def resolve_outbound_media(
    text: str,
    *,
    avatar_dir: Path = AVATAR_DIR,
    character_dir: Path = CHARACTER_DIR,
) -> OutboundDiscordImage | None:
    """Resolve an explicit request through the closed local media catalog."""

    kind = requested_media_kind(text)
    if kind is None:
        return None
    path = _catalog_path(kind, Path(avatar_dir), Path(character_dir))
    if path is None or not path.is_file():
        return None
    expected_parent = (
        Path(avatar_dir) / "portraits"
        if kind == "portrait"
        else Path(character_dir) / ("gallery" if kind == "gallery" else "reference")
    ).resolve()
    resolved = path.resolve()
    if resolved.parent != expected_parent:
        return None
    if kind == "gallery" and not _GALLERY_NAME_RE.fullmatch(resolved.name):
        return None
    declared = "image/jpeg" if resolved.suffix.lower() in {".jpg", ".jpeg"} else f"image/{resolved.suffix.lower().lstrip('.')}"
    try:
        raw = resolved.read_bytes()
        inspected = inspect_image_bytes(
            raw,
            scope=f"discord:outbound:{kind}",
            authorized_scopes={f"discord:outbound:{kind}"},
            source=f"discord:approved-{kind}",
            declared_mime_type=declared,
            max_bytes=OUTBOUND_MAX_BYTES,
        )
    except (OSError, ImageIngressRejected):
        return None
    return OutboundDiscordImage(
        kind=kind,
        filename=f"alpecca-{kind}{resolved.suffix.lower()}",
        image_bytes=inspected.image_bytes,
        mime_type=inspected.mime_type,
        size_bytes=len(inspected.image_bytes),
        sha256=inspected.envelope.sha256,
    )


def record_media_event(
    direction: Literal["inbound", "outbound"],
    *,
    status: Literal["accepted", "sent", "rejected"],
    mime_type: str = "",
    size_bytes: int = 0,
    sha256: str = "",
    kind: str = "",
) -> int | None:
    """Write content-free Discord media evidence into the cognition ledger."""

    try:
        return cognition_mod.record_observation(
            cognition_mod.CognitionObservation(
                source="discord_media",
                content=f"Discord image {direction} was {status}.",
                confidence=1.0,
                room="discord",
                privacy_class="local",
                scope="creator:discord",
                metadata={
                    "event": "discord_image",
                    "direction": direction,
                    "status": status,
                    "mime_type": str(mime_type or "")[:64],
                    "size_bytes": max(0, int(size_bytes or 0)),
                    "sha256": str(sha256 or "")[:64],
                    "kind": str(kind or "")[:32],
                },
            )
        )
    except Exception:
        return None


__all__ = [
    "AUDIO_EXTENSIONS",
    "DisabledMediaKind",
    "DiscordImageRejected",
    "IMAGE_EXTENSIONS",
    "IMAGE_MIME_TYPES",
    "INBOUND_MAX_BYTES",
    "INBOUND_READ_TIMEOUT_SECONDS",
    "OUTBOUND_MAX_BYTES",
    "LocalVisionStatus",
    "MediaDiagnostic",
    "OutboundDiscordImage",
    "PreparedInboundImage",
    "ServerMediaStatus",
    "attachment_media_kind",
    "looks_like_image_attachment",
    "media_diagnostic",
    "media_readiness",
    "prepare_inbound_image",
    "record_media_event",
    "requested_disabled_media_kind",
    "requested_media_kind",
    "resolve_outbound_media",
    "validate_inbound_attachment_size",
]
