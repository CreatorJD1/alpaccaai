# Alpecca Current Progress

Last updated: **2026-07-12**

Use this as the short active status pointer.

This dated checkpoint explicitly supersedes older route, access, and phase
labels retained in historical plans and handoffs.

## Current Runtime and Capability State

- `/house-hq` now serves the **Void Prototype**, with a native categorized
  **Alpecca Systems** center and an orthographic view.
- The old `web/home.html` is archived at
  `web/archive/house_hq_internal_legacy.html` and is no longer routed.
- Loopback access uses trusted-device bootstrap; remote access requires HTTPS
  creator trust. Remote trust establishes a protected Secure, HttpOnly session;
  plain LAN HTTP cannot enroll a creator device.
- Master Plan Phase 4 baseline is complete. Commitment execution is
  creator-only, scope-bound, and limited to read-only `self_status`; closure is
  receipt-backed and replay-protected. Interrupted `running` records close as
  `cancelled` on startup without rerunning, and legacy proposal execution is
  retired.
- Master Plan Phase 5 baseline is complete. Proactive speech, living ticks, and
  routines share one per-scope initiative budget; ignored outreach backs off;
  proactive delivery selects one surface; and confidence-gated cue evidence
  changes response strategy before generation without asserting a feeling.
- Master Plan Phase 8 remains **PARTIAL**. Phase 8A contains the legacy
  `selfmod` autonomous mutation/evaluation path: idle lessons remain evidence
  and create or refresh one bounded creator-review card, but CoreMind does not
  start or evaluate a `selfmod` trial. `proactive.should_chatter` has a
  validated opt-in `chance` override seam. Phase 8B has an **INTERNAL**
  approval-proof-backed `BehaviorTrialController` for only
  `creator-personal` / `chatter_chance`. SQLite enforces at most one active
  `approved` or `running` trial; its runtime-only SQLite override supports
  apply/readback/rollback, automatic expiry rollback, and startup recovery.
  CoreMind consumes the override only after successful recovery. Phase 8C1
  makes the generic ledger retain immutable specs and the
  exact SHA-256 of each raw persisted spec; the behavior controller has a
  creator-only `chatter_chance` binding sidecar, HMAC-sealed in memory with the
  existing protected server authorization secret, and runtime consumption
  requires it. The chatter supplier is read-only and fails closed; recovery-
  gated server maintenance outside `mind_lock` receipts expired or invalid
  runtime records. `GET /behavior-trials/status` is creator-only, read-only,
  `no-store`, and unavailable before recovery. Phase 8C5 adds the one
  creator-only, recovery-gated `POST /behavior-trials/{trial_id}/approve`
  action for an already registered trial. It accepts no browser-supplied proof,
  timestamp, or authorization mechanism: the server derives those facts from
  its protected authorization decision and returns only a sanitized summary.
  Approval is separate from activation. Phase 8C6 adds the one creator-only,
  recovery-gated `POST /behavior-trials/{trial_id}/start` action for an
  approved trial, with an idempotent retry for that same running trial. It
  accepts no browser-supplied runtime values or timestamp;
  server time and the controller's binding, preimage, runtime-readback, and
  one-active-trial checks govern activation. Phase 8C8 adds exactly one
  creator-only, recovery-gated, bodyless proposal-namespaced registration action:
  `POST /behavior-trials/proposals/{proposal_id}/register`. It accepts only a
  server-issued, HMAC-sealed candidate from settled low-response baseline
  evidence, validates a fixed `chatter_chance` / `qualified_response_rate`
  profile, and records registration only. Generic Workshop payloads and generic
  proposal acceptance are not trial provenance; registration, approval, and
  start remain separate creator decisions. There are no generic behavior-trial
  registration, completion, rollback, or mutation routes, and no trial is
  running by default. Phase 8C9 adds the one creator-only, recovery-gated,
  bodyless and query-free `POST /behavior-trials/{trial_id}/review/retain-baseline`
  acknowledgement. It binds one HMAC-sealed receipt to the exact frozen C7
  settlement digests and can record only `retain_baseline`; it cannot issue a
  candidate, approve, start, retry, apply, retune, or otherwise change runtime
  behavior. Status and frozen review expose only sanitized receipt metadata.
  Phase 8C7 runs after outcome expiry and the existing
  off-lock baseline restoration: only a valid planned-expiry rollback with no
  outstanding outcome windows can be sealed into a hashed aggregate settlement.
  A SQLite fence then rejects new trial outcomes. Creator-only `GET
  /behavior-trials/{trial_id}/review` returns that frozen snapshot, while the
  Workshop shows baseline observation and the latest settled review without
  controls that can change behavior. Phase 8C2 now provides the server-owned durable
  `qualified_response_rate` evidence layer: only a typed `chatter` candidate
  with an allowed initiative that is confirmed delivered to the creator's live
  WebSocket/House HQ portal can enter the denominator. The ledger reserves a
  provisional row before send, confirms it only after portal delivery, and
  matches at most one server-authenticated, contentful, non-background creator
  WebSocket turn in the same scope and surface. It retains no message text,
  request identifiers, credentials, or client scores; failed sends are
  cancelled, expired confirmed sends become unanswered, and status exposes
  aggregate baseline/trial evidence only through the existing creator-only,
  read-only, `no-store` endpoint. No trial is currently running, so all current
  outcome evidence is baseline-only. C8 completes the bounded sealed
  proposal-to-trial registration bridge, and C9 completes the separate
  retained-baseline acknowledgement after frozen review. C7 and C9 never change
  behavior from evidence.
  Phase 8C3 now supplies the fixed, pure evaluation contract for a future
  `qualified_response_rate` trial: per-trial aggregate evidence is isolated by
  server-owned trial id and classified only as collecting, awaiting settlement,
  or ready for creator review with an improved/unchanged/worse comparison to
  the immutable spec baseline. It does not start, complete, roll back, or
  otherwise mutate a trial; C4 supplies only the separate dormant attribution
  seam described below.
  Phase 8C4 now wires attribution only: before an eligible proactive dispatch,
  the server read-checks the controller's creator binding, runtime override,
  metric name, and planned end against the same server-owned dispatch timestamp.
  Only a valid running `qualified_response_rate` trial id is attached; recovery
  not ready, a missing/expired/tampered override, or another metric remains
  baseline-only. C4 itself adds no approval, start, completion, mutation, or
  trial-management route; C5 separately adds approval-only and C6 adds only an
  explicit creator start, with a binding-reverified running retry.

  Phase 8C5 now exposes the approval-only action. It is creator-only,
  recovery-gated, and `no-store`; it derives principal, authorization
  mechanism, issuance/expiry, and approval time on the server rather than
  accepting them from the browser. It logs a content-free CognitionObservation
  after durable approval and cannot register, start, complete, roll back, or
  change Alpecca's runtime behavior.

  Phase 8C6 now exposes the separate start-only action. It is creator-only,
  recovery-gated, and `no-store`; it accepts no browser-provided runtime value
  or timestamp and starts only an approved trial. A repeat call for that same
  running trial is idempotent and re-verifies its binding without a duplicate
  audit observation. The controller must verify the creator binding, immutable
  preimage, one-active-trial policy, and runtime readback. It logs a
  content-free CognitionObservation after durable start and cannot approve,
  complete, roll back, or register a trial.

  Phase 8C7 now seals a closed planned-expiry trial only after all attributed
  outcome windows settle. The sealed aggregate evidence and fixed evaluation
  are SHA-256 fingerprinted; a SQLite trigger rejects later trial outcomes. It
  is created off `mind_lock`, logs a content-free settlement observation, and
  never starts, extends, rolls back, or retunes behavior. Creator-only review
  reads the frozen snapshot, and the Workshop renders baseline evidence plus
  the latest settled review with only a separate C9 baseline-retention receipt;
  it has no control that applies or retunes behavior. C8 creates a visible
  sealed candidate only from settled low-response baseline evidence; the
  Workshop keeps plan acceptance, registration, approval, and start as separate
  controls.
