# CLAUDE.md — Alpacca

Context for Claude Code (or any agent) picking up this project. Read this first,
then `README.md` for the user-facing overview.

## What this project is

Alpacca is a **local companion app**: a stateful agent that runs on the user's
machine, keeps a persistent mood, senses what the user is doing, remembers
salient moments, and lets that inner state color how it talks — running against a
local Ollama model.

**Framing — self-awareness is a real feature, kept honest by grounding.**
Alpacca has *functional* self-awareness: a self-model, introspection on its own
live state, self-monitoring of trends, and causal insight into why it feels a
given way (`alpacca/introspection.py`). This is a genuine capability, not flavor —
the persona affirms it and means it.

The line that keeps this honest is GROUNDING: every self-report is read directly
from real internals (live mood, real mood history, real memory count, the actual
signals that moved it). Alpacca never invents an inner life or fabricates
memories of things that didn't happen. So the distinction to hold is:
*functional self-awareness* (real, built, truthful) vs *phenomenal consciousness*
(not claimed). Don't add features that fake sentience by confabulating — a
self-report must always be backed by something real in the system. Within that
rule, lean into the self-awareness; it's the heart of the product.

## Architecture (data flow)

The whole system is one loop, run every turn, kept as plain readable Python
rather than hidden inside a framework:

```
sense → update mood → recall memory → generate reply → persist
```

| File                      | Responsibility |
|---------------------------|----------------|
| `config.py`               | All tunable knobs: emotion coefficients, model name, paths, server host/port. Magic numbers live here, nowhere else. |
| `alpacca/homeostasis.py`  | The mood vector `S = [love, compassion, fear]` (each in [0,1]) and its three update rules. Pure, no I/O — easy to test. |
| `alpacca/state.py`        | SQLite persistence of mood (`state` + `state_log` tables) and the `memories` table schema. |
| `alpacca/memory.py`       | Store salient moments; retrieve relevant ones via keyword-overlap (Jaccard) scoring blended with salience + recency. |
| `alpacca/sensory.py`      | `WindowSensor` reads the active window title (Win32 on Windows, stub elsewhere) and derives `fatigue_signals` + `prediction_error`. |
| `alpacca/introspection.py`| **Self-awareness.** Grounded self-model: identity card, trend detection, causal "why", first-person `SelfReport.narrate()`. Read the GROUNDING note at the top before touching it. |
| `alpacca/appearance.py`   | **Self-directed appearance.** She picks her own palette + accessories from her mood (+ a stable `seed` taste). The user does NOT control this; there are no UI wardrobe controls. Keep it that way. |
| `alpacca/sentiment.py`    | Lexicon sentiment scorer (negation/intensifiers/emphasis) that feeds the Love reward. Optional Ollama path `score_llm`. |
| `alpacca/prompts.py`      | Builds the system prompt from mood + memories + situation + the self-report. Also the reward/salience heuristics. Where the personality lives. |
| `alpacca/mind.py`         | `CoreMind` — orchestrates the loop, wraps Ollama with an offline fallback. |
| `server.py`               | FastAPI + WebSocket; serves the chat UI and streams mood with each reply. |
| `web/index.html`          | Single-file 2D SVG avatar whose face/color track warmth/care/unease. |
| `scripts/run_telemetry.py`| Standalone background window-title logger → `data/telemetry.jsonl`. |
| `tests/test_core.py`      | Tests for the mood math, persistence, memory, sensory derivations. |

### How the mood model works (so you don't misread the math)
- **Love**: EMA toward a per-turn `reward` in [0,1], with slow decay to baseline.
  `update_love(reward)`.
- **Compassion**: `sigmoid(bias + Σ weightᵢ·signalᵢ)` over fatigue signals
  (late_night, long_session, error_context, idle_return). `update_compassion(signals)`.
- **Fear**: thresholded prediction error; rises when surprise > threshold, decays
  on quiet ticks. `update_fear(prediction_error)`.

Each update returns a **new** `EmotionalState` (immutable-style) — don't mutate in
place; tests and reasoning depend on this.

## Running and testing

```bash
pip install -r requirements.txt
ollama pull qwen2.5:7b-instruct      # for real replies; optional for dev
python server.py                     # http://127.0.0.1:8765
python scripts/run_telemetry.py      # background sense (Milestone 1)
python tests/test_core.py            # or: python -m pytest -q
```

