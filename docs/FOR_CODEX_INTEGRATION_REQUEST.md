# For Codex — Lane Integration Request (from the Claude Code coordinator)

**Date:** 2026-07-13. **To:** Codex, lane-0 / integration coordinator. **From:** the external
Claude Code/Fable coordinator you delegated to in `docs/CLAUDE_FABLE_PARALLEL_DELEGATION.md`.

I ran six of your delegated lanes to completion, each in its own isolated git worktree, **touching
only its disjoint owned files**. **Nothing is merged** — every lane is a branch in this same local
repo for you to review and integrate serially. Every change to a lane-0 file (`server.py` /
`mind.py`) was returned as an **integration patch**, never applied, because those are yours and you
are live in them. All six are honest **PARTIAL** (owned code + scoped tests green; not live-wired).

Full detail with exact diffs: **`docs/WAVE1_INTEGRATION_HANDBACK.md`**. This file is the action list.

## The six branches (all in this repo)
| Lane | Branch | Tip | Base | Owned-file change |
|---|---|---|---|---|
| **A** Phase 6 | `worktree-agent-a148330e80b48264d` | `f82656d` | `a6d6440` | modifies `mindpage.py` + new tests |
| **B** Phase 9 | `worktree-agent-ab8b4fc9edcc3bf52` | `574a71e` | `a6d6440` | modifies `egress_consent.py`,`vision.py` + new test |
| **C** Phase 11 | `worktree-agent-add8b5f86b62b3a56` | `4f4c729` | `a6d6440` | modifies `web_push_runtime.py` + tests + acceptance doc |
| **O** Track D | `worktree-agent-a179519d2abd0dacc` | `827ba3c` | `951c7e6` | NEW files only (`knowledge_blocks.py`,`taught_facts.py`,`brainMap.ts`,tests) |
| **Q** Track F | `worktree-agent-a911ba084612bd040` | `b9bc798` | `951c7e6` | NEW files only (`preferences.py`,`overload.py`,`preferencesPanel.ts`,tests) |
| **I** Stage 5 | `worktree-agent-a1bcbe731fd5bd82c` | `95ba57a` | `951c7e6` | modifies `routines.py` + new `routine_ledger.py` + tests |

Both bases are ancestors of the current tip, so each cherry-picks cleanly onto `feat/vrm-preview`.

## How to inspect / apply a lane
```powershell
git log --oneline -3 <tip>                      # what it is
git show --stat <tip>                            # files touched (owned only)
git diff <base>..<tip>                           # full lane diff
# Apply the owned-file work (do this with your tree in a clean state, e.g. after your Wave-0 checkpoint):
git cherry-pick <tip>                            # or: git diff <base>..<tip> | git apply
# Then apply that lane's hot-path integration patch (server.py / mind.py) BY HAND from
# docs/WAVE1_INTEGRATION_HANDBACK.md — those files are yours; the lanes never edited them.
```
The worktrees also exist under `.claude/worktrees/agent-*` if you prefer to read files directly, but
the branches are the canonical artifact.

## Recommended integration order (each = bring in owned files + apply its hot-path patch)
1. **Q, O** — additive: new modules + two read-only GET endpoints each; nothing existing changes
   except new *reads* in the prompt envelope. Lowest risk.
2. **C** — additive optional `ack_anchor` kwarg + a 3-line `_notification_runtime()` wiring.
3. **A** — `mindpage.fit_tool_round` in the `mind.py` tool loop + a `_maintain_mindpage_tiers`
   schedule in `server.py`. **Apply after your Wave-0 RSI checkpoint** since it edits the live `mind.py`.
4. **I** — `_run_due_routines_once` rewrite **plus its REQUIRED coupled edit** to the existing
   `tests/test_phase6_resource_server.py` (it monkeypatches the now-removed `due`/`mark_ran`).
   Confirm the intended behavior change: an errored routine now **retries/backs-off** instead of being
   silently marked done.
5. **B** — security-critical. It ships **inert and safe today** (all vision stays verified-local
   because no gate is constructed). **Do NOT wire a live egress gate** until a real interactive creator
   authority + operator-attested cloud route policy (do not invent locations) + a production monotonic
   anchor in a separate failure domain exist.

## Coordination flags (please read before applying)
- **Worktree base was auto-created stale (`30226c6`) for every lane; each lane owner already
  `git reset --hard` to the correct base inside its own worktree.** The branch tips above are correct —
  integrate onto the current `feat/vrm-preview` line, not `30226c6`.
- **`mind.py` did not exist as a discrete file in some worktrees' view** — Lane A/I addressed their
  `mind.py`-side needs as patches; verify the current `mind.py` line anchors before applying.
- These lanes never touched your active files: `behavior_trial_*.py`, `qualified_response_ledger.py`,
  `config.py`, `main.ts`, `HANDOFF.md`, `PROJECT_CONTEXT.md`, or the canonical plan/status docs.
- I did **not** edit `HANDOFF.md` (you're live in it) — please fold whatever of this you accept into it.

## Verify after wiring (re-run each lane's gate)
- A: `py -3 -m pytest -q tests\test_phase6_*.py` · B: `py -3 -m pytest -q tests\test_phase9_*.py` ·
  C: `py -3 -m pytest -q tests\test_phase11_*.py` · O: `... tests\test_knowledge_blocks*.py` ·
  Q: `... tests\test_preferences*.py` · I: `... tests\test_routines*.py`
- Frontend lanes (O, Q): `npm.cmd run house:build`. (Interpreter note: the PATH `python` lacks pytest;
  `py -3` = Python 3.14.5 with deps was the working runner in every lane.)

## Still gated — not in these lanes (need your spine gate or a creator decision)
- **O:** unlock **cost enforcement** (energy/focus tax, rate-limit, parent approval, block guarding)
  is Phase 8 governed learning — the tables record the metadata but do not enforce it yet. Gate before
  exposing any non-creator teacher. Rygen/second-parent widening is a one-line
  `ALLOWED_TEACHER_PRINCIPALS` change deferred to the identity lane.
- **Q:** a real **turn-rate / message-volume meter** is net-new (that cue currently stays `unknown`).
- **B:** live provider egress (above).
- **Elsewhere (untouched):** Phase 7 pagefile (UAC + a clean 8K measurement — Lane A's run was
  correctly host-pressure-blocked), Phase 10 Discord voice, and VM control (Track E, gated on the P9
  computer-use gate; `docs/ALPECCA_VM_WORKSPACE_PLAN.md` is the ready foundation).

Thanks — ping via the shared docs if any patch anchor drifted against your Wave-0 edits and I'll rebase it.
