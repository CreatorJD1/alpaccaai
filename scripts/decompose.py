"""See-Through -> her layered rig: the layer-splitting pipeline.

See-Through (shitagaki-lab/see-through, "Single-image Layer Decomposition for
Anime Characters", SIGGRAPH 2026) decomposes a single anime image into a ~23-layer
PSD -- hair stack, face, the full eye stack, clothing, accessories -- with
inferred draw order and inpainted occluded regions. That PSD is exactly what her
rigger consumes. This script is the bridge: PSD in, her clean per-part rig out
(into data/avatar/rigger/), ready for her avatar to drive from her mood.

Two entry points:

  # (A) You already have a See-Through PSD -- from its free HuggingFace Space,
  #     ModelScope, ComfyUI-See-through, or a local run. Build her rig from it:
  python scripts/decompose.py path/to/her_seethrough.psd

  # (B) You have a >=8 GB GPU and a local See-Through checkout in vendor/see-through.
  #     Decompose an image AND build the rig in one go:
  python scripts/decompose.py --seethrough path/to/her_art.png

WHY THE SPLIT (VRAM): See-Through needs ~8-16 GB VRAM even NF4-quantized. On a
4 GB laptop you can't run it locally -- run the decomposition on its free
HuggingFace Space (1-2 PSDs/day) or ModelScope, download the PSD, and use path (A).
The rig-building half (this script's main job) is CPU-only and runs anywhere.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# Make the vendored rigger importable.
sys.path.insert(0, str(ROOT / "vendor" / "alpecca-rigger"))

from config import AVATAR_DIR

OUT = AVATAR_DIR / "rigger"
# Where your See-Through checkout lives. Point ALPECCA_SEETHROUGH_DIR at it if it's
# not vendored here (e.g. set ALPECCA_SEETHROUGH_DIR=C:\Users\Jason\see-through).
SEETHROUGH = Path(os.environ.get("ALPECCA_SEETHROUGH_DIR", str(ROOT / "vendor" / "see-through")))


def build_rig_from_psd(psd_path: Path) -> None:
    """Run the vendored alpecca-rigger over a See-Through PSD: classify the layers
    into her parts, export per-part PNGs in draw order, and write the rig
    descriptor + manifest. Output lands in data/avatar/rigger/."""
    try:
        from alpecca_rigger import build_rig
    except ImportError as e:
        print("The rigger needs psd-tools + pillow + numpy:")
        print("  python -m pip install -r vendor/alpecca-rigger/requirements.txt")
        print(f"(missing: {getattr(e, 'name', e)})")
        sys.exit(2)
    if not psd_path.exists():
        print(f"PSD not found: {psd_path}")
        sys.exit(1)
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Building her rig from {psd_path.name} (classifying layers against her profile)...")
    rig = build_rig(str(psd_path))
    rig.save_rig_json(str(OUT / "alpecca.rig.json"))
    rig.save_manifest(str(OUT / "alpecca.manifest.json"))
    rig.export_parts(str(OUT / "parts"))
    n = len(list((OUT / "parts").glob("*.png")))
    print(f"\nDone. {n} parts + rig.json + manifest -> {OUT}")
    print("Her rigged figure is ready. (Next: the avatar serves it from her mood.)")


def run_seethrough_local(image: Path) -> Path:
    """Run a local See-Through checkout (vendor/see-through) to decompose an image
    into a PSD, picking a low-VRAM path automatically. Returns the PSD path.
    Realistically needs >=8 GB VRAM -- on a 4 GB card use the HF Space instead."""
    if not SEETHROUGH.exists():
        print("No local See-Through at vendor/see-through.")
        print("Clone it (needs a >=8 GB GPU):")
        print("  git clone https://github.com/shitagaki-lab/see-through vendor/see-through")
        print("Or -- recommended on a 4 GB laptop -- decompose online and use path (A):")
        print("  https://huggingface.co/spaces/24yearsold/see-through-demo  (free, your HF login)")
        sys.exit(1)
    # NF4-quantized pipeline is the lowest-VRAM local option (~8 GB).
    script = SEETHROUGH / "inference" / "scripts" / "inference_psd_quantized.py"
    if not script.exists():
        script = SEETHROUGH / "inference" / "scripts" / "inference_psd.py"
    print(f"Running See-Through ({script.name}) on {image.name} -- this is slow...")
    subprocess.run([sys.executable, str(script), "--srcp", str(image),
                    "--save_to_psd", "--group_offload"], cwd=str(SEETHROUGH), check=True)
    out_dir = SEETHROUGH / "workspace" / "layerdiff_output"
    psds = sorted(out_dir.glob("*.psd"), key=lambda p: p.stat().st_mtime)
    if not psds:
        print(f"No PSD produced in {out_dir}.")
        sys.exit(1)
    return psds[-1]


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)
    if args[0] == "--seethrough":
        if len(args) < 2:
            print("usage: python scripts/decompose.py --seethrough <image>")
            sys.exit(1)
        psd = run_seethrough_local(Path(args[1]))
        build_rig_from_psd(psd)
    else:
        build_rig_from_psd(Path(args[0]))


if __name__ == "__main__":
    main()
