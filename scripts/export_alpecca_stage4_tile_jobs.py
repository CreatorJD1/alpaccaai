"""Export Stage 4 tile prompts as portable JSONL generation jobs.

These jobs are meant for Colab, Hugging Face Jobs/Spaces, or any external image
generation worker. The exporter does not generate art. It packages prompt text,
reference paths, expected output paths, and import destinations so returned
4096x4096 tiles can be validated and copied back safely.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE4_ROOT = REPO_ROOT / "data" / "alpecca_art_source" / "stage4_generation_batches"
DEFAULT_OUT_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs"
REFERENCE_BOARD_PATHS = [
    "data/alpecca_art_source/reference_boards/identity_turnaround_lock.jpg",
    "data/alpecca_art_source/reference_boards/movement_direction_reference.jpg",
    "data/alpecca_art_source/reference_boards/expression_talk_reference.jpg",
    "data/alpecca_art_source/reference_boards/scale_anchor_reference.jpg",
    "data/alpecca_art_source/external_360_references/external_360_reference_preview.jpg",
    "data/alpecca_art_source/external_360_references/manifest.json",
    "data/alpecca_art_source/external_walk_cycle_references/walk_cycle_3d_pose_guide.jpg",
    "data/alpecca_art_source/external_walk_cycle_references/manifest.json",
    "docs/ALPECCA_STAGE4_WALK_CYCLE_POSE_LOCK.md",
    "data/alpecca_art_source/ALPECCA_DESIGN_LOCK.md",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def batch_dir(stage4_root: Path, batch: int) -> Path:
    matches = sorted(stage4_root.glob(f"batch_{batch:02d}_*"))
    if not matches:
        raise FileNotFoundError(f"No Stage 4 batch directory found for batch {batch}")
    return matches[0]


def build_jobs(batch_path: Path, batch: int) -> list[dict[str, Any]]:
    index_path = batch_path / "tile_generation_index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"Missing tile generation index: {index_path}")
    index = load_json(index_path)
    jobs: list[dict[str, Any]] = []
    for target_summary in index.get("targets", []):
        target_id = str(target_summary["targetId"])
        tile_dir = Path(str(target_summary["tileDirectory"]))
        if not tile_dir.is_absolute():
            tile_dir = REPO_ROOT / tile_dir
        target_dir = tile_dir.parent.parent
        target = load_json(target_dir / "target.json")
        request = load_json(target_dir / "generation_request.json")
        plan = load_json(target_dir / "incoming" / "tile_generation_plan.json")
        action = str(target.get("action") or "")
        seed_condition_policy = (
            "reference-only-no-img2img-for-single-sprite-proof"
            if action in {"walk", "idle", "listen", "talk", "wave"}
            else "allowed-if-single-subject"
        )
        for frame in plan.get("frames", []):
            frame_index = int(frame["index"])
            prompt_path = Path(str(frame["prompt"]))
            expected_tile = Path(str(frame["expectedTile"]))
            if not prompt_path.is_absolute():
                prompt_path = REPO_ROOT / prompt_path
            if not expected_tile.is_absolute():
                expected_tile = REPO_ROOT / expected_tile
            job_id = f"{target_id}_frame_{frame_index:03d}"
            output_relative = f"outputs/{target_id}/{expected_tile.name}"
            jobs.append(
                {
                    "schemaVersion": 1,
                    "stage": "stage-4-4k-frame-tile-job",
                    "batch": batch,
                    "jobId": job_id,
                    "targetId": target_id,
                    "matrixKey": target.get("matrixKey"),
                    "action": action,
                    "verticalTier": target.get("verticalTier"),
                    "horizontalTier": target.get("horizontalTier"),
                    "viewSector16": target.get("viewSector16"),
                    "frameIndex": frame_index,
                    "frameCount": target.get("frameCount"),
                    "slotPixels": target.get("slotPixels"),
                    "expectedSize": frame.get("size"),
                    "prompt": prompt_path.read_text(encoding="utf-8"),
                    "poseNote": frame.get("poseNote"),
                    "referenceFiles": REFERENCE_BOARD_PATHS,
                    "seedCanvas": rel(Path(str(request["files"]["seedCanvas"]))),
                    "seedConditionPolicy": seed_condition_policy,
                    "poseGuides": rel(Path(str(request["files"]["poseGuides"]))),
                    "promptFile": rel(prompt_path),
                    "targetJson": rel(target_dir / "target.json"),
                    "generationRequest": rel(target_dir / "generation_request.json"),
                    "expectedWorkerOutput": output_relative,
                    "stage4ImportDestination": rel(expected_tile),
                    "rawStripOutput": rel(Path(str(plan["rawStripOutput"]))),
                    "policy": "Generate one exact 4096x4096 PNG tile. Do not approve or stitch outside the Stage 4 importer/stitcher.",
                }
            )
    return jobs


def export_jobs(stage4_root: Path, batch: int, out_root: Path, chunk_size: int) -> dict[str, Any]:
    batch_path = batch_dir(stage4_root, batch)
    jobs = build_jobs(batch_path, batch)
    out_dir = out_root / f"batch_{batch:02d}"
    chunks: list[dict[str, Any]] = []
    for chunk_index, start in enumerate(range(0, len(jobs), chunk_size)):
        chunk_jobs = jobs[start : start + chunk_size]
        chunk_path = out_dir / f"tile_jobs_batch_{batch:02d}_chunk_{chunk_index:03d}.jsonl"
        count = write_jsonl(chunk_path, chunk_jobs)
        chunks.append({"index": chunk_index, "file": rel(chunk_path), "jobCount": count})
    manifest = {
        "schemaVersion": 1,
        "stage": "stage-4-tile-job-export",
        "generatedAt": utc_now(),
        "batch": batch,
        "batchDirectory": rel(batch_path),
        "jobCount": len(jobs),
        "chunkSize": chunk_size,
        "chunkCount": len(chunks),
        "chunks": chunks,
        "outputConvention": "Workers write generated PNGs under outputs/<targetId>/frame_000.png, then import_alpecca_stage4_tile_outputs.py validates and copies them into Stage 4.",
        "requiredTileSize": [4096, 4096],
        "referenceFiles": REFERENCE_BOARD_PATHS,
    }
    write_json(out_dir / "tile_job_manifest.json", manifest)
    (out_dir / "README.md").write_text(
        "# Alpecca Stage 4 Tile Jobs\n\n"
        "Generate each JSONL job's `expectedWorkerOutput` as an exact 4096x4096 PNG.\n"
        "Do not stitch or approve outputs in the worker. Return the `outputs/` folder,\n"
        "then run `python scripts/import_alpecca_stage4_tile_outputs.py --manifest <manifest> --outputs-root <outputs> --apply`.\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, required=True)
    parser.add_argument("--stage4-root", type=Path, default=DEFAULT_STAGE4_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--chunk-size", type=int, default=64)
    args = parser.parse_args()
    manifest = export_jobs(args.stage4_root, args.batch, args.out_root, args.chunk_size)
    print(json.dumps({"batch": manifest["batch"], "jobCount": manifest["jobCount"], "chunkCount": manifest["chunkCount"], "manifest": manifest["chunks"][0]["file"] if manifest["chunks"] else ""}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
