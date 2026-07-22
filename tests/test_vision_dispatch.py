from __future__ import annotations

import threading

import pytest

from alpecca.inference_scheduler import TaskState
from alpecca.vision_dispatch import (
    VisionDispatcher,
    VisionEventKind,
    VisionProcessorInput,
)


def test_direct_upload_runs_before_queued_ambient_frame() -> None:
    dispatcher = VisionDispatcher()
    ambient = dispatcher.submit_ambient_frame(
        b"ambient",
        source="screen",
        event_id="frame-1",
        stream_id="desktop",
        content_type="image/png",
    )
    direct = dispatcher.submit_direct_upload(
        b"direct",
        source="discord",
        event_id="upload-1",
        content_type="image/jpeg",
    )
    seen: list[bytes] = []

    first = dispatcher.process_next(
        lambda item: seen.append(item.frame_bytes) or "direct result"
    )
    second = dispatcher.process_next(
        lambda item: seen.append(item.frame_bytes) or "ambient result"
    )

    assert ambient.task is not None and direct.task is not None
    assert first is not None and second is not None
    assert first.task.task_id == direct.task.task_id
    assert second.task.task_id == ambient.task.task_id
    assert seen == [b"direct", b"ambient"]


def test_only_one_processor_can_be_active() -> None:
    dispatcher = VisionDispatcher()
    dispatcher.submit_direct_upload(
        b"one",
        source="discord",
        event_id="upload-1",
        content_type="image/png",
    )
    dispatcher.submit_direct_upload(
        b"two",
        source="discord",
        event_id="upload-2",
        content_type="image/png",
    )

    nested_results: list[object] = []

    def processor(item: VisionProcessorInput) -> str:
        nested_results.append(dispatcher.process_next(lambda nested: "unexpected"))
        return item.event.event_id

    result = dispatcher.process_next(processor)
    assert result is not None and result.succeeded
    assert nested_results == [None]
    assert dispatcher.queued_count == 1


def test_ambient_frames_coalesce_per_stream_and_keep_latest_bytes() -> None:
    dispatcher = VisionDispatcher()
    first = dispatcher.submit_ambient_frame(
        b"old pixels",
        source="screen",
        event_id="frame-1",
        stream_id="desktop",
        content_type="image/png",
    )
    latest = dispatcher.submit_ambient_frame(
        b"new pixels",
        source="screen",
        event_id="frame-2",
        stream_id="desktop",
        content_type="image/png",
    )

    assert first.task is not None and latest.task is not None
    assert latest.accepted and latest.coalesced
    assert latest.task.task_id == first.task.task_id
    assert dispatcher.queued_count == 1
    assert dispatcher.retained_frame_count == 1

    result = dispatcher.process_next(
        lambda item: (item.event.event_id, item.frame_bytes)
    )
    assert result is not None
    assert result.value == ("frame-2", b"new pixels")
    assert dispatcher.retained_frame_count == 0


def test_ambient_event_and_content_dedup_do_not_retain_duplicate_bytes() -> None:
    dispatcher = VisionDispatcher()
    accepted = dispatcher.submit_ambient_frame(
        b"same pixels",
        source="camera",
        event_id="frame-1",
        stream_id="front",
        content_type="image/jpeg",
    )
    same_event = dispatcher.submit_ambient_frame(
        b"different pixels",
        source="camera",
        event_id="frame-1",
        stream_id="front",
        content_type="image/jpeg",
    )
    same_content = dispatcher.submit_ambient_frame(
        b"same pixels",
        source="camera",
        event_id="frame-2",
        stream_id="front",
        content_type="image/jpeg",
    )

    assert accepted.task is not None
    assert same_event.reason == "duplicate_frame_event"
    assert same_content.reason == "duplicate_frame_event"
    assert same_event.duplicate_of == accepted.task.task_id
    assert same_content.duplicate_of == accepted.task.task_id
    assert dispatcher.queued_count == 1
    assert dispatcher.retained_frame_count == 1


def test_direct_upload_displaces_oldest_ambient_when_queue_is_full() -> None:
    dispatcher = VisionDispatcher(max_queued=1)
    ambient = dispatcher.submit_ambient_frame(
        b"ambient",
        source="screen",
        event_id="frame-1",
        stream_id="desktop",
        content_type="image/png",
    )
    direct = dispatcher.submit_direct_upload(
        b"direct",
        source="discord",
        event_id="upload-1",
        content_type="image/png",
    )

    assert ambient.task is not None
    assert direct.accepted and direct.task is not None
    assert direct.displaced is not None
    assert direct.displaced.task_id == ambient.task.task_id
    assert direct.displaced.state is TaskState.CANCELLED
    assert direct.displaced.cancellation is not None
    assert direct.displaced.cancellation.reason == "displaced_by_direct_upload"
    assert direct.displaced.cancellation.requested_by == "vision_dispatch"
    assert dispatcher.retained_frame_count == 1


def test_full_direct_queue_rejects_without_losing_existing_upload() -> None:
    dispatcher = VisionDispatcher(max_queued=1)
    first = dispatcher.submit_direct_upload(
        b"first",
        source="discord",
        event_id="upload-1",
        content_type="image/png",
    )
    rejected = dispatcher.submit_direct_upload(
        b"second",
        source="discord",
        event_id="upload-2",
        content_type="image/png",
    )

    assert first.task is not None
    assert not rejected.accepted
    assert rejected.reason == "queue_capacity"
    assert dispatcher.pending()[0].task_id == first.task.task_id
    assert dispatcher.retained_frame_count == 1


