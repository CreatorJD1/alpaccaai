#!/usr/bin/env python
"""Build a single reference contact sheet for the v11 VRoid pass.

Inputs:
  data/alpecca_art_source/vrm_custom_assets/ac167033/*.jpg

Outputs:
  docs/ALPECCA_V11_REFERENCE_CONTACT_SHEET.jpg

This is an operator aid: one image for quick in-session reference matching while
working with the full VRoid toolset passbook.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "alpecca_art_source" / "vrm_custom_assets" / "ac167033"
OUTPUT_PATH = ROOT / "docs" / "ALPECCA_V11_REFERENCE_CONTACT_SHEET.jpg"

PANEL_SIZE = 1100  # px
PANEL_GAP = 24
MARGIN = 18
BG = (14, 14, 18)
TITLE_BG = (26, 28, 34)
TITLE = (239, 243, 245)

VIEW_LABELS = [
    "1) Front (0 deg)",
    "2) Front-right (45 deg)",
    "3) Side (90 deg)",
    "4) Back-right (~135 deg)",
    "5) Back (180 deg)",
]


def collect_frames() -> list[Path]:
    return sorted(
        [p for p in SOURCE_DIR.glob("*.jpg") if p.is_file()],
        key=lambda p: p.name,
    )


def fit_frame(img: Image.Image, side: int) -> Image.Image:
    return ImageOps.contain(img.convert("RGBA"), (side, side), method=Image.Resampling.LANCZOS)


def make_sheet() -> Image.Image:
    files = collect_frames()
    if not files:
        raise FileNotFoundError(f"No reference images found in {SOURCE_DIR}")

    # Single-row layout for quick side-by-side matching.
    cols = len(files)
    label_space = 72
    sheet_w = MARGIN * 2 + cols * PANEL_SIZE + max(cols - 1, 0) * PANEL_GAP
    sheet_h = MARGIN * 2 + PANEL_SIZE + label_space
    canvas = Image.new("RGB", (sheet_w, sheet_h), BG)
    draw = ImageDraw.Draw(canvas)

    try:
        font = ImageFont.truetype("arial.ttf", 30)
        small = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
        small = font

    draw.rounded_rectangle(
        [(0, 0), (sheet_w - 1, label_space + 10)],
        radius=6,
        fill=TITLE_BG,
    )
    title = "Alpecca v11 VRoid Reference Contact Sheet (AC167033)"
    draw.text((MARGIN, 16), title, fill=TITLE, font=font)
    hint = "Use this during side/full-side/back visual lock checks in the same VRoid session."
    draw.text((MARGIN, 50), hint, fill=TITLE, font=small)

    for idx, src in enumerate(files):
        x = MARGIN + idx * (PANEL_SIZE + PANEL_GAP)
        y = MARGIN + label_space
        with Image.open(src) as raw:
            thumb = fit_frame(raw, PANEL_SIZE)

        frame = Image.new("RGB", (PANEL_SIZE, PANEL_SIZE), "black")
        fx = (PANEL_SIZE - thumb.width) // 2
        fy = (PANEL_SIZE - thumb.height) // 2
        frame.paste(thumb.convert("RGB"), (fx, fy))

        canvas.paste(frame, (x, y))
        draw.rectangle([x, y, x + PANEL_SIZE - 1, y + PANEL_SIZE - 1], outline=(86, 94, 114), width=2)

        label = VIEW_LABELS[idx] if idx < len(VIEW_LABELS) else src.stem
        label_text = f"{label}  |  {src.name}"
        draw.text((x + 10, y + PANEL_SIZE + 8), label_text, fill=(218, 227, 236), font=small)

    return canvas


def main() -> int:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sheet = make_sheet()
    sheet.save(OUTPUT_PATH, quality=95, optimize=True)
    print(f"Reference contact sheet saved to: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
