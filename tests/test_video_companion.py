from __future__ import annotations

import json

import pytest

from alpecca.video_companion import (
    SchedulerPriority,
    SessionStatus,
    SourceKind,
    VideoCompanionError,
    VideoCompanionSession,
)


DIGEST = "a" * 64


def _file(**options):
    return VideoCompanionSession.for_file(
        session_id="session-file-1",
        source_id="asset-42",
        content_sha256=DIGEST,
        duration_seconds=120.0,
        label="Creator-selected local video",
        **options,
    )


def test_file_progress_is_resumable_and_completes_at_full_duration() -> None:
    session = _file()
    session.advance_progress(42.5)
    restored = VideoCompanionSession.from_snapshot(session.snapshot())

    assert restored.source.kind is SourceKind.FILE
    assert restored.progress.processed_until == 42.5
    assert restored.progress.fraction == pytest.approx(42.5 / 120.0)

    progress = restored.advance_progress(500.0)
    assert progress.processed_until == 120.0
    assert progress.fraction == 1.0
    assert progress.complete
    assert restored.status is SessionStatus.COMPLETED


def test_live_session_tracks_live_edge_and_restores_without_fixed_progress() -> None:
    session = VideoCompanionSession.for_live(
        session_id="live-session-1",
        source_id="capture-device-1",
    )
    session.advance_progress(3_600.25)
    restored = VideoCompanionSession.from_snapshot(session.snapshot())

    assert restored.source.kind is SourceKind.LIVE
    assert restored.progress.processed_until == 3_600.25
    assert restored.progress.duration_seconds is None
    assert restored.progress.fraction is None
    assert not restored.progress.complete
    assert restored.status is SessionStatus.ACTIVE
    assert restored.source.surface == "house_hq"
    assert restored.source.adapter_id is None


def test_source_provenance_is_opaque_and_never_accepts_raw_media() -> None:
    with pytest.raises(VideoCompanionError, match="must not contain a URL"):
        VideoCompanionSession.for_live(
            session_id="live-1",
            source_id="https://camera.example/live",
        )
    with pytest.raises(VideoCompanionError, match="raw media bytes"):
        VideoCompanionSession.for_live(
            session_id="live-1",
            source_id=b"raw-video",  # type: ignore[arg-type]
        )

    snapshot = VideoCompanionSession.for_live(
        session_id="live-1", source_id="camera-1"
    ).snapshot()
    snapshot["raw_audio"] = b"secret"
    with pytest.raises(VideoCompanionError, match="raw media bytes"):
        VideoCompanionSession.from_snapshot(snapshot)


def test_adaptive_frame_sampling_deduplicates_and_reacts_to_motion() -> None:
    session = _file(min_sample_interval=2.0, max_sample_interval=8.0)

    first = session.record_frame(
        timestamp=0.0, descriptor="Alpecca enters the room", fingerprint="scene-a"
    )
    unchanged = session.record_frame(
        timestamp=1.0, descriptor="same", fingerprint="scene-a"
    )
    duplicate = session.record_frame(
        timestamp=2.0, descriptor="same", fingerprint="scene-a"
    )
    changed = session.record_frame(
        timestamp=2.5,
        descriptor="A door opens quickly",
        fingerprint="scene-b",
        motion_score=0.9,
    )

    assert first.accepted
    assert not unchanged.accepted and unchanged.reason == "compacted_unchanged_run"
    assert not duplicate.accepted and duplicate.reason == "compacted_unchanged_run"
    assert duplicate.interval_seconds == 4.5
    assert changed.accepted and changed.interval_seconds == 2.0
    assert [entry.kind for entry in session.timeline] == ["frame", "frame"]
    assert session.timeline[0].start_seconds == 0.0
    assert session.timeline[0].end_seconds == 2.0


def test_timestamped_transcripts_are_sanitized_and_deduplicated() -> None:
    session = _file()
    first = session.record_transcript(
        start_seconds=10.0,
        end_seconds=12.5,
        speaker="CreatorJD",
        text="Open https://example.test/watch?token=do-not-store now",
    )
    duplicate = session.record_transcript(
        start_seconds=13.0,
        end_seconds=14.0,
        speaker="CreatorJD",
        text="Open https://example.test/watch?token=another-secret now",
    )

    assert first.accepted
    assert not duplicate.accepted and duplicate.reason == "compacted_duplicate_range"
    entry = session.timeline[0]
    assert (entry.start_seconds, entry.end_seconds) == (10.0, 14.0)
    assert entry.speaker == "CreatorJD"
    assert entry.text == "Open [redacted-url] now"
    serialized = json.dumps(session.snapshot())
    assert "do-not-store" not in serialized
    assert "another-secret" not in serialized


