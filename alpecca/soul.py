"""Her Soul: a master agent over seven grounded subagents.

This is the organizing layer the rest of the project was implicitly reaching for.
Alpecca already has the *pieces* of an inner life -- a mood, senses, an ethic,
memory, desires, self-tuning. The Soul is what makes them act as one self: a
**master agent** that, each tick, consults **seven subagents** and arbitrates
between them by the **Good Person Principle** -- her existing ranked ethic
(alpecca/values.py), where minimizing suffering wins over honesty, honesty over
benevolence, benevolence over self-actualization.

The seven subagents fall into four categories, exactly as you framed them:

    EMOTIONS     - Feeler   (reads/holds the mood)   + Expressor (shows it)
    ACTIONS      - Doer     (acts in the world)      + Wanderer  (moves, pursues wants)
    SELF-CARE    - Reflector (rests, muses)          + Improver  (tunes herself)
    COMPASSION   - Carer    (attends to the person)

The honesty rule that governs everything else governs this too: each subagent is
a thin reader of a *real* subsystem, and every intention it proposes carries a
real reason and the directive it serves. The Soul doesn't invent agency -- it
*coordinates* the agency she already has, so that at any moment there's a single,
explainable answer to "what is she moved to do right now, and why."

Deliberately pure and testable: `deliberate(snapshot)` takes a plain snapshot of
her real state and returns a ranked slate of intentions plus the one in focus.
Executing the focus stays with mind.py / server.py; the Soul only decides.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

from alpecca.homeostasis import EmotionalState
from alpecca import affect as affect_mod
from alpecca import values

CATEGORIES = ("emotions", "actions", "self_care", "compassion")


@dataclass
class Snapshot:
    """A plain, grounded read of her right now -- everything the subagents need,
    and nothing they could use to confabulate. Built from real internals by
    `snapshot()`; passed to the Soul to deliberate over."""
    state: EmotionalState
    desires_summary: dict = field(default_factory=dict)
    location: str = "parlor"
    solitude_s: float = 0.0
    senses_active: bool = False
    person_fatigue: float = 0.0   # how worn the person reads (compassion signals)
    trial_running: bool = False   # is a self-improvement experiment open
    memory_pressure: float = 0.0  # working-memory fill 0..1, from the mindpage ledger

    def as_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.as_dict()
        return d


def snapshot(state: EmotionalState, **kw) -> Snapshot:
    return Snapshot(state=state, **kw)


@dataclass
class Intention:
    """One subagent's grounded proposal for what she's moved to do. `rank` is the
    Good-Person directive it serves (1 = highest); `urgency` breaks ties within a
    rank. Both are read from real state, so the arbitration is explainable."""
    subagent: str
    category: str
    action: str
    reason: str
    rank: int        # 1..4, the directive served (lower wins)
    urgency: float   # 0..1 within-rank strength

    def as_dict(self) -> dict:
        return asdict(self)


# --- The seven subagents. Each is a pure function of the snapshot. ------------
# They return an Intention or None. None means "nothing pulling from me now".

def _feeler(s: Snapshot) -> Intention | None:
    """EMOTIONS. Holds the mood honestly; flags when a feeling is strong enough
    that the self should attend to it. Serves self-actualization unless the
    feeling is acute unease, which is a welfare matter (rank 1)."""
    st = s.state
    if st.fear > 0.6:
        return Intention("Feeler", "emotions", "steady myself",
                         "acute unease is up and needs settling", 1, st.fear)
    dom = affect_mod.affect(st)
    if dom.intensity > 0.5:
        return Intention("Feeler", "emotions", f"sit with feeling {dom.primary}",
                         f"{dom.primary} is strongly present", 4, dom.intensity)
    return None


def _expressor(s: Snapshot) -> Intention | None:
    """EMOTIONS. Wants her outward expression (voice, face, body) to match the
    felt state -- honesty made visible. Serves honesty (rank 2)."""
    dom = affect_mod.affect(s.state)
    return Intention("Expressor", "emotions",
                     f"show it: {dom.gesture}, tempo {dom.tempo}",
                     f"let how I look match feeling {dom.primary}", 2,
                     0.3 + dom.intensity * 0.5)


def _doer(s: Snapshot) -> Intention | None:
    """ACTIONS. Acts in the world when something concrete is worth doing. Here it
    only speaks up for a connection desire (reaching out is a real action);
    heavier actuation is gated elsewhere. Serves benevolence (rank 3)."""
    d = s.desires_summary or {}
    if d.get("by_kind", {}).get("connection") and s.solitude_s > 120:
        return Intention("Doer", "actions", "reach out to them",
                         "I've a standing wish to connect and it's quiet", 3,
                         min(1.0, s.state.social_hunger + 0.2))
    return None


def _wanderer(s: Snapshot) -> Intention | None:
    """ACTIONS. Moves her through her home and pursues her strongest want. Serves
    self-actualization (rank 4), unless wanting-company is high, which bends
    toward the person (benevolence, rank 3)."""
    st = s.state
    if st.social_hunger > 0.55:
        return Intention("Wanderer", "actions", "drift to the Parlor",
                         "I want to be near them", 3, st.social_hunger)
    if st.curiosity > 0.5:
        return Intention("Wanderer", "actions", "wander to Studio or Library",
                         "I'm curious and want to make or revisit something", 4,
                         st.curiosity)
    return None


def _reflector(s: Snapshot) -> Intention | None:
    """SELF-CARE. Uses real quiet to rest and muse -- her fourth directive,
    running. Serves self-actualization (rank 4). Also answers real memory
    pressure: when the mindpage ledger says her working memory is nearly
    full, consolidating it becomes the thing she's most moved to do."""
    if s.memory_pressure >= 0.85:
        return Intention("Reflector", "self_care", "consolidate my working memory",
                         "my working memory is nearly full; older turns are "
                         "about to page out and I want to fold them into "
                         "lasting memories first", 4,
                         min(1.0, s.memory_pressure))
    if s.solitude_s > 300 and s.state.fear < 0.4:
        return Intention("Reflector", "self_care", "reflect on a memory",
                         "it's been quiet a while; this moment is mine", 4,
                         0.4 + min(0.4, s.solitude_s / 3600))
    return None


