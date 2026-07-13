# Lane Integration Handback — Wave 1 + Foundation Lanes (Claude Code coordinator → Codex / CreatorJD)

**Date:** 2026-07-13. **Status:** SIX lanes complete on **isolated branches — nothing merged.**
Three Wave-1 lanes (A Phase 6, B Phase 9, C Phase 11) + three foundation lanes (O knowledge,
Q preferences, I routines). Each carries an integration patch for a **lane-0 (Codex-owned) file**
(`mind.py` / `server.py`), so integration is Codex's call, applied serially after review. All six
report **PARTIAL** (owned code + scoped tests green, but not live-wired). Honest-status rule
enforced: code alone ≠ DONE. ~139 new tests across the six lanes, all green.

**Shared note — worktree base:** the harness created each lane worktree at a stale commit
`30226c6` (a divergent lineage lacking the phase files). All three lane owners detected this and
`git reset --hard a6d6440` **inside their own isolated worktree only** (no effect on the main tree
or each other). Integrate these branches onto the `a6d6440` line, not `30226c6`. Also: the lanes
ran from committed `docs/ALPECCA_MASTER_PLAN.md` + their task briefs — the untracked
`docs/CLAUDE_FABLE_PARALLEL_DELEGATION.md` was not visible inside the worktrees (it's uncommitted
in the main tree), which did not affect scope.

---

## Lane A — Phase 6 Mindpage + resource completion
- **Branch:** `worktree-agent-a148330e80b48264d` @ `f82656d`
- **Owned files changed:** `alpecca/mindpage.py` (+207/−7), `docs/CONTEXT_TIER_MEASUREMENT.md`,
  new `tests/test_phase6_{match_centered_fault,tool_round_budget,page_tier_maintenance}.py`.
  (`host_resources.py`, `resource_*.py`, `measure_context_tier.py` needed no change.)
- **Delivered:** (1) `fit_tool_round(...)` re-measures + evicts oldest middle turns every
  tool-result round, protecting system block + current user msg + this round's tool results, honest
  overflow when the protected minimum still won't fit; (2) `_match_centered_excerpt` — `fault_page`
  gained optional `query` and returns an ellipsis window centered on the densest match (falls back
  to the honest prefix on no match); (3) `maintain_pages` gained a cooperative `cancel_event`
  (partial idempotent progress, leaves `last_maintenance` unstamped to resume, no model call).
- **Tests:** `test_phase6_*` **152 passed** (+17); core `-k "mindpage or context or resource"` 17
  passed; invariant re-check (semantic/refusal/cancellation/content-index) 31 passed.
- **Real 8K measurement:** ran `measure_context_tier.py --execute --tier 8192` → correctly
  `status: blocked`, `host_assessment_high`, all `durations_ms` null, no HTTP, no pagefile/config
  mutation. Gated outcome recorded.
- **Residual:** deliverables 1 & 5 are runtime-PARTIAL until Patches A & B wire them; a real 8K
  inference still awaits cleared disk headroom + separate authorization.

### Patch A → `alpecca/mind.py` (tool loop, ~L907–919; `mindpage_mod` already imported L73)
Budget each follow-up round before re-send:
```diff
                     last = (i == rounds - 1)
+                    round_tools = None if last else tools
+                    messages, _round_ledger = mindpage_mod.fit_tool_round(messages, tools=round_tools)
                     try:
-                        resp = self._chat(messages, tools=(None if last else tools), model=tool_model, local_only=local_only)
+                        resp = self._chat(messages, tools=round_tools, model=tool_model, local_only=local_only)
                     except Exception:
                         resp = self._chat(messages, model=tool_model, local_only=local_only)
```
Optional: `if not _round_ledger["context_fits"]: break` to stop chaining and let the final round speak.

### Patch B → `server.py` (schedule bounded tier maintenance; `mindpage_mod` imported L72)
Mirror `_maintain_mindpage_content_index`: add interval const `ALPECCA_MINDPAGE_TIER_MAINTENANCE_INTERVAL`
(default 900s, floor 60s), two `_background_autonomy_status` keys, a new
`_maintain_mindpage_tiers()` helper that runs via `_optional_bounded_thread("routine",
"mindpage_tier_maintenance", mindpage_mod.maintain_pages, timeout=10, cooperative=True)` (defers
under chat/TTS, no LLM under lock, cooperative cancel), and schedule it right after the existing
content-index maintenance call (~L2174). Full body in the Lane A branch / handback.

---

## Lane B — Phase 9 provider/egress consent + multimodal
- **Branch:** `worktree-agent-ab8b4fc9edcc3bf52` @ `574a71e`
- **Owned files changed:** `alpecca/egress_consent.py` (+141), `alpecca/vision.py` (+~75),
  new `tests/test_phase9_perception_egress_gate.py` (17 tests). The five ingress guards were
  already fail-closed/local-only — verified, unchanged.
