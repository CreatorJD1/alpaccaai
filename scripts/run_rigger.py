r"""Her rigger figure, live: a full-body posed render driven by her mood.

The CPU counterpart to run_talkinghead.py. It builds her rig once from her
decomposed art (the See-Through PSD), then loops: pull her current pose +
expression from the server (chosen from her real affect), render her from her
parts with alpecca-rigger, and POST the frame back. The home shows it as a top
avatar tier -- a clean, full-body figure that changes pose as she feels, from her
actual art, no GPU.

Re-renders only when her pose or expression changes, so it's light on the CPU and
fine to leave running alongside everything else.

Setup:
    python -m pip install -r vendor/alpecca-rigger/requirements.txt   # psd-tools, pillow, numpy
    # produce her rig PSD once via See-Through + scripts/decompose.py, or point at
    # any layered PSD of her:
    python scripts/run_rigger.py path\to\her.psd
    # (or set ALPECCA_PSD and run with no argument)

Then start Alpecca (server.py / start_full.bat) in one window and this in another;
refresh http://127.0.0.1:8765 and she becomes her rigged figure.
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor" / "alpecca-rigger"))

from config import HOST, PORT, AVATAR_DIR

URL = f"http://{HOST}:{PORT}"
DEFAULT_PSD = AVATAR_DIR / "her.psd"   # drop your See-Through PSD here for one-click


def main() -> None:
    psd = (sys.argv[1] if len(sys.argv) > 1
           else os.environ.get("ALPECCA_PSD", "") or str(DEFAULT_PSD))
    if not Path(psd).exists():
        print(f"No PSD found at {psd}.")
        print(f"Decompose her art with See-Through, then copy the .psd to:")
        print(f"   {DEFAULT_PSD}")
        print(f"(or pass a path: python scripts\\run_rigger.py C:\\path\\to\\her.psd)")
        sys.exit(1)
    if not Path(psd).exists():
        print(f"PSD not found: {psd}")
        sys.exit(1)
    try:
        import requests
        from alpecca_rigger import build_rig, Pose, render_pose
    except ImportError as e:
        print("Needs the rigger deps + requests:")
        print("  python -m pip install -r vendor/alpecca-rigger/requirements.txt requests")
        print(f"(missing: {getattr(e, 'name', e)})")
        sys.exit(2)

    try:
        requests.get(f"{URL}/state", timeout=5).raise_for_status()
    except Exception:
        print(f"Alpecca isn't reachable at {URL} -- start the server first.")
        sys.exit(1)

    print(f"Building her rig from {Path(psd).name} ...")
    rig = build_rig(psd)
    scale = float(os.environ.get("ALPECCA_RIGGER_SCALE", "0.5"))
    print("Her rigged figure is live. Ctrl+C to stop.")

    last = None
    try:
        while True:
            try:
                d = requests.get(f"{URL}/rigger/pose", timeout=3).json()
            except Exception:
                time.sleep(0.5); continue
            key = (d.get("pose"), d.get("expression"))
            if key != last:                      # only re-render when her pose changes
                last = key
                try:
                    pose = Pose().pose(d["pose"]).expression(d["expression"])
                    img = render_pose(rig, pose, scale=scale)   # PIL RGBA
                    buf = io.BytesIO(); img.save(buf, format="PNG")
                    requests.post(f"{URL}/rigger/frame", data=buf.getvalue(),
                                  headers={"Content-Type": "image/png"}, timeout=4)
                    print(f"  posed: {d['pose']} / {d['expression']}")
                except Exception as e:
                    print(f"  (render skipped: {e})")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped. Her figure falls back to the cheaper tier.")


if __name__ == "__main__":
    main()
