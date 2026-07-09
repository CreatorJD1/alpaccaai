"""Long-term memory: store salient moments, retrieve the relevant ones each turn.

A companion that forgets everything between turns feels like a chatbot; one that
remembers feels alive. So after each exchange we decide whether the moment was
*salient* enough to keep, and at the start of each turn we pull back the handful
of memories most relevant to what's happening now.

Retrieval is **semantic when an embedding exists**: memories written with an
embed_fn are embedded with a local model (Ollama `nomic-embed-text`) and recalled
by cosine similarity, so "how's the pup" can surface a memory about "my dog
Biscuit" even with no shared words. Live chat, however, deliberately stores and
recalls with `embed_fn=None` (see mind.py -- keeps the embedding model from
evicting the chat model on small GPUs), so conversational memories are keyword-
only today; only background memories (musings, reflections, recaps) get vectors.
If no embedder is available (Ollama not running, model not pulled), recall falls
back to the keyword-overlap score so Alpecca still works offline -- it just
recalls a bit more literally. The `tokens` column is kept for exactly that
fallback.

Embeddings are pluggable via an `embed_fn(text) -> list[float] | None` argument,
which also makes the retrieval logic testable without a running model.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

from config import (DB_PATH, MEMORY_TOP_K, MEMORY_SALIENCE_THRESHOLD,
                    MEMORY_DEDUP_COSINE, MEMORY_DEDUP_TOKEN)

Embedder = Callable[[str], Optional[list]]
MEMORY_KINDS = {"episodic", "semantic", "relationship", "procedural", "self_model", "musing"}

_WORD = re.compile(r"[a-z0-9']+")
_STOP = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "is",
    "it", "i", "you", "me", "my", "your", "we", "they", "this", "that", "with",
    "was", "are", "be", "as", "at", "so", "do", "did", "have", "has",
}


def _tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


def _exact_phrase_match(query: str, content: str) -> bool:
    query = query.strip().lower()
    if len(query) < 4:
        return False
    pattern = rf"(?<![a-z0-9']){re.escape(query)}(?![a-z0-9'])"
    return re.search(pattern, content.lower()) is not None


def _similarity(a: list[str], b: list[str]) -> float:
    """Jaccard overlap of token sets -- the keyword fallback. Returns 0..1."""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors, mapped from [-1,1] into [0,1] so it
    blends cleanly with the salience/recency terms in recall()."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, (dot / (na * nb) + 1.0) / 2.0))


# --- Default embedder: local Ollama or Hugging Face, lazily initialized -----

_EMBED_MODEL = "nomic-embed-text"
_ollama_client = None
_ollama_ready: Optional[bool] = None  # None = untried, then True/False
_hf_client = None
_hf_ready: Optional[bool] = None


def default_embed(text: str) -> Optional[list]:
    """Embed `text`, or return None if no embedder is available (caller then
    falls back to keyword recall). Backend is chosen by config.EMBED_BACKEND:
    local Ollama by default, or Hugging Face when offloading the GPU. We probe
    once per backend and remember the result so we don't hammer a down service."""
    from config import EMBED_BACKEND
    if EMBED_BACKEND == "hf":
        return _hf_embed(text)
    global _ollama_client, _ollama_ready
    if _ollama_ready is False:
        return None
    try:
        if _ollama_client is None:
            import ollama
            from config import OLLAMA_HOST
            _ollama_client = ollama.Client(host=OLLAMA_HOST)
        resp = _ollama_client.embeddings(model=_EMBED_MODEL, prompt=text)
        _ollama_ready = True
        return list(resp["embedding"])
    except Exception:
        _ollama_ready = False
        return None


def _hf_embed(text: str) -> Optional[list]:
    """Embed via Hugging Face Inference (frees the local GPU). Returns a flat
    list[float]; mean-pools if the model hands back token-level vectors. Any
    failure returns None so recall degrades to keyword matching, never crashes."""
    global _hf_client, _hf_ready
    if _hf_ready is False:
        return None
    try:
        if _hf_client is None:
            from huggingface_hub import InferenceClient
            from config import HF_TOKEN, HF_PROVIDER
            _hf_client = InferenceClient(token=HF_TOKEN or None,
                                         provider=HF_PROVIDER or "auto")
        from config import EMBED_HF_MODEL
        v = _hf_client.feature_extraction(text, model=EMBED_HF_MODEL)
        vec = v.tolist() if hasattr(v, "tolist") else v
        # feature_extraction may return [dim] or [tokens][dim]; mean-pool the latter.
        if vec and isinstance(vec[0], list):
            vec = [sum(col) / len(col) for col in zip(*vec)]
        _hf_ready = True
        return [float(x) for x in vec]
    except Exception:
        _hf_ready = False
        return None


