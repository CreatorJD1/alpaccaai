"""Creator-decided, durable profile values for bounded behavior RSI.

The runtime trial controller always restores its preimage before review. This
module is the separate commit boundary: only a creator-authenticated decision
against an immutable settlement may make either the trial value or its prior
baseline the profile used by the next cycle. It never edits source or config.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import sqlite3
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from alpecca import behavior_trial_settlement as settlement_mod
from alpecca import trial_ledger
from alpecca.db import connect
from config import DB_PATH


CREATOR_PERSONAL_SCOPE = "creator-personal"
PROFILE_PARAMETER = "chatter_chance"
RETAIN_TRIAL_VALUE = "retain_trial_value"
REVERT_TO_BASELINE = "revert_to_baseline"
PROFILE_DECISIONS_TABLE = "behavior_trial_profile_decisions"
ACTIVE_PROFILE_TABLE = "behavior_trial_active_profile"
DECISION_CONTRACT_VERSION = 1
_DECISIONS = frozenset({RETAIN_TRIAL_VALUE, REVERT_TO_BASELINE})
_DECISION_DOMAIN = "alpecca.behavior-trial.profile-decision.v1"
_PROFILE_DOMAIN = "alpecca.behavior-trial.active-profile.v1"


class BehaviorTrialProfileError(ValueError):
    """A settled trial cannot safely update the retained behavior profile."""


class ProfileDecisionNotEligible(BehaviorTrialProfileError):
    """The requested decision is not allowed by the frozen evidence."""


class ProfileDecisionIntegrityError(BehaviorTrialProfileError):
    """Stored trial, settlement, decision, or profile data do not agree."""


class ProfileDecisionSealUnavailable(BehaviorTrialProfileError):
    """The process has no protected key with which to verify profile state."""


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
        raise BehaviorTrialProfileError(f"{name} is not canonical JSON") from exc


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _positive_id(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BehaviorTrialProfileError(f"{name} must be a positive integer")
    return value


def _timestamp(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BehaviorTrialProfileError(f"{name} must be numeric")
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0.0:
        raise BehaviorTrialProfileError(f"{name} must be finite and non-negative")
    return stamp


def _optional_timestamp(value: object, *, name: str) -> float | None:
    return None if value is None else _timestamp(value, name=name)


def _probability(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BehaviorTrialProfileError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise BehaviorTrialProfileError(f"{name} must be between 0 and 1")
    return result


def _identifier(value: object, *, name: str, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise BehaviorTrialProfileError(f"{name} must be text")
    cleaned = value.strip()
    if (
        not cleaned
        or cleaned != value
        or len(cleaned) > maximum
        or any(ord(char) < 32 for char in cleaned)
    ):
        raise BehaviorTrialProfileError(f"{name} is invalid")
    return cleaned


def _sha256(value: object, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ProfileDecisionIntegrityError(f"{name} is invalid")
    return value


def _decision(value: object) -> str:
    if not isinstance(value, str) or value not in _DECISIONS:
        raise ProfileDecisionNotEligible(
            "decision must be retain_trial_value or revert_to_baseline"
        )
    return value


def _settlement_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    trial_id = _positive_id(value.get("trial_id"), name="settlement trial id")
    scope = _identifier(value.get("scope"), name="settlement scope")
    parameter = _identifier(value.get("parameter"), name="settlement parameter")
    status = _identifier(value.get("status"), name="settlement status")
    outcome = _identifier(value.get("outcome"), name="settlement outcome")
    if scope != CREATOR_PERSONAL_SCOPE or parameter != PROFILE_PARAMETER:
        raise ProfileDecisionIntegrityError("settlement profile scope is invalid")
    if status not in {
        "ready_for_creator_review",
        "inconclusive_insufficient_samples",
    }:
        raise ProfileDecisionNotEligible("settlement is not ready for a decision")
    return {
        "contract_version": _positive_id(
            value.get("contract_version"), name="settlement contract version"
        ),
        "trial_id": trial_id,
        "scope": scope,
        "parameter": parameter,
        "metric": _identifier(value.get("metric"), name="settlement metric"),
        "definition_version": _positive_id(
            value.get("definition_version"), name="settlement definition version"
        ),
        "spec_sha256": _sha256(
            value.get("spec_sha256"), name="settlement spec digest"
        ),
        "settled_at": _timestamp(value.get("settled_at"), name="settled_at"),
        "status": status,
        "recommendation": _identifier(
            value.get("recommendation"), name="settlement recommendation"
        ),
        "outcome": outcome,
        "creator_retention_eligible": bool(
            value.get("creator_retention_eligible") is True
        ),
        "creator_retention_reason": _identifier(
            value.get("creator_retention_reason"),
            name="creator retention reason",
        ),
        "evidence_sha256": _sha256(
            value.get("evidence_sha256"), name="settlement evidence digest"
        ),
        "review_sha256": _sha256(
            value.get("review_sha256"), name="settlement review digest"
        ),
    }


class BehaviorTrialProfileStore:
    """Persist one sealed creator decision and the resulting active profile."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        seal_key: bytes | bytearray | memoryview | str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self._seal_key: bytes | None = None
        self._schema_lock = threading.Lock()
        self._schema_ready = False
        self.set_seal_key(seal_key)
        self._ensure_schema()

    def set_seal_key(
        self, seal_key: bytes | bytearray | memoryview | str | None
    ) -> None:
        if seal_key is None:
            self._seal_key = None
            return
        if isinstance(seal_key, str):
            seal_key = seal_key.encode("utf-8")
        if not isinstance(seal_key, (bytes, bytearray, memoryview)):
            raise TypeError("seal_key must be bytes, text, or None")
        key = bytes(seal_key)
        if not key:
            raise ValueError("seal_key must not be empty")
        self._seal_key = key

    def _require_seal_key(self) -> bytes:
        if self._seal_key is None:
            raise ProfileDecisionSealUnavailable("profile decision seal key is unavailable")
        return self._seal_key

    def _ensure_schema(self) -> None:
        with self._schema_lock:
            if self._schema_ready:
                return
            settlement_mod.init_db(self.db_path)
            with connect(self.db_path) as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.executescript(
                    f"""
                    CREATE TABLE IF NOT EXISTS {PROFILE_DECISIONS_TABLE} (
                        trial_id                    INTEGER PRIMARY KEY,
                        scope                       TEXT NOT NULL
                            CHECK (scope='creator-personal'),
                        parameter                   TEXT NOT NULL
                            CHECK (parameter='chatter_chance'),
                        decision_contract_version   INTEGER NOT NULL
                            CHECK (decision_contract_version=1),
                        settlement_snapshot_json    TEXT NOT NULL,
                        settlement_snapshot_sha256  TEXT NOT NULL,
                        decision                    TEXT NOT NULL CHECK (
                            decision IN ('retain_trial_value','revert_to_baseline')
                        ),
                        preimage_value              REAL NOT NULL,
                        trial_value                 REAL NOT NULL,
                        applied_value               REAL NOT NULL,
                        principal                   TEXT NOT NULL CHECK (principal='creator'),
                        authorization_mechanism     TEXT NOT NULL,
                        authorization_issued_at     REAL,
                        authorization_expires_at    REAL,
                        decided_at                  REAL NOT NULL,
                        decision_seal               TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS behavior_trial_profile_decisions_time_idx
                    ON {PROFILE_DECISIONS_TABLE}(decided_at DESC, trial_id DESC);

                    CREATE TABLE IF NOT EXISTS {ACTIVE_PROFILE_TABLE} (
                        parameter       TEXT PRIMARY KEY CHECK (parameter='chatter_chance'),
                        value           REAL NOT NULL,
                        source_trial_id INTEGER NOT NULL UNIQUE,
                        updated_at      REAL NOT NULL,
                        profile_seal    TEXT NOT NULL,
                        FOREIGN KEY(source_trial_id)
                            REFERENCES {PROFILE_DECISIONS_TABLE}(trial_id)
                            ON DELETE RESTRICT
                    );
                    """
                )
            self._schema_ready = True

    def _seal(self, domain: str, value: Mapping[str, Any]) -> str:
        material = _canonical_json(
            {"domain": domain, **dict(value)}, name="profile seal material"
        )
        return hmac.new(
            self._require_seal_key(),
            material.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _settlement_binding(self, trial_id: int) -> dict[str, Any]:
        try:
            binding = settlement_mod.get_settlement_binding(trial_id, self.db_path)
        except settlement_mod.BehaviorTrialSettlementError as exc:
            raise ProfileDecisionIntegrityError("frozen settlement is unavailable") from exc
        if binding is None:
            raise ProfileDecisionNotEligible("frozen settlement is unavailable")
        return _settlement_snapshot(binding)

    def _trial_values(
        self,
        conn: sqlite3.Connection,
        *,
        trial_id: int,
        spec_sha256: str,
    ) -> tuple[float, float, float]:
        row = conn.execute(
            "SELECT state, spec_json, created_at FROM experiment_trial_ledger WHERE id=?",
            (trial_id,),
        ).fetchone()
        if row is None or str(row["state"]) != "rolled_back":
            raise ProfileDecisionNotEligible("trial has not reached a rolled-back closure")
        raw_spec = str(row["spec_json"])
        if trial_ledger.spec_sha256_from_json(raw_spec) != spec_sha256:
            raise ProfileDecisionIntegrityError("trial specification changed")
        try:
            spec = json.loads(raw_spec)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ProfileDecisionIntegrityError("trial specification is invalid") from exc
        if not isinstance(spec, dict) or spec.get("parameter") != PROFILE_PARAMETER:
            raise ProfileDecisionIntegrityError("trial does not target chatter_chance")
        preimage = _probability(spec.get("old_value"), name="trial preimage")
        trial_value = _probability(spec.get("trial_value"), name="trial value")
        rollback = _probability(spec.get("rollback_value"), name="trial rollback")
        if rollback != preimage or trial_value == preimage:
            raise ProfileDecisionIntegrityError("trial value contract is invalid")
        return (
            preimage,
            trial_value,
            _timestamp(row["created_at"], name="trial created_at"),
        )

    def _record_from_row(
        self,
        row: sqlite3.Row,
        binding: Mapping[str, Any],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        snapshot = _settlement_snapshot(binding)
        snapshot_json = _canonical_json(snapshot, name="settlement snapshot")
        snapshot_sha256 = _digest(snapshot_json)
        trial_id = _positive_id(row["trial_id"], name="decision trial id")
        if trial_id != int(snapshot["trial_id"]):
            raise ProfileDecisionIntegrityError("decision trial does not match settlement")
        if str(row["scope"]) != CREATOR_PERSONAL_SCOPE:
            raise ProfileDecisionIntegrityError("decision scope is invalid")
        if str(row["parameter"]) != PROFILE_PARAMETER:
            raise ProfileDecisionIntegrityError("decision parameter is invalid")
        if int(row["decision_contract_version"]) != DECISION_CONTRACT_VERSION:
            raise ProfileDecisionIntegrityError("decision contract version is invalid")
        if str(row["settlement_snapshot_json"]) != snapshot_json:
            raise ProfileDecisionIntegrityError("decision settlement snapshot changed")
        if not hmac.compare_digest(
            str(row["settlement_snapshot_sha256"]), snapshot_sha256
        ):
            raise ProfileDecisionIntegrityError("decision settlement digest is invalid")
        decision = _decision(str(row["decision"]))
        preimage = _probability(row["preimage_value"], name="stored preimage")
        trial_value = _probability(row["trial_value"], name="stored trial value")
        applied = _probability(row["applied_value"], name="stored applied value")
        if applied != (trial_value if decision == RETAIN_TRIAL_VALUE else preimage):
            raise ProfileDecisionIntegrityError("stored applied profile value is invalid")
        if decision == RETAIN_TRIAL_VALUE and not (
            snapshot["status"] == "ready_for_creator_review"
            and snapshot["outcome"] == "improved"
            and snapshot["creator_retention_eligible"] is True
        ):
            raise ProfileDecisionIntegrityError("retained trial value lacks eligible evidence")
        principal = str(row["principal"])
        if principal != "creator":
            raise ProfileDecisionIntegrityError("decision principal is invalid")
        mechanism = _identifier(
            row["authorization_mechanism"], name="authorization mechanism"
        )
        issued_at = _optional_timestamp(
            row["authorization_issued_at"], name="authorization issued_at"
        )
        expires_at = _optional_timestamp(
            row["authorization_expires_at"], name="authorization expires_at"
        )
        decided_at = _timestamp(row["decided_at"], name="decided_at")
        if issued_at is not None and expires_at is not None and expires_at < issued_at:
            raise ProfileDecisionIntegrityError("authorization window is invalid")
        material = {
            "applied_value": applied,
            "authorization_expires_at": expires_at,
            "authorization_issued_at": issued_at,
            "authorization_mechanism": mechanism,
            "decision": decision,
            "decided_at": decided_at,
            "preimage_value": preimage,
            "principal": principal,
            "settlement_snapshot_sha256": snapshot_sha256,
            "trial_id": trial_id,
            "trial_value": trial_value,
        }
        expected_seal = self._seal(_DECISION_DOMAIN, material)
        if not hmac.compare_digest(expected_seal, str(row["decision_seal"])):
            raise ProfileDecisionIntegrityError("profile decision seal is invalid")
        if conn is not None:
            trial_preimage, stored_trial, _created_at = self._trial_values(
                conn, trial_id=trial_id, spec_sha256=str(snapshot["spec_sha256"])
            )
            if trial_preimage != preimage or stored_trial != trial_value:
                raise ProfileDecisionIntegrityError("decision values changed from trial")
        return {
            "trial_id": trial_id,
            "decision": decision,
            "preimage_value": preimage,
            "trial_value": trial_value,
            "applied_value": applied,
            "decided_at": decided_at,
            "settlement_status": str(snapshot["status"]),
            "outcome": str(snapshot["outcome"]),
            "creator_retention_eligible": bool(
                snapshot["creator_retention_eligible"]
            ),
        }

    def _active_profile_from_connection(
        self,
        conn: sqlite3.Connection,
        *,
        fallback: float,
    ) -> dict[str, Any]:
        profile = conn.execute(
            f"SELECT * FROM {ACTIVE_PROFILE_TABLE} WHERE parameter=?",
            (PROFILE_PARAMETER,),
        ).fetchone()
        if profile is None:
            retained_history = conn.execute(
                f"SELECT 1 FROM {PROFILE_DECISIONS_TABLE} LIMIT 1"
            ).fetchone()
            if retained_history is not None:
                raise ProfileDecisionIntegrityError(
                    "active profile row is missing despite retained decision history"
                )
            return {
                "parameter": PROFILE_PARAMETER,
                "value": fallback,
                "source_trial_id": None,
                "updated_at": None,
            }
        source_trial_id = _positive_id(
            profile["source_trial_id"], name="profile source trial id"
        )
        binding = self._settlement_binding(source_trial_id)
        decision_row = conn.execute(
            f"SELECT * FROM {PROFILE_DECISIONS_TABLE} WHERE trial_id=?",
            (source_trial_id,),
        ).fetchone()
        if decision_row is None:
            raise ProfileDecisionIntegrityError("active profile has no decision")
        decision = self._record_from_row(decision_row, binding, conn=conn)
        value = _probability(profile["value"], name="active profile value")
        updated_at = _timestamp(profile["updated_at"], name="profile updated_at")
        if value != decision["applied_value"] or updated_at != decision["decided_at"]:
            raise ProfileDecisionIntegrityError("active profile does not match decision")
        expected_profile_seal = self._seal(
            _PROFILE_DOMAIN,
            {
                "decision_seal": str(decision_row["decision_seal"]),
                "parameter": PROFILE_PARAMETER,
                "source_trial_id": source_trial_id,
                "updated_at": updated_at,
                "value": value,
            },
        )
        if not hmac.compare_digest(
            expected_profile_seal, str(profile["profile_seal"])
        ):
            raise ProfileDecisionIntegrityError("active profile seal is invalid")
        latest = conn.execute(
            f"SELECT trial_id, decided_at FROM {PROFILE_DECISIONS_TABLE} "
            "ORDER BY decided_at DESC, trial_id DESC LIMIT 1"
        ).fetchone()
        if latest is None:  # pragma: no cover - active row has a foreign key
            raise ProfileDecisionIntegrityError("active profile has no decision history")
        latest_trial_id = _positive_id(
            latest["trial_id"], name="latest profile decision trial id"
        )
        latest_decided_at = _timestamp(
            latest["decided_at"], name="latest profile decision decided_at"
        )
        if latest_trial_id != source_trial_id or latest_decided_at != updated_at:
            raise ProfileDecisionIntegrityError(
                "active profile is not the latest decision generation"
            )
        return {
            "parameter": PROFILE_PARAMETER,
            "value": value,
            "source_trial_id": source_trial_id,
            "updated_at": updated_at,
            "decision": decision["decision"],
        }

    def decide(
        self,
        trial_id: int,
        *,
        decision: str,
        expected_current_value: float,
        principal: str,
        authorization_mechanism: str,
        authorization_issued_at: float | int | None = None,
        authorization_expires_at: float | int | None = None,
        decided_at: float | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Commit one creator decision and resulting profile atomically."""
        trial_key = _positive_id(trial_id, name="trial id")
        requested_decision = _decision(decision)
        if principal != "creator":
            raise ProfileDecisionNotEligible("only the creator may decide a profile")
        current_value = _probability(
            expected_current_value, name="expected current profile value"
        )
        mechanism = _identifier(
            authorization_mechanism, name="authorization mechanism"
        )
        issued_at = _optional_timestamp(
            authorization_issued_at, name="authorization issued_at"
        )
        expires_at = _optional_timestamp(
            authorization_expires_at, name="authorization expires_at"
        )
        if issued_at is not None and expires_at is not None and expires_at < issued_at:
            raise ProfileDecisionNotEligible("authorization window is invalid")
        stamp = _timestamp(time.time() if decided_at is None else decided_at, name="decided_at")
        binding = self._settlement_binding(trial_key)
        snapshot_json = _canonical_json(binding, name="settlement snapshot")
        snapshot_sha256 = _digest(snapshot_json)
        self._ensure_schema()
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                f"SELECT * FROM {PROFILE_DECISIONS_TABLE} WHERE trial_id=?",
                (trial_key,),
            ).fetchone()
            if existing is not None:
                record = self._record_from_row(existing, binding, conn=conn)
                if record["decision"] != requested_decision:
                    raise ProfileDecisionNotEligible(
                        "trial already has a different creator profile decision"
                    )
                active = self._active_profile_from_connection(
                    conn,
                    fallback=current_value,
                )
                if (
                    active.get("source_trial_id") != trial_key
                    or float(active["value"]) != float(record["applied_value"])
                ):
                    raise ProfileDecisionNotEligible(
                        "profile decision has been superseded by a newer generation"
                    )
                if current_value != float(active["value"]):
                    raise ProfileDecisionNotEligible(
                        "current chatter profile does not match the stored decision"
                    )
                return record, False
            legacy_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='behavior_trial_review_decisions'"
            ).fetchone()
            legacy_baseline_receipt = False
            if legacy_table is not None:
                legacy_baseline_receipt = conn.execute(
                    "SELECT 1 FROM behavior_trial_review_decisions "
                    "WHERE trial_id=? AND decision='retain_baseline'",
                    (trial_key,),
                ).fetchone() is not None
            if legacy_baseline_receipt and requested_decision != REVERT_TO_BASELINE:
                raise ProfileDecisionNotEligible(
                    "legacy baseline-retention receipt forbids retaining the trial value"
                )
            preimage, trial_value, trial_created_at = self._trial_values(
                conn,
                trial_id=trial_key,
                spec_sha256=str(binding["spec_sha256"]),
            )
            active = self._active_profile_from_connection(
                conn,
                fallback=preimage,
            )
            observed_current = _probability(active["value"], name="active profile value")
            if observed_current != preimage or current_value != preimage:
                raise ProfileDecisionNotEligible(
                    "trial preimage is no longer the active chatter profile"
                )
            if (
                active["updated_at"] is not None
                and stamp <= float(active["updated_at"])
            ):
                raise ProfileDecisionNotEligible(
                    "profile decision timestamp must advance the active generation"
                )
            if (
                active["updated_at"] is not None
                and trial_created_at < float(active["updated_at"])
            ):
                raise ProfileDecisionNotEligible(
                    "trial predates the active chatter profile generation"
                )
            if requested_decision == RETAIN_TRIAL_VALUE and not (
                binding["status"] == "ready_for_creator_review"
                and binding["outcome"] == "improved"
                and binding["creator_retention_eligible"] is True
            ):
                raise ProfileDecisionNotEligible(
                    "frozen evidence is not eligible to retain the trial value"
                )
            applied = trial_value if requested_decision == RETAIN_TRIAL_VALUE else preimage
            material = {
                "applied_value": applied,
                "authorization_expires_at": expires_at,
                "authorization_issued_at": issued_at,
                "authorization_mechanism": mechanism,
                "decision": requested_decision,
                "decided_at": stamp,
                "preimage_value": preimage,
                "principal": "creator",
                "settlement_snapshot_sha256": snapshot_sha256,
                "trial_id": trial_key,
                "trial_value": trial_value,
            }
            decision_seal = self._seal(_DECISION_DOMAIN, material)
            conn.execute(
                f"""
                INSERT INTO {PROFILE_DECISIONS_TABLE}
                    (trial_id, scope, parameter, decision_contract_version,
                     settlement_snapshot_json, settlement_snapshot_sha256,
                     decision, preimage_value, trial_value, applied_value,
                     principal, authorization_mechanism,
                     authorization_issued_at, authorization_expires_at,
                     decided_at, decision_seal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trial_key,
                    CREATOR_PERSONAL_SCOPE,
                    PROFILE_PARAMETER,
                    DECISION_CONTRACT_VERSION,
                    snapshot_json,
                    snapshot_sha256,
                    requested_decision,
                    preimage,
                    trial_value,
                    applied,
                    "creator",
                    mechanism,
                    issued_at,
                    expires_at,
                    stamp,
                    decision_seal,
                ),
            )
            profile_material = {
                "decision_seal": decision_seal,
                "parameter": PROFILE_PARAMETER,
                "source_trial_id": trial_key,
                "updated_at": stamp,
                "value": applied,
            }
            profile_seal = self._seal(_PROFILE_DOMAIN, profile_material)
            conn.execute(
                f"""
                INSERT INTO {ACTIVE_PROFILE_TABLE}
                    (parameter, value, source_trial_id, updated_at, profile_seal)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(parameter) DO UPDATE SET
                    value=excluded.value,
                    source_trial_id=excluded.source_trial_id,
                    updated_at=excluded.updated_at,
                    profile_seal=excluded.profile_seal
                """,
                (PROFILE_PARAMETER, applied, trial_key, stamp, profile_seal),
            )
            stored = conn.execute(
                f"SELECT * FROM {PROFILE_DECISIONS_TABLE} WHERE trial_id=?",
                (trial_key,),
            ).fetchone()
            if stored is None:  # pragma: no cover - same transaction invariant
                raise BehaviorTrialProfileError("profile decision was not retrievable")
            return self._record_from_row(stored, binding, conn=conn), True

    def get(self, trial_id: int) -> dict[str, Any] | None:
        trial_key = _positive_id(trial_id, name="trial id")
        self._ensure_schema()
        database_uri = self.db_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(database_uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"SELECT * FROM {PROFILE_DECISIONS_TABLE} WHERE trial_id=?",
                (trial_key,),
            ).fetchone()
            if row is None:
                return None
            binding = self._settlement_binding(trial_key)
            return self._record_from_row(row, binding, conn=conn)

    def list(self, *, limit: int = 5) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
            raise BehaviorTrialProfileError("decision limit must be between 1 and 25")
        self._ensure_schema()
        database_uri = self.db_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(database_uri, uri=True) as conn:
            rows = conn.execute(
                f"SELECT trial_id FROM {PROFILE_DECISIONS_TABLE} "
                "ORDER BY decided_at DESC, trial_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        records = [self.get(int(row[0])) for row in rows]
        return [record for record in records if record is not None]

    def active_profile(self, fallback: float) -> dict[str, Any]:
        """Return a verified active value or an explicit untouched fallback."""
        default = _probability(fallback, name="fallback chatter profile")
        self._ensure_schema()
        database_uri = self.db_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(database_uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            return self._active_profile_from_connection(conn, fallback=default)


__all__ = [
    "ACTIVE_PROFILE_TABLE",
    "BehaviorTrialProfileError",
    "BehaviorTrialProfileStore",
    "CREATOR_PERSONAL_SCOPE",
    "PROFILE_DECISIONS_TABLE",
    "PROFILE_PARAMETER",
    "ProfileDecisionIntegrityError",
    "ProfileDecisionNotEligible",
    "ProfileDecisionSealUnavailable",
    "RETAIN_TRIAL_VALUE",
    "REVERT_TO_BASELINE",
]
