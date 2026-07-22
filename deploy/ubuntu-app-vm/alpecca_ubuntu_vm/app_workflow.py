"""Reviewed app proposals and receipts for the inert Ubuntu desktop lane."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .app_verifier import (
    CREATOR_PRINCIPAL,
    initial_verifier_ledger,
    normalize_catalog,
    operation_digest,
    verify_app_operation,
)
from .common import (
    InputError,
    canonical_digest,
    format_rfc3339,
    load_json,
    parse_rfc3339,
    print_json,
    require_bool,
    require_digest,
    require_exact_keys,
    require_int,
    require_object,
    require_string,
    require_string_list,
)
from .desktop_readiness import evaluate_desktop_readiness
from .supervisor import validate_fencing_epoch


SCHEMA_VERSION = 1
SCAFFOLD_ROOT = Path(__file__).resolve().parents[1]
REVIEWED_CATALOG_PATH = SCAFFOLD_ROOT / "config" / "reviewed-app-install-catalog.json"


def load_reviewed_catalog() -> dict[str, Any]:
    """Load the only catalog accepted by the repository CLI."""
    root = SCAFFOLD_ROOT.resolve()
    path = REVIEWED_CATALOG_PATH.resolve()
    if root not in path.parents:
        raise InputError("reviewed catalog escaped the Ubuntu app VM root")
    with path.open("r", encoding="utf-8") as handle:
        return normalize_catalog(json.load(handle))


def _catalog_entries(catalog_value: Any) -> tuple[str, list[dict[str, Any]]]:
    catalog = normalize_catalog(catalog_value)
    entries: list[dict[str, Any]] = []
    apt_sources = {
        item["id"]: item["source"] for item in catalog["apt"]["allowedRepositories"]
    }
    for item in catalog["apt"]["allowedPackages"]:
        if item["repository"] not in apt_sources:
            raise InputError("APT package references an unknown reviewed repository")
        entries.append(
            {
                "appId": f"apt:{item['package']}",
                "manager": "apt",
                "package": item["package"],
                "source": apt_sources[item["repository"]],
                "versions": item["versions"],
                "actions": item["actions"],
                "maxEstimatedDiskBytes": item["maxEstimatedDiskBytes"],
                "allowedPermissions": item["allowedPermissions"],
            }
        )
    flatpak_sources = {
        item["name"]: item["source"]
        for item in catalog["flatpak"]["allowedRemotes"]
    }
    for item in catalog["flatpak"]["allowedApplications"]:
        if item["remote"] not in flatpak_sources:
            raise InputError("Flatpak app references an unknown reviewed remote")
        entries.append(
            {
                "appId": f"flatpak:{item['applicationId']}",
                "manager": "flatpak",
                "package": item["applicationId"],
                "source": flatpak_sources[item["remote"]],
                "versions": item["versions"],
                "actions": item["actions"],
                "maxEstimatedDiskBytes": item["maxEstimatedDiskBytes"],
                "allowedPermissions": item["allowedPermissions"],
            }
        )
    entries.sort(key=lambda item: item["appId"])
    ids = [item["appId"] for item in entries]
    if len(ids) != len(set(ids)):
        raise InputError("reviewed app IDs must be unique")
    return canonical_digest(catalog), entries


def catalog_status(catalog_value: Any) -> dict[str, Any]:
    """Return a deterministic, non-executable view of the reviewed allowlist."""
    try:
        digest, entries = _catalog_entries(catalog_value)
    except InputError as exc:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "mode": "dry-run",
            "inputValid": False,
            "decision": "catalog-denied",
            "catalogDigest": None,
            "entries": [],
            "reasons": [f"invalid-input:{exc}"],
            "executable": False,
            "sideEffects": [],
        }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "dry-run",
        "inputValid": True,
        "decision": "catalog-reviewed",
        "defaultPolicy": "deny",
        "catalogDigest": digest,
        "entries": entries,
        "reasons": [],
        "executable": False,
        "sideEffects": [],
    }


def _normalize_fence(value: Any, field: str) -> dict[str, Any]:
    fence = require_object(value, field)
    require_exact_keys(fence, field, {"leaseId", "fencingEpoch"})
    return {
        "leaseId": require_string(fence["leaseId"], f"{field}.leaseId", identifier=True),
        "fencingEpoch": require_int(
            fence["fencingEpoch"], f"{field}.fencingEpoch", minimum=1
        ),
    }


def _proposal_denied(message: str, *, input_valid: bool = False) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "app-install-proposal",
        "mode": "dry-run",
        "inputValid": input_valid,
        "decision": "proposal-denied",
        "proposalId": None,
        "reasons": [message],
        "executable": False,
        "installPerformed": False,
        "commands": [],
        "servicesEnabled": [],
        "servicesStarted": [],
        "coreMindStarted": False,
        "sideEffects": [],
    }


def propose_install(request_value: Any, catalog_value: Any) -> dict[str, Any]:
    """Build a deterministic proposal; approval and execution remain external."""
    try:
        request = require_object(request_value, "request")
        require_exact_keys(
            request,
            "request",
            {
                "schemaVersion",
                "appId",
                "approvalId",
                "expiresAt",
                "estimatedDiskBytes",
                "requestedPermissions",
                "requiredFence",
            },
        )
        if require_int(request["schemaVersion"], "request.schemaVersion") != 1:
            raise InputError("request.schemaVersion must be 1")
        app_id = require_string(request["appId"], "request.appId", identifier=True)
        approval_id = require_string(
            request["approvalId"], "request.approvalId", identifier=True
        )
        expires_at = format_rfc3339(
            parse_rfc3339(request["expiresAt"], "request.expiresAt")
        )
        estimated_disk_bytes = require_int(
            request["estimatedDiskBytes"], "request.estimatedDiskBytes"
        )
        requested_permissions = sorted(
            require_string_list(
                request["requestedPermissions"], "request.requestedPermissions"
            )
        )
        required_fence = _normalize_fence(request["requiredFence"], "request.requiredFence")
        catalog_digest, entries = _catalog_entries(catalog_value)
    except InputError as exc:
        return _proposal_denied(f"invalid-input:{exc}")

    matches = [item for item in entries if item["appId"] == app_id]
    if len(matches) != 1:
        return _proposal_denied("app-not-allowlisted", input_valid=True)
    entry = matches[0]
    reasons: list[str] = []
    if "install" not in entry["actions"]:
        reasons.append("install-not-allowlisted")
    if len(entry["versions"]) != 1:
        reasons.append("catalog-version-is-ambiguous")
    if estimated_disk_bytes > entry["maxEstimatedDiskBytes"]:
        reasons.append("disk-estimate-exceeds-allowlist")
    if not set(requested_permissions).issubset(entry["allowedPermissions"]):
        reasons.append("permissions-not-allowlisted")
    if reasons:
        denied = _proposal_denied(reasons[0], input_valid=True)
        denied["reasons"] = reasons
        return denied

    seed = {
        "kind": "app-install-operation",
        "catalogDigest": catalog_digest,
        "appId": app_id,
        "approvalId": approval_id,
        "expiresAt": expires_at,
        "estimatedDiskBytes": estimated_disk_bytes,
        "requestedPermissions": requested_permissions,
        "requiredFence": required_fence,
    }
    operation_id = "app-op-" + canonical_digest(seed).split(":", 1)[1][:32]
    operation = {
        "schemaVersion": SCHEMA_VERSION,
        "operationId": operation_id,
        "creatorPrincipal": CREATOR_PRINCIPAL,
        "approvalLease": approval_id,
        "expiresAt": expires_at,
        "manager": entry["manager"],
        "action": "install",
        "source": entry["source"],
        "package": entry["package"],
        "version": entry["versions"][0],
        "estimatedDiskBytes": estimated_disk_bytes,
        "requestedPermissions": requested_permissions,
    }
    digest = operation_digest(operation)
    proposal_core = {
        "catalogDigest": catalog_digest,
        "appId": app_id,
        "operation": operation,
        "operationDigest": digest,
        "requiredFence": required_fence,
        "approvalRequest": {
            "approvalId": approval_id,
            "creatorPrincipal": CREATOR_PRINCIPAL,
            "externalVerifierRequired": True,
            "oneUseRequired": True,
            "operationDigest": digest,
        },
    }
    proposal_id = canonical_digest({"kind": "app-install-proposal", **proposal_core})
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "app-install-proposal",
        "mode": "dry-run",
        "inputValid": True,
        "decision": "awaiting-creator-approval",
        "proposalId": proposal_id,
        **proposal_core,
        "reasons": [],
        "executable": False,
        "installPerformed": False,
        "commands": [],
        "servicesEnabled": [],
        "servicesStarted": [],
        "coreMindStarted": False,
        "sideEffects": [],
    }


def _validate_proposal(proposal_value: Any, catalog_value: Any) -> dict[str, Any]:
    proposal = require_object(proposal_value, "workflow.proposal")
    require_exact_keys(
        proposal,
        "workflow.proposal",
        {
            "schemaVersion",
            "kind",
            "mode",
            "inputValid",
            "decision",
            "proposalId",
            "catalogDigest",
            "appId",
            "operation",
            "operationDigest",
            "requiredFence",
            "approvalRequest",
            "reasons",
            "executable",
            "installPerformed",
            "commands",
            "servicesEnabled",
            "servicesStarted",
            "coreMindStarted",
            "sideEffects",
        },
    )
    operation = require_object(proposal["operation"], "workflow.proposal.operation")
    approval_request = require_object(
        proposal["approvalRequest"], "workflow.proposal.approvalRequest"
    )
    require_exact_keys(
        approval_request,
        "workflow.proposal.approvalRequest",
        {
            "approvalId",
            "creatorPrincipal",
            "externalVerifierRequired",
            "oneUseRequired",
            "operationDigest",
        },
    )
    required_fence = _normalize_fence(
        proposal["requiredFence"], "workflow.proposal.requiredFence"
    )
    request = {
        "schemaVersion": SCHEMA_VERSION,
        "appId": require_string(proposal["appId"], "workflow.proposal.appId", identifier=True),
        "approvalId": require_string(
            approval_request["approvalId"],
            "workflow.proposal.approvalRequest.approvalId",
            identifier=True,
        ),
        "expiresAt": operation.get("expiresAt"),
        "estimatedDiskBytes": operation.get("estimatedDiskBytes"),
        "requestedPermissions": operation.get("requestedPermissions"),
        "requiredFence": required_fence,
    }
    expected = propose_install(request, catalog_value)
    if expected.get("decision") != "awaiting-creator-approval":
        raise InputError("proposal cannot be reconstructed from the reviewed catalog")
    if proposal != expected:
        raise InputError("proposal differs from its deterministic reviewed form")
    require_digest(proposal["proposalId"], "workflow.proposal.proposalId")
    return proposal


def _receipt_result(
    *,
    input_valid: bool,
    decision: str,
    reasons: list[str],
    proposal: dict[str, Any] | None,
    app_result: dict[str, Any] | None,
    fence_result: dict[str, Any] | None,
    now: str | None,
) -> dict[str, Any]:
    eligible = bool(
        input_valid
        and app_result is not None
        and app_result["decision"] in {"would-reserve", "idempotent-noop"}
        and fence_result is not None
        and fence_result["inputValid"]
        and fence_result["wouldAllowSideEffect"]
        and not reasons
    )
    receipt_id = None
    if proposal is not None and now is not None:
        receipt_id = canonical_digest(
            {
                "kind": "app-install-dry-run-receipt",
                "proposalId": proposal["proposalId"],
                "observedAt": now,
                "decision": decision,
                "reasons": reasons,
                "appDecision": app_result["decision"] if app_result else "not-evaluated",
                "fenceDecision": fence_result["decision"] if fence_result else "not-evaluated",
            }
        )
    operation = proposal["operation"] if proposal is not None else None
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "app-install-dry-run-receipt",
        "mode": "dry-run",
        "inputValid": input_valid,
        "decision": decision,
        "receiptId": receipt_id,
        "proposalId": proposal["proposalId"] if proposal else None,
        "observedAt": now,
        "creatorApprovalVerified": bool(
            app_result is not None and app_result["policyEligible"]
        ),
        "continuityFenceVerified": bool(
            fence_result is not None
            and fence_result["inputValid"]
            and fence_result["wouldAllowSideEffect"]
        ),
        "policyEligible": eligible,
        "operation": (
            {
                "operationId": operation["operationId"],
                "manager": operation["manager"],
                "package": operation["package"],
                "version": operation["version"],
                "operationDigest": proposal["operationDigest"],
            }
            if operation is not None
            else None
        ),
        "reservation": app_result["reservation"] if eligible else None,
        "proposedNextLedger": app_result["nextLedger"] if eligible else None,
        "appPolicyDecision": app_result["decision"] if app_result else "not-evaluated",
        "continuityDecision": fence_result["decision"] if fence_result else "not-evaluated",
        "reasons": reasons,
        "executorImplemented": False,
        "executable": False,
        "wouldInstall": False,
        "installPerformed": False,
        "commands": [],
        "filesWritten": [],
        "servicesEnabled": [],
        "servicesStarted": [],
        "coreMindStarted": False,
        "sideEffects": [],
    }


def create_dry_run_receipt(workflow_value: Any, catalog_value: Any) -> dict[str, Any]:
    """Verify proposal, CreatorJD approval, and exact continuity fence, without install."""
    try:
        workflow = require_object(workflow_value, "workflow")
        require_exact_keys(
            workflow,
            "workflow",
            {
                "schemaVersion",
                "now",
                "proposal",
                "approval",
                "ledger",
                "ledgerIntegrityVerified",
                "fenceCheck",
            },
        )
        if require_int(workflow["schemaVersion"], "workflow.schemaVersion") != 1:
            raise InputError("workflow.schemaVersion must be 1")
        now = format_rfc3339(parse_rfc3339(workflow["now"], "workflow.now"))
        proposal = _validate_proposal(workflow["proposal"], catalog_value)
        ledger_integrity = require_bool(
            workflow["ledgerIntegrityVerified"], "workflow.ledgerIntegrityVerified"
        )
        fence_check = require_object(workflow["fenceCheck"], "workflow.fenceCheck")
    except InputError as exc:
        return _receipt_result(
            input_valid=False,
            decision="receipt-denied",
            reasons=[f"invalid-input:{exc}"],
            proposal=None,
            app_result=None,
            fence_result=None,
            now=None,
        )

    app_result = verify_app_operation(
        operation_value=proposal["operation"],
        approval_value=workflow["approval"],
        catalog_value=catalog_value,
        ledger_value=workflow["ledger"],
        ledger_integrity_verified_value=ledger_integrity,
        now_value=now,
    )
    fence_result = validate_fencing_epoch(fence_check)
    reasons: list[str] = []
    if not app_result["inputValid"]:
        reasons.extend(f"app:{reason}" for reason in app_result["reasons"])
    elif app_result["decision"] not in {"would-reserve", "idempotent-noop"}:
        reasons.extend(f"app:{reason}" for reason in app_result["reasons"])
    if not fence_result["inputValid"] or not fence_result["wouldAllowSideEffect"]:
        reasons.extend(f"fence:{reason}" for reason in fence_result["reasons"])

    required_fence = proposal["requiredFence"]
    try:
        fence_now = format_rfc3339(
            parse_rfc3339(fence_check.get("now"), "workflow.fenceCheck.now")
        )
    except InputError:
        fence_now = None
    if fence_now != now:
        reasons.append("fence:evaluation-time-mismatch")
    supplied_lease_id = fence_check.get("leaseId")
    supplied_epoch = fence_check.get("fencingEpoch")
    if supplied_lease_id != required_fence["leaseId"]:
        reasons.append("fence:proposal-lease-id-mismatch")
    if supplied_epoch != required_fence["fencingEpoch"]:
        reasons.append("fence:proposal-epoch-mismatch")
    reasons = list(dict.fromkeys(reasons))
    input_valid = bool(app_result["inputValid"] and fence_result["inputValid"])
    if reasons:
        decision = (
            "fenced"
            if any(reason.startswith("fence:") for reason in reasons)
            else "approval-denied"
        )
    else:
        decision = "policy-eligible-dry-run"
    return _receipt_result(
        input_valid=input_valid,
        decision=decision,
        reasons=reasons,
        proposal=proposal,
        app_result=app_result,
        fence_result=fence_result,
        now=now,
    )


def _cli_error(message: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "dry-run",
        "inputValid": False,
        "decision": "input-denied",
        "reasons": [f"input-read-failed:{message}"],
        "executable": False,
        "sideEffects": [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect the reviewed app VM workflow without changing the VM."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("catalog", "propose", "receipt", "desktop-status"):
        item = subparsers.add_parser(command)
        item.add_argument("--dry-run", action="store_true", required=True)
        if command != "catalog":
            item.add_argument("--input", required=True, help="JSON path or - for stdin")
    args = parser.parse_args(argv)

    try:
        if args.command == "desktop-status":
            result = evaluate_desktop_readiness(load_json(args.input))
        else:
            catalog = load_reviewed_catalog()
            if args.command == "catalog":
                result = catalog_status(catalog)
            elif args.command == "propose":
                result = propose_install(load_json(args.input), catalog)
            else:
                result = create_dry_run_receipt(load_json(args.input), catalog)
    except (OSError, json.JSONDecodeError, InputError) as exc:
        print_json(_cli_error(type(exc).__name__))
        return 2

    print_json(result)
    if not result["inputValid"]:
        return 2
    if args.command == "catalog":
        return 0
    if args.command == "propose":
        return 0 if result["decision"] == "awaiting-creator-approval" else 3
    if args.command == "receipt":
        return 0 if result["policyEligible"] else 3
    return 0 if result["desktopPhoneReady"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
