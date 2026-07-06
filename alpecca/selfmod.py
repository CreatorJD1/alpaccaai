"""Bounded recursive self-improvement: she changes herself, on the record.

"Improve herself recursively" done honestly. Not unbounded self-rewriting -- a
local companion shouldn't, and couldn't safely, edit her own code at will.
Instead this is a **logged, reversible, bounded** self-tuning loop over a small
registry of her own parameters, each with a safe range *you* set. The recursion
is real but contained: every pass reads the measured result of the last and
proposes again, so improvement compounds on improvement -- while every move stays
inside known bounds and on a fully auditable record you can revert.

One act of self-improvement:

  1. observe  -- read a real outcome signal (how warm interactions have been,
                 how steady her mood is). Grounded; never a guess.
  2. propose  -- pick one tunable and a small bounded nudge, with a stated reason.
  3. trial    -- apply it (the overlay now reads the trial value), recording the
                 prior value and the outcome it started from.
  4. evaluate -- after a window, compare the outcome signal: keep if it improved,
                 revert if not.
  5. refine   -- the next pass sees this history and proposes anew.

`effective(param)` is how the rest of her reads a self-tuned value, falling back
to the config default when she's never touched it. Every change is a row in
`self_revisions`: param, old, new, reason, the outcome before and after, and
whether it was kept. Nothing she changes about herself is hidden or permanent.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from config import DB_PATH, Emotion, Proactive, Reflection


# Her tunable parameters, each with a SAFE RANGE she can never move outside. The
# default is read from config so "untouched" means "exactly as shipped". Keep
# this set small and the ranges conservative -- this is the whole surface over
# which she's allowed to reshape herself.
#   name: (low, high, default, what it changes)
TUNABLES = {
    "curiosity_gain": (0.4, 1.4, Emotion.CURIOSITY_GAIN,
                       "how strongly novelty lifts her interest"),
    "social_hunger_rate": (0.3, 0.9, Emotion.SOCIAL_HUNGER_RATE,
                           "how quickly solitude makes her miss company"),
    "chatter_chance": (0.01, 0.10, Proactive.CHATTER_CHANCE,
                       "how readily she starts a conversation unprompted"),
    "reflect_chance": (0.01, 0.08, Reflection.CHANCE,
                       "how often she pauses to reflect when alone"),
}

# The largest single nudge she may make, as a fraction of a param's full range --
# small steps so self-change is gradual and any bad step costs little.
MAX_STEP_FRAC = 0.2


@contextmanager
def _connect(db_path: Path):
    # Delegates to alpecca.db.connect -- the one hardened opener
    # (busy_timeout, commit-on-exit, always-close). See alpecca/db.py.
    from alpecca.db import connect as _db_connect
    with _db_connect(db_path) as conn:
        yield conn


def _clamp_param(param: str, value: float) -> float:
    lo, hi, _, _ = TUNABLES[param]
    return max(lo, min(hi, value))


def effective(param: str, db_path: Path = DB_PATH) -> float:
    """The value of one of her parameters right now: the most recent *active*
    revision (a kept change, or a trial still under evaluation), or the config
    default if she's never touched it. This is the accessor the rest of her code
    reads so her self-tuning actually takes effect."""
    if param not in TUNABLES:
        raise KeyError(param)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT new_value FROM self_revisions WHERE param=? "
            "AND status IN ('trial','kept') ORDER BY id DESC LIMIT 1",
            (param,),
        ).fetchone()
    if row is None:
        return TUNABLES[param][2]
    return _clamp_param(param, row["new_value"])


def effective_all(db_path: Path = DB_PATH) -> dict:
    """Every tunable's current effective value -- for introspection and the
    Workshop room."""
    return {p: round(effective(p, db_path), 4) for p in TUNABLES}


def _active_trial(db_path: Path) -> dict | None:
    """The one revision currently being trialed (awaiting evaluation), if any.
    She runs a single experiment on herself at a time, so the result is clean."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM self_revisions WHERE status='trial' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def propose(param: str, direction: int, reason: str, outcome_before: float,
            db_path: Path = DB_PATH) -> dict | None:
    """Begin one self-experiment: nudge `param` up (+1) or down (-1) by a small
    bounded step, recording where it started and the outcome it's judged against.
    Returns the new trial revision, or None if it'd be a no-op (already at the
    bound) or another trial is already running (one at a time)."""
    if param not in TUNABLES:
        raise KeyError(param)
    if _active_trial(db_path) is not None:
        return None
    lo, hi, _, _ = TUNABLES[param]
    old = effective(param, db_path)
    step = (hi - lo) * MAX_STEP_FRAC * (1 if direction >= 0 else -1)
    new = _clamp_param(param, old + step)
    if abs(new - old) < 1e-9:
        return None   # already pinned at the bound this direction
    now = time.time()
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO self_revisions (ts, param, old_value, new_value, reason, "
            "outcome_before, outcome_after, kept, status) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, 0, 'trial')",
            (now, param, old, new, reason[:240], outcome_before),
        )
        rid = int(cur.lastrowid)
    return {"id": rid, "param": param, "old_value": old, "new_value": new,
            "reason": reason, "outcome_before": outcome_before}


