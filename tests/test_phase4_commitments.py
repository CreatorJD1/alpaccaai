"""Focused Phase 4 commitment and receipt-ledger coverage."""
from __future__ import annotations

import sqlite3

import pytest

from alpecca import commitments
from alpecca.db import connect


SCOPE = "creator-private"


def _proposed(db_path):
    return commitments.create_commitment(
        "Inspect the requested source files",
        scope=SCOPE,
        evidence={"turn_id": "turn-1", "cue": "action_intent"},
        db_path=db_path,
    )


def _running(db_path):
    item = _proposed(db_path)
    commitments.transition_commitment(
        item["id"],
        commitments.APPROVED,
        scope=SCOPE,
        evidence={"approved_by": "creator"},
        db_path=db_path,
    )
    return commitments.transition_commitment(
        item["id"],
        commitments.RUNNING,
        scope=SCOPE,
        evidence={"worker": "local"},
        db_path=db_path,
    )


def test_create_and_retrieve_are_scoped_and_idempotent(tmp_path):
    db_path = tmp_path / "commitments.db"
    created = _proposed(db_path)

    first = commitments.get_commitment(created["id"], scope=SCOPE, db_path=db_path)
    second = commitments.get_commitment(created["id"], scope=SCOPE, db_path=db_path)

    assert first == second == created
    assert first is not second
    assert first["state"] == commitments.PROPOSED
    assert first["evidence"] == {"turn_id": "turn-1", "cue": "action_intent"}
    assert first["receipt"] is None
    assert [event["to_state"] for event in first["receipts"]] == ["proposed"]
    assert commitments.get_commitment(
        created["id"], scope="guest-private", db_path=db_path
    ) is None

    first["evidence"]["turn_id"] = "mutated-return-value"
    first["receipts"].clear()
    unchanged = commitments.get_commitment(created["id"], scope=SCOPE, db_path=db_path)
    assert unchanged == second


def test_complete_success_chain_persists_receipts(tmp_path):
    db_path = tmp_path / "commitments.db"
    running = _running(db_path)
    succeeded = commitments.transition_commitment(
        running["id"],
        commitments.SUCCEEDED,
        scope=SCOPE,
        evidence={"output_sha256": "abc123"},
        receipt={"tool": "source_reader", "result": "3 files inspected"},
        db_path=db_path,
    )

    assert succeeded["state"] == commitments.SUCCEEDED
    assert succeeded["receipt"] == {
        "tool": "source_reader",
        "result": "3 files inspected",
    }
    assert [event["to_state"] for event in succeeded["receipts"]] == [
        commitments.PROPOSED,
        commitments.APPROVED,
        commitments.RUNNING,
        commitments.SUCCEEDED,
    ]
    assert succeeded["receipts"][-1]["from_state"] == commitments.RUNNING
    assert succeeded["receipts"][-1]["evidence"] == {
        "output_sha256": "abc123"
    }
    assert commitments.get_commitment(
        running["id"], scope=SCOPE, db_path=db_path
    ) == succeeded


@pytest.mark.parametrize("terminal", [commitments.FAILED, commitments.CANCELLED])
def test_running_can_close_with_each_non_success_terminal(tmp_path, terminal):
    db_path = tmp_path / f"{terminal}.db"
    running = _running(db_path)

    closed = commitments.transition_commitment(
        running["id"],
        terminal,
        scope=SCOPE,
        receipt={"reason": f"action {terminal}"},
        db_path=db_path,
    )

    assert closed["state"] == terminal
    assert closed["receipt"] == {"reason": f"action {terminal}"}


