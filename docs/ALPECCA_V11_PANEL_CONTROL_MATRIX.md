# Alpecca VRoid v11 – Control Matrix (Operator Manual)

Purpose: keep the v11 pass fast and stable by using only known-good VRoid Studio controls in a fixed order.

Working checkpoint:

- `data\alpecca_art_source\vrm_experiments\alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`

## 1) Startup + reference lock

1. Launch VRoid Studio from manifest path.
2. Open the checkpoint file from **File → Open**.
3. Open all reference photos in a separate image pane for side-by-side matching:

- `data/alpecca_art_source/vrm_custom_assets/ac167033/1-Photo-1.jpg`
- `data/alpecca_art_source/vrm_custom_assets/ac167033/2-Photo-2.jpg`
- `data/alpecca_art_source/vrm_custom_assets/ac167033/3-Photo-3.jpg`
- `data/alpecca_art_source/vrm_custom_assets/ac167033/4-Photo-4.jpg`
- `data/alpecca_art_source/vrm_custom_assets/ac167033/5-Photo-5.jpg`

## 2) Panel map (allowed edits in v11)

### Body

- Open `Body` tab.
- Confirm height lock close to existing baseline (`170.2 cm` target).
- Do not globally scale model unless absolutely necessary.
- Keep torso/waist/legs as previously accepted silhouettes.

### Face

- Open `Face` tab.
- Keep mouth/lips neutral unless matching references require subtle correction.
- Use the face texture path for brows/iris/lashes only if needed:
  - Brows
  - Eyeliner
  - Irises
- Do not re-run a full re-texture pass if base lock is already stable.

### Hairstyle

- Open `Hairstyle` → `Edit Hairstyle`.
- Work in this order:
  1. `Hairstyle Sets`
  2. `Front`
  3. `Side`
  4. `Back`
  5. `Ahoge`
  6. `Overall Hair`
  7. `Base Hair`
- For each segment: increase depth/flow while avoiding shell collapse in 90°/135° turns.
- Keep ahoge as one curved single lock; avoid twin tufts.

### Outfit

- Open `Outfit` only if silhouette is still clearly blocked or generic.
- Preserve 170.2/170.4 baseline style consistency:
  - top + shoulder line
  - leg coverage
  - footwear proportions

### Accessories

- Open `Accessories`.
- Keep only target identity item set for this batch:
  - `alpecca_blue_x_hair_clip.svg` (left side only)
- Remove unrelated/default accessories introduced by UI defaults.

### Texture Editor (if required)

- Open the relevant texture only for the exact target area:
  - hair lower wash and transitions
  - accessory texture cleanup
- Do not batch-edit unrelated textures in one pass.

## 3) Camera/view ladder

Use these checks during every significant edit pass.

- Low yaw ladder: `Front`, `Front-Right`, `Right`, `Back-Right`, `Back`
- Eye ladder: same sequence
- High ladder: same sequence
- Then mirror checks for left-side equivalents

### Practical input sequence

- Orbit by controlled steps, no fast jumps.
- Mouse wheel: zoom only enough to match reference framing.
- Keep character at scene center before each check.

## 4) Save/update rule

- Save **in-place only** (`...v11_hair_gradient_ahoge.vroid`).
- No versioned `v11_*` saves during micro-tweaks.
- Allowed checkpoints:
  - after at least one full ladder pass is completed,
  - and all required identity checks pass.

## 5) Forbidden operations in this phase

- No runtime or game code changes.
- No alternate model export from this checkpoint.
- No full body proportions overhaul during the same run.
- No new accessory categories beyond allowed identity items.

## 6) Hard acceptance checks

- Ahoge remains single and crown-attached at all angles.
- Lower hair gradient reads smooth, no hard edge steps.
- Clip stays on left side only across front/side/back mirror checks.
- No leg or waist narrowing when side profile turns to right/left equivalent.

After pass completion:

```powershell
python scripts/update_v11_vroid_state.py --state base-gate-validated --notes "v11 control matrix batch passed"
```

If blocked:

```powershell
python scripts/update_v11_vroid_state.py --state base-gate-rework --notes "control matrix pass failed: <specific issue>"
```
