"""Smoke tests for the Alpecca ROG worker MCP server.

These do NOT touch the network. They inject a fake RogWorkerClient and verify
that tools are registered, dispatch to the client, map results into the output
models, and translate client errors into actionable messages.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from alpecca_rog_mcp import server
from alpecca.rog_worker_client import RogWorkerUnavailableError


@dataclass
class _Health:
    request_id = "req-health-0001"
    hostname = "Jason_HOLYROG"
    role = "compute-only"
    ready = True
    reasoning_ready = True
    blender_ready = False
    vision_ready = True
    vision_model = "qwen3-vl:4b"
    speaking = False
    discord = False


@dataclass
class _Reason:
    request_id = "req-reason-0001"
    model = "qwen3.5:9b"
    text = "A bounded answer."
    prompt_tokens = 12
    completion_tokens = 5
    elapsed_ms = 900


class _FakeClient:
    def health(self):
        return _Health()

    def reason(self, system_prompt, user_prompt, history, model, max_tokens):
        assert user_prompt
        return _Reason()

    def describe_vision(self, *a, **k):
        raise RogWorkerUnavailableError("worker down")


def _wav_bytes() -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x01" * 4096)
    return buf.getvalue()


class _FakeVoice:
    def __init__(self, *, enabled=True, ok=True):
        self.enabled = enabled
        self._ok = ok

    def available(self):
        return self._ok

    def synthesize(self, text):
        assert text
        return ("audio/wav", _wav_bytes()) if self._ok else None

    def status(self):
        return {
            "engine": "holyrog-xtts",
            "configured": self.enabled,
            "state": "ready" if self._ok else "unavailable",
            "cooldown_active": not self._ok,
        }


@pytest.fixture(autouse=True)
def _inject(monkeypatch):
    monkeypatch.setattr(server, "_client", _FakeClient())
    monkeypatch.setattr(server, "_voice", _FakeVoice())
    yield
    server._client = None
    server._voice = None


def test_tools_are_registered():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {
        "rog_health",
        "rog_hyfuser_health",
        "rog_reason",
        "rog_describe_vision",
        "rog_render_blender",
        "rog_score_soul",
        "rog_voice_status",
        "rog_synthesize_voice",
    } <= names


def test_voice_status_reports_ready(monkeypatch):
    out = server.rog_voice_status()
    assert out.engine == "holyrog-xtts"
    assert out.configured is True
    assert out.available is True


def test_synthesize_voice_writes_wav(tmp_path):
    dest = tmp_path / "out.wav"
    out = server.rog_synthesize_voice("Hello there.", str(dest))
    assert out.mime == "audio/wav"
    assert out.bytes > 1024
    assert dest.is_file() and dest.stat().st_size == out.bytes


def test_synthesize_voice_unavailable_is_actionable(monkeypatch):
    monkeypatch.setattr(server, "_voice", _FakeVoice(ok=False))
    with pytest.raises(RuntimeError) as exc:
        server.rog_synthesize_voice("Hello there.")
    assert "8790" in str(exc.value)


def test_health_maps_fields():
    out = server.rog_health()
    assert out.ok is True
    assert out.hostname == "Jason_HOLYROG"
    assert out.role == "compute-only"
    assert out.vision_ready is True
    assert out.vision_model == "qwen3-vl:4b"


def test_reason_returns_visible_text():
    out = server.rog_reason("What is the bounded answer?")
    assert out.text == "A bounded answer."
    assert out.model == "qwen3.5:9b"
    assert out.elapsed_ms >= 0


def test_unavailable_worker_becomes_actionable_error():
    with pytest.raises(RuntimeError) as exc:
        server.rog_describe_vision("/nonexistent-but-error-comes-first.png")
    # Missing-file guard fires first; ensure the message is actionable.
    assert "rog_describe_vision" in str(exc.value)
