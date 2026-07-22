"""Focused tests for caller-supplied noVNC readiness evidence."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


SCAFFOLD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCAFFOLD))

from alpecca_ubuntu_vm.desktop_readiness import evaluate_desktop_readiness  # noqa: E402


EXAMPLE = SCAFFOLD / "contracts" / "desktop-readiness.example.json"


def _observation() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_phone_ready_evidence_is_deterministic_and_does_not_activate_anything() -> None:
    observation = _observation()
    original = copy.deepcopy(observation)
    first = evaluate_desktop_readiness(observation)
    repeated = evaluate_desktop_readiness(observation)

    assert observation == original
    assert first == repeated
    assert first["status"] == "phone-ready-fenced"
    assert first["desktopDefinitionReady"] is True
    assert first["desktopRuntimeReady"] is True
    assert first["desktopPhoneReady"] is True
    assert first["continuityFenceReady"] is True
    assert first["evidenceSource"] == "caller-supplied-observation"
    assert first["independentlyProbed"] is False
    assert first["desktopReadinessDoesNotGrantLeadership"] is True
    assert first["coreMindStarted"] is False
    assert first["commands"] == []
    assert first["servicesEnabled"] == []
    assert first["servicesStarted"] == []
    assert first["sideEffects"] == []


def test_public_novnc_listener_or_missing_auth_blocks_phone_readiness() -> None:
    observation = _observation()
    observation["listeners"]["novnc"]["address"] = "0.0.0.0"
    result = evaluate_desktop_readiness(observation)
    assert result["desktopPhoneReady"] is False
    assert "listener-endpoint:novnc" in result["reasons"]

    observation = _observation()
    observation["phoneIngress"]["creatorAuthenticated"] = False
    result = evaluate_desktop_readiness(observation)
    assert result["desktopRuntimeReady"] is True
    assert result["desktopPhoneReady"] is False
    assert result["status"] == "desktop-active-no-phone-ingress"


def test_unverified_or_mixed_time_evidence_fails_closed() -> None:
    observation = _observation()
    observation["evidenceIntegrityVerified"] = False
    unverified = evaluate_desktop_readiness(observation)
    assert unverified["status"] == "evidence-unverified"
    assert unverified["desktopPhoneReady"] is False

    observation = _observation()
    observation["fenceCheck"]["now"] = "2030-01-02T12:00:02Z"
    mixed = evaluate_desktop_readiness(observation)
    assert mixed["desktopPhoneReady"] is True
    assert mixed["continuityFenceReady"] is False
    assert mixed["status"] == "phone-ready-desktop-only"
    assert "continuity:evaluation-time" in mixed["reasons"]


def test_desktop_can_be_visible_without_claiming_coremind_leadership() -> None:
    observation = _observation()
    observation["fenceCheck"]["leaseId"] = "stale-lease"
    result = evaluate_desktop_readiness(observation)

    assert result["desktopPhoneReady"] is True
    assert result["continuityFenceReady"] is False
    assert result["status"] == "phone-ready-desktop-only"
    assert result["desktopReadinessDoesNotGrantLeadership"] is True
    assert result["coreMindStarted"] is False
