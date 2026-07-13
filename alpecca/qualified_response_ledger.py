"""Durable server-owned evidence for the qualified-response metric.

This module intentionally knows nothing about HTTP, WebSockets, model output,
or user text.  The server supplies only its own delivery and turn identifiers.
Rows begin as provisional dispatches before a send awaits; only a confirmed
delivery can become part of the metric denominator.
"""
from __future__ import annotations

import math
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from alpecca.db import connect
from config import DB_PATH


CREATOR_PERSONAL_SCOPE = "creator-personal"
METRIC_NAME = "qualified_response_rate"
DEFINITION_VERSION = 1

DISPATCHING = "dispatching"
PENDING = "pending"
RESPONDED = "responded"
UNANSWERED = "unanswered"
CANCELLED = "cancelled"

_STATES = frozenset({DISPATCHING, PENDING, RESPONDED, UNANSWERED, CANCELLED})
_MAX_IDENTIFIER_LENGTH = 200
_MAX_SCOPE_KEY_LENGTH = 512
_MAX_SURFACE_LENGTH = 80
_MAX_WINDOW_SECONDS = 3600.0


class QualifiedResponseLedgerError(ValueError):
    """The server attempted an invalid outcome-ledger operation."""


class OutcomeNotFound(QualifiedResponseLedgerError):
    """No durable delivery row has the requested server-generated id."""


class OutcomeConflict(QualifiedResponseLedgerError):
    """A retry used the same id with different server-owned facts."""


def _identifier(value: object, *, name: str, maximum: int = _MAX_IDENTIFIER_LENGTH) -> str:
    if not isinstance(value, str):
        raise QualifiedResponseLedgerError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise QualifiedResponseLedgerError(f"{name} is required")
    if cleaned != value:
        raise QualifiedResponseLedgerError(f"{name} must not have outer whitespace")
    if len(cleaned) > maximum:
        raise QualifiedResponseLedgerError(f"{name} exceeds {maximum} characters")
    if any(ord(char) < 32 for char in cleaned):
        raise QualifiedResponseLedgerError(f"{name} contains control characters")
    return cleaned


