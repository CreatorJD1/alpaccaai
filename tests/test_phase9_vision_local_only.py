"""Phase 9 regression coverage for the verified-local generic vision boundary."""
from __future__ import annotations

import sys
import types

import pytest

import config
from alpecca import introspection
from alpecca import vision


IMAGE_BYTES = b"private image bytes"
LOCAL_RESPONSE = (
    "An Alpecca portrait.\n"
    "SELF: yes\n"
    "VERDICT: yes\n"
    "WHY: the locked appearance matches."
)
PUBLIC_WRAPPERS = (
    ("describe_image_result", lambda: vision.describe_image_result(IMAGE_BYTES)),
    ("describe_image", lambda: vision.describe_image(IMAGE_BYTES)),
    (
        "describe_and_recognize",
        lambda: vision.describe_and_recognize(IMAGE_BYTES),
    ),
    (
        "describe_and_recognize_result",
        lambda: vision.describe_and_recognize_result(IMAGE_BYTES),
    ),
    ("recognize_self", lambda: vision.recognize_self(IMAGE_BYTES)),
)


def _forbid_cloud_helpers(monkeypatch) -> None:
    def reject_cloud(*_args, **_kwargs):
        raise AssertionError("generic vision must not call a cloud provider")

    monkeypatch.setattr(vision, "_describe_ollama_cloud", reject_cloud)
    monkeypatch.setattr(vision, "_describe_zerogpu", reject_cloud)


@pytest.mark.parametrize(
    "backend",
    ("auto", "ollama-cloud", "zerogpu", "cloud", "local"),
)
def test_describe_image_result_is_local_only_for_every_configured_backend(
    monkeypatch,
    backend: str,
):
    local_calls: list[tuple[bytes, str]] = []
    monkeypatch.setattr(config, "VISION_BACKEND", backend)
    _forbid_cloud_helpers(monkeypatch)
    monkeypatch.setattr(
        vision,
        "_describe_local",
        lambda image, prompt: local_calls.append((image, prompt)) or "local view",
    )

    result = vision.describe_image_result(IMAGE_BYTES)

    assert local_calls == [(IMAGE_BYTES, vision._DESCRIBE_PROMPT)]
    assert result == vision.VisionDescription(
        text="local view",
        backend="local-ollama",
        processing_location="local-only",
        cloud_egress="denied",
    )


@pytest.mark.parametrize(
    ("wrapper_name", "invoke"),
    PUBLIC_WRAPPERS,
)
def test_public_generic_wrappers_never_call_cloud_helpers_when_flags_are_omitted(
    monkeypatch,
    wrapper_name: str,
    invoke,
):
    local_calls: list[tuple[bytes, str]] = []
    monkeypatch.setattr(config, "VISION_BACKEND", "ollama-cloud")
    monkeypatch.setattr(introspection, "self_appearance", lambda: "locked look")
    _forbid_cloud_helpers(monkeypatch)
    monkeypatch.setattr(
        vision,
        "_describe_local",
        lambda image, prompt: local_calls.append((image, prompt)) or LOCAL_RESPONSE,
    )

    result = invoke()

    assert result is not None, wrapper_name
    assert len(local_calls) == 1, wrapper_name
    assert local_calls[0][0] == IMAGE_BYTES
    if isinstance(result, vision.VisionDescription):
        assert result.backend == "local-ollama"
        assert result.processing_location == "local-only"
        assert result.cloud_egress == "denied"
    if wrapper_name == "recognize_self":
        assert result == {
            "is_self": True,
            "verdict": "yes",
            "why": "the locked appearance matches.",
        }


@pytest.mark.parametrize(("wrapper_name", "invoke"), PUBLIC_WRAPPERS)
def test_public_generic_wrappers_fail_closed_when_local_vision_is_unavailable(
    monkeypatch,
    wrapper_name: str,
    invoke,
):
    monkeypatch.setattr(config, "VISION_BACKEND", "auto")
    monkeypatch.setattr(introspection, "self_appearance", lambda: "locked look")
    _forbid_cloud_helpers(monkeypatch)
    monkeypatch.setattr(vision, "_describe_local", lambda *_args: None)

    assert invoke() is None, wrapper_name


def test_screen_and_face_ambient_glimpses_never_call_cloud_helpers(monkeypatch):
    class FakeScreenshot:
        thumbnail_size = None

        def thumbnail(self, size) -> None:
            self.thumbnail_size = size

        def save(self, buffer, *, format: str, quality: int) -> None:
            assert format == "JPEG"
            assert quality == 80
            buffer.write(b"screen pixels")

    class FakeCapture:
        def read(self):
            return True, b"camera frame"

        def release(self) -> None:
            return None

    class FakeEncodedFrame:
        def tobytes(self) -> bytes:
            return b"camera pixels"

    screenshot = FakeScreenshot()
    image_grab = types.ModuleType("PIL.ImageGrab")
    image_grab.grab = lambda: screenshot
    pil = types.ModuleType("PIL")
    pil.ImageGrab = image_grab
    cv2 = types.ModuleType("cv2")
    cv2.VideoCapture = lambda _index: FakeCapture()
    cv2.imencode = lambda extension, frame: (
        True,
        FakeEncodedFrame(),
    )

    monkeypatch.setitem(sys.modules, "PIL", pil)
    monkeypatch.setitem(sys.modules, "PIL.ImageGrab", image_grab)
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setattr(config, "VISION_BACKEND", "ollama-cloud")
    _forbid_cloud_helpers(monkeypatch)

    local_calls: list[tuple[bytes, str]] = []

    def describe_local(image: bytes, prompt: str) -> str:
        local_calls.append((image, prompt))
        return "tired" if prompt == vision._FACE_PROMPT else "screen view"

    monkeypatch.setattr(vision, "_describe_local", describe_local)
    screen = object.__new__(vision.ScreenSight)
    screen.latest = ""
    face = object.__new__(vision.FaceSense)
    face.expression = ""
    face.weary = 0.0

    screen._glimpse()
    face._glimpse()

    assert screenshot.thumbnail_size == (1280, 1280)
    assert screen.latest == "screen view"
    assert face.expression == "tired"
    assert face.weary == 1.0
    assert local_calls == [
        (b"screen pixels", vision._SCREEN_PROMPT),
        (b"camera pixels", vision._FACE_PROMPT),
    ]
