"""Mindpage: bounded local paging for Alpecca's working memory.

The live context window is treated as working memory. Older conversation turns
are written to compressed SQLite pages, relevant pages can be faulted back into
a bounded prompt allowance, and every pressure claim comes from a deterministic
request-size estimate rather than model narration.
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

from config import (
    DB_PATH,
    MINDPAGE,
    MINDPAGE_DISK_GB,
    OLLAMA_NUM_CTX,
    OLLAMA_NUM_PREDICT,
)

_WORD = re.compile(r"[a-z0-9']+")
_SUMMARY_MARKERS = re.compile(
    r"\b(remember|decid|agree|plan|promise|will|need|must|prefer|question|next|todo)\w*\b",
    re.I,
)
_STOP_WORDS = {
    "about", "after", "again", "also", "been", "could", "from", "have",
    "into", "just", "more", "that", "their", "there", "these", "they",
    "this", "what", "when", "where", "which", "with", "would", "your",
}

PROTOCOL_TOKEN_RESERVE = 64
PRESSURE_MEDIUM = 0.75
PRESSURE_HIGH = 0.90
DEFAULT_PREFAULT_TOKENS = 320
HOT_TTL_SECONDS = 6 * 60 * 60
WARM_TTL_SECONDS = 30 * 24 * 60 * 60
_page_fts_ready_paths: set[str] = set()


def estimate_tokens(text: str) -> int:
    """Return a conservative, model-agnostic chars/4 token estimate."""
    if not text:
        return 0
    return max(1, int(math.ceil(len(str(text)) / 4.0)))


def truncate_tokens(text: str, max_tokens: int) -> str:
    """Bound text by the same estimate used by the context ledger."""
    value = str(text or "")
    limit = max(0, int(max_tokens))
    if estimate_tokens(value) <= limit:
        return value
    if limit <= 0:
        return ""
    max_chars = max(1, limit * 4)
    marker = " [truncated by Mindpage]"
    if max_chars <= len(marker):
        return value[:max_chars]
    return value[: max_chars - len(marker)].rstrip() + marker


def _connect(db_path: Path = DB_PATH):
    from alpecca.db import connect as _db_connect
    return _db_connect(db_path)


def _scope(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", str(value or "shared").strip())
    return (clean.strip("-._:") or "shared")[:160]


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
                salience     REAL NOT NULL,
                scope        TEXT NOT NULL DEFAULT 'shared'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mindpage_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mindpage_topic ON mindpage_pages(topic)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mindpage_access ON mindpage_pages(last_access)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mindpage_tier ON mindpage_pages(tier, salience)")
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(mindpage_pages)")}
        if "scope" not in cols:
            conn.execute("ALTER TABLE mindpage_pages ADD COLUMN scope TEXT NOT NULL DEFAULT 'shared'")
        conn.execute("UPDATE mindpage_pages SET scope='shared' WHERE scope IS NULL OR trim(scope)='' ")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mindpage_scope_access "
            "ON mindpage_pages(scope, tier, salience DESC, last_access DESC)"
        )
        cache_key = str(Path(db_path).resolve())
        if cache_key not in _page_fts_ready_paths:
            try:
                existed = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mindpage_fts'"
                ).fetchone() is not None
                conn.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS mindpage_fts USING fts5(
                        topic,
                        summary,
                        content='mindpage_pages',
                        content_rowid='id'
                    );
                    CREATE TRIGGER IF NOT EXISTS mindpage_fts_ai AFTER INSERT ON mindpage_pages BEGIN
                        INSERT INTO mindpage_fts(rowid, topic, summary)
                        VALUES (new.id, new.topic, new.summary);
                    END;
                    CREATE TRIGGER IF NOT EXISTS mindpage_fts_ad AFTER DELETE ON mindpage_pages BEGIN
                        INSERT INTO mindpage_fts(mindpage_fts, rowid, topic, summary)
                        VALUES('delete', old.id, old.topic, old.summary);
                    END;
                    CREATE TRIGGER IF NOT EXISTS mindpage_fts_au
                    AFTER UPDATE OF topic, summary ON mindpage_pages BEGIN
                        INSERT INTO mindpage_fts(mindpage_fts, rowid, topic, summary)
                        VALUES('delete', old.id, old.topic, old.summary);
                        INSERT INTO mindpage_fts(rowid, topic, summary)
                        VALUES (new.id, new.topic, new.summary);
                    END;
                    """
                )
                needs_rebuild = not existed
                sentinel = conn.execute(
                    "SELECT id, topic, summary FROM mindpage_pages ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if sentinel and not needs_rebuild:
                    words = _query_words(
                        f"{sentinel['topic'] or ''} {sentinel['summary'] or ''}"
                    )
                    if words:
                        match = conn.execute(
                            "SELECT 1 FROM mindpage_fts "
                            "WHERE mindpage_fts MATCH ? AND rowid=? LIMIT 1",
                            (f'"{sorted(words)[0]}"', int(sentinel["id"])),
                        ).fetchone()
                        needs_rebuild = match is None
                if needs_rebuild:
                    conn.execute("INSERT INTO mindpage_fts(mindpage_fts) VALUES('rebuild')")
                _page_fts_ready_paths.add(cache_key)
            except sqlite3.OperationalError:
                pass


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


def _unique_lines(lines: Iterable[str]) -> list[str]:
    out = []
    seen = set()
    for line in lines:
        clean = " ".join(str(line or "").split())
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            out.append(clean)
    return out


def summarize_episode(turns: Iterable[dict], max_chars: int = 700) -> str:
    """Create a deterministic summary while preserving outcomes and questions."""
    lines = [line for line in turns_to_text(turns).splitlines() if line.strip()]
    if not lines:
        return "Empty paged conversation episode."
    important = [line for line in lines if "?" in line or _SUMMARY_MARKERS.search(line)]
    selected = _unique_lines([*lines[:1], *important[:5], *lines[-3:]])
    selected = [truncate_tokens(line, 40) for line in selected]
    compact = " | ".join(selected)
    prefix = "Summary of paged conversation episode: "
    if len(prefix) + len(compact) <= max_chars:
        return prefix + compact
    return prefix + compact[: max(0, max_chars - len(prefix) - 3)].rstrip() + "..."


def topic_from_text(text: str, fallback: str = "conversation episode") -> str:
    words = [
        w for w in _WORD.findall((text or "").lower())
        if len(w) > 3 and w not in _STOP_WORDS
    ]
    seen = []
    for word in words:
        if word not in seen:
            seen.append(word)
        if len(seen) >= 5:
            break
    return " ".join(seen) if seen else fallback


def write_page(*, kind: str, topic: str, summary: str, content: str,
               tier: str = "warm", salience: float = 0.45,
               embedding: list | None = None,
               scope: str = "shared",
               db_path: Path = DB_PATH) -> int:
    if not MINDPAGE:
        return 0
    ensure_schema(db_path)
    now = time.time()
    page_tier = tier if tier in {"hot", "warm", "cold"} else "warm"
    blob = sqlite3.Binary(zlib.compress((content or "").encode("utf-8")))
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO mindpage_pages
                (ts, tier, kind, topic, summary, content_blob, embedding,
                 token_est, last_access, access_count, salience, scope)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                now, page_tier, kind, topic[:160], summary[:1200], blob,
                json.dumps(embedding) if embedding is not None else None,
                estimate_tokens(content) + estimate_tokens(summary),
                now, float(max(0.0, min(1.0, salience))), _scope(scope),
            ),
        )
        return int(cur.lastrowid)