def _timestamp(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QualifiedResponseLedgerError(f"{name} must be numeric")
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0.0:
        raise QualifiedResponseLedgerError(f"{name} must be finite and non-negative")
    return stamp


def _window_seconds(value: object) -> float:
    seconds = _timestamp(value, name="response_window_seconds")
    if seconds <= 0.0 or seconds > _MAX_WINDOW_SECONDS:
        raise QualifiedResponseLedgerError(
            f"response_window_seconds must be between 0 and {_MAX_WINDOW_SECONDS:g}"
        )
    return seconds


def _trial_id(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise QualifiedResponseLedgerError("trial_id must be a positive integer or null")
    return value


def _cohort(trial_id: int | None) -> str:
    return "trial" if trial_id is not None else "baseline"


def _record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "delivery_id": str(row["delivery_id"]),
        "scope": str(row["scope"]),
        "scope_key": str(row["scope_key"]),
        "surface": str(row["surface"]),
        "proactive_turn_id": str(row["proactive_turn_id"]),
        "trial_id": None if row["trial_id"] is None else int(row["trial_id"]),
        "cohort": str(row["cohort"]),
        "state": str(row["state"]),
        "dispatched_at": float(row["dispatched_at"]),
        "delivered_at": None if row["delivered_at"] is None else float(row["delivered_at"]),
        "deadline_at": float(row["deadline_at"]),
        "response_turn_id": row["response_turn_id"],
        "response_at": None if row["response_at"] is None else float(row["response_at"]),
        "resolved_at": None if row["resolved_at"] is None else float(row["resolved_at"]),
    }


class QualifiedResponseLedger:
    """SQLite state machine for one server-observed response metric."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not callable(clock):
            raise QualifiedResponseLedgerError("clock must be callable")
        self.db_path = Path(db_path)
        self._clock = clock
        self.init_db()

    def _now(self) -> float:
        return _timestamp(self._clock(), name="clock timestamp")

    def init_db(self) -> None:
        """Install the evidence table and idempotency indexes."""
        with connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS qualified_response_outcomes (
                    delivery_id             TEXT PRIMARY KEY,
                    scope                   TEXT NOT NULL
                        CHECK (scope='creator-personal'),
                    scope_key               TEXT NOT NULL,
                    surface                 TEXT NOT NULL,
                    proactive_turn_id       TEXT NOT NULL,
                    trial_id                INTEGER,
                    cohort                  TEXT NOT NULL
                        CHECK (cohort IN ('baseline','trial')),
                    metric                  TEXT NOT NULL
                        CHECK (metric='qualified_response_rate'),
                    definition_version      INTEGER NOT NULL CHECK (definition_version=1),
                    state                   TEXT NOT NULL CHECK (
                        state IN ('dispatching','pending','responded','unanswered','cancelled')
                    ),
                    dispatched_at           REAL NOT NULL,
                    response_window_seconds REAL NOT NULL,
                    delivered_at            REAL,
                    deadline_at             REAL NOT NULL,
                    response_turn_id        TEXT,
                    response_at             REAL,
                    resolved_at             REAL
                );

                CREATE INDEX IF NOT EXISTS qualified_response_pending_idx
                    ON qualified_response_outcomes(scope_key, surface, state, deadline_at, dispatched_at);
                CREATE INDEX IF NOT EXISTS qualified_response_trial_idx
                    ON qualified_response_outcomes(cohort, trial_id, state, resolved_at);
                CREATE UNIQUE INDEX IF NOT EXISTS qualified_response_turn_once_idx
                    ON qualified_response_outcomes(response_turn_id)
                    WHERE response_turn_id IS NOT NULL;
                """
            )

    def _get(self, conn: sqlite3.Connection, delivery_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM qualified_response_outcomes WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        if row is None:
            raise OutcomeNotFound(f"delivery {delivery_id!r} was not found")
        return row

    def begin_dispatch(
        self,
        *,
        delivery_id: str,
        scope_key: str,
        surface: str,
        proactive_turn_id: str,
        response_window_seconds: float,
        trial_id: int | None = None,
        dispatched_at: float | None = None,
    ) -> dict[str, Any]:
        """Durably reserve a provisional, not-yet-counted delivery exposure."""
        clean_delivery = _identifier(delivery_id, name="delivery_id")
        clean_scope_key = _identifier(
            scope_key, name="scope_key", maximum=_MAX_SCOPE_KEY_LENGTH
        )
        clean_surface = _identifier(surface, name="surface", maximum=_MAX_SURFACE_LENGTH)
        clean_turn = _identifier(proactive_turn_id, name="proactive_turn_id")
        window = _window_seconds(response_window_seconds)
        clean_trial_id = _trial_id(trial_id)
        stamp = _timestamp(
            self._now() if dispatched_at is None else dispatched_at,
            name="dispatched_at",
        )
        deadline = stamp + window
        cohort = _cohort(clean_trial_id)

        with connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT * FROM qualified_response_outcomes WHERE delivery_id=?",
                (clean_delivery,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO qualified_response_outcomes
                        (delivery_id, scope, scope_key, surface, proactive_turn_id,
                         trial_id, cohort, metric, definition_version, state,
                         dispatched_at, response_window_seconds, delivered_at,
                         deadline_at, response_turn_id, response_at, resolved_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, NULL)
                    """,
                    (
                        clean_delivery,
                        CREATOR_PERSONAL_SCOPE,
                        clean_scope_key,
                        clean_surface,
                        clean_turn,
                        clean_trial_id,
                        cohort,
                        METRIC_NAME,
                        DEFINITION_VERSION,
                        DISPATCHING,
                        stamp,
                        window,
                        deadline,
                    ),
                )
            else:
                same = (
                    str(existing["scope"]) == CREATOR_PERSONAL_SCOPE
                    and str(existing["scope_key"]) == clean_scope_key
                    and str(existing["surface"]) == clean_surface
                    and str(existing["proactive_turn_id"]) == clean_turn
                    and existing["trial_id"] == clean_trial_id
                    and str(existing["cohort"]) == cohort
                    and float(existing["dispatched_at"]) == stamp
                    and float(existing["response_window_seconds"]) == window
                )
                if not same:
                    raise OutcomeConflict(
                        "delivery id was replayed with different server-owned facts"
                    )
            return _record(self._get(conn, clean_delivery))

    def confirm_delivery(
        self,
        delivery_id: str,
        *,
        delivered_at: float | None = None,
    ) -> dict[str, Any]:
        """Turn a provisional dispatch into a confirmed metric exposure."""
        clean_delivery = _identifier(delivery_id, name="delivery_id")
        stamp = _timestamp(
            self._now() if delivered_at is None else delivered_at,
            name="delivered_at",
        )
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._get(conn, clean_delivery)
            state = str(row["state"])
            if state == DISPATCHING:
                deadline = stamp + float(row["response_window_seconds"])
                response_at = row["response_at"]
                next_state = RESPONDED if response_at is not None else PENDING
                resolved_at = response_at if response_at is not None else None
                updated = conn.execute(
                    """
                    UPDATE qualified_response_outcomes
                    SET state=?, delivered_at=?, deadline_at=?, resolved_at=?
                    WHERE delivery_id=? AND state='dispatching'
                    """,
                    (next_state, stamp, deadline, resolved_at, clean_delivery),
                )
                if updated.rowcount != 1:  # pragma: no cover - transaction fences races
                    raise OutcomeConflict("delivery confirmation lost its dispatch state")
            elif state in {PENDING, RESPONDED}:
                if row["delivered_at"] is None or float(row["delivered_at"]) != stamp:
                    raise OutcomeConflict("delivery was confirmed at a different timestamp")
            else:
                raise OutcomeConflict(f"cannot confirm a {state} delivery")
            return _record(self._get(conn, clean_delivery))

    def cancel_dispatch(
        self,
        delivery_id: str,
        *,
        cancelled_at: float | None = None,
    ) -> dict[str, Any]:
        """Exclude a failed or queued send from all metric counts."""
        clean_delivery = _identifier(delivery_id, name="delivery_id")
        stamp = _timestamp(
            self._now() if cancelled_at is None else cancelled_at,
            name="cancelled_at",
        )
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._get(conn, clean_delivery)
            state = str(row["state"])
            if state == DISPATCHING:
                conn.execute(
                    """
                    UPDATE qualified_response_outcomes
                    SET state='cancelled', resolved_at=?
                    WHERE delivery_id=? AND state='dispatching'
                    """,
                    (stamp, clean_delivery),
                )
            elif state != CANCELLED:
                raise OutcomeConflict(f"cannot cancel a {state} delivery")
            return _record(self._get(conn, clean_delivery))

    def record_creator_response(
        self,
        *,
        scope_key: str,
        surface: str,
        response_turn_id: str,
        received_at: float | None = None,
    ) -> dict[str, Any] | None:
        """Attach one server-authenticated response to one pending exposure.

        A response received while a portal send is awaiting confirmation is
        retained on the provisional row and becomes terminal only if the send
        is later confirmed.  This closes the send/response race without ever
        counting failed or queued delivery.
        """
        clean_scope_key = _identifier(
            scope_key, name="scope_key", maximum=_MAX_SCOPE_KEY_LENGTH
        )
        clean_surface = _identifier(surface, name="surface", maximum=_MAX_SURFACE_LENGTH)
        clean_turn = _identifier(response_turn_id, name="response_turn_id")
        stamp = _timestamp(
            self._now() if received_at is None else received_at,
            name="received_at",
        )
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM qualified_response_outcomes WHERE response_turn_id=?",
                (clean_turn,),
            ).fetchone() is not None:
                return None
            row = conn.execute(
                """
                SELECT * FROM qualified_response_outcomes
                WHERE scope=? AND scope_key=? AND surface=?
                  AND state IN ('dispatching','pending')
                  AND response_turn_id IS NULL AND deadline_at>=?
                ORDER BY dispatched_at, delivery_id
                LIMIT 1
                """,
                (CREATOR_PERSONAL_SCOPE, clean_scope_key, clean_surface, stamp),
            ).fetchone()
            if row is None:
                return None
            delivery_id = str(row["delivery_id"])
            next_state = RESPONDED if str(row["state"]) == PENDING else DISPATCHING
            resolved_at = stamp if next_state == RESPONDED else None
            updated = conn.execute(
                """
                UPDATE qualified_response_outcomes
                SET state=?, response_turn_id=?, response_at=?, resolved_at=?
                WHERE delivery_id=? AND state IN ('dispatching','pending')
                  AND response_turn_id IS NULL
                """,
                (next_state, clean_turn, stamp, resolved_at, delivery_id),
            )
            if updated.rowcount != 1:  # pragma: no cover - transaction fences races
                return None
            return _record(self._get(conn, delivery_id))

    def expire_due(self, *, now: float | None = None) -> list[dict[str, Any]]:
        """Finalize confirmed unanswered rows and discard stale provisional sends."""
        stamp = _timestamp(self._now() if now is None else now, name="now")
        changed: list[str] = []
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT delivery_id, state FROM qualified_response_outcomes
                WHERE state IN ('dispatching','pending') AND deadline_at<=?
                ORDER BY deadline_at, delivery_id
                """,
                (stamp,),
            ).fetchall()
            for row in rows:
                delivery_id = str(row["delivery_id"])
                state = str(row["state"])
                next_state = UNANSWERED if state == PENDING else CANCELLED
                updated = conn.execute(
                    """
                    UPDATE qualified_response_outcomes
                    SET state=?, resolved_at=?
                    WHERE delivery_id=? AND state=?
                    """,
                    (next_state, stamp, delivery_id, state),
                )
                if updated.rowcount == 1:
                    changed.append(delivery_id)
            return [_record(self._get(conn, delivery_id)) for delivery_id in changed]

    @staticmethod
    def _summary_bucket() -> dict[str, Any]:
        return {
            "dispatching": 0,
            "pending": 0,
            "qualified_responses": 0,
            "unanswered": 0,
            "cancelled": 0,
            "completed": 0,
            "rate": None,
        }

    @staticmethod
    def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
        completed = int(bucket["qualified_responses"]) + int(bucket["unanswered"])
        bucket["completed"] = completed
        bucket["rate"] = (
            None if completed == 0 else float(bucket["qualified_responses"]) / completed
        )
        return bucket

    def _trial_bucket(self, trial_id: int) -> dict[str, Any]:
        """Read one aggregate-only bucket for a fixed server-owned trial id."""
        database_uri = self.db_path.resolve().as_uri() + "?mode=ro"
        bucket = self._summary_bucket()
        with sqlite3.connect(database_uri, uri=True) as conn:
            rows = conn.execute(
                """
                SELECT state, COUNT(*) AS count
                FROM qualified_response_outcomes
                WHERE metric=? AND definition_version=?
                  AND cohort='trial' AND trial_id=?
                GROUP BY state
                """,
                (METRIC_NAME, DEFINITION_VERSION, trial_id),
            ).fetchall()
        for state, count in rows:
            if str(state) not in _STATES:
                continue
            key = {
                DISPATCHING: "dispatching",
                PENDING: "pending",
                RESPONDED: "qualified_responses",
                UNANSWERED: "unanswered",
                CANCELLED: "cancelled",
            }[str(state)]
            bucket[key] = int(count)
        return self._finalize_bucket(bucket)

    def summary(self) -> dict[str, Any]:
        """Return aggregate-only evidence without delivery/turn identifiers."""
        database_uri = self.db_path.resolve().as_uri() + "?mode=ro"
        buckets = {"baseline": self._summary_bucket(), "trial": self._summary_bucket()}
        with sqlite3.connect(database_uri, uri=True) as conn:
            rows = conn.execute(
                """
                SELECT cohort, state, COUNT(*) AS count
                FROM qualified_response_outcomes
                WHERE metric=? AND definition_version=?
                GROUP BY cohort, state
                """,
                (METRIC_NAME, DEFINITION_VERSION),
            ).fetchall()
        for cohort, state, count in rows:
            bucket = buckets.get(str(cohort))
            if bucket is None or str(state) not in _STATES:
                continue
            key = {
                DISPATCHING: "dispatching",
                PENDING: "pending",
                RESPONDED: "qualified_responses",
                UNANSWERED: "unanswered",
                CANCELLED: "cancelled",
            }[str(state)]
            bucket[key] = int(count)
        for bucket in buckets.values():
            self._finalize_bucket(bucket)
        overall = self._summary_bucket()
        for key in ("dispatching", "pending", "qualified_responses", "unanswered", "cancelled"):
            overall[key] = int(buckets["baseline"][key]) + int(buckets["trial"][key])
        return {
            "metric": METRIC_NAME,
            "definition_version": DEFINITION_VERSION,
            **self._finalize_bucket(overall),
            "baseline": buckets["baseline"],
            "trial": buckets["trial"],
        }

    def baseline_summary(self, *, since: float | None = None) -> dict[str, Any]:
        """Return baseline evidence for the current retained-profile epoch.

        A profile decision starts a new baseline epoch. Dispatches from before
        that decision are deliberately excluded so a later RSI cycle cannot
        reuse evidence produced under an older behavior value.
        """
        cutoff = None if since is None else _timestamp(since, name="since")
        database_uri = self.db_path.resolve().as_uri() + "?mode=ro"
        bucket = self._summary_bucket()
        query = (
            "SELECT state, COUNT(*) AS count FROM qualified_response_outcomes "
            "WHERE metric=? AND definition_version=? AND cohort='baseline'"
        )
        params: list[object] = [METRIC_NAME, DEFINITION_VERSION]
        if cutoff is not None:
            query += " AND dispatched_at>=?"
            params.append(cutoff)
        query += " GROUP BY state"
        with sqlite3.connect(database_uri, uri=True) as conn:
            rows = conn.execute(query, params).fetchall()
        for state, count in rows:
            if str(state) not in _STATES:
                continue
            key = {
                DISPATCHING: "dispatching",
                PENDING: "pending",
                RESPONDED: "qualified_responses",
                UNANSWERED: "unanswered",
                CANCELLED: "cancelled",
            }[str(state)]
            bucket[key] = int(count)
        return {
            "metric": METRIC_NAME,
            "definition_version": DEFINITION_VERSION,
            "since": cutoff,
            **self._finalize_bucket(bucket),
        }

    def trial_summary(self, trial_id: int) -> dict[str, Any]:
        """Return one trial's aggregate-only evidence without mutating it.

        The caller supplies only a server-owned behavior-trial id. No delivery,
        response-turn, scope, or message identifier is returned.
        """
        clean_trial_id = _trial_id(trial_id)
        return {
            "metric": METRIC_NAME,
            "definition_version": DEFINITION_VERSION,
            "trial_id": clean_trial_id,
            **self._trial_bucket(clean_trial_id),
        }


__all__ = [
    "CANCELLED",
    "CREATOR_PERSONAL_SCOPE",
    "DEFINITION_VERSION",
    "DISPATCHING",
    "METRIC_NAME",
    "OutcomeConflict",
    "OutcomeNotFound",
    "PENDING",
    "QualifiedResponseLedger",
    "QualifiedResponseLedgerError",
    "RESPONDED",
    "UNANSWERED",
]
