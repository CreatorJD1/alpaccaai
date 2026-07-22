"""Creator-approval and app-catalog policy checks with dry-run idempotency."""
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
    require_digest,
    require_exact_keys,
    require_int,
    require_object,
    require_string,
    require_string_list,
)


SCHEMA_VERSION = 1
CREATOR_PRINCIPAL = "CreatorJD"
EXTERNAL_VERIFIER = "external-creator-verifier"
SUPPORTED_MANAGERS = frozenset({"apt", "flatpak"})
SUPPORTED_ACTIONS = frozenset({"install", "update", "disable", "remove"})

OPERATION_KEYS = {
    "schemaVersion",
    "operationId",
    "creatorPrincipal",
    "approvalLease",
    "expiresAt",
    "manager",
    "action",
    "source",
    "package",
    "version",
    "estimatedDiskBytes",
    "requestedPermissions",
}
APPROVAL_KEYS = {
    "schemaVersion",
    "approvalId",
    "operationId",
    "creatorPrincipal",
    "operationDigest",
    "issuedAt",
    "expiresAt",
    "oneUse",
    "verification",
}
VERIFICATION_KEYS = {"status", "verifier", "evidenceId"}


def initial_verifier_ledger() -> dict[str, Any]:
    """Return an empty ledger for a future atomic, separately trusted store."""
    return {"schemaVersion": SCHEMA_VERSION, "operations": {}, "consumedApprovals": {}}


def _normalize_operation(value: Any) -> tuple[dict[str, Any], datetime]:
    operation = require_object(value, "operation")
    require_exact_keys(operation, "operation", OPERATION_KEYS)
    if require_int(operation["schemaVersion"], "operation.schemaVersion") != 1:
        raise InputError("operation.schemaVersion must be 1")
    expires_at = parse_rfc3339(operation["expiresAt"], "operation.expiresAt")
    normalized = {
        "schemaVersion": SCHEMA_VERSION,
        "operationId": require_string(
            operation["operationId"], "operation.operationId", identifier=True
        ),
        "creatorPrincipal": require_string(
            operation["creatorPrincipal"], "operation.creatorPrincipal", identifier=True
        ),
        "approvalLease": require_string(
            operation["approvalLease"], "operation.approvalLease", identifier=True
        ),
        "expiresAt": format_rfc3339(expires_at),
        "manager": require_string(operation["manager"], "operation.manager"),
        "action": require_string(operation["action"], "operation.action"),
        "source": require_string(operation["source"], "operation.source"),
        "package": require_string(operation["package"], "operation.package"),
        "version": require_string(operation["version"], "operation.version"),
        "estimatedDiskBytes": require_int(
            operation["estimatedDiskBytes"], "operation.estimatedDiskBytes"
        ),
        "requestedPermissions": sorted(
            require_string_list(
                operation["requestedPermissions"], "operation.requestedPermissions"
            )
        ),
    }
    return normalized, expires_at


def operation_digest(operation_value: Any) -> str:
    """Bind every disclosed operation field using deterministic JSON."""
    operation, _ = _normalize_operation(operation_value)
    return canonical_digest(operation)


def _normalize_approval(value: Any) -> tuple[dict[str, Any], datetime, datetime]:
    approval = require_object(value, "approval")
    require_exact_keys(approval, "approval", APPROVAL_KEYS)
    if require_int(approval["schemaVersion"], "approval.schemaVersion") != 1:
        raise InputError("approval.schemaVersion must be 1")
    issued_at = parse_rfc3339(approval["issuedAt"], "approval.issuedAt")
    expires_at = parse_rfc3339(approval["expiresAt"], "approval.expiresAt")
    if expires_at <= issued_at:
        raise InputError("approval.expiresAt must be after approval.issuedAt")

    verification = require_object(approval["verification"], "approval.verification")
    require_exact_keys(verification, "approval.verification", VERIFICATION_KEYS)
    normalized = {
        "schemaVersion": SCHEMA_VERSION,
        "approvalId": require_string(
            approval["approvalId"], "approval.approvalId", identifier=True
        ),
        "operationId": require_string(
            approval["operationId"], "approval.operationId", identifier=True
        ),
        "creatorPrincipal": require_string(
            approval["creatorPrincipal"], "approval.creatorPrincipal", identifier=True
        ),
        "operationDigest": require_digest(
            approval["operationDigest"], "approval.operationDigest"
        ),
        "issuedAt": format_rfc3339(issued_at),
        "expiresAt": format_rfc3339(expires_at),
        "oneUse": require_bool(approval["oneUse"], "approval.oneUse"),
        "verification": {
            "status": require_string(
                verification["status"], "approval.verification.status"
            ),
            "verifier": require_string(
                verification["verifier"], "approval.verification.verifier"
            ),
            "evidenceId": require_string(
                verification["evidenceId"],
                "approval.verification.evidenceId",
                identifier=True,
            ),
        },
    }
    return normalized, issued_at, expires_at


