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


def test_hosted_selective_soul_receives_only_the_bounded_numeric_slate(
    monkeypatch,
) -> None:
    from alpecca import cognition as cognition_mod
    from alpecca import mind as mind_mod
    from alpecca import soul as soul_mod

    captured: dict[str, object] = {}

    def generate(system_prompt: str, user_msg: str, **kwargs) -> str:
        captured.update({
            "system_prompt": system_prompt,
            "user_msg": user_msg,
            "kwargs": kwargs,
        })
        return json.dumps({
            "selected_role": "Feeler",
            "reason": "The bounded high-affect slate keeps welfare first.",
        })

    instance = mind_mod.CoreMind.__new__(mind_mod.CoreMind)
    instance._soul_snapshot = lambda: soul_mod.snapshot(
        EmotionalState(fear=0.85),
        solitude_s=300,
    )
    instance._location = "studio"
    instance._last_soul_runtime = {}
    instance.llm = SimpleNamespace(
        online=True,
        is_cloud=lambda: True,
        model_for=lambda _tier: "hosted-test-model",
        local_inference_available=lambda _model: False,
        generate=generate,
    )
    monkeypatch.setattr(mind_mod, "SOUL_LLM", True)
    monkeypatch.setattr(mind_mod, "SOUL_LLM_REMOTE", True)
    monkeypatch.setattr(cognition_mod, "record_observation", lambda _item: None)

    plan = instance.soul_state(
        details=False,
        textual_deliberation=True,
    )

    runtime = plan["soul_runtime"]
    assert runtime["outcome"] == "textual_selection"
    assert runtime["callback_invoked"] is True
    assert runtime["selected_role"] == "Feeler"
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["tier"] == "fast"
    assert kwargs["local_only"] is False
    payload = json.loads(str(captured["user_msg"]))
    assert set(payload) == {
        "deterministic_role",
        "response_contract",
        "roles",
        "trigger",
    }
    assert len(payload["roles"]) == 7
    assert all(set(row) == {"active", "role", "score"} for row in payload["roles"])
    serialized = json.dumps(payload, sort_keys=True).casefold()
    assert "memory" not in serialized
    assert "conversation" not in serialized
    assert "situation" not in serialized
    assert "snapshot" not in serialized


def test_hosted_selective_soul_attempts_configured_route_without_racy_online_precheck(
    monkeypatch,
) -> None:
    from alpecca import cognition as cognition_mod
    from alpecca import mind as mind_mod
    from alpecca import soul as soul_mod

    calls: list[dict[str, object]] = []

    def generate(_system_prompt: str, _user_msg: str, **kwargs) -> str:
        calls.append(dict(kwargs))
        return json.dumps({
            "selected_role": "Feeler",
            "reason": "The bounded high-affect slate keeps welfare first.",
        })

    instance = mind_mod.CoreMind.__new__(mind_mod.CoreMind)
    instance._soul_snapshot = lambda: soul_mod.snapshot(
        EmotionalState(fear=0.85),
        solitude_s=300,
    )
    instance._location = "studio"
    instance._last_soul_runtime = {}
    instance.llm = SimpleNamespace(
        online=False,
        is_cloud=lambda: True,
        model_for=lambda _tier: "hosted-test-model",
        local_inference_available=lambda _model: False,
        generate=generate,
    )
    monkeypatch.setattr(mind_mod, "SOUL_LLM", True)
    monkeypatch.setattr(mind_mod, "SOUL_LLM_REMOTE", False)
    monkeypatch.setenv("ALPECCA_SOUL_LLM_REMOTE", "1")
    monkeypatch.setattr(cognition_mod, "record_observation", lambda _item: None)

    plan = instance.soul_state(details=False, textual_deliberation=True)

    assert plan["soul_runtime"]["outcome"] == "textual_selection"
    assert plan["soul_runtime"]["callback_invoked"] is True
    assert calls == [{"tier": "fast", "local_only": False}]


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
    assert "Seven deterministic perspectives are live" in node["summary"]
    assert "ROG shadow runtime is not ready" in node["summary"]
    assert "soul.perspective_vector.model_calls=0" in node["evidence"]
    assert "soul.perspective_vector.independent_transformers=false" in node["evidence"]
    assert "soul.perspective_vector.advisory_only=true" in node["evidence"]
    assert "soul.hyfuser.distinct_transformer_heads=7" in node["evidence"]
    assert "soul.hyfuser.ready=false" in node["evidence"]
    assert any(item.startswith("soul.perspective_vector.scores=") for item in node["evidence"])
    assert secret_marker not in serialized
    assert "send private text" not in serialized
    assert sum(len(item) for item in node["evidence"]) < 1_200


def test_brain_garden_reports_ready_transformer_heads_as_shadow_only() -> None:
    node = _soul_node({
        "soul_agent_count": 7,
        "soul_perspective_vector": _runtime_vector(),
        "hyfuser_soul": {"configured": True, "ready": True},
    })

    assert node["state"] == "degraded"
    assert "seven distinct ROG transformer heads are live" in node["summary"]
    assert "cannot choose actions" in node["summary"]
    assert "soul.hyfuser.configured=true" in node["evidence"]
    assert "soul.hyfuser.ready=true" in node["evidence"]
    assert "soul.hyfuser.shadow_only=true" in node["evidence"]


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
        host_pressure=None,
    )
    monkeypatch.setattr(server_mod.mind, "introspect", lambda: report)
    payload = server_mod.introspect()

    assert payload["soul_perspective_vector"] == vector


def test_core_manifest_states_transformer_heads_are_shared_and_shadow_only() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "alpecca" / "brain_plugins" / "alpecca_core.json").read_text(
            encoding="utf-8"
        )
    )
    soul_node = next(item for item in manifest["nodes"] if item["id"] == "soul")

    assert "deterministic arbitration" in soul_node["detail"]
    assert "seven distinct ROG transformer heads" in soul_node["detail"]
    assert "one shared HyFusER-style multimodal representation" in soul_node["detail"]
    assert "shadow mode" in soul_node["detail"]
