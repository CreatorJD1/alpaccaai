# Alpecca Current Progress

Last updated: **2026-07-10**

Use this as the short active status pointer.

## Current Runtime and Capability State

- `ALPECCA_TOOL_MODE` is `smart` and `ALPECCA_INNATE_TOOLS=1` in this branch.
- Chat tool-calling is now gated and observable through tool schemas + `CognitionObservation`.
- Embedding backfill now runs in background on idle drift ticks.
- Mindpage Layer A now budgets the actual model request, writes evicted chat
  history only after a durable page commit, automatically pre-faults relevant
  bounded page evidence, and exposes one grounded pressure snapshot through the
  Soul, cognition state, WebSocket replies, `/mindpage/stats`, and House HQ.
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
- Master Plan Phase 4 is partial. Cue parsing, scoped commitments,
  confirmations, state transitions, and receipt-gated completion language are
  present; approved commitments still need a validated, scope-bound execution
  payload and trustworthy tool receipt before the phase can be called done.
- The memory path for live chat remains keyword-first (`embed_fn=None`), now with
  bounded FTS5 lexical retrieval and background semantic backfill support.
- No default behavior changes were made to art pipelines, House HQ animation
  architecture, or model replacement.

## Security And Architecture State

A July 9 adversarial audit found that several older diagrams marked features as
done too early. The protected local boundary, creator principal, process
singleton, active portal fencing, and scoped turn transactions now exist. The
following higher-risk features remain held:

- Public tunnels and live computer control are security-blocked.
- The current Alpecca value is intentionally preserved as part of her public
  identity. It appears in House HQ source and generated bundles, so it must not
  be accepted as proof of authorization. Server authorization now uses the
  separate protected secret/session path and ignores the public identity value.
- Action execution is not enabled merely because a commitment or Workshop item
  was approved; Phase 4 must produce a validated payload and successful receipt.
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
behavior.
