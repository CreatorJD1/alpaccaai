"""Small CPU-only Silero ONNX adapter for Discord PCM streams.

The adapter deliberately imports NumPy and ONNX Runtime lazily. It uses the
official model bundled by ``silero-vad`` without importing that package (which
would also import PyTorch). One detector owns recurrent state for one speaker;
all detectors share the immutable ONNX inference session.
"""
from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path
from typing import Callable


TARGET_SAMPLE_RATE = 16_000
FRAME_SAMPLES = 512
CONTEXT_SAMPLES = 64
FRAME_SECONDS = FRAME_SAMPLES / TARGET_SAMPLE_RATE
SOURCE_SAMPLE_RATE = 48_000
SOURCE_CHANNELS = 2
SOURCE_SAMPLE_WIDTH = 2


def _enabled() -> bool:
    return os.environ.get("ALPECCA_DISCORD_SILERO_VAD", "1").strip().lower() not in {
        "", "0", "false", "no", "off",
    }


def model_path() -> Path | None:
    configured = os.environ.get("ALPECCA_SILERO_VAD_MODEL", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_file() else None
    spec = importlib.util.find_spec("silero_vad")
    if spec is None or not spec.origin:
        return None
    path = Path(spec.origin).resolve().parent / "data" / "silero_vad.onnx"
    return path if path.is_file() else None


def readiness() -> dict[str, object]:
    path = model_path()
    runtime = importlib.util.find_spec("onnxruntime") is not None
    numpy = importlib.util.find_spec("numpy") is not None
    enabled = _enabled()
    return {
        "enabled": enabled,
        "status": "ready" if enabled and path and runtime and numpy else "fallback",
        "engine": "silero-onnx-cpu" if enabled and path and runtime and numpy else "packet-fallback",
        "model_available": bool(path),
        "onnxruntime": runtime,
        "numpy": numpy,
        "sample_rate": TARGET_SAMPLE_RATE,
        "frame_ms": round(FRAME_SECONDS * 1000),
    }


class SileroOnnxDetector:
    """Stateful VAD for one 48 kHz stereo signed-16 PCM speaker stream."""

    _session = None
    _session_path: Path | None = None
    _session_init_lock = threading.Lock()
    _inference_lock = threading.Lock()

    def __init__(self, *, session=None) -> None:
        import numpy as np

        self._np = np
        self._session = session if session is not None else self._shared_session()
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)
        self._source_tail = np.empty((0,), dtype=np.float32)
        self._target_buffer = np.empty((0,), dtype=np.float32)

    @classmethod
    def _shared_session(cls):
        path = model_path()
        if path is None:
            raise RuntimeError("Silero ONNX model is unavailable")
        with cls._session_init_lock:
            if cls._session is None or cls._session_path != path:
                import onnxruntime as ort

                cls._session = ort.InferenceSession(
                    str(path),
                    providers=["CPUExecutionProvider"],
                )
                cls._session_path = path
        return cls._session

    def reset(self) -> None:
        np = self._np
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)
        self._source_tail = np.empty((0,), dtype=np.float32)
        self._target_buffer = np.empty((0,), dtype=np.float32)

    def accept_pcm(self, pcm: bytes) -> tuple[float, ...]:
        """Return one probability for every complete 32 ms model frame."""
        if type(pcm) is not bytes or not pcm:
            return ()
        np = self._np
        raw = np.frombuffer(pcm, dtype="<i2")
        if raw.size % SOURCE_CHANNELS:
            raise ValueError("PCM must contain complete stereo frames")
        stereo = raw.reshape(-1, SOURCE_CHANNELS).astype(np.float32)
        mono = stereo.mean(axis=1) / 32768.0
        if self._source_tail.size:
            mono = np.concatenate((self._source_tail, mono))
        usable = (mono.size // 3) * 3
        self._source_tail = mono[usable:].copy()
        if usable:
            downsampled = mono[:usable].reshape(-1, 3).mean(axis=1)
            self._target_buffer = np.concatenate((self._target_buffer, downsampled))

        probabilities: list[float] = []
        while self._target_buffer.size >= FRAME_SAMPLES:
            frame = self._target_buffer[:FRAME_SAMPLES]
            self._target_buffer = self._target_buffer[FRAME_SAMPLES:]
            framed_input = np.concatenate((self._context, frame.reshape(1, -1)), axis=1)
            inputs = {
                "input": framed_input.astype(np.float32, copy=False),
                "state": self._state,
                "sr": np.asarray(TARGET_SAMPLE_RATE, dtype=np.int64),
            }
            with self._inference_lock:
                output, state = self._session.run(["output", "stateN"], inputs)
            self._state = np.asarray(state, dtype=np.float32)
            self._context = framed_input[:, -CONTEXT_SAMPLES:].copy()
            probabilities.append(float(np.asarray(output).reshape(-1)[0]))
        return tuple(probabilities)


def detector_factory() -> Callable[[], SileroOnnxDetector] | None:
    posture = readiness()
    if posture["status"] != "ready":
        return None
    try:
        # Load once here so a failed runtime/model never breaks the audio thread.
        session = SileroOnnxDetector._shared_session()
    except Exception:
        return None
    return lambda: SileroOnnxDetector(session=session)


__all__ = [
    "FRAME_SECONDS",
    "CONTEXT_SAMPLES",
    "SileroOnnxDetector",
    "detector_factory",
    "model_path",
    "readiness",
]
