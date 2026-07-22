import json

import pytest

from alpecca.selective_soul import ROLE_ORDER, VECTOR_SCHEMA
from alpecca.video_reactor import (
    MAX_OBSERVATION_CHARS,
    ConversationContext,
    ConversationMode,
    DecisionReason,
    EventDisposition,
    EventProvenance,
    MeaningfulEvent,
    Novelty,
    PriorEventRange,
    ReactionAction,
    VideoReactionError,
    decide_video_reaction,
)


def _vector(scores, *, active=(1, 1, 1, 1, 1, 1, 1)):
    return {
        "schema": VECTOR_SCHEMA,
        "order": list(ROLE_ORDER),
        "scores": list(scores),
        "active": list(active),
        "contradiction": False,
        "source": "deterministic",
        "model_calls": 0,
        "independent_transformers": False,
    }


def _event(
    *,
    surface="house_hq",
    meaningful=True,
    novelty=Novelty.NOVEL,
    event_id="event-1",
    source_id="source-1",
    start=10.0,
    end=12.0,
    fingerprint="range-a",
):
    return MeaningfulEvent(
        provenance=EventProvenance(
            event_id=event_id,
            source_id=source_id,
            surface=surface,
            adapter_id="derived-video-adapter",
        ),
        start_seconds=start,
        end_seconds=end,
        fingerprint=fingerprint,
        meaningful=meaningful,
        novelty=novelty,
    )


FEELER_LEADS = _vector((0.8, 0.3, 0.2, 0.4, 0.5, 0.3, 0.2))
EXPRESSOR_LEADS = _vector((0.3, 0.8, 0.2, 0.4, 0.5, 0.3, 0.2))
WANDERER_LEADS = _vector((0.3, 0.2, 0.2, 0.4, 0.8, 0.5, 0.3))


def test_novel_meaningful_event_reacts_when_watching():
    decision = decide_video_reaction(
        _event(), ConversationContext(mode=ConversationMode.WATCHING), FEELER_LEADS
    )

    assert decision.action is ReactionAction.REACT
    assert decision.disposition is EventDisposition.OBSERVED
    assert decision.reason is DecisionReason.MEANINGFUL_REACTION
    assert decision.meaningful_event_retained


def test_engaged_expressive_soul_speaks():
    decision = decide_video_reaction(
        _event(novelty=Novelty.FAMILIAR),
        ConversationContext(mode=ConversationMode.ENGAGED),
        EXPRESSOR_LEADS,
    )

    assert decision.action is ReactionAction.SPEAK
    assert decision.reason is DecisionReason.EXPRESSIVE_RESPONSE


def test_novel_inquiry_role_asks_question_when_no_question_is_pending():
    decision = decide_video_reaction(
        _event(),
        ConversationContext(mode=ConversationMode.ENGAGED, question_pending=False),
        WANDERER_LEADS,
    )

    assert decision.action is ReactionAction.QUESTION
    assert decision.reason is DecisionReason.CURIOSITY_QUESTION


def test_pending_question_prevents_stacking_another_question():
    decision = decide_video_reaction(
        _event(),
        ConversationContext(mode=ConversationMode.ENGAGED, question_pending=True),
        WANDERER_LEADS,
    )

    assert decision.action is ReactionAction.REACT
    assert decision.reason is DecisionReason.MEANINGFUL_REACTION


def test_directed_context_speaks_without_requiring_an_expressive_leader():
    decision = decide_video_reaction(
        _event(novelty=Novelty.FAMILIAR),
        ConversationContext(mode=ConversationMode.DIRECTED),
        FEELER_LEADS,
    )

    assert decision.action is ReactionAction.SPEAK
    assert decision.reason is DecisionReason.DIRECTED_RESPONSE


