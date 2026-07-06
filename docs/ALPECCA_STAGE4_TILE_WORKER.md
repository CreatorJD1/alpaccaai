# Alpecca Stage 4 Tile Worker

Stage 4 is exported as a full queue of `6048` frame-tile jobs across `596`
matrix/overlay targets. Each job must produce one exact `4096 x 4096`
transparent PNG at:

```text
outputs/<targetId>/frame_000.png
```

The worker does not approve art. It only runs jobs and writes outputs. The normal importer, stitcher, and QA gates still decide what can become runtime art.

The 360-view art direction is locked in
`docs/ALPECCA_STAGE4_360_REFERENCE_LOCK.md`. Stage 4 must use 16 native sectors
`s0` through `s15` like the Google Drive turnaround reference, not a flat
billboard, 5-view shortcut, or 8-view approximation.

## Pull A Chunk From Hugging Face

```powershell
python scripts\run_alpecca_stage4_tile_worker.py `
  --hf-path stage4-tile-jobs/batch_01/tile_jobs_batch_01_chunk_000.jsonl `
  --output-root output\alpecca_stage4_tile_jobs\batch_01 `
  --limit 4
```

Without a generator command, this stages prompt/job files and writes a report only.

The master queue is:

```text
output/alpecca_stage4_tile_jobs/stage4_generation_queue.json
```

## First Production Slices

Before running the full `6048`-job queue, run these focused slices:

```text
stage4-tile-jobs/first_slices/idle_eye_16sector_frame000_turnaround/tile_jobs_idle_eye_16sector_frame000_turnaround.jsonl
```

This is the cheapest native 4K proof: `16` jobs, one eye-level idle frame for
each sector `s0` through `s15`. It should prove Alpecca has real 2D-in-3D body
volume while the player circles her.

After the still turnaround passes visual QA, run the complete idle loop:

```text
stage4-tile-jobs/first_slices/idle_eye_16sector_full_loop/tile_jobs_idle_eye_16sector_full_loop.jsonl
```

That slice is `128` jobs: `16` sectors x `8` idle frames. Only after that looks
right should the full queue scale up to walking, talking, overlays, rest, and
reaction batches.

## Attach A Generator

Set `ALPECCA_TILE_COMMAND` or pass `--command`. The command receives these template values:

```text
{prompt_file}
{job_json}
{output}
{seed_canvas}
{pose_guides}
{job_id}
{target_id}
{frame_index}
{matrix_key}
```

## First Open-Source Diffusers Adapter

The repo now includes a first-pass Diffusers tile generator:

```text
scripts/generate_alpecca_stage4_tile_diffusers.py
```

Install the art-generation dependencies in the GPU runtime:

```powershell
pip install -r requirements-stage4-art.txt
```

For Colab, install PyTorch using the Colab runtime defaults first, then install
the requirements above. The adapter uses a source frame from the Stage 4 seed
canvas, generates against the job prompt, removes a chroma-key background, and
writes exact `4096 x 4096` RGBA PNG tiles.

Production rule: the adapter defaults to native `4096`. It refuses to upscale a
smaller render and call it production art. `--allow-draft-upscale` exists only
for non-promotable visual tests.

Diffusers command:

```powershell
$env:ALPECCA_TILE_COMMAND='python scripts\generate_alpecca_stage4_tile_diffusers.py --prompt "{prompt_file}" --job-json "{job_json}" --seed "{seed_canvas}" --pose "{pose_guides}" --out "{output}"'

python scripts\run_alpecca_stage4_tile_worker.py `
  --hf-path stage4-tile-jobs/batch_01/tile_jobs_batch_01_chunk_000.jsonl `
  --output-root output\alpecca_stage4_tile_jobs\batch_01 `
  --limit 8 `
  --skip-existing
