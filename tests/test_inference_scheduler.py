from __future__ import annotations

import pytest

from alpecca.inference_scheduler import (
    InferenceScheduler,
    PriorityLane,
    TaskState,
)


class Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float = 1.0) -> None:
        self.value += seconds


def finish_next(scheduler: InferenceScheduler[str]) -> str:
    task = scheduler.dispatch_next()
    assert task is not None
    scheduler.complete(task.task_id)
    return task.payload


def test_priority_lanes_and_fifo_order_are_deterministic() -> None:
    scheduler = InferenceScheduler[str]()
    scheduler.submit("maintenance", PriorityLane.P4_MAINTENANCE, source="test")
    scheduler.submit("background", PriorityLane.P2_BACKGROUND, source="test")
    scheduler.submit("direct-1", PriorityLane.P0_DIRECT_CONVERSATION, source="test")
    scheduler.submit("direct-2", PriorityLane.P0_DIRECT_CONVERSATION, source="test")
    scheduler.submit("reflection", PriorityLane.P3_REFLECTION, source="test")
    scheduler.submit("interactive", PriorityLane.P1_INTERACTIVE, source="test")

    assert [finish_next(scheduler) for _ in range(6)] == [
        "direct-1",
        "direct-2",
        "interactive",
        "background",
        "reflection",
        "maintenance",
    ]


def test_coalescing_replaces_queued_value_without_moving_it() -> None:
    clock = Clock()
    scheduler = InferenceScheduler[dict[str, int]](clock=clock)
    first = scheduler.submit(
        {"value": 1},
        PriorityLane.P2_BACKGROUND,
        source="sensor-a",
        coalesce_key="room",
        metadata={"sample": 1},
    )
    scheduler.submit({"value": 9}, PriorityLane.P2_BACKGROUND, source="other")
    clock.advance()
    replacement = scheduler.submit(
        {"value": 2},
        PriorityLane.P2_BACKGROUND,
        source="sensor-b",
        coalesce_key="room",
        metadata={"sample": 2},
    )

    assert replacement.accepted and replacement.coalesced
    assert replacement.task is not None and first.task is not None
    assert replacement.task.task_id == first.task.task_id
    assert replacement.task.payload == {"value": 2}
    assert replacement.task.source == "sensor-b"
    assert replacement.task.coalesced_count == 1
    assert scheduler.queued_count == 2
    dispatched = scheduler.dispatch_next()
    assert dispatched is not None
    assert dispatched.task_id == first.task.task_id


def test_queue_bounds_reject_without_dropping_existing_work() -> None:
    lane_bound = InferenceScheduler[str](max_queued=4, max_per_lane=1)
    assert lane_bound.submit(
        "one", PriorityLane.P1_INTERACTIVE, source="test"
    ).accepted
    rejected_lane = lane_bound.submit(
        "two", PriorityLane.P1_INTERACTIVE, source="test"
    )
    assert not rejected_lane.accepted
    assert rejected_lane.reason == "lane_capacity"
    assert [task.payload for task in lane_bound.pending()] == ["one"]

    total_bound = InferenceScheduler[str](max_queued=1, max_per_lane=1)
    total_bound.submit("one", PriorityLane.P4_MAINTENANCE, source="test")
    rejected_total = total_bound.submit(
        "two", PriorityLane.P0_DIRECT_CONVERSATION, source="test"
    )
    assert not rejected_total.accepted
    assert rejected_total.reason == "queue_capacity"
    assert total_bound.stats().rejected == 1


def test_higher_priority_admission_requests_cooperative_interruption() -> None:
    clock = Clock()
    scheduler = InferenceScheduler[str](clock=clock)
    low = scheduler.submit("maintenance", PriorityLane.P4_MAINTENANCE, source="job")
    running = scheduler.dispatch_next()
    assert running is not None and low.task is not None
    clock.advance()
    high = scheduler.submit(
        "reply", PriorityLane.P0_DIRECT_CONVERSATION, source="discord"
    )

    assert high.task is not None
    assert high.interruption_requested_for == running.task_id
    requested = scheduler.snapshot(running.task_id).interruption
    assert requested is not None
    assert requested.reason == "higher_priority_task_queued"
    assert requested.preempting_task_id == high.task.task_id
    assert requested.preempting_lane is PriorityLane.P0_DIRECT_CONVERSATION

    interrupted = scheduler.interrupt_running(
        reason="yielded_at_safe_boundary", requested_by="worker-1"
    )
    assert interrupted.state is TaskState.INTERRUPTED
    assert interrupted.finished_at == clock.value
    dispatched = scheduler.dispatch_next()
    assert dispatched is not None
    assert dispatched.task_id == high.task.task_id


def test_cancellation_metadata_is_recorded_for_active_tasks() -> None:
    clock = Clock()
    scheduler = InferenceScheduler[str](clock=clock)
    queued = scheduler.submit("queued", PriorityLane.P2_BACKGROUND, source="test")
    assert queued.task is not None
    clock.advance()
    cancelled = scheduler.cancel(
        queued.task.task_id, reason="superseded", requested_by="caller"
    )
    assert cancelled.state is TaskState.CANCELLED
    assert cancelled.cancellation is not None
    assert cancelled.cancellation.reason == "superseded"
    assert cancelled.cancellation.requested_by == "caller"
    assert cancelled.cancellation.requested_at == clock.value

    running_result = scheduler.submit(
        "running", PriorityLane.P1_INTERACTIVE, source="test"
    )
    running = scheduler.dispatch_next()
    assert running is not None and running_result.task is not None
    scheduler.cancel(running.task_id, reason="shutdown", requested_by="host")
    assert scheduler.stats().running_task_id is None
    assert scheduler.stats().cancelled == 2


def test_starvation_prevention_eventually_dispatches_old_lower_lane_head() -> None:
    scheduler = InferenceScheduler[str](starvation_after=2)
    scheduler.submit("maintenance", PriorityLane.P4_MAINTENANCE, source="test")

    scheduler.submit("p0-1", PriorityLane.P0_DIRECT_CONVERSATION, source="test")
    assert finish_next(scheduler) == "p0-1"
    scheduler.submit("p0-2", PriorityLane.P0_DIRECT_CONVERSATION, source="test")
    assert finish_next(scheduler) == "p0-2"
    scheduler.submit("p0-3", PriorityLane.P0_DIRECT_CONVERSATION, source="test")

    assert finish_next(scheduler) == "maintenance"
    assert finish_next(scheduler) == "p0-3"


def test_snapshots_copy_and_protect_metadata() -> None:
    metadata = {"origin": "unit-test"}
    scheduler = InferenceScheduler[str]()
    result = scheduler.submit(
        "work", PriorityLane.P2_BACKGROUND, source="test", metadata=metadata
    )
    assert result.task is not None
    metadata["origin"] = "mutated"
    assert result.task.metadata["origin"] == "unit-test"
    with pytest.raises(TypeError):
        result.task.metadata["origin"] = "blocked"  # type: ignore[index]


def test_completion_requires_the_current_running_task() -> None:
    scheduler = InferenceScheduler[str]()
    result = scheduler.submit("work", PriorityLane.P1_INTERACTIVE, source="test")
    assert result.task is not None
    with pytest.raises(ValueError, match="not running"):
        scheduler.complete(result.task.task_id)
    running = scheduler.dispatch_next()
    assert running is not None
    completed = scheduler.complete(running.task_id)
    assert completed.state is TaskState.COMPLETED
    assert scheduler.stats().completed == 1
