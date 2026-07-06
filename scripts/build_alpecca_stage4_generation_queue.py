"""Build a top-level Stage 4 generation queue manifest.

The per-batch exporters create JSONL chunks. This script creates one
authoritative queue file for Hugging Face, Colab, or local workers so the whole
Alpecca 16-sector art library can be generated in order without guessing which
folders are real batches.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JOBS_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs"
DEFAULT_STAGE4_ROOT = REPO_ROOT / "data" / "alpecca_art_source" / "stage4_generation_batches"

PRIORITY_ORDER = {
    "batch_01": 1,
    "batch_02": 2,
    "batch_07": 3,
    "batch_08": 4,
    "batch_09": 5,
    "batch_03": 6,
    "batch_04": 7,
    "batch_10": 8,
    "batch_05": 9,
    "batch_11": 10,
    "batch_12": 11,
    "batch_06": 12,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def real_batch_dirs(jobs_root: Path) -> list[Path]:
    out: list[Path] = []
    for path in sorted(jobs_root.glob("batch_[0-9][0-9]")):
        if (path / "tile_job_manifest.json").exists():
            out.append(path)
    return out


def target_counts(stage4_root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(stage4_root.glob("batch_[0-9][0-9]_*")):
        key = path.name[:8]
        counts[key] = len(list((path / "targets").glob("*/target.json")))
    return counts


def build_queue(jobs_root: Path, stage4_root: Path) -> dict[str, Any]:
    counts = target_counts(stage4_root)
    batches: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    total_jobs = 0
    total_chunks = 0

    for batch_dir in real_batch_dirs(jobs_root):
        manifest = load_json(batch_dir / "tile_job_manifest.json")
        batch_key = batch_dir.name[:8]
        batch_chunks = []
        for chunk in manifest.get("chunks", []):
            chunk_file = str(chunk.get("file") or "")
            record = {
                "batch": batch_dir.name,
                "batchNumber": int(batch_dir.name.removeprefix("batch_")),
                "priority": PRIORITY_ORDER.get(batch_key, 99),
                "chunkIndex": int(chunk.get("index") or 0),
                "jobCount": int(chunk.get("jobCount") or 0),
                "file": chunk_file,
                "workerCommand": (
                    "python scripts/run_alpecca_stage4_tile_worker.py "
                    f"--jobs {chunk_file} --output-root output/alpecca_stage4_tile_jobs/worker_outputs "
                    "--skip-existing"
                ),
            }
            batch_chunks.append(record)
            chunks.append(record)
        batches.append(
            {
                "batch": batch_dir.name,
                "batchNumber": int(batch_dir.name.removeprefix("batch_")),
                "priority": PRIORITY_ORDER.get(batch_key, 99),
                "targetCount": counts.get(batch_key, 0),
                "jobCount": int(manifest.get("jobCount") or 0),
                "chunkCount": int(manifest.get("chunkCount") or len(batch_chunks)),
                "requiredTileSize": manifest.get("requiredTileSize") or [4096, 4096],
                "manifest": rel(batch_dir / "tile_job_manifest.json"),
                "chunks": batch_chunks,
            }
        )
        total_jobs += int(manifest.get("jobCount") or 0)
        total_chunks += int(manifest.get("chunkCount") or len(batch_chunks))

    chunks.sort(key=lambda row: (row["priority"], row["batchNumber"], row["chunkIndex"]))
    batches.sort(key=lambda row: (row["priority"], row["batchNumber"]))
    return {
        "schemaVersion": 1,
        "stage": "alpecca-stage4-generation-queue",
        "generatedAt": utc_now(),
        "jobsRoot": rel(jobs_root),
        "stage4Root": rel(stage4_root),
        "targetCount": sum(int(batch.get("targetCount") or 0) for batch in batches),
        "jobCount": total_jobs,
        "chunkCount": total_chunks,
        "requiredTileSize": [4096, 4096],
        "sourceResolutionPolicy": "Every worker output must be an exact 4096x4096 PNG tile before import/stitch. 8K variants can be added as a later source-only pass.",
        "runtimePolicy": "Do not load loose 4K tiles in the browser. Import, stitch raw strips, QA, then compile approved runtime atlases.",
        "storagePolicy": "Source/generated art belongs on Hugging Face datasets. Cloudflare hosts only the app shell and browser-safe runtime assets.",
        "priorityOrder": [
            "standing/talk/listen foundation",
            "walk 16-sector foundation",
            "mouth and eye overlays",
            "head/hair dynamics",
            "wave and action states",
            "rest, shadow, halo, and emotional overlays",
        ],
        "batches": batches,
        "chunks": chunks,
    }


def write_readme(jobs_root: Path, queue: dict[str, Any]) -> None:
    lines = [
        "# Alpecca Stage 4 Generation Queue",
        "",
        f"- Targets: {queue['targetCount']}",
        f"- 4K tile jobs: {queue['jobCount']}",
        f"- JSONL chunks: {queue['chunkCount']}",
        f"- Required tile size: {queue['requiredTileSize'][0]} x {queue['requiredTileSize'][1]}",
        "",
        "Use `stage4_generation_queue.json` as the source of truth for local, Colab, or Hugging Face workers.",
        "Generated outputs are not approved art. They must be imported, stitched into `raw_strip.png`, QA checked, and only then compiled into runtime atlases.",
        "",
        "Example worker command from a queue chunk:",
        "",
        "```powershell",
        "python scripts/run_alpecca_stage4_tile_worker.py --jobs output/alpecca_stage4_tile_jobs/batch_02/tile_jobs_batch_02_chunk_000.jsonl --output-root output/alpecca_stage4_tile_jobs/worker_outputs --skip-existing",
        "```",
        "",
        "Cloudflare should not store this source art. Upload queue files and generated outputs to Hugging Face dataset storage.",
    ]
    (jobs_root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-root", type=Path, default=DEFAULT_JOBS_ROOT)
    parser.add_argument("--stage4-root", type=Path, default=DEFAULT_STAGE4_ROOT)
    args = parser.parse_args()
    queue = build_queue(args.jobs_root, args.stage4_root)
    write_json(args.jobs_root / "stage4_generation_queue.json", queue)
    write_readme(args.jobs_root, queue)
    print(json.dumps({
        "targetCount": queue["targetCount"],
        "jobCount": queue["jobCount"],
        "chunkCount": queue["chunkCount"],
        "queue": rel(args.jobs_root / "stage4_generation_queue.json"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
