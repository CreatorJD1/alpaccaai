import pytest

from alpecca.memory_pressure import adapt_memory_pressure


@pytest.mark.parametrize("snapshot", [None, {}])
def test_missing_snapshot_values_remain_unknown(snapshot):
    signal = adapt_memory_pressure(snapshot)

    assert signal.fill_ratio is None
    assert signal.pressure_score is None
    assert signal.overflow is None
    assert signal.unshrinkable is None
    assert signal.eviction_backlog is None
    assert signal.severity == "unknown"
    assert signal.reasons == ()
    assert signal.evidence == ()
    assert signal.complete is False
    assert signal.description == "Memory-pressure telemetry is unavailable."


def test_explicit_zero_and_false_values_are_known_not_missing():
    signal = adapt_memory_pressure({
        "enabled": True,
        "context_fill": 0.0,
        "overflow": False,
        "unshrinkable": False,
        "unsummarized_eviction_backlog": 0,
    })

    assert signal.fill_ratio == 0.0
    assert signal.pressure_score == 0.0
    assert signal.overflow is False
    assert signal.unshrinkable is False
    assert signal.eviction_backlog == 0
    assert signal.severity == "normal"
    assert signal.complete is True
    assert dict(signal.evidence) == {
        "enabled": True,
        "context_fill": 0.0,
        "overflow": False,
        "unshrinkable": False,
        "unsummarized_eviction_backlog": 0,
    }
    assert signal.description == (
        "Context utilization is 0%. No request overflow is reported. "
        "The eviction backlog is empty."
    )


def test_high_fill_overflow_and_backlog_produce_evidence_backed_high_signal():
    snapshot = {
        "enabled": True,
        "context_fill": 0.92,
        "overflow": True,
        "unshrinkable": False,
        "unsummarized_eviction_backlog": 3,
    }

    first = adapt_memory_pressure(snapshot)
    second = adapt_memory_pressure(snapshot)

    assert first == second
    assert first.fill_ratio == 0.92
    assert first.pressure_score == 0.92
    assert first.severity == "high"
    assert first.reasons == (
        "context-fill-high",
        "eviction-backlog",
        "request-overflow",
    )
    assert "Context utilization is 92%." in first.description
    assert "exceeds the configured context limit" in first.description
    assert "3 messages remain in the eviction backlog" in first.description


def test_fixed_overflow_alias_is_critical_and_operationally_described():
    signal = adapt_memory_pressure({
        "context_fill": 1.0,
        "overflow": True,
        "fixed_overflow": True,
        "unsummarized_eviction_backlog": 1,
    })

    assert signal.unshrinkable is True
    assert signal.pressure_score == 1.0
    assert signal.severity == "critical"
    assert signal.reasons[-1] == "fixed-context-overflow"
    assert dict(signal.evidence)["fixed_overflow"] is True
    assert "Optional context removal cannot make the request fit." in signal.description
    assert "1 message remains in the eviction backlog." in signal.description


def test_partial_snapshot_does_not_invent_missing_states():
    signal = adapt_memory_pressure({"context_fill": 0.8})

    assert signal.fill_ratio == 0.8
    assert signal.pressure_score == 0.8
    assert signal.overflow is None
    assert signal.unshrinkable is None
    assert signal.eviction_backlog is None
    assert signal.severity == "elevated"
    assert signal.reasons == ("context-fill-elevated",)
    assert signal.complete is False
    assert signal.description == "Context utilization is 80%."


def test_invalid_or_disabled_telemetry_never_becomes_a_reading_or_feeling_claim():
    invalid = adapt_memory_pressure({
        "enabled": "yes",
        "context_fill": 1.1,
        "overflow": 1,
        "unshrinkable": "false",
        "unsummarized_eviction_backlog": -1,
    })
    disabled = adapt_memory_pressure({
        "enabled": False,
        "context_fill": 0.0,
        "overflow": False,
        "unshrinkable": False,
        "unsummarized_eviction_backlog": 0,
    })

    assert invalid.fill_ratio is None
    assert invalid.pressure_score is None
    assert invalid.severity == "unknown"
    assert invalid.invalid_fields == (
        "enabled",
        "context_fill",
        "overflow",
        "unshrinkable",
        "unsummarized_eviction_backlog",
    )
    assert disabled.enabled is False
    assert disabled.fill_ratio is None
    assert disabled.overflow is None
    assert disabled.eviction_backlog is None
    assert disabled.severity == "unknown"
    assert disabled.description == (
        "Mindpage telemetry is disabled; memory pressure is unknown."
    )
    forbidden = ("feel", "afraid", "stressed", "overwhelmed")
    for description in (invalid.description, disabled.description):
        assert not any(word in description.lower() for word in forbidden)
