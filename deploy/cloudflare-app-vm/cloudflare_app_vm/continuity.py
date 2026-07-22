"""Proposal-only one-desktop lease evaluator with monotonic fencing."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


MAX_LEASE_SECONDS = 60


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _invalid(reason: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "mode": "dry-run",
        "inputValid": False,
        "decision": "deny",
        "reasons": [reason],
        "wouldAcquireDesktop": False,
        "wouldStartCoreMind": False,
        "proposedNextState": None,
        "decisionId": None,
        "sideEffects": [],
    }


def evaluate_desktop_lease(value: Any) -> dict[str, Any]:
    """Return a proposed lease transition without writing or starting anything."""
    if type(value) is not dict:
        return _invalid("invalid-input:root-must-be-object")
    if set(value) != {"schemaVersion", "nowEpochSeconds", "state", "request"}:
        return _invalid("invalid-input:unexpected-root-fields")
    if value.get("schemaVersion") != 1:
        return _invalid("invalid-input:schema-version")
    now = value.get("nowEpochSeconds")
    state = value.get("state")
    request = value.get("request")
    if type(now) is not int or now < 0 or type(state) is not dict or type(request) is not dict:
        return _invalid("invalid-input:field-types")
    if set(state) != {"highestFencingEpoch", "activeLease"}:
        return _invalid("invalid-input:state-fields")
    if set(request) != {
        "holderId",
        "requestedTtlSeconds",
        "creatorApproved",
        "desktopOnlyAttested",
        "expectedFencingEpoch",
    }:
        return _invalid("invalid-input:request-fields")
    highest = state.get("highestFencingEpoch")
    holder = request.get("holderId")
    ttl = request.get("requestedTtlSeconds")
    expected = request.get("expectedFencingEpoch")
    if type(highest) is not int or highest < 0:
        return _invalid("invalid-input:highest-fence")
    if type(holder) is not str or not holder or len(holder) > 128:
        return _invalid("invalid-input:holder-id")
    if type(ttl) is not int or not 1 <= ttl <= MAX_LEASE_SECONDS:
        return _invalid("invalid-input:lease-ttl")
    if type(request.get("creatorApproved")) is not bool:
        return _invalid("invalid-input:creator-approval")
    if type(request.get("desktopOnlyAttested")) is not bool:
        return _invalid("invalid-input:desktop-attestation")
    if expected is not None and (type(expected) is not int or expected < 1):
        return _invalid("invalid-input:expected-fence")

    active = state.get("activeLease")
    if active is not None:
        if type(active) is not dict or set(active) != {
            "holderId",
            "fencingEpoch",
            "expiresAtEpochSeconds",
        }:
            return _invalid("invalid-input:active-lease-fields")
        if (
            type(active.get("holderId")) is not str
            or type(active.get("fencingEpoch")) is not int
            or type(active.get("expiresAtEpochSeconds")) is not int
            or active["fencingEpoch"] < 1
            or active["fencingEpoch"] > highest
        ):
            return _invalid("invalid-input:active-lease-values")

    reasons: list[str] = []
    if not request["creatorApproved"]:
        reasons.append("creator-approval-missing")
    if not request["desktopOnlyAttested"]:
        reasons.append("desktop-only-attestation-missing")

    active_unexpired = active is not None and now < active["expiresAtEpochSeconds"]
    renewal = bool(active_unexpired and active["holderId"] == holder)
    if active_unexpired and active["holderId"] != holder:
        reasons.append("another-desktop-holder-active")
    if renewal and expected != active["fencingEpoch"]:
        reasons.append("renewal-fence-mismatch")
    if not renewal and expected is not None:
        reasons.append("new-acquisition-must-not-assert-old-fence")

    if reasons:
        return {
            "schemaVersion": 1,
            "mode": "dry-run",
            "inputValid": True,
            "decision": "deny",
            "reasons": reasons,
            "wouldAcquireDesktop": False,
            "wouldStartCoreMind": False,
            "proposedNextState": None,
            "decisionId": _digest({"decision": "deny", "now": now, "reasons": reasons}),
            "sideEffects": [],
        }

    fence = active["fencingEpoch"] if renewal else highest + 1
    next_state = {
        "highestFencingEpoch": max(highest, fence),
        "activeLease": {
            "holderId": holder,
            "fencingEpoch": fence,
            "expiresAtEpochSeconds": now + ttl,
        },
    }
    transition = "renew" if renewal else "acquire"
    decision_payload = {
        "transition": transition,
        "nowEpochSeconds": now,
        "previousState": copy.deepcopy(state),
        "proposedNextState": next_state,
    }
    return {
        "schemaVersion": 1,
        "mode": "dry-run",
        "inputValid": True,
        "decision": f"would-{transition}",
        "reasons": [],
        "wouldAcquireDesktop": True,
        "wouldStartCoreMind": False,
        "proposedNextState": next_state,
        "decisionId": _digest(decision_payload),
        "sideEffects": [],
    }
