"""Run Alpecca's Discord bridge.

Loads her bot token from the git-ignored secret
(`data/secrets/alpecca_discord.env` -> DISCORD_BOT_TOKEN) or the environment,
then connects her as a proper Discord bot. Her backend (`server.py`) must be
running so `/channel/inbound` is reachable.

    python scripts/run_discord_bridge.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECRET = ROOT / "data" / "secrets" / "alpecca_discord.env"


def _load_secret() -> None:
    if not SECRET.exists():
        return
    for line in SECRET.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_LOCK_PORT = int(os.environ.get("ALPECCA_DISCORD_LOCK_PORT", "8779"))
_lock_sock = None


def _acquire_single_instance_lock() -> bool:
    """Only one bridge may run at a time (two would double-reply). Bind a local
    port as the lock; if it's taken, another bridge is already up. Returns True
    if we got the lock."""
    global _lock_sock
    import socket
    _lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock_sock.bind(("127.0.0.1", _LOCK_PORT))
        _lock_sock.listen(1)
        return True
    except OSError:
        _lock_sock = None
        return False


def main() -> int:
    _load_secret()
    if not _acquire_single_instance_lock():
        print("Another Alpecca Discord bridge is already running; not starting a "
              "second (it would double-reply).", file=sys.stderr)
        return 0
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        print("No DISCORD_BOT_TOKEN. Put it in data/secrets/alpecca_discord.env "
              "or export it.", file=sys.stderr)
        return 2

    import discord
    from alpecca.discord_bridge import build_client

    client = build_client()
    try:
        client.run(token)
    except discord.PrivilegedIntentsRequired:
        print("Message Content Intent is OFF. Enable it: Developer Portal -> your "
              "app -> Bot -> Privileged Gateway Intents -> Message Content Intent.",
              file=sys.stderr)
        return 3
    except discord.LoginFailure:
        print("Login failed: the bot token is invalid or was reset.", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
