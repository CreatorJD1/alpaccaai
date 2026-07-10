# Alpecca Stage 0 Baseline

Evidence window: **2026-07-10 00:17-00:58 PDT**
Repository: `C:\Users\Jason\Documents\GitHub\alpaccaai`

## Purpose And Authority

This report freezes a point-in-time truth baseline before security and agency
work continues. `PROJECT_CONTEXT.md` remains canonical for project intent and
`HANDOFF.md` remains canonical for active work. `docs/ALPECCA_MASTER_PLAN.md`
defines sequencing. This file records evidence; it does not promote a feature
to complete merely because code or a document exists.

## Status Contract

| Status | Required meaning |
|---|---|
| DONE | The stage's scoped exit gates are met and evidenced; later-stage blockers remain separately visible. |
| PARTIAL | Useful implementation exists, but integration, safety, testing, reliability, or fidelity remains incomplete. |
| BLOCKED | The behavior is unsafe or depends on an unmet gate and must remain disabled. |
| NOT STARTED | No production implementation was found. |
| PARKED | Deliberately deferred and not a current runtime capability. |
| REPORTED | Stated by a handoff or prior run but not independently reproduced in this evidence window. |

## Stage 0 Decision

**DONE.** The hardened capture completed, its restore drill and an independent
verification passed, focused tests are green, the House HQ build is green, and
the dirty-tree/hardware/runtime boundaries are recorded. DONE applies only to
the Stage 0 truth-baseline gate. It does not mark the whole project secure or
complete: the existing core prompt-length failure remains open, and Stage 1 is
blocked because a public Alpecca identity value is also being used as bearer
authorization.

Verified Stage 0 evidence:

- Hardened DPAPI-encrypted archive created and authenticated.
- Five private payloads restored to a temporary directory without replacing the
  live files.
- Restored 238,321,664-byte SQLite database returned `ok` from
  `PRAGMA integrity_check`.
- Independent archive verification passed after capture.
- Hardened focused suite passed: `41 passed`.
- Current-tree `npm.cmd run house:build` passed. Vite emitted only its existing
  advisory that a generated chunk exceeds 500 kB.
- The full core baseline completed with 346 passes and one existing failure at
  `tests/test_core.py:5115`: different runs assembled 6,116/6,131-character
  prompts while the legacy assertion requires fewer than 4,800.
- Sanitized inventory recorded Git, routes, database counts, launcher state,
  hardware, installed models, packages, and secret-pattern findings without
  recording secret values.

Carried forward without weakening Stage 0's result:

- The core suite is not fully green because of the existing prompt-length
  assertion above. It remains an explicit Mindpage/context-budget defect.
- The public identity/authorization coupling and HTML self-authentication remain
  Stage 1 blockers.
- A portable/off-device restore remains later continuity work. The verified
  local archive key is DPAPI-bound to this Windows user profile.
- The best-effort secret-pattern inventory is not proof of a complete secret
  audit; ignored, binary, and files over 8 MiB are not exhaustively scanned.

## Git And Dirty-Tree Boundary

- Branch: `feat/vrm-preview`
- HEAD: `05b112b3089cfb6be499cd8a1172b254c00bf6ab`
- Upstream divergence at capture: `0 ahead / 0 behind`
- Latest committed subject: `Add repeatable hoodie-hem sway physics injector for VRM exports`

Pre-existing startup modified files, excluding Stage 0 work:

```text
HANDOFF.md
PROJECT_CONTEXT.md
apps/house-hq/src/vrmEmbodiment.ts
config.py
docs/ALPECCA_CURRENT_PROGRESS.md
docs/ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.md
docs/ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.pdf
docs/ALPECCA_PROJECT_ARCHITECTURE_MAP.pdf
docs/README.md
```

Pre-existing startup untracked files, excluding Stage 0 work:

```text
alpecca/creator_contact.py
alpecca/system_pressure.py
docs/ALPECCA_MASTER_PLAN.md
docs/ALPECCA_MASTER_PLAN.pdf
scripts/build_alpecca_master_plan_pdf.py
```

Stage 0 additions made by parallel workstreams after startup:

```text
requirements.txt
scripts/capture_alpecca_baseline.py
tests/test_stage0_baseline.py
docs/ALPECCA_STAGE0_BASELINE.md
```

