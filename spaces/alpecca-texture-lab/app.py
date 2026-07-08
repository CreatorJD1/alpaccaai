from __future__ import annotations

# Alpecca Texture Lab - ZeroGPU worker.
#
# Two jobs, both on the free H200 slice (Jason's PRO ZeroGPU), so the local
# 4 GB card never has to run them:
#   * texture()     -- Pony Diffusion V6 XL (anime) txt2img / img2img for
#                      garment + flat-material texture generation.
#   * vision_json() -- Qwen2.5-VL for reading clothing off reference art and
#                      the anime-deviation guard, returned as strict JSON.
#
# Images cross the gradio API as base64 strings (multiple refs joined by
# "|||"), so the VCS backend can call this with plain httpx/gradio_client and
# no file handles. CUDA work happens only inside @spaces.GPU functions, which
# is the ZeroGPU contract.

import base64
import io
import json
import os
import re
from typing import Any

import gradio as gr
import spaces
import torch
from PIL import Image, ImageFilter

# Pony Diffusion V6 XL, anime-tuned full SDXL pipeline (Jason's pick). Override
# with TEXTURE_MODEL. Vision defaults to Qwen2.5-VL-7B (H200 handles it; far
# better structured extraction than the 3B the brain Space uses for captions).
TEXTURE_MODEL = os.environ.get("TEXTURE_MODEL", "Bakanayatsu/Pony-Diffusion-V6-XL-for-Anime")
VL_MODEL_ID = os.environ.get("VL_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")

# Pony V6 is trained on score tags; leading with them is what unlocks quality.
PONY_QUALITY = os.environ.get(
    "PONY_QUALITY",
    "score_9, score_8_up, score_7_up, source_anime, masterpiece, best quality, ",
)
DEFAULT_NEG = (
    "score_6, score_5, score_4, source_pony, source_furry, worst quality, low quality, "
    "blurry, jpeg artifacts, watermark, signature, text, logo, realistic, 3d render, photo, "
    "extra limbs, deformed, bad anatomy, "
    # Texture-mode: suppress Pony's strong pull toward drawing a character so the
    # output stays a flat garment/material texture, not a 1girl portrait.
    "1girl, 1boy, solo, person, human, character, face, portrait, head, eyes, "
    "body, hands, standing, full body, scenery, background, vignette, cast shadow"
)

_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)

_t2i = None
_i2i = None
_vl_proc = None
_vl_model = None


def _strip_think(text: str) -> str:
    cleaned = _THINK_RE.sub("", text).strip()
    return cleaned or text.strip()


def _b64_to_img(b64: str) -> Image.Image | None:
    if not b64:
        return None
    b64 = b64.strip()
    if b64.startswith("data:") and "," in b64:
        b64 = b64.split(",", 1)[1]
    try:
        return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    except Exception:
        return None


def _img_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _split_imgs(joined: str) -> list[Image.Image]:
    out: list[Image.Image] = []
    for part in (joined or "").split("|||"):
        img = _b64_to_img(part)
        if img is not None:
            out.append(img)
    return out


# --- Pony V6 XL texture generation -------------------------------------------
def _load_t2i():
    global _t2i
    if _t2i is None:
        from diffusers import StableDiffusionXLPipeline

        pipe = StableDiffusionXLPipeline.from_pretrained(
            TEXTURE_MODEL, torch_dtype=torch.float16, use_safetensors=True
        )
        pipe.set_progress_bar_config(disable=True)
        _t2i = pipe.to("cuda")
    return _t2i


def _load_i2i():
    global _i2i
    if _i2i is None:
        from diffusers import StableDiffusionXLImg2ImgPipeline

        base = _load_t2i()
        _i2i = StableDiffusionXLImg2ImgPipeline(**base.components)
        _i2i.set_progress_bar_config(disable=True)
    return _i2i


