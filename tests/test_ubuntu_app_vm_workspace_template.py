"""Tests for the provider-neutral, render-only Ubuntu workspace template."""
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

from alpecca_ubuntu_vm.common import InputError  # noqa: E402
from alpecca_ubuntu_vm.workspace_template import (  # noqa: E402
    ACTIVATION_CONTRACT_PATH,
    EXPECTED_ENABLE_MARKERS,
    EXPECTED_EXTERNAL_SECRETS,
    EXPECTED_SERVICE_TEMPLATES,
    EXPECTED_SERVICE_USERS,
    REVIEWED_PACKAGE_NAMES,
    build_workspace_cloud_config,
    load_reviewed_workspace_inputs,
    render_workspace_cloud_init,
)


def _inputs() -> tuple[dict, dict[str, str]]:
    return load_reviewed_workspace_inputs()


def _write_file_map(cloud_config: dict) -> dict[str, dict]:
    return {item["path"]: item for item in cloud_config["write_files"]}


def test_reviewed_packages_and_locked_users_are_exact_and_non_login() -> None:
    manifest, templates = _inputs()
    originals = copy.deepcopy((manifest, templates))

    cloud_config = build_workspace_cloud_config(manifest, templates)

    assert (manifest, templates) == originals
    assert cloud_config["package_update"] is True
    assert cloud_config["package_upgrade"] is False
    assert tuple(cloud_config["packages"]) == REVIEWED_PACKAGE_NAMES
    assert cloud_config["users"][0] == "default"

    service_users = cloud_config["users"][1:]
    assert [user["name"] for user in service_users] == [
        user["name"] for user in EXPECTED_SERVICE_USERS
    ]
    for user in service_users:
        assert user["system"] is True
        assert user["lock_passwd"] is True
        assert user["shell"] == "/usr/sbin/nologin"
        assert user["no_create_home"] is False
        assert user["no_user_group"] is False
        assert user["ssh_authorized_keys"] == []
        assert not {"passwd", "plain_text_passwd", "hashed_passwd", "sudo"}.intersection(user)


def test_only_disabled_loopback_workspace_units_are_copied() -> None:
    manifest, templates = _inputs()
    cloud_config = build_workspace_cloud_config(manifest, templates)
    written = _write_file_map(cloud_config)

    expected_paths = {item["destination"] for item in EXPECTED_SERVICE_TEMPLATES}
    assert set(written) == expected_paths | {ACTIVATION_CONTRACT_PATH}
    for path in expected_paths:
        assert written[path]["owner"] == "root:root"
        assert written[path]["permissions"] == "0644"
        assert "ConditionPathExists=/etc/alpecca/enable-desktop" in written[path]["content"]

    display = written["/etc/systemd/system/alpecca-desktop-display.service"]["content"]
    gateway = written["/etc/systemd/system/alpecca-desktop-gateway.service"]["content"]
    assert "ConditionPathExists=/run/secrets/alpecca-vnc-password" in display
    assert "-localhost yes" in display
    assert "-rfbport 5900" in display
    assert "127.0.0.1:6080 127.0.0.1:5900" in gateway
    assert "0.0.0.0" not in display + gateway

    rendered_units = "\n".join(written[path]["content"] for path in expected_paths)
    assert "alpecca-cloud-core" not in rendered_units
    assert "alpecca-app-operation" not in rendered_units
    assert "alpecca-desktop-tunnel" not in rendered_units
    assert "cloudflared" not in rendered_units.lower()


def test_external_secrets_ingress_and_enable_markers_remain_absent() -> None:
    manifest, templates = _inputs()
    cloud_config = build_workspace_cloud_config(manifest, templates)
    written = _write_file_map(cloud_config)
    destinations = set(written)

    assert not destinations.intersection(EXPECTED_ENABLE_MARKERS)
    assert not destinations.intersection(
        secret["targetPath"] for secret in EXPECTED_EXTERNAL_SECRETS
    )

    contract = json.loads(written[ACTIVATION_CONTRACT_PATH]["content"])
    assert contract["serviceState"] == "disabled"
    assert all(not item["enabled"] and not item["started"] for item in contract["serviceTemplates"])
    assert all(
        item["createdByTemplate"] is False for item in contract["requiredEnableMarkers"]
    )
    assert all(
        item["injectedByTemplate"] is False for item in contract["requiredExternalSecrets"]
    )
    assert contract["phoneIngress"]["configuredByTemplate"] is False
    assert contract["phoneIngress"]["creatorAuthentication"] == "external-required"
    assert contract["phoneIngress"]["privateIngress"] == "external-required"
    assert set(contract["operationalActions"].values()) == {False}


