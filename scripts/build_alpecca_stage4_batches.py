"""Build Stage 4 generation batch workspaces for Alpecca matrix animation.

Stage 4 is the first production-art generation gate. It does not put raw source
art in the browser. Instead, it turns the Stage 1 generation queue and Stage 3
reference boards into small, repeatable work orders for complete animation
strips. Approved strips can later be compiled into runtime atlas folders.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_ROOT = REPO_ROOT / "data" / "alpecca_art_source"
DEFAULT_RUNTIME_ROOT = REPO_ROOT / "apps" / "house-hq" / "public" / "assets" / "alpecca-optimized"
STAGE4_DIR_NAME = "stage4_generation_batches"
PUBLIC_PLAN_NAME = "stage4_runtime_plan.json"

REFERENCE_BOARD_FILES = {
    "identity": "reference_boards/identity_turnaround_lock.jpg",
    "movement": "reference_boards/movement_direction_reference.jpg",
    "expression": "reference_boards/expression_talk_reference.jpg",
    "scale": "reference_boards/scale_anchor_reference.jpg",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def slug(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return value or "batch"


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def prompt_for_target(target: dict[str, Any]) -> str:
    gates = "\n".join(f"- {gate}" for gate in target.get("qualityGates", []))
    refs = ", ".join(target.get("seedReferenceSlots") or ["reference boards"])
    direction = target.get("movementDirection") or "none"
    reference_horizontal = target.get("referenceHorizontalTier") or target.get("horizontalTier")
    view_sector = target.get("viewSector16") or "not-sector-specific"
    layer_role = target.get("layerRole") or "base-body"
    strip_px = int(target["targetFrameCount"]) * int(target["targetSlotPixels"])
    runtime_slot_px = int(target.get("runtimeSlotPixels") or 512)
    return f"""# Alpecca Stage 4 Generation Prompt

Generate one complete transparent animation strip for Alpecca.

## Target
- id: `{target["id"]}`
- action: `{target["action"]}`
- camera vertical tier: `{target["verticalTier"]}`
- 16-view camera sector: `{view_sector}`
- relative yaw tier/reference family: `{reference_horizontal}`
- movement direction: `{direction}`
- layer role: `{layer_role}`
- frame count: `{target["targetFrameCount"]}`
- frame slot: `{target["targetSlotPixels"]} x {target["targetSlotPixels"]}` pixels
- total strip canvas: `{strip_px} x {target["targetSlotPixels"]}` pixels
- minimum source quality: `4K per frame slot`
- runtime compile target: `{runtime_slot_px} x {runtime_slot_px}` pixels after QA approval
- output folder: `{target["outputFolderSuggestion"]}`
- existing runtime fallback: `{target.get("existingRuntimeFallback") or "none"}`

## Reference Boards
- `reference_boards/identity_turnaround_lock.jpg`
- `reference_boards/movement_direction_reference.jpg`
- `reference_boards/expression_talk_reference.jpg`
- `reference_boards/scale_anchor_reference.jpg`
- `ALPECCA_DESIGN_LOCK.md`

Use these source slots as the strongest references: {refs}.

## Hard Requirements
{gates}

## Style And Composition
- Use existing Alpecca art as identity lock and direction reference only.
- Generate new coherent production art; do not collage loose existing frames.
- Keep her an adult woman at 5ft 7in / 1.704m in standing actions.
- Follow `ALPECCA_DESIGN_LOCK.md` exactly. Do not redesign her.
- Keep the same face, blue eyes, long white-silver hair with pale lavender-blue lower accents, single ahoge strand, and one small blue X/bow hair clip on her left side.
- Keep the oversized warm ivory/cream hoodie-jacket with pale blue trim, blue sleeve/zipper/pocket accents, black sleeve tech patch, white inner shirt, blue lanyard, and Alpecca ID badge.
- Keep black high-waist shorts.
- Keep white full-length thigh-high stockings reaching the upper thigh under the shorts; stocking length, thickness, and white color must stay consistent in every frame.
- Keep the black right-leg thigh strap where that side of the leg is visible.
- Keep chunky cream/white comfort boots with pale blue soles and blue details. Do not turn the boots into sneakers.
- Keep leg length, thigh width, boot size, head size, and body proportions stable across frames.
- Do not add a halo to base body frames; halo/ring effects are separate overlay targets.
- Do not add floor shadows, drop shadows, contact shadows, glow smears, or baked lighting halos to base body frames; shadow/depth are separate overlay targets.
- If this target is a halo or shadow overlay, generate only that overlay layer on transparent background, aligned to the body anchor, with no body repaint.
- Do not add blue orbs, round ear-like discs, floating balls, invented head accessories, animal ears, or extra ornaments.
- Preserve only approved Alpecca details from the design lock. Reject any output that changes her outfit, stockings, boots, lanyard, hair clip, jacket trim, thigh strap, or body proportions.
- Transparent background only.
- Exactly one row of equal frame slots.
- Generate at 4K minimum per frame slot. Do not upscale a low-resolution result and call it 4K.
- No scenery, labels, UI, duplicate characters, poster layout, or camera background.
- Whole-strip generation only; do not create isolated frames.
"""


def qa_checklist_for_target(target: dict[str, Any]) -> str:
    gates = "\n".join(f"- [ ] {gate}" for gate in target.get("qualityGates", []))
    return f"""# QA Checklist: {target["id"]} / {target["outputFolderSuggestion"]}

