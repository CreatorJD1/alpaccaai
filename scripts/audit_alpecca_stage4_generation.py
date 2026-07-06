"""Audit Alpecca Stage 4 generation workspaces.

This is a source-library QA helper. It verifies that prepared seed canvases are
really 4K source workspaces and reports which targets still need source
generation, QA approval, or runtime promotion.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_ROOT = REPO_ROOT / "data" / "alpecca_art_source"
DEFAULT_STAGE4_ROOT = DEFAULT_LIBRARY_ROOT / "stage4_generation_batches"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def image_size(path: Path) -> list[int] | None:
    if not path.exists():
        return None
    try:
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as image:
            return [int(image.width), int(image.height)]
    except Exception:
        return None


def target_status(target_dir: Path, target: dict[str, Any]) -> dict[str, Any]:
    frame_count = int(target["frameCount"])
    slot_px = int(target["slotPixels"])
    expected_size = [frame_count * slot_px, slot_px]
    seed_canvas = target_dir / "incoming" / "seed_canvas.png"
    pose_guides = target_dir / "incoming" / "pose_guides.png"
    raw_strip = target_dir / "incoming" / "raw_strip.png"
    approved_sheet = target_dir / "approved" / "spritesheet.png"
    atlas = target_dir / "approved" / "atlas.json"
    visual = target_dir / "approved" / "visual.json"

    seed_size = image_size(seed_canvas)
    pose_size = image_size(pose_guides)
    raw_size = image_size(raw_strip)
    approved_size = image_size(approved_sheet)

    seed_ready = seed_size == expected_size and pose_size == expected_size
    raw_ready = raw_size == expected_size
    approved_ready = approved_size is not None and atlas.exists() and visual.exists()

    if approved_ready:
        status = "approved-awaiting-runtime-compile"
    elif raw_ready:
        status = "generated-awaiting-qa"
    elif seed_ready:
        status = "seeded-awaiting-generation"
    elif seed_size or pose_size:
        status = "stale-seed-dimensions"
    else:
        status = "planned-generation"

    return {
        "targetId": target.get("targetId"),
        "matrixKey": target.get("matrixKey"),
        "batch": target.get("batch"),
        "batchName": target.get("batchName"),
        "action": target.get("action"),
        "verticalTier": target.get("verticalTier"),
        "horizontalTier": target.get("horizontalTier"),
        "viewSector16": target.get("viewSector16"),
        "frameCount": frame_count,
        "slotPixels": slot_px,
        "minimumSourceSlotPixels": int(target.get("minimumSourceSlotPixels") or slot_px),
        "runtimeSlotPixels": int(target.get("runtimeSlotPixels") or 512),
        "expectedSize": expected_size,
        "seedSize": seed_size,
        "poseGuideSize": pose_size,
        "rawStripSize": raw_size,
        "approvedSheetSize": approved_size,
        "status": status,
        "workspace": str(target_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, default=DEFAULT_LIBRARY_ROOT)
    parser.add_argument("--stage4-root", type=Path, default=DEFAULT_STAGE4_ROOT)
    parser.add_argument("--batch", type=int, default=None)
    args = parser.parse_args()

    pattern = f"batch_{args.batch:02d}_*/targets/*/target.json" if args.batch else "batch_*/targets/*/target.json"
    records: list[dict[str, Any]] = []
    for target_json in sorted(args.stage4_root.glob(pattern)):
        records.append(target_status(target_json.parent, load_json(target_json)))

    counts = Counter(record["status"] for record in records)
    report = {
        "schemaVersion": 1,
        "stage": "stage-4-generation-audit",
        "generatedAt": utc_now(),
        "batch": args.batch,
        "targetCount": len(records),
        "statusCounts": dict(sorted(counts.items())),
        "records": records,
    }
    out_path = args.library_root / "stage4_generation_audit.json"
    write_json(out_path, report)
    print(f"Audited {len(records)} Stage 4 target(s) -> {out_path}")
    print(f"Status: {dict(sorted(counts.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
