from __future__ import annotations

import json
import threading

import pytest

from alpecca import video_api, video_companion, video_reactor, video_vision_bridge
from alpecca.selective_soul import ROLE_ORDER, VECTOR_SCHEMA


def _soul():
    return {
        "schema": VECTOR_SCHEMA,
        "order": list(ROLE_ORDER),
        "scores": [0.8, 0.3, 0.2, 0.4, 0.5, 0.3, 0.2],
        "active": [1] * 7,
        "contradiction": False,
        "source": "deterministic",
        "model_calls": 0,
        "independent_transformers": False,
    }


def _companion(*, kind="live", surface="house_hq", adapter_id=None):
    if kind == "file":
        return video_companion.VideoCompanionSession.for_file(
            session_id="session-1",
            source_id="source-1",
            content_sha256="a" * 64,
            duration_seconds=120.0,
            surface=surface,
            adapter_id=adapter_id,
        )
    return video_companion.VideoCompanionSession.for_live(
        session_id="session-1",
        source_id="source-1",
        surface=surface,
        adapter_id=adapter_id,
    )


def _request(
    *,
    timestamp=1.0,
    intent=video_vision_bridge.FrameIntent.AMBIENT,
    surface=video_api.Surface.HOUSE_HQ,
    source_kind=video_api.SourceKind.LIVE,
    event_id="frame-1",
):
    return video_vision_bridge.FrameRequest(
        event_id=event_id,
        session_id="session-1",
        source_id="source-1",
        source_kind=source_kind,
        surface=surface,
        adapter_id="capture-adapter",
        media_timestamp=timestamp,
        content_type="image/jpeg",
        intent=intent,
        question_id="question-1" if intent is video_vision_bridge.FrameIntent.DIRECT_QUESTION else None,
    )


def _event(
    *,
    seq=1,
    timestamp=1.0,
    descriptor="A person enters the room",
    surface=video_api.Surface.HOUSE_HQ,
    source_kind=video_api.SourceKind.LIVE,
):
    return video_api.VisualDescriptorEvent(
        session_id="session-1",
        seq=seq,
        turn_id=f"turn-{seq}",
        media_timestamp=timestamp,
        source_kind=source_kind,
        surface=surface,
        actor=video_api.Actor("vision-adapter", video_api.ActorKind.ADAPTER),
        descriptor=descriptor,
        confidence=0.9,
        labels=("person",),
    )


def _observation(**options):
    return video_vision_bridge.VisionObservation(
        event=_event(**options),
        meaningful=True,
        novelty=video_reactor.Novelty.NOVEL,
    )


def _context(**options):
    return video_reactor.ConversationContext(**options)


def test_direct_user_question_is_p1_and_raw_frame_exists_only_in_handoff():
    bridge = video_vision_bridge.VideoVisionBridge(_companion())
    marker = b"private-frame-marker"
    seen = []

    def dispatch(item):
        seen.append((item.event.metadata["priority"], item.frame_bytes, bridge.status()["handoff_active"]))
        return _observation()

    outcome = bridge.handoff_frame(
        _request(intent=video_vision_bridge.FrameIntent.DIRECT_QUESTION),
        marker,
        dispatch,
        context=_context(mode=video_reactor.ConversationMode.DIRECTED),
        soul_vector=_soul(),
    )

    assert seen == [("P1", marker, True)]
    assert outcome.receipt.priority == "P1"
    assert outcome.timeline_event is not None
    assert outcome.timeline_event.priority == "P1"
    assert marker not in repr(bridge).encode()
    assert marker not in bridge.serialized_snapshot_json().encode()
    assert marker not in json.dumps(bridge.status()).encode()


def test_ambient_live_frame_is_p2_and_bridge_never_claims_p0():
    bridge = video_vision_bridge.VideoVisionBridge(_companion())
    priorities = []

    outcome = bridge.handoff_frame(
        _request(),
        b"ambient-frame",
        lambda item: priorities.append(item.event.metadata["priority"]) or _observation(),
        context=_context(),
        soul_vector=_soul(),
    )

    assert priorities == ["P2"]
    assert outcome.receipt.priority == "P2"
    assert bridge.status()["owns_p0_conversation"] is False
    assert bridge.status()["direct_question_priority"] == "P1"
    assert bridge.status()["ambient_frame_priority"] == "P2"


