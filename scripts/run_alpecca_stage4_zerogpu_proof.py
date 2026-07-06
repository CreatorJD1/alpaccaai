"""Run one Stage 4 ZeroGPU proof tile and QA the returned output.

This is the smallest repeatable loop for the 400+ art library:

1. Ask the Hugging Face Space to generate one exact queue tile.
2. Upload stays in the Hugging Face art dataset, not Cloudflare.
3. Download the returned prefix locally.
4. Run tile QA, including the Alpecca design-lock drift probes.

The script does not approve art, import it, stitch strips, or touch runtime
atlases. It only produces evidence for the next human visual decision.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from download_alpecca_stage4_worker_outputs import download_prefix
from qa_alpecca_stage4_tile_outputs import qa_outputs
from run_alpecca_stage4_tile_worker import load_jsonl


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPACE = "CREATORJD/alpecca-zerogpu"
DEFAULT_REPO_ID = "CREATORJD/alpecca-art-library"
DEFAULT_HF_PATH = "stage4-tile-jobs/batch_02/tile_jobs_batch_02_chunk_001.jsonl"
DEFAULT_OUTPUT_PREFIX = "stage4-worker-outputs/zerogpu-walk-proof6/walk_low_s4_frame000_designlock"
DEFAULT_LOCAL_JOBS = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "batch_02" / "tile_jobs_batch_02_chunk_001.jsonl"
DEFAULT_OUT_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "zerogpu_proofs"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def quota_wait_hint(text: str) -> str:
    match = re.search(r"Try again in ([^.]+)\.", text)
    return match.group(1).strip() if match else ""


def make_manifest(jobs_path: Path, out_dir: Path) -> Path:
    manifest = {
        "schemaVersion": 1,
        "stage": "stage-4-single-proof-manifest",
        "generatedAt": utc_now(),
        "chunks": [{"file": str(jobs_path.relative_to(REPO_ROOT)).replace("\\", "/")}],
    }
    path = out_dir / "single_proof_manifest.json"
    write_json(path, manifest)
    return path


def run_zero_gpu(args: argparse.Namespace) -> dict[str, Any]:
    try:
        from gradio_client import Client
    except ImportError as error:
        return {
            "status": "blocked-missing-gradio-client",
            "error": str(error),
            "fix": "python -m pip install gradio_client",
        }

    client = Client(args.space)
    try:
        result = client.predict(
            args.hf_path,
            args.offset,
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
        status = "blocked-zero-gpu-quota" if "quota" in text.lower() else "failed"
        return {
            "status": status,
            "error": text,
            "quotaWaitHint": quota_wait_hint(text),
        }


def run_proof(args: argparse.Namespace) -> dict[str, Any]:
    out_root = args.out_root if args.out_root.is_absolute() else REPO_ROOT / args.out_root
    out_root.mkdir(parents=True, exist_ok=True)
    jobs_path = args.local_jobs if args.local_jobs.is_absolute() else REPO_ROOT / args.local_jobs
    jobs = load_jsonl(jobs_path)
    if args.offset < 0 or args.offset >= len(jobs):
        raise SystemExit(f"Offset {args.offset} is outside {jobs_path} with {len(jobs)} jobs.")
    target_job = jobs[args.offset]
    generation = run_zero_gpu(args) if not args.skip_generation else {"status": "skipped-generation"}

    download = None
    qa = None
    if generation["status"] in {"generated", "skipped-generation"}:
        try:
            download = download_prefix(args.repo_id, args.output_prefix, out_root, args.repo_type)
            destination_root = REPO_ROOT / download["destinationRoot"]
            manifest = make_manifest(jobs_path, destination_root)
            qa_root = destination_root / "qa_tile"
            qa = qa_outputs(
                manifest,
                destination_root,
                qa_root,
                target_id=str(target_job.get("targetId") or ""),
                thumb_size=args.thumb_size,
            )
        except Exception as error:
            generation = {
                **generation,
                "postGenerationStatus": "download-or-qa-failed",
                "postGenerationError": f"{type(error).__name__}: {error}",
            }

    summary = {
        "schemaVersion": 1,
        "stage": "stage-4-zerogpu-single-proof",
        "generatedAt": utc_now(),
        "space": args.space,
        "repoId": args.repo_id,
        "repoType": args.repo_type,
        "hfPath": args.hf_path,
        "localJobs": str(jobs_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "offset": args.offset,
        "outputPrefix": args.output_prefix,
        "modelId": args.model_id,
        "renderSize": args.render_size,
        "steps": args.steps,
        "guidance": args.guidance,
        "seed": args.seed,
        "target": {
            "jobId": target_job.get("jobId"),
            "targetId": target_job.get("targetId"),
            "matrixKey": target_job.get("matrixKey"),
            "frameIndex": target_job.get("frameIndex"),
            "expectedWorkerOutput": target_job.get("expectedWorkerOutput"),
        },
        "generation": generation,
        "download": download,
        "qa": {
            "report": str((REPO_ROOT / download["destinationRoot"] / "qa_tile" / "tile_visual_qa_report.json").relative_to(REPO_ROOT)).replace("\\", "/")
            if download and qa else None,
            "readyJobCount": qa.get("readyJobCount") if qa else None,
            "blockedJobCount": qa.get("blockedJobCount") if qa else None,
            "missingJobCount": qa.get("missingJobCount") if qa else None,
            "readyTargetCount": qa.get("readyTargetCount") if qa else None,
        },
        "nextStep": (
            "Inspect the tile preview. If QA blocks design drift, tighten prompt or regenerate this proof."
            if qa else
            "Wait for ZeroGPU quota or fix the reported generation/download issue, then rerun this proof."
        ),
    }
    write_json(out_root / "zerogpu_single_proof_report.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--space", default=DEFAULT_SPACE)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--repo-type", default="dataset")
    parser.add_argument("--hf-path", default=DEFAULT_HF_PATH)
    parser.add_argument("--local-jobs", type=Path, default=DEFAULT_LOCAL_JOBS)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output-prefix", default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--model-id", default="cagliostrolab/animagine-xl-4.0")
    parser.add_argument("--render-size", type=int, default=1536)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--guidance", type=float, default=7.5)
    parser.add_argument("--seed", type=int, default=170408)
    parser.add_argument("--strength", type=float, default=0.52)
    parser.add_argument("--thumb-size", type=int, default=384)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--skip-generation", action="store_true", help="Download/QA an already uploaded proof prefix.")
    args = parser.parse_args()
    summary = run_proof(args)
    print(json.dumps({
        "status": summary["generation"]["status"],
        "quotaWaitHint": summary["generation"].get("quotaWaitHint", ""),
        "target": summary["target"],
        "qa": summary["qa"],
        "report": str((args.out_root if args.out_root.is_absolute() else REPO_ROOT / args.out_root) / "zerogpu_single_proof_report.json"),
        "nextStep": summary["nextStep"],
    }, indent=2))
    return 0 if summary["generation"]["status"] in {"generated", "skipped-generation", "blocked-zero-gpu-quota"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
