"""Phase 4 payload-backed execution and terminal receipt coverage."""
from __future__ import annotations

import sqlite3

import pytest

from alpecca import commitment_executor
from alpecca import commitments
from alpecca import turn_context


SCOPE = "creator-personal"


class FakeToolkit:
    def __init__(self, result: str = '{"turn":{"principal":"creator"}}') -> None:
        self.result = result
        self.calls: list[tuple[str, dict, turn_context.TurnContext]] = []

    def execute(self, tool: str, args: dict, *, turn: turn_context.TurnContext) -> str:
        self.calls.append((tool, args, turn))
        return self.result


def _turn(*, principal: str = "creator", scope: str = SCOPE, surface: str = "workshop"):
    return turn_context.TurnContext.create(
        "creator-workshop-primary",
        principal=principal,
        surface=surface,
        privacy_scope=scope,
        portal_epoch="test-workshop",
    )


def _approved(db_path, *, payload=True):
    created = commitments.create_commitment(
        "Check my current scoped self status",
        scope=SCOPE,
        evidence={"source": "test"},
        payload=(
            commitment_executor.build_payload("self_status", {})
            if payload else None
        ),
        db_path=db_path,
    )
    return commitments.transition_commitment(
        created["id"],
        commitments.APPROVED,
        scope=SCOPE,
        evidence={"approved_by": "creator"},
        db_path=db_path,
    )