def _normalize_source_entries(
    value: Any, field: str, *, name_key: str
) -> list[dict[str, str]]:
    if type(value) is not list:
        raise InputError(f"{field} must be an array")
    result: list[dict[str, str]] = []
    for index, item_value in enumerate(value):
        item_field = f"{field}[{index}]"
        item = require_object(item_value, item_field)
        require_exact_keys(item, item_field, {name_key, "source"})
        result.append(
            {
                name_key: require_string(item[name_key], f"{item_field}.{name_key}"),
                "source": require_string(item["source"], f"{item_field}.source"),
            }
        )
    names = [item[name_key] for item in result]
    sources = [item["source"] for item in result]
    if len(names) != len(set(names)) or len(sources) != len(set(sources)):
        raise InputError(f"{field} must have unique names and sources")
    return result


def _normalize_app_entries(
    value: Any,
    field: str,
    *,
    package_key: str,
    source_ref_key: str,
) -> list[dict[str, Any]]:
    if type(value) is not list:
        raise InputError(f"{field} must be an array")
    result: list[dict[str, Any]] = []
    required_keys = {
        package_key,
        source_ref_key,
        "versions",
        "actions",
        "maxEstimatedDiskBytes",
        "allowedPermissions",
    }
    for index, item_value in enumerate(value):
        item_field = f"{field}[{index}]"
        item = require_object(item_value, item_field)
        require_exact_keys(item, item_field, required_keys)
        versions = sorted(
            require_string_list(item["versions"], f"{item_field}.versions", allow_empty=False)
        )
        actions = sorted(
            require_string_list(item["actions"], f"{item_field}.actions", allow_empty=False)
        )
        if not set(actions).issubset(SUPPORTED_ACTIONS):
            raise InputError(f"{item_field}.actions contains an unsupported action")
        result.append(
            {
                package_key: require_string(item[package_key], f"{item_field}.{package_key}"),
                source_ref_key: require_string(
                    item[source_ref_key], f"{item_field}.{source_ref_key}"
                ),
                "versions": versions,
                "actions": actions,
                "maxEstimatedDiskBytes": require_int(
                    item["maxEstimatedDiskBytes"],
                    f"{item_field}.maxEstimatedDiskBytes",
                ),
                "allowedPermissions": sorted(
                    require_string_list(
                        item["allowedPermissions"], f"{item_field}.allowedPermissions"
                    )
                ),
            }
        )
    identities = [(item[package_key], item[source_ref_key]) for item in result]
    if len(identities) != len(set(identities)):
        raise InputError(f"{field} contains duplicate app policy entries")
    return result


