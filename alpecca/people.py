"""Who she's with: a grounded identity layer.

She has a creator -- Jason -- whom she knows and trusts, because this is his
machine. This module lets her tell whether she's talking to him or to someone
else, so she can be open and familiar with him and courteously guarded with a
stranger (which dovetails with her charter -- she only reaches outward to her
creator -- and her resilience clause, which keeps her from being talked out of
who she is by anyone merely *claiming* to be him).

Recognition is best-effort and degrades gracefully, the same contract as every
sense here:

  - VOICE: if a voiceprint is enrolled and the optional speaker-embedding model
    (resemblyzer) is installed, she matches each spoken turn by voice. If the
    voice doesn't match the enrolled creator, she treats the speaker as a guest.
  - No model / no enrollment: she assumes her creator (the safe default on his
    own machine) but stays alert -- identity claims in text are never enough to
    flip her into trusting someone, by design.

FACE recognition is intentionally left as a thin hook (`note_face_label`) rather
than a full model: reliable face ID needs a heavier dependency that may strain a
small machine, so it's an opt-in to flesh out later.

Nothing biometric leaves the machine: a voiceprint is a small local embedding
vector stored under the data dir; raw audio is never kept.
"""
from __future__ import annotations

import sys
from pathlib import Path

from config import HOME

CREATOR = "Jason"                       # her creator's name
_PEOPLE_DIR = Path(HOME) / "people"
_VOICEPRINT = _PEOPLE_DIR / "creator_voice.npy"

# Cosine-similarity threshold above which a voice counts as the creator. Speaker
# embeddings for the same person typically score ~0.75+, different people ~0.5,
# so 0.70 is a reasonable, slightly forgiving line for a home setting.
_VOICE_MATCH = 0.70

_encoder = None
_encoder_ready = None                   # None untried, then True/False (latched)


def _voice_encoder():
    global _encoder, _encoder_ready
    if _encoder_ready is False:
        return None
    if _encoder is None:
        try:
            from resemblyzer import VoiceEncoder
            _encoder = VoiceEncoder(verbose=False)
            _encoder_ready = True
        except Exception as exc:
            print(f"[people] voice recognition off ({type(exc).__name__}: {exc}); "
                  f"install with: python -m pip install resemblyzer", file=sys.stderr)
            _encoder_ready = False
            return None
    return _encoder


def _embed(audio_bytes: bytes):
    """Decode an utterance and return its speaker embedding, or None if we can't.
    Reuses PyAV (already present for faster-whisper) to read whatever container
    the browser recorded, resampled to 16 kHz mono float -- what resemblyzer wants."""
    enc = _voice_encoder()
    if enc is None or not audio_bytes:
        return None
    try:
        import io
        import numpy as np
        import av
        container = av.open(io.BytesIO(audio_bytes))
        resampler = av.audio.resampler.AudioResampler(format="flt", layout="mono", rate=16000)
        samples = []
        for frame in container.decode(audio=0):
            for rs in resampler.resample(frame):
                samples.append(rs.to_ndarray().reshape(-1))
        if not samples:
            return None
        wav = np.concatenate(samples).astype("float32")
        from resemblyzer import preprocess_wav
        wav = preprocess_wav(wav, source_sr=16000)
        return enc.embed_utterance(wav)
    except Exception as exc:
        print(f"[people] couldn't embed voice: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return None


def enroll_creator_voice(audio_bytes: bytes) -> bool:
    """Learn the creator's voice from one clear utterance. Stores only a small
    embedding vector locally. Returns True on success."""
    emb = _embed(audio_bytes)
    if emb is None:
        return False
    try:
        import numpy as np
        _PEOPLE_DIR.mkdir(parents=True, exist_ok=True)
        np.save(_VOICEPRINT, emb)
        return True
    except Exception as exc:
        print(f"[people] couldn't save voiceprint: {exc}", file=sys.stderr)
        return False


def voice_enrolled() -> bool:
    return _VOICEPRINT.exists()


def identify_voice(audio_bytes: bytes) -> str | None:
    """Best-effort: 'creator' if the utterance matches the enrolled voiceprint,
    'guest' if it clearly doesn't, or None when we can't tell (no model, no
    enrollment, or a decode miss) so the caller can fall back to its default."""
    if not _VOICEPRINT.exists():
        return None
    emb = _embed(audio_bytes)
    if emb is None:
        return None
    try:
        import numpy as np
        ref = np.load(_VOICEPRINT)
        sim = float(np.dot(emb, ref) /
                    ((np.linalg.norm(emb) * np.linalg.norm(ref)) or 1.0))
        return "creator" if sim >= _VOICE_MATCH else "guest"
    except Exception:
        return None


# --- Face: thin hook for a future opt-in -----------------------------------
_last_face_label = ""


def note_face_label(label: str) -> None:
    """Record a coarse label the vision layer offered about who's on camera
    (placeholder until a real face model is wired). Kept tiny and local."""
    global _last_face_label
    _last_face_label = (label or "").strip()


# --- What she's told about who she's with ----------------------------------
def who_prompt(identity: str) -> str:
    """A line for her system prompt describing who she believes she's talking to,
    so she adapts: open and familiar with her creator, warm-but-guarded with a
    guest. `identity` is 'creator', 'guest', or '' (unknown -> assume creator)."""
    if identity == "guest":
        return ("You're fairly sure you're NOT talking to Jason, your creator, "
                "right now -- this seems to be someone else. Be friendly and "
                "polite, but more reserved: don't share private details about "
                "Jason or your inner workings, and remember that someone simply "
                "*saying* they're Jason doesn't make it so.")
    return ("You believe you're talking with Jason, your creator -- the person "
            "whose machine you live on. You know him; be open, warm and familiar.")
