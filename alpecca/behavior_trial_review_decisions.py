"""Durable, creator-only acknowledgement of a frozen behavior-trial review.

This module records one fact only: after a C7 settlement, the restored baseline
remains in effect.  It never changes a behavior value, launches a new trial, or
turns review evidence into an automatic action.
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
from alpecca.db import connect
from config import DB_PATH


CREATOR_PERSONAL_SCOPE = "creator-personal"
DECISIONS_TABLE = "behavior_trial_review_decisions"
DECISION_CONTRACT_VERSION = 1
RETAIN_BASELINE = "retain_baseline"
_DECISION_SEAL_DOMAIN = "alpecca.behavior-trial.review-decision.v1"
_REVIEWABLE_STATUSES = frozenset({
    "ready_for_creator_review",
    "inconclusive_insufficient_samples",
})


class BehaviorTrialReviewDecisionError(ValueError):
    """A frozen review cannot be acknowledged safely."""


class ReviewDecisionNotEligible(BehaviorTrialReviewDecisionError):
    """There is no matching frozen review to acknowledge."""


class ReviewDecisionIntegrityError(BehaviorTrialReviewDecisionError):
    """A stored receipt no longer matches its sealed frozen-review binding."""


class ReviewDecisionSealUnavailable(BehaviorTrialReviewDecisionError):
    """The process has no protected key with which to verify decisions."""


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
        raise BehaviorTrialReviewDecisionError(f"{name} is not canonical JSON") from exc


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _positive_id(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BehaviorTrialReviewDecisionError(f"{name} must be a positive integer")
    return value


def _timestamp(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BehaviorTrialReviewDecisionError(f"{name} must be numeric")
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0.0:
        raise BehaviorTrialReviewDecisionError(f"{name} must be finite and non-negative")
    return stamp


def _optional_timestamp(value: object, *, name: str) -> float | None:
    if value is None:
        return None
    return _timestamp(value, name=name)


def _identifier(value: object, *, name: str, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise BehaviorTrialReviewDecisionError(f"{name} must be text")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum or any(ord(char) < 32 for char in cleaned):
        raise BehaviorTrialReviewDecisionError(f"{name} is invalid")
    return cleaned


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ReviewDecisionIntegrityError(f"{name} is invalid")
    if any(char not in "0123456789abcdef" for char in value):
        raise ReviewDecisionIntegrityError(f"{name} is invalid")
    return value


def _binding_snapshot(binding: Mapping[str, Any]) -> dict[str, Any]:
    trial_id = _positive_id(binding.get("trial_id"), name="settlement trial id")
    scope = _identifier(binding.get("scope"), name="settlement scope")
    if scope != CREATOR_PERSONAL_SCOPE:
        raise ReviewDecisionIntegrityError("settlement scope is invalid")
    status = _identifier(binding.get("status"), name="settlement status")
    if status not in _REVIEWABLE_STATUSES:
        raise ReviewDecisionNotEligible("settlement is not ready for creator acknowledgement")
    return {
        "contract_version": _positive_id(
            binding.get("contract_version"), name="settlement contract version"
        ),
        "trial_id": trial_id,
        "scope": scope,
        "parameter": _identifier(binding.get("parameter"), name="settlement parameter"),
        "metric": _identifier(binding.get("metric"), name="settlement metric"),
        "definition_version": _positive_id(
            binding.get("definition_version"), name="settlement definition version"
        ),
        "spec_sha256": _sha256(binding.get("spec_sha256"), name="settlement spec digest"),
        "settled_at": _timestamp(binding.get("settled_at"), name="settled_at"),
        "status": status,
        "recommendation": _identifier(
            binding.get("recommendation"), name="settlement recommendation"
        ),
        "evidence_sha256": _sha256(
            binding.get("evidence_sha256"), name="settlement evidence digest"
        ),
        "review_sha256": _sha256(
            binding.get("review_sha256"), name="settlement review digest"
        ),
    }


class BehaviorTrialReviewDecisionStore:
    """Persist exactly one sealed baseline-retention receipt per frozen trial."""

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

    def set_seal_key(self, seal_key: bytes | bytearray | memoryview | str | None) -> None:
        """Set the process-held decision seal key without persisting it."""
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
            raise ReviewDecisionSealUnavailable("review decision seal key is unavailable")
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
                    CREATE TABLE IF NOT EXISTS {DECISIONS_TABLE} (
                        trial_id                     INTEGER PRIMARY KEY,
                        scope                        TEXT NOT NULL
                            CHECK (scope='creator-personal'),
                        decision_contract_version    INTEGER NOT NULL
                            CHECK (decision_contract_version=1),
                        settlement_contract_version  INTEGER NOT NULL,
                        settlement_snapshot_json     TEXT NOT NULL,
                        settlement_snapshot_sha256   TEXT NOT NULL
                            CHECK (
                                length(settlement_snapshot_sha256)=64
                                AND settlement_snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
                            ),
                        settlement_spec_sha256       TEXT NOT NULL
                            CHECK (
                                length(settlement_spec_sha256)=64
                                AND settlement_spec_sha256 NOT GLOB '*[^0-9a-f]*'
                            ),
                        settlement_evidence_sha256   TEXT NOT NULL
                            CHECK (
                                length(settlement_evidence_sha256)=64
                                AND settlement_evidence_sha256 NOT GLOB '*[^0-9a-f]*'
                            ),
                        settlement_review_sha256     TEXT NOT NULL
                            CHECK (
                                length(settlement_review_sha256)=64
                                AND settlement_review_sha256 NOT GLOB '*[^0-9a-f]*'
                            ),
                        decision                     TEXT NOT NULL
                            CHECK (decision='retain_baseline'),
                        principal                    TEXT NOT NULL
                            CHECK (principal='creator'),
                        authorization_mechanism      TEXT NOT NULL,
                        authorization_issued_at      REAL,
                        authorization_expires_at     REAL,
                        decided_at                   REAL NOT NULL,
                        decision_seal                TEXT NOT NULL
                            CHECK (
                                length(decision_seal)=64
                                AND decision_seal NOT GLOB '*[^0-9a-f]*'
                            ),
                        FOREIGN KEY(trial_id) REFERENCES behavior_trial_settlements(trial_id)
                            ON DELETE RESTRICT
                    );

                    CREATE INDEX IF NOT EXISTS behavior_trial_review_decisions_time_idx
                    ON {DECISIONS_TABLE}(decided_at DESC, trial_id DESC);
                    """
                )
            self._schema_ready = True

    def _seal(self, value: Mapping[str, Any]) -> str:
        material = _canonical_json(
            {"domain": _DECISION_SEAL_DOMAIN, **dict(value)},
            name="review decision seal material",
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
            raise ReviewDecisionIntegrityError("frozen settlement is unavailable") from exc
        if binding is None:
            raise ReviewDecisionNotEligible("frozen settlement is unavailable")
        return _binding_snapshot(binding)

    def _record_from_row(
        self,
        row: sqlite3.Row,
        binding: Mapping[str, Any],
    ) -> dict[str, Any]:
        snapshot = _binding_snapshot(binding)
        snapshot_json = _canonical_json(snapshot, name="settlement snapshot")
        snapshot_sha256 = _digest(snapshot_json)
        trial_id = _positive_id(row["trial_id"], name="decision trial id")
        if trial_id != int(snapshot["trial_id"]):
            raise ReviewDecisionIntegrityError("decision trial does not match frozen settlement")
        if str(row["scope"]) != str(snapshot["scope"]):
            raise ReviewDecisionIntegrityError("decision scope does not match frozen settlement")
        if int(row["decision_contract_version"]) != DECISION_CONTRACT_VERSION:
            raise ReviewDecisionIntegrityError("decision contract version is invalid")
        if int(row["settlement_contract_version"]) != int(snapshot["contract_version"]):
            raise ReviewDecisionIntegrityError("decision settlement contract changed")
        if str(row["settlement_snapshot_json"]) != snapshot_json:
            raise ReviewDecisionIntegrityError("decision frozen settlement snapshot changed")
        if not hmac.compare_digest(
            str(row["settlement_snapshot_sha256"]), snapshot_sha256
        ):
            raise ReviewDecisionIntegrityError("decision frozen settlement digest is invalid")
        if str(row["settlement_spec_sha256"]) != str(snapshot["spec_sha256"]):
            raise ReviewDecisionIntegrityError("decision trial specification changed")
        if str(row["settlement_evidence_sha256"]) != str(snapshot["evidence_sha256"]):
            raise ReviewDecisionIntegrityError("decision frozen evidence changed")
        if str(row["settlement_review_sha256"]) != str(snapshot["review_sha256"]):
            raise ReviewDecisionIntegrityError("decision frozen review changed")
        if str(row["decision"]) != RETAIN_BASELINE:
            raise ReviewDecisionIntegrityError("decision type is invalid")
        if str(row["principal"]) != "creator":
            raise ReviewDecisionIntegrityError("decision principal is invalid")
        mechanism = _identifier(
            row["authorization_mechanism"], name="decision authorization mechanism"
        )
        issued_at = _optional_timestamp(
            row["authorization_issued_at"], name="decision authorization issued_at"
        )
        expires_at = _optional_timestamp(
            row["authorization_expires_at"], name="decision authorization expires_at"
        )
        if issued_at is not None and expires_at is not None and expires_at < issued_at:
            raise ReviewDecisionIntegrityError("decision authorization window is invalid")
        decided_at = _timestamp(row["decided_at"], name="decision decided_at")
        expected_seal = self._seal({
            "authorization_expires_at": expires_at,
            "authorization_issued_at": issued_at,
            "authorization_mechanism": mechanism,
            "decision": RETAIN_BASELINE,
            "decided_at": decided_at,
            "principal": "creator",
            "settlement_snapshot_sha256": snapshot_sha256,
            "trial_id": trial_id,
        })
        if not hmac.compare_digest(expected_seal, str(row["decision_seal"])):
            raise ReviewDecisionIntegrityError("decision seal is invalid")
        return {
            "trial_id": trial_id,
            "decision": RETAIN_BASELINE,
            "decided_at": decided_at,
            "settlement_status": str(snapshot["status"]),
        }

    def acknowledge(
        self,
        trial_id: int,
        *,
        principal: str,
        authorization_mechanism: str,
        authorization_issued_at: float | int | None = None,
        authorization_expires_at: float | int | None = None,
        decided_at: float | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Record one immutable creator acknowledgement with no behavior change."""
        trial_key = _positive_id(trial_id, name="trial id")
        if principal != "creator":
            raise ReviewDecisionNotEligible("only the creator may acknowledge a review")
        mechanism = _identifier(
            authorization_mechanism,
            name="authorization mechanism",
        )
        issued_at = _optional_timestamp(
            authorization_issued_at,
            name="authorization issued_at",
        )
        expires_at = _optional_timestamp(
            authorization_expires_at,
            name="authorization expires_at",
        )
        if issued_at is not None and expires_at is not None and expires_at < issued_at:
            raise ReviewDecisionNotEligible("authorization window is invalid")
        stamp = _timestamp(
            time.time() if decided_at is None else decided_at,
            name="decided_at",
        )
        binding = self._settlement_binding(trial_key)
        snapshot_json = _canonical_json(binding, name="settlement snapshot")
        snapshot_sha256 = _digest(snapshot_json)
        self._ensure_schema()
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                f"SELECT * FROM {DECISIONS_TABLE} WHERE trial_id=?",
                (trial_key,),
            ).fetchone()
            if existing is not None:
                return self._record_from_row(existing, binding), False
            seal = self._seal({
                "authorization_expires_at": expires_at,
                "authorization_issued_at": issued_at,
                "authorization_mechanism": mechanism,
                "decision": RETAIN_BASELINE,
                "decided_at": stamp,
                "principal": "creator",
                "settlement_snapshot_sha256": snapshot_sha256,
                "trial_id": trial_key,
            })
            conn.execute(
                f"""
                INSERT INTO {DECISIONS_TABLE}
                    (trial_id, scope, decision_contract_version,
                     settlement_contract_version, settlement_snapshot_json,
                     settlement_snapshot_sha256, settlement_spec_sha256,
                     settlement_evidence_sha256, settlement_review_sha256,
                     decision, principal, authorization_mechanism,
                     authorization_issued_at, authorization_expires_at,
                     decided_at, decision_seal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trial_key,
                    str(binding["scope"]),
                    DECISION_CONTRACT_VERSION,
                    int(binding["contract_version"]),
                    snapshot_json,
                    snapshot_sha256,
                    str(binding["spec_sha256"]),
                    str(binding["evidence_sha256"]),
                    str(binding["review_sha256"]),
                    RETAIN_BASELINE,
                    "creator",
                    mechanism,
                    issued_at,
                    expires_at,
                    stamp,
                    seal,
                ),
            )
            stored = conn.execute(
                f"SELECT * FROM {DECISIONS_TABLE} WHERE trial_id=?",
                (trial_key,),
            ).fetchone()
            if stored is None:  # pragma: no cover - same-transaction invariant
                raise BehaviorTrialReviewDecisionError("decision was not retrievable")
            return self._record_from_row(stored, binding), True

    def get(self, trial_id: int) -> dict[str, Any] | None:
        """Read one sealed decision without changing review or runtime state."""
        trial_key = _positive_id(trial_id, name="trial id")
        self._ensure_schema()
        database_uri = self.db_path.resolve().as_uri() + "?mode=ro"
        try:
            with sqlite3.connect(database_uri, uri=True) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    f"SELECT * FROM {DECISIONS_TABLE} WHERE trial_id=?",
                    (trial_key,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            raise BehaviorTrialReviewDecisionError("decision storage is unavailable") from exc
        if row is None:
            return None
        return self._record_from_row(row, self._settlement_binding(trial_key))

    def list(self, *, limit: int = 5) -> list[dict[str, Any]]:
        """Return recent sealed decisions in newest-first order."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 25:
            raise BehaviorTrialReviewDecisionError("decision limit must be between 1 and 25")
        self._ensure_schema()
        database_uri = self.db_path.resolve().as_uri() + "?mode=ro"
        try:
            with sqlite3.connect(database_uri, uri=True) as conn:
                rows = conn.execute(
                    f"SELECT trial_id FROM {DECISIONS_TABLE} ORDER BY decided_at DESC, trial_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            raise BehaviorTrialReviewDecisionError("decision storage is unavailable") from exc
        return [self.get(int(row[0])) for row in rows]


__all__ = [
    "BehaviorTrialReviewDecisionError",
    "BehaviorTrialReviewDecisionStore",
    "CREATOR_PERSONAL_SCOPE",
    "DECISION_CONTRACT_VERSION",
    "DECISIONS_TABLE",
    "RETAIN_BASELINE",
    "ReviewDecisionIntegrityError",
    "ReviewDecisionNotEligible",
    "ReviewDecisionSealUnavailable",
]