## Required Files Before Promotion
- [ ] `incoming/raw_strip.png` exists and is the original generated strip.
- [ ] `approved/spritesheet.png` exists after cleanup and normalization.
- [ ] `approved/spritesheet.webp` exists and is lossless.
- [ ] `approved/atlas.json` exists and matches frame count.
- [ ] `approved/visual.json` exists with bottom-center anchor and feet baseline.
- [ ] `approved/matrix_metadata.json` exists.

## Visual Gates
{gates}

## Runtime Gates
- [ ] Compiled atlas folder uses the target output folder name.
- [ ] Browser loads the compiled atlas, not the Stage 4 source workspace.
- [ ] House HQ debug reports exact matrix key or approved fallback.
- [ ] No random height/scale changes.
- [ ] No loose 400-image runtime requests.
"""


def status_for_target(target_dir: Path, runtime_root: Path, output_folder: str) -> tuple[str, list[str]]:
    approved_dir = target_dir / "approved"
    incoming_dir = target_dir / "incoming"
    runtime_dir = runtime_root / output_folder
    notes: list[str] = []

    if (runtime_dir / "atlas.json").exists() and (runtime_dir / "visual.json").exists():
        return "promoted-runtime", [f"runtime atlas present: {runtime_dir}"]
    if (approved_dir / "spritesheet.png").exists() and (approved_dir / "atlas.json").exists():
        return "approved-awaiting-runtime-compile", ["approved atlas files present"]
    if (approved_dir / "spritesheet.png").exists():
        return "approved-awaiting-atlas", ["approved spritesheet present without atlas.json"]
    if (incoming_dir / "raw_strip.png").exists() or (incoming_dir / "spritesheet.png").exists():
        return "generated-awaiting-qa", ["incoming generated strip present"]
    if (incoming_dir / "seed_canvas.png").exists() and (target_dir / "generation_request.json").exists():
        return "seeded-awaiting-generation", ["clean seed canvas and generation request present"]
    notes.append("no generated strip yet")
    return "planned-generation", notes


def target_contract(
    target: dict[str, Any],
    batch_folder: Path,
    target_dir: Path,
    library_root: Path,
    runtime_root: Path,
) -> dict[str, Any]:
    output_folder = target["outputFolderSuggestion"]
    if output_folder.startswith("matrix_"):
        matrix_key = output_folder.removeprefix("matrix_")
    elif output_folder.startswith("layer_"):
        matrix_key = output_folder.removeprefix("layer_")
    else:
        matrix_key = output_folder
    status, notes = status_for_target(target_dir, runtime_root, output_folder)
    frame_count = int(target["targetFrameCount"])
    slot_px = int(target["targetSlotPixels"])
    runtime_slot_px = int(target.get("runtimeSlotPixels") or 512)
    return {
        "schemaVersion": 1,
        "stage": "stage-4-generation-batch",
        "targetId": target["id"],
        "status": status,
        "statusNotes": notes,
        "batch": target["batch"],
        "batchName": target["batchName"],
        "priority": target["priority"],
        "targetKind": target.get("targetKind", "matrix-atlas"),
        "layerRole": target.get("layerRole"),
        "matrixKey": matrix_key,
        "action": target["action"],
        "verticalTier": target["verticalTier"],
        "horizontalTier": target["horizontalTier"],
        "viewSector16": target.get("viewSector16"),
        "referenceHorizontalTier": target.get("referenceHorizontalTier"),
        "movementDirection": target.get("movementDirection"),
        "frameCount": frame_count,
        "artPieceCount": int(target.get("targetArtPieceCount") or frame_count),
        "slotPixels": slot_px,
        "minimumSourceSlotPixels": int(target.get("minimumSourceSlotPixels") or slot_px),
        "runtimeSlotPixels": runtime_slot_px,
        "expectedStripPixels": [frame_count * slot_px, slot_px],
        "heightClass": (
            "overlay"
            if target.get("targetKind") == "layer-atlas"
            else "adult-standing-5ft7"
            if target["action"] not in {"rest", "sleep", "wake"}
            else "intentional-rest-height"
        ),
        "referenceBoards": REFERENCE_BOARD_FILES,
        "seedReferenceSlots": target.get("seedReferenceSlots", []),
        "seedReferenceSourceIds": target.get("seedReferenceSourceIds", []),
        "existingRuntimeFallback": target.get("existingRuntimeFallback"),
        "fallbackApprovalStatus": target.get("fallbackApprovalStatus"),
        "sourceUsePolicy": target.get("sourceUsePolicy"),
        "layerSeparation": target.get("layerSeparation"),
        "workspace": {
            "targetDir": rel(target_dir, library_root),
            "prompt": rel(target_dir / "prompt.md", library_root),
            "qaChecklist": rel(target_dir / "qa_checklist.md", library_root),
            "incomingRawStrip": rel(target_dir / "incoming" / "raw_strip.png", library_root),
            "approvedSpritesheet": rel(target_dir / "approved" / "spritesheet.png", library_root),
            "approvedAtlas": rel(target_dir / "approved" / "atlas.json", library_root),
        },
        "runtime": {
            "compiledAtlasFolder": output_folder,
            "compiledAtlasPath": rel(runtime_root / output_folder, REPO_ROOT),
            "browserAssetRoot": f"/assets/alpecca-optimized/{output_folder}",
        },
        "qualityGates": target.get("qualityGates", []),
    }


def write_target_workspace(
    target: dict[str, Any],
    batch_folder: Path,
    library_root: Path,
    runtime_root: Path,
) -> dict[str, Any]:
    target_dir = batch_folder / "targets" / f"{target['id']}__{target['outputFolderSuggestion']}"
    (target_dir / "incoming").mkdir(parents=True, exist_ok=True)
    (target_dir / "approved").mkdir(parents=True, exist_ok=True)
    (target_dir / "previews").mkdir(parents=True, exist_ok=True)
    (target_dir / "incoming" / "README.md").write_text(
        "Place the original generated full-strip image here as raw_strip.png.\n",
        encoding="utf-8",
    )
    (target_dir / "approved" / "README.md").write_text(
        "Only normalized QA-approved atlas files belong here before runtime promotion.\n",
        encoding="utf-8",
    )
    (target_dir / "prompt.md").write_text(prompt_for_target(target), encoding="utf-8")
    (target_dir / "qa_checklist.md").write_text(qa_checklist_for_target(target), encoding="utf-8")
    contract = target_contract(target, batch_folder, target_dir, library_root, runtime_root)
    write_json(target_dir / "target.json", contract)
    return contract


def write_batch_readme(batch_folder: Path, batch: dict[str, Any], contracts: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = {}
    for contract in contracts:
        counts[contract["status"]] = counts.get(contract["status"], 0) + 1
    art_piece_count = sum(int(contract.get("artPieceCount") or contract.get("frameCount") or 0) for contract in contracts)
    status_lines = "\n".join(f"- {key}: {value}" for key, value in sorted(counts.items()))
    first_targets = "\n".join(
        f"- `{contract['targetId']}` `{contract['matrixKey']}` -> `{contract['runtime']['compiledAtlasFolder']}`"
        for contract in contracts[:12]
    )
    batch_folder.joinpath("README.md").write_text(
        f"""# Stage 4 Batch {batch['batch']}: {batch['name']}

