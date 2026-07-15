# Alpecca — Handoff (updated 2026-07-15)

## Codex Reconnect And Alpecca App Update Center (2026-07-15)

- The July 15 reconnect regression was a stale R2 mobile-discovery object that
  still advertised `floppy-fans-tan.loca.lt` after the live stack had moved to
  Cloudflare. The public record was republished to the active fenced endpoint.
  `publish_mobile_endpoint.py` now retries a newly issued tunnel's exact
  `/healthz` identity before publishing, closing the startup race that left the
  old record in place.
- Android 2.2.3 (code 9) turns the native launcher into the **Alpecca App Update
  Center**. Its scrollable panel keeps check, byte download, package/signature
  verification, and install status visible; a verified install action remains
  available until Android's installer is opened. **Refresh House source** clears
  stale WebView cache, adds a cache-busting source revision, and rediscovers the
  fenced endpoint without deleting trusted-device cookies.
- The immutable APK is
  `https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/AlpeccaLauncher-v2.2.3.apk`
  with SHA-256
  `52d7a4f5452e438657cb3fdeedfa8c3225e0fd4fdced31411bd2f70cbeb64165`.
  The public manifest advertises code 9 and matches the downloaded bytes.
- The private `CREATORJD/alpecca-cloud-desktop` noVNC Space is provider-paused
  as `Flagged as abusive`; do not clone or restart it to evade moderation.
  Cloudflare's live Containers API also rejects this account because Workers
  Paid is not enabled. No supported VM-provider CLI or authenticated account is
  present on this machine, so the persistent cloud desktop is still blocked.
  The existing desktop-only image and Ubuntu policy scaffold remain inert and
  must not be described as running.

## Codex Fenced Cloud Survival And Android 2.2.2 (2026-07-15)

This section supersedes older claims below that transactional cloud failover is
blocked or that Android 2.1.2 is the current public launcher.

- The working survival host is the public Docker Space
  `CREATORJD/alpecca-survival-core` at
  `https://creatorjd-alpecca-survival-core.hf.space`. The earlier
  `CREATORJD/alpecca-cloud-core` Space was provider-paused after its image
  contacted a blocked `workers.dev` hostname and must not be advertised as a
  usable fallback.
- Hugging Face reaches the existing lease authority and encrypted Vault only
  through `https://alpecca-continuity-gateway.pages.dev`. The Cloudflare Pages
  Functions gateway has service bindings to both Workers, contains no secret,
  stores no state, exposes a content-free `/healthz`, and keeps Worker-to-Worker
  calls off public DNS.
- The survival image never copies `.git`, deployment code, docs, scripts,
  tests, notebooks, workflows, or local launcher artifacts into its final
  runtime layer. Its health-only standby listener does not load CoreMind or a
  model. Promotion requires an authenticated current Vault archive, no active
  lease, no fresh local-primary heartbeat, a newer fencing epoch, and exact
  endpoint publication under that grant.
- A controlled live outage passed end to end. Fresh encrypted archive sequence
  162 restored successfully; local-primary epoch 5 expired; cloud-standby
  acquired epoch 7 and returned a protected WebSocket reply; restarting the
  laptop stack reclaimed epoch 9; the Space then returned to
  `alpecca-continuity-standby`. At no point did two endpoints own the authority.
- The fallback model is hosted `Qwen/Qwen3.5-9B` on Hugging Face. The normal
  launcher split remains `gemma4:cloud` for hosted chat/deep work and
  `qwen3.5:9b` for local reasoning/vision/offline work. Never restore the
  retired `qwen3:8b` default.
- This is a headless survival CoreMind, not the requested permanent Ubuntu app
  desktop. Discord, camera, screen, microphone, computer use, local voice
  workers, legacy Mindscape sync, and cloud Vault writes remain disabled while
  cloud-active. The Ubuntu desktop scaffold is still unprovisioned.
- Android launcher 2.2.2 (version code 8) is built and publicly released at
  `https://pub-5c5620dd93c7472b8ae65bb0e0a6f5be.r2.dev/mobile/AlpeccaLauncher-v2.2.2.apk`.
  SHA-256 is
  `a5666d86074a94ab59f33d439087b0058b5007215bec4c4f2d7514ca645927d5`;
  signer certificate SHA-256 remains
  `ed3f06906454aec9f36fd71ba7f1d4686c3ddf8c46ad178f9750f529752988b8`.
- The public update manifest now advertises 2.2.2. The launcher checks it at
  startup at most once per 12 hours, also offers a manual check, downloads into
  private cache, and verifies HTTPS/no redirects, size, digest, package,
  version, and exact signer set. Android still shows the final install prompt;
  silent self-install is unavailable without managed device-owner/store
  privileges.
- After failback the local stack was healthy with one `run_full.py`, one
  `share.py`/Cloudflare relay, one Discord bridge, and one F5 voice worker. The
  authority published local-primary epoch 9 at the then-current quick-tunnel
  origin. Use the authority or launcher discovery instead of copying that
  rotating hostname into source.
- Verification: 28 focused Android/HF/gateway tests and 364 core regression
  tests passed; the clean-commit House production build passed; Android release
  build passed as package `ai.alpecca.launcher` version 2.2.2; the public APK
  bytes matched the manifest digest; Space standby, failover, WebSocket, local
  failback, and cloud demotion were all observed live. Clean commit `0aa46a0`
  scanned 746 tracked files plus 153 built House assets with zero findings or
  errors (receipt SHA-256
  `12f6f1242f535862961171e7fa64b005049c3e000bfd9c378a762ef98c0e103e`).

## Codex Mobile Recovery And Ubuntu VM Scaffold (2026-07-15)

- The July 15 phone failures had one transport cause: the WebView was still on
  the retired `short-glasses-wink.loca.lt` origin. That made both the lazy VRM
  module and protected Systems requests fail. House HQ now checks the public
  endpoint record at startup, replaces a stale saved backend, performs one
  bounded origin recovery, and handles stale Vite chunks without a reload loop.
- The public R2 mobile-discovery object now has a GET/HEAD-only CORS policy so a
  retired browser shell can read the replacement endpoint. The policy contains
  no credentials or private state. R2 remains discovery/continuity storage, not
  an art host.
- The Android launcher now health-checks the active endpoint, rediscovers after
  WebView/network/TLS failures, retries with a bounded backoff, preserves the
  trusted-device cookie store, clears stale navigation history, and supplies
  LocalTunnel's non-secret reminder-bypass header. The rebuilt APK is at
  `output/alpecca-launcher/AlpeccaLauncher.apk`.
- Cloudflare's accountless quick-tunnel API timed out on four bounded attempts.
  The current R2 record therefore still points at the temporary
  `some-meals-smile.loca.lt` endpoint. A permanent hostname still requires the
  existing named-tunnel setup to be completed against a Cloudflare-owned DNS
  zone; do not describe the temporary endpoint as permanent.
- `deploy/ubuntu-app-vm/` now contains the inert first Ubuntu workspace
  scaffold: separate Core and desktop services, loopback-only VNC/noVNC,
  Cloudflare placeholder ingress, fail-closed leader/fencing contracts, and an
  empty creator-approved APT/Flatpak catalog. No VM was provisioned and no unit
  is enabled; this is foundation work, not an online backup Alpecca.
- Verification: core suite `359 passed`; mobile/VM/Brain focused suite
  `14 passed`; House production build passed; Android release build passed;
  local Systems Overview showed live state and nonzero grounded affect.

## Codex Live Brain Plugin Graph And Fallback Preparation (2026-07-15)

- House HQ now includes a live **Alpecca Brain Garden** at
  `/house-hq?system=internals`. The sunflower-centered, symmetric branch view
  has collapsible nested nodes, evidence detail, progress, plugin provenance,
  live refresh, explicit healthy/degraded/disabled/unfinished/unknown states,
  and responsive mobile layout without horizontal overflow.
- `GET /brain/graph` is the authoritative protected snapshot. Declarative JSON
  plugins are discovered from `alpecca/brain_plugins/` and optional
  `data/brain_plugins/`; manifests can select only allowlisted read-only probes
  and cannot execute code or commands. Invalid plugins are surfaced without
  breaking valid graph nodes.
- The graph probes current Ollama/model readiness, persistent memory count,
  seven Soul perspectives, senses, Discord bridge-process presence, server
  voice, Mindpage, Mindscape configuration, and VRM availability. Missing
  evidence is `unknown`, never inferred healthy. The Soul node explicitly
  states that the seven perspectives are not seven independent transformers.
- P0-P14 are represented individually. Only P0 and P3 are shown complete;
  baseline-complete, unsoaked, or partially integrated phases remain
  unfinished. P14 remains not started.
- The VRM embodiment loader now prewarms download and parsing in parallel with
  sprite startup, removes the mobile double-confirm delay, and separates load
  from reveal. Cached 2D-to-3D switching measured `1 ms` in live telemetry.
- `docs/ALPECCA_BRAIN_PLUGINS.md` documents the extension and accuracy contract.
  `docs/UBUNTU_FALLBACK_CORE_PLAN.md` prepares a fenced, single-leader Ubuntu
  app/desktop standby; its inert deployment scaffold is now implemented under
  `deploy/ubuntu-app-vm/`, but no cloud VM is provisioned. `docs/SOURCE_QUALITY_AUDIT_PLAN.md`
  prepares the post-stage source/dead-code/PDF archive audit.
- Focused verification: Brain Graph tests passed (`4 passed`), House HQ
  TypeScript and production build passed, the live graph returned 27 nodes in
  0.184 seconds, mobile/desktop visual checks passed, the roadmap exposed 15
  unique phase children, and the phone discovery endpoint was republished.

## Codex Mindscape Vault Checkpoint (2026-07-15)

- A separate Cloudflare R2-backed **Mindscape Vault** is deployed for encrypted
  continuity recovery. It is a passive backup only: it never hosts a model,
  serves a browser memory view, or creates a second active Alpecca.
- The local vault endpoint is saved only at `data/secrets/mindscape_vault.env`.
  The transport token and AES-256-GCM recovery key are separate Credential
  Manager entries: `Alpecca/MindscapeVaultTransportToken` and
  `Alpecca/MindscapeVaultEncryptionKey`. Neither is in source, Git, browser
  links, or logs.
- Cloud records are opaque, versioned R2 objects. Latest-record selection is
  ordered by authenticated creation time, not a local writer sequence, so a
  late retry or restored writer cannot displace newer continuity data.
- Deployment and isolated live checks passed for encrypted snapshot round-trip,
  cross-writer ordering, and encrypted SQLite archive recovery. A real
  WAL-safe archive of the current `data/alpecca.db` was uploaded successfully
  (`69,009,408` plaintext bytes, no pending archive outbox item).
- The currently running server predates this source change. Its next normal
  restart reads the saved endpoint and begins five-minute encrypted compact
  syncs plus six-hour recovery archives. Do not start a second CoreMind just to
  activate the Vault. `GET /mindscape/vault/status` shows content-free status;
  `scripts/restore_mindscape_vault_archive.py` restores only into a new file.

## Codex Discord, Voice, Continuity, And V4 Checkpoint (2026-07-14)

- Discord media transport now evaluates only the exact incoming Discord event.
  Expanded room history remains model context but can no longer cause an old
  image request to repeat a later `media disabled` diagnostic. An explicit
  self-image request attaches the approved local portrait in both DMs and
  claimed guild rooms, with `accepted -> Discord send -> sent` audit ordering.
  The catalog is closed: it does not send arbitrary paths or files.
- Discord image perception remains verified-local. The installed local
  `qwen3.5:9b` vision call disables Qwen thinking when supported, then retries
  once for older Ollama Python clients. This prevents an all-reasoning response
  from being flattened into an empty `vision unavailable` result. Readiness is
  correctly `unverified` until an actual approved image is processed.
- Discord voice state is now derived from the live voice client, listener,
  local transcriber, and playback facts rather than dependency imports alone.
  The bridge injects those facts through `discord_presence_prompt()` and
  deterministically corrects a false claim that Alpecca is text-only or absent
  from voice while she is actually connected.
- Discord Kokoro output no longer applies linear pitch resampling to the
  explicitly selected `kokoro` route. That resampling could lower and distort
  the locked `af_heart` speaker. Explicit Discord Kokoro now preserves native
  voice timing/pitch, reports cold/warming/ready state truthfully, and gives
  one synthesis caller a 45-second single-flight bound instead of piling up
  duplicate cold-start work. A real CreatorJD Discord playback check is still
  required to judge the acoustic result; do not claim it has been heard and
  approved merely from unit tests.
- `scripts/run_full.py` mirrors the normal `START_HERE.bat` creator-approved
  Discord posture. A direct `scripts/run_discord_bridge.py` launch defaults
  media and voice send on but keeps voice receive off unless
  `ALPECCA_DISCORD_VOICE_RECEIVE=1` is explicit. Voice send and media never
  imply microphone receive; the separate ambient laptop microphone sensor also
  remains off.
- The full launcher acquires an atomic OS-level `alpecca.instance` lock before
  importing config, starting the bridge, or opening the database. A second
  full-stack launch fails before it can create a duplicate CoreMind writer.
  This does not yet guard every direct `python server.py` path, so the launcher
  remains the supported way to start the live stack.
- Startup continuity backup now uses SQLite's online backup API, validates the
  staged copy with `PRAGMA integrity_check`, atomically publishes it, and keeps
  seven `alpecca-*.sqlite3` snapshots. The latest live startup produced a
  verified local snapshot. This protects local recovery; Mindscape remains a
  passive continuity mirror, not a hosted second mind that can converse after
  the laptop is off.
- V4 now grounds with transformed raw-skeleton heel/toe contact anchors rather
  than a fixed sole offset. The ground clamp ignores the airborne swing foot;
  the gait phases contain toe-off, raised swing, dorsiflexion, and heel-led
  contact. House telemetry on the current live V4 load reports the skinned
  contact source and near-zero sole clearance. An authenticated visual walk is
  still the final manual proof of the full motion loop.
- Verification at this checkpoint: `python -m pytest -q tests/test_core.py`
  passed (`359 passed`); focused Discord/media/voice/vision coverage passed
  (`123 passed`); `npm.cmd run house:test:embodiment` passed (`16` tests); and
  `npm.cmd run house:build` passed with only the retained Vite chunk-size
  advisory. The live stack has one `run_full.py` process, one child Discord
  bridge, and the bridge reports `mode=duplex` with local receive ready.

## Codex V4 Transformed Foot Contacts And Live Restart (2026-07-14)

- The V4 gait contact solver no longer subtracts a fixed ankle-to-sole world-Y
  offset. It uses V4's measured skinned heel and toe points in the raw VRM 1.0
  foot/toe bone frames, transforms them every frame, and uses their actual
  world-space low point for grounding and planted-foot targets.
- The V4 rig signature is checked at load from the raw toe pivot. Another valid
  VRM takes a conservative bone-local, rotation-aware fallback instead of
  receiving V4-specific mesh anchors. Debug telemetry now exposes the contact
  source plus heel, toe, low-sole, clearance, and planted-target values.
- During a planted walk, the airborne foot is excluded from the root ground
  clamp. A toe-off roll therefore cannot lift the whole avatar simply because
  its swinging toe intersects the floor plane for a frame. This is a scoped
  gait correction, not a full physics or collision rewrite.
- Headless V4 verification after the same skeleton-combination path used by
  House confirmed the V4 signature and flat contacts: heel `0.000025 m`, toe
  `0.000671 m` above the floor. The pure contact test also pins heel rise and
  toe-led contact under positive ankle pitch.
- Verification: `npm.cmd run house:test:embodiment` passed (`16` tests),
  `npm.cmd run house:build` passed (including TypeScript), and
  `python -m pytest -q tests/test_phase10_discord_locked_modes.py` passed
  (`44` tests; only the upstream Python `audioop` deprecation warning).
- Live checkpoint: the rebuilt backend listens on `127.0.0.1:8765` and its
  single Discord bridge on `127.0.0.1:8779`. Protected local routes return
  expected `401` responses without a trusted session. The bridge reports its
  closed local media catalog and duplex local voice path ready; Discord's
  public gateway returned HTTP `200`. A logged transient DNS error occurred
  during reconnect and resolved at the host level. An authenticated visual
  walk remains the next manual proof, not a reason to bypass the session gate.

## Codex V4 Avatar Motion And Face Correction (2026-07-14)

- The V4 procedural route no longer injects a random mid-route pause. Alpecca
  now remains in the walk cycle until she reaches a destination, yields to an
  actual interaction, or is genuinely blocked and rerouted.
- Unsignaled idle VRMA flourishes are disabled. The old random `Thinking` /
  `LookAround` clips could create an unexplained quick gesture while she was
  resting; idle now uses the procedural breathing, gaze, and blink layer until
  a real state or interaction requests a full-body motion.
