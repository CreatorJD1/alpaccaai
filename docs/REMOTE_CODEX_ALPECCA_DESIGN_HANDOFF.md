# Remote Codex Handoff: Alpecca Character Design

Prepared: **2026-07-17**  
Coordinator repository: `C:\Users\Jason\Documents\GitHub\alpaccaai`  
Coordinator branch at preparation: `codex/voice-session-audio-normalization`  
Coordinator HEAD at preparation: `0e1ea29ab86d166ee148745a440973bda8e6fed1`

## Read This First

The coordinator working tree contains substantial modified and untracked work
newer than the commit above. A new computer cannot see that source work merely
by cloning GitHub. Do not claim the remote checkout is current until CreatorJD
or the coordinator supplies a checkpoint branch/commit. Character-design
binaries are now versioned as external artifacts by the checked-in manifest
described below; they do not require a manual local-only package.

This lane is for **Alpecca's visual character design and VRM validation**. It
must not modify her brain, memories, Discord bridge, cloud continuity,
authentication, Android launcher, or Phase 9 perception controls.

## Paste Into The New Codex Session

```text
You are the remote Alpecca character-design lane. Work as a senior VRoid/VRM
1.0 character artist and technical avatar engineer. Read AGENTS.md,
PROJECT_CONTEXT.md, HANDOFF.md, and
docs/REMOTE_CODEX_ALPECCA_DESIGN_HANDOFF.md before editing anything.

Stay on an isolated branch named codex/remote-alpecca-design-v5. Do not start
Alpecca Core, Discord, the continuity lease, a cloud failover, or another
speaking instance. Do not edit server.py, config.py, alpecca/mind.py,
alpecca/discord_bridge.py, continuity code, Android code, or House HQ hot-path
files. Preserve Alpecca's locked design and VRM 1.0 format.

First inventory this computer's CPU, RAM, GPU/VRAM, free disk, installed VRoid
Studio/Blender versions, Git commit, and synchronized asset checksums. Report any
missing input rather than substituting an invented asset. Then work in this
order: baseline turntable, base model with clothing hidden (never deleted),
regular outfit textures and accessories, hair/face fidelity, VRM validation,
and a comparison report. Create a V5 candidate; never overwrite the live V4 or
promote it without CreatorJD approval. Commit only source-safe manifests,
scripts, and reports. Large art/VRM assets belong in the approved Hugging Face
art store or the explicit transfer package, never Cloudflare or GitHub.
```

## Non-Negotiable Character Lock

- Name and spelling: **Alpecca**.
- Adult character: **19 years old**, target height **1.70 m / 5 ft 7 in**.
- Runtime format: **VRM 1.0**, not VRM 0.x.
- Preserve her identity: pale silver-white hair, blue eyes, blue hair clip,
  ahoge, soft anime facial proportions, white/blue futuristic hoodie, black
  shorts, thigh-high socks, sneakers, and blue lanyard/ID accessory.
- Preserve the approved silhouette and age-appropriate adult proportions. Do
  not sexualize, radically restyle, or replace her recognizable face.
- Clothing can be hidden to inspect the base model. Do not delete clothing
  layers or destructively flatten the source project.
- Do not remove the hair-tip color. Restore the pale blue/lilac tip treatment
  if an export or texture pass loses it.
- Remove hoodie texture artifacts: fake button-like marks, the stray blue line
  near the open hem, mismatched collar graphics, seams, bleeding, and mirrored
  UV mistakes.
- Match the front hoodie graphics and both sleeves to the character sheet.
- The inner shirt remains its own clothing category.
- The lanyard must be a separate accessory. Prefer XWear; if the installed
  VRoid version cannot provide the required category, use a custom tie/accessory
  item or a purpose-built VRM 1.0 accessory mesh. Do not paint it permanently
  onto the shirt or hoodie.
- Hair, hoodie hem, and accessories need restrained physics. Preserve the live
  V4 design while avoiding clipping, explosive springs, or exaggerated motion.

## Authoritative Inputs

These large files remain outside Git history, but they are no longer
local-machine-only. Their locations and hashes are versioned in
`docs/manifests/alpecca_remote_design_v5.json` and their payloads are stored in
the private Hugging Face dataset `CREATORJD/alpecca-art-library` at revision
`e24f55fe76e1f1b59fe795532e00b7dfd8ad815e`:

