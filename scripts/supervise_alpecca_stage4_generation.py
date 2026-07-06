"""Supervise Stage 4 target generation progress.

This is a thin orchestration layer over the existing Stage 4 queue, target
status audit, and ZeroGPU target runner. It does not approve art. Its job is to
find missing target frames, report exact progress, and optionally run the next
incomplete target through the current generator pipeline.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from run_alpecca_stage4_tile_worker import load_jsonl
from run_alpecca_stage4_zerogpu_target import (
    DEFAULT_REPO_ID,
    DEFAULT_REPO_TYPE,
    DEFAULT_SPACE,
    output_repo_file,
    run_target,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "stage4_generation_queue.json"
DEFAULT_OUT_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "supervisor"
DEFAULT_OUTPUT_BASE_PREFIX = "stage4-worker-outputs/zerogpu-target-runs"


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


def local_path(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else REPO_ROOT / path


def hf_path_for_chunk(local_chunk: str) -> str:
    normalized = local_chunk.replace("\\", "/")
    prefix = "output/alpecca_stage4_tile_jobs/"
    if normalized.startswith(prefix):
        return "stage4-tile-jobs/" + normalized.removeprefix(prefix)
    return normalized


def repo_file_set(repo_id: str, repo_type: str, base_prefix: str) -> set[str]:
    try:
        from huggingface_hub import list_repo_files
    except ImportError:
        return set()
    base_prefix = base_prefix.strip("/").replace("\\", "/")
    try:
        return {
            name for name in list_repo_files(repo_id, repo_type=repo_type)
            if name == base_prefix or name.startswith(base_prefix + "/")
        }
    except Exception:
        return set()


def chunk_records(queue_path: Path, batch: int | None) -> list[dict[str, Any]]:
    queue = load_json(queue_path)
    chunks = list(queue.get("chunks") or [])
    if batch is not None:
        chunks = [chunk for chunk in chunks if int(chunk.get("batchNumber") or -1) == batch]
    return sorted(chunks, key=lambda row: (int(row.get("priority") or 99), int(row.get("batchNumber") or 99), int(row.get("chunkIndex") or 0)))


def target_groups(chunk_file: Path, action: str | None) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for job in load_jsonl(chunk_file):
        if action and str(job.get("action") or "") != action:
            continue
        target_id = str(job.get("targetId") or "")
        if not target_id:
            continue
        groups.setdefault(target_id, []).append(job)
    return {
        target_id: sorted(jobs, key=lambda item: int(item.get("frameIndex") or 0))
        for target_id, jobs in groups.items()
    }


def summarize_target(
    *,
    target_id: str,
    jobs: list[dict[str, Any]],
    chunk_file: Path,
    hf_path: str,
    output_base_prefix: str,
    existing_repo_files: set[str],
) -> dict[str, Any]:
    first = jobs[0]
    expected_frame_count = int(first.get("frameCount") or len(jobs))
    frame_indexes = sorted(int(job.get("frameIndex") or 0) for job in jobs)
    output_prefix = f"{output_base_prefix.strip('/')}/{target_id}"
    expected_files = [output_repo_file(output_prefix, job) for job in jobs]
    present_files = [path for path in expected_files if path in existing_repo_files]
    missing_files = [path for path in expected_files if path not in existing_repo_files]
    complete_selection = frame_indexes == list(range(expected_frame_count))
    complete_outputs = complete_selection and len(present_files) == expected_frame_count and not missing_files
    return {
        "targetId": target_id,
        "matrixKey": first.get("matrixKey"),
        "action": first.get("action"),
        "verticalTier": first.get("verticalTier"),
        "horizontalTier": first.get("horizontalTier"),
        "viewSector16": first.get("viewSector16"),
        "chunkFile": rel(chunk_file),
        "hfPath": hf_path,
        "outputPrefix": output_prefix,
        "selectedJobCount": len(jobs),
        "expectedFrameCount": expected_frame_count,
        "frameIndexes": frame_indexes,
        "completeSelection": complete_selection,
        "presentRepoFileCount": len(present_files),
        "missingRepoFileCount": len(missing_files),
        "completeOutputs": complete_outputs,
        "presentRepoFiles": present_files,
        "missingRepoFiles": missing_files,
    }


def build_supervisor_report(args: argparse.Namespace) -> dict[str, Any]:
    queue_path = args.queue if args.queue.is_absolute() else REPO_ROOT / args.queue
    existing = repo_file_set(args.repo_id, args.repo_type, args.output_base_prefix)
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in chunk_records(queue_path, args.batch):
        chunk_file = local_path(str(chunk.get("file") or ""))
        if not chunk_file.exists():
            continue
        hf_path = hf_path_for_chunk(str(chunk.get("file") or ""))
        for target_id, jobs in target_groups(chunk_file, args.action).items():
            if target_id in seen:
                continue
            seen.add(target_id)
            targets.append(
                summarize_target(
                    target_id=target_id,
                    jobs=jobs,
                    chunk_file=chunk_file,
                    hf_path=hf_path,
                    output_base_prefix=args.output_base_prefix,
                    existing_repo_files=existing,
                )
            )
            if args.max_targets and len(targets) >= args.max_targets:
                break
        if args.max_targets and len(targets) >= args.max_targets:
            break

    incomplete = [target for target in targets if not target["completeOutputs"]]
    complete = [target for target in targets if target["completeOutputs"]]
    next_target = incomplete[0] if incomplete else None
    run_report = None
    if args.run_next and next_target:
        run_out_root = (
            REPO_ROOT
            / "output"
            / "alpecca_stage4_tile_jobs"
            / "zerogpu_target_runs"
            / f"{next_target['targetId']}_supervised"
        )
        run_args = argparse.Namespace(
            space=args.space,
            repo_id=args.repo_id,
            repo_type=args.repo_type,
            hf_path=next_target["hfPath"],
            local_jobs=REPO_ROOT / next_target["chunkFile"],
            target_id=next_target["targetId"],
            output_prefix=next_target["outputPrefix"],
            model_id=args.model_id,
            render_size=args.render_size,
            steps=args.steps,
            guidance=args.guidance,
            seed=args.seed,
            strength=args.strength,
            sleep_between=args.sleep_between,
            out_root=run_out_root,
            skip_existing=True,
            process_after=True,
            apply_import=False,
            apply_stitch=False,
            dry_run=args.dry_run_generation,
        )
        run_report = run_target(run_args)

    return {
        "schemaVersion": 1,
        "stage": "stage-4-generation-supervisor",
        "generatedAt": utc_now(),
        "repoId": args.repo_id,
        "repoType": args.repo_type,
        "queue": rel(queue_path),
        "batchFilter": args.batch,
        "actionFilter": args.action,
        "outputBasePrefix": args.output_base_prefix,
        "scannedTargetCount": len(targets),
        "completeTargetCount": len(complete),
        "incompleteTargetCount": len(incomplete),
        "nextTarget": next_target,
        "targets": targets,
        "runNext": args.run_next,
        "runReport": run_report,
        "nextStep": (
            "Inspect the run report; rerun when GPU quota is available."
            if run_report
            else "Run with --run-next after GPU quota is available."
            if next_target
            else "All scanned targets have complete returned outputs; process them through QA/import/stitch."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--repo-type", default=DEFAULT_REPO_TYPE)
    parser.add_argument("--space", default=DEFAULT_SPACE)
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--action", default="walk")
    parser.add_argument("--max-targets", type=int, default=48)
    parser.add_argument("--output-base-prefix", default=DEFAULT_OUTPUT_BASE_PREFIX)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--run-next", action="store_true")
    parser.add_argument("--dry-run-generation", action="store_true")
    parser.add_argument("--model-id", default="cagliostrolab/animagine-xl-4.0")
    parser.add_argument("--render-size", type=int, default=1536)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--guidance", type=float, default=7.5)
    parser.add_argument("--seed", type=int, default=170408)
    parser.add_argument("--strength", type=float, default=0.52)
    parser.add_argument("--sleep-between", type=float, default=0.0)
    args = parser.parse_args()

    report = build_supervisor_report(args)
    out_root = args.out_root if args.out_root.is_absolute() else REPO_ROOT / args.out_root
    report_path = out_root / "stage4_generation_supervisor_report.json"
    write_json(report_path, report)
    quota = ""
    run_report = report.get("runReport") or {}
    for row in run_report.get("records") or []:
        if row.get("quotaWaitHint"):
            quota = row["quotaWaitHint"]
            break
    print(json.dumps({
        "scannedTargetCount": report["scannedTargetCount"],
        "completeTargetCount": report["completeTargetCount"],
        "incompleteTargetCount": report["incompleteTargetCount"],
        "nextTarget": {
            "targetId": (report["nextTarget"] or {}).get("targetId"),
            "matrixKey": (report["nextTarget"] or {}).get("matrixKey"),
            "presentRepoFileCount": (report["nextTarget"] or {}).get("presentRepoFileCount"),
            "missingRepoFileCount": (report["nextTarget"] or {}).get("missingRepoFileCount"),
        } if report["nextTarget"] else None,
        "runNext": report["runNext"],
        "runStatus": run_report.get("status") if run_report else "",
        "quotaWaitHint": quota,
        "report": rel(report_path),
        "nextStep": report["nextStep"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
