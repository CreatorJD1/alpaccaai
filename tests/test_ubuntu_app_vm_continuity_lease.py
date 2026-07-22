"""Focused tests for the inert local-to-cloud continuity ownership contract."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "deploy" / "ubuntu-app-vm"
EXAMPLE = SCAFFOLD / "contracts" / "continuity-takeover.example.json"
CONTRACT = SCAFFOLD / "contracts" / "continuity-ownership-lease-contract.json"
LEADER_CONTRACT = SCAFFOLD / "contracts" / "leader-lease-contract.json"
ENTRYPOINT = SCAFFOLD / "bin" / "alpecca-cloud-supervisor"
sys.path.insert(0, str(SCAFFOLD))

from alpecca_ubuntu_vm.continuity_lease import (  # noqa: E402
    evaluate_continuity_takeover,
)


def _takeover_input() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_documented_takeover_is_deterministic_but_never_executable() -> None:
    value = _takeover_input()
    original = copy.deepcopy(value)

    first = evaluate_continuity_takeover(value)
    repeated = evaluate_continuity_takeover(value)

    assert value == original
    assert first == repeated
    assert first["inputValid"] is True
    assert first["decision"] == "takeover-eligible"
    assert first["wouldTakeContinuityOwnership"] is True
    assert first["wouldStartAlpecca"] is False
    assert first["executable"] is False
    assert first["sideEffects"] == []
    assert first["localHeartbeatFresh"] is False
    assert first["localOwnershipLeaseExpired"] is True
    assert first["candidateFence"] == {
        "leaseId": "cloud-lease-042",
        "fencingEpoch": 42,
    }
    assert first["nextSupervisorState"]["status"] == "leader-ready"


def test_fresh_local_owner_heartbeat_always_forces_standby() -> None:
    value = _takeover_input()
    value["localOwnerHeartbeat"].update(
        {
            "observedAt": "2030-01-02T12:01:40Z",
            "validUntil": "2030-01-02T12:02:15Z",
        }
    )

    result = evaluate_continuity_takeover(value)

    assert result["decision"] == "standby"
    assert result["localHeartbeatFresh"] is True
    assert "local-owner-heartbeat-fresh" in result["reasons"]
    assert result["wouldTakeContinuityOwnership"] is False
    assert result["wouldStartAlpecca"] is False
    assert result["nextSupervisorState"] is None


def test_unexpired_local_ownership_lease_always_forces_standby() -> None:
    value = _takeover_input()
    value["localOwnershipLease"].update(
        {
            "issuedAt": "2030-01-02T12:01:40Z",
            "expiresAt": "2030-01-02T12:02:15Z",
        }
    )

    result = evaluate_continuity_takeover(value)

    assert result["decision"] == "standby"
    assert result["localOwnershipLeaseExpired"] is False
    assert "local-ownership-lease-active" in result["reasons"]
    assert result["wouldTakeContinuityOwnership"] is False
    assert result["nextSupervisorState"] is None


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda value: value["localOwnerHeartbeat"].update(
                {"integrityVerified": False}
            ),
            "local-owner-heartbeat-unverified",
        ),
        (
            lambda value: value["localOwnershipLease"].update(
                {"integrityVerified": False}
            ),
            "local-ownership-lease-unverified",
        ),
        (
            lambda value: value["localOwnerHeartbeat"].update(
                {"ownerNodeId": "unexpected-local-owner"}
            ),
            "local-owner-identity-mismatch",
        ),
        (
            lambda value: value["localOwnershipLease"].update(
                {"holderNodeId": value["cloudNodeId"]}
            ),
            "cloud-node-is-local-owner",
        ),
    ],
)
def test_local_owner_evidence_must_be_verified_and_identity_consistent(
    mutation, reason: str
) -> None:
    value = _takeover_input()
    mutation(value)

    result = evaluate_continuity_takeover(value)

    assert result["inputValid"] is True
    assert result["decision"] == "standby"
    assert reason in result["reasons"]
    assert result["wouldTakeContinuityOwnership"] is False
    assert result["wouldStartAlpecca"] is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("markerPresent", False, "creator-activation-marker-missing"),
        ("markerIntegrityVerified", False, "creator-activation-marker-unverified"),
        ("creatorApprovalVerified", False, "creator-activation-unapproved"),
        (
            "markerPath",
            "/tmp/enable-cloud-core",
            "creator-activation-marker-path-mismatch",
        ),
    ],
)
def test_creator_activation_marker_is_explicit_and_verified(
    field: str, value: object, reason: str
) -> None:
    takeover = _takeover_input()
    takeover["creatorActivation"][field] = value

    result = evaluate_continuity_takeover(takeover)

    assert result["decision"] == "standby"
    assert reason in result["reasons"]
    assert result["creatorActivationReady"] is False
    assert result["wouldTakeContinuityOwnership"] is False


def test_creator_activation_must_follow_both_local_expiry_signals() -> None:
    value = _takeover_input()
    value["creatorActivation"].update(
        {
            "issuedAt": "2030-01-02T12:00:20Z",
            "expiresAt": "2030-01-02T12:05:20Z",
        }
    )

    result = evaluate_continuity_takeover(value)

    assert "creator-activation-precedes-local-lease-expiry" in result["reasons"]
    assert "creator-activation-precedes-heartbeat-expiry" in result["reasons"]
    assert result["decision"] == "standby"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda value: value["supervisorObservation"]["lease"].update(
                {"fencingEpoch": 41}
            ),
            "candidate-fencing-epoch-not-newer-than-local-owner",
        ),
        (
            lambda value: value["creatorActivation"].update(
                {"issuedAt": "2030-01-02T12:01:55Z"}
            ),
            "candidate-lease-issued-before-creator-activation",
        ),
        (
            lambda value: value["supervisorObservation"]["state"].update(
                {"highestFencingEpoch": 40}
            ),
            "supervisor-state-behind-local-owner-epoch",
        ),
    ],
)
def test_candidate_cloud_lease_must_be_ordered_and_strictly_fenced(
    mutate, reason: str
) -> None:
    value = _takeover_input()
    mutate(value)

    result = evaluate_continuity_takeover(value)

    assert result["decision"] == "standby"
    assert reason in result["reasons"]
    assert result["candidateFence"] is None
    assert result["nextSupervisorState"] is None


def test_expiry_boundaries_are_closed_open_and_takeover_can_only_follow_them() -> None:
    value = _takeover_input()
    value["localOwnerHeartbeat"].update(
        {
            "observedAt": "2030-01-02T12:01:25Z",
            "validUntil": value["now"],
        }
    )
    value["localOwnershipLease"].update(
        {
            "issuedAt": "2030-01-02T12:01:25Z",
            "expiresAt": value["now"],
        }
    )
    value["creatorActivation"].update(
        {
            "issuedAt": value["now"],
            "expiresAt": "2030-01-02T12:05:00Z",
        }
    )
    value["supervisorObservation"]["lease"].update(
        {
            "issuedAt": value["now"],
            "expiresAt": "2030-01-02T12:02:35Z",
        }
    )

    result = evaluate_continuity_takeover(value)

    assert result["decision"] == "takeover-eligible"
    assert result["localHeartbeatFresh"] is False
    assert result["localOwnershipLeaseExpired"] is True
    assert result["wouldStartAlpecca"] is False


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda value: value["supervisorObservation"]["authority"].update(
                {"available": False}
            ),
            "supervisor:authority-unavailable",
        ),
        (
            lambda value: value["supervisorObservation"].update(
                {"now": "2030-01-02T12:02:01Z"}
            ),
            "supervisor-evaluation-time-mismatch",
        ),
        (
            lambda value: (
                value["supervisorObservation"].update({"nodeId": "other-cloud-node"}),
                value["supervisorObservation"]["lease"].update(
                    {"holderNodeId": "other-cloud-node"}
                ),
            ),
            "supervisor-cloud-node-mismatch",
        ),
    ],
)
def test_existing_supervisor_decision_is_a_required_prerequisite(
    mutation, reason: str
) -> None:
    value = _takeover_input()
    mutation(value)

    result = evaluate_continuity_takeover(value)

    assert result["decision"] == "standby"
    assert reason in result["reasons"]
    assert result["wouldTakeContinuityOwnership"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["localOwnerHeartbeat"].pop("integrityVerified"),
        lambda value: value["localOwnerHeartbeat"].update(
            {"validUntil": "2030-01-02T12:00:36Z"}
        ),
        lambda value: value["localOwnershipLease"].update(
            {"expiresAt": "2030-01-02T12:00:26Z"}
        ),
        lambda value: value["creatorActivation"].update(
            {"expiresAt": "2030-01-02T12:05:36Z"}
        ),
    ],
)
def test_malformed_or_overlong_evidence_fails_closed(mutation) -> None:
    value = _takeover_input()
    mutation(value)

    result = evaluate_continuity_takeover(value)

    assert result["inputValid"] is False
    assert result["decision"] == "standby"
    assert result["wouldTakeContinuityOwnership"] is False
    assert result["wouldStartAlpecca"] is False
    assert result["nextSupervisorState"] is None
    assert result["reasons"][0].startswith("invalid-input:")


def test_continuity_cli_requires_dry_run_and_denials_use_exit_code_three(
    tmp_path: Path,
) -> None:
    eligible = subprocess.run(
        [
            sys.executable,
            str(ENTRYPOINT),
            "evaluate-continuity",
            "--dry-run",
            "--input",
            str(EXAMPLE),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert eligible.returncode == 0
    assert json.loads(eligible.stdout)["wouldStartAlpecca"] is False

    denied_value = _takeover_input()
    denied_value["localOwnerHeartbeat"].update(
        {
            "observedAt": "2030-01-02T12:01:40Z",
            "validUntil": "2030-01-02T12:02:15Z",
        }
    )
    denied_path = tmp_path / "fresh-heartbeat.json"
    denied_path.write_text(json.dumps(denied_value), encoding="utf-8")
    denied = subprocess.run(
        [
            sys.executable,
            str(ENTRYPOINT),
            "evaluate-continuity",
            "--dry-run",
            "--input",
            str(denied_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert denied.returncode == 3
    assert "local-owner-heartbeat-fresh" in json.loads(denied.stdout)["reasons"]

    missing_mode = subprocess.run(
        [
            sys.executable,
            str(ENTRYPOINT),
            "evaluate-continuity",
            "--input",
            str(EXAMPLE),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_mode.returncode == 2


def test_contract_declares_standby_precedence_and_no_operational_effects() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    leader_contract = json.loads(LEADER_CONTRACT.read_text(encoding="utf-8"))

    assert contract["localPolicyMode"] == "dry-run-only"
    assert contract["defaultDecision"] == "standby"
    assert contract["localHeartbeat"]["freshHeartbeatDecision"] == "standby"
    assert contract["localOwnershipLease"]["activeLeaseDecision"] == "standby"
    assert "integrity-verified" in contract["localHeartbeat"]["requires"]
    assert "integrity-verified" in contract["localOwnershipLease"]["requires"]
    assert contract["creatorActivationMarkerPath"] == "/etc/alpecca/enable-cloud-core"
    assert "creator-activation-ready" in contract["takeoverRequiresAll"]
    assert set(contract["dryRunOutputGuarantees"]) >= {
        "never-starts-alpecca",
        "never-starts-or-enables-a-service",
        "never-reads-or-writes-a-credential",
        "never-contacts-a-network-or-provider",
        "never-performs-a-system-change",
    }
    continuity_gate = leader_contract["cloudContinuityTakeover"]
    assert continuity_gate["contract"] == CONTRACT.name
    assert continuity_gate["rawLeaderReadyIsSufficient"] is False
    assert "composite-continuity-policy-eligible" in continuity_gate["requires"]


def test_continuity_evaluator_has_no_operational_dependencies() -> None:
    source = (
        SCAFFOLD / "alpecca_ubuntu_vm" / "continuity_lease.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "import os",
        "import socket",
        "import subprocess",
        "import urllib",
        "import requests",
        "systemctl",
        "create_subprocess",
        "write_text(",
        "write_bytes(",
    ):
        assert forbidden not in source
