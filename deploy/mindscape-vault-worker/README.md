# Alpecca Mindscape Vault

Mindscape Vault is Alpecca's separate cloud-recovery system. It does not host
an active Alpecca, generate text, process art, or expose memories to a browser.
The local laptop encrypts each record before upload. This Worker stores opaque,
immutable ciphertext objects in R2 and returns them only to an authenticated
local recovery client.

Two records are retained:

- Frequent compact continuity snapshots: current state, recent memory/chat
  continuity, journal, and observable runtime state.
- Less-frequent full SQLite recovery archives: the local durable database,
  encrypted before upload. They contain no art files; Alpecca art remains on
  Hugging Face under the project storage policy.

The local runtime remains Alpecca's only active CoreMind. A cloud backup can be
restored only after a local host is running and the creator explicitly requests
the restore flow.

## First deployment

From the repository root, use the provisioner with Wrangler authenticated to
the intended Cloudflare account:

```powershell
python scripts\provision_mindscape_vault.py
```

It creates or reuses the bucket, updates the Worker secret from the dedicated
Credential Manager token without printing it, deploys the Worker, discovers
its `workers.dev` URL, and writes only that non-secret endpoint beneath ignored
runtime data. The manual equivalent, for exceptional setups, is:

```powershell
cd deploy\mindscape-vault-worker
npx wrangler r2 bucket create alpecca-mindscape-vault
npx wrangler secret put MINDSCAPE_VAULT_TOKEN
npx wrangler deploy
```

Then configure the local process with the deployed Worker base URL:

```powershell
$env:ALPECCA_MINDSCAPE_VAULT_URL = "https://alpecca-mindscape-vault.<account>.workers.dev"
```

On Windows, Alpecca keeps a separately generated Worker transport token in
Credential Manager under `Alpecca/MindscapeVaultTransportToken`; use that same
value only when setting the Worker secret. The local runtime reads it directly,
so it never belongs in source, Git, a browser URL, or a launcher file.

On first successful use, Alpecca also generates a separate 32-byte encryption
key in Credential Manager under `Alpecca/MindscapeVaultEncryptionKey`. It is
not the Worker token. A disaster recovery host needs the same key through
`ALPECCA_MINDSCAPE_VAULT_KEY`; keep that recovery secret in an owner-controlled
offline password manager, not in this repository or Worker.

## Contract

`POST /v1/snapshot` accepts only a strict AES-256-GCM encrypted JSON envelope.
`POST /v1/archive` accepts an encrypted SQLite byte stream with authenticated
metadata. Both write immutable R2 object keys with `If-None-Match: *`, so a
late retry cannot overwrite an earlier backup. `GET` routes return ciphertext
only; the Worker never decrypts or renders private continuity data.

The Worker requires `MINDSCAPE_VAULT_TOKEN` for every route. Do not embed that
token in a browser page, Cloudflare tunnel URL, Git history, or Discord message.

## Recovery

On a local recovery host with the Vault URL/token and the separate recovery key
available, run:

```powershell
python scripts\restore_mindscape_vault_archive.py
```

The command writes a verified copy below `data\recovery` and never overwrites
the active `alpecca.db`. Promote that file only after stopping the live stack
and reviewing the recovery result.
