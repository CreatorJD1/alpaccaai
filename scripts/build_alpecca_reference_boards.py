"""Build Stage 3 visual reference boards for Alpecca animation generation."""

from __future__ import annotations

import argparse
import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_ROOT = REPO_ROOT / "data" / "alpecca_art_source"
BOARD_DIR_NAME = "reference_boards"
HEIGHT_METERS = 1.704


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def image_for(slot: dict) -> Image.Image:
    path = Path(slot["sourcePath"])
    image = Image.open(path).convert("RGBA")
    return image


def fit_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, (255, 255, 255, 0))
    copy = image.copy()
    copy.thumbnail((size[0] - 24, size[1] - 56), Image.Resampling.LANCZOS)
    x = (size[0] - copy.width) // 2
    y = 20 + (size[1] - 56 - copy.height) // 2
    canvas.alpha_composite(copy, (x, y))
    return canvas


def draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, width: int, fill: str, font: ImageFont.ImageFont) -> None:
    lines: list[str] = []
    for paragraph in text.splitlines():
        lines.extend(textwrap.wrap(paragraph, width=width) or [""])
    draw.multiline_text(xy, "\n".join(lines), fill=fill, font=font, spacing=4)


def draw_card(
    canvas: Image.Image,
    slot: dict,
    label: str,
    xy: tuple[int, int],
    size: tuple[int, int],
    font: ImageFont.ImageFont,
    title_font: ImageFont.ImageFont,
) -> None:
    draw = ImageDraw.Draw(canvas)
    x, y = xy
    w, h = size
    draw.rounded_rectangle((x, y, x + w, y + h), radius=14, fill="#101821", outline="#32506a", width=2)
    draw.text((x + 16, y + 12), label, fill="#9de9ff", font=title_font)
    draw.text((x + 16, y + 40), f"{slot['sourceId']} · {slot['horizontalTier']} · {slot['approvalStatus']}", fill="#b8c7d7", font=font)
    try:
        art = fit_image(image_for(slot), (w, h - 92))
        canvas.alpha_composite(art, (x, y + 70))
    except Exception as exc:
        draw.text((x + 16, y + 84), f"missing: {exc}", fill="#ffb3b3", font=font)


def make_board(title: str, subtitle: str, cards: list[tuple[str, dict]], out_path: Path) -> None:
    font = ImageFont.load_default()
    title_font = ImageFont.load_default()
    card_w, card_h = 360, 520
    cols = min(4, max(1, len(cards)))
    rows = (len(cards) + cols - 1) // cols
    width = cols * card_w + (cols + 1) * 24
    height = 150 + rows * card_h + (rows + 1) * 24
    canvas = Image.new("RGBA", (width, height), "#08101a")
    draw = ImageDraw.Draw(canvas)
    draw.text((28, 22), title, fill="#f4fbff", font=title_font)
    draw_wrapped(draw, (28, 50), subtitle, 120, "#a9bfd6", font)
    for index, (label, slot) in enumerate(cards):
        col = index % cols
        row = index // cols
        x = 24 + col * (card_w + 24)
        y = 126 + row * (card_h + 24)
        draw_card(canvas, slot, label, (x, y), (card_w, card_h), font, title_font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, quality=95)


def make_scale_board(slots: dict, out_path: Path) -> None:
    font = ImageFont.load_default()
    title_font = ImageFont.load_default()
    canvas = Image.new("RGBA", (1200, 780), "#08101a")
    draw = ImageDraw.Draw(canvas)
    draw.text((32, 28), "Alpecca Scale And Anchor Lock", fill="#f4fbff", font=title_font)
    draw_wrapped(
        draw,
        (32, 58),
        "Use this board to keep her adult 5ft 7in standing height, bottom-center feet anchor, leg width, shoe size, hair volume, and halo placement stable across generated strips.",
        150,
        "#a9bfd6",
        font,
    )
    ruler_x = 1040
    top_y = 142
    bottom_y = 682
    draw.line((ruler_x, top_y, ruler_x, bottom_y), fill="#9de9ff", width=5)
    for tick in range(0, 7):
        y = bottom_y - tick * ((bottom_y - top_y) / 6)
        draw.line((ruler_x - 22, y, ruler_x + 22, y), fill="#9de9ff", width=3)
        draw.text((ruler_x + 34, y - 8), f"{tick} ft", fill="#d8f7ff", font=font)
    draw.text((ruler_x - 74, top_y - 34), "5ft 7in / 1.704m", fill="#ffd77a", font=title_font)
    draw.line((100, bottom_y, 980, bottom_y), fill="#ffd77a", width=4)
    draw.text((110, bottom_y + 16), "bottom-center foot anchor baseline", fill="#ffd77a", font=font)
    draw_card(canvas, slots["frontIdentity"], "standing front identity", (90, 136), (390, 520), font, title_font)
    draw_card(canvas, slots["sideIdentity"], "standing side identity", (520, 136), (390, 520), font, title_font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, quality=95)


