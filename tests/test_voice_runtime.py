from __future__ import annotations

import importlib
import inspect
import json
import sys

import pytest

from alpecca import voice_runtime


def _healthy_inputs():
    return {
        "house": {
            "mic_live": True,
            "listening": True,
            "thinking": False,
            "speaking": False,
            "degraded": False,
        },
        "synthesis": {
            "active_route": "f5-tts-worker",
            "routes": {
                "cloud": {"enabled": False, "ready": False},
                "f5": {"enabled": True, "ready": True},
                "kokoro": {"enabled": True, "ready": True},
            },
        },
        "discord": {
            "connected": True,
            "send": {"enabled": True, "ready": True, "active": False},
            "receive": {"enabled": True, "ready": True, "active": True},
            "vad": {"enabled": True, "ready": True, "active": True},
        },
    }


def test_healthy_snapshot_models_house_routes_and_discord_runtime():
    inputs = _healthy_inputs()

    snapshot = voice_runtime.voice_runtime_snapshot(**inputs)

    assert snapshot["schema"] == voice_runtime.SCHEMA
    assert snapshot["state"] == "healthy"
    assert snapshot["ready"] is True
    assert snapshot["house"] == {
        "state": "listening",
        "mic_live": True,
        "listening": True,
        "thinking": False,
        "speaking": False,
        "degraded": False,
        "reasons": [],
    }
    assert snapshot["synthesis"]["selected_route"] == "f5"
    assert snapshot["synthesis"]["routes"]["f5"]["state"] == "active"
    assert snapshot["discord"]["receive"]["state"] == "active"
    assert snapshot["discord"]["vad"]["ready"] is True


@pytest.mark.parametrize("state", ["idle", "listening", "thinking", "speaking"])
def test_house_state_mapping_produces_explicit_activity_fields(state):
    snapshot = voice_runtime.voice_runtime_snapshot(house={"state": state, "mic_live": True})
    house = snapshot["house"]

    assert house["state"] == state
    assert house["listening"] is (state == "listening")
    assert house["thinking"] is (state == "thinking")
    assert house["speaking"] is (state == "speaking")


def test_house_conflicts_are_degraded_with_bounded_reasons():
    snapshot = voice_runtime.voice_runtime_snapshot(
        house={
            "mic_live": False,
            "listening": True,
            "thinking": True,
            "speaking": False,
        }
    )

    assert snapshot["state"] == "degraded"
    assert snapshot["house"]["degraded"] is True
    assert snapshot["house"]["reasons"] == [
        "house-activity-conflict",
        "listening-without-live-mic",
    ]


def test_all_canonical_synthesis_routes_exist_even_without_evidence():
    snapshot = voice_runtime.voice_runtime_snapshot(synthesis={})

    assert tuple(snapshot["synthesis"]["routes"]) == ("cloud", "f5", "kokoro")
    assert all(
        route["state"] == "unknown"
        for route in snapshot["synthesis"]["routes"].values()
    )


@pytest.mark.parametrize("route,alias", [("cloud", "hosted"), ("f5", "f5-tts"), ("kokoro", "kokoro")])
def test_route_aliases_normalize_to_canonical_names(route, alias):
    snapshot = voice_runtime.voice_runtime_snapshot(
        synthesis={
            "active_engine": alias,
            "routes": {route: {"enabled": True, "ready": True}},
        }
    )

    assert snapshot["synthesis"]["selected_route"] == route
    assert snapshot["synthesis"]["routes"][route]["state"] == "active"


def test_active_synthesis_route_without_live_readiness_is_degraded():
    snapshot = voice_runtime.voice_runtime_snapshot(
        synthesis={
            "active_route": "kokoro",
            "routes": {"kokoro": {"enabled": True, "installed": True}},
        }
    )

    kokoro = snapshot["synthesis"]["routes"]["kokoro"]
    assert kokoro["ready"] is None
    assert kokoro["state"] == "degraded"
    assert "active-route-unverified" in kokoro["reasons"]
    assert snapshot["synthesis"]["degraded"] is True


