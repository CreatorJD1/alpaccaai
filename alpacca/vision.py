"""Sight: Alpacca sees images, the screen, and (opt-in) your face.

Three capabilities share one mechanism -- a local Ollama vision model turns
pixels into a short text description, and only the text survives:

  1. **Chat images.** The person attaches a picture; Alpacca describes it to
     herself and responds to what she actually saw.
  2. **Screen sight** (ALPACCA_SIGHT=1). A slow background glimpse of the
     screen, so "what you can sense the person doing" goes beyond the window
     title to what's genuinely on it.
  3. **Expression sense** (ALPACCA_FACE=1). A periodic webcam read distilled
     to a single expression label; a tired or stressed face feeds the same
     `weary_face` fatigue signal pathway as late nights do.

The grounding rule holds throughout: she only ever claims to have seen what
the vision model actually reported. If the model isn't pulled or the hardware
is missing, each capability quietly reports nothing -- same degradation
contract as every other sense.

Privacy: frames live in memory just long enough for one model call, then
they're gone. No image is ever written to disk by this module.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from config import Vision as VisionCfg, OLLAMA_HOST


# --- The shared eye: one image in, a short description out ------------------

_DESCRIBE_PROMPT = (
    "Describe this image in two or three sentences, plainly and concretely: "
    "what it shows, any visible text worth knowing, and the overall feel."
)

_SCREEN_PROMPT = (
    "This is a screenshot of someone's computer screen. In one or two "
    "sentences: what are they working on or looking at right now?"
)

_FACE_PROMPT = (
    "Look at the person in this image. Answer with exactly one word for "
    "their facial expression, chosen from: tired, stressed, sad, happy, "
    "calm, focused, none."
)


def describe_image(image_bytes: bytes, prompt: str = _DESCRIBE_PROMPT) -> Optional[str]:
    """One vision-model call: bytes in, short description out, None on any
    failure (model not pulled, Ollama down). Failures are normal life here --
    callers treat None as 'I couldn't make it out.'"""
    try:
        import ollama
        client = ollama.Client(host=OLLAMA_HOST)
        resp = client.chat(
            model=VisionCfg.MODEL,
            messages=[{"role": "user", "content": prompt, "images": [image_bytes]}],
        )
        text = (resp["message"]["content"] or "").strip()
        return text or None
    except Exception:
        return None


def weary_from_label(label: Optional[str]) -> float:
    """Map an expression label to the weary_face signal strength. Pure, so the
    grounding chain from pixels to mood stays testable without a camera."""
    if not label:
        return 0.0
    return float(VisionCfg.WEARY_WEIGHTS.get(label.strip().lower().rstrip("."), 0.0))


# --- Ambient senses: slow background glimpse threads -------------------------

class _GlimpseThread:
    """Shared shape for the two ambient senses: capture a frame every
    `interval` seconds, reduce it through the vision model, keep only the
    text. Construction never raises; `available` says whether it's running."""

    def __init__(self, enabled: bool, interval: float) -> None:
        self._interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.available = False
        if not enabled:
            return
        if self._probe():
            self.available = True
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name=type(self).__name__)
            self._thread.start()

    def _probe(self) -> bool:           # capture stack importable + working?
        raise NotImplementedError

    def _glimpse(self) -> None:         # one capture + describe + store
        raise NotImplementedError

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._glimpse()
            except Exception:
                pass  # a failed glimpse is a blink, not a crash
            self._stop.wait(self._interval)

    def close(self) -> None:
        self._stop.set()


class ScreenSight(_GlimpseThread):
    """What's on the screen right now, as one or two sentences."""

    def __init__(self) -> None:
        self.latest: str = ""
        super().__init__(VisionCfg.SIGHT_ENABLED, VisionCfg.SIGHT_INTERVAL)

    def _probe(self) -> bool:
        try:
            from PIL import ImageGrab  # noqa: F401  (pillow present?)
            return True
        except Exception:
            return False

    def _glimpse(self) -> None:
        import io
        from PIL import ImageGrab
        shot = ImageGrab.grab()
        # Downscale: the model doesn't need 4K to say "they're editing Python".
        shot.thumbnail((1280, 1280))
        buf = io.BytesIO()
        shot.save(buf, format="JPEG", quality=80)
        desc = describe_image(buf.getvalue(), prompt=_SCREEN_PROMPT)
        if desc:
            self.latest = desc


class FaceSense(_GlimpseThread):
    """A periodic webcam expression read, reduced to one label + the
    weary_face signal it implies."""

    def __init__(self) -> None:
        self.expression: str = ""
        self.weary: float = 0.0
        super().__init__(VisionCfg.FACE_ENABLED, VisionCfg.FACE_INTERVAL)

    def _probe(self) -> bool:
        try:
            import cv2
            cap = cv2.VideoCapture(0)
            ok = cap.isOpened()
            cap.release()
            return ok
        except Exception:
            return False

    def _glimpse(self) -> None:
        import cv2
        cap = cv2.VideoCapture(0)
        try:
            ok, frame = cap.read()
        finally:
            cap.release()
        if not ok:
            return
        ok, jpg = cv2.imencode(".jpg", frame)
        if not ok:
            return
        label = describe_image(jpg.tobytes(), prompt=_FACE_PROMPT)
        if label:
            self.expression = label.strip().lower().rstrip(".")
            self.weary = weary_from_label(label)

    def annotate(self, obs) -> None:
        """Fold the latest expression read into an Observation. No-op when the
        sense is off, so call sites don't need their own guard."""
        if self.available:
            obs.face_weary = self.weary
