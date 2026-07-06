"""Preview and QA returned Alpecca Stage 4 4K tile outputs.

This runs before import/stitch/promotion. It checks worker output tiles for the
minimum mechanical contract and creates contact-sheet previews for human visual
review. It does not copy tiles into the Stage 4 source tree and it does not
approve art.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageStat


REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def resolve_repo_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def load_jobs(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = load_json(manifest_path)
    jobs: list[dict[str, Any]] = []
    for chunk in manifest.get("chunks", []):
        jobs.extend(iter_jsonl(resolve_repo_path(str(chunk["file"]))))
    return jobs


def variance(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    image = Image.new("RGBA", size, (226, 232, 240, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if ((x // cell) + (y // cell)) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(196, 207, 220, 255))
    return image


def load_font(size: int = 18):
    for name in ("arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def image_probe(path: Path, expected_size: tuple[int, int]) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "ready": False, "issues": ["missing"]}
    try:
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            alpha = rgba.getchannel("A")
            bbox = alpha.getbbox()
            issues: list[str] = []
            if tuple(rgba.size) != expected_size:
                issues.append(f"wrong-size:{list(rgba.size)}")
            if "A" not in image.getbands():
                issues.append("no-alpha")
            if bbox is None:
                issues.append("empty-alpha")
            else:
                left, top, right, bottom = bbox
                margin = 24
                if left <= margin or top <= margin or right >= rgba.width - margin or bottom >= rgba.height - margin:
                    issues.append("alpha-near-edge")
                alpha_crop = alpha.crop(bbox)
                alpha_mean = ImageStat.Stat(alpha_crop.resize((64, 64))).mean[0]
                alpha_coverage = alpha_mean / 255.0
                box_w = right - left
                box_h = bottom - top
                if alpha_coverage > 0.82 and box_w > rgba.width * 0.18 and box_h > rgba.height * 0.18:
                    issues.append("opaque-background-rectangle")
                if box_w / max(1, box_h) > 1.25:
                    issues.append("sheet-like-alpha-bounds")
                component_summary = alpha_component_summary(alpha, bbox)
                if component_summary["largeComponentCount"] > 1:
                    issues.append("multi-subject-alpha-components")
                issues.extend(design_lock_issues(rgba, bbox))
            sidecar = path.with_suffix(".generation.json")
            generation = None
            if sidecar.exists():
                try:
                    generation = load_json(sidecar)
                    promotion_status = str(generation.get("promotionStatus") or "")
                    if promotion_status == "draft-not-promotable":
                        issues.append("draft-not-promotable")
                except Exception as error:
                    generation = {"promotionStatus": "unreadable-sidecar", "error": str(error)}
                    issues.append("unreadable-sidecar")
            return {
                "exists": True,
                "ready": not issues,
                "issues": issues,
                "size": list(rgba.size),
                "mode": image.mode,
                "alphaBounds": list(bbox) if bbox else None,
                "alphaComponents": alpha_component_summary(alpha, bbox) if bbox else None,
                "designLock": design_lock_summary(rgba, bbox) if bbox else None,
                "meanAlpha": round(ImageStat.Stat(alpha.resize((64, 64))).mean[0], 3),
                "generation": generation,
            }
    except Exception as error:
        return {"exists": True, "ready": False, "issues": [f"unreadable:{error}"]}


def alpha_component_summary(alpha: Image.Image, bbox: tuple[int, int, int, int] | None) -> dict[str, Any]:
    if bbox is None:
        return {"componentCount": 0, "largeComponentCount": 0, "largestAreaRatio": 0.0}
    left, top, right, bottom = bbox
    crop = alpha.crop(bbox).resize((128, 128), Image.Resampling.NEAREST)
    pixels = crop.load()
    visited: set[tuple[int, int]] = set()
    areas: list[int] = []
    for y in range(crop.height):
        for x in range(crop.width):
            if (x, y) in visited or pixels[x, y] <= 28:
                continue
            stack = [(x, y)]
            visited.add((x, y))
            area = 0
            while stack:
                cx, cy = stack.pop()
                area += 1
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if nx < 0 or ny < 0 or nx >= crop.width or ny >= crop.height:
                        continue
                    if (nx, ny) in visited or pixels[nx, ny] <= 28:
                        continue
                    visited.add((nx, ny))
                    stack.append((nx, ny))
            areas.append(area)
    foreground = sum(areas)
    large_threshold = max(16, int(max(1, foreground) * 0.12))
    large = [area for area in areas if area >= large_threshold]
    return {
        "componentCount": len(areas),
        "largeComponentCount": len(large),
        "largestAreaRatio": round(max(areas or [0]) / max(1, foreground), 4),
    }


def design_lock_summary(rgba: Image.Image, bbox: tuple[int, int, int, int] | None) -> dict[str, Any]:
    """Coarse color evidence for Alpecca's locked design.

    This is intentionally a guardrail, not a final art judge. It catches the
    common failed proofs: brown/red hair, bare legs, black boots replacing cream
    boots, or a generic skirt/blouse character. Human visual QA still decides.
    """
    if bbox is None:
        return {}
    left, top, right, bottom = bbox
    width = max(1, right - left)
    height = max(1, bottom - top)
    pixels = rgba.load()
    sample_step = max(1, max(width, height) // 220)

    def collect(y0_ratio: float, y1_ratio: float) -> dict[str, int]:
        y0 = top + int(height * y0_ratio)
        y1 = top + int(height * y1_ratio)
        counts = {
            "foreground": 0,
            "silverWhite": 0,
            "lavenderBlue": 0,
            "brownRed": 0,
            "stockingWhite": 0,
            "bareSkin": 0,
            "darkBootLike": 0,
        }
        for y in range(max(top, y0), min(bottom, y1), sample_step):
            for x in range(left, right, sample_step):
                r, g, b, a = pixels[x, y]
                if a <= 48:
                    continue
                counts["foreground"] += 1
                max_c = max(r, g, b)
                min_c = min(r, g, b)
                if r > 190 and g > 190 and b > 185 and max_c - min_c < 54:
                    counts["silverWhite"] += 1
                if b > 145 and r > 120 and g > 120 and b >= r - 12:
                    counts["lavenderBlue"] += 1
                if r > 105 and g < 115 and b < 105 and r > b + 24:
                    counts["brownRed"] += 1
                if r > 178 and g > 178 and b > 170 and max_c - min_c < 72:
                    counts["stockingWhite"] += 1
                if r > 145 and g > 95 and b > 65 and r > b + 34 and g > b + 14:
                    counts["bareSkin"] += 1
                if r < 78 and g < 78 and b < 92:
                    counts["darkBootLike"] += 1
        return counts

    upper = collect(0.03, 0.43)
    lower = collect(0.50, 0.88)
    def ratio(counts: dict[str, int], key: str) -> float:
        return round(counts[key] / max(1, counts["foreground"]), 4)
    return {
        "upper": {
            "foreground": upper["foreground"],
            "silverWhiteRatio": ratio(upper, "silverWhite"),
            "lavenderBlueRatio": ratio(upper, "lavenderBlue"),
            "brownRedRatio": ratio(upper, "brownRed"),
        },
        "lower": {
            "foreground": lower["foreground"],
            "stockingWhiteRatio": ratio(lower, "stockingWhite"),
            "bareSkinRatio": ratio(lower, "bareSkin"),
            "darkBootLikeRatio": ratio(lower, "darkBootLike"),
        },
        "policy": "Automatic drift probe only; visual QA remains required.",
    }


def design_lock_issues(rgba: Image.Image, bbox: tuple[int, int, int, int] | None) -> list[str]:
    summary = design_lock_summary(rgba, bbox)
    if not summary:
        return []
    issues: list[str] = []
    upper = summary["upper"]
    lower = summary["lower"]
    silver_family = float(upper["silverWhiteRatio"]) + float(upper["lavenderBlueRatio"]) * 0.35
    if upper["foreground"] > 24 and float(upper["brownRedRatio"]) > max(0.12, silver_family * 1.8):
        issues.append("design-lock-hair-color-drift")
    if lower["foreground"] > 24:
        if float(lower["stockingWhiteRatio"]) < 0.16:
            issues.append("design-lock-missing-white-thigh-highs")
        if float(lower["bareSkinRatio"]) > max(0.18, float(lower["stockingWhiteRatio"]) * 1.4):
            issues.append("design-lock-bare-leg-drift")
        if float(lower["darkBootLikeRatio"]) > 0.32 and float(lower["stockingWhiteRatio"]) < 0.28:
            issues.append("design-lock-dark-boots-or-lower-outfit-drift")
    return issues


def render_preview(target_id: str, records: list[dict[str, Any]], out_path: Path, thumb_size: int) -> None:
    font = load_font(18)
    label_font = load_font(14)
    columns = min(8, max(1, len(records)))
    rows = max(1, math.ceil(len(records) / columns))
    header_h = 74
    cell_w = thumb_size + 24
    cell_h = thumb_size + 54
    canvas = Image.new("RGBA", (columns * cell_w + 24, header_h + rows * cell_h + 24), (18, 24, 38, 255))
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 16), f"Alpecca Stage 4 Tile QA: {target_id}", fill=(240, 249, 255, 255), font=font)
    draw.text((18, 44), "Checkerboard = transparency. Cyan line = detected foot baseline. Red box = alpha bounds.", fill=(180, 198, 215, 255), font=label_font)

    max_bottom = 0
    for record in records:
        bbox = record.get("probe", {}).get("alphaBounds")
        if bbox:
            max_bottom = max(max_bottom, int(bbox[3]))

    for index, record in enumerate(records):
        col = index % columns
        row = index // columns
        x = 12 + col * cell_w
        y = header_h + row * cell_h
        bg = checkerboard((thumb_size, thumb_size), cell=16)
        image_path = Path(record["source"])
        probe = record["probe"]
        if image_path.exists():
            with Image.open(image_path) as image:
                rgba = image.convert("RGBA")
                preview = rgba.resize((thumb_size, thumb_size), Image.Resampling.LANCZOS)
                bg.alpha_composite(preview, (0, 0))
        canvas.alpha_composite(bg, (x, y))
        bbox = probe.get("alphaBounds")
        if bbox:
            sx = thumb_size / max(1, probe["size"][0])
            sy = thumb_size / max(1, probe["size"][1])
            box = [x + int(bbox[0] * sx), y + int(bbox[1] * sy), x + int(bbox[2] * sx), y + int(bbox[3] * sy)]
            draw.rectangle(box, outline=(255, 91, 91, 255), width=2)
        if max_bottom and probe.get("size"):
            baseline_y = y + int(max_bottom * (thumb_size / max(1, probe["size"][1])))
            draw.line((x, baseline_y, x + thumb_size, baseline_y), fill=(66, 245, 255, 210), width=2)
        status_color = (134, 239, 172, 255) if probe.get("ready") else (252, 165, 165, 255)
        draw.text((x, y + thumb_size + 6), f"f{record['frameIndex']:03d} {record['status']}", fill=status_color, font=label_font)
        issue_text = ", ".join(probe.get("issues", []))[:34]
        draw.text((x, y + thumb_size + 28), issue_text or "mechanical pass", fill=(203, 213, 225, 255), font=label_font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, quality=92)


def qa_outputs(manifest_path: Path, outputs_root: Path, out_root: Path, target_id: str | None, thumb_size: int) -> dict[str, Any]:
    jobs = load_jobs(manifest_path)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job in jobs:
        if target_id and job.get("targetId") != target_id:
            continue
        groups[str(job["targetId"])].append(job)

    previews_dir = out_root / "tile_previews"
    target_reports: list[dict[str, Any]] = []
    total_jobs = ready_jobs = missing_jobs = blocked_jobs = 0
    for group_target_id, group_jobs in sorted(groups.items()):
        frame_records: list[dict[str, Any]] = []
        bottoms: list[float] = []
        widths: list[float] = []
        heights: list[float] = []
        for job in sorted(group_jobs, key=lambda item: int(item.get("frameIndex", 0))):
            expected_size = tuple(int(value) for value in job.get("expectedSize", [4096, 4096]))
            source = outputs_root / str(job["expectedWorkerOutput"]).replace("/", os.sep)
            probe = image_probe(source, expected_size)
            total_jobs += 1
            if not probe["exists"]:
                missing_jobs += 1
            if probe["ready"]:
                ready_jobs += 1
            else:
                blocked_jobs += 1
            bbox = probe.get("alphaBounds")
            if bbox:
                widths.append(float(bbox[2] - bbox[0]))
                heights.append(float(bbox[3] - bbox[1]))
                bottoms.append(float(bbox[3]))
            frame_records.append(
                {
                    "jobId": job.get("jobId"),
                    "targetId": group_target_id,
                    "matrixKey": job.get("matrixKey"),
                    "frameIndex": int(job.get("frameIndex", 0)),
                    "source": str(source),
                    "status": "ready" if probe["ready"] else "blocked",
                    "probe": probe,
                }
            )
        preview_path = previews_dir / f"{group_target_id}_tile_qa.jpg"
        if any(Path(record["source"]).exists() for record in frame_records):
            render_preview(group_target_id, frame_records, preview_path, thumb_size)
        complete = len(frame_records) > 0 and all(record["probe"]["ready"] for record in frame_records)
        target_reports.append(
            {
                "targetId": group_target_id,
                "matrixKey": group_jobs[0].get("matrixKey") if group_jobs else None,
                "frameCount": len(frame_records),
                "readyFrameCount": sum(1 for record in frame_records if record["probe"]["ready"]),
                "mechanicalStatus": "ready-for-import" if complete else "blocked",
                "preview": str(preview_path) if preview_path.exists() else None,
                "metrics": {
                    "footBottomVariance": round(variance(bottoms), 4),
                    "alphaWidthVariance": round(variance(widths), 4),
                    "alphaHeightVariance": round(variance(heights), 4),
                },
                "frames": frame_records,
            }
        )

    report = {
        "schemaVersion": 1,
        "stage": "stage-4-tile-output-qa",
        "generatedAt": utc_now(),
        "manifest": str(manifest_path),
        "outputsRoot": str(outputs_root),
        "targetFilter": target_id,
        "targetCount": len(target_reports),
        "jobCount": total_jobs,
        "readyJobCount": ready_jobs,
        "missingJobCount": missing_jobs,
        "blockedJobCount": blocked_jobs,
        "readyTargetCount": sum(1 for target in target_reports if target["mechanicalStatus"] == "ready-for-import"),
        "policy": "Mechanical preview only. Human visual QA must still confirm design lock before import/stitch/promotion.",
        "targets": target_reports,
    }
    write_json(out_root / "tile_visual_qa_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--outputs-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path)
    parser.add_argument("--target-id")
    parser.add_argument("--thumb-size", type=int, default=384)
    args = parser.parse_args()
    out_root = args.out_root or args.outputs_root
    report = qa_outputs(args.manifest, args.outputs_root, out_root, args.target_id, args.thumb_size)
    print(
        json.dumps(
            {
                "targetCount": report["targetCount"],
                "jobCount": report["jobCount"],
                "readyJobCount": report["readyJobCount"],
                "missingJobCount": report["missingJobCount"],
                "blockedJobCount": report["blockedJobCount"],
                "readyTargetCount": report["readyTargetCount"],
                "report": str(out_root / "tile_visual_qa_report.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
