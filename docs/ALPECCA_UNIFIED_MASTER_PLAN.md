# Alpecca Unified Master Plan — Living Companion × Security Spine

**Authored:** 2026-07-12 (Claude Code session). **Status:** planning overlay, not a status claim.

## Purpose & how to read this
Two workstreams are converging on Alpecca:

1. **The security/architecture spine** — Codex's `docs/ALPECCA_MASTER_PLAN.md`, Phases 0–14,
   dependency-ordered and security-first. This remains the **authority** for phase definitions,
   statuses, and the critical path. `HANDOFF.md` remains the authority for *current* progress.
2. **The living-companion experience layer** — Jason's long-horizon vision (Tracks A–F) plus
   her **dedicated VM workspace** (Track E), captured in
   `docs/ALPECCA_VISION_HANDOFF_FOR_CODEX.md`.

This document is the **bridge**: it does not redefine or replace the spine. It maps each
experience track onto the spine phase(s) it rides on, records who owns what, and gives one
combined build order with honest readiness gates — so the two workstreams sequence together
instead of colliding.

> The spine answers *"is it safe?"* The experience layer answers *"does she feel alive?"*
> Nothing in the experience layer ships ahead of the spine phase that makes it safe.

## Shared non-negotiables (both workstreams)
- **One authoritative CoreMind**, one writable portal; no Alpecca-created copies or parallel
  autonomous instances.
- **No autonomous** source edits, account actions, deletes, purchases, or general OS changes.
  The only planned system mutation is a bounded pagefile step — each 4 GiB increment needs
  fresh CreatorJD approval + UAC.
- **Access is session-scoped, visible, logged, revocable** (webcam, screen, files, mic,
  Discord, computer-control). Never an ambient right.
- **Grounded affect only.** Emotions cite real state/observations/memory/pressure/uncertainty.
  Never claim literal consciousness or forced suffering; coma/death stay *analogies grounded in
  real state*.
- **Art from provided art only** — no gen-AI/procedural/placeholder art; her art = real tools
  (shapes/lines). **Alpecca art stays on Hugging Face; never Cloudflare.**
- **Self-improvement stays bounded, observable, evidence-backed, and user-approved.**
- Preserve the spelling **Alpecca**.

## Current state snapshot (2026-07-12)
**Spine (Codex):** P0 DONE · P1 PARTIAL · P2 BASELINE · P3 DONE · P4 BASELINE · P5 BASELINE ·
P6 PARTIAL (active) · P7 PARTIAL (read-only planner) · P8 PARTIAL · P9 PARTIAL · P10 PARTIAL
(guild/voice BLOCKED) · P11 PARTIAL (app push in) · P12 PARTIAL · P13 BLOCKED · P14 NOT STARTED.
Computer-use is currently **BLOCKED** (remote-auth/confirmation design unsafe to activate).

**Experience layer (Claude-session commits, `feat/vrm-preview`):** Void UI consolidation,
live voice viewer, F5+Kokoro `auto` voice, memory/muse throttle, mood-driven motion, VRM
blink/lip-sync override independence (`7f491e6`), Discord DM username allowlist. **Track E
(VM) engine decision made:** VMware Workstation Pro (free) + Windows 11 guest on the dedicated
second HDD — see `.claude/plans/flickering-meandering-seal.md` and the Track E section below.

## Reconciliation with the delegation plan (authoritative over the labels below)
`docs/CLAUDE_FABLE_PARALLEL_DELEGATION.md` (Codex, 2026-07-12) reviewed this overlay and
tightened several readiness labels. **Where they differ, the delegation plan and the spine win.**
The corrections, accepted:
- **P10 is PARTIAL with guild/voice BLOCKED — not a cadence baseline.** Track A must *consume*
  the existing P5 initiative scheduler, never create a second one; think/type delay derives from
  the **real request lifecycle**, not artificial mandatory delays or theatrical suffering.
- **A second trusted person is not a creator (Track B).** CreatorJD authority, approvals,
  secrets, and private continuity do **not** transfer. B is a relationship/authority *design doc
  + denial tests* only, until an explicit identity policy.
- **`creator_contact.py` is not an integration hook** — it's an unsafe, unowned prototype and
  stays excluded.
