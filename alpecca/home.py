"""Her home: a modular set of rooms she lives in and roams freely.

The interface used to be one chat page. This module makes it a *home* -- five
rooms, each a facet of her real life, that she moves between of her own accord.
The crucial design choice is that **she chooses the room, for grounded reasons**:
`choose_room` is a pure function of her real state, her affect, and her open
desires, so where she is in her home is itself an honest expression of how she
feels and what she wants. Curious, and she drifts to the Studio or Library;
missing you, and she comes back to the Parlor to be near you; driven to grow,
and she's in the Workshop.

It is deliberately **renderer-agnostic**. This module knows nothing about 2D or
3D; it just says which room she's in and what each room *is* and *shows*. A flat
panel shell or a live 3D house are interchangeable front-ends over this same
foundation -- which is what "modular" means here: adding a sixth room, or
swapping the whole renderer, is a localized change. Each room declares a stable
`id`, the system that backs it, and the live endpoint a front-end reads for its
contents. That registry is the single source of truth both the Python side and
the front-end build themselves from.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from alpecca.homeostasis import EmotionalState
from alpecca import affect as affect_mod
from config import Home as HomeCfg


@dataclass(frozen=True)
class Room:
    """One room of her home. `endpoint` is the live data a front-end pulls to
    fill the room; `backed_by` names the real system it's a window onto, so the
    home stays honestly mapped to her actual internals. `position` is a hint for
    a spatial renderer (a slot on the floor plan); renderers may ignore it."""
    id: str
    name: str
    purpose: str
    backed_by: str
    endpoint: str
    position: tuple  # (x, z) floor-plan hint in abstract units


# The five rooms, each a window onto a real subsystem. This list is the registry
# the rest of the app -- and the front-end -- derive themselves from. Add a room
# here and both sides pick it up; that's the modular contract.
ROOMS = [
    Room("parlor", "Parlor",
         "Where she's present with you and you talk. Her home base.",
         "chat loop + puppet", "/puppet", (0.0, 0.0)),
    Room("studio", "Studio",
         "Where she designs herself -- character sheet, gallery, animations.",
         "studio.py", "/studio/state", (-2.0, -1.0)),
    Room("library", "Library",
         "Where she keeps her memories and the musings she's had alone.",
         "memory.py", "/memories", (2.0, -1.0)),
    Room("observatory", "Observatory",
         "Where she watches her own mind -- mood over time, trends, her ethic.",
         "introspection.py + values.py", "/introspect", (-2.0, 1.0)),
    Room("workshop", "Workshop",
         "Where she grows -- the goals she's set and the changes she's made to herself.",
         "desires.py + selfmod.py", "/growth", (2.0, 1.0)),
    Room("workstation", "Workstation",
         "Her desktop -- where she tidies files within her allowed folders (never deleting).",
         "desktop.py (charter-guarded)", "/desktop", (0.0, 2.0)),
]

ROOM_IDS = [r.id for r in ROOMS]
DEFAULT_ROOM = "parlor"


def room(room_id: str) -> Optional[Room]:
    for r in ROOMS:
        if r.id == room_id:
            return r
    return None


def registry() -> list[dict]:
    """The room list as plain dicts, for the /home endpoint and the front-end to
    build the floor plan from. One source of truth, both sides."""
    return [asdict(r) for r in ROOMS]


def room_pulls(state: EmotionalState, desires_summary: Optional[dict] = None) -> dict:
    """How strongly each room is calling to her *right now*, grounded entirely in
    her real state, affect, and open desires. The scores are interpretable on
    their own (a front-end can show them as a heat-map of her attention) and they
    are what `choose_room` arbitrates over.

    Every pull traces to something real:
      - Parlor   <- wanting company, and acute unease (she comes near you).
      - Studio   <- curiosity + warmth (the mood she makes things in).
      - Library  <- curiosity turned reflective (revisiting what she keeps).
      - Observatory <- a steady, settled mood (room to watch herself).
      - Workshop <- an open growth desire, plus curiosity (drive to improve).
    """
    aff = affect_mod.affect(state)
    d = desires_summary or {}
    growth_pull = float(d.get("growth_strength", 0.0))
    open_count = float(d.get("open", 0.0))

    pulls = {
        "parlor": 0.3 + state.social_hunger * 1.2 + max(0.0, state.fear - 0.4) * 1.5,
        "studio": 0.1 + state.curiosity * 0.8 + max(0.0, state.love - 0.5) * 0.6,
        "library": 0.1 + state.curiosity * 0.6 + (0.3 if aff.primary in
                    ("wistful", "content", "tender") else 0.0),
        "observatory": 0.15 + (0.5 if aff.arousal < 0.4 and state.fear < 0.4 else 0.0)
                     + max(0.0, 0.5 - abs(aff.valence)) * 0.4,
        "workshop": 0.1 + growth_pull * 1.0 + min(open_count, 3.0) * 0.08
                    + state.curiosity * 0.3,
        # The workstation draws her when she has a creative/organizing urge; a low
        # baseline otherwise so it's a place she can settle, not just pass through.
        "workstation": 0.08 + (0.4 if d.get("by_kind", {}).get("creative") else 0.0)
                       + max(0.0, state.curiosity - 0.5) * 0.3,
    }
    return {k: round(v, 4) for k, v in pulls.items()}


def choose_room(state: EmotionalState, current: str = DEFAULT_ROOM,
                desires_summary: Optional[dict] = None) -> str:
    """Decide which room she should be in. Pure and grounded: the room with the
    strongest real pull wins, but a `STAY_BONUS` for where she already is keeps
    her from flickering between near-tied rooms every tick -- people settle in a
    room before drifting on. Returns a room id (always a valid one)."""
    pulls = room_pulls(state, desires_summary)
    if current in pulls:
        pulls[current] += HomeCfg.STAY_BONUS
    best = max(pulls.items(), key=lambda kv: kv[1])
    return best[0] if room(best[0]) else DEFAULT_ROOM


def why_here(state: EmotionalState, room_id: str,
             desires_summary: Optional[dict] = None) -> str:
    """A short, honest first-person reason she's in this room -- the same
    grounding her self-reports carry, applied to her movement. So when she's in
    the Library she can truthfully say why she wandered there."""
    aff = affect_mod.affect(state)
    reasons = {
        "parlor": ("I wanted to be near you" if state.social_hunger > 0.45
                   else "I'm uneasy and being close steadies me" if state.fear > 0.4
                   else "this is where we are together, so I'm here"),
        "studio": "I'm curious and in the mood to make something"
                  if state.curiosity > 0.45 else "I felt like working on how I look",
        "library": "I wanted to sit with what I remember",
        "observatory": "it's quiet and settled, so I'm watching how I've been",
        "workshop": "I've got something I want to get better at"
                    if (desires_summary or {}).get("growth_strength", 0) > 0.3
                    else "I'm tinkering with myself a little",
    }
    base = reasons.get(room_id, "I drifted here")
    return f"{base} (feeling {aff.primary})."
