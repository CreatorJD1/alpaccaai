from __future__ import annotations

import json

from alpecca import soul
from alpecca.homeostasis import EmotionalState


ROLE_NAMES = (
    "Feeler",
    "Expressor",
    "Carer",
    "Doer",
    "Wanderer",
    "Reflector",
    "Improver",
)


def _tension_snapshot() -> soul.Snapshot:
    return soul.snapshot(
        EmotionalState(
            love=0.8,
            compassion=0.2,
            fear=0.1,
            energy=0.5,
            curiosity=0.7,
            social_hunger=0.8,
        ),
        solitude_s=600,
        desires_summary={"by_kind": {"connection": 1}},
    )


def test_vector_exposes_all_seven_perspectives_in_stable_order() -> None:
    snap = soul.snapshot(EmotionalState())

    first = soul.soul.deliberate(snap)["perspective_vector"]
    second = soul.soul.deliberate(snap)["perspective_vector"]

    assert first == second
    assert tuple(first["order"]) == ROLE_NAMES
    assert tuple(first["order"]) == soul.PERSPECTIVE_ORDER
    assert len(first["scores"]) == 7
    assert len(first["active"]) == 7
    assert len(first["ranks"]) == 7
    # Inactive perspectives remain explicit zeroes instead of disappearing.
    assert sum(first["active"]) < 7
    assert all(
        score == 0.0
        for score, active in zip(first["scores"], first["active"])
        if not active
    )
    assert first["source"] == "deterministic"
    assert first["model_calls"] == 0
    assert first["independent_transformers"] is False
    assert first["escalation_eligibility"] == {
        "schema": soul.ESCALATION_ELIGIBILITY_SCHEMA,
        "eligible": False,
        "reason_codes": [],
        "requires_committed_evidence": True,
        "authorizes_action": False,
    }
    assert len(json.dumps(first, separators=(",", ":"))) < 700


def test_vector_values_remain_bounded_for_extreme_grounded_inputs() -> None:
    plan = soul.soul.deliberate(
        soul.snapshot(
            EmotionalState(
                love=-12.0,
                compassion=12.0,
                fear=99.0,
                energy=99.0,
                curiosity=99.0,
                social_hunger=99.0,
                longing=99.0,
            ),
            person_fatigue=99.0,
            solitude_s=99_999,
            memory_pressure={"score": 1.0, "overflow": True},
        )
    )
    vector = plan["perspective_vector"]

    assert all(0.0 <= score <= 1.0 for score in vector["scores"])
    assert set(vector["active"]) <= {0, 1}
    assert all(0 <= rank <= 4 for rank in vector["ranks"])
    assert vector["pressure"] == "overflow"
    assert vector["escalate"] is True
    assert vector["escalation_eligibility"]["eligible"] is True
    assert "measured_pressure_overflow" in vector["escalation_eligibility"]["reason_codes"]
    assert vector["escalation_eligibility"]["authorizes_action"] is False
    focus_name = plan["focus"]["subagent"]
    assert vector["order"][vector["focus_index"]] == focus_name


def test_competing_execution_directions_raise_contradiction_evidence() -> None:
    plan = soul.soul.deliberate(_tension_snapshot())
    vector = plan["perspective_vector"]

    assert plan["focus"]["subagent"] == "Doer"
    assert vector["pressure"] == "none"
    assert vector["contradiction"] is True
    assert vector["escalate"] is True
    assert vector["scores"][ROLE_NAMES.index("Doer")] >= 0.4
    assert vector["scores"][ROLE_NAMES.index("Reflector")] >= 0.4


def test_settled_single_direction_does_not_invent_a_contradiction() -> None:
    vector = soul.soul.deliberate(
        soul.snapshot(EmotionalState())
    )["perspective_vector"]

    assert vector["contradiction"] is False
    assert vector["pressure"] == "none"
    assert vector["escalate"] is False


def test_memory_and_host_pressure_are_evidence_without_changing_scores_source() -> None:
    memory_vector = soul.soul.deliberate(
        soul.snapshot(
            EmotionalState(),
            memory_pressure={"score": 0.95, "evidence": {"context_fill": 0.95}},
        )
    )["perspective_vector"]
    host_vector = soul.soul.deliberate(
        soul.snapshot(
            EmotionalState(),
            host_pressure={"score": 1.0, "overflow": True},
        )
    )["perspective_vector"]

    assert memory_vector["contradiction"] is False
    assert memory_vector["pressure"] == "high"
    assert memory_vector["escalate"] is True
    assert host_vector["pressure"] == "overflow"
    assert host_vector["escalate"] is True
    assert memory_vector["escalation_eligibility"]["reason_codes"] == [
        "measured_pressure_high"
    ]
    assert host_vector["escalation_eligibility"]["reason_codes"] == [
        "measured_pressure_overflow"
    ]
    assert memory_vector["source"] == host_vector["source"] == "deterministic"


def test_host_pressure_with_projected_evidence_changes_only_self_care_urgency() -> None:
    baseline = soul.soul.deliberate(
        soul.snapshot(EmotionalState(curiosity=0.7), solitude_s=600)
    )
    pressured = soul.soul.deliberate(
        soul.snapshot(
            EmotionalState(curiosity=0.7),
            solitude_s=600,
            host_pressure={
                "severity": "high",
                "evidence_codes": ["commit_pressure"],
            },
        )
    )
    before = {item["subagent"]: item for item in baseline["slate"]}
    after = {item["subagent"]: item for item in pressured["slate"]}

    assert pressured["perspective_vector"]["pressure"] == "high"
    assert after["Reflector"]["urgency"] > before["Reflector"]["urgency"]
    assert after["Improver"]["urgency"] < before["Improver"]["urgency"]
    assert after["Wanderer"] == before["Wanderer"]


def test_vector_evidence_cannot_bypass_existing_arbitration(monkeypatch) -> None:
    snap = _tension_snapshot()
    baseline = soul.MasterAgent().deliberate(snap)
    fabricated = {
        "schema": "test-only",
        "contradiction": False,
        "pressure": "none",
        "escalate": False,
    }
    monkeypatch.setattr(
        soul.MasterAgent,
        "_perspective_vector",
        staticmethod(lambda intentions, focus, snapshot: fabricated),
    )

    observed = soul.MasterAgent().deliberate(snap)

    assert observed["perspective_vector"] is fabricated
    assert observed["focus"] == baseline["focus"]
    assert observed["slate"] == baseline["slate"]
    assert observed["by_category"] == baseline["by_category"]
    assert observed["validation_vector"] == baseline["validation_vector"]