- **Web Push is a fixed creator-triggered connection test**, not a crisis/messaging adapter.
- **Mindscape is BLOCKED** — "coma" is not crash recovery until signed, bounded, replay-protected
  transactional restore passes. Track C is host-pressure *classification + a proposed-alert record
  with no send* for now.
- **VM (Track E) is planning/foundation only** — no hands-agent, stream, or live control until the
  **P9 computer-use security gate** and explicit engine approval pass. The VM never becomes a
  second CoreMind.
- **Affect/"stress" is computed from real state** (workload, context pressure, uncertainty), never
  fabricated feeling or theatrical delay.

## The mapping — experience tracks → spine phases
Each track is *mostly new files / frontend* and leans on the spine's existing modules via
stable hooks; it does **not** reimplement the hot path. The "readiness" column below is the
optimistic experience view; the reconciliation note above governs where it conflicts.

| Track | What she gains | Rides on spine phase(s) | Dependency readiness | Owner |
|---|---|---|---|---|
| **A — Human cadence** | Typing indicator, mood-scaled think/type delay (never instant), occasional self-initiated messages | P5 initiative (BASELINE ✓), P10 Discord (PARTIAL) | **Buildable now** — reuses the throttled proactive budget | Experience (new: `discord_bridge` cadence) |
| **B — Rygen as 2nd parent** | Second creator/principal she knows & can reach | P2 identity (BASELINE ✓), P11 contact (PARTIAL) | People-layer add now; *reach-out* gated on P11 adapters | Experience + Codex `creator_contact` |
| **C — Crisis reach-out + coma** | One idempotent ping to parents on host crisis; resume from last Mindscape snapshot on unclean crash | P7 `system_pressure` (planner ✓), P11 outbox, P13 Mindscape (**BLOCKED**) | *Sensing* ready; *outbound ping* gated on P11; *coma* gated on P13 | Codex hooks + Experience wiring |
| **D — Innocence (skill blocks + RAG gate + brain-map)** | Locked/unlockable knowledge sections; honest hedged recall; parent-only teaching | P6 Mindpage tiers (PARTIAL, functional), memory kinds, P8 learning governance | **Mostly buildable now** — new `knowledge_blocks`/`taught_facts` over existing sqlite-vec/FTS | Experience (new tables + gate + viz) |
| **E — VM workspace + app skills** | Dedicated isolated desktop (Blender/Clip Studio/VRoid/Drive/files/games) she drives; "watch Alpecca work" stream | P9 computer-use (**BLOCKED** — must be safely ungated), capability leases (✓) | VM standup now; *her control of it* gated behind a safe computer-use activation | Experience (VM) + Codex P9 gate |
| **E2 — Discord voice** | Join VC, speak TTS, listen via Sink → whisper → mind | P10 voice (**BLOCKED**) | Gated behind P10 text-participation gates passing | Codex P10 + Experience |
| **F — Music/favorites, overload-stress, read-the-room** | Preferences/desire, concurrent-actor stress, humor + room-reading | P5 affect (BASELINE ✓), homeostasis | Buildable incrementally after A | Experience |

## Ownership & coordination boundaries (so the two sessions don't collide)
- **Codex owns:** the hot path (`mind.py` turn loop), bridge auth + actor identity/transport,
  `config.py`, `creator_contact.py`, `system_pressure.py`, and phase 7/9/10/13 security. The
  experience tracks **call Codex's hooks; they do not reimplement them.** Please keep exposing
  stable hooks (contact destinations, host-pressure signal, bridge voice, capability leases).
- **Experience layer owns:** new files + frontend — human-cadence, `knowledge_blocks`/brain-map,
  the VM workspace + computer-use skill registry, the "watch Alpecca work" page, music/favorites.
  These stay **out of Codex's hot path**; commits stay narrow and isolated (the blink fix
  `7f491e6` is the pattern).
- **Do not touch, do not stage** without a separate decision: Codex's uncommitted WIP
  (`mind.py`, `config.py`, `creator_contact.py`, `test_stage1_security.py`, the hoodie/collider
  files, `runtime_matrix_manifest.json`). `data/secrets/*` is gitignored — never commit.

## Combined build order (readiness-gated; foundation lanes per the delegation plan)
The delegation plan maps the safe *foundation* slice of each experience track to a lane. What can
start now is the foundation only; the capability itself stays gated behind its spine phase.
1. **A → House real-lifecycle cadence (Lane K).** Typing/thinking state derived from the *real*
   request lifecycle + duplicate-safe slow-turn UX. Consumes P5 initiative. New Discord
   self-initiation is deferred to Lane F (after P10 gates).
