"""Focused server coverage for the Phase 8 behavior-trial recovery gate."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from config import PUBLIC_IDENTITY
import server


class _BehaviorTrialController:
    def __init__(
        self,
        *,
        default_chatter_chance: float = 0.25,
        effective_chatter_chance: float = 0.12,
        recovery_error: Exception | None = None,
        closed_trials: list[dict[str, object]] | None = None,
        maintenance_error: Exception | None = None,
    ) -> None:
        self.default_chatter_chance = default_chatter_chance
        self.effective_chatter_chance = effective_chatter_chance
        self.recovery_error = recovery_error
        self.closed_trials = [] if closed_trials is None else closed_trials
        self.maintenance_error = maintenance_error
        self.recovery_calls = 0
        self.chatter_chance_calls = 0
        self.maintain_runtime_state_calls = 0
        self.expire_due_calls = 0

    def recover_interrupted(self) -> list[dict[str, object]]:
        self.recovery_calls += 1
        if self.recovery_error is not None:
            raise self.recovery_error
        return []

    def chatter_chance(self) -> float:
        self.chatter_chance_calls += 1
        return self.effective_chatter_chance

    def maintain_runtime_state(self) -> list[dict[str, object]]:
        self.maintain_runtime_state_calls += 1
        if self.maintenance_error is not None:
            raise self.maintenance_error
        return list(self.closed_trials)

    def expire_due(self) -> list[dict[str, object]]:
        self.expire_due_calls += 1
        raise AssertionError("runtime maintenance must not call expire_due")


class _ReadOnlyStatusController:
    def __init__(self, snapshot: dict[str, object]) -> None:
        self.snapshot = snapshot
        self.calls: list[str] = []

    def status_snapshot(self) -> dict[str, object]:
        self.calls.append("status_snapshot")
        return self.snapshot

    def _unexpected_call(self, name: str) -> None:
        self.calls.append(name)
        raise AssertionError(f"status endpoint must not call {name}")

    def chatter_chance(self) -> float:
        self._unexpected_call("chatter_chance")
        return 0.0  # pragma: no cover - _unexpected_call always raises

    def maintain_runtime_state(self) -> list[dict[str, object]]:
        self._unexpected_call("maintain_runtime_state")
        return []  # pragma: no cover - _unexpected_call always raises

    def expire_due(self) -> list[dict[str, object]]:
        self._unexpected_call("expire_due")
        return []  # pragma: no cover - _unexpected_call always raises

    def recover_interrupted(self) -> list[dict[str, object]]:
        self._unexpected_call("recover_interrupted")
        return []  # pragma: no cover - _unexpected_call always raises

    def start(self, *_args, **_kwargs) -> dict[str, object]:
        self._unexpected_call("start")
        return {}  # pragma: no cover - _unexpected_call always raises

    def rollback(self, *_args, **_kwargs) -> dict[str, object]:
        self._unexpected_call("rollback")
        return {}  # pragma: no cover - _unexpected_call always raises

    def approve(self, *_args, **_kwargs) -> dict[str, object]:
        self._unexpected_call("approve")
        return {}  # pragma: no cover - _unexpected_call always raises


class _ReadOnlyOutcomeLedger:
    def __init__(self, snapshot: dict[str, object]) -> None:
        self.snapshot = snapshot
        self.calls: list[str] = []

    def summary(self) -> dict[str, object]:
        self.calls.append("summary")
        return self.snapshot


def _trial_record(*, state: str = "registered") -> dict[str, object]:
    return {
        "id": 9,
        "scope": "creator-personal",
        "proposal_id": 51,
        "state": state,
        "spec_sha256": "a" * 64,
        "spec": {
            "parameter": "chatter_chance",
            "metric": "qualified_response_rate",
        },
        "approval_proof": {"proof_id": "must-not-leak"},
    }


class _CreatorApprovalController:
    def __init__(self, record: dict[str, object] | None = None) -> None:
        self.record = _trial_record() if record is None else record
        self.calls: list[tuple[str, object]] = []

    def get(self, trial_id: int):
        self.calls.append(("get", trial_id))
        return self.record if trial_id == self.record["id"] else None

    def approve_creator(self, trial_id: int, **kwargs):
        self.calls.append(("approve_creator", {"trial_id": trial_id, **kwargs}))
        if trial_id != self.record["id"]:
            raise ValueError("missing trial")
        return {**self.record, "state": "approved"}


class _DirectRequest:
    def __init__(self, authorization: object | None = None) -> None:
        self.state = SimpleNamespace()
        if authorization is not None:
            self.state.authorization = authorization


def _creator_request() -> _DirectRequest:
    return _DirectRequest(server.auth_mod.AuthDecision(
        True,
        "test",
        "accepted",
        principal="creator",
    ))


def _guest_request() -> _DirectRequest:
    return _DirectRequest(server.auth_mod.AuthDecision(
        True,
        "test",
        "accepted",
        principal="guest",
    ))


class _AllowedNonCreatorAuthority:
    def __init__(self) -> None:
        self.calls = 0

    def authorize_request(self, **_kwargs) -> server.auth_mod.AuthDecision:
        self.calls += 1
        return server.auth_mod.AuthDecision(
            True,
            "test_authority",
            "accepted",
            principal="guest",
        )


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


def test_behavior_trial_runtime_maintenance_does_not_run_before_recovery(monkeypatch):
    controller = _BehaviorTrialController(closed_trials=[{"id": 41}])
    observations = []
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    monkeypatch.setattr(
        server.cognition_mod,
        "record_observation",
        lambda observation: observations.append(observation),
    )

    asyncio.run(server._expire_due_behavior_trials_once())

    assert controller.maintain_runtime_state_calls == 0
    assert controller.expire_due_calls == 0
    assert controller.chatter_chance_calls == 0
    assert observations == []


def test_behavior_trial_runtime_maintenance_receipts_invalid_binding_closures_after_recovery_without_chatter(
    monkeypatch,
):
    controller = _BehaviorTrialController(closed_trials=[{
        "id": 41,
        "rollback": {
            "reason": "creator approval binding could not be verified",
        },
    }])
    observations = []
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    monkeypatch.setattr(
        server.cognition_mod,
        "record_observation",
        lambda observation: observations.append(observation),
    )
    server._behavior_trial_recovery_ready.set()

    asyncio.run(server._expire_due_behavior_trials_once())

    assert controller.maintain_runtime_state_calls == 1
    assert controller.expire_due_calls == 0
    assert controller.chatter_chance_calls == 0
    assert len(observations) == 1
    assert observations[0].source == "behavior_trial_maintenance"
    assert "expired" not in observations[0].content
    assert observations[0].metadata == {
        "trial_count": 1,
        "trial_ids": [41],
        "terminal_state": "rolled_back",
    }


def test_behavior_trial_runtime_maintenance_records_only_closed_trials(monkeypatch):
    controller = _BehaviorTrialController()
    observations = []
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    monkeypatch.setattr(
        server.cognition_mod,
        "record_observation",
        lambda observation: observations.append(observation),
    )
    server._behavior_trial_recovery_ready.set()

    asyncio.run(server._expire_due_behavior_trials_once())

    assert controller.maintain_runtime_state_calls == 1
    assert controller.expire_due_calls == 0
    assert observations == []


def test_behavior_trial_runtime_maintenance_ignores_controller_failures(monkeypatch):
    controller = _BehaviorTrialController(maintenance_error=RuntimeError("database unavailable"))
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    server._behavior_trial_recovery_ready.set()

    asyncio.run(server._expire_due_behavior_trials_once())

    assert controller.maintain_runtime_state_calls == 1
    assert controller.expire_due_calls == 0
    assert controller.chatter_chance_calls == 0


def test_behavior_trial_status_handler_returns_snapshot_for_creator(monkeypatch):
    snapshot = {
        "state": "ready",
        "active_trial": None,
        "recent": [],
    }
    controller = _ReadOnlyStatusController(snapshot)
    outcome = _ReadOnlyOutcomeLedger({"metric": "qualified_response_rate", "completed": 0})
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    monkeypatch.setattr(server, "qualified_response_ledger", outcome)
    server._behavior_trial_recovery_ready.set()

    response = server.behavior_trial_status(_creator_request())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(response.body) == {
        **snapshot,
        "outcome_evidence": outcome.snapshot,
    }
    assert controller.calls == ["status_snapshot"]
    assert outcome.calls == ["summary"]


def test_behavior_trial_status_handler_rejects_anonymous_before_controller_access(monkeypatch):
    controller = _ReadOnlyStatusController({"state": "ready"})
    monkeypatch.setattr(server, "behavior_trial_controller", controller)

    with pytest.raises(server.HTTPException) as exc_info:
        server.behavior_trial_status(_DirectRequest())

    assert exc_info.value.status_code == 401
    assert controller.calls == []


def test_behavior_trial_status_handler_rejects_allowed_guest_before_controller_access(monkeypatch):
    controller = _ReadOnlyStatusController({"state": "ready"})
    monkeypatch.setattr(server, "behavior_trial_controller", controller)

    with pytest.raises(server.HTTPException) as exc_info:
        server.behavior_trial_status(_guest_request())

    assert exc_info.value.status_code == 403
    assert controller.calls == []


def test_behavior_trial_status_handler_returns_503_until_recovery(monkeypatch):
    controller = _ReadOnlyStatusController({"state": "ready"})
    monkeypatch.setattr(server, "behavior_trial_controller", controller)

    response = server.behavior_trial_status(_creator_request())

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(response.body) == {
        "detail": "behavior trial recovery is not ready",
    }
    assert controller.calls == []


def test_behavior_trial_status_handler_never_calls_mutators(monkeypatch):
    controller = _ReadOnlyStatusController({"state": "ready", "recent": []})
    outcome = _ReadOnlyOutcomeLedger({"metric": "qualified_response_rate", "completed": 0})
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    monkeypatch.setattr(server, "qualified_response_ledger", outcome)
    server._behavior_trial_recovery_ready.set()

    response = server.behavior_trial_status(_creator_request())

    assert response.status_code == 200
    assert controller.calls == ["status_snapshot"]
    assert outcome.calls == ["summary"]


def test_creator_approval_route_derives_all_facts_from_server_authorization(monkeypatch):
    controller = _CreatorApprovalController()
    observations: list[object] = []
    decision = server.auth_mod.AuthDecision(
        True,
        "session_cookie",
        "accepted",
        principal="creator",
        issued_at=100,
        expires_at=200,
    )
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    monkeypatch.setattr(server._time, "time", lambda: 150.0)
    monkeypatch.setattr(
        server.cognition_mod, "record_observation", lambda observation: observations.append(observation)
    )
    server._behavior_trial_recovery_ready.set()

    response = server.behavior_trial_creator_approve(
        9, _DirectRequest(decision)
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert json.loads(response.body) == {
        "approved": True,
        "trial": {
            "id": 9,
            "scope": "creator-personal",
            "proposal_id": 51,
            "state": "approved",
            "parameter": "chatter_chance",
            "metric": "qualified_response_rate",
            "spec_sha256": "a" * 64,
        },
    }
    assert controller.calls == [
        ("get", 9),
        ("approve_creator", {
            "trial_id": 9,
            "principal": "creator",
            "authorization_mechanism": "session_cookie",
            "authorization_issued_at": 100,
            "authorization_expires_at": 200,
            "approved_at": 150.0,
        }),
    ]
    assert len(observations) == 1
    assert observations[0].source == "behavior_trial_creator_approval"
    assert observations[0].metadata == {
        "trial_id": 9,
        "scope": "creator-personal",
        "parameter": "chatter_chance",
        "metric": "qualified_response_rate",
        "authorization": "session_cookie",
        "approved_at": 150.0,
        "started": False,
    }
    assert "must-not-leak" not in response.body.decode("utf-8")


def test_creator_approval_route_is_unavailable_until_recovery(monkeypatch):
    controller = _CreatorApprovalController()
    monkeypatch.setattr(server, "behavior_trial_controller", controller)

    response = server.behavior_trial_creator_approve(9, _creator_request())

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert controller.calls == []


def test_creator_approval_route_rejects_missing_or_terminal_trials(monkeypatch):
    missing = _CreatorApprovalController()
    monkeypatch.setattr(server, "behavior_trial_controller", missing)
    server._behavior_trial_recovery_ready.set()

    with pytest.raises(server.HTTPException) as missing_error:
        server.behavior_trial_creator_approve(99, _creator_request())

    assert missing_error.value.status_code == 404
    assert missing.calls == [("get", 99)]

    terminal = _CreatorApprovalController(_trial_record(state="running"))
    monkeypatch.setattr(server, "behavior_trial_controller", terminal)
    with pytest.raises(server.HTTPException) as terminal_error:
        server.behavior_trial_creator_approve(9, _creator_request())

    assert terminal_error.value.status_code == 409
    assert terminal.calls == [("get", 9)]


def test_creator_approval_route_hides_controller_validation_detail(monkeypatch):
    class _RejectingController(_CreatorApprovalController):
        def approve_creator(self, trial_id: int, **kwargs):
            self.calls.append(("approve_creator", {"trial_id": trial_id, **kwargs}))
            raise ValueError("private binding state must not reach the browser")

    controller = _RejectingController()
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    server._behavior_trial_recovery_ready.set()

    with pytest.raises(server.HTTPException) as error:
        server.behavior_trial_creator_approve(9, _creator_request())

    assert error.value.status_code == 409
    assert error.value.detail == "behavior trial cannot be creator-approved"
    assert "private binding" not in error.value.detail
    assert error.value.headers == {"Cache-Control": "no-store"}


def test_creator_approval_asgi_uses_protected_bearer_without_a_start_route(monkeypatch):
    controller = _CreatorApprovalController()
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    monkeypatch.setattr(server.cognition_mod, "record_observation", lambda _observation: None)
    server._behavior_trial_recovery_ready.set()
    client = TestClient(server.app)
    try:
        response = client.post(
            "/behavior-trials/9/approve",
            headers={
                server.auth_mod.AUTHORIZATION_HEADER: f"Bearer {server._AUTH_SECRET}",
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["trial"]["state"] == "approved"
    approval = controller.calls[1][1]
    assert approval["authorization_mechanism"] == "bearer"
    assert approval["authorization_issued_at"] is None
    assert approval["authorization_expires_at"] is None
    assert approval["principal"] == "creator"


def test_creator_approval_asgi_rejects_anonymous_and_public_identity_spoof(monkeypatch):
    controller = _CreatorApprovalController()
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    server._behavior_trial_recovery_ready.set()
    client = TestClient(server.app)
    try:
        anonymous = client.post("/behavior-trials/9/approve")
        spoofed = client.post(
            "/behavior-trials/9/approve",
            headers={"X-Alpecca-Identity": PUBLIC_IDENTITY},
        )
    finally:
        client.close()

    assert anonymous.status_code == 401
    assert spoofed.status_code == 401
    assert controller.calls == []


def test_behavior_trial_status_asgi_rejects_anonymous_and_public_identity_spoof(
    monkeypatch,
):
    controller = _ReadOnlyStatusController({"state": "ready"})
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    client = TestClient(server.app)
    try:
        anonymous = client.get("/behavior-trials/status")
        spoofed = client.get(
            "/behavior-trials/status",
            headers={"X-Alpecca-Identity": PUBLIC_IDENTITY},
        )
    finally:
        client.close()

    assert anonymous.status_code == 401
    assert spoofed.status_code == 401
    assert controller.calls == []


def test_behavior_trial_status_asgi_returns_snapshot_for_protected_bearer(monkeypatch):
    snapshot = {"state": "ready", "active_trial": None, "recent": []}
    controller = _ReadOnlyStatusController(snapshot)
    outcome = _ReadOnlyOutcomeLedger({"metric": "qualified_response_rate", "completed": 0})
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    monkeypatch.setattr(server, "qualified_response_ledger", outcome)
    server._behavior_trial_recovery_ready.set()
    client = TestClient(server.app)
    try:
        response = client.get(
            "/behavior-trials/status",
            headers={
                server.auth_mod.AUTHORIZATION_HEADER: f"Bearer {server._AUTH_SECRET}",
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {**snapshot, "outcome_evidence": outcome.snapshot}
    assert controller.calls == ["status_snapshot"]
    assert outcome.calls == ["summary"]


def test_behavior_trial_status_asgi_rejects_allowed_non_creator_before_controller_access(
    monkeypatch,
):
    controller = _ReadOnlyStatusController({"state": "ready"})
    authority = _AllowedNonCreatorAuthority()
    monkeypatch.setattr(server, "behavior_trial_controller", controller)
    monkeypatch.setattr(server, "_AUTHORITY", authority)
    client = TestClient(server.app)
    try:
        response = client.get("/behavior-trials/status")
    finally:
        client.close()

    assert authority.calls == 1
    assert response.status_code == 403
    assert controller.calls == []


def test_behavior_trial_route_inventory_has_only_status_and_creator_approval():
    behavior_trial_routes = {
        (route.path, method)
        for route in server.app.routes
        if getattr(route, "path", "").startswith("/behavior-trials")
        for method in (getattr(route, "methods", None) or ())
    }
    status_route = next(
        route
        for route in server.app.routes
        if getattr(route, "path", "") == "/behavior-trials/status"
    )

    assert behavior_trial_routes == {
        ("/behavior-trials/status", "GET"),
        ("/behavior-trials/{trial_id}/approve", "POST"),
    }
    assert status_route.dependant.query_params == []
    assert status_route.dependant.body_params == []
    assert not any(path.endswith("/start") for path, _method in behavior_trial_routes)


def test_server_exposes_no_self_improvement_trial_routes():
    route_paths = {route.path for route in server.app.routes}

    assert "/self-improvement" not in route_paths
    assert not any(path.startswith("/self-improvement/") for path in route_paths)
