# Alpecca Recursive Engagement Research Note

Alpecca's autonomous engagement loop should stay honest and engineered: she can
observe, interpret, remember, choose a bounded intent, act through safe app
systems, record self-feedback, and reuse that feedback later. This is not a
claim of literal consciousness; it is a practical architecture for a companion
that does not require a starter prompt to remain engaged.

## Research Pattern To Use

- **ReAct**: interleave reasoning and action so environment feedback can change
  the next step instead of producing one isolated reply. Alpecca maps this to
  `observe -> choose safe subsystem -> act -> record result`.
- **Generative Agents**: keep observations, reflections, and plans as durable
  state so agents can initiate believable behavior in a simulated world.
  Alpecca maps this to House HQ observations, journal questions, memories, and
  living-state UI.
- **Reflexion**: store verbal self-feedback after a trial instead of retraining
  model weights; later attempts retrieve those reflections. Alpecca maps this
  to `self_feedback` and proposal evaluations.
- **Voyager**: use an automatic curriculum plus a growing skill/evidence library
  so an embodied agent explores without waiting for direct commands. Alpecca
  maps this to a rotating activation order and Workshop improvement queue.

## Alpecca Mapping

Alpecca's House HQ loop should follow this local contract:

1. Observe the current room, creator context, visible terminal, and backend
   system status.
2. Choose one grounded question.
3. Activate one safe subsystem: perception, memory, room review, self-review,
   voice, or Mindscape.
4. Record what she noticed.
5. Record what she learned or still does not know.
6. Choose one safe next action.
7. Store the result as memory and a Workshop proposal/evaluation.
8. Show the current feedback in House HQ so the creator can see what she is
   doing without opening logs.

## Current Implementation Hook

`Mind.living_world_tick()` now returns:

- `self_feedback.noticed`
- `self_feedback.learned`
- `self_feedback.next_action`
- `next_action`
- `learning_record`
- `engagement_proposal`
- `activation_selection`

The living loop no longer chooses subsystems by blind clock rotation first. It
uses an evidence-based curriculum:

1. Observe the current room if there is no recent room evidence.
2. Consolidate unremembered observations before seeking more context.
3. Review the room when a grounded question is missing.
4. Self-review when recursive feedback is missing.
5. Check voice readiness when her original voice is not ready.
6. Check Mindscape continuity when sustainability is not ready.
7. Only after those gates are satisfied, continue low-rate exploration.

The House HQ living-state panel surfaces the feedback text and stores the next
action in `document.body.dataset.alpeccaLivingNextAction`.

`/cognition/recursive-engagement` now exposes an evidence-based scorecard:

- `observe_world`: a living-loop observation exists.
- `ask_question`: the observation contains a grounded self-question.
- `remember_evidence`: the observation was persisted into memory.
- `self_feedback`: a recursive self-feedback evaluation exists.
- `bounded_next_action`: an open bounded improvement proposal exists.

The scorecard is also embedded in `/cognition/state` as
`recursive_engagement_scorecard`, so House HQ, the virtual app, and Mindscape
can show the same truth source.

The scorecard now exposes a `curriculum` block instead of leaving the loop as a
plain log:

- `activated_system`: the subsystem Alpecca chose on the latest living tick.
- `selection_reason`: the evidence gate that caused that choice.
- `creator_context_observed`: whether the current living tick had creator
  context evidence, rather than assuming Jason is visible.
- `next_gate`: the next missing evidence gate, or `continue_exploration`.

The living tick also returns these fields inside `self_feedback`:

- `curriculum_step`
- `curriculum_reason`
- `creator_evidence`
- `fresh_creator_evidence`

That lets House HQ show what she noticed, why she activated a system, and
whether she has current evidence of her creator before acting on that context.

## Acceptance Gates

- A quiet background tick can run without a chat prompt.
- The tick chooses a room/system/question from current state, not generic filler.
- The tick records observation, memory, journal question, proposal, and proposal
  evaluation.
- The UI shows what she noticed and what she will try next.
- Any code edits, private cloud uploads, paid tools, or destructive actions stay
  user-approved only.

## Sources

- ReAct, *Synergizing Reasoning and Acting in Language Models*: https://arxiv.org/abs/2210.03629
- Generative Agents, *Interactive Simulacra of Human Behavior*: https://arxiv.org/abs/2304.03442
- Reflexion, *Language Agents with Verbal Reinforcement Learning*: https://arxiv.org/abs/2303.11366
- Voyager, *An Open-Ended Embodied Agent with Large Language Models*: https://arxiv.org/abs/2305.16291
