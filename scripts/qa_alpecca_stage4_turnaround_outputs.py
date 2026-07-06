"""QA a returned Alpecca Stage 4 16-sector turnaround slice.

This is the visual gate for the first production proof. It reads a Stage 4 tile
job manifest, finds one frame for each sector s0 through s15, validates the
mechanical image contract, and renders a contact sheet that makes flat billboard
or ultra-thin side-view regressions easier to catch before import.
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
SECTORS_16 = tuple(f"s{i}" for i in range(16))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
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


def load_font(size: int):
    for name in ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def checkerboard(size: tuple[int, int], cell: int = 18) -> Image.Image:
    image = Image.new("RGBA", size, (228, 234, 242, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if ((x // cell) + (y // cell)) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(190, 203, 219, 255))
    return image


def variance(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def sector_sort_key(sector: str) -> int:
    if sector.startswith("s") and sector[1:].isdigit():
        return int(sector[1:])
    return 999


def image_probe(path: Path, expected_size: tuple[int, int]) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "ready": False, "issues": ["missing"]}
    try:
        with Image.open(path) as source:
            rgba = source.convert("RGBA")
            alpha = rgba.getchannel("A")
            bbox = alpha.getbbox()
            issues: list[str] = []
            if rgba.size != expected_size:
                issues.append(f"wrong-size:{list(rgba.size)}")
            if "A" not in source.getbands():
                issues.append("no-alpha")
            if bbox is None:
                issues.append("empty-alpha")
            else:
                edge_margin = 24
                left, top, right, bottom = bbox
                if left <= edge_margin or top <= edge_margin or right >= rgba.width - edge_margin or bottom >= rgba.height - edge_margin:
                    issues.append("alpha-near-edge")
            return {
                "exists": True,
                "ready": not issues,
                "issues": issues,
                "size": list(rgba.size),
                "mode": source.mode,
                "alphaBounds": list(bbox) if bbox else None,
                "meanAlpha": round(ImageStat.Stat(alpha.resize((64, 64))).mean[0], 3),
            }
    except Exception as error:
        return {"exists": True, "ready": False, "issues": [f"unreadable:{error}"]}


def representative_jobs(jobs: list[dict[str, Any]], frame_index: int | None) -> dict[str, dict[str, Any]]:
    by_sector: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job in jobs:
        sector = str(job.get("viewSector16") or job.get("horizontalTier") or "")
        if sector in SECTORS_16:
            by_sector[sector].append(job)
    selected: dict[str, dict[str, Any]] = {}
    for sector, sector_jobs in by_sector.items():
        sorted_jobs = sorted(sector_jobs, key=lambda item: int(item.get("frameIndex") or 0))
        if frame_index is None:
            selected[sector] = sorted_jobs[0]
            continue
        match = next((job for job in sorted_jobs if int(job.get("frameIndex") or 0) == frame_index), None)
        if match:
            selected[sector] = match
    return selected


def draw_turnaround_sheet(records: list[dict[str, Any]], out_path: Path, thumb_size: int) -> None:
    title_font = load_font(26)
    label_font = load_font(16)
    columns = 8
    rows = 2
    cell_w = thumb_size + 30
    cell_h = thumb_size + 80
    header_h = 110
    canvas = Image.new("RGBA", (columns * cell_w + 40, header_h + rows * cell_h + 36), (14, 18, 30, 255))
    draw = ImageDraw.Draw(canvas)
    draw.text((22, 20), "Alpecca Stage 4 Turnaround QA - s0 through s15", fill=(245, 249, 255, 255), font=title_font)
    draw.text(
        (22, 58),
        "Check body volume, side thickness, thigh-high stockings, boots, hair mass, and no baked halo/shadow/orbs.",
        fill=(178, 194, 214, 255),
        font=label_font,
    )

    bottom_values = [record["probe"]["alphaBounds"][3] for record in records if record["probe"].get("alphaBounds")]
    max_bottom = max(bottom_values) if bottom_values else 0

    for index, record in enumerate(records):
        col = index % columns
        row = index // columns
        x = 20 + col * cell_w
        y = header_h + row * cell_h
        bg = checkerboard((thumb_size, thumb_size))
        path = Path(record["source"])
        probe = record["probe"]
        if path.exists():
            with Image.open(path) as source:
                preview = source.convert("RGBA").resize((thumb_size, thumb_size), Image.Resampling.LANCZOS)
                bg.alpha_composite(preview, (0, 0))
        canvas.alpha_composite(bg, (x, y))

        bbox = probe.get("alphaBounds")
        if bbox and probe.get("size"):
            sx = thumb_size / max(1, int(probe["size"][0]))
            sy = thumb_size / max(1, int(probe["size"][1]))
            draw.rectangle(
                (x + int(bbox[0] * sx), y + int(bbox[1] * sy), x + int(bbox[2] * sx), y + int(bbox[3] * sy)),
                outline=(255, 91, 91, 255),
                width=2,
            )
            baseline_y = y + int(max_bottom * sy)
            draw.line((x, baseline_y, x + thumb_size, baseline_y), fill=(51, 235, 255, 220), width=2)
        status_color = (134, 239, 172, 255) if probe.get("ready") else (252, 165, 165, 255)
        draw.text((x, y + thumb_size + 8), f"{record['sector']} {record['matrixKey']}", fill=status_color, font=label_font)
        issue_text = ", ".join(probe.get("issues") or []) or "mechanical pass"
        draw.text((x, y + thumb_size + 32), issue_text[:36], fill=(203, 213, 225, 255), font=label_font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, quality=92)


def qa_turnaround(manifest_path: Path, outputs_root: Path, out_root: Path, frame_index: int | None, thumb_size: int) -> dict[str, Any]:
    jobs = load_jobs(manifest_path)
    selected = representative_jobs(jobs, frame_index)
    records: list[dict[str, Any]] = []
    missing_sectors = [sector for sector in SECTORS_16 if sector not in selected]
    for sector in SECTORS_16:
        job = selected.get(sector)
        if not job:
            continue
        expected_size = tuple(int(value) for value in job.get("expectedSize", [4096, 4096]))
        source = outputs_root / str(job["expectedWorkerOutput"]).replace("/", os.sep)
        probe = image_probe(source, expected_size)
        records.append(
            {
                "sector": sector,
                "jobId": job.get("jobId"),
                "targetId": job.get("targetId"),
                "matrixKey": job.get("matrixKey"),
                "frameIndex": int(job.get("frameIndex") or 0),
                "source": str(source),
                "probe": probe,
            }
        )

    out_root.mkdir(parents=True, exist_ok=True)
    preview_path = out_root / "turnaround_16_sector_qa.jpg"
    if records:
        draw_turnaround_sheet(records, preview_path, thumb_size)

    widths = []
    heights = []
    bottoms = []
    for record in records:
        bbox = record["probe"].get("alphaBounds")
        if bbox:
            widths.append(float(bbox[2] - bbox[0]))
            heights.append(float(bbox[3] - bbox[1]))
            bottoms.append(float(bbox[3]))
    ready_count = sum(1 for record in records if record["probe"].get("ready"))
    report = {
        "schemaVersion": 1,
        "stage": "stage-4-turnaround-output-qa",
        "generatedAt": utc_now(),
        "manifest": str(manifest_path),
        "outputsRoot": str(outputs_root),
        "frameIndex": frame_index,
        "sectorCount": len(records),
        "expectedSectorCount": 16,
        "missingSectors": missing_sectors,
        "readySectorCount": ready_count,
        "blockedSectorCount": len(records) - ready_count + len(missing_sectors),
        "mechanicalStatus": "ready-for-visual-review" if ready_count == 16 and not missing_sectors else "blocked",
        "preview": str(preview_path) if preview_path.exists() else None,
        "metrics": {
            "footBottomVariance": round(variance(bottoms), 4),
            "alphaWidthVariance": round(variance(widths), 4),
            "alphaHeightVariance": round(variance(heights), 4),
        },
        "visualQaChecklist": [
            "Each sector is a native camera angle around Alpecca, not the same flat billboard.",
            "Side sectors keep adult body depth and do not become ultra-thin.",
            "White thigh-high stockings, black shorts, hoodie, lanyard, hair, and boots stay consistent.",
            "No baked halo, baked floor shadow, blue orbs, UI, text, floor, or scene background.",
            "Feet share a stable bottom baseline and 5ft 7in standing body class.",
        ],
        "records": records,
    }
    write_json(out_root / "turnaround_16_sector_qa_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--outputs-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path)
    parser.add_argument("--frame-index", type=int, default=0)
    parser.add_argument("--thumb-size", type=int, default=512)
    args = parser.parse_args()
    out_root = args.out_root or args.outputs_root
    report = qa_turnaround(args.manifest, args.outputs_root, out_root, args.frame_index, args.thumb_size)
    print(
        json.dumps(
            {
                "mechanicalStatus": report["mechanicalStatus"],
                "sectorCount": report["sectorCount"],
                "readySectorCount": report["readySectorCount"],
                "blockedSectorCount": report["blockedSectorCount"],
                "missingSectors": report["missingSectors"],
                "preview": report["preview"],
                "report": str(out_root / "turnaround_16_sector_qa_report.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
