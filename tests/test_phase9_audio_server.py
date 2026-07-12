"""Focused server integration coverage for Phase 9 audio ingress."""
from __future__ import annotations

import hashlib
import io
import json
import wave

import pytest
from fastapi.testclient import TestClient

import server
from alpecca import people
from alpecca.audio_ingress import MAX_AUDIO_DURATION_SECONDS


def _wav(*, duration_seconds: float = 0.5, sample_rate: int = 100) -> bytes:
    frame_count = int(duration_seconds * sample_rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * frame_count)
    return buffer.getvalue()


def _auth_headers(content_type: str = "audio/wav") -> dict[str, str]:
    return {
        server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET,
        "Content-Type": content_type,
    }


def _assert_audio_perception(
    perception: dict[str, object],
    payload: bytes,
    *,
    source: str,
    scope_prefix: str,
    status: str,
    duration_seconds: float = 0.5,
) -> None:
    assert perception["status"] == status
    assert perception["source"] == source
    assert perception["mime_type"] == "audio/wav"
    assert perception["attachment_type"] == "audio"
    assert str(perception["scope"]).startswith(scope_prefix)
    digest = hashlib.sha256(payload).hexdigest()
    assert perception["sha256"] == digest
    assert perception["provenance"] == f"sha256:{digest}"
    metadata = perception["metadata"]
    assert metadata["size_bytes"] == len(payload)
    assert metadata["width"] is None
    assert metadata["height"] is None
    assert metadata["duration_seconds"] == pytest.approx(duration_seconds)
    assert perception["classification"] == {
        "processing_location": "local-only",
        "cloud_egress": "denied",
    }
    serialized = json.dumps(perception, sort_keys=True)
    assert "audio_bytes" not in serialized
    assert payload.hex() not in serialized


@pytest.fixture
def client():
    test_client = TestClient(server.app)
    try:
        yield test_client
    finally:
        test_client.close()


@pytest.fixture(autouse=True)
def audio_models(monkeypatch):
    state: dict[str, object] = {
        "transcript": "locally transcribed words",
        "identity": None,
        "enrolled": True,
        "hearing_calls": [],
        "identify_calls": [],
        "enroll_calls": [],
        "speaker_calls": [],
        "audit_calls": [],
    }

    def fake_transcribe(audio_bytes: bytes):
        state["hearing_calls"].append(audio_bytes)
        return state["transcript"]

    def fake_identify(audio_bytes: bytes):
        state["identify_calls"].append(audio_bytes)
        return state["identity"]

    def fake_enroll(audio_bytes: bytes):
        state["enroll_calls"].append(audio_bytes)
        return state["enrolled"]

    async def fake_audit(capability: str, **kwargs: str) -> bool:
        state["audit_calls"].append((capability, kwargs))
        return True

    monkeypatch.setattr(server.hearing, "transcribe", fake_transcribe)
    monkeypatch.setattr(people, "identify_voice", fake_identify)
    monkeypatch.setattr(people, "enroll_creator_voice", fake_enroll)
    monkeypatch.setattr(server, "_record_capability_use", fake_audit)
    monkeypatch.setattr(
        server.mind,
        "set_speaker",
        lambda identity: state["speaker_calls"].append(identity),
    )
    return state


