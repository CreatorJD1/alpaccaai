"""Focused server integration tests for Phase 6 optional-work coordination."""
from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from alpecca import host_resources
from alpecca.resource_coordinator import ResourceCoordinator
import server


class _StaticHostResourceSampler:
    def __init__(self, advisory: object):
        self.advisory = advisory
        self.force_values: list[bool] = []

    def snapshot(self, force: bool = False) -> dict:
        self.force_values.append(force)
        return {"advisory": self.advisory}


@pytest.fixture
def optional_work(monkeypatch):
    coordinator = ResourceCoordinator()
    monkeypatch.setattr(server, "_optional_work_coordinator", coordinator)
    monkeypatch.setattr(server, "_host_resource_sampler", _StaticHostResourceSampler({}))
    monkeypatch.setattr(server, "active_chat_turns", 0)
    monkeypatch.setattr(server, "active_tts_requests", 0)
    monkeypatch.setattr(server, "last_chat_turn_started", 0.0)
    return coordinator


@pytest.fixture
def mindpage_backfill_status(monkeypatch):
    status = dict(server._background_autonomy_status)
    status.update({
        "last_mindpage_content_index_backfill_at": 0.0,
        "last_mindpage_content_index_backfill_run": {},
    })
    monkeypatch.setattr(server, "_background_autonomy_status", status)
    return status


def _cached_host_resource_sampler():
    calls = {name: 0 for name in ("cpu", "performance", "battery", "disk", "gpu")}

    def probe(name, value):
        def read():
            calls[name] += 1
            return value

        return read

    sampler = host_resources.HostResourceSampler(
        cache_ttl_seconds=60.0,
        _cpu_probe=probe("cpu", {"cpu_percent": 24.0}),
        _performance_probe=probe("performance", {
            "ram_total_bytes": 16 * 1024**3,
            "ram_available_bytes": 8 * 1024**3,
            "commit_used_bytes": 20 * 1024**3,
            "commit_limit_bytes": 32 * 1024**3,
        }),
        _battery_probe=probe("battery", None),
        _disk_probe=probe("disk", {
            "disk_free_bytes": 400 * 1024**3,
            "disk_total_bytes": 512 * 1024**3,
        }),
        _gpu_probe=probe("gpu", None),
        _is_windows=False,
    )
    return sampler, calls


def _protected_headers():
    return {server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET}


def test_resources_runtime_and_soul_share_a_cached_snapshot(monkeypatch):
    sampler, calls = _cached_host_resource_sampler()
    force_values: list[bool] = []
    original_snapshot = sampler.snapshot

    def snapshot(force: bool = False):
        force_values.append(force)
        return original_snapshot(force=force)

    monkeypatch.setattr(sampler, "snapshot", snapshot)
    monkeypatch.setattr(server, "_host_resource_sampler", sampler)

    client = TestClient(server.app)
    first_response = client.get("/system/resources", headers=_protected_headers())
    second_response = client.get("/system/resources", headers=_protected_headers())
    runtime = server._runtime_status(check_models=False)
    soul_snapshot = server.mind._soul_snapshot()

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first = first_response.json()
    second = second_response.json()
    assert {
        "state", "timestamp", "age", "raw", "headroom", "assessment", "pagefile", "advisory",
    } <= first.keys()
    assert second["timestamp"] == first["timestamp"]
    assert runtime["host_resources"]["timestamp"] == first["timestamp"]
    assert soul_snapshot.host_pressure is not None
    assert soul_snapshot.host_pressure["sample_state"] == first["state"]
    assert soul_snapshot.host_pressure["timestamp"] == first["timestamp"]
    assert soul_snapshot.host_pressure["severity"] == first["assessment"]["severity"]
    assert soul_snapshot.host_pressure["pressure"] == first["assessment"]["pressure"]
    assert set(soul_snapshot.host_pressure) == {
        "source", "sample_state", "timestamp", "age", "severity", "pressure", "evidence_codes",
    }
    assert force_values == [False, False, False, False]
    assert calls == {"cpu": 1, "performance": 1, "battery": 1, "disk": 1, "gpu": 1}


