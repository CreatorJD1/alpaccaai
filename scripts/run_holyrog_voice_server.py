#!/usr/bin/env python3
"""HolyROG authenticated XTTS-v2 voice server for Alpecca (host: Jason_HOLYROG).

Loads Coqui XTTS-v2 once, clones Alpecca's voice from the reference clips in
``ALPECCA_HOLYROG_VOICE_REF``, and exposes ``POST /synthesize`` (returning
``audio/wav``) gated by the shared secret ``ALPECCA_HOLYROG_VOICE_SECRET``.

COMPUTE-ONLY: starts no CoreMind, Discord bridge, autonomy loop, memory writer,
tunnel, or second Alpecca instance. Binds 0.0.0.0 so the RygenART primary can
reach it over Tailscale; Windows' default-inbound-block plus the Tailscale-In
rule keep it tailnet-only, and the shared-secret gate applies on every request.

SECURITY:
  * Refuses to start unless ALPECCA_HOLYROG_VOICE_SECRET is set (fail closed).
  * /synthesize requires the secret via ``Authorization: Bearer <secret>`` or
    ``X-Alpecca-Voice-Secret: <secret>`` (constant-time compare). 401 otherwise.
  * The secret is NEVER logged or returned; startup prints only its length.

LICENSE: the first run downloads the ~1.8 GB XTTS-v2 weights and requires
``COQUI_TOS_AGREED=1`` (Coqui non-commercial license). This server does not set
that for you. On successful warm-up it prints ``XTTS-v2 ready.``.

Run:
    $env:COQUI_TOS_AGREED="1"
    $env:ALPECCA_HOLYROG_VOICE_SECRET="<secret>"
    $env:ALPECCA_HOLYROG_VOICE_REF="<path to xtts_reference_set folder>"
    .\\.venv-xtts\\Scripts\\python.exe scripts\\run_holyrog_voice_server.py
"""
from __future__ import annotations

import glob
import io
import os
import secrets
import threading
from pathlib import Path
from typing import List, Optional

import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
REFS_DIR = Path(os.environ.get(
    "ALPECCA_HOLYROG_VOICE_REF",
    str(ROOT / "data" / "voice_references" / "xtts_reference_set"),
))
SECRET = os.environ.get("ALPECCA_HOLYROG_VOICE_SECRET", "")
MODEL = os.environ.get("ALPECCA_HOLYROG_VOICE_MODEL",
                       "tts_models/multilingual/multi-dataset/xtts_v2")
HOST = os.environ.get("ALPECCA_HOLYROG_VOICE_HOST", "0.0.0.0")
PORT = int(os.environ.get("ALPECCA_HOLYROG_VOICE_PORT", "8123"))
DEFAULT_LANG = os.environ.get("ALPECCA_HOLYROG_VOICE_LANGUAGE", "en")


# --- Naturalness tuning -----------------------------------------------------
# XTTS's stock decode defaults read stiff and slightly robotic. The values
# below were validated against Alpecca's reference set and give a warmer,
# crisper, more natural talk-show delivery:
#   * repetition_penalty 3.0 (vs stock 2.0) removes the robotic buzz/artifacts
#   * temperature 0.70 keeps natural prosodic variation without drifting
#   * speed 0.96 is a touch slower -> unhurried, warmer read
#   * gpt_cond_len/max_ref_len 30 use more reference audio -> truer timbre
# Every knob is env-overridable, so the voice can be retuned without editing
# code -- restart only this process to pick up a change.
def _envf(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, TypeError, ValueError):
        return default


def _envi(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, TypeError, ValueError):
        return default


VOICE_TUNING = {
    "temperature": _envf("ALPECCA_VOICE_TEMPERATURE", 0.70),
    "length_penalty": _envf("ALPECCA_VOICE_LENGTH_PENALTY", 1.0),
    "repetition_penalty": _envf("ALPECCA_VOICE_REPETITION_PENALTY", 3.0),
    "top_k": _envi("ALPECCA_VOICE_TOP_K", 50),
    "top_p": _envf("ALPECCA_VOICE_TOP_P", 0.85),
    "speed": _envf("ALPECCA_VOICE_SPEED", 0.96),
    "gpt_cond_len": _envi("ALPECCA_VOICE_GPT_COND_LEN", 30),
    "max_ref_len": _envi("ALPECCA_VOICE_MAX_REF_LEN", 30),
    "enable_text_splitting": os.environ.get(
        "ALPECCA_VOICE_TEXT_SPLITTING", "1") == "1",
}

_tts = None
_device = ""
_load_lock = threading.Lock()
_load_error = ""


def _refs() -> List[str]:
    return sorted(glob.glob(str(REFS_DIR / "*.wav")))


