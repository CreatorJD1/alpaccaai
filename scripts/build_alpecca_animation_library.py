"""Build Alpecca's staged 2D-in-3D animation source manifests.

This is the first gate for the large source-art library. It catalogs source
references outside public web assets, then writes a small runtime matrix manifest
that describes the current atlas fallbacks. The browser should load compiled
atlases, not this future 40GB source pool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_ROOT = Path(
    r"C:\Users\Jason\Downloads\Character art for Alpecca-20260612T103628Z-3-001\Character art for Alpecca"
)
DEFAULT_LIBRARY_ROOT = REPO_ROOT / "data" / "alpecca_art_source"
DEFAULT_RUNTIME_ROOT = REPO_ROOT / "apps" / "house-hq" / "public" / "assets" / "alpecca-optimized"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
LIVE2D_EXTS = {".json", ".moc3", ".cdi3.json", ".physics3.json", ".model3.json"}
SOURCE_EXTS = IMAGE_EXTS | LIVE2D_EXTS

VERTICAL_TIERS = ("low", "eye", "high")
MATRIX_HORIZONTAL_TIERS = ("front", "frontDiag", "side", "backDiag", "back")
VIEW_SECTORS_16 = tuple(f"s{i}" for i in range(16))
HORIZONTAL_TIERS = VIEW_SECTORS_16
RUNTIME_VERTICAL_TIERS = ("low", "eye", "high")

STATE_FOLDERS = {
    "idleDown": "iso_idle_down_right",
    "idleUp": "iso_idle_up_right",
    "idleSide": "iso_idle_right_right",
    "idleNortheast": "iso_idle_northeast_right",
    "idleSoutheast": "iso_idle_southeast_right",
    "talkDown": "gpt16_talk_down",
    "walkDown": "iso_walk_down_right",
    "walkUp": "iso_walk_up_right",
    "walkSide": "iso_walk_right_right",
    "walkNortheast": "iso_walk_northeast_right",
    "walkSoutheast": "iso_walk_southeast_right",
    "wave": "Wave",
    "waveDown": "Wave Down",
    "waveNortheast": "Wave Northeast",
    "waveUp": "Wave Up",
    "kneel": "Kneel",
    "crouch": "Crouch",
    "point": "Point",
    "sit": "Sit",
    "sleepDown": "Sleep Down",
    "sleepUp": "Sleep Up",
    "sleepNortheast": "Sleep Northeast",
    "sleepSoutheast": "Sleep Southeast",
}

MATRIX_FALLBACKS = {
    "idle": {
        "front": "idleDown",
        "frontDiag": "idleSoutheast",
        "side": "idleSide",
        "backDiag": "idleNortheast",
        "back": "idleUp",
    },
    "listen": {
        "front": "idleDown",
        "frontDiag": "idleSoutheast",
        "side": "idleSide",
        "backDiag": "idleNortheast",
        "back": "idleUp",
    },
    "talk": {
        "front": "talkDown",
        "frontDiag": "talkDown",
        "side": "talkDown",
        "backDiag": "talkDown",
        "back": "talkDown",
    },
    "walk": {
        "front": "walkDown",
        "frontDiag": "walkSoutheast",
        "side": "walkSide",
        "backDiag": "walkNortheast",
        "back": "walkUp",
    },
    "wave": {
        "front": "waveDown",
        "frontDiag": "wave",
        "side": "wave",
        "backDiag": "waveNortheast",
        "back": "waveUp",
    },
    "inspect": {
        "front": "point",
        "frontDiag": "point",
        "side": "point",
        "backDiag": "kneel",
        "back": "kneel",
    },
    "careful": {
        "front": "crouch",
        "frontDiag": "crouch",
        "side": "crouch",
        "backDiag": "kneel",
        "back": "kneel",
    },
    "rest": {
        "front": "sit",
        "frontDiag": "sleepSoutheast",
        "side": "sit",
        "backDiag": "sleepNortheast",
        "back": "sleepUp",
    },
    "sleep": {
        "front": "sleepDown",
        "frontDiag": "sleepSoutheast",
        "side": "sleepSoutheast",
        "backDiag": "sleepNortheast",
        "back": "sleepUp",
    },
}

GENERATION_QUALITY_GATES = [
    "complete strip generated as one coherent pass, not isolated frames",
    "same adult 5ft 7in body class for standing frames",
    "same Alpecca design lock: face, hair volume, blue X hair clip, hoodie-jacket, black shorts, lanyard, stockings, right thigh strap, and boots",
    "white full-length thigh-high stockings must reach the upper thigh under the black shorts and stay consistent across frames",
    "black right-leg thigh strap must be present where that leg side is visible",
    "chunky cream/white comfort boots with pale blue soles must not become sneakers",
    "no halo baked into base body frames; halo/ring effects must be separate overlay layers",
    "no floor shadow, drop shadow, glow smear, or contact shadow baked into base body frames; shadows must be separate render/effect layers",
    "no blue orbs, round ear-like discs, floating balls, animal ears, or invented head ornaments",
    "transparent background with bottom-center foot anchor",
    "no cropped hair, hands, feet, jacket, stockings, thigh strap, or boots",
    "feet stay grounded and body height does not drift",
    "walk phases include contact, down, passing, up, opposite contact, opposite down, opposite passing, opposite up",
    "walk frames must not repeat the same leg pose in adjacent or alternating frames; reject duplicate lower-body silhouettes that make motion read as lag",
    "walk contact frames must alternate left/right foot support with visible passing and lift phases between contacts",
    "left/right silhouettes remain consistent after mirror policy",
    "profile mouth and expression overlays line up with the base face",
    "preview passes at game scale and close-up scale before runtime promotion",
]

GENERATION_BATCHES = [
    {
        "batch": 1,
        "name": "standing-16-sector-foundation",
        "description": "Generate idle, listen, talk, and neutral standing views for all 16 camera sectors.",
        "actions": ("idle", "listen", "talk"),
        "verticals": VERTICAL_TIERS,
        "horizontals": HORIZONTAL_TIERS,
        "frameCount": {"idle": 8, "listen": 8, "talk": 12},
        "priority": "critical",
    },
    {
        "batch": 2,
        "name": "walk-16-sector-foundation",
        "description": "Generate clean 16-frame walk cycles for all 16 camera sectors.",
        "actions": ("walk",),
        "verticals": VERTICAL_TIERS,
        "horizontals": HORIZONTAL_TIERS,
        "frameCount": {"walk": 16},
        "priority": "critical",
    },
    {
        "batch": 3,
        "name": "wave-16-sector-foundation",
        "description": "Generate greeting and reply wave motions for all 16 camera sectors.",
        "actions": ("wave",),
        "verticals": VERTICAL_TIERS,
        "horizontals": HORIZONTAL_TIERS,
        "frameCount": {"wave": 10},
        "priority": "high",
    },
    {
        "batch": 4,
        "name": "inspection-and-careful-actions",
        "description": "Generate body actions for looking, pointing, crouching, kneeling, and careful reactions.",
        "actions": ("inspect", "careful"),
        "verticals": ("eye",),
        "horizontals": HORIZONTAL_TIERS,
        "frameCount": {"inspect": 10, "careful": 10},
        "priority": "high",
    },
    {
        "batch": 5,
        "name": "rest-nook-physical-states",
        "description": "Generate sit, sleep, wake, and rest-nook transitions with intentional lower body height.",
        "actions": ("rest", "sleep", "wake"),
        "verticals": ("eye",),
        "horizontals": HORIZONTAL_TIERS,
        "frameCount": {"rest": 10, "sleep": 12, "wake": 12},
        "priority": "medium",
    },
    {
        "batch": 6,
        "name": "emotional-micro-actions",
        "description": "Generate high-density expression and gesture overlays for cinematic reactions.",
        "actions": ("surprised", "shy", "curious", "worried", "amused", "thinking"),
        "verticals": ("eye",),
        "horizontals": ("front", "frontDiag", "side"),
        "frameCount": 8,
        "priority": "medium",
    },
    {
        "batch": 7,
        "name": "mouth-shape-overlays-16-sector",
        "description": "Generate mouth-shape overlay strips for natural speech and phoneme-like talking in all 16 camera sectors.",
        "targetKind": "layer-atlas",
        "layerRole": "mouth-eye-overlay",
        "actions": ("mouthOverlay",),
        "verticals": VERTICAL_TIERS,
        "horizontals": HORIZONTAL_TIERS,
        "frameCount": 12,
        "priority": "critical",
    },
    {
        "batch": 8,
        "name": "eye-expression-overlays-16-sector",
        "description": "Generate eye, blink, brow, and gaze overlay strips for attention and emotional expression in all 16 camera sectors.",
        "targetKind": "layer-atlas",
        "layerRole": "expression-overlay",
        "actions": ("eyeOverlay",),
        "verticals": VERTICAL_TIERS,
        "horizontals": HORIZONTAL_TIERS,
        "frameCount": 12,
        "priority": "critical",
    },
    {
        "batch": 9,
        "name": "head-turn-and-hair-dynamics-16-sector",
        "description": "Generate subtle head-turn, hair sway, and hoodie motion overlays for 2D volumetric presence.",
        "targetKind": "layer-atlas",
        "layerRole": "expression-overlay",
        "actions": ("headHairOverlay",),
        "verticals": VERTICAL_TIERS,
        "horizontals": HORIZONTAL_TIERS,
        "frameCount": 8,
        "priority": "high",
    },
    {
        "batch": 11,
        "name": "separate-halo-ring-overlays-16-sector",
        "description": "Generate separate halo/ring overlay strips so the base body art stays clean and the halo can be rendered as an effect layer.",
        "targetKind": "layer-atlas",
        "layerRole": "halo-overlay",
        "actions": ("haloOverlay",),
        "verticals": VERTICAL_TIERS,
        "horizontals": HORIZONTAL_TIERS,
        "frameCount": 8,
        "priority": "high",
    },
    {
        "batch": 12,
        "name": "separate-shadow-depth-overlays-16-sector",
        "description": "Generate separate alpha shadow/depth proxy strips so no contact shadow or floor shadow is baked into Alpecca body art.",
        "targetKind": "layer-atlas",
        "layerRole": "shadow-depth-overlay",
        "actions": ("shadowOverlay",),
        "verticals": VERTICAL_TIERS,
        "horizontals": HORIZONTAL_TIERS,
        "frameCount": 8,
        "priority": "high",
    },
    {
        "batch": 10,
        "name": "reaction-micro-overlays",
        "description": "Generate high-detail cinematic reaction overlays: lip quiver, finger stare, shy glance, soft startle, self-critique, and curious focus.",
        "targetKind": "layer-atlas",
        "layerRole": "expression-overlay",
        "actions": ("lipQuiver", "fingerStare", "shyGlance", "softStartle", "selfCritique", "curiousFocus"),
        "verticals": ("eye",),
        "horizontals": ("front", "frontDiag", "side"),
        "frameCount": 8,
        "priority": "high",
    },
]


@dataclass
class SourceRecord:
    id: str
    sourcePath: str
    sourceRoot: str
    folder: str
    fileName: str
    ext: str
    sizeBytes: int
    modifiedUtc: str
    action: str
    verticalTier: str
    horizontalTier: str
    frameIndex: int
    approvalStatus: str
    origin: str
    identityTags: list[str]
    notes: str
    width: int | None = None
    height: int | None = None
    hasAlpha: bool = False
    alphaBounds: dict | None = None
    suggestedCanonicalName: str = ""
    tagConfidence: str = "folder"
    needsHumanTag: bool = True
    sha1: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "item"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def path_has_live2d_suffix(path: Path) -> bool:
    text = path.name.lower()
    return any(text.endswith(ext) for ext in LIVE2D_EXTS)


def source_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in IMAGE_EXTS or path_has_live2d_suffix(path):
            yield path


def tokens_for(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root)
    text = " ".join(rel.parts).lower()
    return re.findall(r"[a-z0-9]+", text)


def infer_action(tokens: list[str]) -> str:
    token_set = set(tokens)
    if {"walk", "walking", "movement", "move"} & token_set:
        return "walk"
    if {"run", "running"} & token_set:
        return "run"
    if {"idle", "neutral", "standing", "stand"} & token_set:
        return "idle"
    if {"talk", "talking", "speech", "mouth", "voice"} & token_set:
        return "talk"
    if {"expression", "expressions", "face", "smile", "sad", "angry", "happy", "worried"} & token_set:
        return "expression"
    if {"wave", "greet", "greeting"} & token_set:
        return "wave"
    if {"sleep", "rest", "sit", "sitting"} & token_set:
        return "rest"
    if {"pose", "poses", "action", "actions"} & token_set:
        return "pose"
    if {"live2d", "model"} & token_set:
        return "rig"
    if {"master", "sheets", "sheet"} & token_set:
        return "identity"
    return "reference"


def infer_vertical(tokens: list[str]) -> str:
    token_set = set(tokens)
    if {"low", "worm", "below", "upshot"} & token_set:
        return "low"
    if {"high", "top", "above", "downshot"} & token_set:
        return "high"
    return "eye"


def infer_horizontal(tokens: list[str]) -> str:
    token_set = set(tokens)
    if {"back", "rear", "up", "north"} & token_set:
        return "back"
    if {"northeast", "northwest", "ne", "nw", "backdiag"} & token_set:
        return "backDiag"
    if {"southeast", "southwest", "se", "sw", "frontdiag", "diag"} & token_set:
        return "frontDiag"
    if {"side", "left", "right", "east", "west", "profile"} & token_set:
        return "side"
    if {"front", "down", "south"} & token_set:
        return "front"
    return "front"


def sector_to_horizontal_tier(horizontal: str) -> str:
    """Map a 16-sector generation target back to the current 5-tier art refs."""
    if horizontal in MATRIX_HORIZONTAL_TIERS:
        return horizontal
    if not re.fullmatch(r"s\d+", str(horizontal)):
        return "front"
    index = int(str(horizontal)[1:]) % 16
    if index in {15, 0, 1}:
        return "front"
    if index in {2, 3}:
        return "frontDiag"
    if index in {4, 5}:
        return "side"
    if index in {6, 7}:
        return "backDiag"
    if index in {8}:
        return "back"
    if index in {9, 10}:
        return "backDiag"
    if index in {11, 12}:
        return "side"
    return "frontDiag"


def infer_frame_index(path: Path) -> int:
    numbers = re.findall(r"\d+", path.stem)
    return int(numbers[-1]) if numbers else 0


def infer_origin(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).parts[0]
    except Exception:
        return "unknown"


def infer_tags(action: str, origin: str, ext: str) -> list[str]:
    tags = ["alpecca"]
    normalized_origin = origin.lower().replace(" ", "-")
    tags.append(normalized_origin)
    if action in {"identity", "rig"} or normalized_origin in {"master-sheets", "live2d-model"}:
        tags.append("identity-lock")
    if action == "walk":
        tags.append("movement-reference")
    if action in {"expression", "talk"}:
        tags.append("expression-reference")
    if ext in IMAGE_EXTS:
        tags.append("image")
    else:
        tags.append("live2d-metadata")
    return sorted(set(tags))


def approval_for(origin: str, action: str) -> str:
    normalized = origin.lower()
    if normalized in {"master sheets", "live2d model"}:
        return "approved-reference"
    if action in {"walk", "expression", "pose", "rest", "wave"}:
        return "reference"
    return "catalogued"


def sha1_for(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def image_metadata(path: Path) -> tuple[int | None, int | None, bool, dict | None]:
    if path.suffix.lower() not in IMAGE_EXTS:
        return None, None, False, None
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
            has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
            bounds = None
            if has_alpha:
                alpha = image.convert("RGBA").getchannel("A")
                bbox = alpha.getbbox()
                if bbox:
                    x0, y0, x1, y1 = bbox
                    bounds = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
            return width, height, has_alpha, bounds
    except Exception:
        return None, None, False, None


def canonical_name(record_id: str, action: str, vertical: str, horizontal: str, frame_index: int, ext: str) -> str:
    frame = frame_index if frame_index > 0 else int(record_id.rsplit("-", 1)[-1])
    return f"Alpecca_{action}_{vertical}_{horizontal}_{frame:04d}{ext if ext in IMAGE_EXTS else '.png'}"


def tag_lookup_keys(record: SourceRecord) -> list[str]:
    return [
        record.id,
        record.sourcePath,
        str(Path(record.sourcePath).as_posix()),
        record.fileName,
    ]


def apply_manual_tags(record: SourceRecord, manual_tags: dict) -> SourceRecord:
    tags = manual_tags.get("records", manual_tags)
    override = None
    for key in tag_lookup_keys(record):
        if isinstance(tags, dict) and key in tags:
            override = tags[key]
            break
    if not isinstance(override, dict):
        return record

    for attr in ("action", "verticalTier", "horizontalTier", "approvalStatus", "notes"):
        if attr in override and override[attr]:
            setattr(record, attr, override[attr])
    if isinstance(override.get("identityTags"), list):
        record.identityTags = sorted(set(str(tag) for tag in override["identityTags"]))
    elif isinstance(override.get("addTags"), list):
        record.identityTags = sorted(set([*record.identityTags, *(str(tag) for tag in override["addTags"])]))
    record.tagConfidence = str(override.get("tagConfidence") or "manual")
    record.needsHumanTag = bool(override.get("needsHumanTag", False))
    record.suggestedCanonicalName = canonical_name(
        record.id,
        record.action,
        record.verticalTier,
        record.horizontalTier,
        record.frameIndex,
        record.ext,
    )
    return record


def needs_human_tag(action: str, horizontal: str, origin: str) -> bool:
    if origin.lower() in {"master sheets", "movement sets", "actions", "poses", "live2d model"}:
        return horizontal == "front"
    return action in {"reference", "pose", "walk", "identity", "rig"}


def build_source_manifest(source_root: Path, library_root: Path, include_hashes: bool) -> list[SourceRecord]:
    manual_tags = load_json(library_root / "source_tags.json", {})
    records: list[SourceRecord] = []
    for index, path in enumerate(source_files(source_root), start=1):
        stat = path.stat()
        tokens = tokens_for(path, source_root)
        action = infer_action(tokens)
        vertical = infer_vertical(tokens)
        horizontal = infer_horizontal(tokens)
        origin = infer_origin(path, source_root)
        ext = path.suffix.lower()
        width, height, has_alpha, alpha_bounds = image_metadata(path)
        record_id = f"src-{index:05d}"
        record = SourceRecord(
            id=record_id,
            sourcePath=str(path),
            sourceRoot=str(source_root),
            folder=str(path.parent.relative_to(source_root)),
            fileName=path.name,
            ext=ext,
            sizeBytes=stat.st_size,
            modifiedUtc=datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
            action=action,
            verticalTier=vertical,
            horizontalTier=horizontal,
            frameIndex=infer_frame_index(path),
            approvalStatus=approval_for(origin, action),
            origin=origin,
            identityTags=infer_tags(action, origin, ext),
            notes="Stage 1 catalog entry; not a runtime web asset.",
            width=width,
            height=height,
            hasAlpha=has_alpha,
            alphaBounds=alpha_bounds,
            suggestedCanonicalName=canonical_name(record_id, action, vertical, horizontal, infer_frame_index(path), ext),
            tagConfidence="folder",
            needsHumanTag=needs_human_tag(action, horizontal, origin),
            sha1=sha1_for(path) if include_hashes else None,
        )
        record = apply_manual_tags(record, manual_tags)
        records.append(record)

    library_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "sourceRoot": str(source_root),
        "libraryRoot": str(library_root),
        "runtimePolicy": "Do not serve these files directly. Compile approved strips into browser atlases.",
        "matrixContract": {
            "verticalTiers": list(VERTICAL_TIERS),
            "horizontalTiers": list(MATRIX_HORIZONTAL_TIERS),
            "viewSectors16": list(VIEW_SECTORS_16),
            "runtimeKey": "action + verticalTier + viewSector16 + mirrored + frameCount",
            "sourceNamingTarget": "Alpecca_[Action]_[Vertical]_[Horizontal]_[Frame].png",
        },
        "records": [asdict(record) for record in records],
    }
    (library_root / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return records


def choose_first(
    records: list[SourceRecord],
    *,
    action: str | None = None,
    horizontal: str | None = None,
    tag: str | None = None,
    exclude_ids: set[str] | None = None,
) -> SourceRecord | None:
    exclude_ids = exclude_ids or set()
    for record in records:
        if record.id in exclude_ids:
            continue
        if action and record.action != action:
            continue
        if horizontal and record.horizontalTier != horizontal:
            continue
        if tag and tag not in record.identityTags:
            continue
        return record
    return None


def choose_reference_slot(
    records: list[SourceRecord],
    used_ids: set[str],
    *,
    action: str,
    horizontal: str,
    tag: str | None = None,
    fallback_action: str | None = None,
    fallback_tag: str | None = None,
) -> tuple[SourceRecord | None, str, str]:
    exact = choose_first(records, action=action, horizontal=horizontal, tag=tag, exclude_ids=used_ids)
    if exact:
        return exact, "exact", ""

    fallback = choose_first(records, action=fallback_action or action, tag=tag or fallback_tag, exclude_ids=used_ids)
    if fallback:
        return (
            fallback,
            "folder-fallback",
            f"Needs human direction tag for requested {horizontal}; source file names are not descriptive.",
        )

    fallback_by_tag = choose_first(records, tag=tag or fallback_tag, exclude_ids=used_ids)
    if fallback_by_tag:
        return (
            fallback_by_tag,
            "tag-fallback",
            f"Needs human action and direction tag for requested {action}/{horizontal}.",
        )

    return None, "missing", "No source candidate found."


def build_reference_board(records: list[SourceRecord], library_root: Path) -> dict:
    used_ids: set[str] = set()
    slot_specs = {
        "frontIdentity": {"action": "identity", "horizontal": "front", "tag": "identity-lock"},
        "sideIdentity": {"action": "identity", "horizontal": "side", "tag": "identity-lock"},
        "backIdentity": {"action": "identity", "horizontal": "back", "tag": "identity-lock"},
        "diagonalIdentity": {"action": "identity", "horizontal": "frontDiag", "tag": "identity-lock"},
        "movementFront": {"action": "walk", "horizontal": "front"},
        "movementFrontDiag": {"action": "walk", "horizontal": "frontDiag"},
        "movementSide": {"action": "walk", "horizontal": "side"},
        "movementBackDiag": {"action": "walk", "horizontal": "backDiag"},
        "movementBack": {"action": "walk", "horizontal": "back"},
        "expressionMouth": {"action": "expression", "horizontal": "front", "fallback_action": "rig", "fallback_tag": "identity-lock"},
        "talkMouth": {"action": "talk", "horizontal": "front", "fallback_action": "rig", "fallback_tag": "identity-lock"},
        "restPose": {"action": "rest", "horizontal": "frontDiag", "fallback_action": "sit"},
    }
    slots: dict[str, dict] = {}
    missing: list[str] = []
    for name, spec in slot_specs.items():
        record, confidence, warning = choose_reference_slot(records, used_ids, **spec)
        if record is None:
            missing.append(name)
            continue
        used_ids.add(record.id)
        slots[name] = {
            "sourceId": record.id,
            "sourcePath": record.sourcePath,
            "action": record.action,
            "requestedAction": spec["action"],
            "verticalTier": record.verticalTier,
            "horizontalTier": record.horizontalTier,
            "requestedHorizontalTier": spec["horizontal"],
            "approvalStatus": record.approvalStatus,
            "confidence": confidence,
            "warning": warning,
        }

    board = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "goal": "Stage 3 identity lock for 400+ matrix animation generation.",
        "heightReferenceMeters": 1.704,
        "anchor": "bottom-center feet",
        "slots": slots,
        "missingSlots": missing,
    }
    (library_root / "reference_board.json").write_text(json.dumps(board, indent=2), encoding="utf-8")
    return board


def write_tagging_template(records: list[SourceRecord], board: dict, library_root: Path, template_limit: int) -> dict:
    template_path = library_root / "source_tags_template.json"
    pending = [
        record
        for record in records
        if record.needsHumanTag or record.tagConfidence != "manual"
    ]
    slot_sources = {
        slot.get("sourceId")
        for slot in (board.get("slots") or {}).values()
        if isinstance(slot, dict) and slot.get("confidence") != "exact"
    }
    limited_pending = pending[:template_limit] if template_limit > 0 else pending
    candidate_ids = {record.id for record in limited_pending} | {source_id for source_id in slot_sources if source_id}
    candidate_records = [record for record in records if record.id in candidate_ids]
    template = {
        "schemaVersion": 1,
        "instructions": [
            "Copy this file to source_tags.json, then edit only the records that need correction.",
            "Valid verticalTier values: low, eye, high.",
            "Valid horizontalTier values: front, frontDiag, side, backDiag, back.",
            "Set approvalStatus to approved-reference for identity-locked source art.",
            "Keep source art here; do not copy the 40GB library into public web assets.",
        ],
        "records": {
            record.id: {
                "sourcePath": record.sourcePath,
                "fileName": record.fileName,
                "current": {
                    "action": record.action,
                    "verticalTier": record.verticalTier,
                    "horizontalTier": record.horizontalTier,
                    "approvalStatus": record.approvalStatus,
                    "identityTags": record.identityTags,
                },
                "action": record.action,
                "verticalTier": record.verticalTier,
                "horizontalTier": record.horizontalTier,
                "approvalStatus": record.approvalStatus,
                "addTags": [],
                "notes": record.notes,
                "needsHumanTag": False,
            }
            for record in candidate_records
        },
    }
    template_path.write_text(json.dumps(template, indent=2), encoding="utf-8")
    return template


def build_stage1_summary(records: list[SourceRecord], board: dict, library_root: Path) -> dict:
    by_origin = Counter(record.origin for record in records)
    by_action = Counter(record.action for record in records)
    by_horizontal = Counter(record.horizontalTier for record in records)
    manual_count = sum(1 for record in records if record.tagConfidence == "manual")
    exact_slots = sum(1 for slot in (board.get("slots") or {}).values() if slot.get("confidence") == "exact")
    fallback_slots = sum(1 for slot in (board.get("slots") or {}).values() if slot.get("confidence") != "exact")
    review_records = [
        {
            "id": record.id,
            "origin": record.origin,
            "action": record.action,
            "horizontalTier": record.horizontalTier,
            "verticalTier": record.verticalTier,
            "fileName": record.fileName,
            "sourcePath": record.sourcePath,
            "reason": "hash-named or folder-inferred source needs visual direction/action approval",
        }
        for record in records
        if record.needsHumanTag
    ][:120]
    summary = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "stage": "stage-1-source-library",
        "sourceCount": len(records),
        "manualTagCount": manual_count,
        "needsHumanTagCount": sum(1 for record in records if record.needsHumanTag),
        "exactReferenceSlots": exact_slots,
        "fallbackReferenceSlots": fallback_slots,
        "missingReferenceSlots": board.get("missingSlots", []),
        "byOrigin": dict(by_origin),
        "byAction": dict(by_action),
        "byHorizontalTier": dict(by_horizontal),
        "reviewQueue": review_records,
        "nextGate": "Fill source_tags.json from source_tags_template.json after reviewing contact sheets.",
    }
    (library_root / "stage1_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def render_contact_sheets(records: list[SourceRecord], library_root: Path, max_items: int = 120) -> list[str]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return []

    out_dir = library_root / "contact_sheets"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()

    grouped: dict[tuple[str, str], list[SourceRecord]] = {}
    for record in records:
        if record.ext.lower() not in IMAGE_EXTS:
            continue
        grouped.setdefault((record.origin, record.action), []).append(record)

    generated: list[str] = []
    thumb = 168
    label_h = 54
    gap = 12
    cols = 5
    font = ImageFont.load_default()

    for (origin, action), items in sorted(grouped.items()):
        items = items[:max_items]
        rows = max(1, math.ceil(len(items) / cols))
        sheet = Image.new("RGB", (cols * (thumb + gap) + gap, rows * (thumb + label_h + gap) + gap), "#f2f4f6")
        draw = ImageDraw.Draw(sheet)
        for index, record in enumerate(items):
            col = index % cols
            row = index // cols
            x = gap + col * (thumb + gap)
            y = gap + row * (thumb + label_h + gap)
            try:
                with Image.open(record.sourcePath) as image:
                    image = image.convert("RGBA")
                    image.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
                    checker = Image.new("RGBA", (thumb, thumb), "#ffffff")
                    cx = x + (thumb - image.width) // 2
                    cy = y + (thumb - image.height) // 2
                    sheet.paste(checker.convert("RGB"), (x, y))
                    sheet.paste(image.convert("RGB"), (cx, cy), image)
            except Exception:
                draw.rectangle((x, y, x + thumb, y + thumb), fill="#222222")
                draw.text((x + 8, y + 8), "unreadable", fill="#ffffff", font=font)
            draw.rectangle((x, y + thumb, x + thumb, y + thumb + label_h), fill="#101820")
            label = f"{record.id}  {record.action}/{record.horizontalTier}\n{record.width or '?'}x{record.height or '?'}  {record.approvalStatus}\n{record.fileName[:30]}"
            draw.multiline_text((x + 6, y + thumb + 5), label, fill="#d8f7ff", font=font, spacing=2)
        out_path = out_dir / f"{slug(origin)}__{slug(action)}.png"
        sheet.save(out_path)
        generated.append(str(out_path))

    index = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "sheets": generated,
        "labelFormat": "source id, inferred action/direction, dimensions, approval status, filename",
    }
    (out_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return generated


def animation_source_family(folder: str) -> str:
    if folder.startswith("iso_"):
        return "iso"
    if folder.startswith("gpt16_"):
        return "gpt16"
    if folder.startswith("gpt3d_"):
        return "gpt3d"
    if folder.startswith("gpt_"):
        return "gpt"
    return re.split(r"[\s_]+", folder)[0] or "legacy"


def atlas_frame_count(runtime_root: Path, folder: str) -> int:
    atlas_path = runtime_root / folder / "atlas.json"
    if not atlas_path.exists():
        return 0
    try:
        atlas = json.loads(atlas_path.read_text(encoding="utf-8"))
        return len(atlas.get("frames", {}))
    except Exception:
        return 0


def visual_meta(runtime_root: Path, folder: str) -> dict:
    meta_path = runtime_root / folder / "visual.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def runtime_status(action: str, folder: str) -> str:
    if folder.startswith("gpt3d_walk_"):
        return "needs-regeneration"
    if action == "walk" and folder.startswith("iso_"):
        return "approved"
    if folder.startswith("gpt16_"):
        return "runtime-ok"
    if action in {"inspect", "careful", "rest", "sleep"}:
        return "runtime-ok"
    return "approved"


def runtime_layer_plan(action: str) -> dict:
    roles = ["base-body", "contact-shadow", "depth-proxy", "floor-reflection"]
    if action in {"talk", "listen"}:
        roles.insert(1, "expression-overlay")
        roles.insert(2, "mouth-eye-overlay")
    return {
        "roles": roles,
        "expressionOverlay": "expression-overlay" in roles,
        "mouthEyeOverlay": "mouth-eye-overlay" in roles,
        "contactShadow": True,
        "depthProxy": True,
        "floorReflection": True,
        "transitionSeconds": 0.065,
    }


def runtime_contact_frames(action: str, frame_count: int) -> list[int]:
    if action != "walk" or frame_count <= 0:
        return []
    stride = max(1, frame_count // 4)
    return sorted({0, stride, stride * 2, stride * 3})


def build_runtime_matrix_manifest(runtime_root: Path) -> dict:
    records = []
    for action, horizontal_map in MATRIX_FALLBACKS.items():
        for vertical in RUNTIME_VERTICAL_TIERS:
            for horizontal in MATRIX_HORIZONTAL_TIERS:
                state = horizontal_map[horizontal]
                folder = STATE_FOLDERS[state]
                meta = visual_meta(runtime_root, folder)
                frame_count = atlas_frame_count(runtime_root, folder)
                records.append(
                    {
                        "key": f"{action}_{vertical}_{horizontal}",
                        "action": action,
                        "verticalTier": vertical,
                        "horizontalTier": horizontal,
                        "mirrorPolicy": "use-view-matrix-flipX-for-negative-relative-yaw",
                        "state": state,
                        "folder": folder,
                        "frameCount": frame_count,
                        "sourceFamily": animation_source_family(folder),
                        "approvalStatus": runtime_status(action, folder),
                        "heightClass": "standing" if action not in {"rest", "sleep"} else "pose",
                        "visualScale": meta.get("visualScale"),
                        "spriteY": meta.get("spriteY"),
                        "footAnchor": "bottom-center",
                        "contactFrameIndexes": runtime_contact_frames(action, frame_count),
                        "layerPlan": runtime_layer_plan(action),
                        "depthProxy": "fallback-alpha-silhouette-plane",
                        "notes": "Stage 2 fallback atlas. Replace with matrix-specific compiled art after QA.",
                    }
                )

    manifest = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "assetRoot": "/assets/alpecca-optimized",
        "runtimePolicy": "Browser loads compiled atlas folders only; source library stays outside public assets.",
        "records": records,
    }
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "runtime_matrix_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def board_reference_ids(board: dict, preferred_slots: list[str]) -> list[str]:
    slots = board.get("slots") or {}
    ids: list[str] = []
    for slot_name in preferred_slots:
        slot = slots.get(slot_name)
        if isinstance(slot, dict) and slot.get("sourceId"):
            ids.append(slot["sourceId"])
    return ids


def generation_reference_slots(action: str, horizontal: str) -> list[str]:
    horizontal_ref = sector_to_horizontal_tier(horizontal)
    direction_slot = {
        "front": "movementFront",
        "frontDiag": "movementFrontDiag",
        "side": "movementSide",
        "backDiag": "movementBackDiag",
        "back": "movementBack",
    }.get(horizontal_ref, "movementFront")
    identity_slot = {
        "front": "frontIdentity",
        "frontDiag": "diagonalIdentity",
        "side": "sideIdentity",
        "backDiag": "diagonalIdentity",
        "back": "backIdentity",
    }.get(horizontal_ref, "frontIdentity")

    slots = [identity_slot, direction_slot]
    if action in {
        "talk",
        "listen",
        "surprised",
        "shy",
        "curious",
        "worried",
        "amused",
        "thinking",
        "mouthOverlay",
        "eyeOverlay",
        "lipQuiver",
        "fingerStare",
        "shyGlance",
        "softStartle",
        "selfCritique",
        "curiousFocus",
    }:
        slots.extend(["expressionMouth", "talkMouth"])
    if action == "headHairOverlay":
        slots.extend(["expressionMouth", "talkMouth"])
    if action == "haloOverlay":
        slots.append(identity_slot)
    if action == "shadowOverlay":
        slots.append("scaleRuler")
    if action in {"rest", "sleep", "wake"}:
        slots.append("restPose")
    return list(dict.fromkeys(slots))


def build_generation_queue(board: dict, runtime_manifest: dict, library_root: Path) -> dict:
    runtime_by_key = {
        record.get("key"): record
        for record in runtime_manifest.get("records", [])
        if isinstance(record, dict) and record.get("key")
    }
    targets: list[dict] = []

    def add_target(
        *,
        batch: dict,
        action: str,
        vertical: str,
        horizontal: str,
        frame_count: int,
        direction: str | None = None,
    ) -> None:
        key = f"{action}_{vertical}_{horizontal}"
        output_key = f"{action}_{vertical}_{direction}" if direction else key
        target_kind = batch.get("targetKind", "matrix-atlas")
        output_prefix = "matrix" if target_kind == "matrix-atlas" else "layer"
        runtime = runtime_by_key.get(key, {})
        reference_horizontal = sector_to_horizontal_tier(horizontal)
        reference_slots = generation_reference_slots(action, horizontal)
        targets.append(
            {
                "id": f"gen-{len(targets) + 1:04d}",
                "batch": batch["batch"],
                "batchName": batch["name"],
                "priority": batch["priority"],
                "targetKind": target_kind,
                "layerRole": batch.get("layerRole"),
                "action": action,
                "verticalTier": vertical,
                "horizontalTier": horizontal,
                "viewSector16": horizontal if horizontal in VIEW_SECTORS_16 else None,
                "referenceHorizontalTier": reference_horizontal,
                "movementDirection": direction,
                "targetFrameCount": frame_count,
                "targetArtPieceCount": frame_count,
                "targetSlotPixels": 4096,
                "minimumSourceSlotPixels": 4096,
                "runtimeSlotPixels": 512,
                "outputFolderSuggestion": f"{output_prefix}_{output_key}",
                "status": "planned-generation",
                "generationRequired": True,
                "existingRuntimeFallback": runtime.get("folder"),
                "fallbackApprovalStatus": runtime.get("approvalStatus"),
                "sourceUsePolicy": (
                    "Use existing Alpecca art only as identity, direction, and expression reference. "
                    "Generate a new coherent production strip for this target; do not collage loose frames "
                    "or promote inconsistent existing movement art directly into runtime."
                ),
                "seedReferenceSlots": reference_slots,
                "seedReferenceSourceIds": board_reference_ids(board, reference_slots),
                "qualityGates": GENERATION_QUALITY_GATES,
                "layerSeparation": {
                    "baseBodyMustExclude": ["halo", "floor-shadow", "drop-shadow", "glow-smear", "contact-shadow"],
                    "separateLayers": ["halo-overlay", "shadow-depth-overlay", "mouth-eye-overlay", "expression-overlay"],
                    "runtimeIntent": "Base body art stays transparent and clean; halo and shadows are rendered independently.",
                },
                "promotionGate": (
                    "Normalize to atlas.json, spritesheet.png, lossless spritesheet.webp, visual.json, "
                    "and matrix metadata; approve only after preview and in-HQ QA."
                ),
            }
        )

    for batch in GENERATION_BATCHES:
        if "walkDirections" in batch:
            for vertical in batch["verticals"]:
                for _state, horizontal, direction in batch["walkDirections"]:
                    add_target(
                        batch=batch,
                        action="walk",
                        vertical=vertical,
                        horizontal=horizontal,
                        direction=direction,
                        frame_count=int(batch["frameCount"]),
                    )
            continue

        for action in batch["actions"]:
            for vertical in batch["verticals"]:
                for horizontal in batch["horizontals"]:
                    frame_spec = batch["frameCount"]
                    frame_count = int(frame_spec[action] if isinstance(frame_spec, dict) else frame_spec)
                    add_target(
                        batch=batch,
                        action=action,
                        vertical=vertical,
                        horizontal=horizontal,
                        frame_count=frame_count,
                    )

    queue = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "goal": "Generate the missing Alpecca production art required for advanced 2D-in-3D presence.",
        "targetCountMeaning": "strip targets; each strip contains multiple art pieces/frames",
        "artPieceTargetCount": sum(int(target.get("targetArtPieceCount") or target.get("targetFrameCount") or 0) for target in targets),
        "minimumArtPieceGoal": 400,
        "pieceDefinition": "one normalized frame slot or overlay slot inside an approved generated strip",
        "policy": {
            "designLock": "ALPECCA_DESIGN_LOCK.md",
            "existingArtRole": "identity-lock and reference material",
            "newArtRole": "required production animation for missing matrix views, motion phases, and emotion overlays",
            "runtimeRule": "ship compiled approved atlases only; never load the large source-art library in the browser",
            "consistencyRule": "generate complete strips in one pass to reduce identity and leg-phase drift",
        },
        "targetCount": len(targets),
        "batches": GENERATION_BATCHES,
        "targets": targets,
    }
    (library_root / "generation_queue.json").write_text(json.dumps(queue, indent=2), encoding="utf-8")
    return queue


def write_readme(
    library_root: Path,
    source_root: Path,
    source_count: int,
    board: dict,
    summary: dict,
    contact_sheets: list[str],
    generation_queue: dict,
) -> None:
    text = f"""# Alpecca Animation Source Library

