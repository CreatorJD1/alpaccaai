# Alpecca VRoid Claude Code Passdown

Updated: 2026-07-06

## Purpose

This passdown is for Claude Code to continue the VRoid Studio experiment for Alpecca.

The goal is to build an experimental 3D/VRM version of Alpecca that stays as close as possible to her 2D reference art. This is not replacing the current Alpecca app, House HQ, 2D sprite system, voice system, or animation pipeline. It is a separate experiment for a possible 3D form Alpecca can use later.

## Current Authoritative Files

Repo root:

`C:\Users\Jason\Documents\GitHub\alpaccaai`

Active VRoid file:

`C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\alpecca_vroid_proxy_v0.vroid`

Latest verified save:

- `LastWriteTime=2026-07-05 09:07:17`
- `Length=9472191`

Experiment manifest:

`C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiment_manifest.json`

Do not look for the manifest under `vrm_experiments`; the correct path is one folder higher.

Recent texture files:

- `C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\vroid_imports\Hoodie_byDAMON\alpecca_recolored_layers\alpecca_girlHoodie_show_recolor_v5_white_shirt.png`
- `C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\vroid_texture_layers\alpecca_inside_plain_white_2048.png`
- `C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\vroid_texture_layers\alpecca_hair_blue_tips_only_1024x2048.png`
- `C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\vroid_texture_layers\alpecca_hair_clean_blue_tip_gradient_1024x2048.png`
- `C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\vroid_texture_layers\alpecca_hair_light_blue_tip_gradient_1024x2048.png`

Imported hoodie asset:

`C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\vroid_imports\Hoodie_byDAMON\girlHoodie.vroidcustomitem`

## First Test VRM Export

Jason explicitly requested the first test `.vrm` export on 2026-07-06. This supersedes the earlier "do not export yet" caution for this one test artifact only.

Canonical export:

`C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\exports\alpecca_vroid_proxy_v0_first_test_20260706.vrm`

Claude Code handoff copy:

`C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\handoff_to_claude\alpecca_vroid_proxy_v0_first_test_20260706.vrm`

Companion tool drop copy:

`C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\companion_tool_drop\alpecca_vroid_proxy_v0_first_test_20260706.vrm`

Export details:

- Exported from current `alpecca_vroid_proxy_v0.vroid`.
- Export format: VRM 1.0.
- Export settings: no polygon/material/bone reduction for this first test.
- VRoid-reported export stats: 56,803 polygons, 20 materials, 121 bones.
- Metadata name: `Alpecca VRoid Prototype Test Export`.
- Metadata version: `first-test-2026-07-06`.
- Metadata creator: `Jason / CreatorJD1`.
- Permissions were set conservatively for a test file: creator-only use, personal non-commercial, redistribution prohibited, alterations prohibited, attribution required.

Important caveat:

This export is not a final Alpecca model. It is only a first compatibility/test artifact for Claude Code and Jason's VRM/VRoid companion tool. Continue improving the source `.vroid` before any production export.

## Companion App Handoff

Use this artifact for the first VRM companion-app import test:

`C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\companion_tool_drop\alpecca_vroid_proxy_v0_first_test_20260706.vrm`

Companion validation goals:

- Confirm the file imports as VRM 1.0.
- Confirm scale reads as an adult female Alpecca proxy and does not spawn tiny or oversized.
- Confirm materials load without missing textures or broken transparency.
- Confirm expressions/blend shapes are visible enough for a companion app test.
- Confirm locomotion/idle animation retargeting does not distort hair, hoodie, or legs.
- Confirm the body mesh is not hidden underneath clothing in a way that would leave a missing torso or missing limbs if clothing visibility changes.
- Report screenshots from front, 3/4, side, and back views before making any export-quality decision.

This companion drop is for compatibility only. Continue source model design in the `.vroid` file.

## Current Model Status

What has been improved:

- Real hoodie custom item was imported into VRoid.
- Old long-coat proxy should no longer be treated as the desired hoodie.
- Hoodie texture was recolored away from purple/teal toward Alpecca's cream/white hoodie and white center shirt.
- Inner material was given a plain white texture to reduce blue/cyan bleed.
- Hair main color was shifted from yellow toward pale cream-blond, currently visible in VRoid as `#F8EFEF`.
- Model was saved after the hoodie and hair-color pass.

Progress 2026-07-05 03:21 (Claude computer-use run):

- Hair base color is now pale platinum `#F8EFEF` on ALL hair groups (Back was still `#F9F1BE` yellow; fixed via the Main Color hex field).
- `alpecca_hair_bluelavender_tip_gradient_1024x2048.png` imported as a texture layer on the back-hair material (Edit Hairstyle > material > Edit Texture > Load Image as new layer). Soft lavender-blue tip wash confirmed on the model, front view.
- Custom hair items overwritten in place (Front/Back/Side/Ahoge), project saved in place.
- GUI automation notes: camera orbit via synthetic drags does NOT work (all variants tried); scroll-zoom, clicks, and Win32 file dialogs DO work. The Claude Desktop window floats over VRoid's right panel and silently eats clicks there — snap VRoid to the left half (Win+Left) before driving the right-side panels. Camera rotation DOES work via PowerShell keybd_event numpad VK codes (0x66/0x64 rotate, 0x61 front, 6 taps = 90°) — side and back hair QA passed with it.
- Iris pass (03:34 save): `alpecca_blue_iris_pair_texture_v2_2048x1024.png` imported as a layer on the existing custom Irises item (Face > Irises > Edit Texture), overwritten in place. Eyes now read deep soft blue with highlight, front-view verified. The lash pair texture is prepared but NOT yet applied (next pass, judge with Jason live).
- ChatGPT art pass (03:54): generated the nose-shading face reference via the ChatGPT desktop app (passdown prompt + 5-Photo-5 attached; the app was driven with computer use, split-screen right of VRoid). Saved to `chatgpt_generated/alpecca_face_nose_shading_overlay_v1.png` — RGBA transparent, 1024x1536, design lock held (soft blue eyes, subtle nose shading, soft blush, no text/halo). NOTE: it is a front-facing REFERENCE portrait, NOT a UV-mapped VRoid face texture — do not import it raw onto the face; use it to reproduce nose shading/blush in the face texture editor or extract patches aligned to the face UV. ALSO NOTE: in `vrm_custom_assets/ac167033/` the face photo is `5-Photo-5` (1-Photo-1 is an iris close-up) — the passboard's photo-to-view mapping is wrong for this folder.

Progress 2026-07-05 07:12-07:41 (Claude computer-use run, continued):

