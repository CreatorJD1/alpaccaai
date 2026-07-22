"""Static safety contracts for the inert Ubuntu app-VM scaffold."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "deploy" / "ubuntu-app-vm"


def _read(relative: str) -> str:
    return (SCAFFOLD / relative).read_text(encoding="utf-8")


def test_runtime_defaults_are_standby_and_fail_closed() -> None:
    env = _read("config/runtime.env.example")
    contract = json.loads(_read("contracts/leader-lease-contract.json"))

    assert "ALPECCA_CLOUD_RUNTIME_ENABLED=0" in env
    assert "ALPECCA_CLOUD_ROLE=standby" in env
    assert "ALPECCA_CONVERSATIONAL_EGRESS_ENABLED=0" in env
    assert "ALPECCA_SIDE_EFFECTS_REQUIRE_FENCE=1" in env
    assert "ALPECCA_SUPERVISOR_MODE=dry-run" in env
    assert "ALPECCA_APP_OPERATION_MODE=dry-run" in env
    assert contract["localPolicyMode"] == "dry-run-only"
    assert contract["renewIntervalSeconds"] == 10
    assert contract["leaseDurationSeconds"] == 35
    assert contract["minimumFailoverGraceSeconds"] >= 90
    assert "stale-fencing-epoch" in contract["failClosedOn"]
    assert "exact-highest-fencing-epoch" in contract["localFenceCheckRequires"]
    assert contract["automaticFailback"] is False


def test_every_service_is_inert_without_an_explicit_enable_marker() -> None:
    units = sorted((SCAFFOLD / "systemd").glob("*.service"))
    assert units
    for unit in units:
        source = unit.read_text(encoding="utf-8")
        assert "ConditionPathExists=/etc/alpecca/enable-" in source, unit.name

    core = _read("systemd/alpecca-cloud-core.service")
    assert "ALPECCA_CLOUD_ROLE=standby" in core
    assert "ALPECCA_CONVERSATIONAL_EGRESS_ENABLED=0" in core
    assert "alpecca-cloud-supervisor" in core
    assert "server.py" not in core


def test_phone_desktop_has_no_public_raw_vnc_or_novnc_listener() -> None:
    display = _read("systemd/alpecca-desktop-display.service")
    desktop = _read("systemd/alpecca-desktop-session.service")
    gateway = _read("systemd/alpecca-desktop-gateway.service")
    tunnel = _read("config/cloudflared-desktop.yml.example")

    assert "-localhost yes" in display
    assert "ConditionPathExists=/run/secrets/alpecca-vnc-password" in display
    assert "Requires=alpecca-desktop-display.service" in desktop
    assert "127.0.0.1:6080" in gateway
    assert "127.0.0.1:5900" in gateway
    assert "0.0.0.0:5900" not in display + desktop + gateway
    assert "0.0.0.0:6080" not in display + desktop + gateway
    assert "service: http://127.0.0.1:6080" in tunnel
    assert "http_status:404" in tunnel


def test_app_catalog_denies_by_default_and_operation_requires_external_approval() -> None:
    catalog = json.loads(_read("config/app-catalog.json"))
    approval_contract = json.loads(_read("contracts/app-approval-contract.json"))
    unit = _read("systemd/alpecca-app-operation@.service")
    example = json.loads(_read("contracts/app-operation.example.json"))

    assert catalog["defaultPolicy"] == "deny"
    assert catalog["apt"]["allowedPackages"] == []
    assert catalog["flatpak"]["allowedApplications"] == []
    assert "enable-app-operations" in unit
    assert "verify-app-approval" in unit
    assert example["creatorPrincipal"] == "CreatorJD"
    assert example["approvalLease"].startswith("SUPPLIED_AT_RUNTIME")
    assert approval_contract["localPolicyMode"] == "dry-run-only"
    assert "never-runs-a-package-manager" in approval_contract["dryRunOutputGuarantees"]


def test_scaffold_contains_no_deployment_credentials() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SCAFFOLD.rglob("*")
        if path.is_file()
        and path.suffix != ".py"
        and "__pycache__" not in path.parts
    )
    forbidden = ("BEGIN PRIVATE KEY", "CF_API_TOKEN=", "DISCORD_BOT_TOKEN=", "sk-proj-")
    assert all(value not in text for value in forbidden)
    assert "REPLACE_WITH_NAMED_TUNNEL_ID" in text
    assert "/run/secrets/" in text


def test_policy_skeleton_has_no_operational_capability_path() -> None:
    implementation = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (SCAFFOLD / "alpecca_ubuntu_vm").glob("*.py")
    )
    forbidden = (
        "import subprocess",
        "import socket",
        "import requests",
        "os.environ",
        "os.getenv",
        "systemctl enable",
        "systemctl start",
        "apt-get",
        "flatpak install",
        "flatpak update",
        "flatpak remove",
    )
    assert all(value not in implementation for value in forbidden)
    assert '"executable": False' in implementation
    assert '"sideEffects": []' in implementation
