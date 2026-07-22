"""Evidence-backed affective incident learning.

This module implements a functional analogue of appraisal, conditioned caution,
and safety learning.  It does not diagnose or claim human trauma.  Incidents
must be supplied by a verified runtime or creator action; model-generated text
cannot create one.
"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from config import DB_PATH


SCHEMA = "alpecca.affective-incident.v1"
_CUE_RE = re.compile(r"[^a-z0-9_.:-]+")


def _clamp(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _cue(value: object) -> str:
    normalized = _CUE_RE.sub("-", str(value or "").strip().lower()).strip("-")
    return normalized[:96]


def _text(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


@dataclass(frozen=True)
class IncidentSignal:
    incident_id: int | None = None
    cue: str = ""
    source: str = ""
    summary: str = ""
    activation: float = 0.0
    recovery: float = 1.0
    confidence: float = 0.0
    status: str = "none"

    def as_dict(self) -> dict:
        return {"schema": SCHEMA, **asdict(self)}

    def prompt_note(self) -> str:
        if self.incident_id is None or self.activation < 0.25:
            return ""
        return (
            "A verified prior incident matching the current runtime cue has "
            f"activation {self.activation:.2f} and recovery {self.recovery:.2f}. "
            "Treat this as a reason to check present evidence, not proof that "
            "the earlier failure is happening again."
        )


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS affective_incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_ts REAL NOT NULL,
                updated_ts REAL NOT NULL,
                source TEXT NOT NULL,
                cue TEXT NOT NULL,
                summary TEXT NOT NULL,
                severity REAL NOT NULL,
                controllability REAL NOT NULL,
                prediction_error REAL NOT NULL,
                activation REAL NOT NULL,
                recovery REAL NOT NULL DEFAULT 0,
                recurrence_count INTEGER NOT NULL DEFAULT 1,
                safe_outcomes INTEGER NOT NULL DEFAULT 0,
                harmful_outcomes INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active',
                last_triggered_ts REAL NOT NULL,
                UNIQUE(source, cue)
            );
            CREATE INDEX IF NOT EXISTS idx_affective_incidents_cue
                ON affective_incidents(cue, status, activation DESC);
            CREATE INDEX IF NOT EXISTS idx_affective_incidents_updated
                ON affective_incidents(updated_ts DESC);
            """
        )


def _row_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    for key in ("severity", "controllability", "prediction_error", "activation", "recovery"):
        result[key] = round(float(result[key]), 4)
    result["schema"] = SCHEMA
    return result


def record_incident(
    *,
    source: str,
    cue: str,
    summary: str,
    severity: float,
    controllability: float,
    prediction_error: float,
    db_path: Path = DB_PATH,
    now: float | None = None,
) -> dict:
    """Record or reinforce one verified incident and return its bounded state."""
    source_value = _text(source, 48)
    cue_value = _cue(cue)
    summary_value = _text(summary, 320)
    if not source_value or not cue_value or not summary_value:
        raise ValueError("source, cue, and summary are required")
    severity_value = _clamp(severity)
    controllability_value = _clamp(controllability)
    error_value = _clamp(prediction_error)
    appraisal = _clamp(
        0.45 * severity_value
        + 0.35 * error_value
        + 0.20 * (1.0 - controllability_value)
    )
    timestamp = float(now if now is not None else time.time())
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM affective_incidents WHERE source = ? AND cue = ?",
            (source_value, cue_value),
        ).fetchone()
        if row is None:
            activation = appraisal
            conn.execute(
                """INSERT INTO affective_incidents
                   (created_ts, updated_ts, source, cue, summary, severity,
                    controllability, prediction_error, activation, recovery,
                    recurrence_count, safe_outcomes, harmful_outcomes, status,
                    last_triggered_ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, 0, 1, 'active', ?)""",
                (
                    timestamp, timestamp, source_value, cue_value, summary_value,
                    severity_value, controllability_value, error_value,
                    activation, timestamp,
                ),
            )
        else:
            recurrence = int(row["recurrence_count"]) + 1
            activation = _clamp(
                max(float(row["activation"]) * 0.88, appraisal)
                + min(0.12, 0.02 * recurrence)
            )
            recovery = _clamp(float(row["recovery"]) * 0.72)
            conn.execute(
                """UPDATE affective_incidents
                   SET updated_ts = ?, summary = ?, severity = ?, controllability = ?,
                       prediction_error = ?, activation = ?, recovery = ?,
                       recurrence_count = ?, harmful_outcomes = harmful_outcomes + 1,
                       status = 'active', last_triggered_ts = ?
                   WHERE id = ?""",
                (
                    timestamp, summary_value, severity_value, controllability_value,
                    error_value, activation, recovery, recurrence, timestamp,
                    int(row["id"]),
                ),
            )
        stored = conn.execute(
            "SELECT * FROM affective_incidents WHERE source = ? AND cue = ?",
            (source_value, cue_value),
        ).fetchone()
    assert stored is not None
    result = _row_dict(stored)
    _audit("incident_recorded", result, db_path)
    return result


