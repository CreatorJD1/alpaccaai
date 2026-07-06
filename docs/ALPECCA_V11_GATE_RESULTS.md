# Alpecca VRoid v11 Gate Results Log

**Session ID:** v11-hair-lock-pass-2026-07-05  
**Target checkpoint:** `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`  
**Objective:** close design-to-reference gate checks before moving to `base-gate-validated`.

## 15-View Matrix

Fill each check as PASS / REWORK / N/A and add one short note when needed.

| Group | Check | Status | Notes |
|---|---|---|---|
| Low | L0 - Front (0 deg) | REWORK | Identity markers still need work: lanyard/ID is now imported rough, but open hoodie-jacket, hair clip, right thigh strap, and boot details remain. |
| Low | L45 - Front-Right (45 deg) | REWORK | Same design mismatch visible; hoodie reads as closed generic proxy. |
| Low | L90 - Right (90 deg) | REWORK | Side audit shows closed hoodie bulk; lanyard layer is visible but needs scale/placement refinement. |
| Low | L135 - Back-Right (135 deg) | REWORK | Back/quarter needs jacket, hair depth, and design-marker validation after edits. |
| Low | L180 - Back (180 deg) | REWORK | Back design markers and hair silhouette are not locked yet. |
| Eye | E0 - Front (0 deg) | REWORK | Front screenshot confirms proxy is not close enough to 2D references. |
| Eye | E45 - Front-Right (45 deg) | REWORK | Quarter-view identity is still generic VRoid hoodie rather than Alpecca jacket. |
| Eye | E90 - Right (90 deg) | REWORK | Side silhouette needs custom outfit/texture pass; lanyard layer is present but not final. |
| Eye | E135 - Back-Right (135 deg) | REWORK | Requires back/quarter recheck after hair and outfit rework. |
| Eye | E180 - Back (180 deg) | REWORK | Requires back identity pass; current gate cannot pass from front/side evidence. |
| High | H0 - Front (0 deg) | REWORK | High view cannot pass while core identity markers are missing. |
| High | H45 - Front-Right (45 deg) | REWORK | Needs same outfit and accessory rework before high-quarter approval. |
| High | H90 - Right (90 deg) | REWORK | Side/high view needs volume and accessory validation after edits. |
| High | H135 - Back-Right (135 deg) | REWORK | Not ready for approval until back hair/outfit markers are corrected. |
| High | H180 - Back (180 deg) | REWORK | Not ready for approval; back view still needs a full identity pass. |

## Mirror checks

| Check | Status | Notes |
|---|---|---|
| Mirror-side (90 deg equivalent) | REWORK | Mirror cannot pass until left-only clip and side silhouette are locked. |
| Mirror-front-right | REWORK | Needs left/right identity audit after clip and jacket work. |
| Mirror-back-right | REWORK | Needs back-right/back-left validation after rework. |

## Core identity checks

| Check | Status | Notes |
|---|---|---|
| Ahoge is single curved lock | PASS | Current side/front inspection shows a single curved ahoge proxy. |
| Clip remains left-only and above earline | REWORK | Blue left-side clip is still missing or not visible enough to validate. |
| Hair lower gradient smooth and not harsh | REWORK | Current material is a pale proxy; final lower lavender-blue gradient is not painted/locked. |
| Side/back volume not flattened | REWORK | Side hair has volume, but back/quarter checks still need correction and proof. |

## Verdict

- All matrix checks complete: `YES - REWORK REQUIRED`
- Final gate command used:
  - Success: `python scripts/update_v11_vroid_state.py --state base-gate-validated --notes "..."`
  - Rework: `python scripts/update_v11_vroid_state.py --state base-gate-rework --notes "..."`

## Last Update

- 2026-07-05: Gate sheet initialized to support live VRoid QA fill-in.
- 2026-07-05: Codex Spark live VRoid inspection opened the v11 checkpoint and confirmed the model is not ready for base-gate validation. Moved blank checks to REWORK/PASS evidence so the next state can become `base-gate-rework`.
- 2026-07-05: Imported `alpecca_lanyard_badge_source_2048x3072.png` as a new hoodie texture layer and saved the v11 project. This improves identity read but remains REWORK because scale/placement and the open jacket silhouette still need refinement.
- 2026-07-05: User reported manual adjustments. Live VRoid window was inspected and is currently open to `alpecca_vroid_proxy_v0.vroid`, not the v11 checkpoint. Do not mark v11 gates improved from the v0 view; reopen the v11 checkpoint before continuing v11 validation or explicitly branch v0 if the user wants those edits promoted.
- 2026-07-05: Preserved the open v0 branch as `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v12_user_adjusted_from_v0.vroid` for comparison. v11 gates remain unchanged until v11 itself is reopened and inspected.
