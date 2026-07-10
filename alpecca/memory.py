"""Long-term memory: store salient moments, retrieve the relevant ones each turn.

A companion that forgets everything between turns feels like a chatbot; one that
remembers feels alive. So after each exchange we decide whether the moment was
*salient* enough to keep, and at the start of each turn we pull back the handful
of memories most relevant to what's happening now.

For chat recall, Alpecca calls this as keyword/semantic fallback: if chat is
running with `embed_fn=None` it uses keyword overlap for speed and stability.
Outside chat (for background recall and search), embeddings are used when
available and fallback is to keyword overlap when an embedder is unavailable.
The `tokens` column is always available as the literal fallback path.

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
                    MEMORY_DEDUP_COSINE, MEMORY_DEDUP_TOKEN,
                    MEMORY_RECALL_CANDIDATE_LIMIT)

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
    """Return positive cosine evidence in [0, 1], or zero for invalid input.

    Orthogonal and negatively aligned vectors are not evidence of relevance,
    so they must not receive the positive offset used by a [-1, 1] mapping.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        av = [float(value) for value in a]
        bv = [float(value) for value in b]
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not all(math.isfinite(value) for value in (*av, *bv)):
        return 0.0
    dot = sum(x * y for x, y in zip(av, bv))
    na = math.sqrt(sum(x * x for x in av))
    nb = math.sqrt(sum(y * y for y in bv))
    if na == 0.0 or nb == 0.0:
        return 0.0
    cosine = dot / (na * nb)
    if not math.isfinite(cosine):
        return 0.0
    return max(0.0, min(1.0, cosine))


def _decode_vector(value) -> list[float] | None:
    """Decode a stored vector defensively; malformed/mixed rows use keywords."""
    if not value:
        return None
    try:
        raw = json.loads(value) if isinstance(value, str) else value
        if not isinstance(raw, list) or not raw:
            return None
        vector = [float(item) for item in raw]
        if not all(math.isfinite(item) for item in vector):
            return None
        return vector
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _has_direction(vector: list[float] | None) -> bool:
    """Whether a decoded embedding can supply a meaningful cosine direction."""
    return bool(vector) and any(value != 0.0 for value in vector)


def _decode_tokens(value) -> list[str]:
    try:
        raw = json.loads(value) if isinstance(value, str) else value
        return [str(item) for item in raw] if isinstance(raw, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


# --- Default embedder: local Ollama or Hugging Face, lazily initialized -----

_EMBED_MODEL = "nomic-embed-text"
_ollama_client = None
_ollama_ready: Optional[bool] = None  # None = untried, then True/False
_hf_client = None
_hf_ready: Optional[bool] = None
_fts_ready_paths: set[str] = set()
_scope_ready_paths: set[str] = set()


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


def _memory_scope(value: str) -> str:
    """Keep an actor/scope label bounded before it reaches SQLite."""
    clean = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", str(value or "shared").strip())
    return (clean.strip("-._:") or "shared")[:160]


def ensure_scope_schema(db_path: Path = DB_PATH) -> None:
    """Backfill the Phase 3 memory scope column for old and temporary DBs."""
    key = str(Path(db_path).resolve())
    if key in _scope_ready_paths:
        return
    with _connect(db_path) as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(memories)")}
        if "scope" not in cols:
            conn.execute("ALTER TABLE memories ADD COLUMN scope TEXT NOT NULL DEFAULT 'shared'")
        conn.execute("UPDATE memories SET scope='shared' WHERE scope IS NULL OR trim(scope)='' ")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS memories_scope_salience_idx "
            "ON memories(scope, salience DESC, ts DESC)"
        )
    _scope_ready_paths.add(key)


