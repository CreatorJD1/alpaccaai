"""Stitch approved-size Alpecca Stage 4 frame tiles into raw_strip.png."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE4_ROOT = REPO_ROOT / "data" / "alpecca_art_source" / "stage4_generation_batches"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def image_size(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    try:
        with Image.open(path) as image:
            return image.size
    except Exception:
        return None


def stitch(target_dir: Path, apply: bool) -> dict[str, Any]:
    target = load_json(target_dir / "target.json")
    frame_count = int(target["frameCount"])
    slot_px = int(target["slotPixels"])
    incoming = target_dir / "incoming"
    tile_dir = incoming / "frame_tiles"
    out_path = incoming / "raw_strip.png"
    expected_tile_size = (slot_px, slot_px)
    expected_strip_size = (frame_count * slot_px, slot_px)
    frames: list[dict[str, Any]] = []
    issues: list[str] = []

    for index in range(frame_count):
        path = tile_dir / f"frame_{index:03d}.png"
        size = image_size(path)
        if size != expected_tile_size:
            issues.append(f"frame_{index:03d}.png size {size} does not match {expected_tile_size}")
        frames.append({"index": index, "path": str(path), "size": list(size) if size else None})

    status = "ready-to-stitch" if not issues else "blocked"
    if apply and not issues:
        strip = Image.new("RGBA", expected_strip_size, (0, 0, 0, 0))
        for index in range(frame_count):
            path = tile_dir / f"frame_{index:03d}.png"
            with Image.open(path) as image:
                strip.alpha_composite(image.convert("RGBA"), (index * slot_px, 0))
        strip.save(out_path)
        status = "stitched"
    elif apply and issues:
        status = "blocked-not-stitched"

    report = {
        "schemaVersion": 1,
        "stage": "stage-4-tile-stitch",
        "generatedAt": utc_now(),
        "targetId": target.get("targetId"),
        "matrixKey": target.get("matrixKey"),
        "frameCount": frame_count,
        "slotPixels": slot_px,
        "expectedTileSize": list(expected_tile_size),
        "expectedStripSize": list(expected_strip_size),
        "tileDirectory": str(tile_dir),
        "rawStripOutput": str(out_path),
        "apply": apply,
        "status": status,
        "issues": issues,
        "frames": frames,
        "policy": "Only exact-size 4K frame tiles may be stitched into incoming/raw_strip.png.",
    }
    write_json(incoming / "tile_stitch_report.json", report)
    return report


def iter_target_dirs(stage4_root: Path, batch: int | None) -> list[Path]:
    pattern = f"batch_{batch:02d}_*/targets/*/target.json" if batch is not None else "batch_*/targets/*/target.json"
    return [path.parent for path in sorted(stage4_root.glob(pattern))]


def stitch_batch(stage4_root: Path, batch: int | None, apply: bool) -> dict[str, Any]:
    target_dirs = iter_target_dirs(stage4_root, batch)
    reports = [stitch(target_dir, apply) for target_dir in target_dirs]
    status_counts: dict[str, int] = {}
    missing_tiles = 0
    wrong_size_tiles = 0
    ready_targets = 0
    for report in reports:
        status = str(report["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        if not report["issues"]:
            ready_targets += 1
        for issue in report["issues"]:
            if "size None" in issue:
                missing_tiles += 1
            else:
                wrong_size_tiles += 1
    summary = {
        "schemaVersion": 1,
        "stage": "stage-4-batch-tile-stitch-audit",
        "generatedAt": utc_now(),
        "batch": batch,
        "apply": apply,
        "targetCount": len(reports),
        "readyTargetCount": ready_targets,
        "statusCounts": status_counts,
        "missingTileCount": missing_tiles,
        "wrongSizeTileCount": wrong_size_tiles,
        "reports": [
            {
                "targetId": report.get("targetId"),
                "matrixKey": report.get("matrixKey"),
                "status": report.get("status"),
                "issueCount": len(report.get("issues", [])),
                "rawStripOutput": report.get("rawStripOutput"),
            }
            for report in reports
        ],
        "policy": "Batch stitching writes raw strips only for targets whose full tile set passes exact-size checks.",
    }
    if batch is not None:
        batch_dirs = sorted(stage4_root.glob(f"batch_{batch:02d}_*"))
        out_dir = batch_dirs[0] if batch_dirs else stage4_root
    else:
        out_dir = stage4_root
    write_json(out_dir / "tile_stitch_index.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--target-dir", type=Path)
    group.add_argument("--batch", type=int, help="Audit/stitch all targets in a Stage 4 batch.")
    parser.add_argument("--stage4-root", type=Path, default=DEFAULT_STAGE4_ROOT)
    parser.add_argument("--apply", action="store_true", help="Write incoming/raw_strip.png when every tile passes.")
    args = parser.parse_args()
    if args.target_dir:
        report = stitch(args.target_dir, args.apply)
        print(json.dumps({"status": report["status"], "issues": report["issues"], "rawStripOutput": report["rawStripOutput"]}, indent=2))
    else:
        summary = stitch_batch(args.stage4_root, args.batch, args.apply)
        print(json.dumps({"batch": summary["batch"], "targetCount": summary["targetCount"], "readyTargetCount": summary["readyTargetCount"], "statusCounts": summary["statusCounts"], "missingTileCount": summary["missingTileCount"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
