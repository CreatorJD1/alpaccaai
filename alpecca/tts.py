"""Her voice: server-side text-to-speech, free and local, with graceful fallback.

Two free engines, picked automatically (ALPECCA_TTS_BACKEND overrides):
  - kokoro : the best free LOCAL voice -- Kokoro-82M, natural, runs on CPU or the
             (now-free) GPU. Needs the `kokoro` + `soundfile` packages.
  - edge   : Microsoft's neural voices via `edge-tts` -- natural, no model, uses
             the network. The always-works fallback.

If neither is installed, `synth()` returns None and the UI falls back to the
browser's built-in voice, so this can only ever improve things. Her voice also
carries emotion: pitch, pace, and volume shift with her real mood at speak-time.

`synth()` is synchronous; the server calls it off the event loop via
asyncio.to_thread (which also lets the async edge engine run cleanly).
"""
from __future__ import annotations

import io
import os
import sys

from config import (TTS_BACKEND, TTS_VOICE, TTS_RATE, TTS_PITCH,
                    KOKORO_VOICE, KOKORO_PITCH)


# --- emotion -> voice dynamics (shared by the engines) ----------------------
def _num(s: str) -> int:
    """Pull the signed number out of an edge param like '+18Hz' or '-6%'."""
    try:
        import re
        m = re.search(r"-?\d+", str(s))
        return int(m.group()) if m else 0
    except Exception:
        return 0


def voice_params_for(state) -> dict:
    """Edge rate/pitch/volume blended from her real affect, so her voice carries
    emotion: livelier and brighter when she's up, softer and lower when uneasy or
    quiet. Layered on the anime-leaning base in config."""
    arousal, valence, intensity = 0.5, 0.0, 0.5
    if state is not None:
        try:
            from alpecca import affect as affect_mod
            a = affect_mod.affect(state)
            arousal = float(getattr(a, "arousal", 0.5))
            valence = float(getattr(a, "valence", 0.0))      # -1..+1
            intensity = float(getattr(a, "intensity", 0.5))
        except Exception:
            pass
    base_rate, base_pitch = _num(TTS_RATE), _num(TTS_PITCH)
    rate = base_rate + round((arousal - 0.5) * 44)           # ~ -22%..+22%
    pitch = base_pitch + round(valence * 26 + (arousal - 0.5) * 18)
    volume = round((intensity - 0.5) * 36)                   # ~ -18%..+18%
    return {"rate": f"{rate:+d}%", "pitch": f"{pitch:+d}Hz", "volume": f"{volume:+d}%"}


# --- Kokoro (best free local voice) -----------------------------------------
_kokoro = None
_kokoro_ready = None        # None untried, then True/False (latched)


def _kokoro_pipeline():
    global _kokoro, _kokoro_ready
    if _kokoro_ready is False:
        return None
    if _kokoro is None:
        try:
            from kokoro import KPipeline
            _kokoro = KPipeline(lang_code="a")    # 'a' = American English
            _kokoro_ready = True
        except Exception as exc:
            print(f"[tts] kokoro unavailable ({type(exc).__name__}: {exc}); "
                  f"install with: python -m pip install kokoro soundfile  "
                  f"(and espeak-ng on the system).", file=sys.stderr)
            _kokoro_ready = False
            return None
    return _kokoro


def _varispeed(audio, factor):
    """Resample by `factor` (linear interp): factor>1 shortens + raises pitch.
    Used with a compensating generation speed to pitch-shift while keeping tempo
    roughly natural -- a clean, dependency-free way to brighten her toward anime."""
    import numpy as np
    if factor is None or abs(factor - 1.0) < 1e-3 or len(audio) < 4:
        return audio
    n = len(audio)
    idx = np.arange(0, n - 1, factor)
    lo = np.floor(idx).astype(np.int64)
    frac = (idx - lo).astype(np.float32)
    return (audio[lo] * (1.0 - frac) + audio[lo + 1] * frac).astype(np.float32)


def _kokoro_dynamics(state):
    """HER voice control: pitch + volume she sets from her own live emotion,
    around her anime baseline (KOKORO_PITCH). Grounded -- the user doesn't tune
    this; it regresses continuously toward her real affect. Returns
    (pitch_factor, gain, arousal, valence, intensity)."""
    base = KOKORO_PITCH if (KOKORO_PITCH and KOKORO_PITCH > 0) else 1.0
    arousal, valence, intensity = 0.5, 0.0, 0.5
    if state is not None:
        try:
            from alpecca import affect as affect_mod
            a = affect_mod.affect(state)
            arousal = float(getattr(a, "arousal", 0.5))
            valence = float(getattr(a, "valence", 0.0))
            intensity = float(getattr(a, "intensity", 0.5))
        except Exception:
            pass
    # Brighter/higher when roused or glad; softer/lower when calm or low. Bounded
    # so she stays herself -- never squeaky, never droning.
    pitch = base * (1.0 + (arousal - 0.5) * 0.10 + valence * 0.05)
    pitch = max(0.88, min(1.30, pitch))
    gain = max(0.65, min(1.35, 1.0 + (intensity - 0.5) * 0.4))
    return pitch, gain, arousal, valence, intensity


