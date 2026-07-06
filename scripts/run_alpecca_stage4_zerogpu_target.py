"""Run one complete Stage 4 target through the Hugging Face ZeroGPU Space.

This is the target-scale companion to run_alpecca_stage4_zerogpu_proof.py. It
requests every frame for one targetId, such as `gen-0149`, so the returned
prefix can become a real `raw_strip.png` candidate after QA.

The script is resumable:

- it checks the HF dataset for already uploaded output files;
- it skips existing frames by default;
- it stops cleanly on ZeroGPU quota errors and records a retry hint;
- it can immediately download/process the target prefix once all frames exist.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from run_alpecca_stage4_tile_worker import load_jsonl
from process_alpecca_stage4_returned_target import process_target


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPACE = "CREATORJD/alpecca-zerogpu"
DEFAULT_REPO_ID = "CREATORJD/alpecca-art-library"
DEFAULT_REPO_TYPE = "dataset"
DEFAULT_HF_PATH = "stage4-tile-jobs/batch_02/tile_jobs_batch_02_chunk_001.jsonl"
DEFAULT_LOCAL_JOBS = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "batch_02" / "tile_jobs_batch_02_chunk_001.jsonl"
DEFAULT_TARGET_ID = "gen-0149"
DEFAULT_OUTPUT_PREFIX = "stage4-worker-outputs/zerogpu-target-runs/gen-0149"
DEFAULT_OUT_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "zerogpu_target_runs"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def quota_wait_hint(text: str) -> str:
    match = re.search(r"Try again in ([^.]+)\.", text)
    return match.group(1).strip() if match else ""


def selected_target_jobs(local_jobs: Path, target_id: str) -> list[dict[str, Any]]:
    jobs = load_jsonl(local_jobs)
    selected: list[dict[str, Any]] = []
    for offset, job in enumerate(jobs):
        if str(job.get("targetId") or "") != target_id:
            continue
        row = dict(job)
        row["_sourceOffset"] = offset
        selected.append(row)
    return sorted(selected, key=lambda item: int(item.get("frameIndex") or 0))


def target_manifest(selected: list[dict[str, Any]], out_root: Path, target_id: str, source_hf_path: str) -> Path:
    jobs_path = out_root / f"tile_jobs_{target_id}.jsonl"
    with jobs_path.open("w", encoding="utf-8") as handle:
        for job in selected:
            clean = {key: value for key, value in job.items() if key != "_sourceOffset"}
            handle.write(json.dumps(clean, ensure_ascii=True) + "\n")
    manifest_path = out_root / f"tile_job_manifest_{target_id}.json"
    write_json(manifest_path, {
        "schemaVersion": 1,
        "stage": "stage-4-zerogpu-target-manifest",
        "generatedAt": utc_now(),
        "sourceHfPath": source_hf_path,
        "targetId": target_id,
        "jobCount": len(selected),
        "chunks": [{"file": str(jobs_path.relative_to(REPO_ROOT)).replace("\\", "/")}],
        "nextStep": "Run process_alpecca_stage4_returned_target.py after all target frames return.",
    })
    return manifest_path


def hf_existing_files(repo_id: str, repo_type: str, prefix: str) -> set[str]:
    try:
        from huggingface_hub import list_repo_files
    except ImportError:
        return set()
    prefix = prefix.strip("/").replace("\\", "/")
    try:
        return {
            name for name in list_repo_files(repo_id, repo_type=repo_type)
            if name == prefix or name.startswith(prefix + "/")
        }
    except Exception:
        return set()


def output_repo_file(prefix: str, job: dict[str, Any]) -> str:
    return f"{prefix.strip('/')}/{str(job.get('expectedWorkerOutput') or '').replace('\\', '/')}"


def generate_one(client: Any, args: argparse.Namespace, offset: int) -> dict[str, Any]:
    try:
        result = client.predict(
            args.hf_path,
            offset,
            args.output_prefix,
            args.model_id,
            args.render_size,
            args.steps,
            args.guidance,
            args.seed,
            args.strength,
            api_name="/generate_stage4_tile",
        )
        return {"status": "generated", "result": result}
    except Exception as error:
        text = f"{type(error).__name__}: {error}"
        return {
            "status": "blocked-zero-gpu-quota" if "quota" in text.lower() else "failed",
            "error": text,
            "quotaWaitHint": quota_wait_hint(text),
        }


def run_target(args: argparse.Namespace) -> dict[str, Any]:
    out_root = args.out_root if args.out_root.is_absolute() else REPO_ROOT / args.out_root
    out_root.mkdir(parents=True, exist_ok=True)
    local_jobs = args.local_jobs if args.local_jobs.is_absolute() else REPO_ROOT / args.local_jobs
    selected = selected_target_jobs(local_jobs, args.target_id)
    manifest = target_manifest(selected, out_root, args.target_id, args.hf_path) if selected else None
    existing = hf_existing_files(args.repo_id, args.repo_type, args.output_prefix)
    records: list[dict[str, Any]] = []
    generated = skipped = failed = 0
    stopped = False

    client = None
    if not args.dry_run:
        try:
            from gradio_client import Client
        except ImportError as error:
            stopped = True
            failed = len(selected)
            records.append({
                "status": "blocked-missing-gradio-client",
                "error": str(error),
                "fix": "python -m pip install gradio_client",
            })
        else:
            client = Client(args.space)

    for job in selected:
        frame_index = int(job.get("frameIndex") or 0)
        offset = int(job["_sourceOffset"])
        repo_file = output_repo_file(args.output_prefix, job)
        exists = repo_file in existing
        record = {
            "jobId": job.get("jobId"),
            "targetId": job.get("targetId"),
            "matrixKey": job.get("matrixKey"),
            "frameIndex": frame_index,
            "sourceOffset": offset,
            "repoFile": repo_file,
            "alreadyUploaded": exists,
        }
        if exists and args.skip_existing:
            skipped += 1
            record["status"] = "skipped-existing"
            records.append(record)
            continue
        if args.dry_run:
            record["status"] = "dry-run"
            records.append(record)
            continue
        if client is None:
            record["status"] = "not-run"
            records.append(record)
            continue
        generation = generate_one(client, args, offset)
        record.update(generation)
        if generation["status"] == "generated":
            generated += 1
        else:
            failed += 1
            stopped = True
            records.append(record)
            break
        records.append(record)
        if args.sleep_between > 0:
            time.sleep(float(args.sleep_between))

    process_report = None
    expected_repo_files = {output_repo_file(args.output_prefix, job) for job in selected}
    refreshed_existing = hf_existing_files(args.repo_id, args.repo_type, args.output_prefix) if args.process_after else set()
    all_outputs_present = bool(expected_repo_files) and expected_repo_files.issubset(refreshed_existing)
    if args.process_after and manifest and not args.dry_run and all_outputs_present:
        try:
            process_report = process_target(
                repo_id=args.repo_id,
                repo_type=args.repo_type,
                prefix=args.output_prefix,
                manifest=manifest,
                out_root=out_root / "returned",
                target_id=args.target_id,
                skip_download=False,
                outputs_root=None,
                apply_import=args.apply_import,
                apply_stitch=args.apply_stitch,
            )
        except BaseException as error:
            process_report = {
                "stage": "stage-4-zerogpu-target-postprocess",
                "status": "failed",
                "error": f"{type(error).__name__}: {error}",
            }
    elif args.process_after:
        process_report = {
            "stage": "stage-4-zerogpu-target-postprocess",
            "status": "waiting-for-target-outputs",
            "expectedFrameFiles": len(expected_repo_files),
            "presentFrameFiles": len(expected_repo_files.intersection(refreshed_existing)),
            "missingFrameFiles": sorted(expected_repo_files - refreshed_existing)[:32],
        }

    expected_frames = int(selected[0].get("frameCount") or len(selected)) if selected else 0
    complete_selection = bool(selected) and sorted(int(job.get("frameIndex") or 0) for job in selected) == list(range(expected_frames))
    summary = {
        "schemaVersion": 1,
        "stage": "stage-4-zerogpu-target-run",
        "generatedAt": utc_now(),
        "status": "stopped" if stopped else "complete",
        "dryRun": args.dry_run,
        "space": args.space,
        "repoId": args.repo_id,
        "repoType": args.repo_type,
        "hfPath": args.hf_path,
        "localJobs": str(local_jobs.relative_to(REPO_ROOT)).replace("\\", "/"),
        "targetId": args.target_id,
        "outputPrefix": args.output_prefix,
        "selectedJobCount": len(selected),
        "expectedFrameCount": expected_frames,
        "completeSelection": complete_selection,
        "generatedCount": generated,
        "skippedExistingCount": skipped,
        "failedCount": failed,
        "expectedRepoFileCount": len(expected_repo_files),
        "presentRepoFileCount": len(expected_repo_files.intersection(refreshed_existing)) if args.process_after else None,
        "targetManifest": str(manifest.relative_to(REPO_ROOT)).replace("\\", "/") if manifest else None,
        "records": records,
        "postProcess": process_report,
        "nextStep": (
            "Wait for ZeroGPU quota, then rerun this same command."
            if any(row.get("status") == "blocked-zero-gpu-quota" for row in records) else
            "Run process_alpecca_stage4_returned_target.py after all frames are uploaded."
            if args.dry_run or not args.process_after else
            "Inspect returned target QA and raw strip preview before runtime promotion."
        ),
    }
    write_json(out_root / f"zerogpu_target_run_{args.target_id}.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--space", default=DEFAULT_SPACE)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--repo-type", default=DEFAULT_REPO_TYPE)
    parser.add_argument("--hf-path", default=DEFAULT_HF_PATH)
    parser.add_argument("--local-jobs", type=Path, default=DEFAULT_LOCAL_JOBS)
    parser.add_argument("--target-id", default=DEFAULT_TARGET_ID)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--model-id", default="cagliostrolab/animagine-xl-4.0")
    parser.add_argument("--render-size", type=int, default=1536)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--guidance", type=float, default=7.5)
    parser.add_argument("--seed", type=int, default=170408)
    parser.add_argument("--strength", type=float, default=0.52)
    parser.add_argument("--sleep-between", type=float, default=0.0)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--no-skip-existing", action="store_false", dest="skip_existing")
    parser.add_argument("--process-after", action="store_true")
    parser.add_argument("--apply-import", action="store_true")
    parser.add_argument("--apply-stitch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    summary = run_target(args)
    quota = next((row.get("quotaWaitHint") for row in summary["records"] if row.get("quotaWaitHint")), "")
    print(json.dumps({
        "status": summary["status"],
        "dryRun": summary["dryRun"],
        "targetId": summary["targetId"],
        "selectedJobCount": summary["selectedJobCount"],
        "expectedFrameCount": summary["expectedFrameCount"],
        "completeSelection": summary["completeSelection"],
        "generatedCount": summary["generatedCount"],
        "skippedExistingCount": summary["skippedExistingCount"],
        "failedCount": summary["failedCount"],
        "quotaWaitHint": quota,
        "targetManifest": summary["targetManifest"],
        "report": str((args.out_root if args.out_root.is_absolute() else REPO_ROOT / args.out_root) / f"zerogpu_target_run_{args.target_id}.json"),
        "nextStep": summary["nextStep"],
    }, indent=2))
    return 0 if summary["status"] in {"complete", "stopped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
