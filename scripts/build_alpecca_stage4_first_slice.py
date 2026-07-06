"""Build focused first-slice Stage 4 tile job packages.

The full Alpecca Stage 4 queue is intentionally large. This helper creates
small, meaningful proof slices from the exported queue so a GPU runtime can
generate one complete 16-sector set before we spend time on all 6048 tiles.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JOBS_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs"
DEFAULT_OUT_ROOT = DEFAULT_JOBS_ROOT / "first_slices"
SECTORS_16 = tuple(f"s{i}" for i in range(16))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def repo_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def load_all_jobs(queue_path: Path) -> list[dict[str, Any]]:
    queue = load_json(queue_path)
    rows: list[dict[str, Any]] = []
    for chunk in queue.get("chunks", []):
        chunk_path = repo_path(str(chunk.get("file") or ""))
        rows.extend(iter_jsonl(chunk_path))
    return rows


def select_slice_jobs(jobs: list[dict[str, Any]], action: str, vertical: str, frame_index: int | None) -> list[dict[str, Any]]:
    selected = [
        job
        for job in jobs
        if str(job.get("action")) == action
        and str(job.get("verticalTier")) == vertical
        and str(job.get("viewSector16")) in SECTORS_16
        and (frame_index is None or int(job.get("frameIndex") or 0) == frame_index)
    ]
    selected.sort(key=lambda job: (int(str(job.get("viewSector16", "s0")).removeprefix("s")), int(job.get("frameIndex") or 0)))
    sectors = {str(job.get("viewSector16")) for job in selected}
    if sectors != set(SECTORS_16):
        missing = sorted(set(SECTORS_16) - sectors, key=lambda value: int(value[1:]))
        raise RuntimeError(f"Slice {action}/{vertical} missing sectors: {missing}")
    return selected


def write_slice(jobs_root: Path, out_root: Path, action: str, vertical: str, frame_index: int | None) -> dict[str, Any]:
    queue_path = jobs_root / "stage4_generation_queue.json"
    jobs = load_all_jobs(queue_path)
    selected = select_slice_jobs(jobs, action, vertical, frame_index)
    slice_name = (
        f"{action}_{vertical}_16sector_frame{frame_index:03d}_turnaround"
        if frame_index is not None
        else f"{action}_{vertical}_16sector_full_loop"
    )
    slice_dir = out_root / slice_name
    jsonl_path = slice_dir / f"tile_jobs_{slice_name}.jsonl"
    manifest_path = slice_dir / "tile_job_manifest.json"
    readme_path = slice_dir / "README.md"
    write_jsonl(jsonl_path, selected)
    target_ids = sorted({str(job.get("targetId")) for job in selected})
    frame_counts = sorted({int(job.get("frameCount") or 0) for job in selected})
    manifest = {
        "schemaVersion": 1,
        "stage": "stage-4-first-production-slice",
        "generatedAt": utc_now(),
        "name": slice_name,
        "purpose": (
            "Generate one 16-sector still-turnaround proof before scaling to full loops."
            if frame_index is not None
            else "Generate one complete 16-sector proof loop before scaling to all Stage 4 art."
        ),
        "action": action,
        "verticalTier": vertical,
        "frameIndexFilter": frame_index,
        "sectorCount": 16,
        "sectors": list(SECTORS_16),
        "targetCount": len(target_ids),
        "targetIds": target_ids,
        "jobCount": len(selected),
        "frameCounts": frame_counts,
        "requiredTileSize": [4096, 4096],
        "chunks": [{"index": 0, "file": rel(jsonl_path), "jobCount": len(selected)}],
        "sourceQueue": rel(queue_path),
        "outputConvention": "Workers write generated PNGs under outputs/<targetId>/frame_000.png, then importer/stitcher/QA handle promotion.",
        "promotionPolicy": "Not complete until every sector target has all frames, raw_strip.png exists, visual QA passes, and Stage 5 compiles approved runtime atlases.",
    }
    write_json(manifest_path, manifest)
    readme_path.write_text(
        f"""# Alpecca First Production Slice: {slice_name}

This slice contains {"one frame from each of 16 sectors" if frame_index is not None else f"one complete 16-sector `{action}` loop"} at `{vertical}` camera height.

- Targets: {len(target_ids)}
- Tile jobs: {len(selected)}
- Required tile size: 4096 x 4096
- Sectors: s0 through s15

Generate this slice before attempting the full 6048-job queue. It proves that
Alpecca can rotate with body volume around the player instead of staying flat.

Colab/HF path in the dataset:

```text
stage4-tile-jobs/first_slices/{slice_name}/tile_jobs_{slice_name}.jsonl
```

Local QA after remote outputs return:

```powershell
python scripts\\qa_alpecca_stage4_tile_outputs.py --manifest {rel(manifest_path)} --outputs-root <returned-output-root>
python scripts\\import_alpecca_stage4_tile_outputs.py --manifest {rel(manifest_path)} --outputs-root <returned-output-root> --apply
python scripts\\stitch_alpecca_stage4_tiles.py --batch 1 --apply
python scripts\\compile_alpecca_stage5_runtime_atlases.py
```
""",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-root", type=Path, default=DEFAULT_JOBS_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--action", default="idle")
    parser.add_argument("--vertical", default="eye")
    parser.add_argument("--frame-index", type=int, help="Optional single frame index from every sector.")
    args = parser.parse_args()
    manifest = write_slice(args.jobs_root, args.out_root, args.action, args.vertical, args.frame_index)
    print(
        json.dumps(
            {
                "name": manifest["name"],
                "targetCount": manifest["targetCount"],
                "jobCount": manifest["jobCount"],
                "manifest": str(args.out_root / manifest["name"] / "tile_job_manifest.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
