# Alpecca VRoid / VRM Experiment

## Goal

Build a VRM animated-model experiment that matches Alpecca's locked character
design closely enough to serve as a 3D reference source for House HQ, Stage 4
turnaround art, animation timing, and future 2D-in-3D sprite generation.

This VRM is an experimental reference rig, not a replacement for Alpecca's
approved 2D identity art.

## 2026-07-08 VCS Texture-Match Pass

Focus shifted back to model and texture fidelity. The VCS Materials panel's
**Match to design** action now applies a broader deterministic browser-side
material pass to the loaded VRM:

- silver-to-lavender hair gradient,
- warm ivory outfit tint for recognized top/outfit materials,
- white stocking cleanup for recognized stocking/sock/legwear materials,
- dark shorts/bottom tint for recognized shorts/pants materials,
- cream boots with pale-blue sole/side accents for recognized shoe/boot
  materials,
- glossy blue tint for recognized clip/bow/ribbon/accessory materials, plus
  blue lanyard/badge/strap materials when those material names exist.

This does not edit `.vroid` binaries directly. It is a reversible VCS preview
pass on the loaded VRM's material maps; use it to validate color and marker
direction before committing equivalent texture work inside VRoid Studio.

## 2026-07-08 Collar Removal And Accessory Routing

Jason rejected the blue collar/choker texture as a mismatch with Alpecca's
locked design. The active `alpecca_vroid_proxy_v0.vroid` body skin custom item
was edited in VRoid Studio: the top body-skin texture layer containing
`alpecca_choker_skin_overlay_v1.png` was deleted, the custom `Skin` item was
overwritten, and the `.vroid` project was saved in place.

The blue hair clip must not be forced through body skin, hoodie texture,
animal-ear, hat, or unrelated accessory presets. Treat it as its own
`Accessories` custom item/category, preferably imported from a BOOTH hairpin or
hair-ornament `.vroidcustomitem` once Jason supplies one. Use the local source
art only as the identity reference for that BOOTH/custom item:

- `data/alpecca_art_source/vrm_custom_assets/alpecca_blue_x_hair_clip.svg`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_blue_x_hair_clip_2048.png`

## 2026-07-08 Hoodie Front/Sleeve And Height Pass

The active source `alpecca_vroid_proxy_v0.vroid` was saved in place after a
focused regular-outfit and base-scale pass. Verified disk state after save:
`LastWriteTime=2026-07-08 21:39:11`, `Length=8927423`.

Captured improvements:

- Added `vroid_texture_layers/alpecca_hoodie_ivory_details_v6_front_sleeves.png`
  to restore missing front hoodie details: zipper/trim paths, pocket accents,
  blue pulls/tags, chest mark, sleeve modules, and hood-center dashes.
- Added the corrective top layer
  `vroid_texture_layers/alpecca_hoodie_ivory_details_v7_front_sleeve_corrections.png`
  after review found v6 too heavy. v7 covers the oversized rails and misplaced
  chest/sleeve marks, redraws slimmer pale-blue front trim, moves the chest mark
  higher/smaller, and rebuilds one clean black/blue tech patch per sleeve.
- Changed the top hoodie material shade color from cool `#CFD6F7` to warm
  `#E8DED7`. This keeps the pale-blue trim readable while making the hoodie
  body read as warm cream/ivory instead of blue-gray.
- Verified the active Body height was not at the design target (`167.6 cm`) and
  corrected it to `170.2 cm`, matching the 5 ft 7 in lock. The saved parameter
  value visible in VRoid was `Fem Height=-0.058`.

Parallel local workbench outputs:

- `data/alpecca_art_source/vrm_experiments/accessory_workbench/` now contains an
  open local OBJ/MTL/SVG/spec proxy for the small glossy blue left-side
  X/bone-bow clip. This is a VCS/Blender/Unity/Three.js workbench asset, not a
  `.vroidcustomitem`.
- `docs/ALPECCA_VROID_ACCESSORY_WORKBENCH.md` points to the accessory workbench
  and repeats the routing rule: use `Accessories > Import as Custom Item` when a
  compatible item exists; do not fake the clip with skin, hoodie texture,
  animal ears, hats, or unrelated presets.
- `data/alpecca_art_source/vrm_experiments/vroid_texture_layers/candidates/`
  contains three alternate hoodie overlay candidates for future manual import
  tests. They were not applied over the saved v7 pass.

Remaining blockers after this pass:

- The current HairHanege/simple-pin item is still only a temporary blue proxy;
  the final clip still needs a proper left-side custom accessory or post-export
  head/hair-bone attachment.
- Hair lower/underside lavender-blue gradient and side/back hair mass still need
  QA and likely direct hair-material work.
- Lanyard/ID, right-leg-only thigh strap, boot panel details, and final
  side/back outfit checks are still not export-ready.
- Adult 19-year-old read must still be verified from front, side, back, and
  three-quarter views before any new `.vrm` export.

## Design Lock

The VRM must preserve the same core identity rules as
`data/alpecca_art_source/ALPECCA_DESIGN_LOCK.md`:

