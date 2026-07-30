# Alpecca Cloud Language Worker

This Worker is an authenticated, text-only OpenAI-compatible bridge from the
fenced Hugging Face continuity core to Cloudflare Workers AI. It forces the
Cloudflare-hosted `@cf/google/gemma-4-26b-a4b-it` model and never accepts art,
audio, files, or screen payloads. It stores no prompt, reply, identity, memory,
or continuity state; Alpecca's one CoreMind and shared context remain in the
fenced runtime.

Gemma 4 thinking is pinned off at the provider boundary so short completions
reserve their output budget for visible answer text. Clients cannot override
that behavior.

## Security boundary

- `GET /healthz` is content-free and exposes only the fixed service contract.
- `POST /v1/chat/completions` requires the `LANGUAGE_AUTH_SECRET` Worker secret.
- Authentication uses fixed-size SHA-256 values and constant-time comparison.
- Bodies, messages, text, tools, and output tokens are bounded before inference.
- Logs contain counts, latency, model ID, and a random request ID, never content.
- Model substitution, streaming, multimodal content, and unknown routes fail
  closed.

## Verification and deployment

```powershell
npm.cmd install
npm.cmd run check
npm.cmd run build:dry-run
npx.cmd wrangler secret put LANGUAGE_AUTH_SECRET
npx.cmd wrangler deploy
```

Never put the shared secret in source, `wrangler.jsonc`, a command argument, or
logs. Use `scripts/deploy_cloud_language_route.ps1 -Apply` from the repository
root to generate one fresh secret, deploy this Worker, update the Pages gateway,
and synchronize the protected Hugging Face Space secret without printing it.
