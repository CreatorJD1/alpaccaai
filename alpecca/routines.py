"""Empty-by-default scheduled routines with durable, atomic run execution.

The routine *catalog* (name, hour, weekday, kind, enabled) lives in the
``routines`` table. Whether a scheduled occurrence has already run is no longer
tracked by a racy ``last_run_key`` string updated after the fact; it is owned by
the atomic claim ledger in :mod:`alpecca.routine_ledger`.

Scheduling identity: a routine fires in an hourly bucket. ``run_key`` maps a wall
clock time to the local ``YYYY-MM-DD-HH`` bucket, and each ``(routine_id,
run_key)`` pair is one occurrence the ledger tracks exactly once.

Missed-run policy (explicit, deterministic): only the *current* run_key window is
ever considered due. A routine whose scheduled hour elapsed while the app was
offline is **skipped, not backfilled** -- the next matching hour is a new
occurrence. This deliberately never fires a burst of missed runs on wake, and it
means crash recovery (an expired lease) only re-runs an occurrence while its hour
is still current.

Execution protocol (see :func:`claim_due`):

    1. ``candidates(now)``            -- schedule match only (a cheap read)
    2. ``claim(id, now)``            -- atomically acquire a bounded lease
    3. run the routine
    4. exactly one of:
       ``complete(claim)``  success -> occurrence done (schedule advanced)
       ``fail(claim)``      error   -> backoff/retry, terminal after max attempts
       ``release(claim)``   deferred/safely-cancelled -> STILL due (not consumed)

DST / timezone determinism: ``run_key`` and schedule matching derive from an
injectable ``localtime`` callable (default ``time.localtime``). On a fall-back
repeat the two physical hours share one run_key (idempotent single run); a
spring-forward skipped hour simply never matches (deterministic skip). Tests feed
a synthetic ``localtime`` to prove both without depending on the host timezone.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from config import DB_PATH

from alpecca import routine_ledger as _ledger

KINDS = {
    "daily_recap",
    "morning_greeting",
    "consolidate_observations",
    "embed_backfill",
    "vacuum",
}

# Bounded default lease for a routine run; re-exported for the scheduler.
DEFAULT_LEASE_SECONDS = _ledger.DEFAULT_LEASE_SECONDS

LocalTime = Callable[[float], time.struct_time]


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
    _ledger.ensure_schema(db_path)


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


def run_key(now: float | None = None, *, localtime: LocalTime = time.localtime) -> str:
    """Local ``YYYY-MM-DD-HH`` bucket a routine fires in.

    Derived through the injectable ``localtime`` so DST/timezone behavior is
    deterministic and testable. Callable with no arguments (used that way by the
    server), matching the historical signature.
    """
    tm = localtime(time.time() if now is None else float(now))
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


def remove(routine_id: int, db_path: Path = DB_PATH) -> bool:
    init_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM routines WHERE id=?", (int(routine_id),))
    return cur.rowcount > 0


def candidates(now: float | None = None, *, db_path: Path = DB_PATH,
               localtime: LocalTime = time.localtime) -> list[dict]:
    """Routines whose schedule matches the current local hour/weekday.

    Pure read of the catalog -- consumes no occurrence and consults no ledger.
    Each returned row is annotated with its ``run_key`` for this window so the
    caller can claim it. This is the schedule-match half of the old ``due()``.
    """
    init_db(db_path)
    ts = time.time() if now is None else float(now)
    tm = localtime(ts)
    key = run_key(ts, localtime=localtime)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM routines "
            "WHERE enabled=1 AND hour=? AND (weekday=-1 OR weekday=?) "
            "ORDER BY id",
            (tm.tm_hour, tm.tm_wday),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["run_key"] = key
        out.append(item)
    return out


def claim(routine_id: int, now: float | None = None, *,
          run_key_value: str | None = None,
          lease_seconds: float = DEFAULT_LEASE_SECONDS,
          db_path: Path = DB_PATH,
          localtime: LocalTime = time.localtime) -> dict | None:
    """Atomically claim one routine's current occurrence for a bounded lease.

    Returns a claim dict (carrying ``routine_id``, ``run_key`` and
    ``claim_token``) if this caller won, else ``None``. This is the atomic
    primitive: of any number of concurrent callers exactly one wins.
    """
    init_db(db_path)
    ts = time.time() if now is None else float(now)
    key = run_key_value if run_key_value is not None else run_key(ts, localtime=localtime)
    return _ledger.claim(int(routine_id), key, ts, lease_seconds=lease_seconds, db_path=db_path)


def claim_due(now: float | None = None, *,
              lease_seconds: float = DEFAULT_LEASE_SECONDS,
              db_path: Path = DB_PATH,
              localtime: LocalTime = time.localtime) -> list[tuple[dict, dict]]:
    """Claim every currently-due routine this caller can win.

    Returns ``[(routine_row, claim), ...]`` for occurrences this caller now holds
    a lease on. Occurrences already claimed elsewhere, completed, terminally
    failed, or still inside a backoff window are silently skipped. The caller must
    resolve each claim with exactly one of :func:`complete`, :func:`fail`, or
    :func:`release`.
    """
    ts = time.time() if now is None else float(now)
    out: list[tuple[dict, dict]] = []
    for row in candidates(ts, db_path=db_path, localtime=localtime):
        got = _ledger.claim(
            int(row["id"]), str(row["run_key"]), ts,
            lease_seconds=lease_seconds, db_path=db_path,
        )
        if got is not None:
            out.append((row, got))
    return out


def complete(claim_row: dict, now: float | None = None, db_path: Path = DB_PATH) -> bool:
    """Advance a claimed occurrence to done -- only for the current holder."""
    return _ledger.complete(
        int(claim_row["routine_id"]), str(claim_row["run_key"]),
        str(claim_row["claim_token"]), now=now, db_path=db_path,
    )


def release(claim_row: dict, now: float | None = None, *,
            retry_after_seconds: float = 0.0, db_path: Path = DB_PATH) -> bool:
    """Return a claimed occurrence to due WITHOUT consuming it (defer/cancel)."""
    return _ledger.release(
        int(claim_row["routine_id"]), str(claim_row["run_key"]),
        str(claim_row["claim_token"]), now=now,
        retry_after_seconds=retry_after_seconds, db_path=db_path,
    )


def fail(claim_row: dict, now: float | None = None, *, error: Any = "",
         max_attempts: int = _ledger.DEFAULT_MAX_ATTEMPTS,
         base_backoff: float = _ledger.DEFAULT_BASE_BACKOFF_SECONDS,
         max_backoff: float = _ledger.DEFAULT_MAX_BACKOFF_SECONDS,
         db_path: Path = DB_PATH) -> dict:
    """Record a failed run: backoff/retry, or terminal after ``max_attempts``."""
    return _ledger.fail(
        int(claim_row["routine_id"]), str(claim_row["run_key"]),
        str(claim_row["claim_token"]), now=now, error=error,
        max_attempts=max_attempts, base_backoff=base_backoff,
        max_backoff=max_backoff, db_path=db_path,
    )


def recover_stale(now: float | None = None, db_path: Path = DB_PATH) -> list[dict]:
    """List occurrences whose lease expired without completion (crash recovery).

    Informational: :func:`claim` reclaims expired leases in place, so no mutation
    is required to recover. Returned rows let the scheduler log/telemeter how many
    interrupted runs are being re-offered.
    """
    init_db(db_path)
    return _ledger.expired_claims(now=now, db_path=db_path)


def prune(now: float | None = None, *,
          keep_seconds: float = _ledger.DEFAULT_PRUNE_KEEP_SECONDS,
          db_path: Path = DB_PATH) -> int:
    """Bound ledger growth by removing old terminal occurrences."""
    init_db(db_path)
    return _ledger.prune(now=now, keep_seconds=keep_seconds, db_path=db_path)


# --- legacy compatibility ---------------------------------------------------
# The pre-integration scheduler (and tests that monkeypatch it) still call the
# non-atomic ``due()`` / ``mark_ran()`` pair. These remain, now ledger-backed, so
# an un-migrated caller is at least idempotent. New code must use the atomic
# ``claim`` -> ``complete``/``fail``/``release`` protocol above instead.

def due(now: float | None = None, db_path: Path = DB_PATH, *,
        localtime: LocalTime = time.localtime) -> list[dict]:
    """LEGACY: schedule-matching routines whose occurrence is still claimable.

    Does not claim anything (so two pollers can still both see a row -- that race
    is exactly what the atomic :func:`claim` protocol closes). Retained only for
    the not-yet-migrated scheduler and status views.
    """
    ts = time.time() if now is None else float(now)
    out = []
    for row in candidates(ts, db_path=db_path, localtime=localtime):
        state = _ledger.state_of(int(row["id"]), str(row["run_key"]), db_path=db_path)
        if _ledger.is_claimable(state, ts):
            item = dict(row)
            item.pop("run_key", None)
            out.append(item)
    return out


def mark_ran(routine_id: int, now: float | None = None, db_path: Path = DB_PATH) -> dict:
    """LEGACY: idempotently mark the current occurrence done in the ledger.

    Mirrors ``last_run_key`` on the catalog row for human inspection. New code
    completes an owned claim via :func:`complete` instead.
    """
    init_db(db_path)
    ts = time.time() if now is None else float(now)
    key = run_key(ts)
    _ledger.force_done(int(routine_id), key, now=ts, db_path=db_path)
    with _connect(db_path) as conn:
        conn.execute("UPDATE routines SET last_run_key=? WHERE id=?", (key, int(routine_id)))
        row = conn.execute("SELECT * FROM routines WHERE id=?", (int(routine_id),)).fetchone()
    if row is None:
        raise KeyError(routine_id)
    return dict(row)