@pytest.mark.parametrize("path", ("/listen", "/people/enroll_voice"))
def test_audio_routes_require_creator_before_body_or_models(
    client, monkeypatch, audio_models, path
):
    body_reads = []

    async def unexpected_body_read(*_args, **_kwargs):
        body_reads.append(True)
        raise AssertionError("unauthorized request body was read")

    monkeypatch.setattr(server, "_read_bounded_body", unexpected_body_read)

    response = client.post(
        path,
        headers={"Content-Type": "audio/wav"},
        content=_wav(),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "authorization required"
    assert body_reads == []
    assert audio_models["hearing_calls"] == []
    assert audio_models["identify_calls"] == []
    assert audio_models["enroll_calls"] == []
    assert audio_models["audit_calls"] == []


def test_listen_valid_wav_calls_local_hearing_once_and_returns_metadata(
    client, audio_models
):
    payload = _wav()
    audio_models["identity"] = "creator"

    response = client.post(
        "/listen",
        headers=_auth_headers(),
        content=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "locally transcribed words"
    assert body["heard"] is True
    assert body["speaker"] == "creator"
    assert audio_models["hearing_calls"] == [payload]
    assert audio_models["identify_calls"] == [payload]
    assert audio_models["speaker_calls"] == ["creator"]
    assert audio_models["enroll_calls"] == []
    assert audio_models["audit_calls"] == [(
        "microphone",
        {"action": "capture", "principal": "creator", "source": "api"},
    )]
    _assert_audio_perception(
        body["perception"],
        payload,
        source="house-hq:push-to-talk",
        scope_prefix="listen:",
        status="transcribed",
    )


@pytest.mark.parametrize(
    ("payload", "content_type", "expected_status", "expected_reason"),
    (
        (_wav(), "audio/ogg", 415, "mime-mismatch"),
        (_wav(), "audio/mp4", 415, "unsupported-mime"),
        (_wav()[:-1], "audio/wav", 400, "malformed-audio"),
        (
            _wav(duration_seconds=MAX_AUDIO_DURATION_SECONDS + 1, sample_rate=1),
            "audio/wav",
            422,
            "duration-limit",
        ),
    ),
    ids=("mime-mismatch", "unsupported-mime", "truncated", "duration-limit"),
)
def test_listen_rejects_invalid_audio_before_hearing(
    client,
    audio_models,
    payload,
    content_type,
    expected_status,
    expected_reason,
):
    response = client.post(
        "/listen",
        headers=_auth_headers(content_type),
        content=payload,
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == {
        "code": "attachment_rejected",
        "reason": expected_reason,
    }
    assert audio_models["hearing_calls"] == []
    assert audio_models["identify_calls"] == []
    assert audio_models["audit_calls"] == []
    assert audio_models["speaker_calls"] == []


def test_listen_rejects_oversize_body_before_hearing(
    client, monkeypatch, audio_models
):
    monkeypatch.setattr(server.audio_ingress_mod, "MAX_AUDIO_BYTES", 32)

    response = client.post(
        "/listen",
        headers=_auth_headers(),
        content=b"x" * 33,
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "attachment is too large"
    assert audio_models["hearing_calls"] == []
    assert audio_models["identify_calls"] == []
    assert audio_models["audit_calls"] == []


def test_listen_no_transcript_returns_scoped_metadata_status(client, audio_models):
    payload = _wav()
    audio_models["transcript"] = None

    response = client.post(
        "/listen",
        headers=_auth_headers(),
        content=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == ""
    assert body["heard"] is False
    assert body["speaker"] == ""
    assert audio_models["hearing_calls"] == [payload]
    assert audio_models["identify_calls"] == [payload]
    assert audio_models["audit_calls"] == [(
        "microphone",
        {"action": "capture", "principal": "creator", "source": "api"},
    )]
    _assert_audio_perception(
        body["perception"],
        payload,
        source="house-hq:push-to-talk",
        scope_prefix="listen:",
        status="no-transcript",
    )


def test_listen_fails_closed_when_capability_receipt_cannot_commit(
    client, monkeypatch, audio_models
):
    async def failed_audit(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(server, "_record_capability_use", failed_audit)
    response = client.post(
        "/listen",
        headers=_auth_headers(),
        content=_wav(),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "capability_audit_unavailable"}
    assert audio_models["hearing_calls"] == []
    assert audio_models["identify_calls"] == []


def test_enroll_voice_uses_audio_guard_and_returns_scoped_envelope(
    client, audio_models
):
    payload = _wav()

    response = client.post(
        "/people/enroll_voice",
        headers=_auth_headers(),
        content=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert audio_models["enroll_calls"] == [payload]
    assert audio_models["hearing_calls"] == []
    assert audio_models["identify_calls"] == []
    assert audio_models["audit_calls"] == [(
        "microphone",
        {"action": "capture", "principal": "creator", "source": "api"},
    )]
    _assert_audio_perception(
        body["perception"],
        payload,
        source="house-hq:voice-enrollment",
        scope_prefix="voice-enrollment:",
        status="enrolled",
    )


def test_enroll_voice_rejects_mime_mismatch_before_embedding(client, audio_models):
    response = client.post(
        "/people/enroll_voice",
        headers=_auth_headers("audio/ogg"),
        content=_wav(),
    )

    assert response.status_code == 415
    assert response.json()["detail"] == {
        "code": "attachment_rejected",
        "reason": "mime-mismatch",
    }
    assert audio_models["enroll_calls"] == []
    assert audio_models["hearing_calls"] == []
    assert audio_models["identify_calls"] == []
    assert audio_models["audit_calls"] == []
