"""Isolated, familiarity-only speaker embedding worker foundation.

The worker accepts one bounded JSON-lines request at a time. It deliberately
does not authenticate a person, grant authority, retain audio, or implement
cryptography. Callers must supply the encrypt/decrypt callbacks used for the
embedding store. sherpa-onnx loading is optional, lazy, and factory-driven so
the main process never needs to import it.
"""
from __future__ import annotations

import array
import base64
import binascii
import importlib
import importlib.util
import io
import json
import math
import os
import re
import sys
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol, TextIO


REQUEST_SCHEMA = "alpecca.speaker-worker.request.v1"
RESPONSE_SCHEMA = "alpecca.speaker-worker.response.v1"
STORE_SCHEMA = "alpecca.speaker-worker.store.v1"
PURPOSE = "familiarity-only"

MAX_AUDIO_SECONDS = 12.0
MAX_AUDIO_BYTES = 48_000 * 2 * 2 * int(MAX_AUDIO_SECONDS)
MAX_AUDIO_CONTAINER_BYTES = MAX_AUDIO_BYTES + 65_536
MAX_JSON_LINE_BYTES = 4_000_000
MAX_PROFILES = 32
MAX_EMBEDDING_DIMENSIONS = 1_024
READINESS_PROBE_AUDIO_SECONDS = 0.5
READINESS_PROBE_TIMEOUT_SECONDS = 5.0
ALLOWED_SAMPLE_RATES = frozenset({8_000, 16_000, 24_000, 32_000, 44_100, 48_000})
_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

SealCallback = Callable[[bytes], bytes]
OpenCallback = Callable[[bytes], bytes]
SherpaFactory = Callable[[object], "EmbeddingBackend | Callable[[bytes, int], object]"]


