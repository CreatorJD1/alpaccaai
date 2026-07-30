from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from alpecca import approved_self_images as approved


class _Response:
    def __init__(self, body: bytes):
        self._body = body
        self._offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


def _manifest() -> dict:
    return json.loads(approved.MANIFEST_PATH.read_text(encoding="utf-8"))


def _write_fake_manifest(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    value = _manifest()
    bodies: dict[str, bytes] = {}
    for index, asset in enumerate(value["assets"]):
        body = b"\x89PNG\r\n\x1a\n" + bytes([index]) * (31 + index)
        asset["byteLength"] = len(body)
        asset["sha256"] = hashlib.sha256(body).hexdigest()
        bodies[asset["filename"]] = body
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, bodies


def test_manifest_defines_the_exact_immutable_twelve_image_release() -> None:
    assets = approved.load_approved_self_images()

    assert tuple(asset.kind for asset in assets) == approved.EXPECTED_KINDS
    assert len(assets) == 12
    assert len({asset.approval_id for asset in assets}) == 12
    assert len({asset.runtime_path for asset in assets}) == 12
    assert len({asset.sha256 for asset in assets}) == 12
    assert all(asset.byte_length <= approved.MAX_ASSET_BYTES for asset in assets)
    assert all(asset.mime_type == "image/png" for asset in assets)
    assert all(
        asset.url.startswith(
            "https://huggingface.co/datasets/CREATORJD/alpecca-runtime-assets/"
            "resolve/approved-self-images-v1/"
        )
        for asset in assets
    )


def test_manifest_rejects_shape_order_path_and_duplicate_digest(tmp_path: Path) -> None:
    original = _manifest()
    variants = []

    bad_shape = copy.deepcopy(original)
    bad_shape["unexpected"] = True
    variants.append(bad_shape)

    bad_order = copy.deepcopy(original)
    bad_order["assets"][0], bad_order["assets"][1] = (
        bad_order["assets"][1],
        bad_order["assets"][0],
    )
    variants.append(bad_order)

    bad_path = copy.deepcopy(original)
    bad_path["assets"][0]["runtimePath"] = "../escape.png"
    variants.append(bad_path)

    duplicate = copy.deepcopy(original)
    duplicate["assets"][1]["sha256"] = duplicate["assets"][0]["sha256"]
    variants.append(duplicate)

    for index, value in enumerate(variants):
        path = tmp_path / f"bad-{index}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(approved.ApprovedSelfImageError):
            approved.load_approved_self_images(path)


def test_installer_promotes_all_twelve_only_after_every_download_validates(
    tmp_path: Path,
) -> None:
    manifest_path, bodies = _write_fake_manifest(tmp_path)
    calls: list[str] = []

    def opener(request, timeout):
        assert timeout == 90
        filename = request.full_url.rsplit("/", 1)[-1]
        calls.append(filename)
        return _Response(bodies[filename])

    home = tmp_path / "home"
    installed = approved.install_approved_self_images(
        home,
        opener=opener,
        manifest_path=manifest_path,
    )

    assert len(installed) == 12
    assert calls == list(bodies)
    assert all(path.is_file() for path in installed)

    calls.clear()
    assert approved.install_approved_self_images(
        home,
        opener=opener,
        manifest_path=manifest_path,
    ) == installed
    assert calls == []


def test_installer_rejects_one_changed_download_without_promoting_any_file(
    tmp_path: Path,
) -> None:
    manifest_path, bodies = _write_fake_manifest(tmp_path)
    bodies["sleeping.png"] += b"changed"

    def opener(request, timeout):
        assert timeout == 90
        return _Response(bodies[request.full_url.rsplit("/", 1)[-1]])

    home = tmp_path / "home"
    with pytest.raises(approved.ApprovedSelfImageError, match="integrity"):
        approved.install_approved_self_images(
            home,
            opener=opener,
            manifest_path=manifest_path,
        )

    assert not any(path.is_file() for path in home.rglob("*.png"))