def test_meaningful_descriptor_is_retained_with_reactor_and_companion_evidence():
    companion = _companion()
    bridge = video_vision_bridge.VideoVisionBridge(companion)

    outcome = bridge.accept_descriptor(
        _observation(),
        source_id="source-1",
        adapter_id="capture-adapter",
        fingerprint="scene-a",
        intent=video_vision_bridge.FrameIntent.AMBIENT,
        context=_context(),
        soul_vector=_soul(),
    )

    assert outcome.receipt.retained is True
    assert outcome.timeline_event is not None
    assert outcome.timeline_event.descriptor == "A person enters the room"
    assert outcome.reaction is not None
    assert outcome.reaction.meaningful_event_retained is True
    assert companion.timeline[0].text == "A person enters the room"


def test_meaningful_event_is_explicitly_deferred_under_backpressure():
    bridge = video_vision_bridge.VideoVisionBridge(_companion())

    outcome = bridge.accept_descriptor(
        _observation(),
        source_id="source-1",
        adapter_id="capture-adapter",
        fingerprint="scene-a",
        intent=video_vision_bridge.FrameIntent.AMBIENT,
        context=_context(technical_backpressure="vision worker unavailable"),
        soul_vector=_soul(),
    )

    assert outcome.receipt.disposition == "deferred"
    assert outcome.receipt.retained is True
    assert outcome.timeline_event is not None
    assert outcome.timeline_event.defer_reason == "technical_backpressure"
    assert bridge.status()["dispositions"]["deferred"] == 1


def test_dispatch_failure_retains_meaningful_frame_as_visible_deferral():
    bridge = video_vision_bridge.VideoVisionBridge(_companion())
    marker = b"failure-frame-marker"

    def fail(_item):
        raise RuntimeError("provider detail must not be retained")

    outcome = bridge.handoff_frame(
        _request(), marker, fail, context=_context(), soul_vector=_soul()
    )

    assert outcome.receipt.disposition == "deferred"
    assert outcome.receipt.reason == "dispatcher_handoff_failed"
    assert outcome.receipt.error_type == "RuntimeError"
    assert "provider detail" not in bridge.serialized_snapshot_json()
    assert marker not in bridge.serialized_snapshot_json().encode()


def test_exact_duplicate_descriptors_compact_into_timestamp_range():
    bridge = video_vision_bridge.VideoVisionBridge(_companion())
    first = _observation(seq=1, timestamp=2.0)
    second = _observation(seq=2, timestamp=5.0)

    bridge.accept_descriptor(
        first,
        source_id="source-1",
        adapter_id="capture-adapter",
        fingerprint="same-scene",
        intent=video_vision_bridge.FrameIntent.AMBIENT,
        context=_context(),
        soul_vector=_soul(),
    )
    compacted = bridge.accept_descriptor(
        second,
        source_id="source-1",
        adapter_id="capture-adapter",
        fingerprint="same-scene",
        intent=video_vision_bridge.FrameIntent.AMBIENT,
        context=_context(),
        soul_vector=_soul(),
    )

    assert len(bridge.timeline) == 1
    assert (bridge.timeline[0].start_seconds, bridge.timeline[0].end_seconds) == (2.0, 5.0)
    assert bridge.timeline[0].compacted_duplicates == 1
    assert compacted.receipt.disposition == "compacted"
    assert compacted.receipt.compacted_into_event_id == "session-1:1"


