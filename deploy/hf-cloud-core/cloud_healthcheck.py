"""Container health probe for cloud Core handoff and the voice sidecar."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Callable
import urllib.request


MAX_HEALTH_BYTES = 16 * 1024
PROMOTION_HEALTH_GRACE_SECONDS = 300.0


def _health_json(url: str, *, opener=urllib.request.urlopen) -> dict:
    with opener(url, timeout=2.0) as response:
        body = response.read(MAX_HEALTH_BYTES + 1)
    if len(body) > MAX_HEALTH_BYTES:
        raise ValueError("health response exceeded limit")
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("health response is not an object")
    return value


def promotion_grace_is_fresh(
    marker: Path,
    *,
    now: float | None = None,
) -> bool:
    try:
        started = float(marker.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    current = time.time() if now is None else float(now)
    age = current - started
    return 0.0 <= age <= PROMOTION_HEALTH_GRACE_SECONDS


def voice_synthesis_ready(voice: dict) -> bool:
    """Require explicit successful synthesis evidence; missing fields fail closed."""

    return (
        voice.get("state") == "ready"
        and voice.get("modelLoaded") is True
        and voice.get("selfCheckPassed") is True
        and voice.get("selfCheckState") == "passed"
        and voice.get("synthesisReady") is True
    )


def healthy(
    *,
    opener: Callable = urllib.request.urlopen,
    now: float | None = None,
    environ: dict[str, str] | None = None,
) -> bool:
    values = os.environ if environ is None else environ
    voice_port = values.get("ALPECCA_CLOUD_VOICE_PORT", "7861")
    try:
        voice = _health_json(
            f"http://127.0.0.1:{int(voice_port)}/healthz",
            opener=opener,
        )
    except Exception:
        return False
    if not voice_synthesis_ready(voice):
        return False

    try:
        _health_json("http://127.0.0.1:7860/healthz", opener=opener)
        return True
    except Exception:
        marker = (
            Path(values.get("ALPECCA_CLOUD_RUNTIME_ROOT", "/tmp/alpecca-cloud-core"))
            / "promotion-health-grace"
        )
        return promotion_grace_is_fresh(marker, now=now)


def main() -> int:
    return 0 if healthy() else 1


if __name__ == "__main__":
    raise SystemExit(main())
