"""Her skeleton: the pose keypoints that anchor her avatar to her real figure.

A pose estimator (rtmlib Wholebody) read her character art and returned a COCO-17
skeleton -- 17 named joints (head, shoulders, elbows, wrists, hips, knees,
ankles) in canvas pixels. On its own that's just a dump of numbers; this module
turns it into something her renderer can use: a normalized skeleton plus the few
**anchors** that make articulation honest instead of guessed.

Why it matters for the avatar. Until now the home renderer tilted her "head
region" around an arbitrary sprite center and leaned her by a made-up pivot. With
a real skeleton we can anchor those to where her body actually is: the head tilts
around the *neck* (the shoulder midpoint), she leans from the *hip*, and her parts
sit at their true proportions. The motion still comes from her live mood
(`puppet.live_pose`); this just gives that motion a real body to move.

Pure and testable: `parse(data)` takes the loaded JSON and returns a plain dict of
normalized joints (x,y in 0..1 of the canvas) and derived anchors. No I/O except
the thin `load(path)` helper.
"""
from __future__ import annotations

import json
from pathlib import Path

# COCO-17 joint order, as emitted by the estimator's top-level `keypoints` list.
COCO17 = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]

# Below this detector confidence we treat a joint as unreliable and skip it in
# the derived anchors (so a low-confidence wrist can't throw off her proportions).
_MIN_CONF = 0.3


def _mid(a: dict | None, b: dict | None) -> dict | None:
    """Midpoint of two joints, or whichever exists, or None."""
    if a and b:
        return {"x": (a["x"] + b["x"]) / 2, "y": (a["y"] + b["y"]) / 2,
                "conf": min(a["conf"], b["conf"])}
    return a or b


def parse(data: dict) -> dict:
    """Turn a COCO-17 keypoint dump into a normalized skeleton + anchors.

    Joints are normalized to the canvas so the result is resolution-independent
    (x,y in 0..1, origin top-left). Anchors are the handful of points the avatar
    actually pivots on; each is None when its source joints are missing or
    low-confidence, so the renderer can fall back gracefully."""
    w = float(data.get("canvas_width") or 1) or 1
    h = float(data.get("canvas_height") or 1) or 1
    kps = data.get("keypoints") or []

    joints: dict[str, dict] = {}
    for i, name in enumerate(COCO17):
        if i >= len(kps):
            break
        x, y, c = (list(kps[i]) + [0, 0, 0])[:3]
        if c is None or c < _MIN_CONF:
            continue
        joints[name] = {"x": round(x / w, 5), "y": round(y / h, 5),
                        "conf": round(float(c), 4)}

    g = joints.get
    # Head center: the face cluster (nose + eyes), whatever's available.
    face = [g(n) for n in ("nose", "left_eye", "right_eye") if g(n)]
    head_center = (
        {"x": round(sum(p["x"] for p in face) / len(face), 5),
         "y": round(sum(p["y"] for p in face) / len(face), 5),
         "conf": round(min(p["conf"] for p in face), 4)}
        if face else None)
    neck = _mid(g("left_shoulder"), g("right_shoulder"))     # head-tilt pivot
    hip_center = _mid(g("left_hip"), g("right_hip"))         # lean pivot

    # Head tilt baseline: the angle of the eye line (degrees, + = right eye lower).
    head_tilt_deg = None
    le, re = g("left_eye"), g("right_eye")
    if le and re:
        import math
        head_tilt_deg = round(math.degrees(math.atan2(
            (le["y"] - re["y"]), (le["x"] - re["x"]) or 1e-6)), 2)
        # Normalize to a small signed tilt (eyes roughly level -> ~0).
        if head_tilt_deg > 90:
            head_tilt_deg -= 180
        elif head_tilt_deg < -90:
            head_tilt_deg += 180

    def _dist(a, b):
        return round(((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5, 5) \
            if a and b else None

    shoulder_width = _dist(g("left_shoulder"), g("right_shoulder"))
    torso_len = _dist(neck, hip_center)
    # Standing height as a fraction of canvas: head top (approx nose) to ankles.
    feet = _mid(g("left_ankle"), g("right_ankle"))
    height = round(feet["y"] - head_center["y"], 5) if (feet and head_center) else None

    confs = [j["conf"] for j in joints.values()]
    return {
        "joints": joints,
        "anchors": {
            "head_center": head_center,
            "neck": neck,
            "hip_center": hip_center,
        },
        "metrics": {
            "head_tilt_deg": head_tilt_deg,
            "shoulder_width": shoulder_width,
            "torso_len": torso_len,
            "height": height,
        },
        "n_joints": len(joints),
        "mean_conf": round(sum(confs) / len(confs), 4) if confs else 0.0,
        "model": data.get("model", ""),
    }


def load(path: Path) -> dict | None:
    """Parse her saved skeleton (data/avatar/rigpose.json), or None if absent."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return parse(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None
