from __future__ import annotations

import base64
import importlib
import io
import json
import math

import pytest

from alpecca import face_worker


JPEG = b"\xff\xd8\xff" + b"bounded-test-image" + b"\xff\xd9"


def _seal(payload: bytes) -> bytes:
    return b"test-seal:" + payload[::-1]


def _open(payload: bytes) -> bytes:
    assert payload.startswith(b"test-seal:")
    return payload[len(b"test-seal:") :][::-1]


def _image(
    payload: bytes = JPEG,
    *,
    width: int = 320,
    height: int = 240,
    channels: int = 3,
) -> dict[str, object]:
    return {
        "encoding": "jpeg",
        "width": width,
        "height": height,
        "channels": channels,
        "data_b64": base64.b64encode(payload).decode("ascii"),
    }


def _request(operation: str, **values: object) -> dict[str, object]:
    return {
        "schema": face_worker.REQUEST_SCHEMA,
        "id": f"request-{operation}",
        "op": operation,
        **values,
    }


class FakeSFaceBackend:
    name = "fake-yunet-sface-cpu"
    device = "cpu"
    available = True
    unavailable_reason = ""

    def __init__(self) -> None:
        self.observations = 0

    def observe(self, packet):
        self.observations += 1
        assert packet.width == 320
        return face_worker.FaceObservation(
            template=(0.6, 0.8),
            detection_confidence=0.97,
            bounding_box=(10, 20, 100, 120),
        )

    def similarity(self, enrolled, observed):
        return sum(left * right for left, right in zip(enrolled, observed))


@pytest.fixture
def worker(tmp_path):
    return face_worker.FaceWorker(
        tmp_path / "face-templates.sealed",
        encrypt=_seal,
        decrypt=_open,
        backend=FakeSFaceBackend(),
    )


def test_default_worker_is_deterministically_unavailable_without_models(tmp_path):
    worker = face_worker.FaceWorker(
        tmp_path / "unused.sealed", encrypt=_seal, decrypt=_open
    )

    status = worker.handle(_request("status"))
    compared = worker.handle(
        _request("compare", profile_id="creator", image=_image())
    )

    assert status["status"] == "unavailable"
    assert status["reason"] == "models_not_configured"
    assert compared["status"] == "unavailable"
    assert compared["reason"] == "models_not_configured"
    assert compared["operation"] == "compare"
    assert compared["may_authenticate"] is False
    assert compared["may_authorize_creator"] is False
    assert compared["may_grant_authority"] is False
    assert not (tmp_path / "unused.sealed").exists()


def test_status_is_cpu_and_familiarity_only(worker):
    result = worker.handle(_request("status"))

    assert result["status"] == "ready"
    assert result["device"] == "cpu"
    assert result["purpose"] == "familiarity-only"
    assert result["may_authenticate"] is False
    assert result["may_authorize_creator"] is False
    assert result["may_grant_authority"] is False


def test_enroll_and_compare_store_only_encrypted_sface_template(worker, tmp_path):
    enrolled = worker.handle(
        _request("enroll", profile_id="creator", image=_image())
    )
    compared = worker.handle(
        _request("compare", profile_id="creator", image=_image())
    )

    assert enrolled["enrolled"] is True
    assert enrolled["image_retained"] is False
    assert compared["score"] == 1.0
    assert compared["familiarity"] == "familiar"
    assert compared["may_authenticate"] is False
    assert compared["may_authorize_creator"] is False
    assert compared["may_grant_authority"] is False

    stored = (tmp_path / "face-templates.sealed").read_bytes()
    assert b'"template"' not in stored
    assert base64.b64encode(JPEG) not in stored
    opened = face_worker.EncryptedFaceTemplateStore(
        tmp_path / "face-templates.sealed", encrypt=_seal, decrypt=_open
    ).load()
    assert opened["creator"]["backend"] == "fake-yunet-sface-cpu"
    assert opened["creator"]["template"] == [0.6, 0.8]


