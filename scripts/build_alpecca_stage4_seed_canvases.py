"""Create Stage 4 seed/edit canvases for Alpecca generation targets.

This prepares generation-ready transparent strips from approved reference art.
It does not approve or ship assets. The output lives in the non-runtime source
library so generated art can be reviewed before Stage 5 promotion.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_ROOT = REPO_ROOT / "data" / "alpecca_art_source"
DEFAULT_STAGE4_ROOT = DEFAULT_LIBRARY_ROOT / "stage4_generation_batches"
DEFAULT_SOURCE_MANIFEST = DEFAULT_LIBRARY_ROOT / "source_manifest.json"

HORIZONTAL_SLOT_FALLBACKS = {
    "front": ("front", "frontDiag", "side"),
    "frontDiag": ("frontDiag", "front", "side"),
    "side": ("side", "frontDiag", "backDiag"),
    "backDiag": ("backDiag", "back", "side"),
    "back": ("back", "backDiag", "side"),
}

SECTOR_16_REFERENCE_TIERS = {
    "s0": "front",
    "s1": "front",
    "s2": "frontDiag",
    "s3": "frontDiag",
    "s4": "side",
    "s5": "backDiag",
    "s6": "backDiag",
    "s7": "back",
    "s8": "back",
    "s9": "back",
    "s10": "backDiag",
    "s11": "backDiag",
    "s12": "side",
    "s13": "frontDiag",
    "s14": "frontDiag",
    "s15": "front",
}

ACTION_SLOT_FALLBACKS = {
    "idle": ("identity", "walk", "pose"),
    "listen": ("identity", "talk", "expression", "pose"),
    "talk": ("talk", "expression", "identity", "pose"),
    "walk": ("walk", "identity", "pose"),
    "wave": ("wave", "pose", "identity"),
    "inspect": ("inspect", "pose", "identity"),
    "careful": ("crouch", "inspect", "pose", "identity"),
    "rest": ("rest", "sit", "pose", "identity"),
    "sleep": ("rest", "sit", "pose", "identity"),
    "wake": ("sit", "rest", "pose", "identity"),
}

LAYER_ACTIONS = {"mouthOverlay", "eyeOverlay", "headHairOverlay", "lipQuiver", "fingerStare", "shyGlance", "softStartle", "selfCritique", "curiousFocus"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_near_background(pixel: tuple[int, int, int, int], corner: tuple[int, int, int]) -> bool:
    r, g, b, a = pixel
    if a == 0:
        return True
    bright_white = r > 244 and g > 244 and b > 244 and (max(r, g, b) - min(r, g, b)) < 22
    close_to_corner = abs(r - corner[0]) + abs(g - corner[1]) + abs(b - corner[2]) < 34 and min(r, g, b) > 218
    return bright_white or close_to_corner


def flood_remove_edge_background(image: Image.Image) -> Image.Image:
    """Remove only background connected to image edges, preserving white clothing."""
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    if width <= 0 or height <= 0:
        return rgba
    corners = [
        rgba.getpixel((0, 0))[:3],
        rgba.getpixel((width - 1, 0))[:3],
        rgba.getpixel((0, height - 1))[:3],
        rgba.getpixel((width - 1, height - 1))[:3],
    ]
    corner = tuple(sorted(corners)[len(corners) // 2])
    seen = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))

    while queue:
        x, y = queue.popleft()
        if x < 0 or y < 0 or x >= width or y >= height:
            continue
        offset = y * width + x
        if seen[offset]:
            continue
        seen[offset] = 1
        if not is_near_background(pixels[x, y], corner):
            continue
        r, g, b, _a = pixels[x, y]
        pixels[x, y] = (r, g, b, 0)
        queue.append((x + 1, y))
        queue.append((x - 1, y))
        queue.append((x, y + 1))
        queue.append((x, y - 1))
    return rgba


def remove_background_white_islands(image: Image.Image) -> Image.Image:
    """Remove neutral paper-white islands left between limbs after edge flood.

    Alpecca's outfit is warm ivory with linework and blue shadows. This removes
    only very bright, low-saturation paper/background pixels so stockings and
    hoodie forms remain readable in the seed.
    """
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            very_bright = r >= 247 and g >= 247 and b >= 247
            low_saturation = max(r, g, b) - min(r, g, b) <= 9
            if very_bright and low_saturation:
                pixels[x, y] = (r, g, b, 0)
    return rgba


def remove_large_plain_paper_fields(image: Image.Image) -> Image.Image:
    """Remove broad low-detail paper fields, especially the wedge between legs."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    mask = Image.new("L", rgba.size, 0)
    mask_pixels = mask.load()
    pixels = rgba.load()
    for y in range(height):
        if y < height * 0.5:
            continue
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            near_paper = 232 <= r <= 246 and 232 <= g <= 246 and 232 <= b <= 246 and max(r, g, b) - min(r, g, b) <= 16
            if near_paper:
                mask_pixels[x, y] = 255
    # Erosion keeps only broad regions; narrow white stockings/trim lose the mask.
    eroded = mask.filter(ImageFilter.MinFilter(17))
    eroded_pixels = eroded.load()
    for y in range(height):
        if y < height * 0.54:
            continue
        for x in range(width):
            if eroded_pixels[x, y] > 0:
                r, g, b, _a = pixels[x, y]
                pixels[x, y] = (r, g, b, 0)
    return rgba


