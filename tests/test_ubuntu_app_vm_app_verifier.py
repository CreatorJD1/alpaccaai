"""Tests for creator-approved, allowlisted, dry-run app-operation policy."""
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

from alpecca_ubuntu_vm.app_verifier import (  # noqa: E402
    initial_verifier_ledger,
    operation_digest,
    verify_app_operation,
)


NOW = "2030-01-02T12:00:00Z"


def _operation() -> dict:
    return {
        "schemaVersion": 1,
        "operationId": "op-gimp-001",
        "creatorPrincipal": "CreatorJD",
        "approvalLease": "approval-001",
        "expiresAt": "2030-01-02T12:10:00Z",
        "manager": "flatpak",
        "action": "install",
        "source": "https://example.invalid/flathub.flatpakrepo",
        "package": "org.gimp.GIMP",
        "version": "3.0.4",
        "estimatedDiskBytes": 800_000_000,
        "requestedPermissions": ["ipc", "network"],
    }


def _approval(operation: dict | None = None) -> dict:
    bound_operation = _operation() if operation is None else operation
    return {
        "schemaVersion": 1,
        "approvalId": bound_operation["approvalLease"],
        "operationId": bound_operation["operationId"],
        "creatorPrincipal": "CreatorJD",
        "operationDigest": operation_digest(bound_operation),
        "issuedAt": "2030-01-02T11:59:00Z",
        "expiresAt": "2030-01-02T12:05:00Z",
        "oneUse": True,
        "verification": {
            "status": "verified",
            "verifier": "external-creator-verifier",
            "evidenceId": "creator-evidence-001",
        },
    }


def _catalog() -> dict:
    return {
        "schemaVersion": 1,
        "defaultPolicy": "deny",
        "apt": {"allowedRepositories": [], "allowedPackages": []},
        "flatpak": {
            "allowedRemotes": [
                {
                    "name": "flathub-reviewed",
                    "source": "https://example.invalid/flathub.flatpakrepo",
                }
            ],
            "allowedApplications": [
                {
                    "applicationId": "org.gimp.GIMP",
                    "remote": "flathub-reviewed",
                    "versions": ["3.0.4"],
                    "actions": ["install", "update", "disable", "remove"],
                    "maxEstimatedDiskBytes": 900_000_000,
                    "allowedPermissions": ["ipc", "network"],
                }
            ],
        },
    }


def _verify(
    operation: dict | None = None,
    approval: dict | None = None,
    catalog: dict | None = None,
    ledger: dict | None = None,
    ledger_integrity_verified: bool = True,
    now: str = NOW,
) -> dict:
    selected_operation = _operation() if operation is None else operation
    return verify_app_operation(
        operation_value=selected_operation,
        approval_value=_approval(selected_operation) if approval is None else approval,
        catalog_value=_catalog() if catalog is None else catalog,
        ledger_value=initial_verifier_ledger() if ledger is None else ledger,
        ledger_integrity_verified_value=ledger_integrity_verified,
        now_value=now,
    )


def test_exact_creator_approval_and_allowlist_emit_only_a_dry_run_reservation() -> None:
    operation = _operation()
    approval = _approval(operation)
    catalog = _catalog()
    ledger = initial_verifier_ledger()
    originals = copy.deepcopy((operation, approval, catalog, ledger))

    result = _verify(operation, approval, catalog, ledger)

    assert (operation, approval, catalog, ledger) == originals
    assert result["decision"] == "would-reserve"
    assert result["policyEligible"] is True
    assert result["wouldReserve"] is True
    assert result["executable"] is False
    assert result["commands"] == []
    assert result["servicesStarted"] == []
    assert result["filesWritten"] == []
    assert result["reservation"]["reservationId"].startswith("dry-run:sha256:")
    assert result["nextLedger"]["operations"][operation["operationId"]]["status"] == "reserved"


def test_replay_is_an_idempotent_noop_even_after_approval_expiry() -> None:
    first = _verify()
    replay = _verify(ledger=first["nextLedger"], now="2030-01-02T12:06:00Z")

    assert replay["decision"] == "idempotent-noop"
    assert replay["idempotent"] is True
    assert replay["wouldReserve"] is False
    assert replay["nextLedger"] == first["nextLedger"]
    assert replay["executable"] is False


def test_idempotent_replay_still_requires_a_trusted_verifier_verdict() -> None:
    first = _verify()
    operation = _operation()
    approval = _approval(operation)
    approval["verification"]["status"] = "unverified"

    replay = _verify(operation=operation, approval=approval, ledger=first["nextLedger"])

    assert replay["decision"] == "deny"
    assert "creator-approval-unverified" in replay["reasons"]
    assert replay["idempotent"] is False


def test_unverified_idempotency_ledger_fails_closed_for_new_and_replayed_requests() -> None:
    denied_new = _verify(ledger_integrity_verified=False)
    assert denied_new["decision"] == "deny"
    assert "ledger-integrity-unverified" in denied_new["reasons"]

    first = _verify()
    denied_replay = _verify(
        ledger=first["nextLedger"], ledger_integrity_verified=False
    )
    assert denied_replay["decision"] == "deny"
    assert "ledger-integrity-unverified" in denied_replay["reasons"]
    assert denied_replay["idempotent"] is False


def test_operation_id_conflict_and_approval_reuse_fail_closed() -> None:
    first = _verify()

    changed = _operation()
    changed["version"] = "3.0.5"
    changed_catalog = _catalog()
    changed_catalog["flatpak"]["allowedApplications"][0]["versions"].append("3.0.5")
    conflict = _verify(
        operation=changed,
        approval=_approval(changed),
        catalog=changed_catalog,
        ledger=first["nextLedger"],
    )
    assert conflict["decision"] == "deny"
    assert "operation-id-conflict" in conflict["reasons"]

    second = _operation()
    second["operationId"] = "op-gimp-002"
    reused = _verify(
        operation=second,
        approval=_approval(second),
        ledger=first["nextLedger"],
    )
    assert reused["decision"] == "deny"
    assert "approval-already-consumed" in reused["reasons"]


