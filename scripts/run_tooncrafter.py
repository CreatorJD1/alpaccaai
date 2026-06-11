"""Inbetween her poses into avatar clips with ToonCrafter.

ToonCrafter (https://github.com/ToonCrafter/ToonCrafter) is a generative cartoon
inbetweener: give it two keyframes and it *generates* the smooth motion between
them, handling large changes (a head turn, an arm raise) that plain frame
interpolation can't. This script wires it into her avatar: feed it two of her
poses, it makes the transition, and we assemble a looping MP4 into her video
avatar tier (data/avatar/<state>.mp4), which the /live2d and chat avatars already
play per state.

This is the *pre-rendered* complement to her live rigs (Spine / Talking Head):
no continuous GPU at play time, real animation from her own art.

Usage:
    # one clip from two poses (ping-pong looped so it cycles seamlessly):
    python scripts/run_tooncrafter.py pair \\
        data/avatar/poses/present.png data/avatar/poses/reach.png speaking --loop

    # the standard set (idle/greet/talk/think) from her poses:
    python scripts/run_tooncrafter.py recipe

Valid clip names are her avatar states: standby, listening, thinking, speaking.

Setup (one-time, needs an Nvidia GPU):
    git clone https://github.com/ToonCrafter/ToonCrafter
    # install its requirements + download its checkpoint, then point this script
    # at its inference command:
    set TOONCRAFTER_CMD=python <ToonCrafter>/scripts/run.py   (Windows)
    export TOONCRAFTER_CMD="python /path/ToonCrafter/scripts/run.py"
    pip install imageio imageio-ffmpeg pillow

NOTE: ToonCrafter's CLI flags vary by release; `_invoke` passes the two images,
an output dir, and a frame count, and then collects whatever frames/video it
wrote. If your build's flags differ, adjust `_invoke` -- the frames->loop->mp4
half below is the part that's stable.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import AVATAR_DIR
from alpecca.avatar import CLIPS              # the valid clip/state names

VALID = set(CLIPS)                            # standby/listening/thinking/speaking

# Map our clip "states" to the pose pairs that make a fitting motion. The user
# can override any of these on the command line.
RECIPE = {
    "standby":   ("present.png", "present.png"),   # gentle idle (near-identical)
    "listening": ("present.png", "lean.png"),      # leans in to listen
    "thinking":  ("lean.png", "lean.png"),         # small thoughtful sway
    "speaking":  ("present.png", "reach.png"),     # animated, reaching out
}


def _invoke(start: Path, end: Path, out_dir: Path, frames: int) -> None:
    """Run ToonCrafter to generate the inbetween frames. Honors TOONCRAFTER_CMD;
    raises if it isn't configured so the caller can explain setup."""
    cmd = os.environ.get("TOONCRAFTER_CMD")
    if not cmd:
        raise RuntimeError(
            "Set TOONCRAFTER_CMD to your ToonCrafter inference command "
            "(see this script's header).")
    args = cmd.split() + [
        "--input_start", str(start), "--input_end", str(end),
        "--output_dir", str(out_dir), "--frames", str(frames),
    ]
    subprocess.run(args, check=True)


def _frames_to_loop_mp4(out_dir: Path, dest: Path, fps: int, loop: bool) -> None:
    """Assemble ToonCrafter's output frames into an MP4 in her avatar dir. With
    --loop we ping-pong (forward then reverse) so the clip cycles seamlessly."""
    import imageio.v2 as imageio
    frames = sorted(out_dir.glob("*.png")) or sorted(out_dir.glob("*.jpg"))
    if not frames:
        # ToonCrafter may emit a video instead of frames; pass it through.
        vids = sorted(out_dir.glob("*.mp4"))
        if vids:
            dest.write_bytes(vids[0].read_bytes())
            return
        raise RuntimeError(f"No frames or video found in {out_dir}")
    imgs = [imageio.imread(f) for f in frames]
    if loop:
        imgs = imgs + imgs[-2:0:-1]            # ping-pong
    dest.parent.mkdir(parents=True, exist_ok=True)
    imageio.mimsave(dest, imgs, fps=fps, codec="libx264", quality=8)
    print(f"  wrote {dest}  ({len(imgs)} frames)")


def make_clip(start: Path, end: Path, name: str, loop: bool, fps: int = 12,
              frames: int = 16) -> None:
    if name not in VALID:
        print(f"'{name}' isn't an avatar state. Use one of: {', '.join(sorted(VALID))}")
        sys.exit(1)
    for p in (start, end):
        if not p.exists():
            print(f"Missing pose: {p}"); sys.exit(1)
    dest = AVATAR_DIR / CLIPS[name]
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        print(f"Inbetweening {start.name} -> {end.name} as {name} ...")
        _invoke(start, end, out, frames)
        _frames_to_loop_mp4(out, dest, fps, loop)
    print(f"Done. Reload the avatar -- {name} now plays her generated clip.")


def main() -> None:
    try:
        import imageio  # noqa: F401
    except ImportError:
        print("Needs imageio:  pip install imageio imageio-ffmpeg")
        sys.exit(2)
    args = sys.argv[1:]
    if args and args[0] == "pair" and len(args) >= 4:
        loop = "--loop" in args
        make_clip(Path(args[1]), Path(args[2]), args[3], loop)
    elif args and args[0] == "recipe":
        poses = AVATAR_DIR / "poses"
        for name, (a, b) in RECIPE.items():
            make_clip(poses / a, poses / b, name, loop=True)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