def test_soul_receives_assessment_only_from_current_shared_sampler(monkeypatch):
    assessment = {
        "pressure": 0.91,
        "severity": "high",
        "reasons": [{"resource": "commit", "pressure": 0.91}],
    }

    class AssessmentSampler:
        def __init__(self):
            self.force_values: list[bool] = []

        def snapshot(self, force: bool = False) -> dict:
            self.force_values.append(force)
            return {
                "state": "ready",
                "timestamp": 123.0,
                "age": 0.0,
                "raw": {"commit_used_bytes": 91},
                "headroom": {"commit_fraction": 0.09},
                "assessment": assessment,
                "advisory": {"defer_optional_work": True},
            }

    sampler = AssessmentSampler()
    monkeypatch.setattr(server, "_host_resource_sampler", sampler)

    soul_snapshot = server.mind._soul_snapshot()

    assert sampler.force_values == [False]
    assert soul_snapshot.host_pressure == {
        "source": "host_resource_snapshot",
        "sample_state": "ready",
        "timestamp": 123.0,
        "age": 0.0,
        "severity": "high",
        "pressure": 0.91,
        "evidence_codes": [],
    }


def test_chat_turn_does_not_sample_host_resources(monkeypatch):
    class UnexpectedSampler:
        def __init__(self):
            self.calls: list[bool] = []

        def snapshot(self, force: bool = False):
            self.calls.append(force)
            raise AssertionError("chat turns must not refresh host resources")

    sampler = UnexpectedSampler()

    async def fake_chat(*_args, **_kwargs):
        return {"text": "ready"}

    monkeypatch.setattr(server, "_host_resource_sampler", sampler)
    monkeypatch.setattr(server, "_locked_ws_chat_turn", fake_chat)
    monkeypatch.setattr(server, "active_chat_turns", 0)
    monkeypatch.setattr(server, "last_chat_turn_started", 0.0)

    assert asyncio.run(server._ws_chat_turn_with_timeout("hello")) == {"text": "ready"}
    assert sampler.calls == []


def test_host_resource_reads_leave_optional_work_coordination_unchanged(
    monkeypatch, optional_work
):
    sampler, _calls = _cached_host_resource_sampler()
    monkeypatch.setattr(server, "_host_resource_sampler", sampler)
    held = optional_work.start("reflection")
    assert held.lease is not None
    before = server._optional_work_telemetry()

    try:
        endpoint_snapshot = server.system_resources()
        runtime = server._runtime_status(check_models=False)
        after = server._optional_work_telemetry()

        assert endpoint_snapshot["timestamp"] == runtime["host_resources"]["timestamp"]
        assert after == before
        assert [item.event for item in optional_work.telemetry()] == ["start"]
    finally:
        optional_work.finish(held.lease)


def test_high_host_advisory_defers_optional_work_with_compact_evidence(
    monkeypatch, optional_work
):
    sampler = _StaticHostResourceSampler({
        "defer_optional_work": True,
        "resource": {"severity": "high"},
        "reasons": ("resource_high", "commit_headroom_low"),
    })
    calls: list[str] = []
    monkeypatch.setattr(server, "_host_resource_sampler", sampler)

    result = asyncio.run(server._optional_bounded_thread(
        "backfill", "backfill", lambda: calls.append("ran"),
    ))

    assert result == {
        "status": "deferred",
        "reason": "host-pressure",
        "category": "backfill",
        "advisory": {
            "severity": "high",
            "reasons": ["resource_high", "commit_headroom_low"],
        },
    }
    assert sampler.force_values == [False]
    assert calls == []
    assert optional_work.active() is None
    assert optional_work.telemetry() == ()


def test_unknown_host_advisory_allows_normal_optional_work(monkeypatch, optional_work):
    sampler = _StaticHostResourceSampler({"evidence_state": "unknown"})
    calls: list[str] = []

    async def immediate_bounded(_label, fn, *args, **kwargs):
        kwargs.pop("timeout", None)
        return fn(*args, **kwargs)

    monkeypatch.setattr(server, "_host_resource_sampler", sampler)
    monkeypatch.setattr(server, "_bounded_thread", immediate_bounded)

    result = asyncio.run(server._optional_bounded_thread(
        "reflection", "reflect", lambda: calls.append("ran") or "completed",
    ))

    assert result == "completed"
    assert sampler.force_values == [False]
    assert calls == ["ran"]
    assert [item.event for item in optional_work.telemetry()] == ["start", "finish"]


