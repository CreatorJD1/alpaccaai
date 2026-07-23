"""Focused tests for pure Phase 4 completion-language enforcement."""
from __future__ import annotations

import pytest

from alpecca.commitment_language import (
    CommitmentReceiptState,
    classify_action_claims,
    coerce_commitment_receipt_state,
    enforce_commitment_language,
)


def test_classifies_future_actions_and_completion_claims_by_sentence():
    analysis = classify_action_claims(
        "I'll prepare the report. I completed the export. What should we review next?"
    )

    assert [claim.kind for claim in analysis.claims] == ["future-action", "completion"]
    assert analysis.claims[0].text == "I'll prepare the report."
    assert analysis.claims[1].text == "I completed the export."
    assert analysis.truncated is False


def test_conversational_did_is_not_misclassified_as_action_completion():
    conversational = classify_action_claims(
        "I did hear you, and I did understand the question."
    )
    completed_action = classify_action_claims("I did send the file.")

    assert conversational.claims == ()
    assert [claim.kind for claim in completed_action.claims] == ["completion"]


@pytest.mark.parametrize(
    "reply",
    [
        "I finished listening, and I understand what you mean.",
        "I opened up because I trust you.",
        "I stopped worrying once you explained it.",
        "I started thinking about your question.",
        "I changed my mind after hearing you.",
        "I ran out of patience for a moment.",
        "I updated my understanding of what you meant.",
        "I committed to listening more carefully.",
    ],
)
def test_conversational_state_changes_are_not_action_completions(reply):
    assert classify_action_claims(reply).claims == ()


@pytest.mark.parametrize(
    "reply",
    [
        "I'll stay with you.",
        "I will answer you directly.",
        "I'm going to listen carefully.",
        "I'll remember that for you.",
        "I'll commit to listening more carefully.",
        "I will keep that grounded as something you told me.",
    ],
)
def test_conversational_future_language_is_not_an_external_action(reply):
    analysis = classify_action_claims(reply)
    from alpecca.mind import CoreMind

    guarded = CoreMind._phase4_enforce_commitment_language(
        reply,
        CommitmentReceiptState(status="unavailable"),
    )

    assert analysis.claims == ()
    assert guarded.rewritten is False
    assert guarded.reply == reply


@pytest.mark.parametrize(
    "reply",
    [
        "I'll prepare the report.",
        "I'll do it now.",
        "I will restart the server.",
        "I'm going to upload the file.",
    ],
)
def test_explicit_future_external_actions_remain_classified(reply):
    assert [
        claim.kind for claim in classify_action_claims(reply).claims
    ] == ["future-action"]


@pytest.mark.parametrize(
    "reply",
    [
        "I uploaded the file.",
        "I downloaded the archive.",
        "I finished the export.",
        "I opened the document.",
        "I did close the app.",
    ],
)
def test_explicit_external_action_completions_are_classified(reply):
    analysis = classify_action_claims(reply)

    assert [claim.kind for claim in analysis.claims] == ["completion"]


@pytest.mark.parametrize(
    "reply",
    [
        "I finished listening, and I understand what you mean.",
        "I opened up because I trust you.",
    ],
)
def test_coremind_phase4_preserves_conversational_self_reports(reply):
    from alpecca.mind import CoreMind

    result = CoreMind._phase4_enforce_commitment_language(
        reply,
        CommitmentReceiptState(status="unavailable"),
    )

    assert result.rewritten is False
    assert result.claims == ()
    assert result.reply == reply


@pytest.mark.parametrize(
    "reply",
    [
        "I uploaded the file.",
        "I downloaded the archive.",
        "I finished the export.",
        "I opened the document.",
    ],
)
def test_coremind_phase4_guards_external_completions_without_receipts(reply):
    from alpecca.mind import CoreMind

    result = CoreMind._phase4_enforce_commitment_language(
        reply,
        CommitmentReceiptState(status="unavailable", action="the external action"),
    )

    assert result.rewritten is True
    assert [claim.kind for claim in result.claims] == ["completion"]
    assert result.reply == (
        "I cannot confirm success because a successful receipt for "
        "the external action is unavailable."
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("proposed", "I have proposed report upload, but it has not been approved or run."),
        ("approved", "Report upload is approved, but no successful receipt confirms completion."),
        ("approval-pending", "Report upload is pending approval, so I cannot confirm it is complete."),
        ("running", "Report upload is running, so I cannot confirm it is complete yet."),
        ("failed", "Report upload failed, so I cannot confirm it is complete."),
        ("cancelled", "Report upload was cancelled, so I cannot confirm it is complete."),
        ("unavailable", "Report upload is unavailable, so I cannot confirm it is complete."),
    ],
)
def test_rewrites_unsupported_completion_for_each_non_success_state(status, expected):
    result = enforce_commitment_language(
        "I completed the report upload.",
        CommitmentReceiptState(status=status, action="report upload"),
    )

    assert result.rewritten is True
    assert result.reply == expected
    assert result.claims[0].kind == "completion"


def test_succeeded_requires_a_successful_receipt_before_completion_is_kept():
    without_receipt = enforce_commitment_language(
        "Done. I sent the report.",
        {"status": "succeeded", "action": "report upload"},
    )
    with_receipt = enforce_commitment_language(
        "Done. I sent the report.",
        {
            "status": "succeeded",
            "action": "report upload",
            "receipt": {"status": "succeeded", "id": "receipt-42"},
        },
    )

    assert without_receipt.rewritten is True
    assert "no successful receipt is available" in without_receipt.reply
    assert with_receipt.rewritten is False
    assert with_receipt.reply == "Done. I sent the report."


def test_proposed_future_action_is_rewritten_as_pending_not_immediate():
    result = enforce_commitment_language(
        "I'll do it now.",
        {"status": "proposed", "action": "terminal update"},
    )

    assert result.reply == (
        "I have proposed terminal update, but it has not been approved or run."
    )
    assert result.rewritten is True
    assert result.claims[0].kind == "future-action"
    assert "I'll" not in result.reply


def test_terminal_states_rewrite_future_promises_but_approved_and_running_remain():
    failed = enforce_commitment_language(
        "I'll deploy the update.",
        {"status": "failed", "action": "update deployment"},
    )
    proposed = enforce_commitment_language(
        "I'll deploy the update.",
        {"status": "proposed", "action": "update deployment"},
    )
    approved = enforce_commitment_language(
        "I'll deploy the update.",
        {"status": "approved", "action": "update deployment"},
    )
    running = enforce_commitment_language(
        "I'll deploy the update.",
        {"status": "running", "action": "update deployment"},
    )

    assert failed.reply == "Update deployment failed, so I cannot confirm it is complete."
    assert failed.rewritten is True
    assert proposed.reply == (
        "I have proposed update deployment, but it has not been approved or run."
    )
    assert proposed.rewritten is True
    assert approved.reply == "I'll deploy the update."
    assert approved.rewritten is False
    assert running.reply == "I'll deploy the update."
    assert running.rewritten is False


def test_state_normalization_and_reply_bounds_are_deterministic():
    state = coerce_commitment_receipt_state({
        "status": "approval_pending",
        "action": "  upload   diagnostics  ",
        "receipt": {"status": "ignored", "id": "  receipt  "},
    })
    analysis = classify_action_claims("I completed it. " + "x" * 100, max_chars=24)

    assert state.status == "approval-pending"
    assert state.receipt_status == "unavailable"
    assert state.action == "upload diagnostics"
    assert analysis.truncated is True
    assert len(analysis.text) == 24
    with pytest.raises(TypeError):
        classify_action_claims(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        classify_action_claims("reply", max_chars=0)