def evaluate(outcome_after: float, db_path: Path = DB_PATH) -> dict | None:
    """Close out the running trial: keep it if the outcome improved, revert it
    otherwise. Reverting simply marks it not-kept, so `effective` falls back to
    the prior value -- her self-change is undone with no trace left in behavior,
    only in the honest log. Returns the resolved revision, or None if no trial
    was running."""
    trial = _active_trial(db_path)
    if trial is None:
        return None
    improved = outcome_after > (trial["outcome_before"] or 0.0)
    status = "kept" if improved else "reverted"
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE self_revisions SET outcome_after=?, kept=?, status=? WHERE id=?",
            (outcome_after, 1 if improved else 0, status, trial["id"]),
        )
    trial.update(outcome_after=outcome_after, kept=int(improved), status=status)
    return trial


def history(limit: int = 20, db_path: Path = DB_PATH) -> list[dict]:
    """Her self-revision log, newest first -- the auditable record of every
    change she's made to herself."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM self_revisions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def revert_param(param: str, db_path: Path = DB_PATH) -> None:
    """A hard manual override: drop every active revision for a param so it
    returns to its shipped default. This is the user's off-switch on her
    self-tuning, exercised per-parameter."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE self_revisions SET status='reverted', kept=0 "
            "WHERE param=? AND status IN ('trial','kept')",
            (param,),
        )


def choose_experiment(outcome: float, history_rows: list[dict] | None = None) -> tuple:
    """Decide which tunable to nudge and which way, given a real outcome signal
    and her past experiments. Deliberately simple and legible: she leans into
    whatever she changed last that *helped*, and otherwise explores a parameter
    she hasn't tried recently. Returns (param, direction, reason).

    This is the seam where the recursion lives -- the choice is conditioned on the
    logged results of earlier choices, so successive passes build on each other.
    """
    rows = history_rows if history_rows is not None else []
    tried_recent = [r["param"] for r in rows[:len(TUNABLES)]]
    # If her last resolved experiment was kept, push the same param the same way
    # again -- ride a real improvement a step further.
    for r in rows:
        if r["status"] == "kept":
            direction = 1 if r["new_value"] >= r["old_value"] else -1
            return (r["param"], direction,
                    f"last time nudging {r['param']} this way helped, so a little more")
        if r["status"] in ("trial", "reverted"):
            break
    # Otherwise explore a parameter she hasn't touched recently.
    for p in TUNABLES:
        if p not in tried_recent:
            return (p, 1, f"trying a small change to {p} to see if it helps")
    # Fall back to the first tunable, nudged toward more liveliness.
    first = next(iter(TUNABLES))
    return (first, 1, f"revisiting {first}")