- The procedural gait is driven by measured travel speed and now uses
  world-space planted-foot IK: a stance foot stays fixed, while the swing foot
  lifts, travels forward, and lands before the next weight transfer. This
  replaces the prior leg-only pose cycle that could visibly slide over the
  floor. Locomotion/rest changes still crossfade briefly rather than snapping.
- House movement no longer falls back to a random patrol after arrival. A room
  target is accepted from a grounded CoreMind living-loop directive, completed
  once, then held until a later directive supplies a new target. This is an
  observable state-driven embodiment projection, not a claim of free will.
- V4 full-face mood morphs now have both mouth and eye component corrections.
  Speech visemes keep ownership of the mouth, while a small mood-specific eye
  contribution remains without leaving the eyelids held closed and defeating
  blinking.
- Verification: `npm.cmd run house:test:embodiment` passed (`13` tests) and
  `npm.cmd run house:build` passed. The live backend and Discord bridge were
  recycled so `/house-hq` serves the rebuilt asset bundle. The retained Vite
  chunk-size advisory is not a build failure.

## Codex Discord Hidden Deliberation (2026-07-14)

- Autonomous proactive and recursive Discord speech no longer uses one model
  call to decide and speak at once. The service-authenticated endpoint now runs
  a compact local-only decision pass with strict
  `{"speak": bool, "pick": 1..5}` output. Only a valid `speak=true` disposition
  reaches a separate local composition pass.
- The composition pass has a bounded public self-model: Alpecca speaks in first
  person as Alpecca, does not introduce herself as a generic/text-only
  assistant, and cannot claim literal consciousness, AGI, unsupported feelings,
  memories, actions, or capabilities. Normal Discord guest replies now share
  the same identity framing without gaining private creator continuity.
- Code rejects malformed/inconsistent decisions, generic assistant identity
  drafts, fallback/offline prose, meta-output, silence markers, and drafts over
  500 characters. Every releasable autonomous draft requires a content-free
  `discord_autonomy` CognitionObservation; audit failure resolves to silence.
- The bridge now sends bounded room state rather than embedding old one-pass
  generation instructions. Its reconnect continuity, voice-state grounding,
  duplicate suppression, and shared proactive/recursive lock remain in force.
- This is an implemented self-monitoring transaction, not evidence that Alpecca
  is already AGI or literally self-aware. General recursive self-improvement
  remains bounded to the separately governed behavioral-trial system.
- Verification: focused autonomy/Discord coverage passed (`73 passed` including
  the authenticated route); the broad Discord/Phase 10 selection passed (`310
  passed`); `tests/test_core.py` passed (`358 passed`); and House HQ built with
  only the retained chunk-size advisory.

## Codex Discord Self-Continuity Fix (2026-07-14)

- A reconnect now restores Alpecca's own recent Discord messages under the
  explicit `Alpecca` label while continuing to ignore other bots. A restored
  self-turn also resets the in-memory reply clock, so a bridge restart cannot
  immediately treat forgotten output as a reason to speak again.
- Direct, proactive, and recursive room prompts now distinguish Alpecca's own
  prior lines from human messages and tell the model not to re-greet, repeat a
  claim, or revive an unanswered topic without new human context.
- Proactive and recursive room speech share one lock. Their output is grounded
  against the authoritative live Discord voice state and deterministically
  suppressed only when it duplicates or closely restates Alpecca's recent
  autonomous output. A false `text-based AI cannot join voice` claim is now
  corrected even while disconnected; the correction says voice is enabled but
  does not falsely claim she is currently connected.
- Recursive follow-ups are now written back into the rolling room context and
  update the common reply clock. A pass or detected duplicate consumes that
  bounded continuation allowance until a human speaks again, preventing
  repeated model evaluations and resend loops.
- Verification: focused Discord tests passed (`62 passed`); the broader
  Discord/Phase 10 selection passed (`302 passed`); `tests/test_core.py` passed
  (`358 passed`); and `npm.cmd run house:build` passed with only the retained
  chunk-size advisory.

## Codex Discord Duplex Voice Baseline (2026-07-14)

- `ALPECCA_DISCORD_VOICE=1` now enables Discord voice-state intent and the
  existing claimed-room join/leave commands. The new independent
  `ALPECCA_DISCORD_VOICE_RECEIVE=1` switch enables bounded claimed-room receive;
  `START_HERE.bat` sets both for the normal full-stack launch.
- While connected, Alpecca speaks reactive, proactive, and the single bounded
  recursive text turn through the backend's local `/tts` route. Playback is
  serialized per guild, has a 16 MiB response cap, a server-aligned 105-second
  synthesis bound, and a 20-second busy bound, and always removes its temporary
  WAV. The join greeting runs asynchronously so a cold voice does not block
  Discord event handling.
- `requirements-discord.txt` declares the voice extras, DAVE encryption support,
  bundled FFmpeg provider, pinned `discord-ext-voice-recv` alpha, and local
  Faster-Whisper. `scripts/run_discord_bridge.py --voice-readiness` reports only
  content-free dependency status and reports `duplex` only when both directions
  are ready.
- Receive starts only from CreatorJD's allowlisted command in a claimed room,
  then keeps separate bounded PCM buffers for up to eight human participants.
  PCM is held in RAM, capped at 12 seconds per utterance, validated, queued two
  utterances deep, transcribed off the Discord event loop, and discarded. Each
  speaker remains guest authority through the signed actor path. Human speech
  interrupts current playback.
- Bounded voice transcripts and speaker identity are retained in a dedicated
  AES-256-GCM SQLite store. Its key is domain-derived from the bridge credential
  protected by Windows Credential Manager; only opaque room/speaker HMACs and
  content-free timing metadata remain outside ciphertext. Recent records restore
  room context after a bridge restart. Raw audio is never persisted.
- Every accepted/transcribed/remembered/dropped/failed transition writes a content-free
  cognition observation; if that audit is unavailable, transcription/model work
  fails closed. No audio or transcript is written to bridge logs.
- Discord.py 2.7 inbound DAVE is bridged locally before Opus decode because the
  pinned receive alpha predates DAVE. A corrupt/early frame is dropped without
  killing the listener. Signed, prefix-bound live voice state is now injected as
  server-validated ephemeral context and forces local guest inference; a final
  deterministic guard prevents connected Alpecca from claiming she is outside VC.
- Claimed-room participation now carries a soft social guideline around
  unsolicited evaluative feedback. Alpecca may ask whether feedback is wanted,
  answer directly when context warrants it, return one of four allowlisted
  reaction directives, or pass. The bridge turns a valid reaction directive into
  one Discord reaction and suppresses malformed directives; this is not a hard
  feedback-consent gate.
- Live mobile retry exposed one command-routing defect: the bridge computed a
  correct raw numeric bot mention but the later voice gate rechecked Python
  object identity, allowing `@Alpecca_ai join voice` to fall through to the
  model. The gate now reuses the numeric result, and the regression test uses a
  distinct mention object with the same Discord id. The bridge was restarted
  from this corrected source and reconnected in `duplex` mode.
- The persistent F5 worker now suppresses third-party `ref_text`/`gen_text`
  console chatter so synthesized Discord or House text does not enter worker
  logs; content-free worker errors and readiness remain visible.
- Previous output smoke: exactly one Discord bridge and one warmed F5 worker were running;
  the bridge connected to one guild, loaded one claimed room, and reported all
  voice dependencies ready. An authenticated bridge `/tts` probe returned a
  502,828-byte WAV in 5.62 seconds, and its redaction canary was absent from both
  worker logs.
- Verification: the full Discord/Phase 10/initiative selection passed (`305
  passed`); `python -m pytest -q tests/test_core.py` passed (`356 passed`); and
  `npm.cmd run house:build` passed with only the retained chunk-size advisory.
  Coverage includes the PCM collector, dependency posture, barge-in, full
  validate/audit/transcribe/sign/reply cleanup path, audit-unavailable denial,
  creator join wiring, and soft feedback/reaction behavior.
- Live smoke: exactly one backend, F5 worker, Discord bridge, and Ollama daemon
  are listening locally. The bridge connected to one guild, loaded one claimed
  room, and reported `mode=duplex` with receive dependencies ready. An
  authenticated `/tts` probe returned a valid 485,420-byte WAV in 7.64 seconds.
  A real CreatorJD Discord microphone packet/latency soak remains pending and
  must not be inferred from mocked PCM.
- `python -m pip check` still reports five pre-existing cross-feature dependency
  conflicts in cached-path/descript-audiotools/F5/fish-speech/x-transformers.
  The pinned Discord receive, Faster-Whisper, discord.py, DAVE, and FFmpeg
  packages are installed at their declared versions; do not treat the global
  environment as dependency-clean.

## Codex House Voice, Drive, Source, And Discord Recovery (2026-07-13)

- Discord guild activation now parses Discord's raw numeric mention protocol
  instead of relying on cached mention-object identity or presentation text.
  CreatorJD (`realcreatorjd`) can claim or release one channel with an exact
  `@Alpecca room on` / `room off` command line. Repeated identical command lines
  and mobile-composed surrounding lines are tolerated; conflicting actions fail
  closed. Registry writes roll back on failure, and a missing Discord send
  permission does not undo a successful durable claim.
- Claimed rooms now have a real quiet-room proactive loop. It uses bounded
  recent room context, quiet/cooldown/chance/model gates, one global in-flight
  decision, one rotated room per sweep, and exponential ignored-outreach
  backoff. Human activity or `room off` cancels an in-flight post, and an
  opener cannot feed the recursive continuation path into a monologue.
- House voice now has one bounded session coordinator. Direct replies and voice
  previews can interrupt stale speech, proactive speech queues without flooding,
  push-to-talk barges in, and listening/thinking/speaking/unavailable are visible.
  VRM mouth and attention timing follow real audio playback progress.
- Alpecca Systems > Files now presents a visual virtual drive and a separate
  read-only source workspace. Source listing/search is creator-only, no-store,
  metadata-only, root allowlisted, traversal/symlink/credential blocked, and
  cannot mutate source. Eligible selected text files reuse the existing exact
  `{root, rel}` lease-bound attachment path; content remains ephemeral.
- WebSocket timeout recovery now keeps a late worker counted as foreground work,
  and automatic Mindscape snapshots defer during active/recent chat. This keeps
  the socket usable for an immediate retry without disabling manual or shutdown
  continuity sync.
- Verification on this tree: `npm.cmd run house:build`; 34 focused Discord
  presence tests; the focused voice, drive, source-workspace, source-tool,
  attachment, and WebSocket-retry
  suites; six Void consolidation tests; and `python -m pytest -q
  tests/test_core.py` (`356 passed`).

## Codex Wave 1 Integration (2026-07-13)

- The six coordinator lanes were reviewed and integrated in dependency order.
  Commits `9501c27`, `4cb5099`, `24c9931`, `e1e6188`, `e255ddb`, `7e09bf7`,
  and `8881eff` are pushed to `origin/feat/vrm-preview`.
- Lane Q supplies grounded preference storage and an honest workload assessment;
  Lane O supplies creator-taught knowledge blocks and a brain-map; Lane C adds
  an acknowledgement-consumption monotonic anchor; Lane A adds per-tool-round
  context budgeting and cancellable page-tier maintenance; Lane I makes routine
  execution atomic with retry/backoff; Lane B adds the byte-bound perception
  consent gate.
- Commit `e655cf7` checkpoints the integrated Wave 0 work with the corresponding
  `server.py` / `mind.py` changes: creator-only no-store snapshots for knowledge,
  preferences, and workload; the push acknowledgement anchor; per-round tool
  budgeting; cancellable page maintenance; and durable routine claims.
- Remote perception remains **inert**. No server egress gate is constructed,
  so all current image, screen, webcam, and Discord vision remains
  verified-local. Do not activate the remote path without an interactive
  creator decision authority, operator-attested route values, and a production
  monotonic anchor in a separate failure domain.
- Verification: Phase 8 `302 passed`; Phase 6/9/12 `434 passed, 2 skipped`;
  Phase 9 after the consent integration `316 passed, 2 skipped`; foundation +
  Phase 11 `267 passed`; routines/resource `34 passed`; security/consolidation/
  RSI smoke `36 passed`; House HQ build passed. A full `pytest -q tests` run
  exceeded the runner's 120-second cap without an early failure, so it remains
  unconfirmed rather than green.

## Codex Lane K: House Slow-Turn Transaction (2026-07-13)

- House HQ now keeps one original request ID for a chat turn. It no longer aborts
  the HTTP request at 25 seconds and resends the same message over WebSocket.
  The 12-second and 35-second messages are nonterminal progress notices; a valid
  late reply still renders, while duplicate delivery for a completed request is
  ignored.
- Verification: `python -m pytest -q tests/test_core.py` (`355 passed`) and
  `npm.cmd run house:build` passed. The retained Vite chunk-size advisory is not
  a build failure. This is a frontend transaction fix; an end-to-end delayed
  backend soak remains useful before declaring the live latency issue closed.

## Codex Phase 7: Pagefile Broker Preparation (2026-07-13)

- Commit `eeda7a1` adds only a read-only prerequisite assessment for the future
  pagefile broker. The latest 8K measurement stopped at `host_assessment_high`,
  so the assessment reports `blocked`; even a structurally complete report only
  reports `review_required`. No UAC helper, approval consumer, command, or
  pagefile mutation path exists in this commit.
- A later isolated broker still needs a completed locally measured `qwen3.5:9b`
  8K run, explicit one-use `CreatorJD` approval, UAC, fresh host readback, a
  single +4,096 MiB bounded adjustment, and post-write verification. Do not
  describe the existing 38,000 MiB allocation as an autonomous Alpecca action.
- Verification: `python -m pytest -q tests/test_phase7_system_pressure.py
  tests/test_phase7_pagefile_broker_preparation.py` (`32 passed`) and
  `npm.cmd run house:build` passed.

## Codex Governed Learning Signal (2026-07-13)

- Commit `0a90cc6` adds a fail-closed, read-only projection of the existing
  Phase 8 trial lifecycle for cognition and the seven-role Soul. The serial
  integration adds a recovery-gated supplier to CoreMind: the Soul can observe
  a verified candidate, running trial, settlement, or creator review, but it
  receives no lifecycle controls and cannot approve, start, settle, retain, or
  revert any behavior value.
- Verification: governed-learning and Phase 8 focused tests passed, and
  `python -c "import server"` succeeds. The transition-observation adapter is
  available, but broad status polling is intentionally not treated as a new
  source of autonomous trial activity.

## Codex Resume Checkpoint: Local Model Honesty And Parallel Stage Review

This block is the newest operational handoff. Preserve the later shared-branch
commits `56106bb` (Codex vision handoff) and `7f491e6` (VRM blink/lip-sync
independence); they landed after the Phase 11 checkpoint and must not be reset.

- Commit `335a1e3` is pushed on `feat/vrm-preview`. It adds the reviewed Web
  Push connection-test slice, credential-backed monotonic outbox anchor,
  rollback-aware subscription state, reserve-before-ack recovery, cross-process
  first-use/send mutexes, verified-local computer screenshots, service-worker
  retry/origin/cache hardening, and fail-closed hoodie-collider reach checks.
  Verification for that exact tree was `1756 passed, 2 skipped`; House HQ built
  and `web/sw.js` passed `node --check`.
- The last live smoke ran locally at `http://127.0.0.1:8765/house-hq` with
  `ALPECCA_MODEL=qwen3.5:9b`, `ALPECCA_FAST_MODEL=qwen3.5:9b`, an 8K context,
  and chat cloud/ZeroGPU disabled for this smoke. Ollama reports the installed
  `qwen3.5:9b` (8.95B) resident at 8K. The server was stopped after the smoke
  for isolated verification. Do not reintroduce Qwen 3 8B.
- Live smoke exposed a false self-report: the model guessed
  `Llama-3.1-8B` while the inherited route was actually `gemma4:cloud`.
  Current uncommitted changes in `alpecca/mind.py` and `tests/test_core.py`
  force runtime-model questions to verified local inference, suppress streaming
  and tools for that status turn, label hosted Ollama calls `ollama-cloud`, and
  replace the draft with a code-grounded line from `llm.last_call()`. Three
  focused tests pass. A second live smoke now truthfully reports
  `qwen3.5:9b` through verified local Ollama.
- The second live smoke still showed a House timeout/fallback notice before the
  eventual correct 9B reply. Treat that as an open UX/runtime issue: do not send
  a duplicate request when the primary House channel is merely slow, and do not
  announce terminal failure before a still-running turn can commit.