def test_identity_sealing_callback_is_rejected(worker, tmp_path):
    unsafe = face_worker.FaceWorker(
        tmp_path / "unsafe.sealed",
        encrypt=lambda payload: payload,
        decrypt=lambda payload: payload,
        backend=FakeSFaceBackend(),
    )

    response = face_worker.protocol_response(
        unsafe, _request("enroll", profile_id="creator", image=_image())
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "store_error"
    assert not (tmp_path / "unsafe.sealed").exists()


@pytest.mark.parametrize(
    "mutate, code",
    [
        (lambda image: image.update(width=4097), "invalid_image_metadata"),
        (lambda image: image.update(width=4000, height=4000), "image_too_large"),
        (lambda image: image.update(channels=2), "invalid_image_metadata"),
        (lambda image: image.update(data_b64="not base64"), "invalid_image"),
        (
            lambda image: image.update(
                data_b64=base64.b64encode(b"not-a-jpeg").decode("ascii")
            ),
            "invalid_image",
        ),
    ],
)
def test_image_metadata_and_bytes_are_bounded(worker, mutate, code):
    image = _image()
    mutate(image)

    response = face_worker.protocol_response(
        worker, _request("enroll", profile_id="creator", image=image)
    )

    assert response["ok"] is False
    assert response["error"]["code"] == code


def test_backend_must_return_bounded_similarity(worker):
    worker.handle(_request("enroll", profile_id="creator", image=_image()))
    worker.backend.similarity = lambda enrolled, observed: math.nan

    response = face_worker.protocol_response(
        worker, _request("compare", profile_id="creator", image=_image())
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "backend_error"


def test_encoded_image_byte_limit_is_enforced(worker, monkeypatch):
    monkeypatch.setattr(face_worker, "MAX_IMAGE_BYTES", 8)

    response = face_worker.protocol_response(
        worker, _request("enroll", profile_id="creator", image=_image())
    )

    assert response["ok"] is False
    assert response["error"]["code"] == "image_too_large"


def test_json_lines_contract_handles_multiple_requests_and_invalid_json(worker):
    requests = [
        _request("status"),
        _request("enroll", profile_id="creator", image=_image()),
        _request("compare", profile_id="creator", image=_image()),
    ]
    reader = io.StringIO("\n".join(json.dumps(item) for item in requests) + "\n{bad\n")
    writer = io.StringIO()

    face_worker.serve_json_lines(worker, reader, writer)
    responses = [json.loads(line) for line in writer.getvalue().splitlines()]

    assert [response["ok"] for response in responses] == [True, True, True, False]
    assert responses[2]["result"]["score"] == 1.0
    assert responses[3]["error"]["code"] == "invalid_json"
    assert all(response["schema"] == face_worker.RESPONSE_SCHEMA for response in responses)


def test_json_lines_rejects_an_oversized_request_before_parsing(worker, monkeypatch):
    monkeypatch.setattr(face_worker, "MAX_JSON_LINE_BYTES", 16)
    writer = io.StringIO()

    face_worker.serve_json_lines(worker, io.StringIO('{"oversized":true}\n'), writer)
    response = json.loads(writer.getvalue())

    assert response["ok"] is False
    assert response["error"]["code"] == "request_too_large"


def test_opencv_probe_and_import_are_lazy(monkeypatch, tmp_path):
    imported = []
    monkeypatch.setattr(face_worker, "opencv_available", lambda: True)
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: imported.append(name) or object(),
    )
    backend = face_worker.select_backend(
        detector_model=tmp_path / "yunet.onnx",
        recognizer_model=tmp_path / "sface.onnx",
        opencv_factory=lambda cv2, numpy, detector, recognizer: FakeSFaceBackend(),
    )

    assert backend.name == "opencv-yunet-sface-cpu"
    assert imported == []
    backend.observe(face_worker.parse_image(_image()))
    assert imported == ["cv2", "numpy"]


def test_status_loads_both_configured_models_before_reporting_ready(
    monkeypatch, tmp_path
):
    imported = []
    loaded_paths = []
    detector = tmp_path / "yunet.onnx"
    recognizer = tmp_path / "sface.onnx"
    monkeypatch.setattr(face_worker, "opencv_available", lambda: True)
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: imported.append(name) or object(),
    )

    def factory(_cv2, _numpy, detector_path, recognizer_path):
        loaded_paths.extend((detector_path, recognizer_path))
        return FakeSFaceBackend()

    worker = face_worker.FaceWorker(
        tmp_path / "unused.sealed",
        encrypt=_seal,
        decrypt=_open,
        detector_model=detector,
        recognizer_model=recognizer,
        opencv_factory=factory,
    )

    status = worker.handle(_request("status"))

    assert status["status"] == "ready"
    assert imported == ["cv2", "numpy"]
    assert loaded_paths == [detector, recognizer]


def test_status_does_not_report_ready_when_configured_model_pair_fails(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(face_worker, "opencv_available", lambda: True)
    monkeypatch.setattr(importlib, "import_module", lambda _name: object())

    def failing_factory(_cv2, _numpy, _detector, _recognizer):
        raise face_worker.FaceWorkerError(
            "backend_unavailable", "configured model pair failed to load"
        )

    worker = face_worker.FaceWorker(
        tmp_path / "unused.sealed",
        encrypt=_seal,
        decrypt=_open,
        detector_model=tmp_path / "yunet.onnx",
        recognizer_model=tmp_path / "sface.onnx",
        opencv_factory=failing_factory,
    )

    status = worker.handle(_request("status"))

    assert status["status"] == "unavailable"
    assert status["reason"] == "model_load_failed"


def test_lazy_model_load_failure_becomes_stable_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(face_worker, "opencv_available", lambda: True)
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ImportError(name)),
    )
    worker = face_worker.FaceWorker(
        tmp_path / "unused.sealed",
        encrypt=_seal,
        decrypt=_open,
        detector_model=tmp_path / "yunet.onnx",
        recognizer_model=tmp_path / "sface.onnx",
    )

    status = worker.handle(_request("status"))
    first = face_worker.protocol_response(
        worker, _request("compare", profile_id="creator", image=_image())
    )
    second = face_worker.protocol_response(
        worker, _request("compare", profile_id="creator", image=_image())
    )

    assert status["status"] == "unavailable"
    assert status["reason"] == "model_load_failed"
    assert first == second
    assert first["ok"] is True
    assert first["result"]["status"] == "unavailable"
    assert first["result"]["reason"] == "model_load_failed"
    assert first["result"]["may_authorize_creator"] is False


def test_non_cpu_backend_is_rejected(tmp_path):
    backend = FakeSFaceBackend()
    backend.device = "cuda"

    with pytest.raises(ValueError, match="CPU-only"):
        face_worker.FaceWorker(
            tmp_path / "unused.sealed",
            encrypt=_seal,
            decrypt=_open,
            backend=backend,
        )


def test_inference_failure_invalidates_subsequent_health(worker):
    worker.backend.observe = lambda _packet: (_ for _ in ()).throw(
        RuntimeError("camera inference stopped")
    )

    failed = face_worker.protocol_response(
        worker, _request("enroll", profile_id="creator", image=_image())
    )
    status = worker.handle(_request("status"))

    assert failed["ok"] is False
    assert status["status"] == "unavailable"
    assert status["reason"] == "face_backend_inference_failed"
    assert status["inference_verified"] is False
