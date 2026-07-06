"""Download Stage 4 worker outputs from Hugging Face dataset storage.

Cloudflare is only the app shell. Generated/source art lives on Hugging Face.
This helper pulls a returned worker-output prefix back into the local repo so
the normal importer, stitcher, and QA scripts can run.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO_ID = "CREATORJD/alpecca-art-library"
DEFAULT_PREFIX = "stage4-worker-outputs/colab/batch_01_chunk_000"
DEFAULT_OUT_ROOT = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "returned"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def download_prefix(repo_id: str, prefix: str, out_root: Path, repo_type: str) -> dict:
    try:
        from huggingface_hub import hf_hub_download, list_repo_files
    except ImportError as error:
        raise SystemExit("Install huggingface_hub first: pip install huggingface_hub") from error

    out_root = out_root if out_root.is_absolute() else REPO_ROOT / out_root
    prefix = prefix.strip("/").replace("\\", "/")
    files = [
        name for name in list_repo_files(repo_id, repo_type=repo_type)
        if name == prefix or name.startswith(prefix + "/")
    ]
    if not files:
        raise SystemExit(f"No files found under {repo_id}:{prefix}")

    destination_root = out_root / prefix.replace("/", "_")
    if destination_root.exists():
        shutil.rmtree(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)

    downloaded: list[dict] = []
    for repo_file in files:
        local_cached = Path(hf_hub_download(repo_id=repo_id, filename=repo_file, repo_type=repo_type))
        relative = Path(repo_file).relative_to(prefix)
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_cached, destination)
        downloaded.append({
            "repoFile": repo_file,
            "localPath": str(destination.relative_to(REPO_ROOT)).replace("\\", "/"),
            "bytes": destination.stat().st_size,
        })

    report = {
        "schemaVersion": 1,
        "stage": "stage-4-worker-output-download",
        "generatedAt": utc_now(),
        "repoId": repo_id,
        "repoType": repo_type,
        "prefix": prefix,
        "destinationRoot": str(destination_root.relative_to(REPO_ROOT)).replace("\\", "/"),
        "fileCount": len(downloaded),
        "downloaded": downloaded,
        "nextStep": (
            "Run import_alpecca_stage4_tile_outputs.py with --outputs-root set to "
            f"{destination_root.relative_to(REPO_ROOT).as_posix()}."
        ),
    }
    write_json(destination_root / "download_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--repo-type", default="dataset")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()
    report = download_prefix(args.repo_id, args.prefix, args.out_root, args.repo_type)
    print(json.dumps({
        "fileCount": report["fileCount"],
        "destinationRoot": report["destinationRoot"],
        "nextStep": report["nextStep"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