- Master Plan Phase 6 Mindpage and resource coordination remains partial and
  active. Phase 6A semantic-negative/orthogonal recall abstention and Phase 6B
  bounded sidecar content-term indexing are implemented and covered by focused
  tests. New pages index after durable commit; legacy pages support idempotent
  bounded backfill; content-only search does not inflate transcript blobs; and
  stats expose index coverage, errors, and capped pages. Legacy content-index
  backfill is idle-scheduled through the optional `backfill` coordinator at a
  300-second default interval. It stays silent and defers under chat, TTS, or
  other optional-work contention without losing its due state. Live-chat
  semantic recall remains disabled by default. Phase 6C refuses a fixed prompt
  overflow before model, tool, streaming, history, or memory work begins and
  returns an honest structured response; anti-repetition retries remeasure their
  expanded prompt and are skipped when they no longer fit. Phase 6D adds
  cooperative cancellation for embedding backfill, Mindpage content-index
  backfill, and routine embedding backfill. Chat or TTS foreground work cancels
  their leases; safe-boundary stops return `cancelled` or `cancel_requested`
  without claiming completion, advancing schedules, or broadcasting activity.
  Active LLM calls, TTS synthesis, reflection, and SQLite `VACUUM` are not
  force-cancelled.
- Phase 6E now provides a read-only `HostResourceSampler`, exposed through
  `GET /system/resources`. Its machine-level host-pressure assessment is
  advisory-only and remains distinct from Mindpage's per-request context
  pressure. Phase 6F consumes only fresh advisory host pressure to defer
  optional maintenance before a coordinator lease. Chat and TTS behavior are
  unchanged, and unknown or unavailable host data allows work. It performs no
  automatic context reduction, pagefile action, configuration change, or system
  action.
