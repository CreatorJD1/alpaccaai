"""Persistent F5-TTS worker for Alpecca.

The CLI path is correct but slow because every sentence imports Python, loads
Vocos, loads the 1.35 GB F5 checkpoint, then exits. This worker keeps F5 and the
vocoder resident so normal House HQ speech pays only inference time.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import F5_WORKER_HOST, F5_WORKER_PORT, OPEN_TTS_DEVICE, OPEN_TTS_NFE_STEP
from alpecca import open_tts

_lock = threading.Lock()
_ready = False
_load_error = ""
_model = None
_vocoder = None
_load_seconds = 0.0


def _noop(*_args, **_kwargs):
    return None


class _Progress:
    @staticmethod
    def tqdm(iterable, *_args, **_kwargs):
        return iterable


_progress = _Progress()


class _DiscardWriter:
    """Drop third-party inference chatter that may include synthesized text."""

    @staticmethod
    def write(value: str) -> int:
        return len(value)

    @staticmethod
    def flush() -> None:
        return None


_discard_writer = _DiscardWriter()


def _normalize_waveform(wave, requested_gain: float = 1.0):
    """Scale an F5 waveform before PCM encoding so WAV output cannot clip."""

    import numpy as np

    if hasattr(wave, "detach"):
        wave = wave.detach().float().cpu().numpy()
    samples = np.asarray(wave, dtype=np.float32)
    if samples.size == 0 or not np.isfinite(samples).all():
        raise RuntimeError("F5 produced an invalid waveform")
    input_peak = float(np.max(np.abs(samples)))
    requested_gain = max(0.55, min(1.2, float(requested_gain)))
    samples = samples * requested_gain
    gained_peak = float(np.max(np.abs(samples)))
    limiter_gain = 1.0
    if gained_peak > 0.92:
        limiter_gain = 0.92 / gained_peak
        samples = samples * limiter_gain
    applied_gain = requested_gain * limiter_gain
    output_peak = float(np.max(np.abs(samples)))
    return samples, input_peak, applied_gain, limiter_gain, output_peak


def _controls(speed: float = 1.0, gain: float = 1.0, style: str = "present") -> dict:
    """Validate remote controls and map style to supported F5 parameters."""
    speed = max(0.8, min(1.2, float(speed)))
    gain = max(0.55, min(1.2, float(gain)))
    style = str(style or "present").strip().lower()[:24]
    profiles = {
        "bright": (2.1, -0.8),
        "spark": (2.1, -0.75),
        "curious": (2.05, -0.85),
        "close": (1.85, -0.95),
        "soft": (1.75, -1.0),
        "hushed": (1.7, -1.0),
        "small": (1.7, -1.0),
        "reserved": (1.8, -1.0),
        "careful": (2.1, -0.85),
        "tight": (2.2, -0.75),
        "drowsy": (1.7, -1.0),
        "searching": (2.0, -0.9),
        "present": (2.0, -1.0),
    }
    cfg_strength, sway_sampling_coef = profiles.get(style, profiles["present"])
    return {
        "speed": round(speed, 3),
        "gain": round(gain, 3),
        "style": style if style in profiles else "present",
        "cfg_strength": cfg_strength,
        "sway_sampling_coef": sway_sampling_coef,
    }


def load_once() -> None:
    global _ready, _load_error, _model, _vocoder, _load_seconds
    if _ready:
        return
    started = time.perf_counter()
    try:
        from f5_tts.infer.utils_infer import load_model, load_vocoder
        from f5_tts.model import DiT

        cfg = dict(dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512, conv_layers=4)
        _vocoder = load_vocoder(device=OPEN_TTS_DEVICE)
        _model = load_model(
            DiT,
            cfg,
            str(open_tts.LOCAL_CKPT),
            vocab_file=str(open_tts.LOCAL_VOCAB),
            device=OPEN_TTS_DEVICE,
        )
        _ready = True
        _load_error = ""
    except Exception as exc:
        _load_error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        _load_seconds = round(time.perf_counter() - started, 3)


def synth(
    text: str,
    ref_audio: str,
    ref_text: str,
    nfe_step: int,
    *,
    speed: float = 1.0,
    gain: float = 1.0,
    style: str = "present",
) -> tuple[bytes, dict]:
    load_once()
    started = time.perf_counter()
    from f5_tts.infer.utils_infer import infer_process, preprocess_ref_audio_text
    import soundfile as sf

    applied = _controls(speed, gain, style)
    with _lock:
        # F5's helpers print ref_text/gen_text even when show_info is disabled.
        # Those strings can contain private conversation, so suppress only the
        # library output while the outer handler retains content-free failures.
        with contextlib.redirect_stdout(_discard_writer), contextlib.redirect_stderr(
            _discard_writer
        ):
            ref_audio2, ref_text2 = preprocess_ref_audio_text(
                ref_audio,
                ref_text,
                show_info=_noop,
            )
            wave, sr, _spectrogram = infer_process(
                ref_audio2,
                ref_text2,
                text,
                _model,
                _vocoder,
                show_info=_noop,
                progress=_progress,
                nfe_step=max(4, int(nfe_step or OPEN_TTS_NFE_STEP)),
                speed=applied["speed"],
                cfg_strength=applied["cfg_strength"],
                sway_sampling_coef=applied["sway_sampling_coef"],
                device=OPEN_TTS_DEVICE,
            )
    if wave is None:
        raise RuntimeError("F5 produced no waveform")
    wave, input_peak, applied_gain, limiter_gain, output_peak = _normalize_waveform(
        wave, applied["gain"]
    )
    buf = io.BytesIO()
    sf.write(buf, wave, sr, format="WAV")
    return buf.getvalue(), {
        "engine": "f5-tts-worker",
        "seconds": round(time.perf_counter() - started, 3),
        "load_seconds": _load_seconds,
        "sample_rate": sr,
        "bytes": buf.tell(),
        "input_peak": round(input_peak, 4),
        "normalization_gain": round(limiter_gain, 4),
        "output_peak": round(output_peak, 4),
        "applied": {
            **applied,
            "gain": round(applied_gain, 4),
            "requested_gain": applied["gain"],
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "AlpeccaF5Worker/1.0"

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.startswith("/health"):
            self._json(200, {
                "ok": _ready,
                "ready": _ready,
                "loading_error": _load_error,
                "load_seconds": _load_seconds,
                "device": OPEN_TTS_DEVICE,
                "nfe_step": OPEN_TTS_NFE_STEP,
            })
            return
        if self.path.startswith("/warm"):
            try:
                load_once()
                self._json(200, {"ok": True, "ready": True, "load_seconds": _load_seconds})
            except Exception as exc:
                self._json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if not self.path.startswith("/synth"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size).decode("utf-8-sig") or "{}")
            audio, meta = synth(
                str(body.get("text") or ""),
                str(body.get("ref_audio") or ""),
                str(body.get("ref_text") or ""),
                int(body.get("nfe_step") or OPEN_TTS_NFE_STEP),
                speed=float(body.get("speed") or 1.0),
                gain=float(body.get("gain") or 1.0),
                style=str(body.get("style") or "present"),
            )
        except Exception as exc:
            tb = traceback.format_exc()
            print(f"[f5-worker] synth failed: {tb}", flush=True)
            self._json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": tb[-1200:]})
            return
        meta_json = json.dumps(meta, ensure_ascii=True)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(audio)))
        self.send_header("X-Alpecca-F5-Worker", meta_json[:400])
        self.end_headers()
        self.wfile.write(audio)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[f5-worker] {self.address_string()} {fmt % args}", flush=True)


def main() -> int:
    print(f"[f5-worker] starting on http://{F5_WORKER_HOST}:{F5_WORKER_PORT}", flush=True)
    print("[f5-worker] loading F5 once...", flush=True)
    try:
        load_once()
        print(f"[f5-worker] ready in {_load_seconds}s", flush=True)
    except Exception as exc:
        print(f"[f5-worker] initial load failed: {type(exc).__name__}: {exc}", flush=True)
    httpd = ThreadingHTTPServer((F5_WORKER_HOST, F5_WORKER_PORT), Handler)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
