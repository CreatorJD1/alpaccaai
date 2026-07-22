"""Offline, fail-closed Cloudflare desktop deployment preflight."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = PACKAGE_ROOT / "config" / "capability-policy.json"
DEFAULT_CONTRACT = PACKAGE_ROOT / "config" / "desktop-contract.json"
DEFAULT_CATALOG = PACKAGE_ROOT.parent / "ubuntu-app-vm" / "config" / "reviewed-app-install-catalog.json"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _command_version(command: str) -> dict[str, Any]:
    executable = shutil.which(command)
    if executable is None:
        return {"present": False, "version": None, "path": None}
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"present": True, "version": None, "path": executable}
    version = (completed.stdout or completed.stderr).strip().splitlines()
    return {
        "present": True,
        "version": version[0][:120] if version else None,
        "path": executable,
    }


def _docker_status() -> dict[str, Any]:
    status = _command_version("docker")
    status["daemonReady"] = False
    if not status["present"]:
        return status
    try:
        completed = subprocess.run(
            [status["path"], "info", "--format", "{{json .ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return status
    status["daemonReady"] = completed.returncode == 0 and bool(completed.stdout.strip())
    return status


def _wrangler_status() -> dict[str, Any]:
    """Detect either a direct Wrangler CLI or an already-cached npx copy.

    The npx check is forced offline so an observation-only preflight cannot
    install a package or contact the registry while merely inspecting a host.
    """
    direct = _command_version("wrangler")
    if direct["present"]:
        direct["source"] = "direct"
        return direct
    node = shutil.which("node")
    cache_roots: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        cache_roots.append(Path(local_app_data) / "npm-cache" / "_npx")
    cache_roots.append(Path.home() / ".npm" / "_npx")
    candidates: list[Path] = []
    for root in cache_roots:
        try:
            candidates.extend(
                item for item in root.glob("*/node_modules/wrangler/bin/wrangler.js")
                if item.is_file()
            )
        except OSError:
            continue
    try:
        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        candidates = []
    if node:
        for candidate in candidates[:8]:
            try:
                completed = subprocess.run(
                    [node, str(candidate), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            lines = (completed.stdout or completed.stderr).strip().splitlines()
            if completed.returncode == 0 and lines:
                return {
                    "present": True,
                    "version": lines[0][:120],
                    "path": str(candidate),
                    "source": "npx-cache-offline",
                }
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx is None:
        return {**direct, "source": "unavailable"}
    env = dict(os.environ)
    env["npm_config_offline"] = "true"
    try:
        completed = subprocess.run(
            [npx, "--no-install", "wrangler", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {**direct, "source": "unavailable"}
    lines = (completed.stdout or completed.stderr).strip().splitlines()
    if completed.returncode != 0 or not lines:
        return {**direct, "source": "unavailable"}
    return {
        "present": True,
        "version": lines[0][:120],
        "path": npx,
        "source": "npx-cache-offline",
    }


def inspect_host() -> dict[str, Any]:
    """Inspect commands and the local Docker daemon; never contact Cloudflare."""
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "node": _command_version("node"),
        "npm": _command_version("npm"),
        "docker": _docker_status(),
        "wrangler": _wrangler_status(),
        "networkChecksPerformed": False,
    }


def _validate_catalog(catalog: Any) -> dict[str, Any]:
    reasons: list[str] = []
    entries: list[str] = []
    if type(catalog) is not dict or catalog.get("schemaVersion") != 1:
        reasons.append("catalog-schema-invalid")
    elif catalog.get("defaultPolicy") != "deny":
        reasons.append("catalog-not-deny-by-default")
    else:
        apt = catalog.get("apt")
        flatpak = catalog.get("flatpak")
        if type(apt) is not dict or type(flatpak) is not dict:
            reasons.append("catalog-manager-sections-invalid")
        else:
            for item in apt.get("allowedPackages", []):
                if type(item) is not dict or item.get("actions") != ["install"]:
                    reasons.append("catalog-apt-action-invalid")
                    continue
                if item.get("allowedPermissions") != []:
                    reasons.append("catalog-apt-permissions-not-empty")
                    continue
                entries.append("apt:" + str(item.get("package")))
            for item in flatpak.get("allowedApplications", []):
                if type(item) is not dict or item.get("actions") != ["install"]:
                    reasons.append("catalog-flatpak-action-invalid")
                    continue
                if item.get("allowedPermissions") != []:
                    reasons.append("catalog-flatpak-permissions-not-empty")
                    continue
                entries.append("flatpak:" + str(item.get("applicationId")))
    if not entries:
        reasons.append("catalog-has-no-reviewed-apps")
    return {
        "valid": not reasons,
        "defaultPolicy": catalog.get("defaultPolicy") if type(catalog) is dict else None,
        "entryCount": len(entries),
        "entries": sorted(entries),
        "digest": _digest(catalog),
        "reasons": list(dict.fromkeys(reasons)),
        "installExecutorPresent": False,
    }


def _validate_contract(contract: Any) -> list[str]:
    reasons: list[str] = []
    if type(contract) is not dict or contract.get("schemaVersion") != 1:
        return ["desktop-contract-invalid"]
    continuity = contract.get("continuity", {})
    ingress = contract.get("ingress", {})
    persistence = contract.get("persistence", {})
    process = contract.get("processPolicy", {})
    if contract.get("maximumDesktopInstances") != 1:
        reasons.append("desktop-instance-limit-not-one")
    if continuity.get("coordinator") != "single-named-sqlite-durable-object":
        reasons.append("continuity-coordinator-not-strongly-consistent")
    if continuity.get("newAcquisitionRequiresStrictlyNewerFence") is not True:
        reasons.append("monotonic-fence-not-required")
    if ingress.get("httpsRequired") is not True or ingress.get("cloudflareAccessRequired") is not True:
        reasons.append("creator-https-access-not-required")
    required_jwt = {"signature", "issuer", "audience", "expiry", "exact-creator-identity"}
    if set(ingress.get("originJwtValidationRequired", [])) != required_jwt:
        reasons.append("access-origin-jwt-validation-incomplete")
    if ingress.get("vncBindAddress") != "127.0.0.1":
        reasons.append("vnc-not-loopback-only")
    if persistence.get("provider") != "r2-standard":
        reasons.append("persistence-not-r2-standard")
    prohibited = set(process.get("prohibitedProcessRoles", []))
    if not {"autonomous-game", "coremind", "discord-bridge", "model-server", "server.py"} <= prohibited:
        reasons.append("prohibited-process-list-incomplete")
    return reasons


def _validate_account_evidence(value: Any) -> list[str]:
    if value is None:
        return ["account-entitlement-evidence-missing"]
    required_true = {
        "containersEntitled",
        "workersPaidPlanActive",
        "customDomainZoneActive",
        "accessApplicationConfigured",
        "creatorIdentityAllowlisted",
        "accessJwtOriginValidationConfigured",
        "r2StandardBucketConfigured",
        "billingAlertsConfigured",
    }
    if type(value) is not dict or value.get("schemaVersion") != 1:
        return ["account-entitlement-evidence-invalid"]
    reasons = [f"account-evidence-false:{key}" for key in sorted(required_true) if value.get(key) is not True]
    if value.get("evidenceSource") not in {"cloudflare-dashboard-export", "cloudflare-api-read-only"}:
        reasons.append("account-evidence-source-untrusted")
    return reasons


def _validate_runtime_evidence(value: Any, required: list[str]) -> list[str]:
    if value is None:
        return ["runtime-health-evidence-missing"]
    if type(value) is not dict or value.get("schemaVersion") != 1:
        return ["runtime-health-evidence-invalid"]
    checks = value.get("checks")
    if type(checks) is not dict:
        return ["runtime-health-checks-invalid"]
    reasons = [f"runtime-check-failed:{name}" for name in required if checks.get(name) is not True]
    if value.get("evidenceSource") != "independent-external-probe":
        reasons.append("runtime-evidence-not-independent")
    if value.get("desktopInstanceCount") != 1:
        reasons.append("runtime-desktop-count-not-one")
    if value.get("prohibitedProcessCount") != 0:
        reasons.append("runtime-prohibited-process-count-not-zero")
    return reasons


def _blocker(identifier: str, detail: str, remediation: str) -> dict[str, str]:
    return {"id": identifier, "detail": detail, "remediation": remediation}


def evaluate_preflight(
    *,
    host: dict[str, Any] | None = None,
    account_evidence: Any = None,
    runtime_evidence: Any = None,
    catalog: Any = None,
    policy: Any = None,
    contract: Any = None,
) -> dict[str, Any]:
    policy = _load_json(DEFAULT_POLICY) if policy is None else policy
    contract = _load_json(DEFAULT_CONTRACT) if contract is None else contract
    catalog = _load_json(DEFAULT_CATALOG) if catalog is None else catalog
    host = inspect_host() if host is None else host
    blockers: list[dict[str, str]] = []

    cost = policy.get("costPolicy", {}) if type(policy) is dict else {}
    if cost.get("containersFreePlanAvailable") is not True:
        blockers.append(_blocker(
            "containers-free-tier-unavailable",
            "Official Containers pricing lists no Free plan allocation and requires Workers Paid.",
            "A creator must explicitly approve recurring and metered Cloudflare spend; zero-cost deployment is unavailable.",
        ))
    if cost.get("maximumApprovedMonthlyUsd") != 0:
        blockers.append(_blocker("cost-policy-invalid", "The lane is not locked to zero approved spend.", "Restore the zero-spend policy."))
    if not host.get("docker", {}).get("present"):
        blockers.append(_blocker(
            "local-docker-missing",
            "Docker is absent; official Sandbox deployment requires Docker running for wrangler deploy.",
            "Use a separately reviewed build host only after spend is approved; do not install or bypass Docker from this lane.",
        ))
    elif not host.get("docker", {}).get("daemonReady"):
        blockers.append(_blocker(
            "local-docker-daemon-unavailable",
            "Docker is installed but its local daemon did not pass docker info; Sandbox deployment requires it running.",
            "Do not start or configure Docker from this lane; use a separately reviewed build host only after spend approval.",
        ))
    if not host.get("wrangler", {}).get("present"):
        blockers.append(_blocker(
            "wrangler-missing",
            "Wrangler is not installed as a local command.",
            "Install a pinned Wrangler only after deployment is authorized; installation alone does not solve Docker or billing.",
        ))

    contract_reasons = _validate_contract(contract)
    for reason in contract_reasons:
        blockers.append(_blocker(reason, "The desktop safety contract failed validation.", "Review and repair the contract before implementation."))
    catalog_status = _validate_catalog(catalog)
    for reason in catalog_status["reasons"]:
        blockers.append(_blocker(reason, "The reviewed app catalog failed closed.", "Review the source catalog; do not add an installer here."))
    for reason in _validate_account_evidence(account_evidence):
        blockers.append(_blocker(reason, "Cloudflare account, Access, domain, R2, or billing evidence is incomplete.", "Supply a content-free, read-only account evidence record after creator review."))
    required_health = contract.get("healthEvidenceRequired", []) if type(contract) is dict else []
    for reason in _validate_runtime_evidence(runtime_evidence, required_health):
        blockers.append(_blocker(reason, "No independent live health/readiness proof satisfies the desktop contract.", "Run an external probe only after an authorized deployment exists."))

    blocker_ids = [item["id"] for item in blockers]
    evidence_payload = {
        "policyDigest": _digest(policy),
        "contractDigest": _digest(contract),
        "catalogDigest": catalog_status["digest"],
        "host": host,
        "blockerIds": blocker_ids,
    }
    return {
        "schemaVersion": 1,
        "mode": "dry-run",
        "status": "blocked" if blockers else "review-required",
        "technicalGuiCapability": "plausible-not-deployed",
        "feasibleUnderRequestedConstraints": False,
        "deployReady": False,
        "wouldDeploy": False,
        "wouldCreateCloudResources": False,
        "wouldStartDesktop": False,
        "wouldStartCoreMind": False,
        "deploymentCommands": [],
        "networkChecksPerformed": False,
        "host": host,
        "catalog": catalog_status,
        "contractValid": not contract_reasons,
        "accountEvidenceAccepted": not _validate_account_evidence(account_evidence),
        "runtimeEvidenceAccepted": not _validate_runtime_evidence(runtime_evidence, required_health),
        "blockers": blockers,
        "evidenceId": _digest(evidence_payload),
        "sideEffects": [],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="required safety lock")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--account-evidence", type=Path)
    parser.add_argument("--runtime-evidence", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.dry_run:
        print(json.dumps({"error": "--dry-run is required", "wouldDeploy": False}, sort_keys=True))
        return 2
    try:
        catalog = _load_json(args.catalog)
        account = _load_json(args.account_evidence) if args.account_evidence else None
        runtime = _load_json(args.runtime_evidence) if args.runtime_evidence else None
        result = evaluate_preflight(catalog=catalog, account_evidence=account, runtime_evidence=runtime)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"input-error:{exc}", "wouldDeploy": False}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
