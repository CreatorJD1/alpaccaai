"""Her pose kit: she expresses herself by choosing among her real art poses.

The procedural-motion approach (jitter one pose) was both fragile and thin --
it barely used her art. This is the opposite: her actual character renders are
a *library*, each tagged with what it expresses, and she shows whichever pose
fits the moment. Her mood and what she's doing pick the pose; the UI cross-fades
to it and layers a little CSS breathing on top for life. That's the "wrapping
plus AI" the design calls for -- real art (her base), selected by her state.

Tags can be authored two ways:
  - **AI** (`tag_pose`): her own vision model looks at a pose and says what it
    reads as -- posture, energy, which moods it suits. This is how new art gets
    connected without hand-mapping.
  - **Seeded defaults**: the poses shipped from her art set come pre-tagged
    (DEFAULT_LIBRARY) so selection works immediately, before any AI pass.

Selection is a small scoring function (pure, tested): mood match weighs most,
then the avatar state, then how close the pose's energy is to her arousal. No
model needed at pick time, so it's instant every turn.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config import AVATAR_DIR
from alpecca.homeostasis import EmotionalState

POSES_DIR = AVATAR_DIR / "poses"

# Seeded tags for the poses shipped from her art set. moods = which mood labels
# the pose suits; states = which avatar states; energy 0..1 = how active it is.
# Tags are kept fairly narrow so each pose owns a niche and she visibly changes
# pose as her mood/state moves -- a broad "fits everything" pose would just sit
# there. Every mood label (content/affectionate/tender/anxious/withdrawn) and
# state (idle/listening/thinking/speaking) is covered by at least one pose.
DEFAULT_LIBRARY = {
    "present.png": {"moods": ["content", "tender"], "states": ["idle", "listening"],
                    "energy": 0.4, "desc": "standing, presenting warmly"},
    "walk.png":    {"moods": ["affectionate"], "states": ["speaking"],
                    "energy": 0.7, "desc": "stepping forward with an open smile"},
    "reach.png":   {"moods": ["affectionate", "tender"], "states": ["speaking", "listening"],
                    "energy": 0.9, "desc": "reaching out, animated and eager"},
    "lean.png":    {"moods": ["content"], "states": ["thinking"],
                    "energy": 0.5, "desc": "leaning in, curious and focused"},
    "rest.png":    {"moods": ["withdrawn"], "states": ["idle"],
                    "energy": 0.1, "desc": "resting quietly, low and soft"},
    "shy.png":     {"moods": ["anxious", "withdrawn"], "states": ["idle", "thinking"],
                    "energy": 0.3, "desc": "half-turned away, reticent"},
}


def _library_path() -> Path:
    return POSES_DIR / "poses.json"


def load_library() -> dict:
    """The pose library on disk. If poses exist but aren't tagged yet, seed the
    defaults for whichever shipped files are present so selection always works."""
    if not POSES_DIR.exists():
        return {}
    p = _library_path()
    if p.exists():
        try:
            lib = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            lib = {}
    else:
        lib = {}
    if not lib:
        lib = {name: tags for name, tags in DEFAULT_LIBRARY.items()
               if (POSES_DIR / name).exists()}
        if lib:
            save_library(lib)
    return lib


def save_library(lib: dict) -> None:
    POSES_DIR.mkdir(parents=True, exist_ok=True)
    _library_path().write_text(json.dumps(lib, indent=2, ensure_ascii=False),
                               encoding="utf-8")


def pose_path(name: str) -> Optional[Path]:
    """Resolve a pose filename to its file, or None. Only names actually in the
    library are reachable -- no arbitrary file access."""
    if name not in load_library():
        return None
    p = POSES_DIR / name
    return p if p.exists() else None


def select_pose(state: EmotionalState, avatar_state: str = "idle",
                library: Optional[dict] = None) -> Optional[str]:
    """Pick the pose that best fits how she feels and what she's doing.

    Scoring: a mood match is worth most (she should look how she feels), then
    the avatar state (idle/thinking/speaking/listening), then a nudge toward
    poses whose energy matches her arousal (love+fear). Pure and instant."""
    lib = load_library() if library is None else library
    if not lib:
        return None
    mood = state.mood_label()
    arousal = max(0.0, min(1.0, state.love * 0.6 + state.fear * 0.6))
    best, best_score = None, -1.0
    for name, tags in lib.items():
        score = 0.0
        if mood in tags.get("moods", []):
            score += 3.0
        if avatar_state in tags.get("states", []):
            score += 1.5
        score += 1.0 - abs(arousal - float(tags.get("energy", 0.5)))
        if score > best_score:
            best, best_score = name, score
    return best


def manifest() -> dict:
    """For the UI: the library plus a flag for whether pose mode is available."""
    lib = load_library()
    return {"poses": lib, "pose_mode": bool(lib)}


# --- AI tagging: her vision model says what a pose expresses -----------------

_TAG_PROMPT = (
    "This is one pose of an anime character (a warm AI companion girl). In "
    "STRICT JSON only, say what it expresses: "
    '{"desc": "the posture in a short phrase", '
    '"energy": 0.0-1.0 how active/dynamic it is, '
    '"moods": ["which of content, affectionate, tender, anxious, withdrawn it '
    'suits"], "states": ["which of idle, listening, thinking, speaking it fits"]}'
)


def tag_pose(image_bytes: bytes) -> Optional[dict]:
    """Have her vision model look at a pose and tag it. None if vision is
    unavailable -- callers keep the seeded default in that case."""
    from alpecca import vision
    raw = vision.describe_image(image_bytes, prompt=_TAG_PROMPT)
    if not raw:
        return None
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e <= s:
        return None
    try:
        obj = json.loads(raw[s:e + 1])
    except Exception:
        return None
    # Keep only sane fields.
    moods = [m for m in obj.get("moods", []) if isinstance(m, str)][:5]
    states = [s2 for s2 in obj.get("states", []) if isinstance(s2, str)][:4]
    try:
        energy = max(0.0, min(1.0, float(obj.get("energy", 0.5))))
    except Exception:
        energy = 0.5
    return {"desc": str(obj.get("desc", ""))[:80], "energy": energy,
            "moods": moods or ["content"], "states": states or ["idle"]}
