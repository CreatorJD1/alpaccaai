from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import math

import pytest

from alpecca.affect_evidence import (
    MAX_DECAY_SECONDS,
    MAX_SOURCE_CHARS,
    MAX_STATE_DESCRIPTION_CHARS,
    MAX_TTL_SECONDS,
    AffectEvidenceEnvelope,
    assess_affect_evidence,
    evaluate_affect_evidence,
)


def envelope(**overrides: object) -> AffectEvidenceEnvelope:
    values: dict[str, object] = {
        "source": "user_message",
        "cue_kind": "distress",
        "confidence": 0.9,
        "timestamp": 100.0,
        "observable_state": "use a calmer, support-focused response strategy",
        "decay_seconds": 20.0,
        "ttl_seconds": 60.0,
    }
    values.update(overrides)
    return AffectEvidenceEnvelope.create(**values)  # type: ignore[arg-type]


def test_envelope_is_immutable_bounded_and_derives_expiry():
    evidence = envelope()

    assert evidence.source == "user_message"
    assert evidence.cue_kind == "distress"
    assert evidence.timestamp == 100.0
    assert evidence.decay_seconds == 20.0
    assert evidence.expires_at == 160.0
    with pytest.raises(FrozenInstanceError):
        evidence.confidence = 0.1  # type: ignore[misc]


def test_current_strong_evidence_is_eligible_and_described_operationally():
    decision = assess_affect_evidence(envelope(), now=100.0)

    assert decision.should_update is True
    assert decision.reason == "eligible"
    assert decision.effective_confidence == pytest.approx(0.9)
    description = decision.observable_description().lower()
    assert "observed distress cue" in description
    assert "operational state" in description
    assert "i feel" not in description
    assert "conscious" not in description
    assert "sentient" not in description


def test_confidence_decays_by_half_life_and_eventually_becomes_weak():
    evidence = envelope(confidence=1.0, decay_seconds=10.0)

    at_half_life = assess_affect_evidence(
        evidence, now=110.0, min_confidence=0.5
    )
    after_half_life = assess_affect_evidence(
        evidence, now=111.0, min_confidence=0.5
    )

    assert at_half_life.should_update is True
    assert at_half_life.effective_confidence == pytest.approx(0.5)
    assert after_half_life.should_update is False
    assert after_half_life.reason == "weak_evidence"


def test_missing_and_initially_weak_evidence_do_not_update():
    missing = assess_affect_evidence(None, now=100.0)
    weak = assess_affect_evidence(envelope(confidence=0.59), now=100.0)

    assert missing.should_update is False
    assert missing.reason == "missing_evidence"
    assert missing.evidence is None
    assert weak.should_update is False
    assert weak.reason == "weak_evidence"


def test_future_and_expired_evidence_do_not_update_at_boundaries():
    evidence = envelope(timestamp=100.0, ttl_seconds=10.0)

    future = assess_affect_evidence(evidence, now=99.999)
    just_before_expiry = assess_affect_evidence(
        evidence, now=109.999, min_confidence=0.0
    )
    expired = assess_affect_evidence(
        evidence, now=110.0, min_confidence=0.0
    )

    assert future.reason == "not_yet_observed"
    assert future.should_update is False
    assert just_before_expiry.should_update is True
    assert expired.reason == "expired"
    assert expired.should_update is False
    assert evidence.effective_confidence(110.0) == 0.0


@pytest.mark.parametrize(
    "cue_kind",
    (
        "correction",
        "confirmation",
        "reference",
        "urgency",
        "distress",
        "question",
        "action_intent",
    ),
)
def test_all_phase4_cue_kinds_are_supported(cue_kind: str):
    evidence = envelope(cue_kind=cue_kind)
    assert evidence.cue_kind == cue_kind


@pytest.mark.parametrize(
    "observable_state",
    (
        "I feel scared",
        "Alpecca feels worried",
        "She is feeling anxious",
        "I am conscious",
        "Alpecca is sentient",
    ),
)
def test_literal_inner_life_claims_are_rejected(observable_state: str):
    with pytest.raises(ValueError, match="operational behavior"):
        envelope(observable_state=observable_state)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("source", "", "source is required"),
        ("source", "user message", "source may contain"),
        ("source", "x" * (MAX_SOURCE_CHARS + 1), "source exceeds"),
        ("cue_kind", "joy", "cue_kind"),
        ("confidence", -0.01, "between 0 and 1"),
        ("confidence", 1.01, "between 0 and 1"),
        ("confidence", math.nan, "finite"),
        ("timestamp", -1.0, "cannot be negative"),
        ("decay_seconds", 0.0, "greater than 0"),
        ("decay_seconds", MAX_DECAY_SECONDS + 1, "at most"),
        ("ttl_seconds", 0.0, "greater than 0"),
        ("ttl_seconds", MAX_TTL_SECONDS + 1, "at most"),
        (
            "observable_state",
            "x" * (MAX_STATE_DESCRIPTION_CHARS + 1),
            "observable_state exceeds",
        ),
    ),
)
def test_invalid_or_unbounded_envelopes_are_rejected(
    field: str, value: object, error: str
):
    with pytest.raises((TypeError, ValueError), match=error):
        envelope(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("confidence", True),
        ("timestamp", "now"),
        ("decay_seconds", None),
        ("ttl_seconds", False),
    ),
)
def test_numeric_fields_reject_non_numeric_and_boolean_values(
    field: str, value: object
):
    with pytest.raises(TypeError, match="must be numeric"):
        envelope(**{field: value})


def test_direct_expiry_must_follow_timestamp_within_hard_limit():
    common = {
        "source": "system_telemetry",
        "cue_kind": "urgency",
        "confidence": 0.8,
        "timestamp": 100.0,
        "decay_seconds": 30.0,
        "observable_state": "prioritize a concise and time-aware response",
    }

    with pytest.raises(ValueError, match="expires_at must be after"):
        AffectEvidenceEnvelope(expires_at=100.0, **common)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="expires_at must be after"):
        AffectEvidenceEnvelope(
            expires_at=100.0 + MAX_TTL_SECONDS + 0.1, **common
        )  # type: ignore[arg-type]


def test_assessment_is_deterministic_serializable_and_alias_matches():
    evidence = envelope(cue_kind="correction", confidence=0.88)
    first = assess_affect_evidence(evidence, now=102.0)
    second = evaluate_affect_evidence(evidence, now=102.0)

    assert first == second
    encoded = json.dumps(first.as_dict(), sort_keys=True)
    assert '"cue_kind": "correction"' in encoded
    assert '"should_update": true' in encoded


@pytest.mark.parametrize("value", (math.nan, math.inf, -1.0, True, "now"))
def test_assessment_rejects_invalid_now(value: object):
    with pytest.raises((TypeError, ValueError)):
        assess_affect_evidence(envelope(), now=value)  # type: ignore[arg-type]


def test_assessment_rejects_wrong_evidence_type():
    with pytest.raises(TypeError, match="AffectEvidenceEnvelope"):
        assess_affect_evidence(object(), now=100.0)  # type: ignore[arg-type]
