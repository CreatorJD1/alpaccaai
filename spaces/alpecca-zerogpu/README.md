---
title: Alpecca ZeroGPU Deep Tier
emoji: 🧠
colorFrom: blue
colorTo: indigo
sdk: gradio
app_file: app.py
pinned: false
---

# Alpecca ZeroGPU

This Space is an optional free-cloud booster for Alpecca.

It is not her normal chat brain. Local Ollama should remain the reliable default
for live conversation. This Space handles only Alpecca's deep/self-work calls
when the main app is configured with:

```powershell
setx ALPECCA_DEEP_BACKEND zerogpu
setx ALPECCA_ZEROGPU_SPACE your-name/alpecca-zerogpu
setx ALPECCA_ZEROGPU_API /chat
```

The Gradio API accepts:

- `system_prompt`
- `user_msg`
- `history_json`

and returns one text reply.

## Stage 4 Tile Worker

The Space also exposes a `Stage 4 tile worker` tab and `/generate_stage4_tile`
API for the advanced 2D-in-3D Alpecca art pipeline.

It generates exactly one selected Stage 4 job offset at a time, then uploads the
result back to the Hugging Face dataset:

```text
CREATORJD/alpecca-art-library
```

Default first proof:

```text
stage4-tile-jobs/first_slices/idle_eye_16sector_frame000_turnaround/tile_jobs_idle_eye_16sector_frame000_turnaround.jsonl
```

Run offsets `0` through `15` first. Those are the native 16 camera sectors for
the eye-level idle still proof.

The default output prefix is intentionally a draft prefix:

```text
stage4-worker-outputs/zerogpu-drafts/idle_eye_16sector_frame000_turnaround
```

The default render size is `1536`, placed onto an exact `4096 x 4096` alpha
canvas and marked `draft-not-promotable`. Use this to preview direction,
design-lock, and silhouette before spending more GPU time. For a production
attempt, set render size to the job's exact size, currently `4096`.

The worker uses the Stage 4 seed canvas as image-to-image guidance and keeps the
text prompt compact. This is intentional: long Stage 4 prompt documents exceed
SDXL's text window and can cause the model to ignore Alpecca completely.

Important:

- This worker does not approve or ship art.
- Returned tiles still must pass local contact-sheet QA, 360-volume QA, tile QA,
  import, stitch, and visual review.
- Draft canvases are blocked by the local importer and cannot be promoted.
- Production tiles must match the job's exact native size and must not be marked
  `draft-not-promotable`.
- Generated/source art belongs on Hugging Face, not Cloudflare.