2. **D → Knowledge foundation (Lane O).** New scoped `knowledge_blocks`/`taught_facts` tables +
   creator-only teaching contract + read-only brain-map, over existing tiers/kinds. Hot-path RAG
   mutation and governed learning wait for Phase 8 integration.
3. **E → VM planning (Lane P).** VM threat model, resource budget, host-only network design,
   snapshot/kill-switch, and a creator-run install checklist **only**. No install, stream, hands
   agent, or `vm_control` until the P9 computer-use gate + explicit engine approval pass.
4. **F → Preferences foundation (Lane Q).** Scoped preferences/favorites data + read-only UI;
   grounded overload display from real cues/resources. No fabricated emotion, no hot-path affect
   mutation (the serial owner wires affect).
5. **B — deferred** to a future identity lane (design + denial tests only for now).
6. **C — sensing now** (host-pressure classification, no send); reach-out gated on P11 maturing,
   coma gated on P13 Mindscape.
7. **E2 — after P10** text-participation gates pass.
8. Everything folds into **P14 release soak** with the spine.

Meanwhile the spine's own completion runs as the delegation waves: Wave 0 (Phase 8 RSI closeout,
Codex-owned) → Wave 1 (A Phase 6, B Phase 9, C Phase 11, D Phase 12) → Wave 2/3 dependency+cloud
lanes → Wave 4 release.

## Track E detail — her dedicated VM workspace
Full setup + integration is in `.claude/plans/flickering-meandering-seal.md`. Summary:

- **Engine:** VMware Workstation Pro (free personal). On this laptop's single RTX 3050 4 GB
  laptop GPU, strict-OSS (VirtualBox) can't do Blender/games, Hyper-V GPU-PV is *"laptop NVIDIA
  not supported"*, and VFIO needs a Linux host + collapses on muxless Optimus. VMware's virtual
  DirectX 11/12 is the pragmatic GPU-capable path (recorded tradeoff: not open-source).
- **Guest:** Windows 11 (Clip Studio + VRoid are Windows-only), on the **spinning second HDD**
  (usable with fixed-size VMDK + guest tuning; an SSD is the top future upgrade), **6–8 GB RAM**
  so ≥16 GB stays with host + brain, 3D accel on. VRAM (4 GB) is shared with her brain — sequence
  heavy 3D vs local inference, or cloud-route the brain during creative sessions.
- **Isolation invariant:** her **mind stays on the host** (server + Ollama + memory + Mindscape);
  a VM crash is a workspace outage, not death.
- **Integration foundation (my code, after approval):** guest-side "hands" agent (UI-Automation
  via `uiautomation`/`pywinauto` + SoM/OCR fallback) on a host-only network; host-side `"vm"`
  target evolving `computer.py` into a skill registry; the "watch Alpecca work" stream reusing
  creator-auth + a new `vm_control` capability-lease policy (mirroring `screen_share`).

## Verification per track
- **A:** typing indicator + realistic delay + self-initiated at a natural rate; never instant.
- **D:** locked domain → "haven't learned that"; taught fact → recalled; deep/old fact → hedged,
  **never fabricated**; parent-only unlock; brain-map reflects tier/kind/salience.
- **E:** VM boots from HDD, 3D confirmed, host-only reachable, snapshot restore works, **brain
  still runs on host**; later — host intent → guest UI-Automation action → frame on watch page,
  per-action confirm + `vm_control` lease enforced, guest kill leaves the mind alive.
- **B/C:** second principal reachable; host-pressure high → **one** idempotent ping; unclean
  crash → resume from a persisted coma snapshot.
- **E2:** join VC, speak, listen → transcribe → reply, within P10 gates.
- **All:** `python -m pytest -q tests\test_core.py` + `npm.cmd run house:build` green; Codex WIP
  untouched.

## Cross-references
- Spine authority: `docs/ALPECCA_MASTER_PLAN.md` (phases, statuses, verification matrix).
- Current progress: `HANDOFF.md`.
- Vision source: `docs/ALPECCA_VISION_HANDOFF_FOR_CODEX.md`.
- VM standup detail: `.claude/plans/flickering-meandering-seal.md`.
