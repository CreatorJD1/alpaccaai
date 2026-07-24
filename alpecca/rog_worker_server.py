"""Bounded compute-only worker for the Jason_HOLYROG machine.

This process is deliberately not an Alpecca runtime.  It exposes only two
authenticated jobs: local Ollama reasoning and a fixed Blender frame render.
It owns no conversational state, memory database, Discord connection, or
speaking loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import hmac
import http.client
import importlib
import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


HEALTH_SCHEMA = "alpecca.rog-worker.health.v1"
REASON_REQUEST_SCHEMA = "alpecca.rog-worker.reason.request.v1"
REASON_RESPONSE_SCHEMA = "alpecca.rog-worker.reason.response.v1"
BLENDER_REQUEST_SCHEMA = "alpecca.rog-worker.blender.request.v1"
BLENDER_RESPONSE_SCHEMA = "alpecca.rog-worker.blender.response.v1"
HYFUSER_HEALTH_SCHEMA = "alpecca.rog-worker.hyfuser.health.v1"
HYFUSER_REQUEST_SCHEMA = "alpecca.rog-worker.hyfuser.request.v1"
HYFUSER_RESPONSE_SCHEMA = "alpecca.rog-worker.hyfuser.response.v1"
HYFUSER_HEALTH_PATH = "/v1/soul/hyfuser/health"
HYFUSER_SCORE_PATH = "/v1/soul/hyfuser/score"
HYFUSER_ARCHITECTURE = "hyfuser-shared-backbone-seven-heads"
HYFUSER_PERSPECTIVES = (
    "Feeler",
    "Expressor",
    "Carer",
    "Doer",
    "Wanderer",
    "Reflector",
    "Improver",
)
HYFUSER_VECTOR_DIM = 8
HYFUSER_RUNTIME_MODULE = "alpecca_hyfuser_runtime"
HYFUSER_WEIGHTS_ENV = "ALPECCA_ROG_HYFUSER_WEIGHTS"
HYFUSER_WEIGHTS_SHA256_ENV = "ALPECCA_ROG_HYFUSER_WEIGHTS_SHA256"
HYFUSER_MODE_ENV = "ALPECCA_ROG_HYFUSER_MODE"
CREDENTIAL_TARGET_ENV = "ALPECCA_ROG_WORKER_CREDENTIAL_TARGET"
DEFAULT_CREDENTIAL_TARGET = "Alpecca/Jason_HOLYROG/ComputeWorker"
CREDENTIAL_TARGET = DEFAULT_CREDENTIAL_TARGET
TLS_CERT_ENV = "ALPECCA_ROG_WORKER_TLS_CERT"
TLS_KEY_ENV = "ALPECCA_ROG_WORKER_TLS_KEY"
REPLAY_DB_ENV = "ALPECCA_ROG_WORKER_REPLAY_DB"

TIMESTAMP_HEADER = "X-Alpecca-Worker-Timestamp"
NONCE_HEADER = "X-Alpecca-Worker-Nonce"
BODY_SHA256_HEADER = "X-Alpecca-Worker-Body-SHA256"
SIGNATURE_HEADER = "X-Alpecca-Worker-Signature"
REQUEST_ID_HEADER = "X-Alpecca-Request-Id"

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODELS = "qwen3.5:9b"
DEFAULT_PORT = 8788

REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,96}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
BLEND_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,119}\.blend$")
HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_RUNTIME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

LOGGER = logging.getLogger("alpecca.rog_worker")

_BLENDER_CHILD_ENV_ALLOWLIST = frozenset(
    {
        "APPDATA",
        "COMMONPROGRAMFILES",
        "COMMONPROGRAMFILES(X86)",
        "COMSPEC",
        "CUDA_PATH",
        "CUDA_VISIBLE_DEVICES",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
    }
)


class WorkerConfigurationError(RuntimeError):
    """The worker configuration is invalid or incomplete."""


class WorkerRequestError(RuntimeError):
    """A bounded, user-safe HTTP failure."""

    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = int(status_code)
        self.code = str(code)


def _credential_error_code(exc: BaseException) -> int | None:
    value = getattr(exc, "winerror", None)
    if isinstance(value, int):
        return value
    args = getattr(exc, "args", ())
    return args[0] if args and isinstance(args[0], int) else None


def _decode_credential_blob(blob: object) -> str:
    if isinstance(blob, bytes):
        encoding = "utf-16-le" if b"\x00" in blob else "utf-8"
        try:
            value = blob.decode(encoding).rstrip("\x00")
        except UnicodeDecodeError as exc:
            raise WorkerConfigurationError("worker credential is invalid") from exc
    elif isinstance(blob, str):
        value = blob
    else:
        value = ""
    return value


def _validate_secret(value: str) -> bytes:
    if any(ord(character) < 32 for character in value):
        raise WorkerConfigurationError("worker credential contains control characters")
    encoded = value.encode("utf-8")
    if not 32 <= len(encoded) <= 512:
        raise WorkerConfigurationError("worker credential must contain 32 to 512 bytes")
    return encoded


def load_worker_secret(
    environment: Mapping[str, str] | None = None,
    *,
    win32cred_module: object | None = None,
) -> bytes | None:
    """Read the worker secret from one env key or one exact credential target."""

    env = os.environ if environment is None else environment
    configured = str(env.get("ALPECCA_ROG_WORKER_SECRET", ""))
    if configured:
        return _validate_secret(configured)

    win32cred = win32cred_module
    if win32cred is None:
        if os.name != "nt":
            return None
        try:
            import win32cred as imported_win32cred
        except ImportError:
            return None
        win32cred = imported_win32cred

    target = str(env.get(CREDENTIAL_TARGET_ENV, DEFAULT_CREDENTIAL_TARGET)).strip()
    if (
        not target
        or len(target) > 240
        or any(ord(character) < 32 for character in target)
    ):
        raise WorkerConfigurationError("worker credential target is invalid")
    try:
        credential = win32cred.CredRead(
            target,
            win32cred.CRED_TYPE_GENERIC,
            0,
        )
    except Exception as exc:
        if _credential_error_code(exc) in {2, 1168}:
            return None
        raise WorkerConfigurationError("worker credential could not be read") from exc
    return _validate_secret(_decode_credential_blob(credential.get("CredentialBlob")))


def _env_int(
    environment: Mapping[str, str],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = str(environment.get(name, default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise WorkerConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise WorkerConfigurationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _env_float(
    environment: Mapping[str, str],
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = str(environment.get(name, default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise WorkerConfigurationError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise WorkerConfigurationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _optional_root(environment: Mapping[str, str], name: str) -> Path | None:
    raw = str(environment.get(name, "")).strip()
    return Path(raw).expanduser() if raw else None


def _default_worker_dir(environment: Mapping[str, str]) -> Path:
    local_app_data = str(environment.get("LOCALAPPDATA", "")).strip()
    if local_app_data:
        return Path(local_app_data).expanduser() / "Alpecca" / "rog-worker"
    return Path.home() / "AppData" / "Local" / "Alpecca" / "rog-worker"


def _configured_path(
    environment: Mapping[str, str],
    name: str,
    default: Path,
) -> Path:
    raw = str(environment.get(name, "")).strip()
    return Path(raw).expanduser() if raw else default


def _validated_tls_file(
    path: Path | None,
    label: str,
    *,
    private_key: bool = False,
) -> Path:
    if path is None:
        raise WorkerConfigurationError(f"{label} is required for LAN mode")
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError:
        raise WorkerConfigurationError(f"{label} was not found") from None
    if not resolved.is_file():
        raise WorkerConfigurationError(f"{label} is not a file")
    if private_key:
        repository_root = Path(__file__).resolve().parents[1]
        try:
            resolved.relative_to(repository_root)
        except ValueError:
            pass
        else:
            raise WorkerConfigurationError(
                "ROG TLS private key cannot be stored in the repository"
            )
    return resolved


def _model_allowlist(environment: Mapping[str, str]) -> frozenset[str]:
    raw = str(
        environment.get(
            "ALPECCA_ROG_WORKER_ALLOWED_MODELS",
            environment.get("ALPECCA_ROG_WORKER_MODELS", DEFAULT_MODELS),
        )
    )
    models = frozenset(item.strip() for item in raw.split(",") if item.strip())
    if not models or len(models) > 16:
        raise WorkerConfigurationError("worker model allowlist must contain 1 to 16 models")
    if any(not MODEL_RE.fullmatch(model) for model in models):
        raise WorkerConfigurationError("worker model allowlist contains an invalid model")
    return models


def _loopback_ollama_route(url: str, route: str) -> tuple[str, int, str]:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.username or parsed.password:
        raise WorkerConfigurationError("Ollama URL must be unauthenticated loopback HTTP")
    if parsed.query or parsed.fragment:
        raise WorkerConfigurationError("Ollama URL cannot contain a query or fragment")
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise WorkerConfigurationError("Ollama URL must use a literal loopback address") from exc
    if not address.is_loopback:
        raise WorkerConfigurationError("Ollama URL must remain on loopback")
    try:
        port = int(parsed.port or 80)
    except ValueError as exc:
        raise WorkerConfigurationError("Ollama URL contains an invalid port") from exc
    if not 1 <= port <= 65535:
        raise WorkerConfigurationError("Ollama port is outside the valid range")
    base_path = parsed.path.rstrip("/")
    return str(address), port, f"{base_path}/api/{route}"


def _loopback_ollama_parts(url: str) -> tuple[str, int, str]:
    return _loopback_ollama_route(url, "chat")


def _validated_bind_host(host: str, allow_lan: bool) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise WorkerConfigurationError("worker bind host must be a literal IP address") from exc
    if not address.is_loopback and not allow_lan:
        raise WorkerConfigurationError(
            "non-loopback binding requires ALPECCA_ROG_WORKER_ALLOW_LAN=1"
        )
    return str(address)


def _blender_child_environment(
    source: Mapping[str, str],
    secret: bytes | None,
) -> dict[str, str]:
    """Build a minimal child environment without Alpecca authority material."""

    secret_text = ""
    if secret:
        try:
            secret_text = secret.decode("utf-8")
        except UnicodeDecodeError:
            secret_text = ""
    child: dict[str, str] = {}
    for key, value in source.items():
        if key.upper() not in _BLENDER_CHILD_ENV_ALLOWLIST:
            continue
        clean_value = str(value)
        if "\x00" in clean_value or (secret_text and secret_text in clean_value):
            continue
        child[str(key)] = clean_value
    child["PYTHONNOUSERSITE"] = "1"
    return child


@dataclass(frozen=True)
class WorkerSettings:
    """Server-owned policy and limits; request bodies cannot override these."""

    secret: bytes | None = field(default=None, repr=False)
    model_allowlist: frozenset[str] = field(
        default_factory=lambda: frozenset({"qwen3.5:9b"})
    )
    ollama_url: str = DEFAULT_OLLAMA_URL
    blender_executable: str = "blender"
    blend_root: Path | None = None
    output_root: Path | None = None
    max_concurrency: int = 1
    max_body_bytes: int = 65_536
    max_prompt_chars: int = 32 * 1024
    max_system_chars: int = 8 * 1024
    max_history_messages: int = 32
    max_history_chars: int = 12 * 1024
    max_result_chars: int = 32 * 1024
    max_ollama_response_bytes: int = 512 * 1024
    max_render_bytes: int = 128 * 1024 * 1024
    max_tokens: int = 2_048
    ollama_num_ctx: int = 8_192
    reason_timeout_seconds: float = 120.0
    render_timeout_seconds: float = 600.0
    hyfuser_timeout_seconds: float = 8.0
    timestamp_skew_seconds: int = 90
    idempotency_ttl_seconds: int = 3_600
    idempotency_entries: int = 128
    bind_host: str = "127.0.0.1"
    bind_port: int = DEFAULT_PORT
    allow_lan: bool = False
    tls_cert_path: Path | None = None
    tls_key_path: Path | None = field(default=None, repr=False)
    replay_db_path: Path | None = None

    def __post_init__(self) -> None:
        if self.secret is not None and not 32 <= len(self.secret) <= 512:
            raise WorkerConfigurationError("worker credential must contain 32 to 512 bytes")
        if not self.model_allowlist or len(self.model_allowlist) > 16:
            raise WorkerConfigurationError("worker model allowlist is invalid")
        if any(not MODEL_RE.fullmatch(model) for model in self.model_allowlist):
            raise WorkerConfigurationError("worker model allowlist contains an invalid model")
        _loopback_ollama_parts(self.ollama_url)
        _validated_bind_host(self.bind_host, self.allow_lan)
        if self.allow_lan:
            _validated_tls_file(self.tls_cert_path, TLS_CERT_ENV)
            _validated_tls_file(
                self.tls_key_path,
                TLS_KEY_ENV,
                private_key=True,
            )
            if self.replay_db_path is None:
                raise WorkerConfigurationError(
                    f"{REPLAY_DB_ENV} is required for LAN mode"
                )
        bounded_values = (
            (self.max_concurrency, 1, 4, "max_concurrency"),
            (self.max_body_bytes, 1_024, 262_144, "max_body_bytes"),
            (self.max_prompt_chars, 1, 131_072, "max_prompt_chars"),
            (self.max_system_chars, 0, 32_768, "max_system_chars"),
            (self.max_history_messages, 0, 64, "max_history_messages"),
            (self.max_history_chars, 1, 32_768, "max_history_chars"),
            (self.max_result_chars, 1, 131_072, "max_result_chars"),
            (self.max_ollama_response_bytes, 1_024, 1_048_576, "max_ollama_response_bytes"),
            (self.max_render_bytes, 1_024, 2 * 1024 * 1024 * 1024, "max_render_bytes"),
            (self.max_tokens, 1, 8_192, "max_tokens"),
            (self.ollama_num_ctx, 1_024, 8_192, "ollama_num_ctx"),
            (self.timestamp_skew_seconds, 10, 300, "timestamp_skew_seconds"),
            (self.idempotency_ttl_seconds, 60, 86_400, "idempotency_ttl_seconds"),
            (self.idempotency_entries, 8, 1_024, "idempotency_entries"),
            (self.bind_port, 1, 65_535, "bind_port"),
        )
        for value, minimum, maximum, label in bounded_values:
            if not minimum <= int(value) <= maximum:
                raise WorkerConfigurationError(f"{label} is outside its safe range")
        for value, minimum, maximum, label in (
            (self.reason_timeout_seconds, 1.0, 600.0, "reason_timeout_seconds"),
            (self.render_timeout_seconds, 5.0, 1_800.0, "render_timeout_seconds"),
            (self.hyfuser_timeout_seconds, 0.2, 15.0, "hyfuser_timeout_seconds"),
        ):
            if not math.isfinite(float(value)) or not minimum <= float(value) <= maximum:
                raise WorkerConfigurationError(f"{label} is outside its safe range")

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> "WorkerSettings":
        env = os.environ if environment is None else environment
        allow_lan = str(env.get("ALPECCA_ROG_WORKER_ALLOW_LAN", "0")).strip() == "1"
        bind_host = _validated_bind_host(
            str(env.get("ALPECCA_ROG_WORKER_BIND", "127.0.0.1")).strip(),
            allow_lan,
        )
        worker_dir = _default_worker_dir(env)
        tls_dir = worker_dir / "tls"
        return cls(
            secret=load_worker_secret(env),
            model_allowlist=_model_allowlist(env),
            ollama_url=str(
                env.get("ALPECCA_ROG_WORKER_OLLAMA_URL", DEFAULT_OLLAMA_URL)
            ).strip(),
            blender_executable=str(
                env.get("ALPECCA_ROG_WORKER_BLENDER_EXE", "blender")
            ).strip(),
            blend_root=_optional_root(env, "ALPECCA_ROG_WORKER_BLEND_ROOT"),
            output_root=_optional_root(env, "ALPECCA_ROG_WORKER_OUTPUT_ROOT"),
            max_concurrency=_env_int(env, "ALPECCA_ROG_WORKER_CONCURRENCY", 1, 1, 4),
            max_body_bytes=_env_int(env, "ALPECCA_ROG_WORKER_MAX_BODY", 65_536, 1_024, 262_144),
            max_prompt_chars=_env_int(env, "ALPECCA_ROG_WORKER_MAX_PROMPT", 32 * 1024, 1, 131_072),
            max_system_chars=_env_int(env, "ALPECCA_ROG_WORKER_MAX_SYSTEM", 8 * 1024, 0, 32_768),
            max_history_messages=_env_int(env, "ALPECCA_ROG_WORKER_MAX_HISTORY", 32, 0, 64),
            max_history_chars=_env_int(env, "ALPECCA_ROG_WORKER_MAX_HISTORY_MESSAGE", 12 * 1024, 1, 32_768),
            max_result_chars=_env_int(env, "ALPECCA_ROG_WORKER_MAX_RESULT", 32 * 1024, 1, 131_072),
            max_ollama_response_bytes=_env_int(
                env, "ALPECCA_ROG_WORKER_MAX_OLLAMA_RESPONSE", 512 * 1024, 1_024, 1_048_576
            ),
            max_render_bytes=_env_int(
                env, "ALPECCA_ROG_WORKER_MAX_RENDER", 128 * 1024 * 1024, 1_024, 2 * 1024 * 1024 * 1024
            ),
            max_tokens=_env_int(env, "ALPECCA_ROG_WORKER_MAX_TOKENS", 2_048, 1, 8_192),
            ollama_num_ctx=_env_int(env, "ALPECCA_ROG_WORKER_NUM_CTX", 8_192, 1_024, 8_192),
            reason_timeout_seconds=_env_float(
                env, "ALPECCA_ROG_WORKER_REASON_TIMEOUT", 120.0, 1.0, 600.0
            ),
            render_timeout_seconds=_env_float(
                env, "ALPECCA_ROG_WORKER_RENDER_TIMEOUT", 600.0, 5.0, 1_800.0
            ),
            hyfuser_timeout_seconds=_env_float(
                env, "ALPECCA_ROG_WORKER_HYFUSER_TIMEOUT_SECONDS", 8.0, 0.2, 15.0
            ),
            timestamp_skew_seconds=_env_int(
                env, "ALPECCA_ROG_WORKER_TIMESTAMP_SKEW", 90, 10, 300
            ),
            idempotency_ttl_seconds=_env_int(
                env, "ALPECCA_ROG_WORKER_IDEMPOTENCY_TTL", 3_600, 60, 86_400
            ),
            idempotency_entries=_env_int(
                env, "ALPECCA_ROG_WORKER_IDEMPOTENCY_ENTRIES", 128, 8, 1_024
            ),
            bind_host=bind_host,
            bind_port=_env_int(env, "ALPECCA_ROG_WORKER_PORT", DEFAULT_PORT, 1, 65_535),
            allow_lan=allow_lan,
            tls_cert_path=_configured_path(
                env,
                TLS_CERT_ENV,
                tls_dir / "jason-holyrog.crt",
            ),
            tls_key_path=_configured_path(
                env,
                TLS_KEY_ENV,
                tls_dir / "jason-holyrog.key",
            ),
            replay_db_path=_configured_path(
                env,
                REPLAY_DB_ENV,
                worker_dir / "worker-ops.sqlite3",
            ),
        )


def canonical_request(
    method: str,
    path: str,
    timestamp: int | str,
    nonce: str,
    body_sha256: str,
) -> bytes:
    """Match the client lane's exact five-line canonical representation."""

    return "\n".join(
        (method.upper(), path, str(timestamp), nonce, body_sha256)
    ).encode("ascii")


