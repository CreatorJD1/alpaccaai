"""Public endpoint discovery records for Alpecca's mobile launcher.

The document contains reachability metadata only. It never carries creator
credentials, cookies, memory, or authorization material.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urlparse


DISCOVERY_VERSION = 1
DEFAULT_QUICK_TTL_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class EndpointCandidate:
    url: str
    kind: str
    priority: int
    expires_at: int


def normalize_endpoint(value: str) -> str:
    """Return a credential-free HTTPS origin, or an empty string."""
    try:
        parsed = urlparse(str(value or "").strip())
    except Exception:
        return ""
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    if parsed.path not in {"", "/", "/house-hq"}:
        return ""
    return f"https://{parsed.netloc}".rstrip("/")


def build_endpoint_document(
    endpoints: Iterable[tuple[str, str, int]],
    *,
    now: int | None = None,
    quick_ttl_seconds: int = DEFAULT_QUICK_TTL_SECONDS,
) -> dict:
    """Build a bounded public discovery document in deterministic order."""
    timestamp = int(time.time() if now is None else now)
    rows: list[dict] = []
    seen: set[str] = set()
    for raw_url, raw_kind, raw_priority in endpoints:
        url = normalize_endpoint(raw_url)
        if not url or url in seen:
            continue
        seen.add(url)
        kind = "named" if raw_kind == "named" else "quick"
        rows.append({
            "url": url,
            "kind": kind,
            "priority": max(0, min(100, int(raw_priority))),
            "expiresAt": 0 if kind == "named" else timestamp + max(60, int(quick_ttl_seconds)),
        })
    rows.sort(key=lambda row: (row["priority"], row["kind"] != "named", row["url"]))
    return {
        "service": "alpecca-mobile-discovery",
        "version": DISCOVERY_VERSION,
        "updatedAt": timestamp,
        "endpoints": rows[:4],
    }


def read_endpoint_candidates(document: dict, *, now: int | None = None) -> list[EndpointCandidate]:
    """Validate and order a downloaded discovery document."""
    if document.get("service") != "alpecca-mobile-discovery" or document.get("version") != DISCOVERY_VERSION:
        return []
    timestamp = int(time.time() if now is None else now)
    candidates: list[EndpointCandidate] = []
    for row in document.get("endpoints", [])[:8]:
        if not isinstance(row, dict):
            continue
        url = normalize_endpoint(str(row.get("url", "")))
        kind = str(row.get("kind", ""))
        if not url or kind not in {"named", "quick"}:
            continue
        try:
            priority = max(0, min(100, int(row.get("priority", 100))))
            expires_at = int(row.get("expiresAt", 0))
        except (TypeError, ValueError):
            continue
        if kind == "quick" and expires_at <= timestamp:
            continue
        candidates.append(EndpointCandidate(url, kind, priority, expires_at))
    return sorted(candidates, key=lambda item: (item.priority, item.kind != "named", item.url))[:4]


HealthOpener = Callable[[str, float], tuple[int, bytes]]


def _open_health(url: str, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url.rstrip("/") + "/healthz",
        method="GET",
        headers={"User-Agent": "alpecca-mobile-publisher/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - validated HTTPS URL
        return int(response.status), response.read(256)


def probe_alpecca_endpoint(url: str, *, timeout: float = 8.0, opener: HealthOpener | None = None) -> bool:
    """Accept only an exact, public Alpecca health identity."""
    normalized = normalize_endpoint(url)
    if not normalized:
        return False
    try:
        status, body = (opener or _open_health)(normalized, timeout)
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return False
    return status == 200 and payload == {"service": "alpecca", "version": 1}
