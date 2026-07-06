"""Download and QA a returned Stage 4 Alpecca worker slice.

This command is the bridge between remote GPU generation and local promotion:
it pulls one Hugging Face worker-output prefix, runs the 16-sector turnaround QA,
and runs the per-tile mechanical QA. It does not import, stitch, or approve art.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from download_alpecca_stage4_worker_outputs import download_prefix
from qa_alpecca_stage4_tile_outputs import qa_outputs
from qa_alpecca_stage4_turnaround_outputs import qa_turnaround
from qa_alpecca_stage4_360_volume import run_volume_qa


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO_ID = "CREATORJD/alpecca-art-library"
DEFAULT_PREFIX = "stage4-worker-outputs/colab/idle_eye_16sector_frame000_turnaround"
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "output"
    / "alpecca_stage4_tile_jobs"
    / "first_slices"
    / "idle_eye_16sector_frame000_turnaround"
    / "tile_job_manifest.json"
)
DEFAULT_OUT_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "returned"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_returned_slice_qa(repo_id: str, repo_type: str, prefix: str, manifest: Path, out_root: Path, frame_index: int) -> dict[str, Any]:
    download = download_prefix(repo_id, prefix, out_root, repo_type)
    destination_root = REPO_ROOT / str(download["destinationRoot"])
    qa_root = destination_root / "qa"
    turnaround = qa_turnaround(manifest, destination_root, qa_root, frame_index=frame_index, thumb_size=384)
    volume = run_volume_qa(manifest, destination_root, qa_root / "turnaround_360_volume_report.json", frame_index=frame_index)
    tile = qa_outputs(manifest, destination_root, qa_root / "tile_mechanical", target_id=None, thumb_size=256)
    ready = (
        turnaround.get("mechanicalStatus") == "ready-for-visual-review"
        and volume.get("status") == "pass"
        and int(tile.get("missingJobCount") or 0) == 0
        and int(tile.get("blockedJobCount") or 0) == 0
    )
    summary = {
        "schemaVersion": 1,
        "stage": "stage-4-returned-slice-qa",
        "generatedAt": utc_now(),
        "repoId": repo_id,
        "repoType": repo_type,
        "prefix": prefix,
        "manifest": str(manifest),
        "destinationRoot": download["destinationRoot"],
        "turnaroundReport": str((qa_root / "turnaround_16_sector_qa_report.json").relative_to(REPO_ROOT)).replace("\\", "/"),
        "turnaroundPreview": turnaround.get("preview"),
        "volumeReport": str((qa_root / "turnaround_360_volume_report.json").relative_to(REPO_ROOT)).replace("\\", "/"),
        "tileReport": str((qa_root / "tile_mechanical" / "tile_visual_qa_report.json").relative_to(REPO_ROOT)).replace("\\", "/"),
        "readyForHumanVisualReview": ready,
        "nextStep": (
            "Inspect turnaround_16_sector_qa.jpg. If design and 360 volume pass, run "
            "import_alpecca_stage4_tile_outputs.py, then stitch_alpecca_stage4_tiles.py."
            if ready
            else "Wait for missing worker outputs or regenerate blocked sectors before import."
        ),
        "download": download,
        "turnaround": {
            "mechanicalStatus": turnaround.get("mechanicalStatus"),
            "sectorCount": turnaround.get("sectorCount"),
            "readySectorCount": turnaround.get("readySectorCount"),
            "blockedSectorCount": turnaround.get("blockedSectorCount"),
            "missingSectors": turnaround.get("missingSectors"),
        },
        "volume": {
            "status": volume.get("status"),
            "readySectorCount": volume.get("readySectorCount"),
            "issues": volume.get("issues"),
            "metrics": volume.get("metrics"),
        },
        "tile": {
            "targetCount": tile.get("targetCount"),
            "jobCount": tile.get("jobCount"),
            "readyJobCount": tile.get("readyJobCount"),
            "missingJobCount": tile.get("missingJobCount"),
            "blockedJobCount": tile.get("blockedJobCount"),
        },
    }
    write_json(destination_root / "returned_slice_qa_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--repo-type", default="dataset")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--frame-index", type=int, default=0)
    args = parser.parse_args()
    summary = run_returned_slice_qa(args.repo_id, args.repo_type, args.prefix, args.manifest, args.out_root, args.frame_index)
    print(
        json.dumps(
            {
                "readyForHumanVisualReview": summary["readyForHumanVisualReview"],
                "destinationRoot": summary["destinationRoot"],
                "turnaroundPreview": summary["turnaroundPreview"],
                "turnaround": summary["turnaround"],
                "volume": summary["volume"],
                "tile": summary["tile"],
                "nextStep": summary["nextStep"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