def _normalize_catalog(value: Any) -> dict[str, Any]:
    catalog = require_object(value, "catalog")
    require_exact_keys(catalog, "catalog", {"schemaVersion", "defaultPolicy", "apt", "flatpak"})
    if require_int(catalog["schemaVersion"], "catalog.schemaVersion") != 1:
        raise InputError("catalog.schemaVersion must be 1")
    if require_string(catalog["defaultPolicy"], "catalog.defaultPolicy") != "deny":
        raise InputError("catalog.defaultPolicy must be deny")

    apt = require_object(catalog["apt"], "catalog.apt")
    require_exact_keys(apt, "catalog.apt", {"allowedRepositories", "allowedPackages"})
    flatpak = require_object(catalog["flatpak"], "catalog.flatpak")
    require_exact_keys(
        flatpak, "catalog.flatpak", {"allowedRemotes", "allowedApplications"}
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "defaultPolicy": "deny",
        "apt": {
            "allowedRepositories": _normalize_source_entries(
                apt["allowedRepositories"],
                "catalog.apt.allowedRepositories",
                name_key="id",
            ),
            "allowedPackages": _normalize_app_entries(
                apt["allowedPackages"],
                "catalog.apt.allowedPackages",
                package_key="package",
                source_ref_key="repository",
            ),
        },
        "flatpak": {
            "allowedRemotes": _normalize_source_entries(
                flatpak["allowedRemotes"],
                "catalog.flatpak.allowedRemotes",
                name_key="name",
            ),
            "allowedApplications": _normalize_app_entries(
                flatpak["allowedApplications"],
                "catalog.flatpak.allowedApplications",
                package_key="applicationId",
                source_ref_key="remote",
            ),
        },
    }


def normalize_catalog(value: Any) -> dict[str, Any]:
    """Return the canonical fail-closed catalog used by higher-level dry runs."""
    return _normalize_catalog(value)


def _normalize_ledger(value: Any) -> dict[str, Any]:
    ledger = require_object(value, "ledger")
    require_exact_keys(ledger, "ledger", {"schemaVersion", "operations", "consumedApprovals"})
    if require_int(ledger["schemaVersion"], "ledger.schemaVersion") != 1:
        raise InputError("ledger.schemaVersion must be 1")
    operations = require_object(ledger["operations"], "ledger.operations")
    consumed = require_object(ledger["consumedApprovals"], "ledger.consumedApprovals")

    normalized_operations: dict[str, Any] = {}
    for operation_id, entry_value in operations.items():
        require_string(operation_id, "ledger operation id", identifier=True)
        field = f"ledger.operations.{operation_id}"
        entry = require_object(entry_value, field)
        require_exact_keys(
            entry, field, {"operationDigest", "approvalId", "status", "reservationId"}
        )
        status = require_string(entry["status"], f"{field}.status")
        if status not in {"reserved", "completed"}:
            raise InputError(f"{field}.status must be reserved or completed")
        normalized_operations[operation_id] = {
            "operationDigest": require_digest(
                entry["operationDigest"], f"{field}.operationDigest"
            ),
            "approvalId": require_string(
                entry["approvalId"], f"{field}.approvalId", identifier=True
            ),
            "status": status,
            "reservationId": require_string(
                entry["reservationId"], f"{field}.reservationId", identifier=True
            ),
        }

    normalized_consumed: dict[str, Any] = {}
    for approval_id, entry_value in consumed.items():
        require_string(approval_id, "ledger approval id", identifier=True)
        field = f"ledger.consumedApprovals.{approval_id}"
        entry = require_object(entry_value, field)
        require_exact_keys(entry, field, {"operationId", "operationDigest"})
        normalized_consumed[approval_id] = {
            "operationId": require_string(
                entry["operationId"], f"{field}.operationId", identifier=True
            ),
            "operationDigest": require_digest(
                entry["operationDigest"], f"{field}.operationDigest"
            ),
        }

    for operation_id, entry in normalized_operations.items():
        consumed_entry = normalized_consumed.get(entry["approvalId"])
        if consumed_entry != {
            "operationId": operation_id,
            "operationDigest": entry["operationDigest"],
        }:
            raise InputError("ledger operation and consumed-approval records are inconsistent")
    for approval_id, entry in normalized_consumed.items():
        operation_entry = normalized_operations.get(entry["operationId"])
        if operation_entry is None or operation_entry["approvalId"] != approval_id:
            raise InputError("ledger consumed approval has no matching operation")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "operations": normalized_operations,
        "consumedApprovals": normalized_consumed,
    }