- Discord media code exists, but the current plain `python server.py` launch has
  media disabled and no bridge process. More importantly, bridge debug logging
  defaults on and writes raw DM text/captions to disk. Before enabling the
  bridge, redact message content, default debug off, expose a secret-free media
  readiness result, and return fixed diagnostics for disabled/vision-unavailable
  paths. Keep guilds, cloud vision, tools, and durable guest history blocked.
- Mindpage is durable and bounded for the first request, but two high gaps are
  verified: tool-result follow-up rounds bypass the context ledger, and indexed
  buried facts can select a page while `fault_page()` returns only a prefix that
  omits the match. Fix per-tool-round budgeting first, then match-centered page
  excerpts. Pressure-to-Soul remains telemetry/urgency rather than a scoped
  consolidation action.
- Phase 12 now has dedicated invisible VRM 1.0 hem colliders in the injector:
  six three-centimetre spheres are hips-attached and overlap the six hem-chain
  roots without changing locked meshes, materials, textures, images, samplers,
  or `VRMC_vrm`. Strip/reinject idempotency and V4 output validation pass. The
  live V4 binary was deliberately not promoted; preserve its design lock until
  the remaining animation soak gate is complete.
- Ten distinct parallel review lanes were rotated through the runtime's smaller
  concurrency cap. Their verified gaps are recorded above and in the Phase 8
  work below; completed agents should be closed rather than left consuming a
  slot.
- Unrelated dirty work remains in
  `apps/house-hq/public/assets/alpecca-optimized/runtime_matrix_manifest.json`,
  `config.py`, `tests/test_stage1_security.py`, `.agents/`, `PROJECT.md`,
  `alpecca/creator_contact.py`, `explorer_phase2_audit/`, and the local PDF
  builder. Do not stage, revert, or absorb it without a separate decision.

### Phase 8 RSI Worktree Review: CONTRACT IMPLEMENTED, VERIFICATION BLOCKED

The current uncommitted work implements the intended bounded cycle for only
`creator-personal` / `chatter_chance`; it does not enable general self-editing.

- A candidate is fixed at two hours and five minimum samples. Issue,
  registration, controller registration, and start all reject a profile that
  cannot fit five optimistic opportunities under current chatter enablement,
  effective cooldown, and the shared initiative rate cap.
- The intervention now affects the real proactive path. CoreMind resolves the
  verified chance and draws one probability gate; the local model may veto or
  choose a grounded seed after that gate but cannot bypass or reroll it.
- Workshop keeps plan acceptance, registration, approval, start, running-trial
  abort, and the final profile choice as distinct creator-confirmed actions.
  Abort restores the preimage and records an idempotent `inconclusive` receipt.
  Frozen review shows the exact profile values, duration, and sample floor, and
  the baseline sentence uses the current profile epoch.
- Planned expiry restores the preimage before settlement. Settlement waits for
  all response windows, requires at least five completed samples, and uses a
  code-owned 10-point absolute rate threshold. Only `improved` evidence can make
  `Retain trial value` available; the creator may always choose `Keep baseline`.
- The final choice is HMAC-bound to the immutable trial and settlement and
  persists the active profile in SQLite without editing config or source. The
  controller reloads and re-verifies it on restart. Its decision timestamp
  starts a fresh baseline epoch, so later candidate issuance excludes old rows.
  Terminal response transitions run an idempotent successor reconciliation;
  manual review reaches the same issuer.
- The current all-Phase-8 selection is `282 passed, 4 failed`, with one existing
  Starlette/httpx deprecation warning. Three profile-decision route tests return
  `503` because `server.py` calls an undefined `_behavior_profile_generation`
  helper. One profile-store regression test references an undefined local
  `trial`. The durable contract is present, but this exact tree is not green.
- The last House build passed and its entrypoint is unchanged. A previous full
  core rerun passed after one transient order-sensitive grounding-card failure,
  but it predates the latest server/profile-test edits. Rerun Phase 8, core, and
  the House build against one stable tree after the two current defects are
  repaired. The accelerated temporary-SQLite retain/successor test is not a
  substitute for that acceptance run or for a real two-hour portal trial.

Master Plan Phase 8's bounded behavioral RSI completion contract is
**implemented but not currently acceptance-green**. Do not mark this worktree
complete until the four focused failures above are resolved and verification is
rerun. The inspected local database still has only two unanswered baseline
outcomes and no candidate, trial, override, rollback, settlement, profile
decision, or active retained profile, so no real cycle has run and it cannot
yet issue a candidate. After the tree is green, the next operational validation
is one real qualifying baseline and full two-hour lifecycle, exact rollback,
creator retain/revert decision, restart readback with no stale override, then
fresh-epoch evidence that produces the next candidate exactly once through
reconciliation. Exercise the House abort control separately as a live safety
drill.

Known limits: feasibility is a best-case upper bound and does not account for
random misses, model veto, ignored-outreach backoff, shared-budget competition,
creator activity, or portal loss. Five samples and a 10-point threshold are a
bounded product rule, not causal/statistical proof. Abort does not create a
planned-expiry settlement. Fresh epochs are timestamp-filtered, not explicit
epoch ids, and Phase 8 SQLite/HMAC state has no external monotonic anchor. The
legacy `review/retain-baseline` route is now a compatibility alias for the same
sealed baseline profile decision, not an acknowledgement-only branch.

The House slow-turn, Discord readiness, and Mindpage tool-round gaps remain
separate follow-on work.

## Current Active Handoff: Phase 9 Multimodal And Source Perception

This checkpoint supersedes the older active-scope and phase-status language
retained below as historical implementation evidence.

- Phase 9 is materially advanced but remains **PARTIAL**. Creator chat can now
  reach `source_inspect` through the smart tool gate; repository reads are
  read-only, explicitly rooted, creator-only, and require a verified loopback
  Ollama target with a non-cloud model. Image and push-to-talk ingress retain
  their strict pre-model byte/MIME/container/dimension/duration gates,
  server-derived SHA-256 provenance, exact turn/request scopes, metadata-only
  responses, and local-only/cloud-denied envelopes. Screen, camera, microphone,
  and voice enrollment uses are recorded through the capability audit path.
  House HQ auto-stops microphone capture at 60 seconds and cancels stale
  recording or transcription work on disconnect.
- Creator-only, server-resolved House text attachments are implemented. The
  client supplies only a bounded root id and relative path; the server
  resolves that reference against its allowed roots, records the file-access
  audit before reading, and binds locally derived MIME/SHA-256 provenance to the
  exact server-issued turn scope. The legacy raw/base64 `file_name`/`file_data`
  path is rejected, and the serialized attachment record contains provenance
  metadata rather than the ingested excerpt or raw bytes. The live file-derived
  answer is ephemeral: it cannot confirm/create commitments, enter recent-reply
  memory, persist as content-bearing history/cognition, reach Mindscape, or use
  the OpenClaw delivery bridge. Follow-ups must reattach the file.
- Server-issued capability leases now gate `camera_frame`, `screen_share`,
  `push_to_talk`, `voice_enrollment`, and resource-bound `file_source_ref`.
  Grants bind to the current creator portal, scope, surface, and purpose; file
  grants also bind the exact `{root, rel}` reference. Fixed TTL, use, and byte
  ceilings fail closed. Explicit stop, expiry, disconnect, portal replacement,
  and restart revoke active grants. Tokens remain client-memory-only and only
  HMACs plus uniquely sealed, content-free transition receipts persist. House
  HQ and the secondary classic app acquire grants before opening browser media
  devices; ordinary text chat remains lease-free.
- Discord transport authentication is partitioned from creator authority. The
  bridge uses a separate Credential Manager/deployment secret and a closed
  service header; `/channel/discord` rejects the creator bearer and enters
  CoreMind as `guest`. Image-bearing bridge requests use loopback even when
  text traffic is configured for a tunnel. The bridge now serializes each DM
  once, obtains a short-lived server-minted actor envelope bound to those exact
  bytes and Discord event/actor/channel IDs, then sends the unchanged body.
  `/channel/discord` consumes that envelope before perception or model work and
  derives a stable opaque guest scope without persisting raw Discord IDs.
- A hardened Phase 9 egress-consent ledger now exists in
  `alpecca/egress_consent.py`, but it is not live. Its frozen route policy binds
  provider, deployment, model, processing location, destination class, HTTPS
  route, one operation, keyed payload metadata, and byte count. It uses a
  separate monotonic anchor, automatic restart stop, exact sealed schema
  manifest, tokenless server consumption, content-free attempt evidence, and
  fixed-batch stale cleanup. Vision/provider calls, the interactive creator
  authority, API/UI controls, and ordered attempt reporting still need wiring.
- A hardened signed bridge-actor core now exists in
  `alpecca/bridge_actor_identity.py`. Its constructor fixes the service/platform
  boundary, policy, clock, keys, and external anchor; envelopes bind actual
  request bytes, Discord event ID, actor, guild, channel, and thread through
  keyed identifiers and can only produce a factory-validated guest result. It
  verifies exact schema objects, detects rollback/truncation, and supports the
  current bounded image JSON size. Its DM transport is now wired through
  `/channel/discord/actor-envelope` plus one-use consumption on
  `/channel/discord`. Missing, mismatched, replayed, or duplicate proof fails
  before CoreMind; redirects are rejected and loopback image requests bypass
  proxies. Guest history remains deliberately ephemeral.
- Creator-DM Discord images are now implemented through a dedicated authenticated
  `/channel/discord` route. The bridge accepts one PNG/JPEG/GIF under 2 MiB,
  sniffs MIME/dimensions from bytes before forwarding, records content-free
  ingress/egress observations, and no longer sends the retired raw document
  fields. Discord image vision is verified-local only; backend flags cannot
  authorize cloud egress. Explicit creator requests such as `!image
  portrait`, `!image base`, `!image reference`, or `!image gallery` attach one
  byte-validated image from a closed Alpecca-owned local catalog. No model text,
  Discord filename, URL, or user path can select an outbound file.
- Private image descriptions, microphone-derived text, source-tool turns,
  House file excerpts, retained private history, and paged private evidence
  force verified local inference. Discord images are also processed locally.
  File attachment context remains isolated as untrusted
  prompt data and suppresses tool schemas for that turn. A remote `OLLAMA_HOST`,
  HF primary backend, or cloud-tagged model receives no House/private sensor or
  source-file request. Normal non-private hosted-chat paths remain unchanged.
- Computer-use screenshots now use the same verified-loopback/non-cloud gate
  before client creation, capture, and every model call. An explicit local VCS
  selection also fails closed locally instead of falling through to a remote
  provider; that VCS experiment remains excluded from this Git checkout.
- Verification for this checkpoint: `1756 passed, 2 skipped` under `tests/`;
  the 198-test signed actor/Discord matrix is green; House embodiment tests are
  4/4; House HQ builds with only the existing large-chunk advisory. The two
  Python warnings are existing dependency/model warnings, not test failures.
- Phase 9 is not DONE: the provider/model-specific egress consent core is not
  wired into perception.
  Keep Phase 10 Discord participation/voice blocked.

- `/house-hq` now serves the **Void Prototype**, including a native categorized
  **Alpecca Systems** center and an orthographic view.
- The old `web/home.html` implementation is archived at
  `web/archive/house_hq_internal_legacy.html` and is no longer routed.
- Loopback access uses trusted-device bootstrap; remote access requires HTTPS
  creator trust. Remote trust establishes a protected Secure, HttpOnly session;
  plain LAN HTTP cannot enroll a creator device.
- Master Plan Phase 4 baseline is complete. The only commitment execution slice
  is creator-only, scope-bound, read-only `self_status`; successful closure is
  receipt-backed and replay-protected. Startup closes interrupted runs without
  rerunning, and the unscoped legacy proposal executor is retired.
- Master Plan Phase 5 baseline is complete. Proactive speech, living ticks, and
  routines share one per-scope relevance/cooldown/dedupe budget; unanswered
  outreach feeds backoff; one proactive event chooses one delivery surface; and
  eligible cue evidence changes the response strategy with traceable provenance.
- Master Plan Phase 8's bounded behavioral RSI contract is **IMPLEMENTED BUT
  NOT CURRENTLY ACCEPTANCE-GREEN**. The current worktree implements one bounded
  `creator-personal` / `chatter_chance` cycle. It now includes the fixed
  two-hour/five-sample profile, feasibility preflight, one real probability
  gate, separate Workshop plan/register/approve/start/abort choices,
  rollback-before-settlement, conservative outcome classification, a separate
  durable creator profile decision, and a fresh post-decision baseline epoch.
  The newest Phase 8 RSI block at the top of this file is authoritative for the
  completion contract, current database evidence, verification, and remaining
  limits. The older C1-C9 narrative below is historical implementation evidence.
- Master Plan Phase 6 Mindpage and resource coordination remains partial and
  active. Phase 6A rejects orthogonal and negative semantic matches. Phase 6B
  adds bounded sidecar Mindpage content-term indexing: new pages index after a
  durable commit, legacy pages support idempotent bounded backfill, and
  content-only retrieval selects candidates without inflating transcript blobs.
  Mindpage stats expose index coverage, errors, and capped pages. Legacy
  content-index backfill is now idle-scheduled through the optional `backfill`
  coordinator at a 300-second default interval. It remains silent and defers
  under chat, TTS, or other optional-work contention without losing its due
  state. Phase 6C refuses a fixed prompt overflow before it reaches the model,
  tools, streaming, history, or memory, and returns an honest structured
  response instead. Anti-repetition retries remeasure their expanded prompt and
  are skipped when it no longer fits. Phase 6D adds cooperative cancellation for
  embedding backfill, Mindpage content-index backfill, and routine embedding
  backfill: foreground chat or TTS cancels their leases, and workers stop at
  safe boundaries. `cancelled` and `cancel_requested` runs do not claim
  completion, advance scheduling, or broadcast maintenance activity. LLM calls,
  TTS synthesis, reflection, and SQLite `VACUUM` are not force-cancelled.
  Live-chat semantic recall remains disabled by default.
- Phase 6E adds a read-only `HostResourceSampler` and `GET /system/resources`.
  The shared snapshot reports host evidence and an advisory-only host-pressure
  assessment. This machine-level signal is distinct from Mindpage's per-request
  context pressure. Phase 6F consumes only fresh advisory host pressure to defer
  optional maintenance before a coordinator lease. Chat and TTS behavior are
  unchanged, and unknown or unavailable host data allows work. It performs no
  automatic context reduction, pagefile action, configuration change, or system
  action.
- Phase 6G projects the cached shared host assessment into the Soul snapshot as
  separate `host_pressure` evidence. The projection is assessment-only: it
  excludes raw host telemetry and advisory data, and unknown, invalid, or
  unavailable data remains `null`. It is observational only, making no LLM or
  system call and changing no seven-agent Soul deliberation, urgency, or action.
- Phase 6H adds an execute-only, read-only host preflight to the one-tier
  `scripts\measure_context_tier.py` harness. The default 8,192 dry run still
  uses no sampler and makes no request. On `--execute --tier N`, known high or
  critical host pressure, RAM/commit/disk headroom below fixed thresholds, or a
  low unplugged battery block the run before Ollama with zero HTTP requests.
  Unknown telemetry remains explicit and does not fabricate a block. `--all`
  remains rejected; reports never promote a tier or change configuration,
  pagefile, registry, system settings, or files.
- On 2026-07-10, a real-machine execute invocation was blocked by critical host
  pressure before any Ollama request. No real `qwen3.5:9b` inference or
  context-tier measurement completed, and no tier was promoted.
- Phase 6 remains partial. The next gated action is to clear resources and
  re-run preflight, then separately authorize one 8,192 measurement. Do not
  make a direct pagefile mutation as part of this work. Keep broader tools and
  action classes outside the Phase 4 baseline until separately approved and
  gated. See `docs/CONTEXT_TIER_MEASUREMENT.md` for the Phase 6E-6H boundary.

## Superseded Claude Code Handoff: Master Phase 4 onward (historical)

### User direction and entry point

Continue the **master architecture plan from Phase 4 onward**, not merely the
smaller agentic Stage 3 choice-point feature. `docs/ALPECCA_MASTER_PLAN.md` is
the full sequencing authority. Phase 3's turn transaction and context-isolation
gate passed on 2026-07-10; continue through Phases 4-14 in the order below.

The older agentic Stage 3 foundation already exists:
`alpecca/choice.py` provides strict local tiny-JSON choices; `alpecca/mind.py`
uses them for living questions, same-rank Soul ties, and proactive judgement;
`alpecca/soul.py` has compact hidden deliberation. Preserve those pieces, but
they do not substitute for actor isolation, commitments, approvals, or portal
ownership.

The Phase 2 prerequisite slice is now present: protected authorization derives
the creator principal, the Windows process singleton prevents a second live
CoreMind, and one active WebSocket portal epoch fences its predecessor. Broader
device/passkey pairing remains future hardening and is not a Phase 3 blocker.

