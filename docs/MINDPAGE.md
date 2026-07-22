# Mindpage

Last updated: 2026-07-21

Mindpage is Alpecca's bounded local working-memory paging experiment. It treats
the configured model context as working memory and compressed SQLite pages as
swap. This is software paging; it does not claim that Ollama exposes KV-cache
persistence or that Windows pagefile activity is directly sensed.

## Implemented Layer A

### Request budget ledger

- `alpecca/mindpage.py` estimates tokens with a conservative chars/4 heuristic.
- Every chat request is measured from the actual compact system prompt, current
  message, attached history, tool schemas, protocol allowance, and reserved
  response tokens.
- Optional context shrinks deterministically in this order: weakest recalled
  memories/pages, oldest complete chat turns, then musings.
- A second hard fit measures the final formatted request before the LLM call.
- The resulting snapshot reports pressure, component counts, excluded-message
  backlog, turns until likely history eviction, page-store use, and timestamp.

The ledger is an estimate, not tokenizer-perfect accounting. It prevents the
previous error where only raw history length was presented as total context use.

### Page writeback and recall

- Evicted conversation episodes are zlib-compressed in `mindpage_pages`.
- Deterministic summaries preserve the first context, questions, commitments,
  decisions, and final outcome while retaining the full compressed transcript.
- History is removed only after a page write returns a committed page ID. Failed
  writes retain every turn and expose a paging error/backlog in status.
- Automatic pre-fault searches bounded hot/warm page metadata and attaches up to
  320 estimated tokens of labeled summaries/excerpts to a relevant chat turn.
- The `recall_page(topic)` innate tool can explicitly search every tier, fault a
  page back in, and promote it to hot.
- Unrelated page queries return no hit; salience alone is not relevance.

### Long-term recall

- Normal memory recall keeps the bounded salience/recency pool and unions it with
  bounded FTS5 lexical candidates. Old exact memories are therefore reachable
  even when they fall outside the newest/highest-salience 500 rows.
- Mixed-dimension, malformed, or zero embeddings fall back to keyword scoring
  rather than being mislabeled as semantic evidence.
- Embedding backfill performs model calls outside a write transaction, then
  commits the completed batch in a short transaction.

### Grounded pressure sensing

One canonical snapshot is reused by:

- the dedicated factual working-memory prompt block
- `Soul.Snapshot.memory_pressure`
- Reflector's `consolidate working memory` intention
- `cognition_state()["mindpage"]`
- chat/WebSocket reply payloads
- `GET /mindpage/stats`
- the House HQ Working Memory gauge

The prompt explicitly classifies pressure as a runtime limit, not distress,
confusion, consciousness, or an imagined event. When Reflector acts on high
pressure, it now pages old chat history toward a bounded target and records
before/after evidence. Observation consolidation remains a separate operation.

### Tiers and maintenance

- A full page fault promotes a page to `hot`.
- `maintain_pages()` deterministically demotes inactive hot pages to `warm` and
  old warm pages to `cold`, with bounded salience decay and an idempotent cadence
  marker.
- Automatic chat pre-fault excludes cold pages; explicit `recall_page` can search
  them.
- `vacuum()` is an explicit maintenance hook only. It is never run automatically.
- Disk usage reports compressed page payload plus indexed metadata and labels
  that SQLite overhead is excluded. The configured disk budget is observable,
  not a deletion policy; Mindpage never silently deletes pages to enforce it.

## Deferred Work

- Schedule `maintain_pages()` through the empty-by-default routines system after
  operational cadence is measured.
- Optional semantic page search with embedding provenance.
- Hierarchical episode-to-theme summaries and a separate cold archive directory.
- Tokenizer-calibrated estimates per model family.
- Layer B: opt-in llama.cpp slot save/restore. Ollama still does not expose slot
  persistence through this project.
- Layer C: pagefile/mmap-assisted local deep models, background-only and timeout
  capped. No Windows pagefile setting is changed by Layer A.

Optional llama.cpp binaries already present in the workspace are tracked in
`docs/DOWNLOADED_SYSTEMS.md`. They are not activated by this Layer A work.

## Safety Rules

- Local-only persistence; no new cloud dependency.
- No autonomous file, web, account, or code action.
- No LLM call in the chat paging/writeback path.
- No unbounded Python full-table scan per chat turn.
- No conversation deletion before durable page commit.
- No new Soul subagent and no bypass of Soul arbitration.
- No claim of literal consciousness or human memory sensation.

## Laptop Runtime Profile

The unified launcher keeps live local context at 8K and uses an 8 GB Mindpage
budget for compressed, indexed conversational pages. Under pressure, history is
paged toward 55% working-context occupancy before optional background work is
allowed to compete with chat.

Ollama is launched or recovered with one loaded model and one parallel request.
Flash Attention and q8 KV cache are requested to reduce committed memory where
the active model and GPU support them. Windows may back cold pageable model and
KV allocations with the existing pagefile automatically; Alpecca does not force
hot pages out of RAM and does not describe the pagefile as VRAM.
