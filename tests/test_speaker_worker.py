from __future__ import annotations

import base64
import importlib
import io
import json
import math
import struct
import wave

import pytest

from alpecca import speaker_worker


def _seal(payload: bytes) -> bytes:
    return b"test-callback:" + payload[::-1]


def _open(payload: bytes) -> bytes:
    assert payload.startswith(b"test-callback:")
    return payload[len(b"test-callback:") :][::-1]


def _pcm(*, frequency: float = 220.0, seconds: float = 0.4, rate: int = 16_000) -> bytes:
    samples = []
    for index in range(int(rate * seconds)):
        value = int(12_000 * math.sin(2.0 * math.pi * frequency * index / rate))
        samples.append(struct.pack("<h", value))
    return b"".join(samples)


def _audio(pcm: bytes, *, rate: int = 16_000) -> dict[str, object]:
    return {
        "encoding": "pcm_s16le",
        "sample_rate_hz": rate,
        "channels": 1,
        "sample_width_bytes": 2,
        "frame_count": len(pcm) // 2,
        "data_b64": base64.b64encode(pcm).decode("ascii"),
    }


def _wav_audio(pcm: bytes, *, declared_rate: int = 16_000) -> dict[str, object]:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(pcm)
    return {
        "encoding": "wav",
        "sample_rate_hz": declared_rate,
        "channels": 1,
        "sample_width_bytes": 2,
        "frame_count": len(pcm) // 2,
        "data_b64": base64.b64encode(output.getvalue()).decode("ascii"),
    }


def _request(operation: str, **values: object) -> dict[str, object]:
    return {
        "schema": speaker_worker.REQUEST_SCHEMA,
        "id": f"request-{operation}",
        "op": operation,
        **values,
    }


@pytest.fixture
def worker(tmp_path):
    return speaker_worker.SpeakerWorker(
        tmp_path / "speaker-profiles.sealed",
        encrypt=_seal,
        decrypt=_open,
        prefer_sherpa=False,
    )


def test_status_is_cpu_familiarity_only_and_does_not_require_sherpa(worker):
    result = worker.handle(_request("status"))

    assert result["purpose"] == "familiarity-only"
    assert result["may_authenticate"] is False
    assert result["may_grant_authority"] is False
    assert result["device"] == "cpu"
    assert result["backend"] == "deterministic-cpu-fallback"
    assert result["enrolled_profiles"] == 0


def test_enroll_and_compare_are_deterministic_and_store_only_sealed_embeddings(
    worker, tmp_path
):
    pcm = _pcm()
    enrolled = worker.handle(_request("enroll", profile_id="creator", audio=_audio(pcm)))
    compared = worker.handle(_request("compare", profile_id="creator", audio=_audio(pcm)))

    assert enrolled == {
        "profile_id": "creator",
        "enrolled": True,
        "backend": "deterministic-cpu-fallback",
        "purpose": "familiarity-only",
        "may_authenticate": False,
        "audio_retained": False,
    }
    assert compared["score"] == 1.0
    assert compared["familiarity"] == "familiar"
    assert compared["may_authenticate"] is False
    assert compared["may_grant_authority"] is False
    assert compared["audio_retained"] is False

    stored = (tmp_path / "speaker-profiles.sealed").read_bytes()
    assert b'"embedding"' not in stored
    assert base64.b64encode(pcm) not in stored
    assert speaker_worker.EncryptedEmbeddingStore(
        tmp_path / "speaker-profiles.sealed", encrypt=_seal, decrypt=_open
    ).load()["creator"]["backend"] == "deterministic-cpu-fallback"


def test_compare_does_not_conflate_a_score_with_authentication(worker):
    worker.handle(_request("enroll", profile_id="known", audio=_audio(_pcm(frequency=180))))
    result = worker.handle(
        _request("compare", profile_id="known", audio=_audio(_pcm(frequency=710)))
    )

    assert 0.0 <= result["score"] <= 1.0
    assert result["familiarity"] in {"familiar", "ambiguous", "unfamiliar"}
    assert result["purpose"] == "familiarity-only"
    assert result["may_authenticate"] is False
    assert result["may_grant_authority"] is False


