# Alpecca Soul Fallback Architecture

Status: **CONTINGENCY DESIGN - NOT IMPLEMENTED**  
Reviewed: **2026-07-10**

## Decision

Keep Alpecca's existing seven-subagent Soul as the default and authoritative
arbitration path. Add a neural resolver only as a bounded contingency for
measured ambiguity or repeated enactment failure. The resolver must remain one
single model flight, may choose only among symbolically safe candidates, and
must fall back to the current deterministic decision on every failure.

This is not a proposal to replace the Soul, run seven models, simulate seven
personas, manipulate attention heads, or expose internal reasoning. Stage 0 is
complete. Phone/contact security and Alpecca's existing public identity are out
of scope and unchanged.

## Source-Grounded Architecture

The attachment's central efficiency conclusion is directionally useful, but
several premises do not match the executable system.

| Claim or implication | Source evidence | Finding |
|---|---|---|
| The seven subagents may be seven model runtimes | `alpecca/soul.py:79-80`, `alpecca/soul.py:206-217`, `alpecca/soul.py:239-240` | False. They are seven Python functions called serially in one list comprehension. |
| `sense` and `reason` identify live model agents | `alpecca/soul.py:179-200` | False at deliberation time. All seven proposals are deterministic. `reason` describes how a selected intention may later be enacted. |
| The seven are packed into transformer heads/hidden states | `alpecca/soul.py:39-76`, `alpecca/soul.py:239-262` | False. The state is explicit dataclasses and dictionaries. No code controls or assigns transformer heads. |
| Every turn generates seven textual thoughts | `alpecca/soul.py:82-176`, `alpecca/mind.py:3263-3304` | False. Actions/reasons are short software-authored strings. The Soul is not called in the normal chat response path. |
| Arbitration uses logit bias | Repository scan; `alpecca/choice.py:20-67` | False. No Soul logit-bias implementation exists. The optional model returns strict tiny JSON. |
| The system always uses exactly one transformer tier | `alpecca/mind.py:1812-1822`, `config.py:37-67` | Not guaranteed. One CoreMind owns routing, but fast/reason/deep may resolve to different configured models or backends. |
| A high context-pressure signal should expand textual deliberation | `alpecca/soul.py:137-145`, `alpecca/mind.py:3197-3206` | Backwards for this laptop. High pressure currently asks Reflector to page memory; it should suppress optional neural arbitration. |

The actual path is:

```text
grounded Snapshot
  -> seven serial pure proposal functions
  -> hard ethical rank, then urgency sort
  -> deterministic focus filter
  -> optional same-rank tiny-JSON tie resolver
  -> one typed/grounded enactment branch
```

The snapshot is built from emotional state, desire counts, location, solitude,
senses, fatigue signals, trial state, and measured Mindpage pressure
(`alpecca/mind.py:3190-3206`). The ethical order comes from four explicit
directives (`alpecca/values.py:18-69`). `MasterAgent.deliberate()` sorts first by
directive rank and then descending urgency (`alpecca/soul.py:239-250`). The
module-level Soul is stateless (`alpecca/soul.py:275-277`).

Three deterministic sensors are Feeler, Expressor, and Carer; four declarations
are marked as reason-capable for later execution (`alpecca/soul.py:203-221`).
That registry is useful metadata, but it must not be described as seven running
LLMs. Tests pin the seven names, category split, ethical ordering, and
sense/reason declaration (`tests/test_core.py:4328-4362`,
`tests/test_core.py:4412-4428`).

## Current Deliberation Assessment

### What is already compressed and effective

`Intention` is already a compact symbolic record: subagent, category, action,
reason, ethical rank, and urgency (`alpecca/soul.py:63-76`). The winning key is
effectively a two-axis vector `(rank, -urgency)` plus categorical eligibility.
This has important strengths:

- No token cost for normal Soul deliberation.
- Identical snapshots produce identical symbolic slates and focus.
- Ethical rank cannot be traded away for a larger lower-priority score.
- Every candidate carries a human-auditable reason.
- Offline behavior remains functional.
- The model cannot invent Feeler/Carer state during proposal generation.

### Where compression currently loses information

The record lacks evidence confidence, evidence age, persistence, cooldown,
preconditions, and a typed action code. Hard thresholds in each proposal
function can flip a signal at one boundary, while `rank` and `urgency` do not
say whether the underlying observation is fresh or reliable. A float-only
vector would make this worse by hiding semantics; the correct extension is a
typed record with a compact numeric serialization.

