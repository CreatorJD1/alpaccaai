# Alpecca Stage 4 Walk Proof Notes

## Proof 4: `walk_low_s4_frame000_no_seed`

- Target: `gen-0149_frame_000`
- Matrix key: `walk_low_s4`
- Sector: `s4`, true right side profile
- Source job: `output/alpecca_stage4_tile_jobs/batch_02/tile_jobs_batch_02_chunk_001.jsonl`
- Returned tile: `output/alpecca_stage4_tile_jobs/returned_zerogpu_walk_proof4/stage4-worker-outputs/zerogpu-walk-proof4/walk_low_s4_frame000_no_seed/outputs/gen-0149/frame_000.png`
- QA report: `output/alpecca_stage4_tile_jobs/qa_zerogpu_walk_proof4/tile_visual_qa_report.json`
- Promotion status: `draft-not-promotable`

## Result

The no-seed policy fixed the previous four-character reference-sheet failure,
but base SDXL still failed the production target:

- It produced an opaque gray background instead of transparent/chroma-key art.
- It did not preserve Alpecca's locked outfit.
- It drifted toward abstract/mechanical concept art instead of her approved
  anime companion design.
- It is a 1536 proof placed into a 4096 canvas, so it is not promotable as
  native 4K source art.

## Pipeline Fix From This Proof

- Keep `seedConditionPolicy=reference-only-no-img2img-for-single-sprite-proof`
  for walk/standing proof jobs so reference boards do not become img2img sheets.
- Use an anime SDXL model for future proofs:
  `cagliostrolab/animagine-xl-4.0`.
- Prompt for a flat pure chroma key green `#00ff00` background so cleanup can
  remove it deterministically.
- Reject gray/white/opaque backgrounds, character sheets, and missing outfit
  parts before import/stitch.

## Next Proof

Run the same target with the anime model and chroma-key prompt:

```powershell
python scripts/run_alpecca_stage4_tile_worker.py `
  --hf-path stage4-tile-jobs/batch_02/tile_jobs_batch_02_chunk_001.jsonl `
  --offset 0 --limit 1 `
  --output-root output/alpecca_stage4_tile_jobs/worker_outputs/walk_low_s4_animagine_proof `
  --command "python scripts/generate_alpecca_stage4_tile_diffusers.py --prompt {prompt_file} --job-json {job_json} --out {output} --render-size 4096 --steps 28 --guidance 7.0"
```

On ZeroGPU, run the same job after quota reset using:

- HF path: `stage4-tile-jobs/batch_02/tile_jobs_batch_02_chunk_001.jsonl`
- Offset: `0`
- Model: `cagliostrolab/animagine-xl-4.0`
- Output prefix: `stage4-worker-outputs/zerogpu-walk-proof5/walk_low_s4_frame000_animagine`

## Proof 5: `walk_low_s4_frame000_animagine`

- Target: `gen-0149_frame_000`
- Matrix key: `walk_low_s4`
- Sector: `s4`, true right side profile
- Source job: `output/alpecca_stage4_tile_jobs/batch_02/tile_jobs_batch_02_chunk_001.jsonl`
- Returned tile: `output/alpecca_stage4_tile_jobs/returned_zerogpu_walk_proof5/stage4-worker-outputs/zerogpu-walk-proof5/walk_low_s4_frame000_animagine/outputs/gen-0149/frame_000.png`
- QA report: `output/alpecca_stage4_tile_jobs/qa_zerogpu_walk_proof5/tile_visual_qa_report.json`
- Model: `cagliostrolab/animagine-xl-4.0`
- Promotion status: `draft-not-promotable`

## Result

The anime model improved the biggest structural failure: it returned one
readable single-character anime sprite instead of a reference sheet or
mechanical concept form. It is still rejected for production:

- It used an opaque beige/tan background instead of pure chroma green or alpha.
- It touched the lower/right edge after draft placement, so the full body does
  not have enough safe margin for normalization.
- It drifted from Alpecca's identity: brown/red hair, wrong top/outfit, skirt or
  blouse-like silhouette, bare legs, and dark boots.
- It leaned/bent instead of matching the walk-cycle guide's upright side-contact
  pose with one planted support foot and one trailing rear foot.
- It is a 1536 proof placed into a 4096 canvas, so it remains a draft only.

## Pipeline Fix From This Proof

- Keep Animagine as the current open-source proof model because it is closer to
  the target anime sprite language than base SDXL.
- Move Alpecca's design-lock tags to the start of the prompt so the model sees
  the identity before action/camera text.
- Add explicit negatives for the drift seen in Proof 5: brown/red hair, skirt,
  blouse, bare legs, black boots, bent-over/crouching posture, and beige/tan
  backgrounds.
- Keep side-walk prompts anchored to the provided walk-cycle pose guide: upright
  torso, planted support foot, trailing rear foot, stable adult proportions, and
  slim consistent thighs.

## Next Proof

Run a design-lock proof against the same job:

- HF path: `stage4-tile-jobs/batch_02/tile_jobs_batch_02_chunk_001.jsonl`
- Offset: `0`
- Model: `cagliostrolab/animagine-xl-4.0`
- Output prefix: `stage4-worker-outputs/zerogpu-walk-proof6/walk_low_s4_frame000_designlock`
- Render size: `1536` for quota-safe proof, still non-promotable
- Steps: `20`
- Guidance: `7.5`
- Seed: `170408`

Use the repeatable proof runner:

```powershell
python scripts/run_alpecca_stage4_zerogpu_proof.py `
  --out-root output/alpecca_stage4_tile_jobs/zerogpu_proofs/proof6_live_attempt
```

If ZeroGPU quota is unavailable, the command writes a structured report with
`generation.status = blocked-zero-gpu-quota` and `quotaWaitHint`. When quota is
available, it downloads the returned Hugging Face prefix and runs the tile QA
automatically.

The QA now includes a coarse Alpecca design-lock probe. It blocks the observed
Proof 5 drift classes before import:

- `design-lock-hair-color-drift`
- `design-lock-missing-white-thigh-highs`
- `design-lock-bare-leg-drift`
- `design-lock-dark-boots-or-lower-outfit-drift`
