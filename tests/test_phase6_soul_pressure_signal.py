"""Pure mapping tests for Soul-facing memory and resource pressure signals."""
from __future__ import annotations

import dataclasses

import pytest

from alpecca import resource_signals
from alpecca import soul_pressure_signal


def test_unknown_inputs_remain_unknown_and_create_no_intention():
    resource = resource_signals.assess_resources()
    result = soul_pressure_signal.build_soul_pressure_signal(None, resource)

    assert result.vector.values == (None, None, None, None, None)
    assert result.vector.known_mask == (0, 0, 0, 0, 0)
    assert result.vector.overall is None
    assert result.vector.known_fraction == 0.0
    assert result.hints == ()
    assert result.as_snapshot_memory_pressure()["context_fill"] is None


def test_disabled_mindpage_zeroes_are_unknown_not_low_pressure():
    result = soul_pressure_signal.build_soul_pressure_signal({
        "enabled": False,
        "source": "disabled",
        "context_fill": 0.0,
        "pressure_score": 0.0,
        "pressure": "unavailable",
        "disk_fill": 0.0,
    })

    assert result.vector.context is None
    assert result.vector.page_store is None
    assert result.vector.overflow is None
    assert result.vector.overall is None


def test_low_known_pressure_maps_to_numbers_without_hints():
    memory = {
        "enabled": True,
        "source": "estimated_request",
        "context_fill": 0.3,
        "unsummarized_eviction_backlog": 0,
        "disk_fill": 0.1,
        "overflow": False,
        "context_fits": True,
    }
    resource = resource_signals.assess_resources(
        cpu_percent=20,
        ram_used_bytes=30,
        ram_total_bytes=100,
        commit_used_bytes=25,
        commit_limit_bytes=100,
    )
    result = soul_pressure_signal.map_pressure_signals(memory, resource)

    assert result.vector.values == (0.3, 0.0, 0.1, 0.0, 0.3)
    assert result.vector.known_mask == (1, 1, 1, 1, 1)
    assert result.vector.overall == 0.3
    assert result.vector.known_fraction == 1.0
    assert result.hints == ()


def test_high_context_and_host_pressure_create_bounded_operational_hints():
    memory = {
        "enabled": True,
        "context_fill": 0.94,
        "unsummarized_eviction_backlog": 4,
        "disk_fill": 0.2,
        "overflow": False,
    }
    resource = resource_signals.assess_resources(
        cpu_percent=70,
        ram_used_bytes=88,
        ram_total_bytes=100,
        commit_used_bytes=86,
        commit_limit_bytes=100,
    )
    result = soul_pressure_signal.build_soul_pressure_signal(memory, resource)

    assert result.vector.context == 0.94
    assert result.vector.eviction == 0.5
    assert result.vector.host == 0.88
    assert result.vector.overall == 0.94
    assert [hint.action for hint in result.hints] == [
        "consolidate_working_memory",
        "defer_optional_work",
        "summarize_eviction_backlog",
    ]
    for hint in result.hints:
        assert hint.subagent == "Reflector"
        assert hint.subagent in soul_pressure_signal.EXISTING_SOUL_ROLES
        assert hint.category == "self_care"
        assert hint.rank == 4
        assert 0.0 <= hint.urgency <= 1.0


def test_overflow_and_out_of_range_values_cap_deterministically():
    memory = {
        "enabled": True,
        "context_fill": 4.0,
        "unsummarized_eviction_backlog": 1000,
        "disk_fill": 9.0,
        "disk_over_budget": True,
        "overflow": True,
        "fixed_overflow": True,
        "overflow_tokens": 50_000,
        "paging_error": "disk write unavailable",
    }
    resource = {
        "pressure": 7.0,
        "severity": "critical",
        "reasons": [
            {"resource": "commit"},
            {"resource": "thermal"},
            {"resource": "disk"},
        ],
    }

    first = soul_pressure_signal.build_soul_pressure_signal(memory, resource)
    second = soul_pressure_signal.build_soul_pressure_signal(memory, resource)

    assert first == second
    assert first.vector.values == (1.0, 1.0, 1.0, 1.0, 1.0)
    assert first.vector.overall == 1.0
    assert first.vector.known_fraction == 1.0
    assert len(first.hints) == soul_pressure_signal.MAX_HINTS
    assert first.hints[0].action == "resolve_context_overflow"
    assert {hint.action for hint in first.hints} <= {
        "resolve_context_overflow",
        "defer_optional_work",
        "inspect_paging_failure",
        "consolidate_working_memory",
        "summarize_eviction_backlog",
        "compact_page_store",
    }
    assert all(hint.urgency <= 1.0 for hint in first.hints)


def test_normalized_resource_readings_shape_is_supported():
    normalized = resource_signals.normalize_readings(
        cpu_percent=80,
        ram_used_bytes=40,
        ram_total_bytes=100,
        battery_percent=20,
        battery_charging=False,
    )
    result = soul_pressure_signal.build_soul_pressure_signal({}, normalized)

    assert result.vector.context is None
    assert result.vector.host == 0.8
    assert result.vector.overall == 0.8
    assert [hint.action for hint in result.hints] == ["defer_optional_work"]


@pytest.mark.parametrize(
    "bad_value",
    [None, True, "0.9", float("nan"), float("inf")],
)
def test_invalid_numeric_context_values_remain_unknown(bad_value):
    result = soul_pressure_signal.build_soul_pressure_signal({
        "enabled": True,
        "context_fill": bad_value,
    })

    assert result.vector.context is None
    assert result.vector.overall is None
    assert result.hints == ()


def test_snapshot_payload_is_compact_numeric_and_contains_no_prompt_or_feeling_text():
    result = soul_pressure_signal.build_soul_pressure_signal({
        "enabled": True,
        "context_fill": 0.95,
        "overflow": False,
    })
    payload = result.as_snapshot_memory_pressure()
    rendered = repr(payload).lower()

    assert payload["signal_vector"]["order"] == list(soul_pressure_signal.VECTOR_ORDER)
    assert len(payload["signal_vector"]["values"]) == 5
    assert payload["intention_hints"][0]["action"] == "consolidate_working_memory"
    for prohibited in ("feel", "emotion", "conscious", "afraid"):
        assert prohibited not in rendered


def test_result_and_inputs_are_immutable_or_unmodified():
    memory = {"enabled": True, "context_fill": 0.8, "overflow": False}
    resource = resource_signals.assess_resources(cpu_percent=20)
    memory_before = dict(memory)
    resource_before = dict(resource)
    result = soul_pressure_signal.build_soul_pressure_signal(memory, resource)

    assert memory == memory_before
    assert resource == resource_before
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.vector.context = 0.0