def test_reactions_have_no_rate_quota_and_deferrals_remain_visible() -> None:
    session = _file()

    first = session.record_reaction(now=100.0, cue="notable scene change")
    second = session.record_reaction(now=100.01, cue="important spoken correction")
    assert first.disposition == second.disposition == "observed"
    assert session.reaction_eligibility().eligible

    session.interrupt_for_direct_conversation(now=101.0)
    blocked = session.reaction_eligibility()
    assert not blocked.eligible and blocked.deferred
    deferred = session.record_reaction(now=101.1, cue="meaningful event during turn")
    assert deferred.disposition == "deferred"
    assert deferred.defer_reason == "turn_ownership"


def test_direct_conversation_preempts_and_resume_preserves_progress() -> None:
    session = _file()
    session.advance_progress(30.0)
    companion = session.scheduler_metadata()
    direct = session.interrupt_for_direct_conversation(now=200.0)

    assert companion.priority is SchedulerPriority.VIDEO_COMPANION
    assert companion.priority.value == "P2" and companion.preemptible
    assert direct.priority is SchedulerPriority.DIRECT_CONVERSATION
    assert direct.priority.value == "P0" and not direct.preemptible
    assert session.status is SessionStatus.INTERRUPTED
    deferred = session.record_frame(timestamp=31.0, descriptor="meaningful event")
    assert deferred.accepted and deferred.reason == "turn_ownership"
    assert session.deferred_timeline[-1].text == "meaningful event"

    restored = VideoCompanionSession.from_snapshot(session.snapshot())
    resumed = restored.resume_after_direct_conversation(now=210.0)
    resolved = restored.resolve_deferred(restored.deferred_timeline[-1].sequence)
    assert resumed.priority is SchedulerPriority.VIDEO_COMPANION
    assert restored.status is SessionStatus.ACTIVE
    assert restored.progress.processed_until == 31.0
    assert resolved.disposition == "resolved"
    assert restored.timeline[-1].kind == "resume"


def test_timeline_is_hard_bounded_and_contains_derived_data_only() -> None:
    session = VideoCompanionSession.for_live(
        session_id="live-1",
        source_id="camera-1",
        max_timeline=3,
        min_sample_interval=1.0,
    )
    for index in range(5):
        decision = session.record_frame(
            timestamp=float(index),
            descriptor=f"derived frame {index}",
            fingerprint=f"frame-{index}",
            motion_score=1.0,
        )
        assert decision.accepted

    assert len(session.timeline) == 3
    assert [entry.text for entry in session.timeline] == [
        "derived frame 2", "derived frame 3", "derived frame 4"
    ]
    assert session.timeline[0].sequence == 3
    summary = session.compaction_summary
    assert summary.entry_count == 2
    assert summary.start_seconds == 0.0
    assert summary.end_seconds == 1.0
    assert summary.digest_sha256 is not None
    assert summary.entry_count + len(session.timeline) == 5
    snapshot = session.snapshot()
    assert isinstance(json.dumps(snapshot), str)
    assert VideoCompanionSession.from_snapshot(snapshot).compaction_summary == summary


def test_host_pressure_defers_meaningful_events_instead_of_dropping_them() -> None:
    session = VideoCompanionSession.for_live(
        session_id="live-1",
        source_id="camera-1",
        adapter_id="generic-capture-adapter",
    )
    decision = session.record_transcript(
        start_seconds=1.0,
        end_seconds=2.0,
        text="A meaningful statement",
        host_pressure=True,
    )

    assert decision.accepted and decision.reason == "host_pressure"
    assert session.source.surface == "house_hq"
    assert session.source.adapter_id == "generic-capture-adapter"
    assert session.deferred_timeline[0].text == "A meaningful statement"


def test_unresolved_deferred_capacity_applies_explicit_backpressure() -> None:
    session = VideoCompanionSession.for_live(
        session_id="live-1", source_id="camera-1", max_timeline=2
    )
    for index in range(2):
        session.record_frame(
            timestamp=float(index),
            descriptor=f"meaningful event {index}",
            fingerprint=f"event-{index}",
            host_pressure=True,
        )

    with pytest.raises(VideoCompanionError, match="unresolved deferred events"):
        session.record_frame(
            timestamp=2.0,
            descriptor="meaningful event requiring backpressure",
            fingerprint="event-2",
            host_pressure=True,
        )

    assert [entry.text for entry in session.deferred_timeline] == [
        "meaningful event 0", "meaningful event 1"
    ]
    assert session.compaction_summary.entry_count == 0


def test_pause_and_snapshot_restore_preserve_live_resume_state() -> None:
    session = VideoCompanionSession.for_live(
        session_id="live-1", source_id="camera-1"
    )
    session.advance_progress(55.0)
    session.pause()

    restored = VideoCompanionSession.from_snapshot(session.snapshot())
    assert restored.status is SessionStatus.PAUSED
    restored.resume()
    restored.advance_progress(60.0)
    assert restored.status is SessionStatus.ACTIVE
    assert restored.progress.processed_until == 60.0
