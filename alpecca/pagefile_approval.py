"""Durable, one-use approval ledger for Phase 7 pagefile proposals.

This module is intentionally inert. It validates and binds the exact
proposal-only plan emitted by :mod:`alpecca.system_pressure`, records explicit
CreatorJD approval, and consumes that approval once. It has no host probe,
command, elevation, pagefile mutation, execution, scheduler, or route surface.

Only opaque identifiers, SHA-256 plan/token digests, fixed state, and
timestamps are persisted. Raw request and approval tokens are returned once to
the caller and are never written to SQLite.

Principal authentication remains outside this inert boundary. A future caller
must pass an already-authenticated principal; this module accepts only the
exact code-owned ``CreatorJD`` value and cannot establish identity itself.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from . import system_pressure


REQUEST_SCHEMA = "alpecca.phase7.pagefile-approval-request.v1"
APPROVAL_SCHEMA = "alpecca.phase7.pagefile-approval.v1"
CONSUMPTION_SCHEMA = "alpecca.phase7.pagefile-approval-consumption.v1"
PLANNER_SCHEMA = "alpecca.phase7.pagefile-proposal.v1"

REQUIRED_PRINCIPAL = "CreatorJD"
PAGEFILE_STEP_MIB = 4096
PAGEFILE_ABSOLUTE_MAX_MIB = 55296
REQUEST_TTL_SECONDS = 10 * 60
APPROVAL_TTL_SECONDS = 5 * 60

_EXPECTED_FUTURE_REQUIREMENTS = (
    "documented_safe_8192_measurement",
    "fresh_live_pagefile_commit_disk_readback",
    "authenticated_one_use_creatorjd_approval",
    "uac_elevation",
    "separate_minimal_elevated_helper",
    "single_bounded_write",
    "post_write_readback",
)
_PLAN_KEYS = frozenset(
    {
        "schema",
        "operation",
        "execution_state",
        "current_maximum_mib",
        "proposed_maximum_mib",
        "increase_mib",
        "future_requirements",
    }
)
_PLAN_DOMAIN = b"alpecca.phase7.pagefile-plan.v1\x00"
_REQUEST_TOKEN_DOMAIN = b"alpecca.phase7.pagefile-request-token.v1\x00"
_APPROVAL_TOKEN_DOMAIN = b"alpecca.phase7.pagefile-approval-token.v1\x00"
_REQUEST_TOKEN_RE = re.compile(r"pfr1_[A-Za-z0-9_-]{43}\Z")
_APPROVAL_TOKEN_RE = re.compile(r"pfa1_[A-Za-z0-9_-]{43}\Z")
_TABLE = "phase7_pagefile_approvals"
_EXPECTED_COLUMNS = frozenset(
    {
        "request_id",
        "plan_digest",
        "request_token_digest",
        "created_at",
        "request_expires_at",
        "request_used_at",
        "principal",
        "approved",
        "approved_at",
        "approval_expires_at",
        "approval_token_digest",
        "consumed_at",
    }
)


class PagefileApprovalError(ValueError):
    """A request, approval, or durable ledger transition failed closed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require_planner_contract() -> None:
    if (
        system_pressure.PROPOSAL_SCHEMA != PLANNER_SCHEMA
        or system_pressure.PAGEFILE_STEP_MIB != PAGEFILE_STEP_MIB
        or system_pressure.PAGEFILE_ABSOLUTE_MAX_MIB
        != PAGEFILE_ABSOLUTE_MAX_MIB
        or system_pressure.BROKER_REQUIRED_CREATOR_PRINCIPAL
        != REQUIRED_PRINCIPAL
        or system_pressure.FUTURE_EXECUTION_REQUIREMENTS
        != _EXPECTED_FUTURE_REQUIREMENTS
    ):
        raise PagefileApprovalError("planner_contract_mismatch")


def _validated_plan(plan: object) -> dict[str, object]:
    _require_planner_contract()
    if type(plan) is not dict or frozenset(plan) != _PLAN_KEYS:
        raise PagefileApprovalError("plan_invalid")
    if (
        plan.get("schema") != PLANNER_SCHEMA
        or plan.get("operation") != "pagefile_maximum_increase"
        or plan.get("execution_state") != "proposal_only"
        or type(plan.get("future_requirements")) is not tuple
        or plan.get("future_requirements") != _EXPECTED_FUTURE_REQUIREMENTS
    ):
        raise PagefileApprovalError("plan_invalid")

    current = plan.get("current_maximum_mib")
    proposed = plan.get("proposed_maximum_mib")
    increase = plan.get("increase_mib")
    if (
        type(current) is not int
        or type(proposed) is not int
        or type(increase) is not int
        or current < 1
        or increase != PAGEFILE_STEP_MIB
        or proposed != current + PAGEFILE_STEP_MIB
    ):
        raise PagefileApprovalError("plan_invalid")
    if current > PAGEFILE_ABSOLUTE_MAX_MIB or proposed > PAGEFILE_ABSOLUTE_MAX_MIB:
        raise PagefileApprovalError("plan_cap_exceeded")

    return {
        "schema": PLANNER_SCHEMA,
        "operation": "pagefile_maximum_increase",
        "execution_state": "proposal_only",
        "current_maximum_mib": current,
        "proposed_maximum_mib": proposed,
        "increase_mib": increase,
        "future_requirements": list(_EXPECTED_FUTURE_REQUIREMENTS),
    }


