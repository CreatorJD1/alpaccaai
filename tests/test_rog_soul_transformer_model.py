from __future__ import annotations

import copy
import hashlib
import json

import pytest

from alpecca import rog_soul_transformer_model as model_mod
from alpecca import soul


SHA = "a" * 64


def _metadata() -> dict[str, object]:
    return model_mod.CheckpointMetadata(
        dimensions=model_mod.ModelDimensions(),
        calibration=model_mod.CalibrationMetadata(
            method="per-head-temperature-v1",
            score_temperatures=(1.0,) * 7,
            confidence_temperatures=(1.0,) * 7,
            calibration_set_sha256="b" * 64,
        ),
        training_run_id="holyrog-research-run-1",
    ).as_dict()


def _manifest(**metric_overrides: object) -> dict[str, object]:
    metrics: dict[str, object] = {
        "samples": 800,
        "macro_f1": 0.80,
        "per_head_f1": [0.75] * 7,
        "expected_calibration_error": 0.08,
        "text_coverage": 0.98,
        "speech_coverage": 0.90,
    }
    metrics.update(metric_overrides)
    return {
        "schema": model_mod.EVALUATION_SCHEMA,
        "version": model_mod.MODEL_VERSION,
        "evaluation_id": "holyrog-eval-1",
        "checkpoint_sha256": SHA,
        "architecture": model_mod.ARCHITECTURE,
        "head_order": list(model_mod.EXPECTED_HEAD_ORDER),
        "dimensions": model_mod.ModelDimensions().as_dict(),
        "metrics": metrics,
        "evaluation_data_sha256": "c" * 64,
    }


def test_normal_import_preserves_exact_soul_order_without_requiring_torch() -> None:
    assert model_mod.EXPECTED_HEAD_ORDER == soul.PERSPECTIVE_ORDER
    assert len(model_mod.EXPECTED_HEAD_ORDER) == 7


def test_checkpoint_metadata_is_strict_versioned_calibrated_and_unqualified() -> None:
    parsed = model_mod.parse_checkpoint_metadata(_metadata())
    assert parsed.dimensions.text_emotion_dim == 7
    assert parsed.calibration.method == "per-head-temperature-v1"
    assert parsed.qualified is False
    assert parsed.as_dict()["authorizes_action"] is False


@pytest.mark.parametrize(
    "mutation,error",
    [
        (("head_order", list(reversed(model_mod.EXPECTED_HEAD_ORDER))), "exact Soul order"),
        (("qualified", True), "self-declare"),
        (("architecture", "seven-base-encoders"), "architecture"),
        (("version", 2), "schema or version"),
    ],
)
def test_checkpoint_parser_rejects_contract_drift(mutation, error: str) -> None:
    value = _metadata()
    value[mutation[0]] = mutation[1]
    with pytest.raises(model_mod.SoulTransformerContractError, match=error):
        model_mod.parse_checkpoint_metadata(value)


def test_checkpoint_cannot_qualify_without_separate_manifest() -> None:
    metadata = model_mod.parse_checkpoint_metadata(_metadata())
    result = model_mod.evaluate_qualification(metadata, SHA, None)
    assert result.qualified is False
    assert result.reasons == ("evaluation_manifest_missing",)


def test_evaluation_manifest_qualifies_only_above_code_owned_thresholds() -> None:
    metadata = model_mod.parse_checkpoint_metadata(_metadata())
    result = model_mod.evaluate_qualification(metadata, SHA, _manifest())
    assert result.qualified is True
    assert result.reasons == ()


@pytest.mark.parametrize(
    "metric,value,reason",
    [
        ("samples", 499, "insufficient_samples"),
        ("macro_f1", 0.71, "macro_f1_below_threshold"),
        ("per_head_f1", [0.75] * 6 + [0.59], "per_head_f1_below_threshold"),
        ("expected_calibration_error", 0.13, "calibration_error_above_threshold"),
        ("text_coverage", 0.89, "text_coverage_below_threshold"),
        ("speech_coverage", 0.74, "speech_coverage_below_threshold"),
    ],
)
def test_each_evaluation_gate_fails_closed(metric: str, value: object, reason: str) -> None:
    metadata = model_mod.parse_checkpoint_metadata(_metadata())
    result = model_mod.evaluate_qualification(metadata, SHA, _manifest(**{metric: value}))
    assert result.qualified is False
    assert reason in result.reasons


