# Alpecca Current Progress

Last updated: **2026-07-08**

Use this as the short active status pointer.

## Current Runtime and Capability State

- `ALPECCA_TOOL_MODE` is `smart` and `ALPECCA_INNATE_TOOLS=1` in this branch.
- Chat tool-calling is now gated and observable through tool schemas + `CognitionObservation`.
- Embedding backfill now runs in background on idle drift ticks.
- The memory path for live chat remains keyword-first (`embed_fn=None`), with
  background semantic recall support through backfill.
- No default behavior changes were made to art pipelines, House HQ animation
  architecture, or model replacement.

## Document Baseline for this Session

- `docs/AGENTIC_ASSESSMENT.md` is the current systems audit and stage-0 snapshot.
- `docs/MINDPAGE.md` is the Layer A+ target design and constraints.

## Archival Policy

Stale or superseded source docs were archived under
`docs/archive/2026-07-08/` to preserve evidence without treating them as current
behavior.
