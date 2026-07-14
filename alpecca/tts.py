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
import json
import re
import importlib.util
from pathlib import Path

from config import (TTS_BACKEND, TTS_VOICE, TTS_RATE, TTS_PITCH,
                    KOKORO_VOICE, KOKORO_PITCH, KOKORO_IDENTITY_LOCK)

_last_engine = ""
_last_error = ""
_last_modulation: dict = {}
_voice_reference_cache: dict | None = None
# 'auto' blends both engines by emotion: calm/everyday speech uses Kokoro
# af_heart (cleaner, more realistic), high-affect lines use the F5 voice clone
# (its strength). This cutoff (0..1, on max(intensity, arousal)) tunes the mix;
# lower = more F5, higher = more Kokoro.
VOICE_MIX_INTENSITY = float(os.environ.get("ALPECCA_VOICE_MIX_INTENSITY", "0.6"))
_VOICE_REFERENCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "voice_references"
    / "alpecca_voice_personality_profile.json"
)


def _voice_reference() -> dict:
    """Processed Jason-provided voice/personality target, if available."""
    global _voice_reference_cache
    if _voice_reference_cache is not None:
        return _voice_reference_cache
    try:
        payload = json.loads(_VOICE_REFERENCE_PATH.read_text(encoding="utf-8"))
        profile = payload.get("profile") if isinstance(payload, dict) else {}
        _voice_reference_cache = profile if isinstance(profile, dict) else {}
    except Exception:
        _voice_reference_cache = {}
    return _voice_reference_cache


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