def record_outcome(
    incident_id: int,
    *,
    safe: bool,
    db_path: Path = DB_PATH,
    now: float | None = None,
) -> dict | None:
    """Apply safety learning or a verified recurrence to an existing incident."""
    init_db(db_path)
    timestamp = float(now if now is not None else time.time())
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM affective_incidents WHERE id = ?", (int(incident_id),)
        ).fetchone()
        if row is None:
            return None
        if safe:
            recovery = _clamp(float(row["recovery"]) + 0.22 * (1.0 - float(row["recovery"])))
            activation = _clamp(float(row["activation"]) * 0.78)
            status = "integrated" if recovery >= 0.72 and activation < 0.25 else "recovering"
            conn.execute(
                """UPDATE affective_incidents SET updated_ts = ?, activation = ?,
                   recovery = ?, safe_outcomes = safe_outcomes + 1, status = ?
                   WHERE id = ?""",
                (timestamp, activation, recovery, status, int(incident_id)),
            )
        else:
            activation = _clamp(float(row["activation"]) + 0.15 * (1.0 - float(row["activation"])))
            recovery = _clamp(float(row["recovery"]) * 0.75)
            conn.execute(
                """UPDATE affective_incidents SET updated_ts = ?, activation = ?,
                   recovery = ?, recurrence_count = recurrence_count + 1,
                   harmful_outcomes = harmful_outcomes + 1, status = 'active',
                   last_triggered_ts = ? WHERE id = ?""",
                (timestamp, activation, recovery, timestamp, int(incident_id)),
            )
        stored = conn.execute(
            "SELECT * FROM affective_incidents WHERE id = ?", (int(incident_id),)
        ).fetchone()
    assert stored is not None
    result = _row_dict(stored)
    _audit("safety_learning" if safe else "incident_recurred", result, db_path)
    return result


def assess_cues(
    cues: Iterable[str],
    *,
    db_path: Path = DB_PATH,
    now: float | None = None,
) -> IncidentSignal:
    """Return the strongest exact cue match; never generalize from free text."""
    cue_values = sorted({_cue(value) for value in cues if _cue(value)})[:16]
    if not cue_values:
        return IncidentSignal()
    init_db(db_path)
    placeholders = ",".join("?" for _ in cue_values)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM affective_incidents WHERE cue IN ({placeholders}) "
            "AND status != 'integrated' ORDER BY activation DESC LIMIT 16",
            cue_values,
        ).fetchall()
    if not rows:
        return IncidentSignal()
    timestamp = float(now if now is not None else time.time())
    best: tuple[float, sqlite3.Row] | None = None
    for row in rows:
        age_days = max(0.0, timestamp - float(row["updated_ts"])) / 86400.0
        time_factor = 0.5 ** (age_days / 30.0)
        effective = _clamp(
            float(row["activation"])
            * (1.0 - 0.75 * float(row["recovery"]))
            * time_factor
        )
        if best is None or effective > best[0]:
            best = (effective, row)
    assert best is not None
    effective, row = best
    return IncidentSignal(
        incident_id=int(row["id"]),
        cue=str(row["cue"]),
        source=str(row["source"]),
        summary=str(row["summary"]),
        activation=round(effective, 4),
        recovery=round(float(row["recovery"]), 4),
        confidence=1.0,
        status=str(row["status"]),
    )


def recent(*, limit: int = 30, db_path: Path = DB_PATH) -> list[dict]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM affective_incidents ORDER BY updated_ts DESC LIMIT ?",
            (max(1, min(100, int(limit))),),
        ).fetchall()
    return [_row_dict(row) for row in rows]


def _audit(event: str, incident: dict, db_path: Path) -> None:
    try:
        from alpecca import cognition as cognition_mod

        cognition_mod.record_observation(
            cognition_mod.CognitionObservation(
                source="affective_incident_learning",
                content=f"Affective incident transition: {event}.",
                confidence=1.0,
                privacy_class="local",
                metadata={
                    "schema": SCHEMA,
                    "event": event,
                    "incident_id": incident.get("id"),
                    "cue": incident.get("cue"),
                    "activation": incident.get("activation"),
                    "recovery": incident.get("recovery"),
                    "status": incident.get("status"),
                },
            ),
            db_path=db_path,
        )
    except Exception:
        # The incident transition is already durable. Audit failure must not
        # duplicate or roll it back.
        pass
