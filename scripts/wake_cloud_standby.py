"""Request Alpecca's health-only cloud standby to wake without promotion.

The Hugging Face Space remains a passive standby until the continuity authority
grants it a newer fence.  This helper only makes a bounded HTTPS health request
so a sleeping Space begins warming; it never launches a second CoreMind.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_STANDBY_URL = "https://creatorjd-alpecca-survival-core.hf.space"
_EXPECTED_SERVICES = {"alpecca", "alpecca-continuity-standby"}


def standby_health_url(raw_url: str | None = None) -> str:
    """Return the fixed health endpoint, rejecting accidental non-HTTPS input."""
    base = (raw_url or os.environ.get("ALPECCA_CLOUD_STANDBY_URL") or DEFAULT_STANDBY_URL).strip()
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("ALPECCA_CLOUD_STANDBY_URL must be an HTTPS origin")
    if parsed.query or parsed.fragment:
        raise ValueError("ALPECCA_CLOUD_STANDBY_URL must not contain a query or fragment")
    return urllib.parse.urlunsplit(("https", parsed.netloc, "/healthz", "", ""))


def probe_standby(url: str, *, timeout: float = 15.0) -> dict[str, object]:
    """Perform one credential-free probe and report only public health facts."""
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "alpecca-local-wake/1"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, timeout)) as response:
            raw = response.read(16_384)
            payload = json.loads(raw.decode("utf-8"))
            service = str(payload.get("service") or "") if isinstance(payload, dict) else ""
            return {
                "ok": 200 <= response.status < 300 and service in _EXPECTED_SERVICES,
                "status": response.status,
                "service": service or "unknown",
                "url": url,
            }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "service": "unknown", "url": url}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "status": type(exc).__name__, "service": "unknown", "url": url}


def main() -> int:
    try:
        url = standby_health_url()
    except ValueError as exc:
        print(f"[cloud] Standby wake skipped: {exc}", file=sys.stderr)
        return 2

    # A first request is the wake signal for a sleeping Space. Poll briefly so
    # the launcher log records whether it returned to health-only standby.
    deadline = time.monotonic() + 75.0
    result: dict[str, object] = {}
    while True:
        result = probe_standby(url)
        if result.get("ok") or time.monotonic() >= deadline:
            break
        time.sleep(5.0)

    print(json.dumps({"event": "cloud_standby_wake", **result}, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
