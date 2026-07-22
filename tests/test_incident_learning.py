from pathlib import Path

from alpecca import incident_learning
from alpecca.homeostasis import EmotionalState
from alpecca import soul


def _incident(db: Path) -> dict:
    return incident_learning.record_incident(
        source="test_runtime",
        cue="voice-receive-timeout",
        summary="A verified voice receive turn timed out.",
        severity=0.8,
        controllability=0.3,
        prediction_error=0.9,
        db_path=db,
        now=1000.0,
    )


def test_incident_is_persistent_and_exact_cue_scoped(tmp_path):
    db = tmp_path / "incident.db"
    stored = _incident(db)

    matched = incident_learning.assess_cues(
        ["voice-receive-timeout"], db_path=db, now=1000.0
    )
    unrelated = incident_learning.assess_cues(
        ["voice-synthesis-timeout"], db_path=db, now=1000.0
    )

    assert matched.incident_id == stored["id"]
    assert matched.activation > 0.5
    assert unrelated.incident_id is None
    assert unrelated.activation == 0.0


def test_successful_retries_create_safety_learning(tmp_path):
    db = tmp_path / "incident.db"
    stored = _incident(db)
    before = incident_learning.assess_cues(
        [stored["cue"]], db_path=db, now=1000.0
    )

    result = None
    for offset in range(1, 8):
        result = incident_learning.record_outcome(
            stored["id"], safe=True, db_path=db, now=1000.0 + offset
        )
    after = incident_learning.assess_cues(
        [stored["cue"]], db_path=db, now=1010.0
    )

    assert result is not None
    assert result["recovery"] > 0.7
    assert result["status"] == "integrated"
    assert after.incident_id is None
    assert after.activation < before.activation


def test_recurrence_reactivates_a_recovering_incident(tmp_path):
    db = tmp_path / "incident.db"
    stored = _incident(db)
    recovered = incident_learning.record_outcome(
        stored["id"], safe=True, db_path=db, now=1001.0
    )
    repeated = _incident(db)

    assert recovered is not None
    assert repeated["recurrence_count"] == 2
    assert repeated["activation"] > recovered["activation"]
    assert repeated["recovery"] < recovered["recovery"]
    assert repeated["status"] == "active"


def test_incident_signal_moves_unease_without_overriding_bounds():
    state = EmotionalState(fear=0.1)
    moved = state.update_incident_stress(
        {"activation": 0.9, "recovery": 0.0, "confidence": 1.0}
    )
    eased = moved.update_incident_stress(
        {"activation": 0.1, "recovery": 0.9, "confidence": 1.0}
    )

    assert 0.1 < moved.fear <= 1.0
    assert 0.0 <= eased.fear < moved.fear
    assert moved.update_incident_recovery().fear < moved.fear


def test_soul_attends_to_strong_incident_and_integrates_moderate_one():
    strong = soul.soul.deliberate(
        soul.snapshot(
            EmotionalState(fear=0.1),
            incident_signal={"activation": 0.8, "recovery": 0.0},
        )
    )
    moderate = soul.soul.deliberate(
        soul.snapshot(
            EmotionalState(fear=0.1),
            solitude_s=600,
            incident_signal={"activation": 0.35, "recovery": 0.2},
        )
    )

    assert strong["focus"]["subagent"] == "Feeler"
    assert strong["focus"]["rank"] == 1
    actions = {item["action"] for item in moderate["slate"]}
    assert "review what changed since the incident" in actions
    assert "propose one bounded prevention experiment" in actions


def test_prompt_note_labels_caution_as_nonproof():
    note = incident_learning.IncidentSignal(
        incident_id=1,
        cue="x",
        activation=0.7,
        recovery=0.1,
        confidence=1.0,
        status="active",
    ).prompt_note()

    assert "verified prior incident" in note
    assert "not proof" in note
