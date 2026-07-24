"""Optional PyTorch HyFusER-style shadow model for the seven Soul perspectives.

The normal Alpecca runtime can import this module without PyTorch installed.
PyTorch is loaded only when a model is built or a checkpoint is opened.  The
model is an advisory evaluator: its output cannot select a Soul focus, approve
an action, mutate affect, or write self-improvement parameters.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from alpecca.soul import PERSPECTIVE_ORDER


CHECKPOINT_SCHEMA = "alpecca.rog-soul-transformer-checkpoint.v1"
EVALUATION_SCHEMA = "alpecca.rog-soul-transformer-evaluation.v1"
ARCHITECTURE = "hyfuser-shared-backbone-seven-heads"
MODEL_VERSION = 1
RUNTIME_ID_PREFIX = "rog-soul-transformer-v1"
EXPECTED_HEAD_ORDER = (
    "Feeler",
    "Expressor",
    "Carer",
    "Doer",
    "Wanderer",
    "Reflector",
    "Improver",
)
if PERSPECTIVE_ORDER != EXPECTED_HEAD_ORDER:
    raise RuntimeError("Soul perspective order changed; transformer contract needs review")

MIN_MACRO_F1 = 0.72
MIN_PER_HEAD_F1 = 0.60
MAX_EXPECTED_CALIBRATION_ERROR = 0.12
MIN_EVALUATION_SAMPLES = 500
MIN_TEXT_COVERAGE = 0.90
MIN_SPEECH_COVERAGE = 0.75
MAX_CHECKPOINT_BYTES = 512 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class SoulTransformerContractError(ValueError):
    """Checkpoint, evaluation, or inference data violated the fixed contract."""


class TorchUnavailableError(RuntimeError):
    """The optional model was requested without a usable PyTorch install."""


def _torch_modules() -> tuple[Any, Any]:
    try:
        import torch
        from torch import nn
    except (ImportError, OSError) as exc:
        raise TorchUnavailableError("PyTorch is not available for the optional ROG model") from exc
    return torch, nn


def torch_available() -> bool:
    try:
        _torch_modules()
    except TorchUnavailableError:
        return False
    return True


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SoulTransformerContractError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise SoulTransformerContractError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return value


def _number(value: object, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SoulTransformerContractError(f"{field} must be numeric")
    checked = float(value)
    if not math.isfinite(checked) or not minimum <= checked <= maximum:
        raise SoulTransformerContractError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return checked


def _exact_head_order(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise SoulTransformerContractError("head_order must be a list")
    order = tuple(value)
    if order != EXPECTED_HEAD_ORDER:
        raise SoulTransformerContractError("head_order must match the exact Soul order")
    return order


@dataclass(frozen=True, slots=True)
class ModelDimensions:
    text_emotion_dim: int = 8
    speech_emotion_dim: int = 8
    model_dim: int = 32
    attention_heads: int = 4
    backbone_layers: int = 1
    perspective_layers: int = 1
    feedforward_dim: int = 64
    dropout: float = 0.0

    def __post_init__(self) -> None:
        _integer(self.text_emotion_dim, "text_emotion_dim", 1, 64)
        _integer(self.speech_emotion_dim, "speech_emotion_dim", 1, 64)
        _integer(self.model_dim, "model_dim", 8, 256)
        _integer(self.attention_heads, "attention_heads", 1, 16)
        _integer(self.backbone_layers, "backbone_layers", 1, 4)
        _integer(self.perspective_layers, "perspective_layers", 1, 3)
        _integer(self.feedforward_dim, "feedforward_dim", 16, 1024)
        _number(self.dropout, "dropout", 0.0, 0.5)
        if self.model_dim % self.attention_heads:
            raise SoulTransformerContractError(
                "model_dim must be divisible by attention_heads"
            )

    @classmethod
    def from_mapping(cls, value: object) -> "ModelDimensions":
        if not isinstance(value, Mapping):
            raise SoulTransformerContractError("dimensions must be an object")
        expected = {
            "text_emotion_dim",
            "speech_emotion_dim",
            "model_dim",
            "attention_heads",
            "backbone_layers",
            "perspective_layers",
            "feedforward_dim",
            "dropout",
        }
        if set(value) != expected:
            raise SoulTransformerContractError("dimensions fields are invalid")
        return cls(**{name: value[name] for name in expected})

    def as_dict(self) -> dict[str, int | float]:
        return {
            "text_emotion_dim": self.text_emotion_dim,
            "speech_emotion_dim": self.speech_emotion_dim,
            "model_dim": self.model_dim,
            "attention_heads": self.attention_heads,
            "backbone_layers": self.backbone_layers,
            "perspective_layers": self.perspective_layers,
            "feedforward_dim": self.feedforward_dim,
            "dropout": self.dropout,
        }


@dataclass(frozen=True, slots=True)
class CalibrationMetadata:
    method: str
    score_temperatures: tuple[float, ...]
    confidence_temperatures: tuple[float, ...]
    calibration_set_sha256: str

    def __post_init__(self) -> None:
        if self.method != "per-head-temperature-v1":
            raise SoulTransformerContractError("unsupported calibration method")
        if len(self.score_temperatures) != 7 or len(self.confidence_temperatures) != 7:
            raise SoulTransformerContractError("calibration requires exactly seven temperatures")
        for index, value in enumerate(self.score_temperatures):
            _number(value, f"score_temperatures[{index}]", 0.05, 10.0)
        for index, value in enumerate(self.confidence_temperatures):
            _number(value, f"confidence_temperatures[{index}]", 0.05, 10.0)
        if not _SHA256_RE.fullmatch(self.calibration_set_sha256):
            raise SoulTransformerContractError("calibration_set_sha256 is invalid")

    @classmethod
    def from_mapping(cls, value: object) -> "CalibrationMetadata":
        if not isinstance(value, Mapping) or set(value) != {
            "method",
            "score_temperatures",
            "confidence_temperatures",
            "calibration_set_sha256",
        }:
            raise SoulTransformerContractError("calibration metadata is invalid")
        scores = value["score_temperatures"]
        confidences = value["confidence_temperatures"]
        if not isinstance(scores, (list, tuple)) or not isinstance(
            confidences, (list, tuple)
        ):
            raise SoulTransformerContractError("calibration temperatures must be lists")
        return cls(
            method=str(value["method"]),
            score_temperatures=tuple(scores),
            confidence_temperatures=tuple(confidences),
            calibration_set_sha256=str(value["calibration_set_sha256"]),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "score_temperatures": list(self.score_temperatures),
            "confidence_temperatures": list(self.confidence_temperatures),
            "calibration_set_sha256": self.calibration_set_sha256,
        }


@dataclass(frozen=True, slots=True)
class CheckpointMetadata:
    dimensions: ModelDimensions
    calibration: CalibrationMetadata
    training_run_id: str

    @property
    def qualified(self) -> bool:
        return False

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CHECKPOINT_SCHEMA,
            "version": MODEL_VERSION,
            "architecture": ARCHITECTURE,
            "head_order": list(EXPECTED_HEAD_ORDER),
            "dimensions": self.dimensions.as_dict(),
            "calibration": self.calibration.as_dict(),
            "training_run_id": self.training_run_id,
            "qualified": False,
            "advisory_only": True,
            "authorizes_action": False,
        }


def parse_checkpoint_metadata(value: object) -> CheckpointMetadata:
    if not isinstance(value, Mapping):
        raise SoulTransformerContractError("checkpoint metadata must be an object")
    expected = {
        "schema",
        "version",
        "architecture",
        "head_order",
        "dimensions",
        "calibration",
        "training_run_id",
        "qualified",
        "advisory_only",
        "authorizes_action",
    }
    if set(value) != expected:
        raise SoulTransformerContractError("checkpoint metadata fields are invalid")
    if value["schema"] != CHECKPOINT_SCHEMA or value["version"] != MODEL_VERSION:
        raise SoulTransformerContractError("checkpoint schema or version is invalid")
    if value["architecture"] != ARCHITECTURE:
        raise SoulTransformerContractError("checkpoint architecture is invalid")
    _exact_head_order(value["head_order"])
    if value["qualified"] is not False:
        raise SoulTransformerContractError("checkpoint cannot self-declare qualification")
    if value["advisory_only"] is not True or value["authorizes_action"] is not False:
        raise SoulTransformerContractError("checkpoint must remain advisory-only")
    training_run_id = value["training_run_id"]
    if not isinstance(training_run_id, str) or not _SAFE_ID_RE.fullmatch(training_run_id):
        raise SoulTransformerContractError("training_run_id is invalid")
    return CheckpointMetadata(
        ModelDimensions.from_mapping(value["dimensions"]),
        CalibrationMetadata.from_mapping(value["calibration"]),
        training_run_id,
    )


@dataclass(frozen=True, slots=True)
class QualificationResult:
    qualified: bool
    reasons: tuple[str, ...]
    evaluation_id: str | None = None


def evaluate_qualification(
    metadata: CheckpointMetadata,
    checkpoint_sha256: str,
    manifest: object | None,
) -> QualificationResult:
    """Qualify only against one separate, strictly bounded evaluation manifest."""

    if not _SHA256_RE.fullmatch(checkpoint_sha256):
        raise SoulTransformerContractError("checkpoint SHA-256 is invalid")
    if manifest is None:
        return QualificationResult(False, ("evaluation_manifest_missing",))
    if not isinstance(manifest, Mapping):
        raise SoulTransformerContractError("evaluation manifest must be an object")
    expected = {
        "schema",
        "version",
        "evaluation_id",
        "checkpoint_sha256",
        "architecture",
        "head_order",
        "dimensions",
        "metrics",
        "evaluation_data_sha256",
    }
    if set(manifest) != expected:
        raise SoulTransformerContractError("evaluation manifest fields are invalid")
    if manifest["schema"] != EVALUATION_SCHEMA or manifest["version"] != MODEL_VERSION:
        raise SoulTransformerContractError("evaluation schema or version is invalid")
    evaluation_id = manifest["evaluation_id"]
    if not isinstance(evaluation_id, str) or not _SAFE_ID_RE.fullmatch(evaluation_id):
        raise SoulTransformerContractError("evaluation_id is invalid")
    if manifest["checkpoint_sha256"] != checkpoint_sha256:
        raise SoulTransformerContractError("evaluation checkpoint SHA-256 does not match")
    if manifest["architecture"] != ARCHITECTURE:
        raise SoulTransformerContractError("evaluation architecture is invalid")
    _exact_head_order(manifest["head_order"])
    if ModelDimensions.from_mapping(manifest["dimensions"]) != metadata.dimensions:
        raise SoulTransformerContractError("evaluation dimensions do not match")
    if not isinstance(manifest["evaluation_data_sha256"], str) or not _SHA256_RE.fullmatch(
        manifest["evaluation_data_sha256"]
    ):
        raise SoulTransformerContractError("evaluation_data_sha256 is invalid")
    metrics = manifest["metrics"]
    if not isinstance(metrics, Mapping) or set(metrics) != {
        "samples",
        "macro_f1",
        "per_head_f1",
        "expected_calibration_error",
        "text_coverage",
        "speech_coverage",
    }:
        raise SoulTransformerContractError("evaluation metrics are invalid")
    samples = _integer(metrics["samples"], "samples", 1, 100_000_000)
    macro_f1 = _number(metrics["macro_f1"], "macro_f1", 0.0, 1.0)
    ece = _number(
        metrics["expected_calibration_error"],
        "expected_calibration_error",
        0.0,
        1.0,
    )
    text_coverage = _number(metrics["text_coverage"], "text_coverage", 0.0, 1.0)
    speech_coverage = _number(metrics["speech_coverage"], "speech_coverage", 0.0, 1.0)
    per_head = metrics["per_head_f1"]
    if not isinstance(per_head, (list, tuple)) or len(per_head) != 7:
        raise SoulTransformerContractError("per_head_f1 must contain exactly seven scores")
    per_head_values = tuple(
        _number(value, f"per_head_f1[{index}]", 0.0, 1.0)
        for index, value in enumerate(per_head)
    )
    reasons: list[str] = []
    if samples < MIN_EVALUATION_SAMPLES:
        reasons.append("insufficient_samples")
    if macro_f1 < MIN_MACRO_F1:
        reasons.append("macro_f1_below_threshold")
    if min(per_head_values) < MIN_PER_HEAD_F1:
        reasons.append("per_head_f1_below_threshold")
    if ece > MAX_EXPECTED_CALIBRATION_ERROR:
        reasons.append("calibration_error_above_threshold")
    if text_coverage < MIN_TEXT_COVERAGE:
        reasons.append("text_coverage_below_threshold")
    if speech_coverage < MIN_SPEECH_COVERAGE:
        reasons.append("speech_coverage_below_threshold")
    return QualificationResult(not reasons, tuple(reasons), evaluation_id)


def sha256_file(path: str | Path) -> str:
    target = Path(path).expanduser().resolve(strict=True)
    if not target.is_file() or target.is_symlink():
        raise SoulTransformerContractError("checkpoint must be a regular non-symlink file")
    if not 0 < target.stat().st_size <= MAX_CHECKPOINT_BYTES:
        raise SoulTransformerContractError("checkpoint size is outside its bound")
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_model(dimensions: ModelDimensions) -> Any:
    """Build one shared dual-attention backbone and seven distinct heads."""

    torch, nn = _torch_modules()

    class PerspectiveHead(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            layer = nn.TransformerEncoderLayer(
                d_model=dimensions.model_dim,
                nhead=dimensions.attention_heads,
                dim_feedforward=dimensions.feedforward_dim,
                dropout=dimensions.dropout,
                batch_first=True,
                norm_first=True,
            )
            self.encoder = nn.TransformerEncoder(
                layer, num_layers=dimensions.perspective_layers
            )
            self.output = nn.Linear(dimensions.model_dim, 2)

        def forward(self, shared: Any) -> Any:
            encoded = self.encoder(shared)
            return self.output(encoded.mean(dim=1))

    class SevenPerspectiveSoulModel(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            # One projection is intentionally shared by text and speech tokens.
            self.modality_projection = nn.Linear(1, dimensions.model_dim)
            self.text_positions = nn.Parameter(
                torch.zeros(1, dimensions.text_emotion_dim, dimensions.model_dim)
            )
            self.speech_positions = nn.Parameter(
                torch.zeros(1, dimensions.speech_emotion_dim, dimensions.model_dim)
            )
            self.text_to_speech = nn.MultiheadAttention(
                dimensions.model_dim,
                dimensions.attention_heads,
                dropout=dimensions.dropout,
                batch_first=True,
            )
            self.speech_to_text = nn.MultiheadAttention(
                dimensions.model_dim,
                dimensions.attention_heads,
                dropout=dimensions.dropout,
                batch_first=True,
            )
            backbone_layer = nn.TransformerEncoderLayer(
                d_model=dimensions.model_dim,
                nhead=dimensions.attention_heads,
                dim_feedforward=dimensions.feedforward_dim,
                dropout=dimensions.dropout,
                batch_first=True,
                norm_first=True,
            )
            self.fusion_backbone = nn.TransformerEncoder(
                backbone_layer, num_layers=dimensions.backbone_layers
            )
            self.perspective_heads = nn.ModuleList(
                PerspectiveHead() for _ in EXPECTED_HEAD_ORDER
            )

        def forward(self, text_emotion: Any, speech_emotion: Any) -> tuple[Any, Any]:
            if text_emotion.ndim != 2 or text_emotion.shape[-1] != dimensions.text_emotion_dim:
                raise SoulTransformerContractError("text input shape is invalid")
            if speech_emotion.ndim != 2 or speech_emotion.shape[-1] != dimensions.speech_emotion_dim:
                raise SoulTransformerContractError("speech input shape is invalid")
            text = self.modality_projection(text_emotion.unsqueeze(-1)) + self.text_positions
            speech = self.modality_projection(speech_emotion.unsqueeze(-1)) + self.speech_positions
            text_cross, _ = self.text_to_speech(text, speech, speech, need_weights=False)
            speech_cross, _ = self.speech_to_text(speech, text, text, need_weights=False)
            shared = self.fusion_backbone(torch.cat((text + text_cross, speech + speech_cross), dim=1))
            outputs = torch.stack([head(shared) for head in self.perspective_heads], dim=1)
            return torch.tanh(outputs[..., 0]), torch.sigmoid(outputs[..., 1])

    return SevenPerspectiveSoulModel()


def checkpoint_payload(
    model: Any,
    metadata: CheckpointMetadata,
) -> dict[str, object]:
    if not hasattr(model, "state_dict"):
        raise SoulTransformerContractError("model does not expose a state_dict")
    return {"metadata": metadata.as_dict(), "state_dict": model.state_dict()}


def _safe_torch_load(torch: Any, path: Path) -> object:
    try:
        return torch.load(path, map_location="cpu", weights_only=True)
    except TypeError as exc:
        raise SoulTransformerContractError(
            "PyTorch must support weights_only checkpoint loading"
        ) from exc


def _load_manifest(path: str | Path | None) -> object | None:
    if path is None or not str(path).strip():
        return None
    target = Path(path).expanduser().resolve(strict=True)
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SoulTransformerContractError("evaluation manifest is unreadable") from exc


class SoulTransformerBackend:
    """Worker-compatible shadow backend; qualification does not grant authority."""

    def __init__(
        self,
        *,
        model: Any,
        metadata: CheckpointMetadata,
        weights_sha256: str,
        qualification: QualificationResult,
        device: str,
    ) -> None:
        torch, _ = _torch_modules()
        self._torch = torch
        self.model = model.to(device).eval()
        self.metadata = metadata
        self.weights_sha256 = weights_sha256
        self.qualification = qualification
        self.device = device
        self.runtime_id = f"{RUNTIME_ID_PREFIX}:{weights_sha256[:16]}"

    def probe(self) -> dict[str, object]:
        return {
            "ready": True,
            "architecture": ARCHITECTURE,
            "runtime_id": self.runtime_id,
            "weights_sha256": self.weights_sha256,
            "perspectives": list(EXPECTED_HEAD_ORDER),
            "text_emotion_dim": self.metadata.dimensions.text_emotion_dim,
            "speech_emotion_dim": self.metadata.dimensions.speech_emotion_dim,
        }

    def qualification_report(self) -> dict[str, object]:
        return {
            "qualified": self.qualification.qualified,
            "reasons": list(self.qualification.reasons),
            "evaluation_id": self.qualification.evaluation_id,
            "advisory_only": True,
            "authorizes_action": False,
        }

    def infer(
        self,
        *,
        text_emotion: Sequence[float],
        speech_emotion: Sequence[float],
        timeout_seconds: float,
    ) -> dict[str, object]:
        _number(timeout_seconds, "timeout_seconds", 0.05, 60.0)
        dims = self.metadata.dimensions
        if len(text_emotion) != dims.text_emotion_dim or len(speech_emotion) != dims.speech_emotion_dim:
            raise SoulTransformerContractError("inference dimensions do not match checkpoint")
        text = self._torch.tensor([list(text_emotion)], dtype=self._torch.float32, device=self.device)
        speech = self._torch.tensor([list(speech_emotion)], dtype=self._torch.float32, device=self.device)
        if not self._torch.isfinite(text).all() or not self._torch.isfinite(speech).all():
            raise SoulTransformerContractError("inference inputs must be finite")
        with self._torch.inference_mode():
            scores, confidences = self.model(text, speech)
            score_temps = self._torch.tensor(
                self.metadata.calibration.score_temperatures,
                dtype=scores.dtype,
                device=scores.device,
            )
            confidence_temps = self._torch.tensor(
                self.metadata.calibration.confidence_temperatures,
                dtype=confidences.dtype,
                device=confidences.device,
            )
            scores = self._torch.tanh(self._torch.atanh(scores.clamp(-0.999999, 0.999999)) / score_temps)
            logits = self._torch.logit(confidences.clamp(0.000001, 0.999999))
            confidences = self._torch.sigmoid(logits / confidence_temps)
        return {
            "scores": [float(value) for value in scores[0].cpu().tolist()],
            "confidences": [float(value) for value in confidences[0].cpu().tolist()],
            "runtime_id": self.runtime_id,
            "weights_sha256": self.weights_sha256,
        }


def create_backend(
    *,
    weights_path: str,
    weights_sha256: str,
    architecture: str,
    perspectives: Sequence[str],
    text_emotion_dim: int,
    speech_emotion_dim: int,
    evaluation_manifest_path: str | None = None,
    device: str | None = None,
) -> SoulTransformerBackend:
    """Create the worker backend after independent digest and metadata checks."""

    if architecture != ARCHITECTURE or tuple(perspectives) != EXPECTED_HEAD_ORDER:
        raise SoulTransformerContractError("worker architecture contract does not match")
    if not _SHA256_RE.fullmatch(weights_sha256):
        raise SoulTransformerContractError("weights SHA-256 is invalid")
    path = Path(weights_path).expanduser().resolve(strict=True)
    actual_digest = sha256_file(path)
    if actual_digest != weights_sha256:
        raise SoulTransformerContractError("weights SHA-256 mismatch")
    torch, _ = _torch_modules()
    payload = _safe_torch_load(torch, path)
    if not isinstance(payload, Mapping) or set(payload) != {"metadata", "state_dict"}:
        raise SoulTransformerContractError("checkpoint envelope is invalid")
    metadata = parse_checkpoint_metadata(payload["metadata"])
    if (
        metadata.dimensions.text_emotion_dim != text_emotion_dim
        or metadata.dimensions.speech_emotion_dim != speech_emotion_dim
    ):
        raise SoulTransformerContractError("worker dimensions do not match checkpoint")
    manifest_path = evaluation_manifest_path or os.getenv(
        "ALPECCA_ROG_HYFUSER_EVALUATION_MANIFEST", ""
    )
    qualification = evaluate_qualification(
        metadata, actual_digest, _load_manifest(manifest_path)
    )
    model = build_model(metadata.dimensions)
    state_dict = payload["state_dict"]
    if not isinstance(state_dict, Mapping):
        raise SoulTransformerContractError("checkpoint state_dict is invalid")
    try:
        model.load_state_dict(state_dict, strict=True)
    except Exception as exc:
        raise SoulTransformerContractError("checkpoint state_dict does not match") from exc
    selected_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    if selected_device not in {"cpu", "cuda"}:
        raise SoulTransformerContractError("device must be cpu or cuda")
    if selected_device == "cuda" and not torch.cuda.is_available():
        raise SoulTransformerContractError("CUDA was requested but is unavailable")
    return SoulTransformerBackend(
        model=model,
        metadata=metadata,
        weights_sha256=actual_digest,
        qualification=qualification,
        device=selected_device,
    )


__all__ = [
    "ARCHITECTURE",
    "CHECKPOINT_SCHEMA",
    "EVALUATION_SCHEMA",
    "EXPECTED_HEAD_ORDER",
    "CalibrationMetadata",
    "CheckpointMetadata",
    "ModelDimensions",
    "QualificationResult",
    "SoulTransformerBackend",
    "SoulTransformerContractError",
    "TorchUnavailableError",
    "build_model",
    "checkpoint_payload",
    "create_backend",
    "evaluate_qualification",
    "parse_checkpoint_metadata",
    "sha256_file",
    "torch_available",
]
