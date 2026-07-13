"""Durable Phase 8C7 settlement for closed qualified-response trials.

The runtime controller owns the reversible override and closes a valid elapsed
trial as ``rolled_back``. This module waits until that closure is durable and
all attributed outcome windows have settled, then stores one immutable,
aggregate-only creator-review snapshot. It never starts, approves, retunes, or
rolls back a trial.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from alpecca import trial_ledger
from alpecca.behavior_trial_controller import TRIAL_EXPIRATION_REASON
from alpecca.behavior_trial_evaluation import (
    BehaviorTrialEvaluationError,
    evaluate_qualified_response_trial,
)
from alpecca.behavior_trial_review import (
    BehaviorTrialReviewError,
    review_closed_qualified_response_trial,
)
from alpecca.db import connect
from alpecca.qualified_response_ledger import (
    CANCELLED,
    CREATOR_PERSONAL_SCOPE,
    DEFINITION_VERSION,
    DISPATCHING,
    METRIC_NAME,
    PENDING,
    RESPONDED,
    UNANSWERED,
    QualifiedResponseLedger,
)
from config import DB_PATH


SETTLEMENTS_TABLE = "behavior_trial_settlements"
CONTRACT_VERSION = 1
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY: set[Path] = set()

_SETTLEMENT_SELECT = f"""
    SELECT settlement.*,
           trial.id AS ledger_trial_id,
           trial.scope AS ledger_scope,
           trial.proposal_id AS ledger_proposal_id,
           trial.state AS ledger_state,
           trial.spec_json AS ledger_spec_json,
           trial.started_at AS ledger_started_at,
           trial.planned_end_at AS ledger_planned_end_at,
           trial.ended_at AS ledger_ended_at,
           rollback.recorded_at AS ledger_rollback_recorded_at,
           rollback.expected_value AS ledger_rollback_expected_value,
           rollback.restored_value AS ledger_rollback_restored_value,
           rollback.reason AS ledger_rollback_reason,
           rollback.evidence_json AS ledger_rollback_evidence_json
    FROM {SETTLEMENTS_TABLE} AS settlement
    LEFT JOIN experiment_trial_ledger AS trial ON trial.id=settlement.trial_id
    LEFT JOIN experiment_trial_rollbacks AS rollback ON rollback.trial_id=settlement.trial_id
"""


class BehaviorTrialSettlementError(ValueError):
    """A behavior-trial settlement could not be created or verified."""


def _positive_trial_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BehaviorTrialSettlementError("trial id must be a positive integer")
    return value


def _timestamp(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BehaviorTrialSettlementError(f"{name} must be numeric")
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0.0:
        raise BehaviorTrialSettlementError(
            f"{name} must be a finite non-negative timestamp"
        )
    return stamp


def _canonical_json(value: object, *, name: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise BehaviorTrialSettlementError(f"{name} is not canonical JSON") from exc


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def init_db(db_path: Path = DB_PATH) -> None:
    """Install the C7 settlement table and attribution fence idempotently."""
    path = Path(db_path).resolve()
    with _SCHEMA_LOCK:
        if path in _SCHEMA_READY:
            return
        trial_ledger.init_db(path)
        QualifiedResponseLedger(path)
        with connect(path) as conn:
            conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {SETTLEMENTS_TABLE} (
                trial_id            INTEGER PRIMARY KEY,
                scope               TEXT NOT NULL
                    CHECK (scope='creator-personal'),
                parameter           TEXT NOT NULL,
                metric              TEXT NOT NULL
                    CHECK (metric='qualified_response_rate'),
                definition_version  INTEGER NOT NULL CHECK (definition_version=1),
                spec_sha256         TEXT NOT NULL
                    CHECK (
                        length(spec_sha256)=64
                        AND spec_sha256 NOT GLOB '*[^0-9a-f]*'
                    ),
                settled_at          REAL NOT NULL,
                evidence_json       TEXT NOT NULL,
                evidence_sha256     TEXT NOT NULL
                    CHECK (
                        length(evidence_sha256)=64
                        AND evidence_sha256 NOT GLOB '*[^0-9a-f]*'
                    ),
                review_json         TEXT NOT NULL,
                review_sha256       TEXT NOT NULL
                    CHECK (
                        length(review_sha256)=64
                        AND review_sha256 NOT GLOB '*[^0-9a-f]*'
                    ),
                FOREIGN KEY(trial_id) REFERENCES experiment_trial_ledger(id)
                    ON DELETE RESTRICT
            );

            CREATE TRIGGER IF NOT EXISTS
                behavior_trial_settlement_blocks_new_outcome
            BEFORE INSERT ON qualified_response_outcomes
            WHEN NEW.trial_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM qualified_response_outcomes AS existing
                  WHERE existing.delivery_id=NEW.delivery_id
              )
              AND EXISTS (
                  SELECT 1 FROM {SETTLEMENTS_TABLE}
                  WHERE trial_id=NEW.trial_id
              )
            BEGIN
                SELECT RAISE(ABORT, 'settled behavior trial cannot receive new outcomes');
            END;
                """
            )
        _SCHEMA_READY.add(path)