@pytest.mark.parametrize(
    ("target", "value", "reason"),
    [
        ("source", "https://unreviewed.invalid/repo", "source-not-allowlisted"),
        ("package", "org.unknown.App", "package-not-allowlisted"),
        ("version", "9.9.9", "version-not-allowlisted"),
        ("action", "update", "action-not-allowlisted"),
        ("estimatedDiskBytes", 900_000_001, "disk-estimate-exceeds-allowlist"),
        ("requestedPermissions", ["ipc", "host"], "permissions-not-allowlisted"),
    ],
)
def test_every_allowlist_dimension_is_exact(target: str, value: object, reason: str) -> None:
    operation = _operation()
    operation[target] = value
    catalog = _catalog()
    if target == "action":
        catalog["flatpak"]["allowedApplications"][0]["actions"] = ["install"]

    result = _verify(operation=operation, approval=_approval(operation), catalog=catalog)

    assert result["decision"] == "deny"
    assert reason in result["reasons"]
    assert result["nextLedger"] == initial_verifier_ledger()


def test_empty_catalog_is_deny_by_default() -> None:
    catalog = {
        "schemaVersion": 1,
        "defaultPolicy": "deny",
        "apt": {"allowedRepositories": [], "allowedPackages": []},
        "flatpak": {"allowedRemotes": [], "allowedApplications": []},
    }
    result = _verify(catalog=catalog)
    assert result["decision"] == "deny"
    assert "source-not-allowlisted" in result["reasons"]


@pytest.mark.parametrize(
    ("mutator", "now", "reason"),
    [
        (lambda approval: approval.update(operationDigest="sha256:" + "0" * 64), NOW, "approval-digest-mismatch"),
        (lambda approval: approval.update(creatorPrincipal="SomeoneElse"), NOW, "approval-creator-mismatch"),
        (lambda approval: approval.update(oneUse=False), NOW, "approval-not-one-use"),
        (
            lambda approval: approval["verification"].update(status="unverified"),
            NOW,
            "creator-approval-unverified",
        ),
        (
            lambda approval: approval["verification"].update(verifier="unknown-verifier"),
            NOW,
            "creator-verifier-not-trusted",
        ),
        (lambda approval: None, "2030-01-02T12:05:00Z", "approval-expired"),
    ],
)
def test_approval_binding_and_expiry_fail_closed(mutator, now: str, reason: str) -> None:
    operation = _operation()
    approval = _approval(operation)
    mutator(approval)
    result = _verify(operation=operation, approval=approval, now=now)
    assert result["decision"] == "deny"
    assert reason in result["reasons"]
    assert result["executable"] is False


def test_operation_digest_is_stable_for_permission_order_but_binds_disclosure() -> None:
    first = _operation()
    reordered = copy.deepcopy(first)
    reordered["requestedPermissions"] = list(reversed(first["requestedPermissions"]))
    assert operation_digest(first) == operation_digest(reordered)

    changed = copy.deepcopy(first)
    changed["estimatedDiskBytes"] += 1
    assert operation_digest(first) != operation_digest(changed)


def test_malformed_catalog_or_ledger_is_invalid_and_cannot_reserve() -> None:
    malformed_catalog = _catalog()
    malformed_catalog["defaultPolicy"] = "allow"
    denied_catalog = _verify(catalog=malformed_catalog)
    assert denied_catalog["inputValid"] is False
    assert denied_catalog["nextLedger"] is None

    malformed_ledger = initial_verifier_ledger()
    malformed_ledger["operations"]["orphan"] = {
        "operationDigest": "sha256:" + "0" * 64,
        "approvalId": "missing",
        "status": "reserved",
        "reservationId": "sha256:" + "1" * 64,
    }
    denied_ledger = _verify(ledger=malformed_ledger)
    assert denied_ledger["inputValid"] is False
    assert denied_ledger["executable"] is False


def test_app_verifier_cli_requires_dry_run_and_never_returns_a_command(tmp_path: Path) -> None:
    operation = _operation()
    payload = {
        "schemaVersion": 1,
        "now": NOW,
        "operation": operation,
        "approval": _approval(operation),
        "catalog": _catalog(),
        "ledger": initial_verifier_ledger(),
        "ledgerIntegrityVerified": True,
    }
    input_path = tmp_path / "verification.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    entrypoint = SCAFFOLD / "bin" / "verify-app-approval"

    completed = subprocess.run(
        [sys.executable, str(entrypoint), "verify", "--dry-run", "--input", str(input_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    result = json.loads(completed.stdout)
    assert completed.returncode == 0
    assert result["decision"] == "would-reserve"
    assert result["executable"] is False
    assert result["commands"] == []

    missing_mode = subprocess.run(
        [sys.executable, str(entrypoint), "verify", "--input", str(input_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_mode.returncode == 2


def test_documented_app_verification_example_remains_runnable() -> None:
    payload = json.loads(
        (SCAFFOLD / "contracts" / "app-verification.example.json").read_text(
            encoding="utf-8"
        )
    )
    result = verify_app_operation(
        operation_value=payload["operation"],
        approval_value=payload["approval"],
        catalog_value=payload["catalog"],
        ledger_value=payload["ledger"],
        ledger_integrity_verified_value=payload["ledgerIntegrityVerified"],
        now_value=payload["now"],
    )
    assert result["decision"] == "would-reserve"
    assert result["reservation"]["reservationId"].startswith("dry-run:")
    assert result["executable"] is False
