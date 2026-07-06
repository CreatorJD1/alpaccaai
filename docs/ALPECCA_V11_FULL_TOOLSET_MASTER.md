# Alpecca VRoid v11 Full-Toolset Master Pass (Reference Match Session)

This pass is **an experimental art-reference build only**. It must not modify runtime
application code (`apps/`, `server.py`, or house runtime).

## Mission

Build a VRM source proxy that is as close as possible to the locked 2D references,
using the full VRoid Studio panel workflow instead of texture-only patching.

## Scope

- Allowed: body proportion lock, face geometry tuning, hair model, ahoge, outfit pass,
  lashes/eyes, accessories, texture iteration, and camera-matrix validation.
- Explicitly not allowed in this pass:
  - runtime/game edits,
  - launching production code changes,
  - shipping a final VRM without the export gate,
  - adding unrelated costume pieces.

## 1) Full Toolset Execution Map

Follow this order once per session:

1. **Profile**
   - Confirm the file is loaded: `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`
   - Check model name/comment and note checkpoint name in VRoid.

2. **Body**
   - Keep stable height lock close to **170.2 cm / 170.4 cm target**.
   - Avoid repeated global scaling; only micro-tune limb and torso volumes for
     silhouette match.

3. **Face**
   - Face shape: jaw softness, eye spacing, eye position.
   - Irises/eyes: keep `alpecca_blue_iris_pair_texture_v2_2048x1024.png` as a
     source reference.
   - Inspect existing custom textures in:
     - `Face > Eyebrows > Edit Texture`
     - `Face > Eyeliner > Edit Texture`
     - `Face > Eyes > Irises > Edit Texture`
   - Keep lips and mouth in a neutral anime default unless source references
     explicitly require expression variants.

4. **Hairstyle**
   - Enter `Hairstyle > Edit Hairstyle` and visit:
     `Hairstyle Sets`, `Front`, `Side`, `Back`, `Overall Hair`,
     `Extensions`, `Ahoge`, `Extra`, `Base Hair`.
   - Preserve crown attachment and avoid detached front/temple mass.
   - Shape long-flow front/side/back silhouettes using the side profile pass.

5. **Ahoge**
   - `Ahoge > Custom > Edit Hairstyle`
   - Keep one single curved ahoge lock, left-front anchor.

6. **Outfit**
   - Open `Outfit` and inspect:
     - `Tops`/`Dress` silhouette and neckline.
     - `Bottoms` for leg length match.
     - `Socks` for stocking continuity.
     - `Shoes` for boot-read proportion.
   - Confirm no "yellow hoodie" fallback is reintroduced.
   - Do not force changes that conflict with the 170.2–170.4 cm body target.

7. **Accessories**
   - Place `alpecca_blue_x_hair_clip.svg` (or equivalent) on left side above earline.
   - Preserve blue lanyard / badge workflow for later passes; do not add random
     accessories.
   - Verify accessory paths do not import unrelated defaults (animal ears, tails,
     hats).

8. **Texture Editor / Appearance**
   - Keep palette clean: no orange/brown casts.
   - Avoid halo-like bloom; no hard transition bands in hair lower wash.
   - If a paint-pass is needed, export source textures once, edit at minimum 1024px,
     then re-import and save once per meaningful session batch.

9. **Preview camera**
   - Run the 15-view matrix below and the mirror checks before each save.
   - Use VRoid camera shortcuts:
     - `1`: front
     - `3`: front-right (~45°)
     - `4`: rotate left
     - `6`: rotate right
     - Mouse wheel: zoom out until head-to-torso ratio matches references.

## 1A) Operator control matrix (required)

- Use this concrete control map for consistent pass execution:
  - [ALPECCA_V11_PANEL_CONTROL_MATRIX.md](ALPECCA_V11_PANEL_CONTROL_MATRIX.md)
  - [ALPECCA_V11_GUI_OPERATION_RECIPE.md](ALPECCA_V11_GUI_OPERATION_RECIPE.md)

## 2) Passbook order (Mandatory)

- Run **ALPECCA_VROID_V11_PASSBOARD.md** from top to bottom.
- For each edit block, verify at least:
  - body/face lock,
  - hair lock (front+side+back),
  - ahoge single lock,
  - lower-lavender wash,
  - left clip.
- Do not jump between tools after an incomplete acceptance gate.

## 3) Matrix verification ladder

- Validate against:
  - `ALPECCA_V11_15_VIEW_CAMERA_MATRIX.md`
- The ladder is: Low, Eye, High each with 0/45/90/135/180 plus mirror confirmation.

## 4) Save / Continue rule

- Save only to the same file:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`
- Use the save cadence policy:
  - keep working with inspection passes
  - save in-place only when one meaningful batch is complete
  - do not create per-probe checkpoints.
- If any check fails, continue editing in-place.
- Use the QA checklist after each substantial camera-facing edit.

## 5) Completion handoff

Use the state-safe launch helper so gate-level state does not get overwritten by
the launcher during passbook work:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_vroid_v11_session.ps1 -StateNote "resume v11 full-toolset pass" -SkipStateTouch
```

When all hard gates pass:

```powershell
python scripts/update_v11_vroid_state.py --state base-gate-validated --notes "v11 gates passed"
``` 

If gates fail:

```powershell
python scripts/update_v11_vroid_state.py --state base-gate-rework --notes "v11 qa fail: ..."
```

## 6) In-session reference panel set

- `docs/ALPECCA_V11_REFERENCE_CONTACT_SHEET.jpg` (generated quick-reference strip)
- `data/alpecca_art_source/vrm_custom_assets/ac167033/1-Photo-1.jpg`
- `data/alpecca_art_source/vrm_custom_assets/ac167033/2-Photo-2.jpg`
- `data/alpecca_art_source/vrm_custom_assets/ac167033/3-Photo-3.jpg`
- `data/alpecca_art_source/vrm_custom_assets/ac167033/4-Photo-4.jpg`
- `data/alpecca_art_source/vrm_custom_assets/ac167033/5-Photo-5.jpg`
- `docs/ALPECCA_V11_PANEL_CONTROL_MATRIX.md`
- `docs/ALPECCA_V11_SESSION_CARD.md` (current stage status and next commands)

If the strip is missing or outdated:

```powershell
python scripts/build_v11_reference_sheet.py
```

## 7) QA reporting

- Open and fill:
  - `docs/ALPECCA_V11_GATE_RESULTS.md`