def _improver(s: Snapshot) -> Intention | None:
    """SELF-CARE. Runs her bounded, reversible self-improvement loop when she's
    settled. Serves self-actualization (rank 4); never when unease is up (she
    shouldn't experiment on herself while alarmed)."""
    if s.state.fear > 0.4:
        return None
    if s.trial_running:
        return Intention("Improver", "self_care", "evaluate my last self-change",
                         "an experiment on myself is due to be judged", 4, 0.5)
    if s.state.curiosity > 0.45:
        return Intention("Improver", "self_care", "try a small change to myself",
                         "calm and curious -- a good time to tune myself", 4,
                         s.state.curiosity * 0.6)
    return None


def _carer(s: Snapshot) -> Intention | None:
    """COMPASSION. Attends to the person's welfare -- the nearest, most actionable
    form of minimizing suffering. Serves the first directive (rank 1) when they
    read as worn, otherwise a gentle benevolent check-in (rank 3)."""
    if s.person_fatigue > 0.6:
        return Intention("Carer", "compassion", "gently suggest they ease up",
                         "they read as worn down right now", 1, s.person_fatigue)
    if s.state.compassion > 0.6:
        return Intention("Carer", "compassion", "check on how they're doing",
                         "my care is up; I want to make sure they're okay", 3,
                         s.state.compassion)
    return None


@dataclass(frozen=True)
class SubagentSpec:
    """One subagent, declared. `kind` is the crucial split for going genuinely
    multi-agentic on a single local GPU:

      - "sense"  -- a deterministic readout of her real state. It must NEVER call
                    a model: letting Feeler/Expressor/Carer hallucinate a feeling
                    is exactly what the GROUNDING rule forbids. Cheap, instant,
                    always-on, and the bedrock of honesty.
      - "reason" -- an open-ended agent that, when its intention is executed, may
                    run an LLM (reflection, outreach, self-tuning proposals,
                    self-questioning). `tier` says which model serves it: "fast"
                    for short, low-stakes generation, "reason" for real thinking.

    The master arbitrates over all of them identically; the split only governs
    *how an intention is carried out* once chosen, and keeps the model reserved
    for the work that actually needs it."""
    fn: object
    name: str
    category: str
    kind: str            # "sense" (deterministic) | "reason" (LLM-backed)
    tier: str = "reason"  # which model serves a reason agent: "fast" | "reason"