```

Useful knobs:

```powershell
$env:ALPECCA_TILE_MODEL="stabilityai/stable-diffusion-xl-base-1.0"
$env:ALPECCA_TILE_RENDER_SIZE="4096"
$env:ALPECCA_TILE_STEPS="28"
$env:ALPECCA_TILE_GUIDANCE="7.0"
$env:ALPECCA_TILE_STRENGTH="0.62"
$env:ALPECCA_TILE_MEMORY_MODE="low_vram"
$env:ALPECCA_TILE_ENABLE_ATTENTION_SLICING="1"
$env:ALPECCA_TILE_ENABLE_VAE_SLICING="1"
$env:ALPECCA_TILE_ENABLE_VAE_TILING="1"
$env:ALPECCA_TILE_ENABLE_XFORMERS="1"
```

Low-VRAM mode keeps the production requirement intact. It enables Diffusers
memory features when available -- model CPU offload, attention slicing, VAE
slicing/tiling, and optional xFormers -- but the output must still be a native
`4096 x 4096` PNG. If the GPU cannot complete native 4096, the worker should
fail or run a clearly marked draft. Do not promote a resized low-resolution
render as source art.

## Colab / Remote GPU Notebook

Use:

```text
notebooks/alpecca_stage4_tile_generation_colab.py
```

In Colab:

1. Switch runtime to GPU.
2. Set `HF_TOKEN` in Colab secrets or run `hf auth login`.
3. Run the preflight cell before generation.
4. Run the generation/upload cells only if preflight is not blocked.
5. Keep `JOB_LIMIT=16` for the first native 4K turnaround proof.
6. Inspect the uploaded worker report before raising the limit.

Preflight can also be run manually:

```powershell
python scripts\preflight_alpecca_stage4_tile_worker.py `
  --hf-path stage4-tile-jobs/first_slices/idle_eye_16sector_frame000_turnaround/tile_jobs_idle_eye_16sector_frame000_turnaround.jsonl `
  --limit 16
```

The preflight checks Hugging Face access, PyTorch/CUDA, Diffusers packages, the
selected job slice, native `4096 x 4096` requirements, and low-VRAM settings. A
GPU-memory warning is not always fatal, but a blocked preflight should be fixed
before starting a long generation run.

The notebook uses the resumable worker by default:

```powershell
python scripts\run_alpecca_stage4_resumable_colab_worker.py `
  --hf-path stage4-tile-jobs/first_slices/idle_eye_16sector_frame000_turnaround/tile_jobs_idle_eye_16sector_frame000_turnaround.jsonl `
  --output-prefix stage4-worker-outputs/colab/idle_eye_16sector_frame000_turnaround `
  --limit 16 `
  --upload-every 1
```

This runs one selected tile at a time and uploads the output root after each
tile. If Colab disconnects after sector `s7`, sectors `s0` through `s7` should
already be stored on Hugging Face. Re-run with the same command and
`--skip-existing` to continue.

The notebook uploads returned tiles and reports to:

```text
stage4-worker-outputs/colab/idle_eye_16sector_frame000_turnaround
```

inside the private Hugging Face dataset:

```text
CREATORJD/alpecca-art-library
```

## Pull Returned Remote Outputs

After Colab/HF uploads worker outputs:

```powershell
python scripts\download_alpecca_stage4_worker_outputs.py `
  --prefix stage4-worker-outputs/colab/batch_01_chunk_000
```

Then point QA/import at the printed `destinationRoot`.

For the first 16-sector proof, use the one-command returned-slice QA runner:

```powershell
python scripts\run_alpecca_stage4_returned_slice_qa.py
```

It downloads:

```text
stage4-worker-outputs/colab/idle_eye_16sector_frame000_turnaround
```

then runs both:

- `qa_alpecca_stage4_turnaround_outputs.py`
- `qa_alpecca_stage4_tile_outputs.py`

It still does not import, stitch, or approve art. It only reports whether the
returned slice is ready for human visual review.

