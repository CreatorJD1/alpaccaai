---
title: Alpecca Continuity Core
sdk: docker
app_port: 7860
pinned: false
---

# Alpecca Continuity Core

This public-repository Docker Space is an on-demand fallback for Alpecca. It is not a
second active CoreMind and is not an always-on guarantee. Free Hugging Face
Spaces may sleep and stop executing; every enabled wake starts from a closed
port and must pass verified restore, the configured promotion policy, and
continuity fencing again. The image is inert unless
`ALPECCA_CLOUD_CORE_ENABLED=1` is explicit.

The core uses the existing `alpecca.mind` Hugging Face backend with exactly
`Qwen/Qwen3.5-9B`. Qwen companion and reflection calls use non-thinking mode.
The image does not run Ollama or substitute an older Qwen family.

## Startup order

`cloud_entrypoint.py` and `app.py` enforce this sequence:

1. Start the descriptor-free Kokoro voice sidecar on internal port 7861, then
   serve the standby identity and authenticated voice gateway on the only
   public Space port, 7860. The standby identity is explicitly not CoreMind and
   the phone launcher will not accept it as active Alpecca.
2. Poll authenticated authority status without loading a model or memory. A
   promotion attempt begins only when there is no active lease and no fresh
   local-primary heartbeat.
3. Create a fresh private runtime directory and install the SHA-256-locked V.4
   VRM from Alpecca's Hugging Face asset dataset.
4. Fetch `/archive/latest` from Mindscape Vault. The existing Vault client
   authenticates AES-256-GCM, checks ciphertext and plaintext digests, and runs
   SQLite `PRAGMA integrity_check` before installing `alpecca.db`.
5. Require either a short-lived CreatorJD approval bound to the restored
   archive and next fencing epoch, or the explicit deployment-level unattended
   failover policy described below.
6. Acquire the remote continuity lease as `cloud-standby`. In manual mode the
   exact grant must consume the approval's one-use epoch; automatic mode still
   cannot proceed while a fresh local heartbeat or another lease exists.
7. Publish the Space HTTPS origin under that lease, then and only then spawn
   `uvicorn server:app` on port 7860.
8. Renew every 10 seconds. Lease loss sends `SIGKILL` to the server process
   group so no shutdown hook or descendant can write after the fence is gone.
   The supervisor then returns to health-only standby. An unexpected clean
   server exit also returns to standby; only a container shutdown ends the
   entrypoint.

There is no pre-lease CoreMind. The credential-free standby response contains
only service/state flags and no memory, model output, credential, or private
status. A disabled deployment leaves the process inert; missing configuration,
Vault failure, promotion-policy failure, lease denial, or endpoint-publication
failure returns the enabled process to standby. The local laptop remains
preferred while its heartbeat is fresh.

## Cloud voice lifecycle

Hugging Face routes one configured Docker Space `app_port`, which is 7860 for
this image. The supervised Kokoro process listens on loopback-only port 7861,
and the standby gateway addresses it through that fixed URL. Hugging Face does
not publish 7861 as a second Space port. If the sidecar exits, the container
exits instead of reporting a voice-capable but unusable standby; container
health also requires the sidecar's content-free loopback health route to be
ready during both standby and promotion. A timestamped five-minute health grace
covers only the intentional public-port handoff across the capped VRM download,
archive restore, event merge, and promoted Core bind; it cannot hide sidecar
failure or a longer stall.

While the continuity core is in standby:

- `GET /voice/health` returns content-free engine, voice, load, persistence,
  CoreMind, and singleton-authority status. It does not load Kokoro.
- `POST /voice/tts` requires `X-Alpecca-Authorization`, applies bounded request
  and response limits, and proxies to the sidecar's in-memory `af_heart` WAV
  synthesis. Request text and audio are not persisted.
- `/` and `/healthz` retain the original standby identity and do not claim an
  active CoreMind or continuity lease.

During promotion the standby listener releases port 7860 before the fenced
supervisor starts `server:app`. The active server owns the same public
`POST /voice/tts` path through its normal authorization middleware. Its process
is pinned to local Kokoro and receives empty cloud-TTS endpoint and
authorization variables, preventing the active route from recursively calling
its own Space URL. The sidecar remains internal so it is immediately available
when the supervisor returns to standby; it never restores memory, constructs
CoreMind, acquires a lease, or gains singleton authority.

