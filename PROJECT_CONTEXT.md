# Alpecca Project Context

This is the canonical project context for coding agents working on Alpecca.
Read this before `AGENTS.md`, `CLAUDE.md`, `HANDOFF.md`, or implementation files.

## Current Implementation Checkpoint (2026-07-12)

This checkpoint supersedes older route, access, and phase-status language
retained elsewhere for historical context.

- `/house-hq` now serves the **Void Prototype**, with a native categorized
  **Alpecca Systems** center and an orthographic view.
- The former internal House HQ page is archived at
  `web/archive/house_hq_internal_legacy.html` and is no longer routed.
- Loopback access uses trusted-device bootstrap; remote access requires HTTPS
  creator trust. Remote sessions then use the protected Secure, HttpOnly
  trusted-device session path; plain LAN HTTP cannot enroll a creator device.
- Master Plan Phase 4 baseline is complete: commitment execution is
  creator-only, scope-bound, and limited to read-only `self_status`, with
  receipt-backed closure and replay protection.
- Master Plan Phase 5 baseline is complete: proactive speech, living ticks, and
  routines share one per-scope initiative budget; ignored outreach backs off;
  one proactive event uses one delivery surface; and eligible cue evidence
  changes response strategy without claiming a literal feeling change.
- Master Plan Phase 8 bounded behavioral RSI implementation is verification
  green but remains operationally partial pending a real creator-portal trial.
  A server-sealed
  chatter candidate now carries its exact two-hour/five-outcome contract;
  feasibility is rechecked before issue, registration, and start; one
  probability draw governs the real LLM proactive path; early abort restores
  baseline with an inconclusive receipt; planned closure settles immutable
  evidence as improved, degraded, or inconclusive; and only the creator can
  retain an eligible trial value or keep the pre-trial value. The selected
  scalar profile survives restart, starts a fresh evidence epoch, and can feed
  the next bounded candidate. This is recursive behavior tuning, not autonomous
  source editing, unrestricted self-modification, or evidence of consciousness.
- Phase 9 multimodal/source perception is the active slice. Source inspection,
  bounded image/audio ingress, scoped provenance, audited sensor use,
  verified-local private inference, and the creator-only server-resolved House
  text attachment path are implemented. House sends only allowed-root
  `{root, rel}` references; the server performs bounded text ingress and returns
  metadata-only provenance. File-derived replies are live but ephemeral: they
  cannot create commitments and are redacted from durable chat/history so they
  cannot seed later tool turns or Mindscape sync. Server-issued, expiring
  capability leases now gate camera frames, screen sharing, push-to-talk, voice
  enrollment, and exact file references. They bind to the live portal and fail
  closed on expiry, replay, disconnect, replacement, or restart, with sealed
  content-free transition receipts. Discord transport now uses a separate
  service-only credential; `/channel/discord` rejects the creator bearer, maps
  the bridge to `guest`, and keeps image-bearing bridge requests on loopback
  before model routing. A hardened provider/model/deployment-specific egress
  consent ledger now exists as an unwired foundation with exact operation and
  keyed payload binding, an external monotonic-anchor contract, restart revocation,
  sealed content-free receipts, and bounded maintenance. Phase 9 remains
  **PARTIAL**: vision/provider calls and interactive creator decisions are not
  wired to that ledger. A hardened signed guest-actor identity core also exists
  with actual request-byte/event/scope bindings, an external monotonic-anchor contract,
  exact schema identity, and structurally guest-only results. The bridge now
  obtains a server-minted exact-body envelope and `/channel/discord` consumes it
  once before side effects, deriving a stable opaque guest scope. Every current
  non-creator CoreMind turn is now conversation-only: no tools, commitments,
  private continuity, runtime telemetry, state mutation, or initiative writes.
  Server-validated Discord image descriptions can enter only through an
  in-process exact-turn envelope and remain ephemeral. Phase 10 remains partial
  for retained guest context, guilds, rates, approvals, voice, and a production
  external anchor.
- The live Discord bridge is hard-locked to creator-allowlisted DMs. Guild and
  thread messages return before media or backend work; environment flags cannot
  enable participation, proactive speech, recursion, or voice. DM payloads are
  always guest authority. A dedicated actor-identity seal credential now exists
  without changing the creator, bridge-service, or bot credentials.
