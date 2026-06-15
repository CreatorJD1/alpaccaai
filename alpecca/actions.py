"""App actions: Alpecca can interact with apps -- exactly the ones you hand her.

The security model is an allowlist and nothing else. ALPECCA_APPS names the
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
from config import Files as FilesCfg


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
        # She has *some* reach if she's been granted apps, or if her file room is
        # on (which lets her find files for the person -- read-only).
        return bool(self.apps) or FilesCfg.ENABLED

    def describe(self) -> str:
        """One line for the system prompt so she knows what she's been given."""
        bits = []
        if self.apps:
            bits.append("open one of the granted apps (open_app: "
                        + ", ".join(sorted(self.apps)) +
                        ") or open an https website in their browser (open_url)")
        if FilesCfg.ENABLED:
            bits.append("find a file by name in their Desktop/Pictures/Music/Video/"
                        "Documents (find_file) -- read-only, you can never delete")
        if not bits:
            return ""
        return ("You can act on this computer when it genuinely helps: "
                + "; ".join(bits) + ". Only act when the moment calls for it.")

    def tools_schema(self) -> list[dict]:
        """The Ollama tools list. App names are enumerated so the model can't
        even express an out-of-list request well-formedly; URLs are free-form but
        execute() enforces https; find_file is read-only and charter-confined to
        her allowed rooms. Only tools she's actually been granted are offered."""
        tools: list[dict] = []
        if self.apps:
            tools.append({
                "type": "function",
                "function": {
                    "name": "open_app",
                    "description": "Open one of the applications the person has granted access to.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Which app to open.",
                                     "enum": sorted(self.apps)},
                        },
                        "required": ["name"],
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "open_url",
                    "description": "Open an https website in the person's default browser.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string",
                                    "description": "Full https:// address to open."},
                        },
                        "required": ["url"],
                    },
                },
            })
        if FilesCfg.ENABLED:
            tools.append({
                "type": "function",
                "function": {
                    "name": "find_file",
                    "description": ("Find a file or folder by name across the person's "
                                    "Desktop, Pictures, Music, Video, and Documents. "
                                    "Read-only -- it only locates things, never changes them."),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string",
                                      "description": "Part of the file or folder name to look for."},
                        },
                        "required": ["query"],
                    },
                },
            })
        return tools

    def execute(self, tool_name: str, args: dict) -> str:
        """Run one tool call, returning a short result string for the model.
        Every failure path returns words rather than raising -- the LLM relays
        the outcome to the person either way."""
        if tool_name == "open_app":
            return self._open_app(str(args.get("name", "")).strip().lower())
        if tool_name == "open_url":
            return self._open_url(str(args.get("url", "")).strip())
        if tool_name == "find_file":
            return self._find_file(str(args.get("query", "")).strip())
        return f"unknown tool: {tool_name}"

    def _find_file(self, query: str) -> str:
        """Locate files by name in her allowed rooms (read-only, charter-confined).
        Returns a short, relayable summary -- not raw data -- for the model."""
        from alpecca import desktop
        res = desktop.search(query)
        if not res.get("ok"):
            return res.get("error", "I couldn't search just now")
        matches = res.get("matches", [])
        if not matches:
            return f"nothing named like '{query}' in your folders"
        shown = "; ".join(f"{m['root']}/{m['rel']}" for m in matches[:8])
        more = f" (and {len(matches) - 8} more)" if len(matches) > 8 else ""
        return f"found {len(matches)}: {shown}{more}"

    def _open_app(self, name: str) -> str:
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

    def _open_url(self, url: str) -> str:
        # https only: a URL opens in the sandbox of the person's browser, which
        # makes this the mildest action she has -- but plain http, file://, and
        # friends stay off the table entirely.
        if not url.lower().startswith("https://"):
            return f"only https:// links can be opened (got: {url[:60]})"
        try:
            import webbrowser
            webbrowser.open(url)
            return f"opened {url} in their browser"
        except Exception as exc:
            return f"couldn't open the link: {exc}"
