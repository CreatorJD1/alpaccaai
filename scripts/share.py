"""Serve Alpecca so your phone can reach her -- on WiFi or through Cloudflare.

This launcher binds the local server to all interfaces and prints token-gated
links for desktop, LAN, and optional Cloudflare access. If a local Alpecca server
is already running, the tunnel points to that same instance instead of creating a
second mind.
"""
from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def lan_ip() -> str:
    """Best-effort local network IP for phones on the same WiFi."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()


def start_tunnel(port: int) -> None:
    """Open or reuse one Cloudflare preview tunnel to the local server."""
    from alpecca import preview as preview_mod

    url, proc = preview_mod.ensure(port, reuse=True)
    if not url:
        print("\n[tunnel] Cloudflare preview unavailable. Install cloudflared or run:")
        print("         python scripts\\preview.py\n")
        return

    print("\n" + "=" * 64)
    print("  PUBLIC LINK (same Alpecca instance, open on your phone):")
    print("   ", preview_mod.with_access_token(url.strip()))
    print("  ", "reused existing tunnel" if proc is None else "opened one tunnel to the existing server")
    print("  First open drops a 30-day cookie on that phone.")
    print("=" * 64 + "\n")


def main() -> None:
    os.environ["ALPECCA_SERVER_HOST"] = "0.0.0.0"

    from config import ACCESS_TOKEN, HOST, PORT
    from alpecca import instance as instance_mod

    ip = lan_ip()
    local = f"http://127.0.0.1:{PORT}/?token={ACCESS_TOKEN}"
    phone = f"http://{ip}:{PORT}/?token={ACCESS_TOKEN}"

    print("\nAlpecca is opening to your network (token-gated).")
    print(f"  On this computer          : {local}")
    print(f"  On your phone (same WiFi) : {phone}")
    print(f"  Access token              : {ACCESS_TOKEN}")

    if "--tunnel" in sys.argv[1:]:
        start_tunnel(PORT)
        time.sleep(1.0)
    else:
        print("  For a link that works ANYWHERE: python scripts/share.py --tunnel")
    print()

    existing = instance_mod.existing_server_url(PORT, token=ACCESS_TOKEN)
    if existing:
        print(f"Alpecca is already awake at {existing}; reusing the same mind instance.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    import uvicorn
    import server  # noqa: F401

    uvicorn.run(server.app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
