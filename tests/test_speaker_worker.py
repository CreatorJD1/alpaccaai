from __future__ import annotations

import base64
import importlib
import io
import json
import math
import struct
import threading
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
        backend=speaker_worker.SherpaOnnxBackend(
            lambda _pcm_f32, _sample_rate_hz: [1.0, 0.5, 0.25]
        ),
    )


def test_status_is_cpu_familiarity_only_for_recognition_backend(worker):
    result = worker.handle(_request("status"))

    assert result["status"] == "ready"
    assert result["purpose"] == "familiarity-only"
    assert result["recognition_ready"] is True
    assert result["evidence_kind"] == "speaker-embedding-similarity"
    assert result["may_authenticate"] is False
    assert result["may_grant_authority"] is False
    assert result["device"] == "cpu"
    assert result["backend"] == "sherpa-onnx-cpu"
    assert result["enrolled_profiles"] == 0


def test_sherpa_readiness_probe_is_lazy_cached_and_does_not_retain_audio(tmp_path):
    observed = []

    def extractor(pcm_f32: bytes, sample_rate_hz: int):
        observed.append((len(pcm_f32), sample_rate_hz))
        return [1.0, 0.5, 0.25]

    backend = speaker_worker.SherpaOnnxBackend(extractor)
    probed = speaker_worker.SpeakerWorker(
        tmp_path / "probe-profiles.sealed",
        encrypt=_seal,
        decrypt=_open,
        backend=backend,
    )

    assert observed == []
    first = probed.handle(_request("status"))
    second = probed.handle(_request("status"))

    assert first["status"] == second["status"] == "ready"
    assert len(observed) == 1
    assert observed[0] == (
        int(16_000 * speaker_worker.READINESS_PROBE_AUDIO_SECONDS) * 4,
        16_000,
    )
    assert first["audio_retained"] is False
    assert not any(
        isinstance(value, (bytes, bytearray, speaker_worker.AudioPacket))
        for value in vars(backend).values()
    )


@pytest.mark.parametrize(
    "extractor, reason",
    [
        (
            lambda _pcm_f32, _sample_rate_hz: (_ for _ in ()).throw(RuntimeError("broken")),
            "speaker_recognition_probe_failed",
        ),
        (lambda _pcm_f32, _sample_rate_hz: [], "speaker_recognition_probe_failed"),
    ],
)
def test_broken_sherpa_probe_stays_unavailable_and_never_processes_user_audio(
    tmp_path, extractor, reason
):
    calls = []

    def observed_extractor(pcm_f32: bytes, sample_rate_hz: int):
        calls.append((len(pcm_f32), sample_rate_hz))
        return extractor(pcm_f32, sample_rate_hz)

    backend = speaker_worker.SherpaOnnxBackend(observed_extractor)
    probed = speaker_worker.SpeakerWorker(
        tmp_path / "broken-profiles.sealed",
        encrypt=_seal,
        decrypt=_open,
        backend=backend,
    )

    status = probed.handle(_request("status"))
    enrolled = probed.handle(
        _request("enroll", profile_id="creator", audio=_audio(_pcm()))
    )

    assert status["status"] == "unavailable"
    assert status["recognition_ready"] is False
    assert status["reason"] == reason
    assert enrolled["status"] == "unavailable"
    assert enrolled["reason"] == reason
    assert enrolled["may_authenticate"] is False
    assert enrolled["may_grant_authority"] is False
    assert len(calls) == 1
    assert not (tmp_path / "broken-profiles.sealed").exists()


def test_static_recognition_flag_without_real_probe_cannot_report_ready(tmp_path):
    class FlagOnlyBackend:
        name = "flag-only"
        device = "cpu"
        recognition_capable = True

        def embed(self, _packet):
            raise AssertionError("embed must not run without a readiness probe")

    probed = speaker_worker.SpeakerWorker(
        tmp_path / "flag-only-profiles.sealed",
        encrypt=_seal,
        decrypt=_open,
        backend=FlagOnlyBackend(),
    )

    status = probed.handle(_request("status"))

    assert status["status"] == "unavailable"
    assert status["recognition_ready"] is False
    assert status["reason"] == "speaker_recognition_probe_unavailable"
    assert status["evidence_kind"] == "none"
    assert status["may_authenticate"] is False


