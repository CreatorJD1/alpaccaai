# MINDPAGE Roadmap (Layer A design spec)

This document is the experimental implementation guide for bounded context-memory
management and future memory paging.

## Current reality

- Chat remains short-context and deterministic.
- Memory recall today is:
  - live chat: deterministic keyword recall (`embed_fn=None`),
  - background: semantic recall where embeddings are available.

## Planned Layer A behavior (bounded, observable, restart-safe)

1. Token-budget ledger in `mind.py` before each LLM call.
2. On-budget overflow, reclaim components in priority order:
   content outside immediate context first, then older context lines, then musings.
3. `memory` recall becomes O(cap) instead of full scan:
   keep a writable hot memory tier in RAM, bounded recency/salience,
   page less-salient rows to an SQLite-backed warm tier.
4. `MINDPAGE` pages become explicit recall units with metadata and confidence.
5. User and model-visible status from `/mindpage/stats`.

## Constraints kept across all stages

- Only local/open-source components in the core path.
- No behavior can skip existing bounded approvals in `ActionsCfg`/`cognition`.
- No changes to raw user data semantics without explicit schema migration + idempotent
  backfill.
- All background operations use hard time caps and never block chat.

## Deferred implementation

Layer B/C (`llama.cpp` slot persistence + deep local model paging) are not
implemented in this branch; this document remains the design target for a later
pass so the repository keeps the same contract and stays testable.
