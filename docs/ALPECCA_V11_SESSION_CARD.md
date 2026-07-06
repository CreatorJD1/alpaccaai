# Alpecca VRoid v11 Session Card

Generated: 2026-07-05 09:08:11-0700

## Current State
- state: gui-resume-in-progress
- checkpoint: data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid
- focus: v11 full-toolset master execution in VRoid GUI: full-panel validation, front/side/back/quarter walks, ahoge guide lock, lavender gradient, and left blue clip placement
- target height: 170.4 cm
- status: **experimental only** (does not replace runtime systems)

## Branch Caution
- Live VRoid was last observed open to `alpecca_vroid_proxy_v0.vroid`, not the v11 checkpoint.
- That open v0 file has been preserved as:
  `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v12_user_adjusted_from_v0.vroid`
- Branch decision: continue v11 as the main rework path; keep v12 as a preserved fallback/reference.
- Decision doc: `docs/ALPECCA_VROID_BRANCH_DECISION.md`
- Do not validate v11 gates from v0/v12 screenshots.

## Design Gates Still Open
- open warm-ivory hoodie-jacket silhouette or custom texture/model workaround
- custom-drawn or imported pale-blue trim, zipper pulls, and sleeve modules
- refined placement/scale for the imported blue lanyard and Alpecca ID badge
- custom accessory/import or hair-guide workaround for the glossy blue bone/bow hair clip on her left side
- verify and optionally refine the v5 single curved ahoge/cowlick
- custom-drawn or imported right-leg black thigh strap
- custom-drawn cream/white boot texture with pale-blue soles/details

## Gate Results Quick Check
- rows parsed: 22
- incomplete: 0
- rework: 21
- invalid: 0
- passable: NO

## Next Required Actions
1. Open `docs/ALPECCA_V11_15_VIEW_CAMERA_MATRIX.md` and validate all 15-angle checks + mirror checks.
2. Fill `docs/ALPECCA_V11_GATE_RESULTS.md` with PASS/REWORK and one-line notes.
3. Re-run: `python scripts/validate_v11_gate_results.py`
4. If any check is REWORK: `python scripts/update_v11_vroid_state.py --state base-gate-rework --notes "..."`
5. If all check out: `python scripts/update_v11_vroid_state.py --state base-gate-validated --notes "v11 gates passed"`

## One-Line Launch
```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_vroid_v11_session.ps1 -StateNote "resume v11 full-toolset pass" -SkipStateTouch
```

## Full Toolset Confirmed Scope
- Body, Face, Hairstyle, Ahoge, Outfit, Accessories, Texture Editor
- Focus is on VRoid model fidelity only; runtime/game code untouched during this pass.