# IP-Adapter (SDXL): condition generation on a garment REFERENCE image, not just
# the text prompt. t2i/i2i share the UNet, so loading on either covers both. Lazy
# (only downloads the ~700 MB adapter on the first ref call) and defensive (a load
# failure falls back to plain generation instead of breaking the endpoint).
_ip_loaded = False
_ip_failed = False
IP_REPO = os.environ.get("IP_ADAPTER_REPO", "h94/IP-Adapter")
IP_WEIGHT = os.environ.get("IP_ADAPTER_WEIGHT", "ip-adapter_sdxl.bin")


def _ensure_ip_adapter(pipe) -> bool:
    global _ip_loaded, _ip_failed
    if _ip_failed:
        return False
    if not _ip_loaded:
        try:
            pipe.load_ip_adapter(IP_REPO, subfolder="sdxl_models", weight_name=IP_WEIGHT)
            _ip_loaded = True
        except Exception as e:
            print("IP-Adapter load failed, continuing without it:", repr(e)[:200])
            _ip_failed = True
            return False
    return True


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
    ref_image_b64: str = "",
    ip_scale: float = 0.6,
) -> str:
    """Generate one anime texture/garment image with Pony V6 XL. init_image_b64 ->
    img2img off it (else txt2img). ref_image_b64 (a garment/design reference), if
    given, conditions the fabric look via IP-Adapter. Returns a base64 PNG."""
    full_prompt = PONY_QUALITY + (prompt or "").strip()
    neg = (negative_prompt or "").strip() or DEFAULT_NEG
    seed_i = int(seed) if int(seed) else 12345
    gen = torch.Generator("cuda").manual_seed(seed_i)
    w, h = int(width), int(height)
    init = _b64_to_img(init_image_b64)
    ref_img = _b64_to_img(ref_image_b64)

    common = dict(
        prompt=full_prompt, negative_prompt=neg,
        num_inference_steps=int(steps), guidance_scale=float(guidance), generator=gen,
    )
    if init is not None:
        pipe = _load_i2i()
        init = init.resize((w, h), Image.Resampling.LANCZOS)
        call = dict(image=init, strength=float(strength), **common)
    else:
        pipe = _load_t2i()
        call = dict(width=w, height=h, **common)

    # IP-Adapter: reference-image conditioning when a ref is supplied; if the
    # adapter was loaded on a prior call, keep it neutral (scale 0) so restyle-only
    # calls are unaffected.
    if ref_img is not None and _ensure_ip_adapter(pipe):
        pipe.set_ip_adapter_scale(float(ip_scale))
        call["ip_adapter_image"] = ref_img
    elif _ip_loaded:
        pipe.set_ip_adapter_scale(0.0)
        call["ip_adapter_image"] = Image.new("RGB", (224, 224), (127, 127, 127))

    result = pipe(**call)
    return _img_to_b64(result.images[0])


# --- Qwen2.5-VL structured vision --------------------------------------------
def _load_vl():
    global _vl_proc, _vl_model
    if _vl_proc is None:
        from transformers import AutoProcessor

        _vl_proc = AutoProcessor.from_pretrained(VL_MODEL_ID, trust_remote_code=True)
    if _vl_model is None:
        from transformers import Qwen2_5_VLForConditionalGeneration

        _vl_model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            VL_MODEL_ID,
            torch_dtype=torch.float16,
            device_map="auto",
            trust_remote_code=True,
            low_cpu_mem_usage=True,
        ).eval()
    return _vl_proc, _vl_model


