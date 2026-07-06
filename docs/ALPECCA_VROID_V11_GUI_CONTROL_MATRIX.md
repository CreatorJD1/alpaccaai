# Alpecca VRoid v11 — GUI Control Matrix (Hands-on Pass)

Purpose: make the v11 pass reproducible in VRoid Studio without guessing.  
Working file: `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`

## 1) Launch + hard lock

1. Start VRoid Studio:
```powershell
"C:\Users\Jason\AppData\Local\Programs\VRoidStudio\2.14.0\VRoidStudio.exe"
```
2. Open target checkpoint:
- `File > Open`
- `data\alpecca_art_source\vrm_experiments\alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`
3. Save once before touching anything (safety checkpoint).
4. Keep the reference panel open:
- `data\alpecca_art_source\vrm_custom_assets\ac167033\1-Photo-1.jpg`
- `data\alpecca_art_source\vrm_custom_assets\ac167033\2-Photo-2.jpg`
- `data\alpecca_art_source\vrm_custom_assets\ac167033\4-Photo-4.jpg`

## 2) Exact control checklist (per pass)

### Base proportions (do not alter during v11)
- Body height: keep at the existing 170.2 baseline unless body scale visibly drifts.
- Face: keep original v11 face scale and jaw length.
- Outfit scale/placement: leave untouched in v11 (base-model pass only).

### Hair + ahoge + clip pass

Open `Hairstyle > Edit Hairstyle`.

#### A) Group visibility/shape
- Ensure active groups: `Front`, `Side`, `Back`, `Ahoge`.
- For each group run the same pass:
  - **Reduce flattening in side and back silhouettes.**
  - Raise back hair volume where side profile reads thin.
  - Keep crown/head attachment stable (do not create helmet-like cut-in).

#### B) Hair guide tuning
- `Ahoge > Custom > Edit Hairstyle`
  - Use freehand/procedural adjust only to form a **single** curved strand.
- Verify:
  - one single arc,
  - no twin tufts,
  - anchor remains near crown-left.

#### C) Hair material + gradient behavior
- Use material values as targets (relative tuning allowed):
  - Main: `#FCECF6` (or nearest match in your palette picker)
  - Highlight: `#C7D5FF` (or nearest cool lavender-blue)
- If possible, add a soft lower wash in texture editor:
  - Transition smooth, no hard edges.
  - No orange, no saturated purple.
  - Underside and lower fringes warm-white → pale-lavender tint only.
  - Keep upper hair slightly brighter than lower zones.

#### D) Blue clip placement
- Open or import clip asset:
  - `data\alpecca_art_source\vrm_custom_assets\alpecca_blue_x_hair_clip.svg`
- Place on **left side hair mass only**:
  - above earline,
  - not mirrored to right,
  - not centered on crown,
  - no halo geometry touching eyebrows/eye line.

## 3) Camera QA ladder (15-view strict)

Reference matrix:
- [ALPECCA_V11_15_VIEW_CAMERA_MATRIX.md](C:/Users/Jason/Documents/GitHub/alpaccaai/docs/ALPECCA_V11_15_VIEW_CAMERA_MATRIX.md)
- Use each set at the stated pitch (Low / Eye / High).

### Low pitch checks (5)
1. Front Low
2. Front-right Low (45°)
3. Right Low (90°)
4. Back-right Low (135°)
5. Back Low (180°)

### Eye pitch checks (5)
1. Front Eye
2. Front-right Eye (45°)
3. Right Eye (90°)
4. Back-right Eye (135°)
5. Back Eye (180°)

### High pitch checks (5)
1. Front High
2. Front-right High (45°)
3. Right High (90°)
4. Back-right High (135°)
5. Back High (180°)

### Mirror-side checks (3)
- Mirror-left equivalents for 45°, 90°, 135° in the same pitch family you are validating.
- This includes confirming clip and ahoge do not swap sides.

For each view:
- side silhouette must remain “alive” (not flat strip),
- ahoge stays attached to crown and singular,
- gradient reads on the lower mass only,
- clip remains on left side at all yaw offsets,
- overall body proportion remains adult-stable (no visible leg/waist spikes).

## 4) Acceptance gates for v11 save

Save only if all are true:

- [ ] Front, 45°, side, and 3/4 back read as one consistent body.
- [ ] Hair mass is long and has side/back volume.
- [ ] Ahoge is a clean single curved lock.
- [ ] Lower hair has visible lavender wash only by soft transition.
- [ ] Clip is present and only on left side.
- [ ] No new outfit, marker, or boot changes introduced in v11 (base-model purity held).
- [ ] All 15-view + mirror checks in matrix are passing.

## 5) Save rule

- In-place overwrite save target:
  - `data\alpecca_art_source\vrm_experiments\alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`
- Save only when all acceptance gates pass.
- If fail:
  - continue in the same checkpoint file (no new v11* version files until gate pass).

## 6) Post-pass handoff

After save:
- Update `data/alpecca_art_source/vrm_experiment_manifest.json`
  - `v11Iteration.state` from `gui-resume-in-progress` to `base-gate-validated` (or `base-gate-rework`).
  - bump `v11Iteration.notes` with the result.
