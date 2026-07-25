# Alpecca ROG Worker — MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes
Alpecca's compute-only **Jason_HOLYROG** worker as tools. It wraps
`alpecca.rog_worker_client.RogWorkerClient`, so an MCP client (Claude Desktop /
Cowork, or any MCP host) can drive the worker's authenticated jobs **without
ever handling the HMAC secret** — the secret, URL, TLS CA, and timeouts are read
from the environment by the underlying client.

The worker is compute-only: it never speaks, remembers, or holds Alpecca's
identity. This server preserves that — it only dispatches bounded jobs and
returns their results.

## Tools

| Tool | What it does | Read-only |
|------|--------------|-----------|
| `rog_health` | Worker readiness: reasoning / vision / blender, vision model, role | ✅ |
| `rog_hyfuser_health` | Readiness of the optional seven-head HyFusER shadow model | ✅ |
| `rog_reason` | One bounded reasoning call (visible answer only, no chain-of-thought) | ✅ |
| `rog_describe_vision` | Describe a PNG/JPEG/WebP image via the private vision path | ✅ |
| `rog_render_blender` | Render one frame of an approved `.blend` project | ❌ (writes an artifact) |
| `rog_score_soul` | Seven advisory HyFusER perspective scores (shadow-only) | ✅ |
| `rog_voice_status` | Health of the HOLYROG XTTS voice server (separate 8790 service) | ✅ |
| `rog_synthesize_voice` | Synthesize speech (XTTS) and write a WAV file | ❌ (writes a file) |

> **Note:** `rog_voice_status` / `rog_synthesize_voice` target the separate
> HOLYROG voice offload service (`scripts/run_holyrog_voice_server.py`, port
> 8790), not the ROG compute worker. They use their own env vars (below). If the
> voice server is down, the primary falls back to local Kokoro.

Call `rog_health` first — it tells you which capabilities are live so you don't
dispatch a job to one that's down (e.g. `vision_ready=false`).

## Requirements

- Python ≥ 3.11
- The `alpaccaai` repo importable (this server imports `alpecca.rog_worker_client`)
- `pip install mcp>=1.2 pydantic>=2 pillow>=10` (Pillow is only needed for the vision tool)

## Configuration (environment)

The underlying client reads these — this server never takes credentials as tool
arguments:

| Variable | Purpose |
|----------|---------|
| `ALPECCA_ROG_WORKER_URL` | Worker base URL, e.g. `https://jason-holyrog.tailda0108.ts.net:8788` |
| `ALPECCA_ROG_WORKER_SECRET` | HMAC secret (or store it in the Windows credential manager under the configured target) |
| `ALPECCA_ROG_WORKER_CA_CERT` | Path to the worker's TLS CA/public cert (required for non-loopback HTTPS) |
| `ALPECCA_ROG_WORKER_MODEL` / `..._MODELS` | Reasoning model + allowlist |
| `ALPECCA_ROG_WORKER_VISION_MODEL` | Opt-in vision model tag (leave unset to keep vision fail-closed) |
| `ALPECCA_HOLYROG_VOICE_URL` | XTTS voice server base URL, e.g. `https://jason-holyrog.tailda0108.ts.net:8790` (voice tools only) |
| `ALPECCA_HOLYROG_VOICE_SECRET` | Voice server auth token (voice tools only) |
| `ALPECCA_REPO_ROOT` | Optional: explicit path to the `alpaccaai` repo if not auto-detected |

## Run

Over stdio (the intended transport — run it on RygenART, where the secret and
tailnet route live):

```bash
# from the repo root, or with ALPECCA_REPO_ROOT set:
python -m alpecca_rog_mcp.server
# or, after `pip install -e mcp/rog_worker`:
alpecca-rog-mcp
```

## MCP client config

Example entry for a Claude Desktop / Cowork `mcpServers` config:

```json
{
  "mcpServers": {
    "alpecca-rog": {
      "command": "python",
      "args": ["-m", "alpecca_rog_mcp.server"],
      "env": {
        "ALPECCA_REPO_ROOT": "C:\\Users\\Jason\\Documents\\GitHub\\alpaccaai",
        "PYTHONPATH": "C:\\Users\\Jason\\Documents\\GitHub\\alpaccaai;C:\\Users\\Jason\\Documents\\GitHub\\alpaccaai\\mcp\\rog_worker",
        "ALPECCA_ROG_WORKER_URL": "https://jason-holyrog.tailda0108.ts.net:8788",
        "ALPECCA_ROG_WORKER_CA_CERT": "C:\\Users\\Jason\\AppData\\Local\\Alpecca\\rog-worker\\tls\\jason-holyrog.crt"
      }
    }
  }
}
```

The HMAC secret is intentionally **not** in the config above — set
`ALPECCA_ROG_WORKER_SECRET` in a secure environment, or rely on the Windows
credential store the client already reads.

## Testing

Network-free smoke tests (inject a fake client, verify registration, dispatch,
result mapping, and error translation):

```bash
cd mcp/rog_worker
PYTHONPATH="<repo-root>:$PWD" python -m pytest -q tests/test_server_smoke.py
```

Interactive inspection with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector python -m alpecca_rog_mcp.server
```

## A note on formal evaluations

The MCP-builder eval format expects read-only questions with **single, stable,
verifiable** answers over a queryable dataset. This worker is a **stateful
inference** service — reasoning and vision outputs are non-deterministic, and
health reflects live machine state — so a fixed-answer eval suite would not be
meaningful or stable. The `tests/` smoke suite is the deterministic verification
instead. Once a live worker is reachable, useful manual checks are: `rog_health`
returns `role="compute-only"` and the expected `vision_ready`; `rog_reason`
returns non-empty visible text with no `thinking` field; and an unreachable
worker surfaces the actionable "open TCP 8788 / start the ROG Compute Server"
error rather than a raw stack trace.

## Security

- The server never accepts, logs, or returns the HMAC secret or TLS private key.
- It preserves the worker's compute-only contract: no speaking, memory, or state
  mutation is exposed. `rog_score_soul` is advisory and shadow-only.
- All client errors are mapped to actionable messages (auth, unreachable,
  firewall/port, config) with no credential leakage.
