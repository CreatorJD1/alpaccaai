# Alpecca Current Progress

Last verified: **2026-07-22**

This is the short operational status. `PROJECT_CONTEXT.md` remains canonical;
`HANDOFF.md` contains implementation detail and verification history.

The July 22 proof boundary is deliberately narrow. Receipt-language and hosted
tool partial-execution honesty are fixed. Temporal shadow comparison is wired as
evaluation-only evidence while legacy SQLite/Mindpage recall remains
authoritative, and temporal fact writes are transaction-atomic. Cloud voice
health now requires playable PCM WAV evidence. The complete inherited singleton
tuple and speaker inference readiness both fail closed. YuNet/SFace weights are
installed and CPU-load verified outside Git, but face familiarity is not
production-wired and has no personal corpus; sherpa remains uninstalled because
the selected speaker model's license is unresolved. No post-restart live Discord
voice proof was completed for these latest changes.

## Phase Matrix

| Phase | Status | Current evidence / remaining gate |
|---|---|---|
| P0 Truth baseline | COMPLETE | Encrypted capture, verification, restore, tamper rejection, and failure tests pass. |
| P1 Security containment | PARTIAL | Protected HTTP/WS auth, capability audits, and device trust exist. The July 17 current-source + House scan passed with 1,078 files, zero findings, and zero errors. Republishing the public shell from this verified bundle remains open. |
| P2 Identity + singleton | COMPLETE | Stable creator identity, cross-process singleton ownership, and stale portal fencing are tested. Configured cross-host server import requires the complete inherited lease ID, holder, positive epoch, and same-process launcher PID; only explicit offline-isolated mode may start unfenced. |
| P3 Turn transactions | COMPLETE | Scoped immutable turns, cancellation barriers, and stale-commit rejection are tested. |
| P4 Commitment closure | COMPLETE | The bounded `self_status` cue-to-execution gate is exactly-once and receipt-backed. Conversational `I finished/I opened` phrases no longer false-trigger the external-action guard, and hosted tool partial execution remains honestly reported if a later call is rejected. |
| P5 Initiative + affect | COMPLETE | Shared initiative budget, dedupe, one-surface delivery, ignored-outreach backoff, and grounded affect are tested. The seven Soul perspectives remain compact deterministic scoring; one bounded textual arbitration may run only for a contradiction, measured pressure, or a close tie. |
| P6 Mindpage + resources | PARTIAL | Paging, pressure sensing, and safe preflight exist. The July 17 real 8,192 attempt was blocked before HTTP by high host pressure. After clearing the stale audit server, headroom remained below both launch gates at 3.98 GiB/17.1% RAM and 21.60 GiB/4.7% disk. No Ollama request or system mutation occurred. |
| P7 Pagefile broker | BLOCKED | Read-only exact-step planning exists. Durable approval is being added; no UAC helper, write, or system mutation exists. |
| P8 Bounded RSI | PARTIAL | Two-hour/five-outcome lifecycle, settlement, review decisions, rollback, server integration, and governed learning passed 309 focused tests on July 17. No real creator-approved trial has soaked. |
| P9 Perception + egress | PARTIAL | Local source/image/audio ingress and leases work. The authenticated exact-byte, one-use remote perception route, creator API controls, and House HQ Privacy panel passed the full 322-test P9 gate plus 55 House module tests. One configured-provider live consent soak remains open. |
| P10 Discord + voice | PARTIAL | Claimed rooms, signed actors, media, voice send, local receive, Silero endpointing, interruption, and cloud-first Kokoro routing are integrated. Cloud health now rejects missing evidence and header-only/non-playable WAV output. Earlier Silero and deployed HF Kokoro smokes remain bounded historical evidence; the latest source has no post-restart live Discord proof. |
| P11 Contact + outbox | PARTIAL | Durable Web Push test outbox exists. Real browser enrollment, provider acceptance, click acknowledgement, and mobile soak remain open. |
| P12 V4 embodiment | PARTIAL | V4 is VRM 1.0 with 74 spring joints. Gait restart, displacement yaw, unsafe loop seams, and gaze reset are fixed; live walk/physics/design proof remains open. |
| P13 Cloud continuity | PARTIAL | Fenced HF promotion and the survival Space are deployed. Authenticated cloud Kokoro synthesis completed one smoke. Encrypted append-only chat/memory/game-event reconciliation is test-green and Vault Worker version `0cf0bdb8-d1f6-48f1-a2f9-71ea0bb76582` is deployed; controlled cloud-created-event reconciliation and a real cloud-to-local failback receipt remain open. The permanent Ubuntu desktop VM is still absent. |
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
- **Soul evidence:** seven compact deterministic perspective scores remain the
  normal path. One bounded textual arbitration call is permitted only for a
  contradiction, measured pressure, or a close tie. They are not seven
  transformer instances.