def trim_alpha(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if not bbox:
        return rgba
    return rgba.crop(bbox)


def keep_largest_alpha_component(image: Image.Image, alpha_threshold: int = 12) -> Image.Image:
    """Drop disconnected halo/shadow specks so base-body seeds stay clean."""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    alpha = rgba.getchannel("A")
    pixels = alpha.load()
    seen = bytearray(width * height)
    components: list[list[tuple[int, int]]] = []

    for start_y in range(height):
        for start_x in range(width):
            offset = start_y * width + start_x
            if seen[offset] or pixels[start_x, start_y] <= alpha_threshold:
                seen[offset] = 1
                continue
            queue: deque[tuple[int, int]] = deque([(start_x, start_y)])
            component: list[tuple[int, int]] = []
            seen[offset] = 1
            while queue:
                x, y = queue.popleft()
                if pixels[x, y] <= alpha_threshold:
                    continue
                component.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    neighbor_offset = ny * width + nx
                    if seen[neighbor_offset]:
                        continue
                    seen[neighbor_offset] = 1
                    queue.append((nx, ny))
            if component:
                components.append(component)

    if not components:
        return rgba
    largest = max(components, key=len)
    keep = {point for point in largest}
    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    src_pixels = rgba.load()
    out_pixels = out.load()
    for x, y in keep:
        out_pixels[x, y] = src_pixels[x, y]
    return out


def remove_floor_reference_marks(image: Image.Image) -> Image.Image:
    """Remove horizontal floor/contact guide marks from source references.

    Movement-set references sometimes include a long gray floor line between
    feet. That line poisons the generator into baking a shadow/base ring into
    otherwise transparent body frames, so seeds must strip it before Stage 4.
    """
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return rgba
    left, top, right, bottom = bbox
    width = max(1, right - left)
    subject_h = max(1, bottom - top)
    pixels = rgba.load()
    alpha_pixels = alpha.load()
    for y in range(max(top, bottom - int(subject_h * 0.16)), bottom):
        xs = [x for x in range(left, right) if alpha_pixels[x, y] > 10]
        if not xs:
            continue
        row_span = max(xs) - min(xs) + 1
        if row_span / width < 0.48:
            continue
        for x in xs:
            r, g, b, a = pixels[x, y]
            if a <= 0:
                continue
            mx = max(r, g, b)
            mn = min(r, g, b)
            saturation = (mx - mn) / max(1, mx)
            neutral_line = saturation < 0.18 and mx < 252
            thin_dark_line = saturation < 0.30 and mx < 185
            if neutral_line or thin_dark_line:
                pixels[x, y] = (0, 0, 0, 0)
    return rgba


def load_seed_image(path: Path) -> Image.Image:
    raw = Image.open(path)
    has_real_alpha = raw.mode in {"RGBA", "LA"} or "transparency" in raw.info
    source = raw.convert("RGBA")
    source.load()
    alpha_min, alpha_max = source.getchannel("A").getextrema()
    if has_real_alpha and alpha_min < alpha_max:
        cutout = source
    else:
        cutout = flood_remove_edge_background(source)
        cutout = remove_background_white_islands(cutout)
        cutout = remove_large_plain_paper_fields(cutout)
    cutout = keep_largest_alpha_component(cutout)
    cutout = trim_alpha(cutout)
    return cutout


def fit_bottom_center(image: Image.Image, slot_px: int, max_ratio: float = 0.9) -> Image.Image:
    canvas = Image.new("RGBA", (slot_px, slot_px), (0, 0, 0, 0))
    sprite = image.copy()
    max_w = int(slot_px * max_ratio)
    max_h = int(slot_px * max_ratio)
    sprite.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    x = (slot_px - sprite.width) // 2
    y = slot_px - int(slot_px * 0.04) - sprite.height
    canvas.alpha_composite(sprite, (x, y))
    return canvas


def make_seed_strip(seed: Image.Image, frame_count: int, slot_px: int) -> Image.Image:
    strip = Image.new("RGBA", (frame_count * slot_px, slot_px), (0, 0, 0, 0))
    strip.alpha_composite(seed, (0, 0))
    return strip


def make_pose_guide(seed: Image.Image, frame_count: int, slot_px: int) -> Image.Image:
    guide = Image.new("RGBA", (frame_count * slot_px, slot_px), (0, 0, 0, 0))
    ghost = seed.copy()
    alpha = ghost.getchannel("A").point(lambda value: int(value * 0.16))
    ghost.putalpha(alpha)
    draw = ImageDraw.Draw(guide)
    baseline_y = slot_px - int(slot_px * 0.04)
    for index in range(frame_count):
        x = index * slot_px
        guide.alpha_composite(ghost if index else seed, (x, 0))
        draw.line((x, baseline_y, x + slot_px, baseline_y), fill=(110, 220, 255, 72), width=2)
        draw.rectangle((x, 0, x + slot_px - 1, slot_px - 1), outline=(100, 160, 210, 48), width=1)
    return guide


def make_contact_preview(seed: Image.Image, target: dict[str, Any], seed_record: dict[str, Any], out_path: Path) -> None:
    font = ImageFont.load_default()
    width, height = 1400, 760
    canvas = Image.new("RGBA", (width, height), "#08101a")
    draw = ImageDraw.Draw(canvas)
    draw.text((28, 24), f"Alpecca Stage 4 Seed Canvas: {target['matrixKey']}", fill="#f4fbff", font=font)
    draw.text((28, 50), f"{target['action']} / {target['verticalTier']} / {target['horizontalTier']} / {target['frameCount']} frames", fill="#9de9ff", font=font)
    draw.text((28, 76), f"seed: {seed_record.get('id')} {seed_record.get('origin')} {seed_record.get('action')} {seed_record.get('horizontalTier')}", fill="#b8c7d7", font=font)
    draw.text((28, 102), "Design lock: ivory hoodie, black shorts, white full thigh-high stockings, thigh strap, boots, no blue orbs.", fill="#ffd77a", font=font)
    preview = seed.copy()
    preview.thumbnail((420, 560), Image.Resampling.LANCZOS)
    canvas.alpha_composite(preview, (58, 170))
    draw.rectangle((540, 160, 1340, 700), outline="#32506a", width=2)
    y = 184
    for gate in target.get("qualityGates", [])[:10]:
        draw.text((568, y), f"- {gate}", fill="#d7e6f7", font=font)
        y += 38
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, quality=94)


