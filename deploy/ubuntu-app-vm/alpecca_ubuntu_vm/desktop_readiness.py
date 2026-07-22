"""Pure noVNC desktop readiness evidence; no probes or operational effects."""
from __future__ import annotations

from typing import Any

from .common import (
    InputError,
    canonical_digest,
    format_rfc3339,
    parse_rfc3339,
    require_bool,
    require_exact_keys,
    require_int,
    require_object,
    require_string,
)
from .supervisor import validate_fencing_epoch


SCHEMA_VERSION = 1
PACKAGE_KEYS = ("novnc", "tigervnc", "websockify", "xfce4")
UNIT_KEYS = (
    "alpecca-desktop-display.service",
    "alpecca-desktop-gateway.service",
    "alpecca-desktop-session.service",
)
LISTENER_POLICY = {
    "vnc": {"address": "127.0.0.1", "port": 5900},
    "novnc": {"address": "127.0.0.1", "port": 6080},
}


def _boolean_map(value: Any, field: str, keys: tuple[str, ...]) -> dict[str, bool]:
    item = require_object(value, field)
    require_exact_keys(item, field, keys)
    return {key: require_bool(item[key], f"{field}.{key}") for key in keys}


def _normalize_units(value: Any) -> dict[str, dict[str, bool]]:
    units = require_object(value, "observation.units")
    require_exact_keys(units, "observation.units", UNIT_KEYS)
    normalized: dict[str, dict[str, bool]] = {}
    for name in UNIT_KEYS:
        field = f"observation.units.{name}"
        unit = require_object(units[name], field)
        require_exact_keys(unit, field, {"definitionPresent", "enabled", "active"})
        normalized[name] = {
            "definitionPresent": require_bool(
                unit["definitionPresent"], f"{field}.definitionPresent"
            ),
            "enabled": require_bool(unit["enabled"], f"{field}.enabled"),
            "active": require_bool(unit["active"], f"{field}.active"),
        }
    return normalized


def _normalize_listeners(value: Any) -> dict[str, dict[str, Any]]:
    listeners = require_object(value, "observation.listeners")
    require_exact_keys(listeners, "observation.listeners", LISTENER_POLICY)
    normalized: dict[str, dict[str, Any]] = {}
    for name in LISTENER_POLICY:
        field = f"observation.listeners.{name}"
        listener = require_object(listeners[name], field)
        require_exact_keys(listener, field, {"address", "port", "listening"})
        normalized[name] = {
            "address": require_string(listener["address"], f"{field}.address"),
            "port": require_int(listener["port"], f"{field}.port", minimum=1),
            "listening": require_bool(listener["listening"], f"{field}.listening"),
        }
        if normalized[name]["port"] > 65535:
            raise InputError(f"{field}.port must be <= 65535")
    return normalized


def _invalid_result(message: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "dry-run",
        "inputValid": False,
        "status": "evidence-invalid",
        "evidenceId": None,
        "evidenceSource": "caller-supplied-observation",
        "independentlyProbed": False,
        "desktopDefinitionReady": False,
        "desktopRuntimeReady": False,
        "desktopPhoneReady": False,
        "continuityFenceReady": False,
        "coreMindStarted": False,
        "desktopReadinessDoesNotGrantLeadership": True,
        "reasons": [f"invalid-input:{message}"],
        "checks": [],
        "executable": False,
        "commands": [],
        "servicesEnabled": [],
        "servicesStarted": [],
        "sideEffects": [],
    }


