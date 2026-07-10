"""Durable Phase 4 commitments and action receipts.

This module is storage only.  It records a scoped commitment, enforces its
small state machine, and keeps an append-only receipt for every transition.
Execution, approval policy, cue interpretation, and response wording belong to
their respective integration layers.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from alpecca.db import connect
from config import DB_PATH


PROPOSED = "proposed"
APPROVED = "approved"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"

STATES = frozenset({PROPOSED, APPROVED, RUNNING, SUCCEEDED, FAILED, CANCELLED})
TERMINAL_STATES = frozenset({SUCCEEDED, FAILED, CANCELLED})
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    PROPOSED: frozenset({APPROVED}),
    APPROVED: frozenset({RUNNING}),
    RUNNING: TERMINAL_STATES,
    SUCCEEDED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
}

_MAX_SCOPE_LENGTH = 160
_MAX_ACTION_LENGTH = 2000
_MAX_PAYLOAD_BYTES = 64 * 1024


class CommitmentError(ValueError):
    """Base error for an invalid commitment operation."""


class CommitmentNotFound(CommitmentError):
    """The requested commitment is absent from the caller's scope."""


class IllegalTransition(CommitmentError):
    """A requested state change is outside the commitment state machine."""


class CorruptCommitment(CommitmentError):
    """Stored payload data is not in the format written by this module."""


