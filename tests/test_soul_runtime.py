import json

import pytest

from alpecca import soul
from alpecca.homeostasis import EmotionalState
from alpecca.selective_soul import ROLE_ORDER, DeliberationReason, ResponseError
from alpecca.soul_runtime import (
    MAX_OBSERVATION_CHARS,
    REQUEST_SCHEMA,
    PlanError,
    RuntimeOutcome,
    evaluate_compact_plan,
)


def _synthetic_plan(
    scores=(0.2, 0.1, 0.3, 0.7, 0.4, 0.5, 0.35),
    *,
    active=(1, 1, 1, 1, 1, 1, 1),
    focus="Doer",
    contradiction=False,
):
    return {
        "focus": {"subagent": focus} if focus is not None else None,
        "perspective_vector": {
            "schema": "alpecca.soul-perspective-vector.v1",
            "order": list(ROLE_ORDER),
            "scores": list(scores),
            "active": list(active),
            "ranks": [1] * 7,
            "focus_index": ROLE_ORDER.index(focus) if focus in ROLE_ORDER else -1,
            "contradiction": contradiction,
            "pressure": "none",
            "escalate": contradiction,
            "source": "deterministic",
            "model_calls": 0,
            "independent_transformers": False,
        },
        "agents": {role: {"kind": "test"} for role in ROLE_ORDER},
        "deliberation_mode": "compact",
    }


def test_real_compact_soul_output_preserves_all_seven_roles():
    plan = soul.soul.compact_plan(soul.snapshot(EmotionalState()))
    record = evaluate_compact_plan(plan)

    assert tuple(item.role for item in record.roles) == ROLE_ORDER
    assert tuple(plan["perspective_vector"]["order"]) == ROLE_ORDER
    assert [item.score for item in record.roles] == plan["perspective_vector"]["scores"]
    assert [int(item.active) for item in record.roles] == plan["perspective_vector"]["active"]


def test_normal_non_triggered_decision_never_invokes_textual_callback():
    calls = []

    def deliberator(request):
        calls.append(request)
        raise AssertionError("normal decision must not invoke a model")

    record = evaluate_compact_plan(_synthetic_plan(), textual_deliberator=deliberator)

    assert calls == []
    assert not record.escalation_eligible
    assert not record.callback_invoked
    assert record.outcome is RuntimeOutcome.NOT_ELIGIBLE
    assert record.deterministic_role == record.selected_role == "Doer"
    assert record.decision.reason is DeliberationReason.NOT_WARRANTED


@pytest.mark.parametrize(
    ("plan", "reason"),
    [
        (_synthetic_plan(contradiction=True), DeliberationReason.CONTRADICTION),
        (_synthetic_plan(scores=(0.8, 0.1, 0.2, 0.7, 0.3, 0.4, 0.2)), DeliberationReason.HIGH_AFFECT),
        (_synthetic_plan(scores=(0.1, 0.1, 0.2, 0.7, 0.68, 0.3, 0.4)), DeliberationReason.CLOSE_MARGIN),
    ],
)
def test_only_selective_triggers_are_escalation_eligible(plan, reason):
    record = evaluate_compact_plan(plan)

    assert record.escalation_eligible
    assert not record.callback_invoked
    assert record.outcome is RuntimeOutcome.CALLBACK_UNAVAILABLE
    assert record.decision.reason is reason
    assert record.selected_role == record.deterministic_role == "Doer"


