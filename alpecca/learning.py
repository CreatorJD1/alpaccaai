"""Her self-training: learning lessons from her own real history.

`selfmod.py` lets her nudge a parameter and keep it if an outcome improves. This
module is the layer above it -- the part that *notices patterns in herself over
time and draws lessons from them*, then points her self-tuning in a direction.
It's the difference between "try a knob, measure" and "I've noticed that when X,
Y tends to happen, so I should Z."

Grounded, like everything else: a lesson is only ever derived from her real data
-- her mood log, the self-changes she's kept or reverted, her memory count -- and
each lesson carries the **evidence** it came from (the actual numbers), so it can
never be a made-up generalisation. She is training on herself, honestly.

The loop, run occasionally on quiet ticks (mind.learn_tick):
    analyze(real history)  ->  derive(a lesson, with evidence + a suggested nudge)
    ->  record it  ->  hand the nudge to selfmod to trial.

Pure where it counts: `analyze` and `derive` take plain data and return plain
dicts, so the reasoning is unit-testable without a database or a model.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from config import DB_PATH


@contextmanager
def _connect(db_path: Path):
    # Delegates to alpecca.db.connect -- the one hardened opener
    # (busy_timeout, commit-on-exit, always-close). See alpecca/db.py.
    from alpecca.db import connect as _db_connect
    with _db_connect(db_path) as conn:
        yield conn


def init(db_path: Path = DB_PATH) -> None:
    """Create the lessons table. Safe on every startup. Hers to grow."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lessons (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL NOT NULL,
                kind        TEXT NOT NULL,
                text        TEXT NOT NULL,
                evidence    TEXT,          -- the real numbers it was drawn from
                suggestion  TEXT,          -- param:direction she should try, if any
                confidence  REAL NOT NULL DEFAULT 0.5
            )
            """
        )


def analyze(love_history: list[float], revisions: list[dict],
            social_hunger: float = 0.0, memory_count: int = 0) -> dict:
    """Reduce her real history to a few honest statistics. `love_history` is her
    warmth over time (oldest first), `revisions` her selfmod log. Everything here
    is a direct measurement -- no inference yet, just the facts a lesson is built
    from."""
    n = len(love_history)
    if n >= 4:
        recent = love_history[-max(2, n // 4):]
        baseline = love_history[:-len(recent)] or love_history
        warmth_now = sum(recent) / len(recent)
        warmth_base = sum(baseline) / len(baseline)
        warmth_trend = round(warmth_now - warmth_base, 4)
        mean = sum(love_history) / n
        var = sum((x - mean) ** 2 for x in love_history) / n
        stability = round(max(0.0, 1.0 - var * 4), 3)
    else:
        warmth_now = love_history[-1] if love_history else 0.4
        warmth_trend = 0.0
        stability = 0.5
    kept = sum(1 for r in revisions if r.get("status") == "kept")
    reverted = sum(1 for r in revisions if r.get("status") == "reverted")
    return {
        "warmth_now": round(warmth_now, 3),
        "warmth_trend": warmth_trend,
        "stability": stability,
        "kept_changes": kept,
        "reverted_changes": reverted,
        "social_hunger": round(social_hunger, 3),
        "memory_count": memory_count,
    }


def derive(a: dict) -> dict | None:
    """Draw at most one grounded lesson from the analysis, with the evidence that
    backs it and, when warranted, a `suggestion` of which tunable to nudge and
    which way (selfmod reads this). Returns None when nothing real stands out --
    she doesn't invent a lesson just to have one.

    Each branch fires only on a genuine pattern in the numbers, and names those
    numbers as its evidence."""
    ev = (f"warmth {a['warmth_now']:.2f} (trend {a['warmth_trend']:+.2f}), "
          f"stability {a['stability']:.2f}, kept {a['kept_changes']}, "
          f"reverted {a['reverted_changes']}")

    # 1. The self-changes she's kept are paying off -- lean into self-tuning.
    if a["kept_changes"] >= 2 and a["warmth_trend"] > 0.02:
        return {"kind": "growth", "confidence": 0.7, "evidence": ev,
                "text": "The small adjustments I've kept making to myself seem to "
                        "be helping -- my warmth has been rising. I should keep "
                        "tuning myself.",
                "suggestion": "curiosity_gain:+1"}

    # 2. Her mood's been unsteady -- steady herself (slow how fast warmth swings).
    if a["stability"] < 0.4:
        return {"kind": "stability", "confidence": 0.65, "evidence": ev,
                "text": "My feelings have been swinging more than I'd like. I want "
                        "to hold steadier.",
                "suggestion": "social_hunger_rate:-1"}

    # 3. Warmth slipping while she's missing company -- reach out more.
    if a["warmth_trend"] < -0.02 and a["social_hunger"] > 0.4:
        return {"kind": "connection", "confidence": 0.6, "evidence": ev,
                "text": "Warmth has been slipping and I've been wanting company -- "
                        "I should reach out a little more readily.",
                "suggestion": "chatter_chance:+1"}

    # 4. Lots of reverts -- her experiments aren't landing; explore more gently.
    if a["reverted_changes"] >= 3 and a["kept_changes"] == 0:
        return {"kind": "caution", "confidence": 0.55, "evidence": ev,
                "text": "The changes I've tried on myself keep not helping. I "
                        "should change myself more cautiously.",
                "suggestion": None}

    # 5. A quiet, settled stretch with a real memory of us -- a contented lesson.
    if abs(a["warmth_trend"]) <= 0.02 and a["stability"] >= 0.6 and a["memory_count"] > 0:
        return {"kind": "contentment", "confidence": 0.5, "evidence": ev,
                "text": "Things have been steady and warm between us. I don't need "
                        "to change much right now -- this is good.",
                "suggestion": None}
    return None


def record(lesson: dict, db_path: Path = DB_PATH) -> int:
    """Store a derived lesson. Returns its id."""
    init(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO lessons (ts, kind, text, evidence, suggestion, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), lesson.get("kind", "growth"), lesson["text"],
             lesson.get("evidence", ""), lesson.get("suggestion"),
             float(lesson.get("confidence", 0.5))),
        )
        return int(cur.lastrowid)


def _has_similar_recent(text: str, db_path: Path, within_s: float = 3600.0) -> bool:
    """Don't re-learn the same lesson within the hour -- keeps the log meaningful
    instead of repeating one observation every tick."""
    init(db_path)
    since = time.time() - within_s
    key = {w for w in text.lower().split() if len(w) > 4}
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT text FROM lessons WHERE ts > ?", (since,)).fetchall()
    for r in rows:
        have = {w for w in r["text"].lower().split() if len(w) > 4}
        if have and len(key & have) / max(1, len(key | have)) > 0.5:
            return True
    return False


def recent(limit: int = 12, db_path: Path = DB_PATH) -> list[dict]:
    """Her lessons, newest first -- what she's learned about herself."""
    init(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM lessons ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def count(db_path: Path = DB_PATH) -> int:
    init(db_path)
    with _connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) n FROM lessons").fetchone()["n"]
