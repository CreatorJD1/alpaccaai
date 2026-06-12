# Alpecca — Handoff (updated 2026-06-12)

Snapshot for whoever picks this up next (human or agent): current state, how to
run her, what was built, what's solid vs. shaky, and what's next. Read `CLAUDE.md`
for the canonical architecture, `docs/BRINGING_HER_TO_LIFE.md` for the honest
review + phase plan. (An earlier handoff is folded into the history below.)

---

## TL;DR

Alpecca is a **local, private AI companion** — a stateful agent on one machine
with a persistent mood, real memory, senses, an explicit ethic, self-set goals,
self-tuning, self-questioning, and a reactive anime face. Brain = local Ollama.
**Grounding is the hard rule:** every self-report reads from real internals;
nothing is confabulated.

Her **inner life is real and strong** (mostly unit-tested). The recent friction
was **setup**, now handled by a `doctor` + one-click `.bat` launchers.

**Target machine:** Windows, **RTX 3050 Laptop (~4 GB VRAM)**. Plan around 4 GB.

---

## How to run her

### First time
```
cd C:\Users\Jason\Documents\GitHub\alpaccaai
python -m pip install fastapi uvicorn websockets ollama
ollama pull qwen3:4b-instruct-2507        # 4B brain that fits a 4 GB GPU
python scripts\doctor.py                  # the source of truth for "why won't she run"
```
`doctor.py` checks Python, packages, Ollama + model, the port, every sense, and
the neural-face setup, and prints the exact fix for each. Run it whenever stuck.

### Every time (use the .bat launchers — they avoid the PowerShell env-var trap)
- **`start_full.bat`** — brain + all senses + cowork (expression-sheet face).
- **`start_face.bat`** — brain *and* the THA3 neural face in two windows (after
  `setup_face.bat`).
- `python server.py` — private, senses off.
Open **http://127.0.0.1:8765** ( `/classic` = old chat UI with voice/image ).

