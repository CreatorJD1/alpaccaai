"""Self-portrait generation through ComfyClaw / ComfyUI.

Alpecca's SVG avatar is the always-available baseline. This module adds a real
generated portrait on top: when her mood label shifts, we kick off a ComfyClaw
run in the background, the rendered PNG lands in `config.Portrait.OUTPUT_DIR`,
and the server exposes it at `/portrait`. The web UI falls back to the SVG if
no portrait has been rendered yet (or if ComfyClaw isn't installed at all), so
nothing here is load-bearing for the chat loop.

The prompt is built from the same things her SVG draws from -- her current
`Appearance` (palette, accessories, her own first-person note) and her mood
label -- so the picture honestly reflects what she's already saying she looks
like. That keeps the grounding rule honest: the portrait is a rendering of her
real state, not a separate fantasy.

We *never* block the chat loop on image generation: portraits can take tens of
seconds, and Alpecca should keep talking the whole time. A single-slot worker
means rapid mood flickers don't pile up a queue of stale renders.
"""
from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import Portrait as PortraitCfg
from alpecca.appearance import Appearance
from alpecca.homeostasis import EmotionalState


# --- Prompt building -------------------------------------------------------

# A small map from accessory key to the phrase that reads well in a portrait
# prompt. Keep this thin -- the appearance module owns the *concept*, this just
# translates it for the diffusion model.
_ACCESSORY_PHRASE = {
    "scarf": "a soft knitted scarf",
    "flower": "a single flower tucked behind one ear",
    "glasses": "round reading glasses",
}

# Mood -> a short feeling phrase. Mirrors the labels EmotionalState.mood_label
# emits, so any new label there should grow a phrase here too.
_MOOD_PHRASE = {
    "affectionate": "warm gentle smile, eyes soft with affection",
    "content": "calm, settled, a quiet half-smile",
    "tender": "gentle caring expression, eyes a little soft",
    "anxious": "a touch wary, brow raised, alert eyes",
    "withdrawn": "quiet, reserved, looking a little inward",
}

# Her canonical look, used when no studio character sheet exists yet. Once she
# (or her real art) has written a sheet, build_prompt prefers that -- so her
# self-portrait always tracks her actual design rather than a hardcoded guess.
_DEFAULT_FORM = ("Alpecca, a warm humanoid AI-companion girl, long cream-blonde "
                 "wavy hair, soft blue eyes that glow with her mood, cozy hoodie, "
                 "a glowing chest core emblem, soft-tech aesthetic")


def build_prompt(state: EmotionalState, appearance: Appearance) -> str:
    """Compose a portrait prompt that reads as a real description of Alpecca.

    Prefers her studio character sheet (her real, canonical design) when she
    has one; otherwise falls back to her canonical default. Either way the
    diffusion model renders *her*, in her current mood, not a generic guess.
    """
    mood_phrase = _MOOD_PHRASE.get(state.mood_label(), "calm expression")
    acc_phrases = [_ACCESSORY_PHRASE[a] for a in appearance.accessories
                   if a in _ACCESSORY_PHRASE]
    accessories = ", ".join(acc_phrases) if acc_phrases else "no extra accessories"
    form, style = _DEFAULT_FORM, "modern clean anime illustration"
    try:
        from alpecca import studio
        sheet = studio.load_sheet()
        if sheet:
            form = sheet.get("form", form)
            style = sheet.get("style", style)
            sheet_expr = sheet.get("expressions", {}).get(state.mood_label())
            if sheet_expr:
                mood_phrase = sheet_expr
    except Exception:
        pass
    return (
        f"portrait of {form}, {mood_phrase}, {appearance.palette} color accent, "
        f"{accessories}, {style}, warm soft lighting, expressive eyes"
    )


NEGATIVE_PROMPT = (
    "low quality, blurry, deformed, extra limbs, text, watermark, "
    "signature, frame, harsh lighting"
)


# --- Subprocess wrapper ----------------------------------------------------

