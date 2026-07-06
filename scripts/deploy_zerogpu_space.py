"""Push the alpecca-zerogpu Space files to Hugging Face so the endpoints
(/chat, /generate_stage4_tile, and the new /vision) go live and the Space
rebuilds. Uses the configured HF token.

    python scripts/deploy_zerogpu_space.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import ZEROGPU_SPACE, HF_TOKEN, ZEROGPU_TOKEN


def main() -> int:
    space = ZEROGPU_SPACE
    token = ZEROGPU_TOKEN or HF_TOKEN
    if not space:
        print("No ALPECCA_ZEROGPU_SPACE configured.", file=sys.stderr)
        return 2
    if not token:
        print("No HF token configured (HF_TOKEN / ALPECCA_ZEROGPU_TOKEN).", file=sys.stderr)
        return 2

    from huggingface_hub import HfApi
    api = HfApi(token=token)
    space_dir = ROOT / "spaces" / "alpecca-zerogpu"
    pushed = []
    for fname in ("app.py", "requirements.txt", "README.md"):
        f = space_dir / fname
        if not f.exists():
            continue
        api.upload_file(
            path_or_fileobj=str(f),
            path_in_repo=fname,
            repo_id=space,
            repo_type="space",
            commit_message="Add /vision cloud-vision endpoint",
        )
        pushed.append(fname)
        print("uploaded", fname)
    print(f"Pushed {pushed} to https://huggingface.co/spaces/{space} -- it will rebuild "
          "(installs qwen-vl-utils + torchvision; a few minutes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
