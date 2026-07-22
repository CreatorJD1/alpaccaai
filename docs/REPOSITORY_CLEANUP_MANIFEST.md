# Alpecca Repository Cleanup Manifest

**Audit date:** 2026-07-22
**Checkout:** `codex/voice-session-audio-normalization` at `0e1ea29`
**Scope:** inventory and classification, followed by the bounded cleanup receipt
at the end of this file. Large continuity, database, character, and document
archives remain gated. `HANDOFF.md` was not edited by the inventory worker.

This manifest distinguishes disposable generated output from unique continuity,
character, release, and source assets. A path being listed as a candidate is not
authorization to remove it. Items marked **archive first** require the Google
Drive verification gate below. Items marked **conditional** require an additional
project-specific gate.

## Executive Summary

The largest local footprint is not documentation. The measured high-value areas
are:

| Area | Files | Bytes | Approx. MiB | Assessment |
|---|---:|---:|---:|---|
| `data/mindscape_vault/` | 189 | 17,257,675,728 | 16,458.20 | 187 orphaned encrypted archive files; 2 are live pending outbox entries |
| `data/backups/` | 27 | 2,171,985,920 | 2,071.37 | Mix of current rotating snapshots and older/manual backups |
| `data/tools/` | 3,706 | 1,985,258,388 | 1,893.29 | Installed tools plus removable download archives |
| `data/models/` | 2 | 1,348,449,561 | 1,285.98 | Active F5-TTS model; must remain |
| `data/alpecca_art_source/` | 2,336 | 994,987,348 | 948.89 | Current design inputs plus historical versions and exact duplicates |
| `data/build-tools/` | 625 | 826,810,348 | 788.51 | Installed Android/JDK tools plus removable installer archives |
| `.claude/worktrees/` | 7 worktrees | 617,469,677 | 588.87 | Clean but not merged into current HEAD; conditional only |
| `apps/house-hq/dist/` | 327 | 542,396,825 | 517.27 | Reproducible frontend output, dominated by copied spritesheets |
| `data/_memory_reset_backups/` | 3 | 479,993,856 | 457.76 | Historical database snapshots, including one exact duplicate |
| `.handoff/` | 22,127 | 365,006,596 | 348.10 | Extracted third-party handoff source; ignored and reproducible |
| `deploy/continuity-lease-worker/node_modules/` | 3,559 | 249,771,689 | 238.20 | Reproducible dependency install |
| `apps/house-hq/node_modules/` | 2,902 | 114,640,198 | 109.33 | Reproducible dependency install |

The working tree contains substantial unrelated work. Cleanup must happen only
after the current work is checkpointed. Regular deletion will reduce checkout
size, but it will not remove historical blobs from Git's current 560.20 MiB pack.
Any history rewrite must be a separate, coordinated migration.

## Priority 1: Generated Artifacts

These paths are reproducible and do not need a Google Drive archive. Remove only
while the related build/runtime is stopped, then regenerate and run its normal
build gate.

| Exact path or exact set | Files | Bytes | Recommendation and rationale |
|---|---:|---:|---|
| `apps/house-hq/dist/**` | 327 | 542,396,825 | **Remove/regenerate.** Vite output; source assets and code remain outside `dist`. Run `npm.cmd run house:build` afterward. |
| `apps/house-hq/node_modules/**` | 2,902 | 114,640,198 | **Remove/reinstall when needed.** Recreated from the package lock. |
| `deploy/continuity-lease-worker/node_modules/**` | 3,559 | 249,771,689 | **Remove/reinstall when needed.** Recreated from `package-lock.json`. |
| `apps/android-launcher/app/build/**` | 456 | 25,949,866 | **Remove/regenerate.** Android build output. |
| `apps/android-launcher/.gradle/**` | 16 | 1,044,955 | **Remove/regenerate.** Project-local Gradle cache. |
| `apps/launcher/build/**` | 15 | 14,324,063 | **Remove/regenerate and untrack.** PyInstaller intermediate output. Ten files are still tracked despite the current ignore rule. |
| `tmp/**` | 1,070 | 28,708,478 | **Remove after checking for unreported evidence.** Session scratch is ignored by policy. |
| `**/__pycache__/**`, `**/*.pyc`, `**/.pytest_cache/**` | variable | not materialized here | **Remove/regenerate.** Python/test caches are ignored. |
| `deploy/continuity-lease-worker/worker-configuration.d.ts` | 1 | 551,174 | **Remove/regenerate if `wrangler types` reproduces it.** It is currently untracked generated type output. |

