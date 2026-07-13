r"""Durable, atomic run ledger for scheduled routines.

The scheduler used to be a non-atomic ``due()`` read followed by a separate
``mark_ran()`` write. Two pollers (an overlapping restart, a future second
worker, a slow poll that laps itself) could both read the same due routine and
both run it -- a double ``daily_recap`` post or a duplicated proactive greeting.

This module replaces that pair with an **expiring durable claim**. Each scheduled
occurrence is identified by ``(routine_id, run_key)`` where ``run_key`` is the
local ``YYYY-MM-DD-HH`` bucket a routine fires in (see ``routines.run_key``). A
poller must atomically *claim* the occurrence for a bounded lease before running
it; only the holder of the current claim token may complete, fail, or release it.

State machine for one occurrence row::

    (absent) --claim--> claimed --complete--> done      (terminal, schedule advanced)
                          |  \--fail(<max)--> pending --claim--> claimed ...
                          |   \-fail(>=max)-> failed    (terminal, schedule advanced)
                          \--release-------> pending    (deferred/cancelled: STILL due)
                          \--lease expiry--> (reclaimable in place: crash recovery)

Guarantees (all proven in ``tests/test_routines_ledger.py``):

* **Exactly once under contention** -- SQLite serializes writers, so of N
  concurrent ``claim`` calls for one occurrence exactly one returns a claim.
* **Only the claimant advances** -- ``complete``/``fail``/``release`` are guarded
  by ``claim_token`` and ``state='claimed'``; a stale holder whose lease expired
  and was reclaimed cannot complete someone else's run.
* **Deferred / safely-cancelled work is never consumed** -- ``release`` returns
  the row to ``pending`` with no attempt burned, so it is immediately due again.
* **Success OR terminal failure advances exactly once** -- ``done`` and ``failed``
  are terminal; the guarded transition happens at most once per occurrence.
* **Crash recovery is deterministic** -- an expired ``claimed`` lease is
  reclaimable in place by the next ``claim`` (no burst; see the missed-run policy
  in ``routines``: only the current ``run_key`` window is ever considered).

The ledger stores no routine payload, no transcripts, and no secrets -- only
scheduling bookkeeping (ids, the run_key bucket, attempt counts, a bounded error
label). It reuses the shared hardened SQLite connection from :mod:`alpecca.db`.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from config import DB_PATH

# --- states -----------------------------------------------------------------
PENDING = "pending"    # reclaimable (fresh backoff window or a released claim)
CLAIMED = "claimed"    # a lease is held; reclaimable only once lease_expiry passes
DONE = "done"          # terminal: completed successfully, schedule advanced
FAILED = "failed"      # terminal: exhausted retries, schedule advanced
TERMINAL_STATES = frozenset({DONE, FAILED})

# --- bounded, deterministic defaults ---------------------------------------
# A lease must comfortably exceed the slowest routine worker (~20s) plus the
# poll and coordinator overhead, while staying short enough that a crashed run
# is reclaimable inside the same hourly run_key window.
DEFAULT_LEASE_SECONDS = 300.0
# Terminal-failure policy: retry a handful of times with capped exponential
# backoff, then mark the occurrence permanently failed so the schedule advances
# exactly once instead of retrying forever.
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_BACKOFF_SECONDS = 30.0
DEFAULT_MAX_BACKOFF_SECONDS = 900.0
# Retention: keep a bounded window of ledger history for observability.
DEFAULT_PRUNE_KEEP_SECONDS = 30 * 24 * 60 * 60
_MAX_ERROR_CHARS = 240


def _connect(db_path: Path = DB_PATH):
    from alpecca.db import connect as _db_connect
    return _db_connect(db_path)


def _now(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _clean_error(value: Any) -> str:
    return " ".join(str(value or "").split())[:_MAX_ERROR_CHARS]


def ensure_schema(db_path: Path = DB_PATH) -> None:
    """Install the run ledger. Idempotent and safe to call on every startup."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS routine_runs (
                routine_id   INTEGER NOT NULL,
                run_key      TEXT NOT NULL,
                state        TEXT NOT NULL DEFAULT 'pending',
                claim_token  TEXT,
                lease_expiry REAL NOT NULL DEFAULT 0,
                attempts     INTEGER NOT NULL DEFAULT 0,
                retry_after  REAL NOT NULL DEFAULT 0,
                last_error   TEXT NOT NULL DEFAULT '',
                claimed_at   REAL NOT NULL DEFAULT 0,
                updated_at   REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (routine_id, run_key)
            )
            """
        )
        # Reclaim scans read by (state, gate); a small covering index keeps the
        # poll cheap even with a long retention window.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_routine_runs_reclaim "
            "ON routine_runs(state, lease_expiry, retry_after)"
        )


def is_claimable(row: dict | None, now: float | None = None) -> bool:
    """Pure predicate: could a fresh claim acquire this occurrence right now?

    ``None`` (no ledger row yet) is claimable. A ``pending`` row is claimable
    once its backoff gate passes. A ``claimed`` row is claimable only after its
    lease expires (crash / timeout recovery). Terminal rows are never claimable.
    """
    ts = _now(now)
    if row is None:
        return True
    state = str(row.get("state") or PENDING)
    if state in TERMINAL_STATES:
        return False
    if state == CLAIMED:
        return float(row.get("lease_expiry") or 0.0) <= ts
    if state == PENDING:
        return float(row.get("retry_after") or 0.0) <= ts
    # Unknown/legacy state: treat as reclaimable rather than wedging a routine.
    return True


def state_of(routine_id: int, run_key: str, db_path: Path = DB_PATH) -> dict | None:
    """Return the ledger row for one occurrence, or ``None`` if unclaimed."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM routine_runs WHERE routine_id=? AND run_key=?",
            (int(routine_id), str(run_key)),
        ).fetchone()
    return dict(row) if row is not None else None


