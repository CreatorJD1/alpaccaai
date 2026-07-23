from __future__ import annotations

from types import SimpleNamespace


def test_deep_chain_constructs_rog_worker_before_existing_fallback(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca import rog_worker_client

    worker = object()
    monkeypatch.setattr(mind_mod, "DEEP_BACKEND", "rog-worker,ollama-cloud")
    monkeypatch.setattr(mind_mod, "ROG_WORKER_URL", "https://Jason_HOLYROG:8788")
    monkeypatch.setattr(mind_mod, "OLLAMA_CLOUD_MODEL", "gemma4:cloud")
    monkeypatch.setattr(
        rog_worker_client.RogWorkerClient,
        "from_environment",
        classmethod(lambda cls: worker),
    )

    llm = object.__new__(mind_mod._LLM)
    first = llm._build_deep()

    assert first == ("rog-worker", worker)
    assert llm._deep_chain == [
        ("rog-worker", worker),
        ("ollama-cloud", "gemma4:cloud"),
    ]


def test_rog_worker_deep_generation_returns_only_visible_answer(monkeypatch):
    from alpecca import mind as mind_mod

    seen: dict[str, object] = {}

    class Worker:
        def reason(self, system_prompt, user_prompt, **kwargs):
            seen.update(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                **kwargs,
            )
            return SimpleNamespace(text="<think>private notes</think>Remote conclusion.")

    monkeypatch.setattr(mind_mod, "ROG_WORKER_MODEL", "qwen3.5:9b")
    llm = object.__new__(mind_mod._LLM)

    answer = llm._generate_deep(
        "system",
        "reflect",
        history=[{"role": "assistant", "content": "earlier"}],
        tier=("rog-worker", Worker()),
    )

    assert answer == "Remote conclusion."
    assert seen["model"] == "qwen3.5:9b"
    assert seen["history"] == [{"role": "assistant", "content": "earlier"}]
    assert 160 <= seen["max_tokens"] <= 1024


def test_missing_rog_credential_omits_only_that_link(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca import rog_worker_client

    def unavailable(cls):
        raise rog_worker_client.RogWorkerConfigurationError("credential unavailable")

    monkeypatch.setattr(mind_mod, "DEEP_BACKEND", "rog-worker,ollama-cloud")
    monkeypatch.setattr(mind_mod, "ROG_WORKER_URL", "https://Jason_HOLYROG:8788")
    monkeypatch.setattr(mind_mod, "OLLAMA_CLOUD_MODEL", "gemma4:cloud")
    monkeypatch.setattr(
        rog_worker_client.RogWorkerClient,
        "from_environment",
        classmethod(unavailable),
    )

    llm = object.__new__(mind_mod._LLM)
    first = llm._build_deep()

    assert first == ("ollama-cloud", "gemma4:cloud")
    assert llm._deep_chain == [("ollama-cloud", "gemma4:cloud")]


def test_runtime_model_status_names_compute_worker_truthfully():
    from alpecca.mind import _runtime_model_status_reply

    reply = _runtime_model_status_reply(
        {
            "model": "qwen3.5:9b",
            "backend": "rog-worker",
            "ok": True,
            "fallback": False,
        }
    )

    assert "Jason_HOLYROG" in reply
    assert "non-speaking" in reply


def test_unreachable_worker_uses_short_health_gate_and_cooldown(monkeypatch):
    from alpecca import mind as mind_mod

    class Worker:
        health_calls = 0

        def health(self):
            self.health_calls += 1
            raise TimeoutError("unreachable")

    worker = Worker()
    llm = object.__new__(mind_mod._LLM)
    llm._backend = "ollama"
    llm._client = None
    llm._deep = ("rog-worker", worker)
    llm._deep_chain = [
        ("rog-worker", worker),
        ("ollama-cloud", "gemma4:cloud"),
    ]
    llm._deep_retry_after = {}
    monkeypatch.setattr(llm, "_generate_deep", lambda *args, **kwargs: "hosted fallback")
    monkeypatch.setattr(llm, "_mark_model_use", lambda **kwargs: None)

    assert llm.generate("system", "reflect", tier="deep") == "hosted fallback"
    assert llm.generate("system", "reflect", tier="deep") == "hosted fallback"
    assert worker.health_calls == 1
    assert llm._deep_retry_after["rog-worker"] > 0
