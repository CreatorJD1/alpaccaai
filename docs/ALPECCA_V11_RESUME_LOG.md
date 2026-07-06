**Latest Resume Update (2026-07-04 21:33 PT):** v11 pre-flight checks continue to pass.

**Action:** Resume v11 in-place base-model pass after previous run.

- `python scripts/audit_v11_vroid_session.py --strict` -> READY
- Working checkpoint exists:
  - `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`
- State remains: `gui-resume-in-progress`
- Next required gates: `15-view + mirror checks` before moving to `base-gate-validated`

**Action plan:**
1. Run `powershell -ExecutionPolicy Bypass -File scripts/start_vroid_v11_session.ps1 -StateNote "resume v11 full-toolset pass"`
2. Follow `docs/ALPECCA_V11_15_VIEW_CAMERA_MATRIX.md` and `docs/ALPECCA_V11_VR_QA_CHECKLIST.md`
3. Run side/front/back/3-4 checks with mirror consistency
4. On pass: `python scripts/update_v11_vroid_state.py --state base-gate-validated --notes "v11 gates passed"`
5. If any gate fails: `python scripts/update_v11_vroid_state.py --state base-gate-rework --notes "<specific issue>"`

**Note:** App/runtime code has not changed in this pass; this is a continuity handoff for the VRoid operator session only.

## 2026-07-05 Resume continuation

- Stage: **VRoid v11 base-model continuity pass** (post-v1 checkpoint)
- Current checkpoint: `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`
- Current state: `base-gate-validating`
- Immediate objective: complete side/front/back and 15-view/mirror checks against `ALPECCA_V11_15_VIEW_CAMERA_MATRIX.md`
- Required outcome before next checkpoint: pass all **15 directional checks + 3 mirror checks**, keep design lock unchanged, keep no runtime edits.

## 2026-07-05 Operator Artifact Added

- Created `docs/ALPECCA_V11_GATE_RESULTS.md` as an in-session QA sheet for all
  15-view + mirror checks.
- Next action remains `base-gate-validating` until all cells are PASS and the sheet is finalized.

**Action 2026-07-05:** Added `ALPECCA_V11_REFERENCE_CONTACT_SHEET.jpg` generation support and wired session helper to open it automatically. Run `python scripts/build_v11_reference_sheet.py` when references change, then run VRoid with `-SkipStateTouch` and complete gate checks in `ALPECCA_V11_GATE_RESULTS.md`.

## 2026-07-05 Resume Continuation (Codex Spark)

- Added `docs/ALPECCA_V11_PANEL_CONTROL_MATRIX.md` with the explicit v11 tab
  operation sequence for Base-model pass stability.
- Linked this matrix into:
  - `docs/ALPECCA_V11_FULL_TOOLSET_MASTER.md`
  - `docs/ALPECCA_V11_GUI_OPERATION_RECIPE.md`
- Manifest state updated to `gui-resume-in-progress` with note:
  "`Added operator-focused control matrix doc and linked it into full-toolset + recipe docs for consistent v11 manual passes. Next step: continue 15-view+mirror checks in VRoid.`"
