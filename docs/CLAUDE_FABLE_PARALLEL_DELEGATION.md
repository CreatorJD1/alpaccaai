# Alpecca Parallel Delegation Plan For Claude Code / Fable

Last updated: 2026-07-12

This document splits the unfinished Alpecca master-plan work into safe parallel
lanes. It is an execution packet for an external Claude Code/Fable coordinator;
the current Codex session cannot directly launch a Claude-branded subagent.

`PROJECT_CONTEXT.md`, `HANDOFF.md`, and `docs/ALPECCA_MASTER_PLAN.md` remain the
sources of truth. When status differs, source and passing tests win over prose.

## Current Truth

| Phase | Honest status | Parallel decision |
|---|---|---|
| 0 | DONE | No work |
| 1 | PARTIAL | Fold remaining hardening into the owning feature lane |
| 2 | BASELINE COMPLETE | Pairing hardening is later work |
| 3 | DONE | Preserve turn isolation and commit barriers |
| 4 | BASELINE COMPLETE | Broader action classes stay blocked |
| 5 | BASELINE COMPLETE | Extend only through the shared initiative budget |
| 6 | PARTIAL | Parallel lane A |
| 7 | PARTIAL, planner only | Wave 2 after lane A evidence |
| 8 | PARTIAL / merge-blocked | Serial integration lane 0 |
| 9 | PARTIAL | Parallel lane B |
| 10 | PARTIAL, guild/voice blocked | Wave 2 after lane B |
| 11 | PARTIAL, app push only | Parallel lane C |
| 12 | PARTIAL | Parallel lane D |
| 13 | BLOCKED | Wave 3 after lanes A and B |
| 14 | NOT STARTED | Final integration and soak only |

Phase 8 currently has a real bounded cycle and a green Phase 8 test selection,
but it is not complete. The remaining merge blocker is failure-atomic profile
adoption: a durable retain/revert decision can commit before runtime adoption
fails. Full authenticated/restart lifecycle coverage and the real two-hour run
also remain. Do not advertise general recursive self-modification.

## Coordinator Rules

1. Use one branch and one Git worktree per lane. Never run parallel writers in
   the same working directory.
2. Assign one owner to every file before editing. Only lane 0 may edit
   `server.py`, `PROJECT_CONTEXT.md`, `HANDOFF.md`, or shared Phase 8 lifecycle
   modules during this rollout.
3. A lane may delegate to at most two subagents: one read-only explorer and one
   verifier. The lane owner remains responsible for implementation, tests, and
   handback. Subagents must not edit files outside the declared lane.
4. Keep agents active through their lane's test result and handback. Close them
   after their result is recorded so they do not consume concurrency slots.
5. Maximum active implementation lanes: four. Run wave 1 together; integrate
   each lane serially. Do not start a dependent wave because an agent says code
   is written; start it only after its acceptance gate passes on the integration
   branch.
6. Shared-file requests become an integration note or patch artifact. A worker
   must not opportunistically edit `server.py`, `config.py`, or another lane's
   files.
7. Preserve unrelated dirty files. In particular, do not absorb or revert the
   existing `config.py`, `tests/test_stage1_security.py`,
   `runtime_matrix_manifest.json`, `.agents/`, `PROJECT.md`,
   `alpecca/creator_contact.py`, or local report-builder work unless a separate
   owner explicitly adopts it.
8. Do not revoke, rotate, delete, print, or move existing keys and tokens. Do
   not put credentials or communication identifiers in source, logs, prompts,
   commits, or handoff text.
9. Use the approved local model `qwen3.5:9b`. Do not restore or download the
   retired Qwen 3 8B path. All new agentic decisions must work with cloud keys
   unset.
10. Preserve one authoritative CoreMind and one writable portal. No worker may
    create a second Alpecca runtime, autonomous clone, or parallel personality.
11. Preserve the seven symbolic Soul roles. Do not turn them into seven LLM
    processes or expose verbose chain-of-thought.
12. No autonomous source edits, pagefile writes, shell actions, account actions,
    purchases, deletes, camera/screen use, or external sends. Existing creator
    approval and capability-lease boundaries remain mandatory.