def sign_request(
    secret: bytes | str,
    method: str,
    path: str,
    timestamp: int | str,
    nonce: str,
    body: bytes,
) -> str:
    key = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    body_hash = hashlib.sha256(body).hexdigest()
    return hmac.new(
        key,
        canonical_request(method, path, timestamp, nonce, body_hash),
        hashlib.sha256,
    ).hexdigest()


def _json_with_no_duplicates(body: bytes) -> dict[str, Any]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkerRequestError(400, "invalid_utf8") from exc

    def object_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise WorkerRequestError(400, "duplicate_json_key")
            result[key] = value
        return result

    def invalid_constant(_value: str) -> None:
        raise WorkerRequestError(400, "invalid_json_number")

    try:
        value = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=invalid_constant,
        )
    except WorkerRequestError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise WorkerRequestError(400, "invalid_json") from exc
    if not isinstance(value, dict):
        raise WorkerRequestError(422, "json_object_required")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    keys = frozenset(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise WorkerRequestError(422, "invalid_contract_fields")


def _request_id(value: object) -> str:
    if not isinstance(value, str) or not REQUEST_ID_RE.fullmatch(value):
        raise WorkerRequestError(422, "invalid_request_id")
    return value


def _bounded_text(value: object, *, maximum: int, label: str, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise WorkerRequestError(422, f"invalid_{label}")
    if "\x00" in value or (not allow_empty and not value.strip()):
        raise WorkerRequestError(422, f"invalid_{label}")
    if len(value.encode("utf-8")) > maximum:
        raise WorkerRequestError(413, f"{label}_too_large")
    return value


@dataclass(frozen=True)
class ReasoningJob:
    request_id: str
    model: str
    system_prompt: str
    user_prompt: str
    history: tuple[tuple[str, str], ...]
    max_tokens: int


@dataclass(frozen=True)
class BlenderJob:
    request_id: str
    project: str
    frame: int


@dataclass(frozen=True)
class HyfuserJob:
    request_id: str
    text_emotion: tuple[float, ...]
    speech_emotion: tuple[float, ...]


def _emotion_vector(value: object, label: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != HYFUSER_VECTOR_DIM:
        raise WorkerRequestError(422, f"invalid_{label}")
    cleaned: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise WorkerRequestError(422, f"invalid_{label}")
        number = float(item)
        if not math.isfinite(number) or not -1.0 <= number <= 1.0:
            raise WorkerRequestError(422, f"invalid_{label}")
        cleaned.append(number)
    return tuple(cleaned)


def _hyfuser_job(payload: Mapping[str, Any]) -> HyfuserJob:
    _exact_keys(
        payload,
        frozenset(
            {
                "schema",
                "request_id",
                "mode",
                "text_emotion",
                "speech_emotion",
            }
        ),
    )
    if payload["schema"] != HYFUSER_REQUEST_SCHEMA or payload["mode"] != "shadow":
        raise WorkerRequestError(422, "invalid_schema")
    return HyfuserJob(
        request_id=_request_id(payload["request_id"]),
        text_emotion=_emotion_vector(payload["text_emotion"], "text_emotion"),
        speech_emotion=_emotion_vector(
            payload["speech_emotion"], "speech_emotion"
        ),
    )


def _reasoning_job(payload: Mapping[str, Any], settings: WorkerSettings) -> ReasoningJob:
    _exact_keys(
        payload,
        frozenset(
            {
                "schema",
                "request_id",
                "system_prompt",
                "user_prompt",
                "history",
                "model",
                "max_tokens",
            }
        ),
    )
    if payload["schema"] != REASON_REQUEST_SCHEMA:
        raise WorkerRequestError(422, "invalid_schema")
    model = payload["model"]
    if not isinstance(model, str) or model not in settings.model_allowlist:
        raise WorkerRequestError(403, "model_not_allowed")
    max_tokens = payload["max_tokens"]
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
        raise WorkerRequestError(422, "invalid_max_tokens")
    if not 1 <= max_tokens <= settings.max_tokens:
        raise WorkerRequestError(422, "invalid_max_tokens")
    history_value = payload["history"]
    if (
        not isinstance(history_value, list)
        or len(history_value) > settings.max_history_messages
    ):
        raise WorkerRequestError(422, "invalid_history")
    history: list[tuple[str, str]] = []
    for message in history_value:
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise WorkerRequestError(422, "invalid_history")
        role = message.get("role")
        if role not in {"user", "assistant"}:
            raise WorkerRequestError(422, "invalid_history")
        history.append(
            (
                role,
                _bounded_text(
                    message.get("content"),
                    maximum=settings.max_history_chars,
                    label="history",
                    allow_empty=True,
                ),
            )
        )
    return ReasoningJob(
        request_id=_request_id(payload["request_id"]),
        model=model,
        user_prompt=_bounded_text(
            payload["user_prompt"],
            maximum=settings.max_prompt_chars,
            label="user_prompt",
            allow_empty=False,
        ),
        system_prompt=_bounded_text(
            payload["system_prompt"],
            maximum=settings.max_system_chars,
            label="system_prompt",
            allow_empty=True,
        ),
        history=tuple(history),
        max_tokens=max_tokens,
    )


def _blender_job(payload: Mapping[str, Any]) -> BlenderJob:
    _exact_keys(payload, frozenset({"schema", "request_id", "project", "frame"}))
    if payload["schema"] != BLENDER_REQUEST_SCHEMA:
        raise WorkerRequestError(422, "invalid_schema")
    project = payload["project"]
    if (
        not isinstance(project, str)
        or not BLEND_NAME_RE.fullmatch(project)
        or Path(project).name != project
        or "/" in project
        or "\\" in project
        or ":" in project
    ):
        raise WorkerRequestError(422, "invalid_project")
    frame = payload["frame"]
    if isinstance(frame, bool) or not isinstance(frame, int) or not 1 <= frame <= 999_999:
        raise WorkerRequestError(422, "invalid_frame")
    return BlenderJob(
        request_id=_request_id(payload["request_id"]),
        project=project,
        frame=frame,
    )


@dataclass
class _IdempotencyRecord:
    endpoint: str
    body_hash: str
    started_at: float
    completed_at: float | None = None
    status_code: int | None = None
    response: dict[str, Any] | None = None


class _IdempotencyStore:
    def __init__(self, ttl_seconds: int, max_entries: int, clock: Callable[[], float]) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._records: dict[str, _IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def _clean_locked(self, now: float) -> None:
        expired = [
            request_id
            for request_id, record in self._records.items()
            if record.completed_at is not None
            and now - record.completed_at > self._ttl_seconds
        ]
        for request_id in expired:
            self._records.pop(request_id, None)
        if len(self._records) < self._max_entries:
            return
        completed = sorted(
            (
                (record.completed_at, request_id)
                for request_id, record in self._records.items()
                if record.completed_at is not None
            ),
            key=lambda item: item[0] or 0.0,
        )
        while len(self._records) >= self._max_entries and completed:
            _, request_id = completed.pop(0)
            self._records.pop(request_id, None)

    def lookup(
        self, request_id: str, endpoint: str, body_hash: str
    ) -> tuple[str, _IdempotencyRecord | None]:
        with self._lock:
            self._clean_locked(self._clock())
            record = self._records.get(request_id)
            if record is None:
                return "new", None
            if record.endpoint != endpoint or record.body_hash != body_hash:
                return "conflict", record
            return ("complete" if record.completed_at is not None else "running"), record

    def begin(self, request_id: str, endpoint: str, body_hash: str) -> str:
        with self._lock:
            now = self._clock()
            self._clean_locked(now)
            record = self._records.get(request_id)
            if record is not None:
                if record.endpoint != endpoint or record.body_hash != body_hash:
                    return "conflict"
                return "complete" if record.completed_at is not None else "running"
            if len(self._records) >= self._max_entries:
                return "full"
            self._records[request_id] = _IdempotencyRecord(endpoint, body_hash, now)
            return "started"

    def complete(
        self,
        request_id: str,
        status_code: int,
        response: Mapping[str, Any],
    ) -> None:
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return
            record.completed_at = self._clock()
            record.status_code = int(status_code)
            record.response = dict(response)


class _NonceStore:
    def __init__(
        self,
        ttl_seconds: int,
        max_entries: int,
        clock: Callable[[], float],
        database_path: Path | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._database_path = database_path
        self._nonces: dict[str, float] = {}
        self._lock = threading.Lock()

    def _accept_memory(self, nonce: str, now: float) -> str:
        self._nonces = {
            value: seen
            for value, seen in self._nonces.items()
            if now - seen <= self._ttl_seconds
        }
        if nonce in self._nonces:
            return "replay"
        if len(self._nonces) >= self._max_entries:
            return "full"
        self._nonces[nonce] = now
        return "accepted"

    def _accept_sqlite(self, nonce: str, now: float) -> str:
        assert self._database_path is not None
        try:
            path = self._database_path.expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                str(path),
                timeout=2.0,
                isolation_level=None,
            )
            try:
                connection.execute("PRAGMA busy_timeout=2000")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS replay_nonces ("
                    "nonce TEXT PRIMARY KEY NOT NULL, "
                    "seen_at REAL NOT NULL, "
                    "expires_at REAL NOT NULL"
                    ") WITHOUT ROWID"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS replay_nonces_expiry "
                    "ON replay_nonces(expires_at)"
                )
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "DELETE FROM replay_nonces WHERE expires_at < ?",
                    (now,),
                )
                if connection.execute(
                    "SELECT 1 FROM replay_nonces WHERE nonce = ?",
                    (nonce,),
                ).fetchone() is not None:
                    connection.execute("ROLLBACK")
                    return "replay"
                count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM replay_nonces"
                    ).fetchone()[0]
                )
                if count >= self._max_entries:
                    connection.execute("ROLLBACK")
                    return "full"
                connection.execute(
                    "INSERT INTO replay_nonces(nonce, seen_at, expires_at) "
                    "VALUES (?, ?, ?)",
                    (nonce, now, now + self._ttl_seconds),
                )
                connection.execute("COMMIT")
                return "accepted"
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            return "unavailable"

    def accept(self, nonce: str) -> str:
        with self._lock:
            now = self._clock()
            if self._database_path is None:
                return self._accept_memory(nonce, now)
            return self._accept_sqlite(nonce, now)


ConnectionFactory = Callable[..., Any]
ProcessRunner = Callable[..., Any]
AuditSink = Callable[[Mapping[str, Any]], None]


def _load_hyfuser_backend(
    environment: Mapping[str, str] | None = None,
) -> object | None:
    """Load one fixed optional runtime only after verifying external weights."""

    env = os.environ if environment is None else environment
    raw_path = str(env.get(HYFUSER_WEIGHTS_ENV, "")).strip()
    expected_digest = str(env.get(HYFUSER_WEIGHTS_SHA256_ENV, "")).strip()
    if (
        str(env.get(HYFUSER_MODE_ENV, "")).strip() != "shadow-only"
        or not raw_path
        or not HEX_SHA256_RE.fullmatch(expected_digest)
    ):
        return None
    try:
        weights = Path(raw_path).expanduser().resolve(strict=True)
        repository = Path(__file__).resolve().parents[1]
        weights.relative_to(repository)
        return None
    except ValueError:
        pass
    except OSError:
        return None
    try:
        size = weights.stat().st_size
    except OSError:
        return None
    if not weights.is_file() or size <= 0 or size > 8 * 1024 * 1024 * 1024:
        return None
    digest = hashlib.sha256()
    try:
        with weights.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError:
        return None
    if not hmac.compare_digest(digest.hexdigest(), expected_digest):
        return None
    try:
        module = importlib.import_module(HYFUSER_RUNTIME_MODULE)
        factory = getattr(module, "create_backend", None)
        if not callable(factory):
            return None
        return factory(
            weights_path=str(weights),
            weights_sha256=expected_digest,
            architecture=HYFUSER_ARCHITECTURE,
            perspectives=HYFUSER_PERSPECTIVES,
            text_emotion_dim=HYFUSER_VECTOR_DIM,
            speech_emotion_dim=HYFUSER_VECTOR_DIM,
        )
    except Exception:
        return None


def _hyfuser_readiness(backend: object | None) -> dict[str, Any] | None:
    if backend is None:
        return None
    probe = getattr(backend, "probe", None)
    if not callable(probe):
        return None
    try:
        value = probe()
    except Exception:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "ready",
        "architecture",
        "runtime_id",
        "weights_sha256",
        "perspectives",
        "text_emotion_dim",
        "speech_emotion_dim",
    }:
        return None
    if value.get("ready") is not True:
        return None
    if value.get("architecture") != HYFUSER_ARCHITECTURE:
        return None
    if tuple(value.get("perspectives", ())) != HYFUSER_PERSPECTIVES:
        return None
    if (
        value.get("text_emotion_dim") != HYFUSER_VECTOR_DIM
        or value.get("speech_emotion_dim") != HYFUSER_VECTOR_DIM
    ):
        return None
    runtime_id = value.get("runtime_id")
    weights_sha256 = value.get("weights_sha256")
    if (
        not isinstance(runtime_id, str)
        or not SAFE_RUNTIME_RE.fullmatch(runtime_id)
        or not isinstance(weights_sha256, str)
        or not HEX_SHA256_RE.fullmatch(weights_sha256)
    ):
        return None
    return {
        "runtime_id": runtime_id,
        "weights_sha256": weights_sha256,
    }


