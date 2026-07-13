from __future__ import annotations

from pathlib import Path

from alpecca import cognition
from alpecca import governed_learning
from alpecca import soul
from alpecca.homeostasis import EmotionalState


def _running_status() -> dict[str, object]:
    return {
        "active_trial": {
            "id": 41,
            "scope": "creator-personal",
            "proposal_id": 17,
            "state": "running",
            "parameter": "chatter_chance",
            "started_at": 100.0,
            "planned_end_at": 7300.0,
            "creator_binding_present": True,
        },
        "runtime_override": {
            "trial_id": 41,
            "scope": "creator-personal",
            "parameter": "chatter_chance",
            "preimage_value": 0.05,
            "override_value": 0.04,
            "applied_at": 100.0,
        },
    }


def _settled_status(*, decided: bool = False) -> dict[str, object]:
    decisions = (
        [{"trial_id": 41, "decision": "revert_to_baseline"}]
        if decided
        else []
    )
    return {
        "active_trial": None,
        "runtime_override": None,
        "registration_candidate_available": True,
        "registration_candidate": (
            None
            if decided
            else {
                "proposal_id": 17,
                "state": "registered",
                "registered_trial_id": 41,
                "trial": {"id": 41, "state": "rolled_back"},
            }
        ),
        "review_settlements_available": True,
        "review_settlements": [
            {
                "trial_id": 41,
                "status": "ready_for_creator_review",
                "outcome": "improved",
            }
        ],
        "profile_decisions_available": True,
        "profile_decisions": decisions,
    }


def test_running_signal_requires_the_exact_runtime_binding():
    signal = governed_learning.build_signal(_running_status())

    assert signal.available is True
    assert signal.phase == "running"
    assert signal.trial_id == 41
    assert signal.proposal_id == 17
    assert signal.creator_action_required is False
    assert signal.candidate_card() == {
        "schema": governed_learning.CANDIDATE_CARD_SCHEMA,
        "proposal_id": 17,
        "trial_id": 41,
        "phase": "running",
        "candidate_state": "registered",
        "trial_state": "running",
        "waiting_for": "evidence_collection",
        "creator_action_required": False,
        "read_only": True,
    }
    assert "preimage_value" not in signal.as_dict()
    assert "override_value" not in signal.as_dict()

    missing = _running_status()
    missing["runtime_override"] = None
    unavailable = governed_learning.build_signal(missing)
    assert unavailable.available is False
    assert unavailable.phase == "unavailable"
    assert unavailable.evidence_code == "running_override_missing"

    mismatched = _running_status()
    mismatched["runtime_override"] = {
        **mismatched["runtime_override"],  # type: ignore[arg-type]
        "trial_id": 99,
    }
    assert governed_learning.build_signal(mismatched).evidence_code == (
        "running_override_invalid"
    )


def test_candidate_settlement_and_creator_decision_are_distinct_phases():
    candidate = governed_learning.build_signal(
        {
            "active_trial": None,
            "runtime_override": None,
            "registration_candidate_available": True,
            "registration_candidate": {
                "proposal_id": 17,
                "state": "pending_creator_plan",
            },
        }
    )
    assert candidate.phase == "candidate"
    assert candidate.creator_action_required is True
    assert candidate.candidate_card()["waiting_for"] == "creator_plan_review"

    review = governed_learning.build_signal(_settled_status())
    assert review.phase == "creator_review"
    assert review.outcome == "improved"
    assert review.creator_action_required is True
    assert "only the creator" in review.observation_text().lower()

    decided = governed_learning.build_signal(_settled_status(decided=True))
    assert decided.phase == "decided"
    assert decided.decision == "revert_to_baseline"
    assert decided.creator_action_required is False

    conflict = _settled_status()
    conflict["registration_candidate"] = {
        "proposal_id": 18,
        "state": "pending_creator_plan",
    }
    rejected = governed_learning.build_signal(conflict)
    assert rejected.available is False
    assert rejected.evidence_code == "candidate_settlement_conflict"


def test_serialized_signals_cannot_forge_a_lifecycle_phase():
    signal = governed_learning.build_signal(_running_status())
    serialized = signal.as_dict()
    assert governed_learning.coerce_signal(serialized) == signal

    forged = {**serialized, "phase": "creator_review"}
    rejected = governed_learning.coerce_signal(forged)
    assert rejected.available is False
    assert rejected.evidence_code == "signal_invalid"
    assert governed_learning.soul_cue(forged) is None

    extra = {**serialized, "command": "retain_trial_value"}
    assert governed_learning.coerce_signal(extra).available is False

    malformed_object = governed_learning.GovernedLearningSignal(
        True,
        "running",
        "forged",
        proposal_id=-1,
        trial_id=41,
        candidate_state="registered",
        trial_state="running",
        parameter="chatter_chance",
        started_at="now",  # type: ignore[arg-type]
        planned_end_at=7300.0,
    )
    assert governed_learning.coerce_signal(malformed_object).available is False


