"""Focused adversarial coverage for pure Phase 9 audio ingress."""
from __future__ import annotations

from contextlib import contextmanager
import dataclasses
import hashlib
import inspect
import io
import json
from types import SimpleNamespace
import wave

import pytest

from alpecca import audio_ingress as ingress_mod
from alpecca.attachment_perception import AttachmentPerceptionEnvelope
from alpecca.audio_ingress import (
    MAX_AUDIO_BYTES,
    MAX_AUDIO_DURATION_SECONDS,
    AudioIngressRejected,
    inspect_audio_bytes,
)


SCOPE = "creator-private"
SOURCE = "chat:voice-note"


def _wav(*, duration_seconds: float = 0.5, sample_rate: int = 100) -> bytes:
    frame_count = int(duration_seconds * sample_rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * frame_count)
    return buffer.getvalue()


def _inspect(payload: bytes, *, mime_type: str = "audio/wav", **overrides):
    values = {
        "scope": SCOPE,
        "authorized_scopes": {SCOPE},
        "source": SOURCE,
        "declared_mime_type": mime_type,
    }
    values.update(overrides)
    return inspect_audio_bytes(payload, **values)


@contextmanager
def _rejected(reason: str):
    with pytest.raises(AudioIngressRejected) as caught:
        yield caught
    assert caught.value.reason == reason


@pytest.mark.parametrize(
    ("mime_type", "expected_mime"),
    (
        ("audio/wav", "audio/wav"),
        (" AUDIO/X-WAV ", "audio/x-wav"),
    ),
)
def test_wav_bytes_are_duration_measured_scoped_and_provenanced(mime_type, expected_mime):
    payload = _wav(duration_seconds=0.5)

    result = _inspect(payload, mime_type=mime_type)

    assert isinstance(result.envelope, AttachmentPerceptionEnvelope)
    assert result.audio_bytes == payload
    assert result.mime_type == expected_mime
    assert result.duration_seconds == pytest.approx(0.5)
    assert result.envelope.scope == SCOPE
    assert result.envelope.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.envelope.processing_location == "local-only"
    assert result.envelope.cloud_egress == "denied"


def test_as_dict_is_metadata_only_and_audio_bytes_are_immutable():
    payload = _wav()
    result = _inspect(payload)

    assert result.as_dict() == result.envelope.as_dict()
    serialized = json.dumps(result.as_dict(), sort_keys=True)
    assert "audio_bytes" not in serialized
    assert payload.hex() not in serialized
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.audio_bytes = b"changed"  # type: ignore[misc]


@pytest.mark.parametrize("mime_type", ("audio/webm", "audio/ogg"))
def test_declared_mime_must_match_container_magic(mime_type):
    with _rejected("mime-mismatch"):
        _inspect(_wav(), mime_type=mime_type)


@pytest.mark.parametrize("value", (b"", bytearray(b"RIFF"), memoryview(b"RIFF"), "RIFF"))
def test_raw_bytes_entry_point_rejects_non_bytes_or_empty_values(value):
    with _rejected("invalid-bytes"):
        _inspect(value)  # type: ignore[arg-type]


def test_unsupported_mime_is_rejected_before_audio_parser():
    with _rejected("unsupported-mime"):
        _inspect(_wav(), mime_type="audio/mp4")


def test_hard_cap_is_enforced_before_any_duration_parser(monkeypatch):
    payload = b"RIFF\x00\x00\x00\x00WAVE" + b"x" * (MAX_AUDIO_BYTES + 1)
    parsed = []

    def unexpected_parser(*_args, **_kwargs):
        parsed.append(True)
        raise AssertionError("oversized audio reached a duration parser")

    monkeypatch.setattr(ingress_mod, "_wav_duration", unexpected_parser)

    with _rejected("size-limit"):
        _inspect(payload, max_bytes=MAX_AUDIO_BYTES + 1)

    assert parsed == []


def test_wav_magic_without_a_parseable_wave_is_rejected():
    with _rejected("malformed-audio"):
        _inspect(b"RIFF\x00\x00\x00\x00WAVE")