@pytest.mark.parametrize(
    "second,fingerprint",
    [
        (_observation(seq=2, timestamp=2.0, descriptor="A door opens"), "same-scene"),
        (_observation(seq=2, timestamp=2.0), "different-scene"),
    ],
)
def test_near_duplicates_are_retained_separately(second, fingerprint):
    bridge = video_vision_bridge.VideoVisionBridge(_companion())
    for observation, frame_fingerprint in (
        (_observation(seq=1, timestamp=1.0), "same-scene"),
        (second, fingerprint),
    ):
        bridge.accept_descriptor(
            observation,
            source_id="source-1",
            adapter_id="capture-adapter",
            fingerprint=frame_fingerprint,
            intent=video_vision_bridge.FrameIntent.AMBIENT,
            context=_context(),
            soul_vector=_soul(),
        )

    assert len(bridge.timeline) == 2


def test_distinct_events_have_no_rate_cooldown_or_quota_suppression():
    bridge = video_vision_bridge.VideoVisionBridge(_companion())

    for index in range(40):
        outcome = bridge.accept_descriptor(
            _observation(
                seq=index + 1,
                timestamp=float(index),
                descriptor=f"Meaningful scene {index}",
            ),
            source_id="source-1",
            adapter_id="capture-adapter",
            fingerprint=f"scene-{index}",
            intent=video_vision_bridge.FrameIntent.AMBIENT,
            context=_context(),
            soul_vector=_soul(),
        )
        assert outcome.receipt.retained is True

    assert len(bridge.timeline) == 40
    encoded = bridge.serialized_snapshot_json()
    assert "cooldown" not in encoded and "quota" not in encoded and "rate_limit" not in encoded


@pytest.mark.parametrize(
    "kind,surface,adapter",
    [
        ("live", "house_hq", None),
        ("live", "discord", "discord-video-adapter"),
        ("file", "house_hq", "file-video-adapter"),
    ],
)
def test_source_neutral_house_discord_and_file_adapters(kind, surface, adapter):
    companion = _companion(kind=kind, surface=surface, adapter_id=adapter)
    bridge = video_vision_bridge.VideoVisionBridge(companion)
    source_kind = video_api.SourceKind.FILE if kind == "file" else video_api.SourceKind.LIVE
    api_surface = video_api.Surface(surface)

    outcome = bridge.accept_descriptor(
        _observation(source_kind=source_kind, surface=api_surface),
        source_id="source-1",
        adapter_id=adapter,
        fingerprint="scene-a",
        intent=video_vision_bridge.FrameIntent.AMBIENT,
        context=_context(),
        soul_vector=_soul(),
    )

    assert outcome.timeline_event is not None
    assert outcome.timeline_event.surface == surface
    assert outcome.timeline_event.source_kind == kind
    assert outcome.timeline_event.adapter_id == adapter


def test_json_video_api_descriptor_mapping_uses_same_path():
    bridge = video_vision_bridge.VideoVisionBridge(_companion())
    observation = {
        "event": _event().as_dict(),
        "meaningful": True,
        "novelty": "novel",
        "fingerprint": "scene-a",
    }

    outcome = bridge.accept_descriptor(
        observation,
        source_id="source-1",
        adapter_id="house-camera",
        fingerprint="scene-a",
        intent=video_vision_bridge.FrameIntent.AMBIENT,
        context=_context(),
        soul_vector=_soul(),
    )

    assert outcome.timeline_event is not None
    assert outcome.timeline_event.descriptor == "A person enters the room"


def test_nonmeaningful_descriptor_may_be_ignored_without_timeline_retention():
    bridge = video_vision_bridge.VideoVisionBridge(_companion())
    observation = video_vision_bridge.VisionObservation(
        event=_event(), meaningful=False, novelty=video_reactor.Novelty.UNCHANGED
    )

    outcome = bridge.accept_descriptor(
        observation,
        source_id="source-1",
        adapter_id="capture-adapter",
        fingerprint="unchanged",
        intent=video_vision_bridge.FrameIntent.AMBIENT,
        context=_context(),
        soul_vector=_soul(),
    )

    assert outcome.receipt.disposition == "ignored"
    assert outcome.receipt.retained is False
    assert outcome.timeline_event is None
    assert bridge.timeline == ()