The encrypted files under `data/baselines/stage0/` are ignored private runtime
Stage 0 artifacts. Do not stage them. This documentation workstream owns only
this report; the other Stage 0 additions belong to parallel workstreams. Do not
clean, revert, stage, or claim ownership of unrelated items above.

## Directly Verified Facts

### Host And Pagefile

| Fact | Measured value |
|---|---:|
| Laptop | Dell G15 5525 |
| Installed DIMMs | 16 GB + 8 GB DDR5-4800 |
| OS-usable physical RAM | 23.24 GiB |
| Free RAM at sample | 8.61 GiB |
| Windows commit limit | 60.35 GiB |
| Free commit at sample | 32.99 GiB |
| Pagefile | `C:\pagefile.sys`, fixed 38,000 MiB |
| Pagefile use / recorded peak | 1,175 MiB / 10,320 MiB |
| C: capacity / free | 456.56 GiB / 57.83 GiB |
| GPU | NVIDIA GeForce RTX 3050 Laptop GPU, 4,096 MiB |
| GPU used / free / temperature | 731 MiB / 3,234 MiB / 38 C |

The DIMMs were independently queried and report DDR5 at 4,800 MT/s. This
supersedes older project documents that labeled the local laptop memory DDR4.
Free-memory, commit, disk, GPU, and temperature values are transient samples,
not capacity guarantees. The 38,000 MiB pagefile is intentional commit reserve
for CPU-backed model and KV-cache allocation; it does not add VRAM. The current
8K context is a benchmark baseline, not the final context ceiling.

### Model And Toolchain

| Fact | Current value |
|---|---|
| Ollama | `0.30.7` |
| Launcher primary model | `qwen3.5:9b` |
| Launcher fast model | `qwen3.5:4b` |
| Launcher context | `8192` |
| Loaded models at sample | None |
| Installed approved primary | `qwen3.5:9b`, 6.5 GB |
| Retired legacy 8B model | Not present in `ollama list` |
| Python / Node / npm | `3.12.10` / `24.15.0` / `11.12.1` |

The launcher still uses a separate 4B fast model. The master plan's proposed
single-resident 9B compute policy is not implemented by this baseline.

### Local State

- Capture-time database: 238,321,664 bytes; read-only integrity check: `ok`.
- Rows: 980 chat turns, 22,986 cognition observations, 3,255 journal entries,
  20,900 memories, 3,421 proposal evaluations, 10 action proposals, and zero
  configured routines.
- Mindpage: 7 pages, all hot, with 8,514 total stored token estimates. Stored
  page tokens are not the same as per-turn injected context.
- Static route inventory found 131 FastAPI/WebSocket decorators.

### Embodiment Artifacts

- The live V4 VRM was independently parsed and simulated with 74 spring joints
  and 22 colliders.
- The pristine V4 archive was independently parsed and simulated with 62 spring
  joints and 22 colliders. The 12-joint difference matches the injected hoodie
  hem sway chains.
- The current v13 base-view source is 9,603,521 bytes.

### Encrypted Recovery Baseline

- Run: `data/baselines/stage0/20260710T075727Z/`
- Archive: `alpecca-stage0-20260710T075727Z.apb`
- Archive ID: `31384b33-fee2-4042-b738-dce4565a5b3e`
- Encrypted size: 83,305,692 bytes as measured from the archive and recorded by
  `verification.json`.
- Archive SHA-256: `c369165f306b7d442ebc835ced279c94e8db7d2e7b5568aa55420b520865a937`
- Key mode: Windows DPAPI; key contents are intentionally not documented.
- Payloads: live SQLite database, live V4 VRM, pristine V4 VRM archive,
  regular-outfit `.vroid` source, and current base-view `.vroid` source.
- Capture-time restore drill and later independent verification both passed.

### Transient Plaintext And Stale Candidates

The published payload is AES-256-GCM encrypted, but capture and verification
cannot honestly be described as plaintext-free. They create a temporary SQLite
copy, payload tree/ZIP, or decrypted ZIP under the current user's local OS temp
directory. Normal success and handled failure paths remove those temporary
directories. An abrupt process or OS failure can leave plaintext scratch behind,
so full-disk encryption remains advisable.

