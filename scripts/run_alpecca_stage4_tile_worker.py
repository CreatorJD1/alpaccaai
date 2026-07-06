"""Run Alpecca Stage 4 4K tile generation jobs.

This worker is intentionally generator-agnostic. It reads exported Stage 4
JSONL jobs from disk or Hugging Face, writes each prompt/job payload to a small
workspace folder, and optionally calls an external image-generation command.

The worker never approves art and never writes into the Stage 4 source tree.
Generated images stay under an outputs folder until
import_alpecca_stage4_tile_outputs.py validates exact 4096x4096 alpha PNG tiles.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "worker_outputs"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                jobs.append(json.loads(line))
    return jobs


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def resolve_repo_path(path: str | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def download_hf_file(repo_id: str, repo_path: str, repo_type: str, revision: str | None) -> Path:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as error:
        raise SystemExit(
            "huggingface_hub is required for --hf-repo. Install with: pip install huggingface_hub"
        ) from error
    downloaded = hf_hub_download(
        repo_id=repo_id,
        filename=repo_path,
        repo_type=repo_type,
        revision=revision,
    )
    return Path(downloaded)


def image_status(path: Path, expected_size: tuple[int, int]) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "ready": False, "issues": ["missing"]}
    try:
        with Image.open(path) as image:
            bands = image.getbands()
            has_alpha = "A" in bands or image.mode in {"LA", "PA"}
            issues: list[str] = []
            if tuple(image.size) != expected_size:
                issues.append(f"wrong-size:{list(image.size)}")
            if not has_alpha:
                issues.append("no-alpha")
            return {
                "exists": True,
                "ready": not issues,
                "issues": issues,
                "size": list(image.size),
                "mode": image.mode,
                "hasAlpha": has_alpha,
            }
    except Exception as error:
        return {"exists": True, "ready": False, "issues": [f"unreadable:{error}"]}


def command_parts(command: str, replacements: dict[str, str]) -> list[str]:
    expanded = command.format(**replacements)
    if os.name == "nt":
        return expanded
    return shlex.split(expanded)


def run_job_command(command: str, replacements: dict[str, str], timeout: int) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command_parts(command, replacements),
            cwd=REPO_ROOT,
            shell=os.name == "nt",
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "returnCode": result.returncode,
            "stdoutTail": result.stdout[-2000:],
            "stderrTail": result.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as error:
        return {
            "returnCode": None,
            "timedOut": True,
            "stdoutTail": (error.stdout or "")[-2000:] if isinstance(error.stdout, str) else "",
            "stderrTail": (error.stderr or "")[-2000:] if isinstance(error.stderr, str) else "",
        }


def worker_run(
    jobs_path: Path,
    output_root: Path,
    command: str | None,
    offset: int,
    limit: int | None,
    skip_existing: bool,
    timeout: int,
    fail_fast: bool,
) -> dict[str, Any]:
    all_jobs = load_jsonl(jobs_path)
    selected_jobs = all_jobs[offset : offset + limit if limit is not None else None]
    prompt_root = output_root / "_worker_prompts"
    records: list[dict[str, Any]] = []
    generated = 0
    ready = 0
    skipped = 0
    failed = 0

    def flush(status: str, active_job: str = "") -> None:
        write_json(output_root / "worker_report.json", {
            "schemaVersion": 1,
            "stage": "stage-4-tile-worker-run",
            "generatedAt": utc_now(),
            "jobsPath": str(jobs_path),
            "outputRoot": str(output_root),
            "offset": offset,
            "limit": limit,
            "selectedJobCount": len(selected_jobs),
            "generatedCount": generated,
            "readyCount": ready,
            "skippedCount": skipped,
            "failedCount": failed,
            "commandConfigured": bool(command),
            "status": status,
            "activeJob": active_job,
            "records": records,
            "nextStep": "Run import_alpecca_stage4_tile_outputs.py against this output root, then stitch and QA approved strips.",
        })

    flush("started")

    for job in selected_jobs:
        job_id = str(job["jobId"])
        expected_size = tuple(int(value) for value in job.get("expectedSize", [4096, 4096]))
        output_path = output_root / str(job["expectedWorkerOutput"]).replace("/", os.sep)
        job_dir = prompt_root / job_id
        prompt_path = job_dir / "prompt.md"
        job_json_path = job_dir / "job.json"
        job_dir.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(str(job.get("prompt", "")), encoding="utf-8")
        write_json(job_json_path, job)
        flush("running-job", job_id)

        before_status = image_status(output_path, expected_size)
        command_result: dict[str, Any] | None = None
        status = "pending"

        if skip_existing and before_status.get("ready"):
            skipped += 1
            status = "skipped-existing"
        elif not command:
            status = "pending-no-command"
        else:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            replacements = {
                "job_id": job_id,
                "prompt_file": str(prompt_path),
                "job_json": str(job_json_path),
                "output": str(output_path),
                "seed_canvas": str(resolve_repo_path(job.get("seedCanvas")) or ""),
                "pose_guides": str(resolve_repo_path(job.get("poseGuides")) or ""),
                "target_id": str(job.get("targetId", "")),
                "frame_index": str(job.get("frameIndex", "")),
                "matrix_key": str(job.get("matrixKey", "")),
            }
            command_result = run_job_command(command, replacements, timeout)
            if command_result.get("returnCode") == 0:
                generated += 1
                status = "generated"
            else:
                failed += 1
                status = "command-failed"

        after_status = image_status(output_path, expected_size)
        if after_status.get("ready"):
            ready += 1
        elif status == "generated":
            failed += 1
            status = "generated-invalid"

        record = {
            "jobId": job_id,
            "targetId": job.get("targetId"),
            "matrixKey": job.get("matrixKey"),
            "frameIndex": job.get("frameIndex"),
            "output": str(output_path),
            "status": status,
            "image": after_status,
            "command": command_result,
        }
        records.append(record)
        flush("running")
        if fail_fast and status in {"command-failed", "generated-invalid"}:
            break

    report = {
        "schemaVersion": 1,
        "stage": "stage-4-tile-worker-run",
        "generatedAt": utc_now(),
        "jobsPath": str(jobs_path),
        "outputRoot": str(output_root),
        "offset": offset,
        "limit": limit,
        "selectedJobCount": len(selected_jobs),
        "generatedCount": generated,
        "readyCount": ready,
        "skippedCount": skipped,
        "failedCount": failed,
        "commandConfigured": bool(command),
        "records": records,
        "nextStep": "Run import_alpecca_stage4_tile_outputs.py against this output root, then stitch and QA approved strips.",
        "status": "complete",
        "activeJob": "",
    }
    write_json(output_root / "worker_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--jobs", type=Path, help="Local JSONL chunk exported by export_alpecca_stage4_tile_jobs.py")
    source.add_argument("--hf-path", help="Path to a JSONL chunk inside a Hugging Face repo")
    parser.add_argument("--hf-repo", default="CREATORJD/alpecca-art-library")
    parser.add_argument("--hf-repo-type", default="dataset")
    parser.add_argument("--hf-revision")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--command", default=os.environ.get("ALPECCA_TILE_COMMAND"))
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args()

    jobs_path = args.jobs
    if args.hf_path:
        jobs_path = download_hf_file(args.hf_repo, args.hf_path, args.hf_repo_type, args.hf_revision)
    assert jobs_path is not None

    report = worker_run(
        jobs_path=jobs_path,
        output_root=args.output_root,
        command=args.command,
        offset=args.offset,
        limit=args.limit,
        skip_existing=args.skip_existing,
        timeout=args.timeout,
        fail_fast=args.fail_fast,
    )
    print(
        json.dumps(
            {
                "selectedJobCount": report["selectedJobCount"],
                "generatedCount": report["generatedCount"],
                "readyCount": report["readyCount"],
                "failedCount": report["failedCount"],
                "report": str(args.output_root / "worker_report.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
