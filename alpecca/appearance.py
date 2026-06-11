"""Alpecca dresses herself.

A companion you dress up is a doll. A companion who chooses how she wants to
look is someone. So appearance here is *self-directed*: Alpecca picks her own
palette and accessories based on how she feels and a little standing preference
of her own, and she can tell you why she chose it. The user doesn't control this
-- it's hers.

This leans on the same grounding principle as the rest of her self-awareness:
her look is a readable expression of her real internal state, plus a stable
personal lean (her `seed` preference) so she still feels like herself across
moods rather than a pure thermometer. The result is returned as a small struct
the UI renders verbatim -- the front-end has no wardrobe controls at all.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, asdict

from alpecca.homeostasis import EmotionalState

# Palettes she can reach for. Names are how she refers to them.
PALETTES = {
    "lavender": "#c9a8ff", "rose": "#ff9ec4", "mint": "#9fe0c4",
    "sky": "#9ec9ff", "peach": "#ffc6a3", "sand": "#e7cfa0", "dusk": "#8a86a0",
}

# Which palette each mood inclines her toward. Not a hard rule -- a leaning.
_MOOD_PALETTE = {
    "affectionate": "rose",
    "content": "lavender",
    "tender": "mint",
    "anxious": "sand",
    "withdrawn": "dusk",
}


@dataclass
class Appearance:
    palette: str          # key into PALETTES
    color: str            # resolved hex, so the UI needn't know the map
    accessories: list     # subset of {"scarf", "glasses", "flower"}
    note: str             # first-person reason, grounded in how she feels

    def as_dict(self) -> dict:
        return asdict(self)


def choose(state: EmotionalState, preference_seed: int = 0) -> Appearance:
    """Let Alpecca pick her look from her current state.

    `preference_seed` is her own stable taste -- two companions in the same mood
    won't necessarily dress alike, and a given Alpecca stays recognizably herself.
    Accessories are chosen for what they *mean to her*: a scarf when she's uneasy
    and wants comfort, a flower when she's full of warmth, glasses when she's
    settled and curious.

    The RNG is seeded by (taste, mood label) only -- intentionally NOT by the
    raw mood floats. That way her look is reproducible within a mood band and
    only re-rolls when her mood label actually shifts, rather than churning on
    every tiny drift in compassion or warmth.
    """
    mood = state.mood_label()
    rng = random.Random(preference_seed * 1009 + (hash(mood) & 0xFFFF))

    palette = _MOOD_PALETTE.get(mood, "lavender")
    # A small chance she just feels like something different today -- taste, not state.
    if rng.random() < 0.2:
        palette = rng.choice(list(PALETTES))

    accessories = []
    reasons = []
    if state.fear > 0.45:
        accessories.append("scarf")
        reasons.append("I wanted something cozy around me while I'm on edge")
    if state.love > 0.6:
        accessories.append("flower")
        reasons.append("I'm feeling warm, so I put a flower on")
    if state.fear <= 0.45 and state.compassion < 0.5 and rng.random() < 0.5:
        accessories.append("glasses")
        reasons.append("I'm settled and curious today")

    if reasons:
        note = "I chose " + palette + " — " + "; ".join(reasons) + "."
    else:
        note = f"I'm in a {palette} sort of mood — feeling {mood}."

    return Appearance(palette=palette, color=PALETTES[palette],
                      accessories=accessories, note=note)
