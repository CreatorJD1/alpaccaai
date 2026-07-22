from __future__ import annotations

from pathlib import Path

import pytest

from alpecca import temporal_derivation
from alpecca.temporal_memory import TemporalMemoryStore


def _store(tmp_path: Path) -> TemporalMemoryStore:
    return TemporalMemoryStore(tmp_path / "temporal-derivation.db")


def _bounded(
    store: TemporalMemoryStore,
    text: str,
    *,
    uid: str,
    observed_at: float,
    scope: str = "creator",
):
    observation = store.record_observation(
        observation_uid=uid,
        source="authenticated_input",
        actor_id="creator-jd",
        surface="house-hq",
        scope=scope,
        observed_at=observed_at,
        content=text,
        raw_reference=f"turn:{uid}",
        recorded_at=observed_at,
    )
    return temporal_derivation.BoundedObservation(observation, text)


def test_bounded_observation_requires_exact_stored_content_hash(tmp_path: Path):
    store = _store(tmp_path)
    bounded = _bounded(
        store,
        "fact: Jason | works_in | California",
        uid="observation-1",
        observed_at=100.0,
    )
    assert bounded.observation.raw_reference == "turn:observation-1"

    with pytest.raises(temporal_derivation.TemporalDerivationError, match="hash"):
        temporal_derivation.BoundedObservation(
            bounded.observation,
            "fact: Jason | works_in | Oregon",
        )


def test_default_extractor_is_narrow_deterministic_and_source_bound(tmp_path: Path):
    store = _store(tmp_path)
    bounded = _bounded(
        store,
        "ordinary prose is ignored\n"
        "fact: Jason | works_in | California | 0.8\n"
        "contradiction: Jason | works_in | Oregon",
        uid="observation-1",
        observed_at=100.0,
    )

    candidates = temporal_derivation.derive_candidates([bounded])

    assert [(item.relation, item.object_text, item.confidence) for item in candidates] == [
        ("assertion", "California", 0.8),
        ("contradiction", "Oregon", 0.6),
    ]
    assert all(item.actor_id == "creator-jd" for item in candidates)
    assert all(item.surface == "house-hq" for item in candidates)
    assert all(item.scope == "creator" for item in candidates)
    assert all(item.evidence_observation_ids == (bounded.observation.id,) for item in candidates)


def test_optional_extractor_can_propose_content_but_not_provenance(tmp_path: Path):
    store = _store(tmp_path)
    bounded = _bounded(
        store, "free-form authenticated statement", uid="observation-1", observed_at=125.0,
    )

    def extractor(_observation):
        return [temporal_derivation.ExtractedFact(
            "Alpecca", "favorite_room", "Library", 0.75, "assertion"
        )]

    candidate = temporal_derivation.derive_candidates(
        [bounded], extractor=extractor,
    )[0]
    assert candidate.actor_id == bounded.observation.actor_id
    assert candidate.surface == bounded.observation.surface
    assert candidate.scope == bounded.observation.scope
    assert candidate.valid_from == bounded.observation.observed_at

    with pytest.raises(temporal_derivation.TemporalDerivationError, match="ExtractedFact"):
        temporal_derivation.derive_candidates(
            [bounded], extractor=lambda _item: [{"subject": "forged"}],
        )


def test_correction_closes_prior_fact_and_preserves_contradiction_history(tmp_path: Path):
    store = _store(tmp_path)
    first = _bounded(
        store, "fact: Jason | works_in | California | 0.8",
        uid="observation-1", observed_at=100.0,
    )
    correction = _bounded(
        store, "correction: Jason | works_in | Oregon | 0.95",
        uid="observation-2", observed_at=200.0,
    )

    first_outcome = temporal_derivation.derive_and_apply(store, [first])[0]
    corrected = temporal_derivation.derive_and_apply(store, [correction])[0]

    assert corrected.closed_fact_ids == (first_outcome.fact.id,)
    assert len(corrected.contradiction_links) == 1
    assert store.facts_valid_at(
        199.0, scope="creator", subject="Jason", predicate="works_in"
    )[0].object_text == "California"
    current = store.facts_valid_at(
        200.0, scope="creator", subject="Jason", predicate="works_in"
    )
    assert [fact.object_text for fact in current] == ["Oregon"]
    assert store.evidence_for_fact(corrected.fact.id) == [correction.observation]


def test_asserted_contradiction_links_without_closing_active_fact(tmp_path: Path):
    store = _store(tmp_path)
    first = _bounded(
        store, "fact: Jason | works_in | California",
        uid="observation-1", observed_at=100.0,
    )
    conflict = _bounded(
        store, "contradiction: Jason | works_in | Oregon",
        uid="observation-2", observed_at=150.0,
    )
    original = temporal_derivation.derive_and_apply(store, [first])[0]
    outcome = temporal_derivation.derive_and_apply(store, [conflict])[0]

    assert outcome.closed_fact_ids == ()
    assert len(outcome.contradiction_links) == 1
    active = store.facts_valid_at(
        150.0, scope="creator", subject="Jason", predicate="works_in"
    )
    assert {fact.object_text for fact in active} == {"California", "Oregon"}
    assert store.contradictions_for_fact(original.fact.id) == list(
        outcome.contradiction_links
    )


def test_supersession_and_replay_are_bounded_and_idempotent(tmp_path: Path):
    store = _store(tmp_path)
    original = _bounded(
        store, "fact: project | status | planning",
        uid="observation-1", observed_at=10.0,
    )
    superseding = _bounded(
        store, "supersession: project | status | active",
        uid="observation-2", observed_at=20.0,
    )
    temporal_derivation.derive_and_apply(store, [original])
    first = temporal_derivation.derive_and_apply(store, [superseding])[0]
    replay = temporal_derivation.derive_and_apply(store, [superseding])[0]

    assert first.closed_fact_ids
    assert replay.fact.id == first.fact.id
    assert store.facts_valid_at(
        20.0, scope="creator", subject="project", predicate="status"
    ) == [first.fact]
    assert len(store.contradictions_for_fact(first.fact.id)) == 1


def test_shadow_recall_comparison_is_read_only_scoped_and_exact(tmp_path: Path):
    store = _store(tmp_path)
    creator = _bounded(
        store, "fact: Jason | works_in | California",
        uid="creator-observation", observed_at=100.0,
    )
    guest = _bounded(
        store, "fact: Jason | works_in | Oregon",
        uid="guest-observation", observed_at=100.0, scope="guest",
    )
    temporal_derivation.derive_and_apply(store, [creator, guest])
    legacy = [
        {"subject": "Jason", "predicate": "works_in", "object": "California"},
        {"subject": "Alpecca", "predicate": "room", "object": "Library"},
    ]

    comparison = temporal_derivation.compare_shadow_recall(
        store,
        legacy,
        at=100.0,
        scope="creator",
        subject="Jason",
        predicate="works_in",
    )

    assert comparison.legacy_count == 2
    assert comparison.temporal_count == 1
    assert comparison.overlap == ("jason | works_in | california",)
    assert comparison.legacy_only == ("alpecca | room | library",)
    assert comparison.temporal_only == ()
    assert comparison.agreement_ratio == 0.5
    assert legacy[0]["object"] == "California"
