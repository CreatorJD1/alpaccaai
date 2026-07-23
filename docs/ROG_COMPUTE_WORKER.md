# Jason_HOLYROG Compute Worker

Status: authenticated health and `qwen3.5:9b` reasoning were live-verified from
the primary on 2026-07-23. Persistent dedicated-server installation remains a
separate ROG-side step until the scheduled task below is installed and checked.

Current source verification: 156 focused worker/client/launcher/host-role tests
and 371 core regression tests pass. This is not a substitute for the live ROG
checks below.

## Purpose

`Jason_HOLYROG` is a compute-only helper for Alpecca's primary instance. It can
accept the bounded jobs implemented by `alpecca.rog_worker_server`, such as
background reasoning with `qwen3.5:9b` and approved Blender renders. The primary
CoreMind remains the only speaker and the only authority for memory, identity,
emotion, tools, Discord, and continuity.

The worker must never run:

- CoreMind or Alpecca's main HTTP application;
- Discord text or voice bridges;
- memory, journal, Mindpage, Vault, or continuity writers;
- a continuity speaking lease or cloud failover role;
- Cloudflare, another tunnel, screen control, camera, or file tools;
- arbitrary commands, scripts, Blender expressions, or user-supplied paths.

The worker launcher applies inert process settings before loading the isolated
app. It starts one Uvicorn process with access logging disabled. Loopback is the
default. LAN listening requires the explicit
`ALPECCA_ROG_WORKER_LAN=1` setting.

Private-LAN traffic is HTTPS-only. The worker generates a private key and a
self-signed certificate for the exact DNS name `Jason_HOLYROG` under
`%LOCALAPPDATA%\Alpecca\rog-worker\tls`; the private key never leaves the ROG.
The primary trusts a copied public certificate through
`ALPECCA_ROG_WORKER_CA_CERT`. HMAC still authenticates each bounded request.

## Trust Boundary

The shared worker secret is read in this order:

1. `ALPECCA_ROG_WORKER_SECRET` in the current process environment.
2. The exact Windows Credential Manager record
   `Alpecca/Jason_HOLYROG/ComputeWorker`.

The secret is never accepted as a command-line argument, URL, source file, or
log field. Use the same 32-or-more-character value on the ROG and on the primary
computer. `--install-secret` prompts without echo and writes only the dedicated
Credential Manager record.

Worker authentication does not make the worker a second Alpecca. Every remote
job remains bounded by the worker's fixed operation schema, input/output caps,
approved model and render roots, concurrency limit, timeout, and content-free
audit record.

## Prerequisites On Jason_HOLYROG

1. Windows hostname exactly `Jason_HOLYROG` (comparison is case-insensitive).
2. A clean checkout at the same approved source commit as the primary.
3. Python 3.11 or newer with this repository's requirements installed.
4. Ollama installed and `qwen3.5:9b` available.
5. Blender installed only if Blender jobs will be enabled by the worker app.
6. A private network route from the primary computer to the ROG.

The setup script does not install packages, pull models, modify firewall rules,
create services, or create scheduled tasks. It inventories the machine with the
read-only `scripts/qualify_rog_worker.py` utility and prints explicit next
steps. A separate, explicit dedicated-server installer is described below.

## Setup

Open PowerShell in the repository on `Jason_HOLYROG`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_rog_worker.ps1
python -m pip install -r requirements.txt
ollama pull qwen3.5:9b
powershell -ExecutionPolicy Bypass -File scripts\setup_rog_worker.ps1 -InstallTls
powershell -ExecutionPolicy Bypass -File scripts\setup_rog_worker.ps1 -InstallSecret
powershell -ExecutionPolicy Bypass -File scripts\setup_rog_worker.ps1 -CheckWorker
```

Copy only the generated public certificate
`%LOCALAPPDATA%\Alpecca\rog-worker\tls\jason-holyrog.crt` to the same path on
the primary laptop. Never copy `jason-holyrog.key`. The supported launcher
uses that public-certificate path by default.

Enter the same shared secret when prompted on each computer. On the primary
computer, this command stores the matching credential and exits without
starting a worker:

```powershell
python scripts\run_rog_compute_worker.py --install-secret
```

The credential command is intentionally usable on the primary computer. The
hostname requirement is enforced when checking or starting the worker, and by
the setup script itself.

## Start And Connect

Loopback-only smoke on the ROG:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_rog_worker.ps1 -StartWorker
```

For private-LAN use, explicitly widen only that process:

```powershell
$env:ALPECCA_ROG_WORKER_LAN = '1'
$env:ALPECCA_ROG_WORKER_BLEND_ROOT = 'D:\AlpeccaWorker\blend-input'
$env:ALPECCA_ROG_WORKER_OUTPUT_ROOT = 'D:\AlpeccaWorker\render-output'
powershell -ExecutionPolicy Bypass -File scripts\setup_rog_worker.ps1 -StartWorker
```

Both render folders must already exist. Put only approved `.blend` files
directly inside the input folder; render requests accept a basename such as
`alpecca_scene.blend`, never an arbitrary path or Blender script. The worker
writes a PNG into the output folder and returns content-free artifact metadata.
Automatic artifact transfer back to the primary is not part of this first
slice; use the ROG output folder as the render authority.

The default port is `8788`. A different unprivileged port can be selected for
that process with `ALPECCA_ROG_WORKER_PORT`. Restrict the Windows Firewall rule
to the Private profile and the primary computer's IP. Do not publish this port
through a public tunnel or router port-forward.

