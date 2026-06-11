"""A small, dependency-free sentiment model.

`prompts.estimate_reward` used to be a handful of hardcoded keywords -- fine as a
placeholder, but it meant Love barely tracked the actual warmth of a
conversation. This module replaces that with a proper lexicon-based scorer that
understands the things that flip or amplify sentiment in real messages:

  - negation   ("not good", "no longer happy") inverts the words that follow,
  - intensifiers ("really", "so") scale the next word up,
  - dampeners  ("kind of", "a little") scale it down,
  - emphasis   (ALL CAPS, exclamation marks) nudges magnitude.

It's deliberately self-contained (no model download, runs offline) so Alpacca's
emotional learning works out of the box. For higher fidelity you can flip on the
Ollama path (`score_llm`) which asks the local model to rate sentiment; we keep
the lexicon as the always-available default and graceful fallback.

The output contract: `score(text)` returns a float in [-1, 1]; `reward(text)`
maps that to the [0, 1] signal the Love update expects.
"""
from __future__ import annotations

import re

# A compact affective lexicon. Values are rough valence in [-1, 1]. This isn't
# meant to be exhaustive -- it covers the everyday vocabulary of a companion
# chat, and it's trivial to extend.
_LEXICON = {
    # positive
    "love": 0.9, "adore": 0.9, "amazing": 0.8, "wonderful": 0.8, "great": 0.7,
    "good": 0.6, "nice": 0.55, "happy": 0.75, "glad": 0.6, "thank": 0.6,
    "thanks": 0.6, "appreciate": 0.7, "fun": 0.6, "cool": 0.5, "sweet": 0.6,
    "beautiful": 0.7, "perfect": 0.8, "best": 0.7, "enjoy": 0.65, "excited": 0.7,
    "miss": 0.4, "care": 0.5, "kind": 0.55, "proud": 0.65, "haha": 0.5,
    "lol": 0.45, "yay": 0.7, "awesome": 0.8, "brilliant": 0.75, "warm": 0.5,
    # negative
    "hate": -0.9, "awful": -0.8, "terrible": -0.8, "bad": -0.6, "sad": -0.6,
    "angry": -0.7, "annoying": -0.6, "annoyed": -0.6, "useless": -0.7,
    "stupid": -0.7, "ugly": -0.6, "worst": -0.8, "horrible": -0.8,
    "disappointed": -0.65, "upset": -0.6, "tired": -0.3, "bored": -0.45,
    "lonely": -0.6, "afraid": -0.55, "hurt": -0.6, "shut": -0.5, "sucks": -0.7,
    "ugh": -0.4, "cry": -0.5, "depressed": -0.7, "anxious": -0.5, "stressed": -0.55,
}

_NEGATIONS = {"not", "no", "never", "n't", "without", "hardly", "barely", "neither", "nor"}
_INTENSIFIERS = {"really": 1.5, "very": 1.5, "so": 1.4, "extremely": 1.8,
                 "incredibly": 1.8, "absolutely": 1.7, "totally": 1.5, "super": 1.5}
_DAMPENERS = {"kind": 0.6, "sort": 0.6, "little": 0.6, "bit": 0.6, "slightly": 0.5,
              "somewhat": 0.7, "barely": 0.4}

_WORD = re.compile(r"[a-z']+", re.I)


def score(text: str) -> float:
    """Valence of `text` in [-1, 1]. 0 means neutral / no signal found."""
    if not text:
        return 0.0
    raw = text
    words = _WORD.findall(text.lower())
    total = 0.0
    hits = 0
    for i, w in enumerate(words):
        val = _LEXICON.get(w)
        if val is None:
            continue
        # Look back up to two words for negation / intensity modifiers.
        mult = 1.0
        negated = False
        for j in (i - 1, i - 2):
            if j < 0:
                break
            prev = words[j]
            if prev in _NEGATIONS:
                negated = True
            if prev in _INTENSIFIERS:
                mult *= _INTENSIFIERS[prev]
            if prev in _DAMPENERS:
                mult *= _DAMPENERS[prev]
        v = val * mult
        if negated:
            v = -0.7 * v  # negation flips and slightly weakens
        total += v
        hits += 1

    if hits == 0:
        base = 0.0
    else:
        base = total / hits  # average so long messages aren't over-weighted

    # Emphasis cues amplify whatever signal exists.
    if base != 0.0:
        if "!" in raw:
            base *= 1.1 + 0.1 * min(raw.count("!"), 3)
        caps_words = [w for w in raw.split() if len(w) > 2 and w.isupper()]
        if caps_words:
            base *= 1.15

    return max(-1.0, min(1.0, base))


def reward(text: str) -> float:
    """Map sentiment in [-1, 1] to the Love reward signal in [0, 1].

    A neutral message lands near 0.5 (mildly positive baseline -- engagement
    itself is gently rewarding), warmth pushes toward 1, hostility toward 0.
    """
    s = score(text)
    return max(0.0, min(1.0, 0.55 + 0.45 * s))


def score_llm(text: str, client=None, model: str | None = None) -> float | None:
    """Optional: ask a local Ollama model to rate sentiment in [-1, 1].

    Returns None on any failure so callers can fall back to the lexicon. This is
    off by default; wire it in if you want sharper reads on subtle or sarcastic
    messages the lexicon can miss.
    """
    try:
        if model is None:
            # Reuse the configured reasoning model so this never drifts from
            # whatever the rest of Alpacca is running on.
            from config import OLLAMA_MODEL
            model = OLLAMA_MODEL
        if client is None:
            import ollama
            client = ollama.Client()
        prompt = (
            "Rate the emotional sentiment of this message toward the listener, "
            "as a single number from -1 (hostile) to 1 (warm). Reply with only "
            f"the number.\n\nMessage: {text}"
        )
        resp = client.chat(model=model, messages=[{"role": "user", "content": prompt}])
        m = re.search(r"-?\d*\.?\d+", resp["message"]["content"])
        if not m:
            return None
        return max(-1.0, min(1.0, float(m.group())))
    except Exception:
        return None
