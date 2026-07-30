"""Content-bound approved self-images shared by local and cloud CoreMind.

The actual art is distributed from Alpecca's Hugging Face runtime-assets
dataset. The manifest and every byte digest remain source-reviewed, while the
cloud installer promotes files only after the complete missing set validates.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Callable
import urllib.parse
import urllib.request


SCHEMA = "alpecca.approved-self-images.v1"
SET_ID = "alpecca-approved-self-images-2026-07"
DATASET = "CREATORJD/alpecca-runtime-assets"
REVISION = "approved-self-images-v1"
BASE_PATH = "runtime-assets/approved-self-images/v1"
MAX_ASSET_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
EXPECTED_KINDS = (
    "portrait",
    "speaking",
    "thinking",
    "reach",
    "rest",
    "shy",
    "confirmation",
    "sleeping",
    "running",
    "balance",
    "ready",
    "rear",
)
MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "manifests"
    / "alpecca-approved-self-images-v1.json"
)
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,95}$")
_TOP_KEYS = {
    "schema",
    "setId",
    "dataset",
    "revision",
    "basePath",
    "assetCount",
    "maxAssetBytes",
    "sourceApprovalCatalog",
    "sourceApprovalSchema",
    "assets",
}
_ASSET_KEYS = {
    "kind",
    "approvalId",
    "filename",
    "runtimePath",
    "sha256",
    "byteLength",
    "mimeType",
}


class ApprovedSelfImageError(RuntimeError):
    """The approved self-image set could not be trusted or installed."""


@dataclass(frozen=True, slots=True)
class ApprovedSelfImageAsset:
    kind: str
    approval_id: str
    filename: str
    runtime_path: str
    sha256: str
    byte_length: int
    mime_type: str

    @property
    def url(self) -> str:
        revision = urllib.parse.quote(REVISION, safe="")
        path = "/".join(
            urllib.parse.quote(part, safe="")
            for part in PurePosixPath(BASE_PATH, self.filename).parts
        )
        return (
            f"https://huggingface.co/datasets/{DATASET}/resolve/"
            f"{revision}/{path}"
        )


def _read_manifest(path: Path) -> dict:
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise ApprovedSelfImageError("approved self-image manifest is too large")
        with path.open("rb") as handle:
            raw = handle.read(MAX_MANIFEST_BYTES + 1)
            if len(raw) > MAX_MANIFEST_BYTES or handle.read(1):
                raise ApprovedSelfImageError("approved self-image manifest is too large")
        value = json.loads(raw.decode("utf-8"))
    except ApprovedSelfImageError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApprovedSelfImageError("approved self-image manifest is unreadable") from exc
    if not isinstance(value, dict) or set(value) != _TOP_KEYS:
        raise ApprovedSelfImageError("approved self-image manifest shape is invalid")
    return value


def load_approved_self_images(
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[ApprovedSelfImageAsset, ...]:
    value = _read_manifest(Path(manifest_path))
    expected_header = {
        "schema": SCHEMA,
        "setId": SET_ID,
        "dataset": DATASET,
        "revision": REVISION,
        "basePath": BASE_PATH,
        "assetCount": len(EXPECTED_KINDS),
        "maxAssetBytes": MAX_ASSET_BYTES,
        "sourceApprovalCatalog": "apps/android-launcher/approved-art.json",
        "sourceApprovalSchema": "alpecca.android.approved-art.v2",
    }
    for key, expected in expected_header.items():
        if value.get(key) != expected:
            raise ApprovedSelfImageError(
                f"approved self-image manifest {key} is invalid"
            )
    raw_assets = value.get("assets")
    if not isinstance(raw_assets, list) or len(raw_assets) != len(EXPECTED_KINDS):
        raise ApprovedSelfImageError("approved self-image asset count is invalid")

    assets: list[ApprovedSelfImageAsset] = []
    runtime_paths: set[str] = set()
    filenames: set[str] = set()
    digests: set[str] = set()
    for index, raw_asset in enumerate(raw_assets):
        if not isinstance(raw_asset, dict) or set(raw_asset) != _ASSET_KEYS:
            raise ApprovedSelfImageError("approved self-image asset shape is invalid")
        kind = raw_asset.get("kind")
        approval_id = raw_asset.get("approvalId")
        filename = raw_asset.get("filename")
        runtime_path = raw_asset.get("runtimePath")
        sha256 = raw_asset.get("sha256")
        byte_length = raw_asset.get("byteLength")
        mime_type = raw_asset.get("mimeType")
        if kind != EXPECTED_KINDS[index]:
            raise ApprovedSelfImageError("approved self-image kind order is invalid")
        if not isinstance(approval_id, str) or not _ID_RE.fullmatch(approval_id):
            raise ApprovedSelfImageError("approved self-image approval ID is invalid")
        if filename != f"{kind}.png":
            raise ApprovedSelfImageError("approved self-image filename is invalid")
        if not isinstance(runtime_path, str):
            raise ApprovedSelfImageError("approved self-image runtime path is invalid")
        runtime_parts = PurePosixPath(runtime_path).parts
        if (
            not runtime_parts
            or runtime_parts[0] not in {"avatar", "character"}
            or ".." in runtime_parts
            or PurePosixPath(runtime_path).is_absolute()
        ):
            raise ApprovedSelfImageError("approved self-image runtime path is invalid")
        if not isinstance(sha256, str) or not _HEX64_RE.fullmatch(sha256):
            raise ApprovedSelfImageError("approved self-image digest is invalid")
        if type(byte_length) is not int or not 1 <= byte_length <= MAX_ASSET_BYTES:
            raise ApprovedSelfImageError("approved self-image byte length is invalid")
        if mime_type != "image/png":
            raise ApprovedSelfImageError("approved self-image MIME type is invalid")
        if runtime_path in runtime_paths or filename in filenames or sha256 in digests:
            raise ApprovedSelfImageError("approved self-image asset is duplicated")
        runtime_paths.add(runtime_path)
        filenames.add(filename)
        digests.add(sha256)
        assets.append(
            ApprovedSelfImageAsset(
                kind=kind,
                approval_id=approval_id,
                filename=filename,
                runtime_path=runtime_path,
                sha256=sha256,
                byte_length=byte_length,
                mime_type=mime_type,
            )
        )
    return tuple(assets)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(128 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _matches(path: Path, asset: ApprovedSelfImageAsset) -> bool:
    try:
        return (
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size == asset.byte_length
            and _sha256_file(path) == asset.sha256
        )
    except OSError:
        return False


def _target(home: Path, asset: ApprovedSelfImageAsset) -> Path:
    root = home.resolve()
    target = home.joinpath(*PurePosixPath(asset.runtime_path).parts)
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ApprovedSelfImageError(
            "approved self-image target escaped the runtime home"
        ) from exc
    if target.is_symlink():
        raise ApprovedSelfImageError("approved self-image target cannot be a symlink")
    return target


def install_approved_self_images(
    home: Path,
    *,
    opener: Callable[..., object] = urllib.request.urlopen,
    manifest_path: Path = MANIFEST_PATH,
) -> tuple[Path, ...]:
    """Install the exact twelve-image set transactionally into one runtime home."""

    home = Path(home).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    assets = load_approved_self_images(manifest_path)
    targets = tuple(_target(home, asset) for asset in assets)
    missing = [
        (asset, target)
        for asset, target in zip(assets, targets, strict=True)
        if not _matches(target, asset)
    ]
    if not missing:
        return targets

    with tempfile.TemporaryDirectory(
        prefix=".approved-self-images-",
        dir=home,
    ) as staging_name:
        staging_root = Path(staging_name)
        staged: list[tuple[Path, Path]] = []
        for asset, target in missing:
            request = urllib.request.Request(
                asset.url,
                headers={"User-Agent": "Alpecca-Approved-Self-Images/1"},
            )
            try:
                with opener(request, timeout=90) as response:  # type: ignore[misc]
                    body = response.read(asset.byte_length + 1)
                    extra = response.read(1)
            except Exception as exc:
                raise ApprovedSelfImageError(
                    f"approved self-image download failed for {asset.kind}"
                ) from exc
            if (
                len(body) != asset.byte_length
                or extra
                or hashlib.sha256(body).hexdigest() != asset.sha256
            ):
                raise ApprovedSelfImageError(
                    f"approved self-image integrity failed for {asset.kind}"
                )
            staging = staging_root / asset.filename
            with staging.open("wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            staged.append((staging, target))

        for staging, target in staged:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)

    if any(
        not _matches(target, asset)
        for asset, target in zip(assets, targets, strict=True)
    ):
        raise ApprovedSelfImageError("approved self-image post-install verification failed")
    return targets


__all__ = [
    "ApprovedSelfImageAsset",
    "ApprovedSelfImageError",
    "BASE_PATH",
    "DATASET",
    "EXPECTED_KINDS",
    "MANIFEST_PATH",
    "MAX_ASSET_BYTES",
    "REVISION",
    "SCHEMA",
    "SET_ID",
    "install_approved_self_images",
    "load_approved_self_images",
]
