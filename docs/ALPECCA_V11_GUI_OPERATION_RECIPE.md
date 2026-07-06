# Alpecca VRoid GUI Operation Recipe (v11)

Purpose: this is the practical operator-level recipe for running the VRoid base-model
experiment in a way that stays faithful to the requested objective:

- use full VRoid Studio controls (Face, Body, Hairstyle, Outfit, Accessories, Texture),
- match the 2D references as closely as possible,
- keep this as an **experimental model pass only** (do not replace runtime systems).

Use these steps in order in every run.

## A) Session bootstrap (mandatory)

1. Verify files are ready:

```powershell
python scripts/audit_v11_vroid_session.py --strict
```

2. Start the guided session helper:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_vroid_v11_session.ps1 -StateNote "operator recipe resumed"
```

3. Keep the helper output open and note the opened paths:
   - passbook + full-toolset docs,
   - reference photos folder,
   - checkpoint file.

4. Keep the operator control matrix nearby for the exact per-tab sequence:
   - `docs/ALPECCA_V11_PANEL_CONTROL_MATRIX.md`

## B) Core rule set (strict)

- Working file is **always in-place overwrite**:
  `data\alpecca_art_source\vrm_experiments\alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`.
- Do **not** save version-per-trial files for this stage.
- No app/runtime changes during VRoid passes.
- Maintain this priority: `base/body -> face -> hair/ahoge -> identity clip` before any outfit texture work.

## C) Official VRoid toolmap for this pass

Use full toolset tabs in this order while staying in the same session:

1. **Body**: confirm height/stance stay stable near `170.2cm`.
2. **Face**: keep face scale/jaw consistent; only minor shape and texture refinement.
3. **Hairstyle**
   - `Edit Hairstyle`
   - `Front`, `Side`, `Back`, `Ahoge`, `Overall Hair` groups
   - apply long-hair volume balancing and side/back depth correction.
4. **Hairstyle > Ahoge > Custom > Edit Hairstyle**
   - keep a **single curved** ahoge lock
   - keep anchor near left crown/front.
5. **Hairstyle texture/material controls**
   - Main Color target: pale white-silver base (`#FCECF6` target family)
   - Highlight target: cool lavender-blue (`#C7D5FF` target family)
   - apply lower-lower wash only by smooth, soft transition.
6. **Accessories**
   - import/use `alpecca_blue_x_hair_clip.svg`,
   - place strictly on **left-side hair mass** above earline.
7. **Texture Editor workflow (only where needed)**
   - export candidate hair texture,
   - add smooth upper-to-lower wash outside hard edges,
   - re-import and compare across 3/4 and side poses.

## D) 15-view gate execution

Use `docs/ALPECCA_V11_15_VIEW_CAMERA_MATRIX.md` and run all entries:

- Low: Front / 45 / Right / BackRight / Back
- Eye: Front / 45 / Right / BackRight / Back
- High: Front / 45 / Right / BackRight / Back
- Mirror side checks: left equivalents for 45 / 90 / 135

Gate requirement before saving:
- 15-view + mirror checks pass,
- ahoge remains one lock in all relevant poses,
- left clip never becomes right/mirrored in mirrored poses,
- no proportion spike in leg/waist width during side/back checks.

## E) Capture and evidence protocol (for evidence-backed progress)

For every major save event:

1. Open these reference targets simultaneously:
   - `docs/ALPECCA_V11_PASSBOARD.md`
   - `docs/ALPECCA_V11_VR_QA_CHECKLIST.md`
   - `data\alpecca_art_source\vrm_custom_assets\ac167033\1-Photo-1.jpg` (front)
   - `data\alpecca_art_source\vrm_custom_assets\ac167033\2-Photo-2.jpg` (45s)
   - `data\alpecca_art_source\vrm_custom_assets\ac167033\3-Photo-3.jpg` (side)
   - `data\alpecca_art_source\vrm_custom_assets\ac167033\4-Photo-4.jpg` (3/4 back)
   - `data\alpecca_art_source\vrm_custom_assets\ac167033\5-Photo-5.jpg` (back)

2. Save a short note in:
   - `docs/ALPECCA_V11_RESUME_LOG.md`
   - `data/alpecca_art_source/vrm_experiment_manifest.json` notes via:

```powershell
python scripts/update_v11_vroid_state.py --state gui-resume-in-progress --notes "front/side/back review completed, pending ..."
```

or on success:

```powershell
python scripts/update_v11_vroid_state.py --state base-gate-validated --notes "all v11 checks passed"
```

On any fail:

```powershell
python scripts/update_v11_vroid_state.py --state base-gate-rework --notes "failed at <view>: <specific issue>"
```

## F) Completion gate for stage transition

Do not advance to outfit detail exports until base identity passes this gate:

- adult height/limbs stable,
- single ahoge lock stable,
- left-side glossy clip stable,
- lower-hair lavender wash is smooth and localized,
- side/back profiles not collapsing into flat shell.

Then hand off to Stage 5 outfit custom-item pass or to export planning.
