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

Privacy: every generic public wrapper requires a verified-local Ollama target.
The only standing cloud exception is a deliberate image upload from the
cryptographically verified CreatorJD Discord actor when that creator preference
is enabled. Ambient screen, webcam, and guest pixels remain local-only.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal, Optional

from config import (
    Vision as VisionCfg,
    OLLAMA_HOST,
    OLLAMA_NUM_CTX,
    VISION_CLOUD_MODEL,
)
from alpecca.local_inference import verified_local_ollama_target
from alpecca.egress_consent import EgressConsentDenied, PerceptionEgressGate


# --- The shared eye: one image in, a short description out ------------------


@dataclass(frozen=True, slots=True)
class VisionDescription:
    """A grounded description plus the backend that actually saw the pixels."""

    text: str
    backend: str
    processing_location: str
    cloud_egress: str


FrameSource = Literal["attachment", "video-frame"]
MAX_EVENT_FRAME_BYTES = 12 * 1024 * 1024
MAX_VIDEO_FRAME_AGE_SECONDS = 15.0
MAX_ATTACHMENT_FRAME_AGE_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class EventFrame:
    """One ephemeral image-bearing event with bounded provenance."""

    image_bytes: bytes
    source: FrameSource
    source_id: str
    captured_at: float


@dataclass(frozen=True, slots=True)
class FrameVisibility:
    """Truthful result: ``visible`` only when a backend saw these pixels."""

    status: Literal["visible", "stale", "invalid", "unavailable"]
    source: FrameSource
    source_id: str
    captured_at: float
    description: VisionDescription | None = None
    reason: str = ""

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

_VISION_CALL_LOCK = threading.Lock()
_VISION_STATE_LOCK = threading.Lock()
_VISION_STATE: dict[str, object] = {
    "attempts": 0,
    "successes": 0,
    "last_status": "unverified",
    "last_source": "",
    "last_observed_at": 0.0,
}


def _record_vision_outcome(*, success: bool, source: str) -> None:
    with _VISION_STATE_LOCK:
        _VISION_STATE["attempts"] = int(_VISION_STATE["attempts"]) + 1
        if success:
            _VISION_STATE["successes"] = int(_VISION_STATE["successes"]) + 1
        _VISION_STATE["last_status"] = "ready" if success else "unavailable"
        _VISION_STATE["last_source"] = source[:32]
        _VISION_STATE["last_observed_at"] = time.time()


def vision_readiness() -> dict[str, object]:
    """Return measured local-vision posture without claiming a live sensor."""

    configured = verified_local_ollama_target(
        OLLAMA_HOST,
        VisionCfg.MODEL,
        known_cloud_models={VISION_CLOUD_MODEL},
    )
    with _VISION_STATE_LOCK:
        observed = dict(_VISION_STATE)
    status = str(observed["last_status"])
    if not configured:
        status = "unavailable"
    elif not int(observed["attempts"]):
        status = "unverified"
    return {
        "status": status,
        "configured_local_target": configured,
        "model": str(VisionCfg.MODEL),
        "processing": "local-only",
        "sensor_attached": False,
        "event_frames_supported": ("attachment", "video-frame"),
        **observed,
    }


def _timeout_seconds(name: str, default: float) -> float:
    try:
        return max(5.0, min(120.0, float(os.environ.get(name, str(default)))))
    except (TypeError, ValueError):
        return default


def _describe_local(image_bytes: bytes, prompt: str) -> Optional[str]:
    """Run one bounded local Ollama vision call.

    The configured fallback is the smaller Qwen 3.5 4B vision model. Calls are
    serialized so an attachment, ScreenSight, and FaceSense cannot compete for
    the same four-gigabyte GPU or silently queue several large model loads.
    """
    if not verified_local_ollama_target(
        OLLAMA_HOST,
        VisionCfg.MODEL,
        known_cloud_models={VISION_CLOUD_MODEL},
    ):
        return None
    if not _VISION_CALL_LOCK.acquire(timeout=2.0):
        return None
    try:
        import ollama
        client = ollama.Client(
            host=OLLAMA_HOST,
            timeout=_timeout_seconds("ALPECCA_VISION_TIMEOUT", 60.0),
        )
        kwargs = {
            "model": VisionCfg.MODEL,
            "messages": [{"role": "user", "content": prompt, "images": [image_bytes]}],
            "options": {
                "num_gpu": int(os.environ.get("ALPECCA_VISION_NUM_GPU", "0")),
                # CRITICAL: without this cap Ollama sizes the KV cache for the
                # model's full advertised window (qwen3.5's 256K -> a 16 GB
                # allocation that thrashes the whole machine on CPU). Found
                # live 2026-07-04: one un-capped vision call wedged her app.
                "num_ctx": OLLAMA_NUM_CTX,
                "num_predict": 192,
            },
            # The same local model handles the grounded reply after perception.
            # Keeping it warm briefly avoids immediately unloading and loading
            # several GB again, which previously made image turns time out.
            "keep_alive": os.environ.get("ALPECCA_VISION_KEEP_ALIVE", "2m"),
        }
        # Qwen 3.5 may put all output in a reasoning field unless thinking is
        # disabled. Older Ollama Python clients do not accept this argument, so
        # retain a bounded compatibility retry before reporting no perception.
        try:
            resp = client.chat(**kwargs, think=False)
        except TypeError:
            resp = client.chat(**kwargs)
        text = (resp["message"]["content"] or "").strip()
        return text or None
    except Exception:
        return None
    finally:
        _VISION_CALL_LOCK.release()


