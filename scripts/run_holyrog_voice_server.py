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
    wav = tts.tts(text=text, speaker_wav=refs, language=req.language or DEFAULT_LANG)
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