### Phase 3: turn transactions and context isolation - DONE (2026-07-10)

Build immutable per-turn context with at least `turn_id`, `conversation_id`,
server-derived actor/principal, surface, privacy scope, cancellation token, and
commit state. Replace global `_speaker` and shared `_history` semantics in
`alpecca/mind.py`; requests must carry their own scoped history and memory view.

Persist enough scoped state to recover safely after restart. Partition chat
turns, short-term history, Mindpage pages/faults, memory retrieval, tool
availability, and outbound replies by scope. Route identity must come from the
protected server session/principal, never from a client `speaker`, `source`,
channel, or display-name field. A timeout/cancel must fence all late writes,
tool actions, broadcasts, and duplicate replies through a commit barrier.

Implemented evidence: immutable `TurnContext`, server-derived principal and
surface, scoped history/memory/Mindpage/tool access, commit barriers, stable
creator conversation ids, durable reconnect/restart recovery, and separate
House HQ routes (`/channel/house-hq`, `/ws/house-hq`). Portal epochs remain
transport fences rather than durable history identity. The latest compatible v1
creator history is promoted once to the v2 primary scope; guest contexts remain
ephemeral until a server-issued guest subject exists. Focused Phase 3 tests cover
scope isolation, timeout late-write rejection, stale epochs, and reconnects.

### Phase 4: cue, commitment, and action closure - IN PROGRESS

Add a structured cue envelope for corrections, confirmations, references,
urgency, distress, questions, and action intent. Add durable commitments and
tool receipts with `proposed -> approved -> running -> succeeded|failed|cancelled`.
Alpecca may only say an action is complete when a successful receipt exists;
otherwise she must state that it is proposed, pending approval, failed, or
unavailable. Make "yes, do it" resume the correct scoped pending commitment.

### Phase 5: unified initiative and grounded affect

Unify living-loop, proactive chat, routines, recursive follow-ups, and later
Discord participation behind one per-scope relevance, cooldown, and dedupe
budget. Feed the Phase 4 cue envelope into affect with evidence, confidence,
and timestamps. Maintain the seven symbolic Soul roles; do not create seven
LLM processes or inject verbose hidden reasoning into prompts.

### Phase 6: Mindpage and resource coordinator

Phase 6A semantic-negative/orthogonal recall abstention and Phase 6B bounded
sidecar content-term indexing are implemented and covered by focused tests. New
pages are indexed after durable commit; legacy pages support idempotent bounded
backfill; content-only search does not inflate transcript blobs; and Mindpage
stats expose index coverage, errors, and capped pages. Live-chat semantic recall
remains disabled by default.
Legacy content-index backfill is now idle-scheduled through the optional
`backfill` coordinator at a 300-second default interval. It stays silent and
defers under chat, TTS, or other optional-work contention without losing its
due state. Phase 6C now refuses a fixed request overflow before model, tool,
streaming, history, memory, or commitment work begins, returning an honest
structured response instead of a truncated request. Anti-repetition retries
remeasure their expanded prompt and are skipped when they no longer fit. Phase
6D adds cooperative cancellation for embedding backfill, Mindpage content-index
backfill, and routine embedding backfill. Foreground chat or TTS cancels their
leases; workers stop only at safe boundaries; and `cancelled` or
`cancel_requested` work is not recorded as completed, scheduled as successful,
or broadcast. Active LLM calls, TTS synthesis, reflection, and SQLite `VACUUM`
remain non-force-cancellable. Next, add bounded host-resource telemetry and a
context-tier measurement harness; do not mutate the pagefile in Phase 6.
Keep 8K as the initial measured context. Only promote Qwen 3.5 9B context after
real 16K/24K/32K/48K measurements stay below 90 percent commit, retain 2 GiB
physical-RAM headroom, and avoid sustained SSD paging. The 38,000 MiB pagefile
is commit reserve, not extra VRAM or a reason to oversubscribe the laptop.

### Phase 7: creator-approved pagefile broker - PARTIAL; READ-ONLY PLANNER COMPLETE

`alpecca/system_pressure.py` is now a read-only, command-free planning
foundation. It samples only Phase 6 commit/disk probes, preserves unknowns,
uses exact integer 20 percent headroom math, and can propose exactly one 4,096
MiB step from measured configuration evidence. The 55,296 MiB cap and projected
40 GiB system-disk floor are code-owned. From 38,000 MiB the only next proposal
is 42,096 MiB.

It has no command, pagefile write, persistence, approval consumer, elevation,
server route, scheduler, or UI. Execution remains blocked until a separate
minimal elevated helper performs fresh live remeasurement, consumes one
authenticated CreatorJD approval atomically, writes once, and verifies readback.

### Phase 8: bounded recursive self-improvement - ACCEPTANCE CURRENTLY BLOCKED

This historical section is superseded by **Phase 8 RSI Worktree Review** at the
top of this file. The current worktree has the bounded proposal-to-trial bridge,
creator lifecycle and abort routes, real chatter probability intervention,
planned-expiry settlement, durable retain/revert profile choice, and fresh
baseline epoch. The intended code contract is implemented, but the exact tree
has four focused Phase 8 failures described in the authoritative review above;
it is not verification-complete. A real two-hour lifecycle and
restart/next-candidate validation run is also pending. General `selfmod`, code,
files, accounts, shell, services, and operating-system changes remain outside
the implemented surface.

### Phase 9: multimodal and source perception

**PARTIAL as of 2026-07-12.** Scoped read-only repository browsing, strict
image/audio ingress, derived provenance, verified-local sensor inference,
capability-use audit records, bounded House microphone lifecycle, and
creator-only, server-resolved House text attachments are implemented. The
House attachment path
accepts only a server-resolved allowed-root id plus relative path, audits before
the read, derives MIME and SHA-256 locally, binds metadata to the exact turn
scope, forces local-only inference, and suppresses tools while the untrusted
file excerpt is in prompt context. The serialized attachment record contains
provenance metadata, not the excerpt or raw bytes. Legacy raw/base64
`file_name`/`file_data` input is retired. Existing source inspection and
image/audio behavior remain unchanged. File-derived answers are shown live but
stored only as a redacted omission marker; they cannot mutate commitments,
seed later tool-bearing turns, sync through Mindscape, or auto-deliver through
OpenClaw.

Server-issued expiring leases now gate camera frames, screen sharing,
push-to-talk, voice enrollment, and exact House file references. Leases bind to
the live portal and creator scope, enforce fixed use/byte/time ceilings, and
stop on explicit cancellation, expiry, disconnect, portal replacement, or
restart. Grant/deny/use/stop evidence is content-free and sealed; raw tokens,
connection ids, and file references are not persisted.

Focused tests cover malformed/oversized payloads, MIME/magic mismatch,
dimensions, duration, scope, provenance, creator authorization, audit-before-
read, local-only model routing, tool suppression, raw file-payload rejection,
derived-output non-retention, commitment blocking, and House/WebSocket
integration.

Still required: wire the exact provider/model egress consent broker into every
private perception provider attempt. Discord service authentication and signed
guest identity are now partitioned and wired for allowlisted DMs; do not mark
Phase 9 complete while provider consent remains unwired.

Generic vision is now verified-local by construction. `VISION_BACKEND`, a cloud
model tag, or the former Discord cloud flag cannot authorize image egress or
produce `creator-approved` metadata. Private Ollama-cloud and ZeroGPU helper
functions remain dormant for a future consent adapter. Do not wire one until the
provider can truthfully supply the exact deployment, model, processing location,
destination class, and HTTPS route required by `alpecca/egress_consent.py`.
Current Ollama-cloud-through-loopback and dynamically selected ZeroGPU routes do
not meet that contract. Art and Studio paths remain local; do not upload art to
Cloudflare.

### Phase 10: Discord presence and voice - PARTIAL; OUTPUT VOICE IMPLEMENTED

Reactive creator-DM text and bounded creator-DM image seeing/sending work.
The current non-creator CoreMind path is now a reply-only conversation boundary:
it uses a static prompt and deliberately retains no history even though signed
DM actor scopes now exist.
It exposes no tools, commitments, private continuity, state, location, model
telemetry, Mindpage, cognition, or initiative
mutation. Arbitrary caller image descriptions are ignored; a Discord image can
reach the guest model only through a server-created exact-turn envelope, and
that image-derived turn is not persisted. This is capability denial, not actor
authentication or Discord autonomy.
The bridge accepts allowlisted creator DMs and only those guild rooms explicitly
claimed by CreatorJD with the bot-mention `room on` command. Claimed rooms have
bounded recent context, participation, quiet-room proactive speech, and at most
one paced recursive continuation; unclaimed rooms still fail closed. Every
backend body remains labeled guest. The dedicated actor-identity seal credential
is separate from creator authorization, bridge service authentication, and the
bot token; no existing credential was changed or revoked.
Discord voice output and bounded claimed-room local receive are explicitly enabled by
the full launcher. Alpecca can join from a claimed room, speak text turns through
local TTS, locally transcribe bounded human utterances, retain only encrypted
transcript memory, and answer through the signed guest path. Persistent
cross-process rates, nonce-bound creator approvals, a real receive soak, and a
production external anchor remain unfinished.

### Phase 11: creator contact and notification outbox - PARTIAL; APP PUSH IMPLEMENTED

`alpecca/notification_outbox.py` provides the model-free durable core:
opaque payload references, closed category/adapter policy, idempotent enqueue,
quiet hours and quotas, atomic expiring claims, explicit indeterminate outcomes,
acknowledgement/cancellation state, externally anchored transition chains,
exact schema checks, and fixed-batch recovery. It intentionally has no adapter,
destination, credential, or network code inside the core itself.

The first separate adapter is now implemented for **explicit connection testing
only**.
Creator-authenticated House controls register/revoke one browser subscription
and can enqueue one fixed server-owned test template. The adapter claims through
the outbox, treats transport uncertainty as indeterminate, disables redirects
and environment proxies, and records provider acceptance separately from a
one-use event/subscription-bound click receipt. The service worker acknowledges
only when the creator clicks the notification. Subscription endpoints and keys,
VAPID material, outbox/store seals, and anchor state use dedicated Windows
Credential Manager targets; no existing creator, Discord, or bot credential was
changed or revoked. `pywebpush==2.3.0` is the optional open-source transport.
The subscription record and its monotonic anchor are distinct Credential Manager
records in the same failure domain; they detect record-only rollback, not
coordinated Credential Manager restoration. The service worker durably queues
click acknowledgements in IndexedDB and retries only on the same origin; House
refuses push enrollment when its backend is on a different origin. Browser
enrollment, one accepted-device test, and mobile soak remain manual acceptance
gates and have not been claimed complete.

Residual: acknowledgement-receipt consumption is sealed in SQLite but is not
monotonic-anchored. Restoring a valid pre-consumption receipt database can make
an already-acknowledged event return another idempotent success, but cannot
resend the notification or create another action.

There is no model, cognition, initiative, routine, watcher, or autonomous enqueue
path. Arbitrary message content, escalation, Discord DM delivery, SMS, and calls
remain absent. Add those only one adapter at a time after mobile soak and review.

Notification delivery now injects a canonical HMAC-sealed credential anchor
with a named cross-process mutex and compare-under-lock transitions. Its state
lives in Windows Credential Manager rather than beside the outbox SQLite
database. Bundled SQLite anchors remain development-only for the identity and
egress ledgers, whose production acceptance still requires anchors in separate
failure domains.

Do **not** import or checkpoint the current untracked
`alpecca/creator_contact.py`. Audit found that its direct Web Push/Discord/SMS/
OpenClaw sends bypass the outbox, accept caller-controlled routing and cooldown
bypass, expose caller reason to shared cognition/Mindscape, and lack restart-safe
idempotency or sender-bound acknowledgement. It remains inert and unimported;
the reviewed `web_push_adapter.py` path does not reuse it.

### Phase 12: V4 embodiment behavior and physics

**PARTIAL.** V4 now uses direct 1.70 m scaling, rejects VRMA translation tracks,
keeps finite one-shot/LookAround scheduling, closes all five vowels after speech,
compensates the measured V4 mood-mouth components without removing eye/brow
emotion, and uses bounded two-bone right-arm IK for terminal contact. Debug
telemetry exposes face/vowels, active/fading VRMA mode, root/hips, hand distance,
reachability, soles, and spring counts. Actual-model probes measured 1.70009 m,
40 valid mouth-correction bindings, near-zero reachable-hand error, 74 spring
joints, and 22 colliders. Keep Phase 12 open until the ten-minute physics soak,
all-terminal contact drill, per-clip sole measurements, hoodie collider check,
and four-angle design-lock turntable pass.

The hoodie injector now deterministically selects only an existing verified
hips/lower-spine collider group and fails closed on head/hair/accessory-only or
ambiguous exports. It also measures collider volumes against every hem-chain
root and requires a surface gap of at most 2.5 cm. The actual V4 fails this gate:
its selected spine collider surfaces are 5.6-8.9 cm from the roots. The live V4
binary remains untouched; add dedicated effective hem colliders before any
re-export/promotion or physics soak.

### Phase 13: cloud egress and Mindscape continuity - BLOCKED

Route all outbound inference through a data-classifying, allowlisted, audited
broker. Mindscape must fail closed and use separate credentials, signed/versioned
bounded snapshots, monotonic replay protection, CreatorJD-approved transactional
restore, and an expired local portal lease before any interactive cloud fallback.
Cloud is continuity standby, never a second CoreMind.

### Phase 14: release soak and living documentation

Run fresh-DB, concurrent actor, timeout, resource, Discord canary, Mindscape
failover, and V4 turntable/animation drills. Then rebuild/deploy the Cloudflare
shell and sync approved Hugging Face runtime assets. Update diagrams and status
claims only from evidence.

### Global constraints and verification

- Approved local model: `qwen3.5:9b`; do not revive, download, or reference
  the retired legacy model. If no approved fast model is installed, use Qwen 3.5 9B for smoke
  tests rather than downloading another model.
- No LLM call under `mind_lock`; no extra Alpecca instance; no autonomous code,
  account, delete, purchase, or general OS action.
- Do not revoke, rotate, delete, or alter existing keys/tokens or the preserved
  public Alpecca identity. It is not server authorization.
- Preserve `apps/house-hq/src/vrmEmbodiment.ts`, the unrelated dirty `config.py`,
  and untracked `alpecca/creator_contact.py` unless an active phase explicitly
  adopts them after its gate.
- Before every checkpoint run `python -m pytest -q tests\test_core.py` and
  `npm.cmd run house:build`. Current verified baseline: `tests/test_core.py`
  is green and the full suite reports `1756 passed, 2 skipped`; House HQ builds
  with only its existing large-chunk advisory.

### Current checkpoint

- Branch: `feat/vrm-preview`; save this handoff as its own narrow commit before
  Claude begins implementation.
- Stage 0 recovery baseline: `a79a6a3`; local authorization/capability work:
  `0eb1016`; compact Soul work: `bdbf8fc`; local tool/stream fallback fix:
  `afcbf07`; scoped cognition/V4 checkpoint: `cde2d91`.
- The legacy `data/access_token.txt` remains present and untouched.

Everything below this line is retained historical evidence. It may describe
superseded status labels or old active scopes; the Phase 3 onward roadmap above,
`PROJECT_CONTEXT.md`, and `docs/ALPECCA_MASTER_PLAN.md` control new work.

## Historical architecture checkpoint (2026-07-09)

- `docs/ALPECCA_MASTER_PLAN.md` and `docs/ALPECCA_MASTER_PLAN.pdf` are the
  dependency-ordered implementation plan produced from the AI-core, security,
  Mindpage/pagefile, Discord, Creator contact, and V4 embodiment audits.
- The corrected compute boundary is authoritative: the local laptop is
  approximately 24 GB DDR4 with an RTX 3050 Laptop GPU (4 GB VRAM). Any 34 GB
  memory or H100-class label belongs only to an observed/requested Hugging Face
  ZeroGPU or Google notebook runtime. Cloud allocations are ephemeral and are
  never counted as local or persistent Alpecca capacity.
- Current security hold: keep public tunnels and computer control disabled until
  Phase 1 passes. The existing Alpecca value appears in House HQ source/generated
  bundles because Jason considers it part of her public identity; preserve it and
  do not revoke or rotate it. The defect is that the server currently accepts that
  public value as bearer authorization and HTML navigation can bootstrap a
  privileged cookie. Phase 1 must separate public identity from a new protected
  authorization secret and fix the middleware before remote autonomy.
