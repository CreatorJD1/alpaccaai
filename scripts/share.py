"""Serve Alpecca so your phone can reach her -- on your WiFi, or anywhere.

`python server.py` binds 127.0.0.1, which only the same computer can open. This
launcher binds the server to all interfaces and prints the two ways to reach her
from a phone:

  1. SAME WIFI -- open http://<your-LAN-IP>:<port> on the phone. Instant, private,
     never leaves your network. This is the recommended default.
  2. ANYWHERE -- with `--tunnel`, if `cloudflared` is installed, it opens a free
     Cloudflare quick tunnel and prints a public https URL (works over mobile
     data, supports the WebSocket the app uses). No account needed.

        winget install cloudflare.cloudflared      # or: brew install cloudflared
        python scripts/share.py --tunnel

PRIVACY: a public tunnel link is UNAUTHENTICATED -- anyone with it can chat with
her and see her memories. Keep ALPECCA_FILES off while sharing publicly, only hand
the link to yourself, and stop it (Ctrl-C) when done. The WiFi option keeps
everything on your own network and is the safer choice.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


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


def start_tunnel(port: int) -> None:
    """Open a Cloudflare quick tunnel and stream its public URL, if cloudflared is
    installed. Runs in a thread so the server can start alongside it."""
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
                    print("\n" + "=" * 56)
                    print("  PUBLIC LINK (open on your phone, works on mobile data):")
                    print("   ", url.strip())
                    print("=" * 56 + "\n")
    threading.Thread(target=pump, daemon=True).start()


def main() -> None:
    from config import PORT
    # Bind to every interface so other devices on the network can connect.
    os.environ["ALPECCA_SERVER_HOST"] = "0.0.0.0"
    ip = lan_ip()
    print("\nAlpecca is opening to your network.")
    print(f"  On this computer : http://127.0.0.1:{PORT}")
    print(f"  On your phone (same WiFi) : http://{ip}:{PORT}")
    if "--tunnel" in sys.argv[1:]:
        start_tunnel(PORT)
        time.sleep(1.0)   # give the tunnel a moment to print its URL first
    else:
        print("  For a link that works ANYWHERE: python scripts/share.py --tunnel")
    print()

    # Import after setting the host env so config picks up 0.0.0.0.
    import uvicorn
    from config import HOST
    import server  # noqa: F401  (registers the app)
    uvicorn.run(server.app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
