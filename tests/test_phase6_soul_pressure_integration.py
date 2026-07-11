import pytest

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
HIGH_DELTAS = {
    "Feeler": 0.05,
    "Carer": 0.03,
    "Reflector": 0.12,
    "Improver": -0.08,
}
OVERFLOW_DELTAS = {
    "Feeler": 0.10,
    "Carer": 0.05,
    "Reflector": 0.20,
    "Improver": -0.16,
}


def _active_snapshot(memory_pressure=None, host_pressure=None):
    state = EmotionalState(
        love=0.95,
        compassion=0.7,
        fear=0.1,
        energy=0.8,
        curiosity=0.7,
        social_hunger=0.1,
    )
    return soul.snapshot(
        state,
        solitude_s=600,
        person_fatigue=0.7,
        trial_running=True,
        memory_pressure=memory_pressure,
        host_pressure=host_pressure,
    )


def _slate(plan):
    return {item["subagent"]: item for item in plan["slate"]}


def _without_urgency(item):
    return {key: value for key, value in item.items() if key != "urgency"}


def test_registry_and_default_deliberation_remain_exactly_role_preserving():
    assert tuple(spec.name for spec in soul.SUBAGENT_SPECS) == ROLE_NAMES
    assert len(soul.SUBAGENTS) == 7

    missing = soul.soul.deliberate(_active_snapshot())
    empty = soul.soul.deliberate(_active_snapshot({}))
    low = soul.soul.deliberate(_active_snapshot({
        "score": 0.89,
        "severity": "normal",
        "overflow": False,
        "evidence": {"context_fill": 0.89},
    }))

    assert missing == empty == low
    assert tuple(missing["agents"]) == ROLE_NAMES
    assert set(_slate(missing)) == {
        "Feeler", "Expressor", "Carer", "Wanderer", "Reflector", "Improver",
    }


@pytest.mark.parametrize(
    ("signal", "expected_deltas"),
    [
        (
            {
                "score": 0.92,
                "severity": "high",
                "overflow": False,
                "evidence": {"context_fill": 0.92},
            },
            HIGH_DELTAS,
        ),
        (
            {
                "score": 1.0,
                "severity": "critical",
                "overflow": True,
                "evidence": {"overflow": True},
            },
            OVERFLOW_DELTAS,
        ),
    ],
)
def test_pressure_changes_only_named_role_scores_with_bounded_deltas(
    signal, expected_deltas
):
    baseline = _slate(soul.soul.deliberate(_active_snapshot()))
    adjusted = _slate(soul.soul.deliberate(_active_snapshot(signal)))

    assert set(adjusted) == set(baseline)
    for name, original in baseline.items():
        current = adjusted[name]
        assert _without_urgency(current) == _without_urgency(original)
        assert 0.0 <= current["urgency"] <= 1.0
        if name in expected_deltas:
            expected = round(
                max(0.0, min(1.0, original["urgency"] + expected_deltas[name])),
                6,
            )
            assert current["urgency"] == pytest.approx(expected)
            assert abs(current["urgency"] - original["urgency"]) <= 0.2
        else:
            assert current["urgency"] == original["urgency"]


def test_host_pressure_is_observable_but_leaves_soul_deliberation_unchanged():
    host_pressure = {
        "score": 1.0,
        "severity": "critical",
        "defer_optional_work": True,
        "evidence": {"commit_pressure": 1.0},
    }

    baseline = soul.soul.deliberate(_active_snapshot())
    host_only_snapshot = _active_snapshot(host_pressure=host_pressure)
    host_only = soul.soul.deliberate(host_only_snapshot)

    assert host_only_snapshot.memory_pressure is None
    assert host_only_snapshot.host_pressure is host_pressure
    assert host_only_snapshot.as_dict()["host_pressure"] == host_pressure
    assert host_only["slate"] == baseline["slate"]
    assert host_only["focus"] == baseline["focus"]
    assert [item["urgency"] for item in host_only["slate"]] == [
        item["urgency"] for item in baseline["slate"]
    ]
    assert [item["action"] for item in host_only["slate"]] == [
        item["action"] for item in baseline["slate"]
    ]


def test_memory_pressure_retains_urgency_effects_when_host_pressure_is_present():
    memory_pressure = {
        "score": 0.92,
        "severity": "high",
        "overflow": False,
        "evidence": {"context_fill": 0.92},
    }
    host_pressure = {
        "score": 1.0,
        "severity": "critical",
        "defer_optional_work": True,
    }

    baseline = _slate(soul.soul.deliberate(_active_snapshot(host_pressure=host_pressure)))
    adjusted = _slate(soul.soul.deliberate(_active_snapshot(
        memory_pressure=memory_pressure,
        host_pressure=host_pressure,
    )))

    for name, original in baseline.items():
        current = adjusted[name]
        assert _without_urgency(current) == _without_urgency(original)
        expected = round(
            max(0.0, min(1.0, original["urgency"] + HIGH_DELTAS.get(name, 0.0))),
            6,
        )
        assert current["urgency"] == pytest.approx(expected)


def test_pressure_cannot_create_a_role_intention_or_new_action():
    baseline = soul.soul.deliberate(soul.snapshot(EmotionalState()))
    pressured = soul.soul.deliberate(soul.snapshot(
        EmotionalState(),
        memory_pressure={
            "score": 1.0,
            "severity": "critical",
            "overflow": True,
            "evidence": {"overflow": True},
        },
    ))

    assert pressured["slate"] == baseline["slate"]
    assert [item["subagent"] for item in pressured["slate"]] == ["Expressor"]
    assert all(item["action"] != "consolidate working memory" for item in pressured["slate"])


def test_severity_requires_evidence_when_no_numeric_or_overflow_signal_exists():
    baseline = soul.soul.deliberate(_active_snapshot())
    unsupported = soul.soul.deliberate(_active_snapshot({"severity": "high"}))
    evidenced = soul.soul.deliberate(_active_snapshot({
        "severity": "high",
        "evidence": {"source": "mindpage-ledger"},
    }))

    assert unsupported == baseline
    assert _slate(evidenced)["Reflector"]["urgency"] == pytest.approx(
        round(_slate(baseline)["Reflector"]["urgency"] + HIGH_DELTAS["Reflector"], 6)
    )


def test_snapshot_preserves_compact_numeric_severity_and_evidence():
    signal = {
        "score": 0.94,
        "severity": "high",
        "overflow": False,
        "evidence": {"context_fill": 0.94},
    }

    snap = _active_snapshot(signal)

    assert snap.memory_pressure is signal
    assert snap.as_dict()["memory_pressure"] == signal
