import json

import pytest

from alpecca.selective_soul import (
    CLOSE_TOP_MARGIN,
    HIGH_AFFECT_SCORE,
    MAX_REASON_CHARS,
    MAX_RESPONSE_CHARS,
    ROLE_ORDER,
    VECTOR_SCHEMA,
    DeliberationReason,
    EvidenceError,
    ResolutionSource,
    ResponseError,
    decide_deliberation,
    resolve_textual_deliberation,
)


def _vector(
    scores=(0.2, 0.1, 0.3, 0.7, 0.4, 0.5, 0.35),
    *,
    active=(1, 1, 1, 1, 1, 1, 1),
    contradiction=False,
    **changes,
):
    value = {
        "schema": VECTOR_SCHEMA,
        "order": list(ROLE_ORDER),
        "scores": list(scores),
        "active": list(active),
        "contradiction": contradiction,
        "source": "deterministic",
        "model_calls": 0,
        "independent_transformers": False,
    }
    value.update(changes)
    return value


def test_clear_low_affect_winner_does_not_warrant_textual_deliberation():
    decision = decide_deliberation(_vector())

    assert not decision.warranted
    assert decision.reason is DeliberationReason.NOT_WARRANTED
    assert decision.evidence.top_role == "Doer"
    assert decision.evidence.runner_up_role == "Reflector"
    assert decision.evidence.top_margin == 0.2


def test_contradiction_has_highest_priority_and_explicit_evidence():
    decision = decide_deliberation(_vector(
        scores=(0.9, 0.1, 0.2, 0.89, 0.1, 0.69, 0.2),
        contradiction=True,
    ))

    assert decision.warranted
    assert decision.reason is DeliberationReason.CONTRADICTION
    assert decision.evidence.contradiction is True
    assert decision.evidence.affect_score >= HIGH_AFFECT_SCORE
    assert decision.evidence.top_margin <= CLOSE_TOP_MARGIN


@pytest.mark.parametrize("affect_index", [0, 1])
def test_high_feeler_or_expressor_score_warrants_deliberation(affect_index):
    scores = [0.1] * 7
    scores[affect_index] = HIGH_AFFECT_SCORE
    scores[3] = 0.6

    decision = decide_deliberation(_vector(scores=scores))

    assert decision.warranted
    assert decision.reason is DeliberationReason.HIGH_AFFECT
    assert decision.evidence.affect_role == ROLE_ORDER[affect_index]
    assert decision.evidence.affect_score == HIGH_AFFECT_SCORE


def test_non_affect_role_above_affect_threshold_does_not_trigger_high_affect():
    decision = decide_deliberation(_vector(
        scores=(0.1, 0.1, 0.2, 0.95, 0.3, 0.5, 0.4)
    ))

    assert not decision.warranted
    assert decision.reason is DeliberationReason.NOT_WARRANTED


def test_inactive_affect_score_does_not_trigger_high_affect():
    decision = decide_deliberation(_vector(
        scores=(0.99, 0.1, 0.2, 0.7, 0.3, 0.5, 0.4),
        active=(0, 1, 1, 1, 1, 1, 1),
    ))

    assert not decision.warranted
    assert decision.evidence.affect_role == "Expressor"
    assert decision.evidence.affect_score == 0.1


@pytest.mark.parametrize("margin", [0.0, CLOSE_TOP_MARGIN])
def test_close_top_active_score_margin_warrants_deliberation(margin):
    decision = decide_deliberation(_vector(
        scores=(0.1, 0.1, 0.2, 0.7, 0.7 - margin, 0.3, 0.4)
    ))

    assert decision.warranted
    assert decision.reason is DeliberationReason.CLOSE_MARGIN
    assert decision.evidence.top_margin == pytest.approx(margin)


def test_margin_above_boundary_is_not_close():
    decision = decide_deliberation(_vector(
        scores=(0.1, 0.1, 0.2, 0.7, 0.649999, 0.3, 0.4)
    ))

    assert not decision.warranted


def test_inactive_roles_are_excluded_from_ranking_but_scores_remain_evidence():
    decision = decide_deliberation(_vector(
        scores=(0.1, 0.1, 0.99, 0.7, 0.68, 0.3, 0.4),
        active=(1, 1, 0, 1, 1, 1, 1),
    ))

    assert decision.evidence.top_role == "Doer"
    assert decision.evidence.runner_up_role == "Wanderer"
    assert "Carer" not in decision.evidence.active_roles
    assert dict(decision.evidence.scores)["Carer"] == 0.99


