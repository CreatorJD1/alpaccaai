# alpecca-rigger

A **modular Live2D auto-rigging + posing tool** for the Alpecca AI. It turns a
layered character **PSD** into clean rig data and can render posed frames at
runtime — importable as a Python package, usable from the CLI, or via the bundled
browser tool.

```
alpecca-rigger-tool/
├── alpecca_rigger/        # the Python package (import this from your AI)
│   ├── __init__.py        # public API
│   ├── classify.py        # PSD layer -> Live2D part classification
│   ├── rig.py             # Rig: read PSD, build manifest, export parts
│   ├── pose.py            # Pose model + .rigpose.json IO + named libraries
│   ├── render.py          # runtime pose renderer (Pillow)
│   ├── cli.py             # `python -m alpecca_rigger ...`
│   └── data/              # schema.json + alpecca.profile.json (the "learned" profile)
├── web/                   # the full browser rigger (open web/index.html)
├── examples/              # quickstart.py + sample renders
├── requirements.txt
└── pyproject.toml         # pip install -e .
```

## Install

```bash
pip install -r requirements.txt      # or:  pip install -e .
```

## Python API (what the Alpecca AI calls)

```python
from alpecca_rigger import build_rig, Pose, render_pose, list_poses, list_expressions

rig = build_rig("alpecca.psd")          # classify + analyze the PSD
rig.save_rig_json("alpecca.rig.json")   # compact rig descriptor
rig.save_manifest("alpecca.manifest.json")
rig.export_parts("parts/")              # per-part PNGs in draw order

# drive the character by name (libraries learned from the Alpecca master sheets)
pose = Pose().pose("Present Information").expression("Warm Smile")
img  = render_pose(rig, pose, scale=0.5)   # -> PIL.Image (RGBA)
img.save("frame.png")
pose.save("alpecca.rigpose.json")          # persist / share the pose
pose2 = Pose.load("alpecca.rigpose.json")  # reload
```

`Pose` is a plain parameter bag (`pose.params`) so the AI can also set values
directly, e.g. `Pose().set(ParamAngleZ=8, ParamArmRA=0.8, ParamMouthForm=0.6)`.

## CLI

```bash
python -m alpecca_rigger rig  alpecca.psd -o rig_out          # rig.json + manifest + parts/
python -m alpecca_rigger pose alpecca.psd "Wave" -e Happy -o wave.png -s 0.5
python -m alpecca_rigger pose alpecca.psd alpecca.rigpose.json -o frame.png
python -m alpecca_rigger list                                 # poses + expressions
```

## What it knows about Alpecca

`data/alpecca.profile.json` is distilled from the Alpecca master art sheets
(layer & deformer guide, hair/eye breakdowns, expression sheet, action library).
It gives the classifier Alpecca's exact vocabulary (ahoge, top/back/inner hair,
hood, jacket front/back, lanyard, thigh strap, stockings, socks, the full eye
stack), the documented draw order, physics groups, **12 expressions** and
**14 action poses** — all addressable by name. Extend the profile as you add more
reference sheets; the classifier and both renderers pick it up automatically.

## Two renderers, on purpose

- **`render.py` (Python / Pillow)** — fast runtime renderer for the AI. Rigid
  limb rotation about the shoulder/hip + head tilt + draw-order-correct
  compositing (arms tuck under the jacket; hand-in-front where the pose needs
  it). Great for companion gestures (arms down, wave, present, celebrate, …).
- **`web/` (browser)** — the full editor: mesh-skinned limb deformation (smooth
  elbow/knee bends), joint limiters, draggable skeleton, expression sliders,
  pose save/load, and clean Cubism-ready PSD export.

## Honest limits

- The `.moc3` runtime binary is proprietary to Live2D Cubism Editor and cannot be
  generated outside it. This tool does everything up to that point (clean parts,
  draw order, parameters, deformers, physics, bones) — import into Cubism to
  finish.
- The Python runtime renderer uses rigid limb rotation (no per-pixel elbow mesh),
  so hard elbow/knee gestures are approximate; use the browser tool for full
  mesh-skinned deformation and for export.
- Legs in the Python renderer are static by default (the sample PSD ships both
  legs as one layer); arm + head posing is fully supported.
```