@contextmanager
def _connect(db_path: Path):
    """Same close-on-exit pattern as state._connect -- see the note there."""
    # Delegates to alpecca.db.connect -- the one hardened opener
    # (busy_timeout, commit-on-exit, always-close). See alpecca/db.py.
    from alpecca.db import connect as _db_connect
    with _db_connect(db_path) as conn:
        yield conn


def classify_kind(content: str, source: str = "", fallback: str = "episodic") -> str:
    """Classify a memory into the bucket that best fits how Alpecca should use it.

    The classifier is deliberately conservative and keyword-based. It is not a
    claim that she understands the memory perfectly; it gives retrieval and UI a
    stable structure without spending an LLM call on every little event.
    """
    text = (content or "").lower()
    src = (source or "").lower()
    if fallback in MEMORY_KINDS and fallback not in {"episodic", "musing"}:
        return fallback
    if src in {"soul", "self", "learning"} or any(k in text for k in (
        "i learned something about myself",
        "i tried adjusting my own",
        "my own state",
        "my self",
        "self-design",
        "character sheet",
    )):
        return "self_model"
    if any(k in text for k in (
        "my name is",
        "i'm called",
        "call me",
        "my favorite",
        "my favourite",
        "my mom",
        "my dad",
        "my partner",
        "i love",
        "i hate",
        "important to me",
    )):
        return "relationship"
    if any(k in text for k in (
        "when i",
        "if i",
        "remember to",
        "i need to",
        "we should",
        "next time",
        "the way to",
        "how to",
    )):
        return "procedural"
    if any(k in text for k in (
        " is a ",
        " means ",
        " refers to ",
        " definition ",
        "system uses",
        "project uses",
    )):
        return "semantic"
    return fallback if fallback in MEMORY_KINDS else "episodic"


def remember_with_id(content: str, kind: str = "episodic", salience: float = 0.5,
                     db_path: Path = DB_PATH,
                     embed_fn: Optional[Embedder] = default_embed,
                     source: str = "") -> int | None:
    """Store a memory if it clears the salience bar. Returns its id if kept.

    `salience` is "how much does this matter" in [0, 1]. We don't store every
    passing remark -- only moments worth carrying forward -- which keeps
    retrieval sharp instead of drowning in trivia. We store both a token list
    (for keyword fallback) and, when an embedder is available, a dense vector
    (for semantic recall).
    """
    if salience < MEMORY_SALIENCE_THRESHOLD:
        return None
    kind = classify_kind(content, source=source, fallback=kind)
    tokens = _tokenize(content)
    vec = embed_fn(content) if embed_fn else None
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO memories (ts, kind, content, salience, tokens, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), kind, content, salience, json.dumps(tokens),
             json.dumps(vec) if vec is not None else None),
        )
        return int(cur.lastrowid)


def remember(content: str, kind: str = "episodic", salience: float = 0.5,
             db_path: Path = DB_PATH, embed_fn: Optional[Embedder] = default_embed,
             source: str = "") -> bool:
    """Store a memory if it clears the salience bar. Returns whether it was kept."""
    return remember_with_id(content, kind=kind, salience=salience,
                            db_path=db_path, embed_fn=embed_fn,
                            source=source) is not None


def backfill_embeddings(batch: int = 16, db_path: Path = DB_PATH,
                        embed_fn: Optional[Embedder] = default_embed) -> dict:
    """Embed memories that were stored without a vector (newest first).

    Live chat deliberately writes memories with embed_fn=None so the embedding
    model never competes with the chat model for VRAM mid-turn. This runs in
    idle moments instead, giving those keyword-only memories a dense vector so
    semantic recall can reach them too. Idempotent: only touches NULL-embedding
    rows. If the embedder is unavailable (returns None), the batch aborts
    quietly and leaves every row untouched -- no fake vectors, ever.
    Returns {"embedded": n, "remaining": m} so callers can report honestly.
    """
    embedded = 0
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, content FROM memories WHERE embedding IS NULL "
            "ORDER BY ts DESC LIMIT ?", (int(batch),)
        ).fetchall()
        if embed_fn:
            for mem_id, content in rows:
                vec = embed_fn(content)
                if vec is None:
                    break
                conn.execute("UPDATE memories SET embedding = ? WHERE id = ?",
                             (json.dumps(vec), mem_id))
                embedded += 1
        remaining = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE embedding IS NULL"
        ).fetchone()[0]
    return {"embedded": embedded, "remaining": int(remaining)}


