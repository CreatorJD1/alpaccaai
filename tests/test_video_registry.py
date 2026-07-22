from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpecca.video_companion import SessionStatus, SourceKind, VideoCompanionError
from alpecca.video_registry import VideoRegistryError, VideoSessionRegistry


DIGEST = "b" * 64


def test_create_defaults_to_house_hq_and_enforces_one_authority(tmp_path: Path) -> None:
    path = tmp_path / "video-registry.json"
    registry = VideoSessionRegistry(path)
    created = registry.create_live(session_id="watch-1", source_id="capture-1")

    assert created.source.surface == "house_hq"
    assert created.source.adapter_id == "live"
    assert created.source.kind is SourceKind.LIVE
    with pytest.raises(VideoRegistryError, match="active session already exists"):
        registry.create_live(session_id="watch-2", source_id="capture-2")

    detached = registry.get()
    assert detached is not None
    detached.pause()
    assert registry.status().active is not None
    assert registry.status().active.status is SessionStatus.ACTIVE
    registry.pause()
    assert registry.status().active.status is SessionStatus.PAUSED
    registry.resume()
    assert registry.status().active.status is SessionStatus.ACTIVE
    assert path.exists()


def test_restart_recovers_authoritative_session_as_paused(tmp_path: Path) -> None:
    path = tmp_path / "video-registry.json"
    registry = VideoSessionRegistry(path)
    registry.create_file(
        session_id="movie-1",
        source_id="asset-1",
        content_sha256=DIGEST,
        duration_seconds=100.0,
        adapter_id="file",
    )
    registry.advance_progress(25.0)

    recovered = VideoSessionRegistry(path)
    active = recovered.get()
    assert active is not None
    assert active.status is SessionStatus.PAUSED
    assert active.progress.processed_until == 25.0
    assert json.loads(path.read_text(encoding="utf-8"))["active"]["state"]["status"] == "paused"

    recovered.resume()
    assert recovered.status().active is not None
    assert recovered.status().active.status is SessionStatus.ACTIVE


def test_events_are_descriptor_only_sanitized_and_deferred_durably(tmp_path: Path) -> None:
    path = tmp_path / "video-registry.json"
    registry = VideoSessionRegistry(path)
    registry.create_live(
        session_id="watch-1",
        source_id="capture-1",
        adapter_id="discord",
    )
    visual = registry.accept_visual_descriptor(
        timestamp=1.0,
        descriptor=(
            "Open https://private.test/watch?token=abc or www.backup.test/watch "
            "token=top-secret"
        ),
        fingerprint="scene-1",
        host_pressure=True,
    )
    transcript = registry.accept_transcript(
        start_seconds=1.0,
        end_seconds=2.0,
        text="Authorization: Bearer abc.def.ghi and password=hunter2",
        turn_owned=False,
    )

    assert visual.accepted and visual.reason == "host_pressure"
    assert transcript.accepted and transcript.reason == "turn_ownership"
    active = registry.get()
    assert active is not None
    assert len(active.deferred_timeline) == 2
    persisted = path.read_text(encoding="utf-8")
    assert "https://" not in persisted
    assert "www.backup.test" not in persisted
    assert "top-secret" not in persisted
    assert "hunter2" not in persisted
    assert "abc.def.ghi" not in persisted
    assert "[redacted-url]" in persisted
    assert "[redacted-credential]" in persisted

    with pytest.raises(VideoRegistryError, match="raw media bytes"):
        registry.accept_visual_descriptor(timestamp=3.0, descriptor=b"pixels")  # type: ignore[arg-type]


def test_unchanged_runs_compact_but_changed_events_are_never_sampled_out(tmp_path: Path) -> None:
    registry = VideoSessionRegistry(tmp_path / "registry.json")
    registry.create_live(
        session_id="watch-1",
        source_id="capture-1",
        min_sample_interval=5.0,
    )
    registry.record_visual_descriptor(
        timestamp=0.0, descriptor="scene one", fingerprint="same"
    )
    duplicate = registry.record_visual_descriptor(
        timestamp=1.0, descriptor="scene one", fingerprint="same"
    )
    changed = registry.record_visual_descriptor(
        timestamp=1.1, descriptor="meaningful change", fingerprint="different"
    )

    assert not duplicate.accepted and duplicate.reason == "compacted_unchanged_run"
    assert changed.accepted
    active = registry.get()
    assert active is not None
    assert [(item.text, item.start_seconds, item.end_seconds) for item in active.timeline] == [
        ("scene one", 0.0, 1.0),
        ("meaningful change", 1.1, 1.1),
    ]


def test_stop_and_natural_completion_keep_bounded_terminal_snapshots(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    registry = VideoSessionRegistry(path, max_completed=2)
    for index in range(3):
        registry.create_live(session_id=f"live-{index}", source_id=f"capture-{index}")
        stopped = registry.stop()
        assert stopped.status is SessionStatus.STOPPED

    status = registry.status()
    assert status.active is None
    assert [item.session_id for item in status.completed] == ["live-1", "live-2"]
    assert status.retired_completed_count == 1
    assert status.retired_completed_digest is not None

    registry.create_file(
        session_id="movie",
        source_id="asset",
        content_sha256=DIGEST,
        duration_seconds=10.0,
    )
    progress = registry.advance_progress(10.0)
    assert progress.complete
    assert registry.status().active is None
    assert registry.get("movie") is not None
    recovered = VideoSessionRegistry(path, max_completed=2)
    assert recovered.status().active is None
    assert recovered.get("movie") is not None


def test_status_is_content_bounded_and_contains_no_event_text(tmp_path: Path) -> None:
    registry = VideoSessionRegistry(tmp_path / "registry.json")
    registry.create_live(session_id="watch-1", source_id="capture-1")
    registry.accept_transcript(
        start_seconds=0.0,
        end_seconds=1.0,
        text="private but meaningful transcript content",
        host_pressure=True,
    )

    status = registry.status()
    assert status.active is not None
    assert status.active.retained_events == 1
    assert status.active.deferred_events == 1
    assert "private but meaningful" not in repr(status)


def test_unresolved_deferred_backpressure_preserves_durable_prior_state(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    registry = VideoSessionRegistry(path)
    registry.create_live(
        session_id="watch-1", source_id="capture-1", max_timeline=2
    )
    for index in range(2):
        registry.accept_visual_descriptor(
            timestamp=float(index),
            descriptor=f"meaningful {index}",
            fingerprint=f"event-{index}",
            host_pressure=True,
        )
    before = path.read_bytes()

    with pytest.raises(VideoCompanionError, match="unresolved deferred events"):
        registry.accept_visual_descriptor(
            timestamp=2.0,
            descriptor="must receive explicit backpressure",
            fingerprint="event-2",
            host_pressure=True,
        )

    assert path.read_bytes() == before
    active = registry.get()
    assert active is not None
    assert [item.text for item in active.deferred_timeline] == [
        "meaningful 0", "meaningful 1"
    ]


def test_atomic_publish_failure_rolls_back_in_memory_and_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "registry.json"
    registry = VideoSessionRegistry(path)
    registry.create_live(session_id="watch-1", source_id="capture-1")
    before = path.read_bytes()

    def fail_replace(_source, _destination):
        raise OSError("simulated publish failure")

    monkeypatch.setattr("alpecca.video_registry.os.replace", fail_replace)
    with pytest.raises(VideoRegistryError, match="atomically"):
        registry.accept_transcript(
            start_seconds=0.0, end_seconds=1.0, text="not durably accepted"
        )

    assert path.read_bytes() == before
    active = registry.get()
    assert active is not None and active.timeline == ()
