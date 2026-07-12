"""Scoped durable records for already-validated Phase 8 trials.

The ledger stores specifications, approval proof, observation timestamps, and
rollback receipts.  It never applies a parameter value and has no execution
hook.  Every mutation is scope-bound and identical retries are idempotent.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from alpecca.db import connect
from alpecca.experiment_trials import (
    ExposureWindow,
    ParameterChange,
    TrialSpecification,
    ValidatedTrialSpecification as ExperimentTrial,
    validate_trial_spec,
)
from config import DB_PATH


REGISTERED = "registered"
APPROVED = "approved"
RUNNING = "running"
COMPLETED = "completed"
ROLLED_BACK = "rolled_back"

TRIAL_STATES = frozenset({REGISTERED, APPROVED, RUNNING, COMPLETED, ROLLED_BACK})
_MAX_SCOPE_LENGTH = 160
_MAX_ID_LENGTH = 160
_MAX_REASON_LENGTH = 1000
_MAX_PAYLOAD_BYTES = 64 * 1024


class TrialLedgerError(ValueError):
    """Base error for a rejected trial-ledger operation."""


class UnvalidatedExperimentTrial(TrialLedgerError):
    """Registration did not receive an authentic normalized validator result."""


class ApprovalRequired(TrialLedgerError):
    """A trial start was attempted without stored proposal approval proof."""


class TrialNotFound(TrialLedgerError):
    """The trial does not exist in the caller's scope."""


class TrialStateError(TrialLedgerError):
    """The requested ledger transition is invalid or conflicts with a retry."""


@dataclass(frozen=True, slots=True)
class ProposalApprovalProof:
    """Proof issued by a future authoritative approval layer."""

    proposal_id: int
    scope: str
    proof_id: str
    authority: str
    approved_at: float
    decision: Literal["approved"] = "approved"


