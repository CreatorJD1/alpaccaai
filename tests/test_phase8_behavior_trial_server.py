"""Focused server coverage for the Phase 8 behavior-trial recovery gate."""
from __future__ import annotations

import asyncio

import pytest

import server


class _BehaviorTrialController:
    def __init__(
        self,
        *,
        default_chatter_chance: float = 0.25,
        effective_chatter_chance: float = 0.12,
        recovery_error: Exception | None = None,
    ) -> None:
        self.default_chatter_chance = default_chatter_chance
        self.effective_chatter_chance = effective_chatter_chance
        self.recovery_error = recovery_error
        self.recovery_calls = 0
        self.chatter_chance_calls = 0

    def recover_interrupted(self) -> list[dict[str, object]]:
        self.recovery_calls += 1
        if self.recovery_error is not None:
            raise self.recovery_error
        return []

    def chatter_chance(self) -> float:
        self.chatter_chance_calls += 1
        return self.effective_chatter_chance


@pytest.fixture(autouse=True)
def _restore_behavior_trial_recovery_gate():
    originally_ready = server._behavior_trial_recovery_ready.is_set()
    server._behavior_trial_recovery_ready.clear()
    yield
    if originally_ready:
        server._behavior_trial_recovery_ready.set()
    else:
        server._behavior_trial_recovery_ready.clear()


def _isolate_lifespan(monkeypatch) -> None:
    async def no_op_async(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(server, "DRIFT_INTERVAL", 3_600.0)
    monkeypatch.setattr(
        server.commitments_mod,
        "recover_running_commitments",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(server.capabilities_mod, "record_snapshot", lambda **_kwargs: None)
    monkeypatch.setattr(server.mind, "write_session_recap", lambda: None)
    monkeypatch.setattr(server, "_mindscape_sync_once", no_op_async)
    monkeypatch.setattr(server, "_warm_alpecca_voice", no_op_async)
    monkeypatch.setattr(server.voice_sensor, "close", lambda: None)
    monkeypatch.setattr(server.screen_sight, "close", lambda: None)
    monkeypatch.setattr(server.face_sense, "close", lambda: None)


async def _chatter_chance_after_lifespan_startup() -> tuple[float, bool]:
    async with server.lifespan(server.app):
        return (
            server._behavior_trial_chatter_chance(),
            server._behavior_trial_recovery_ready.is_set(),
        )


def test_behavior_trial_chatter_gate_uses_default_before_recovery(monkeypatch):
    controller = _BehaviorTrialController()
    monkeypatch.setattr(server, "behavior_trial_controller", controller)

    assert server._behavior_trial_chatter_chance() == controller.default_chatter_chance
    assert controller.chatter_chance_calls == 0


def test_lifespan_recovery_failure_keeps_behavior_trial_chatter_gate_closed(monkeypatch):
    _isolate_lifespan(monkeypatch)
    controller = _BehaviorTrialController(recovery_error=RuntimeError("database unavailable"))
    monkeypatch.setattr(server, "behavior_trial_controller", controller)

    chance, ready = asyncio.run(_chatter_chance_after_lifespan_startup())

    assert controller.recovery_calls == 1
    assert ready is False
    assert chance == controller.default_chatter_chance
    assert controller.chatter_chance_calls == 0


def test_successful_lifespan_recovery_allows_behavior_trial_chatter_chance(monkeypatch):
    _isolate_lifespan(monkeypatch)
    controller = _BehaviorTrialController()
    monkeypatch.setattr(server, "behavior_trial_controller", controller)

    chance, ready = asyncio.run(_chatter_chance_after_lifespan_startup())

    assert controller.recovery_calls == 1
    assert ready is True
    assert chance == controller.effective_chatter_chance
    assert controller.chatter_chance_calls == 1


def test_server_exposes_no_self_improvement_trial_routes():
    route_paths = {route.path for route in server.app.routes}

    assert "/self-improvement" not in route_paths
    assert not any(path.startswith("/self-improvement/") for path in route_paths)
