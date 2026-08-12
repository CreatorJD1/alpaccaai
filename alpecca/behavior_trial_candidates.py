"""Server-owned, immutable candidates for one bounded behavior trial profile.

Candidates are deliberately separate from the generic Workshop payload.  The
Workshop can display and move a proposal through its board, but it cannot set a
metric, baseline, preimage, duration, or trial value.  Those facts are snapped
from server-owned evidence when this module issues a candidate, HMAC sealed,
and later translated into a validated specification for registration only.
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
from dataclasses import asdict
from pathlib import Path
from typing import Any

from alpecca import cognition
from alpecca.behavior_trial_controller import (
    BehaviorTrialFeasibilityError,
    ChatterTrialPacing,
    assert_chatter_trial_feasible,
    current_chatter_trial_pacing,
)
from alpecca.db import connect
from alpecca.experiment_trials import (
    ALLOWED_PARAMETERS,
    ExposureWindow,
    ParameterChange,
    TrialSpecification,
    ValidatedTrialSpecification,
    validate_trial_spec,
)
from alpecca.qualified_response_ledger import METRIC_NAME, QualifiedResponseLedger
from config import DB_PATH


CREATOR_PERSONAL_SCOPE = "creator-personal"
CANDIDATES_TABLE = "behavior_trial_candidates"
CANDIDATE_KIND = "behavior_trial.chatter_chance.v2"
PROFILE_PARAMETER = "chatter_chance"
PROFILE_METRIC = METRIC_NAME
EXPOSURE_SECONDS = 2 * 60 * 60.0
MIN_SAMPLES = 5
LOW_RESPONSE_RATE = 0.5
LOW_RESPONSE_DELTA = 0.02
TRIAL_PROFILE_NOT_FEASIBLE_REASON = "trial_profile_not_feasible"

_CANDIDATE_SEAL_DOMAIN = "alpecca.behavior-trial-candidate.v1"
_REGISTRATION_SEAL_DOMAIN = "alpecca.behavior-trial-registration.v1"
_CANDIDATE_FIELDS = frozenset({
    "kind",
    "baseline_rate",
    "preimage_value",
    "trial_value",
    "exposure_seconds",
    "min_samples",
})
_WITHDRAWN_PROPOSAL_STATUSES = frozenset({"rejected", "superseded"})


class BehaviorTrialCandidateError(ValueError):
    """A candidate is absent, invalid, or cannot enter registration."""


class CandidateNotFound(BehaviorTrialCandidateError):
    """No server-issued behavior-trial candidate exists for the proposal."""


class CandidateIntegrityError(BehaviorTrialCandidateError):
    """A candidate or its source proposal no longer matches its sealed snapshot."""


class CandidateNotEligible(BehaviorTrialCandidateError):
    """The candidate is valid but not ready for the requested lifecycle step."""


class CandidateSealUnavailable(BehaviorTrialCandidateError):
    """The process has no protected key with which to verify candidates."""


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
        raise BehaviorTrialCandidateError(f"{name} is not canonical JSON") from exc


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _timestamp(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BehaviorTrialCandidateError(f"{name} must be numeric")
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0.0:
        raise BehaviorTrialCandidateError(f"{name} must be finite and non-negative")
    return stamp


def _number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BehaviorTrialCandidateError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise BehaviorTrialCandidateError(f"{name} must be finite")
    return result


def _positive_id(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BehaviorTrialCandidateError(f"{name} must be a positive integer")
    return value


def _count(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BehaviorTrialCandidateError(f"{name} must be a non-negative integer")
    return value


def _text(value: object, *, name: str, maximum: int = 240) -> str:
    if not isinstance(value, str):
        raise BehaviorTrialCandidateError(f"{name} must be text")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        raise BehaviorTrialCandidateError(f"{name} is invalid")
    return cleaned


def _candidate_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _CANDIDATE_FIELDS:
        raise CandidateIntegrityError("candidate payload shape is invalid")
    if value.get("kind") != CANDIDATE_KIND:
        raise CandidateIntegrityError("candidate profile is unsupported")
    baseline_rate = _number(value.get("baseline_rate"), name="baseline_rate")
    preimage_value = _number(value.get("preimage_value"), name="preimage_value")
    trial_value = _number(value.get("trial_value"), name="trial_value")
    exposure_seconds = _number(
        value.get("exposure_seconds"), name="exposure_seconds"
    )
    min_samples = _count(value.get("min_samples"), name="min_samples")
    if not 0.0 < baseline_rate <= 1.0:
        raise CandidateIntegrityError("candidate baseline is invalid")
    if exposure_seconds <= 0.0 or min_samples <= 0:
        raise CandidateIntegrityError("candidate exposure contract is invalid")
    return {
        "kind": CANDIDATE_KIND,
        "baseline_rate": baseline_rate,
        "preimage_value": preimage_value,
        "trial_value": trial_value,
        "exposure_seconds": exposure_seconds,
        "min_samples": min_samples,
    }


def _proposal_snapshot(proposal: Mapping[str, Any]) -> str:
    proposal_id = _positive_id(proposal.get("id"), name="proposal id")
    ts = _timestamp(proposal.get("ts"), name="proposal timestamp")
    snapshot = {
        "id": proposal_id,
        "ts": ts,
        "action": _text(proposal.get("action"), name="proposal action"),
        "reason": _text(proposal.get("reason"), name="proposal reason", maximum=800),
        "approval": _text(proposal.get("approval"), name="proposal approval", maximum=80),
        "risk": _text(proposal.get("risk"), name="proposal risk", maximum=80),
        "evidence": _text(proposal.get("evidence"), name="proposal evidence", maximum=1000),
    }
    return _digest(_canonical_json(snapshot, name="proposal snapshot"))


class BehaviorTrialCandidateStore:
    """Own the small C8 candidate ledger and its server-only seals."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        seal_key: bytes | bytearray | memoryview | str | None = None,
        chatter_trial_pacing: ChatterTrialPacing | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        if chatter_trial_pacing is not None and not isinstance(
            chatter_trial_pacing, ChatterTrialPacing
        ):
            raise TypeError("chatter_trial_pacing must be a ChatterTrialPacing")
        self.chatter_trial_pacing = (
            current_chatter_trial_pacing()
            if chatter_trial_pacing is None
            else chatter_trial_pacing
        )
        self._seal_key: bytes | None = None
        self._schema_lock = threading.Lock()
        self._schema_ready = False
        self.set_seal_key(seal_key)
        self._ensure_schema()

    def set_seal_key(self, seal_key: bytes | bytearray | memoryview | str | None) -> None:
        """Set the process-held key without persisting it to SQLite."""
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
            raise CandidateSealUnavailable("behavior trial candidate seal key is unavailable")
        return self._seal_key

    def _ensure_schema(self) -> None:
        with self._schema_lock:
            if self._schema_ready:
                return
            cognition.init_db(self.db_path)
            with connect(self.db_path) as conn:
                conn.executescript(
                    f"""
                    CREATE TABLE IF NOT EXISTS {CANDIDATES_TABLE} (
                        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                        proposal_id             INTEGER NOT NULL UNIQUE,
                        scope                   TEXT NOT NULL
                            CHECK (scope='creator-personal'),
                        candidate_json          TEXT NOT NULL,
                        proposal_snapshot_sha256 TEXT NOT NULL
                            CHECK (
                                length(proposal_snapshot_sha256)=64
                                AND proposal_snapshot_sha256 NOT GLOB '*[^0-9a-f]*'
                            ),
                        seal                    TEXT NOT NULL
                            CHECK (
                                length(seal)=64 AND seal NOT GLOB '*[^0-9a-f]*'
                            ),
                        state                   TEXT NOT NULL
                            CHECK (state IN ('issued','registered','withdrawn')),
                        created_at              REAL NOT NULL,
                        registered_trial_id     INTEGER UNIQUE,
                        registered_at           REAL,
                        registered_principal    TEXT,
                        registration_mechanism  TEXT,
                        registration_seal       TEXT
                            CHECK (
                                registration_seal IS NULL OR (
                                    length(registration_seal)=64
                                    AND registration_seal NOT GLOB '*[^0-9a-f]*'
                                )
                            )
                    );

                    CREATE INDEX IF NOT EXISTS behavior_trial_candidates_scope_state_idx
                    ON {CANDIDATES_TABLE}(scope, state, id DESC);
                    """
                )
            self._schema_ready = True

    def _seal(self, domain: str, value: Mapping[str, Any]) -> str:
        key = self._require_seal_key()
        material = _canonical_json(
            {"domain": domain, **dict(value)},
            name="candidate seal material",
        )
        return hmac.new(key, material.encode("utf-8"), hashlib.sha256).hexdigest()

    def _candidate_seal(
        self,
        *,
        proposal_id: int,
        scope: str,
        candidate_json: str,
        proposal_snapshot_sha256: str,
    ) -> str:
        return self._seal(
            _CANDIDATE_SEAL_DOMAIN,
            {
                "candidate_json": candidate_json,
                "proposal_id": proposal_id,
                "proposal_snapshot_sha256": proposal_snapshot_sha256,
                "scope": scope,
            },
        )

    def _registration_seal(
        self,
        *,
        candidate_seal: str,
        proposal_id: int,
        trial_id: int,
        scope: str,
        principal: str,
        mechanism: str,
        registered_at: float,
    ) -> str:
        return self._seal(
            _REGISTRATION_SEAL_DOMAIN,
            {
                "candidate_seal": candidate_seal,
                "mechanism": mechanism,
                "principal": principal,
                "proposal_id": proposal_id,
                "registered_at": registered_at,
                "scope": scope,
                "trial_id": trial_id,
            },
        )

    @staticmethod
    def _proposal_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def _row_record(
        self,
        row: sqlite3.Row,
        proposal: Mapping[str, Any],
        *,
        verify_registration: bool = True,
    ) -> dict[str, Any]:
        proposal_id = _positive_id(row["proposal_id"], name="candidate proposal id")
        scope = str(row["scope"])
        if scope != CREATOR_PERSONAL_SCOPE:
            raise CandidateIntegrityError("candidate scope is invalid")
        if _positive_id(proposal.get("id"), name="proposal id") != proposal_id:
            raise CandidateIntegrityError("candidate proposal no longer matches its source")
        candidate_json = str(row["candidate_json"])
        try:
            raw_candidate = json.loads(candidate_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CandidateIntegrityError("candidate JSON is invalid") from exc
        payload = _candidate_payload(raw_candidate)
        canonical_candidate = _canonical_json(payload, name="candidate payload")
        if candidate_json != canonical_candidate:
            raise CandidateIntegrityError("candidate JSON is not canonical")
        snapshot = _proposal_snapshot(proposal)
        if not hmac.compare_digest(snapshot, str(row["proposal_snapshot_sha256"])):
            raise CandidateIntegrityError("candidate proposal snapshot changed")
        expected_seal = self._candidate_seal(
            proposal_id=proposal_id,
            scope=scope,
            candidate_json=candidate_json,
            proposal_snapshot_sha256=snapshot,
        )
        if not hmac.compare_digest(expected_seal, str(row["seal"])):
            raise CandidateIntegrityError("candidate seal is invalid")
        state = str(row["state"])
        if state not in {"issued", "registered", "withdrawn"}:
            raise CandidateIntegrityError("candidate state is invalid")
        record: dict[str, Any] = {
            "id": int(row["id"]),
            "proposal_id": proposal_id,
            "scope": scope,
            "payload": payload,
            "state": state,
            "created_at": _timestamp(row["created_at"], name="candidate created_at"),
            "proposal_status": str(proposal.get("status") or ""),
        }
        if state == "registered":
            trial_id = _positive_id(row["registered_trial_id"], name="registered trial id")
            registered_at = _timestamp(row["registered_at"], name="registered_at")
            principal = _text(row["registered_principal"], name="registered principal", maximum=80)
            mechanism = _text(row["registration_mechanism"], name="registration mechanism", maximum=120)
            seal = str(row["registration_seal"] or "")
            if verify_registration:
                expected_registration_seal = self._registration_seal(
                    candidate_seal=str(row["seal"]),
                    proposal_id=proposal_id,
                    trial_id=trial_id,
                    scope=scope,
                    principal=principal,
                    mechanism=mechanism,
                    registered_at=registered_at,
                )
                if not hmac.compare_digest(expected_registration_seal, seal):
                    raise CandidateIntegrityError("candidate registration seal is invalid")
            record.update({
                "registered_trial_id": trial_id,
                "registered_at": registered_at,
                "registered_principal": principal,
                "registration_mechanism": mechanism,
            })
        return record

    @staticmethod
    def _draft_from_baseline(
        baseline: Mapping[str, Any],
        *,
        preimage_value: object,
    ) -> tuple[dict[str, Any] | None, str]:
        try:
            completed = _count(baseline.get("completed"), name="baseline completed")
            pending = _count(baseline.get("pending"), name="baseline pending")
            dispatching = _count(baseline.get("dispatching"), name="baseline dispatching")
            qualified = _count(
                baseline.get("qualified_responses"), name="baseline qualified responses"
            )
        except BehaviorTrialCandidateError:
            return None, "baseline_unavailable"
        rate_value = baseline.get("rate")
        if rate_value is None:
            return None, "baseline_unavailable"
        try:
            rate = _number(rate_value, name="baseline rate")
            old_value = _number(preimage_value, name="chatter preimage")
        except BehaviorTrialCandidateError:
            return None, "baseline_unavailable"
        if completed < MIN_SAMPLES or pending or dispatching:
            return None, "baseline_not_settled"
        if qualified <= 0 or not 0.0 < rate < LOW_RESPONSE_RATE:
            return None, "baseline_does_not_support_lowering"
        rule = ALLOWED_PARAMETERS[PROFILE_PARAMETER]
        trial_value = round(old_value - LOW_RESPONSE_DELTA, 10)
        if not rule.minimum <= old_value <= rule.maximum:
            return None, "preimage_out_of_bounds"
        if not rule.minimum <= trial_value <= rule.maximum:
            return None, "trial_value_out_of_bounds"
        if not 0.0 < old_value - trial_value <= rule.max_delta:
            return None, "trial_delta_out_of_bounds"
        return {
            "kind": CANDIDATE_KIND,
            "baseline_rate": rate,
            "preimage_value": old_value,
            "trial_value": trial_value,
            "exposure_seconds": EXPOSURE_SECONDS,
            "min_samples": MIN_SAMPLES,
        }, "ready"

    @staticmethod
    def _proposal_for_candidate(
        baseline: Mapping[str, Any],
        *,
        issued_at: float,
        committed_evidence: Mapping[str, Any] | None = None,
    ) -> cognition.ActionProposal:
        completed = _count(baseline.get("completed"), name="baseline completed")
        qualified = _count(
            baseline.get("qualified_responses"), name="baseline qualified responses"
        )
        rate = _number(baseline.get("rate"), name="baseline rate")
        provenance = ""
        if committed_evidence is not None:
            provenance = (
                f"; source={committed_evidence['source']}; "
                f"rows={committed_evidence['row_count']}; "
                f"resolved={committed_evidence['resolved_count']}; "
                f"evidence_sha256={committed_evidence['sha256']}"
            )
        return cognition.ActionProposal(
            action="Consider a bounded proactive chatter trial",
            reason=(
                "The settled creator response baseline shows limited engagement with "
                "proactive outreach. A small, reversible reduction can be evaluated."
            ),
            approval=cognition.APPROVAL_ASK_FIRST,
            risk="low",
            status="testing",
            evidence=(
                f"metric={PROFILE_METRIC}; qualified={qualified}; completed={completed}; "
                f"rate={rate:.4f}; profile={CANDIDATE_KIND}{provenance}"
            ),
            result=(
                "Creator may accept the plan, then separately register, approve, "
                "and start one time-bounded trial."
            ),
            payload={},
            ts=issued_at,
        ).clean()

    def _active_issued_candidate_in_transaction(
        self,
        conn: sqlite3.Connection,
    ) -> sqlite3.Row | None:
        rows = conn.execute(
            f"""
            SELECT candidate.*, proposal.id AS proposal_id_source, proposal.ts AS proposal_ts,
                   proposal.action AS proposal_action, proposal.reason AS proposal_reason,
                   proposal.approval AS proposal_approval, proposal.risk AS proposal_risk,
                   proposal.status AS proposal_status, proposal.evidence AS proposal_evidence,
                   proposal.result AS proposal_result, proposal.payload AS proposal_payload
            FROM {CANDIDATES_TABLE} AS candidate
            JOIN action_proposals AS proposal ON proposal.id=candidate.proposal_id
            WHERE candidate.scope=? AND candidate.state='issued'
            ORDER BY candidate.id DESC
            """,
            (CREATOR_PERSONAL_SCOPE,),
        ).fetchall()
        for joined in rows:
            proposal = {
                "id": int(joined["proposal_id_source"]),
                "ts": joined["proposal_ts"],
                "action": joined["proposal_action"],
                "reason": joined["proposal_reason"],
                "approval": joined["proposal_approval"],
                "risk": joined["proposal_risk"],
                "status": joined["proposal_status"],
                "evidence": joined["proposal_evidence"],
                "result": joined["proposal_result"],
                "payload": joined["proposal_payload"],
            }
            if str(proposal["status"] or "") in _WITHDRAWN_PROPOSAL_STATUSES:
                conn.execute(
                    f"UPDATE {CANDIDATES_TABLE} SET state='withdrawn' WHERE id=? AND state='issued'",
                    (int(joined["id"]),),
                )
                continue
            return joined
        return None

    def issue_from_baseline(
        self,
        baseline: Mapping[str, Any],
        *,
        preimage_value: object,
        issued_at: float | None = None,
    ) -> dict[str, Any]:
        """Create or reuse one server-owned low-response candidate.

        It creates a visible Workshop proposal and its sealed candidate snapshot
        in one transaction.  The caller receives no path that can provide a
        candidate payload directly.
        """
        return self._issue_from_baseline(
            baseline,
            preimage_value=preimage_value,
            issued_at=issued_at,
            committed_evidence=None,
        )

    def activate_from_committed_evidence(
        self,
        *,
        preimage_value: object,
        since: float | None = None,
        issued_at: float | None = None,
    ) -> dict[str, Any]:
        """Issue one review-only candidate from durable outcome rows.

        This model-free entrypoint intentionally accepts no baseline mapping.
        It reads the SQLite evidence authority itself and cannot approve,
        register, start, retain, or apply a trial.
        """
        committed = QualifiedResponseLedger(self.db_path).committed_baseline_evidence(
            since=since
        )
        baseline = committed["baseline"]
        result = self._issue_from_baseline(
            baseline,
            preimage_value=preimage_value,
            issued_at=issued_at,
            committed_evidence=committed,
        )
        return {
            **result,
            "activation": {
                "source": committed["source"],
                "row_count": committed["row_count"],
                "resolved_count": committed["resolved_count"],
                "evidence_sha256": committed["sha256"],
                "model_calls": 0,
                "authorizes_trial_start": False,
                "authorizes_source_edits": False,
            },
        }

    def _issue_from_baseline(
        self,
        baseline: Mapping[str, Any],
        *,
        preimage_value: object,
        issued_at: float | None,
        committed_evidence: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        self._ensure_schema()
        try:
            assert_chatter_trial_feasible(
                EXPOSURE_SECONDS,
                MIN_SAMPLES,
                pacing=self.chatter_trial_pacing,
            )
        except BehaviorTrialFeasibilityError:
            return {
                "issued": False,
                "reason": TRIAL_PROFILE_NOT_FEASIBLE_REASON,
            }
        payload, reason = self._draft_from_baseline(
            baseline,
            preimage_value=preimage_value,
        )
        if payload is None:
            return {"issued": False, "reason": reason}
        stamp = _timestamp(time.time() if issued_at is None else issued_at, name="issued_at")
        candidate_json = _canonical_json(payload, name="candidate payload")
        proposal = self._proposal_for_candidate(
            baseline,
            issued_at=stamp,
            committed_evidence=committed_evidence,
        )
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = self._active_issued_candidate_in_transaction(conn)
            if active is not None:
                joined = active
                existing_proposal = {
                    "id": int(joined["proposal_id_source"]),
                    "ts": joined["proposal_ts"],
                    "action": joined["proposal_action"],
                    "reason": joined["proposal_reason"],
                    "approval": joined["proposal_approval"],
                    "risk": joined["proposal_risk"],
                    "status": joined["proposal_status"],
                    "evidence": joined["proposal_evidence"],
                    "result": joined["proposal_result"],
                    "payload": joined["proposal_payload"],
                }
                record = self._row_record(joined, existing_proposal)
                return {
                    "issued": True,
                    "reused": True,
                    "proposal": existing_proposal,
                    "candidate": record,
                }
            cursor = conn.execute(
                """
                INSERT INTO action_proposals
                    (ts, action, reason, approval, risk, status, evidence, result, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
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
            proposal_id = int(cursor.lastrowid)
            source = {
                "id": proposal_id,
                "ts": proposal.ts,
                "action": proposal.action,
                "reason": proposal.reason,
                "approval": proposal.approval,
                "risk": proposal.risk,
                "status": proposal.status,
                "evidence": proposal.evidence,
                "result": proposal.result,
                "payload": proposal.payload,
            }
            snapshot = _proposal_snapshot(source)
            seal = self._candidate_seal(
                proposal_id=proposal_id,
                scope=CREATOR_PERSONAL_SCOPE,
                candidate_json=candidate_json,
                proposal_snapshot_sha256=snapshot,
            )
            cursor = conn.execute(
                f"""
                INSERT INTO {CANDIDATES_TABLE}
                    (proposal_id, scope, candidate_json, proposal_snapshot_sha256,
                     seal, state, created_at, registered_trial_id, registered_at,
                     registered_principal, registration_mechanism, registration_seal)
                VALUES (?, ?, ?, ?, ?, 'issued', ?, NULL, NULL, NULL, NULL, NULL)
                """,
                (
                    proposal_id,
                    CREATOR_PERSONAL_SCOPE,
                    candidate_json,
                    snapshot,
                    seal,
                    stamp,
                ),
            )
            row = conn.execute(
                f"SELECT * FROM {CANDIDATES_TABLE} WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
            if row is None:  # pragma: no cover - same-transaction invariant
                raise BehaviorTrialCandidateError("candidate was not retrievable")
            record = self._row_record(row, source)
        return {"issued": True, "reused": False, "proposal": source, "candidate": record}

    def _candidate_and_proposal(self, proposal_id: int) -> tuple[sqlite3.Row, dict[str, Any]]:
        self._ensure_schema()
        with connect(self.db_path) as conn:
            row = conn.execute(
                f"SELECT * FROM {CANDIDATES_TABLE} WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise CandidateNotFound("proposal has no server-issued behavior trial candidate")
            proposal_row = conn.execute(
                "SELECT * FROM action_proposals WHERE id=?",
                (proposal_id,),
            ).fetchone()
        if proposal_row is None:
            raise CandidateIntegrityError("candidate source proposal is unavailable")
        proposal = self._proposal_from_row(proposal_row)
        self._row_record(row, proposal)
        return row, proposal

    def registration_details(
        self,
        proposal_id: int,
        *,
        default_chatter_chance: object,
    ) -> dict[str, Any]:
        """Return a sealed candidate's exact validated spec for registration."""
        proposal_key = _positive_id(proposal_id, name="proposal id")
        row, proposal = self._candidate_and_proposal(proposal_key)
        record = self._row_record(row, proposal)
        state = str(record["state"])
        proposal_status = str(record["proposal_status"])
        if state == "withdrawn" or proposal_status in _WITHDRAWN_PROPOSAL_STATUSES:
            raise CandidateNotEligible("candidate proposal is no longer eligible")
        if state == "issued" and proposal_status != "accepted":
            raise CandidateNotEligible("candidate plan has not been accepted")
        payload = dict(record["payload"])
        preimage = _number(default_chatter_chance, name="current chatter default")
        if payload["preimage_value"] != preimage:
            raise CandidateNotEligible("candidate preimage no longer matches the chatter default")
        try:
            assert_chatter_trial_feasible(
                EXPOSURE_SECONDS,
                MIN_SAMPLES,
                pacing=self.chatter_trial_pacing,
            )
        except BehaviorTrialFeasibilityError as exc:
            raise CandidateNotEligible(
                "candidate trial profile is not feasible under current chatter pacing"
            ) from exc
        specification = validate_trial_spec(TrialSpecification(
            proposal_id=proposal_key,
            parameter=PROFILE_PARAMETER,
            hypothesis=(
                "A small reduction in proactive chatter may improve qualified creator "
                "responses from the sealed baseline."
            ),
            metric=PROFILE_METRIC,
            baseline=float(payload["baseline_rate"]),
            exposure=ExposureWindow(
                float(payload["exposure_seconds"]),
                int(payload["min_samples"]),
            ),
            change=ParameterChange(
                float(payload["preimage_value"]),
                float(payload["trial_value"]),
            ),
            rollback_value=float(payload["preimage_value"]),
        ))
        return {
            "candidate": record,
            "proposal": proposal,
            "spec": specification,
        }

    @staticmethod
    def matches_trial(record: Mapping[str, Any], spec: ValidatedTrialSpecification) -> bool:
        if not isinstance(record.get("spec"), Mapping):
            return False
        return (
            record.get("scope") == CREATOR_PERSONAL_SCOPE
            and record.get("proposal_id") == spec.proposal_id
            and dict(record["spec"]) == asdict(spec)
        )

    def mark_registered(
        self,
        proposal_id: int,
        *,
        trial_id: int,
        principal: str,
        mechanism: str,
        registered_at: float | None = None,
    ) -> bool:
        """Attach one creator-authenticated registration receipt idempotently."""
        proposal_key = _positive_id(proposal_id, name="proposal id")
        trial_key = _positive_id(trial_id, name="trial id")
        if principal != "creator":
            raise CandidateNotEligible("only the creator may register a behavior trial")
        clean_mechanism = _text(mechanism, name="registration mechanism", maximum=120)
        stamp = _timestamp(
            time.time() if registered_at is None else registered_at,
            name="registered_at",
        )
        self._ensure_schema()
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT * FROM {CANDIDATES_TABLE} WHERE proposal_id=?",
                (proposal_key,),
            ).fetchone()
            if row is None:
                raise CandidateNotFound("proposal has no server-issued behavior trial candidate")
            proposal_row = conn.execute(
                "SELECT * FROM action_proposals WHERE id=?",
                (proposal_key,),
            ).fetchone()
            if proposal_row is None:
                raise CandidateIntegrityError("candidate source proposal is unavailable")
            record = self._row_record(row, self._proposal_from_row(proposal_row))
            state = str(row["state"])
            if state == "registered":
                if int(row["registered_trial_id"]) != trial_key:
                    raise CandidateIntegrityError("candidate is already bound to another trial")
                return False
            if state != "issued":
                raise CandidateNotEligible("candidate is no longer eligible for registration")
            if str(record["proposal_status"]) != "accepted":
                raise CandidateNotEligible("candidate plan has not been accepted")
            registration_seal = self._registration_seal(
                candidate_seal=str(row["seal"]),
                proposal_id=proposal_key,
                trial_id=trial_key,
                scope=str(row["scope"]),
                principal="creator",
                mechanism=clean_mechanism,
                registered_at=stamp,
            )
            updated = conn.execute(
                f"""
                UPDATE {CANDIDATES_TABLE}
                SET state='registered', registered_trial_id=?, registered_at=?,
                    registered_principal=?, registration_mechanism=?, registration_seal=?
                WHERE proposal_id=? AND state='issued' AND registered_trial_id IS NULL
                """,
                (trial_key, stamp, "creator", clean_mechanism, registration_seal, proposal_key),
            )
            if updated.rowcount == 1:
                return True
            row = conn.execute(
                f"SELECT * FROM {CANDIDATES_TABLE} WHERE proposal_id=?",
                (proposal_key,),
            ).fetchone()
            if row is not None and str(row["state"]) == "registered" and int(row["registered_trial_id"]) == trial_key:
                return False
            raise CandidateIntegrityError("candidate registration lost its issued state")

    def public_status(self) -> dict[str, Any] | None:
        """Return one sanitized candidate summary for the creator-only status API."""
        self._ensure_schema()
        with connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM {CANDIDATES_TABLE} WHERE scope=? ORDER BY id DESC",
                (CREATOR_PERSONAL_SCOPE,),
            ).fetchall()
            for row in rows:
                proposal_row = conn.execute(
                    "SELECT * FROM action_proposals WHERE id=?",
                    (int(row["proposal_id"]),),
                ).fetchone()
                if proposal_row is None:
                    raise CandidateIntegrityError("candidate source proposal is unavailable")
                proposal = self._proposal_from_row(proposal_row)
                record = self._row_record(row, proposal)
                state = str(record["state"])
                proposal_status = str(record["proposal_status"])
                if state == "withdrawn" or proposal_status in _WITHDRAWN_PROPOSAL_STATUSES:
                    continue
                if state == "issued":
                    public_state = (
                        "ready_for_registration"
                        if proposal_status == "accepted"
                        else "pending_creator_plan"
                    )
                    return {
                        "proposal_id": int(record["proposal_id"]),
                        "state": public_state,
                    }
                return {
                    "proposal_id": int(record["proposal_id"]),
                    "state": "registered",
                    "registered_trial_id": int(record["registered_trial_id"]),
                }
        return None


__all__ = [
    "BehaviorTrialCandidateError",
    "BehaviorTrialCandidateStore",
    "CANDIDATE_KIND",
    "CANDIDATES_TABLE",
    "CandidateIntegrityError",
    "CandidateNotEligible",
    "CandidateNotFound",
    "CandidateSealUnavailable",
    "CREATOR_PERSONAL_SCOPE",
    "EXPOSURE_SECONDS",
    "LOW_RESPONSE_DELTA",
    "LOW_RESPONSE_RATE",
    "MIN_SAMPLES",
    "PROFILE_METRIC",
    "PROFILE_PARAMETER",
    "TRIAL_PROFILE_NOT_FEASIBLE_REASON",
]
