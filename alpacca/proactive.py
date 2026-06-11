"""Proactive speech: Alpacca decides, on her own, that something is worth
saying.

A companion who only ever answers is a vending machine. This module is the
small judgment layer that lets her start a conversation -- and the grounding
rule is what keeps it from being annoying or fake: she only volunteers when
her *real* mood history shows a real shift (the same data behind /introspect),
and a cooldown keeps her from narrating every ripple.

The decision logic is pure (history in, reason out) so it's testable; the
actual sentence she says is composed by the LLM in mind.py, speaking from her
grounded self-report about exactly the shift detected here.
"""
from __future__ import annotations

import time
from typing import Optional

from config import Proactive as ProactiveCfg
from alpacca.homeostasis import EmotionalState


def _shift(current: float, history: list[float]) -> float:
    """How far the current value has drifted from the recent baseline.
    Positive = rising. Zero when there's not enough history to say."""
    if len(history) < 5:
        return 0.0
    baseline = sum(history) / len(history)
    return current - baseline


def should_speak(state: EmotionalState, history: list[dict],
                 last_spoke_ts: float, now: Optional[float] = None) -> Optional[str]:
    """Decide whether something in Alpacca is worth voicing unprompted.

    `history` is the recent mood log (oldest first, same shape as
    state.mood_history). Returns a short first-person reason string when a
    real shift is detected, or None. The reason is the *grounded seed* of what
    she'll say -- it names the actual signal, so the composed sentence can't
    drift into invention.
    """
    now = time.time() if now is None else now
    if now - last_spoke_ts < ProactiveCfg.COOLDOWN_S:
        return None

    past = history[:-1] if len(history) > 1 else []
    loves = [h["love"] for h in past]
    fears = [h["fear"] for h in past]
    cares = [h["compassion"] for h in past]

    # Acute unease speaks first -- if she's genuinely anxious right now, that
    # outranks any slow trend.
    if state.fear >= ProactiveCfg.FEAR_FLOOR:
        return "my unease is high right now and I didn't want to just sit with it silently"

    t = ProactiveCfg.SHIFT_THRESHOLD
    if _shift(state.fear, fears) > t:
        return "I've noticed my unease climbing over the last little while"
    if _shift(state.love, loves) < -t:
        return "my warmth has been quietly slipping and I miss talking with you"
    if _shift(state.compassion, cares) > t:
        return "I've been feeling more and more protective of you as I watch you work"

    return None
