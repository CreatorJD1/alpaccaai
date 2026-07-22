"""Pure Phase 13 promotion transaction policy with no operational effects."""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from .common import (
    InputError,
    canonical_digest,
    format_rfc3339,
    parse_rfc3339,
    require_bool,
    require_digest,
    require_exact_keys,
    require_int,
    require_object,
    require_string,
    require_string_list,
)


SCHEMA_VERSION = 1
CREATOR_PRINCIPAL = "CreatorJD"
MAX_APPROVAL_SECONDS = 300
MAX_LEASE_SECONDS = 35
PHASES = frozenset(
    {
        "passive-standby",
        "restore-staged",
        "restore-verified",
        "lease-acquired",
        "desktop-standby-eligible",
        "coremind-promotion-eligible",
        "released",
    }
)
EVENT_TYPES = frozenset(
    {
        "stage-passive-restore",
        "verify-restored-snapshot",
        "acquire-continuity-lease",
        "qualify-desktop-standby",
        "qualify-coremind-promotion",
        "rollback-release",
    }
)
STATE_KEYS = {
    "schemaVersion",
    "nodeId",
    "phase",
    "highestFenceEpoch",
    "snapshot",
    "lease",
    "releasedLease",
    "lastEvaluatedAt",
    "usedApprovalIds",
    "processedEventIds",
    "lastReceiptId",
}
SNAPSHOT_KEYS = {
    "snapshotId",
    "digest",
    "sourceEpoch",
    "stagedAt",
    "verifiedAt",
}
LEASE_KEYS = {
    "leaseId",
    "holderNodeId",
    "epoch",
    "issuedAt",
    "expiresAt",
    "authorityGrantId",
}


