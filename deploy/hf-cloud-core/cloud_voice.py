"""Standalone authenticated Kokoro voice service for cloud standby use.

This process intentionally has no dependency on the Alpecca package, CoreMind,
continuity restore, or singleton leases. It accepts bounded text and returns an
in-memory WAV response; neither request text nor audio is persisted.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import hmac
from io import BytesIO
import json
import os
import threading
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Request, Response


SERVICE_NAME = "alpecca-cloud-kokoro-voice"
SERVICE_VERSION = 1
AUTHORIZATION_HEADER = "X-Alpecca-Authorization"
VOICE = "af_heart"
LANGUAGE_CODE = "a"
SAMPLE_RATE_HZ = 24_000
MAX_TEXT_CHARS = 1_200
MAX_BODY_BYTES = 16 * 1024
MAX_AUDIO_BYTES = 12 * 1024 * 1024
MAX_CREDENTIAL_CHARS = 512
DEFAULT_PORT = 7861


class VoiceServiceError(RuntimeError):
    """The bounded voice service could not complete synthesis."""


class Synthesizer(Protocol):
    @property
    def loaded(self) -> bool: ...

    def synthesize(self, text: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class HealthMetadata:
    service: str
    version: int
    state: str
    engine: str
    voice: str
    device: str
    sampleRateHz: int
    modelLoaded: bool
    persistence: bool
    coreMind: bool
    singletonAuthority: bool
    maxTextChars: int
    maxBodyBytes: int


class LazyKokoroSynthesizer:
    """Load Kokoro on first use and serialize CPU synthesis calls."""

    def __init__(self) -> None:
        self._pipeline: Any | None = None
        self._load_lock = threading.Lock()
        self._synthesis_lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None

    def _get_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        with self._load_lock:
            if self._pipeline is None:
                # These imports may initialize the model, so they remain behind
                # the authenticated request boundary and never run at startup.
                os.environ["CUDA_VISIBLE_DEVICES"] = ""
                from kokoro import KPipeline

                self._pipeline = KPipeline(lang_code=LANGUAGE_CODE)
        return self._pipeline

    def synthesize(self, text: str) -> bytes:
        with self._synthesis_lock:
            pipeline = self._get_pipeline()
            try:
                import soundfile as sf

                output = BytesIO()
                generated = False
                with sf.SoundFile(
                    output,
                    mode="w",
                    samplerate=SAMPLE_RATE_HZ,
                    channels=1,
                    format="WAV",
                    subtype="PCM_16",
                ) as wav:
                    for chunk in pipeline(
                        text,
                        voice=VOICE,
                        speed=1.0,
                        split_pattern=r"\n+",
                    ):
                        audio = chunk[2]
                        if audio is None:
                            continue
                        wav.write(audio)
                        generated = True
                data = output.getvalue()
            except VoiceServiceError:
                raise
            except Exception as exc:
                raise VoiceServiceError("kokoro_synthesis_failed") from exc
            if not generated or not data:
                raise VoiceServiceError("kokoro_returned_no_audio")
            if len(data) > MAX_AUDIO_BYTES:
                raise VoiceServiceError("synthesized_audio_exceeds_limit")
            return data


def _secret_digest(secret: str) -> bytes:
    if not isinstance(secret, str) or not secret or len(secret) > MAX_CREDENTIAL_CHARS:
        raise ValueError("voice authorization secret is missing or malformed")
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _authorized(supplied: str | None, expected_digest: bytes) -> bool:
    value = supplied or ""
    if value[:7].casefold() == "bearer ":
        value = value[7:]
    malformed = not value or len(value) > MAX_CREDENTIAL_CHARS
    candidate_value = "" if malformed else value
    candidate = hashlib.sha256(candidate_value.encode("utf-8")).digest()
    matched = hmac.compare_digest(candidate, expected_digest)
    return matched and not malformed


async def _bounded_json(request: Request) -> dict[str, Any]:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_size = int(declared)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_content_length") from None
        if declared_size < 0:
            raise HTTPException(status_code=400, detail="invalid_content_length")
        if declared_size > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="request_body_too_large")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="request_body_too_large")
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="invalid_json") from None
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail="json_object_required")
    return value


def _bounded_text(payload: dict[str, Any]) -> str:
    text = payload.get("text")
    if not isinstance(text, str):
        raise HTTPException(status_code=422, detail="text_string_required")
    normalized = " ".join(text.split())
    if not normalized:
        raise HTTPException(status_code=422, detail="text_required")
    if len(normalized) > MAX_TEXT_CHARS:
        raise HTTPException(status_code=413, detail="text_too_long")
    return normalized


def create_app(*, secret: str, synthesizer: Synthesizer | None = None) -> FastAPI:
    """Create the isolated service without loading Kokoro or Alpecca state."""

    expected_digest = _secret_digest(secret)
    engine = synthesizer or LazyKokoroSynthesizer()
    app = FastAPI(
        title="Alpecca Cloud Voice",
        version=str(SERVICE_VERSION),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        metadata = HealthMetadata(
            service=SERVICE_NAME,
            version=SERVICE_VERSION,
            state="ready",
            engine="kokoro",
            voice=VOICE,
            device="cpu",
            sampleRateHz=SAMPLE_RATE_HZ,
            modelLoaded=bool(engine.loaded),
            persistence=False,
            coreMind=False,
            singletonAuthority=False,
            maxTextChars=MAX_TEXT_CHARS,
            maxBodyBytes=MAX_BODY_BYTES,
        )
        return {
            field: getattr(metadata, field)
            for field in metadata.__dataclass_fields__
        }

    async def synthesize(request: Request) -> Response:
        if not _authorized(request.headers.get(AUTHORIZATION_HEADER), expected_digest):
            raise HTTPException(status_code=401, detail="unauthorized")
        payload = await _bounded_json(request)
        text = _bounded_text(payload)
        try:
            audio = await asyncio.to_thread(engine.synthesize, text)
        except VoiceServiceError:
            raise HTTPException(status_code=503, detail="synthesis_unavailable") from None
        except Exception:
            raise HTTPException(status_code=503, detail="synthesis_unavailable") from None
        if not isinstance(audio, bytes) or not audio or len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=503, detail="invalid_synthesis_result")
        return Response(
            content=audio,
            media_type="audio/wav",
            headers={
                "Cache-Control": "no-store",
                "X-Alpecca-Voice": VOICE,
                "X-Alpecca-Engine": "kokoro",
            },
        )

    app.post("/v1/voice/synthesize")(synthesize)
    app.post("/v1/synthesize", include_in_schema=False)(synthesize)
    return app


def main() -> int:
    secret = (
        os.environ.get("ALPECCA_CLOUD_VOICE_SECRET", "").strip()
        or os.environ.get("ALPECCA_AUTH_SECRET", "").strip()
    )
    if not secret:
        print("Cloud voice is disabled: authorization secret is unavailable.", flush=True)
        return 2
    try:
        port = int(os.environ.get("ALPECCA_CLOUD_VOICE_PORT", str(DEFAULT_PORT)))
    except ValueError:
        print("Cloud voice is disabled: port is invalid.", flush=True)
        return 2
    if not 1 <= port <= 65_535:
        print("Cloud voice is disabled: port is invalid.", flush=True)
        return 2

    import uvicorn

    uvicorn.run(
        create_app(secret=secret),
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
