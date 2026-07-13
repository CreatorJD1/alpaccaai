# Phase 11 Notification Reliability & Mobile Acceptance Checklist

Lane C manual acceptance checklist for the creator-only app Web Push
connection-test slice. This document does **not** trigger real sends; it
describes how to verify each acceptance item on a real enrolled device and maps
every item to the automated test that proves the underlying mechanism.

## Scope and invariants (must stay true)

- Only the **fixed connection-test template** exists. Title/body are compile-time
  constants in `alpecca/web_push_runtime.py`
  (`TEST_TITLE = "Alpecca creator alerts"`,
  `TEST_BODY = "Creator alerts are connected. Tap to acknowledge this test."`).
  No model, cognition path, routine, or autonomous trigger can enqueue a
  notification; `enqueue_connection_test` is the only enqueue path and it is
  creator-request driven.
- Out of scope for this lane and intentionally absent: SMS, phone calls,
  arbitrary Discord delivery, arbitrary payloads, escalation, and the untracked
  `alpecca/creator_contact.py` experiment (rejected WIP, never imported).
- Subscription endpoints, browser keys, VAPID material, and outbox/subscription
  monotonic state stay in dedicated Windows Credential Manager records. Payloads
  are opaque references; no secret or endpoint appears in SQLite, logs, or this
  document.

## Automated coverage

Run the scoped gate (no real device or Credential Manager required — tests use
`tmp_path` plus in-memory anchors and fake credential records):

```powershell
python -m pytest -q tests\test_phase11_*.py
npm.cmd run house:build
```

## Acceptance matrix

| # | Acceptance item | Automated proof (test name / file) | Manual verification (real device) |
|---|---|---|---|
| 1 | **Browser enrollment** | `test_subscribe_accepts_only_the_exact_bounded_browser_shape`, `test_subscribe_rejects_wrong_shapes_and_expirations` (`test_phase11_web_push_server.py`); `test_subscription_registration_requires_exact_valid_shape`, `test_subscription_upsert_cap_and_strict_revoke` (`test_phase11_web_push_runtime.py`) | In House HQ Devices controls, enroll this browser. Confirm the status shows exactly one subscription and the browser prompted for notification permission. |
| 2 | **Accepted-device delivery (exactly one test)** | `test_accepted_delivery_marks_sent_builds_bounded_payload_and_acknowledges`, `test_concurrent_delivery_workers_produce_one_claim_and_one_send` (`test_phase11_web_push_adapter.py`); `test_connection_test_maps_an_accepted_transport_result` (`test_phase11_web_push_server.py`) | Request one connection test. Confirm the device shows exactly **one** notification with the fixed title/body. No duplicate for the same event tag. |
| 3 | **Click acknowledgement (accepted exactly once)** | `test_acknowledgement_requires_bound_signed_receipt_and_rejects_replay`, `test_acknowledgement_maps_a_valid_pre_sent_receipt_to_conflict` (`test_phase11_web_push_server.py`); `test_receipt_is_expiring_and_one_use` (`test_phase11_web_push_runtime.py`); `test_acknowledgement_rejects_wrong_replayed_and_wrong_event_receipts` (`test_phase11_web_push_adapter.py`) | Tap the notification. House HQ focuses/opens `/house-hq`. Confirm the connection test shows acknowledged. Tapping again (or a retried ack) does not produce a second acknowledgement. |
| 4 | **Retry** | `test_acknowledgement_retry_after_reservation_succeeds_once_sent` (`test_phase11_web_push_adapter.py`); `test_reserved_receipt_recovers_after_reopen_and_original_expiry` (`test_phase11_web_push_runtime.py`); service-worker bounded retry in `web/sw.js` (`retryPendingAcknowledgementsBounded`, IndexedDB `pending` store) | Tap the notification while offline, then reconnect and open `/house-hq`. Confirm the queued ack is delivered exactly once on reconnect (cooldown-bounded, batch-limited). |
| 5 | **Revoke blocks later sends** | `test_revoke_blocks_a_later_connection_test_send`, `test_delete_revokes_only_the_exact_endpoint` (`test_phase11_web_push_server.py`); `test_subscription_upsert_cap_and_strict_revoke` (`test_phase11_web_push_runtime.py`) | Revoke the browser in Devices controls. Request another connection test. Confirm it is refused with "no creator browser subscription" and the device receives nothing. |
| 6 | **Ack-consumption rollback protection (new monotonic anchor)** | `test_ack_consumption_anchor_rejects_receipt_db_rollback`, `test_ack_consumption_anchor_advances_and_reopen_is_idempotent`, `test_ack_consumption_anchor_rejects_missing_anchor_for_consumed_state`, `test_ack_consumption_anchor_rolls_forward_after_interrupted_commit`, `test_ack_anchor_must_be_a_distinct_failure_domain` (`test_phase11_web_push_runtime.py`) | Requires the server integration patch (below) to wire the ack anchor to its own Credential Manager record. Once wired, restoring a pre-consumption push database must fail closed instead of re-acknowledging. |
| 7 | **No payload secret in logs** | `test_secrets_are_absent_from_repr_public_status_and_sqlite` (`test_phase11_web_push_runtime.py`); sanitized transport result and opaque payload references throughout | After the manual run, grep server logs and the push SQLite for the endpoint host, `p256dh`, `auth`, VAPID key, and raw `wpa_` receipts. Confirm none appear. |
| 8 | **Mobile soak** | Not automatable in this suite. | **PENDING — not executed in this lane.** See "Mobile soak procedure" below. Requires a real installed PWA on the target phone. |

