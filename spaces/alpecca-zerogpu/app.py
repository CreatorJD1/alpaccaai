from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import gradio as gr
import spaces
import torch
from PIL import Image, ImageFilter
from huggingface_hub import HfApi, hf_hub_download
from transformers import AutoModelForCausalLM, AutoTokenizer


# Her EXACT brain, cloud muscle: the same Qwen3.5-9B she runs locally (Jason's
# explicit model; do not substitute). qwen3_5 is a multimodal arch, so loading
# goes through AutoProcessor + its ForConditionalGeneration class -- text-only
# chat still works through the same chat template.
MODEL_ID = os.environ.get("ALPECCA_ZEROGPU_MODEL", "Qwen/Qwen3.5-9B")
MAX_NEW_TOKENS = int(os.environ.get("ALPECCA_ZEROGPU_MAX_NEW_TOKENS", "768"))
ART_REPO_ID = os.environ.get("ALPECCA_ART_REPO_ID", "CREATORJD/alpecca-art-library")
DEFAULT_STAGE4_HF_PATH = "stage4-tile-jobs/first_slices/idle_eye_16sector_frame000_turnaround/tile_jobs_idle_eye_16sector_frame000_turnaround.jsonl"
DEFAULT_STAGE4_OUTPUT_PREFIX = "stage4-worker-outputs/zerogpu-drafts/idle_eye_16sector_frame000_turnaround"
DEFAULT_TILE_MODEL = os.environ.get("ALPECCA_TILE_MODEL", "cagliostrolab/animagine-xl-4.0")
_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)

tokenizer = None
model = None
tile_pipes: dict[str, Any] = {}


def strip_think(text: str) -> str:
    cleaned = _THINK_RE.sub("", text).strip()
    return cleaned or text.strip()


def load_model():
    global tokenizer, model
    if tokenizer is None:
        # qwen3_5 ships a processor (it can see); for text chat the processor's
        # tokenizer/chat-template side is all we use. Fall back to a plain
        # tokenizer for older text-only MODEL_ID overrides.
        try:
            from transformers import AutoProcessor
            tokenizer = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
        except Exception:
            tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
    if model is None:
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        try:
            from transformers import AutoModelForImageTextToText
            model = AutoModelForImageTextToText.from_pretrained(
                MODEL_ID,
                torch_dtype=dtype,
                device_map="auto",
                trust_remote_code=True,
                low_cpu_mem_usage=True,
            )
        except Exception:
            model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID,
                torch_dtype=dtype,
                device_map="auto",
                trust_remote_code=True,
                low_cpu_mem_usage=True,
            )
        model.eval()
    return tokenizer, model


def parse_history(history_json: str) -> list[dict[str, Any]]:
    if not history_json.strip():
        return []
    try:
        parsed = json.loads(history_json)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    cleaned = []
    for item in parsed[-10:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            cleaned.append({"role": role, "content": content})
    return cleaned


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                jobs.append(json.loads(line))
    return jobs


def tile_status(path: Path, expected_size: tuple[int, int]) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "ready": False, "issues": ["missing"]}
    try:
        with Image.open(path) as image:
            issues: list[str] = []
            if tuple(image.size) != expected_size:
                issues.append(f"wrong-size:{list(image.size)}")
            if "A" not in image.getbands():
                issues.append("no-alpha")
            return {
                "exists": True,
                "ready": not issues,
                "issues": issues,
                "size": list(image.size),
                "mode": image.mode,
            }
    except Exception as error:
        return {"exists": True, "ready": False, "issues": [f"unreadable:{type(error).__name__}:{error}"]}


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
                # Despill antialiased pixels that belong to Alpecca, without
                # changing alpha. This prevents a neon outline on white hair,
                # stockings, and boots after the chroma background is removed.
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

    # The real boot/ankle columns are present just above the generated ground
    # smear. Use them to remove flat contact blobs that widen below the feet.
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