def claim(routine_id: int, run_key: str, now: float | None = None, *,
          lease_seconds: float = DEFAULT_LEASE_SECONDS,
          db_path: Path = DB_PATH) -> dict | None:
    """Atomically acquire the occurrence for a bounded lease, or return ``None``.

    The single ``INSERT ... ON CONFLICT DO UPDATE ... WHERE`` claims the row only
    when it is absent, a ``pending`` row past its backoff gate, or a ``claimed``
    row whose lease already expired. SQLite serializes writers, so of any number
    of concurrent callers exactly one observes its own ``claim_token`` written
    back -- the rest see the winner's token and return ``None``. Attempt history
    is preserved across reclaim (never reset here); only ``fail`` advances it.
    """
    ts = _now(now)
    token = uuid.uuid4().hex
    lease = float(lease_seconds)
    expiry = ts + max(0.0, lease)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO routine_runs
                (routine_id, run_key, state, claim_token, lease_expiry,
                 attempts, retry_after, last_error, claimed_at, updated_at)
            VALUES (?, ?, 'claimed', ?, ?, 0, 0, '', ?, ?)
            ON CONFLICT(routine_id, run_key) DO UPDATE SET
                state='claimed',
                claim_token=excluded.claim_token,
                lease_expiry=excluded.lease_expiry,
                claimed_at=excluded.claimed_at,
                updated_at=excluded.updated_at
            WHERE (routine_runs.state='pending'
                       AND routine_runs.retry_after <= excluded.claimed_at)
               OR (routine_runs.state='claimed'
                       AND routine_runs.lease_expiry <= excluded.claimed_at)
            """,
            (int(routine_id), str(run_key), token, expiry, ts, ts),
        )
        row = conn.execute(
            "SELECT * FROM routine_runs WHERE routine_id=? AND run_key=?",
            (int(routine_id), str(run_key)),
        ).fetchone()
    if row is None:
        return None
    won = dict(row)
    if won.get("claim_token") == token and str(won.get("state")) == CLAIMED:
        return won
    return None


def complete(routine_id: int, run_key: str, claim_token: str,
             now: float | None = None, db_path: Path = DB_PATH) -> bool:
    """Advance the occurrence to ``done`` -- only for the current claim holder.

    Returns ``False`` (a no-op) if the lease expired and another poller reclaimed
    the occurrence (token mismatch) or it is already terminal.
    """
    ts = _now(now)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE routine_runs SET state='done', claim_token=NULL, "
            "lease_expiry=0, retry_after=0, last_error='', updated_at=? "
            "WHERE routine_id=? AND run_key=? AND claim_token=? AND state='claimed'",
            (ts, int(routine_id), str(run_key), str(claim_token)),
        )
        return cur.rowcount > 0


def release(routine_id: int, run_key: str, claim_token: str,
            now: float | None = None, *, retry_after_seconds: float = 0.0,
            db_path: Path = DB_PATH) -> bool:
    """Return a claimed occurrence to ``pending`` WITHOUT burning an attempt.

    This is the deferred / safely-cancelled path: a refused coordinator lease or
    a cooperative cancel is *not* a run, so the occurrence must remain due. With
    the default ``retry_after_seconds=0`` it is immediately reclaimable. Only the
    current claim holder may release.
    """
    ts = _now(now)
    gate = ts + max(0.0, float(retry_after_seconds))
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE routine_runs SET state='pending', claim_token=NULL, "
            "lease_expiry=0, retry_after=?, updated_at=? "
            "WHERE routine_id=? AND run_key=? AND claim_token=? AND state='claimed'",
            (gate, ts, int(routine_id), str(run_key), str(claim_token)),
        )
        return cur.rowcount > 0


def _backoff_seconds(attempts: int, base: float, cap: float) -> float:
    # Capped exponential backoff on the attempt count (1 -> base, 2 -> 2*base...).
    exponent = max(0, int(attempts) - 1)
    delay = float(base) * (2 ** min(16, exponent))
    return min(float(cap), delay)


def fail(routine_id: int, run_key: str, claim_token: str,
         now: float | None = None, *, error: Any = "",
         max_attempts: int = DEFAULT_MAX_ATTEMPTS,
         base_backoff: float = DEFAULT_BASE_BACKOFF_SECONDS,
         max_backoff: float = DEFAULT_MAX_BACKOFF_SECONDS,
         db_path: Path = DB_PATH) -> dict:
    """Record a run failure for the current claim holder.

    Increments the attempt count and either re-arms the occurrence as ``pending``
    behind a capped-exponential backoff gate, or -- once ``max_attempts`` is
    reached -- advances it to the terminal ``failed`` state so the schedule moves
    on exactly once. Only the current claim holder may fail an occurrence.

    Returns ``{"applied", "state", "attempts", "retry_after", "terminal"}``.
    """
    ts = _now(now)
    limit = max(1, int(max_attempts))
    detail = _clean_error(error)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT attempts FROM routine_runs "
            "WHERE routine_id=? AND run_key=? AND claim_token=? AND state='claimed'",
            (int(routine_id), str(run_key), str(claim_token)),
        ).fetchone()
        if row is None:
            return {"applied": False, "state": None, "attempts": 0,
                    "retry_after": 0.0, "terminal": False}
        attempts = int(row["attempts"] or 0) + 1
        if attempts >= limit:
            new_state = FAILED
            retry_after = 0.0
            terminal = True
        else:
            new_state = PENDING
            retry_after = ts + _backoff_seconds(attempts, base_backoff, max_backoff)
            terminal = False
        conn.execute(
            "UPDATE routine_runs SET state=?, attempts=?, retry_after=?, "
            "last_error=?, claim_token=NULL, lease_expiry=0, updated_at=? "
            "WHERE routine_id=? AND run_key=? AND claim_token=? AND state='claimed'",
            (new_state, attempts, retry_after, detail, ts,
             int(routine_id), str(run_key), str(claim_token)),
        )
    return {"applied": True, "state": new_state, "attempts": attempts,
            "retry_after": retry_after, "terminal": terminal}


def force_done(routine_id: int, run_key: str, now: float | None = None,
               db_path: Path = DB_PATH) -> None:
    """Unconditionally mark an occurrence ``done`` (legacy ``mark_ran`` support).

    Not part of the atomic claim protocol -- kept so the pre-integration
    ``due()`` / ``mark_ran()`` pair stays idempotent for a not-yet-patched
    scheduler. New code claims and completes instead.
    """
    ts = _now(now)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO routine_runs
                (routine_id, run_key, state, claim_token, lease_expiry,
                 attempts, retry_after, last_error, claimed_at, updated_at)
            VALUES (?, ?, 'done', NULL, 0, 0, 0, '', ?, ?)
            ON CONFLICT(routine_id, run_key) DO UPDATE SET
                state='done', claim_token=NULL, lease_expiry=0,
                retry_after=0, updated_at=excluded.updated_at
            """,
            (int(routine_id), str(run_key), ts, ts),
        )