def test_evaluation_manifest_is_bound_to_checkpoint_order_and_dimensions() -> None:
    metadata = model_mod.parse_checkpoint_metadata(_metadata())
    wrong_digest = _manifest()
    wrong_digest["checkpoint_sha256"] = "d" * 64
    with pytest.raises(model_mod.SoulTransformerContractError, match="does not match"):
        model_mod.evaluate_qualification(metadata, SHA, wrong_digest)
    wrong_order = _manifest()
    wrong_order["head_order"] = list(reversed(model_mod.EXPECTED_HEAD_ORDER))
    with pytest.raises(model_mod.SoulTransformerContractError, match="exact Soul order"):
        model_mod.evaluate_qualification(metadata, SHA, wrong_order)


@pytest.mark.skipif(not model_mod.torch_available(), reason="optional PyTorch unavailable")
def test_torch_model_uses_one_shared_projection_and_seven_distinct_heads() -> None:
    torch, _ = model_mod._torch_modules()
    dimensions = model_mod.ModelDimensions(dropout=0.0)
    model = model_mod.build_model(dimensions)
    text = torch.zeros(3, dimensions.text_emotion_dim)
    speech = torch.ones(3, dimensions.speech_emotion_dim)
    scores, confidences = model(text, speech)
    assert scores.shape == (3, 7)
    assert confidences.shape == (3, 7)
    assert torch.all(scores >= -1.0) and torch.all(scores <= 1.0)
    assert torch.all(confidences >= 0.0) and torch.all(confidences <= 1.0)
    assert hasattr(model, "modality_projection")
    assert not hasattr(model, "text_projection")
    assert not hasattr(model, "speech_projection")
    assert len(model.perspective_heads) == 7
    parameter_ids = {
        id(next(head.parameters())) for head in model.perspective_heads
    }
    assert len(parameter_ids) == 7


@pytest.mark.skipif(not model_mod.torch_available(), reason="optional PyTorch unavailable")
def test_checkpoint_round_trip_stays_shadow_only(tmp_path) -> None:
    torch, _ = model_mod._torch_modules()
    metadata = model_mod.parse_checkpoint_metadata(_metadata())
    model = model_mod.build_model(metadata.dimensions)
    checkpoint = tmp_path / "soul-shadow.pt"
    torch.save(model_mod.checkpoint_payload(model, metadata), checkpoint)
    digest = model_mod.sha256_file(checkpoint)
    backend = model_mod.create_backend(
        weights_path=str(checkpoint),
        weights_sha256=digest,
        architecture=model_mod.ARCHITECTURE,
        perspectives=model_mod.EXPECTED_HEAD_ORDER,
        emotion_order=model_mod.EXPECTED_EMOTION_ORDER,
        text_emotion_dim=7,
        speech_emotion_dim=7,
        device="cpu",
    )
    assert backend.qualification_report() == {
        "qualified": False,
        "reasons": ["evaluation_manifest_missing"],
        "evaluation_id": None,
        "advisory_only": True,
        "authorizes_action": False,
    }
    result = backend.infer(
        text_emotion=[1.0] + [0.0] * 6,
        speech_emotion=[1.0] + [0.0] * 6,
        emotion_order=model_mod.EXPECTED_EMOTION_ORDER,
        timeout_seconds=1.0,
    )
    assert len(result["scores"]) == 7
    assert len(result["confidences"]) == 7
    assert result["weights_sha256"] == digest


def test_checkpoint_hash_verification_rejects_changed_file(tmp_path) -> None:
    checkpoint = tmp_path / "checkpoint.bin"
    checkpoint.write_bytes(b"checkpoint")
    digest = model_mod.sha256_file(checkpoint)
    assert digest == hashlib.sha256(b"checkpoint").hexdigest()
    checkpoint.write_bytes(b"changed")
    assert model_mod.sha256_file(checkpoint) != digest
