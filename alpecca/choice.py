"""Constrained local-LLM choices with deterministic fallback."""
from __future__ import annotations

import json
import re
from typing import Any

_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)


def _clean(text: str) -> str:
    text = _THINK_RE.sub("", str(text or "")).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0).strip() if match else text


def parse_choice(text: str, option_count: int, *, allow_speak: bool = False) -> dict | None:
    """Parse tiny JSON decisions. `pick` is 1-based in model output."""
    try:
        data = json.loads(_clean(text))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    out: dict[str, Any] = {}
    if allow_speak and "speak" in data:
        if not isinstance(data.get("speak"), bool):
            return None
        out["speak"] = bool(data["speak"])
    if "pick" in data:
        try:
            pick = int(data["pick"])
        except (TypeError, ValueError):
            return None
        if pick < 1 or pick > int(option_count):
            return None
        out["pick"] = pick - 1
    if "pick" not in out and not (allow_speak and "speak" in out):
        return None
    return out


def constrained_pick(llm, question: str, options: list[str], context: str = "",
                     *, allow_speak: bool = False) -> dict | None:
    if not options or not getattr(llm, "online", False):
        return None
    numbered = "\n".join(f"{i + 1}. {str(opt)[:240]}" for i, opt in enumerate(options))
    shape = '{"speak": true, "pick": 1}' if allow_speak else '{"pick": 1}'
    system = (
        "You are a strict local decision helper for Alpecca. "
        "Choose only from the numbered options. Return only tiny JSON, no prose. "
        f"Required shape: {shape}"
    )
    prompt = (
        f"Question: {question}\n"
        f"Context: {context[:900]}\n"
        f"Options:\n{numbered}\n"
        "Return JSON now."
    )
    try:
        text = llm.generate(system, prompt, history=None, tier="fast")
    except Exception:
        return None
    return parse_choice(text, len(options), allow_speak=allow_speak)
