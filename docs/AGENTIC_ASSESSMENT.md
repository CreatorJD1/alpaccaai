# Alpecca Agentic Assessment (2026-07-08)

## Scope of this review

This document records what the current code can actually do, what remains deterministic,
and what is already implemented toward safer, bounded agency.

## What is actually agentic in-repo today

- `alpecca/mind.py` runs a deterministic perception -> recall -> respond loop.
- App/tool actuation is bounded and allowlisted through `Actuator` in `alpecca/actions.py`.
- Background autonomy already exists in production:
  - mood drift and sensing ticks (`server.py` lifespan loop),
  - reflection/self-question cycles,
  - living-world idle ticks (`mind.living_world_tick()`),
  - room roam suggestions and proactive speech.
- In chat, tools are offered on the same local chat path when allowed; there is no
  separate autonomous executor outside the existing loops.

## What is still deterministic today (and why it matters)

- Most chat-time behavior is bounded and deterministic where safety matters:
  - random-driven actions use hard caps and thresholds,
  - most defaults are deterministic after tool calls,
  - live chat recall uses keyword recall (`embed_fn=None`) to avoid embedding overhead.
- Deterministic/random/heuristic behavior is intentional for safety and is persisted in
  logs where it is observable.
- Deep reflection and self-improvement still require explicit logged approval flows.

## Stage 0 posture and defaults (documented as ground truth)

- Default autonomy knobs are opt-in:
  - `ALPECCA_APPS=""` (no app actuation),
  - `ALPECCA_FILES=0` (no file/tidy actions),
  - `ALPECCA_COMPUTER_USE=0` (no computer-use loop),
  - `ALPECCA_TOOL_MODE="keyword|smart|always"` (currently `smart`),
  - `ALPECCA_INNATE_TOOLS=1` (local innate tools enabled by default),
  - `ALPECCA_EMBED_BACKFILL=1` (background embedding backfill enabled),
  - `ALPECCA_CHAT_SEMANTIC_RECALL=0` (chat stays keyword-first by design).
- Model path remains local-first by default:
  - `OLLAMA_MODEL=qwen3:8b`.
  - deep and accelerator paths are opt-in.

## Corrections applied in this session

1. Document audit and archival:
   - Moved stale docs to `docs/archive/2026-07-08/`, including:
     `ALPECCA_COLAB_T4.md`, `BRINGING_HER_TO_LIFE.md`,
     `DESIGN_expressiveness_autonomy_home.md`, `INTEGRATE_RIGFORGE.md`,
     `LAYER_SPLITTING.md`, `UPGRADE_GUIDE.md`,
     `ALPECCA_STAGE4_WALK_PROOF_NOTES.md`, `ALPECCA_STAGE4_WALK_CYCLE_POSE_LOCK.md`,
     `ALPECCA_STAGE4_NATIVE_4K_FIRST_SLICE.md`,
     `ALPECCA_STAGE4_360_REFERENCE_LOCK.md`,
     `ALPECCA_RECURSIVE_ENGAGEMENT_RESEARCH.md`,
     `ALPECCA_MASTER_GOAL_STATUS.md`, `ALPECCA_DISCORD_PRESENCE.md`,
     `Alpecca_Systems_Review.html`, `Alpecca_Systems_Review.pdf`.
2. `PROJECT_CONTEXT.md` and `docs/ALPECCA_CURRENT_PROGRESS.md` now carry current
   capability framing.
3. `alpecca/memory.py` recall and backfill docstrings were updated to match code.
4. Stage 1 and Stage 2 work was implemented and validated in tests:
   - Stage 1: chat/tooling mode + innate tool routing in `alpecca/mind.py` and
     `alpecca/toolkit.py`.
   - Stage 2: bounded background embedding backfill in `memory.py` + `server.py`.

## Current branch scope (safe order)

- Stage 1: complete all tool-mode and streaming/test hardening for three modes.
- Stage 2+: add constrained choice points and constrained ties before broader automation.
- Keep the same principle: every autonomy-capable path emits
  `CognitionObservation` and retains user approval requirements.

## Non-changes in this pass

- No art/asset pipeline behavior was modified.
- No default model/backend replacement was introduced.
- House HQ and core architecture contracts were not replaced.