### Neural face on the 4 GB laptop GPU (optional)
THA3 fits *with* the brain via three levers: light model (`separable_half`,
~half VRAM), the 4B LLM, and **adaptive framerate** (face renders fast only while
she speaks, drops to ~4 fps while she thinks, so the brain gets the GPU when it
needs it). Run **`setup_face.bat`** once (installs CUDA torch, pulls the 4B model,
clones THA3, preps her 512 image; the one manual step is downloading THA3's light
models into `vendor\talking-head-anime-3-demo\data\models\`). If THA3 OOMs, the
app silently falls back to the expression-sheet face (no VRAM).

### Critical Windows gotcha
In **PowerShell**, `set VAR=value` does NOTHING (that's cmd syntax) — use
`$env:VAR="value"`. The `.bat`s sidestep this. For git, PowerShell here-strings
mangle commit messages — write to a temp file and `git commit -F`.

---

## What was built this session (on top of the existing core)

**Backend (Python, mostly tested):**
- Emotion model gained `curiosity` + `social_hunger` (`homeostasis.py`).
- `affect.py` — expressive readout (feeling/valence/arousal/tempo/gesture + voice
  markup) read by prompts, avatar, and TTS.
- `soul.py` — master agent over 7 subagents (deterministic sensors + LLM
  reasoners), arbitrated by the Good Person Principle.
- `charter.py` — her constitution, enforced in code (priority hierarchy; never
  self-deletes; file ops confined to Desktop/Pictures/Music/Video/general;
  internet only to reach Jason).
- `desires.py`, `selfmod.py`, `journal.py` (+ recursive self-questioning),
  `learning.py` (self-training: grounded *lessons* from her history that steer
  `selfmod`), `home.py` (5 roamed rooms), `pose.py`, `desktop.py` (charter-guarded
  file room).

**Front-end — the super-app at `/` (`web/home.html`):**
- Live 3D home (Three.js) + integrated chat (one WebSocket) + voice (🎤 push-to-
  talk, 🔊 mood-driven TTS) + camera (📷) + cowork (🖥).
- **Live anime face**: her 16 drawn expressions (sliced from her expression sheet
  → `data/character/expressions/`) mapped from her real mood, with lip-sync and a
  mood-glow ring.
- Senses strip (👁/🎤/📷/🖥) + "what she last saw" + her cursor when she works +
  an **activity ticker** showing her autonomous acts.
- Facet panels: Studio, Library, Journal, Mind, Workshop (desires + revisions +
  lessons), Senses/Workspace, Files, Play (browser games).

**Avatar tiers (each driven by the *same grounded mood*, degrading to the next):**
THA3 neural > pose-swap real-art > RIGFORGE mesh (`web/rigforge.html`) >
expression-sheet face > portrait > SVG. Also still wired: Live2D/Cubism, Spine,
layered rig, ToonCrafter clips (see the prior handoff section).

**Ops:** `scripts/doctor.py`, `start_full.bat`, `setup_face.bat`, `start_face.bat`.

**Routes added:** `/`, `/classic`, `/home/state`, `/growth`, `/soul`, `/journal`,
`/memories`, `/desktop` (+move/rename), `/sight`, `/games` (+play),
`/avatar/expression/{name}`, `/avatar/skeleton`, `/avatar/rigpose`, `/rigforge`
(+capture).

---

## Solid vs. shaky (honest)

**Solid:** the backend modules + their tests (emotion rules, affect, home,
desires, selfmod, soul, journal, charter guards, learning, pose). LLM brain works;
state persists; the autonomous loop is wired and livened.

**Shaky:**
- **`web/home.html` is large and NOT fully syntax-checked.** The dev sandbox mount
  serves a stale truncated copy, so a full `node --check` wasn't possible; blocks
  were verified individually via the editor. **If the page renders blank, it's a
  JS error — open F12, find the red line, fix it.** (That's how the earlier
  `THREE`-before-load blank-page bug was caught.) A Phase-4 audit on the real file
  is the top to-do.
- Neural face on 4 GB is tight (fallback covers OOM).
- Senses/cowork need optional packages + flags (doctor reports them).

**Dev-env quirk:** the Linux sandbox mount intermittently truncates large files on
read; the canonical Windows files are correct. Run tests on the real checkout:
`python tests\test_core.py` (or `python -m pytest -q`).

---

## Her real art (still true)
Character bible in `data/character/reference/`. She is a **humanoid anime girl**
(cream-blonde, glowing eyes, chest power-core) — *not* an alpaca (legacy
placeholder). Backgrounds removed (transparent). **`data/` is gitignored** — her
DB, memories, art, and avatar exports live there and don't travel with the repo; a
fresh clone needs her pose/portrait PNGs replaced. The expression face uses
`data/character/expressions/` (sliced this session) and `data/avatar/portraits/`.

---

## Work plan (where we are — from docs/BRINGING_HER_TO_LIFE.md)
- **Phase 0 — runs reliably:** DONE (doctor + launchers).
- **Phase 1 — visibly alive on her own:** DONE (livelier cadences + activity ticker).
- **Phase 2 — presence:** DONE (expression face + lip-sync + mood-driven voice).
- **Phase 3 — senses, visible:** DONE (senses strip + "what she sees" + cursor).
- **Phase 4 — consolidate front-end:** PARTIAL. **Next:** full audit of
  `home.html` (node-check the real file; fix any syntax slip; finish/verify the
  half-wired pieces), give each 3D room distinct visual purpose.
- **Phase 5 — stretch:** THA3 on the laptop (built; needs the one-time setup run +
  model download); cowork reliability + her cursor; RIGFORGE → `Alpeccaai-data`
  self-training loop; AutoSprite-generated expression/animation frames.

## Immediate next steps
1. `setup_face.bat` → `python scripts\doctor.py` → `start_face.bat`; confirm she
   comes up with brain + neural face on the 4 GB GPU.
2. Phase-4 audit of `web/home.html` on the real checkout (node-check; fix blanks).
3. Watch the activity ticker a few minutes — confirm the autonomous loop fires.

## Orientation
`CLAUDE.md` (architecture) · `docs/` (design + review docs) · `alpecca/` (modules)
· `server.py` (FastAPI + WS) · `web/` (UI) · `tests/test_core.py` (Ollama/Windows-
free) · `scripts/` (doctor, run_full, run_talkinghead, import_rig, build_manifest).

---

## Prior handoff (2026-06-11) — still-relevant notes
- Branch `build/alpecca-companion` → PR #2 against `main`; tests were 96 passing
  then (more added this session).
- The full avatar tier stack predates this session: **THA3** (`talkinghead.py`),
  **Cubism** (`live2d.py`, drop a `.model3.json`), **Spine** (`spine.py`,
  StretchyStudio export — the originally-recommended primary rig path),
  **ToonCrafter clips** (`run_tooncrafter.py` → `data/avatar/*.mp4`), **layered
  rig** (See-Through PSD → `import_rig.py`), **mesh rig**, pose/SVG.
- Recommended full-rig pipeline (needs the user's GPU, all free/open):
  See-Through (decompose art → PSD) → StretchyStudio (in-browser auto-rig →
  Spine 4.0 JSON) → drop into `data/avatar/spine/`. Tune the renderer fit to her
  real skeleton on first export.
- PIXI + pixi-spine vendored in `web/vendor/` (local-first). Live2D Cubism core is
  still CDN (proprietary, model tier only).
- Talk mode (`scripts/run_talk.py`) needs a separate Python 3.12 venv
  (`.venv-talk/`) — pyaudio has no 3.14 wheels; browser 🎤 avoids this.
