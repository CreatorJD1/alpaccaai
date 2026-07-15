from __future__ import annotations

import json

from alpecca import brain_graph


def _facts() -> dict:
    return {
        "runtime": {"models": {"chat_ready": True, "reason": "qwen3.5:9b"}, "voice": {"server_voice_ready": True}},
        "memory_count": 42,
        "soul_agent_count": 7,
        "senses": {"screen_sight": True, "computer_use": False},
        "discord_configured": True,
        "discord_running": False,
        "mindpage_enabled": True,
        "memory_pressure": 0.25,
        "mindscape_configured": True,
        "vrm_available": True,
    }


def test_builtin_graph_is_qualified_and_evidence_backed():
    snapshot = brain_graph.build_snapshot(_facts())
    nodes = {node["id"]: node for node in snapshot["nodes"]}

    assert snapshot["accuracy"] == "live-probe-or-explicit-unknown"
    assert nodes["alpecca-core:alpecca"]["state"] == "healthy"
    assert nodes["alpecca-core:memory"]["summary"].startswith("42 persistent")
    assert nodes["alpecca-core:soul"]["state"] == "degraded"
    assert "not seven independent transformer" in nodes["alpecca-core:soul"]["summary"]
    assert nodes["alpecca-core:mindpage"]["parent"] == "alpecca-core:memory"
    assert nodes["alpecca-core:p2"]["state"] == "healthy"
    assert nodes["alpecca-core:p4"]["state"] == "healthy"
    assert nodes["alpecca-core:p5"]["state"] == "healthy"
    assert nodes["alpecca-core:p7"]["state"] == "unfinished"
    assert "blocks phase completion" in nodes["alpecca-core:p7"]["summary"]
    assert nodes["alpecca-core:p14"]["progress"] == 35
    assert all(node["evidence"] for node in snapshot["nodes"])


def test_local_plugin_auto_discovery_uses_only_allowlisted_probes(tmp_path):
    plugin = {
        "schemaVersion": 1,
        "id": "creator-view",
        "name": "Creator View",
        "nodes": [{"id": "server", "label": "Server", "probe": "server"}],
    }
    (tmp_path / "creator.json").write_text(json.dumps(plugin), encoding="utf-8")

    plugins, errors = brain_graph.discover_plugins(tmp_path)

    assert not errors
    assert {item["id"] for item in plugins} == {"alpecca-core", "creator-view"}


def test_invalid_plugin_is_rejected_without_breaking_the_core_graph(tmp_path):
    plugin = {
        "schemaVersion": 1,
        "id": "unsafe",
        "nodes": [{"id": "exec", "label": "Execute", "probe": "python.eval"}],
    }
    (tmp_path / "unsafe.json").write_text(json.dumps(plugin), encoding="utf-8")

    snapshot = brain_graph.build_snapshot(_facts(), extra_dir=tmp_path)

    assert snapshot["pluginErrors"]
    assert all(node["plugin"] == "alpecca-core" for node in snapshot["nodes"])


def test_unavailable_live_fact_is_unknown_not_healthy():
    snapshot = brain_graph.build_snapshot({})
    nodes = {node["id"]: node for node in snapshot["nodes"]}

    assert nodes["alpecca-core:memory"]["state"] == "unknown"
    assert nodes["alpecca-core:embodiment"]["state"] == "unknown"
    assert nodes["alpecca-core:soul"]["state"] == "unfinished"
