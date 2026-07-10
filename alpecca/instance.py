"""Single-instance helpers for the local Alpecca server.

Cloudflare links and desktop windows should point at the same local mind. These
helpers let launchers detect an already-awake server before importing server.py,
because importing server.py constructs CoreMind.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request


HEALTHZ_PATH = "/healthz"
HEALTHZ_SERVICE = "alpecca"
HEALTHZ_VERSION = 1
MAX_HEALTHZ_BYTES = 512


def http_status(url: str, timeout: float = 1.0) -> int | None:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "alpecca-instance"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:
        return None


def _is_alpecca_healthz(url: str, timeout: float) -> bool:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "alpecca-instance"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            if int(resp.status) != 200 or resp.geturl() != url:
                return False
            raw = resp.read(MAX_HEALTHZ_BYTES + 1)
    except Exception:
        return False
    if not raw or len(raw) > MAX_HEALTHZ_BYTES:
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and set(payload) == {"service", "version"}
        and payload["service"] == HEALTHZ_SERVICE
        and type(payload["version"]) is int
        and payload["version"] == HEALTHZ_VERSION
    )


def existing_server_url(port: int, host: str = "127.0.0.1",
                        token: str = "", timeout: float = 1.0) -> str | None:
    """Return the local URL if an Alpecca server is already answering.

    ``token`` remains only for caller compatibility. Public identity and other
    credentials must never be placed in a probe URL.
    """
    del token
    base = f"http://{host}:{int(port)}"
    return base if _is_alpecca_healthz(base + HEALTHZ_PATH, timeout) else None
