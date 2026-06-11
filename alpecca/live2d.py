"""Her Live2D tier: the rigged puppet, driven by her real state.

This is the top renderer in her avatar stack -- a proper Live2D Cubism model
(the rig blueprinted in data/character/reference/live2d/) above the pose tier,
the video tier, and the SVG fallback. When a compiled model is dropped into
data/avatar/live2d/ (a `.model3.json` plus its `.moc3`, textures, physics, and
motions), the UI renders it; until then everything below this tier keeps
working untouched.

The point of this module is the *wrapping*: it maps her live internal state
onto the standard Cubism parameters the rig exposes, so the rigged face is a
true readout of how she actually feels -- the same grounding rule as the flat
avatar, now on a real puppet. The fast, time-driven parameters (blink, breath,
lip-sync) are produced in the browser each frame; the slow, mood-driven ones
are defined here as the single tested source of truth and mirrored by the JS
renderer (the same pattern posekit/select_pose uses).

Parameter names follow the Cubism conventions from her rig sheets (ParamAngleX,
ParamMouthOpenY, ParamBrowLY, ...) plus a couple of custom ones for her chest
power-core and UI halo. studio.write_rig_spec emits these names so whatever the
artist rigs is drivable by this module with no translation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from config import AVATAR_DIR
from alpecca.homeostasis import EmotionalState

LIVE2D_DIR = AVATAR_DIR / "live2d"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# Her avatar state -> the halo / UI status the rig should show (sheet 09).
HALO_STATE = {
    "idle": "idle", "listening": "listening",
    "thinking": "processing", "speaking": "active",
}


def params_for_state(state: EmotionalState) -> dict:
    """Map her live mood onto the slow, expressive Cubism parameters. Pure and
    tested; the JS renderer mirrors this and adds blink/breath/lip-sync. Values
    are in each parameter's natural Cubism range (angles in degrees, the rest
    roughly -1..1 or 0..1)."""
    love, care, fear = state.love, state.compassion, state.fear
    return {
        # Cheeks blush with warmth.
        "ParamCheek": round(_clamp(love, 0.0, 1.0), 4),
        # Mouth curves up with warmth, down with unease.
        "ParamMouthForm": round(_clamp(love * 1.4 - fear * 1.2, -1.0, 1.0), 4),
        # Brows raise when happy, drop when uneasy...
        "ParamBrowLY": round(_clamp(love * 0.5 - fear * 0.6, -1.0, 1.0), 4),
        "ParamBrowRY": round(_clamp(love * 0.5 - fear * 0.6, -1.0, 1.0), 4),
        # ...and angle inward (worried) with unease.
        "ParamBrowLAngle": round(_clamp(fear, 0.0, 1.0), 4),
        "ParamBrowRAngle": round(_clamp(fear, 0.0, 1.0), 4),
        # She tilts her head toward you when her care is high.
        "ParamAngleZ": round(_clamp(care * 6.0, -30.0, 30.0), 4),
        # And draws back a little when uneasy.
        "ParamBodyAngleX": round(_clamp(-fear * 4.0, -10.0, 10.0), 4),
        # Eyes soften with care and droop when her energy is low (drowsy);
        # blink overrides the open/close in JS.
        "ParamEyeForm": round(_clamp(care * 0.5 - fear * 0.3 - (1.0 - state.energy) * 0.4,
                                     -1.0, 1.0), 4),
        # Custom: her chest power-core brightness tracks overall arousal.
        "Param_CoreGlow": round(_clamp(0.3 + love * 0.4 + fear * 0.4, 0.0, 1.0), 4),
        # Custom: iris/eye glow leans toward the intense end with unease+care.
        "Param_EyeGlow": round(_clamp(0.3 + fear * 0.5 + care * 0.2, 0.0, 1.0), 4),
    }


def model_path() -> Optional[Path]:
    """The first `.model3.json` in data/avatar/live2d/, or None. Its presence is
    what flips the UI into Live2D mode."""
    if not LIVE2D_DIR.exists():
        return None
    models = sorted(LIVE2D_DIR.glob("*.model3.json"))
    return models[0] if models else None


def manifest() -> dict:
    """For the UI: whether a rigged model exists and the relative path to load.
    `params` ships the parameter map names so the renderer and a debug view can
    introspect what's driven."""
    m = model_path()
    return {
        "live2d_mode": m is not None,
        "model_file": m.name if m else None,
        "halo_states": HALO_STATE,
    }


def asset_path(rel: str) -> Optional[Path]:
    """Resolve a model-relative asset path safely inside LIVE2D_DIR. Blocks
    traversal -- the renderer requests textures/physics/motions by relative
    name and nothing outside the model folder is reachable."""
    if not rel or rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
        return None
    p = (LIVE2D_DIR / rel).resolve()
    try:
        p.relative_to(LIVE2D_DIR.resolve())
    except ValueError:
        return None
    return p if p.exists() and p.is_file() else None
