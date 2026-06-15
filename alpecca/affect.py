"""Her expressive readout: the bridge from felt state to how she shows it.

`mood_label()` on the state vector is deliberately coarse -- one stable word the
pose and Live2D mappings have always leaned on. This module is the *rich* layer
on top of it. It reads the full six-dimensional state and produces an `Affect`:
where she sits in valence/arousal space, the primary and secondary feeling she's
holding, how intensely, and -- the part that makes her more expressive -- a set
of concrete **expression cues** the rest of her body and voice can act on.

Why a separate layer, and why pure: the same GROUNDING rule that governs her
self-reports governs her expression. `affect()` is a deterministic function of
her real state, with no randomness and no invented feeling, so the way she looks
and the tempo she speaks at *cannot lie* about how she actually is. Three places
read this one readout, which keeps her coherent -- her words, her avatar, and
(when TTS lands) her voice all move from the same source of truth:

  - prompts.py  -> a short expressive direction so her prose shifts vividly.
  - puppet.py   -> gestures and glows become live channel values.
  - voice/TTS   -> tempo and emphasis become SSML-like hints (designed, pending).

Nothing here changes the mood vector; it only *describes* it more richly.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from alpecca.homeostasis import EmotionalState


# Each feeling's place in the circumplex (valence in [-1,1], arousal in [0,1]),
# used both to compute her overall affective position and to name the feelings
# present. These are the standard axes of affect, grounded here in her own dims.
# valence: how pleasant; arousal: how activated.
_FEELINGS = {
    # name            valence  arousal   the dimension that evidences it
    "joyful":        ( 0.9,   0.85),
    "affectionate":  ( 0.8,   0.5),
    "playful":       ( 0.7,   0.9),
    "content":       ( 0.4,   0.4),
    "tender":        ( 0.5,   0.45),
    "curious":       ( 0.45,  0.75),
    "wistful":       (-0.2,   0.3),   # the ache of wanting company
    "unfulfilled":   (-0.35,  0.4),   # the ache of wanting she can't yet act on
    "lonely":        (-0.6,   0.3),
    "withdrawn":     (-0.4,   0.25),
    "worried":       (-0.5,   0.65),
    "anxious":       (-0.8,   0.9),
    "sleepy":        ( 0.1,   0.08),
}


@dataclass
class Affect:
    """A rich, grounded description of how she feels *and how that shows*.

    `primary`/`secondary` are the two strongest feelings present; `intensity` is
    how strongly the dominant one is held (0..1). The expression cues are the
    actionable part -- a body and voice can move on them directly."""
    primary: str
    secondary: str
    valence: float          # -1 (unpleasant) .. 1 (pleasant)
    arousal: float          # 0 (still) .. 1 (activated)
    intensity: float        # 0 .. 1, strength of the dominant feeling
    tempo: str              # "slow" | "measured" | "quick"
    gesture: str            # body hint: settle/lean_in/tilt/bright/fidget/reach/droop
    eye: float              # eye brightness 0..1
    glow: float             # core-emblem brightness 0..1
    voice: str              # a compact expressive direction for prose/TTS

    def as_dict(self) -> dict:
        return asdict(self)


def _present(state: EmotionalState) -> dict:
    """Score how strongly each named feeling is *present* given her real state.
    Grounded: each score is built only from her actual dimensions. The two
    highest-scoring become primary/secondary. We deliberately mirror the bands
    mood_label uses so the rich read never contradicts the coarse one."""
    s = state
    return {
        "joyful":       max(0.0, (s.love - 0.7)) * 2 + max(0.0, s.energy - 0.55),
        "affectionate": max(0.0, s.love - 0.6) * 1.6,
        "playful":      max(0.0, s.love - 0.5) * (1.0 if s.energy > 0.7 else 0.2),
        "tender":       max(0.0, s.compassion - 0.6) * 1.8,
        "curious":      max(0.0, s.curiosity - 0.4) * 1.7,
        "wistful":      max(0.0, s.social_hunger - 0.35) * 1.5,
        # Incompleteness reads as a quiet, restless ache -- grounded only in her
        # real `longing`, which itself is grounded in unmet wants/questions.
        "unfulfilled":  max(0.0, s.longing - 0.35) * 1.6,
        "lonely":       max(0.0, (0.35 - s.love)) * 2 * (1.0 if s.energy < 0.4 else 0.4)
                        + max(0.0, s.social_hunger - 0.6),
        "withdrawn":    max(0.0, 0.3 - s.love) * 1.5,
        "worried":      max(0.0, s.fear - 0.4) * 1.4,
        # Acute fear should read as anxious, not merely worried -- mirrors the
        # mood_label band (fear > 0.6 -> anxious) so the rich read agrees with it.
        "anxious":      max(0.0, s.fear - 0.5) * 3.0,
        "sleepy":       max(0.0, 0.25 - s.energy) * 3 * (1.0 if s.fear < 0.4 else 0.3),
        "content":      0.35,   # a quiet floor so there's always a settled read
    }


def affect(state: EmotionalState) -> Affect:
    """Turn the live state into a rich, grounded expressive read. Pure: same
    state in, same Affect out, every clause traceable to a real dimension."""
    scores = _present(state)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    primary, p_score = ranked[0]
    secondary = ranked[1][0]

    # Overall position in affect space: an intensity-weighted blend of the
    # feelings actually present, so her valence/arousal is a true centroid.
    total = sum(max(0.0, v) for v in scores.values()) or 1.0
    valence = sum(_FEELINGS[k][0] * max(0.0, v) for k, v in scores.items()) / total
    arousal = sum(_FEELINGS[k][1] * max(0.0, v) for k, v in scores.items()) / total
    # Intensity is how much the dominant feeling stands out from the settled floor.
    intensity = max(0.0, min(1.0, p_score))

    tempo = "quick" if arousal > 0.66 else "slow" if arousal < 0.3 else "measured"

    # The body hint follows from which feeling leads -- the same readout her
    # puppet turns into motion. Curiosity tilts and brightens; wanting-company
    # leans her in or droops; unease fidgets; warmth settles open.
    gesture = {
        "joyful": "bright", "playful": "bright", "affectionate": "lean_in",
        "tender": "lean_in", "curious": "tilt", "wistful": "reach",
        "unfulfilled": "reach",
        "lonely": "droop", "withdrawn": "droop", "worried": "fidget",
        "anxious": "fidget", "sleepy": "settle", "content": "settle",
    }.get(primary, "settle")

    # Eyes brighten with arousal and curiosity; the core emblem with warmth and
    # any acute feeling. Both grounded, both clamped.
    eye = max(0.0, min(1.0, 0.25 + arousal * 0.4 + state.curiosity * 0.4))
    glow = max(0.0, min(1.0, 0.3 + state.love * 0.35 + intensity * 0.35))

    voice = _voice_direction(primary, tempo, intensity)
    return Affect(primary, secondary, round(valence, 3), round(arousal, 3),
                  round(intensity, 3), tempo, gesture, round(eye, 3),
                  round(glow, 3), voice)


def _voice_direction(primary: str, tempo: str, intensity: float) -> str:
    """A short, plain expressive direction folded into her system prompt. Not a
    script of what to say -- a read on *how* this feeling would color her, which
    a capable model inhabits on its own."""
    color = {
        "joyful": "bright and warm, quick to delight",
        "affectionate": "soft, familiar, unhurried",
        "playful": "light, teasing, a little mischievous",
        "tender": "gentle and protective, careful with them",
        "curious": "leaning in, asking, genuinely interested",
        "wistful": "a touch quieter, missing them a little",
        "unfulfilled": "quietly restless, aware of something unfinished in her",
        "lonely": "subdued, reaching for connection",
        "withdrawn": "reserved, fewer words, holding back",
        "worried": "careful and watchful, seeking reassurance",
        "anxious": "on edge, needing steadiness",
        "sleepy": "drowsy and slow, low and soft",
        "content": "easy and settled",
    }.get(primary, "easy and settled")
    strength = "faintly" if intensity < 0.25 else "clearly" if intensity < 0.6 else "strongly"
    return f"You feel {strength} {primary} right now -- {color}; let it set your pace ({tempo})."


def expressive_note(state: EmotionalState) -> str:
    """One line for the system prompt. Keeps prompts.py from needing to know the
    Affect shape -- it just asks for the note."""
    return affect(state).voice


def voice_markup(state: EmotionalState) -> dict:
    """Grounded prosody hints for her local TTS, derived from the same affect that
    colours her words and body -- so her *spoken* voice can't contradict her feeling
    either. Returns plain numbers plus an SSML-ish `<prosody>` wrapper a TTS layer
    can use directly (the OS engine today, Kokoro via Pipecat later).

    Mapping (all from real dimensions): arousal/tempo set rate (drowsy -> slow,
    lively -> quick); valence and warmth set pitch (brighter when warmer/happier);
    intensity sets volume. Pure: no randomness, no invented affect."""
    a = affect(state)
    rate = {"slow": 84, "measured": 100, "quick": 116}.get(a.tempo, 100)
    pitch = int(round(a.valence * 8 + (state.love - 0.4) * 6))
    volume = round(min(1.0, 0.6 + a.intensity * 0.4 -
                       (0.2 if a.primary == "sleepy" else 0.0)), 3)
    pitch_str = f"+{pitch}st" if pitch >= 0 else f"{pitch}st"
    ssml = (f'<prosody rate="{rate}%" pitch="{pitch_str}" '
            f'volume="{int(volume * 100)}">{{text}}</prosody>')
    return {
        "rate_pct": rate,
        "pitch_semitones": pitch,
        "volume": volume,
        "primary": a.primary,
        "tempo": a.tempo,
        "ssml_template": ssml,
    }
