"""Focused tests for the pure Phase 6 resource-shedding policy."""
from __future__ import annotations

from alpecca import resource_policy


def test_unknown_signals_allow_work_without_claiming_normal_pressure():
    decision = resource_policy.decide()

    assert decision["action"] == "allow_normal_work"
    assert decision["allow_normal_work"] is True
    assert decision["evidence_state"] == "unknown"
    assert decision["resource"] == {
        "state": "unknown",
        "pressure": None,
        "severity": "unknown",
    }
    assert decision["memory"]["state"] == "unknown"
    assert decision["memory"]["context_fill"] is None
    assert decision["reasons"] == ()


def test_normal_observed_signals_allow_normal_work():
    decision = resource_policy.decide(
        {"pressure": 0.22, "severity": "normal"},
        {
            "enabled": True,
            "context_fill": 0.34,
            "pressure": "low",
            "overflow": False,
            "fixed_overflow": False,
            "context_fits": True,
        },
    )

    assert decision["action"] == "allow_normal_work"
    assert decision["evidence_state"] == "observed"
    assert decision["defer_optional_work"] is False
    assert decision["reduce_context"] is False
    assert decision["require_recovery_notice"] is False
    assert decision["reasons"] == ()


def test_warning_pressure_defers_optional_work_without_reducing_context():
    decision = resource_policy.decide(
        {"pressure": 0.74, "severity": "elevated"},
        {"enabled": True, "context_fill": 0.42, "pressure": "low"},
    )

    assert decision["action"] == "defer_optional_work"
    assert decision["defer_optional_work"] is True
    assert decision["reduce_context"] is False
    assert decision["require_recovery_notice"] is False
    assert decision["resource"]["severity"] == "warning"
    assert decision["reasons"] == ("resource_warning",)


def test_critical_resource_pressure_requires_user_visible_recovery_notice():
    decision = resource_policy.decide(
        {"pressure": 0.97, "severity": "critical"},
        {"enabled": False},
    )

    assert decision["action"] == "recovery_notice"
    assert decision["defer_optional_work"] is True
    assert decision["reduce_context"] is True
    assert decision["require_recovery_notice"] is True
    assert decision["evidence_state"] == "partial"
    assert decision["reasons"] == ("resource_critical",)


def test_reducible_overflow_reduces_context_but_fixed_overflow_requires_notice():
    reducible = resource_policy.decide(
        memory_pressure={
            "enabled": True,
            "context_fill": 1.0,
            "overflow": True,
            "fixed_overflow": False,
            "context_fits": False,
        }
    )
    fixed = resource_policy.decide(
        memory_pressure={
            "enabled": True,
            "context_fill": 1.0,
            "overflow": True,
            "fixed_overflow": True,
            "unshrinkable": True,
            "context_fits": False,
        }
    )

    assert reducible["action"] == "reduce_context"
    assert reducible["reduce_context"] is True
    assert reducible["require_recovery_notice"] is False
    assert reducible["reasons"] == ("memory_overflow",)
    assert fixed["action"] == "recovery_notice"
    assert fixed["require_recovery_notice"] is True
    assert fixed["reasons"] == ("memory_fixed_overflow",)
