"""Focused fail-closed Cloudflare desktop preflight tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cloudflare_app_vm.preflight import (  # noqa: E402
    DEFAULT_CATALOG,
    _wrangler_status,
    evaluate_preflight,
)


ENTRYPOINT = ROOT / "bin" / "cloudflare-desktop-preflight"


def _host(*, docker: bool = False, wrangler: bool = False) -> dict:
    command = lambda present: {"present": present, "version": "test", "path": "test" if present else None}
    docker_command = command(docker)
    docker_command["daemonReady"] = docker
    return {
        "platform": "Windows-test",
        "python": "3.12-test",
        "node": command(True),
        "npm": command(True),
        "docker": docker_command,
        "wrangler": command(wrangler),
        "networkChecksPerformed": False,
    }


def _account() -> dict:
    return {
        "schemaVersion": 1,
        "evidenceSource": "cloudflare-api-read-only",
        "containersEntitled": True,
        "workersPaidPlanActive": True,
        "customDomainZoneActive": True,
        "accessApplicationConfigured": True,
        "creatorIdentityAllowlisted": True,
        "accessJwtOriginValidationConfigured": True,
        "r2StandardBucketConfigured": True,
        "billingAlertsConfigured": True,
    }


def _runtime() -> dict:
    contract = json.loads((ROOT / "config" / "desktop-contract.json").read_text(encoding="utf-8"))
    return {
        "schemaVersion": 1,
        "evidenceSource": "independent-external-probe",
        "checks": {name: True for name in contract["healthEvidenceRequired"]},
        "desktopInstanceCount": 1,
        "prohibitedProcessCount": 0,
    }


def test_official_zero_cost_blocker_cannot_be_erased_by_positive_evidence() -> None:
    result = evaluate_preflight(
        host=_host(docker=True, wrangler=True),
        account_evidence=_account(),
        runtime_evidence=_runtime(),
    )

    assert result["status"] == "blocked"
    assert result["feasibleUnderRequestedConstraints"] is False
    assert result["deployReady"] is False
    assert [item["id"] for item in result["blockers"]] == ["containers-free-tier-unavailable"]
    assert result["wouldDeploy"] is False
    assert result["wouldCreateCloudResources"] is False
    assert result["wouldStartCoreMind"] is False
    assert result["deploymentCommands"] == []
    assert result["sideEffects"] == []


def test_current_host_gaps_and_missing_external_evidence_are_exact() -> None:
    result = evaluate_preflight(host=_host())
    ids = {item["id"] for item in result["blockers"]}

    assert "containers-free-tier-unavailable" in ids
    assert "local-docker-missing" in ids
    assert "wrangler-missing" in ids
    assert "account-entitlement-evidence-missing" in ids
    assert "runtime-health-evidence-missing" in ids
    assert result["networkChecksPerformed"] is False


def test_docker_cli_without_daemon_is_not_deployment_capable() -> None:
    host = _host(docker=True)
    host["docker"]["daemonReady"] = False
    result = evaluate_preflight(host=host)
    ids = {item["id"] for item in result["blockers"]}

    assert "local-docker-missing" not in ids
    assert "local-docker-daemon-unavailable" in ids


def test_wrangler_detects_an_existing_offline_npx_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = tmp_path / "local"
    cached = local / "npm-cache" / "_npx" / "cache-key" / "node_modules" / "wrangler" / "bin" / "wrangler.js"
    cached.parent.mkdir(parents=True)
    cached.write_text("// cached Wrangler entry", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(
        "cloudflare_app_vm.preflight.shutil.which",
        lambda name: "C:/tools/node.exe" if name == "node" else None,
    )

    def fake_run(command, **kwargs):
        assert command == ["C:/tools/node.exe", str(cached), "--version"]
        return subprocess.CompletedProcess(command, 0, stdout="4.111.0\n", stderr="")

    monkeypatch.setattr("cloudflare_app_vm.preflight.subprocess.run", fake_run)
    status = _wrangler_status()

    assert status == {
        "present": True,
        "version": "4.111.0",
        "path": str(cached),
        "source": "npx-cache-offline",
    }


def test_reviewed_catalog_is_integrated_deny_by_default_without_executor() -> None:
    result = evaluate_preflight(host=_host())
    catalog = result["catalog"]

    assert DEFAULT_CATALOG.exists()
    assert catalog["valid"] is True
    assert catalog["defaultPolicy"] == "deny"
    assert catalog["entryCount"] == 4
    assert catalog["installExecutorPresent"] is False
    assert catalog["digest"].startswith("sha256:")


def test_catalog_widening_or_runtime_coremind_evidence_fails_closed() -> None:
    catalog = json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))
    catalog["defaultPolicy"] = "allow"
    result = evaluate_preflight(host=_host(), catalog=catalog)
    assert "catalog-not-deny-by-default" in {item["id"] for item in result["blockers"]}

    runtime = _runtime()
    runtime["prohibitedProcessCount"] = 1
    result = evaluate_preflight(host=_host(), runtime_evidence=runtime)
    assert "runtime-prohibited-process-count-not-zero" in {item["id"] for item in result["blockers"]}


def test_cli_requires_dry_run_and_emits_no_commands() -> None:
    denied = subprocess.run(
        [sys.executable, str(ENTRYPOINT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert denied.returncode == 2
    assert json.loads(denied.stdout)["wouldDeploy"] is False

    preflight = subprocess.run(
        [sys.executable, str(ENTRYPOINT), "--dry-run"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    result = json.loads(preflight.stdout)
    assert preflight.returncode == 0
    assert result["status"] == "blocked"
    assert result["deploymentCommands"] == []
    assert result["networkChecksPerformed"] is False


def test_package_contains_no_deployment_or_coremind_runtime_hooks() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "cloudflare_app_vm").glob("*.py")
    )
    for forbidden in (
        '["wrangler", "deploy"]',
        '["wrangler", "containers"]',
        '["docker", "build"]',
        "import server",
        "from server",
        "run_full",
        "subprocess.Popen",
        "os.system",
        "requests.",
        "urllib.request",
    ):
        assert forbidden not in source