`apps/launcher/dist/AlpeccaLauncher.exe` (10,922,301 bytes) is not classified as
disposable yet. Keep it until the current desktop launcher release, checksum,
and replacement download location are verified.

## Priority 2: Orphaned Mindscape Vault Files

The local database was queried read-only. Its `mindscape_vault_archives` table
references exactly these two pending files, which **must remain**:

- `data/mindscape_vault/archive-00000000000000000740-c50dce09781d29c9.bin`
  (98,267,152 bytes; one recorded `transport_failed` attempt)
- `data/mindscape_vault/archive-00000000000000000742-ac62db05314b3507.bin`
  (98,308,096 bytes; not yet attempted at audit time)

The exact archival candidate set is:

> Every `data/mindscape_vault/archive-*.bin` file except the two paths above.

That set contains **187 files / 17,061,100,480 bytes (16,270.73 MiB)**, from
`archive-00000000000000000198-0e83ce9062114f45.bin` through sequence 738.
These are not referenced by the current outbox table. The implementation caps
the archive outbox at two and deletes successfully uploaded files, so these are
orphaned local ciphertext left by earlier runs or database state changes.

**Archive first, then remove only after all of these gates pass:**

1. The remote Mindscape Vault reports a latest immutable recovery archive at
   sequence 738 or newer.
2. That remote archive is downloaded and its envelope/ciphertext validation
   succeeds.
3. A controlled restore copy passes SQLite `PRAGMA integrity_check` without
   touching `data/alpecca.db`.
4. The two pending local paths above remain present and byte-identical.

Do not place raw decrypted databases in Google Drive. If the orphaned ciphertext
is copied to Drive as a second archive, retain it as ciphertext and include the
separate manifest hash.

## Priority 3: Database Backup Candidates

### Archive first

These legacy snapshots predate the current seven-file rotating snapshot series:

| Exact path | Bytes | Rationale |
|---|---:|---|
| `data/backups/alpecca-20260704.db` | 159,997,952 | Legacy manual snapshot |
| `data/backups/alpecca-20260704.db-shm` | 32,768 | Detached sidecar; all six listed SHM files have SHA-256 `FD4C9FDA9CD3F9AE7C962B0DDF37232294D55580E1AA165AA06129B8549389EB` |
| `data/backups/alpecca-20260704.db-wal` | 0 | Empty detached sidecar |
| `data/backups/alpecca-20260706.db` | 159,997,952 | Legacy manual snapshot |
| `data/backups/alpecca-20260706.db-shm` | 32,768 | Detached sidecar |
| `data/backups/alpecca-20260706.db-wal` | 0 | Empty detached sidecar |
| `data/backups/alpecca-20260709.db` | 166,428,672 | Legacy manual snapshot |
| `data/backups/alpecca-20260709.db-shm` | 32,768 | Detached sidecar |
| `data/backups/alpecca-20260709.db-wal` | 0 | Empty detached sidecar |
| `data/backups/alpecca-20260710.db` | 240,173,056 | Legacy manual snapshot |
| `data/backups/alpecca-20260710.db-shm` | 32,768 | Detached sidecar |
| `data/backups/alpecca-20260710.db-wal` | 0 | Empty detached sidecar |
| `data/backups/alpecca-20260712.db` | 31,342,592 | Legacy manual snapshot |
| `data/backups/alpecca-20260712.db-shm` | 32,768 | Detached sidecar |
| `data/backups/alpecca-20260712.db-wal` | 0 | Empty detached sidecar |
| `data/backups/alpecca-20260714.db` | 60,678,144 | Legacy manual snapshot |
| `data/backups/alpecca-20260714.db-shm` | 32,768 | Detached sidecar |
| `data/backups/alpecca-20260714.db-wal` | 0 | Empty detached sidecar |
| `data/alpecca.db.backup_20260710_193716` | 304,680,960 | Standalone pre-current backup |
| `data/alpecca_identity_backup_20260710_193956.json` | 54,056,048 | Historical identity export; sensitive and must be encrypted before Drive upload |