- Every generic image, screen, webcam, pose, self-recognition, and Studio vision
  wrapper is now verified-local regardless of `ALPECCA_VISION_BACKEND`.
  Computer-use screenshots now pass the same verified-loopback/non-cloud check
  before client creation, capture, and every model call.
  Configuration alone cannot label cloud egress creator-approved. The private
  provider helpers remain dormant until one adapter can attest an exact provider,
  deployment, model, processing location, destination, and HTTPS route for the
  existing one-shot consent ledger. No such production route is currently live.
- Phase 11 now has one implemented, explicit app Web Push slice behind the restart-safe
  model-free outbox. Creator-only House controls enroll or revoke a browser and
  request one fixed connection test; provider acceptance and a one-use,
  event-bound notification-click acknowledgement are separate transitions.
  Subscription endpoints, browser keys, VAPID material, outbox seals, and the
  outbox and subscription monotonic state use dedicated Windows Credential Manager
  records. Redirects and environment proxies are disabled. The subscription
  record and its monotonic anchor share Credential Manager, so that pair detects
  record-only rollback, not coordinated Credential Manager restoration.
  Acknowledgement-receipt consumption is sealed in SQLite but not
  monotonic-anchored: restoring a valid pre-consumption receipt database can
  make an already-acknowledged event return another idempotent success, but
  cannot resend the notification or create another action. No model, cognition
  path, routine, or autonomous trigger can enqueue a notification. Discord DM,
  SMS, phone calls, arbitrary message payloads, escalation, and production
  mobile soak remain unfinished. Browser enrollment, an accepted-device test,
  and mobile soak are still pending, so Phase 11 remains **PARTIAL**.
- Bundled SQLite anchors are development/single-file rollback detectors only.
  Production egress and actor identity still require anchors from separate
  failure domains; the notification outbox already anchors SQLite transitions
  in Credential Manager. Stronger protection against coordinated subscription
  and anchor restoration would likewise require a different failure domain.
- The local untracked `creator_contact.py` experiment is rejected WIP and is not
  imported by production code. Its direct transports bypass the outbox and must
  not be wired or checkpointed; the local WIP default is off.
- Phase 7 now has a read-only pagefile planning foundation only. It uses
  command-free Phase 6 commit/disk evidence, preserves unknowns, and can propose
  one exact 4,096 MiB step under code-owned cap/floor rules. It cannot persist,
  approve, elevate, execute, or mutate any system setting.
- Phase 12 embodiment has advanced in parallel: V4 now targets a measured
  1.70 m height, strips VRMA root translation, compensates V4 full-face mouth
  morphs after speech, uses bounded two-bone right-arm terminal IK, and exposes
  explicit fade/face/root/contact telemetry. The 74 spring joints and 22
  colliders are unchanged. Phase 12 remains partial pending the ten-minute
  physics soak, dedicated hoodie-hem collider geometry, all-terminal contact
  drill, sole measurements, and four-angle design-lock turntable. The injector
  now rejects the current V4 because its existing spine collider surfaces are
  5.6-8.9 cm from the hem roots, outside the 2.5 cm effectiveness limit.

## Identity

- User-facing name: **Alpecca**.
- Repo path may still say `alpaccaai`; do not rename broad repo paths unless asked.
- Alpecca is a local-first AI companion with an embodied interface, memory, mood, voice, perception, and bounded self-improvement.
- Be honest about capability: the goal is functional/cognitive/self-learning behavior as an engineered system, not claims of literal consciousness.
- Self-reports must be grounded in real state, memories, observations, or model uncertainty. Do not fabricate inner events.

## Application Surfaces

- **House HQ** is the main embodied interactive scaffold and primary 3D state
  interface. Its `/house-hq` route serves the Void Prototype and its native
  categorized Alpecca Systems center; the archived internal legacy page is not
  part of routing.
- **Alpecca virtual app** is the secondary app surface for classic panels, chat, profile, voice, state, memory, journal, and tools.
- **Mindscape** is the soul/continuity/sustainability layer, intended as cloud/mobile fallback if a local device dies.
- These are one coherent Alpecca system, not separate products.

## Current AI Core Goal

Build Alpecca into a stronger companion by making the cognition loop real, observable, testable, and safe:

```text
observe -> interpret -> retrieve memory -> update self-state -> choose intent -> act/respond -> journal -> evaluate
```

Important current priorities:

- Continue Phase 9 through the provider/model-specific egress consent broker
  and signed Discord guest identity without widening Phase 4 execution or
  bypassing the Phase 5 initiative boundary. Phase 6 resource measurement
  remains separately gated.