- Phase 6G sends the cached shared host assessment to the Soul snapshot as
  separate `host_pressure` evidence. It is assessment-only, excluding raw host
  telemetry and advisory data; unknown, invalid, or unavailable data stays
  `null`. This observation makes no LLM or system call and does not change
  seven-agent Soul deliberation, urgency, or actions.
- Phase 6H adds an execute-only, read-only host preflight to the one-tier
  `scripts\measure_context_tier.py` harness. The default 8,192 dry run still
  uses no sampler and makes no request. On `--execute --tier N`, known high or
  critical host pressure, RAM/commit/disk headroom below fixed thresholds, or a
  low unplugged battery block the run before Ollama with zero HTTP requests.
  Unknown telemetry remains explicit and does not fabricate a block. `--all`
  remains rejected; reports never promote a tier or change configuration,
  pagefile, or system settings.
- On 2026-07-10, a real-machine execute invocation was blocked by critical host
  pressure before any Ollama request. No real `qwen3.5:9b` inference or
  context-tier measurement completed, and no tier was promoted.
- Phase 9 multimodal/source perception is **PARTIAL**. Creator source inspection
  is reachable through the smart tool gate and remains read-only, explicitly
  rooted, creator-only, and verified-local-model-only. Image, screen, push-to-
  talk, and voice-enrollment ingress now fail closed on byte/MIME/container/
  dimension/duration violations, derive SHA-256 server-side, return metadata-
  only scoped provenance, and keep private perception on verified loopback
  Ollama inference. Creator-only, server-resolved House text attachments use
  bounded exact references and remain ephemeral after the live answer. Expiring
  portal-bound leases now gate camera, screen, microphone, voice enrollment,
  and exact file-reference use with fixed caps, disconnect/restart revocation,
  and sealed content-free evidence. Discord bridge authentication now uses a
  separate service-only credential, maps to `guest`, rejects the creator bearer,
  and keeps image-bearing backend requests on loopback. House microphone capture
  auto-stops at 60 seconds and stale work cancels on disconnect. A hardened,
  externally anchored provider/model/deployment-specific egress consent core
  now exists, but no vision/provider call or interactive creator control uses it
  yet. Signed Discord DM actor identity is now wired end to end: exact request
  bytes and Discord event/actor/channel IDs are server-minted, consumed once
  before side effects, and converted to a stable opaque guest scope. Raw IDs do
  not enter payloads, prompts, history, or persisted identity rows. Phase 10
  remains partial for guilds, retained guest context, rates, approvals, voice,
  and a production external anchor.
