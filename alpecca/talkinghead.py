"""Talking Head Anime tier: her face, animated by a neural net from one image.

The top renderer of all -- Talking Head Anime 3 (pkhungurn) animates a single
512x512 portrait of her with real blink, gaze, eyebrows, lip-sync, head turn,
and breathing, no rigging or layer decomposition needed. It runs as a separate
process on the GPU (scripts/run_talkinghead.py); this module is the seam:

  - **pose_for_state(state)** maps her live mood onto the slow, expressive THA3
    pose parameters (smile, brow, head lean, soft eyes, breathing baseline) --
    the grounding wrapper, pure and tested. The runner adds the fast per-frame
    bits (auto-blink, lip-sync phase) itself.
  - **a frame buffer** -- the runner POSTs each generated frame here; the
    /live2d page pulls the latest. Kept in memory, never written to disk.
  - **freshness** -- if no frame has arrived recently the tier is "off" and the
    UI falls back to the cheaper rigs, so her face only takes over when the
    THA3 process is actually running and feeding frames.

Parameter names here are our own small abstraction; the runner maps them onto
THA3's actual pose vector via the model's parameter groups, so this stays
stable even if THA3's internal layout differs.
"""
from __future__ import annotations

import time
from typing import Optional

from alpecca.homeostasis import EmotionalState

# A frame older than this (seconds) means the THA3 process isn't feeding us, so
# the tier is considered inactive and the UI uses a cheaper renderer.
FRESH_S = 3.0

_latest: dict = {"bytes": None, "ts": 0.0, "n": 0}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# --- frame buffer -----------------------------------------------------------

def set_frame(data: bytes) -> int:
    """Store the newest rendered frame (JPEG/PNG bytes) and bump the counter."""
    _latest["bytes"] = data
    _latest["ts"] = time.time()
    _latest["n"] += 1
    return _latest["n"]


def get_frame() -> tuple[Optional[bytes], int]:
    """The latest frame bytes and its sequence number (for cache-busting)."""
    return _latest["bytes"], _latest["n"]


def is_active(now: Optional[float] = None) -> bool:
    """Is the THA3 process currently feeding fresh frames?"""
    if _latest["bytes"] is None:
        return False
    now = time.time() if now is None else now
    return (now - _latest["ts"]) < FRESH_S


def manifest() -> dict:
    return {"talkinghead_mode": is_active(), "frame_n": _latest["n"]}


# --- her mood -> THA3 expressive pose ---------------------------------------

def pose_for_state(state: EmotionalState) -> dict:
    """Map her live state onto the slow THA3 pose parameters. Pure and tested;
    the runner merges these with per-frame blink + lip-sync. Values are 0..1
    (or -1..1 for the head angles), THA3's natural ranges."""
    love, care, fear, energy = state.love, state.compassion, state.fear, state.energy
    return {
        # Brows: lift happily with warmth, knit/trouble with unease.
        "eyebrow_happy": round(_clamp(love), 4),
        "eyebrow_troubled": round(_clamp(fear), 4),
        # Mouth corners: THA3 has separate raised/lowered corners, both 0..1 --
        # smile when warm, frown when uneasy (the resting shape; the runner
        # overlays lip-sync open/close while she speaks).
        "mouth_smile": round(_clamp(love * 1.3 - fear), 4),
        "mouth_frown": round(_clamp(fear * 1.2 - love), 4),
        # Eyes soften (relax) with care.
        "eye_relaxed": round(_clamp(care * 0.6), 4),
        # Pupils shrink a touch when she's frightened.
        "iris_small": round(_clamp(fear * 0.4), 4),
        # Head tilts toward you when her care is high; small downward when drowsy.
        "head_y": round(_clamp(care * 0.25 - (1 - energy) * 0.1, -1.0, 1.0), 4),
        # Breathing baseline depth rises with energy (runner animates the phase).
        "breathing": round(_clamp(0.3 + energy * 0.5), 4),
    }
