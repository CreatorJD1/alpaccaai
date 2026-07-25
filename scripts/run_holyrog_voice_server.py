#!/usr/bin/env python3
"""HolyROG authenticated XTTS-v2 voice server for Alpecca (host: Jason_HOLYROG).

Loads Coqui XTTS-v2 once, clones Alpecca's voice from the reference clips in
``ALPECCA_HOLYROG_VOICE_REF``, and exposes ``POST /synthesize`` (returning
``audio/wav``) gated by the shared secret ``ALPECCA_HOLYROG_VOICE_SECRET``.

COMPUTE-ONLY: starts no CoreMind, Discord bridge, autonomy loop, memory writer,
tunnel, or second Alpecca instance. Binds 127.0.0.1 by default; if you bind a
non-loopback host the shared-secret gate still applies (but scope the firewall
like the 8788 worker before exposing it to the tailnet).

SECURITY:
  * Refuses to start unless ALPECCA_HOLYROG_VOICE_SECRET is set (fail closed).
  * /synthesize requires the secret via ``Authorization: Bearer <secret>`` or
    ``X-Alpecca-Voice-Secret: <secret>`` (constant-time compare). 401 otherwise.
  * The secret is NEVER logged or returned; startup prints only its length.

LICENSE: the first synthesis downloads the ~1.8 GB XTTS-v2 weights and requires
``COQUI_TOS_AGREED=1`` (Coqui non-commercial license). This server does not set
that for you.

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
HOST = os.environ.get("ALPECCA_HOLYROG_VOICE_HOST", "127.0.0.1")
PORT = int(os.environ.get("ALPECCA_HOLYROG_VOICE_PORT", "8123"))
DEFAULT_LANG = os.environ.get("ALPECCA_HOLYROG_VOICE_LANGUAGE", "en")

_tts = None
_load_lock = threading.Lock()
_load_error = ""


def _refs() -> List[str]:
    return sorted(glob.glob(str(REFS_DIR / "*.wav")))


def _load():
    """Load XTTS-v2 once (thread-safe). Honors the Coqui license gate."""
    global _tts, _load_error
    if _tts is not None:
        return _tts
    with _load_lock:
        if _tts is not None:
            return _tts
        if os.environ.get("COQUI_TOS_AGREED") != "1":
            raise HTTPException(
                status_code=503,
                detail=("model not loaded: set COQUI_TOS_AGREED=1 to accept "
                        "Coqui's non-commercial license before first download."),
            )
        try:
            import torch
            from TTS.api import TTS
            device = "cuda" if torch.cuda.is_available() else "cpu"
            _tts = TTS(MODEL).to(device)
        except Exception as exc:  # noqa: BLE001
            _load_error = type(exc).__name__
            raise HTTPException(status_code=503,
                                detail=f"model load failed: {_load_error}")
    return _tts


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
              "(the /synthesize endpoint must be secret-gated).")
        return 2
    print(f"Alpecca HolyROG voice server binding {HOST}:{PORT} | model={MODEL} | "
          f"refs={len(_refs())} in {REFS_DIR} | secret=set(len={len(SECRET)}) | "
          f"license_accepted={os.environ.get('COQUI_TOS_AGREED') == '1'}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
