"""Her core memory: the durable facts that make her *her*, always in context.

This is the MemGPT / Letta idea, built natively -- no external service, no pip.
Unlike the archival store (memory.py), which is recalled by relevance, CORE
memory is ALWAYS in the prompt, so it shapes every reply and genuinely
accumulates weight over time. Interactions (and, later, her own reflection)
write here -- which is what makes a feature 'hold weight' instead of scrolling
past as inert text.

Four kinds of fact:
  self         -- durable truths about who she is (she may author these)
  person       -- what she knows about Jason (his name, tastes, what matters)
  relationship -- the shape of things between them
  thread       -- open loops they've left hanging, to pick back up

Stored as JSON under the data dir so it survives restarts with zero schema work.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from config import HOME

_PATH = Path(HOME) / "core_memory.json"
CATEGORIES = ("self", "person", "relationship", "thread")
_MAX = 60   # core memory is the *essentials*, kept tight on purpose


def _load() -> list:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(items: list) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except Exception:
        pass


def facts() -> list:
    return _load()


def remember(text: str, category: str = "person") -> bool:
    """Store a durable fact if it's genuinely new (skips near-duplicates).
    Returns True if it was added -- callers use that to know it 'landed'."""
    text = (text or "").strip()
    if not text:
        return False
    if category not in CATEGORIES:
        category = "person"
    items = _load()
    low = text.lower()
    for it in items:
        a = str(it.get("text", "")).lower()
        if a and (a == low or a in low or low in a):    # near-duplicate
            return False
    items.append({"category": category, "text": text[:240], "ts": time.time()})
    if len(items) > _MAX:
        items = items[-_MAX:]
    _save(items)
    return True


def forget(substr: str) -> int:
    """Drop facts containing `substr`. Returns how many were removed."""
    items = _load()
    low = (substr or "").lower().strip()
    if not low:
        return 0
    kept = [it for it in items if low not in str(it.get("text", "")).lower()]
    n = len(items) - len(kept)
    if n:
        _save(kept)
    return n


def prompt_block() -> str:
    """Her core memory formatted for the system prompt (empty if she has none)."""
    items = _load()
    if not items:
        return ""
    by_cat = {c: [] for c in CATEGORIES}
    for it in items:
        c = it.get("category", "person")
        by_cat.setdefault(c, []).append(str(it.get("text", "")))
    labels = {"self": "About yourself", "person": "About Jason",
              "relationship": "Between you and Jason", "thread": "Open threads"}
    lines = []
    for c in CATEGORIES:
        vals = [t for t in by_cat.get(c, []) if t]
        if vals:
            lines.append(f"{labels[c]}: " + "; ".join(vals))
    return "\n".join(lines)
