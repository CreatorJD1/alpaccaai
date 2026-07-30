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
from alpecca.approved_self_images import load_approved_self_images
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
MediaKind = Literal[
    "portrait", "speaking", "thinking", "reach", "rest", "shy",
    "confirmation", "sleeping", "running", "balance", "ready", "rear",
    "base", "expressions",
]
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
ApprovedPortraitStatus = Literal["unknown", "ready", "unavailable"]

INBOUND_MAX_BYTES = DEFAULT_MAX_IMAGE_BYTES
OUTBOUND_MAX_BYTES = min(2 * 1024 * 1024, ATTACHMENT_IMAGE_MAX_BYTES)
INBOUND_READ_TIMEOUT_SECONDS = 20.0
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif"})
IMAGE_MIME_TYPES = ("image/gif", "image/jpeg", "image/png")
AUDIO_EXTENSIONS = frozenset(
    {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}
)

_COMMAND_RE = re.compile(r"^\s*!image(?:\s+([a-z-]+))?\s*$", re.IGNORECASE)
_DIRECT_OUTBOUND_REQUEST_RE = re.compile(
    r"^\s*(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|"
    r"please\s+|i\s+(?:want|need|would\s+like)\s+you\s+to\s+)?"
    r"(?:send|show|share|post|attach)\b",
    re.IGNORECASE,
)
_DIRECT_ADDRESS_RE = re.compile(
    r"^\s*(?:(?:hey|hi|hello)\s*[,!:;-]?\s+)?"
    r"@?alpecca(?:[ _]?ai)?(?:\s*[,.:;!?-]\s*|\s+)",
    re.IGNORECASE,
)
_MENTION_RESIDUE_RE = re.compile(r"^\s*[,.:;!?-]+\s*")
_IMAGE_RE = re.compile(
    r"\b(?:image|picture|photo|portrait|selfie|character\s+sheet|design\s+sheet|"
    r"reference\s+sheet|base\s+model|gallery|pose|stance|rear\s+view|back\s+view)\b",
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
_MEDIA_KINDS = frozenset({
    "portrait", "speaking", "thinking", "reach", "rest", "shy",
    "confirmation", "sleeping", "running", "balance", "ready", "rear",
    "base", "expressions",
})
_MEDIA_KIND_ALIASES = MappingProxyType({
    "active": "speaking",
    "focused": "thinking",
    "reaching": "reach",
    "resting": "rest",
    "sleep": "sleeping",
    "run": "running",
    "dynamic": "balance",
    "confirm": "confirmation",
    "back": "rear",
    "rear-view": "rear",
    "gallery": "ready",
    "reference": "confirmation",
    "gestures": "reach",
    "gesture": "reach",
    "wardrobe": "rear",
    "outfit": "rear",
    "movement": "running",
})

# The complete outbound set is derived from the reviewed manifest shared with
# the cloud installer. Unknown files under familiar local paths never become
# sendable merely by existing there.
_APPROVED_SELF_IMAGE_ASSETS = load_approved_self_images()
APPROVED_SELF_IMAGE_SHA256 = MappingProxyType({
    asset.kind: asset.sha256 for asset in _APPROVED_SELF_IMAGE_ASSETS
})
APPROVED_SELF_IMAGE_KINDS = tuple(APPROVED_SELF_IMAGE_SHA256)

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
        "I can inspect exactly one image in an allowed Discord conversation. "
        "I did not read any of those attachments."
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

_STALE_MEDIA_TURN_CORRECTION = (
    "I'm following your current message here."
)


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


def stale_media_turn_correction() -> str:
    """Return a fixed current-turn correction for replayed media boilerplate."""

    return _STALE_MEDIA_TURN_CORRECTION


def media_readiness(
    *,
    media_enabled: bool,
    server_status: ServerMediaStatus = "unknown",
    local_vision_status: LocalVisionStatus = "unknown",
    portrait_status: ApprovedPortraitStatus = "unknown",
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
    if type(portrait_status) is not str or portrait_status not in {
        "unknown", "ready", "unavailable",
    }:
        raise ValueError("portrait_status is invalid")

    if not media_enabled or server_status == "disabled":
        inbound_status = "disabled"
    elif local_vision_status == "ready":
        inbound_status = "ready"
    elif local_vision_status == "unavailable":
        inbound_status = "vision-unavailable"
    else:
        inbound_status = "unverified"

    receive_ready = inbound_status == "ready"
    outbound_status = "explicit-closed-catalog" if media_enabled else "disabled"
    effective_portrait_status = portrait_status if media_enabled else "disabled"
    send_ready = media_enabled and portrait_status == "ready"
    return {
        "version": 1,
        "enabled": media_enabled,
        "ready": receive_ready,
        "receive_ready": receive_ready,
        "send_ready": send_ready,
        "gates": {
            "bridge_media": "enabled" if media_enabled else "disabled",
            "backend_media": server_status,
            "local_vision": local_vision_status,
            "approved_portrait": effective_portrait_status,
        },
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
    # Discord commonly labels phone uploads and CDN-transcoded attachments as
    # generic binary data. That metadata is not evidence of a conflicting file
    # type, so let the existing byte sniffer establish the concrete image MIME.
    # Specific declarations still have to match the bytes exactly.
    if declared in {"application/octet-stream", "binary/octet-stream"}:
        declared = None
    try:
        inspected = inspect_image_bytes(
            image_bytes,
            scope="discord:allowed-image",
            authorized_scopes={"discord:allowed-image"},
            source="discord:allowed-image",
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


def _normalize_outbound_request_text(text: str) -> str:
    """Remove only a direct Alpecca address or leftover mention punctuation."""

    clean = str(text or "").strip()
    addressed = _DIRECT_ADDRESS_RE.sub("", clean, count=1)
    if addressed != clean:
        clean = addressed
    return _MENTION_RESIDUE_RE.sub("", clean, count=1)


def requested_media_kind(text: str) -> MediaKind | None:
    """Recognize only an explicit request to attach one of Alpecca's own images."""

    raw = str(text or "").strip()
    command = _COMMAND_RE.fullmatch(raw)
    if command:
        requested = (command.group(1) or "portrait").lower()
        requested = _MEDIA_KIND_ALIASES.get(requested, requested)
        return requested if requested in _MEDIA_KINDS else None  # type: ignore[return-value]
    clean = _normalize_outbound_request_text(raw)
    if not (_DIRECT_OUTBOUND_REQUEST_RE.search(clean) and _IMAGE_RE.search(clean)):
        return None
    low = clean.casefold()
    if "sleeping" in low or "asleep" in low or "sleep pose" in low:
        return "sleeping"
    if "resting" in low or "rest pose" in low:
        return "rest"
    if "shy" in low or "reserved pose" in low:
        return "shy"
    if "reaching" in low or "reach pose" in low or "gesture" in low or "hand pose" in low:
        return "reach"
    if "confirmation" in low or "confirming" in low or "confirm pose" in low:
        return "confirmation"
    if "running" in low or "run pose" in low:
        return "running"
    if "balance" in low or "side-moving" in low:
        return "balance"
    if "ready" in low or "ready stance" in low:
        return "ready"
    if "rear" in low or "back view" in low or "wardrobe" in low or "outfit" in low:
        return "rear"
    if "thinking" in low or "focused" in low:
        return "thinking"
    if "speaking" in low or "talking" in low or "active pose" in low:
        return "speaking"
    if "base model" in low:
        return "base"
    if "expression" in low or "phoneme" in low:
        return "expressions"
    if "movement" in low or "action pose" in low:
        return "running"
    if "reference" in low or "character sheet" in low or "design sheet" in low:
        return "confirmation"
    if "gallery" in low or "latest art" in low or "latest image" in low:
        return "ready"
    if re.search(r"\banother\b", low):
        return "reach"
    return "portrait"


def requested_disabled_media_kind(text: str) -> DisabledMediaKind | None:
    """Recognize explicit outbound file/audio requests that remain disabled."""

    raw = str(text or "").strip()
    command = _DISABLED_COMMAND_RE.fullmatch(raw)
    if command:
        return command.group(1).lower()  # type: ignore[return-value]
    clean = _normalize_outbound_request_text(raw)
    if not _DIRECT_OUTBOUND_REQUEST_RE.search(clean):
        return None
    if _AUDIO_RE.search(clean):
        return "audio"
    if _FILE_RE.search(clean):
        return "file"
    return None


def _catalog_location(
    kind: MediaKind,
    avatar_dir: Path,
    character_dir: Path,
) -> tuple[Path, Path] | None:
    portrait_paths = {
        "portrait": avatar_dir / "portraits" / "idle.png",
        "speaking": avatar_dir / "portraits" / "speaking.png",
        "thinking": avatar_dir / "portraits" / "thinking.png",
    }
    pose_paths = {
        "reach": avatar_dir / "poses" / "reach.png",
        "rest": avatar_dir / "poses" / "rest.png",
        "shy": avatar_dir / "poses" / "shy.png",
    }
    reference_paths = {
        "confirmation": character_dir / "reference" / "poses" / "pose-1.png",
        "sleeping": character_dir / "reference" / "poses" / "pose-2.png",
        "running": character_dir / "reference" / "poses" / "pose-3.png",
        "balance": character_dir / "reference" / "poses" / "pose-4.png",
        "ready": character_dir / "reference" / "poses" / "pose-5.png",
        "rear": character_dir / "reference" / "poses" / "pose-6.png",
    }
    if kind in portrait_paths:
        return portrait_paths[kind], avatar_dir / "portraits"
    if kind in pose_paths:
        return pose_paths[kind], avatar_dir / "poses"
    if kind in reference_paths:
        return reference_paths[kind], character_dir / "reference" / "poses"
    return None


def _load_approved_outbound_image(
    kind: MediaKind,
    path: Path | None,
    *,
    expected_parent: Path,
    expected_sha256: str,
) -> OutboundDiscordImage | None:
    """Read one catalog entry after resolving it inside its fixed directory."""

    try:
        if path is None:
            return None
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or resolved.parent != expected_parent.resolve():
            return None
        if not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256 or "")):
            return None
        declared = (
            "image/jpeg"
            if resolved.suffix.lower() in {".jpg", ".jpeg"}
            else f"image/{resolved.suffix.lower().lstrip('.')}"
        )
        if resolved.stat().st_size > OUTBOUND_MAX_BYTES:
            return None
        with resolved.open("rb") as handle:
            raw = handle.read(OUTBOUND_MAX_BYTES + 1)
            if len(raw) > OUTBOUND_MAX_BYTES or handle.read(1):
                return None
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
    if inspected.envelope.sha256 != expected_sha256:
        return None
    return OutboundDiscordImage(
        kind=kind,
        filename=f"alpecca-{kind}{resolved.suffix.lower()}",
        image_bytes=inspected.image_bytes,
        mime_type=inspected.mime_type,
        size_bytes=len(inspected.image_bytes),
        sha256=inspected.envelope.sha256,
    )


def resolve_self_portrait() -> OutboundDiscordImage | None:
    """Resolve only Alpecca's approved local portrait, or return ``None``.

    Integration contract for the Discord bridge:
    - Call this only after an explicit request for Alpecca's own image.
    - Attach only the returned bounded ``image_bytes`` under ``filename``;
      never accept a path, URL, attachment, or model-provided asset choice.
    - A ``None`` result means no image may be sent; use the code-owned
      ``catalog-unavailable`` diagnostic instead of a fallback source.

    The public resolver has no caller-controlled path parameter.  The only
    permitted source is ``data/avatar/portraits/idle.png`` under ``AVATAR_DIR``.
    """

    avatar_dir = Path(AVATAR_DIR)
    portraits_dir = avatar_dir / "portraits"
    return _load_approved_outbound_image(
        "portrait",
        portraits_dir / "idle.png",
        expected_parent=portraits_dir,
        expected_sha256=APPROVED_SELF_IMAGE_SHA256["portrait"],
    )


def approved_portrait_status() -> ApprovedPortraitStatus:
    """Validate the one default self-portrait without exposing its local path."""

    return "ready" if resolve_self_portrait() is not None else "unavailable"


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
    avatar_dir = Path(avatar_dir)
    character_dir = Path(character_dir)
    expected_sha256 = APPROVED_SELF_IMAGE_SHA256.get(kind)
    if expected_sha256 is None:
        return None
    location = _catalog_location(kind, avatar_dir, character_dir)
    if location is None:
        return None
    path, expected_parent = location
    return _load_approved_outbound_image(
        kind,
        path,
        expected_parent=expected_parent,
        expected_sha256=expected_sha256,
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
    "ApprovedPortraitStatus",
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
    "approved_portrait_status",
    "looks_like_image_attachment",
    "media_diagnostic",
    "media_readiness",
    "prepare_inbound_image",
    "record_media_event",
    "requested_disabled_media_kind",
    "requested_media_kind",
    "resolve_self_portrait",
    "resolve_outbound_media",
    "stale_media_turn_correction",
    "validate_inbound_attachment_size",
]