def test_render_is_deterministic_json_compatible_cloud_config_without_commands() -> None:
    manifest, templates = _inputs()
    first = render_workspace_cloud_init(manifest, templates)
    second = render_workspace_cloud_init(manifest, templates)

    assert first == second
    assert first.startswith("#cloud-config\n")
    parsed = json.loads(first.removeprefix("#cloud-config\n"))
    assert parsed == build_workspace_cloud_config(manifest, templates)
    assert not {"runcmd", "bootcmd", "phone_home", "power_state"}.intersection(parsed)
    assert "systemctl" not in first
    assert "0.0.0.0" not in first

    lowered = first.lower()
    provider_terms = (
        "cloudflare",
        "amazon",
        "aws",
        "azure",
        "digitalocean",
        "google cloud",
        "gcp",
        "hetzner",
        "oracle cloud",
    )
    assert all(term not in lowered for term in provider_terms)


@pytest.mark.parametrize(
    "mutation",
    [
        "extra-package",
        "unsafe-output",
        "core-service",
        "missing-secret",
        "missing-marker",
        "provider-metadata",
    ],
)
def test_manifest_drift_fails_closed(mutation: str) -> None:
    manifest, templates = _inputs()
    changed = copy.deepcopy(manifest)
    if mutation == "extra-package":
        changed["packagePolicy"]["packages"].append(
            {"name": "curl", "purpose": "unreviewed"}
        )
    elif mutation == "unsafe-output":
        changed["outputSafety"]["startServices"] = True
    elif mutation == "core-service":
        changed["serviceTemplates"][0]["source"] = "systemd/alpecca-cloud-core.service"
    elif mutation == "missing-secret":
        changed["requiredExternalSecrets"] = []
    elif mutation == "missing-marker":
        changed["requiredEnableMarkers"] = []
    else:
        changed["packagePolicy"]["packages"][0]["purpose"] = "AWS-specific setup"

    with pytest.raises(InputError):
        build_workspace_cloud_config(changed, templates)


@pytest.mark.parametrize(
    ("source", "old", "new"),
    [
        (
            "systemd/alpecca-desktop-gateway.service",
            "127.0.0.1:6080",
            "0.0.0.0:6080",
        ),
        (
            "systemd/alpecca-desktop-display.service",
            "ConditionPathExists=/run/secrets/alpecca-vnc-password\n",
            "",
        ),
        (
            "systemd/alpecca-desktop-display.service",
            "Description=Alpecca loopback-only VNC display",
            "Description=Cloudflare-managed VNC display",
        ),
    ],
)
def test_service_template_drift_fails_closed(source: str, old: str, new: str) -> None:
    manifest, templates = _inputs()
    changed = copy.deepcopy(templates)
    assert old in changed[source]
    changed[source] = changed[source].replace(old, new, 1)
    with pytest.raises(InputError):
        build_workspace_cloud_config(manifest, changed)


def test_cli_renders_stdout_only_and_requires_explicit_dry_run() -> None:
    entrypoint = SCAFFOLD / "bin" / "render-workspace-cloud-init"
    completed = subprocess.run(
        [sys.executable, "-B", str(entrypoint), "render", "--dry-run"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert completed.stdout.startswith("#cloud-config\n")
    parsed = json.loads(completed.stdout.removeprefix("#cloud-config\n"))
    assert tuple(parsed["packages"]) == REVIEWED_PACKAGE_NAMES

    missing_mode = subprocess.run(
        [sys.executable, "-B", str(entrypoint), "render"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_mode.returncode == 2
    assert missing_mode.stdout == ""


def test_generator_has_no_provider_or_operational_capability_imports() -> None:
    source = (SCAFFOLD / "alpecca_ubuntu_vm" / "workspace_template.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "import subprocess",
        "import socket",
        "import requests",
        "import urllib",
        "os.environ",
        "os.getenv",
        ".write_text(",
        ".write_bytes(",
        "systemctl enable",
        "systemctl start",
        "apt-get",
    )
    assert all(value not in source for value in forbidden)
