"""Research-only Emotion-LLaMA teacher qualification and shadow comparison.

This module is deliberately absent from Alpecca's normal runtime import graph.
It validates an operator-supplied asset manifest and compares an external
Emotion-LLaMA result with the seven HyFusER Soul shadow heads. It never loads
model code, performs inference, generates conversation, mutates Soul state, or
authorizes an action.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


MANIFEST_SCHEMA = "alpecca.emotion-llama-qualification.v1"
COMPARISON_SCHEMA = "alpecca.emotion-llama-shadow-comparison.v1"
OFFICIAL_REPOSITORY = "https://github.com/ZebangCheng/Emotion-LLaMA"
EXPECTED_HOST = "Jason_HOLYROG"
PERSPECTIVE_ORDER = (
    "Feeler",
    "Expressor",
    "Carer",
    "Doer",
    "Wanderer",
    "Reflector",
    "Improver",
)
EMOTION_ORDER = (
    "neutral",
    "joy",
    "sadness",
    "fear",
    "anger",
    "surprise",
    "disgust",
)
REQUIRED_ASSETS = (
    "emotion_llama_checkout",
    "emotion_llama_checkpoint",
    "llama2_7b_chat_hf",
    "minigpt_v2_checkpoint",
    "hubert_large",
)
REQUIRED_DEPENDENCIES = {
    "python": "3.9",
    "torch": "2.0.0",
    "transformers": "4.30.0",
    "opencv-python": "4.7.0.72",
    "moviepy": "1.0.3",
    "soundfile": "0.12.1",
}
MAX_ASSET_FILES = 120_000
MAX_ASSET_BYTES = 96 * 1024 * 1024 * 1024
MAX_REASON_CLUES = 8
MAX_CLUE_CHARS = 240
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")

_LABEL_ALIASES = {
    "happy": "joy",
    "happiness": "joy",
    "sad": "sadness",
    "angry": "anger",
    "fearful": "fear",
    "surprised": "surprise",
    "neutral": "neutral",
    "joy": "joy",
    "sadness": "sadness",
    "fear": "fear",
    "anger": "anger",
    "surprise": "surprise",
    "disgust": "disgust",
}

_PERSPECTIVE_WEIGHTS = (
    (0.15, 0.75, 0.90, 1.00, 0.85, 0.65, 0.75),
    (0.10, 1.00, 0.70, 0.85, 0.90, 0.85, 0.70),
    (0.10, 0.45, 1.00, 1.00, 0.65, 0.50, 0.80),
    (0.20, 0.55, 0.35, 0.75, 0.75, 0.70, 0.60),
    (0.15, 0.90, 0.25, 0.35, 0.30, 1.00, 0.35),
    (0.20, 0.40, 0.90, 0.90, 0.70, 0.55, 0.85),
    (0.20, 0.45, 0.70, 0.80, 0.75, 0.75, 0.90),
)

_CLUE_TERMS = {
    "Feeler": ("feel", "emotion", "tone", "expression", "voice"),
    "Expressor": ("say", "speech", "express", "face", "gesture"),
    "Carer": ("care", "hurt", "comfort", "need", "safety"),
    "Doer": ("act", "move", "change", "respond", "avoid"),
    "Wanderer": ("curious", "novel", "explore", "wonder", "surprise"),
    "Reflector": ("because", "pattern", "remember", "meaning", "context"),
    "Improver": ("learn", "repair", "improve", "mistake", "correct"),
}


class QualificationError(RuntimeError):
    """The research lane is not explicitly and completely qualified."""


def _unit(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    checked = float(value)
    if not math.isfinite(checked) or not 0.0 <= checked <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return checked


def _sha256_file(path: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ASSET_BYTES:
                raise QualificationError("asset exceeds the qualification byte cap")
            digest.update(chunk)
    return digest.hexdigest(), 1, total


def _sha256_tree(path: Path) -> tuple[str, int, int]:
    """Hash a directory deterministically without following symlinks."""

    digest = hashlib.sha256()
    files = 0
    total = 0
    for child in sorted(path.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if ".git" in child.relative_to(path).parts:
            continue
        if child.is_symlink():
            raise QualificationError("qualified asset trees cannot contain symlinks")
        if not child.is_file():
            continue
        files += 1
        if files > MAX_ASSET_FILES:
            raise QualificationError("asset tree exceeds the qualification file cap")
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with child.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ASSET_BYTES:
                    raise QualificationError("asset tree exceeds the qualification byte cap")
                digest.update(chunk)
    if files == 0:
        raise QualificationError("qualified asset directory is empty")
    return digest.hexdigest(), files, total


def hash_asset(path: Path) -> tuple[str, int, int]:
    resolved = path.expanduser().resolve(strict=True)
    if resolved.is_symlink():
        raise QualificationError("qualified assets cannot be symlinks")
    if resolved.is_file():
        return _sha256_file(resolved)
    if resolved.is_dir():
        return _sha256_tree(resolved)
    raise QualificationError("qualified asset must be a file or directory")


@dataclass(frozen=True, slots=True)
class QualifiedAsset:
    asset_id: str
    path: str
    sha256: str
    files: int
    bytes: int


@dataclass(frozen=True, slots=True)
class QualifiedTeacherLane:
    manifest_path: str
    host: str
    assets: tuple[QualifiedAsset, ...]
    checkpoint_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": MANIFEST_SCHEMA,
            "qualified": True,
            "host": self.host,
            "research_only": True,
            "normal_runtime_import": False,
            "conversational_generation": False,
            "action_authority": False,
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "path": asset.path,
                    "sha256": asset.sha256,
                    "files": asset.files,
                    "bytes": asset.bytes,
                }
                for asset in self.assets
            ],
            "checkpoint_sha256": self.checkpoint_sha256,
        }


def _outside_repository(path: Path, repository_root: Path) -> bool:
    try:
        path.relative_to(repository_root)
    except ValueError:
        return True
    return False


def qualify_manifest(
    manifest_path: str | Path,
    *,
    repository_root: str | Path,
    acknowledge_research_only: bool,
) -> QualifiedTeacherLane:
    """Verify every opt-in, license, dependency, path, and digest gate."""

    path = Path(manifest_path).expanduser().resolve(strict=True)
    root = Path(repository_root).expanduser().resolve(strict=True)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("qualification manifest is unreadable") from exc
    if not isinstance(raw, Mapping) or raw.get("schema") != MANIFEST_SCHEMA:
        raise QualificationError("qualification manifest schema is invalid")
    if raw.get("enabled") is not True or not acknowledge_research_only:
        raise QualificationError("research-only teacher requires explicit opt-in")
    if raw.get("host") != EXPECTED_HOST:
        raise QualificationError(f"teacher lane is restricted to {EXPECTED_HOST}")
    policy = raw.get("policy")
    if not isinstance(policy, Mapping) or policy != {
        "research_only": True,
        "normal_runtime_import": False,
        "conversational_generation": False,
        "action_authority": False,
    }:
        raise QualificationError("teacher policy must remain evaluation-only")
    source = raw.get("source")
    if not isinstance(source, Mapping) or source.get("repository") != OFFICIAL_REPOSITORY:
        raise QualificationError("official Emotion-LLaMA repository is required")
    licensing = raw.get("licensing")
    if not isinstance(licensing, Mapping):
        raise QualificationError("license declaration is missing")
    if licensing.get("code") != "BSD-3-Clause":
        raise QualificationError("Emotion-LLaMA code license must be BSD-3-Clause")
    if licensing.get("mer_data") != "research-only-EULA":
        raise QualificationError("MER data must retain its research-only EULA boundary")
    if licensing.get("mer_data_used") is True and licensing.get("eula_accepted") is not True:
        raise QualificationError("MER data use requires recorded EULA acceptance")

    dependencies = raw.get("dependencies")
    if not isinstance(dependencies, list):
        raise QualificationError("dependency qualification is missing")
    observed: dict[str, str] = {}
    for item in dependencies:
        if not isinstance(item, Mapping):
            raise QualificationError("dependency records must be objects")
        name = item.get("name")
        version = item.get("observed_version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise QualificationError("dependency name/version is invalid")
        if item.get("qualified") is not True:
            raise QualificationError(f"dependency {name} is not qualified")
        observed[name] = version
    for name, version in REQUIRED_DEPENDENCIES.items():
        if observed.get(name) != version:
            raise QualificationError(f"dependency {name} must be qualified at {version}")

    assets_raw = raw.get("assets")
    if not isinstance(assets_raw, list):
        raise QualificationError("asset qualification is missing")
    assets_by_id: dict[str, Mapping[str, object]] = {}
    for item in assets_raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            raise QualificationError("asset record is invalid")
        asset_id = str(item["id"])
        if asset_id in assets_by_id:
            raise QualificationError("asset identifiers must be unique")
        assets_by_id[asset_id] = item
    if set(assets_by_id) != set(REQUIRED_ASSETS):
        raise QualificationError("manifest must contain the exact required asset set")

    qualified: list[QualifiedAsset] = []
    for asset_id in REQUIRED_ASSETS:
        record = assets_by_id[asset_id]
        raw_path = record.get("path")
        expected = record.get("sha256")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise QualificationError(f"asset {asset_id} requires an explicit path")
        if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
            raise QualificationError(f"asset {asset_id} requires an explicit SHA-256")
        asset_path = Path(raw_path).expanduser()
        if not asset_path.is_absolute():
            raise QualificationError(f"asset {asset_id} path must be absolute")
        resolved = asset_path.resolve(strict=True)
        if not _outside_repository(resolved, root):
            raise QualificationError("model code, weights, and datasets must stay outside Git")
        actual, files, byte_count = hash_asset(resolved)
        if actual != expected:
            raise QualificationError(f"asset {asset_id} SHA-256 mismatch")
        qualified.append(QualifiedAsset(asset_id, str(resolved), actual, files, byte_count))

    checkpoint = next(
        asset.sha256 for asset in qualified if asset.asset_id == "emotion_llama_checkpoint"
    )
    return QualifiedTeacherLane(str(path), EXPECTED_HOST, tuple(qualified), checkpoint)


@dataclass(frozen=True, slots=True)
class TeacherResult:
    sample_ref: str
    label: str
    confidence: float
    reason_clues: tuple[str, ...]
    checkpoint_sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "TeacherResult":
        if set(value) != {
            "sample_ref", "label", "confidence", "reason_clues", "checkpoint_sha256"
        }:
            raise ValueError("teacher result has missing or extra fields")
        sample_ref = value.get("sample_ref")
        label = value.get("label")
        clues = value.get("reason_clues")
        digest = value.get("checkpoint_sha256")
        if not isinstance(sample_ref, str) or not _SAFE_REF_RE.fullmatch(sample_ref):
            raise ValueError("teacher sample_ref is invalid")
        if not isinstance(label, str) or label.strip().casefold() not in _LABEL_ALIASES:
            raise ValueError("teacher emotion label is unsupported")
        if not isinstance(clues, list) or len(clues) > MAX_REASON_CLUES:
            raise ValueError("teacher reason_clues exceed the bound")
        checked_clues: list[str] = []
        for clue in clues:
            if not isinstance(clue, str):
                raise ValueError("teacher reason clue must be text")
            cleaned = " ".join(clue.split())
            if not cleaned or len(cleaned) > MAX_CLUE_CHARS:
                raise ValueError("teacher reason clue has an invalid length")
            checked_clues.append(cleaned)
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise ValueError("teacher checkpoint SHA-256 is invalid")
        return cls(
            sample_ref=sample_ref,
            label=_LABEL_ALIASES[label.strip().casefold()],
            confidence=_unit(value.get("confidence"), field="teacher confidence"),
            reason_clues=tuple(checked_clues),
            checkpoint_sha256=digest,
        )


def _parse_shadow_heads(value: Mapping[str, object]) -> tuple[tuple[float, float], ...]:
    if value.get("advisory_only") is not True or value.get("authorizes_action") is not False:
        raise ValueError("HyFusER input must remain advisory-only")
    heads = value.get("heads")
    if not isinstance(heads, list) or len(heads) != len(PERSPECTIVE_ORDER):
        raise ValueError("HyFusER input must contain exactly seven heads")
    parsed: list[tuple[float, float]] = []
    for perspective, record in zip(PERSPECTIVE_ORDER, heads, strict=True):
        if not isinstance(record, Mapping) or record.get("perspective") != perspective:
            raise ValueError("HyFusER head order or identity is invalid")
        parsed.append(
            (
                _unit(record.get("score"), field="HyFusER score"),
                _unit(record.get("confidence"), field="HyFusER confidence"),
            )
        )
    return tuple(parsed)


def compare_teacher_to_hyfuser(
    teacher: TeacherResult,
    hyfuser_advisory: Mapping[str, object],
    *,
    qualified_lane: QualifiedTeacherLane,
) -> dict[str, object]:
    """Compare teacher evidence to seven shadow heads without applying it."""

    if teacher.checkpoint_sha256 != qualified_lane.checkpoint_sha256:
        raise QualificationError("teacher result checkpoint is not the qualified checkpoint")
    shadow_heads = _parse_shadow_heads(hyfuser_advisory)
    emotion_index = EMOTION_ORDER.index(teacher.label)
    clue_tokens = [set(re.findall(r"[a-z]+", clue.casefold())) for clue in teacher.reason_clues]
    clue_refs = [hashlib.sha256(clue.encode("utf-8")).hexdigest()[:16] for clue in teacher.reason_clues]
    comparisons: list[dict[str, object]] = []
    for index, perspective in enumerate(PERSPECTIVE_ORDER):
        shadow_score, shadow_confidence = shadow_heads[index]
        teacher_score = min(1.0, _PERSPECTIVE_WEIGHTS[index][emotion_index] * teacher.confidence)
        terms = set(_CLUE_TERMS[perspective])
        matched = [ref for ref, tokens in zip(clue_refs, clue_tokens, strict=True) if terms & tokens]
        comparisons.append(
            {
                "perspective": perspective,
                "teacher_expected_score": round(teacher_score, 6),
                "shadow_score": round(shadow_score, 6),
                "absolute_delta": round(abs(teacher_score - shadow_score), 6),
                "teacher_confidence": round(teacher.confidence, 6),
                "shadow_confidence": round(shadow_confidence, 6),
                "confidence_delta": round(abs(teacher.confidence - shadow_confidence), 6),
                "reason_clue_refs": matched,
            }
        )
    return {
        "schema": COMPARISON_SCHEMA,
        "sample_ref": teacher.sample_ref,
        "teacher": {
            "label": teacher.label,
            "confidence": round(teacher.confidence, 6),
            "checkpoint_sha256": teacher.checkpoint_sha256,
            "reason_clue_refs": clue_refs,
            "reason_clue_count": len(clue_refs),
        },
        "perspectives": comparisons,
        "qualified_host": qualified_lane.host,
        "teacher_only": True,
        "shadow_only": True,
        "normal_runtime_import": False,
        "changes_soul_state": False,
        "conversational_generation": False,
        "authorizes_action": False,
    }


__all__ = [
    "COMPARISON_SCHEMA",
    "EXPECTED_HOST",
    "MANIFEST_SCHEMA",
    "OFFICIAL_REPOSITORY",
    "QualificationError",
    "QualifiedTeacherLane",
    "TeacherResult",
    "compare_teacher_to_hyfuser",
    "hash_asset",
    "qualify_manifest",
]
