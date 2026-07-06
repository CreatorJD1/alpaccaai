"""Publish Alpecca art to Hugging Face storage.

Cloudflare should only host the lightweight app shell. Hugging Face is the source
of truth for Alpecca's large source-art archive, generated-art batches, and the
browser-safe runtime asset bundle that the Cloudflare shell can fetch remotely.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_REPO_ID = "CREATORJD/alpecca-art-library"
DEFAULT_RUNTIME_REPO_ID = "CREATORJD/alpecca-runtime-assets"
DEFAULT_LIBRARY_ROOT = REPO_ROOT / "data" / "alpecca_art_source"
DEFAULT_GENERATED_ROOT = REPO_ROOT / "data" / "alpecca_generated_art"
DEFAULT_RUNTIME_ASSETS_ROOT = REPO_ROOT / "apps" / "house-hq" / "public" / "assets"
DEFAULT_RUNTIME_UPLOAD_STAGING = REPO_ROOT / "output" / "hf_runtime_assets_upload"
RUNTIME_METADATA_EXTENSIONS = {".json", ".md", ".txt"}


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def upload_folder(repo_id: str, local_path: Path, path_in_repo: str, message: str, large: bool) -> None:
    if not local_path.exists():
        print(f"Skipping missing folder: {local_path}")
        return
    if large:
        run(
            [
                "hf",
                "upload-large-folder",
                repo_id,
                str(local_path),
                "--type",
                "dataset",
                "--include",
                "**",
            ]
        )
        return
    run(
        [
            "hf",
            "upload",
            repo_id,
            str(local_path),
            path_in_repo,
            "--type",
            "dataset",
            "--commit-message",
            message,
        ]
    )


def ensure_clean_output_dir(path: Path) -> None:
    resolved = path.resolve()
    output_root = (REPO_ROOT / "output").resolve()
    if not str(resolved).startswith(str(output_root)):
        raise RuntimeError(f"Refusing to clean unexpected path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def upload_runtime_assets(repo_id: str, runtime_root: Path, staging_root: Path, workers: int) -> None:
    if not runtime_root.exists():
        print(f"Skipping missing runtime assets folder: {runtime_root}")
        return
    ensure_clean_output_dir(staging_root)
    staged_assets_root = staging_root / "runtime-assets" / "assets"
    shutil.copytree(runtime_root, staged_assets_root)
    run(
        [
            "hf",
            "upload-large-folder",
            repo_id,
            str(staging_root),
            "--type",
            "dataset",
            "--num-workers",
            str(workers),
        ]
    )


def upload_runtime_metadata(repo_id: str, runtime_root: Path, staging_root: Path, workers: int) -> None:
    if not runtime_root.exists():
        print(f"Skipping missing runtime assets folder: {runtime_root}")
        return
    ensure_clean_output_dir(staging_root)
    staged_assets_root = staging_root / "runtime-assets" / "assets"
    copied = 0
    for source in runtime_root.rglob("*"):
        if not source.is_file() or source.suffix.lower() not in RUNTIME_METADATA_EXTENSIONS:
            continue
        destination = staged_assets_root / source.relative_to(runtime_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    if copied == 0:
        print(f"No runtime metadata files found under: {runtime_root}")
        return
    run(
        [
            "hf",
            "upload-large-folder",
            repo_id,
            str(staging_root),
            "--type",
            "dataset",
            "--num-workers",
            str(workers),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default=DEFAULT_SOURCE_REPO_ID, help="Private source/generated art dataset repo.")
    parser.add_argument("--runtime-repo-id", default=DEFAULT_RUNTIME_REPO_ID, help="Public browser-safe runtime asset dataset repo.")
    parser.add_argument("--library-root", type=Path, default=DEFAULT_LIBRARY_ROOT)
    parser.add_argument("--generated-root", type=Path, default=DEFAULT_GENERATED_ROOT)
    parser.add_argument("--runtime-assets-root", type=Path, default=DEFAULT_RUNTIME_ASSETS_ROOT)
    parser.add_argument("--runtime-upload-staging", type=Path, default=DEFAULT_RUNTIME_UPLOAD_STAGING)
    parser.add_argument("--runtime-upload-workers", type=int, default=4)
    parser.add_argument("--skip-source", action="store_true")
    parser.add_argument("--large-generated", action="store_true", help="Use resumable large-folder upload for generated art.")
    parser.add_argument("--skip-generated", action="store_true")
    parser.add_argument("--skip-runtime-assets", action="store_true")
    parser.add_argument("--runtime-metadata-only", action="store_true", help="Upload only runtime JSON/MD/TXT metadata for fast stage/status sync.")
    args = parser.parse_args()

    run(["hf", "repos", "create", args.repo_id, "--type", "dataset", "--private", "--exist-ok"])
    if not args.skip_runtime_assets:
        run(["hf", "repos", "create", args.runtime_repo_id, "--type", "dataset", "--exist-ok"])
    if not args.skip_source:
        upload_folder(
            args.repo_id,
            args.library_root,
            "source-library",
            "Sync Alpecca source library and design lock references",
            large=False,
        )
    if not args.skip_generated:
        upload_folder(
            args.repo_id,
            args.generated_root,
            "generated-art",
            "Sync Alpecca generated art batches",
            large=args.large_generated,
        )
    if not args.skip_runtime_assets:
        if args.runtime_metadata_only:
            upload_runtime_metadata(args.runtime_repo_id, args.runtime_assets_root, args.runtime_upload_staging, args.runtime_upload_workers)
        else:
            upload_runtime_assets(args.runtime_repo_id, args.runtime_assets_root, args.runtime_upload_staging, args.runtime_upload_workers)
    print(f"Alpecca source/generated art synced to https://huggingface.co/datasets/{args.repo_id}")
    print(f"Runtime asset base: https://huggingface.co/datasets/{args.runtime_repo_id}/resolve/main/runtime-assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
