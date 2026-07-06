# Alpecca VRoid v11 --- 15-View Camera Matrix (Strict Gate)

This matrix is the strict visual gate for the v11 base-model pass.
Use it before every save decision in VRoid.

## View taxonomy

We evaluate 3 pitch tiers x 5 yaw sectors:

| Pitch tier | Angle intent |
| --- | --- |
| Low | Camera low and looking up toward model |
| Eye | Standard player eye-level |
| High | Camera high and looking down |

| Yaw sector | Direction |
| --- | --- |
| 0 | Front |
| 45 | Front-Right |
| 90 | Right |
| 135 | Back-Right |
| 180 | Back |

Mirrors are checked by continuing yaw sweep to the corresponding left-side angle.

## Required 15 checks

For each check, mark **PASS / REWORK** and note one fix sentence if failed.

### Low pitch (5)
- [ ] L0  -- Low + Front (0)
- [ ] L45 -- Low + Front-Right (45)
- [ ] L90 -- Low + Right (90)
- [ ] L135 -- Low + Back-Right (135)
- [ ] L180 -- Low + Back (180)

### Eye pitch (5)
- [ ] E0  -- Eye + Front (0)
- [ ] E45 -- Eye + Front-Right (45)
- [ ] E90 -- Eye + Right (90)
- [ ] E135 -- Eye + Back-Right (135)
- [ ] E180 -- Eye + Back (180)

### High pitch (5)
- [ ] H0  -- High + Front (0)
- [ ] H45 -- High + Front-Right (45)
- [ ] H90 -- High + Right (90)
- [ ] H135 -- High + Back-Right (135)
- [ ] H180 -- High + Back (180)

## Mirror readback after yaw sweep

- [ ] M90  -- Left-side mirror of right profile
- [ ] M45  -- Left-front mirror of front-right profile
- [ ] M135 -- Left-back mirror of back-right profile

Mirror checks must confirm:
- clip is left-side only and not mirrored to right,
- ahoge remains single/crown-anchored,
- silhouette depth remains readable.

## Gate policy

Save (in-place overwrite) is allowed only when:

- all 15 entries are pass,
- mirror checks are stable and symmetric enough for VRoid viewport,
- no leg/waist proportion drift,
- side and back-right body/hair depth stays alive,
- ahoge is a single curve in all tested poses,
- left clip remains left across mirror checks.

## Camera control targets (VRoid)

- Front: key 1
- Front-right: key 3 (or equivalent rotate offset)
- Right: key 4
- Back-right: rotate or key path toward 135
- Back: key 2
- Left-side mirrors: continue rotating with same orbit cadence

Use the same key cadence for Low/Eye/High passes to avoid angular mismatch.

## Optional extension

For future high-fidelity passes, add mirror-equivalent 16-angle sampling by
incrementing the yaw granularity to 22.5 deg steps after this matrix clears.
