"""Authenticated, bounded HTTP client for a configured cloud voice endpoint.

The client logs nothing, follows no redirects, and exposes no submitted text or
authorization material through results or status snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
import re
from threading import RLock
import time
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)


AUTHORIZATION_HEADER = "X-Alpecca-Authorization"
ENDPOINT_ENV = "ALPECCA_CLOUD_TTS_ENDPOINT"
AUTHORIZATION_ENV = "ALPECCA_CLOUD_TTS_AUTHORIZATION"
TIMEOUT_ENV = "ALPECCA_CLOUD_TTS_TIMEOUT_SECONDS"
MAX_RESPONSE_BYTES_ENV = "ALPECCA_CLOUD_TTS_MAX_RESPONSE_BYTES"
MAX_TEXT_BYTES_ENV = "ALPECCA_CLOUD_TTS_MAX_TEXT_BYTES"
TTS_PATH = "/voice/tts"

DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_TEXT_BYTES = 16 * 1024
MAX_TIMEOUT_SECONDS = 60.0
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_TEXT_BYTES = 64 * 1024
READ_CHUNK_BYTES = 64 * 1024

ALLOWED_CONTENT_TYPES = frozenset({
    "audio/flac",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "audio/x-wav",
})

CloudTTSResult = tuple[str, bytes, dict[str, object]]
OpenCallable = Callable[..., object]


class CloudTTSConfigError(ValueError):
    """Cloud TTS configuration was rejected before network access."""


@dataclass(frozen=True, slots=True)
class CloudTTSConfig:
    endpoint: str = field(repr=False)
    authorization: str = field(repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_text_bytes: int = DEFAULT_MAX_TEXT_BYTES
    host: str = field(init=False, repr=False)
    path: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        endpoint, host, path = _validated_endpoint(self.endpoint)
        authorization = _authorization(self.authorization)
        timeout = _bounded_float(
            self.timeout_seconds,
            "timeout_seconds",
            minimum=0.1,
            maximum=MAX_TIMEOUT_SECONDS,
        )
        response_limit = _bounded_int(
            self.max_response_bytes,
            "max_response_bytes",
            maximum=MAX_RESPONSE_BYTES,
        )
        text_limit = _bounded_int(
            self.max_text_bytes,
            "max_text_bytes",
            maximum=MAX_TEXT_BYTES,
        )
        object.__setattr__(self, "endpoint", endpoint)
        object.__setattr__(self, "authorization", authorization)
        object.__setattr__(self, "timeout_seconds", timeout)
        object.__setattr__(self, "max_response_bytes", response_limit)
        object.__setattr__(self, "max_text_bytes", text_limit)
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "path", path)

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> "CloudTTSConfig":
        values = os.environ if env is None else env
        endpoint = values.get(ENDPOINT_ENV, "")
        authorization = values.get(AUTHORIZATION_ENV, "")
        if not endpoint or not authorization:
            raise CloudTTSConfigError("endpoint and authorization are required")
        return cls(
            endpoint=endpoint,
            authorization=authorization,
            timeout_seconds=_env_float(
                values,
                TIMEOUT_ENV,
                DEFAULT_TIMEOUT_SECONDS,
            ),
            max_response_bytes=_env_int(
                values,
                MAX_RESPONSE_BYTES_ENV,
                DEFAULT_MAX_RESPONSE_BYTES,
            ),
            max_text_bytes=_env_int(
                values,
                MAX_TEXT_BYTES_ENV,
                DEFAULT_MAX_TEXT_BYTES,
            ),
        )


@dataclass(frozen=True, slots=True)
class CloudTTSStatus:
    configured: bool
    state: str
    reason: str
    calls: int
    network_attempts: int
    successes: int
    failures: int
    last_http_status: int | None = None
    last_content_type: str | None = None
    last_response_bytes: int | None = None
    last_elapsed_ms: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            "state": self.state,
            "reason": self.reason,
            "calls": self.calls,
            "network_attempts": self.network_attempts,
            "successes": self.successes,
            "failures": self.failures,
            "last_http_status": self.last_http_status,
            "last_content_type": self.last_content_type,
            "last_response_bytes": self.last_response_bytes,
            "last_elapsed_ms": self.last_elapsed_ms,
        }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CloudTTSClient:
    """Synchronous fail-closed client for one exact configured target."""

    def __init__(
        self,
        config: CloudTTSConfig | None,
        *,
        opener: OpenCallable | object | None = None,
        clock: Callable[[], float] = time.monotonic,
        configuration_reason: str | None = None,
    ) -> None:
        if config is not None and not isinstance(config, CloudTTSConfig):
            raise TypeError("config must be CloudTTSConfig or None")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._config = config
        self._configuration_reason = configuration_reason or "not_configured"
        self._clock = clock
        self._opener = opener or build_opener(ProxyHandler({}), _NoRedirect()).open
        if not callable(self._opener) and not callable(
            getattr(self._opener, "open", None)
        ):
            raise TypeError("opener must be callable or expose open()")
        self._calls = 0
        self._network_attempts = 0
        self._successes = 0
        self._failures = 0
        configured = config is not None
        self._status = CloudTTSStatus(
            configured=configured,
            state="unverified" if configured else "unavailable",
            reason=(
                "configured_not_called"
                if configured
                else configuration_reason or "not_configured"
            ),
            calls=0,
            network_attempts=0,
            successes=0,
            failures=0,
        )
        self._lock = RLock()

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        opener: OpenCallable | object | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> "CloudTTSClient":
        try:
            config = CloudTTSConfig.from_env(env)
        except CloudTTSConfigError:
            values = os.environ if env is None else env
            supplied = bool(
                values.get(ENDPOINT_ENV) or values.get(AUTHORIZATION_ENV)
            )
            return cls(
                None,
                opener=opener,
                clock=clock,
                configuration_reason=(
                    "configuration_invalid" if supplied else "not_configured"
                ),
            )
        return cls(config, opener=opener, clock=clock)

    def status(self) -> CloudTTSStatus:
        with self._lock:
            return self._status

    def synthesize(self, text: str) -> CloudTTSResult | None:
        with self._lock:
            self._calls += 1
        config = self._config
        if config is None:
            return self._fail(self._configuration_reason)
        payload = _request_payload(text, config.max_text_bytes)
        if payload is None:
            return self._fail("invalid_text")
        request = Request(
            config.endpoint,
            data=payload,
            headers={
                AUTHORIZATION_HEADER: config.authorization,
                "Accept": ", ".join(sorted(ALLOWED_CONTENT_TYPES)),
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        if not _request_matches_config(request, config):
            return self._fail("target_mismatch")

        started = self._safe_clock()
        with self._lock:
            self._network_attempts += 1
        try:
            response = self._open(request, timeout=config.timeout_seconds)
            with response as opened:
                if not _response_matches_config(opened, config):
                    return self._fail(
                        "target_mismatch",
                        elapsed_ms=self._elapsed_ms(started),
                    )
                http_status = _response_status(opened)
                if http_status != 200:
                    return self._fail(
                        "http_status",
                        http_status=http_status,
                        elapsed_ms=self._elapsed_ms(started),
                    )
                mime = _response_mime(opened)
                if mime not in ALLOWED_CONTENT_TYPES:
                    return self._fail(
                        "content_type_not_allowed",
                        http_status=http_status,
                        mime=mime,
                        elapsed_ms=self._elapsed_ms(started),
                    )
                declared = _content_length(opened)
                if declared is None:
                    pass
                elif declared < 0:
                    return self._fail(
                        "invalid_content_length",
                        http_status=http_status,
                        mime=mime,
                        elapsed_ms=self._elapsed_ms(started),
                    )
                elif declared > config.max_response_bytes:
                    return self._fail(
                        "response_too_large",
                        http_status=http_status,
                        mime=mime,
                        response_bytes=declared,
                        elapsed_ms=self._elapsed_ms(started),
                    )
                body, read_reason, elapsed_ms = self._read_response(
                    opened,
                    config,
                    started=started,
                    declared=declared,
                )
                if read_reason is not None:
                    return self._fail(
                        read_reason,
                        http_status=http_status,
                        mime=mime,
                        response_bytes=len(body),
                        elapsed_ms=elapsed_ms,
                    )
                if declared is not None and len(body) != declared:
                    return self._fail(
                        "content_length_mismatch",
                        http_status=http_status,
                        mime=mime,
                        response_bytes=len(body),
                        elapsed_ms=self._elapsed_ms(started),
                    )
        except HTTPError as exc:
            return self._fail(
                "http_status",
                http_status=exc.code,
                elapsed_ms=self._elapsed_ms(started),
            )
        except Exception:
            return self._fail(
                "transport_error",
                elapsed_ms=self._elapsed_ms(started),
            )

        if not body:
            return self._fail(
                "empty_response",
                http_status=200,
                mime=mime,
                response_bytes=0,
                elapsed_ms=elapsed_ms,
            )
        if len(body) > config.max_response_bytes:
            return self._fail(
                "response_too_large",
                http_status=200,
                mime=mime,
                response_bytes=len(body),
                elapsed_ms=elapsed_ms,
            )
        metadata: dict[str, object] = {
            "http_status": 200,
            "content_type": mime,
            "byte_count": len(body),
            "elapsed_ms": elapsed_ms,
        }
        request_id = _safe_response_header(response, "X-Alpecca-Request-Id")
        if request_id is not None:
            metadata["request_id"] = request_id
        self._succeed(mime, len(body), elapsed_ms)
        return mime, body, metadata

    def _open(self, request: Request, *, timeout: float):
        opener = self._opener
        if callable(opener):
            return opener(request, timeout=timeout)
        return opener.open(request, timeout=timeout)

    def _read_response(
        self,
        response: object,
        config: CloudTTSConfig,
        *,
        started: float,
        declared: int | None,
    ) -> tuple[bytes, str | None, int]:
        limit = config.max_response_bytes + 1
        target = limit if declared is None else min(limit, declared + 1)
        chunks: list[bytes] = []
        total = 0
        elapsed_ms = 0

        while total < target:
            remaining, elapsed_ms = self._remaining_budget(
                started,
                config.timeout_seconds,
            )
            if remaining <= 0:
                return b"".join(chunks), "time_limit_exceeded", elapsed_ms
            _set_response_socket_timeout(response, remaining)
            if declared is not None and total < declared:
                unread = declared - total
            else:
                unread = target - total
            read_size = min(READ_CHUNK_BYTES, unread)
            reader = getattr(response, "read1", None)
            if not callable(reader):
                reader = response.read
            try:
                chunk = reader(read_size)
            except TimeoutError:
                _, elapsed_ms = self._remaining_budget(
                    started,
                    config.timeout_seconds,
                )
                return b"".join(chunks), "time_limit_exceeded", elapsed_ms
            if not isinstance(chunk, bytes):
                return b"".join(chunks), "response_read_failed", elapsed_ms
            chunks.append(chunk)
            total += len(chunk)
            remaining, elapsed_ms = self._remaining_budget(
                started,
                config.timeout_seconds,
            )
            if remaining <= 0:
                return b"".join(chunks), "time_limit_exceeded", elapsed_ms
            if not chunk:
                break
            if total > config.max_response_bytes:
                break
        return b"".join(chunks), None, elapsed_ms

    def _remaining_budget(
        self,
        started: float,
        timeout_seconds: float,
    ) -> tuple[float, int]:
        elapsed = max(0.0, self._safe_clock() - started)
        elapsed_ms = min(round(elapsed * 1000), 86_400_000)
        return timeout_seconds - elapsed, elapsed_ms

    def _safe_clock(self) -> float:
        try:
            value = float(self._clock())
        except (TypeError, ValueError, OverflowError):
            return 0.0
        return value if math.isfinite(value) else 0.0

    def _elapsed_ms(self, started: float) -> int:
        elapsed = max(0.0, self._safe_clock() - started)
        return min(round(elapsed * 1000), 86_400_000)

    def _fail(
        self,
        reason: str,
        *,
        http_status: int | None = None,
        mime: str | None = None,
        response_bytes: int | None = None,
        elapsed_ms: int | None = None,
    ) -> None:
        with self._lock:
            self._failures += 1
            self._status = self._snapshot_status(
                state="degraded" if self._config is not None else "unavailable",
                reason=reason,
                http_status=http_status,
                mime=mime,
                response_bytes=response_bytes,
                elapsed_ms=elapsed_ms,
            )
        return None

    def _succeed(self, mime: str, byte_count: int, elapsed_ms: int) -> None:
        with self._lock:
            self._successes += 1
            self._status = self._snapshot_status(
                state="ready",
                reason="ok",
                http_status=200,
                mime=mime,
                response_bytes=byte_count,
                elapsed_ms=elapsed_ms,
            )

    def _snapshot_status(
        self,
        *,
        state: str,
        reason: str,
        http_status: int | None,
        mime: str | None,
        response_bytes: int | None,
        elapsed_ms: int | None,
    ) -> CloudTTSStatus:
        config = self._config
        return CloudTTSStatus(
            configured=config is not None,
            state=state,
            reason=reason,
            calls=self._calls,
            network_attempts=self._network_attempts,
            successes=self._successes,
            failures=self._failures,
            last_http_status=http_status,
            last_content_type=mime,
            last_response_bytes=response_bytes,
            last_elapsed_ms=elapsed_ms,
        )


def _validated_endpoint(value: object) -> tuple[str, str, str]:
    if not isinstance(value, str) or not value.strip():
        raise CloudTTSConfigError("endpoint must be non-empty text")
    endpoint = value.strip()
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        raise CloudTTSConfigError("endpoint is invalid") from None
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or not host
        or host.endswith(".")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != TTS_PATH
        or parsed.query
        or parsed.fragment
    ):
        raise CloudTTSConfigError(
            "endpoint must be an exact HTTPS /voice/tts target"
        )
    try:
        host.encode("ascii")
    except UnicodeEncodeError:
        raise CloudTTSConfigError("endpoint host must be ASCII") from None
    if not re.fullmatch(r"[a-z0-9.:-]+", host) or port == 0:
        raise CloudTTSConfigError("endpoint host or port is invalid")
    return endpoint, host, parsed.path


def _authorization(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CloudTTSConfigError("authorization must be non-empty bounded text")
    if len(value) > 4096 or any(
        not 0x20 <= ord(character) <= 0x7E for character in value
    ):
        raise CloudTTSConfigError("authorization must be non-empty bounded text")
    return value


def _request_payload(text: object, maximum: int) -> bytes | None:
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        encoded_text = text.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if len(encoded_text) > maximum:
        return None
    try:
        payload = json.dumps(
            {"text": text},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        return None
    return payload if len(payload) <= maximum + 32 else None


def _request_matches_config(request: Request, config: CloudTTSConfig) -> bool:
    parsed = urlsplit(request.full_url)
    return (
        request.get_method() == "POST"
        and parsed.scheme == "https"
        and (parsed.hostname or "").lower() == config.host
        and parsed.path == config.path == TTS_PATH
        and not parsed.query
        and not parsed.fragment
        and request.full_url == config.endpoint
    )


def _response_status(response: object) -> int | None:
    value = getattr(response, "status", None)
    if value is None and callable(getattr(response, "getcode", None)):
        value = response.getcode()
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _response_matches_config(
    response: object,
    config: CloudTTSConfig,
) -> bool:
    geturl = getattr(response, "geturl", None)
    if not callable(geturl):
        return True
    try:
        final_url = geturl()
    except Exception:
        return False
    if not isinstance(final_url, str):
        return False
    parsed = urlsplit(final_url)
    return (
        final_url == config.endpoint
        and parsed.scheme == "https"
        and (parsed.hostname or "").lower() == config.host
        and parsed.path == config.path
        and not parsed.query
        and not parsed.fragment
    )


def _response_header(response: object, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    value = headers.get(name) if hasattr(headers, "get") else None
    if value is None and callable(getattr(response, "getheader", None)):
        value = response.getheader(name)
    return value if isinstance(value, str) else None


def _response_mime(response: object) -> str | None:
    value = _response_header(response, "Content-Type")
    if value is None:
        return None
    mime = value.split(";", 1)[0].strip().lower()
    return mime or None


def _content_length(response: object) -> int | None:
    value = _response_header(response, "Content-Length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return -1


def _safe_response_header(response: object, name: str) -> str | None:
    value = _response_header(response, name)
    if value is None or len(value) > 128:
        return None
    return value if re.fullmatch(r"[A-Za-z0-9._:-]+", value) else None


def _set_response_socket_timeout(response: object, remaining: float) -> bool:
    current = response
    for attribute in ("fp", "raw", "_sock"):
        current = getattr(current, attribute, None)
        if current is None:
            return False
    setter = getattr(current, "settimeout", None)
    if not callable(setter):
        return False
    try:
        setter(remaining)
    except (OSError, TypeError, ValueError):
        return False
    return True


def _bounded_float(
    value: object,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool):
        raise CloudTTSConfigError(f"{name} is outside its supported bound")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise CloudTTSConfigError(f"{name} is outside its supported bound") from None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise CloudTTSConfigError(f"{name} is outside its supported bound")
    return result


def _bounded_int(value: object, name: str, *, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CloudTTSConfigError(f"{name} is outside its supported bound")
    if not 1 <= value <= maximum:
        raise CloudTTSConfigError(f"{name} is outside its supported bound")
    return value


def _env_float(values: Mapping[str, str], key: str, default: float) -> float:
    raw = values.get(key)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise CloudTTSConfigError(f"{key} is invalid") from None


def _env_int(values: Mapping[str, str], key: str, default: int) -> int:
    raw = values.get(key)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise CloudTTSConfigError(f"{key} is invalid") from None


__all__ = [
    "ALLOWED_CONTENT_TYPES",
    "AUTHORIZATION_ENV",
    "AUTHORIZATION_HEADER",
    "CloudTTSClient",
    "CloudTTSConfig",
    "CloudTTSConfigError",
    "CloudTTSResult",
    "CloudTTSStatus",
    "ENDPOINT_ENV",
    "MAX_RESPONSE_BYTES_ENV",
    "MAX_TEXT_BYTES_ENV",
    "TIMEOUT_ENV",
    "TTS_PATH",
]
