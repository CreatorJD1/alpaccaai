# Alpecca Project Context

This is the canonical project context for coding agents working on Alpecca.
Read this before `AGENTS.md`, `CLAUDE.md`, `HANDOFF.md`, or implementation files.

## Identity

- User-facing name: **Alpecca**.
- Repo path may still say `alpaccaai`; do not rename broad repo paths unless asked.
- Alpecca is a local-first AI companion with an embodied interface, memory, mood, voice, perception, and bounded self-improvement.
- Be honest about capability: the goal is functional/cognitive/self-learning behavior as an engineered system, not claims of literal consciousness.
- Self-reports must be grounded in real state, memories, observations, or model uncertainty. Do not fabricate inner events.

## Application Surfaces

- **House HQ** is the main embodied interactive scaffold and primary 3D state interface.
- **Alpecca virtual app** is the secondary app surface for classic panels, chat, profile, voice, state, memory, journal, and tools.
- **Mindscape** is the soul/continuity/sustainability layer, intended as cloud/mobile fallback if a local device dies.
- These are one coherent Alpecca system, not separate products.

## Current AI Core Goal

Build Alpecca into a stronger companion by making the cognition loop real, observable, testable, and safe:

```text
observe -> interpret -> retrieve memory -> update self-state -> choose intent -> act/respond -> journal -> evaluate
```

Important current priorities:

- Natural replies through the live backend, not event echoes or copied user text.
- Stable local model path uses the currently approved Ollama model from `ALPECCA_MODEL`; do not revive retired legacy model paths.
- Voice should use her personality and modulation system, with Kokoro `af_heart` as the intended voice profile.
- Alpecca should initiate bounded observations/questions from real context, not spam logs or hallucinate events.
- Self-improvement should create evidence-backed proposals and require user approval before risky changes.

## Storage And Deployment

- **Do not upload Alpecca art to Cloudflare.**
- Cloudflare/R2 is only the lightweight static app shell and remote preview host.
- Hugging Face stores Alpecca art:
  - Private source/generated art archive: `CREATORJD/alpecca-art-library`
  - Public browser-safe runtime assets: `CREATORJD/alpecca-runtime-assets`
- Runtime art base:
  - `https://huggingface.co/datasets/CREATORJD/alpecca-runtime-assets/resolve/main/runtime-assets`
- Current Cloudflare shell preview:
  - `https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/house-hq`
- `scripts/prepare_house_hq_r2_static.py` excludes Alpecca art folders by default.
- `scripts/publish_alpecca_art_library_hf.py` syncs art to Hugging Face.

## Alpecca Design Lock

Never change Alpecca's core design while generating or repairing art. The canonical design lock lives at:

- `data/alpecca_art_source/ALPECCA_DESIGN_LOCK.md`
- `data/alpecca_art_source/design_lock_references/`

Required design elements:

- Adult anime woman proportions; stable standing height and slim leg silhouette.
- Long white-silver hair with pale lavender-blue lower accents.
- One curved ahoge/cowlick.
- Small blue X/bow hair clip.
- Blue eyes and soft anime face.
- Oversized warm ivory/cream hoodie-jacket with pale blue trim.
- White inner shirt.
- Blue lanyard and Alpecca ID badge.
- Black high-waist shorts.
- White full-length thigh-high stockings.
- Black right-leg thigh strap.
- Chunky cream/white boots with pale blue soles/details.
- Black sleeve tech patch and blue zipper/side tags where visible.

Reject generated art that:

- Removes or shortens the thigh-high stockings.
- Drops the right-leg thigh strap.
- Changes boots into sneakers.
- Adds blue orbs, animal ears, round discs, or invented accessories.
- Changes hair, face, hoodie, shorts, lanyard, or body proportions.
- Crops feet, hair, jacket, hands, or boots.

The halo is a separate UI/effect layer. Do not bake large halos or blue orbs into body frames.

## Animation Library Plan

The advanced 2D-in-3D goal is staged, not one giant dump.

Current foundation:

- 15-state view matrix:
  - Vertical tiers: `low`, `eye`, `high`
  - Relative yaw tiers: `front`, `frontDiag`, `side`, `backDiag`, `back`
  - Left-side views may mirror matching right-side assets when approved.
- Stage 4 plan currently has 181 strip targets and 1848 planned art pieces/frame slots.
- Runtime must load compiled atlases, not hundreds of loose source images.
- Source/generated library can grow toward 400+ art pieces and beyond, but only approved runtime atlases should ship to the browser.

