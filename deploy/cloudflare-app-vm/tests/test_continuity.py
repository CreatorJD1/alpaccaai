"""Focused one-desktop continuity lease tests."""
from __future__ import annotations

import copy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cloudflare_app_vm.continuity import evaluate_desktop_lease  # noqa: E402


def _request(holder: str, expected: int | None = None) -> dict:
    return {
        "schemaVersion": 1,
        "nowEpochSeconds": 100,
        "state": {"highestFencingEpoch": 4, "activeLease": None},
        "request": {
            "holderId": holder,
            "requestedTtlSeconds": 30,
            "creatorApproved": True,
            "desktopOnlyAttested": True,
            "expectedFencingEpoch": expected,
        },
    }


def test_new_holder_gets_strictly_newer_fence_without_side_effects() -> None:
    value = _request("desktop-a")
    original = copy.deepcopy(value)
    result = evaluate_desktop_lease(value)

    assert value == original
    assert result["decision"] == "would-acquire"
    assert result["proposedNextState"]["highestFencingEpoch"] == 5
    assert result["proposedNextState"]["activeLease"]["fencingEpoch"] == 5
    assert result["wouldStartCoreMind"] is False
    assert result["sideEffects"] == []


def test_second_desktop_is_denied_while_first_lease_is_active() -> None:
    value = _request("desktop-b")
    value["state"] = {
        "highestFencingEpoch": 7,
        "activeLease": {
            "holderId": "desktop-a",
            "fencingEpoch": 7,
            "expiresAtEpochSeconds": 120,
        },
    }
    result = evaluate_desktop_lease(value)

    assert result["decision"] == "deny"
    assert "another-desktop-holder-active" in result["reasons"]
    assert result["proposedNextState"] is None


def test_expired_holder_replacement_increments_fence() -> None:
    value = _request("desktop-b")
    value["state"] = {
        "highestFencingEpoch": 7,
        "activeLease": {
            "holderId": "desktop-a",
            "fencingEpoch": 7,
            "expiresAtEpochSeconds": 100,
        },
    }
    result = evaluate_desktop_lease(value)

    assert result["decision"] == "would-acquire"
    assert result["proposedNextState"]["activeLease"]["fencingEpoch"] == 8


def test_renewal_requires_exact_holder_fence_and_approval() -> None:
    value = _request("desktop-a", expected=7)
    value["state"] = {
        "highestFencingEpoch": 7,
        "activeLease": {
            "holderId": "desktop-a",
            "fencingEpoch": 7,
            "expiresAtEpochSeconds": 120,
        },
    }
    assert evaluate_desktop_lease(value)["decision"] == "would-renew"

    value["request"]["expectedFencingEpoch"] = 6
    assert "renewal-fence-mismatch" in evaluate_desktop_lease(value)["reasons"]
    value["request"]["expectedFencingEpoch"] = 7
    value["request"]["creatorApproved"] = False
    assert "creator-approval-missing" in evaluate_desktop_lease(value)["reasons"]
