"""Composite local-owner continuity takeover policy with no operational effects."""
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
    require_exact_keys,
    require_int,
    require_object,
    require_string,
)
from .supervisor import evaluate_supervisor


SCHEMA_VERSION = 1
LOCAL_HEARTBEAT_MAX_TTL_SECONDS = 35
LOCAL_OWNERSHIP_LEASE_MAX_SECONDS = 35
CREATOR_ACTIVATION_MAX_SECONDS = 300
CREATOR_ACTIVATION_MARKER_PATH = "/etc/alpecca/enable-cloud-core"


def _normalize_heartbeat(value: Any) -> tuple[dict[str, Any], datetime, datetime]:
    heartbeat = require_object(value, "continuity.localOwnerHeartbeat")
    require_exact_keys(
        heartbeat,
        "continuity.localOwnerHeartbeat",
        {"ownerNodeId", "observedAt", "validUntil", "integrityVerified"},
    )
    observed_at = parse_rfc3339(
        heartbeat["observedAt"], "continuity.localOwnerHeartbeat.observedAt"
    )
    valid_until = parse_rfc3339(
        heartbeat["validUntil"], "continuity.localOwnerHeartbeat.validUntil"
    )
    if valid_until <= observed_at:
        raise InputError("local owner heartbeat validUntil must be after observedAt")
    if (valid_until - observed_at).total_seconds() > LOCAL_HEARTBEAT_MAX_TTL_SECONDS:
        raise InputError("local owner heartbeat exceeds the maximum freshness interval")
    normalized = {
        "ownerNodeId": require_string(
            heartbeat["ownerNodeId"],
            "continuity.localOwnerHeartbeat.ownerNodeId",
            identifier=True,
        ),
        "observedAt": format_rfc3339(observed_at),
        "validUntil": format_rfc3339(valid_until),
        "integrityVerified": require_bool(
            heartbeat["integrityVerified"],
            "continuity.localOwnerHeartbeat.integrityVerified",
        ),
    }
    return normalized, observed_at, valid_until


def _normalize_local_lease(value: Any) -> tuple[dict[str, Any], datetime, datetime]:
    lease = require_object(value, "continuity.localOwnershipLease")
    require_exact_keys(
        lease,
        "continuity.localOwnershipLease",
        {
            "schemaVersion",
            "leaseId",
            "holderNodeId",
            "fencingEpoch",
            "issuedAt",
            "expiresAt",
            "integrityVerified",
        },
    )
    if require_int(
        lease["schemaVersion"], "continuity.localOwnershipLease.schemaVersion"
    ) != 1:
        raise InputError("local ownership lease schemaVersion must be 1")
    issued_at = parse_rfc3339(
        lease["issuedAt"], "continuity.localOwnershipLease.issuedAt"
    )
    expires_at = parse_rfc3339(
        lease["expiresAt"], "continuity.localOwnershipLease.expiresAt"
    )
    if expires_at <= issued_at:
        raise InputError("local ownership lease expiresAt must be after issuedAt")
    if (expires_at - issued_at).total_seconds() > LOCAL_OWNERSHIP_LEASE_MAX_SECONDS:
        raise InputError("local ownership lease exceeds the maximum lease duration")
    normalized = {
        "schemaVersion": SCHEMA_VERSION,
        "leaseId": require_string(
            lease["leaseId"], "continuity.localOwnershipLease.leaseId", identifier=True
        ),
        "holderNodeId": require_string(
            lease["holderNodeId"],
            "continuity.localOwnershipLease.holderNodeId",
            identifier=True,
        ),
        "fencingEpoch": require_int(
            lease["fencingEpoch"],
            "continuity.localOwnershipLease.fencingEpoch",
            minimum=1,
        ),
        "issuedAt": format_rfc3339(issued_at),
        "expiresAt": format_rfc3339(expires_at),
        "integrityVerified": require_bool(
            lease["integrityVerified"],
            "continuity.localOwnershipLease.integrityVerified",
        ),
    }
    return normalized, issued_at, expires_at


