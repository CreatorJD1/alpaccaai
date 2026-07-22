"""Provider-neutral cloud-init rendering for the inert Ubuntu workspace."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .common import (
    InputError,
    require_bool,
    require_exact_keys,
    require_int,
    require_object,
    require_string,
)


SCHEMA_VERSION = 1
SCAFFOLD_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = SCAFFOLD_ROOT / "config" / "workspace-template.json"
ACTIVATION_CONTRACT_PATH = "/etc/alpecca/workspace-activation-contract.json"

REVIEWED_PACKAGE_NAMES = (
    "ca-certificates",
    "dbus-x11",
    "flatpak",
    "novnc",
    "tigervnc-standalone-server",
    "tigervnc-tools",
    "websockify",
    "xauth",
    "xfce4",
)
EXPECTED_TARGET = {
    "distribution": "ubuntu",
    "release": "24.04",
    "desktop": "xfce",
    "displayServer": "tigervnc",
    "webGateway": "novnc-websockify",
}
EXPECTED_SERVICE_USERS = (
    {
        "name": "alpecca-workspace",
        "home": "/var/lib/alpecca-workspace",
        "shell": "/usr/sbin/nologin",
    },
    {
        "name": "alpecca-core",
        "home": "/var/lib/alpecca",
        "shell": "/usr/sbin/nologin",
    },
)
EXPECTED_SERVICE_TEMPLATES = (
    {
        "source": "systemd/alpecca-desktop-display.service",
        "destination": "/etc/systemd/system/alpecca-desktop-display.service",
    },
    {
        "source": "systemd/alpecca-desktop-session.service",
        "destination": "/etc/systemd/system/alpecca-desktop-session.service",
    },
    {
        "source": "systemd/alpecca-desktop-gateway.service",
        "destination": "/etc/systemd/system/alpecca-desktop-gateway.service",
    },
)
EXPECTED_EXTERNAL_SECRETS = (
    {
        "id": "vnc-password-file",
        "targetPath": "/run/secrets/alpecca-vnc-password",
        "owner": "alpecca-workspace:alpecca-workspace",
        "mode": "0600",
        "injection": "external-host-secret-store",
    },
)
EXPECTED_ENABLE_MARKERS = ("/etc/alpecca/enable-desktop",)
EXPECTED_PHONE_INGRESS = {
    "loopbackUpstream": "http://127.0.0.1:6080",
    "privateIngress": "external-required",
    "creatorAuthentication": "external-required",
    "ingressCredentialInjection": "external-required",
}
EXPECTED_EXCLUDED_SERVICES = (
    "alpecca-cloud-core.service",
    "alpecca-app-operation@.service",
    "alpecca-desktop-tunnel.service",
)
EXPECTED_OUTPUT_SAFETY = {
    "provisionInfrastructure": False,
    "contactExternalApis": False,
    "injectSecrets": False,
    "createEnableMarkers": False,
    "enableServices": False,
    "startServices": False,
}
FORBIDDEN_PROVIDER_TERMS = (
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
FORBIDDEN_CREDENTIAL_MARKERS = (
    "begin private key",
    "cf_api_token=",
    "discord_bot_token=",
    "sk-proj-",
    "secret_access_key",
)


def _require_array(value: Any, field: str) -> list[Any]:
    if type(value) is not list:
        raise InputError(f"{field} must be an array")
    return value


def _normalize_target(value: Any) -> dict[str, str]:
    target = require_object(value, "manifest.target")
    require_exact_keys(target, "manifest.target", EXPECTED_TARGET)
    normalized = {
        key: require_string(target[key], f"manifest.target.{key}")
        for key in EXPECTED_TARGET
    }
    if normalized != EXPECTED_TARGET:
        raise InputError("manifest.target is not the reviewed Ubuntu workspace target")
    return normalized


def _normalize_package_policy(value: Any) -> dict[str, Any]:
    policy = require_object(value, "manifest.packagePolicy")
    require_exact_keys(
        policy,
        "manifest.packagePolicy",
        {"manager", "updatePackageIndex", "upgradePackages", "packages"},
    )
    manager = require_string(policy["manager"], "manifest.packagePolicy.manager")
    update_index = require_bool(
        policy["updatePackageIndex"], "manifest.packagePolicy.updatePackageIndex"
    )
    upgrade_packages = require_bool(
        policy["upgradePackages"], "manifest.packagePolicy.upgradePackages"
    )
    packages: list[dict[str, str]] = []
    for index, item_value in enumerate(
        _require_array(policy["packages"], "manifest.packagePolicy.packages")
    ):
        field = f"manifest.packagePolicy.packages[{index}]"
        item = require_object(item_value, field)
        require_exact_keys(item, field, {"name", "purpose"})
        packages.append(
            {
                "name": require_string(item["name"], f"{field}.name"),
                "purpose": require_string(item["purpose"], f"{field}.purpose"),
            }
        )
    package_names = tuple(item["name"] for item in packages)
    if manager != "apt" or not update_index or upgrade_packages:
        raise InputError("manifest package-manager policy is not fail-closed")
    if package_names != REVIEWED_PACKAGE_NAMES:
        raise InputError("manifest package list differs from the reviewed prerequisite set")
    return {
        "manager": manager,
        "updatePackageIndex": update_index,
        "upgradePackages": upgrade_packages,
        "packages": packages,
    }


def _normalize_object_array(
    value: Any,
    field: str,
    keys: set[str],
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for index, item_value in enumerate(_require_array(value, field)):
        item_field = f"{field}[{index}]"
        item = require_object(item_value, item_field)
        require_exact_keys(item, item_field, keys)
        result.append(
            {key: require_string(item[key], f"{item_field}.{key}") for key in keys}
        )
    return result


def _normalize_string_array(value: Any, field: str) -> list[str]:
    result = [
        require_string(item, f"{field}[{index}]")
        for index, item in enumerate(_require_array(value, field))
    ]
    if len(result) != len(set(result)):
        raise InputError(f"{field} must not contain duplicates")
    return result


def _normalize_manifest(value: Any) -> dict[str, Any]:
    manifest = require_object(value, "manifest")
    serialized_manifest = json.dumps(manifest, sort_keys=True, ensure_ascii=True).lower()
    if any(term in serialized_manifest for term in FORBIDDEN_PROVIDER_TERMS):
        raise InputError("manifest must not contain a provider-specific integration")
    if any(marker in serialized_manifest for marker in FORBIDDEN_CREDENTIAL_MARKERS):
        raise InputError("manifest must not contain credential material")
    require_exact_keys(
        manifest,
        "manifest",
        {
            "schemaVersion",
            "templateId",
            "target",
            "packagePolicy",
            "serviceUsers",
            "serviceTemplates",
            "requiredExternalSecrets",
            "requiredEnableMarkers",
            "phoneIngress",
            "excludedServiceTemplates",
            "outputSafety",
        },
    )
    if require_int(manifest["schemaVersion"], "manifest.schemaVersion") != 1:
        raise InputError("manifest.schemaVersion must be 1")
    template_id = require_string(
        manifest["templateId"], "manifest.templateId", identifier=True
    )
    if template_id != "alpecca-ubuntu-xfce-novnc-v1":
        raise InputError("manifest.templateId is not reviewed")

    service_users = _normalize_object_array(
        manifest["serviceUsers"],
        "manifest.serviceUsers",
        {"name", "home", "shell"},
    )
    service_templates = _normalize_object_array(
        manifest["serviceTemplates"],
        "manifest.serviceTemplates",
        {"source", "destination"},
    )
    external_secrets = _normalize_object_array(
        manifest["requiredExternalSecrets"],
        "manifest.requiredExternalSecrets",
        {"id", "targetPath", "owner", "mode", "injection"},
    )
    markers = _normalize_string_array(
        manifest["requiredEnableMarkers"], "manifest.requiredEnableMarkers"
    )
    excluded_services = _normalize_string_array(
        manifest["excludedServiceTemplates"], "manifest.excludedServiceTemplates"
    )

    phone_ingress = require_object(manifest["phoneIngress"], "manifest.phoneIngress")
    require_exact_keys(phone_ingress, "manifest.phoneIngress", EXPECTED_PHONE_INGRESS)
    normalized_phone_ingress = {
        key: require_string(phone_ingress[key], f"manifest.phoneIngress.{key}")
        for key in EXPECTED_PHONE_INGRESS
    }

    output_safety = require_object(manifest["outputSafety"], "manifest.outputSafety")
    require_exact_keys(output_safety, "manifest.outputSafety", EXPECTED_OUTPUT_SAFETY)
    normalized_output_safety = {
        key: require_bool(output_safety[key], f"manifest.outputSafety.{key}")
        for key in EXPECTED_OUTPUT_SAFETY
    }

    if tuple(service_users) != EXPECTED_SERVICE_USERS:
        raise InputError("manifest service users differ from the locked reviewed users")
    if tuple(service_templates) != EXPECTED_SERVICE_TEMPLATES:
        raise InputError("manifest service templates differ from the reviewed desktop set")
    if tuple(external_secrets) != EXPECTED_EXTERNAL_SECRETS:
        raise InputError("manifest external secret requirements are not reviewed")
    if tuple(markers) != EXPECTED_ENABLE_MARKERS:
        raise InputError("manifest enable-marker requirements are not reviewed")
    if normalized_phone_ingress != EXPECTED_PHONE_INGRESS:
        raise InputError("manifest phone ingress contract is not provider-neutral")
    if tuple(excluded_services) != EXPECTED_EXCLUDED_SERVICES:
        raise InputError("manifest excluded service set is not reviewed")
    if normalized_output_safety != EXPECTED_OUTPUT_SAFETY:
        raise InputError("manifest output safety must keep every operational action disabled")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "templateId": template_id,
        "target": _normalize_target(manifest["target"]),
        "packagePolicy": _normalize_package_policy(manifest["packagePolicy"]),
        "serviceUsers": service_users,
        "serviceTemplates": service_templates,
        "requiredExternalSecrets": external_secrets,
        "requiredEnableMarkers": markers,
        "phoneIngress": normalized_phone_ingress,
        "excludedServiceTemplates": excluded_services,
        "outputSafety": normalized_output_safety,
    }


def _require_service_text(value: Any, field: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise InputError(f"{field} must be non-empty text without NUL bytes")
    return value if value.endswith("\n") else value + "\n"


def _validate_service_templates(
    manifest: dict[str, Any], templates_value: Any
) -> dict[str, str]:
    if type(templates_value) is not dict:
        raise InputError("serviceTemplates must be an object")
    expected_sources = [item["source"] for item in manifest["serviceTemplates"]]
    if set(templates_value) != set(expected_sources):
        raise InputError("service template inputs must exactly match the reviewed source set")

    templates = {
        source: _require_service_text(templates_value[source], f"serviceTemplates.{source}")
        for source in expected_sources
    }
    combined = "\n".join(templates.values()).lower()
    if any(term in combined for term in FORBIDDEN_PROVIDER_TERMS):
        raise InputError("reviewed workspace service templates must be provider-neutral")
    if any(marker in combined for marker in FORBIDDEN_CREDENTIAL_MARKERS):
        raise InputError("service templates contain credential material")
    if "0.0.0.0" in combined or "[::]" in combined:
        raise InputError("service templates must not expose public listeners")
    if "systemctl" in combined:
        raise InputError("service templates must not activate other services")

    for source, template in templates.items():
        if "ConditionPathExists=/etc/alpecca/enable-desktop" not in template:
            raise InputError(f"{source} lacks the explicit desktop enable-marker gate")

    display = templates["systemd/alpecca-desktop-display.service"]
    if "ConditionPathExists=/run/secrets/alpecca-vnc-password" not in display:
        raise InputError("display service lacks the external VNC secret gate")
    if "-localhost yes" not in display or "-rfbport 5900" not in display:
        raise InputError("display service is not loopback-only TigerVNC")
    if "-PasswordFile /run/secrets/alpecca-vnc-password" not in display:
        raise InputError("display service does not consume the reviewed external secret path")

    session = templates["systemd/alpecca-desktop-session.service"]
    if "DISPLAY=:10" not in session or "/usr/bin/startxfce4" not in session:
        raise InputError("desktop session service is not the reviewed Xfce session")

    gateway = templates["systemd/alpecca-desktop-gateway.service"]
    expected_gateway = (
        "ExecStart=/usr/bin/websockify --web=/usr/share/novnc "
        "127.0.0.1:6080 127.0.0.1:5900"
    )
    if expected_gateway not in gateway:
        raise InputError("noVNC gateway does not bind and forward on reviewed loopback endpoints")
    return templates


def _activation_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "templateId": manifest["templateId"],
        "serviceState": "disabled",
        "lockedServiceUsers": [item["name"] for item in manifest["serviceUsers"]],
        "serviceTemplates": [
            {
                "path": item["destination"],
                "copied": True,
                "enabled": False,
                "started": False,
            }
            for item in manifest["serviceTemplates"]
        ],
        "loopbackEndpoints": {
            "vnc": "127.0.0.1:5900",
            "noVnc": "127.0.0.1:6080",
        },
        "requiredExternalSecrets": [
            {**item, "injectedByTemplate": False}
            for item in manifest["requiredExternalSecrets"]
        ],
        "requiredEnableMarkers": [
            {"path": marker, "createdByTemplate": False}
            for marker in manifest["requiredEnableMarkers"]
        ],
        "phoneIngress": {
            **manifest["phoneIngress"],
            "configuredByTemplate": False,
        },
        "excludedServiceTemplates": manifest["excludedServiceTemplates"],
        "operationalActions": {
            "infrastructureProvisioned": False,
            "externalApisContacted": False,
            "secretsInjected": False,
            "enableMarkersCreated": False,
            "servicesEnabled": False,
            "servicesStarted": False,
        },
    }


def build_workspace_cloud_config(
    manifest_value: Any, service_templates_value: Any
) -> dict[str, Any]:
    """Build an inert cloud-config document from exact reviewed inputs."""
    manifest = _normalize_manifest(copy.deepcopy(manifest_value))
    templates = _validate_service_templates(manifest, service_templates_value)

    write_files = [
        {
            "path": item["destination"],
            "owner": "root:root",
            "permissions": "0644",
            "content": templates[item["source"]],
        }
        for item in manifest["serviceTemplates"]
    ]
    write_files.append(
        {
            "path": ACTIVATION_CONTRACT_PATH,
            "owner": "root:root",
            "permissions": "0644",
            "content": json.dumps(
                _activation_contract(manifest),
                sort_keys=True,
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
        }
    )

    destinations = {item["path"] for item in write_files}
    if destinations.intersection(manifest["requiredEnableMarkers"]):
        raise InputError("cloud-config must not create an enable marker")
    secret_paths = {item["targetPath"] for item in manifest["requiredExternalSecrets"]}
    if destinations.intersection(secret_paths):
        raise InputError("cloud-config must not inject an external secret")

    return {
        "package_update": manifest["packagePolicy"]["updatePackageIndex"],
        "package_upgrade": manifest["packagePolicy"]["upgradePackages"],
        "packages": [item["name"] for item in manifest["packagePolicy"]["packages"]],
        "users": [
            "default",
            *[
                {
                    "name": item["name"],
                    "system": True,
                    "lock_passwd": True,
                    "shell": item["shell"],
                    "homedir": item["home"],
                    "no_create_home": False,
                    "no_user_group": False,
                    "ssh_authorized_keys": [],
                }
                for item in manifest["serviceUsers"]
            ],
        ],
        "write_files": write_files,
    }


def render_workspace_cloud_init(
    manifest_value: Any, service_templates_value: Any
) -> str:
    """Render a cloud-config YAML document using JSON as the YAML body."""
    cloud_config = build_workspace_cloud_config(manifest_value, service_templates_value)
    return "#cloud-config\n" + json.dumps(
        cloud_config,
        sort_keys=True,
        indent=2,
        ensure_ascii=True,
    ) + "\n"


def load_reviewed_workspace_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    """Load only the repository-owned reviewed manifest and service templates."""
    scaffold_root = SCAFFOLD_ROOT.resolve()
    manifest_path = MANIFEST_PATH.resolve()
    if scaffold_root not in manifest_path.parents:
        raise InputError("workspace manifest escaped the scaffold root")
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest_value = json.load(handle)
    manifest = _normalize_manifest(manifest_value)
    templates: dict[str, str] = {}
    for item in manifest["serviceTemplates"]:
        source_path = (SCAFFOLD_ROOT / item["source"]).resolve()
        if scaffold_root not in source_path.parents:
            raise InputError("service template source escaped the scaffold root")
        templates[item["source"]] = source_path.read_text(encoding="utf-8")
    return manifest, templates


def render_reviewed_workspace_cloud_init() -> str:
    manifest, templates = load_reviewed_workspace_inputs()
    return render_workspace_cloud_init(manifest, templates)


def _failure_result(error: Exception) -> str:
    return json.dumps(
        {
            "schemaVersion": SCHEMA_VERSION,
            "mode": "dry-run",
            "decision": "render-denied",
            "inputValid": False,
            "executable": False,
            "error": type(error).__name__,
        },
        sort_keys=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the inert provider-neutral Alpecca workspace cloud-init."
    )
    parser.add_argument("command", choices=["render"])
    parser.add_argument("--dry-run", action="store_true", required=True)
    args = parser.parse_args(argv)
    assert args.command == "render" and args.dry_run

    try:
        rendered = render_reviewed_workspace_cloud_init()
    except (InputError, OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(_failure_result(exc) + "\n")
        return 2
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