def _parse_json_object(text: str):
    """Return the first JSON object OR array in the text (VL models often reply
    with a bare array for lists like garments). Falls back to {"raw": text}."""
    text = _strip_think(text)
    fence = re.search(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return {"raw": text}


@spaces.GPU(duration=60)
def vision_json(image_b64: str, system: str = "", prompt: str = "Describe this image.") -> str:
    """Read one or more images (base64, joined by '|||') and return a strict
    JSON string. Used for outfit extraction and the anime-deviation guard."""
    imgs = _split_imgs(image_b64)
    content: list[dict[str, Any]] = [{"type": "image", "image": im} for im in imgs]
    instruction = ((system or "").strip() + "\n\n" + (prompt or "").strip()).strip()
    instruction += "\n\nRespond with a single valid JSON object and nothing else."
    content.append({"type": "text", "text": instruction})
    messages = [{"role": "user", "content": content}]
    proc, mdl = _load_vl()
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


# --- ControlNet UV-lock: bold/high-denoise texturing that stays on the panel ----
# structure. The plain /texture path must keep denoise low or it drifts off the
# UV islands; here a canny ControlNet holds the panel + seam edges so we can crank
# strength for real new patterns/fabric while staying aligned. Shares the base
# UNet/VAE with the Pony pipes. Lazy + defensive (falls back to plain img2img).
_cn_pipe = None
_cn_failed = False
CN_MODEL = os.environ.get("CONTROLNET_MODEL", "xinsir/controlnet-canny-sdxl-1.0")


def _load_cn_pipe():
    global _cn_pipe, _cn_failed
    if _cn_failed:
        return None
    if _cn_pipe is None:
        try:
            from diffusers import ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline
            base = _load_t2i()
            cn = ControlNetModel.from_pretrained(CN_MODEL, torch_dtype=torch.float16)
            _cn_pipe = StableDiffusionXLControlNetImg2ImgPipeline(
                vae=base.vae, text_encoder=base.text_encoder, text_encoder_2=base.text_encoder_2,
                tokenizer=base.tokenizer, tokenizer_2=base.tokenizer_2, unet=base.unet,
                scheduler=base.scheduler, controlnet=cn, feature_extractor=None, image_encoder=None,
            ).to("cuda")
            _cn_pipe.set_progress_bar_config(disable=True)
        except Exception as e:
            print("ControlNet load failed, falling back to plain img2img:", repr(e)[:200])
            _cn_failed = True
            return None
    return _cn_pipe


def _canny_from(img: Image.Image) -> Image.Image:
    """Structure map via PIL edges (no opencv dep) - panel/seam outlines as the
    ControlNet conditioning image."""
    g = img.convert("L").filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(3))
    return Image.merge("RGB", (g, g, g))


@spaces.GPU(duration=150)
def texture_cn(
    prompt: str,
    negative_prompt: str = "",
    init_image_b64: str = "",
    control_image_b64: str = "",
    strength: float = 0.7,
    cn_scale: float = 0.55,
    steps: float = 30,
    guidance: float = 7.0,
    width: float = 1024,
    height: float = 1024,
    seed: float = 0,
) -> str:
    """Structure-locked texturing: img2img off the atlas + a canny ControlNet on
    the panel edges, so a HIGH strength paints bold new fabric that still lands
    inside the UV islands. control_image_b64 (if given) is the structure map, else
    it's derived from the init. Returns a base64 PNG."""
    full_prompt = PONY_QUALITY + (prompt or "").strip()
    neg = (negative_prompt or "").strip() or DEFAULT_NEG
    gen = torch.Generator("cuda").manual_seed(int(seed) if int(seed) else 12345)
    w, h = int(width), int(height)
    init = _b64_to_img(init_image_b64) or Image.new("RGB", (w, h), (127, 127, 127))
    init = init.resize((w, h), Image.Resampling.LANCZOS)
    ctrl = _b64_to_img(control_image_b64) or _canny_from(init)
    ctrl = ctrl.resize((w, h), Image.Resampling.LANCZOS)

    pipe = _load_cn_pipe()
    if pipe is None:
        fallback = _load_i2i()
        result = fallback(
            prompt=full_prompt, negative_prompt=neg, image=init, strength=float(strength),
            num_inference_steps=int(steps), guidance_scale=float(guidance), generator=gen,
        )
        return _img_to_b64(result.images[0])

    result = pipe(
        prompt=full_prompt, negative_prompt=neg, image=init, control_image=ctrl,
        strength=float(strength), controlnet_conditioning_scale=float(cn_scale),
        num_inference_steps=int(steps), guidance_scale=float(guidance), generator=gen,
    )
    return _img_to_b64(result.images[0])