- adult anime woman proportions,
- target standing height near `170.4 cm` / 5 ft 7 in for the House HQ scale,
- long white-silver hair with soft lavender-blue lower accents,
- one curved ahoge/cowlick,
- small blue glossy bone/bow hair clip on her left side,
- blue eyes and soft anime face,
- oversized warm ivory/cream hoodie-jacket with pale blue trim,
- white inner shirt,
- blue lanyard and Alpecca ID badge,
- black high-waist shorts,
- white full-length thigh-high stockings,
- black right-leg thigh strap,
- chunky cream/white boots with pale blue soles/details,
- no baked halo, floor shadow, blue orbs, animal ears, or invented accessories.

## Current VRoid Probe

Tool tested: `VRoid Studio 2.14.0`

Executable:

```text
C:\Users\Jason\AppData\Local\Programs\VRoidStudio\2.14.0\VRoidStudio.exe
```

Computer-control result:

- VRoid can be launched and controlled through the Windows automation layer.
- The editor window is targetable and screenshot-readable.
- The UI exposes very little accessibility text, so practical automation is
  mostly screenshot/coordinate driven.
- Parameter editing is possible, but should be done in small verified steps.

First proxy pass performed:

- Created a new feminine base model.
- Opened Body controls.
- Tuned body height to `170.2 cm`, matching the 5 ft 7 in standing lock closely.
- Selected a longer hairstyle preset.
- Set hair material to a pale white/lavender proxy color.
- Selected a hoodie whole-set preset for a first oversized-hoodie silhouette
  proxy.
- Replaced the first red outfit proxy with a pale warm hoodie, black shorts,
  cleaner white stocking proxy, and dark boot silhouette.
- Set irises to a visible Alpecca-blue proxy color through the VRoid iris
  material color field.
- Preserved the original v0 checkpoint before the outfit/eye pass:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v0_preserved_before_v1.vroid`
- Saved the current working `.vroid` checkpoint:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v0.vroid`
- Copied the refined current checkpoint to:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v1.vroid`
- Built a second checkpoint after deeper scroll/preset inspection of the Shoes
  category:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v2.vroid`
- Built a third checkpoint after correcting the hoodie away from yellow and
  toward Alpecca's white/cream design:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v3.vroid`
- Built a fourth checkpoint after comparing against the latest user-provided
  front/back/reference images and preserving the non-yellow hoodie state:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v4_reference_locked.vroid`
- Built a fifth checkpoint after a deeper Hairstyle category sweep found the
  proper VRoid `Ahoge` category and selected the closest single curved ahoge
  preset:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v5_ahoge.vroid`
- Built a sixth checkpoint after correcting the VRoid hair highlight material
  from orange to pale lavender-blue:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v6_hair_highlight.vroid`
- Built a seventh checkpoint after replacing the asymmetric/laced stocking
  preset with a cleaner white full-leg stocking proxy:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v7_stocking_proxy.vroid`
- Built an eighth checkpoint during the base-model-first pass after importing
  Alpecca's layered blue iris pair texture as a new iris texture layer:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v8_base_iris.vroid`
- Built a ninth checkpoint after replacing the first iris layer with a closer
  v2 oval Alpecca iris texture based on the latest eye reference:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v9_base_face_iris_v2.vroid`
- Built a tenth checkpoint after importing the latest pale eyebrow reference as
  a custom `Eyebrows` item and the darker winged lash reference as a custom
  `Eyeliner` item:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v10_base_brows_eyeliner.vroid`
- Staged transparent base-face reference cutouts from the latest eyebrow and
  eyelash sheets:
  `data/alpecca_art_source/vrm_custom_assets/alpecca_eyebrow_pair_reference_v2_2048x1024.png`,
  `data/alpecca_art_source/vrm_custom_assets/alpecca_lash_pair_reference_v2_2048x1024.png`,
  and
  `data/alpecca_art_source/vrm_custom_assets/alpecca_lash_pair_with_browline_reference_v2_2048x1024.png`.
  These are not imported yet; the next VRoid step is to inspect the Eyebrows,
  Eyelashes, Eyeliner, and Eyelids texture templates before applying them.

## Current v1 Status

`alpecca_vroid_proxy_v1.vroid` is the first blue-eye / clean-stocking proxy.

## Current v2 Status

`alpecca_vroid_proxy_v2.vroid` is the footwear-improved checkpoint.

## Current v3 Status

`alpecca_vroid_proxy_v3.vroid` is the first corrected white-hoodie checkpoint.

## Current v4 Status

`alpecca_vroid_proxy_v4_reference_locked.vroid` is the reference-lock
checkpoint before the ahoge and hair-highlight corrections.

Export status: **not ready for `.vrm` export**. The v4 model is useful as a
VRoid control/parameter probe, but it is not design-complete enough to become a
reference asset yet.

## Current v5 Status

`alpecca_vroid_proxy_v5_ahoge.vroid` is the ahoge checkpoint before the
hair-highlight correction.

