"""Her layered rig: a real per-part avatar built from decomposed art.

The single-image mesh rig (web/live2d.html) can breathe and sway, but it can't
blink or lip-sync because her art is one flat picture. This module is the other
half of the fix: once her illustration is decomposed into named layers -- eyes,
mouth, hair, head, body (e.g. by See-Through, https://github.com/shitagaki-lab/
see-through, then imported with scripts/import_rig.py) -- the renderer can move
each part on its own. Real blink, lip-sync, head-turn, hair sway, all driven by
her live state, fully local, no proprietary Cubism editor.

This module owns the *convention*: where the layers live, what roles they play,
and a manifest the renderer reads. The roles are deliberately few and forgiving,
because See-Through's exact layer set varies -- `role_for(name)` maps any layer
name onto one of them, and unknown layers fall back to the body so nothing is
lost.

Layers live in data/avatar/rig/ as transparent PNGs (each full-canvas, the
See-Through convention) plus a rig.json manifest. The renderer stacks them by z
and animates them by role.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from config import AVATAR_DIR

RIG_DIR = AVATAR_DIR / "rig"

# The roles the renderer knows how to animate, with their stacking order (back
# to front). Keep this small -- each role drives a specific motion.
ROLE_Z = {
    "back_hair": 0,     # behind everything, sways with lag
    "body": 1,          # torso/clothing/limbs, breathes
    "head": 2,          # face base, moves as a group with the features
    "brows": 3,         # expression
    "eyes": 4,          # blink
    "mouth": 5,         # lip-sync
    "front_hair": 6,    # bangs over the face, sway with lag
    "accessory": 7,     # halo, etc.
}
ROLES = list(ROLE_Z)


def role_for(layer_name: str) -> str:
    """Map a raw layer name (from See-Through / a PSD) onto one of our roles.
    Forgiving substring matching; anything unrecognized becomes body so no part
    of her is dropped."""
    n = (layer_name or "").lower()
    if ("hair" in n and ("back" in n or "inner" in n or "lower" in n)):
        return "back_hair"
    if ("brow" in n or "eyebrow" in n):
        return "brows"
    if ("lid" in n or "closed" in n) and "eye" in n:
        return "eyes"            # eyelid layers ride with the eyes group
    if "eye" in n or "iris" in n or "pupil" in n:
        return "eyes"
    if "mouth" in n or "lip" in n:
        return "mouth"
    if ("hair" in n or "bang" in n or "ahoge" in n):
        return "front_hair"
    if ("face" in n or "head" in n or "skin" in n):
        return "head"
    if ("halo" in n or "ring" in n or "badge" in n or "emblem" in n or "core" in n):
        return "accessory"
    return "body"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (name or "").lower()).strip("_")


# --- manifest ----------------------------------------------------------------

def manifest_path(rig_dir: Path = RIG_DIR) -> Path:
    return rig_dir / "rig.json"


def load_manifest(rig_dir: Path = RIG_DIR) -> Optional[dict]:
    """Her rig manifest, or None if she has no layered rig yet."""
    p = manifest_path(rig_dir)
    if not p.exists():
        return None
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
        return m if m.get("layers") else None
    except Exception:
        return None


def save_manifest(layers: list[dict], size: list[int],
                  rig_dir: Path = RIG_DIR, anchors: Optional[dict] = None) -> dict:
    """Write rig.json. `layers` is a list of {file, role}; we sort by role z and
    fill defaults so the renderer has everything it needs.

    `anchors` is her pose skeleton's normalized anchors (alpecca/pose.py:
    head_center/neck/hip_center in 0..1). When present, the head pivot becomes her
    *real* neck in pixels instead of a guess, and the anchors ride along in the
    manifest so the renderer can tilt her head and lean her body around her actual
    joints. Backwards compatible: with no anchors we keep the old 0.32 estimate."""
    rig_dir.mkdir(parents=True, exist_ok=True)
    clean = []
    for lyr in layers:
        role = lyr.get("role") or role_for(lyr.get("file", ""))
        if role not in ROLE_Z:
            role = "body"
        clean.append({"file": lyr["file"], "role": role, "z": ROLE_Z[role]})
    clean.sort(key=lambda l: l["z"])
    # Head pivot: her real neck (or head center) when the skeleton gives one,
    # else the historical estimate so nothing regresses without a skeleton.
    pivot = [size[0] / 2, size[1] * 0.32]
    neck = (anchors or {}).get("neck") or (anchors or {}).get("head_center")
    if neck and neck.get("x") is not None:
        pivot = [round(neck["x"] * size[0], 1), round(neck["y"] * size[1], 1)]
    manifest = {"size": size, "layers": clean, "head_pivot": pivot}
    if anchors:
        manifest["anchors"] = anchors          # normalized, for grounded motion
    manifest_path(rig_dir).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def manifest(rig_dir: Path = RIG_DIR) -> dict:
    """For the UI: whether a layered rig exists, plus its manifest."""
    m = load_manifest(rig_dir)
    return {"rig_mode": m is not None, "manifest": m}


def layer_path(name: str, rig_dir: Path = RIG_DIR) -> Optional[Path]:
    """Resolve a layer filename to its file, traversal-blocked. Only files
    actually listed in the manifest are reachable."""
    m = load_manifest(rig_dir)
    if not m:
        return None
    allowed = {l["file"] for l in m["layers"]}
    if name not in allowed:
        return None
    p = (rig_dir / name).resolve()
    try:
        p.relative_to(rig_dir.resolve())
    except ValueError:
        return None
    return p if p.exists() and p.is_file() else None
