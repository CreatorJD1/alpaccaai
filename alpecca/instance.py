"""Single-instance helpers for the local Alpecca server.

Cloudflare links and desktop windows should point at the same local mind. These
helpers let launchers detect an already-awake server before importing server.py,
because importing server.py constructs CoreMind.
"""
from __future__ import annotations

import urllib.error
import urllib.request


def http_status(url: str, timeout: float = 1.0) -> int | None:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "alpecca-instance"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:
        return None


def existing_server_url(port: int, host: str = "127.0.0.1",
                        token: str = "", timeout: float = 1.0) -> str | None:
    """Return the local URL if an Alpecca server is already answering."""
    base = f"http://{host}:{int(port)}"
    token_qs = f"?token={token}" if token else ""
    for route in (f"/system/doctor{token_qs}", f"/state{token_qs}", f"/house-hq{token_qs}"):
        status = http_status(base + route, timeout=timeout)
        if status and status < 500:
            return base
    return None
