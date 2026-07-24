"""Isolated CPU face-familiarity worker with a bounded JSON-lines protocol.

YuNet detection and SFace comparison are optional and loaded only on the first
readiness probe or inference. Results are familiarity signals only: this module cannot
authenticate anyone or authorize the Creator principal. Face templates are
persisted only through caller-supplied encryption and decryption callbacks.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import Callable, Mapping, Protocol, TextIO


REQUEST_SCHEMA = "alpecca.face-worker.request.v1"
RESPONSE_SCHEMA = "alpecca.face-worker.response.v1"
STORE_SCHEMA = "alpecca.face-worker.store.v1"
PURPOSE = "familiarity-only"

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_JSON_LINE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_WIDTH = 4096
MAX_IMAGE_HEIGHT = 4096
MAX_IMAGE_PIXELS = 12_000_000
MAX_PROFILES = 32
MAX_TEMPLATE_DIMENSIONS = 4096
MAX_MODEL_PATH_CHARS = 1024
_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

SealCallback = Callable[[bytes], bytes]
OpenCallback = Callable[[bytes], bytes]
OpenCVFactory = Callable[[object, object, Path, Path], "FaceBackend"]


class FaceWorkerError(ValueError):
    """A bounded protocol error safe to expose to the local caller."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ImagePacket:
    encoded: bytes
    encoding: str
    width: int
    height: int
    channels: int

    @property
    def pixel_count(self) -> int:
        return self.width * self.height


@dataclass(frozen=True, slots=True)
class FaceObservation:
    """One normalized SFace template derived from exactly one detected face."""

    template: tuple[float, ...]
    detection_confidence: float
    bounding_box: tuple[int, int, int, int]


class FaceBackend(Protocol):
    name: str
    device: str
    available: bool
    unavailable_reason: str

    def observe(self, packet: ImagePacket) -> FaceObservation: ...

    def similarity(
        self, enrolled: tuple[float, ...], observed: tuple[float, ...]
    ) -> float: ...