class SpeakerWorkerError(ValueError):
    """A bounded protocol failure safe to return to the caller."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AudioPacket:
    pcm_s16le: bytes
    sample_rate_hz: int
    channels: int
    frame_count: int
    source_encoding: str

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.sample_rate_hz


class EmbeddingBackend(Protocol):
    name: str
    device: str
    recognition_capable: bool

    def embed(self, packet: AudioPacket) -> tuple[float, ...]: ...


def _bounded_int(value: object, *, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise SpeakerWorkerError(
            "invalid_audio_metadata", f"{name} must be an integer from {minimum} to {maximum}"
        )
    return value


def _decode_base64(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise SpeakerWorkerError("invalid_audio", "audio data_b64 must be a non-empty string")
    if len(value) > ((MAX_AUDIO_CONTAINER_BYTES + 2) // 3) * 4 + 8:
        raise SpeakerWorkerError("audio_too_large", "encoded audio exceeds the worker limit")
    try:
        payload = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SpeakerWorkerError("invalid_audio", "audio data_b64 is malformed") from exc
    if not payload or len(payload) > MAX_AUDIO_CONTAINER_BYTES:
        raise SpeakerWorkerError("audio_too_large", "audio exceeds the worker limit")
    return payload


def parse_audio(value: object) -> AudioPacket:
    """Validate bounded PCM/WAV bytes and require exact accompanying metadata."""

    if not isinstance(value, Mapping):
        raise SpeakerWorkerError("invalid_audio", "audio must be an object")
    encoding = str(value.get("encoding") or "").strip().lower()
    if encoding not in {"pcm_s16le", "wav"}:
        raise SpeakerWorkerError("invalid_audio", "audio encoding must be pcm_s16le or wav")
    rate = _bounded_int(
        value.get("sample_rate_hz"), name="sample_rate_hz", minimum=8_000, maximum=48_000
    )
    if rate not in ALLOWED_SAMPLE_RATES:
        raise SpeakerWorkerError("invalid_audio_metadata", "sample_rate_hz is unsupported")
    channels = _bounded_int(value.get("channels"), name="channels", minimum=1, maximum=2)
    width = _bounded_int(
        value.get("sample_width_bytes"), name="sample_width_bytes", minimum=2, maximum=2
    )
    frames = _bounded_int(
        value.get("frame_count"),
        name="frame_count",
        minimum=1,
        maximum=int(rate * MAX_AUDIO_SECONDS),
    )
    payload = _decode_base64(value.get("data_b64"))

    if encoding == "pcm_s16le":
        expected = frames * channels * width
        if len(payload) != expected:
            raise SpeakerWorkerError(
                "audio_metadata_mismatch", "PCM byte length does not match frame metadata"
            )
        pcm = payload
    else:
        try:
            with wave.open(io.BytesIO(payload), "rb") as wav:
                actual = (
                    wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()
                )
                if wav.getcomptype() != "NONE":
                    raise SpeakerWorkerError("invalid_audio", "compressed WAV is unsupported")
                pcm = wav.readframes(wav.getnframes())
        except SpeakerWorkerError:
            raise
        except (EOFError, wave.Error) as exc:
            raise SpeakerWorkerError("invalid_audio", "WAV container is malformed") from exc
        if actual != (rate, channels, width, frames):
            raise SpeakerWorkerError(
                "audio_metadata_mismatch", "WAV header does not match request metadata"
            )
        if len(pcm) != frames * channels * width:
            raise SpeakerWorkerError("invalid_audio", "WAV payload is incomplete")

    return AudioPacket(pcm, rate, channels, frames, encoding)


def _mono_samples(packet: AudioPacket) -> list[float]:
    samples = array.array("h")
    samples.frombytes(packet.pcm_s16le)
    if sys.byteorder != "little":
        samples.byteswap()
    if packet.channels == 1:
        return [sample / 32768.0 for sample in samples]
    return [
        (samples[index] + samples[index + 1]) / 65536.0
        for index in range(0, len(samples), 2)
    ]


def _normalize(vector: list[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise SpeakerWorkerError("audio_has_no_signal", "audio contains no usable signal")
    return tuple(round(value / norm, 8) for value in vector)


class DeterministicFallbackBackend:
    """Non-evidentiary signal fingerprint for protocol/offline operation."""

    name = "deterministic-cpu-fallback"
    device = "cpu"
    recognition_capable = False
    _SEGMENTS = 16

    def embed(self, packet: AudioPacket) -> tuple[float, ...]:
        samples = _mono_samples(packet)
        if not samples:
            raise SpeakerWorkerError("audio_has_no_signal", "audio contains no samples")
        features: list[float] = []
        for segment in range(self._SEGMENTS):
            start = len(samples) * segment // self._SEGMENTS
            end = len(samples) * (segment + 1) // self._SEGMENTS
            window = samples[start:end] or [0.0]
            rms = math.sqrt(sum(sample * sample for sample in window) / len(window))
            mean_abs = sum(abs(sample) for sample in window) / len(window)
            crossings = sum(
                1 for left, right in zip(window, window[1:]) if (left < 0.0) != (right < 0.0)
            ) / max(1, len(window) - 1)
            features.extend((rms, mean_abs, crossings))
        return _normalize(features)


class SherpaOnnxBackend:
    """Adapter around a caller-configured sherpa-onnx CPU extractor."""

    name = "sherpa-onnx-cpu"
    device = "cpu"
    recognition_capable = True

    def __init__(self, extractor: Callable[[bytes, int], object]) -> None:
        if not callable(extractor):
            raise TypeError("sherpa extractor must be callable")
        self._extractor = extractor

    def embed(self, packet: AudioPacket) -> tuple[float, ...]:
        mono = _mono_samples(packet)
        pcm = array.array("f", mono).tobytes()
        raw = self._extractor(pcm, packet.sample_rate_hz)
        try:
            vector = [float(value) for value in raw]  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise SpeakerWorkerError("backend_error", "speaker backend returned no embedding") from exc
        if not 1 <= len(vector) <= MAX_EMBEDDING_DIMENSIONS:
            raise SpeakerWorkerError("backend_error", "speaker embedding dimension is invalid")
        if not all(math.isfinite(value) for value in vector):
            raise SpeakerWorkerError("backend_error", "speaker embedding contains invalid values")
        return _normalize(vector)

    def readiness_probe(self, *, timeout_seconds: float) -> tuple[bool, str]:
        """Run one bounded inference over ephemeral synthetic audio."""

        rate = 16_000
        frame_count = int(rate * READINESS_PROBE_AUDIO_SECONDS)
        samples = array.array(
            "h",
            (
                int(
                    6_000 * math.sin(2.0 * math.pi * 220.0 * index / rate)
                    + 2_000 * math.sin(2.0 * math.pi * 440.0 * index / rate)
                )
                for index in range(frame_count)
            ),
        )
        if sys.byteorder != "little":
            samples.byteswap()
        packet = AudioPacket(samples.tobytes(), rate, 1, frame_count, "synthetic-probe")
        finished = threading.Event()
        outcome: dict[str, object] = {}

        def run_probe() -> None:
            try:
                outcome["embedding_dimensions"] = len(self.embed(packet))
            except Exception:
                outcome["failed"] = True
            finally:
                finished.set()

        thread = threading.Thread(
            target=run_probe,
            name="alpecca-speaker-readiness-probe",
            daemon=True,
        )
        thread.start()
        if not finished.wait(max(0.01, float(timeout_seconds))):
            return False, "speaker_recognition_probe_timeout"
        if outcome.get("failed") or not outcome.get("embedding_dimensions"):
            return False, "speaker_recognition_probe_failed"
        return True, ""


def sherpa_onnx_available() -> bool:
    return importlib.util.find_spec("sherpa_onnx") is not None


def select_backend(
    *, prefer_sherpa: bool = False, sherpa_factory: SherpaFactory | None = None
) -> EmbeddingBackend:
    """Load sherpa lazily only when explicitly preferred and configured."""

    if prefer_sherpa and sherpa_factory is not None and sherpa_onnx_available():
        try:
            module = importlib.import_module("sherpa_onnx")
            candidate = sherpa_factory(module)
            if callable(candidate) and not hasattr(candidate, "embed"):
                return SherpaOnnxBackend(candidate)
            if getattr(candidate, "device", "cpu") != "cpu":
                raise ValueError("speaker backend must be CPU-only")
            if callable(getattr(candidate, "embed", None)):
                return candidate  # type: ignore[return-value]
        except Exception:
            pass
    return DeterministicFallbackBackend()


class EncryptedEmbeddingStore:
    """Persist embeddings only through caller-supplied sealing callbacks."""

    def __init__(self, path: Path, *, encrypt: SealCallback, decrypt: OpenCallback) -> None:
        if not callable(encrypt) or not callable(decrypt):
            raise TypeError("encrypt and decrypt callbacks are required")
        self.path = Path(path)
        self._encrypt = encrypt
        self._decrypt = decrypt

    @staticmethod
    def _validate_profiles(value: object) -> dict[str, dict[str, object]]:
        if not isinstance(value, dict) or len(value) > MAX_PROFILES:
            raise SpeakerWorkerError("store_error", "embedding store is invalid")
        profiles: dict[str, dict[str, object]] = {}
        for profile_id, record in value.items():
            if not isinstance(profile_id, str) or _PROFILE_RE.fullmatch(profile_id) is None:
                raise SpeakerWorkerError("store_error", "embedding store profile is invalid")
            if not isinstance(record, dict):
                raise SpeakerWorkerError("store_error", "embedding store record is invalid")
            vector = record.get("embedding")
            if not isinstance(vector, list) or not 1 <= len(vector) <= MAX_EMBEDDING_DIMENSIONS:
                raise SpeakerWorkerError("store_error", "stored embedding is invalid")
            clean = [float(item) for item in vector]
            if not all(math.isfinite(item) for item in clean):
                raise SpeakerWorkerError("store_error", "stored embedding is invalid")
            profiles[profile_id] = {
                "embedding": clean,
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
        except SpeakerWorkerError:
            raise
        except Exception as exc:
            raise SpeakerWorkerError("store_error", "embedding store could not be opened") from exc

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
            raise SpeakerWorkerError("store_error", "embedding store could not be sealed") from exc
        if not isinstance(sealed, bytes) or not sealed or sealed == plaintext:
            raise SpeakerWorkerError("store_error", "encrypt callback did not return sealed bytes")
        envelope = json.dumps(
            {"schema": STORE_SCHEMA, "sealed_b64": base64.b64encode(sealed).decode("ascii")},
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
            raise SpeakerWorkerError("store_error", "embedding store could not be written") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _profile_id(value: object) -> str:
    profile = str(value or "")
    if _PROFILE_RE.fullmatch(profile) is None:
        raise SpeakerWorkerError("invalid_profile", "profile_id is invalid")
    return profile


def _familiarity_score(left: list[float] | tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise SpeakerWorkerError("embedding_mismatch", "stored and observed embeddings differ")
    score = sum(float(a) * float(b) for a, b in zip(left, right))
    return round(max(0.0, min(1.0, score)), 6)


def _familiarity_band(score: float) -> str:
    if score >= 0.82:
        return "familiar"
    if score >= 0.62:
        return "ambiguous"
    return "unfamiliar"


class SpeakerWorker:
    def __init__(
        self,
        store_path: Path,
        *,
        encrypt: SealCallback,
        decrypt: OpenCallback,
        backend: EmbeddingBackend | None = None,
        prefer_sherpa: bool = False,
        sherpa_factory: SherpaFactory | None = None,
    ) -> None:
        self.backend = backend or select_backend(
            prefer_sherpa=prefer_sherpa, sherpa_factory=sherpa_factory
        )
        if getattr(self.backend, "device", "") != "cpu":
            raise ValueError("speaker worker backend must be CPU-only")
        self.store = EncryptedEmbeddingStore(
            Path(store_path), encrypt=encrypt, decrypt=decrypt
        )
        self._lock = threading.RLock()
        self._probe_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._probe_checked = False
        self._probe_ready = False
        self._probe_reason = "speaker_recognition_probe_pending"

    def _recognition_state(self) -> tuple[bool, str]:
        if not bool(getattr(self.backend, "recognition_capable", False)):
            return False, "speaker_recognition_backend_not_configured"
        with self._probe_lock:
            if not self._probe_checked:
                probe = getattr(self.backend, "readiness_probe", None)
                if not callable(probe):
                    self._probe_ready = False
                    self._probe_reason = "speaker_recognition_probe_unavailable"
                else:
                    try:
                        ready, reason = probe(timeout_seconds=READINESS_PROBE_TIMEOUT_SECONDS)
                    except Exception:
                        ready, reason = False, "speaker_recognition_probe_failed"
                    self._probe_ready = ready is True
                    self._probe_reason = (
                        ""
                        if self._probe_ready
                        else str(reason or "speaker_recognition_probe_failed")
                    )
                self._probe_checked = True
            return self._probe_ready, self._probe_reason

    def _invalidate_recognition(self, reason: str) -> None:
        with self._probe_lock:
            self._probe_checked = True
            self._probe_ready = False
            self._probe_reason = reason

    def _embed_if_ready(self, packet: AudioPacket) -> tuple[float, ...] | None:
        with self._inference_lock:
            ready, _reason = self._recognition_state()
            if not ready:
                return None
            try:
                return self.backend.embed(packet)
            except Exception:
                self._invalidate_recognition("speaker_recognition_backend_failed")
                return None

    def _safety(self, ready: bool) -> dict[str, object]:
        return {
            "purpose": PURPOSE,
            "recognition_ready": ready,
            "evidence_kind": "speaker-embedding-similarity" if ready else "none",
            "may_authenticate": False,
            "may_grant_authority": False,
            "audio_retained": False,
        }

    def _unavailable(self, operation: str) -> dict[str, object]:
        ready, reason = self._recognition_state()
        return {
            "status": "unavailable",
            "operation": operation,
            "backend": self.backend.name,
            "reason": reason,
            **self._safety(ready),
        }

    def _status(self) -> dict[str, object]:
        with self._lock:
            profiles = self.store.load()
        ready, reason = self._recognition_state()
        return {
            "status": "ready" if ready else "unavailable",
            "reason": reason,
            "device": "cpu",
            "backend": self.backend.name,
            "sherpa_onnx_available": sherpa_onnx_available(),
            "enrolled_profiles": len(profiles),
            "max_audio_seconds": MAX_AUDIO_SECONDS,
            **self._safety(ready),
        }

    def _enroll(self, request: Mapping[str, object]) -> dict[str, object]:
        profile = _profile_id(request.get("profile_id"))
        ready, _reason = self._recognition_state()
        if not ready:
            return self._unavailable("enroll")
        packet = parse_audio(request.get("audio"))
        embedding = self._embed_if_ready(packet)
        if embedding is None:
            return self._unavailable("enroll")
        with self._lock:
            profiles = self.store.load()
            if profile not in profiles and len(profiles) >= MAX_PROFILES:
                raise SpeakerWorkerError("profile_limit", "speaker profile limit reached")
            profiles[profile] = {"embedding": list(embedding), "backend": self.backend.name}
            self.store.save(profiles)
        return {
            "status": "ready",
            "profile_id": profile,
            "enrolled": True,
            "backend": self.backend.name,
            **self._safety(ready),
        }

    def _compare(self, request: Mapping[str, object]) -> dict[str, object]:
        profile = _profile_id(request.get("profile_id"))
        ready, _reason = self._recognition_state()
        if not ready:
            return self._unavailable("compare")
        packet = parse_audio(request.get("audio"))
        with self._lock:
            record = self.store.load().get(profile)
        if record is None:
            raise SpeakerWorkerError("profile_not_found", "speaker profile is not enrolled")
        if record.get("backend") != self.backend.name:
            raise SpeakerWorkerError(
                "embedding_mismatch", "stored speaker embedding uses a different backend"
            )
        observed = self._embed_if_ready(packet)
        if observed is None:
            return self._unavailable("compare")
        score = _familiarity_score(record["embedding"], observed)  # type: ignore[arg-type]
        return {
            "status": "ready",
            "profile_id": profile,
            "score": score,
            "familiarity": _familiarity_band(score),
            "backend": self.backend.name,
            **self._safety(ready),
        }

    def handle(self, request: object) -> dict[str, object]:
        if not isinstance(request, Mapping):
            raise SpeakerWorkerError("invalid_request", "request must be an object")
        if request.get("schema") != REQUEST_SCHEMA:
            raise SpeakerWorkerError("invalid_schema", "request schema is unsupported")
        operation = str(request.get("op") or "")
        if operation == "status":
            return self._status()
        if operation == "enroll":
            return self._enroll(request)
        if operation == "compare":
            return self._compare(request)
        raise SpeakerWorkerError("invalid_operation", "operation must be status, enroll, or compare")


def _request_id(request: object) -> str:
    if not isinstance(request, Mapping):
        return ""
    value = request.get("id")
    return str(value)[:128] if isinstance(value, (str, int)) else ""


def protocol_response(worker: SpeakerWorker, request: object) -> dict[str, object]:
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
    except SpeakerWorkerError as exc:
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
            "error": {"code": "internal_error", "message": "speaker worker failed"},
        }


def serve_json_lines(worker: SpeakerWorker, reader: TextIO, writer: TextIO) -> None:
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
                "error": {"code": "request_too_large", "message": "request line is too large"},
            }
        else:
            try:
                request = json.loads(raw_line)
            except json.JSONDecodeError:
                request = None
                response = {
                    "schema": RESPONSE_SCHEMA,
                    "id": "",
                    "op": "",
                    "ok": False,
                    "error": {"code": "invalid_json", "message": "request is not valid JSON"},
                }
            else:
                response = protocol_response(worker, request)
        writer.write(json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n")
        writer.flush()


__all__ = [
    "ALLOWED_SAMPLE_RATES",
    "AudioPacket",
    "DeterministicFallbackBackend",
    "EncryptedEmbeddingStore",
    "MAX_AUDIO_BYTES",
    "MAX_AUDIO_CONTAINER_BYTES",
    "MAX_AUDIO_SECONDS",
    "MAX_JSON_LINE_BYTES",
    "PURPOSE",
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "SherpaOnnxBackend",
    "SpeakerWorker",
    "SpeakerWorkerError",
    "parse_audio",
    "protocol_response",
    "select_backend",
    "serve_json_lines",
    "sherpa_onnx_available",
]
