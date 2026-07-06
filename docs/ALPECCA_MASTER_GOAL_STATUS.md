# Alpecca Master Goal Status

Last updated by `scripts/audit_alpecca_master_goal_contract.py`.

## Current Objective

Generate Alpecca's advanced 2D-in-3D source art library and continue the
recursive engagement system:

- 16 views per angle family.
- At least 186 billboard/source targets.
- More than 400 art pieces.
- 4K-8K source resolution.
- Hugging Face storage for generated/source art.
- Promptless recursive engagement with observation, memory, self-feedback, and
  safe next actions.

## Current Evidence

The Stage 4 queue contract passes:

- `596` source/billboard targets are queued.
- `6048` source-art jobs are queued.
- `35/35` action/camera groups have complete native 16-sector coverage.
- All queued jobs are exact `4096x4096` source tiles.
- Walk coverage includes `48` walk targets and `768` 16-frame walk pieces.
- Source/generated art storage policy is Hugging Face; Cloudflare is only for
  the app shell/runtime preview.
- Runtime policy blocks loose 4K browser loading.
- Recursive engagement scorecard is observable and evidence-first.

The latest walk-cycle reference lock is active:

- The attached walk-cycle 3D pose guide matches
  `data/alpecca_art_source/external_walk_cycle_references/walk_cycle_3d_pose_guide.jpg`
  by SHA-256 hash.
- `gen-0149` / `walk_low_s4` selects all `16` required frames.
- The exported tile prompts include the external walk guide,
  `docs/ALPECCA_STAGE4_WALK_CYCLE_POSE_LOCK.md`, white thigh-high stocking
  design-lock text, no baked halo/shadow rules, and true side-view body-depth
  requirements.
- `python scripts\audit_alpecca_stage4_walk_cycle_contract.py` passes with
  `48` walk targets, `768` walk art pieces, and `48` checked prompts.

The master goal is still incomplete:

- `rawStripCount = 0`
- `importedFrameTileCount = 0`
- `approvedSpritesheetCount = 0`

Latest ZeroGPU target attempt:

- Command:
  `python scripts\run_alpecca_stage4_zerogpu_target.py --target-id gen-0149 --out-root output/alpecca_stage4_tile_jobs/zerogpu_target_runs/gen-0149_walk_pose_guide --process-after`
- Result: stopped before generation because ZeroGPU quota was exhausted
  (`270s requested vs. 47s left`).
- Retry hint from Hugging Face: `21:45:20`.
- Generated count: `0`.
- Expected target frames still missing: `16/16`.

Current target-output audit:

```powershell
python scripts\audit_alpecca_stage4_target_run_status.py `
  --target-id gen-0149 `
  --out-root output\alpecca_stage4_tile_jobs\target_status\gen-0149_walk_pose_guide
```

Expected current result:

- `selectedJobCount: 16`
- `expectedFrameCount: 16`
- `completeSelection: true`
- `presentRepoFileCount: 0`
- `missingRepoFileCount: 16`
- `completeOutputs: false`

Current walk-batch supervisor audit:

```powershell
python scripts\supervise_alpecca_stage4_generation.py `
  --batch 2 `
  --action walk `
  --max-targets 48 `
  --out-root output\alpecca_stage4_tile_jobs\supervisor\walk_batch_status
```

Current result:

- `scannedTargetCount: 48`
- `completeTargetCount: 0`
- `incompleteTargetCount: 48`
- first missing target: `gen-0145` / `walk_low_s0`
- first missing target returned frames: `0/16`

Latest supervised generation attempt:

```powershell
python scripts\supervise_alpecca_stage4_generation.py `
  --batch 2 `
  --action walk `
  --max-targets 48 `
  --out-root output\alpecca_stage4_tile_jobs\supervisor\walk_batch_run_next `
  --run-next
```

Result: ZeroGPU stopped before generating because quota was exhausted. Hugging
Face reported `Try again in 21:40:08`.

## Next Required Step

Check walk-batch status before generating or processing:

```powershell
python scripts\supervise_alpecca_stage4_generation.py `
  --batch 2 `
  --action walk `
  --max-targets 48 `
  --out-root output\alpecca_stage4_tile_jobs\supervisor\walk_batch_status
```

Run the supervisor after Hugging Face ZeroGPU quota resets:

```powershell
python scripts\supervise_alpecca_stage4_generation.py `
  --batch 2 `
  --action walk `
  --max-targets 48 `
  --out-root output\alpecca_stage4_tile_jobs\supervisor\walk_batch_run_next `
  --run-next
```

Or check one target status directly before generating or processing:

```powershell
python scripts\audit_alpecca_stage4_target_run_status.py `
  --target-id gen-0149 `
  --out-root output\alpecca_stage4_tile_jobs\target_status\gen-0149_walk_pose_guide
```

Run the first complete 16-frame target pass for `gen-0149` after Hugging Face
ZeroGPU quota resets:

```powershell
python scripts\run_alpecca_stage4_zerogpu_target.py `
  --target-id gen-0149 `
  --out-root output/alpecca_stage4_tile_jobs/zerogpu_target_runs/gen-0149_walk_pose_guide `
  --process-after
```

If the target run generates, inspect the local QA previews. The 16 frames must
pass mechanical QA, design-lock QA, full target-frame coverage checks, and the
walk-cycle pose-lock before import/stitch/promotion. If ZeroGPU is blocked by
quota, the command writes a structured report with the retry hint.

If running on Colab or another local GPU worker instead of the ZeroGPU Space,
use:

```powershell
python scripts\run_alpecca_stage4_resumable_colab_worker.py `
  --hf-path stage4-tile-jobs/batch_02/tile_jobs_batch_02_chunk_001.jsonl `
  --target-id gen-0149 `
  --output-root output/alpecca_stage4_tile_jobs/target_runs/gen-0149 `
  --output-prefix stage4-worker-outputs/target-runs/gen-0149
```

The target-aware worker writes `tile_job_manifest_gen-0149.json`, selecting all
16 frames for the target. After the returned Hugging Face prefix contains all
target frames, run:

```powershell
python scripts\process_alpecca_stage4_returned_target.py `
  --manifest output/alpecca_stage4_tile_jobs/target_runs/gen-0149/tile_job_manifest_gen-0149.json `
  --prefix stage4-worker-outputs/target-runs/gen-0149 `
  --target-id gen-0149 `
  --out-root output/alpecca_stage4_tile_jobs/returned_targets `
  --apply-import --apply-stitch
```

That target-return step downloads the Hugging Face prefix, runs mechanical QA,
design-lock QA, full target-frame coverage checks, imports exact 4K alpha tiles,
stitches `incoming/raw_strip.png`, and renders a preview sheet only when all
gates pass.

## Audit Command

```powershell
python scripts\audit_alpecca_master_goal_contract.py
```

Expected current result:

- `queueContractPass: true`
- `completionPass: false`
- failed checks: `production_pixels_generated`,
  `approved_runtime_candidates`