def test_direct_delivery_event_is_deduplicated_but_pixels_are_not() -> None:
    dispatcher = VisionDispatcher()
    first = dispatcher.submit_direct_upload(
        b"same pixels",
        source="discord",
        event_id="upload-1",
        content_type="image/png",
    )
    duplicate_event = dispatcher.submit_direct_upload(
        b"different pixels",
        source="discord",
        event_id="upload-1",
        content_type="image/png",
    )
    distinct_upload = dispatcher.submit_direct_upload(
        b"same pixels",
        source="discord",
        event_id="upload-2",
        content_type="image/png",
    )

    assert first.task is not None and distinct_upload.task is not None
    assert not duplicate_event.accepted
    assert duplicate_event.reason == "duplicate_frame_event"
    assert duplicate_event.duplicate_of == first.task.task_id
    assert distinct_upload.accepted
    assert dispatcher.queued_count == 2
    assert dispatcher.retained_frame_count == 2


def test_cancel_removes_frame_and_records_provenance() -> None:
    dispatcher = VisionDispatcher()
    submission = dispatcher.submit_ambient_frame(
        b"private pixels",
        source="camera",
        event_id="frame-1",
        stream_id="front",
        content_type="image/jpeg",
    )
    assert submission.task is not None

    cancelled = dispatcher.cancel(
        submission.task.task_id,
        reason="camera_disabled",
        requested_by="privacy-control",
    )

    assert cancelled.state is TaskState.CANCELLED
    assert cancelled.cancellation is not None
    assert cancelled.cancellation.reason == "camera_disabled"
    assert cancelled.cancellation.requested_by == "privacy-control"
    assert dispatcher.retained_frame_count == 0
    assert dispatcher.process_next(lambda item: "unexpected") is None


def test_running_cancellation_discards_processor_value() -> None:
    dispatcher = VisionDispatcher()
    submission = dispatcher.submit_ambient_frame(
        b"private pixels",
        source="camera",
        event_id="frame-1",
        stream_id="front",
        content_type="image/jpeg",
    )
    assert submission.task is not None
    started = threading.Event()
    release = threading.Event()
    outcomes = []

    def processor(item: VisionProcessorInput) -> str:
        started.set()
        assert release.wait(timeout=2.0)
        return "must be discarded"

    worker = threading.Thread(
        target=lambda: outcomes.append(dispatcher.process_next(processor))
    )
    worker.start()
    assert started.wait(timeout=2.0)
    cancelled = dispatcher.cancel(
        submission.task.task_id,
        reason="privacy_revoked",
        requested_by="privacy-control",
    )
    release.set()
    worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert cancelled.state is TaskState.CANCELLED
    assert len(outcomes) == 1
    assert outcomes[0] is not None
    assert not outcomes[0].succeeded
    assert outcomes[0].value is None
    assert outcomes[0].task.cancellation == cancelled.cancellation
    assert dispatcher.retained_frame_count == 0


def test_processor_failure_releases_lane_and_does_not_retain_frame() -> None:
    dispatcher = VisionDispatcher()
    failed_submission = dispatcher.submit_direct_upload(
        b"secret marker pixels",
        source="discord",
        event_id="upload-1",
        content_type="image/png",
    )
    next_submission = dispatcher.submit_direct_upload(
        b"next",
        source="discord",
        event_id="upload-2",
        content_type="image/png",
    )
    assert failed_submission.task is not None and next_submission.task is not None

    def fail(item: VisionProcessorInput) -> str:
        raise RuntimeError("processor unavailable")

    failed = dispatcher.process_next(fail)
    succeeded = dispatcher.process_next(lambda item: "ok")

    assert failed is not None and not failed.succeeded
    assert failed.error_type == "RuntimeError"
    assert failed.error_message == "processor unavailable"
    assert failed.task.state is TaskState.INTERRUPTED
    assert succeeded is not None and succeeded.succeeded
    assert dispatcher.retained_frame_count == 0


def test_public_records_exclude_raw_frame_bytes() -> None:
    marker = b"unique-private-frame-marker"
    dispatcher = VisionDispatcher()
    submission = dispatcher.submit_direct_upload(
        marker,
        source="discord",
        event_id="upload-1",
        content_type="image/png",
        metadata={"channel": "dm"},
    )
    assert submission.task is not None

    task = submission.task
    assert task.payload.byte_length == len(marker)
    assert task.payload.kind is VisionEventKind.DIRECT_UPLOAD
    assert task.payload.metadata == {"channel": "dm"}
    assert marker not in repr(task).encode()

    result = dispatcher.process_next(lambda item: "description only")
    assert result is not None and result.succeeded
    assert dispatcher.retained_frame_count == 0
    assert marker not in repr(dispatcher.snapshot(task.task_id)).encode()


def test_binary_metadata_and_oversized_frames_are_rejected() -> None:
    dispatcher = VisionDispatcher(max_frame_bytes=4)
    with pytest.raises(ValueError, match="max_frame_bytes"):
        dispatcher.submit_direct_upload(
            b"12345",
            source="discord",
            event_id="upload-1",
            content_type="image/png",
        )
    with pytest.raises(TypeError, match="metadata values"):
        dispatcher.submit_direct_upload(
            b"1234",
            source="discord",
            event_id="upload-2",
            content_type="image/png",
            metadata={"raw": b"pixels"},  # type: ignore[dict-item]
        )
    assert dispatcher.retained_frame_count == 0


def test_frame_limit_uses_memoryview_byte_count() -> None:
    dispatcher = VisionDispatcher(max_frame_bytes=4)
    wide_view = memoryview(bytearray(8)).cast("I")

    assert len(wide_view) == 2
    assert wide_view.nbytes == 8
    with pytest.raises(ValueError, match="max_frame_bytes"):
        dispatcher.submit_direct_upload(
            wide_view,
            source="discord",
            event_id="upload-1",
            content_type="image/png",
        )
    assert dispatcher.retained_frame_count == 0
