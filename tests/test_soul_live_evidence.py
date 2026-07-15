from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from alpecca import brain_graph
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


def _runtime_vector(**overrides) -> dict:
    value = {
        "schema": "alpecca.soul-perspective-vector.v1",
        "order": list(ROLE_NAMES),
        "scores": [0.2, 0.55, 0.0, 0.8, 0.7, 0.45, 0.42],
        "active": [1, 1, 0, 1, 1, 1, 1],
        "ranks": [4, 2, 0, 3, 3, 4, 4],
        "focus_index": 3,
        "contradiction": True,
        "pressure": "none",
        "escalate": True,
        "source": "deterministic",
        "model_calls": 0,
        "independent_transformers": False,
        "advisory_only": True,
        "focus_stage": "deterministic_arbitration",
    }
    value.update(overrides)
    return value


def _soul_node(facts: dict) -> dict:
    snapshot = brain_graph.build_snapshot(facts)
    return next(node for node in snapshot["nodes"] if node["id"] == "alpecca-core:soul")


def test_compact_mind_evidence_is_live_fixed_shape_and_never_calls_a_model(
    monkeypatch,
) -> None:
    from alpecca import mind as mind_mod
    from alpecca import soul as soul_mod

    instance = mind_mod.CoreMind.__new__(mind_mod.CoreMind)
    snapshot = soul_mod.snapshot(
        EmotionalState(love=0.8, curiosity=0.7, social_hunger=0.8),
        solitude_s=600,
        desires_summary={"by_kind": {"connection": 1}},
    )
    instance._soul_snapshot = lambda: snapshot
    calls: list[bool] = []
    original = soul_mod.soul.deliberate

    def deliberate(snap, *, verbose=True):
        calls.append(verbose)
        return original(snap, verbose=verbose)

    monkeypatch.setattr(soul_mod.soul, "deliberate", deliberate)
    monkeypatch.setattr(mind_mod, "SOUL_LLM", True)
    monkeypatch.setattr(
        mind_mod.choice_mod,
        "constrained_pick",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("compact Soul evidence must not call an LLM tie-break")
        ),
    )

    evidence = instance.soul_perspective_evidence()

    assert calls == [False]
    assert tuple(evidence["order"]) == ROLE_NAMES
    assert len(evidence["scores"]) == len(evidence["active"]) == len(evidence["ranks"]) == 7
    assert all(0.0 <= score <= 1.0 for score in evidence["scores"])
    assert evidence["source"] == "deterministic"
    assert evidence["model_calls"] == 0
    assert evidence["independent_transformers"] is False
    assert evidence["advisory_only"] is True
    assert evidence["focus_stage"] == "deterministic_arbitration"
    serialized = json.dumps(evidence, sort_keys=True)
    assert "reason" not in serialized
    assert "because" not in serialized


def test_mind_drops_malformed_or_model_claiming_vector_instead_of_leaking_it(
    monkeypatch,
) -> None:
    from alpecca import mind as mind_mod
    from alpecca import soul as soul_mod

    instance = mind_mod.CoreMind.__new__(mind_mod.CoreMind)
    snapshot = soul_mod.snapshot(EmotionalState())
    instance._soul_snapshot = lambda: snapshot
    secret_marker = "private-prose-must-not-escape"
    malformed = _runtime_vector(
        model_calls=1,
        secret=secret_marker,
        scores=[99.0] * 7,
    )
    monkeypatch.setattr(
        soul_mod.soul,
        "deliberate",
        lambda _snap, *, verbose=True: {
            "focus": None,
            "validation_vector": [],
            "perspective_vector": malformed,
            "principle": "test",
            "agents": {},
            "deliberation_mode": "compact" if not verbose else "verbose",
        },
    )

    plan = instance.soul_state(details=False)

    assert "perspective_vector" not in plan
    assert secret_marker not in json.dumps(plan)


def test_brain_garden_soul_probe_exposes_only_bounded_numeric_evidence() -> None:
    secret_marker = "private-prose-must-not-reach-brain-garden"
    vector = _runtime_vector(secret=secret_marker, action="send private text")

    node = _soul_node({
        "soul_agent_count": 7,
        "soul_perspective_vector": vector,
    })
    serialized = json.dumps(node, sort_keys=True)

    assert node["state"] == "degraded"
    assert "model_calls=0" in node["summary"]
    assert "not seven independent transformer" in node["summary"]
    assert "does not choose actions" in node["summary"]
    assert "soul.perspective_vector.model_calls=0" in node["evidence"]
    assert "soul.perspective_vector.independent_transformers=false" in node["evidence"]
    assert "soul.perspective_vector.advisory_only=true" in node["evidence"]
    assert any(item.startswith("soul.perspective_vector.scores=") for item in node["evidence"])
    assert secret_marker not in serialized
    assert "send private text" not in serialized
    assert sum(len(item) for item in node["evidence"]) < 1_200


def test_brain_garden_rejects_unbounded_vector_and_exposes_no_unknown_fields() -> None:
    secret_marker = "invalid-vector-private-field"
    vector = _runtime_vector(
        scores=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 10**10_000]
    )
    vector["secret"] = secret_marker

    node = _soul_node({
        "soul_agent_count": 7,
        "soul_perspective_vector": vector,
    })
    serialized = json.dumps(node, sort_keys=True)

    assert node["state"] == "degraded"
    assert node["evidence"] == ["alpecca/soul.py", "soul_agent_count=7"]
    assert secret_marker not in serialized


def test_server_brain_graph_and_introspection_publish_same_advisory_vector(
    monkeypatch,
) -> None:
    import server as server_mod
    from alpecca import vrm as vrm_mod

    vector = _runtime_vector()
    monkeypatch.setattr(server_mod.mind, "soul_perspective_evidence", lambda: vector)
    monkeypatch.setattr(server_mod, "_runtime_status", lambda **_kwargs: {})
    monkeypatch.setattr(server_mod.mindpage_mod, "stats", lambda: {})
    monkeypatch.setattr(server_mod.memory_store, "count", lambda: 0)
    monkeypatch.setattr(server_mod, "_sense_status", lambda: {})
    monkeypatch.setattr(server_mod, "_discord_bot_token", lambda: "")
    monkeypatch.setattr(server_mod.mind.llm, "model_for", lambda _tier: "local-model")
    monkeypatch.setattr(vrm_mod, "manifest", lambda: {})

    def no_bridge(*_args, **_kwargs):
        raise OSError("test bridge offline")

    monkeypatch.setattr(server_mod.socket, "create_connection", no_bridge)
    captured: dict = {}

    def capture(facts):
        captured.update(facts)
        return {"ok": True}

    monkeypatch.setattr(server_mod.brain_graph_mod, "build_snapshot", capture)

    assert server_mod.brain_graph() == {"ok": True}
    assert captured["soul_perspective_vector"] == vector

    report = SimpleNamespace(
        narrate=lambda: "grounded",
        state={},
        mood="settled",
        trends={},
        reason="measured",
        memory_count=0,
        senses_active=False,
    )
    monkeypatch.setattr(server_mod.mind, "introspect", lambda: report)
    payload = server_mod.introspect()

    assert payload["soul_perspective_vector"] == vector


def test_core_manifest_states_the_vector_is_advisory_and_not_transformer_instances() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "alpecca" / "brain_plugins" / "alpecca_core.json").read_text(
            encoding="utf-8"
        )
    )
    soul_node = next(item for item in manifest["nodes"] if item["id"] == "soul")

    assert "bounded advisory vector" in soul_node["detail"]
    assert "model_calls=0" in soul_node["detail"]
    assert "not independent transformer instances" in soul_node["detail"]