def image_size(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    try:
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def expected_seed_size(target: dict[str, Any]) -> tuple[int, int]:
    frame_count = int(target["frameCount"])
    slot_px = int(target["slotPixels"])
    return (frame_count * slot_px, slot_px)


def target_needs_seed_rebuild(target_dir: Path, target: dict[str, Any]) -> bool:
    seed_canvas = target_dir / "incoming" / "seed_canvas.png"
    pose_guide = target_dir / "incoming" / "pose_guides.png"
    generation_request = target_dir / "generation_request.json"
    if not seed_canvas.exists() or not pose_guide.exists() or not generation_request.exists():
        return True
    expected_size = expected_seed_size(target)
    return image_size(seed_canvas) != expected_size or image_size(pose_guide) != expected_size


def records_by_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(record.get("id")): record for record in records}


def record_score(record: dict[str, Any], target: dict[str, Any], seed_ids: set[str]) -> tuple[int, int, int, int]:
    action = str(record.get("action"))
    horizontal = str(record.get("horizontalTier"))
    origin = str(record.get("origin"))
    width = int(record.get("width") or 0)
    height = int(record.get("height") or 0)
    ratio = width / max(1, height)
    target_action = str(target.get("action"))
    target_horizontal = str(
        target.get("referenceHorizontalTier")
        or SECTOR_16_REFERENCE_TIERS.get(str(target.get("horizontalTier")))
        or target.get("horizontalTier")
    )
    action_order = ACTION_SLOT_FALLBACKS.get(target_action, (target_action, "identity", "pose", "walk"))
    horizontal_order = HORIZONTAL_SLOT_FALLBACKS.get(target_horizontal, (target_horizontal, "front"))
    action_score = 100 - (action_order.index(action) * 10 if action in action_order else 80)
    horizontal_score = 100 - (horizontal_order.index(horizontal) * 10 if horizontal in horizontal_order else 70)
    seed_score = 25 if str(record.get("id")) in seed_ids else 0
    single_score = 24 if 0.45 <= ratio <= 0.95 and height >= 900 else 0
    origin_score = 20 if origin in {"Movement sets", "Poses"} else 8 if origin == "Master sheets" else 0
    return (action_score + horizontal_score + seed_score + single_score + origin_score, single_score, origin_score, -abs(width - height))