- Hoodie back logo (07:30 save): deep-blue power symbol + "ALPECCA" wordmark (Arial Rounded Bold) now on the hoodie's upper/mid back, generated as `vroid_texture_layers/alpecca_hoodie_back_logo_v2.png` and imported as a layer on the outer Hoodie material of the BOOTH "Hoodie Open" item, item overwritten in place. KEY UV FACTS (outer hoodie material, 2048x2048): the body wrap's CENTER-BACK SEAM is at the UV block's outer edges x=219 and x=1829 — a back-centered graphic must be split (left-of-spine half ends at x1829, right-of-spine half starts at x219; no mirroring, direct copy both halves, add ~7px bleed past each edge). Upper-back islands (shoulder-blade zone) are x219-471 and x1577-1829 at y1024-1344; below y1360 the body is one continuous strip x219-1829 to the hem zigzag at y~1950; armhole notch intrudes at x~360-395 around y1300. Front-opening alpha gap sits at x~941-1012. The BOOTH base texture is near-white; the light blue comes from the material Base Color tint, so dark blue overlays read correctly, white does not.
- Choker (07:41 save): per the turnaround sheet, blue neck band (76,116,200) with darker edge lines and a silver square buckle at front center, generated as `vroid_texture_layers/alpecca_choker_skin_overlay_v1.png` and imported as a layer on the BODY SKIN texture (Body > Edit Texture). Closing prompts "Whole Body will be saved as a new item" — the skin is now a custom Body item named "Skin" (thumbnail shows the blue strip). NECK UV FACTS (body skin, 2048x2048): neck front island ~x928-1120 (front center ≈ x1024), neck back halves ~x735-829 and ~x1219-1313, all spanning y~20-250 before merging into the torso by y~416; choker band painted x690-1360, y105-175 wraps the full neck; nothing else occupies that strip. Ear-ish side pieces at x496-602/x1466-1552 must be avoided.
- Correction 2026-07-08: Jason rejected this collar/choker texture as a mismatch with Alpecca's design. The top body-skin layer was deleted in VRoid Studio, the custom `Skin` item was overwritten, and `alpecca_vroid_proxy_v0.vroid` was saved in place. Do not re-add this collar/choker pass.
- Boot geometry update 2026-07-08: active `alpecca_vroid_proxy_v0.vroid` was saved after improving the shoe silhouette in VRoid Studio. Current shoe values: `Overall Volume` 33.436, `Boot Volume` 57.753, `Toebox Width` 31.322, `Toebox Volume` 44.361, `Toebox Thickness` 28.855, `Foot Thickness` 22.159. The boots now read chunkier and keep the cream/blue palette; remaining footwear work is exact custom texture/model polish.
- Accessory routing update 2026-07-08: VRoid's Accessories tab has the correct `Import as Custom Item` path for the hair clip, and the model currently has no Accessories items. Do not use `Create New` hats/bows/glasses/ears as a fake clip. Free BOOTH hair-clip candidates were found, but their `.vroidcustomitem` downloads redirect to BOOTH sign-in, so import is blocked until Jason provides a downloaded `.vroidcustomitem` or signs in.
- UV calibration upgrade: "Export Guide" in the layer context menu exports the exact UV wireframe (black lines + black fill outside islands, island interiors transparent) — analyzing that PNG in Python (transparent-fraction density map + per-row segment scan) gives exact island bounds and beats color-band guessing. Guides saved: `vroid_texture_layers/hoodie_outer_uv_guide.png`, `vroid_texture_layers/body_skin_uv_guide.png`.
- Save flow gotcha: the centered "Close Texture Editor" dialog can eat the first click on Overwrite — click again if the dialog persists. Ctrl+S via MCP key tool works but can lag; verify by title asterisk clearing AND `.vroid` mtime.
- Project saves verified on disk: 07:30:19 (8,939,459 bytes, back logo) and 07:41:15 (9,467,824 bytes, choker skin).

Progress 2026-07-05 08:00 (hoodie color fix per Jason "hoodie is wrong color"):

