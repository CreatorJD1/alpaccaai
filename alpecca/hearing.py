"""Hearing words: local speech-to-text for the push-to-talk loop.

The voice-tone sense (alpecca/voice.py) deliberately never transcribes -- it's
ambient and reduces audio to loudness. This module is the consensual
counterpart: when the person explicitly holds the mic button and speaks *to*
Alpecca, their recording is transcribed locally with faster-whisper and then
discarded. Push-to-talk is the privacy model -- she only ever hears the words
you chose to say to her.

Degradation contract, same as every sense: faster-whisper missing or the model
failing to load latches the module off and every call returns None; a single
bad audio blob just returns None without latching, because one undecodable
recording doesn't mean the ears are broken.
"""
from __future__ import annotations

import io
from typing import Optional

from config import Hearing as HearingCfg

_model = None
_ready: Optional[bool] = None   # None = untried, then True/False


def available() -> bool:
    """Whether the ears are (or could be) working. Tries to load on first ask."""
    return _ensure_model() is not None


def _ensure_model():
    global _model, _ready
    if _ready is False:
        return None
    if _model is None:
        try:
            from faster_whisper import WhisperModel
            # int8 on CPU keeps the model small and fast enough for short
            # push-to-talk clips; first call downloads the model weights.
            _model = WhisperModel(HearingCfg.WHISPER_MODEL,
                                  device="cpu", compute_type="int8")
            _ready = True
        except Exception as exc:
            # Latch off, but say WHY once -- a silent failure here is the
            # "(didn't catch that)" message with no way to diagnose it. The
            # usual causes: faster-whisper installed in a different Python than
            # the server runs, or the model download being blocked.
            import traceback, sys
            print(f"[hearing] couldn't load Whisper ({HearingCfg.WHISPER_MODEL}): "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc()
            _ready = False
            return None
    return _model


def transcribe(audio_bytes: bytes) -> Optional[str]:
    """Turn one recorded utterance into text, or None if we couldn't.

    Accepts whatever container the browser's MediaRecorder produced (webm/ogg/
    wav) -- faster-whisper's PyAV decoding handles the demuxing.
    """
    model = _ensure_model()
    if model is None or not audio_bytes:
        return None
    try:
        segments, _info = model.transcribe(io.BytesIO(audio_bytes), beam_size=1)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text or None
    except Exception as exc:
        # One bad blob isn't a broken ear -- don't latch. But print it, so a
        # decode problem (e.g. PyAV not present to read the browser's webm)
        # isn't invisible.
        import sys
        print(f"[hearing] transcribe failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return None
