"""Dry-run Cloudflare private desktop readiness and fencing tools."""

from .continuity import evaluate_desktop_lease
from .preflight import evaluate_preflight

__all__ = ["evaluate_desktop_lease", "evaluate_preflight"]
