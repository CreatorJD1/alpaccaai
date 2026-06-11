"""Long-term memory: store salient moments, retrieve the relevant ones each turn.

A companion that forgets everything between turns feels like a chatbot; one that
remembers feels alive. So after each exchange we decide whether the moment was
*salient* enough to keep, and at the start of each turn we pull back the handful
of memories most relevant to what's happening now.

Retrieval is **semantic by default**: each memory is embedded with a local model
(Ollama `nomic-embed-text`) and recalled by cosine similarity, so "how's the pup"
can surface a memory about "my dog Biscuit" even with no shared words. If no
embedder is available (Ollama not running, model not pulled), we fall back to the
old keyword-overlap score so Alpecca still works offline -- it just recalls a bit
more literally. The `tokens` column is kept for exactly that fallback.

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

from config import DB_PATH, MEMORY_TOP_K, MEMORY_SALIENCE_THRESHOLD

Embedder = Callable[[str], Optional[list]]

_WORD = re.compile(r"[a-z0-9']+")
_STOP = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "is",
    "it", "i", "you", "me", "my", "your", "we", "they", "this", "that", "with",
    "was", "are", "be", "as", "at", "so", "do", "did", "have", "has",
}


def _tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


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


# --- Default embedder: local Ollama, lazily initialized --------------------

_EMBED_MODEL = "nomic-embed-text"
_ollama_client = None
_ollama_ready: Optional[bool] = None  # None = untried, then True/False


def default_embed(text: str) -> Optional[list]:
    """Embed `text` with a local Ollama embedding model, or return None if that
    isn't available. We probe once and remember the result so we don't hammer a
    down server on every call."""
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


@contextmanager
def _connect(db_path: Path):
    """Same close-on-exit pattern as state._connect -- see the note there."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def remember(content: str, kind: str = "episodic", salience: float = 0.5,
             db_path: Path = DB_PATH, embed_fn: Optional[Embedder] = default_embed) -> bool:
    """Store a memory if it clears the salience bar. Returns whether it was kept.

    `salience` is "how much does this matter" in [0, 1]. We don't store every
    passing remark -- only moments worth carrying forward -- which keeps
    retrieval sharp instead of drowning in trivia. We store both a token list
    (for keyword fallback) and, when an embedder is available, a dense vector
    (for semantic recall).
    """
    if salience < MEMORY_SALIENCE_THRESHOLD:
        return False
    tokens = _tokenize(content)
    vec = embed_fn(content) if embed_fn else None
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO memories (ts, kind, content, salience, tokens, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), kind, content, salience, json.dumps(tokens),
             json.dumps(vec) if vec is not None else None),
        )
    return True


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
        else:
            sim = _similarity(q_tokens, json.loads(r["tokens"]))
            floor = 0.0
        if sim <= floor:
            continue
        age_days = (now - r["ts"]) / 86400.0
        recency = 1.0 / (1.0 + age_days)        # 1.0 today, fades with age
        score = 0.6 * sim + 0.3 * r["salience"] + 0.1 * recency
        scored.append((score, dict(r)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:top_k]]


def count(db_path: Path = DB_PATH) -> int:
    """How many memories Alpecca is currently holding -- used by introspection so
    it can truthfully say how much of 'us' it carries."""
    with _connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"]


def recent(limit: int = 10, db_path: Path = DB_PATH) -> list[dict]:
    """Most recent memories regardless of relevance -- useful for a 'what have we
    been up to lately' read."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ts, kind, content, salience FROM memories ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
