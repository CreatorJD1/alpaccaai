from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from PIL import Image


DEFAULT_ASSET_ROOT = Path("public/assets/alpecca-optimized")
DEFAULT_OUT = Path("output/alpecca-animation-audit")
ALPHA_THRESHOLD = 4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Alpecca animation atlas/source quality without modifying assets.")
    parser.add_argument("--asset-root", type=Path, default=DEFAULT_ASSET_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def sorted_frame_items(atlas: dict) -> list[tuple[str, dict]]:
    def key(item: tuple[str, dict]) -> tuple[int, str]:
        try:
            return (int(item[0]), item[0])
        except ValueError:
            return (10**9, item[0])

    return sorted(atlas.get("frames", {}).items(), key=key)


def frame_bounds(image: Image.Image, frame: dict) -> dict[str, int]:
    x, y, w, h = (int(frame[key]) for key in ("x", "y", "w", "h"))
    alpha = image.crop((x, y, x + w, y + h)).getchannel("A").point(lambda value: 255 if value > ALPHA_THRESHOLD else 0)
    bounds = alpha.getbbox()
    if not bounds:
        return {"x": 0, "y": 0, "w": 0, "h": 0}
    bx1, by1, bx2, by2 = bounds
    return {"x": bx1, "y": by1, "w": bx2 - bx1, "h": by2 - by1}


def alpha_band_width(image: Image.Image, frame: dict, y_min: float, y_max: float) -> int:
    x, y, w, h = (int(frame[key]) for key in ("x", "y", "w", "h"))
    alpha = image.crop((x, y, x + w, y + h)).getchannel("A").point(lambda value: 255 if value > ALPHA_THRESHOLD else 0)
    band = alpha.crop((0, int(h * y_min), w, int(h * y_max))).getbbox()
    return int(band[2] - band[0]) if band else 0


def spread(values: list[int]) -> int:
    return max(values) - min(values) if values else 0


def source_family(folder: str) -> str:
    if folder.startswith("iso_"):
        return "iso"
    if folder.startswith("gpt16_"):
        return "gpt16"
    if folder.startswith("gpt3d_"):
        return "gpt3d"
    if folder.startswith("gpt_"):
        return "gpt"
    return folder.replace(" ", "_").split("_")[0] or "legacy"


def classify(folder: str, visual: dict, feet_var: int, lower_var: int, missing_metadata: list[str]) -> str:
    if folder.startswith("gpt3d_walk_"):
        return "needs-regeneration"
    if missing_metadata and folder.startswith(("Wave ", "Sleep ", "Kneel", "Crouch")):
        return "runtime-ok"
    if visual.get("proportion", {}).get("flagged") or feet_var > 24 or lower_var > 90:
        return "qa-only"
    if folder.startswith("iso_walk_"):
        return "approved"
    if folder.startswith("gpt16_walk_"):
        return "runtime-ok" if visual.get("mirroredFrom") else "qa-only"
    if folder.startswith(("iso_idle_", "gpt16_talk_")):
        return "approved"
    return "runtime-ok"


def audit_folder(folder: Path) -> dict:
    atlas_path = folder / "atlas.json"
    png_path = folder / "spritesheet.png"
    webp_path = folder / "spritesheet.webp"
    visual_path = folder / "visual.json"
    if not atlas_path.exists() or not png_path.exists():
        return {
            "folder": folder.name,
            "status": "needs-regeneration",
            "issues": ["missing atlas.json or spritesheet.png"],
        }

    atlas = json.loads(atlas_path.read_text(encoding="utf-8"))
    visual = json.loads(visual_path.read_text(encoding="utf-8")) if visual_path.exists() else {}
    image = Image.open(png_path).convert("RGBA")
    items = sorted_frame_items(atlas)
    bounds = [frame_bounds(image, frame) for _, frame in items]
    lower_widths = [alpha_band_width(image, frame, 0.58, 0.88) for _, frame in items]
    feet = [bound["y"] + bound["h"] for bound in bounds if bound["h"] > 0]
    widths = [bound["w"] for bound in bounds if bound["w"] > 0]
    heights = [bound["h"] for bound in bounds if bound["h"] > 0]
    missing_metadata = []
    for key in ("alphaBounds", "visualScale", "spriteY"):
        if key not in visual:
            missing_metadata.append(key)
    issues = []
    if not webp_path.exists():
        issues.append("missing spritesheet.webp")
    if missing_metadata:
        issues.append(f"missing metadata: {', '.join(missing_metadata)}")
    feet_var = spread(feet)
    lower_var = spread([value for value in lower_widths if value > 0])
    if feet_var > 24:
        issues.append(f"feet baseline variance {feet_var}px")
    if lower_var > 90:
        issues.append(f"lower-body width variance {lower_var}px")
    if visual.get("proportion", {}).get("flagged"):
        issues.append("visual.json proportion flagged")
    status = classify(folder.name, visual, feet_var, lower_var, missing_metadata)
    return {
        "folder": folder.name,
        "family": source_family(folder.name),
        "status": status,
        "frameCount": len(items),
        "atlasSize": f"{image.width}x{image.height}",
        "alphaBounds": visual.get("alphaBounds", {}),
        "heightClass": "short-pose" if folder.name.startswith(("Sleep", "Sit", "Kneel", "Crouch")) else "standing",
        "feetBaselineVariance": feet_var,
        "lowerBodyWidthVariance": lower_var,
        "bodyWidthVariance": spread(widths),
        "bodyHeightVariance": spread(heights),
        "visualScale": visual.get("visualScale"),
        "spriteY": visual.get("spriteY"),
        "mirroredFrom": visual.get("mirroredFrom", ""),
        "missingMetadata": missing_metadata,
        "issues": issues,
    }


def main() -> None:
    args = parse_args()
    folders = sorted(folder for folder in args.asset_root.iterdir() if folder.is_dir())
    report = [audit_folder(folder) for folder in folders]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "alpecca-animation-audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    fields = [
        "folder",
        "family",
        "status",
        "frameCount",
        "atlasSize",
        "heightClass",
        "feetBaselineVariance",
        "lowerBodyWidthVariance",
        "bodyWidthVariance",
        "bodyHeightVariance",
        "visualScale",
        "spriteY",
        "mirroredFrom",
        "missingMetadata",
        "issues",
    ]
    with (args.out / "alpecca-animation-audit.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in report:
            writer.writerow({field: "; ".join(row[field]) if isinstance(row.get(field), list) else row.get(field, "") for field in fields})
    counts: dict[str, int] = {}
    for row in report:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"audited {len(report)} folders -> {args.out}")
    print("status", counts)


if __name__ == "__main__":
    main()
