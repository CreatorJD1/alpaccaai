"""Audit the Stage 4 walk-cycle generation contract.

This catches the failure mode where walk prompts silently fall back to vague
"walk frame" text and new generations repeat leg poses or lose foot grounding.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_ROOT = REPO_ROOT / "data" / "alpecca_art_source"
STAGE4_ROOT = LIBRARY_ROOT / "stage4_generation_batches"
WALK_GUIDE = LIBRARY_ROOT / "external_walk_cycle_references" / "walk_cycle_3d_pose_guide.jpg"
WALK_MANIFEST = LIBRARY_ROOT / "external_walk_cycle_references" / "manifest.json"
WALK_DOC = REPO_ROOT / "docs" / "ALPECCA_STAGE4_WALK_CYCLE_POSE_LOCK.md"
EXPORT_MANIFEST = REPO_ROOT / "output" / "alpecca_stage4_tile_jobs" / "batch_02" / "tile_job_manifest.json"

REQUIRED_PROMPT_TERMS = [
    "walk_cycle_3d_pose_guide.jpg",
    "ALPECCA_STAGE4_WALK_CYCLE_POSE_LOCK.md",
    "contact, down, passing, and up",
    "Do not repeat adjacent or alternating leg positions",
    "shared baseline",
    "no thigh-width changes",
]

REQUIRED_EXPORT_REFERENCES = [
    "data/alpecca_art_source/external_walk_cycle_references/walk_cycle_3d_pose_guide.jpg",
    "data/alpecca_art_source/external_walk_cycle_references/manifest.json",
    "docs/ALPECCA_STAGE4_WALK_CYCLE_POSE_LOCK.md",
]

REQUIRED_WALK_SEED_POLICY = "reference-only-no-img2img-for-single-sprite-proof"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_walk_batch() -> Path:
    matches = sorted(STAGE4_ROOT.glob("batch_02_*walk*"))
    if not matches:
        raise FileNotFoundError("Missing Stage 4 Batch 02 walk directory.")
    return matches[0]


def main() -> int:
    errors: list[str] = []
    for path in [WALK_GUIDE, WALK_MANIFEST, WALK_DOC]:
        if not path.exists():
            errors.append(f"Missing walk reference file: {path}")

    queue = load_json(LIBRARY_ROOT / "generation_queue.json")
    walk_targets = [target for target in queue.get("targets", []) if target.get("action") == "walk"]
    if len(walk_targets) != 48:
        errors.append(f"Expected 48 walk targets, found {len(walk_targets)}.")
    for target in walk_targets:
        if int(target.get("targetFrameCount") or 0) != 16:
            errors.append(f"{target.get('id')} has frame count {target.get('targetFrameCount')}, expected 16.")
    walk_art_pieces = sum(int(target.get("targetFrameCount") or 0) for target in walk_targets)
    if walk_art_pieces != 768:
        errors.append(f"Expected 768 walk art pieces, found {walk_art_pieces}.")

    try:
        batch_path = find_walk_batch()
    except FileNotFoundError as exc:
        errors.append(str(exc))
        batch_path = None

    checked_prompts = 0
    if batch_path:
        prompt_paths = sorted(batch_path.glob("targets/*/incoming/frame_tiles/prompts/frame_000.md"))
        if len(prompt_paths) != 48:
            errors.append(f"Expected 48 first-frame walk prompts, found {len(prompt_paths)}.")
        for prompt_path in prompt_paths:
            text = prompt_path.read_text(encoding="utf-8")
            checked_prompts += 1
            for term in REQUIRED_PROMPT_TERMS:
                if term not in text:
                    errors.append(f"{prompt_path} missing prompt term: {term}")
                    break

        plan_paths = sorted(batch_path.glob("targets/*/incoming/tile_generation_plan.json"))
        if len(plan_paths) != 48:
            errors.append(f"Expected 48 walk tile plans, found {len(plan_paths)}.")
        for plan_path in plan_paths:
            plan = load_json(plan_path)
            frames = plan.get("frames", [])
            if len(frames) != 16:
                errors.append(f"{plan_path} has {len(frames)} frames, expected 16.")
                continue
            pose_notes = [str(frame.get("poseNote") or "") for frame in frames]
            for phase in ["contact A", "down A", "passing A", "up A", "contact B", "passing B", "up B return"]:
                if not any(phase in note for note in pose_notes):
                    errors.append(f"{plan_path} missing pose phase: {phase}")
                    break

    if EXPORT_MANIFEST.exists():
        manifest = load_json(EXPORT_MANIFEST)
        references = set(manifest.get("referenceFiles") or [])
        for reference in REQUIRED_EXPORT_REFERENCES:
            if reference not in references:
                errors.append(f"Export manifest missing reference: {reference}")
        for chunk in manifest.get("chunks", []):
            chunk_path = REPO_ROOT / str(chunk.get("file", ""))
            if not chunk_path.exists():
                errors.append(f"Missing export chunk: {chunk_path}")
                continue
            with chunk_path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    job = json.loads(line)
                    if job.get("action") == "walk" and job.get("seedConditionPolicy") != REQUIRED_WALK_SEED_POLICY:
                        errors.append(
                            f"{chunk_path}:{line_number} has seedConditionPolicy={job.get('seedConditionPolicy')!r}, "
                            f"expected {REQUIRED_WALK_SEED_POLICY!r}."
                        )
                        break
    else:
        errors.append(f"Missing exported Batch 02 tile job manifest: {EXPORT_MANIFEST}")

    if errors:
        print("Stage 4 walk-cycle contract audit failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "walkTargets": len(walk_targets),
                "walkArtPieces": walk_art_pieces,
                "checkedPrompts": checked_prompts,
                "walkGuide": str(WALK_GUIDE),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