def test_cognition_records_each_verified_transition_once_and_reuses_card(
    tmp_path: Path,
):
    db_path = tmp_path / "governed-cognition.db"
    cognition.init_db(db_path)
    proposal_id = cognition.propose_action(
        cognition.ActionProposal(
            action=cognition.GOVERNED_CANDIDATE_ACTION,
            reason="Qualified-response evidence supports creator review.",
            approval=cognition.APPROVAL_ASK_FIRST,
            risk="low",
            status="testing",
            evidence="metric=qualified_response_rate; completed=5",
            result="Creator lifecycle decisions remain separate.",
        ),
        db_path=db_path,
    )
    assert proposal_id is not None
    signal = governed_learning.build_signal(
        {
            "registration_candidate": {
                "proposal_id": proposal_id,
                "state": "pending_creator_plan",
            }
        }
    )

    first = cognition.record_governed_learning_observation(signal, db_path=db_path)
    second = cognition.record_governed_learning_observation(signal, db_path=db_path)

    assert first["recorded"] is True
    assert second["recorded"] is False
    assert second["reused"] is True
    assert first["observation_id"] == second["observation_id"]
    assert first["candidate_card"]["read_only"] is True
    assert first["candidate_card"]["proposal"]["id"] == proposal_id
    observations = cognition.recent_observations(
        limit=10,
        db_path=db_path,
        scope=cognition.GOVERNED_LEARNING_SCOPE,
    )
    assert len(observations) == 1
    assert observations[0]["source"] == cognition.GOVERNED_LEARNING_SOURCE
    assert observations[0]["metadata"]["signal"]["phase"] == "candidate"
    assert len(cognition.recent_action_proposals(db_path=db_path)) == 1

    registered = governed_learning.build_signal(
        {
            "registration_candidate": {
                "proposal_id": proposal_id,
                "state": "registered",
                "registered_trial_id": 41,
            }
        }
    )
    transition = cognition.record_governed_learning_observation(
        registered, db_path=db_path
    )
    assert transition["recorded"] is True
    assert len(
        cognition.recent_observations(
            limit=10,
            db_path=db_path,
            scope=cognition.GOVERNED_LEARNING_SCOPE,
        )
    ) == 2
    assert len(cognition.recent_action_proposals(db_path=db_path)) == 1


def test_learning_review_card_cannot_claim_governed_trial_authority(tmp_path: Path):
    db_path = tmp_path / "learning-review.db"
    cognition.init_db(db_path)
    result = cognition.record_behavior_improvement_review(
        {
            "kind": "connection",
            "confidence": 0.6,
            "text": "Warmth and response evidence should be reviewed.",
            "evidence": "warmth=0.42; trend=-0.03",
            "suggestion": "chatter_chance:+1",
        },
        {"warmth_now": 0.42, "warmth_trend": -0.03},
        db_path=db_path,
    )

    proposal = result["proposal"]
    assert proposal["action"] == "Review one behavior improvement"
    assert "separately server-issued" in proposal["result"]
    assert "selfmod" not in proposal["result"].lower()
    assert "cannot apply or retain" in result["evaluation"]["test"]


def test_soul_senses_governed_status_without_selecting_a_lifecycle_action():
    running = governed_learning.build_signal(_running_status())
    plan = soul.soul.deliberate(
        soul.snapshot(
            EmotionalState(curiosity=0.8, fear=0.1),
            governed_learning=running,
        )
    )
    improver = next(
        item for item in plan["slate"] if item["subagent"] == "Improver"
    )
    assert improver["action"] == "observe governed trial evidence"
    assert "retention decision is due" in improver["reason"]
    assert "governed_learning" in soul.snapshot(
        EmotionalState(), governed_learning=running
    ).as_dict()

    review = governed_learning.build_signal(_settled_status())
    review_plan = soul.soul.deliberate(
        soul.snapshot(EmotionalState(curiosity=0.8), governed_learning=review)
    )
    review_improver = next(
        item for item in review_plan["slate"] if item["subagent"] == "Improver"
    )
    assert review_improver["action"] == "hold the governed result for creator review"
    assert "retain" not in review_improver["action"]
    assert "revert" not in review_improver["action"]

    fearful = soul.soul.deliberate(
        soul.snapshot(
            EmotionalState(curiosity=0.8, fear=0.5),
            governed_learning=running,
        )
    )
    assert all(item["subagent"] != "Improver" for item in fearful["slate"])

    idle = soul.soul.deliberate(
        soul.snapshot(EmotionalState(curiosity=0.8, fear=0.1))
    )
    idle_improver = next(
        item for item in idle["slate"] if item["subagent"] == "Improver"
    )
    assert idle_improver["action"] == "review one bounded behavior improvement"


def test_coremind_passes_only_a_read_only_governed_signal_to_soul():
    from alpecca.mind import CoreMind

    mind = CoreMind(governed_learning_supplier=_running_status)

    snapshot = mind._soul_snapshot()

    assert snapshot.governed_learning is not None
    assert snapshot.governed_learning.phase == "running"
    assert snapshot.governed_learning.creator_action_required is False
    assert not hasattr(snapshot.governed_learning, "start")

    mind.set_governed_learning_supplier(lambda: {"recovery_ready": False})
    unavailable = mind._soul_snapshot().governed_learning
    assert unavailable is not None
    assert unavailable.available is False
    assert unavailable.evidence_code == "recovery_not_ready"
