"""Install pinned CPU face-familiarity evaluation models without enabling them."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "docs" / "manifests" / "face_familiarity_models.json"
SCHEMA = "alpecca.face-familiarity-models.v1"
_MODEL_URL = re.compile(
    r"^/media/opencv/opencv_zoo/(?P<revision>[0-9a-f]{40})/models/.+\.onnx$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """Raised when the pinned asset manifest is invalid."""


class UnsafePathError(ValueError):
    """Raised when an install path could escape or traverse a link."""


class AssetVerificationError(RuntimeError):
    """Raised when downloaded bytes do not match the pinned manifest."""


def default_target_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / "AppData" / "Local"
    return base / "Alpecca" / "models" / "face"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _reject_link_components(path: Path) -> None:
    absolute = Path(os.path.abspath(os.path.expandvars(str(path.expanduser()))))
    for component in (*reversed(absolute.parents), absolute):
        if _is_link(component):
            raise UnsafePathError(f"symlink or junction is not allowed: {component}")


def _prepare_target_root(path: Path) -> Path:
    target_root = Path(os.path.abspath(os.path.expandvars(str(path.expanduser()))))
    _reject_link_components(target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    _reject_link_components(target_root)
    if not target_root.is_dir():
        raise UnsafePathError(f"target root is not a directory: {target_root}")
    return target_root


def _validated_filename(filename: str) -> str:
    relative = Path(filename.replace("\\", "/"))
    if (
        relative.is_absolute()
        or len(relative.parts) != 1
        or not relative.name
        or relative.name in {".", ".."}
    ):
        raise UnsafePathError(f"asset filename must stay directly under the target root: {filename}")
    return relative.name


def _safe_target(target_root: Path, filename: str) -> Path:
    safe_name = _validated_filename(filename)
    target = target_root / safe_name
    try:
        target.relative_to(target_root)
    except ValueError as exc:
        raise UnsafePathError(f"asset path leaves the target root: {filename}") from exc
    _reject_link_components(target)
    if target.exists() and not target.is_file():
        raise UnsafePathError(f"asset target is not a regular file: {target}")
    return target


def _validate_asset(asset: Any, seen: set[str]) -> dict[str, Any]:
    if not isinstance(asset, dict):
        raise ManifestError("every asset entry must be an object")

    required = {
        "name",
        "role",
        "filename",
        "url",
        "revision",
        "bytes",
        "sha256",
        "license",
        "license_url",
    }
    missing = sorted(required.difference(asset))
    if missing:
        raise ManifestError(f"asset is missing required fields: {', '.join(missing)}")

    filename = _validated_filename(str(asset["filename"]))
    if not filename.lower().endswith(".onnx"):
        raise ManifestError(f"asset is not an ONNX model: {filename}")
    if filename in seen:
        raise ManifestError(f"duplicate asset filename: {filename}")
    seen.add(filename)

    parsed = urlsplit(str(asset["url"]))
    match = _MODEL_URL.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "media.githubusercontent.com"
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise ManifestError(f"asset URL is not a pinned official OpenCV Zoo model: {filename}")
    revision = str(asset["revision"])
    if revision != match.group("revision"):
        raise ManifestError(f"asset URL revision does not match manifest revision: {filename}")

    size = asset["bytes"]
    digest = str(asset["sha256"]).lower()
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise ManifestError(f"invalid byte count for {filename}")
    if _SHA256.fullmatch(digest) is None:
        raise ManifestError(f"invalid SHA-256 for {filename}")
    if asset["license"] not in {"MIT", "Apache-2.0"}:
        raise ManifestError(f"unsupported model license for {filename}")

    license_url = urlsplit(str(asset["license_url"]))
    expected_prefix = f"/opencv/opencv_zoo/blob/{revision}/models/"
    if (
        license_url.scheme != "https"
        or license_url.netloc != "github.com"
        or not license_url.path.startswith(expected_prefix)
    ):
        raise ManifestError(f"license URL is not pinned to the model revision: {filename}")

    normalized = dict(asset)
    normalized["sha256"] = digest
    return normalized


def validate_manifest(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ManifestError("unsupported face-familiarity manifest schema")
    if payload.get("evaluation_only") is not True:
        raise ManifestError("face-familiarity assets must be marked evaluation-only")
    if payload.get("enables_runtime") is not False:
        raise ManifestError("the asset manifest must not enable runtime behavior")
    assets = payload.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ManifestError("face-familiarity manifest contains no assets")

    seen: set[str] = set()
    normalized = dict(payload)
    normalized["assets"] = [_validate_asset(asset, seen) for asset in assets]
    return normalized


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    return validate_manifest(json.loads(path.read_text(encoding="utf-8")))


def verify_asset(path: Path, asset: dict[str, Any]) -> tuple[bool, str]:
    if _is_link(path):
        raise UnsafePathError(f"asset target cannot be a symlink or junction: {path}")
    if not path.is_file():
        return False, "missing"
    if path.stat().st_size != asset["bytes"]:
        return False, "size mismatch"
    if _sha256(path) != asset["sha256"]:
        return False, "sha256 mismatch"
    return True, "verified"


def _download_verified(
    asset: dict[str, Any],
    target_root: Path,
    *,
    opener: Callable[..., Any],
    timeout: float,
) -> Path:
    target = _safe_target(target_root, asset["filename"])
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target_root,
        prefix=f".{target.name}.",
        suffix=".download",
    )
    temporary = Path(temporary_name)
    try:
        request = Request(
            asset["url"],
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "Alpecca-face-familiarity-installer/1",
            },
        )
        written = 0
        with os.fdopen(descriptor, "wb") as destination:
            descriptor = -1
            with opener(request, timeout=timeout) as response:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > asset["bytes"]:
                        raise AssetVerificationError(
                            f"download exceeded pinned size for {asset['filename']}"
                        )
                    destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())

        ok, status = verify_asset(temporary, asset)
        if not ok:
            raise AssetVerificationError(f"{asset['filename']}: {status}")

        # Recheck after network I/O so a swapped link cannot redirect promotion.
        _reject_link_components(target_root)
        target = _safe_target(target_root, asset["filename"])
        os.replace(temporary, target)
        ok, status = verify_asset(target, asset)
        if not ok:
            raise AssetVerificationError(f"post-install verification failed: {status}")
        return target
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def install_assets(
    manifest: dict[str, Any],
    target_root: Path,
    *,
    opener: Callable[..., Any] | None = None,
    timeout: float = 60.0,
) -> dict[str, str]:
    manifest = validate_manifest(manifest)
    root = _prepare_target_root(target_root)
    open_url = opener or urlopen
    results: dict[str, str] = {}
    for asset in manifest["assets"]:
        target = _safe_target(root, asset["filename"])
        ok, _ = verify_asset(target, asset)
        if ok:
            results[asset["name"]] = "already verified"
            continue
        _download_verified(asset, root, opener=open_url, timeout=timeout)
        results[asset["name"]] = "installed"
    return results


def verify_assets(manifest: dict[str, Any], target_root: Path) -> dict[str, str]:
    manifest = validate_manifest(manifest)
    root = _prepare_target_root(target_root)
    results: dict[str, str] = {}
    for asset in manifest["assets"]:
        target = _safe_target(root, asset["filename"])
        ok, status = verify_asset(target, asset)
        results[asset["name"]] = status if ok else f"failed: {status}"
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--target", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--install", action="store_true", help="download and verify the pinned assets")
    action.add_argument("--verify", action="store_true", help="verify installed assets without network access")
    args = parser.parse_args(argv)

    target = args.target or default_target_root()
    try:
        manifest = load_manifest(args.manifest)
        results = (
            install_assets(manifest, target, timeout=args.timeout)
            if args.install
            else verify_assets(manifest, target)
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Face familiarity asset gate failed: {exc}", file=sys.stderr)
        return 1

    failed = False
    for name, status in results.items():
        print(f"{name}: {status}")
        failed = failed or status.startswith("failed:")
    print("Evaluation assets only; no Alpecca runtime capability was enabled.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