def ensure_search_index(db_path: Path = DB_PATH) -> bool:
    """Install an FTS5 lexical index and keep it synchronized with memories."""
    cache_key = str(Path(db_path).resolve())
    if cache_key in _fts_ready_paths:
        return True
    try:
        with _connect(db_path) as conn:
            existed = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories_fts'"
            ).fetchone() is not None
            conn.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    content,
                    content='memories',
                    content_rowid='id'
                );
                CREATE TRIGGER IF NOT EXISTS memories_fts_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                END;
                CREATE TRIGGER IF NOT EXISTS memories_fts_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES('delete', old.id, old.content);
                END;
                CREATE TRIGGER IF NOT EXISTS memories_fts_au AFTER UPDATE OF content ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES('delete', old.id, old.content);
                    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                END;
                """
            )
            needs_rebuild = not existed
            sentinel = conn.execute(
                "SELECT id, content FROM memories ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if sentinel and not needs_rebuild:
                tokens = _tokenize(str(sentinel["content"] or ""))
                if tokens:
                    match = conn.execute(
                        "SELECT 1 FROM memories_fts "
                        "WHERE memories_fts MATCH ? AND rowid=? LIMIT 1",
                        (f'"{tokens[0]}"', int(sentinel["id"])),
                    ).fetchone()
                    needs_rebuild = match is None
            if needs_rebuild:
                conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
        _fts_ready_paths.add(cache_key)
        return True
    except sqlite3.OperationalError:
        # Some minimal SQLite builds omit FTS5. Recall still has the bounded
        # salience/recency candidate path in that environment.
        return False


def _lexical_candidates(query_tokens: list[str], *, limit: int,
                        db_path: Path, scopes: tuple[str, ...]) -> list[dict]:
    if not query_tokens or not ensure_search_index(db_path):
        return []
    terms = []
    for token in dict.fromkeys(query_tokens):
        clean = str(token).replace('"', '""')
        if clean:
            terms.append(f'"{clean}"')
    if not terms:
        return []
    expression = " OR ".join(terms[:16])
    try:
        placeholders = ", ".join("?" for _ in scopes)
        with _connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT m.id, m.ts, m.kind, m.content, m.salience, m.tokens, m.embedding, m.scope
                FROM memories_fts
                JOIN memories AS m ON m.id = memories_fts.rowid
                WHERE memories_fts MATCH ? AND m.scope IN (""" + placeholders + """)
                ORDER BY bm25(memories_fts)
                LIMIT ?
                """,
                (expression, *scopes, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        return []


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
                     source: str = "", scope: str = "shared") -> int | None:
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
    scope = _memory_scope(scope)
    tokens = _tokenize(content)
    vec = embed_fn(content) if embed_fn else None
    ensure_scope_schema(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO memories (ts, kind, content, salience, tokens, embedding, scope) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), kind, content, salience, json.dumps(tokens),
             json.dumps(vec) if vec is not None else None, scope),
        )
        return int(cur.lastrowid)


def remember(content: str, kind: str = "episodic", salience: float = 0.5,
             db_path: Path = DB_PATH, embed_fn: Optional[Embedder] = default_embed,
             source: str = "", scope: str = "shared") -> bool:
    """Store a memory if it clears the salience bar. Returns whether it was kept."""
    return remember_with_id(content, kind=kind, salience=salience,
                            db_path=db_path, embed_fn=embed_fn,
                            source=source, scope=scope) is not None


def recall(query: str, top_k: int = MEMORY_TOP_K, db_path: Path = DB_PATH,
           embed_fn: Optional[Embedder] = default_embed, *,
           scope: str = "shared", include_shared: bool = True) -> list[dict]:
    """Return the `top_k` memories most relevant to `query`.

    Relevance blends a *meaning* score with salience and a mild recency nudge, so
    a vivid recent moment can edge out a stale one -- roughly how human recall
    feels. The meaning score is cosine similarity over embeddings when both the
    query and the memory have one; otherwise it falls back to keyword overlap.
    This means semantic recall kicks in automatically once Ollama is available,
    and degrades gracefully when it isn't.
    """
    q_tokens = _tokenize(query)
    q_vec = _decode_vector(embed_fn(query)) if embed_fn else None
    q_exact = query.strip().lower()
    now = time.time()
    scored = []
    requested_scope = _memory_scope(scope)
    scopes = (requested_scope,) if requested_scope == "shared" or not include_shared else (
        requested_scope, "shared",
    )
    ensure_scope_schema(db_path)
    placeholders = ", ".join("?" for _ in scopes)
    with _connect(db_path) as conn:
        base_rows = conn.execute(
            "SELECT id, ts, kind, content, salience, tokens, embedding, scope FROM memories "
            f"WHERE scope IN ({placeholders}) ORDER BY salience DESC, ts DESC LIMIT ?",
            (*scopes, max(int(top_k or 1), int(MEMORY_RECALL_CANDIDATE_LIMIT))),
        ).fetchall()
    rows_by_id = {int(row["id"]): dict(row) for row in base_rows}
    lexical_limit = max(64, min(256, int(MEMORY_RECALL_CANDIDATE_LIMIT)))
    for row in _lexical_candidates(
        q_tokens, limit=lexical_limit, db_path=db_path, scopes=scopes,
    ):
        rows_by_id[int(row["id"])] = row
    rows = list(rows_by_id.values())
    for r in rows:
        m_vec = _decode_vector(r["embedding"])
        valid_semantic_pair = (
            q_vec is not None and m_vec is not None
            and len(q_vec) == len(m_vec)
            and _has_direction(q_vec) and _has_direction(m_vec)
        )
        if valid_semantic_pair:
            sim = _cosine(q_vec, m_vec)
            floor = 0.05   # cosine is rarely exactly 0; ignore near-orthogonal
            method = "semantic"
        else:
            sim = _similarity(q_tokens, _decode_tokens(r["tokens"]))
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