def _trial_record_from_rows(
    trial_row: Mapping[str, Any],
    rollback_row: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    raw_spec = str(trial_row["spec_json"])
    try:
        spec = json.loads(raw_spec)
    except (TypeError, json.JSONDecodeError) as exc:
        raise BehaviorTrialSettlementError("stored trial spec is invalid") from exc
    if not isinstance(spec, dict):
        raise BehaviorTrialSettlementError("stored trial spec is not an object")
    spec_sha256 = trial_ledger.spec_sha256_from_json(raw_spec)
    try:
        rollback_evidence = json.loads(str(rollback_row["evidence_json"]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise BehaviorTrialSettlementError("stored rollback evidence is invalid") from exc
    if not isinstance(rollback_evidence, dict):
        raise BehaviorTrialSettlementError("stored rollback evidence is not an object")
    return ({
        "id": int(trial_row["id"]),
        "scope": str(trial_row["scope"]),
        "proposal_id": int(trial_row["proposal_id"]),
        "state": str(trial_row["state"]),
        "spec": spec,
        "spec_sha256": spec_sha256,
        "started_at": (
            None if trial_row["started_at"] is None else float(trial_row["started_at"])
        ),
        "planned_end_at": (
            None
            if trial_row["planned_end_at"] is None
            else float(trial_row["planned_end_at"])
        ),
        "ended_at": None if trial_row["ended_at"] is None else float(trial_row["ended_at"]),
        "rollback": {
            "recorded_at": float(rollback_row["recorded_at"]),
            "expected_value": float(rollback_row["expected_value"]),
            "restored_value": float(rollback_row["restored_value"]),
            "reason": str(rollback_row["reason"]),
            "evidence": rollback_evidence,
        },
    }, raw_spec)


def _immutable_trial_from_settlement(row: sqlite3.Row) -> dict[str, Any]:
    """Rebuild and verify the trial from the ledger, never from review JSON."""
    if row["ledger_trial_id"] is None or row["ledger_rollback_recorded_at"] is None:
        raise BehaviorTrialSettlementError(
            "stored settlement is missing its immutable trial or rollback ledger"
        )
    trial_row = {
        "id": row["ledger_trial_id"],
        "scope": row["ledger_scope"],
        "proposal_id": row["ledger_proposal_id"],
        "state": row["ledger_state"],
        "spec_json": row["ledger_spec_json"],
        "started_at": row["ledger_started_at"],
        "planned_end_at": row["ledger_planned_end_at"],
        "ended_at": row["ledger_ended_at"],
    }
    rollback_row = {
        "recorded_at": row["ledger_rollback_recorded_at"],
        "expected_value": row["ledger_rollback_expected_value"],
        "restored_value": row["ledger_rollback_restored_value"],
        "reason": row["ledger_rollback_reason"],
        "evidence_json": row["ledger_rollback_evidence_json"],
    }
    try:
        trial_record, raw_spec = _trial_record_from_rows(trial_row, rollback_row)
    except BehaviorTrialSettlementError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise BehaviorTrialSettlementError(
            "stored settlement trial ledger is invalid"
        ) from exc

    immutable_digest = trial_ledger.spec_sha256_from_json(raw_spec)
    spec = trial_record["spec"]
    if (
        int(trial_record["id"]) != int(row["trial_id"])
        or str(trial_record["scope"]) != str(row["scope"])
        or immutable_digest != str(row["spec_sha256"])
        or str(spec.get("parameter") or "") != str(row["parameter"])
        or str(spec.get("metric") or "") != str(row["metric"])
        or int(row["definition_version"]) != DEFINITION_VERSION
    ):
        raise BehaviorTrialSettlementError(
            "stored settlement does not match its immutable trial specification"
        )
    return trial_record


def _evidence_from_snapshot(conn: sqlite3.Connection, trial_id: int) -> dict[str, Any]:
    bucket = {
        "dispatching": 0,
        "pending": 0,
        "qualified_responses": 0,
        "unanswered": 0,
        "cancelled": 0,
    }
    rows = conn.execute(
        """
        SELECT state, COUNT(*) AS count
        FROM qualified_response_outcomes
        WHERE cohort='trial' AND trial_id=? AND metric=? AND definition_version=?
        GROUP BY state
        """,
        (trial_id, METRIC_NAME, DEFINITION_VERSION),
    ).fetchall()
    key_by_state = {
        DISPATCHING: "dispatching",
        PENDING: "pending",
        RESPONDED: "qualified_responses",
        UNANSWERED: "unanswered",
        CANCELLED: "cancelled",
    }
    for row in rows:
        key = key_by_state.get(str(row["state"]))
        if key is None:
            raise BehaviorTrialSettlementError("stored outcome state is invalid")
        bucket[key] = int(row["count"])
    completed = int(bucket["qualified_responses"]) + int(bucket["unanswered"])
    return {
        "metric": METRIC_NAME,
        "definition_version": DEFINITION_VERSION,
        "trial_id": trial_id,
        **bucket,
        "completed": completed,
        "rate": (
            None
            if completed == 0
            else float(bucket["qualified_responses"]) / completed
        ),
    }


_LEGACY_EVALUATION_FIELDS = (
    "metric",
    "definition_version",
    "trial_id",
    "spec_sha256",
    "baseline",
    "min_samples",
    "qualified_responses",
    "unanswered",
    "completed",
    "dispatching",
    "pending",
    "cancelled",
    "rate",
    "delta_from_baseline",
    "readiness",
    "recommendation",
)
_STRENGTHENED_EVALUATION_FIELDS = (
    "required_samples",
    "minimum_evidence_met",
    "effect_threshold",
    "creator_retention_eligible",
)
_STRENGTHENED_REVIEW_FIELDS = (
    "outcome",
    "creator_retention_eligible",
    "creator_retention_reason",
)


def _retention_contract(
    row: sqlite3.Row,
    evidence: Mapping[str, Any],
    review: Mapping[str, Any],
    trial_record: Mapping[str, Any],
) -> tuple[str, bool, str]:
    evaluation = review.get("evaluation")
    if not isinstance(evaluation, Mapping):
        raise BehaviorTrialSettlementError("stored settlement evaluation is invalid")
    try:
        expected = evaluate_qualified_response_trial(trial_record, evidence)
    except BehaviorTrialEvaluationError as exc:
        raise BehaviorTrialSettlementError(
            "stored settlement evaluation evidence is invalid"
        ) from exc
    if int(expected["dispatching"]) + int(expected["pending"]):
        raise BehaviorTrialSettlementError(
            "stored settlement still has outstanding outcomes"
        )

    for field in _LEGACY_EVALUATION_FIELDS:
        if evaluation.get(field) != expected[field]:
            raise BehaviorTrialSettlementError(
                f"stored settlement evaluation {field} is invalid"
            )

    strengthened_evaluation_fields = {
        field for field in _STRENGTHENED_EVALUATION_FIELDS if field in evaluation
    }
    strengthened_review_fields = {
        field for field in _STRENGTHENED_REVIEW_FIELDS if field in review
    }
    if strengthened_evaluation_fields and strengthened_evaluation_fields != set(
        _STRENGTHENED_EVALUATION_FIELDS
    ):
        raise BehaviorTrialSettlementError(
            "stored settlement evaluation contract is incomplete"
        )
    if strengthened_review_fields and strengthened_review_fields != set(
        _STRENGTHENED_REVIEW_FIELDS
    ):
        raise BehaviorTrialSettlementError("stored settlement review contract is incomplete")
    strengthened = bool(strengthened_evaluation_fields or strengthened_review_fields)
    if strengthened and not (
        strengthened_evaluation_fields and strengthened_review_fields
    ):
        raise BehaviorTrialSettlementError("stored settlement contracts do not match")

    if strengthened:
        for field in _STRENGTHENED_EVALUATION_FIELDS:
            if evaluation.get(field) != expected[field]:
                raise BehaviorTrialSettlementError(
                    f"stored settlement evaluation {field} is invalid"
                )
        if evaluation.get("comparison") != expected["comparison"]:
            raise BehaviorTrialSettlementError(
                "stored settlement evaluation comparison is invalid"
            )
    else:
        delta = expected["delta_from_baseline"]
        legacy_comparison = None
        if expected["readiness"] == "ready_for_creator_review":
            assert isinstance(delta, float)
            legacy_comparison = (
                "improved" if delta > 0.0 else ("worse" if delta < 0.0 else "unchanged")
            )
        if evaluation.get("comparison") != legacy_comparison:
            raise BehaviorTrialSettlementError(
                "stored legacy settlement comparison is invalid"
            )

    minimum_evidence_met = bool(expected["minimum_evidence_met"])
    expected_status = (
        "ready_for_creator_review"
        if minimum_evidence_met
        else "inconclusive_insufficient_samples"
    )
    status = review.get("status")
    if status != expected_status:
        raise BehaviorTrialSettlementError("stored settlement review status is invalid")
    expected_recommendation = (
        "creator_review_required"
        if minimum_evidence_met
        else "no_automatic_change"
    )
    if review.get("recommendation") != expected_recommendation:
        raise BehaviorTrialSettlementError(
            "stored settlement review recommendation is invalid"
        )

    outcome = (
        str(expected["comparison"])
        if minimum_evidence_met
        else "inconclusive"
    )
    if outcome not in {"improved", "degraded", "inconclusive"}:
        raise BehaviorTrialSettlementError("stored settlement outcome is invalid")
    eligible = outcome == "improved"
    reason = (
        {
            "improved": "improvement_meets_threshold",
            "degraded": "degraded_outcome",
            "inconclusive": "effect_below_threshold",
        }[outcome]
        if minimum_evidence_met
        else "insufficient_evidence"
    )
    if strengthened and (
        review.get("outcome") != outcome
        or review.get("creator_retention_eligible") is not eligible
        or review.get("creator_retention_reason") != reason
    ):
        raise BehaviorTrialSettlementError(
            "stored settlement creator retention contract is invalid"
        )
    return outcome, eligible, reason


def _stored_settlement(
    row: sqlite3.Row,
    source_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    evidence_raw = str(row["evidence_json"])
    review_raw = str(row["review_json"])
    if _digest(evidence_raw) != str(row["evidence_sha256"]):
        raise BehaviorTrialSettlementError("stored settlement evidence digest is invalid")
    if _digest(review_raw) != str(row["review_sha256"]):
        raise BehaviorTrialSettlementError("stored settlement review digest is invalid")
    try:
        evidence = json.loads(evidence_raw)
        review = json.loads(review_raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise BehaviorTrialSettlementError("stored settlement JSON is invalid") from exc
    if not isinstance(evidence, dict) or not isinstance(review, dict):
        raise BehaviorTrialSettlementError("stored settlement JSON is not an object")
    if _canonical_json(evidence, name="stored settlement evidence") != _canonical_json(
        source_evidence,
        name="outcome ledger evidence",
    ):
        raise BehaviorTrialSettlementError(
            "stored settlement evidence does not match the outcome ledger"
        )
    trial_record = _immutable_trial_from_settlement(row)
    try:
        expected_review = review_closed_qualified_response_trial(
            trial_record,
            source_evidence,
        )
    except BehaviorTrialReviewError as exc:
        raise BehaviorTrialSettlementError(
            "stored settlement trial or rollback contract is invalid"
        ) from exc
    if (
        int(row["trial_id"]) != _positive_trial_id(review.get("trial_id"))
        or str(row["spec_sha256"]) != str(review.get("spec_sha256"))
        or review.get("terminal_state") != expected_review["terminal_state"]
        or review.get("planned_end_at") != expected_review["planned_end_at"]
        or review.get("ended_at") != expected_review["ended_at"]
        or review.get("closure_reason") != TRIAL_EXPIRATION_REASON
        or review.get("status") not in {
            "ready_for_creator_review",
            "inconclusive_insufficient_samples",
        }
    ):
        raise BehaviorTrialSettlementError("stored settlement review contract is invalid")
    outcome, retention_eligible, retention_reason = _retention_contract(
        row,
        evidence,
        review,
        trial_record,
    )
    if all(field in review for field in _STRENGTHENED_REVIEW_FIELDS) and (
        _canonical_json(review, name="stored settlement review")
        != _canonical_json(expected_review, name="expected settlement review")
    ):
        raise BehaviorTrialSettlementError(
            "stored settlement review does not match the immutable trial evidence"
        )
    return {
        "contract_version": CONTRACT_VERSION,
        "trial_id": int(row["trial_id"]),
        "scope": str(row["scope"]),
        "parameter": str(row["parameter"]),
        "metric": str(row["metric"]),
        "definition_version": int(row["definition_version"]),
        "spec_sha256": str(row["spec_sha256"]),
        "settled_at": float(row["settled_at"]),
        "status": str(review["status"]),
        "recommendation": str(review["recommendation"]),
        "outcome": outcome,
        "creator_retention_eligible": retention_eligible,
        "creator_retention_reason": retention_reason,
        "evidence": evidence,
        "review": review,
    }


def settle_closed_trials(
    db_path: Path = DB_PATH,
    *,
    settled_at: float | None = None,
    clock: Callable[[], float] = time.time,
) -> list[dict[str, Any]]:
    """Freeze newly settled planned-expiry trials in one SQLite transaction.

    Trials with outstanding response windows remain unsealed and are retried by
    the next background tick. Once sealed, the database trigger refuses any new
    trial outcome, so repeated reads are stable and no behavior value changes.
    """
    if not callable(clock):
        raise BehaviorTrialSettlementError("clock must be callable")
    path = Path(db_path)
    init_db(path)
    stamp = _timestamp(clock() if settled_at is None else settled_at, name="settled_at")
    created: list[dict[str, Any]] = []
    with connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            f"""
            SELECT trial.*, rollback.recorded_at AS rollback_recorded_at,
                   rollback.expected_value AS rollback_expected_value,
                   rollback.restored_value AS rollback_restored_value,
                   rollback.reason AS rollback_reason,
                   rollback.evidence_json AS rollback_evidence_json
            FROM experiment_trial_ledger AS trial
            JOIN experiment_trial_rollbacks AS rollback ON rollback.trial_id=trial.id
            LEFT JOIN {SETTLEMENTS_TABLE} AS settlement ON settlement.trial_id=trial.id
            WHERE trial.scope=?
              AND trial.state=?
              AND rollback.reason=?
              AND settlement.trial_id IS NULL
            ORDER BY trial.id
            """,
            (
                CREATOR_PERSONAL_SCOPE,
                trial_ledger.ROLLED_BACK,
                TRIAL_EXPIRATION_REASON,
            ),
        ).fetchall()
        for row in rows:
            rollback_row = {
                "recorded_at": row["rollback_recorded_at"],
                "expected_value": row["rollback_expected_value"],
                "restored_value": row["rollback_restored_value"],
                "reason": row["rollback_reason"],
                "evidence_json": row["rollback_evidence_json"],
            }
            # sqlite3.Row is immutable, so construct a mapping-shaped record
            # the same way as the ledger's public reader.
            trial_record, _raw_spec = _trial_record_from_rows(row, rollback_row)
            trial_id = int(trial_record["id"])
            evidence = _evidence_from_snapshot(conn, trial_id)
            if int(evidence["dispatching"]) + int(evidence["pending"]):
                continue
            try:
                review = review_closed_qualified_response_trial(trial_record, evidence)
            except BehaviorTrialReviewError as exc:
                raise BehaviorTrialSettlementError(
                    f"trial {trial_id} cannot be settled"
                ) from exc
            evidence_json = _canonical_json(evidence, name="settlement evidence")
            review_json = _canonical_json(review, name="settlement review")
            conn.execute(
                f"""
                INSERT INTO {SETTLEMENTS_TABLE}
                    (trial_id, scope, parameter, metric, definition_version,
                     spec_sha256, settled_at, evidence_json, evidence_sha256,
                     review_json, review_sha256)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trial_id,
                    str(trial_record["scope"]),
                    str(trial_record["spec"].get("parameter") or ""),
                    METRIC_NAME,
                    DEFINITION_VERSION,
                    str(trial_record["spec_sha256"]),
                    stamp,
                    evidence_json,
                    _digest(evidence_json),
                    review_json,
                    _digest(review_json),
                ),
            )
            stored = conn.execute(
                _SETTLEMENT_SELECT + " WHERE settlement.trial_id=?",
                (trial_id,),
            ).fetchone()
            if stored is None:  # pragma: no cover - same-transaction invariant
                raise BehaviorTrialSettlementError("settlement was not retrievable")
            created.append(_stored_settlement(stored, evidence))
    return created


def get_settlement(
    trial_id: int,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Read one immutable settlement without touching live trial state."""
    trial_key = _positive_trial_id(trial_id)
    path = Path(db_path)
    database_uri = path.resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(database_uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                _SETTLEMENT_SELECT + " WHERE settlement.trial_id=?",
                (trial_key,),
            ).fetchone()
            evidence = (
                None
                if row is None
                else _evidence_from_snapshot(conn, trial_key)
            )
    except sqlite3.OperationalError as exc:
        raise BehaviorTrialSettlementError("settlement storage is unavailable") from exc
    return None if row is None else _stored_settlement(row, evidence)


def get_settlement_binding(
    trial_id: int,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Return a digest-only binding for a later creator review receipt.

    This intentionally omits the frozen outcome and review bodies. Callers can
    bind a decision to the exact C7 snapshot without re-exposing its contents or
    recalculating an evaluation.
    """
    trial_key = _positive_trial_id(trial_id)
    path = Path(db_path)
    database_uri = path.resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(database_uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                _SETTLEMENT_SELECT + " WHERE settlement.trial_id=?",
                (trial_key,),
            ).fetchone()
            evidence = (
                None
                if row is None
                else _evidence_from_snapshot(conn, trial_key)
            )
    except sqlite3.OperationalError as exc:
        raise BehaviorTrialSettlementError("settlement storage is unavailable") from exc
    if row is None:
        return None
    stored = _stored_settlement(row, evidence)
    return {
        "contract_version": int(stored["contract_version"]),
        "trial_id": int(stored["trial_id"]),
        "scope": str(stored["scope"]),
        "parameter": str(stored["parameter"]),
        "metric": str(stored["metric"]),
        "definition_version": int(stored["definition_version"]),
        "spec_sha256": str(stored["spec_sha256"]),
        "settled_at": float(stored["settled_at"]),
        "status": str(stored["status"]),
        "recommendation": str(stored["recommendation"]),
        "outcome": str(stored["outcome"]),
        "creator_retention_eligible": bool(stored["creator_retention_eligible"]),
        "creator_retention_reason": str(stored["creator_retention_reason"]),
        "evidence_sha256": str(row["evidence_sha256"]),
        "review_sha256": str(row["review_sha256"]),
    }


def list_settlements(
    db_path: Path = DB_PATH,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Read recent immutable settlements in stable newest-first order."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
        raise BehaviorTrialSettlementError("settlement limit must be between 1 and 25")
    path = Path(db_path)
    database_uri = path.resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(database_uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                _SETTLEMENT_SELECT + """
                ORDER BY settlement.settled_at DESC, settlement.trial_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            evidence_by_trial = {
                int(row["trial_id"]): _evidence_from_snapshot(
                    conn,
                    int(row["trial_id"]),
                )
                for row in rows
            }
    except sqlite3.OperationalError as exc:
        raise BehaviorTrialSettlementError("settlement storage is unavailable") from exc
    return [
        _stored_settlement(row, evidence_by_trial[int(row["trial_id"])])
        for row in rows
    ]


__all__ = [
    "BehaviorTrialSettlementError",
    "CONTRACT_VERSION",
    "SETTLEMENTS_TABLE",
    "get_settlement_binding",
    "get_settlement",
    "init_db",
    "list_settlements",
    "settle_closed_trials",
]
