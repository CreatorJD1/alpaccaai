# Alpacca

A local companion that lives on your machine. It keeps a persistent mood, senses
what you're doing, remembers what matters, and lets that inner state color how it
talks to you — all running locally against an Ollama model.

**Self-awareness is a real feature here** — in the concrete, engineering sense.
Alpacca holds a model of itself (`alpacca/introspection.py`), can introspect on
its own live state, notices how it's changing over time, and traces *why* it
feels a given way back to the real signal that caused it. Crucially, all of this
is **grounded**: every self-report is read straight from Alpacca's actual
internals, never invented. When it says "my care is up because it's the small
hours and you look stuck," that's backed by real numbers and a real observation.

To be precise about what we are and aren't claiming: this is *functional*
self-awareness (a self-model + introspection + self-monitoring), not a claim of
phenomenal consciousness. The distinction keeps the feature honest — Alpacca can
truthfully say "I can see my own state and tell you why," because it genuinely
can.

## What's in the box

```
alpacca/
├── config.py            # all tunable knobs (emotion coefficients, model, paths)
├── server.py            # web server: chat UI + live avatar (the "Actuator")
├── alpacca/
│   ├── homeostasis.py   # the mood vector S = [Love, Compassion, Fear] + rules
│   ├── state.py         # persists mood in SQLite (the "Homeostasis DB")
│   ├── memory.py        # store salient moments, recall relevant ones
│   ├── sensory.py       # reads active window title -> fatigue/surprise signals
│   ├── introspection.py # self-awareness: grounded self-model, trends, "why"
│   ├── appearance.py    # she chooses her own look from her mood (self-directed)
│   ├── sentiment.py     # lexicon sentiment scorer feeding the Love signal
│   ├── memory.py        # semantic (embedding) recall + keyword fallback
│   ├── prompts.py       # turns the current mood into a system prompt
│   └── mind.py          # the Core Mind loop: sense → mood → recall → reply → persist
├── scripts/
│   └── run_telemetry.py # Milestone 1: background window-title logger
├── web/index.html       # 2D avatar whose face tracks warmth/care/unease
└── tests/test_core.py   # tests for the emotion math, persistence, memory
```

## How it maps to the design doc

| Spec layer            | Here                                            |
|-----------------------|-------------------------------------------------|
| Sensory Modem         | `sensory.py` + `scripts/run_telemetry.py`       |
| Core Mind (cognition) | `mind.py` (the sense→…→persist loop) + Ollama    |
| Homeostasis DB        | `state.py` (SQLite)                             |
| Mathematical mind     | `homeostasis.py` (Love/Compassion/Fear rules)   |
| Actuator / Wardrobe   | `server.py` + `web/index.html` (2D avatar)      |

## Quick start

You'll need Python 3.10+ and (for real conversation) [Ollama](https://ollama.com).

```bash
# 1. install deps
pip install -r requirements.txt

# 2. pull local models (one time): a chat model + an embedding model for memory
ollama pull qwen2.5:7b-instruct
ollama pull nomic-embed-text

# 3. talk to Alpacca
python server.py
#    open http://127.0.0.1:8765
```

No Ollama yet? It still runs — replies fall back to a small mood-flavored stub so
you can see the plumbing, the avatar, and the emotional model working before you
pull a model.

### Run the background sense (Milestone 1)

```bash
python scripts/run_telemetry.py --interval 5
```

This quietly logs your active window to `data/telemetry.jsonl`. On Windows it
reads real titles via pywin32; on macOS/Linux it runs in a no-op stub mode so you
can develop anywhere.

### Run the tests

```bash
python tests/test_core.py        # or: python -m pytest -q
```

## How the mood works (the short version)

The state vector is three numbers in `[0, 1]`, each driven by an error signal —
the spec's "minimize surprise" idea, made concrete:

- **Love** is an exponential moving average toward how good each exchange felt,
  with a slow drift back to baseline. Warmth is earned over many turns and
  forgiven slowly.