- The BOOTH hoodie's light blue came from the material Base Color tints (#C3F2FF), not the textures (which are near-white). Fixed per the turnaround sheet: outer Hoodie material Base Color -> #F7EFE7 (warm ivory), hood material Base Color -> #FFF6E8, hood Shade Color -> #AEC6EE so the hood interior reads blue-lined in shadow (the hood is entirely material 2; its interior shows via shade). Fabric now renders warm ivory like the sheet.
- Back logo recolored to the sheet's sky blue (94,150,216) and combined with new trim into one layer `vroid_texture_layers/alpecca_hoodie_ivory_details_v3.png` (replaces the old deep-blue logo layer): power symbol + ALPECCA wordmark on the back, two blue stripes on each cuff ribbing (texture y812-852 across both sleeve pieces), dashed blue hem band (y1886-1924, skipping the front gap x930-1135). Item overwritten, project saved 08:00:33 (9,467,856 bytes).
- Colors were sampled from `design_lock_references/01-turnaround-front-side-back.jpg` (fabric ivory ~#F2E9E2 lit, hood lining periwinkle ~#BDD2F2, logo blue ~#5E96D8, trim blue ~#96B2DE, sleeve patch = dark navy w/ blue power symbol).
- STOCKINGS "bare from behind" MYSTERY SOLVED: the white v5 sock texture fully wraps both legs (verified with hbands/vbands calibration + a region-probe texture). The pink backs are SHADING, not missing texture: VRoid "Skin Overlay" items (socks category) shade with the BODY SKIN's Dark Color (#EFBAA3), so white stockings in shadow render skin-pink and read as bare legs. VRoid 2.14 exposes NO per-material shader colors for Skin Overlay items (no Shader Color section, parameters locked, only ankle-height sock templates exist). Options: adjust global shading in the Look tab (design decision - ask Jason), or accept front-lit appearance. Do NOT "fix" the sock texture - it is correct. JASON RULING 2026-07-05: she already has stockings, do NOT make new thigh-high stockings or touch the Socks item at all.
- Remaining hoodie deltas vs sheet: blue dashes along the hood center seam. Sheet also shows the back logo larger and higher than current placement (current sits lower so it is visible below her hair).

Progress 2026-07-05 08:21 (left-sleeve pass, saved 08:21:09, 9,468,357 bytes):

- Sheet check confirmed the sleeve details are LEFT ARM ONLY (right sleeve is plain): twin blue shoulder tape -> dark navy power-symbol patch at the deltoid -> paired dashes continuing below, plus the cuff stripes both arms already have.
- SLEEVE UV MAP (outer hoodie material): piece x32-608 = HER RIGHT sleeve (top-of-arm line ~x320, front of arm = higher x, back = lower x); piece x1440-2016 = HER LEFT sleeve (top line ~x1728, front = lower x, back = higher x; mirrored). UV y runs shoulder ~y195 -> cuff ribbing ~y805 (ribbing y805-890, teeth to ~y960). Calibrated with vbands front+back reads; note BACK-view orientation: her right arm is on screen RIGHT.
- Current custom layer is `vroid_texture_layers/alpecca_hoodie_ivory_details_v5.png` (replaces v3/v4): back logo + cuff stripes + hem dashes + left-sleeve tape (x1728±27, y195-292), navy patch (center x1748, y285-428, power symbol + text bars in light blue), dashes (y432-660). Patch is centered on the top-outer arm line: reads half-face from the front in T-pose and faces sideways with arms down (real-use pose); sheet's back-facing lean was tried (+20 shift) and kept.
- Dialog gotchas reconfirmed: file-dialog filename typing often fails on the FIRST attempt (click field, type, Enter; if the dialog persists, click+retype once more, or scroll the list and double-click the file); the Close Texture Editor dialog eats the first Overwrite click.

What is still not good enough:

- Hair clip: VRoid 2.14 has NO hairpin/ribbon accessory preset (only Glasses/Furry Ears/Tail/Hat) and no clip `.vroidcustomitem` exists in the repo. Keep this as its own BOOTH/imported `Accessories` custom item/category when Jason supplies one; use a manual freehand hair-strand clip only as a fallback.
- Hair is much closer now but tips/wash have only been verified from the front camera.
- Hair shape needs more attention: long flowing hair, side pieces, ahoge, and a small blue hair clip.
- Face still needs stronger Alpecca identity: soft blue eyes, subtle nose shading, gentle anime face proportions, and less generic VRoid look.
- Hoodie shape is closer, but hoodie texture may still need cleanup for cream fabric, white undershirt, and blue trim details.
- Do not make another VRM export unless Jason explicitly asks. The existing 2026-07-06 export is a first test artifact only.

## Design Lock

Do not drift from Alpecca's design.

Required design traits:

- Adult female companion.
- Approximate target height: 5 ft 7 in / around 170 cm.
- Pale blond / platinum hair, not saturated yellow.
- Light blue to lavender hair tips.
- Long hair with soft volume.
- Ahoge/cowlick on top.
- Small blue hair clip on the left side of her hair.
- Soft blue eyes.
- Subtle anime nose shading.
- Gentle, calm face.
- Cream/white hoodie, not yellow and not purple.
- White T-shirt / underlayer under the hoodie.
- White thigh-high leggings are part of the broader design and should not be forgotten later.
- Avoid changing her into a different character, outfit, body type, or color palette.

Recent local reference images from the Codex attachment cache:

- `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\251dcebd-a891-4830-ab00-55615404f0e8\1-Photo-1.jpg`
- `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\251dcebd-a891-4830-ab00-55615404f0e8\2-Photo-2.jpg`
- `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\251dcebd-a891-4830-ab00-55615404f0e8\3-Photo-3.jpg`
- `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\251dcebd-a891-4830-ab00-55615404f0e8\4-Photo-4.jpg`
- `C:\Users\Jason\Documents\Codex\2026-06-15\create-3d-exploration-game-based-inside\.codex-remote-attachments\019ecec5-3f7c-7df1-9160-f9e0b0c287de\251dcebd-a891-4830-ab00-55615404f0e8\5-Photo-5.jpg`

Use these as visual truth, not as optional inspiration.

## Workflow Rules From Jason

- Focus on in-app VRoid Studio control.
- Do not create piles of unnecessary scripts.
- Small helper scripts are acceptable only when they directly create or repair a VRoid texture that will be imported.
- Save about every 15 minutes or after a verified meaningful improvement, not after every tiny click.
- Rotate and zoom out the character in VRoid before judging changes.
- Check category and subcategory scrollbars. Many VRoid presets are hidden below the visible panel.
- Use Edge, not Chrome, if a browser is needed.
- Do not accept account/security prompts or sign-in prompts on Jason's behalf.
- Do not upload art to Cloudflare. Use Hugging Face for large art storage when storage is needed.
- Do not export another VRM until Jason confirms or requests a new test artifact.
- Do not replace Alpecca's current system. This is a VRoid/VRM experiment only.

## Immediate Next Tasks

1. Open `alpecca_vroid_proxy_v0.vroid` in VRoid Studio if it is not already open.
2. Verify the hoodie still reads as cream/white with a white shirt, not teal or purple.
3. Work on base model fidelity next:
   - hair color and gradient;
   - hair tips;
   - face shape and eyes;
   - subtle nose shading;
   - hair clip / accessory.
4. Check clothing/body integrity:
   - base torso and limbs must remain fully rendered under clothing;
   - inspect VRoid skin mask / clothing mask settings before any future export;
   - do not accept a model where removing a shirt/hoodie would reveal missing torso geometry.
5. Do not spend the next pass on major clothing beyond preserving the hoodie and underlayer.
6. Take or inspect screenshots after each visible pass and compare to reference.

## ChatGPT Art Generation Instructions For Claude Code

Claude Code should use ChatGPT image generation as an art collaborator when VRoid's built-in presets are insufficient. Do not rely only on existing art if it cannot reach the design goal. The goal is to generate missing Alpecca-specific art while preserving her locked design.

Use ChatGPT for:

- VRoid face texture guide images.
- Nose shading texture references.
- Hair gradient texture references.
- Hoodie texture overlays.
- Hair clip concept art.
- 360/turnaround reference sheets for later modeling.
- Clean 4K reference sheets for future 2D/3D hybrid animation work.

Do not ask ChatGPT to redesign Alpecca. Ask it to produce locked-design assets that match the existing Alpecca reference.

Minimum generation rules:

- 4K minimum for source art whenever possible.
- Transparent PNG when the asset is meant to become a texture overlay.
- No baked halo.
- No baked shadow.
- No random logo or text.
- No outfit redesign unless Jason explicitly asks.
- Keep the cream hoodie, white shirt, pale blond hair, blue/lavender tips, blue eyes, and small blue hair clip.
- Reject generations that make her hair yellow, remove the thigh-high design, change her body type, change her age presentation, or make her a different character.

### ChatGPT Prompt: Hair Gradient Texture Reference

Use this prompt with the current reference images attached:

```text
Create a high-resolution VRoid hair texture reference for Alpecca. Keep her design locked: pale platinum-blond anime hair, soft cream-pink highlights, light blue to lavender gradient only at the lower tips, long smooth strands, delicate line detail, no yellow saturation, no green cast. Do not redesign her. Do not add halo, shadow, text, logo, or background. Output a clean 4K texture-style reference suitable for recreating in VRoid Studio hair materials.
```

### ChatGPT Prompt: Face And Nose Shading Texture Reference

Use this prompt with the current reference images attached:

```text
Create a clean 4K anime face texture reference for Alpecca for use in VRoid Studio. Keep her identity locked: soft blue eyes, pale skin, gentle expression, subtle small nose shading, soft blush, delicate lower eyelid detail, calm companion feel. No heavy makeup, no dramatic expression, no redesign, no halo, no background, no text. Focus on texture-level face details that can be reproduced in VRoid: nose shading, blush, eye softness, and skin gradients.
```

### ChatGPT Prompt: Hoodie Texture Reference

Use this prompt with the current reference images attached:

```text
Create a clean 4K hoodie texture reference for Alpecca. The hoodie must be warm cream / off-white, not yellow, not purple. Underlayer is a clean white T-shirt. Add only subtle pale-blue trim where appropriate, matching Alpecca's design. No redesign, no logos, no new symbols, no dark heavy shadows, no text. The output should help repaint a VRoid hoodie texture while preserving the existing hoodie mesh.
```

### ChatGPT Prompt: Hair Clip Reference

Use this prompt with the current reference images attached:

```text
Create a small blue hair clip accessory reference for Alpecca, matching her reference sheet. The clip is a soft blue bone/bow-like shape on the left side of her hair. Make it simple enough to model or texture in VRoid, glossy but not oversized, with no text, no background, no extra accessories, and no design drift.
```

### ChatGPT Prompt: Full Identity Lock Sheet

Use this before larger changes:

```text
Create a 4K identity-lock reference sheet for Alpecca's VRoid model. Show front, 3/4 front, side, 3/4 back, and back views. She is an adult female AI companion with pale platinum-blond long hair, light blue/lavender tips, soft blue eyes, ahoge, small blue hair clip, cream/white hoodie, white T-shirt, white thigh-high leggings, and calm gentle expression. Keep proportions consistent. No halo, no baked shadow, no redesign, no alternate outfit, no text except simple view labels if necessary.
```

## How To Apply ChatGPT Art Back Into VRoid

1. Generate the reference or texture in ChatGPT.
2. Save the image into a local staging folder first, preferably:
   `C:\Users\Jason\Documents\GitHub\alpaccaai\data\alpecca_art_source\vrm_experiments\chatgpt_generated`
3. Inspect the image before importing.
4. If it is a texture overlay, make sure it is transparent where needed.
5. Import through VRoid's texture editor as a new layer.
6. Verify on the 3D model by rotating and zooming out.
7. Save only after the change visibly improves Alpecca.

Do not blindly import raw generated art onto the model. VRoid UVs may not match the generated image. Treat generated art as source/reference unless it is specifically prepared as a VRoid texture layer.

## Recommended Next VRoid Pass

Focus order:

1. Hair base color: reduce remaining yellow and keep pale blond / cream-platinum.
2. Hair tip gradient: make lower hair tips visibly light blue/lavender.
3. Face identity: adjust blue eyes, nose shading, soft blush.
4. Hair clip: find or create a small blue clip accessory.
5. Hoodie cleanup: remove any remaining cool-blue cast from the center if it still reads wrong after rotating.
6. Only after base model is closer, return to clothing details.

## QA Checklist Before Claiming Progress

Before telling Jason a pass is done:

- Rotate model front, side, and back in VRoid.
- Zoom out enough to see full-body proportions.
- Confirm hoodie does not look yellow/purple/teal.
- Confirm shirt reads white.
- Confirm hair is pale blond, not yellow-green.
- Confirm blue/lavender tips are present but not covering the whole head.
- Confirm face still reads as Alpecca, not a generic VRoid preset.
- Confirm the model file timestamp changed after saving.

## Do Not Do

- Do not export another VRM unless Jason asks for a new test export.
- Do not push unrelated code changes.
- Do not overwrite Jason's manual VRoid adjustments without checking the current state.
- Do not revert other repo changes.
- Do not create a new game/app state.
- Do not treat this as a replacement for House HQ or the Alpecca app.
- Do not change spelling to Alpacca in user-facing docs.