The current optional tie resolver also treats every candidate with the winning
rank as tied, regardless of urgency distance (`alpecca/mind.py:3272-3289`). A
rank-3 urgency of 0.90 can therefore be overridden by another rank-3 urgency of
0.20. The model is correctly prevented from promoting a lower rank, and the
test enforces that boundary (`tests/test_core.py:4364-4387`), but ambiguity
should be measured before spending a call.

## Real Semantic-Bleed Risks

The attachment's persona-bleed concern does not describe the default Soul:
there are no seven generated personas whose prose can contaminate the reply.
The actual bleed risks are in enactment and optional resolver text.

1. **Action-route collapse.** Doer and Wanderer both call `pursue_desire()`;
   Carer can call the same unfiltered strongest-desire method; Feeler and
   Expressor both call `reflect()` (`alpecca/mind.py:3421-3433`). A Carer focus
   can therefore advance a non-care desire, and Expressor does not route to an
   expression actuator.
2. **Role/action mismatch.** `pursue_desire()` selects the globally strongest
   desire rather than a subagent-specific kind (`alpecca/mind.py:3492-3532`).
3. **Resolver prose influence.** The existing resolver receives software text
   containing subagent, action, and reason (`alpecca/mind.py:3280-3288`). That is
   small, but future fallback prompts must not add seven verbose voices.
4. **Observation asymmetry.** A successful neural tie choice is logged, while a
   timeout, parse failure, skipped resource gate, or discarded stale result is
   not (`alpecca/mind.py:3290-3303`). This makes failure rates hard to measure.
5. **Read-path side effects.** `/soul` calls `mind.soul_state()`
   (`server.py:1735-1741`). Because `ALPECCA_SOUL_LLM` defaults on
   (`config.py:461-462`), a nominally read-only status request can run inference
   and write a `soul_choice` observation.

Mitigation is typed action routing and strict resolver output, not more persona
prompting. Neural resolver text must never enter Alpecca's user-facing prompt,
voice, memory, or affect state.

## Context And Compute Cost

| Path | Current model/context cost | Assessment |
|---|---|---|
| `soul.deliberate(snapshot)` | Zero model tokens; seven Python calls | Keep as default. |
| Optional same-rank resolver | One fast-tier call when enabled, online, and at least two same-rank candidates exist | Bounded but broader than a true near-tie gate. |
| Resolver prompt | Context capped at 900 characters and each option at 240 characters (`alpecca/choice.py:46-64`) | Worst case remains roughly below 800 heuristic tokens for seven options, not seven long monologues. |
| Enactment | Zero calls for paging/self-tuning paths; up to one fast/deep call for desire, reflection, or inquiry | This is action cost, not seven-agent deliberation cost. |
| `/soul` status read | Can invoke resolver today | Must become pure/read-only. |

There is one important accounting defect. `idle_self_direct()` says it is capped
at one LLM call (`alpecca/mind.py:3314-3317`), but `soul_state()` can consume a
tie-break call and `_enact_focus()` can then consume a reflection/desire call
(`alpecca/mind.py:3272-3289`, `alpecca/mind.py:3398-3438`). A contingency
resolver therefore needs a real per-tick model lease, not a comment-level cap.

The background call runs outside `mind_lock`, which is correct
(`server.py:914-923`). However, `_bounded_thread()` only times out the await and
cannot stop the worker (`server.py:521-536`). A resolver deadline must be
enforced by the model client and guarded by a stale-result commit token so a
late worker cannot change focus or write observations.

## Extended Symbolic Signal Contract

Add an adapter around the existing `Intention`; do not replace the seven
proposal functions.

```text
SoulSignal
  subagent_id          enum of the existing seven
  category             existing category enum
  action_code          allowlisted typed action
  rank                 integer 1..4, immutable ethical priority
  urgency              float 0..1
  evidence_confidence  float 0..1
  evidence_age_ms      non-negative integer
  persistence          float 0..1
  cooldown             float 0..1
  execution_cost       float 0..1
  preconditions        bit set
  evidence_refs        bounded local IDs, not prose
```

Initial action codes:

