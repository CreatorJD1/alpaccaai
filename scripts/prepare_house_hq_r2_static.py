"""Prepare and optionally upload the House HQ static shell for Cloudflare R2.

The public R2 endpoint is a static object host, not a dev server. This script
copies the Vite build into a clean upload folder, adds SPA aliases for
``/house-hq`` routes, and can upload the objects through Wrangler when the
machine is logged in to Cloudflare. Alpecca art assets are excluded by default;
they belong in Hugging Face storage and are loaded by the app through the
configured art base URL.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "apps" / "house-hq" / "dist"
OUTPUT_ROOT = REPO_ROOT / "output"
PACKAGE_DIR = OUTPUT_ROOT / "house-hq-r2-static"
PREVIEW_RECORD = REPO_ROOT / "data" / "r2_preview.json"


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".wasm": "application/wasm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}

ART_ASSET_PREFIXES = (
    "assets/alpecca",
    "assets/alpecca-avatar",
    "assets/alpecca-chat",
    "assets/alpecca-expressions",
    "assets/alpecca-optimized",
    "assets/alpecca-source",
)


def rel_key(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def content_type_for(path: Path) -> str:
    if path.name == "house-hq":
        return CONTENT_TYPES[".html"]
    if path.suffix.lower() in CONTENT_TYPES:
        return CONTENT_TYPES[path.suffix.lower()]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def is_alpecca_art_asset(key: str) -> bool:
    normalized = key.replace("\\", "/")
    return any(normalized == prefix or normalized.startswith(f"{prefix}/") for prefix in ART_ASSET_PREFIXES)


def ensure_clean_output(path: Path) -> None:
    resolved = path.resolve()
    output_root = OUTPUT_ROOT.resolve()
    if not str(resolved).startswith(str(output_root)):
        raise RuntimeError(f"Refusing to clean unexpected path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def run_build() -> None:
    subprocess.run(["npm.cmd", "run", "house:build"], cwd=REPO_ROOT, check=True)


def copy_dist(dist_dir: Path, package_dir: Path, include_art_assets: bool) -> list[str]:
    if not dist_dir.exists():
        raise FileNotFoundError(
            f"House HQ dist folder was not found: {dist_dir}. Run npm.cmd run house:build first."
        )
    ensure_clean_output(package_dir)
    skipped_art_assets: list[str] = []
    for source in dist_dir.rglob("*"):
        if not source.is_file():
            continue
        key = rel_key(source, dist_dir)
        if not include_art_assets and is_alpecca_art_asset(key):
            skipped_art_assets.append(key)
            continue
        target = package_dir / source.relative_to(dist_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return skipped_art_assets


def add_spa_aliases(package_dir: Path) -> None:
    index = package_dir / "index.html"
    if not index.exists():
        raise FileNotFoundError(f"index.html was not found in packaged build: {index}")

    house_index = package_dir / "house-hq" / "index.html"
    house_index.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(index, house_index)


def build_manifest(package_dir: Path, public_url: str, skipped_art_assets: list[str]) -> dict:
    files = []
    index_path = package_dir / "index.html"
    if index_path.exists():
        files.append(
            {
                "key": "house-hq",
                "path": str(index_path),
                "bytes": index_path.stat().st_size,
                "contentType": CONTENT_TYPES[".html"],
                "aliasOf": "index.html",
            }
        )
    for file_path in sorted(package_dir.rglob("*")):
        if not file_path.is_file():
            continue
        key = rel_key(file_path, package_dir)
        files.append(
            {
                "key": key,
                "path": str(file_path),
                "bytes": file_path.stat().st_size,
                "contentType": content_type_for(file_path),
            }
        )

    base_url = public_url.rstrip("/")
    expected = {
        "root": f"{base_url}/" if base_url else "",
        "index": f"{base_url}/index.html" if base_url else "",
        "houseHq": f"{base_url}/house-hq" if base_url else "",
        "houseHqIndex": f"{base_url}/house-hq/index.html" if base_url else "",
    }
    return {
        "packageDir": str(package_dir),
        "publicUrl": public_url,
        "artStorage": "hugging-face",
        "artAssetsExcluded": bool(skipped_art_assets),
        "excludedArtAssetCount": len(skipped_art_assets),
        "excludedArtAssetSamples": skipped_art_assets[:20],
        "expectedUrls": expected,
        "fileCount": len(files),
        "files": files,
    }


def find_wrangler() -> list[str] | None:
    direct = shutil.which("wrangler")
    if direct:
        return [direct]
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if npx:
        return [npx, "--yes", "wrangler"]
    return None


def upload_with_wrangler(manifest: dict, bucket: str) -> None:
    wrangler = find_wrangler()
    if not wrangler:
        raise RuntimeError("Wrangler was not found. Install it or use npx.cmd with Cloudflare auth.")

    for entry in manifest["files"]:
        object_name = f"{bucket}/{entry['key']}"
        cmd = [
            *wrangler,
            "r2",
            "object",
            "put",
            object_name,
            "--file",
            entry["path"],
            "--content-type",
            entry["contentType"],
            "--remote",
        ]
        for attempt in range(1, 4):
            try:
                subprocess.run(cmd, cwd=REPO_ROOT, check=True)
                break
            except subprocess.CalledProcessError:
                if attempt == 3:
                    raise
                time.sleep(2 * attempt)


def validate_public_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid public URL: {value}")
    return value.rstrip("/")


def write_preview_record(manifest: dict, uploaded: bool, bucket: str) -> None:
    PREVIEW_RECORD.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "uploaded": uploaded,
        "bucket": bucket,
        "publicUrl": manifest["publicUrl"],
        "houseHqUrl": manifest["expectedUrls"]["houseHq"],
        "indexUrl": manifest["expectedUrls"]["index"],
        "fileCount": manifest["fileCount"],
    }
    PREVIEW_RECORD.write_text(json.dumps(record, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-url", default=os.environ.get("ALPECCA_R2_PUBLIC_URL", ""))
    parser.add_argument("--bucket", default=os.environ.get("ALPECCA_R2_BUCKET", "alpeccaai"))
    parser.add_argument("--dist", default=str(DIST_DIR))
    parser.add_argument("--out", default=str(PACKAGE_DIR))
    parser.add_argument("--build", action="store_true", help="Run npm.cmd run house:build before packaging.")
    parser.add_argument("--upload", action="store_true", help="Upload packaged files with Wrangler.")
    parser.add_argument(
        "--include-art-assets",
        action="store_true",
        help="Include Alpecca art assets in the R2 package. Disabled by default; use Hugging Face for art storage.",
    )
    args = parser.parse_args()

    public_url = validate_public_url(args.public_url)
    dist_dir = Path(args.dist).resolve()
    package_dir = Path(args.out).resolve()

    if args.build:
        run_build()

    skipped_art_assets = copy_dist(dist_dir, package_dir, include_art_assets=args.include_art_assets)
    add_spa_aliases(package_dir)

    manifest = build_manifest(package_dir, public_url, skipped_art_assets)
    manifest_path = package_dir / "r2_upload_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    uploaded = False
    if args.upload:
        upload_with_wrangler(manifest, args.bucket)
        uploaded = True

    if public_url:
        write_preview_record(manifest, uploaded, args.bucket)

    print(f"Prepared {manifest['fileCount']} objects for R2: {package_dir}")
    if skipped_art_assets:
        print(f"Excluded {len(skipped_art_assets)} Alpecca art assets from R2 package; use Hugging Face art storage.")
    print(f"Manifest: {manifest_path}")
    if public_url:
        print(f"House HQ URL: {manifest['expectedUrls']['houseHq']}")
    if not uploaded:
        print("Upload not run. Add --upload after Cloudflare Wrangler is authenticated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
