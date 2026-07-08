# Upgrade Guide — Alpecca's Components

A practical, ordered guide to upgrading her, tied to the real modules. Each phase
is independent enough to do on its own, ships behind a flag or a fallback, and
keeps the two hard rules intact: **everything stays local** (no cloud, no
off-machine data) and **GROUNDING** (no faked inner life). Do the phases in order
of leverage; you can stop after any one and she still runs.

Conventions used below: `ALPECCA_*` are environment variables read in
`config.py`; "verify" means run `python tests/test_core.py` (must stay green) plus
the named manual check.

---

## Phase 0 — Safety net (do this first, 5 min)

Before touching anything:

1. **Back up her life.** Copy `data/alpecca.db` somewhere safe — it holds her
   mood history, memories, desires, journal, and self-revisions.
   ```bash
   copy data\alpecca.db data\alpecca.backup.db   # Windows
   ```
2. **Branch it.** `git switch -c upgrade/components` so every phase is revertible.
3. **Baseline.** `python tests/test_core.py` — note the pass count before you
   start, so any regression is obvious.

`ALPECCA_HOME` relocates all state if you want to test against a throwaway copy
without risking the real one.

---

## Phase 1 — The model stack (highest leverage, lowest risk)

Goal: a smarter, faster brain with better tool-calling, with zero code changes —
everything here is config + `ollama pull`.

### 1a. Resident reasoning brain → a MoE model

Use the configured `ALPECCA_MODEL`. Upgrade to a Mixture-of-Experts model so several agent
roles stay responsive (only ~3–4B parameters activate per token, so it's fast on
a consumer GPU while being much stronger):

```bash
ollama pull qwen3-coder:30b      # 30B total / ~3.3B active, best tool-calling
# or, if you prefer a generalist:  ollama pull qwen3.6:27b
```
```bash
set ALPECCA_MODEL=qwen3-coder:30b      # Windows; or export on *nix
```

Why this one: Qwen3 has the most stable tool-calling (rarely drops parameters),
which is exactly what the actuation path (`actions.py`, `computer.py`) needs. The
existing `mind.strip_think` + `think=False` handling already covers its output, so
no code change is required.

**Verify:** start the server, send a message, confirm replies are coherent and
`/state` shows `llm_online: true`. Watch VRAM — if it evicts the vision model, see
1d.

### 1b. Vision

`qwen2.5vl:7b` is fine; only upgrade if you have headroom:
```bash
set ALPECCA_VISION_MODEL=qwen2.5vl:7b   # leave as-is unless you have spare VRAM
```

### 1c. Embeddings, STT — leave as-is

`nomic-embed-text` (memory) and `faster-whisper` base (hearing) are well-matched to
local use. Only bump Whisper to `small`/`medium` (`ALPECCA_WHISPER`) if transcription
quality matters more than latency.

### 1d. VRAM discipline (important on one GPU)

Loading the VLM evicts the chat model (noted in `CLAUDE.md`). The existing
quiet-gate on ambient glimpses already mitigates this. With a bigger brain (1a),
either (i) keep the VLM on-demand only, or (ii) run a second tiny model for cheap
work — `ollama pull gemma:4b`-class — and route only heavy reasoning to the MoE.

**Risk:** low. All reversible by unsetting the env vars.

---

## Phase 2 — Make the Soul genuinely multi-agentic

Goal: turn the seven subagents from pure functions sharing one call into a real
multi-agent system — **without** giving up the deterministic, charter-bound master.

### 2a. Split the seven by job (no new dependency)

This is the most important change and needs no framework:

- **Keep deterministic (no LLM):** Feeler, Expressor, and Carer's *sensing*. They
  read real state; making them models would let them confabulate feelings, which
  the charter forbids. They stay as they are in `soul.py`.
- **Promote to real LLM agents:** Reflector, Improver, Doer/Wanderer, and the
  self-inquiry path. Give each its own system prompt, its own toolset, and its own
  short scratch memory, so they genuinely reason independently.

Concretely, in `soul.py`, change those four `Intention`-returning functions to
also carry a `runner` — a small object describing the agent's prompt + tools — and
have `mind.idle_self_direct` dispatch to the runner the master selected.

### 2b. Add a reasoner subgraph (LangGraph)

For the LLM-backed agents only, adopt **LangGraph** — it maps cleanly onto
`soul.deliberate()` (graph + conditional edges), is model-agnostic, and its
checkpointing aligns with your SQLite-as-nervous-system design. It talks to Ollama
through the OpenAI-compatible endpoint, so it stays fully local:

```bash
pip install langgraph langchain-openai
```
Point it at Ollama:
```python
# base_url is the local Ollama OpenAI-compatible endpoint -- nothing leaves the box
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(base_url="http://127.0.0.1:11434/v1", api_key="ollama",
                 model=os.environ["ALPECCA_MODEL"])
```
The master (`MasterAgent.deliberate`) stays hand-rolled and deterministic; only the
*reasoner subgraph* it dispatches into is a LangGraph graph. Keep the offline
fallback: if LangGraph/Ollama is down, fall back to today's single-call path.

