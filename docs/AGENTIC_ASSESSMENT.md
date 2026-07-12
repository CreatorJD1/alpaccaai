# Alpecca Agentic Assessment and Staged Upgrade Plan

Last updated: 2026-07-12

## Audit Result

A three-pass audit found that Alpecca is partly agentic, but still heavily
workflow-driven. The current system has real state, memory, sensing, Soul
arbitration, bounded self-review, and tool-calling, but many choice points are
still deterministic or random: Soul rank sorting, random drift gates, hard-coded
living-loop question banks, and arithmetic self-tuning.

The honesty finding is good: Alpecca generally does not lie to the user about
her runtime state. The main false claims were documentation claims, now corrected:

- Chat memory is keyword-first by default; semantic recall only runs when
  embeddings exist and chat semantic recall is explicitly enabled.
- App/files/computer-use reach is opt-in; defaults do not grant broad tools.

Guiding invariant for every stage: bounded code-side caps, deterministic fallback
on parse/model failure, `CognitionObservation` logging for autonomous acts, and
`APPROVAL_ASK_FIRST` proposals for anything beyond Alpecca's own DB/local state.

## Completed In This Branch

- Stage 0: audit docs, archive cleanup, capability framing, and memory docstring
  correction.
- Stage 1: innate local tool registry, `ALPECCA_TOOL_MODE`, tool schema gating,
  and observable tool execution.
- Stage 2: chat-memory embedding backfill, idle server scheduling, and
  `ALPECCA_CHAT_SEMANTIC_RECALL` opt-in.
- Mindpage Layer A initial core: token pressure stats, compressed page table,
  episode writeback on history eviction, `recall_page`, memory indexes, and
  `/mindpage/stats`.
- Stage 3 initial constrained choice points: strict tiny-JSON choice helper,
  living-loop question choice, Soul same-rank tie-breaks, and proactive chatter
  judge/seed choice with deterministic fallback.
- Stage 4: local-only planner, `payload` proposal storage, `make_plan(goal)`,
  and explicit user-approved one-step execution through Workshop proposals.
- Stage 5 initial automation: empty-by-default routines, off-by-default passive
  directory watchers, `/routines` routes, and observation logging.
- Optional local systems downloaded for future stages: llama.cpp b9933
  CPU/CUDA builds, `sqlite-vec==0.1.9`, and isolated `mcp==1.28.1` venv.

Current model note: do not revive retired legacy model paths. Runtime planning
uses the configured local Ollama model from `ALPECCA_MODEL`.

## Current Phase 9 Checkpoint - PARTIAL

Creator-only, server-resolved House text attachments are implemented. A House client
provides only a bounded allowed-root id and relative path; the server resolves
the root, commits the `file_access` capability audit before any read, and passes
the reference through the shared source-perception and attachment-perception
boundary. MIME and SHA-256 are derived locally, provenance is bound to the exact
server-issued turn scope, and the serialized attachment record contains
metadata rather than the file excerpt or raw bytes.

The bounded excerpt is treated as untrusted prompt data. Its turn forces
verified local-only inference and suppresses model tool schemas, so file text
cannot grant authority or trigger a tool call. The legacy raw/base64
`file_name`/`file_data` upload path is retired and rejected. Existing scoped
`source_inspect`, image ingress, and audio ingress retain their previously
documented local-only provenance and validation behavior.

The answer is deliberately ephemeral. Attachment-derived text is not retained
in recent replies, content-bearing history, cognition chat records, Mindpage,
or Mindscape; a redacted omission marker is stored instead. Attachment turns
cannot resolve or create commitments and cannot auto-deliver through OpenClaw.
A follow-up that needs the file must attach it again.

Server-issued expiring capability leases now gate camera frames, screen share,
push-to-talk, voice enrollment, and exact file references. They bind to the
live creator portal and fixed scope/surface/purpose, enforce byte/use/time caps,
stop on disconnect, replacement, expiry, or restart, and persist only HMACs plus
sealed content-free transition evidence. House HQ and the classic app acquire
leases before browser media access; normal text chat is unchanged.

Discord transport authentication is separate from creator authorization. The
bridge receives a service-only credential, `/channel/discord` treats it as
guest transport rather than CreatorJD, and image-bearing bridge requests stay
on loopback until server-side perception routing. Signed per-actor subjects
remain unfinished, so this does not enable guild participation or Discord
autonomy.

All generic image, screen, webcam, pose, self-recognition, ingestion, and Studio
vision wrappers are now verified-local. `VISION_BACKEND`, a cloud model tag, or
the retired Discord cloud flag cannot authorize egress or produce a
creator-approved result. Private provider helpers are dormant until an adapter
can attest every exact provider/deployment/model/location/destination/HTTPS fact
required by the consent ledger. No production remote vision route is live.

A hardened provider/model/deployment-specific egress consent ledger now exists
with exact operation/keyed-payload binding, an external monotonic-anchor contract,
restart revocation, tokenless server consumption, exact sealed schema identity,
and bounded maintenance. It remains a foundation: no perception provider or
interactive creator control is wired to it. A hardened signed Discord guest-
actor core also exists with actual request-byte/event/scope bindings and
structurally guest-only results. Bridge minting and one-use server consumption
are now wired for allowlisted DMs and derive stable opaque guest scopes. A
separate live capability boundary now makes every non-creator turn
reply-only, without tools, commitments, creator continuity, state mutation, or
private telemetry. Validated Discord image context can enter only through an
in-process exact-turn envelope and is not persisted. This closes capability
leakage and establishes signed DM identity, while guest history, guild
participation, rates, approvals, voice, and production anchoring remain
unfinished.
The bridge is therefore hard-locked to allowlisted DMs. Guild/thread input,
proactive participation, recursion, and voice are code-disabled, and all DM
payloads remain guest authority. Actor sealing now has a dedicated protected
credential separate from creator, service, and bot credentials.
Phase 10 Discord participation and voice stay blocked on those boundaries.

