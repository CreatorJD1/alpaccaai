"""Persistence for the emotional state -- the spec's "Homeostasis DB".

The point of persisting the mood vector is continuity: Alpecca should wake up
tomorrow feeling roughly how it felt when you last closed it, not reset to a
blank slate. We keep a single-row `state` table plus an append-only `state_log`
so you can later chart how the mood drifted over time.

SQLite is deliberate -- it's a single file, needs no server, and survives
restarts, which is exactly the "file system as nervous system" idea in the spec.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from config import DB_PATH
from alpecca.homeostasis import EmotionalState


@contextmanager
def _connect(db_path: Path = DB_PATH):
    """Open a SQLite connection, commit on clean exit, and *always* close it.

    Closing matters on Windows -- a dangling handle keeps the .db file locked,
    which surfaces both as test flakes (TemporaryDirectory can't unlink) and as
    real "disk I/O error"-class problems on synced filesystems.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS state (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                love            REAL NOT NULL,
                compassion      REAL NOT NULL,
                fear            REAL NOT NULL,
                updated_at      REAL NOT NULL,
                appearance_seed INTEGER
            );

            CREATE TABLE IF NOT EXISTS state_log (
                ts          REAL NOT NULL,
                love        REAL NOT NULL,
                compassion  REAL NOT NULL,
                fear        REAL NOT NULL,
                trigger     TEXT
            );

            CREATE TABLE IF NOT EXISTS memories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL NOT NULL,
                kind        TEXT NOT NULL,
                content     TEXT NOT NULL,
                salience    REAL NOT NULL,
                tokens      TEXT NOT NULL,
                embedding   TEXT
            );
            """
        )
        # Lightweight migrations: older databases won't have these columns.
        mem_cols = {r["name"] for r in conn.execute("PRAGMA table_info(memories)")}
        if "embedding" not in mem_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN embedding TEXT")
        state_cols = {r["name"] for r in conn.execute("PRAGMA table_info(state)")}
        if "appearance_seed" not in state_cols:
            conn.execute("ALTER TABLE state ADD COLUMN appearance_seed INTEGER")


def load_state(db_path: Path = DB_PATH) -> EmotionalState:
    """Return the persisted mood, or a fresh baseline on first ever run."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT love, compassion, fear FROM state WHERE id = 1").fetchone()
    if row is None:
        return EmotionalState()
    return EmotionalState(row["love"], row["compassion"], row["fear"])


def save_state(state: EmotionalState, trigger: str = "", db_path: Path = DB_PATH) -> None:
    """Persist the current mood and append a log entry. `trigger` is a short note
    about what caused this update (e.g. "chat", "telemetry tick") so the log
    stays interpretable when you look back at it."""
    now = time.time()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO state (id, love, compassion, fear, updated_at)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                love=excluded.love,
                compassion=excluded.compassion,
                fear=excluded.fear,
                updated_at=excluded.updated_at
            """,
            (state.love, state.compassion, state.fear, now),
        )
        conn.execute(
            "INSERT INTO state_log (ts, love, compassion, fear, trigger) VALUES (?, ?, ?, ?, ?)",
            (now, state.love, state.compassion, state.fear, trigger),
        )


def load_appearance_seed(db_path: Path = DB_PATH) -> int | None:
    """Return Alpecca's persisted standing taste-seed, or None if she's never had
    one yet. Keeping this stable across restarts is what lets her remain
    recognizably herself instead of getting a new personality every reboot."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT appearance_seed FROM state WHERE id = 1"
        ).fetchone()
    if row is None or row["appearance_seed"] is None:
        return None
    return int(row["appearance_seed"])


def save_appearance_seed(seed: int, db_path: Path = DB_PATH) -> None:
    """Persist her standing taste-seed. Uses an upsert so it works even on the
    very first run before any mood has been saved."""
    default = EmotionalState()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO state (id, love, compassion, fear, updated_at, appearance_seed) "
            "VALUES (1, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET appearance_seed = excluded.appearance_seed",
            (default.love, default.compassion, default.fear, time.time(), seed),
        )


def mood_history(limit: int = 200, db_path: Path = DB_PATH) -> list[dict]:
    """Recent mood samples, oldest first -- handy for plotting the avatar's life."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ts, love, compassion, fear, trigger FROM state_log "
            "ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]
