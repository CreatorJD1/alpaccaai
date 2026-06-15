"""Turn her flat art into her per-part rig -- the one command that sets up the
layered avatar (real blink, lip-sync, head-turn, hair sway) from her own art.

Her rig renderer is already built and waiting (alpecca/rig.py, /live2d, the 3D
home rig tier); the only missing input is her illustration *decomposed into named
transparent layers*. The decomposition itself needs a GPU (See-Through), which
this script can't run for you -- but it does everything around it, and tells you
the exact one step it can't, with her real art path already filled in.

Usage:

  python scripts/decompose_art.py
      Auto-pick her base art and:
        - if her layers already exist (a PSD or a folder of layer PNGs nearby),
          import them into data/avatar/rig/ for you;
        - else if See-Through is available locally, run it on her art, then import;
        - else print the exact HF-Space / local-CUDA command (with her real art
          path) to produce the PSD -- then re-run this with that PSD.

  python scripts/decompose_art.py path/to/her_layers.psd     # import a PSD you made
  python scripts/decompose_art.py path/to/layers/            # import a layers folder
  python scripts/decompose_art.py --base path/to/her_art.png # override the base art

The GPU step is See-Through (https://github.com/shitagaki-lab/see-through) -- run
its local CUDA inference, or use its HuggingFace Space demo and download the PSD.
Point this script at a local checkout with ALPECCA_SEETHROUGH=/path/to/see-through
to have it run the inference for you.

Everything here uses ONLY her provided art -- it never invents or substitutes any.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import AVATAR_DIR, CHARACTER_DIR  # noqa: E402

RIG_DIR = AVATAR_DIR / "rig"
IMPORTER = ROOT / "scripts" / "import_rig.py"

# Where to look for her canonical full-figure art to decompose, best first. These
# are HER files; we only auto-pick among the art she already has.
BASE_CANDIDATES = [
    AVATAR_DIR / "source.png",
    CHARACTER_DIR / "reference" / "base-model.png",
    CHARACTER_DIR / "reference" / "master-character-sheet.png",
    AVATAR_DIR / "talkinghead" / "her.png",
    AVATAR_DIR / "portraits" / "idle.png",
]


def _pick_base(override: str | None) -> Path | None:
    if override:
        p = Path(override)
        return p if p.exists() else None
    for c in BASE_CANDIDATES:
        if c.exists():
            return c
    return None


def _run_importer(src: Path) -> int:
    """Hand a PSD or a layers folder to scripts/import_rig.py (which writes the
    role-tagged layers + rig.json, now seeded with her real skeleton anchors)."""
    print(f"\nImporting layers from {src} ...")
    return subprocess.call([sys.executable, str(IMPORTER), str(src)])


def _find_existing_layers(base: Path | None) -> Path | None:
    """Look for layers you've already produced: a .psd or a layers/ folder near
    her art or in data/avatar/. Returns the first found, or None."""
    search_dirs = {AVATAR_DIR, RIG_DIR.parent}
    if base:
        search_dirs.add(base.parent)
    for d in search_dirs:
        if not d.exists():
            continue
        for psd in sorted(d.glob("*.psd")):
            return psd
        layers = d / "layers"
        if layers.is_dir() and any(layers.glob("*.png")):
            return layers
    return None


def _seethrough_dir() -> Path | None:
    """A local See-Through checkout, if you've got one: ALPECCA_SEETHROUGH, or a
    sibling ../see-through with its inference entrypoint."""
    env = os.environ.get("ALPECCA_SEETHROUGH", "").strip()
    cands = [Path(env)] if env else []
    cands += [ROOT.parent / "see-through", ROOT / "see-through"]
    for d in cands:
        if d.is_dir() and (d / "inference_psd.py").exists():
            return d
    return None


def _instructions(base: Path) -> None:
    out_psd = AVATAR_DIR / "her_layers.psd"
    print(
        "\nHer rig needs her art decomposed into transparent layers -- that step\n"
        "needs a GPU (See-Through), which this script can't run here. Do ONE of:\n\n"
        "  A) HuggingFace Space (no local CUDA):\n"
        "     - open the See-Through demo Space, upload her base art:\n"
        f"         {base}\n"
        f"     - download the resulting PSD, then run:\n"
        f"         python scripts/decompose_art.py <that_file>.psd\n\n"
        "  B) Local CUDA checkout of See-Through:\n"
        "     - git clone https://github.com/shitagaki-lab/see-through\n"
        "     - install its requirements (PyTorch + CUDA), then EITHER point this\n"
        "       script at it and re-run:\n"
        "         set ALPECCA_SEETHROUGH=C:\\path\\to\\see-through   (Windows)\n"
        "         python scripts/decompose_art.py\n"
        "       OR run its inference yourself and import the PSD:\n"
        f"         python inference_psd.py --input \"{base}\" --output \"{out_psd}\"\n"
        f"         python scripts/decompose_art.py \"{out_psd}\"\n\n"
        "Either way the layers land in data/avatar/rig/ and /live2d + the 3D home\n"
        "rig tier animate her real parts (blink, lip-sync, head-turn, hair sway).\n"
    )


def main() -> int:
    args = [a for a in sys.argv[1:]]
    base_override = None
    if "--base" in args:
        i = args.index("--base")
        base_override = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]

    # An explicit PSD / folder argument -> just import it.
    if args:
        src = Path(args[0])
        if not src.exists():
            print(f"Not found: {src}")
            return 1
        return _run_importer(src)

    if (RIG_DIR / "rig.json").exists():
        print(f"She's already rigged -- {RIG_DIR / 'rig.json'} exists.\n"
              "Re-run with a new PSD/folder to replace her layers, or delete that\n"
              "file first. /live2d renders her per-part rig now.")
        return 0

    base = _pick_base(base_override)
    if base is None:
        print("Couldn't find her base art to decompose. Pass one with --base "
              "path/to/her_art.png (use HER art only).")
        return 1
    print(f"Her base art: {base}")

    # Already produced her layers? Import them.
    existing = _find_existing_layers(base)
    if existing is not None:
        print(f"Found layers you've already made: {existing}")
        return _run_importer(existing)

    # A local See-Through? Run it, then import.
    st = _seethrough_dir()
    if st is not None:
        out_psd = AVATAR_DIR / "her_layers.psd"
        print(f"Found See-Through at {st} -- running its inference on her art...")
        rc = subprocess.call([sys.executable, str(st / "inference_psd.py"),
                              "--input", str(base), "--output", str(out_psd)], cwd=str(st))
        if rc != 0 or not out_psd.exists():
            print("See-Through didn't produce a PSD (check its install / CUDA). "
                  "Falling back to instructions.")
            _instructions(base)
            return rc or 1
        return _run_importer(out_psd)

    # Otherwise: tell them the single GPU step, paths filled in.
    _instructions(base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
