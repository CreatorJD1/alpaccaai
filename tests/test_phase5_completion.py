"""Focused regression coverage for the completed Phase 5 initiative boundary."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from alpecca import cues, mind as mind_mod, turn_context
from alpecca.initiative import InitiativeBudget, InitiativePolicy
from alpecca.resource_coordinator import ResourceCoordinator
import server


class _JsonRequest:
    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self) -> dict:
        return dict(self._body)


class _Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _turn(scope: str = "phase5-completion") -> turn_context.TurnContext:
    return turn_context.TurnContext.create(
        "creator-house-hq-primary",
        principal="creator",
        surface="house-hq",
        privacy_scope=scope,
        portal_epoch="phase5-completion-test",
    )


def _initiative(*, scope: str = "creator-scope", key: str = "volunteer:check-in") -> dict:
    return {
        "allowed": True,
        "decision": "allow",
        "reason": "allowed",
        "scope": scope,
        "dedupe_key": key,
    }


async def _run_immediately(_label, fn, *args, **kwargs):
    kwargs.pop("timeout", None)
    return fn(*args, **kwargs)


def test_quiet_world_tick_uses_scope_and_defer_has_no_outputs(monkeypatch):
    quiet_mind = object.__new__(mind_mod.CoreMind)
    quiet_mind._location = "hq-control"
    proactive_turn = _turn("quiet-world")
    reservations: list[dict] = []

    def reserve(**kwargs):
        reservations.append(kwargs)
        return {
            "allowed": False,
            "decision": "defer",
            "reason": "cooldown",
            "scope": kwargs["scope_key"],
            "event_kind": kwargs["event_kind"],
        }

    def forbidden(*_args, **_kwargs):
        raise AssertionError("deferred quiet tick performed post-budget work")

    async def forbidden_broadcast(*_args, **_kwargs):
        raise AssertionError("deferred quiet tick was broadcast")

    monkeypatch.setattr(quiet_mind, "reserve_initiative", reserve)
    monkeypatch.setattr(server.mind, "living_world_tick", quiet_mind.living_world_tick)
    monkeypatch.setattr(server, "_proactive_turn_context", lambda: proactive_turn)
    monkeypatch.setattr(server, "_living_systems_context", lambda _check: {"test": True})
    monkeypatch.setattr(server, "_bounded_thread", _run_immediately)
    monkeypatch.setattr(server, "_remember_living_result", forbidden)
    monkeypatch.setattr(server, "_mindscape_request_event_sync", forbidden)
    monkeypatch.setattr(server, "_broadcast", forbidden_broadcast)
    monkeypatch.setattr(mind_mod.home_mod, "room", forbidden)

    result = asyncio.run(
        server.cognition_world_tick(_JsonRequest({"reason": "quiet", "quiet": True}))
    )

    assert result["status"] == "deferred"
    assert result["phase"] == "initiative_budget"
    assert reservations == [{
        "event_kind": "living",
        "evidence_key": "quiet:hq-control",
        "scope_key": proactive_turn.scope_key,
        "relevance": 0.75,
        "user_active": False,
        "outreach": False,
    }]


def test_manual_world_tick_bypasses_initiative_scope(monkeypatch):
    calls: list[dict] = []
    remembered: list[tuple[dict, bool]] = []
    broadcasts: list[dict] = []
    sync_reasons: list[str] = []

    def manual_tick(reason, systems, *, initiative_scope):
        calls.append({
            "reason": reason,
            "systems": systems,
            "initiative_scope": initiative_scope,
        })
        return {"ok": True, "line": "Manual tick complete."}

    async def broadcast(payload):
        broadcasts.append(payload)
        return 1

    monkeypatch.setattr(
        server,
        "_proactive_turn_context",
        lambda: (_ for _ in ()).throw(
            AssertionError("manual tick requested an initiative scope")
        ),
    )
    monkeypatch.setattr(server, "_living_systems_context", lambda _check: {"test": True})
    monkeypatch.setattr(server.mind, "living_world_tick", manual_tick)
    monkeypatch.setattr(server.mind, "cognition_state", lambda: {"status": "test"})
    monkeypatch.setattr(server, "_bounded_thread", _run_immediately)
    monkeypatch.setattr(
        server,
        "_remember_living_result",
        lambda result, *, counted=False: remembered.append((result, counted)),
    )
    monkeypatch.setattr(server, "_broadcast", broadcast)
    monkeypatch.setattr(
        server,
        "_mindscape_request_event_sync",
        lambda reason: sync_reasons.append(reason),
    )

    result = asyncio.run(server.cognition_world_tick(_JsonRequest({"reason": "manual"})))

    assert calls == [{
        "reason": "manual",
        "systems": {"test": True},
        "initiative_scope": "",
    }]
    assert remembered == [(result, True)]
    assert len(broadcasts) == 1
    assert sync_reasons == ["living_world_tick"]


def test_idle_self_direct_defers_before_cognition_journal_or_model_work(monkeypatch):
    idle_mind = object.__new__(mind_mod.CoreMind)
    idle_mind._location = "library"
    reservations: list[dict] = []

    def reserve(**kwargs):
        reservations.append(kwargs)
        return {
            "allowed": False,
            "decision": "defer",
            "reason": "cooldown",
            "scope": kwargs["scope_key"],
        }

    def forbidden(name: str):
        def call(*_args, **_kwargs):
            raise AssertionError(f"deferred idle work reached {name}")

        return call

    idle_mind.llm = type("ForbiddenLLM", (), {"generate": forbidden("model")})()
    monkeypatch.setattr(idle_mind, "reserve_initiative", reserve)
    for name in (
        "form_desire",
        "learn_tick",
        "soul_state",
        "_enact_focus",
        "review_behavior_improvement",
        "consolidate_observations",
    ):
        monkeypatch.setattr(idle_mind, name, forbidden(name))
    monkeypatch.setattr(mind_mod.cognition_mod, "set_intent", forbidden("cognition"))
    monkeypatch.setattr(mind_mod.journal_mod, "ask", forbidden("journal"))
    monkeypatch.setattr(mind_mod.journal_mod, "write", forbidden("journal"))

    result = idle_mind.idle_self_direct(initiative_scope="creator-idle")

    assert result == {
        "ok": True,
        "status": "deferred",
        "deferred": True,
        "phase": "initiative_budget",
        "initiative": {
            "allowed": False,
            "decision": "defer",
            "reason": "cooldown",
            "scope": "creator-idle",
        },
        "note": None,
    }
    assert reservations == [{
        "event_kind": "recursive",
        "evidence_key": "idle-self-direct:library",
        "scope_key": "creator-idle",
        "relevance": 0.72,
        "user_active": False,
        "outreach": False,
    }]


def test_optional_deferral_preserves_routine_budget_for_retry(monkeypatch):
    coordinator = ResourceCoordinator()
    proactive_turn = _turn("routine-retry")
    reservations: list[dict] = []
    routine_calls: list[str] = []
    observations: list[object] = []

    monkeypatch.setattr(server, "_optional_work_coordinator", coordinator)
    monkeypatch.setattr(server, "active_chat_turns", 0)
    monkeypatch.setattr(server, "active_tts_requests", 0)
    monkeypatch.setattr(server, "last_chat_turn_started", 0.0)
    monkeypatch.setattr(server, "_bounded_thread", _run_immediately)
    monkeypatch.setattr(server, "_proactive_turn_context", lambda: proactive_turn)
    monkeypatch.setattr(server.routines_mod, "run_key", lambda: "2026-07-10")

    def reserve(**kwargs):
        reservations.append(kwargs)
        return {
            "allowed": True,
            "decision": "allow",
            "scope": kwargs["scope_key"],
            "dedupe_key": "routine:daily-recap",
        }

    def recap():
        routine_calls.append("recap")
        return {"written": True}

    monkeypatch.setattr(server.mind, "reserve_initiative", reserve)
    monkeypatch.setattr(server.mind, "write_session_recap", recap)
    monkeypatch.setattr(
        server.cognition_mod,
        "record_observation",
        lambda observation: observations.append(observation),
    )

    held = coordinator.start("reflection")
    assert held.lease is not None
    deferred = asyncio.run(server._run_routine({
        "id": 21,
        "name": "Daily recap",
        "kind": "daily_recap",
    }))

    assert deferred["status"] == "deferred"
    assert deferred["result"]["reason"] == "optional-work-active"
    assert reservations == []
    assert routine_calls == []

    coordinator.finish(held.lease)
    retried = asyncio.run(server._run_routine({
        "id": 21,
        "name": "Daily recap",
        "kind": "daily_recap",
    }))

    assert retried["status"] == "ok"
    assert retried["result"] == {"written": True}
    assert len(reservations) == 1
    assert reservations[0]["scope_key"] == proactive_turn.scope_key
    assert routine_calls == ["recap"]
    assert len(observations) == 1


def test_failed_portal_and_channel_delivery_is_not_delivered_or_timed(monkeypatch):
    initiative = _initiative()
    portal_payloads: list[dict] = []
    armed: list[dict] = []
    cleared: list[tuple[str, str]] = []

    async def failed_portal(payload):
        portal_payloads.append(payload)
        return 0

    async def failed_channel(label, _fn, *args, **kwargs):
        assert label == "openclaw_deliver"
        assert args == ("Check-in",)
        return {"attempted": True, "ok": False, "queued": True}

    monkeypatch.setattr(server, "ws_clients", {object()})
    monkeypatch.setattr(server, "_broadcast", failed_portal)
    monkeypatch.setattr(server, "_bounded_thread", failed_channel)
    monkeypatch.setattr(
        server,
        "_schedule_ignored_outreach",
        lambda value: armed.append(value) or True,
    )
    monkeypatch.setattr(
        server.mind,
        "clear_initiative_outreach",
        lambda scope, key: cleared.append((scope, key)) or True,
    )

    result = asyncio.run(server._deliver_proactive_once("Check-in", initiative))

    assert len(portal_payloads) == 1
    assert result["surface"] == "channel"
    assert result["delivered"] is False
    assert result["queued"] is True
    assert armed == []
    assert cleared == [(initiative["scope"], initiative["dedupe_key"])]


@pytest.mark.parametrize("surface", ["portal", "channel"])
def test_verified_delivery_arms_ignored_timer(monkeypatch, surface):
    initiative = _initiative(key=f"volunteer:{surface}")
    armed: list[dict] = []

    async def delivered_portal(_payload):
        return 1

    async def delivered_channel(_label, _fn, *_args, **_kwargs):
        return {"attempted": True, "ok": True}

    async def forbidden(*_args, **_kwargs):
        raise AssertionError(f"verified {surface} delivery used a second surface")

    monkeypatch.setattr(
        server,
        "_schedule_ignored_outreach",
        lambda value: armed.append(value) or True,
    )
    monkeypatch.setattr(
        server.mind,
        "clear_initiative_outreach",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("verified delivery cleared its outreach reservation")
        ),
    )
    if surface == "portal":
        monkeypatch.setattr(server, "ws_clients", {object()})
        monkeypatch.setattr(server, "_broadcast", delivered_portal)
        monkeypatch.setattr(server, "_bounded_thread", forbidden)
    else:
        monkeypatch.setattr(server, "ws_clients", set())
        monkeypatch.setattr(server, "_broadcast", forbidden)
        monkeypatch.setattr(server, "_bounded_thread", delivered_channel)

    result = asyncio.run(server._deliver_proactive_once("Delivered", initiative))

    assert result["surface"] == surface
    assert result["delivered"] is True
    assert armed == [initiative]


def test_immediate_duplicate_outreach_does_not_count_as_ignored():
    clock = _Clock()
    budget = InitiativeBudget(
        InitiativePolicy(
            min_relevance=0.6,
            cooldown_seconds=10.0,
            window_seconds=60.0,
            max_per_window=4,
            dedupe_seconds=30.0,
            activity_quiet_seconds=5.0,
        ),
        clock=clock,
    )
    initiative_mind = object.__new__(mind_mod.CoreMind)
    initiative_mind._initiative_budget = budget
    initiative_mind._initiative_lock = threading.Lock()
    initiative_mind._last_initiative_decision = None

    first = initiative_mind.reserve_initiative(
        event_kind="volunteer",
        evidence_key="same check-in",
        scope_key="creator-duplicate",
        relevance=0.9,
        outreach=True,
    )
    duplicate = initiative_mind.reserve_initiative(
        event_kind="volunteer",
        evidence_key="same check-in",
        scope_key="creator-duplicate",
        relevance=0.9,
        outreach=True,
    )
    snapshot = initiative_mind.initiative_snapshot("creator-duplicate")

    assert first["allowed"] is True
    assert duplicate["allowed"] is False
    assert duplicate["reason"] == "awaiting_response"
    assert duplicate["ignored_streak"] == 0
    assert snapshot["ignored_streak"] == 0
    assert snapshot["window_used"] == 1
    assert snapshot["pending_outreach_key"] == first["dedupe_key"]


def test_generic_help_request_does_not_inject_distress_posture():
    envelope = cues.parse_cues("Please help me sort this list")
    metadata = mind_mod.CoreMind._phase5_affect_metadata(
        envelope,
        _turn("generic-help"),
        observed_at=100.0,
    )
    distress = next(
        event for event in metadata["events"] if event["cue_kind"] == "distress"
    )

    assert envelope.distress.detected is True
    assert envelope.distress.confidence == 0.55
    assert distress["decision"]["should_update"] is False
    assert distress["decision"]["reason"] == "weak_evidence"
    assert "calm, support-focused response strategy" not in metadata["operational_states"]
    assert "calm, support-focused response strategy" not in metadata["response_strategy"]


def test_discord_autonomous_defaults_are_off(tmp_path):
    env = os.environ.copy()
    for key in (
        "ALPECCA_DISCORD_PROACTIVE",
        "ALPECCA_DISCORD_RECURSIVE",
        "ALPECCA_DISCORD_PARTICIPATE",
        "ALPECCA_DISCORD_VOICE",
    ):
        env.pop(key, None)
    env["ALPECCA_HOME"] = str(tmp_path)
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from alpecca import discord_bridge as bridge; "
                "print(bridge.PROACTIVE_ENABLED, bridge.RECURSIVE_ENABLED, "
                "bridge.PARTICIPATE, bridge.VOICE_ENABLED)"
            ),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "False False False False"
