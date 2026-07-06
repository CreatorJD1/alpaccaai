"""Audit returned Stage 4 target outputs without starting generation.

This script answers one practical question: does the Hugging Face art dataset
already contain every generated 4K frame for a target such as `gen-0149`?

It is intentionally read-only. Use it before rerunning ZeroGPU/Colab jobs, and
before calling process_alpecca_stage4_returned_target.py.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from run_alpecca_stage4_zerogpu_target import (
    DEFAULT_HF_PATH,
    DEFAULT_LOCAL_JOBS,
    DEFAULT_OUTPUT_PREFIX,
    DEFAULT_REPO_ID,
    DEFAULT_REPO_TYPE,
    DEFAULT_TARGET_ID,
    hf_existing_files,
    output_repo_file,
    selected_target_jobs,
    target_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "target_status"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def build_status(args: argparse.Namespace) -> dict[str, Any]:
    out_root = args.out_root if args.out_root.is_absolute() else REPO_ROOT / args.out_root
    out_root.mkdir(parents=True, exist_ok=True)
    local_jobs = args.local_jobs if args.local_jobs.is_absolute() else REPO_ROOT / args.local_jobs
    selected = selected_target_jobs(local_jobs, args.target_id)
    manifest_path = target_manifest(selected, out_root, args.target_id, args.hf_path) if selected else None
    existing = hf_existing_files(args.repo_id, args.repo_type, args.output_prefix)

    expected = [output_repo_file(args.output_prefix, job) for job in selected]
    present = [path for path in expected if path in existing]
    missing = [path for path in expected if path not in existing]
    frame_indexes = sorted(int(job.get("frameIndex") or 0) for job in selected)
    expected_frame_count = int(selected[0].get("frameCount") or len(selected)) if selected else 0
    complete_selection = bool(selected) and frame_indexes == list(range(expected_frame_count))
    complete_outputs = complete_selection and len(missing) == 0 and len(present) == expected_frame_count

    process_command = ""
    if manifest_path:
        process_command = (
            "python scripts\\process_alpecca_stage4_returned_target.py "
            f"--manifest {rel(manifest_path)} "
            f"--prefix {args.output_prefix} "
            f"--target-id {args.target_id} "
            "--out-root output\\alpecca_stage4_tile_jobs\\returned_targets "
            "--apply-import --apply-stitch"
        )

    generation_command = (
        "python scripts\\run_alpecca_stage4_zerogpu_target.py "
        f"--target-id {args.target_id} "
        f"--output-prefix {args.output_prefix} "
        f"--out-root output\\alpecca_stage4_tile_jobs\\zerogpu_target_runs\\{args.target_id}_walk_pose_guide "
        "--process-after"
    )

    return {
        "schemaVersion": 1,
        "stage": "stage-4-target-run-status",
        "generatedAt": utc_now(),
        "repoId": args.repo_id,
        "repoType": args.repo_type,
        "hfPath": args.hf_path,
        "localJobs": rel(local_jobs),
        "targetId": args.target_id,
        "outputPrefix": args.output_prefix,
        "selectedJobCount": len(selected),
        "expectedFrameCount": expected_frame_count,
        "frameIndexes": frame_indexes,
        "completeSelection": complete_selection,
        "expectedRepoFileCount": len(expected),
        "presentRepoFileCount": len(present),
        "missingRepoFileCount": len(missing),
        "completeOutputs": complete_outputs,
        "targetManifest": rel(manifest_path) if manifest_path else "",
        "presentRepoFiles": present,
        "missingRepoFiles": missing,
        "nextStep": (
            "Run the process command; all expected target frames are present."
            if complete_outputs
            else "Run or resume the generation command after GPU quota is available."
        ),
        "commands": {
            "generation": generation_command,
            "processReturnedTarget": process_command,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--repo-type", default=DEFAULT_REPO_TYPE)
    parser.add_argument("--hf-path", default=DEFAULT_HF_PATH)
    parser.add_argument("--local-jobs", type=Path, default=DEFAULT_LOCAL_JOBS)
    parser.add_argument("--target-id", default=DEFAULT_TARGET_ID)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()

    status = build_status(args)
    out_root = args.out_root if args.out_root.is_absolute() else REPO_ROOT / args.out_root
    report_path = out_root / f"target_run_status_{args.target_id}.json"
    write_json(report_path, status)
    print(json.dumps({
        "targetId": status["targetId"],
        "selectedJobCount": status["selectedJobCount"],
        "expectedFrameCount": status["expectedFrameCount"],
        "completeSelection": status["completeSelection"],
        "presentRepoFileCount": status["presentRepoFileCount"],
        "missingRepoFileCount": status["missingRepoFileCount"],
        "completeOutputs": status["completeOutputs"],
        "report": rel(report_path),
        "nextStep": status["nextStep"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
