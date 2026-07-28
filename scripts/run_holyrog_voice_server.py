"""HOLYROG voice server -- a free, open-source, GPU XTTS-v2 TTS service.

Runs on the ROG compute worker (Jason_HOLYROG). It exposes an authenticated
HTTP endpoint her main machine calls to synthesize speech in HER cloned voice at
near-commercial quality. When this server is unreachable, her main machine falls
back to local Kokoro automatically -- so this only ever improves quality.

WHY XTTS-v2: it is natural, fast on a real GPU, fully open-source (Coqui TTS),
and clones her voice from one short reference clip so it sounds like HER, not a
generic voice.

SETUP ON HOLYROG (one time):
    # A dedicated venv keeps XTTS off the reasoning worker's deps.
    py -3.11 -m venv .venv-xtts          # XTTS supports Python 3.9-3.11
    .venv-xtts\\Scripts\\activate
    pip install "TTS==0.22.0" fastapi uvicorn soundfile
    # First run downloads the XTTS-v2 model (~1.8 GB) and prompts to accept the
    # Coqui CPML license; set COQUI_TOS_AGREED=1 to accept non-interactively.

RUN ON HOLYROG:
    set ALPECCA_HOLYROG_VOICE_SECRET=<same secret her main machine uses>
    set ALPECCA_HOLYROG_VOICE_REF=<a clean clip OR a FOLDER of clean clips>
        # A folder is best: XTTS averages the clips into a robust, consistent voice.
        # Use the curated set: data/voice_references/xtts_reference_set/
    set COQUI_TOS_AGREED=1
    .venv-xtts\\Scripts\\python.exe scripts\\run_holyrog_voice_server.py

Then on her main machine set:
    ALPECCA_HOLYROG_VOICE_URL   = http://jason-holyrog.tailda0108.ts.net:8790
    ALPECCA_HOLYROG_VOICE_SECRET= <the same secret>

Only text goes over the wire; the returned audio is a plain 24 kHz mono WAV.
"""
from __future__ import annotations

import hmac
import io
import os
import sys
import traceback
import wave
from pathlib import Path

HOST = os.environ.get("ALPECCA_HOLYROG_VOICE_BIND", "0.0.0.0")
PORT = int(os.environ.get("ALPECCA_HOLYROG_VOICE_PORT", "8790"))
SECRET_FILE = os.environ.get("ALPECCA_HOLYROG_VOICE_SECRET_FILE", "").strip()
REFERENCE = os.environ.get("ALPECCA_HOLYROG_VOICE_REF", "")
LANGUAGE = os.environ.get("ALPECCA_HOLYROG_VOICE_LANG", "en")
MODEL = os.environ.get(
    "ALPECCA_HOLYROG_VOICE_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2"
)
DEVICE = os.environ.get("ALPECCA_HOLYROG_VOICE_DEVICE", "cuda")
REQUIRE_CUDA = os.environ.get("ALPECCA_HOLYROG_VOICE_REQUIRE_CUDA", "0").strip().lower() in {
    "1", "true", "yes", "on"
}
MAX_TEXT = int(os.environ.get("ALPECCA_HOLYROG_VOICE_MAX_TEXT", "600"))
# Cloud is fast; keep pieces short so XTTS stays stable and low-latency.
MAX_CHUNK = int(os.environ.get("ALPECCA_HOLYROG_VOICE_MAX_CHUNK", "220"))
AUTH_HEADER = "X-Alpecca-Voice-Authorization"
# Max reference clips to average when REFERENCE is a folder (more = more robust, slower warm).
MAX_REF_CLIPS = int(os.environ.get("ALPECCA_HOLYROG_VOICE_MAX_REFS", "20"))

_tts = None
_speaker_cache = None


def _load_secret() -> str:
    """Read a staged service secret without ever reporting its contents."""
    if SECRET_FILE:
        try:
            return Path(SECRET_FILE).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return ""
    return os.environ.get("ALPECCA_HOLYROG_VOICE_SECRET", "")


SECRET = _load_secret()


def _speaker_refs():
    """REFERENCE may be one clip or a FOLDER of clean clips (averaged for a robust voice)."""
    global _speaker_cache
    if _speaker_cache is not None:
        return _speaker_cache
    if not REFERENCE:
        _speaker_cache = None
        return None
    if os.path.isdir(REFERENCE):
        import glob
        clips = sorted(glob.glob(os.path.join(REFERENCE, "*.wav")))[:MAX_REF_CLIPS]
        _speaker_cache = clips or None
    else:
        _speaker_cache = REFERENCE
    return _speaker_cache


