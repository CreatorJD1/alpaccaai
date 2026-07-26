"""Routing tests for the opt-in private HolyROG vision worker in vision.py.

These exercise the fourth acceleration behavior at the vision-router level:
the worker is off unless explicitly enabled, a successful worker call is
labelled with the truthful ``private-holyrog`` receipt (never ``local-only``),
and any worker failure falls back to verified-local vision without dropping the
image turn.
"""

from __future__ import annotations

import pytest

from alpecca import rog_worker_client
from alpecca import vision
from alpecca.rog_worker_client import RogWorkerError, VisionResult


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class _FakeClient:
    """Stands in for RogWorkerClient.from_environment()."""

    last_kwargs: dict = {}

    def __init__(self, *, result=None, error=None):
        self._result = result
        self._error = error

    @classmethod
    def make(cls, *, result=None, error=None):
        def _from_environment():
            return cls(result=result, error=error)

        return _from_environment

    def describe_vision(self, image_bytes, *, model=None, prompt=None):
        type(self).last_kwargs = {"model": model, "prompt": prompt, "bytes": image_bytes}
        if self._error is not None:
            raise self._error
        return self._result


def test_private_worker_is_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ALPECCA_VISION_PRIVATE_WORKER", raising=False)
    # If the worker were consulted, from_environment would blow up the test.
    monkeypatch.setattr(
        rog_worker_client.RogWorkerClient,
        "from_environment",
        staticmethod(lambda: (_ for _ in ()).throw(AssertionError("worker used"))),
    )
    monkeypatch.setattr(vision, "_describe_local", lambda image, prompt: "local text")
    result = vision.describe_image_result(PNG)
    assert result is not None
    assert result.processing_location == "local-only"
    assert result.backend == "local-ollama"
    assert result.cloud_egress == "denied"


def test_enabled_worker_success_is_labelled_private_holyrog(monkeypatch) -> None:
    monkeypatch.setenv("ALPECCA_VISION_PRIVATE_WORKER", "1")
    monkeypatch.setenv("ALPECCA_ROG_WORKER_VISION_MODEL", "qwen3-vl:4b")
    vision_result = VisionResult(
        request_id="request-vision-0001",
        model="qwen3-vl:4b",
        description="A Discord channel with one visible message.",
        elapsed_ms=1200,
    )
    monkeypatch.setattr(
        rog_worker_client.RogWorkerClient,
        "from_environment",
        staticmethod(_FakeClient.make(result=vision_result)),
    )
    # Local must not be consulted when the worker already saw the pixels.
    monkeypatch.setattr(
        vision,
        "_describe_local",
        lambda image, prompt: (_ for _ in ()).throw(AssertionError("local used")),
    )
    result = vision.describe_image_result(PNG)
    assert result is not None
    assert result.text == "A Discord channel with one visible message."
    assert result.processing_location == "private-holyrog"
    assert result.cloud_egress == "private-tailnet"
    assert result.backend == "private-holyrog:qwen3-vl:4b"
    assert _FakeClient.last_kwargs["model"] == "qwen3-vl:4b"


def test_enabled_worker_falls_back_to_local_when_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("ALPECCA_VISION_PRIVATE_WORKER", "1")
    monkeypatch.setenv("ALPECCA_ROG_WORKER_VISION_MODEL", "qwen3-vl:4b")
    monkeypatch.setattr(
        rog_worker_client.RogWorkerClient,
        "from_environment",
        staticmethod(_FakeClient.make(error=RogWorkerError("worker down"))),
    )
    monkeypatch.setattr(vision, "_describe_local", lambda image, prompt: "local fallback text")
    result = vision.describe_image_result(PNG)
    assert result is not None
    # The image turn is not dropped: it lands on verified-local vision.
    assert result.text == "local fallback text"
    assert result.processing_location == "local-only"
    assert result.cloud_egress == "denied"


def test_enabled_but_no_model_configured_stays_local(monkeypatch) -> None:
    monkeypatch.setenv("ALPECCA_VISION_PRIVATE_WORKER", "1")
    monkeypatch.delenv("ALPECCA_ROG_WORKER_VISION_MODEL", raising=False)
    monkeypatch.setattr(
        rog_worker_client.RogWorkerClient,
        "from_environment",
        staticmethod(lambda: (_ for _ in ()).throw(AssertionError("worker used"))),
    )
    monkeypatch.setattr(vision, "_describe_local", lambda image, prompt: "local text")
    result = vision.describe_image_result(PNG)
    assert result is not None
    assert result.processing_location == "local-only"


def test_worker_empty_description_falls_back_to_local(monkeypatch) -> None:
    monkeypatch.setenv("ALPECCA_VISION_PRIVATE_WORKER", "1")
    monkeypatch.setenv("ALPECCA_ROG_WORKER_VISION_MODEL", "qwen3-vl:4b")
    blank = VisionResult(
        request_id="request-vision-0002", model="qwen3-vl:4b", description="   ", elapsed_ms=5
    )
    monkeypatch.setattr(
        rog_worker_client.RogWorkerClient,
        "from_environment",
        staticmethod(_FakeClient.make(result=blank)),
    )
    monkeypatch.setattr(vision, "_describe_local", lambda image, prompt: "local text")
    result = vision.describe_image_result(PNG)
    assert result is not None
    assert result.processing_location == "local-only"
    assert result.text == "local text"
