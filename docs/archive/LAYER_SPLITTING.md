# Layer splitting → her rigged avatar

How a single picture of her becomes a clean, posable, layered figure — using
**See-Through** for decomposition and the vendored **alpecca-rigger** for the rig.

```
 single image  ──(See-Through)──▶  23-layer PSD  ──(decompose.py)──▶  her rig
 (her full-body art)                (hair/face/eyes/                 (parts/ + rig.json
                                     clothing/...)                    in data/avatar/rigger/)
                                                                          │
                                                                          ▼
                                                              avatar drives it from her mood
```

## Step 1 — Decompose her art into layers (See-Through)

**See-Through** (`shitagaki-lab/see-through`, SIGGRAPH 2026) turns one anime image
into a PSD of up to **23 inpainted, semantically separated layers** with inferred
draw order. That's the hard, GPU-heavy part.

**VRAM reality:** it needs ~8–16 GB even NF4-quantized. Your **RTX 3050 (4 GB)
can't run it locally.** Use one of these to get the PSD (one-time, per art):

- **Free HuggingFace Space** — `huggingface.co/spaces/24yearsold/see-through-demo`
  (your HF login; ~1–2 PSDs/day, 2–3 min each at 1280). **Recommended for you.**
- **ModelScope demo** — free, slightly higher resolution.
- **ComfyUI-See-through** (`jtydhr88/ComfyUI-See-through`) — you have ComfyUI, but
  the 8 GB+ VRAM requirement still applies on your laptop.
- **Local** (only with a ≥8 GB GPU): `git clone …/see-through vendor/see-through`,
  install per its README, then `python scripts/decompose.py --seethrough her.png`.

Upload her **full-body transparent art** (the master render, not the chibi);
download the resulting `.psd`.

## Step 2 — Build her rig from the PSD (this repo)

The bridge is CPU-only and runs on your laptop:

```
python -m pip install -r vendor/alpecca-rigger/requirements.txt   # psd-tools, pillow, numpy
python scripts/decompose.py path\to\her_seethrough.psd
```

This runs **alpecca-rigger** over the PSD: it classifies each layer against her
profile (`vendor/alpecca-rigger/alpecca_rigger/data/alpecca.profile.json` — distilled
from her master sheets, so it knows her ahoge, hood, lanyard, the full eye stack,
etc.), exports clean per-part PNGs in draw order, and writes a compact rig
descriptor + manifest into **`data/avatar/rigger/`**.

## Step 3 — She wears it

`alpecca-rigger` ships a Python runtime renderer and 12 named expressions + 14
named poses that line up with her affect, so the avatar maps her live mood → a
pose + expression and renders her from her real art, locally, no GPU. (Wiring that
render tier into the home is the next integration step — the rig data from Step 2
is what it consumes.)

## Notes

- **Already done:** her art is *already decomposed* in
  `vendor/alpecca-rigger/examples/parts/` (24 layers), so you can build a rig from
  those immediately to try the pipeline, before re-running See-Through on a new pose.
- See-Through's own ecosystem also feeds **StretchyStudio** (in-browser auto-rig →
  Spine) and **PachiPakuGen** (blink/lip-sync materials) if you want those paths.
- The decomposition is one-time per piece of art; the rig + render run locally
  forever after.
