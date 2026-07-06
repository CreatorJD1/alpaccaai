"""Build 16-sector 360 QA contact sheets for Stage 4 Alpecca targets.

This is a source-art QA helper. It does not approve or ship assets. The goal is
to make the 360 coverage visible so flat billboard regressions are easier to
catch before Stage 5 runtime atlas promotion.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGE4_ROOT = REPO_ROOT / "data" / "alpecca_art_source" / "stage4_generation_batches"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "output" / "alpecca_stage4_360"
SECTOR_ORDER = tuple(f"s{i}" for i in range(16))
VERTICAL_ORDER = ("low", "eye", "high")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def status_and_image(target_dir: Path) -> tuple[str, Path | None]:
    candidates = (
        ("raw", target_dir / "incoming" / "raw_strip.png"),
        ("approved", target_dir / "approved" / "spritesheet.png"),
        ("seed", target_dir / "previews" / "seed_contact.jpg"),
        ("seed", target_dir / "incoming" / "seed_canvas.png"),
    )
    for status, path in candidates:
        if path.exists():
            return status, path
    return "missing", None


def target_dirs(stage4_root: Path) -> list[Path]:
    return sorted(path.parent for path in stage4_root.glob("batch_*/targets/*/target.json"))


def target_preview(path: Path | None, slot_px: int, cell_px: int) -> Image.Image:
    canvas = Image.new("RGBA", (cell_px, cell_px), (18, 22, 30, 255))
    if path is None:
        return canvas
    try:
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            frame_width = min(max(slot_px, 1), rgba.width)
            crop = rgba.crop((0, 0, frame_width, min(slot_px, rgba.height)))
            crop.thumbnail((cell_px - 18, cell_px - 32), Image.Resampling.LANCZOS)
            x = (cell_px - crop.width) // 2
            y = cell_px - crop.height - 18
            canvas.alpha_composite(crop, (x, y))
    except Exception:
        draw = ImageDraw.Draw(canvas)
        draw.line((18, 18, cell_px - 18, cell_px - 18), fill=(230, 90, 90, 255), width=4)
        draw.line((cell_px - 18, 18, 18, cell_px - 18), fill=(230, 90, 90, 255), width=4)
    return canvas


def make_sheet(
    action: str,
    records: list[dict[str, Any]],
    output_root: Path,
    cell_px: int,
) -> dict[str, Any]:
    by_vertical_sector: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        vertical = str(record["verticalTier"])
        sector = str(record["viewSector16"])
        by_vertical_sector[(vertical, sector)] = record

    verticals = [vertical for vertical in VERTICAL_ORDER if any((vertical, sector) in by_vertical_sector for sector in SECTOR_ORDER)]
    if not verticals:
        verticals = sorted({str(record["verticalTier"]) for record in records})

    label_h = 30
    left_w = 92
    header_h = 64
    width = left_w + len(SECTOR_ORDER) * cell_px
    height = header_h + len(verticals) * (cell_px + label_h)
    sheet = Image.new("RGB", (width, height), (12, 16, 24))
    draw = ImageDraw.Draw(sheet)
    title_font = load_font(20)
    label_font = load_font(13)
    tiny_font = load_font(10)

    draw.text((18, 14), f"Alpecca Stage 4 360 QA - {action}", fill=(236, 242, 255), font=title_font)
    draw.text((18, 40), "16 sectors per vertical tier. Use for body-volume continuity checks, not final approval.", fill=(158, 176, 210), font=label_font)

    for index, sector in enumerate(SECTOR_ORDER):
        x = left_w + index * cell_px + 6
        draw.text((x, header_h - 22), sector, fill=(184, 206, 244), font=label_font)

    coverage: list[dict[str, Any]] = []
    for row_index, vertical in enumerate(verticals):
        y = header_h + row_index * (cell_px + label_h)
        draw.text((14, y + 8), vertical, fill=(236, 242, 255), font=label_font)
        for sector_index, sector in enumerate(SECTOR_ORDER):
            x = left_w + sector_index * cell_px
            record = by_vertical_sector.get((vertical, sector))
            target_dir = Path(record["targetDir"]) if record else None
            status, image_path = status_and_image(target_dir) if target_dir else ("missing", None)
            slot_px = int(record.get("slotPixels", 4096)) if record else 4096
            cell = target_preview(image_path, slot_px, cell_px)
            sheet.paste(cell.convert("RGB"), (x, y))

            color = {
                "raw": (88, 232, 160),
                "approved": (108, 164, 255),
                "seed": (245, 190, 88),
                "missing": (232, 88, 88),
            }.get(status, (220, 220, 220))
            draw.rectangle((x, y, x + cell_px - 1, y + cell_px - 1), outline=color, width=2)
            draw.text((x + 6, y + 6), status.upper(), fill=color, font=tiny_font)

            coverage.append(
                {
                    "action": action,
                    "verticalTier": vertical,
                    "viewSector16": sector,
                    "status": status,
                    "targetId": record.get("targetId") if record else None,
                    "matrixKey": record.get("matrixKey") if record else None,
                    "targetDir": str(target_dir) if target_dir else None,
                    "imagePath": str(image_path) if image_path else None,
                }
            )

    output_root.mkdir(parents=True, exist_ok=True)
    out_path = output_root / f"{action}_16_sector_contact.jpg"
    sheet.save(out_path, quality=92, optimize=True)
    return {
        "action": action,
        "path": str(out_path),
        "verticalTiers": verticals,
        "sectorsPerTier": len(SECTOR_ORDER),
        "records": coverage,
        "statusCounts": {
            status: sum(1 for row in coverage if row["status"] == status)
            for status in ("approved", "raw", "seed", "missing")
        },
    }


def collect_records(stage4_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for target_dir in target_dirs(stage4_root):
        data = load_json(target_dir / "target.json")
        sector = data.get("viewSector16")
        if sector not in SECTOR_ORDER:
            continue
        data["targetDir"] = str(target_dir)
        records.append(data)
    return records


def write_readme(output_root: Path, sheets: list[dict[str, Any]]) -> None:
    lines = [
        "# Alpecca Stage 4 360 QA Contact Sheets",
        "",
        "These sheets verify the planned 16-sector turnaround coverage inspired by the external Drive references.",
        "They are QA previews for the source-art pipeline only. Yellow cells are seed/edit canvases; green/blue cells are generated or approved art once those files exist.",
        "",
        "Critical rejection rule: Alpecca must not remain a single flat billboard while the player circles her. Adjacent sectors must preserve adult body volume, hair mass, stocking length, boot size, and side/back silhouette continuity.",
        "",
    ]
    for sheet in sheets:
        lines.append(f"- `{Path(sheet['path']).name}`: {sheet['statusCounts']}")
    output_root.joinpath("README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage4-root", type=Path, default=DEFAULT_STAGE4_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--action", action="append", help="Limit to one or more actions")
    parser.add_argument("--cell-px", type=int, default=150)
    args = parser.parse_args()

    records = collect_records(args.stage4_root)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        action = str(record["action"])
        if args.action and action not in set(args.action):
            continue
        groups[action].append(record)

    sheets = [make_sheet(action, rows, args.output_root, args.cell_px) for action, rows in sorted(groups.items())]
    manifest = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "stage4Root": str(args.stage4_root),
        "outputRoot": str(args.output_root),
        "sectorCount": 16,
        "sectorOrder": SECTOR_ORDER,
        "sheets": sheets,
    }
    write_json(args.output_root / "stage4_360_coverage.json", manifest)
    write_readme(args.output_root, sheets)
    print(f"Wrote {len(sheets)} 360 contact sheets to {args.output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
