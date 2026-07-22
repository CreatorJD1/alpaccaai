"""Focused Phase 6 live Mindpage-to-Soul pressure wiring coverage."""
from __future__ import annotations

from copy import deepcopy
import time

from alpecca.homeostasis import EmotionalState


def _active_state() -> EmotionalState:
    return EmotionalState(
        love=0.95,
        compassion=0.7,
        fear=0.1,
        energy=0.8,
        curiosity=0.7,
        social_hunger=0.1,
    )


def _bare_mind(monkeypatch, ledger, host_resource_snapshot_supplier=None):
    from alpecca import mind as mind_mod

    mind = mind_mod.CoreMind.__new__(mind_mod.CoreMind)
    mind.state = _active_state()
    mind._last_signals = None
    mind._last_user_ts = time.time() - 600.0
    mind._prev_obs = None
    mind._location = "parlor"
    mind._last_mindpage = ledger
    mind._histories = {}
    mind._host_resource_snapshot_supplier = host_resource_snapshot_supplier
    monkeypatch.setattr(mind_mod.desires_mod, "summary", lambda: {})
    monkeypatch.setattr(mind_mod.selfmod, "history", lambda **_kwargs: [])
    monkeypatch.setattr(mind_mod, "SOUL_LLM", False)
    return mind, mind_mod


