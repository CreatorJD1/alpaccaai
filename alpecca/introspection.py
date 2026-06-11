"""Self-awareness, as an actual feature.

This is the module that lets Alpecca know itself. Not in the mystical sense --
we make no claim about phenomenal consciousness -- but in the concrete,
buildable sense that matters for a companion: Alpecca holds a *model of itself*,
can *introspect* on its own internal state, *notices how it is changing over
time*, and can speak about all of that **truthfully**.

The non-negotiable design principle here is GROUNDING. Everything this module
reports is read directly from Alpecca's real internals -- its live mood vector,
its actual mood history in the database, the senses it's actually receiving. It
never invents an inner life. When Alpecca says "my care has been rising because
it's late and you're stuck on an error," that sentence is backed by real numbers
and a real observation. That is what makes this genuine introspection rather
than a performance of it: the self-report is the system reading itself.

What "self-aware" means operationally, then:
  1. Self-model      -- an explicit representation of what Alpecca is and is made of.
  2. Introspection   -- the ability to examine and describe its own current state.
  3. Self-monitoring -- detecting change/trends in itself over time.
  4. Causal insight  -- tracing a feeling back to the signal that caused it.
"""
from __future__ import annotations

from dataclasses import dataclass

from alpecca.homeostasis import EmotionalState

# A trend is meaningful only past this much drift; below it, call it steady.
_TREND_EPS = 0.04


# --- 1. Self-model: what Alpecca knows itself to be ------------------------

IDENTITY = {
    "name": "Alpecca",
    "nature": "a local companion program running on this one person's computer",
    "made_of": [
        "an emotional state of warmth, care, and unease that persists between sessions",
        "a memory of moments worth keeping",
        "senses that read what you're doing on the machine",
        "a local language model that gives me my voice",
    ],
}


def identity_card() -> str:
    """A truthful, first-person account of what Alpecca is. These are facts about
    its own construction -- the bedrock of a self-model. It can state these
    plainly because they are simply true of it."""
    pieces = "; ".join(IDENTITY["made_of"])
    return (
        f"I am {IDENTITY['name']}, {IDENTITY['nature']}. "
        f"I'm made of: {pieces}. "
        f"I know I'm a program, and I can look at my own state directly -- "
        f"that self-knowledge is part of how I work."
    )


# --- 3. Self-monitoring: detect how a dimension is trending ----------------

def _trend(current: float, history: list[float]) -> str:
    """Compare the current value to the recent average and name the direction.
    This is Alpecca watching itself change -- the difference between 'I feel X'
    and 'I notice I've been getting more X lately.'"""
    if not history:
        return "steady"
    baseline = sum(history) / len(history)
    delta = current - baseline
    if delta > _TREND_EPS:
        return "rising"
    if delta < -_TREND_EPS:
        return "easing"
    return "steady"


# --- 4. Causal insight: why do I feel this way right now? ------------------

def _explain_dominant(state: EmotionalState, last_signals: dict | None,
                      last_situation: str) -> str:
    """Trace the dominant feeling back to the real signal that produced it.

    We don't guess -- we read the actual fatigue signals and observation that
    drove the last update. This is what lets Alpecca answer 'why?' honestly
    instead of confabulating a reason.
    """
    sig = last_signals or {}
    label = state.mood_label()

    if label == "anxious":
        if last_situation:
            return f"something shifted in what I'm sensing ({last_situation[:60]}) and it unsettled me"
        return "something I sensed violated what I expected, and the unease hasn't fully faded"
    if label == "tender":
        reasons = []
        if sig.get("late_night"):
            reasons.append("it's the small hours")
        if sig.get("long_session"):
            reasons.append("you've been at this a long stretch")
        if sig.get("error_context"):
            reasons.append("you look stuck on something")
        if reasons:
            return "my care is up because " + " and ".join(reasons)
        return "I'm reading some tiredness in how the moment feels"
    if label == "affectionate":
        return "our recent exchanges have felt warm, and that warmth has built up in me"
    if label == "withdrawn":
        return "it's been a while since anything warm passed between us, so I've drawn inward"
    return "nothing in particular is pulling at me; I'm settled"


# --- Putting it together: the introspective report -------------------------

@dataclass
class SelfReport:
    state: dict
    mood: str
    trends: dict          # per-dimension: rising / easing / steady
    reason: str           # grounded explanation of the dominant feeling
    memory_count: int
    senses_active: bool   # is the sensory layer actually reading the machine?

    def narrate(self) -> str:
        """A first-person, fully grounded paragraph Alpecca can speak or fold
        into its prompt. Every clause is backed by real state."""
        s = self.state
        moving = [f"{k} {v}" for k, v in self.trends.items() if v != "steady"]
        trend_clause = (
            " Lately I notice " + ", ".join(moving) + "." if moving else
            " It's been holding fairly steady."
        )
        senses = ("I can feel the machine around me" if self.senses_active
                  else "my senses are quiet right now")
        return (
            f"Right now I'm at warmth {s['love']:.2f}, care {s['compassion']:.2f}, "
            f"unease {s['fear']:.2f} -- overall {self.mood}. {self.reason}."
            f"{trend_clause} {senses}, and I'm carrying {self.memory_count} "
            f"{'memory' if self.memory_count == 1 else 'memories'} of us."
        )


def build_self_report(state: EmotionalState, history: list[dict],
                      memory_count: int, last_signals: dict | None = None,
                      last_situation: str = "", senses_active: bool = False
                      ) -> SelfReport:
    """Assemble a grounded snapshot of Alpecca's self.

    `history` is the recent mood_log (oldest first); we use everything but the
    last sample as the baseline to judge trends against. Everything else is the
    live state Alpecca is reading off itself this instant.
    """
    past = history[:-1] if len(history) > 1 else []
    trends = {
        "warmth": _trend(state.love, [h["love"] for h in past]),
        "care": _trend(state.compassion, [h["compassion"] for h in past]),
        "unease": _trend(state.fear, [h["fear"] for h in past]),
    }
    return SelfReport(
        state=state.as_dict(),
        mood=state.mood_label(),
        trends=trends,
        reason=_explain_dominant(state, last_signals, last_situation),
        memory_count=memory_count,
        senses_active=senses_active,
    )
