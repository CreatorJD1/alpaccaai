from __future__ import annotations

from alpecca.homeostasis import EmotionalState
from alpecca import soul


def test_compact_soul_plan_keeps_focus_and_drops_prose_slate():
    snap = soul.snapshot(
        EmotionalState(love=0.8, social_hunger=0.8),
        solitude_s=400,
    )
    plan = soul.soul.compact_plan(snap)

    assert plan["deliberation_mode"] == "compact"
    assert plan["focus"]["category"] == "actions"
    assert "slate" not in plan
    assert "by_category" not in plan
    assert plan["validation_vector"]
    assert all(
        set(item) == {"subagent", "rank", "urgency"}
        for item in plan["validation_vector"]
    )


def test_verbose_soul_plan_remains_available_for_ui_and_review():
    plan = soul.soul.deliberate(soul.snapshot(EmotionalState(fear=0.8)))

    assert plan["deliberation_mode"] == "verbose"
    assert plan["slate"]
    assert plan["slate"][0]["reason"]
    assert len(plan["validation_vector"]) == len(plan["slate"])
