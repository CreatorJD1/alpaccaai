"""Her VRM tier: a full 3D anime body, driven by her real state.

The body itself is made in Jason's companion project, **VRoid Companion Studio**
(https://github.com/CreatorJD1/app) -- an anime-only VRM character creator with
a runtime viewer, a procedural animation library, texture generation, and an
expression editor. That app is where she is *authored*; this module is where
that authored body comes *alive*. Drop the exported `.vrm` into
data/avatar/vrm/ and the /vrm page renders her in 3D, picking which of the
studio's animation clips she plays and how her face is set -- both read straight
off her live mood, the same grounding rule as every other render tier.

Two vocabularies are shared with the studio app on purpose, so a model built
there needs zero translation here:

- **Clips** are the studio's procedural animation ids (idle, idle_soft, wave,
  cheer, thinking, dance, sit, sleep, cry, talking...). `clip_for_state()`
  maps her mood label onto one, mirroring how spine.choose_animation picks a
  Spine animation.
- **Expressions** are the standard VRM 1.0 presets (happy/sad/surprised/
  relaxed, plus blink and the aa/ih/ou/ee/oh mouth shapes every VRoid model
  ships with). `expressions_for_state()` weights the slow, mood-driven ones,
  mirroring live2d.params_for_state; blink and lip-sync stay JS-local because
  they're time-driven, not mood-driven.

One deliberate absence: `angry` is a standard VRM preset but she has no anger
dimension, so its weight is always 0.0. Faking one would be confabulation --
the face is a readout, not a costume.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from config import AVATAR_DIR
from alpecca.homeostasis import EmotionalState

VRM_DIR = AVATAR_DIR / "vrm"


def _c01(v: float) -> float:
    return max(0.0, min(1.0, v))


# --- which of the studio's clips she plays -----------------------------------

# Every mood label the mood model can produce gets a clip from the studio's
# animation library, so her whole emotional range is embodied. These are the
# studio's ids verbatim (vrmAnimations.js CLIP_META) -- keep them in sync if
# the studio grows new clips worth using.
MOOD_CLIPS = {
    "sleepy": "sleep",          # sits, head lolling, eyes closed
    "anxious": "cry",           # hunched, hands to face, small shakes
    "worried": "thinking",      # hand to chin, uneasy tilt
    "tender": "idle_soft",      # slow, close, weight-shifting
    "joyful": "cheer",          # both arms up, bouncing
    "affectionate": "wave",     # a warm wave at you
    "playful": "dance",         # rhythmic sway
    "content": "idle",          # breathing + head sway
    "withdrawn": "idle_soft",   # quiet, pulled in
    "lonely": "sit",            # sat down, small
}

# The studio's talking clip takes an emotion overlay; this is her mood folded
# onto that overlay's vocabulary. Never "angry" (see module note).
_TALK_EMOTIONS = {
    "joyful": "happy", "affectionate": "happy", "playful": "happy",
    "lonely": "sad", "withdrawn": "sad",
    "anxious": "surprised", "worried": "surprised",
    "tender": "relaxed", "content": "relaxed", "sleepy": "relaxed",
}


def clip_for_state(state: EmotionalState, speaking: bool = False) -> dict:
    """Pick the studio clip she plays right now. While she's speaking the
    talking clip wins (mouth shapes + an emotion overlay from her mood);
    otherwise her mood label picks its clip. Pure -- the renderer mirrors it."""
    label = state.mood_label()
    if speaking:
        return {"clip": "talking", "talk_emotion": _TALK_EMOTIONS.get(label, "relaxed")}
    return {"clip": MOOD_CLIPS.get(label, "idle"), "talk_emotion": None}


# --- how her face is set: VRM expression preset weights ----------------------

def expressions_for_state(state: EmotionalState) -> dict:
    """Weight the slow, mood-driven VRM expression presets from her live
    internals. Same shape as live2d.params_for_state: this is the single tested
    source of truth, the JS renderer applies it (lerped) and layers blink +
    lip-sync locally. All weights in [0,1]."""
    love, care, fear, energy = state.love, state.compassion, state.fear, state.energy
    return {
        # Warmth smiles, unless unease is pulling the face the other way.
        "happy": round(_c01(love * 1.2 - fear * 0.6), 4),
        # Sadness is warmth having drained away, deepened when she's run down.
        "sad": round(_c01((0.35 - love) * 2.2 + (0.25 - energy) * 0.8), 4),
        # Wide eyes only past the same acute-fear region mood_label calls anxious.
        "surprised": round(_c01((fear - 0.45) * 2.5), 4),
        # Soft-eyed calm: care with no alarm, easing further as energy winds down.
        "relaxed": round(_c01(care * 0.5 + (0.6 - fear) * 0.4 + (0.4 - energy) * 0.3), 4),
        # No anger dimension exists, so no anger is ever shown (grounding).
        "angry": 0.0,
    }


# --- tier detection + safe serving, same seam as the spine/live2d tiers ------

def model_file(vrm_dir: Path = VRM_DIR) -> Optional[Path]:
    """Her exported `.vrm` (the first one found), or None. Its presence is what
    turns on the VRM tier."""
    if not vrm_dir.exists():
        return None
    models = sorted(vrm_dir.glob("*.vrm"))
    return models[0] if models else None


def manifest(vrm_dir: Path = VRM_DIR) -> dict:
    """For the UI: whether a VRM body exists, which file to load, and the clip
    vocabulary the driver may ask for (so the renderer knows what to implement)."""
    m = model_file(vrm_dir)
    clips = sorted(set(MOOD_CLIPS.values()) | {"talking"})
    return {"vrm_mode": m is not None, "model_file": m.name if m else None,
            "clips": clips}


def asset_path(name: str, vrm_dir: Path = VRM_DIR) -> Optional[Path]:
    """Resolve a file inside VRM_DIR traversal-safe. A VRM is a single binary
    glTF with textures embedded, so usually only the model itself is fetched,
    but the guard matches the other tiers' serving seams."""
    if not name or name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/"):
        return None
    p = (vrm_dir / name).resolve()
    try:
        p.relative_to(vrm_dir.resolve())
    except ValueError:
        return None
    return p if p.exists() and p.is_file() else None