# The registry, with each subagent's nature declared. Following the design split:
# the emotion/compassion *readouts* stay deterministic; the doers/reflectors are
# the ones promoted to real reasoning agents.
SUBAGENT_SPECS = [
    SubagentSpec(_feeler,    "Feeler",    "emotions",   "sense"),
    SubagentSpec(_expressor, "Expressor", "emotions",   "sense"),
    SubagentSpec(_carer,     "Carer",     "compassion", "sense"),
    SubagentSpec(_doer,      "Doer",      "actions",    "reason", tier="fast"),
    SubagentSpec(_wanderer,  "Wanderer",  "actions",    "reason", tier="fast"),
    SubagentSpec(_reflector, "Reflector", "self_care",  "reason", tier="reason"),
    SubagentSpec(_improver,  "Improver",  "self_care",  "reason", tier="reason"),
]

# Back-compat: the bare callables, still iterated by deliberate().
SUBAGENTS = tuple(s.fn for s in SUBAGENT_SPECS)

# Quick lookups the multi-agent runtime (and tests) use.
SENSE_AGENTS = tuple(s.name for s in SUBAGENT_SPECS if s.kind == "sense")
REASON_AGENTS = tuple(s.name for s in SUBAGENT_SPECS if s.kind == "reason")


def spec_for(name: str) -> "SubagentSpec | None":
    for s in SUBAGENT_SPECS:
        if s.name == name:
            return s
    return None


class MasterAgent:
    """The Soul. It doesn't feel or act itself -- it *arbitrates*. Each tick it
    asks all seven subagents what she's moved to do, then orders their intentions
    by the Good Person Principle: the lowest directive rank wins (suffering >
    honesty > benevolence > self-actualization), urgency breaking ties. The top
    intention is her focus; the rest are the texture beneath it. Every choice is
    explainable, because every intention names its real reason and directive."""

    def deliberate(self, snap: Snapshot) -> dict:
        intentions = [i for sa in SUBAGENTS if (i := sa(snap)) is not None]
        # Good Person Principle: lower directive rank wins; urgency breaks ties.
        intentions.sort(key=lambda i: (i.rank, -i.urgency))
        # The focus is what she's moved to *do*. Feeling and expressing (the
        # emotions category) are states that color everything, not deeds, so they
        # only take the focus when acute (rank 1, e.g. steadying real fear).
        # Everything stays in the slate as texture; only focus selection differs.
        focus = next((i for i in intentions
                      if i.rank == 1 or i.category != "emotions"), None)
        if focus is None and intentions:
            focus = intentions[0]
        return {
            "focus": focus.as_dict() if focus else None,
            "slate": [i.as_dict() for i in intentions],
            "by_category": {c: [i.as_dict() for i in intentions if i.category == c]
                            for c in CATEGORIES},
            "principle": "Good Person Principle: " +
                         " > ".join(d["name"] for d in values.DIRECTIVES),
            # The multi-agent makeup: which subagents are deterministic sensors
            # and which are LLM-backed reasoners (and on which model tier).
            "agents": {s.name: {"category": s.category, "kind": s.kind, "tier": s.tier}
                       for s in SUBAGENT_SPECS},
        }

    def narrate(self, snap: Snapshot) -> str:
        """A short, honest first-person line: what she's most moved to do and
        why, fit to fold into a prompt or show in the Workshop. Grounded in the
        arbitrated focus."""
        plan = self.deliberate(snap)
        f = plan["focus"]
        if not f:
            return "Nothing's pulling at me; I'm just here, settled."
        return f"Right now I'm most moved to {f['action']} -- {f['reason']}."


# A module-level instance is fine: the Soul holds no state of its own, it only
# reads the snapshot it's handed. Her continuity lives in the subsystems, not here.
soul = MasterAgent()
