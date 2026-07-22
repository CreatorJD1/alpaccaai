# Source Quality And Archive Audit Plan

Status: PREPARED - run after active implementation stages reach a green checkpoint

## Scope

1. Review Python, TypeScript, launchers, deployment workers, tests, generated
   outputs, and documentation against current runtime behavior.
2. Build an import/call/route/asset reachability inventory before classifying
   anything as unused.
3. Separate dead code from dormant, flag-gated, migration, recovery, and test
   code. Only confirmed dead code is removed.
4. Run secret-pattern and large-art checks without rotating or revoking
   credentials as part of code cleanup.
5. Archive superseded documents and PDFs with `git mv` first so history is
   preserved. Delete only duplicates that are verified byte-identical or are
   explicitly approved for removal.

## Evidence Gates

- `python -m pytest -q tests/test_core.py`
- focused Discord, voice, security, Brain Graph, Mindpage, and continuity tests
- `npm.cmd run house:test:embodiment`
- House HQ TypeScript check and production build
- protected route and one-instance smoke checks
- before/after route, import, file-count, and package-size reports

## Documentation Rules

- `PROJECT_CONTEXT.md` and `HANDOFF.md` remain canonical.
- Current operational docs must carry a status and update date.
- Old PDFs are not sources of truth. Superseded PDFs move to `docs/archive/`
  with an index entry naming their replacement.
- Stale runtime manifests are regenerated or explicitly labeled historical;
  they are not silently treated as current stage evidence.

## Removal Sequence

1. Inventory and classify.
2. Archive documentation.
3. Remove unreachable code in small ownership-scoped changes.
4. Run the full gate after each removal batch.
5. Keep rollback commits independent from feature commits.
