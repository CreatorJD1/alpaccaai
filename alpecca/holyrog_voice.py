"""Authenticated client for the dedicated HOLYROG XTTS-v2 worker.

The authoritative Alpecca process sends only bounded text to Jason_HOLYROG and
receives a bounded WAV. Every failure returns ``None`` so the existing local
voice route remains available. Secrets and spoken text are never logged.
"""
from __future__ import annotations

import io
import os
import time
import wave
from threading import RLock
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


AUTH_HEADER = "X-Alpecca-Voice-Authorization"
_CREDENTIAL_TARGET = "Alpecca/Jason_HOLYROG/XTTSVoice"
_READ_CHUNK = 64 * 1024
_MIN_SECRET_BYTES = 32
_ALLOWED_ENDPOINTS = {
    ("jason-holyrog.tailda0108.ts.net", 8790),
    ("100.92.250.12", 8790),
}


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(os.environ.get(name, str(default)))))
    except (TypeError, ValueError):
        return default


def _validated_url(value: str) -> str:
    """Accept only the assigned private tailnet endpoint.

    Redirects and environment proxies are disabled separately. This exact-host
    check prevents a bad environment value from sending the voice credential or
    private speech to an unrelated destination.
    """
    candidate = (value or "").strip().rstrip("/")
    if not candidate:
        return ""
    try:
        parsed = urlsplit(candidate)
        endpoint = ((parsed.hostname or "").casefold(), parsed.port)
    except ValueError:
        return ""
    if (
        parsed.scheme.casefold() != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or endpoint not in _ALLOWED_ENDPOINTS
    ):
        return ""
    return f"http://{endpoint[0]}:{endpoint[1]}"


def _credential_secret() -> str:
    """Read the primary host's dedicated voice credential, if configured."""
    if os.name != "nt":
        return ""
    try:
        from alpecca.auth import _read_windows_credential

        return (_read_windows_credential(_CREDENTIAL_TARGET) or "").strip()
    except Exception:
        return ""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HolyrogVoiceClient:
    def __init__(self) -> None:
        self._lock = RLock()
        self._url = _validated_url(os.environ.get("ALPECCA_HOLYROG_VOICE_URL", ""))
        self._secret = (
            os.environ.get("ALPECCA_HOLYROG_VOICE_SECRET", "")
            or _credential_secret()
        ).strip()
        self._timeout = _env_float(
            "ALPECCA_HOLYROG_VOICE_TIMEOUT_SECONDS", 20.0, 1.0, 120.0
        )
        self._health_timeout = _env_float(
            "ALPECCA_HOLYROG_VOICE_HEALTH_TIMEOUT_SECONDS", 2.0, 0.3, 10.0
        )
        self._cooldown = _env_float(
            "ALPECCA_HOLYROG_VOICE_FAILURE_COOLDOWN_SECONDS", 60.0, 5.0, 300.0
        )
        self._max_bytes = 32 * 1024 * 1024
        self._down_until = 0.0
        self._state = "unconfigured" if not self.enabled else "unverified"
        self._opener = build_opener(_NoRedirect(), ProxyHandler({}))

    @property
    def enabled(self) -> bool:
        return bool(
            self._url
            and len(self._secret.encode("utf-8", errors="ignore")) >= _MIN_SECRET_BYTES
        )

    def _request(self, path: str, payload: bytes | None, timeout: float):
        request = Request(
            f"{self._url}{path}",
            data=payload,
            method="POST" if payload is not None else "GET",
            headers={
                AUTH_HEADER: self._secret,
                **({"Content-Type": "application/json"} if payload is not None else {}),
            },
        )
        return self._opener.open(request, timeout=timeout)

    def available(self) -> bool:
        """Probe health with a cooldown so an outage cannot stall every line."""
        if not self.enabled:
            return False
        now = time.monotonic()
        with self._lock:
            if now < self._down_until:
                return False
        try:
            with self._request("/health", None, self._health_timeout) as response:
                ready = response.status == 200
        except (URLError, OSError, ValueError):
            ready = False
        with self._lock:
            if ready:
                self._down_until = 0.0
                self._state = "ready"
            else:
                self._down_until = now + self._cooldown
                self._state = "unavailable"
        return ready

    def synthesize(self, text: str) -> tuple[str, bytes] | None:
        text = (text or "").strip()
        if not text or not self.enabled or not self.available():
            return None

        import json

        payload = json.dumps({"text": text[:600]}).encode("utf-8")
        try:
            with self._request("/synth", payload, self._timeout) as response:
                if response.status != 200:
                    self._arm_cooldown()
                    return None
                chunks: list[bytes] = []
                size = 0
                while size <= self._max_bytes:
                    chunk = response.read(_READ_CHUNK)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                data = b"".join(chunks)
        except (URLError, OSError, ValueError):
            self._arm_cooldown()
            return None

        if not (1024 < len(data) <= self._max_bytes):
            self._arm_cooldown()
            return None
        try:
            with wave.open(io.BytesIO(data)) as reader:
                if reader.getnframes() < 1:
                    self._arm_cooldown()
                    return None
        except (OSError, EOFError, wave.Error):
            self._arm_cooldown()
            return None
        with self._lock:
            self._state = "ready"
        return ("audio/wav", data)

    def _arm_cooldown(self) -> None:
        with self._lock:
            self._down_until = time.monotonic() + self._cooldown
            self._state = "unavailable"

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "engine": "holyrog-xtts",
                "configured": self.enabled,
                "state": self._state,
                "cooldown_active": time.monotonic() < self._down_until,
            }


_client: HolyrogVoiceClient | None = None


def client() -> HolyrogVoiceClient:
    global _client
    if _client is None:
        _client = HolyrogVoiceClient()
    return _client