## Current Phase 11 Checkpoint - PARTIAL, CORE ONLY

The notification outbox now has a durable model-free state machine with opaque
payload references, frozen route policy, idempotent claims, quiet-hour and quota
deferral, explicit indeterminate delivery, acknowledgements, independent
external monotonic anchoring, exact schema verification, and bounded recovery. This is an
unwired foundation only: it has no destination, transport, credential,
autonomous trigger, callback route, server route, or UI control. No external
notification capability should be inferred from the presence of this module.
Independent follow-up review passes 47 focused tests, including repeated
concurrency cases. The state-machine core is complete; transport remains absent.

The bundled SQLite sidecars are development-only, single-file rollback
detectors. A production path must inject an anchor in a separate failure domain;
co-restoring both local files cannot be detected.

## Stage 3 - LLM-In-The-Loop Choice Points

Add a strict constrained-choice helper:

- `constrained_pick(llm, question, options, context) -> int | None`
- local Ollama fast tier only
- tiny JSON only, for example `{"pick": 2}`
- strip `<think>` wrappers, reject malformed/out-of-range output
- `None` means caller keeps current deterministic fallback

Targets:

- Living-loop questions: one grounded question from room, purpose, recent
  observations, and open-question dedupe; fallback remains the static bank.
- Soul tie-breaks: keep `soul.deliberate()` pure; use the model only when two or
  more intentions tie at the top rank, and only within that rank.
- Proactive chatter: keep cooldowns/eligibility in code; let the model decide
  `{"speak": bool, "pick": N}` among existing seeds. Failure is quiet.

Flags:

- `ALPECCA_LIVING_LLM=1`
- `ALPECCA_SOUL_LLM=1`
- `ALPECCA_PROACTIVE_LLM=1`

Status: implemented for the initial three choice points. Future expansion should
reuse the same parser/helper and keep all safety gates in code.

## Stage 4 - Simple Planner

Add a local-only planner that drafts Workshop proposals, not autonomous actions.

- Add `payload TEXT` to action proposals with guarded migration.
- Add `alpecca/planner.py` with a 5-step cap, strict JSON parse, one retry, and
  honest failure.
- Add `make_plan(goal)` as an innate tool.
- Store each step as an `APPROVAL_ASK_FIRST` proposal.
- Execute a step only after `proposal_decision_allowed(..., approved_by_user=True)`.
- No autonomous chaining.

Flag: `ALPECCA_PLANNER=1`.

Status: implemented. The planner creates proposals only; execution requires the
existing proposal route to accept the step with `approved_by_user=true` and
`execute=true`.

## Stage 5 - Automation

Automation remains empty/off until configured.

- Routines: SQLite schedule table, pure `due(now)`, 60s server poll, kinds mapped
  only to existing safe functions such as recap, greeting, consolidation, and
  embedding backfill.
- Watchers: polling stat scan of `ALPECCA_WATCH_DIRS`; records names/counts only,
  never file contents.
- MCP: parked/stretch. If added, servers default off and exposed actions route
  through ask-first proposals.

Status: routines and watchers are implemented. The routines table ships empty,
and watchers only run when `ALPECCA_WATCH_DIRS` is set. MCP remains parked.

## Stage 6 - Mindpage

Mindpage treats context as RAM and disk as swap. Layer A is software paging and is
safe by default; Layer B/C are experimental.

Layer A:

- Actual-request token budget ledger from `OLLAMA_NUM_CTX`, including prompt,
  tools, attached history, protocol allowance, and output reserve
- Compressed SQLite pages with failure-safe write-before-delete eviction
- Deterministic summaries that preserve questions, decisions, and episode endings
- Bounded automatic pre-fault plus `recall_page(topic)` explicit page faults
- FTS5 lexical candidates unioned with bounded salience/recency memory recall
- Hot/warm/cold page transitions and explicit maintenance/VACUUM hooks
- One measured pressure snapshot routed through prompt, Soul, cognition,
  WebSocket/API status, and House HQ

Implemented 2026-07-09. Remaining Layer A research items are tokenizer-specific
calibration, semantic page embeddings with provenance, hierarchical theme pages,
and scheduling tier maintenance after runtime cadence is measured.

Layer B:

- Optional llama.cpp backend with slot save/restore.
- Off by default because Ollama does not expose slot persistence.

Layer C:

- Pagefile-powered local deep tier using mmap-capable local models.
- Background-only, timeout-capped, never in the normal chat path.

Open-source constraint: new agentic paths use local Ollama/llama.cpp/stdlib or
clearly optional open components. No Claude Agent SDK, Anthropic API, or
proprietary agent framework is required for any new path.

Downloaded optional systems are tracked in `docs/DOWNLOADED_SYSTEMS.md`.

## Verification Contract

For every completed checkpoint:

- `python -m pytest -q tests/test_core.py -q`
- `npm.cmd run house:build`
- Grep edited user-facing text for the locked spelling `Alpecca`
- Keep House HQ 2D art pipeline untouched unless the task explicitly targets it
