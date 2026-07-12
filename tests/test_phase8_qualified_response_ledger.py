from __future__ import annotations

import inspect
import sqlite3

import pytest

from alpecca import qualified_response_ledger as ledger_mod


class _Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _ledger(tmp_path, clock: _Clock | None = None):
    return ledger_mod.QualifiedResponseLedger(
        tmp_path / "qualified-response.db",
        clock=_Clock() if clock is None else clock,
    )


def _dispatch(ledger, delivery_id: str = "delivery-1", **kwargs):
    values = {
        "delivery_id": delivery_id,
        "scope_key": "creator:house-hq",
        "surface": "house-hq",
        "proactive_turn_id": "proactive-turn-1",
        "response_window_seconds": 30.0,
        "dispatched_at": 100.0,
    }
    values.update(kwargs)
    return ledger.begin_dispatch(**values)


def test_dispatch_is_idempotent_and_only_confirmed_delivery_enters_pending(tmp_path):
    ledger = _ledger(tmp_path)
    dispatch = _dispatch(ledger)

    assert dispatch["state"] == ledger_mod.DISPATCHING
    assert ledger.summary()["pending"] == 0
    assert ledger.begin_dispatch(
        delivery_id="delivery-1",
        scope_key="creator:house-hq",
        surface="house-hq",
        proactive_turn_id="proactive-turn-1",
        response_window_seconds=30.0,
        dispatched_at=100.0,
    ) == dispatch
    with pytest.raises(ledger_mod.OutcomeConflict):
        _dispatch(ledger, surface="websocket")

    confirmed = ledger.confirm_delivery("delivery-1", delivered_at=101.0)
    assert confirmed["state"] == ledger_mod.PENDING
    assert confirmed["deadline_at"] == 131.0
    summary = ledger.summary()
    assert summary["pending"] == 1
    assert summary["completed"] == 0
    assert summary["rate"] is None


def test_response_during_dispatch_is_counted_only_after_confirmed_delivery(tmp_path):
    ledger = _ledger(tmp_path)
    _dispatch(ledger)

    provisional = ledger.record_creator_response(
        scope_key="creator:house-hq",
        surface="house-hq",
        response_turn_id="creator-turn-1",
        received_at=102.0,
    )
    assert provisional is not None
    assert provisional["state"] == ledger_mod.DISPATCHING
    assert ledger.summary()["completed"] == 0

    confirmed = ledger.confirm_delivery("delivery-1", delivered_at=103.0)
    assert confirmed["state"] == ledger_mod.RESPONDED
    assert confirmed["response_turn_id"] == "creator-turn-1"
    summary = ledger.summary()
    assert summary["qualified_responses"] == 1
    assert summary["completed"] == 1
    assert summary["rate"] == 1.0


def test_response_matches_one_same_scope_surface_exposure_and_is_idempotent(tmp_path):
    ledger = _ledger(tmp_path)
    _dispatch(ledger, "delivery-1")
    ledger.confirm_delivery("delivery-1", delivered_at=101.0)
    _dispatch(
        ledger,
        "delivery-2",
        proactive_turn_id="proactive-turn-2",
        dispatched_at=102.0,
    )
    ledger.confirm_delivery("delivery-2", delivered_at=103.0)

    assert ledger.record_creator_response(
        scope_key="creator:other",
        surface="house-hq",
        response_turn_id="wrong-scope",
        received_at=104.0,
    ) is None
    first = ledger.record_creator_response(
        scope_key="creator:house-hq",
        surface="house-hq",
        response_turn_id="creator-turn-1",
        received_at=104.0,
    )
    assert first is not None
    assert first["delivery_id"] == "delivery-1"
    assert ledger.record_creator_response(
        scope_key="creator:house-hq",
        surface="house-hq",
        response_turn_id="creator-turn-1",
        received_at=104.0,
    ) is None
    second = ledger.record_creator_response(
        scope_key="creator:house-hq",
        surface="house-hq",
        response_turn_id="creator-turn-2",
        received_at=105.0,
    )
    assert second is not None
    assert second["delivery_id"] == "delivery-2"
    assert ledger.summary()["qualified_responses"] == 2


def test_expiry_counts_only_confirmed_pending_rows_and_keeps_baseline_trial_split(tmp_path):
    clock = _Clock()
    ledger = _ledger(tmp_path, clock)
    _dispatch(ledger, "baseline")
    ledger.confirm_delivery("baseline", delivered_at=101.0)
    _dispatch(
        ledger,
        "trial",
        proactive_turn_id="proactive-turn-2",
        trial_id=7,
        dispatched_at=102.0,
    )
    ledger.confirm_delivery("trial", delivered_at=103.0)
    _dispatch(ledger, "failed", proactive_turn_id="proactive-turn-3", dispatched_at=104.0)

    expired = ledger.expire_due(now=140.0)
    by_id = {item["delivery_id"]: item["state"] for item in expired}
    assert by_id == {
        "baseline": ledger_mod.UNANSWERED,
        "trial": ledger_mod.UNANSWERED,
        "failed": ledger_mod.CANCELLED,
    }
    summary = ledger.summary()
    assert summary["unanswered"] == 2
    assert summary["cancelled"] == 1
    assert summary["completed"] == 2
    assert summary["rate"] == 0.0
    assert summary["baseline"]["unanswered"] == 1
    assert summary["trial"]["unanswered"] == 1


def test_cancelled_dispatch_and_late_response_never_inflate_metric(tmp_path):
    ledger = _ledger(tmp_path)
    _dispatch(ledger, "cancelled")
    cancelled = ledger.cancel_dispatch("cancelled", cancelled_at=101.0)
    assert cancelled["state"] == ledger_mod.CANCELLED
    assert ledger.record_creator_response(
        scope_key="creator:house-hq",
        surface="house-hq",
        response_turn_id="late-after-cancel",
        received_at=102.0,
    ) is None

    _dispatch(ledger, "late", proactive_turn_id="proactive-turn-2")
    ledger.confirm_delivery("late", delivered_at=101.0)
    assert ledger.record_creator_response(
        scope_key="creator:house-hq",
        surface="house-hq",
        response_turn_id="late-turn",
        received_at=132.0,
    ) is None
    ledger.expire_due(now=132.0)
    assert ledger.summary()["qualified_responses"] == 0
    assert ledger.summary()["unanswered"] == 1


def test_schema_and_public_contract_do_not_accept_or_store_content(tmp_path):
    ledger = _ledger(tmp_path)
    signature = inspect.signature(ledger.begin_dispatch)
    assert "text" not in signature.parameters
    assert "content" not in signature.parameters
    assert "score" not in signature.parameters
    assert "request_id" not in signature.parameters
    assert "text" not in inspect.signature(ledger.record_creator_response).parameters

    with sqlite3.connect(ledger.db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(qualified_response_outcomes)")
        }
    forbidden = {"text", "content", "message", "authorization", "credential", "request_id"}
    assert not (columns & forbidden)
