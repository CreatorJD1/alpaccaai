from __future__ import annotations

import pytest

from alpecca.observer_slots import ObserverSlot


class Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_publish_records_typed_value_provenance_and_timestamps() -> None:
    wall = Clock(1_700_000_000.0)
    monotonic = Clock(25.0)
    slot = ObserverSlot[int](int, wall_clock=wall, monotonic_clock=monotonic)
    metadata = {"transport": "local"}

    result = slot.publish(
        42,
        source="host-pressure",
        observed_at=1_699_999_999.5,
        event_id="sample-7",
        metadata=metadata,
    )

    assert result.accepted
    observation = result.observation
    assert observation is not None
    assert observation.value == 42
    assert observation.version == 1
    assert observation.observed_at == 1_699_999_999.5
    assert observation.published_at == wall.value
    assert observation.received_monotonic == monotonic.value
    assert observation.provenance.source == "host-pressure"
    assert observation.provenance.event_id == "sample-7"
    metadata["transport"] = "mutated"
    assert observation.provenance.metadata["transport"] == "local"
    with pytest.raises(TypeError):
        observation.provenance.metadata["transport"] = "blocked"  # type: ignore[index]


def test_value_type_is_enforced() -> None:
    slot = ObserverSlot[int](int)
    with pytest.raises(TypeError, match="int"):
        slot.publish("wrong", source="test")  # type: ignore[arg-type]


def test_older_observation_is_rejected_without_replacing_latest() -> None:
    wall = Clock(100.0)
    monotonic = Clock(10.0)
    slot = ObserverSlot[str](str, wall_clock=wall, monotonic_clock=monotonic)
    newest = slot.publish("new", source="sensor", observed_at=20.0)
    wall.advance(1.0)
    monotonic.advance(1.0)
    stale = slot.publish("old", source="sensor", observed_at=19.0)

    assert newest.observation is not None
    assert not stale.accepted
    assert stale.reason == "out_of_order"
    assert stale.observation is None
    assert stale.current == newest.observation
    assert slot.read() == newest.observation


def test_equal_observed_timestamp_is_a_deterministic_later_version() -> None:
    slot = ObserverSlot[str](str)
    first = slot.publish("first", source="sensor", observed_at=20.0)
    second = slot.publish("second", source="sensor", observed_at=20.0)

    assert first.observation is not None and second.observation is not None
    assert second.accepted
    assert second.observation.version == first.observation.version + 1
    assert slot.read().value == "second"  # type: ignore[union-attr]


def test_freshness_uses_monotonic_receive_time() -> None:
    wall = Clock(1_000.0)
    monotonic = Clock(50.0)
    slot = ObserverSlot[float](float, wall_clock=wall, monotonic_clock=monotonic)
    published = slot.publish(0.75, source="pressure", observed_at=10.0)
    assert published.observation is not None

    wall.advance(10_000.0)
    monotonic.advance(4.0)
    assert slot.read_fresh(5.0) == published.observation
    monotonic.advance(2.0)
    assert slot.read_fresh(5.0) is None
    status = slot.status(max_age_seconds=5.0)
    assert status.age_seconds == 6.0
    assert status.stale is True


def test_clear_can_compare_the_latest_version() -> None:
    slot = ObserverSlot[str](str)
    first = slot.publish("one", source="test").observation
    assert first is not None
    assert slot.clear(expected_version=first.version + 1) is None
    assert slot.read() == first
    assert slot.clear(expected_version=first.version) == first
    assert slot.read() is None

    second = slot.publish("two", source="test").observation
    assert second is not None
    assert second.version == 2


@pytest.mark.parametrize("timestamp", [-1, float("inf"), float("nan")])
def test_invalid_observation_timestamps_are_rejected(timestamp: float) -> None:
    slot = ObserverSlot[str](str)
    with pytest.raises(ValueError, match="observed_at"):
        slot.publish("value", source="test", observed_at=timestamp)


def test_source_and_event_id_must_be_non_empty() -> None:
    slot = ObserverSlot[str](str)
    with pytest.raises(ValueError, match="source"):
        slot.publish("value", source=" ")
    with pytest.raises(ValueError, match="event_id"):
        slot.publish("value", source="test", event_id="")
