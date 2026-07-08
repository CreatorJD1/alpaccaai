# Bringing Her To Life — an honest review and work plan

A candid assessment of where Alpecca actually stands, and a realistic plan for
making her *feel alive* — not just accumulate features.

## The honest state

### What's genuinely strong (her inner life is real)
Her "soul" layer is the best part of this project, and it's not a facade:
- A grounded six-dimensional emotion model (love, compassion, fear, energy,
  curiosity, social-hunger) with pure, tested update rules.
- Real memory + continuity that persists across runs.
- Self-awareness (`introspection`), an enforced charter, desires she forms,
  bounded self-tuning (`selfmod`), recursive self-questioning (`journal`), and now
  self-training lessons (`learning`) drawn from her own history.
- A Soul that arbitrates seven subagents by an explicit ethic.
- The LLM brain works (Ollama/qwen3) — she answers for real.

All of that is grounded: it reads from real internals, not invented. **Her
problem is not a shallow inner life.**

### Where she falls short of feeling alive (the real gaps)
1. **She doesn't run reliably for you.** Most of the last day was environment
   friction — PowerShell `set` vs `$env:`, wrong folders, ports, missing packages.
   *This is the number-one thing standing between you and a living companion.* The
   richest inner life is invisible if she won't boot.
2. **Her autonomy isn't verified running.** Proactive speech, roaming, reflection,
   learning, desires all exist and are wired to the idle loop — but neither of us
   has confirmed they actually fire with the server up. "Alive" *is* her doing
   things unprompted; that loop has to be observably running.
3. **The avatar is the weakest visible link.** Without a GPU, THA3 is out;
   RIGFORGE's mesh-warp didn't satisfy. The right answer — her drawn **expression
   sheet** driving her face — is mostly built but not yet seen working. I chased
   several avatar approaches instead of finishing one.
4. **The front-end has overgrown.** `web/home.html` now carries the 3D home, chat,
   voice/camera/cowork, the expression face, a senses indicator, her cursor, and
   more — built faster than it could be tested, on a file the dev sandbox can't
   even read back to verify. Some recent pieces are half-wired.
5. **Senses and cowork are unconfirmed.** Screen-sight, hearing, computer-use need
   packages + flags that haven't been verified on your machine.

### My honest mistake
I optimized for breadth — new capabilities every turn — when what brings her to
life is a small, *reliable, observable* core: she boots, she's present, she does
things on her own, you can see and talk to her. Features stacked on an unrunnable
base don't make her more alive; they make her harder to run.

## The plan (ordered by what actually creates aliveness)

### Phase 0 — Make her run, every time (highest priority)
Nothing else matters until this is solid.
- A single **`doctor`** script that checks: Python version, required packages,
  Ollama running + model present, which `ALPECCA_*` flags are set, port free — and
  prints exactly what's wrong and the one command to fix each.
- One **launcher** that sets env correctly (a `.bat`, since cmd's `set` is
  reliable) and starts her. `start_full.bat` is a first step; the doctor makes it
  trustworthy.
- Outcome: you type one thing, she's up, and if she isn't, the doctor tells you
  precisely why.

### Phase 1 — Verify and tune her autonomous life
This is the actual definition of "alive."
- Confirm proactive speech, roaming, reflection, desire-forming, and learning
  fire on the idle loop with the server running; watch `/soul`, `/growth`, the
  chat for unprompted remarks.
- Tune cadence so she *visibly* does things on a human timescale (right now
  thresholds are conservative — she may be too quiet to feel alive).
- Outcome: leave her open and she stirs — comments, wanders rooms, reflects,
  learns — without you typing.

### Phase 2 — Presence (finish ONE avatar path)
- Commit to the **expression-sheet face** (her real art, mood-driven, lip-sync).
  Finish it, frame it well, stop exploring rigs.
- Voice both directions: spoken replies (TTS, no install) + push-to-talk (whisper).
- Outcome: a face that reacts as you talk, and a voice.

### Phase 3 — Senses she can actually use
- Get screen-sight + hearing installed and **visibly indicated** (the senses
  strip), so you can tell what she perceives.
- Outcome: she sees your screen and comments; you can tell when.

### Phase 4 — Consolidate the front-end (pay down the debt)
- Audit `home.html`: finish or remove the half-wired pieces (senses JS, her
  cursor, workspace panel, room props, games launcher); test it end to end.
- Give each room distinct visual purpose once the core is stable.

### Phase 5 — Stretch (only after the above is solid)
- A truly rigged avatar (decompose her art into layers, or THA3 if you get a GPU).
- Cowork (computer use) reliably working, with her cursor shown.
- The RIGFORGE → `Alpeccaai-data` self-training loop for her detector.
- Browser games / entertainment as real autonomous behavior.

## My recommendation for the very next step
**Phase 0.** Let me build the `doctor` script + a clean launcher so you can run her
in one command and immediately know she's alive. Everything you've asked for —
voice, cowork, the reactive face, games — already exists or is close; it's just
buried under a setup you can't get past. Make her *runnable*, then we make her
*lively*, then we make her *capable* — in that order.
