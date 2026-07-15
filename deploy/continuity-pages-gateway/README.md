# Alpecca Continuity Pages Gateway

This Cloudflare Pages Function gives the Hugging Face survival core a stable
`pages.dev` route to the existing continuity authority and encrypted Vault.
Both backends remain the same Workers and storage; service bindings invoke them
inside Cloudflare, so this gateway does not copy a lease, token, archive, or
memory.

- `/lease/*` forwards to `alpecca-continuity-lease`.
- `/vault/*` forwards to `alpecca-mindscape-vault`.
- `/healthz` exposes only a content-free gateway identity.
- Every other path fails closed.

Authorization headers pass through to the downstream service. The gateway has
no secrets of its own. Cloudflare stores no Alpecca art here.

Deploy from this directory after the two bound Workers exist:

```powershell
..\continuity-lease-worker\node_modules\.bin\wrangler.cmd pages deploy public --project-name alpecca-continuity-gateway --branch main
```