def test_enabled_synthesis_route_confirmed_not_ready_is_degraded():
    snapshot = voice_runtime.voice_runtime_snapshot(
        synthesis={"routes": {"cloud": {"enabled": True, "ready": False}}}
    )

    assert snapshot["synthesis"]["routes"]["cloud"]["state"] == "degraded"
    assert snapshot["synthesis"]["routes"]["cloud"]["reasons"] == [
        "enabled-route-not-ready"
    ]
    assert "cloud-route-degraded" in snapshot["synthesis"]["reasons"]


def test_installed_files_and_model_availability_never_claim_readiness():
    snapshot = voice_runtime.voice_runtime_snapshot(
        synthesis={
            "routes": {
                "f5": {"installed": True, "model_available": True, "path": "model.onnx"},
                "kokoro": {"available": True},
            }
        },
        discord={
            "connected": True,
            "vad": {"installed": True, "model_available": True},
        },
    )

    assert snapshot["synthesis"]["routes"]["f5"]["ready"] is None
    assert snapshot["synthesis"]["routes"]["kokoro"]["ready"] is None
    assert snapshot["discord"]["vad"]["ready"] is None
    assert snapshot["safety"]["readiness_from_installed_files"] is False


def test_discord_runtime_aliases_accept_verified_voice_runtime_state():
    snapshot = voice_runtime.voice_runtime_snapshot(
        discord={
            "connected": True,
            "can_speak": True,
            "speaking": True,
            "can_receive": True,
            "receiving": True,
            "vad": {"ready": True, "active": True},
        }
    )

    discord = snapshot["discord"]
    assert discord["send"]["ready"] is True
    assert discord["send"]["state"] == "active"
    assert discord["receive"]["ready"] is True
    assert discord["receive"]["state"] == "active"
    assert discord["vad"]["state"] == "active"


def test_receive_activity_without_vad_runtime_evidence_is_truthfully_degraded():
    snapshot = voice_runtime.voice_runtime_snapshot(
        discord={
            "connected": True,
            "receive": {"enabled": True, "ready": True, "active": True},
            "vad": {"status": "ready", "model_available": True},
        }
    )

    assert snapshot["discord"]["vad"]["ready"] is None
    assert snapshot["discord"]["degraded"] is True
    assert "discord-vad-unverified-during-receive" in snapshot["discord"]["reasons"]


def test_disabled_discord_paths_are_disabled_not_ready():
    snapshot = voice_runtime.voice_runtime_snapshot(
        discord={
            "connected": False,
            "send": {"enabled": False},
            "receive": {"enabled": False},
            "vad": {"enabled": False},
        }
    )

    assert snapshot["discord"]["state"] == "disconnected"
    assert snapshot["discord"]["send"]["state"] == "disabled"
    assert snapshot["discord"]["receive"]["state"] == "disabled"
    assert snapshot["discord"]["vad"]["state"] == "disabled"
    assert snapshot["discord"]["degraded"] is False


def test_enabled_discord_path_confirmed_not_ready_is_degraded():
    snapshot = voice_runtime.voice_runtime_snapshot(
        discord={
            "connected": True,
            "send": {"enabled": True, "ready": False},
            "receive": {"enabled": False},
            "vad": {"enabled": False},
        }
    )

    assert snapshot["discord"]["send"]["state"] == "degraded"
    assert snapshot["discord"]["send"]["reasons"] == ["send-enabled-not-ready"]
    assert "discord-send-degraded" in snapshot["discord"]["reasons"]


def test_callables_are_invoked_once_and_aggregator_is_deterministic():
    inputs = _healthy_inputs()
    calls = {"house": 0, "synthesis": 0, "discord": 0}

    def provider(name):
        def read():
            calls[name] += 1
            return inputs[name]

        return read

    aggregator = voice_runtime.VoiceRuntimeAggregator(
        house=provider("house"),
        synthesis=provider("synthesis"),
        discord=provider("discord"),
    )
    first = aggregator.snapshot()

    assert calls == {"house": 1, "synthesis": 1, "discord": 1}
    second = voice_runtime.voice_runtime_snapshot(**inputs)
    assert first == second


def test_callable_failures_are_content_free_and_degraded():
    def fail():
        raise RuntimeError("secret provider detail")

    snapshot = voice_runtime.voice_runtime_snapshot(house=fail)
    encoded = json.dumps(snapshot)

    assert snapshot["house"]["state"] == "degraded"
    assert snapshot["house"]["reasons"] == ["house-status-source-error"]
    assert "secret provider detail" not in encoded