- **Delivered:** `PerceptionEgressGate.authorize_attempt(...)` = one fresh interactive creator
  consent + atomic one-use bounded consume, bound to the exact route
  (provider+deployment+model+capability+purpose+location+destination+HTTPS-route) and to the exact
  bytes via keyed HMAC. `vision.describe_image_via_consent(...)` is the only remote path; absent/
  denied/misconfigured consent → provider never runs → returns `None` → verified-local fallback,
  never relabeling cloud as local. Default wrappers stay verified-local.
- **Tests:** Phase 9 **333 passed / 2 skipped** (+17); core egress 2 passed. Verifier subagent
  audited fail-open/relabel/TOCTOU/binding vectors → SOUND.
- **Residual:** inert until `server.py` constructs it; route policy MUST use **real operator-attested**
  cloud values (do not invent locations); production monotonic anchor still required for Phase 9 DONE;
  recommend `max_uses=1` per perception route.

### Patch → `server.py` (lane 0)
(a) One-time startup: build `PerceptionEgressGate` from an `EgressConsentLedger` with a **real
interactive creator authority** + **attested route policy** + a `SQLiteMonotonicAnchor` in a
**separate db file**; return `None` if either is absent → all vision stays verified-local (current
default). (b) Call-site pattern (Discord image branch ~L7305, screen-sight ~L5499, house-hq image
~L7325, webcam WS ~L7746): attempt `describe_image_via_consent(...)` only when the gate exists AND
the creator explicitly opted into remote perception **for this turn** (never a config/env flag);
else keep the local `local_only=True` call. Full snippet in the Lane B handback.

---

## Lane C — Phase 11 notification reliability + mobile acceptance
- **Branch:** `worktree-agent-add8b5f86b62b3a56` @ `4f4c729`
- **Owned files changed:** `alpecca/web_push_runtime.py`, `tests/test_phase11_web_push_runtime.py`
  (+5), `tests/test_phase11_web_push_server.py` (+1), new `docs/PHASE11_NOTIFICATION_ACCEPTANCE.md`.
  (`notification_outbox.py`, `notification_anchor.py`, `web_push_adapter.py`, `web/sw.js` unchanged.)
- **Delivered:** closed the documented residual — ack-receipt consumption was per-row sealed only,
  so restoring a pre-consumption DB could double-ack. Added an **optional** `ack_anchor` (monotonic,
  separate failure domain): new sealed `notification_push_ack_meta` table + two-phase
  `LedgerCheckpoint` that **fails closed** when the SQLite count regresses below the external anchor.
  Defaults to `None` → fully backward-compatible; fixed connection-test template + one-use receipt
  preserved; SMS/calls/Discord/`creator_contact.py` untouched.
- **Tests:** Phase 11 **210 passed** (+6, incl. DB-rollback rejection); `house:build` succeeded.
- **Residual:** anchor inert until wired; **mobile soak PENDING** (real installed PWA); protects
  consumptions from enablement forward (attach at first deployment).

### Patch → `server.py` `_notification_runtime()` (lane 0)
(a) New target const `_NOTIFICATION_PUSH_ACK_ANCHOR_TARGET = "Alpecca/NotificationPushAckAnchor"`
(~L2519). (b) After the existing `subscription_anchor = (...)` block (~L2659), build a
`CredentialMonotonicAnchor(WindowsCredentialManagerBackend(_NOTIFICATION_PUSH_ACK_ANCHOR_TARGET),
anchor_key=push_store_key)`. (c) Pass `ack_anchor=ack_anchor` to the `WebPushPrivateStore(...)`
constructor (~L2689). Reuses the existing key; new credential = separate failure domain; existing
credentials untouched.

---

---

## Lane O — Knowledge foundation (Track D)
- **Branch:** `worktree-agent-a179519d2abd0dacc` @ `827ba3c`
- **New files only:** `alpecca/knowledge_blocks.py` (brain-section blocks; sections = memory kinds;
  state locked/unlockable/populated; unlock `risk/reward/rate_limit/guarded` **recorded, not
  enforced**; `brain_map_snapshot()`), `alpecca/taught_facts.py` (authenticated-speaker teaching +
  honest recall), `apps/house-hq/src/brainMap.ts` (read-only canvas map, **not** imported into
  main.ts), 3 test files.
- **Teaching contract:** a fact is writable only via `teach_fact(text, speaker, ...)` where
  `speaker` is minted **only** by `authenticate_speaker(auth_decision)` from a positive creator
  decision; a hand-built identity (what a self-prompt could fabricate) lacks the module-private
  witness and is refused; provenance must be genuine input (`spoken|typed|authenticated_input`),
  `model|self|inference|latent` refused. Recall returns effective (age-decayed, reinforced)
  confidence: below 0.35 → `hedged`; no match → `unknown` ("haven't learned that"); `text` is only
  ever a genuinely stored fact — never fabricated.