def test_handoffs_are_serialized_across_threads():
    bridge = video_vision_bridge.VideoVisionBridge(_companion())
    first_started = threading.Event()
    release_first = threading.Event()
    order = []

    def dispatch(item):
        order.append(f"start:{item.event.event_id}")
        if item.event.event_id == "frame-1":
            first_started.set()
            assert release_first.wait(timeout=2.0)
        order.append(f"end:{item.event.event_id}")
        seq = 1 if item.event.event_id == "frame-1" else 2
        timestamp = 1.0 if seq == 1 else 2.0
        return _observation(seq=seq, timestamp=timestamp, descriptor=f"scene {seq}")

    outcomes = []
    first = threading.Thread(
        target=lambda: outcomes.append(
            bridge.handoff_frame(
                _request(event_id="frame-1", timestamp=1.0),
                b"one",
                dispatch,
                context=_context(),
                soul_vector=_soul(),
            )
        )
    )
    second = threading.Thread(
        target=lambda: outcomes.append(
            bridge.handoff_frame(
                _request(event_id="frame-2", timestamp=2.0),
                b"two",
                dispatch,
                context=_context(),
                soul_vector=_soul(),
            )
        )
    )
    first.start()
    assert first_started.wait(timeout=2.0)
    second.start()
    release_first.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert not first.is_alive() and not second.is_alive()
    assert order == ["start:frame-1", "end:frame-1", "start:frame-2", "end:frame-2"]
    assert len(outcomes) == 2


def test_snapshot_status_and_timeline_are_json_safe_and_byte_free():
    bridge = video_vision_bridge.VideoVisionBridge(_companion())
    marker = b"never-retain-this-frame"
    bridge.handoff_frame(
        _request(),
        marker,
        lambda _item: _observation(),
        context=_context(),
        soul_vector=_soul(),
    )

    representations = (
        bridge.serialized_snapshot_json().encode(),
        json.dumps(bridge.status(), sort_keys=True).encode(),
        repr(bridge.timeline).encode(),
        repr(bridge.receipts).encode(),
    )
    assert all(marker not in value for value in representations)
    assert bridge.status()["network_calls"] == 0
    assert bridge.status()["model_calls"] == 0
    assert bridge.status()["stores_raw_frames"] is False


def test_invalid_dispatch_result_is_deferred_without_retaining_returned_bytes():
    bridge = video_vision_bridge.VideoVisionBridge(_companion())

    outcome = bridge.handoff_frame(
        _request(),
        b"input-marker",
        lambda _item: b"invalid-output-marker",
        context=_context(),
        soul_vector=_soul(),
    )

    assert outcome.receipt.disposition == "deferred"
    encoded = bridge.serialized_snapshot_json().encode()
    assert b"input-marker" not in encoded
    assert b"invalid-output-marker" not in encoded


def test_mismatched_dispatch_descriptor_is_explicitly_deferred():
    bridge = video_vision_bridge.VideoVisionBridge(_companion())

    outcome = bridge.handoff_frame(
        _request(timestamp=1.0),
        b"frame",
        lambda _item: _observation(timestamp=2.0),
        context=_context(),
        soul_vector=_soul(),
    )

    assert outcome.receipt.disposition == "deferred"
    assert outcome.receipt.reason == "dispatcher_descriptor_mismatch"
    assert outcome.receipt.retained is True
    assert outcome.timeline_event is not None
    assert outcome.timeline_event.defer_reason == "dispatcher_descriptor_mismatch"


def test_frame_contract_rejects_p0_and_arbitrary_priority_inputs():
    fields = set(video_vision_bridge.FrameRequest.__dataclass_fields__)

    assert "priority" not in fields
    assert {priority.value for priority in video_vision_bridge.BridgePriority} == {"P1", "P2"}
    with pytest.raises(TypeError):
        video_vision_bridge.FrameRequest(
            event_id="frame-1",
            session_id="session-1",
            source_id="source-1",
            source_kind=video_api.SourceKind.LIVE,
            priority="P0",  # type: ignore[call-arg]
        )
