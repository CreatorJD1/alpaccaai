from __future__ import annotations

import math

import pytest

from alpecca import multimodal_affect_fusion as fusion
from alpecca import soul


def evidence(
    modality: str,
    scores=(0.05, 0.65, 0.05, 0.05, 0.05, 0.10, 0.05),
    confidence: float = 0.8,
    provenance: tuple[str, ...] | None = None,
) -> fusion.ModalityAffectEvidence:
    return fusion.ModalityAffectEvidence(
        modality=modality,  # type: ignore[arg-type]
        scores=scores,
        confidence=confidence,
        provenance=(f"{modality}:event-1",) if provenance is None else provenance,
    )


def test_contract_uses_exact_soul_order_and_one_shared_encoder() -> None:
    result = fusion.fuse_affect_evidence(
        text=evidence("text"),
        speech=evidence("speech"),
    ).as_dict()

    advisory = result["soul_advisory"]
    assert fusion.PERSPECTIVE_ORDER == soul.PERSPECTIVE_ORDER
    assert tuple(advisory["order"]) == soul.PERSPECTIVE_ORDER
    assert len(advisory["scores"]) == 7
    assert advisory["shared_encoder_count"] == 1
    assert advisory["perspective_head_count"] == 7
    assert advisory["shared_backbone_id"] == fusion.SHARED_BACKBONE_ID
    assert len({head["head_id"] for head in advisory["heads"]}) == 7
    assert all(
        spec["shared_backbone_id"] == fusion.SHARED_BACKBONE_ID
        for spec in advisory["head_specs"]
    )
    assert all(
        spec["architecture"] == fusion.HEAD_ARCHITECTURE
        for spec in advisory["head_specs"]
    )
    assert advisory["advisory_only"] is True
    assert advisory["authorizes_action"] is False
    assert advisory["qualified"] is False


def test_fallback_heads_are_distinct_unqualified_and_provenanced() -> None:
    result = fusion.fuse_affect_evidence(
        text=evidence("text", provenance=("turn:19", "text:lexicon-v2")),
        speech=evidence("speech", provenance=("turn:19", "speech:prosody-v1")),
    ).soul_advisory

    assert tuple(head.perspective for head in result.heads) == soul.PERSPECTIVE_ORDER
    assert len({head.head_id for head in result.heads}) == 7
    for head in result.heads:
        assert head.mode == "deterministic_fallback"
        assert head.evaluator_id == fusion.DETERMINISTIC_FALLBACK_ID
        assert head.confidence == pytest.approx(
            result.source_confidence * fusion.FALLBACK_HEAD_CONFIDENCE_FACTOR
        )
        assert head.provenance == ("turn:19", "text:lexicon-v2", "speech:prosody-v1")
        serialized = head.as_dict()
        assert serialized["qualified"] is False
        assert serialized["advisory_only"] is True
        assert serialized["authorizes_action"] is False


def test_identical_modalities_preserve_distribution_and_full_agreement() -> None:
    text = evidence("text", confidence=0.9)
    speech = evidence("speech", confidence=0.9)
    result = fusion.fuse_affect_evidence(text=text, speech=speech)

    assert result.mode == "dual_cross_late"
    assert result.agreement == pytest.approx(1.0)
    assert result.scores == pytest.approx(text.scores)
    assert result.confidence == pytest.approx(0.9)
    assert result.text_branch == pytest.approx(text.scores)
    assert result.speech_branch == pytest.approx(speech.scores)


def test_disagreeing_modalities_remain_bounded_and_lower_confidence() -> None:
    text = evidence("text", (0, 1, 0, 0, 0, 0, 0), confidence=1.0)
    speech = evidence("speech", (0, 0, 0, 1, 0, 0, 0), confidence=1.0)
    result = fusion.fuse_affect_evidence(text=text, speech=speech)

    assert result.agreement == 0.0
    assert result.confidence == 0.5
    assert sum(result.scores) == pytest.approx(1.0)
    assert result.scores[1] == pytest.approx(0.5)
    assert result.scores[3] == pytest.approx(0.5)
    assert all(0.0 <= value <= 1.0 for value in result.scores)