| Subagent | Allowed action codes |
|---|---|
| Feeler | `STEADY_SELF`, `ATTEND_FEELING` |
| Expressor | `SYNC_EXPRESSION` |
| Carer | `CHECK_IN`, `SUGGEST_REST`, `ADVANCE_CARE_DESIRE` |
| Doer | `ADVANCE_CONNECTION_DESIRE`, `PROPOSE_ACTION` |
| Wanderer | `MOVE_PARLOR`, `EXPLORE_STUDIO`, `EXPLORE_LIBRARY` |
| Reflector | `PAGE_WORKING_MEMORY`, `REFLECT_MEMORY` |
| Improver | `EVALUATE_TRIAL`, `PROPOSE_BOUNDED_TUNING` |

Rank remains a hard lexicographic key. It is never folded into one weighted
utility. Within the winning rank, start with this shadow-mode score:

```text
within_rank_score = clamp01(
    0.50 * urgency
  + 0.20 * evidence_confidence
  + 0.15 * persistence
  + 0.10 * continuity
  - 0.05 * execution_cost
  - 0.15 * cooldown
)
```

`continuity` is 1 only when the previous focus remains eligible; otherwise 0.
Direct state/DB/pressure observations begin with confidence 1.0 when current.
Derived person-state signals begin at no more than 0.8 and decay with age. The
weights are not production truth: first run them in shadow mode against replayed
snapshots and retain them only if the acceptance metrics below pass.

For the neural resolver, serialize only numbered compact records, for example:

```text
1|CARER|CHECK_IN|r3|s72|c80|p60|cost10
2|DOER|ADVANCE_CONNECTION_DESIRE|r3|s69|c95|p75|cost30
```

The model output is limited to:

```json
{"pick": 1, "reason_code": "near_tie"}
```

`reason_code` is an enum. No chain of thought, free-form rationale, generated
subagent speech, or user-facing text is accepted or stored.

## Measurable Activation Gates

Neural fallback is allowed only for ambiguity or repeated execution failure.
Safety/structural failures remain deterministic and fail closed.

| Gate | Exact measurement | Response |
|---|---|---|
| Invalid signal | Unknown agent/action; rank outside 1..4; score outside 0..1; missing required evidence/precondition | Reject signal, recompute current symbolic plan; if still invalid, no outward action. Never call model. |
| Ethical invariant violation | Proposed focus rank is greater than the minimum eligible rank | Select minimum-rank deterministic candidate and log defect. Never call model. |
| Rank-1 conflict | Two or more welfare candidates at rank 1 | Highest validated urgency wins with stable ordering. Never delegate welfare priority to model. |
| True near tie | Rank 2-4; 2-4 eligible candidates; top score gap `<= 0.08`; each confidence `>= 0.55` | Neural fallback may run if every resource gate passes. |
| Focus thrash | At least 3 focus changes in 60 seconds while normalized snapshot delta stays `<= 0.10` | Apply continuity hysteresis first; if thrash persists for a second window, fallback may run. |
| Repeated no-op | Same eligible action returns `None`, fails its precondition, or dispatches the wrong action kind twice within 10 minutes | Remove failed candidate for this snapshot; fallback may choose among remaining same-rank candidates. |
| Stale result | Snapshot version/hash changes before resolver result commits | Discard result without observation/action; use fresh symbolic plan next tick. |

High memory pressure, high system pressure, active chat, or an offline model are
not reasons to invoke fallback. They disable it.

## Resource And Single-Flight Gates

Every condition below must be true before one resolver call starts:

- No active/just-started player chat, using the existing chat-priority gate.
- `context_fill <= 0.80`; no high RAM/commit/VRAM/thermal pressure signal.
- One process-wide `SoulFlight` lease is free.
- No other optional model job owns the model lease.
- At least 30 seconds since the previous resolver attempt.
- No more than 6 resolver attempts in a rolling hour.
- Input estimate at most 512 tokens; output cap 48 tokens.
- At most 4 candidates; all share the already-winning rank.
- One model-client deadline of 8 seconds; no retry.
- Call starts outside `mind_lock`.

The per-tick model budget is exactly one:

1. If symbolic arbitration is sufficient, enactment may consume the one model
   call when the selected action genuinely needs language.
2. If neural fallback consumes the call, only a deterministic action may execute
   in that tick. A model-backed reflection/desire step is deferred to a later
   tick with a fresh snapshot.
