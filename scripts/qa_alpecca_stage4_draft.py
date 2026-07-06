"""QA a generated Alpecca Stage 4 draft without approving it.

This is intentionally separate from `normalize_alpecca_generated_strip.py`.
It lets quick image-generation drafts enter a target workspace as evidence
without making them look like approved source art or runtime-ready atlases.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def expected_size(contract: dict[str, Any]) -> tuple[int, int]:
    frame_count = int(contract["frameCount"])
    slot_px = int(contract["slotPixels"])
    return (frame_count * slot_px, slot_px)


def border_samples(image: Image.Image) -> list[tuple[int, int, int]]:
    rgb = image.convert("RGB")
    samples: list[tuple[int, int, int]] = []
    for x in range(rgb.width):
        samples.append(rgb.getpixel((x, 0)))
        samples.append(rgb.getpixel((x, rgb.height - 1)))
    for y in range(rgb.height):
        samples.append(rgb.getpixel((0, y)))
        samples.append(rgb.getpixel((rgb.width - 1, y)))
    return samples


def dominant_color(samples: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    if not samples:
        return (0, 0, 0)
    # Quantize lightly so antialiasing/noise does not create thousands of keys.
    quantized = [tuple((channel // 8) * 8 for channel in sample) for sample in samples]
    color, _count = Counter(quantized).most_common(1)[0]
    return color


def border_flatness(image: Image.Image) -> dict[str, Any]:
    samples = border_samples(image)
    color = dominant_color(samples)
    if not samples:
        return {"dominantColor": list(color), "meanDistance": 9999, "maxDistance": 9999, "flat": False}
    distances = [
        abs(sample[0] - color[0]) + abs(sample[1] - color[1]) + abs(sample[2] - color[2])
        for sample in samples
    ]
    mean_distance = sum(distances) / len(distances)
    return {
        "dominantColor": list(color),
        "meanDistance": round(mean_distance, 3),
        "maxDistance": max(distances),
        "flat": mean_distance <= 6 and max(distances) <= 30,
    }


def frame_alpha_bounds(image: Image.Image, frame_count: int) -> list[dict[str, Any]]:
    rgba = image.convert("RGBA")
    cell_w = rgba.width / max(1, frame_count)
    frames: list[dict[str, Any]] = []
    for index in range(frame_count):
        left = int(round(index * cell_w))
        right = int(round((index + 1) * cell_w))
        frame = rgba.crop((left, 0, right, rgba.height))
        alpha = frame.getchannel("A")
        bbox = alpha.getbbox()
        stat = ImageStat.Stat(alpha)
        frames.append(
            {
                "index": index,
                "cell": [left, 0, right - left, rgba.height],
                "alphaBounds": list(bbox) if bbox else None,
                "meanAlpha": round(stat.mean[0], 3),
            }
        )
    return frames


def qa_draft(draft_path: Path, request_path: Path, out_path: Path) -> dict[str, Any]:
    contract = load_json(request_path)
    image = Image.open(draft_path)
    image.load()
    expected = expected_size(contract)
    actual = image.size
    border = border_flatness(image)
    frame_count = int(contract["frameCount"])
    issues: list[str] = []
    if actual != expected:
        issues.append(f"Draft size {actual[0]}x{actual[1]} does not match required {expected[0]}x{expected[1]}.")
    if "A" not in image.getbands() and not border["flat"]:
        issues.append("Draft is not transparent and border/background is not flat enough for clean chroma removal.")
    if actual[0] / max(1, frame_count) < 1024 or actual[1] < 1024:
        issues.append("Draft is below minimum practical source resolution for 4K-per-frame promotion.")

    report = {
        "schemaVersion": 1,
        "stage": "stage-4-draft-qa",
        "generatedAt": utc_now(),
        "targetId": contract.get("targetId"),
        "matrixKey": contract.get("matrixKey"),
        "action": contract.get("action"),
        "verticalTier": contract.get("verticalTier"),
        "horizontalTier": contract.get("horizontalTier"),
        "draftPath": str(draft_path),
        "expectedSize": list(expected),
        "actualSize": list(actual),
        "frameCount": frame_count,
        "border": border,
        "frameProbe": frame_alpha_bounds(image, frame_count),
        "promotionStatus": "draft-rejected" if issues else "draft-needs-human-review",
        "issues": issues,
        "notes": [
            "This report does not approve art.",
            "Move a passing 4K strip to incoming/raw_strip.png only after visual QA and design-lock review.",
            "Stage 5 promotion still requires approved/spritesheet.png."
        ],
    }
    write_json(out_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = qa_draft(args.draft, args.request, args.out)
    print(json.dumps({"promotionStatus": report["promotionStatus"], "issues": report["issues"], "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