with gr.Blocks(title="Alpecca Texture Lab GPU") as demo:
    gr.Markdown(
        "# Alpecca Texture Lab - ZeroGPU\n"
        "Pony Diffusion V6 XL (anime textures) + Qwen2.5-VL (outfit read / guard) on the H200."
    )
    with gr.Tab("Texture"):
        t_prompt = gr.Textbox(label="prompt", lines=3)
        t_neg = gr.Textbox(label="negative_prompt", lines=2)
        t_init = gr.Textbox(label="init_image_b64 (blank = txt2img)", lines=2)
        t_strength = gr.Slider(0.2, 0.95, value=0.72, step=0.01, label="strength")
        t_steps = gr.Slider(10, 45, value=28, step=1, label="steps")
        t_guidance = gr.Slider(1.0, 12.0, value=7.0, step=0.25, label="guidance")
        t_w = gr.Number(label="width", value=1024, precision=0)
        t_h = gr.Number(label="height", value=1024, precision=0)
        t_seed = gr.Number(label="seed (0 = fixed)", value=0, precision=0)
        t_ref = gr.Textbox(label="ref_image_b64 (garment reference for IP-Adapter)", lines=2)
        t_ipscale = gr.Slider(0.0, 1.0, value=0.6, step=0.05, label="ip_scale")
        t_out = gr.Textbox(label="image_b64", lines=4)
        gr.Button("Generate texture", variant="primary").click(
            texture,
            [t_prompt, t_neg, t_init, t_strength, t_steps, t_guidance, t_w, t_h, t_seed, t_ref, t_ipscale],
            t_out,
            api_name="texture",
        )
    with gr.Tab("Texture CN (UV-lock)"):
        gr.Markdown("Structure-locked bold texturing - canny ControlNet holds the panel edges so high strength stays on the UV.")
        c_prompt = gr.Textbox(label="prompt", lines=3)
        c_neg = gr.Textbox(label="negative_prompt", lines=2)
        c_init = gr.Textbox(label="init_image_b64 (the atlas)", lines=2)
        c_ctrl = gr.Textbox(label="control_image_b64 (blank = canny of init)", lines=2)
        c_strength = gr.Slider(0.3, 0.95, value=0.7, step=0.01, label="strength")
        c_cnscale = gr.Slider(0.0, 1.5, value=0.55, step=0.05, label="cn_scale")
        c_steps = gr.Slider(10, 45, value=30, step=1, label="steps")
        c_guidance = gr.Slider(1.0, 12.0, value=7.0, step=0.25, label="guidance")
        c_w = gr.Number(label="width", value=1024, precision=0)
        c_h = gr.Number(label="height", value=1024, precision=0)
        c_seed = gr.Number(label="seed (0 = fixed)", value=0, precision=0)
        c_out = gr.Textbox(label="image_b64", lines=4)
        gr.Button("Generate (UV-lock)", variant="primary").click(
            texture_cn,
            [c_prompt, c_neg, c_init, c_ctrl, c_strength, c_cnscale, c_steps, c_guidance, c_w, c_h, c_seed],
            c_out,
            api_name="texture_cn",
        )
    with gr.Tab("Vision JSON"):
        v_img = gr.Textbox(label="image_b64 (join multiple with |||)", lines=3)
        v_sys = gr.Textbox(label="system", lines=4)
        v_prompt = gr.Textbox(label="prompt", lines=3)
        v_out = gr.Textbox(label="json", lines=8)
        gr.Button("Read", variant="primary").click(
            vision_json, [v_img, v_sys, v_prompt], v_out, api_name="vision_json"
        )


if __name__ == "__main__":
    demo.launch()
