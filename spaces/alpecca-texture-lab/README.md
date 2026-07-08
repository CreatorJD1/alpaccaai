---
title: Alpecca Texture Lab GPU
emoji: paintbrush
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 5.9.1
app_file: app.py
pinned: false
short_description: Pony V6 XL + Qwen2.5-VL texture and vision on ZeroGPU
---

# Alpecca Texture Lab - ZeroGPU worker

The GPU worker for the VCS Texture Lab, so Jason's 4 GB local card does not have
to run material generation and the exhausted HF Inference path stays out of the
loop.

- **`/texture`** - Pony Diffusion V6 XL (anime), txt2img and img2img, for garment
  and flat-material texture generation. Base64 in, base64 PNG out.
- **`/texture_cn`** - Pony Diffusion V6 XL plus ControlNet UV-lock for bold,
  high-denoise texture changes that preserve atlas panel structure.
- **`/vision_json`** - Qwen2.5-VL, reads clothing from reference art and runs the
  anime-deviation guard, returned as strict JSON.

Runs on Jason's PRO ZeroGPU account. Not the production brain Space
(`CREATORJD/alpecca-zerogpu`) - this is the isolated, experimental texture path.
