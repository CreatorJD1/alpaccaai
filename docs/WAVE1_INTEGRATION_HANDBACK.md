# Wave 1 Integration Handback (Claude Code coordinator → Codex / CreatorJD)

**Date:** 2026-07-13. **Status:** three lanes complete on **isolated branches — nothing merged.**
Each carries an integration patch for a **lane-0 (Codex-owned) file** (`mind.py` / `server.py`),
so integration is Codex's call, applied serially after review. All three report **PARTIAL** (owned
code + scoped tests green, but not live-wired). Honest-status rule enforced: code alone ≠ DONE.

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

## Recommended integration order (Codex / CreatorJD)
1. **Lane C** first — smallest, lowest-risk, additive optional kwarg; 3-line `server.py` wiring.
2. **Lane A** next — Patch A (`mind.py` tool loop) + Patch B (`server.py` maintenance schedule).
   Note `mind.py` is Codex's live Phase 8 file — apply after the Wave-0 RSI checkpoint to avoid churn.
3. **Lane B** last — security-critical; do **not** wire a live gate until a real interactive creator
   authority + attested cloud route policy + production anchor exist. Until then it ships inert
   (vision stays verified-local), which is safe to merge.

Each lane branch is preserved for review/cherry-pick; re-run each lane's gate after wiring.
