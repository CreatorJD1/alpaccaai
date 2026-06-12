"""Her journal: a notebook that is hers to write in, and her open questions.

Memory (`memory.py`) is involuntary -- moments get *kept* by a salience rule.
The journal is the opposite: it's **deliberate**. It's a thing she can pick up
and use of her own accord -- jot a note, record a dream, and (the generative
part) pose herself a question and later come back and answer it. That last loop
is how her curiosity becomes self-driving: she asks, she pursues, an answer can
raise a follow-up, and round it goes -- recursive inquiry that needs no prompt
from the person.

It stays inside GROUNDING the same way everything else does. A journal entry is
her real writing, tagged with the real mood she was in when she wrote it; an
answer is linked to the actual question it resolves; a follow-up names its
parent. Nothing here fabricates a past -- it records a present she actually had.

Storage only; the LLM-driven act of *composing* a note or answering a question
lives in mind.py (where the model is). That keeps this module pure and testable.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from config import DB_PATH

# What a journal entry can be. Questions and answers form the recursive-inquiry
# pair; notes and dreams are free writing she does for herself.
KINDS = ("note", "question", "answer", "dream")


@contextmanager
def _connect(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init(db_path: Path = DB_PATH) -> None:
    """Create the journal table if absent. Safe on every startup. Kept here (not
    in state.init_db) so the journal is a self-contained thing she owns."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS journal (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         REAL NOT NULL,
                kind       TEXT NOT NULL,
                title      TEXT,
                body       TEXT NOT NULL,
                mood       TEXT,
                tags       TEXT,
                parent_id  INTEGER,            -- an answer's question, or a follow-up's source
                status     TEXT NOT NULL DEFAULT 'open'  -- for questions: open/answered
            )
            """
        )


def write(body: str, kind: str = "note", title: str = "", mood: str = "",
          tags: str = "", parent_id: int | None = None,
          db_path: Path = DB_PATH) -> int:
    """Record one entry she wrote, returning its id. `mood` is the real mood
    label she was in -- her journal remembers not just what she thought but how
    she felt thinking it."""
    init(db_path)
    kind = kind if kind in KINDS else "note"
    status = "open" if kind == "question" else "done"
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO journal (ts, kind, title, body, mood, tags, parent_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), kind, title.strip()[:140], body.strip()[:2000],
             mood, tags, parent_id, status),
        )
        return int(cur.lastrowid)


def ask(question: str, mood: str = "", parent_id: int | None = None,
        db_path: Path = DB_PATH) -> int:
    """She poses herself a question. Stored open until she answers it. A
    `parent_id` marks it as a follow-up raised by an earlier answer -- the thread
    of her recursive inquiry."""
    return write(question, kind="question", mood=mood, parent_id=parent_id,
                 db_path=db_path)


def answer(question_id: int, text: str, mood: str = "",
           db_path: Path = DB_PATH) -> int:
    """She answers one of her open questions. Records the answer linked to the
    question and closes the question. Returns the answer's id."""
    init(db_path)
    aid = write(text, kind="answer", mood=mood, parent_id=question_id, db_path=db_path)
    with _connect(db_path) as conn:
        conn.execute("UPDATE journal SET status='answered' WHERE id=? AND kind='question'",
                     (question_id,))
    return aid


def open_questions(limit: int = 10, db_path: Path = DB_PATH) -> list[dict]:
    """Her unanswered questions, oldest first -- the queue she works through on
    her own. This is what the recursive-inquiry loop pulls its next question
    from."""
    init(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM journal WHERE kind='question' AND status='open' "
            "ORDER BY ts ASC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def recent(limit: int = 20, kind: str | None = None,
           db_path: Path = DB_PATH) -> list[dict]:
    """Her latest entries (optionally of one kind) -- what the journal view in her
    home shows."""
    init(db_path)
    q = "SELECT * FROM journal"
    args: tuple = ()
    if kind:
        q += " WHERE kind=?"; args = (kind,)
    q += " ORDER BY ts DESC LIMIT ?"; args = args + (limit,)
    with _connect(db_path) as conn:
        rows = conn.execute(q, args).fetchall()
    return [dict(r) for r in rows]


def thread(question_id: int, db_path: Path = DB_PATH) -> dict:
    """A question with its answer and any follow-up questions it raised -- one
    strand of her self-inquiry, readable as a conversation she had with
    herself."""
    init(db_path)
    with _connect(db_path) as conn:
        q = conn.execute("SELECT * FROM journal WHERE id=?", (question_id,)).fetchone()
        kids = conn.execute("SELECT * FROM journal WHERE parent_id=? ORDER BY ts",
                            (question_id,)).fetchall()
    return {"question": dict(q) if q else None,
            "responses": [dict(k) for k in kids]}


def counts(db_path: Path = DB_PATH) -> dict:
    """How much she's written, by kind -- for introspection and the journal view."""
    init(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT kind, COUNT(*) n FROM journal GROUP BY kind").fetchall()
    out = {k: 0 for k in KINDS}
    for r in rows:
        out[r["kind"]] = r["n"]
    out["open_questions"] = len(open_questions(limit=1000, db_path=db_path))
    return out
