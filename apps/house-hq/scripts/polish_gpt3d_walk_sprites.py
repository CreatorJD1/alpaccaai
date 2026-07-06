from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw


DEFAULT_ASSET_ROOT = Path("public/assets/alpecca-optimized")
DEFAULT_PREVIEW_OUT = Path("output/alpecca-generation/gpt3d-movement")
FRAME_SIZE = 512
PREVIEW_FRAME_SIZE = 128
CLOSEUP_FRAME_SIZE = 192


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polish generated GPT3D Alpecca walk atlases without resizing or lowering art quality.")
    parser.add_argument("--asset-root", type=Path, default=DEFAULT_ASSET_ROOT)
    parser.add_argument("--preview-out", type=Path, default=DEFAULT_PREVIEW_OUT)
    parser.add_argument("--folders", nargs="*", default=None, help="Specific gpt3d walk folders to polish.")
    parser.add_argument("--metadata-only", action="store_true", help="Only refresh visual.json proportion metadata and reports; do not rewrite sprite images.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def sorted_frame_items(atlas: dict) -> list[tuple[str, dict]]:
    frames = atlas.get("frames", {})

    def key(item: tuple[str, dict]) -> tuple[int, str]:
        try:
            return (int(item[0]), item[0])
        except ValueError:
            return (10**9, item[0])

    return sorted(frames.items(), key=key)


def alpha_bounds(image: Image.Image, atlas: dict) -> dict[str, int]:
    left = top = 10**9
    right = bottom = -1
    rgba = image.convert("RGBA")
    for _, frame in sorted_frame_items(atlas):
        x, y, w, h = (int(frame[key]) for key in ("x", "y", "w", "h"))
        alpha = rgba.crop((x, y, x + w, y + h)).getchannel("A").point(lambda value: 255 if value > 4 else 0)
        bounds = alpha.getbbox()
        if not bounds:
            continue
        bx1, by1, bx2, by2 = bounds
        left = min(left, bx1)
        top = min(top, by1)
        right = max(right, bx2)
        bottom = max(bottom, by2)
    if right < left or bottom < top:
        return {"x": 0, "y": 0, "w": FRAME_SIZE, "h": FRAME_SIZE}
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def frame_alpha_bounds(image: Image.Image, frame: dict) -> dict[str, int]:
    x, y, w, h = (int(frame[key]) for key in ("x", "y", "w", "h"))
    alpha = image.crop((x, y, x + w, y + h)).getchannel("A").point(lambda value: 255 if value > 4 else 0)
    bounds = alpha.getbbox()
    if not bounds:
        return {"x": 0, "y": 0, "w": 0, "h": 0}
    bx1, by1, bx2, by2 = bounds
    return {"x": bx1, "y": by1, "w": bx2 - bx1, "h": by2 - by1}


def alpha_band_width(alpha: Image.Image, y1: int, y2: int) -> int:
    band = alpha.crop((0, max(0, y1), alpha.width, min(alpha.height, y2))).getbbox()
    if not band:
        return 0
    return int(band[2] - band[0])


def frame_proportion_metrics(image: Image.Image, frame: dict) -> dict:
    x, y, w, h = (int(frame[key]) for key in ("x", "y", "w", "h"))
    crop = image.crop((x, y, x + w, y + h))
    alpha = crop.getchannel("A").point(lambda value: 255 if value > 4 else 0)
    bounds = frame_alpha_bounds(image, frame)
    torso_width = alpha_band_width(alpha, int(h * 0.28), int(h * 0.56))
    lower_width = alpha_band_width(alpha, int(h * 0.58), int(h * 0.88))
    foot_band_width = alpha_band_width(alpha, int(h * 0.84), int(h * 0.98))
    ratio_base = max(1, bounds["w"])
    return {
        "bounds": bounds,
        "torsoWidth": torso_width,
        "lowerBodyWidth": lower_width,
        "lowerBodyWidthRatio": round(lower_width / ratio_base, 4),
        "footBandWidth": foot_band_width,
        "footBottom": bounds["y"] + bounds["h"],
    }


def proportion_report(image: Image.Image, atlas: dict) -> dict:
    metrics = [frame_proportion_metrics(image, frame) for _, frame in sorted_frame_items(atlas)]
    body_widths = [item["bounds"]["w"] for item in metrics if item["bounds"]["w"] > 0]
    body_heights = [item["bounds"]["h"] for item in metrics if item["bounds"]["h"] > 0]
    lower_widths = [item["lowerBodyWidth"] for item in metrics if item["lowerBodyWidth"] > 0]
    lower_ratios = [item["lowerBodyWidthRatio"] for item in metrics if item["lowerBodyWidth"] > 0]
    foot_bottoms = [item["footBottom"] for item in metrics if item["footBottom"] > 0]

    def spread(values: list[float]) -> float:
        return max(values) - min(values) if values else 0

    lower_width_variance = spread(lower_widths)
    lower_ratio_variance = spread(lower_ratios)
    body_height_variance = spread(body_heights)
    return {
        "frameCount": len(metrics),
        "maxFrameWidth": max(body_widths) if body_widths else 0,
        "minFrameWidth": min(body_widths) if body_widths else 0,
        "bodyWidthVariance": round(spread(body_widths), 3),
        "bodyHeightVariance": round(body_height_variance, 3),
        "lowerBodyWidthMin": min(lower_widths) if lower_widths else 0,
        "lowerBodyWidthMax": max(lower_widths) if lower_widths else 0,
        "lowerBodyWidthVariance": round(lower_width_variance, 3),
        "lowerBodyWidthRatio": round(sum(lower_ratios) / len(lower_ratios), 4) if lower_ratios else 0,
        "lowerBodyWidthRatioVariance": round(lower_ratio_variance, 4),
        "footBottomVariance": round(spread(foot_bottoms), 3),
        "flagged": lower_width_variance > 44 or lower_ratio_variance > 0.22 or body_height_variance > 18,
        "frames": metrics,
    }


def polish_pixel(r: int, g: int, b: int, a: int) -> tuple[int, int, int, int]:
    if a <= 2:
        return (0, 0, 0, 0)
    if a >= 245:
        return (r, g, b, a)

    edge = 1 - a / 255
    nr, ng, nb = float(r), float(g), float(b)

    cyan_excess = max(0.0, min(ng, nb) - nr - 10)
    if cyan_excess > 0:
        amount = cyan_excess * (0.62 + edge * 0.34)
        ng -= amount
        nb -= amount * 0.86
        nr += amount * 0.12

    green_excess = max(0.0, ng - max(nr, nb) - 8)
    if green_excess > 0:
        ng -= green_excess * (0.7 + edge * 0.25)

    # Very faint pixels are usually chroma-key residue. Keep soft outline color, but
    # stop it from glowing against the 3D floor.
    if a < 42:
        luma = nr * 0.299 + ng * 0.587 + nb * 0.114
        nr = nr * 0.55 + luma * 0.45
        ng = ng * 0.55 + luma * 0.45
        nb = nb * 0.55 + luma * 0.45

    return (
        max(0, min(255, round(nr))),
        max(0, min(255, round(ng))),
        max(0, min(255, round(nb))),
        a,
    )


def polish_image(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    for y in range(height):
        for x in range(width):
            pixels[x, y] = polish_pixel(*pixels[x, y])
    return rgba


def checker(width: int, height: int, cell: int = 16) -> Image.Image:
    image = Image.new("RGBA", (width, height), "#f2f4f7")
    draw = ImageDraw.Draw(image)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill="#dfe6ee")
    return image


def render_preview(folder: Path, image: Image.Image, atlas: dict, out: Path, frame_size: int) -> None:
    items = sorted_frame_items(atlas)
    columns = 4
    rows = (len(items) + columns - 1) // columns
    label_h = 24 if frame_size == PREVIEW_FRAME_SIZE else 30
    canvas = checker(columns * frame_size, rows * frame_size + label_h, max(8, frame_size // 16))
    for index, (_, frame) in enumerate(items):
        x, y, w, h = (int(frame[key]) for key in ("x", "y", "w", "h"))
        crop = image.crop((x, y, x + w, y + h)).resize((frame_size, frame_size), Image.Resampling.LANCZOS)
        px = (index % columns) * frame_size
        py = (index // columns) * frame_size
        canvas.alpha_composite(crop, (px, py))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, rows * frame_size, canvas.width, canvas.height), fill="#ffffff")
    draw.text((8, rows * frame_size + 5), folder.name, fill="#1a202c")
    canvas.save(out)


def process_folder(folder: Path, preview_out: Path, dry_run: bool, metadata_only: bool) -> tuple[str, dict]:
    atlas_path = folder / "atlas.json"
    sheet_path = folder / "spritesheet.png"
    webp_path = folder / "spritesheet.webp"
    visual_path = folder / "visual.json"
    atlas = json.loads(atlas_path.read_text(encoding="utf-8"))
    image = Image.open(sheet_path).convert("RGBA")
    polished = image if metadata_only else polish_image(image)
    proportions = proportion_report(polished, atlas)
    visual = {
        "frameSize": int(atlas.get("meta", {}).get("frame_size", {}).get("h") or FRAME_SIZE),
        "alphaBounds": alpha_bounds(polished, atlas),
        "polish": "soft-edge-cyan-green-despill-v1",
        "proportion": proportions,
    }
    if not metadata_only:
        atlas.setdefault("meta", {})["background_mode"] = "gpt3d_chromakey_despill_polished_v1"
        atlas["meta"]["edge_polish"] = "soft-alpha-cyan-green-despill-v1"
        atlas["meta"]["optimized_for_game"] = True

    if not dry_run:
        if not metadata_only:
            polished.save(sheet_path, "PNG", optimize=True)
            polished.save(webp_path, "WEBP", lossless=True, quality=100, method=6)
            atlas_path.write_text(json.dumps(atlas, separators=(",", ":")), encoding="utf-8")
        visual_path.write_text(json.dumps(visual, separators=(",", ":")), encoding="utf-8")
        preview_out.mkdir(parents=True, exist_ok=True)
        render_preview(folder, polished, atlas, preview_out / f"{folder.name}-preview.png", PREVIEW_FRAME_SIZE)
        render_preview(folder, polished, atlas, preview_out / f"{folder.name}-closeup-preview.png", CLOSEUP_FRAME_SIZE)

    return folder.name, visual


def build_combined_preview(preview_out: Path, folders: list[Path]) -> None:
    previews = [Image.open(preview_out / f"{folder.name}-preview.png").convert("RGBA") for folder in folders]
    if not previews:
        return
    tile_w, tile_h = previews[0].size
    columns = 4
    rows = (len(previews) + columns - 1) // columns
    canvas = Image.new("RGBA", (columns * tile_w, rows * tile_h), "#ffffff")
    for index, preview in enumerate(previews):
        canvas.alpha_composite(preview, ((index % columns) * tile_w, (index // columns) * tile_h))
    canvas.save(preview_out / "gpt3d-walk-combined-preview.png")


def write_proportion_reports(preview_out: Path, reports: dict[str, dict]) -> None:
    preview_out.mkdir(parents=True, exist_ok=True)
    (preview_out / "gpt3d-proportion-report.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    lines = ["folder,frames,width_var,height_var,lower_var,lower_ratio,lower_ratio_var,foot_var,flagged"]
    for name, report in reports.items():
        lines.append(
            ",".join(
                [
                    name,
                    str(report.get("frameCount", 0)),
                    str(report.get("bodyWidthVariance", 0)),
                    str(report.get("bodyHeightVariance", 0)),
                    str(report.get("lowerBodyWidthVariance", 0)),
                    str(report.get("lowerBodyWidthRatio", 0)),
                    str(report.get("lowerBodyWidthRatioVariance", 0)),
                    str(report.get("footBottomVariance", 0)),
                    str(report.get("flagged", False)),
                ]
            )
        )
    (preview_out / "gpt3d-proportion-report.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    folders = [args.asset_root / name for name in args.folders] if args.folders else sorted(args.asset_root.glob("gpt3d_walk_*"))
    folders = [folder for folder in folders if folder.is_dir()]
    if not folders:
        raise SystemExit("No gpt3d walk folders found.")

    reports: dict[str, dict] = {}
    for folder in folders:
        name, visual = process_folder(folder, args.preview_out, args.dry_run, args.metadata_only)
        reports[name] = visual["proportion"]
        action = "measured" if args.metadata_only else "polished"
        flag = " FLAGGED" if visual["proportion"].get("flagged") else ""
        print(f"{action} {name} bounds={visual['alphaBounds']} lowerVar={visual['proportion']['lowerBodyWidthVariance']}{flag}")
    if not args.dry_run:
        write_proportion_reports(args.preview_out, reports)
        build_combined_preview(args.preview_out, folders)


if __name__ == "__main__":
    main()
