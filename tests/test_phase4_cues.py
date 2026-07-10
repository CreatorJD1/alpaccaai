from __future__ import annotations

import json

import pytest

from alpecca.cues import (
    MAX_EVIDENCE_CHARS,
    MAX_EVIDENCE_PER_CUE,
    MAX_MESSAGE_CHARS,
    CueEnvelope,
    parse_cue_envelope,
    parse_cues,
)


def test_correction_has_grounded_evidence_without_false_confirmation():
    cues = parse_cues("No, I meant the blue file, not the green one.")

    assert cues.correction.detected is True
    assert cues.correction.confidence >= 0.9
    assert cues.correction.evidence
    assert cues.confirmation.detected is False


def test_confirmation_and_action_can_overlap():
    cues = parse_cue_envelope("Yes, exactly. Go ahead.")

    assert cues.confirmation.detected is True
    assert cues.action_intent.detected is True
    assert cues.active_kinds == ("confirmation", "action_intent")


def test_reference_prefers_explicit_context_language():
    cues = parse_cues("Use the previous plan and update it.")

    assert cues.reference.detected is True
    assert cues.reference.confidence >= 0.9
    assert cues.action_intent.detected is True
    assert any("previous plan" in item for item in cues.reference.evidence)


def test_urgency_and_distress_are_separate_signals():
    cues = parse_cues("Please help me right now! I'm overwhelmed.")

    assert cues.urgency.detected is True
    assert cues.distress.detected is True
    assert cues.action_intent.detected is True
    assert cues.distress.confidence >= 0.9


@pytest.mark.parametrize(
    "message",
    (
        "Why did that happen?",
        "How does this work",
        "Could you review the file",
    ),
)
def test_question_recognizes_punctuation_or_interrogative_opening(message: str):
    assert parse_cues(message).question.detected is True


@pytest.mark.parametrize(
    "message",
    (
        "Please update the document.",
        "Build the local index.",
        "I need you to review this.",
        "I'll check the result.",
    ),
)
def test_action_intent_covers_requests_commands_and_stated_intent(message: str):
    assert parse_cues(message).action_intent.detected is True


def test_correct_command_is_not_confirmation():
    cues = parse_cues("Correct the parser and run the tests.")

    assert cues.action_intent.detected is True
    assert cues.confirmation.detected is False


def test_empty_message_returns_complete_negative_envelope():
    cues = parse_cues(" \n\t ")

    assert isinstance(cues, CueEnvelope)
    assert cues.text == ""
    assert cues.active_kinds == ()
    assert all(signal.detected is False for signal in cues.signals)
    assert all(signal.confidence == 0.0 for signal in cues.signals)


def test_parser_is_hard_bounded_and_evidence_is_small():
    message = "Please update this file right now! " + ("x" * (MAX_MESSAGE_CHARS + 500))
    cues = parse_cues(message, max_chars=MAX_MESSAGE_CHARS * 2)

    assert cues.truncated is True
    assert len(cues.text) <= MAX_MESSAGE_CHARS
    for signal in cues.signals:
        assert 0.0 <= signal.confidence <= 1.0
        assert len(signal.evidence) <= MAX_EVIDENCE_PER_CUE
        assert all(len(item) <= MAX_EVIDENCE_CHARS for item in signal.evidence)


def test_result_is_deterministic_and_json_serializable():
    message = "Actually, can you use the earlier document ASAP?"
    first = parse_cues(message)
    second = parse_cues(message)

    assert first == second
    encoded = json.dumps(first.as_dict(), sort_keys=True)
    assert "correction" in encoded
    assert "question" in encoded
    assert "action_intent" in encoded


@pytest.mark.parametrize("value", (None, 42, object()))
def test_non_string_message_is_rejected(value: object):
    with pytest.raises(TypeError, match="message must be a string"):
        parse_cues(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("max_chars", (0, -1, 1.5, True))
def test_invalid_bounds_are_rejected(max_chars: object):
    with pytest.raises(ValueError, match="positive integer"):
        parse_cues("hello", max_chars=max_chars)  # type: ignore[arg-type]
