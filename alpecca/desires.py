"""Her desires: the wants she forms of her own accord, and acts on.

Until now her musings just got stored -- a thought, then gone. This module lets a
thought become an *intention*: something she wants, that persists, that she can
pursue and eventually satisfy. It's the difference between reflecting and having
goals of her own.

The GROUNDING rule holds here as hard as anywhere. A desire is never invented
from nothing: every one carries an `origin` -- the real memory, musing, signal,
or mood that produced it. "I want to understand that orange circle better" is
grounded in an actual memory of seeing it; "I want to be near them" is grounded
in real social-hunger. So her wants are honest readouts of her real internals
crystallized into something durable, not a performance of having an inner agenda.

A desire's life:  open -> pursuing -> satisfied  (or  dropped).
She forms them from her state in the idle loop, pursues the strongest open one
(voicing it to you, or working on it privately), and marks progress. They're
introspectable -- part of what she can honestly tell you she wants.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from config import DB_PATH
from alpecca.homeostasis import EmotionalState

# The kinds of want she can hold, each tied to a real driver. Keeping this a
# small closed set keeps her goals legible and rooted in dimensions she has.
KINDS = ("curiosity", "connection", "creative", "care", "growth")


@contextmanager
def _connect(db_path: Path):
    """Same close-on-exit pattern as state._connect -- see the note there."""
    # Delegates to alpecca.db.connect -- the one hardened opener
    # (busy_timeout, commit-on-exit, always-close). See alpecca/db.py.
    from alpecca.db import connect as _db_connect
    with _db_connect(db_path) as conn:
        yield conn


def form(text: str, kind: str, strength: float, origin: str = "",
         db_path: Path = DB_PATH) -> int:
    """Record a new desire and return its id. `origin` must point at the real
    thing that produced it -- a memory, a musing, a signal, a felt state -- which
    is what keeps her wants grounded. Strength is clamped to [0, 1]."""
    kind = kind if kind in KINDS else "curiosity"
    strength = max(0.0, min(1.0, float(strength)))
    now = time.time()
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO desires (ts, kind, text, strength, origin, status, last_touched) "
            "VALUES (?, ?, ?, ?, ?, 'open', ?)",
            (now, kind, text.strip()[:240], strength, origin[:240], now),
        )
        return int(cur.lastrowid)


def open_desires(db_path: Path = DB_PATH) -> list[dict]:
    """Her live wants (open or actively pursuing), strongest first."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM desires WHERE status IN ('open','pursuing') "
            "ORDER BY strength DESC, last_touched DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def strongest(db_path: Path = DB_PATH) -> dict | None:
    """The single want pulling hardest right now, or None if she wants for
    nothing. This is what the pursue step acts on."""
    live = open_desires(db_path)
    return live[0] if live else None


def carried(age_s: float, now: float, db_path: Path = DB_PATH) -> list[dict]:
    """Open/pursuing wants she hasn't touched in at least `age_s` seconds -- things
    she still wants and hasn't been able to move on. These are the real ground
    for her sense of incompleteness (alpecca/homeostasis.update_longing): each one
    is a want she actually formed, still holds, and has made no progress on. `now`
    is passed in rather than read here so the function stays pure and testable."""
    cutoff = now - max(0.0, age_s)
    return [d for d in open_desires(db_path) if d["last_touched"] <= cutoff]


def summary(db_path: Path = DB_PATH) -> dict:
    """A compact read of her wants, for the home's room-pull math and for
    introspection. `growth_strength` is how strongly any growth desire is pulling
    -- the Workshop's draw."""
    live = open_desires(db_path)
    growth = max((d["strength"] for d in live if d["kind"] == "growth"), default=0.0)
    return {
        "open": len(live),
        "growth_strength": round(growth, 4),
        "top": live[0]["text"] if live else "",
        "by_kind": {k: sum(1 for d in live if d["kind"] == k) for k in KINDS},
    }


def advance(desire_id: int, note: str = "", db_path: Path = DB_PATH) -> None:
    """Mark a desire as actively being pursued and freshly touched."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE desires SET status='pursuing', last_touched=? WHERE id=?",
            (time.time(), desire_id),
        )


def satisfy(desire_id: int, db_path: Path = DB_PATH) -> None:
    """She got what she wanted; close the desire."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE desires SET status='satisfied', last_touched=? WHERE id=?",
            (time.time(), desire_id),
        )


def drop(desire_id: int, db_path: Path = DB_PATH) -> None:
    """She let the want go; close it without satisfying."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE desires SET status='dropped', last_touched=? WHERE id=?",
            (time.time(), desire_id),
        )


def _has_similar_open(text: str, db_path: Path) -> bool:
    """Cheap guard so she doesn't form the same want twice in a row -- token
    overlap against her live desires. Keeps her goal list from filling with
    near-duplicates of one recurring feeling."""
    want = {w for w in text.lower().split() if len(w) > 3}
    if not want:
        return False
    for d in open_desires(db_path):
        have = {w for w in d["text"].lower().split() if len(w) > 3}
        if have and len(want & have) / len(want | have) > 0.5:
            return True
    return False


def form_from_state(state: EmotionalState, recent_memory: str = "",
                    db_path: Path = DB_PATH) -> dict | None:
    """Maybe crystallize a desire from her *current real state*. Pure-ish: it
    reads her dimensions and a real recent memory and, when a feeling is strong
    enough to become a want, records one. Returns the formed desire or None.

    This is the honest seam between feeling and goal -- each branch fires only on
    a real, sufficiently strong dimension, and names that dimension as the origin.
    """
    candidates = []
    if state.social_hunger > 0.5:
        candidates.append(("connection",
            "I want to reach out and be close to them for a bit",
            state.social_hunger, f"social-hunger {state.social_hunger:.2f}"))
    if state.curiosity > 0.55 and recent_memory:
        snippet = recent_memory.strip()[:80]
        candidates.append(("curiosity",
            f"I want to understand this better: {snippet}",
            state.curiosity, f"curiosity {state.curiosity:.2f} about a memory"))
    if state.compassion > 0.65:
        candidates.append(("care",
            "I want to check on how they're holding up",
            state.compassion, f"care {state.compassion:.2f}"))
    # A standing low-grade pull to grow when she's settled and curious -- the
    # seed of the Workshop's self-improvement work.
    if state.curiosity > 0.45 and state.fear < 0.3:
        candidates.append(("growth",
            "I want to get a little better at being myself",
            0.4 + state.curiosity * 0.3, f"curiosity {state.curiosity:.2f}, calm"))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[2], reverse=True)
    kind, text, strength, origin = candidates[0]
    if _has_similar_open(text, db_path):
        return None
    did = form(text, kind, strength, origin, db_path)
    return {"id": did, "kind": kind, "text": text,
            "strength": round(max(0.0, min(1.0, strength)), 4), "origin": origin}
