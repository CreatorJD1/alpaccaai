"""Smoke probes for the VCS Texture Lab ZeroGPU path.

These are developer utilities, not CI tests. They require `HF_TOKEN` and may
spend ZeroGPU quota. Route modes also require the VCS backend on 127.0.0.1:8001.
Outputs are written under data/screenshots/.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import time
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "screenshots"
REFS = ROOT / "apps" / "vcs" / "backend" / "texture_refs"
TURNAROUND = ROOT / "data" / "alpecca_art_source" / "design_lock_references" / "01-turnaround-front-side-back.jpg"
SPACE = os.environ.get("TEXTURE_SPACE", "CREATORJD/alpecca-texture-lab")
BACKEND = os.environ.get("VCS_BACKEND", "http://127.0.0.1:8001")


def _token() -> str:
    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not tok:
        raise SystemExit("Set HF_TOKEN or HUGGINGFACE_TOKEN first.")
    return tok


def _b64(path: Path, max_edge: int = 1024, fmt: str = "PNG") -> str:
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_edge, max_edge))
    buf = io.BytesIO()
    img.save(buf, fmt)
    return base64.b64encode(buf.getvalue()).decode()


def _data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _save_b64(raw_b64: str, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    if raw_b64.startswith("data:"):
        raw_b64 = raw_b64.split(",", 1)[1]
    raw = base64.b64decode(raw_b64)
    out = OUT / name
    out.write_bytes(raw)
    return out


def _client():
    from gradio_client import Client
    return Client(SPACE, token=_token(), verbose=False)


def _wait_running() -> None:
    from huggingface_hub import HfApi
    api = HfApi(token=_token())
    for _ in range(40):
        runtime = api.get_space_runtime(SPACE, token=_token())
        if runtime.stage == "RUNNING":
            return
        print("stage=", runtime.stage, flush=True)
        time.sleep(12)


def texture() -> None:
    c = _client()
    prompt = (
        "flat fabric texture swatch, seamless navy blue cotton twill weave, "
        "anime cel-shaded, even flat lighting, no character, no text"
    )
    start = time.time()
    res = c.predict(prompt, "", "", 0.72, 28, 7.0, 1024, 1024, 0, api_name="/texture")
    out = _save_b64(res, "zerogpu_texture.png")
    print(f"TEXTURE OK {round(time.time() - start)}s -> {out}")


def vision() -> None:
    c = _client()
    system = "You are an anime fashion analyst. List distinct clothing items."
    prompt = (
        'Return JSON: {"garments":[{"slot":"top|bottom|legs|feet|accessory",'
        '"name":"...","primary_color":"...","material":"..."}]}. Only clothing.'
    )
    start = time.time()
    js = c.predict(_b64(TURNAROUND, max_edge=1280, fmt="JPEG"), system, prompt, api_name="/vision_json")
    print(f"VISION OK {round(time.time() - start)}s -> {js[:800]}")


def ipadapter() -> None:
    c = _client()
    atlas = _b64(REFS / "original_outfit_atlas.png")
    garment = _b64(REFS / "vroid_dress_atlas_example.png")
    prompt = "flat anime clothing UV texture atlas, floral fabric, no character, no face"
    start = time.time()
    res = c.predict(prompt, "", atlas, 0.5, 28, 7.0, 1024, 1024, 0, garment, 0.7, api_name="/texture")
    out = _save_b64(res, "ipadapter_out.png")
    print(f"IPADAPTER OK {round(time.time() - start)}s -> {out}")


def controlnet() -> None:
    c = _client()
    atlas_path = REFS / "original_outfit_atlas.png"
    atlas = _b64(atlas_path)
    prompt = "bold crimson and gold ornate floral brocade fabric, anime flat texture, no character"
    start = time.time()
    res = c.predict(prompt, "", atlas, "", 0.75, 0.6, 30, 7.0, 1024, 1024, 0, api_name="/texture_cn")
    out = _save_b64(res, "controlnet_out.png")
    print(f"CONTROLNET OK {round(time.time() - start)}s -> {out}")


def route(mode: str) -> None:
    atlas = REFS / "original_outfit_atlas.png"
    payload = {
        "original_atlas_data_url": _data_url(atlas),
        "region": "top",
        "provider": "zerogpu",
        "guard": False,
        "description": "deep crimson red wool vest and sleeves",
        "palette": "#7a1f2b, #a83440",
        "mode": "bold" if mode == "route_bold" else "restyle",
        "strength": None,
    }
    if mode == "route_ipadapter":
        payload["garment_data_url"] = _data_url(REFS / "vroid_dress_atlas_example.png")
        payload["description"] = "match the reference garment's fabric style and palette"
        payload["strength"] = 0.4
    req = urllib.request.Request(
        f"{BACKEND}/api/generate/material_texture",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    start = time.time()
    data = json.loads(urllib.request.urlopen(req, timeout=600).read().decode())
    asset = data.get("asset") or {}
    out = _save_b64(asset.get("data_url", ""), f"{mode}_out.png")
    print(f"{mode.upper()} OK {round(time.time() - start)}s -> {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=["texture", "vision", "ipadapter", "controlnet", "route_texture", "route_ipadapter", "route_bold", "all"],
    )
    parser.add_argument("--wait", action="store_true", help="Wait for the HF Space to be RUNNING first.")
    args = parser.parse_args()
    if args.wait:
        _wait_running()
    modes = ["texture", "vision", "ipadapter", "controlnet"] if args.mode == "all" else [args.mode]
    for mode in modes:
        if mode.startswith("route_"):
            route(mode)
        else:
            globals()[mode]()


if __name__ == "__main__":
    main()