Captured improvement:

- Added a single curved ahoge from VRoid's dedicated `Hairstyle > Ahoge`
  category. The selected preset is closer to the front-reference hook shape than
  the tight loop and avoids the rejected twin-tuft look.

Important VRoid workflow finding:

- The hair stack has separate categories for `Hairstyle Sets`, `Front`, `Back`,
  `Overall Hair`, `Extensions`, `Side`, `Ahoge`, `Extra`, and `Base Hair`.
  The correct ahoge was not in `Extra`; it was in the dedicated `Ahoge`
  category.
- `Ahoge > Custom > Edit Hairstyle` opens VRoid's hair editor with Freehand and
  Procedural Hair Guides. This is the correct route for refining the curl later
  instead of compromising with unrelated presets.

## Current v6 Status

`alpecca_vroid_proxy_v6_hair_highlight.vroid` is the hair-highlight
correction checkpoint before the stocking proxy update.

Captured improvement:

- Corrected the Hairstyle `Highlight Color` from the wrong orange
  `#DB8A3B` to pale lavender-blue `#C7D5FF`, keeping the main hair color at
  `#FCECF6`. This better supports Alpecca's white-silver hair with cool
  lavender-blue accents without changing her outfit or exporting a VRM.

Export status: **not ready for `.vrm` export**. The v6 model is still a proxy:
it needs custom texture/import work for the open hoodie-jacket, trim, badge,
lanyard, thigh strap, hair clip, and boots.

## Current v7 Status

`alpecca_vroid_proxy_v7_stocking_proxy.vroid` is the best current VRoid proxy.

Captured improvement:

- Replaced the selected asymmetric/laced stocking preset with a cleaner
  full-leg white stocking proxy. This improves Alpecca's white-stocking read
  under the black shorts, but it still has extra banding on both legs.

Remaining stocking work:

- The final design should use white full-length stockings with a black strap on
  the right leg only. The current v7 preset is closer than v6 but still needs a
  custom texture pass to remove unwanted banding and place the right-thigh strap
  deliberately.

## Current v8 Status

`alpecca_vroid_proxy_v8_base_iris.vroid` is the first base-model-focused
checkpoint.

Captured improvement:

- Imported the Alpecca layered blue iris pair texture into the VRoid iris
  Texture Editor as a new layer. This gives her eyes a closer Alpecca read:
  deep blue iris base, cyan lower glow, dark pupil, upper depth, and bright
  highlights.

Export status: **not ready for `.vrm` export**. The v8 model improves the eyes,
but the base model is still not locked because hair shape/volume, hair gradient,
clip placement, and body/face silhouette still need direct work.

## Current v9 Status

`alpecca_vroid_proxy_v9_base_face_iris_v2.vroid` is the current base-face
checkpoint.

Captured improvement:

- Imported `alpecca_blue_iris_pair_texture_v2_2048x1024.png` as a new top
  iris layer in `Face > Irises > Edit Texture`.
- The v2 iris better matches the latest Alpecca eye reference: oval blue lens,
  vertical dark pupil, darker upper glass, bright blue center, cyan lower arc,
  warm lower reflection, and cleaner highlight placement.
- Added staged source assets for eyebrow, eyelash, eyelid/crease, and mouth
  expression work, but did not import them yet because their VRoid texture
  templates need separate inspection.

Export status: **not ready for `.vrm` export**. The v9 checkpoint improves the
eye texture only; face proportions, lashes, mouth, hair mass, hair gradient, and
clip placement remain open base-model tasks.

## Current v10 Status

`alpecca_vroid_proxy_v10_base_brows_eyeliner.vroid` is the current base-face
checkpoint.

## VRoid v11 Full-Toolset Run Mode

This is the active workflow for the next manual v11 pass:

1. Validate all paths/assets first (recommended):
```powershell
python scripts/audit_v11_vroid_session.py
```