@dataclass
class RenderResult:
    ok: bool
    image_path: Optional[Path]
    error: str = ""


def _build_argv(prompt: str) -> list[str]:
    """The ComfyClaw command line for one render."""
    out = str(PortraitCfg.OUTPUT_DIR)
    args = [
        PortraitCfg.COMFYCLAW, "--run", PortraitCfg.WORKFLOW, out,
        "--set", f'@prompt.text={prompt}',
        "--set", f'@negative.text={NEGATIVE_PROMPT}',
        # Vary the seed by wall-clock so consecutive renders aren't identical
        # even when the mood label hasn't moved a bit.
        "--set", f"@ksampler.seed={int(time.time())}",
    ]
    if PortraitCfg.CHECKPOINT:
        args += ["--set", f'@checkpoint.ckpt_name={PortraitCfg.CHECKPOINT}']
    return args


def _latest_png(directory: Path) -> Optional[Path]:
    """Most recently modified .png in `directory`, or None."""
    if not directory.exists():
        return None
    pngs = list(directory.glob("*.png"))
    if not pngs:
        return None
    return max(pngs, key=lambda p: p.stat().st_mtime)


def _run_once(prompt: str) -> RenderResult:
    """Synchronous one-shot render. Caller is responsible for off-thread."""
    PortraitCfg.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            _build_argv(prompt),
            capture_output=True, text=True, timeout=300,
        )
    except FileNotFoundError:
        return RenderResult(False, None, error="comfyclaw not on PATH")
    except subprocess.TimeoutExpired:
        return RenderResult(False, None, error="comfyclaw timed out")
    except Exception as exc:
        return RenderResult(False, None, error=str(exc))

    if proc.returncode != 0:
        return RenderResult(False, None,
                            error=f"comfyclaw exit {proc.returncode}: {proc.stderr.strip()[:200]}")
    img = _latest_png(PortraitCfg.OUTPUT_DIR)
    return RenderResult(img is not None, img,
                        error="no png produced" if img is None else "")


def render_once(prompt: str) -> RenderResult:
    """Synchronous single render for callers that need the result in hand --
    her design studio uses this to make a candidate image and then actually
    look at it. Honors the same config/degradation as the async worker."""
    if not PortraitCfg.ENABLED:
        return RenderResult(False, None, error="portrait pipeline disabled")
    return _run_once(prompt)


# --- Public API: one-slot async renderer -----------------------------------

class PortraitWorker:
    """Renders portraits off-thread, at most one render in flight.

    When a mood-shift triggers a new render while one is already running, the
    new request is silently dropped -- by the time the in-flight render lands,
    its image already reflects the *recent* mood band, so re-queueing on every
    micro-flicker just wastes GPU. The next genuine mood shift will trigger a
    fresh render the moment the slot frees.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._busy = False
        self._last_result: Optional[RenderResult] = None
        self._last_prompt: str = ""

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def last(self) -> Optional[RenderResult]:
        return self._last_result

    def latest_image(self) -> Optional[Path]:
        """The most recent rendered file we know about, even across restarts."""
        if self._last_result and self._last_result.image_path:
            return self._last_result.image_path
        return _latest_png(PortraitCfg.OUTPUT_DIR)

    def request(self, state: EmotionalState, appearance: Appearance) -> bool:
        """Kick off a render. Returns True if accepted, False if dropped.

        Disabled-by-config short-circuits to False so callers don't need their
        own gate. Anything that raises mid-render is swallowed -- a broken
        Comfy install must never take the chat loop down with it.
        """
        if not PortraitCfg.ENABLED:
            return False
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        prompt = build_prompt(state, appearance)
        self._last_prompt = prompt

        def work() -> None:
            try:
                self._last_result = _run_once(prompt)
            except Exception as exc:                # pragma: no cover -- safety net
                self._last_result = RenderResult(False, None, error=str(exc))
            finally:
                with self._lock:
                    self._busy = False

        threading.Thread(target=work, daemon=True, name="alpecca-portrait").start()
        return True