- Phase order is: containment -> authoritative CreatorJD identity + OS singleton
  + active-portal lease -> scoped turn transactions -> cue/commitment/action
  receipts -> unified initiative/grounded affect -> Mindpage/resource fixes ->
  approved pagefile broker -> bounded recursive improvement -> multimodal source
  perception -> Discord/contact -> V4 behavior -> Mindscape/cloud failover -> soak.
- `alpecca/creator_contact.py` and `alpecca/system_pressure.py` remain untracked
  WIP scaffolds. They are not live capabilities and must not be wired before the
  identity/approval gates. From the audited 38,000 MiB pagefile baseline, exact
  4 GiB steps are 42,096, 46,192, 50,288, and 54,384 MiB; current pressure did
  not justify an increase.
- V4 remains the live body with 74 spring joints and 22 colliders. Promotion
  still requires 170 cm scale correction, posed-boot sole grounding, stationary
  hips-track filtering, expression reset, one-shot gesture scheduling, collider
  tuning, and design-lock turntable QA.

---

## Mindpage adaptive paging checkpoint (2026-07-09)

- `alpecca/mindpage.py` now measures the actual formatted request instead of
  treating raw history length as total context pressure. It includes system
  prompt, current message, attached history, tool schemas, protocol allowance,
  and output reserve, with deterministic optional-context shrink order.
- Chat now performs bounded automatic pre-fault of relevant hot/warm pages and
  injects labeled summary/excerpt evidence. Explicit `recall_page` searches all
  tiers and is preserved inside the seven-tool cap for memory requests.
- History deletion is commit-safe: a failed page write retains all messages and
  exposes `paging_error` plus `unsummarized_eviction_backlog`.
- The same measured snapshot reaches the factual prompt block, Soul Snapshot,
  cognition state, chat/WebSocket reply, `/mindpage/stats`, and the House HQ
  Working Memory gauge. Reflector now relieves pressure by paging chat history;
  it no longer substitutes cognition-observation consolidation.
- Long-term memory recall now unions the 500-row salience/recency pool with FTS5
  lexical candidates. Malformed or mixed-dimension embeddings fall back to
  keywords. Embedding calls run outside the write transaction during backfill.
- Page faults promote to hot. `maintain_pages()` supports deterministic
  hot-to-warm and warm-to-cold demotion; `vacuum()` is explicit and never runs
  automatically. The disk limit is reported, not enforced through deletion.
- Focused Mindpage/recall tests and `npm.cmd run house:build` pass. The full suite
  must be run with `ALPECCA_CHAT_CLOUD_MODEL` unset because this machine's launcher
  exports `gemma4:cloud`, which makes fake-local `_LLM` tests call the live cloud
  client instead of their injected fake.
- `docs/MINDPAGE.md` is the canonical implemented/deferred boundary. Layer B
  llama.cpp slot persistence and Layer C OS pagefile/mmap deep-model work remain
  experimental and were not activated.

---

## Active handoff for next Claude session (2026-07-09)

- Scope is **VRoid base-model matching work** only; House HQ, core backend, and other app surfaces remain untouched.
- User requirement remains: **disable layers instead of deleting**.
- Current state:
  - The updated regular-outfit source remains `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v0.vroid` (9,650,830 bytes, saved 2026-07-09 12:19:40). It was preserved byte-for-byte as `alpecca_vroid_proxy_v0_updated_source_20260709_121940_preserved.vroid` before the base-view work.
  - The stripped inspection model is a separate file: `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v13_base_view_170cm.vroid` (9,603,521 bytes, modified 2026-07-09 17:13:10). It changed after the earlier 15:07 visual checkpoint, so reverify its visible layer state before relying on the older QA notes. Do not treat v13 as the regular-outfit source.
  - Blank/no-item presets are active in v13 for `Tops`, `Bottoms`, `Socks`, and `Shoes`; neck/accessory routes remain absent. `Inner Top` and `Inner Bottom` expose no blank preset, so the minimal required underlayers remain. No item or texture layer was deleted.
  - Base height was 170.2 cm / 5 ft 7 in when v13 was saved (`Fem Height=0.475`, `Masc Height=0.050`) with shoes disabled. VRoid displayed 170.3 cm after returning from Photo Booth with the same unchanged sliders; this is within the 170.2-170.4 cm gate and appears to be display/pose rounding.
  - Full-body editor QA was completed at front, left/right 3/4, side, back 3/4, and back. A persistent front A-pose capture is `data/alpecca_art_source/vrm_experiments/qa_lane/alpecca_v13_base_front_20260709.png`.
  - Adult/slim proportions, single ahoge, blue eyes, and pale blue lower hair color are present. The model is not design-complete: hair is shorter, straighter, and less layered than the locked references, and the left blue clip remains the simple-pin proxy rather than the required small X/bow accessory.
  - Lanyard/accessory routing:
    - Custom item fallback remains at `%USERPROFILE%\AppData\LocalLow\pixiv\VRoid Studio\custom_items\N00-NeckAccessory\2026-07-09-07-50-16-412.vroidcustomitem`.
    - Matching package is `data/alpecca_art_source/vrm_experiments/xwear/alpecca_neck_accessory_lanyard_fallback_20260709.xwear`.
  - BOOTH zip path is downloaded as `data/alpecca_art_source/vrm_experiments/accessory_workbench/booth_downloads/BWL_Group1000ThanksTicketHolder1.0.0Gift.zip` but encrypted (password-required).
  - Custom scratch lanyard source package lives at `data/alpecca_art_source/vrm_experiments/accessory_workbench/lanyard_3d/` (`.obj/.mtl/.glb` + textures/spec).
- Open items:
  - Improve v13 hair length, layered/wavy mass, and soft lavender-blue lower transition against `design_lock_references/01-turnaround-front-side-back.jpg` and `02-volumetric-angle-reference.jpg` without changing the preserved v0 source.
  - Replace the simple-pin proxy with a true small blue X/bow clip on Alpecca's left side through a compatible accessory/XWear route.
  - Add persisted side, back 3/4, and back QA captures after the hair/clip correction; the orbit was visually checked but only the front image is currently saved.
  - Keep using blank/no-item presets and separate source variants. Avoid delete, trash, or overwrite actions on the preserved regular-outfit source.
- Canonical references for continuation:
  - `PROJECT_CONTEXT.md`
  - `docs/ALPECCA_CURRENT_PROGRESS.md` (if still present/authoritative)
  - `HANDOFF.md` (this file)

---

## Cloud-interface refresh checkpoint (2026-07-09)

Scope: cloud/hosting surfaces, docs corrections, and bridge/tunnel bring-up. The
VRoid v13 work above remains the active handoff.

- The adaptive Mindpage changeset is committed and pushed as `a5084c3` on
  `feat/vrm-preview`: mindpage/mind/memory/prompts plus the House HQ Working
  Memory gauge. 347 tests green and `npm.cmd run house:build` green at commit
  time.
- Multi-subagent code-audit corrections were folded into
  `docs/ALPECCA_FEATURE_SKELETON_INFRASTRUCTURE.md` and the PDF was regenerated.
  Three of the five defects were already resolved by the Mindpage pass
  (tool-cap recall drop, adaptive pressure shrink, vacuum hook). Two remain
  open — the routines DELETE route and ngrok URL capture — and are being fixed
  in this session by parallel agents.
- The Cloudflare R2 static shell was re-packaged and re-uploaded: 6 objects,
  with all 304 art assets excluded per the no-art-on-Cloudflare rule. The new
  bundle `index-EI-cuJEZ.js` replaced the stale Jul-2 `index-Boi8Fodb.js`.
- Hugging Face runtime metadata was synced via
  `publish_alpecca_art_library_hf.py --runtime-metadata-only`; 136 files
  committed to `CREATORJD/alpecca-runtime-assets`.
- `config.py` cloud-model comments were corrected to match the approved
  launcher: `gemma4:cloud` for chat/deep/vision via `START_HERE.bat`, with
  `qwen3.5:9b` as the local fallback. No unapproved model substitutions.
- The Discord bridge was started and is online as `Alpecca_ai#0929` (1 server,
  `dm_allow=none`). A Cloudflare quick tunnel is being established via
  `scripts/share.py` for phone access.
- Still pending/user-gated: Mindscape Worker hosted deploy (wrangler secret +
  deploy + `ALPECCA_MINDSCAPE_URL` — explicit user go required), ZeroGPU brain
  space wiring (`ALPECCA_ZEROGPU_SPACE` unset by design), Colab T4 fast tier
  (`ALPECCA_COLAB_URL` unset), Stage 4 art generation (144 targets still
  seeded-awaiting-generation), and the VRoid v13 base-model work per the active
  handoff above.

---

Snapshot for whoever picks this up next (human or agent): current state, how to
run her, what was built, what's solid vs. shaky, and what's next. Read `CLAUDE.md`
for the canonical architecture, `docs/ALPECCA_CURRENT_PROGRESS.md` for the current
state and plan. (An earlier handoff is folded into the history below.)

---

## VRoid hoodie/lanyard cleanup checkpoint (2026-07-09)

Scope: active VRoid source only; House HQ and the 2D pipeline remain untouched.

- The active source `data/alpecca_art_source/vrm_experiments/alpecca_vroid_proxy_v0.vroid`
  was saved in VRoid Studio at 2026-07-09 06:36:47 local time (9,532,476 bytes).
- Hoodie artifact cleanup is now applied through the pass 05 clean overlay:
  `vroid_texture_layers/continuous_texture_lane/pass_05/alpecca_v10_hoodie_minimal_reference_matched_no_buttons_2048.png`.
  This removed the baked-in lanyard/buttons, dashed seam noise, and the stray lower
  blue open-front line from the hoodie texture.
- Jason clarified the white inner shirt is its own `Outfit > Inner Top` category.
  The lanyard/ID base layer was moved there with a pure no-choker overlay:
  `vroid_texture_layers/continuous_texture_lane/pass_06/alpecca_pass06_inner_top_lanyard_id_pure_no_choker_2048.png`.
  A second chest-high pure overlay was added so the lanyard reads higher in the
  hoodie opening:
  `vroid_texture_layers/continuous_texture_lane/pass_06/alpecca_pass06_inner_top_lanyard_id_chest_high_pure_no_choker_2048.png`.
  The older accidental `Neck Accessories` texture-edit dirty flag was explicitly
  left unchecked in VRoid save prompts so it was not overwritten.
- Front hair tips were restored with a softer lower-only overlay:
  `vroid_texture_layers/continuous_texture_lane/pass_06/alpecca_pass06_hair_lower_tips_only_soft_blue_1024x2048.png`.
  The too-strong full lower-gradient layer was hidden before saving the Front hair item.
- The current worn regular outfit state was exported through VRoid Studio's
  top-left `Bulk export worn items as XWear` path:
  `data/alpecca_art_source/vrm_experiments/xwear/alpecca_regular_outfit_lanyard_inner_top_20260709.xwear`
  (8,719,402 bytes, saved 2026-07-09 07:41:29). This is a full worn-outfit XWear
  package, not a lanyard-only XWear, because VRoid exports accessories via the
  bulk XWear route rather than individual accessory export.
- Jason clarified that the lanyard should be an accessory; VRoid Studio 2.14.0
  does not provide a native modern `Accessories` lanyard preset, and importing the
  existing lanyard custom item routes it back to `Outfit > Neck Accessories`.
  The fallback is now saved there as a custom neck/tie-section item:
  `%USERPROFILE%\AppData\LocalLow\pixiv\VRoid Studio\custom_items\N00-NeckAccessory\2026-07-09-07-50-16-412.vroidcustomitem`.
  The active source project was saved after that at 2026-07-09 07:50:33 local
  time (9,672,693 bytes).
- A corrected fallback XWear export from the worn `Outfit > Neck Accessories`
  state is saved at
  `data/alpecca_art_source/vrm_experiments/xwear/alpecca_neck_accessory_lanyard_fallback_20260709.xwear`
  (8,737,591 bytes, saved 2026-07-09 07:52:38). This remains a VRoid bulk worn
  item package, but the lanyard source item is now in the neck accessory/tie
  category rather than the inner shirt texture route.
- A separate custom 3D source model for the lanyard/badge was generated under
  `data/alpecca_art_source/vrm_experiments/accessory_workbench/lanyard_3d/`:
  `alpecca_lanyard_badge_source.obj`, `alpecca_lanyard_badge_source.mtl`, and
  `generate_lanyard_obj.py`. After the BOOTH ZIP password block, Jason chose the
  scratch-build route. The generator now outputs an upgraded no-collar/no-choker
  source package: preferred self-contained
  `alpecca_lanyard_badge_source.glb`, editable OBJ/MTL, external glTF/bin,
  `textures/alpecca_id_badge_1024.png`, and
  `alpecca_lanyard_badge_source.spec.json`. It includes a blue V-lanyard, strap
  highlights/shadows, gray hardware, lower blue tag tails, and a UV-mapped
  Alpecca ID badge face. Use the GLB as the active import source for the later
  true accessory/XWear Package build path; parent it to the VRM `Chest` bone and
  keep the badge slightly in front of the hoodie opening.
- Jason provided BOOTH item `https://booth.pm/en/items/8077106`. It was opened
  in Microsoft Edge while signed in and downloaded successfully to Downloads as
  `BWL_Group1000ThanksTicketHolder1.0.0Gift.zip` (76,129,588 bytes), then copied
  to
  `data/alpecca_art_source/vrm_experiments/accessory_workbench/booth_downloads/`.
  The archive is password-encrypted; listed contents include a Unity package,
  `FBX/Group1000Keychain_Charm.fbx`, `FBX/Group1000Keychain_NeckStrap.fbx`, and
  Blue/LightBlue texture PNGs, but extraction requires the password. The BOOTH
  page states the extraction password is distributed through the creator's VRChat
  group member-only post dated 2026-03-14 22:00. Do not bypass this; Jason needs
  to provide the password or retrieve it through the intended route.
- The rejected collar/choker body-skin texture remains off. Do not reintroduce a
  standalone collar/choker; keep the lanyard as a separate accessory only.
- Remaining model-fidelity gaps: the lanyard is now routed through
  `Outfit > Neck Accessories`, but it is still constrained by VRoid's neck/tie
  geometry and reads more tie-like than the reference. The separate OBJ source
  model should be used for the later true accessory/XWear Package build. The blue
  X/bow hair clip is still a proxy hair extra rather than a true modern
  `Accessories` custom item, and full front/side/back orbit QA still needs a
  manual VRoid camera pass.

## VCS texture/model-fidelity pass (2026-07-08)

Scope: experimental VRM/VCS appearance work only. House HQ and the canonical 2D
pipeline remain untouched.

- Extended `apps/vcs/frontend/src/lib/materialUtils.js` so the existing
  **Match to design** action applies more of Alpecca's locked design palette in
  the browser: hair gradient, ivory outfit tint, stocking cleanup,
  dark shorts, cream/blue boots, and blue clip/accessory/lanyard-style materials
  when material names allow safe targeting.
- Jason rejected the separate collar/choker texture as a design mismatch on
  2026-07-08. The active `alpecca_vroid_proxy_v0.vroid` body-skin top layer was
  deleted in VRoid Studio, the custom `Skin` item was overwritten, and the source
  project was saved. Do not reintroduce collar/choker tinting in VCS or VRoid.
- The blue hair clip should be kept as its own BOOTH/imported `Accessories`
  custom item/category. Do not route it through body skin, hoodie textures,
  animal ears, hats, or unrelated presets.
- Later on 2026-07-08, VRoid Studio was used to improve the active source
  `alpecca_vroid_proxy_v0.vroid` boots in place: `Overall Volume` 33.436,
  `Boot Volume` 57.753, `Toebox Width` 31.322, `Toebox Volume` 44.361,
  `Toebox Thickness` 28.855, and `Foot Thickness` 22.159. The source file was
  saved at 20:52:49 local time. The Accessories tab was verified as the correct
  route for the blue clip (`Import as Custom Item`), but the matching free
  BOOTH `.vroidcustomitem` candidates redirect to BOOTH sign-in for download.
- Jason then provided `Star_shape_hair_pin.rar` and
  `Simple_hair_pin_pink.rar`. Both are BOOTH `HairHanege` / VRoid `Extra`
  custom items, not modern `Accessories` items. The star pin import was rejected
  by VRoid Studio 2.14.0 as incompatible. The simple pin loaded through
  `Hairstyle > Extra > Custom`, was recolored at the material level to blue, and
  the active source `alpecca_vroid_proxy_v0.vroid` was saved at 21:07:39. This is
  a proxy clip route, not the final perfect left-side bone/bow accessory.
