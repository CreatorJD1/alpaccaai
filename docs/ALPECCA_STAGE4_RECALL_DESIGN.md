# Stage 4 — Reliable Local Recall: Implementation Design

Authored 2026-07-10 by Claude Code (read-only design audit, pre-implementation).
Builds on Stage 3 Context Mesh storage (`alpecca/context_mesh.py`, `memory_cards`/
`memory_edges`/`context_capsules`/`recall_receipts` + cards FTS5). The legacy
`memories` reader is the rollback path.

## Verified defects in current recall (`alpecca/memory.py`)

1. **Cosine remap inflates unrelated similarity.** `_cosine` (~L63-73) maps
   `(cos+1)/2`, so orthogonal pairs score 0.5 and sentence-embedding
   "unrelated" pairs land at 0.55-0.72 mapped — above the 0.05 floor, so every
   semantic candidate passes. This is the false-recall source. Fix: raw cosine
   clamped at 0, no affine remap.
2. **Contradiction scoring backwards** — sign-flipped memories still score
   0.0-0.5; no signed handling.
3. **Incomparable scales blended** — mapped-cosine vs Jaccard rows share one
   weight set (0.6/0.3/0.1); not rank-comparable. Fix: reciprocal-rank fusion.
4. **Exact-phrase boost brittle** — whole-query match pins sim=1.0; useless for
   long queries, false-positive for short ones; bypasses ranking.
5. **Candidate pool salience-biased** — top-500-by-salience + <=256 FTS rows;
   no global ANN. Low-salience relevant memories invisible.
6. **Live injection capped at [:2]** — `mind.py` ~L1505 and `prompts.py` ~L259
   slice recalled memories to two; Recall@5 unreachable on the live path.

## Embedding swap (nomic-768 / bge-m3-1024 → bge-small-en-v1.5 384)

Dimension mismatch makes `_cosine` return 0.0 → old rows silently fall back to
keyword recall; `backfill_embeddings` only fills NULLs so stale-dim rows strand
permanently. Migration: add `embed_model`/`embed_dim` provenance columns,
force-re-embed rows where `embed_model != EMBED_MODEL` (idle scheduler, embeds
outside the write transaction), and rebuild the vec index on any dim change.

## sqlite-vec (0.1.9, downloaded, unused)

Load per-connection in `alpecca/db.py connect`; `vec_cards` vec0 virtual table
pinned `float[384]`; KNN lane via `embedding MATCH :qvec`. Brute-force cosine
stays as the extension-unavailable fallback (mirror the FTS5 fallback pattern).

## Router (`alpecca/context_mesh_recall.py`, new)

`recall_router(query, scope, turn_kind, top_k, embed_fn, db_path)`:
lanes `_lane_fts5` / `_lane_vec` / `_lane_entity` / `_lane_temporal` /
`_lane_commitment` → `_rrf_fuse` (k=60) → supersession collapse (edges
`supersedes` win; `valid_to` closes old facts) → contradiction drop (prefer
newer; flag on receipt) → diversity (reuse `_select_diverse` + per-lane caps)
→ abstention (below calibrated raw-cosine floor → return empty, receipt
`abstained=1`) → `_write_receipt` into `recall_receipts`. Scope filter is
mandatory in every lane (zero cross-scope leakage).

Rollback: `ALPECCA_CONTEXT_MESH_RECALL` (default 0) delegates verbatim to
`memory_store.recall()`; router returns the same dict shape
(`recall_score/recall_similarity/recall_method`) so evidence panels are
unchanged. Other flags: `ALPECCA_RECALL_LANES`, `ALPECCA_RECALL_ABSTAIN_FLOOR`,
`ALPECCA_SQLITE_VEC`, `ALPECCA_EMBED_MODEL`/`_DIM`, `ALPECCA_RECALL_TOP_K`
(raises the [:2] live cap).

## Gate criteria → tests (`tests/test_context_mesh_recall.py`, fake embedders)

| Gate | Test |
|---|---|
| Recall@5 >= 90% exact/relationship | seeded corpus, paraphrased queries, top-5 assertion; assert live path no longer truncates to [:2] |
| Recall@5 >= 80% temporal/update | fact + superseding update; head-of-chain returned; superseded excluded for "current", included for history turns |
| False recall <= 5% | orthogonal-negatives → abstention; `_fix_cosine` unit: orthogonal→0.0 not 0.5 |
| Zero cross-scope leakage | same-topic cards in creator vs guest scope; no foreign card_id in any lane or receipt |
| Commitments | open commitment resolves via commitment lane |
| Contradiction | only newer injected; receipt flagged |
| Rollback parity | flag off → byte-identical to legacy recall |
| vec fallback | forced extension failure → brute-force same top-k |

Key files: `alpecca/memory.py` (L63-73, L347-401, L404-471), `alpecca/state.py`
(migration pattern L107-110), `alpecca/mind.py` (L1396-1399, L1505),
`alpecca/prompts.py` (L255-263), `alpecca/db.py`, config knobs.