The tool reports scratch/restore staging directories older than 24 hours as
**stale candidates only**. It does not delete unknown paths automatically. The
final hardened capture and verification reported no stale candidates. An
explicit restore intentionally produces plaintext at its user-selected output
directory after authentication and checksum validation.

The current base-view file is 9,603,521 bytes with a 2026-07-09 17:13 PDT
modification time. That supersedes the older `HANDOFF.md` size/time claim for
v13; inspect the current file rather than assuming the earlier state.

## Security Evidence

No authorization secret value is reproduced here.

- The current Alpecca value is intentionally public identity data and appears in
  `apps/house-hq/src/main.ts` and the current generated House HQ bundle. The
  security defect is that the server also accepts this public value as bearer
  authorization.
- Static inspection of `server.py` confirms an unauthenticated HTML GET can be
  served and then receive an authorization cookie populated from that public
  identity value.
- `START_HERE.bat` currently sets `ALPECCA_COMPUTER_USE=1`.
- A sanitized pattern scan returned nine findings requiring human triage. Some
  are examples/defaults/test fixtures, so the count is not nine confirmed live
  credentials.
- No `cloudflared` or `ngrok` process was observed at the sample time. A Discord
  bridge process was observed. Process absence is not proof that remote access
  is safely configured.

These findings keep remote auth, tunnels, Discord autonomy, and computer control
BLOCKED regardless of whether their individual modules run locally.

## Reported, Not Reproduced Here

The following remain `REPORTED` for this baseline and must not be upgraded to
DONE from documentation alone:

- `AGENTIC_ASSESSMENT.md` reports implemented tools, planner, routines,
  constrained choices, embedding backfill, and initial Mindpage Layer A. Their
  stricter current status remains the status in `ALPECCA_MASTER_PLAN.md`.
- Cloudflare/Hugging Face publishing and Discord connectivity are historical
  operational reports, not proof that current authentication or deployments are
  secure and current.

## Snapshot And Verification Commands

Run from the repository root. Do not print or paste credential values.

```powershell
git status --short --branch
git log -8 --date=iso-strict --pretty=format:"%h`t%ad`t%s"

python scripts\capture_alpecca_baseline.py inventory --root .
python scripts\capture_alpecca_baseline.py capture --root . --output-root data\baselines\stage0
python scripts\capture_alpecca_baseline.py verify <archive.apb> --key-file <matching.key.json>

python -m pytest -q tests\test_stage0_baseline.py
python -m pytest -q tests\test_core.py -q
npm.cmd run house:build
```

Use passphrase mode for an approved portable/off-device archive by setting
`ALPECCA_BASELINE_PASSPHRASE` through a secure local mechanism before capture.
Never commit the passphrase, DPAPI key file, archive, or generated inventory.

## Stage 1 Authorization Blockers

1. Preserve Alpecca's existing public identity value exactly. Stop accepting it
   as bearer authorization, and create a separate authorization secret in
   Windows Credential Manager or deployment secrets. Keep remote access blocked
   until that separation is proven.
2. Remove HTML navigation self-authentication. Establish server-derived creator
   sessions with secure cookies, CSRF/Origin enforcement, expiry, and explicit logout.
3. Default computer use and public tunnels off in launchers and runtime config;
   prove protected routes cannot execute without a scoped grant.
4. Implement authoritative CreatorJD identity before wiring the untracked
   `creator_contact.py` or `system_pressure.py` scaffolds.
5. Add the OS singleton, active-portal lease, and fencing epoch before Discord,
   House HQ, and Mindscape can all write or speak.
6. Triage every sanitized secret-pattern finding and scan rebuilt assets. The
   preserved public identity value is allowed; authorization secrets are not.

## Later Carry-Forward Work

- Resolve or intentionally replace the `<4800` prompt-length assertion using the
  measured context-budget contract; do not hide the current core failure.
- Review and commit the Stage 0 additions intentionally without staging private
  files under `data/baselines/stage0/`.
- Create and verify an explicitly approved portable/off-device encrypted
  recovery copy. The local DPAPI archive alone is not disaster recovery if the
  Windows profile or laptop is lost.
