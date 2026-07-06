"""Generate one Alpecca Stage 4 tile with an open-source Diffusers backend.

This is a first production-runner adapter, not an approval gate. It is designed
to be called by run_alpecca_stage4_tile_worker.py as ALPECCA_TILE_COMMAND.

Example:

python scripts/generate_alpecca_stage4_tile_diffusers.py \
  --prompt "{prompt_file}" --job-json "{job_json}" --seed "{seed_canvas}" \
  --pose "{pose_guides}" --out "{output}"

Production output is an exact native 4096x4096 RGBA PNG. Draft upscales are
allowed only when explicitly requested and are written with a sidecar flag so
they are not mistaken for real 4K source art. Art still must pass the Stage 4
importer, stitcher, and visual QA before Stage 5 runtime compilation.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter


DEFAULT_MODEL = os.environ.get("ALPECCA_TILE_MODEL", "cagliostrolab/animagine-xl-4.0")
DEFAULT_NEGATIVE = (
    "low quality, blurry, cropped, cut off feet, cut off hair, missing stockings, "
    "brown hair, red hair, orange hair, black hair, skirt, dress, school uniform, blouse, tie, "
    "bare legs, bare thighs, short socks, black stockings, sneakers, black boots, red boots, "
    "redesigned outfit, missing hoodie, missing shorts, missing lanyard, missing blue hair clip, "
    "animal ears, blue orbs, halo, floor shadow, bent over, crouching, leaning forward, "
    "drop shadow, text, watermark, scenery, furniture, UI, extra limbs, deformed hands, "
    "wrong character, child proportions, thick thighs, tiny body, huge head, flat billboard, "
    "paper thin side view, collapsed silhouette, duplicated back view, multiple characters, "
    "character sheet, turnaround sheet, reference sheet, four bodies, mannequin, robot, mech armor, grey bodysuit, "
    "gray background, grey background, white background, beige background, tan background, opaque background"
)

SECTOR_16_DESCRIPTIONS = {
    "s0": "0 degrees, straight front view, both eyes and front outfit visible",
    "s1": "22.5 degrees, subtle front-right turn, right shoulder slightly recedes",
    "s2": "45 degrees, clear front-right three-quarter view",
    "s3": "67.5 degrees, near right-side view with partial face and visible body depth",
    "s4": "90 degrees, true right side profile, torso and boots in profile but not paper-thin",
    "s5": "112.5 degrees, rear-right three-quarter view with mostly back hair and jacket",
    "s6": "135 degrees, clear back-right diagonal view",
    "s7": "157.5 degrees, near back view turned slightly right",
    "s8": "180 degrees, straight back view, back hair and back of jacket visible",
    "s9": "202.5 degrees, near back view turned slightly left",
    "s10": "225 degrees, clear back-left diagonal view",
    "s11": "247.5 degrees, rear-left three-quarter view with mostly back hair and jacket",
    "s12": "270 degrees, true left side profile, torso and boots in profile but not paper-thin",
    "s13": "292.5 degrees, near left-side view with partial face and visible body depth",
    "s14": "315 degrees, clear front-left three-quarter view",
    "s15": "337.5 degrees, subtle front-left turn, left shoulder slightly recedes",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def crop_frame_source(path: Path | None, job: dict[str, Any], size: int) -> Image.Image | None:
    seed_policy = str(job.get("seedConditionPolicy") or "").lower()
    if "no-img2img" in seed_policy or "reference-only" in seed_policy:
        return None
    if not path or not path.exists():
        return None
    image = Image.open(path).convert("RGBA")
    frame_count = int(job.get("frameCount") or 1)
    frame_index = int(job.get("frameIndex") or 0)
    slot = int(job.get("slotPixels") or size)
    if image.width >= slot * frame_count and image.height >= slot:
        left = min(frame_index * slot, max(0, image.width - slot))
        frame = image.crop((left, 0, left + slot, slot))
        return crop_visible_seed_subject(frame)
    side = min(image.width, image.height)
    left = max(0, (image.width - side) // 2)
    top = max(0, (image.height - side) // 2)
    frame = image.crop((left, top, left + side, top + side))
    return crop_visible_seed_subject(frame)


def crop_visible_seed_subject(frame: Image.Image) -> Image.Image | None:
    alpha = frame.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return None
    if (bbox[2] - bbox[0]) > frame.width * 0.86 and (bbox[3] - bbox[1]) > frame.height * 0.86:
        pixels = frame.load()
        xs: list[int] = []
        ys: list[int] = []
        sample_step = max(1, frame.width // 2048)
        for y in range(0, frame.height, sample_step):
            for x in range(0, frame.width, sample_step):
                r, g, b, a = pixels[x, y]
                if a > 16 and max(r, g, b) > 42:
                    xs.append(x)
                    ys.append(y)
        if xs and ys:
            pad = max(12, int(min(frame.width, frame.height) * 0.025))
            bbox = (
                max(0, min(xs) - pad),
                max(0, min(ys) - pad),
                min(frame.width, max(xs) + pad),
                min(frame.height, max(ys) + pad),
            )
        else:
            return None
    bbox_w = bbox[2] - bbox[0]
    bbox_h = bbox[3] - bbox[1]
    if bbox_w <= 0 or bbox_h <= 0 or bbox_w / max(1, bbox_h) > 1.25:
        return None
    return frame.crop(bbox)


def fit_source_for_generation(image: Image.Image | None, render_size: int) -> Image.Image | None:
    if image is None:
        return None
    canvas = Image.new("RGB", (render_size, render_size), (0, 255, 0))
    working = image.convert("RGBA")
    working.thumbnail((render_size, render_size), Image.Resampling.LANCZOS)
    x = (render_size - working.width) // 2
    y = render_size - working.height
    canvas.paste(working.convert("RGB"), (x, y), working)
    return canvas


def remove_chroma_green(image: Image.Image, feather: int = 0) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            max_rb = max(r, b)
            green_excess = g - max_rb
            green_dominant = g > 72 and green_excess > 18 and g > r * 1.10 and g > b * 1.10
            bright_key = g > 135 and green_excess > 32 and r < 170 and b < 190
            edge_spill = a < 245 and g > 80 and green_excess > 12
            if green_dominant or bright_key or edge_spill:
                pixels[x, y] = (0, 0, 0, 0)
            elif g > max_rb + 10 and g > 70:
                clean_g = max(max_rb, min(g, int(max_rb + 8)))
                pixels[x, y] = (r, clean_g, b, a)
    if feather > 0:
        alpha = rgba.getchannel("A").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(feather))
        rgba.putalpha(alpha)
    return remove_floor_shadow_artifacts(rgba)


def remove_floor_shadow_artifacts(image: Image.Image) -> Image.Image:
    """Remove generated contact blobs outside Alpecca's real foot/boot columns."""
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return rgba
    left, top, right, bottom = bbox
    subject_h = max(1, bottom - top)
    y0 = max(top, bottom - int(subject_h * 0.12))
    alpha_pixels = alpha.load()
    occupied_columns: set[int] = set()
    for x in range(left, right):
        for y in range(top, max(top, y0 - 8)):
            if alpha_pixels[x, y] > 28:
                occupied_columns.add(x)
                break
    expanded_columns: set[int] = set()
    for x in occupied_columns:
        for dx in range(-10, 11):
            expanded_columns.add(x + dx)

    core_columns: set[int] = set()
    core_band_end = min(bottom, y0 + int(subject_h * 0.02))
    for x in range(left, right):
        for y in range(y0, core_band_end):
            if alpha_pixels[x, y] > 28:
                core_columns.add(x)
                break
    expanded_core_columns: set[int] = set()
    for x in core_columns:
        for dx in range(-18, 19):
            expanded_core_columns.add(x + dx)

    pixels = rgba.load()
    for y in range(y0, bottom):
        for x in range(left, right):
            if x in expanded_core_columns:
                continue
            r, g, b, a = pixels[x, y]
            if a <= 0:
                continue
            mx = max(r, g, b)
            mn = min(r, g, b)
            saturation = (mx - mn) / max(1, mx)
            if (x not in expanded_columns and saturation < 0.20 and mx < 254) or (saturation < 0.10 and mx < 246):
                pixels[x, y] = (0, 0, 0, 0)
    return rgba


