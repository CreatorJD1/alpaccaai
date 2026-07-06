"""Prepare per-frame 4K tile prompts for an Alpecca Stage 4 target.

The ideal Stage 4 output is one coherent full strip, but many generators cannot
produce a 32768px-wide image. This helper creates a controlled segmented path:
generate each 4096x4096 frame tile, then stitch those tiles into the canonical
`incoming/raw_strip.png` for the normal QA/promotion gates.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_ROOT = REPO_ROOT / "data" / "alpecca_art_source"
DEFAULT_STAGE4_ROOT = DEFAULT_LIBRARY_ROOT / "stage4_generation_batches"
WALK_CYCLE_GUIDE_PATH = "data/alpecca_art_source/external_walk_cycle_references/walk_cycle_3d_pose_guide.jpg"
WALK_CYCLE_DOC_PATH = "docs/ALPECCA_STAGE4_WALK_CYCLE_POSE_LOCK.md"

WALK_16_PHASES = [
    {
        "phase": "contact A",
        "note": "front/support foot planted on the shared baseline, rear foot trailing, full adult standing height",
    },
    {
        "phase": "down A",
        "note": "weight settles onto the support foot, subtle pelvis drop, no body compression or thigh widening",
    },
    {
        "phase": "passing A",
        "note": "rear foot passes under the body, arms counter-swing naturally, head height stable",
    },
    {
        "phase": "up A",
        "note": "passing foot lifts forward, support heel rises, modest walking stride",
    },
    {
        "phase": "contact B",
        "note": "opposite foot plants on the same baseline, first foot trails, leg length unchanged",
    },
    {
        "phase": "down B",
        "note": "weight settles onto opposite support foot, same hip width and thigh silhouette",
    },
    {
        "phase": "passing B",
        "note": "first foot passes under the body, arms counter-swing opposite the earlier passing phase",
    },
    {
        "phase": "up B",
        "note": "first foot lifts forward, support heel rises, full 5ft 7in standing body class",
    },
    {
        "phase": "contact A in-between",
        "note": "contact A returns with slight in-between variation, not a duplicated frame 0",
    },
    {
        "phase": "down A in-between",
        "note": "weight settles with small cloth and hair follow-through, no height collapse",
    },
    {
        "phase": "passing A in-between",
        "note": "passing pose remains readable and distinct from frame 2",
    },
    {
        "phase": "up A in-between",
        "note": "lift phase has a clear foot arc and stable foot baseline",
    },
    {
        "phase": "contact B in-between",
        "note": "opposite contact returns with the same leg length, boot size, and stocking coverage",
    },
    {
        "phase": "down B in-between",
        "note": "weight settles naturally, no wide stance or thickened thighs",
    },
    {
        "phase": "passing B in-between",
        "note": "passing pose remains readable and distinct from frame 6",
    },
    {
        "phase": "up B return",
        "note": "lift phase anticipates frame 0 for a seamless loop without snapping",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def frame_pose_note(action: str, index: int, frame_count: int) -> str:
    if action == "idle":
        notes = [
            "neutral inhale, relaxed shoulders, eyes open",
            "slight breath lift, hair barely rising",
            "soft attentive look, tiny hand and sleeve settle",
            "blink preparation, posture unchanged",
            "calm blink or softened eyelids, same body height",
            "exhale settle, hair returns, feet fixed",
            "subtle breathing recovery, face calm",
            "returns to frame 0 posture for seamless loop",
        ]
        return notes[index % len(notes)]
    if action == "talk":
        return f"talking mouth/face variant {index + 1} of {frame_count}, body posture stable"
    if action == "listen":
        return f"listening micro-expression {index + 1} of {frame_count}, body posture stable"
    if action == "walk":
        phase = WALK_16_PHASES[index % len(WALK_16_PHASES)]
        return f"walk {phase['phase']}: {phase['note']}"
    return f"{action} frame {index + 1} of {frame_count}, coherent with adjacent frames"


def sector_angle_note(sector: str) -> str:
    try:
        index = int(str(sector).lower().removeprefix("s"))
    except Exception:
        index = 0
    index = max(0, min(15, index))
    degrees = index * 22.5
    if index in {0, 15, 1}:
        family = "front/front-quarter"
    elif index in {2, 3}:
        family = "front diagonal turning toward side"
    elif index in {4}:
        family = "true side view with visible body depth"
    elif index in {5, 6}:
        family = "back diagonal emerging from side"
    elif index in {7, 8, 9}:
        family = "back/back-quarter"
    elif index in {10, 11}:
        family = "opposite back diagonal"
    elif index in {12}:
        family = "opposite true side view with visible body depth"
    else:
        family = "opposite front diagonal"
    return f"sector {index} at approximately {degrees:.1f} degrees: {family}"


def build_prompt(target: dict[str, Any], frame_index: int, frame_count: int) -> str:
    action = str(target.get("action") or "idle")
    vertical = str(target.get("verticalTier") or "eye")
    sector = str(target.get("viewSector16") or target.get("horizontalTier") or "s0")
    pose_note = frame_pose_note(action, frame_index, frame_count)
    sector_note = sector_angle_note(sector)
    walk_requirements = ""
    if action == "walk":
        walk_requirements = f"""
