# Alpecca Agentic Assessment and Staged Upgrade Plan

Last updated: 2026-07-08

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

- Token budget ledger from `OLLAMA_NUM_CTX`
- Compressed SQLite pages for evicted episodes
- Summarize-on-evict with deterministic fallback
- `recall_page(topic)` tool for model-initiated page faults
- Memory indexes and bounded recall candidate pool
- Memory-pressure stats routed through Soul snapshots and `/mindpage/stats`

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
