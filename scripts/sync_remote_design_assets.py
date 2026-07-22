"""Restore the exact remote Alpecca design inputs from private HF storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "docs" / "manifests" / "alpecca_remote_design_v5.json"
SCHEMA = "alpecca.remote-design-assets.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_local_path(root: Path, value: str) -> Path:
    relative = Path(value.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe local asset path: {value}")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"asset path leaves repository: {value}")
    if not relative.parts or relative.parts[0] != "data":
        raise ValueError(f"design assets must restore under data/: {value}")
    return resolved


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError("unsupported remote design manifest schema")
    if payload.get("repo_type") != "dataset":
        raise ValueError("remote design assets must use a Hugging Face dataset")
    assets = payload.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("remote design manifest contains no assets")
    seen: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("invalid asset entry")
        local_path = str(asset.get("local_path", ""))
        remote_path = str(asset.get("remote_path", ""))
        digest = str(asset.get("sha256", "")).lower()
        size = asset.get("bytes")
        _safe_local_path(ROOT, local_path)
        if not remote_path or remote_path.startswith("/") or ".." in Path(remote_path).parts:
            raise ValueError(f"unsafe remote asset path: {remote_path}")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"invalid sha256 for {local_path}")
        if not isinstance(size, int) or size < 1:
            raise ValueError(f"invalid byte count for {local_path}")
        if local_path in seen:
            raise ValueError(f"duplicate local asset path: {local_path}")
        seen.add(local_path)
    return payload


def verify_asset(path: Path, asset: dict[str, Any]) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    if path.stat().st_size != asset["bytes"]:
        return False, "size mismatch"
    if _sha256(path) != asset["sha256"]:
        return False, "sha256 mismatch"
    return True, "verified"


def download_assets(manifest: dict[str, Any], root: Path) -> int:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise SystemExit("Install huggingface_hub and authenticate with `hf auth login`.") from exc

    failures = 0
    for asset in manifest["assets"]:
        target = _safe_local_path(root, asset["local_path"])
        ok, status = verify_asset(target, asset)
        if ok:
            print(f"verified  {asset['role']}: {asset['local_path']}")
            continue
        print(f"download  {asset['role']}: {status}")
        cached = Path(
            hf_hub_download(
                repo_id=manifest["repo_id"],
                repo_type=manifest["repo_type"],
                revision=manifest["revision"],
                filename=asset["remote_path"],
            )
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.download")
        shutil.copyfile(cached, temporary)
        ok, status = verify_asset(temporary, asset)
        if not ok:
            temporary.unlink(missing_ok=True)
            print(f"failed    {asset['local_path']}: {status}")
            failures += 1
            continue
        os.replace(temporary, target)
        print(f"restored  {asset['local_path']}")
    return failures


def verify_local(manifest: dict[str, Any], root: Path) -> int:
    failures = 0
    for asset in manifest["assets"]:
        target = _safe_local_path(root, asset["local_path"])
        ok, status = verify_asset(target, asset)
        print(f"{'verified' if ok else 'failed':8} {asset['local_path']}: {status}")
        failures += 0 if ok else 1
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--root", type=Path, default=ROOT)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--download", action="store_true")
    action.add_argument("--verify-local", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest.resolve())
    failures = download_assets(manifest, args.root) if args.download else verify_local(manifest, args.root)
    if failures:
        print(f"Remote design asset gate failed: {failures} asset(s).")
        return 1
    print("Remote design asset gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