Walk cycle requirements:
- Use `{WALK_CYCLE_GUIDE_PATH}` as the body-mechanics guide and `{WALK_CYCLE_DOC_PATH}` as the 16-frame phase contract.
- This frame must match the named walk phase above while staying coherent with the other 15 frames in the strip.
- The full strip must follow contact, down, passing, and up phases for both legs, then return to frame 0 seamlessly.
- Do not repeat adjacent or alternating leg positions; every frame needs a slight useful motion change.
- This is calm walking, not running, dashing, or posing: grounded contacts, modest stride, natural weight transfer.
- Keep feet on the shared baseline with no sliding, no random height changes, no thigh-width changes, and no compressed side silhouette.
"""
    return f"""Alpecca Stage 4 4K frame tile generation

Target: {target.get("targetId")} / {target.get("matrixKey")}
Frame: {frame_index + 1} of {frame_count}
Action: {action}
Camera vertical tier: {vertical}
16-sector view: {sector}
Frame size: 4096 x 4096
Output file: incoming/frame_tiles/frame_{frame_index:03d}.png

Generate this as one full-body transparent-background 4K frame tile. This tile
must match the same character, same scale, same bottom-center foot anchor, and
same design as every other tile in this target. Treat the other frame prompts
as one coherent animation, not independent redesigns.

Pose/motion note for this frame: {pose_note}.
360 sector note: {sector_note}.
{walk_requirements}

360 rotation requirements:
- Use `data/alpecca_art_source/external_360_references/external_360_reference_preview.jpg` only as a body-volume/turnaround reference.
- Match the Google Drive 360 reference folder: `https://drive.google.com/drive/folders/1TCaawZt7idE7ib-Kw8T-sq23z5cIXJmw`.
- Treat sector `s0` through `s15` as sixteen native camera angles around Alpecca's body. Each sector must have its own shoulder angle, hip angle, hair volume, leg spacing, boot angle, and back/side silhouette.
- This sector must read as a distinct camera angle around Alpecca, not the same flat billboard.
- Adjacent sectors must change shoulder angle, hip angle, hair mass, leg spacing, stocking visibility, boot angle, and back/side silhouette coherently.
- Side sectors must keep believable adult body depth; do not make her ultra-thin, paper-flat, or compressed.
- Do not mirror one front pose into every sector. Do not make a 5-view or 8-view approximation. Mirroring is allowed later in runtime only after native sector art exists and passes QA.

Design lock:
- adult female AI companion, 5ft 7in body class
- same face, blue eyes, long white-silver hair with pale lavender-blue lower accents
- one small blue X/bow hair clip on her left side
- oversized warm ivory/cream hoodie-jacket with pale blue trim
- white inner shirt, blue lanyard, Alpecca ID badge
- black high-waist shorts
- both legs fully covered by white full-length thigh-high stockings reaching the upper thigh under the shorts
- black right-leg thigh strap where visible
- chunky cream/white comfort boots with pale blue soles and blue details

Hard negatives:
- no outfit redesign
- no missing or shortened white thigh-high stockings
- no single bare leg, mismatched stocking length, or skin-colored stockings
- no bare legs replacing stockings
- no sneakers
- no baked halo, no baked floor shadow, no drop shadow, no glow smear
- no blue orbs, animal ears, round ear-like discs, floating balls, or invented ornaments
- no scene, no floor, no UI, no text, no watermark
- no cropping of hair, hands, feet, jacket, stockings, thigh strap, or boots
- no random body-height, thigh-width, leg-length, boot-size, or head-size changes
- no flat billboard rotation, no collapsed side silhouette, no duplicated back design

