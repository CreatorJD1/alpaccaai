from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpecca.emotion_llama_teacher import (
    COMPARISON_SCHEMA,
    QualificationError,
    TeacherResult,
    compare_teacher_to_hyfuser,
    hash_asset,
    qualify_manifest,
)


DEPENDENCIES = [
    {"name": "python", "observed_version": "3.9", "qualified": True},
    {"name": "torch", "observed_version": "2.0.0", "qualified": True},
    {"name": "transformers", "observed_version": "4.30.0", "qualified": True},
    {"name": "opencv-python", "observed_version": "4.7.0.72", "qualified": True},
    {"name": "moviepy", "observed_version": "1.0.3", "qualified": True},
    {"name": "soundfile", "observed_version": "0.12.1", "qualified": True},
]
ASSET_IDS = (
    "emotion_llama_checkout",
    "emotion_llama_checkpoint",
    "llama2_7b_chat_hf",
    "minigpt_v2_checkpoint",
    "hubert_large",
)
PERSPECTIVES = (
    "Feeler", "Expressor", "Carer", "Doer", "Wanderer", "Reflector", "Improver"
)


def _manifest(tmp_path: Path, repo: Path, *, enabled: bool = True) -> Path:
    asset_root = tmp_path / "external-assets"
    asset_root.mkdir()
    assets = []
    for index, asset_id in enumerate(ASSET_IDS):
        path = asset_root / asset_id
        if asset_id in {"emotion_llama_checkout", "llama2_7b_chat_hf", "hubert_large"}:
            path.mkdir()
            (path / "asset.bin").write_bytes(f"asset-{index}".encode())
        else:
            path.write_bytes(f"asset-{index}".encode())
        digest, _, _ = hash_asset(path)
        assets.append({"id": asset_id, "path": str(path.resolve()), "sha256": digest})
    value = {
        "schema": "alpecca.emotion-llama-qualification.v1",
        "enabled": enabled,
        "host": "Jason_HOLYROG",
        "policy": {
            "research_only": True,
            "normal_runtime_import": False,
            "conversational_generation": False,
            "action_authority": False,
        },
        "source": {"repository": "https://github.com/ZebangCheng/Emotion-LLaMA"},
        "licensing": {
            "code": "BSD-3-Clause",
            "mer_data": "research-only-EULA",
            "mer_data_used": False,
            "eula_accepted": False,
        },
        "dependencies": DEPENDENCIES,
        "assets": assets,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _advisory() -> dict[str, object]:
    return {
        "advisory_only": True,
        "authorizes_action": False,
        "heads": [
            {"perspective": name, "score": 0.1 + index * 0.1, "confidence": 0.6}
            for index, name in enumerate(PERSPECTIVES)
        ],
    }


def test_manifest_fails_closed_without_opt_in(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = _manifest(tmp_path, repo, enabled=False)
    with pytest.raises(QualificationError, match="explicit opt-in"):
        qualify_manifest(manifest, repository_root=repo, acknowledge_research_only=True)
    with pytest.raises(QualificationError, match="explicit opt-in"):
        qualify_manifest(manifest, repository_root=repo, acknowledge_research_only=False)


def test_manifest_qualifies_explicit_external_assets(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    lane = qualify_manifest(
        _manifest(tmp_path, repo),
        repository_root=repo,
        acknowledge_research_only=True,
    )
    assert lane.host == "Jason_HOLYROG"
    assert len(lane.assets) == 5
    assert lane.as_dict()["action_authority"] is False


def test_manifest_rejects_asset_inside_git_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = _manifest(tmp_path, repo)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    inside = repo / "weight.pth"
    inside.write_bytes(b"not-in-git")
    digest, _, _ = hash_asset(inside)
    value["assets"][1] = {
        "id": "emotion_llama_checkpoint", "path": str(inside), "sha256": digest
    }
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(QualificationError, match="outside Git"):
        qualify_manifest(manifest, repository_root=repo, acknowledge_research_only=True)


def test_manifest_rejects_digest_mismatch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    manifest = _manifest(tmp_path, repo)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["assets"][1]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(QualificationError, match="SHA-256 mismatch"):
        qualify_manifest(manifest, repository_root=repo, acknowledge_research_only=True)


def test_comparison_is_seven_head_shadow_evidence_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    lane = qualify_manifest(
        _manifest(tmp_path, repo), repository_root=repo, acknowledge_research_only=True
    )
    teacher = TeacherResult.from_mapping(
        {
            "sample_ref": "sample:abc-123",
            "label": "happiness",
            "confidence": 0.8,
            "reason_clues": ["Her voice and facial expression show joy", "She wants to explore"],
            "checkpoint_sha256": lane.checkpoint_sha256,
        }
    )
    result = compare_teacher_to_hyfuser(teacher, _advisory(), qualified_lane=lane)
    assert result["schema"] == COMPARISON_SCHEMA
    assert [item["perspective"] for item in result["perspectives"]] == list(PERSPECTIVES)
    assert result["teacher"]["label"] == "joy"
    assert result["authorizes_action"] is False
    assert result["changes_soul_state"] is False
    assert "voice and facial" not in json.dumps(result)


def test_comparison_rejects_wrong_checkpoint_or_head_order(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    lane = qualify_manifest(
        _manifest(tmp_path, repo), repository_root=repo, acknowledge_research_only=True
    )
    teacher = TeacherResult.from_mapping(
        {
            "sample_ref": "sample:one",
            "label": "fear",
            "confidence": 0.7,
            "reason_clues": [],
            "checkpoint_sha256": "a" * 64,
        }
    )
    with pytest.raises(QualificationError, match="qualified checkpoint"):
        compare_teacher_to_hyfuser(teacher, _advisory(), qualified_lane=lane)
    valid_teacher = TeacherResult(
        teacher.sample_ref, teacher.label, teacher.confidence, teacher.reason_clues,
        lane.checkpoint_sha256,
    )
    invalid = _advisory()
    invalid["heads"][0]["perspective"] = "Improver"
    with pytest.raises(ValueError, match="order or identity"):
        compare_teacher_to_hyfuser(valid_teacher, invalid, qualified_lane=lane)