@pytest.mark.parametrize("modality", ["text", "speech"])
def test_missing_modality_fallback_is_explicit_and_discounted(modality: str) -> None:
    item = evidence(modality, confidence=0.8)
    kwargs = {modality: item}
    result = fusion.fuse_affect_evidence(**kwargs)

    assert result.mode == f"{modality}_only"
    assert result.modalities == (modality,)
    assert result.agreement is None
    assert result.confidence == pytest.approx(0.8 * fusion.FALLBACK_CONFIDENCE_FACTOR)
    assert result.scores == pytest.approx(item.scores)
    assert (result.text_branch is not None) is (modality == "text")
    assert (result.speech_branch is not None) is (modality == "speech")


def test_no_modality_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one modality"):
        fusion.fuse_affect_evidence()


@pytest.mark.parametrize(
    "scores, error",
    [
        ((1, 0), "exactly"),
        ((0, 0, 0, 0, 0, 0, 0), "positive evidence"),
        ((1, 0, 0, 0, 0, 0, -0.1), "between 0 and 1"),
        ((1, 0, 0, 0, 0, 0, math.inf), "finite"),
        ((1, 0, 0, 0, 0, 0, True), "numeric"),
    ],
)
def test_vector_dimensions_and_values_are_strict(scores, error: str) -> None:
    with pytest.raises((TypeError, ValueError), match=error):
        evidence("text", scores=scores)


@pytest.mark.parametrize("confidence", [-0.1, 1.1, math.nan, True])
def test_confidence_is_strict(confidence) -> None:
    with pytest.raises((TypeError, ValueError)):
        evidence("text", confidence=confidence)


