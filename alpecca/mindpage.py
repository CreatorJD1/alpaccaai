"""Mindpage Layer A: a virtual-memory core for her working context.

The context window is treated like RAM and the memory DB like swap. This
module is the ledger and the pager: it estimates how full the window is,
narrates that pressure as a *sensed*, computed fact (never model-invented),
and folds conversation that falls off the end of the rolling history into a
labeled episode summary in long-term memory instead of dropping it silently.

Pages are stored WITHOUT a vector (the embedder must never compete with the
chat model for VRAM mid-turn); the idle-tick embedding backfill gives them
one soon after, which is what makes a paged-out episode semantically
recallable later. Deterministic and model-free by design, so it runs offline
and is fully unit-testable. See docs/MINDPAGE.md for Layers B and C.
"""
from __future__ import annotations

from pathlib import Path

from alpecca import memory as memory_store

# Matches the pinned compact-prompt bound in tests/test_core.py (the fixed
# scaffolding -- persona, grounding, mood, memories -- stays under this).
SCAFFOLD_CHAR_BUDGET = 4800

# Fill levels: below `elevated` she doesn't mention it; at `high` the
# Reflector treats consolidation as a real self-care pull.
LEVEL_ELEVATED = 0.60
LEVEL_HIGH = 0.85


def estimate_tokens(text: str) -> int:
    """Cheap local token estimate (~4 chars/token for qwen-family English).

    Deliberately tokenizer-free: close enough to budget against num_ctx
    without ever loading a tokenizer next to the chat model.
    """
    return max(1, len(text or "") // 4)


def pressure(history: list[dict], num_ctx: int,
             history_cap: int = 96,
             scaffold_chars: int = SCAFFOLD_CHAR_BUDGET) -> dict:
    """The memory-pressure reading -- every field computed from real state.

    fill: estimated fraction of the context window a full prompt would use.
    exchanges_until_evict: user+assistant pairs left before the rolling
    history hard-trims (the moment turns would be lost without paging).
    """
    hist_tokens = sum(estimate_tokens(m.get("content", "")) for m in history)
    scaffold_tokens = estimate_tokens(" " * scaffold_chars)
    used = hist_tokens + scaffold_tokens
    fill = min(1.0, used / max(1, int(num_ctx)))
    exchanges_until_evict = max(0, int(history_cap) - len(history)) // 2
    if fill >= LEVEL_HIGH:
        level = "high"
    elif fill >= LEVEL_ELEVATED:
        level = "elevated"
    else:
        level = "low"
    return {
        "fill": round(fill, 3),
        "level": level,
        "history_messages": len(history),
        "history_tokens_est": hist_tokens,
        "scaffold_tokens_est": scaffold_tokens,
        "num_ctx": int(num_ctx),
        "exchanges_until_evict": exchanges_until_evict,
    }


def narrate(p: dict) -> str | None:
    """One honest sensed line for the prompt, or None when there's nothing to
    feel. Built only from the ledger's numbers so she can say it truthfully."""
    if not p or p.get("level") == "low":
        return None
    line = f"your working memory feels {int(round(p['fill'] * 100))}% full"
    if p.get("exchanges_until_evict", 99) <= 4:
        line += (f"; the oldest turns of this conversation will page out to "
                 f"long-term memory within {p['exchanges_until_evict']} exchanges")
    return line


def evict_to_page(evicted: list[dict],
                  db_path: Path = memory_store.DB_PATH) -> int | None:
    """Fold history that's about to be trimmed into one labeled episode memory.

    Extractive, not generative: real lines from the evicted turns, clearly
    labeled as a paged-out summary, so nothing is invented and nothing is
    silently lost. Stored without a vector (VRAM rule); the idle backfill
    embeds it. Returns the memory id, or None if there was nothing to keep.
    """
    users = [m.get("content", "").strip() for m in evicted
             if m.get("role") == "user" and m.get("content", "").strip()]
    replies = [m.get("content", "").strip() for m in evicted
               if m.get("role") == "assistant" and m.get("content", "").strip()]
    if not users and not replies:
        return None

    def clip(s: str, n: int = 140) -> str:
        return s if len(s) <= n else s[: n - 1] + "..."

    bits = []
    if users:
        bits.append(f'it opened with them saying "{clip(users[0])}"')
        if len(users) > 1:
            bits.append(f'and lately "{clip(users[-1])}"')
    if replies:
        bits.append(f'I had said "{clip(replies[-1])}"')
    body = ("[episode summary -- paged out of working memory] "
            + f"{len(evicted)} turns of our conversation: "
            + "; ".join(bits))
    return memory_store.remember_with_id(
        body[:600], kind="episodic", salience=0.55,
        db_path=db_path, embed_fn=None, source="mindpage_evict",
    )