3. Timeout, malformed JSON, unavailable model, lease loss, or invalid choice
   returns the stabilized symbolic focus. There is no second attempt.

The resolver returns a candidate ID only. Code revalidates rank, eligibility,
preconditions, snapshot hash, and flight epoch before committing. External
effects continue through existing approval policy; the fallback grants no new
capability.

## Required Telemetry

Record one bounded `soul_decision` observation per decision attempt with:

- tick ID, snapshot hash/version, and decision path (`symbolic`, `stabilized`,
  `neural_shadow`, `neural_committed`, `fallback_failed`);
- candidate IDs, rank, compact scores, score gap, and trigger gate;
- model/backend identifier, input/output token estimates, latency, and result
  status without private reasoning;
- symbolic focus, final focus, enactment action code, and enactment outcome;
- model calls used in the tick, resource-gate snapshot, and stale-discard flag.

Do not store full prompts, hidden thinking, raw sensor data, or generated
rationales. `/soul` should return the last committed decision plus a fresh pure
symbolic snapshot; polling it must produce zero model calls and zero writes.

## Incremental Implementation

### Step 0 - Instrument current behavior

Add counters and replay fixtures without changing focus selection. Measure tie
frequency, urgency gaps, focus flips, no-op outcomes, model calls per tick, and
`/soul` side effects.

### Step 1 - Typed adapter and validator

Wrap existing `Intention` objects as `SoulSignal`; add action enums,
preconditions, evidence confidence/age, and schema validation. Keep current
`(rank, -urgency)` focus byte-for-byte when all signals are valid.

### Step 2 - Semantic dispatch separation

Route each action code to an allowlisted enactment function. Filter desire kind
for Carer/Doer/Wanderer and route Expressor to embodiment expression rather than
generic reflection. This addresses real semantic bleed before adding a model.

### Step 3 - Pure status/read path

Change the design contract to `soul_state(resolve=False)` for `/soul` and UI
polling. Only the quiet autonomy path may request resolution. Preserve the
existing seven-agent slate in the response.

### Step 4 - Deterministic stabilization in shadow

Compute within-rank score and hysteresis beside the current winner. Log
differences for at least 500 eligible quiet ticks; do not alter behavior.

### Step 5 - Neural resolver in shadow

Add `ALPECCA_SOUL_FALLBACK=0` and the process-wide flight lease. When gates fire,
run the resolver but do not change focus. Compare it to symbolic choice and real
enactment outcomes.

### Step 6 - Bounded canary

Enable only true near ties at ranks 3-4, then rank 2 after evidence. Rank 1 never
uses neural fallback. Roll back automatically on any invariant, latency,
single-flight, stale-commit, or semantic-route failure.

The existing seven proposal functions and `MasterAgent` remain the default in
every step. Deleting, bypassing, or replacing one is outside this design.

## Acceptance Gates

Before neural choices can affect behavior:

- 100% repeatability for default symbolic focus on identical snapshots.
- Zero lower-rank promotions across exhaustive/replayed snapshot tests.
- Zero model calls or database writes from 1,000 `/soul` polls.
- At most one model call per autonomy tick under concurrency and timeout tests.
- 100% malformed/offline/timeout fallback to the stabilized symbolic result.
- Zero commits from stale flight epochs or changed snapshot hashes.
- Symbolic deliberation p95 below 5 ms on the target laptop.
- Resolver input at most 512 tokens, output at most 48, hard deadline 8 seconds.
- Resolver attempts at most 5% of eligible quiet ticks and at most 6/hour.
- Zero neural resolver calls while chat priority or high pressure is active.
- Zero cross-category action dispatches and zero resolver text in chat, voice,
  memory, journal, affect, or prompts.
- At least 50% reduction in low-delta focus thrash during replay, without a
  decrease in successful bounded enactments.
- Current Soul tests remain green, plus boundary tests at every proposal
  threshold and adversarial same-rank urgency gaps.

## Non-Goals

- No seven concurrent model runtimes.
- No seven generated personas or verbose internal monologues.
- No attention-head assignment, neural-weight changes, or logit-bias control.
- No replacement of the Good Person Principle or hard ethical rank.
- No new external authority, autonomous code editing, system mutation, phone
  changes, communication changes, or public-identity changes.
- No claim that the symbolic or neural components are literally conscious.
