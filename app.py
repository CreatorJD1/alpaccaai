"""Alpecca as a real desktop app.

`python server.py` (or the browser) is the old way: a web page at a localhost
URL. This is the other way -- a native application window. It runs her FastAPI
server in-process (a background thread) and shows her UI in an OS-native webview
via pywebview, so there's no browser to open and no URL to copy.

The same server keeps running underneath, so this is also how she's reached from
*other* devices when you want that:

  - LOCAL (default):   just her window on this machine; nothing is exposed.
  - REMOTE (LAN):       set ALPECCA_REMOTE=1 -> the server binds to every network
                        interface so your phone / another PC can connect.
  - INTERNET (tunnel):  set ALPECCA_TUNNEL=cloudflare (or ngrok) -> a public URL
                        is opened through a tunnel binary.

The native window asks the loaded server module for a one-time loopback bootstrap
after startup. The launcher neither handles the protected authorization secret
nor places it in URLs or browser-visible storage.

Run:
    python app.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Launch is not consent for ambient capture or device control. Explicit caller
# values still win because config.py reads these variables after setdefault.
os.environ.setdefault("ALPECCA_COMPUTER_USE", "0")
os.environ.setdefault("ALPECCA_SIGHT", "0")    # periodic screen glimpses
os.environ.setdefault("ALPECCA_FACE", "0")     # webcam expression sense
os.environ.setdefault("ALPECCA_VOICE", "0")    # mic voice-tone sense
os.environ.setdefault("ALPECCA_APPS", "")      # explicit app allowlist only

import config  # noqa: E402  (after the env defaults above)
from alpecca import instance as instance_mod  # noqa: E402
from alpecca import preview as preview_mod  # noqa: E402

_tunnel_proc = None
_server_module = None
_server_module_ready = threading.Event()


def _credential_free_url(url: str) -> str:
    """Strip legacy credential parameters before displaying a public URL."""
    parsed = urllib.parse.urlsplit(url)
    query = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in {"token", "access_token", "authorization", "bootstrap"}
    ]
    return urllib.parse.urlunsplit(
        parsed._replace(query=urllib.parse.urlencode(query))
    )


def _serve() -> None:
    """Run the FastAPI server in this thread (bound per config -- localhost when
    private, 0.0.0.0 when ALPECCA_REMOTE=1)."""
    global _server_module
    import uvicorn
    import server as server_mod
    _server_module = server_mod
    _server_module_ready.set()
    uvicorn.run(server_mod.app, host=config.BIND_HOST, port=config.PORT,
                log_level="warning")


def _issue_local_bootstrap_url(path: str = "/", timeout: float = 5.0) -> str | None:
    """Bounded wait for the server module's one-time loopback bootstrap API."""
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() <= deadline:
        server_mod = _server_module
        if server_mod is not None:
            issue = getattr(server_mod, "issue_local_bootstrap_url", None)
            if callable(issue):
                try:
                    url = issue(path)
                except Exception:
                    url = None
                if isinstance(url, str) and url.strip():
                    return url.strip()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        _server_module_ready.wait(timeout=min(0.05, remaining))
        if _server_module_ready.is_set():
            time.sleep(min(0.05, remaining))
    return None


def _wait_until_up(url: str, timeout: float = 25.0) -> bool:
    """Poll the local server until it answers, so the window doesn't open onto a
    not-yet-listening port. 401 still means 'up' (the token gate is live)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except urllib.error.HTTPError:
            return True               # responding (e.g. 401) -> it's up
        except Exception:
            time.sleep(0.25)
    return False


def _start_tunnel(kind: str, port: int) -> None:
    """Open a public internet URL to the local server via a tunnel CLI. Best
    effort: if the binary isn't installed we say so and stay local. The token
    still guards every request, so the public URL alone can't reach her."""
    global _tunnel_proc
    if kind == "cloudflare":
        url, proc = preview_mod.ensure(port, reuse=True)
        if not url:
            print("[app] Cloudflare tunnel unavailable or not installed. Use:\n"
                  "      python scripts\\preview.py", file=sys.stderr)
            return
        _tunnel_proc = proc
        print(f"[app] Cloudflare preview: {_credential_free_url(url)}")
        print("[app] Reused the existing tunnel." if proc is None else "[app] Opened one tunnel to the existing Alpecca server.")
        return
    elif kind == "ngrok":
        exe = shutil.which("ngrok")
        if not exe:
            print("[app] ngrok not on PATH -- internet tunnel skipped "
                  "(https://ngrok.com/download).", file=sys.stderr)
            return
        # ngrok draws a TUI instead of printing a copyable line, so we don't
        # scrape its output -- we ask its local inspection API for the URL.
        _tunnel_proc = subprocess.Popen([exe, "http", str(port)])
        url = _ngrok_public_url()
        if url:
            # Mirror the cloudflare path: persist the URL so tools can discover
            # it, and print the clean shareable link.
            preview_mod.write_state(url, port, provider="ngrok")
            print(f"[app] ngrok preview: {_credential_free_url(url)}")
        else:
            print("[app] ngrok is running, but its public URL couldn't be read from "
                  "its inspection API -- check the ngrok window for the https link.",
                  file=sys.stderr)
        return
    else:
        print(f"[app] unknown ALPECCA_TUNNEL={kind!r} (expected cloudflare|ngrok|off).",
              file=sys.stderr)
        return


def _ngrok_public_url(timeout: float = 15.0) -> str | None:
    """Ask ngrok's local inspection API (port 4040) for the public https URL.

    ngrok takes a moment to establish the tunnel, so poll until it answers or
    ``timeout`` runs out. Best effort: any failure just returns ``None`` and the
    caller falls back to pointing at ngrok's own window."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels",
                                        timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for tunnel in data.get("tunnels", []):
                url = str(tunnel.get("public_url", ""))
                if url.startswith("https://"):
                    return url
        except Exception:
            pass                       # not listening yet, or no tunnel yet
        time.sleep(0.5)
    return None


def main() -> None:
    local_url = f"http://127.0.0.1:{config.PORT}/"
    existing = instance_mod.existing_server_url(config.PORT)
    if existing:
        print(f"[app] Alpecca is already awake at {existing}; reusing that mind.")
        print("[app] Use the already-open authenticated surface.")
        return
    else:
        threading.Thread(target=_serve, daemon=True).start()
        if not _wait_until_up(local_url):
            print("[app] the server didn't come up in time -- check the errors above.",
                  file=sys.stderr)
            return
    window_url = _issue_local_bootstrap_url()
    if not window_url:
        print("[app] local bootstrap unavailable; no window was opened.",
              file=sys.stderr)
        return

    if config.TUNNEL not in ("", "off", "none"):
        _start_tunnel(config.TUNNEL, config.PORT)

    try:
        import webview
    except Exception:
        print("[app] pywebview isn't installed -- opening her in your browser instead.\n"
              "      for the native app window:  python -m pip install pywebview",
              file=sys.stderr)
        import webbrowser
        webbrowser.open(window_url)
        try:
            while True:
                time.sleep(3600)       # keep the server thread alive
        except KeyboardInterrupt:
            return

    webview.create_window("Alpecca", window_url, width=1200, height=820,
                          min_size=(900, 640))
    webview.start()                    # blocks until the window is closed


if __name__ == "__main__":
    main()