def test_payload_is_persisted_and_old_schema_is_migrated(tmp_path):
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE commitments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                scope TEXT NOT NULL,
                action TEXT NOT NULL,
                state TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                receipt_json TEXT
            )
            """
        )
    commitments.init_db(db_path)
    columns = {
        row[1]
        for row in sqlite3.connect(db_path).execute("PRAGMA table_info(commitments)")
    }
    assert "payload_json" in columns

    approved = _approved(db_path)
    assert approved["payload"] == {
        "version": 1,
        "tool": "self_status",
        "args": {},
    }


def test_approved_self_status_executes_once_and_closes_with_receipt(tmp_path):
    db_path = tmp_path / "execute.db"
    approved = _approved(db_path)
    toolkit = FakeToolkit()

    result = commitment_executor.execute_approved_commitment(
        approved["id"], toolkit=toolkit, turn=_turn(), db_path=db_path,
    )

    assert result["ok"] is True
    assert result["commitment"]["state"] == commitments.SUCCEEDED
    assert result["commitment"]["receipt"]["status"] == "succeeded"
    assert result["commitment"]["receipt"]["tool"] == "self_status"
    assert [row["to_state"] for row in result["commitment"]["receipts"]] == [
        commitments.PROPOSED,
        commitments.APPROVED,
        commitments.RUNNING,
        commitments.SUCCEEDED,
    ]
    assert len(toolkit.calls) == 1
    assert toolkit.calls[0][2].surface == "workshop"

    with pytest.raises(PermissionError, match="must be approved"):
        commitment_executor.execute_approved_commitment(
            approved["id"], toolkit=toolkit, turn=_turn(), db_path=db_path,
        )
    assert len(toolkit.calls) == 1


def test_text_only_or_cross_scope_commitments_never_execute(tmp_path):
    db_path = tmp_path / "denied.db"
    text_only = _approved(db_path, payload=False)
    toolkit = FakeToolkit()

    with pytest.raises(
        commitment_executor.CommitmentExecutionError,
        match="no machine payload",
    ):
        commitment_executor.execute_approved_commitment(
            text_only["id"], toolkit=toolkit, turn=_turn(), db_path=db_path,
        )
    with pytest.raises(commitments.CommitmentNotFound):
        commitment_executor.execute_approved_commitment(
            text_only["id"],
            toolkit=toolkit,
            turn=_turn(scope="different-creator-scope"),
            db_path=db_path,
        )
    with pytest.raises(PermissionError, match="creator Workshop"):
        commitment_executor.execute_approved_commitment(
            text_only["id"],
            toolkit=toolkit,
            turn=_turn(principal="guest", scope=SCOPE),
            db_path=db_path,
        )

    assert toolkit.calls == []
    assert commitments.get_commitment(
        text_only["id"], scope=SCOPE, db_path=db_path,
    )["state"] == commitments.APPROVED


def test_tool_error_closes_failed_instead_of_claiming_success(tmp_path):
    db_path = tmp_path / "failed.db"
    approved = _approved(db_path)
    toolkit = FakeToolkit("error: scoped status unavailable")

    result = commitment_executor.execute_approved_commitment(
        approved["id"], toolkit=toolkit, turn=_turn(), db_path=db_path,
    )

    assert result["ok"] is False
    assert result["execution"]["status"] == "failed"
    assert result["commitment"]["state"] == commitments.FAILED
    assert result["commitment"]["receipt"]["status"] == "failed"
    assert result["commitment"]["receipt"]["error"].startswith("error:")


def test_startup_recovery_cancels_running_without_rerunning(tmp_path):
    db_path = tmp_path / "recovery.db"
    approved = _approved(db_path)
    running = commitments.transition_commitment(
        approved["id"],
        commitments.RUNNING,
        scope=SCOPE,
        evidence={"source": "interrupted-test"},
        db_path=db_path,
    )
    assert running["state"] == commitments.RUNNING

    recovered = commitments.recover_running_commitments(
        scope=SCOPE,
        db_path=db_path,
    )
    repeated = commitments.recover_running_commitments(
        scope=SCOPE,
        db_path=db_path,
    )

    assert len(recovered) == 1
    assert recovered[0]["state"] == commitments.CANCELLED
    assert recovered[0]["receipt"] == {
        "status": commitments.CANCELLED,
        "error": "server restarted before execution receipt was written",
        "recovered": True,
    }
    assert recovered[0]["receipts"][-1]["from_state"] == commitments.RUNNING
    assert recovered[0]["receipts"][-1]["to_state"] == commitments.CANCELLED
    assert repeated == []


def test_creator_commitment_routes_complete_the_read_only_flow(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import server

    db_path = tmp_path / "route.db"
    real_create = commitments.create_commitment
    real_get = commitments.get_commitment
    real_list = commitments.list_commitments
    real_transition = commitments.transition_commitment
    monkeypatch.setattr(
        server.commitments_mod,
        "create_commitment",
        lambda action, **kwargs: real_create(
            action, **{**kwargs, "db_path": db_path}
        ),
    )
    monkeypatch.setattr(
        server.commitments_mod,
        "get_commitment",
        lambda commitment_id, **kwargs: real_get(
            commitment_id, **{**kwargs, "db_path": db_path}
        ),
    )
    monkeypatch.setattr(
        server.commitments_mod,
        "list_commitments",
        lambda **kwargs: real_list(**{**kwargs, "db_path": db_path}),
    )
    monkeypatch.setattr(
        server.commitments_mod,
        "transition_commitment",
        lambda commitment_id, to_state, **kwargs: real_transition(
            commitment_id, to_state, **{**kwargs, "db_path": db_path}
        ),
    )
    client = TestClient(server.app)
    auth_headers = {server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET}
    monkeypatch.setattr(
        server.cognition_mod, "record_observation", lambda *_args, **_kwargs: 1,
    )
    created_response = client.post(
        "/commitments",
        json={"tool": "self_status", "args": {}},
        headers=auth_headers,
    )
    assert created_response.status_code == 200
    created = created_response.json()["commitment"]
    created_id = int(created["id"])
    assert created["state"] == commitments.PROPOSED
    assert created["payload"]["tool"] == "self_status"

    approved_response = client.post(
        f"/commitments/{created_id}/approve", headers=auth_headers,
    )
    assert approved_response.status_code == 200
    assert approved_response.json()["commitment"]["state"] == commitments.APPROVED

    executed_response = client.post(
        f"/commitments/{created_id}/execute", headers=auth_headers,
    )
    assert executed_response.status_code == 200
    executed = executed_response.json()
    assert executed["execution"]["tool"] == "self_status"
    assert executed["execution"]["status"] == "succeeded"
    assert executed["commitment"]["receipt"]["status"] == "succeeded"

    replay = client.post(
        f"/commitments/{created_id}/execute", headers=auth_headers,
    )
    assert replay.status_code == 403
