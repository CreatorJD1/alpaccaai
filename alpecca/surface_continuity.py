"""Content-free cross-surface awareness for Alpecca's single core.

The ledger proves that contact occurred without copying private message text
between creator and guest scopes.  It lets every surface distinguish "I saw an
interaction" from "I can quote that private conversation".
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from config import DB_PATH


_ALLOWED_SURFACES = {
    "house-hq", "websocket", "channel", "discord", "voice", "direct", "app",
}


def _clean_surface(value: str) -> str:
    normalized = "-".join(str(value or "unknown").strip().lower().split())[:48]
    return normalized if normalized in _ALLOWED_SURFACES else "other"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS surface_continuity_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                surface TEXT NOT NULL,
                principal_class TEXT NOT NULL,
                event_kind TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_surface_continuity_recent
                ON surface_continuity_events(ts DESC);
            """
        )


def record_contact(
    surface: str,
    *,
    principal: str,
    event_kind: str = "message",
    db_path: Path = DB_PATH,
    now: float | None = None,
) -> int:
    """Record only route and actor class; never message content or identity."""
    surface_name = _clean_surface(surface)
    principal_class = "creator" if principal == "creator" else "guest"
    kind = "voice" if event_kind == "voice" else "message"
    init_db(db_path)
    with _connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO surface_continuity_events "
            "(ts, surface, principal_class, event_kind) VALUES (?, ?, ?, ?)",
            (float(now if now is not None else time.time()), surface_name, principal_class, kind),
        )
        # Keep the awareness ledger bounded independently of chat/memory data.
        conn.execute(
            "DELETE FROM surface_continuity_events WHERE id NOT IN "
            "(SELECT id FROM surface_continuity_events ORDER BY id DESC LIMIT 256)"
        )
        return int(cursor.lastrowid)


def recent_contacts(
    *, db_path: Path = DB_PATH, limit: int = 6, now: float | None = None,
) -> list[dict]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id,ts,surface,principal_class,event_kind "
            "FROM surface_continuity_events ORDER BY id DESC LIMIT ?",
            (max(1, min(20, int(limit))),),
        ).fetchall()
    current = float(now if now is not None else time.time())
    return [
        {
            **dict(row),
            "age_seconds": max(0, round(current - float(row["ts"]))),
        }
        for row in rows
    ]


def prompt_awareness(*, db_path: Path = DB_PATH, limit: int = 4) -> str:
    try:
        contacts = recent_contacts(db_path=db_path, limit=limit)
    except (OSError, sqlite3.Error):
        return ""
    if not contacts:
        return ""
    lines = []
    for item in contacts:
        age = int(item["age_seconds"])
        age_text = "just now" if age < 15 else f"about {max(1, age // 60)} minute(s) ago"
        actor = "the creator" if item["principal_class"] == "creator" else "a verified guest"
        lines.append(
            f"- {actor} contacted you through {item['surface']} {age_text} ({item['event_kind']})."
        )
    return (
        "Cross-surface activity ledger (measured, content-free):\n"
        + "\n".join(lines)
        + "\nThis proves contact occurred, not what private text said. Never claim the "
        "other surface was unseen when it appears here; do not invent or reveal its content."
    )