def test_host_pressure_deferral_does_not_touch_the_coordinator(monkeypatch, optional_work):
    sampler = _StaticHostResourceSampler({
        "defer_optional_work": True,
        "resource": {"severity": "high"},
        "reasons": ("resource_high",),
    })
    held = optional_work.start("reflection")
    assert held.lease is not None
    before = optional_work.snapshot()
    telemetry = optional_work.telemetry()

    def unexpected_coordinator_call(*_args, **_kwargs):
        raise AssertionError("host-pressure deferral must not touch the coordinator")

    monkeypatch.setattr(server, "_host_resource_sampler", sampler)
    monkeypatch.setattr(optional_work, "set_foreground", unexpected_coordinator_call)
    monkeypatch.setattr(optional_work, "start", unexpected_coordinator_call)
    monkeypatch.setattr(optional_work, "cancel", unexpected_coordinator_call)

    try:
        result = asyncio.run(server._optional_bounded_thread(
            "backfill", "backfill", lambda: "should not run",
        ))

        assert result["reason"] == "host-pressure"
        assert sampler.force_values == [False]
        assert optional_work.active() is held.lease
        assert held.lease.cancelled is False
        assert optional_work.snapshot() == before
        assert optional_work.telemetry() == telemetry
    finally:
        optional_work.finish(held.lease)


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
        timed_out = await server._optional_bounded_thread(
            "reflection", "reflect", work, timeout=0.2
        )
        assert timed_out == {
            "status": "cancel_requested",
            "category": "reflection",
            "reason": "timeout",
        }
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


def test_chat_start_immediately_requests_cancellation_of_active_optional_work(
    monkeypatch, optional_work
):
    held = optional_work.start("backfill")
    assert held.lease is not None
    observed: list[bool] = []

    async def fake_chat(*_args, **_kwargs):
        observed.append(held.lease.cancelled)
        return {"text": "ready"}

    monkeypatch.setattr(server, "_locked_ws_chat_turn", fake_chat)

    result = asyncio.run(server._ws_chat_turn_with_timeout("hello"))

    assert result == {"text": "ready"}
    assert observed == [True]
    assert server.active_chat_turns == 0
    assert [item.event for item in optional_work.telemetry()] == ["start", "cancel"]


def test_cooperative_optional_work_receives_and_reports_its_cancel_event(
    monkeypatch, optional_work
):
    received: list[threading.Event] = []

    async def immediate_bounded(_label, fn, *args, **kwargs):
        kwargs.pop("timeout", None)
        return fn(*args, **kwargs)

    def worker(*, cancel_event):
        received.append(cancel_event)
        optional_work.set_foreground(chat_active=True, tts_active=False)
        assert cancel_event.is_set()
        return {"scanned": 1, "cancelled": True}

    monkeypatch.setattr(server, "_bounded_thread", immediate_bounded)
    result = asyncio.run(server._optional_bounded_thread(
        "backfill", "cooperative_backfill", worker, cooperative=True,
    ))

    assert len(received) == 1
    assert received[0].is_set() is True
    assert result == {
        "scanned": 1,
        "cancelled": True,
        "status": "cancelled",
        "category": "backfill",
        "reason": "worker-observed",
    }
    assert optional_work.active() is None