On the primary computer, set the endpoint for the current launch session:

```powershell
$env:ALPECCA_ROG_WORKER_URL = 'https://Jason_HOLYROG:8788'
$env:ALPECCA_ROG_WORKER_CA_CERT = "$env:LOCALAPPDATA\Alpecca\rog-worker\tls\jason-holyrog.crt"
$env:ALPECCA_ROG_WORKER_MODEL = 'qwen3.5:9b'
```

The supported launcher applies those primary-side defaults. CreatorJD can read
the authenticated worker state at `GET /system/rog-worker` and request one
approved render with `POST /system/rog-worker/render` using exactly
`{"project":"alpecca_scene.blend","frame":1}`. Deep background reflection
tries the worker first, then the existing hosted and local fallback chain.

## Dedicated Server Mode

After the foreground health and reasoning checks pass, install the compute-only
worker as a dedicated Windows scheduled task from an **Administrator
PowerShell** on `Jason_HOLYROG`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_rog_compute_server.ps1 -Install
```

When Blender is installed and render offload is wanted, enable the bounded
render lane during installation:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_rog_compute_server.ps1 -Install -EnableBlender
```

This creates only `%LOCALAPPDATA%\Alpecca\rog-worker\blend-input` and
`render-output`, plus a local enable marker. The scheduled worker resolves the
installed `blender.exe` on every start and exposes only projects placed directly
in the approved input root. It does not accept arbitrary paths or Blender
scripts.

This separate installer performs worker qualification again, registers one
hidden task named `Alpecca ROG Compute Server`, starts it at the dedicated
Windows account's logon, and restarts it one minute after a failure. It keeps
the existing authenticated HTTPS listener on port 8788 and writes operational
output under `%LOCALAPPDATA%\Alpecca\rog-worker\logs`.

It launches only `setup_rog_worker.ps1 -CheckWorker -StartWorker`. It does not
launch CoreMind, Discord, memory, continuity, Cloudflare, or another Alpecca
instance. Tailscale remains the private cross-network transport; do not add a
public tunnel or router port-forward.

Inspect or control the task on the ROG with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_rog_compute_server.ps1 -Status
powershell -ExecutionPolicy Bypass -File scripts\install_rog_compute_server.ps1 -Stop
powershell -ExecutionPolicy Bypass -File scripts\install_rog_compute_server.ps1 -Start
```

Removal unregisters only this task and preserves its credential, TLS identity,
models, logs, and all Alpecca data:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_rog_compute_server.ps1 -Remove
```

The primary's ordered deep route remains `rog-worker,ollama-cloud`; if the ROG
is unreachable or rejects a job, Alpecca continues to `gemma4:cloud` and then
the existing local Qwen fallback. The dedicated worker is never a required
speaker or memory authority.

The primary must retain its existing local/cloud fallback. A timeout, refused
connection, bad signature, stale request, malformed response, or unavailable
ROG capability must fail that one remote attempt; it must not stall live chat,
promote the ROG to speaker, or transfer memory authority.

## Operational Checks

Before accepting the worker as live evidence, record all of these:

1. `scripts/setup_rog_worker.ps1 -CheckWorker` passes on `Jason_HOLYROG`.
2. The qualification report says `qualified-worker-only` and names no live role.
3. The worker health response arrives over certificate-validated HTTPS,
   reports `role=compute-only`, and names no speaking, Discord, memory-writer,
   tunnel, or continuity ownership capability.
4. One authenticated `qwen3.5:9b` job completes within its bound.
5. If enabled, one approved-root Blender render completes and an escaped path
   is rejected.
6. Stopping the ROG makes the primary use its normal fallback without losing a
   chat turn or creating a second speaker.
7. Process inspection shows one worker listener and no Alpecca speaker process
   on the ROG.

Source presence, a successful import, or a visible listener is not sufficient
to call the remote worker operational.

## Stop And Undo

- Stop a foreground worker with `Ctrl+C`.
- Clear session-only settings with
  `Remove-Item Env:ALPECCA_ROG_WORKER_LAN -ErrorAction SilentlyContinue` and the
  equivalent commands for URL, port, and model if they were set.
- Remove only the dedicated credential on `Jason_HOLYROG` with:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_rog_worker.ps1 -RemoveCredential
```

No service, task, firewall rule, model, repository file, or Alpecca state is
removed by that command. If a firewall rule or model was installed manually,
remove it separately only after confirming it is not shared by another use.

## Troubleshooting

- **Wrong hostname:** do not bypass the check. Confirm that the intended ROG is
  being configured.
- **Qualification needs attention:** synchronize the approved commit, inspect
  the content-free reasons, and restore a clean checkout before startup.
- **Authorization not configured:** rerun `-InstallSecret` on both computers
  with the same value; never place it in a tracked `.env` file.
- **Model not ready:** run `ollama show qwen3.5:9b`, then pull it if absent.
- **Works on loopback but not LAN:** confirm the explicit LAN environment,
  copied public certificate, exact `Jason_HOLYROG` DNS name, private DNS/IP
  reachability, and a narrowly scoped Private-profile firewall rule. Do not
  replace the HTTPS URL with private-LAN HTTP.
- **Primary falls back:** inspect content-free worker health and audit status;
  do not increase timeouts until connectivity, authentication, and model
  readiness are separately verified.
