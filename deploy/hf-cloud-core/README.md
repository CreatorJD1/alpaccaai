---
title: Alpecca Continuity Core
sdk: docker
app_port: 7860
pinned: false
---

# Alpecca Continuity Core

This private Docker Space is an on-demand fallback for Alpecca. It is not a
second active CoreMind and is not an always-on guarantee. Free Hugging Face
Spaces may sleep and stop executing; every enabled wake starts from a closed
port and must pass verified restore, the configured promotion policy, and
continuity fencing again. The image is inert unless
`ALPECCA_CLOUD_CORE_ENABLED=1` is explicit.

The core uses the existing `alpecca.mind` Hugging Face backend with exactly
`Qwen/Qwen3.5-9B`. Qwen companion and reflection calls use non-thinking mode.
The image does not run Ollama or substitute an older Qwen family.

## Startup order

`app.py` enforces this sequence:

1. Create a fresh private runtime directory.
2. Fetch `/archive/latest` from Mindscape Vault. The existing Vault client
   authenticates AES-256-GCM, checks ciphertext and plaintext digests, and runs
   SQLite `PRAGMA integrity_check` before installing `alpecca.db`.
3. Require either a short-lived CreatorJD approval bound to the restored
   archive and next fencing epoch, or the explicit deployment-level unattended
   failover policy described below.
4. Acquire the remote continuity lease as `cloud-standby`. In manual mode the
   exact grant must consume the approval's one-use epoch; automatic mode still
   cannot proceed while a fresh local heartbeat or another lease exists.
5. Publish the Space HTTPS origin under that lease, then and only then spawn
   `uvicorn server:app` on port 7860.
6. Renew every 10 seconds. Lease loss sends `SIGKILL` to the server process
   group so no shutdown hook or descendant can write after the fence is gone.

There is no pre-lease CoreMind or public standby server. A disabled deployment,
missing configuration, Vault failure, promotion-policy failure, lease denial,
or endpoint-publication failure leaves port 7860 closed. The local laptop
remains preferred while its heartbeat is fresh.

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

- `ALPECCA_CONTINUITY_LEASE_URL`
- `ALPECCA_MINDSCAPE_VAULT_URL`
- `ALPECCA_CLOUD_CORE_ENABLED=1` after the reviewed image is deployed and the
  laptop is confirmed to be renewing its local lease
- `ALPECCA_CLOUD_AUTO_FAILOVER=1` to authorize unattended promotion after an
  authenticated Vault restore; omit it to require one-use approval instead

Hugging Face supplies `SPACE_HOST` and `SPACE_ID`. `SPACE_HOST` becomes the
published HTTPS origin. `ALPECCA_PUBLIC_URL` and
`ALPECCA_CONTINUITY_NODE_ID` are optional explicit overrides. Secrets must stay
in Space settings, never image layers, variables, URLs, or repository files.

Camera, screen, microphone, computer use, Discord, local voice workers, legacy
Mindscape sync, and cloud Vault writes are forced off. The restored archive is
read-only continuity input until those side effects can validate the exact
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

The standalone Space Dockerfile clones the reviewed source branch
`codex/voice-session-audio-normalization`, runs the House HQ production build,
then copies this supervisor from the Space repository. Override
`ALPECCA_GIT_REF` only with another reviewed ref.

`cloud_entrypoint.install_vrm()` retains a SHA-256-locked optional fetch from
Alpecca's Hugging Face runtime-assets dataset. Core startup does not depend on
that download. Art remains on Hugging Face and is never uploaded to Cloudflare
by this scaffold.

## Network-free tests

```powershell
python -m pytest -q tests\test_hf_cloud_core.py
```

The tests use fake Vault, lease, and child-process adapters. They do not contact
Hugging Face, Cloudflare, GitHub, or Mindscape Vault.
