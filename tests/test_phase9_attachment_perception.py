from __future__ import annotations

from contextlib import contextmanager
from dataclasses import FrozenInstanceError
import hashlib
import json
import math

import pytest

from alpecca.attachment_perception import (
    MAX_BYTES_BY_TYPE,
    MAX_DIMENSION_PIXELS,
    MAX_DURATION_SECONDS,
    MAX_IMAGE_PIXELS,
    AttachmentEnvelopeRejected,
    AttachmentPerceptionEnvelope,
    create_attachment_envelope,
)


DIGEST = hashlib.sha256(b"already inspected local attachment").hexdigest()
SCOPE = "creator-private"


def image_envelope(**overrides: object) -> AttachmentPerceptionEnvelope:
    values: dict[str, object] = {
        "scope": SCOPE,
        "authorized_scopes": {SCOPE},
        "source": "workspace:attachments/preview.png",
        "mime_type": "image/png",
        "attachment_type": "image",
        "sha256": DIGEST,
        "size_bytes": 4096,
        "width": 640,
        "height": 480,
    }
    values.update(overrides)
    return create_attachment_envelope(**values)  # type: ignore[arg-type]


@contextmanager
def rejected(reason: str):
    with pytest.raises(AttachmentEnvelopeRejected) as caught:
        yield caught
    assert caught.value.reason == reason


def test_valid_image_metadata_is_scoped_provenanced_and_cloud_denied():
    result = image_envelope(mime_type="IMAGE/PNG", sha256=DIGEST.upper())

    assert result.scope == SCOPE
    assert result.source == "workspace:attachments/preview.png"
    assert result.mime_type == "image/png"
    assert result.attachment_type == "image"
    assert result.sha256 == DIGEST
    assert result.provenance == f"sha256:{DIGEST}"
    assert (result.width, result.height) == (640, 480)
    assert result.duration_seconds is None
    assert result.processing_location == "local-only"
    assert result.cloud_egress == "denied"


def test_scope_authorization_is_exact_and_cannot_use_wildcards():
    with rejected("unauthorized-scope"):
        image_envelope(authorized_scopes={"guest-private"})
    with rejected("invalid-scope"):
        image_envelope(scope="*")
    with rejected("unauthorized-scope"):
        image_envelope(authorized_scopes=SCOPE)


@pytest.mark.parametrize("sha256", ("", "abc", "0" * 64, "g" * 64))
def test_missing_or_malformed_provenance_is_rejected(sha256: str):
    with rejected("missing-provenance"):
        image_envelope(sha256=sha256)


@pytest.mark.parametrize(
    "source",
    (
        "",
        "../secret.png",
        "workspace:attachments/../secret.png",
        "/absolute/preview.png",
        r"C:\Users\Jason\preview.png",
        "https://example.test/preview.png",
        "data:image/png;base64,AAAA",
        "workspace:attachments//preview.png",
    ),
)
def test_source_must_be_a_bounded_local_identifier(source: str):
    with rejected("invalid-source"):
        image_envelope(source=source)


@pytest.mark.parametrize(
    ("mime_type", "attachment_type", "reason"),
    (
        ("image/png; charset=binary", "image", "invalid-mime"),
        ("not-a-mime", "image", "invalid-mime"),
        ("application/octet-stream", "document", "unsupported-mime"),
        ("image/png", "audio", "type-mismatch"),
        ("audio/wav", "image", "type-mismatch"),
    ),
)
def test_malformed_unsupported_or_mismatched_mime_is_rejected(
    mime_type: str, attachment_type: str, reason: str
):
    with rejected(reason):
        image_envelope(
            mime_type=mime_type,
            attachment_type=attachment_type,
            duration_seconds=1.0 if attachment_type == "audio" else None,
        )


@pytest.mark.parametrize("size_bytes", (0, -1, True, 1.5, "12"))
def test_invalid_sizes_are_rejected(size_bytes: object):
    with rejected("invalid-size"):
        image_envelope(size_bytes=size_bytes)


@pytest.mark.parametrize("attachment_type", tuple(MAX_BYTES_BY_TYPE))
def test_each_attachment_type_has_a_hard_size_limit(attachment_type: str):
    mime_and_metadata = {
        "text": {"mime_type": "text/plain", "width": None, "height": None},
        "image": {"mime_type": "image/png", "width": 1, "height": 1},
        "audio": {
            "mime_type": "audio/wav",
            "width": None,
            "height": None,
            "duration_seconds": 1.0,
        },
        "video": {
            "mime_type": "video/mp4",
            "width": 1,
            "height": 1,
            "duration_seconds": 1.0,
        },
        "document": {
            "mime_type": "application/pdf",
            "width": None,
            "height": None,
        },
    }[attachment_type]
    values = {
        "attachment_type": attachment_type,
        "size_bytes": MAX_BYTES_BY_TYPE[attachment_type] + 1,
        **mime_and_metadata,
    }

    with rejected("size-limit"):
        image_envelope(**values)