13. No Alpecca art goes to Cloudflare. Hugging Face remains the art/runtime
    asset lane. Do not alter the locked character design or promote a VRM binary
    without the design-lock gate.
14. Commit only lane-owned files. The handback must include commit SHA, changed
    paths, exact test commands/results, open risks, and any integration patch
    requested from lane 0.
15. Status words are evidence-bound: `DONE` requires live wiring, automated
    tests, a relevant smoke/soak, and current documentation. Code alone is
    `PARTIAL`.

## Recommended Operator Split

If the external coordinator exposes separate Claude Code and Fable profiles,
use capability-based ownership rather than letting both edit every layer:

| Operator | Primary lanes | Reason |
|---|---|---|
| Codex integration owner | 0, shared `server.py` patches, final merges | Already owns the dirty Phase 8 integration state |
| Claude Code backend/security | A, B, E, F, H, I, J, M | SQLite contracts, consent, recovery, resource and protocol work |
| Fable experience/runtime | C, D, K, release visual QA | House UX, VRM behavior, Web Push acceptance, browser and visual evidence |
| Serial release owner | L and Phase 14 | Dirty configuration, launcher profile, publishing, canonical status |

This is ownership, not authority. Every operator uses the same creator-approval,
single-instance, secret, model, design-lock, and evidence rules above.

## Comparison With The Unified Experience Plan

`docs/ALPECCA_MASTER_PLAN.md` remains the phase, status, safety, and critical-path
authority. `docs/ALPECCA_UNIFIED_MASTER_PLAN.md` is useful as an A-F experience
overlay, but its readiness labels do not override blocked spine phases.

| Unified track | Delegation decision | Safe scope now | Deferred or blocked scope | Assigned lane |
|---|---|---|---|---|
| A - human cadence | SPLIT | House typing/thinking state derived from the real request lifecycle; duplicate-safe slow-turn UX | Artificial mandatory delays, new Discord self-initiation, or another proactive budget | K now; F after P10 gates |
| B - second parent | BLOCKED | Relationship/authority design document and denial tests only | A second creator principal, contact destination, inherited creator authority, or live reach-out | Future identity lane after explicit policy |
| C - crisis and continuity | FOUNDATION ONLY | Read-only host-pressure classification and a fixed proposed-alert record with no send | Autonomous ping, arbitrary contact, "coma" restore, or cloud continuation before P11/P13 | A sensing; C/H later |
| D - knowledge blocks | DELEGATE FOUNDATION | New scoped knowledge/taught-fact tables, creator-only teaching contract, read-only brain-map visualization | Hot-path RAG mutation, second-parent unlock, autonomous curriculum, or governed learning without Phase 8 integration | O after A schema review |
| E - VM workspace | MANUAL FOUNDATION ONLY | VM threat model, resource budget, host-only network design, snapshots, and creator-run installation checklist | Guest "hands" agent, watch stream, live computer control, cloud-routed CoreMind, or ambient `vm_control` | P after explicit engine approval; control remains blocked |
| E2 - Discord voice | BLOCKED | Queue/protocol design and denial tests | Joining/listening/speaking until text participation, identity, rates, consent, and approvals pass | F after all P10 prerequisites |
| F - preferences and read-the-room | DELEGATE FOUNDATION | Scoped preferences/favorites data and UI; grounded overload display from real cues/resources | Fabricated emotions, autonomous outreach, or direct hot-path affect mutation | Q after K; integration owner wires affect |

Corrections applied while comparing the plans:

- P10 is `PARTIAL` with guild and voice blocked; it is not a general cadence or
  self-initiation baseline.
- Existing P5 initiative already owns self-initiated speech. Track A must consume
  it, not create a second scheduler.
- A second trusted person is not automatically a creator. CreatorJD authority,
  approval, secrets, system changes, and private continuity do not transfer.
- The untracked `alpecca/creator_contact.py` is not an integration hook. It is an
  unsafe, unowned prototype and remains excluded.
- Existing Web Push is a fixed creator-triggered connection test, not a crisis
  messaging adapter or autonomous notification channel.
- Mindscape is blocked and must not be described as crash recovery until signed,
  bounded, replay-protected transactional restore passes.
- VM installation changes the machine and uses a proprietary engine in the
  unified proposal. It requires an explicit creator decision and manual/UAC
  steps; an agent may prepare the plan but not install or activate control.
