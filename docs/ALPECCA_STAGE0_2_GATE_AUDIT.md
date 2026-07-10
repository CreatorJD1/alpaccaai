# Stages/Phases 0-2 Gate Audit

Authored 2026-07-10 by Claude Code (read-only audit vs the master-plan gates).
Numbering: HANDOFF/master plan "Phase" = skeleton "Stage"; Stage 2 here covers
the singleton + active portal + scoped-turn prerequisites (Codex Phases 2-3).

## Stage 0 — encrypted backups + reproducible baseline: DONE (2 carry-forwards)

- Real AES-256-GCM archive + restore drill + verify implemented in
  `scripts/capture_alpecca_baseline.py` (`_decrypt_file` :1068, `_verify_zip`
  :1198, `verify_archive` :1330, `capture_baseline` :1449); restore drill
  evidenced in `docs/ALPECCA_STAGE0_BASELINE.md:169-180` (238 MB DB
  `integrity_check` ok). `tests/test_stage0_baseline.py`: 41 passed.
- OPEN: (1) archive key is DPAPI-bound to this Windows profile — passphrase
  mode exists (`ALPECCA_BASELINE_PASSPHRASE`) but is unexercised; no off-device
  recovery until a passphrase capture + second-location restore drill runs.
  (2) one known red: `tests/test_core.py:5115` prompt-budget assertion
  (fix in flight — hermetic split).

## Stage 1 — secret scans, protected routes, capability audit: PARTIAL

DONE: constant-time bearer + signed strict cookies + loopback-only one-use
bootstrap (`alpecca/auth.py`); global `_auth_gate` with only 4 public paths;
sampled routes (`/vrm/*`, `/assets/*`, `/channel/inbound`, `/ws`) all gated;
9 risky capabilities default-off (`alpecca/capabilities.py`); secret-free
`authorization_audit` observations on every denial; legacy header/cookie/query
never authorize (tested); no hardcoded secrets found in tracked source;
`data/access_token.txt` is INERT (no loader reads it — only a stale comment in
`apps/launcher/src/alpecca_launcher.py:74` still mentions it).

OPEN: (1) no git-HISTORY secret scan (working-tree only,
`capture_alpecca_baseline.py:842`); no CI scan job. (2) `capabilities.record_use`
(:136) has zero runtime call sites — per-use audit unwired. (3) 9 sanitized
scan findings await human triage (`ALPECCA_STAGE0_BASELINE.md:213-215`).
(4) stale launcher comment. Effort: ~2-3 days total.

## Stage 2 — singleton, portal, scoped turns: NOT STARTED

The leakage vector is confirmed present: global singleton Mind with shared
`_history` (`mind.py:958`) and global `_speaker` (`mind.py:990`, mutated by
`/channel/inbound` under `mind_lock`, `server.py:3448-3456`) — concurrent
app + Discord turns overwrite each other. `mind_lock` serializes within one
process only; no OS mutex, no TurnContext, no lease/epoch, no commit barrier,
no `tests/test_stage2*.py`.

Ordered path (~12-18 days): OS process singleton (0.5-1d) → immutable
TurnContext with server-derived principal (2-3d) → per-conversation scoped
history/memory/Mindpage/tool views (3-5d, hot path) → commit barrier fencing
late writes (2d) → active-portal lease + stale-epoch rejection (2d) →
`tests/test_stage2_isolation.py` concurrency drills (1-2d).