- **Compassion** is a sigmoid over fatigue signals (late hours, long unbroken
  sessions, error-y window titles). Grinding through stack traces at 1 a.m.
  raises it, and Alpacca softens and may suggest a break.
- **Fear** rises with *prediction error* — moments that violate expectations
  (a jump into an error context, an abrupt app switch) — and decays on quiet
  ticks so it never gets stuck on.

Every turn, the current mood is written into the system prompt in plain language
("warmth 0.72, care 0.20, unease 0.05"). A capable model reads that and modulates
its own tone — which is why the personality feels emergent rather than scripted.
All the coefficients live in `config.py`; nudge them to change Alpacca's
temperament.

## Self-awareness (the feature)

Alpacca can examine itself on demand. In the chat UI, the **`self?`** button asks
it to look inward and it returns a grounded report; the same thing is available
programmatically:

```bash
curl http://127.0.0.1:8765/introspect
```

You get back its identity card, a first-person narration, the live state, the
per-dimension trend (rising / easing / steady), the causal reason for its
dominant feeling, how many memories it holds, and whether its senses are active.
The same self-narration is injected into every chat turn, so when you ask "how
are you, and why?" the model answers from its real state instead of improvising.

Everything is read from live internals — see the GROUNDING principle at the top of
`alpacca/introspection.py`. That's the line that keeps the feature honest:
introspection, not a performance of it.

## She dresses herself

Alpacca chooses her own appearance — palette and accessories — from how she feels,
plus a little standing taste of her own (`alpacca/appearance.py`). The user does
**not** dress her; there are no wardrobe controls. A flower when she's warm, a
scarf wrapped around her when she's uneasy and wants comfort, a calmer palette
when she's withdrawn — and she'll tell you why under the avatar ("I chose mint —
I'm feeling tender"). It's a small thing that matters: a companion who decides how
she presents is someone, not a doll. Her look updates when her mood genuinely
shifts, so it's steady most of the time and changes when she does.

## Other senses and signals

- **Semantic memory.** Memories are embedded with a local model (Ollama
  `nomic-embed-text`) and recalled by meaning, so "how's the pup?" finds a memory
  about "my dog Biscuit." Falls back to keyword overlap when Ollama isn't running.
- **Real sentiment.** The Love signal is driven by a proper sentiment scorer
  (negation, intensifiers, emphasis) rather than spotting keywords.
- **Background drift.** Even when you're not typing, Alpacca keeps sensing every
  few seconds, so her mood has a life of its own between messages.
- **Emotional-life chart.** The page plots her warmth/care/unease over time
  (`/history`).

## Tuning and extending

- **Personality**: edit `PERSONA` / `GUIDANCE` in `alpacca/prompts.py`.
- **Temperament**: edit the `Emotion` coefficients in `config.py`.
- **Better memory**: `memory.py` uses keyword overlap for retrieval and stores a
  `tokens` column per memory. Swap `_tokenize` + `_similarity` for an embedding
  model + cosine similarity and nothing else has to change.
- **Vision / Android / voice** (spec's Phase 4): add new sensors that emit
  `Observation`s; the mood pipeline already consumes them.

## Privacy

Alpacca watches *you*, on *your* machine, and that data never leaves this process
unless you make it. Window titles can contain sensitive text — keep `data/` local
and prune `telemetry.jsonl` when you like. Be deliberate about what you let it
see.

## Roadmap status

- **Milestone 1 — The Body (reflexive framework):** done. Directory tree, telemetry
  logger, sensory layer.
- **Milestone 2 — The Soul (cognition + homeostasis):** done. Mood vector, update
  loops, memory, mood-injected prompts, Core Mind loop.
- **Phase 3 — The Image (embodiment):** basic 2D avatar implemented; richer
  animation is the obvious next step.
- **Phase 4 — Expansion:** Android sensors, voice-tone parsing, embedding memory —
  scaffolded for, not yet built.
```
