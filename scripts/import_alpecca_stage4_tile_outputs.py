"""Validate and import generated Alpecca Stage 4 frame tiles."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def resolve_repo_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def image_info(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "size": None, "mode": None, "hasAlpha": False}
    try:
        with Image.open(path) as image:
            bands = image.getbands()
            return {
                "exists": True,
                "size": list(image.size),
                "mode": image.mode,
                "hasAlpha": "A" in bands or image.mode in {"LA", "PA"},
            }
    except Exception as error:
            return {"exists": False, "size": None, "mode": None, "hasAlpha": False, "error": str(error)}


def generation_sidecar(path: Path) -> dict[str, Any] | None:
    sidecar = path.with_suffix(".generation.json")
    if not sidecar.exists():
        return None
    try:
        return load_json(sidecar)
    except Exception as error:
        return {"promotionStatus": "unreadable-sidecar", "error": str(error)}


def load_jobs(manifest_path: Path) -> list[dict[str, Any]]:
    manifest = load_json(manifest_path)
    jobs: list[dict[str, Any]] = []
    for chunk in manifest.get("chunks", []):
        chunk_path = resolve_repo_path(str(chunk["file"]))
        jobs.extend(iter_jsonl(chunk_path))
    return jobs


def import_outputs(manifest_path: Path, outputs_root: Path, apply: bool) -> dict[str, Any]:
    jobs = load_jobs(manifest_path)
    imported = 0
    ready = 0
    missing = 0
    wrong_size = 0
    no_alpha = 0
    records: list[dict[str, Any]] = []
    for job in jobs:
        source = outputs_root / str(job["expectedWorkerOutput"]).replace("/", "\\")
        destination = resolve_repo_path(str(job["stage4ImportDestination"]))
        expected_size = tuple(int(value) for value in job.get("expectedSize", [4096, 4096]))
        info = image_info(source)
        sidecar = generation_sidecar(source)
        issues: list[str] = []
        if not info["exists"]:
            issues.append("missing")
            missing += 1
        elif tuple(info["size"] or []) != expected_size:
            issues.append(f"wrong-size:{info['size']}")
            wrong_size += 1
        if info["exists"] and not info["hasAlpha"]:
            issues.append("no-alpha")
            no_alpha += 1
        promotion_status = str((sidecar or {}).get("promotionStatus") or "")
        if promotion_status in {"draft-not-promotable", "unreadable-sidecar"}:
            issues.append(promotion_status)
        status = "ready" if not issues else "blocked"
        if status == "ready":
            ready += 1
            if apply:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                imported += 1
        records.append(
            {
                "jobId": job.get("jobId"),
                "targetId": job.get("targetId"),
                "frameIndex": job.get("frameIndex"),
                "source": str(source),
                "destination": str(destination),
                "info": info,
                "generation": sidecar,
                "status": status,
                "issues": issues,
            }
        )
    report = {
        "schemaVersion": 1,
        "stage": "stage-4-tile-output-import",
        "generatedAt": utc_now(),
        "manifest": str(manifest_path),
        "outputsRoot": str(outputs_root),
        "apply": apply,
        "jobCount": len(jobs),
        "readyCount": ready,
        "importedCount": imported,
        "missingCount": missing,
        "wrongSizeCount": wrong_size,
        "noAlphaCount": no_alpha,
        "records": records,
        "policy": "Only exact-size alpha PNG tiles are copied into Stage 4 frame_tiles destinations.",
    }
    report_path = manifest_path.parent / "tile_output_import_report.json"
    write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--outputs-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = import_outputs(args.manifest, args.outputs_root, args.apply)
    print(
        json.dumps(
            {
                "jobCount": report["jobCount"],
                "readyCount": report["readyCount"],
                "importedCount": report["importedCount"],
                "missingCount": report["missingCount"],
                "wrongSizeCount": report["wrongSizeCount"],
                "noAlphaCount": report["noAlphaCount"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
