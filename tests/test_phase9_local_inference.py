"""Fail-closed target checks for private local-only inference."""
from __future__ import annotations

import pytest

from alpecca.local_inference import (
    model_name_is_local,
    ollama_host_is_loopback,
    verified_local_ollama_target,
)
from alpecca import mind as mind_mod
from alpecca import turn_context
from alpecca import vision


@pytest.mark.parametrize(
    "host",
    (
        "http://127.0.0.1:11434",
        "https://localhost:11434",
        "localhost:11434",
        "http://[::1]:11434",
    ),
)
def test_literal_loopback_ollama_hosts_are_accepted(host: str):
    assert ollama_host_is_loopback(host)


@pytest.mark.parametrize(
    "host",
    (
        "",
        "http://0.0.0.0:11434",
        "http://192.168.1.20:11434",
        "https://ollama.example.test",
        "host.docker.internal:11434",
    ),
)
def test_non_loopback_or_ambiguous_ollama_hosts_are_rejected(host: str):
    assert not ollama_host_is_loopback(host)


def test_qwen_35_local_tag_is_allowed_but_cloud_tags_are_rejected():
    assert model_name_is_local("qwen3.5:9b")
    assert not model_name_is_local("qwen3.5:397b-cloud")
    assert not model_name_is_local("hosted:cloud")
    assert not model_name_is_local(
        "custom-hosted",
        known_cloud_models={"CUSTOM-HOSTED"},
    )


def test_verified_target_requires_both_loopback_and_local_model():
    assert verified_local_ollama_target(
        "http://127.0.0.1:11434", "qwen3.5:9b"
    )
    assert not verified_local_ollama_target(
        "https://ollama.example.test", "qwen3.5:9b"
    )
    assert not verified_local_ollama_target(
        "http://127.0.0.1:11434", "gpt-oss:120b-cloud"
    )


class _ChatClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return {"message": {"content": "verified local answer"}}


def _llm(client: object | None, *, backend: str = "ollama") -> mind_mod._LLM:
    llm = mind_mod._LLM.__new__(mind_mod._LLM)
    llm._backend = backend
    llm._client = client
    llm._hf = object() if backend == "hf" else None
    llm._deep = None
    llm._deep_chain = []
    llm._last_call = {}
    llm.last_chat_model = ""
    return llm


def test_private_generation_uses_only_verified_loopback_ollama(monkeypatch):
    client = _ChatClient()
    llm = _llm(client)
    monkeypatch.setattr(mind_mod, "OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setattr(mind_mod, "OLLAMA_MODEL", "qwen3.5:9b")
    monkeypatch.setattr(mind_mod, "CHAT_CLOUD_MODEL", "hosted:cloud")
    monkeypatch.setattr(mind_mod, "CHAT_ZEROGPU", False)

    result = llm.generate("system", "private input", local_only=True)

    assert result == "verified local answer"
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "qwen3.5:9b"
    assert llm.last_call()["backend"] == "ollama"


@pytest.mark.parametrize(
    ("backend", "host", "model"),
    (
        ("ollama", "https://ollama.example.test", "qwen3.5:9b"),
        ("ollama", "http://127.0.0.1:11434", "qwen3.5:397b-cloud"),
        ("hf", "http://127.0.0.1:11434", "qwen3.5:9b"),
    ),
)
def test_private_generation_falls_back_without_contacting_unverified_target(
    monkeypatch, backend: str, host: str, model: str
):
    client = _ChatClient() if backend == "ollama" else None
    llm = _llm(client, backend=backend)
    monkeypatch.setattr(mind_mod, "OLLAMA_HOST", host)
    monkeypatch.setattr(mind_mod, "OLLAMA_MODEL", model)
    monkeypatch.setattr(mind_mod, "CHAT_CLOUD_MODEL", "hosted:cloud")

    result = llm.generate("system", "private input", local_only=True)

    assert result
    assert client is None or client.calls == []
    assert llm.last_call()["fallback"] is True
    assert "loopback Ollama" in llm.last_call()["error"]


def test_private_history_marker_survives_scope_storage(tmp_path):
    context = turn_context.TurnContext.create(
        "phase9-private", principal="creator", surface="house-hq"
    )
    history = [
        {"role": "user", "content": "microphone transcript", "private_context": True},
        {"role": "assistant", "content": "local reply", "private_context": True},
    ]

    turn_context.save_history(context, history, db_path=tmp_path / "history.db")
    loaded = turn_context.load_history(context, db_path=tmp_path / "history.db")

    assert loaded == history


@pytest.mark.parametrize(
    ("host", "model"),
    (
        ("https://ollama.example.test", "qwen3.5:9b"),
        ("http://127.0.0.1:11434", "qwen3.5:397b-cloud"),
    ),
)
def test_local_vision_rejects_remote_or_cloud_targets_before_client_use(
    monkeypatch, host: str, model: str
):
    monkeypatch.setattr(vision, "OLLAMA_HOST", host)
    monkeypatch.setattr(vision.VisionCfg, "MODEL", model)
    monkeypatch.setattr(vision, "VISION_CLOUD_MODEL", "qwen3.5:397b-cloud")

    assert vision._describe_local(b"private pixels", "describe") is None