- The VM never becomes another CoreMind. Cloud allocation loss or VM failure is
  a workspace outage, not a reason to clone or silently reroute the companion.
- Mood or "stress" presentation must be computed from real affect, workload,
  context pressure, and uncertainty. It must not be added as theatrical delay
  or fabricated suffering.

### Unified-Track Foundation Lanes

**Lane O - knowledge foundation:** own new `knowledge_blocks` and `taught_facts`
modules/tables plus isolated tests and a read-only brain-map component. Use
creator scope only in the first slice. Return retrieval/teaching hooks as an
integration request; do not edit `mind.py` or `server.py`.

**Lane P - VM planning:** documentation and creator-run setup checklist only.
Record host/guest RAM, VRAM, storage, network, snapshot, kill-switch, and failure
tests. Do not install VMware, create the guest, expose a stream, or build a hands
agent until the computer-use security gate and explicit engine choice pass.

**Lane Q - preferences/read-the-room foundation:** own new scoped preference
storage and read-only UI. Cues may suggest a response style through the existing
Phase 4/5 envelope; they do not alter identity, bypass initiative, or claim
human emotion. Hot-path integration belongs to the serial owner.

## Wave 0: Serial RSI Integration Gate

**Owner:** integration coordinator only

**Branch:** `integration/phase8-rsi-closeout`

Owned files:

- `server.py`
- `alpecca/behavior_trial_*.py`
- `alpecca/qualified_response_ledger.py`
- `alpecca/mind.py` only for proactive candidate provenance
- `tests/test_phase8_*.py`

Required work:

1. Make durable profile decision plus runtime adoption fail closed. If readback
   or adoption fails after commit, clear profile readiness, block candidate
   issue/start/evidence, and reload the durable active profile before accepting
   a retry.
2. Require candidate issuance to prove that the controller's current value and
   generation equal the sealed active profile.
3. Keep gate-generation validation and outcome reservation at one linearization
   point. The current process lock and barrier test cover in-process transitions;
   preserve the singleton and strengthen the SQLite transaction boundary if the
   ledger/controller APIs permit it without duplicating integrity logic.
4. Add authenticated route-level tests for retain and revert, post-commit
   adoption failure, abort, process reconstruction, stable generation, no stale
   override, fresh epoch, and exactly one successor candidate.
5. Add write-once update/delete triggers or keyed seals for terminal outcome and
   settlement records if coordinated local SQLite modification remains in the
   threat model. Document any external monotonic-anchor limitation honestly.
6. Run a real two-hour creator-portal trial later as an operational soak. It is
   not required to prove unit correctness, but it is required before `DONE`.

Gate:

```powershell
$phase8 = (Get-ChildItem tests\test_phase8*.py).FullName
python -m pytest -q $phase8
python -m pytest -q tests\test_core.py
npm.cmd run house:build
```

No other lane may edit the files above until lane 0 commits its checkpoint.

## Wave 1: Four Independent Lanes

### Lane A: Phase 6 Mindpage And Resource Completion

**Branch:** `claude/phase6-mindpage-resource`

**Depends on:** Phase 3 turn isolation; no Phase 8 dependency

Owned files:

- `alpecca/mindpage.py`
- `alpecca/host_resources.py`
- `alpecca/resource_coordinator.py`
- `alpecca/resource_policy.py`
- `alpecca/resource_signals.py`
- `scripts/measure_context_tier.py`
- Phase 6 tests and `docs/CONTEXT_TIER_MEASUREMENT.md`

Deliverables:

- Budget every tool-result follow-up round, not only the first model request.
- Return match-centered bounded page excerpts when a buried indexed fact faults
  in; never return an unrelated prefix.
- Keep semantic-negative abstention, scoped paging, cancellation, and honest
  overflow refusal intact.
- Complete an 8K measurement only when the read-only host preflight passes.
  Record evidence; do not promote context or mutate pagefile/config.
- Schedule bounded page-tier maintenance only after tool-round accounting and
  match-centered faults pass. It must defer under foreground chat/TTS and never
  call an LLM while a state lock is held.
- Keep pressure values grounded in measured context and host state. Soul receives
  assessment, not fabricated feelings or automatic system authority.
