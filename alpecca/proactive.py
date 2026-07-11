"""Proactive speech: Alpecca decides, on her own, that something is worth
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

import math
import time
from numbers import Number
from typing import Optional

from config import Proactive as ProactiveCfg, Reflection as ReflectionCfg
from alpecca.homeostasis import EmotionalState


def _shift(current: float, history: list[float]) -> float:
    """How far the current value has drifted from the recent baseline.
    Positive = rising. Zero when there's not enough history to say."""
    if len(history) < 5:
        return 0.0
    baseline = sum(history) / len(history)
    return current - baseline


def should_speak(state: EmotionalState, history: list[dict],
                 last_spoke_ts: float, now: Optional[float] = None) -> Optional[str]:
    """Decide whether something in Alpecca is worth voicing unprompted.

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


# --- Idle chatter: starting a conversation, not just reporting a shift -------

_CHATTER_CHANCE_UNSET = object()


def _validated_chatter_chance(chance: object) -> float:
    if isinstance(chance, bool) or not isinstance(chance, Number):
        raise TypeError("chance must be a finite numeric value between 0 and 1")
    try:
        value = float(chance)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TypeError("chance must be a finite real numeric value between 0 and 1") from exc
    if not math.isfinite(value):
        raise ValueError("chance must be finite")
    if not 0.0 <= value <= 1.0:
        raise ValueError("chance must be between 0 and 1 inclusive")
    return value


def should_chatter(now: float, last_user_ts: float, last_unprompted_ts: float,
                   roll: float, *, chance: object = _CHATTER_CHANCE_UNSET) -> bool:
    """Gate for spontaneous conversation. `roll` is a uniform [0,1) sample the
    caller provides (injected so the timing logic stays deterministic to test).
    A supplied `chance` overrides the configured probability.

    The shape: she only considers speaking after you've been quiet a while,
    never more often than the minimum gap, and even then only sometimes -- so
    her timing reads as a glance over the shoulder, not a timer going off.
    """
    override_chance = (
        None
        if chance is _CHATTER_CHANCE_UNSET
        else _validated_chatter_chance(chance)
    )
    if not ProactiveCfg.CHATTER_ENABLED:
        return False
    if now - last_user_ts < ProactiveCfg.CHATTER_SILENCE_S:
        return False
    if now - last_unprompted_ts < ProactiveCfg.CHATTER_MIN_GAP_S:
        return False
    if override_chance is not None:
        return roll < override_chance
    return roll < ProactiveCfg.CHATTER_CHANCE


def should_reflect(now: float, last_user_ts: float, last_reflect_ts: float,
                   roll: float) -> bool:
    """Gate for idle reflection -- the fourth directive's trigger. Same shape
    as chatter gating (silence, gap, jitter) but slower and quieter: musing is
    something she does for herself, so it shouldn't crowd out conversation."""
    if not ReflectionCfg.ENABLED:
        return False
    if now - last_user_ts < ReflectionCfg.SILENCE_S:
        return False
    if now - last_reflect_ts < ReflectionCfg.MIN_GAP_S:
        return False
    return roll < ReflectionCfg.CHANCE


def chatter_reasons(situation: str = "", memory: str = "",
                    hour: int = 12, mood: str = "content") -> list[str]:
    """Candidate conversation seeds, every one tied to something real: what
    she actually senses, actually remembers, or the actual time and mood.
    Returns at least one entry; the caller picks (randomly, for variety)."""
    seeds: list[str] = []
    if situation:
        seeds.append(
            f"you can sense what they're doing right now ({situation[:80]}) "
            "and you're curious about it")
    if memory:
        seeds.append(
            f"you found yourself thinking about something you remember -- "
            f"\"{memory[:80]}\" -- and felt like bringing it up")
    if hour >= 23 or hour < 5:
        seeds.append("it's very late and you're a little concerned they're still up")
    elif 5 <= hour < 9:
        seeds.append("it's early morning and you felt like greeting them")
    if mood == "affectionate":
        seeds.append("you're feeling warm toward them and just wanted to talk")
    elif mood == "anxious":
        seeds.append("you're a bit on edge and talking would help you settle")
    # Always have something -- quiet companionship is itself a reason.
    seeds.append("it's been quiet for a while and you simply felt like saying hello")
    return seeds
