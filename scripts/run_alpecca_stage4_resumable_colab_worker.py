"""Run a Stage 4 tile slice resumably and upload partial results.

This is intended for Colab/free GPU runtimes where disconnects are common. It
runs one selected job at a time through run_alpecca_stage4_tile_worker.py and
uploads the output root to Hugging Face after each job, so completed 4K tiles
survive even if the runtime dies before the whole 16-sector proof finishes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from preflight_alpecca_stage4_tile_worker import run_preflight
from run_alpecca_stage4_tile_worker import download_hf_file, load_jsonl, write_json


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HF_REPO = "CREATORJD/alpecca-art-library"
DEFAULT_HF_PATH = "stage4-tile-jobs/first_slices/idle_eye_16sector_frame000_turnaround/tile_jobs_idle_eye_16sector_frame000_turnaround.jsonl"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "worker_outputs_colab"
DEFAULT_OUTPUT_PREFIX = "stage4-worker-outputs/colab/idle_eye_16sector_frame000_turnaround"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_command(command: list[str], *, dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {"returnCode": 0, "dryRun": True, "command": command}
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    return {
        "returnCode": result.returncode,
        "command": command,
        "stdoutTail": result.stdout[-2000:],
        "stderrTail": result.stderr[-2000:],
    }


def upload_output_root(repo_id: str, repo_type: str, output_root: Path, output_prefix: str, *, dry_run: bool) -> dict[str, Any]:
    command = [
        "hf",
        "upload",
        repo_id,
        str(output_root),
        output_prefix,
        "--type",
        repo_type,
        "--commit-message",
        "Upload partial Alpecca Stage 4 resumable worker outputs",
    ]
    return run_command(command, dry_run=dry_run)


def run_resumable(
    *,
    hf_path: str,
    hf_repo: str,
    hf_repo_type: str,
    hf_revision: str | None,
    output_root: Path,
    output_prefix: str,
    offset: int,
    limit: int,
    target_id: str | None,
    timeout: int,
    upload_every: int,
    skip_existing: bool,
    fail_fast: bool,
    preflight: bool,
    dry_run: bool,
) -> dict[str, Any]:
    output_root = output_root if output_root.is_absolute() else REPO_ROOT / output_root
    output_root.mkdir(parents=True, exist_ok=True)
    jobs_path = download_hf_file(hf_repo, hf_path, hf_repo_type, hf_revision)
    all_jobs = load_jsonl(jobs_path)
    indexed_jobs = list(enumerate(all_jobs))
    if target_id:
        indexed_jobs = [
            (index, job)
            for index, job in indexed_jobs
            if str(job.get("targetId") or "") == target_id
        ]
        selected = [job for _, job in indexed_jobs]
    else:
        indexed_jobs = indexed_jobs[offset : offset + limit]
        selected = [job for _, job in indexed_jobs]
    preflight_report = None
    if preflight:
        if target_id:
            all_native_4096 = all(job.get("expectedSize") == [4096, 4096] for job in selected)
            ready = bool(selected) and all_native_4096
            preflight_report = {
                "schemaVersion": 1,
                "stage": "stage-4-target-filter-preflight",
                "generatedAt": utc_now(),
                "status": "ready" if ready else "blocked",
                "ready": ready,
                "blockingCount": 0 if ready else 1,
                "hfPath": hf_path,
                "targetId": target_id,
                "selectedJobs": len(selected),
                "frameIndexes": sorted(int(job.get("frameIndex") or 0) for job in selected),
                "allSelectedNative4096": all_native_4096,
                "nextStep": (
                    "Run the target-filtered worker."
                    if ready else
                    "Pick a targetId present in the selected HF job file with native 4096x4096 jobs."
                ),
            }
            write_json(output_root / "resumable_preflight_report.json", preflight_report)
        else:
            preflight_report = run_preflight(
                jobs=jobs_path,
                hf_path=None,
                hf_repo=hf_repo,
                hf_repo_type=hf_repo_type,
                hf_revision=hf_revision,
                offset=offset,
                limit=limit,
                report_path=output_root / "resumable_preflight_report.json",
                strict_native_4k=True,
            )
        if not preflight_report.get("ready"):
            return {
                "schemaVersion": 1,
                "stage": "stage-4-resumable-colab-worker",
                "generatedAt": utc_now(),
                "status": "blocked-preflight",
                "preflight": preflight_report,
                "records": [],
            }

    records: list[dict[str, Any]] = []
    uploads: list[dict[str, Any]] = []
    stopped = False
    target_manifest = None
    if target_id and selected:
        target_jobs_path = output_root / f"tile_jobs_{target_id}.jsonl"
        with target_jobs_path.open("w", encoding="utf-8") as handle:
            for job in selected:
                handle.write(json.dumps(job, ensure_ascii=True) + "\n")
        target_manifest = output_root / f"tile_job_manifest_{target_id}.json"
        write_json(target_manifest, {
            "schemaVersion": 1,
            "stage": "stage-4-target-filter-manifest",
            "generatedAt": utc_now(),
            "sourceHfPath": hf_path,
            "targetId": target_id,
            "jobCount": len(selected),
            "chunks": [{"file": str(target_jobs_path.relative_to(REPO_ROOT)).replace("\\", "/")}],
            "nextStep": "Use this manifest with import/process/stitch scripts after all target frames are generated.",
        })
    for local_index, (absolute_offset, job) in enumerate(indexed_jobs):
        command = [
            sys.executable,
            "scripts/run_alpecca_stage4_tile_worker.py",
            "--jobs",
            str(jobs_path),
            "--output-root",
            str(output_root),
            "--offset",
            str(absolute_offset),
            "--limit",
            "1",
            "--timeout",
            str(timeout),
        ]
        if skip_existing:
            command.append("--skip-existing")
        if fail_fast:
            command.append("--fail-fast")
        worker = run_command(command, dry_run=dry_run)
        record = {
            "jobId": job.get("jobId"),
            "matrixKey": job.get("matrixKey"),
            "offset": absolute_offset,
            "worker": worker,
        }
        records.append(record)
        should_upload = (local_index + 1) % max(1, upload_every) == 0 or local_index == len(selected) - 1
        if should_upload:
            upload = upload_output_root(hf_repo, hf_repo_type, output_root, output_prefix, dry_run=dry_run)
            upload["afterJobOffset"] = absolute_offset
            # QA checkpoint after every upload batch: validate what just went
            # up (run_alpecca_stage4_returned_slice_qa.py) so a session that
            # dies mid-run never leaves unvetted frames as the latest state.
            qa = run_command(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parent / "run_alpecca_stage4_returned_slice_qa.py"),
                    "--out-root",
                    str(output_root),
                ],
                dry_run=dry_run,
            )
            upload["qa"] = qa
            uploads.append(upload)
        if worker.get("returnCode") not in {0, None} and fail_fast:
            stopped = True
            break
    summary = {
        "schemaVersion": 1,
        "stage": "stage-4-resumable-colab-worker",
        "generatedAt": utc_now(),
        "status": "stopped" if stopped else "complete",
        "dryRun": dry_run,
        "hfPath": hf_path,
        "hfRepo": hf_repo,
        "outputRoot": str(output_root),
        "outputPrefix": output_prefix,
        "offset": offset,
        "limit": limit,
        "targetId": target_id,
        "selectedJobCount": len(selected),
        "uploadEvery": upload_every,
        "preflight": preflight_report,
        "targetManifest": str(target_manifest) if target_manifest else None,
        "records": records,
        "uploads": uploads,
        "nextStep": "Run process_alpecca_stage4_returned_slice.py with the target manifest after the returned prefix contains all target frames.",
    }
    write_json(output_root / "resumable_worker_report.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hf-path", default=DEFAULT_HF_PATH)
    parser.add_argument("--hf-repo", default=DEFAULT_HF_REPO)
    parser.add_argument("--hf-repo-type", default="dataset")
    parser.add_argument("--hf-revision")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=16)
    parser.add_argument("--target-id", help="Generate every frame for one targetId, such as gen-0149, instead of an offset slice.")
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--upload-every", type=int, default=1)
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", action="store_false", dest="skip_existing")
    parser.add_argument("--fail-fast", action="store_true", default=True)
    parser.add_argument("--no-fail-fast", action="store_false", dest="fail_fast")
    parser.add_argument("--preflight", action="store_true", default=True)
    parser.add_argument("--no-preflight", action="store_false", dest="preflight")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    summary = run_resumable(
        hf_path=args.hf_path,
        hf_repo=args.hf_repo,
        hf_repo_type=args.hf_repo_type,
        hf_revision=args.hf_revision,
        output_root=args.output_root,
        output_prefix=args.output_prefix,
        offset=args.offset,
        limit=args.limit,
        target_id=args.target_id,
        timeout=args.timeout,
        upload_every=args.upload_every,
        skip_existing=args.skip_existing,
        fail_fast=args.fail_fast,
        preflight=args.preflight,
        dry_run=args.dry_run,
    )
    print(json.dumps({
        "status": summary["status"],
        "dryRun": summary.get("dryRun", False),
        "selectedJobCount": summary.get("selectedJobCount", 0),
        "targetId": summary.get("targetId"),
        "targetManifest": summary.get("targetManifest"),
        "uploadCount": len(summary.get("uploads", [])),
        "outputRoot": summary.get("outputRoot"),
        "outputPrefix": summary.get("outputPrefix"),
        "nextStep": summary.get("nextStep"),
    }, indent=2))
    return 0 if summary["status"] in {"complete", "blocked-preflight"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
