"""QA Stage 4 seed frames before expensive Alpecca GPU generation.

This catches bad conditioning canvases such as T-pose/wide-arm references,
baked floor blobs, missing alpha, and missing 16-sector coverage. The seed
frames are not runtime art, but bad seeds directly cause flat/repeating 360
outputs, so this is a preflight gate.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "first_slices" / "idle_eye_16sector_frame000_turnaround" / "tile_job_manifest.json"
DEFAULT_REPORT = REPO_ROOT / "output" / "alpecca_stage4_seed_frame_qa_report.json"
SECTORS_16 = tuple(f"s{i}" for i in range(16))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def resolve_repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def crop_seed_frame(job: dict[str, Any]) -> Image.Image:
    path = resolve_repo_path(str(job["seedCanvas"]))
    image = Image.open(path).convert("RGBA")
    slot = int(job.get("slotPixels") or job.get("expectedSize", [4096, 4096])[0])
    frame_index = int(job.get("frameIndex") or 0)
    if image.width >= slot * (frame_index + 1) and image.height >= slot:
        return image.crop((frame_index * slot, 0, frame_index * slot + slot, slot))
    return image


def seed_probe(job: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []
    frame = crop_seed_frame(job)
    alpha = frame.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return {
            "jobId": job.get("jobId"),
            "matrixKey": job.get("matrixKey"),
            "viewSector16": job.get("viewSector16"),
            "status": "blocked",
            "issues": ["empty-alpha"],
        }
    left, top, right, bottom = bbox
    width = right - left
    height = bottom - top
    ratio = width / max(1, height)
    if width < 64 or height < 256:
        issues.append("seed-too-small")
    if ratio > 0.62 and str(job.get("action")) in {"idle", "listen", "talk"}:
        issues.append(f"wide-arm-or-tpose-seed:ratio:{ratio:.3f}")

    subject = frame.crop(bbox)
    subject_alpha = subject.getchannel("A")
    bottom_band_y = max(0, subject.height - int(subject.height * 0.08))
    bottom_alpha = subject_alpha.crop((0, bottom_band_y, subject.width, subject.height))
    bottom_bbox = bottom_alpha.getbbox()
    if bottom_bbox:
        bottom_width = bottom_bbox[2] - bottom_bbox[0]
        if bottom_width / max(1, width) > 0.72:
            warnings.append(f"possible-floor-or-wide-stance-seed:bottom-width:{bottom_width / max(1, width):.3f}")

    visible_alpha_mean = ImageStat.Stat(alpha.resize((64, 64))).mean[0]
    return {
        "jobId": job.get("jobId"),
        "targetId": job.get("targetId"),
        "matrixKey": job.get("matrixKey"),
        "action": job.get("action"),
        "viewSector16": job.get("viewSector16"),
        "seedCanvas": job.get("seedCanvas"),
        "alphaBounds": [left, top, right, bottom],
        "widthHeightRatio": round(ratio, 5),
        "meanAlpha": round(visible_alpha_mean, 3),
        "status": "pass" if not issues else "blocked",
        "issues": issues,
        "warnings": warnings,
    }


def run_qa(manifest_path: Path, report_path: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    jsonl_value = manifest.get("jsonl") or manifest.get("jobsFile")
    if not jsonl_value:
        chunks = manifest.get("chunks") or []
        if chunks:
            jsonl_value = chunks[0].get("file")
    if not jsonl_value:
        raise SystemExit(f"Could not find a JSONL job file in {manifest_path}")
    jsonl_path = resolve_repo_path(str(jsonl_value))
    jobs = load_jsonl(jsonl_path)
    records = [seed_probe(job) for job in jobs]
    sectors = {str(record.get("viewSector16")) for record in records}
    issues: list[str] = []
    missing = sorted(set(SECTORS_16) - sectors, key=lambda value: int(value[1:]))
    for sector in missing:
        issues.append(f"{sector}:missing-seed-job")
    for record in records:
        for item in record.get("issues") or []:
            issues.append(f"{record.get('matrixKey')}:{item}")
    warnings: list[str] = []
    for record in records:
        for item in record.get("warnings") or []:
            warnings.append(f"{record.get('matrixKey')}:{item}")
    report = {
        "schemaVersion": 1,
        "stage": "stage-4-seed-frame-qa",
        "generatedAt": utc_now(),
        "manifest": str(manifest_path),
        "jobsFile": str(jsonl_path),
        "targetCount": len(records),
        "status": "pass" if not issues else "blocked",
        "issueCount": len(issues),
        "warningCount": len(warnings),
        "issues": issues,
        "warnings": warnings,
        "records": records,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = run_qa(args.manifest, args.report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "issueCount": report["issueCount"],
                "warningCount": report["warningCount"],
                "targetCount": report["targetCount"],
                "report": str(args.report),
                "issues": report["issues"][:16],
                "warnings": report["warnings"][:16],
            },
            indent=2,
        )
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