def test_cancelled_maintenance_and_routines_are_not_recorded_as_completed(
    monkeypatch, optional_work, mindpage_backfill_status
):
    observations: list[object] = []
    released: list[dict] = []
    broadcasts: list[dict] = []

    async def cancelled_optional(category, _label, _fn, *args, **kwargs):
        return {
            "status": "cancelled",
            "category": category,
            "reason": "worker-observed",
        }

    async def cancelled_routine(_row):
        return {"status": "cancel_requested", "kind": "embed_backfill"}

    async def capture_broadcast(event):
        broadcasts.append(event)
        return 1

    monkeypatch.setattr(server, "_optional_bounded_thread", cancelled_optional)
    monkeypatch.setattr(
        server.cognition_mod, "record_observation", lambda value: observations.append(value)
    )
    row = {
        "id": 71,
        "name": "Cancelled embedding backfill",
        "kind": "embed_backfill",
    }
    claim = {"routine_id": 71, "run_key": "test", "claim_token": "test"}
    monkeypatch.setattr(server.routines_mod, "claim_due", lambda: [(row, claim)])
    monkeypatch.setattr(server.routines_mod, "release", lambda value: released.append(value))
    monkeypatch.setattr(server, "_broadcast", capture_broadcast)
    monkeypatch.setattr(server.AutomationCfg, "ROUTINES", True)

    routine = asyncio.run(server._run_routine({"id": 70, "kind": "embed_backfill"}))
    maintenance = asyncio.run(server._maintain_mindpage_content_index(now=1_000.0))
    monkeypatch.setattr(server, "_run_routine", cancelled_routine)
    asyncio.run(server._run_due_routines_once())

    assert routine["status"] == "cancelled"
    assert observations == []
    assert maintenance["status"] == "cancelled"
    assert mindpage_backfill_status["last_mindpage_content_index_backfill_at"] == 0.0
    assert mindpage_backfill_status["last_mindpage_content_index_backfill_run"] == {}
    assert released == [claim]
    assert broadcasts == []


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


def test_tts_route_honors_bounded_engine_override(monkeypatch, optional_work):
    from alpecca import tts as tts_mod

    calls: list[tuple[str, str]] = []

    class JsonRequest:
        async def json(self):
            return {"text": "Speak this", "engine": "kokoro"}

    def synth(_text, _state, *, backend_override=""):
        calls.append((_text, backend_override))
        return "audio/wav", b"wav"

    monkeypatch.setattr(tts_mod, "synth", synth)
    monkeypatch.setattr(tts_mod, "_last_engine", "")

    response = asyncio.run(server.tts(JsonRequest()))

    assert response.status_code == 200
    assert response.headers["x-alpecca-tts-engine"] == "server"
    assert calls == [("Speak this", "kokoro")]


def test_tts_route_rejects_unknown_engine_before_synthesis(monkeypatch, optional_work):
    from alpecca import tts as tts_mod

    class JsonRequest:
        async def json(self):
            return {"text": "Speak this", "engine": "unknown"}

    monkeypatch.setattr(
        tts_mod,
        "synth",
        lambda *_args, **_kwargs: pytest.fail("invalid engine reached synthesis"),
    )

    response = asyncio.run(server.tts(JsonRequest()))

    assert response.status_code == 422
    assert response.headers["x-alpecca-tts-error"] == "unsupported voice engine"


def test_routines_use_routine_category_and_leave_deferred_rows_unrecorded(
    monkeypatch, optional_work
):
    calls: list[tuple[str, str, dict]] = []
    observations: list[object] = []

    async def completed_optional(category, label, _fn, *args, **kwargs):
        calls.append((category, label, kwargs))
        return {"updated": 2}

    monkeypatch.setattr(server, "_optional_bounded_thread", completed_optional)
    monkeypatch.setattr(
        server.mind,
        "reserve_initiative",
        lambda **_kwargs: {"allowed": True, "decision": "allow"},
    )
    monkeypatch.setattr(
        server.cognition_mod, "record_observation", lambda value: observations.append(value)
    )

    result = asyncio.run(server._run_routine({"id": 7, "kind": "embed_backfill"}))

    assert result["status"] == "ok"
    assert calls == [(
        "routine",
        "routine_embed_backfill",
        {"timeout": 10.0, "cooperative": True},
    )]
    assert len(observations) == 1

    async def deferred_optional(category, label, _fn, *args, **kwargs):
        calls.append((category, label, kwargs))
        return {"status": "deferred", "reason": "chat-active", "category": category}

    monkeypatch.setattr(server, "_optional_bounded_thread", deferred_optional)
    deferred = asyncio.run(server._run_routine({"id": 8, "kind": "daily_recap"}))

    assert deferred["status"] == "deferred"
    assert calls[-1][:2] == ("routine", "routine_daily_recap")
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


