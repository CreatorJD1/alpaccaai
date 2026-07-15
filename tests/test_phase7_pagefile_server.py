"""Focused server and Brain Garden tests for the inert Phase 7 surface."""
from __future__ import annotations

import asyncio
import inspect
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import server
from alpecca import brain_graph, pagefile_approval, system_pressure


GiB = 1024**3


def _host_snapshot() -> dict[str, object]:
    return {
        "state": "ready",
        "commit": {
            "state": "known",
            "used_bytes": 85 * GiB,
            "limit_bytes": 100 * GiB,
        },
        "disk": {
            "state": "known",
            "free_bytes": 50 * GiB,
            "total_bytes": 500 * GiB,
        },
    }


def _telemetry(maximum_mib: int = 38_000) -> dict[str, object]:
    return {
        "schema": server.pagefile_telemetry_mod.SCHEMA,
        "state": "ready",
        "platform": "windows",
        "evidence": {
            "powershell": {
                "available": True,
                "state": "available",
                "reason": None,
            },
            "wmi": {
                "available": True,
                "state": "available",
                "management": "available",
                "configuration": "available",
                "usage": "available",
                "reason": None,
            },
        },
        "configured": {
            "state": "known",
            "mode": "custom",
            "initial_mib": maximum_mib,
            "maximum_mib": maximum_mib,
            "entry_count": 1,
        },
        "usage": {
            "state": "known",
            "allocated_mib": maximum_mib,
            "used_mib": 2_048,
            "free_mib": maximum_mib - 2_048,
            "peak_used_mib": 4_096,
            "entry_count": 1,
        },
    }


def _proposed_plan(current_maximum_mib: int = 38_000) -> dict[str, object]:
    proposal = system_pressure.propose_pagefile_plan(
        _host_snapshot(),
        {"state": "known", "maximum_mib": current_maximum_mib},
    )
    assert proposal["state"] == "proposed"
    assert type(proposal["plan"]) is dict
    return proposal["plan"]


def _authorization(principal: str = "creator") -> server.auth_mod.AuthDecision:
    return server.auth_mod.AuthDecision(
        True,
        "test",
        "accepted",
        principal=principal,
    )


class _DirectRequest:
    def __init__(self, authorization: object | None, body: object | None = None):
        self.state = SimpleNamespace()
        if authorization is not None:
            self.state.authorization = authorization
        self._raw = b"" if body is None else json.dumps(body).encode("utf-8")
        self.headers = (
            {"content-length": str(len(self._raw))} if self._raw else {}
        )

    async def stream(self):
        yield self._raw


def _response_payload(response) -> dict[str, object]:
    return json.loads(response.body)


class _Sampler:
    def __init__(self, thread_ids: list[int]):
        self.thread_ids = thread_ids

    def snapshot(self, force: bool = False) -> dict[str, object]:
        assert force is True
        self.thread_ids.append(threading.get_ident())
        return _host_snapshot()


class _RecordingLedger:
    def __init__(self, inner: pagefile_approval.PagefileApprovalLedger):
        self.inner = inner
        self.create_threads: list[int] = []
        self.approve_threads: list[int] = []
        self.approve_arguments: list[tuple[object, object]] = []

    def create_request(self, plan: object) -> dict[str, object]:
        self.create_threads.append(threading.get_ident())
        return self.inner.create_request(plan)

    def approve_request(
        self,
        request_token: object,
        plan: object,
        *,
        principal: object,
        approved: object,
    ) -> dict[str, object]:
        self.approve_threads.append(threading.get_ident())
        self.approve_arguments.append((principal, approved))
        return self.inner.approve_request(
            request_token,
            plan,
            principal=principal,
            approved=approved,
        )


@pytest.mark.parametrize(
    ("authorization", "expected_status"),
    ((None, 401), (_authorization("guest"), 403)),
)
@pytest.mark.parametrize(
    "route_name",
    ("pagefile_read", "pagefile_request", "pagefile_approve"),
)
def test_pagefile_routes_reject_non_creator_before_probe_or_body(
    monkeypatch,
    authorization: object | None,
    expected_status: int,
    route_name: str,
) -> None:
    calls: list[str] = []

    def unexpected_probe():
        calls.append("probe")
        raise AssertionError("authorization must precede pagefile collection")

    async def unexpected_body(*_args, **_kwargs):
        calls.append("body")
        raise AssertionError("authorization must precede body ingress")

    monkeypatch.setattr(server, "_collect_pagefile_live_evidence", unexpected_probe)
    monkeypatch.setattr(server, "_read_bounded_json_object", unexpected_body)
    route = getattr(server, route_name)

    with pytest.raises(server.HTTPException) as exc:
        asyncio.run(route(_DirectRequest(authorization)))

    assert exc.value.status_code == expected_status
    assert exc.value.headers == {"Cache-Control": "no-store"}
    assert calls == []


