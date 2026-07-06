from __future__ import annotations

import argparse
import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Iterable

from PIL import Image


DEFAULT_ZIP = Path(r"C:\Users\Jason\Downloads\Alpecca-spritesheet (1).zip")
DEFAULT_OUT = Path("public/assets/alpecca-optimized")

ALPECCA_ASSET_FOLDERS = [
    "idle_right",
    "walk_right",
    "run_right",
    "jump_right",
    "iso_idle_down_right",
    "iso_idle_up_right",
    "iso_idle_right_right",
    "iso_idle_northeast_right",
    "iso_idle_southeast_right",
    "iso_walk_down_right",
    "iso_walk_up_right",
    "iso_walk_right_right",
    "iso_walk_northeast_right",
    "iso_walk_southeast_right",
    "iso_run_down_right",
    "iso_run_up_right",
    "iso_run_right_right",
    "iso_run_northeast_right",
    "iso_run_southeast_right",
    "iso_jump_down_right",
    "iso_jump_up_right",
    "iso_jump_right_right",
    "iso_jump_southeast_right",
    "Climb",
    "Crouch",
    "Dash",
    "Dance",
    "Kneel",
    "Pickup",
    "Point",
    "Sit",
    "Sleep",
    "Sleep Down",
    "Sleep Northeast",
    "Sleep Southeast",
    "Sleep Up",
    "Victory",
    "Wave",
    "Wave Down",
    "Wave Northeast",
    "Wave Up",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare selected Alpecca atlas folders for the Three.js game.")
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP, help="Path to Alpecca-spritesheet zip.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output asset root.")
    parser.add_argument(
        "--folders",
        nargs="*",
        default=ALPECCA_ASSET_FOLDERS,
        help="Folder names to extract. Defaults to every Alpecca atlas state used by the game, including directional movement.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing target folders.")
    return parser.parse_args()


def zip_read(zf: zipfile.ZipFile, name: str) -> bytes:
    try:
        return zf.read(name)
    except KeyError as exc:
        raise FileNotFoundError(f"Missing {name} in source zip") from exc


def sorted_frame_items(atlas: dict) -> Iterable[tuple[str, dict]]:
    frames = atlas.get("frames", {})

    def key(item: tuple[str, dict]) -> tuple[int, str]:
        raw = item[0]
        try:
            return (int(raw), raw)
        except ValueError:
            return (10**9, raw)

    return sorted(frames.items(), key=key)


def alpha_bounds_for_atlas(image: Image.Image, atlas: dict) -> dict[str, int]:
    rgba = image.convert("RGBA")
    left = top = 10**9
    right = bottom = -1

    for _, frame in sorted_frame_items(atlas):
        x = int(frame["x"])
        y = int(frame["y"])
        w = int(frame["w"])
        h = int(frame["h"])
        alpha = rgba.crop((x, y, x + w, y + h)).getchannel("A")
        bounds = alpha.getbbox()
        if not bounds:
            continue
        frame_left, frame_top, frame_right, frame_bottom = bounds
        left = min(left, frame_left)
        top = min(top, frame_top)
        right = max(right, frame_right)
        bottom = max(bottom, frame_bottom)

    frame_size = atlas.get("meta", {}).get("frame_size", {})
    fallback_w = int(frame_size.get("w") or 512)
    fallback_h = int(frame_size.get("h") or 512)
    if right < left or bottom < top:
        return {"x": 0, "y": 0, "w": fallback_w, "h": fallback_h}

    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def prepare_folder(zf: zipfile.ZipFile, source_folder: str, out_root: Path, overwrite: bool) -> None:
    target = out_root / source_folder
    if target.exists():
        if not overwrite:
            print(f"skip existing {source_folder}")
            return
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    atlas_name = f"{source_folder}/atlas.json"
    sheet_name = f"{source_folder}/spritesheet.png"
    atlas_bytes = zip_read(zf, atlas_name)
    sheet_bytes = zip_read(zf, sheet_name)
    atlas = json.loads(atlas_bytes.decode("utf-8"))

    (target / "atlas.json").write_bytes(atlas_bytes)
    (target / "spritesheet.png").write_bytes(sheet_bytes)

    with Image.open(io.BytesIO(sheet_bytes)) as image:
        image.load()
        frame_size = atlas.get("meta", {}).get("frame_size", {})
        visual = {
            "frameSize": int(frame_size.get("h") or frame_size.get("w") or image.height),
            "alphaBounds": alpha_bounds_for_atlas(image, atlas),
        }
        (target / "visual.json").write_text(json.dumps(visual, separators=(",", ":")), encoding="utf-8")
        image.save(target / "spritesheet.webp", "WEBP", lossless=True, quality=100, method=0)
    print(f"prepared {source_folder}")


def main() -> None:
    args = parse_args()
    if not args.zip.exists():
        raise FileNotFoundError(f"Alpecca source zip not found: {args.zip}")

    args.out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.zip) as zf:
        for folder in args.folders:
            prepare_folder(zf, folder, args.out, args.overwrite)


if __name__ == "__main__":
    main()
