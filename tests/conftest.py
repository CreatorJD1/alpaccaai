"""Repository-wide test isolation from a configured live continuity lease."""

from __future__ import annotations

import os


# Test processes are never continuity owners. Dedicated fence tests explicitly
# remove this flag in their subprocess environment before importing server.py.
os.environ.setdefault("ALPECCA_CONTINUITY_OFFLINE_ISOLATED", "1")