def backfill_embeddings(batch: int = 16, db_path: Path = DB_PATH,
                       embed_fn: Optional[Embedder] = default_embed,
                       cancel_event=None) -> dict[str, int | bool]:
    """Populate `embedding` for memories where it is NULL.

    This is intentionally idempotent: rows with existing embeddings are never
    touched, and each call updates at most ``batch`` NULL rows. If the embedder
    is unavailable or `embed_fn` is `None`, the function exits quietly without
    writes.

    Returns summary counters to support background observability and scheduling.
    When a cooperative ``cancel_event`` is set, returns the counters accumulated
    so far plus ``cancelled: True``. A non-cancelled call retains its original
    four-counter result shape.
    """
    def cancelled() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    scanned = 0
    updated = 0
    skipped = 0
    errors = 0

    def summary(*, was_cancelled: bool = False) -> dict[str, int | bool]:
        result: dict[str, int | bool] = {
            "scanned": scanned,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }
        if was_cancelled:
            result["cancelled"] = True
        return result

    if cancelled():
        return summary(was_cancelled=True)
    if not embed_fn:
        return summary()
    try:
        batch = int(batch)
    except (TypeError, ValueError):
        batch = 16
    if batch < 1:
        batch = 1
    # Probe default embedder once to avoid a full walk when Ollama is offline.
    if embed_fn is default_embed:
        if default_embed("alpecca memory backfill probe") is None:
            if cancelled():
                return summary(was_cancelled=True)
            return summary()
        if cancelled():
            return summary(was_cancelled=True)

    with _connect(db_path) as conn:
        # Read candidates in a short transaction. Embedding calls happen after
        # this connection closes so other writers are never blocked by a model.
        rows = conn.execute(
            "SELECT id, content FROM memories WHERE embedding IS NULL ORDER BY ts LIMIT ?",
            (batch,),
        ).fetchall()
    scanned = len(rows)
    pending = []
    for row in rows:
        if cancelled():
            return summary(was_cancelled=True)
        content = (row["content"] or "").strip()
        if not content:
            skipped += 1
            continue
        try:
            vec = embed_fn(content)
        except Exception:
            if cancelled():
                return summary(was_cancelled=True)
            errors += 1
            break
        if cancelled():
            return summary(was_cancelled=True)
        if vec is None:
            skipped += 1
            continue
        pending.append((json.dumps(vec), int(row["id"])))
    if pending:
        with _connect(db_path) as conn:
            for encoded, memory_id in pending:
                if cancelled():
                    return summary(was_cancelled=True)
                try:
                    conn.execute(
                        "UPDATE memories SET embedding=? WHERE id=? AND embedding IS NULL",
                        (encoded, memory_id),
                    )
                    updated += int(conn.execute("SELECT changes() AS n").fetchone()["n"] or 0)
                except Exception:
                    if cancelled():
                        return summary(was_cancelled=True)
                    errors += 1
    return summary()


def _is_near_duplicate(a: dict, b: dict) -> bool:
    """Whether two stored memories say essentially the same thing. Measured the
    same way relevance is -- cosine on embeddings when both have one, else token
    overlap -- so the diversity guard matches however recall scored them."""
    a_vec = _decode_vector(a["embedding"])
    b_vec = _decode_vector(b["embedding"])
    if a_vec is not None and b_vec is not None and len(a_vec) == len(b_vec):
        return _cosine(a_vec, b_vec) >= MEMORY_DEDUP_COSINE
    return _similarity(_decode_tokens(a["tokens"]), _decode_tokens(b["tokens"])) >= MEMORY_DEDUP_TOKEN


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
