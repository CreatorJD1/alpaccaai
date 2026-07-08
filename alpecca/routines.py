"""Empty-by-default scheduled routines for safe local maintenance."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from config import DB_PATH

KINDS = {
    "daily_recap",
    "morning_greeting",
    "consolidate_observations",
    "embed_backfill",
}


def _connect(db_path: Path = DB_PATH):
    from alpecca.db import connect as _db_connect
    return _db_connect(db_path)


def init_db(db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS routines (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                hour          INTEGER NOT NULL,
                weekday       INTEGER NOT NULL DEFAULT -1,
                kind          TEXT NOT NULL,
                enabled       INTEGER NOT NULL DEFAULT 1,
                last_run_key  TEXT,
                created_ts    REAL NOT NULL
            )
            """
        )


def _clean_hour(value: Any) -> int:
    hour = int(value)
    if hour < 0 or hour > 23:
        raise ValueError("hour must be 0-23")
    return hour


def _clean_weekday(value: Any = -1) -> int:
    weekday = int(value)
    if weekday < -1 or weekday > 6:
        raise ValueError("weekday must be -1 or 0-6")
    return weekday


def _clean_kind(value: Any) -> str:
    kind = str(value or "").strip()
    if kind not in KINDS:
        raise ValueError(f"unknown routine kind: {kind}")
    return kind


def run_key(now: float | None = None) -> str:
    tm = time.localtime(time.time() if now is None else float(now))
    return f"{tm.tm_year:04d}-{tm.tm_mon:02d}-{tm.tm_mday:02d}-{tm.tm_hour:02d}"


def add(name: str, hour: int, kind: str, weekday: int = -1, *,
        enabled: bool = True, db_path: Path = DB_PATH) -> dict:
    init_db(db_path)
    name = (name or "").strip()[:120]
    if not name:
        raise ValueError("name is required")
    hour = _clean_hour(hour)
    weekday = _clean_weekday(weekday)
    kind = _clean_kind(kind)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO routines (name, hour, weekday, kind, enabled, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, hour, weekday, kind, 1 if enabled else 0, time.time()),
        )
        row = conn.execute("SELECT * FROM routines WHERE id=?", (int(cur.lastrowid),)).fetchone()
    return dict(row)


def list_all(db_path: Path = DB_PATH) -> list[dict]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM routines ORDER BY hour, weekday, id").fetchall()
    return [dict(r) for r in rows]


def set_enabled(routine_id: int, enabled: bool, db_path: Path = DB_PATH) -> dict:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute("UPDATE routines SET enabled=? WHERE id=?", (1 if enabled else 0, int(routine_id)))
        row = conn.execute("SELECT * FROM routines WHERE id=?", (int(routine_id),)).fetchone()
    if row is None:
        raise KeyError(routine_id)
    return dict(row)


def due(now: float | None = None, db_path: Path = DB_PATH) -> list[dict]:
    init_db(db_path)
    ts = time.time() if now is None else float(now)
    tm = time.localtime(ts)
    key = run_key(ts)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM routines "
            "WHERE enabled=1 AND hour=? AND (weekday=-1 OR weekday=?) "
            "AND (last_run_key IS NULL OR last_run_key != ?) "
            "ORDER BY id",
            (tm.tm_hour, tm.tm_wday, key),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_ran(routine_id: int, now: float | None = None, db_path: Path = DB_PATH) -> dict:
    init_db(db_path)
    key = run_key(now)
    with _connect(db_path) as conn:
        conn.execute("UPDATE routines SET last_run_key=? WHERE id=?", (key, int(routine_id)))
        row = conn.execute("SELECT * FROM routines WHERE id=?", (int(routine_id),)).fetchone()
    if row is None:
        raise KeyError(routine_id)
    return dict(row)
