"""Focused tests for the inert app catalog, proposal, and receipt workflow."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCAFFOLD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCAFFOLD))

from alpecca_ubuntu_vm.app_verifier import initial_verifier_ledger  # noqa: E402
from alpecca_ubuntu_vm.app_workflow import (  # noqa: E402
    catalog_status,
    create_dry_run_receipt,
    load_reviewed_catalog,
    propose_install,
)


REQUEST_PATH = SCAFFOLD / "contracts" / "app-proposal-request.example.json"
FENCE_PATH = SCAFFOLD / "contracts" / "fence-check.example.json"
ENTRYPOINT = SCAFFOLD / "bin" / "alpecca-app-workflow"
NOW = "2030-01-02T12:00:01Z"


def _request() -> dict:
    return json.loads(REQUEST_PATH.read_text(encoding="utf-8"))


def _proposal() -> dict:
    return propose_install(_request(), load_reviewed_catalog())


def _approval(
    proposal: dict,
    *,
    creator: str = "CreatorJD",
    status: str = "verified",
) -> dict:
    return {
        "schemaVersion": 1,
        "approvalId": proposal["approvalRequest"]["approvalId"],
        "operationId": proposal["operation"]["operationId"],
        "creatorPrincipal": creator,
        "operationDigest": proposal["operationDigest"],
        "issuedAt": "2030-01-02T11:59:00Z",
        "expiresAt": "2030-01-02T12:05:00Z",
        "oneUse": True,
        "verification": {
            "status": status,
            "verifier": "external-creator-verifier",
            "evidenceId": "creator-device-evidence-043",
        },
    }


def _workflow(*, proposal: dict | None = None, approval: dict | None = None) -> dict:
    proposal = proposal or _proposal()
    return {
        "schemaVersion": 1,
        "now": NOW,
        "proposal": proposal,
        "approval": approval or _approval(proposal),
        "ledger": initial_verifier_ledger(),
        "ledgerIntegrityVerified": True,
        "fenceCheck": json.loads(FENCE_PATH.read_text(encoding="utf-8")),
    }


def test_reviewed_catalog_is_nonempty_sorted_and_deny_by_default() -> None:
    first = catalog_status(load_reviewed_catalog())
    second = catalog_status(load_reviewed_catalog())

    assert first == second
    assert first["decision"] == "catalog-reviewed"
    assert first["defaultPolicy"] == "deny"
    assert [item["appId"] for item in first["entries"]] == sorted(
        item["appId"] for item in first["entries"]
    )
    assert {item["manager"] for item in first["entries"]} == {"apt", "flatpak"}
    assert all(item["actions"] == ["install"] for item in first["entries"])
    assert first["executable"] is False


def test_proposal_is_stable_fence_bound_and_non_executable() -> None:
    request = _request()
    original = copy.deepcopy(request)
    first = propose_install(request, load_reviewed_catalog())
    repeated = propose_install(request, load_reviewed_catalog())

    assert request == original
    assert first == repeated
    assert first["decision"] == "awaiting-creator-approval"
    assert first["requiredFence"] == {"leaseId": "lease-042", "fencingEpoch": 42}
    assert first["approvalRequest"]["creatorPrincipal"] == "CreatorJD"
    assert first["approvalRequest"]["operationDigest"] == first["operationDigest"]
    assert first["operation"]["operationId"].startswith("app-op-")
    assert first["executable"] is False
    assert first["installPerformed"] is False
    assert first["commands"] == []
    assert first["servicesEnabled"] == []
    assert first["servicesStarted"] == []
    assert first["coreMindStarted"] is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("appId", "apt:not-reviewed", "app-not-allowlisted"),
        ("estimatedDiskBytes", 1_500_000_001, "disk-estimate-exceeds-allowlist"),
        ("requestedPermissions", ["host"], "permissions-not-allowlisted"),
    ],
)
def test_proposal_rejects_any_request_outside_the_exact_catalog(
    field: str, value: object, reason: str
) -> None:
    request = _request()
    request[field] = value
    result = propose_install(request, load_reviewed_catalog())
    assert result["decision"] == "proposal-denied"
    assert reason in result["reasons"]
    assert result["executable"] is False


def test_receipt_requires_approval_and_exact_active_fence_but_never_installs() -> None:
    result = create_dry_run_receipt(_workflow(), load_reviewed_catalog())

    assert result["decision"] == "policy-eligible-dry-run"
    assert result["creatorApprovalVerified"] is True
    assert result["continuityFenceVerified"] is True
    assert result["policyEligible"] is True
    assert result["reservation"]["reservationId"].startswith("dry-run:")
    assert result["proposedNextLedger"] is not None
    assert result["executorImplemented"] is False
    assert result["executable"] is False
    assert result["wouldInstall"] is False
    assert result["installPerformed"] is False
    assert result["commands"] == []
    assert result["filesWritten"] == []
    assert result["servicesEnabled"] == []
    assert result["servicesStarted"] == []
    assert result["coreMindStarted"] is False
    assert result["sideEffects"] == []


@pytest.mark.parametrize(
    ("creator", "status", "reason"),
    [
        ("SomeoneElse", "verified", "app:approval-creator-mismatch"),
        ("CreatorJD", "unverified", "app:creator-approval-unverified"),
    ],
)
def test_receipt_fails_closed_without_verified_creatorjd_approval(
    creator: str, status: str, reason: str
) -> None:
    proposal = _proposal()
    workflow = _workflow(
        proposal=proposal,
        approval=_approval(proposal, creator=creator, status=status),
    )
    result = create_dry_run_receipt(workflow, load_reviewed_catalog())

    assert result["decision"] == "approval-denied"
    assert reason in result["reasons"]
    assert result["policyEligible"] is False
    assert result["reservation"] is None
    assert result["proposedNextLedger"] is None
    assert result["installPerformed"] is False


def test_receipt_rejects_expired_or_mismatched_fence() -> None:
    workflow = _workflow()
    workflow["now"] = "2030-01-02T12:00:25Z"
    workflow["fenceCheck"]["now"] = workflow["now"]
    expired = create_dry_run_receipt(workflow, load_reviewed_catalog())
    assert expired["decision"] == "fenced"
    assert "fence:lease-expired" in expired["reasons"]
    assert expired["policyEligible"] is False

    workflow = _workflow()
    workflow["fenceCheck"]["leaseId"] = "different-lease"
    mismatched = create_dry_run_receipt(workflow, load_reviewed_catalog())
    assert mismatched["decision"] == "fenced"
    assert "fence:proposal-lease-id-mismatch" in mismatched["reasons"]
    assert mismatched["proposedNextLedger"] is None


def test_receipt_rejects_tampered_proposal_and_mixed_time_evidence() -> None:
    workflow = _workflow()
    workflow["proposal"]["operation"]["package"] = "org.unknown.App"
    tampered = create_dry_run_receipt(workflow, load_reviewed_catalog())
    assert tampered["inputValid"] is False
    assert tampered["decision"] == "receipt-denied"

    workflow = _workflow()
    workflow["fenceCheck"]["now"] = "2030-01-02T12:00:02Z"
    mixed_time = create_dry_run_receipt(workflow, load_reviewed_catalog())
    assert mixed_time["decision"] == "fenced"
    assert "fence:evaluation-time-mismatch" in mixed_time["reasons"]


def test_cli_is_locked_to_dry_run_and_the_reviewed_catalog(tmp_path: Path) -> None:
    catalog = subprocess.run(
        [sys.executable, str(ENTRYPOINT), "catalog", "--dry-run"],
        cwd=SCAFFOLD,
        capture_output=True,
        text=True,
        check=False,
    )
    assert catalog.returncode == 0
    assert json.loads(catalog.stdout)["decision"] == "catalog-reviewed"

    proposal = subprocess.run(
        [
            sys.executable,
            str(ENTRYPOINT),
            "propose",
            "--dry-run",
            "--input",
            str(REQUEST_PATH),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proposal.returncode == 0
    assert json.loads(proposal.stdout)["decision"] == "awaiting-creator-approval"

    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(json.dumps(_workflow()), encoding="utf-8")
    receipt = subprocess.run(
        [
            sys.executable,
            str(ENTRYPOINT),
            "receipt",
            "--dry-run",
            "--input",
            str(workflow_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    receipt_result = json.loads(receipt.stdout)
    assert receipt.returncode == 0
    assert receipt_result["decision"] == "policy-eligible-dry-run"
    assert receipt_result["installPerformed"] is False

    desktop = subprocess.run(
        [
            sys.executable,
            str(ENTRYPOINT),
            "desktop-status",
            "--dry-run",
            "--input",
            str(SCAFFOLD / "contracts" / "desktop-readiness.example.json"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert desktop.returncode == 0
    assert json.loads(desktop.stdout)["status"] == "phone-ready-fenced"

    missing_mode = subprocess.run(
        [sys.executable, str(ENTRYPOINT), "catalog"],
        cwd=SCAFFOLD,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_mode.returncode == 2


def test_workflow_source_has_no_installer_or_service_control_dependency() -> None:
    sources = "\n".join(
        (SCAFFOLD / "alpecca_ubuntu_vm" / name).read_text(encoding="utf-8")
        for name in ("app_workflow.py", "desktop_readiness.py")
    )
    for forbidden in (
        "import os",
        "import socket",
        "import subprocess",
        "import urllib",
        "import requests",
        "systemctl",
        "apt-get",
        "flatpak install",
        "create_subprocess",
        "write_text(",
        "write_bytes(",
    ):
        assert forbidden not in sources