| Purpose | Coordinator path | SHA-256 |
|---|---|---|
| Current live V4 body | `data/avatar/vrm/alpecca.vrm` | `0B6385DE90BE7C2401F94F8F2450C6A0E1198942BA11083E68A6C3233FDE27D3` |
| Pristine V4 archive | `data/avatar/vrm/alpecca_vroid_prototype_v4_20260709.vrm` | `12C5EA603422B388846C0BDE93847B6EBEED16EA6045568B709C5DE928810BC0` |
| Editable V13 VRoid source | `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v13_base_view_170cm.vroid` | `26DB8B01B7DF97E2B98F982DFFFBF03AD645ADD08EB6D54790CD16EF3623F35C` |
| Locked master sheet | `data/character/reference/master-character-sheet.png` | `5343196A5AD8E4C13E150E917C26A856880871C134B026C060A8667BA865E62F` |

Also synchronize or transfer, when available:

- `data/character/reference/ref-sheet/`
- `data/character/reference/live2d/`
- Any newer editable `.vroid` project created after the registered V13 source.
- Licensed accessory source files needed for the lanyard or hair clip, with
  their license/readme. Do not transfer or redistribute an asset if its license
  does not permit it.

The live and pristine V4 hashes intentionally differ. Treat the pristine file
as rollback evidence and `alpecca.vrm` as the current runtime body. Neither is
an editable VRoid source project.

## Design Asset Synchronization

Authenticate the new workstation to the private Hugging Face repository, then
restore and verify every registered design input:

```powershell
hf auth login
python scripts/sync_remote_design_assets.py --download
python scripts/sync_remote_design_assets.py --verify-local
```

The downloader is revision-pinned, rejects traversal, restores only manifest
paths under `data/`, writes atomically, and verifies byte count plus SHA-256.
Do **not** copy the entire `data/` directory: it currently contains roughly
16.56 GiB including memories, runtime state, logs, tokens, and private
continuity material. Never transfer `.env` files, browser profiles, Windows
Credential Manager records, tokens, passwords, SQLite memory databases,
Mindscape archives, or Discord credentials to the design computer.

## Remote Setup

1. Clone the repository and fetch all branches.
2. Confirm the checkpoint branch/commit supplied by the coordinator.
3. Create `codex/remote-alpecca-design-v5` from that checkpoint.
4. Record hardware and tools before downloading models or starting renders:

```powershell
Get-CimInstance Win32_ComputerSystem | Select-Object Model,TotalPhysicalMemory
Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion
Get-PSDrive -PSProvider FileSystem | Select-Object Name,Free,Used
git branch --show-current
git rev-parse HEAD
git status --short
```

5. Install only tools needed for the lane. VRoid Studio and a VRM 1.0-capable
   inspection/export workflow are required. Blender is optional for accessory
   mesh work; record its version and VRM add-on version if used.
6. Keep synchronized binary assets outside Git staging. Confirm with
   `git status --short` before every commit.

## Work Order

### 1. Establish Evidence

- Render or capture front, left, right, back, three-quarter, and close face
  views of the unchanged live V4.
- Capture a base-model pass with clothing layers disabled, not deleted.
- Capture a regular-outfit pass under neutral lighting.
- Use the same orthographic camera, pose, focal length, and lighting for every
  before/after comparison.
- List visible mismatches without claiming subjective “100%” equivalence.

### 2. Base Model

- Validate height, head/body proportion, shoulder width, hands, legs, facial
  proportions, eye placement, and neutral mouth closure.
- Preserve adult but youthful proportions appropriate to the locked sheet.
- Validate the blue eyes, lashes, eyebrows, nose/mouth placement, ahoge, hair
  volume, back silhouette, clip position, and hair-tip gradient.
- Do not use clothing geometry to hide base-mesh defects.

### 3. Regular Outfit

- Correct the hoodie front panel, zipper/opening, pocket edges, hem blocks,
  sleeve bands, sleeve graphics, and back mark against the reference sheet.
