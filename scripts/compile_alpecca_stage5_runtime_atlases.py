"""Compile QA-approved Stage 4 Alpecca strips into runtime atlas folders.

Stage 5 is a promotion gate, not an art generator. It scans Stage 4 target
workspaces for `approved/spritesheet.png`, validates the frame contract, writes
runtime atlas metadata, and only copies approved assets into `public/assets`.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE4_ROOT = REPO_ROOT / "data" / "alpecca_art_source" / "stage4_generation_batches"
DEFAULT_RUNTIME_ROOT = REPO_ROOT / "apps" / "house-hq" / "public" / "assets" / "alpecca-optimized"
DEFAULT_REPORT = REPO_ROOT / "data" / "alpecca_art_source" / "stage5_compile_report.json"
DEFAULT_MATRIX_MANIFEST = DEFAULT_RUNTIME_ROOT / "runtime_matrix_manifest.json"
DEFAULT_LAYER_MANIFEST = DEFAULT_RUNTIME_ROOT / "runtime_layer_manifest.json"
MATRIX_ACTIONS = {"idle", "listen", "talk", "walk", "wave", "inspect", "careful", "rest", "sleep"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def iter_target_contracts(stage4_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    contracts: list[tuple[Path, dict[str, Any]]] = []
    for target_json in sorted(stage4_root.glob("batch_*/targets/*/target.json")):
      try:
          contracts.append((target_json.parent, load_json(target_json)))
      except Exception:
          continue
    return contracts


def build_atlas(frame_count: int, slot_px: int) -> dict[str, Any]:
    frames = {
        str(index): {"x": index * slot_px, "y": 0, "w": slot_px, "h": slot_px, "duration": 1}
        for index in range(frame_count)
    }
    return {
        "frames": frames,
        "meta": {
            "size": {"w": frame_count * slot_px, "h": slot_px},
            "frame_size": {"w": slot_px, "h": slot_px},
            "stage": "stage-5-approved-runtime",
            "optimized_for_game": True,
        },
    }


def alpha_bounds_for_frames(image: Image.Image, frame_count: int, slot_px: int) -> tuple[dict[str, int], list[dict[str, int]]]:
    rgba = image.convert("RGBA")
    union_left = union_top = 10**9
    union_right = union_bottom = -1
    per_frame: list[dict[str, int]] = []

    for index in range(frame_count):
        alpha = rgba.crop((index * slot_px, 0, (index + 1) * slot_px, slot_px)).getchannel("A")
        bounds = alpha.getbbox()
        if not bounds:
            frame_bounds = {"x": 0, "y": 0, "w": 0, "h": 0, "bottom": 0}
        else:
            left, top, right, bottom = bounds
            frame_bounds = {"x": left, "y": top, "w": right - left, "h": bottom - top, "bottom": bottom}
            union_left = min(union_left, left)
            union_top = min(union_top, top)
            union_right = max(union_right, right)
            union_bottom = max(union_bottom, bottom)
        per_frame.append(frame_bounds)

    if union_right < union_left or union_bottom < union_top:
        return {"x": 0, "y": 0, "w": slot_px, "h": slot_px}, per_frame
    return {
        "x": union_left,
        "y": union_top,
        "w": union_right - union_left,
        "h": union_bottom - union_top,
    }, per_frame


def variance(values: list[float]) -> float:
    if not values:
        return 0.0
    avg = sum(values) / len(values)
    return sum((value - avg) ** 2 for value in values) / len(values)


def lower_body_signature(frame: Image.Image, size: int = 48) -> list[int]:
    rgba = frame.convert("RGBA")
    alpha = rgba.getchannel("A")
    bounds = alpha.getbbox()
    if not bounds:
        return []
    left, top, right, bottom = bounds
    lower_top = top + int((bottom - top) * 0.48)
    crop = rgba.crop((left, lower_top, right, bottom)).resize((size, size), Image.Resampling.BILINEAR)
    gray = crop.convert("L")
    a = crop.getchannel("A")
    values: list[int] = []
    for y in range(size):
        for x in range(size):
            alpha_value = a.getpixel((x, y))
            if alpha_value <= 16:
                values.append(0)
            else:
                values.append(1 if gray.getpixel((x, y)) > 118 else 2)
    return values


def signature_similarity(a: list[int], b: list[int]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    matches = sum(1 for av, bv in zip(a, b) if av == bv)
    return matches / len(a)


def walk_duplicate_pose_report(image: Image.Image, contract: dict[str, Any]) -> dict[str, Any]:
    if str(contract.get("action") or "") != "walk":
        return {"enabled": False, "duplicatePosePairs": [], "warning": ""}
    frame_count = int(contract["frameCount"])
    slot_px = int(contract["slotPixels"])
    if frame_count < 4:
        return {"enabled": True, "duplicatePosePairs": [], "warning": ""}
    frames = [image.crop((index * slot_px, 0, (index + 1) * slot_px, slot_px)) for index in range(frame_count)]
    signatures = [lower_body_signature(frame) for frame in frames]
    duplicate_pairs: list[dict[str, Any]] = []
    for index in range(len(signatures)):
        for offset in (1, 2):
            other = (index + offset) % len(signatures)
            similarity = signature_similarity(signatures[index], signatures[other])
            if similarity >= 0.925:
                duplicate_pairs.append(
                    {
                        "frameA": index,
                        "frameB": other,
                        "offset": offset,
                        "lowerBodySimilarity": round(similarity, 4),
                    }
                )
    return {
        "enabled": True,
        "duplicatePosePairs": duplicate_pairs,
        "duplicatePosePairCount": len(duplicate_pairs),
        "warning": "duplicate lower-body walk poses detected" if duplicate_pairs else "",
    }


def visual_metadata(image: Image.Image, contract: dict[str, Any]) -> dict[str, Any]:
    frame_count = int(contract["frameCount"])
    slot_px = int(contract["slotPixels"])
    alpha_bounds, per_frame = alpha_bounds_for_frames(image, frame_count, slot_px)
    bottom_values = [frame["bottom"] for frame in per_frame if frame["bottom"]]
    width_values = [frame["w"] for frame in per_frame if frame["w"]]
    height_values = [frame["h"] for frame in per_frame if frame["h"]]
    target_px = 338 if contract.get("heightClass") == "adult-standing-5ft7" else max(210, int(alpha_bounds["h"] * 0.92))
    visual_scale = target_px / max(1, alpha_bounds["h"])
    sprite_y = 0.5 + ((slot_px - alpha_bounds["y"] - alpha_bounds["h"]) / slot_px)
    return {
        "frameSize": slot_px,
        "alphaBounds": alpha_bounds,
        "visualScale": round(visual_scale, 6),
        "spriteY": round(sprite_y, 6),
        "heightClass": contract.get("heightClass"),
        "stage": "stage-5-approved-runtime",
        "qa": {
            "frameCount": frame_count,
            "footBottomVariance": round(variance([float(v) for v in bottom_values]), 6),
            "bodyWidthVariance": round(variance([float(v) for v in width_values]), 6),
            "bodyHeightVariance": round(variance([float(v) for v in height_values]), 6),
            "emptyFrameCount": sum(1 for frame in per_frame if not frame["w"] or not frame["h"]),
            "walkDuplicatePoseReport": walk_duplicate_pose_report(image, contract),
        },
    }


def runtime_layer_plan(action: str) -> dict[str, Any]:
    roles = ["base-body", "contact-shadow", "depth-proxy", "floor-reflection"]
    if action in {"talk", "listen"}:
        roles.insert(1, "expression-overlay")
        roles.insert(2, "mouth-eye-overlay")
    return {
        "roles": roles,
        "expressionOverlay": "expression-overlay" in roles,
        "mouthEyeOverlay": "mouth-eye-overlay" in roles,
        "contactShadow": True,
        "depthProxy": True,
        "floorReflection": True,
        "transitionSeconds": 0.065,
    }


def runtime_contact_frames(action: str, frame_count: int) -> list[int]:
    if action != "walk" or frame_count <= 0:
        return []
    stride = max(1, frame_count // 4)
    return sorted({0, stride, stride * 2, stride * 3})


def runtime_state_for_action(action: str) -> str:
    return {
        "idle": "idleDown",
        "listen": "idleDown",
        "talk": "talkDown",
        "walk": "walkDown",
        "wave": "waveDown",
        "inspect": "point",
        "careful": "crouch",
        "rest": "sit",
        "sleep": "sleepDown",
        "wake": "sit",
        "surprised": "idleDown",
        "shy": "idleDown",
        "curious": "idleDown",
        "worried": "idleDown",
        "amused": "idleDown",
        "thinking": "idleDown",
    }.get(action, "idleDown")


def runtime_record(contract: dict[str, Any], visual: dict[str, Any]) -> dict[str, Any]:
    action = str(contract["action"])
    frame_count = int(contract["frameCount"])
    folder = str(contract.get("runtime", {}).get("compiledAtlasFolder"))
    return {
        "key": contract.get("matrixKey"),
        "action": action,
        "verticalTier": contract.get("verticalTier"),
        "horizontalTier": contract.get("horizontalTier"),
        "mirrorPolicy": "use-view-matrix-flipX-for-negative-relative-yaw",
        "state": runtime_state_for_action(action),
        "folder": folder,
        "frameCount": frame_count,
        "sourceFamily": "stage5-matrix",
        "approvalStatus": "approved",
        "heightClass": "standing" if contract.get("heightClass") == "adult-standing-5ft7" else "pose",
        "visualScale": visual.get("visualScale"),
        "spriteY": visual.get("spriteY"),
        "footAnchor": "bottom-center",
        "contactFrameIndexes": runtime_contact_frames(action, frame_count),
        "layerPlan": runtime_layer_plan(action),
        "depthProxy": "compiled-alpha-silhouette-plane",
        "notes": "Stage 5 approved matrix atlas. Browser-safe compiled runtime asset.",
    }


def runtime_layer_record(contract: dict[str, Any], visual: dict[str, Any]) -> dict[str, Any]:
    action = str(contract["action"])
    frame_count = int(contract["frameCount"])
    folder = str(contract.get("runtime", {}).get("compiledAtlasFolder"))
    return {
        "key": contract.get("matrixKey"),
        "action": action,
        "verticalTier": contract.get("verticalTier"),
        "horizontalTier": contract.get("horizontalTier"),
        "layerRole": contract.get("layerRole") or "expression-overlay",
        "folder": folder,
        "frameCount": frame_count,
        "sourceFamily": "stage5-layer",
        "approvalStatus": "approved",
        "heightClass": "overlay",
        "visualScale": visual.get("visualScale"),
        "spriteY": visual.get("spriteY"),
        "footAnchor": "face-or-body-local",
        "layerPlan": runtime_layer_plan(action),
        "depthProxy": "no-depth-proxy-overlay-layer",
        "notes": "Stage 5 approved layered overlay atlas. Loaded by future layered character runtime.",
    }


def merge_runtime_manifest(manifest_path: Path, compiled_records: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        manifest = load_json(manifest_path)
    except Exception:
        manifest = {
            "schemaVersion": 1,
            "assetRoot": "/assets/alpecca-optimized",
            "runtimePolicy": "Browser loads compiled atlas folders only; source library stays outside public assets.",
            "records": [],
        }
    by_key = {
        str(record.get("key")): record
        for record in manifest.get("records", [])
        if isinstance(record, dict) and record.get("key")
    }
    for record in compiled_records:
        key = str(record.get("key"))
        if key:
            by_key[key] = record
    merged = {
        **manifest,
        "schemaVersion": 2,
        "generatedAt": utc_now(),
        "stage": "stage-6-layered-runtime-matrix",
        "assetRoot": "/assets/alpecca-optimized",
        "runtimePolicy": "Browser loads compiled atlas folders only; source library stays outside public assets.",
        "compiledRecordCount": len(compiled_records),
        "records": list(by_key.values()),
    }
    write_json(manifest_path, merged)
    return merged


def merge_layer_manifest(manifest_path: Path, compiled_records: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        manifest = load_json(manifest_path)
    except Exception:
        manifest = {
            "schemaVersion": 1,
            "assetRoot": "/assets/alpecca-optimized",
            "runtimePolicy": "Browser loads compiled overlay atlas folders only; source library stays outside public assets.",
            "records": [],
        }
    by_key = {
        str(record.get("key")): record
        for record in manifest.get("records", [])
        if isinstance(record, dict) and record.get("key")
    }
    for record in compiled_records:
        key = str(record.get("key"))
        if key:
            by_key[key] = record
    merged = {
        **manifest,
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "stage": "stage-6-layered-runtime-overlays",
        "assetRoot": "/assets/alpecca-optimized",
        "runtimePolicy": "Browser loads compiled overlay atlas folders only; source library stays outside public assets.",
        "compiledRecordCount": len(compiled_records),
        "records": list(by_key.values()),
    }
    write_json(manifest_path, merged)
    return merged


def validate_strip(path: Path, contract: dict[str, Any]) -> tuple[bool, str, Image.Image | None]:
    frame_count = int(contract["frameCount"])
    slot_px = int(contract["slotPixels"])
    expected = (frame_count * slot_px, slot_px)
    if not path.exists():
        return False, "approved/spritesheet.png missing", None
    try:
        image = Image.open(path).convert("RGBA")
        image.load()
    except Exception as exc:
        return False, f"could not open spritesheet: {exc}", None
    if image.size != expected:
        return False, f"spritesheet size {image.size} does not match expected {expected}", image
    return True, "ready", image


def resize_strip_slots(image: Image.Image, frame_count: int, source_slot_px: int, runtime_slot_px: int) -> Image.Image:
    if runtime_slot_px == source_slot_px:
        return image
    out = Image.new("RGBA", (frame_count * runtime_slot_px, runtime_slot_px), (0, 0, 0, 0))
    for index in range(frame_count):
        frame = image.crop((index * source_slot_px, 0, (index + 1) * source_slot_px, source_slot_px))
        resized = frame.resize((runtime_slot_px, runtime_slot_px), Image.Resampling.LANCZOS)
        out.alpha_composite(resized, (index * runtime_slot_px, 0))
    return out


def compile_target(target_dir: Path, contract: dict[str, Any], runtime_root: Path, apply: bool) -> dict[str, Any]:
    approved_dir = target_dir / "approved"
    sheet_path = approved_dir / "spritesheet.png"
    ok, reason, image = validate_strip(sheet_path, contract)
    result = {
        "targetId": contract.get("targetId"),
        "matrixKey": contract.get("matrixKey"),
        "compiledAtlasFolder": contract.get("runtime", {}).get("compiledAtlasFolder"),
        "status": "ready" if ok else "skipped",
        "reason": reason,
        "applied": False,
    }
    if not ok or image is None:
        return result

    frame_count = int(contract["frameCount"])
    source_slot_px = int(contract["slotPixels"])
    runtime_slot_px = int(contract.get("runtimeSlotPixels") or source_slot_px)
    runtime_image = resize_strip_slots(image, frame_count, source_slot_px, runtime_slot_px)
    runtime_contract = {**contract, "slotPixels": runtime_slot_px}
    atlas = build_atlas(frame_count, runtime_slot_px)
    visual = visual_metadata(runtime_image, runtime_contract)
    metadata = {
        "schemaVersion": 1,
        "stage": "stage-5-approved-runtime",
        "generatedAt": utc_now(),
        "targetId": contract.get("targetId"),
        "matrixKey": contract.get("matrixKey"),
        "action": contract.get("action"),
        "verticalTier": contract.get("verticalTier"),
        "horizontalTier": contract.get("horizontalTier"),
        "movementDirection": contract.get("movementDirection"),
        "frameCount": frame_count,
        "sourceSlotPixels": source_slot_px,
        "runtimeSlotPixels": runtime_slot_px,
        "heightClass": contract.get("heightClass"),
        "sourceWorkspace": str(target_dir),
        "approvalStatus": "approved",
        "footAnchor": "bottom-center",
        "contactFrameIndexes": runtime_contact_frames(str(contract.get("action")), frame_count),
        "layerPlan": runtime_layer_plan(str(contract.get("action"))),
        "depthProxy": "compiled-alpha-silhouette-plane",
    }
    is_matrix_target = contract.get("targetKind", "matrix-atlas") == "matrix-atlas" and str(contract.get("action")) in MATRIX_ACTIONS
    record = runtime_record(contract, visual) if is_matrix_target else runtime_layer_record(contract, visual)

    if apply:
        runtime_folder = runtime_root / str(result["compiledAtlasFolder"])
        runtime_folder.mkdir(parents=True, exist_ok=True)
        runtime_image.save(runtime_folder / "spritesheet.png")
        runtime_image.save(runtime_folder / "spritesheet.webp", "WEBP", lossless=True, quality=100, method=0)
        write_json(runtime_folder / "atlas.json", atlas)
        write_json(runtime_folder / "visual.json", visual)
        write_json(runtime_folder / "matrix_metadata.json", metadata)
        result["applied"] = True
        result["status"] = "compiled"
        result["runtimeFolder"] = str(runtime_folder)
        result["runtimeRecord" if is_matrix_target else "runtimeLayerRecord"] = record
    else:
        result["status"] = "ready-dry-run"
        result["runtimeRecordPreview" if is_matrix_target else "runtimeLayerRecordPreview"] = record
    result["visualQa"] = visual["qa"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage4-root", type=Path, default=DEFAULT_STAGE4_ROOT)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--matrix-manifest", type=Path, default=DEFAULT_MATRIX_MANIFEST)
    parser.add_argument("--layer-manifest", type=Path, default=DEFAULT_LAYER_MANIFEST)
    parser.add_argument("--apply", action="store_true", help="Copy ready approved strips into runtime asset folders.")
    args = parser.parse_args()

    contracts = iter_target_contracts(args.stage4_root)
    results = [compile_target(target_dir, contract, args.runtime_root, args.apply) for target_dir, contract in contracts]
    compiled_records = [
        result["runtimeRecord"]
        for result in results
        if result.get("applied") and isinstance(result.get("runtimeRecord"), dict)
    ]
    compiled_layer_records = [
        result["runtimeLayerRecord"]
        for result in results
        if result.get("applied") and isinstance(result.get("runtimeLayerRecord"), dict)
    ]
    runtime_manifest = merge_runtime_manifest(args.matrix_manifest, compiled_records) if args.apply else None
    layer_manifest = merge_layer_manifest(args.layer_manifest, compiled_layer_records) if args.apply else None
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    report = {
        "schemaVersion": 1,
        "stage": "stage-5-approved-runtime-compile",
        "generatedAt": utc_now(),
        "apply": args.apply,
        "targetCount": len(results),
        "statusCounts": counts,
        "runtimeManifest": str(args.matrix_manifest),
        "runtimeLayerManifest": str(args.layer_manifest),
        "compiledRuntimeRecordCount": len(compiled_records),
        "compiledRuntimeLayerRecordCount": len(compiled_layer_records),
        "runtimeManifestRecordCount": len(runtime_manifest.get("records", [])) if runtime_manifest else None,
        "runtimeLayerManifestRecordCount": len(layer_manifest.get("records", [])) if layer_manifest else None,
        "results": results,
    }
    write_json(args.report, report)
    print(f"Stage 5 compile scan: {len(results)} target(s) -> {args.report}")
    print(f"Status: {counts}")
    if not args.apply:
        print("Dry run only. Add --apply after generated strips pass QA.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