2. Open and run the v11 session helper:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_vroid_v11_session.ps1 -StateNote "resume v11 full toolset pass"
```

For a strict operator-level action list and evidence policy, open:

- [ALPECCA_V11_GUI_OPERATION_RECIPE](ALPECCA_V11_GUI_OPERATION_RECIPE.md)

3. During edits, use `docs/ALPECCA_V11_PASSBOARD.md` as the execution checklist.

- Working file: `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`.

4. Work in-place on
   `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`
   using `docs/ALPECCA_V11_PASSBOARD.md` as the execution checklist.
5. Restrict edits to base-model, face, hair/ahoge, and custom identity accessories.
6. Keep the branch in probe mode: no `.vrm` export, no runtime pipeline edits.
7. Save only meaningful milestones and log notes through
   `scripts/update_v11_vroid_state.py`.

Scope boundary:

- **Allowed:** proportions, face tuning, hair mass/gradient/ahoge, clip placement,
  stock/hoodie/footwear reference checks.
- **Not allowed:** replacing the existing House HQ gameplay runtime, AI systems,
  or existing 2D pipeline architecture from this VRoid pass.

Manifest contract:

- The active checkpoint and latest progress live at:
  `data/alpecca_art_source/vrm_experiment_manifest.json`.
- Use these commands:
  - `python scripts/update_v11_vroid_state.py --state gui-resume-in-progress --notes "..."`
  - `python scripts/update_v11_vroid_state.py --state base-gate-validated --notes "..."`

## Current v11 Planned

`alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid` is the next planned checkpoint.

Planned scope for this pass:

- Keep body/face/eyes as-is (no base-face resets).
- Open `Hairstyle > Edit Hairstyle` with front, side, back, and Ahoge groups visible.
- Restore long hair silhouette where it reads too flat on side views.
- Tune group-based hair material for strong white-silver top and lavender-blue lower wash.
- Align ahoge curl with latest front/side references at yawed camera checks.
- Place and scale the blue bone/bow clip only on her left side; validate at 45° and 90° yaw.
- Save only once the above is complete as the first meaningful v11 checkpoint.

Reference for this pass:
- `data/alpecca_art_source/vrm_custom_assets/ac167033/1-Photo-1.jpg`
- `data/alpecca_art_source/vrm_custom_assets/ac167033/2-Photo-2.jpg`
- `data/alpecca_art_source/vrm_custom_assets/ac167033/4-Photo-4.jpg`

Execution passboard:
- [ALPECCA_VROID_V11_PASSBOARD.md](ALPECCA_VROID_V11_PASSBOARD.md)
- [ALPECCA_V11_FULL_TOOLSET_MASTER.md](ALPECCA_V11_FULL_TOOLSET_MASTER.md)
- [ALPECCA_V11_VR_QA_CHECKLIST.md](ALPECCA_V11_VR_QA_CHECKLIST.md)
- [ALPECCA_VROID_V11_RESUME_LOG.md](ALPECCA_VROID_V11_RESUME_LOG.md)
- [ALPECCA_VROID_V11_GUI_CONTROL_MATRIX.md](ALPECCA_VROID_V11_GUI_CONTROL_MATRIX.md)


State tracking:
- Manifest entry: `data/alpecca_art_source/vrm_experiment_manifest.json` 
- Quick state update command (after GUI pass):
  ```powershell
  python scripts/update_v11_vroid_state.py --state base-gate-validated --notes "side/front/3-4 checks passed"
  ``` 
Execution checklist:

- Load `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid` as the working file.
- Open `Hairstyle`.
- Open `Edit Hairstyle`.
- Validate each group has active visibility: `Front`, `Side`, `Back`, `Ahoge`.
- If the side silhouette collapses, pull `Back` and `Side` length and lift parameters inward while preserving head shape.
- In hair material, enforce warm white crown (`#FCECF6`), then lower-lavender wash through texture-based editing.
- Apply a soft lower strip wash only; keep the upper two-thirds bright and brightened.
- Add the clip only on left side front-frame edge, not centered and not behind forehead.
- Final gate before save:
  - Side and quarter view preserve long flow with volume.
  - Ahoge stays single curved and non-paired.
  - Lower wash reads lavender-blue without hard color blocks.
  - Left-clip sits above the ear line.
- Save only after this pass, and keep the same saved file name as the v11 checkpoint.

## v12 User-Adjusted Candidate Branch

`alpecca_vroid_proxy_v12_user_adjusted_from_v0.vroid` preserves the currently
open `v0` project after the user reported manual adjustments.

Decision record:

- `docs/ALPECCA_VROID_BRANCH_DECISION.md`
- `docs/vroid_branch_compare/alpecca_vroid_v11_v12_branch_compare.jpg`

Why this exists:

- VRoid was live-inspected after the user adjustment note.
- The open editor title showed `alpecca_vroid_proxy_v0.vroid`, not the active
  v11 checkpoint.
- To avoid losing or overwriting user edits, `v0` was copied into this separate
  candidate checkpoint instead of being merged blindly into v11.

Use this branch only if the user explicitly wants the visible v0 model to become
the next working base. Otherwise, keep the main experiment on v11:

- main rework checkpoint:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`
- preserved user-adjusted candidate:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v12_user_adjusted_from_v0.vroid`

Branch decision rule:

- If v12 has better body/face/hair foundation, promote it deliberately and then
  reapply the missing v11 identity work.
- If v11 remains the better identity base, reopen v11 and continue the lanyard,
  open jacket, hair gradient, left clip, strap, and boot rework there.
- Do not validate v11 gates from v0/v12 screenshots.

Current decision: v11 remains the main rework branch; v12 stays preserved as a
fallback/body comparison reference.

Captured improvement:

- Saved the latest transparent pale brow cutout as a custom `Eyebrows` item.
  This moves the face away from generic dark VRoid brows and closer to the
  thin taupe brow shape in the Alpecca references.
- Imported the darker v2 lash reference into `Face > Eyeliner > Edit Texture`
  as a custom `Eyeliner` item. This category matched the visible upper-lash
  UV islands better than the `Eyelashes` texture category.