The three reset backups are also archival candidates:

| Exact path | Bytes | SHA-256 note |
|---|---:|---|
| `data/_memory_reset_backups/alpecca.db.reset-backup-20260702-153016.bak` | 159,997,952 | Unique within this group: `E215B3AFA01C5E42B4C20947BA84439D221D34CD33A2DEC21EB6CE6065563977` |
| `data/_memory_reset_backups/alpecca.db.reset-backup-20260702-153116.bak` | 159,997,952 | Exact duplicate hash `B074EF78996E2F9673194E96C68831F7A25B797903C01CE47FCD977E8EA36288` |
| `data/_memory_reset_backups/alpecca.db.reset-backup-20260702-153122.bak` | 159,997,952 | Exact duplicate hash `B074EF78996E2F9673194E96C68831F7A25B797903C01CE47FCD977E8EA36288` |

Upload only one of the exact duplicate reset files. Preserve both distinct reset
states in the archive package, validate each with SQLite integrity checking, and
encrypt the package with a key that is not stored in Drive.

### Must remain for now

- `data/alpecca.db` and any live `-wal`/`-shm` files.
- The seven current `data/backups/alpecca-20260722T*.sqlite3` rotating snapshots.
- `data/backups/alpecca-pre-continuity-dedupe-20260721-230309.db` and
  `data/backups/alpecca-deduped-uncompacted-20260721-230309.db`. Their SHA-256
  values differ (`A856...4E04` and `94D7...4CCE`); retain the rollback pair until
  continuity dedupe has a completed restore/failback soak.
- Continuity journal segments, quarantine evidence, lease state, and current
  encrypted event outboxes under `data/`.

## Priority 4: Character and VRoid Archive Candidates

The current remote-design manifest identifies these as required and they must
remain locally until a replacement is approved:

- `data/avatar/vrm/alpecca.vrm` -- current live V4 runtime body.
- `data/avatar/vrm/alpecca_vroid_prototype_v4_20260709.vrm` -- pristine V4
  rollback body.
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v13_base_view_170cm.vroid`
  -- current editable V13 source.
- Every other input listed in
  `docs/manifests/alpecca_remote_design_v5.json`.

### Exact duplicate VRM group

These four files are byte-identical: 18,118,508 bytes each, SHA-256
`B35E7753F94B5474F944028EBD64DB84D36345B7D15CB4E4BE81AA9066A88931`.

- `data/alpecca_art_source/vrm_experiments/companion_tool_drop/alpecca_vroid_proxy_v0_first_test_20260706.vrm`
- `data/alpecca_art_source/vrm_experiments/exports/alpecca_vroid_proxy_v0_first_test_20260706.vrm`
- `data/alpecca_art_source/vrm_experiments/handoff_to_claude/alpecca_vroid_proxy_v0_first_test_20260706.vrm`
- `data/avatar/vrm/alpecca_vroid_proxy_v0_first_test_20260706.vrm`

**Recommendation:** archive one copy with the hash and original-path list, then
remove all four local V0 copies after Drive verification. Three redundant copies
alone consume 54,355,524 bytes. The three copies under
`data/alpecca_art_source` are tracked Git files, so removing them from the tip
will reduce future checkout size but not existing Git history.

### Superseded editable/model iterations

Archive first, then remove locally only after VRoid V13 and V4 restore/open tests:

- `data/alpecca_art_source/vrm_experiments/alpecca_hoodie_sway_qa.vrm`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v0.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v0_before_base_view_20260709.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v0_before_hoodie_front_sleeves_20260708_2108.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v0_preserved_before_v1.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v0_updated_source_20260709_121940_preserved.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v1.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v2.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v3.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v4_reference_locked.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v5_ahoge.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v6_hair_highlight.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v7_stocking_proxy.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v8_base_iris.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v9_base_face_iris_v2.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v10_base_brows_eyeliner.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v11_hair_gradient_ahoge.vroid`
- `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v12_user_adjusted_from_v0.vroid`

