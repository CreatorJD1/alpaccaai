"""Focused fail-closed tests for computer-use vision routing."""
from __future__ import annotations

import sys
import types

import pytest

from alpecca import computer


class _Client:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise ConnectionError("local Ollama is unavailable")
        return {"message": {"content": '{"action":"done","summary":"finished"}'}}


def _install_ollama(monkeypatch, client: _Client, constructions: list[dict]) -> None:
    def make_client(**kwargs):
        constructions.append(kwargs)
        return client

    monkeypatch.setitem(sys.modules, "ollama", types.SimpleNamespace(Client=make_client))


@pytest.mark.parametrize(
    ("host", "model", "known_cloud_model"),
    (
        ("https://ollama.example.test", "qwen3-vl:7b", ""),
        ("http://127.0.0.1:11434", "qwen3-vl:cloud", ""),
        ("http://127.0.0.1:11434", "hosted-vision", "hosted-vision"),
    ),
)
def test_rejected_target_prevents_capture_and_client_construction(
    monkeypatch, host: str, model: str, known_cloud_model: str
):
    captures: list[bool] = []
    constructions: list[dict] = []
    client = _Client()
    _install_ollama(monkeypatch, client, constructions)
    monkeypatch.setattr(computer, "available", lambda: True)
    monkeypatch.setattr(computer, "OLLAMA_HOST", host)
    monkeypatch.setattr(computer.VisionCfg, "MODEL", model)
    monkeypatch.setattr(computer, "VISION_CLOUD_MODEL", known_cloud_model)
    monkeypatch.setattr(
        computer,
        "screenshot_for_model",
        lambda: (captures.append(True) or b"private screen", 1.0),
    )

    result = computer.run_task(
        "inspect the screen", confirm=lambda _action: True, status=lambda _msg: None
    )

    assert result.ok is False
    assert "verified loopback Ollama" in result.error
    assert captures == []
    assert constructions == []
    assert client.calls == []


def test_target_is_reverified_before_each_screenshot(monkeypatch):
    decisions = iter((True, False))
    checks: list[bool] = []
    captures: list[bool] = []
    constructions: list[dict] = []
    client = _Client()
    _install_ollama(monkeypatch, client, constructions)
    monkeypatch.setattr(computer, "available", lambda: True)

    def verify(*_args, **_kwargs):
        checks.append(True)
        return next(decisions)

    monkeypatch.setattr(computer, "verified_local_ollama_target", verify)
    monkeypatch.setattr(
        computer,
        "screenshot_for_model",
        lambda: (captures.append(True) or b"private screen", 1.0),
    )

    result = computer.run_task(
        "inspect the screen", confirm=lambda _action: True, status=lambda _msg: None
    )

    assert result.ok is False
    assert len(checks) == 2
    assert len(constructions) == 1
    assert captures == []
    assert client.calls == []


def test_target_is_reverified_after_capture_before_model_call(monkeypatch):
    decisions = iter((True, True, False))
    checks: list[bool] = []
    constructions: list[dict] = []
    client = _Client()
    _install_ollama(monkeypatch, client, constructions)
    monkeypatch.setattr(computer, "available", lambda: True)

    def verify(*_args, **_kwargs):
        checks.append(True)
        return next(decisions)

    monkeypatch.setattr(computer, "verified_local_ollama_target", verify)
    monkeypatch.setattr(computer, "screenshot_for_model", lambda: (b"private screen", 1.0))

    result = computer.run_task(
        "inspect the screen", confirm=lambda _action: True, status=lambda _msg: None
    )

    assert result.ok is False
    assert len(checks) == 3
    assert len(constructions) == 1
    assert client.calls == []


def test_local_model_failure_is_reported_without_another_model_path(monkeypatch):
    constructions: list[dict] = []
    client = _Client(fail=True)
    _install_ollama(monkeypatch, client, constructions)
    monkeypatch.setattr(computer, "available", lambda: True)
    monkeypatch.setattr(computer, "OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setattr(computer.VisionCfg, "MODEL", "qwen3-vl:7b")
    monkeypatch.setattr(computer, "VISION_CLOUD_MODEL", "qwen3-vl:cloud")
    monkeypatch.setattr(computer, "screenshot_for_model", lambda: (b"private screen", 1.0))

    result = computer.run_task(
        "inspect the screen", confirm=lambda _action: True, status=lambda _msg: None
    )

    assert result.ok is False
    assert "vision step failed" in result.error
    assert constructions == [
        {
            "host": "http://127.0.0.1:11434",
            "follow_redirects": False,
            "trust_env": False,
        }
    ]
    assert len(client.calls) == 1