def _scope(value: object) -> str:
    if not isinstance(value, str):
        raise TrialLedgerError("scope must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise TrialLedgerError("scope is required")
    if len(cleaned) > _MAX_SCOPE_LENGTH:
        raise TrialLedgerError(f"scope exceeds {_MAX_SCOPE_LENGTH} characters")
    if any(ord(char) < 32 for char in cleaned):
        raise TrialLedgerError("scope contains control characters")
    return cleaned


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TrialLedgerError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise TrialLedgerError(f"{name} is required")
    if len(cleaned) > _MAX_ID_LENGTH:
        raise TrialLedgerError(f"{name} exceeds {_MAX_ID_LENGTH} characters")
    if any(ord(char) < 32 for char in cleaned):
        raise TrialLedgerError(f"{name} contains control characters")
    return cleaned


def _timestamp(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrialLedgerError(f"{name} must be numeric")
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0.0:
        raise TrialLedgerError(f"{name} must be a finite non-negative timestamp")
    return stamp


def _number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrialLedgerError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise TrialLedgerError(f"{name} must be finite")
    return number


def _payload(value: Mapping[str, Any] | None, *, name: str) -> str:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise TrialLedgerError(f"{name} must be a mapping")
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise TrialLedgerError(f"{name} is not JSON serializable") from exc
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise TrialLedgerError(f"{name} exceeds {_MAX_PAYLOAD_BYTES} bytes")
    return encoded


def _decode_object(raw: str | None, *, name: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise TrialLedgerError(f"stored {name} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise TrialLedgerError(f"stored {name} is not an object")
    return value


def spec_sha256_from_json(spec_json: str) -> str:
    """Return the SHA-256 of the exact persisted trial-spec JSON text."""
    if not isinstance(spec_json, str):
        raise TrialLedgerError("stored trial spec must be a JSON string")
    _decode_object(spec_json, name="trial spec")
    return hashlib.sha256(spec_json.encode("utf-8")).hexdigest()


def spec_sha256(spec_json: str) -> str:
    """Backward-compatible alias for :func:`spec_sha256_from_json`."""
    return spec_sha256_from_json(spec_json)


def _validated_spec_json(spec: object) -> str:
    if not isinstance(spec, ExperimentTrial):
        raise UnvalidatedExperimentTrial(
            "trial must be a ValidatedTrialSpecification returned by validate_trial_spec"
        )
    # Reconstruct and validate the raw contract.  This rejects forged normalized
    # dataclasses whose bounds, delta, consumer, or rollback do not match policy.
    try:
        expected = validate_trial_spec(TrialSpecification(
            proposal_id=spec.proposal_id,
            parameter=spec.parameter,
            hypothesis=spec.hypothesis,
            metric=spec.metric,
            baseline=spec.baseline,
            exposure=ExposureWindow(spec.exposure_seconds, spec.min_samples),
            change=ParameterChange(spec.old_value, spec.trial_value),
            rollback_value=spec.rollback_value,
        ))
    except (TypeError, ValueError) as exc:
        raise UnvalidatedExperimentTrial("trial failed validator replay") from exc
    if expected != spec:
        raise UnvalidatedExperimentTrial(
            "trial does not exactly match the validator's normalized result"
        )
    return json.dumps(
        dataclasses.asdict(spec),
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _proof_json(proof: object, *, scope: str, proposal_id: int) -> str:
    if not isinstance(proof, ProposalApprovalProof):
        raise ApprovalRequired("proposal approval proof is required")
    proof_scope = _scope(proof.scope)
    if proof_scope != scope:
        raise ApprovalRequired("approval proof scope does not match the trial")
    if (
        isinstance(proof.proposal_id, bool)
        or not isinstance(proof.proposal_id, int)
        or proof.proposal_id != proposal_id
    ):
        raise ApprovalRequired("approval proof proposal_id does not match the trial")
    if proof.decision != APPROVED:
        raise ApprovalRequired("approval proof decision must be approved")
    clean = {
        "proposal_id": proof.proposal_id,
        "scope": proof_scope,
        "proof_id": _identifier(proof.proof_id, name="proof_id"),
        "authority": _identifier(proof.authority, name="authority"),
        "approved_at": _timestamp(proof.approved_at, name="approved_at"),
        "decision": APPROVED,
    }
    return json.dumps(clean, separators=(",", ":"), sort_keys=True)


def init_db(db_path: Path = DB_PATH) -> None:
    """Create the scoped ledger schema idempotently."""
    with connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS experiment_trial_ledger (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                scope          TEXT NOT NULL,
                proposal_id    INTEGER NOT NULL,
                state          TEXT NOT NULL CHECK (
                    state IN ('registered','approved','running',
                              'completed','rolled_back')
                ),
                spec_json      TEXT NOT NULL,
                approval_json  TEXT,
                created_at     REAL NOT NULL,
                updated_at     REAL NOT NULL,
                started_at     REAL,
                planned_end_at REAL,
                ended_at       REAL,
                UNIQUE(scope, proposal_id)
            );

            CREATE TABLE IF NOT EXISTS experiment_trial_observations (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                trial_id         INTEGER NOT NULL,
                observation_key  TEXT NOT NULL,
                observed_at      REAL NOT NULL,
                value            REAL NOT NULL,
                evidence_json    TEXT NOT NULL,
                UNIQUE(trial_id, observation_key),
                FOREIGN KEY(trial_id) REFERENCES experiment_trial_ledger(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS experiment_trial_rollbacks (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                trial_id       INTEGER NOT NULL UNIQUE,
                recorded_at    REAL NOT NULL,
                expected_value REAL NOT NULL,
                restored_value REAL NOT NULL,
                reason         TEXT NOT NULL,
                evidence_json  TEXT NOT NULL,
                FOREIGN KEY(trial_id) REFERENCES experiment_trial_ledger(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS experiment_trial_scope_state_idx
                ON experiment_trial_ledger(scope, state, updated_at DESC);
            CREATE INDEX IF NOT EXISTS experiment_trial_observation_idx
                ON experiment_trial_observations(trial_id, observed_at, id);

            CREATE TRIGGER IF NOT EXISTS experiment_trial_state_guard
            BEFORE UPDATE OF state ON experiment_trial_ledger
            FOR EACH ROW
            WHEN NOT (
                (OLD.state='registered' AND NEW.state='approved') OR
                (OLD.state='approved' AND NEW.state='running') OR
                (OLD.state='running' AND NEW.state IN ('completed','rolled_back')) OR
                (OLD.state='completed' AND NEW.state='rolled_back')
            )
            BEGIN
                SELECT RAISE(ABORT, 'illegal experiment trial transition');
            END;

            CREATE TRIGGER IF NOT EXISTS experiment_trial_spec_immutable
            BEFORE UPDATE OF spec_json ON experiment_trial_ledger
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'experiment trial specification is immutable');
            END;
            """
        )


def _observation_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "observation_key": str(row["observation_key"]),
        "observed_at": float(row["observed_at"]),
        "value": float(row["value"]),
        "evidence": _decode_object(row["evidence_json"], name="observation evidence") or {},
    }


def _rollback_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "recorded_at": float(row["recorded_at"]),
        "expected_value": float(row["expected_value"]),
        "restored_value": float(row["restored_value"]),
        "reason": str(row["reason"]),
        "evidence": _decode_object(row["evidence_json"], name="rollback evidence") or {},
    }


def _trial_dict(
    row: sqlite3.Row,
    observations: list[sqlite3.Row],
    rollback: sqlite3.Row | None,
) -> dict[str, Any]:
    spec_json = row["spec_json"]
    return {
        "id": int(row["id"]),
        "scope": str(row["scope"]),
        "proposal_id": int(row["proposal_id"]),
        "state": str(row["state"]),
        "spec": _decode_object(spec_json, name="trial spec") or {},
        "spec_sha256": spec_sha256_from_json(spec_json),
        "approval_proof": _decode_object(row["approval_json"], name="approval proof"),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "started_at": None if row["started_at"] is None else float(row["started_at"]),
        "planned_end_at": (
            None if row["planned_end_at"] is None else float(row["planned_end_at"])
        ),
        "ended_at": None if row["ended_at"] is None else float(row["ended_at"]),
        "observations": [_observation_dict(item) for item in observations],
        "rollback": _rollback_dict(rollback),
    }


def _row_in_scope(conn: sqlite3.Connection, trial_id: int, scope: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM experiment_trial_ledger WHERE id=? AND scope=?",
        (int(trial_id), scope),
    ).fetchone()
    if row is None:
        raise TrialNotFound(f"trial {int(trial_id)} was not found in scope {scope!r}")
    return row


def get_trial(
    trial_id: int,
    *,
    scope: str,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Retrieve a full scoped trial record without mutating it."""
    clean_scope = _scope(scope)
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM experiment_trial_ledger WHERE id=? AND scope=?",
            (int(trial_id), clean_scope),
        ).fetchone()
        if row is None:
            return None
        observations = conn.execute(
            """
            SELECT * FROM experiment_trial_observations
            WHERE trial_id=? ORDER BY observed_at, id
            """,
            (int(trial_id),),
        ).fetchall()
        rollback = conn.execute(
            "SELECT * FROM experiment_trial_rollbacks WHERE trial_id=?",
            (int(trial_id),),
        ).fetchone()
    return _trial_dict(row, list(observations), rollback)


def register_trial(
    spec: ExperimentTrial,
    *,
    scope: str,
    created_at: float | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Store one validated spec; identical scope/proposal retries deduplicate."""
    clean_scope = _scope(scope)
    spec_json = _validated_spec_json(spec)
    stamp = _timestamp(time.time() if created_at is None else created_at, name="created_at")
    init_db(db_path)
    with connect(db_path) as conn:
        existing = conn.execute(
            "SELECT * FROM experiment_trial_ledger WHERE scope=? AND proposal_id=?",
            (clean_scope, spec.proposal_id),
        ).fetchone()
        if existing is not None:
            if str(existing["spec_json"]) != spec_json:
                raise TrialStateError("proposal already has a different trial specification")
            trial_id = int(existing["id"])
        else:
            cursor = conn.execute(
                """
                INSERT INTO experiment_trial_ledger
                    (scope, proposal_id, state, spec_json, approval_json,
                     created_at, updated_at, started_at, planned_end_at, ended_at)
                VALUES (?, ?, 'registered', ?, NULL, ?, ?, NULL, NULL, NULL)
                """,
                (clean_scope, spec.proposal_id, spec_json, stamp, stamp),
            )
            trial_id = int(cursor.lastrowid)
    result = get_trial(trial_id, scope=clean_scope, db_path=db_path)
    if result is None:  # pragma: no cover - same-database invariant
        raise TrialLedgerError("registered trial was not retrievable")
    return result


def approve_trial_in_transaction(
    conn: sqlite3.Connection,
    trial_id: int,
    proof: ProposalApprovalProof,
    *,
    scope: str,
) -> int:
    """Approve a trial using the caller-owned transaction without committing it."""
    clean_scope = _scope(scope)
    row = _row_in_scope(conn, trial_id, clean_scope)
    encoded = _proof_json(
        proof, scope=clean_scope, proposal_id=int(row["proposal_id"])
    )
    if row["approval_json"] is not None:
        if str(row["approval_json"]) != encoded:
            raise TrialStateError("trial already has different approval proof")
        return int(row["id"])
    if str(row["state"]) != REGISTERED:
        raise TrialStateError(f"cannot approve a {row['state']} trial")
    approved_at = json.loads(encoded)["approved_at"]
    updated = conn.execute(
        """
        UPDATE experiment_trial_ledger
        SET state='approved', approval_json=?, updated_at=?
        WHERE id=? AND scope=? AND state='registered'
        """,
        (encoded, approved_at, int(trial_id), clean_scope),
    )
    if updated.rowcount != 1:  # pragma: no cover - caller transaction fences races
        raise TrialStateError("trial approval lost its registered state")
    return int(trial_id)


def approve_trial(
    trial_id: int,
    proof: ProposalApprovalProof,
    *,
    scope: str,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Attach authoritative proof before a trial may be marked running."""
    clean_scope = _scope(scope)
    init_db(db_path)
    with connect(db_path) as conn:
        return_result = approve_trial_in_transaction(
            conn, trial_id, proof, scope=clean_scope
        )
    result = get_trial(return_result, scope=clean_scope, db_path=db_path)
    if result is None:  # pragma: no cover
        raise TrialLedgerError("approved trial was not retrievable")
    return result


def start_trial(
    trial_id: int,
    *,
    scope: str,
    started_at: float | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Record timing for an approved trial without applying its parameter."""
    clean_scope = _scope(scope)
    init_db(db_path)
    with connect(db_path) as conn:
        row = _row_in_scope(conn, trial_id, clean_scope)
        if row["approval_json"] is None or str(row["state"]) == REGISTERED:
            raise ApprovalRequired("trial start requires stored proposal approval proof")
        if row["started_at"] is not None:
            if started_at is not None and float(row["started_at"]) != _timestamp(
                started_at, name="started_at"
            ):
                raise TrialStateError("trial already started at a different timestamp")
            trial_key = int(row["id"])
        else:
            if str(row["state"]) != APPROVED:
                raise TrialStateError(f"cannot start a {row['state']} trial")
            stamp = _timestamp(
                time.time() if started_at is None else started_at, name="started_at"
            )
            proof = _decode_object(row["approval_json"], name="approval proof") or {}
            if stamp < float(proof["approved_at"]):
                raise TrialStateError("trial cannot start before its approval timestamp")
            spec = _decode_object(row["spec_json"], name="trial spec") or {}
            planned_end = stamp + float(spec["exposure_seconds"])
            conn.execute(
                """
                UPDATE experiment_trial_ledger
                SET state='running', started_at=?, planned_end_at=?, updated_at=?
                WHERE id=? AND scope=? AND state='approved'
                """,
                (stamp, planned_end, stamp, int(trial_id), clean_scope),
            )
            trial_key = int(trial_id)
    result = get_trial(trial_key, scope=clean_scope, db_path=db_path)
    if result is None:  # pragma: no cover
        raise TrialLedgerError("started trial was not retrievable")
    return result


def record_metric_observation(
    trial_id: int,
    *,
    scope: str,
    observation_key: str,
    value: float,
    observed_at: float | None = None,
    evidence: Mapping[str, Any] | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Append one bounded-window metric reading; identical keys deduplicate."""
    clean_scope = _scope(scope)
    clean_key = _identifier(observation_key, name="observation_key")
    clean_value = _number(value, name="metric value")
    evidence_json = _payload(evidence, name="observation evidence")
    init_db(db_path)
    with connect(db_path) as conn:
        row = _row_in_scope(conn, trial_id, clean_scope)
        existing = conn.execute(
            """
            SELECT * FROM experiment_trial_observations
            WHERE trial_id=? AND observation_key=?
            """,
            (int(trial_id), clean_key),
        ).fetchone()
        if existing is not None:
            same_time = observed_at is None or float(existing["observed_at"]) == _timestamp(
                observed_at, name="observed_at"
            )
            if (
                not same_time
                or float(existing["value"]) != clean_value
                or str(existing["evidence_json"]) != evidence_json
            ):
                raise TrialStateError("observation key was replayed with different data")
            return _observation_dict(existing)
        if str(row["state"]) != RUNNING:
            raise TrialStateError("metric observations require a running trial")
        stamp = _timestamp(
            time.time() if observed_at is None else observed_at, name="observed_at"
        )
        if not float(row["started_at"]) <= stamp <= float(row["planned_end_at"]):
            raise TrialStateError("metric observation is outside the exposure window")
        cursor = conn.execute(
            """
            INSERT INTO experiment_trial_observations
                (trial_id, observation_key, observed_at, value, evidence_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(trial_id), clean_key, stamp, clean_value, evidence_json),
        )
        inserted = conn.execute(
            "SELECT * FROM experiment_trial_observations WHERE id=?",
            (int(cursor.lastrowid),),
        ).fetchone()
    return _observation_dict(inserted)


def complete_trial(
    trial_id: int,
    *,
    scope: str,
    ended_at: float | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Close a fully exposed trial; this only records completion."""
    clean_scope = _scope(scope)
    init_db(db_path)
    with connect(db_path) as conn:
        row = _row_in_scope(conn, trial_id, clean_scope)
        if str(row["state"]) == COMPLETED:
            if ended_at is not None and float(row["ended_at"]) != _timestamp(
                ended_at, name="ended_at"
            ):
                raise TrialStateError("trial already completed at a different timestamp")
            trial_key = int(row["id"])
        else:
            if str(row["state"]) != RUNNING:
                raise TrialStateError(f"cannot complete a {row['state']} trial")
            stamp = _timestamp(
                time.time() if ended_at is None else ended_at, name="ended_at"
            )
            if stamp < float(row["planned_end_at"]):
                raise TrialStateError("trial exposure window has not ended")
            spec = _decode_object(row["spec_json"], name="trial spec") or {}
            count = int(conn.execute(
                "SELECT COUNT(*) FROM experiment_trial_observations WHERE trial_id=?",
                (int(trial_id),),
            ).fetchone()[0])
            if count < int(spec["min_samples"]):
                raise TrialStateError("trial has fewer than its required metric samples")
            conn.execute(
                """
                UPDATE experiment_trial_ledger
                SET state='completed', ended_at=?, updated_at=?
                WHERE id=? AND scope=? AND state='running'
                """,
                (stamp, stamp, int(trial_id), clean_scope),
            )
            trial_key = int(trial_id)
    result = get_trial(trial_key, scope=clean_scope, db_path=db_path)
    if result is None:  # pragma: no cover
        raise TrialLedgerError("completed trial was not retrievable")
    return result


def record_rollback(
    trial_id: int,
    *,
    scope: str,
    restored_value: float,
    reason: str,
    recorded_at: float | None = None,
    evidence: Mapping[str, Any] | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Record proof of an exact rollback; never perform the rollback itself."""
    clean_scope = _scope(scope)
    restored = _number(restored_value, name="restored_value")
    clean_reason = " ".join(str(reason or "").split())
    if not clean_reason:
        raise TrialLedgerError("rollback reason is required")
    if len(clean_reason) > _MAX_REASON_LENGTH:
        raise TrialLedgerError(f"rollback reason exceeds {_MAX_REASON_LENGTH} characters")
    evidence_json = _payload(evidence, name="rollback evidence")
    init_db(db_path)
    with connect(db_path) as conn:
        row = _row_in_scope(conn, trial_id, clean_scope)
        spec = _decode_object(row["spec_json"], name="trial spec") or {}
        expected = float(spec["rollback_value"])
        if restored != expected:
            raise TrialLedgerError(
                f"restored_value must exactly equal rollback value {expected}"
            )
        existing = conn.execute(
            "SELECT * FROM experiment_trial_rollbacks WHERE trial_id=?",
            (int(trial_id),),
        ).fetchone()
        if existing is not None:
            same_time = recorded_at is None or float(existing["recorded_at"]) == _timestamp(
                recorded_at, name="recorded_at"
            )
            if (
                not same_time
                or float(existing["restored_value"]) != restored
                or str(existing["reason"]) != clean_reason
                or str(existing["evidence_json"]) != evidence_json
            ):
                raise TrialStateError("rollback was replayed with different data")
            trial_key = int(trial_id)
        else:
            if str(row["state"]) not in {RUNNING, COMPLETED}:
                raise TrialStateError("only a started trial can record rollback")
            stamp = _timestamp(
                time.time() if recorded_at is None else recorded_at, name="recorded_at"
            )
            if stamp < float(row["started_at"]):
                raise TrialStateError("rollback cannot predate trial start")
            conn.execute(
                """
                INSERT INTO experiment_trial_rollbacks
                    (trial_id, recorded_at, expected_value, restored_value,
                     reason, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(trial_id), stamp, expected, restored,
                    clean_reason, evidence_json,
                ),
            )
            conn.execute(
                """
                UPDATE experiment_trial_ledger
                SET state='rolled_back', ended_at=?, updated_at=?
                WHERE id=? AND scope=? AND state IN ('running','completed')
                """,
                (stamp, stamp, int(trial_id), clean_scope),
            )
            trial_key = int(trial_id)
    result = get_trial(trial_key, scope=clean_scope, db_path=db_path)
    if result is None:  # pragma: no cover
        raise TrialLedgerError("rolled-back trial was not retrievable")
    return result


__all__ = [
    "APPROVED",
    "ApprovalRequired",
    "COMPLETED",
    "ExperimentTrial",
    "ProposalApprovalProof",
    "REGISTERED",
    "ROLLED_BACK",
    "RUNNING",
    "TRIAL_STATES",
    "TrialLedgerError",
    "TrialNotFound",
    "TrialStateError",
    "UnvalidatedExperimentTrial",
    "approve_trial",
    "approve_trial_in_transaction",
    "complete_trial",
    "get_trial",
    "init_db",
    "record_metric_observation",
    "record_rollback",
    "register_trial",
    "spec_sha256",
    "spec_sha256_from_json",
    "start_trial",
]