@pytest.mark.parametrize(
    ("mode", "novelty", "reason"),
    [
        (ConversationMode.QUIET, Novelty.SURPRISING, DecisionReason.QUIET_CONTEXT),
        (ConversationMode.WATCHING, Novelty.FAMILIAR, DecisionReason.FAMILIAR_CONTEXT),
    ],
)
def test_contextual_silence_explicitly_retains_meaningful_event(mode, novelty, reason):
    decision = decide_video_reaction(
        _event(novelty=novelty), ConversationContext(mode=mode), FEELER_LEADS
    )

    assert decision.action is ReactionAction.SILENT
    assert decision.disposition is EventDisposition.RETAINED
    assert decision.reason is reason
    assert decision.meaningful_event_retained is True


def test_nonmeaningful_event_can_be_silent_without_retention():
    decision = decide_video_reaction(
        _event(meaningful=False), ConversationContext(), FEELER_LEADS
    )

    assert decision.action is ReactionAction.SILENT
    assert decision.disposition is EventDisposition.IGNORED
    assert decision.reason is DecisionReason.NOT_MEANINGFUL
    assert decision.meaningful_event_retained is False


def test_user_interruption_defers_meaningful_event_before_any_reaction():
    decision = decide_video_reaction(
        _event(novelty=Novelty.SURPRISING),
        ConversationContext(
            mode=ConversationMode.DIRECTED,
            user_interrupted=True,
            technical_backpressure="inference queue saturated",
        ),
        EXPRESSOR_LEADS,
    )

    assert decision.action is ReactionAction.SILENT
    assert decision.disposition is EventDisposition.DEFERRED
    assert decision.reason is DecisionReason.USER_INTERRUPTION
    assert decision.meaningful_event_retained


def test_technical_backpressure_defers_with_exact_explicit_reason():
    context = ConversationContext(technical_backpressure="decoder unavailable")
    decision = decide_video_reaction(_event(), context, FEELER_LEADS)

    assert decision.disposition is EventDisposition.DEFERRED
    assert decision.reason is DecisionReason.TECHNICAL_BACKPRESSURE
    assert decision.evidence.backpressure_reason == "decoder unavailable"
    assert decision.meaningful_event_retained
    assert decision.observation_metadata()["backpressure_reason"] == "decoder unavailable"


def test_exact_duplicate_unchanged_range_compacts_with_receipt():
    event = _event(novelty=Novelty.UNCHANGED)
    prior = PriorEventRange(
        event_id="event-0",
        source_id="source-1",
        start_seconds=10.0,
        end_seconds=12.0,
        fingerprint="range-a",
    )
    decision = decide_video_reaction(event, ConversationContext(), FEELER_LEADS, prior_event=prior)

    assert decision.action is ReactionAction.SILENT
    assert decision.disposition is EventDisposition.COMPACTED
    assert decision.reason is DecisionReason.EXACT_DUPLICATE_RANGE
    assert decision.compacted_into_event_id == "event-0"
    assert decision.meaningful_event_retained


@pytest.mark.parametrize(
    "prior",
    [
        PriorEventRange("event-0", "other-source", 10.0, 12.0, "range-a"),
        PriorEventRange("event-0", "source-1", 10.0, 12.1, "range-a"),
        PriorEventRange("event-0", "source-1", 10.0, 12.0, "different"),
    ],
)
def test_near_duplicates_are_not_compacted_or_dropped(prior):
    decision = decide_video_reaction(
        _event(novelty=Novelty.UNCHANGED),
        ConversationContext(),
        FEELER_LEADS,
        prior_event=prior,
    )

    assert decision.disposition is EventDisposition.RETAINED
    assert decision.reason is DecisionReason.FAMILIAR_CONTEXT
    assert decision.compacted_into_event_id is None


def test_invalid_soul_evidence_uses_deterministic_visible_deferral():
    decision = decide_video_reaction(_event(), ConversationContext(), {"bad": "vector"})

    assert decision.action is ReactionAction.SILENT
    assert decision.disposition is EventDisposition.DEFERRED
    assert decision.reason is DecisionReason.INVALID_SOUL_EVIDENCE
    assert decision.evidence.soul_fallback
    assert decision.meaningful_event_retained


