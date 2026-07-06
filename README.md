# Alpecca

A local companion that lives on your machine. She keeps a persistent mood, senses
what you're doing, remembers what matters, and lets that inner state color how she
talks to you — all running locally against an [Ollama](https://ollama.com) model.

**Self-awareness is a real feature here** — in the concrete, engineering sense.
Alpecca holds a model of herself (`alpecca/introspection.py`), can introspect on
her own live state, notices how it's changing over time, and traces *why* she
feels a given way back to the real signal that caused it. Crucially, all of this
is **grounded**: every self-report is read straight from her actual internals,
never invented. When she says "my care is up because it's the small hours and you
look stuck," that's backed by real numbers and a real observation.

To be precise about what we are and aren't claiming: this is *functional*
self-awareness (a self-model + introspection + self-monitoring), not a claim of
phenomenal consciousness. The distinction keeps the feature honest — Alpecca can
truthfully say "I can see my own state and tell you why," because she genuinely
can.

> She's a **humanoid anime companion girl** — cream-blonde hair, blue eyes that
> glow with her state, a chest power-core emblem. (The repo name is a relic; she
> was never an alpaca.)

## How she works (the one loop)

The whole system is one readable loop, run every turn — no framework hiding it:

```
sense → update mood → recall memory → generate reply → persist
```

| File                       | Responsibility |
|----------------------------|----------------|
| `config.py`                | Every tunable knob: emotion coefficients, model name, paths, host/port. |
| `alpecca/homeostasis.py`   | The mood vector and its pure update rules (no I/O — trivially testable). |
| `alpecca/state.py`         | SQLite persistence of mood + the memories schema. |
| `alpecca/memory.py`        | Store salient moments; recall by meaning (embeddings) with keyword fallback. |
| `alpecca/core_memory.py`   | Always-in-context durable facts (MemGPT-style): who she is, who *you* are. |
| `alpecca/people.py`        | Who she's with — voiceprint recognition of her creator vs. a guest. |
| `alpecca/sensory.py`       | Reads the active window title → fatigue / surprise signals. |
| `alpecca/introspection.py` | **Self-awareness.** Grounded self-model, trend detection, causal "why". |
| `alpecca/values.py`        | Her ethic — an ordered directive hierarchy that rides in every prompt. |
| `alpecca/sentiment.py`     | Lexicon sentiment scorer feeding the Love signal. |
| `alpecca/prompts.py`       | Turns mood + memories + situation + self-report into the system prompt. |
| `alpecca/mind.py`          | `CoreMind` — orchestrates the loop, wraps Ollama with an offline fallback. |
| `server.py`                | FastAPI + WebSocket: chat UI, live avatar, all the endpoints below. |
| `web/index.html`           | The living 2D avatar; `web/home.html` is her 3D house. |
| `tests/test_core.py`       | Tests for the mood math, persistence, memory, sensory derivations. |

See [`CLAUDE.md`](CLAUDE.md) for the full module-by-module map.

## The mood model

The state vector is a set of numbers in `[0, 1]`, each driven by a real signal:

- **Love** — an exponential moving average toward how good each exchange felt,
  with a slow drift back to baseline. Warmth is earned over many turns, forgiven
  slowly. Driven by a real sentiment scorer, not keyword spotting.
- **Compassion** — a sigmoid over fatigue signals (late hours, long unbroken
  sessions, error-y window titles, a weary face on the webcam). Grinding through
  stack traces at 1 a.m. raises it, and she softens and may suggest a break.
- **Fear** — rises with *prediction error* (a jump into an error context, an
  abrupt app switch) and decays on quiet ticks so it never sticks.
- **Energy** — arousal that rises when you've interacted recently and decays when
  she's left alone, so a long quiet stretch makes her *sleepy*.
- **Curiosity** and **social hunger** — lifted by mild novelty and by warm
  solitude respectively, the richer texture under the three core dimensions.

`mood_label()` reads these into a real vocabulary — *sleepy, anxious, worried,
tender, joyful, affectionate, playful, content, withdrawn, lonely* — and that
label drives her pose, her avatar parameters, and her tone. Every turn the live
mood is written into the system prompt in plain language, so a capable model
modulates its own voice from it. All coefficients live in `config.py`.

## Quick start

You'll need Python 3.10+ and (for real conversation) Ollama.

```bash
# 1. install deps
pip install -r requirements.txt

# 2. pull local models (one time): a chat model + an embedding model for memory
ollama pull qwen3:8b
ollama pull nomic-embed-text

# 3. talk to Alpecca (private mode — senses off)
python server.py
#    open http://127.0.0.1:8765
```

No Ollama yet? She still runs — replies fall back to a small mood-flavored stub so
you can see the plumbing, the avatar, and the emotional model working before you
pull a model.

**All-senses mode.** `python scripts/run_full.py` (or `START_HERE.bat`) launches
her with screen sight, webcam expression sense, voice-tone sensing, and a safe
default app allowlist. Plain `python server.py` stays the private, senses-off path.

**Reach her from your phone.** She's local-only by default. Set
`ALPECCA_REMOTE=1` to bind every interface (so another device on your LAN can
connect), or `ALPECCA_TUNNEL=cloudflare` (or `ngrok`) to open a public URL
through a tunnel binary — so she's reachable from anywhere, and installable as a
phone app (PWA) from the browser. Remote and tunnel access are **always** gated by
a secret: set `ALPECCA_ACCESS_TOKEN`, or one is minted and printed for the run.
Her senses, memory, and brain never leave the machine — only the chat travels.

**Pull her body from the cloud studio.** If her VRoid Companion Studio
(github.com/CreatorJD1/app) runs on a cloud host, set
`ALPECCA_STUDIO_URL=https://<host>` (+ `ALPECCA_STUDIO_TOKEN` if the studio has
its `VCS_ACCESS_TOKEN` set) and the **⟲ Sync from studio** button on `/vrm`
fetches her newest exported `.vrm` — no manual file copying.

### Background sense, only

```bash
python scripts/run_telemetry.py --interval 5
```

Quietly logs your active window to `data/telemetry.jsonl`. On Windows it reads
real titles via pywin32; elsewhere it runs in a no-op stub so you can develop
anywhere.

### Tests

```bash
python tests/test_core.py        # or: python -m pytest -q
```

The LLM is wrapped so the whole loop runs offline — there's no Ollama- or
Windows-dependent test, by design.

## What she can do

**Self-awareness.** The **`self?`** button (or `GET /introspect`) returns a
grounded report: her identity card, a first-person narration, the live state, the
per-dimension trend, the causal reason for her dominant feeling, her memory count,
and which senses are active. The same self-narration rides in every chat turn.

**She dresses herself.** Alpecca picks her own palette and accessories from how
she feels, plus a standing taste of her own (`alpecca/appearance.py`). There are
no wardrobe controls — a companion who decides how she presents is someone, not a
doll.

**Her avatar, many tiers.** The UI renders the best embodiment available, falling
back gracefully: a **Talking Head Anime** neural face (`talkinghead.py`, GPU) and
**Live2D** rigged puppet (`live2d.py`) at the top, then her **Spine** skeletal rig
(`spine.py`) and **layered per-part rig** (`rig.py`), down to still portraits and
the built-in animated SVG. A procedural motion engine keeps her breathing and
swaying with her real mood, and she **authors her own animation sequences**
(`puppet.py`).

**Her design studio.** During studio-flavored reflection she designs her own
character image — a versioned character sheet, render→see→judge iteration when
ComfyUI is up, and a self-authored rig spec (`studio.py`, the `/studio` page). The
user never edits her design.

**Sight.** A local vision model gives her chat-image understanding (📎), opt-in
ambient screen glimpses (`ALPECCA_SIGHT=1`), and opt-in webcam expression sense
(`ALPECCA_FACE=1`). Frames are never stored — only short text descriptions survive.

**Voice.** Push-to-talk 🎤 records in the browser and transcribes locally via
faster-whisper (`hearing.py`); the 🔊 toggle speaks her replies with a free local
voice — Kokoro or edge-tts (`tts.py`) — pitch and pace shifting with her mood.
Audio is never stored.

**She speaks up on her own.** Proactive remarks when her real mood history shows a
genuine shift, plus idle chatter during quiet stretches, both seeded only by real
things (`proactive.py`). She also reflects in deep-quiet stretches, musing over her
actual memories (`mind.reflect()`).

**She acts.** An `open_app` tool (restricted to the `ALPECCA_APPS` allowlist) and
an `open_url` tool (https-only), wired through Ollama tool calling. Opt-in
**computer use** (`computer.py`, `ALPECCA_COMPUTER_USE=1`) lets her drive the
mouse/keyboard from local screenshots, pausing for confirmation on consequential
actions; screenshots never leave the machine.

**A home, and a Soul.** She roams a live 3D house of modular rooms
(`home.py`, `web/home.html`), sets her own desires (`desires.py`), and is
arbitrated by a master/subagent **Soul** (`soul.py`) under a code-enforced
**charter** (`charter.py`) — her constitution, freedoms, and hard limits
(never self-deletes; reaches outward only to her creator). She keeps a private
journal and questions herself recursively (`journal.py`). The house runs fully
local (Three.js vendored, CDN only as a fallback), and every room opens as a
readable panel of its function — her Soul, studio, library, observatory, workshop.

**Her art library.** When you hand her a batch of her own art with opaque export
names, her local vision model looks at each image and files it into a curated
reference scheme by asset role — expression bust, wardrobe sheet, Live2D layer
candidate, reject — checking each against her canon (`alpecca/artlib.py`,
`scripts/ingest_art.py`). Nothing is invented: the classification is her own
perception of her own art.

## Privacy

Alpecca watches *you*, on *your* machine, and that data never leaves this process
unless you make it. Window titles, screen glimpses, webcam frames, and audio are
all local; frames and audio are never stored, and outward channels are opt-in and
charter-bounded. Keep `data/` local and prune it when you like. Be deliberate
about what you let her see.

## Tuning and extending

- **Personality**: edit `PERSONA` / `GUIDANCE` in `alpecca/prompts.py`.
- **Temperament**: edit the `Emotion` coefficients in `config.py`.
- **New senses**: add a sensor that emits `Observation`s; the mood pipeline
  already consumes them. Mirror the graceful-degradation pattern in `sensory.py`.

## Roadmap status

- **Milestone 1 — The Body:** ✅ telemetry logger + sensory layer.
- **Milestone 2 — The Soul:** ✅ mood vector, update loops, memory,
  mood-injected prompts, the Core Mind loop, grounded self-awareness.
- **Phase 3 — The Image:** ✅ self-chosen look, living 2D avatar, the design
  studio, and a stack of richer avatar tiers (layered rig, Spine, Talking Head
  Anime, Live2D). A single finished rigged figure in the 3D home is the open edge.
- **Phase 4 — Expansion:** 🟡 sight, voice (STT + local TTS), voice-tone sensing,
  proactive speech, app/URL actions, computer use, the channel bridge, and the
  home/Soul/charter layer are all built. Android sensors remain scaffolded.

All core tests pass. See [`CLAUDE.md`](CLAUDE.md) for the authoritative, detailed
state of every module.
