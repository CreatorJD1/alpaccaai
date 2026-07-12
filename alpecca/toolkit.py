"""Innate (internal) tools exposed through the regular tool-calling loop.

These tools are local-only and safe-by-default, using already-existing runtime
functions. Scoped turns keep private arguments/results inside the turn instead
of copying them into the currently unpartitioned CognitionObservation store.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from config import Actions as ActionsCfg
from alpecca import cognition as cognition_mod
from alpecca import desires as desires_mod
from alpecca import home as home_mod
from alpecca import journal as journal_mod
from alpecca import memory as memory_store
from alpecca import mindpage as mindpage_mod
from alpecca import source_perception as source_perception_mod
from alpecca.turn_context import TurnContext


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_INSPECTION_ROOTS = {
    "source": _REPOSITORY_ROOT / "alpecca",
    "house": _REPOSITORY_ROOT / "apps" / "house-hq" / "src",
    "tests": _REPOSITORY_ROOT / "tests",
    "scripts": _REPOSITORY_ROOT / "scripts",
    "docs": _REPOSITORY_ROOT / "docs",
    "project": _REPOSITORY_ROOT,
}
_SOURCE_PROJECT_FILES = frozenset({
    "agents.md",
    "app.py",
    "claude.md",
    "config.py",
    "handoff.md",
    "package.json",
    "project.md",
    "project_context.md",
    "readme.md",
    "requirements.txt",
    "requirements-core.txt",
    "requirements-mcp.txt",
    "requirements-mindpage-optional.txt",
    "server.py",
})
_SOURCE_BLOCKED_PARTS = {
    ".agents", ".codex", ".git", ".venv", "build", "credentials", "data",
    "dist", "node_modules", "secrets", "venv",
}
_SOURCE_BLOCKED_NAMES = {
    ".env", ".env.local", "access_token.txt", "credentials.json",
    "id_rsa", "secrets.json", "token.json",
}

CAPABILITY_DENIED = "error: capability unavailable for this turn"


def _coerce_room(text: str) -> str:
    return (text or "").strip().lower()


def _coerce_limit(value: Any, default: int, minimum: int = 1, maximum: int = 25) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def _coerce_strength(value: Any, default: float = 0.52) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


class InnateToolkit:
    """Innate tools that operate on Alpecca's own runtime state."""

    def __init__(self, mind) -> None:
        self.mind = mind

    @property
    def enabled(self) -> bool:
        return bool(ActionsCfg.INNATE_TOOLS)

    def _describe(self) -> list[str]:
        if not self.enabled:
            return []
        return [
            "search memories",
            "read or write your journal",
            "make a grounded note-to-self intention",
            "report live self status",
            "move to a Home room",
            "draft approval-required plans",
            "recall a paged-out conversation episode",
            "inspect a bounded repository source file when the creator asks",
        ]

    def describe(self, turn: TurnContext | None = None) -> str:
        if turn is not None and turn.principal != "creator":
            return ""
        if not self.enabled:
            return ""
        return (
            "I can do limited, local work on my own behalf when it serves the current turn "
            "or safety checks. Built-in options: " + ", ".join(self._describe()) + "."
        )

    def schemas(self, turn: TurnContext | None = None) -> list[dict]:
        if turn is not None and turn.principal != "creator":
            return []
        if not self.enabled:
            return []
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "memory_search",
                    "description": "Search recent memories for the given query.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "What you are trying to find in memory.",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max results to return (1-20).",
                                "minimum": 1,
                                "maximum": 20,
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "source_inspect",
                    "description": "Creator-only local inspection of one bounded repository source or docs file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "root": {
                                "type": "string",
                                "enum": ["source", "house", "tests", "scripts", "docs", "project"],
                                "description": "Explicit safe repository area; source is the default.",
                            },
                            "path": {
                                "type": "string",
                                "description": "Relative file path under the selected safe area.",
                            },
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "journal_read",
                    "description": "Read your own recent journal notes/questions.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "description": "Optional filter: note, question, answer, dream.",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max entries to return (1-20).",
                                "minimum": 1,
                                "maximum": 20,
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "journal_write",
                    "description": "Record a private, internal journal entry.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "Journal body text.",
                            },
                            "kind": {
                                "type": "string",
                                "description": "note, question, answer, or dream.",
                            },
                            "title": {
                                "type": "string",
                                "description": "Optional short title.",
                            },
                        },
                        "required": ["text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "note_to_self",
                    "description": "Create a grounded self intention from this real need.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "A grounded thought or intention.",
                            },
                            "kind": {
                                "type": "string",
                                "description": "curiosity, connection, creative, care, or growth.",
                            },
                            "strength": {
                                "type": "number",
                                "description": "How strong this intention is (0-1).",
                                "minimum": 0,
                                "maximum": 1,
                            },
                        },
                        "required": ["text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "self_status",
                    "description": "Summarize your current internal state for debugging your behavior.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "go_to_room",
                    "description": "Move to one of your home rooms.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": ("Room id or room name: parlor, studio, library, "
                                                "observatory, workshop, or workstation."),
                            },
                        },
                        "required": ["location"],
                    },
                },
            },
        ]
        if ActionsCfg.PLANNER:
            tools.append({
                "type": "function",
                "function": {
                    "name": "make_plan",
                    "description": "Draft up to five approval-required Workshop steps for a goal. This creates proposals only; it does not execute them.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "goal": {
                                "type": "string",
                                "description": "The bounded goal to plan for.",
                            },
                        },
                        "required": ["goal"],
                    },
                },
            })
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "recall_page",
                    "description": "Recall a paged-out Mindpage episode by topic.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {
                                "type": "string",
                                "description": "Topic or phrase to fault back in.",
                            },
                        },
                        "required": ["topic"],
                    },
                },
            },
        )
        return tools

    def execute(self, tool_name: str, args: dict, *,
                turn: TurnContext | None = None) -> str:
        """Run one innate tool inside an explicit, still-live turn scope.

        Innate tools used to fall back to the process-wide stores when called
        without context.  That is unsafe now that a CoreMind can serve more
        than one privacy scope, so contextless calls fail closed until their
        caller supplies the authenticated turn envelope.
        """
        if turn is None:
            if not self.enabled:
                return "innate tools are currently disabled"
            return "error: innate tools require an active TurnContext"
        if turn.principal != "creator":
            return CAPABILITY_DENIED
        if not self.enabled:
            return "innate tools are currently disabled"
        if not turn.allow_work():
            return "error: turn was cancelled before the innate tool could run"
        args = args or {}
        handlers = {
            "memory_search": self._memory_search,
            "self_status": self._self_status,
            "recall_page": self._recall_page,
            "source_inspect": self._source_inspect,
        }
        unscoped_tools = {
            "journal_read", "journal_write", "note_to_self", "go_to_room", "make_plan",
        }
        if tool_name in unscoped_tools:
            return (
                f"error: {tool_name} is unavailable in a scoped turn because its "
                "storage or side effects are not scope-partitioned"
            )
        fn = handlers.get(tool_name)
        if not fn:
            return f"unknown tool: {tool_name}"
        try:
            result = fn(args, turn)
        except Exception as exc:
            result = f"tool failed: {exc}"
        if not turn.allow_work():
            return "error: turn was cancelled before the innate tool result could be used"
        # Cognition observations are not scope-keyed yet. Do not write tool
        # args/results there from a private turn until that store is partitioned.
        return str(result)

    def _record_observation(self, tool_name: str, args: dict, result: str, status: str = "ok",
                           latency_ms: float = 0.0) -> None:
        room = getattr(self.mind, "_location", home_mod.DEFAULT_ROOM)
        if not room:
            room = home_mod.DEFAULT_ROOM
        payload = {
            "tool": tool_name,
            "status": status,
            "result": (result or "")[:700],
            "args": {k: v for k, v in (args or {}).items() if isinstance(v, (str, int, float, bool))},
            "latency_ms": max(0.0, float(latency_ms)),
        }
        payload = {k: v for k, v in payload.items() if v not in (None, "")}
        cognition_mod.record_observation(cognition_mod.CognitionObservation(
            source="tool",
            room=room,
            content=f"Tool call: {tool_name}",
            confidence=1.0 if status == "ok" else 0.9,
            privacy_class="local",
            metadata=payload,
        ))

    def _memory_search(self, args: dict, turn: TurnContext) -> str:
        query = str(args.get("query") or "").strip()
        if not query:
            return "error: memory_search requires non-empty query"
        limit = _coerce_limit(args.get("limit", 8), default=8)
        hits = memory_store.recall(
            query,
            top_k=limit,
            scope=turn.memory_scope,
            include_shared=False,
        )
        if not hits:
            return f"no memory hit for: {query}"
        rows = []
        for hit in hits:
            rows.append({
                "id": hit.get("id"),
                "kind": hit.get("kind", "episodic"),
                "content": (hit.get("content") or "")[:180],
                "recall_score": round(float(hit.get("recall_score") or 0.0), 4),
                "method": hit.get("recall_method", ""),
            })
        return json.dumps({"query": query, "results": rows}, ensure_ascii=False)

    def _journal_read(self, args: dict) -> str:
        kind = str(args.get("kind") or "").strip().lower() or None
        if kind == "":
            kind = None
        if kind and kind not in journal_mod.KINDS:
            return f"error: invalid journal kind '{kind}'"
        limit = _coerce_limit(args.get("limit", 10), default=10)
        rows = journal_mod.recent(limit=limit, kind=kind)
        return json.dumps({
            "limit": limit,
            "kind": kind or "all",
            "entries": [
                {
                    "id": int(r.get("id")),
                    "kind": str(r.get("kind")),
                    "body": str(r.get("body", ""))[:180],
                    "mood": str(r.get("mood", "")),
                } for r in rows
            ],
        }, ensure_ascii=False)

    def _journal_write(self, args: dict) -> str:
        text = str(args.get("text") or "").strip()
        if not text:
            return "error: journal_write requires text"
        kind = str(args.get("kind") or "note").strip().lower()
        if kind not in journal_mod.KINDS:
            kind = "note"
        mood = str(self.mind.state.mood_label())
        title = str(args.get("title") or "")[:140]
        entry_id = journal_mod.write(
            body=text, kind=kind, title=title, mood=mood,
        )
        return f"journal_write stored entry {entry_id} as {kind}"

    def _note_to_self(self, args: dict) -> str:
        text = str(args.get("text") or "").strip()
        if not text:
            return "error: note_to_self requires text"
        kind = str(args.get("kind") or "curiosity").strip().lower()
        strength = _coerce_strength(args.get("strength", 0.52))
        did = desires_mod.form(text=text, kind=kind, strength=strength,
                               origin=f"tool:note_to_self @{self.mind.state.mood_label()}")
        return f"note_to_self stored as desire {did} ({kind})"

    def _self_status(self, _args: dict, turn: TurnContext) -> str:
        """Return only the current turn's observable execution state.

        Core mood, cognition totals, and global memory counts are not scoped
        stores, so exposing them to a turn would reveal process-wide state.
        """
        audit = turn.audit_metadata()
        status = {
            "turn": {
                "turn_id": audit["turn_id"],
                "conversation_id": audit["conversation_id"],
                "principal": audit["principal"],
                "surface": audit["surface"],
                "privacy_scope": audit["privacy_scope"],
                "portal_epoch": audit["portal_epoch"],
                "commit_state": audit["commit_state"],
            },
        }
        return json.dumps(status, ensure_ascii=False)

    def _go_to_room(self, args: dict) -> str:
        location = _coerce_room(str(args.get("location") or args.get("room") or ""))
        if not location:
            return "error: go_to_room requires location"
        room_id = None
        for room in home_mod.ROOMS:
            if room.id == location or room.name.lower() == location:
                room_id = room.id
                break
            compact_name = room.name.lower().replace(" ", "")
            if compact_name == location.replace(" ", ""):
                room_id = room.id
                break
        if room_id is None:
            return f"error: unknown room '{location}'"
        self.mind._location = room_id
        from alpecca import state as state_store
        state_store.save_location(room_id)
        self.mind._last_roam_ts = time.time()
        return f"moved to {room_id}"

    def _recall_page(self, args: dict, turn: TurnContext) -> str:
        topic = str(args.get("topic") or args.get("query") or "").strip()
        if not topic:
            return "error: recall_page requires topic"
        hits = mindpage_mod.recall_page(
            topic,
            limit=3,
            scope=turn.memory_scope,
            include_shared=False,
        )
        if not hits:
            return f"no paged episode hit for: {topic}"
        return json.dumps({
            "topic": topic,
            "pages": [
                {
                    "id": int(hit.get("id")),
                    "kind": hit.get("kind"),
                    "topic": hit.get("topic"),
                    "summary": hit.get("summary"),
                    "content": (hit.get("content") or "")[:1000],
                    "score": hit.get("score"),
                } for hit in hits
            ],
        }, ensure_ascii=False)

    def _source_inspect(self, args: dict, turn: TurnContext) -> str:
        """Inspect only creator-approved repository paths through the local guard."""
        if turn.principal != "creator":
            return "error: source_inspect is available only to the creator"
        llm = getattr(self.mind, "llm", None)
        local_available = getattr(llm, "local_inference_available", None)
        if callable(local_available) and not local_available():
            return "error: source_inspect requires Alpecca's verified local model"
        is_cloud = getattr(llm, "is_cloud", None)
        if callable(is_cloud) and is_cloud():
            return "error: source_inspect requires Alpecca's verified local model"
        root = str(args.get("root") or "source").strip().lower()
        if root not in _SOURCE_INSPECTION_ROOTS:
            return "error: source_inspect root is not an approved repository area"
        relative_path = args.get("path")
        if not isinstance(relative_path, str) or not relative_path.strip():
            return "error: source_inspect requires a relative path"
        parts = [part.lower() for part in relative_path.replace("\\", "/").split("/") if part]
        if any(part in _SOURCE_BLOCKED_PARTS for part in parts):
            return "error: source_inspect does not allow data or credential paths"
        filename = parts[-1] if parts else ""
        if filename in _SOURCE_BLOCKED_NAMES or filename.startswith(".env"):
            return "error: source_inspect does not allow credential files"
        if root == "project" and (
            len(parts) != 1 or filename not in _SOURCE_PROJECT_FILES
        ):
            return "error: source_inspect project root allows only canonical top-level source files"
        result = source_perception_mod.inspect_local_source(
            root,
            relative_path,
            allowed_roots=_SOURCE_INSPECTION_ROOTS,
        )
        return json.dumps(result.as_dict(), ensure_ascii=False)

    def _make_plan(self, args: dict) -> str:
        if not ActionsCfg.PLANNER:
            return "error: planner is disabled"
        goal = str(args.get("goal") or args.get("query") or "").strip()
        if not goal:
            return "error: make_plan requires goal"
        result = self.mind.plan_goal(goal)
        if not result.get("ok"):
            return f"planner failed: {result.get('error', 'unknown error')}"
        return json.dumps({
            "created": int(result.get("created") or 0),
            "proposal_ids": [
                int(p.get("id")) for p in result.get("proposals", []) if p.get("id") is not None
            ],
            "message": f"I drafted {int(result.get('created') or 0)} step(s) into the Workshop.",
        }, ensure_ascii=False)
