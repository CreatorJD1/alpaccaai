"""Custom avatar clips: the slot her real character art drops into.

The web UI has four avatar states -- idle, listening, thinking, speaking --
animated on the built-in SVG by default. This module adds the upgrade path
(borrowed from Alice's custom-avatar design): drop looping video clips into
`data/avatar/` and the UI plays those instead, switched by the same states.

    data/avatar/standby.mp4    -> idle + listening
    data/avatar/listening.mp4  -> listening (optional, falls back to standby)
    data/avatar/thinking.mp4   -> thinking
    data/avatar/speaking.mp4   -> speaking

No recompile, no config: the manifest endpoint reports what exists and the UI
adapts. When her rigged Inochi2D puppet lands, it replaces this layer the same
way -- the state machine stays, only the renderer changes.

The clip names are a closed whitelist so /avatar/clip/{name} can never be
talked into serving arbitrary files.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from config import AVATAR_DIR

# State -> filename. Closed set; anything else 404s.
CLIPS = {
    "standby": "standby.mp4",
    "listening": "listening.mp4",
    "thinking": "thinking.mp4",
    "speaking": "speaking.mp4",
}

# Static portrait images, one per avatar state, in data/avatar/portraits/.
# This is the middle tier between full video clips and the SVG fallback -- and
# it's where her real character art (the chibi poses) lives today: a still
# pose per state, swapped by the state machine. Only `idle` is required for
# portrait mode; the others fall back to idle.
PORTRAITS = {
    "idle": "idle.png",
    "listening": "listening.png",
    "thinking": "thinking.png",
    "speaking": "speaking.png",
}


def manifest(avatar_dir: Path = AVATAR_DIR) -> dict:
    """What avatar assets exist on disk, and which render mode the UI should
    use. Preference order: video clips > still portraits > built-in SVG."""
    clips = {name: (avatar_dir / fname).exists() for name, fname in CLIPS.items()}
    pdir = avatar_dir / "portraits"
    portraits = {name: (pdir / fname).exists() for name, fname in PORTRAITS.items()}
    return {
        "clips": clips,
        "portraits": portraits,
        "video_mode": clips["standby"],
        "portrait_mode": portraits["idle"],
    }


def clip_path(name: str, avatar_dir: Path = AVATAR_DIR) -> Optional[Path]:
    """Resolve a whitelisted clip name to its file, or None. Unknown names and
    missing files both return None -- the caller 404s either way."""
    fname = CLIPS.get(name)
    if not fname:
        return None
    path = avatar_dir / fname
    return path if path.exists() else None


def portrait_path(name: str, avatar_dir: Path = AVATAR_DIR) -> Optional[Path]:
    """Resolve a whitelisted portrait-state name to its image, or None.
    Unknown names and missing files both return None."""
    fname = PORTRAITS.get(name)
    if not fname:
        return None
    path = avatar_dir / "portraits" / fname
    return path if path.exists() else None
