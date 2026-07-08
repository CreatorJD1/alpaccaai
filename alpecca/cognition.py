"""Unified cognition records for Alpecca.

This module gives the app one durable place to record what Alpecca observed,
what she is trying to do, and which improvements she has noticed. It keeps the
house and profile UI grounded in real backend state instead of inferred vibes.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config import DB_PATH

INTENTS = {
    "listening",
    "replying",
    "observing",
    "remembering",
    "questioning",
    "creating",
    "self-reviewing",
    "resting",
    "waiting",
}

APPROVAL_AUTOMATIC = "automatic"
APPROVAL_ASK_FIRST = "ask_first"
APPROVAL_NEVER_AUTO = "never_auto"
PROPOSAL_STATUSES = {"noticed", "planned", "testing", "accepted", "rejected", "superseded"}
CLOSED_PROPOSAL_STATUSES = {"accepted", "rejected", "superseded"}
EVALUATION_PHASES = {"noticed", "baseline", "planned", "testing", "result", "accepted", "rejected"}


@dataclass
class CognitionObservation:
    source: str
    content: str
    confidence: float = 1.0
    room: str = ""
    privacy_class: str = "local"
    metadata: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def clean(self) -> "CognitionObservation":
        self.source = (self.source or "unknown")[:48]
        self.content = (self.content or "").strip()[:1000]
        self.room = (self.room or "")[:80]
        self.privacy_class = (self.privacy_class or "local")[:40]
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        return self


@dataclass
class IntentState:
    name: str
    reason: str = ""
    target: str = ""
    confidence: float = 1.0
    ts: float = field(default_factory=time.time)

    def clean(self) -> "IntentState":
        if self.name not in INTENTS:
            self.name = "waiting"
        self.reason = (self.reason or "")[:500]
        self.target = (self.target or "")[:160]
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        return self


@dataclass
class ActionProposal:
    action: str
    reason: str
    approval: str = APPROVAL_ASK_FIRST
    risk: str = "low"
    status: str = "noticed"
    evidence: str = ""
    result: str = ""
    payload: dict[str, Any] | str = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def clean(self) -> "ActionProposal":
        self.action = (self.action or "").strip()[:240]
        self.reason = (self.reason or "").strip()[:800]
        self.evidence = (self.evidence or "").strip()[:1000]
        self.result = (self.result or "").strip()[:1000]
        if isinstance(self.payload, str):
            self.payload = self.payload.strip()[:4000]
        else:
            try:
                self.payload = json.dumps(self.payload if self.payload is not None else {}, ensure_ascii=True)[:4000]
            except Exception:
                self.payload = "{}"
        if self.approval not in {APPROVAL_AUTOMATIC, APPROVAL_ASK_FIRST, APPROVAL_NEVER_AUTO}:
            self.approval = APPROVAL_ASK_FIRST
        if self.risk not in {"low", "medium", "high"}:
            self.risk = "low"
        if self.status not in PROPOSAL_STATUSES:
            self.status = "noticed"
        return self


@dataclass
class ProposalEvaluation:
    proposal_id: int
    phase: str = "testing"
    metric: str = ""
    evidence: str = ""
    test: str = ""
    outcome: str = ""
    score: float | None = None
    supports_status: str = ""
    ts: float = field(default_factory=time.time)

    def clean(self) -> "ProposalEvaluation":
        self.proposal_id = int(self.proposal_id)
        self.phase = (self.phase or "testing").strip()
        if self.phase not in EVALUATION_PHASES:
            self.phase = "testing"
        self.metric = (self.metric or "").strip()[:160]
        self.evidence = (self.evidence or "").strip()[:1200]
        self.test = (self.test or "").strip()[:1200]
        self.outcome = (self.outcome or "").strip()[:1200]
        self.supports_status = (self.supports_status or "").strip()
        if self.supports_status and self.supports_status not in PROPOSAL_STATUSES:
            self.supports_status = ""
        if self.score is not None:
            self.score = max(0.0, min(1.0, float(self.score)))
        return self


@dataclass
class ChatTurn:
    user_text: str
    reply: str
    room: str = ""
    mood: str = ""
    intent: str = "replying"
    model_use: dict[str, Any] = field(default_factory=dict)
    memory_evidence: list[dict[str, Any]] = field(default_factory=list)
    observation_id: int | None = None
    privacy_class: str = "personal"
    ts: float = field(default_factory=time.time)

    def clean(self) -> "ChatTurn":
        self.user_text = (self.user_text or "").strip()[:2000]
        self.reply = (self.reply or "").strip()[:4000]
        self.room = (self.room or "")[:80]
        self.mood = (self.mood or "")[:80]
        self.intent = (self.intent or "replying")[:80]
        self.privacy_class = (self.privacy_class or "personal")[:40]
        if self.observation_id is not None:
            self.observation_id = int(self.observation_id)
        return self


@contextmanager
def _connect(db_path: Path = DB_PATH):
    # Delegates to alpecca.db.connect -- the one hardened opener
    # (busy_timeout, commit-on-exit, always-close). See alpecca/db.py.
    from alpecca.db import connect as _db_connect
    with _db_connect(db_path) as conn:
        yield conn


def init_db(db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cognition_observations (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                ts             REAL NOT NULL,
                source         TEXT NOT NULL,
                room           TEXT,
                content        TEXT NOT NULL,
                confidence     REAL NOT NULL,
                privacy_class  TEXT NOT NULL,
                metadata       TEXT,
                remembered     INTEGER NOT NULL DEFAULT 0,
                memory_id      INTEGER
            );

            CREATE TABLE IF NOT EXISTS cognition_intent (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                ts          REAL NOT NULL,
                name        TEXT NOT NULL,
                reason      TEXT,
                target      TEXT,
                confidence  REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS action_proposals (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        REAL NOT NULL,
                action    TEXT NOT NULL,
                reason    TEXT NOT NULL,
                approval  TEXT NOT NULL,
                risk      TEXT NOT NULL,
                status    TEXT NOT NULL,
                evidence  TEXT,
                result    TEXT,
                payload   TEXT
            );

            CREATE TABLE IF NOT EXISTS proposal_evaluations (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id      INTEGER NOT NULL,
                ts               REAL NOT NULL,
                phase            TEXT NOT NULL,
                metric           TEXT,
                evidence         TEXT,
                test             TEXT,
                outcome          TEXT,
                score            REAL,
                supports_status  TEXT,
                FOREIGN KEY(proposal_id) REFERENCES action_proposals(id)
            );

            CREATE TABLE IF NOT EXISTS chat_turns (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                ts               REAL NOT NULL,
                room             TEXT,
                mood             TEXT,
                intent           TEXT,
                user_text        TEXT NOT NULL,
                reply            TEXT NOT NULL,
                model_use        TEXT,
                memory_evidence  TEXT,
                observation_id   INTEGER,
                privacy_class    TEXT NOT NULL,
                FOREIGN KEY(observation_id) REFERENCES cognition_observations(id)
            );
            """
        )
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(cognition_observations)")}
        if "remembered" not in cols:
            conn.execute("ALTER TABLE cognition_observations ADD COLUMN remembered INTEGER NOT NULL DEFAULT 0")
        if "memory_id" not in cols:
            conn.execute("ALTER TABLE cognition_observations ADD COLUMN memory_id INTEGER")
        proposal_cols = {r["name"] for r in conn.execute("PRAGMA table_info(action_proposals)")}
        if "payload" not in proposal_cols:
            conn.execute("ALTER TABLE action_proposals ADD COLUMN payload TEXT")


