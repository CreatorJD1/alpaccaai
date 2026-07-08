# Mindpage

Last updated: 2026-07-08

Mindpage is Alpecca's bounded context paging layer. It treats the prompt context
as working memory and disk-backed pages as swap, while keeping all claims honest:
summaries are labeled as summaries, pressure is computed from real counters, and
faulted pages come from local storage.

## Implemented Layer A

- `alpecca/mindpage.py` provides:
  - `estimate_tokens(text)` using a chars/4 heuristic
  - compressed `mindpage_pages` SQLite rows
  - episode writeback for evicted chat history
  - deterministic extractive summaries
  - `recall_page(topic)` retrieval
  - `/mindpage/stats` pressure metrics
- `memory.recall()` now reads from a bounded salience/recency candidate pool.
- Memory indexes are installed idempotently during DB init.
- `Soul.Snapshot` carries `memory_pressure` without adding or bypassing any of
  the seven subagents.
- The innate toolkit exposes `recall_page` as the seventh local tool.

## Current Runtime Behavior

- Chat still sends only the normal rolling history window to the LLM.
- When raw history exceeds the existing cap, the evicted turns are written to a
  compressed Mindpage episode before trimming.
- When pressure is high, a grounded one-line working-memory note can enter the
  prompt; the value is computed, not model-invented.
- `/mindpage/stats` reports context fill, page count, compressed bytes, disk fill,
  and tier counts.

## Deferred Layer B/C

Layer B is optional llama.cpp slot save/restore through a future
`ALPECCA_LLM_BACKEND=llamacpp` path. Ollama remains the default because it does
not expose KV slot persistence.

Layer C is a pagefile-powered local deep tier using mmap-capable open models,
background-only calls, and hard timeouts. It should never run in the normal chat
path.

## Safety Rules

- No cloud dependency.
- No autonomous file/web/code action.
- No unbounded scan in the chat path.
- No silent deletion of evicted conversation context.
- No new subagents; pressure enters through the existing Soul snapshot.