def _allowlist_reasons(operation: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    manager = operation["manager"]
    if manager not in SUPPORTED_MANAGERS:
        return ["unsupported-manager"]
    if operation["action"] not in SUPPORTED_ACTIONS:
        return ["unsupported-action"]

    if manager == "apt":
        source_entries = catalog["apt"]["allowedRepositories"]
        app_entries = catalog["apt"]["allowedPackages"]
        source_name_key = "id"
        package_key = "package"
        source_ref_key = "repository"
    else:
        source_entries = catalog["flatpak"]["allowedRemotes"]
        app_entries = catalog["flatpak"]["allowedApplications"]
        source_name_key = "name"
        package_key = "applicationId"
        source_ref_key = "remote"

    source_matches = [entry for entry in source_entries if entry["source"] == operation["source"]]
    if len(source_matches) != 1:
        return ["source-not-allowlisted"]
    source_name = source_matches[0][source_name_key]
    app_matches = [
        entry
        for entry in app_entries
        if entry[package_key] == operation["package"]
        and entry[source_ref_key] == source_name
    ]
    if len(app_matches) != 1:
        return ["package-not-allowlisted"]

    policy = app_matches[0]
    reasons: list[str] = []
    if operation["version"] not in policy["versions"]:
        reasons.append("version-not-allowlisted")
    if operation["action"] not in policy["actions"]:
        reasons.append("action-not-allowlisted")
    if operation["estimatedDiskBytes"] > policy["maxEstimatedDiskBytes"]:
        reasons.append("disk-estimate-exceeds-allowlist")
    denied_permissions = sorted(
        set(operation["requestedPermissions"]) - set(policy["allowedPermissions"])
    )
    if denied_permissions:
        reasons.append("permissions-not-allowlisted")
    return reasons


def _result(
    *,
    decision: str,
    reasons: list[str],
    input_valid: bool,
    operation_digest_value: str | None,
    next_ledger: dict[str, Any] | None,
    policy_eligible: bool = False,
    would_reserve: bool = False,
    idempotent: bool = False,
    reservation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "dry-run",
        "inputValid": input_valid,
        "decision": decision,
        "policyEligible": policy_eligible,
        "wouldReserve": would_reserve,
        "idempotent": idempotent,
        "operationDigest": operation_digest_value,
        "reservation": reservation,
        "reasons": reasons,
        "executable": False,
        "commands": [],
        "servicesStarted": [],
        "filesWritten": [],
        "nextLedger": next_ledger,
    }


def verify_app_operation(
    *,
    operation_value: Any,
    approval_value: Any,
    catalog_value: Any,
    ledger_value: Any,
    ledger_integrity_verified_value: Any,
    now_value: Any,
) -> dict[str, Any]:
    """Evaluate an exact request and emit only a simulated one-use reservation."""
    try:
        now = parse_rfc3339(now_value, "now")
        operation, operation_expires_at = _normalize_operation(operation_value)
        digest = canonical_digest(operation)
        approval, approval_issued_at, approval_expires_at = _normalize_approval(approval_value)
        catalog = _normalize_catalog(catalog_value)
        ledger = _normalize_ledger(ledger_value)
        ledger_integrity_verified = require_bool(
            ledger_integrity_verified_value, "ledgerIntegrityVerified"
        )
    except InputError as exc:
        return _result(
            decision="deny",
            reasons=[f"invalid-input:{exc}"],
            input_valid=False,
            operation_digest_value=None,
            next_ledger=None,
        )

    binding_reasons: list[str] = []
    if operation["creatorPrincipal"] != CREATOR_PRINCIPAL:
        binding_reasons.append("operation-creator-mismatch")
    if approval["creatorPrincipal"] != CREATOR_PRINCIPAL:
        binding_reasons.append("approval-creator-mismatch")
    if operation["approvalLease"] != approval["approvalId"]:
        binding_reasons.append("approval-lease-mismatch")
    if approval["operationId"] != operation["operationId"]:
        binding_reasons.append("approval-operation-mismatch")
    if approval["operationDigest"] != digest:
        binding_reasons.append("approval-digest-mismatch")
    if not approval["oneUse"]:
        binding_reasons.append("approval-not-one-use")

    verification_reasons: list[str] = []
    if not ledger_integrity_verified:
        verification_reasons.append("ledger-integrity-unverified")
    verification = approval["verification"]
    if verification["status"] != "verified":
        verification_reasons.append("creator-approval-unverified")
    if verification["verifier"] != EXTERNAL_VERIFIER:
        verification_reasons.append("creator-verifier-not-trusted")

    existing = ledger["operations"].get(operation["operationId"])
    existing_matches = bool(
        existing is not None
        and existing["operationDigest"] == digest
        and existing["approvalId"] == approval["approvalId"]
    )
    if existing_matches:
        if not binding_reasons and not verification_reasons:
            assert existing is not None
            return _result(
                decision="idempotent-noop",
                reasons=[],
                input_valid=True,
                operation_digest_value=digest,
                next_ledger=copy.deepcopy(ledger),
                policy_eligible=True,
                idempotent=True,
                reservation={
                    "reservationId": existing["reservationId"],
                    "status": existing["status"],
                },
            )
    elif existing is not None:
        binding_reasons.append("operation-id-conflict")

    if approval["approvalId"] in ledger["consumedApprovals"] and not existing_matches:
        binding_reasons.append("approval-already-consumed")

    temporal_reasons: list[str] = []
    if now >= operation_expires_at:
        temporal_reasons.append("operation-expired")
    if now < approval_issued_at:
        temporal_reasons.append("approval-not-yet-valid")
    if now >= approval_expires_at:
        temporal_reasons.append("approval-expired")
    if approval_expires_at > operation_expires_at:
        temporal_reasons.append("approval-outlives-operation")

    reasons = (
        binding_reasons
        + temporal_reasons
        + verification_reasons
        + _allowlist_reasons(operation, catalog)
    )
    if reasons:
        return _result(
            decision="deny",
            reasons=list(dict.fromkeys(reasons)),
            input_valid=True,
            operation_digest_value=digest,
            next_ledger=copy.deepcopy(ledger),
        )

    reservation_id = "dry-run:" + canonical_digest(
        {
            "kind": "app-operation-reservation",
            "operationId": operation["operationId"],
            "operationDigest": digest,
            "approvalId": approval["approvalId"],
        }
    )
    next_ledger = copy.deepcopy(ledger)
    next_ledger["operations"][operation["operationId"]] = {
        "operationDigest": digest,
        "approvalId": approval["approvalId"],
        "status": "reserved",
        "reservationId": reservation_id,
    }
    next_ledger["consumedApprovals"][approval["approvalId"]] = {
        "operationId": operation["operationId"],
        "operationDigest": digest,
    }
    return _result(
        decision="would-reserve",
        reasons=[],
        input_valid=True,
        operation_digest_value=digest,
        next_ledger=next_ledger,
        policy_eligible=True,
        would_reserve=True,
        reservation={"reservationId": reservation_id, "status": "reserved"},
    )


def _cli_error(message: str) -> dict[str, Any]:
    return _result(
        decision="deny",
        reasons=[f"input-read-failed:{message}"],
        input_valid=False,
        operation_digest_value=None,
        next_ledger=None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate an Alpecca app operation without executing it."
    )
    parser.add_argument("verify", choices=["verify"])
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--input", required=True, help="Combined JSON path or - for stdin")
    args = parser.parse_args(argv)

    try:
        payload_value = load_json(args.input)
        payload = require_object(payload_value, "input")
        require_exact_keys(
            payload,
            "input",
            {
                "schemaVersion",
                "now",
                "operation",
                "approval",
                "catalog",
                "ledger",
                "ledgerIntegrityVerified",
            },
        )
        if require_int(payload["schemaVersion"], "input.schemaVersion") != 1:
            raise InputError("input.schemaVersion must be 1")
    except (OSError, json.JSONDecodeError, InputError) as exc:
        print_json(_cli_error(type(exc).__name__ if not isinstance(exc, InputError) else str(exc)))
        return 2

    result = verify_app_operation(
        operation_value=payload["operation"],
        approval_value=payload["approval"],
        catalog_value=payload["catalog"],
        ledger_value=payload["ledger"],
        ledger_integrity_verified_value=payload["ledgerIntegrityVerified"],
        now_value=payload["now"],
    )
    print_json(result)
    if not result["inputValid"]:
        return 2
    return 0 if result["decision"] in {"would-reserve", "idempotent-noop"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