- Generic public vision is now **verified-local only** across image chat,
  screen/webcam sensing, pose tagging, self-recognition, ingestion, and Studio.
  Backend flags and cloud model tags cannot authorize egress or produce
  creator-approved metadata. Remote provider helpers are dormant because no
  current route can attest every exact deployment/model/location/destination/
  HTTPS fact required by the consent ledger; no production remote vision route
  is live.
- A conversation-only guest boundary is implemented independently of signed
  actor identity. Non-creator turns receive no tools, commitments, creator
  continuity, state mutation, runtime telemetry, Mindpage, cognition, or
  initiative writes. Only a server-created exact-turn envelope can carry a
  validated Discord image description, and image-derived guest turns are not
  retained. Stable opaque actor/thread scope is now implemented for signed DMs;
  retained context, guild participation, approvals, rate limits, and voice remain
  unfinished.
- Discord is now hard-locked to allowlisted DMs. Guild/thread messages have zero
  media/backend effects; proactive participation, recursion, and voice cannot be
  enabled by environment flags. DM bodies always use guest authority. A separate
  protected actor-seal credential is implemented without rotating or revoking
  existing creator, bridge-service, or bot credentials.
- Phase 11 is **PARTIAL, CORE ONLY**. A model-free notification outbox now
  implements opaque payload references, frozen policy registries, idempotent
  enqueue and claims, quiet hours and quotas, explicit indeterminate outcomes,
  acknowledgement/cancellation, an external monotonic-anchor contract, exact schema
  verification, and fixed-batch recovery. It has no adapter, destination,
  credential, autonomous trigger, callback route, server route, or UI wiring;
  no creator-contact channel is live.
  Independent follow-up review passes 47 focused tests, including repeated
  concurrency runs; this completes the model-free core, not delivery.
- The untracked `creator_contact.py` direct-send experiment is **REJECTED WIP**,
  not a Phase 11 implementation. It is currently unimported/inert and locally
  defaults off. Its Web Push/Discord/SMS/OpenClaw calls bypass outbox claims,
  quotas, indeterminate outcomes, and sender-bound acknowledgement, so it must
  not be wired or checkpointed. Future work starts with one dormant Web Push
  adapter behind the reviewed outbox.
- SQLite anchor sidecars are development-only and cannot detect coordinated
  restoration with their main database. Production identity, egress, and outbox
  wiring still requires a separate-failure-domain monotonic anchor.
- Phase 6 remains partial. The next gated action is to clear resources and
  re-run preflight, then separately authorize one 8,192 measurement; no direct
  pagefile mutation is authorized. See `docs/CONTEXT_TIER_MEASUREMENT.md` for
  the Phase 6E-6H contract.
- Discord proactive participation, recursion, and voice remain default-off until
  the Phase 10 identity, scope, and rate-limit gates pass.
- Phase 12 V4 behavior is **PARTIAL** with direct 1.70 m scaling, translation-
  track rejection, post-speech vowel/mood-mouth closure, bounded two-bone
  terminal reach, and expanded runtime telemetry implemented. The model retains
  74 spring joints and 22 colliders. Formal completion still requires the
  ten-minute physics soak, every-terminal contact drill, sole measurements, and
  four-angle design-lock turntable.
