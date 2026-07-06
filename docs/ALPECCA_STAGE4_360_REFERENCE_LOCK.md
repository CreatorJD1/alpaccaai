# Alpecca Stage 4 360 Reference Lock

Stage 4 must develop Alpecca's 2D-in-3D body rotation against the locked Google
Drive reference folder:

```text
https://drive.google.com/drive/folders/1TCaawZt7idE7ib-Kw8T-sq23z5cIXJmw
```

The Drive files are reference only. They define the expected turnaround behavior,
not Alpecca's identity. Alpecca's design still comes from
`data/alpecca_art_source/ALPECCA_DESIGN_LOCK.md`.

## Reference Files

The Google Drive folder currently contains these checked reference files:

| Drive file | Local reference | Use |
| --- | --- | --- |
| `aca09040d806c8ebbca0c3a6d3ce9577.gif` | `drive_360_reference_high_density_turnaround.gif` | High-density sector-to-sector body volume reference. |
| `image-processing20200913-22045-1aseb8q.gif` | `drive_360_reference_processing_turntable.gif` | Full turntable motion and silhouette reference. |
| `finally-found-the-time-to-make-a-full-turnaround-in-my-art-v0-yy9dcjbnkm6a1.jpg` | `drive_360_reference_turnaround_sheet.jpg` | Static multi-view turnaround sheet reference. |
| `bl3b3k4iim6a1.gif` | `drive_360_reference_small_rotation.gif` | Small rotation timing reference. |

Use `data/alpecca_art_source/external_360_references/external_360_reference_preview.jpg`
as the quick local preview when reviewing prompts or QA reports.

## Locked 360 Rules

- Use 16 native camera sectors: `s0` through `s15`.
- Each sector is a slightly different view around Alpecca's body.
- Do not solve rotation by scaling, narrowing, mirroring, or reusing one flat billboard.
- Do not fall back to a 5-view or 8-view approximation for production Stage 4 art.
- Adjacent sectors must change shoulder angle, hip angle, hair mass, leg spacing,
  stocking visibility, boot angle, side thickness, and back/side silhouette.
- Side sectors must keep believable adult body depth. Ultra-thin side views fail QA.
- White thigh-high stockings, black shorts, cream hoodie, blue lanyard, boots, hair
  clip, and 5ft 7in adult proportions must remain locked across every sector.
- No baked halo, floor shadow, glow smear, blue orbs, scene background, UI, text, or
  invented accessories in base-body frames.

## Drive Reference Behavior Checklist

Each approved 16-sector Alpecca slice must read like the Drive reference folder:

- `s0 -> s4 -> s8 -> s12 -> s15` must visibly rotate around the same body, not
  replay the same drawing at different widths.
- Side sectors must show body thickness, shoulder depth, arm overlap, hair depth,
  hip depth, and a real boot side profile.
- Adjacent sectors must change gradually enough that circling Alpecca feels like
  a smooth 2D turntable.
- Front, side, back, and diagonals must preserve the same adult 5ft 7in body
  height and the same slim thigh/stocking proportions.
- Mirroring is only a runtime fallback for non-production preview. Production
  Stage 4 360 art should prefer native sector art whenever a sector exists.
- Any sector that loses white thigh-high stockings, turns her legs into a narrow
  line, removes the black shorts, or invents a new outfit fails the batch.

## First Proof

The first production proof is the 16-sector eye-level idle still:

```text
output/alpecca_stage4_tile_jobs/first_slices/idle_eye_16sector_frame000_turnaround/tile_jobs_idle_eye_16sector_frame000_turnaround.jsonl
```

It contains 16 jobs, one per sector, at exact `4096 x 4096` PNG output size.
This proof must pass visual QA before full idle loops, walking cycles, talking
sets, overlays, rest states, or reaction sets are promoted.

## QA Requirement

After GPU worker outputs return, run:

```powershell
python scripts\run_alpecca_stage4_returned_slice_qa.py `
  --prefix stage4-worker-outputs/colab/idle_eye_16sector_frame000_turnaround `
  --out-root output\alpecca_stage4_tile_jobs\returned `
  --frame-index 0
```

The resulting contact sheet must show a real 16-sector turnaround. If Alpecca
still looks flat from the side, becomes ultra-thin, loses stockings, changes
height, or duplicates front/back designs, the slice is rejected and regenerated.

For an importable production slice, also run the guarded processor:

```powershell
python scripts\process_alpecca_stage4_returned_slice.py `
  --manifest output\alpecca_stage4_tile_jobs\first_slices\idle_eye_16sector_frame000_turnaround\tile_job_manifest.json `
  --outputs-root output\alpecca_stage4_tile_jobs\returned\stage4-worker-outputs_colab_idle_eye_16sector_frame000_turnaround `
  --apply-import `
  --apply-stitch
```

Draft outputs with `promotionStatus: draft-not-promotable` are allowed only as
visual probes. They must not be imported into runtime atlases.