def test_sherpa_probe_timeout_fails_closed_and_is_not_retried(tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def extractor(_pcm_f32: bytes, _sample_rate_hz: int):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(1.0)
        return [1.0, 0.5, 0.25]

    monkeypatch.setattr(speaker_worker, "READINESS_PROBE_TIMEOUT_SECONDS", 0.01)
    probed = speaker_worker.SpeakerWorker(
        tmp_path / "timeout-profiles.sealed",
        encrypt=_seal,
        decrypt=_open,
        backend=speaker_worker.SherpaOnnxBackend(extractor),
    )

    try:
        first = probed.handle(_request("status"))
        assert started.wait(0.2)
        second = probed.handle(_request("status"))
    finally:
        release.set()

    assert first["status"] == second["status"] == "unavailable"
    assert first["reason"] == "speaker_recognition_probe_timeout"
    assert calls == 1


def test_enroll_inference_failure_invalidates_cached_readiness_until_restart(tmp_path):
    calls = 0

    def extractor(_pcm_f32: bytes, _sample_rate_hz: int):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [1.0, 0.5, 0.25]
        raise RuntimeError("private backend failure")

    probed = speaker_worker.SpeakerWorker(
        tmp_path / "enroll-failure-profiles.sealed",
        encrypt=_seal,
        decrypt=_open,
        backend=speaker_worker.SherpaOnnxBackend(extractor),
    )
    pcm = _pcm()

    assert probed.handle(_request("status"))["status"] == "ready"
    enrolled = probed.handle(
        _request("enroll", profile_id="creator", audio=_audio(pcm))
    )
    status = probed.handle(_request("status"))

    assert enrolled["status"] == "unavailable"
    assert enrolled["reason"] == "speaker_recognition_backend_failed"
    assert enrolled["recognition_ready"] is False
    assert enrolled["audio_retained"] is False
    assert "score" not in enrolled
    assert "familiarity" not in enrolled
    assert status["status"] == "unavailable"
    assert status["reason"] == "speaker_recognition_backend_failed"
    assert calls == 2
    assert not (tmp_path / "enroll-failure-profiles.sealed").exists()


def test_compare_inference_failure_invalidates_without_label_or_retry(tmp_path):
    calls = 0

    def extractor(_pcm_f32: bytes, _sample_rate_hz: int):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return [1.0, 0.5, 0.25]
        raise RuntimeError("private backend failure")

    store_path = tmp_path / "compare-failure-profiles.sealed"
    probed = speaker_worker.SpeakerWorker(
        store_path,
        encrypt=_seal,
        decrypt=_open,
        backend=speaker_worker.SherpaOnnxBackend(extractor),
    )
    pcm = _pcm()

    assert probed.handle(_request("status"))["status"] == "ready"
    assert probed.handle(
        _request("enroll", profile_id="creator", audio=_audio(pcm))
    )["status"] == "ready"
    compared = probed.handle(
        _request("compare", profile_id="creator", audio=_audio(pcm))
    )
    status = probed.handle(_request("status"))

    assert compared["status"] == "unavailable"
    assert compared["reason"] == "speaker_recognition_backend_failed"
    assert compared["recognition_ready"] is False
    assert compared["audio_retained"] is False
    assert compared["may_authenticate"] is False
    assert compared["may_grant_authority"] is False
    assert "score" not in compared
    assert "familiarity" not in compared
    assert status["status"] == "unavailable"
    assert status["reason"] == "speaker_recognition_backend_failed"
    assert calls == 3
    assert base64.b64encode(pcm) not in store_path.read_bytes()


def test_default_fallback_never_enrolls_or_labels_speaker_as_familiar(tmp_path):
    fallback = speaker_worker.SpeakerWorker(
        tmp_path / "fallback-profiles.sealed",
        encrypt=_seal,
        decrypt=_open,
        prefer_sherpa=False,
    )
    pcm = _pcm()

    status = fallback.handle(_request("status"))
    enrolled = fallback.handle(
        _request("enroll", profile_id="creator", audio=_audio(pcm))
    )
    compared = fallback.handle(
        _request("compare", profile_id="creator", audio=_audio(pcm))
    )

    assert status["status"] == "unavailable"
    assert status["recognition_ready"] is False
    assert status["evidence_kind"] == "none"
    assert enrolled["status"] == "unavailable"
    assert compared["status"] == "unavailable"
    assert enrolled["may_authenticate"] is False
    assert compared["may_authenticate"] is False
    assert "score" not in compared
    assert "familiarity" not in compared
    assert not (tmp_path / "fallback-profiles.sealed").exists()


def test_enroll_and_compare_are_deterministic_and_store_only_sealed_embeddings(
    worker, tmp_path
):
    pcm = _pcm()
    enrolled = worker.handle(_request("enroll", profile_id="creator", audio=_audio(pcm)))
    compared = worker.handle(_request("compare", profile_id="creator", audio=_audio(pcm)))

    assert enrolled == {
        "status": "ready",
        "profile_id": "creator",
        "enrolled": True,
        "backend": "sherpa-onnx-cpu",
        "purpose": "familiarity-only",
        "recognition_ready": True,
        "evidence_kind": "speaker-embedding-similarity",
        "may_authenticate": False,
        "may_grant_authority": False,
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
    ).load()["creator"]["backend"] == "sherpa-onnx-cpu"


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
        backend=speaker_worker.SherpaOnnxBackend(
            lambda _pcm_f32, _sample_rate_hz: [1.0, 0.5, 0.25]
        ),
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
    assert backend.recognition_capable is False
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
    assert backend.recognition_capable is True
    assert len(vector) == 3
    assert observed and observed[0][1] == 16_000