def test_mindpage_content_index_backfill_runs_when_due_and_records_status(
    monkeypatch, optional_work, mindpage_backfill_status
):
    calls: list[tuple[str, str, object, tuple, dict]] = []
    run = {"scanned": 8, "indexed": 3, "errors": 0, "pending": 4}

    async def completed_optional(category, label, fn, *args, **kwargs):
        calls.append((category, label, fn, args, kwargs))
        return run

    async def unexpected_broadcast(*_args, **_kwargs):
        raise AssertionError("maintenance must not broadcast activity")

    monkeypatch.setattr(server, "_optional_bounded_thread", completed_optional)
    monkeypatch.setattr(server, "_broadcast", unexpected_broadcast)
    monkeypatch.setattr(server, "BACKGROUND_MINDPAGE_CONTENT_INDEX_INTERVAL", 300.0)

    result = asyncio.run(server._maintain_mindpage_content_index(now=1_000.0))

    assert result == run
    assert calls == [
        (
            "backfill",
            "mindpage_content_index_backfill",
            server.mindpage_mod.backfill_content_index,
            (),
            {"batch": 8, "timeout": 10.0, "cooperative": True},
        )
    ]
    assert mindpage_backfill_status["last_mindpage_content_index_backfill_at"] == 1_000.0
    assert mindpage_backfill_status["last_mindpage_content_index_backfill_run"] == {
        "status": "completed",
        "scanned": 8,
        "indexed": 3,
        "errors": 0,
        "pending": 4,
    }


def test_mindpage_content_index_backfill_skips_until_interval_is_due(
    monkeypatch, optional_work, mindpage_backfill_status
):
    mindpage_backfill_status["last_mindpage_content_index_backfill_at"] = 900.0
    mindpage_backfill_status["last_mindpage_content_index_backfill_run"] = {"status": "completed"}
    monkeypatch.setattr(server, "BACKGROUND_MINDPAGE_CONTENT_INDEX_INTERVAL", 300.0)

    async def unexpected_optional(*_args, **_kwargs):
        raise AssertionError("not-due maintenance must not acquire an optional lease")

    monkeypatch.setattr(server, "_optional_bounded_thread", unexpected_optional)

    result = asyncio.run(server._maintain_mindpage_content_index(now=1_000.0))

    assert result == {"status": "skipped", "reason": "interval", "next_in": 200.0}
    assert mindpage_backfill_status["last_mindpage_content_index_backfill_at"] == 900.0
    assert mindpage_backfill_status["last_mindpage_content_index_backfill_run"] == {
        "status": "completed"
    }


def test_mindpage_content_index_backfill_defers_for_chat_without_dispatch(
    monkeypatch, optional_work, mindpage_backfill_status
):
    monkeypatch.setattr(server, "active_chat_turns", 1)

    async def unexpected_optional(*_args, **_kwargs):
        raise AssertionError("chat-priority maintenance must not acquire an optional lease")

    monkeypatch.setattr(server, "_optional_bounded_thread", unexpected_optional)

    result = asyncio.run(server._maintain_mindpage_content_index(now=1_000.0))

    assert result == {"status": "deferred", "reason": "chat-active", "category": "backfill"}
    assert mindpage_backfill_status["last_mindpage_content_index_backfill_at"] == 0.0
    assert mindpage_backfill_status["last_mindpage_content_index_backfill_run"] == {}


def test_mindpage_content_index_backfill_preserves_due_time_when_optional_work_or_tts_defers(
    monkeypatch, optional_work, mindpage_backfill_status
):
    calls: list[object] = []
    monkeypatch.setattr(
        server.mindpage_mod,
        "backfill_content_index",
        lambda **_kwargs: calls.append("backfill"),
    )
    held = optional_work.start("reflection")
    assert held.lease is not None

    overlap = asyncio.run(server._maintain_mindpage_content_index(now=1_000.0))
    optional_work.finish(held.lease)

    monkeypatch.setattr(server, "active_tts_requests", 1)
    tts = asyncio.run(server._maintain_mindpage_content_index(now=1_001.0))

    assert overlap["reason"] == "optional-work-active"
    assert tts["reason"] == "tts-active"
    assert calls == []
    assert mindpage_backfill_status["last_mindpage_content_index_backfill_at"] == 0.0
    assert mindpage_backfill_status["last_mindpage_content_index_backfill_run"] == {}