- **Research integration:** temporal facts, contradiction/supersession history,
  source provenance, evaluation-only shadow comparison, transaction-atomic fact
  application, and selective Soul arbitration are integrated in source. Speaker
  readiness requires a successful bounded inference probe and fails closed.
- **Face evaluation assets:** YuNet
  `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`
  and SFace
  `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`
  are installed under `%LOCALAPPDATA%\Alpecca\models\face\`; both passed an
  OpenCV CPU load smoke. They are not production-wired and no personal face
  corpus has been enrolled. `sherpa_onnx` and a speaker model remain absent
  pending resolution of the selected model's upstream license.
- **Release evidence:** a separate July 17 broader content-free secret-scan
  receipt covered 1,080 source and built House files with zero findings and zero
  scan errors. The P1 row retains its narrower 1,078-file scan as distinct
  historical evidence.

## Phone And Live Stack

- The single supported launcher is
  [`ALPECCA_LAUNCHER.bat`](../ALPECCA_LAUNCHER.bat); retired wrapper scripts are
  historical evidence, not supported entry points.

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

- July 22 broad `tests` run with the intended offline-isolated continuity
  setting: **3,197 passed, 3 skipped, 0 failed**; House production build passed.
- Subsequent receipt-language, hosted tool-loop, playable-WAV health,
  speaker-readiness, temporal atomicity/shadow, and inherited-singleton changes
  passed their focused tests. The broad suite was not rerun after every final
  focused patch.
- Deployed HF cloud Kokoro completed an authenticated synthesis smoke. This is
  not a sustained House-browser or Discord voice-quality soak.
- Silero completed a live receive-path smoke; sustained noise, endpoint,
  interruption, and latency calibration remains open.

- `python -m pytest -q tests/test_core.py`: **359 passed** before the final
  integration rerun.
- Post-ROG integration core regression: **371 passed** on July 22; the focused
  authenticated worker/client/launcher gate passed **156 tests**.
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
2. Complete sustained House and Discord microphone/playback latency,
   interruption, transcription, and voice-quality soaks.
3. Run authenticated V4 walking, terminal-contact, and ten-minute physics proof.
4. Select/provision an Ubuntu VM provider before activating the fenced standby.
5. Complete Cloudflare named-tunnel login and DNS routing for a fixed hostname.
6. Run the full P14 soak windows and retain their content-free receipts.
7. Retain a controlled cloud-created-event to local-failback merge receipt.
8. Retain real-corpus evidence from the now-wired evaluation-only temporal
   shadow comparison: false recall, source attribution, and supersession.
9. Wire optional speaker/face workers only after a licensed speaker model and
  consented personal corpora establish accuracy, ambiguity/replay behavior,
  latency, and resource isolation.
- **ROG compute worker:** the compute-only `Jason_HOLYROG` worker, strict client,
  deep-reflection fallback chain, creator-only status/render routes, launcher
  control, qualification probe, and setup guide are source-complete. The worker
  cannot acquire Alpecca's speaking/continuity roles. Private-LAN use requires
  certificate-validated HTTPS; replay state persists without storing prompts or
  results. Deployment remains open:
  this laptop could not reach the ROG on port 8788 or a remote-management port,
  so no live health, reasoning, or Blender receipt is claimed.
10. Complete singleton failover/failback soak before qualifying another host or
    cloud runtime as a speaking authority.
11. Run `scripts/setup_rog_worker.ps1 -InstallTls` and the remaining setup
    directly on `Jason_HOLYROG`, copy only its public certificate to the primary,
    restrict its private-LAN firewall rule to the primary laptop, then retain
    authenticated health, reasoning, and (when Blender is configured) one-frame
    render receipts. Do not run the main launcher or Discord bridge on the ROG.
