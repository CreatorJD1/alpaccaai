# Alpecca Stage 4 Walk Cycle Pose Lock

This lock turns the supplied 3D mannequin walk-cycle guide into a repeatable
Alpecca production-art contract. The guide is a mechanics reference only:
Alpecca's identity, outfit, proportions, and 5ft 7in adult body class still
come from `data/alpecca_art_source/ALPECCA_DESIGN_LOCK.md`.

## Reference

- Local guide: `data/alpecca_art_source/external_walk_cycle_references/walk_cycle_3d_pose_guide.jpg`
- Manifest: `data/alpecca_art_source/external_walk_cycle_references/manifest.json`

## 16-Frame Walk Phase Map

Every Stage 4 walk strip uses 16 frames per direction/sector. The cycle should
read as a grounded walking loop, not a run, shuffle, or repeated-pose flicker.

| Frame | Phase | Required motion note |
| --- | --- | --- |
| 0 | contact A | Front/support foot plants on the shared baseline; rear foot trails; body is full height. |
| 1 | down A | Weight settles onto support foot; pelvis drops subtly; no body compression. |
| 2 | passing A | Rear foot passes under the body; arms counter-swing; head height remains stable. |
| 3 | up A | Passing foot lifts forward; support heel begins to rise; stride stays modest. |
| 4 | contact B | Opposite foot plants on the baseline; first foot trails. |
| 5 | down B | Weight settles onto the opposite support foot with the same thigh width. |
| 6 | passing B | First foot passes under the body; arms counter-swing opposite frame 2. |
| 7 | up B | First foot lifts forward; support heel rises; body remains 5ft 7in standing class. |
| 8 | contact A in-between | Contact A returns with slight in-between variation, not a duplicated frame 0. |
| 9 | down A in-between | Weight settles with small cloth/hair follow-through, no height collapse. |
| 10 | passing A in-between | Passing pose is readable and not identical to frame 2. |
| 11 | up A in-between | Lift phase has a clear foot arc and stable foot baseline. |
| 12 | contact B in-between | Opposite contact returns with the same leg length and boot size. |
| 13 | down B in-between | Weight settles naturally; no wide stance or thickened thighs. |
| 14 | passing B in-between | Passing pose is readable and not identical to frame 6. |
| 15 | up B return | Lift phase anticipates frame 0 for a seamless loop without snapping. |

## Generation Rules

- Generate each 16-frame walk strip as one coherent motion family.
- Preserve the same bottom-center foot anchor in every frame.
- Keep both legs covered by white thigh-high stockings from upper thigh to boots.
- Do not repeat adjacent or alternating leg poses just to fill 16 frames.
- Do not widen thighs or shorten legs during movement.
- Do not make side sectors ultra-thin; side views need believable body depth.
- Use calm walking speed: modest stride, grounded foot contacts, natural weight transfer.
- Keep sector orientation stable: each view sector keeps its camera angle while the legs animate.

## QA Rules

A walk strip fails before runtime promotion if it shows:

- repeated leg positions that make the loop stutter,
- foot sliding across the shared baseline,
- random height/scale changes,
- running or dash energy during normal walking,
- bare legs or missing white thigh-high stockings,
- side views collapsed into a flat billboard,
- adjacent 16-sector views that do not change body volume or silhouette.
