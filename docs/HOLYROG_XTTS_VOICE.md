# HOLYROG XTTS Voice Service

`Jason_HOLYROG` can provide GPU-only XTTS-v2 synthesis to the RygenART primary.
It is a separate helper service, not a second Alpecca instance: it starts no
CoreMind, Discord bridge, memory, identity, continuity, tunnel, or computer-use
process.

## Security boundary

- The service runs as `SYSTEM` in the `Alpecca HOLYROG XTTS Voice` startup task.
- Its 32-or-more-byte voice secret uses the dedicated Windows Credential Manager
  record `Alpecca/Jason_HOLYROG/XTTSVoice`. It is staged only to
  `%PROGRAMDATA%\Alpecca\holyrog-xtts\voice.secret`, whose ACL grants full access
  only to `SYSTEM` and local Administrators. It is never a task argument, URL,
  source file, or log field.
- It binds `0.0.0.0:8790` solely so Tailscale can reach it. The installer creates
  one Windows Firewall allow rule on the `Tailscale` interface for RygenART's
  address `100.96.54.97`; it does not open LAN, public, router, or tunnel access.
- Traffic remains inside the encrypted tailnet. The endpoint additionally requires
  the `X-Alpecca-Voice-Authorization` secret header. Do not publish port 8790.
- The service requires CUDA. It will not silently switch to CPU, download a model,
  or accept the Coqui license without the explicit installation flag below.

## One-time setup on Jason_HOLYROG

Install XTTS into the dedicated Python 3.9-3.11 environment and place consented
reference `.wav` clips directly in:

```text
data\voice_references\xtts_reference_set\
```

When the existing compute-worker credential is already installed, derive a
separate, domain-scoped voice credential without displaying either value:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_holyrog_xtts_voice.ps1 -DeriveSecret
```

Run the same command on RygenART before enabling its voice client. It derives
the same value locally from the shared compute-worker credential; the voice
secret is never copied through chat, a command line, a file, or a log. Use
`-InstallSecret` only if no compute-worker credential exists and you deliberately
choose to provide a separate voice secret twice through the hidden prompt.

Then, from an Administrator PowerShell, create the service. `-AcceptCoquiLicense`
records your explicit acknowledgement for the task; use it only if you agree to
the XTTS-v2 license terms:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_holyrog_xtts_voice.ps1 `
  -Install -AcceptCoquiLicense
```

Use `-ReferencePath 'D:\consented-clips'` only when the clips intentionally live
outside the default location. The installer requires direct `.wav` clips, a
CUDA-capable XTTS Python environment, the staged secret, and explicit license
acknowledgement before it creates or starts the task. It installs no packages and
does not download XTTS weights.

## Primary configuration and verification

On RygenART, use `-DeriveSecret` (or the matching hidden-prompt alternative) to
store the **same voice secret** in its own Credential Manager. The primary client
reads that record locally; do not add the secret to an environment variable.
Configure only the endpoint for the current primary process:

```powershell
$env:ALPECCA_HOLYROG_VOICE_URL = 'http://jason-holyrog.tailda0108.ts.net:8790'
```

The existing primary client fails closed and falls back to its local Kokoro path
when this service is unavailable.

On the ROG, inspect the task without revealing secret material:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_holyrog_xtts_voice.ps1 -Status
Get-NetTCPConnection -LocalPort 8790 -State Listen
Get-Content 'C:\ProgramData\Alpecca\holyrog-xtts\logs\voice-server.log' -Tail 40
```

`-Start`, `-Stop`, and `-Remove` manage only this voice task. Removal preserves
the protected secret, clip set, XTTS model cache, and logs.