def test_illegal_or_duplicate_transitions_leave_ledger_unchanged(tmp_path):
    db_path = tmp_path / "commitments.db"
    item = _proposed(db_path)

    for illegal in (
        commitments.PROPOSED,
        commitments.RUNNING,
        commitments.SUCCEEDED,
        commitments.FAILED,
        commitments.CANCELLED,
    ):
        with pytest.raises(commitments.IllegalTransition):
            commitments.transition_commitment(
                item["id"],
                illegal,
                scope=SCOPE,
                receipt={"reason": "must not be stored"}
                if illegal in commitments.TERMINAL_STATES
                else None,
                db_path=db_path,
            )

    unchanged = commitments.get_commitment(item["id"], scope=SCOPE, db_path=db_path)
    assert unchanged["state"] == commitments.PROPOSED
    assert len(unchanged["receipts"]) == 1

    approved = commitments.transition_commitment(
        item["id"], commitments.APPROVED, scope=SCOPE, db_path=db_path
    )
    with pytest.raises(commitments.IllegalTransition):
        commitments.transition_commitment(
            item["id"], commitments.APPROVED, scope=SCOPE, db_path=db_path
        )
    assert commitments.get_commitment(
        item["id"], scope=SCOPE, db_path=db_path
    ) == approved


def test_terminal_transition_requires_nonempty_receipt(tmp_path):
    db_path = tmp_path / "commitments.db"
    running = _running(db_path)

    with pytest.raises(commitments.CommitmentError, match="receipt payload is required"):
        commitments.transition_commitment(
            running["id"], commitments.SUCCEEDED, scope=SCOPE, db_path=db_path
        )
    with pytest.raises(commitments.CommitmentError, match="cannot be empty"):
        commitments.transition_commitment(
            running["id"],
            commitments.SUCCEEDED,
            scope=SCOPE,
            receipt={},
            db_path=db_path,
        )

    unchanged = commitments.get_commitment(
        running["id"], scope=SCOPE, db_path=db_path
    )
    assert unchanged["state"] == commitments.RUNNING
    assert unchanged["receipt"] is None


def test_sqlite_trigger_rejects_direct_state_machine_bypass(tmp_path):
    db_path = tmp_path / "commitments.db"
    item = _proposed(db_path)

    with connect(db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="illegal commitment"):
            conn.execute(
                "UPDATE commitments SET state='running' WHERE id=?",
                (item["id"],),
            )

    unchanged = commitments.get_commitment(item["id"], scope=SCOPE, db_path=db_path)
    assert unchanged["state"] == commitments.PROPOSED
    assert len(unchanged["receipts"]) == 1


def test_listing_is_scope_and_state_partitioned(tmp_path):
    db_path = tmp_path / "commitments.db"
    creator = _proposed(db_path)
    guest = commitments.create_commitment(
        "Guest-scoped action",
        scope="guest-private",
        db_path=db_path,
    )
    commitments.transition_commitment(
        creator["id"], commitments.APPROVED, scope=SCOPE, db_path=db_path
    )

    creator_rows = commitments.list_commitments(scope=SCOPE, db_path=db_path)
    guest_rows = commitments.list_commitments(scope="guest-private", db_path=db_path)
    proposed_creator = commitments.list_commitments(
        scope=SCOPE, state=commitments.PROPOSED, db_path=db_path
    )

    assert [row["id"] for row in creator_rows] == [creator["id"]]
    assert [row["id"] for row in guest_rows] == [guest["id"]]
    assert proposed_creator == []


def test_invalid_payload_and_wrong_scope_cannot_mutate(tmp_path):
    db_path = tmp_path / "commitments.db"
    item = _proposed(db_path)

    with pytest.raises(commitments.CommitmentError, match="JSON serializable"):
        commitments.transition_commitment(
            item["id"],
            commitments.APPROVED,
            scope=SCOPE,
            evidence={"bad": object()},
            db_path=db_path,
        )
    with pytest.raises(commitments.CommitmentNotFound):
        commitments.transition_commitment(
            item["id"],
            commitments.APPROVED,
            scope="guest-private",
            db_path=db_path,
        )

    unchanged = commitments.get_commitment(item["id"], scope=SCOPE, db_path=db_path)
    assert unchanged["state"] == commitments.PROPOSED
    assert len(unchanged["receipts"]) == 1
