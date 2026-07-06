"""Gate, import, and optionally stitch a returned Alpecca Stage 4 slice.

This is the safe bridge after GPU generation. It can process a local returned
worker-output folder, or a folder downloaded by run_alpecca_stage4_returned_slice_qa.
It refuses to import if the mechanical, 16-sector visual, or 360-volume gates
are blocked.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from import_alpecca_stage4_tile_outputs import import_outputs, load_jobs, resolve_repo_path
    from qa_alpecca_stage4_360_volume import run_volume_qa
    from qa_alpecca_stage4_tile_outputs import qa_outputs
    from qa_alpecca_stage4_turnaround_outputs import qa_turnaround
    from stitch_alpecca_stage4_tiles import stitch
except ModuleNotFoundError:
    from scripts.import_alpecca_stage4_tile_outputs import import_outputs, load_jobs, resolve_repo_path
    from scripts.qa_alpecca_stage4_360_volume import run_volume_qa
    from scripts.qa_alpecca_stage4_tile_outputs import qa_outputs
    from scripts.qa_alpecca_stage4_turnaround_outputs import qa_turnaround
    from scripts.stitch_alpecca_stage4_tiles import stitch


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "output"
    / "alpecca_stage4_tile_jobs"
    / "first_slices"
    / "idle_eye_16sector_frame000_turnaround"
    / "tile_job_manifest.json"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def target_frame_coverage(manifest: Path) -> dict[str, Any]:
    jobs = load_jobs(manifest)
    by_target: dict[str, set[int]] = defaultdict(set)
    expected_counts: dict[str, int] = {}
    target_dirs: dict[str, str] = {}
    for job in jobs:
        target_id = str(job.get("targetId") or "")
        by_target[target_id].add(int(job.get("frameIndex") or 0))
        expected_counts[target_id] = max(int(job.get("frameCount") or 1), expected_counts.get(target_id, 0))
        target_dirs[target_id] = str(resolve_repo_path(str(job.get("targetJson"))).parent)
    records = []
    full_target_ids = []
    partial_target_ids = []
    for target_id, frames in sorted(by_target.items()):
        expected = expected_counts.get(target_id, 0)
        full = len(frames) >= expected and expected > 0
        if full:
            full_target_ids.append(target_id)
        else:
            partial_target_ids.append(target_id)
        records.append({
            "targetId": target_id,
            "frameIndexes": sorted(frames),
            "sliceFrameCount": len(frames),
            "expectedTargetFrameCount": expected,
            "fullTargetInSlice": full,
            "targetDir": target_dirs.get(target_id),
        })
    return {
        "targetCount": len(records),
        "fullTargetCount": len(full_target_ids),
        "partialTargetCount": len(partial_target_ids),
        "fullTargetIds": full_target_ids,
        "partialTargetIds": partial_target_ids,
        "records": records,
    }


def process_slice(
    *,
    manifest: Path,
    outputs_root: Path,
    out_root: Path,
    frame_index: int,
    apply_import: bool,
    apply_stitch: bool,
) -> dict[str, Any]:
    qa_root = out_root / "qa"
    turnaround = qa_turnaround(manifest, outputs_root, qa_root, frame_index=frame_index, thumb_size=384)
    volume = run_volume_qa(manifest, outputs_root, qa_root / "turnaround_360_volume_report.json", frame_index=frame_index)
    tile = qa_outputs(manifest, outputs_root, qa_root / "tile_mechanical", target_id=None, thumb_size=256)
    coverage = target_frame_coverage(manifest)
    gates_pass = (
        turnaround.get("mechanicalStatus") == "ready-for-visual-review"
        and volume.get("status") == "pass"
        and int(tile.get("missingJobCount") or 0) == 0
        and int(tile.get("blockedJobCount") or 0) == 0
    )

    import_report = None
    if gates_pass and apply_import:
        import_report = import_outputs(manifest, outputs_root, apply=True)

    stitch_reports: list[dict[str, Any]] = []
    if gates_pass and apply_import and apply_stitch:
        for record in coverage["records"]:
            if not record["fullTargetInSlice"]:
                stitch_reports.append({
                    "targetId": record["targetId"],
                    "status": "skipped-partial-slice",
                    "reason": (
                        f"slice has {record['sliceFrameCount']} of "
                        f"{record['expectedTargetFrameCount']} frames"
                    ),
                })
                continue
            stitch_reports.append(stitch(Path(record["targetDir"]), apply=True))

    summary = {
        "schemaVersion": 1,
        "stage": "stage-4-returned-slice-process",
        "generatedAt": utc_now(),
        "manifest": str(manifest),
        "outputsRoot": str(outputs_root),
        "outRoot": str(out_root),
        "frameIndex": frame_index,
        "applyImport": apply_import,
        "applyStitch": apply_stitch,
        "gatesPass": gates_pass,
        "turnaround": {
            "mechanicalStatus": turnaround.get("mechanicalStatus"),
            "sectorCount": turnaround.get("sectorCount"),
            "readySectorCount": turnaround.get("readySectorCount"),
            "blockedSectorCount": turnaround.get("blockedSectorCount"),
            "preview": turnaround.get("preview"),
        },
        "volume": {
            "status": volume.get("status"),
            "readySectorCount": volume.get("readySectorCount"),
            "issues": volume.get("issues"),
            "metrics": volume.get("metrics"),
        },
        "tile": {
            "jobCount": tile.get("jobCount"),
            "readyJobCount": tile.get("readyJobCount"),
            "missingJobCount": tile.get("missingJobCount"),
            "blockedJobCount": tile.get("blockedJobCount"),
        },
        "coverage": coverage,
        "import": {
            "ran": import_report is not None,
            "importedCount": import_report.get("importedCount") if import_report else 0,
            "readyCount": import_report.get("readyCount") if import_report else 0,
        },
        "stitch": {
            "ran": bool(stitch_reports),
            "reports": stitch_reports,
        },
        "nextStep": (
            "Inspect imported frame tiles. Run the full-loop 16-sector slice before stitching raw strips."
            if gates_pass and apply_import and coverage["partialTargetCount"]
            else "Fix missing/blocked/flat outputs before import."
            if not gates_pass
            else "Run stitch/Stage 5 only after full targets have approved spritesheets."
        ),
    }
    write_json(out_root / "returned_slice_process_report.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--outputs-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path)
    parser.add_argument("--frame-index", type=int, default=0)
    parser.add_argument("--apply-import", action="store_true")
    parser.add_argument("--apply-stitch", action="store_true")
    args = parser.parse_args()
    out_root = args.out_root or args.outputs_root
    summary = process_slice(
        manifest=args.manifest,
        outputs_root=args.outputs_root,
        out_root=out_root,
        frame_index=args.frame_index,
        apply_import=args.apply_import,
        apply_stitch=args.apply_stitch,
    )
    print(json.dumps({
        "gatesPass": summary["gatesPass"],
        "import": summary["import"],
        "coverage": {
            "fullTargetCount": summary["coverage"]["fullTargetCount"],
            "partialTargetCount": summary["coverage"]["partialTargetCount"],
        },
        "nextStep": summary["nextStep"],
        "report": str(out_root / "returned_slice_process_report.json"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