def ensure_exact_rgba(image: Image.Image, out_path: Path, size: int, *, allow_draft_upscale: bool) -> bool:
    rgba = remove_chroma_green(image)
    if rgba.size != (size, size):
        if not allow_draft_upscale:
            raise SystemExit(
                f"Refusing to upscale {rgba.size} to {(size, size)}. "
                "Set --allow-draft-upscale only for non-promotable draft runs, "
                "or generate natively at 4096x4096."
            )
        rgba = rgba.resize((size, size), Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(out_path)
    return image.size != (size, size)


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _try_call(pipe, method_name: str, sidecar: dict[str, Any], label: str) -> None:
    method = getattr(pipe, method_name, None)
    if not callable(method):
        sidecar.setdefault("unavailable", []).append(label)
        return
    try:
        method()
        sidecar.setdefault("enabled", []).append(label)
    except Exception as error:
        sidecar.setdefault("failed", []).append({"label": label, "error": f"{type(error).__name__}: {error}"})


def configure_memory(pipe, torch) -> dict[str, Any]:
    """Enable production-safe low-VRAM Diffusers features when available."""
    settings = {
        "schema": "alpecca.stage4.diffusers_memory.v1",
        "cuda": bool(torch.cuda.is_available()),
        "mode": os.environ.get("ALPECCA_TILE_MEMORY_MODE", "low_vram").strip().lower(),
        "enabled": [],
        "failed": [],
        "unavailable": [],
        "maxGpuMemoryGb": None,
    }
    if torch.cuda.is_available():
        try:
            props = torch.cuda.get_device_properties(0)
            settings["gpuName"] = props.name
            settings["totalGpuMemoryGb"] = round(props.total_memory / (1024 ** 3), 2)
        except Exception:
            pass
    mode = settings["mode"]
    if mode == "off":
        return settings

    if _truthy_env("ALPECCA_TILE_ENABLE_XFORMERS", "1"):
        _try_call(pipe, "enable_xformers_memory_efficient_attention", settings, "xformers_memory_efficient_attention")
    if _truthy_env("ALPECCA_TILE_ENABLE_ATTENTION_SLICING", "1"):
        _try_call(pipe, "enable_attention_slicing", settings, "attention_slicing")
    if _truthy_env("ALPECCA_TILE_ENABLE_VAE_SLICING", "1"):
        _try_call(pipe, "enable_vae_slicing", settings, "vae_slicing")
    if _truthy_env("ALPECCA_TILE_ENABLE_VAE_TILING", "1"):
        _try_call(pipe, "enable_vae_tiling", settings, "vae_tiling")
    return settings


def load_pipeline(model: str, mode: str):
    try:
        import torch
        from diffusers import AutoPipelineForImage2Image, AutoPipelineForText2Image
    except ImportError as error:
        raise SystemExit(
            "Diffusers generation requires: pip install diffusers transformers accelerate safetensors torch pillow"
        ) from error

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    pipeline_cls = AutoPipelineForImage2Image if mode == "img2img" else AutoPipelineForText2Image
    try:
        pipe = pipeline_cls.from_pretrained(model, torch_dtype=dtype, variant="fp16" if dtype == torch.float16 else None)
    except ValueError as error:
        if "variant=fp16" not in str(error):
            raise
        pipe = pipeline_cls.from_pretrained(model, torch_dtype=dtype)
    if torch.cuda.is_available():
        memory_mode = os.environ.get("ALPECCA_TILE_MEMORY_MODE", "low_vram").strip().lower()
        try:
            if memory_mode == "sequential":
                pipe.enable_sequential_cpu_offload()
            else:
                pipe.enable_model_cpu_offload()
        except Exception:
            pipe = pipe.to("cuda")
    else:
        pipe = pipe.to("cpu")
    memory = configure_memory(pipe, torch)
    return pipe, torch, memory


def build_prompt(base_prompt: str, job: dict[str, Any]) -> str:
    sector = str(job.get("viewSector16") or job.get("horizontalTier") or "s0")
    sector_description = SECTOR_16_DESCRIPTIONS.get(sector, "exact native 16-sector turnaround view")
    camera = f"{job.get('verticalTier')} camera tier, 16-sector view {sector}: {sector_description}"
    motion = job.get("poseNote") or "stable full-body Alpecca animation frame"
    return (
        base_prompt
        + "\n\nGenerator adapter addendum:\n"
        + "- masterpiece, best quality, 1girl, solo, one isolated production game sprite on flat pure chroma key green #00ff00 background\n"
        + "- adult female Alpecca, 5ft7, exact character design lock, no redesign\n"
        + "- white silver hair with pale lavender blue tips, blue eyes, small blue X hair clip\n"
        + f"- {camera}\n"
        + f"- {motion}\n"
        + "- for side walk frames: true standing side-profile contact pose, torso upright, one planted support foot on the shared baseline, rear foot trailing, natural knees, slim consistent thighs\n"
        + "- the camera angle must match this sector exactly; never draw a generic front view for side or back sectors\n"
        + "- one single isolated full-body Alpecca character only; do not draw a character sheet or turntable sheet\n"
        + "- pure flat chroma green #00ff00 background for alpha removal; no gray, beige, tan, white, or opaque studio background\n"
        + "- crisp clean anime production sprite, stable adult proportions\n"
        + "- exact outfit: warm ivory cream oversized hoodie jacket with pale blue trim, white inner shirt, blue lanyard ID badge, black high-waist shorts, both legs fully covered by white thigh-high stockings from upper thigh to boots, black right thigh strap where visible, chunky cream white boots with pale blue details\n"
        + "- draw only this one camera angle while preserving believable 3D body depth: shoulders, hips, hair mass, legs, stockings, and boots rotate coherently\n"
        + "- side views must keep believable adult body depth, never an ultra-thin flat cutout\n"
        + "- full body centered with generous transparent margin, feet fully visible, hair fully visible\n"
        + "- no baked shadow, no halo, no blue orbs, no floor, no furniture, no skirt, no bare legs, no brown hair\n"
    )


def generate_tile(args: argparse.Namespace) -> dict[str, Any]:
    job = load_json(args.job_json)
    prompt = build_prompt(read_prompt(args.prompt), job)
    expected = tuple(int(value) for value in job.get("expectedSize", [4096, 4096]))
    if expected[0] != expected[1]:
        raise SystemExit(f"Expected square tile size, got {expected}")
    source = crop_frame_source(args.seed, job, expected[0])
    render_source = fit_source_for_generation(source, args.render_size)
    mode = "img2img" if render_source is not None and args.strength > 0 else "txt2img"
    pipe, torch, memory = load_pipeline(args.model, mode)
    seed = args.seed_value if args.seed_value is not None else random.randint(1, 2_147_483_647)
    generator = torch.Generator(device="cuda" if torch.cuda.is_available() else "cpu").manual_seed(seed)

    common = {
        "prompt": prompt,
        "negative_prompt": args.negative_prompt,
        "num_inference_steps": args.steps,
        "guidance_scale": args.guidance,
        "generator": generator,
    }
    if mode == "img2img":
        result = pipe(
            image=render_source,
            strength=args.strength,
            **common,
        )
    else:
        result = pipe(
            width=args.render_size,
            height=args.render_size,
            **common,
        )
    image = result.images[0]
    upscaled = ensure_exact_rgba(image, args.out, expected[0], allow_draft_upscale=args.allow_draft_upscale)
    sidecar = {
        "schemaVersion": 1,
        "stage": "stage-4-diffusers-tile-generation",
        "jobId": job.get("jobId"),
        "targetId": job.get("targetId"),
        "matrixKey": job.get("matrixKey"),
        "frameIndex": job.get("frameIndex"),
        "model": args.model,
        "mode": mode,
        "seed": seed,
        "renderSize": args.render_size,
        "nativeSourcePixels": list(image.size),
        "memory": memory,
        "upscaledToRequiredSize": upscaled,
        "promotionStatus": "draft-not-promotable" if upscaled else "generated-awaiting-import",
        "output": str(args.out),
        "expectedSize": list(expected),
        "policy": "Generated tile still requires importer, stitcher, and visual QA approval.",
    }
    args.out.with_suffix(".generation.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return sidecar


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--job-json", type=Path, required=True)
    parser.add_argument("--seed", type=Path)
    parser.add_argument("--pose", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE)
    parser.add_argument("--render-size", type=int, default=int(os.environ.get("ALPECCA_TILE_RENDER_SIZE", "4096")))
    parser.add_argument("--steps", type=int, default=int(os.environ.get("ALPECCA_TILE_STEPS", "28")))
    parser.add_argument("--guidance", type=float, default=float(os.environ.get("ALPECCA_TILE_GUIDANCE", "7.0")))
    parser.add_argument("--strength", type=float, default=float(os.environ.get("ALPECCA_TILE_STRENGTH", "0.62")))
    parser.add_argument("--seed-value", type=int)
    parser.add_argument(
        "--allow-draft-upscale",
        action="store_true",
        help="Allow non-promotable draft upscaling to 4096x4096. Do not use for production source art.",
    )
    args = parser.parse_args()
    result = generate_tile(args)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