def load_tile_pipeline(model_id: str, mode: str):
    key = f"{mode}:{model_id}"
    if key in tile_pipes:
        return tile_pipes[key]
    from diffusers import AutoPipelineForImage2Image, AutoPipelineForText2Image

    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    pipe_cls = AutoPipelineForImage2Image if mode == "img2img" else AutoPipelineForText2Image
    try:
        pipe = pipe_cls.from_pretrained(
            model_id,
            torch_dtype=dtype,
            variant="fp16" if dtype == torch.float16 else None,
        )
    except ValueError as error:
        if "variant=fp16" not in str(error):
            raise
        pipe = pipe_cls.from_pretrained(model_id, torch_dtype=dtype)
    if torch.cuda.is_available():
        try:
            pipe.enable_model_cpu_offload()
        except Exception:
            pipe = pipe.to("cuda")
    else:
        pipe = pipe.to("cpu")
    for method_name in ("enable_attention_slicing", "enable_vae_slicing", "enable_vae_tiling"):
        method = getattr(pipe, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                pass
    tile_pipes[key] = pipe
    return pipe


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


# Character grounding: the one-phrase identity summary every tile generation
# leads with (design-lock contract; see data/character/sheet.json locally).
CHARACTER_GROUNDING = "Full-body Alpecca anime woman"


def build_tile_prompt(job: dict[str, Any]) -> str:
    sector = str(job.get("viewSector16") or job.get("horizontalTier") or "s0")
    vertical = str(job.get("verticalTier") or "eye")
    action = str(job.get("action") or "idle")
    sector_description = SECTOR_16_DESCRIPTIONS.get(sector, "exact native 16-sector turnaround view")
    motion = str(job.get("poseNote") or "").strip()
    walk_clause = ""
    if action == "walk":
        walk_clause = (
            " calm natural walk-cycle frame, clear readable leg phase, grounded foot contact,"
            " walk-cycle pose-guide anatomy, upright adult posture, no repeated leg pose,"
            " no running, stable foot baseline, one foot planted on the baseline,"
        )
    return (
        f"{CHARACTER_GROUNDING}, "
        "masterpiece, best quality, 1girl, solo, one single isolated full body Alpecca adult anime woman, "
        "adult female, 5ft7, production game sprite, exact character design lock, "
        "white silver hair, pale lavender blue hair tips, blue eyes, small blue X hair clip, "
        "oversized warm ivory cream hoodie jacket, pale blue trim, white inner shirt, blue lanyard ID badge, "
        "black high waist shorts, both legs fully covered by white thigh-high stockings, white stockings from upper thigh to boots, "
        "black right thigh strap where visible, chunky cream white boots with pale blue details, "
        f"{action} {walk_clause} {vertical} camera, {sector} {sector_description}, "
        f"{motion}, "
        "for side walk frames: true standing side-profile contact pose, torso upright, adult proportions, "
        "front/support foot planted flat on shared baseline, rear foot trailing, knees natural, thighs slim consistent, "
        "draw only this one camera angle, believable 3D body depth, side thickness, not a flat billboard, "
        "full body centered with generous transparent margin, feet fully visible, hair fully visible, "
        "stable adult proportions, stable thigh width, exact outfit, no redesign, "
        "flat pure chroma key green #00ff00 background, solid green background, no gray background, no beige background, no transparent checkerboard, "
        "no halo, no shadow, no blue orbs, no scenery, no text, no character sheet, no turntable sheet"
    )


def hf_source_path(path: str | None) -> str | None:
    if not path:
        return None
    value = str(path).replace("\\", "/")
    if value.startswith("data/alpecca_art_source/"):
        return "source-library/" + value[len("data/alpecca_art_source/") :]
    return value


def build_seed_condition(job: dict[str, Any], render_size: int) -> Image.Image | None:
    seed_policy = str(job.get("seedConditionPolicy") or "").lower()
    if "no-img2img" in seed_policy or "reference-only" in seed_policy:
        return None
    seed_path = hf_source_path(job.get("seedCanvas"))
    if not seed_path:
        return None
    try:
        local_seed = Path(hf_hub_download(repo_id=ART_REPO_ID, filename=seed_path, repo_type="dataset"))
        source = Image.open(local_seed).convert("RGBA")
    except Exception:
        return None
    frame_count = max(1, int(job.get("frameCount") or 1))
    frame_index = int(job.get("frameIndex") or 0)
    slot = int(job.get("slotPixels") or source.height)
    if source.width >= slot * frame_count and source.height >= slot:
        left = min(frame_index * slot, max(0, source.width - slot))
        frame = source.crop((left, 0, left + slot, slot))
    else:
        frame = source
    alpha = frame.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return None
    # Some Stage 4 seed canvases are opaque black strips with a tiny visible
    # reference figure. Alpha then reports the whole slot and img2img turns the
    # input into a multi-character sheet. Prefer visible non-background pixels.
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
    if bbox_w <= 0 or bbox_h <= 0:
        return None
    if bbox_w / max(1, bbox_h) > 1.25:
        return None
    subject = frame.crop(bbox)
    target_h = int(render_size * 0.78)
    scale = target_h / max(1, subject.height)
    target_w = max(1, int(subject.width * scale))
    if target_w > int(render_size * 0.62):
        scale = (render_size * 0.62) / max(1, subject.width)
        target_w = int(subject.width * scale)
        target_h = int(subject.height * scale)
    subject = subject.resize((target_w, target_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (render_size, render_size), (0, 255, 0))
    x = (render_size - target_w) // 2
    y = render_size - target_h - int(render_size * 0.06)
    canvas.paste(subject.convert("RGB"), (x, y), subject)
    return canvas


@spaces.GPU(duration=180)
def generate_stage4_tile(
    hf_path: str,
    offset: int,
    output_prefix: str,
    model_id: str,
    render_size: int,
    steps: int,
    guidance: float,
    seed: int,
    strength: float,
) -> str:
    hf_path = (hf_path or DEFAULT_STAGE4_HF_PATH).strip()
    output_prefix = (output_prefix or DEFAULT_STAGE4_OUTPUT_PREFIX).strip().strip("/")
    model_id = (model_id or DEFAULT_TILE_MODEL).strip()
    jobs_file = Path(hf_hub_download(repo_id=ART_REPO_ID, filename=hf_path, repo_type="dataset"))
    jobs = load_jsonl(jobs_file)
    if offset < 0 or offset >= len(jobs):
        raise gr.Error(f"Offset {offset} is outside the job file with {len(jobs)} jobs.")
    job = jobs[offset]
    expected_size = tuple(int(value) for value in job.get("expectedSize", [4096, 4096]))
    if expected_size[0] != expected_size[1] or expected_size[0] < 4096:
        raise gr.Error(f"Stage 4 production jobs must be square native 4K+, got {expected_size}.")

    render_size = int(render_size)
    if render_size < 1024 or render_size > expected_size[0]:
        raise gr.Error(f"render_size must be between 1024 and {expected_size[0]}, got {render_size}.")
    seed_condition = build_seed_condition(job, render_size)
    mode = "img2img" if seed_condition is not None else "txt2img"
    pipe = load_tile_pipeline(model_id, mode)
    generator = torch.Generator(device="cuda" if torch.cuda.is_available() else "cpu").manual_seed(int(seed))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out_path = root / str(job["expectedWorkerOutput"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        common = {
            "prompt": build_tile_prompt(job),
            "negative_prompt": (
                "rug, carpet, frame, box, object, scenery, room, floor, low quality, blurry, cropped, "
                "brown hair, red hair, orange hair, black hair, skirt, dress, school uniform, blouse, tie, "
                "bare legs, bare thighs, missing stockings, short socks, black stockings, black boots, sneakers, "
                "red boots, redesigned outfit, missing hoodie, missing shorts, missing lanyard, missing blue hair clip, "
                "bent over, crouching, leaning forward, child proportions, tiny body, huge head, thick thighs, "
                "halo, blue orbs, floor shadow, "
                "drop shadow, UI, text, watermark, flat billboard, paper thin side view, multiple characters, "
                "character sheet, turnaround sheet, reference sheet, four bodies, mannequin, robot, mech armor, grey bodysuit, "
                "gray background, grey background, white background, beige background, tan background, opaque background"
            ),
            "num_inference_steps": int(steps),
            "guidance_scale": float(guidance),
            "generator": generator,
        }
        if mode == "img2img":
            result = pipe(image=seed_condition, strength=float(strength), **common)
        else:
            result = pipe(width=render_size, height=render_size, **common)
        rgba = remove_chroma_green(result.images[0])
        promotion_status = "generated-awaiting-import"
        if rgba.size != expected_size:
            if rgba.size != (render_size, render_size):
                raise gr.Error(f"Generator returned unexpected size {rgba.size}; expected {(render_size, render_size)}.")
            canvas = Image.new("RGBA", expected_size, (0, 0, 0, 0))
            x = (expected_size[0] - rgba.width) // 2
            y = expected_size[1] - rgba.height
            canvas.alpha_composite(rgba, (x, y))
            rgba = canvas
            promotion_status = "draft-not-promotable"
        rgba.save(out_path)
        status = tile_status(out_path, expected_size)
        sidecar = {
            "schemaVersion": 1,
            "stage": "stage-4-zerogpu-tile-generation",
            "jobId": job.get("jobId"),
            "targetId": job.get("targetId"),
            "matrixKey": job.get("matrixKey"),
            "viewSector16": job.get("viewSector16"),
            "frameIndex": job.get("frameIndex"),
            "model": model_id,
            "mode": mode,
            "renderSize": render_size,
            "steps": int(steps),
            "guidance": float(guidance),
            "strength": float(strength),
            "seed": int(seed),
            "expectedSize": list(expected_size),
            "tileStatus": status,
            "promotionStatus": promotion_status,
            "singleCharacterOnly": True,
            "promotionPolicy": "Returned tile still requires local returned-slice QA, import, stitch, and visual approval.",
        }
        out_path.with_suffix(".generation.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        HfApi().upload_folder(
            repo_id=ART_REPO_ID,
            repo_type="dataset",
            folder_path=str(root),
            path_in_repo=output_prefix,
            commit_message=f"Upload ZeroGPU Stage 4 tile {job.get('jobId')}",
        )
        return json.dumps(
            {
                "uploaded": True,
                "repo": ART_REPO_ID,
                "prefix": output_prefix,
                "jobId": job.get("jobId"),
                "matrixKey": job.get("matrixKey"),
                "tileStatus": status,
                "promotionStatus": promotion_status,
                "nextStep": "Run scripts/run_alpecca_stage4_returned_slice_qa.py locally after all 16 sectors return.",
            },
            indent=2,
        )


@spaces.GPU(duration=120)
def chat(system_prompt: str, user_msg: str, history_json: str = "") -> str:
    tok, mdl = load_model()
    messages = [{"role": "system", "content": system_prompt.strip()}]
    messages.extend(parse_history(history_json))
    messages.append({"role": "user", "content": user_msg.strip() or "(think freely)"})

    # `tok` may be an AutoProcessor (qwen3_5 multimodal) or a plain tokenizer;
    # the text side lives on .tokenizer when it's a processor.
    text_tok = getattr(tok, "tokenizer", tok)
    try:
        prompt = tok.apply_chat_template(messages, tokenize=False,
                                         add_generation_prompt=True,
                                         enable_thinking=False)
    except TypeError:
        prompt = tok.apply_chat_template(messages, tokenize=False,
                                         add_generation_prompt=True)
    inputs = text_tok(prompt, return_tensors="pt").to(mdl.device)
    with torch.inference_mode():
        output = mdl.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=True,
            temperature=0.75,
            top_p=0.9,
            repetition_penalty=1.05,
            pad_token_id=text_tok.eos_token_id,
        )
    new_tokens = output[0][inputs["input_ids"].shape[-1] :]
    return strip_think(text_tok.decode(new_tokens, skip_special_tokens=True))


# --- Cloud vision: offload the VL model to the Space GPU (loads lazily, so the
# chat/art tabs are untouched until /vision is actually called) ----------------
VL_MODEL_ID = os.environ.get("ALPECCA_ZEROGPU_VL_MODEL", "Qwen/Qwen2.5-VL-3B-Instruct")
vl_processor = None
vl_model = None


def load_vl():
    global vl_processor, vl_model
    if vl_processor is None:
        from transformers import AutoProcessor
        vl_processor = AutoProcessor.from_pretrained(VL_MODEL_ID, trust_remote_code=True)
    if vl_model is None:
        from transformers import Qwen2_5_VLForConditionalGeneration
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        vl_model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            VL_MODEL_ID, torch_dtype=dtype, device_map="auto",
            trust_remote_code=True, low_cpu_mem_usage=True,
        )
        vl_model.eval()
    return vl_processor, vl_model


@spaces.GPU(duration=45)
def describe(image, prompt: str = "Describe this image.") -> str:
    """Describe an image with the cloud VL model. `image` is a filepath from the
    gradio client; returns a short text description (grounding stays text-only)."""
    if not image:
        return ""
    if isinstance(image, str):
        image = Image.open(image).convert("RGB")
    proc, mdl = load_vl()
    messages = [{"role": "user", "content": [
        {"type": "image", "image": image},
        {"type": "text", "text": (prompt or "Describe this image.").strip()},
    ]}]
    text = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    from qwen_vl_utils import process_vision_info
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = proc(text=[text], images=image_inputs, videos=video_inputs,
                  padding=True, return_tensors="pt").to(mdl.device)
    with torch.inference_mode():
        gen = mdl.generate(**inputs, max_new_tokens=220, do_sample=False)
    trimmed = [out[len(inp):] for inp, out in zip(inputs.input_ids, gen)]
    decoded = proc.batch_decode(trimmed, skip_special_tokens=True,
                                clean_up_tokenization_spaces=False)
    return strip_think((decoded[0] if decoded else "").strip())


# --- Texture Lab GPU: Pony Diffusion V6 XL + structured VL vision -------------
# Added for the VCS Texture Lab so garment/material generation and outfit
# reading run here on ZeroGPU, not Jason's 4 GB local card (which times out) and
# not paid HF Inference (402). Lazy-loaded: the chat / Stage-4 / describe paths
# above are untouched until these two endpoints are actually called.
PONY_MODEL = os.environ.get("ALPECCA_TEXTURE_MODEL", "Bakanayatsu/Pony-Diffusion-V6-XL-for-Anime")
PONY_QUALITY = os.environ.get(
    "ALPECCA_PONY_QUALITY",
    "score_9, score_8_up, score_7_up, source_anime, masterpiece, best quality, ",
)
PONY_NEG = (
    "score_6, score_5, score_4, source_pony, source_furry, worst quality, low quality, "
    "blurry, jpeg artifacts, watermark, signature, text, logo, realistic, 3d render, photo, "
    "extra limbs, deformed, bad anatomy"
)
VJSON_MODEL = os.environ.get("ALPECCA_VJSON_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")

_pony_t2i = None
_pony_i2i = None
_vj_proc = None
_vj_model = None


def _b64_to_rgb(b64: str) -> Image.Image | None:
    if not b64:
        return None
    b64 = b64.strip()
    if b64.startswith("data:") and "," in b64:
        b64 = b64.split(",", 1)[1]
    try:
        return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    except Exception:
        return None


def _rgb_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _split_b64(joined: str) -> list[Image.Image]:
    out: list[Image.Image] = []
    for part in (joined or "").split("|||"):
        img = _b64_to_rgb(part)
        if img is not None:
            out.append(img)
    return out


def load_pony_t2i():
    global _pony_t2i
    if _pony_t2i is None:
        from diffusers import StableDiffusionXLPipeline

        pipe = StableDiffusionXLPipeline.from_pretrained(
            PONY_MODEL, torch_dtype=torch.float16, use_safetensors=True
        )
        pipe.set_progress_bar_config(disable=True)
        _pony_t2i = pipe.to("cuda")
    return _pony_t2i


def load_pony_i2i():
    global _pony_i2i
    if _pony_i2i is None:
        from diffusers import StableDiffusionXLImg2ImgPipeline

        base = load_pony_t2i()
        _pony_i2i = StableDiffusionXLImg2ImgPipeline(**base.components)
        _pony_i2i.set_progress_bar_config(disable=True)
    return _pony_i2i


@spaces.GPU(duration=120)
def texture(
    prompt: str,
    negative_prompt: str = "",
    init_image_b64: str = "",
    strength: float = 0.72,
    steps: float = 28,
    guidance: float = 7.0,
    width: float = 1024,
    height: float = 1024,
    seed: float = 0,
) -> str:
    """Generate one anime texture/garment image with Pony V6 XL. With
    init_image_b64 -> img2img off it, else txt2img. Returns a base64 PNG."""
    full_prompt = PONY_QUALITY + (prompt or "").strip()
    neg = (negative_prompt or "").strip() or PONY_NEG
    seed_i = int(seed) if int(seed) else 12345
    generator = torch.Generator("cuda").manual_seed(seed_i)
    w, h = int(width), int(height)
    init = _b64_to_rgb(init_image_b64)
    if init is not None:
        pipe = load_pony_i2i()
        init = init.resize((w, h), Image.Resampling.LANCZOS)
        result = pipe(
            prompt=full_prompt,
            negative_prompt=neg,
            image=init,
            strength=float(strength),
            num_inference_steps=int(steps),
            guidance_scale=float(guidance),
            generator=generator,
        )
    else:
        pipe = load_pony_t2i()
        result = pipe(
            prompt=full_prompt,
            negative_prompt=neg,
            width=w,
            height=h,
            num_inference_steps=int(steps),
            guidance_scale=float(guidance),
            generator=generator,
        )
    return _rgb_to_b64(result.images[0])


def load_vjson():
    global _vj_proc, _vj_model
    if _vj_proc is None:
        from transformers import AutoProcessor

        _vj_proc = AutoProcessor.from_pretrained(VJSON_MODEL, trust_remote_code=True)
    if _vj_model is None:
        from transformers import Qwen2_5_VLForConditionalGeneration

        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        _vj_model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            VJSON_MODEL,
            torch_dtype=dtype,
            device_map="auto",
            trust_remote_code=True,
            low_cpu_mem_usage=True,
        ).eval()
    return _vj_proc, _vj_model


def _parse_json_object(text: str) -> dict[str, Any]:
    text = strip_think(text)
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    return {"raw": text}


@spaces.GPU(duration=60)
def vision_json(image_b64: str, system: str = "", prompt: str = "Describe this image.") -> str:
    """Read one or more images (base64, joined by '|||') and return a strict
    JSON string. Used for VCS outfit extraction and the anime-deviation guard."""
    imgs = _split_b64(image_b64)
    content: list[dict[str, Any]] = [{"type": "image", "image": im} for im in imgs]
    instruction = ((system or "").strip() + "\n\n" + (prompt or "").strip()).strip()
    instruction += "\n\nRespond with a single valid JSON object and nothing else."
    content.append({"type": "text", "text": instruction})
    messages = [{"role": "user", "content": content}]
    proc, mdl = load_vjson()
    text = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    from qwen_vl_utils import process_vision_info

    image_inputs, video_inputs = process_vision_info(messages)
    inputs = proc(
        text=[text], images=image_inputs, videos=video_inputs, padding=True, return_tensors="pt"
    ).to(mdl.device)
    with torch.inference_mode():
        gen = mdl.generate(**inputs, max_new_tokens=768, do_sample=False)
    trimmed = [out[len(inp):] for inp, out in zip(inputs.input_ids, gen)]
    decoded = proc.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)
    return json.dumps(_parse_json_object(decoded[0] if decoded else ""))


