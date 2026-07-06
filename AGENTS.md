# AGENTS.md - Alpecca

Read `PROJECT_CONTEXT.md` first. It is the canonical source of truth for this repo.

Then read `HANDOFF.md` for the latest active work and verification notes.

## Codex Priorities

- Preserve the user-facing spelling: **Alpecca**.
- House HQ is the main embodied scaffold.
- The Alpecca virtual app is the secondary app state.
- Mindscape is the continuity/sustainability layer.
- Do not upload Alpecca art to Cloudflare; art storage belongs on Hugging Face.
- Do not change Alpecca's locked design when generating or repairing art.
- Keep self-improvement bounded, observable, evidence-backed, and user-approved.
- Never claim literal consciousness; keep self-reports grounded in real state.

## Before Editing

1. Read `PROJECT_CONTEXT.md`.
2. Check `HANDOFF.md`.
3. Inspect the relevant files instead of assuming the old duplicated context is current.
4. Preserve unrelated work in the dirty tree.

## Usual Checks

```powershell
npm.cmd run house:build
python -m pytest -q tests\test_core.py -q
```
