# Alpecca VRoid v11 Visual QA Checklist

Use this after each v11 save (or before save for pre-check) to keep the model
locked to the 2D references while staying in the base-model scope.

## Scope

This checklist validates only:
- body proportions,
- face silhouette proportions,
- hair volume/hue/gradient,
- ahoge geometry,
- left-side clip placement.

Do not use this pass to alter house runtime systems, AI behavior, or gameplay code.

## Mandatory visual checks

### 1) Global proportion checks
- Keep 170.2 cm baseline height lock intact.
- No torso-length/leg-length drift after edits.
- No body scale changes caused by hair/face tool edits.
- Feet and leg silhouette are not visually thinner than the current v10 baseline.

### 2) Head/face checks
- Crown-line sits natural on skull silhouette.
- Jaw edge remains consistent with previous accepted v11 face pass.
- Eye line remains adult anime proportional (not too close or dropped low).
- No unintended facial resets.

### 3) Hair mass checks (front and sides)
- Front view: hair reads as long, soft-volume mass.
- 45° view: side volume remains alive (not flat strip).
- Side view: no side-plane collapse.
- 3/4 view: back/side transition still has crown flow and no clipping into face.
- Back view: loose strands should taper naturally without "helmet" look.

### 4) Ahoge checks
- Single curved ahoge only.
- Ahoge remains attached to crown-left.
- Ahoge does not become twin tufts after side/back rotations.

### 5) Color/gradient checks
- Upper crown remains pale white-silver.
- Lower mass shows soft lavender-blue wash.
- Transition is smooth (no harsh hard-edge stripe).
- No orange/purple contamination.

### 6) Clip checks (critical identity cue)
- Blue bone/bow clip is on left hair region only.
- Clip is above earline and not centered.
- Clip remains on left across mirrored rotations.
- Clip is not mirrored by accident to right side.

## Gate matrix (pass/fail)

- [ ] L0  Low + Front (0°): front check passes.
- [ ] L45 Low + 45°: read still long/volumetric, no flattening.
- [ ] L90 Low + 90°: side read stays alive, no shell collapse.
- [ ] L135 Low + 135°: 3/4-back style read remains consistent.
- [ ] L180 Low + 180°: back read consistent, no clipping.
- [ ] E0  Eye + Front (0°): stable silhouette and anchor.
- [ ] E45 Eye + 45°: side-forward volume still stable.
- [ ] E90 Eye + 90°: side read still has hair mass depth.
- [ ] E135 Eye + 135°: 3/4 back remains clean, ahoge stays single.
- [ ] E180 Eye + 180°: back read stable.
- [ ] H0  High + Front (0°): top-front read remains stable.
- [ ] H45 High + 45°: down-angle 3/4 still clean.
- [ ] H90 High + 90°: high-side does not distort leg/body ratio.
- [ ] H135 High + 135°: high 3/4 back remains stable.
- [ ] H180 High + 180°: high back check passes with no shoulder drift.
- [ ] Mirror-left side check: side mirror remains on clip-left and ahoge-single.
- [ ] Mirror-left-forward check: mirrored front-right equivalent stays stable.
- [ ] Mirror-left-rear check: mirrored back-right equivalent stays stable.

All above true = save in-place and update manifest state.

## Post-save state command

```powershell
python scripts/update_v11_vroid_state.py --state base-gate-validated --notes "passboard + qa checklist all pass"
```

If any check fails:

```powershell
python scripts/update_v11_vroid_state.py --state base-gate-rework --notes "qa check fail: <specific fail>"
```
