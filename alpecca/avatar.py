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


def manifest(avatar_dir: Path = AVATAR_DIR) -> dict:
    """Which clips actually exist on disk. The UI uses this to decide between
    video mode and the SVG fallback (video mode needs at least standby)."""
    present = {name: (avatar_dir / fname).exists() for name, fname in CLIPS.items()}
    return {"clips": present, "video_mode": present["standby"]}


def clip_path(name: str, avatar_dir: Path = AVATAR_DIR) -> Optional[Path]:
    """Resolve a whitelisted clip name to its file, or None. Unknown names and
    missing files both return None -- the caller 404s either way."""
    fname = CLIPS.get(name)
    if not fname:
        return None
    path = avatar_dir / fname
    return path if path.exists() else None