def _describe_ollama_cloud(image_bytes: bytes, prompt: str) -> Optional[str]:
    """Describe an image on a vision-capable Ollama *cloud* model, through the
    same signed-in local Ollama API as everything else. No ZeroGPU queue or
    quota, zero local VRAM -- pixels go to the account's hosted model and only
    text comes back. Retained for a future exact-consent adapter."""
    if not VISION_CLOUD_MODEL:
        return None
    if not _VISION_CALL_LOCK.acquire(timeout=2.0):
        return None
    try:
        import ollama
        client = ollama.Client(
            host=OLLAMA_HOST,
            timeout=_timeout_seconds("ALPECCA_VISION_CLOUD_TIMEOUT", 45.0),
        )
        kwargs = {
            "model": VISION_CLOUD_MODEL,
            "messages": [
                {"role": "user", "content": prompt, "images": [image_bytes]}
            ],
        }
        try:
            resp = client.chat(**kwargs, think=False)
        except TypeError:
            resp = client.chat(**kwargs)
        text = (resp["message"]["content"] or "").strip()
        return text or None
    except Exception:
        return None
    finally:
        _VISION_CALL_LOCK.release()


def _describe_zerogpu(image_bytes: bytes, prompt: str) -> Optional[str]:
    """Describe an image on her ZeroGPU space's /vision endpoint -- the VL model
    runs on the Space's cloud GPU, so the local card is never touched. None on any
    failure. Retained for a future exact-consent adapter."""
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
    """Run one verified-local vision call with truthful metadata.

    `ambient` remains accepted for compatibility with existing sensor callers.
    Generic wrappers are local-only regardless of that flag or
    ``config.VISION_BACKEND``. A future remote adapter must consume an exact
    consent grant before it invokes either private provider helper.
    """
    local = _describe_local(image_bytes, prompt)
    _record_vision_outcome(success=bool(local), source="direct-image")
    return (
        VisionDescription(local, "local-ollama", "local-only", "denied")
        if local else None
    )


def describe_image(image_bytes: bytes, prompt: str = _DESCRIBE_PROMPT,
                   ambient: bool = False) -> Optional[str]:
    """Compatibility wrapper returning only the grounded description text."""

    result = describe_image_result(image_bytes, prompt=prompt, ambient=ambient)
    return result.text if result else None


# --- Consented remote vision: the ONLY reachable private-provider path -------
#
# The generic wrappers above are verified-local only. A remote provider
# (Ollama-cloud or the ZeroGPU Space) is reachable exclusively through the
# function below, and only after a PerceptionEgressGate authorizes exactly one
# creator-approved, byte-bound, single-use egress on an allowlisted route that
# attests the exact provider, deployment, model, processing location,
# destination, and HTTPS transport. Configuration alone never reaches here.

# Route "provider" identifiers map to the transport helper that performs the
# actual outbound call. The helper is resolved by name at call time so tests
# (and the fail-closed guard tests) that monkeypatch the module-level helpers
# are honored.
CONSENTED_REMOTE_PROVIDERS = ("ollama-cloud", "zerogpu")


def _remote_transport(provider: str) -> Optional[Callable[[bytes, str], Optional[str]]]:
    """Resolve the outbound transport for an attested provider, or None."""
    if provider == "ollama-cloud":
        return _describe_ollama_cloud
    if provider == "zerogpu":
        return _describe_zerogpu
    return None