The BOOTH accessory download and generated eye/lanyard ZIPs are source inputs,
not disposable build output. Archive them only after their licenses, passwords,
checksums, and extracted derivative paths are recorded.

## Priority 5: Documentation Archive Candidates

### Already classified historical

The exact `docs/archive/**` set contains 22 files / 389,870 bytes. It is safe to
remove from the active checkout only after a verified Drive archive because the
files are retained for traceability:

- `docs/archive/2026-07-08/ALPECCA_COLAB_T4.md`
- `docs/archive/2026-07-08/ALPECCA_DISCORD_PRESENCE.md`
- `docs/archive/2026-07-08/ALPECCA_MASTER_GOAL_STATUS.md`
- `docs/archive/2026-07-08/ALPECCA_RECURSIVE_ENGAGEMENT_RESEARCH.md`
- `docs/archive/2026-07-08/ALPECCA_STAGE4_360_REFERENCE_LOCK.md`
- `docs/archive/2026-07-08/ALPECCA_STAGE4_NATIVE_4K_FIRST_SLICE.md`
- `docs/archive/2026-07-08/ALPECCA_STAGE4_WALK_CYCLE_POSE_LOCK.md`
- `docs/archive/2026-07-08/ALPECCA_STAGE4_WALK_PROOF_NOTES.md`
- `docs/archive/2026-07-08/Alpecca_Systems_Review.html`
- `docs/archive/2026-07-08/Alpecca_Systems_Review.pdf`
- `docs/archive/2026-07-08/BRINGING_HER_TO_LIFE.md`
- `docs/archive/2026-07-08/DESIGN_expressiveness_autonomy_home.md`
- `docs/archive/2026-07-08/INTEGRATE_RIGFORGE.md`
- `docs/archive/2026-07-08/LAYER_SPLITTING.md`
- `docs/archive/2026-07-08/UPGRADE_GUIDE.md`
- `docs/archive/2026-07-10/PASSDOWN_remote_computer_access.md`
- `docs/archive/2026-07-15/ALPECCA_ENTIRE_PROJECT_DETAILED_DIAGRAM.pdf`
- `docs/archive/2026-07-15/ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.pdf`
- `docs/archive/2026-07-15/ALPECCA_MASTER_PLAN.pdf`
- `docs/archive/2026-07-15/ALPECCA_PROJECT_ARCHITECTURE_MAP.pdf`
- `docs/archive/2026-07-15/ALPECCA_STAGE0_2_GATE_AUDIT.md`
- `docs/archive/2026-07-15/ALPECCA_STAGE4_RECALL_DESIGN.md`

The July 15 paths currently appear as staged root deletions plus untracked archive
copies. Preserve that working-tree state; do not repeat or reverse the move as
part of cleanup.

### Move to historical archive after Drive verification

These are stale passdowns or superseded implementation plans, not current
behavior specifications:

- `docs/ALPECCA_V11_15_VIEW_CAMERA_MATRIX.md`
- `docs/ALPECCA_V11_FULL_TOOLSET_MASTER.md`
- `docs/ALPECCA_V11_GATE_RESULTS.md`
- `docs/ALPECCA_V11_GUI_OPERATION_RECIPE.md`
- `docs/ALPECCA_V11_PANEL_CONTROL_MATRIX.md`
- `docs/ALPECCA_V11_REFERENCE_CONTACT_SHEET.jpg`
- `docs/ALPECCA_V11_RESUME_LOG.md`
- `docs/ALPECCA_V11_SESSION_CARD.md`
- `docs/ALPECCA_V11_VR_QA_CHECKLIST.md`
- `docs/ALPECCA_VROID_ACCESSORY_WORKBENCH.md`
- `docs/ALPECCA_VROID_BRANCH_DECISION.md`
- `docs/ALPECCA_VROID_CLAUDE_CODE_PASSDOWN.md`
- `docs/ALPECCA_VROID_V11_GUI_CONTROL_MATRIX.md`
- `docs/ALPECCA_VROID_V11_PASSBOARD.md`
- `docs/ALPECCA_VROID_V11_RESUME_LOG.md`
- `docs/ALPECCA_VROID_VRM_EXPERIMENT.md`
- `docs/ALPECCA_STAGE0_BASELINE.md`
- `docs/ALPECCA_STAGE4_TILE_WORKER.md`
- `docs/ALPECCA_VM_WORKSPACE_PLAN.md`
- `docs/ALPECCA_VISION_HANDOFF_FOR_CODEX.md`

### Conditional coordination archive

Do not remove these until every referenced lane has been integrated or explicitly
rejected and its commit is preserved on a pushed branch or Git bundle:

- `docs/CLAUDE_FABLE_PARALLEL_DELEGATION.md`
- `docs/FOR_CODEX_INTEGRATION_REQUEST.md`
- `docs/WAVE1_INTEGRATION_HANDBACK.md`

### Documentation that must remain

- `PROJECT_CONTEXT.md` and `HANDOFF.md`.
- `docs/README.md` and this manifest.
- `docs/AGENTIC_ASSESSMENT.md`.
- `docs/ALPECCA_CURRENT_PROGRESS.md`.
- `docs/ALPECCA_MASTER_PLAN.md` and
  `docs/ALPECCA_UNIFIED_MASTER_PLAN.md` until replaced by one approved canonical
  plan.
- `docs/MINDPAGE.md`, `docs/PAGEFILE_TELEMETRY.md`, and
  `docs/CONTEXT_TIER_MEASUREMENT.md`.
- `docs/ALPECCA_BRAIN_PLUGINS.md`, `docs/SOUL_FALLBACK_ARCHITECTURE.md`, and
  `docs/AFFECTIVE_INCIDENT_LEARNING.md`.
- `docs/RELEASE_SECRET_SCAN.md`, `docs/RELEASE_SOAK.md`, and
  `docs/PHASE11_NOTIFICATION_ACCEPTANCE.md` while their gates remain partial.
- `docs/UBUNTU_FALLBACK_CORE_PLAN.md` and
  `docs/REMOTE_CODEX_ALPECCA_DESIGN_HANDOFF.md` while those workstreams are
  active.
- `docs/AGENTIC_FRONTIER.md`; the game remains a separate application.
- The three current generated architecture PDFs at the root of `docs/` because
  they are the user-facing current visuals and total only 59,910 bytes.

## Priority 6: Download Archives and Third-Party Handoffs

These download archives can be removed after the extracted installation passes
its version/smoke check and the source URL plus SHA-256 remains documented:

| Exact path | Bytes | SHA-256 |
|---|---:|---|
| `data/build-tools/commandlinetools-win-latest.zip` | 150,532,528 | `CC610CCBE83FADDB58E1AA68E8FC8743BB30AA5E83577ECEB4CC168DAE95F9EE` |
| `data/build-tools/microsoft-jdk-17-windows-x64.zip` | 186,907,952 | `394D1D8253D58B462300F15F9C81369478CF8813F82DCA914C3B5DFDEF080F9F` |
| `data/tools/llama.cpp/b9933/cudart-llama-bin-win-cuda-12.4-x64.zip` | 391,443,627 | `8C79A9B226DE4B3CACFD1F83D24F962D0773BE79F1E7B75C6AF4DED7E32AE1D6` |
| `data/tools/llama.cpp/b9933/llama-b9933-bin-win-cpu-x64.zip` | 18,206,545 | `E56C23CC78CECE2EDB1E603B5163DF6D4B8B2A3DB746250A8FE8B2C7EFEE1555` |
| `data/tools/llama.cpp/b9933/llama-b9933-bin-win-cuda-12.4-x64.zip` | 267,009,763 | `64B50A6215FAEB5EBFF7E1CF9B6AB277BBE27CED0F279F6F6DB31122C0853251` |

Do not remove `data/build-tools/jdk17/**`, Android SDK components, extracted
`data/tools/llama.cpp/b9933/**` binaries, or the MCP virtual environment until
the launcher/tool routes prove they are unused or are replaced.

`.handoff/**` is an ignored, 365,006,596-byte extraction of third-party source.
No runtime source reference was found. It is a cleanup candidate after recording
the upstream repositories/revisions needed to reproduce it. It does not need to
be uploaded to Drive if the exact upstream revisions are available publicly.

## Priority 7: Worktrees and Old Audit Scratch

The seven in-repository Claude worktrees are clean but none of their tips is an
ancestor of the current HEAD. They are therefore **not safe to remove now**:

| Worktree | Tip | Bytes (excluding dependency/venv caches) |
|---|---|---:|
| `.claude/worktrees/agent-add8b5f86b62b3a56` | `4f4c729` | 92,532,252 |
| `.claude/worktrees/agent-a148330e80b48264d` | `f82656d` | 90,055,396 |
| `.claude/worktrees/agent-ab8b4fc9edcc3bf52` | `574a71e` | 89,752,470 |
| `.claude/worktrees/agent-a911ba084612bd040` | `b9bc798` | 89,569,567 |
| `.claude/worktrees/agent-a179519d2abd0dacc` | `827ba3c` | 89,546,781 |
| `.claude/worktrees/agent-a1bcbe731fd5bd82c` | `95ba57a` | 87,614,712 |
| `.claude/worktrees/pensive-heyrovsky-82ee05` | `30226c6` detached | 78,398,499 |

They become candidates only after each tip is pushed or included in a verified
Git bundle and the integration packet is resolved. Use `git worktree remove`
and `git worktree prune` in that later operation; never delete registered
worktree directories directly.

The old `.agents/**` reports (54 files / 158,188 bytes), `PROJECT.md` (1,439
bytes), `explorer_phase2_audit/**` (2 files / 10,140 bytes), and the zero-byte
root `Desktop` plus 51-byte root `Dev` files are archive/removal candidates after
confirming their findings are represented in the canonical plan/current-progress
documents. They are not runtime inputs.

## Launcher Files

`ALPECCA_LAUNCHER.bat` is the current master launcher and must remain. The
following tiny root files are compatibility shims, not meaningful bloat:

- `START_HERE.bat` (51 bytes)
- `START_DISCORD.bat` (60 bytes)
- `SHARE_PHONE.bat` (58 bytes)
- `RUN_VCS.bat` (50 bytes)
- `ALPECCA_TOOLS.bat` (52 bytes)
- `apps/agentic-frontier/START_AGENTIC_FRONTIER.bat` (61 bytes)

Remove those only after all documentation, shortcuts, tests, and external user
workflows invoke `ALPECCA_LAUNCHER.bat` directly. Keep
`apps/android-launcher/gradlew.bat`; it is the platform wrapper, not an Alpecca
startup launcher. `apps/launcher/build_exe.bat` and
`apps/launcher/src/run_launcher.bat` can be replaced later by master-launcher
subcommands, but that is a functional refactor and not part of archive cleanup.

