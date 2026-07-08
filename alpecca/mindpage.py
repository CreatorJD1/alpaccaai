"""Mindpage: bounded software paging for Alpecca's working memory.

Layer A is intentionally small and local-only. It estimates token pressure,
writes evicted chat history into compressed SQLite pages, and exposes enough
stats for the Soul/UI to treat memory pressure as grounded state.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import time
import zlib
from pathlib import Path
from typing import Iterable

from config import DB_PATH, MINDPAGE_DISK_GB, OLLAMA_NUM_CTX

_WORD = re.compile(r"[a-z0-9']+")


def estimate_tokens(text: str) -> int:
    """Cheap model-agnostic token estimate used for budget pressure."""
    if not text:
        return 0
    return max(1, int(math.ceil(len(str(text)) / 4.0)))


def _connect(db_path: Path = DB_PATH):
    from alpecca.db import connect as _db_connect
    return _db_connect(db_path)


def ensure_schema(db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mindpage_pages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL NOT NULL,
                tier         TEXT NOT NULL,
                kind         TEXT NOT NULL,
                topic        TEXT NOT NULL,
                summary      TEXT NOT NULL,
                content_blob BLOB NOT NULL,
                embedding    TEXT,
                token_est    INTEGER NOT NULL,
                last_access  REAL NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0,
                salience     REAL NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mindpage_topic ON mindpage_pages(topic)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mindpage_access ON mindpage_pages(last_access)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mindpage_tier ON mindpage_pages(tier, salience)")


def install_memory_indexes(db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_ts ON memories(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_salience_ts ON memories(salience, ts)")


def turns_to_text(turns: Iterable[dict]) -> str:
    lines = []
    for turn in turns or []:
        role = str((turn or {}).get("role") or "unknown").strip()[:24]
        content = str((turn or {}).get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def summarize_episode(turns: Iterable[dict], max_chars: int = 700) -> str:
    text = turns_to_text(turns)
    if not text:
        return "Empty paged conversation episode."
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return "Summary of paged conversation episode: " + compact
    return "Summary of paged conversation episode: " + compact[: max_chars - 3].rstrip() + "..."


def topic_from_text(text: str, fallback: str = "conversation episode") -> str:
    words = [w for w in _WORD.findall((text or "").lower()) if len(w) > 3]
    seen = []
    for w in words:
        if w not in seen:
            seen.append(w)
        if len(seen) >= 5:
            break
    return " ".join(seen) if seen else fallback


def write_page(*, kind: str, topic: str, summary: str, content: str,
               tier: str = "warm", salience: float = 0.45,
               embedding: list | None = None,
               db_path: Path = DB_PATH) -> int:
    ensure_schema(db_path)
    now = time.time()
    blob = sqlite3.Binary(zlib.compress((content or "").encode("utf-8")))
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO mindpage_pages
                (ts, tier, kind, topic, summary, content_blob, embedding,
                 token_est, last_access, access_count, salience)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                now, tier, kind, topic[:160], summary[:1200], blob,
                json.dumps(embedding) if embedding is not None else None,
                estimate_tokens(content) + estimate_tokens(summary),
                now, float(max(0.0, min(1.0, salience))),
            ),
        )
        return int(cur.lastrowid)


def write_episode_page(turns: list[dict], db_path: Path = DB_PATH) -> int | None:
    content = turns_to_text(turns)
    if not content.strip():
        return None
    summary = summarize_episode(turns)
    return write_page(
        kind="episode",
        topic=topic_from_text(content),
        summary=summary,
        content=content,
        tier="warm",
        salience=0.48,
        db_path=db_path,
    )


def _inflate(blob) -> str:
    raw = bytes(blob or b"")
    try:
        return zlib.decompress(raw).decode("utf-8", errors="replace")
    except Exception:
        return ""


def get_page(page_id: int, db_path: Path = DB_PATH) -> dict | None:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM mindpage_pages WHERE id=?", (int(page_id),)).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE mindpage_pages SET last_access=?, access_count=access_count+1 WHERE id=?",
            (time.time(), int(page_id)),
        )
    d = dict(row)
    d["content"] = _inflate(d.pop("content_blob", b""))
    return d


def recall_page(query: str, limit: int = 3, db_path: Path = DB_PATH) -> list[dict]:
    ensure_schema(db_path)
    q_words = set(_WORD.findall((query or "").lower()))
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM mindpage_pages
            ORDER BY salience DESC, last_access DESC
            LIMIT 80
            """
        ).fetchall()
    scored = []
    for row in rows:
        d = dict(row)
        hay = " ".join([d.get("topic", ""), d.get("summary", "")]).lower()
        words = set(_WORD.findall(hay))
        overlap = len(q_words & words) if q_words else 0
        phrase = 2 if query and query.lower() in hay else 0
        score = phrase + overlap + float(d.get("salience") or 0)
        if score <= 0:
            continue
        d["content"] = _inflate(d.pop("content_blob", b""))
        d["score"] = round(score, 4)
        scored.append((score, d))
    scored.sort(key=lambda item: item[0], reverse=True)
    out = [d for _, d in scored[: max(1, int(limit))]]
    now = time.time()
    if out:
        with _connect(db_path) as conn:
            for d in out:
                conn.execute(
                    "UPDATE mindpage_pages SET last_access=?, access_count=access_count+1 WHERE id=?",
                    (now, int(d["id"])),
                )
    return out


def history_token_estimate(history: list[dict]) -> int:
    return estimate_tokens(turns_to_text(history))


def stats(history: list[dict] | None = None, db_path: Path = DB_PATH,
          num_ctx: int = OLLAMA_NUM_CTX) -> dict:
    ensure_schema(db_path)
    hist_tokens = history_token_estimate(history or [])
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT tier, COUNT(*) AS count, COALESCE(SUM(token_est), 0) AS tokens,
                   COALESCE(SUM(LENGTH(content_blob)), 0) AS bytes
            FROM mindpage_pages GROUP BY tier
            """
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(token_est), 0) AS tokens, "
            "COALESCE(SUM(LENGTH(content_blob)), 0) AS bytes FROM mindpage_pages"
        ).fetchone()
    disk_budget = max(1, int(float(MINDPAGE_DISK_GB) * 1024 * 1024 * 1024))
    page_bytes = int(total["bytes"] or 0) if total else 0
    fill = min(1.0, hist_tokens / max(1, int(num_ctx)))
    return {
        "enabled": True,
        "num_ctx": int(num_ctx),
        "history_tokens": hist_tokens,
        "context_fill": round(fill, 4),
        "pressure": "high" if fill >= 0.9 else "medium" if fill >= 0.75 else "low",
        "page_count": int(total["count"] or 0) if total else 0,
        "page_tokens": int(total["tokens"] or 0) if total else 0,
        "page_bytes": page_bytes,
        "disk_budget_bytes": disk_budget,
        "disk_fill": round(min(1.0, page_bytes / disk_budget), 6),
        "tiers": {str(r["tier"]): {
            "count": int(r["count"] or 0),
            "tokens": int(r["tokens"] or 0),
            "bytes": int(r["bytes"] or 0),
        } for r in rows},
    }


def pressure_snapshot(history: list[dict] | None = None, db_path: Path = DB_PATH) -> dict:
    s = stats(history=history or [], db_path=db_path)
    return {
        "context_fill": s["context_fill"],
        "history_tokens": s["history_tokens"],
        "page_count": s["page_count"],
        "disk_fill": s["disk_fill"],
        "pressure": s["pressure"],
    }