def describe_image_via_consent(
    image_bytes: bytes,
    *,
    gate: PerceptionEgressGate,
    route_id: str,
    operation_id: str,
    provider: str,
    prompt: str = _DESCRIBE_PROMPT,
) -> Optional[VisionDescription]:
    """Attempt one CONSENTED remote vision description, or return None.

    Fail-closed. The private provider is invoked only after ``gate`` authorizes
    exactly one bounded, creator-approved egress use bound to *these exact bytes*
    and *this exact* allowlisted route. Any denial (no consent, creator refusal,
    binding mismatch, expiry, replay, or an unready ledger) means the provider is
    NEVER called and this returns None, so the caller falls back to
    verified-local vision. The returned description reports the route's attested
    processing location and destination -- it is never relabelled local-only.
    """
    # A missing or invalid gate is treated as absent consent: fall back to
    # verified-local vision rather than crash or reach a remote provider.
    if not isinstance(gate, PerceptionEgressGate):
        return None
    transport = _remote_transport(provider)
    if transport is None:
        return None
    if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
        return None
    payload = bytes(image_bytes)
    try:
        authorization = gate.authorize_attempt(
            operation_id=operation_id,
            route_id=route_id,
            payload=payload,
        )
    except EgressConsentDenied:
        return None
    text = transport(payload, prompt)
    if not text:
        return None
    return VisionDescription(
        text=text,
        backend=f"{authorization.provider}:{authorization.deployment}",
        processing_location=authorization.processing_location,
        cloud_egress=authorization.destination_class,
    )

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
    Returns an enriched description string, or None if she couldn't look.
    ``local_only`` remains for compatibility; generic vision is always local."""
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
    """Local description/self-recognition with truthful processing metadata."""

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


def _valid_event_image(payload: bytes) -> bool:
    if not payload or len(payload) > MAX_EVENT_FRAME_BYTES:
        return False
    return bool(
        payload.startswith(b"\xff\xd8\xff")
        or payload.startswith(b"\x89PNG\r\n\x1a\n")
        or (payload.startswith(b"RIFF") and payload[8:12] == b"WEBP")
        or payload.startswith((b"GIF87a", b"GIF89a"))
    )


def describe_event_frame(
    frame: EventFrame,
    *,
    prompt: str = _DESCRIBE_PROMPT,
    now: float | None = None,
) -> FrameVisibility:
    """Describe one attachment/video frame, fencing stale and invalid events.

    No camera or screen capability is inferred.  ``visible`` means the exact
    supplied bytes reached a verified vision backend during this call.
    """

    if not isinstance(frame, EventFrame):
        raise TypeError("frame must be EventFrame")
    observed = time.monotonic() if now is None else float(now)
    source_id = " ".join(str(frame.source_id or "").split())[:128]
    if frame.source not in {"attachment", "video-frame"} or not source_id:
        return FrameVisibility(
            "invalid", frame.source, source_id, frame.captured_at, reason="invalid-source"
        )
    if not _valid_event_image(frame.image_bytes):
        return FrameVisibility(
            "invalid", frame.source, source_id, frame.captured_at, reason="invalid-image"
        )
    age = observed - float(frame.captured_at)
    max_age = (
        MAX_VIDEO_FRAME_AGE_SECONDS
        if frame.source == "video-frame"
        else MAX_ATTACHMENT_FRAME_AGE_SECONDS
    )
    if age < -1.0 or age > max_age:
        return FrameVisibility(
            "stale", frame.source, source_id, frame.captured_at, reason="stale-frame"
        )
    result = describe_image_result(frame.image_bytes, prompt=prompt)
    if result is None:
        return FrameVisibility(
            "unavailable",
            frame.source,
            source_id,
            frame.captured_at,
            reason="vision-backend-unavailable",
        )
    with _VISION_STATE_LOCK:
        _VISION_STATE["last_source"] = frame.source
    return FrameVisibility(
        "visible", frame.source, source_id, frame.captured_at, description=result
    )


def describe_and_recognize_via_consent(
    image_bytes: bytes,
    *,
    gate: PerceptionEgressGate,
    route_id: str,
    operation_id: str,
    provider: str,
) -> Optional[VisionDescription]:
    """Run self-recognizing remote vision through the exact consent gate."""

    result = describe_image_via_consent(
        image_bytes,
        gate=gate,
        route_id=route_id,
        operation_id=operation_id,
        provider=provider,
        prompt=_self_recognition_prompt(),
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
        self.last_capture_at = 0.0
        self.last_description_at = 0.0
        self.last_error = "disabled" if not enabled else "unverified"
        if not enabled:
            return
        if self._probe():
            self.available = True
            self.last_error = ""
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
                self.last_error = "capture-or-inference-failed"
            self._stop.wait(self._interval)

    def close(self) -> None:
        self._stop.set()

    def readiness(self) -> dict[str, object]:
        return {
            "capture_ready": bool(self.available),
            "last_capture_at": float(getattr(self, "last_capture_at", 0.0)),
            "last_description_at": float(
                getattr(self, "last_description_at", 0.0)
            ),
            "reason": str(getattr(self, "last_error", "unverified")),
        }


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
        self.last_capture_at = time.time()
        # Downscale: the model doesn't need 4K to say "they're editing Python".
        shot.thumbnail((1280, 1280))
        buf = io.BytesIO()
        shot.save(buf, format="JPEG", quality=80)
        desc = describe_image(buf.getvalue(), prompt=_SCREEN_PROMPT, ambient=True)
        if desc:
            self.latest = desc
            self.last_description_at = time.time()
            self.last_error = ""
        else:
            self.last_error = "vision-backend-unavailable"


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
            self.last_error = "camera-frame-unavailable"
            return
        self.last_capture_at = time.time()
        ok, jpg = cv2.imencode(".jpg", frame)
        if not ok:
            self.last_error = "camera-encode-failed"
            return
        label = describe_image(jpg.tobytes(), prompt=_FACE_PROMPT, ambient=True)
        if label:
            self.expression = label.strip().lower().rstrip(".")
            self.weary = weary_from_label(label)
            self.last_description_at = time.time()
            self.last_error = ""
        else:
            self.last_error = "vision-backend-unavailable"

    def annotate(self, obs) -> None:
        """Fold the latest expression read into an Observation. No-op when the
        sense is off, so call sites don't need their own guard."""
        if self.available:
            obs.face_weary = self.weary