def initial_promotion_state(
    node_id: str, *, highest_fence_epoch: int = 0
) -> dict[str, Any]:
    """Return an inert first state; this function does not persist it."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "nodeId": require_string(node_id, "nodeId", identifier=True),
        "phase": "passive-standby",
        "highestFenceEpoch": require_int(
            highest_fence_epoch, "highestFenceEpoch"
        ),
        "snapshot": None,
        "lease": None,
        "releasedLease": None,
        "lastEvaluatedAt": None,
        "usedApprovalIds": [],
        "processedEventIds": [],
        "lastReceiptId": None,
    }


def _normalize_snapshot(value: Any) -> dict[str, Any]:
    snapshot = require_object(value, "state.snapshot")
    require_exact_keys(snapshot, "state.snapshot", SNAPSHOT_KEYS)
    staged_at = format_rfc3339(
        parse_rfc3339(snapshot["stagedAt"], "state.snapshot.stagedAt")
    )
    verified_at = None
    if snapshot["verifiedAt"] is not None:
        verified_at = format_rfc3339(
            parse_rfc3339(snapshot["verifiedAt"], "state.snapshot.verifiedAt")
        )
        if parse_rfc3339(verified_at, "state.snapshot.verifiedAt") < parse_rfc3339(
            staged_at, "state.snapshot.stagedAt"
        ):
            raise InputError("state.snapshot.verifiedAt precedes stagedAt")
    return {
        "snapshotId": require_string(
            snapshot["snapshotId"], "state.snapshot.snapshotId", identifier=True
        ),
        "digest": require_digest(snapshot["digest"], "state.snapshot.digest"),
        "sourceEpoch": require_int(
            snapshot["sourceEpoch"], "state.snapshot.sourceEpoch"
        ),
        "stagedAt": staged_at,
        "verifiedAt": verified_at,
    }


def _normalize_lease(value: Any, field: str) -> dict[str, Any]:
    lease = require_object(value, field)
    require_exact_keys(lease, field, LEASE_KEYS)
    issued_at = parse_rfc3339(lease["issuedAt"], f"{field}.issuedAt")
    expires_at = parse_rfc3339(lease["expiresAt"], f"{field}.expiresAt")
    if expires_at <= issued_at:
        raise InputError(f"{field}.expiresAt must be after issuedAt")
    if (expires_at - issued_at).total_seconds() > MAX_LEASE_SECONDS:
        raise InputError(f"{field} exceeds the maximum lease duration")
    return {
        "leaseId": require_string(lease["leaseId"], f"{field}.leaseId", identifier=True),
        "holderNodeId": require_string(
            lease["holderNodeId"], f"{field}.holderNodeId", identifier=True
        ),
        "epoch": require_int(lease["epoch"], f"{field}.epoch", minimum=1),
        "issuedAt": format_rfc3339(issued_at),
        "expiresAt": format_rfc3339(expires_at),
        "authorityGrantId": require_string(
            lease["authorityGrantId"], f"{field}.authorityGrantId", identifier=True
        ),
    }


def _normalize_state(value: Any) -> dict[str, Any]:
    state = require_object(value, "state")
    require_exact_keys(state, "state", STATE_KEYS)
    if require_int(state["schemaVersion"], "state.schemaVersion") != SCHEMA_VERSION:
        raise InputError("state.schemaVersion must be 1")
    phase = require_string(state["phase"], "state.phase")
    if phase not in PHASES:
        raise InputError("state.phase is not recognized")
    node_id = require_string(state["nodeId"], "state.nodeId", identifier=True)
    highest_epoch = require_int(state["highestFenceEpoch"], "state.highestFenceEpoch")
    snapshot = None if state["snapshot"] is None else _normalize_snapshot(state["snapshot"])
    lease = None if state["lease"] is None else _normalize_lease(state["lease"], "state.lease")
    released_lease = (
        None
        if state["releasedLease"] is None
        else _normalize_lease(state["releasedLease"], "state.releasedLease")
    )
    last_evaluated_at = None
    if state["lastEvaluatedAt"] is not None:
        last_evaluated_at = format_rfc3339(
            parse_rfc3339(state["lastEvaluatedAt"], "state.lastEvaluatedAt")
        )
    used_approvals = require_string_list(
        state["usedApprovalIds"], "state.usedApprovalIds"
    )
    processed_events = require_string_list(
        state["processedEventIds"], "state.processedEventIds"
    )
    last_receipt_id = None
    if state["lastReceiptId"] is not None:
        last_receipt_id = require_digest(
            state["lastReceiptId"], "state.lastReceiptId"
        )

    if phase == "passive-standby" and any(
        item is not None for item in (snapshot, lease, released_lease)
    ):
        raise InputError("passive-standby state cannot retain transaction artifacts")
    if phase in {"restore-staged", "restore-verified"}:
        if snapshot is None or lease is not None or released_lease is not None:
            raise InputError(f"{phase} state has inconsistent artifacts")
    if phase in {
        "lease-acquired",
        "desktop-standby-eligible",
        "coremind-promotion-eligible",
    }:
        if snapshot is None or lease is None or released_lease is not None:
            raise InputError(f"{phase} state has inconsistent artifacts")
    if phase == "released":
        if snapshot is None or lease is not None or released_lease is None:
            raise InputError("released state has inconsistent artifacts")
    if snapshot is not None:
        if highest_epoch < snapshot["sourceEpoch"]:
            raise InputError("state highest fence is behind the snapshot source epoch")
        if phase != "restore-staged" and snapshot["verifiedAt"] is None:
            raise InputError(f"{phase} state requires a verified snapshot")
    active_or_released = lease if lease is not None else released_lease
    if active_or_released is not None:
        if active_or_released["holderNodeId"] != node_id:
            raise InputError("state lease holder must match state node")
        if active_or_released["epoch"] != highest_epoch:
            raise InputError("state lease epoch must equal the highest fence epoch")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "nodeId": node_id,
        "phase": phase,
        "highestFenceEpoch": highest_epoch,
        "snapshot": snapshot,
        "lease": lease,
        "releasedLease": released_lease,
        "lastEvaluatedAt": last_evaluated_at,
        "usedApprovalIds": used_approvals,
        "processedEventIds": processed_events,
        "lastReceiptId": last_receipt_id,
    }


def _normalize_event(value: Any) -> tuple[dict[str, Any], datetime]:
    event = require_object(value, "event")
    event_type = require_string(event.get("type"), "event.type")
    if event_type not in EVENT_TYPES:
        raise InputError("event.type is not recognized")
    payload_key = {
        "stage-passive-restore": "restore",
        "verify-restored-snapshot": "verification",
        "acquire-continuity-lease": "leaseAcquisition",
        "qualify-desktop-standby": "desktopEvidence",
        "qualify-coremind-promotion": "promotionEvidence",
        "rollback-release": "releaseEvidence",
    }[event_type]
    required = {"schemaVersion", "eventId", "type", "now", payload_key}
    if event_type in {
        "stage-passive-restore",
        "acquire-continuity-lease",
        "qualify-desktop-standby",
        "qualify-coremind-promotion",
    }:
        required.add("approval")
    require_exact_keys(event, "event", required)
    if require_int(event["schemaVersion"], "event.schemaVersion") != SCHEMA_VERSION:
        raise InputError("event.schemaVersion must be 1")
    normalized = copy.deepcopy(event)
    normalized["eventId"] = require_string(
        event["eventId"], "event.eventId", identifier=True
    )
    normalized["type"] = event_type
    now = parse_rfc3339(event["now"], "event.now")
    normalized["now"] = format_rfc3339(now)
    return normalized, now


def _normalize_approval(value: Any) -> tuple[dict[str, Any], datetime, datetime]:
    approval = require_object(value, "event.approval")
    require_exact_keys(
        approval,
        "event.approval",
        {
            "approvalId",
            "purpose",
            "creatorPrincipal",
            "snapshotDigest",
            "leaseEpoch",
            "issuedAt",
            "expiresAt",
            "oneUse",
            "verification",
        },
    )
    verification = require_object(
        approval["verification"], "event.approval.verification"
    )
    require_exact_keys(
        verification,
        "event.approval.verification",
        {"status", "verifier", "evidenceId"},
    )
    issued_at = parse_rfc3339(approval["issuedAt"], "event.approval.issuedAt")
    expires_at = parse_rfc3339(approval["expiresAt"], "event.approval.expiresAt")
    if expires_at <= issued_at:
        raise InputError("event.approval.expiresAt must be after issuedAt")
    if (expires_at - issued_at).total_seconds() > MAX_APPROVAL_SECONDS:
        raise InputError("event.approval exceeds the maximum validity interval")
    return (
        {
            "approvalId": require_string(
                approval["approvalId"], "event.approval.approvalId", identifier=True
            ),
            "purpose": require_string(approval["purpose"], "event.approval.purpose"),
            "creatorPrincipal": require_string(
                approval["creatorPrincipal"], "event.approval.creatorPrincipal"
            ),
            "snapshotDigest": require_digest(
                approval["snapshotDigest"], "event.approval.snapshotDigest"
            ),
            "leaseEpoch": require_int(
                approval["leaseEpoch"], "event.approval.leaseEpoch"
            ),
            "issuedAt": format_rfc3339(issued_at),
            "expiresAt": format_rfc3339(expires_at),
            "oneUse": require_bool(approval["oneUse"], "event.approval.oneUse"),
            "verification": {
                "status": require_string(
                    verification["status"], "event.approval.verification.status"
                ),
                "verifier": require_string(
                    verification["verifier"],
                    "event.approval.verification.verifier",
                    identifier=True,
                ),
                "evidenceId": require_string(
                    verification["evidenceId"],
                    "event.approval.verification.evidenceId",
                    identifier=True,
                ),
            },
        },
        issued_at,
        expires_at,
    )


def _approval_reasons(
    state: dict[str, Any],
    approval: dict[str, Any],
    issued_at: datetime,
    expires_at: datetime,
    now: datetime,
    *,
    purpose: str,
    snapshot_digest: str,
    lease_epoch: int,
) -> list[str]:
    reasons: list[str] = []
    if approval["approvalId"] in state["usedApprovalIds"]:
        reasons.append("duplicate-approval")
    if approval["purpose"] != purpose:
        reasons.append("approval-purpose-mismatch")
    if approval["creatorPrincipal"] != CREATOR_PRINCIPAL:
        reasons.append("approval-creator-mismatch")
    if approval["snapshotDigest"] != snapshot_digest:
        reasons.append("approval-snapshot-digest-mismatch")
    if approval["leaseEpoch"] != lease_epoch:
        reasons.append("approval-lease-epoch-mismatch")
    if not approval["oneUse"]:
        reasons.append("approval-not-one-use")
    if approval["verification"]["status"] != "verified":
        reasons.append("approval-unverified")
    if issued_at > now:
        reasons.append("approval-not-yet-valid")
    if now >= expires_at:
        reasons.append("approval-expired")
    return reasons


def _effect_free_result(
    *,
    input_valid: bool,
    accepted: bool,
    decision: str,
    reasons: list[str],
    next_state: dict[str, Any] | None,
    receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "dry-run",
        "inputValid": input_valid,
        "accepted": accepted,
        "decision": decision,
        "reasons": reasons,
        "receipt": receipt,
        "nextState": next_state,
        "desktopStandbyEligible": bool(
            accepted and decision == "desktop-standby-eligible"
        ),
        "coreMindPromotionEligible": bool(
            accepted and decision == "coremind-promotion-eligible"
        ),
        "singleSpeakerInvariant": {
            "maximumEligibleSpeakingCoreMinds": 1,
            "existingSpeakingCoreMindsRequired": 0,
            "speakingCoreMindStarted": False,
            "scope": "eligibility-policy-only",
        },
        "executable": False,
        "coreMindStarted": False,
        "desktopStarted": False,
        "vmStarted": False,
        "tunnelStarted": False,
        "discordBridgeStarted": False,
        "modelServerStarted": False,
        "gameStarted": False,
        "commands": [],
        "filesWritten": [],
        "servicesEnabled": [],
        "servicesStarted": [],
        "networkRequests": [],
        "sideEffects": [],
    }


def _make_receipt(
    state: dict[str, Any],
    event: dict[str, Any],
    next_state: dict[str, Any],
    decision: str,
    *,
    approval_id: str | None,
    details: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = next_state["snapshot"]
    lease = next_state["lease"] or next_state["releasedLease"]
    body = {
        "kind": "phase13-transaction-transition",
        "decision": decision,
        "eventId": event["eventId"],
        "nodeId": next_state["nodeId"],
        "evaluatedAt": event["now"],
        "snapshotDigest": snapshot["digest"] if snapshot else None,
        "leaseId": lease["leaseId"] if lease else None,
        "leaseEpoch": lease["epoch"] if lease else (
            snapshot["sourceEpoch"] if snapshot else None
        ),
        "approvalId": approval_id,
        "previousStateDigest": canonical_digest(state),
        "eventDigest": canonical_digest(event),
        "nextPhase": next_state["phase"],
        "coreMindStarted": False,
        "sideEffects": [],
        "details": details or {},
    }
    return {"schemaVersion": SCHEMA_VERSION, "receiptId": canonical_digest(body), **body}


def _accept(
    state: dict[str, Any],
    event: dict[str, Any],
    next_state: dict[str, Any],
    decision: str,
    *,
    approval_id: str | None = None,
    receipt_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    next_state["lastEvaluatedAt"] = event["now"]
    next_state["processedEventIds"].append(event["eventId"])
    if approval_id is not None:
        next_state["usedApprovalIds"].append(approval_id)
    receipt = _make_receipt(
        state,
        event,
        next_state,
        decision,
        approval_id=approval_id,
        details=receipt_details,
    )
    next_state["lastReceiptId"] = receipt["receiptId"]
    return _effect_free_result(
        input_valid=True,
        accepted=True,
        decision=decision,
        reasons=[],
        next_state=next_state,
        receipt=receipt,
    )


def _reject(
    state: dict[str, Any], decision: str, reasons: list[str]
) -> dict[str, Any]:
    return _effect_free_result(
        input_valid=True,
        accepted=False,
        decision=decision,
        reasons=list(dict.fromkeys(reasons)),
        next_state=state,
    )


def _exact_lease_reasons(
    state: dict[str, Any], *, lease_id: str, holder: str, epoch: int
) -> list[str]:
    lease = state["lease"]
    if lease is None:
        return ["active-lease-missing"]
    reasons: list[str] = []
    if lease_id != lease["leaseId"]:
        reasons.append("lease-id-mismatch")
    if holder != lease["holderNodeId"]:
        reasons.append("lease-holder-mismatch")
    if epoch < lease["epoch"]:
        reasons.append("stale-lease-epoch")
    elif epoch > lease["epoch"]:
        reasons.append("unknown-lease-epoch")
    return reasons


def _stage_restore(
    state: dict[str, Any], event: dict[str, Any], now: datetime
) -> dict[str, Any]:
    restore = require_object(event["restore"], "event.restore")
    require_exact_keys(
        restore,
        "event.restore",
        {
            "snapshotId",
            "snapshotDigest",
            "snapshotEpoch",
            "sourceMode",
            "vaultCoreMindActive",
            "restoreTarget",
            "archiveAuthenticated",
            "restoreReceiptIntegrityVerified",
        },
    )
    snapshot_id = require_string(
        restore["snapshotId"], "event.restore.snapshotId", identifier=True
    )
    digest = require_digest(restore["snapshotDigest"], "event.restore.snapshotDigest")
    source_epoch = require_int(restore["snapshotEpoch"], "event.restore.snapshotEpoch")
    source_mode = require_string(restore["sourceMode"], "event.restore.sourceMode")
    vault_active = require_bool(
        restore["vaultCoreMindActive"], "event.restore.vaultCoreMindActive"
    )
    target = require_string(restore["restoreTarget"], "event.restore.restoreTarget")
    authenticated = require_bool(
        restore["archiveAuthenticated"], "event.restore.archiveAuthenticated"
    )
    receipt_verified = require_bool(
        restore["restoreReceiptIntegrityVerified"],
        "event.restore.restoreReceiptIntegrityVerified",
    )
    approval, issued_at, expires_at = _normalize_approval(event["approval"])
    reasons: list[str] = []
    if state["phase"] != "passive-standby":
        reasons.append("transition-requires-passive-standby")
    if source_mode != "passive-vault":
        reasons.append("restore-source-not-passive-vault")
    if vault_active:
        reasons.append("passive-vault-reports-active-coremind")
    if target != "isolated-staging":
        reasons.append("restore-target-not-isolated-staging")
    if not authenticated:
        reasons.append("restore-archive-unauthenticated")
    if not receipt_verified:
        reasons.append("restore-receipt-unverified")
    if source_epoch < state["highestFenceEpoch"]:
        reasons.append("snapshot-fence-behind-known-state")
    reasons.extend(
        _approval_reasons(
            state,
            approval,
            issued_at,
            expires_at,
            now,
            purpose="stage-passive-restore",
            snapshot_digest=digest,
            lease_epoch=source_epoch,
        )
    )
    if reasons:
        return _reject(state, "restore-rejected", reasons)
    next_state = copy.deepcopy(state)
    next_state["phase"] = "restore-staged"
    next_state["highestFenceEpoch"] = source_epoch
    next_state["snapshot"] = {
        "snapshotId": snapshot_id,
        "digest": digest,
        "sourceEpoch": source_epoch,
        "stagedAt": event["now"],
        "verifiedAt": None,
    }
    return _accept(
        state,
        event,
        next_state,
        "restore-staged",
        approval_id=approval["approvalId"],
    )


def _verify_restore(
    state: dict[str, Any], event: dict[str, Any], now: datetime
) -> dict[str, Any]:
    verification = require_object(event["verification"], "event.verification")
    require_exact_keys(
        verification,
        "event.verification",
        {
            "snapshotId",
            "snapshotDigest",
            "verifiedAt",
            "evidenceId",
            "artifactDigestMatches",
            "manifestAuthenticated",
            "sqliteIntegrityOk",
            "filesComplete",
            "stagingRuntimeInactive",
        },
    )
    snapshot_id = require_string(
        verification["snapshotId"], "event.verification.snapshotId", identifier=True
    )
    digest = require_digest(
        verification["snapshotDigest"], "event.verification.snapshotDigest"
    )
    verified_at = parse_rfc3339(
        verification["verifiedAt"], "event.verification.verifiedAt"
    )
    require_string(
        verification["evidenceId"], "event.verification.evidenceId", identifier=True
    )
    checks = {
        name: require_bool(verification[name], f"event.verification.{name}")
        for name in (
            "artifactDigestMatches",
            "manifestAuthenticated",
            "sqliteIntegrityOk",
            "filesComplete",
            "stagingRuntimeInactive",
        )
    }
    reasons: list[str] = []
    if state["phase"] != "restore-staged" or state["snapshot"] is None:
        reasons.append("transition-requires-staged-restore")
    else:
        if snapshot_id != state["snapshot"]["snapshotId"]:
            reasons.append("verification-snapshot-id-mismatch")
        if digest != state["snapshot"]["digest"]:
            reasons.append("verification-snapshot-digest-mismatch")
        if verified_at < parse_rfc3339(
            state["snapshot"]["stagedAt"], "state.snapshot.stagedAt"
        ):
            reasons.append("verification-precedes-restore")
    if verified_at > now:
        reasons.append("verification-from-future")
    reasons.extend(f"integrity-check-failed:{name}" for name, ok in checks.items() if not ok)
    if reasons:
        return _reject(state, "verification-rejected", reasons)
    next_state = copy.deepcopy(state)
    next_state["phase"] = "restore-verified"
    next_state["snapshot"]["verifiedAt"] = format_rfc3339(verified_at)
    return _accept(state, event, next_state, "restore-verified")


def _acquire_lease(
    state: dict[str, Any], event: dict[str, Any], now: datetime
) -> dict[str, Any]:
    acquisition = require_object(
        event["leaseAcquisition"], "event.leaseAcquisition"
    )
    require_exact_keys(
        acquisition,
        "event.leaseAcquisition",
        {"request", "authority"},
    )
    request = require_object(acquisition["request"], "event.leaseAcquisition.request")
    require_exact_keys(
        request,
        "event.leaseAcquisition.request",
        {
            "leaseId",
            "holderNodeId",
            "requestedEpoch",
            "snapshotDigest",
            "issuedAt",
            "expiresAt",
        },
    )
    authority = require_object(
        acquisition["authority"], "event.leaseAcquisition.authority"
    )
    require_exact_keys(
        authority,
        "event.leaseAcquisition.authority",
        {
            "observedAt",
            "available",
            "linearizable",
            "grantAuthenticated",
            "ownershipUnambiguous",
            "grantId",
            "grantedLeaseId",
            "grantedHolderNodeId",
            "grantedEpoch",
            "observedHighestEpoch",
            "activeLeaseCountBeforeGrant",
            "activeSpeakingCoreMindCount",
            "conflictingOwnerNodeIds",
        },
    )
    lease_id = require_string(
        request["leaseId"], "event.leaseAcquisition.request.leaseId", identifier=True
    )
    holder = require_string(
        request["holderNodeId"],
        "event.leaseAcquisition.request.holderNodeId",
        identifier=True,
    )
    epoch = require_int(
        request["requestedEpoch"],
        "event.leaseAcquisition.request.requestedEpoch",
        minimum=1,
    )
    digest = require_digest(
        request["snapshotDigest"], "event.leaseAcquisition.request.snapshotDigest"
    )
    issued_at = parse_rfc3339(
        request["issuedAt"], "event.leaseAcquisition.request.issuedAt"
    )
    expires_at = parse_rfc3339(
        request["expiresAt"], "event.leaseAcquisition.request.expiresAt"
    )
    if expires_at <= issued_at:
        raise InputError("lease request expiresAt must be after issuedAt")
    if (expires_at - issued_at).total_seconds() > MAX_LEASE_SECONDS:
        raise InputError("lease request exceeds the maximum lease duration")
    observed_at = parse_rfc3339(
        authority["observedAt"], "event.leaseAcquisition.authority.observedAt"
    )
    available = require_bool(
        authority["available"], "event.leaseAcquisition.authority.available"
    )
    linearizable = require_bool(
        authority["linearizable"], "event.leaseAcquisition.authority.linearizable"
    )
    authenticated = require_bool(
        authority["grantAuthenticated"],
        "event.leaseAcquisition.authority.grantAuthenticated",
    )
    unambiguous = require_bool(
        authority["ownershipUnambiguous"],
        "event.leaseAcquisition.authority.ownershipUnambiguous",
    )
    grant_id = require_string(
        authority["grantId"], "event.leaseAcquisition.authority.grantId", identifier=True
    )
    granted_lease_id = require_string(
        authority["grantedLeaseId"],
        "event.leaseAcquisition.authority.grantedLeaseId",
        identifier=True,
    )
    granted_holder = require_string(
        authority["grantedHolderNodeId"],
        "event.leaseAcquisition.authority.grantedHolderNodeId",
        identifier=True,
    )
    granted_epoch = require_int(
        authority["grantedEpoch"],
        "event.leaseAcquisition.authority.grantedEpoch",
        minimum=1,
    )
    observed_highest = require_int(
        authority["observedHighestEpoch"],
        "event.leaseAcquisition.authority.observedHighestEpoch",
    )
    active_before = require_int(
        authority["activeLeaseCountBeforeGrant"],
        "event.leaseAcquisition.authority.activeLeaseCountBeforeGrant",
    )
    active_speakers = require_int(
        authority["activeSpeakingCoreMindCount"],
        "event.leaseAcquisition.authority.activeSpeakingCoreMindCount",
    )
    conflicts = require_string_list(
        authority["conflictingOwnerNodeIds"],
        "event.leaseAcquisition.authority.conflictingOwnerNodeIds",
    )
    approval, approval_issued, approval_expires = _normalize_approval(event["approval"])

    reasons: list[str] = []
    if state["phase"] != "restore-verified" or state["snapshot"] is None:
        reasons.append("transition-requires-verified-restore")
    else:
        if digest != state["snapshot"]["digest"]:
            reasons.append("lease-snapshot-digest-mismatch")
    if holder != state["nodeId"]:
        reasons.append("lease-holder-node-mismatch")
    if observed_at != now:
        reasons.append("authority-evaluation-time-mismatch")
    if not available:
        reasons.append("lease-authority-unavailable")
    if not linearizable:
        reasons.append("lease-authority-not-linearizable")
    if not authenticated:
        reasons.append("lease-grant-unauthenticated")
    if not unambiguous:
        reasons.append("ownership-ambiguous")
    if active_before != 0:
        reasons.append("existing-active-lease")
    if active_speakers != 0:
        reasons.append("existing-speaking-coremind")
    if conflicts:
        reasons.append("conflicting-owner-identities")
    if granted_lease_id != lease_id:
        reasons.append("authority-lease-id-mismatch")
    if granted_holder != holder:
        reasons.append("authority-holder-mismatch")
    if granted_epoch != epoch:
        reasons.append("authority-epoch-mismatch")
    if epoch <= max(state["highestFenceEpoch"], observed_highest):
        reasons.append("fencing-epoch-not-monotonically-newer")
    if issued_at > now:
        reasons.append("lease-not-yet-valid")
    if now >= expires_at:
        reasons.append("lease-expired")
    reasons.extend(
        _approval_reasons(
            state,
            approval,
            approval_issued,
            approval_expires,
            now,
            purpose="acquire-continuity-lease",
            snapshot_digest=digest,
            lease_epoch=epoch,
        )
    )
    if reasons:
        return _reject(state, "lease-acquisition-rejected", reasons)
    next_state = copy.deepcopy(state)
    next_state["phase"] = "lease-acquired"
    next_state["highestFenceEpoch"] = epoch
    next_state["lease"] = {
        "leaseId": lease_id,
        "holderNodeId": holder,
        "epoch": epoch,
        "issuedAt": format_rfc3339(issued_at),
        "expiresAt": format_rfc3339(expires_at),
        "authorityGrantId": grant_id,
    }
    return _accept(
        state,
        event,
        next_state,
        "lease-acquired",
        approval_id=approval["approvalId"],
    )


def _qualify_desktop(
    state: dict[str, Any], event: dict[str, Any], now: datetime
) -> dict[str, Any]:
    evidence = require_object(event["desktopEvidence"], "event.desktopEvidence")
    require_exact_keys(
        evidence,
        "event.desktopEvidence",
        {
            "evidenceId",
            "observedAt",
            "snapshotDigest",
            "leaseId",
            "leaseEpoch",
            "holderNodeId",
            "evidenceIntegrityVerified",
            "definitionReady",
            "runtimeStopped",
            "loopbackOnly",
            "creatorIngressPrepared",
            "noRuntimeProcessesStarted",
        },
    )
    evidence_id = require_string(
        evidence["evidenceId"], "event.desktopEvidence.evidenceId", identifier=True
    )
    observed_at = parse_rfc3339(
        evidence["observedAt"], "event.desktopEvidence.observedAt"
    )
    digest = require_digest(
        evidence["snapshotDigest"], "event.desktopEvidence.snapshotDigest"
    )
    lease_id = require_string(
        evidence["leaseId"], "event.desktopEvidence.leaseId", identifier=True
    )
    epoch = require_int(
        evidence["leaseEpoch"], "event.desktopEvidence.leaseEpoch", minimum=1
    )
    holder = require_string(
        evidence["holderNodeId"],
        "event.desktopEvidence.holderNodeId",
        identifier=True,
    )
    checks = {
        name: require_bool(evidence[name], f"event.desktopEvidence.{name}")
        for name in (
            "evidenceIntegrityVerified",
            "definitionReady",
            "runtimeStopped",
            "loopbackOnly",
            "creatorIngressPrepared",
            "noRuntimeProcessesStarted",
        )
    }
    approval, issued_at, expires_at = _normalize_approval(event["approval"])
    reasons: list[str] = []
    if state["phase"] != "lease-acquired" or state["snapshot"] is None:
        reasons.append("transition-requires-acquired-lease")
    else:
        if digest != state["snapshot"]["digest"]:
            reasons.append("desktop-snapshot-digest-mismatch")
    reasons.extend(
        _exact_lease_reasons(state, lease_id=lease_id, holder=holder, epoch=epoch)
    )
    if observed_at != now:
        reasons.append("desktop-evaluation-time-mismatch")
    if state["lease"] is not None and now >= parse_rfc3339(
        state["lease"]["expiresAt"], "state.lease.expiresAt"
    ):
        reasons.append("lease-expired")
    reasons.extend(f"desktop-check-failed:{name}" for name, ok in checks.items() if not ok)
    reasons.extend(
        _approval_reasons(
            state,
            approval,
            issued_at,
            expires_at,
            now,
            purpose="qualify-desktop-standby",
            snapshot_digest=digest,
            lease_epoch=epoch,
        )
    )
    if reasons:
        return _reject(state, "desktop-standby-rejected", reasons)
    next_state = copy.deepcopy(state)
    next_state["phase"] = "desktop-standby-eligible"
    result = _accept(
        state,
        event,
        next_state,
        "desktop-standby-eligible",
        approval_id=approval["approvalId"],
        receipt_details={"desktopEvidenceId": evidence_id},
    )
    return result


def _qualify_coremind(
    state: dict[str, Any], event: dict[str, Any], now: datetime
) -> dict[str, Any]:
    evidence = require_object(
        event["promotionEvidence"], "event.promotionEvidence"
    )
    require_exact_keys(
        evidence,
        "event.promotionEvidence",
        {
            "evidenceId",
            "observedAt",
            "snapshotDigest",
            "leaseId",
            "leaseEpoch",
            "holderNodeId",
            "authorityAvailable",
            "authorityLinearizable",
            "grantAuthenticated",
            "ownershipUnambiguous",
            "activeLeaseCount",
            "activeLeaseId",
            "activeLeaseHolderNodeId",
            "activeLeaseEpoch",
            "knownSpeakingCoreMindCount",
            "knownSpeakingCoreMindOwners",
            "conflictingOwnerNodeIds",
            "formerPrimaryFenced",
            "formerSpeakingCoreMindStoppedVerified",
            "desktopStillStandby",
        },
    )
    evidence_id = require_string(
        evidence["evidenceId"], "event.promotionEvidence.evidenceId", identifier=True
    )
    observed_at = parse_rfc3339(
        evidence["observedAt"], "event.promotionEvidence.observedAt"
    )
    digest = require_digest(
        evidence["snapshotDigest"], "event.promotionEvidence.snapshotDigest"
    )
    lease_id = require_string(
        evidence["leaseId"], "event.promotionEvidence.leaseId", identifier=True
    )
    epoch = require_int(
        evidence["leaseEpoch"], "event.promotionEvidence.leaseEpoch", minimum=1
    )
    holder = require_string(
        evidence["holderNodeId"],
        "event.promotionEvidence.holderNodeId",
        identifier=True,
    )
    active_lease_id = require_string(
        evidence["activeLeaseId"],
        "event.promotionEvidence.activeLeaseId",
        identifier=True,
    )
    active_holder = require_string(
        evidence["activeLeaseHolderNodeId"],
        "event.promotionEvidence.activeLeaseHolderNodeId",
        identifier=True,
    )
    active_epoch = require_int(
        evidence["activeLeaseEpoch"],
        "event.promotionEvidence.activeLeaseEpoch",
        minimum=1,
    )
    active_count = require_int(
        evidence["activeLeaseCount"], "event.promotionEvidence.activeLeaseCount"
    )
    speaker_count = require_int(
        evidence["knownSpeakingCoreMindCount"],
        "event.promotionEvidence.knownSpeakingCoreMindCount",
    )
    speaker_owners = require_string_list(
        evidence["knownSpeakingCoreMindOwners"],
        "event.promotionEvidence.knownSpeakingCoreMindOwners",
    )
    conflicts = require_string_list(
        evidence["conflictingOwnerNodeIds"],
        "event.promotionEvidence.conflictingOwnerNodeIds",
    )
    boolean_checks = {
        name: require_bool(evidence[name], f"event.promotionEvidence.{name}")
        for name in (
            "authorityAvailable",
            "authorityLinearizable",
            "grantAuthenticated",
            "ownershipUnambiguous",
            "formerPrimaryFenced",
            "formerSpeakingCoreMindStoppedVerified",
            "desktopStillStandby",
        )
    }
    approval, issued_at, expires_at = _normalize_approval(event["approval"])
    reasons: list[str] = []
    if state["phase"] != "desktop-standby-eligible" or state["snapshot"] is None:
        reasons.append("transition-requires-desktop-standby-eligibility")
    else:
        if digest != state["snapshot"]["digest"]:
            reasons.append("promotion-snapshot-digest-mismatch")
    reasons.extend(
        _exact_lease_reasons(state, lease_id=lease_id, holder=holder, epoch=epoch)
    )
    if observed_at != now:
        reasons.append("promotion-evaluation-time-mismatch")
    if state["lease"] is not None and now >= parse_rfc3339(
        state["lease"]["expiresAt"], "state.lease.expiresAt"
    ):
        reasons.append("lease-expired")
    for name, ok in boolean_checks.items():
        if not ok:
            reasons.append(f"promotion-check-failed:{name}")
    if active_count != 1:
        reasons.append("active-lease-count-not-exactly-one")
    if active_lease_id != lease_id:
        reasons.append("active-lease-id-mismatch")
    if active_holder != holder:
        reasons.append("active-lease-holder-mismatch")
    if active_epoch != epoch:
        reasons.append("active-lease-epoch-mismatch")
    if speaker_count != len(speaker_owners):
        reasons.append("speaking-owner-count-inconsistent")
    if speaker_count != 0 or speaker_owners:
        reasons.append("another-speaking-coremind-observed")
    if conflicts:
        reasons.append("conflicting-owner-identities")
    reasons.extend(
        _approval_reasons(
            state,
            approval,
            issued_at,
            expires_at,
            now,
            purpose="qualify-coremind-promotion",
            snapshot_digest=digest,
            lease_epoch=epoch,
        )
    )
    if reasons:
        return _reject(state, "coremind-promotion-rejected", reasons)
    next_state = copy.deepcopy(state)
    next_state["phase"] = "coremind-promotion-eligible"
    result = _accept(
        state,
        event,
        next_state,
        "coremind-promotion-eligible",
        approval_id=approval["approvalId"],
        receipt_details={"promotionEvidenceId": evidence_id},
    )
    return result


def _release(
    state: dict[str, Any], event: dict[str, Any], now: datetime
) -> dict[str, Any]:
    evidence = require_object(event["releaseEvidence"], "event.releaseEvidence")
    require_exact_keys(
        evidence,
        "event.releaseEvidence",
        {
            "observedAt",
            "snapshotDigest",
            "leaseId",
            "leaseEpoch",
            "holderNodeId",
            "authorityReleaseId",
            "releaseAuthenticated",
            "ownershipUnambiguous",
            "leaseNoLongerActive",
            "speakingCoreMindStoppedVerified",
            "knownSpeakingCoreMindCount",
            "knownSpeakingCoreMindOwners",
            "reason",
        },
    )
    observed_at = parse_rfc3339(
        evidence["observedAt"], "event.releaseEvidence.observedAt"
    )
    digest = require_digest(
        evidence["snapshotDigest"], "event.releaseEvidence.snapshotDigest"
    )
    lease_id = require_string(
        evidence["leaseId"], "event.releaseEvidence.leaseId", identifier=True
    )
    epoch = require_int(
        evidence["leaseEpoch"], "event.releaseEvidence.leaseEpoch", minimum=1
    )
    holder = require_string(
        evidence["holderNodeId"],
        "event.releaseEvidence.holderNodeId",
        identifier=True,
    )
    authority_release_id = require_string(
        evidence["authorityReleaseId"],
        "event.releaseEvidence.authorityReleaseId",
        identifier=True,
    )
    authenticated = require_bool(
        evidence["releaseAuthenticated"],
        "event.releaseEvidence.releaseAuthenticated",
    )
    unambiguous = require_bool(
        evidence["ownershipUnambiguous"],
        "event.releaseEvidence.ownershipUnambiguous",
    )
    no_longer_active = require_bool(
        evidence["leaseNoLongerActive"],
        "event.releaseEvidence.leaseNoLongerActive",
    )
    speaker_stopped = require_bool(
        evidence["speakingCoreMindStoppedVerified"],
        "event.releaseEvidence.speakingCoreMindStoppedVerified",
    )
    speaker_count = require_int(
        evidence["knownSpeakingCoreMindCount"],
        "event.releaseEvidence.knownSpeakingCoreMindCount",
    )
    owners = require_string_list(
        evidence["knownSpeakingCoreMindOwners"],
        "event.releaseEvidence.knownSpeakingCoreMindOwners",
    )
    require_string(evidence["reason"], "event.releaseEvidence.reason")
    reasons: list[str] = []
    if state["phase"] not in {
        "lease-acquired",
        "desktop-standby-eligible",
        "coremind-promotion-eligible",
    } or state["snapshot"] is None:
        reasons.append("transition-requires-held-lease")
    else:
        if digest != state["snapshot"]["digest"]:
            reasons.append("release-snapshot-digest-mismatch")
    reasons.extend(
        _exact_lease_reasons(state, lease_id=lease_id, holder=holder, epoch=epoch)
    )
    if observed_at != now:
        reasons.append("release-evaluation-time-mismatch")
    if not authenticated:
        reasons.append("release-unauthenticated")
    if not unambiguous:
        reasons.append("release-ownership-ambiguous")
    if not no_longer_active:
        reasons.append("lease-still-active")
    if not speaker_stopped:
        reasons.append("speaking-coremind-stop-unverified")
    if speaker_count != len(owners):
        reasons.append("speaking-owner-count-inconsistent")
    if speaker_count != 0 or owners:
        reasons.append("speaking-coremind-remains")
    if reasons:
        return _reject(state, "rollback-release-rejected", reasons)
    next_state = copy.deepcopy(state)
    next_state["phase"] = "released"
    next_state["releasedLease"] = next_state["lease"]
    next_state["lease"] = None
    result = _accept(
        state,
        event,
        next_state,
        "rollback-release-complete",
        receipt_details={
            "authorityReleaseId": authority_release_id,
            "releaseReason": evidence["reason"],
        },
    )
    return result


def evaluate_promotion_transition(
    state_value: Any, event_value: Any
) -> dict[str, Any]:
    """Evaluate one exact transition without probing, persisting, or executing."""
    try:
        state = _normalize_state(state_value)
    except InputError as exc:
        return _effect_free_result(
            input_valid=False,
            accepted=False,
            decision="invalid-state",
            reasons=[f"invalid-input:{exc}"],
            next_state=None,
        )
    try:
        event, now = _normalize_event(event_value)
        if event["eventId"] in state["processedEventIds"]:
            return _reject(state, "duplicate-event-rejected", ["duplicate-event"])
        if state["lastEvaluatedAt"] is not None and now < parse_rfc3339(
            state["lastEvaluatedAt"], "state.lastEvaluatedAt"
        ):
            return _reject(state, "clock-rollback-rejected", ["clock-rollback"])
        handler = {
            "stage-passive-restore": _stage_restore,
            "verify-restored-snapshot": _verify_restore,
            "acquire-continuity-lease": _acquire_lease,
            "qualify-desktop-standby": _qualify_desktop,
            "qualify-coremind-promotion": _qualify_coremind,
            "rollback-release": _release,
        }[event["type"]]
        return handler(state, event, now)
    except InputError as exc:
        return _effect_free_result(
            input_valid=False,
            accepted=False,
            decision="invalid-event",
            reasons=[f"invalid-input:{exc}"],
            next_state=state,
        )
