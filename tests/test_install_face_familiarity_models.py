from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from scripts import install_face_familiarity_models as installer


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _asset(content: bytes, *, filename: str = "face_detection_yunet_2023mar.onnx") -> dict[str, object]:
    revision = "f12e12798e8314f7c074a6656816c048dcc95b7a"
    return {
        "name": "test-yunet",
        "role": "face-detection",
        "filename": filename,
        "url": (
            "https://media.githubusercontent.com/media/opencv/opencv_zoo/"
            f"{revision}/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
        ),
        "revision": revision,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "license": "MIT",
        "license_url": (
            "https://github.com/opencv/opencv_zoo/blob/"
            f"{revision}/models/face_detection_yunet/README.md#license"
        ),
    }


def _manifest(asset: dict[str, object]) -> dict[str, object]:
    return {
        "schema": installer.SCHEMA,
        "evaluation_only": True,
        "enables_runtime": False,
        "assets": [asset],
    }


def test_committed_manifest_contains_exact_verified_assets() -> None:
    manifest = installer.load_manifest()

    assert manifest["evaluation_only"] is True
    assert manifest["enables_runtime"] is False
    assert [
        {
            key: asset[key]
            for key in (
                "name",
                "filename",
                "url",
                "revision",
                "bytes",
                "sha256",
                "license",
                "license_url",
            )
        }
        for asset in manifest["assets"]
    ] == [
        {
            "name": "yunet-2023mar",
            "filename": "face_detection_yunet_2023mar.onnx",
            "url": "https://media.githubusercontent.com/media/opencv/opencv_zoo/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
            "revision": "f12e12798e8314f7c074a6656816c048dcc95b7a",
            "bytes": 232589,
            "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
            "license": "MIT",
            "license_url": "https://github.com/opencv/opencv_zoo/blob/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/README.md#license",
        },
        {
            "name": "sface-2021dec",
            "filename": "face_recognition_sface_2021dec.onnx",
            "url": "https://media.githubusercontent.com/media/opencv/opencv_zoo/ba91a3b91d00d76e86540d4013f944bd6b514e39/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
            "revision": "ba91a3b91d00d76e86540d4013f944bd6b514e39",
            "bytes": 38696353,
            "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
            "license": "Apache-2.0",
            "license_url": "https://github.com/opencv/opencv_zoo/blob/ba91a3b91d00d76e86540d4013f944bd6b514e39/models/face_recognition_sface/README.md#license",
        },
    ]


def test_install_downloads_to_target_and_atomically_promotes(tmp_path: Path, monkeypatch) -> None:
    content = b"verified-model-bytes"
    manifest = _manifest(_asset(content))
    replacements: list[tuple[Path, Path]] = []
    original_replace = installer.os.replace

    def open_fake(_request: object, *, timeout: float) -> FakeResponse:
        assert timeout == 12.0
        return FakeResponse(content)

    def replace(source: object, destination: object) -> None:
        replacements.append((Path(source), Path(destination)))
        original_replace(source, destination)

    monkeypatch.setattr(installer.os, "replace", replace)
    result = installer.install_assets(manifest, tmp_path, opener=open_fake, timeout=12.0)
    target = tmp_path / "face_detection_yunet_2023mar.onnx"

    assert result == {"test-yunet": "installed"}
    assert target.read_bytes() == content
    assert replacements == [(replacements[0][0], target)]
    assert replacements[0][0].parent == tmp_path
    assert not list(tmp_path.glob("*.download"))


def test_hash_mismatch_removes_temp_and_does_not_promote(tmp_path: Path) -> None:
    expected = b"good"
    manifest = _manifest(_asset(expected))

    def open_fake(_request: object, *, timeout: float) -> FakeResponse:
        assert timeout > 0
        return FakeResponse(b"baad")

    with pytest.raises(installer.AssetVerificationError, match="sha256 mismatch"):
        installer.install_assets(manifest, tmp_path, opener=open_fake)

    assert not (tmp_path / "face_detection_yunet_2023mar.onnx").exists()
    assert list(tmp_path.iterdir()) == []


def test_verified_existing_asset_is_idempotent_and_skips_network(tmp_path: Path) -> None:
    content = b"already-present"
    asset = _asset(content)
    target = tmp_path / str(asset["filename"])
    target.write_bytes(content)

    def unexpected_network(*_args: object, **_kwargs: object) -> FakeResponse:
        raise AssertionError("network must not be used for an already verified asset")

    result = installer.install_assets(_manifest(asset), tmp_path, opener=unexpected_network)

    assert result == {"test-yunet": "already verified"}
    assert target.read_bytes() == content


def test_out_of_root_manifest_path_is_rejected_before_network(tmp_path: Path) -> None:
    asset = _asset(b"model", filename="../escaped.onnx")

    def unexpected_network(*_args: object, **_kwargs: object) -> FakeResponse:
        raise AssertionError("unsafe paths must be rejected before network access")

    with pytest.raises(installer.UnsafePathError, match="directly under the target root"):
        installer.install_assets(_manifest(asset), tmp_path, opener=unexpected_network)

    assert not (tmp_path.parent / "escaped.onnx").exists()


def test_symlink_target_root_is_rejected_before_network(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "linked-root"
    root.mkdir()
    original_is_link = installer._is_link

    def is_link(path: Path) -> bool:
        return Path(path) == root or original_is_link(Path(path))

    monkeypatch.setattr(installer, "_is_link", is_link)

    def unexpected_network(*_args: object, **_kwargs: object) -> FakeResponse:
        raise AssertionError("linked roots must be rejected before network access")

    with pytest.raises(installer.UnsafePathError, match="symlink or junction"):
        installer.install_assets(_manifest(_asset(b"model")), root, opener=unexpected_network)


def test_default_target_uses_local_app_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert installer.default_target_root() == tmp_path / "Alpecca" / "models" / "face"


def test_manifest_file_rejects_path_escape(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest(_asset(b"model", filename="..\\escape.onnx"))), encoding="utf-8")

    with pytest.raises(installer.UnsafePathError):
        installer.load_manifest(path)
