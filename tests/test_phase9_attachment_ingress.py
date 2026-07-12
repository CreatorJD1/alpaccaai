"""Focused adversarial coverage for pure Phase 9 image ingress."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import dataclasses
import hashlib
import inspect
import json

import pytest

from alpecca import attachment_ingress as ingress_mod
from alpecca.attachment_ingress import (
    ATTACHMENT_IMAGE_MAX_BYTES,
    DEFAULT_MAX_IMAGE_BYTES,
    ImageIngressRejected,
    ingest_image,
    inspect_image_bytes,
)
from alpecca.source_perception import parse_image_header


SCOPE = "creator-private"
SOURCE = "chat:camera-frame"


def _png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def _jpeg(width: int, height: int) -> bytes:
    return (
        b"\xff\xd8\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
    )


def _gif(width: int, height: int) -> bytes:
    return b"GIF89a" + width.to_bytes(2, "little") + height.to_bytes(2, "little")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _encoded(payload: bytes, mime_type: str | None = None) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}" if mime_type else encoded


def _ingest(payload: bytes, *, mime_type: str | None = None, **overrides):
    values = {
        "scope": SCOPE,
        "authorized_scopes": {SCOPE},
        "source": SOURCE,
    }
    values.update(overrides)
    return ingest_image(_encoded(payload, mime_type), **values)


def _raw(payload: bytes, **overrides):
    values = {
        "scope": SCOPE,
        "authorized_scopes": {SCOPE},
        "source": SOURCE,
    }
    values.update(overrides)
    return inspect_image_bytes(payload, **values)


@contextmanager
def _rejected(reason: str):
    with pytest.raises(ImageIngressRejected) as caught:
        yield caught
    assert caught.value.reason == reason


@pytest.mark.parametrize(
    ("mime_type", "payload", "width", "height", "as_data_url"),
    (
        ("image/png", _png(3, 2), 3, 2, True),
        ("image/jpeg", _jpeg(5, 4), 5, 4, True),
        ("image/gif", _gif(7, 6), 7, 6, False),
    ),
)
def test_supported_image_headers_are_bounded_and_provenanced(
    mime_type, payload, width, height, as_data_url
):
    result = _ingest(payload, mime_type=mime_type if as_data_url else None)

    assert result.image_bytes == payload
    assert (result.mime_type, result.width, result.height) == (mime_type, width, height)
    assert result.envelope.scope == SCOPE
    assert result.envelope.sha256 == _digest(payload)
    assert result.envelope.processing_location == "local-only"
    assert result.envelope.cloud_egress == "denied"


def test_raw_bytes_entry_point_reuses_header_scope_and_metadata_contract():
    payload = _png(4, 3)
    result = _raw(payload, declared_mime_type="image/png")

    assert result.image_bytes == payload
    assert result.as_dict() == result.envelope.as_dict()
    serialized = json.dumps(result.as_dict(), sort_keys=True)
    assert "image_bytes" not in serialized
    assert base64.b64encode(payload).decode("ascii") not in serialized
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.image_bytes = b"changed"  # type: ignore[misc]


def test_source_header_parser_exposes_dimensions_without_pixel_decoding():
    header = parse_image_header(_jpeg(11, 9))
    incomplete = parse_image_header(b"\xff\xd8\xff\xc0")

    assert header is not None
    assert (header.mime_type, header.width, header.height) == ("image/jpeg", 11, 9)
    assert incomplete is not None
    assert (incomplete.mime_type, incomplete.width, incomplete.height) == (
        "image/jpeg", None, None
    )


@pytest.mark.parametrize(
    ("value", "reason"),
    (
        ("%%%%", "malformed-base64"),
        ("data:image/png;base64,%%%%", "malformed-base64"),
        ("data:image/png,AAAA", "malformed-data-url"),
        ("data:image/webp;base64,AAAA", "unsupported-mime"),
    ),
)
def test_malformed_or_unsupported_base64_values_fail_closed(value, reason):
    with _rejected(reason) as caught:
        ingest_image(
            value,
            scope=SCOPE,
            authorized_scopes={SCOPE},
            source=SOURCE,
        )


def test_declared_and_sniffed_mime_must_match_for_both_entry_points():
    payload = _png(2, 2)

    with _rejected("mime-mismatch") as encoded_error:
        _ingest(payload, mime_type="image/jpeg")
    with _rejected("mime-mismatch") as raw_error:
        _raw(payload, declared_mime_type="image/jpeg")



def test_unsupported_headers_and_invalid_dimensions_fail_closed():
    with _rejected("unsupported-mime") as unsupported:
        _raw(b"not an image")
    with _rejected("invalid-dimensions") as zero_dimension:
        _raw(_png(0, 1))
    with _rejected("pixel-limit") as too_many_pixels:
        _raw(_png(8192, 8192))



def test_scope_is_enforced_and_provenance_is_derived_inside_the_guard():
    payload = _gif(2, 2)

    with _rejected("unauthorized-scope"):
        _raw(payload, authorized_scopes={"guest-private"})
    raw_result = _raw(payload)
    encoded_result = _ingest(payload, mime_type="image/gif")

    assert raw_result.envelope.sha256 == _digest(payload)
    assert encoded_result.envelope.sha256 == _digest(payload)
    assert "sha256" not in inspect.signature(inspect_image_bytes).parameters
    assert "sha256" not in inspect.signature(ingest_image).parameters
    with pytest.raises(TypeError, match="unexpected keyword argument 'sha256'"):
        inspect_image_bytes(
            payload,
            scope=SCOPE,
            authorized_scopes={SCOPE},
            source=SOURCE,
            sha256="0" * 64,  # type: ignore[call-arg]
        )


def test_oversized_base64_is_rejected_before_decode(monkeypatch):
    encoded = "A" * ((((DEFAULT_MAX_IMAGE_BYTES + 2) // 3) * 4) + 4)
    decoded = []

    def unexpected_decode(*_args, **_kwargs):
        decoded.append(True)
        raise AssertionError("oversized payload reached the decoder")

    monkeypatch.setattr(ingress_mod.base64, "b64decode", unexpected_decode)

    with _rejected("size-limit") as caught:
        ingest_image(
            encoded,
            scope=SCOPE,
            authorized_scopes={SCOPE},
            source=SOURCE,
        )

    assert decoded == []


def test_raw_entry_point_never_raises_its_cap_above_attachment_policy():
    payload = b"x" * (ATTACHMENT_IMAGE_MAX_BYTES + 1)

    with _rejected("size-limit") as caught:
        _raw(payload, max_bytes=ATTACHMENT_IMAGE_MAX_BYTES + 1)