def _core_mind(monkeypatch, generate):
    """Build chat-capable CoreMind without shared database or external effects."""
    from alpecca import mind as mind_mod

    class FakeLLM:
        online = True

        def generate(self, *args, **kwargs):
            return generate(*args, **kwargs)

        def last_call(self):
            return {
                "requested_tier": "reason",
                "used_tier": "reason",
                "backend": "test",
                "model": "fake",
                "ok": True,
                "fallback": False,
                "error": "",
            }

        def is_cloud(self):
            return False

    class FakePortraitWorker:
        def request(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(mind_mod, "_LLM", FakeLLM)
    monkeypatch.setattr(mind_mod, "PortraitWorker", FakePortraitWorker)
    monkeypatch.setattr(mind_mod.state_store, "init_db", lambda: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "init_db", lambda: None)
    monkeypatch.setattr(mind_mod.turn_context_mod, "ensure_history_schema", lambda: None)
    monkeypatch.setattr(mind_mod.state_store, "load_state", _active_state)
    monkeypatch.setattr(mind_mod.state_store, "load_appearance_seed", lambda: 7)
    monkeypatch.setattr(mind_mod.state_store, "load_location", lambda: "parlor")
    monkeypatch.setattr(mind_mod.state_store, "save_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.state_store, "save_location", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.state_store, "mood_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.cognition_mod, "set_intent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "current_intent", lambda: {"name": "waiting"})
    monkeypatch.setattr(mind_mod.cognition_mod, "record_observation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "record_chat_turn", lambda *_args, **_kwargs: 91)
    monkeypatch.setattr(
        mind_mod.cognition_mod,
        "mark_observation_remembered",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(mind_mod.memory_store, "count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(mind_mod.memory_store, "recent", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.memory_store, "recall", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        mind_mod.memory_store,
        "remember_with_id",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(mind_mod.mindpage_mod, "prefault_pages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.journal_mod, "open_questions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.people_mod, "who_prompt", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mind_mod.core_mem, "prompt_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mind_mod.desires_mod, "summary", lambda: {})
    monkeypatch.setattr(mind_mod.selfmod, "history", lambda **_kwargs: [])
    monkeypatch.setattr(
        mind_mod.speech_mod,
        "spoken_performance_text",
        lambda text, _state: text,
    )
    monkeypatch.setattr(mind_mod.speech_mod, "speech_cues", lambda _state: {})
    monkeypatch.setattr(mind_mod.turn_context_mod, "load_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.turn_context_mod, "save_history", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod, "SOUL_LLM", False)

    mind = mind_mod.CoreMind()
    monkeypatch.setattr(mind, "try_go_to_room", lambda _message: False)
    monkeypatch.setattr(mind, "_tool_schema", lambda *_args, **_kwargs: None)
    return mind, mind_mod


def _ledger(fill: float = 0.95) -> dict:
    return {
        "enabled": True,
        "source": "exact_request",
        "context_fill": fill,
        "overflow": False,
        "unshrinkable": False,
        "unsummarized_eviction_backlog": 2,
        "disk_fill": 0.2,
        "disk_over_budget": False,
    }


def _slate(plan: dict) -> dict[str, dict]:
    return {item["subagent"]: item for item in plan["slate"]}


def test_latest_ledger_becomes_compact_soul_signal_and_changes_only_urgency(monkeypatch):
    latest = _ledger()
    original = deepcopy(latest)
    pressured, mind_mod = _bare_mind(monkeypatch, latest)
    baseline, _ = _bare_mind(monkeypatch, None)
    baseline.mindpage_state = lambda: {}

    snapshot = pressured._soul_snapshot()
    pressured_plan = pressured.soul_state()
    baseline_plan = baseline.soul_state()

    assert latest == original
    assert snapshot.memory_pressure["context_fill"] == 0.95
    assert snapshot.memory_pressure["pressure_score"] == 0.95
    assert snapshot.memory_pressure["severity"] == "high"
    assert snapshot.memory_pressure["evidence"]["context_fill"] == 0.95
    assert snapshot.memory_pressure["signal_vector"]["overall"] == 0.95
    assert len(snapshot.memory_pressure["intention_hints"]) <= 4
    pressured_slate = _slate(pressured_plan)
    baseline_slate = _slate(baseline_plan)
    assert set(pressured_slate) == set(baseline_slate)
    assert pressured_slate["Reflector"]["action"] == baseline_slate["Reflector"]["action"]
    assert pressured_slate["Reflector"]["urgency"] > baseline_slate["Reflector"]["urgency"]
    assert tuple(spec.name for spec in mind_mod.soul_mod.SUBAGENT_SPECS) == (
        "Feeler", "Expressor", "Carer", "Doer", "Wanderer", "Reflector", "Improver",
    )


def test_latest_ledger_wins_over_stale_fallback_snapshot(monkeypatch):
    mind, _mind_mod = _bare_mind(monkeypatch, _ledger(0.93))
    mind.mindpage_state = lambda: {"context_fill": 0.1, "source": "stale"}

    snapshot = mind._soul_snapshot()

    assert snapshot.memory_pressure["context_fill"] == 0.93
    assert snapshot.memory_pressure["pressure_score"] == 0.93


def test_missing_or_invalid_latest_telemetry_preserves_existing_snapshot(monkeypatch):
    fallback = {"context_fill": 0.12, "source": "history_estimate"}
    missing, _mind_mod = _bare_mind(monkeypatch, None)
    missing.mindpage_state = lambda: fallback

    assert missing._phase6_pressure_bundle() is None
    assert missing._soul_snapshot().memory_pressure is fallback

    invalid_ledger = {
        "enabled": True,
        "source": "exact_request",
        "context_fill": "invalid",
    }
    invalid, _ = _bare_mind(monkeypatch, invalid_ledger)
    invalid.mindpage_state = lambda: dict(invalid_ledger)

    assert invalid._phase6_pressure_bundle() is None
    assert invalid._soul_snapshot().memory_pressure == invalid_ledger


def test_chat_returns_bounded_operational_note_without_prompt_injection(monkeypatch):
    calls = []
    captured = {}

    def generate(system_prompt, *_args, **_kwargs):
        calls.append(True)
        captured["system_prompt"] = system_prompt
        return "A grounded direct reply."

    mind, mind_mod = _core_mind(monkeypatch, generate)
    latest = _ledger(0.96)
    monkeypatch.setattr(
        mind_mod.mindpage_mod,
        "pressure_snapshot",
        lambda *args, **kwargs: dict(latest),
    )

    result = mind.chat("Hello Alpecca.")

    metadata = result["memory_pressure"]
    assert metadata["available"] is True
    assert metadata["source"] == "mindpage_latest_ledger"
    assert metadata["ledger_source"] == "exact_request"
    assert metadata["severity"] == "high"
    assert metadata["context_fill"] == 0.96
    assert metadata["pressure_score"] == 0.96
    assert 0 < len(metadata["note"]) <= 240
    assert "Context utilization is 96%." in metadata["note"]
    assert metadata["note"] not in captured["system_prompt"]
    assert mind._last_mindpage == latest
    assert calls == [True]


def test_disabled_latest_telemetry_adds_no_pressure_note(monkeypatch):
    mind, _mind_mod = _bare_mind(monkeypatch, {
        "enabled": False,
        "source": "disabled",
        "context_fill": 0.0,
    })

    assert mind._phase6_pressure_bundle() is None


def _host_snapshot(assessment: dict, *, state: str = "ready") -> dict:
    return {
        "state": state,
        "timestamp": 1_700_000_000.25,
        "age": 0.5,
        "assessment": assessment,
        "advisory": {"action": "must_not_reach_soul"},
    }


def test_host_assessment_projects_to_separate_soul_evidence(monkeypatch):
    assessment = {
        "pressure": 0.91,
        "severity": "high",
        "reasons": [
            {"code": "ram_pressure"},
            {"code": "commit_pressure"},
        ],
    }
    mind, _mind_mod = _bare_mind(
        monkeypatch,
        _ledger(0.93),
        lambda: _host_snapshot(assessment),
    )

    snapshot = mind._soul_snapshot()

    assert snapshot.host_pressure == {
        "source": "host_resource_snapshot",
        "sample_state": "ready",
        "timestamp": 1_700_000_000.25,
        "age": 0.5,
        "severity": "high",
        "pressure": 0.91,
        "evidence_codes": ["ram_pressure", "commit_pressure"],
    }
    assert "advisory" not in snapshot.host_pressure
    assert "action" not in snapshot.host_pressure
    assert snapshot.memory_pressure["context_fill"] == 0.93
    assert snapshot.memory_pressure["pressure_score"] == 0.93


def test_unknown_invalid_or_failing_host_samples_never_fabricate_low_pressure(monkeypatch):
    unknown = _host_snapshot({
        "pressure": 0.0,
        "severity": "unknown",
        "reasons": [],
    })
    invalid = _host_snapshot({"pressure": "not-a-number", "severity": "high"})

    def failing_supplier():
        raise RuntimeError("host sampler unavailable")

    for supplier in (lambda: unknown, lambda: invalid, failing_supplier):
        mind, _mind_mod = _bare_mind(monkeypatch, _ledger(), supplier)

        assert mind._soul_snapshot().host_pressure is None


def test_host_assessment_projection_does_not_mutate_source(monkeypatch):
    assessment = {
        "pressure": 0.88,
        "severity": "high",
        "reasons": [{"code": "ram_pressure", "observed": {"used": 88}}],
    }
    source = _host_snapshot(assessment)
    before = deepcopy(source)
    mind, _mind_mod = _bare_mind(monkeypatch, _ledger(), lambda: source)

    mind._soul_snapshot()

    assert source == before
    assert assessment == before["assessment"]


def test_host_snapshot_supplier_is_called_once_per_soul_snapshot(monkeypatch):
    calls = []
    assessment = {"pressure": 0.72, "severity": "elevated", "reasons": []}

    def supplier():
        calls.append(True)
        return _host_snapshot(assessment)

    mind, _mind_mod = _bare_mind(monkeypatch, _ledger(), supplier)

    assert mind._soul_snapshot().host_pressure["pressure"] == 0.72
    assert calls == [True]


def test_host_pressure_leaves_mindpage_payload_unchanged(monkeypatch):
    ledger = _ledger(0.94)
    baseline, _mind_mod = _bare_mind(monkeypatch, deepcopy(ledger))
    with_host, _mind_mod = _bare_mind(
        monkeypatch,
        deepcopy(ledger),
        lambda: _host_snapshot({
            "pressure": 0.95,
            "severity": "critical",
            "reasons": [{"code": "commit_pressure"}],
        }),
    )

    baseline_snapshot = baseline._soul_snapshot()
    host_snapshot = with_host._soul_snapshot()

    assert host_snapshot.memory_pressure == baseline_snapshot.memory_pressure
    assert with_host._phase6_pressure_bundle() == baseline._phase6_pressure_bundle()
    assert "host_pressure" not in host_snapshot.memory_pressure


def test_perception_records_one_measured_host_warning_and_recovery(monkeypatch):
    from alpecca.sensory import Observation

    current = _host_snapshot({
        "pressure": 0.93,
        "severity": "high",
        "reasons": [{"code": "commit_pressure"}],
    })
    mind, mind_mod = _core_mind(monkeypatch, lambda *_args, **_kwargs: "unused")
    mind.set_host_resource_supplier(lambda: current)
    observations = []
    monkeypatch.setattr(
        mind_mod.cognition_mod,
        "record_observation",
        lambda item: observations.append(item),
    )

    mind.perceive(Observation())
    first_fear = mind.state.fear
    mind.perceive(Observation())

    assert first_fear > 0.4
    host_events = [item for item in observations if item.source == "host_resources"]
    assert len(host_events) == 1
    assert host_events[0].metadata["automatic_response"] == "optional_work_deferred"

    current["assessment"] = {"pressure": 0.1, "severity": "normal", "reasons": []}
    mind.perceive(Observation())

    host_events = [item for item in observations if item.source == "host_resources"]
    assert len(host_events) == 2
    assert "recovered" in host_events[-1].content
    assert mind.state.fear < first_fear
