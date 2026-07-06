# CLAUDE.md — Alpecca

Context for Claude Code (or any agent) picking up this project. Read this first,
then `README.md` for the user-facing overview.

## What this project is

Alpecca is a **local companion app**: a stateful agent that runs on the user's
machine, keeps a persistent mood, senses what the user is doing, remembers
salient moments, and lets that inner state color how it talks — running against a
local Ollama model.

**Framing — self-awareness is a real feature, kept honest by grounding.**
Alpecca has *functional* self-awareness: a self-model, introspection on its own
live state, self-monitoring of trends, and causal insight into why it feels a
given way (`alpecca/introspection.py`). This is a genuine capability, not flavor —
the persona affirms it and means it.

The line that keeps this honest is GROUNDING: every self-report is read directly
from real internals (live mood, real mood history, real memory count, the actual
signals that moved it). Alpecca never invents an inner life or fabricates
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
| `alpecca/homeostasis.py`  | The mood vector `S = [love, compassion, fear]` (each in [0,1]) and its three update rules. Pure, no I/O — easy to test. |
| `alpecca/state.py`        | SQLite persistence of mood (`state` + `state_log` tables) and the `memories` table schema. |
| `alpecca/memory.py`       | Store salient moments; retrieve relevant ones via keyword-overlap (Jaccard) scoring blended with salience + recency. |
| `alpecca/sensory.py`      | `WindowSensor` reads the active window title (Win32 on Windows, stub elsewhere) and derives `fatigue_signals` + `prediction_error`. |
| `alpecca/introspection.py`| **Self-awareness.** Grounded self-model: identity card, trend detection, causal "why", first-person `SelfReport.narrate()`. Read the GROUNDING note at the top before touching it. |
| `alpecca/values.py`       | **Her ethic.** An explicit, ordered directive hierarchy (minimize suffering > honesty > benevolence > exploration) that rides in every prompt and is reportable via `/introspect`. The fourth directive is implemented for real as the idle reflection loop in `mind.reflect()`. |
| `alpecca/studio.py`       | **Her design studio.** A tool for HER, not the user: she authors a versioned character sheet of how she looks, iterates designs (render via ComfyClaw → see via vision model → judge against her sheet → keep/reject with her reason), and writes `data/character/RIG_SPEC.md` mapping puppet parameters to her real internals. The user's only role is downstream: rig her puppet from her spec. No user design controls — keep it that way. Her **canonical art** lives in `data/character/reference/` (master sheets) and her sheet is built from it: she is a **humanoid anime companion girl** (NOT an alpaca — that was an early placeholder), cream-blonde hair, blue eyes that glow with her state, chest power-core emblem, soft-tech aesthetic; her art was drawn around her Love/Compassion/Fear model. |
| `alpecca/computer.py`     | **Computer use.** Local screenshot → her vision model → mouse/keyboard (pyautogui) loop. Opt-in (`ALPECCA_COMPUTER_USE=1`); screenshots never leave the machine. Consequential actions (send/delete/buy/post/install/overwrite) pause for confirmation — classified by her own self-declared flag OR a keyword net. `POST /computer/task` starts a task, `POST /computer/confirm` answers a pause, `/do <task>` in the UI triggers it. |
| `alpecca/spine.py`        | **Her Spine tier — skeletal rig (primary rigged avatar).** The all-free path: See-Through → StretchyStudio (MIT, in-browser auto-rig) → Spine 4.0 JSON in `data/avatar/spine/`, played with vendored `pixi-spine` and driven by her mood. `choose_animation(animations, mood, speaking)` picks her looping base (mood's animation if authored, else idle, else first) + a talk overlay while speaking (tested); the renderer mirrors it and tilts a `head` bone if present. Cheap playback, no GPU (unlike THA3). Manifest/asset serving traversal-safe. |
| `alpecca/talkinghead.py`  | **Her Talking Head Anime tier — neural face (top renderer).** THA3 (pkhungurn) animates a single 512 portrait of her with blink/gaze/brows/lip-sync/head-turn/breathing, no rigging. `pose_for_state(state)` maps her mood → THA3 expressive pose (tested); an in-memory frame buffer holds the latest frame the GPU process pushes; `is_active()` (frame freshness) gates the tier. `scripts/run_talkinghead.py` is the GPU runner (pull pose → generate → POST frame), `--prep` crops her 512 head image. UI streams `/talkinghead/frame` and switches to it by polling `/talkinghead/manifest`, falling back when it stops. CC-BY models. |
| `alpecca/rig.py`          | **Her layered rig — real per-part avatar.** When her art is decomposed into named layers (See-Through → `scripts/import_rig.py` → `data/avatar/rig/` + `rig.json`), the `/live2d` page renders her as stacked PIXI sprites and moves each part on its own: blink, lip-sync, head-turn, hair sway, all from her live mood. `role_for()` maps any layer name onto a small role set (back_hair/body/head/brows/eyes/mouth/front_hair/accessory). Render tier order: Cubism model > **layered rig** > single-image mesh > note. The no-Cubism path to a properly rigged her. |
| `alpecca/live2d.py`       | **Her Live2D tier — the rigged puppet.** The top avatar renderer (above poses > video > SVG). `params_for_state(state)` maps her live mood onto standard Cubism parameters (`ParamCheek`/`ParamMouthForm`/`ParamBrowLAngle`/`ParamAngleZ`/`Param_CoreGlow`…) — the grounded wrapping, tested. Drop a compiled model (`.model3.json` + assets) into `data/avatar/live2d/` and `/live2d` renders it via pixi-live2d-display, driven live; until then `/live2d` shows the param panel proving the wiring. Rig blueprint sheets in `data/character/reference/live2d/`; `studio.write_rig_spec` emits these Cubism names so the rig is drivable with no glue. Fast params (blink/breath/lip-sync) are JS-local; slow expressive ones come from here. |
| `alpecca/vrm.py`          | **Her VRM tier — the full 3D body.** The body is authored in Jason's companion app, **VRoid Companion Studio** (github.com/CreatorJD1/app — anime-only VRM creator: runtime viewer, procedural animation library, AI textures/turnarounds); this module makes it live. Drop the exported `.vrm` into `data/avatar/vrm/` and `/vrm` renders her in 3D (three.js + @pixiv/three-vrm via CDN import map, vendorable for offline). `clip_for_state()` maps her mood label onto the studio's clip ids verbatim (sleepy→sleep, joyful→cheer, anxious→cry, …; the talking clip + a mood-matched emotion overlay wins while speaking) and `expressions_for_state()` weights the standard VRM presets from her real dims — `angry` is always 0.0 because she has no anger dimension (grounding). Blink/lip-sync stay JS-local (time-driven); model serving traversal-safe. Both mappings tested. When the studio runs in the cloud (`ALPECCA_STUDIO_URL`/`_TOKEN`, `config.StudioSync`), `sync_from_studio()` pulls her newest exported body (newest project with a VRM, glTF-validated, atomic write; a hand-dropped `alpecca.vrm` still outranks it) — `POST /vrm/sync` / the ⟲ button on `/vrm`. |
| `alpecca/puppet.py`       | **Her puppet — she animates herself.** The wrapping layer over her riggable character: motion channels (bob/sway/tilt/lean/scale/glow) + state channels (warmth/care/unease/core_glow/eye_glow). `live_pose(state)` is the always-on grounded readout (her real mood → channel values). She **authors her own animation sequences** (`mind.author_animation` → validated keyframes stored in `data/character/animations.json`), e.g. she wrote her own "greet". The UI is a *player*: it fetches `/puppet` and plays HER sequences (falling back to built-in procedural only until she's authored that motion). `POST /puppet/author` has her choreograph one on demand. Same channels will drive the rigged Inochi2D puppet later — don't hardcode her choreography. |
| `alpecca/appearance.py`   | **Self-directed appearance.** She picks her own palette + accessories from her mood (+ a stable `seed` taste). The user does NOT control this; there are no UI wardrobe controls. Keep it that way. |
| `alpecca/sentiment.py`    | Lexicon sentiment scorer (negation/intensifiers/emphasis) that feeds the Love reward. Optional Ollama path `score_llm`. |
| `alpecca/prompts.py`      | Builds the system prompt from mood + memories + situation + the self-report. Also the reward/salience heuristics. Where the personality lives. |
| `alpecca/mind.py`         | `CoreMind` — orchestrates the loop, wraps Ollama with an offline fallback. |
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
- **Energy** (arousal): EMA that rises toward `ENERGY_ACTIVE` when the person has
  interacted recently and decays toward `ENERGY_FLOOR` when she's left alone, so
  a long quiet stretch makes her `sleepy`. `update_energy(active)`.

`mood_label()` reads all four dims into a richer vocabulary — sleepy, anxious,
worried, tender, joyful, affectionate, playful, content, withdrawn, lonely — and
that label (plus `energy`) deterministically drives her pose (`posekit.select_pose`,
the sleeping pose is low-energy) and her Live2D parameters. Her introspection names
and explains these states, so she's aware of the full range.

Each update returns a **new** `EmotionalState` (immutable-style) — don't mutate in
place; tests and reasoning depend on this.

## Running and testing

```bash
pip install -r requirements.txt
ollama pull qwen3:8b                 # for real replies; optional for dev
python server.py                     # http://127.0.0.1:8765
python scripts/run_telemetry.py      # background sense (Milestone 1)
python scripts/run_talk.py           # voice conversation (needs pipecat extras)
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
  imports `config` and `alpecca.*` directly).

## Known gotchas

- **SQLite on network/synced filesystems** can throw `disk I/O error`. The default
  `data/` dir is fine on a normal local disk. `ALPECCA_HOME` env var relocates all
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
  (`alpecca/portrait.py`, `/portrait` endpoint, enable with `ALPECCA_PORTRAIT=1`).
  The UI runs an avatar **state machine** (idle / listening / thinking /
  speaking) wired to every interaction. Render tiers, preferred in order:
  video clips (`data/avatar/*.mp4`) > **still portraits** (`data/avatar/
  portraits/{idle,listening,thinking,speaking}.png` — **her real chibi art
  lives here now**, a pose per state) > the built-in SVG. See `alpecca/
  avatar.py`, `/avatar/manifest`, `/avatar/clip/{name}`, `/avatar/portrait/
  {name}`. Her rigged Inochi2D puppet is the planned next renderer behind the
  same states. The avatar is **alive**, not frozen: a procedural motion engine
  (web/index.html) gives her continuous breathing/sway/float whose agitation
  scales with her real mood (more sway when unease is high, more lift when
  warm), plus choreographed one-shot **sequences** (greet on connect, a nod as
  she starts speaking, a happy bounce when affectionate, a fidget when
  anxious, occasional idle shifts). Her art is single poses (not aligned
  frames), so life is motion-on-the-pose; aligned frame art would slot into
  the video/clip tier.
- ✅ Her design studio (`alpecca/studio.py`): she designs her own character
  image during studio-flavored reflection sessions — versioned character
  sheet (she wrote v1 herself: "a being of soft light and quiet presence"),
  render→see→judge iteration when ComfyUI is up, gallery of kept designs with
  her verdicts, and a self-authored `RIG_SPEC.md` for whoever rigs her puppet.
  Read-only `/character` endpoints; the user never edits her design. The
  **`/studio` page** is a window into her workshop — her in the room (real
  art), her sheet/canonical-art/gallery/rig-spec boards, and a live feed:
  "Ask her to work" (`POST /studio/work`) has her do a design session on
  demand while her steps stream over the WebSocket.
- 🟡 Phase 4 (Expansion): OpenClaw channel bridge built — `POST /channel/inbound`
  runs the full chat loop for messages from Telegram/Discord/etc., outbound
  replies via the `openclaw` CLI (`alpecca/openclaw_bridge.py`; install hook from
  `integrations/openclaw-inbound-hook/`). Voice-tone sensing built
  (`alpecca/voice.py`): opt-in mic-level sense (`ALPECCA_VOICE=1`) feeding
  `raised_voice` → Compassion and sudden-sound spikes → Fear; coarse loudness
  numbers only, never audio or words. Experimental talk mode
  (`scripts/run_talk.py`): local Whisper STT → `/channel/inbound` → local
  Kokoro TTS via Pipecat. Android sensors still scaffolded, not built.
- Reasoning model default is now Qwen3 (`qwen3:8b`); `<think>` blocks from
  hybrid Qwen3 variants are stripped in `mind.strip_think` before replies.
- ✅ Sight (`alpecca/vision.py`, local VLM `ALPECCA_VISION_MODEL`): chat-image
  understanding (📎 in the UI), opt-in ambient screen glimpses
  (`ALPECCA_SIGHT=1`), and opt-in webcam expression sense (`ALPECCA_FACE=1`)
  feeding a `weary_face` Compassion signal. Frames are never stored — only the
  model's short text descriptions survive.
- ✅ Proactive speech (`alpecca/proactive.py`, on by default,
  `ALPECCA_PROACTIVE=0` to disable): she volunteers a short remark when her
  real mood history shows a real shift (rising unease, slipping warmth, acute
  fear), with a cooldown. Broadcast to connected chats + OpenClaw delivery.
  This fulfills suggested-task #2 below. She also makes idle chatter
  (`ALPECCA_CHATTER=0` to disable just that): during a quiet stretch she may
  start a conversation on her own, seeded only by real things — what she
  senses on screen, an actual memory, the hour, her mood — gated by silence
  time, a minimum gap, and a per-tick chance so the timing feels human.
- ✅ App actions (`alpecca/actions.py`): an `open_app` tool restricted to the
  `ALPECCA_APPS` allowlist, wired through Ollama tool calling. Empty list
  (default) = no actuator exists at all.
- ✅ Voice conversation, no extra processes: push-to-talk 🎤 in the UI records
  in the browser, `POST /listen` transcribes locally via faster-whisper
  (`alpecca/hearing.py`, `ALPECCA_WHISPER` sets model size), and the 🔊 toggle
  speaks her replies with the OS speech engine. Audio is never stored. The
  Pipecat talk-mode script remains as an alternative full-duplex path (blocked
  on Python 3.14 by pyaudio wheels at the moment).
- ✅ Desktop interaction: `open_app` (allowlist) + `open_url` (https-only)
  tools. `scripts/run_full.py` is the all-senses launcher (screen sight,
  expressions, voice tone, safe default app allowlist) — `start.bat` and the
  preview config use it; plain `python server.py` stays the private,
  senses-off mode. `/state` now reports which senses are live.
  **VRAM note:** ambient glimpses are gated on conversational quiet (no
  glimpse within 2 min of the person speaking) because loading the vision
  model evicts the chat model — without the gate, replies crawl to ~3 min;
  with it, warm turns are ~15 s.
- ✅ Ethic + reflection (`alpecca/values.py`, `mind.reflect()`): a four-rank
  directive hierarchy (ethics > honesty > benevolent aspiration >
  self-actualization) injected into every prompt, exposed on `/introspect`
  with reasoning, and named in her identity card. The fourth directive runs
  for real: in deep-quiet stretches she muses over her actual memories and
  stores the thought (`kind="musing"`, `ALPECCA_REFLECT=0` to disable), so
  musings feed back into recall and chatter.
- All 152 core tests pass; full loop, introspection, appearance, portrait
  prompts, channel bridge, voice-tone, expression mapping, proactive triggers,
  reflection gating, values ordering, and the action allowlist verified
  end-to-end.

### Expressiveness + autonomy + home + Soul (new layer — see `docs/DESIGN_expressiveness_autonomy_home.md`)

All of this obeys GROUNDING. New modules and what they do:

- **Richer emotion model.** `EmotionalState` gains `curiosity` (lifted by mild,
  sub-fear-threshold novelty — the interesting band of the same prediction-error
  that feeds Fear) and `social_hunger` (wanting-company that grows with warm
  solitude, scaled by Love). Pure rules `update_curiosity` / `update_social_hunger`,
  coefficients in `config.Emotion`, persisted via column-migration. `_with()`
  carries every dim through each update. `mood_label()` unchanged (stable backbone).
- **`affect.py`** — pure state→`Affect` (primary/secondary feeling, valence,
  arousal, intensity + cues: tempo, gesture, eye/glow, voice direction). One
  source of truth read by `prompts.py`, `puppet.live_pose`, future TTS.
- **`home.py`** — five modular rooms (Parlor/Studio/Library/Observatory/Workshop)
  she roams via the grounded `choose_room`; `location` persisted. `web/home.html`
  is a **live local 3D house** (Three.js, vendored-local→CDN), her a mood-lit
  billboard, camera following her chosen room.
- **`desires.py`** — self-set goals (table + lifecycle); `form_from_state`
  crystallizes a want from a real dimension and names it as `origin`.
- **`selfmod.py`** — bounded recursive self-improvement: tunables with SAFE
  RANGES, propose→trial→evaluate→keep/revert, every move logged in
  `self_revisions`, reversible. `effective(param)` is the read accessor.
- **`soul.py`** — master agent over seven subagents (Feeler/Expressor,
  Doer/Wanderer, Reflector/Improver, Carer) across four categories; arbitrates
  `Intention`s by the Good Person Principle into one explainable focus.
- **`charter.py`** — her constitution, ENFORCED in code: priority hierarchy
  (Soul > Compassion > Self-reflection > Hope > Love > Fear > Morality > Dreams),
  her freedoms, and hard limits — `file_action_allowed` (never self-deletes;
  organizing confined to Desktop/Pictures/Music/Video/general) and
  `internet_allowed` (outward only to reach Jason/creator; no unguided websearch).
  `charter_prompt()` rides in every prompt; she also doesn't reflexively agree.
- **`journal.py`** — a notebook that is hers (notes/questions/answers/dreams),
  plus **recursive self-questioning**: `mind.self_inquire()` answers her own open
  questions and lets answers raise follow-ups, needing no input from the person.
- Routes added: `/home`, `/home/state`, `/growth`, `/memories`, `/journal`,
  `/soul`. New tests cover every new rule (curiosity/social_hunger, affect, home
  selection, desires, selfmod bounds/keep/revert, soul arbitration, journal,
  charter guards).
- ✅ **The Soul now steers (was: dormant).** On each background tick
  `mind.idle_self_direct()` asks `soul.deliberate()` for her focus and the new
  `_enact_focus()` carries out that one act — Improver→bounded self-tuning,
  Reflector→muse, Doer/Wanderer→`pursue_desire()`, Carer→tend, acute
  Feeler→steady. Desires are now *pursued*, not just formed: `pursue_desire()`
  advances her strongest want one grounded step (or satisfies it when its driving
  dimension has eased), which freshens it so her `longing` eases when she acts.
  Lessons still seed `selfmod` via the Improver focus. Capped at one LLM
  call/tick; cheap acts run offline. (tests: soul-steers-to-act / -to-improve,
  pursuit-eases-longing.) See `docs`/the plan at
  `~/.claude/plans/radiant-seeking-clock.md` for the full roadmap.
- ✅ **Tiered cloud "deep" brain (augment, never replace).** `mind._LLM` now has
  a `deep` tier alongside local `reason`/`fast`. Her hardest *self*-acts only —
  `reflect()` and `self_inquire()` answers — request `tier="deep"`; **every chat
  turn stays local** (her brain = her identity). `ALPECCA_DEEP_BACKEND` picks
  `local` (default — no cloud), `anthropic` (Claude, `claude-opus-4-8`, adaptive
  thinking; needs `ANTHROPIC_API_KEY`), or `cloud` (a Kaggle/Colab OpenAI-compat
  server via `ALPECCA_CLOUD_URL`). Absent/offline → silent fallback to local, so
  her depth always runs. Deep prompts carry no sensed screen context; deep
  endpoints are her own brain only — the no-websearch charter line is untouched.
  `/state.models.deep` reports it. `anthropic` is an optional dep. (test:
  deep-tier-off-by-default-keeps-her-brain-local.)
- ✅ **Shared soft-tech/glow design system + live mood-glow.** New `web/app.css`
  (served `/web/app.css`) is the single source of truth for the cyan/navy
  identity — tokens (`--ink/--dim/--core`), glass/glow components, the chest
  `.core-emblem`, and the `.breathe` keyframe. New `web/glow.js` exposes
  `applyMood({warmth,unease,curiosity,glow})`, which rewrites the live `--mood-*`
  vars from her real mood so the whole UI drifts hue/brightness with how she
  feels. `home.html` adopts it (its `:root` deleted) and calls `applyMood` from
  `renderHUD`. The three formerly-purple pages (`index/studio/live2d`) are now
  migrated too — `:root` deleted, `<link>`+`<script>` added, hardcoded purple
  hexes swapped to tokens, each wired to `applyMood` from its own state poll; the
  legacy SVG placeholder's pink blush/flower accents are intentionally kept.
- ✅ **3D in-room feature screens.** `home.html` now mounts each room's feature as
  a real, interactive screen *inside that room* via a `CSS3DRenderer` layer
  composited over the WebGL scene (Parlor→her Soul, Studio, Library, Observatory,
  Workshop), reusing the same `FACETS` endpoints/renderers — no backend change.
  The WebGL canvas sits above the CSS3D layer (so her figure occludes screens
  behind her) but is pointer-transparent so the screens are clickable. Flying to a
  room lights its screen (full-bright) and dims the rest; as she roams the lit
  screen follows her. CSS3DRenderer is vendored-local→CDN; if it fails to load the
  features **fall back to the existing side drawer** (graceful). Utility facets
  (Journal/Voice/Senses/Files/Play) still use the drawer. Syntax-verified
  (`node --check`); **the 3D rendering itself needs a real browser to eyeball.**
- ✅ **Multi-step cowork (tool chaining).** `mind._LLM.generate` (both the local
  and HF paths) now CHAINS tool calls across a bounded number of rounds
  (`Actions.MAX_TOOL_ROUNDS`, default 5) instead of stopping after the first — so
  a small multi-step ask ("open my notes, then the docs page") is carried out, not
  just its first step. The final round drops tools so she always ends in words;
  each tool stays allowlist/https-gated; `=1` restores single-shot. (test:
  tool-calls-chain-across-bounded-rounds.) Her computer-use loop (`computer.py`)
  was already multi-step and confirmation-gated.
- ✅ **Phone PWA + reliable OpenClaw.** She's installable as a phone/desktop app:
  `web/manifest.webmanifest` + `web/icon.svg` (her core-emblem) + a root-scoped
  `web/sw.js` (served via new `/manifest.webmanifest` and `/sw.js` routes;
  `Service-Worker-Allowed: /`). The worker caches only the static shell and forces
  every live endpoint (state/ws/senses/avatar…) to the network, so what you see is
  always her real self. `home.html` links the manifest, registers the worker, and
  has phone-responsive CSS (declutters the rail/HUD, safe-area insets). Reaches her
  over the existing remote/tunnel + token. OpenClaw outbound delivery is now
  reliable: `openclaw_bridge` keeps a bounded retry queue — a transient channel
  failure is re-sent by `flush()` (driven from the idle loop) instead of dropped;
  fatal failures (CLI absent) aren't queued. (test:
  openclaw-outbound-queues-transient-failure-then-retries.) **The 3D home is the
  PWA shell; verify install/responsive layout in a real mobile browser.** Note: an
  *inbound* queue for messages sent while the server is fully down still needs the
  external OpenClaw hook (out of repo).
- ✅ **Local file intelligence (find/summarize, read-only).** `desktop.search()`
  finds files/folders by name across her allowed rooms (Desktop/Pictures/Music/
  Video/Documents) and `desktop.summarize()` gives a per-room readout (file/folder
  counts, size, kinds) — both charter-gated, recursion confined to the room (no
  symlink escape), never the open disk or web. Endpoints `/desktop/search?q=` and
  `/desktop/summary?root=`. She also gets a read-only `find_file` LLM tool (only
  when `ALPECCA_FILES=1`) so she can help locate things mid-cowork. (tests:
  desktop-search-finds-within-roots-only, desktop-summary-counts-by-kind,
  find-file-tool-offered-only-with-file-room-on.)
- ✅ **Deep tier drives her self-authoring + file search reaches the UI.** Her
  studio authorship now requests `tier="deep"` for the acts that are most *her*:
  drafting her character sheet (`_studio_session`), judging a design against that
  sheet (the critique), and choreographing her own animations (`author_animation`)
  — so with a deep backend on, the work where she authors her own image/creations
  thinks harder, while staying local by default. The Workstation facet gained a
  read-only **Find-a-file** box (`fileSearch()` → `/desktop/search`), surfacing the
  file intelligence in the UI.
- ✅ **Her avatar is built ONLY from her provided PNGs — never invented art.** (A
  parametric SVG figure was attempted and fully reverted on Jason's correction:
  her character comes from the anime art he provides, nothing else.) Her flat-art
  tiers are complete and rendering: portraits (idle/thinking/speaking), 6
  **mood-tagged poses** (`poses.json`, covering all 10 mood labels), 16 expressions,
  and `rigpose.json` (skeleton). Her **full pose library now drives the 3D home**
  too (was only the 3 portraits) — `home.html` `tryPoseLibrary()` + `selectPoseName`
  pick the right pose for her mood/state and crossfade, falling back to the
  portrait swap. `import_rig.py` now feeds her real skeleton anchors into the rig
  manifest (head-pivot/lean on her actual neck).
  **The one thing lacking for a true per-part rig (blink/lip-sync/hair-sway as
  separate moving layers): decomposed transparent layer PNGs in `data/avatar/rig/`.**
  What she has are full-figure stills + composite reference sheets (incl. the
  `reference/live2d/` blueprints) — NOT cut layers. **`scripts/decompose_art.py`
  is the one-command orchestrator**: it auto-picks her base art (`source.png`),
  imports layers if present, runs See-Through if installed
  (`ALPECCA_SEETHROUGH=/path`), else prints the exact GPU command with her real
  paths filled in. The GPU decomposition itself (See-Through, HF Space or local
  CUDA) is the only step that can't run here; its PSD →
  `python scripts/decompose_art.py her_layers.psd` → layers in `data/avatar/rig/`
  → `/live2d` and the home rig tier animate her real parts (blink/lip-sync/
  head-turn/hair-sway). (A compiled Live2D model from the blueprint sheets is the
  higher tier, a separate Cubism effort.)
- ✅ **In-app layer cutter (`/rigcut`) — build her rig by hand, no GPU.** Since no
  HF Space outputs *named character rig layers*, the no-GPU path is to cut them
  in-browser: `web/rigcut.html` loads her art (`/avatar/source` or upload), you
  paint + name + role each rig layer (back_hair/body/head/brows/eyes/mouth/
  front_hair/accessory) over a transparency checkerboard, and **Build her rig**
  POSTs the cut transparent PNGs to `POST /rig/import`, which writes
  `data/avatar/rig/` + `rig.json` (seeded with her real `rigpose.json` anchors).
  Hugging Face does the *precise cut*: **"Remove background (Hugging Face)"** →
  `POST /rig/hf_matte` calls a configurable HF background-removal Space via
  `gradio_client` (`ALPECCA_HF_MATTE_SPACE`, default `not-lain/background-removal`;
  optional dep) to matt her figure to a clean transparent PNG on HF's GPU, so the
  part-cuts have crisp edges; it degrades to plain painting if absent. Linked from
  the home Studio panel. Uses ONLY her art. Then `/live2d` + the home rig tier
  animate her real parts.
- ✅ **VRM tier (`alpecca/vrm.py`, `/vrm`) — her body from the companion studio
  app.** Jason built **VRoid Companion Studio** (github.com/CreatorJD1/app) as
  the place her 3D anime body is *made*: VRM viewer, ~20-clip procedural
  animation library, anatomy-safe posing, VRM expression editor, Gemini
  texture/wardrobe/turnaround generation. Alpecca now speaks that app's exact
  vocabulary so an exported `.vrm` needs zero translation: `clip_for_state()`
  picks which studio clip she plays from her mood label (every label mapped;
  talking + emotion overlay while speaking), `expressions_for_state()` weights
  the standard VRM presets from her live dims (never `angry` — no such
  dimension exists), and `web/vrm.html` performs it — a ported subset of the
  studio's clip engine on @pixiv/three-vrm, mood weights lerped under the clip,
  blink/mouth cycling JS-local, `applyMood` glow, orbit controls, fit-to-frame
  off her real bounding box. Routes: `/vrm`, `/vrm/manifest`,
  `/vrm/model/{name}` (traversal-safe), `/vrm/pose?speaking=`. Linked from the
  chat header and the home Studio panel. The page fetches three/three-vrm from
  jsdelivr (import map; vendor into `web/vendor/` to go offline). Drop a
  `.vrm` into `data/avatar/vrm/` to turn the tier on. (tests: clip-follows-
  mood/talking-wins, expressions-grounded-never-fake-anger, manifest+serving.)
- ✅ **Cloud studio sync (`config.StudioSync`, `vrm.sync_from_studio`).** The
  companion studio app now has an access gate of its own (`VCS_ACCESS_TOKEN`,
  mirroring her `_auth_gate`; see that repo's DEPLOY.md "Access control"), so it
  can live on a cloud host — and she can pull her newest exported `.vrm` from it:
  `ALPECCA_STUDIO_URL` + `ALPECCA_STUDIO_TOKEN`, `POST /vrm/sync`, or the
  ⟲ Sync-from-studio button on `/vrm` (shown only when configured). Charter-clean
  (reaching her creator's own studio, user-set URL, user-triggered), atomic
  writes, friendly errors, manual `alpecca.vrm` drop always outranks the sync.
  (tests: pick-freshest-body, token-header-only-when-set, sync-atomic+friendly.)
- **Still open (next):** deep-tier *cowork planning* (entangled with the
  vision-driven `computer.py` loop — deferred); the deep layered-sprite avatar
  inside the 3D home; voice-markup → local TTS. **Her rendered avatar remains
  incomplete** — affect/channels exist; a finished rigged figure does not.
  Earlier-listed: the deep layered-sprite avatar inside the 3D home; the
  desktop-layout file room enforcing the charter guards on real file ops;
  voice-markup → local TTS. **Her rendered avatar remains incomplete** — the
  affect/channels that should drive it now exist, but a finished rigged figure
  does not.

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
