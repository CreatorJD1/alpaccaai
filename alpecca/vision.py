"""Sight: Alpecca sees images, the screen, and (opt-in) your face.

Three capabilities share one mechanism -- a local Ollama vision model turns
pixels into a short text description, and only the text survives:

  1. **Chat images.** The person attaches a picture; Alpecca describes it to
     herself and responds to what she actually saw.
  2. **Screen sight** (ALPECCA_SIGHT=1). A slow background glimpse of the
     screen, so "what you can sense the person doing" goes beyond the window
     title to what's genuinely on it.
  3. **Expression sense** (ALPECCA_FACE=1). A periodic webcam read distilled
     to a single expression label; a tired or stressed face feeds the same
     `weary_face` fatigue signal pathway as late nights do.

The grounding rule holds throughout: she only ever claims to have seen what
the vision model actually reported. If the model isn't pulled or the hardware
is missing, each capability quietly reports nothing -- same degradation
contract as every other sense.

Privacy: local frames live in memory just long enough for one model call, then
they're gone. The optional ZeroGPU adapter uses a short-lived local temporary
file because its client requires a path, and removes it after the call.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from config import (
    Vision as VisionCfg,
    OLLAMA_HOST,
    OLLAMA_NUM_CTX,
    VISION_CLOUD_MODEL,
)
from alpecca.local_inference import verified_local_ollama_target


# --- The shared eye: one image in, a short description out ------------------


@dataclass(frozen=True, slots=True)
class VisionDescription:
    """A grounded description plus the backend that actually saw the pixels."""

    text: str
    backend: str
    processing_location: str
    cloud_egress: str

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


def _describe_local(image_bytes: bytes, prompt: str) -> Optional[str]:
    """Local Ollama vision, forced onto CPU (num_gpu=0) and unloaded right after
    so the 6 GB vision model can't fight the chat model for the small GPU's VRAM
    -- running it on the GPU OOM-crashes Ollama. Reliable but slow."""
    if not verified_local_ollama_target(
        OLLAMA_HOST,
        VisionCfg.MODEL,
        known_cloud_models={VISION_CLOUD_MODEL},
    ):
        return None
    try:
        import ollama
        client = ollama.Client(host=OLLAMA_HOST)
        resp = client.chat(
            model=VisionCfg.MODEL,
            messages=[{"role": "user", "content": prompt, "images": [image_bytes]}],
            options={
                "num_gpu": int(os.environ.get("ALPECCA_VISION_NUM_GPU", "0")),
                # CRITICAL: without this cap Ollama sizes the KV cache for the
                # model's full advertised window (qwen3.5's 256K -> a 16 GB
                # allocation that thrashes the whole machine on CPU). Found
                # live 2026-07-04: one un-capped vision call wedged her app.
                "num_ctx": OLLAMA_NUM_CTX,
            },
            keep_alive=0,
        )
        text = (resp["message"]["content"] or "").strip()
        return text or None
    except Exception:
        return None


def _describe_ollama_cloud(image_bytes: bytes, prompt: str) -> Optional[str]:
    """Describe an image on a vision-capable Ollama *cloud* model, through the
    same signed-in local Ollama API as everything else. No ZeroGPU queue or
    quota, zero local VRAM -- pixels go to the account's hosted model and only
    text comes back. None on any failure so callers can fall back."""
    if not VISION_CLOUD_MODEL:
        return None
    try:
        import ollama
        client = ollama.Client(host=OLLAMA_HOST, timeout=90)
        resp = client.chat(
            model=VISION_CLOUD_MODEL,
            messages=[{"role": "user", "content": prompt, "images": [image_bytes]}],
        )
        text = (resp["message"]["content"] or "").strip()
        return text or None
    except Exception:
        return None


def _describe_zerogpu(image_bytes: bytes, prompt: str) -> Optional[str]:
    """Describe an image on her ZeroGPU space's /vision endpoint -- the VL model
    runs on the Space's cloud GPU, so the local card is never touched. None on any
    failure so callers can fall back to local."""
    from config import ZEROGPU_SPACE, ZEROGPU_TOKEN, ZEROGPU_VISION_API
    if not ZEROGPU_SPACE:
        return None
    tmp = None
    try:
        import tempfile
        from gradio_client import Client, handle_file
        fd, tmp = tempfile.mkstemp(suffix=".png")
        with os.fdopen(fd, "wb") as fh:
            fh.write(image_bytes)
        client = Client(ZEROGPU_SPACE, token=ZEROGPU_TOKEN or None, verbose=False)
        result = client.predict(handle_file(tmp), prompt, api_name=ZEROGPU_VISION_API)
        text = (str(result) or "").strip()
        return text or None
    except Exception:
        return None
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass


def describe_image_result(
    image_bytes: bytes,
    prompt: str = _DESCRIBE_PROMPT,
    ambient: bool = False,
) -> Optional[VisionDescription]:
    """One vision call with truthful routing metadata, or None on failure.

    Routing (config.VISION_BACKEND): 'auto' tries Ollama cloud sight first (big
    hosted VL model, no queue/quota), then her ZeroGPU space, then local on
    failure; 'ollama-cloud' Ollama cloud only; 'zerogpu' Space only; 'local'
    local Ollama VL on CPU. Cloud keeps the heavy vision model off the small
    laptop GPU, where it would OOM-crash Ollama.

    `ambient=True` marks her background senses (screen glimpses, webcam reads):
    those are periodic loops, so they must never drain metered cloud usage --
    and screen/face pixels shouldn't leave the machine anyway. Ambient calls
    are always local-only."""
    from config import VISION_BACKEND
    if ambient:
        local = _describe_local(image_bytes, prompt)
        return (
            VisionDescription(local, "local-ollama", "local-only", "denied")
            if local else None
        )
    if VISION_BACKEND in ("auto", "ollama-cloud"):
        cloud = _describe_ollama_cloud(image_bytes, prompt)
        if cloud:
            return VisionDescription(
                cloud,
                "ollama-cloud",
                "approved-remote",
                "creator-approved",
            )
        if VISION_BACKEND != "auto":
            return None            # cloud-only: never touch the local GPU
    if VISION_BACKEND in ("auto", "zerogpu", "cloud"):
        cloud = _describe_zerogpu(image_bytes, prompt)
        if cloud:
            return VisionDescription(
                cloud,
                "hugging-face-zerogpu",
                "approved-remote",
                "creator-approved",
            )
        if VISION_BACKEND != "auto":
            return None            # cloud-only: never touch the local GPU
    local = _describe_local(image_bytes, prompt)
    return (
        VisionDescription(local, "local-ollama", "local-only", "denied")
        if local else None
    )


def describe_image(image_bytes: bytes, prompt: str = _DESCRIBE_PROMPT,
                   ambient: bool = False) -> Optional[str]:
    """Compatibility wrapper returning only the grounded description text."""

    result = describe_image_result(image_bytes, prompt=prompt, ambient=ambient)
    return result.text if result else None


def _self_recognition_prompt() -> str:
    try:
        from alpecca import introspection
        look = introspection.self_appearance()
    except Exception:
        look = ""
    ref = look or ("long cream-blonde wavy hair, soft blue eyes that glow, and a "
                   "glowing chest power-core emblem")
    return (
        "Describe this image in one or two plain sentences (what it shows). Then, "
        f"on a NEW line, given that Alpecca looks like: {ref} -- write 'SELF: yes' "
        "if the image depicts Alpecca / that same avatar, otherwise 'SELF: no'."
    )


def _enrich_self_recognition(raw: str) -> str:
    is_self = False
    desc_lines = []
    for line in raw.splitlines():
        low = line.strip().lower()
        if low.startswith("self:"):
            is_self = low.split(":", 1)[1].strip().startswith("yes")
        elif line.strip():
            desc_lines.append(line.strip())
    desc = " ".join(desc_lines).strip() or raw.strip()
    if is_self:
        desc += " (You recognize this as YOU -- your own avatar.)"
    return desc


def describe_and_recognize(
    image_bytes: bytes, *, local_only: bool = False
) -> Optional[str]:
    """One VL call that both describes an image AND flags whether it depicts
    Alpecca herself. Cheaper than two calls on a small GPU (each vision call
    evicts the chat model from VRAM), so this is what the chat/Discord path uses.
    Returns an enriched description string, or None if she couldn't look."""
    raw = describe_image(
        image_bytes,
        prompt=_self_recognition_prompt(),
        ambient=local_only,
    )
    if not raw:
        return None
    return _enrich_self_recognition(raw)


