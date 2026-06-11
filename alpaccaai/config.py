"""Configuration for alpaccaai.

Values are resolved from (in order of precedence): explicit constructor
arguments, environment variables, then built-in defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Default Claude model. Computer use requires a model that supports the
# computer_20251124 tool (Opus 4.8/4.7/4.6, Sonnet 4.6, Opus 4.5).
DEFAULT_MODEL = "claude-opus-4-8"

# Beta header required to enable the computer use tool.
COMPUTER_USE_BETA = "computer-use-2025-11-24"

# Recommended display size for general desktop tasks (see computer use docs).
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 800

# Safeguard against runaway agent loops / unexpected API cost.
DEFAULT_MAX_ITERATIONS = 20


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Config:
    """Runtime configuration for an alpaccaai session."""

    api_key: str | None = None
    model: str = DEFAULT_MODEL
    display_width: int = DEFAULT_WIDTH
    display_height: int = DEFAULT_HEIGHT
    display_number: int | None = None
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    max_tokens: int = 4096

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config from environment variables, falling back to defaults."""
        display_number = os.environ.get("ALPACCAAI_DISPLAY_NUMBER")
        return cls(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=os.environ.get("ALPACCAAI_MODEL", DEFAULT_MODEL),
            display_width=_env_int("ALPACCAAI_DISPLAY_WIDTH", DEFAULT_WIDTH),
            display_height=_env_int("ALPACCAAI_DISPLAY_HEIGHT", DEFAULT_HEIGHT),
            display_number=int(display_number) if display_number else None,
            max_iterations=_env_int("ALPACCAAI_MAX_ITERATIONS", DEFAULT_MAX_ITERATIONS),
            max_tokens=_env_int("ALPACCAAI_MAX_TOKENS", 4096),
        )