with gr.Blocks(title="Alpecca ZeroGPU") as demo:
    gr.Markdown("# Alpecca ZeroGPU")
    with gr.Tab("Deep thought"):
        system_prompt = gr.Textbox(label="system_prompt", lines=8)
        user_msg = gr.Textbox(label="user_msg", lines=3)
        history_json = gr.Textbox(label="history_json", lines=4, value="[]")
        reply = gr.Textbox(label="reply", lines=8)
        gr.Button("Run deep tier", variant="primary").click(
            fn=chat,
            inputs=[system_prompt, user_msg, history_json],
            outputs=reply,
            api_name="chat",
        )
    with gr.Tab("Stage 4 tile worker"):
        gr.Markdown(
            "Generate one native 4K Stage 4 tile from the Hugging Face art queue and upload it back to the dataset. "
            "Run offsets 0-15 first for the idle eye 16-sector proof."
        )
        hf_path = gr.Textbox(label="HF JSONL job path", value=DEFAULT_STAGE4_HF_PATH, lines=2)
        offset = gr.Number(label="Job offset", value=0, precision=0, minimum=0)
        output_prefix = gr.Textbox(label="HF output prefix", value=DEFAULT_STAGE4_OUTPUT_PREFIX, lines=1)
        tile_model = gr.Textbox(label="Tile model", value=DEFAULT_TILE_MODEL, lines=1)
        render_size = gr.Number(label="Render size", value=1536, precision=0, minimum=1024, maximum=4096)
        steps = gr.Slider(label="Steps", minimum=12, maximum=40, value=24, step=1)
        guidance = gr.Slider(label="Guidance", minimum=3.0, maximum=10.0, value=7.0, step=0.25)
        seed = gr.Number(label="Seed", value=1704, precision=0)
        strength = gr.Slider(label="Image guidance strength", minimum=0.25, maximum=0.85, value=0.52, step=0.01)
        tile_result = gr.Textbox(label="Result", lines=14)
        gr.Button("Generate one Stage 4 tile", variant="primary").click(
            fn=generate_stage4_tile,
            inputs=[hf_path, offset, output_prefix, tile_model, render_size, steps, guidance, seed, strength],
            outputs=tile_result,
            api_name="generate_stage4_tile",
        )
    with gr.Tab("Vision"):
        gr.Markdown("Cloud vision: describe an image (offloads the VL model to the Space GPU).")
        v_image = gr.Image(label="image", type="filepath")
        v_prompt = gr.Textbox(label="prompt", lines=2, value="Describe this image.")
        v_out = gr.Textbox(label="description", lines=6)
        gr.Button("Describe", variant="primary").click(
            fn=describe,
            inputs=[v_image, v_prompt],
            outputs=v_out,
            api_name="vision",
        )
    with gr.Tab("Texture Lab"):
        gr.Markdown("Pony Diffusion V6 XL anime texture / garment generation (base64 in/out).")
        t_prompt = gr.Textbox(label="prompt", lines=3)
        t_neg = gr.Textbox(label="negative_prompt", lines=2)
        t_init = gr.Textbox(label="init_image_b64 (blank = txt2img)", lines=2)
        t_strength = gr.Slider(0.2, 0.95, value=0.72, step=0.01, label="strength")
        t_steps = gr.Slider(10, 45, value=28, step=1, label="steps")
        t_guidance = gr.Slider(1.0, 12.0, value=7.0, step=0.25, label="guidance")
        t_w = gr.Number(label="width", value=1024, precision=0)
        t_h = gr.Number(label="height", value=1024, precision=0)
        t_seed = gr.Number(label="seed (0 = fixed)", value=0, precision=0)
        t_out = gr.Textbox(label="image_b64", lines=4)
        gr.Button("Generate texture", variant="primary").click(
            fn=texture,
            inputs=[t_prompt, t_neg, t_init, t_strength, t_steps, t_guidance, t_w, t_h, t_seed],
            outputs=t_out,
            api_name="texture",
        )
    with gr.Tab("Vision JSON"):
        gr.Markdown("Qwen2.5-VL structured read (outfit extract / anime-deviation guard).")
        vj_img = gr.Textbox(label="image_b64 (join multiple with |||)", lines=3)
        vj_sys = gr.Textbox(label="system", lines=4)
        vj_prompt = gr.Textbox(label="prompt", lines=3)
        vj_out = gr.Textbox(label="json", lines=8)
        gr.Button("Read", variant="primary").click(
            fn=vision_json,
            inputs=[vj_img, vj_sys, vj_prompt],
            outputs=vj_out,
            api_name="vision_json",
        )


if __name__ == "__main__":
    demo.launch()