def evaluate_desktop_readiness(observation_value: Any) -> dict[str, Any]:
    """Evaluate explicit runtime evidence without inspecting or changing the host."""
    try:
        observation = require_object(observation_value, "observation")
        require_exact_keys(
            observation,
            "observation",
            {
                "schemaVersion",
                "observedAt",
                "evidenceIntegrityVerified",
                "packages",
                "units",
                "listeners",
                "activation",
                "phoneIngress",
                "fenceCheck",
            },
        )
        if require_int(observation["schemaVersion"], "observation.schemaVersion") != 1:
            raise InputError("observation.schemaVersion must be 1")
        observed_at = format_rfc3339(
            parse_rfc3339(observation["observedAt"], "observation.observedAt")
        )
        integrity = require_bool(
            observation["evidenceIntegrityVerified"],
            "observation.evidenceIntegrityVerified",
        )
        packages = _boolean_map(observation["packages"], "observation.packages", PACKAGE_KEYS)
        units = _normalize_units(observation["units"])
        listeners = _normalize_listeners(observation["listeners"])
        activation = _boolean_map(
            observation["activation"],
            "observation.activation",
            ("desktopMarkerPresent", "vncSecretPresent"),
        )
        ingress = _boolean_map(
            observation["phoneIngress"],
            "observation.phoneIngress",
            ("configured", "creatorAuthenticated", "https"),
        )
        fence_check = require_object(observation["fenceCheck"], "observation.fenceCheck")
    except InputError as exc:
        return _invalid_result(str(exc))

    fence_result = validate_fencing_epoch(fence_check)
    checks: list[dict[str, Any]] = []

    def add_check(check_id: str, passed: bool, observed: Any, required: Any) -> None:
        checks.append(
            {
                "id": check_id,
                "passed": bool(passed),
                "observed": observed,
                "required": required,
            }
        )

    add_check("evidence-integrity", integrity, integrity, True)
    for name in PACKAGE_KEYS:
        add_check(f"package:{name}", packages[name], packages[name], True)
    for name in UNIT_KEYS:
        add_check(
            f"unit-definition:{name}",
            units[name]["definitionPresent"],
            units[name]["definitionPresent"],
            True,
        )
        add_check(
            f"unit-active:{name}", units[name]["active"], units[name]["active"], True
        )
    for name, policy in LISTENER_POLICY.items():
        listener = listeners[name]
        endpoint_ok = (
            listener["address"] == policy["address"]
            and listener["port"] == policy["port"]
        )
        add_check(
            f"listener-endpoint:{name}",
            endpoint_ok,
            {"address": listener["address"], "port": listener["port"]},
            policy,
        )
        add_check(
            f"listener-active:{name}",
            listener["listening"],
            listener["listening"],
            True,
        )
    for name in ("desktopMarkerPresent", "vncSecretPresent"):
        add_check(f"activation:{name}", activation[name], activation[name], True)
    for name in ("configured", "creatorAuthenticated", "https"):
        add_check(f"phone-ingress:{name}", ingress[name], ingress[name], True)

    try:
        fence_observed_at = format_rfc3339(
            parse_rfc3339(fence_check.get("now"), "observation.fenceCheck.now")
        )
    except InputError:
        fence_observed_at = None
    fence_time_matches = fence_observed_at == observed_at
    fence_ready = bool(
        fence_result["inputValid"]
        and fence_result["wouldAllowSideEffect"]
        and fence_time_matches
    )
    add_check(
        "continuity:evaluation-time",
        fence_time_matches,
        fence_observed_at,
        observed_at,
    )
    add_check(
        "continuity:exact-active-fence",
        fence_ready,
        fence_result["decision"],
        "allow-fence",
    )

    definition_ready = bool(
        integrity
        and all(packages.values())
        and all(unit["definitionPresent"] for unit in units.values())
    )
    runtime_ready = bool(
        definition_ready
        and all(activation.values())
        and all(unit["active"] for unit in units.values())
        and all(
            listeners[name]["listening"]
            and listeners[name]["address"] == policy["address"]
            and listeners[name]["port"] == policy["port"]
            for name, policy in LISTENER_POLICY.items()
        )
    )
    phone_ready = bool(runtime_ready and all(ingress.values()))
    if not integrity:
        status = "evidence-unverified"
    elif phone_ready and fence_ready:
        status = "phone-ready-fenced"
    elif phone_ready:
        status = "phone-ready-desktop-only"
    elif runtime_ready:
        status = "desktop-active-no-phone-ingress"
    elif definition_ready:
        status = "desktop-defined-standby"
    else:
        status = "not-ready"

    failed_checks = [item["id"] for item in checks if not item["passed"]]
    evidence_id = canonical_digest(
        {
            "kind": "novnc-desktop-readiness",
            "observedAt": observed_at,
            "observation": observation,
            "status": status,
            "failedChecks": failed_checks,
        }
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "mode": "dry-run",
        "inputValid": True,
        "status": status,
        "evidenceId": evidence_id,
        "observedAt": observed_at,
        "evidenceSource": "caller-supplied-observation",
        "independentlyProbed": False,
        "desktopDefinitionReady": definition_ready,
        "desktopRuntimeReady": runtime_ready,
        "desktopPhoneReady": phone_ready,
        "continuityFenceReady": fence_ready,
        "continuityDecision": fence_result["decision"],
        "coreMindStarted": False,
        "desktopReadinessDoesNotGrantLeadership": True,
        "reasons": failed_checks,
        "checks": checks,
        "observedServiceState": {
            name: {"enabled": units[name]["enabled"], "active": units[name]["active"]}
            for name in UNIT_KEYS
        },
        "executable": False,
        "commands": [],
        "servicesEnabled": [],
        "servicesStarted": [],
        "sideEffects": [],
    }