def expired_claims(now: float | None = None, db_path: Path = DB_PATH) -> list[dict]:
    """List claimed occurrences whose lease has expired (crash-recovery view).

    Observability only -- ``claim`` already reclaims expired leases in place, so
    callers do not need to mutate anything to recover. Useful for a deterministic
    restart-recovery assertion and for operational telemetry.
    """
    ts = _now(now)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM routine_runs WHERE state='claimed' AND lease_expiry <= ? "
            "ORDER BY routine_id, run_key",
            (ts,),
        ).fetchall()
    return [dict(r) for r in rows]


def prune(now: float | None = None, *, keep_seconds: float = DEFAULT_PRUNE_KEEP_SECONDS,
          db_path: Path = DB_PATH) -> int:
    """Delete terminal occurrences older than the retention window.

    Bounds ledger growth without touching any live (claimable or claimed) row.
    Returns the number of rows removed.
    """
    ts = _now(now)
    cutoff = ts - max(0.0, float(keep_seconds))
    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM routine_runs WHERE state IN ('done', 'failed') AND updated_at < ?",
            (cutoff,),
        )
        return int(cur.rowcount or 0)


__all__ = [
    "PENDING", "CLAIMED", "DONE", "FAILED", "TERMINAL_STATES",
    "DEFAULT_LEASE_SECONDS", "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_BASE_BACKOFF_SECONDS", "DEFAULT_MAX_BACKOFF_SECONDS",
    "DEFAULT_PRUNE_KEEP_SECONDS",
    "ensure_schema", "is_claimable", "state_of", "claim", "complete",
    "release", "fail", "force_done", "expired_claims", "prune",
]