def write_episode_page(turns: list[dict], *, scope: str = "shared",
                       db_path: Path = DB_PATH) -> int | None:
    if not MINDPAGE:
        return None
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
        scope=scope,
        db_path=db_path,
    )


def _inflate(blob) -> str:
    raw = bytes(blob or b"")
    try:
        return zlib.decompress(raw).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _query_words(text: str) -> set[str]:
    return {
        word for word in _WORD.findall((text or "").lower())
        if len(word) > 2 and word not in _STOP_WORDS
    }


def search_pages(query: str, limit: int = 5, *, include_cold: bool = False,
                 scope: str = "shared", include_shared: bool = True,
                 db_path: Path = DB_PATH) -> list[dict]:
    """Search bounded page metadata without inflating stored transcripts."""
    if not MINDPAGE or not str(query or "").strip():
        return []
    ensure_schema(db_path)
    q_text = " ".join(str(query).lower().split())
    q_words = _query_words(q_text)
    if not q_words:
        return []
    requested_scope = _scope(scope)
    scopes = (requested_scope,) if requested_scope == "shared" or not include_shared else (
        requested_scope, "shared",
    )
    placeholders = ", ".join("?" for _ in scopes)
    cold_where = "" if include_cold else " AND tier != 'cold'"
    where = f"WHERE scope IN ({placeholders}){cold_where}"
    terms = " OR ".join(f'"{word}"' for word in sorted(q_words)[:16])
    with _connect(db_path) as conn:
        base_rows = conn.execute(
            f"""
            SELECT id, ts, tier, kind, topic, summary, token_est, last_access,
                    access_count, salience, scope
            FROM mindpage_pages
            {where}
            ORDER BY salience DESC, last_access DESC
            LIMIT 120
            """
            , scopes
        ).fetchall()
        fts_rows = []
        if terms:
            cold_clause = "" if include_cold else "AND p.tier != 'cold'"
            try:
                fts_rows = conn.execute(
                    f"""
                    SELECT p.id, p.ts, p.tier, p.kind, p.topic, p.summary,
                           p.token_est, p.last_access, p.access_count, p.salience, p.scope
                    FROM mindpage_fts
                    JOIN mindpage_pages AS p ON p.id = mindpage_fts.rowid
                    WHERE mindpage_fts MATCH ? AND p.scope IN ({placeholders}) {cold_clause}
                    ORDER BY bm25(mindpage_fts)
                    LIMIT 120
                    """,
                    (terms, *scopes),
                ).fetchall()
            except sqlite3.OperationalError:
                fts_rows = []
    rows_by_id = {int(row["id"]): row for row in base_rows}
    for row in fts_rows:
        rows_by_id[int(row["id"])] = row
    scored = []
    for row in rows_by_id.values():
        item = dict(row)
        hay = " ".join([item.get("topic", ""), item.get("summary", "")]).lower()
        overlap = len(q_words & _query_words(hay))
        phrase = bool(q_text and len(q_text) >= 5 and q_text in hay)
        if not overlap and not phrase:
            continue
        score = (3.0 if phrase else 0.0) + overlap * 1.25 + float(item.get("salience") or 0)
        item["score"] = round(score, 4)
        item["overlap"] = overlap
        item["phrase_match"] = phrase
        scored.append((score, float(item.get("last_access") or 0), item))
    scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
    return [item for _, _, item in scored[: max(1, int(limit))]]


