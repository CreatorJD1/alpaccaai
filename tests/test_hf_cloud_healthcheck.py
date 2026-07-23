from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import urllib.error


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "deploy" / "hf-cloud-core" / "cloud_healthcheck.py"
SPEC = importlib.util.spec_from_file_location("alpecca_cloud_healthcheck", PATH)
assert SPEC and SPEC.loader
healthcheck = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(healthcheck)


class Response:
    def __init__(self, payload: dict) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


def opener(*, public: bool, voice: bool):
    def open_url(url: str, timeout: float):
        assert timeout == 2.0
        if url.endswith(":7861/healthz"):
            if not voice:
                raise urllib.error.URLError("voice unavailable")
            return Response({
                "state": "ready",
                "modelLoaded": True,
                "selfCheckPassed": True,
                "selfCheckState": "passed",
                "synthesisReady": True,
            })
        if url.endswith(":7860/healthz"):
            if not public:
                raise urllib.error.URLError("handoff in progress")
            return Response({"status": "ok"})
        raise AssertionError(f"unexpected health URL: {url}")

    return open_url


def test_health_requires_voice_even_during_promotion_grace(tmp_path: Path) -> None:
    marker = tmp_path / "promotion-health-grace"
    marker.write_text("100.0", encoding="ascii")
    environment = {"ALPECCA_CLOUD_RUNTIME_ROOT": str(tmp_path)}

    assert not healthcheck.healthy(
        opener=opener(public=False, voice=False),
        now=120.0,
        environ=environment,
    )


def test_health_rejects_ready_label_without_synthesis_evidence(tmp_path: Path) -> None:
    environment = {"ALPECCA_CLOUD_RUNTIME_ROOT": str(tmp_path)}

    def incomplete_voice(url: str, timeout: float):
        assert timeout == 2.0
        if url.endswith(":7861/healthz"):
            return Response({"state": "ready"})
        return Response({"status": "ok"})

    assert not healthcheck.healthy(
        opener=incomplete_voice,
        now=1_000.0,
        environ=environment,
    )


def test_health_accepts_public_service_or_fresh_handoff_marker(tmp_path: Path) -> None:
    environment = {"ALPECCA_CLOUD_RUNTIME_ROOT": str(tmp_path)}
    assert healthcheck.healthy(
        opener=opener(public=True, voice=True),
        now=1_000.0,
        environ=environment,
    )

    marker = tmp_path / "promotion-health-grace"
    marker.write_text("100.0", encoding="ascii")
    assert healthcheck.healthy(
        opener=opener(public=False, voice=True),
        now=200.0,
        environ=environment,
    )


def test_health_rejects_missing_stale_or_future_handoff_marker(tmp_path: Path) -> None:
    environment = {"ALPECCA_CLOUD_RUNTIME_ROOT": str(tmp_path)}
    unavailable = opener(public=False, voice=True)
    assert not healthcheck.healthy(opener=unavailable, now=200.0, environ=environment)

    marker = tmp_path / "promotion-health-grace"
    marker.write_text("1.0", encoding="ascii")
    assert not healthcheck.healthy(opener=unavailable, now=500.0, environ=environment)

    marker.write_text("201.0", encoding="ascii")
    assert not healthcheck.healthy(opener=unavailable, now=200.0, environ=environment)
