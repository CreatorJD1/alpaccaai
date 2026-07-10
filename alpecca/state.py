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
    # Delegates to alpecca.db.connect -- the one hardened opener
    # (busy_timeout, commit-on-exit, always-close). See alpecca/db.py.
    from alpecca.db import connect as _db_connect
    with _db_connect(db_path) as conn:
        yield conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    # Persistent per-database safety: WAL + synchronous=NORMAL. This is what
    # keeps the save from corrupting under concurrent writers or a cloud-sync
    # client snapshotting mid-write. Idempotent and cheap.
    from alpecca.db import harden
    harden(db_path)
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
                embedding   TEXT,
                scope       TEXT NOT NULL DEFAULT 'shared'
            );

            -- Her self-set goals: wants she forms from real internals and acts
            -- on. See alpecca/desires.py. `origin` always points at the real
            -- memory/musing/signal that produced the desire -- grounding.
            CREATE TABLE IF NOT EXISTS desires (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL NOT NULL,
                kind         TEXT NOT NULL,
                text         TEXT NOT NULL,
                strength     REAL NOT NULL,
                origin       TEXT,
                status       TEXT NOT NULL DEFAULT 'open',
                last_touched REAL NOT NULL
            );

            -- Her bounded recursive self-improvement log: every nudge she makes
            -- to one of her own tunable parameters, with the outcome it was
            -- judged against. See alpecca/selfmod.py. Fully auditable, fully
            -- reversible -- nothing she changes about herself is hidden.
            CREATE TABLE IF NOT EXISTS self_revisions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ts              REAL NOT NULL,
                param           TEXT NOT NULL,
                old_value       REAL NOT NULL,
                new_value       REAL NOT NULL,
                reason          TEXT,
                outcome_before  REAL,
                outcome_after   REAL,
                kept            INTEGER NOT NULL DEFAULT 0,
                status          TEXT NOT NULL DEFAULT 'trial'
            );
            """
        )
        # Lightweight migrations: older databases won't have these columns.
        mem_cols = {r["name"] for r in conn.execute("PRAGMA table_info(memories)")}
        if "embedding" not in mem_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN embedding TEXT")
        if "scope" not in mem_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN scope TEXT NOT NULL DEFAULT 'shared'")
        conn.execute("UPDATE memories SET scope='shared' WHERE scope IS NULL OR trim(scope)='' ")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS memories_scope_salience_idx "
            "ON memories(scope, salience DESC, ts DESC)"
        )
        state_cols = {r["name"] for r in conn.execute("PRAGMA table_info(state)")}
        if "appearance_seed" not in state_cols:
            conn.execute("ALTER TABLE state ADD COLUMN appearance_seed INTEGER")
        if "energy" not in state_cols:
            conn.execute("ALTER TABLE state ADD COLUMN energy REAL")
        # Two newer feelings (curiosity, social_hunger) and where she is in her
        # home (location). All default in for databases that predate them.
        if "curiosity" not in state_cols:
            conn.execute("ALTER TABLE state ADD COLUMN curiosity REAL")
        if "social_hunger" not in state_cols:
            conn.execute("ALTER TABLE state ADD COLUMN social_hunger REAL")
        if "location" not in state_cols:
            conn.execute("ALTER TABLE state ADD COLUMN location TEXT")
        # Her seventh feeling: a grounded sense of incompleteness. Defaults in
        # for databases that predate it (NULL -> the dataclass default).
        if "longing" not in state_cols:
            conn.execute("ALTER TABLE state ADD COLUMN longing REAL")
        # Keep the mood log bounded: one row per ~8s tick forever was the only
        # unbounded growth in her save file. Trend introspection reads days,
        # not months -- see config.STATE_LOG_KEEP_DAYS (0 = never prune).
        from config import STATE_LOG_KEEP_DAYS
        if STATE_LOG_KEEP_DAYS > 0:
            cutoff = time.time() - STATE_LOG_KEEP_DAYS * 86400.0
            conn.execute("DELETE FROM state_log WHERE ts < ?", (cutoff,))
    try:
        from alpecca import mindpage as mindpage_mod
        mindpage_mod.install_memory_indexes(db_path)
        mindpage_mod.ensure_schema(db_path)
        from alpecca import memory as memory_mod
        memory_mod.ensure_search_index(db_path)
    except Exception:
        pass


def load_state(db_path: Path = DB_PATH) -> EmotionalState:
    """Return the persisted mood, or a fresh baseline on first ever run.

    energy, curiosity and social_hunger are newer columns; older rows store NULL,
    so each falls back to its dataclass default rather than crashing. We build the
    state from a dict of just the non-NULL feelings, letting EmotionalState fill
    the rest -- the same append-only safety the dataclass itself relies on."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT love, compassion, fear, energy, curiosity, social_hunger, longing "
            "FROM state WHERE id = 1"
        ).fetchone()
    if row is None:
        return EmotionalState()
    fields = {"love": row["love"], "compassion": row["compassion"], "fear": row["fear"]}
    for newer in ("energy", "curiosity", "social_hunger", "longing"):
        if row[newer] is not None:
            fields[newer] = row[newer]
    # Clamp on load: the update rules keep values in [0,1] at runtime, but a
    # hand-edited or damaged row would otherwise flow straight into her prompt.
    # Non-numeric garbage falls back to a fresh baseline rather than crashing.
    try:
        fields = {k: min(1.0, max(0.0, float(v))) for k, v in fields.items()}
    except (TypeError, ValueError):
        return EmotionalState()
    return EmotionalState(**fields)


def save_state(state: EmotionalState, trigger: str = "", db_path: Path = DB_PATH) -> None:
    """Persist the current mood and append a log entry. `trigger` is a short note
    about what caused this update (e.g. "chat", "telemetry tick") so the log
    stays interpretable when you look back at it."""
    now = time.time()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO state (id, love, compassion, fear, energy,
                               curiosity, social_hunger, longing, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                love=excluded.love,
                compassion=excluded.compassion,
                fear=excluded.fear,
                energy=excluded.energy,
                curiosity=excluded.curiosity,
                social_hunger=excluded.social_hunger,
                longing=excluded.longing,
                updated_at=excluded.updated_at
            """,
            (state.love, state.compassion, state.fear, state.energy,
             state.curiosity, state.social_hunger, state.longing, now),
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


def load_location(db_path: Path = DB_PATH) -> str | None:
    """Which room of her home she's currently in, or None if she's never moved
    yet (the caller picks a default). Part of her persisted state so she's in the
    same room when she wakes that she was in when you left."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT location FROM state WHERE id = 1").fetchone()
    if row is None or row["location"] is None:
        return None
    return str(row["location"])


def save_location(location: str, db_path: Path = DB_PATH) -> None:
    """Persist the room she's moved to. Upsert so it works on first run before any
    mood has been written."""
    default = EmotionalState()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO state (id, love, compassion, fear, updated_at, location) "
            "VALUES (1, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET location = excluded.location",
            (default.love, default.compassion, default.fear, time.time(), location),
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
