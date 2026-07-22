from __future__ import annotations

import json

from alpecca import tts
import server


def _sensitive_tts_status() -> dict[str, object]:
    return {
        "active_engine": "f5-tts-worker",
        "last_error": "private spoken content",
        "engines": {
            "cloud": {
                "configured": True,
                "state": "unverified",
                "ready": None,
                "endpoint_host": "private.example.test",
                "endpoint_path": "/private/synthesize",
                "authorization": "Bearer private-token",
            },
            "open_tts": {
                "ready": True,
                "url": "http://private.example.test/voice",
                "worker": {
                    "enabled": True,
                    "ready": True,
                    "model_path": "C:/private/model.bin",
                },
            },
            "kokoro": True,
            "kokoro_status": {
                "installed": True,
                "ready": False,
                "path": "C:/private/kokoro",
            },
        },
    }


def test_runtime_status_wires_one_sanitized_live_tts_snapshot(monkeypatch):
    raw_tts = _sensitive_tts_status()
    voice_reads = 0

    def voice_state(_state):
        nonlocal voice_reads
        voice_reads += 1
        return raw_tts

    monkeypatch.setattr(tts, "voice_state", voice_state)
    monkeypatch.setattr(server.mind.llm, "model_for", lambda _tier: "test-model")
    monkeypatch.setattr(server.mind.llm, "deep_online", lambda: False)
    monkeypatch.setattr(server.mind.llm, "last_call", lambda: {})
    monkeypatch.setattr(server, "COLAB_URL", "")
    monkeypatch.setattr(server, "_sense_status", lambda: {})
    monkeypatch.setattr(server, "_optional_work_telemetry", lambda: {})
    monkeypatch.setattr(server._host_resource_sampler, "snapshot", lambda: {})
    monkeypatch.setattr(server.mind, "temporal_memory_status", lambda: {})
    monkeypatch.setattr(server.mind, "soul_runtime_status", lambda: {})
    monkeypatch.setattr(
        server.runtime_status_mod,
        "build_runtime_status",
        lambda **values: {"legacy_voice": values["voice"]},
    )

    status = server._runtime_status(check_models=False)
    voice = status["research_runtime"]["voice"]

    assert voice_reads == 1
    assert status["legacy_voice"] is raw_tts
    assert voice["schema"] == "alpecca.voice-runtime.v1"
    assert voice["house"]["state"] == "unknown"
    assert voice["discord"]["state"] == "unknown"
    assert voice["synthesis"]["selected_route"] == "f5"
    assert voice["synthesis"]["routes"]["f5"] == {
        "state": "active",
        "enabled": True,
        "ready": True,
        "active": True,
        "reasons": [],
    }

    encoded = json.dumps(voice, sort_keys=True)
    for private_value in (
        "private.example.test",
        "/private/synthesize",
        "private-token",
        "private spoken content",
        "C:/private/model.bin",
        "C:/private/kokoro",
    ):
        assert private_value not in encoded
    assert "endpoint_host" not in encoded
    assert "endpoint_path" not in encoded
    assert "authorization" not in encoded
    assert "model_path" not in encoded


def test_tts_adapter_requires_runtime_readiness_not_installation_or_configuration():
    voice = server._voice_runtime_status(_sensitive_tts_status())
    routes = voice["synthesis"]["routes"]

    assert routes["cloud"]["enabled"] is True
    assert routes["cloud"]["ready"] is None
    assert routes["kokoro"]["enabled"] is None
    assert routes["kokoro"]["ready"] is False
    assert voice["safety"]["readiness_from_installed_files"] is False


def test_cloud_adapter_uses_finalized_explicit_readiness_and_states():
    cases = (
        ("unverified", None, None),
        ("unverified", True, None),
        ("ready", True, True),
        ("degraded", False, False),
        ("degraded", True, False),
        ("unavailable", False, False),
        # Explicit readiness wins if state and evidence briefly cross in flight.
        ("ready", False, False),
    )
    for state, explicit_ready, expected in cases:
        cloud = {"configured": True, "state": state, "ready": explicit_ready}
        synthesis = server._tts_synthesis_runtime({"engines": {"cloud": cloud}})
        assert synthesis["routes"]["cloud"]["ready"] is expected


def test_cloud_adapter_keeps_legacy_terminal_states_fail_closed():
    succeeded = server._tts_synthesis_runtime(
        {"engines": {"cloud": {"configured": True, "state": "succeeded"}}}
    )
    failed = server._tts_synthesis_runtime(
        {"engines": {"cloud": {"configured": True, "state": "failed"}}}
    )

    assert succeeded["routes"]["cloud"]["ready"] is True
    assert failed["routes"]["cloud"]["ready"] is False


def test_direct_house_and_discord_runtime_evidence_is_preserved_conservatively():
    voice = server._voice_runtime_status(
        {
            "active_engine": "cloud",
            "engines": {
                "cloud": {"configured": True, "state": "ready", "ready": True},
            },
        },
        house=lambda: {
            "state": "listening",
            "mic_live": True,
            "degraded": False,
        },
        discord={
            "connected": True,
            "send": {"enabled": True, "ready": True},
            "receive": {"enabled": True, "ready": True},
            "vad": {"enabled": True, "ready": True},
        },
    )

    assert voice["house"]["state"] == "listening"
    assert voice["house"]["mic_live"] is True
    assert voice["discord"]["state"] == "ready"
    assert voice["synthesis"]["selected_route"] == "cloud"
    assert voice["synthesis"]["routes"]["cloud"]["state"] == "active"
    assert voice["degraded"] is False


def test_brain_graph_receives_the_exact_strict_runtime_snapshot(monkeypatch):
    strict_voice = server._voice_runtime_status(
        {
            "active_engine": "cloud",
            "engines": {
                "cloud": {"configured": True, "state": "ready", "ready": True},
            },
        }
    )
    runtime = {"research_runtime": {"voice": strict_voice}}
    captured = {}

    monkeypatch.setattr(server, "_runtime_status", lambda check_models=True: runtime)
    monkeypatch.setattr(server.mindpage_mod, "stats", lambda: {})
    monkeypatch.setattr(server.mind, "soul_perspective_evidence", lambda: {})
    monkeypatch.setattr(server.mind, "soul_runtime_status", lambda: {})
    monkeypatch.setattr(server.mind, "temporal_memory_status", lambda: {})
    monkeypatch.setattr(server.mind.llm, "model_for", lambda _tier: "test-model")
    monkeypatch.setattr(server.memory_store, "count", lambda: 0)
    monkeypatch.setattr(server, "_sense_status", lambda: {})
    monkeypatch.setattr(server, "_discord_bot_token", lambda: "")
    monkeypatch.setattr(server, "DISCORD_CLIENT_ID", "")
    monkeypatch.setattr(server, "_collect_pagefile_live_evidence", lambda: {})
    monkeypatch.setattr(
        server.socket,
        "create_connection",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
    )

    def build_snapshot(facts):
        captured.update(facts)
        return {"ok": True}

    monkeypatch.setattr(server.brain_graph_mod, "build_snapshot", build_snapshot)

    assert server.brain_graph() == {"ok": True}
    assert captured["voice_runtime"] is strict_voice