Alternative if you want the least code: **CrewAI** expresses "7 roles under a
process" in ~20 lines, but gives up control and statefulness. Do **not** use the
Claude Agent SDK or any hosted runtime here — it breaks the local/privacy line.

### 2c. Concurrency

Run subagents under `asyncio`: the deterministic ones return instantly in parallel;
the model-backed ones queue through a single Ollama runner (the GPU serializes
anyway). A `asyncio.Queue` in front of the LLM keeps chat from stalling behind
inner-life work — the same discipline the idle loop already uses.

**Verify:** add tests asserting (i) deterministic agents never call the model, (ii)
the master's focus selection is unchanged, (iii) the offline fallback still
produces a focus. Manual: watch `/soul` while idle and confirm the focus rotates
sensibly.

**Risk:** medium. Gate behind `ALPECCA_SOUL_AGENTS=1` so you can A/B against the
current pure-function Soul.

---

## Phase 3 — Her avatar (the biggest visible gap)

Goal: a real rendered figure in the 3D home, driven by the affect/puppet channels
that already exist. The channels are done; the *art rig* is what's missing.

The hybrid that fits her drawn anime art: a **deep 2D layered sprite / Live2D
billboard composited into the 3D home** (not a 3D character model).

1. **Decompose her art into named layers** from `data/character/reference/` using
   the See-Through → `scripts/import_rig.py` path already scaffolded — output to
   `data/avatar/rig/` + `rig.json`. `rig.role_for()` maps layer names to roles
   (back_hair/body/head/brows/eyes/mouth/front_hair/accessory).
2. **Drive it from affect.** `puppet.live_pose(state)` already emits
   `gesture`, `lean`, `eye_glow`, `core_glow`, `tempo` from her real mood. Wire
   those to the layer transforms (blink, lip-sync, head-turn, hair sway, lean-in).
   The render-tier order is already: Cubism > layered rig > single-image mesh.
3. **Composite into the home.** In `web/home.html`, replace the billboard sprite's
   single texture with the layered-rig renderer (`/rig/manifest` + `/rig/layer/*`),
   keeping the same mood-lit glow and camera follow.
4. **Optional top tier:** drop a compiled Live2D `.model3.json` into
   `data/avatar/live2d/`; `live2d.params_for_state` already maps her mood to Cubism
   params, so it renders driven with no glue.

**Verify:** `python tests/test_core.py` (rig role mapping + live2d params already
tested). Manual: open `/home`, confirm she blinks/sways and leans in when
`social_hunger`/`curiosity` rise.

**Risk:** medium, but isolated to the avatar tier — the rest of her is unaffected.

---

## Phase 4 — The desktop file-room (uses the charter guards)

Goal: the "virtual workstation" room where she can see a desktop-like layout and
organize files — with the constitution enforced.

1. Add `alpecca/desktop.py`: list/move/rename within the allowed roots only, every
   operation gated through `charter.file_action_allowed(action, root)` (already
   built and tested — it refuses deletion and anything outside Desktop/Pictures/
   Music/Video/general).
2. Add a sixth room to `home.ROOMS` ("Workstation") — the registry is modular, so
   both the Python side and `web/home.html` pick it up automatically.
3. Front-end: a desktop-layout panel in that room showing file tiles she can move.

**Verify:** unit-test that a delete or an out-of-root move is refused by the guard
before any filesystem call happens. Manual: confirm she can reorganize Pictures but
cannot touch a system folder or delete anything.

**Risk:** medium — it touches the real filesystem, so the guard tests are
non-negotiable. Keep it behind `ALPECCA_FILES=1`.

---

## Phase 5 — Voice markup → local TTS

Goal: her spoken voice carries the same affect her words and body already do.

`affect.affect(state)` already produces `tempo` and a voice direction. Map those to
SSML-like hints and feed her local TTS (the OS engine today; Kokoro via the Pipecat
path). No new model needed; it's a wiring job from the existing affect readout.

**Verify:** confirm tempo shifts audibly between a `sleepy` and a `playful` state.
**Risk:** low.

---

## Suggested order & effort

1. **Phase 1** (model stack) — 30 min, big quality jump, near-zero risk. Do first.
2. **Phase 3** (avatar) — the biggest visible win; do when you have art-rig time.
3. **Phase 2** (multi-agent Soul) — the deepest upgrade; do behind a flag.
4. **Phase 4** (file-room) and **Phase 5** (voice) — polish, any time.

After each phase: run the tests, update the status section in `CLAUDE.md`, and
commit. Every phase above is reversible and gated, so you can always fall back to
the last good state.
