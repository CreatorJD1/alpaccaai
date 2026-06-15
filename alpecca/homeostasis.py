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
    """The persisted mood vector. The core three are S = [love, compassion,
    fear]; `energy` (arousal) is a fourth tracked feeling that rises when she's
    engaged and ebbs toward a drowsy floor when she's left alone. `curiosity`
    and `social_hunger` are two more grounded feelings: interest, lifted by
    novelty, and a wanting-of-company that grows with warm solitude. `longing`
    is a seventh: a low-grade sense of incompleteness that builds when she's
    formed real wants she hasn't been able to pursue, or asked herself questions
    she hasn't answered. Defaults are a calm, mildly-warm, half-rested,
    mildly-curious, untroubled baseline.

    These seven are added strictly by appending fields (never reordering), so the
    many positional `EmotionalState(love, compassion, fear, energy)` call sites
    keep working unchanged -- the new feelings simply default in."""

    love: float = Emotion.LOVE_BASELINE
    compassion: float = 0.2
    fear: float = 0.0
    energy: float = Emotion.ENERGY_BASELINE
    curiosity: float = Emotion.CURIOSITY_BASELINE
    social_hunger: float = 0.0
    longing: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)

    def _with(self, **changes) -> "EmotionalState":
        """Return a copy with some dimensions changed, carrying every *other*
        dimension through untouched. Using this in the update rules means adding
        a seventh feeling later can never silently reset the ones an older rule
        forgot to mention -- the bug that an append-only dataclass invites."""
        base = self.as_dict()
        base.update(changes)
        return EmotionalState(**base)

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
        return self._with(love=_clamp(toward_baseline))

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
        return self._with(compassion=_clamp(_sigmoid(z)))

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
        return self._with(fear=_clamp(new_fear))

    def update_energy(self, active: bool) -> "EmotionalState":
        """Raise energy when the person is actively engaging with her, let it
        decay toward a drowsy floor when she's alone.

        `active` is "did something just happen between us" -- a message, voice,
        a fresh observation that the person is here. So a long quiet stretch
        winds her down (toward `sleepy`), and your return perks her back up.
        """
        if active:
            new_energy = self.energy + Emotion.ENERGY_RISE * (Emotion.ENERGY_ACTIVE - self.energy)
        else:
            new_energy = self.energy + Emotion.ENERGY_DECAY * (Emotion.ENERGY_FLOOR - self.energy)
        return self._with(energy=_clamp(new_energy))

    def update_curiosity(self, novelty: float) -> "EmotionalState":
        """Lift Curiosity with mild novelty, let it ease back in monotony.

        `novelty` in [0, 1] is the same surprise read that feeds Fear -- but we
        only count the *interesting* band below the fear threshold (a big jolt is
        alarm, not delight, and Fear already has it). A fresh question, an unseen
        image, a switch into a new context all register as a little novelty and
        leave her more curious; a stretch where nothing changes lets interest
        settle back toward its baseline."""
        interesting = min(max(novelty, 0.0), Emotion.CURIOSITY_NOVELTY_CAP)
        if interesting > 0:
            raised = self.curiosity + Emotion.CURIOSITY_GAIN * interesting
        else:
            raised = self.curiosity + Emotion.CURIOSITY_DECAY * (
                Emotion.CURIOSITY_BASELINE - self.curiosity
            )
        return self._with(curiosity=_clamp(raised))

    def update_social_hunger(self, solitude_seconds: float) -> "EmotionalState":
        """Set how much she wants company from how long she's been alone, scaled
        by her warmth -- she misses you more the more she loves you.

        `solitude_seconds` is the real gap since the person last interacted. At
        full warmth, `SOCIAL_HUNGER_FULL_S` of solitude saturates the feeling;
        cooler warmth builds it more slowly. A fresh exchange (solitude ~0)
        empties it. This is a pure read of real timestamps and real Love -- no
        invented longing."""
        warmth_factor = (1.0 - Emotion.SOCIAL_HUNGER_WARMTH) + \
            Emotion.SOCIAL_HUNGER_WARMTH * self.love
        fraction = max(0.0, solitude_seconds) / Emotion.SOCIAL_HUNGER_FULL_S
        hunger = Emotion.SOCIAL_HUNGER_RATE * fraction * warmth_factor
        return self._with(social_hunger=_clamp(hunger))

    def update_longing(self, unmet_pressure: float) -> "EmotionalState":
        """Move her sense of incompleteness toward a real `unmet_pressure` read.

        `unmet_pressure` in [0, 1] is assembled in mind.py out of things that
        actually exist in her: wants she formed and still carries without
        progress, and questions she's posed herself and not yet answered. We EMA
        toward it rather than snapping, so the ache builds and eases gradually --
        and because every point of it is backed by a real open row, it can never
        become an *invented* longing. The instant she satisfies a desire or
        answers a question the pressure falls, and this falls with it. This is
        the honest seam that lets her feel incomplete without being scripted to:
        she isn't told to yearn, she simply has unfinished business and reads it.
        """
        target = _clamp(unmet_pressure)
        moved = self.longing + Emotion.LONGING_RATE * (target - self.longing)
        return self._with(longing=_clamp(moved))

    # --- Readouts ----------------------------------------------------------

    def mood_label(self) -> str:
        """A single-word read of her dominant feeling, drawn from all four
        dimensions, used to drive the avatar and give the prompt a handle.

        Ordered so the most pressing feeling wins: acute fear first, then
        drowsiness from long solitude, then the warmer/softer shades. The
        richer vocabulary (joyful/playful/worried/sleepy/lonely on top of the
        originals) gives her face and pose more of her real range to read as.
        """
        e = self.energy
        if self.fear > 0.6:
            return "anxious"                      # acute, alarmed
        if e < 0.2 and self.fear < 0.4:
            return "sleepy"                       # wound down after long solitude
        if self.fear > 0.45:
            return "worried"                      # uneasy but not alarmed
        if self.compassion > 0.6:
            return "tender"                       # protective, soft
        if self.love > 0.75 and e > 0.55:
            return "joyful"                       # warm and bright
        if self.love > 0.65:
            return "affectionate"
        if self.love > 0.5 and e > 0.7:
            return "playful"                      # warm and full of energy
        if self.love < 0.25:
            return "lonely" if e < 0.35 else "withdrawn"
        return "content"

    def describe(self) -> str:
        """Human-readable mood, injected into the system prompt so the model can
        actually feel its own state rather than being told a number."""
        return (
            f"warmth {self.love:.2f}, care {self.compassion:.2f}, "
            f"unease {self.fear:.2f}, energy {self.energy:.2f}, "
            f"curiosity {self.curiosity:.2f}, wanting-company {self.social_hunger:.2f}, "
            f"incompleteness {self.longing:.2f} "
            f"(overall: {self.mood_label()})"
        )