## Git Object Store

The checkout has 753 tracked paths totaling 88,245,139 bytes. Git reports a
560.20 MiB packed object store. The largest historical blob is the 18,118,508-byte
V0 VRM; the PyInstaller package contributes a 10,553,434-byte historical blob.
Deleting tracked copies in a new commit will not remove those historical bytes.

Do not rewrite history during routine cleanup. If clone size remains a problem
after the working-tree cleanup, perform a separate migration with:

1. A complete mirrored remote backup and verified Git bundle.
2. A published freeze window for all worktrees and collaborators.
3. A path/object report agreed before filtering.
4. Rewritten branch/tag verification and fresh-clone tests.
5. Explicit force-push approval and rollback instructions.

## Google Drive Archive Verification Gate

Use a dedicated folder such as
`Alpecca/Repository Archive/2026-07-22/<category>/`. A Drive upload is not
considered verified merely because the filename appears in the web UI.

Before any local archive candidate is removed:

1. Create a content manifest containing every original relative path, byte size,
   SHA-256, classification, archive date, source branch, and source commit.
2. Deduplicate only after hashes match. Record every original path against the
   one retained object.
3. Encrypt databases, memory exports, chat/identity material, screenshots, and
   private source packages client-side. Store the encryption key outside Google
   Drive and outside the repository.
4. Upload immutable archive packages plus the plaintext metadata-only manifest.
   Record each Google Drive item ID, exact uploaded byte size, and upload time.
5. Download each uploaded object through Drive into a separate temporary
   location. Recompute SHA-256 and require an exact match to the local package.
6. For split archives, verify every part and reconstruct the archive before the
   restore test.
7. Open/list the reconstructed archive and verify its file count and path set
   against the content manifest.
8. Run format-specific restore checks: SQLite `PRAGMA integrity_check`, VRM/VRoid
   open/import plus hash checks, PDF render/open, and Git bundle branch/tip checks.
9. Keep the local originals until at least one controlled restore succeeds and a
   second independent continuity copy exists (Mindscape Vault for continuity,
   private Hugging Face for versioned character assets, or another encrypted
   backup).
10. Produce a signed cleanup receipt listing only the paths actually removed,
    their archived Drive item IDs, package hashes, and restore-test result.

## Recommended Execution Order

1. Checkpoint the current dirty tree without changing unrelated work.
2. Clear reproducible caches/build output.
3. Repair Mindscape archive retention and verify remote sequence/restore state.
4. Archive and remove the 187 orphaned Vault ciphertext files.
5. Archive legacy database snapshots and historical docs using the Drive gate.
6. Deduplicate/archive old V0-V12 character iterations while preserving the
   current V4/V13 manifest set.
7. Resolve and retire clean worktrees through Git-aware commands.
8. Re-run builds, tests, launcher smoke checks, continuity status, and a final
   size inventory. Consider Git history migration only as a separate project.

## 2026-07-22 Cleanup Receipt

- Staged `tmp/Alpecca_Legacy_Source_Archive_2026-07-22.zip`: 68 files,
  23,860,988 bytes, SHA-256
  `66E5703D8858503DE904349BF88CD56FB30220EA205F8E7A29329AAA230F4F0A`.
- Retired the obsolete root launcher wrappers, Stage 4 BAT, and launcher-local
  BAT wrappers. `ALPECCA_LAUNCHER.bat` is now the only user-facing BAT; Android
  `gradlew.bat` remains build tooling.
- Removed `apps/launcher/build/**` after it was included in the archive. It is
  reproducible through `apps/launcher/build_launcher.py`.
- Drive upload and download/hash verification are **not complete** because the
  migrated browser integration could not initialize. Therefore no historical
  docs, legacy databases, V0-V12 sources, Vault ciphertext, or other archive-
  first files were removed.