Generated: {utc_now()}

This folder is the non-runtime catalog for Alpecca's future 400+ image 2D-in-3D
animation source pool. It is intentionally outside `apps/house-hq/public` and is
ignored by git with the rest of `data/`.

- Source root: `{source_root}`
- Catalogued source files: `{source_count}`
- Reference board slots: `{len(board.get("slots", {}))}`
- Missing board slots: `{", ".join(board.get("missingSlots", [])) or "none"}`
- Needs human tagging: `{summary.get("needsHumanTagCount", 0)}`
- Contact sheets: `{len(contact_sheets)}`
- Planned generation targets: `{generation_queue.get("targetCount", 0)}`

Runtime rule: compile approved strips into atlas folders with `atlas.json`,
`spritesheet.png`, `spritesheet.webp`, `visual.json`, and matrix metadata before
the House HQ loads them.

## Generation Policy

Existing Alpecca art is not enough for the final goal by itself. It should be
used as identity-lock, expression, direction, and pose reference. Missing camera
tiers, full walk loops, rest-nook states, cinematic reactions, and expression
overlays must be generated as new complete strips, then normalized and QA'd
before runtime promotion.

The generated plan is in `generation_queue.json`. Each target records the
action, camera tier, yaw tier, frame count, source references, and quality gates.

