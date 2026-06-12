"""Assemble her certified rig samples into a training manifest (Path 3).

This is the back half of her avatar's recursive loop. RIGFORGE certifies a rig
(its readiness check), then captures the figure + corrected keypoints + rig as a
labelled sample -- staged under data/avatar/samples/{figures,pose,rigs} by the
/rigforge/capture endpoint. This script walks those triplets, writes a manifest
(JSONL), and -- when you ask -- pushes the whole set to the Hugging Face dataset
in config (CREATORJD/Alpeccaai-data).

Why it matters: each certified rig is a labelled example of *her* art with known
joints. Train the RIGFORGE Pose Space on the growing set and her detector gets
better at her specific character over time -- her self-improvement, made literal
for her body. The loop is: rig her -> certify -> capture -> retrain -> rig her
better next time.

Usage:
    python scripts/build_manifest.py            # build manifest.jsonl locally
    python scripts/build_manifest.py --push     # also upload to the HF dataset

The push needs `huggingface_hub` and a token (huggingface-cli login, or HF_TOKEN);
without them the local manifest is still written, so the loop works offline first.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import RigData


def _triplets(base: Path) -> list[dict]:
    """Find every complete sample: a figure with its pose and rig. We key on the
    figure stem so a half-captured sample (missing pose or rig) is simply skipped
    rather than poisoning the training set."""
    figs = base / "figures"
    if not figs.exists():
        return []
    out = []
    for fig in sorted(figs.glob("*.png")):
        name = fig.stem
        pose = base / "pose" / f"{name}.rigpose.json"
        rig = base / "rigs" / f"{name}.rig.json"
        entry = {"name": name, "figure": f"figures/{fig.name}"}
        if pose.exists():
            entry["pose"] = f"pose/{pose.name}"
        if rig.exists():
            entry["rig"] = f"rigs/{rig.name}"
        # A usable training sample needs at least the figure and its keypoints.
        if "pose" in entry:
            out.append(entry)
    return out


def build(base: Path) -> Path:
    """Write manifest.jsonl listing every complete triplet; return its path."""
    samples = _triplets(base)
    base.mkdir(parents=True, exist_ok=True)
    manifest = base / "manifest.jsonl"
    with manifest.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"Assembled {len(samples)} certified sample(s) -> {manifest}")
    if not samples:
        print("  (no complete figure+pose triplets yet -- certify & capture some "
              "rigs in RIGFORGE first.)")
    return manifest


def push(base: Path, repo: str) -> None:
    """Upload the staged samples + manifest to the HF dataset. Degrades to a clear
    message if huggingface_hub or a token isn't available -- the local manifest is
    already written either way."""
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("Push needs huggingface_hub:  pip install huggingface_hub")
        return
    api = HfApi()
    try:
        api.create_repo(repo, repo_type="dataset", exist_ok=True)
        api.upload_folder(folder_path=str(base), repo_id=repo, repo_type="dataset",
                          path_in_repo=".", commit_message="Add certified rig samples")
        print(f"Pushed {base} -> https://huggingface.co/datasets/{repo}")
    except Exception as e:
        print(f"Push failed ({e}). Log in with `huggingface-cli login` or set HF_TOKEN.")


def main() -> None:
    base = RigData.SAMPLES_DIR
    build(base)
    if "--push" in sys.argv[1:]:
        push(base, RigData.HF_DATASET)
    else:
        print(f"To upload to {RigData.HF_DATASET}: python scripts/build_manifest.py --push")


if __name__ == "__main__":
    main()