def pagefile_plan_digest(plan: object) -> str:
    """Validate an exact planner result and return its canonical digest."""
    material = _validated_plan(plan)
    encoded = json.dumps(
        material,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(_PLAN_DOMAIN + encoded).hexdigest()


def _timestamp(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PagefileApprovalError("clock_invalid")
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0:
        raise PagefileApprovalError("clock_invalid")
    return int(stamp)


def _principal(value: object) -> str:
    if type(value) is not str or value != REQUIRED_PRINCIPAL:
        raise PagefileApprovalError("creatorjd_principal_required")
    return value


def _new_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def _token_digest(
    token: object,
    *,
    pattern: re.Pattern[str],
    domain: bytes,
    invalid_code: str,
) -> str:
    if type(token) is not str or pattern.fullmatch(token) is None:
        raise PagefileApprovalError(invalid_code)
    return hashlib.sha256(domain + token.encode("ascii")).hexdigest()


class PagefileApprovalLedger:
    """SQLite-backed pending -> approved -> consumed state machine."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        now: Callable[[], float] = time.time,
    ) -> None:
        if not callable(now):
            raise PagefileApprovalError("clock_invalid")
        self.db_path = str(db_path)
        self._now = now
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=10,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    request_id TEXT PRIMARY KEY,
                    plan_digest TEXT NOT NULL CHECK(length(plan_digest) = 64),
                    request_token_digest TEXT NOT NULL UNIQUE
                        CHECK(length(request_token_digest) = 64),
                    created_at INTEGER NOT NULL,
                    request_expires_at INTEGER NOT NULL,
                    request_used_at INTEGER,
                    principal TEXT,
                    approved INTEGER CHECK(approved IS NULL OR approved = 1),
                    approved_at INTEGER,
                    approval_expires_at INTEGER,
                    approval_token_digest TEXT UNIQUE
                        CHECK(approval_token_digest IS NULL
                            OR length(approval_token_digest) = 64),
                    consumed_at INTEGER,
                    CHECK(request_expires_at > created_at),
                    CHECK(
                        (approved IS NULL
                            AND request_used_at IS NULL
                            AND principal IS NULL
                            AND approved_at IS NULL
                            AND approval_expires_at IS NULL
                            AND approval_token_digest IS NULL
                            AND consumed_at IS NULL)
                        OR
                        (approved = 1
                            AND request_used_at IS NOT NULL
                            AND principal = '{REQUIRED_PRINCIPAL}'
                            AND approved_at IS NOT NULL
                            AND approval_expires_at > approved_at
                            AND approval_token_digest IS NOT NULL)
                    ),
                    CHECK(consumed_at IS NULL OR approved = 1)
                );
                CREATE INDEX IF NOT EXISTS idx_phase7_pagefile_plan_digest
                    ON {_TABLE}(plan_digest, consumed_at);
                """
            )
            columns = {
                str(row[1])
                for row in conn.execute(f"PRAGMA table_info({_TABLE})").fetchall()
            }
            if columns != _EXPECTED_COLUMNS:
                raise PagefileApprovalError("ledger_schema_invalid")
        finally:
            conn.close()

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.commit()
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
            finally:
                conn.close()

    def _now_timestamp(self) -> int:
        try:
            return _timestamp(self._now())
        except PagefileApprovalError:
            raise
        except Exception as exc:
            raise PagefileApprovalError("clock_invalid") from exc

    def create_request(self, plan: object) -> dict[str, object]:
        """Create one expiring request bound to an exact proposal digest."""
        plan_digest = pagefile_plan_digest(plan)
        now = self._now_timestamp()
        request_token = _new_token("pfr1_")
        request_token_digest = _token_digest(
            request_token,
            pattern=_REQUEST_TOKEN_RE,
            domain=_REQUEST_TOKEN_DOMAIN,
            invalid_code="request_invalid",
        )
        request_id = "pfrq_" + secrets.token_urlsafe(18)
        expires_at = now + REQUEST_TTL_SECONDS

        with self._write_transaction() as conn:
            prior = conn.execute(
                f"SELECT request_expires_at, approved, approval_expires_at, "
                f"consumed_at FROM {_TABLE} WHERE plan_digest = ?",
                (plan_digest,),
            ).fetchall()
            for row in prior:
                if row["consumed_at"] is not None:
                    raise PagefileApprovalError("plan_already_consumed")
                active_until = (
                    row["approval_expires_at"]
                    if row["approved"] == 1
                    else row["request_expires_at"]
                )
                if active_until is not None and now < int(active_until):
                    raise PagefileApprovalError("active_request_exists")
            try:
                conn.execute(
                    f"INSERT INTO {_TABLE} "
                    "(request_id, plan_digest, request_token_digest, created_at, "
                    "request_expires_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        request_id,
                        plan_digest,
                        request_token_digest,
                        now,
                        expires_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise PagefileApprovalError("ledger_conflict") from exc

        return {
            "schema": REQUEST_SCHEMA,
            "request_id": request_id,
            "request_token": request_token,
            "plan_digest": plan_digest,
            "state": "pending",
            "expires_at": expires_at,
            "approved": False,
        }

    def approve_request(
        self,
        request_token: object,
        plan: object,
        *,
        principal: object,
        approved: object,
    ) -> dict[str, object]:
        """Consume a pending request and issue one expiring approval token."""
        if approved is not True:
            raise PagefileApprovalError("explicit_approval_required")
        bounded_principal = _principal(principal)
        plan_digest = pagefile_plan_digest(plan)
        request_token_digest = _token_digest(
            request_token,
            pattern=_REQUEST_TOKEN_RE,
            domain=_REQUEST_TOKEN_DOMAIN,
            invalid_code="request_invalid",
        )
        now = self._now_timestamp()
        approval_token = _new_token("pfa1_")
        approval_token_digest = _token_digest(
            approval_token,
            pattern=_APPROVAL_TOKEN_RE,
            domain=_APPROVAL_TOKEN_DOMAIN,
            invalid_code="approval_invalid",
        )
        approval_expires_at = now + APPROVAL_TTL_SECONDS

        with self._write_transaction() as conn:
            row = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE request_token_digest = ?",
                (request_token_digest,),
            ).fetchone()
            if row is None:
                raise PagefileApprovalError("request_invalid")
            if row["request_used_at"] is not None or row["approved"] is not None:
                raise PagefileApprovalError("request_replayed")
            if now < int(row["created_at"]):
                raise PagefileApprovalError("clock_rollback")
            if now >= int(row["request_expires_at"]):
                raise PagefileApprovalError("request_expired")
            if row["plan_digest"] != plan_digest:
                raise PagefileApprovalError("plan_mismatch")
            try:
                changed = conn.execute(
                    f"UPDATE {_TABLE} SET request_used_at = ?, principal = ?, "
                    "approved = 1, approved_at = ?, approval_expires_at = ?, "
                    "approval_token_digest = ? WHERE request_id = ? "
                    "AND request_used_at IS NULL AND approved IS NULL",
                    (
                        now,
                        bounded_principal,
                        now,
                        approval_expires_at,
                        approval_token_digest,
                        row["request_id"],
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise PagefileApprovalError("ledger_conflict") from exc
            if changed.rowcount != 1:
                raise PagefileApprovalError("request_replayed")

        return {
            "schema": APPROVAL_SCHEMA,
            "request_id": str(row["request_id"]),
            "approval_token": approval_token,
            "plan_digest": plan_digest,
            "principal": bounded_principal,
            "state": "approved",
            "expires_at": approval_expires_at,
            "approved": True,
        }

    def consume_approval(
        self,
        approval_token: object,
        plan: object,
        *,
        principal: object,
    ) -> dict[str, object]:
        """Atomically consume one approval bound to the same exact plan."""
        bounded_principal = _principal(principal)
        plan_digest = pagefile_plan_digest(plan)
        approval_token_digest = _token_digest(
            approval_token,
            pattern=_APPROVAL_TOKEN_RE,
            domain=_APPROVAL_TOKEN_DOMAIN,
            invalid_code="approval_invalid",
        )
        now = self._now_timestamp()

        with self._write_transaction() as conn:
            row = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE approval_token_digest = ?",
                (approval_token_digest,),
            ).fetchone()
            if row is None:
                raise PagefileApprovalError("approval_invalid")
            if row["consumed_at"] is not None:
                raise PagefileApprovalError("approval_replayed")
            if row["approved"] != 1 or row["principal"] != bounded_principal:
                raise PagefileApprovalError("approval_invalid")
            if now < int(row["approved_at"]):
                raise PagefileApprovalError("clock_rollback")
            if now >= int(row["approval_expires_at"]):
                raise PagefileApprovalError("approval_expired")
            if row["plan_digest"] != plan_digest:
                raise PagefileApprovalError("plan_mismatch")
            changed = conn.execute(
                f"UPDATE {_TABLE} SET consumed_at = ? WHERE request_id = ? "
                "AND consumed_at IS NULL",
                (now, row["request_id"]),
            )
            if changed.rowcount != 1:
                raise PagefileApprovalError("approval_replayed")

        return {
            "schema": CONSUMPTION_SCHEMA,
            "request_id": str(row["request_id"]),
            "plan_digest": plan_digest,
            "principal": bounded_principal,
            "state": "consumed",
            "consumed_at": now,
            "approved": True,
        }


__all__ = [
    "APPROVAL_SCHEMA",
    "APPROVAL_TTL_SECONDS",
    "CONSUMPTION_SCHEMA",
    "PAGEFILE_ABSOLUTE_MAX_MIB",
    "PAGEFILE_STEP_MIB",
    "PagefileApprovalError",
    "PagefileApprovalLedger",
    "REQUEST_SCHEMA",
    "REQUEST_TTL_SECONDS",
    "REQUIRED_PRINCIPAL",
    "pagefile_plan_digest",
]