@pytest.mark.parametrize(
    "mutate, code",
    [
        (lambda audio: audio.update(frame_count=audio["frame_count"] + 1), "audio_metadata_mismatch"),
        (lambda audio: audio.update(sample_rate_hz=12_345), "invalid_audio_metadata"),
        (lambda audio: audio.update(data_b64="not base64"), "invalid_audio"),
    ],
)
def test_pcm_metadata_and_payload_are_strictly_bounded(worker, mutate, code):
    audio = _audio(_pcm())
    mutate(audio)

    response = speaker_worker.protocol_response(
        worker, _request("enroll", profile_id="creator", audio=audio)
    )

    assert response["ok"] is False
    assert response["error"]["code"] == code


def test_wav_header_must_match_supplied_metadata(worker):
    response = speaker_worker.protocol_response(
        worker,
        _request(
            "enroll",
            profile_id="creator",
            audio=_wav_audio(_pcm(), declared_rate=8_000),
        ),
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "audio_metadata_mismatch"


def test_identity_sealing_callback_is_rejected(tmp_path):
    worker = speaker_worker.SpeakerWorker(
        tmp_path / "bad.sealed",
        encrypt=lambda payload: payload,
        decrypt=lambda payload: payload,
    )

    response = speaker_worker.protocol_response(
        worker,
        _request("enroll", profile_id="creator", audio=_audio(_pcm())),
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "store_error"
    assert not (tmp_path / "bad.sealed").exists()


def test_json_lines_contract_handles_multiple_requests_and_invalid_json(worker):
    pcm = _pcm()
    requests = [
        _request("status"),
        _request("enroll", profile_id="creator", audio=_audio(pcm)),
        _request("compare", profile_id="creator", audio=_audio(pcm)),
    ]
    reader = io.StringIO("\n".join(json.dumps(item) for item in requests) + "\n{bad\n")
    writer = io.StringIO()

    speaker_worker.serve_json_lines(worker, reader, writer)
    responses = [json.loads(line) for line in writer.getvalue().splitlines()]

    assert [response["ok"] for response in responses] == [True, True, True, False]
    assert responses[2]["result"]["score"] == 1.0
    assert responses[3]["error"]["code"] == "invalid_json"
    assert all(response["schema"] == speaker_worker.RESPONSE_SCHEMA for response in responses)


def test_sherpa_import_is_lazy_and_missing_package_falls_back(monkeypatch):
    imported = []
    monkeypatch.setattr(speaker_worker, "sherpa_onnx_available", lambda: False)
    monkeypatch.setattr(importlib, "import_module", lambda name: imported.append(name))

    backend = speaker_worker.select_backend(
        prefer_sherpa=True,
        sherpa_factory=lambda _module: pytest.fail("factory must not run"),
    )

    assert backend.name == "deterministic-cpu-fallback"
    assert imported == []


def test_sherpa_factory_can_supply_a_lazy_cpu_extractor(monkeypatch):
    sentinel_module = object()
    monkeypatch.setattr(speaker_worker, "sherpa_onnx_available", lambda: True)
    monkeypatch.setattr(importlib, "import_module", lambda name: sentinel_module)
    observed = []

    def factory(module):
        assert module is sentinel_module

        def extractor(pcm_f32: bytes, sample_rate_hz: int):
            observed.append((len(pcm_f32), sample_rate_hz))
            return [1.0, 0.5, 0.25]

        return extractor

    backend = speaker_worker.select_backend(prefer_sherpa=True, sherpa_factory=factory)
    vector = backend.embed(speaker_worker.parse_audio(_audio(_pcm())))

    assert backend.name == "sherpa-onnx-cpu"
    assert len(vector) == 3
    assert observed and observed[0][1] == 16_000
