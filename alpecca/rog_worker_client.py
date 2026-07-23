"""Strict client for Alpecca's non-speaking Jason_HOLYROG compute worker.

The worker is an optional accelerator, never a second CoreMind.  This client
therefore exposes only three fixed, bounded operations and carries no memory,
Discord, or continuity-lease authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import ssl
import time
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)


HEALTH_PATH = "/v1/health"
REASON_PATH = "/v1/reason"
BLENDER_PATH = "/v1/render/blender"

TIMESTAMP_HEADER = "X-Alpecca-Worker-Timestamp"
NONCE_HEADER = "X-Alpecca-Worker-Nonce"
BODY_SHA256_HEADER = "X-Alpecca-Worker-Body-SHA256"
SIGNATURE_HEADER = "X-Alpecca-Worker-Signature"
REQUEST_ID_HEADER = "X-Alpecca-Request-Id"

URL_ENV = "ALPECCA_ROG_WORKER_URL"
SECRET_ENV = "ALPECCA_ROG_WORKER_SECRET"
ALLOW_PRIVATE_LAN_ENV = "ALPECCA_ROG_WORKER_ALLOW_PRIVATE_LAN"
TIMEOUT_ENV = "ALPECCA_ROG_WORKER_TIMEOUT_SECONDS"
TIMEOUT_COMPAT_ENV = "ALPECCA_ROG_WORKER_TIMEOUT"
HEALTH_TIMEOUT_ENV = "ALPECCA_ROG_WORKER_HEALTH_TIMEOUT_SECONDS"
REASON_TIMEOUT_ENV = "ALPECCA_ROG_WORKER_REASON_TIMEOUT_SECONDS"
RENDER_TIMEOUT_ENV = "ALPECCA_ROG_WORKER_RENDER_TIMEOUT_SECONDS"
MAX_REQUEST_BYTES_ENV = "ALPECCA_ROG_WORKER_MAX_REQUEST_BYTES"
MAX_RESPONSE_BYTES_ENV = "ALPECCA_ROG_WORKER_MAX_RESPONSE_BYTES"
MODEL_ENV = "ALPECCA_ROG_WORKER_MODEL"
ALLOWED_MODELS_ENV = "ALPECCA_ROG_WORKER_MODELS"
CREDENTIAL_TARGET_ENV = "ALPECCA_ROG_WORKER_CREDENTIAL_TARGET"
CA_CERT_ENV = "ALPECCA_ROG_WORKER_CA_CERT"

DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_BASE_URL = "https://Jason_HOLYROG:8788"
DEFAULT_CREDENTIAL_TARGET = "Alpecca/Jason_HOLYROG/ComputeWorker"
DEFAULT_HEALTH_TIMEOUT_SECONDS = 2.0
DEFAULT_REASON_TIMEOUT_SECONDS = 180.0
DEFAULT_RENDER_TIMEOUT_SECONDS = 650.0
DEFAULT_TIMEOUT_SECONDS = DEFAULT_REASON_TIMEOUT_SECONDS
DEFAULT_MAX_REQUEST_BYTES = 65_536
DEFAULT_MAX_RESPONSE_BYTES = 128 * 1024
MAX_HEALTH_TIMEOUT_SECONDS = 5.0
MAX_REASON_TIMEOUT_SECONDS = 180.0
MAX_RENDER_TIMEOUT_SECONDS = 900.0
MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_SYSTEM_PROMPT_BYTES = 8 * 1024
MAX_USER_PROMPT_BYTES = 32 * 1024
MAX_HISTORY_MESSAGES = 32
MAX_HISTORY_MESSAGE_BYTES = 12 * 1024
MAX_REASON_TEXT_BYTES = 32 * 1024
MAX_TOKENS_LIMIT = 2048
EXPECTED_HOSTNAME = "Jason_HOLYROG"

HEALTH_SCHEMA = "alpecca.rog-worker.health.v1"
REASON_REQUEST_SCHEMA = "alpecca.rog-worker.reason.request.v1"
REASON_RESPONSE_SCHEMA = "alpecca.rog-worker.reason.response.v1"
BLENDER_REQUEST_SCHEMA = "alpecca.rog-worker.blender.request.v1"
BLENDER_RESPONSE_SCHEMA = "alpecca.rog-worker.blender.response.v1"

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$")
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,96}$")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,127}$")
_BLEND_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,119}\.blend$")
_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
_OUTPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.png$")
_REMOTE_ERROR_CODES = frozenset(
    {
        "busy",
        "cancelled",
        "internal_error",
        "invalid_request",
        "model_unavailable",
        "remote_error",
        "render_failed",
        "timeout",
    }
)

OpenCallable = Callable[..., object]
Clock = Callable[[], float]
TokenFactory = Callable[[], str]


class RogWorkerError(Exception):
    """Base class for all worker-client failures."""


class RogWorkerConfigurationError(RogWorkerError, ValueError):
    """Local worker configuration was invalid; no request was sent."""


class RogWorkerTransportError(RogWorkerError):
    """The exact configured worker could not be reached."""


class RogWorkerAuthenticationError(RogWorkerError):
    """The worker rejected the HMAC authentication material."""


class RogWorkerUnavailableError(RogWorkerError):
    """The worker is temporarily unable to accept work."""


class RogWorkerProtocolError(RogWorkerError):
    """The worker response violated the bounded protocol."""


class RogWorkerResponseTooLargeError(RogWorkerProtocolError):
    """The worker response exceeded the configured byte ceiling."""


class RogWorkerRemoteJobError(RogWorkerError):
    """A well-formed worker response reported a bounded job failure."""

    def __init__(self, code: str = "remote_error") -> None:
        safe_code = code if code in _REMOTE_ERROR_CODES else "remote_error"
        self.code = safe_code
        super().__init__(f"worker job failed ({safe_code})")


@dataclass(frozen=True, slots=True)
class WorkerHealth:
    request_id: str
    hostname: str
    ready: bool
    reasoning_ready: bool
    blender_ready: bool
    role: str = "compute-only"
    speaking: bool = False
    discord: bool = False

@dataclass(frozen=True, slots=True)
class ReasoningResult:
    request_id: str
    model: str
    text: str = field(repr=False)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    elapsed_ms: int = 0


@dataclass(frozen=True, slots=True)
class BlenderRenderResult:
    request_id: str
    job_id: str
    frame: int
    status: str
    artifact_id: str
    artifact_name: str
    artifact_sha256: str
    artifact_bytes: int
    elapsed_ms: int


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def body_sha256_hex(body: bytes) -> str:
    """Return the lowercase SHA-256 used in the signed canonical request."""

    if not isinstance(body, bytes):
        raise TypeError("body must be bytes")
    return hashlib.sha256(body).hexdigest()


def canonical_request(
    method: str,
    path: str,
    timestamp: int | str,
    nonce: str,
    body: bytes,
) -> bytes:
    """Build ``METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256_HEX(body)``."""

    clean_method = _validated_method(method)
    clean_path = _validated_path(path)
    clean_timestamp = _validated_timestamp(timestamp)
    clean_nonce = _validated_nonce(nonce)
    digest = body_sha256_hex(body)
    return "\n".join(
        (clean_method, clean_path, clean_timestamp, clean_nonce, digest)
    ).encode("utf-8")


def sign_request(
    secret: str | bytes,
    method: str,
    path: str,
    timestamp: int | str,
    nonce: str,
    body: bytes,
) -> str:
    """Return the lowercase HMAC-SHA256 signature for one exact body."""

    key = _validated_secret(secret)
    material = canonical_request(method, path, timestamp, nonce, body)
    return hmac.new(key, material, hashlib.sha256).hexdigest()


class RogWorkerClient:
    """Synchronous, fail-closed client for one exact compute-only worker."""

    __slots__ = (
        "_allow_private_lan_http",
        "_allowed_models",
        "_base_url",
        "_ca_cert",
        "_clock",
        "_default_model",
        "_health_timeout_seconds",
        "_max_request_bytes",
        "_max_response_bytes",
        "_nonce_factory",
        "_opener",
        "_request_id_factory",
        "_reason_timeout_seconds",
        "_render_timeout_seconds",
        "_secret",
    )

    def __init__(
        self,
        base_url: str,
        secret: str | bytes,
        *,
        allow_private_lan_http: bool = False,
        ca_cert: str | os.PathLike[str] | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        health_timeout_seconds: float = DEFAULT_HEALTH_TIMEOUT_SECONDS,
        reason_timeout_seconds: float | None = None,
        render_timeout_seconds: float = DEFAULT_RENDER_TIMEOUT_SECONDS,
        max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        default_model: str = DEFAULT_MODEL,
        allowed_models: Sequence[str] | None = None,
        opener: OpenCallable | object | None = None,
        clock: Clock = time.time,
        nonce_factory: TokenFactory | None = None,
        request_id_factory: TokenFactory | None = None,
    ) -> None:
        if not isinstance(allow_private_lan_http, bool):
            raise RogWorkerConfigurationError(
                "allow_private_lan_http must be a boolean"
            )
        self._base_url = _validated_base_url(
            base_url,
            allow_private_lan_http=allow_private_lan_http,
        )
        parsed_base_url = urlsplit(self._base_url)
        self._ca_cert = _validated_ca_cert(
            ca_cert,
            required=(
                parsed_base_url.scheme == "https"
                and not _is_loopback_host(parsed_base_url.hostname or "")
            ),
        )
        self._secret = _validated_secret(secret)
        self._allow_private_lan_http = allow_private_lan_http
        legacy_reason_timeout = _bounded_float(
            timeout_seconds,
            "timeout_seconds",
            minimum=0.2,
            maximum=MAX_REASON_TIMEOUT_SECONDS,
        )
        self._health_timeout_seconds = _bounded_float(
            health_timeout_seconds,
            "health_timeout_seconds",
            minimum=0.2,
            maximum=MAX_HEALTH_TIMEOUT_SECONDS,
        )
        self._reason_timeout_seconds = _bounded_float(
            legacy_reason_timeout
            if reason_timeout_seconds is None
            else reason_timeout_seconds,
            "reason_timeout_seconds",
            minimum=0.2,
            maximum=MAX_REASON_TIMEOUT_SECONDS,
        )
        self._render_timeout_seconds = _bounded_float(
            render_timeout_seconds,
            "render_timeout_seconds",
            minimum=1.0,
            maximum=MAX_RENDER_TIMEOUT_SECONDS,
        )
        self._max_request_bytes = _bounded_int(
            max_request_bytes,
            "max_request_bytes",
            minimum=1024,
            maximum=MAX_REQUEST_BYTES,
        )
        self._max_response_bytes = _bounded_int(
            max_response_bytes,
            "max_response_bytes",
            minimum=1024,
            maximum=MAX_RESPONSE_BYTES,
        )
        self._default_model = _validated_model(default_model)
        if isinstance(allowed_models, (str, bytes)):
            raise RogWorkerConfigurationError("allowed_models must be a sequence")
        configured_models = (
            tuple(allowed_models)
            if allowed_models is not None
            else (self._default_model,)
        )
        if not configured_models or len(configured_models) > 16:
            raise RogWorkerConfigurationError(
                "allowed_models must contain between 1 and 16 models"
            )
        self._allowed_models = frozenset(
            _validated_model(model) for model in configured_models
        )
        if self._default_model not in self._allowed_models:
            raise RogWorkerConfigurationError("default model is not allowed")
        if not callable(clock):
            raise RogWorkerConfigurationError("clock must be callable")
        self._clock = clock
        self._nonce_factory = nonce_factory or (lambda: secrets.token_urlsafe(24))
        self._request_id_factory = request_id_factory or (
            lambda: secrets.token_hex(16)
        )
        if not callable(self._nonce_factory) or not callable(
            self._request_id_factory
        ):
            raise RogWorkerConfigurationError("token factories must be callable")
        candidate = opener or _default_opener(
            parsed_base_url,
            self._ca_cert,
        )
        if not callable(candidate) and not callable(getattr(candidate, "open", None)):
            raise RogWorkerConfigurationError(
                "opener must be callable or expose open()"
            )
        self._opener = candidate

    def __repr__(self) -> str:
        return (
            "RogWorkerClient("
            f"base_url={self._base_url!r}, "
            f"health_timeout_seconds={self._health_timeout_seconds!r}, "
            f"reason_timeout_seconds={self._reason_timeout_seconds!r}, "
            f"render_timeout_seconds={self._render_timeout_seconds!r}, "
            f"max_request_bytes={self._max_request_bytes!r}, "
            f"max_response_bytes={self._max_response_bytes!r}, "
            "secret=<redacted>)"
        )

    @classmethod
    def from_environment(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        opener: OpenCallable | object | None = None,
        clock: Clock = time.time,
        nonce_factory: TokenFactory | None = None,
        request_id_factory: TokenFactory | None = None,
        win32cred_module: object | None = None,
    ) -> "RogWorkerClient":
        """Build from injected or process environment without logging secrets."""

        values = os.environ if env is None else env
        base_url = values.get(URL_ENV, DEFAULT_BASE_URL)
        secret = values.get(SECRET_ENV, "")
        if not secret:
            target = _credential_target(values)
            secret = _read_windows_credential(
                target,
                win32cred_module=win32cred_module,
            )
        if not secret:
            raise RogWorkerConfigurationError("ROG worker HMAC secret is unavailable")
        default_model = values.get(MODEL_ENV, DEFAULT_MODEL)
        raw_allowed = values.get(ALLOWED_MODELS_ENV, "").strip()
        allowed_models = (
            tuple(part.strip() for part in raw_allowed.split(",") if part.strip())
            if raw_allowed
            else (default_model,)
        )
        reason_timeout_seconds = _environment_reason_timeout(values)
        return cls(
            base_url,
            secret,
            allow_private_lan_http=_env_bool(
                values,
                ALLOW_PRIVATE_LAN_ENV,
                False,
            ),
            ca_cert=_environment_ca_cert(values, base_url),
            timeout_seconds=reason_timeout_seconds,
            health_timeout_seconds=_env_float(
                values,
                HEALTH_TIMEOUT_ENV,
                DEFAULT_HEALTH_TIMEOUT_SECONDS,
            ),
            reason_timeout_seconds=reason_timeout_seconds,
            render_timeout_seconds=_env_float(
                values,
                RENDER_TIMEOUT_ENV,
                DEFAULT_RENDER_TIMEOUT_SECONDS,
            ),
            max_request_bytes=_env_int(
                values,
                MAX_REQUEST_BYTES_ENV,
                DEFAULT_MAX_REQUEST_BYTES,
            ),
            max_response_bytes=_env_int(
                values,
                MAX_RESPONSE_BYTES_ENV,
                DEFAULT_MAX_RESPONSE_BYTES,
            ),
            default_model=default_model,
            allowed_models=allowed_models,
            opener=opener,
            clock=clock,
            nonce_factory=nonce_factory,
            request_id_factory=request_id_factory,
        )

    def health(self) -> WorkerHealth:
        request_id = self._new_request_id()
        payload = self._request_json(
            "GET",
            HEALTH_PATH,
            None,
            request_id=request_id,
            timeout_seconds=self._health_timeout_seconds,
        )
        _exact_response_keys(
            payload,
            {
                "schema",
                "ok",
                "request_id",
                "hostname",
                "role",
                "ready",
                "speaking",
                "discord",
                "capabilities",
            },
        )
        if payload.get("schema") != HEALTH_SCHEMA:
            raise RogWorkerProtocolError("worker response schema did not match")
        self._expect_request_id(payload, request_id)

        hostname = _required_text(payload, "hostname", maximum=128)
        role = _required_text(payload, "role", maximum=32)
        if _required_bool(payload, "ok") is not True:
            raise RogWorkerProtocolError("worker health response was not successful")
        ready = _required_bool(payload, "ready")
        speaking = _required_bool(payload, "speaking")
        discord = _required_bool(payload, "discord")
        if hostname.casefold() != EXPECTED_HOSTNAME.casefold():
            raise RogWorkerProtocolError("worker hostname did not match")
        if role != "compute-only" or speaking or discord:
            raise RogWorkerProtocolError("worker role contract was not compute-only")
        capabilities = _required_mapping(payload, "capabilities")
        if set(capabilities) != {"reasoning", "blender"}:
            raise RogWorkerProtocolError("worker capabilities did not match")
        reasoning_ready = _capability_ready(capabilities, "reasoning")
        blender_ready = _capability_ready(capabilities, "blender")
        if ready != (reasoning_ready or blender_ready):
            raise RogWorkerProtocolError("worker readiness was inconsistent")
        return WorkerHealth(
            request_id=request_id,
            hostname=hostname,
            ready=ready,
            reasoning_ready=reasoning_ready,
            blender_ready=blender_ready,
            role=role,
            speaking=speaking,
            discord=discord,
        )

    def reason(
        self,
        system_prompt: str,
        user_prompt: str,
        history: Sequence[Mapping[str, str]] | None = None,
        model: str | None = None,
        max_tokens: int = 512,
    ) -> ReasoningResult:
        selected_model = _validated_model(model or self._default_model)
        if selected_model not in self._allowed_models:
            raise RogWorkerConfigurationError("requested model is not allowed")
        clean_system = _bounded_utf8_text(
            system_prompt,
            "system_prompt",
            MAX_SYSTEM_PROMPT_BYTES,
        )
        clean_user = _bounded_utf8_text(
            user_prompt,
            "user_prompt",
            MAX_USER_PROMPT_BYTES,
        )
        if not clean_user.strip():
            raise RogWorkerConfigurationError("user_prompt must not be empty")
        clean_history = _validated_history(history)
        clean_max_tokens = _bounded_int(
            max_tokens,
            "max_tokens",
            minimum=1,
            maximum=MAX_TOKENS_LIMIT,
        )
        request_id = self._new_request_id()
        request_payload: dict[str, object] = {
            "schema": REASON_REQUEST_SCHEMA,
            "request_id": request_id,
            "system_prompt": clean_system,
            "user_prompt": clean_user,
            "history": clean_history,
            "model": selected_model,
            "max_tokens": clean_max_tokens,
        }
        payload = self._request_json(
            "POST",
            REASON_PATH,
            request_payload,
            request_id=request_id,
            timeout_seconds=self._reason_timeout_seconds,
        )
        _exact_response_keys(
            payload,
            {"schema", "ok", "request_id", "result"},
        )
        if payload.get("schema") != REASON_RESPONSE_SCHEMA:
            raise RogWorkerProtocolError("worker response schema did not match")
        if payload.get("ok") is not True:
            raise RogWorkerProtocolError("worker reasoning response was not successful")
        self._expect_request_id(payload, request_id)
        result = _required_mapping(payload, "result")
        if not set(result).issubset(
            {
                "model",
                "text",
                "prompt_tokens",
                "completion_tokens",
                "elapsed_ms",
            }
        ) or not {"model", "text", "elapsed_ms"}.issubset(result):
            raise RogWorkerProtocolError("worker reasoning result fields did not match")
        response_model = _required_text(result, "model", maximum=128)
        if response_model != selected_model:
            raise RogWorkerProtocolError("worker returned a different model")
        text = _required_text(result, "text", maximum=MAX_REASON_TEXT_BYTES)
        if not text.strip():
            raise RogWorkerProtocolError("worker reasoning text was empty")
        return ReasoningResult(
            request_id=request_id,
            model=response_model,
            text=text,
            prompt_tokens=_optional_nonnegative_int(result, "prompt_tokens"),
            completion_tokens=_optional_nonnegative_int(
                result,
                "completion_tokens",
            ),
            elapsed_ms=_required_nonnegative_int(result, "elapsed_ms"),
        )

    def render_blender(
        self,
        project: str,
        frame: int = 1,
    ) -> BlenderRenderResult:
        clean_project = _validated_project(project)
        clean_frame = _bounded_int(
            frame,
            "frame",
            minimum=1,
            maximum=999_999,
        )
        request_id = self._new_request_id()
        request_payload: dict[str, object] = {
            "schema": BLENDER_REQUEST_SCHEMA,
            "request_id": request_id,
            "project": clean_project,
            "frame": clean_frame,
        }
        payload = self._request_json(
            "POST",
            BLENDER_PATH,
            request_payload,
            request_id=request_id,
            timeout_seconds=self._render_timeout_seconds,
        )
        _exact_response_keys(
            payload,
            {"schema", "ok", "request_id", "result"},
        )
        if payload.get("schema") != BLENDER_RESPONSE_SCHEMA:
            raise RogWorkerProtocolError("worker response schema did not match")
        if payload.get("ok") is not True:
            raise RogWorkerProtocolError("worker render response was not successful")
        self._expect_request_id(payload, request_id)
        result = _required_mapping(payload, "result")
        if set(result) != {"job_id", "frame", "status", "artifact", "elapsed_ms"}:
            raise RogWorkerProtocolError("worker render result fields did not match")
        job_id = _required_safe_token(result, "job_id")
        status = _required_text(result, "status", maximum=32)
        if status != "completed":
            raise RogWorkerProtocolError("worker returned an invalid render status")
        response_frame = _required_nonnegative_int(result, "frame")
        if response_frame != clean_frame:
            raise RogWorkerProtocolError("worker returned a different render frame")
        artifact = _required_mapping(result, "artifact")
        if set(artifact) != {"id", "name", "sha256", "bytes"}:
            raise RogWorkerProtocolError("worker artifact fields did not match")
        artifact_id = _required_safe_token(artifact, "id")
        artifact_name = _required_text(artifact, "name", maximum=128)
        if not _OUTPUT_NAME_RE.fullmatch(artifact_name):
            raise RogWorkerProtocolError("worker artifact name was invalid")
        artifact_sha256 = _required_text(artifact, "sha256", maximum=64)
        if not _HEX_64_RE.fullmatch(artifact_sha256):
            raise RogWorkerProtocolError("worker artifact digest was invalid")
        artifact_bytes = _required_positive_int(artifact, "bytes")
        return BlenderRenderResult(
            request_id=request_id,
            job_id=job_id,
            frame=clean_frame,
            status=status,
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            artifact_sha256=artifact_sha256,
            artifact_bytes=artifact_bytes,
            elapsed_ms=_required_nonnegative_int(result, "elapsed_ms"),
        )

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None,
        *,
        request_id: str,
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        body = b"" if payload is None else _canonical_json(payload)
        if len(body) > self._max_request_bytes:
            raise RogWorkerConfigurationError("worker request exceeded byte limit")
        timestamp_value = self._clock()
        if isinstance(timestamp_value, bool) or not isinstance(
            timestamp_value,
            (int, float),
        ):
            raise RogWorkerConfigurationError("clock returned an invalid timestamp")
        if not math.isfinite(float(timestamp_value)) or float(timestamp_value) <= 0:
            raise RogWorkerConfigurationError("clock returned an invalid timestamp")
        timestamp = str(int(float(timestamp_value)))
        nonce = self._new_nonce()
        digest = body_sha256_hex(body)
        signature = sign_request(
            self._secret,
            method,
            path,
            timestamp,
            nonce,
            body,
        )
        endpoint = self._base_url + path
        headers = {
            "Accept": "application/json",
            TIMESTAMP_HEADER: timestamp,
            NONCE_HEADER: nonce,
            BODY_SHA256_HEADER: digest,
            SIGNATURE_HEADER: signature,
            REQUEST_ID_HEADER: request_id,
        }
        if payload is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(
            endpoint,
            data=body if payload is not None else None,
            headers=headers,
            method=method,
        )
        if request.full_url != endpoint or request.get_method() != method:
            raise RogWorkerConfigurationError("worker request target was invalid")

        try:
            response = self._open(request, timeout_seconds=timeout_seconds)
        except HTTPError as exc:
            try:
                exc.close()
            except Exception:
                pass
            self._raise_http_error(int(exc.code))
        except (URLError, TimeoutError, OSError):
            raise RogWorkerTransportError("worker request failed") from None
        except RogWorkerError:
            raise
        except Exception:
            raise RogWorkerTransportError("worker request failed") from None

        try:
            return self._decode_response(response, endpoint)
        finally:
            try:
                response.close()
            except Exception:
                pass

    def _open(self, request: Request, *, timeout_seconds: float):
        opener = self._opener
        if callable(opener):
            return opener(request, timeout=timeout_seconds)
        return opener.open(request, timeout=timeout_seconds)

    def _decode_response(
        self,
        response: object,
        endpoint: str,
    ) -> Mapping[str, object]:
        status = _response_status(response)
        if status != 200:
            self._raise_http_error(status)
        final_url = _response_url(response)
        if final_url != endpoint:
            raise RogWorkerProtocolError("worker response target changed")
        headers = getattr(response, "headers", None)
        content_type = ""
        content_encoding = ""
        content_length: str | None = None
        if headers is not None and callable(getattr(headers, "get", None)):
            content_type = str(headers.get("Content-Type") or "")
            content_encoding = str(headers.get("Content-Encoding") or "")
            raw_length = headers.get("Content-Length")
            content_length = None if raw_length is None else str(raw_length)
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise RogWorkerProtocolError("worker response was not JSON")
        if content_encoding.strip().lower() not in {"", "identity"}:
            raise RogWorkerProtocolError("encoded worker responses are not allowed")
        declared = _validated_content_length(content_length)
        if declared is not None and declared > self._max_response_bytes:
            raise RogWorkerResponseTooLargeError(
                "worker response exceeded byte limit"
            )
        try:
            body = response.read(self._max_response_bytes + 1)
        except Exception:
            raise RogWorkerTransportError("worker response could not be read") from None
        if not isinstance(body, bytes):
            raise RogWorkerProtocolError("worker response body was invalid")
        if len(body) > self._max_response_bytes:
            raise RogWorkerResponseTooLargeError(
                "worker response exceeded byte limit"
            )
        if declared is not None and declared != len(body):
            raise RogWorkerProtocolError("worker response length did not match")
        try:
            decoded = json.loads(body.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RogWorkerProtocolError("worker response JSON was invalid") from None
        if not isinstance(decoded, Mapping):
            raise RogWorkerProtocolError("worker response must be a JSON object")
        return decoded

    @staticmethod
    def _raise_http_error(status: int) -> None:
        if status in {401, 403}:
            raise RogWorkerAuthenticationError("worker authentication failed")
        if status in {408, 425, 429, 502, 503, 504}:
            raise RogWorkerUnavailableError("worker is unavailable")
        raise RogWorkerProtocolError(f"worker returned HTTP {status}")

    @staticmethod
    def _expect_request_id(
        payload: Mapping[str, object],
        expected: str,
    ) -> None:
        if payload.get("request_id") != expected:
            raise RogWorkerProtocolError("worker request id did not match")

    @staticmethod
    def _new_token(factory: TokenFactory, name: str) -> object:
        try:
            value = factory()
        except Exception:
            raise RogWorkerConfigurationError(f"{name} generation failed") from None
        return value

    def _new_request_id(self) -> str:
        value = self._new_token(self._request_id_factory, "request id")
        if not isinstance(value, str) or not _REQUEST_ID_RE.fullmatch(value):
            raise RogWorkerConfigurationError("request id is invalid")
        return value

    def _new_nonce(self) -> str:
        return _validated_nonce(self._new_token(self._nonce_factory, "nonce"))


def _canonical_json(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise RogWorkerConfigurationError("worker request was not valid JSON") from None


def _validated_secret(secret: str | bytes) -> bytes:
    if isinstance(secret, str):
        if "\x00" in secret or "\r" in secret or "\n" in secret:
            raise RogWorkerConfigurationError("HMAC secret is invalid")
        encoded = secret.encode("utf-8")
    elif isinstance(secret, bytes):
        encoded = bytes(secret)
    else:
        raise RogWorkerConfigurationError("HMAC secret is invalid")
    if len(encoded) < 32 or len(encoded) > 512:
        raise RogWorkerConfigurationError("HMAC secret length is invalid")
    return encoded


def _credential_error_code(exc: BaseException) -> int | None:
    code = getattr(exc, "winerror", None)
    if isinstance(code, int):
        return code
    args = getattr(exc, "args", ())
    return args[0] if args and isinstance(args[0], int) else None


def _credential_target(values: Mapping[str, str]) -> str:
    target = str(values.get(CREDENTIAL_TARGET_ENV, DEFAULT_CREDENTIAL_TARGET)).strip()
    if (
        not target
        or len(target) > 240
        or any(ord(character) < 32 or ord(character) == 127 for character in target)
    ):
        raise RogWorkerConfigurationError("worker credential target is invalid")
    return target


def _decode_credential_blob(blob: object) -> str:
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    if isinstance(blob, bytes):
        encoding = "utf-16-le" if b"\x00" in blob else "utf-8"
        try:
            return blob.decode(encoding).rstrip("\x00")
        except UnicodeDecodeError:
            raise RogWorkerConfigurationError(
                "stored worker credential is invalid"
            ) from None
    if isinstance(blob, str):
        return blob
    raise RogWorkerConfigurationError("stored worker credential is invalid")


def _read_windows_credential(
    target: str,
    *,
    win32cred_module: object | None = None,
) -> str | None:
    """Read exactly one generic credential; never create or update one."""

    win32cred = win32cred_module
    if win32cred is None:
        if os.name != "nt":
            return None
        try:
            import win32cred as imported_win32cred
        except ImportError:
            return None
        win32cred = imported_win32cred
    reader = getattr(win32cred, "CredRead", None)
    credential_type = getattr(win32cred, "CRED_TYPE_GENERIC", None)
    if not callable(reader) or not isinstance(credential_type, int):
        raise RogWorkerConfigurationError(
            "Windows Credential Manager reader is unavailable"
        )
    try:
        credential = reader(target, credential_type, 0)
    except Exception as exc:
        if _credential_error_code(exc) in {2, 1168}:
            return None
        raise RogWorkerConfigurationError(
            "worker credential could not be read"
        ) from None
    if not isinstance(credential, Mapping):
        raise RogWorkerConfigurationError("stored worker credential is invalid")
    return _decode_credential_blob(credential.get("CredentialBlob"))


def _validated_method(method: str) -> str:
    if not isinstance(method, str) or method.upper() not in {"GET", "POST"}:
        raise RogWorkerConfigurationError("worker method is invalid")
    if method != method.upper():
        raise RogWorkerConfigurationError("worker method must be uppercase")
    return method


def _validated_path(path: str) -> str:
    if path not in {HEALTH_PATH, REASON_PATH, BLENDER_PATH}:
        raise RogWorkerConfigurationError("worker path is not allowed")
    return path


def _validated_timestamp(timestamp: int | str) -> str:
    if isinstance(timestamp, bool):
        raise RogWorkerConfigurationError("worker timestamp is invalid")
    value = str(timestamp)
    if not value.isascii() or not value.isdigit() or len(value) > 16:
        raise RogWorkerConfigurationError("worker timestamp is invalid")
    if int(value) <= 0:
        raise RogWorkerConfigurationError("worker timestamp is invalid")
    return value


def _validated_nonce(value: object) -> str:
    if not isinstance(value, str) or not _NONCE_RE.fullmatch(value):
        raise RogWorkerConfigurationError("nonce is invalid")
    return value


def _validated_model(value: object) -> str:
    if not isinstance(value, str) or not _MODEL_RE.fullmatch(value):
        raise RogWorkerConfigurationError("model name is invalid")
    return value


def _validated_base_url(value: object, *, allow_private_lan_http: bool) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RogWorkerConfigurationError("worker URL is invalid")
    if any(ord(char) < 0x21 or char == "\\" for char in value):
        raise RogWorkerConfigurationError("worker URL is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise RogWorkerConfigurationError("worker URL is invalid") from None
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RogWorkerConfigurationError("worker URL must be an exact origin")
    if port is not None and not (1 <= port <= 65535):
        raise RogWorkerConfigurationError("worker URL port is invalid")
    if parsed.scheme == "http":
        if not _is_loopback_host(parsed.hostname):
            raise RogWorkerConfigurationError(
                "non-loopback ROG worker connections require authenticated TLS"
            )
    elif not _is_loopback_host(parsed.hostname):
        if parsed.hostname.rstrip(".").casefold() != EXPECTED_HOSTNAME.casefold():
            raise RogWorkerConfigurationError(
                "remote ROG worker URL must use the Jason_HOLYROG DNS name"
            )
    return value[:-1] if value.endswith("/") else value


def _is_loopback_host(hostname: str) -> bool:
    clean = hostname.rstrip(".").casefold()
    if clean == "localhost":
        return True
    try:
        return ipaddress.ip_address(clean).is_loopback
    except ValueError:
        return False


def _default_tls_dir(values: Mapping[str, str]) -> Path:
    local_app_data = str(values.get("LOCALAPPDATA", "")).strip()
    if local_app_data:
        return Path(local_app_data).expanduser() / "Alpecca" / "rog-worker" / "tls"
    return Path.home() / "AppData" / "Local" / "Alpecca" / "rog-worker" / "tls"


def _environment_ca_cert(
    values: Mapping[str, str],
    base_url: str,
) -> str | None:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or _is_loopback_host(parsed.hostname or ""):
        configured = str(values.get(CA_CERT_ENV, "")).strip()
        return configured or None
    configured = str(values.get(CA_CERT_ENV, "")).strip()
    return configured or str(_default_tls_dir(values) / "jason-holyrog.crt")


def _validated_ca_cert(
    value: str | os.PathLike[str] | None,
    *,
    required: bool,
) -> Path | None:
    if value is None or not str(value).strip():
        if required:
            raise RogWorkerConfigurationError(
                f"{CA_CERT_ENV} certificate is required for the remote ROG worker"
            )
        return None
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise RogWorkerConfigurationError("ROG worker CA certificate was not found") from None
    if not resolved.is_file():
        raise RogWorkerConfigurationError("ROG worker CA certificate is not a file")
    return resolved


def _default_opener(parsed_base_url, ca_cert: Path | None) -> OpenCallable:
    handlers: list[object] = [ProxyHandler({}), _NoRedirect()]
    if parsed_base_url.scheme == "https":
        try:
            context = ssl.create_default_context(
                purpose=ssl.Purpose.SERVER_AUTH,
                cafile=str(ca_cert) if ca_cert is not None else None,
            )
        except (OSError, ssl.SSLError, ValueError):
            raise RogWorkerConfigurationError(
                "ROG worker CA certificate could not be loaded"
            ) from None
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        if hasattr(ssl, "TLSVersion"):
            context.minimum_version = ssl.TLSVersion.TLSv1_2
        handlers.append(HTTPSHandler(context=context))
    return build_opener(*handlers).open


def _is_private_lan_host(hostname: str) -> bool:
    clean = hostname.rstrip(".").casefold()
    if clean == "localhost":
        return True
    try:
        address = ipaddress.ip_address(clean)
    except ValueError:
        if not clean or len(clean) > 253:
            return False
        if clean.endswith((".local", ".lan", ".home.arpa")):
            return True
        return "." not in clean and re.fullmatch(r"[a-z0-9_-]+", clean) is not None
    return bool(
        (address.is_private or address.is_loopback or address.is_link_local)
        and not address.is_multicast
        and not address.is_unspecified
    )


def _validated_project(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RogWorkerConfigurationError("Blender project is invalid")
    if len(value) > 120 or "\x00" in value:
        raise RogWorkerConfigurationError("Blender project is invalid")
    if (
        not _BLEND_NAME_RE.fullmatch(value)
        or "/" in value
        or "\\" in value
        or ":" in value
    ):
        raise RogWorkerConfigurationError(
            "Blender project must be an approved-root .blend basename"
        )
    return value


def _validated_history(
    history: Sequence[Mapping[str, str]] | None,
) -> list[dict[str, str]]:
    if history is None:
        return []
    if isinstance(history, (str, bytes)) or not isinstance(history, Sequence):
        raise RogWorkerConfigurationError("history must be a sequence")
    if len(history) > MAX_HISTORY_MESSAGES:
        raise RogWorkerConfigurationError("history has too many messages")
    cleaned: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, Mapping) or set(item) != {"role", "content"}:
            raise RogWorkerConfigurationError("history message shape is invalid")
        role = item.get("role")
        if role not in {"user", "assistant"}:
            raise RogWorkerConfigurationError("history role is invalid")
        content = _bounded_utf8_text(
            item.get("content"),
            "history content",
            MAX_HISTORY_MESSAGE_BYTES,
        )
        cleaned.append({"role": role, "content": content})
    return cleaned


def _bounded_utf8_text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise RogWorkerConfigurationError(f"{name} is invalid")
    if len(value.encode("utf-8")) > maximum:
        raise RogWorkerConfigurationError(f"{name} exceeded byte limit")
    return value


def _bounded_int(
    value: object,
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RogWorkerConfigurationError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise RogWorkerConfigurationError(f"{name} is outside its bounds")
    return value


def _bounded_float(
    value: object,
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RogWorkerConfigurationError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < minimum or number > maximum:
        raise RogWorkerConfigurationError(f"{name} is outside its bounds")
    return number


def _env_bool(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().casefold()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise RogWorkerConfigurationError(f"{name} must be a boolean")


def _env_int(
    values: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw = values.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise RogWorkerConfigurationError(f"{name} must be an integer") from None


def _env_float(
    values: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    raw = values.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise RogWorkerConfigurationError(f"{name} must be numeric") from None


def _environment_reason_timeout(values: Mapping[str, str]) -> float:
    if values.get(REASON_TIMEOUT_ENV, "") != "":
        return _env_float(values, REASON_TIMEOUT_ENV, DEFAULT_REASON_TIMEOUT_SECONDS)
    if values.get(TIMEOUT_ENV, "") != "":
        return _env_float(values, TIMEOUT_ENV, DEFAULT_REASON_TIMEOUT_SECONDS)
    return _env_float(values, TIMEOUT_COMPAT_ENV, DEFAULT_REASON_TIMEOUT_SECONDS)


def _response_status(response: object) -> int:
    raw = getattr(response, "status", None)
    if raw is None and callable(getattr(response, "getcode", None)):
        raw = response.getcode()
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise RogWorkerProtocolError("worker response status was invalid")
    return raw


def _response_url(response: object) -> str:
    getter = getattr(response, "geturl", None)
    if not callable(getter):
        raise RogWorkerProtocolError("worker response URL was unavailable")
    value = getter()
    if not isinstance(value, str):
        raise RogWorkerProtocolError("worker response URL was invalid")
    return value


def _validated_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    if not value.isascii() or not value.isdigit():
        raise RogWorkerProtocolError("worker content length was invalid")
    return int(value)


def _required_mapping(
    payload: Mapping[str, object],
    key: str,
) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise RogWorkerProtocolError(f"worker {key} was invalid")
    return value


def _exact_response_keys(
    payload: Mapping[str, object],
    expected: set[str],
) -> None:
    if set(payload) != expected:
        raise RogWorkerProtocolError("worker response fields did not match")


def _required_text(
    payload: Mapping[str, object],
    key: str,
    *,
    maximum: int,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or "\x00" in value:
        raise RogWorkerProtocolError(f"worker {key} was invalid")
    if len(value.encode("utf-8")) > maximum:
        raise RogWorkerProtocolError(f"worker {key} exceeded its limit")
    return value


def _required_safe_token(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not _SAFE_TOKEN_RE.fullmatch(value):
        raise RogWorkerProtocolError(f"worker {key} was invalid")
    return value


def _required_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise RogWorkerProtocolError(f"worker {key} was invalid")
    return value


def _required_nonnegative_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RogWorkerProtocolError(f"worker {key} was invalid")
    return value


def _required_positive_int(payload: Mapping[str, object], key: str) -> int:
    value = _required_nonnegative_int(payload, key)
    if value == 0:
        raise RogWorkerProtocolError(f"worker {key} was invalid")
    return value


def _optional_nonnegative_int(
    payload: Mapping[str, object],
    key: str,
) -> int | None:
    if payload.get(key) is None:
        return None
    return _required_nonnegative_int(payload, key)


def _capability_ready(
    capabilities: Mapping[str, object],
    name: str,
) -> bool:
    value = capabilities.get(name)
    if (
        isinstance(value, Mapping)
        and set(value) == {"ready"}
        and isinstance(value.get("ready"), bool)
    ):
        return bool(value["ready"])
    raise RogWorkerProtocolError(f"worker {name} capability was invalid")


__all__ = [
    "ALLOW_PRIVATE_LAN_ENV",
    "ALLOWED_MODELS_ENV",
    "BLENDER_REQUEST_SCHEMA",
    "BLENDER_RESPONSE_SCHEMA",
    "BLENDER_PATH",
    "BODY_SHA256_HEADER",
    "BlenderRenderResult",
    "CA_CERT_ENV",
    "CREDENTIAL_TARGET_ENV",
    "DEFAULT_BASE_URL",
    "DEFAULT_CREDENTIAL_TARGET",
    "HEALTH_PATH",
    "HEALTH_SCHEMA",
    "HEALTH_TIMEOUT_ENV",
    "MODEL_ENV",
    "NONCE_HEADER",
    "REASON_REQUEST_SCHEMA",
    "REASON_RESPONSE_SCHEMA",
    "REASON_PATH",
    "REASON_TIMEOUT_ENV",
    "RENDER_TIMEOUT_ENV",
    "REQUEST_ID_HEADER",
    "RogWorkerAuthenticationError",
    "RogWorkerClient",
    "RogWorkerConfigurationError",
    "RogWorkerError",
    "RogWorkerProtocolError",
    "RogWorkerRemoteJobError",
    "RogWorkerResponseTooLargeError",
    "RogWorkerTransportError",
    "RogWorkerUnavailableError",
    "SIGNATURE_HEADER",
    "SECRET_ENV",
    "TIMESTAMP_HEADER",
    "TIMEOUT_COMPAT_ENV",
    "TIMEOUT_ENV",
    "URL_ENV",
    "ReasoningResult",
    "WorkerHealth",
    "body_sha256_hex",
    "canonical_request",
    "sign_request",
]
