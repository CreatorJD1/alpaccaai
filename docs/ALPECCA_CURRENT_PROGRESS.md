# Alpecca Current Progress

Last verified: **2026-07-17**

This is the short operational status. `PROJECT_CONTEXT.md` remains canonical;
`HANDOFF.md` contains implementation detail and verification history.

## Phase Matrix

| Phase | Status | Current evidence / remaining gate |
|---|---|---|
| P0 Truth baseline | COMPLETE | Encrypted capture, verification, restore, tamper rejection, and failure tests pass. |
| P1 Security containment | PARTIAL | Protected HTTP/WS auth, capability audits, and device trust exist. The July 17 current-source + House scan passed with 1,078 files, zero findings, and zero errors. Republishing the public shell from this verified bundle remains open. |
| P2 Identity + singleton | COMPLETE | Stable creator identity, cross-process singleton ownership, and stale portal fencing are tested. |
| P3 Turn transactions | COMPLETE | Scoped immutable turns, cancellation barriers, and stale-commit rejection are tested. |
| P4 Commitment closure | COMPLETE | The bounded `self_status` cue-to-execution gate is exactly-once and receipt-backed. |
| P5 Initiative + affect | COMPLETE | Shared initiative budget, dedupe, one-surface delivery, ignored-outreach backoff, and grounded affect are tested. |
| P6 Mindpage + resources | PARTIAL | Paging, pressure sensing, and safe preflight exist. The July 17 real 8,192 attempt was blocked before HTTP by high host pressure. After clearing the stale audit server, headroom remained below both launch gates at 3.98 GiB/17.1% RAM and 21.60 GiB/4.7% disk. No Ollama request or system mutation occurred. |
| P7 Pagefile broker | BLOCKED | Read-only exact-step planning exists. Durable approval is being added; no UAC helper, write, or system mutation exists. |
| P8 Bounded RSI | PARTIAL | Two-hour/five-outcome lifecycle, settlement, review decisions, rollback, server integration, and governed learning passed 309 focused tests on July 17. No real creator-approved trial has soaked. |
| P9 Perception + egress | PARTIAL | Local source/image/audio ingress and leases work. The authenticated exact-byte, one-use remote perception route, creator API controls, and House HQ Privacy panel passed the full 322-test P9 gate plus 55 House module tests. One configured-provider live consent soak remains open. |
| P10 Discord + voice | PARTIAL | Claimed rooms, signed actors, media, voice send, and local receive foundations exist. July 17 readiness found output dependencies ready and receive dependencies installed; receive remains disabled. The stale audit HTTP server was stopped and port 8765 is clear, but the full stack was not started under unsafe host pressure. A real duplex voice soak and independent production anchor remain open. |
| P11 Contact + outbox | PARTIAL | Durable Web Push test outbox exists. Real browser enrollment, provider acceptance, click acknowledgement, and mobile soak remain open. |
| P12 V4 embodiment | PARTIAL | V4 is VRM 1.0 with 74 spring joints. Gait restart, displacement yaw, unsafe loop seams, and gaze reset are fixed; live walk/physics/design proof remains open. |
| P13 Cloud continuity | PARTIAL | Fenced HF promotion is live. Encrypted append-only chat/memory/game-event reconciliation is test-green and Vault Worker version `0cf0bdb8-d1f6-48f1-a2f9-71ea0bb76582` is deployed; survival-Space publication plus a real cloud-to-local failback receipt remain open. The permanent Ubuntu desktop VM is still absent. |
| P14 Release soak | BLOCKED | Observation-only harness and public mobile probes exist; repository collection now succeeds. Full live soak and clean deployment evidence are still absent. |

## Current Deliverables

- **Brain Garden:** protected live diagram at `/house-hq?system=internals`, with
  collapsible evidence-backed nodes and explicit unknown/unfinished state.
- **Android 2.2.5:** Android Keystore device trust, locally validated challenge
  transcript, origin-bound revocable cookie, endpoint rediscovery, and
  credential-free APK distribution.
- **Mindscape Vault:** AES-256-GCM encrypted passive snapshots and SQLite
  archives in R2, plus source-complete encrypted append-only event segments.
  Cloud sees ciphertext only; event writes require the active singleton fence.
- **Agentic Frontier vertical slice:** a separate server-authoritative Jason +
  Alpecca co-op relay mission with bounded perception, idempotent actions,
  reconnect receipts, and a validated companion-memory boundary. The planned
  anime-cel-shaded client and cloud multiplayer deployment are not built yet.
- **Ubuntu standby scaffold:** provider-neutral dry-run supervisor, app
  verifier, workspace template, systemd examples, and duplicate-instance lease.
- **Soul evidence:** one deterministic seven-perspective score vector with
  contradiction/pressure escalation evidence; zero model calls and no claim of
  seven transformer instances.
- **Release evidence:** content-free secret-scan receipt covering 1,080 current
  source and built House files with zero findings and zero scan errors.

## Phone And Live Stack

- The reviewed APK is
  `https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/AlpeccaLauncher-v2.2.5.apk`.
- Endpoint discovery is
  `https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/alpecca-endpoint.json`.
- The current public relay is temporary and discoverable. A permanent named
  Cloudflare hostname still requires a Cloudflare-owned DNS zone and completed
  named-tunnel login.
- Source changes in this checkpoint require one controlled full-stack restart
  before the running server, Discord bridge, and phone surface can be called
  live-verified.

## Verification

- `python -m pytest -q tests/test_core.py`: **359 passed** before the final
  integration rerun.
- Device trust + Android + Stage 1 security: **43 passed**.
- Mindscape restore approval focused tests: **4 passed**.
- Continuity journal + Agentic Frontier + HF supervisor focused tests: **31 passed**.
- Mindscape Vault Worker: JavaScript syntax and Wrangler 4.111.0 dry-run passed.
- Brain Graph tests: **4 passed**.
- House embodiment tests: **20 passed** in the animation lane.
- Repository collection-only: **2,321 tests collected**, exit `0`.
- `npm.cmd run house:build`: passed; retained bundle-size advisory only.
- Android release build: passed; public/local APK SHA-256 matched exactly.
- Knowledge blocks, creator-only teaching, and honest recall: **27 passed** on
  July 17.
- Phase 8 bounded RSI and governed learning: **309 passed** on July 17; no live
  candidate or autonomous trial was started.
- Phase 9 local perception, source access, capability leases, exact egress
  consent, and server controls: **322 passed, 2 skipped** on July 17.
- House HQ privacy normalization, exact-image execution matching, and malformed
  ingress rejection: **55 passed** across all House module tests on July 17.
- House production build: passed on July 17 with the existing large-chunk
  advisory only.
- July 17 P1 scan after preserving the three existing documentation deletions:
  **0 findings**, **0 errors**, `release_ready=true`; the current content-free
  receipt is `output/release-secret-scan.json`.
- Core regression suite after the Phase 9 integration: **365 passed**.
- House production build after the Phase 9 integration: passed with the
  existing large-chunk advisory only.

## External Gates

These cannot be truthfully marked complete from source changes alone:

1. Install Android 2.2.5 and perform one password sign-in to enroll the phone key.
2. Complete one live Discord microphone/playback latency and voice-quality soak.
3. Run authenticated V4 walking, terminal-contact, and ten-minute physics proof.
4. Select/provision an Ubuntu VM provider before activating the fenced standby.
5. Complete Cloudflare named-tunnel login and DNS routing for a fixed hostname.
6. Run the full P14 soak windows and retain their content-free receipts.
7. Redeploy the Vault Worker and HF survival core, then retain a controlled
   cloud-created-event to local-failback merge receipt.
