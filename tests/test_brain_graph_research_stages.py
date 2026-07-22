from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpecca import brain_graph


RESEARCH_IDS = (
    "temporal-memory-shadow",
    "selective-soul-runtime",
    "video-companion",
    "asr-dispatch",
    "speaker-worker",
    "face-worker",
    "event-driven-vision",
)


def _nodes(facts: dict) -> dict[str, dict]:
    snapshot = brain_graph.build_snapshot(facts)
    assert not snapshot["pluginErrors"]
    return {node["id"].split(":", 1)[1]: node for node in snapshot["nodes"]}


def _valid_facts() -> dict:
    return {
        "temporal_memory": {
            "available": True,
            "authority": "sqlite_mindpage",
            "mode": "shadow",
            "pending_observations": 2,
            "observations_processed": 12,
            "facts_derived": 7,
            "shadow_comparisons": 4,
        },
        "soul_runtime": {
            "schema": "alpecca.soul-runtime-decision.v1",
            "roles": list(brain_graph.SOUL_PERSPECTIVE_ORDER),
            "outcome": "textual_selection",
            "callback_invoked": True,
            "advisory_only": True,
        },
        "video_companion": {
            "available": True,
            "status": "active",
            "source_kind": "file",
            "timeline_entries": 18,
            "deferred_entries": 1,
            "raw_media_retained": False,
        },
        "asr_dispatch": {
            "schema": "alpecca.asr-dispatch-status.v1",
            "selection": {
                "schema": "alpecca.asr-selection.v1",
                "selected_backend": "faster-whisper",
            },
            "capabilities": {
                "faster-whisper": {"configured": True, "ready": True}
            },
        },
        "speaker_worker": {
            "purpose": "familiarity-only",
            "may_authenticate": False,
            "may_grant_authority": False,
            "device": "cpu",
            "backend": "deterministic-audio",
            "sherpa_onnx_available": False,
            "enrolled_profiles": 2,
            "max_audio_seconds": 15.0,
        },
        "face_worker": {
            "status": "ready",
            "purpose": "familiarity-only",
            "device": "cpu",
            "may_authenticate": False,
            "may_authorize_creator": False,
            "may_grant_authority": False,
            "image_retained": False,
            "max_image_bytes": 1_000_000,
            "max_image_pixels": 2_000_000,
        },
        "vision_dispatch": {
            "available": True,
            "serialized": True,
            "raw_frame_persisted": False,
            "max_queued": 8,
            "queued_count": 2,
            "retained_frame_count": 2,
        },
    }


def test_core_plugin_declares_all_research_runtime_nodes() -> None:
    path = Path(brain_graph.__file__).with_name("brain_plugins") / "alpecca_core.json"
    plugin = json.loads(path.read_text(encoding="utf-8"))
    definitions = {item["id"]: item for item in plugin["nodes"]}

    assert set(RESEARCH_IDS) <= definitions.keys()
    assert definitions["temporal-memory-shadow"]["parent"] == "memory"
    assert definitions["selective-soul-runtime"]["parent"] == "soul"
    for node_id in RESEARCH_IDS:
        assert definitions[node_id]["probe"] in brain_graph.PROBES


def test_absent_or_file_claim_facts_never_report_research_nodes_healthy() -> None:
    nodes = _nodes({"files_exist": {node_id: True for node_id in RESEARCH_IDS}})

    for node_id in RESEARCH_IDS:
        assert nodes[node_id]["state"] == "unknown"
        assert nodes[node_id]["progress"] is None
        assert nodes[node_id]["evidence"]


def test_valid_bounded_runtime_facts_report_each_stage_healthy() -> None:
    nodes = _nodes(_valid_facts())

    for node_id in RESEARCH_IDS:
        assert nodes[node_id]["state"] == "healthy"
        assert nodes[node_id]["progress"] == 100

    temporal = nodes["temporal-memory-shadow"]
    assert "legacy SQLite Mindpage recall remains authoritative" in temporal["summary"]
    assert "temporal_memory.mode=shadow" in temporal["evidence"]
    soul = nodes["selective-soul-runtime"]
    assert "does not choose or execute actions" in soul["summary"]
    assert "soul_runtime.advisory_only=true" in soul["evidence"]


@pytest.mark.parametrize(
    ("node_id", "fact_key", "field", "unsafe_value"),
    [
        ("temporal-memory-shadow", "temporal_memory", "mode", "authoritative"),
        ("selective-soul-runtime", "soul_runtime", "advisory_only", False),
        ("video-companion", "video_companion", "raw_media_retained", True),
        ("asr-dispatch", "asr_dispatch", "schema", "wrong"),
        ("speaker-worker", "speaker_worker", "may_authenticate", True),
        ("face-worker", "face_worker", "image_retained", True),
        ("event-driven-vision", "vision_dispatch", "serialized", False),
    ],
)
def test_invalid_or_unsafe_stage_facts_never_report_healthy(
    node_id: str,
    fact_key: str,
    field: str,
    unsafe_value: object,
) -> None:
    facts = _valid_facts()
    facts[fact_key][field] = unsafe_value

    assert _nodes(facts)[node_id]["state"] != "healthy"


def test_explicit_unavailable_and_partial_states_are_not_promoted() -> None:
    facts = _valid_facts()
    facts["temporal_memory"] = {
        "available": False,
        "authority": "sqlite_mindpage",
    }
    facts["video_companion"] = {"available": False}
    facts["face_worker"]["status"] = "unavailable"
    facts["vision_dispatch"] = {"available": False}
    facts["asr_dispatch"]["capabilities"]["faster-whisper"]["ready"] = False
    facts["soul_runtime"]["outcome"] = "callback_failed"

    nodes = _nodes(facts)

    assert nodes["temporal-memory-shadow"]["state"] == "unfinished"
    assert nodes["video-companion"]["state"] == "unfinished"
    assert nodes["face-worker"]["state"] == "unfinished"
    assert nodes["event-driven-vision"]["state"] == "unfinished"
    assert nodes["asr-dispatch"]["state"] == "unfinished"
    assert nodes["selective-soul-runtime"]["state"] == "degraded"


def test_probe_evidence_projects_only_bounded_fields() -> None:
    secret = "private transcript and image description"
    facts = _valid_facts()
    for value in facts.values():
        value["untrusted_detail"] = secret
    nodes = _nodes(facts)

    for node_id in RESEARCH_IDS:
        encoded = json.dumps(nodes[node_id], sort_keys=True)
        assert secret not in encoded


def test_boolean_or_excessive_counters_are_unknown_not_healthy() -> None:
    facts = _valid_facts()
    facts["temporal_memory"]["facts_derived"] = True
    facts["vision_dispatch"]["queued_count"] = 1_000_001
    facts["speaker_worker"]["enrolled_profiles"] = -1

    nodes = _nodes(facts)

    assert nodes["temporal-memory-shadow"]["state"] == "unknown"
    assert nodes["event-driven-vision"]["state"] == "unknown"
    assert nodes["speaker-worker"]["state"] == "unknown"