def _naturalize_audio(audio, gain: float, warmth: float = 0.5, breath: float = 0.25):
    """Apply gentle level shaping without hard clipping.

    The old path multiplied then clipped at +/-1.0, which can make Kokoro peaks
    buzz and feel synthetic. A soft limiter plus tiny fade keeps af_heart intact
    while smoothing the edges that read as robotic.
    """
    import numpy as np
    if audio is None or len(audio) == 0:
        return audio
    shaped = np.asarray(audio, dtype=np.float32)
    shaped = shaped - float(np.mean(shaped))
    pre_peak = float(np.max(np.abs(shaped))) if len(shaped) else 0.0
    if pre_peak > 1.35:
        shaped = shaped * (1.0 / pre_peak)
    rms = float(np.sqrt(np.mean(np.square(shaped)))) if len(shaped) else 0.0
    target_rms = 0.115 + max(0.0, min(1.0, float(warmth))) * 0.025
    rms_gain = min(float(gain), target_rms / max(rms, 0.001))
    shaped = shaped * max(0.35, min(1.0, rms_gain))
    drive = 1.04 + max(0.0, min(1.0, float(warmth))) * 0.10
    shaped = np.tanh(shaped * drive) / np.tanh(drive)
    peak = float(np.max(np.abs(shaped))) if len(shaped) else 0.0
    if peak > 0.92:
        shaped = shaped * (0.92 / peak)
    fade_n = min(len(shaped) // 12, 420)
    if fade_n > 8:
        fade = np.linspace(0.0, 1.0, fade_n, dtype=np.float32)
        shaped[:fade_n] *= fade
        shaped[-fade_n:] *= fade[::-1]
    # Keep the waveform clean. Earlier builds added synthetic breath noise here,
    # but it could read as distortion after browser playback/compression.
    shaped = shaped - float(np.mean(shaped))
    final_peak = float(np.max(np.abs(shaped))) if len(shaped) else 0.0
    if final_peak > 0.94:
        shaped = shaped * (0.94 / final_peak)
    global _last_modulation
    _last_modulation = {
        **_last_modulation,
        "audio_pre_peak": round(pre_peak, 4),
        "audio_rms": round(rms, 4),
        "audio_final_peak": round(float(np.max(np.abs(shaped))) if len(shaped) else 0.0, 4),
        "audio_limiter": "soft-rms-dc-final-peak",
    }
    return shaped.astype(np.float32)


def _kokoro_dynamics(state):
    """HER voice control: pitch + volume she sets from her own live emotion,
    around her original Kokoro speaker identity. Grounded -- the user doesn't
    tune this; it regresses continuously toward her real affect."""
    base = KOKORO_PITCH if (KOKORO_PITCH and KOKORO_PITCH > 0) else 1.0
    arousal, valence, intensity = 0.5, 0.0, 0.5
    primary, tempo = "content", "measured"
    markup = {
        "rate_pct": 100,
        "pitch_semitones": 0,
        "volume": 0.8,
        "style": "present",
        "warmth": 0.5,
        "breath": 0.25,
    }
    if state is not None:
        try:
            from alpecca import affect as affect_mod
            a = affect_mod.affect(state)
            arousal = float(getattr(a, "arousal", 0.5))
            valence = float(getattr(a, "valence", 0.0))
            intensity = float(getattr(a, "intensity", 0.5))
            primary = str(getattr(a, "primary", "content"))
            tempo = str(getattr(a, "tempo", "measured"))
            markup = affect_mod.voice_markup(state)
        except Exception:
            pass
    # Identity-lock keeps af_heart recognizable while still letting emotion reach
    # the waveform. The prior path reported pitch in headers but avoided applying
    # it to locked Kokoro audio, which is why she could sound like one flat preset.
    expressivity = 1.0
    reference = _voice_reference()
    if reference:
        expressivity = 1.18
    if KOKORO_IDENTITY_LOCK:
        # Subtle emotion-driven pitch that still reads as af_heart. Widened from
        # the prior +-6% so mood is actually audible (Jason: more expressive +
        # a little pitch), while the clamp keeps her identity recognizable.
        pitch = base * (1.0 + float(markup.get("pitch_semitones", 0)) * 0.0155 * expressivity)
        pitch += (arousal - 0.5) * 0.022 * expressivity
        pitch += valence * 0.018 * expressivity
        pitch += {
            "joyful": 0.030,
            "playful": 0.030,
            "curious": 0.012,
            "content": -0.026,
            "affectionate": -0.034,
            "tender": -0.060,
            "wistful": -0.058,
            "lonely": -0.050,
            "withdrawn": -0.042,
            "sleepy": -0.056,
            "worried": -0.026,
            "anxious": -0.018,
        }.get(primary, 0.0)
        pitch = max(0.915, min(1.085, pitch))
    else:
        pitch = base * (1.0 + (arousal - 0.5) * 0.10 + valence * 0.05)
        pitch = max(0.88, min(1.30, pitch))
    warmth = round(float(markup.get("warmth", 0.5)), 3)
    breath = round(float(markup.get("breath", 0.25)), 3)
    natural_rate = float(markup.get("rate_pct", 100)) / 100.0
    # af_heart reads more natural a little under perfect machine tempo. Keep the
    # affect range, but bias measured speech toward a warmer, less robotic pace.
    speed = natural_rate - (0.035 if KOKORO_IDENTITY_LOCK else 0.0) - warmth * 0.012 + breath * 0.006
    if reference:
        # Jason's reference set favors a close, less robotic delivery. Keep the
        # af_heart identity locked, then bias pacing/softness and let emotion
        # push the range enough to be audible.
        speed -= 0.028
        breath = max(breath, 0.34)
    # Wider pacing swing so her emotional state carries in the delivery, not
    # just a near-flat tempo.
    if primary in {"anxious", "worried"}:
        speed += 0.055
    elif primary in {"tender", "wistful", "sleepy", "lonely"}:
        speed -= 0.065
    elif primary in {"joyful", "playful"}:
        speed += 0.030
    speed = max(0.66, min(1.22, speed))
    gain = max(0.52, min(1.10, 0.66 + float(markup.get("volume", 0.8)) * 0.36))
    return {
        "pitch": pitch,
        "volume": gain,
        "speed": speed,
        "arousal": arousal,
        "valence": valence,
        "intensity": intensity,
        "primary": primary,
        "tempo": tempo,
        "rate_pct": int(markup.get("rate_pct", round(speed * 100))),
        "pitch_semitones": int(markup.get("pitch_semitones", 0)),
        "style": str(markup.get("style", "present")),
        "warmth": warmth,
        "breath": breath,
        "natural_voice": True,
        "identity_lock": bool(KOKORO_IDENTITY_LOCK),
        "profile": "af_heart_original_modulated" if KOKORO_IDENTITY_LOCK else "experimental_pitch_shift",
        "reference_loaded": bool(reference),
        "modulation_strength": round(expressivity, 3),
    }


def voice_state(state=None) -> dict:
    """A read-only readout of how she's steering her own voice right now -- for
    the in-app Voice visualizer. Pitch/volume are derived live from her emotion."""
    dyn = _kokoro_dynamics(state)
    engines = engine_status()
    open_tts_status = engines.get("open_tts") if isinstance(engines.get("open_tts"), dict) else {}
    open_ready = bool(open_tts_status.get("ready"))
    active_engine = _last_engine or ("f5-tts-worker" if open_ready else "")
    pitch, gain, speed = dyn["pitch"], dyn["volume"], dyn["speed"]
    arousal, valence, intensity = dyn["arousal"], dyn["valence"], dyn["intensity"]
    base = KOKORO_PITCH if (KOKORO_PITCH and KOKORO_PITCH > 0) else 1.0
    tone = "bright" if pitch > base * 1.03 else ("soft" if pitch < base * 0.97 else "even")
    return {
        "voice": KOKORO_VOICE or "af_heart",
        "baseline": round(base, 3),
        "pitch": round(pitch, 3),
        "volume": round(gain, 3),
        "speed": round(speed, 3),
        "tone": tone,
        "arousal": round(arousal, 3),
        "valence": round(valence, 3),
        "intensity": round(intensity, 3),
        "primary": dyn["primary"],
        "tempo": dyn["tempo"],
        "rate_pct": dyn["rate_pct"],
        "pitch_semitones": dyn["pitch_semitones"],
        "style": dyn["style"],
        "warmth": dyn["warmth"],
        "breath": dyn["breath"],
        "personality": "original Alpecca: warm, curious, gently animated",
        "natural_voice": dyn.get("natural_voice", True),
        "identity_lock": dyn["identity_lock"],
        "profile": dyn["profile"],
        "reference_profile_loaded": dyn.get("reference_loaded", False),
        "modulation_strength": dyn.get("modulation_strength", 1.0),
        "reference_target": _voice_reference().get("target_quality", {}),
        "house_hq_embodiment_reference": _voice_reference().get("house_hq_embodiment_reference", {}),
        "reference_acoustics": _voice_reference().get("acoustic_summary", {}),
        "backend": (TTS_BACKEND or "auto").lower(),
        "active_engine": active_engine,
        "engines": engines,
        "last_engine": active_engine,
        "last_error": _last_error,
        "last_modulation": _last_modulation,
    }


def engine_status() -> dict:
    """What voice engines are available without loading a model.

    This is intentionally import-spec based so polling /voice stays cheap and
    does not cold-start Kokoro just to draw the Voice panel.
    """
    backend = (TTS_BACKEND or "auto").lower()
    open_status = __import__("alpecca.open_tts", fromlist=["status"]).status()
    open_ready = bool(open_status.get("ready"))
    return {
        "backend": backend,
        "server_enabled": backend not in ("off", "browser", "none"),
        "primary": "f5-tts-worker" if open_ready else ("kokoro" if importlib.util.find_spec("kokoro") else "edge"),
        "open_tts": open_status,
        "open_tts_ready": open_ready,
        "f5_worker": (open_status.get("worker") or {}),
        "kokoro": bool(importlib.util.find_spec("kokoro") and importlib.util.find_spec("soundfile")),
        "edge": bool(importlib.util.find_spec("edge_tts")),
        "browser_fallback": True,
    }


def _synth_kokoro(text: str, state=None):
    pipe = _kokoro_pipeline()
    if pipe is None:
        return None
    import numpy as np
    import soundfile as sf
    # Kokoro uses its own voice names (af_heart...) -- never the edge TTS_VOICE.
    # Pitch/volume are HERS, modulated from her emotion around the anime baseline:
    # by default preserve the original af_heart timbre, then apply subtle speed
    # and volume. Experimental pitch shifting is opt-in.
    voice = KOKORO_VOICE or "af_heart"
    dyn = _kokoro_dynamics(state)
    pitch, gain, speed = dyn["pitch"], dyn["volume"], dyn["speed"]
    shaped = _shape_text_for_alpecca_voice(text, dyn)
    segments = _alpecca_voice_segments(shaped, dyn)
    chunks = []
    for seg_text, seg_speed, pause_ms in segments:
        if not seg_text:
            continue
        # Generate at a compensating speed, then varispeed back. Final tempo
        # stays near seg_speed while the small pitch color becomes real audio.
        gen_speed = max(0.55, min(1.35, seg_speed / max(0.05, pitch)))
        chunks.extend(audio for _gs, _ps, audio in pipe(seg_text, voice=voice, speed=gen_speed))
        if pause_ms > 0:
            chunks.append(np.zeros(int(24000 * pause_ms / 1000), dtype=np.float32))
    if not chunks:
        return None
    audio = np.concatenate(chunks)
    audio = _varispeed(audio, pitch)
    audio = _naturalize_audio(audio, gain, dyn.get("warmth", 0.5), dyn.get("breath", 0.25))
    buf = io.BytesIO()
    sf.write(buf, audio, 24000, format="WAV")
    return ("audio/wav", buf.getvalue())


def _alpecca_voice_segments(text: str, dyn: dict) -> list[tuple[str, float, int]]:
    """Split a reply into a few prosody chunks Kokoro can actually express.

    Kokoro exposes speaker and speed, not a full emotional control bus. Segmenting
    lets Alpecca vary pacing and pauses inside one sentence while preserving
    af_heart. Capped to keep /tts fast.
    """
    clean = " ".join((text or "").split())
    if not clean:
        return []
    primary = str(dyn.get("primary") or "content")
    base_speed = float(dyn.get("speed") or 0.96)
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+|(?<=,)\s+", clean) if p.strip()]
    if len(parts) <= 1:
        parts = [clean]
    if len(parts) > 5:
        head = parts[:4]
        tail = " ".join(parts[4:])
        parts = head + ([tail] if tail else [])

    out: list[tuple[str, float, int]] = []
    for i, part in enumerate(parts):
        speed = base_speed
        pause = 70
        if primary in {"anxious", "worried"}:
            speed += 0.025 if i % 2 == 0 else -0.015
            pause = 95 if part.endswith(("?", "!")) else 55
        elif primary in {"tender", "affectionate", "wistful", "lonely"}:
            speed -= 0.025 if i % 2 == 0 else 0.0
            pause = 150 if part.endswith((".", "?", "…")) else 95
        elif primary in {"joyful", "playful", "curious"}:
            speed += 0.035 if i % 2 == 0 else 0.015
            pause = 45
        elif primary in {"sleepy", "withdrawn"}:
            speed -= 0.055
            pause = 180
        out.append((part, max(0.62, min(1.24, speed)), pause))
    if out:
        out[-1] = (out[-1][0], out[-1][1], 0)
    return out


def _shape_text_for_alpecca_voice(text: str, dyn: dict) -> str:
    """Light text shaping for Kokoro.

    Kokoro does not expose the same SSML controls as edge-tts, so punctuation is
    the most reliable free way to recover Alpecca's original personality without
    swapping speaker identity. Keep it conservative: no new facts, no fake
    catchphrases, only pause/tempo hints from the same voice markup.
    """
    clean = " ".join((text or "").split())
    if not clean:
        return clean
    primary = str(dyn.get("primary") or "content")
    style = str(dyn.get("style") or "present")
    if primary in {"tender", "affectionate", "wistful"} or style in {"soft", "close"}:
        clean = clean.replace(". ", ".  ")
        clean = clean.replace("? ", "?  ")
    elif primary in {"joyful", "playful", "curious"} or style in {"bright", "curious"}:
        clean = clean.replace(". ", ". ")
    elif primary in {"sleepy", "withdrawn", "lonely"}:
        clean = clean.replace(". ", "... ")
        clean = clean.replace(", ", ",  ")
    elif primary in {"anxious", "worried"}:
        clean = clean.replace(". ", ". ")
        clean = clean.replace("; ", ". ")
    return clean


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


def _prefers_clone_voice(state=None) -> bool:
    """Whether this moment is emotional enough to route to the F5 voice clone.

    The 'auto' backend blends both engines: F5 voice-cloning for high-affect
    lines (where its emotional reference cloning shines) and Kokoro af_heart for
    calm/everyday speech (cleaner, less artifact-prone). Returns True when her
    live emotion crosses VOICE_MIX_INTENSITY so F5 leads; otherwise Kokoro leads.
    """
    if state is None:
        return False
    try:
        dyn = _kokoro_dynamics(state)
    except Exception:
        return False
    return max(float(dyn.get("intensity", 0.5)),
               float(dyn.get("arousal", 0.5))) >= VOICE_MIX_INTENSITY


def synth(text: str, state=None, *, backend_override: str = ""):
    """Return (mime_type, audio_bytes) for `text`, or None to let the browser
    voice handle it. `state` is her live EmotionalState so the voice carries
    emotion. ALPECCA_TTS_BACKEND: auto (default) blends the F5 clone and Kokoro
    by emotion; 'kokoro'/'edge'/'f5' force one; 'browser'/'off' disable server
    TTS. Trusted channel bridges may pin one engine for a request so a bad
    clone render cannot silently replace the channel's established voice."""
    text = (text or "").strip()
    global _last_engine, _last_error, _last_modulation
    _last_engine = ""
    _last_error = ""
    if not text:
        return None
    backend = (backend_override or TTS_BACKEND or "auto").strip().lower()
    print(f"[tts] synth: backend={backend!r} "
          f"(env ALPECCA_TTS_BACKEND={os.environ.get('ALPECCA_TTS_BACKEND')!r})",
          file=sys.stderr)
    if backend in ("off", "browser", "none"):
        print("[tts] backend disables server TTS -> browser voice", file=sys.stderr)
        _last_error = "server TTS disabled by backend setting"
        return None
    if backend in ("open", "f5", "f5-tts"):
        from alpecca import open_tts

        order = (open_tts.synth,)
    elif backend == "kokoro":
        # Kokoro af_heart is her actual voice profile. Do not substitute a
        # different server voice and label it as Alpecca.
        order = (_synth_kokoro,)
    elif backend == "edge":
        order = (_synth_edge,)
    else:                                     # auto: blend F5 clone + Kokoro by emotion
        from alpecca import open_tts

        if open_tts.ready():
            # High-affect moments lead with the F5 clone; calm/everyday speech
            # leads with Kokoro af_heart. Whichever leads, the other stays as
            # fallback so a single-engine failure still speaks.
            order = ((open_tts.synth, _synth_kokoro)
                     if _prefers_clone_voice(state)
                     else (_synth_kokoro, open_tts.synth))
        else:
            order = (_synth_kokoro,)
    for fn in order:
        try:
            r = fn(text, state)
            if r:
                metadata = {}
                if isinstance(r, tuple) and len(r) == 3:
                    mime, data, metadata = r
                    r = (mime, data)
                _last_engine = str(metadata.get("engine") or fn.__name__.replace("_synth_", ""))
                _last_error = ""
                _last_modulation = {
                    k: voice_state(state).get(k)
                    for k in (
                        "voice", "pitch", "volume", "speed", "tone",
                        "primary", "tempo", "rate_pct", "pitch_semitones",
                        "style", "warmth", "breath", "personality",
                        "identity_lock", "profile", "modulation_strength",
                    )
                }
                if metadata:
                    _last_modulation.update({
                        "engine_profile": metadata.get("profile", ""),
                        "reference": metadata.get("reference", {}),
                    })
                print(f"[tts] -> spoke via {fn.__name__}", file=sys.stderr)
                return r
            print(f"[tts] {fn.__name__} returned None", file=sys.stderr)
            if fn.__name__ == "synth":
                try:
                    from alpecca import open_tts

                    _last_error = open_tts.status().get("last_error") or f"{fn.__name__} returned no audio"
                except Exception:
                    _last_error = f"{fn.__name__} returned no audio"
            else:
                _last_error = f"{fn.__name__} returned no audio"
        except Exception as exc:
            _last_error = f"{type(exc).__name__}: {exc}"
            print(f"[tts] {fn.__name__} errored: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
    print("[tts] no engine produced audio -> browser voice", file=sys.stderr)
    return None