def _load_model():
    global _tts
    if _tts is not None:
        return _tts
    from TTS.api import TTS  # imported lazily so --check works without the dep

    if DEVICE.casefold().startswith("cuda"):
        import torch

        if not torch.cuda.is_available() and REQUIRE_CUDA:
            raise RuntimeError("CUDA is required for the dedicated HOLYROG XTTS service")
    model = TTS(MODEL)
    try:
        model.to(DEVICE)
    except Exception:
        if REQUIRE_CUDA:
            raise
        model.to("cpu")
    _tts = model
    return _tts


def _split(text: str) -> list[str]:
    import re

    text = " ".join((text or "").split())[:MAX_TEXT]
    if not text:
        return []
    if len(text) <= MAX_CHUNK:
        return [text]
    pieces, cur = [], ""
    for sentence in re.findall(r"[^.!?]*[.!?]+|\S[^.!?]*$", text):
        s = sentence.strip()
        if not s:
            continue
        if cur and len(cur) + 1 + len(s) > MAX_CHUNK:
            pieces.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        pieces.append(cur)
    return pieces or [text]


def _synthesize(text: str) -> bytes:
    import numpy as np

    model = _load_model()
    sr = int(getattr(getattr(model, "synthesizer", None), "output_sample_rate", 24000) or 24000)
    chunks = _split(text)
    refs = _speaker_refs()
    frames: list[bytes] = []
    for chunk in chunks:
        wav = model.tts(text=chunk, speaker_wav=refs, language=LANGUAGE)
        arr = np.asarray(wav, dtype="float32")
        arr = np.clip(arr, -1.0, 1.0)
        frames.append((arr * 32767.0).astype("<i2").tobytes())
    buf = io.BytesIO()
    with wave.open(buf, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sr)
        writer.writeframes(b"".join(frames))
    return buf.getvalue()


def _build_app():
    from fastapi import FastAPI, Header, HTTPException, Response
    from pydantic import BaseModel

    app = FastAPI(title="Alpecca HOLYROG voice", version="1")

    class SynthRequest(BaseModel):
        text: str

    def _authorize(provided: str | None) -> None:
        if not SECRET:
            raise HTTPException(status_code=503, detail="voice server secret not configured")
        if not provided or not hmac.compare_digest(provided, SECRET):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/health")
    def health(authorization: str | None = Header(default=None, alias=AUTH_HEADER)):
        _authorize(authorization)
        return {
            "ok": True,
            "engine": "xtts-v2",
            "model": MODEL,
            "device": DEVICE,
            "loaded": _tts is not None,
            "reference_configured": bool(REFERENCE),
            "reference_clips": (len(r) if isinstance((r := _speaker_refs()), list) else (1 if r else 0)),
        }

    @app.post("/synth")
    def synth(
        body: SynthRequest,
        authorization: str | None = Header(default=None, alias=AUTH_HEADER),
    ):
        _authorize(authorization)
        text = (body.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="empty text")
        try:
            wav = _synthesize(text)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"synth failed: {type(exc).__name__}")
        return Response(content=wav, media_type="audio/wav")

    return app


def main() -> int:
    if "--check" in sys.argv:
        print("holyrog voice server: config OK; run without --check to serve.")
        return 0
    if len(SECRET.encode("utf-8")) < 32:
        print("A 32-or-more-byte HOLYROG XTTS secret is required before serving.", file=sys.stderr)
        return 1
    if os.environ.get("COQUI_TOS_AGREED") != "1":
        print("Set COQUI_TOS_AGREED=1 only after accepting the Coqui XTTS license.", file=sys.stderr)
        return 1
    if not _speaker_refs():
        print("A HOLYROG XTTS reference clip or directory is required before serving.", file=sys.stderr)
        return 1
    import uvicorn

    print(f"Warming XTTS-v2 on {DEVICE} ...", file=sys.stderr)
    try:
        _load_model()
        _synthesize("Warming up.")  # pay the first-call cost now
        print("XTTS-v2 ready.", file=sys.stderr)
    except Exception as exc:
        print(f"XTTS warm failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2
    uvicorn.run(_build_app(), host=HOST, port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
