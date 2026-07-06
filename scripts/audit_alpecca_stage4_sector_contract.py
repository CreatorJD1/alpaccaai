"""Audit the Alpecca Stage 4 16-sector generation contract.

This is a pre-GPU and pre-promotion gate. It verifies that the source-art
queue, tile worker jobs, prompts, and runtime resolver agree on the same
360-view contract before expensive 4K generation starts.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_ROOT = REPO_ROOT / "data" / "alpecca_art_source"
DEFAULT_JOBS_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs"
DEFAULT_STAGE4_ROOT = DEFAULT_LIBRARY_ROOT / "stage4_generation_batches"
DEFAULT_REPORT = REPO_ROOT / "output" / "alpecca_stage4_sector_contract_report.json"
DRIVE_360_SOURCE_FOLDER = "https://drive.google.com/drive/folders/1TCaawZt7idE7ib-Kw8T-sq23z5cIXJmw"
EXTERNAL_360_REQUIRED_FILES = (
    "drive_360_reference_high_density_turnaround.gif",
    "drive_360_reference_processing_turntable.gif",
    "drive_360_reference_small_rotation.gif",
    "drive_360_reference_turnaround_sheet.jpg",
    "external_360_reference_preview.jpg",
)

SECTORS_16 = tuple(f"s{i}" for i in range(16))
PROMPT_REQUIRED_PHRASES = (
    "Google Drive 360 reference folder",
    "s0` through `s15",
    "sixteen native camera angles",
    "Do not make a 5-view or 8-view approximation",
    "no flat billboard rotation",
    "4096x4096",
)


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


def repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def issue(issues: list[str], message: str) -> None:
    issues.append(message)


def expected_targets_for_batch(batch: dict[str, Any]) -> int:
    actions = len(batch.get("actions") or [])
    verticals = len(batch.get("verticals") or [])
    horizontals = len(batch.get("horizontals") or [])
    return actions * verticals * horizontals


def audit_source_queue(library_root: Path, issues: list[str]) -> dict[str, Any]:
    queue_path = library_root / "generation_queue.json"
    queue = load_json(queue_path)
    targets = queue.get("targets") or []
    batches = queue.get("batches") or []
    if int(queue.get("minimumArtPieceGoal") or 0) < 400:
        issue(issues, "generation queue minimumArtPieceGoal is below 400")
    if len(targets) < 186:
        issue(issues, f"generation queue target count {len(targets)} is below 186")

    batch_reports: list[dict[str, Any]] = []
    targets_by_batch: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for target in targets:
        targets_by_batch[int(target.get("batch") or 0)].append(target)
        if int(target.get("targetSlotPixels") or 0) < 4096:
            issue(issues, f"{target.get('id')}: targetSlotPixels is below 4096")
        if int(target.get("minimumSourceSlotPixels") or 0) < 4096:
            issue(issues, f"{target.get('id')}: minimumSourceSlotPixels is below 4096")
        if target.get("viewSector16") and target.get("viewSector16") not in SECTORS_16:
            issue(issues, f"{target.get('id')}: invalid viewSector16 {target.get('viewSector16')}")

    for batch in batches:
        batch_number = int(batch.get("batch") or 0)
        horizontals = tuple(batch.get("horizontals") or [])
        batch_targets = targets_by_batch.get(batch_number, [])
        expected = expected_targets_for_batch(batch)
        is_native_16 = all(horizontal in SECTORS_16 for horizontal in horizontals)
        if len(batch_targets) != expected:
            issue(issues, f"batch {batch_number}: expected {expected} targets, found {len(batch_targets)}")
        if "16-sector" in str(batch.get("name") or "") and not is_native_16:
            issue(issues, f"batch {batch_number}: named 16-sector but horizontals are {horizontals}")
        if is_native_16:
            groups: dict[tuple[str, str, str], set[str]] = defaultdict(set)
            for target in batch_targets:
                key = (
                    str(target.get("targetKind") or "matrix-atlas"),
                    str(target.get("action") or ""),
                    str(target.get("verticalTier") or ""),
                )
                groups[key].add(str(target.get("viewSector16") or target.get("horizontalTier") or ""))
            for key, sectors in groups.items():
                missing = sorted(set(SECTORS_16) - sectors, key=lambda value: int(value[1:]))
                extra = sorted(sectors - set(SECTORS_16))
                if missing or extra:
                    issue(issues, f"batch {batch_number} group {key}: missing={missing} extra={extra}")
        batch_reports.append(
            {
                "batch": batch_number,
                "name": batch.get("name"),
                "native16Sector": is_native_16,
                "expectedTargetCount": expected,
                "targetCount": len(batch_targets),
                "horizontals": list(horizontals),
            }
        )

    return {
        "path": str(queue_path),
        "targetCount": len(targets),
        "batchCount": len(batches),
        "minimumArtPieceGoal": queue.get("minimumArtPieceGoal"),
        "batches": batch_reports,
    }


def audit_external_360_references(library_root: Path, issues: list[str]) -> dict[str, Any]:
    references_root = library_root / "external_360_references"
    manifest_path = references_root / "manifest.json"
    if not manifest_path.exists():
        issue(issues, f"missing external 360 reference manifest {manifest_path}")
        return {"path": str(manifest_path), "fileCount": 0, "missingFiles": list(EXTERNAL_360_REQUIRED_FILES)}

    manifest = load_json(manifest_path)
    if manifest.get("sourceFolder") != DRIVE_360_SOURCE_FOLDER:
        issue(issues, "external 360 reference manifest sourceFolder does not match the locked Drive folder")
    if "Reject outputs that remain flat like a single billboard while the player circles her." not in manifest.get("usePolicy", []):
        issue(issues, "external 360 reference manifest is missing the flat-billboard rejection policy")

    missing_files = [name for name in EXTERNAL_360_REQUIRED_FILES if not (references_root / name).exists()]
    for name in missing_files:
        issue(issues, f"missing external 360 reference file {name}")

    return {
        "path": str(manifest_path),
        "sourceFolder": manifest.get("sourceFolder"),
        "fileCount": len(manifest.get("files") or []),
        "missingFiles": missing_files,
        "requiredFiles": list(EXTERNAL_360_REQUIRED_FILES),
    }


def audit_stage4_targets(stage4_root: Path, issues: list[str]) -> dict[str, Any]:
    target_paths = sorted(stage4_root.glob("batch_*/targets/*/target.json"))
    prompt_checks = 0
    stage_targets = 0
    for target_path in target_paths:
        target = load_json(target_path)
        stage_targets += 1
        if int(target.get("slotPixels") or 0) < 4096:
            issue(issues, f"{target.get('targetId')}: Stage 4 slotPixels below 4096")
        if target.get("viewSector16") and target.get("viewSector16") not in SECTORS_16:
            issue(issues, f"{target.get('targetId')}: invalid Stage 4 viewSector16 {target.get('viewSector16')}")
        prompt_path = target_path.parent / "incoming" / "frame_tiles" / "prompts" / "frame_000.md"
        if prompt_path.exists():
            prompt_checks += 1
            prompt = prompt_path.read_text(encoding="utf-8")
            for phrase in PROMPT_REQUIRED_PHRASES:
                if phrase not in prompt:
                    issue(issues, f"{target.get('targetId')}: prompt missing phrase {phrase!r}")
        else:
            issue(issues, f"{target.get('targetId')}: missing frame_000 tile prompt")
    return {"targetCount": stage_targets, "promptCheckCount": prompt_checks}


def audit_worker_jobs(jobs_root: Path, issues: list[str]) -> dict[str, Any]:
    queue_path = jobs_root / "stage4_generation_queue.json"
    queue = load_json(queue_path)
    if queue.get("requiredTileSize") != [4096, 4096]:
        issue(issues, f"worker queue requiredTileSize is {queue.get('requiredTileSize')}, expected [4096, 4096]")
    job_count = 0
    chunk_count = 0
    prompt_sample_issues = 0
    for chunk in queue.get("chunks", []):
        chunk_count += 1
        chunk_path = repo_path(str(chunk.get("file") or ""))
        if not chunk_path.exists():
            issue(issues, f"missing worker chunk {chunk_path}")
            continue
        for job in iter_jsonl(chunk_path):
            job_count += 1
            if job.get("expectedSize") != [4096, 4096]:
                issue(issues, f"{job.get('jobId')}: expectedSize is {job.get('expectedSize')}")
            sector = job.get("viewSector16")
            if sector and sector not in SECTORS_16:
                issue(issues, f"{job.get('jobId')}: invalid job viewSector16 {sector}")
            prompt = str(job.get("prompt") or "")
            if job_count <= 128:
                for phrase in PROMPT_REQUIRED_PHRASES:
                    if phrase not in prompt:
                        prompt_sample_issues += 1
                        issue(issues, f"{job.get('jobId')}: job prompt missing phrase {phrase!r}")
    if int(queue.get("jobCount") or 0) != job_count:
        issue(issues, f"worker queue jobCount {queue.get('jobCount')} does not match counted {job_count}")
    if int(queue.get("chunkCount") or 0) != chunk_count:
        issue(issues, f"worker queue chunkCount {queue.get('chunkCount')} does not match counted {chunk_count}")
    return {
        "path": str(queue_path),
        "targetCount": queue.get("targetCount"),
        "jobCount": job_count,
        "chunkCount": chunk_count,
        "requiredTileSize": queue.get("requiredTileSize"),
        "promptSampleIssues": prompt_sample_issues,
    }


def audit_runtime_resolver(issues: list[str]) -> dict[str, Any]:
    source_path = REPO_ROOT / "apps" / "house-hq" / "src" / "main.ts"
    source = source_path.read_text(encoding="utf-8")
    required_patterns = {
        "sector runtime key helper": r"function alpeccaSector16RuntimeKey",
        "sector exact key": r"const exactKey = `\$\{action\}_\$\{matrix\.vertical\}_\$\{sectorKey\}`",
        "sector eye key": r"const eyeKey = `\$\{action\}_eye_\$\{sectorKey\}`",
        "5-tier fallback retained": r"const horizontalExactKey = `\$\{action\}_\$\{matrix\.vertical\}_\$\{matrix\.horizontal\}`",
        "runtime accepts sector tiers": r"isAlpeccaRuntimeHorizontalTier",
    }
    missing = []
    for label, pattern in required_patterns.items():
        if not re.search(pattern, source):
            missing.append(label)
            issue(issues, f"runtime resolver missing {label}")
    return {"path": str(source_path), "missingChecks": missing}


def run_audit(library_root: Path, jobs_root: Path, stage4_root: Path, report_path: Path) -> dict[str, Any]:
    issues: list[str] = []
    report = {
        "schemaVersion": 1,
        "stage": "stage-4-sector-contract-audit",
        "generatedAt": utc_now(),
        "status": "pending",
        "external360References": audit_external_360_references(library_root, issues),
        "sourceQueue": audit_source_queue(library_root, issues),
        "stage4Targets": audit_stage4_targets(stage4_root, issues),
        "workerJobs": audit_worker_jobs(jobs_root, issues),
        "runtimeResolver": audit_runtime_resolver(issues),
        "issues": issues,
    }
    report["status"] = "pass" if not issues else "fail"
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, default=DEFAULT_LIBRARY_ROOT)
    parser.add_argument("--jobs-root", type=Path, default=DEFAULT_JOBS_ROOT)
    parser.add_argument("--stage4-root", type=Path, default=DEFAULT_STAGE4_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = run_audit(args.library_root, args.jobs_root, args.stage4_root, args.report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "issueCount": len(report["issues"]),
                "targetCount": report["sourceQueue"]["targetCount"],
                "jobCount": report["workerJobs"]["jobCount"],
                "report": str(args.report),
            },
            indent=2,
        )
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
