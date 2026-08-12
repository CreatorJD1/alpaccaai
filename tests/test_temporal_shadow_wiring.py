from __future__ import annotations

from pathlib import Path

from alpecca import memory as memory_store
from alpecca import mind as mind_mod
from alpecca import turn_context as turn_context_mod
from alpecca.temporal_memory import TemporalMemoryStore
from alpecca.temporal_runtime import TemporalRuntime


def _legacy_memory() -> list[dict]:
    return [{
        "id": 41,
        "kind": "episodic",
        "content": "The legacy cobalt-orchard memory remains authoritative.",
        "salience": 0.8,
        "recall_score": 0.9,
        "recall_similarity": 0.0,
        "recall_recency": 0.7,
        "recall_method": "keyword",
    }]


def _prepare_chat(monkeypatch, *, legacy: list[dict]):
    mind = mind_mod.CoreMind()
    model_calls: list[str] = []

    def fake_recall(query, **kwargs):
        return legacy

    def fake_generate(system_prompt, user_msg, history=None, **kwargs):
        model_calls.append(user_msg)
        mind.llm._last_call = {
            "requested_tier": "reason",
            "used_tier": "reason",
            "backend": "test",
            "model": "fake",
            "ok": True,
            "fallback": False,
            "error": "",
        }
        return "I remember the cobalt orchard from the legacy memory path."

    monkeypatch.setattr(memory_store, "recall", fake_recall)
    monkeypatch.setattr(mind_mod, "MINDPAGE", False)
    mind.llm.generate = fake_generate
    return mind, model_calls


def _creator_turn() -> turn_context_mod.TurnContext:
    return turn_context_mod.TurnContext.create(
        "temporal-shadow-wiring",
        principal="creator",
        surface="house",
        privacy_scope="creator-personal",
    )


def test_production_recall_increments_shadow_counter_without_extra_model_call(
    tmp_path: Path,
    monkeypatch,
) -> None:
    legacy = _legacy_memory()
    original = [dict(item) for item in legacy]
    mind, model_calls = _prepare_chat(monkeypatch, legacy=legacy)
    runtime = TemporalRuntime(TemporalMemoryStore(tmp_path / "shadow.db"))
    mind._temporal_runtime = runtime

    result = mind.chat(
        "What do you remember about the cobalt orchard?",
        turn=_creator_turn(),
    )

    assert runtime.status().shadow_comparisons == 1
    assert model_calls == ["What do you remember about the cobalt orchard?"]
    assert legacy == original
    assert result["memories_used"] == [original[0]["content"]]


def test_shadow_failure_and_mutation_cannot_change_chat_recall(
    monkeypatch,
) -> None:
    legacy = _legacy_memory()
    original = [dict(item) for item in legacy]
    mind, model_calls = _prepare_chat(monkeypatch, legacy=legacy)

    class FailingShadowRuntime:
        calls = 0

        def compare_shadow_recall(self, shadow_input, **kwargs):
            self.calls += 1
            shadow_input[0]["content"] = "mutated shadow-only content"
            raise RuntimeError("shadow evaluation unavailable")

    runtime = FailingShadowRuntime()
    mind._temporal_runtime = runtime

    result = mind.chat(
        "What do you remember about the cobalt orchard?",
        turn=_creator_turn(),
    )

    assert runtime.calls == 1
    assert model_calls == ["What do you remember about the cobalt orchard?"]
    assert legacy == original
    assert result["memories_used"] == [original[0]["content"]]