def test_read_collects_wmi_and_host_facts_off_event_loop(monkeypatch) -> None:
    collector_threads: list[int] = []
    sampler_threads: list[int] = []

    def collect() -> dict[str, object]:
        collector_threads.append(threading.get_ident())
        return _telemetry()

    monkeypatch.setattr(
        server.pagefile_telemetry_mod,
        "collect_pagefile_telemetry",
        collect,
    )
    monkeypatch.setattr(server, "_host_resource_sampler", _Sampler(sampler_threads))

    async def exercise():
        loop_thread = threading.get_ident()
        response = await server.pagefile_read(_DirectRequest(_authorization()))
        return loop_thread, response

    loop_thread, response = asyncio.run(exercise())
    payload = _response_payload(response)
    serialized = json.dumps(payload, sort_keys=True)

    assert response.headers["cache-control"] == "no-store"
    assert collector_threads and sampler_threads
    assert all(thread_id != loop_thread for thread_id in collector_threads)
    assert all(thread_id != loop_thread for thread_id in sampler_threads)
    assert payload["state"] == "blocked"
    assert payload["proposal"]["state"] == "proposed"
    assert payload["approval"]["consume_available"] is False
    assert payload["execution"] == {
        "available": False,
        "authorized": False,
        "mutation_available": False,
        "elevation_available": False,
    }
    assert set(payload["gates"].values()) == {False}
    assert "pfr1_" not in serialized
    assert "pfa1_" not in serialized


def test_first_ledger_open_is_lazy_and_off_event_loop(monkeypatch) -> None:
    constructor_threads: list[int] = []
    transition_threads: list[int] = []

    class LazyLedger:
        def __init__(self, _db_path: object):
            constructor_threads.append(threading.get_ident())

        def create_request(self, plan: object) -> dict[str, object]:
            transition_threads.append(threading.get_ident())
            assert plan == _proposed_plan()
            return {
                "schema": pagefile_approval.REQUEST_SCHEMA,
                "request_id": "pfrq_test",
                "request_token": "pfr1_" + "A" * 43,
                "plan_digest": "0" * 64,
                "state": "pending",
                "expires_at": 1_000,
                "approved": False,
            }

    proposal = system_pressure.propose_pagefile_plan(
        _host_snapshot(),
        {"state": "known", "maximum_mib": 38_000},
    )
    monkeypatch.setattr(server, "_PAGEFILE_APPROVAL_LEDGER", None)
    monkeypatch.setattr(
        server.pagefile_approval_mod,
        "PagefileApprovalLedger",
        LazyLedger,
    )
    monkeypatch.setattr(
        server,
        "_collect_pagefile_live_evidence",
        lambda: {
            "schema": server._PAGEFILE_LIVE_EVIDENCE_SCHEMA,
            "state": "blocked",
            "proposal": proposal,
            **server._pagefile_blocked_controls(),
        },
    )

    async def exercise():
        loop_thread = threading.get_ident()
        response = await server.pagefile_request(_DirectRequest(_authorization()))
        return loop_thread, response

    loop_thread, response = asyncio.run(exercise())

    assert response.status_code == 200
    assert constructor_threads and transition_threads
    assert all(item != loop_thread for item in constructor_threads)
    assert all(item != loop_thread for item in transition_threads)


