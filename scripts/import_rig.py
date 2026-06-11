"""Import a decomposed character into Alpecca's layered rig.

You produce her layers (the part that needs a GPU); this script turns them into
the rig her renderer drives. Two input shapes:

  - a **PSD** of named layers (what See-Through outputs):
        python scripts/import_rig.py her_layers.psd
  - a **folder** of transparent layer PNGs (named by part):
        python scripts/import_rig.py path/to/layers/

It writes role-tagged PNGs + rig.json into data/avatar/rig/, after which the
/live2d page renders her as a real per-part rig (blink, lip-sync, head-turn,
hair sway) driven by her live mood -- no Cubism editor.

How to get her layers (the upstream step, on your machine/GPU):
  1. See-Through -- https://github.com/shitagaki-lab/see-through
       git clone, install its requirements (PyTorch + CUDA), then:
         python inference_psd.py --input her_art.png --output her_layers.psd
       (or use its HuggingFace Space / ModelScope demo, download the PSD.)
  2. Run this importer on the PSD.

Layer names are mapped to rig roles by alpecca.rig.role_for, which is forgiving
-- "Front Bangs", "Eye Highlight", "Mouth_A", "Jacket Outer" all land on the
right role, and anything unrecognized becomes part of her body so nothing is
dropped.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import AVATAR_DIR
from alpecca import rig

OUT_DIR = AVATAR_DIR / "rig"


def _from_psd(psd_path: Path) -> None:
    try:
        from psd_tools import PSDImage
    except ImportError:
        print("Reading a PSD needs psd-tools:  pip install psd-tools")
        sys.exit(2)
    psd = PSDImage.open(psd_path)
    W, H = psd.size
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    layers = []
    i = 0
    for layer in psd.descendants():
        if layer.is_group():
            continue
        img = layer.composite(viewport=(0, 0, W, H), force=True)  # full-canvas RGBA
        if img is None:
            continue
        role = rig.role_for(layer.name)
        fname = f"{i:02d}_{rig._slug(layer.name) or role}.png"
        img.convert("RGBA").save(OUT_DIR / fname)
        layers.append({"file": fname, "role": role})
        print(f"  {layer.name!r:32} -> {role:11} {fname}")
        i += 1
    if not layers:
        print("No usable layers found in the PSD.")
        sys.exit(1)
    rig.save_manifest(layers, [W, H], OUT_DIR)
    print(f"\nImported {len(layers)} layers -> {OUT_DIR}\nReload /live2d to see her rigged.")


def _from_folder(folder: Path) -> None:
    from PIL import Image
    pngs = sorted(folder.glob("*.png"))
    if not pngs:
        print(f"No PNGs in {folder}")
        sys.exit(1)
    W, H = Image.open(pngs[0]).size
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    layers = []
    for i, p in enumerate(pngs):
        role = rig.role_for(p.stem)
        fname = f"{i:02d}_{rig._slug(p.stem) or role}.png"
        Image.open(p).convert("RGBA").save(OUT_DIR / fname)
        layers.append({"file": fname, "role": role})
        print(f"  {p.name:32} -> {role:11} {fname}")
    rig.save_manifest(layers, [W, H], OUT_DIR)
    print(f"\nImported {len(layers)} layers -> {OUT_DIR}\nReload /live2d to see her rigged.")


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(0)
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"Not found: {src}")
        sys.exit(1)
    if src.is_dir():
        _from_folder(src)
    elif src.suffix.lower() == ".psd":
        _from_psd(src)
    else:
        print("Pass a .psd file or a folder of layer PNGs.")
        sys.exit(1)


if __name__ == "__main__":
    main()
