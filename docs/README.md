# Docs Index

**Last updated:** 2026-07-12

Stage 0 is complete. Phone and communication-channel security is intentionally
deferred until the post-stage hardening pass; no phone identifier or channel is
changed by the current rollout.

## Canonical Sources

For implementation and behavior decisions, use:

- `PROJECT_CONTEXT.md`
- `HANDOFF.md`
- `docs/AGENTIC_ASSESSMENT.md`
- `docs/ALPECCA_CURRENT_PROGRESS.md`
- `docs/SOUL_FALLBACK_ARCHITECTURE.md`

## Freshness Rule

Docs older than 5 days should be archived under `docs/archive/YYYY-MM-DD/` unless marked
as required passdown or reference logs.

## Document Status (This Cycle)

### CURRENT
- `docs/ALPECCA_MASTER_PLAN.md`
- `docs/ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.md`
- `docs/AGENTIC_ASSESSMENT.md`
- `docs/MINDPAGE.md`
- `docs/DOWNLOADED_SYSTEMS.md`
- `docs/ALPECCA_CURRENT_PROGRESS.md`
- `PROJECT_CONTEXT.md`
- `HANDOFF.md`

### VISUAL BASELINE (2026-07-10)
- `docs/ALPECCA_MASTER_PLAN.pdf`
- `docs/ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.pdf`
- `docs/ALPECCA_PROJECT_ARCHITECTURE_MAP.pdf`

These PDFs remain useful architecture visuals, but their feature-status labels
predate the 2026-07-12 Phase 9 checkpoint. Use the current Markdown and canonical
sources above for implementation status until the visual set is regenerated.

### HISTORICAL / PASSDOWN
- `docs/ALPECCA_V11_*.md`
- `docs/ALPECCA_VROID_*.md`
- `docs/ALPECCA_V11_REFERENCE_CONTACT_SHEET.jpg`

### SUPERSEDED / ARCHIVED (2026-07-10)
- `docs/archive/2026-07-10/PASSDOWN_remote_computer_access.md`:
  **SUPERSEDED** by `PROJECT_CONTEXT.md`, `HANDOFF.md`,
  `docs/ALPECCA_MASTER_PLAN.md`, and `docs/ALPECCA_CURRENT_PROGRESS.md`.
  Its token-in-URL and unrestricted remote computer-access pipeline is retained
  only as historical evidence; current access uses creator trust and protected
  trusted-device sessions.

### ARCHIVED (2026-07-08)
- `docs/archive/2026-07-08/*`

## Archive Policy Notes

The archived set includes stale systems/plan/research docs that were superseded by
this session's assessed state, including:

- `ALPECCA_COLAB_T4.md`
- `BRINGING_HER_TO_LIFE.md`
- `DESIGN_expressiveness_autonomy_home.md`
- `INTEGRATE_RIGFORGE.md`
- `LAYER_SPLITTING.md`
- `UPGRADE_GUIDE.md`
- `ALPECCA_MASTER_GOAL_STATUS.md`
- `ALPECCA_RECURSIVE_ENGAGEMENT_RESEARCH.md`
- `ALPECCA_DISCORD_PRESENCE.md`
- `ALPECCA_STAGE4_360_REFERENCE_LOCK.md`
- `ALPECCA_STAGE4_NATIVE_4K_FIRST_SLICE.md`
- `ALPECCA_STAGE4_WALK_CYCLE_POSE_LOCK.md`
- `ALPECCA_STAGE4_WALK_PROOF_NOTES.md`
- `Alpecca_Systems_Review.pdf`
- `Alpecca_Systems_Review.html`

## Note

`docs/archive/2026-07-08/` retains the full historical files for traceability.
`docs/ALPECCA_CURRENT_PROGRESS.md` is a short, active pointer and is intentionally
small.

The July 9 architecture PDFs supersede the downloaded June 14 systems graph.
That graph assigned 34 GB DDR5 and H100 capacity to the local rig. Current docs
separate the 24 GB DDR4 / RTX 3050 4 GB laptop from optional, ephemeral Hugging
Face ZeroGPU and Google notebook compute.