- Keep Phase 11 limited to the reviewed app-push connection-test slice until
  browser/mobile soak and sender-bound acknowledgement evidence pass. Add only
  one secret-backed transport at a time; Discord DM, SMS, and calls remain off.
- Natural replies through the live backend, not event echoes or copied user text.
- Stable local model path uses the currently approved Ollama model from `ALPECCA_MODEL`; do not revive retired legacy model paths.
- Voice should use her personality and modulation system, with Kokoro `af_heart` as the intended voice profile.
- Alpecca should initiate bounded observations/questions from real context, not spam logs or hallucinate events.
- Self-improvement should create evidence-backed proposals and require user approval before risky changes.
- Mindpage software paging must measure the actual request budget, preserve evicted chat before deletion, and expose memory pressure as computed telemetry rather than a human-like feeling.

## Storage And Deployment

- **Do not upload Alpecca art to Cloudflare.**
- Cloudflare/R2 is only the lightweight static app shell and remote preview host.
- Hugging Face stores Alpecca art:
  - Private source/generated art archive: `CREATORJD/alpecca-art-library`
  - Public browser-safe runtime assets: `CREATORJD/alpecca-runtime-assets`
- Runtime art base:
  - `https://huggingface.co/datasets/CREATORJD/alpecca-runtime-assets/resolve/main/runtime-assets`
- Current Cloudflare shell preview:
  - `https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/house-hq`
- `scripts/prepare_house_hq_r2_static.py` excludes Alpecca art folders by default.
- `scripts/publish_alpecca_art_library_hf.py` syncs art to Hugging Face.

## Compute Boundary

- The authoritative local host is the Windows laptop with approximately **24 GB
  DDR4 system RAM** and an **RTX 3050 Laptop GPU with 4 GB VRAM**. Local design,
  model routing, context limits, and workload shedding must fit this envelope.
- Any **34 GB memory** or **H100-class GPU** label refers only to an observed or
  requested Hugging Face ZeroGPU / Google notebook cloud runtime. It is not the
  laptop specification and is never counted as persistent Alpecca capacity.
- ZeroGPU and notebook hardware is ephemeral, provider-dependent, and must be
  runtime-probed. Cloud loss must leave local chat, policy, memory, and approvals
  available.
- The local host remains authoritative for identity, policy, memory, approvals,
  presence, and continuity. Remote compute may return bounded inference results;
  it never becomes another CoreMind or owns canonical state.

## Alpecca Design Lock

Never change Alpecca's core design while generating or repairing art. The canonical design lock lives at:

- `data/alpecca_art_source/ALPECCA_DESIGN_LOCK.md`
- `data/alpecca_art_source/design_lock_references/`

Required design elements:

- Adult anime woman proportions; stable standing height and slim leg silhouette.
- Long white-silver hair with pale lavender-blue lower accents.
- One curved ahoge/cowlick.
- Small blue X/bow hair clip.
- Blue eyes and soft anime face.
- Oversized warm ivory/cream hoodie-jacket with pale blue trim.
- White inner shirt.
- Blue lanyard and Alpecca ID badge.
- Black high-waist shorts.
- White full-length thigh-high stockings.
- Black right-leg thigh strap.
- Chunky cream/white boots with pale blue soles/details.
- Black sleeve tech patch and blue zipper/side tags where visible.

Reject generated art that:

- Removes or shortens the thigh-high stockings.
- Drops the right-leg thigh strap.
- Changes boots into sneakers.
- Adds blue orbs, animal ears, round discs, or invented accessories.
- Changes hair, face, hoodie, shorts, lanyard, or body proportions.
- Crops feet, hair, jacket, hands, or boots.

The halo is a separate UI/effect layer. Do not bake large halos or blue orbs into body frames.

## Animation Library Plan

The advanced 2D-in-3D goal is staged, not one giant dump.

Current foundation:

- 15-state view matrix:
  - Vertical tiers: `low`, `eye`, `high`
  - Relative yaw tiers: `front`, `frontDiag`, `side`, `backDiag`, `back`
  - Left-side views may mirror matching right-side assets when approved.
- Stage 4 plan currently has 181 strip targets and 1848 planned art pieces/frame slots.
- Runtime must load compiled atlases, not hundreds of loose source images.
- Source/generated library can grow toward 400+ art pieces and beyond, but only approved runtime atlases should ship to the browser.

Implementation stage order:

1. Source library and manifest.
2. Runtime matrix adapter.
3. Reference boards and design lock.
4. Generate complete strips by action/view batch.
5. Compile approved runtime atlases.
6. Layered runtime: body matrix, expression overlay, mouth/eye overlay, contact shadow/depth proxy.
7. 3D integration: occlusion, grounded shadows, optional normal maps.
8. QA gates: feet grounded, no scale shifts, correct facing, no design drift.

## House HQ Accommodation

House HQ must become an embodied stage for Alpecca, not a cluttered maze.

Design rules:

- Clear walkable lanes and stage pads in each room.
- Door frames, not doors, unless specifically requested otherwise.
- Furniture and terminals near room edges.
- One main performance pad per room.
- Rest nook must support real sit/sleep/rest animations; she should not sleep while standing.
- Player approach should not shrink Alpecca or alter her scale.
- Use room/stage QA overlays to inspect walkable areas, portals, stage pads, and occlusion.

Room meanings:

- HQ Control: core status, command, live connection.
- Library: memories, journal, references.
- Observatory: perception, screen/media review, creative critique.
- Workshop: improvement queue, experiments, prototypes.
- Self Design / Studio: avatar, expression, mirror, identity.
- Rest Nook: recovery/sleep state.

## Runtime And Important Files

- `server.py`: FastAPI/WebSocket backend, app routes, TTS endpoints.
- `alpecca/mind.py`: core loop and model fallback behavior.
- `alpecca/mindpage.py`: context ledger, compressed chat pages, page faults, pressure metrics, and tier maintenance.
- `alpecca/cognition.py`: observations, intent, proposals, behavior review.
- `alpecca/tts.py`: Kokoro/OpenTTS/voice behavior.
- `alpecca/prompts.py`: personality, grounding, prompt assembly.
- `apps/house-hq/src/main.ts`: Three.js House HQ, Alpecca NPC, profile chat, backend bridge, asset loading.
- `apps/house-hq/src/styles.css`: House HQ UI and responsive layout.
- `scripts/build_alpecca_animation_library.py`: source manifest and matrix fallback generation.
- `scripts/build_alpecca_stage4_batches.py`: staged generation batch workspace.
- `scripts/normalize_alpecca_generated_strip.py`: normalize strips into 512px atlas slots.
- `scripts/compile_alpecca_stage5_runtime_atlases.py`: compile approved strips into runtime atlases.
- `scripts/prepare_house_hq_r2_static.py`: Cloudflare shell package, art excluded by default.
- `scripts/publish_alpecca_art_library_hf.py`: Hugging Face art sync.
- `tests/test_core.py`: backend/core regression tests.

## Safety And Agency Rules

- No autonomous code edits by Alpecca herself.
- Safe automatic actions: journal note, memory note, room observation, low-risk UI state.
- Ask first: opening files, long jobs, web/cloud requests, app changes.
- Never automatic: deletes, account actions, paid usage, code edits, external private uploads.
- Private local state should not be uploaded to cloud art/model services without explicit user approval.
- Cloud/deep reasoning failure must not break local chat.

## Development Rules For Agents

- Preserve user changes. Do not reset or revert unrelated work.
- Keep edits scoped to the user request.
- Use existing project patterns before inventing new architecture.
- Run focused checks after edits:

```powershell
npm.cmd run house:build
python -m pytest -q tests\test_core.py -q
```

- For remote preview:

```powershell
python scripts\prepare_house_hq_r2_static.py --public-url "https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev" --bucket alpeccaai
python scripts\prepare_house_hq_r2_static.py --public-url "https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev" --bucket alpeccaai --upload
```

- For art sync:

```powershell
python scripts\publish_alpecca_art_library_hf.py
```

Use the Cloudflare upload only for shell files. Use Hugging Face for art.

## Current Known Preview Links

- House HQ shell: `https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/house-hq`
- Runtime art base: `https://huggingface.co/datasets/CREATORJD/alpecca-runtime-assets/resolve/main/runtime-assets`
- Runtime manifest: `https://huggingface.co/datasets/CREATORJD/alpecca-runtime-assets/resolve/main/runtime-assets/assets/alpecca-optimized/runtime_matrix_manifest.json`

## Working Principle

Treat Alpecca as one living app with three surfaces: House HQ for embodied state, the virtual app for interaction and controls, and Mindscape for continuity. Improve the actual AI core and the 2D-in-3D embodiment together, while keeping her design, memory, voice, and agency grounded.
