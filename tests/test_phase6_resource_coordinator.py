"""Focused tests for the pure Phase 6 optional-work coordinator."""
from __future__ import annotations

import threading

import pytest

from alpecca.resource_coordinator import ResourceCoordinator


class _Clock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        self.value += 1.0
        return self.value


def test_single_flight_rejects_overlaps_and_records_start_finish_telemetry():
    coordinator = ResourceCoordinator(clock=_Clock())

    first = coordinator.start("reflection")
    overlap = coordinator.start("backfill")
    finished = coordinator.finish(first.lease)
    next_job = coordinator.start("routine")

    assert first.accepted is True and first.lease is not None
    assert overlap.accepted is False and overlap.reason == "optional-work-active"
    assert finished.state == "finished"
    assert next_job.accepted is True and next_job.lease is not None
    assert [item.event for item in coordinator.telemetry()] == [
        "start", "rejected", "finish", "start"
    ]


def test_foreground_chat_or_tts_rejects_optional_work_and_cancels_active_lease():
    coordinator = ResourceCoordinator(clock=_Clock())

    coordinator.set_foreground(chat_active=True, tts_active=False)
    chat_blocked = coordinator.start("reflection")
    coordinator.set_foreground(chat_active=False, tts_active=True)
    tts_blocked = coordinator.start("backfill")
    coordinator.set_foreground(chat_active=False, tts_active=False)
    accepted = coordinator.start("routine")
    coordinator.set_foreground(chat_active=True, tts_active=False)

    assert chat_blocked.reason == "chat-active"
    assert tts_blocked.reason == "tts-active"
    assert accepted.lease is not None and accepted.lease.cancelled is True
    assert coordinator.active() is accepted.lease
    assert coordinator.finish(accepted.lease).state == "cancelled"
    assert [item.event for item in coordinator.telemetry()] == [
        "rejected", "rejected", "start", "cancel"
    ]


def test_run_supports_cooperative_cancellation_and_error_telemetry():
    coordinator = ResourceCoordinator(clock=_Clock())

    def cancelled_worker(lease):
        assert coordinator.cancel(lease, "chat-began") is True
        assert lease.allow_work() is False
        return "discarded"

    cancelled = coordinator.run("reflection", cancelled_worker)

    def failed_worker(_lease):
        raise RuntimeError("backfill broke")

    failed = coordinator.run("backfill", failed_worker)

    assert cancelled.state == "cancelled"
    assert cancelled.value == "discarded"
    assert failed.state == "error"
    assert "RuntimeError: backfill broke" in failed.reason
    assert [item.event for item in coordinator.telemetry()] == [
        "start", "cancel", "start", "error"
    ]


def test_lock_allows_only_one_concurrent_start_and_rejects_unknown_categories():
    coordinator = ResourceCoordinator(clock=_Clock())
    barrier = threading.Barrier(3)
    decisions = []
    decisions_lock = threading.Lock()

    def request(category):
        barrier.wait()
        decision = coordinator.start(category)
        with decisions_lock:
            decisions.append(decision)

    first = threading.Thread(target=request, args=("reflection",))
    second = threading.Thread(target=request, args=("routine",))
    first.start()
    second.start()
    barrier.wait()
    first.join(timeout=1)
    second.join(timeout=1)

    assert len(decisions) == 2
    assert sum(decision.accepted for decision in decisions) == 1
    accepted = next(decision for decision in decisions if decision.accepted)
    assert accepted.lease is not None
    assert coordinator.finish(accepted.lease).state == "finished"
    with pytest.raises(ValueError, match="unknown optional category"):
        coordinator.start("chat")  # type: ignore[arg-type]
