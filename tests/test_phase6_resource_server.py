"""Focused server integration tests for Phase 6 optional-work coordination."""
from __future__ import annotations

import asyncio
import threading

import pytest

from alpecca.resource_coordinator import ResourceCoordinator
import server


@pytest.fixture
def optional_work(monkeypatch):
    coordinator = ResourceCoordinator()
    monkeypatch.setattr(server, "_optional_work_coordinator", coordinator)
    monkeypatch.setattr(server, "active_chat_turns", 0)
    monkeypatch.setattr(server, "active_tts_requests", 0)
    monkeypatch.setattr(server, "last_chat_turn_started", 0.0)
    return coordinator


def test_optional_work_skips_overlap_and_defers_for_chat_or_tts(
    monkeypatch, optional_work
):
    calls: list[str] = []

    async def immediate_bounded(_label, fn, *args, **kwargs):
        kwargs.pop("timeout", None)
        return fn(*args, **kwargs)

    monkeypatch.setattr(server, "_bounded_thread", immediate_bounded)
    held = optional_work.start("reflection")
    assert held.lease is not None

    async def exercise() -> tuple[dict, str, dict, dict]:
        overlap = await server._optional_bounded_thread(
            "backfill", "backfill", lambda: calls.append("overlap")
        )
        optional_work.finish(held.lease)
        completed = await server._optional_bounded_thread(
            "reflection", "reflection", lambda: "done"
        )

        server.active_chat_turns = 1
        chat_deferred = await server._optional_bounded_thread(
            "routine", "routine", lambda: calls.append("chat")
        )
        server.active_chat_turns = 0
        server.active_tts_requests = 1
        tts_deferred = await server._optional_bounded_thread(
            "routine", "routine", lambda: calls.append("tts")
        )
        return overlap, completed, chat_deferred, tts_deferred

    overlap, completed, chat_deferred, tts_deferred = asyncio.run(exercise())

    assert overlap == {
        "status": "deferred",
        "reason": "optional-work-active",
        "category": "backfill",
    }
    assert completed == "done"
    assert chat_deferred["reason"] == "chat-active"
    assert tts_deferred["reason"] == "tts-active"
    assert calls == []
    assert [item.event for item in optional_work.telemetry()] == [
        "start",
        "rejected",
        "finish",
        "start",
        "finish",
        "rejected",
        "rejected",
    ]


def test_timeout_keeps_optional_lease_until_worker_exits(monkeypatch, optional_work):
    started = threading.Event()
    release = threading.Event()

    def work():
        started.set()
        release.wait(1.0)
        return "late"

    async def timed_out_bounded(_label, fn, *args, **kwargs):
        kwargs.pop("timeout", None)
        thread = threading.Thread(target=fn, args=args, daemon=True)
        thread.start()
        assert started.wait(1.0)
        return None

    monkeypatch.setattr(server, "_bounded_thread", timed_out_bounded)

    async def exercise() -> dict:
        assert await server._optional_bounded_thread(
            "reflection", "reflect", work, timeout=0.2
        ) is None
        active = optional_work.active()
        assert active is not None and active.cancelled is True
        deferred = await server._optional_bounded_thread(
            "backfill", "backfill", lambda: "should not run"
        )
        release.set()
        for _ in range(100):
            if optional_work.active() is None:
                break
            await asyncio.sleep(0.01)
        assert optional_work.active() is None
        return deferred

    deferred = asyncio.run(exercise())

    assert deferred["reason"] == "optional-work-active"
    assert [item.event for item in optional_work.telemetry()] == [
        "start",
        "cancel",
        "rejected",
    ]


def test_tts_route_defers_optional_work_while_synthesis_is_active(
    monkeypatch, optional_work
):
    from alpecca import tts as tts_mod

    started = threading.Event()
    release = threading.Event()

    class JsonRequest:
        async def json(self):
            return {"text": "Speak this"}

    def synth(_text, _state):
        started.set()
        release.wait(1.0)
        return "audio/wav", b"wav"

    monkeypatch.setattr(tts_mod, "synth", synth)

    async def exercise() -> tuple[dict, int]:
        tts_task = asyncio.create_task(server.tts(JsonRequest()))
        assert await asyncio.to_thread(started.wait, 1.0)
        assert server.active_tts_requests == 1
        deferred = await server._optional_bounded_thread(
            "reflection", "reflect", lambda: "should not run"
        )
        release.set()
        response = await tts_task
        return deferred, response.status_code

    deferred, status_code = asyncio.run(exercise())

    assert deferred["reason"] == "tts-active"
    assert status_code == 200
    assert server.active_tts_requests == 0


def test_routines_use_routine_category_and_leave_deferred_rows_unrecorded(
    monkeypatch, optional_work
):
    calls: list[tuple[str, str]] = []
    observations: list[object] = []

    async def completed_optional(category, label, _fn, *args, **kwargs):
        calls.append((category, label))
        return {"updated": 2}

    monkeypatch.setattr(server, "_optional_bounded_thread", completed_optional)
    monkeypatch.setattr(
        server.cognition_mod, "record_observation", lambda value: observations.append(value)
    )

    result = asyncio.run(server._run_routine({"id": 7, "kind": "embed_backfill"}))

    assert result["status"] == "ok"
    assert calls == [("routine", "routine_embed_backfill")]
    assert len(observations) == 1

    async def deferred_optional(category, label, _fn, *args, **kwargs):
        calls.append((category, label))
        return {"status": "deferred", "reason": "chat-active", "category": category}

    monkeypatch.setattr(server, "_optional_bounded_thread", deferred_optional)
    deferred = asyncio.run(server._run_routine({"id": 8, "kind": "daily_recap"}))

    assert deferred["status"] == "deferred"
    assert calls[-1] == ("routine", "routine_daily_recap")
    assert len(observations) == 1


def test_optional_work_telemetry_is_compact_and_runtime_ready(optional_work):
    decision = optional_work.start("reflection")
    assert decision.lease is not None
    optional_work.finish(decision.lease)

    telemetry = server._optional_work_telemetry()

    assert telemetry["active"] == {
        "job_id": None,
        "category": "",
        "cancelled": False,
    }
    assert telemetry["recent"] == [
        {"event": "start", "category": "reflection", "detail": ""},
        {"event": "finish", "category": "reflection", "detail": ""},
    ]
