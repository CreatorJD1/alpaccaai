"""Her Spine tier: a real skeletal rig, her primary rigged avatar.

The cleanest all-free path to a properly rigged her, no Cubism and no continuous
GPU: decompose her art (See-Through), auto-rig + animate it in StretchyStudio
(https://github.com/MangoLion/stretchystudio, MIT, in-browser), export Spine 4.0
JSON, and drop it in data/avatar/spine/. The /live2d page plays it with
pixi-spine and drives the skeleton from her live mood.

This module owns the seam: detecting her exported skeleton, listing its
animations, serving its assets safely, and -- the grounding wrapper --
`choose_animation()`, which maps her mood + what she's doing onto which of her
authored animations to play. Pure and tested; the renderer mirrors it.

Her export is a few files in data/avatar/spine/ sharing a base name, the Spine
convention: `<name>.json` (skeleton), `<name>.atlas`, and the atlas's `.png`(s).
pixi-spine resolves the atlas and textures from the skeleton URL.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config import AVATAR_DIR

SPINE_DIR = AVATAR_DIR / "spine"


def skeleton_file(spine_dir: Path = SPINE_DIR) -> Optional[Path]:
    """Her exported Spine skeleton (the first *.json), or None. Its presence is
    what turns on the Spine tier."""
    if not spine_dir.exists():
        return None
    jsons = sorted(spine_dir.glob("*.json"))
    return jsons[0] if jsons else None


def _animations(skel: Path) -> list[str]:
    """The animation names in her export, so the driver knows what she can do."""
    try:
        data = json.loads(skel.read_text(encoding="utf-8"))
        return list((data.get("animations") or {}).keys())
    except Exception:
        return []


def manifest(spine_dir: Path = SPINE_DIR) -> dict:
    """For the UI: whether a Spine rig exists, the skeleton filename to load, and
    her animation list (used to pick base/talk/blink animations)."""
    skel = skeleton_file(spine_dir)
    if skel is None:
        return {"spine_mode": False, "skeleton": None, "animations": []}
    return {"spine_mode": True, "skeleton": skel.name,
            "animations": _animations(skel)}


def asset_path(name: str, spine_dir: Path = SPINE_DIR) -> Optional[Path]:
    """Resolve a Spine asset (skeleton/atlas/png) traversal-safe inside
    SPINE_DIR. pixi-spine requests the atlas and textures by relative name; only
    files actually in the folder are reachable."""
    if not name or name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/"):
        return None
    p = (spine_dir / name).resolve()
    try:
        p.relative_to(spine_dir.resolve())
    except ValueError:
        return None
    return p if p.exists() and p.is_file() else None


# --- the wrapper: her mood -> which animation she plays ----------------------

# Names we look for, in order, when picking the looping base animation. A
# mood-named animation wins if she authored one; else a generic idle; else her
# first animation -- so any export animates out of the box.
_IDLE_NAMES = ("idle", "Idle", "idle_loop", "breathing", "loop")
_TALK_NAMES = ("talk", "Talk", "talking", "mouth", "speak")
_BLINK_NAMES = ("blink", "Blink")


def _first_present(candidates, available: set) -> Optional[str]:
    for c in candidates:
        if c in available:
            return c
    return None


def choose_animation(animations: list[str], mood: str, speaking: bool) -> dict:
    """Pick what she plays: a looping base (her mood's animation if she authored
    one, else idle, else her first), a talk overlay while speaking, and a blink
    track if she has one. Pure -- the renderer applies the result."""
    avail = set(animations)
    base = _first_present((mood, mood.capitalize()) + _IDLE_NAMES, avail)
    if base is None and animations:
        base = animations[0]
    talk = _first_present(_TALK_NAMES, avail) if speaking else None
    blink = _first_present(_BLINK_NAMES, avail)
    return {"base": base, "talk": talk, "blink": blink}