- Later on 2026-07-08 the active source was improved again in VRoid Studio and
  saved in place at 21:39:11 local time (`alpecca_vroid_proxy_v0.vroid`,
  8,927,423 bytes). The hoodie got a new top repair layer
  `alpecca_hoodie_ivory_details_v7_front_sleeve_corrections.png` over the v6
  layer: it covers the too-heavy front rails, redraws slimmer pale-blue zipper
  trim, moves the chest mark higher/smaller, rebuilds one clean black/blue tech
  patch per sleeve, and keeps the existing back/cuff/hem work. The hoodie shade
  color was changed from cool `#CFD6F7` to warm `#E8DED7` so the fabric reads
  cream/ivory instead of blue-gray.
- The active Body height was found at `167.6 cm`, which conflicted with Jason's
  5 ft 7 in requirement. It was corrected in VRoid Body controls to `170.2 cm`
  (`Fem Height=-0.058`) and saved. Current visible proportions still need
  front/side/back adult-read QA, but the scale target is now aligned.
- Multi-agent local workbench outputs were created under ignored `data/`:
  `vrm_experiments/accessory_workbench/` contains an OBJ/MTL/SVG/spec for a
  small glossy blue X/bone-bow hair clip proxy, and
  `vroid_texture_layers/candidates/` contains three alternate hoodie overlay
  candidates. These are not committed because `data/` is private/local source
  art, but `docs/ALPECCA_VROID_ACCESSORY_WORKBENCH.md` points to the workbench.
- Updated `apps/vcs/frontend/src/components/panels/MaterialsPanel.jsx` to call
  the broader matcher and report which material groups were affected.
- This is a reversible VCS preview/material-map pass. It does not mutate the
  `.vroid` source files directly; equivalent changes still need to be saved in
  VRoid Studio for a locked source checkpoint/export.

## VRM viewer framing + VCS port polish + launcher (2026-07-07, later session)

Scope: the **experimental VRM companion path** — both the in-app `/vrm` page
(`web/vrm.html`) and the ported **VCS studio** (`apps/vcs`, the clone of Jason's
Emergent VRoid Companion Studio at emergentagent.com). Nothing here touches the
2D/House HQ pipeline. NOTE: emergentagent.com is the SOURCE app being ported into
`apps/vcs` — it is NOT a deploy target; do not push there.

### `/vrm` page camera framing — FIXED + verified
Her VRM loaded zoomed onto her head. Two compounding causes, neither is
"feet at y=0":
- The export is **origin-centered** — feet ~-0.90, hips ~0, crown ~+0.74.
- A VRM's skinned-mesh `geometry.boundingBox` is a **phantom BIND-pose column**
  (~0→1.8 m), not where the bones actually render her; `Box3.setFromObject`/
  `expandByObject` read that phantom box and mis-frame her low + small.
Fix (`web/vrm.html` `frameCamera()`): sample the **posed skinned vertices**
(`applyBoneTransform` → world matrix → Box3) and run it on the **first rendered
frame** (skinning only settles after the skeleton updates once). Camera targets
the true center (y≈-0.08), distance fits her real ~1.65 m height. Verified via
headless Chrome CDP (SwiftShader WebGL): full-body, centered; orbit + zoom work
and zoom clamps (no clip-through). Shots: `data/screenshots/vrm_preview.png`
(882×1104) + `vrm_preview_mobile.jpg` (22 KB). Phone artifact:
https://claude.ai/code/artifact/799064ce-a3dd-4b54-befe-1ebf91cca45a
Lesson saved to memory as `vrm-framing-skinned-bounds`.

### VCS studio (`apps/vcs`) — port is COMPLETE + improved
Feature-audited against the emergentagent.com reference: all 20 animation
prefabs, all 4 tabs (Anim/Face/Pose/Mats), Runtime Behaviors, Procedural
Timeline are present. On top of the port this session:
- **Same framing fix** in `VRMViewer.jsx` `computeVRMBoundingBox()` — now samples
  posed skinned vertices (was reading the phantom bind box).
- **Foot grounding** — new `frontend/src/lib/vrmIK.js` (`snapGround` at load +
  per-frame `groundFeet`, easing back for airtime/Jump). Her soles sit exactly on
  the grid (verified toe-sole world-Y = 0.000); fixes the float-through-grid item.
  Wired in `VRMViewer.jsx` (snapGround before auto-frame, groundFeet after
  `vrm.update`). `state.groundBase` = resting offset, `groundOffset` = live.
- **Texture Lab "Bold" mode (ControlNet UV-lock) wired end-to-end** —
  backend `ai_service.py`: `_panel_edge_control()` builds the ControlNet control
  image from the atlas ALPHA (island outlines + threshold-gated interior seams;
  adaptive for opaque-vs-void atlases — avoids the beaded-mesh artifact from raw
  FIND_EDGES), `_zerogpu_texture_cn()` calls the Space's `/texture_cn`,
  `generate_material_texture(..., mode=)` routes restyle (low-denoise recolor) vs
  bold (high-denoise + edge lock). `routes.py` + `api.js` carry `mode`;
  `TextureLabDialog.jsx` has a Restyle/Bold header toggle threaded to both tabs.
  Route-tested live: bold 17s / IP-Adapter restyle 20s, alpha byte-preserved.
  Scripts: `scripts/test_route_bold.py`, `scripts/test_route_ipadapter.py`.
- **One-click launcher** — `RUN_VCS.bat` (repo root): starts backend :8001 +
  frontend :3200 in their own windows, opens http://localhost:3200 (Alpecca
  auto-loads). Paths verified. Was two hand-typed terminals (RUN_LOCAL.md).

### How to run / verify
`RUN_VCS.bat` (or the two commands in `apps/vcs/RUN_LOCAL.md`). Backend has 20
Alpecca VRM projects in Mongo; `StudioPage.jsx` auto-loads the newest on mount.
localhost is PC-only (phone can't reach :3200). All changes are in the working
tree (uncommitted); servers were reaped at session end.

---

## VCS (VRoid Companion Studio) — ZeroGPU texture pipeline + anim/texture upgrades (2026-07-07)

Scope: this whole session was the **experimental VRM companion tool** at `apps/vcs`
(the "VCS" port, backend :8001 + frontend :3200 + local MongoDB). Per CLAUDE.md the
VRM path must NOT replace 2D/House HQ — nothing here touches the main pipeline.

### The ZeroGPU pipeline (the infra everything else rides on)
All heavy AI for the VCS Texture Lab runs on Jason's **PRO ZeroGPU Space
`CREATORJD/alpecca-texture-lab`** (H200) — **Pony Diffusion V6 XL**
(`Bakanayatsu/Pony-Diffusion-V6-XL-for-Anime`) for images + **Qwen2.5-VL-7B** for
structured vision. This replaced the dead local-4GB path (times out >400s) and paid
HF Inference (402). Local ComfyUI + Ollama remain as fallbacks.
- Space source: `spaces/alpecca-texture-lab/app.py`. Redeploy via `scripts/deploy_texture_space.py` or `HfApi().upload_file(...)`. It's PRIVATE, on `zero-a10g`.
- Endpoints (gradio api_name): `/texture` (restyle img2img + IP-Adapter, 11 args), `/texture_cn` (ControlNet UV-lock, 11 args), `/vision_json` (outfit extract + anime guard).
- Backend calls it via `gradio_client` (`Client(space, token=HF_TOKEN)` — param is `token`, NOT hf_token). Routed by `AI_PROVIDER=zerogpu` in `apps/vcs/backend/.env` (+ `ZEROGPU_TEXTURE_SPACE`, `TEXTURE_RESTYLE_STRENGTH=0.32`, `TEXTURE_TINT_AMOUNT=0.7`, `ZEROGPU_IP_SCALE=0.6`).

### Texture render fix — the core bug ("UV grid rendered as the texture"). FIXED + verified.
Root cause: the generator was seeded with the **wireframe UV template** (or free-gen
character art), so it painted a grid / a character that then wrapped as garbage.
Fix = **restyle the material's ORIGINAL atlas in place**:
`generate_material_texture` → `_flatten_atlas_for_init` (shading-multiply palette
tint on the alpha region) → Pony **low-denoise img2img (0.32)** → `_reapply_alpha`
(re-composite the original alpha so the transparent UV void stays empty).
Frontend: `extractOriginalAtlas()` in `materialUtils.js` grabs `material.map` + its
`flipY`; `DressTab`/`MaterialTab` send `original_atlas_data_url`; `applyTexture`
re-applies with the original flipY. **Verified through the live route**
(`/api/generate/material_texture`): alpha byte-identical (397,528 px), every panel
held in its UV island, palette-accurate recolor. `scripts/test_restyle.py`,
`scripts/test_route_texture.py`.

### Animation upgrades (frontend, shipped, hot-reloaded, no console errors)
- **Cross-fade:** `VRMViewer.jsx` `vrmaUrl` effect now uses ONE persistent
  `AnimationMixer` + `crossFadeTo(0.45s)` (was: fresh mixer + `stopAllAction` = hard
  cut). Clips cached per-url. Mood transitions blend. Render loop still keys off
  `!!ref.vrmaMixer` (nulled only on vrmaUrl→null → procedural handoff).
- **Procedural gaze:** `vrmAnimations.js` `computeGaze()` (saccades + aversion);
  the lookAt branch uses it when the cursor's been idle >2.5s (eyes never freeze).
- **Auto-load + live driver:** `StudioPage.jsx` mount effect auto-loads the newest
  VRM project (nothing is persisted, so a refresh otherwise drops to empty) and
  enables `alpeccaLive` if `/api/alpecca/pose` is reachable. The live driver
  (VRMViewer 89–118) already maps her real mood→VRMA + expressions; pose data is
  REAL (mood/expressions/glow from her app on :8765).

### Texture upgrades from the OSS research (deployed to the Space + direct-tested)
- **IP-Adapter (SDXL)** — `h94/IP-Adapter/ip-adapter_sdxl.bin`, lazy + defensive.
  `/texture` now takes `ref_image_b64`+`ip_scale`; **FULLY threaded backend-side**
  (`_zerogpu_texture` → `_image_call` → `generate_material_texture` passes the
  garment ref as the IP image). Restyle now conditions fabric on the actual garment
  IMAGE, not just text. Compile-clean; needs a backend restart + in-app DressTab run
  to confirm the full flow.
- **ControlNet UV-lock** — `/texture_cn` (`xinsir/controlnet-canny-sdxl-1.0`,
  StableDiffusionXLControlNetImg2ImgPipeline, lazy + fallback to plain img2img).
  Direct-tested: **strength 0.75 held every panel** while painting bold new fabric
  (plain img2img scrambles at that strength). `scripts/test_controlnet.py`.
  ⚠️ NOT wired into the backend/UI yet — Space endpoint only. And the PIL
  `FIND_EDGES` control image is crude (beaded-mesh artifact) — feed clean
  **panel-edge control from the atlas alpha** instead.

### Current state / how to run (all servers were DOWN at handoff — reaped on session end)
- Backend: `cd apps/vcs/backend && ../.venv/Scripts/python.exe -m uvicorn server:app --host 127.0.0.1 --port 8001` (restart REQUIRED to pick up `.env` `AI_PROVIDER=zerogpu` + latest `ai_service.py`).
- Frontend: preview `vcs-frontend` in `.claude/launch.json`, or `npm --prefix apps/vcs/frontend start` (PORT=3200, `REACT_APP_BACKEND_URL=http://localhost:8001`).
- Live companion needs her app on **:8765** (mood/pose feed) — start via `scripts/run_full.py`.
- The Space stays live on HF independently.

### Solid vs. shaky
- **Solid:** texture render fix (route-verified); ZeroGPU pipeline (extract 22–37s, image 5–27s); animation crossfade+gaze (compile-clean); IP-Adapter (full chain) + ControlNet (Space) endpoints direct-tested; anime deviation guard.
- **Shaky / NEXT (in order):** (1) **wire ControlNet** into the backend (`_zerogpu_texture_cn`) + a "bold / structure-lock" mode in `generate_material_texture` + a UI toggle, and pass an **alpha-derived panel-edge** control image; (2) restart backend + verify IP-Adapter improves the in-app DressTab flow; (3) **foot-grounding IK** (analytic 2-bone, new `lib/vrmIK.js` — feet float through the grid today); (4) **lipsync BLOCKED** — `wawa-lipsync` is the pick but needs her TTS audio (or a speaking-level signal) piped into VCS; it plays only in her own app. Expand motion library later via `bvh2vrma` + `Kalidokit`.

### Key files touched
- `spaces/alpecca-texture-lab/app.py` (3 endpoints: texture / texture_cn / vision_json)
- `apps/vcs/backend/ai_service.py` (`_zerogpu_*`, `generate_material_texture`, `_flatten_atlas_for_init` tint, `_reapply_alpha`, `_hex_to_rgb`)
- `apps/vcs/backend/routes.py` (MaterialTextureRequest + `original_atlas_data_url`/`strength`)
- `apps/vcs/backend/.env` (zerogpu provider + tunables)
- `apps/vcs/frontend/src/lib/{materialUtils.js (extractOriginalAtlas), vrmAnimations.js (computeGaze), api.js}`
- `apps/vcs/frontend/src/components/VRMViewer.jsx` (crossfade + gaze)
- `apps/vcs/frontend/src/pages/StudioPage.jsx` (auto-load + live driver)
- `apps/vcs/frontend/src/components/dialogs/TextureLabDialog.jsx` (atlas wiring, ZeroGPU default provider)
- `scripts/test_{restyle,route_texture,controlnet,zerogpu,zerogpu2,zerogpu3,backend_flow}.py`, `scripts/deploy_texture_space.py`
- OSS research roadmap: workflow journal `subagents/workflows/wf_a00f92a6-85a/journal.jsonl` (8 findings: IK/mocap/lipsync/blending + ControlNet/IP-Adapter/PBR/projection). Ship-license flags: IDM-VTON / nvdiffrast / Ubisoft CHORD = non-commercial; DeepBump code GPL (load `.onnx` only).

---

## Post-review hardening + latency plan EXECUTED (2026-07-04)

Full plan in C:\Users\Jason\.claude\plans\serialized-booping-dream.md. Landed:

**Phase A — felt latency:**
- A1 voice warmup: `_warm_alpecca_voice` now ALWAYS warms Kokoro (the F5-healthy
  short-circuit left the calm-speech engine cold → 44s first line). Knobs:
  ALPECCA_VOICE_WARMUP=1, ALPECCA_VOICE_WARMUP_TIMEOUT=90. home.html pings
  /tts/warmup on page load.
- A2 streaming seam: alpecca/streaming.py (ThinkTagFilter — incremental
  strip_think across chunk boundaries), _LLM._chat_stream (stream=True,
  zero-token retry only, _StreamPartial after partial emission → echo fallback
  replaces draft), generate/chat take optional on_token (regen retries never
  stream; tools/HF/hybrid never stream). Kill switch ALPECCA_STREAM_CHAT.
- A3 WS protocol: client opts in per message ({"stream":true}) →
  reply_start / reply_token× / final authoritative {"type":"reply","streamed":true}.
  Greeting advertises features.stream_chat. Old clients (house-hq) untouched.
  home.html renders a .draft bubble replaced by the final text.
- A4 sentence TTS: home.html sentencesOf() (JS port of speech._sentences,
  pinned by test), SentenceSpeaker + ordered SpeechQueue — first sentence is
  SPOKEN while the rest generates; regen mismatch stops further speech.

**Phase B — persistence:** alpecca/db.py shared connect (busy_timeout=5000) —
all 8 module _connects delegate; WAL+synchronous=NORMAL applied in
state.init_db (harden()); rotating 7-day startup backup (scripts/run_full.py
_backup_soul → data/backups/); clamp-on-load in load_state; state_log pruned
to ALPECCA_STATE_LOG_KEEP_DAYS=30.

**Phase C — Stage 4:** conveyor script scripts/run_alpecca_stage4_conveyor.py
(process_returned_slice per frame → build_animation_library → house-hq assets;
audit by default, --apply for real). Contract fixes: CHARACTER_GROUNDING
("Full-body Alpecca anime woman") leads build_tile_prompt in the ZeroGPU space
(REDEPLOYED); resumable colab worker now runs returned-slice QA after every
upload batch. Nightly drip bat: scripts/run_stage4_nightly_drip.bat
(zerogpu_target → conveyor --apply) — Task Scheduler registration still needs
Jason to run: schtasks /Create /F /TN "Alpecca Stage4 Nightly Drip"
/TR "<repo>\scripts\run_stage4_nightly_drip.bat" /SC DAILY /ST 03:30

**FINAL VERIFICATION (2026-07-04):** suite 302 passed / 1 failed — the one
failure was world-tick under 3-way Ollama contention (two parallel pytest
sessions + live streaming probe, self-inflicted); it passes standalone twice.
All 5 previous baseline failures are FIXED. Live measurements on the running
app: streamed WS turn shows reply_start instantly, first token 10.7s warm
(prompt-eval bound on the 9B), draft==final, 100 tokens streamed; TTS after
warmup 1.3s (was 44.5s cold). data/backups/alpecca-20260704.db exists;
journal_mode=wal on the real save. Nightly drip task REGISTERED (03:30).
Doctor's one X is its own pre-existing false-negative (route probe sends no
token). STILL PENDING (auto-mode blocks production deploys, needs Jason to
run/approve directly): the two Mindscape commands in the section above.