@pytest.mark.parametrize(
    ("width", "height", "reason"),
    (
        (None, 100, "invalid-dimensions"),
        (100, None, "invalid-dimensions"),
        (0, 100, "invalid-dimensions"),
        (True, 100, "invalid-dimensions"),
        (MAX_DIMENSION_PIXELS + 1, 1, "invalid-dimensions"),
        (MAX_DIMENSION_PIXELS, MAX_DIMENSION_PIXELS, "pixel-limit"),
    ),
)
def test_image_dimensions_are_required_and_bounded(
    width: object, height: object, reason: str
):
    with rejected(reason):
        image_envelope(width=width, height=height)


def test_total_pixel_limit_accepts_boundary_and_rejects_above_it():
    width = 5000
    height = MAX_IMAGE_PIXELS // width

    accepted = image_envelope(width=width, height=height)
    assert accepted.width * accepted.height == MAX_IMAGE_PIXELS  # type: ignore[operator]
    with rejected("pixel-limit"):
        image_envelope(width=width, height=height + 1)


@pytest.mark.parametrize(
    "duration",
    (None, 0.0, -1.0, math.nan, math.inf, True, MAX_DURATION_SECONDS + 0.1),
)
def test_audio_duration_is_required_finite_and_bounded(duration: object):
    with rejected("invalid-duration"):
        create_attachment_envelope(
            scope=SCOPE,
            authorized_scopes={SCOPE},
            source="workspace:attachments/voice.wav",
            mime_type="audio/wav",
            attachment_type="audio",
            sha256=DIGEST,
            size_bytes=1024,
            duration_seconds=duration,  # type: ignore[arg-type]
        )


def test_valid_audio_video_text_and_document_metadata_shapes():
    audio = create_attachment_envelope(
        scope=SCOPE,
        authorized_scopes={SCOPE},
        source="workspace:attachments/voice.wav",
        mime_type="audio/wav",
        attachment_type="audio",
        sha256=DIGEST,
        size_bytes=1024,
        duration_seconds=12.5,
    )
    video = create_attachment_envelope(
        scope=SCOPE,
        authorized_scopes={SCOPE},
        source="workspace:attachments/clip.mp4",
        mime_type="video/mp4",
        attachment_type="video",
        sha256=DIGEST,
        size_bytes=2048,
        width=1920,
        height=1080,
        duration_seconds=4.25,
    )
    text = create_attachment_envelope(
        scope=SCOPE,
        authorized_scopes={SCOPE},
        source="workspace:attachments/note.txt",
        mime_type="text/plain",
        attachment_type="text",
        sha256=DIGEST,
        size_bytes=32,
    )
    document = create_attachment_envelope(
        scope=SCOPE,
        authorized_scopes={SCOPE},
        source="workspace:attachments/report.pdf",
        mime_type="application/pdf",
        attachment_type="document",
        sha256=DIGEST,
        size_bytes=512,
    )

    assert audio.duration_seconds == 12.5
    assert (video.width, video.height, video.duration_seconds) == (1920, 1080, 4.25)
    assert text.width is None and text.duration_seconds is None
    assert document.attachment_type == "document"


def test_non_media_types_cannot_smuggle_dimensions_or_duration():
    with rejected("invalid-dimensions"):
        create_attachment_envelope(
            scope=SCOPE,
            authorized_scopes={SCOPE},
            source="workspace:attachments/note.txt",
            mime_type="text/plain",
            attachment_type="text",
            sha256=DIGEST,
            size_bytes=32,
            width=1,
        )
    with rejected("invalid-duration"):
        image_envelope(duration_seconds=1.0)


def test_local_only_and_cloud_denied_classifications_cannot_be_relaxed():
    with rejected("classification-not-local"):
        image_envelope(processing_location="cloud")
    with rejected("cloud-egress-not-denied"):
        image_envelope(cloud_egress="allowed")


def test_envelope_is_immutable_serializable_and_contains_no_raw_content():
    result = image_envelope()
    payload = result.as_dict()
    encoded = json.dumps(payload, sort_keys=True)

    assert "raw_content" not in payload
    assert "content" not in payload
    assert "bytes" not in payload
    assert DIGEST in encoded
    assert '"cloud_egress": "denied"' in encoded
    with pytest.raises(FrozenInstanceError):
        result.scope = "guest-private"  # type: ignore[misc]
    with pytest.raises(TypeError):
        AttachmentPerceptionEnvelope(
            scope=SCOPE,
            authorized_scopes={SCOPE},
            source="workspace:attachments/preview.png",
            mime_type="image/png",
            attachment_type="image",
            sha256=DIGEST,
            size_bytes=4096,
            width=640,
            height=480,
            raw_content=b"not allowed",  # type: ignore[call-arg]
        )
