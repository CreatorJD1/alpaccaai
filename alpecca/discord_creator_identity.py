"""Private binding between CreatorJD's Discord account and creator authority."""
from __future__ import annotations

import hmac
import os
from pathlib import Path

from config import HOME


_BINDING_FILE = "alpecca_discord_creator_id"


def _canonical_actor_id(value: object) -> str:
    actor_id = str(value or "").strip()
    if (
        not actor_id.isdecimal()
        or actor_id.startswith("0")
        or len(actor_id) > 20
        or int(actor_id) > (2**64 - 1)
    ):
        raise ValueError("Discord creator id must be a canonical snowflake")
    return actor_id


def binding_path(home: Path = HOME) -> Path:
    return Path(home) / "secrets" / _BINDING_FILE


def remember_creator_actor_id(actor_id: object, home: Path = HOME) -> str:
    """Persist the ID resolved by the locally configured bridge allowlist."""
    canonical = _canonical_actor_id(actor_id)
    path = binding_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(canonical + "\n", encoding="ascii")
    temporary.replace(path)
    return canonical


def configured_creator_actor_ids(home: Path = HOME) -> tuple[str, ...]:
    candidates: list[str] = []
    for name in ("ALPECCA_DISCORD_CREATOR_ID", "ALPECCA_DISCORD_DM_ALLOW"):
        for value in os.environ.get(name, "").split(","):
            value = value.strip()
            if value.isdecimal():
                candidates.append(value)
    path = binding_path(home)
    try:
        candidates.append(path.read_text(encoding="ascii").strip())
    except (OSError, UnicodeError):
        pass
    valid: list[str] = []
    for candidate in candidates:
        try:
            canonical = _canonical_actor_id(candidate)
        except ValueError:
            continue
        if canonical not in valid:
            valid.append(canonical)
    return tuple(valid)


def is_creator_actor_id(actor_id: object, home: Path = HOME) -> bool:
    try:
        candidate = _canonical_actor_id(actor_id)
    except ValueError:
        return False
    return any(
        hmac.compare_digest(candidate, expected)
        for expected in configured_creator_actor_ids(home)
    )
