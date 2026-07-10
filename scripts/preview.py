"""Open (or reuse) a Cloudflare preview of the running Alpecca server and print
its public URL -- the preview system.

Unlike `scripts/share.py` (which binds the server itself and lets the URL scroll
by), this assumes the server is already running on its port and focuses on the
ONE job of a preview system: get a public URL, capture it where tools can read
it (`data/preview_url.txt`), and keep it alive.

    python scripts/preview.py            # reuse a healthy tunnel, else open one
    python scripts/preview.py --no-reuse # always open a fresh tunnel
    python scripts/preview.py --once     # print the current URL and exit
    python scripts/preview.py --port 8765

The captured URL is written to `<data>/preview.json` and `<data>/preview_url.txt`
so the UI, a test, or another agent can answer "what's the public preview URL?"
without scraping a console. Stop a tunnel this script owns with Ctrl-C.

PRIVACY: quick-tunnel URLs do not carry credentials. A remote browser must be
enrolled and then presents a signed HttpOnly trusted-device cookie. Still treat
the tunnel URL as private and stop it when the preview is finished.
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PORT  # noqa: E402
from alpecca import preview  # noqa: E402


def _server_listening(port: int, host: str = "127.0.0.1") -> bool:
    """Quick check that something is serving on the local port we tunnel to."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.6)
        return sock.connect_ex((host, port)) == 0


def main() -> int:
    argv = sys.argv[1:]
    port = PORT
    for i, arg in enumerate(argv):
        if arg == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])

    if not _server_listening(port):
        print(f"[preview] nothing is listening on 127.0.0.1:{port}. Start Alpecca "
              f"first (python server.py  or  python scripts/run_full.py), then "
              f"re-run this.", file=sys.stderr)
        # Still continue: the tunnel can come up and wait for the server.
    return preview._cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
