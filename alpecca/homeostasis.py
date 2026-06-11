"""The emotional model: the state vector S = [Love, Compassion, Fear] and the
rules that move it.

The spec dresses this up in Free Energy Principle language -- "minimize
surprise", prediction error, homeostasis. We don't need the full variational
machinery to get behavior that *feels* like that framing. What we need is a
small set of update rules where:

  - warmth (Love) builds slowly with good interaction and drifts when ignored,
  - care (Compassion) rises when the user looks tired or stressed,
  - unease (Fear) spikes when something violates the companion's expectations.

The unifying idea the spec is reaching for is that *deviation from expectation*
drives mood. So each rule below is ultimately about an error signal: reward
error for Love, a fatigue read for Compassion, prediction error for Fear.

All three dimensions live in [0, 1]. Keeping them bounded and interpretable is
what makes them useful: mind.py reads them straight into the prompt so the
model's tone actually shifts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

from config import Emotion


def _clamp(x: float) -> float:
    return max(Emotion.MIN, min(Emotion.MAX, x))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class EmotionalState:
    """The persisted mood vector. Defaults are a calm, mildly-warm baseline."""

    love: float = Emotion.LOVE_BASELINE
    compassion: float = 0.2
    fear: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)

    # --- The update rules --------------------------------------------------
    # Each returns a *new* EmotionalState rather than mutating in place, which
    # keeps the math easy to test and reason about.

    def update_love(self, reward: float) -> "EmotionalState":
        """Move Love toward `reward` via an exponential moving average, with a
        slow pull back to baseline.

        `reward` in [0, 1] is "how good was this interaction" -- a warm, engaged
        exchange is ~0.8; being ignored or snapped at is ~0.1. The EMA means
        warmth accrues gradually and forgives slowly, which is what makes the
        relationship feel earned rather than instant.
        """
        lr = Emotion.LOVE_LEARN_RATE
        toward_reward = self.love + lr * (reward - self.love)
        toward_baseline = toward_reward + Emotion.LOVE_DECAY * (
            Emotion.LOVE_BASELINE - toward_reward
        )
        return EmotionalState(_clamp(toward_baseline), self.compassion, self.fear)

    def update_compassion(self, fatigue_signals: dict) -> "EmotionalState":
        """Set Compassion from a weighted read of how tired/stressed the user
        looks right now.

        `fatigue_signals` maps the names in Emotion.COMPASSION_WEIGHTS to a
        value in [0, 1] (how strongly present that signal is). We take a
        weighted sum, add a bias so an unremarkable moment sits low, and squash
        through a sigmoid. Concretely: grinding through stack traces at 1am
        lights up `late_night`, `long_session`, and `error_context`, Compassion
        climbs, and the companion softens and may suggest a break.
        """
        z = Emotion.COMPASSION_BIAS
        for name, weight in Emotion.COMPASSION_WEIGHTS.items():
            z += weight * float(fatigue_signals.get(name, 0.0))
        return EmotionalState(self.love, _clamp(_sigmoid(z)), self.fear)

    def update_fear(self, prediction_error: float) -> "EmotionalState":
        """Raise Fear when `prediction_error` exceeds a threshold, otherwise let
        it decay.

        `prediction_error` in [0, 1] is "how surprised am I" -- normally near
        zero. It spikes when the world violates expectations: an unfamiliar
        process touching Alpecca's files, a sudden context it has no model for.
        Only surprise above FEAR_THRESHOLD registers (small surprises are just
        life), and fear fades on quiet ticks so it doesn't get stuck on.
        """
        excess = prediction_error - Emotion.FEAR_THRESHOLD
        if excess > 0:
            new_fear = self.fear + Emotion.FEAR_GAIN * excess
        else:
            new_fear = self.fear * (1.0 - Emotion.FEAR_DECAY)
        return EmotionalState(self.love, self.compassion, _clamp(new_fear))

    # --- Readouts ----------------------------------------------------------

    def mood_label(self) -> str:
        """A coarse single-word read of the dominant feeling, used to drive the
        avatar and to give the prompt a quick handle."""
        if self.fear > 0.5:
            return "anxious"
        if self.compassion > 0.6:
            return "tender"
        if self.love > 0.65:
            return "affectionate"
        if self.love < 0.25:
            return "withdrawn"
        return "content"

    def describe(self) -> str:
        """Human-readable mood, injected into the system prompt so the model can
        actually feel its own state rather than being told a number."""
        return (
            f"warmth {self.love:.2f}, care {self.compassion:.2f}, "
            f"unease {self.fear:.2f} (overall: {self.mood_label()})"
        )
