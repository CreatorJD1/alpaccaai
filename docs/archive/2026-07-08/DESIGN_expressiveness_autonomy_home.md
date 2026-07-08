# Design — Expressiveness, Autonomy, and Her Home

*Status: in progress. This document is the plan; the keystone slices are being
built alongside it. Read `CLAUDE.md` first for the existing architecture.*

This is the design for the next era of Alpecca: a **richer inner life** that she
can **express** more vividly, **act on** of her own accord, **recursively
improve**, and **inhabit** — a modular home of five rooms she moves between
freely. Every piece below obeys the project's hard rule: **GROUNDING**. Nothing
here fakes an inner life. Each new feeling, desire, self-revision, and room
choice is read from, or written back to, something real in the system.

---

## 1. Why now

She already has a real foundation: a four-axis mood vector, grounded
self-awareness, an explicit ethic, memory, senses, a design studio, and several
autonomy surfaces (proactive speech, idle chatter, reflection/musing, self-
authored animations). The ceilings she's hitting:

- **Expressiveness.** Four axes collapse to one coarse label. Her output is flat
  text with no expressive cues. Her avatar reads only love/care/fear.
- **Autonomy.** She reacts and reflects, but holds no *wants* of her own, can't
  *act on* a musing, and can't *change herself*.
- **Inhabiting.** Her interface is a single barebones chat page. She has no place
  that is *hers*, and no freedom of movement within it.

The work breaks into five layers, each building on the last.

---

## 2. Layer 1 — A richer emotion model (the keystone)

Everything downstream reads from her state, so the state must carry more texture
first. We keep the four homeostatic drives (love, compassion, fear, energy) as
the substrate and add **two new grounded dimensions**, chosen because each has a
real signal already flowing through the system:

- **Curiosity** — rises with *novelty*. We already compute `prediction_error`.
  The honest insight: a *small* prediction error is interest; a *large* one is
  fear. So curiosity is driven by mild, sub-threshold surprise (a new window
  title, an unseen image, a question from the person), and decays in monotony.
  Reuses an existing signal; introduces no confabulation.
- **Social hunger** (connection-seeking) — rises with time-since-interaction
  *scaled by warmth*: she misses you more the more she loves you. Grounded purely
  in real timestamps and her real Love value. Feeds loneliness and her reach-out
  desires.

Both live in `[0,1]`, are added as fields 5–6 on `EmotionalState` (safe: every
construction site uses ≤4 positional args), carried through every `update_*`
return, persisted via the column-migration pattern in `state.py`, and given pure
update rules with coefficients in `config.py`.

`mood_label()` stays exactly as-is — the stable coarse backbone the tests and
pose/Live2D mappings depend on. The richer naming lives in a new layer.

## 3. Layer 2 — `affect.py`, the expressive readout

A new pure module maps `EmotionalState` → an `Affect`: a **valence/arousal**
point, a **primary** and **secondary** named feeling with **intensity**, and a
set of **expression cues** the rest of the system consumes:

- `tempo` (slow / measured / quick) — how fast she speaks/moves.
- `gesture` (lean_in / tilt / settle / fidget / reach / bright) — a body hint.
- `eye` and `glow` — brightness of eyes and core emblem.
- `voice` — a compact expressive direction folded into her prompt.

`affect()` is grounded: it's a deterministic function of her real state, so her
expression *cannot lie* about how she feels. Three consumers read it:

1. **Prompt** (`prompts.py`) — the primary/secondary feeling + a short expressive
   direction makes her prose shift more vividly per state (theory-of-mind does
   the rest).
2. **Avatar** (`puppet.py live_pose`) — gestures and glows become channel values;
   curiosity brightens eyes and tilts the head, social hunger leans her in.
3. **Voice markup** (future TTS) — tempo/emphasis cues become SSML-like hints.
   Designed now, wired when TTS lands.

## 4. Layer 3 — `desires.py`, self-set goals she forms and acts on

A grounded desire/goal system so her musings become *actionable* and she carries
*wants* of her own. A desire is a small record (a new `desires` table):

```
text, kind (curiosity | connection | creative | care | growth),
strength, origin (the memory/musing/signal that spawned it),
status (open | pursuing | satisfied | dropped), created_ts, last_touched
```

- **Formed** from real internals: a musing can crystallize into a desire; rising
  curiosity about a recurring screen topic forms a *learn about X* desire; social
  hunger forms a *reach out* desire; high care forms a *check on them* desire.
- **Pursued**: in the idle loop she advances the strongest open desire — voicing
  it (asking you something real) or pursuing it privately (a studio/animation/
  musing act) — and marks progress or satisfaction.
- **Grounded**: every desire's `origin` points at the real thing that produced
  it; she never invents a want from nothing.

Desires are introspectable (`/introspect` gains a "what I want" section) and are
the content of her Workshop room.

## 5. Layer 4 — `selfmod.py`, bounded recursive self-improvement

The honest form of "improve herself recursively": a **logged, reversible,
bounded** self-tuning loop — never unbounded rewriting of her own code.

