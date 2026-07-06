"""Analyze 16-sector Alpecca turnaround outputs for real 2D-in-3D volume.

The contact-sheet QA makes the result visible to a human. This script adds a
machine-readable pre-promotion gate for the specific failures that kept showing
up in the HQ: one flat billboard reused across sectors, paper-thin side views,
duplicated silhouettes, unstable feet, and missing sector outputs.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from PIL import Image, ImageChops, ImageStat


REPO_ROOT = Path(__file__).resolve().parents[1]
SECTORS_16 = tuple(f"s{i}" for i in range(16))
SIDE_SECTORS = ("s4", "s12")


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


def sector_sort_key(sector: str) -> int:
    return int(sector[1:]) if sector.startswith("s") and sector[1:].isdigit() else 999


def selected_jobs_by_sector(jobs: list[dict[str, Any]], frame_index: int) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for job in sorted(jobs, key=lambda item: int(item.get("frameIndex") or 0)):
        sector = str(job.get("viewSector16") or job.get("horizontalTier") or "")
        if sector not in SECTORS_16:
            continue
        if int(job.get("frameIndex") or 0) != frame_index:
            continue
        selected.setdefault(sector, job)
    return selected


def normalized_alpha(path: Path, size: int) -> Image.Image | None:
    if not path.exists():
        return None
    with Image.open(path) as source:
        alpha = source.convert("RGBA").getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            return None
        cropped = alpha.crop(bbox)
        normalized = Image.new("L", (size, size), 0)
        cropped.thumbnail((size, size), Image.Resampling.LANCZOS)
        x = (size - cropped.width) // 2
        y = size - cropped.height
        normalized.paste(cropped, (x, y))
        return normalized


def mean_alpha_delta(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a, b)
    return float(ImageStat.Stat(diff.resize((32, 32), Image.Resampling.BILINEAR)).mean[0])


def probe_sector(path: Path, expected_size: tuple[int, int], normalize_size: int) -> dict[str, Any]:
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
            if bbox is None:
                issues.append("empty-alpha")
            width = height = bottom = ratio = 0.0
            if bbox:
                width = float(bbox[2] - bbox[0])
                height = float(bbox[3] - bbox[1])
                bottom = float(bbox[3])
                ratio = width / height if height else 0.0
            mask = normalized_alpha(path, normalize_size)
            return {
                "exists": True,
                "ready": not issues and mask is not None,
                "issues": issues,
                "size": list(rgba.size),
                "alphaBounds": list(bbox) if bbox else None,
                "alphaWidth": round(width, 4),
                "alphaHeight": round(height, 4),
                "widthHeightRatio": round(ratio, 5),
                "footBottom": round(bottom, 4),
            }
    except Exception as error:
        return {"exists": True, "ready": False, "issues": [f"unreadable:{type(error).__name__}:{error}"]}


def run_volume_qa(
    manifest_path: Path,
    outputs_root: Path,
    out_path: Path,
    *,
    frame_index: int = 0,
    normalize_size: int = 128,
    min_side_width_ratio: float = 0.16,
    min_width_range_ratio: float = 0.08,
    min_adjacent_delta: float = 2.5,
) -> dict[str, Any]:
    jobs = selected_jobs_by_sector(load_jobs(manifest_path), frame_index)
    records: list[dict[str, Any]] = []
    masks: dict[str, Image.Image] = {}
    issues: list[str] = []

    for sector in SECTORS_16:
        job = jobs.get(sector)
        if not job:
            issues.append(f"{sector}:missing-job")
            records.append({"sector": sector, "ready": False, "issues": ["missing-job"]})
            continue
        expected_size = tuple(int(value) for value in job.get("expectedSize", [4096, 4096]))
        source = outputs_root / str(job["expectedWorkerOutput"]).replace("/", os.sep)
        probe = probe_sector(source, expected_size, normalize_size)
        record = {
            "sector": sector,
            "jobId": job.get("jobId"),
            "matrixKey": job.get("matrixKey"),
            "source": str(source),
            "ready": probe.get("ready"),
            "probe": probe,
        }
        records.append(record)
        if not probe.get("ready"):
            issues.extend(f"{sector}:{issue}" for issue in probe.get("issues") or ["not-ready"])
            continue
        mask = normalized_alpha(source, normalize_size)
        if mask is not None:
            masks[sector] = mask

    ready_records = [record for record in records if record.get("ready")]
    width_ratios = [
        float(record["probe"].get("widthHeightRatio") or 0)
        for record in ready_records
        if record.get("probe")
    ]
    foot_bottoms = [
        float(record["probe"].get("footBottom") or 0)
        for record in ready_records
        if record.get("probe")
    ]
    side_ratios = {
        sector: float(next((record["probe"].get("widthHeightRatio") for record in ready_records if record["sector"] == sector), 0) or 0)
        for sector in SIDE_SECTORS
    }
    adjacent_deltas: list[dict[str, Any]] = []
    for index, sector in enumerate(SECTORS_16):
        next_sector = SECTORS_16[(index + 1) % len(SECTORS_16)]
        if sector not in masks or next_sector not in masks:
            continue
        delta = mean_alpha_delta(masks[sector], masks[next_sector])
        adjacent_deltas.append({"from": sector, "to": next_sector, "meanAlphaDelta": round(delta, 4)})

    if len(ready_records) != 16:
        issues.append(f"ready-sector-count:{len(ready_records)}")
    if width_ratios:
        width_range_ratio = (max(width_ratios) - min(width_ratios)) / max(0.0001, median(width_ratios))
        if width_range_ratio < min_width_range_ratio:
            issues.append(f"flat-billboard-suspected:width-range-ratio:{width_range_ratio:.4f}")
        for sector, ratio in side_ratios.items():
            if ratio and ratio < min_side_width_ratio:
                issues.append(f"{sector}:ultra-thin-side-view:{ratio:.4f}")
    else:
        width_range_ratio = 0.0
    if adjacent_deltas:
        average_adjacent_delta = sum(item["meanAlphaDelta"] for item in adjacent_deltas) / len(adjacent_deltas)
        if average_adjacent_delta < min_adjacent_delta:
            issues.append(f"flat-billboard-suspected:adjacent-alpha-delta:{average_adjacent_delta:.4f}")
    else:
        average_adjacent_delta = 0.0

    report = {
        "schemaVersion": 1,
        "stage": "stage-4-360-volume-qa",
        "generatedAt": utc_now(),
        "manifest": str(manifest_path),
        "outputsRoot": str(outputs_root),
        "frameIndex": frame_index,
        "status": "pass" if not issues else "blocked",
        "readySectorCount": len(ready_records),
        "expectedSectorCount": 16,
        "thresholds": {
            "normalizeSize": normalize_size,
            "minSideWidthRatio": min_side_width_ratio,
            "minWidthRangeRatio": min_width_range_ratio,
            "minAdjacentDelta": min_adjacent_delta,
        },
        "metrics": {
            "widthHeightRatios": [round(value, 5) for value in width_ratios],
            "sideWidthHeightRatios": {key: round(value, 5) for key, value in side_ratios.items()},
            "widthRangeRatio": round(width_range_ratio, 5),
            "averageAdjacentAlphaDelta": round(average_adjacent_delta, 5),
            "footBottomRange": round(max(foot_bottoms) - min(foot_bottoms), 4) if foot_bottoms else 0,
            "adjacentDeltas": adjacent_deltas,
        },
        "issues": issues,
        "visualQaMeaning": (
            "This report cannot judge Alpecca's beauty or exact design, but it blocks obvious "
            "non-volumetric rotation failures before import/promotion."
        ),
        "records": records,
    }
    write_json(out_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--outputs-root", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--frame-index", type=int, default=0)
    parser.add_argument("--normalize-size", type=int, default=128)
    args = parser.parse_args()
    out = args.out or (args.outputs_root / "qa" / "turnaround_360_volume_report.json")
    report = run_volume_qa(args.manifest, args.outputs_root, out, frame_index=args.frame_index, normalize_size=args.normalize_size)
    print(json.dumps({
        "status": report["status"],
        "readySectorCount": report["readySectorCount"],
        "issues": report["issues"][:8],
        "report": str(out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
