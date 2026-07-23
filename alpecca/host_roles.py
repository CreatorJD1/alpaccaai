"""Machine-role boundary for Alpecca's single authoritative runtime."""

from __future__ import annotations

import socket
from typing import Callable


COMPUTE_ONLY_HOSTS = frozenset({"jason_holyrog"})


class ComputeOnlyHostError(RuntimeError):
    """A dedicated worker host attempted to start an authoritative role."""


def is_compute_only_host(
    hostname: str | None = None,
    *,
    hostname_provider: Callable[[], str] = socket.gethostname,
) -> bool:
    observed = hostname if hostname is not None else hostname_provider()
    return str(observed or "").strip().casefold() in COMPUTE_ONLY_HOSTS


def require_primary_runtime_host(
    hostname: str | None = None,
    *,
    hostname_provider: Callable[[], str] = socket.gethostname,
) -> None:
    """Fail closed before CoreMind, Discord, or a speaking server starts."""

    observed = hostname if hostname is not None else hostname_provider()
    if is_compute_only_host(str(observed or "")):
        raise ComputeOnlyHostError(
            "Jason_HOLYROG is assigned to the non-speaking compute-worker role; "
            "the authoritative Alpecca runtime is refused on this host"
        )


__all__ = [
    "COMPUTE_ONLY_HOSTS",
    "ComputeOnlyHostError",
    "is_compute_only_host",
    "require_primary_runtime_host",
]
