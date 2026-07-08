# Alpecca Stage 4 Native 4K First Slice

This is the smallest production-art run that moves Stage 4 from queued prompts
to real native 4K frame tiles.

## Current Evidence

- Queue: `output/alpecca_stage4_tile_jobs/stage4_generation_queue.json`
- Targets: `596`
- Tile jobs: `6048`
- Required tile size: `4096 x 4096`
- Current production raw strips: `0`
- Current generated draft references: `1`
- Local GPU detected: NVIDIA GeForce RTX 3050 Laptop GPU
- Missing local package at last check: `diffusers`

## First Slice Target

Start with one frame from the first idle target:

```powershell
python scripts/run_alpecca_stage4_tile_worker.py `
  --jobs output/alpecca_stage4_tile_jobs/batch_01/tile_jobs_batch_01_chunk_000.jsonl `
  --offset 0 `
  --limit 1 `
  --output-root output/alpecca_stage4_tile_jobs/worker_outputs `
  --command "python scripts/generate_alpecca_stage4_tile_diffusers.py --prompt ""{prompt_file}"" --job-json ""{job_json}"" --seed ""{seed_canvas}"" --pose ""{pose_guides}"" --out ""{output}""" `
  --timeout 3600 `
  --fail-fast
```

The generator now refuses fake 4K by default. It must render natively at
`4096 x 4096`; it will not resize a smaller image and call it production art.

## Local Install If Needed

Use the project environment you intend to run generation from:

```powershell
pip install -r requirements-stage4-art.txt
```

The RTX 3050 Laptop GPU may not have enough VRAM for native SDXL at 4096. If it
fails locally, use a Colab/Hugging Face GPU worker with the same JSONL queue.

## Import And Stitch After Tile Generation

After a worker writes exact alpha PNGs under `output/alpecca_stage4_tile_jobs/worker_outputs`,
validate and import:

```powershell
python scripts/import_alpecca_stage4_tile_outputs.py `
  --manifest output/alpecca_stage4_tile_jobs/batch_01/tile_job_manifest.json `
  --outputs-root output/alpecca_stage4_tile_jobs/worker_outputs `
  --apply
```

Then stitch any target whose full frame set exists:

```powershell
python scripts/stitch_alpecca_stage4_tiles.py --batch 1 --apply
python scripts/audit_alpecca_stage4_art_status.py
```

## Non-Promotable Draft Mode

For visual experiments only:

```powershell
python scripts/generate_alpecca_stage4_tile_diffusers.py ... --render-size 1024 --allow-draft-upscale
```

Draft-upscaled outputs are marked `draft-not-promotable` in the sidecar and
should not be imported as production art.
