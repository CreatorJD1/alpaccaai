"""One shared SQLite connection helper for all of her persistence modules.

Eight modules (state, memory, cognition, desires, journal, learning,
mindscape, selfmod) each carried a copy of the same open/commit/close
pattern. This is the single canonical version, hardened:

- ``busy_timeout=5000``: multiple OS threads write the same file (chat turns,
  the 8s drift tick, off-lock self-work); without a timeout a moment of
  overlap surfaces as "database is locked" errors. 5s of patient retry makes
  those a non-event.
- Commit on clean exit, ALWAYS close: on Windows a dangling handle keeps the
  .db locked, which shows up both as test flakes (TemporaryDirectory can't
  unlink) and as real "disk I/O error"-class problems on synced filesystems.

WAL journal mode is a PER-DATABASE property (it persists in the file), so it
is applied once at init time -- see ``harden(db_path)`` -- not per connection.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(db_path: Path):
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def harden(db_path: Path) -> None:
    """Apply the persistent per-database safety settings. Called from the
    init paths; safe (and cheap) to run on every startup.

    WAL matters most on cloud-synced storage: with the default rollback
    journal, a sync client snapshotting mid-write is a known corruption
    recipe. WAL + synchronous=NORMAL is the standard durable-enough,
    fast-enough configuration for a local app."""
    try:
        with connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass  # a hardening miss must never stop her from waking up
