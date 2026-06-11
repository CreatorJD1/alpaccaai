"""App actions: Alpacca can interact with apps -- exactly the ones you hand her.

The security model is an allowlist and nothing else. ALPACCA_APPS names the
apps she may open ("spotify=C:\\path\\Spotify.exe;notes=notepad.exe"); those
names become an `open_app` tool the LLM can call mid-reply, and anything not
on the list is refused with a plain explanation she can relay. No shell
access, no arbitrary commands, no file writes -- if you didn't grant it, it
doesn't exist for her.

The tool round itself is wired in mind.py via Ollama's tool-calling API
(Qwen3 handles tools well). When the model or client can't do tools, the
whole layer silently disappears and she's conversation-only again -- the same
graceful-degradation contract as every sense.
"""
from __future__ import annotations

import subprocess
from typing import Optional

from config import Actions as ActionsCfg


def parse_apps(spec: str) -> dict[str, str]:
    """Parse "name=command;name2=command2" into an allowlist dict. Forgiving
    about whitespace and empty segments so a hand-typed env var just works."""
    apps: dict[str, str] = {}
    for part in (spec or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, command = part.partition("=")
        name, command = name.strip().lower(), command.strip()
        if name and command:
            apps[name] = command
    return apps


class Actuator:
    """Holds the allowlist and executes granted actions. One instance per
    CoreMind; `enabled` gates whether tools are offered to the LLM at all."""

    def __init__(self, apps: Optional[dict[str, str]] = None) -> None:
        self.apps = parse_apps(ActionsCfg.APPS_SPEC) if apps is None else dict(apps)

    @property
    def enabled(self) -> bool:
        return bool(self.apps)

    def describe(self) -> str:
        """One line for the system prompt so she knows what she's been given."""
        if not self.enabled:
            return ""
        return ("You can open these apps for the person when it genuinely helps, "
                "via the open_app tool: " + ", ".join(sorted(self.apps)) + ". "
                "Only open something when the moment calls for it, never to show off.")

    def tools_schema(self) -> list[dict]:
        """The Ollama tools list. Names are enumerated so the model can't even
        express an out-of-list request well-formedly."""
        if not self.enabled:
            return []
        return [{
            "type": "function",
            "function": {
                "name": "open_app",
                "description": "Open one of the applications the person has granted access to.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Which app to open.",
                            "enum": sorted(self.apps),
                        },
                    },
                    "required": ["name"],
                },
            },
        }]

    def execute(self, tool_name: str, args: dict) -> str:
        """Run one tool call, returning a short result string for the model.
        Every failure path returns words rather than raising -- the LLM relays
        the outcome to the person either way."""
        if tool_name != "open_app":
            return f"unknown tool: {tool_name}"
        name = str(args.get("name", "")).strip().lower()
        command = self.apps.get(name)
        if not command:
            granted = ", ".join(sorted(self.apps)) or "none"
            return f"'{name}' isn't on the access list (granted: {granted})"
        try:
            # The command string is owner-authored config, so shell=True is the
            # point here: it lets entries be paths, bare exe names, or commands
            # with arguments alike.
            subprocess.Popen(command, shell=True)
            return f"opened {name}"
        except Exception as exc:
            return f"couldn't open {name}: {exc}"
