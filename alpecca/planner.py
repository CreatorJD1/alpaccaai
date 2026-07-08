"""Approval-gated local planner for Alpecca's Workshop.

The planner drafts proposals only. It never executes steps by itself; each step
stores one machine-readable tool call that still has to pass the Workshop
approval route before `CoreMind.execute_approved_step` will run it.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from config import DB_PATH
from alpecca import cognition as cognition_mod

MAX_STEPS = 5
ALLOWED_PLAN_TOOLS: dict[str, set[str]] = {
    "memory_search": {"query"},
    "journal_write": {"text"},
    "note_to_self": {"text"},
    "self_status": set(),
    "go_to_room": {"location"},
    "recall_page": {"topic"},
}

_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)


def _clean_json_text(text: str) -> str:
    text = _THINK_RE.sub("", str(text or "")).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0).strip() if match else text


def parse_plan(text: str) -> list[dict[str, Any]] | None:
    try:
        data = json.loads(_clean_json_text(text))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        return None
    steps: list[dict[str, Any]] = []
    for raw in raw_steps[:MAX_STEPS]:
        if not isinstance(raw, dict):
            continue
        tool = str(raw.get("tool") or "").strip()
        if tool not in ALLOWED_PLAN_TOOLS:
            continue
        args = raw.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        allowed_args = ALLOWED_PLAN_TOOLS[tool]
        clean_args: dict[str, Any] = {}
        for key in allowed_args:
            if key in args:
                value = args.get(key)
                if isinstance(value, (str, int, float, bool)):
                    clean_args[key] = str(value).strip()[:500]
        if allowed_args and not all(clean_args.get(key) for key in allowed_args):
            continue
        action = str(raw.get("action") or "").strip()[:220]
        reason = str(raw.get("reason") or "").strip()[:700]
        if not action:
            action = f"Run {tool}"
        if not reason:
            reason = "Planner drafted this as one bounded local step toward the goal."
        steps.append({
            "tool": tool,
            "args": clean_args,
            "action": action,
            "reason": reason,
        })
    return steps if steps else None


def _prompt(goal: str) -> tuple[str, str]:
    system = (
        "You are Alpecca's local planning helper. Draft Workshop steps only; "
        "do not claim execution. Use only the allowed local tools. Return one "
        "valid JSON object and no prose."
    )
    prompt = (
        f"Goal: {goal[:700]}\n"
        "Allowed tools and required args:\n"
        "- memory_search: {\"query\":\"...\"}\n"
        "- journal_write: {\"text\":\"...\"}\n"
        "- note_to_self: {\"text\":\"...\"}\n"
        "- self_status: {}\n"
        "- go_to_room: {\"location\":\"parlor|studio|library|observatory|workshop|workstation\"}\n"
        "- recall_page: {\"topic\":\"...\"}\n\n"
        "Return shape:\n"
        "{\"steps\":[{\"tool\":\"note_to_self\",\"args\":{\"text\":\"...\"},"
        "\"action\":\"short Workshop title\",\"reason\":\"why this step helps\"}]}\n"
        "Maximum 5 steps. Each step must be independently useful and safe after user approval."
    )
    return system, prompt


def plan_goal(goal: str, generate: Callable[[str, str], str], *, db_path=DB_PATH) -> dict[str, Any]:
    goal = (goal or "").strip()
    if not goal:
        return {"ok": False, "error": "goal is required", "created": 0, "proposals": []}
    system, prompt = _prompt(goal)
    steps = None
    last_text = ""
    for attempt in range(2):
        ask = prompt if attempt == 0 else prompt + "\n\nYour previous answer was invalid. Return ONLY the JSON object."
        try:
            last_text = generate(system, ask)
        except Exception as exc:
            return {"ok": False, "error": f"planner unavailable: {exc}", "created": 0, "proposals": []}
        steps = parse_plan(last_text)
        if steps:
            break
    if not steps:
        return {
            "ok": False,
            "error": "planner returned no valid bounded steps",
            "created": 0,
            "proposals": [],
            "raw": last_text[:500],
        }
    proposals: list[dict[str, Any]] = []
    for idx, step in enumerate(steps, start=1):
        payload = {
            "kind": "planner_step",
            "goal": goal[:700],
            "step": idx,
            "tool": step["tool"],
            "args": step["args"],
        }
        proposal_id = cognition_mod.propose_action(cognition_mod.ActionProposal(
            action=step["action"],
            reason=step["reason"],
            approval=cognition_mod.APPROVAL_ASK_FIRST,
            risk="low",
            status="planned",
            evidence=f"Drafted by local planner for goal: {goal[:500]}",
            payload=payload,
        ), db_path=db_path)
        if proposal_id:
            row = cognition_mod.get_action_proposal(proposal_id, db_path=db_path)
            if row:
                proposals.append(row)
    return {"ok": True, "created": len(proposals), "proposals": proposals}
