"""Talking Head Anime 3 runner: her face, animated live by her real state.

This is the GPU process that brings her neural face alive. It loads THA3
(pkhungurn/talking-head-anime-3-demo) and a single 512x512 portrait of her,
then loops: pull her current expressive pose from the server (derived from her
real mood), add per-frame auto-blink and lip-sync, run THA3 to generate the
frame, and POST it back. The /live2d page shows the stream as her top tier.

It runs as a *separate process* against the same one mind, exactly like
run_talk.py -- her brain stays in server.py; this is just an actuator.

Setup (one-time, needs an Nvidia GPU):
    git clone https://github.com/pkhungurn/talking-head-anime-3-demo
    # install its requirements (PyTorch + CUDA) and download its models, then
    # make the `tha3` package importable (run from that repo, or set PYTHONPATH)
    pip install requests pillow torch

    # 1. Prepare her image (512x512, transparent, head centred):
    python scripts/run_talkinghead.py --prep data/avatar/poses/present.png
    # 2. Start Alpecca:  python server.py
    # 3. Run her face:   python scripts/run_talkinghead.py

NOTE: THA3's exact pose-parameter names vary slightly by release. The mapping in
`_build_pose` below looks them up by name from the loaded model and skips any it
can't find, so it degrades rather than crashes -- but if blink/mouth don't move,
print `poser.get_pose_parameter_groups()` and adjust the names here.
"""
from __future__ import annotations

import io
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import HOST, PORT, AVATAR_DIR

URL = f"http://{HOST}:{PORT}"
IMG_PATH = AVATAR_DIR / "talkinghead" / "her.png"


# --- image prep: crop her art to THA3's 512 head-centred format -------------