def _normalize_creator_activation(
    value: Any,
) -> tuple[dict[str, Any], datetime, datetime]:
    activation = require_object(value, "continuity.creatorActivation")
    require_exact_keys(
        activation,
        "continuity.creatorActivation",
        {
            "activationId",
            "markerPath",
            "markerPresent",
            "markerIntegrityVerified",
            "creatorApprovalVerified",
            "issuedAt",
            "expiresAt",
        },
    )
    issued_at = parse_rfc3339(
        activation["issuedAt"], "continuity.creatorActivation.issuedAt"
    )
    expires_at = parse_rfc3339(
        activation["expiresAt"], "continuity.creatorActivation.expiresAt"
    )
    if expires_at <= issued_at:
        raise InputError("creator activation expiresAt must be after issuedAt")
    if (expires_at - issued_at).total_seconds() > CREATOR_ACTIVATION_MAX_SECONDS:
        raise InputError("creator activation exceeds the maximum validity interval")
    normalized = {
        "activationId": require_string(
            activation["activationId"],
            "continuity.creatorActivation.activationId",
            identifier=True,
        ),
        "markerPath": require_string(
            activation["markerPath"], "continuity.creatorActivation.markerPath"
        ),
        "markerPresent": require_bool(
            activation["markerPresent"], "continuity.creatorActivation.markerPresent"
        ),
        "markerIntegrityVerified": require_bool(
            activation["markerIntegrityVerified"],
            "continuity.creatorActivation.markerIntegrityVerified",
        ),
        "creatorApprovalVerified": require_bool(
            activation["creatorApprovalVerified"],
            "continuity.creatorActivation.creatorApprovalVerified",
        ),
        "issuedAt": format_rfc3339(issued_at),
        "expiresAt": format_rfc3339(expires_at),
    }
    return normalized, issued_at, expires_at


def _result(
    *,
    input_valid: bool,
    decision: str,
    reasons: list[str],
    heartbeat_fresh: bool | None,
    local_lease_expired: bool | None,
    creator_activation_ready: bool,
    supervisor_decision: str,
    decision_id: str | None = None,
    candidate_fence: dict[str, Any] | None = None,
    next_supervisor_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    eligible = decision == "takeover-eligible"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "dry-run",
        "inputValid": input_valid,
        "decision": decision,
        "wouldTakeContinuityOwnership": eligible,
        "wouldStartAlpecca": False,
        "executable": False,
        "reasons": reasons,
        "localHeartbeatFresh": heartbeat_fresh,
        "localOwnershipLeaseExpired": local_lease_expired,
        "creatorActivationReady": creator_activation_ready,
        "supervisorDecision": supervisor_decision,
        "decisionId": decision_id,
        "candidateFence": candidate_fence,
        "nextSupervisorState": next_supervisor_state if eligible else None,
        "sideEffects": [],
    }


def _invalid_result(error: InputError) -> dict[str, Any]:
    return _result(
        input_valid=False,
        decision="standby",
        reasons=[f"invalid-input:{error}"],
        heartbeat_fresh=None,
        local_lease_expired=None,
        creator_activation_ready=False,
        supervisor_decision="not-evaluated",
    )