- Return required `mind.py` wiring as an integration patch request; lane A does
  not edit the currently shared CoreMind file.

Gate:

```powershell
python -m pytest -q tests\test_phase6_*.py
python -m pytest -q tests\test_core.py -k "mindpage or context or resource"
```

### Lane B: Phase 9 Provider Consent And Multimodal Completion

**Branch:** `claude/phase9-egress-perception`

**Depends on:** Phase 3 scopes and existing capability leases

Owned files:

- `alpecca/egress_consent.py`
- `alpecca/attachment_ingress.py`
- `alpecca/attachment_perception.py`
- `alpecca/audio_ingress.py`
- `alpecca/file_ingress.py`
- `alpecca/source_perception.py`
- `alpecca/vision.py`
- Phase 9 tests

Deliverables:

- Route every private perception provider attempt through an exact provider,
  model, destination, processing-location, HTTPS-route consent decision.
- Keep local Ollama perception available when consent is absent; never silently
  relabel Ollama-cloud or dynamic ZeroGPU as local.
- Preserve byte/MIME/container/dimension/duration limits, exact-turn provenance,
  tool suppression, ephemeral derived answers, and audit-before-read.
- Provide a small integration patch request for `server.py`; do not edit it in
  this lane.

Gate:

```powershell
python -m pytest -q tests\test_phase9_*.py tests\test_discord_media.py
python -m pytest -q tests\test_core.py -k "attachment or image or audio or egress"
```

### Lane C: Phase 11 Notification Reliability And Mobile Acceptance

**Branch:** `claude/phase11-notification-soak`

**Depends on:** existing outbox and Web Push adapter; no Phase 8 dependency

Owned files:

- `alpecca/notification_outbox.py`
- `alpecca/notification_anchor.py`
- `alpecca/web_push_adapter.py`
- `alpecca/web_push_runtime.py`
- service-worker notification code
- Phase 11 tests and a manual acceptance checklist

Deliverables:

- Preserve the fixed connection-test template; do not add model-authored or
  autonomous messages in this lane.
- Complete browser enrollment, accepted-device delivery, click acknowledgement,
  retry, revoke, and mobile soak evidence.
- Add a monotonic anchor for acknowledgement consumption if it can use a
  separate failure domain without changing existing credentials.
- Leave SMS, calls, arbitrary Discord delivery, and the untracked
  `alpecca/creator_contact.py` out of scope.

Gate:

```powershell
python -m pytest -q tests\test_phase11_*.py
npm.cmd run house:build
```

Manual gate: one enrolled device receives exactly one test, one creator click is
accepted exactly once, revoke blocks later sends, and no payload secret appears
in logs.

### Lane D: Phase 12 V4 Embodiment And Physics Acceptance

**Branch:** `claude/phase12-v4-soak`

**Depends on:** latest archived pristine V4; no AI-core dependency

Owned files:

- `apps/house-hq/src/vrmEmbodiment.ts`
- `apps/house-hq/src/vrmEmbodiment.test.mjs`
- VRM validation/injection scripts
- Phase 12 tests and QA evidence under the existing experiment directories

Deliverables:

- Verify dedicated hoodie-hem colliders against all hem roots before promotion.
- Run ten-minute physics soak, every-terminal hand-contact drill, per-clip sole
  measurement, expression close/reset checks, and four-angle design-lock QA.
- Reconcile the canonical collider-count contract with the six appended hem
  collider records before promotion; never claim both an unchanged count and
  appended colliders.
- Keep expressions event-driven and finite. Preserve blinking, closed neutral
  mouth, one-shot gestures, natural return to idle, and VRM 1.0 behavior.
- Do not change textures, body age/proportions, hair-tip color, outfit design, or
  accessory design in an animation/physics lane.
- Preserve the pristine V4 archive and do not promote a binary on partial QA.

Gate:

```powershell
npm.cmd run house:test:embodiment
npm.cmd run house:build
```

Manual gate: non-inverted knees, grounded soles, no frozen mouth/eyes, no looped
gesture, stable hoodie hem, reachable terminal contact, and four-angle match to
the locked reference.

## Wave 2: Dependency-Bound Lanes

