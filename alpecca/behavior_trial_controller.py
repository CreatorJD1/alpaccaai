"""Creator-owned runtime control for the first bounded behavior trial.

This is deliberately a narrow Phase 8B foundation.  It persists a single
runtime-only value in SQLite, but never writes configuration, source files, or
system state.  The existing trial ledger remains the durable record of the
specification, approval, timing, and rollback receipt; this controller adds the
atomic apply/readback/rollback boundary that the ledger intentionally does not
own.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from alpecca import self_improvement_policy
from alpecca import trial_ledger
from alpecca.db import connect
from alpecca.experiment_trials import ValidatedTrialSpecification
from alpecca.trial_ledger import ProposalApprovalProof
from config import DB_PATH, Proactive


CREATOR_PERSONAL_SCOPE = "creator-personal"
CHATTER_CHANCE_PARAMETER = "chatter_chance"
INTERRUPTED_RECOVERY_REASON = "interrupted runtime-only behavior trial recovery"
TRIAL_EXPIRATION_REASON = "planned behavior trial exposure elapsed"


class BehaviorTrialControllerError(ValueError):
    """The controller cannot safely apply or restore a behavior value."""


class ForeignBehaviorTrialScope(BehaviorTrialControllerError):
    """The controller was asked to operate outside its creator-owned scope."""


class UnsupportedBehaviorTrial(BehaviorTrialControllerError):
    """The trial targets a behavior this foundation does not implement."""


class RuntimeOverrideError(BehaviorTrialControllerError):
    """Persisted runtime state does not prove the expected apply/restore value."""


def _finite_number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BehaviorTrialControllerError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise BehaviorTrialControllerError(f"{name} must be finite")
    return result


def _timestamp(value: object, *, name: str) -> float:
    stamp = _finite_number(value, name=name)
    if stamp < 0.0:
        raise BehaviorTrialControllerError(
            f"{name} must be a finite non-negative timestamp"
        )
    return stamp


def _trial_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BehaviorTrialControllerError("trial_id must be a positive integer")
    return value


def _rollback_reason(value: object) -> str:
    cleaned = " ".join(str(value or "").split())
    if not cleaned:
        raise BehaviorTrialControllerError("rollback reason is required")
    if len(cleaned) > 1000:
        raise BehaviorTrialControllerError("rollback reason exceeds 1000 characters")
    return cleaned


def _json_object(raw: object, *, name: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise BehaviorTrialControllerError(f"stored {name} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise BehaviorTrialControllerError(f"stored {name} is not an object")
    return value


class BehaviorTrialController:
    """Approval-proof-backed internal foundation for one ``chatter_chance`` override.

    ``default_chatter_chance`` is an injected runtime baseline for tests and
    host wiring.  It is never copied into or written back to ``config.py``.
    """

    def __init__(
        self,
        db_path: Path = DB_PATH,
        scope: str = CREATOR_PERSONAL_SCOPE,
        default_chatter_chance: float = Proactive.CHATTER_CHANCE,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if scope != CREATOR_PERSONAL_SCOPE:
            raise ForeignBehaviorTrialScope(
                "behavior trials require the creator-personal scope"
            )
        chance = _finite_number(
            default_chatter_chance, name="default_chatter_chance"
        )
        if not 0.0 <= chance <= 1.0:
            raise BehaviorTrialControllerError(
                "default_chatter_chance must be between 0 and 1"
            )
        if clock is not None and not callable(clock):
            raise BehaviorTrialControllerError("clock must be callable")
        self.db_path = Path(db_path)
        self.scope = CREATOR_PERSONAL_SCOPE
        self.default_chatter_chance = chance
        self._clock = time.time if clock is None else clock
        self._schema_ready = False
        self._schema_lock = threading.Lock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Install the ledger and runtime schema once per controller instance."""
        with self._schema_lock:
            if self._schema_ready:
                return
            trial_ledger.init_db(self.db_path)
            with connect(self.db_path) as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.executescript(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS
                        behavior_trial_creator_personal_active_unique_idx
                    ON experiment_trial_ledger(scope)
                    WHERE scope='creator-personal'
                      AND state IN ('approved','running');

                    CREATE TABLE IF NOT EXISTS behavior_trial_runtime_overrides (
                        trial_id       INTEGER PRIMARY KEY,
                        scope          TEXT NOT NULL CHECK (scope='creator-personal'),
                        parameter      TEXT NOT NULL CHECK (parameter='chatter_chance'),
                        preimage_value REAL NOT NULL,
                        override_value REAL NOT NULL,
                        applied_at     REAL NOT NULL,
                        UNIQUE(scope, parameter),
                        FOREIGN KEY(trial_id) REFERENCES experiment_trial_ledger(id)
                            ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS behavior_trial_runtime_scope_idx
                        ON behavior_trial_runtime_overrides(scope, parameter, trial_id);
                    """
                )
            self._schema_ready = True

    def _now(self) -> float:
        return _timestamp(self._clock(), name="clock timestamp")

    def _require_supported_spec(self, spec: object) -> None:
        parameter = getattr(spec, "parameter", None)
        if parameter is not None and parameter != CHATTER_CHANCE_PARAMETER:
            raise UnsupportedBehaviorTrial(
                "this controller supports only chatter_chance trials"
            )

    def _record_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        spec = _json_object(row["spec_json"], name="trial spec")
        if spec is None:  # pragma: no cover - schema invariant
            raise BehaviorTrialControllerError("stored trial has no specification")
        return {
            "id": int(row["id"]),
            "scope": str(row["scope"]),
            "proposal_id": int(row["proposal_id"]),
            "state": str(row["state"]),
            "spec": spec,
            "approval_proof": _json_object(row["approval_json"], name="approval proof"),
        }

    def _require_supported_record(self, record: Mapping[str, Any]) -> None:
        if record.get("scope") != self.scope:
            raise ForeignBehaviorTrialScope(
                "behavior trial record belongs to another scope"
            )
        spec = record.get("spec")
        if not isinstance(spec, Mapping) or spec.get("parameter") != CHATTER_CHANCE_PARAMETER:
            raise UnsupportedBehaviorTrial(
                "this controller supports only chatter_chance trials"
            )

    def _row_in_scope(
        self, conn: sqlite3.Connection, trial_id: int
    ) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM experiment_trial_ledger WHERE id=? AND scope=?",
            (trial_id, self.scope),
        ).fetchone()
        if row is None:
            raise trial_ledger.TrialNotFound(
                f"trial {trial_id} was not found in scope {self.scope!r}"
            )
        return row

    def _other_active_trial_exists(self, trial_id: int) -> bool:
        with connect(self.db_path) as conn:
            return (
                conn.execute(
                    """
                    SELECT 1
                    FROM experiment_trial_ledger
                    WHERE scope=? AND state IN ('approved','running') AND id<>?
                    LIMIT 1
                    """,
                    (self.scope, trial_id),
                ).fetchone()
                is not None
            )

    def _runtime_override(
        self, conn: sqlite3.Connection
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT * FROM behavior_trial_runtime_overrides
            WHERE scope=? AND parameter=?
            """,
            (self.scope, CHATTER_CHANCE_PARAMETER),
        ).fetchone()

    def _stored_chatter_chance(self, conn: sqlite3.Connection) -> float:
        row = self._runtime_override(conn)
        if row is None:
            return self.default_chatter_chance
        return _finite_number(row["override_value"], name="stored chatter override")

    def _spec_values(
        self, record: Mapping[str, Any]
    ) -> tuple[float, float, float]:
        self._require_supported_record(record)
        spec = record["spec"]
        assert isinstance(spec, Mapping)  # narrowed by _require_supported_record
        return (
            _finite_number(spec.get("old_value"), name="trial old_value"),
            _finite_number(spec.get("trial_value"), name="trial trial_value"),
            _finite_number(spec.get("rollback_value"), name="trial rollback_value"),
        )

    def _assert_default_preimage(self, record: Mapping[str, Any]) -> tuple[float, float]:
        old_value, trial_value, rollback_value = self._spec_values(record)
        if old_value != self.default_chatter_chance:
            raise RuntimeOverrideError(
                "trial old_value does not exactly match the chatter default"
            )
        if rollback_value != old_value:
            raise RuntimeOverrideError(
                "trial rollback_value does not exactly match its old_value"
            )
        return old_value, trial_value

    def _assert_override_matches(
        self,
        conn: sqlite3.Connection,
        *,
        trial_id: int,
        old_value: float,
        trial_value: float,
    ) -> None:
        override = self._runtime_override(conn)
        if override is None:
            raise RuntimeOverrideError("running trial has no runtime override")
        if int(override["trial_id"]) != trial_id:
            raise RuntimeOverrideError(
                "another trial owns the active chatter runtime override"
            )
        if (
            str(override["scope"]) != self.scope
            or str(override["parameter"]) != CHATTER_CHANCE_PARAMETER
            or _finite_number(override["preimage_value"], name="stored preimage")
            != old_value
            or _finite_number(override["override_value"], name="stored override")
            != trial_value
        ):
            raise RuntimeOverrideError("stored runtime override does not match the trial")

    def _remove_override_and_read_default(
        self,
        conn: sqlite3.Connection,
        *,
        trial_id: int,
        old_value: float,
        trial_value: float,
        require_override: bool,
    ) -> bool:
        override = self._runtime_override(conn)
        if override is None:
            if require_override:
                raise RuntimeOverrideError("running trial has no runtime override to remove")
            if self._stored_chatter_chance(conn) != self.default_chatter_chance:
                raise RuntimeOverrideError("chatter chance did not read back to its default")
            return False
        self._assert_override_matches(
            conn,
            trial_id=trial_id,
            old_value=old_value,
            trial_value=trial_value,
        )
        deleted = conn.execute(
            "DELETE FROM behavior_trial_runtime_overrides WHERE trial_id=?",
            (trial_id,),
        )
        if deleted.rowcount != 1:  # pragma: no cover - protected by the row lookup
            raise RuntimeOverrideError("runtime override removal did not affect one row")
        if self._stored_chatter_chance(conn) != self.default_chatter_chance:
            raise RuntimeOverrideError("chatter chance did not read back to its default")
        return True

    @staticmethod
    def _rollback_evidence_json(trial_id: int, *, override_was_present: bool) -> str:
        return json.dumps(
            {
                "runtime_override": {
                    "parameter": CHATTER_CHANCE_PARAMETER,
                    "trial_id": trial_id,
                    "removed": True,
                    "was_present": override_was_present,
                }
            },
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _assert_exact_existing_rollback(
        self,
        conn: sqlite3.Connection,
        *,
        trial_id: int,
        old_value: float,
        reason: str,
        recorded_at: float | None,
    ) -> bool:
        existing = conn.execute(
            "SELECT * FROM experiment_trial_rollbacks WHERE trial_id=?",
            (trial_id,),
        ).fetchone()
        if existing is None:
            return False
        if recorded_at is not None and float(existing["recorded_at"]) != recorded_at:
            raise trial_ledger.TrialStateError(
                "rollback was replayed with a different timestamp"
            )
        expected_evidence = self._rollback_evidence_json(
            trial_id, override_was_present=True
        )
        if (
            float(existing["expected_value"]) != old_value
            or float(existing["restored_value"]) != self.default_chatter_chance
            or str(existing["reason"]) != reason
            or str(existing["evidence_json"]) != expected_evidence
        ):
            raise trial_ledger.TrialStateError(
                "rollback was replayed with different data"
            )
        if self._runtime_override(conn) is not None:
            raise RuntimeOverrideError(
                "rolled-back trial still has an active runtime override"
            )
        if self._stored_chatter_chance(conn) != self.default_chatter_chance:
            raise RuntimeOverrideError("chatter chance did not read back to its default")
        return True

    def _deny_start_from_policy(
        self,
        record: Mapping[str, Any],
        active_trials: list[dict[str, Any]],
    ) -> None:
        decision = self_improvement_policy.evaluate_trial(
            record,
            scope=self.scope,
            active_trials=active_trials,
        )
        if decision.allowed:
            return
        if decision.reason in {"approval_required", "scope_mismatch"}:
            raise trial_ledger.ApprovalRequired(
                f"self-improvement policy denied trial: {decision.reason}"
            )
        if decision.reason == "conflicting_trial":
            raise trial_ledger.TrialStateError(
                "self-improvement policy denied a conflicting active trial"
            )
        if decision.reason == "unvalidated_spec":
            raise trial_ledger.UnvalidatedExperimentTrial(
                "self-improvement policy denied an unvalidated trial"
            )
        raise BehaviorTrialControllerError(
            f"self-improvement policy denied trial: {decision.reason}"
        )

    def register(self, validated_spec: ValidatedTrialSpecification) -> dict[str, Any]:
        """Persist a validator-produced chatter trial specification."""
        self._ensure_schema()
        self._require_supported_spec(validated_spec)
        return trial_ledger.register_trial(
            validated_spec,
            scope=self.scope,
            db_path=self.db_path,
        )

    def approve(
        self, trial_id: int, proof: ProposalApprovalProof
    ) -> dict[str, Any]:
        """Attach one scope-bound authoritative approval proof."""
        self._ensure_schema()
        trial_key = _trial_id(trial_id)
        existing = self.get(trial_key)
        if existing is None:
            raise trial_ledger.TrialNotFound(
                f"trial {trial_key} was not found in scope {self.scope!r}"
            )
        self._require_supported_record(existing)
        if (
            existing["state"] == trial_ledger.REGISTERED
            and self._other_active_trial_exists(trial_key)
        ):
            raise trial_ledger.TrialStateError(
                "another approved or running creator-personal behavior trial is already active"
            )
        try:
            return trial_ledger.approve_trial(
                trial_key,
                proof,
                scope=self.scope,
                db_path=self.db_path,
            )
        except sqlite3.IntegrityError as exc:
            if self._other_active_trial_exists(trial_key) or (
                "UNIQUE constraint failed: experiment_trial_ledger.scope" in str(exc)
            ):
                raise trial_ledger.TrialStateError(
                    "another approved or running creator-personal behavior trial is already active"
                ) from exc
            raise

    def start(
        self, trial_id: int, started_at: float | None = None
    ) -> dict[str, Any]:
        """Atomically apply, read back, and ledger-start one approved trial."""
        self._ensure_schema()
        trial_key = _trial_id(trial_id)
        requested_started_at = (
            None if started_at is None else _timestamp(started_at, name="started_at")
        )
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            row = self._row_in_scope(conn, trial_key)
            record = self._record_from_row(row)
            self._require_supported_record(record)
            state = str(row["state"])
            if state == trial_ledger.RUNNING:
                old_value, trial_value = self._assert_default_preimage(record)
                if (
                    requested_started_at is not None
                    and float(row["started_at"]) != requested_started_at
                ):
                    raise trial_ledger.TrialStateError(
                        "trial already started at a different timestamp"
                    )
                self._assert_override_matches(
                    conn,
                    trial_id=trial_key,
                    old_value=old_value,
                    trial_value=trial_value,
                )
                if self._stored_chatter_chance(conn) != trial_value:
                    raise RuntimeOverrideError(
                        "runtime chatter override did not read back after start"
                    )
            else:
                if row["approval_json"] is None or state == trial_ledger.REGISTERED:
                    raise trial_ledger.ApprovalRequired(
                        "trial start requires stored proposal approval proof"
                    )
                if state != trial_ledger.APPROVED:
                    raise trial_ledger.TrialStateError(
                        f"cannot start a {state} trial"
                    )
                active_rows = conn.execute(
                    """
                    SELECT * FROM experiment_trial_ledger
                    WHERE scope=? AND state IN ('approved','running')
                    ORDER BY id
                    """,
                    (self.scope,),
                ).fetchall()
                self._deny_start_from_policy(
                    record,
                    [self._record_from_row(item) for item in active_rows],
                )
                old_value, trial_value = self._assert_default_preimage(record)
                if self._runtime_override(conn) is not None:
                    raise RuntimeOverrideError(
                        "another trial already owns the active chatter runtime override"
                    )
                if self._stored_chatter_chance(conn) != old_value:
                    raise RuntimeOverrideError(
                        "chatter chance does not read back to the trial preimage"
                    )
                stamp = (
                    self._now()
                    if requested_started_at is None
                    else requested_started_at
                )
                proof = record["approval_proof"]
                if not isinstance(proof, Mapping):  # policy already fails this closed
                    raise trial_ledger.ApprovalRequired(
                        "trial start requires stored proposal approval proof"
                    )
                approved_at = _timestamp(proof.get("approved_at"), name="approved_at")
                if stamp < approved_at:
                    raise trial_ledger.TrialStateError(
                        "trial cannot start before its approval timestamp"
                    )
                spec = record["spec"]
                assert isinstance(spec, Mapping)  # narrowed by _require_supported_record
                exposure_seconds = _finite_number(
                    spec.get("exposure_seconds"), name="trial exposure_seconds"
                )
                planned_end_at = stamp + exposure_seconds
                conn.execute(
                    """
                    INSERT INTO behavior_trial_runtime_overrides
                        (trial_id, scope, parameter, preimage_value, override_value, applied_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trial_key,
                        self.scope,
                        CHATTER_CHANCE_PARAMETER,
                        old_value,
                        trial_value,
                        stamp,
                    ),
                )
                self._assert_override_matches(
                    conn,
                    trial_id=trial_key,
                    old_value=old_value,
                    trial_value=trial_value,
                )
                if self._stored_chatter_chance(conn) != trial_value:
                    raise RuntimeOverrideError(
                        "runtime chatter override did not read back after apply"
                    )
                updated = conn.execute(
                    """
                    UPDATE experiment_trial_ledger
                    SET state='running', started_at=?, planned_end_at=?, updated_at=?
                    WHERE id=? AND scope=? AND state='approved'
                    """,
                    (stamp, planned_end_at, stamp, trial_key, self.scope),
                )
                if updated.rowcount != 1:  # pragma: no cover - BEGIN IMMEDIATE fences races
                    raise trial_ledger.TrialStateError("trial start lost its approved state")
        result = self.get(trial_key)
        if result is None:  # pragma: no cover - same-database invariant
            raise BehaviorTrialControllerError("started trial was not retrievable")
        return result

    def chatter_chance(self) -> float:
        """Return the effective chance after atomically expiring due trials."""
        self._ensure_schema()
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            expiration_stamp = self._now()
            self._expire_due_in_transaction(conn, recorded_at=expiration_stamp)
            row = conn.execute(
                """
                SELECT runtime.override_value, trial.planned_end_at
                FROM behavior_trial_runtime_overrides AS runtime
                JOIN experiment_trial_ledger AS trial ON trial.id=runtime.trial_id
                WHERE runtime.scope=? AND runtime.parameter=?
                  AND trial.scope=? AND trial.state='running'
                """,
                (self.scope, CHATTER_CHANCE_PARAMETER, self.scope),
            ).fetchone()
            if row is None:
                chance = self.default_chatter_chance
            else:
                planned_end_at = row["planned_end_at"]
                if (
                    planned_end_at is None
                    or _timestamp(planned_end_at, name="planned_end_at")
                    <= expiration_stamp
                ):
                    raise RuntimeOverrideError(
                        "a due chatter trial still has an active runtime override"
                    )
                chance = _finite_number(
                    row["override_value"], name="stored chatter override"
                )
        return chance

    def _rollback_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        reason: str,
        recorded_at: float | None,
        require_override: bool,
    ) -> int:
        record = self._record_from_row(row)
        self._require_supported_record(record)
        trial_key = int(row["id"])
        old_value, trial_value = self._assert_default_preimage(record)
        if self._assert_exact_existing_rollback(
            conn,
            trial_id=trial_key,
            old_value=old_value,
            reason=reason,
            recorded_at=recorded_at,
        ):
            return trial_key
        state = str(row["state"])
        if state not in {trial_ledger.RUNNING, trial_ledger.COMPLETED}:
            raise trial_ledger.TrialStateError("only a started trial can record rollback")
        stamp = self._now() if recorded_at is None else recorded_at
        if row["started_at"] is None or stamp < float(row["started_at"]):
            raise trial_ledger.TrialStateError("rollback cannot predate trial start")
        override_was_present = self._remove_override_and_read_default(
            conn,
            trial_id=trial_key,
            old_value=old_value,
            trial_value=trial_value,
            require_override=require_override,
        )
        evidence_json = self._rollback_evidence_json(
            trial_key, override_was_present=override_was_present
        )
        conn.execute(
            """
            INSERT INTO experiment_trial_rollbacks
                (trial_id, recorded_at, expected_value, restored_value,
                 reason, evidence_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                trial_key,
                stamp,
                old_value,
                self.default_chatter_chance,
                reason,
                evidence_json,
            ),
        )
        updated = conn.execute(
            """
            UPDATE experiment_trial_ledger
            SET state='rolled_back', ended_at=?, updated_at=?
            WHERE id=? AND scope=? AND state IN ('running','completed')
            """,
            (stamp, stamp, trial_key, self.scope),
        )
        if updated.rowcount != 1:  # pragma: no cover - BEGIN IMMEDIATE fences races
            raise trial_ledger.TrialStateError("trial rollback lost its running state")
        return trial_key

    def _expire_due_in_transaction(
        self, conn: sqlite3.Connection, *, recorded_at: float
    ) -> list[int]:
        rows = conn.execute(
            """
            SELECT * FROM experiment_trial_ledger
            WHERE scope=? AND state='running'
              AND (planned_end_at IS NULL OR planned_end_at <= ?)
            ORDER BY id
            """,
            (self.scope, recorded_at),
        ).fetchall()
        expired_ids: list[int] = []
        for row in rows:
            record = self._record_from_row(row)
            spec = record.get("spec")
            if not isinstance(spec, Mapping):  # _record_from_row guarantees this
                raise BehaviorTrialControllerError("stored trial has no specification")
            if spec.get("parameter") != CHATTER_CHANCE_PARAMETER:
                continue
            expired_ids.append(
                self._rollback_in_transaction(
                    conn,
                    row=row,
                    reason=TRIAL_EXPIRATION_REASON,
                    recorded_at=recorded_at,
                    require_override=False,
                )
            )
        return expired_ids

    def rollback(
        self,
        trial_id: int,
        reason: str,
        recorded_at: float | None = None,
    ) -> dict[str, Any]:
        """Atomically remove/read back the override before recording rollback."""
        self._ensure_schema()
        trial_key = _trial_id(trial_id)
        clean_reason = _rollback_reason(reason)
        requested_recorded_at = (
            None
            if recorded_at is None
            else _timestamp(recorded_at, name="recorded_at")
        )
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            row = self._row_in_scope(conn, trial_key)
            self._rollback_in_transaction(
                conn,
                row=row,
                reason=clean_reason,
                recorded_at=requested_recorded_at,
                require_override=True,
            )
        result = self.get(trial_key)
        if result is None:  # pragma: no cover - same-database invariant
            raise BehaviorTrialControllerError("rolled-back trial was not retrievable")
        return result

    def expire_due(self) -> list[dict[str, Any]]:
        """Atomically receipt and roll back chatter trials at their planned end."""
        self._ensure_schema()
        expiration_stamp = self._now()
        expired_ids: list[int] = []
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            expired_ids = self._expire_due_in_transaction(
                conn, recorded_at=expiration_stamp
            )
        results: list[dict[str, Any]] = []
        for trial_key in expired_ids:
            result = self.get(trial_key)
            if result is None:  # pragma: no cover - same-database invariant
                raise BehaviorTrialControllerError("expired trial was not retrievable")
            results.append(result)
        return results

    def recover_interrupted(
        self, recorded_at: float | None = None
    ) -> list[dict[str, Any]]:
        """Close interrupted chatter trials after a process restart.

        A normal controller start commits both the override and ``running``
        state together.  Recovery also closes older ledger-only running rows:
        no runtime row means the chance already reads as its default, which is
        still durably receipted before the stale trial is left behind.
        """
        self._ensure_schema()
        recovery_stamp = (
            self._now()
            if recorded_at is None
            else _timestamp(recorded_at, name="recorded_at")
        )
        recovered_ids: list[int] = []
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT * FROM experiment_trial_ledger
                WHERE scope=? AND state IN ('running','completed')
                ORDER BY id
                """,
                (self.scope,),
            ).fetchall()
            for row in rows:
                record = self._record_from_row(row)
                spec = record.get("spec")
                if not isinstance(spec, Mapping):  # _record_from_row guarantees this
                    raise BehaviorTrialControllerError("stored trial has no specification")
                if spec.get("parameter") != CHATTER_CHANCE_PARAMETER:
                    continue
                recovered_ids.append(
                    self._rollback_in_transaction(
                        conn,
                        row=row,
                        reason=INTERRUPTED_RECOVERY_REASON,
                        recorded_at=recovery_stamp,
                        require_override=False,
                    )
                )

            # A terminal row with an override cannot arise from the controller's
            # atomic paths, but remove it rather than leave an effective value
            # behind after an interrupted/manual database operation.
            stale = self._runtime_override(conn)
            if stale is not None:
                stale_id = int(stale["trial_id"])
                stale_row = self._row_in_scope(conn, stale_id)
                stale_record = self._record_from_row(stale_row)
                self._require_supported_record(stale_record)
                old_value, trial_value = self._assert_default_preimage(stale_record)
                if str(stale_row["state"]) in {
                    trial_ledger.RUNNING,
                    trial_ledger.COMPLETED,
                }:
                    raise RuntimeOverrideError(
                        "interrupted runtime override was not selected for recovery"
                    )
                self._remove_override_and_read_default(
                    conn,
                    trial_id=stale_id,
                    old_value=old_value,
                    trial_value=trial_value,
                    require_override=True,
                )
        results: list[dict[str, Any]] = []
        for trial_key in recovered_ids:
            result = self.get(trial_key)
            if result is None:  # pragma: no cover - same-database invariant
                raise BehaviorTrialControllerError("recovered trial was not retrievable")
            results.append(result)
        return results

    def get(self, trial_id: int) -> dict[str, Any] | None:
        """Return one scoped ledger record, rejecting unsupported targets."""
        self._ensure_schema()
        trial_key = _trial_id(trial_id)
        record = trial_ledger.get_trial(
            trial_key,
            scope=self.scope,
            db_path=self.db_path,
        )
        if record is not None:
            self._require_supported_record(record)
        return record


__all__ = [
    "BehaviorTrialController",
    "BehaviorTrialControllerError",
    "CHATTER_CHANCE_PARAMETER",
    "CREATOR_PERSONAL_SCOPE",
    "ForeignBehaviorTrialScope",
    "INTERRUPTED_RECOVERY_REASON",
    "ProposalApprovalProof",
    "RuntimeOverrideError",
    "TRIAL_EXPIRATION_REASON",
    "UnsupportedBehaviorTrial",
]