def test_scores_are_normalized_without_mutating_input() -> None:
    raw = (0.5, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    item = evidence("text", scores=raw)
    assert raw == (0.5, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert item.scores == pytest.approx((1 / 3, 2 / 3, 0, 0, 0, 0, 0))


def test_wrong_modality_slots_are_rejected() -> None:
    with pytest.raises(ValueError, match="wrong modality"):
        fusion.fuse_affect_evidence(text=evidence("speech"))
    with pytest.raises(ValueError, match="wrong modality"):
        fusion.fuse_affect_evidence(speech=evidence("text"))


def test_provenance_is_bounded_unique_and_metadata_only() -> None:
    with pytest.raises(ValueError, match="1 to"):
        evidence("text", provenance=())
    with pytest.raises(ValueError, match="unique"):
        evidence("text", provenance=("event:1", "event:1"))
    with pytest.raises(ValueError, match="unsupported"):
        evidence("text", provenance=("raw words are not accepted",))
    with pytest.raises(ValueError, match="hard cap"):
        fusion.fuse_affect_evidence(
            text=evidence("text", provenance=("t:1", "t:2", "t:3")),
            speech=evidence("speech", provenance=("s:1", "s:2", "s:3")),
        )


def test_combined_provenance_deduplicates_shared_event_references() -> None:
    result = fusion.fuse_affect_evidence(
        text=evidence("text", provenance=("turn:4", "text:model-a")),
        speech=evidence("speech", provenance=("turn:4", "speech:model-b")),
    )
    assert result.provenance == ("turn:4", "text:model-a", "speech:model-b")


def test_projection_is_confidence_bounded_and_emotion_sensitive() -> None:
    fear = fusion.project_for_soul((0, 0, 0, 1, 0, 0, 0), confidence=1.0)
    joy = fusion.project_for_soul((0, 1, 0, 0, 0, 0, 0), confidence=1.0)
    weak = fusion.project_for_soul((0, 0, 0, 1, 0, 0, 0), confidence=0.2)

    carer = fusion.PERSPECTIVE_ORDER.index("Carer")
    wanderer = fusion.PERSPECTIVE_ORDER.index("Wanderer")
    assert fear.scores[carer] > joy.scores[carer]
    assert joy.scores[wanderer] > fear.scores[wanderer]
    assert max(weak.scores) <= 0.2


def test_serialized_result_makes_non_authority_explicit() -> None:
    result = fusion.fuse_affect_evidence(text=evidence("text")).as_dict()
    assert result["schema"] == fusion.SCHEMA
    assert result["order"] == list(fusion.EMOTION_ORDER)
    assert result["shadow_only"] is True
    assert result["changes_emotional_state"] is False
    assert result["authorizes_action"] is False
    assert "raw_text" not in result
    assert "raw_audio" not in result


def backend_payload(
    provenance: tuple[str, ...] = ("turn:22", "rog:hyfuser-shadow-v1"),
) -> list[dict[str, object]]:
    return [
        {
            "perspective": spec.perspective,
            "head_id": spec.head_id,
            "score": 0.1 + index * 0.1,
            "confidence": 0.9,
            "provenance": list(provenance),
        }
        for index, spec in enumerate(fusion.PERSPECTIVE_HEAD_SPECS)
    ]


def test_future_rog_parser_accepts_exact_seven_head_shadow_contract() -> None:
    provenance = ("turn:22", "rog:hyfuser-shadow-v1")
    advisory = fusion.parse_shadow_head_output(
        backend_payload(provenance),
        backend_id="rog:hyfuser-heads-v1",
        source_confidence=0.72,
        provenance=provenance,
    )

    assert tuple(head.perspective for head in advisory.heads) == soul.PERSPECTIVE_ORDER
    assert [head.score for head in advisory.heads] == pytest.approx(
        [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    )
    assert all(head.confidence == pytest.approx(0.72) for head in advisory.heads)
    assert all(head.mode == "transformer_shadow" for head in advisory.heads)
    assert all(head.evaluator_id == "rog:hyfuser-heads-v1" for head in advisory.heads)
    assert advisory.as_dict()["qualified"] is False


@pytest.mark.parametrize("mutation", ["missing", "extra", "reordered", "wrong_id"])
def test_future_backend_parser_rejects_malformed_head_sets(mutation: str) -> None:
    payload = backend_payload()
    if mutation == "missing":
        payload.pop()
    elif mutation == "extra":
        payload.append(dict(payload[-1]))
    elif mutation == "reordered":
        payload[0], payload[1] = payload[1], payload[0]
    else:
        payload[0]["head_id"] = "hyfuser-head:not-feeler"

    with pytest.raises(ValueError):
        fusion.parse_shadow_head_output(
            payload,
            backend_id="rog:hyfuser-heads-v1",
            source_confidence=0.8,
            provenance=("turn:22", "rog:hyfuser-shadow-v1"),
        )


def test_future_backend_cannot_replace_provenance_or_raise_source_confidence() -> None:
    payload = backend_payload()
    payload[0]["provenance"] = ["invented:event"]
    with pytest.raises(ValueError, match="cannot replace"):
        fusion.parse_shadow_head_output(
            payload,
            backend_id="rog:hyfuser-heads-v1",
            source_confidence=0.4,
            provenance=("turn:22", "rog:hyfuser-shadow-v1"),
        )

    payload = backend_payload()
    advisory = fusion.parse_shadow_head_output(
        payload,
        backend_id="rog:hyfuser-heads-v1",
        source_confidence=0.4,
        provenance=("turn:22", "rog:hyfuser-shadow-v1"),
    )
    assert all(head.confidence == pytest.approx(0.4) for head in advisory.heads)


def test_normal_import_does_not_load_torch() -> None:
    import inspect

    source = inspect.getsource(fusion)
    assert "import torch" not in source
    assert "from torch" not in source