def test_truncated_wav_sample_payload_is_rejected():
    with _rejected("malformed-audio"):
        _inspect(_wav(duration_seconds=0.5)[:-1])


def test_wav_duration_over_sixty_seconds_is_rejected():
    payload = _wav(duration_seconds=MAX_AUDIO_DURATION_SECONDS + 1, sample_rate=1)

    with _rejected("duration-limit"):
        _inspect(payload)


class _FakeContainer:
    def __init__(self, duration: int | None, streams: tuple[object, ...]) -> None:
        self.duration = duration
        self.streams = streams
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeAv:
    time_base = 1_000_000

    def __init__(self, duration: int | None, *, opens: list[tuple[object, str, str]]) -> None:
        self.duration = duration
        self.opens = opens
        self.container: _FakeContainer | None = None

    def open(self, buffer: io.BytesIO, *, mode: str, format: str) -> _FakeContainer:
        self.opens.append((buffer, mode, format))
        self.container = _FakeContainer(
            self.duration,
            (SimpleNamespace(type="audio", duration=None, time_base=None),),
        )
        return self.container


def test_webm_duration_uses_optional_pyav_against_bytesio_only(monkeypatch):
    payload = b"\x1a\x45\xdf\xa3not-a-real-webm-but-a-fake-probe-fixture"
    opens: list[tuple[object, str, str]] = []
    fake_av = _FakeAv(1_250_000, opens=opens)
    monkeypatch.setattr(ingress_mod, "_optional_av_module", lambda: fake_av)

    result = _inspect(payload, mime_type="audio/webm")

    assert result.duration_seconds == pytest.approx(1.25)
    assert len(opens) == 1
    buffer, mode, format_name = opens[0]
    assert isinstance(buffer, io.BytesIO)
    assert buffer.getvalue() == payload
    assert (mode, format_name) == ("r", "webm")
    assert fake_av.container is not None and fake_av.container.closed is True


@pytest.mark.parametrize(
    ("mime_type", "payload"),
    (
        ("audio/webm", b"\x1a\x45\xdf\xa3minimal-ebml"),
        ("audio/ogg", b"OggSminimal-ogg"),
    ),
)
def test_webm_and_ogg_fail_closed_when_local_duration_probe_is_unavailable(
    monkeypatch, mime_type, payload
):
    monkeypatch.setattr(ingress_mod, "_optional_av_module", lambda: None)

    with _rejected("duration-unavailable"):
        _inspect(payload, mime_type=mime_type)


def test_optional_container_without_duration_is_rejected(monkeypatch):
    payload = b"\x1a\x45\xdf\xa3duration-missing"
    fake_av = _FakeAv(None, opens=[])
    monkeypatch.setattr(ingress_mod, "_optional_av_module", lambda: fake_av)

    with _rejected("duration-unavailable"):
        _inspect(payload, mime_type="audio/webm")


def test_optional_container_parse_failure_is_stably_rejected(monkeypatch):
    class _RaisingAv:
        time_base = 1_000_000

        @staticmethod
        def open(*_args, **_kwargs):
            raise RuntimeError("bad container")

    monkeypatch.setattr(ingress_mod, "_optional_av_module", lambda: _RaisingAv())

    with _rejected("malformed-audio"):
        _inspect(b"OggSbad", mime_type="audio/ogg")


def test_scope_is_exact_and_hash_cannot_be_supplied_by_a_caller():
    payload = _wav()

    with _rejected("unauthorized-scope"):
        _inspect(payload, authorized_scopes={"guest-private"})
    result = _inspect(payload)

    assert result.envelope.sha256 == hashlib.sha256(payload).hexdigest()
    assert "sha256" not in inspect.signature(inspect_audio_bytes).parameters
    with pytest.raises(TypeError, match="unexpected keyword argument 'sha256'"):
        inspect_audio_bytes(
            payload,
            scope=SCOPE,
            authorized_scopes={SCOPE},
            source=SOURCE,
            declared_mime_type="audio/wav",
            sha256="0" * 64,  # type: ignore[call-arg]
        )
