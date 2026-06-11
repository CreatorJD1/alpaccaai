"""Tests for the parts that don't need Ollama or Windows: the emotional model,
persistence, memory (keyword + semantic), sensory derivations, introspection,
sentiment, and self-directed appearance. These are the load-bearing logic of the
companion. Run with: python -m pytest -q  (or just run this file directly).
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpacca.homeostasis import EmotionalState
from alpacca import state as state_store
from alpacca import memory as memory_store
from alpacca.sensory import Observation, prediction_error
from alpacca import introspection
from alpacca import sentiment
from alpacca import appearance
from alpacca import portrait
from alpacca import openclaw_bridge


# --- Homeostasis -----------------------------------------------------------

def test_love_rises_with_reward_and_stays_bounded():
    s = EmotionalState(love=0.4)
    for _ in range(50):
        s = s.update_love(reward=0.9)
    assert 0.4 < s.love <= 1.0
    assert s.love > 0.7

def test_love_drifts_toward_baseline_when_ignored():
    s = EmotionalState(love=0.95)
    for _ in range(200):
        s = s.update_love(reward=0.4)
    assert abs(s.love - 0.4) < 0.05

def test_compassion_spikes_on_late_night_errors():
    s = EmotionalState()
    tired = s.update_compassion({"late_night":1, "long_session":1, "error_context":1})
    rested = s.update_compassion({"late_night":0, "long_session":0, "idle_return":1})
    assert tired.compassion > 0.7
    assert rested.compassion < 0.3

def test_fear_spikes_then_decays():
    s = EmotionalState()
    s = s.update_fear(prediction_error=0.9)
    assert s.fear > 0.5
    for _ in range(30):
        s = s.update_fear(prediction_error=0.0)
    assert s.fear < 0.05

def test_small_surprise_below_threshold_does_not_scare():
    s = EmotionalState(fear=0.0)
    s = s.update_fear(prediction_error=0.2)
    assert s.fear == 0.0

def test_mood_labels():
    assert EmotionalState(fear=0.8).mood_label() == "anxious"
    assert EmotionalState(love=0.8).mood_label() == "affectionate"
    assert EmotionalState(love=0.1).mood_label() == "withdrawn"


# --- Persistence -----------------------------------------------------------

def test_state_round_trips_through_sqlite():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        state_store.init_db(db)
        original = EmotionalState(love=0.71, compassion=0.33, fear=0.12)
        state_store.save_state(original, trigger="test", db_path=db)
        loaded = state_store.load_state(db)
        assert abs(loaded.love - 0.71) < 1e-9
        assert abs(loaded.compassion - 0.33) < 1e-9
        assert abs(loaded.fear - 0.12) < 1e-9
        assert len(state_store.mood_history(db_path=db)) == 1


def test_appearance_seed_persists_across_loads():
    """Her standing taste-seed should survive a restart -- otherwise she'd get
    a fresh personality every time the process starts."""
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "seed.db"
        state_store.init_db(db)
        assert state_store.load_appearance_seed(db) is None
        state_store.save_appearance_seed(4242, db_path=db)
        assert state_store.load_appearance_seed(db) == 4242
        # And the saved seed coexists cleanly with later mood writes.
        state_store.save_state(EmotionalState(love=0.5), trigger="t", db_path=db)
        assert state_store.load_appearance_seed(db) == 4242


# --- Memory (keyword) ------------------------------------------------------

def test_memory_stores_salient_and_retrieves_relevant():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "m.db"
        state_store.init_db(db)
        assert memory_store.remember("My dog Biscuit loves the park",
                                     salience=0.8, db_path=db, embed_fn=None)
        assert memory_store.remember("We talked about quantum computing",
                                     salience=0.8, db_path=db, embed_fn=None)
        assert not memory_store.remember("um ok", salience=0.1, db_path=db, embed_fn=None)
        hits = memory_store.recall("how is the dog doing at the park",
                                   db_path=db, embed_fn=None)
        assert hits and "Biscuit" in hits[0]["content"]


# --- Sensory ---------------------------------------------------------------

def test_error_context_detection():
    assert Observation(window_title="Traceback (most recent call last)").is_error_context() == 1.0
    assert Observation(window_title="vacation photos").is_error_context() == 0.0

def test_prediction_error_on_app_switch_and_error():
    a = Observation(window_title="notes - Obsidian", app="Obsidian")
    b = Observation(window_title="error: build failed - Terminal", app="Terminal")
    assert prediction_error(a, b) > 0.5
    assert prediction_error(None, a) == 0.0


# --- Self-awareness / introspection ----------------------------------------

def _history(samples):
    return [{"love": l, "compassion": c, "fear": f} for (l, c, f) in samples]

def test_introspection_detects_rising_trend():
    state = EmotionalState(love=0.8, compassion=0.2, fear=0.0)
    hist = _history([(0.4,0.2,0.0),(0.5,0.2,0.0),(0.6,0.2,0.0),(0.8,0.2,0.0)])
    rep = introspection.build_self_report(state, hist, memory_count=3)
    assert rep.trends["warmth"] == "rising"
    assert rep.trends["care"] == "steady"

def test_introspection_reason_is_grounded_in_signals():
    state = EmotionalState(love=0.4, compassion=0.85, fear=0.0)
    signals = {"late_night": 1, "long_session": 1, "error_context": 1}
    rep = introspection.build_self_report(state, [], memory_count=0,
                                          last_signals=signals)
    assert "small hours" in rep.reason
    assert "stuck" in rep.reason

def test_self_report_narration_is_grounded_in_real_numbers():
    state = EmotionalState(love=0.62, compassion=0.31, fear=0.05)
    rep = introspection.build_self_report(state, [], memory_count=2,
                                          senses_active=True)
    text = rep.narrate()
    assert "0.62" in text and "0.31" in text
    assert "2 memories" in text

def test_identity_card_is_truthful_about_being_a_program():
    card = introspection.identity_card()
    assert "Alpacca" in card and "program" in card


# --- Sentiment -------------------------------------------------------------

def test_sentiment_basic_polarity():
    assert sentiment.score("I love this, it's wonderful") > 0.4
    assert sentiment.score("this is awful and I hate it") < -0.4
    assert abs(sentiment.score("the meeting is at noon")) < 0.2

def test_sentiment_handles_negation():
    pos = sentiment.score("this is good")
    neg = sentiment.score("this is not good")
    assert pos > 0 and neg < pos

def test_sentiment_intensifiers_amplify():
    assert sentiment.score("really love it") >= sentiment.score("love it") - 1e-9
    assert sentiment.reward("I absolutely love you!") > sentiment.reward("ok")

def test_reward_maps_to_unit_interval():
    assert 0.0 <= sentiment.reward("you are the worst") <= 0.5
    assert 0.5 <= sentiment.reward("you're amazing, thank you") <= 1.0


# --- Embedding-based memory (with an injected fake embedder) ----------------

def _fake_embedder():
    """A tiny deterministic embedder over a few topical axes, so we can test
    semantic recall (related but lexically-different phrases) without Ollama."""
    axes = {
        "pets": {"dog", "puppy", "pup", "biscuit", "park", "walk", "leash", "fetch"},
        "tech": {"quantum", "computing", "code", "python", "bug", "program"},
        "food": {"pizza", "dinner", "cook", "recipe", "hungry", "eat"},
    }
    def embed(text):
        t = set(re.findall(r"[a-z]+", text.lower()))
        return [len(t & words) / len(words) for words in axes.values()]
    return embed

def test_semantic_recall_finds_related_but_different_words():
    fake = _fake_embedder()
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "sem.db"
        state_store.init_db(db)
        memory_store.remember("My dog Biscuit loves the park", salience=0.8,
                              db_path=db, embed_fn=fake)
        memory_store.remember("We discussed quantum computing", salience=0.8,
                              db_path=db, embed_fn=fake)
        # Query shares NO words with the dog memory but is about the same topic.
        hits = memory_store.recall("how is the puppy doing on its walk",
                                   db_path=db, embed_fn=fake)
        assert hits, "semantic recall should surface the topically-related memory"
        assert "Biscuit" in hits[0]["content"]

def test_recall_falls_back_to_keywords_without_embedder():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "kw.db"
        state_store.init_db(db)
        memory_store.remember("My dog Biscuit loves the park", salience=0.8,
                              db_path=db, embed_fn=None)
        hits = memory_store.recall("tell me about the dog and the park",
                                   db_path=db, embed_fn=None)
        assert hits and "Biscuit" in hits[0]["content"]


# --- Self-directed appearance ----------------------------------------------

def test_appearance_is_grounded_in_mood_and_self_described():
    # Affectionate -> she leans rose and reaches for a flower, and says why.
    warm = appearance.choose(EmotionalState(love=0.8, compassion=0.2, fear=0.0), 1)
    assert warm.color.startswith("#")
    assert "flower" in warm.accessories
    assert warm.note and ("I " in warm.note)

def test_appearance_reaches_for_comfort_when_uneasy():
    anxious = appearance.choose(EmotionalState(love=0.4, compassion=0.2, fear=0.7), 1)
    assert "scarf" in anxious.accessories  # she wraps up when on edge

def test_appearance_is_deterministic_for_a_given_self_and_state():
    s = EmotionalState(love=0.5, compassion=0.3, fear=0.1)
    assert appearance.choose(s, 7).as_dict() == appearance.choose(s, 7).as_dict()

def test_appearance_palette_is_stable_within_a_mood_band():
    """Two states with different raw floats but the same mood label should
    pick the same palette -- otherwise her look churns on every mood-vector
    drift, which is exactly the bug the seeding rewrite was meant to fix."""
    a = EmotionalState(love=0.4, compassion=0.2, fear=0.0)   # "content"
    b = EmotionalState(love=0.55, compassion=0.35, fear=0.1)  # also "content"
    assert a.mood_label() == b.mood_label() == "content"
    assert appearance.choose(a, 13).palette == appearance.choose(b, 13).palette


# --- Portrait prompt building ----------------------------------------------

def test_portrait_prompt_mentions_mood_palette_and_accessories():
    state = EmotionalState(love=0.8, compassion=0.2, fear=0.0)  # affectionate
    look = appearance.choose(state, 1)
    prompt = portrait.build_prompt(state, look)
    assert "Alpacca" in prompt
    assert look.palette in prompt              # her chosen color appears
    # Accessories she picked should be reflected somewhere in the prompt.
    for a in look.accessories:
        if a in portrait._ACCESSORY_PHRASE:
            assert portrait._ACCESSORY_PHRASE[a] in prompt

def test_portrait_prompt_steady_within_mood_band():
    # Two states with the same mood label should produce the same prompt --
    # so a tiny mood drift doesn't ask Comfy for a redundant new picture.
    a = EmotionalState(love=0.4, compassion=0.2, fear=0.0)
    b = EmotionalState(love=0.55, compassion=0.3, fear=0.1)
    assert a.mood_label() == b.mood_label() == "content"
    look_a = appearance.choose(a, 13)
    look_b = appearance.choose(b, 13)
    assert portrait.build_prompt(a, look_a) == portrait.build_prompt(b, look_b)


class _Override:
    """Tiny attribute-override helper so the tests work whether the file is
    run under pytest or via its built-in __main__ runner (no fixtures)."""
    def __init__(self, target, **overrides):
        self._t = target
        self._overrides = overrides
        self._saved = {}
    def __enter__(self):
        for k, v in self._overrides.items():
            self._saved[k] = getattr(self._t, k)
            setattr(self._t, k, v)
        return self
    def __exit__(self, *exc):
        for k, v in self._saved.items():
            setattr(self._t, k, v)


# --- Portrait worker degrades gracefully when ComfyClaw is missing ---------

def test_portrait_worker_disabled_short_circuits():
    with _Override(portrait.PortraitCfg, ENABLED=False):
        w = portrait.PortraitWorker()
        look = appearance.choose(EmotionalState(), 1)
        assert w.request(EmotionalState(), look) is False
        assert w.busy is False


# --- OpenClaw bridge: outbound delivery ------------------------------------

def test_openclaw_disabled_does_not_attempt_delivery():
    with _Override(openclaw_bridge.OpenClawCfg, ENABLED=False):
        result = openclaw_bridge.try_deliver("hi", reply_target="telegram:+123")
        assert result["attempted"] is False

def test_openclaw_enabled_but_no_target_reports_missing_target():
    with _Override(openclaw_bridge.OpenClawCfg, ENABLED=True, DEFAULT_TARGET=""):
        result = openclaw_bridge.try_deliver("hi", reply_target="")
        assert result["attempted"] is False
        assert "target" in result["reason"]

def test_openclaw_missing_cli_is_handled():
    with _Override(openclaw_bridge.OpenClawCfg,
                   ENABLED=True,
                   EXEC="definitely-not-a-real-binary-xyz",
                   DEFAULT_TARGET="telegram:+10000000000"):
        result = openclaw_bridge.try_deliver("hello")
        assert result["attempted"] is True
        assert result["ok"] is False
        assert "PATH" in result["reason"] or "not" in result["reason"].lower()


if __name__ == "__main__":
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); passed += 1; print(f"  PASS  {name}")
            except Exception:
                failed += 1; print(f"  FAIL  {name}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