def _load_model():
    """Load XTTS-v2 once (thread-safe). Raises plain exceptions; license-gated."""
    global _tts, _device
    if _tts is not None:
        return _tts
    with _load_lock:
        if _tts is not None:
            return _tts
        if os.environ.get("COQUI_TOS_AGREED") != "1":
            raise RuntimeError(
                "COQUI_TOS_AGREED=1 required to accept Coqui's non-commercial "
                "license before the first XTTS-v2 download")
        import torch
        # torch>=2.6 defaults torch.load(weights_only=True), which rejects the
        # official XTTS-v2 checkpoint's config globals. The weights come from
        # Coqui's trusted model download, so allowlist the XTTS config classes
        # so the checkpoint loads under weights_only.
        try:
            from TTS.tts.configs.xtts_config import XttsConfig
            from TTS.tts.models.xtts import XttsAudioConfig, XttsArgs
            from TTS.config.shared_configs import BaseDatasetConfig
            torch.serialization.add_safe_globals(
                [XttsConfig, XttsAudioConfig, XttsArgs, BaseDatasetConfig])
        except Exception:  # noqa: BLE001 -- older torch lacks add_safe_globals
            pass
        from TTS.api import TTS
        _device = os.environ.get("ALPECCA_HOLYROG_VOICE_DEVICE") or (
            "cuda" if torch.cuda.is_available() else "cpu")
        _tts = TTS(MODEL).to(_device)
        return _tts


def _load():
    """Request-time loader: wraps load errors as HTTP 503."""
    global _load_error
    try:
        return _load_model()
    except Exception as exc:  # noqa: BLE001
        _load_error = f"{type(exc).__name__}: {exc}"
        raise HTTPException(status_code=503,
                            detail=f"model load failed: {type(exc).__name__}")


def _authorized(request: Request) -> bool:
    provided = ""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        provided = auth[7:].strip()
    if not provided:
        provided = request.headers.get("x-alpecca-voice-secret", "").strip()
    return bool(provided) and secrets.compare_digest(provided, SECRET)


def _synthesize_wav(tts, text: str, refs: List[str], language: str):
    """Synthesize with the tuned decode params, degrading gracefully.

    Different coqui-tts versions accept different kwarg sets on ``tts()``. If a
    knob is unsupported we retry with fewer of them rather than 500 the
    request, so a library bump can never silently break voice output.
    """
    attempts = (
        VOICE_TUNING,
        {k: v for k, v in VOICE_TUNING.items()
         if k not in ("gpt_cond_len", "max_ref_len")},
        {},
    )
    last_error: Optional[TypeError] = None
    for kwargs in attempts:
        try:
            return tts.tts(text=text, speaker_wav=refs, language=language,
                           **kwargs)
        except TypeError as exc:  # unsupported kwarg for this TTS version
            last_error = exc
    raise RuntimeError(f"no supported tts() kwarg set: {last_error}")


app = FastAPI(title="Alpecca HolyROG voice server", docs_url=None, redoc_url=None)


class SynthRequest(BaseModel):
    text: str
    language: Optional[str] = None


@app.get("/healthz")
def healthz() -> dict:
    # Content-free: no secret, no reference contents.
    return {
        "ok": True,
        "role": "compute-only-holyrog-voice",
        "model": MODEL,
        "device": _device or None,
        "refs": len(_refs()),
        "loaded": _tts is not None,
        "load_error": _load_error or None,
        "license_accepted": os.environ.get("COQUI_TOS_AGREED") == "1",
        "tuning": VOICE_TUNING,
    }


@app.post("/synthesize")
def synthesize(req: SynthRequest, request: Request) -> Response:
    if not _authorized(request):
        raise HTTPException(status_code=401, detail="voice authorization required")
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty text")
    if len(text) > 2000:
        raise HTTPException(status_code=413, detail="text too long (>2000 chars)")
    refs = _refs()
    if not refs:
        raise HTTPException(status_code=503,
                            detail=f"no voice references in {REFS_DIR}")
    tts = _load()
    wav = _synthesize_wav(tts, text, refs, req.language or DEFAULT_LANG)
    sample_rate = tts.synthesizer.output_sample_rate
    buf = io.BytesIO()
    sf.write(buf, wav, sample_rate, format="WAV", subtype="PCM_16")
    return Response(content=buf.getvalue(), media_type="audio/wav")


def main() -> int:
    if not SECRET:
        print("REFUSING TO START: ALPECCA_HOLYROG_VOICE_SECRET is not set "
              "(the /synthesize endpoint must be secret-gated).", flush=True)
        return 2
    refs = _refs()
    print(f"Alpecca HolyROG voice server | model={MODEL} | refs={len(refs)} in "
          f"{REFS_DIR} | secret=set(len={len(SECRET)}) | "
          f"license_accepted={os.environ.get('COQUI_TOS_AGREED') == '1'}",
          flush=True)
    print(f"voice tuning: {VOICE_TUNING}", flush=True)
    if not refs:
        print(f"WARNING: no voice references found in {REFS_DIR}", flush=True)
    # Prewarm: download + load the model so the first request is fast.
    try:
        tts = _load_model()
        sr = tts.synthesizer.output_sample_rate
    except Exception as exc:  # noqa: BLE001
        print(f"XTTS-v2 load FAILED: {type(exc).__name__}: {exc}", flush=True)
        return 3
    print(f"XTTS-v2 ready. device={_device} refs={len(refs)} sample_rate={sr}",
          flush=True)
    print(f"Serving on {HOST}:{PORT}", flush=True)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