## Stage 1 Tagging Workflow

1. Open `contact_sheets/*.png` and use the labels to identify each useful image.
2. Copy `source_tags_template.json` to `source_tags.json`.
3. Edit `source_tags.json` for the images you approve:
   - `action`: identity, walk, talk, expression, rest, pose, wave, inspect
   - `verticalTier`: low, eye, high
   - `horizontalTier`: front, frontDiag, side, backDiag, back
   - `approvalStatus`: approved-reference, reference, qa-only, reject
4. Re-run `python scripts\\build_alpecca_animation_library.py`.
5. Stage 2/3 should only use exact or manually approved reference slots.
"""
    (library_root / "README.md").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Catalog Alpecca source art and runtime matrix atlas fallbacks.")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--library-root", type=Path, default=DEFAULT_LIBRARY_ROOT)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--hash", action="store_true", help="Compute sha1 for source files. Off by default for huge libraries.")
    parser.add_argument("--template-limit", type=int, default=200, help="Maximum records in source_tags_template.json; 0 means all.")
    args = parser.parse_args()

    if not args.source_root.exists():
        raise SystemExit(f"Source root not found: {args.source_root}")
    if not args.runtime_root.exists():
        raise SystemExit(f"Runtime atlas root not found: {args.runtime_root}")

    records = build_source_manifest(args.source_root, args.library_root, args.hash)
    board = build_reference_board(records, args.library_root)
    tag_template = write_tagging_template(records, board, args.library_root, args.template_limit)
    contact_sheets = render_contact_sheets(records, args.library_root)
    summary = build_stage1_summary(records, board, args.library_root)
    runtime_manifest = build_runtime_matrix_manifest(args.runtime_root)
    generation_queue = build_generation_queue(board, runtime_manifest, args.library_root)
    write_readme(args.library_root, args.source_root, len(records), board, summary, contact_sheets, generation_queue)

    print(f"Catalogued {len(records)} source file(s) -> {args.library_root / 'source_manifest.json'}")
    print(f"Reference board slots: {len(board.get('slots', {}))}; missing: {', '.join(board.get('missingSlots', [])) or 'none'}")
    print(f"Tagging template records: {len(tag_template.get('records', {}))} -> {args.library_root / 'source_tags_template.json'}")
    print(f"Contact sheets: {len(contact_sheets)} -> {args.library_root / 'contact_sheets'}")
    print(f"Needs human tags: {summary.get('needsHumanTagCount', 0)} -> {args.library_root / 'stage1_summary.json'}")
    print(f"Runtime matrix records: {len(runtime_manifest['records'])} -> {args.runtime_root / 'runtime_matrix_manifest.json'}")
    print(f"Generation targets: {generation_queue.get('targetCount', 0)} -> {args.library_root / 'generation_queue.json'}")


if __name__ == "__main__":
    main()