@pytest.mark.parametrize("unsafe", [{"raw_audio": b"pcm"}, {"token": "secret"}, {"nested": {"text": "spoken content"}}])
def test_raw_audio_secrets_and_content_are_rejected_without_echo(unsafe):
    snapshot = voice_runtime.voice_runtime_snapshot(discord=unsafe)
    encoded = json.dumps(snapshot, sort_keys=True)

    assert snapshot["discord"]["state"] == "degraded"
    assert snapshot["discord"]["reasons"] == ["discord-unsafe-input-rejected"]
    assert "pcm" not in encoded
    assert "spoken content" not in encoded
    assert '"token"' not in encoded


def test_free_form_reasons_are_redacted_but_reason_codes_survive():
    snapshot = voice_runtime.voice_runtime_snapshot(
        house={
            "state": "degraded",
            "reasons": ["mic-disconnected", "User said private words here"],
        }
    )

    assert snapshot["house"]["reasons"] == [
        "mic-disconnected",
        "invalid-reason-redacted",
    ]
    assert "private words" not in json.dumps(snapshot)


def test_empty_inputs_are_unknown_not_falsely_ready():
    snapshot = voice_runtime.voice_runtime_snapshot()

    assert snapshot["state"] == "degraded"
    assert snapshot["ready"] is False
    assert snapshot["house"]["mic_live"] is None
    assert snapshot["synthesis"]["routes"]["cloud"]["ready"] is None
    assert snapshot["discord"]["send"]["ready"] is None
    assert {reason["code"] for reason in snapshot["reasons"]} == {
        "house-status-unavailable",
        "synthesis-status-unavailable",
        "discord-status-unavailable",
    }


def test_unavailable_routes_with_unknown_surfaces_are_not_ready():
    snapshot = voice_runtime.voice_runtime_snapshot(
        house={},
        synthesis={
            "routes": {
                "cloud": {"enabled": False, "ready": False},
                "f5": {"enabled": None, "ready": False},
                "kokoro": {"enabled": None, "ready": False},
            }
        },
        discord={},
    )

    assert snapshot["state"] == "unknown"
    assert snapshot["ready"] is False


def test_all_paths_explicitly_disabled_produce_disabled_snapshot():
    snapshot = voice_runtime.voice_runtime_snapshot(
        house={
            "state": "idle",
            "mic_live": False,
            "degraded": False,
        },
        synthesis={
            "routes": {
                name: {"enabled": False, "ready": False}
                for name in voice_runtime.CANONICAL_SYNTHESIS_ROUTES
            }
        },
        discord={
            "connected": False,
            "send": {"enabled": False},
            "receive": {"enabled": False},
            "vad": {"enabled": False},
        },
    )

    assert snapshot["state"] == "disabled"
    assert snapshot["ready"] is False


def test_snapshot_is_bounded_json_safe_and_fixed_to_metadata():
    snapshot = voice_runtime.voice_runtime_snapshot(**_healthy_inputs())
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)

    assert len(encoded) <= voice_runtime.MAX_SNAPSHOT_CHARS
    assert snapshot["safety"] == {
        "contains_secrets": False,
        "contains_content": False,
        "contains_raw_audio": False,
        "readiness_from_installed_files": False,
    }


def test_module_reload_imports_no_voice_engines_or_service_modules(monkeypatch):
    blocked = {
        "alpecca.tts",
        "alpecca.open_tts",
        "alpecca.discord_bridge",
        "alpecca.discord_voice",
        "alpecca.silero_vad",
        "faster_whisper",
        "kokoro",
    }
    attempted = []
    real_import = importlib.import_module

    def guarded(name, package=None):
        if name in blocked:
            attempted.append(name)
            raise AssertionError("service-bearing module imported")
        return real_import(name, package)

    before = {name for name in sys.modules if name in blocked}
    monkeypatch.setattr(importlib, "import_module", guarded)

    importlib.reload(voice_runtime)

    assert attempted == []
    assert {name for name in sys.modules if name in blocked} == before


def test_source_contains_no_service_discovery_or_environment_access():
    source = inspect.getsource(voice_runtime)

    assert "find_spec" not in source
    assert "os.environ" not in source
    assert "Path(" not in source
    assert "subprocess" not in source