def _json_dict(value: Any) -> str:
    try:
        return json.dumps(value if value is not None else {}, ensure_ascii=True)
    except Exception:
        return "{}"


def _json_list(value: Any) -> str:
    try:
        return json.dumps(value if isinstance(value, list) else [], ensure_ascii=True)
    except Exception:
        return "[]"


def proposal_payload(row: dict | None) -> dict[str, Any]:
    if not row:
        return {}
    raw = row.get("payload") if isinstance(row, dict) else None
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def record_observation(obs: CognitionObservation, db_path: Path = DB_PATH) -> int | None:
    obs = obs.clean()
    if not obs.content:
        return None
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO cognition_observations "
            "(ts, source, room, content, confidence, privacy_class, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                obs.ts,
                obs.source,
                obs.room,
                obs.content,
                obs.confidence,
                obs.privacy_class,
                json.dumps(obs.metadata, ensure_ascii=True),
            ),
        )
        return int(cur.lastrowid)


def recent_observations(limit: int = 12, db_path: Path = DB_PATH) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM cognition_observations ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["metadata"] = json.loads(d.get("metadata") or "{}")
        except Exception:
            d["metadata"] = {}
        out.append(d)
    return out


def unremembered_observations(limit: int = 20, db_path: Path = DB_PATH) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM cognition_observations "
            "WHERE remembered = 0 ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["metadata"] = json.loads(d.get("metadata") or "{}")
        except Exception:
            d["metadata"] = {}
        out.append(d)
    return out


def mark_observation_remembered(obs_id: int, memory_id: int | None,
                                db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE cognition_observations SET remembered=1, memory_id=? WHERE id=?",
            (memory_id, obs_id),
        )