**APP SUITE: launcher + private site + Discord invite (2026-07-04 night).**
One token-gated hub at **/app** (web/app.html, inline assets, no CDN):
- Windows: downloads a REAL packaged **AlpeccaLauncher.exe** (built, 10 MB,
  apps/launcher/dist; rebuild via apps/launcher/build_exe.bat) or the source
  zip (/app/download/launcher.zip streams apps/launcher/src on demand). The
  launcher (tkinter, stdlib-only): status dot polling /system/status, Wake
  her / Open her home / App site / Phone access (share.py) / Invite to
  Discord / Put her to sleep. Works frozen or from source (repo-root walk).
- Android/iPhone: PWA install cards + QR of her tokened URL (works on LAN
  via scripts/share.py, anywhere via --tunnel).
- Discord: GET /app/discord/invite 302s to discord.com OAuth (client_id
  derived from the bot token's first base64 segment; override
  ALPECCA_DISCORD_CLIENT_ID in config.py; permissions=3263552).
- /app/meta reports {exe_built, lan_ip, port, discord_ready}.
- PASSWORD LOCK = the EXISTING auth gate, untouched: APIs/downloads hard-401
  without the token; HTML navigations seed the cookie BY DESIGN (gate's own
  documented behavior — and the TestClient host is whitelisted, so the lock
  test asserts on server._token_ok directly). 5 contract tests green
  (app_site/app_meta/discord_invite/launcher_zip). All routes live-verified:
  /app 200, meta true-values, invite 302 w/ client_id 1522307155254837278,
  zip 7KB w/ sources, exe 200 MZ 10MB.

**CHAT MOVED TO gemma4:cloud (2026-07-04 late — JASON'S PICK, supersedes the
ZeroGPU-chat entry below).** He asked for an Ollama-cloud model that's
efficient and advanced enough to replace the ZeroGPU chat system; options
were presented by name and he chose gemma4:cloud (the same model he already
picked for deep+vision). Now ONE always-warm cloud brain serves chat + deep
+ vision; local qwen3.5:9b is the net everywhere. Implementation: the
existing hybrid path (CHAT_CLOUD_MODEL) — just set
ALPECCA_CHAT_CLOUD_MODEL=gemma4:cloud, ALPECCA_CHAT_ZEROGPU=0 (bat + setx).
Verified live in-app: 8.1s first turn, then 3.3s / 3.3s full turns, recall
works, telemetry "gemma4:cloud". think=false verified clean. The ZeroGPU
9B chat path (below) STAYS BUILT as the switchback: ALPECCA_CHAT_ZEROGPU=1
+ CHAT_CLOUD_MODEL= empty.

**CLOUD-FIRST 9B CHAT via ZeroGPU (2026-07-04 night — superseded same night,
kept as the alternate path).** The ZeroGPU Space now runs the EXACT same
Qwen/Qwen3.5-9B as her local brain (spaces app.py MODEL_ID swap; AutoProcessor
+ AutoModelForImageTextToText load path for the qwen3_5 multimodal arch;
transformers>=4.57; enable_thinking=False in the chat template; REDEPLOYED).
Her chat tier tries the Space FIRST (mind.generate zerogpu-chat block,
ALPECCA_CHAT_ZEROGPU=1, 30s bound): warm cloud replies ~2s generation /
~8s full mind turn (vs ~30s local); if the Space is asleep the LOCAL 9B
answers that turn while the abandoned attempt wakes it — she never goes
quiet, and it's the same model either way. Telemetry:
last_call backend "zerogpu", model "qwen3.5-9b@CREATORJD/alpecca-zerogpu".
Measured live in-app: 17.4s (wake-ish) then 8.2s. Costs HF ZeroGPU quota
per reply; kill switch ALPECCA_CHAT_ZEROGPU=0 → all-local. Cloud-served
turns don't token-stream (whole reply arrives fast); local turns still do.

**Slow-turn incident + fixes (2026-07-04 evening).** Jason hit >60s turns +
the "grounded live mode" timeout line. Chain of causes: (1) a restart race
spawned a DUPLICATE F5 voice worker (~800 MB CUDA) — fixed live (killed
orphan) and permanently (_f5_worker_port_taken() in run_full.py: never spawn
if ANYTHING listens on the port, healthy or warming); (2) with VRAM starved,
Ollama placed the 9B at 0% GPU (all-CPU) — fixed persistently with
OLLAMA_FLASH_ATTENTION=1 + OLLAMA_KV_CACHE_TYPE=q8_0 (user env; halves KV,
auto-placer restored the usual 18% GPU). NOTE: forcing num_gpu on the 9B
WEDGES Ollama 0.30.7 outright (240s hang) — do not pin, leave auto;
(3) the 24-message history doubled CPU prompt-eval — now
ALPECCA_HISTORY_MESSAGES=12 (still 2x the original 6);
(4) turn budgets: ALPECCA_OLLAMA_TIMEOUT=105, WS window 120s — the canned
fallback should now be effectively unreachable. Verified after: warm streamed
turn ~30s total, first token ~12s, no fallback, 9B at 18% GPU.