def recall(query: str, top_k: int = MEMORY_TOP_K, db_path: Path = DB_PATH,
           embed_fn: Optional[Embedder] = default_embed) -> list[dict]:
    """Return the `top_k` memories most relevant to `query`.

    Relevance blends a *meaning* score with salience and a mild recency nudge, so
    a vivid recent moment can edge out a stale one -- roughly how human recall
    feels. The meaning score is cosine similarity over embeddings when both the
    query and the memory have one; otherwise it falls back to keyword overlap.
    This means semantic recall kicks in automatically once Ollama is available,
    and degrades gracefully when it isn't.
    """
    q_tokens = _tokenize(query)
    q_vec = embed_fn(query) if embed_fn else None
    q_exact = query.strip().lower()
    now = time.time()
    scored = []
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, ts, kind, content, salience, tokens, embedding FROM memories"
        ).fetchall()
    for r in rows:
        m_vec = json.loads(r["embedding"]) if r["embedding"] else None
        if q_vec is not None and m_vec is not None:
            sim = _cosine(q_vec, m_vec)
            floor = 0.05   # cosine is rarely exactly 0; ignore near-orthogonal
            method = "semantic"
        else:
            sim = _similarity(q_tokens, json.loads(r["tokens"]))
            floor = 0.0
            method = "keyword"
        if q_exact and _exact_phrase_match(q_exact, str(r["content"])):
            sim = max(sim, 1.0)
        if sim <= floor:
            continue
        age_days = (now - r["ts"]) / 86400.0
        recency = 1.0 / (1.0 + age_days)        # 1.0 today, fades with age
        score = 0.6 * sim + 0.3 * r["salience"] + 0.1 * recency
        d = dict(r)
        d["recall_score"] = round(score, 4)
        d["recall_similarity"] = round(sim, 4)
        d["recall_recency"] = round(recency, 4)
        d["recall_method"] = method
        scored.append((score, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return _select_diverse(scored, top_k)


def _is_near_duplicate(a: dict, b: dict) -> bool:
    """Whether two stored memories say essentially the same thing. Measured the
    same way relevance is -- cosine on embeddings when both have one, else token
    overlap -- so the diversity guard matches however recall scored them."""
    a_vec = json.loads(a["embedding"]) if a["embedding"] else None
    b_vec = json.loads(b["embedding"]) if b["embedding"] else None
    if a_vec is not None and b_vec is not None:
        return _cosine(a_vec, b_vec) >= MEMORY_DEDUP_COSINE
    return _similarity(json.loads(a["tokens"]), json.loads(b["tokens"])) >= MEMORY_DEDUP_TOKEN


def _select_diverse(scored: list, top_k: int) -> list[dict]:
    """Take the highest-scoring memories, but skip any that merely echo one already
    chosen -- so the handful she carries into a turn stays varied instead of being
    four phrasings of a single thought. `scored` is pre-sorted best-first, so the
    strongest of a near-duplicate cluster is the one that survives."""
    picked: list[dict] = []
    for _score, m in scored:
        if any(_is_near_duplicate(m, p) for p in picked):
            continue
        picked.append(m)
        if len(picked) >= top_k:
            break
    return picked


def count(db_path: Path = DB_PATH) -> int:
    """How many memories Alpecca is currently holding -- used by introspection so
    it can truthfully say how much of 'us' it carries."""
    with _connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"]


def kind_counts(db_path: Path = DB_PATH) -> dict:
    """Memory totals by class for the Library and cognition view."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT kind, COUNT(*) AS n FROM memories GROUP BY kind ORDER BY kind"
        ).fetchall()
    return {str(r["kind"]): int(r["n"]) for r in rows}


def recent(limit: int = 10, db_path: Path = DB_PATH) -> list[dict]:
    """Most recent memories regardless of relevance -- useful for a 'what have we
    been up to lately' read."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ts, kind, content, salience FROM memories ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