def prep_head_image(src: str) -> None:
    """Crop a full-body transparent render down to THA3's input: 512x512, alpha,
    character upright and facing forward, head in the upper-middle. This is a
    heuristic (head ~ top of the alpha bounding box); eyeball the result and
    re-crop by hand if her face isn't centred near the top."""
    from PIL import Image
    im = Image.open(src).convert("RGBA")
    bbox = im.getbbox()                      # tight box around non-transparent
    if bbox:
        im = im.crop(bbox)
    w, h = im.size
    # Take the head + shoulders: roughly the top 55% of the figure, square.
    crop_h = int(h * 0.55)
    side = max(w, crop_h)
    head = im.crop((0, 0, w, crop_h))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(head, ((side - w) // 2, int(side * 0.08)))   # head near the top
    canvas = canvas.resize((512, 512), Image.LANCZOS)
    IMG_PATH.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(IMG_PATH)
    print(f"Saved her THA3 portrait -> {IMG_PATH}\n"
          f"Open it and check her head sits centred near the top; re-crop if not.")


# --- THA3 driving -----------------------------------------------------------

def _name_index_map(poser):
    """Build {parameter_name: flat_index} from the model's pose groups so we can
    set params by name regardless of THA3's internal ordering."""
    mapping = {}
    idx = 0
    for g in poser.get_pose_parameter_groups():
        arity = g.get_arity()
        for i in range(arity):
            try:
                name = g.get_parameter_name(i)
            except Exception:
                name = f"{g.get_group_name()}_{i}" if arity > 1 else g.get_group_name()
            mapping[name] = idx
            idx += 1
    return mapping


def _set(pose, names, value, *candidates):
    """Set the first matching THA3 parameter (by exact name or substring)."""
    for c in candidates:
        if c in names:
            pose[names[c]] = value
            return
    for c in candidates:                      # fall back to substring match
        for k, i in names.items():
            if c in k:
                pose[i] = value
                return


def _build_pose(poser, names, mood_pose, t, speaking):
    """Compose the full THA3 pose tensor: her mood (slow params) + per-frame
    auto-blink and lip-sync."""
    import torch
    pose = [0.0] * poser.get_num_parameters()
    mp = mood_pose
    _set(pose, names, mp.get("eyebrow_happy", 0), "eyebrow_happy_left", "eyebrow_happy")
    _set(pose, names, mp.get("eyebrow_happy", 0), "eyebrow_happy_right")
    _set(pose, names, mp.get("eyebrow_troubled", 0), "eyebrow_troubled_left", "eyebrow_troubled")
    _set(pose, names, mp.get("eyebrow_troubled", 0), "eyebrow_troubled_right")
    _set(pose, names, max(0.0, mp.get("mouth_smile", 0)), "mouth_raised_corner_left", "mouth_raised_corner")
    _set(pose, names, max(0.0, mp.get("mouth_smile", 0)), "mouth_raised_corner_right")
    _set(pose, names, max(0.0, mp.get("mouth_frown", 0)), "mouth_lowered_corner_left", "mouth_lowered_corner")
    _set(pose, names, max(0.0, mp.get("mouth_frown", 0)), "mouth_lowered_corner_right")
    _set(pose, names, mp.get("eye_relaxed", 0), "eye_relaxed_left", "eye_relaxed")
    _set(pose, names, mp.get("eye_relaxed", 0), "eye_relaxed_right")
    _set(pose, names, mp.get("iris_small", 0), "iris_small_left", "iris_small")
    _set(pose, names, mp.get("iris_small", 0), "iris_small_right")
    _set(pose, names, mp.get("head_y", 0), "head_y")
    _set(pose, names, math.sin(t * 0.6) * 0.15, "head_x")          # gentle idle sway
    _set(pose, names, (math.sin(t * (1.0 + mp.get("breathing", 0.4))) * 0.5 + 0.5), "breathing")

    # auto-blink: a quick close every few seconds
    cycle = t % 4.0
    blink = 1.0 if cycle > 3.88 else 0.0
    _set(pose, names, blink, "eye_wink_left", "eye_wink")
    _set(pose, names, blink, "eye_wink_right")
    # lip-sync: open the mouth rhythmically while she's speaking
    mouth = abs(math.sin(t * 11)) * 0.9 if speaking else 0.0
    _set(pose, names, mouth, "mouth_aaa")
    return torch.tensor(pose, dtype=torch.float32)


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--prep":
        prep_head_image(sys.argv[2])
        return

    try:
        import requests, torch
        from PIL import Image
        from tha3.poser.modes.load_poser import load_poser
        from tha3.util import extract_pytorch_image_from_filelike, \
            pytorch_rgba_to_numpy_image
    except ImportError as exc:
        print("Talking-head mode needs THA3 + torch + requests + pillow.")
        print("Clone pkhungurn/talking-head-anime-3-demo, install its requirements,")
        print("make the `tha3` package importable, then: pip install requests pillow")
        print(f"(missing: {exc.name})")
        sys.exit(2)

    if not IMG_PATH.exists():
        print(f"No portrait at {IMG_PATH}. Make one first:")
        print(f"  python scripts/run_talkinghead.py --prep <her_transparent_art.png>")
        sys.exit(1)
    try:
        requests.get(f"{URL}/state", timeout=5).raise_for_status()
    except Exception:
        print(f"Alpecca isn't reachable at {URL} -- start `python server.py` first.")
        sys.exit(1)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Loading THA3 on {device} (first run downloads models)...")
    poser = load_poser("standard_float", device)
    names = _name_index_map(poser)
    image = extract_pytorch_image_from_filelike(str(IMG_PATH)).to(device).unsqueeze(0)

    print("Her face is live. Ctrl+C to stop.")
    import numpy as np
    t0 = time.time()
    pose_cache, speaking, last_pull = {}, False, 0.0
    try:
        while True:
            t = time.time() - t0
            if t - last_pull > 0.25:                # refresh mood pose ~4x/sec
                try:
                    d = requests.get(f"{URL}/talkinghead/pose", timeout=2).json()
                    pose_cache = d.get("pose", {}); speaking = d.get("speaking", False)
                except Exception:
                    pass
                last_pull = t
            pose_t = _build_pose(poser, names, pose_cache, t, speaking).to(device).unsqueeze(0)
            with torch.no_grad():
                out = poser.pose(image, pose_t)[0]
            arr = pytorch_rgba_to_numpy_image(out.detach().cpu())
            frame = Image.fromarray(np.uint8(np.rint(arr * 255)), mode="RGBA").convert("RGB")
            buf = io.BytesIO(); frame.save(buf, format="JPEG", quality=85)
            try:
                requests.post(f"{URL}/talkinghead/frame", data=buf.getvalue(),
                              headers={"Content-Type": "image/jpeg"}, timeout=2)
            except Exception:
                pass
    except KeyboardInterrupt:
        print("\nStopped. Her face is back to the cheaper rig.")


if __name__ == "__main__":
    main()