def fault_page(page_id: int, *, max_tokens: int = 1000,
               scope: str = "shared", include_shared: bool = True,
               db_path: Path = DB_PATH) -> dict | None:
    """Inflate one page, promote it to hot, and bound returned content."""
    if not MINDPAGE:
        return None
    ensure_schema(db_path)
    requested_scope = _scope(scope)
    scopes = (requested_scope,) if requested_scope == "shared" or not include_shared else (
        requested_scope, "shared",
    )
    placeholders = ", ".join("?" for _ in scopes)
    with _connect(db_path) as conn:
        row = conn.execute(
            f"SELECT * FROM mindpage_pages WHERE id=? AND scope IN ({placeholders})",
            (int(page_id), *scopes),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            """
            UPDATE mindpage_pages
            SET tier='hot', last_access=?, access_count=access_count+1
            WHERE id=?
            """,
            (time.time(), int(page_id)),
        )
    item = dict(row)
    item["tier"] = "hot"
    item["content"] = truncate_tokens(_inflate(item.pop("content_blob", b"")), max_tokens)
    return item


def get_page(page_id: int, db_path: Path = DB_PATH, *, scope: str = "shared",
             include_shared: bool = True) -> dict | None:
    return fault_page(
        page_id, max_tokens=1_000_000, scope=scope,
        include_shared=include_shared, db_path=db_path,
    )


def recall_page(query: str, limit: int = 3, db_path: Path = DB_PATH, *,
                scope: str = "shared", include_shared: bool = True) -> list[dict]:
    """Explicit page fault across every tier, including cold pages."""
    hits = search_pages(
        query, limit=limit, include_cold=True, scope=scope,
        include_shared=include_shared, db_path=db_path,
    )
    out = []
    for hit in hits:
        page = fault_page(
            int(hit["id"]), max_tokens=1000, scope=scope,
            include_shared=include_shared, db_path=db_path,
        )
        if page:
            page["score"] = hit.get("score")
            page["overlap"] = hit.get("overlap")
            page["phrase_match"] = hit.get("phrase_match")
            out.append(page)
    return out


