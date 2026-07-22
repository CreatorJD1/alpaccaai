# Local storage audit - 2026-07-22

This is a read-only size review. No runtime data, memories, models, worktrees,
or user assets were deleted.

## Measured totals

- Checkout excluding `.git`: 36.96 GiB.
- Git object store: 563.46 MiB.
- Present tracked files: 70.56 MiB.
- Ignored runtime/dependency data: 30.10 GiB.
- Untracked, non-ignored work in progress: 4.85 MiB.

The Python/TypeScript source is not the size problem. Most space is continuity
archives, model runtimes, backups, generated builds, and duplicated avatar data.

## Largest areas

| Path | Size | Current classification |
|---|---:|---|
| `data/mindscape_vault` | 16.997 GiB | Preserve until remote restore verification |
| `vendor/fish-speech` | 3.443 GiB | Dormant archive candidate |
| `data/backups` | 2.056 GiB | Preserve, then apply retention after restore test |
| `data/tools` | 1.849 GiB | Installed tools/downloads; verify before pruning |
| `.venv-f5-tts` | 1.786 GiB | Active voice runtime |
| `apps/vcs` | 1.627 GiB | Dirty nested app checkout; checkpoint first |
| `data/models` | 1.256 GiB | Active F5 model |
| `apps/house-hq` | 1.117 GiB | Assets plus reproducible build/dependencies |
| `data/alpecca_art_source` | 948.89 MiB | Character source/history |
| `.claude/worktrees` | 897.19 MiB | Registered worktrees with unmerged tips |

## Conservative recovery candidates

1. Reproducible build/dependency trees total about 1.47 GiB. Clear only with
   relevant processes stopped and after confirming clean rebuilds.
2. The vault database references sequences 761 and 783. Another 197 files
   total 16.81 GiB and are orphan candidates, but require remote sequence 783+
   verification and an isolated restore before removal.
3. `apps/vcs/storage` contains about 467.31 MiB of duplicate VRM bytes. Preserve
   ID/path mappings before deduplication.
4. Downloaded Android/JDK/llama.cpp archives total about 967.12 MiB. Remove only
   after recording hashes/source URLs and smoke-testing extracted installations.
5. Fish Speech has no active launcher/config/runtime reference outside old
   handoff material. Archive it only after confirming no manual workflow uses it.

## Do not remove yet

- Live `data/alpecca.db`, WAL/SHM, current rotating snapshots, continuity
  journals/outboxes, quarantine, and lease state.
- F5 model/environment and voice references.
- Current V4 runtime VRM, pristine V4 rollback, V13 editable source, and remote
  design manifests.
- Registered worktrees before their branches are pushed or merged.
- The dirty nested `apps/vcs` checkout.

Documentation is only 1.60 MiB and PDFs total 0.328 MiB. Document pruning helps
clarity but will not materially reduce disk use.
