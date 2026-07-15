"""Attach a phone relay to the one already-running Alpecca instance.

This tool never starts the backend. The supported launcher owns the atomic
instance lock and CoreMind construction; this process only verifies the exact
local health identity and optionally opens a credential-free HTTPS relay.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TUNNEL_PROCS = []
_LOCALTUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.loca\.lt")


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


def _start_https_fallback(port: int) -> tuple[str | None, subprocess.Popen | None]:
    """Open a provider-neutral HTTPS fallback when Cloudflare is unavailable."""
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        return None, None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0
    proc = subprocess.Popen(
        [npx, "--yes", "localtunnel", "--port", str(port)],
        cwd=Path(__file__).resolve().parent.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=flags,
    )
    lines: queue.Queue[str] = queue.Queue()

    def pump() -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            lines.put(line)

    threading.Thread(target=pump, daemon=True, name="alpecca-localtunnel-output").start()
    deadline = time.monotonic() + 35.0
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            line = lines.get(timeout=0.5)
        except queue.Empty:
            continue
        match = _LOCALTUNNEL_URL.search(line)
        if match:
            return match.group(0), proc
    proc.terminate()
    return None, None


def start_tunnel(port: int) -> bool:
    """Open a validated HTTPS tunnel to the one running Alpecca instance."""
    from alpecca import preview as preview_mod

    url, proc = preview_mod.ensure(port, reuse=True)
    if proc is not None:
        TUNNEL_PROCS.append(proc)
    if not url:
        print("[tunnel] Cloudflare quick tunnel attempt 1 failed; retrying...")

    for attempt in range(2, 4):
        if url:
            break
        time.sleep(4.0)
        url, proc = preview_mod.ensure(port, reuse=False)
        if proc is not None:
            TUNNEL_PROCS.append(proc)
        if url:
            break
        print(f"[tunnel] Cloudflare quick tunnel attempt {attempt} failed; retrying...")

    if not url:
        print("[tunnel] Cloudflare is unavailable; trying the HTTPS fallback...")
        url, proc = _start_https_fallback(port)
        if proc is not None:
            TUNNEL_PROCS.append(proc)
        if url:
            preview_mod.write_state(url, port, provider="localtunnel")
        else:
            print("\n[tunnel] No HTTPS phone relay could be opened.\n")
            return False

    # The full-stack launcher acquires the cross-host singleton lease before a
    # tunnel hostname exists. Publish the discovered hostname only after the
    # authority confirms that this machine still owns the exact active fence.
    # A stale relay process therefore cannot replace the endpoint of a newer
    # local or cloud runtime.
    try:
        from alpecca.continuity_lease import client_from_env

        continuity = client_from_env(role="local-primary")
        if continuity is not None:
            continuity.publish_active_endpoint(url)
            print("  Continuity endpoint updated under the active local fence.")
    except Exception as exc:
        print(f"  Continuity endpoint update failed: {type(exc).__name__}")

    try:
        subprocess.run(
            [
                sys.executable,
                "scripts\\publish_mobile_endpoint.py",
                "--url", url,
                "--kind", "quick",
            ],
            cwd=Path(__file__).resolve().parent.parent,
            check=True,
        )
        print("  Mobile app discovery record updated.")
    except Exception as exc:
        print(f"  Mobile discovery update failed: {type(exc).__name__}")

    print("\n" + "=" * 64)
    print("  PUBLIC LINK (same Alpecca instance, open on your phone):")
    print("   ", preview_mod.with_access_token(url.strip()))
    print("  ", "reused existing tunnel" if proc is None else "opened one tunnel to the existing server")
    print("  First remote open enrolls that browser; later opens reuse its HttpOnly trust cookie.")
    print("=" * 64 + "\n")
    return True


def main() -> int:
    from config import PORT
    from alpecca import instance as instance_mod

    existing = instance_mod.existing_server_url(PORT)
    if not existing:
        print(
            "No verified Alpecca CoreMind is running on the local port. "
            "Start it with START_HERE.bat or python scripts\\run_full.py, "
            "then run this relay again.",
            file=sys.stderr,
        )
        return 2

    ip = lan_ip()
    local = f"http://127.0.0.1:{PORT}/"
    phone = f"http://{ip}:{PORT}/"

    print("\nAlpecca phone access is attaching to the existing instance.")
    print(f"  Verified local instance   : {existing}")
    print(f"  Local browser             : {local}")
    print(f"  LAN address (if enabled)  : {phone}")
    print("  Remote trusted-device enrollment requires HTTPS; LAN HTTP is not offered.")
    print("  Credentials are never placed in URLs.")

    if "--tunnel" in sys.argv[1:]:
        print("  Opening a relay to this verified instance.")
        if not start_tunnel(PORT):
            return 1
    else:
        print("  For the secure phone link: python scripts/share.py --tunnel")
    print()

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
