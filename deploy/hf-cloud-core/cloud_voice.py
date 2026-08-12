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
import time
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
SELF_CHECK_TEXT = "Voice readiness check."
SELF_CHECK_TIMEOUT_SECONDS = 45.0
MIN_PCM_DURATION_MS = 100
MIN_SIGNAL_AMPLITUDE = 64
MIN_ACTIVE_SAMPLE_PER_MILLE = 5
MAX_SIGNAL_PROBES = 8_192


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
    selfCheckPassed: bool
    selfCheckState: str
    synthesisReady: bool
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


def _has_meaningful_pcm_signal(
    audio: bytes,
    *,
    data_start: int,
    data_size: int,
    block_align: int,
) -> bool:
    frame_count = data_size // block_align
    minimum_frames = (SAMPLE_RATE_HZ * MIN_PCM_DURATION_MS + 999) // 1_000
    if frame_count < minimum_frames:
        return False

    probe_count = min(frame_count, MAX_SIGNAL_PROBES)
    required_active = max(
        2,
        (probe_count * MIN_ACTIVE_SAMPLE_PER_MILLE + 999) // 1_000,
    )
    active = 0
    for probe_index in range(probe_count):
        frame_index = probe_index * frame_count // probe_count
        sample_start = data_start + frame_index * block_align
        sample = int.from_bytes(
            audio[sample_start : sample_start + 2],
            "little",
            signed=True,
        )
        if abs(sample) >= MIN_SIGNAL_AMPLITUDE:
            active += 1
            if active >= required_active:
                return True
    return False


def _valid_wav(audio: object) -> bool:
    """Validate playable PCM structure, duration, and signal quality."""

    if not isinstance(audio, bytes) or not 44 <= len(audio) <= MAX_AUDIO_BYTES:
        return False
    if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return False

    riff_size = int.from_bytes(audio[4:8], "little")
    if riff_size != len(audio) - 8:
        return False

    fmt: tuple[int, int, int, int, int, int] | None = None
    data_span: tuple[int, int] | None = None
    offset = 12
    while offset < len(audio):
        if offset + 8 > len(audio):
            return False
        chunk_id = audio[offset : offset + 4]
        chunk_size = int.from_bytes(audio[offset + 4 : offset + 8], "little")
        chunk_start = offset + 8
        chunk_end = chunk_start + chunk_size
        padded_end = chunk_end + (chunk_size & 1)
        if chunk_end > len(audio) or padded_end > len(audio):
            return False

        if chunk_id == b"fmt ":
            if fmt is not None or chunk_size < 16:
                return False
            fmt = tuple(
                int.from_bytes(audio[start:end], "little")
                for start, end in (
                    (chunk_start, chunk_start + 2),
                    (chunk_start + 2, chunk_start + 4),
                    (chunk_start + 4, chunk_start + 8),
                    (chunk_start + 8, chunk_start + 12),
                    (chunk_start + 12, chunk_start + 14),
                    (chunk_start + 14, chunk_start + 16),
                )
            )
        elif chunk_id == b"data":
            if data_span is not None:
                return False
            data_span = (chunk_start, chunk_end)

        offset = padded_end

    if offset != len(audio) or fmt is None or data_span is None:
        return False

    audio_format, channels, sample_rate, byte_rate, block_align, bits = fmt
    if (
        audio_format != 1
        or channels != 1
        or sample_rate != SAMPLE_RATE_HZ
        or bits != 16
        or block_align != channels * (bits // 8)
        or byte_rate != sample_rate * block_align
    ):
        return False
    data_start, data_end = data_span
    data_size = data_end - data_start
    if data_size < block_align or data_size % block_align != 0:
        return False
    return _has_meaningful_pcm_signal(
        audio,
        data_start=data_start,
        data_size=data_size,
        block_align=block_align,
    )


class SynthesisReadiness:
    """Run one bounded synthesis probe without blocking the health endpoint."""

    def __init__(self, *, timeout_seconds: float = SELF_CHECK_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = max(0.01, float(timeout_seconds))
        self._lock = threading.Lock()
        self._state = "pending"
        self._started_at = 0.0

    def ensure_started(self, engine: Synthesizer) -> None:
        with self._lock:
            if self._state != "pending":
                return
            self._state = "running"
            self._started_at = time.monotonic()
        threading.Thread(
            target=self._run,
            args=(engine,),
            name="cloud-voice-self-check",
            daemon=True,
        ).start()

    def _run(self, engine: Synthesizer) -> None:
        try:
            audio = engine.synthesize(SELF_CHECK_TEXT)
            valid = _valid_wav(audio)
        except Exception:
            valid = False
        completed_at = time.monotonic()
        with self._lock:
            elapsed = completed_at - self._started_at
            if self._state == "running":
                self._state = (
                    "passed" if valid and elapsed <= self._timeout_seconds else "failed"
                )

    def snapshot(self, *, model_loaded: bool) -> tuple[str, bool, bool]:
        with self._lock:
            if (
                self._state == "running"
                and time.monotonic() - self._started_at > self._timeout_seconds
            ):
                self._state = "failed"
            check_state = self._state
        check_passed = check_state == "passed"
        return check_state, check_passed, bool(model_loaded and check_passed)


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


def create_app(
    *,
    secret: str,
    synthesizer: Synthesizer | None = None,
    self_check_timeout_seconds: float = SELF_CHECK_TIMEOUT_SECONDS,
) -> FastAPI:
    """Create the isolated service without loading Kokoro or Alpecca state."""

    expected_digest = _secret_digest(secret)
    engine = synthesizer or LazyKokoroSynthesizer()
    readiness = SynthesisReadiness(timeout_seconds=self_check_timeout_seconds)
    app = FastAPI(
        title="Alpecca Cloud Voice",
        version=str(SERVICE_VERSION),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        readiness.ensure_started(engine)
        try:
            model_loaded = bool(engine.loaded)
        except Exception:
            model_loaded = False
        check_state, check_passed, synthesis_ready = readiness.snapshot(
            model_loaded=model_loaded
        )
        state = (
            "ready"
            if synthesis_ready
            else "unavailable"
            if check_state == "failed"
            else "starting"
        )
        metadata = HealthMetadata(
            service=SERVICE_NAME,
            version=SERVICE_VERSION,
            state=state,
            engine="kokoro",
            voice=VOICE,
            device="cpu",
            sampleRateHz=SAMPLE_RATE_HZ,
            modelLoaded=model_loaded,
            selfCheckPassed=check_passed,
            selfCheckState=check_state,
            synthesisReady=synthesis_ready,
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
        except VoiceServiceError as exc:
            print(f"Cloud voice synthesis unavailable: {exc}", flush=True)
            raise HTTPException(status_code=503, detail="synthesis_unavailable") from None
        except Exception as exc:
            print(
                f"Cloud voice synthesis unavailable: {type(exc).__name__}",
                flush=True,
            )
            raise HTTPException(status_code=503, detail="synthesis_unavailable") from None
        if not _valid_wav(audio):
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
