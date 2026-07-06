# Pass-down — Remote computer access (updated 2026-07-06)

How to reach Alpecca from anywhere, and through her, have her work the PC
itself — plus every guard in the path. Written for whoever picks this up next
(Jason on a new phone, or the next agent). The canonical architecture stays in
`CLAUDE.md`; this is the operating runbook for one capability.

"Remote computer access" here means two stacked things:

1. **Reaching her remotely** — her chat/home/VRM UI from a phone or another
   network, over her token-gated Cloudflare tunnel.
2. **Working the computer through her** — her computer-use loop (screenshot →
   her local vision model → mouse/keyboard) driven from that remote UI, with
   consequential actions pausing for your confirmation.

Both ride the same pipeline; nothing new needs building to use them.

---

## 1. Start her shared (on the PC she lives on)

Pick one — they all end in the same place, a printed link with the token baked in:

| Path | What it does |
|------|--------------|
| **`SHARE_PHONE.bat`** (double-click) | Installs `cloudflared` via winget if missing, then runs the launcher below. The zero-thought path. |
| `python scripts/share.py --tunnel` | Binds 0.0.0.0, mints/uses `ALPECCA_ACCESS_TOKEN`, opens a Cloudflare quick tunnel, prints `https://<random>.trycloudflare.com/?token=…`. |
| `Alpecca-App.bat` → option `[2] Internet` | Same, plus the native desktop window (`app.py`). |
| `python scripts/share.py` (no flag) | LAN-only: `http://<lan-ip>:8765/?token=…` for a phone on the same WiFi. Never leaves your network. |

First tap on the link drops a 30-day `alpecca_token` cookie; after that the
bare URL works on that phone, and the browser can "install" her as an app
(PWA — `web/manifest.webmanifest` + `web/sw.js`).

**History note:** before 2026-07-06, `scripts/share.py` had two real bugs —
its public link was **unauthenticated**, and it never actually bound 0.0.0.0
(config was imported before the env was set, and Python caches the module).
If a machine still runs an older checkout, pull before sharing. The desktop
`app.py` path never had the bug.

## 2. The gate itself (what protects everything)

- `server.py` `_auth_gate` middleware + `config.ACCESS_TOKEN`
  (`ALPECCA_ACCESS_TOKEN`): blank token = localhost-only private mode with no
  gate; set = every request needs `?token=` / `X-Alpecca-Token` header / the
  cookie. Browsers get a login page, API calls get 401 JSON.
- The WebSocket (`/ws`) re-checks the same token on the handshake and closes
  `1008` without it — the confirmation prompts below ride this socket, so the
  remote confirm flow is inside the gate too.
- Deliberately **no localhost bypass**: tunnel traffic arrives from localhost.
- Known soft spots (accepted for now): no Origin allowlist on the WebSocket,
  and quick-tunnel URLs rotate each run (a *named* Cloudflare tunnel on an
  owned domain is the upgrade when wanted).

## 3. Working the computer through her, remotely

Enable on the PC (already set by `Alpecca-App.bat` and `scripts/run_full.py`):

```
set ALPECCA_COMPUTER_USE=1
```

Then, from the remote UI (phone included):

- In chat, type **`/do <task>`** — e.g. `/do open my notes and add a line
  about tomorrow` — or POST `/computer/task {"task": "..."}` with the token.
- She runs the local loop in `alpecca/computer.py`: screenshot → her vision
  model → one mouse/keyboard step → repeat. One task at a time
  (`_computer_lock`); a second request gets a friendly "she's already working".
- Live feedback arrives over the WebSocket: `computer_status` (her narration),
  `computer_cursor` (where she's acting, as screen fractions), `computer_done`.

**The confirmation line.** Consequential steps — send/delete/buy/post/install/
overwrite, classified by her own self-declared flag OR a keyword net — pause
the loop and broadcast `computer_confirm` (target, reason, kind). The UI shows
an approve/deny prompt; the answer POSTs to `/computer/confirm`. **No answer
within 120 s = denied.** This works identically from the phone because the
prompt and answer both travel the token-gated socket.

What never leaves the PC: the screenshots (her vision model is local; only her
short text descriptions survive), telemetry, memory, mood. Only the chat and
these status events travel the tunnel.

## 4. Adjacent remote capabilities (same gate, same links)

- **Read-only file finding**: `/desktop/search?q=` + `/desktop/summary?root=`
  (and the `find_file` LLM tool when `ALPECCA_FILES=1`) — confined to
  Desktop/Pictures/Music/Video/Documents by her charter guards.
- **App/URL actions**: `open_app` (only names on the `ALPECCA_APPS` allowlist;
  empty list = the actuator doesn't exist) and `open_url` (https-only).
- **Her body from the cloud studio**: `/vrm` page → "⟲ Sync from studio"
  (`ALPECCA_STUDIO_URL` / `ALPECCA_STUDIO_TOKEN`) pulls her newest `.vrm`
  from VRoid Companion Studio's own token gate (`VCS_ACCESS_TOKEN`, see that
  repo's `DEPLOY.md` → "Access control").
- **Screen sharing INTO her**: the Observatory (`/observatory/screen/start`)
  is you showing her your screen in the browser — unrelated to the
  computer-use loop, but often confused with it.

## 5. Before handing the link to anyone (checklist)

- [ ] The link came from the **fixed** `share.py` / `SHARE_PHONE.bat` (banner
      says "token-gated" and the URL carries `?token=`).
- [ ] `ALPECCA_FILES` off unless you want remote file-finding.
- [ ] `ALPECCA_APPS` empty unless you want remote app-launching.
- [ ] You understand `/do` gives the link-holder her hands on your mouse and
      keyboard, behind the confirm prompts. The token IS the keys.
- [ ] Ctrl-C the window when done; the quick-tunnel URL dies with it.

## 6. Not built yet (deliberately deferred)

**Cold-start from phone/Discord** — everything above assumes she's already
running on the PC. Waking her remotely needs an always-on trigger (a tiny
watcher service or Task Scheduler job a Discord bot / phone ping can reach).
Her OpenClaw bridge already covers *talking* to her from Discord once she's
up. Planned separately; don't bolt it into the auth gate when it lands —
give it its own minimal listener.