def _scope(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise CommitmentError("scope is required")
    if len(cleaned) > _MAX_SCOPE_LENGTH:
        raise CommitmentError(f"scope exceeds {_MAX_SCOPE_LENGTH} characters")
    if any(ord(char) < 32 for char in cleaned):
        raise CommitmentError("scope contains control characters")
    return cleaned


def _action(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise CommitmentError("action is required")
    if len(cleaned) > _MAX_ACTION_LENGTH:
        raise CommitmentError(f"action exceeds {_MAX_ACTION_LENGTH} characters")
    return cleaned


def _dump_payload(
    value: Mapping[str, Any] | None,
    *,
    name: str,
    required: bool = False,
) -> str | None:
    if value is None:
        if required:
            raise CommitmentError(f"{name} payload is required")
        return None
    if not isinstance(value, Mapping):
        raise CommitmentError(f"{name} payload must be a mapping")
    materialized = dict(value)
    if required and not materialized:
        raise CommitmentError(f"{name} payload cannot be empty")
    try:
        encoded = json.dumps(
            materialized,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CommitmentError(f"{name} payload is not JSON serializable") from exc
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise CommitmentError(f"{name} payload exceeds {_MAX_PAYLOAD_BYTES} bytes")
    return encoded


def _load_payload(raw: str | None, *, name: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CorruptCommitment(f"stored {name} payload is invalid JSON") from exc
    if not isinstance(value, dict):
        raise CorruptCommitment(f"stored {name} payload is not an object")
    return value


def init_db(db_path: Path = DB_PATH) -> None:
    """Create the ledger schema idempotently."""
    with connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS commitments (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at    REAL NOT NULL,
                updated_at    REAL NOT NULL,
                scope         TEXT NOT NULL,
                action        TEXT NOT NULL,
                state         TEXT NOT NULL CHECK (
                    state IN ('proposed', 'approved', 'running',
                              'succeeded', 'failed', 'cancelled')
                ),
                evidence_json TEXT NOT NULL,
                receipt_json  TEXT
            );

            CREATE TABLE IF NOT EXISTS commitment_receipts (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                commitment_id  INTEGER NOT NULL,
                created_at     REAL NOT NULL,
                from_state     TEXT,
                to_state       TEXT NOT NULL CHECK (
                    to_state IN ('proposed', 'approved', 'running',
                                 'succeeded', 'failed', 'cancelled')
                ),
                evidence_json  TEXT,
                receipt_json   TEXT,
                FOREIGN KEY(commitment_id) REFERENCES commitments(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS commitments_scope_state_idx
                ON commitments(scope, state, updated_at DESC);
            CREATE INDEX IF NOT EXISTS commitment_receipts_commitment_idx
                ON commitment_receipts(commitment_id, id ASC);

            CREATE TRIGGER IF NOT EXISTS commitments_state_transition_guard
            BEFORE UPDATE OF state ON commitments
            FOR EACH ROW
            WHEN NOT (
                (OLD.state = 'proposed' AND NEW.state = 'approved') OR
                (OLD.state = 'approved' AND NEW.state = 'running') OR
                (OLD.state = 'running' AND NEW.state IN
                    ('succeeded', 'failed', 'cancelled'))
            )
            BEGIN
                SELECT RAISE(ABORT, 'illegal commitment state transition');
            END;
            """
        )


def _receipt_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "created_at": float(row["created_at"]),
        "from_state": row["from_state"],
        "to_state": str(row["to_state"]),
        "evidence": _load_payload(row["evidence_json"], name="evidence"),
        "receipt": _load_payload(row["receipt_json"], name="receipt"),
    }


def _commitment_dict(
    row: sqlite3.Row,
    receipt_rows: list[sqlite3.Row],
) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "scope": str(row["scope"]),
        "action": str(row["action"]),
        "state": str(row["state"]),
        "evidence": _load_payload(row["evidence_json"], name="evidence") or {},
        "receipt": _load_payload(row["receipt_json"], name="receipt"),
        "receipts": [_receipt_dict(item) for item in receipt_rows],
    }


def create_commitment(
    action: str,
    *,
    scope: str,
    evidence: Mapping[str, Any] | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Store a new proposed commitment and its initial ledger entry."""
    clean_scope = _scope(scope)
    clean_action = _action(action)
    evidence_json = _dump_payload(evidence or {}, name="evidence") or "{}"
    init_db(db_path)
    now = time.time()
    with connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.execute(
            """
            INSERT INTO commitments
                (created_at, updated_at, scope, action, state,
                 evidence_json, receipt_json)
            VALUES (?, ?, ?, ?, 'proposed', ?, NULL)
            """,
            (now, now, clean_scope, clean_action, evidence_json),
        )
        commitment_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO commitment_receipts
                (commitment_id, created_at, from_state, to_state,
                 evidence_json, receipt_json)
            VALUES (?, ?, NULL, 'proposed', ?, NULL)
            """,
            (commitment_id, now, evidence_json),
        )
    created = get_commitment(commitment_id, scope=clean_scope, db_path=db_path)
    if created is None:  # pragma: no cover - same-transaction invariant
        raise CommitmentError("commitment was not retrievable after creation")
    return created


def get_commitment(
    commitment_id: int,
    *,
    scope: str,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Retrieve one scoped commitment without changing any stored state."""
    clean_scope = _scope(scope)
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM commitments WHERE id=? AND scope=?",
            (int(commitment_id), clean_scope),
        ).fetchone()
        if row is None:
            return None
        receipt_rows = conn.execute(
            """
            SELECT * FROM commitment_receipts
            WHERE commitment_id=? ORDER BY id ASC
            """,
            (int(commitment_id),),
        ).fetchall()
    return _commitment_dict(row, list(receipt_rows))


def transition_commitment(
    commitment_id: int,
    to_state: str,
    *,
    scope: str,
    evidence: Mapping[str, Any] | None = None,
    receipt: Mapping[str, Any] | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Atomically apply one legal transition and append its durable receipt."""
    clean_scope = _scope(scope)
    requested = str(to_state or "").strip().lower()
    if requested not in STATES:
        raise IllegalTransition(f"unknown commitment state: {requested or '<empty>'}")
    evidence_json = _dump_payload(evidence, name="evidence")
    receipt_json = _dump_payload(
        receipt,
        name="receipt",
        required=requested in TERMINAL_STATES,
    )
    if requested not in TERMINAL_STATES and receipt_json is not None:
        raise CommitmentError("receipt payload is only valid for a terminal transition")

    init_db(db_path)
    now = time.time()
    with connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        current_row = conn.execute(
            "SELECT state FROM commitments WHERE id=? AND scope=?",
            (int(commitment_id), clean_scope),
        ).fetchone()
        if current_row is None:
            raise CommitmentNotFound(
                f"commitment {int(commitment_id)} was not found in scope {clean_scope!r}"
            )
        current = str(current_row["state"])
        if requested not in LEGAL_TRANSITIONS[current]:
            raise IllegalTransition(f"illegal commitment transition: {current} -> {requested}")

        cursor = conn.execute(
            """
            UPDATE commitments
            SET state=?, updated_at=?, receipt_json=?
            WHERE id=? AND scope=? AND state=?
            """,
            (
                requested,
                now,
                receipt_json,
                int(commitment_id),
                clean_scope,
                current,
            ),
        )
        if cursor.rowcount != 1:
            observed = conn.execute(
                "SELECT state FROM commitments WHERE id=? AND scope=?",
                (int(commitment_id), clean_scope),
            ).fetchone()
            state = str(observed["state"]) if observed is not None else "missing"
            raise IllegalTransition(
                f"commitment changed concurrently; expected {current}, found {state}"
            )
        conn.execute(
            """
            INSERT INTO commitment_receipts
                (commitment_id, created_at, from_state, to_state,
                 evidence_json, receipt_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(commitment_id),
                now,
                current,
                requested,
                evidence_json,
                receipt_json,
            ),
        )

    updated = get_commitment(int(commitment_id), scope=clean_scope, db_path=db_path)
    if updated is None:  # pragma: no cover - same-database invariant
        raise CommitmentError("commitment disappeared after transition")
    return updated


def list_commitments(
    *,
    scope: str,
    state: str | None = None,
    limit: int = 100,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """List commitments in one scope, newest activity first."""
    clean_scope = _scope(scope)
    clean_state = None if state is None else str(state).strip().lower()
    if clean_state is not None and clean_state not in STATES:
        raise CommitmentError(f"unknown commitment state: {clean_state}")
    bounded_limit = max(1, min(200, int(limit)))
    init_db(db_path)
    query = "SELECT id FROM commitments WHERE scope=?"
    args: list[Any] = [clean_scope]
    if clean_state is not None:
        query += " AND state=?"
        args.append(clean_state)
    query += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    args.append(bounded_limit)
    with connect(db_path) as conn:
        ids = [int(row["id"]) for row in conn.execute(query, args).fetchall()]
    records = [
        get_commitment(item_id, scope=clean_scope, db_path=db_path)
        for item_id in ids
    ]
    return [record for record in records if record is not None]
