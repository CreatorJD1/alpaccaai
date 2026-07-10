# Alpecca Current Progress

Last updated: **2026-07-10**

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
- Master Plan Phase 6 Mindpage and resource coordination remains partial and
  active. Phase 6A semantic-negative/orthogonal recall abstention and Phase 6B
  bounded sidecar content-term indexing are implemented and covered by focused
  tests. New pages index after durable commit; legacy pages support idempotent
  bounded backfill; content-only search does not inflate transcript blobs; and
  stats expose index coverage, errors, and capped pages. Legacy content-index
  backfill is idle-scheduled through the optional `backfill` coordinator at a
  300-second default interval. It stays silent and defers under chat, TTS, or
  other optional-work contention without losing its due state. Live-chat
  semantic recall remains disabled by default.
- The next Phase 6 sequence is hard context-overflow refusal/re-measurement,
  then cooperative optional-worker cancellation.
- Discord proactive participation, recursion, and voice remain default-off until
  the Phase 10 identity, scope, and rate-limit gates pass.
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
- `alpecca/creator_contact.py` and `alpecca/system_pressure.py` are untracked WIP
  scaffolds, not live capabilities. The pagefile implementation is not approved
  for activation.

The corrected local compute target is approximately 24 GB DDR5-4800 with an RTX 3050
Laptop GPU (4 GB). The old 34 GB/H100 labels describe optional cloud notebook or
ZeroGPU runtimes only, and those allocations are ephemeral and provider-dependent.

## Document Baseline for this Session

- `docs/AGENTIC_ASSESSMENT.md` is the current systems audit and stage-0 snapshot.
- `docs/MINDPAGE.md` is the Layer A+ target design and constraints.

## Archival Policy

Stale or superseded source docs were archived under
`docs/archive/2026-07-08/` to preserve evidence without treating them as current
behavior. The former internal House HQ page follows the same rule at
`web/archive/house_hq_internal_legacy.html`: it is preserved but not routed.