class ROGComputeWorker:
    def __init__(
        self,
        settings: WorkerSettings,
        *,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        connection_factory: ConnectionFactory = http.client.HTTPConnection,
        process_runner: ProcessRunner = subprocess.run,
        audit_sink: AuditSink | None = None,
        hyfuser_backend: object | None = None,
    ) -> None:
        self.settings = settings
        self._clock = clock
        self._monotonic = monotonic
        self._connection_factory = connection_factory
        self._process_runner = process_runner
        self._audit_sink = audit_sink
        self._hyfuser_backend = (
            hyfuser_backend
            if hyfuser_backend is not None
            else _load_hyfuser_backend()
        )
        self._slots = threading.BoundedSemaphore(settings.max_concurrency)
        self._nonces = _NonceStore(
            settings.timestamp_skew_seconds * 2,
            # Health checks are authenticated too. Keep enough live nonces for
            # several clients polling throughout the complete timestamp-skew
            # window without weakening replay rejection or evicting live rows.
            max(4_096, settings.idempotency_entries * 4),
            clock,
            settings.replay_db_path,
        )
        self._idempotency = _IdempotencyStore(
            settings.idempotency_ttl_seconds,
            settings.idempotency_entries,
            clock,
        )

    def _audit(
        self,
        event: str,
        status: str,
        *,
        request_id: str | None = None,
        duration_ms: int | None = None,
        **metadata: int | float | bool | str,
    ) -> None:
        observation: dict[str, Any] = {
            "schema": "alpecca.rog-worker-observation.v1",
            "event": event,
            "status": status,
        }
        if request_id:
            observation["request_ref"] = hashlib.sha256(
                request_id.encode("utf-8")
            ).hexdigest()[:16]
        if duration_ms is not None:
            observation["duration_ms"] = max(0, int(duration_ms))
        observation.update(metadata)
        if self._audit_sink is not None:
            self._audit_sink(observation)
        else:
            LOGGER.info("rog_worker_observation %s", json.dumps(observation, sort_keys=True))

    def health(self, request_id: str) -> dict[str, Any]:
        blender_ready = self._blender_configuration() is not None
        reasoning_ready = self._ollama_reasoning_ready()
        ready = reasoning_ready or blender_ready
        return {
            "schema": HEALTH_SCHEMA,
            "ok": True,
            "request_id": request_id,
            "hostname": socket.gethostname(),
            "role": "compute-only",
            "ready": ready,
            "speaking": False,
            "discord": False,
            "capabilities": {
                "reasoning": {"ready": reasoning_ready},
                "blender": {"ready": blender_ready},
            },
        }

    def hyfuser_health(self, request_id: str) -> dict[str, Any]:
        readiness = _hyfuser_readiness(self._hyfuser_backend)
        ready = readiness is not None
        return {
            "schema": HYFUSER_HEALTH_SCHEMA,
            "ok": True,
            "request_id": request_id,
            "ready": ready,
            "state": "ready" if ready else "unavailable",
            "architecture": HYFUSER_ARCHITECTURE,
            "perspectives": list(HYFUSER_PERSPECTIVES),
            "advisory": True,
            "shadow_only": True,
            "speaking": False,
            "state_mutation": False,
        }

    def run_hyfuser(self, job: HyfuserJob) -> dict[str, Any]:
        readiness = _hyfuser_readiness(self._hyfuser_backend)
        if readiness is None:
            raise WorkerRequestError(503, "hyfuser_unavailable")
        infer = getattr(self._hyfuser_backend, "infer", None)
        if not callable(infer):
            raise WorkerRequestError(503, "hyfuser_unavailable")
        started = self._monotonic()
        try:
            output = infer(
                text_emotion=job.text_emotion,
                speech_emotion=job.speech_emotion,
                timeout_seconds=self.settings.hyfuser_timeout_seconds,
            )
        except TimeoutError as exc:
            raise WorkerRequestError(504, "hyfuser_timeout") from exc
        except Exception as exc:
            raise WorkerRequestError(502, "hyfuser_inference_failed") from exc
        if not isinstance(output, Mapping) or set(output) != {
            "scores", "confidences", "runtime_id", "weights_sha256"
        }:
            raise WorkerRequestError(502, "hyfuser_invalid_response")
        if (
            output.get("runtime_id") != readiness["runtime_id"]
            or output.get("weights_sha256") != readiness["weights_sha256"]
        ):
            raise WorkerRequestError(502, "hyfuser_provenance_mismatch")
        scores = output.get("scores")
        confidences = output.get("confidences")
        if (
            not isinstance(scores, (list, tuple))
            or not isinstance(confidences, (list, tuple))
            or len(scores) != len(HYFUSER_PERSPECTIVES)
            or len(confidences) != len(HYFUSER_PERSPECTIVES)
        ):
            raise WorkerRequestError(502, "hyfuser_invalid_response")
        heads: list[dict[str, Any]] = []
        for name, raw_score, raw_confidence in zip(
            HYFUSER_PERSPECTIVES, scores, confidences, strict=True
        ):
            if (
                isinstance(raw_score, bool)
                or not isinstance(raw_score, (int, float))
                or isinstance(raw_confidence, bool)
                or not isinstance(raw_confidence, (int, float))
            ):
                raise WorkerRequestError(502, "hyfuser_invalid_response")
            score = float(raw_score)
            confidence = float(raw_confidence)
            if (
                not math.isfinite(score)
                or not -1.0 <= score <= 1.0
                or not math.isfinite(confidence)
                or not 0.0 <= confidence <= 1.0
            ):
                raise WorkerRequestError(502, "hyfuser_invalid_response")
            heads.append(
                {"name": name, "score": score, "confidence": confidence}
            )
        return {
            "schema": HYFUSER_RESPONSE_SCHEMA,
            "ok": True,
            "request_id": job.request_id,
            "result": {
                "architecture": HYFUSER_ARCHITECTURE,
                "heads": heads,
                "provenance": {
                    "runtime_id": readiness["runtime_id"],
                    "weights_sha256": readiness["weights_sha256"],
                    "input_dimensions": {
                        "text_emotion": HYFUSER_VECTOR_DIM,
                        "speech_emotion": HYFUSER_VECTOR_DIM,
                    },
                },
                "elapsed_ms": max(
                    0, int((self._monotonic() - started) * 1000)
                ),
                "advisory": True,
                "shadow_only": True,
                "speaking": False,
                "state_mutation": False,
            },
        }

    def _ollama_reasoning_ready(self) -> bool:
        """Confirm one allowed model is installed without exposing inventory."""

        host, port, path = _loopback_ollama_route(
            self.settings.ollama_url,
            "tags",
        )
        connection = None
        try:
            connection = self._connection_factory(
                host,
                port,
                timeout=min(2.0, self.settings.reason_timeout_seconds),
            )
            connection.request(
                "GET",
                path,
                headers={"Accept": "application/json"},
            )
            response = connection.getresponse()
            raw = response.read(min(self.settings.max_ollama_response_bytes, 131_072) + 1)
            if int(getattr(response, "status", 500)) != 200:
                return False
            if len(raw) > min(self.settings.max_ollama_response_bytes, 131_072):
                return False
            decoded = json.loads(raw.decode("utf-8", errors="strict"))
            models = decoded.get("models") if isinstance(decoded, Mapping) else None
            if not isinstance(models, list) or len(models) > 512:
                return False
            for model in models:
                if not isinstance(model, Mapping):
                    continue
                for field_name in ("name", "model"):
                    name = model.get(field_name)
                    if isinstance(name, str) and name in self.settings.model_allowlist:
                        return True
            return False
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            TimeoutError,
            OSError,
            http.client.HTTPException,
        ):
            return False
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def authenticate(self, request: Request, body: bytes) -> str:
        if self.settings.secret is None:
            self._audit("authentication", "unconfigured")
            raise WorkerRequestError(503, "authentication_not_configured")
        timestamp_text = str(request.headers.get(TIMESTAMP_HEADER, ""))
        nonce = str(request.headers.get(NONCE_HEADER, ""))
        body_hash = str(request.headers.get(BODY_SHA256_HEADER, ""))
        signature = str(request.headers.get(SIGNATURE_HEADER, ""))
        request_id = str(request.headers.get(REQUEST_ID_HEADER, ""))
        if (
            not timestamp_text.isascii()
            or not timestamp_text.isdigit()
            or not 1 <= len(timestamp_text) <= 16
            or int(timestamp_text) <= 0
            or not NONCE_RE.fullmatch(nonce)
        ):
            self._audit("authentication", "rejected")
            raise WorkerRequestError(401, "invalid_authentication")
        if not REQUEST_ID_RE.fullmatch(request_id):
            self._audit("authentication", "rejected")
            raise WorkerRequestError(401, "invalid_authentication")
        if not HEX_SHA256_RE.fullmatch(body_hash) or not HEX_SHA256_RE.fullmatch(signature):
            self._audit("authentication", "rejected")
            raise WorkerRequestError(401, "invalid_authentication")
        if not hmac.compare_digest(body_hash, hashlib.sha256(body).hexdigest()):
            self._audit("authentication", "rejected")
            raise WorkerRequestError(401, "body_hash_mismatch")
        timestamp = int(timestamp_text)
        if abs(self._clock() - timestamp) > self.settings.timestamp_skew_seconds:
            self._audit("authentication", "stale")
            raise WorkerRequestError(401, "stale_request")
        expected = sign_request(
            self.settings.secret,
            request.method,
            request.url.path,
            timestamp_text,
            nonce,
            body,
        )
        if not hmac.compare_digest(expected, signature):
            self._audit("authentication", "rejected")
            raise WorkerRequestError(401, "invalid_authentication")
        replay_state = self._nonces.accept(nonce)
        if replay_state == "replay":
            self._audit("authentication", "replay")
            raise WorkerRequestError(409, "nonce_replay")
        if replay_state != "accepted":
            self._audit("authentication", "replay_store_unavailable")
            raise WorkerRequestError(503, "replay_protection_unavailable")
        return request_id

    def _blender_configuration(self) -> tuple[str, Path, Path] | None:
        if self.settings.blend_root is None or self.settings.output_root is None:
            return None
        try:
            blend_root = self.settings.blend_root.resolve(strict=True)
            output_root = self.settings.output_root.resolve(strict=True)
        except OSError:
            return None
        if not blend_root.is_dir() or not output_root.is_dir():
            return None
        executable = self.settings.blender_executable
        if Path(executable).parent != Path("."):
            try:
                resolved_executable = Path(executable).resolve(strict=True)
            except OSError:
                return None
            if not resolved_executable.is_file():
                return None
            executable = str(resolved_executable)
        else:
            found = shutil.which(executable)
            if not found:
                return None
            executable = found
        return executable, blend_root, output_root

    def run_reasoning(self, job: ReasoningJob) -> dict[str, Any]:
        started = self._monotonic()
        host, port, path = _loopback_ollama_parts(self.settings.ollama_url)
        messages: list[dict[str, str]] = []
        if job.system_prompt:
            messages.append({"role": "system", "content": job.system_prompt})
        messages.extend(
            {"role": role, "content": content} for role, content in job.history
        )
        messages.append({"role": "user", "content": job.user_prompt})
        upstream_body = json.dumps(
            {
                "model": job.model,
                "messages": messages,
                "stream": False,
                # The endpoint returns only the bounded visible conclusion and
                # never exposes chain-of-thought. Asking Ollama for a separate
                # thinking field can consume the full prediction budget and
                # leave Qwen with no visible answer, so deliberation remains
                # internal to the model invocation.
                "think": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": job.max_tokens,
                    "num_ctx": self.settings.ollama_num_ctx,
                },
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        connection = None
        try:
            connection = self._connection_factory(
                host,
                port,
                timeout=self.settings.reason_timeout_seconds,
            )
            connection.request(
                "POST",
                path,
                body=upstream_body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            response = connection.getresponse()
            raw = response.read(self.settings.max_ollama_response_bytes + 1)
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            raise WorkerRequestError(504, "reasoning_unavailable") from exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
        if len(raw) > self.settings.max_ollama_response_bytes:
            raise WorkerRequestError(502, "reasoning_response_too_large")
        if int(getattr(response, "status", 500)) != 200:
            raise WorkerRequestError(502, "reasoning_upstream_error")
        try:
            decoded = json.loads(raw.decode("utf-8"))
            result = decoded["message"]["content"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise WorkerRequestError(502, "reasoning_invalid_response") from exc
        if not isinstance(result, str):
            raise WorkerRequestError(502, "reasoning_invalid_response")
        encoded_result = result.encode("utf-8")
        if not result.strip():
            raise WorkerRequestError(502, "reasoning_no_visible_content")
        if len(encoded_result) > self.settings.max_result_chars:
            raise WorkerRequestError(502, "reasoning_result_too_large")
        visible: dict[str, Any] = {
            "model": job.model,
            "text": result,
            "elapsed_ms": max(0, int((self._monotonic() - started) * 1000)),
        }
        for source, target in (
            ("prompt_eval_count", "prompt_tokens"),
            ("eval_count", "completion_tokens"),
        ):
            count = decoded.get(source)
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                visible[target] = count
        return {
            "schema": REASON_RESPONSE_SCHEMA,
            "ok": True,
            "request_id": job.request_id,
            "result": visible,
        }

    def run_blender(self, job: BlenderJob) -> dict[str, Any]:
        started = self._monotonic()
        configuration = self._blender_configuration()
        if configuration is None:
            raise WorkerRequestError(503, "blender_not_configured")
        executable, blend_root, output_root = configuration
        candidate = blend_root / job.project
        try:
            blend_file = candidate.resolve(strict=True)
        except OSError as exc:
            raise WorkerRequestError(404, "blend_file_not_found") from exc
        if blend_file.parent != blend_root or not blend_file.is_file():
            raise WorkerRequestError(403, "blend_file_outside_approved_root")
        safe_job_ref = hashlib.sha256(job.request_id.encode("utf-8")).hexdigest()[:16]
        output_template = output_root / f"render-{safe_job_ref}-######"
        output_file = output_root / f"render-{safe_job_ref}-{job.frame:06d}.png"
        if output_file.exists():
            raise WorkerRequestError(409, "blender_output_conflict")
        command = (
            executable,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            str(blend_file),
            "--render-output",
            str(output_template),
            "--render-format",
            "PNG",
            "--render-frame",
            str(job.frame),
        )
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            completed = self._process_runner(
                command,
                cwd=str(blend_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self.settings.render_timeout_seconds,
                check=False,
                shell=False,
                creationflags=creationflags,
                env=_blender_child_environment(os.environ, self.settings.secret),
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkerRequestError(504, "blender_timeout") from exc
        except OSError as exc:
            raise WorkerRequestError(502, "blender_unavailable") from exc
        if int(getattr(completed, "returncode", 1)) != 0:
            raise WorkerRequestError(502, "blender_failed")
        try:
            rendered = output_file.resolve(strict=True)
            size = rendered.stat().st_size
        except OSError as exc:
            raise WorkerRequestError(502, "blender_output_missing") from exc
        if rendered.parent != output_root or not rendered.is_file():
            raise WorkerRequestError(502, "blender_output_invalid")
        if size <= 0 or size > self.settings.max_render_bytes:
            raise WorkerRequestError(502, "blender_output_outside_limits")
        artifact_digest = hashlib.sha256()
        try:
            with rendered.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    artifact_digest.update(chunk)
        except OSError as exc:
            raise WorkerRequestError(502, "blender_output_invalid") from exc
        digest = artifact_digest.hexdigest()
        return {
            "schema": BLENDER_RESPONSE_SCHEMA,
            "ok": True,
            "request_id": job.request_id,
            "result": {
                "job_id": f"render-{safe_job_ref}",
                "frame": job.frame,
                "status": "completed",
                "artifact": {
                    "id": f"artifact-{digest[:16]}",
                    "name": rendered.name,
                    "sha256": digest,
                    "bytes": size,
                },
                "elapsed_ms": max(0, int((self._monotonic() - started) * 1000)),
            },
        }

    def execute(
        self,
        endpoint: str,
        request_id: str,
        body_hash: str,
        runner: Callable[[], dict[str, Any]],
        *,
        audit_event: str,
    ) -> tuple[int, dict[str, Any], bool]:
        state, record = self._idempotency.lookup(request_id, endpoint, body_hash)
        if state == "conflict":
            raise WorkerRequestError(409, "request_id_conflict")
        if state == "running":
            raise WorkerRequestError(409, "request_in_progress")
        if state == "complete" and record is not None:
            assert record.status_code is not None and record.response is not None
            self._audit(audit_event, "idempotent_replay", request_id=request_id)
            return record.status_code, dict(record.response), True
        if not self._slots.acquire(blocking=False):
            self._audit(audit_event, "busy", request_id=request_id)
            raise WorkerRequestError(429, "worker_busy")
        began = self._idempotency.begin(request_id, endpoint, body_hash)
        if began != "started":
            self._slots.release()
            if began == "conflict":
                raise WorkerRequestError(409, "request_id_conflict")
            if began == "complete":
                state, record = self._idempotency.lookup(request_id, endpoint, body_hash)
                if state == "complete" and record is not None:
                    assert record.status_code is not None and record.response is not None
                    return record.status_code, dict(record.response), True
            raise WorkerRequestError(409, "request_in_progress")
        started = self._monotonic()
        try:
            try:
                response = runner()
                status_code = 200
                status = "completed"
            except WorkerRequestError as exc:
                status_code = exc.status_code
                response = {"ok": False, "error": exc.code}
                status = exc.code
            except Exception:
                status_code = 500
                response = {"ok": False, "error": "internal_error"}
                status = "internal_error"
            self._idempotency.complete(request_id, status_code, response)
            self._audit(
                audit_event,
                status,
                request_id=request_id,
                duration_ms=int((self._monotonic() - started) * 1000),
            )
            return status_code, response, False
        finally:
            self._slots.release()


async def _read_bounded_body(request: Request, maximum: int) -> bytes:
    encoding = str(request.headers.get("content-encoding", "identity")).lower()
    if encoding not in {"", "identity"}:
        raise WorkerRequestError(415, "content_encoding_not_supported")
    content_type = str(request.headers.get("content-type", "")).lower()
    if content_type.split(";", 1)[0].strip() != "application/json":
        raise WorkerRequestError(415, "application_json_required")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise WorkerRequestError(400, "invalid_content_length") from exc
        if declared < 0 or declared > maximum:
            raise WorkerRequestError(413, "request_body_too_large")
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > maximum:
            raise WorkerRequestError(413, "request_body_too_large")
    if not chunks:
        raise WorkerRequestError(400, "request_body_required")
    return bytes(chunks)


def _error_response(exc: WorkerRequestError) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if exc.status_code == 429:
        headers["Retry-After"] = "1"
    return JSONResponse(
        {"ok": False, "error": exc.code},
        status_code=exc.status_code,
        headers=headers,
    )


def _require_secure_transport(request: Request, settings: WorkerSettings) -> None:
    if settings.allow_lan and request.url.scheme.casefold() != "https":
        raise WorkerRequestError(426, "tls_required")


def create_app(
    settings: WorkerSettings | None = None,
    *,
    clock: Callable[[], float] = time.time,
    monotonic: Callable[[], float] = time.monotonic,
    connection_factory: ConnectionFactory = http.client.HTTPConnection,
    process_runner: ProcessRunner = subprocess.run,
    audit_sink: AuditSink | None = None,
    hyfuser_backend: object | None = None,
) -> FastAPI:
    worker = ROGComputeWorker(
        settings or WorkerSettings.from_env(),
        clock=clock,
        monotonic=monotonic,
        connection_factory=connection_factory,
        process_runner=process_runner,
        audit_sink=audit_sink,
        hyfuser_backend=hyfuser_backend,
    )
    application = FastAPI(
        title="Alpecca ROG Compute Worker",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.worker = worker

    @application.get("/v1/health")
    async def health(request: Request) -> JSONResponse:
        try:
            _require_secure_transport(request, worker.settings)
            if request.url.query:
                raise WorkerRequestError(400, "query_not_allowed")
            request_id = worker.authenticate(request, b"")
        except WorkerRequestError as exc:
            return _error_response(exc)
        return JSONResponse(
            await asyncio.to_thread(worker.health, request_id),
            headers={"Cache-Control": "no-store"},
        )

    @application.get(HYFUSER_HEALTH_PATH)
    async def hyfuser_health(request: Request) -> JSONResponse:
        try:
            _require_secure_transport(request, worker.settings)
            if request.url.query:
                raise WorkerRequestError(400, "query_not_allowed")
            request_id = worker.authenticate(request, b"")
        except WorkerRequestError as exc:
            return _error_response(exc)
        return JSONResponse(
            await asyncio.to_thread(worker.hyfuser_health, request_id),
            headers={"Cache-Control": "no-store"},
        )

    async def authenticated_payload(
        request: Request,
    ) -> tuple[bytes, dict[str, Any], str]:
        _require_secure_transport(request, worker.settings)
        if request.url.query:
            raise WorkerRequestError(400, "query_not_allowed")
        body = await _read_bounded_body(request, worker.settings.max_body_bytes)
        request_id = worker.authenticate(request, body)
        payload = _json_with_no_duplicates(body)
        if payload.get("request_id") != request_id:
            raise WorkerRequestError(409, "request_id_mismatch")
        return body, payload, request_id

    @application.post("/v1/reason")
    async def reason(request: Request) -> JSONResponse:
        try:
            body, payload, _request_id_header = await authenticated_payload(request)
            job = _reasoning_job(payload, worker.settings)
            status, response, replay = await asyncio.to_thread(
                worker.execute,
                "/v1/reason",
                job.request_id,
                hashlib.sha256(body).hexdigest(),
                lambda: worker.run_reasoning(job),
                audit_event="reasoning",
            )
        except WorkerRequestError as exc:
            return _error_response(exc)
        headers = {"Cache-Control": "no-store"}
        if replay:
            headers["X-Alpecca-Idempotent-Replay"] = "1"
        return JSONResponse(response, status_code=status, headers=headers)

    @application.post("/v1/render/blender")
    async def blender_render(request: Request) -> JSONResponse:
        try:
            body, payload, _request_id_header = await authenticated_payload(request)
            job = _blender_job(payload)
            status, response, replay = await asyncio.to_thread(
                worker.execute,
                "/v1/render/blender",
                job.request_id,
                hashlib.sha256(body).hexdigest(),
                lambda: worker.run_blender(job),
                audit_event="blender_render",
            )
        except WorkerRequestError as exc:
            return _error_response(exc)
        headers = {"Cache-Control": "no-store"}
        if replay:
            headers["X-Alpecca-Idempotent-Replay"] = "1"
        return JSONResponse(response, status_code=status, headers=headers)

    @application.post(HYFUSER_SCORE_PATH)
    async def hyfuser_score(request: Request) -> JSONResponse:
        try:
            body, payload, _request_id_header = await authenticated_payload(request)
            job = _hyfuser_job(payload)
            status, response, replay = await asyncio.wait_for(
                asyncio.to_thread(
                    worker.execute,
                    HYFUSER_SCORE_PATH,
                    job.request_id,
                    hashlib.sha256(body).hexdigest(),
                    lambda: worker.run_hyfuser(job),
                    audit_event="hyfuser_shadow_score",
                ),
                timeout=worker.settings.hyfuser_timeout_seconds + 0.1,
            )
        except asyncio.TimeoutError:
            return _error_response(WorkerRequestError(504, "hyfuser_timeout"))
        except WorkerRequestError as exc:
            return _error_response(exc)
        headers = {"Cache-Control": "no-store"}
        if replay:
            headers["X-Alpecca-Idempotent-Replay"] = "1"
        return JSONResponse(response, status_code=status, headers=headers)

    return application


app = create_app()


def main() -> None:
    """Start the compute-only worker from validated environment settings."""

    settings = WorkerSettings.from_env()
    if settings.secret is None:
        raise SystemExit(
            f"Set ALPECCA_ROG_WORKER_SECRET or Windows credential {CREDENTIAL_TARGET}."
        )
    import uvicorn

    uvicorn_options: dict[str, object] = {
        "host": settings.bind_host,
        "port": settings.bind_port,
        "access_log": False,
        "log_level": "info",
        "proxy_headers": False,
    }
    if settings.allow_lan:
        assert settings.tls_cert_path is not None
        assert settings.tls_key_path is not None
        uvicorn_options["ssl_certfile"] = str(settings.tls_cert_path)
        uvicorn_options["ssl_keyfile"] = str(settings.tls_key_path)
    uvicorn.run(create_app(settings), **uvicorn_options)


if __name__ == "__main__":
    main()
