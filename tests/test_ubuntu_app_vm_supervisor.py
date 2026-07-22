"""Behavioral tests for the inert Ubuntu single-leader supervisor policy."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "deploy" / "ubuntu-app-vm"
sys.path.insert(0, str(SCAFFOLD))

from alpecca_ubuntu_vm.supervisor import (  # noqa: E402
    evaluate_supervisor,
    initial_supervisor_state,
    validate_fencing_epoch,
)


NOW = "2030-01-02T12:00:00Z"


def _observation() -> dict:
    return {
        "schemaVersion": 1,
        "nodeId": "ubuntu-standby-1",
        "now": NOW,
        "stateIntegrityVerified": True,
        "authority": {
            "available": True,
            "linearizable": True,
            "grantAuthenticated": True,
            "primaryGraceElapsed": True,
        },
        "vault": {
            "ready": True,
            "latestSnapshotVerified": True,
            "restoreCompleted": True,
            "snapshotId": "snapshot-006",
            "snapshotFencingEpoch": 6,
            "verifiedAt": "2030-01-02T11:59:49Z",
        },
        "lease": {
            "schemaVersion": 1,
            "leaseId": "lease-007",
            "holderNodeId": "ubuntu-standby-1",
            "fencingEpoch": 7,
            "issuedAt": "2030-01-02T11:59:50Z",
            "expiresAt": "2030-01-02T12:00:25Z",
        },
        "state": {**initial_supervisor_state(), "highestFencingEpoch": 6},
    }


def _leader_state() -> dict:
    result = evaluate_supervisor(_observation())
    assert result["decision"] == "leader-ready"
    return result["nextState"]


def test_valid_grant_requires_every_gate_and_does_not_mutate_input() -> None:
    observation = _observation()
    original = copy.deepcopy(observation)

    result = evaluate_supervisor(observation)

    assert observation == original
    assert result["inputValid"] is True
    assert result["decision"] == "leader-ready"
    assert result["wouldLead"] is True
    assert result["executable"] is False
    assert result["sideEffects"] == []
    assert result["nextState"]["highestFencingEpoch"] == 7
    assert result["nextState"]["activeLease"]["leaseId"] == "lease-007"
    assert result["nextState"]["vaultSnapshotId"] == "snapshot-006"


def test_same_grant_is_idempotent_and_renewal_cannot_regress() -> None:
    first = evaluate_supervisor(_observation())
    replay = _observation()
    replay["state"] = first["nextState"]

    repeated = evaluate_supervisor(replay)

    assert repeated["decision"] == "leader-ready"
    assert repeated["idempotent"] is True
    assert repeated["decisionId"] == first["decisionId"]

    regressed = copy.deepcopy(replay)
    regressed["now"] = "2030-01-02T12:00:01Z"
    regressed["lease"]["expiresAt"] = "2030-01-02T12:00:24Z"
    denied = evaluate_supervisor(regressed)
    assert denied["decision"] == "fenced"
    assert "lease-expiry-regression" in denied["reasons"]


def test_one_grant_cannot_make_two_nodes_leader_ready() -> None:
    intended = evaluate_supervisor(_observation())
    other_node = _observation()
    other_node["nodeId"] = "ubuntu-standby-2"

    rejected = evaluate_supervisor(other_node)

    assert intended["wouldLead"] is True
    assert rejected["wouldLead"] is False
    assert "lease-held-by-different-node" in rejected["reasons"]


@pytest.mark.parametrize(
    ("section", "field", "value", "reason"),
    [
        ("authority", "available", False, "authority-unavailable"),
        ("authority", "linearizable", False, "authority-not-linearizable"),
        ("authority", "grantAuthenticated", False, "grant-unauthenticated"),
        ("authority", "primaryGraceElapsed", False, "primary-grace-not-elapsed"),
        ("vault", "ready", False, "vault-not-ready"),
        (
            "vault",
            "latestSnapshotVerified",
            False,
            "latest-vault-snapshot-unverified",
        ),
        ("vault", "restoreCompleted", False, "vault-restore-incomplete"),
    ],
)
def test_each_authority_and_vault_gate_fails_closed(
    section: str, field: str, value: bool, reason: str
) -> None:
    observation = _observation()
    observation[section][field] = value

    result = evaluate_supervisor(observation)

    assert result["decision"] == "fenced"
    assert result["wouldLead"] is False
    assert result["nextState"]["activeLease"] is None
    assert reason in result["reasons"]


def test_expiry_clock_rollback_and_long_lease_fail_closed() -> None:
    expired = _observation()
    expired["now"] = expired["lease"]["expiresAt"]
    assert "lease-expired" in evaluate_supervisor(expired)["reasons"]

    rollback = _observation()
    rollback["state"]["lastEvaluatedAt"] = "2030-01-02T12:00:01Z"
    assert "clock-rollback" in evaluate_supervisor(rollback)["reasons"]

    long_lease = _observation()
    long_lease["lease"]["expiresAt"] = "2030-01-02T12:00:26Z"
    assert "lease-duration-exceeds-policy" in evaluate_supervisor(long_lease)["reasons"]


def test_higher_epoch_fences_delayed_old_actions() -> None:
    first = evaluate_supervisor(_observation())
    next_grant = _observation()
    next_grant["now"] = "2030-01-02T12:00:05Z"
    next_grant["state"] = first["nextState"]
    next_grant["lease"] = {
        "schemaVersion": 1,
        "leaseId": "lease-008",
        "holderNodeId": "ubuntu-standby-1",
        "fencingEpoch": 8,
        "issuedAt": "2030-01-02T12:00:01Z",
        "expiresAt": "2030-01-02T12:00:35Z",
    }

    advanced = evaluate_supervisor(next_grant)
    stale_check = {
        "schemaVersion": 1,
        "now": "2030-01-02T12:00:06Z",
        "stateIntegrityVerified": True,
        "state": advanced["nextState"],
        "leaseId": "lease-007",
        "fencingEpoch": 7,
    }

    assert advanced["decision"] == "leader-ready"
    assert advanced["nextState"]["highestFencingEpoch"] == 8
    rejected = validate_fencing_epoch(stale_check)
    assert rejected["decision"] == "deny-fence"
    assert "stale-fencing-epoch" in rejected["reasons"]
    assert rejected["executable"] is False


@pytest.mark.parametrize(
    ("lease_id", "epoch", "now", "reason"),
    [
        ("lease-007", 6, "2030-01-02T12:00:01Z", "stale-fencing-epoch"),
        ("lease-007", 8, "2030-01-02T12:00:01Z", "unknown-fencing-epoch"),
        ("wrong-lease", 7, "2030-01-02T12:00:01Z", "lease-id-mismatch"),
        ("lease-007", 7, "2030-01-02T12:00:25Z", "lease-expired"),
    ],
)
def test_fence_validation_rejects_any_non_exact_active_lease(
    lease_id: str, epoch: int, now: str, reason: str
) -> None:
    check = {
        "schemaVersion": 1,
        "now": now,
        "stateIntegrityVerified": True,
        "state": _leader_state(),
        "leaseId": lease_id,
        "fencingEpoch": epoch,
    }
    result = validate_fencing_epoch(check)
    assert result["wouldAllowSideEffect"] is False
    assert reason in result["reasons"]


def test_exact_unexpired_fence_is_policy_eligible_but_never_executable() -> None:
    check = {
        "schemaVersion": 1,
        "now": "2030-01-02T12:00:01Z",
        "stateIntegrityVerified": True,
        "state": _leader_state(),
        "leaseId": "lease-007",
        "fencingEpoch": 7,
    }
    result = validate_fencing_epoch(check)
    assert result["decision"] == "allow-fence"
    assert result["wouldAllowSideEffect"] is True
    assert result["executable"] is False
    assert result["sideEffects"] == []


def test_malformed_or_untrusted_state_is_never_reconstructed_as_leader() -> None:
    malformed = _observation()
    malformed["state"].pop("highestFencingEpoch")
    invalid = evaluate_supervisor(malformed)
    assert invalid["inputValid"] is False
    assert invalid["decision"] == "fenced"
    assert invalid["nextState"]["highestFencingEpoch"] == 0

    untrusted = _observation()
    untrusted["stateIntegrityVerified"] = False
    denied = evaluate_supervisor(untrusted)
    assert "state-integrity-unverified" in denied["reasons"]
    assert denied["wouldLead"] is False


def test_supervisor_cli_requires_dry_run_and_returns_only_json_decisions(tmp_path: Path) -> None:
    input_path = tmp_path / "observation.json"
    input_path.write_text(json.dumps(_observation()), encoding="utf-8")
    entrypoint = SCAFFOLD / "bin" / "alpecca-cloud-supervisor"

    completed = subprocess.run(
        [sys.executable, str(entrypoint), "evaluate", "--dry-run", "--input", str(input_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    result = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert result["decision"] == "leader-ready"
    assert result["executable"] is False
    assert result["sideEffects"] == []

    missing_mode = subprocess.run(
        [sys.executable, str(entrypoint), "evaluate", "--input", str(input_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_mode.returncode == 2


def test_documented_supervisor_example_remains_runnable() -> None:
    example = json.loads(
        (SCAFFOLD / "contracts" / "supervisor-observation.example.json").read_text(
            encoding="utf-8"
        )
    )
    result = evaluate_supervisor(example)
    assert result["decision"] == "leader-ready"
    assert result["executable"] is False

    fence_example = json.loads(
        (SCAFFOLD / "contracts" / "fence-check.example.json").read_text(
            encoding="utf-8"
        )
    )
    fence_result = validate_fencing_epoch(fence_example)
    assert fence_result["decision"] == "allow-fence"
    assert fence_result["executable"] is False