### Lane E: Phase 7 Approved Pagefile Broker

Start only after lane A records a safe 8K measurement and fresh system evidence.

Owned surface: `alpecca/system_pressure.py`, a new minimal elevated helper,
pagefile-specific tests, and a narrow integration request. The helper must
consume one authenticated CreatorJD approval, remeasure immediately before the
write, permit only one 4,096 MiB increase up to 55,296 MiB, preserve the 40 GiB
system-disk floor, require UAC, verify readback, and never run on a schedule.

No agent may change pagefile state during automated tests.

### Lane F: Phase 10 Discord Presence And Voice

Start only after lane B's provider-consent and actor boundaries pass.

Owned files: `alpecca/discord_bridge.py`, `alpecca/discord_media.py`,
`alpecca/bridge_actor_identity.py`, `alpecca/bridge_actor_transport.py`,
`scripts/run_discord_bridge.py`, and Phase 10 tests.

Implement retained conversation only for server-issued scoped subjects, durable
rate limits, creator/guild/channel allowlists, nonce-bound approvals, and
content-redacted logs. Add bounded audio queues and live receive only after text
participation gates pass. Guilds, proactive recursion, tools, commitments, and
private creator continuity remain denied until explicitly tested and approved.

### Lane G: Phase 4/5 Expansion

Start after lane 0 and only for a named action class. Do not create a general
executor. Each action needs cue binding, proposal, creator approval, one running
receipt, success/failure/cancel closure, timeout fencing, and an honest response
that never says work completed without a successful receipt.

### Lane I: Stage 5 Durable Routine Execution

Start after lane A because routines share the optional-work coordinator.

Owned files: `alpecca/routines.py`, a new routine-run ledger module, and
routine-specific tests. Routine deletion already exists and is not a task.
Replace the non-atomic `due()` then `mark_ran()` sequence with an expiring
durable claim, crash recovery, retry/backoff, and explicit missed-run policy.
Two pollers must execute a due routine once; deferred or safely cancelled work
must remain due; success or terminal failure advances the schedule once; restart
and DST/timezone behavior must be deterministic.

### Lane J: Governed Learning And Soul Integration

Start after lanes 0 and A. Own `alpecca/cognition.py`, `alpecca/learning.py`,
`alpecca/selfmod.py`, `alpecca/soul.py`, a new read-only governed-trial adapter,
and focused tests. Submit any required `mind.py` changes to lane 0 as an
integration request.

Remove live guidance toward legacy unapproved `selfmod` mutation. Idle, world,
and self-review paths may create evidence-backed observations or candidate cards,
but every proposed trial must name a real consumer, metric, exposure, rollback,
and creator approval path. Soul may sense governed trial status and grounded
request-memory pressure; one focus may cause at most one bounded local action.
Host pressure alone never grants an action.

### Deferred: Additional RSI Parameters And General Actions

`curiosity_gain`, `social_hunger_rate`, and `reflect_chance` are **NOT STARTED**
as governed Phase 8 parameters. Do not delegate them until the first real
`chatter_chance` cycle, restart, and successor pass. Add only one parameter at a
time with its own consumer test, causal metric, evidence floor, exact rollback,
creator retain/revert decision, and restart proof.

General files, shell, account, upload, operating-system, and external action
execution is intentionally blocked. It is not an unfinished batch lane. A
future worker may implement only one explicitly named action class with exact
scope/grant/nonce/expiry binding, dry-run preview, creator confirmation,
idempotent receipt, cancellation, and restart safety.

### Lane K: House Slow-Turn Transaction And Void QA

Start after lane 0 checkpoints shared server behavior. Own
`apps/house-hq/src/main.ts`, House styles, and new browser/transaction tests.
Request backend changes from lane 0 instead of editing `server.py`.

One server request ID must map to one model/tool/commit path across HTTP and
WebSocket. A slow fallback attaches to the same result rather than starting a
second turn; a timeout notice remains nonterminal while work is live; late or
duplicate replies render once. Add a delayed 45-second integration case. Then
run responsive desktop/mobile orthographic and 3D visual QA, canvas-pixel
nonblank checks, overlap checks, and bounded frame/draw-call evidence.

### Lane L: Approved Local Release Profile