def prompt_for_target(target: dict) -> str:
    refs = ", ".join(target.get("seedReferenceSlots") or [])
    gates = "\n".join(f"- {gate}" for gate in target.get("qualityGates", [])[:8])
    return f"""Generate one complete transparent animation strip for Alpecca.

Target:
- action: {target['action']}
- camera vertical tier: {target['verticalTier']}
- relative yaw tier: {target['horizontalTier']}
- movement direction: {target.get('movementDirection') or 'none'}
- frame count: {target['targetFrameCount']}
- frame slot: {target['targetSlotPixels']}px square
- output folder: {target['outputFolderSuggestion']}

Use these reference board slots: {refs}

Hard requirements:
{gates}

Do not create scenery, labels, UI, or poster art. Preserve Alpecca's identity,
adult proportions, outfit, hair volume, face language, and bottom-center foot
anchor. Do not bake halo, glow, floor shadow, or contact shadow into base body
art; those belong to separate overlay/effect targets. Generate the whole strip
as one coherent animation pass.
"""


def write_prompt_packs(queue: dict, out_dir: Path) -> list[str]:
    prompt_dir = out_dir / "prompt_packs"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    expected_names: set[str] = set()
    for target in queue.get("targets", []):
        if target.get("priority") != "critical":
            continue
        expected_names.add(f"{target['id']}__{target['outputFolderSuggestion']}.md")
        path = prompt_dir / f"{target['id']}__{target['outputFolderSuggestion']}.md"
        path.write_text(prompt_for_target(target), encoding="utf-8")
        written.append(str(path))
    for old_prompt in prompt_dir.glob("*.md"):
        if old_prompt.name not in expected_names:
            old_prompt.unlink()
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, default=DEFAULT_LIBRARY_ROOT)
    args = parser.parse_args()

    library_root = args.library_root
    board = load_json(library_root / "reference_board.json")
    queue = load_json(library_root / "generation_queue.json")
    slots = board["slots"]
    out_dir = library_root / BOARD_DIR_NAME

    make_board(
        "Alpecca Identity Turnaround Lock",
        "Primary identity references for generated 2D-in-3D matrix art. Use as identity lock, not as direct runtime frames.",
        [
            ("front", slots["frontIdentity"]),
            ("front diagonal", slots["diagonalIdentity"]),
            ("side", slots["sideIdentity"]),
            ("back", slots["backIdentity"]),
        ],
        out_dir / "identity_turnaround_lock.jpg",
    )
    make_board(
        "Alpecca Movement Direction References",
        "Facing-direction references for walk generation. These are directional guides only; new coherent walk strips must be generated.",
        [
            ("front/down", slots["movementFront"]),
            ("front diagonal/southeast", slots["movementFrontDiag"]),
            ("side/right-left", slots["movementSide"]),
            ("back diagonal/northeast", slots["movementBackDiag"]),
            ("back/up", slots["movementBack"]),
        ],
        out_dir / "movement_direction_reference.jpg",
    )
    make_board(
        "Alpecca Expression And Talking References",
        "Expression and mouth-shape references for profile speech, in-world talking, and emotional overlays.",
        [
            ("expression mouth sheet", slots["expressionMouth"]),
            ("talk mouth sheet", slots["talkMouth"]),
            ("rest reference", slots["restPose"]),
            ("front identity", slots["frontIdentity"]),
        ],
        out_dir / "expression_talk_reference.jpg",
    )
    make_scale_board(slots, out_dir / "scale_anchor_reference.jpg")

    prompts = write_prompt_packs(queue, out_dir)
    manifest = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "stage": "stage-3-reference-boards",
        "heightReferenceMeters": HEIGHT_METERS,
        "boards": [
            "identity_turnaround_lock.jpg",
            "movement_direction_reference.jpg",
            "expression_talk_reference.jpg",
            "scale_anchor_reference.jpg",
        ],
        "criticalPromptPacks": len(prompts),
        "promptPackFolder": "prompt_packs",
        "policy": "Use boards and prompt packs to generate new coherent strips; existing art remains reference material.",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Built {len(manifest['boards'])} reference boards -> {out_dir}")
    print(f"Built {len(prompts)} critical prompt packs -> {out_dir / 'prompt_packs'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
