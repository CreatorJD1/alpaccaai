"""Serve Alpecca so your phone can reach her -- on your WiFi, or anywhere.

`python server.py` binds 127.0.0.1, which only the same computer can open. This
launcher binds the server to all interfaces and prints the two ways to reach her
from a phone:

  1. SAME WIFI -- open the printed http://<your-LAN-IP>:<port> link on the phone.
     Instant, private, never leaves your network.
  2. ANYWHERE -- with `--tunnel`, if `cloudflared` is installed, it opens a free
     Cloudflare quick tunnel and prints a public https URL (works over mobile
     data, supports the WebSocket the app uses). No account needed.

        winget install cloudflare.cloudflared      # or: brew install cloudflared
        python scripts/share.py --tunnel

Both links are ALWAYS gated by her access token (the same system app.py and the
server's _auth_gate use): if ALPECCA_ACCESS_TOKEN isn't set, one is minted for
the run and baked into the printed ?token= links -- opening a link once drops a
30-day cookie, so it's one tap on the phone and locked to everyone else. Still:
only hand the link to yourself, keep ALPECCA_FILES off while a tunnel is up, and
stop it (Ctrl-C) when done.
"""
from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def ensure_token() -> str:
    """The shared secret every remote client must present -- the same rule
    app.py applies: use ALPECCA_ACCESS_TOKEN if set, mint one otherwise. Must
    run BEFORE importing server, which reads the token at import time."""
    tok = os.environ.get("ALPECCA_ACCESS_TOKEN", "")
    if not tok:
        tok = secrets.token_urlsafe(18)
        os.environ["ALPECCA_ACCESS_TOKEN"] = tok
    return tok


def lan_ip() -> str:
    """Best-effort local network IP (the address a phone on the same WiFi uses)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))      # no packets sent; just picks the route's IP
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def start_tunnel(port: int, token: str) -> None:
    """Open a Cloudflare quick tunnel and stream its public URL -- with the
    access token baked in, so the printed link is tap-and-done while the raw
    URL stays a locked door. Runs in a thread so the server starts alongside."""
    exe = "cloudflared"
    try:
        proc = subprocess.Popen(
            [exe, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except FileNotFoundError:
        print("\n[tunnel] cloudflared isn't installed. Install it, or use the WiFi "
              "link below.\n         winget install cloudflare.cloudflared   "
              "(Windows)   |   brew install cloudflared   (macOS)\n")
        return

    def pump():
        for line in proc.stdout:
            if "trycloudflare.com" in line:
                url = next((tok for tok in line.split() if "trycloudflare.com" in tok), "")
                if url:
                    print("\n" + "=" * 64)
                    print("  PUBLIC LINK (open on your phone, works on mobile data):")
                    print(f"    {url.strip()}/?token={token}")
                    print("  First open drops a 30-day cookie; after that the bare")
                    print("  URL works on that phone. Without the token: a login page.")
                    print("=" * 64 + "\n")
    threading.Thread(target=pump, daemon=True).start()


def main() -> None:
    # Env FIRST, then any config import: config reads the environment once, at
    # import time, and Python caches the module -- an import before these lines
    # would freeze the gate open and the bind on localhost. (The original
    # version of this script had exactly that bug.)
    os.environ["ALPECCA_SERVER_HOST"] = "0.0.0.0"
    token = ensure_token()
    from config import PORT
    ip = lan_ip()
    print("\nAlpecca is opening to your network (token-gated).")
    print(f"  On this computer          : http://127.0.0.1:{PORT}/?token={token}")
    print(f"  On your phone (same WiFi) : http://{ip}:{PORT}/?token={token}")
    print(f"  Access token              : {token}")
    if "--tunnel" in sys.argv[1:]:
        start_tunnel(PORT, token)
        time.sleep(1.0)   # give the tunnel a moment to print its URL first
    else:
        print("  For a link that works ANYWHERE: python scripts/share.py --tunnel")
    print()

    # Import after setting the host + token env so config picks both up.
    import uvicorn
    from config import HOST
    import server  # noqa: F401  (registers the app)
    uvicorn.run(server.app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
