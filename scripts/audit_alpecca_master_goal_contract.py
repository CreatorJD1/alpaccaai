"""Audit progress against the active Alpecca master goal.

The master goal is larger than a normal unit test:

- 3D-effect source art: at least 186 billboard targets, more than 400 art
  pieces, 16 views per angle family, and 4K-8K source resolution.
- Storage policy: source/generated art belongs on Hugging Face, while
  Cloudflare is only the app/runtime preview shell.
- Completion gate: actual generated 4K tiles must be imported, stitched into
  raw strips, visually QA'd, and promoted before the art side can be complete.
- Recursive engagement: Alpecca must have evidence of promptless observation,
  memory, self-feedback, bounded next action, and an evidence-first curriculum.

This audit is deliberately honest: it can pass the *queue contract* while still
reporting the master goal as incomplete until real pixels and runtime approvals
exist.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_QUEUE = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "stage4_generation_queue.json"
DEFAULT_ART_STATUS = REPO_ROOT / "output" / "alpecca_stage4_art_status.json"
DEFAULT_REPORT = REPO_ROOT / "output" / "alpecca_master_goal_contract_report.json"
SECTORS_16 = tuple(f"s{i}" for i in range(16))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def repo_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def check(check_id: str, label: str, ok: bool, evidence: str, *, blocking: bool = True) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "ok": bool(ok),
        "blocking": bool(blocking),
        "evidence": evidence,
    }


def load_worker_jobs(queue: dict[str, Any]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for chunk in queue.get("chunks", []):
        chunk_path = repo_path(str(chunk.get("file") or ""))
        if chunk_path.exists():
            jobs.extend(iter_jsonl(chunk_path))
    return jobs


def sector_group_report(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for job in jobs:
        action = str(job.get("action") or "")
        vertical = str(job.get("verticalTier") or "")
        target_kind = str(job.get("targetKind") or "matrix-atlas")
        sector = str(job.get("viewSector16") or "")
        if sector:
            groups[(target_kind, action, vertical)].add(sector)
    group_rows = []
    complete = 0
    incomplete = 0
    for key, sectors in sorted(groups.items()):
        missing = sorted(set(SECTORS_16) - sectors, key=lambda value: int(value[1:]))
        extra = sorted(sectors - set(SECTORS_16))
        ok = not missing and not extra
        complete += 1 if ok else 0
        incomplete += 0 if ok else 1
        group_rows.append({
            "targetKind": key[0],
            "action": key[1],
            "verticalTier": key[2],
            "sectorCount": len(sectors),
            "complete16Sector": ok,
            "missing": missing,
            "extra": extra,
        })
    return {
        "groupCount": len(group_rows),
        "complete16SectorGroups": complete,
        "incomplete16SectorGroups": incomplete,
        "groups": group_rows,
    }


def resolution_report(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    sizes: dict[str, int] = defaultdict(int)
    invalid: list[dict[str, Any]] = []
    for job in jobs:
        size = job.get("expectedSize") or []
        key = "x".join(str(v) for v in size)
        sizes[key] += 1
        if (
            not isinstance(size, list)
            or len(size) != 2
            or int(size[0]) != int(size[1])
            or int(size[0]) < 4096
            or int(size[0]) > 8192
        ):
            invalid.append({
                "jobId": job.get("jobId"),
                "expectedSize": size,
            })
    return {
        "sizes": dict(sorted(sizes.items())),
        "invalidCount": len(invalid),
        "invalidSamples": invalid[:20],
    }


def walk_report(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    walk_targets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job in jobs:
        if job.get("action") == "walk":
            walk_targets[str(job.get("targetId"))].append(job)
    bad_targets = []
    for target_id, rows in sorted(walk_targets.items()):
        frame_count = int(rows[0].get("frameCount") or 0) if rows else 0
        frames = {int(row.get("frameIndex") or 0) for row in rows}
        if frame_count != 16 or frames != set(range(16)):
            bad_targets.append({
                "targetId": target_id,
                "frameCount": frame_count,
                "actualFrames": sorted(frames),
            })
    return {
        "walkTargetCount": len(walk_targets),
        "walkArtPieces": sum(len(rows) for rows in walk_targets.values()),
        "badTargetCount": len(bad_targets),
        "badTargetSamples": bad_targets[:20],
    }


def recursive_report() -> dict[str, Any]:
    try:
        from alpecca import cognition
        cognition.init_db()
        scorecard = cognition.recursive_engagement_scorecard()
    except Exception as error:
        return {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
            "scorecard": None,
        }
    curriculum = scorecard.get("curriculum") if isinstance(scorecard, dict) else {}
    return {
        "ok": bool(scorecard.get("ok")),
        "score": scorecard.get("score"),
        "curriculumMode": (curriculum or {}).get("mode"),
        "activatedSystem": (curriculum or {}).get("activated_system"),
        "nextGate": (curriculum or {}).get("next_gate"),
        "scorecard": scorecard,
    }


def run_audit(queue_path: Path, art_status_path: Path, report_path: Path) -> dict[str, Any]:
    queue = load_json(queue_path)
    art_status = load_json(art_status_path) if art_status_path.exists() else {}
    jobs = load_worker_jobs(queue)
    sectors = sector_group_report(jobs)
    resolution = resolution_report(jobs)
    walks = walk_report(jobs)
    recursive = recursive_report()

    target_count = int(queue.get("targetCount") or 0)
    job_count = len(jobs)
    raw_strips = int(art_status.get("rawStripCount") or 0)
    approved = int(art_status.get("approvedSpritesheetCount") or 0)
    imported_tiles = int(art_status.get("importedFrameTileCount") or 0)
    storage_policy = str(queue.get("storagePolicy") or "")
    resolution_policy = str(queue.get("sourceResolutionPolicy") or "")
    runtime_policy = str(queue.get("runtimePolicy") or "")

    checks = [
        check(
            "billboard_target_count",
            "At least 186 billboard/source targets are queued",
            target_count >= 186,
            f"{target_count} targets",
        ),
        check(
            "art_piece_count",
            "More than 400 art pieces are queued",
            job_count > 400,
            f"{job_count} jobs/art pieces",
        ),
        check(
            "native_16_sector_groups",
            "Each camera/action group resolves to native 16-sector views",
            sectors["incomplete16SectorGroups"] == 0 and sectors["groupCount"] > 0,
            f"{sectors['complete16SectorGroups']}/{sectors['groupCount']} groups complete",
        ),
        check(
            "resolution_4k_to_8k",
            "Every queued source tile is 4K-8K square",
            resolution["invalidCount"] == 0 and job_count > 0,
            f"sizes={resolution['sizes']}; invalid={resolution['invalidCount']}",
        ),
        check(
            "walk_16_frame_cycles",
            "Walk targets use 16-frame cycles",
            walks["badTargetCount"] == 0 and walks["walkTargetCount"] > 0,
            f"{walks['walkTargetCount']} walk targets; {walks['walkArtPieces']} walk pieces",
        ),
        check(
            "hf_art_storage_policy",
            "Source/generated art is assigned to Hugging Face storage",
            "Hugging Face" in storage_policy and "Cloudflare hosts only the app" in storage_policy,
            storage_policy,
        ),
        check(
            "runtime_not_loose_4k",
            "Runtime policy avoids loading loose 4K tiles in browser",
            "Do not load loose 4K tiles" in runtime_policy,
            runtime_policy,
        ),
        check(
            "production_pixels_generated",
            "Generated tiles have been imported/stitched into source strips",
            raw_strips > 0 and imported_tiles > 0,
            f"rawStrips={raw_strips}; importedFrameTiles={imported_tiles}",
            blocking=False,
        ),
        check(
            "approved_runtime_candidates",
            "Approved runtime spritesheets exist",
            approved > 0,
            f"approvedSpritesheetCount={approved}",
            blocking=False,
        ),
        check(
            "recursive_engagement_scorecard",
            "Recursive engagement has observable promptless evidence",
            bool(recursive.get("ok")),
            f"score={recursive.get('score')}; curriculum={recursive.get('curriculumMode')}; nextGate={recursive.get('nextGate')}",
        ),
    ]
    blocking_failures = [row for row in checks if row["blocking"] and not row["ok"]]
    completion_failures = [row for row in checks if not row["ok"]]
    report = {
        "schemaVersion": 1,
        "stage": "alpecca-master-goal-contract",
        "generatedAt": utc_now(),
        "status": "complete" if not completion_failures else "in_progress",
        "queueContractPass": not blocking_failures,
        "completionPass": not completion_failures,
        "checks": checks,
        "counts": {
            "targetCount": target_count,
            "jobCount": job_count,
            "rawStripCount": raw_strips,
            "approvedSpritesheetCount": approved,
            "importedFrameTileCount": imported_tiles,
        },
        "storagePolicy": storage_policy,
        "sourceResolutionPolicy": resolution_policy,
        "runtimePolicy": runtime_policy,
        "sectorGroups": sectors,
        "resolution": resolution,
        "walk": walks,
        "recursiveEngagement": recursive,
        "nextRequiredStep": (
            "Run a 4K generation proof, QA it, then generate/import/stitch full raw strips."
            if raw_strips == 0 else
            "Continue visual QA and runtime promotion of generated strips."
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--art-status", type=Path, default=DEFAULT_ART_STATUS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = run_audit(args.queue, args.art_status, args.report)
    print(json.dumps({
        "status": report["status"],
        "queueContractPass": report["queueContractPass"],
        "completionPass": report["completionPass"],
        "counts": report["counts"],
        "failedChecks": [row["id"] for row in report["checks"] if not row["ok"]],
        "report": str(args.report),
        "nextRequiredStep": report["nextRequiredStep"],
    }, indent=2))
    return 0 if report["queueContractPass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