def evaluate_continuity_takeover(value: Any) -> dict[str, Any]:
    """Evaluate cloud takeover only after local ownership is conclusively stale."""
    try:
        continuity = require_object(value, "continuity")
        require_exact_keys(
            continuity,
            "continuity",
            {
                "schemaVersion",
                "now",
                "cloudNodeId",
                "localOwnerHeartbeat",
                "localOwnershipLease",
                "creatorActivation",
                "supervisorObservation",
            },
        )
        if require_int(continuity["schemaVersion"], "continuity.schemaVersion") != 1:
            raise InputError("continuity.schemaVersion must be 1")
        now = parse_rfc3339(continuity["now"], "continuity.now")
        cloud_node_id = require_string(
            continuity["cloudNodeId"], "continuity.cloudNodeId", identifier=True
        )
        heartbeat, heartbeat_observed_at, heartbeat_valid_until = _normalize_heartbeat(
            continuity["localOwnerHeartbeat"]
        )
        local_lease, _, local_lease_expires_at = _normalize_local_lease(
            continuity["localOwnershipLease"]
        )
        activation, activation_issued_at, activation_expires_at = (
            _normalize_creator_activation(continuity["creatorActivation"])
        )
        supervisor_observation = copy.deepcopy(
            require_object(continuity["supervisorObservation"], "continuity.supervisorObservation")
        )
    except InputError as exc:
        return _invalid_result(exc)

    heartbeat_fresh = now < heartbeat_valid_until
    local_lease_expired = now >= local_lease_expires_at
    reasons: list[str] = []

    if not heartbeat["integrityVerified"]:
        reasons.append("local-owner-heartbeat-unverified")
    if heartbeat_observed_at > now:
        reasons.append("local-owner-heartbeat-from-future")
    if heartbeat_fresh:
        reasons.append("local-owner-heartbeat-fresh")
    if not local_lease["integrityVerified"]:
        reasons.append("local-ownership-lease-unverified")
    if heartbeat["ownerNodeId"] != local_lease["holderNodeId"]:
        reasons.append("local-owner-identity-mismatch")
    if local_lease["holderNodeId"] == cloud_node_id:
        reasons.append("cloud-node-is-local-owner")
    if not local_lease_expired:
        reasons.append("local-ownership-lease-active")

    if activation["markerPath"] != CREATOR_ACTIVATION_MARKER_PATH:
        reasons.append("creator-activation-marker-path-mismatch")
    if not activation["markerPresent"]:
        reasons.append("creator-activation-marker-missing")
    if not activation["markerIntegrityVerified"]:
        reasons.append("creator-activation-marker-unverified")
    if not activation["creatorApprovalVerified"]:
        reasons.append("creator-activation-unapproved")
    if activation_issued_at > now:
        reasons.append("creator-activation-not-yet-valid")
    if now >= activation_expires_at:
        reasons.append("creator-activation-expired")
    if activation_issued_at < local_lease_expires_at:
        reasons.append("creator-activation-precedes-local-lease-expiry")
    if activation_issued_at < heartbeat_valid_until:
        reasons.append("creator-activation-precedes-heartbeat-expiry")

    base_result = evaluate_supervisor(supervisor_observation)
    if not base_result["inputValid"]:
        reasons.append("supervisor-observation-invalid")
    if not base_result["wouldLead"]:
        reasons.extend(f"supervisor:{reason}" for reason in base_result["reasons"])

    candidate_epoch: int | None = None
    candidate_lease_id: str | None = None
    if base_result["inputValid"]:
        observation_now = parse_rfc3339(
            supervisor_observation["now"], "continuity.supervisorObservation.now"
        )
        observation_node_id = require_string(
            supervisor_observation["nodeId"],
            "continuity.supervisorObservation.nodeId",
            identifier=True,
        )
        if observation_now != now:
            reasons.append("supervisor-evaluation-time-mismatch")
        if observation_node_id != cloud_node_id:
            reasons.append("supervisor-cloud-node-mismatch")

        candidate_lease = supervisor_observation.get("lease")
        if type(candidate_lease) is dict:
            candidate_epoch = require_int(
                candidate_lease["fencingEpoch"],
                "continuity.supervisorObservation.lease.fencingEpoch",
                minimum=1,
            )
            candidate_lease_id = require_string(
                candidate_lease["leaseId"],
                "continuity.supervisorObservation.lease.leaseId",
                identifier=True,
            )
            candidate_issued_at = parse_rfc3339(
                candidate_lease["issuedAt"],
                "continuity.supervisorObservation.lease.issuedAt",
            )
            if candidate_epoch <= local_lease["fencingEpoch"]:
                reasons.append("candidate-fencing-epoch-not-newer-than-local-owner")
            if candidate_issued_at < local_lease_expires_at:
                reasons.append("candidate-lease-issued-before-local-lease-expiry")
            if candidate_issued_at < activation_issued_at:
                reasons.append("candidate-lease-issued-before-creator-activation")

            state = supervisor_observation["state"]
            highest_observed_epoch = require_int(
                state["highestFencingEpoch"],
                "continuity.supervisorObservation.state.highestFencingEpoch",
            )
            if highest_observed_epoch < local_lease["fencingEpoch"]:
                reasons.append("supervisor-state-behind-local-owner-epoch")

    creator_activation_ready = not any(
        reason.startswith("creator-activation-") for reason in reasons
    )
    reasons = list(dict.fromkeys(reasons))
    if reasons:
        return _result(
            input_valid=True,
            decision="standby",
            reasons=reasons,
            heartbeat_fresh=heartbeat_fresh,
            local_lease_expired=local_lease_expired,
            creator_activation_ready=creator_activation_ready,
            supervisor_decision=base_result["decision"],
        )

    assert candidate_epoch is not None and candidate_lease_id is not None
    decision_id = canonical_digest(
        {
            "kind": "continuity-takeover-eligible",
            "cloudNodeId": cloud_node_id,
            "localHeartbeatValidUntil": heartbeat["validUntil"],
            "localOwnershipLeaseId": local_lease["leaseId"],
            "localOwnershipEpoch": local_lease["fencingEpoch"],
            "localOwnershipExpiresAt": local_lease["expiresAt"],
            "creatorActivationId": activation["activationId"],
            "candidateLeaseId": candidate_lease_id,
            "candidateEpoch": candidate_epoch,
            "supervisorDecisionId": base_result["decisionId"],
        }
    )
    return _result(
        input_valid=True,
        decision="takeover-eligible",
        reasons=[],
        heartbeat_fresh=False,
        local_lease_expired=True,
        creator_activation_ready=True,
        supervisor_decision=base_result["decision"],
        decision_id=decision_id,
        candidate_fence={
            "leaseId": candidate_lease_id,
            "fencingEpoch": candidate_epoch,
        },
        next_supervisor_state=base_result["nextState"],
    )