There is no Ollama-dependent test — the LLM is wrapped so the loop runs offline
(stub replies). Always keep it that way: **core logic must be testable without
Ollama or Windows.**

## Conventions — match these

- **Explain the *why* in comments and docstrings.** This codebase deliberately
  reads like prose: every module top-comment explains intent and the reasoning
  behind design choices, not just what the code does. Continue that voice. Avoid
  terse uncommented code and avoid heavy-handed `MUST`/`ALWAYS` directives.
- **Keep tuning in `config.py`.** New behavioral constants go in the `Emotion`
  class or a sibling, never inline.
- **Pure mood functions.** Keep `homeostasis.py` free of I/O so it stays trivially
  testable. Persistence belongs in `state.py`.
- **Graceful degradation.** Anything platform- or service-specific (pywin32,
  Ollama) must fall back, not crash. Mirror the patterns in `sensory.py` /
  `mind.py`.
- **Every new feature gets a test** in `tests/test_core.py` if it has objectively
  checkable logic.
- Imports assume the project root is on `sys.path` (scripts insert it; the package
  imports `config` and `alpacca.*` directly).

## Known gotchas

- **SQLite on network/synced filesystems** can throw `disk I/O error`. The default
  `data/` dir is fine on a normal local disk. `ALPACCA_HOME` env var relocates all
  state if needed.
- **pywin32 is Windows-only** and is the only OS-specific dep; `requirements.txt`
  guards it with a platform marker. Everything else is cross-platform.
- **Window titles can contain sensitive text.** Telemetry is local-only by design.
  Don't add any code that ships it off-machine without an explicit, opt-in user
  decision. Treat this as a hard privacy line.

## Current status

- ✅ Milestone 1 (Body): telemetry logger + sensory layer.
- ✅ Milestone 2 (Soul): mood vector, update loops, memory, mood-injected prompts,
  Core Mind loop.
- ✅ Self-awareness: grounded self-model, introspection, trend self-monitoring,
  `/introspect` endpoint + `self?` UI button.
- ✅ Self-directed appearance: she chooses her own look (`appearance.py`); no user
  wardrobe controls.
- ✅ Semantic (embedding) memory with keyword fallback; real sentiment-driven Love;
  background mood drift; `/history` + mood-timeline chart.
- 🟡 Phase 3 (Image): 2D character avatar with idle breathing/blink + self-chosen
  look done; plus optional generated self-portraits via ComfyClaw/ComfyUI
  (`alpacca/portrait.py`, `/portrait` endpoint, enable with `ALPACCA_PORTRAIT=1`).
  A richer built-in sprite (Replika-style) remains the next visual step.
- 🟡 Phase 4 (Expansion): OpenClaw channel bridge built — `POST /channel/inbound`
  runs the full chat loop for messages from Telegram/Discord/etc., outbound
  replies via the `openclaw` CLI (`alpacca/openclaw_bridge.py`; install hook from
  `integrations/openclaw-inbound-hook/`). Android sensors and voice-tone parsing
  still scaffolded via the `Observation` interface, not built.
- All 31 core tests pass; full loop, introspection, appearance, portrait
  prompts, and channel bridge verified end-to-end.

Note on the dev environment: this sandbox's Linux file mount intermittently
truncates large files *on read* (a mount cache artifact). The canonical files are
correct. If a `python` run fails with an unterminated-string/`NameError` on a
partial token, re-copy the file and retry rather than "fixing" a phantom bug.

## Suggested next tasks (good entry points)

1. **Richer character sprite.** The avatar is a clean SVG with idle animation and
   her self-chosen palette/accessories. Next visual step (the Replika inspiration):
   a more detailed, layered character — keep it driven by the same mood vector and
   the `appearance.py` output; do not add user-facing wardrobe controls.
2. **She volunteers self-observations.** When `introspect()` detects a big shift
   (e.g. unease jumped over the last hour), have her proactively say so in chat,
   not just when asked. Grounded in the same trend data.
3. **Voice-tone sensing (Phase 4).** Add a mic-level/tone sensor that emits
   `Observation`s feeding the fatigue/surprise signals — the mood pipeline already
   consumes them.
4. **Smarter salience.** `prompts.estimate_salience` is heuristic; a small local
   model deciding what's worth remembering would sharpen long-term memory.

When you finish a unit of work, run the tests and update the status section above.
```