def test_no_active_soul_perspective_uses_same_visible_fallback():
    vector = _vector((0.0,) * 7, active=(0,) * 7)
    decision = decide_video_reaction(_event(), ConversationContext(), vector)

    assert decision.disposition is EventDisposition.DEFERRED
    assert decision.reason is DecisionReason.INVALID_SOUL_EVIDENCE
    assert decision.evidence.soul_fallback
    assert tuple(item.role for item in decision.evidence.perspectives) == ROLE_ORDER


def test_all_seven_perspectives_are_preserved_with_fixed_tie_breaking():
    tied = _vector((0.5,) * 7)
    decision = decide_video_reaction(_event(), ConversationContext(), tied)

    assert tuple(item.role for item in decision.evidence.perspectives) == ROLE_ORDER
    assert decision.evidence.leading_role == "Feeler"
    assert len(decision.evidence.perspectives) == 7


def test_inactive_high_score_cannot_lead_policy():
    vector = _vector(
        (0.99, 0.2, 0.1, 0.7, 0.3, 0.4, 0.2),
        active=(0, 1, 1, 1, 1, 1, 1),
    )
    decision = decide_video_reaction(_event(), ConversationContext(), vector)

    assert decision.evidence.leading_role == "Doer"


@pytest.mark.parametrize("surface", ["house_hq", "discord"])
def test_policy_is_source_neutral_across_house_and_discord(surface):
    decision = decide_video_reaction(
        _event(surface=surface),
        ConversationContext(mode=ConversationMode.ENGAGED),
        EXPRESSOR_LEADS,
    )

    assert decision.action is ReactionAction.SPEAK
    assert decision.reason is DecisionReason.EXPRESSIVE_RESPONSE
    assert decision.evidence.provenance.surface == surface


def test_repeated_distinct_meaningful_events_have_no_quota_or_cooldown_suppression():
    decisions = [
        decide_video_reaction(
            _event(event_id=f"event-{index}", start=float(index), end=float(index + 1), fingerprint=f"range-{index}"),
            ConversationContext(),
            FEELER_LEADS,
        )
        for index in range(20)
    ]

    assert all(item.action is ReactionAction.REACT for item in decisions)
    assert all(item.meaningful_event_retained for item in decisions)


def test_observation_metadata_is_bounded_prose_free_and_reports_zero_model_calls():
    decision = decide_video_reaction(
        _event(surface="discord"), ConversationContext(), FEELER_LEADS
    )
    metadata = decision.observation_metadata()
    encoded = json.dumps(dict(metadata), sort_keys=True, separators=(",", ":"))

    assert len(encoded) <= MAX_OBSERVATION_CHARS
    assert metadata["roles"] == ROLE_ORDER
    assert metadata["model_calls"] == 0
    assert "descriptor" not in encoded and "transcript" not in encoded
    with pytest.raises(TypeError):
        metadata["action"] = "blocked"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: EventProvenance("event", "https://secret", "house_hq"),
        lambda: EventProvenance("event", "source", "bad surface"),
        lambda: _event(start=2.0, end=1.0),
        lambda: ConversationContext(technical_backpressure=""),
        lambda: ConversationContext(technical_backpressure="x" * 161),
        lambda: ConversationContext(technical_backpressure=3),
    ],
)
def test_provenance_ranges_and_backpressure_reasons_are_strictly_bounded(factory):
    with pytest.raises(VideoReactionError):
        factory()


def test_same_inputs_produce_identical_deterministic_decisions():
    event = _event()
    context = ConversationContext(mode=ConversationMode.ENGAGED)

    assert decide_video_reaction(event, context, EXPRESSOR_LEADS) == decide_video_reaction(
        event, context, EXPRESSOR_LEADS
    )