def record_chat_turn(turn: ChatTurn, db_path: Path = DB_PATH) -> int | None:
    turn = turn.clean()
    if not turn.user_text or not turn.reply:
        return None
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO chat_turns "
            "(ts, room, mood, intent, user_text, reply, model_use, "
            "memory_evidence, observation_id, privacy_class) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                turn.ts,
                turn.room,
                turn.mood,
                turn.intent,
                turn.user_text,
                turn.reply,
                _json_dict(turn.model_use),
                _json_list(turn.memory_evidence),
                turn.observation_id,
                turn.privacy_class,
            ),
        )
        return int(cur.lastrowid)


def recent_chat_turns(limit: int = 8, db_path: Path = DB_PATH) -> list[dict]:
    limit = max(1, min(50, int(limit)))
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM chat_turns ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["model_use"] = json.loads(d.get("model_use") or "{}")
        except Exception:
            d["model_use"] = {}
        try:
            d["memory_evidence"] = json.loads(d.get("memory_evidence") or "[]")
        except Exception:
            d["memory_evidence"] = []
        out.append(d)
    return out


GROUNDING_CONTEXT_TERMS = {
    "offline",
    "online",
    "library",
    "observatory",
    "workshop",
    "screen",
    "camera",
    "room",
    "activated",
}


def review_chat_grounding(turns: list[dict]) -> dict:
    """Review recent chat turns for obvious grounding risks.

    This is intentionally conservative and deterministic: it does not judge
    style or truth broadly. It only flags patterns that have already caused
    trouble in the app, such as treating background context as if the person
    just said it, or making memory claims without memory evidence attached.
    """
    issues = []
    for turn in turns or []:
        user = str(turn.get("user_text", ""))
        reply = str(turn.get("reply", ""))
        evidence = turn.get("memory_evidence") or []
        evidence_text = " ".join(str(e.get("content", "")) for e in evidence if isinstance(e, dict))
        combined_ground = f"{user} {evidence_text}".lower()
        reply_lower = reply.lower()
        safe_echo_fallback = (
            reply_lower.startswith("you said:")
            or reply_lower.startswith("i hear you:")
            or "basic live mode" in reply_lower
            or "what should we focus on next" in reply_lower
        )
        turn_issues = []
        context_terms = sorted(
            term for term in GROUNDING_CONTEXT_TERMS
            if term in reply_lower
            and term not in combined_ground
            and not (safe_echo_fallback and term == "offline")
        )
        if context_terms:
            turn_issues.append({
                "code": "context_claim_without_current_evidence",
                "terms": context_terms[:6],
                "detail": "Reply used app/room/context terms that were not present in the user text or recalled memory evidence.",
            })
        if ("remember" in reply_lower or "memory" in reply_lower) and not evidence:
            turn_issues.append({
                "code": "memory_claim_without_evidence",
                "detail": "Reply referenced memory without attached memory evidence.",
            })
        model_use = turn.get("model_use") or {}
        if isinstance(model_use, dict) and model_use.get("fallback") and (
            not safe_echo_fallback or bool(turn_issues)
        ):
            turn_issues.append({
                "code": "offline_fallback_reply",
                "detail": "Fallback reply also carried unsupported context or memory claims.",
            })
        if turn_issues:
            issues.append({
                "chat_turn_id": turn.get("id"),
                "room": turn.get("room", ""),
                "user_text": user[:220],
                "reply": reply[:320],
                "issues": turn_issues,
            })
    reviewed = len(turns or [])
    risk_count = len(issues)
    score = 1.0 if reviewed == 0 else max(0.0, round(1.0 - risk_count / reviewed, 3))
    return {
        "reviewed": reviewed,
        "risk_count": risk_count,
        "grounding_score": score,
        "issues": issues,
        "status": "needs_review" if risk_count else "grounded",
    }