def choose_seed_record(target: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    records = [record for record in manifest.get("records", []) if record.get("ext", "").lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    by_id = records_by_id(records)
    seed_ids = set(str(item) for item in target.get("seedReferenceSourceIds", []))

    preferred_actions = ACTION_SLOT_FALLBACKS.get(str(target.get("action")), (str(target.get("action")), "identity", "pose", "walk"))
    if str(target.get("action")) in LAYER_ACTIONS:
        preferred_actions = ("talk", "expression", "identity", "pose")
    target_horizontal = str(
        target.get("referenceHorizontalTier")
        or SECTOR_16_REFERENCE_TIERS.get(str(target.get("horizontalTier")))
        or target.get("horizontalTier")
    )
    preferred_horizontals = HORIZONTAL_SLOT_FALLBACKS.get(target_horizontal, (target_horizontal, "front"))

    candidates: list[dict[str, Any]] = []
    for record in records:
        if str(record.get("approvalStatus")) in {"reject", "qa-only"}:
            continue
        if str(record.get("action")) not in preferred_actions and str(record.get("id")) not in seed_ids:
            continue
        if str(record.get("horizontalTier")) not in preferred_horizontals and str(record.get("id")) not in seed_ids:
            continue
        candidates.append(record)

    for seed_id in target.get("seedReferenceSourceIds", []):
        record = by_id.get(str(seed_id))
        if record and record not in candidates:
            candidates.append(record)

    if not candidates:
        raise RuntimeError(f"No seed candidate found for {target.get('matrixKey')}")
    return sorted(candidates, key=lambda item: record_score(item, target, seed_ids), reverse=True)[0]


def iter_targets(stage4_root: Path, batch: int | None) -> list[tuple[Path, dict[str, Any]]]:
    pattern = f"batch_{batch:02d}_*/targets/*/target.json" if batch is not None else "batch_*/targets/*/target.json"
    targets: list[tuple[Path, dict[str, Any]]] = []
    for target_json in sorted(stage4_root.glob(pattern)):
        targets.append((target_json.parent, load_json(target_json)))
    return targets


def build_for_target(
    target_dir: Path,
    target: dict[str, Any],
    manifest: dict[str, Any],
    overwrite: bool,
    seed_cache: dict[str, Image.Image],
) -> dict[str, Any]:
    frame_count = int(target["frameCount"])
    slot_px = int(target["slotPixels"])
    runtime_slot_px = int(target.get("runtimeSlotPixels") or 512)
    seed_canvas = target_dir / "incoming" / "seed_canvas.png"
    pose_guide = target_dir / "incoming" / "pose_guides.png"
    seed_preview = target_dir / "previews" / "seed_contact.jpg"
    generation_request = target_dir / "generation_request.json"
    if not overwrite and seed_canvas.exists() and pose_guide.exists() and generation_request.exists():
        expected_size = (frame_count * slot_px, slot_px)
        seed_size = image_size(seed_canvas)
        guide_size = image_size(pose_guide)
        if seed_size == expected_size and guide_size == expected_size:
            return {
                "targetId": target.get("targetId"),
                "matrixKey": target.get("matrixKey"),
                "status": "exists",
                "seedCanvas": str(seed_canvas),
            }
        stale_reason = {
            "expectedSize": expected_size,
            "seedSize": seed_size,
            "poseGuideSize": guide_size,
        }
    else:
        stale_reason = None

    if stale_reason:
        # Continue into rebuild path. Old 512px seeds must not masquerade as
        # 4K source canvases.
        pass

    if not overwrite and seed_canvas.exists() and pose_guide.exists() and generation_request.exists() and not stale_reason:
        return {
            "targetId": target.get("targetId"),
            "matrixKey": target.get("matrixKey"),
            "status": "exists",
            "seedCanvas": str(seed_canvas),
        }

    seed_record = choose_seed_record(target, manifest)
    seed_path = Path(str(seed_record["sourcePath"]))
    seed_cache_key = str(seed_path)
    if seed_cache_key not in seed_cache:
        seed_cache[seed_cache_key] = load_seed_image(seed_path)
    cutout = seed_cache[seed_cache_key].copy()
    fitted = fit_bottom_center(cutout, slot_px)
    target_dir.joinpath("incoming").mkdir(parents=True, exist_ok=True)
    target_dir.joinpath("previews").mkdir(parents=True, exist_ok=True)
    make_seed_strip(fitted, frame_count, slot_px).save(seed_canvas)
    make_pose_guide(fitted, frame_count, slot_px).save(pose_guide)
    make_contact_preview(fitted, target, seed_record, seed_preview)
    request = {
        "schemaVersion": 1,
        "stage": "stage-4-seed-canvas",
        "generatedAt": utc_now(),
        "targetId": target.get("targetId"),
        "matrixKey": target.get("matrixKey"),
        "action": target.get("action"),
        "verticalTier": target.get("verticalTier"),
        "horizontalTier": target.get("horizontalTier"),
        "frameCount": frame_count,
        "slotPixels": slot_px,
        "minimumSourceSlotPixels": int(target.get("minimumSourceSlotPixels") or slot_px),
        "runtimeSlotPixels": runtime_slot_px,
        "expectedOutputSize": [frame_count * slot_px, slot_px],
        "seedRecord": {
            "id": seed_record.get("id"),
            "origin": seed_record.get("origin"),
            "action": seed_record.get("action"),
            "horizontalTier": seed_record.get("horizontalTier"),
            "approvalStatus": seed_record.get("approvalStatus"),
            "sourcePath": seed_record.get("sourcePath"),
        },
        "files": {
            "seedCanvas": str(seed_canvas),
            "poseGuides": str(pose_guide),
            "seedPreview": str(seed_preview),
            "prompt": str(target_dir / "prompt.md"),
            "rawStripOutput": str(target_dir / "incoming" / "raw_strip.png"),
        },
        "generationInstruction": "Use seed_canvas.png as the edit canvas and reference boards as identity lock. Generate one coherent 4K-minimum full strip into incoming/raw_strip.png. Do not upscale low-resolution art and do not promote until QA passes.",
        "negativeDesignRules": [
            "no blue orbs",
            "no animal ears",
            "no shortened stockings",
            "no missing thigh strap where visible",
            "no sneakers",
            "no baked full-body halo",
            "no baked floor shadow or drop shadow",
            "no outfit redesign",
            "no random height or thigh-width changes",
            "no duplicate walk leg poses",
        ],
    }
    write_json(generation_request, request)
    return {
        "targetId": target.get("targetId"),
        "matrixKey": target.get("matrixKey"),
        "status": "built",
        "seedRecordId": seed_record.get("id"),
        "seedCanvas": str(seed_canvas),
        "poseGuides": str(pose_guide),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, default=DEFAULT_LIBRARY_ROOT)
    parser.add_argument("--stage4-root", type=Path, default=DEFAULT_STAGE4_ROOT)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--batch", type=int, default=None, help="Optional Stage 4 batch number. Omit to build all targets.")
    parser.add_argument("--offset", type=int, default=0, help="Optional number of selected targets to skip before building.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max target count after offset.")
    parser.add_argument("--only-stale", action="store_true", help="Rebuild only missing or wrong-dimension seed canvases.")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    manifest = load_json(args.source_manifest)
    selected_targets = iter_targets(args.stage4_root, args.batch)
    if args.only_stale:
        selected_targets = [(target_dir, target) for target_dir, target in selected_targets if target_needs_seed_rebuild(target_dir, target)]
    if args.offset and args.offset > 0:
        selected_targets = selected_targets[args.offset :]
    if args.limit and args.limit > 0:
        selected_targets = selected_targets[: args.limit]
    seed_cache: dict[str, Image.Image] = {}
    results = [build_for_target(target_dir, target, manifest, args.overwrite, seed_cache) for target_dir, target in selected_targets]
    counts: dict[str, int] = {}
    for result in results:
        counts[str(result["status"])] = counts.get(str(result["status"]), 0) + 1
    report = {
        "schemaVersion": 1,
        "stage": "stage-4-seed-canvases",
        "generatedAt": utc_now(),
        "batch": args.batch,
        "offset": args.offset,
        "onlyStale": args.only_stale,
        "targetCount": len(results),
        "statusCounts": counts,
        "results": results,
        "policy": "Seed canvases are source-library generation inputs only; do not serve them as runtime art.",
    }
    report_path = args.library_root / "stage4_seed_canvas_report.json"
    write_json(report_path, report)
    print(f"Built Stage 4 seed canvases for {len(results)} target(s) -> {report_path}")
    print(f"Status: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
