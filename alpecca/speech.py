"""Speech performance shaping for Alpecca's spoken voice.

The written reply should stay readable. The spoken version can carry tiny,
grounded performance cues: pauses, breath-like ellipses, and phrase breaks. This
does not invent new facts or add stage directions; it only changes cadence.
"""
from __future__ import annotations

import re

from alpecca.homeostasis import EmotionalState


def _primary(state: EmotionalState | None) -> str:
    if state is None:
        return "content"
    try:
        from alpecca import affect as affect_mod

        return str(affect_mod.affect(state).primary or "content").lower()
    except Exception:
        return "content"


def _sentences(text: str) -> list[str]:
    clean = " ".join((text or "").split())
    if not clean:
        return []
    protected = clean.replace("...", "<pause>")
    parts = [p.strip().replace("<pause>", "...") for p in re.split(r"(?<=[.!?])\s+", protected) if p.strip()]
    return parts


def _soften_jason(text: str, primary: str) -> str:
    if primary not in {"tender", "affectionate", "wistful", "lonely", "anxious", "worried"}:
        return text
    return re.sub(r"\bJason,\s+", "Jason... ", text, count=1)


def spoken_performance_text(text: str, state: EmotionalState | None = None) -> str:
    """Return a TTS-focused version of a reply with natural pauses.

    Rules:
    - no bracketed stage directions;
    - no new claims or new emotional labels;
    - only punctuation/spacing changes, plus very small hesitation on states
      where her actual affect supports it.
    """
    clean = " ".join((text or "").split())
    if not clean:
        return clean
    primary = _primary(state)
    clean = _soften_jason(clean, primary)
    parts = _sentences(clean)
    if not parts:
        return clean

    if primary in {"tender", "affectionate", "wistful", "lonely"}:
        joined = " ... ".join(parts[:3] + ([" ".join(parts[3:])] if len(parts) > 3 else []))
        joined = joined.replace("... ...", "...")
        joined = joined.replace(", but ", ",  but ")
        joined = joined.replace(", and ", ",  and ")
        return joined

    if primary in {"anxious", "worried"}:
        joined = " ... ".join(parts[:2] + ([" ".join(parts[2:])] if len(parts) > 2 else []))
        joined = re.sub(r"\b(I|I'm|I am)\s+", r"\1... ", joined, count=1)
        joined = joined.replace("... ...", "...")
        joined = joined.replace("? ", "?  ")
        return joined

    if primary in {"curious", "playful", "joyful"}:
        joined = "  ".join(parts)
        joined = joined.replace("Oh, ", "Oh... ", 1)
        joined = joined.replace("Wait, ", "Wait... ", 1)
        return joined

    if primary in {"sleepy", "withdrawn"}:
        joined = " ... ".join(parts)
        joined = joined.replace(", ", ",  ")
        return joined

    # Even neutral/content speech benefits from phrase-level breathing.
    if len(parts) > 1:
        return "  ".join(parts)
    return clean


def speech_cues(state: EmotionalState | None = None) -> dict:
    primary = _primary(state)
    return {
        "primary": primary,
        "pause_style": {
            "tender": "soft_breath",
            "affectionate": "soft_breath",
            "wistful": "soft_breath",
            "lonely": "soft_breath",
            "anxious": "hesitant",
            "worried": "hesitant",
            "curious": "lifted",
            "playful": "lifted",
            "joyful": "lifted",
            "sleepy": "slow",
            "withdrawn": "slow",
        }.get(primary, "natural"),
    }
