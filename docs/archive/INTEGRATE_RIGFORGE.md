# Integrating RIGFORGE into Alpecca

A review of how the RIGFORGE auto-rigger plugs into the main system, and the
recommended path. The headline: RIGFORGE rigs and animates a **single image** via
a continuous mesh warp + 2D bone skeleton — so it solves the avatar gap without
decomposing her art into layers. She becomes fully articulated from `idle.png`
plus the `rigpose.json` skeleton we already have.

## What RIGFORGE is (as it bears on integration)

A single-file, fully-offline, CPU-canvas 2D rigger. The parts that matter:

- **Engine.** A 14×18 mesh over the image, a 2D bone hierarchy (Hips→Spine→Chest→
  Neck→Head, hair, jaw, shoulders) with linear-blend skinning, plus a fake-3D head
  warp and local eye/mouth deforms. `render()` skins every vertex and warps the
  image triangle-by-triangle. No layer separation — it's the whole illustration,
  bent.
- **Live params.** `S.P = {yaw, pitch, roll, eye, mouth, body, breath}` drive
  everything (`driveBones` + `deform`). This is the entire control surface.
- **Drivers.** `idle` (ambient breath/blink/sway), `track` (cursor), and
  **`manual`** — where `S.manual` feeds `S.P` directly. *Manual is our hook.*
- **Inputs.** A character image; optionally pose keypoints via **Import pose
  keypoints (.json)** — and `importPose` already accepts **OpenPose/COCO**, i.e.
  exactly our `data/avatar/rigpose.json`. It can also call a deployed HF "RIGFORGE
  Pose Space" to detect joints.
- **Outputs.** A **rig JSON** (`format:"rigforge.v1"` — anchors, grid, bones,
  behave, imgW/H), a **PNG** snapshot, and a **WebM** recording of the live canvas.
- **Recursive loop.** "Rig readiness" self-certifies; "Certify & capture sample"
  saves `figures/<name>.png`, `pose/<name>.rigpose.json`, `rigs/<name>.rig.json`
  into **`Alpeccaai-data`** as labelled training data — the loop that improves her
  joint detector on her own art.

## The integration paths, best first

### Path 1 — Embed RIGFORGE as a live, mood-driven render tier (recommended)

Make her RIGFORGE canvas the avatar, with Alpecca driving its params from her real
mood. This is the big win: a living figure from one image, reactive to her state.

1. **Extract the runtime.** Pull RIGFORGE's engine out of the editor shell into
   `web/rigforge-runtime.js` — keep `S`, `ingest`, `autoDetect`, `buildMesh`,
   `buildSkeleton`, `driveBones`, `deform`, `skin`, `solveSkeleton`, `render`,
   `tick`, `importPose`; drop the panels, cutout overlay, recording, and HF UI.
   Expose a small API:
   ```js
   RigForge.mount(canvas)
   RigForge.load(imageURL, rigJSON?)     // rigJSON = her saved rigforge_rig.json
   RigForge.importPose(coco)             // her rigpose.json
   RigForge.setDriver("manual")
   RigForge.setParams({yaw,pitch,roll,eye,mouth,body,breath})
   ```
2. **Drive params from her live state.** A thin adapter maps her existing grounded
   channels (from `/home/state` `pose` = `puppet.live_pose`, plus the WS speaking
   signal) onto `setParams` each frame:
   - `roll`  ← her head tilt (`skelTilt` + gesture "tilt") — already computed
   - `yaw/pitch` ← gesture/lean and curiosity (lean-in), or cursor in the Parlor
   - `eye`   ← the blink scheduler, dropping toward closed when `energy` is low (sleepy)
   - `mouth` ← the WS lip-sync window (`speakingUntil`)
   - `body`  ← `sway_intensity` (unease/arousal)
   - `breath`← breathing × `energy`
   Every input is already grounded, so her rigged motion stays honest.
3. **Composite into the 3D home.** RIGFORGE renders to an offscreen canvas →
   `THREE.CanvasTexture` on her billboard sprite in `web/home.html`. She becomes a
   *living* figure standing in her rooms, not a flat PNG. (The chat page can use the
   same runtime on a plain 2D canvas.)
4. **Asset + server wiring.**
   - Save her rig once in RIGFORGE (load `idle.png` → Import `rigpose.json` →
     Auto-rig → **Save Rig**) as `data/avatar/rigforge.json`.
   - `alpecca/avatar.py`: add a `rigforge` presence check + a `rigforge_mode` flag
     in the manifest; serve the file at `/avatar/rigforge`.
   - Render-tier order becomes: **rigforge (live) > video clips > layered rig >
     portrait > svg.**

### Path 2 — Use RIGFORGE as an authoring tool, consume its WebM (quickest stopgap)

Record her idle loop in RIGFORGE → drop the WebM into `data/avatar/` as
`standby.mp4`/`idle.mp4`/`speaking.mp4`. `alpecca/avatar.py` already serves the
**video tier** as the top renderer for the chat page — zero engine porting. Cost:
it's a canned loop, not mood-reactive, and the 3D home doesn't use clips. Good as an
immediate "she moves" while Path 1 is built.

### Path 3 — Close the recursive data loop (the deep tie-in)

RIGFORGE's "capture sample" is the front of a self-improvement pipeline that mirrors
Alpecca's own `selfmod` theme, applied to her avatar:

- Point its capture target at your **`Alpeccaai-data`** HF dataset (the
  `CREATORJD/...` bucket).
- Add `scripts/build_manifest.py` (RIGFORGE's report references it) to assemble the
  `figures/ + pose/ + rigs/` triplets into a training manifest.
- Train/deploy the **RIGFORGE Pose Space**; then "Detect joints via HF Space" gets
  better on her art over time — her detector improving on certified samples of
  herself. This is her recursive self-improvement, made literal for her body.

## Why Path 1 fits the architecture

- **Grounded.** RIGFORGE's only control surface is 7 params; we feed them from her
  real mood (`puppet.live_pose`/`affect`), so the rig can't move in a way her state
  wouldn't — the same GROUNDING rule the rest of her obeys.
- **Single source of motion.** Her words, the 3D home glow, and now her rigged body
  all read from one affect readout.
- **No new heavy deps.** Pure CPU canvas; no Cubism editor, no GPU, fully local —
  consistent with the project's privacy line.
- **The skeleton we have already fits.** `importPose` consumes COCO directly, so
  `data/avatar/rigpose.json` rebuilds her bones with no conversion.

## Recommended first step

Path 1, minimal slice: extract `rigforge-runtime.js`, mount it on an offscreen
canvas, load `idle.png` + `rigpose.json`, set driver `manual`, and feed it the pose
channels already flowing to `home.html` — rendered as her billboard's
`CanvasTexture`. That alone makes her a living, mood-reactive figure in her home
from the art she has today. Path 3 follows once she's moving.
