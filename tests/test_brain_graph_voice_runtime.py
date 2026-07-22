from __future__ import annotations

import copy
import json

from alpecca import brain_graph, voice_runtime


def _voice_node(facts):
    snapshot = brain_graph.build_snapshot(facts)
    return next(node for node in snapshot["nodes"] if node["id"] == "alpecca-core:voice")


def _live_snapshot():
    return voice_runtime.voice_runtime_snapshot(
        house={
            "mic_live": True,
            "listening": True,
            "thinking": False,
            "speaking": False,
            "degraded": False,
        },
        synthesis={
            "active_route": "f5",
            "routes": {
                "cloud": {"enabled": False, "ready": False},
                "f5": {"enabled": True, "ready": True},
                "kokoro": {"enabled": True, "ready": True},
            },
        },
        discord={
            "connected": True,
            "send": {"enabled": True, "ready": True, "active": False},
            "receive": {"enabled": True, "ready": True, "active": True},
            "vad": {"enabled": True, "ready": True, "active": True},
        },
    )


def test_missing_voice_runtime_snapshot_is_unknown_even_with_legacy_voice_flags():
    node = _voice_node(
        {
            "runtime": {
                "voice": {
                    "server_voice_ready": True,
                    "original_alpecca_voice_ready": True,
                }
            }
        }
    )

    assert node["state"] == "unknown"
    assert node["progress"] is None
    assert node["evidence"] == ["facts.voice_runtime"]


def test_live_snapshot_exposes_live_from_explicit_runtime_evidence():
    node = _voice_node({"voice_runtime": _live_snapshot()})

    assert node["state"] == "live"
    assert node["progress"] == 100
    assert "runtime evidence verifies" in node["summary"]
    assert node["evidence"] == [
        "voice_runtime.schema=v1",
        "voice_runtime.state=healthy",
        "voice_runtime.house=listening",
        "voice_runtime.synthesis=active",
        "voice_runtime.discord=active",
        "voice_runtime.selected_route=f5",
        "voice_runtime.content_free=true",
    ]


def test_house_activity_can_supply_live_evidence_without_ready_synthesis():
    snapshot = _live_snapshot()
    snapshot["synthesis"]["selected_route"] = None
    for route in snapshot["synthesis"]["routes"].values():
        route.update(state="unknown", enabled=None, ready=None, active=False)
    snapshot["synthesis"]["state"] = "unknown"
    snapshot["discord"]["state"] = "unknown"
    for channel in ("send", "receive", "vad"):
        snapshot["discord"][channel].update(
            state="unknown", enabled=None, ready=None, active=None
        )

    node = _voice_node({"voice_runtime": snapshot})

    assert node["state"] == "live"
    assert "voice_runtime.house=listening" in node["evidence"]


def test_discord_ready_path_can_supply_live_evidence():
    snapshot = _live_snapshot()
    snapshot["house"].update(
        state="idle",
        mic_live=False,
        listening=False,
        thinking=False,
        speaking=False,
    )
    snapshot["synthesis"]["selected_route"] = None
    snapshot["synthesis"]["state"] = "unknown"
    for route in snapshot["synthesis"]["routes"].values():
        route.update(state="unknown", enabled=None, ready=None, active=False)

    node = _voice_node({"voice_runtime": snapshot})

    assert node["state"] == "live"
    assert "voice_runtime.discord=active" in node["evidence"]


def test_degraded_evidence_overrides_other_live_paths_and_hides_reason_content():
    snapshot = _live_snapshot()
    secret_reason = "creator said private content token=do-not-expose"
    snapshot["state"] = "degraded"
    snapshot["ready"] = False
    snapshot["degraded"] = True
    snapshot["house"]["state"] = "degraded"
    snapshot["house"]["degraded"] = True
    snapshot["house"]["reasons"] = [secret_reason]
    snapshot["reasons"] = [{"component": "house", "code": secret_reason}]

    node = _voice_node({"voice_runtime": snapshot})
    encoded = json.dumps(node, sort_keys=True)

    assert node["state"] == "degraded"
    assert node["progress"] == 50
    assert secret_reason not in encoded
    assert "private content" not in encoded
    assert "token=" not in encoded


def test_explicitly_disabled_paths_expose_disabled():
    snapshot = voice_runtime.voice_runtime_snapshot(
        house={"state": "idle", "mic_live": False, "degraded": False},
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

    node = _voice_node({"voice_runtime": snapshot})

    assert node["state"] == "disabled"
    assert node["progress"] == 0


def test_contradictory_top_level_ready_claim_is_rejected():
    snapshot = _live_snapshot()
    snapshot["ready"] = False

    node = _voice_node({"voice_runtime": snapshot})

    assert node["state"] == "unknown"
    assert node["progress"] is None


def test_installed_or_file_presence_without_runtime_readiness_stays_unknown():
    snapshot = _live_snapshot()
    snapshot.update(state="unknown", ready=False, degraded=False)
    snapshot["house"].update(
        state="unknown",
        mic_live=None,
        listening=None,
        thinking=None,
        speaking=None,
        degraded=False,
    )
    snapshot["synthesis"].update(
        state="unknown", selected_route=None, degraded=False
    )
    for route in snapshot["synthesis"]["routes"].values():
        route.update(state="unknown", enabled=None, ready=None, active=False)
        route["installed"] = True
        route["model_path"] = "present.onnx"
    snapshot["discord"].update(state="unknown", connected=None, degraded=False)
    for channel in ("send", "receive", "vad"):
        snapshot["discord"][channel].update(
            state="unknown", enabled=None, ready=None, active=None
        )
        snapshot["discord"][channel]["installed"] = True

    node = _voice_node({"voice_runtime": snapshot})

    assert node["state"] == "unknown"
    assert "installed" not in json.dumps(node)
    assert "model_path" not in json.dumps(node)


def test_wrong_schema_or_unsafe_safety_claims_are_unknown():
    wrong_schema = _live_snapshot()
    wrong_schema["schema"] = "other"
    unsafe = _live_snapshot()
    unsafe["safety"]["contains_secrets"] = True

    assert _voice_node({"voice_runtime": wrong_schema})["state"] == "unknown"
    assert _voice_node({"voice_runtime": unsafe})["state"] == "unknown"


def test_probe_does_not_mutate_supplied_snapshot():
    snapshot = _live_snapshot()
    original = copy.deepcopy(snapshot)

    _voice_node({"voice_runtime": snapshot})

    assert snapshot == original


def test_voice_plugin_description_names_evidence_not_file_presence():
    plugins, errors = brain_graph.discover_plugins()
    core = next(plugin for plugin in plugins if plugin["id"] == "alpecca-core")
    voice = next(node for node in core["nodes"] if node["id"] == "voice")

    assert errors == []
    assert "Evidence-backed" in voice["detail"]
    assert "missing live evidence remains unknown" in voice["detail"]
    assert "installed" not in voice["detail"].casefold()
    assert "file" not in voice["detail"].casefold()