## Manual gate (from the delegation packet)

Verify, without executing sends from this lane:

1. One enrolled device receives **exactly one** connection test.
2. One creator click is accepted **exactly once** (replay/second click does not
   double-acknowledge).
3. Revoke **blocks later sends** (a subsequent test reaches zero devices).
4. **No payload secret** (endpoint, keys, VAPID material, raw receipt) appears in
   logs or SQLite.

## Mobile soak procedure (PENDING)

Not yet run. To perform it later on the target phone:

1. Install House HQ as a PWA on the phone over HTTPS creator trust (loopback LAN
   HTTP cannot enroll a creator device).
2. Enroll the phone browser and confirm one subscription.
3. Over an extended session (target: continuous background across screen-lock,
   network changes, and app-backgrounding for the soak window), periodically
   request a connection test and record: delivery latency, duplicate count
   (expect zero per event tag), click-ack success, and offline-then-online ack
   retry behavior.
4. Confirm the service worker never acknowledges on receipt or on display — only
   on an explicit click — and that pending acks survive a browser restart via
   IndexedDB and flush on the next same-origin navigation.
5. Confirm no secret or endpoint leaks into device console/network logs.

Record the soak evidence (dates, device, counts, latencies) here when complete.
Until then, Phase 11 mobile soak remains **unverified** and Phase 11 stays
**PARTIAL**.

## Residual and honest status

- The acknowledgement-receipt consumption path is now backed by a **monotonic
  anchor in a separate failure domain** (a dedicated Windows Credential Manager
  record, distinct from the subscription and outbox anchors and existing
  credentials). This closes the previously documented residual where restoring a
  valid pre-consumption receipt database could return a second idempotent
  acknowledgement success. The protection is **active only when the store is
  constructed with `ack_anchor=`**, which requires the server integration patch
  in the Lane C handback. Without it, the store still functions exactly as
  before (no behavior change) but the ack-consumption rollback protection is
  inactive.
- Anchoring protects consumptions from anchor enablement forward. Consumptions
  that occurred before the anchor was first attached to an existing database are
  not retroactively bound; enable the anchor at first deployment of the push
  store to avoid an unprotected window.
- Bundled SQLite anchors remain development-only rollback detectors. Production
  protection relies on the separate Credential Manager failure domain.
