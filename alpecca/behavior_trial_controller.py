"""Creator-owned runtime control for the first bounded behavior trial.

This is deliberately a narrow Phase 8B foundation.  It persists a single
runtime-only value in SQLite, but never writes configuration, source files, or
system state.  The existing trial ledger remains the durable record of the
specification, approval, timing, and rollback receipt; this controller adds the
atomic apply/readback/rollback boundary that the ledger intentionally does not
own.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
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
from alpecca.qualified_response_ledger import METRIC_NAME as QUALIFIED_RESPONSE_METRIC
from alpecca.trial_ledger import ProposalApprovalProof
from config import DB_PATH, Proactive


CREATOR_PERSONAL_SCOPE = "creator-personal"
CHATTER_CHANCE_PARAMETER = "chatter_chance"
CREATOR_APPROVAL_BINDINGS_TABLE = "behavior_trial_creator_approval_bindings"
INTERRUPTED_RECOVERY_REASON = "interrupted runtime-only behavior trial recovery"
TRIAL_EXPIRATION_REASON = "planned behavior trial exposure elapsed"
CREATOR_BINDING_VERIFICATION_FAILURE_REASON = (
    "creator approval binding could not be verified"
)

_MAX_IDENTIFIER_LENGTH = 160
_MAX_AUTHORIZATION_MECHANISM_LENGTH = 64
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_AUTHORIZATION_MECHANISM_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_SENSITIVE_AUTHORIZATION_TERMS = frozenset({
    "password",
    "token",
    "secret",
    "credential",
})


class BehaviorTrialControllerError(ValueError):
    """The controller cannot safely apply or restore a behavior value."""


class ForeignBehaviorTrialScope(BehaviorTrialControllerError):
    """The controller was asked to operate outside its creator-owned scope."""


class UnsupportedBehaviorTrial(BehaviorTrialControllerError):
    """The trial targets a behavior this foundation does not implement."""


class RuntimeOverrideError(BehaviorTrialControllerError):
    """Persisted runtime state does not prove the expected apply/restore value."""


class CreatorApprovalBindingError(
    BehaviorTrialControllerError, trial_ledger.ApprovalRequired
):
    """A runtime trial lacks a complete, exact creator approval binding."""


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


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise BehaviorTrialControllerError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise BehaviorTrialControllerError(f"{name} is required")
    if cleaned != value:
        raise BehaviorTrialControllerError(f"{name} must not have outer whitespace")
    if len(cleaned) > _MAX_IDENTIFIER_LENGTH:
        raise BehaviorTrialControllerError(
            f"{name} exceeds {_MAX_IDENTIFIER_LENGTH} characters"
        )
    if any(ord(char) < 32 for char in cleaned):
        raise BehaviorTrialControllerError(f"{name} contains control characters")
    return cleaned


def _authorization_mechanism(value: object) -> str:
    """Accept only a compact mechanism label, never credential material."""
    if not isinstance(value, str):
        raise BehaviorTrialControllerError(
            "authorization_mechanism must be a string"
        )
    cleaned = value.strip()
    if cleaned != value or not cleaned:
        raise BehaviorTrialControllerError(
            "authorization_mechanism must be a non-empty mechanism label"
        )
    if len(cleaned) > _MAX_AUTHORIZATION_MECHANISM_LENGTH:
        raise BehaviorTrialControllerError(
            "authorization_mechanism exceeds "
            f"{_MAX_AUTHORIZATION_MECHANISM_LENGTH} characters"
        )
    if _AUTHORIZATION_MECHANISM_RE.fullmatch(cleaned) is None:
        raise BehaviorTrialControllerError(
            "authorization_mechanism must use lowercase identifier characters"
        )
    if any(term in cleaned for term in _SENSITIVE_AUTHORIZATION_TERMS):
        raise BehaviorTrialControllerError(
            "authorization_mechanism must not contain credential material"
        )
    return cleaned


def _optional_timestamp(value: object, *, name: str) -> float | None:
    return None if value is None else _timestamp(value, name=name)


def _validate_authorization_window(
    *,
    approved_at: float,
    authorization_issued_at: float | None,
    authorization_expires_at: float | None,
) -> None:
    if (
        authorization_issued_at is not None
        and authorization_expires_at is not None
        and authorization_expires_at < authorization_issued_at
    ):
        raise BehaviorTrialControllerError(
            "authorization_expires_at cannot predate authorization_issued_at"
        )
    if (
        authorization_issued_at is not None
        and approved_at < authorization_issued_at
    ):
        raise BehaviorTrialControllerError(
            "approved_at cannot predate authorization_issued_at"
        )
    if (
        authorization_expires_at is not None
        and approved_at > authorization_expires_at
    ):
        raise BehaviorTrialControllerError(
            "approved_at cannot follow authorization_expires_at"
        )


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
        approval_seal_key: bytes | bytearray | memoryview | str | None = None,
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
        self._approval_seal_key: bytes | None = None
        self.set_approval_seal_key(approval_seal_key)
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

                    CREATE TABLE IF NOT EXISTS behavior_trial_creator_approval_bindings (
                        trial_id                   INTEGER PRIMARY KEY,
                        scope                      TEXT NOT NULL
                            CHECK (scope='creator-personal'),
                        proof_id                   TEXT NOT NULL,
                        spec_sha256                TEXT NOT NULL
                            CHECK (
                                length(spec_sha256)=64
                                AND spec_sha256 NOT GLOB '*[^0-9a-f]*'
                            ),
                        principal                  TEXT NOT NULL CHECK (principal='creator'),
                        authorization_mechanism    TEXT NOT NULL,
                        approved_at                REAL NOT NULL,
                        authorization_issued_at    REAL,
                        authorization_expires_at   REAL,
                        approval_seal              TEXT NOT NULL
                            CHECK (
                                length(approval_seal)=64
                                AND approval_seal NOT GLOB '*[^0-9a-f]*'
                            ),
                        FOREIGN KEY(trial_id) REFERENCES experiment_trial_ledger(id)
                            ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS behavior_trial_creator_approval_scope_idx
                        ON behavior_trial_creator_approval_bindings(scope, trial_id);
                    """
                )
                binding_columns = {
                    str(column[1])
                    for column in conn.execute(
                        f"PRAGMA table_info({CREATOR_APPROVAL_BINDINGS_TABLE})"
                    ).fetchall()
                }
                if "approval_seal" not in binding_columns:
                    # Existing bindings cannot be retroactively signed.  A nullable
                    # migration keeps their history intact while verification fails
                    # them closed until a new server-derived approval is written.
                    conn.execute(
                        "ALTER TABLE behavior_trial_creator_approval_bindings "
                        "ADD COLUMN approval_seal TEXT"
                    )
            self._schema_ready = True

    def _now(self) -> float:
        return _timestamp(self._clock(), name="clock timestamp")

    def set_approval_seal_key(
        self,
        approval_seal_key: bytes | bytearray | memoryview | str | None,
    ) -> None:
        """Set or clear the controller-local HMAC key without persisting it."""
        if approval_seal_key is None:
            self._approval_seal_key = None
            return
        if isinstance(approval_seal_key, str):
            key = approval_seal_key.encode("utf-8")
        elif isinstance(approval_seal_key, (bytes, bytearray, memoryview)):
            key = bytes(approval_seal_key)
        else:
            raise BehaviorTrialControllerError(
                "approval_seal_key must be text or bytes-like"
            )
        if not key:
            raise BehaviorTrialControllerError("approval_seal_key must not be empty")
        self._approval_seal_key = key

    def _require_approval_seal_key(self) -> bytes:
        key = self._approval_seal_key
        if key is None:
            raise CreatorApprovalBindingError(
                "creator approval binding requires a controller-held approval seal key"
            )
        return key

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
            return self._other_active_trial_exists_in_transaction(conn, trial_id)

    def _other_active_trial_exists_in_transaction(
        self, conn: sqlite3.Connection, trial_id: int
    ) -> bool:
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

    @staticmethod
    def _creator_proof_id(row: sqlite3.Row, spec_sha256: str) -> str:
        """Derive a retry-stable proof id from immutable stored trial identity."""
        identity_json = json.dumps(
            {
                "proposal_id": int(row["proposal_id"]),
                "scope": str(row["scope"]),
                "spec_sha256": spec_sha256,
                "trial_id": int(row["id"]),
            },
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return "creator-approval-" + hashlib.sha256(
            identity_json.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _approval_seal_payload(
        *,
        trial_id: int,
        scope: str,
        proposal_id: int,
        spec_sha256: str,
        proof_id: str,
        principal: str,
        authorization_mechanism: str,
        approved_at: float,
        authorization_issued_at: float | None,
        authorization_expires_at: float | None,
    ) -> bytes:
        """Canonical bytes for the exact facts a creator binding authorizes."""
        return json.dumps(
            {
                "approved_at": approved_at,
                "authorization_expires_at": authorization_expires_at,
                "authorization_issued_at": authorization_issued_at,
                "authorization_mechanism": authorization_mechanism,
                "id": trial_id,
                "principal": principal,
                "proof_id": proof_id,
                "proposal_id": proposal_id,
                "scope": scope,
                "spec_sha256": spec_sha256,
            },
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def _approval_seal_for_binding(
        self,
        *,
        row: sqlite3.Row,
        spec_sha256: str,
        proof_id: str,
        principal: str,
        authorization_mechanism: str,
        approved_at: float,
        authorization_issued_at: float | None,
        authorization_expires_at: float | None,
    ) -> str:
        return hmac.new(
            self._require_approval_seal_key(),
            self._approval_seal_payload(
                trial_id=int(row["id"]),
                scope=str(row["scope"]),
                proposal_id=int(row["proposal_id"]),
                spec_sha256=spec_sha256,
                proof_id=proof_id,
                principal=principal,
                authorization_mechanism=authorization_mechanism,
                approved_at=approved_at,
                authorization_issued_at=authorization_issued_at,
                authorization_expires_at=authorization_expires_at,
            ),
            hashlib.sha256,
        ).hexdigest()

    def _spec_sha256_from_row(self, row: sqlite3.Row) -> str:
        raw_spec_json = row["spec_json"]
        if not isinstance(raw_spec_json, str):
            raise CreatorApprovalBindingError("stored trial spec is not text")
        digest_helper = getattr(trial_ledger, "spec_sha256_from_json", None)
        if not callable(digest_helper):
            # Accept the pre-rename helper while other worktrees converge on
            # the documented ``spec_sha256_from_json`` name.
            digest_helper = getattr(trial_ledger, "spec_sha256", None)
        try:
            digest = (
                digest_helper(raw_spec_json)
                if callable(digest_helper)
                else hashlib.sha256(raw_spec_json.encode("utf-8")).hexdigest()
            )
        except (TypeError, ValueError) as exc:
            raise CreatorApprovalBindingError(
                "stored trial spec has no valid SHA-256"
            ) from exc
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise CreatorApprovalBindingError(
                "stored trial spec SHA-256 is not canonical lowercase hex"
            )
        return digest

    def _creator_binding(
        self, conn: sqlite3.Connection, trial_id: int
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT trial_id, scope, proof_id, spec_sha256, principal,
                   authorization_mechanism, approved_at,
                   authorization_issued_at, authorization_expires_at,
                   approval_seal
            FROM behavior_trial_creator_approval_bindings
            WHERE trial_id=?
            """,
            (trial_id,),
        ).fetchone()

    def _stored_approval_proof(self, row: sqlite3.Row) -> dict[str, Any] | None:
        proof = _json_object(row["approval_json"], name="approval proof")
        if proof is None:
            return None
        try:
            proof_id = _identifier(proof.get("proof_id"), name="stored proof_id")
            authority = _identifier(
                proof.get("authority"), name="stored approval authority"
            )
            approved_at = _timestamp(
                proof.get("approved_at"), name="stored approved_at"
            )
        except BehaviorTrialControllerError as exc:
            raise CreatorApprovalBindingError(
                "stored approval proof is incomplete"
            ) from exc
        if proof.get("scope") != self.scope:
            raise CreatorApprovalBindingError(
                "stored approval proof scope does not match the creator scope"
            )
        proposal_id = proof.get("proposal_id")
        if (
            isinstance(proposal_id, bool)
            or not isinstance(proposal_id, int)
            or proposal_id != int(row["proposal_id"])
        ):
            raise CreatorApprovalBindingError(
                "stored approval proof proposal does not match the trial"
            )
        if proof.get("decision") != trial_ledger.APPROVED:
            raise CreatorApprovalBindingError("stored approval proof is not approved")
        return {
            "proof_id": proof_id,
            "authority": authority,
            "approved_at": approved_at,
        }

    def _verify_creator_binding_in_transaction(
        self, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> dict[str, Any]:
        """Verify every persisted approval element before a runtime value is used."""
        trial_key = int(row["id"])
        binding = self._creator_binding(conn, trial_key)
        if binding is None:
            raise CreatorApprovalBindingError(
                "trial start requires a creator approval binding"
            )
        if (
            int(binding["trial_id"]) != trial_key
            or binding["scope"] != self.scope
            or row["scope"] != self.scope
        ):
            raise CreatorApprovalBindingError(
                "creator approval binding scope does not match the trial"
            )
        if binding["principal"] != "creator":
            raise CreatorApprovalBindingError(
                "creator approval binding principal is not creator"
            )
        try:
            binding_proof_id = _identifier(
                binding["proof_id"], name="stored creator binding proof_id"
            )
            mechanism = _authorization_mechanism(
                binding["authorization_mechanism"]
            )
            binding_approved_at = _timestamp(
                binding["approved_at"], name="stored creator binding approved_at"
            )
            authorization_issued_at = _optional_timestamp(
                binding["authorization_issued_at"],
                name="stored authorization_issued_at",
            )
            authorization_expires_at = _optional_timestamp(
                binding["authorization_expires_at"],
                name="stored authorization_expires_at",
            )
        except BehaviorTrialControllerError as exc:
            raise CreatorApprovalBindingError(
                "creator approval binding is incomplete"
            ) from exc
        raw_spec_sha256 = self._spec_sha256_from_row(row)
        stored_digest = binding["spec_sha256"]
        if (
            not isinstance(stored_digest, str)
            or _SHA256_RE.fullmatch(stored_digest) is None
            or stored_digest != raw_spec_sha256
        ):
            raise CreatorApprovalBindingError(
                "creator approval binding does not match the raw stored trial spec"
            )
        proof = self._stored_approval_proof(row)
        if proof is None:
            raise CreatorApprovalBindingError(
                "creator approval binding has no generic approval proof"
            )
        expected_proof_id = self._creator_proof_id(row, raw_spec_sha256)
        if (
            binding_proof_id != expected_proof_id
            or proof["proof_id"] != expected_proof_id
        ):
            raise CreatorApprovalBindingError(
                "creator approval binding proof id does not match the current raw stored trial spec"
            )
        if (
            binding_proof_id != proof["proof_id"]
            or binding_approved_at != proof["approved_at"]
            or mechanism != _authorization_mechanism(proof["authority"])
        ):
            raise CreatorApprovalBindingError(
                "creator approval binding does not match the generic approval proof"
            )
        try:
            _validate_authorization_window(
                approved_at=binding_approved_at,
                authorization_issued_at=authorization_issued_at,
                authorization_expires_at=authorization_expires_at,
            )
        except BehaviorTrialControllerError as exc:
            raise CreatorApprovalBindingError(
                "creator approval binding authorization timestamps are invalid"
            ) from exc
        approval_seal = binding["approval_seal"]
        if (
            not isinstance(approval_seal, str)
            or _SHA256_RE.fullmatch(approval_seal) is None
        ):
            raise CreatorApprovalBindingError(
                "creator approval binding approval seal is missing or malformed"
            )
        expected_seal = self._approval_seal_for_binding(
            row=row,
            spec_sha256=raw_spec_sha256,
            proof_id=binding_proof_id,
            principal="creator",
            authorization_mechanism=mechanism,
            approved_at=binding_approved_at,
            authorization_issued_at=authorization_issued_at,
            authorization_expires_at=authorization_expires_at,
        )
        if not hmac.compare_digest(approval_seal, expected_seal):
            raise CreatorApprovalBindingError(
                "creator approval binding approval seal does not verify"
            )
        return {
            "proof_id": binding_proof_id,
            "spec_sha256": raw_spec_sha256,
            "authorization_mechanism": mechanism,
            "approved_at": binding_approved_at,
            "authorization_issued_at": authorization_issued_at,
            "authorization_expires_at": authorization_expires_at,
        }

    @staticmethod
    def _creator_proof_json(proof: ProposalApprovalProof) -> str:
        """Mirror the generic ledger's canonical proof representation."""
        return json.dumps(
            {
                "proposal_id": proof.proposal_id,
                "scope": proof.scope,
                "proof_id": proof.proof_id,
                "authority": proof.authority,
                "approved_at": proof.approved_at,
                "decision": proof.decision,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def _approve_trial_in_transaction(
        self,
        conn: sqlite3.Connection,
        trial_id: int,
        proof: ProposalApprovalProof,
    ) -> None:
        """Use the ledger helper when present, with a current-ledger fallback."""
        approve_helper = getattr(trial_ledger, "approve_trial_in_transaction", None)
        if callable(approve_helper):
            approve_helper(conn, trial_id, proof, scope=self.scope)
            return

        row = self._row_in_scope(conn, trial_id)
        encoded = self._creator_proof_json(proof)
        if row["approval_json"] is not None:
            if str(row["approval_json"]) != encoded:
                raise trial_ledger.TrialStateError(
                    "trial already has different approval proof"
                )
            return
        if str(row["state"]) != trial_ledger.REGISTERED:
            raise trial_ledger.TrialStateError(
                f"cannot approve a {row['state']} trial"
            )
        updated = conn.execute(
            """
            UPDATE experiment_trial_ledger
            SET state='approved', approval_json=?, updated_at=?
            WHERE id=? AND scope=? AND state='registered'
            """,
            (encoded, proof.approved_at, trial_id, self.scope),
        )
        if updated.rowcount != 1:  # pragma: no cover - BEGIN IMMEDIATE fences races
            raise trial_ledger.TrialStateError("trial approval lost its registered state")

    def _replace_unbound_generic_approval_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        proof: ProposalApprovalProof,
    ) -> None:
        """Replace a pre-start generic approval with the server-derived proof."""
        trial_key = int(row["id"])
        updated = conn.execute(
            """
            UPDATE experiment_trial_ledger
            SET approval_json=?, updated_at=?
            WHERE id=? AND scope=? AND state='approved' AND started_at IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM behavior_trial_creator_approval_bindings
                  WHERE trial_id=?
              )
            """,
            (
                self._creator_proof_json(proof),
                proof.approved_at,
                trial_key,
                self.scope,
                trial_key,
            ),
        )
        if updated.rowcount != 1:  # pragma: no cover - BEGIN IMMEDIATE fences races
            raise trial_ledger.TrialStateError(
                "unbound generic approval could not be superseded"
            )

    def _write_creator_binding_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        authorization_mechanism: str,
        authorization_issued_at: float | None,
        authorization_expires_at: float | None,
    ) -> None:
        trial_key = int(row["id"])
        proof = self._stored_approval_proof(row)
        if proof is None:  # pragma: no cover - approval helper invariant
            raise CreatorApprovalBindingError(
                "creator approval binding has no generic approval proof"
            )
        if _authorization_mechanism(proof["authority"]) != authorization_mechanism:
            raise CreatorApprovalBindingError(
                "creator approval mechanism does not match the generic proof"
            )
        spec_sha256 = self._spec_sha256_from_row(row)
        if proof["proof_id"] != self._creator_proof_id(row, spec_sha256):
            raise CreatorApprovalBindingError(
                "creator approval proof id does not match the current raw stored trial spec"
            )
        _validate_authorization_window(
            approved_at=proof["approved_at"],
            authorization_issued_at=authorization_issued_at,
            authorization_expires_at=authorization_expires_at,
        )
        existing = self._creator_binding(conn, trial_key)
        if existing is None:
            approval_seal = self._approval_seal_for_binding(
                row=row,
                spec_sha256=spec_sha256,
                proof_id=proof["proof_id"],
                principal="creator",
                authorization_mechanism=authorization_mechanism,
                approved_at=proof["approved_at"],
                authorization_issued_at=authorization_issued_at,
                authorization_expires_at=authorization_expires_at,
            )
            conn.execute(
                """
                INSERT INTO behavior_trial_creator_approval_bindings
                    (trial_id, scope, proof_id, spec_sha256, principal,
                     authorization_mechanism, approved_at,
                     authorization_issued_at, authorization_expires_at,
                     approval_seal)
                VALUES (?, ?, ?, ?, 'creator', ?, ?, ?, ?, ?)
                """,
                (
                    trial_key,
                    self.scope,
                    proof["proof_id"],
                    spec_sha256,
                    authorization_mechanism,
                    proof["approved_at"],
                    authorization_issued_at,
                    authorization_expires_at,
                    approval_seal,
                ),
            )
            return

        verified = self._verify_creator_binding_in_transaction(conn, row)
        if (
            verified["proof_id"] != proof["proof_id"]
            or verified["spec_sha256"] != spec_sha256
            or verified["authorization_mechanism"] != authorization_mechanism
            or verified["approved_at"] != proof["approved_at"]
            or verified["authorization_issued_at"] != authorization_issued_at
            or verified["authorization_expires_at"] != authorization_expires_at
        ):
            raise trial_ledger.TrialStateError(
                "trial already has a different creator approval binding"
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

    def _runtime_override_for_trial(
        self, conn: sqlite3.Connection, trial_id: int
    ) -> sqlite3.Row | None:
        """Read a runtime row by owner without trusting its stored values."""
        return conn.execute(
            "SELECT * FROM behavior_trial_runtime_overrides WHERE trial_id=?",
            (trial_id,),
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

    def _remove_untrusted_override_and_read_default(
        self, conn: sqlite3.Connection, *, trial_id: int
    ) -> bool:
        """Restore the effective default without reading malformed override fields."""
        override_was_present = (
            self._runtime_override_for_trial(conn, trial_id) is not None
        )
        conn.execute(
            "DELETE FROM behavior_trial_runtime_overrides WHERE trial_id=?",
            (trial_id,),
        )
        # The table's unique constraint normally makes this second delete a
        # no-op.  If corruption bypassed it, fail closed rather than retain a
        # different effective chatter override.
        conn.execute(
            """
            DELETE FROM behavior_trial_runtime_overrides
            WHERE scope=? AND parameter=?
            """,
            (self.scope, CHATTER_CHANCE_PARAMETER),
        )
        if self._runtime_override(conn) is not None:
            raise RuntimeOverrideError(
                "untrusted override removal did not restore the chatter default"
            )
        if self._stored_chatter_chance(conn) != self.default_chatter_chance:
            raise RuntimeOverrideError("chatter chance did not read back to its default")
        return override_was_present

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

    @staticmethod
    def _binding_failure_evidence_json(
        trial_id: int, *, override_was_present: bool
    ) -> str:
        return json.dumps(
            {
                "creator_approval_binding": {"verified": False},
                "runtime_override": {
                    "parameter": CHATTER_CHANCE_PARAMETER,
                    "trial_id": trial_id,
                    "removed": True,
                    "was_present": override_was_present,
                },
            },
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _assert_verified_active_override(
        self, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> tuple[float, float]:
        self._verify_creator_binding_in_transaction(conn, row)
        record = self._record_from_row(row)
        self._require_supported_record(record)
        old_value, trial_value = self._assert_default_preimage(record)
        self._assert_override_matches(
            conn,
            trial_id=int(row["id"]),
            old_value=old_value,
            trial_value=trial_value,
        )
        return old_value, trial_value

    def _receipt_rollback_unverified_override_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        recorded_at: float,
    ) -> int:
        """Close an untrusted running/completed row without parsing its spec."""
        trial_key = int(row["id"])
        override_was_present = self._remove_untrusted_override_and_read_default(
            conn, trial_id=trial_key
        )
        conn.execute(
            """
            INSERT INTO experiment_trial_rollbacks
                (trial_id, recorded_at, expected_value, restored_value,
                 reason, evidence_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(trial_id) DO UPDATE SET
                recorded_at=excluded.recorded_at,
                expected_value=excluded.expected_value,
                restored_value=excluded.restored_value,
                reason=excluded.reason,
                evidence_json=excluded.evidence_json
            """,
            (
                trial_key,
                recorded_at,
                self.default_chatter_chance,
                self.default_chatter_chance,
                CREATOR_BINDING_VERIFICATION_FAILURE_REASON,
                self._binding_failure_evidence_json(
                    trial_key, override_was_present=override_was_present
                ),
            ),
        )
        updated = conn.execute(
            """
            UPDATE experiment_trial_ledger
            SET state='rolled_back', ended_at=?, updated_at=?
            WHERE id=? AND scope=? AND state IN ('running','completed')
            """,
            (recorded_at, recorded_at, trial_key, self.scope),
        )
        if updated.rowcount != 1:  # pragma: no cover - BEGIN IMMEDIATE fences races
            raise trial_ledger.TrialStateError(
                "unverified trial rollback lost its running state"
            )
        return trial_key

    def _closed_results(
        self, closed: list[tuple[int, str]]
    ) -> list[dict[str, Any]]:
        """Return normal ledger rows, with a safe fallback for corrupt specs."""
        results: list[dict[str, Any]] = []
        for trial_key, reason in closed:
            try:
                result = self.get(trial_key)
            except Exception:
                result = None
            if result is None:
                result = {
                    "id": trial_key,
                    "scope": self.scope,
                    "state": trial_ledger.ROLLED_BACK,
                    "rollback": {"reason": reason},
                }
            results.append(result)
        return results

    def _reconcile_running_row_in_transaction(
        self,
        conn: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        recorded_at: float,
    ) -> tuple[int, str] | None:
        """Close invalid running rows immediately and valid rows at planned end."""
        trial_key = int(row["id"])
        has_override = self._runtime_override_for_trial(conn, trial_key) is not None
        if has_override:
            try:
                self._assert_verified_active_override(conn, row)
                planned_end_at = _timestamp(
                    row["planned_end_at"], name="planned_end_at"
                )
            except Exception:
                self._receipt_rollback_unverified_override_in_transaction(
                    conn, row=row, recorded_at=recorded_at
                )
                return (trial_key, CREATOR_BINDING_VERIFICATION_FAILURE_REASON)
        else:
            try:
                record = self._record_from_row(row)
                self._require_supported_record(record)
            except UnsupportedBehaviorTrial:
                return None
            except Exception:
                self._receipt_rollback_unverified_override_in_transaction(
                    conn, row=row, recorded_at=recorded_at
                )
                return (trial_key, CREATOR_BINDING_VERIFICATION_FAILURE_REASON)
            try:
                self._verify_creator_binding_in_transaction(conn, row)
                self._assert_default_preimage(record)
                planned_end_at = _timestamp(
                    row["planned_end_at"], name="planned_end_at"
                )
            except Exception:
                self._receipt_rollback_unverified_override_in_transaction(
                    conn, row=row, recorded_at=recorded_at
                )
                return (trial_key, CREATOR_BINDING_VERIFICATION_FAILURE_REASON)

        if planned_end_at > recorded_at:
            return None
        try:
            self._rollback_in_transaction(
                conn,
                row=row,
                reason=TRIAL_EXPIRATION_REASON,
                recorded_at=recorded_at,
                require_override=has_override,
            )
        except Exception:
            self._receipt_rollback_unverified_override_in_transaction(
                conn, row=row, recorded_at=recorded_at
            )
            return (trial_key, CREATOR_BINDING_VERIFICATION_FAILURE_REASON)
        return (trial_key, TRIAL_EXPIRATION_REASON)

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
        """Attach one generic scope-bound approval proof for compatibility.

        Generic approval alone is intentionally insufficient to apply a runtime
        override.  New creator approvals must go through ``approve_creator``.
        """
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

    def approve_creator(
        self,
        trial_id: int,
        *,
        principal: str,
        authorization_mechanism: str,
        authorization_issued_at: float | None = None,
        authorization_expires_at: float | None = None,
        approved_at: float | None = None,
    ) -> dict[str, Any]:
        """Atomically attach server-derived creator approval to one stored trial.

        The caller supplies only server-derived authorization facts.  Trial
        identity, scope, proposal, exact raw-spec digest, and proof id are all
        read from the durable ledger inside this transaction.
        """
        self._ensure_schema()
        trial_key = _trial_id(trial_id)
        if principal != "creator":
            raise CreatorApprovalBindingError(
                "creator approval requires principal exactly 'creator'"
            )
        mechanism = _authorization_mechanism(authorization_mechanism)
        self._require_approval_seal_key()
        requested_issued_at = _optional_timestamp(
            authorization_issued_at, name="authorization_issued_at"
        )
        requested_expires_at = _optional_timestamp(
            authorization_expires_at, name="authorization_expires_at"
        )
        requested_approved_at = _optional_timestamp(approved_at, name="approved_at")

        with connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            row = self._row_in_scope(conn, trial_key)
            record = self._record_from_row(row)
            self._require_supported_record(record)
            existing_binding = self._creator_binding(conn, trial_key)
            if existing_binding is None:
                effective_issued_at = requested_issued_at
                effective_expires_at = requested_expires_at
            else:
                try:
                    existing_mechanism = _authorization_mechanism(
                        existing_binding["authorization_mechanism"]
                    )
                    existing_issued_at = _optional_timestamp(
                        existing_binding["authorization_issued_at"],
                        name="stored authorization_issued_at",
                    )
                    existing_expires_at = _optional_timestamp(
                        existing_binding["authorization_expires_at"],
                        name="stored authorization_expires_at",
                    )
                except BehaviorTrialControllerError as exc:
                    raise CreatorApprovalBindingError(
                        "stored creator approval binding is incomplete"
                    ) from exc
                if existing_mechanism != mechanism:
                    raise trial_ledger.TrialStateError(
                        "trial already has a different creator approval binding"
                    )
                if (
                    requested_issued_at is not None
                    and requested_issued_at != existing_issued_at
                ):
                    raise trial_ledger.TrialStateError(
                        "trial already has a different creator approval binding"
                    )
                if (
                    requested_expires_at is not None
                    and requested_expires_at != existing_expires_at
                ):
                    raise trial_ledger.TrialStateError(
                        "trial already has a different creator approval binding"
                    )
                effective_issued_at = existing_issued_at
                effective_expires_at = existing_expires_at

            state = str(row["state"])
            needs_server_proof = state == trial_ledger.REGISTERED or (
                state == trial_ledger.APPROVED and existing_binding is None
            )
            if needs_server_proof:
                if state == trial_ledger.REGISTERED:
                    if existing_binding is not None:
                        raise trial_ledger.TrialStateError(
                            "registered trial already has a creator approval binding"
                        )
                    if self._other_active_trial_exists_in_transaction(conn, trial_key):
                        raise trial_ledger.TrialStateError(
                            "another approved or running creator-personal behavior trial "
                            "is already active"
                        )
                elif row["started_at"] is not None:
                    raise trial_ledger.TrialStateError(
                        "cannot supersede a generic approval after a trial has started"
                    )
                proof_approved_at = (
                    self._now()
                    if requested_approved_at is None
                    else requested_approved_at
                )
                _validate_authorization_window(
                    approved_at=proof_approved_at,
                    authorization_issued_at=effective_issued_at,
                    authorization_expires_at=effective_expires_at,
                )
                proof = ProposalApprovalProof(
                    proposal_id=int(row["proposal_id"]),
                    scope=str(row["scope"]),
                    proof_id=self._creator_proof_id(
                        row, self._spec_sha256_from_row(row)
                    ),
                    authority=mechanism,
                    approved_at=proof_approved_at,
                )
                if state == trial_ledger.REGISTERED:
                    self._approve_trial_in_transaction(conn, trial_key, proof)
                else:
                    # A generic authority string is never trusted as a creator
                    # authorization.  Before start, replace it atomically with
                    # the server-derived canonical proof that this binding seals.
                    self._replace_unbound_generic_approval_in_transaction(
                        conn, row=row, proof=proof
                    )
                row = self._row_in_scope(conn, trial_key)
                stored_proof = self._stored_approval_proof(row)
                if stored_proof is None:  # pragma: no cover - helper invariant
                    raise CreatorApprovalBindingError(
                        "creator approval did not persist a generic proof"
                    )
            else:
                if state not in {trial_ledger.APPROVED, trial_ledger.RUNNING}:
                    raise trial_ledger.TrialStateError(
                        f"cannot bind a {state} trial approval"
                    )
                if existing_binding is None:
                    raise trial_ledger.TrialStateError(
                        "cannot attach a creator binding after a trial has started"
                    )
                stored_proof = self._stored_approval_proof(row)
                if stored_proof is None:
                    raise CreatorApprovalBindingError(
                        "creator approval binding has no generic approval proof"
                    )
                if (
                    requested_approved_at is not None
                    and requested_approved_at != stored_proof["approved_at"]
                ):
                    raise trial_ledger.TrialStateError(
                        "trial already has a different approval timestamp"
                    )

            if _authorization_mechanism(stored_proof["authority"]) != mechanism:
                raise trial_ledger.TrialStateError(
                    "creator approval mechanism does not match the generic proof"
                )
            _validate_authorization_window(
                approved_at=stored_proof["approved_at"],
                authorization_issued_at=effective_issued_at,
                authorization_expires_at=effective_expires_at,
            )
            self._write_creator_binding_in_transaction(
                conn,
                row=row,
                authorization_mechanism=mechanism,
                authorization_issued_at=effective_issued_at,
                authorization_expires_at=effective_expires_at,
            )
            self._verify_creator_binding_in_transaction(conn, row)

        result = self.get(trial_key)
        if result is None:  # pragma: no cover - same-database invariant
            raise BehaviorTrialControllerError("approved trial was not retrievable")
        return result

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
            state = str(row["state"])
            if state == trial_ledger.RUNNING:
                self._verify_creator_binding_in_transaction(conn, row)
                record = self._record_from_row(row)
                self._require_supported_record(record)
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
                self._verify_creator_binding_in_transaction(conn, row)
                record = self._record_from_row(row)
                self._require_supported_record(record)
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
        """Read a verified active override without mutating controller state.

        ``CoreMind`` may call this supplier while ``mind_lock`` is held.  Any
        expiry, integrity receipt, or override cleanup therefore belongs to
        ``maintain_runtime_state`` on the server's off-lock background path.
        A due or unverified record simply reads as the fixed default here.
        """
        self._ensure_schema()
        database_uri = self.db_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(database_uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT trial.*
                FROM behavior_trial_runtime_overrides AS runtime
                JOIN experiment_trial_ledger AS trial ON trial.id=runtime.trial_id
                WHERE runtime.scope=? AND runtime.parameter=?
                  AND trial.scope=? AND trial.state='running'
                """,
                (self.scope, CHATTER_CHANCE_PARAMETER, self.scope),
            ).fetchone()
            if row is None:
                return self.default_chatter_chance
            try:
                _old_value, chance = self._assert_verified_active_override(conn, row)
                planned_end_at = _timestamp(
                    row["planned_end_at"], name="planned_end_at"
                )
                if planned_end_at <= self._now():
                    return self.default_chatter_chance
                return chance
            except Exception:
                return self.default_chatter_chance

    def active_outcome_trial_id(
        self,
        *,
        dispatched_at: float | None = None,
    ) -> int | None:
        """Return a verified running trial id suitable for outcome attribution.

        This is intentionally read-only and fails closed.  A caller records the
        returned id alongside a server-owned delivery timestamp; a due, missing,
        malformed, or unverified override is never attributed to a trial.
        """
        stamp = self._now() if dispatched_at is None else _timestamp(
            dispatched_at, name="dispatched_at"
        )
        database_uri = self.db_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(database_uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT trial.*
                FROM behavior_trial_runtime_overrides AS runtime
                JOIN experiment_trial_ledger AS trial ON trial.id=runtime.trial_id
                WHERE runtime.scope=? AND runtime.parameter=?
                  AND trial.scope=? AND trial.state='running'
                """,
                (self.scope, CHATTER_CHANCE_PARAMETER, self.scope),
            ).fetchone()
            if row is None:
                return None
            try:
                self._assert_verified_active_override(conn, row)
                record = self._record_from_row(row)
                spec = record.get("spec")
                if (
                    not isinstance(spec, Mapping)
                    or spec.get("metric") != QUALIFIED_RESPONSE_METRIC
                ):
                    return None
                planned_end_at = _timestamp(
                    row["planned_end_at"], name="planned_end_at"
                )
                if planned_end_at <= stamp:
                    return None
                return int(row["id"])
            except Exception:
                return None

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
            closed = self._reconcile_running_row_in_transaction(
                conn, row=row, recorded_at=recorded_at
            )
            if closed is not None:
                expired_ids.append(closed[0])
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
        """Backward-compatible entry point for off-lock runtime maintenance."""
        return self.maintain_runtime_state()

    def maintain_runtime_state(self) -> list[dict[str, Any]]:
        """Reconcile unsafe or expired runtime overrides off the mind lock.

        This is the only maintenance writer used by the server's background
        loop.  It never starts or extends a trial.  Invalid records are closed
        with an integrity-failure receipt without trusting malformed spec or
        runtime values; valid running records close only at their planned end.
        """
        self._ensure_schema()
        stamp = self._now()
        closed: list[tuple[int, str]] = []
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
                trial_key = int(row["id"])
                state = str(row["state"])
                has_override = self._runtime_override_for_trial(conn, trial_key) is not None
                try:
                    record = self._record_from_row(row)
                    self._require_supported_record(record)
                except UnsupportedBehaviorTrial:
                    continue
                except Exception:
                    if has_override:
                        self._receipt_rollback_unverified_override_in_transaction(
                            conn, row=row, recorded_at=stamp
                        )
                        closed.append((trial_key, CREATOR_BINDING_VERIFICATION_FAILURE_REASON))
                    continue

                if state == trial_ledger.RUNNING:
                    result = self._reconcile_running_row_in_transaction(
                        conn, row=row, recorded_at=stamp
                    )
                    if result is not None:
                        closed.append(result)
                    continue

                # A completed ledger record should never retain an effective
                # override.  Close it only when one exists; without an override
                # it is already inert and remains historical evidence.
                if not has_override:
                    continue
                try:
                    self._assert_verified_active_override(conn, row)
                    self._rollback_in_transaction(
                        conn,
                        row=row,
                        reason=TRIAL_EXPIRATION_REASON,
                        recorded_at=stamp,
                        require_override=True,
                    )
                    closed.append((trial_key, TRIAL_EXPIRATION_REASON))
                except Exception:
                    self._receipt_rollback_unverified_override_in_transaction(
                        conn, row=row, recorded_at=stamp
                    )
                    closed.append((trial_key, CREATOR_BINDING_VERIFICATION_FAILURE_REASON))
        return self._closed_results(closed)

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
        recovered: list[tuple[int, str]] = []
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
                trial_key = int(row["id"])
                has_override = self._runtime_override_for_trial(conn, trial_key) is not None
                try:
                    record = self._record_from_row(row)
                    self._require_supported_record(record)
                except UnsupportedBehaviorTrial:
                    continue
                except Exception:
                    if has_override:
                        self._receipt_rollback_unverified_override_in_transaction(
                            conn, row=row, recorded_at=recovery_stamp
                        )
                        recovered.append(
                            (trial_key, CREATOR_BINDING_VERIFICATION_FAILURE_REASON)
                        )
                    continue

                try:
                    if has_override:
                        self._assert_verified_active_override(conn, row)
                    else:
                        self._verify_creator_binding_in_transaction(conn, row)
                        self._assert_default_preimage(record)
                    self._rollback_in_transaction(
                        conn,
                        row=row,
                        reason=INTERRUPTED_RECOVERY_REASON,
                        recorded_at=recovery_stamp,
                        require_override=False,
                    )
                    recovered.append((trial_key, INTERRUPTED_RECOVERY_REASON))
                except Exception:
                    self._receipt_rollback_unverified_override_in_transaction(
                        conn, row=row, recorded_at=recovery_stamp
                    )
                    recovered.append(
                        (trial_key, CREATOR_BINDING_VERIFICATION_FAILURE_REASON)
                    )

            # A terminal row with an override cannot arise from the controller's
            # atomic paths, but remove it rather than leave an effective value
            # behind after an interrupted/manual database operation.
            stale = self._runtime_override(conn)
            if stale is not None:
                stale_id = int(stale["trial_id"])
                stale_row = self._row_in_scope(conn, stale_id)
                if str(stale_row["state"]) in {
                    trial_ledger.RUNNING,
                    trial_ledger.COMPLETED,
                }:
                    raise RuntimeOverrideError(
                        "interrupted runtime override was not selected for recovery"
                    )
                self._remove_untrusted_override_and_read_default(
                    conn, trial_id=stale_id
                )
        return self._closed_results(recovered)

    def status_snapshot(self) -> dict[str, Any]:
        """Read one active trial and its runtime metadata without changing state."""
        database_uri = self.db_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(database_uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            snapshot_row = conn.execute(
                """
                SELECT
                    active.id AS active_trial_id,
                    active.scope AS active_scope,
                    active.proposal_id AS active_proposal_id,
                    active.state AS active_state,
                    active.spec_json AS active_spec_json,
                    active.started_at AS active_started_at,
                    active.planned_end_at AS active_planned_end_at,
                    active.creator_binding_trial_id,
                    runtime.trial_id AS runtime_trial_id,
                    runtime.scope AS runtime_scope,
                    runtime.parameter AS runtime_parameter,
                    runtime.preimage_value AS runtime_preimage_value,
                    runtime.override_value AS runtime_override_value,
                    runtime.applied_at AS runtime_applied_at
                FROM (SELECT 1) AS snapshot
                LEFT JOIN (
                    SELECT trial.id, trial.scope, trial.proposal_id, trial.state,
                           trial.spec_json, trial.started_at, trial.planned_end_at,
                           binding.trial_id AS creator_binding_trial_id
                    FROM experiment_trial_ledger AS trial
                    LEFT JOIN behavior_trial_creator_approval_bindings AS binding
                        ON binding.trial_id=trial.id
                    WHERE trial.scope=? AND trial.state IN ('approved','running')
                    ORDER BY CASE trial.state WHEN 'running' THEN 0 ELSE 1 END, trial.id
                    LIMIT 1
                ) AS active ON 1=1
                LEFT JOIN (
                    SELECT trial_id, scope, parameter, preimage_value, override_value,
                           applied_at
                    FROM behavior_trial_runtime_overrides
                    WHERE scope=? AND parameter=?
                    LIMIT 1
                ) AS runtime ON 1=1
                """,
                (self.scope, self.scope, CHATTER_CHANCE_PARAMETER),
            ).fetchone()

        active_trial: dict[str, Any] | None
        if snapshot_row is None or snapshot_row["active_trial_id"] is None:
            active_trial = None
        else:
            try:
                parsed_spec = json.loads(str(snapshot_row["active_spec_json"]))
            except (TypeError, ValueError):
                parsed_spec = None
            parameter = (
                parsed_spec.get("parameter")
                if isinstance(parsed_spec, Mapping)
                and isinstance(parsed_spec.get("parameter"), str)
                else None
            )
            active_trial = {
                "id": int(snapshot_row["active_trial_id"]),
                "scope": str(snapshot_row["active_scope"]),
                "proposal_id": int(snapshot_row["active_proposal_id"]),
                "state": str(snapshot_row["active_state"]),
                "parameter": parameter,
                "started_at": (
                    None
                    if snapshot_row["active_started_at"] is None
                    else float(snapshot_row["active_started_at"])
                ),
                "planned_end_at": (
                    None
                    if snapshot_row["active_planned_end_at"] is None
                    else float(snapshot_row["active_planned_end_at"])
                ),
                "creator_binding_present": (
                    snapshot_row["creator_binding_trial_id"] is not None
                ),
            }

        runtime_override: dict[str, Any] | None
        if snapshot_row is None or snapshot_row["runtime_trial_id"] is None:
            runtime_override = None
        else:
            runtime_override = {
                "trial_id": int(snapshot_row["runtime_trial_id"]),
                "scope": str(snapshot_row["runtime_scope"]),
                "parameter": str(snapshot_row["runtime_parameter"]),
                "preimage_value": float(snapshot_row["runtime_preimage_value"]),
                "override_value": float(snapshot_row["runtime_override_value"]),
                "applied_at": float(snapshot_row["runtime_applied_at"]),
            }
        return {
            "active_trial": active_trial,
            "runtime_override": runtime_override,
        }

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
    "CREATOR_APPROVAL_BINDINGS_TABLE",
    "CREATOR_BINDING_VERIFICATION_FAILURE_REASON",
    "CREATOR_PERSONAL_SCOPE",
    "CreatorApprovalBindingError",
    "ForeignBehaviorTrialScope",
    "INTERRUPTED_RECOVERY_REASON",
    "ProposalApprovalProof",
    "RuntimeOverrideError",
    "TRIAL_EXPIRATION_REASON",
    "UnsupportedBehaviorTrial",
]