def _bounded_int(value: object, *, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise FaceWorkerError(
            "invalid_image_metadata",
            f"{name} must be an integer from {minimum} to {maximum}",
        )
    return value


def _decode_base64(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise FaceWorkerError(
            "invalid_image", "image data_b64 must be a non-empty string"
        )
    if len(value) > ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 8:
        raise FaceWorkerError(
            "image_too_large", "encoded image exceeds the worker limit"
        )
    try:
        payload = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise FaceWorkerError("invalid_image", "image data_b64 is malformed") from exc
    if not payload:
        raise FaceWorkerError("invalid_image", "image payload is empty")
    if len(payload) > MAX_IMAGE_BYTES:
        raise FaceWorkerError("image_too_large", "image exceeds the worker limit")
    return payload


def parse_image(value: object) -> ImagePacket:
    """Validate bounded encoded bytes and caller-declared image metadata."""

    if not isinstance(value, Mapping):
        raise FaceWorkerError("invalid_image", "image must be an object")
    encoding = str(value.get("encoding") or "").strip().lower()
    if encoding not in {"jpeg", "png"}:
        raise FaceWorkerError("invalid_image", "image encoding must be jpeg or png")
    width = _bounded_int(
        value.get("width"), name="width", minimum=1, maximum=MAX_IMAGE_WIDTH
    )
    height = _bounded_int(
        value.get("height"), name="height", minimum=1, maximum=MAX_IMAGE_HEIGHT
    )
    channels = _bounded_int(
        value.get("channels"), name="channels", minimum=1, maximum=4
    )
    if channels not in {1, 3, 4}:
        raise FaceWorkerError(
            "invalid_image_metadata", "channels must be 1, 3, or 4"
        )
    if width * height > MAX_IMAGE_PIXELS:
        raise FaceWorkerError("image_too_large", "declared image has too many pixels")
    payload = _decode_base64(value.get("data_b64"))
    if encoding == "jpeg" and not (
        payload.startswith(b"\xff\xd8\xff") and payload.endswith(b"\xff\xd9")
    ):
        raise FaceWorkerError("invalid_image", "JPEG signature is invalid")
    if encoding == "png" and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise FaceWorkerError("invalid_image", "PNG signature is invalid")
    return ImagePacket(payload, encoding, width, height, channels)


def _normalize_template(raw: object) -> tuple[float, ...]:
    try:
        values = [float(value) for value in raw]  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise FaceWorkerError(
            "backend_error", "SFace returned an invalid template"
        ) from exc
    if not 1 <= len(values) <= MAX_TEMPLATE_DIMENSIONS:
        raise FaceWorkerError(
            "backend_error", "SFace template dimension is invalid"
        )
    if not all(math.isfinite(value) for value in values):
        raise FaceWorkerError("backend_error", "SFace template is not finite")
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise FaceWorkerError("backend_error", "SFace template has no usable signal")
    return tuple(round(value / norm, 8) for value in values)


class UnavailableFaceBackend:
    """Deterministic fallback that performs no visual identity inference."""

    name = "opencv-yunet-sface-unavailable"
    device = "cpu"
    available = False

    def __init__(self, reason: str = "opencv_unavailable") -> None:
        self.unavailable_reason = reason

    def observe(self, packet: ImagePacket) -> FaceObservation:
        del packet
        raise FaceWorkerError(
            "backend_unavailable", "YuNet/SFace CPU backend is unavailable"
        )

    def similarity(
        self, enrolled: tuple[float, ...], observed: tuple[float, ...]
    ) -> float:
        del enrolled, observed
        raise FaceWorkerError(
            "backend_unavailable", "YuNet/SFace CPU backend is unavailable"
        )


class OpenCVYuNetSFaceBackend:
    """CPU adapter for OpenCV YuNet detection and SFace similarity."""

    name = "opencv-yunet-sface-cpu"
    device = "cpu"
    available = True
    unavailable_reason = ""

    def __init__(
        self,
        cv2_module: object,
        numpy_module: object,
        detector_model: Path,
        recognizer_model: Path,
    ) -> None:
        self._cv2 = cv2_module
        self._numpy = numpy_module
        try:
            self._detector = cv2_module.FaceDetectorYN.create(  # type: ignore[attr-defined]
                str(detector_model), "", (320, 320), 0.9, 0.3, 5000
            )
            self._recognizer = cv2_module.FaceRecognizerSF.create(  # type: ignore[attr-defined]
                str(recognizer_model), ""
            )
        except Exception as exc:
            raise FaceWorkerError(
                "backend_unavailable", "YuNet/SFace models could not be loaded"
            ) from exc

    def _decode(self, packet: ImagePacket) -> object:
        try:
            encoded = self._numpy.frombuffer(packet.encoded, dtype=self._numpy.uint8)
            image = self._cv2.imdecode(encoded, self._cv2.IMREAD_UNCHANGED)
        except Exception as exc:
            raise FaceWorkerError("invalid_image", "image decode failed") from exc
        if image is None:
            raise FaceWorkerError("invalid_image", "image decode failed")
        shape = tuple(int(value) for value in image.shape)
        actual_height, actual_width = shape[:2]
        actual_channels = 1 if len(shape) == 2 else shape[2]
        if (actual_width, actual_height, actual_channels) != (
            packet.width,
            packet.height,
            packet.channels,
        ):
            raise FaceWorkerError(
                "image_metadata_mismatch",
                "decoded image dimensions do not match request metadata",
            )
        if actual_channels == 1:
            image = self._cv2.cvtColor(image, self._cv2.COLOR_GRAY2BGR)
        elif actual_channels == 4:
            image = self._cv2.cvtColor(image, self._cv2.COLOR_BGRA2BGR)
        return image

    def observe(self, packet: ImagePacket) -> FaceObservation:
        image = self._decode(packet)
        try:
            self._detector.setInputSize((packet.width, packet.height))
            _status, faces = self._detector.detect(image)
        except FaceWorkerError:
            raise
        except Exception as exc:
            raise FaceWorkerError("backend_error", "YuNet detection failed") from exc
        count = 0 if faces is None else len(faces)
        if count == 0:
            raise FaceWorkerError("no_face", "YuNet detected no face")
        if count != 1:
            raise FaceWorkerError("multiple_faces", "YuNet detected multiple faces")
        face = faces[0]
        try:
            aligned = self._recognizer.alignCrop(image, face)
            feature = self._recognizer.feature(aligned)
            template = _normalize_template(feature.flatten().tolist())
            confidence = max(0.0, min(1.0, float(face[-1])))
            box = tuple(max(0, int(round(float(face[index])))) for index in range(4))
        except FaceWorkerError:
            raise
        except Exception as exc:
            raise FaceWorkerError("backend_error", "SFace extraction failed") from exc
        return FaceObservation(template, round(confidence, 6), box)  # type: ignore[arg-type]

    def similarity(
        self, enrolled: tuple[float, ...], observed: tuple[float, ...]
    ) -> float:
        if len(enrolled) != len(observed):
            raise FaceWorkerError(
                "template_mismatch", "stored and observed SFace templates differ"
            )
        try:
            left = self._numpy.asarray([enrolled], dtype=self._numpy.float32)
            right = self._numpy.asarray([observed], dtype=self._numpy.float32)
            raw = self._recognizer.match(
                left, right, self._cv2.FaceRecognizerSF_FR_COSINE
            )
            score = float(raw)
        except Exception as exc:
            raise FaceWorkerError("backend_error", "SFace comparison failed") from exc
        if not math.isfinite(score):
            raise FaceWorkerError("backend_error", "SFace similarity is not finite")
        return round(max(0.0, min(1.0, score)), 6)


class LazyOpenCVBackend:
    """Defers OpenCV, NumPy, and model initialization until first inference."""

    name = "opencv-yunet-sface-cpu"
    device = "cpu"
    available = True
    unavailable_reason = ""

    def __init__(
        self,
        detector_model: Path,
        recognizer_model: Path,
        *,
        factory: OpenCVFactory | None = None,
    ) -> None:
        self._detector_model = detector_model
        self._recognizer_model = recognizer_model
        self._factory = factory or OpenCVYuNetSFaceBackend
        self._backend: FaceBackend | None = None
        self._lock = threading.Lock()

    def _load(self) -> FaceBackend:
        if self._backend is not None:
            return self._backend
        with self._lock:
            if self._backend is not None:
                return self._backend
            try:
                cv2_module = importlib.import_module("cv2")
                numpy_module = importlib.import_module("numpy")
                backend = self._factory(
                    cv2_module,
                    numpy_module,
                    self._detector_model,
                    self._recognizer_model,
                )
                if getattr(backend, "device", "") != "cpu":
                    raise ValueError("face backend must be CPU-only")
                self._backend = backend
            except Exception:
                self._backend = UnavailableFaceBackend("model_load_failed")
            return self._backend

    def ensure_available(self) -> bool:
        """Resolve lazy initialization once and expose its stable readiness."""

        backend = self._load()
        self.available = backend.available
        self.unavailable_reason = backend.unavailable_reason
        return self.available

    def observe(self, packet: ImagePacket) -> FaceObservation:
        return self._load().observe(packet)

    def similarity(
        self, enrolled: tuple[float, ...], observed: tuple[float, ...]
    ) -> float:
        return self._load().similarity(enrolled, observed)


def opencv_available() -> bool:
    """Probe package metadata without importing OpenCV."""

    return importlib.util.find_spec("cv2") is not None


def _bounded_model_path(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    text = str(value)
    if not text or len(text) > MAX_MODEL_PATH_CHARS or "\x00" in text:
        raise ValueError("face model path is invalid")
    return Path(text)


def select_backend(
    *,
    detector_model: Path | str | None = None,
    recognizer_model: Path | str | None = None,
    opencv_factory: OpenCVFactory | None = None,
) -> FaceBackend:
    """Choose lazy CPU OpenCV inference or a deterministic unavailable backend."""

    detector = _bounded_model_path(detector_model)
    recognizer = _bounded_model_path(recognizer_model)
    if detector is None or recognizer is None:
        return UnavailableFaceBackend("models_not_configured")
    if not opencv_available():
        return UnavailableFaceBackend("opencv_unavailable")
    return LazyOpenCVBackend(detector, recognizer, factory=opencv_factory)


class EncryptedFaceTemplateStore:
    """Persist SFace templates only through caller-provided crypto callbacks."""

    def __init__(self, path: Path, *, encrypt: SealCallback, decrypt: OpenCallback) -> None:
        if not callable(encrypt) or not callable(decrypt):
            raise TypeError("encrypt and decrypt callbacks are required")
        self.path = Path(path)
        self._encrypt = encrypt
        self._decrypt = decrypt

    @staticmethod
    def _validate_profiles(value: object) -> dict[str, dict[str, object]]:
        if not isinstance(value, dict) or len(value) > MAX_PROFILES:
            raise FaceWorkerError("store_error", "face template store is invalid")
        profiles: dict[str, dict[str, object]] = {}
        for profile_id, record in value.items():
            if not isinstance(profile_id, str) or _PROFILE_RE.fullmatch(profile_id) is None:
                raise FaceWorkerError("store_error", "stored profile is invalid")
            if not isinstance(record, dict):
                raise FaceWorkerError("store_error", "stored template is invalid")
            template = record.get("template")
            if not isinstance(template, list):
                raise FaceWorkerError("store_error", "stored template is invalid")
            clean = _normalize_template(template)
            profiles[profile_id] = {
                "template": list(clean),
                "backend": str(record.get("backend") or "")[:80],
            }
        return profiles

    def load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        try:
            envelope = json.loads(self.path.read_text(encoding="ascii"))
            if envelope.get("schema") != STORE_SCHEMA:
                raise ValueError("wrong schema")
            sealed = base64.b64decode(envelope["sealed_b64"], validate=True)
            plaintext = self._decrypt(sealed)
            if not isinstance(plaintext, bytes):
                raise TypeError("decrypt callback must return bytes")
            document = json.loads(plaintext.decode("utf-8"))
            if document.get("schema") != STORE_SCHEMA:
                raise ValueError("wrong plaintext schema")
            return self._validate_profiles(document.get("profiles"))
        except FaceWorkerError:
            raise
        except Exception as exc:
            raise FaceWorkerError(
                "store_error", "face template store could not be opened"
            ) from exc

    def save(self, profiles: Mapping[str, Mapping[str, object]]) -> None:
        clean = self._validate_profiles(dict(profiles))
        plaintext = json.dumps(
            {"schema": STORE_SCHEMA, "profiles": clean},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            sealed = self._encrypt(plaintext)
        except Exception as exc:
            raise FaceWorkerError(
                "store_error", "face template store could not be sealed"
            ) from exc
        if not isinstance(sealed, bytes) or not sealed or sealed == plaintext:
            raise FaceWorkerError(
                "store_error", "encrypt callback did not return sealed bytes"
            )
        envelope = json.dumps(
            {
                "schema": STORE_SCHEMA,
                "sealed_b64": base64.b64encode(sealed).decode("ascii"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(envelope, encoding="ascii")
            os.replace(temporary, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except OSError as exc:
            raise FaceWorkerError(
                "store_error", "face template store could not be written"
            ) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _profile_id(value: object) -> str:
    profile = str(value or "")
    if _PROFILE_RE.fullmatch(profile) is None:
        raise FaceWorkerError("invalid_profile", "profile_id is invalid")
    return profile


def _familiarity_band(score: float) -> str:
    if score >= 0.50:
        return "familiar"
    if score >= 0.30:
        return "ambiguous"
    return "unfamiliar"


def _familiarity_safety() -> dict[str, object]:
    return {
        "purpose": PURPOSE,
        "may_authenticate": False,
        "may_authorize_creator": False,
        "may_grant_authority": False,
        "image_retained": False,
    }


class FaceWorker:
    """Synchronous CPU worker for enrollment and face familiarity comparison."""

    def __init__(
        self,
        store_path: Path,
        *,
        encrypt: SealCallback,
        decrypt: OpenCallback,
        backend: FaceBackend | None = None,
        detector_model: Path | str | None = None,
        recognizer_model: Path | str | None = None,
        opencv_factory: OpenCVFactory | None = None,
    ) -> None:
        self.backend = backend or select_backend(
            detector_model=detector_model,
            recognizer_model=recognizer_model,
            opencv_factory=opencv_factory,
        )
        if getattr(self.backend, "device", "") != "cpu":
            raise ValueError("face worker backend must be CPU-only")
        self.store = EncryptedFaceTemplateStore(
            Path(store_path), encrypt=encrypt, decrypt=decrypt
        )
        self._lock = threading.RLock()
        self._runtime_failure = ""
        self._successful_inferences = 0
        self._last_inference_at = 0.0

    def _mark_runtime_failure(self, reason: str = "face_backend_inference_failed") -> None:
        with self._lock:
            self._runtime_failure = str(reason or "face_backend_inference_failed")[:64]

    def _mark_runtime_success(self) -> None:
        with self._lock:
            self._successful_inferences += 1
            self._last_inference_at = time.time()

    def _backend_ready(self) -> bool:
        if self._runtime_failure:
            return False
        ensure_available = getattr(self.backend, "ensure_available", None)
        try:
            if callable(ensure_available):
                return bool(ensure_available())
            return bool(self.backend.available)
        except Exception:
            self._mark_runtime_failure("face_backend_probe_failed")
            return False

    def _unavailable(self, operation: str) -> dict[str, object]:
        return {
            "status": "unavailable",
            "operation": operation,
            "backend": self.backend.name,
            "reason": (
                self._runtime_failure
                or self.backend.unavailable_reason
                or "backend_unavailable"
            ),
            **_familiarity_safety(),
        }

    def _status(self) -> dict[str, object]:
        ready = self._backend_ready()
        result = {
            "status": "ready" if ready else "unavailable",
            "device": "cpu",
            "backend": self.backend.name,
            "reason": self._runtime_failure or self.backend.unavailable_reason,
            "opencv_available": opencv_available(),
            "max_image_bytes": MAX_IMAGE_BYTES,
            "max_image_pixels": MAX_IMAGE_PIXELS,
            "inference_verified": self._successful_inferences > 0,
            "successful_inferences": self._successful_inferences,
            "last_inference_at": self._last_inference_at,
            **_familiarity_safety(),
        }
        return result

    def _enroll(self, request: Mapping[str, object]) -> dict[str, object]:
        if not self._backend_ready():
            return self._unavailable("enroll")
        profile = _profile_id(request.get("profile_id"))
        packet = parse_image(request.get("image"))
        try:
            observation = self.backend.observe(packet)
        except Exception:
            self._mark_runtime_failure()
            raise
        self._mark_runtime_success()
        with self._lock:
            profiles = self.store.load()
            if profile not in profiles and len(profiles) >= MAX_PROFILES:
                raise FaceWorkerError("profile_limit", "face profile limit reached")
            profiles[profile] = {
                "template": list(observation.template),
                "backend": self.backend.name,
            }
            self.store.save(profiles)
        return {
            "status": "ready",
            "profile_id": profile,
            "enrolled": True,
            "backend": self.backend.name,
            "detection_confidence": observation.detection_confidence,
            **_familiarity_safety(),
        }

    def _compare(self, request: Mapping[str, object]) -> dict[str, object]:
        if not self._backend_ready():
            return self._unavailable("compare")
        profile = _profile_id(request.get("profile_id"))
        packet = parse_image(request.get("image"))
        with self._lock:
            record = self.store.load().get(profile)
        if record is None:
            raise FaceWorkerError("profile_not_found", "face profile is not enrolled")
        if record.get("backend") != self.backend.name:
            raise FaceWorkerError(
                "template_mismatch", "stored face template uses a different backend"
            )
        try:
            observation = self.backend.observe(packet)
        except Exception:
            self._mark_runtime_failure()
            raise
        enrolled = tuple(float(value) for value in record["template"])  # type: ignore[arg-type]
        try:
            score = self.backend.similarity(enrolled, observation.template)
        except Exception:
            self._mark_runtime_failure()
            raise
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            self._mark_runtime_failure()
            raise FaceWorkerError(
                "backend_error", "SFace similarity must be between 0 and 1"
            )
        self._mark_runtime_success()
        return {
            "status": "ready",
            "profile_id": profile,
            "score": round(score, 6),
            "familiarity": _familiarity_band(score),
            "backend": self.backend.name,
            "detection_confidence": observation.detection_confidence,
            **_familiarity_safety(),
        }

    def handle(self, request: object) -> dict[str, object]:
        if not isinstance(request, Mapping):
            raise FaceWorkerError("invalid_request", "request must be an object")
        if request.get("schema") != REQUEST_SCHEMA:
            raise FaceWorkerError("invalid_schema", "request schema is unsupported")
        operation = str(request.get("op") or "")
        if operation == "status":
            return self._status()
        if operation == "enroll":
            return self._enroll(request)
        if operation == "compare":
            return self._compare(request)
        raise FaceWorkerError(
            "invalid_operation", "operation must be status, enroll, or compare"
        )


def _request_id(request: object) -> str:
    if not isinstance(request, Mapping):
        return ""
    value = request.get("id")
    return str(value)[:128] if isinstance(value, (str, int)) else ""


def protocol_response(worker: FaceWorker, request: object) -> dict[str, object]:
    request_id = _request_id(request)
    operation = str(request.get("op") or "") if isinstance(request, Mapping) else ""
    try:
        result = worker.handle(request)
        return {
            "schema": RESPONSE_SCHEMA,
            "id": request_id,
            "op": operation,
            "ok": True,
            "result": result,
        }
    except FaceWorkerError as exc:
        return {
            "schema": RESPONSE_SCHEMA,
            "id": request_id,
            "op": operation,
            "ok": False,
            "error": {"code": exc.code, "message": str(exc)},
        }
    except Exception:
        return {
            "schema": RESPONSE_SCHEMA,
            "id": request_id,
            "op": operation,
            "ok": False,
            "error": {"code": "internal_error", "message": "face worker failed"},
        }


def serve_json_lines(worker: FaceWorker, reader: TextIO, writer: TextIO) -> None:
    """Serve bounded JSON-lines requests synchronously until EOF."""

    for raw_line in reader:
        if not raw_line.strip():
            continue
        if len(raw_line.encode("utf-8", "replace")) > MAX_JSON_LINE_BYTES:
            response = {
                "schema": RESPONSE_SCHEMA,
                "id": "",
                "op": "",
                "ok": False,
                "error": {
                    "code": "request_too_large",
                    "message": "request line is too large",
                },
            }
        else:
            try:
                request = json.loads(raw_line)
            except json.JSONDecodeError:
                response = {
                    "schema": RESPONSE_SCHEMA,
                    "id": "",
                    "op": "",
                    "ok": False,
                    "error": {
                        "code": "invalid_json",
                        "message": "request is not valid JSON",
                    },
                }
            else:
                response = protocol_response(worker, request)
        writer.write(json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n")
        writer.flush()


__all__ = [
    "EncryptedFaceTemplateStore",
    "FaceBackend",
    "FaceObservation",
    "FaceWorker",
    "FaceWorkerError",
    "ImagePacket",
    "LazyOpenCVBackend",
    "MAX_IMAGE_BYTES",
    "MAX_IMAGE_HEIGHT",
    "MAX_IMAGE_PIXELS",
    "MAX_IMAGE_WIDTH",
    "MAX_JSON_LINE_BYTES",
    "OpenCVYuNetSFaceBackend",
    "PURPOSE",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "UnavailableFaceBackend",
    "opencv_available",
    "parse_image",
    "protocol_response",
    "select_backend",
    "serve_json_lines",
]
