# Docs Index

**Last updated:** 2026-07-23

Stage 0 is complete. Native phone trust and communication-channel boundaries
now have implemented security gates; live phone, Discord voice, and release
soaks remain open and must not be described as complete.

## Active Phase 9 Checkpoint

Phase 9 remains **PARTIAL**. Creator-only, server-resolved House text attachments
use an allowed-root id and relative path, audit file access before
the read, derive MIME and SHA-256 locally, bind provenance to the exact turn
scope, force local-only inference, and suppress tools while bounded file text is
present. The serialized attachment record retains metadata-only provenance, and
the legacy raw/base64 `file_name`/`file_data` path is retired. File-derived
answers are live but ephemeral: commitment mutation, durable content retention,
Mindscape sync, and automatic OpenClaw delivery are blocked. Existing source,
image, and audio perception behavior remains as documented.

Expiring connection-bound capability leases now gate browser camera, screen,
microphone, voice-enrollment, and exact file-reference use. Their fixed caps,
disconnect/restart revocation, and sealed content-free transition evidence are
implemented for House HQ and the secondary classic app. Provider/model-specific
egress consent is not yet wired into perception, and signed Discord guest
identity is wired for allowlisted DMs. Claimed guild-room participation and
duplex Discord voice paths are implemented with bounded state, but live
microphone/playback quality, retained guest context, production rates and
approvals, and actor anchoring still lack release evidence. Do not mark Phase 9
or Phase 10 complete.

Phase 11 is partial with one explicit app Web Push connection-test path
implemented. House Devices controls enroll/revoke a browser and request the fixed test;
provider acceptance is separate from one-use click acknowledgement. No model or
autonomous notification trigger, arbitrary payload, Discord delivery, SMS, or
call path is live. Browser enrollment, an accepted-device test, and mobile soak
remain pending. The subscription record and monotonic anchor are distinct
Credential Manager records in the same failure domain, so they detect
record-only rollback rather than coordinated Credential Manager restoration.

## Canonical Sources

For implementation and behavior decisions, use:

- `PROJECT_CONTEXT.md`
- `HANDOFF.md`
- `docs/AGENTIC_ASSESSMENT.md`
- `docs/ALPECCA_CURRENT_PROGRESS.md`
- `docs/ALPECCA_BRAIN_PLUGINS.md`
- `docs/UBUNTU_FALLBACK_CORE_PLAN.md` (inert scaffold implemented; deployment and leader supervisor pending)
- `docs/SOURCE_QUALITY_AUDIT_PLAN.md` (prepared; execute after a green stage checkpoint)
- `docs/RELEASE_SECRET_SCAN.md` (implemented P1 content-free source/bundle gate)
- `docs/RELEASE_SOAK.md` (observation-only P14 harness; no completion claim)
- `docs/SOUL_FALLBACK_ARCHITECTURE.md`

## Freshness Rule

Docs older than 4 days should be archived under `docs/archive/YYYY-MM-DD/` unless marked
as required passdown or reference logs.

## Document Status (This Cycle)

### CURRENT
- `docs/ALPECCA_MASTER_PLAN.md`
- `docs/ALPECCA_UNIFIED_MASTER_PLAN.md` (experience overlay; spine status remains authoritative)
- `docs/CLAUDE_FABLE_PARALLEL_DELEGATION.md`
- `docs/ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.md`
- `docs/AGENTIC_ASSESSMENT.md`
- `docs/MINDPAGE.md`
- `docs/AFFECTIVE_INCIDENT_LEARNING.md`
- `docs/EXPERIENCE_SHAPED_PERSONALITY.md`
- `docs/OPEN_SOURCE_RESEARCH_REVIEW.md` (2026-07-22 source-reviewed integration decisions and local acceptance gates)
- `docs/ROG_COMPUTE_WORKER.md` (compute-only Jason_HOLYROG setup and deployment gates)
- `docs/ALPECCA_STATE_DIAGNOSTIC_2026-07-23.md` (live measured primary/ROG health, latency, storage, and completion matrix)
- `docs/VIDEO_COMPANION_STREAMING_PLAN.md` (2026-07-22 researched full-video, live-stream, reactor, and governed-sharing stages)
- `docs/REPOSITORY_CLEANUP_MANIFEST.md`
- `docs/DOWNLOADED_SYSTEMS.md`
- `docs/ALPECCA_CURRENT_PROGRESS.md`
- `docs/ALPECCA_BRAIN_PLUGINS.md`
- `docs/RELEASE_SECRET_SCAN.md`
- `docs/RELEASE_SOAK.md`
- `docs/UBUNTU_FALLBACK_CORE_PLAN.md`
- `PROJECT_CONTEXT.md`
- `HANDOFF.md`

### CURRENT VISUALS (regenerated 2026-07-15)
- `docs/ALPECCA_MASTER_PLAN.pdf`
- `docs/ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.pdf`
- `docs/ALPECCA_PROJECT_ARCHITECTURE_MAP.pdf`

These PDFs are generated from the 2026-07-15 source-reviewed status model. They
are visual summaries, not sources of truth; use `PROJECT_CONTEXT.md` and
`docs/ALPECCA_CURRENT_PROGRESS.md` when a later status conflicts.

### SUPERSEDED / ARCHIVED (2026-07-15)
- `docs/archive/2026-07-15/ALPECCA_STAGE0_2_GATE_AUDIT.md`: historical gate
  audit superseded by `PROJECT_CONTEXT.md` and the current phase matrix.
- `docs/archive/2026-07-15/ALPECCA_STAGE4_RECALL_DESIGN.md`: pre-implementation
  recall design superseded by the bounded P3/P4 implementation evidence.
- `docs/archive/2026-07-15/ALPECCA_ENTIRE_PROJECT_DETAILED_DIAGRAM.pdf`:
  superseded project visual retained for traceability.
- `docs/archive/2026-07-15/ALPECCA_MASTER_PLAN.pdf`
- `docs/archive/2026-07-15/ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.pdf`
- `docs/archive/2026-07-15/ALPECCA_PROJECT_ARCHITECTURE_MAP.pdf`

The last three paths are the prior generated visual snapshot. Their regenerated
current counterparts remain at the root paths listed above.

### HISTORICAL / PASSDOWN

The V11/older VRoid passdowns are archive candidates listed by exact path in
`docs/REPOSITORY_CLEANUP_MANIFEST.md`. They are not current behavior sources.

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

The archived July 9/10 architecture visuals supersede the downloaded June 14
systems graph. Historical visuals assigned cloud-reported memory and accelerator
capacity to the local rig. Current docs separate the approximately 24 GB DDR4 /
RTX 3050 4 GB laptop from optional, ephemeral Hugging Face ZeroGPU and Google
notebook compute.