def set_intent(intent: IntentState, db_path: Path = DB_PATH) -> dict:
    intent = intent.clean()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO cognition_intent (id, ts, name, reason, target, confidence)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                ts=excluded.ts,
                name=excluded.name,
                reason=excluded.reason,
                target=excluded.target,
                confidence=excluded.confidence
            """,
            (intent.ts, intent.name, intent.reason, intent.target, intent.confidence),
        )
    return asdict(intent)


def current_intent(db_path: Path = DB_PATH) -> dict:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM cognition_intent WHERE id = 1").fetchone()
    if row is None:
        return asdict(IntentState("waiting", "Alpecca is awake and waiting."))
    return dict(row)


def propose_action(proposal: ActionProposal, db_path: Path = DB_PATH) -> int | None:
    proposal = proposal.clean()
    if not proposal.action or not proposal.reason:
        return None
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO action_proposals "
            "(ts, action, reason, approval, risk, status, evidence, result, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                proposal.ts,
                proposal.action,
                proposal.reason,
                proposal.approval,
                proposal.risk,
                proposal.status,
                proposal.evidence,
                proposal.result,
                proposal.payload,
            ),
        )
        return int(cur.lastrowid)


def open_action_proposal_by_action(action: str, db_path: Path = DB_PATH) -> dict | None:
    """Return the newest open proposal with this action, if one exists."""
    action = (action or "").strip()[:220]
    if not action:
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM action_proposals "
            "WHERE action=? AND status NOT IN ('accepted', 'rejected', 'superseded') "
            "ORDER BY id DESC LIMIT 1",
            (action,),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        counts = _proposal_evaluation_counts(conn, [int(out["id"])])
        out["evaluation_count"] = counts.get(int(out["id"]), 0)
        return out


def open_action_proposals_by_action(action: str, limit: int = 50,
                                    db_path: Path = DB_PATH) -> list[dict]:
    """Return open proposals with this action, newest first."""
    action = (action or "").strip()[:220]
    if not action:
        return []
    limit = max(1, min(200, int(limit)))
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM action_proposals "
            "WHERE action=? AND status NOT IN ('accepted', 'rejected', 'superseded') "
            "ORDER BY id DESC LIMIT ?",
            (action, limit),
        ).fetchall()
        out = [dict(row) for row in rows]
        counts = _proposal_evaluation_counts(conn, [int(row["id"]) for row in out])
        for row in out:
            row["evaluation_count"] = counts.get(int(row["id"]), 0)
        return out


def refresh_action_proposal(proposal_id: int, *, reason: str = "",
                            evidence: str = "", status: str = "",
                            result: str = "",
                            db_path: Path = DB_PATH) -> dict:
    """Refresh an open proposal with newer evidence without changing approval.

    This is how repeated self-review keeps one Workshop card current instead of
    creating duplicate cards. Accepted/rejected proposals are preserved as
    historical decisions and cannot be refreshed through this helper.
    """
    row = get_action_proposal(proposal_id, db_path=db_path)
    if row is None:
        raise KeyError(proposal_id)
    if row.get("status") in CLOSED_PROPOSAL_STATUSES:
        return row
    reason = (reason or row.get("reason") or "").strip()[:1000]
    evidence = (evidence or row.get("evidence") or "").strip()[:1000]
    status = (status or row.get("status") or "noticed").strip()
    result = (result or row.get("result") or "").strip()[:1000]
    if status not in PROPOSAL_STATUSES or status in {"accepted", "rejected"}:
        status = row.get("status") or "noticed"
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE action_proposals SET ts=?, reason=?, evidence=?, status=?, result=? WHERE id=?",
            (time.time(), reason, evidence, status, result, int(proposal_id)),
        )
    refreshed = get_action_proposal(proposal_id, db_path=db_path) or {}
    refreshed["deduped"] = True
    return refreshed


def upsert_action_proposal(proposal: ActionProposal, db_path: Path = DB_PATH) -> dict:
    """Create a proposal or refresh the newest open card with the same action."""
    proposal = proposal.clean()
    existing = open_action_proposal_by_action(proposal.action, db_path=db_path)
    if existing:
        return refresh_action_proposal(
            int(existing["id"]),
            reason=proposal.reason,
            evidence=proposal.evidence,
            status=proposal.status,
            result=proposal.result,
            db_path=db_path,
        )
    proposal_id = propose_action(proposal, db_path=db_path)
    return get_action_proposal(proposal_id, db_path=db_path) if proposal_id else {}


def compact_duplicate_open_proposals(limit: int = 250, db_path: Path = DB_PATH) -> dict:
    """Close older duplicate open proposals while preserving their evidence."""
    limit = max(1, min(1000, int(limit)))
    changed: list[dict] = []
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM action_proposals "
            "WHERE status NOT IN ('accepted', 'rejected', 'superseded') "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        newest_by_action: dict[str, int] = {}
        for row in [dict(r) for r in rows]:
            action = str(row.get("action") or "")
            if not action:
                continue
            if action not in newest_by_action:
                newest_by_action[action] = int(row["id"])
                continue
            keeper = newest_by_action[action]
            result = f"Superseded by duplicate open proposal #{keeper}."
            conn.execute(
                "UPDATE action_proposals SET status='superseded', result=? WHERE id=?",
                (result, int(row["id"])),
            )
            changed.append({
                "id": int(row["id"]),
                "action": action,
                "superseded_by": keeper,
            })
    return {
        "ok": True,
        "closed": len(changed),
        "superseded": changed,
    }


def _proposal_evaluation_counts(conn: sqlite3.Connection, proposal_ids: list[int]) -> dict[int, int]:
    if not proposal_ids:
        return {}
    marks = ",".join("?" for _ in proposal_ids)
    rows = conn.execute(
        f"SELECT proposal_id, COUNT(*) AS c FROM proposal_evaluations "
        f"WHERE proposal_id IN ({marks}) GROUP BY proposal_id",
        proposal_ids,
    ).fetchall()
    return {int(r["proposal_id"]): int(r["c"]) for r in rows}


def recent_action_proposals(limit: int = 10, db_path: Path = DB_PATH,
                            include_evaluation_counts: bool = True) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM action_proposals ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = [dict(r) for r in rows]
        if include_evaluation_counts:
            counts = _proposal_evaluation_counts(conn, [int(r["id"]) for r in out])
            for row in out:
                row["evaluation_count"] = counts.get(int(row["id"]), 0)
    return out


def get_action_proposal(proposal_id: int, db_path: Path = DB_PATH) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM action_proposals WHERE id=?", (int(proposal_id),)
        ).fetchone()
    return dict(row) if row else None


def proposal_decision_allowed(row: dict, status: str, approved_by_user: bool) -> tuple[bool, str]:
    """Safety gate for proposal lifecycle changes.

    Automatic proposals may move through the board freely. Anything ask-first or
    never-auto needs a real user approval before it can be accepted. Never-auto
    remains impossible to execute automatically; accepting only means the person
    approved the idea as a plan, not that Alpecca may perform it unassisted.
    """
    status = (status or "").strip()
    if status not in PROPOSAL_STATUSES:
        return False, f"unknown status: {status}"
    if status != "accepted":
        return True, ""
    approval = row.get("approval") or APPROVAL_ASK_FIRST
    risk = row.get("risk") or "low"
    if approval == APPROVAL_AUTOMATIC and risk == "low":
        return True, ""
    if not approved_by_user:
        return False, "accepting this proposal requires explicit user approval"
    return True, ""


def update_action_proposal(proposal_id: int, status: str, result: str = "",
                           approved_by_user: bool = False,
                           db_path: Path = DB_PATH) -> dict:
    row = get_action_proposal(proposal_id, db_path=db_path)
    if row is None:
        raise KeyError(proposal_id)
    status = (status or "").strip()
    ok, reason = proposal_decision_allowed(row, status, approved_by_user)
    if not ok:
        raise PermissionError(reason)
    result = (result or "").strip()[:1000]
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE action_proposals SET status=?, result=? WHERE id=?",
            (status, result, int(proposal_id)),
        )
    updated = get_action_proposal(proposal_id, db_path=db_path) or {}
    updated["decision"] = "approved_by_user" if approved_by_user else "system"
    return updated


def record_proposal_evaluation(evaluation: ProposalEvaluation,
                               db_path: Path = DB_PATH) -> dict:
    evaluation = evaluation.clean()
    if get_action_proposal(evaluation.proposal_id, db_path=db_path) is None:
        raise KeyError(evaluation.proposal_id)
    if not (evaluation.evidence or evaluation.test or evaluation.outcome or evaluation.metric):
        raise ValueError("evaluation needs evidence, test, outcome, or metric")
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO proposal_evaluations "
            "(proposal_id, ts, phase, metric, evidence, test, outcome, score, supports_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evaluation.proposal_id,
                evaluation.ts,
                evaluation.phase,
                evaluation.metric,
                evaluation.evidence,
                evaluation.test,
                evaluation.outcome,
                evaluation.score,
                evaluation.supports_status,
            ),
        )
        row = conn.execute(
            "SELECT * FROM proposal_evaluations WHERE id=?",
            (int(cur.lastrowid),),
        ).fetchone()
    return dict(row)


def proposal_evaluations(proposal_id: int | None = None, limit: int = 25,
                         db_path: Path = DB_PATH) -> list[dict]:
    limit = max(1, min(100, int(limit)))
    with _connect(db_path) as conn:
        if proposal_id is None:
            rows = conn.execute(
                "SELECT * FROM proposal_evaluations ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM proposal_evaluations WHERE proposal_id=? "
                "ORDER BY id DESC LIMIT ?",
                (int(proposal_id), limit),
            ).fetchall()
    return [dict(r) for r in rows]


def recent_recursive_engagement(limit: int = 8, db_path: Path = DB_PATH) -> list[dict]:
    """Recent self-feedback records from Alpecca's promptless living loop."""
    limit = max(1, min(50, int(limit)))
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT pe.*, ap.action, ap.status, ap.approval "
            "FROM proposal_evaluations pe "
            "LEFT JOIN action_proposals ap ON ap.id = pe.proposal_id "
            "WHERE pe.metric = ? "
            "ORDER BY pe.id DESC LIMIT ?",
            ("autonomous_recursive_engagement", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def recursive_engagement_scorecard(db_path: Path = DB_PATH) -> dict:
    """Observable health check for the promptless observe-learn-act loop.

    This is intentionally evidence-based. It does not infer consciousness; it
    reports whether recent stored records prove that Alpecca observed her world,
    asked a grounded question, stored memory evidence, recorded self-feedback,
    and proposed a bounded next action.
    """
    observations = recent_observations(limit=40, db_path=db_path)
    recursive = recent_recursive_engagement(limit=12, db_path=db_path)
    proposals = recent_action_proposals(limit=25, db_path=db_path)
    intent = current_intent(db_path=db_path)
    living_observations = [
        row for row in observations
        if str(row.get("source") or "") == "living_loop"
    ]
    living_with_question = [
        row for row in living_observations
        if isinstance(row.get("metadata"), dict) and str(row["metadata"].get("question") or "").strip()
    ]
    living_remembered = [
        row for row in living_observations
        if int(row.get("remembered") or 0) == 1 and row.get("memory_id") is not None
    ]
    engagement_proposals = [
        row for row in proposals
        if str(row.get("action") or "") == "Strengthen autonomous recursive engagement"
        and str(row.get("status") or "") not in CLOSED_PROPOSAL_STATUSES
    ]
    latest_observation = living_observations[0] if living_observations else None
    latest_question = ""
    if latest_observation and isinstance(latest_observation.get("metadata"), dict):
        latest_question = str(latest_observation["metadata"].get("question") or "")
    latest_learning = recursive[0] if recursive else None
    latest_evidence = str((latest_learning or {}).get("evidence") or "")
    activated_system = ""
    selection_reason = ""
    if latest_evidence:
        for part in latest_evidence.split(";"):
            key, _, value = part.strip().partition("=")
            if key == "activated":
                activated_system = value.strip()
            elif key == "selection_reason":
                selection_reason = value.strip()
    creator_context_observed = bool(
        latest_observation
        and isinstance(latest_observation.get("metadata"), dict)
        and latest_observation["metadata"].get("speaker") == "creator"
    )
    checks = [
        {
            "id": "observe_world",
            "label": "Recorded a living-loop world observation",
            "ok": bool(living_observations),
            "evidence": f"{len(living_observations)} recent living-loop observation(s)",
        },
        {
            "id": "ask_question",
            "label": "Asked a grounded self-question",
            "ok": bool(living_with_question),
            "evidence": latest_question,
        },
        {
            "id": "remember_evidence",
            "label": "Persisted the observation into memory",
            "ok": bool(living_remembered),
            "evidence": f"{len(living_remembered)} remembered living-loop observation(s)",
        },
        {
            "id": "self_feedback",
            "label": "Recorded recursive self-feedback",
            "ok": bool(recursive),
            "evidence": str((recursive[0] if recursive else {}).get("outcome") or ""),
        },
        {
            "id": "bounded_next_action",
            "label": "Maintains a bounded improvement/action proposal",
            "ok": bool(engagement_proposals),
            "evidence": str((engagement_proposals[0] if engagement_proposals else {}).get("result") or ""),
        },
    ]
    passed = sum(1 for check in checks if check["ok"])
    return {
        "schema": "alpecca.recursive_engagement_scorecard.v1",
        "ok": passed == len(checks),
        "score": round(passed / max(1, len(checks)), 3),
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "current_intent": intent,
        "latest_question": latest_question,
        "latest_observation_id": latest_observation.get("id") if latest_observation else None,
        "latest_memory_id": latest_observation.get("memory_id") if latest_observation else None,
        "latest_learning_record": latest_learning,
        "latest_engagement_proposal": engagement_proposals[0] if engagement_proposals else None,
        "curriculum": {
            "activated_system": activated_system,
            "selection_reason": selection_reason,
            "creator_context_observed": creator_context_observed,
            "mode": "evidence_first",
            "next_gate": next((check["id"] for check in checks if not check["ok"]), "continue_exploration"),
        },
        "research_mapping": {
            "ReAct": "interleave grounded observations with safe actions",
            "Generative Agents": "store observations, reflections, and plans as durable state",
            "Reflexion": "record verbal self-feedback for later attempts",
            "Voyager": "maintain an open-ended curriculum through safe next actions",
        },
    }


def record_behavior_improvement_review(lesson: dict | None = None,
                                       analysis: dict | None = None,
                                       db_path: Path = DB_PATH) -> dict:
    """Turn a self-learning lesson into one bounded, evidence-backed queue item.

    This keeps the Workshop from filling with vague "review behavior" cards. The
    action stays stable so repeated reviews refresh one card, while the proposal
    and evaluation carry the concrete evidence, test, and bounded next step.
    """
    lesson = lesson or {}
    analysis = analysis or lesson.get("analysis") or {}
    lesson_text = str(lesson.get("text") or "Review one behavior pattern from recent self-state.")
    lesson_kind = str(lesson.get("kind") or "behavior").strip()[:80] or "behavior"
    suggestion = str(lesson.get("suggestion") or "").strip()
    lesson_evidence = str(lesson.get("evidence") or "").strip()
    if not lesson_evidence and analysis:
        lesson_evidence = "; ".join(
            f"{key}={value}" for key, value in analysis.items()
            if key in {"warmth_now", "warmth_trend", "stability", "kept_changes",
                       "reverted_changes", "social_hunger", "memory_count"}
        )
    bounded_test = (
        f"Observe whether the {lesson_kind} lesson improves grounded replies and "
        "self-tuning before keeping any behavior change."
    )
    next_step = (
        f"Next bounded step: trial {suggestion} through selfmod only after user-visible evidence."
        if suggestion else
        "Next bounded step: keep observing; do not change a tunable until evidence points to one."
    )
    evidence = (
        f"lesson_kind={lesson_kind}; lesson={lesson_text}; evidence={lesson_evidence or 'no numeric evidence supplied'}"
    )[:1000]
    proposal = upsert_action_proposal(ActionProposal(
        action="Review one behavior improvement",
        reason=lesson_text,
        approval=APPROVAL_ASK_FIRST,
        risk="low",
        status="testing",
        evidence=evidence,
        result=next_step,
    ), db_path=db_path)
    proposal_id = int(proposal.get("id") or 0)
    evaluation = None
    reused = False
    if proposal_id:
        recent = proposal_evaluations(proposal_id, limit=8, db_path=db_path)
        for row in recent:
            if row.get("metric") == "behavior_self_review" and row.get("evidence") == evidence:
                evaluation = row
                reused = True
                break
        if evaluation is None:
            evaluation = record_proposal_evaluation(ProposalEvaluation(
                proposal_id=proposal_id,
                phase="testing",
                metric="behavior_self_review",
                evidence=evidence,
                test=bounded_test,
                outcome=next_step,
                score=float(lesson.get("confidence", 0.5) or 0.5),
                supports_status="testing",
            ), db_path=db_path)
    return {
        "proposal": proposal,
        "evaluation": evaluation,
        "evaluation_reused": reused,
        "lesson": lesson,
        "analysis": analysis,
        "next_step": next_step,
    }


def improvement_summary(db_path: Path = DB_PATH) -> dict:
    """Compact queue view for House HQ, Mindscape, and quick status cards."""
    proposals = recent_action_proposals(limit=50, db_path=db_path)
    evaluations = proposal_evaluations(limit=50, db_path=db_path)
    by_status: dict[str, int] = {}
    by_approval: dict[str, int] = {}
    open_items = []
    for row in proposals:
        status = str(row.get("status") or "noticed")
        approval = str(row.get("approval") or APPROVAL_ASK_FIRST)
        by_status[status] = by_status.get(status, 0) + 1
        by_approval[approval] = by_approval.get(approval, 0) + 1
        if status not in CLOSED_PROPOSAL_STATUSES:
            open_items.append(row)
    latest = open_items[0] if open_items else (proposals[0] if proposals else None)
    latest_eval = None
    if latest:
        for ev in evaluations:
            if int(ev.get("proposal_id") or 0) == int(latest.get("id") or 0):
                latest_eval = ev
                break
    return {
        "recent_total": len(proposals),
        "recent_open": len(open_items),
        "total": len(proposals),
        "open": len(open_items),
        "by_status": by_status,
        "by_approval": by_approval,
        "latest": latest,
        "latest_evaluation": latest_eval,
        "recent_evaluation_count": len(evaluations),
    }


def _handoff_line(value: Any, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    return " ".join(text.split())


def improvement_handoff_markdown(limit: int = 8, db_path: Path = DB_PATH) -> dict:
    """Build a local, approval-gated handoff packet for Codex/Claude/ChatGPT.

    This does not execute any change. It turns Alpecca's current evidence-backed
    Workshop queue into a concise Markdown brief the person can paste into an
    external coding assistant when Alpecca is off-platform.
    """
    limit = max(1, min(20, int(limit)))
    proposals = recent_action_proposals(limit=50, db_path=db_path)
    evaluations = proposal_evaluations(limit=100, db_path=db_path)
    open_items = [
        row for row in proposals
        if str(row.get("status") or "") not in CLOSED_PROPOSAL_STATUSES
    ][:limit]
    eval_by_proposal: dict[int, list[dict]] = {}
    for ev in evaluations:
        eval_by_proposal.setdefault(int(ev.get("proposal_id") or 0), []).append(ev)

    lines = [
        "# Alpecca Self-Improvement Handoff",
        "",
        "Use this packet as a bounded implementation brief for Alpecca.",
        "Do not grant autonomous file edits, account actions, paid API use, or cloud uploads.",
        "Every change should stay approval-gated, tested, and recorded back into the Workshop queue.",
        "",
        "## Current Goal",
        "Improve Alpecca's real AI core, House HQ embodiment, movement, voice, memory, perception, and recursive self-review while preserving her identity and safety boundaries.",
        "",
        "## Safety Contract",
        "- Automatic is allowed only for local notes, observations, and memory records.",
        "- Ask first before code edits, file access, network jobs, model changes, or long compute jobs.",
        "- Never automate deletes, account actions, paid usage, or private cloud uploads.",
        "- Keep Alpecca honest: model self-state and learning behavior without claiming literal consciousness.",
        "",
        "## Open Improvement Queue",
    ]

    if not open_items:
        lines.append("No open proposals are currently waiting. Run a House HQ self-review or living loop first.")
    for index, proposal in enumerate(open_items, start=1):
        pid = int(proposal.get("id") or 0)
        action = _handoff_line(proposal.get("action"), "Untitled improvement")
        reason = _handoff_line(proposal.get("reason"))
        evidence = _handoff_line(proposal.get("evidence"))
        approval = _handoff_line(proposal.get("approval"), APPROVAL_ASK_FIRST)
        risk = _handoff_line(proposal.get("risk"), "low")
        status = _handoff_line(proposal.get("status"), "noticed")
        lines.extend([
            "",
            f"### {index}. Proposal #{pid}: {action}",
            f"- Status: {status}",
            f"- Approval: {approval}",
            f"- Risk: {risk}",
        ])
        if reason:
            lines.append(f"- Reason: {reason}")
        if evidence:
            lines.append(f"- Evidence: {evidence}")
        for ev_index, ev in enumerate((eval_by_proposal.get(pid) or [])[:2], start=1):
            metric = _handoff_line(ev.get("metric"), "evidence")
            test = _handoff_line(ev.get("test"))
            outcome = _handoff_line(ev.get("outcome"))
            ev_line = f"- Evaluation {ev_index}: {metric}"
            if test:
                ev_line += f"; test={test}"
            if outcome:
                ev_line += f"; outcome={outcome}"
            lines.append(ev_line)
        lines.append("- Required output: propose the smallest safe implementation step, tests to run, and the exact evidence to record back into Alpecca.")

    lines.extend([
        "",
        "## Return Evidence",
        "After work is done, record what changed, which tests passed or failed, and whether the proposal should move to planned, testing, accepted, rejected, or superseded.",
    ])

    markdown = "\n".join(lines).strip() + "\n"
    return {
        "format": "markdown",
        "target_tools": ["Codex", "Claude", "ChatGPT"],
        "proposal_count": len(open_items),
        "safety_policy": safety_policy(),
        "markdown": markdown,
    }


def safety_policy() -> dict:
    return {
        "automatic": [
            "record a room observation",
            "write a memory note",
            "write a journal/self-review note",
        ],
        "ask_first": [
            "open files or folders",
            "start long model jobs",
            "send private context to a cloud/deep tier",
            "use web or remote services",
        ],
        "never_auto": [
            "edit code or delete files",
            "change accounts, billing, or credentials",
            "take destructive desktop actions",
            "use paid APIs unless the person explicitly enables them",
        ],
    }


def state(
    *,
    mood: str,
    emotion: dict,
    location: str,
    models: dict,
    senses: dict,
    memories: list[dict],
    memory_counts: dict | None = None,
    journal: dict,
    desires: dict,
    self_report: str,
    capabilities: dict | None = None,
    db_path: Path = DB_PATH,
) -> dict:
    return {
        "intent": current_intent(db_path),
        "mood": mood,
        "emotion": emotion,
        "location": location,
        "models": models,
        "senses": senses,
        "recent_observations": recent_observations(db_path=db_path),
        "recent_chat_turns": recent_chat_turns(db_path=db_path),
        "recalled_memories": memories,
        "memory_counts": memory_counts or {},
        "journal": journal,
        "desires": desires,
        "self_report": self_report,
        "capabilities": capabilities or {},
        "action_proposals": recent_action_proposals(db_path=db_path),
        "proposal_evaluations": proposal_evaluations(db_path=db_path),
        "recursive_engagement": recent_recursive_engagement(db_path=db_path),
        "recursive_engagement_scorecard": recursive_engagement_scorecard(db_path=db_path),
        "improvement_summary": improvement_summary(db_path=db_path),
        "safety_policy": safety_policy(),
    }