def test_equal_scores_use_fixed_role_order_for_deterministic_fallback():
    decision = decide_deliberation(_vector(scores=(0.6,) * 7))

    assert decision.evidence.top_role == "Feeler"
    assert decision.evidence.runner_up_role == "Expressor"


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda value: None, EvidenceError.NOT_A_MAPPING),
        (lambda value: {**value, "schema": "wrong"}, EvidenceError.INVALID_SCHEMA),
        (lambda value: {**value, "order": list(reversed(ROLE_ORDER))}, EvidenceError.INVALID_ORDER),
        (lambda value: {**value, "scores": [0.1] * 6}, EvidenceError.INVALID_SCORES),
        (lambda value: {**value, "scores": [0.1] * 6 + [True]}, EvidenceError.INVALID_SCORES),
        (lambda value: {**value, "scores": [0.1] * 6 + [float("nan")]}, EvidenceError.INVALID_SCORES),
        (lambda value: {**value, "scores": [0.1] * 6 + [1.01]}, EvidenceError.INVALID_SCORES),
        (lambda value: {**value, "active": [1] * 6}, EvidenceError.INVALID_ACTIVE),
        (lambda value: {**value, "active": [1] * 6 + [True]}, EvidenceError.INVALID_ACTIVE),
        (lambda value: {**value, "contradiction": 1}, EvidenceError.INVALID_CONTRADICTION),
        (lambda value: {**value, "source": "model"}, EvidenceError.INVALID_PROVENANCE),
        (lambda value: {**value, "model_calls": True}, EvidenceError.INVALID_PROVENANCE),
        (lambda value: {**value, "independent_transformers": True}, EvidenceError.INVALID_PROVENANCE),
    ],
)
def test_invalid_compact_evidence_fails_closed_without_model_request(mutate, error):
    value = _vector()
    changed = mutate(value)
    decision = decide_deliberation(changed)

    assert not decision.warranted
    assert decision.reason is DeliberationReason.INVALID_EVIDENCE
    assert decision.evidence.validation_error is error
    assert decision.evidence.top_role is None


def test_valid_textual_json_can_select_only_an_active_role():
    decision = decide_deliberation(_vector(
        scores=(0.2, 0.1, 0.3, 0.7, 0.69, 0.4, 0.2)
    ))
    result = resolve_textual_deliberation(
        '{"selected_role":"Wanderer","reason":"It better balances the close options."}',
        decision,
    )

    assert result.ok
    assert result.selected_role == "Wanderer"
    assert result.source is ResolutionSource.LLM
    assert result.decision_reason is DeliberationReason.CLOSE_MARGIN
    assert result.evidence is decision.evidence


def test_leading_think_wrapper_is_tolerated_but_json_remains_strict():
    decision = decide_deliberation(_vector(contradiction=True))
    result = resolve_textual_deliberation(
        '<think>compare the active perspectives</think>\n'
        '{"selected_role":"Doer","reason":"It remains the strongest grounded option."}',
        decision,
    )

    assert result.ok and result.selected_role == "Doer"


def test_not_warranted_decision_never_consumes_model_text():
    decision = decide_deliberation(_vector())
    result = resolve_textual_deliberation(
        '{"selected_role":"Reflector","reason":"model claim"}', decision
    )

    assert result.selected_role == "Doer"
    assert result.source is ResolutionSource.DETERMINISTIC
    assert result.error is ResponseError.NOT_WARRANTED
    assert result.explanation == "deterministic fallback: not_warranted"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        ("not json", ResponseError.MALFORMED_JSON),
        ("[]", ResponseError.MALFORMED_JSON),
        ('{"selected_role":"Doer"}', ResponseError.EXTRA_FIELDS),
        ('{"selected_role":"Doer","reason":"ok","extra":1}', ResponseError.EXTRA_FIELDS),
        ('{"selected_role":"Doer","selected_role":"Feeler","reason":"ok"}', ResponseError.MALFORMED_JSON),
        ('{"selected_role":"Unknown","reason":"ok"}', ResponseError.INVALID_ROLE),
        ('{"selected_role":"Doer","reason":""}', ResponseError.INVALID_REASON),
        ('{"selected_role":"Doer","reason":3}', ResponseError.INVALID_REASON),
        ('{"selected_role":"Doer","reason":"ok"} trailing', ResponseError.MALFORMED_JSON),
        ('```json\n{"selected_role":"Doer","reason":"ok"}\n```', ResponseError.MALFORMED_JSON),
        ('<think>unclosed', ResponseError.MALFORMED_JSON),
    ],
)
def test_invalid_textual_responses_use_deterministic_top_role(response, error):
    decision = decide_deliberation(_vector(contradiction=True))
    result = resolve_textual_deliberation(response, decision)

    assert result.selected_role == "Doer"
    assert result.source is ResolutionSource.DETERMINISTIC
    assert result.error is error
    assert result.explanation == f"deterministic fallback: {error.value}"


def test_inactive_role_cannot_be_selected_by_textual_deliberation():
    decision = decide_deliberation(_vector(
        active=(1, 1, 0, 1, 1, 1, 1), contradiction=True
    ))
    result = resolve_textual_deliberation(
        '{"selected_role":"Carer","reason":"not active"}', decision
    )

    assert result.error is ResponseError.INVALID_ROLE
    assert result.selected_role == "Doer"


def test_response_and_reason_caps_are_hard_failures():
    decision = decide_deliberation(_vector(contradiction=True))
    oversized_response = resolve_textual_deliberation(
        "x" * (MAX_RESPONSE_CHARS + 1), decision
    )
    oversized_reason = resolve_textual_deliberation(
        json.dumps({
            "selected_role": "Doer",
            "reason": "x" * (MAX_REASON_CHARS + 1),
        }),
        decision,
    )

    assert oversized_response.error is ResponseError.INPUT_TOO_LARGE
    assert oversized_reason.error is ResponseError.INVALID_REASON


def test_resolution_is_deterministic_for_identical_inputs():
    decision = decide_deliberation(_vector(contradiction=True))
    response = '{"selected_role":"Reflector","reason":"Review the conflict."}'

    assert resolve_textual_deliberation(response, decision) == resolve_textual_deliberation(
        response, decision
    )