- Inspected `Face > Eyelashes > Edit Texture`, but did not keep a saved
  eyelash edit because the template did not match the simple two-island lash
  source and would risk creating a junk custom item.

Export status: **not ready for `.vrm` export**. The v10 checkpoint is a better
base-face lock candidate than v9, but the model still needs face close-up QA,
mouth/expression tuning, hair mass, hair gradient, ahoge refinement, and the
blue bone/bow hair clip before outfit work resumes.

## Base-Face Source Notes

The latest face references clarify the base-model direction:

- Brows should be thin, pale taupe, and softly arced. They should not read as
  thick dark brows.
- Upper lashes should be visibly darker than the brows, with outward wing tips
  and layered anime lash mass.
- The thin upper crease/browline should be treated separately if VRoid's
  `Eyelids` or `Eyeliner` templates allow it.
- The current iris texture is close enough to keep while testing the brow/lash
  templates; do not keep replacing the iris unless the new asset is clearly
  better.

## Character Sheet Mismatch Audit

Current state after front/side viewport inspection: **not close enough to the
Alpecca character sheet**. Treat v7 as a technical control proxy only, not an
acceptable likeness.

Latest live viewport check:

- VRoid is currently open as `alpecca_vroid_proxy_v0.vroid`, with later proxy
  edits/checkpoints documented separately.
- The visible model still reads as a generic closed-hoodie proxy: weak hair
  mass, no blue bone/bow clip, no lanyard or badge, no open jacket silhouette,
  and no true Alpecca boot/stocking finish.
- This confirms the next pass must focus on custom texture/accessory work and
  stronger silhouette authoring, not VRM export.

Major mismatch blockers:

- Overall read is still a generic VRoid hoodie model, not Alpecca.
- Hoodie is a closed pullover; reference requires an open warm-ivory
  hoodie-jacket over a white shirt.
- Hair front/silhouette lacks Alpecca's full white-silver mass, long side
  strands, and lavender-blue lower gradient.
- Blue glossy bone/bow hair clip is absent from the VRoid model. The latest
  user-provided close-up reference shows a rounded bone/bow silhouette, not a
  generic X.
- Blue lanyard and Alpecca ID badge are absent.
- Stockings are closer to white but still have unwanted extra bands; final needs
  clean white full-length stockings plus right-leg-only black thigh strap.
- Shoes read closer to high-top sneakers than chunky cream/white boots with
  pale-blue paneling.
- Outfit texture lacks blue zipper pulls, sleeve modules, side pocket details,
  and back Alpecca power mark.

Latest rendering reference notes:

- Hair clip: glossy medium-blue bone/bow piece, rounded lobes, a small vertical
  center/right petal, placed on Alpecca's left hair mass near the front/side
  transition.
- Hair clip close-up references:
  `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\93a77eaa-f33c-4875-be38-cf7393d79b74\1-Photo-1.jpg`
  and
  `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\93a77eaa-f33c-4875-be38-cf7393d79b74\2-Photo-2.jpg`.
- Hair: long white-silver layered hair with soft lavender-blue lower/underside
  tint, stronger side strands, and curved ahoge. Avoid short/bob/ponytail
  silhouettes.
- 3D reference render: open warm-ivory jacket, blue trim, lanyard/badge, sleeve
  modules, chunky boots, full white stockings, right-leg strap, and back hoodie
  details are all visible across front/side/back views.
- 3D render reference:
  `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\93a77eaa-f33c-4875-be38-cf7393d79b74\3-Photo-3.jpg`.
  The glowing ring in this render is a scene/light reference only; do not bake
  it into the VRoid model or sprite source unless the user explicitly approves
  it later.

Revised priority:

1. Lock the base model first: adult body proportions, soft face, layered blue
   eyes, long white-silver hair mass, lavender-blue lower gradient, ahoge, and
   correct left-side glossy blue bone/bow hair clip placement.
2. Fix outfit silhouette second: open jacket shape, boots, and full stocking
   read.
3. Add outfit identity markers third: lanyard, badge, sleeve modules, back
   power mark, trim, zipper pulls, and right-leg strap.
4. Only after the base model, outfit silhouette, and markers read as Alpecca should the VRM be
   exported for Blender/Three.js reference testing.

Captured improvements:

- feminine adult base at `170.2 cm`,
- long pale white-lavender hair proxy,
- blue iris proxy,
- white/cream hoodie silhouette with pale cool-blue shadow accents,
- black shorts,
- white stocking proxy,
- white high-top / chunky-sole footwear proxy with boosted sole parameters.
- 2026-07-08 update on active `alpecca_vroid_proxy_v0.vroid`: boots were made
  chunkier in VRoid Studio and saved in place. Shoe parameters now include
  `Overall Volume` 33.436, `Boot Volume` 57.753, `Toebox Width` 31.322,
  `Toebox Volume` 44.361, `Toebox Thickness` 28.855, and `Foot Thickness`
  22.159. The cream/blue texture already reads closer than the earlier dark
  boot proxy; final polish is now an exact custom boot texture/model pass, not
  basic silhouette repair.