Space-side voice configuration uses protected Space settings:

- `ALPECCA_CLOUD_VOICE_SECRET` is an optional dedicated authorization secret.
  When omitted, the service uses the existing protected `ALPECCA_AUTH_SECRET`.
- `ALPECCA_CLOUD_VOICE_PORT` optionally changes the internal sidecar port; the
  image default is 7861 and must match the standby gateway.

The laptop client must send the same protected authorization value. Set
`ALPECCA_CLOUD_TTS_AUTHORIZATION` to match `ALPECCA_CLOUD_VOICE_SECRET`, or let
the launcher reuse its protected local `ALPECCA_AUTH_SECRET` when the Space uses
that fallback. A mismatch returns `401` and `auto` routing falls back locally.

Never place either authorization value in Space variables, repository files,
URLs, image layers, logs, or health output.

## Space settings

The phone-reachable survival endpoint uses a **public Docker Space repository**
with Alpecca's own server authentication still enforced. Hugging Face Space
secrets remain private; no credential is stored in repository files or public
variables. A private Space adds a Hugging Face login wall that the launcher
cannot use for unattended discovery. Required Space secrets:

- `HF_TOKEN`
- `ALPECCA_CONTINUITY_LEASE_TOKEN`
- `ALPECCA_MINDSCAPE_VAULT_TOKEN`
- `ALPECCA_MINDSCAPE_VAULT_KEY`
- `ALPECCA_AUTH_SECRET`
- `ALPECCA_CREATOR_PASSWORD`
- `ALPECCA_CLOUD_RESTORE_APPROVAL` only when using manual promotion

Required Space variables:

- `ALPECCA_GIT_REF`, the reviewed GitHub branch to clone (`main` for release,
  or an explicitly reviewed branch for a preview build)
- `ALPECCA_GIT_SHA`, the exact full 40-character commit expected at that branch;
  the Docker build fails if the cloned branch head differs
- `ALPECCA_CONTINUITY_LEASE_URL`
- `ALPECCA_MINDSCAPE_VAULT_URL`
- `ALPECCA_CLOUD_CORE_ENABLED=1` after the reviewed image is deployed and the
  laptop is confirmed to be renewing its local lease
- `ALPECCA_CLOUD_AUTO_FAILOVER=1` to authorize unattended promotion after an
  authenticated Vault restore; omit it to require one-use approval instead

The deployed Space uses the service-binding gateway rather than direct
`workers.dev` URLs because Hugging Face blocks that DNS suffix in Space
containers. Configure:

- `ALPECCA_CONTINUITY_LEASE_URL=https://alpecca-continuity-gateway.pages.dev/lease`
- `ALPECCA_MINDSCAPE_VAULT_URL=https://alpecca-continuity-gateway.pages.dev/vault`

Those prefixes forward to the existing Workers without copying continuity
state. The final Docker image also removes repository deployment scripts,
documentation, and `.git`; the survival container retains runtime source only.

Hugging Face supplies `SPACE_HOST` and `SPACE_ID`. `SPACE_HOST` becomes the
published HTTPS origin. `ALPECCA_PUBLIC_URL` and
`ALPECCA_CONTINUITY_NODE_ID` are optional explicit overrides. Secrets must stay
in Space settings, never image layers, variables, URLs, or repository files.

Camera, screen, microphone, computer use, Discord, in-process background voice
workers, legacy Mindscape sync, and cloud Vault writes are forced off. The
isolated Kokoro sidecar is the only standby voice process. The restored archive
is read-only continuity input until other side effects can validate the exact
fencing tuple at their own trust boundaries.

## Restore approval

A wake without `ALPECCA_CLOUD_RESTORE_APPROVAL` verifies the latest archive,
prints only its sequence and SHA-256 fingerprint, and exits before requesting a
lease. CreatorJD or the external creator verifier combines that fingerprint
with the authority's expected next epoch and issues a maximum-five-minute
approval:

