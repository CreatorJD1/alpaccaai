---
name: alpacca-inbound
description: "Forward inbound messages to a local Alpacca companion at /channel/inbound"
metadata:
  { "openclaw": { "emoji": "🦙", "events": ["message:received"], "requires": { "bins": ["node"] } } }
---

# Alpacca inbound bridge

Forwards every `message:received` event to Alpacca's local
`POST /channel/inbound` endpoint and lets Alpacca's reply ride back on the
same conversation surface via `event.messages`. Outbound delivery to the
original channel is handled by OpenClaw itself when a hook pushes to
`event.messages`, so the bridge does not need to shell out to
`openclaw message send` from inside this hook.

## Install

Copy or symlink this directory into your OpenClaw managed-hooks dir:

```
ln -s "$PWD/integrations/openclaw-inbound-hook" ~/.openclaw/hooks/alpacca-inbound
openclaw hooks enable alpacca-inbound
```

## Configure

Two environment variables on the OpenClaw side:

| Var                    | Default                          | Notes                                      |
| ---------------------- | -------------------------------- | ------------------------------------------ |
| `ALPACCA_URL`          | `http://127.0.0.1:8765`          | Where Alpacca's server is listening        |
| `ALPACCA_TIMEOUT_MS`   | `15000`                          | Max wait for Alpacca's reply               |
