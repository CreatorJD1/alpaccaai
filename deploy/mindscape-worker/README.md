# Alpecca Mindscape Worker

This is the free Cloudflare Worker receiver for Alpecca Mindscape. It stores the
latest continuity snapshot in Workers KV and serves a small mobile page if the
local machine goes down.

It accepts the payload sent by local Alpecca:

- `POST /sync` stores the latest snapshot.
- `GET /snapshot` returns the full stored snapshot.
- `GET /state` returns a compact status summary.
- `GET /` opens the mobile Mindscape cloud page.

## Deploy

```powershell
cd C:\Users\Jason\Documents\GitHub\alpaccaai\deploy\mindscape-worker
npx wrangler kv namespace create MINDSCAPE_KV --json
```

Bind the returned KV namespace id into `wrangler.toml`:

```powershell
python ..\..\scripts\setup_mindscape_worker.py --kv-id "<namespace-id>" --print-next
```

You can also copy the full Wrangler JSON output and run
`python ..\..\scripts\setup_mindscape_worker.py --from-clipboard --print-next`.

Set the private sync token:

```powershell
npx wrangler secret put MINDSCAPE_TOKEN
```

Deploy:

```powershell
npx wrangler deploy
```

Cloudflare will print a URL like:

```text
https://alpecca-mindscape.<your-subdomain>.workers.dev
```

## Connect local Alpecca

Set local Alpecca to mirror into the Worker:

```powershell
$env:ALPECCA_MINDSCAPE_URL="https://alpecca-mindscape.<your-subdomain>.workers.dev/sync"
$env:ALPECCA_MINDSCAPE_TOKEN="the-same-token-you-put-in-cloudflare"
python server.py
```

Open local Mindscape and press **Sync Mindscape continuity**:

```text
http://127.0.0.1:8765/mindscape
```

Then test the cloud page:

```text
https://alpecca-mindscape.<your-subdomain>.workers.dev/
```

## Privacy

The Worker stores Alpecca's compact continuity snapshot: mood, current intent,
recent memory summaries, journal summaries, observations, proposals, and runtime
health. It does not receive raw screen images, webcam frames, audio, or local
files from the default snapshot.
