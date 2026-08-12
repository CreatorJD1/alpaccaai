#!/usr/bin/env python3
"""Minimal local XTTS-v2 voice server for Alpecca (assigned host: Jason_HOLYROG).

Loads Coqui XTTS-v2 once, clones Alpecca's voice from the reference clips in
``data/voice_references/xtts_reference_set/``, and exposes a loopback-only
FastAPI endpoint ``POST /synthesize {text, language?}`` returning ``audio/wav``.

COMPUTE-ONLY: this process starts no CoreMind, Discord bridge, autonomy loop,
memory writer, tunnel, or second Alpecca instance, and binds 127.0.0.1 only.

LICENSE / FIRST RUN: the first synthesis downloads the ~1.8 GB XTTS-v2 weights
and requires accepting Coqui's non-commercial model license (CPML). This server
does NOT auto-accept it -- set ``COQUI_TOS_AGREED=1`` yourself only if you agree.
Without that, model loading will refuse rather than silently accept the license.

Run:
    .venv-xtts\\Scripts\\python.exe scripts\\run_xtts_server.py
Env knobs: ALPECCA_XTTS_HOST (127.0.0.1), ALPECCA_XTTS_PORT (8123),
ALPECCA_XTTS_MODEL, ALPECCA_XTTS_LANGUAGE (en), ALPECCA_XTTS_REFS_DIR.
"""
from __future__ import annotations

import glob
import io
import os
from pathlib import Path
from typing import List, Optional

import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
REFS_DIR = Path(os.environ.get(
    "ALPECCA_XTTS_REFS_DIR",
    str(ROOT / "data" / "voice_references" / "xtts_reference_set"),
))
MODEL = os.environ.get("ALPECCA_XTTS_MODEL",
                       "tts_models/multilingual/multi-dataset/xtts_v2")
HOST = os.environ.get("ALPECCA_XTTS_HOST", "127.0.0.1")
PORT = int(os.environ.get("ALPECCA_XTTS_PORT", "8123"))
DEFAULT_LANG = os.environ.get("ALPECCA_XTTS_LANGUAGE", "en")

_tts = None


def _refs() -> List[str]:
    return sorted(glob.glob(str(REFS_DIR / "*.wav")))


def _load():
    """Load XTTS-v2 once. Refuses unless the operator accepted the license."""
    global _tts
    if _tts is not None:
        return _tts
    if os.environ.get("COQUI_TOS_AGREED") != "1":
        raise HTTPException(
            status_code=503,
            detail=("XTTS-v2 model not loaded: set COQUI_TOS_AGREED=1 to accept "
                    "Coqui's non-commercial model license before first download."),
        )
    import torch
    from TTS.api import TTS
    device = "cuda" if torch.cuda.is_available() else "cpu"
    _tts = TTS(MODEL).to(device)
    return _tts


app = FastAPI(title="Alpecca XTTS server", docs_url=None, redoc_url=None)


class SynthRequest(BaseModel):
    text: str
    language: Optional[str] = None


@app.get("/healthz")
def healthz() -> dict:
    return {
        "ok": True,
        "role": "compute-only-xtts",
        "model": MODEL,
        "refs": len(_refs()),
        "refs_dir": str(REFS_DIR),
        "loaded": _tts is not None,
        "license_accepted": os.environ.get("COQUI_TOS_AGREED") == "1",
    }


@app.post("/synthesize")
def synthesize(req: SynthRequest) -> Response:
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
    print(f"Alpecca XTTS server binding {HOST}:{PORT} | model={MODEL} | "
          f"refs={len(_refs())} in {REFS_DIR} | "
          f"license_accepted={os.environ.get('COQUI_TOS_AGREED') == '1'}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
