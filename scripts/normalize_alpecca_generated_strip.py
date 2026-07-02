"""Normalize a generated Alpecca strip into the Stage 4 approved atlas format."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def remove_chroma(image: Image.Image, key=(0, 255, 0), threshold=132, soft=88) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            distance = math.sqrt((r - key[0]) ** 2 + (g - key[1]) ** 2 + (b - key[2]) ** 2)
            if distance <= threshold:
                pixels[x, y] = (r, g, b, 0)
            elif distance <= threshold + soft:
                alpha = int(a * ((distance - threshold) / max(1, soft)))
                pixels[x, y] = (r, g, b, alpha)
            elif g > r + 28 and g > b + 28:
                despilled_g = int((r + b) * 0.5)
                pixels[x, y] = (r, max(0, min(g, despilled_g)), b, a)
    return rgba


def detect_border_key(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    samples: list[tuple[int, int, int]] = []
    for x in range(rgb.width):
        samples.append(rgb.getpixel((x, 0)))
        samples.append(rgb.getpixel((x, rgb.height - 1)))
    for y in range(rgb.height):
        samples.append(rgb.getpixel((0, y)))
        samples.append(rgb.getpixel((rgb.width - 1, y)))
    if not samples:
        return (0, 255, 0)
    samples.sort()
    return samples[len(samples) // 2]


def alpha_bounds(image: Image.Image) -> tuple[int, int, int, int] | None:
    return image.convert("RGBA").getchannel("A").getbbox()


def variance(values: list[float]) -> float:
    if not values:
        return 0.0
    avg = sum(values) / len(values)
    return sum((value - avg) ** 2 for value in values) / len(values)


def lower_body_signature(frame: Image.Image, size: int = 48) -> list[int]:
    rgba = frame.convert("RGBA")
    alpha = rgba.getchannel("A")
    bounds = alpha.getbbox()
    if not bounds:
        return []
    left, top, right, bottom = bounds
    lower_top = top + int((bottom - top) * 0.48)
    crop = rgba.crop((left, lower_top, right, bottom)).resize((size, size), Image.Resampling.BILINEAR)
    gray = crop.convert("L")
    a = crop.getchannel("A")
    values: list[int] = []
    for y in range(size):
        for x in range(size):
            alpha_value = a.getpixel((x, y))
            if alpha_value <= 16:
                values.append(0)
            else:
                values.append(1 if gray.getpixel((x, y)) > 118 else 2)
    return values


def signature_similarity(a: list[int], b: list[int]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    matches = sum(1 for av, bv in zip(a, b) if av == bv)
    return matches / len(a)


def walk_duplicate_pose_report(frames: list[Image.Image], action: str) -> dict[str, Any]:
    if action != "walk" or len(frames) < 4:
        return {"enabled": action == "walk", "duplicatePosePairs": [], "warning": ""}
    signatures = [lower_body_signature(frame) for frame in frames]
    duplicate_pairs: list[dict[str, Any]] = []
    for index in range(len(signatures)):
        for offset in (1, 2):
            other = (index + offset) % len(signatures)
            similarity = signature_similarity(signatures[index], signatures[other])
            if similarity >= 0.925:
                duplicate_pairs.append(
                    {
                        "frameA": index,
                        "frameB": other,
                        "offset": offset,
                        "lowerBodySimilarity": round(similarity, 4),
                    }
                )
    return {
        "enabled": True,
        "duplicatePosePairs": duplicate_pairs,
        "duplicatePosePairCount": len(duplicate_pairs),
        "warning": "duplicate lower-body walk poses detected" if duplicate_pairs else "",
    }


def build_atlas(frame_count: int, slot_px: int) -> dict[str, Any]:
    return {
        "frames": {
            str(index): {"x": index * slot_px, "y": 0, "w": slot_px, "h": slot_px, "duration": 1}
            for index in range(frame_count)
        },
        "meta": {
            "size": {"w": frame_count * slot_px, "h": slot_px},
            "frame_size": {"w": slot_px, "h": slot_px},
            "stage": "stage-4-normalized-approved",
            "normalized_for_game": True,
        },
    }


def normalize(raw_path: Path, target_path: Path, out_dir: Path, key: tuple[int, int, int] | None = None) -> dict[str, Any]:
    contract = load_json(target_path)
    frame_count = int(contract["frameCount"])
    slot_px = int(contract["slotPixels"])
    raw = Image.open(raw_path).convert("RGBA")
    raw.load()
    chroma_key = key or detect_border_key(raw)
    cell_w = raw.width / frame_count
    frames: list[Image.Image] = []
    boxes: list[tuple[int, int, int, int]] = []

    for index in range(frame_count):
        left = int(round(index * cell_w))
        right = int(round((index + 1) * cell_w))
        frame = remove_chroma(raw.crop((left, 0, right, raw.height)), key=chroma_key)
        bounds = alpha_bounds(frame)
        if not bounds:
            frames.append(frame)
            boxes.append((0, 0, frame.width, frame.height))
            continue
        crop = frame.crop(bounds)
        frames.append(crop)
        boxes.append(bounds)

    max_w = max(frame.width for frame in frames)
    max_h = max(frame.height for frame in frames)
    pad = max(18, int(slot_px * 0.045))
    max_target_w = slot_px - pad * 2
    max_target_h = slot_px - pad * 2
    scale = min(max_target_w / max(1, max_w), max_target_h / max(1, max_h))
    sheet = Image.new("RGBA", (frame_count * slot_px, slot_px), (0, 0, 0, 0))
    normalized_bounds: list[dict[str, int]] = []

    for index, frame in enumerate(frames):
        new_w = max(1, int(round(frame.width * scale)))
        new_h = max(1, int(round(frame.height * scale)))
        resized = frame.resize((new_w, new_h), Image.Resampling.LANCZOS)
        x = index * slot_px + (slot_px - new_w) // 2
        y = slot_px - pad - new_h
        sheet.alpha_composite(resized, (x, y))
        normalized_bounds.append({"x": x - index * slot_px, "y": y, "w": new_w, "h": new_h, "bottom": y + new_h})

    out_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = out_dir / "spritesheet.png"
    sheet.save(sheet_path)
    sheet.save(out_dir / "spritesheet.webp", "WEBP", lossless=True, quality=100, method=0)
    atlas = build_atlas(frame_count, slot_px)
    write_json(out_dir / "atlas.json", atlas)

    widths = [item["w"] for item in normalized_bounds]
    heights = [item["h"] for item in normalized_bounds]
    bottoms = [item["bottom"] for item in normalized_bounds]
    normalized_frames = [sheet.crop((index * slot_px, 0, (index + 1) * slot_px, slot_px)) for index in range(frame_count)]
    duplicate_pose_report = walk_duplicate_pose_report(normalized_frames, str(contract.get("action") or ""))
    union_left = min(item["x"] for item in normalized_bounds)
    union_top = min(item["y"] for item in normalized_bounds)
    union_right = max(item["x"] + item["w"] for item in normalized_bounds)
    union_bottom = max(item["bottom"] for item in normalized_bounds)
    visual = {
        "frameSize": slot_px,
        "alphaBounds": {"x": union_left, "y": union_top, "w": union_right - union_left, "h": union_bottom - union_top},
        "visualScale": 1,
        "spriteY": 0.5 + ((slot_px - union_bottom) / slot_px),
        "heightClass": contract.get("heightClass"),
        "stage": "stage-4-normalized-approved",
        "qa": {
            "rawSize": [raw.width, raw.height],
            "detectedChromaKey": list(chroma_key),
            "expectedStripPixels": contract.get("expectedStripPixels"),
            "frameCount": frame_count,
            "slotPixels": slot_px,
            "normalizationScale": round(scale, 6),
            "footBottomVariance": round(variance([float(value) for value in bottoms]), 6),
            "bodyWidthVariance": round(variance([float(value) for value in widths]), 6),
            "bodyHeightVariance": round(variance([float(value) for value in heights]), 6),
            "emptyFrameCount": sum(1 for item in normalized_bounds if item["w"] <= 1 or item["h"] <= 1),
            "walkDuplicatePoseReport": duplicate_pose_report,
        },
    }
    write_json(out_dir / "visual.json", visual)
    write_json(
        out_dir / "matrix_metadata.json",
        {
            "schemaVersion": 1,
            "stage": "stage-4-normalized-approved",
            "generatedAt": utc_now(),
            "targetId": contract.get("targetId"),
            "matrixKey": contract.get("matrixKey"),
            "targetKind": contract.get("targetKind", "matrix-atlas"),
            "layerRole": contract.get("layerRole"),
            "action": contract.get("action"),
            "verticalTier": contract.get("verticalTier"),
            "horizontalTier": contract.get("horizontalTier"),
            "frameCount": frame_count,
            "slotPixels": slot_px,
            "heightClass": contract.get("heightClass"),
            "sourceRawStrip": str(raw_path),
            "approvalStatus": "approved-normalized-draft",
            "footAnchor": "bottom-center",
        },
    )
    return {"spritesheet": str(sheet_path), "visual": visual}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--key", default="", help="Optional chroma key as R,G,B. Defaults to border detection.")
    args = parser.parse_args()
    key = tuple(int(part) for part in args.key.split(",")) if args.key else None
    if key is not None and len(key) != 3:
        raise SystemExit("--key must be R,G,B")
    result = normalize(args.raw, args.target, args.out_dir, key=key)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
