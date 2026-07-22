from __future__ import annotations

import builtins

import pytest

from alpecca.media_timeline import (
    FrameDescriptor,
    MediaSource,
    MediaTimelineError,
    TimelineEventKind,
    TranscriptDescriptor,
    parse_ffprobe_metadata,
    plan_adaptive_sampling,
    plan_timeline,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def metadata(*, adapter: str = "house_hq", duration: str = "60.0"):
    return parse_ffprobe_metadata(
        MediaSource("media-42", adapter, "session-7"),
        {
            "format": {
                "duration": duration,
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                "size": "1048576",
                "bit_rate": "140000",
                "filename": "ignored-by-pure-planner.mp4",
            },
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "duration": duration,
                    "avg_frame_rate": "30000/1001",
                    "width": 1920,
                    "height": 1080,
                },
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "duration": duration,
                    "sample_rate": "48000",
                    "channels": 2,
                },
            ],
        },
    )


@pytest.mark.parametrize(
    "adapter",
    ["house_hq", "discord_attachment", "file_session"],
)
def test_source_neutral_metadata_contract_supports_all_ingress_surfaces(
    adapter: str,
) -> None:
    result = metadata(adapter=adapter)

    assert result.source.adapter == adapter
    assert result.source.source_id == "media-42"
    assert result.duration_seconds == 60.0
    assert result.byte_size == 1_048_576
    assert result.streams[0].kind == "video"
    assert result.streams[0].frame_rate == pytest.approx(29.97002997)
    assert result.streams[1].sample_rate == 48_000


def test_probe_parser_uses_stream_duration_when_format_duration_is_absent() -> None:
    result = parse_ffprobe_metadata(
        MediaSource("media-1", "file_session"),
        {
            "format": {"format_name": "matroska"},
            "streams": [
                {"index": 0, "codec_type": "video", "duration": "12.5"},
                {"index": 1, "codec_type": "audio", "duration": "12.4"},
            ],
        },
    )

    assert result.duration_seconds == 12.5


def test_source_ids_are_opaque_and_stream_indices_are_unique() -> None:
    for source_id in (
        "https://cdn.example.test/private.mp4",
        "C:\\private\\clip.mp4",
        "/private/clip.mp4",
    ):
        with pytest.raises(MediaTimelineError, match="opaque"):
            MediaSource(source_id, "file_session")

    with pytest.raises(MediaTimelineError, match="indices"):
        parse_ffprobe_metadata(
            MediaSource("media-1", "file_session"),
            {
                "format": {"duration": "2"},
                "streams": [
                    {"index": 0, "codec_type": "video"},
                    {"index": 0, "codec_type": "audio"},
                ],
            },
        )