**Phase D — debt:** world-tick test polls for background persistence (race
fixed); REAL grounding bug fixed in mind.py — the embodied-location line was
LAST in `inner` and the 160-char compact cap truncated it away whenever a
musing existed (she'd mis-report her room); it now goes FIRST. Volume-QA test
fixture now draws a connected character silhouette (head/neck/torso/legs) —
the mechanical probe rightly rejected solid rectangles. All 3 Stage 4 contract
tests green. Mindscape worker deploy STILL pending (auto-mode blocks
production deploys): cd deploy/mindscape-worker && npx wrangler deploy, then
npx wrangler secret put MINDSCAPE_TOKEN, then setx ALPECCA_MINDSCAPE_URL/TOKEN.

## Ollama Pro: cloud deep tier + cloud sight (2026-07-03)

Jason purchased **Ollama Pro** and the machine is signed in (`ollama signin`),
which unlocks Ollama's hosted cloud models through the SAME local API
(`localhost:11434`) — no new transport, no local VRAM, no ZeroGPU queue/quota.

- **New deep backend `ALPECCA_DEEP_BACKEND=ollama-cloud`** (set in
  START_HERE.bat): deep self-acts run on **`gpt-oss:120b-cloud`** — chosen for
  LOW USAGE DRAIN after Jason flagged quota burn (reflection fires several
  times/hour idle). gpt-oss deliberates concisely (~400 chars) and answers
  within budget (no salvage call): a reflection is ~500 tokens in 3.5s, vs
  ~4,500 tokens in 28s on qwen3.5:397b-cloud. `_build_deep` returns
  `("ollama-cloud", model)`; `_generate_deep` routes through
  `_generate_local_thinking` (takes model/num_predict params),
  `ALPECCA_CLOUD_REFLECT_NUM_PREDICT=2500` cap. Knobs: gpt-oss:20b-cloud
  (cheapest) / qwen3.5:397b-cloud (richest) via ALPECCA_OLLAMA_CLOUD_MODEL.
- **Vision auto-routing is now ollama-cloud → zerogpu → local**
  (alpecca/vision.py `_describe_ollama_cloud`). `ALPECCA_VISION_CLOUD_MODEL`
  defaults to qwen3.5:397b-cloud (the ONLY vision-capable cloud model; NOT
  tied to the deep model). Cloud sight serves only explicit image turns —
  **ambient senses (screen glimpses, webcam) are hard-forced local via
  `describe_image(..., ambient=True)`** so background loops can never drain
  metered usage and screen/face pixels never leave the machine. Set
  ALPECCA_VISION_CLOUD_MODEL="" to keep all vision off the metered cloud.
  Verified: `describe_and_recognize` on her avatar = 23.5s, "SELF: yes".
- Fallback chain if signed out/offline: ollama-cloud deep raises → local
  thinking pass → plain local. Chat stays 100% local (privacy line intact:
  deep prompts carry no sensed screen context, unchanged).
- Other cloud models available on the account: deepseek-v3.1:671b-cloud
  (thinking), gpt-oss:120b/20b-cloud (thinking), qwen3-coder:480b-cloud.
- **Final division of labor (Jason's architecture, 2026-07-03): all-local
  qwen3.5 family, near-zero metered usage.**
  - chat → `qwen3.5:4b` (ALPECCA_MODEL): fast, fits VRAM alongside F5.
  - deep reflection → `qwen3.5:9b` (ALPECCA_DEEP_BACKEND=local +
    ALPECCA_REFLECT_MODEL=qwen3.5:9b, new config knob wired through
    `_generate_local_thinking`): think-first musings ~2-5 min, idle work.
  - vision → `qwen3.5:9b` (ALPECCA_VISION_BACKEND=local +
    ALPECCA_VISION_MODEL=qwen3.5:9b — the 9B GGUF has a built-in 456M CLIP
    encoder): ~2.5 min/image on CPU, pixels never leave the PC.
  - `ALPECCA_OLLAMA_TIMEOUT=60` (default 18s cuts long replies under
    co-load → echo fallback).
  - Ollama Pro cloud remains one env flip away: DEEP_BACKEND=ollama-cloud
    (gpt-oss:120b, 3.5s/reflection) / VISION_BACKEND=auto (qwen3.5:397b,
    ~23s/image, metered).
  - **Voice canNOT run on Ollama** — Ollama serves text/vision models only,
    no audio-synthesis endpoint. Her voice stays Kokoro (local CPU) + F5
    (local CUDA), which is already fully local and how Jason likes it.

- **Fallback-line outage + fixes (2026-07-03 late).** She was stuck on "my
  deeper language core is offline" in the home app. TWO causes found:
  (1) the Ollama daemon had silently died AGAIN (repeat offender) — and it
  is now a single point of failure since local AND cloud models route
  through it. Fix: `_ollama_watchdog()` in scripts/run_full.py pings
  /api/version every 60s and respawns `ollama serve` detached if dead.
  (2) The launcher's old option [1] "HF cloud brain (recommended)" routes
  ALL turns to HF InferenceClient with setx model Qwen3-Next-80B which HF
  providers don't serve → permanent fallback. Fix: menu rewritten — [1] is
  now the hybrid stack (Enter default), [2] fully-offline; the HF
  InferenceClient path is env-only (ALPECCA_LLM_BACKEND=hf) and setx
  ALPECCA_HF_MODEL corrected to Qwen/Qwen2.5-7B-Instruct. ALSO: stale setx
  stale user-env model settings synced to the current
  architecture so out-of-bat launches match the bat. ALSO: gpt-oss cloud
  chat could return EMPTY content (its internal reasoning eats num_predict
  under her big system prompt) — cloud calls now get num_predict>=512 and
  an empty cloud reply raises → falls to local, never ships "" to a person.
  Verified live end-to-end: 3-4.6s cloud replies in the app, turn-2 recall
  works, telemetry truthful.
- **FINAL brain config (2026-07-03, latest — supersedes hybrid-chat entry
  below): gpt-oss is OUT.** Jason never approved it; I had substituted it
  twice. Now: **qwen3.5:9b is her ONE brain** — chat + deep reflection +
  vision, all local (ALPECCA_MODEL=qwen3.5:9b); qwen3.5:4b only serves the
  cheap idle-chatter tier (ALPECCA_FAST_MODEL). ALPECCA_CHAT_CLOUD_MODEL is
  EMPTY (hybrid off; the knob remains for a model Jason picks himself —
  only qwen3.5 cloud tag is qwen3.5:397b-cloud). START_HERE.bat menu
  removed (one brain path, Enter to wake). Related fix: server.py's
  hardcoded WS_CHAT_REPLY_TIMEOUT_SECONDS=30 made the app give up before
  the 9B finished (~25-40s) and serve the canned "deeper model taking too
  long" line — now max(45, ALPECCA_OLLAMA_TIMEOUT+15)=75s, override
  ALPECCA_WS_CHAT_TIMEOUT (`import os` was added to server.py for this).
  Verified live in the home app WS path: 17.5s/19s turns on qwen3.5:9b,
  grounded replies + turn recall. DO NOT swap models without Jason's
  explicit approval.
- **gemma4:cloud for deep+vision (2026-07-04, JASON'S EXPLICIT NAMED PICK —
  latest state).** He asked "what about gemma4"; probing found
  `gemma4:cloud` on his Ollama plan: 33B BF16, 256K ctx, thinking + tools +
  vision — ~12x lighter usage than the rejected 397B. He chose it by name
  for the cloud deep+vision link. Config now:
  DEEP_BACKEND=ollama-cloud + OLLAMA_CLOUD_MODEL=gemma4:cloud (local 9B
  thinking = net), VISION_BACKEND=auto + VISION_CLOUD_MODEL=gemma4:cloud
  (→ ZeroGPU Space → local 9B). Chat stays local qwen3.5:9b; chatter
  qwen3.5:4b; ambient senses hard-local. Verified: deep 4.4s with
  1,275-char think chain; vision+self-recognition 3.1s through
  describe_and_recognize. (His local gemma4-e4b is actually a gemma3n
  6.9B text-only build — unused now.)
- **397B REMOVED — all-local 9B interlude (2026-07-04, superseded the
  chained-cloud entry below; deep+vision then moved to gemma4:cloud, above).** Jason challenged qwen3.5:397b-cloud too
  ("why you keep using this?") — the "both, chained" answer approved a
  routing shape, not that model; treating it as model approval was a
  mistake. Facts: Ollama cloud hosts NO qwen3.5:9b (only 397B; the
  ollama.com/library/qwen3.5:9b page he linked is the LOCAL tag). Current
  state: chat + deep + vision ALL on local qwen3.5:9b, 4b = chatter tier,
  every cloud model env EMPTY (config defaults too). The official
  `qwen3.5:9b` library tag was pulled but MISBEHAVES on Ollama 0.30.7
  (16 GB alloc despite num_ctx=8192, 0% GPU, wedged loads) — it's parked
  as `qwen3.5:9b-official`; the name `qwen3.5:9b` was re-aliased to the
  proven lmstudio-community GGUF (same weights). Retry the official tag
  after an Ollama upgrade. Only remaining cloud path that serves HIS model:
  ZeroGPU Space running Qwen/Qwen3.5-9B (exists on HF, multimodal,
  needs transformers>=4.57 + Space rebuild) — NOT built, needs his go.
  Verified in-app: 30.5s turn (cold), served by qwen3.5:9b, grounded.
- **Cloud offload, CHAINED (2026-07-04, Jason chose "both, chained" —
  SUPERSEDED same day, see above).**
  Deep reflection + vision now try the cloud first and degrade gracefully:
  **qwen3.5:397b-cloud on Ollama → his ZeroGPU Space → local qwen3.5:9b.**
  Chat stays 100% local on the 9B. Implementation: DEEP_BACKEND accepts a
  comma-chain ("ollama-cloud,zerogpu") — mind._build_deep builds
  self._deep_chain, generate() walks it, local thinking pass stays the
  final net; vision was already chained via VISION_BACKEND=auto. Jason
  explicitly approved qwen3.5:397b-cloud here (config default changed;
  earlier "frugal default" note is superseded). Verified: link 1 serves in
  ~35s with a 10k-char thinking chain; forced link-1 failure correctly
  falls through. Two hardening fixes from that test: (1) config's
  _gradio_api_name() undoes Git-Bash mangling of "/chat" api names;
  (2) when the deep chain exhausts, the plain net now runs on
  REFLECT_MODEL/local — it used to re-dial the cloud model name.
  Env synced (bat + setx): ALPECCA_DEEP_BACKEND=ollama-cloud,zerogpu,
  ALPECCA_OLLAMA_CLOUD_MODEL=qwen3.5:397b-cloud, ALPECCA_VISION_BACKEND=auto.
- **Mindscape Cloudflare worker: still NOT deployed** (wrangler IS
  authenticated on this machine; deploy blocked pending Jason's explicit
  go: `cd deploy/mindscape-worker && npx wrangler deploy`, then
  `npx wrangler secret put MINDSCAPE_TOKEN`, then setx
  ALPECCA_MINDSCAPE_URL + ALPECCA_MINDSCAPE_TOKEN).

- **Hybrid chat + real conversational memory (2026-07-03, Jason's ask:
  "context too low / reduce wait / hybrid").** Two root causes fixed:
  - Her forgetfulness was NOT num_ctx — chat only sent `_history[-6:]` (3
    exchanges). Now `ALPECCA_HISTORY_MESSAGES` (default 24, set in bat)
    rides along on every turn, and the raw `_history` list is bounded at 4x.
    Verified: recalls a fact stated 22 messages back.
  - `ALPECCA_CHAT_CLOUD_MODEL=gpt-oss:120b-cloud` (bat) turns on hybrid
    chat in `_chat`: reasoning-tier turns try the cloud model FIRST
    (~1.7-3.5s replies, `ALPECCA_CLOUD_NUM_CTX=32768`) via a dedicated
    20s-timeout client; ANY failure falls through to local qwen3.5:4b
    (verified with a 404 model: logs "cloud chat unavailable -> local" and
    answers locally). Fast-tier/chatter and explicit-model calls never
    touch the cloud. `llm.last_chat_model` keeps last_call telemetry
    truthful about who actually served. Empty CHAT_CLOUD_MODEL = 100%
    local chat again. NOTE: with hybrid on, chat text (not senses) leaves
    the machine — Jason explicitly requested this trade for speed.

---

## Local brain + reflection-tier thinking (2026-07-02)

**New local chat brain: `qwen3.5:4b`** (Qwen3.5-4B Q4_K_M, pulled from
`hf.co/lmstudio-community/Qwen3.5-4B-GGUF:Q4_K_M`, aliased `qwen3.5:4b`).
Set via `ALPECCA_MODEL=qwen3.5:4b` in `START_HERE.bat`. Newer arch than
a retired older local model, ~2.7 GB — fits the 4 GB RTX 3050 (45 tok/s when the card is free,
~11 tok/s under auto placement alongside F5/vision). `/api/chat` with
`think=false` (mind.py's path) yields clean no-think replies; the inline
`<think>` leakage only happens on raw `/api/generate`. **F5/Kokoro voice
config untouched** — user likes the voice as-is; do not move F5 off `cuda`.
`ALPECCA_NUM_GPU` knob exists (config.py `OLLAMA_NUM_GPU` → `_chat` options)
to force full-GPU placement, default OFF to protect F5's VRAM slice.

**Reflection-tier thinking (plan item 2) is DONE.** Her deep self-acts
(reflect, recursive self-question, choreography/sheet authorship — every
`tier="deep"` caller) now run a real chain-of-thought pass when they land
locally: `_LLM._generate_local_thinking` in `alpecca/mind.py` calls Ollama
`think=True` (private reasoning returned in the separate `thinking` field),
budget `ALPECCA_REFLECT_NUM_PREDICT=1600`, own slow client
(`ALPECCA_REFLECT_TIMEOUT=600`s — reflection is idle work, nobody waits).
Order: cloud deep tier (ZeroGPU) first → local think pass → plain local.
qwen3.5:4b deliberates LONG (7k+ chars) and can exhaust the budget before
answering — the salvage pass hands her own chain back and asks for just the
conclusion (no-think, short), so the musing still comes from real
deliberation. Verified live: 296s, 7,789-char private chain → grounded
3-sentence musing. Observability: `last_call.used_tier == "reason-think"`,
`llm.last_thinking`, console line in `reflect()`. Kill switch:
`ALPECCA_REFLECT_THINK=0`. No overlap risk: Reflection.MIN_GAP_S=600 >
worst-case deliberation ~300s. Remaining plan item: audio self-voiceprint
(needs resemblyzer, local-only).

---

## Game-state review (2026-06-13) — persistence hardening to-dos

**Save DB is healthy.** `data/alpecca.db` passes `PRAGMA integrity_check` (`ok`),
1.75 MB / 427 pages, header consistent. (A first pass flagged it as "corrupt" —
that was the documented sandbox-mount *truncated-read* quirk, not the real file.
Lesson: copy the DB locally before running integrity checks through the mount.)

No emergency, but persistence has real **hardening gaps** worth closing before
she's relied on heavily:
- **No WAL, no `busy_timeout`.** Both `_connect` helpers (`alpecca/state.py`,
  `alpecca/memory.py`) open plain `sqlite3.connect`. Add
  `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000` (and `synchronous=NORMAL`).
  This matters because the config docstring suggests pointing `ALPECCA_HOME` at a
  synced Google Drive folder — SQLite on cloud-synced storage without WAL is a
  known corruption risk. Keep `ALPECCA_HOME` on local disk unless WAL is on.
- **Concurrent writers aren't serialized.** `mind_lock` (asyncio) only guards the
  *in-memory* mood mutation; the slow self-directed work (`idle_self_direct`,
  `compose_volunteer`) runs off the lock via `asyncio.to_thread` and writes the
  same DB (desires/selfmod/memory) alongside the 8 s drift tick and chat handler.
  Multiple OS threads on one file with no busy_timeout → possible "database is
  locked" errors. Serialize DB writes or add the busy_timeout above.
- **No auto-backup.** Only safety net is a manual copy (`alpecca.backup.db` sits on
  the Desktop). Add a rotating backup on startup/shutdown.
- **No validation on load.** `load_state` trusts persisted values are in [0,1] —
  clamping only happens inside the update rules, so a bad/edited value flows
  straight into the prompt. Clamp on load too.
- **`state_log` grows unbounded** — one row per ~8 s tick plus per chat, never
  pruned. Add periodic pruning/rotation.

---

## TL;DR

Alpecca is a **local, private AI companion** — a stateful agent on one machine
with a persistent mood, real memory, senses, an explicit ethic, self-set goals,
self-tuning, self-questioning, and a reactive anime face. Brain = local Ollama.
**Grounding is the hard rule:** every self-report reads from real internals;
nothing is confabulated.

Her **inner life is real and strong** (mostly unit-tested). The recent friction
was **setup**, now handled by a `doctor` + one-click `.bat` launchers.

**Target machine:** Windows, **RTX 3050 Laptop (~4 GB VRAM)**. Plan around 4 GB.

---

## How to run her

### First time
```
cd C:\Users\Jason\Documents\GitHub\alpaccaai
python -m pip install fastapi uvicorn websockets ollama
ollama pull qwen3:4b-instruct-2507        # 4B brain that fits a 4 GB GPU
python scripts\doctor.py                  # the source of truth for "why won't she run"
```
`doctor.py` checks Python, packages, Ollama + model, the port, every sense, and
the neural-face setup, and prints the exact fix for each. Run it whenever stuck.

### Every time (use the .bat launchers — they avoid the PowerShell env-var trap)
- **`start_full.bat`** — brain + all senses + cowork (expression-sheet face).
- **`start_face.bat`** — brain *and* the THA3 neural face in two windows (after
  `setup_face.bat`).
- `python server.py` — private, senses off.
Open **http://127.0.0.1:8765** ( `/classic` = old chat UI with voice/image ).

### Desktop app + remote access (new)
She now runs as a **real desktop app**, not just a browser page:
- **`Alpecca-App.bat`** (or `python app.py`) — a native window via **pywebview**
  (`pip install pywebview`; falls back to your browser if it's absent). Runs the
  same FastAPI server in-process, senses on, in its own window.
- **Remote access** is opt-in and **always token-gated** (server.py `_auth_gate`
  middleware + `/ws` guard; localhost is *not* special-cased, so a tunnel can't
  slip past): `ALPECCA_REMOTE=1` binds `0.0.0.0` for LAN devices;
  `ALPECCA_TUNNEL=cloudflare|ngrok` opens a public internet URL via a tunnel CLI.
  `app.py` mints `ALPECCA_ACCESS_TOKEN` if unset and prints it; remote clients
  append `?token=…` once (a cookie carries it after). Knobs in `config.py`
  (REMOTE_ACCESS / ACCESS_TOKEN / TUNNEL / BIND_HOST). Senses, memory and brain
  stay local — only chat travels.
- **Package to one `.exe`:** `pip install pyinstaller && pyinstaller --noconsole
  --add-data "web;web" --name Alpecca app.py` (add `data/`/config as needed).
- **Full runbook** for reaching her remotely AND working the PC through her
  (computer-use over the tunnel, confirm flow, guards, checklist):
  `docs/PASSDOWN_remote_computer_access.md`. Quick start: double-click
  `SHARE_PHONE.bat` — it prints the token-gated trycloudflare link.
  (2026-07-06: `scripts/share.py` was fixed — it previously shared
  UNAUTHENTICATED and never really bound 0.0.0.0; pull before sharing.)

### Screen-share in her home (new)
The **Share** nav button now has her walk to the **Observatory** and *hold the live
shared screen as a framed window beside her* in the 3D home (THREE.VideoTexture on
a panel parented to her figure), replacing the old flat fullscreen desk overlay.
Server: `POST /observatory/screen/start|stop`, `mind.set_screen_sharing()` (she
stays put while sharing); she still sees the screen via `/sight/push` (grounding).

### Neural face on the 4 GB laptop GPU (optional)
THA3 fits *with* the brain via three levers: light model (`separable_half`,
~half VRAM), the 4B LLM, and **adaptive framerate** (face renders fast only while
she speaks, drops to ~4 fps while she thinks, so the brain gets the GPU when it
needs it). Run **`setup_face.bat`** once (installs CUDA torch, pulls the 4B model,
clones THA3, preps her 512 image; the one manual step is downloading THA3's light
models into `vendor\talking-head-anime-3-demo\data\models\`). If THA3 OOMs, the
app silently falls back to the expression-sheet face (no VRAM).

### Critical Windows gotcha
In **PowerShell**, `set VAR=value` does NOTHING (that's cmd syntax) — use
`$env:VAR="value"`. The `.bat`s sidestep this. For git, PowerShell here-strings
mangle commit messages — write to a temp file and `git commit -F`.

---

## What was built this session (on top of the existing core)

**Backend (Python, mostly tested):**
- Emotion model gained `curiosity` + `social_hunger` (`homeostasis.py`).
- `affect.py` — expressive readout (feeling/valence/arousal/tempo/gesture + voice
  markup) read by prompts, avatar, and TTS.
- `soul.py` — master agent over 7 subagents (deterministic sensors + LLM
  reasoners), arbitrated by the Good Person Principle.
- `charter.py` — her constitution, enforced in code (priority hierarchy; never
  self-deletes; file ops confined to Desktop/Pictures/Music/Video/general;
  internet only to reach Jason).
- `desires.py`, `selfmod.py`, `journal.py` (+ recursive self-questioning),
  `learning.py` (self-training: grounded *lessons* from her history that steer
  `selfmod`), `home.py` (5 roamed rooms), `pose.py`, `desktop.py` (charter-guarded
  file room).

**Front-end — the super-app at `/` (`web/home.html`):**
- Live 3D home (Three.js) + integrated chat (one WebSocket) + voice (🎤 push-to-
  talk, 🔊 mood-driven TTS) + camera (📷) + cowork (🖥).
- **Live anime face**: her 16 drawn expressions (sliced from her expression sheet
  → `data/character/expressions/`) mapped from her real mood, with lip-sync and a
  mood-glow ring.
- Senses strip (👁/🎤/📷/🖥) + "what she last saw" + her cursor when she works +
  an **activity ticker** showing her autonomous acts.
- Facet panels: Studio, Library, Journal, Mind, Workshop (desires + revisions +
  lessons), Senses/Workspace, Files, Play (browser games).

**Avatar tiers (each driven by the *same grounded mood*, degrading to the next):**
THA3 neural > pose-swap real-art > RIGFORGE mesh (`web/rigforge.html`) >
expression-sheet face > portrait > SVG. Also still wired: Live2D/Cubism, Spine,
layered rig, ToonCrafter clips (see the prior handoff section).

**Ops:** `scripts/doctor.py`, `start_full.bat`, `setup_face.bat`, `start_face.bat`.

**Routes added:** `/`, `/classic`, `/home/state`, `/growth`, `/soul`, `/journal`,
`/memories`, `/desktop` (+move/rename), `/sight`, `/games` (+play),
`/avatar/expression/{name}`, `/avatar/skeleton`, `/avatar/rigpose`, `/rigforge`
(+capture).

---

## Solid vs. shaky (honest)

**Solid:** the backend modules + their tests (emotion rules, affect, home,
desires, selfmod, soul, journal, charter guards, learning, pose). LLM brain works;
state persists; the autonomous loop is wired and livened.

**Shaky:**
- **Persistence hardening pending** (DB itself is healthy — see the game-state
  review section up top). No WAL, no busy_timeout, off-lock concurrent writers, no
  auto-backup, no load validation. Close these before relying on her heavily,
  especially if `ALPECCA_HOME` ever points at synced storage.
- **`web/home.html` is large and NOT fully syntax-checked.** The dev sandbox mount
  serves a stale truncated copy, so a full `node --check` wasn't possible; blocks
  were verified individually via the editor. **If the page renders blank, it's a
  JS error — open F12, find the red line, fix it.** (That's how the earlier
  `THREE`-before-load blank-page bug was caught.) A Phase-4 audit on the real file
  is the top to-do.
- Neural face on 4 GB is tight (fallback covers OOM).
- Senses/cowork need optional packages + flags (doctor reports them).

**Dev-env quirk:** the Linux sandbox mount intermittently truncates large files on
read; the canonical Windows files are correct. Run tests on the real checkout:
`python tests\test_core.py` (or `python -m pytest -q`).

---

## Her real art (still true)
Character bible in `data/character/reference/`. She is a **humanoid anime girl**
(cream-blonde, glowing eyes, chest power-core) — *not* an alpaca (legacy
placeholder). Backgrounds removed (transparent). **`data/` is gitignored** — her
DB, memories, art, and avatar exports live there and don't travel with the repo; a
fresh clone needs her pose/portrait PNGs replaced. The expression face uses
`data/character/expressions/` (sliced this session) and `data/avatar/portraits/`.

---

## Work plan (where we are — from docs/ALPECCA_CURRENT_PROGRESS.md)
- **Phase 0 — runs reliably:** DONE (doctor + launchers).
- **Phase 1 — visibly alive on her own:** DONE (livelier cadences + activity ticker).
- **Phase 2 — presence:** DONE (expression face + lip-sync + mood-driven voice).
- **Phase 3 — senses, visible:** DONE (senses strip + "what she sees" + cursor).
- **Phase 4 — consolidate front-end:** PARTIAL. **Next:** full audit of
  `home.html` (node-check the real file; fix any syntax slip; finish/verify the
  half-wired pieces), give each 3D room distinct visual purpose.
- **Phase 5 — stretch:** THA3 on the laptop (built; needs the one-time setup run +
  model download); cowork reliability + her cursor; RIGFORGE → `Alpeccaai-data`
  self-training loop; AutoSprite-generated expression/animation frames.

## Immediate next steps
1. **Harden persistence** (DB is healthy, this is preventive): WAL + `busy_timeout`
   in both `_connect` helpers, serialized/single-writer DB writes, a rotating
   auto-backup, clamp-on-load, and keep `ALPECCA_HOME` on local disk.
2. `setup_face.bat` → `python scripts\doctor.py` → `start_face.bat`; confirm she
   comes up with brain + neural face on the 4 GB GPU.
3. Phase-4 audit of `web/home.html` on the real checkout (node-check; fix blanks).
4. Watch the activity ticker a few minutes — confirm the autonomous loop fires.

## Orientation
`CLAUDE.md` (architecture) · `docs/` (design + review docs) · `alpecca/` (modules)
· `server.py` (FastAPI + WS) · `web/` (UI) · `tests/test_core.py` (Ollama/Windows-
free) · `scripts/` (doctor, run_full, run_talkinghead, import_rig, build_manifest).

---

## Prior handoff (2026-06-11) — still-relevant notes
- Branch `build/alpecca-companion` → PR #2 against `main`; tests were 96 passing
  then (more added this session).
- The full avatar tier stack predates this session: **THA3** (`talkinghead.py`),
  **Cubism** (`live2d.py`, drop a `.model3.json`), **Spine** (`spine.py`,
  StretchyStudio export — the originally-recommended primary rig path),
  **ToonCrafter clips** (`run_tooncrafter.py` → `data/avatar/*.mp4`), **layered
  rig** (See-Through PSD → `import_rig.py`), **mesh rig**, pose/SVG.
- Recommended full-rig pipeline (needs the user's GPU, all free/open):
  See-Through (decompose art → PSD) → StretchyStudio (in-browser auto-rig →
  Spine 4.0 JSON) → drop into `data/avatar/spine/`. Tune the renderer fit to her
  real skeleton on first export.
- PIXI + pixi-spine vendored in `web/vendor/` (local-first). Live2D Cubism core is
  still CDN (proprietary, model tier only).
- Talk mode (`scripts/run_talk.py`) needs a separate Python 3.12 venv
  (`.venv-talk/`) — pyaudio has no 3.14 wheels; browser 🎤 avoids this.
