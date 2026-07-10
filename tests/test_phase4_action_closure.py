"""Focused pure Phase 4 action-closure adapter coverage."""
from __future__ import annotations

import pytest

from alpecca.action_closure import (
    action_closure_status,
    derive_receipt_evidence,
    resolve_confirmation,
)
from alpecca.cues import parse_cues


CREATOR_SCOPE = "creator-private"
GUEST_SCOPE = "guest-private"


def _commitment(
    commitment_id: int,
    *,
    scope: str = CREATOR_SCOPE,
    state: str = "proposed",
    action: str = "upload report",
    receipt: dict | None = None,
):
    receipts = []
    if receipt is not None:
        receipts.append({
            "id": commitment_id * 10,
            "to_state": state,
            "receipt": receipt,
            "evidence": {"turn_id": f"turn-{commitment_id}"},
        })
    return {
        "id": commitment_id,
        "scope": scope,
        "state": state,
        "action": action,
        "receipt": receipt,
        "receipts": receipts,
    }


def test_confirmation_resolves_exactly_one_proposed_commitment_in_scope():
    resolution = resolve_confirmation(
        parse_cues("Yes, do it."),
        [
            _commitment(1),
            _commitment(2, scope=GUEST_SCOPE),
            _commitment(3, state="running"),
        ],
        scope=CREATOR_SCOPE,
    )

    assert resolution.outcome == "resolved"
    assert resolution.commitment_id == 1
    assert resolution.action == "upload report"
    assert resolution.candidate_ids == (1,)


def test_confirmation_refuses_ambiguous_and_cross_scope_candidates():
    cues = parse_cues("Yes, proceed.")
    ambiguous = resolve_confirmation(
        cues, [_commitment(1), _commitment(2, action="send notice")], scope=CREATOR_SCOPE
    )
    guest_only = resolve_confirmation(cues, [_commitment(3, scope=GUEST_SCOPE)], scope=CREATOR_SCOPE)

    assert ambiguous.outcome == "ambiguous"
    assert ambiguous.commitment_id is None
    assert ambiguous.candidate_ids == (1, 2)
    assert guest_only.outcome == "no-pending"
    assert guest_only.candidate_ids == ()


def test_non_confirmation_never_selects_a_pending_commitment():
    resolution = resolve_confirmation(
        parse_cues("What is the status of the upload?"), [_commitment(1)], scope=CREATOR_SCOPE
    )

    assert resolution.outcome == "not-confirmation"
    assert resolution.commitment_id is None


@pytest.mark.parametrize(
    ("state", "receipt", "expected"),
    [
        ("proposed", None, "I have proposed upload report, but it has not been approved or run."),
        ("running", None, "Upload report is running, so I cannot confirm it is complete yet."),
        ("succeeded", {"tool": "uploader", "result": "ok"}, "I completed upload report."),
        ("failed", {"reason": "network"}, "Upload report failed, so I cannot confirm it is complete."),
        ("cancelled", {"reason": "user"}, "Upload report was cancelled, so I cannot confirm it is complete."),
    ],
)
def test_action_status_wording_tracks_durable_commitment_state(state, receipt, expected):
    status = action_closure_status(_commitment(7, state=state, receipt=receipt))

    assert status.wording == expected
    assert status.state.status == ("approval-pending" if state == "approved" else state)
    if state == "succeeded":
        assert status.state.has_successful_receipt is True
        assert status.receipt_evidence["receipt_id"] == 70
        assert status.receipt_evidence["transition_evidence"] == {"turn_id": "turn-7"}
    else:
        assert status.state.has_successful_receipt is False


def test_receipt_metadata_is_bounded_and_serializable_scalars_only():
    commitment = _commitment(
        4,
        state="succeeded",
        receipt={"result": "x" * 500, "nested": {"not": "included"}, "count": 2},
    )

    metadata = derive_receipt_evidence(commitment)

    assert metadata["receipt"] == {"result": "x" * 240, "count": 2}
    assert metadata["receipt_present"] is True
    assert metadata["commitment_state"] == "succeeded"
