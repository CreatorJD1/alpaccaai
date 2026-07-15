"""Focused tests for the inert Phase 7 pagefile approval ledger."""
from __future__ import annotations

import ast
import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from alpecca import pagefile_approval, system_pressure


GiB = 1024**3
_FORBIDDEN_OUTPUT_KEYS = {
    "command",
    "content",
    "elevation",
    "host_snapshot",
    "path",
    "plan",
    "script",
}


class _Clock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _proposed_plan(current_maximum_mib: int = 38_000) -> dict:
    result = system_pressure.propose_pagefile_plan(
        {
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
        },
        {"state": "known", "maximum_mib": current_maximum_mib},
    )
    assert result["state"] == "proposed"
    assert result["plan"] is not None
    return result["plan"]


def _error_code(exc: pytest.ExceptionInfo[pagefile_approval.PagefileApprovalError]) -> str:
    return exc.value.code


def test_exact_system_pressure_plan_is_digest_bound_and_tokens_are_not_persisted(tmp_path):
    db_path = tmp_path / "pagefile-approval.sqlite3"
    ledger = pagefile_approval.PagefileApprovalLedger(db_path)
    plan = _proposed_plan()
    original = deepcopy(plan)

    request = ledger.create_request(plan)
    assert set(request) == {
        "schema",
        "request_id",
        "request_token",
        "plan_digest",
        "state",
        "expires_at",
        "approved",
    }
    assert request["state"] == "pending"
    assert request["approved"] is False
    assert not set(request).intersection(_FORBIDDEN_OUTPUT_KEYS)

    approval = ledger.approve_request(
        request["request_token"],
        plan,
        principal="CreatorJD",
        approved=True,
    )
    assert approval["state"] == "approved"
    assert approval["approved"] is True
    assert approval["plan_digest"] == request["plan_digest"]
    assert not set(approval).intersection(_FORBIDDEN_OUTPUT_KEYS)
    assert plan == original

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(phase7_pagefile_approvals)"
            ).fetchall()
        }
        row = conn.execute(
            "SELECT * FROM phase7_pagefile_approvals"
        ).fetchone()
    assert "request_token" not in columns
    assert "approval_token" not in columns
    assert "request_token_digest" in columns
    assert "approval_token_digest" in columns
    assert request["request_token"] not in tuple(row)
    assert approval["approval_token"] not in tuple(row)
    assert row["plan_digest"] == request["plan_digest"]
    assert len(row["request_token_digest"]) == 64
    assert len(row["approval_token_digest"]) == 64


@pytest.mark.parametrize(
    "case",
    (
        "extra_key",
        "wrong_schema",
        "wrong_operation",
        "not_proposal_only",
        "requirements_list",
        "wrong_step",
        "wrong_target",
        "boolean_current",
        "over_cap",
    ),
)
def test_only_the_exact_bounded_system_pressure_plan_is_accepted(tmp_path, case: str):
    plan = _proposed_plan()
    if case == "extra_key":
        plan["token"] = "not-allowed"
    elif case == "wrong_schema":
        plan["schema"] = "alpecca.phase7.pagefile-proposal.v2"
    elif case == "wrong_operation":
        plan["operation"] = "pagefile_write"
    elif case == "not_proposal_only":
        plan["execution_state"] = "approved"
    elif case == "requirements_list":
        plan["future_requirements"] = list(plan["future_requirements"])
    elif case == "wrong_step":
        plan["increase_mib"] = 1
    elif case == "wrong_target":
        plan["proposed_maximum_mib"] += 1
    elif case == "boolean_current":
        plan["current_maximum_mib"] = True
    elif case == "over_cap":
        plan["current_maximum_mib"] = 55_296
        plan["proposed_maximum_mib"] = 59_392

    ledger = pagefile_approval.PagefileApprovalLedger(
        tmp_path / f"{case}.sqlite3"
    )
    with pytest.raises(pagefile_approval.PagefileApprovalError):
        ledger.create_request(plan)


def test_planner_policy_drift_fails_closed(tmp_path, monkeypatch):
    ledger = pagefile_approval.PagefileApprovalLedger(tmp_path / "ledger.sqlite3")
    plan = _proposed_plan()
    monkeypatch.setattr(system_pressure, "PAGEFILE_STEP_MIB", 1)

    with pytest.raises(pagefile_approval.PagefileApprovalError) as exc:
        ledger.create_request(plan)

    assert _error_code(exc) == "planner_contract_mismatch"


@pytest.mark.parametrize("approved", (False, 1, "true", None))
def test_approval_requires_literal_true_and_exact_creatorjd_principal(
    tmp_path,
    approved: object,
):
    ledger = pagefile_approval.PagefileApprovalLedger(tmp_path / "ledger.sqlite3")
    plan = _proposed_plan()
    request = ledger.create_request(plan)

    with pytest.raises(pagefile_approval.PagefileApprovalError) as exc:
        ledger.approve_request(
            request["request_token"],
            plan,
            principal="CreatorJD",
            approved=approved,
        )
    assert _error_code(exc) == "explicit_approval_required"

    with pytest.raises(pagefile_approval.PagefileApprovalError) as exc:
        ledger.approve_request(
            request["request_token"],
            plan,
            principal="creatorjd",
            approved=True,
        )
    assert _error_code(exc) == "creatorjd_principal_required"

    result = ledger.approve_request(
        request["request_token"],
        plan,
        principal="CreatorJD",
        approved=True,
    )
    assert result["principal"] == "CreatorJD"
    assert result["approved"] is True