- Remove collar, button, blue-line, UV seam, and texture-bleed artifacts.
- Check every correction from front, both sides, back, arms down, and arms
  raised. A front-only texture fix is not accepted.
- Keep inner shirt, hoodie, shorts, socks, shoes, and accessories independently
  controllable where VRoid permits it.
- Build the lanyard and ID as a separate accessory with believable thickness,
  attachment, collision clearance, and restrained movement.

### 4. Export And Technical Validation

- Export a new candidate such as
  `alpecca_vroid_candidate_v5_<YYYYMMDD>.vrm`; do not overwrite either V4 file.
- Keep VRM 1.0 metadata, humanoid mapping, expressions, gaze, materials,
  spring-bone groups, and colliders valid.
- Confirm neutral eyes and mouth are not latched open.
- Confirm hair tips and outfit textures survive export.
- Check feet at ground level, normal joint orientation, and no inverted knees
  in a neutral pose. Animation/IK runtime changes belong to the coordinator
  unless explicitly reassigned.
- Run the repository validator when Node dependencies are available:

```powershell
node scripts/check_vrm_three.mjs <candidate.vrm> <absolute-node_modules-directory>
```

- If hoodie physics must be reinjected, operate on a fresh exported copy and
  write to a separate candidate location:

```powershell
python scripts/inject_hoodie_sway_physics.py --input <fresh-export.vrm> --output <candidate-with-sway.vrm>
```

Do not use `--allow-live-dir` during experimentation. Promotion is manual only.

### 5. Deliverables

Return all of the following:

- Candidate VRM and, when licensing permits, the editable `.vroid` project.
- Texture source files with layers preserved.
- Accessory source and license/readme.
- Before/after contact sheet covering the required angles.
- A short mismatch matrix with `fixed`, `improved`, `blocked`, or `unchanged`.
- Candidate SHA-256, file size, VRM version, height, spring-joint count,
  collider count, and validator output.
- `docs/REMOTE_ALPECCA_DESIGN_V5_REPORT.md` containing exact actions, tool
  versions, remaining defects, and promotion recommendation.
- A clean commit on `codex/remote-alpecca-design-v5` containing only safe code,
  manifests, and documentation. Store large art/VRM payloads in the approved
  Hugging Face art repository or return them through the explicit private asset
  package.

## Acceptance Gates

The remote lane is complete only when:

1. All received source hashes match.
2. The base model and regular outfit each have comparable multi-angle evidence.
3. No clothing layer was deleted merely to expose the base model.
4. Hair-tip color, hoodie front/sleeves, and lanyard are visibly present.
5. The listed collar/button/blue-line artifacts are absent from every relevant
   angle and arm pose.
6. The candidate loads as VRM 1.0 with valid humanoid, expression, gaze, spring,
   and material data.
7. No secret, memory, runtime database, or private continuity asset appears in
   the branch or transfer report.
8. CreatorJD reviews the evidence before the coordinator promotes any candidate
   to `data/avatar/vrm/alpecca.vrm`.

## Coordination Rules

- One speaking Alpecca instance only. The design computer must not acquire the
  continuity lease, connect Discord, publish mobile discovery, or start cloud
  failover.
- A static avatar preview is allowed if it does not start CoreMind or write
  runtime state.
- Never force-push, rewrite the coordinator branch, or merge into it directly.
- Rebase or cherry-pick only after the coordinator identifies the checkpoint.
- If a runtime integration change is needed in House HQ, describe it in the
  report or provide a separate patch. Do not edit `apps/house-hq/src/main.ts`
  or `styles.css` while those files remain active on the coordinator computer.
- Do not upload Alpecca art to Cloudflare. GitHub receives code and small
  manifests; Hugging Face is the designated art storage.
- Report uncertainty honestly. “Looks correct” is not a replacement for the
  required angle, checksum, and validator evidence.

## Return Message Format

```text
Branch / commit:
Checkpoint base:
Computer and tool versions:
Inputs received and hashes:
Base-model changes:
Regular-outfit changes:
Accessory changes:
VRM 1.0 validation:
Evidence locations:
Remaining mismatches or blockers:
Files safe to cherry-pick:
Large asset delivery location and hashes:
Promotion recommendation: reject / review / promote
```
