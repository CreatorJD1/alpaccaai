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

import hashlib
import json
import struct
from functools import lru_cache
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


@lru_cache(maxsize=8)
def _model_sha256(path_value: str, size: int, mtime_ns: int) -> str:
    del size, mtime_ns
    digest = hashlib.sha256()
    with Path(path_value).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _vrm1_capabilities(path: Path) -> dict:
    """Read bounded public VRM 1.0 metadata from the GLB JSON chunk."""
    empty = {
        "vrm_spec_version": None,
        "look_at": False,
        "look_at_type": None,
        "expressions": [],
    }
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            header = stream.read(20)
            if len(header) != 20:
                return empty
            magic, glb_version, declared_size, chunk_size, chunk_type = struct.unpack(
                "<4sIIII", header
            )
            if (
                magic != b"glTF"
                or glb_version != 2
                or declared_size > size
                or chunk_type != 0x4E4F534A
                or chunk_size <= 0
                or chunk_size > min(max(0, size - 20), 16 * 1024 * 1024)
            ):
                return empty
            document = json.loads(stream.read(chunk_size).decode("utf-8").rstrip("\x00 \t\r\n"))
        vrm_extension = ((document.get("extensions") or {}).get("VRMC_vrm") or {})
        look_at = vrm_extension.get("lookAt") or {}
        preset = ((vrm_extension.get("expressions") or {}).get("preset") or {})
        return {
            "vrm_spec_version": vrm_extension.get("specVersion"),
            "look_at": bool(look_at),
            "look_at_type": look_at.get("type") if isinstance(look_at, dict) else None,
            "expressions": sorted(str(name) for name in preset),
        }
    except (OSError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        return empty


def manifest(vrm_dir: Path = VRM_DIR) -> dict:
    """For the UI: whether a VRM body exists, which file to load, and the clip
    vocabulary the driver may ask for (so the renderer knows what to implement)."""
    m = model_file(vrm_dir)
    clips = sorted(set(MOOD_CLIPS.values()) | {"talking"})
    if m is None:
        return {
            "vrm_mode": False,
            "model_file": None,
            "model_version": None,
            "model_sha256": None,
            "model_bytes": 0,
            "model_mtime_ns": None,
            "clips": clips,
            **_vrm1_capabilities(Path("missing")),
        }
    stat = m.stat()
    digest = _model_sha256(str(m.resolve()), stat.st_size, stat.st_mtime_ns)
    return {
        "vrm_mode": True,
        "model_file": m.name,
        "model_version": digest[:16],
        "model_sha256": digest,
        "model_bytes": stat.st_size,
        "model_mtime_ns": stat.st_mtime_ns,
        "clips": clips,
        **_vrm1_capabilities(m),
    }


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


# --- syncing her body from the cloud studio ----------------------------------
# When the studio runs on a cloud host behind its VCS_ACCESS_TOKEN, she can pull
# her newest exported .vrm from it (config.StudioSync). The download lands as
# alpecca_studio.vrm -- which sorts AFTER a hand-dropped alpecca.vrm in
# model_file()'s alphabetical pick, so a manual drop always wins over the sync;
# that's the intended override, not an accident.

STUDIO_FILE = "alpecca_studio.vrm"


def studio_configured() -> bool:
    """Whether a studio URL is set -- what turns the /vrm sync button on."""
    from config import StudioSync
    return bool(StudioSync.URL)


def pick_project(projects: list) -> Optional[dict]:
    """The studio project whose VRM she should wear: the most recently updated
    one that actually has a VRM uploaded. The studio's /api/projects already
    sorts newest-first, but we re-sort defensively (ISO timestamps compare
    lexicographically) so a reordering server can't hand her a stale body."""
    with_vrm = [p for p in (projects or [])
                if p.get("vrm_path") or p.get("vrm_filename")]
    if not with_vrm:
        return None
    return max(with_vrm, key=lambda p: p.get("updated_at") or "")


def build_request(base_url: str, path: str, token: str = "") -> tuple:
    """(url, headers) for a studio API call -- the X-VCS-Token header only when
    a token is configured, matching the studio's auth gate."""
    url = base_url.rstrip("/") + path
    headers = {"X-VCS-Token": token} if token else {}
    return url, headers


def _http_get(url: str, headers: dict, timeout: float) -> bytes:
    """Tiny stdlib transport (no new deps, same pattern as the rest of the
    codebase). Split out so tests inject a fake instead."""
    import urllib.request
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def sync_from_studio(base_url: str = None, token: str = None,
                     vrm_dir: Path = VRM_DIR, fetch=None) -> dict:
    """Pull her newest body from the studio: list projects, pick the freshest
    one with a VRM, download it, and swap it in atomically. Never raises -- the
    UI gets {"ok": True, "file": ...} or {"ok": False, "error": <a friendly
    sentence>}, and a failed sync can never corrupt the model she's wearing
    (the write goes to a temp file first, os.replace is atomic)."""
    import json as _json
    import os
    import tempfile
    from config import StudioSync
    from alpecca import charter

    base = (base_url if base_url is not None else StudioSync.URL).rstrip("/")
    tok = token if token is not None else StudioSync.TOKEN
    get = fetch or (lambda u, h: _http_get(u, h, StudioSync.TIMEOUT))

    if not base:
        return {"ok": False, "error": "No studio configured -- set ALPECCA_STUDIO_URL."}
    allowed, why = charter.internet_allowed("reach my creator's studio to fetch my body")
    if not allowed:  # can't happen for this purpose, but the guard stays real
        return {"ok": False, "error": why}

    try:
        url, headers = build_request(base, "/api/projects", tok)
        projects = _json.loads(get(url, headers)).get("projects", [])
    except Exception:
        return {"ok": False, "error": "Couldn't reach the studio -- is it running, "
                                      "and are the URL and token right?"}

    proj = pick_project(projects)
    if proj is None:
        return {"ok": False, "error": "The studio has no project with a VRM yet -- "
                                      "upload one there first."}

    try:
        url, headers = build_request(base, f"/api/projects/{proj.get('id')}/vrm", tok)
        data = get(url, headers)
    except Exception:
        return {"ok": False, "error": "The studio answered, but the VRM download failed."}
    if not data or not data[:4] == b"glTF":
        # The same magic-bytes check the studio itself applies on import.
        return {"ok": False, "error": "The studio sent something that isn't a VRM."}

    vrm_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".part", dir=vrm_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, vrm_dir / STUDIO_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return {"ok": False, "error": "Downloaded fine but couldn't write the file."}
    return {"ok": True, "file": STUDIO_FILE, "project": proj.get("name") or proj.get("id"),
            "bytes": len(data)}
