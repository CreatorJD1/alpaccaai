"""Audit Alpecca Stage 4 art status across queued, draft, and generated assets."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE4_ROOT = REPO_ROOT / "data" / "alpecca_art_source" / "stage4_generation_batches"
DEFAULT_GENERATED_ROOT = REPO_ROOT / "data" / "alpecca_generated_art"
DEFAULT_QUEUE = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "stage4_generation_queue.json"
DEFAULT_OUT = REPO_ROOT / "output" / "alpecca_stage4_art_status.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def count_files(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return sum(1 for _ in root.rglob(pattern))


def draft_manifests(generated_root: Path) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    if not generated_root.exists():
        return manifests
    for path in sorted(generated_root.rglob("manifest.json")):
        try:
            data = load_json(path)
        except Exception:
            continue
        if str(data.get("stage") or "").startswith("stage-4"):
            manifests.append({
                "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "stage": data.get("stage"),
                "status": data.get("status"),
                "viewCount": data.get("viewCount"),
                "actualSize": data.get("actualSize"),
                "turnaroundImage": data.get("turnaroundImage"),
            })
    return manifests


def local_attempts(queue_path: Path) -> list[dict[str, Any]]:
    attempts_root = queue_path.parent / "local_attempts"
    attempts: list[dict[str, Any]] = []
    if not attempts_root.exists():
        return attempts
    for path in sorted(attempts_root.glob("*.json")):
        try:
            data = load_json(path)
        except Exception:
            continue
        attempts.append({
            "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "stage": data.get("stage"),
            "target": data.get("target"),
            "mode": data.get("mode"),
            "result": data.get("result"),
            "durationSeconds": data.get("durationSeconds"),
            "interpretation": data.get("interpretation"),
        })
    return attempts


def audit(stage4_root: Path, generated_root: Path, queue_path: Path) -> dict[str, Any]:
    queue = load_json(queue_path) if queue_path.exists() else {}
    raw_strips = count_files(stage4_root, "raw_strip.png")
    approved_sheets = count_files(stage4_root, "spritesheet.png")
    seed_canvases = count_files(stage4_root, "seed_canvas.png")
    frame_tiles = count_files(stage4_root, "frame_*.png")
    targets = count_files(stage4_root, "target.json")
    drafts = draft_manifests(generated_root)
    attempts = local_attempts(queue_path)
    return {
        "schemaVersion": 1,
        "stage": "alpecca-stage4-art-status",
        "generatedAt": utc_now(),
        "targetCount": targets,
        "seedCanvasCount": seed_canvases,
        "draftReferenceCount": len(drafts),
        "localAttemptCount": len(attempts),
        "rawStripCount": raw_strips,
        "approvedSpritesheetCount": approved_sheets,
        "importedFrameTileCount": frame_tiles,
        "queue": {
            "path": str(queue_path.relative_to(REPO_ROOT)).replace("\\", "/") if queue_path.exists() else "",
            "targetCount": queue.get("targetCount", 0),
            "jobCount": queue.get("jobCount", 0),
            "chunkCount": queue.get("chunkCount", 0),
            "requiredTileSize": queue.get("requiredTileSize", [4096, 4096]),
        },
        "promotionReadiness": {
            "hasFullQueue": queue.get("targetCount") == targets and int(queue.get("jobCount") or 0) > 400,
            "hasDraftReferences": bool(drafts),
            "hasProductionRawStrips": raw_strips > 0,
            "hasApprovedRuntimeCandidates": approved_sheets > 0,
            "complete": raw_strips >= targets and approved_sheets >= targets,
        },
        "draftReferences": drafts,
        "localAttempts": attempts,
        "nextRequiredStep": (
            "Generate exact 4096x4096 PNG frame tiles from the queue, import them, stitch raw_strip.png, "
            "then QA and approve runtime atlases."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage4-root", type=Path, default=DEFAULT_STAGE4_ROOT)
    parser.add_argument("--generated-root", type=Path, default=DEFAULT_GENERATED_ROOT)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    report = audit(args.stage4_root, args.generated_root, args.queue)
    write_json(args.out, report)
    print(json.dumps({
        "targets": report["targetCount"],
        "draftReferences": report["draftReferenceCount"],
        "rawStrips": report["rawStripCount"],
        "queueJobs": report["queue"]["jobCount"],
        "out": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