Implementation stage order:

1. Source library and manifest.
2. Runtime matrix adapter.
3. Reference boards and design lock.
4. Generate complete strips by action/view batch.
5. Compile approved runtime atlases.
6. Layered runtime: body matrix, expression overlay, mouth/eye overlay, contact shadow/depth proxy.
7. 3D integration: occlusion, grounded shadows, optional normal maps.
8. QA gates: feet grounded, no scale shifts, correct facing, no design drift.

## House HQ Accommodation

House HQ must become an embodied stage for Alpecca, not a cluttered maze.

Design rules:

- Clear walkable lanes and stage pads in each room.
- Door frames, not doors, unless specifically requested otherwise.
- Furniture and terminals near room edges.
- One main performance pad per room.
- Rest nook must support real sit/sleep/rest animations; she should not sleep while standing.
- Player approach should not shrink Alpecca or alter her scale.
- Use room/stage QA overlays to inspect walkable areas, portals, stage pads, and occlusion.

Room meanings:

- HQ Control: core status, command, live connection.
- Library: memories, journal, references.
- Observatory: perception, screen/media review, creative critique.
- Workshop: improvement queue, experiments, prototypes.
- Self Design / Studio: avatar, expression, mirror, identity.
- Rest Nook: recovery/sleep state.

## Runtime And Important Files

- `server.py`: FastAPI/WebSocket backend, app routes, TTS endpoints.
- `alpecca/mind.py`: core loop and model fallback behavior.
- `alpecca/cognition.py`: observations, intent, proposals, behavior review.
- `alpecca/tts.py`: Kokoro/OpenTTS/voice behavior.
- `alpecca/prompts.py`: personality, grounding, prompt assembly.
- `apps/house-hq/src/main.ts`: Three.js House HQ, Alpecca NPC, profile chat, backend bridge, asset loading.
- `apps/house-hq/src/styles.css`: House HQ UI and responsive layout.
- `scripts/build_alpecca_animation_library.py`: source manifest and matrix fallback generation.
- `scripts/build_alpecca_stage4_batches.py`: staged generation batch workspace.
- `scripts/normalize_alpecca_generated_strip.py`: normalize strips into 512px atlas slots.
- `scripts/compile_alpecca_stage5_runtime_atlases.py`: compile approved strips into runtime atlases.
- `scripts/prepare_house_hq_r2_static.py`: Cloudflare shell package, art excluded by default.
- `scripts/publish_alpecca_art_library_hf.py`: Hugging Face art sync.
- `tests/test_core.py`: backend/core regression tests.

## Safety And Agency Rules

- No autonomous code edits by Alpecca herself.
- Safe automatic actions: journal note, memory note, room observation, low-risk UI state.
- Ask first: opening files, long jobs, web/cloud requests, app changes.
- Never automatic: deletes, account actions, paid usage, code edits, external private uploads.
- Private local state should not be uploaded to cloud art/model services without explicit user approval.
- Cloud/deep reasoning failure must not break local chat.

## Development Rules For Agents

- Preserve user changes. Do not reset or revert unrelated work.
- Keep edits scoped to the user request.
- Use existing project patterns before inventing new architecture.
- Run focused checks after edits:

```powershell
npm.cmd run house:build
python -m pytest -q tests\test_core.py -q
```

- For remote preview:

```powershell
python scripts\prepare_house_hq_r2_static.py --public-url "https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev" --bucket alpeccaai
python scripts\prepare_house_hq_r2_static.py --public-url "https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev" --bucket alpeccaai --upload
```

- For art sync:

```powershell
python scripts\publish_alpecca_art_library_hf.py
```

Use the Cloudflare upload only for shell files. Use Hugging Face for art.

## Current Known Preview Links

- House HQ shell: `https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/house-hq`
- Runtime art base: `https://huggingface.co/datasets/CREATORJD/alpecca-runtime-assets/resolve/main/runtime-assets`
- Runtime manifest: `https://huggingface.co/datasets/CREATORJD/alpecca-runtime-assets/resolve/main/runtime-assets/assets/alpecca-optimized/runtime_matrix_manifest.json`

## Working Principle

Treat Alpecca as one living app with three surfaces: House HQ for embodied state, the virtual app for interaction and controls, and Mindscape for continuity. Improve the actual AI core and the 2D-in-3D embodiment together, while keeping her design, memory, voice, and agency grounded.