def test_injected_callback_receives_bounded_role_only_request_and_can_select():
    captured = []

    def deliberator(request):
        captured.append(request)
        return json.dumps({
            "selected_role": "Wanderer",
            "reason": "The close active scores warrant the alternate perspective.",
        })

    record = evaluate_compact_plan(
        _synthetic_plan(scores=(0.1, 0.1, 0.2, 0.7, 0.68, 0.3, 0.4)),
        textual_deliberator=deliberator,
    )

    assert len(captured) == 1
    request = captured[0]
    assert request.schema == REQUEST_SCHEMA
    assert request.trigger is DeliberationReason.CLOSE_MARGIN
    assert request.deterministic_role == "Doer"
    assert tuple(item.role for item in request.roles) == ROLE_ORDER
    assert record.callback_invoked
    assert record.outcome is RuntimeOutcome.TEXTUAL_SELECTION
    assert record.selected_role == "Wanderer"


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        '{"selected_role":"Unknown","reason":"invalid role"}',
        '{"selected_role":"Wanderer","reason":"ok","extra":true}',
        "x" * 4_097,
    ],
)
def test_rejected_textual_response_falls_back_to_original_soul_focus(response):
    plan = _synthetic_plan(
        scores=(0.7, 0.1, 0.2, 0.69, 0.3, 0.4, 0.2),
        focus="Doer",
        contradiction=True,
    )
    record = evaluate_compact_plan(plan, textual_deliberator=lambda _request: response)

    # The score leader is Feeler, but fallback preserves soul.py's ranked focus.
    assert record.decision.evidence.top_role == "Feeler"
    assert record.deterministic_role == record.selected_role == "Doer"
    assert record.callback_invoked
    assert record.outcome is RuntimeOutcome.RESPONSE_REJECTED
    assert record.resolution is not None and not record.resolution.ok


def test_callback_exception_is_content_free_and_deterministic():
    def failing(_request):
        raise RuntimeError("private provider details")

    first = evaluate_compact_plan(
        _synthetic_plan(contradiction=True), textual_deliberator=failing
    )
    second = evaluate_compact_plan(
        _synthetic_plan(contradiction=True), textual_deliberator=failing
    )

    assert first == second
    assert first.selected_role == "Doer"
    assert first.outcome is RuntimeOutcome.CALLBACK_FAILED
    assert "private provider details" not in str(first.observation_metadata())


def test_observation_metadata_is_bounded_fixed_and_contains_no_model_reason():
    model_reason = "private textual rationale"
    record = evaluate_compact_plan(
        _synthetic_plan(contradiction=True),
        textual_deliberator=lambda _request: json.dumps({
            "selected_role": "Reflector", "reason": model_reason
        }),
    )

    metadata = record.observation_metadata()
    encoded = json.dumps(dict(metadata), sort_keys=True, separators=(",", ":"))
    assert len(encoded) <= MAX_OBSERVATION_CHARS
    assert metadata["roles"] == ROLE_ORDER
    assert metadata["advisory_only"] is True
    assert metadata["callback_invoked"] is True
    assert metadata["selected_role"] == "Reflector"
    assert model_reason not in encoded
    with pytest.raises(TypeError):
        metadata["selected_role"] = "blocked"


@pytest.mark.parametrize(
    ("plan", "error"),
    [
        (None, PlanError.NOT_A_MAPPING),
        ({}, PlanError.NOT_COMPACT),
        ({**_synthetic_plan(), "agents": {"Doer": {}}}, PlanError.INVALID_AGENTS),
        ({**_synthetic_plan(), "perspective_vector": None}, PlanError.INVALID_VECTOR),
        ({**_synthetic_plan(), "focus": {"subagent": "Unknown"}}, PlanError.INVALID_FOCUS),
        ({**_synthetic_plan(), "focus": None}, PlanError.INVALID_FOCUS),
    ],
)
def test_invalid_compact_plans_never_invoke_callback(plan, error):
    calls = []
    record = evaluate_compact_plan(
        plan,
        textual_deliberator=lambda request: calls.append(request) or "{}",
    )

    assert calls == []
    assert not record.escalation_eligible
    assert not record.callback_invoked
    assert record.outcome is RuntimeOutcome.INVALID_PLAN
    assert record.plan_error is error


def test_response_error_is_projected_without_response_content():
    record = evaluate_compact_plan(
        _synthetic_plan(contradiction=True),
        textual_deliberator=lambda _request: "bad response",
    )

    assert record.resolution.error is ResponseError.MALFORMED_JSON
    metadata = record.observation_metadata()
    assert metadata["response_error"] == "malformed_json"
    assert "bad response" not in str(metadata)
