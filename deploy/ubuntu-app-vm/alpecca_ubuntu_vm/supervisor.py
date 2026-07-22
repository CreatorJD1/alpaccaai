"""Fail-closed, single-leader policy state machine with no operational effects."""
from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime
from typing import Any, Sequence

from .common import (
    InputError,
    canonical_digest,
    format_rfc3339,
    load_json,
    parse_rfc3339,
    print_json,
    require_bool,
    require_exact_keys,
    require_int,
    require_object,
    require_string,
)


SCHEMA_VERSION = 1
MAX_LEASE_DURATION_SECONDS = 35
STATE_STATUSES = frozenset({"standby", "leader-ready", "fenced"})

LEASE_KEYS = {
    "schemaVersion",
    "leaseId",
    "holderNodeId",
    "fencingEpoch",
    "issuedAt",
    "expiresAt",
}
ACTIVE_LEASE_KEYS = LEASE_KEYS - {"schemaVersion"}
STATE_KEYS = {
    "schemaVersion",
    "status",
    "highestFencingEpoch",
    "activeLease",
    "lastEvaluatedAt",
    "vaultSnapshotId",
    "lastDecisionId",
}


def initial_supervisor_state() -> dict[str, Any]:
    """Return explicit first-boot state for a separately trusted state store."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "standby",
        "highestFencingEpoch": 0,
        "activeLease": None,
        "lastEvaluatedAt": None,
        "vaultSnapshotId": None,
        "lastDecisionId": None,
    }


def _normalize_lease(value: Any, field: str, *, active: bool = False) -> dict[str, Any]:
    lease = require_object(value, field)
    keys = ACTIVE_LEASE_KEYS if active else LEASE_KEYS
    require_exact_keys(lease, field, keys)
    if not active and require_int(lease["schemaVersion"], f"{field}.schemaVersion") != 1:
        raise InputError(f"{field}.schemaVersion must be 1")

    issued_at = parse_rfc3339(lease["issuedAt"], f"{field}.issuedAt")
    expires_at = parse_rfc3339(lease["expiresAt"], f"{field}.expiresAt")
    if expires_at <= issued_at:
        raise InputError(f"{field}.expiresAt must be after issuedAt")

    normalized = {
        "leaseId": require_string(lease["leaseId"], f"{field}.leaseId", identifier=True),
        "holderNodeId": require_string(
            lease["holderNodeId"], f"{field}.holderNodeId", identifier=True
        ),
        "fencingEpoch": require_int(
            lease["fencingEpoch"], f"{field}.fencingEpoch", minimum=1
        ),
        "issuedAt": format_rfc3339(issued_at),
        "expiresAt": format_rfc3339(expires_at),
    }
    if not active:
        normalized = {"schemaVersion": SCHEMA_VERSION, **normalized}
    return normalized


def _normalize_state(value: Any) -> dict[str, Any]:
    state = require_object(value, "state")
    require_exact_keys(state, "state", STATE_KEYS)
    if require_int(state["schemaVersion"], "state.schemaVersion") != SCHEMA_VERSION:
        raise InputError("state.schemaVersion must be 1")

    status = require_string(state["status"], "state.status")
    if status not in STATE_STATUSES:
        raise InputError("state.status is not recognized")
    highest_epoch = require_int(
        state["highestFencingEpoch"], "state.highestFencingEpoch"
    )

    active_lease = None
    if state["activeLease"] is not None:
        active_lease = _normalize_lease(state["activeLease"], "state.activeLease", active=True)
    if status == "leader-ready" and active_lease is None:
        raise InputError("leader-ready state requires an active lease")
    if status != "leader-ready" and active_lease is not None:
        raise InputError("only leader-ready state may retain an active lease")
    if active_lease is not None and active_lease["fencingEpoch"] != highest_epoch:
        raise InputError("active lease epoch must equal the highest fencing epoch")

    last_evaluated = None
    if state["lastEvaluatedAt"] is not None:
        last_evaluated = format_rfc3339(
            parse_rfc3339(state["lastEvaluatedAt"], "state.lastEvaluatedAt")
        )
    vault_snapshot_id = None
    if state["vaultSnapshotId"] is not None:
        vault_snapshot_id = require_string(
            state["vaultSnapshotId"], "state.vaultSnapshotId", identifier=True
        )
    last_decision_id = None
    if state["lastDecisionId"] is not None:
        last_decision_id = require_string(
            state["lastDecisionId"], "state.lastDecisionId", max_length=71
        )
    if status == "leader-ready" and vault_snapshot_id is None:
        raise InputError("leader-ready state requires a vault snapshot id")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "highestFencingEpoch": highest_epoch,
        "activeLease": active_lease,
        "lastEvaluatedAt": last_evaluated,
        "vaultSnapshotId": vault_snapshot_id,
        "lastDecisionId": last_decision_id,
    }


def _fenced_state(state: dict[str, Any], now: datetime | None) -> dict[str, Any]:
    next_state = copy.deepcopy(state)
    next_state["status"] = "fenced"
    next_state["activeLease"] = None
    if now is not None:
        previous = next_state.get("lastEvaluatedAt")
        if previous is None or parse_rfc3339(previous, "state.lastEvaluatedAt") <= now:
            next_state["lastEvaluatedAt"] = format_rfc3339(now)
    return next_state


def _result(
    *,
    decision: str,
    next_state: dict[str, Any],
    reasons: list[str],
    input_valid: bool = True,
    would_lead: bool = False,
    idempotent: bool = False,
    decision_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "dry-run",
        "inputValid": input_valid,
        "decision": decision,
        "wouldLead": would_lead,
        "idempotent": idempotent,
        "decisionId": decision_id,
        "reasons": reasons,
        "executable": False,
        "sideEffects": [],
        "nextState": next_state,
    }


def _invalid_result(message: str) -> dict[str, Any]:
    state = initial_supervisor_state()
    state["status"] = "fenced"
    return _result(
        decision="fenced",
        next_state=state,
        reasons=[f"invalid-input:{message}"],
        input_valid=False,
    )


def evaluate_supervisor(observation_value: Any) -> dict[str, Any]:
    """Evaluate a lease observation without starting or enabling any runtime."""
    try:
        observation = require_object(observation_value, "observation")
        require_exact_keys(
            observation,
            "observation",
            {
                "schemaVersion",
                "nodeId",
                "now",
                "stateIntegrityVerified",
                "authority",
                "vault",
                "lease",
                "state",
            },
        )
        if require_int(observation["schemaVersion"], "observation.schemaVersion") != 1:
            raise InputError("observation.schemaVersion must be 1")

        node_id = require_string(observation["nodeId"], "observation.nodeId", identifier=True)
        now = parse_rfc3339(observation["now"], "observation.now")
        state_integrity_verified = require_bool(
            observation["stateIntegrityVerified"], "observation.stateIntegrityVerified"
        )
        state = _normalize_state(observation["state"])

        authority = require_object(observation["authority"], "observation.authority")
        require_exact_keys(
            authority,
            "observation.authority",
            {"available", "linearizable", "grantAuthenticated", "primaryGraceElapsed"},
        )
        authority_available = require_bool(
            authority["available"], "observation.authority.available"
        )
        authority_linearizable = require_bool(
            authority["linearizable"], "observation.authority.linearizable"
        )
        grant_authenticated = require_bool(
            authority["grantAuthenticated"], "observation.authority.grantAuthenticated"
        )
        primary_grace_elapsed = require_bool(
            authority["primaryGraceElapsed"], "observation.authority.primaryGraceElapsed"
        )

        vault = require_object(observation["vault"], "observation.vault")
        require_exact_keys(
            vault,
            "observation.vault",
            {
                "ready",
                "latestSnapshotVerified",
                "restoreCompleted",
                "snapshotId",
                "snapshotFencingEpoch",
                "verifiedAt",
            },
        )
        vault_ready = require_bool(vault["ready"], "observation.vault.ready")
        latest_snapshot_verified = require_bool(
            vault["latestSnapshotVerified"],
            "observation.vault.latestSnapshotVerified",
        )
        restore_completed = require_bool(
            vault["restoreCompleted"], "observation.vault.restoreCompleted"
        )
        snapshot_epoch = require_int(
            vault["snapshotFencingEpoch"], "observation.vault.snapshotFencingEpoch"
        )
        snapshot_id = None
        if vault["snapshotId"] is not None:
            snapshot_id = require_string(
                vault["snapshotId"], "observation.vault.snapshotId", identifier=True
            )
        verified_at = None
        if vault["verifiedAt"] is not None:
            verified_at = parse_rfc3339(vault["verifiedAt"], "observation.vault.verifiedAt")

        lease = None
        lease_issued_at = None
        lease_expires_at = None
        if observation["lease"] is not None:
            lease = _normalize_lease(observation["lease"], "observation.lease")
            lease_issued_at = parse_rfc3339(lease["issuedAt"], "observation.lease.issuedAt")
            lease_expires_at = parse_rfc3339(
                lease["expiresAt"], "observation.lease.expiresAt"
            )
    except InputError as exc:
        return _invalid_result(str(exc))

    reasons: list[str] = []
    previous_evaluated_at = (
        parse_rfc3339(state["lastEvaluatedAt"], "state.lastEvaluatedAt")
        if state["lastEvaluatedAt"] is not None
        else None
    )
    if not state_integrity_verified:
        reasons.append("state-integrity-unverified")
    if previous_evaluated_at is not None and now < previous_evaluated_at:
        reasons.append("clock-rollback")
    if not authority_available:
        reasons.append("authority-unavailable")
    if not authority_linearizable:
        reasons.append("authority-not-linearizable")
    if not grant_authenticated:
        reasons.append("grant-unauthenticated")
    if not primary_grace_elapsed:
        reasons.append("primary-grace-not-elapsed")
    if not vault_ready:
        reasons.append("vault-not-ready")
    if not latest_snapshot_verified:
        reasons.append("latest-vault-snapshot-unverified")
    if not restore_completed:
        reasons.append("vault-restore-incomplete")
    if snapshot_id is None:
        reasons.append("vault-snapshot-id-missing")
    if verified_at is None:
        reasons.append("vault-verification-time-missing")
    elif verified_at > now:
        reasons.append("vault-verification-from-future")

    if lease is None:
        reasons.append("lease-missing")
    else:
        assert lease_issued_at is not None and lease_expires_at is not None
        duration = (lease_expires_at - lease_issued_at).total_seconds()
        if duration > MAX_LEASE_DURATION_SECONDS:
            reasons.append("lease-duration-exceeds-policy")
        if lease_issued_at > now:
            reasons.append("lease-not-yet-valid")
        if now >= lease_expires_at:
            reasons.append("lease-expired")
        if lease["holderNodeId"] != node_id:
            reasons.append("lease-held-by-different-node")
        if snapshot_epoch > lease["fencingEpoch"]:
            reasons.append("vault-snapshot-epoch-ahead-of-lease")

        active_lease = state["activeLease"]
        highest_epoch = state["highestFencingEpoch"]
        if active_lease is None:
            if lease["fencingEpoch"] <= highest_epoch:
                reasons.append("stale-fencing-epoch")
        elif lease["leaseId"] == active_lease["leaseId"]:
            if lease["fencingEpoch"] != active_lease["fencingEpoch"]:
                reason = (
                    "stale-fencing-epoch"
                    if lease["fencingEpoch"] < active_lease["fencingEpoch"]
                    else "lease-id-epoch-conflict"
                )
                reasons.append(reason)
            active_issued_at = parse_rfc3339(
                active_lease["issuedAt"], "state.activeLease.issuedAt"
            )
            active_expires_at = parse_rfc3339(
                active_lease["expiresAt"], "state.activeLease.expiresAt"
            )
            if lease_issued_at < active_issued_at:
                reasons.append("lease-issued-at-regression")
            if lease_expires_at < active_expires_at:
                reasons.append("lease-expiry-regression")
        elif lease["fencingEpoch"] <= highest_epoch:
            reasons.append("stale-fencing-epoch")

    if reasons:
        return _result(
            decision="fenced",
            next_state=_fenced_state(state, now),
            reasons=reasons,
        )

    assert lease is not None and snapshot_id is not None
    normalized_active_lease = {key: lease[key] for key in ACTIVE_LEASE_KEYS}
    decision_id = canonical_digest(
        {
            "kind": "leader-ready",
            "nodeId": node_id,
            "lease": normalized_active_lease,
            "vaultSnapshotId": snapshot_id,
        }
    )
    idempotent = (
        state["status"] == "leader-ready"
        and state["activeLease"] == normalized_active_lease
        and state["vaultSnapshotId"] == snapshot_id
        and state["lastDecisionId"] == decision_id
    )
    next_state = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "leader-ready",
        "highestFencingEpoch": lease["fencingEpoch"],
        "activeLease": normalized_active_lease,
        "lastEvaluatedAt": format_rfc3339(now),
        "vaultSnapshotId": snapshot_id,
        "lastDecisionId": decision_id,
    }
    return _result(
        decision="leader-ready",
        next_state=next_state,
        reasons=[],
        would_lead=True,
        idempotent=idempotent,
        decision_id=decision_id,
    )


def validate_fencing_epoch(check_value: Any) -> dict[str, Any]:
    """Check a side-effect fence against exact lease id, epoch, and expiry."""
    try:
        check = require_object(check_value, "fenceCheck")
        require_exact_keys(
            check,
            "fenceCheck",
            {
                "schemaVersion",
                "now",
                "stateIntegrityVerified",
                "state",
                "leaseId",
                "fencingEpoch",
            },
        )
        if require_int(check["schemaVersion"], "fenceCheck.schemaVersion") != 1:
            raise InputError("fenceCheck.schemaVersion must be 1")
        now = parse_rfc3339(check["now"], "fenceCheck.now")
        integrity_verified = require_bool(
            check["stateIntegrityVerified"], "fenceCheck.stateIntegrityVerified"
        )
        state = _normalize_state(check["state"])
        lease_id = require_string(check["leaseId"], "fenceCheck.leaseId", identifier=True)
        epoch = require_int(check["fencingEpoch"], "fenceCheck.fencingEpoch", minimum=1)
    except InputError as exc:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "mode": "dry-run",
            "inputValid": False,
            "decision": "deny-fence",
            "wouldAllowSideEffect": False,
            "reasons": [f"invalid-input:{exc}"],
            "executable": False,
            "sideEffects": [],
        }

    reasons: list[str] = []
    if not integrity_verified:
        reasons.append("state-integrity-unverified")
    if state["status"] != "leader-ready" or state["activeLease"] is None:
        reasons.append("runtime-not-leader-ready")
    if state["vaultSnapshotId"] is None:
        reasons.append("vault-not-ready")
    if state["lastEvaluatedAt"] is not None:
        last_evaluated = parse_rfc3339(state["lastEvaluatedAt"], "state.lastEvaluatedAt")
        if now < last_evaluated:
            reasons.append("clock-rollback")

    active_lease = state["activeLease"]
    if active_lease is not None:
        expires_at = parse_rfc3339(active_lease["expiresAt"], "state.activeLease.expiresAt")
        if now >= expires_at:
            reasons.append("lease-expired")
        if lease_id != active_lease["leaseId"]:
            reasons.append("lease-id-mismatch")
        if epoch < state["highestFencingEpoch"]:
            reasons.append("stale-fencing-epoch")
        elif epoch > state["highestFencingEpoch"]:
            reasons.append("unknown-fencing-epoch")
        elif epoch != active_lease["fencingEpoch"]:
            reasons.append("lease-epoch-mismatch")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "dry-run",
        "inputValid": True,
        "decision": "deny-fence" if reasons else "allow-fence",
        "wouldAllowSideEffect": not reasons,
        "reasons": reasons,
        "executable": False,
        "sideEffects": [],
    }


def _cli_error(message: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "dry-run",
        "inputValid": False,
        "decision": "fenced",
        "wouldLead": False,
        "reasons": [f"input-read-failed:{message}"],
        "executable": False,
        "sideEffects": [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the inert Alpecca Ubuntu leader policy."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("evaluate", "validate-fence", "evaluate-continuity"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--dry-run", action="store_true", required=True)
        command_parser.add_argument("--input", required=True, help="JSON path or - for stdin")
    args = parser.parse_args(argv)

    try:
        payload = load_json(args.input)
    except (OSError, json.JSONDecodeError) as exc:
        print_json(_cli_error(type(exc).__name__))
        return 2

    if args.command == "evaluate":
        result = evaluate_supervisor(payload)
    elif args.command == "validate-fence":
        result = validate_fencing_epoch(payload)
    else:
        from .continuity_lease import evaluate_continuity_takeover

        result = evaluate_continuity_takeover(payload)
    print_json(result)
    if not result["inputValid"]:
        return 2
    if args.command == "evaluate":
        return 0 if result["wouldLead"] else 3
    if args.command == "validate-fence":
        return 0 if result["wouldAllowSideEffect"] else 3
    return 0 if result["wouldTakeContinuityOwnership"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
