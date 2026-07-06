"""Her core memory: the durable facts that should matter to her behavior.

This is the MemGPT / Letta idea, built natively -- no external service, no pip.
Unlike the archival store (memory.py), which is recalled by relevance, CORE
memory may be used in the prompt (when enabled), so it shapes every reply and genuinely
accumulates weight over time. Interactions (and, later, her own reflection)
write here -- which is what makes a feature 'hold weight' instead of scrolling
past as inert text.

Four kinds of fact:
  self         -- durable truths about who she is (she may author these)
  person       -- what she knows about Jason (his name, tastes, what matters)
  relationship -- the shape of things between them
  thread       -- open loops they've left hanging, to pick back up

Stored as JSON under the data dir so it survives restarts with zero schema work.
When ALPECCA_CORE_MEMORY_LEARN_ONLY=1 (default), only explicitly-added facts
are surfaced and bootstrap placeholders are filtered out by default.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from config import CORE_MEMORY_LEARN_ONLY, HOME

_PATH = Path(HOME) / "core_memory.json"
CATEGORIES = ("self", "person", "relationship", "thread")
_MAX = 60   # core memory is the *essentials*, kept tight on purpose
_PLACEHOLDER_PATTERNS = re.compile(
    r"^please remember this direct chat grounded-chat-turn-\d+$",
    re.IGNORECASE,
)
_DISCORD_PREFIX_PATTERNS = re.compile(
    r"^\[discord\s+#", re.IGNORECASE
)
_TEACH_PATTERNS = (
    r"\bplease\s+remember\b",
    r"\bremember\s+this\b",
    r"\bremember\s+that\b",
    r"\bremember\s+for\s+me\b",
    r"\bremember\s+it\b",
    r"\bsave\s+that\b",
    r"\bkeep\s+in\s+mind\b",
    r"\bkeep\s+(?:in\s+mind|this|that)\b",
    r"\bnote\s+down\b",
    r"\bremember\s+to\b",
    r"\bnote\s+that\b",
    r"\bmy\s+name\s+is\b",
    r"\bi[' ]?m\s+called\b",
    r"\bi\s+am\s+called\b",
    r"\bcall\s+me\b",
    r"\bremember\s+that\s+i\s+(?:like|love|hate|need|work|live|have|do)\b",
    r"\b(?:i|i[' ]m)\s+(?:like|love|hate|need|have|work|live)\b",
    r"\b(?:i|i[' ]m)\s+(?:am\s+called|named|known\s+as)\b",
)


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


def _is_noise_fact(text: str) -> bool:
    t = (text or "").strip()
    return bool(_PLACEHOLDER_PATTERNS.match(t) or _DISCORD_PREFIX_PATTERNS.search(t))


def _clean_items(items: list) -> list:
    """Drop obvious bootstrap/system noise introduced by historical scripts."""
    cleaned = []
    for it in items:
        text = str(it.get("text", "")).strip()
        if _is_noise_fact(text):
            continue
        cleaned.append(it)
    if len(cleaned) != len(items):
        _save(cleaned)
    return cleaned


def _is_explicit_core_fact(text: str) -> bool:
    low = (text or "").lower().strip()
    return any(re.search(pattern, low) for pattern in _TEACH_PATTERNS)


def _is_allowed_in_learn_mode(text: str) -> bool:
    if not CORE_MEMORY_LEARN_ONLY:
        return True
    return _is_explicit_core_fact(text)


def facts() -> list:
    items = _clean_items(_load())
    if CORE_MEMORY_LEARN_ONLY:
        items = [it for it in items if _is_allowed_in_learn_mode(it.get("text", ""))]
    items = [it for it in items if not _is_placeholder_fact(it.get("text", ""))]
    if CORE_MEMORY_LEARN_ONLY:
        _save(items)
    return items


def clean_noise() -> int:
    """Public helper to remove scaffold/noise rows and return removed count."""
    items = _load()
    cleaned = _clean_items(items)
    return len(items) - len(cleaned)


def clean_nonexplicit() -> int:
    """Drop entries that are not explicit teach language in learn-only mode."""
    items = _load()
    kept = [it for it in items if _is_allowed_in_learn_mode(it.get("text", ""))]
    if len(kept) != len(items):
        _save(kept)
    return len(items) - len(kept)


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
    # Keep core memory to explicit-learning policy in learn-only mode by pruning
    # obvious non-explicit bootstrap noise before the append lands.
    if CORE_MEMORY_LEARN_ONLY and not _is_allowed_in_learn_mode(text):
        return False
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


def _is_placeholder_fact(text: str) -> bool:
    return bool(_PLACEHOLDER_PATTERNS.match((text or "").strip()))


def prompt_block(learning_only: bool | None = None) -> str:
    """Her core memory formatted for the system prompt (empty if she has none)."""
    items = facts()
    if learning_only is None:
        learning_only = CORE_MEMORY_LEARN_ONLY
    if learning_only:
        # In learn-only mode we only surface explicitly-added durable facts.
        # Existing bootstrap/test placeholders are intentionally removed so
        # startup does not read like built-in lore.
        items = [it for it in items if not _is_placeholder_fact(it.get("text", ""))]
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