def test_request_and_approval_are_bound_to_the_same_exact_plan(tmp_path):
    ledger = pagefile_approval.PagefileApprovalLedger(tmp_path / "ledger.sqlite3")
    plan = _proposed_plan(38_000)
    other_plan = _proposed_plan(42_096)
    request = ledger.create_request(plan)

    with pytest.raises(pagefile_approval.PagefileApprovalError) as exc:
        ledger.approve_request(
            request["request_token"],
            other_plan,
            principal="CreatorJD",
            approved=True,
        )
    assert _error_code(exc) == "plan_mismatch"

    approval = ledger.approve_request(
        request["request_token"],
        plan,
        principal="CreatorJD",
        approved=True,
    )
    with pytest.raises(pagefile_approval.PagefileApprovalError) as exc:
        ledger.consume_approval(
            approval["approval_token"],
            plan,
            principal="creatorjd",
        )
    assert _error_code(exc) == "creatorjd_principal_required"

    with pytest.raises(pagefile_approval.PagefileApprovalError) as exc:
        ledger.consume_approval(
            approval["approval_token"],
            other_plan,
            principal="CreatorJD",
        )
    assert _error_code(exc) == "plan_mismatch"

    consumed = ledger.consume_approval(
        approval["approval_token"],
        plan,
        principal="CreatorJD",
    )
    assert consumed["state"] == "consumed"
    assert consumed["plan_digest"] == request["plan_digest"]
    assert not set(consumed).intersection(_FORBIDDEN_OUTPUT_KEYS)


def test_request_and_approval_expire_at_the_exact_boundary(tmp_path):
    clock = _Clock()
    ledger = pagefile_approval.PagefileApprovalLedger(
        tmp_path / "ledger.sqlite3",
        now=clock,
    )
    plan = _proposed_plan()
    request = ledger.create_request(plan)
    clock.advance(pagefile_approval.REQUEST_TTL_SECONDS)

    with pytest.raises(pagefile_approval.PagefileApprovalError) as exc:
        ledger.approve_request(
            request["request_token"],
            plan,
            principal="CreatorJD",
            approved=True,
        )
    assert _error_code(exc) == "request_expired"

    renewed = ledger.create_request(plan)
    approval = ledger.approve_request(
        renewed["request_token"],
        plan,
        principal="CreatorJD",
        approved=True,
    )
    clock.advance(pagefile_approval.APPROVAL_TTL_SECONDS)
    with pytest.raises(pagefile_approval.PagefileApprovalError) as exc:
        ledger.consume_approval(
            approval["approval_token"],
            plan,
            principal="CreatorJD",
        )
    assert _error_code(exc) == "approval_expired"


def test_request_and_approval_replay_are_rejected_across_restart(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    plan = _proposed_plan()
    first = pagefile_approval.PagefileApprovalLedger(db_path)
    request = first.create_request(plan)
    approval = first.approve_request(
        request["request_token"],
        plan,
        principal="CreatorJD",
        approved=True,
    )

    with pytest.raises(pagefile_approval.PagefileApprovalError) as exc:
        first.approve_request(
            request["request_token"],
            plan,
            principal="CreatorJD",
            approved=True,
        )
    assert _error_code(exc) == "request_replayed"

    restarted = pagefile_approval.PagefileApprovalLedger(db_path)
    restarted.consume_approval(
        approval["approval_token"],
        plan,
        principal="CreatorJD",
    )
    after_consume_restart = pagefile_approval.PagefileApprovalLedger(db_path)
    with pytest.raises(pagefile_approval.PagefileApprovalError) as exc:
        after_consume_restart.consume_approval(
            approval["approval_token"],
            plan,
            principal="CreatorJD",
        )
    assert _error_code(exc) == "approval_replayed"

    with pytest.raises(pagefile_approval.PagefileApprovalError) as exc:
        after_consume_restart.create_request(plan)
    assert _error_code(exc) == "plan_already_consumed"


def test_concurrent_consumers_obtain_exactly_one_success(tmp_path):
    db_path = tmp_path / "ledger.sqlite3"
    plan = _proposed_plan()
    ledger = pagefile_approval.PagefileApprovalLedger(db_path)
    request = ledger.create_request(plan)
    approval = ledger.approve_request(
        request["request_token"],
        plan,
        principal="CreatorJD",
        approved=True,
    )
    ledgers = [pagefile_approval.PagefileApprovalLedger(db_path) for _ in range(8)]

    def consume(index: int) -> str:
        try:
            ledgers[index].consume_approval(
                approval["approval_token"],
                plan,
                principal="CreatorJD",
            )
            return "consumed"
        except pagefile_approval.PagefileApprovalError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(consume, range(8)))

    assert outcomes.count("consumed") == 1
    assert outcomes.count("approval_replayed") == 7


def test_module_has_no_host_action_or_route_capability():
    source = inspect.getsource(pagefile_approval)
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint(
        {"ctypes", "fastapi", "flask", "os", "server", "subprocess"}
    )
    assert function_names.isdisjoint(
        {
            "apply_pagefile_request",
            "elevate_pagefile_request",
            "execute_pagefile_request",
            "mutate_pagefile",
            "set_pagefile_maximum",
        }
    )
    assert "Set-CimInstance" not in source
    assert "Win32_PageFileSetting" not in source
