"""Download, QA, import, and stitch one returned Stage 4 target.

Use this after a target-aware GPU run, for example `gen-0149`, has uploaded all
16 frames to the Hugging Face art dataset. This script is target-centric, not
turnaround-centric: it verifies all frames for one target/sector/action cycle
before importing and stitching `incoming/raw_strip.png`.

It never approves runtime art by itself. The resulting strip still needs human
visual QA before Stage 5 runtime atlas promotion.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from download_alpecca_stage4_worker_outputs import download_prefix
from import_alpecca_stage4_tile_outputs import import_outputs, load_jobs, resolve_repo_path
from qa_alpecca_stage4_tile_outputs import qa_outputs
from stitch_alpecca_stage4_tiles import stitch


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO_ID = "CREATORJD/alpecca-art-library"
DEFAULT_PREFIX = "stage4-worker-outputs/target-runs/gen-0149"
DEFAULT_MANIFEST = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "target_runs" / "gen-0149" / "tile_job_manifest_gen-0149.json"
DEFAULT_OUT_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "returned_targets"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_font(size: int = 18):
    for name in ("arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def target_coverage(manifest: Path, target_id: str | None = None) -> dict[str, Any]:
    jobs = load_jobs(manifest)
    if target_id:
        jobs = [job for job in jobs if str(job.get("targetId") or "") == target_id]
    if not jobs:
        return {
            "targetId": target_id or "",
            "jobCount": 0,
            "expectedFrameCount": 0,
            "frameIndexes": [],
            "fullTarget": False,
            "targetDir": "",
            "matrixKey": "",
        }
    first = jobs[0]
    expected = int(first.get("frameCount") or len(jobs))
    frames = sorted({int(job.get("frameIndex") or 0) for job in jobs})
    return {
        "targetId": str(first.get("targetId") or target_id or ""),
        "jobCount": len(jobs),
        "expectedFrameCount": expected,
        "frameIndexes": frames,
        "fullTarget": frames == list(range(expected)),
        "targetDir": str(resolve_repo_path(str(first.get("targetJson"))).parent),
        "matrixKey": str(first.get("matrixKey") or ""),
    }


def render_strip_preview(raw_strip: Path, out_path: Path, *, target_id: str, matrix_key: str) -> str | None:
    if not raw_strip.exists():
        return None
    with Image.open(raw_strip) as image:
        rgba = image.convert("RGBA")
        frame_count = 16
        frame_size = rgba.height
        if rgba.width % frame_size == 0:
            frame_count = max(1, rgba.width // frame_size)
        thumb = 256
        header = 70
        cell_w = thumb + 16
        canvas = Image.new("RGBA", (frame_count * cell_w + 16, header + thumb + 54), (18, 24, 38, 255))
        draw = ImageDraw.Draw(canvas)
        font = load_font(18)
        small = load_font(13)
        draw.text((14, 14), f"Alpecca Stage 4 Target Preview: {target_id} / {matrix_key}", fill=(240, 249, 255, 255), font=font)
        draw.text((14, 42), "Preview only. Human design-lock QA required before runtime promotion.", fill=(180, 198, 215, 255), font=small)
        for index in range(frame_count):
            frame = rgba.crop((index * frame_size, 0, (index + 1) * frame_size, frame_size))
            bg = Image.new("RGBA", (thumb, thumb), (226, 232, 240, 255))
            checker = ImageDraw.Draw(bg)
            for y in range(0, thumb, 16):
                for x in range(0, thumb, 16):
                    if ((x // 16) + (y // 16)) % 2:
                        checker.rectangle((x, y, x + 15, y + 15), fill=(196, 207, 220, 255))
            bg.alpha_composite(frame.resize((thumb, thumb), Image.Resampling.LANCZOS), (0, 0))
            x = 12 + index * cell_w
            y = header
            canvas.alpha_composite(bg, (x, y))
            draw.text((x, y + thumb + 7), f"f{index:03d}", fill=(203, 213, 225, 255), font=small)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(out_path, quality=92)
    return str(out_path.relative_to(REPO_ROOT)).replace("\\", "/")


def process_target(
    *,
    repo_id: str,
    repo_type: str,
    prefix: str,
    manifest: Path,
    out_root: Path,
    target_id: str | None,
    skip_download: bool,
    outputs_root: Path | None,
    apply_import: bool,
    apply_stitch: bool,
) -> dict[str, Any]:
    manifest = manifest if manifest.is_absolute() else REPO_ROOT / manifest
    out_root = out_root if out_root.is_absolute() else REPO_ROOT / out_root
    download = None
    if skip_download:
        if outputs_root is None:
            raise SystemExit("--outputs-root is required with --skip-download")
        destination_root = outputs_root if outputs_root.is_absolute() else REPO_ROOT / outputs_root
    else:
        download = download_prefix(repo_id, prefix, out_root, repo_type)
        destination_root = REPO_ROOT / str(download["destinationRoot"])

    qa_root = destination_root / "qa_target"
    coverage = target_coverage(manifest, target_id=target_id)
    qa = qa_outputs(manifest, destination_root, qa_root / "tile_mechanical", target_id=coverage["targetId"], thumb_size=256)
    gates_pass = (
        coverage["fullTarget"]
        and int(qa.get("missingJobCount") or 0) == 0
        and int(qa.get("blockedJobCount") or 0) == 0
    )
    import_report = None
    stitch_report = None
    preview = None
    if gates_pass and apply_import:
        import_report = import_outputs(manifest, destination_root, apply=True)
    if gates_pass and apply_import and apply_stitch:
        stitch_report = stitch(Path(coverage["targetDir"]), apply=True)
        raw_strip = Path(stitch_report.get("rawStripOutput") or "")
        preview = render_strip_preview(
            raw_strip,
            qa_root / f"{coverage['targetId']}_raw_strip_preview.jpg",
            target_id=coverage["targetId"],
            matrix_key=coverage["matrixKey"],
        )
    summary = {
        "schemaVersion": 1,
        "stage": "stage-4-returned-target-process",
        "generatedAt": utc_now(),
        "repoId": repo_id,
        "repoType": repo_type,
        "prefix": prefix,
        "manifest": str(manifest),
        "destinationRoot": str(destination_root.relative_to(REPO_ROOT)).replace("\\", "/"),
        "targetId": coverage["targetId"],
        "matrixKey": coverage["matrixKey"],
        "skipDownload": skip_download,
        "applyImport": apply_import,
        "applyStitch": apply_stitch,
        "gatesPass": gates_pass,
        "coverage": coverage,
        "tileQa": {
            "report": str((qa_root / "tile_mechanical" / "tile_visual_qa_report.json").relative_to(REPO_ROOT)).replace("\\", "/"),
            "readyJobCount": qa.get("readyJobCount"),
            "missingJobCount": qa.get("missingJobCount"),
            "blockedJobCount": qa.get("blockedJobCount"),
            "readyTargetCount": qa.get("readyTargetCount"),
        },
        "import": {
            "ran": import_report is not None,
            "readyCount": import_report.get("readyCount") if import_report else 0,
            "importedCount": import_report.get("importedCount") if import_report else 0,
        },
        "stitch": {
            "ran": stitch_report is not None,
            "status": stitch_report.get("status") if stitch_report else "",
            "rawStripOutput": stitch_report.get("rawStripOutput") if stitch_report else "",
            "preview": preview,
        },
        "download": download,
        "nextStep": (
            "Inspect the raw strip preview and run Stage 5 runtime atlas compilation only after visual approval."
            if stitch_report and stitch_report.get("status") == "stitched"
            else "Run with --apply-import --apply-stitch after all target frames pass QA."
            if gates_pass else
            "Generate or fix missing/blocked target frames before import."
        ),
    }
    write_json(destination_root / "returned_target_process_report.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--repo-type", default="dataset")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--target-id")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--outputs-root", type=Path)
    parser.add_argument("--apply-import", action="store_true")
    parser.add_argument("--apply-stitch", action="store_true")
    args = parser.parse_args()
    summary = process_target(
        repo_id=args.repo_id,
        repo_type=args.repo_type,
        prefix=args.prefix,
        manifest=args.manifest,
        out_root=args.out_root,
        target_id=args.target_id,
        skip_download=args.skip_download,
        outputs_root=args.outputs_root,
        apply_import=args.apply_import,
        apply_stitch=args.apply_stitch,
    )
    print(json.dumps({
        "gatesPass": summary["gatesPass"],
        "targetId": summary["targetId"],
        "matrixKey": summary["matrixKey"],
        "coverage": {
            "jobCount": summary["coverage"]["jobCount"],
            "expectedFrameCount": summary["coverage"]["expectedFrameCount"],
            "fullTarget": summary["coverage"]["fullTarget"],
        },
        "tileQa": summary["tileQa"],
        "import": summary["import"],
        "stitch": summary["stitch"],
        "report": str((REPO_ROOT / summary["destinationRoot"] / "returned_target_process_report.json")),
        "nextStep": summary["nextStep"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
