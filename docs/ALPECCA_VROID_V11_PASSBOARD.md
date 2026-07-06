# Alpecca VRoid v11 Hair-Lock Passboard

## Mission

Complete the v11 pass for Alpecca base-model fidelity in VRoid Studio while preserving
body proportions and the in-place checkpoint discipline:

- strengthen front/side/back hair volume,
- tune front/side hair gradient behavior,
- refine ahoge geometry,
- place the blue glossy bone/bow clip on the left side.

Target source file:

- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`

## Runtime Setup

- Launch VRoid Studio 2.14.0.
- Open `File > Open`.
- Load:
  - `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`
- Keep the following reference panels visible:
  - `data/alpecca_art_source/vrm_custom_assets/ac167033/1-Photo-1.jpg`
  - `data/alpecca_art_source/vrm_custom_assets/ac167033/2-Photo-2.jpg`
  - `data/alpecca_art_source/vrm_custom_assets/ac167033/3-Photo-3.jpg`
  - `data/alpecca_art_source/vrm_custom_assets/ac167033/4-Photo-4.jpg`
  - `data/alpecca_art_source/vrm_custom_assets/ac167033/5-Photo-5.jpg`

## Execution Sequence

1. Open `Hairstyle` panel.
2. Open `Edit Hairstyle`.
3. Enable/inspect hair groups: `Front`, `Side`, `Back`, `Ahoge`, `Base Hair`,
   `Overall Hair`, `Hairstyle Sets`.
4. For each group, tune silhouette so long strands keep volume in 90 and 135 side checks:
   - reduce flattening,
   - increase forward/back spread only where it reads too short,
   - preserve face framing around crown.
5. Ahoge pass:
   - Enter `Ahoge > Custom > Edit Hairstyle`,
   - maintain single curved lock (single arc, no twin tuft),
   - keep anchor above left-temple/left-front region,
   - avoid touching head shape.
6. Hair material pass:
   - keep upper crown white-silver (`#FCECF6`) base,
   - keep cool highlight (`#C7D5FF`) only for strand accents,
   - apply gradient where possible so lower hair transitions to lavender-blue,
   - avoid hard transitions or orange/purple casts.
7. Clip placement:
   - add or import glossy blue bone/bow clip,
   - place on left side of hair mass above earline,
   - do not mirror right.
8. Preview QA cycle:
   - open `ALPECCA_V11_15_VIEW_CAMERA_MATRIX.md`,
   - run Low/Eye/High front, 45, 90, 135, 180 and mirror confirmations,
   - confirm no shell-collapse on side profiles and ahoge stays single.
9. Finish with accessory sanity:
   - confirm no accidental accessory defaults beyond planned clip/path,
   - keep head and shoulder silhouette stable.

Use `docs/ALPECCA_V11_PANEL_CONTROL_MATRIX.md` for tab-by-tab control boundaries and save rules.

Use `docs/ALPECCA_V11_SESSION_CARD.md` at run start and after major edits to
track what is still open and what the next gate command should be.

Mandatory QA cross-check:

- Execute `ALPECCA_V11_VR_QA_CHECKLIST.md` and
  `ALPECCA_V11_15_VIEW_CAMERA_MATRIX.md` after camera QA before save.

## Acceptance Gate (Pass or Continue)

- Side/quarter profiles preserve long-flow silhouette.
- Ahoge is clearly one single curl from side/top reference.
- Hair lower area has smooth lavender wash and soft transition.
- Clip remains on left side only and does not read as accessory halo.
- Head-to-neck proportion remains unchanged from previous base model lock.

## Save Rule

- Save only when all acceptance checks are true.
- Save as overwrite on:
  - `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`
- Update manifest checkpoint notes immediately after save.