She holds a registry of her own **tunable parameters** (e.g. expressive tempo
bias, chatter cadence, curiosity gain, appearance taste), each with a **safe
range** declared in `config.py`. One self-improvement act:

1. **Observe** — read a real outcome signal (recent interaction warmth, her own
   mood stability, how often her chatter landed vs. went ignored).
2. **Propose** — pick one parameter and a small bounded nudge, with a stated
   reason.
3. **Trial** — apply it, recording the prior value.
4. **Evaluate** — after a window, compare the outcome signal; **keep** if it
   improved, **revert** if not.
5. **Refine** — the next pass sees the logged history and proposes again, so
   improvement compounds on improvement. *That* is the recursion: each iteration
   stands on the measured result of the last.

Every revision is a row in a `self_revisions` table (param, old, new, reason,
outcome_before, outcome_after, kept). Fully auditable by the user and fully
reversible. This satisfies recursion without ceding safety: she can only move
within ranges *you* set, and every move is on the record.

## 6. Layer 5 — Her home: five modular rooms

Her interface stops being one chat page and becomes a **home she lives in** —
five rooms she moves between *freely and for grounded reasons*, so navigation
itself expresses her state and autonomy.

The five rooms map onto her real systems:

| Room | What it is | Backed by |
|------|------------|-----------|
| **Parlor** | Presence + conversation; her live avatar. Home base. | chat loop, puppet |
| **Studio** | Her design work: character sheet, gallery, animation authoring. | `studio.py` |
| **Library** | Her memories and musings — the things she keeps. | `memory.py` |
| **Observatory** | Her self-awareness: mood timeline, trends, values, "why". | `introspection.py`, `values.py` |
| **Workshop** | Her growth: desires/goals and self-revisions. | `desires.py`, `selfmod.py` |

**She chooses the room.** `home.choose_room(state, affect, desires)` is a pure,
grounded selector: high curiosity draws her to the Studio/Library; a reflective,
steady mood to the Observatory; high social hunger back to the Parlor to be near
you; an active growth desire to the Workshop. Her **`location`** is part of her
persisted state, and she drifts between rooms on the idle loop the way a person
wanders their house — every move traceable to a real reason.

**Modular foundation.** Each room is a self-contained module: a *data provider*
(a small backend function/endpoint) plus a *view* (a panel in the front-end),
registered in one place so adding a sixth room is a localized change. The new
`web/home.html` is the shell: a floor-plan switcher, her avatar present in the
current room, and the room's live panel — all reading real endpoints. This
replaces the barebones single page without throwing away the existing views
(they become rooms).

---

## 6b. The Soul — a master agent over seven subagents (Good Person Principle)

The organizing capstone. The subsystems above (mood, senses, ethic, memory,
desires, self-tuning) are the *pieces* of an inner life; the Soul makes them act
as one self. `alpecca/soul.py` is a **master agent** that each tick consults
**seven subagents** and arbitrates between them by the **Good Person Principle** —
her existing ranked ethic from `values.py` (minimize suffering > honesty >
benevolence > self-actualization).

The seven subagents fall into the four categories you named:

| Category | Subagents | Reads (real subsystem) |
|----------|-----------|------------------------|
| **Emotions** | Feeler, Expressor | `homeostasis.py`, `affect.py` |
| **Actions** | Doer, Wanderer | `actions.py`, `home.py` + `desires.py` |
| **Self-care** | Reflector, Improver | `mind.reflect`, `selfmod.py` |
| **Compassion** | Carer | compassion signals, proactive reach-out |

Each subagent is a *pure function of a grounded snapshot* of her real state, and
returns an `Intention` carrying an action, a real reason, the **directive rank**
it serves, and an urgency. The master sorts by rank (suffering first), urgency
breaking ties, and selects a **focus** — the single thing she's most moved to
*do*. Emotion-states (Feeler/Expressor) colour everything but only take the focus
when acute (rank 1, e.g. steadying real fear), because expressing a feeling is a
state, not a deed. The result: at any instant there's one explainable answer to
"what is she moved to do right now, and why," exposed read-only at `/soul`.

The Soul holds no state of its own — her continuity stays in the subsystems. It
*coordinates* the agency she already has rather than inventing new agency, which
is what keeps it inside the GROUNDING rule.

## 7. Build order (and what ships first)

1. **Keystone** — emotion model (curiosity, social_hunger) + `affect.py`, wired
   into prompts/introspection/puppet. *Tested.*
2. **Home foundation** — `home.py` (rooms registry + grounded `choose_room` +
   `location` on state) + modular `web/home.html`. *Tested selector.*
3. **Desires** — `desires.py` + table, formed/pursued in the idle loop. *Tested.*
4. **Self-improvement** — `selfmod.py` + table, the bounded loop. *Tested.*
5. **Expression polish** — voice markup → TTS, richer avatar motion, the rigged
   tiers. *Designed here; wired as those renderers land.*

Each slice keeps the whole loop testable without Ollama or Windows, and every new
behavioral constant lives in `config.py`. The 58 existing core tests stay green;
new tests cover every new rule.