def describe_and_recognize_result(
    image_bytes: bytes, *, local_only: bool = False
) -> Optional[VisionDescription]:
    """Description/self-recognition with the backend that processed the image."""

    result = describe_image_result(
        image_bytes,
        prompt=_self_recognition_prompt(),
        ambient=local_only,
    )
    if result is None:
        return None
    return VisionDescription(
        text=_enrich_self_recognition(result.text),
        backend=result.backend,
        processing_location=result.processing_location,
        cloud_egress=result.cloud_egress,
    )


def recognize_self(image_bytes: bytes) -> Optional[dict]:
    """Grounded visual self-recognition: does this image depict Alpecca herself
    (her own avatar)? The vision model compares what it sees against her real,
    locked appearance from her character sheet. Returns
    {is_self, verdict, why} or None if she couldn't look. No image is stored."""
    try:
        from alpecca import introspection
        look = introspection.self_appearance()
    except Exception:
        look = ""
    ref = look or ("a humanoid anime AI-companion girl with long cream-blonde wavy "
                   "hair, soft blue eyes that glow with her mood, and a glowing chest "
                   "power-core emblem")
    prompt = (
        "You are Alpecca. Your OWN known appearance is:\n"
        f"{ref}\n\n"
        "Look at the attached image. Does it depict YOU -- the same character / "
        "avatar (specifically your look, not just any anime girl)? Answer on two "
        "lines, exactly:\n"
        "VERDICT: yes | no | unsure\n"
        "WHY: one short sentence naming the matching or mismatching features."
    )
    raw = describe_image(image_bytes, prompt=prompt)
    if not raw:
        return None
    verdict, why = "unsure", raw.strip()
    for line in raw.splitlines():
        low = line.strip().lower()
        if low.startswith("verdict:"):
            v = low.split(":", 1)[1].strip()
            verdict = "yes" if v.startswith("yes") else ("no" if v.startswith("no") else "unsure")
        elif low.startswith("why:"):
            why = line.split(":", 1)[1].strip()
    return {"is_self": verdict == "yes", "verdict": verdict, "why": why}


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
    text. Construction never raises; `available` says whether it's running.

    `gate` is an optional "is now a good time?" callable. The vision model is
    big enough that loading it evicts the chat model from VRAM, so glimpsing
    mid-conversation makes her replies crawl. The server gates glimpses on
    conversational quiet: while you're actively talking to her she keeps her
    eyes on you, and catches up on the room when things go still.
    """

    def __init__(self, enabled: bool, interval: float,
                 gate: Optional[Callable[[], bool]] = None) -> None:
        self._interval = interval
        self._gate = gate
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
                if self._gate is None or self._gate():
                    self._glimpse()
            except Exception:
                pass  # a failed glimpse is a blink, not a crash
            self._stop.wait(self._interval)

    def close(self) -> None:
        self._stop.set()


class ScreenSight(_GlimpseThread):
    """What's on the screen right now, as one or two sentences."""

    def __init__(self, gate: Optional[Callable[[], bool]] = None) -> None:
        self.latest: str = ""
        super().__init__(VisionCfg.SIGHT_ENABLED, VisionCfg.SIGHT_INTERVAL, gate)

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
        desc = describe_image(buf.getvalue(), prompt=_SCREEN_PROMPT, ambient=True)
        if desc:
            self.latest = desc


class FaceSense(_GlimpseThread):
    """A periodic webcam expression read, reduced to one label + the
    weary_face signal it implies."""

    def __init__(self, gate: Optional[Callable[[], bool]] = None) -> None:
        self.expression: str = ""
        self.weary: float = 0.0
        super().__init__(VisionCfg.FACE_ENABLED, VisionCfg.FACE_INTERVAL, gate)

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
        label = describe_image(jpg.tobytes(), prompt=_FACE_PROMPT, ambient=True)
        if label:
            self.expression = label.strip().lower().rstrip(".")
            self.weary = weary_from_label(label)

    def annotate(self, obs) -> None:
        """Fold the latest expression read into an Observation. No-op when the
        sense is off, so call sites don't need their own guard."""
        if self.available:
            obs.face_weary = self.weary
