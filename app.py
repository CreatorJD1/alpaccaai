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

Remote and tunnel access are ALWAYS gated by a secret token. If you didn't set
ALPECCA_ACCESS_TOKEN, Alpecca keeps one stable local token in data/access_token.txt
and reuses it for future launches. Her senses, memory and brain never leave this
machine -- only the chat travels.

Run:
    python app.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Senses on by default -- launching the desktop app is the owner saying "yes,
# all of it" (mirrors scripts/run_full.py). Anything already in your env wins,
# and config.py reads every ALPECCA_* var at import time, so set these FIRST.
os.environ.setdefault("ALPECCA_SIGHT", "1")    # periodic screen glimpses
os.environ.setdefault("ALPECCA_FACE", "1")     # webcam expression sense
os.environ.setdefault("ALPECCA_VOICE", "1")    # mic voice-tone sense
os.environ.setdefault(
    "ALPECCA_APPS",
    "notepad=notepad.exe;calculator=calc.exe;paint=mspaint.exe;files=explorer.exe",
)

import config  # noqa: E402  (after the env defaults above)
from alpecca import instance as instance_mod  # noqa: E402
from alpecca import preview as preview_mod  # noqa: E402

_tunnel_proc = None


def _ensure_token() -> None:
    """Remote/tunnel launches must be behind Alpecca's persistent token. Must run
    BEFORE server is imported, since server.py binds the token at import time."""
    remote = config.REMOTE_ACCESS or config.TUNNEL not in ("", "off", "none")
    if remote:
        os.environ["ALPECCA_ACCESS_TOKEN"] = config.ACCESS_TOKEN
        print("[app] remote access is on -- using Alpecca's persistent access token.")


def _serve() -> None:
    """Run the FastAPI server in this thread (bound per config -- localhost when
    private, 0.0.0.0 when ALPECCA_REMOTE=1)."""
    import uvicorn
    from server import app  # imported here so the token env is already set
    uvicorn.run(app, host=config.BIND_HOST, port=config.PORT, log_level="warning")


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
        print(f"[app] Cloudflare preview: {preview_mod.with_access_token(url)}")
        print("[app] Reused the existing tunnel." if proc is None else "[app] Opened one tunnel to the existing Alpecca server.")
        return
    elif kind == "ngrok":
        exe = shutil.which("ngrok")
        if not exe:
            print("[app] ngrok not on PATH -- internet tunnel skipped "
                  "(https://ngrok.com/download).", file=sys.stderr)
            return
        cmd = [exe, "http", str(port)]
    else:
        print(f"[app] unknown ALPECCA_TUNNEL={kind!r} (expected cloudflare|ngrok|off).",
              file=sys.stderr)
        return
    print(f"[app] opening {kind} tunnel -- watch its output for the public URL, "
          f"then append ?token=<your token> to it.")
    # The tunnel CLI prints its public URL to its own stdout/stderr (left
    # inheriting this console), so you can copy it from here.
    subprocess.Popen(cmd)


def main() -> None:
    _ensure_token()
    local_url = f"http://127.0.0.1:{config.PORT}/"
    existing = instance_mod.existing_server_url(config.PORT, token=config.ACCESS_TOKEN)
    if existing:
        print(f"[app] Alpecca is already awake at {existing}; reusing that mind.")
    else:
        threading.Thread(target=_serve, daemon=True).start()
        if not _wait_until_up(local_url):
            print("[app] the server didn't come up in time -- check the errors above.",
                  file=sys.stderr)
    # The window authenticates itself with the token (when one is set) so the
    # local webview isn't blocked by its own gate.
    window_url = local_url + (f"?token={config.ACCESS_TOKEN}" if config.ACCESS_TOKEN else "")

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