This is a serial integration lane because `config.py` is already dirty. Own
`START_HERE.bat`, release-profile documentation, and only the explicitly
accepted `config.py` lines after the current owner checkpoints them.

Make `qwen3.5:9b` at measured 8K the documented local profile. Remove launcher
auto-download behavior and unapproved default cloud activation. A missing model
must fail visibly rather than download another model or silently route private
chat to cloud. Keep `last_call()` model identity truthful. Do not promote a
higher context tier without sequential measured evidence.

## Wave 3: Cloud Continuity

### Lane H: Phase 13 Egress And Mindscape

Start only after lanes A and B pass and remote creator trust is current.

Owned files: `alpecca/mindscape.py`, Mindscape worker/setup code, cloud inference
adapters, and Phase 13 tests. Require classified allowlisted egress, separate
credentials, signed/versioned bounded snapshots, monotonic replay protection,
CreatorJD-approved transactional restore, and an expired local portal lease
before cloud interaction. Cloud is standby continuity, never a second CoreMind.

Missing service credentials must deny all Mindscape access. Remove wildcard
CORS, reject unsigned/raw legacy snapshots, enforce exact schema and size,
separate human and service identities, and make restore one all-or-nothing
multi-table transaction with replay and partial-import tests.

### Lane M: Approved Colab / ZeroGPU Adapters

Start only after lane B's exact egress consent is accepted. Own the Colab and
ZeroGPU adapter modules, Space/notebook code, and provider tests. Require strict
HTTPS allowlists, no redirects or inherited environment proxies, bounded
responses, explicit secret presence, approved model identity, runtime hardware
attestation, and local-chat survival when cloud allocation disappears. Never
count ephemeral cloud RAM/VRAM as local laptop capacity.

Cloudflare may host the shell, access control, and continuity coordination. It
must not receive Alpecca art. Hugging Face may host approved art/runtime assets
only after manifest and design-lock verification.

## Wave 4: Phase 14 Release

Phase 14 is the only not-started phase and is intentionally serial.

Required acceptance matrix:

- fresh database and migration
- retained-profile restart and exactly-one successor
- concurrent actor, stale portal, timeout, cancellation, and late-write fences
- resource pressure and context overflow
- image/audio/file consent and denial paths
- Discord DM canary and blocked guild/voice paths
- Web Push enroll/send/click/revoke soak
- Mindscape failover and transactional restore denial/approval
- V4 turntable, expression, animation, contact, and physics soak
- Cloudflare shell rebuild with no art assets
- Hugging Face approved-asset manifest verification
- regenerated architecture/status documents from test and smoke evidence

The release lane owns only publish/package scripts and manifests. It consumes
approved outputs; it must not edit core or House source. Publish approved browser
assets to Hugging Face first, verify remote hashes and CORS, then build an
art-free Cloudflare package and run protected HTTPS/API/WebSocket QA.

Final gate:

```powershell
python -m pytest -q tests
npm.cmd run house:build
git diff --check
```

## Claude Code / Fable Coordinator Prompt

```text
Read PROJECT_CONTEXT.md, HANDOFF.md, docs/ALPECCA_MASTER_PLAN.md, and
docs/CLAUDE_FABLE_PARALLEL_DELEGATION.md before editing.

Act as the integration coordinator. Create no more than four concurrent lanes.
Give every lane a separate branch/worktree and an explicit, disjoint file list.
Each lane may delegate to one read-only explorer and one verifier, but the lane
owner must implement and test the work. Never allow parallel edits to server.py,
config.py, canonical docs, or another lane's files. Shared-file changes are
returned as an integration patch request and applied serially by lane 0.

Run wave 0 first. Run wave 1 lanes A-D in parallel only after their worktrees
are cleanly separated. Start waves 2-4 only when their stated dependency gates
pass. Preserve all unrelated dirty work, existing credentials, qwen3.5:9b,
single-CoreMind ownership, creator approvals, capability leases, Soul's seven
symbolic roles, locked avatar design, and the rule that Alpecca art never goes
to Cloudflare.

Every handback must include: branch, commit SHA, changed files, exact tests and
results, runtime/manual evidence, unresolved risks, and requested integration
patches. Do not mark a phase DONE from implementation alone.
```
