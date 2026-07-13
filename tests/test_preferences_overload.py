"""Isolated tests for the grounded overload / read-the-room signal (Lane Q).

The signal must be honest: it reads ONLY from real measured cues, cites the
evidence, leaves anything unmeasured as explicit ``unknown`` (never a fabricated
zero), and never claims an emotion. These tests pin all of that, including that
an unknown cue is dropped rather than counted as no-load, and that the signal
composes cleanly with the real (fail-closed) host measurement.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpecca import overload  # noqa: E402
from alpecca import system_pressure  # noqa: E402


# --- cue builders: unknown stays unknown ------------------------------------


def test_message_volume_cue_unknown_without_count():
    cue = overload.message_volume_cue(None, 60.0)
    assert cue.state == "unknown"
    assert cue.normalized is None
    known = overload.message_volume_cue(6, 60.0)
    assert known.state == "known"
    assert known.normalized == pytest.approx(0.5)
    assert known.evidence["message_count"] == 6


def test_concurrent_actor_cue_baseline_and_missing():
    # One actor is her normal one-to-one baseline: zero added load.
    assert overload.concurrent_actor_cue(1).normalized == pytest.approx(0.0)
    # Zero actors is also zero load (no one is here) -- but it is a real reading.
    assert overload.concurrent_actor_cue(0).state == "known"
    # Extra actors add load.
    assert overload.concurrent_actor_cue(3).normalized == pytest.approx(0.5)
    # A missing count is unknown, not an assumed-zero.
    assert overload.concurrent_actor_cue(None).state == "unknown"


def test_context_pressure_cue_range():
    assert overload.context_pressure_cue(0.8).normalized == pytest.approx(0.8)
    assert overload.context_pressure_cue(None).state == "unknown"
    assert overload.context_pressure_cue(1.5).state == "invalid"
    assert overload.context_pressure_cue(-0.1).state == "invalid"


def test_host_pressure_cue_inverts_headroom():
    # Low headroom == high load.
    assert overload.host_pressure_cue(0.2).normalized == pytest.approx(0.8)
    assert overload.host_pressure_cue(None).state == "unknown"
    assert overload.host_pressure_cue(2.0).state == "invalid"


def test_host_pressure_cue_from_real_measurement_inherits_honestly():
    # Compose with the REAL Phase 6/7 sampler. Whatever it reports -- a known
    # headroom or an explicit unknown -- the cue must inherit it honestly and
    # never fabricate. It is never 'invalid', and state/normalized stay
    # consistent (known <-> a real number; unknown <-> None).
    measurement = system_pressure.measure_host_pressure()
    cue = overload.host_pressure_cue_from_measurement(measurement)
    assert cue.state in {"known", "unknown"}
    if cue.state == "known":
        assert cue.normalized is not None
        assert 0.0 <= cue.normalized <= 1.0
    else:
        assert cue.normalized is None


def test_host_pressure_cue_from_measurement_unknown_when_no_headroom():
    # An explicit unknown host measurement must yield an unknown cue, not a
    # fabricated calm host.
    assert (
        overload.host_pressure_cue_from_measurement({"headroom": {}}).state
        == "unknown"
    )
    assert (
        overload.host_pressure_cue_from_measurement("not-a-mapping").state
        == "unknown"
    )


def test_host_pressure_cue_from_measurement_reads_known_headroom():
    measurement = {
        "headroom": {"commit_fraction": 0.4, "disk_fraction": 0.1},
    }
    cue = overload.host_pressure_cue_from_measurement(measurement)
    assert cue.state == "known"
    # Worst (smallest) headroom drives the load: 1 - 0.1 = 0.9.
    assert cue.normalized == pytest.approx(0.9)


# --- assessment: grounding + no fabrication ---------------------------------


def test_no_cues_is_unknown_not_zero():
    result = overload.assess_overload()
    assert result["state"] == "unknown"
    assert result["value"] is None
    assert result["band"] == "unknown"
    assert set(result["unknown_cues"]) == set(overload.CUE_NAMES)
    assert "no_known_cue_evidence" in result["reasons"]
    # It never claims an emotion.
    assert result["kind"] == "workload_pressure"
    assert "not an emotion" in result["disclaimer"]


def test_unknown_cue_is_dropped_not_counted_as_zero():
    # A single high known cue with the rest unknown must read high -- if unknown
    # cues were fabricated to zero, the mean would be diluted to ~0.225.
    result = overload.assess_overload(
        host_pressure=overload.host_pressure_cue(0.1),
    )
    assert result["state"] == "partial"
    assert result["value"] == pytest.approx(0.9)
    assert result["band"] == "high"
    assert result["known_cues"] == ["host_pressure"]
    assert "partial_cue_evidence" in result["reasons"]


def test_all_known_cues_combine_to_known_value():
    result = overload.assess_overload(
        message_volume=overload.message_volume_cue(6, 60.0),   # 0.5, w=1.0
        concurrent_actors=overload.concurrent_actor_cue(3),    # 0.5, w=1.0
        context_pressure=overload.context_pressure_cue(0.8),   # 0.8, w=1.2
        host_pressure=overload.host_pressure_cue(0.2),         # 0.8, w=1.2
    )
    assert result["state"] == "known"
    # (0.5 + 0.5 + 1.2*0.8 + 1.2*0.8) / 4.4
    assert result["value"] == pytest.approx(2.92 / 4.4, abs=1e-4)
    assert result["band"] == "elevated"
    assert result["unknown_cues"] == []
    assert result["invalid_cues"] == []
    # Every cue is cited with its real reading.
    names = {e["name"] for e in result["evidence"]}
    assert names == set(overload.CUE_NAMES)


def test_invalid_cue_is_surfaced_and_excluded():
    result = overload.assess_overload(
        context_pressure=overload.context_pressure_cue(1.5),   # invalid
        host_pressure=overload.host_pressure_cue(0.2),         # 0.8 known
    )
    assert "context_pressure" in result["invalid_cues"]
    assert result["known_cues"] == ["host_pressure"]
    assert result["value"] == pytest.approx(0.8)
    assert "invalid_cue_evidence" in result["reasons"]


def test_higher_readings_yield_higher_value():
    calm = overload.assess_overload(
        host_pressure=overload.host_pressure_cue(0.9),  # load 0.1
    )
    busy = overload.assess_overload(
        host_pressure=overload.host_pressure_cue(0.1),  # load 0.9
    )
    assert calm["value"] < busy["value"]
    assert calm["band"] == "low"
    assert busy["band"] == "high"


def test_mismatched_cue_object_is_rejected_as_invalid():
    # Passing a cue under the wrong keyword must not silently mislabel evidence.
    result = overload.assess_overload(
        message_volume=overload.host_pressure_cue(0.2),
    )
    assert "message_volume" in result["invalid_cues"]
