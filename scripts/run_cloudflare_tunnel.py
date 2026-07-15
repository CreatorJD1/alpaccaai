"""Run Alpecca's stable Cloudflare named tunnel."""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from alpecca import preview  # noqa: E402


def listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def start_server_if_needed(port: int) -> subprocess.Popen | None:
    if listening(port):
        return None
    proc = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=Path(__file__).resolve().parent.parent,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if listening(port):
            return proc
        time.sleep(0.5)
    raise SystemExit("Alpecca server did not start on port %s." % port)


def hostname_from_config(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("hostname:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return ""
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the configured stable Cloudflare tunnel.")
    parser.add_argument("--config", type=Path, default=config.CLOUDFLARE_CONFIG)
    parser.add_argument("--name", default=config.CLOUDFLARE_TUNNEL_NAME)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--no-server", action="store_true", help="Do not start server.py if port is closed.")
    args = parser.parse_args()

    exe = preview.find_cloudflared()
    if not exe:
        raise SystemExit("cloudflared was not found. Install with: winget install cloudflare.cloudflared")
    if not args.config.exists():
        raise SystemExit(
            f"Named tunnel config not found: {args.config}\n"
            "Run: python scripts\\setup_cloudflare_tunnel.py --hostname <your-hostname>"
        )

    server_proc = None if args.no_server else start_server_if_needed(args.port)
    public_url = preview.configured_public_url()
    if not public_url:
        hostname = hostname_from_config(args.config)
        if hostname:
            public_url = "https://" + hostname
    if public_url:
        preview.write_state(public_url, args.port, provider="cloudflare-named")
        print("Stable Alpecca link:")
        print(" ", preview.with_access_token(public_url.rstrip("/") + "/house-hq"))
        print()

    proc = subprocess.Popen([exe, "tunnel", "--config", str(args.config), "run", args.name])
    if public_url:
        for _ in range(40):
            if preview.health_check(public_url, route="/healthz", timeout=2.0):
                subprocess.run(
                    [sys.executable, "scripts\\publish_mobile_endpoint.py", "--url", public_url, "--kind", "named"],
                    cwd=Path(__file__).resolve().parent.parent,
                    check=False,
                )
                break
            time.sleep(0.5)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0
    finally:
        if server_proc is not None:
            server_proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