def prefault_pages(query: str, *, token_budget: int = DEFAULT_PREFAULT_TOKENS,
                   limit: int = 2, scope: str = "shared",
                   include_shared: bool = True,
                   db_path: Path = DB_PATH) -> list[dict]:
    """Fault relevant hot/warm pages into a strict per-turn token allowance."""
    budget = max(0, int(token_budget))
    if not MINDPAGE or budget <= 0:
        return []
    candidates = search_pages(
        query, limit=max(1, int(limit)), include_cold=False, scope=scope,
        include_shared=include_shared, db_path=db_path,
    )
    selected = []
    remaining = budget
    for candidate in candidates:
        if remaining < 24:
            break
        # Reserve room for the summary and labels; a stronger match receives a
        # larger excerpt, but no page can consume the whole per-turn allowance.
        per_page = min(remaining, max(80, budget // max(1, int(limit))))
        page = fault_page(
            int(candidate["id"]), max_tokens=max(24, per_page - 40), scope=scope,
            include_shared=include_shared, db_path=db_path,
        )
        if not page:
            continue
        summary = str(page.get("summary") or "")
        content = str(page.get("content") or "")
        evidence = (
            f"Page {page['id']} ({page.get('topic', 'conversation')}), labeled summary: "
            f"{summary}\nBounded page excerpt: {content}"
        )
        evidence = truncate_tokens(evidence, per_page)
        used = estimate_tokens(evidence)
        if used <= 0 or used > remaining:
            continue
        page["score"] = candidate.get("score")
        page["overlap"] = candidate.get("overlap")
        page["phrase_match"] = candidate.get("phrase_match")
        page["evidence_text"] = evidence
        selected.append(page)
        remaining -= used
    return selected


def history_token_estimate(history: list[dict]) -> int:
    return estimate_tokens(turns_to_text(history))


def _tools_token_estimate(tools) -> int:
    if not tools:
        return 0
    try:
        value = json.dumps(tools, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        value = str(tools)
    return estimate_tokens(value)


def _history_groups(history: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    current: list[dict] = []
    for message in history or []:
        role = str((message or {}).get("role") or "")
        if role == "user" and current:
            groups.append(current)
            current = []
        current.append(message)
    if current:
        groups.append(current)
    return groups


def _pressure_band(fill: float) -> str:
    if fill >= PRESSURE_HIGH:
        return "high"
    if fill >= PRESSURE_MEDIUM:
        return "medium"
    return "low"


def _ledger(*, fixed_tokens: int, memory_tokens: int, history_tokens: int,
            musing_tokens: int, tool_tokens: int, output_reserve: int,
            protocol_reserve: int, num_ctx: int, history_messages: int,
            dropped_memory_items: int = 0, dropped_history_messages: int = 0,
            dropped_history_tokens: int = 0, dropped_musing_items: int = 0,
            prefault_page_count: int = 0) -> dict:
    total = (
        fixed_tokens + memory_tokens + history_tokens + musing_tokens + tool_tokens
        + output_reserve + protocol_reserve
    )
    context_limit = max(1, int(num_ctx))
    minimum_required = fixed_tokens + tool_tokens + output_reserve + protocol_reserve
    context_fits = total <= context_limit
    fixed_overflow = minimum_required > context_limit
    if context_fits:
        fit_status = "fit"
    elif fixed_overflow:
        fit_status = "fixed_overflow"
    else:
        fit_status = "overflow"
    fill = min(1.0, total / context_limit)
    input_budget = max(0, context_limit - output_reserve - protocol_reserve)
    input_tokens = fixed_tokens + memory_tokens + history_tokens + musing_tokens + tool_tokens
    average_message = max(1, history_tokens // max(1, history_messages))
    remaining_input = max(0, input_budget - input_tokens)
    turns_until_eviction = (
        remaining_input // max(1, average_message * 2)
        if history_messages > 0 else None
    )
    return {
        "enabled": bool(MINDPAGE),
        "source": "estimated_request",
        "measured_at": round(time.time(), 3),
        "num_ctx": context_limit,
        "input_budget_tokens": input_budget,
        "input_tokens": input_tokens,
        "output_reserve_tokens": output_reserve,
        "protocol_reserve_tokens": protocol_reserve,
        "total_tokens": min(context_limit, total),
        "estimated_tokens_before_hard_limit": total,
        "required_context_tokens": total,
        "minimum_required_tokens": minimum_required,
        "overflow_tokens": max(0, total - context_limit),
        "fixed_overflow_tokens": max(0, minimum_required - context_limit),
        "context_fits": context_fits,
        "fit_status": fit_status,
        "overflow": not context_fits,
        "fixed_overflow": fixed_overflow,
        "unshrinkable": fixed_overflow,
        "context_fill": round(fill, 4),
        "pressure_score": round(fill, 4),
        "pressure": _pressure_band(fill),
        "history_tokens": history_tokens,
        "history_messages": history_messages,
        "turns_until_history_eviction": turns_until_eviction,
        "unsummarized_eviction_backlog": max(0, int(dropped_history_messages)),
        "prefault_page_count": max(0, int(prefault_page_count)),
        "dropped_memory_items": max(0, int(dropped_memory_items)),
        "dropped_history_messages": max(0, int(dropped_history_messages)),
        "dropped_history_tokens": max(0, int(dropped_history_tokens)),
        "dropped_musing_items": max(0, int(dropped_musing_items)),
        "breakdown": {
            "fixed": fixed_tokens,
            "memories": memory_tokens,
            "history": history_tokens,
            "musings": musing_tokens,
            "tools": tool_tokens,
            "output_reserve": output_reserve,
            "protocol_reserve": protocol_reserve,
        },
    }


def fit_context(*, fixed_texts: Iterable[str], memories: list[str],
                history: list[dict], musings: list[str], tools=None,
                num_ctx: int = OLLAMA_NUM_CTX,
                output_reserve: int = OLLAMA_NUM_PREDICT,
                protocol_reserve: int = PROTOCOL_TOKEN_RESERVE,
                prefault_page_count: int = 0) -> dict:
    """Fit optional context in the declared shrink order.

    Memory evidence is removed first, then the oldest complete history groups,
    then musings. Fixed prompt scaffolding, the current message, tool schemas,
    and the output reserve are never silently removed here.
    """
    fixed = [str(value or "") for value in fixed_texts or []]
    kept_memories = list(memories or [])
    kept_groups = _history_groups(list(history or []))
    kept_musings = list(musings or [])
    fixed_tokens = sum(estimate_tokens(value) for value in fixed)
    tool_tokens = _tools_token_estimate(tools)
    output = max(0, min(int(output_reserve), max(0, int(num_ctx) - 1)))
    protocol = max(0, min(int(protocol_reserve), max(0, int(num_ctx) - output)))
    dropped_memory = 0
    dropped_history: list[dict] = []
    dropped_musings = 0

    def token_total() -> int:
        return (
            fixed_tokens
            + sum(estimate_tokens(value) for value in kept_memories)
            + sum(history_token_estimate(group) for group in kept_groups)
            + sum(estimate_tokens(value) for value in kept_musings)
            + tool_tokens + output + protocol
        )

    while token_total() > max(1, int(num_ctx)) and kept_memories:
        kept_memories.pop()
        dropped_memory += 1
    while token_total() > max(1, int(num_ctx)) and kept_groups:
        dropped_history.extend(kept_groups.pop(0))
    while token_total() > max(1, int(num_ctx)) and kept_musings:
        kept_musings.pop()
        dropped_musings += 1

    kept_history = [message for group in kept_groups for message in group]
    memory_tokens = sum(estimate_tokens(value) for value in kept_memories)
    history_tokens = history_token_estimate(kept_history)
    musing_tokens = sum(estimate_tokens(value) for value in kept_musings)
    snapshot = _ledger(
        fixed_tokens=fixed_tokens,
        memory_tokens=memory_tokens,
        history_tokens=history_tokens,
        musing_tokens=musing_tokens,
        tool_tokens=tool_tokens,
        output_reserve=output,
        protocol_reserve=protocol,
        num_ctx=num_ctx,
        history_messages=len(kept_history),
        dropped_memory_items=dropped_memory,
        dropped_history_messages=len(dropped_history),
        dropped_history_tokens=history_token_estimate(dropped_history),
        dropped_musing_items=dropped_musings,
        prefault_page_count=min(prefault_page_count, len(kept_memories)),
    )
    return {
        "memories": kept_memories,
        "history": kept_history,
        "musings": kept_musings,
        "dropped_history": dropped_history,
        "snapshot": snapshot,
    }


def fit_request(system_prompt: str, user_message: str, history: list[dict],
                tools=None, *, num_ctx: int = OLLAMA_NUM_CTX,
                output_reserve: int = OLLAMA_NUM_PREDICT,
                protocol_reserve: int = PROTOCOL_TOKEN_RESERVE) -> tuple[list[dict], dict]:
    """Hard final fit against the exact request passed to the LLM wrapper."""
    groups = _history_groups(list(history or []))
    fixed_tokens = estimate_tokens(system_prompt) + estimate_tokens(user_message)
    tool_tokens = _tools_token_estimate(tools)
    output = max(0, min(int(output_reserve), max(0, int(num_ctx) - 1)))
    protocol = max(0, min(int(protocol_reserve), max(0, int(num_ctx) - output)))
    allowed_history = max(
        0,
        int(num_ctx) - fixed_tokens - tool_tokens - output - protocol,
    )
    selected_reversed = []
    selected_tokens = 0
    for group in reversed(groups):
        group_tokens = history_token_estimate(group)
        if selected_tokens + group_tokens > allowed_history:
            break
        selected_reversed.append(group)
        selected_tokens += group_tokens
    selected_groups = list(reversed(selected_reversed))
    selected = [message for group in selected_groups for message in group]
    dropped_group_count = max(0, len(groups) - len(selected_groups))
    dropped = [message for group in groups[:dropped_group_count] for message in group]
    snapshot = _ledger(
        fixed_tokens=fixed_tokens,
        memory_tokens=0,
        history_tokens=history_token_estimate(selected),
        musing_tokens=0,
        tool_tokens=tool_tokens,
        output_reserve=output,
        protocol_reserve=protocol,
        num_ctx=num_ctx,
        history_messages=len(selected),
        dropped_history_messages=len(dropped),
        dropped_history_tokens=history_token_estimate(dropped),
    )
    return selected, snapshot


def select_history_for_page(history: list[dict], snapshot: dict,
                            target_fill: float = 0.72,
                            min_keep_messages: int = 4) -> tuple[list[dict], list[dict]]:
    """Choose oldest complete turns that would lower a measured request target."""
    current = list(history or [])
    if len(current) <= max(0, int(min_keep_messages)):
        return [], current
    num_ctx = max(1, int((snapshot or {}).get("num_ctx") or OLLAMA_NUM_CTX))
    total = int((snapshot or {}).get("estimated_tokens_before_hard_limit") or 0)
    target_tokens = int(num_ctx * max(0.1, min(0.95, float(target_fill))))
    needed = max(0, total - target_tokens)
    if needed <= 0:
        return [], current
    attached_count = max(
        0,
        min(len(current), int((snapshot or {}).get("history_messages") or 0)),
    )
    if attached_count <= max(0, int(min_keep_messages)):
        return [], current
    attached_start = len(current) - attached_count
    groups = _history_groups(current)
    evicted: list[dict] = []
    attached_removed_tokens = 0
    consumed_messages = 0
    while groups and attached_removed_tokens < needed:
        remaining_messages = sum(len(group) for group in groups)
        if remaining_messages <= max(0, int(min_keep_messages)):
            break
        group = groups.pop(0)
        evicted.extend(group)
        group_start = consumed_messages
        group_end = consumed_messages + len(group)
        if group_end > attached_start:
            overlap_start = max(0, attached_start - group_start)
            attached_removed_tokens += history_token_estimate(group[overlap_start:])
        consumed_messages = group_end
    remaining = [message for group in groups for message in group]
    return evicted, remaining


def adjust_pressure_after_paging(snapshot: dict, attached_evicted: list[dict]) -> dict:
    """Estimate post-page pressure using only messages attached to the request."""
    result = dict(snapshot or {})
    removed_tokens = history_token_estimate(attached_evicted)
    removed_messages = len(attached_evicted or [])
    if removed_tokens <= 0:
        return result
    result["source"] = "estimated_after_page"
    result["measured_at"] = round(time.time(), 3)
    result["history_tokens"] = max(0, int(result.get("history_tokens") or 0) - removed_tokens)
    result["history_messages"] = max(
        0, int(result.get("history_messages") or 0) - removed_messages
    )
    result["input_tokens"] = max(0, int(result.get("input_tokens") or 0) - removed_tokens)
    total_before = int(result.get("estimated_tokens_before_hard_limit") or 0)
    total_after = max(0, total_before - removed_tokens)
    num_ctx = max(1, int(result.get("num_ctx") or OLLAMA_NUM_CTX))
    result["estimated_tokens_before_hard_limit"] = total_after
    result["total_tokens"] = min(num_ctx, total_after)
    fill = min(1.0, total_after / num_ctx)
    result["context_fill"] = round(fill, 4)
    result["pressure_score"] = round(fill, 4)
    result["pressure"] = _pressure_band(fill)
    result["overflow"] = total_after > num_ctx
    result["unsummarized_eviction_backlog"] = max(
        0,
        int(result.get("unsummarized_eviction_backlog") or 0) - removed_messages,
    )
    breakdown = dict(result.get("breakdown") or {})
    if breakdown:
        breakdown["history"] = max(0, int(breakdown.get("history") or 0) - removed_tokens)
        result["breakdown"] = breakdown
    history_messages = int(result.get("history_messages") or 0)
    history_tokens = int(result.get("history_tokens") or 0)
    remaining_input = max(
        0,
        int(result.get("input_budget_tokens") or 0) - int(result.get("input_tokens") or 0),
    )
    if history_messages > 0:
        average_message = max(1, history_tokens // history_messages)
        result["turns_until_history_eviction"] = (
            remaining_input // max(1, average_message * 2)
        )
    else:
        result["turns_until_history_eviction"] = None
    return result


def maintain_pages(*, db_path: Path = DB_PATH, now: float | None = None,
                   force: bool = False, min_interval_s: float = 3600.0,
                   decay: float = 0.995, batch: int = 500) -> dict:
    """Idempotently decay salience and demote inactive pages in bounded batches."""
    if not MINDPAGE:
        return {"ran": False, "updated": 0, "hot_to_warm": 0, "warm_to_cold": 0}
    ensure_schema(db_path)
    stamp = float(now if now is not None else time.time())
    with _connect(db_path) as conn:
        meta = conn.execute(
            "SELECT value FROM mindpage_meta WHERE key='last_maintenance'"
        ).fetchone()
        last = float(meta["value"]) if meta else 0.0
        if not force and stamp - last < max(0.0, float(min_interval_s)):
            return {"ran": False, "updated": 0, "hot_to_warm": 0, "warm_to_cold": 0}
        rows = conn.execute(
            """
            SELECT id, tier, last_access, salience
            FROM mindpage_pages
            ORDER BY last_access ASC
            LIMIT ?
            """,
            (max(1, int(batch)),),
        ).fetchall()
        hot_to_warm = 0
        warm_to_cold = 0
        updated = 0
        for row in rows:
            age = max(0.0, stamp - float(row["last_access"] or 0.0))
            old_tier = str(row["tier"] or "warm")
            new_tier = old_tier
            if old_tier == "hot" and age >= HOT_TTL_SECONDS:
                new_tier = "warm"
                hot_to_warm += 1
            if new_tier == "warm" and age >= WARM_TTL_SECONDS:
                new_tier = "cold"
                warm_to_cold += 1
            new_salience = max(0.05, min(1.0, float(row["salience"] or 0.0) * float(decay)))
            conn.execute(
                "UPDATE mindpage_pages SET tier=?, salience=? WHERE id=?",
                (new_tier, new_salience, int(row["id"])),
            )
            updated += 1
        conn.execute(
            """
            INSERT INTO mindpage_meta(key, value) VALUES('last_maintenance', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(stamp),),
        )
    return {
        "ran": True,
        "updated": updated,
        "hot_to_warm": hot_to_warm,
        "warm_to_cold": warm_to_cold,
    }


def vacuum(db_path: Path = DB_PATH) -> bool:
    """Run explicit database compaction outside any caller transaction."""
    if not MINDPAGE:
        return False
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute("VACUUM")
    return True


def _page_stats(db_path: Path) -> dict:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT tier, COUNT(*) AS count, COALESCE(SUM(token_est), 0) AS tokens,
                   COALESCE(SUM(
                       LENGTH(content_blob) + LENGTH(topic) + LENGTH(summary)
                       + COALESCE(LENGTH(embedding), 0)
                   ), 0) AS bytes
            FROM mindpage_pages GROUP BY tier
            """
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(token_est), 0) AS tokens, "
            "COALESCE(SUM(LENGTH(content_blob) + LENGTH(topic) + LENGTH(summary) "
            "+ COALESCE(LENGTH(embedding), 0)), 0) AS bytes FROM mindpage_pages"
        ).fetchone()
    disk_budget = max(1, int(float(MINDPAGE_DISK_GB) * 1024 * 1024 * 1024))
    page_bytes = int(total["bytes"] or 0) if total else 0
    tiers = {
        str(row["tier"]): {
            "count": int(row["count"] or 0),
            "tokens": int(row["tokens"] or 0),
            "bytes": int(row["bytes"] or 0),
        }
        for row in rows
    }
    hot = tiers.get("hot", {"count": 0, "tokens": 0, "bytes": 0})
    return {
        "page_count": int(total["count"] or 0) if total else 0,
        "page_tokens": int(total["tokens"] or 0) if total else 0,
        "page_bytes": page_bytes,
        "page_payload_bytes": page_bytes,
        "storage_measurement": "compressed page payload plus indexed metadata; SQLite overhead excluded",
        "hot_page_count": int(hot.get("count") or 0),
        "hot_page_tokens": int(hot.get("tokens") or 0),
        "hot_page_bytes": int(hot.get("bytes") or 0),
        "disk_budget_bytes": disk_budget,
        "disk_fill": round(min(1.0, page_bytes / disk_budget), 6),
        "disk_over_budget": page_bytes > disk_budget,
        "tiers": tiers,
    }


def stats(history: list[dict] | None = None, db_path: Path = DB_PATH,
          num_ctx: int = OLLAMA_NUM_CTX, ledger: dict | None = None) -> dict:
    """Return the canonical request pressure plus durable page-store metrics."""
    if not MINDPAGE:
        return {
            "enabled": False,
            "source": "disabled",
            "num_ctx": int(num_ctx),
            "context_fill": 0.0,
            "pressure_score": 0.0,
            "pressure": "unavailable",
            "page_count": 0,
            "disk_fill": 0.0,
            "tiers": {},
        }
    if ledger is None:
        raw_history = list(history or [])
        ledger = _ledger(
            fixed_tokens=0,
            memory_tokens=0,
            history_tokens=history_token_estimate(raw_history),
            musing_tokens=0,
            tool_tokens=0,
            output_reserve=0,
            protocol_reserve=0,
            num_ctx=num_ctx,
            history_messages=len(raw_history),
        )
        ledger["source"] = "history_estimate"
    result = dict(ledger)
    result.update(_page_stats(db_path))
    result["enabled"] = True
    return result


def pressure_snapshot(history: list[dict] | None = None, db_path: Path = DB_PATH,
                      ledger: dict | None = None) -> dict:
    current = stats(history=history or [], db_path=db_path, ledger=ledger)
    keys = (
        "enabled", "source", "measured_at", "num_ctx", "input_budget_tokens",
        "input_tokens", "output_reserve_tokens", "total_tokens", "context_fill",
        "estimated_tokens_before_hard_limit",
        "required_context_tokens", "minimum_required_tokens", "overflow_tokens",
        "fixed_overflow_tokens", "context_fits", "fit_status", "fixed_overflow",
        "unshrinkable",
        "pressure_score", "pressure", "history_tokens", "history_messages",
        "turns_until_history_eviction", "unsummarized_eviction_backlog",
        "prefault_page_count", "page_count", "hot_page_count", "hot_page_tokens",
        "page_payload_bytes", "disk_fill", "disk_over_budget",
        "dropped_memory_items", "dropped_history_messages",
        "dropped_musing_items", "breakdown", "overflow",
        "paging_error",
    )
    return {key: current[key] for key in keys if key in current}


def pressure_prompt(snapshot: dict) -> str:
    """Format factual runtime telemetry for a dedicated prompt block."""
    if not snapshot or not snapshot.get("enabled", True):
        return "Working-memory telemetry is unavailable because Mindpage is disabled."
    fill = max(0.0, min(1.0, float(snapshot.get("context_fill") or 0.0)))
    percent = int(round(fill * 100))
    pressure = str(snapshot.get("pressure") or _pressure_band(fill))
    history_messages = int(snapshot.get("history_messages") or 0)
    pages = int(snapshot.get("page_count") or 0)
    backlog = int(snapshot.get("unsummarized_eviction_backlog") or 0)
    note = f"{percent}% context ({pressure}); {history_messages} messages; {pages} local pages."
    if backlog:
        note += f" {backlog} older messages excluded."
    return note
