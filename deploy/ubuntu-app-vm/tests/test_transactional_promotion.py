"""Focused tests for the pure Phase 13 transactional-promotion lane."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


SCAFFOLD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCAFFOLD))

from alpecca_ubuntu_vm.transactional_promotion import (  # noqa: E402
    evaluate_promotion_transition,
    initial_promotion_state,
)


DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64
NODE = "ubuntu-standby-example"


def _approval(approval_id: str, purpose: str, epoch: int) -> dict:
    return {
        "approvalId": approval_id,
        "purpose": purpose,
        "creatorPrincipal": "CreatorJD",
        "snapshotDigest": DIGEST,
        "leaseEpoch": epoch,
        "issuedAt": "2030-01-02T11:59:55Z",
        "expiresAt": "2030-01-02T12:04:55Z",
        "oneUse": True,
        "verification": {
            "status": "verified",
            "verifier": "external-creator-verifier",
            "evidenceId": f"evidence-{approval_id}",
        },
    }


def _restore_event() -> dict:
    return {
        "schemaVersion": 1,
        "eventId": "event-restore-041",
        "type": "stage-passive-restore",
        "now": "2030-01-02T12:00:00Z",
        "restore": {
            "snapshotId": "snapshot-041",
            "snapshotDigest": DIGEST,
            "snapshotEpoch": 41,
            "sourceMode": "passive-vault",
            "vaultCoreMindActive": False,
            "restoreTarget": "isolated-staging",
            "archiveAuthenticated": True,
            "restoreReceiptIntegrityVerified": True,
        },
        "approval": _approval(
            "approval-restore-041", "stage-passive-restore", 41
        ),
    }


def _verification_event() -> dict:
    return {
        "schemaVersion": 1,
        "eventId": "event-verify-041",
        "type": "verify-restored-snapshot",
        "now": "2030-01-02T12:00:01Z",
        "verification": {
            "snapshotId": "snapshot-041",
            "snapshotDigest": DIGEST,
            "verifiedAt": "2030-01-02T12:00:01Z",
            "evidenceId": "integrity-evidence-041",
            "artifactDigestMatches": True,
            "manifestAuthenticated": True,
            "sqliteIntegrityOk": True,
            "filesComplete": True,
            "stagingRuntimeInactive": True,
        },
    }


def _lease_event() -> dict:
    return {
        "schemaVersion": 1,
        "eventId": "event-lease-042",
        "type": "acquire-continuity-lease",
        "now": "2030-01-02T12:00:02Z",
        "leaseAcquisition": {
            "request": {
                "leaseId": "cloud-lease-042",
                "holderNodeId": NODE,
                "requestedEpoch": 42,
                "snapshotDigest": DIGEST,
                "issuedAt": "2030-01-02T12:00:02Z",
                "expiresAt": "2030-01-02T12:00:32Z",
            },
            "authority": {
                "observedAt": "2030-01-02T12:00:02Z",
                "available": True,
                "linearizable": True,
                "grantAuthenticated": True,
                "ownershipUnambiguous": True,
                "grantId": "authority-grant-042",
                "grantedLeaseId": "cloud-lease-042",
                "grantedHolderNodeId": NODE,
                "grantedEpoch": 42,
                "observedHighestEpoch": 41,
                "activeLeaseCountBeforeGrant": 0,
                "activeSpeakingCoreMindCount": 0,
                "conflictingOwnerNodeIds": [],
            },
        },
        "approval": _approval(
            "approval-lease-042", "acquire-continuity-lease", 42
        ),
    }


def _desktop_event() -> dict:
    return {
        "schemaVersion": 1,
        "eventId": "event-desktop-042",
        "type": "qualify-desktop-standby",
        "now": "2030-01-02T12:00:03Z",
        "desktopEvidence": {
            "evidenceId": "desktop-evidence-042",
            "observedAt": "2030-01-02T12:00:03Z",
            "snapshotDigest": DIGEST,
            "leaseId": "cloud-lease-042",
            "leaseEpoch": 42,
            "holderNodeId": NODE,
            "evidenceIntegrityVerified": True,
            "definitionReady": True,
            "runtimeStopped": True,
            "loopbackOnly": True,
            "creatorIngressPrepared": True,
            "noRuntimeProcessesStarted": True,
        },
        "approval": _approval(
            "approval-desktop-042", "qualify-desktop-standby", 42
        ),
    }


def _promotion_event() -> dict:
    return {
        "schemaVersion": 1,
        "eventId": "event-promote-042",
        "type": "qualify-coremind-promotion",
        "now": "2030-01-02T12:00:04Z",
        "promotionEvidence": {
            "evidenceId": "promotion-evidence-042",
            "observedAt": "2030-01-02T12:00:04Z",
            "snapshotDigest": DIGEST,
            "leaseId": "cloud-lease-042",
            "leaseEpoch": 42,
            "holderNodeId": NODE,
            "authorityAvailable": True,
            "authorityLinearizable": True,
            "grantAuthenticated": True,
            "ownershipUnambiguous": True,
            "activeLeaseCount": 1,
            "activeLeaseId": "cloud-lease-042",
            "activeLeaseHolderNodeId": NODE,
            "activeLeaseEpoch": 42,
            "knownSpeakingCoreMindCount": 0,
            "knownSpeakingCoreMindOwners": [],
            "conflictingOwnerNodeIds": [],
            "formerPrimaryFenced": True,
            "formerSpeakingCoreMindStoppedVerified": True,
            "desktopStillStandby": True,
        },
        "approval": _approval(
            "approval-promote-042", "qualify-coremind-promotion", 42
        ),
    }


def _release_event() -> dict:
    return {
        "schemaVersion": 1,
        "eventId": "event-release-042",
        "type": "rollback-release",
        "now": "2030-01-02T12:00:05Z",
        "releaseEvidence": {
            "observedAt": "2030-01-02T12:00:05Z",
            "snapshotDigest": DIGEST,
            "leaseId": "cloud-lease-042",
            "leaseEpoch": 42,
            "holderNodeId": NODE,
            "authorityReleaseId": "authority-release-042",
            "releaseAuthenticated": True,
            "ownershipUnambiguous": True,
            "leaseNoLongerActive": True,
            "speakingCoreMindStoppedVerified": True,
            "knownSpeakingCoreMindCount": 0,
            "knownSpeakingCoreMindOwners": [],
            "reason": "promotion-soak-rollback",
        },
    }


def _advance(state: dict, event: dict) -> dict:
    result = evaluate_promotion_transition(state, event)
    assert result["accepted"] is True, result
    return result["nextState"]


def _verified_state() -> dict:
    state = initial_promotion_state(NODE, highest_fence_epoch=40)
    state = _advance(state, _restore_event())
    return _advance(state, _verification_event())


def _leased_state() -> dict:
    return _advance(_verified_state(), _lease_event())


def _desktop_state() -> dict:
    return _advance(_leased_state(), _desktop_event())


def _assert_effect_free(result: dict) -> None:
    assert result["mode"] == "dry-run"
    assert result["executable"] is False
    for key in (
        "coreMindStarted",
        "desktopStarted",
        "vmStarted",
        "tunnelStarted",
        "discordBridgeStarted",
        "modelServerStarted",
        "gameStarted",
    ):
        assert result[key] is False
    for key in (
        "commands",
        "filesWritten",
        "servicesEnabled",
        "servicesStarted",
        "networkRequests",
        "sideEffects",
    ):
        assert result[key] == []


def test_complete_transaction_is_pure_deterministic_and_stops_at_eligibility() -> None:
    state = initial_promotion_state(NODE, highest_fence_epoch=40)
    events = [
        _restore_event(),
        _verification_event(),
        _lease_event(),
        _desktop_event(),
        _promotion_event(),
    ]
    expected = [
        "restore-staged",
        "restore-verified",
        "lease-acquired",
        "desktop-standby-eligible",
        "coremind-promotion-eligible",
    ]
    for event, decision in zip(events, expected):
        original_state = copy.deepcopy(state)
        original_event = copy.deepcopy(event)
        first = evaluate_promotion_transition(state, event)
        repeated = evaluate_promotion_transition(state, event)
        assert first == repeated
        assert state == original_state
        assert event == original_event
        assert first["accepted"] is True
        assert first["decision"] == decision
        _assert_effect_free(first)
        state = first["nextState"]

    assert state["phase"] == "coremind-promotion-eligible"
    assert state["highestFenceEpoch"] == 42
    assert state["lease"]["epoch"] == 42
    assert len(state["usedApprovalIds"]) == 4
    assert len(state["processedEventIds"]) == 5
    assert first["coreMindPromotionEligible"] is True
    assert first["singleSpeakerInvariant"]["maximumEligibleSpeakingCoreMinds"] == 1
    assert first["singleSpeakerInvariant"]["speakingCoreMindStarted"] is False


def test_stale_or_duplicate_fence_is_rejected() -> None:
    state = _verified_state()
    event = _lease_event()
    event["leaseAcquisition"]["request"]["requestedEpoch"] = 41
    event["leaseAcquisition"]["authority"]["grantedEpoch"] = 41
    event["approval"]["leaseEpoch"] = 41

    result = evaluate_promotion_transition(state, event)
    assert result["accepted"] is False
    assert "fencing-epoch-not-monotonically-newer" in result["reasons"]
    assert result["nextState"] == state
    _assert_effect_free(result)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("snapshotDigest", OTHER_DIGEST, "approval-snapshot-digest-mismatch"),
        ("leaseEpoch", 43, "approval-lease-epoch-mismatch"),
    ],
)
def test_approval_is_bound_to_exact_snapshot_and_lease_epoch(
    field: str, value: object, reason: str
) -> None:
    state = _leased_state()
    event = _desktop_event()
    event["approval"][field] = value

    result = evaluate_promotion_transition(state, event)
    assert result["accepted"] is False
    assert reason in result["reasons"]
    _assert_effect_free(result)


def test_used_approval_and_processed_event_are_rejected() -> None:
    initial = initial_promotion_state(NODE, highest_fence_epoch=40)
    restore = _restore_event()
    restored = _advance(initial, restore)
    duplicate_event = evaluate_promotion_transition(restored, restore)
    assert duplicate_event["decision"] == "duplicate-event-rejected"
    assert duplicate_event["reasons"] == ["duplicate-event"]

    verified = _advance(restored, _verification_event())
    lease = _lease_event()
    lease["approval"]["approvalId"] = "approval-restore-041"
    duplicate_approval = evaluate_promotion_transition(verified, lease)
    assert duplicate_approval["accepted"] is False
    assert "duplicate-approval" in duplicate_approval["reasons"]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("ambiguous", "promotion-check-failed:ownershipUnambiguous"),
        ("speaker", "another-speaking-coremind-observed"),
        ("conflict", "conflicting-owner-identities"),
    ],
)
def test_ambiguous_or_competing_ownership_blocks_promotion(
    mutation: str, reason: str
) -> None:
    state = _desktop_state()
    event = _promotion_event()
    evidence = event["promotionEvidence"]
    if mutation == "ambiguous":
        evidence["ownershipUnambiguous"] = False
    elif mutation == "speaker":
        evidence["knownSpeakingCoreMindCount"] = 1
        evidence["knownSpeakingCoreMindOwners"] = ["local-authoritative-host"]
    else:
        evidence["conflictingOwnerNodeIds"] = ["unexpected-owner"]

    result = evaluate_promotion_transition(state, event)
    assert result["accepted"] is False
    assert reason in result["reasons"]
    assert result["coreMindPromotionEligible"] is False
    _assert_effect_free(result)


def test_expired_lease_blocks_desktop_eligibility() -> None:
    state = _leased_state()
    event = _desktop_event()
    event["now"] = "2030-01-02T12:00:32Z"
    event["desktopEvidence"]["observedAt"] = event["now"]

    result = evaluate_promotion_transition(state, event)
    assert result["accepted"] is False
    assert "lease-expired" in result["reasons"]
    assert result["desktopStandbyEligible"] is False


def test_release_receipt_is_exact_and_preserves_the_monotonic_fence() -> None:
    promoted = _advance(_desktop_state(), _promotion_event())
    release = _release_event()
    result = evaluate_promotion_transition(promoted, release)

    assert result["accepted"] is True
    assert result["decision"] == "rollback-release-complete"
    assert result["nextState"]["phase"] == "released"
    assert result["nextState"]["lease"] is None
    assert result["nextState"]["releasedLease"]["leaseId"] == "cloud-lease-042"
    assert result["nextState"]["highestFenceEpoch"] == 42
    assert result["receipt"]["snapshotDigest"] == DIGEST
    assert result["receipt"]["leaseId"] == "cloud-lease-042"
    assert result["receipt"]["leaseEpoch"] == 42
    assert (
        result["receipt"]["details"]["authorityReleaseId"]
        == "authority-release-042"
    )
    _assert_effect_free(result)

    duplicate = evaluate_promotion_transition(result["nextState"], release)
    assert duplicate["decision"] == "duplicate-event-rejected"
    assert duplicate["accepted"] is False


def test_release_rejects_ambiguous_or_incomplete_external_acknowledgement() -> None:
    promoted = _advance(_desktop_state(), _promotion_event())
    release = _release_event()
    release["releaseEvidence"]["leaseNoLongerActive"] = False
    release["releaseEvidence"]["ownershipUnambiguous"] = False

    result = evaluate_promotion_transition(promoted, release)
    assert result["accepted"] is False
    assert "lease-still-active" in result["reasons"]
    assert "release-ownership-ambiguous" in result["reasons"]
    assert result["nextState"] == promoted


def test_source_has_no_operational_dependency_or_write_api() -> None:
    source = (
        SCAFFOLD / "alpecca_ubuntu_vm" / "transactional_promotion.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "import os",
        "import socket",
        "import subprocess",
        "import urllib",
        "import requests",
        "systemctl",
        "docker",
        "cloudflared",
        "ollama",
        "import discord",
        "write_text(",
        "write_bytes(",
        "open(",
        "Popen(",
    ):
        assert forbidden not in source