def test_request_and_approve_are_exact_one_use_and_threaded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "pagefile-live.sqlite3"
    recording = _RecordingLedger(
        pagefile_approval.PagefileApprovalLedger(db_path)
    )
    monkeypatch.setattr(server, "_PAGEFILE_APPROVAL_LEDGER", recording)
    monkeypatch.setattr(
        server.pagefile_telemetry_mod,
        "collect_pagefile_telemetry",
        _telemetry,
    )
    monkeypatch.setattr(server, "_host_resource_sampler", _Sampler([]))

    async def exercise():
        loop_thread = threading.get_ident()
        request_response = await server.pagefile_request(
            _DirectRequest(_authorization())
        )
        request_payload = _response_payload(request_response)
        request_token = request_payload["request"]["request_token"]
        plan = request_payload["plan"]

        with pytest.raises(server.HTTPException) as denied:
            await server.pagefile_approve(_DirectRequest(
                _authorization(),
                {
                    "request_token": request_token,
                    "plan": plan,
                    "approved": False,
                },
            ))

        with pytest.raises(server.HTTPException) as mismatch:
            await server.pagefile_approve(_DirectRequest(
                _authorization(),
                {
                    "request_token": request_token,
                    "plan": _proposed_plan(42_096),
                    "approved": True,
                },
            ))

        approval_response = await server.pagefile_approve(_DirectRequest(
            _authorization(),
            {
                "request_token": request_token,
                "plan": plan,
                "approved": True,
            },
        ))
        with pytest.raises(server.HTTPException) as replay:
            await server.pagefile_approve(_DirectRequest(
                _authorization(),
                {
                    "request_token": request_token,
                    "plan": plan,
                    "approved": True,
                },
            ))
        return (
            loop_thread,
            request_response,
            approval_response,
            denied.value,
            mismatch.value,
            replay.value,
        )

    (
        loop_thread,
        request_response,
        approval_response,
        denied,
        mismatch,
        replay,
    ) = asyncio.run(exercise())
    request_payload = _response_payload(request_response)
    approval_payload = _response_payload(approval_response)
    request_token = request_payload["request"]["request_token"]
    approval_token = approval_payload["approval"]["approval_token"]

    assert denied.status_code == 400
    assert denied.detail == {"code": "explicit_approval_required"}
    assert mismatch.status_code == 409
    assert mismatch.detail == {"code": "plan_mismatch"}
    assert replay.status_code == 409
    assert replay.detail == {"code": "request_replayed"}
    assert request_payload["phase_state"] == "blocked"
    assert approval_payload["phase_state"] == "blocked"
    assert approval_payload["approval"]["principal"] == "CreatorJD"
    assert approval_payload["execution"]["available"] is False
    assert set(approval_payload["gates"].values()) == {False}
    assert json.dumps(request_payload).count(request_token) == 1
    assert request_token not in json.dumps(approval_payload)
    assert json.dumps(approval_payload).count(approval_token) == 1
    assert recording.create_threads
    assert recording.approve_threads
    assert all(item != loop_thread for item in recording.create_threads)
    assert all(item != loop_thread for item in recording.approve_threads)
    assert recording.approve_arguments == [
        ("CreatorJD", True),
        ("CreatorJD", True),
        ("CreatorJD", True),
    ]

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT request_token_digest, approval_token_digest "
            "FROM phase7_pagefile_approvals"
        ).fetchone()
    assert row is not None
    persisted = json.dumps(row)
    assert request_token not in persisted
    assert approval_token not in persisted
    assert all(len(value) == 64 for value in row)


def test_brain_garden_keeps_p7_blocked_and_projects_no_tokens() -> None:
    secret = "pfr1_private-token-must-not-reach-brain-garden"
    surface = {
        "schema": server._PAGEFILE_LIVE_EVIDENCE_SCHEMA,
        "state": "blocked",
        "telemetry": _telemetry(),
        "proposal": {
            "state": "proposed",
            "plan": _proposed_plan(),
            "secret": secret,
        },
        **server._pagefile_blocked_controls(),
        "request_token": secret,
    }

    snapshot = brain_graph.build_snapshot({"pagefile_evidence": surface})
    node = next(
        item for item in snapshot["nodes"] if item["id"] == "alpecca-core:p7"
    )
    serialized = json.dumps(node, sort_keys=True)

    assert node["state"] == "unfinished"
    assert "blocks phase completion" in node["summary"]
    assert "no consume or execution surface" in node["summary"]
    assert "phase7.state=blocked" in node["evidence"]
    assert "pagefile.approval.request=true" in node["evidence"]
    assert "pagefile.approval.approve=true" in node["evidence"]
    assert "pagefile.approval.consume=false" in node["evidence"]
    assert "pagefile.execution.available=false" in node["evidence"]
    assert secret not in serialized


def test_only_read_request_and_approve_pagefile_routes_exist() -> None:
    routes = {
        (route.path, frozenset(route.methods or ()))
        for route in server.app.routes
        if route.path.startswith("/system/pagefile")
    }
    assert routes == {
        ("/system/pagefile", frozenset({"GET"})),
        ("/system/pagefile/request", frozenset({"POST"})),
        ("/system/pagefile/approve", frozenset({"POST"})),
    }
    assert "consume_approval" not in inspect.getsource(server.pagefile_approve)

    manifest = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "alpecca"
            / "brain_plugins"
            / "alpecca_core.json"
        ).read_text(encoding="utf-8")
    )
    node = next(item for item in manifest["nodes"] if item["id"] == "p7")
    assert node["probe"] == "pagefile"
    assert "No consume, mutation, execution, or elevation route exists" in node["detail"]
