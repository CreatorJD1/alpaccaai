"""Run Alpecca's Discord bridge.

Loads her bot token from the git-ignored secret
(`data/secrets/alpecca_discord.env` -> DISCORD_BOT_TOKEN) or the environment,
then connects her as a proper Discord bot. Her backend (`server.py`) must be
running so `/channel/discord` is reachable.

    python scripts/run_discord_bridge.py
    python scripts/run_discord_bridge.py --media-readiness
    python scripts/run_discord_bridge.py --voice-readiness
"""
from __future__ import annotations

import json
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


def _media_enabled() -> bool:
    return os.environ.get("ALPECCA_DISCORD_MEDIA", "0").strip().lower() not in {
        "", "0", "false", "no", "off",
    }


def _print_media_readiness() -> None:
    from alpecca import discord_media

    print(
        json.dumps(
            discord_media.media_readiness(media_enabled=_media_enabled()),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _print_voice_readiness() -> None:
    from alpecca.discord_bridge import voice_readiness

    print(
        json.dumps(
            voice_readiness(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def main(argv: list[str] | None = None) -> int:
    # The secret/env loader uses setdefault, so an explicit process value wins
    # over the local file and an explicit false value remains a muted-media
    # override. Load it before selecting the normal direct-launch default.
    _load_secret()
    os.environ.setdefault("ALPECCA_DISCORD_MEDIA", "1")
    # Keep direct bridge launches aligned with the full-stack launcher and
    # START_HERE.bat. These flags govern only the creator-approved Discord
    # voice room; an explicit false value remains an opt-out.
    os.environ.setdefault("ALPECCA_DISCORD_VOICE", "1")
    os.environ.setdefault("ALPECCA_DISCORD_VOICE_RECEIVE", "1")
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--media-readiness"]:
        _print_media_readiness()
        return 0
    if args == ["--voice-readiness"]:
        _print_voice_readiness()
        return 0
    if args:
        print(
            "Usage: python scripts/run_discord_bridge.py "
            "[--media-readiness|--voice-readiness]",
            file=sys.stderr,
        )
        return 2

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