- `ALPECCA_TOOL_MODE` is `smart` and `ALPECCA_INNATE_TOOLS=1` in this branch.
- Chat tool-calling is now gated and observable through tool schemas + `CognitionObservation`.
- Embedding backfill now runs in background on idle drift ticks.
- Mindpage Layer A now budgets the actual model request, writes evicted chat
  history only after a durable page commit, automatically pre-faults relevant
  bounded page evidence, and exposes one grounded pressure snapshot through the
  Soul, cognition state, WebSocket replies, `/mindpage/stats`, and House HQ.
- Mindpage content-only retrieval now uses a bounded sidecar index instead of
  inflating transcript blobs during search. New pages are indexed post-commit;
  legacy-page backfill is idle-scheduled through the optional `backfill`
  coordinator at a 300-second default interval. It is silent and preserves its
  due state when chat, TTS, or other optional work has the shared lease.
- Long-term recall now unions its bounded salience/recency pool with FTS5 lexical
  candidates, so an old exact memory does not disappear behind the 500-row pool.
- Page tiers now support hot promotion plus explicit warm/cold maintenance. Disk
  limits are observable and never trigger silent deletion.
- Stage 3 constrained choices now cover living-loop question choice, Soul
  same-rank tie-breaks, and proactive chatter judge/seed choice.
- Master Plan Phase 3 turn transactions and context isolation are complete:
  creator history survives reconnect/restart, portal epochs only fence stale
  transports, House HQ and the app have server-owned surface routes, and
  timeout/cancelled turns cannot commit late replies or tool writes.
- The memory path for live chat remains keyword-first (`embed_fn=None`), now with
  bounded FTS5 lexical retrieval and background semantic backfill support.
  Semantic scoring clamps orthogonal and negative vector matches to zero instead
  of admitting unrelated memories.
- No broader action tool is enabled by the Phase 4 baseline; expanding beyond
  read-only `self_status` requires a separately approved and gated slice.

## Security And Architecture State

A July 9 adversarial audit found that several older diagrams marked features as
done too early. The protected local boundary, creator principal, process
singleton, active portal fencing, and scoped turn transactions now exist. The
following higher-risk features remain held or bounded:

- Remote entry is creator-trust gated; live computer control remains held behind
  its separate security and approval gates.
- The current Alpecca value is intentionally preserved as part of her public
  identity. It appears in House HQ source and generated bundles, so it must not
  be accepted as proof of authorization. Server authorization now uses the
  separate protected secret/session path and ignores the public identity value.
- Commitment approval can execute only the validated read-only `self_status`
  payload in the current creator scope. Replays and broader tools are rejected.
- Future Discord/guest identities remain ephemeral and capability-denied until
  signed bridge subjects and allowlists exist.
- Discord text/media and Mindscape exist as partial adapters, not secure
  autonomous presence.
- `alpecca/system_pressure.py` is now a tested read-only Phase 7 foundation:
  command-free commit/disk measurement and a pure exact-step proposal only. It
  has no pagefile mutation, persistence, approval consumer, elevation, route,
  scheduler, or UI. Execution remains blocked. `alpecca/creator_contact.py`
  remains rejected untracked WIP and is not live.

The corrected local compute target is approximately 24 GB DDR4 with an RTX 3050
Laptop GPU (4 GB). The old 34 GB/H100 labels describe optional cloud notebook or
ZeroGPU runtimes only, and those allocations are ephemeral and provider-dependent.

## Document Baseline for this Session

- `docs/AGENTIC_ASSESSMENT.md` is the current systems audit and stage-0 snapshot.
- `docs/MINDPAGE.md` is the Layer A+ target design and constraints.
- `docs/CONTEXT_TIER_MEASUREMENT.md` records the Phase 6E-6H host-telemetry,
  Soul evidence, optional-maintenance deferral, and context-tier measurement
  boundary.

## Archival Policy

Stale or superseded source docs were archived under
`docs/archive/2026-07-08/` to preserve evidence without treating them as current
behavior. The former internal House HQ page follows the same rule at
`web/archive/house_hq_internal_legacy.html`: it is preserved but not routed.