def voice_state(state=None) -> dict:
    """A read-only readout of how she's steering her own voice right now -- for
    the in-app Voice visualizer. Pitch/volume are derived live from her emotion."""
    pitch, gain, arousal, valence, intensity = _kokoro_dynamics(state)
    base = KOKORO_PITCH if (KOKORO_PITCH and KOKORO_PITCH > 0) else 1.0
    tone = "bright" if pitch > base * 1.03 else ("soft" if pitch < base * 0.97 else "even")
    return {
        "voice": KOKORO_VOICE or "af_heart",
        "baseline": round(base, 3),
        "pitch": round(pitch, 3),
        "volume": round(gain, 3),
        "tone": tone,
        "arousal": round(arousal, 3),
        "valence": round(valence, 3),
        "intensity": round(intensity, 3),
    }


def _synth_kokoro(text: str, state=None):
    pipe = _kokoro_pipeline()
    if pipe is None:
        return None
    import numpy as np
    import soundfile as sf
    # Kokoro uses its own voice names (af_heart...) -- never the edge TTS_VOICE.
    # Pitch/volume are HERS, modulated from her emotion around the anime baseline:
    # generate a touch slower, varispeed UP by the same factor (pitch rises, pace
    # stays natural), then apply her chosen volume gain.
    voice = KOKORO_VOICE or "af_heart"
    pitch, gain, _a, _v, _i = _kokoro_dynamics(state)
    gen_speed = 1.0 / pitch
    chunks = [audio for _gs, _ps, audio in pipe(text, voice=voice, speed=gen_speed)]
    if not chunks:
        return None
    audio = np.concatenate(chunks)
    audio = _varispeed(audio, pitch)
    audio = np.clip(audio * gain, -1.0, 1.0).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, audio, 24000, format="WAV")
    return ("audio/wav", buf.getvalue())


# --- edge-tts (always-works neural fallback) --------------------------------
def _synth_edge(text: str, state=None):
    try:
        import asyncio
        import edge_tts
    except Exception:
        return None
    # A bright young female voice + a pitch lift reads as "anime girl" rather
    # than flat newsreader. Only honor an edge-style voice name (a Kokoro name
    # like af_heart isn't a valid edge voice); else default to Jenny.
    voice = TTS_VOICE if (TTS_VOICE and "Neural" in TTS_VOICE) else "en-US-JennyNeural"
    p = voice_params_for(state)              # emotion: tone/pace/volume from mood

    async def _go() -> bytes:
        out = io.BytesIO()
        com = edge_tts.Communicate(text, voice, rate=p["rate"],
                                   pitch=p["pitch"], volume=p["volume"])
        async for chunk in com.stream():
            if chunk.get("type") == "audio":
                out.write(chunk["data"])
        return out.getvalue()

    try:
        data = asyncio.run(_go())
        return ("audio/mpeg", data) if data else None
    except Exception as exc:
        print(f"[tts] edge-tts failed ({type(exc).__name__}: {exc}); "
              f"install with: python -m pip install edge-tts", file=sys.stderr)
        return None


def synth(text: str, state=None):
    """Return (mime_type, audio_bytes) for `text`, or None to let the browser
    voice handle it. `state` is her live EmotionalState so the voice carries
    emotion. ALPECCA_TTS_BACKEND: auto (default) prefers Kokoro then edge;
    'kokoro'/'edge' force one; 'browser'/'off' disable server TTS."""
    text = (text or "").strip()
    if not text:
        return None
    backend = (TTS_BACKEND or "auto").lower()
    print(f"[tts] synth: backend={backend!r} "
          f"(env ALPECCA_TTS_BACKEND={os.environ.get('ALPECCA_TTS_BACKEND')!r})",
          file=sys.stderr)
    if backend in ("off", "browser", "none"):
        print("[tts] backend disables server TTS -> browser voice", file=sys.stderr)
        return None
    if backend == "kokoro":
        order = (_synth_kokoro,)
    elif backend == "edge":
        order = (_synth_edge,)
    else:                                     # auto: best local, then neural
        order = (_synth_kokoro, _synth_edge)
    for fn in order:
        try:
            r = fn(text, state)
            if r:
                print(f"[tts] -> spoke via {fn.__name__}", file=sys.stderr)
                return r
            print(f"[tts] {fn.__name__} returned None", file=sys.stderr)
        except Exception as exc:
            print(f"[tts] {fn.__name__} errored: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
    print("[tts] no engine produced audio -> browser voice", file=sys.stderr)
    return None
