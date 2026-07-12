"""Focused server wiring coverage for Phase 8C2 outcome evidence."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from alpecca.mind import ProactiveCandidate
from alpecca.qualified_response_ledger import QualifiedResponseLedger
from alpecca.turn_context import TurnContext
import server


def _turn(
    *,
    principal: str = "creator",
    surface: str = "house-hq",
    privacy_scope: str = "creator-personal",
) -> TurnContext:
    return TurnContext.create(
        "creator-house-hq-primary",
        principal=principal,
        surface=surface,
        privacy_scope=privacy_scope,
        portal_epoch="phase8c2-test",
    )


def _initiative() -> dict[str, object]:
    return {
        "allowed": True,
        "scope": "creator-personal",
        "dedupe_key": "volunteer:phase8c2",
    }


class _DeliveryLedger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def begin_dispatch(self, **kwargs):
        self.calls.append(("begin", kwargs))
        return {"state": "dispatching", **kwargs}

    def confirm_delivery(self, delivery_id: str, *, delivered_at: float):
        self.calls.append(("confirm", {"delivery_id": delivery_id, "delivered_at": delivered_at}))
        return {"state": "pending", "delivery_id": delivery_id}

    def cancel_dispatch(self, delivery_id: str, *, cancelled_at: float):
        self.calls.append(("cancel", {"delivery_id": delivery_id, "cancelled_at": cancelled_at}))
        return {"state": "cancelled", "delivery_id": delivery_id}


class _ResponseLedger:
    def __init__(self, *, result: object | None = None, error: Exception | None = None) -> None:
        self.result = {"state": "responded"} if result is None else result
        self.error = error
        self.calls: list[dict[str, object]] = []

    def record_creator_response(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class _OutcomeTrialController:
    def __init__(self, trial_id: object) -> None:
        self.trial_id = trial_id
        self.calls: list[float] = []

    def active_outcome_trial_id(self, *, dispatched_at: float):
        self.calls.append(dispatched_at)
        return self.trial_id


def _delivery_mind(*, cleared: list[tuple[str, str]] | None = None):
    return SimpleNamespace(
        state=SimpleNamespace(mood_label=lambda: "steady", as_dict=lambda: {"mood": "steady"}),
        current_appearance=lambda: SimpleNamespace(as_dict=lambda: {"pose": "idle"}),
        clear_initiative_outreach=(
            lambda scope, key: (cleared if cleared is not None else []).append((scope, key))
        ),
    )


def test_qualified_response_eligibility_requires_the_typed_chatter_candidate():
    turn = _turn()
    initiative = _initiative()

    assert server._qualified_response_outcome_eligible(
        ProactiveCandidate(origin="chatter", reason="A grounded check-in."),
        initiative,
        turn,
    )
    assert not server._qualified_response_outcome_eligible(
        ProactiveCandidate(origin="mood_speech", reason="A mood shift."),
        initiative,
        turn,
    )
    assert not server._qualified_response_outcome_eligible(
        SimpleNamespace(origin="chatter"), initiative, turn
    )
    assert not server._qualified_response_outcome_eligible(
        ProactiveCandidate(origin="chatter", reason="A grounded check-in."),
        {"allowed": False},
        turn,
    )
    assert not server._qualified_response_outcome_eligible(
        ProactiveCandidate(origin="chatter", reason="A grounded check-in."),
        initiative,
        _turn(principal="guest"),
    )


def test_typed_chatter_reserves_before_portal_send_and_confirms_after(monkeypatch):
    ledger = _DeliveryLedger()
    turn = _turn()
    initiative = _initiative()
    broadcasts: list[dict[str, object]] = []
    scheduled: list[dict[str, object]] = []

    async def broadcast(payload):
        assert [name for name, _value in ledger.calls] == ["begin"]
        broadcasts.append(payload)
        return 1

    async def forbidden_channel(*_args, **_kwargs):
        raise AssertionError("a delivered portal event must not use the channel")

    monkeypatch.setattr(server, "qualified_response_ledger", ledger)
    monkeypatch.setattr(server, "ws_clients", {object()})
    monkeypatch.setattr(server, "mind", _delivery_mind())
    monkeypatch.setattr(server, "_broadcast", broadcast)
    monkeypatch.setattr(server, "_bounded_thread", forbidden_channel)
    monkeypatch.setattr(
        server, "_schedule_ignored_outreach", lambda value: scheduled.append(value) or True
    )

    result = asyncio.run(server._deliver_proactive_once(
        "A concise check-in.",
        initiative,
        proactive_turn=turn,
        outcome_candidate=ProactiveCandidate(origin="chatter", reason="check-in"),
    ))

    assert result == {"surface": "portal", "delivered": True, "count": 1}
    assert [name for name, _value in ledger.calls] == ["begin", "confirm"]
    begin = ledger.calls[0][1]
    assert begin["scope_key"] == turn.scope_key
    assert begin["surface"] == turn.surface
    assert begin["proactive_turn_id"] == turn.turn_id
    assert broadcasts == [{
        "type": "proactive",
        "reply": "A concise check-in.",
        "mood": "steady",
        "state": {"mood": "steady"},
        "appearance": {"pose": "idle"},
    }]
    assert scheduled == [initiative]


def test_verified_running_trial_is_attached_to_the_server_owned_dispatch(monkeypatch):
    ledger = _DeliveryLedger()
    controller = _OutcomeTrialController(17)
    turn = _turn()
    server._behavior_trial_recovery_ready.set()
    monkeypatch.setattr(server, "qualified_response_ledger", ledger)
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    monkeypatch.setattr(server._time, "time", lambda: 123.0)

    delivery_id = asyncio.run(server._begin_qualified_response_dispatch(turn))

    assert delivery_id
    assert controller.calls == [123.0]
    assert ledger.calls == [("begin", {
        "delivery_id": delivery_id,
        "scope_key": turn.scope_key,
        "surface": turn.surface,
        "proactive_turn_id": turn.turn_id,
        "response_window_seconds": server.INITIATIVE_RESPONSE_WINDOW_SECONDS,
        "trial_id": 17,
        "dispatched_at": 123.0,
    })]


def test_unrecovered_server_never_queries_for_outcome_trial_attribution(monkeypatch):
    ledger = _DeliveryLedger()
    controller = _OutcomeTrialController(17)
    monkeypatch.setattr(server, "qualified_response_ledger", ledger)
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    monkeypatch.setattr(server._time, "time", lambda: 222.0)

    delivery_id = asyncio.run(server._begin_qualified_response_dispatch(_turn()))

    assert delivery_id
    assert controller.calls == []
    assert ledger.calls[0][1]["trial_id"] is None


@pytest.mark.parametrize("candidate", [None, 0, True, "17"])
def test_unverified_or_invalid_trial_id_leaves_dispatch_baseline_only(monkeypatch, candidate):
    ledger = _DeliveryLedger()
    controller = _OutcomeTrialController(candidate)
    server._behavior_trial_recovery_ready.set()
    monkeypatch.setattr(server, "qualified_response_ledger", ledger)
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    monkeypatch.setattr(server._time, "time", lambda: 321.0)

    delivery_id = asyncio.run(server._begin_qualified_response_dispatch(_turn()))

    assert delivery_id
    assert ledger.calls[0][1]["trial_id"] is None


def test_mood_speech_and_channel_delivery_never_create_metric_exposure(monkeypatch):
    ledger = _DeliveryLedger()
    initiative = _initiative()
    scheduled: list[dict[str, object]] = []

    async def portal(_payload):
        return 1

    async def channel(*_args, **_kwargs):
        return {"ok": True}

    monkeypatch.setattr(server, "qualified_response_ledger", ledger)
    monkeypatch.setattr(server, "mind", _delivery_mind())
    monkeypatch.setattr(
        server, "_schedule_ignored_outreach", lambda value: scheduled.append(value) or True
    )
    monkeypatch.setattr(server, "ws_clients", {object()})
    monkeypatch.setattr(server, "_broadcast", portal)

    portal_result = asyncio.run(server._deliver_proactive_once(
        "A mood update.",
        initiative,
        proactive_turn=_turn(),
        outcome_candidate=ProactiveCandidate(origin="mood_speech", reason="mood"),
    ))

    monkeypatch.setattr(server, "ws_clients", set())
    monkeypatch.setattr(server, "_bounded_thread", channel)
    channel_result = asyncio.run(server._deliver_proactive_once(
        "A channel check-in.",
        initiative,
        proactive_turn=_turn(surface="channel"),
        outcome_candidate=ProactiveCandidate(origin="chatter", reason="check-in"),
    ))

    assert portal_result["delivered"] is True
    assert channel_result["surface"] == "channel"
    assert channel_result["delivered"] is True
    assert ledger.calls == []
    assert scheduled == [initiative, initiative]


def test_failed_portal_dispatch_is_cancelled_and_never_confirmed(monkeypatch):
    ledger = _DeliveryLedger()
    initiative = _initiative()
    cleared: list[tuple[str, str]] = []
    scheduled: list[dict[str, object]] = []

    async def failed_portal(_payload):
        return 0

    async def failed_channel(*_args, **_kwargs):
        return {"ok": False, "queued": True}

    monkeypatch.setattr(server, "qualified_response_ledger", ledger)
    monkeypatch.setattr(server, "ws_clients", {object()})
    monkeypatch.setattr(server, "mind", _delivery_mind(cleared=cleared))
    monkeypatch.setattr(server, "_broadcast", failed_portal)
    monkeypatch.setattr(server, "_bounded_thread", failed_channel)
    monkeypatch.setattr(
        server, "_schedule_ignored_outreach", lambda value: scheduled.append(value) or True
    )

    result = asyncio.run(server._deliver_proactive_once(
        "A check-in that did not arrive.",
        initiative,
        proactive_turn=_turn(),
        outcome_candidate=ProactiveCandidate(origin="chatter", reason="check-in"),
    ))

    assert result["surface"] == "channel"
    assert result["delivered"] is False
    assert result["queued"] is True
    assert [name for name, _value in ledger.calls] == ["begin", "cancel"]
    assert scheduled == []
    assert cleared == [(initiative["scope"], initiative["dedupe_key"])]


def test_authenticated_contentful_portal_turn_matches_without_storing_message_text(monkeypatch):
    ledger = _ResponseLedger()
    turn = _turn()
    monkeypatch.setattr(server, "qualified_response_ledger", ledger)

    matched = asyncio.run(server._record_qualified_creator_response(
        turn,
        "I saw that.",
        "chat",
    ))

    assert matched is True
    assert len(ledger.calls) == 1
    recorded = ledger.calls[0]
    assert recorded["scope_key"] == turn.scope_key
    assert recorded["surface"] == turn.surface
    assert recorded["response_turn_id"] == turn.turn_id
    assert isinstance(recorded["received_at"], float)
    assert "I saw that." not in json.dumps(ledger.calls)


def test_background_guest_blank_and_failed_turns_do_not_match_or_block_chat(monkeypatch):
    ledger = _ResponseLedger(error=RuntimeError("temporary ledger issue"))
    monkeypatch.setattr(server, "qualified_response_ledger", ledger)

    assert asyncio.run(server._record_qualified_creator_response(
        _turn(), "", "chat"
    )) is False
    assert asyncio.run(server._record_qualified_creator_response(
        _turn(), "hello", "house-event"
    )) is False
    assert asyncio.run(server._record_qualified_creator_response(
        _turn(principal="guest", privacy_scope="guest-test"), "hello", "chat"
    )) is False
    assert asyncio.run(server._record_qualified_creator_response(
        _turn(), "hello", "chat"
    )) is False
    assert len(ledger.calls) == 1


def test_protected_house_hq_turn_matches_only_after_background_frame_is_excluded(
    tmp_path, monkeypatch
):
    ledger = QualifiedResponseLedger(tmp_path / "qualified-outcomes.db")
    proactive_turn = TurnContext.create(
        server._server_conversation_id("creator", "house-hq"),
        principal="creator",
        surface="house-hq",
        portal_epoch="phase8c2-proactive",
    )
    dispatched_at = time.time()
    ledger.begin_dispatch(
        delivery_id="house-hq-delivery",
        scope_key=proactive_turn.scope_key,
        surface="house-hq",
        proactive_turn_id=proactive_turn.turn_id,
        response_window_seconds=60.0,
        dispatched_at=dispatched_at,
    )
    ledger.confirm_delivery("house-hq-delivery", delivered_at=dispatched_at + 0.01)

    async def fake_chat(*_args, **_kwargs):
        return {"reply": "Acknowledged."}

    monkeypatch.setattr(server, "qualified_response_ledger", ledger)
    monkeypatch.setattr(server, "_ws_chat_turn_with_timeout", fake_chat)
    monkeypatch.setattr(server, "_mindscape_request_event_sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        server,
        "_record_ws_background_observation",
        lambda *_args, **_kwargs: {"observation_id": 1, "intent": {}},
    )
    monkeypatch.setattr(server, "ws_clients", set())
    monkeypatch.setattr(server, "_ws_portal_epochs", {})
    monkeypatch.setattr(server, "_ws_portal_turns", {})
    monkeypatch.setattr(server, "_active_ws_portal", None)

    client = TestClient(server.app)
    try:
        with client.websocket_connect(
            "/ws/house-hq",
            headers={
                server.auth_mod.AUTHORIZATION_HEADER: f"Bearer {server._AUTH_SECRET}",
            },
        ) as ws:
            assert ws.receive_json()["type"] == "state"
            ws.send_json({
                "text": "A background perception frame.",
                "source": "house-perception",
                "request_id": "caller-background-id",
            })
            assert ws.receive_json()["type"] == "observation_ack"
            assert ledger.summary()["pending"] == 1

            ws.send_json({
                "text": "I saw your check-in.",
                "source": "chat",
                "request_id": "caller-request-id",
            })
            assert ws.receive_json()["type"] == "reply"
    finally:
        client.close()

    assert ledger.summary()["qualified_responses"] == 1
    assert ledger.summary()["rate"] == 1.0
    with sqlite3.connect(ledger.db_path) as conn:
        response_turn_id = conn.execute(
            "SELECT response_turn_id FROM qualified_response_outcomes "
            "WHERE delivery_id='house-hq-delivery'"
        ).fetchone()[0]
    assert response_turn_id
    assert response_turn_id != "caller-request-id"


def test_outcome_ledger_delivery_failures_never_block_portal_delivery_or_count(monkeypatch):
    initiative = _initiative()
    scheduled: list[dict[str, object]] = []
    turn = _turn()

    class _BeginFailureLedger:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def begin_dispatch(self, **_kwargs):
            self.calls.append("begin")
            raise RuntimeError("storage unavailable")

    begin_failure = _BeginFailureLedger()

    async def delivered_portal(_payload):
        return 1

    monkeypatch.setattr(server, "qualified_response_ledger", begin_failure)
    monkeypatch.setattr(server, "ws_clients", {object()})
    monkeypatch.setattr(server, "mind", _delivery_mind())
    monkeypatch.setattr(server, "_broadcast", delivered_portal)
    monkeypatch.setattr(
        server, "_schedule_ignored_outreach", lambda value: scheduled.append(value) or True
    )

    begin_result = asyncio.run(server._deliver_proactive_once(
        "A check-in.",
        initiative,
        proactive_turn=turn,
        outcome_candidate=ProactiveCandidate(origin="chatter", reason="check-in"),
    ))

    class _ConfirmFailureLedger(_DeliveryLedger):
        def confirm_delivery(self, delivery_id: str, *, delivered_at: float):
            self.calls.append(("confirm", {"delivery_id": delivery_id, "delivered_at": delivered_at}))
            raise RuntimeError("confirmation unavailable")

    confirm_failure = _ConfirmFailureLedger()
    monkeypatch.setattr(server, "qualified_response_ledger", confirm_failure)

    confirm_result = asyncio.run(server._deliver_proactive_once(
        "A second check-in.",
        initiative,
        proactive_turn=_turn(),
        outcome_candidate=ProactiveCandidate(origin="chatter", reason="check-in"),
    ))

    assert begin_result["delivered"] is True
    assert begin_failure.calls == ["begin"]
    assert confirm_result["delivered"] is True
    assert [name for name, _value in confirm_failure.calls] == ["begin", "confirm", "cancel"]
    assert scheduled == [initiative, initiative]


def test_outcome_expiry_failure_is_best_effort_and_silent(monkeypatch):
    observations: list[object] = []

    class _BrokenExpiryLedger:
        def expire_due(self, *, now: float):
            assert now == 123.0
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr(server, "qualified_response_ledger", _BrokenExpiryLedger())
    monkeypatch.setattr(
        server.cognition_mod, "record_observation", lambda observation: observations.append(observation)
    )

    assert asyncio.run(server._expire_due_qualified_response_outcomes_once(now=123.0)) == []
    assert observations == []


def test_outcome_expiry_records_only_aggregate_maintenance_evidence(monkeypatch):
    observations: list[object] = []

    class _ExpiryLedger:
        def expire_due(self, *, now: float):
            assert now == 123.0
            return [
                {"delivery_id": "private-1", "state": "unanswered"},
                {"delivery_id": "private-2", "state": "cancelled"},
            ]

    monkeypatch.setattr(server, "qualified_response_ledger", _ExpiryLedger())
    monkeypatch.setattr(
        server.cognition_mod, "record_observation", lambda observation: observations.append(observation)
    )

    closed = asyncio.run(server._expire_due_qualified_response_outcomes_once(now=123.0))

    assert len(closed) == 2
    assert len(observations) == 1
    observation = observations[0]
    assert observation.source == "qualified_response_outcome_maintenance"
    assert observation.metadata == {
        "closure_count": 2,
        "unanswered": 1,
        "cancelled": 1,
    }
    assert "private-" not in observation.content


@pytest.fixture(autouse=True)
def _restore_recovery_gate():
    initially_ready = server._behavior_trial_recovery_ready.is_set()
    server._behavior_trial_recovery_ready.clear()
    yield
    if initially_ready:
        server._behavior_trial_recovery_ready.set()
    else:
        server._behavior_trial_recovery_ready.clear()


def test_status_includes_read_only_aggregate_evidence_without_mutating_controller_snapshot(monkeypatch):
    snapshot = {"state": "ready", "active_trial": None}
    evidence = {
        "metric": "qualified_response_rate",
        "definition_version": 1,
        "completed": 0,
        "rate": None,
    }

    class _Controller:
        def status_snapshot(self):
            return snapshot

    class _StatusLedger:
        def summary(self):
            return evidence

    request = SimpleNamespace(state=SimpleNamespace(
        authorization=server.auth_mod.AuthDecision(
            True, "test", "accepted", principal="creator"
        )
    ))
    monkeypatch.setattr(server, "behavior_trial_controller", _Controller())
    monkeypatch.setattr(server, "qualified_response_ledger", _StatusLedger())
    server._behavior_trial_recovery_ready.set()

    response = server.behavior_trial_status(request)

    assert response.status_code == 200
    assert json.loads(response.body) == {
        **snapshot,
        "outcome_evidence": evidence,
        "review_settlements": [],
        "review_settlements_available": True,
        "registration_candidate": None,
        "registration_candidate_available": True,
    }
    assert snapshot == {"state": "ready", "active_trial": None}