Technical requirements:
- transparent alpha PNG preferred
- if alpha is impossible, use one perfectly flat chroma-key background only
- keep the full body centered in the 4096x4096 slot
- feet anchored to the same bottom baseline across all tiles
- preserve enough padding for hair and boots
"""


def prepare_target(target_dir: Path) -> dict[str, Any]:
    target = load_json(target_dir / "target.json")
    frame_count = int(target["frameCount"])
    slot_px = int(target["slotPixels"])
    incoming = target_dir / "incoming"
    tile_dir = incoming / "frame_tiles"
    prompt_dir = tile_dir / "prompts"
    tile_dir.mkdir(parents=True, exist_ok=True)
    prompt_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    for index in range(frame_count):
        prompt_path = prompt_dir / f"frame_{index:03d}.md"
        tile_path = tile_dir / f"frame_{index:03d}.png"
        prompt = build_prompt(target, index, frame_count)
        prompt_path.write_text(prompt, encoding="utf-8")
        frames.append(
            {
                "index": index,
                "prompt": str(prompt_path),
                "expectedTile": str(tile_path),
                "size": [slot_px, slot_px],
                "poseNote": frame_pose_note(str(target.get("action") or ""), index, frame_count),
            }
        )
    plan = {
        "schemaVersion": 1,
        "stage": "stage-4-tile-generation-plan",
        "generatedAt": utc_now(),
        "targetId": target.get("targetId"),
        "matrixKey": target.get("matrixKey"),
        "action": target.get("action"),
        "verticalTier": target.get("verticalTier"),
        "horizontalTier": target.get("horizontalTier"),
        "viewSector16": target.get("viewSector16"),
        "frameCount": frame_count,
        "slotPixels": slot_px,
        "expectedStripPixels": target.get("expectedStripPixels"),
        "tileDirectory": str(tile_dir),
        "rawStripOutput": str(incoming / "raw_strip.png"),
        "frames": frames,
        "policy": "Frame tiles are source-generation inputs. Stitching creates incoming/raw_strip.png only after every tile matches the 4096x4096 contract.",
    }
    write_json(incoming / "tile_generation_plan.json", plan)
    return plan


def iter_target_dirs(stage4_root: Path, batch: int | None) -> list[Path]:
    pattern = f"batch_{batch:02d}_*/targets/*/target.json" if batch is not None else "batch_*/targets/*/target.json"
    return [path.parent for path in sorted(stage4_root.glob(pattern))]


def prepare_batch(stage4_root: Path, batch: int | None) -> dict[str, Any]:
    target_dirs = iter_target_dirs(stage4_root, batch)
    plans = [prepare_target(target_dir) for target_dir in target_dirs]
    total_frames = sum(int(plan["frameCount"]) for plan in plans)
    report = {
        "schemaVersion": 1,
        "stage": "stage-4-batch-tile-generation-plan",
        "generatedAt": utc_now(),
        "batch": batch,
        "targetCount": len(plans),
        "frameTilePromptCount": total_frames,
        "targets": [
            {
                "targetId": plan.get("targetId"),
                "matrixKey": plan.get("matrixKey"),
                "frameCount": plan.get("frameCount"),
                "tileDirectory": plan.get("tileDirectory"),
                "rawStripOutput": plan.get("rawStripOutput"),
            }
            for plan in plans
        ],
        "policy": "Batch plan only prepares 4K frame-tile prompts; it does not generate, approve, or promote art.",
    }
    if batch is not None:
        batch_dirs = sorted(stage4_root.glob(f"batch_{batch:02d}_*"))
        out_dir = batch_dirs[0] if batch_dirs else stage4_root
    else:
        out_dir = stage4_root
    write_json(out_dir / "tile_generation_index.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--target-dir", type=Path)
    group.add_argument("--batch", type=int, help="Prepare all targets in a Stage 4 batch.")
    parser.add_argument("--stage4-root", type=Path, default=DEFAULT_STAGE4_ROOT)
    args = parser.parse_args()
    if args.target_dir:
        plan = prepare_target(args.target_dir)
        print(json.dumps({"targetId": plan["targetId"], "matrixKey": plan["matrixKey"], "frameCount": plan["frameCount"], "tileDirectory": plan["tileDirectory"]}, indent=2))
    else:
        report = prepare_batch(args.stage4_root, args.batch)
        print(json.dumps({"batch": report["batch"], "targetCount": report["targetCount"], "frameTilePromptCount": report["frameTilePromptCount"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
