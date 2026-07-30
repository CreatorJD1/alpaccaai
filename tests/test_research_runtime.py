from __future__ import annotations

from alpecca import brain_graph
from alpecca import research_runtime


def test_defaults_are_explicit_unavailable_evidence() -> None:
    facts = research_runtime.brain_graph_facts()

    assert facts["video_companion"] == {"available": False}
    assert facts["vision_dispatch"] == {"available": False}
    assert facts["speaker_worker"]["status"] == "unavailable"
    assert facts["face_worker"]["status"] == "unavailable"
    assert facts["asr_dispatch"]["capabilities"]["faster-whisper"] == {
        "configured": False,
        "ready": False,
    }
    nodes = {
        node["id"].split(":", 1)[1]: node
        for node in brain_graph.build_snapshot(facts)["nodes"]
    }
    for node_id in (
        "video-companion",
        "asr-dispatch",
        "speaker-worker",
        "face-worker",
        "event-driven-vision",
    ):
        assert nodes[node_id]["state"] == "unfinished"


def test_registered_provider_replaces_only_its_bounded_runtime_snapshot() -> None:
    research_runtime.register_status_provider(
        "vision_dispatch",
        lambda: {
            "available": True,
            "serialized": True,
            "raw_frame_persisted": False,
            "max_queued": 8,
            "queued_count": 0,
            "retained_frame_count": 0,
        },
    )
    try:
        facts = research_runtime.brain_graph_facts()
    finally:
        research_runtime.clear_status_provider("vision_dispatch")

    assert facts["vision_dispatch"]["available"] is True
    assert facts["video_companion"] == {"available": False}