- **Tests:** knowledge suite **27 passed**; `house:build` clean (brainMap.ts type-checks).
- **Residual:** unwired (PARTIAL); unlock costs recorded but not enforced (governed learning =
  Phase 8, gate before any non-creator teacher); witness is defense-in-depth, not airtight; recall
  keyword-only (embeddings later via `memory.py`'s `embed_fn`); creator scope only (Rygen widening
  is a one-line `ALLOWED_TEACHER_PRINCIPALS` change deferred to the identity lane).
- **Patches:** `mind.py` — mint speaker from the existing AuthDecision on an explicit teach intent,
  and consult `recall_answer(...)` before answering a factual question (unknown → "say you haven't
  learned it, don't guess"; hedged → hedge; confident → recall), injected as a grounding block
  **before** cappable sections. `server.py` — read-only `GET /knowledge/brain-map` →
  `knowledge_blocks.brain_map_snapshot(scope="creator")` (global auth middleware already applies).

## Lane Q — Preferences + grounded read-the-room (Track F)
- **Branch:** `worktree-agent-a911ba084612bd040` @ `b9bc798`
- **New files only:** `alpecca/preferences.py` (favorites store; guarded writes via injected
  authorizer, **fail-closed** default mirroring `turn.principal == "creator"`), `alpecca/overload.py`
  (read-the-room signal derived **only** from real cues — message volume, concurrent actors,
  context pressure, host pressure; **unknown stays unknown**, cited evidence, framed
  `workload_pressure` not emotion), `apps/house-hq/src/preferencesPanel.ts` (read-only, not wired),
  2 test files.
- **Tests:** preferences suite **30 passed**; `house:build` clean.
- **Residual:** unwired (PARTIAL). **Instrumentation gap it surfaced:** concurrent-actor count only
  exists as `len(ws_clients)` and turn-rate is unmeasured — those cues correctly stay `unknown`
  rather than fabricated; a real turn-rate meter is net-new work.
- **Patches:** route through the *existing* `response_strategy`/`working_memory` prompt envelope
  (already labeled "not a feeling") + read-only `GET /api/preferences/snapshot` and
  `GET /api/overload/read-the-room`. Never alter affect math/identity/initiative.

## Lane I — Durable routine execution (Stage 5)
- **Branch:** `worktree-agent-a1bcbe731fd5bd82c` @ `95ba57a`
- **Files:** new `alpecca/routine_ledger.py` (atomic expiring-claim ledger) + reworked
  `alpecca/routines.py` (`due()`→`mark_ran()` becomes a claim protocol; legacy calls kept
  compatible) + new test file. Two pollers run a due routine **exactly once**; deferred/cancelled
  **stays due**; success/terminal-failure advances once; crash-recovery via expired-lease reclaim;
  retry/backoff; explicit missed-run policy (no offline burst); DST-deterministic via injectable
  clock.
- **Tests:** ledger suite **15 passed** (concurrency stable ×3); existing routine test still green.
- **Residual:** single-process exactly-once (relies on SQLite single-writer — fine for current
  deployment); compatible-by-design with Lane A's cooperative-cancel coordinator.
- **Patches — more entangled than the others:** `server.py` `_run_due_routines_once` rewrite (an
  errored routine now **retries/backs-off** instead of being silently marked done — a behavior
  change to confirm) **plus a REQUIRED coupled update** to the existing
  `tests/test_phase6_resource_server.py` (it monkeypatches the now-removed `due`/`mark_ran`). Both
  patches supplied.

---

## Recommended integration order (Codex / CreatorJD)
Independent, low-coupling foundation lanes first; Codex-hot-path lanes after the Wave-0 checkpoint;
security/enforcement last.
1. **Q, O** (foundation, additive) — new modules + two read-only GET endpoints each; nothing
   existing changes except new prompt-envelope reads. Lowest risk.
2. **C** (Phase 11) — additive optional `ack_anchor` kwarg; 3-line `server.py` wiring.
3. **A** (Phase 6) — `mind.py` tool loop + `server.py` maintenance schedule; apply **after Codex's
   Wave-0 RSI checkpoint** since it touches the live `mind.py`.
4. **I** (routines) — apply with its **coupled** `test_phase6_resource_server.py` update; confirm the
   errored-routine retry behavior change is intended.
5. **B** (Phase 9) — security-critical; ships **inert/safe** now (vision stays verified-local). Do
   **not** wire a live egress gate until a real interactive creator authority + attested cloud route
   policy + production monotonic anchor exist.

**Enforcement still gated (not in these lanes):** governed learning / unlock-cost enforcement for O
(Phase 8), a real turn-rate meter for Q, and live egress for B — each needs its spine gate or a
creator decision. Each lane branch is preserved for review/cherry-pick; re-run its gate after wiring.
