"""Persistent F5-TTS worker for Alpecca.

The CLI path is correct but slow because every sentence imports Python, loads
Vocos, loads the 1.35 GB F5 checkpoint, then exits. This worker keeps F5 and the
vocoder resident so normal House HQ speech pays only inference time.
"""
from __future__ import annotations

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


def synth(text: str, ref_audio: str, ref_text: str, nfe_step: int) -> tuple[bytes, dict]:
    load_once()
    started = time.perf_counter()
    from f5_tts.infer.utils_infer import infer_process, preprocess_ref_audio_text
    import soundfile as sf

    ref_audio2, ref_text2 = preprocess_ref_audio_text(ref_audio, ref_text, show_info=_noop)
    with _lock:
        wave, sr, _spectrogram = infer_process(
            ref_audio2,
            ref_text2,
            text,
            _model,
            _vocoder,
            show_info=_noop,
            progress=_progress,
            nfe_step=max(4, int(nfe_step or OPEN_TTS_NFE_STEP)),
            device=OPEN_TTS_DEVICE,
        )
    if wave is None:
        raise RuntimeError("F5 produced no waveform")
    buf = io.BytesIO()
    sf.write(buf, wave, sr, format="WAV")
    return buf.getvalue(), {
        "engine": "f5-tts-worker",
        "seconds": round(time.perf_counter() - started, 3),
        "load_seconds": _load_seconds,
        "sample_rate": sr,
        "bytes": buf.tell(),
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