VRoid toolset notes from this pass:

- Face > Irises exposes a material color field and can set Alpecca-blue eyes.
- Outfit > Socks has scrollable presets; the cleaner white stocking preset is a
  better baseline than the decorative garter proxy.
- Outfit > Shoes has deeper scrollable presets; a white high-top preset with
  raised sole parameters currently reads closer to Alpecca's cream footwear
  color than the earlier dark boot proxy.
- Outfit > Shoes > Custom opens the Texture Editor for the selected shoe item.
  The selected `Chunky Sole Boots` texture is editable, but the dark boot is
  baked into the source texture, so exact cream/blue boots should be handled as
  a deliberate custom texture pass instead of blind flood-fill painting.
- Outfit > Tops has a scrollable hoodie library. The initial yellow hoodie was
  rejected because it did not match Alpecca's white/cream hoodie. The v3 proxy
  uses the whiter hoodie preset from deeper in the Tops list.
- Latest reference lock confirms the production target is an open warm-ivory
  hoodie-jacket over a white shirt, not a closed pullover hoodie. VRoid's built
  in Tops/Dresses/Bottoms preset scan did not expose a safe open hoodie-jacket
  silhouette that preserved her shorts and stockings, so v4 keeps the best
  non-yellow closed hoodie proxy until custom clothing work is done.
- Accurate outfit details require texture drawing/imports, not only presets:
  blue trim, zipper pulls, sleeve modules, lanyard/ID badge, thigh strap, back
  power symbol, and cream/blue boot panels should be authored as custom
  textures or imported custom items.

## Latest Reference Requirements

The latest supplied images strengthen the design lock:

- long white-silver hair with lavender-blue lower gradient,
- curved ahoge/cowlick at the crown,
- blue glossy bone/bow hair clip on Alpecca's left side,
- large blue eyes with soft expression,
- open warm-ivory hoodie-jacket, blue trim, blue zipper pulls, and sleeve
  pocket modules,
- white inner shirt,
- blue lanyard with Alpecca ID badge,
- black high-waist shorts,
- white full-length stockings,
- black strap on the right thigh,
- chunky cream/white boots with pale-blue soles/details,
- back jacket power symbol / Alpecca mark when feasible,
- no animal ears, no random costume parts, no baked halo, no unrelated
  accessories.

Remaining design gaps:

- no approved blue glossy bone/bow hair clip yet. On 2026-07-08 the active
  Accessories tab was checked and confirmed to have the correct `Import as
  Custom Item` route, while `Create New` only exposed built-in shapes such as
  hats, bows, glasses, and similar presets that should not be used as a fake
  clip. Free BOOTH candidates were found, including `[FREE] Butterfly Hairclip
  VRoid Accessory`, but the actual `.vroidcustomitem` downloads redirected to
  BOOTH sign-in, so the clip is still blocked until Jason provides a signed-in
  download or local `.vroidcustomitem`. Keep this as a separate BOOTH/imported
  `Accessories` custom item, not as a body-skin or hoodie texture layer. A
  source SVG exists for reference:
  `data/alpecca_art_source/vrm_custom_assets/alpecca_blue_x_hair_clip.svg`,
- 2026-07-08 hair-pin import update: Jason provided
  `Star_shape_hair_pin.rar` and `Simple_hair_pin_pink.rar`. Metadata inspection
  showed both are `TransferableGroupType.N00.Level1.HairHanege`, which VRoid
  exposes as `Hairstyle > Extra`, not the modern Accessories category. The star
  pin failed to import in VRoid Studio 2.14.0 as incompatible. The simple pin
  loaded as an Extra custom item, was recolored from pink to Alpecca blue at the
  material level, moved off the forehead toward the side hair, and the source
  was saved. Treat it as a temporary BOOTH-based clip proxy; the final target
  remains a small glossy blue left-side bone/bow clip,
- ahoge exists as a close preset, but still needs optional custom hair-guide
  refinement to match the exact front-reference curl,
- hoodie is no longer yellow, but still needs exact ivory fabric, pale-blue trim,
  and Alpecca-specific seam/details through a custom texture pass,
- no lanyard or Alpecca ID badge in VRoid yet. A source SVG now exists for
  texture/custom-item work:
  `data/alpecca_art_source/vrm_custom_assets/alpecca_lanyard_badge_source.svg`,
- right-leg black thigh strap is not separately modeled after switching to the
  cleaner white stocking proxy,
- footwear now has better cream/white color read and a chunkier saved silhouette,
  but still needs a true boot-like custom texture/model pass with exact
  pale-blue panels/details,
- no `.vrm` export has been created yet.

## Base Model Focus

The user has now clarified that the next work should focus on Alpecca's base
model before outfit completion. Treat the outfit as deferred until this gate
passes.

Latest base-model references:

- `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\b91e812f-bff3-400b-b522-e65a8b450ee5\1-Photo-1.jpg`
- `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\b91e812f-bff3-400b-b522-e65a8b450ee5\2-Photo-2.jpg`
- `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\b91e812f-bff3-400b-b522-e65a8b450ee5\3-Photo-3.jpg`
- `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\b91e812f-bff3-400b-b522-e65a8b450ee5\4-Photo-4.jpg`
- `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\b91e812f-bff3-400b-b522-e65a8b450ee5\5-Photo-5.jpg`

Base-model gate:

- front, 3/4, side, 3/4 back, and back views must read as the same slender
  adult Alpecca body,
- hair mass must be long, layered, and visible around the head, shoulders, and
  back without relying on the outfit,
- lower and underside hair should carry a soft lavender-blue tint,
- ahoge should be a single curved strand, not twin tufts or animal-ear shapes,
- eyes should use layered blue iris depth, not a flat color swatch,
- the glossy blue bone/bow clip must sit on her left hair mass above the ear,
- outfit detailing stays deferred until these base checks pass.

New base-model source assets:

- `data/alpecca_art_source/vrm_custom_assets/alpecca_base_model_lock.json`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_blue_iris_layered.svg`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_blue_iris_layered_2048.png`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_blue_iris_pair_texture_2048x1024.png`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_blue_iris_reference_v2.svg`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_blue_iris_reference_v2_2048.png`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_blue_iris_pair_texture_v2_2048x1024.png`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_lash_pair_reference.svg`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_lash_pair_reference_2048x1024.png`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_mouth_open_reference.svg`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_mouth_open_reference_1024.png`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_mouth_soft_smile_reference.svg`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_mouth_soft_smile_reference_1024x512.png`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_hair_gradient_reference.svg`
- `data/alpecca_art_source/vrm_custom_assets/alpecca_hair_gradient_reference_2048.png`

Base-model v8 checkpoint:

- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v8_base_iris.vroid`
- Change made in VRoid: imported
  `data/alpecca_art_source/vrm_custom_assets/alpecca_blue_iris_pair_texture_2048x1024.png`
  as a new layer in `Face > Irises > Edit Texture`.
- Result: eyes now use layered blue iris art with darker upper depth, cyan lower
  glow, pupil, and highlights instead of only a flat colorized preset.
- Still not base-model locked: hair mass, hair gradient, ahoge refinement, body
  side silhouette, and left-side hair clip placement remain pending.

Base-model v9 checkpoint:

- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v9_base_face_iris_v2.vroid`
- Change made in VRoid: imported
  `data/alpecca_art_source/vrm_custom_assets/alpecca_blue_iris_pair_texture_v2_2048x1024.png`
  as a new top layer in `Face > Irises > Edit Texture`.
- Result: eyes are closer to Alpecca's latest face reference than v8.
- Still pending: inspect and tune `Face > Eyelashes` and `Face > Mouth` templates
  before importing the staged lash/mouth assets.

## Export Gate

Do not export or promote the VRoid experiment until these design blockers are
resolved:

- true open hoodie-jacket silhouette or custom texture/model workaround,
- custom-drawn or imported blue trim/zipper pulls/sleeve modules,
- custom-drawn or imported blue lanyard and Alpecca ID badge,
- blue glossy bone/bow hair clip on her left side, routed first as a BOOTH/imported
  `Accessories` custom item; use a hair-guide workaround only if no suitable
  hairpin custom item exists,
- verify/refine the v5 single curved ahoge/cowlick, not twin tufts or
  animal-ear silhouettes,
- custom-drawn or imported right-leg black thigh strap,
- custom-drawn cream/white boot design with pale-blue soles/details.

Rejected built-in VRoid options from the design-fidelity pass:

- animal ears, tails, hats, and unrelated accessories,
- side hair puffs, twin antenna strands, and twin top tufts,
- plain short-sleeve shirt replacing the hoodie-jacket.

## Save Cadence

Do not create a new `.vroid` checkpoint for every small probe. Use inspection-only
passes while searching categories or testing candidates. Save/checkpoint roughly
every 15 minutes, or sooner only when a meaningful design batch is ready.

## Official VRoid Workflow Notes

Use the official VRoid help material as the operating guide for the next pass:

- The beginner workflow confirms that a model is built from Face, Hairstyle,
  Body, Outfit, and Accessories, and that every item can be adjusted by shape,
  color, and design rather than accepted as-is.
- VRoid custom items can be created by editing presets or by starting from a
  category template. Edited outfits, face parts, hairstyles, and body textures
  can be saved as custom items; accessories can be imported/exported as custom
  items in modern VRoid Studio versions.
- The Texture Editor is the correct place to draw/import Alpecca-specific
  clothing details. It supports drawing on item textures, direct model painting,
  UV editing, layers, brush/eraser/bucket tools, fill tolerance, opacity, and
  import/export-oriented texture work.
- Hairstyle customization supports both freehand and procedural hair guides,
  material edits, texture edits, hair-group mirroring, and hair bounce. This is
  the correct path for refining the ahoge, long hair mass, side strands, and
  possible glossy blue bone/bow clip workaround if no accessory import is
  available.
- VRoid hair materials control how hair texture and light reflection read.
  Materials expose Main, Highlight, and Outline colors; the current proxy uses
  `#FCECF6` Main Color and `#C7D5FF` Highlight Color on the visible hair
  material. This is a proxy swatch pass, not the final Alpecca gradient.
