"""Client for the HOLYROG XTTS-v2 voice server (scripts/run_holyrog_voice_server.py).

Her main machine calls this to synthesize speech in her cloned voice on the ROG
worker's GPU. It is fail-closed and health-gated: every error returns None so
tts.synth falls back to local Kokoro, and it stops probing a down server for a
cooldown window instead of stalling every turn. Only text is sent; a bounded WAV
comes back. Nothing here logs the text or the secret.
"""
from __future__ import annotations

import io
import os
import time
import wave
from threading import RLock
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

AUTH_HEADER = "X-Alpecca-Voice-Authorization"
_READ_CHUNK = 64 * 1024
_CREDENTIAL_TARGET = "Alpecca/Jason_HOLYROG/XTTSVoice"


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(os.environ.get(name, str(default)))))
    except (TypeError, ValueError):
        return default


def _credential_secret() -> str:
    """Read the local primary's dedicated voice credential, if configured."""
    if os.name != "nt":
        return ""
    try:
        import win32cred

        value = win32cred.CredRead(
            _CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0
        ).get("CredentialBlob", b"")
    except Exception:
        return ""
    if isinstance(value, bytes):
        for encoding in ("utf-8", "utf-16-le"):
            try:
                return value.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        return ""
    return value.strip() if isinstance(value, str) else ""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HolyrogVoiceClient:
    def __init__(self) -> None:
        self._lock = RLock()
        self._url = os.environ.get("ALPECCA_HOLYROG_VOICE_URL", "").strip().rstrip("/")
        self._secret = os.environ.get("ALPECCA_HOLYROG_VOICE_SECRET", "") or _credential_secret()
        self._timeout = _env_float("ALPECCA_HOLYROG_VOICE_TIMEOUT_SECONDS", 20.0, 1.0, 120.0)
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
        return bool(self._url and self._secret)

    def _post(self, path: str, payload: bytes | None, timeout: float):
        req = Request(
            f"{self._url}{path}",
            data=payload,
            method="POST" if payload is not None else "GET",
            headers={
                AUTH_HEADER: self._secret,
                **({"Content-Type": "application/json"} if payload is not None else {}),
            },
        )
        return self._opener.open(req, timeout=timeout)

    def available(self) -> bool:
        """Health-gated with a cooldown so a down server is not re-probed every turn."""
        if not self.enabled:
            return False
        now = time.monotonic()
        with self._lock:
            if now < self._down_until:
                return False
        try:
            with self._post("/health", None, self._health_timeout) as resp:
                ok = resp.status == 200
        except (URLError, OSError, ValueError):
            ok = False
        with self._lock:
            if ok:
                self._down_until = 0.0
                self._state = "ready"
            else:
                self._down_until = now + self._cooldown
                self._state = "unavailable"
        return ok

    def synthesize(self, text: str) -> "tuple[str, bytes] | None":
        text = (text or "").strip()
        if not text or not self.enabled:
            return None
        if not self.available():
            return None
        import json

        body = json.dumps({"text": text[:600]}).encode("utf-8")
        try:
            with self._post("/synth", body, self._timeout) as resp:
                if resp.status != 200:
                    self._arm_cooldown()
                    return None
                data = b""
                while len(data) <= self._max_bytes:
                    chunk = resp.read(_READ_CHUNK)
                    if not chunk:
                        break
                    data += chunk
        except (URLError, OSError, ValueError):
            self._arm_cooldown()
            return None
        # Only accept a real, structurally valid WAV.
        if not (1024 < len(data) <= self._max_bytes):
            self._arm_cooldown()
            return None
        try:
            with wave.open(io.BytesIO(data)) as reader:
                if reader.getnframes() < 1:
                    self._arm_cooldown()
                    return None
        except Exception:
            self._arm_cooldown()
            return None
        with self._lock:
            self._state = "ready"
        return ("audio/wav", data)

    def _arm_cooldown(self) -> None:
        with self._lock:
            self._down_until = time.monotonic() + self._cooldown
            self._state = "unavailable"

    def status(self) -> dict:
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