This is only the first open-source generation adapter. If a stronger 4K/anime/reference-lock model is used later, keep the same worker contract: one exact alpha PNG per job, then importer, stitcher, visual QA, and Stage 5 compile.

## Preview / QA Returned Tiles

Run this before importing. It creates a mechanical QA report and contact-sheet previews over a checkerboard background:

```powershell
python scripts\qa_alpecca_stage4_tile_outputs.py `
  --manifest output\alpecca_stage4_tile_jobs\batch_01\tile_job_manifest.json `
  --outputs-root output\alpecca_stage4_tile_jobs\batch_01
```

The preview checks:

- exact tile size
- alpha channel presence
- non-empty alpha bounds
- cropped-edge risk
- foot baseline variance
- frame width/height variance
- a contact sheet for visual inspection

This gate still does not approve art. It only tells us whether a returned tile set is mechanically safe enough to inspect/import.

For the first 16-sector proof, also run the turnaround QA. This assembles
`s0` through `s15` together so flat billboard rotation, ultra-thin side views,
missing stockings, or baked halo/shadow artifacts are visible before import:

```powershell
python scripts\qa_alpecca_stage4_turnaround_outputs.py `
  --manifest output\alpecca_stage4_tile_jobs\first_slices\idle_eye_16sector_frame000_turnaround\tile_job_manifest.json `
  --outputs-root output\alpecca_stage4_tile_jobs\first_slices\idle_eye_16sector_frame000_turnaround `
  --out-root output\alpecca_stage4_tile_jobs\first_slices\idle_eye_16sector_frame000_turnaround\qa
```

The turnaround preview writes:

```text
turnaround_16_sector_qa.jpg
turnaround_16_sector_qa_report.json
turnaround_360_volume_report.json
```

`turnaround_360_volume_report.json` is generated by the returned-slice QA runner
and acts as a machine-readable silhouette gate. It checks for missing sectors,
repeated alpha silhouettes, too-little width change between sectors, ultra-thin
side views, and unstable foot baselines. It is not an art-quality judge by
itself, but a slice with `status: blocked` must not be imported or promoted.

Only continue to import after the turnaround report says
`ready-for-visual-review`, the volume report says `pass`, and the preview
visually passes the 360 body-volume/design-lock checklist.

## Validate And Import Returned Tiles

For the first still-turnaround proof, use the guarded processor:

```powershell
python scripts\process_alpecca_stage4_returned_slice.py `
  --manifest output\alpecca_stage4_tile_jobs\first_slices\idle_eye_16sector_frame000_turnaround\tile_job_manifest.json `
  --outputs-root output\alpecca_stage4_tile_jobs\returned\stage4-worker-outputs_colab_idle_eye_16sector_frame000_turnaround `
  --apply-import
```

This command runs the contact-sheet QA, 360-volume QA, and per-tile mechanical
QA first. It refuses to import missing, flat, ultra-thin, wrong-size, or
non-alpha sectors. For the first still proof it imports only the valid
`frame_000.png` tiles; it does not pretend those partial targets are ready to
stitch.

```powershell
python scripts\import_alpecca_stage4_tile_outputs.py `
  --manifest output\alpecca_stage4_tile_jobs\batch_01\tile_job_manifest.json `
  --outputs-root output\alpecca_stage4_tile_jobs\batch_01 `
  --apply
```

Only exact-size alpha PNG tiles are copied into the Stage 4 source tree.

## Stitch Ready Targets

```powershell
python scripts\stitch_alpecca_stage4_tiles.py --batch 1 --apply
```

Targets with all required frame tiles become `incoming/raw_strip.png`. They still need visual QA before promotion.

## Compile Runtime Atlases

After visual QA approves a target:

```powershell
python scripts\compile_alpecca_stage5_runtime_atlases.py --apply
```

Stage 5 compiles approved strips into runtime atlas folders. It must continue skipping unapproved or missing art.