- The official gradient workflow recommends painting a gradient on a separate
  layer/set mode, or exporting a white-base hair texture, editing it in painting
  software, and importing it back into VRoid. Use that route for Alpecca's true
  white-silver hair with lavender-blue lower gradient.
- Hair modeling should separate overlapping strand groups and follow adjusted
  hair guides. Use this for the ahoge curl, front strand framing, long back hair
  volume, and side silhouette so the VRM reference does not collapse into a flat
  single hair shell.
- VRoid camera inspection should use the official shortcuts when automation
  cannot right-drag cleanly: `1` front, `3` front-right, `4` rotate left,
  `6` rotate right, plus zoom controls. This is now the preferred way to inspect
  Alpecca's side and back silhouette through Windows automation.
- `.vroid` remains the editable source format. `.vrm` is an exported 3D model
  format and should not be treated as the editable master.

## Hair Texture / Gradient Plan

Current state:

- Main/Back/Ahoge visible material swatches are aligned to Alpecca's palette:
  pale main hair `#FCECF6`, cool lavender-blue highlight `#C7D5FF`.
- This creates a better cool read than the old orange highlight, but it does not
  yet create the full reference gradient.
- Viewport inspection was rotated and zoomed out with VRoid camera shortcuts,
  confirming the current side/three-quarter read still needs stronger long-hair
  volume, cleaner stocking texture, and custom outfit details.

Next hair pass:

1. Open `Hairstyle > Edit Hairstyle`.
2. Select the active long back hair group and front/side hair groups.
3. Confirm each relevant group uses the Alpecca hair material, or duplicate a
   new material for groups that need the lavender-blue lower gradient.
4. Export the base hair texture with a white/pale base.
5. Paint/import a vertical gradient texture:
   - upper hair: white-silver / pale warm white,
   - lower hair and underside: soft lavender-blue,
   - preserve soft anime strand highlights,
   - avoid orange, brown, saturated purple, or harsh blue bands.
6. Reimport the texture in VRoid and save it as a custom hairstyle item.
7. Only then consider this hair color work ready for VRM reference export.

## Recommended Pipeline

1. Build a stable VRoid base model.
2. Author Alpecca-specific custom items/textures inside VRoid:
   - hoodie/jacket surface with warm ivory fabric and pale-blue trim,
   - sleeve modules, zipper pulls, pocket details, and back power symbol,
   - blue lanyard and ID badge using
     `data/alpecca_art_source/vrm_custom_assets/alpecca_lanyard_badge_source.svg`
     as source art,
   - right thigh strap,
   - cream/white boots with pale-blue panels/soles,
   - hair clip via BOOTH/imported accessory custom item, or last-resort custom
     hair workaround, using
     `data/alpecca_art_source/vrm_custom_assets/alpecca_blue_x_hair_clip.svg`
     as source art.
3. Save the `.vroid` experiment under an explicit Alpecca checkpoint name.
4. Export `.vrm` only after the export gate is clear.
5. Import the VRM into Blender or a Three.js preview rig.
6. Render controlled reference passes:
   - 16-sector idle turnaround,
   - 16-sector walk-cycle body mechanics,
   - front/side/back pose references,
   - mouth/eye expression references,
   - hoodie/stocking/boot silhouette references.
7. Use renders as reference guides for Stage 4 source-art generation and QA.
8. Do not ship the VRM as production Alpecca unless the user approves that
   direction separately.

## Next VRoid Passes

1. Face and eyes:
   - soften default face,
   - set blue eyes,
   - tune eye size and eye position to match the design sheet.

2. Hair:
   - add or approximate ahoge/cowlick,
   - lengthen hair mass if needed,
   - add lavender-blue lower gradient if VRoid material editing allows it,
   - add the blue glossy bone/bow hair clip if an accessory workaround is available.

3. Outfit:
   - replace temporary T-shirt with hoodie/jacket silhouette,
   - recolor to warm ivory/cream with pale blue trim,
   - preserve black high-waist shorts,
   - add white thigh-high stockings,
   - add black right-leg thigh strap,
   - choose chunky cream/white boots with pale blue accents.

4. Export/reference:
   - save the working `.vroid`,
   - export `.vrm` only after the export gate is cleared,
   - build a small render/animation test scene,
   - render first 16-sector turnaround contact sheet.

## Acceptance Criteria

The VRM experiment is useful when it can produce references where:

- Alpecca keeps a stable adult height and slim adult leg silhouette,
- side views show real body depth instead of an ultra-thin billboard,
- hair mass rotates believably around the head and shoulders,
- white stockings, black shorts, hoodie, boots, and hair clip remain visible,
- the model can be animated for walk/talk/idle reference without changing
  proportions.











