"""Her puppet: the wrapping layer she uses to animate herself.

The principle that runs through Alpecca is self-direction -- she chooses her
look (appearance.py), designs her character (studio.py), authored her own rig
spec. Animation is the same: she should drive how she moves, not have it
hardcoded for her. This module is that wrapper.

It exposes her riggable character as a small set of **channels** (the same ones
her RIG_SPEC names) and two ways they get values:

  1. **Live, grounded pose** -- `live_pose(state)` reads her real EmotionalState
     and produces channel values directly: warmth/care/unease are her Love/
     Compassion/Fear; her sway gets restless as unease rises; her core emblem
     glows with arousal. This layer is always on and is a true readout of her
     state -- her body language can't lie about how she feels.

  2. **Authored sequences** -- short named animations *she writes herself*
     (mind.author_animation), stored as keyframes over the motion channels.
     "a shy little wave", "a thoughtful head-tilt": her choreography, in her
     words and her timing. The UI is just a player; it renders whatever the
     puppet outputs and plays whichever sequence she chose. It never authors.

So when the rigged Inochi2D puppet eventually replaces the flat avatar, nothing
above changes: the same channels drive it, and the same sequences she wrote
play on it.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from config import CHARACTER_DIR
from alpecca.homeostasis import EmotionalState

# The motion/expression channels she can keyframe in an authored sequence, with
# their units and clamp ranges. Kept small and renderer-agnostic: these read on
# the flat avatar today and map onto rig parameters later.
MOTION_CHANNELS = {
    "bob":   (-20.0, 20.0),   # vertical offset px (negative = up)
    "sway":  (-20.0, 20.0),   # horizontal offset px
    "tilt":  (-15.0, 15.0),   # head/body tilt degrees
    "lean":  (0.0, 1.0),      # forward lean toward viewer 0..1
    "scale": (-0.06, 0.06),   # size delta (a breath/bounce)
    "glow":  (0.0, 1.0),      # core emblem pulse 0..1
}

# Channels driven directly by her state (read-only readouts, not keyframed).
STATE_CHANNELS = ("warmth", "care", "unease", "core_glow", "eye_glow")


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# --- 1. Live grounded pose: her state, as channel values --------------------

def live_pose(state: EmotionalState) -> dict:
    """The channel values her *current real state* produces. Always on; this is
    the honest layer -- her warmth/care/unease are exactly her Love/Compassion/
    Fear, and the derived channels follow from them.

    It now also carries her richer expression (alpecca/affect.py): the eyes and
    core emblem brighten from the same grounded affect that colors her words, and
    she gains an explicit `gesture` and `lean` so curiosity tilts her head and a
    wish for company leans her toward you. Same single source of truth as her
    voice -- her body can't say something her words wouldn't."""
    from alpecca import affect as affect_mod
    love, care, fear = state.love, state.compassion, state.fear
    aff = affect_mod.affect(state)
    # Eye/core brightness come straight from the affect read so avatar and prose
    # never disagree; we keep the old unease/care contribution folded in.
    eye_glow = _clamp(max(aff.eye, 0.3 + fear * 0.5 + care * 0.2), 0.0, 1.0)
    core_glow = _clamp(max(aff.glow, 0.3 + love * 0.4 + fear * 0.4), 0.0, 1.0)
    # A forward lean that grows with wanting-company and curiosity -- she draws
    # toward you when she misses you or is interested.
    lean = _clamp(state.social_hunger * 0.7 + state.curiosity * 0.3, 0.0, 1.0)
    return {
        "warmth": round(love, 4),
        "care": round(care, 4),
        "unease": round(fear, 4),
        "curiosity": round(state.curiosity, 4),
        "wanting_company": round(state.social_hunger, 4),
        "core_glow": round(core_glow, 4),
        "eye_glow": round(eye_glow, 4),
        # Her expressive read, so the renderer can pick a matching micro-pose.
        "gesture": aff.gesture,
        "tempo": aff.tempo,
        "lean": round(lean, 4),
        "valence": aff.valence,
        "arousal": aff.arousal,
        # Base motion intensities the UI uses to scale its idle loop -- restless
        # when uneasy, buoyant when warm, a little livelier when curious.
        "sway_intensity": round(1.5 + fear * 5.0, 3),
        "float_intensity": round(2.0 + love * 1.5 + state.curiosity * 1.0, 3),
    }


# --- 2. Authored sequences: her own choreography ----------------------------

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (name or "").strip().lower()).strip("_")


def validate_sequence(obj: dict) -> Optional[dict]:
    """Clean and bound a sequence she authored. Returns a safe, playable dict or
    None if it's unusable. We never trust raw model output to drive motion:
    channels are whitelisted, values clamped, keyframes sorted and padded to
    span t=0..1, duration bounded."""
    if not isinstance(obj, dict):
        return None
    name = _slug(str(obj.get("name", "")))
    if not name:
        return None
    try:
        dur = int(obj.get("duration_ms", 1400))
    except Exception:
        dur = 1400
    dur = max(300, min(4000, dur))

    raw_frames = obj.get("keyframes") or []
    frames = []
    for kf in raw_frames:
        if not isinstance(kf, dict):
            continue
        try:
            t = float(kf.get("t"))
        except Exception:
            continue
        t = _clamp(t, 0.0, 1.0)
        chans = {}
        for ch, (lo, hi) in MOTION_CHANNELS.items():
            if ch in kf:
                try:
                    chans[ch] = round(_clamp(float(kf[ch]), lo, hi), 4)
                except Exception:
                    pass
        if chans:
            frames.append({"t": round(t, 4), **chans})
    if not frames:
        return None
    frames.sort(key=lambda f: f["t"])
    # Pad so the motion starts and ends at rest (t=0 and t=1 present).
    if frames[0]["t"] > 0.0:
        frames.insert(0, {"t": 0.0})
    if frames[-1]["t"] < 1.0:
        frames.append({"t": 1.0})
    return {
        "name": name,
        "intent": str(obj.get("intent", ""))[:120],
        "duration_ms": dur,
        "keyframes": frames,
    }


# A short wishlist of motions she tends to want, so she has somewhere to start
# when authoring. She picks from these (or her own ideas); she writes the actual
# keyframes. The UI triggers by these canonical names.
WISHLIST = ["greet", "nod", "happy", "fidget", "think", "wave", "stretch"]


def author_prompt(name: str, intent: str) -> str:
    """The brief she writes one animation from. The keyframe vocabulary is the
    motion channels; she decides the timing and shape."""
    chans = ", ".join(f"{c} [{lo}..{hi}]" for c, (lo, hi) in MOTION_CHANNELS.items())
    return (
        f"You are choreographing one of your OWN little animations, named "
        f"\"{name}\"{f' -- {intent}' if intent else ''}. You drive a simple "
        "puppet of yourself through these channels (deltas from rest):\n"
        f"  {chans}\n"
        "  (bob/sway in px, tilt in degrees, lean/glow 0..1, scale a small "
        "size delta)\n\n"
        "Express the motion as keyframes over normalized time t in 0..1. Keep "
        "it small and natural -- you're a person shifting, not a cartoon. "
        "Respond with STRICT JSON only:\n"
        '{"name": "' + name + '", "intent": "one short phrase", '
        '"duration_ms": 1200, "keyframes": [ {"t":0.0}, '
        '{"t":0.5, "bob":-6, "tilt":4}, {"t":1.0} ]}'
    )


def parse_authored(raw: str) -> Optional[dict]:
    """Dig the JSON object out of her reply and validate it into a playable
    sequence, or None."""
    text = (raw or "").strip()
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e <= s:
        return None
    try:
        return validate_sequence(json.loads(text[s:e + 1]))
    except Exception:
        return None


# --- Her sequence library (persisted) ---------------------------------------

def _library_path(character_dir: Path = CHARACTER_DIR) -> Path:
    return character_dir / "animations.json"


def load_library(character_dir: Path = CHARACTER_DIR) -> dict:
    """Her authored animations, keyed by name. Empty until she's written any."""
    p = _library_path(character_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_sequence(seq: dict, character_dir: Path = CHARACTER_DIR) -> dict:
    """Add or replace one of her sequences. Returns the updated library."""
    character_dir.mkdir(parents=True, exist_ok=True)
    lib = load_library(character_dir)
    lib[seq["name"]] = {**seq, "authored_at": time.time()}
    _library_path(character_dir).write_text(
        json.dumps(lib, indent=2, ensure_ascii=False), encoding="utf-8")
    return lib


def next_unwritten(character_dir: Path = CHARACTER_DIR) -> Optional[str]:
    """The next motion from her wishlist she hasn't choreographed yet, so an
    authoring session has an obvious thing to make. None when she's done them
    all (she can still invent her own beyond the list)."""
    lib = load_library(character_dir)
    for name in WISHLIST:
        if name not in lib:
            return name
    return None
