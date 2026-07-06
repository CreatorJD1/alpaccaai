# v11 Resume Log — Alpecca VRoid Base-Model Pass

**Latest Update (resume):** 2026-07-04 20:58 PT  
**Action:** Expanded v11 passbooks to tighten full-toolset execution, 15-view matrix checks, and in-place save cadence for the design-matching objective.  
**Status:** `gui-resume-in-progress` remains active; continue in-place pass on `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`.

**Latest Update (resume):** 2026-07-04 20:58 PT  
**Action:** Restored and linked the VRoid operation recipe doc inside the source repo docs set. Verified strict pre-flight readiness and re-logged manifest state.

**Latest Update (resume):** 2026-07-04 20:45 PT  
**Action:** Refined the v11 experiment handoff documents for a full-toolset session.

**Latest Update (resume):** 2026-07-04 20:31 PT  
**Action:** Added `scripts/audit_v11_vroid_session.py` and linked mandatory pre-flight + launch commands into `docs/ALPECCA_VROID_VRM_EXPERIMENT.md`.

**Current Run Focus:**
- Keep in-place checkpoint discipline.
- Run full-toolset passbook and QA list in order.
- Run 15-view matrix and mirror checks before manifest transition.

**Latest Update (resume):** 2026-07-04 20:11 PT  
**Action:** Re-ran pre-flight and confirmed readiness to continue same checkpoint.

**Resume Time:** 2026-07-04 19:17 PT  
**Status:** Awaiting GUI execution in VRoid Studio  
**Current Checkpoint:** `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`

## What is active

- v11Iteration state is now `gui-resume-in-progress`.
- Working scope: full-toolset base match lock: body/face/hairstyle/ahoge/outfit identity/clip.
- Continue in-place, no unrelated runtime/game changes.

## Runbook for next action

1. Launch VRoid and load the v11 checkpoint.
2. Execute `docs/ALPECCA_VROID_V11_PASSBOARD.md` and `docs/ALPECCA_V11_VR_QA_CHECKLIST.md` end-to-end.
3. Run `docs/ALPECCA_V11_15_VIEW_CAMERA_MATRIX.md` checks.
4. Save only if all gates pass.
5. Update manifest:
   - Pass: `python scripts/update_v11_vroid_state.py --state base-gate-validated --notes "v11 gates passed"`
   - Fail: `python scripts/update_v11_vroid_state.py --state base-gate-rework --notes "v11 qa fail: ..."`

## Notes

- Do not save per tiny micro-adjustments.
- Save only on meaningful pass completion approximately every 15 minutes.
- This is an experimental character-reference pass only and should not alter house runtime.