```json
{
  "approvalId": "restore-20260715-001",
  "purpose": "stage-passive-restore",
  "creatorPrincipal": "CreatorJD",
  "snapshotDigest": "sha256:<verified archive fingerprint>",
  "leaseEpoch": 42,
  "issuedAt": "2026-07-15T20:00:00Z",
  "expiresAt": "2026-07-15T20:05:00Z",
  "oneUse": true,
  "verification": {
    "status": "verified",
    "verifier": "external-creator-verifier",
    "evidenceId": "creator-check-20260715-001"
  }
}
```

Set the compact JSON as the Space secret and restart. The authority's monotonic
epoch makes the approval one-use: after acquisition, release, or expiry, a later
grant has a different epoch and the old approval cannot publish or start the
core. If another actor consumes the predicted epoch, query authority status and
issue a new approval.

## Automatic survival mode

`ALPECCA_CLOUD_AUTO_FAILOVER=1` is a persistent CreatorJD deployment decision,
not a bypass of the singleton fence. It removes only the short-lived approval
document that cannot be supplied after an unexpected laptop power loss. The
core must still authenticate and integrity-check the newest encrypted Vault
archive, acquire a newer monotonic fencing epoch, publish under that exact
lease, and keep renewing it. A fresh laptop heartbeat blocks acquisition, and
lease loss kills the cloud server process group before another host can take
over. Discord, sensors, computer use, voice workers, and Vault writes remain
disabled in this survival core.

## Image and source

The standalone Space Dockerfile defaults to the reviewed `main` branch, requires
an explicit `ALPECCA_GIT_SHA`, clones that branch, and aborts unless its head is
the exact configured commit. It then runs the House HQ production build and
copies this supervisor from the Space repository. The branch selects what Git
may fetch; the SHA prevents a moving branch or stale Space variable from
silently selecting different runtime source.

### Source publication gate

There is no local cloud-core deployment script. Scripts that publish the
ZeroGPU or texture Spaces target different repositories and must not be reused
for this continuity Space. Use this order for either a reviewed branch preview
or a `main` release:

1. Keep the Space paused. This prevents an edit to build variables or Space
   files from launching an intermediate rebuild with its previous Dockerfile.
2. Commit the complete GitHub runtime source first. The commit must include the
   active `/voice/tts` alias and every runtime dependency expected by this Space.
3. Push the selected branch to `origin`. For a release, merge and push `main`
   before continuing; for a preview, push the exact reviewed branch.
4. Read both local and remote identities without abbreviation:

   ```powershell
   git rev-parse HEAD
   git ls-remote --heads origin <selected-branch>
   ```

   Stop unless both commands identify the same 40-character commit and the
   working tree contains no uncommitted release files.
5. In Space **Variables** (not Secrets), set `ALPECCA_GIT_REF` to that branch,
   then set `ALPECCA_GIT_SHA` to the matching full commit. Never point the ref
   at an unpushed local branch. Do not put authorization material in either
   value.
6. Publish the contents of `deploy/hf-cloud-core/` to the Space repository as
   one reviewed commit. Do not publish the parent repository or local runtime
   data. The Space README metadata must remain `sdk: docker` and
   `app_port: 7860`.
7. Resume or rebuild the Space only after the GitHub ref, exact SHA, Space
   variables, Dockerfile, and Space support files agree. A source mismatch must
   fail during the Docker clone stage rather than start a stale runtime.
8. Inspect the build receipt, then verify `/healthz` retains the standby
   identity and `/voice/health` reports content-free voice status. Promotion
   remains separately gated by restore approval or the configured automatic
   policy and the singleton continuity lease.

Changing only the Space files before the GitHub push is unsafe: the rebuild
would clone whichever source the previous build variables still select.
Changing a branch without changing its expected SHA is intentionally a failed
build, not an implicit upgrade.

`cloud_entrypoint.install_vrm()` fetches V.4 from Alpecca's Hugging Face
runtime-assets dataset and verifies its locked SHA-256 before restore or lease
acquisition. A failed or changed body blocks promotion. Art remains on Hugging
Face and is never uploaded to Cloudflare by this scaffold.

## Network-free tests

```powershell
python -m pytest -q tests\test_hf_cloud_core.py tests\test_hf_cloud_voice.py tests\test_hf_cloud_entrypoint_voice.py
```

The tests use fake Vault, lease, child-process, HTTP, Kokoro, and soundfile
adapters. They do not contact Hugging Face, Cloudflare, GitHub, Mindscape Vault,
or model hosting.