def test_planning_never_reads_or_downloads_media(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("pure planner attempted file access")

    monkeypatch.setattr(builtins, "open", forbidden)
    result = metadata(adapter="discord_attachment")
    plan = plan_timeline(result, window_seconds=10.0)

    assert len(plan.windows) == 6
    assert plan.events == ()


def test_unordered_descriptors_become_complete_ordered_timestamp_windows() -> None:
    result = metadata()
    transcripts = [
        TranscriptDescriptor("speech-2", 31.0, 34.0, "Later statement"),
        TranscriptDescriptor("speech-1", 4.0, 6.0, "Opening statement"),
    ]
    frames = [
        FrameDescriptor("frame-2", 22.0, "A door opens", HASH_B),
        FrameDescriptor("frame-1", 2.0, "A closed door", HASH_A),
    ]

    plan = plan_timeline(
        result,
        transcripts=transcripts,
        frames=frames,
        window_seconds=10.0,
    )

    assert [(window.start_seconds, window.end_seconds) for window in plan.windows] == [
        (0.0, 10.0),
        (10.0, 20.0),
        (20.0, 30.0),
        (30.0, 40.0),
        (40.0, 50.0),
        (50.0, 60.0),
    ]
    assert [event.first_event_id for event in plan.events] == [
        "frame-1",
        "speech-1",
        "frame-2",
        "speech-2",
    ]


def test_exact_unchanged_frames_compact_only_to_explicit_range() -> None:
    result = metadata()
    frames = [
        FrameDescriptor("frame-1", 1.0, "Static title card", HASH_A),
        FrameDescriptor("frame-2", 2.0, "Static title card", HASH_A),
        FrameDescriptor("frame-3", 4.0, "Static title card", HASH_A),
        FrameDescriptor("frame-4", 5.0, "The title fades", HASH_B),
    ]

    events = plan_timeline(result, frames=frames).events

    assert len(events) == 2
    unchanged = events[0]
    assert unchanged.kind is TimelineEventKind.UNCHANGED_FRAME_RANGE
    assert unchanged.start_seconds == 1.0
    assert unchanged.end_seconds == 4.0
    assert unchanged.first_event_id == "frame-1"
    assert unchanged.last_event_id == "frame-3"
    assert unchanged.sample_count == 3
    assert events[1].first_event_id == "frame-4"


def test_descriptions_without_exact_hash_never_compact() -> None:
    result = metadata()
    frames = [
        FrameDescriptor("frame-1", 1.0, "Looks the same"),
        FrameDescriptor("frame-2", 2.0, "Looks the same"),
    ]

    events = plan_timeline(result, frames=frames).events

    assert len(events) == 2
    assert all(event.kind is TimelineEventKind.FRAME for event in events)


def test_meaningful_exact_frame_is_never_compacted() -> None:
    result = metadata()
    frames = [
        FrameDescriptor("frame-1", 1.0, "Button is pressed", HASH_A),
        FrameDescriptor(
            "frame-2",
            2.0,
            "Button is pressed",
            HASH_A,
            meaningful=True,
        ),
        FrameDescriptor("frame-3", 3.0, "Button is pressed", HASH_A),
    ]

    events = plan_timeline(result, frames=frames).events

    assert [event.first_event_id for event in events] == [
        "frame-1",
        "frame-2",
        "frame-3",
    ]
    assert events[1].meaningful is True


def test_transcript_events_are_never_compacted_or_rate_limited() -> None:
    result = metadata()
    transcripts = [
        TranscriptDescriptor(
            f"speech-{index}",
            index / 100.0,
            index / 100.0,
            "Repeated but meaningful statement",
        )
        for index in range(100)
    ]

    events = plan_timeline(result, transcripts=transcripts).events

    assert len(events) == 100
    assert all(event.kind is TimelineEventKind.TRANSCRIPT for event in events)
    assert {event.first_event_id for event in events} == {
        f"speech-{index}" for index in range(100)
    }


def test_adaptive_sampling_tracks_every_frame_and_resets_for_events() -> None:
    result = metadata()
    frames = [
        FrameDescriptor("frame-1", 0.0, "Still", HASH_A),
        FrameDescriptor("frame-2", 1.0, "Still", HASH_A),
        FrameDescriptor("frame-3", 2.0, "Still", HASH_A),
        FrameDescriptor("frame-4", 3.0, "Motion", HASH_B, motion_score=0.8),
        FrameDescriptor(
            "frame-5",
            4.0,
            "Meaningful reveal",
            HASH_B,
            meaningful=True,
        ),
    ]

    plan = plan_adaptive_sampling(
        result,
        frames,
        min_interval_seconds=1.0,
        max_interval_seconds=10.0,
    )

    assert len(plan.decisions) == len(frames)
    assert [item.reason for item in plan.decisions] == [
        "observed_frame",
        "exact_unchanged_frame",
        "exact_unchanged_frame",
        "motion",
        "meaningful_event",
    ]
    assert [item.interval_seconds for item in plan.decisions] == [
        1.0,
        1.5,
        2.25,
        1.0,
        1.0,
    ]


def test_sampling_has_no_arbitrary_reaction_rate_cap() -> None:
    result = metadata()
    frames = [
        FrameDescriptor(
            f"event-{index}",
            index / 100.0,
            f"Meaningful event {index}",
            meaningful=True,
        )
        for index in range(100)
    ]

    plan = plan_adaptive_sampling(result, frames)

    assert len(plan.decisions) == 100
    assert all(item.reason == "meaningful_event" for item in plan.decisions)
    assert all(item.meaningful for item in plan.decisions)


@pytest.mark.parametrize(
    ("probe", "message"),
    [
        ({"format": {}, "streams": []}, "duration"),
        ({"format": {"duration": "nan"}, "streams": []}, "finite"),
        (
            {
                "format": {"duration": "1"},
                "streams": [{"codec_type": "video", "width": 40_000}],
            },
            "bound",
        ),
    ],
)
def test_probe_metadata_bounds_are_validated(probe, message: str) -> None:
    with pytest.raises(MediaTimelineError, match=message):
        parse_ffprobe_metadata(MediaSource("media-1", "file_session"), probe)


def test_descriptor_timestamps_and_ids_are_bounded() -> None:
    result = metadata(duration="10")
    with pytest.raises(MediaTimelineError, match="exceeds media duration"):
        plan_timeline(
            result,
            frames=[FrameDescriptor("late", 11.0, "Too late")],
        )
    with pytest.raises(MediaTimelineError, match="unique"):
        plan_timeline(
            result,
            transcripts=[TranscriptDescriptor("same", 1.0, 2.0, "Words")],
            frames=[FrameDescriptor("same", 3.0, "Image")],
        )
    with pytest.raises(MediaTimelineError, match="SHA-256"):
        FrameDescriptor("frame", 1.0, "Image", "not-a-hash")


def test_window_count_is_bounded_without_dropping_events() -> None:
    result = metadata(duration="600")
    with pytest.raises(MediaTimelineError, match="timestamp windows"):
        plan_timeline(result, window_seconds=0.1)