{batch['description']}

Priority: `{batch['priority']}`
Target kind: `{batch.get('targetKind', 'matrix-atlas')}`
Planned art pieces/frame slots: `{art_piece_count}`

## Status
{status_lines or "- no targets"}

## Workflow
1. Open `batch_manifest.json`.
2. Use each target's `prompt.md` with the Stage 3 reference boards.
3. Save generated strips to `targets/<target>/incoming/raw_strip.png`.
4. Normalize, inspect, and write approved atlas files to `targets/<target>/approved/`.
5. Compile approved folders into `apps/house-hq/public/assets/alpecca-optimized/<outputFolder>`.
6. Rebuild the runtime matrix manifest only after QA acceptance.

## First Targets
{first_targets}
""",
        encoding="utf-8",
    )


def target_dir_contains_art(target_dir: Path) -> bool:
    art_names = {
        "raw_strip.png",
        "spritesheet.png",
        "spritesheet.webp",
        "atlas.json",
        "visual.json",
        "matrix_metadata.json",
    }
    for child in target_dir.rglob("*"):
        if child.is_file() and child.name in art_names:
            return True
    return False


def prune_stale_target_dirs(batch_folder: Path, expected_names: set[str]) -> list[str]:
    targets_root = batch_folder / "targets"
    if not targets_root.exists():
        return []
    kept: list[str] = []
    for target_dir in targets_root.iterdir():
        if not target_dir.is_dir() or target_dir.name in expected_names:
            continue
        if target_dir_contains_art(target_dir):
            kept.append(target_dir.name)
            continue
        shutil.rmtree(target_dir)
    return kept


def prune_stale_batch_dirs(stage4_root: Path, expected_names: set[str]) -> list[str]:
    kept: list[str] = []
    if not stage4_root.exists():
        return kept
    for batch_dir in stage4_root.glob("batch_*"):
        if not batch_dir.is_dir() or batch_dir.name in expected_names:
            continue
        if target_dir_contains_art(batch_dir):
            kept.append(batch_dir.name)
            continue
        shutil.rmtree(batch_dir)
    return kept


def build_batches(
    library_root: Path,
    runtime_root: Path,
    selected_batch: int | None = None,
) -> dict[str, Any]:
    queue = load_json(library_root / "generation_queue.json")
    reference_manifest = load_json(library_root / "reference_boards" / "manifest.json")
    stage4_root = library_root / STAGE4_DIR_NAME
    stage4_root.mkdir(parents=True, exist_ok=True)

    batches_by_number = {int(batch["batch"]): batch for batch in queue.get("batches", [])}
    targets_by_batch: dict[int, list[dict[str, Any]]] = {}
    for target in queue.get("targets", []):
        batch_number = int(target["batch"])
        if selected_batch is not None and batch_number != selected_batch:
            continue
        targets_by_batch.setdefault(batch_number, []).append(target)

    expected_batch_names = {
        f"batch_{batch_number:02d}_{slug(batches_by_number[batch_number]['name'])}"
        for batch_number in targets_by_batch
    }
    stale_batches_kept = prune_stale_batch_dirs(stage4_root, expected_batch_names)

    batch_summaries: list[dict[str, Any]] = []
    public_targets: list[dict[str, Any]] = []
    all_contracts: list[dict[str, Any]] = []
    for batch_number in sorted(targets_by_batch):
        batch = batches_by_number[batch_number]
        batch_folder = stage4_root / f"batch_{batch_number:02d}_{slug(batch['name'])}"
        batch_folder.mkdir(parents=True, exist_ok=True)
        expected_names = {
            f"{target['id']}__{target['outputFolderSuggestion']}"
            for target in targets_by_batch[batch_number]
        }
        contracts = [
            write_target_workspace(target, batch_folder, library_root, runtime_root)
            for target in targets_by_batch[batch_number]
        ]
        stale_kept = prune_stale_target_dirs(batch_folder, expected_names)
        all_contracts.extend(contracts)
        write_batch_readme(batch_folder, batch, contracts)
        batch_manifest = {
            "schemaVersion": 1,
            "stage": "stage-4-generation-batch",
            "generatedAt": utc_now(),
            "batch": batch,
            "targetCount": len(contracts),
            "targetCountMeaning": "strip targets; each strip contains multiple generated art pieces/frame slots",
            "artPieceTargetCount": sum(int(contract.get("artPieceCount") or contract.get("frameCount") or 0) for contract in contracts),
            "staleTargetFoldersKeptBecauseTheyContainArt": stale_kept,
            "targets": contracts,
        }
        write_json(batch_folder / "batch_manifest.json", batch_manifest)
        status_counts: dict[str, int] = {}
        for contract in contracts:
            status_counts[contract["status"]] = status_counts.get(contract["status"], 0) + 1
            public_targets.append(
                {
                    "targetId": contract["targetId"],
                    "batch": contract["batch"],
                    "batchName": contract["batchName"],
                    "priority": contract["priority"],
                    "targetKind": contract.get("targetKind", "matrix-atlas"),
                    "layerRole": contract.get("layerRole"),
                    "matrixKey": contract["matrixKey"],
                    "action": contract["action"],
                    "verticalTier": contract["verticalTier"],
                    "horizontalTier": contract["horizontalTier"],
                    "movementDirection": contract["movementDirection"],
                    "status": contract["status"],
                    "frameCount": contract["frameCount"],
                    "artPieceCount": contract["artPieceCount"],
                    "slotPixels": contract["slotPixels"],
                    "minimumSourceSlotPixels": contract.get("minimumSourceSlotPixels"),
                    "runtimeSlotPixels": contract.get("runtimeSlotPixels"),
                    "heightClass": contract["heightClass"],
                    "compiledAtlasFolder": contract["runtime"]["compiledAtlasFolder"],
                    "fallback": contract["existingRuntimeFallback"],
                }
            )
        batch_summaries.append(
            {
                "batch": batch_number,
                "name": batch["name"],
                "priority": batch["priority"],
                "targetCount": len(contracts),
                "artPieceTargetCount": sum(int(contract.get("artPieceCount") or contract.get("frameCount") or 0) for contract in contracts),
                "targetKind": batch.get("targetKind", "matrix-atlas"),
                "layerRole": batch.get("layerRole"),
                "folder": rel(batch_folder, library_root),
                "statusCounts": status_counts,
            }
        )

    status_counts: dict[str, int] = {}
    for contract in all_contracts:
        status_counts[contract["status"]] = status_counts.get(contract["status"], 0) + 1
    manifest = {
        "schemaVersion": 1,
        "stage": "stage-4-generation-batches",
        "generatedAt": utc_now(),
        "libraryRoot": str(library_root),
        "runtimeRoot": str(runtime_root),
        "selectedBatch": selected_batch,
        "sourceQueueGeneratedAt": queue.get("generatedAt"),
        "referenceBoardsGeneratedAt": reference_manifest.get("generatedAt"),
        "targetCount": len(all_contracts),
        "targetCountMeaning": "strip targets; each strip contains multiple generated art pieces/frame slots",
        "artPieceTargetCount": sum(int(contract.get("artPieceCount") or contract.get("frameCount") or 0) for contract in all_contracts),
        "minimumArtPieceGoal": queue.get("minimumArtPieceGoal", 400),
        "batchCount": len(batch_summaries),
        "statusCounts": status_counts,
        "staleBatchFoldersKeptBecauseTheyContainArt": stale_batches_kept,
        "batches": batch_summaries,
        "policy": "Generate complete strips into Stage 4 workspaces; compile only QA-approved atlases into public runtime assets.",
    }
    write_json(stage4_root / "manifest.json", manifest)

    public_plan = {
        "schemaVersion": 1,
        "stage": "stage-4-runtime-plan",
        "generatedAt": manifest["generatedAt"],
        "policy": "Browser-safe status only. Source art and prompts remain outside public assets.",
        "targetCount": len(public_targets),
        "targetCountMeaning": "strip targets; each strip contains multiple generated art pieces/frame slots",
        "artPieceTargetCount": sum(int(target.get("artPieceCount") or target.get("frameCount") or 0) for target in public_targets),
        "minimumArtPieceGoal": queue.get("minimumArtPieceGoal", 400),
        "statusCounts": status_counts,
        "targets": public_targets,
    }
    write_json(runtime_root / PUBLIC_PLAN_NAME, public_plan)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, default=DEFAULT_LIBRARY_ROOT)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--batch", type=int, default=None, help="Optional single generation batch number to materialize.")
    args = parser.parse_args()

    manifest = build_batches(args.library_root, args.runtime_root, args.batch)
    print(f"Built Stage 4 batches: {manifest['targetCount']} targets across {manifest['batchCount']} batch(es)")
    print(f"Workspace: {args.library_root / STAGE4_DIR_NAME}")
    print(f"Public runtime plan: {args.runtime_root / PUBLIC_PLAN_NAME}")
    for batch in manifest["batches"]:
        print(f"- batch {batch['batch']:02d} {batch['name']}: {batch['targetCount']} targets {batch['statusCounts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
