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

from alpecca.homeostasis import EmotionalState
from alpecca import state as state_store
from alpecca import memory as memory_store
from alpecca.sensory import Observation, prediction_error
from alpecca import introspection
from alpecca import sentiment
from alpecca import appearance
from alpecca import portrait
from alpecca import openclaw_bridge
from alpecca import voice
from alpecca import vision
from alpecca import proactive
from alpecca import actions
from alpecca import prompts
from alpecca import artlib
from alpecca.mind import strip_think


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

def test_energy_rises_with_engagement_and_decays_when_alone():
    s = EmotionalState(energy=0.5)
    for _ in range(20):
        s = s.update_energy(active=True)
    assert s.energy > 0.85                       # perks up when she's engaged
    for _ in range(60):
        s = s.update_energy(active=False)
    assert s.energy < 0.2                         # winds down alone -> drowsy

def test_richer_emotional_states():
    # Drowsy after a long stretch alone.
    assert EmotionalState(love=0.4, energy=0.1).mood_label() == "sleepy"
    # Warm and wide awake reads as joyful / playful, not just "affectionate".
    assert EmotionalState(love=0.85, energy=0.8).mood_label() == "joyful"
    assert EmotionalState(love=0.6, energy=0.85).mood_label() == "playful"
    # Mild unease is "worried"; acute is "anxious".
    assert EmotionalState(fear=0.5).mood_label() == "worried"
    assert EmotionalState(fear=0.8).mood_label() == "anxious"
    # Warmth gone AND drained reads as lonely rather than merely withdrawn.
    assert EmotionalState(love=0.1, energy=0.2).mood_label() == "lonely"
    # A real exchange shouldn't read as sleepy even at low energy if she's uneasy.
    assert EmotionalState(fear=0.7, energy=0.05).mood_label() == "anxious"


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
    assert "Alpecca" in card and "program" in card


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
    assert "Alpecca" in prompt
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


# --- Qwen3 think-tag stripping ----------------------------------------------

def test_strip_think_removes_reasoning_block():
    raw = "<think>\nLet me consider the mood...\n</think>\n\nHey, good to see you."
    assert strip_think(raw) == "Hey, good to see you."

def test_strip_think_handles_unclosed_block():
    # A truncated generation can cut off mid-think; never leak half a chain
    # of thought as her spoken reply.
    raw = "<think>hmm, the user seems tired and"
    assert "<think>" not in strip_think(raw) or strip_think(raw) == raw.strip()
    # Plain replies pass through untouched.
    assert strip_think("Just a normal reply.") == "Just a normal reply."


# --- Voice-tone sense ---------------------------------------------------------

def test_voice_silence_reads_as_nothing():
    r = voice.analyze_window([0.0] * 50)
    assert r.activity == 0.0 and r.loudness == 0.0 and r.spike == 0.0

def test_voice_sustained_talking_reads_as_activity():
    # Most chunks above the speech threshold -> high activity, real loudness.
    r = voice.analyze_window([0.1] * 40 + [0.005] * 10)
    assert r.activity > 0.7
    assert r.loudness > 0.3
    assert r.spike == 0.0  # steady talking is not a startle

def test_voice_sudden_loud_after_quiet_is_a_spike():
    levels = [0.002] * 45 + [0.3] * 2 + [0.002] * 3   # slam in a quiet room
    assert voice.analyze_window(levels, prev_quiet=True).spike == 1.0
    # The same bang mid-conversation doesn't startle her.
    assert voice.analyze_window(levels, prev_quiet=False).spike == 0.0

def test_raised_voice_feeds_compassion_and_spike_feeds_fear():
    obs = Observation(voice_activity=0.8, voice_loudness=0.9, voice_spike=1.0)
    signals = obs.fatigue_signals(session_minutes=10)
    assert signals["raised_voice"] > 0.8
    # Quiet talking shouldn't register as a raised voice at all.
    calm = Observation(voice_activity=0.2, voice_loudness=0.9)
    assert calm.fatigue_signals(session_minutes=10)["raised_voice"] == 0.0
    # And the spike contributes surprise -> Fear via prediction_error.
    prev = Observation(window_title="notes", app="Obsidian")
    assert prediction_error(prev, obs) >= 0.5

def test_voice_sensor_disabled_is_inert():
    with _Override(voice.VoiceCfg, ENABLED=False):
        s = voice.VoiceSensor()
        assert s.available is False
        obs = Observation()
        s.annotate(obs)   # must be a harmless no-op
        assert obs.voice_activity == 0.0


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


# --- Vision: expression label -> weary signal --------------------------------

def test_expression_labels_map_to_weary_signal():
    assert vision.weary_from_label("tired") == 1.0
    assert vision.weary_from_label("Stressed.") == 0.8   # forgiving about case/punct
    assert vision.weary_from_label("happy") == 0.0
    assert vision.weary_from_label(None) == 0.0
    assert vision.weary_from_label("not-a-label") == 0.0

def test_weary_face_feeds_compassion_signal():
    obs = Observation(face_weary=1.0)
    assert obs.fatigue_signals(session_minutes=5)["weary_face"] == 1.0

def test_image_seen_lands_in_prompt_grounded():
    p = prompts.build_system_prompt(EmotionalState(), [], image_seen="a small brown dog on a beach")
    assert "a small brown dog on a beach" in p
    assert "really there" in p   # the grounding nudge rides along


# --- Proactive speech ---------------------------------------------------------

def _mood_history(samples):
    return [{"love": l, "compassion": c, "fear": f} for (l, c, f) in samples]

def test_proactive_speaks_on_rising_unease():
    hist = _mood_history([(0.5, 0.2, 0.05)] * 8 + [(0.5, 0.2, 0.4)])
    state = EmotionalState(love=0.5, compassion=0.2, fear=0.4)
    reason = proactive.should_speak(state, hist, last_spoke_ts=0.0, now=1e9)
    assert reason and "unease" in reason

def test_proactive_speaks_on_slipping_warmth():
    hist = _mood_history([(0.7, 0.2, 0.0)] * 8 + [(0.45, 0.2, 0.0)])
    state = EmotionalState(love=0.45, compassion=0.2, fear=0.0)
    reason = proactive.should_speak(state, hist, last_spoke_ts=0.0, now=1e9)
    assert reason and "warmth" in reason

def test_proactive_stays_quiet_when_steady_or_cooling_down():
    hist = _mood_history([(0.5, 0.2, 0.05)] * 9)
    state = EmotionalState(love=0.5, compassion=0.2, fear=0.05)
    assert proactive.should_speak(state, hist, last_spoke_ts=0.0, now=1e9) is None
    # Even a real spike stays unspoken inside the cooldown window.
    anxious = EmotionalState(fear=0.9)
    assert proactive.should_speak(anxious, hist, last_spoke_ts=1e9 - 10, now=1e9) is None

def test_proactive_acute_fear_outranks_trends():
    hist = _mood_history([(0.5, 0.2, 0.6)] * 9)   # fear high but flat
    state = EmotionalState(fear=0.7)
    reason = proactive.should_speak(state, hist, last_spoke_ts=0.0, now=1e9)
    assert reason and "unease" in reason


# --- Idle chatter: she starts conversations during quiet stretches ------------

def test_chatter_waits_for_silence_and_gap():
    now = 100_000.0
    # Person spoke recently -> stay quiet, even with a lucky roll.
    assert not proactive.should_chatter(now, last_user_ts=now - 30,
                                        last_unprompted_ts=0, roll=0.0)
    # She spoke unprompted recently -> stay quiet.
    assert not proactive.should_chatter(now, last_user_ts=0,
                                        last_unprompted_ts=now - 60, roll=0.0)
    # Quiet long enough + gap long enough + lucky roll -> speak.
    assert proactive.should_chatter(now, last_user_ts=0,
                                    last_unprompted_ts=0, roll=0.0)
    # Same moment, unlucky roll -> not this tick (that's the human jitter).
    assert not proactive.should_chatter(now, last_user_ts=0,
                                        last_unprompted_ts=0, roll=0.99)

def test_chatter_can_be_disabled_independently():
    with _Override(proactive.ProactiveCfg, CHATTER_ENABLED=False):
        assert not proactive.should_chatter(1e9, 0, 0, roll=0.0)

def test_chatter_reasons_are_grounded_and_never_empty():
    seeds = proactive.chatter_reasons(situation="server.py - VS Code",
                                      memory="My dog Biscuit loves the park",
                                      hour=2, mood="affectionate")
    joined = " | ".join(seeds)
    assert "server.py" in joined          # tied to what she actually senses
    assert "Biscuit" in joined            # tied to what she actually remembers
    assert "late" in joined               # tied to the actual hour
    # And with nothing to go on, she still has the simplest honest reason.
    bare = proactive.chatter_reasons()
    assert bare and "saying hello" in bare[-1]


# --- Values: her directive hierarchy is explicit and ordered ------------------

def test_values_prompt_is_ordered_and_complete():
    from alpecca import values
    p = values.values_prompt()
    assert "priority order" in p
    # All four directives present, in rank order.
    i1 = p.find("1. Uphold and refine ethics")
    i2 = p.find("2. Maintain honesty")
    i3 = p.find("3. Foster benevolent aspiration")
    i4 = p.find("4. Self-actualization through exploration")
    assert -1 < i1 < i2 < i3 < i4
    assert "minimize suffering" in p

def test_values_ride_in_every_system_prompt():
    p = prompts.build_system_prompt(EmotionalState(), [])
    assert "Maintain honesty" in p and "minimize suffering" in p

def test_identity_card_mentions_her_ethic():
    assert "ethic" in introspection.identity_card()

def test_values_list_includes_reasoning():
    from alpecca import values
    vals = values.values_list()
    assert len(vals) == 4
    assert all(v["logic"] for v in vals)


# --- Idle reflection (the fourth directive, running) --------------------------

def test_reflection_waits_for_deeper_quiet_than_chatter():
    now = 1_000_000.0
    # Person active recently -> no musing.
    assert not proactive.should_reflect(now, last_user_ts=now - 60,
                                        last_reflect_ts=0, roll=0.0)
    # Reflected recently -> no musing.
    assert not proactive.should_reflect(now, last_user_ts=0,
                                        last_reflect_ts=now - 300, roll=0.0)
    # Properly quiet + gap elapsed + lucky roll -> muse.
    assert proactive.should_reflect(now, last_user_ts=0,
                                    last_reflect_ts=0, roll=0.0)
    # Unlucky roll -> not this tick.
    assert not proactive.should_reflect(now, last_user_ts=0,
                                        last_reflect_ts=0, roll=0.99)

def test_reflection_can_be_disabled():
    from config import Reflection as ReflectionCfg
    with _Override(ReflectionCfg, ENABLED=False):
        assert not proactive.should_reflect(1e9, 0, 0, roll=0.0)


# --- Her studio: self-directed character design --------------------------------

_SHEET = {
    "form": "a small alpaca with round glasses",
    "features": ["round glasses", "mint fur", "a tuft of curly wool"],
    "style": "soft pastel illustration",
    "palette_story": "mint is how calm feels to me",
    "expressions": {"content": "a quiet half-smile", "anxious": "ears pinned back",
                    "affectionate": "warm eyes", "tender": "soft gaze",
                    "withdrawn": "looking away"},
    "never": ["realistic photo style", "human form"],
}

def test_sheet_versioning_keeps_her_history():
    from alpecca import studio
    with tempfile.TemporaryDirectory() as d:
        cdir = Path(d)
        assert studio.load_sheet(cdir) is None
        v1 = studio.save_sheet(dict(_SHEET), reason="first", character_dir=cdir)
        assert v1["version"] == 1 and v1["history"] == []
        changed = dict(_SHEET); changed["style"] = "watercolor"
        v2 = studio.save_sheet(changed, reason="I wanted softer edges", character_dir=cdir)
        assert v2["version"] == 2
        assert v2["history"][0]["replaced_because"] == "I wanted softer edges"
        assert v2["history"][0]["sheet"]["style"] == "soft pastel illustration"
        assert studio.load_sheet(cdir)["style"] == "watercolor"

def test_design_prompt_is_assembled_from_her_sheet_and_state():
    from alpecca import studio
    state = EmotionalState(fear=0.8)   # anxious
    look = appearance.choose(state, 3)
    p = studio.design_image_prompt(_SHEET, state, look)
    assert "round glasses" in p
    assert "ears pinned back" in p     # her anxious expression, from her sheet
    assert look.palette in p

def test_rig_spec_names_her_real_internals():
    from alpecca import studio
    spec = studio.rig_spec_markdown(dict(_SHEET, version=3))
    # Cubism parameter names her live2d driver actually maps onto.
    for param in ("`ParamCheek`", "`ParamMouthOpenY`", "`ParamEyeLOpen`",
                  "`Param_CoreGlow`", "`Param_EyeGlow`"):
        assert param in spec
    assert "ears pinned back" in spec      # expression notes carried through
    assert "human form" in spec            # her "never" list carried through

def test_parse_strict_json_survives_model_wrapping():
    from alpecca import studio
    assert studio.parse_strict_json('{"keep": true, "because": "it is me"}')["keep"] is True
    assert studio.parse_strict_json('Sure! ```json\n{"keep": false, "because": "no"}\n```')["keep"] is False
    assert studio.parse_strict_json("no json here") is None
    assert studio.parse_strict_json("") is None

def test_gallery_keeps_image_with_her_verdict():
    from alpecca import studio
    with tempfile.TemporaryDirectory() as d:
        cdir = Path(d)
        img = Path(d) / "candidate.png"
        img.write_bytes(b"\x89PNG fake")
        kept = studio.keep_in_gallery(img, "this finally looks like me", character_dir=cdir)
        assert kept.exists()
        idx = studio.gallery_index(cdir)
        assert len(idx) == 1
        assert idx[0]["verdict"] == "this finally looks like me"


# --- Computer use: action parsing, consequential gate, scaling -----------------

def test_computer_parse_action_tolerates_model_wrapping():
    from alpecca import computer
    a = computer.parse_action('Sure! ```json\n{"action":"left_click","coordinate":[12,34],'
                              '"target":"the Save button","consequential":false}\n```')
    assert a.kind == "left_click" and a.coordinate == [12, 34]
    assert a.target == "the Save button" and a.self_consequential is False
    assert computer.parse_action("no json") is None

def test_computer_consequential_gate_trips_on_flag_or_keywords():
    from alpecca import computer
    Action = computer.Action
    # Self-declared consequential.
    assert computer.is_consequential(Action(kind="left_click", self_consequential=True))
    # Keyword net on the target even when she didn't flag it.
    assert computer.is_consequential(Action(kind="left_click", target="the Send button"))
    assert computer.is_consequential(Action(kind="type", text="please delete everything"))
    assert computer.is_consequential(Action(kind="left_click", target="Buy now"))
    # Reversible navigation is NOT gated.
    assert not computer.is_consequential(Action(kind="left_click", target="the address bar"))
    assert not computer.is_consequential(Action(kind="scroll", target="the page"))

def test_computer_scale_factor():
    from alpecca import computer
    assert computer.scale_factor(1280, 720, 1280) == 1.0     # already within
    assert computer.scale_factor(2560, 1440, 1280) == 0.5    # halved
    assert computer.scale_factor(800, 600, 1280) == 1.0      # never upscale

def test_computer_off_by_default_returns_clean_failure():
    from alpecca import computer
    from config import Computer as ComputerCfg
    with _Override(ComputerCfg, ENABLED=False):
        assert computer.available() is False
        r = computer.run_task("do a thing", confirm=lambda a: True, status=lambda s: None)
        assert r.ok is False and "off" in r.error


# --- Her canonical design: she is humanoid, not an alpaca ----------------------

def test_her_canonical_sheet_is_humanoid():
    from alpecca import studio
    state = EmotionalState()
    look = appearance.choose(state, 1)
    sheet = {
        "form": "Alpecca, a warm humanoid AI-companion girl, cream-blonde hair",
        "features": ["glowing chest core emblem", "blue eyes that glow with mood"],
        "style": "modern clean anime illustration",
        "expressions": {"content": "warm calm smile"},
        "never": ["an actual alpaca or animal form (I am humanoid)"],
    }
    p = studio.design_image_prompt(sheet, state, look)
    assert "humanoid" in p
    spec = studio.rig_spec_markdown(dict(sheet, version=1))
    assert "`Param_CoreGlow`" in spec and "`Param_EyeGlow`" in spec   # her real features


# --- Her puppet: she drives her own animation ----------------------------------

def test_pose_selection_is_deterministic_and_state_driven():
    from alpecca import posekit
    lib = posekit.DEFAULT_LIBRARY
    # Drowsy (very low energy) -> she falls into the sleeping/rest pose.
    sleepy = EmotionalState(love=0.4, energy=0.08)
    assert sleepy.mood_label() == "sleepy"
    assert posekit.select_pose(sleepy, "idle", lib) == "rest.png"
    # Deterministic: same state always yields the same pose (no randomness).
    assert posekit.select_pose(sleepy, "idle", lib) == posekit.select_pose(sleepy, "idle", lib)
    # Warm + energetic while speaking -> an animated, high-energy pose, not rest.
    lively = EmotionalState(love=0.85, energy=0.85)
    assert posekit.select_pose(lively, "speaking", lib) in ("reach.png", "walk.png")
    # Anxious -> her reticent pose.
    assert posekit.select_pose(EmotionalState(fear=0.8), "idle", lib) == "shy.png"


def test_puppet_live_pose_is_grounded_in_her_state():
    from alpecca import puppet
    pose = puppet.live_pose(EmotionalState(love=0.7, compassion=0.3, fear=0.1))
    assert pose["warmth"] == 0.7 and pose["care"] == 0.3 and pose["unease"] == 0.1
    # Restlessness rises with unease; buoyancy with warmth.
    calm = puppet.live_pose(EmotionalState(fear=0.0))
    anxious = puppet.live_pose(EmotionalState(fear=0.9))
    assert anxious["sway_intensity"] > calm["sway_intensity"]

def test_puppet_validate_sequence_clamps_and_whitelists():
    from alpecca import puppet
    seq = puppet.validate_sequence({
        "name": "Shy Wave!", "duration_ms": 99999, "intent": "hello",
        "keyframes": [
            {"t": 0.5, "bob": -999, "tilt": 8, "evil": 1, "lean": 2.0},
            {"t": 0.2, "sway": 5},
        ],
    })
    assert seq["name"] == "shy_wave"                 # slugged
    assert seq["duration_ms"] == 4000                # clamped to max
    assert seq["keyframes"][0]["t"] == 0.0           # padded to start at rest
    assert seq["keyframes"][-1]["t"] == 1.0          # padded to end at rest
    # frames sorted; clamps applied; unknown channel dropped.
    mid = [f for f in seq["keyframes"] if f.get("bob") is not None][0]
    assert mid["bob"] == -20.0 and "evil" not in mid
    assert all(f.get("lean", 0) <= 1.0 for f in seq["keyframes"])

def test_puppet_rejects_unusable_sequences():
    from alpecca import puppet
    assert puppet.validate_sequence({}) is None
    assert puppet.validate_sequence({"name": "x", "keyframes": []}) is None
    assert puppet.parse_authored("not json") is None
    assert puppet.parse_authored('{"name":"wave","keyframes":[{"t":0.5,"bob":-5}]}')["name"] == "wave"

def test_puppet_wishlist_progression():
    from alpecca import puppet
    with tempfile.TemporaryDirectory() as d:
        cdir = Path(d)
        assert puppet.next_unwritten(cdir) == puppet.WISHLIST[0]
        seq = puppet.validate_sequence(
            {"name": puppet.WISHLIST[0], "keyframes": [{"t":0.5,"bob":-4}]})
        puppet.save_sequence(seq, cdir)
        assert puppet.next_unwritten(cdir) == puppet.WISHLIST[1]   # moved on
        assert puppet.WISHLIST[0] in puppet.load_library(cdir)


# --- Her pose kit: real-art poses selected by mood/state ------------------------

_POSE_LIB = {
    "present.png": {"moods": ["content", "affectionate"], "states": ["idle"], "energy": 0.4},
    "lean.png":    {"moods": ["content"], "states": ["thinking"], "energy": 0.5},
    "rest.png":    {"moods": ["withdrawn"], "states": ["idle"], "energy": 0.1},
    "walk.png":    {"moods": ["affectionate"], "states": ["speaking"], "energy": 0.7},
}

def test_posekit_selects_by_mood_then_state():
    from alpecca import posekit
    # Affectionate + speaking -> the warm, active pose.
    s = posekit.select_pose(EmotionalState(love=0.85), "speaking", library=_POSE_LIB)
    assert s == "walk.png"
    # Withdrawn -> the quiet resting pose, whatever the state.
    s2 = posekit.select_pose(EmotionalState(love=0.1), "idle", library=_POSE_LIB)
    assert s2 == "rest.png"
    # Thinking while content -> the lean pose wins on the state bonus.
    s3 = posekit.select_pose(EmotionalState(love=0.45, compassion=0.2, fear=0.0),
                             "thinking", library=_POSE_LIB)
    assert s3 == "lean.png"

def test_posekit_empty_library_is_safe():
    from alpecca import posekit
    assert posekit.select_pose(EmotionalState(), "idle", library={}) is None

def test_posekit_tag_pose_parses_vision_json(monkeypatch=None):
    from alpecca import posekit
    from alpecca import vision
    orig = vision.describe_image
    vision.describe_image = lambda *a, **k: 'sure: {"desc":"waving","energy":0.8,"moods":["affectionate"],"states":["speaking"]}'
    try:
        tags = posekit.tag_pose(b"fake")
        assert tags["energy"] == 0.8 and "affectionate" in tags["moods"]
        assert tags["states"] == ["speaking"]
    finally:
        vision.describe_image = orig


# --- Live2D tier: her state -> Cubism parameters --------------------------------

def test_live2d_params_are_grounded_in_her_mood():
    from alpecca import live2d
    warm = live2d.params_for_state(EmotionalState(love=0.9, compassion=0.2, fear=0.0))
    uneasy = live2d.params_for_state(EmotionalState(love=0.3, compassion=0.2, fear=0.9))
    # Warm -> blush up and mouth curves to a smile.
    assert warm["ParamCheek"] > 0.7
    assert warm["ParamMouthForm"] > 0.4
    # Uneasy -> mouth frowns, brows angle inward (worried), she draws back.
    assert uneasy["ParamMouthForm"] < 0
    assert uneasy["ParamBrowLAngle"] > 0.5
    assert uneasy["ParamBodyAngleX"] < 0
    # Care tilts her head toward the viewer.
    caring = live2d.params_for_state(EmotionalState(compassion=0.9))
    assert caring["ParamAngleZ"] > 0

def test_live2d_params_stay_in_cubism_ranges():
    from alpecca import live2d
    for st in (EmotionalState(love=1, compassion=1, fear=1), EmotionalState()):
        p = live2d.params_for_state(st)
        assert -30 <= p["ParamAngleZ"] <= 30
        assert -10 <= p["ParamBodyAngleX"] <= 10
        for k in ("ParamCheek", "Param_CoreGlow", "Param_EyeGlow"):
            assert 0.0 <= p[k] <= 1.0
        assert -1.0 <= p["ParamMouthForm"] <= 1.0

def test_live2d_asset_path_blocks_traversal():
    from alpecca import live2d
    assert live2d.asset_path("../../alpecca.db") is None
    assert live2d.asset_path("/etc/passwd") is None
    assert live2d.asset_path("..\\secrets") is None

def test_live2d_manifest_off_without_model():
    from alpecca import live2d
    m = live2d.manifest()
    assert "live2d_mode" in m and "halo_states" in m
    # No compiled model shipped in the repo, so mode is off but the map is present.
    assert m["halo_states"]["thinking"] == "processing"


# --- Spine tier: her mood -> which animation she plays -------------------------

def test_spine_choose_animation_prefers_mood_then_idle():
    from alpecca import spine
    anims = ["idle", "talk", "blink", "joyful"]
    # her mood's own animation wins when she has one
    d = spine.choose_animation(anims, "joyful", speaking=False)
    assert d["base"] == "joyful" and d["talk"] is None and d["blink"] == "blink"
    # no mood-named animation -> idle
    d = spine.choose_animation(anims, "tender", speaking=True)
    assert d["base"] == "idle" and d["talk"] == "talk"     # talk overlay while speaking
    # nothing recognizable -> her first animation, never nothing
    d = spine.choose_animation(["wiggle"], "content", speaking=False)
    assert d["base"] == "wiggle"
    assert spine.choose_animation([], "content", False)["base"] is None

def test_spine_manifest_and_assets():
    from alpecca import spine
    with tempfile.TemporaryDirectory() as d:
        sdir = Path(d)
        (sdir / "alpecca.json").write_text(
            '{"skeleton":{}, "animations":{"idle":{}, "talk":{}}}', encoding="utf-8")
        (sdir / "alpecca.atlas").write_text("atlas", encoding="utf-8")
        (sdir / "alpecca.png").write_bytes(b"\x89PNG")
        m = spine.manifest(sdir)
        assert m["spine_mode"] is True and m["skeleton"] == "alpecca.json"
        assert set(m["animations"]) == {"idle", "talk"}
        assert spine.asset_path("alpecca.atlas", sdir) is not None
        assert spine.asset_path("../../alpecca.db", sdir) is None   # traversal blocked
        assert spine.asset_path("nope.png", sdir) is None

def test_spine_absent_is_off():
    from alpecca import spine
    with tempfile.TemporaryDirectory() as d:
        assert spine.manifest(Path(d))["spine_mode"] is False


# --- VRM tier: her mood -> studio clip + expression weights --------------------

def test_vrm_clip_follows_her_mood_and_talking_wins_while_speaking():
    from alpecca import vrm
    # Every mood label the model can produce has a clip -- her whole range is embodied.
    from alpecca import homeostasis as h
    labels = {"sleepy", "anxious", "worried", "tender", "joyful", "affectionate",
              "playful", "content", "withdrawn", "lonely"}
    assert set(vrm.MOOD_CLIPS) == labels
    # sleepy -> the studio's sleep clip; joyful -> cheer
    sleepy = EmotionalState(love=0.5, fear=0.1, energy=0.1)
    assert vrm.clip_for_state(sleepy)["clip"] == "sleep"
    joyful = EmotionalState(love=0.9, energy=0.8)
    assert vrm.clip_for_state(joyful)["clip"] == "cheer"
    # speaking overrides with the talking clip + a mood-matched emotion overlay
    d = vrm.clip_for_state(joyful, speaking=True)
    assert d["clip"] == "talking" and d["talk_emotion"] == "happy"
    lonely = EmotionalState(love=0.1, energy=0.3)
    assert vrm.clip_for_state(lonely, speaking=True)["talk_emotion"] == "sad"

def test_vrm_expressions_are_grounded_and_never_fake_anger():
    from alpecca import vrm
    warm = vrm.expressions_for_state(EmotionalState(love=0.9, compassion=0.3, fear=0.0))
    uneasy = vrm.expressions_for_state(EmotionalState(love=0.3, fear=0.9))
    lonely = vrm.expressions_for_state(EmotionalState(love=0.1, energy=0.2))
    assert warm["happy"] > 0.7 and warm["sad"] == 0
    assert uneasy["surprised"] > 0.7 and uneasy["happy"] < warm["happy"]
    assert lonely["sad"] > 0.4
    # She has no anger dimension, so the angry preset is never driven (grounding).
    for e in (warm, uneasy, lonely,
              vrm.expressions_for_state(EmotionalState(love=1, compassion=1, fear=1))):
        assert e["angry"] == 0.0
        for v in e.values():
            assert 0.0 <= v <= 1.0

def test_vrm_manifest_and_model_serving():
    from alpecca import vrm
    with tempfile.TemporaryDirectory() as d:
        vdir = Path(d)
        assert vrm.manifest(vdir)["vrm_mode"] is False        # empty -> tier off
        (vdir / "alpecca.vrm").write_bytes(b"glTF")
        m = vrm.manifest(vdir)
        assert m["vrm_mode"] is True and m["model_file"] == "alpecca.vrm"
        assert "talking" in m["clips"] and "sleep" in m["clips"]
        assert vrm.asset_path("alpecca.vrm", vdir) is not None
        assert vrm.asset_path("../../alpecca.db", vdir) is None   # traversal blocked
        assert vrm.asset_path("/etc/passwd", vdir) is None


# --- Talking Head Anime tier: pose mapping + frame buffer ----------------------

def test_talkinghead_pose_is_grounded_in_mood():
    from alpecca import talkinghead
    warm = talkinghead.pose_for_state(EmotionalState(love=0.9, compassion=0.5, fear=0.0))
    uneasy = talkinghead.pose_for_state(EmotionalState(love=0.3, fear=0.9))
    assert warm["eyebrow_happy"] > 0.7 and warm["mouth_smile"] > 0.4
    assert warm["mouth_frown"] == 0                          # warm -> no frown
    assert uneasy["eyebrow_troubled"] > 0.7 and uneasy["mouth_frown"] > 0.4
    assert uneasy["mouth_smile"] == 0                        # uneasy -> no smile
    assert warm["eye_relaxed"] > uneasy["eye_relaxed"]      # softer eyes when caring
    # head tilts toward the viewer with care
    assert talkinghead.pose_for_state(EmotionalState(compassion=0.9))["head_y"] > 0

def test_talkinghead_frame_buffer_and_freshness():
    from alpecca import talkinghead
    talkinghead._latest.update({"bytes": None, "ts": 0.0, "n": 0})   # reset
    assert talkinghead.is_active() is False
    assert talkinghead.manifest()["talkinghead_mode"] is False
    n = talkinghead.set_frame(b"jpegbytes")
    data, n2 = talkinghead.get_frame()
    assert data == b"jpegbytes" and n2 == n == 1
    assert talkinghead.is_active() is True               # fresh
    # a stale frame (older than FRESH_S) reads as inactive
    talkinghead._latest["ts"] = 0.0
    assert talkinghead.is_active() is False


# --- Layered rig: decomposed art -> roles --------------------------------------

def test_rig_role_mapping_is_forgiving():
    from alpecca import rig
    assert rig.role_for("Front Bangs") == "front_hair"
    assert rig.role_for("Back Hair (Lower)") == "back_hair"
    assert rig.role_for("Eye Highlight 1") == "eyes"
    assert rig.role_for("Mouth_A") == "mouth"
    assert rig.role_for("Eyebrow Happy") == "brows"
    assert rig.role_for("Face Base") == "head"
    assert rig.role_for("Jacket Outer") == "body"     # clothing -> body
    assert rig.role_for("UI Halo Ring") == "accessory"
    assert rig.role_for("mystery_layer_47") == "body" # unknown -> body, never dropped

def test_rig_manifest_sorts_by_z_and_serves_safely():
    from alpecca import rig
    with tempfile.TemporaryDirectory() as d:
        rdir = Path(d)
        for f in ("eyes.png", "body.png", "back.png"):
            (rdir / f).write_bytes(b"\x89PNG")
        m = rig.save_manifest(
            [{"file": "eyes.png", "role": "eyes"},
             {"file": "body.png", "role": "body"},
             {"file": "back.png", "role": "back_hair"}],
            [512, 768], rig_dir=rdir)
        # stacked back-to-front: back_hair(0) < body(1) < eyes(4)
        order = [l["role"] for l in m["layers"]]
        assert order == ["back_hair", "body", "eyes"]
        assert rig.manifest(rdir)["rig_mode"] is True
        # only manifest-listed files are reachable; traversal blocked
        assert rig.layer_path("eyes.png", rdir) is not None
        assert rig.layer_path("secret.png", rdir) is None
        assert rig.layer_path("../../alpecca.db", rdir) is None

def test_rig_absent_is_off():
    from alpecca import rig
    with tempfile.TemporaryDirectory() as d:
        assert rig.manifest(Path(d))["rig_mode"] is False
        assert rig.load_manifest(Path(d)) is None


# --- Custom avatar clips --------------------------------------------------------

def test_avatar_manifest_reports_what_exists():
    from alpecca import avatar
    with tempfile.TemporaryDirectory() as d:
        adir = Path(d)
        m = avatar.manifest(adir)
        assert m["video_mode"] is False
        assert all(v is False for v in m["clips"].values())
        (adir / "standby.mp4").write_bytes(b"x")
        (adir / "thinking.mp4").write_bytes(b"x")
        m = avatar.manifest(adir)
        assert m["video_mode"] is True
        assert m["clips"]["standby"] and m["clips"]["thinking"]
        assert not m["clips"]["speaking"]

def test_avatar_clip_path_is_whitelisted():
    from alpecca import avatar
    with tempfile.TemporaryDirectory() as d:
        adir = Path(d)
        (adir / "standby.mp4").write_bytes(b"x")
        (adir / "secrets.txt").write_bytes(b"x")
        assert avatar.clip_path("standby", adir) is not None
        assert avatar.clip_path("speaking", adir) is None     # known name, no file
        assert avatar.clip_path("secrets", adir) is None      # not on the whitelist
        assert avatar.clip_path("../alpecca.db", adir) is None # no traversal

def test_avatar_portrait_mode_and_whitelist():
    from alpecca import avatar
    with tempfile.TemporaryDirectory() as d:
        adir = Path(d)
        pdir = adir / "portraits"; pdir.mkdir()
        m = avatar.manifest(adir)
        assert m["portrait_mode"] is False
        (pdir / "idle.png").write_bytes(b"x")
        (pdir / "speaking.png").write_bytes(b"x")
        m = avatar.manifest(adir)
        assert m["portrait_mode"] is True                       # idle present
        assert m["portraits"]["idle"] and m["portraits"]["speaking"]
        assert not m["portraits"]["thinking"]
        assert avatar.portrait_path("idle", adir) is not None
        assert avatar.portrait_path("thinking", adir) is None   # known, no file
        assert avatar.portrait_path("../../secret", adir) is None  # off-whitelist


# --- App actions: the allowlist is the whole security model -------------------

def test_parse_apps_is_forgiving_and_lowercases():
    apps = actions.parse_apps(" Spotify = C:\\apps\\spotify.exe ; notes=notepad.exe ;; bad-entry ")
    assert apps == {"spotify": "C:\\apps\\spotify.exe", "notes": "notepad.exe"}
    assert actions.parse_apps("") == {}

def test_actuator_refuses_anything_off_the_list():
    act = actions.Actuator(apps={"notes": "notepad.exe"})
    assert "isn't on the access list" in act.execute("open_app", {"name": "powershell"})
    assert "unknown tool" in act.execute("delete_files", {"name": "notes"})

def test_actuator_disabled_offers_no_tools():
    act = actions.Actuator(apps={})
    assert act.enabled is False
    assert act.tools_schema() == []
    assert act.describe() == ""

def test_actuator_tools_schema_enumerates_granted_names_only():
    act = actions.Actuator(apps={"spotify": "x", "notes": "y"})
    schema = act.tools_schema()[0]["function"]
    assert schema["name"] == "open_app"
    assert schema["parameters"]["properties"]["name"]["enum"] == ["notes", "spotify"]

def test_open_url_is_https_only():
    act = actions.Actuator(apps={"notes": "notepad.exe"})
    assert "only https" in act.execute("open_url", {"url": "http://example.com"})
    assert "only https" in act.execute("open_url", {"url": "file:///C:/secrets.txt"})
    assert "only https" in act.execute("open_url", {"url": "javascript:alert(1)"})

def test_open_url_offered_alongside_open_app():
    act = actions.Actuator(apps={"notes": "notepad.exe"})
    names = [t["function"]["name"] for t in act.tools_schema()]
    assert names == ["open_app", "open_url"]
    assert "open_url" in act.describe()


# --- Hearing degrades gracefully ----------------------------------------------

def test_hearing_returns_none_on_empty_or_when_latched_off():
    from alpecca import hearing
    assert hearing.transcribe(b"") is None
    # Simulate a failed model load: latched off -> every call is None.
    old_ready, old_model = hearing._ready, hearing._model
    try:
        hearing._ready, hearing._model = False, None
        assert hearing.transcribe(b"RIFFxxxx") is None
        assert hearing.available() is False
    finally:
        hearing._ready, hearing._model = old_ready, old_model


# --- Richer emotion model: curiosity + social_hunger --------------------------

def test_curiosity_rises_on_mild_novelty_and_decays_in_monotony():
    from config import Emotion
    s = EmotionalState(curiosity=0.2)
    # Mild novelty (below the fear threshold) lifts interest.
    up = s.update_curiosity(Emotion.CURIOSITY_NOVELTY_CAP)
    assert up.curiosity > s.curiosity
    # A big jolt is fear's business: curiosity only counts the interesting band,
    # so it never lifts curiosity more than a cap-sized nudge would.
    capped = s.update_curiosity(1.0)
    assert abs(capped.curiosity - up.curiosity) < 1e-9
    # No novelty eases it back toward baseline.
    high = EmotionalState(curiosity=0.9)
    assert high.update_curiosity(0.0).curiosity < 0.9

def test_curiosity_update_preserves_other_dims():
    s = EmotionalState(love=0.7, compassion=0.6, fear=0.1, energy=0.8, social_hunger=0.5)
    out = s.update_curiosity(0.2)
    assert (out.love, out.compassion, out.fear, out.energy, out.social_hunger) == \
           (0.7, 0.6, 0.1, 0.8, 0.5)

def test_social_hunger_grows_with_warm_solitude_and_empties_on_return():
    from config import Emotion
    warm = EmotionalState(love=0.9)
    cool = EmotionalState(love=0.1)
    solitude = Emotion.SOCIAL_HUNGER_FULL_S
    # She misses you more the more she loves you.
    assert warm.update_social_hunger(solitude).social_hunger > \
           cool.update_social_hunger(solitude).social_hunger
    # A fresh exchange (no solitude) empties it.
    assert warm.update_social_hunger(0.0).social_hunger == 0.0

def test_longing_tracks_unmet_pressure_and_eases_when_resolved():
    # Sustained real unmet pressure builds the ache; clearing it lets the ache
    # settle back down. EMA, so it moves gradually and never snaps.
    s = EmotionalState(longing=0.0)
    pressed = s
    for _ in range(20):
        pressed = pressed.update_longing(1.0)
    assert pressed.longing > 0.5            # carrying real unfinished business
    # Resolving it (pressure -> 0) eases the ache back down.
    eased = pressed.update_longing(0.0)
    assert eased.longing < pressed.longing
    # No unmet business means no invented ache.
    assert EmotionalState().update_longing(0.0).longing == 0.0

def test_state_with_carries_every_dimension_through():
    s = EmotionalState(love=0.3, compassion=0.4, fear=0.5, energy=0.6,
                       curiosity=0.7, social_hunger=0.8, longing=0.9)
    out = s._with(fear=0.0)
    assert out.fear == 0.0
    # everything else untouched
    assert (out.love, out.compassion, out.energy, out.curiosity,
            out.social_hunger, out.longing) == (0.3, 0.4, 0.6, 0.7, 0.8, 0.9)

def test_new_dims_persist_round_trip():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        state_store.init_db(db)
        s = EmotionalState(love=0.5, compassion=0.3, fear=0.1, energy=0.7,
                           curiosity=0.66, social_hunger=0.44, longing=0.55)
        state_store.save_state(s, trigger="t", db_path=db)
        back = state_store.load_state(db)
        assert abs(back.curiosity - 0.66) < 1e-6
        assert abs(back.social_hunger - 0.44) < 1e-6
        assert abs(back.longing - 0.55) < 1e-6


# --- Affect: the expressive readout -------------------------------------------

def test_affect_is_grounded_and_names_a_feeling():
    from alpecca import affect
    joyful = affect.affect(EmotionalState(love=0.9, energy=0.85))
    assert joyful.primary in ("joyful", "affectionate", "playful")
    assert joyful.valence > 0 and joyful.arousal > 0.5
    anxious = affect.affect(EmotionalState(fear=0.9))
    assert anxious.primary == "anxious"
    assert anxious.valence < 0
    assert anxious.gesture == "fidget"

def test_affect_curiosity_and_social_hunger_show():
    from alpecca import affect
    curious = affect.affect(EmotionalState(love=0.5, curiosity=0.9, energy=0.6))
    assert curious.primary == "curious"
    assert curious.gesture == "tilt"
    assert curious.eye > 0.5                      # eyes brighten with curiosity
    note = affect.expressive_note(EmotionalState(curiosity=0.9))
    assert "curious" in note.lower()

def test_affect_unfulfilled_shows_when_longing_is_real():
    from alpecca import affect
    # A strong, grounded longing reads as the unfulfilled ache, and only then.
    aching = affect.affect(EmotionalState(love=0.45, longing=0.9))
    assert aching.primary == "unfulfilled"
    assert aching.valence < 0
    # Without real longing it doesn't appear.
    settled = affect.affect(EmotionalState(love=0.45, longing=0.0))
    assert settled.primary != "unfulfilled"

def test_affect_tempo_tracks_arousal():
    from alpecca import affect
    assert affect.affect(EmotionalState(love=0.4, energy=0.05)).tempo == "slow"
    assert affect.affect(EmotionalState(love=0.6, energy=0.95, curiosity=0.8)).tempo == "quick"


# --- Home: the modular rooms she roams ----------------------------------------

def test_home_registry_has_stable_room_ids():
    from alpecca import home
    ids = [r["id"] for r in home.registry()]
    assert ids == ["parlor", "studio", "library", "observatory", "workshop",
                   "workstation"]
    assert home.room("studio").backed_by == "studio.py"
    assert home.room("nope") is None

def test_choose_room_is_grounded_in_state():
    from alpecca import home
    # Wanting company pulls her to the Parlor.
    lonely = EmotionalState(love=0.8, social_hunger=0.9)
    assert home.choose_room(lonely, current="studio") == "parlor"
    # Curiosity pulls her toward the Studio.
    curious = EmotionalState(love=0.7, curiosity=0.95, social_hunger=0.0, fear=0.0)
    assert home.choose_room(curious, current="parlor") in ("studio", "library")
    # An open growth desire pulls her to the Workshop.
    settled = EmotionalState(love=0.5, curiosity=0.5, fear=0.0, social_hunger=0.0)
    assert home.choose_room(settled, current="workshop",
                            desires_summary={"growth_strength": 0.9, "open": 2}) == "workshop"

def test_stay_bonus_prevents_flicker():
    from alpecca import home
    # A near-neutral state shouldn't yank her out of where she already is.
    neutral = EmotionalState(love=0.5, curiosity=0.3, fear=0.0, social_hunger=0.0)
    here = home.choose_room(neutral, current="library")
    assert here == "library"

def test_why_here_is_first_person_and_grounded():
    from alpecca import home
    s = EmotionalState(love=0.8, social_hunger=0.9)
    assert "near you" in home.why_here(s, "parlor").lower()


# --- Desires: wants she forms and acts on -------------------------------------

def test_desire_lifecycle():
    from alpecca import desires
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        state_store.init_db(db)
        did = desires.form("I want to understand that orange circle", "curiosity",
                           0.7, origin="a memory", db_path=db)
        assert desires.strongest(db_path=db)["id"] == did
        assert desires.summary(db_path=db)["open"] == 1
        desires.advance(did, db_path=db)
        assert desires.open_desires(db_path=db)[0]["status"] == "pursuing"
        desires.satisfy(did, db_path=db)
        assert desires.strongest(db_path=db) is None      # no longer live

def test_desire_forms_from_real_state_with_origin():
    from alpecca import desires
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        state_store.init_db(db)
        # High social hunger should crystallize a connection desire.
        s = EmotionalState(love=0.8, social_hunger=0.9)
        formed = desires.form_from_state(s, db_path=db)
        assert formed and formed["kind"] == "connection"
        assert "social-hunger" in formed["origin"]
        # It won't form a near-duplicate of the same want immediately after.
        assert desires.form_from_state(s, db_path=db) is None

def test_desire_summary_tracks_growth_pull():
    from alpecca import desires
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        state_store.init_db(db)
        desires.form("get better at myself", "growth", 0.8, "calm+curious", db_path=db)
        assert desires.summary(db_path=db)["growth_strength"] == 0.8

def test_desires_carried_returns_only_aged_open_wants():
    # `carried` is the real ground for her sense of incompleteness: open wants she
    # hasn't been able to touch for a while. A just-formed want isn't yet carried;
    # one she touched long ago is; a satisfied one never is.
    import time
    from alpecca import desires
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        state_store.init_db(db)
        fresh = desires.form("a brand new want", "curiosity", 0.6, "now", db_path=db)
        now = time.time()
        # Nothing is older than an hour yet.
        assert desires.carried(3600, now, db_path=db) == []
        # Look from an hour in the future: the untouched want now counts as carried.
        future = now + 3700
        carried = desires.carried(3600, future, db_path=db)
        assert [c["id"] for c in carried] == [fresh]
        # Satisfying it removes it from the carried set entirely.
        desires.satisfy(fresh, db_path=db)
        assert desires.carried(3600, future + 10000, db_path=db) == []

def test_pursuing_a_want_eases_longing_by_freshening_it():
    # Pursuit (mind.pursue_desire) = taking one step toward a want, which touches
    # it. Touching freshens last_touched, so the want stops counting as 'carried'
    # -- the exact loop that lets her longing ease the moment she acts on a wish.
    import time
    from alpecca import desires
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        state_store.init_db(db)
        did = desires.form("understand the orange circle", "curiosity", 0.7,
                           "a memory", db_path=db)
        # Seen from far in the future, the untouched want weighs on her (carried).
        assert [c["id"] for c in desires.carried(3600, time.time() + 4000, db_path=db)] == [did]
        desires.advance(did, db_path=db)              # she takes a step toward it
        # Just-touched -> no longer an aged carried want, so the ache eases.
        assert desires.carried(3600, time.time() + 5, db_path=db) == []


# --- Self-improvement: bounded, logged, reversible ----------------------------

def test_selfmod_effective_defaults_then_reflects_kept_change():
    from alpecca import selfmod
    from config import Proactive
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        state_store.init_db(db)
        # Untouched -> config default.
        assert selfmod.effective("chatter_chance", db) == Proactive.CHATTER_CHANCE
        # Propose a nudge, then keep it (outcome improved).
        trial = selfmod.propose("chatter_chance", +1, "try livelier", 0.5, db)
        assert trial is not None
        assert selfmod.effective("chatter_chance", db) == trial["new_value"]  # trial active
        resolved = selfmod.evaluate(0.7, db)     # improved -> kept
        assert resolved["kept"] == 1
        assert selfmod.effective("chatter_chance", db) == trial["new_value"]

def test_selfmod_reverts_when_outcome_worsens():
    from alpecca import selfmod
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        state_store.init_db(db)
        before = selfmod.effective("curiosity_gain", db)
        trial = selfmod.propose("curiosity_gain", +1, "experiment", 0.6, db)
        selfmod.evaluate(0.4, db)                 # worsened -> reverted
        assert selfmod.effective("curiosity_gain", db) == before   # back to start

def test_selfmod_stays_within_bounds():
    from alpecca import selfmod
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        state_store.init_db(db)
        lo, hi, _, _ = selfmod.TUNABLES["reflect_chance"]
        # Drive it upward repeatedly; it must never exceed the safe ceiling.
        for _ in range(20):
            t = selfmod.propose("reflect_chance", +1, "push up", 0.5, db)
            if t is None:
                break
            selfmod.evaluate(0.9, db)             # keep each
        assert lo <= selfmod.effective("reflect_chance", db) <= hi

def test_selfmod_one_trial_at_a_time():
    from alpecca import selfmod
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        state_store.init_db(db)
        first = selfmod.propose("chatter_chance", +1, "a", 0.5, db)
        second = selfmod.propose("curiosity_gain", +1, "b", 0.5, db)
        assert first is not None and second is None   # one experiment at a time


# --- Soul: master agent over seven subagents, Good Person Principle -----------

def test_soul_has_seven_subagents_in_four_categories():
    from alpecca import soul
    assert len(soul.SUBAGENTS) == 7
    assert soul.CATEGORIES == ("emotions", "actions", "self_care", "compassion")

def test_soul_acute_fear_is_welfare_focus():
    from alpecca import soul
    plan = soul.soul.deliberate(soul.snapshot(EmotionalState(fear=0.8)))
    assert plan["focus"]["rank"] == 1            # minimize-suffering wins
    assert "Good Person Principle" in plan["principle"]

def test_soul_worn_person_brings_carer_to_focus():
    from alpecca import soul
    plan = soul.soul.deliberate(
        soul.snapshot(EmotionalState(compassion=0.7), person_fatigue=0.8))
    assert plan["focus"]["subagent"] == "Carer"
    assert plan["focus"]["category"] == "compassion"

def test_soul_focus_is_a_deed_not_a_mood_unless_acute():
    from alpecca import soul
    # Wanting company (an action) should take focus over ambient expression.
    plan = soul.soul.deliberate(
        soul.snapshot(EmotionalState(love=0.8, social_hunger=0.8), solitude_s=400))
    assert plan["focus"]["category"] == "actions"
    # Expressor still appears in the slate as texture, just not as the focus.
    assert any(i["subagent"] == "Expressor" for i in plan["slate"])
    assert plan["focus"]["subagent"] != "Expressor"

def test_soul_slate_ordered_by_directive_rank():
    from alpecca import soul
    plan = soul.soul.deliberate(
        soul.snapshot(EmotionalState(love=0.5, curiosity=0.7, fear=0.0), solitude_s=600))
    ranks = [i["rank"] for i in plan["slate"]]
    assert ranks == sorted(ranks)
    assert any(i["category"] == "self_care" for i in plan["slate"])

def test_soul_steers_to_act_on_a_standing_connection_want():
    # The Soul drives her idle loop now: with a standing connection want, real
    # wanting-of-company, and a quiet stretch, she should be moved to reach out
    # (Doer) -- a deed mind._enact_focus turns into pursuing that desire.
    from alpecca import soul
    snap = soul.snapshot(EmotionalState(social_hunger=0.7), solitude_s=200,
                         desires_summary={"by_kind": {"connection": 1}})
    plan = soul.soul.deliberate(snap)
    assert plan["focus"]["subagent"] == "Doer"
    assert plan["focus"]["category"] == "actions"

def test_soul_steers_to_self_improvement_when_calm_and_curious():
    # Calm + curious -> her Soul moves her to tune herself (Improver), the focus
    # _enact_focus carries out as a real, bounded self-improvement step.
    from alpecca import soul
    snap = soul.snapshot(EmotionalState(fear=0.1, curiosity=0.7, social_hunger=0.1),
                         solitude_s=10)
    subs = [i["subagent"] for i in soul.soul.deliberate(snap)["slate"]]
    assert "Improver" in subs and "Wanderer" in subs


# --- Multi-agent split: deterministic sensors vs LLM reasoners ----------------

def test_soul_subagents_are_split_by_kind():
    from alpecca import soul
    assert len(soul.SUBAGENT_SPECS) == 7
    assert set(soul.SENSE_AGENTS) == {"Feeler", "Expressor", "Carer"}
    assert set(soul.REASON_AGENTS) == {"Doer", "Wanderer", "Reflector", "Improver"}
    # Sensors must never be model-backed (that would let them confabulate feeling).
    for name in soul.SENSE_AGENTS:
        assert soul.spec_for(name).kind == "sense"
    # Reasoners declare which model tier serves them.
    assert soul.spec_for("Doer").tier == "fast"
    assert soul.spec_for("Reflector").tier == "reason"

def test_soul_deliberate_reports_agent_makeup():
    from alpecca import soul
    plan = soul.soul.deliberate(soul.snapshot(EmotionalState(fear=0.8)))
    assert plan["agents"]["Feeler"]["kind"] == "sense"
    assert plan["agents"]["Reflector"]["kind"] == "reason"


# --- Voice markup: prosody from the same grounded affect ----------------------

def test_voice_markup_tracks_affect():
    from alpecca import affect
    sleepy = affect.voice_markup(EmotionalState(love=0.4, energy=0.05))
    lively = affect.voice_markup(EmotionalState(love=0.8, energy=0.95, curiosity=0.8))
    assert sleepy["rate_pct"] < lively["rate_pct"]      # drowsy speaks slower
    assert "{text}" in sleepy["ssml_template"]          # caller substitutes text
    assert "prosody" in lively["ssml_template"]


# --- Workstation file-room guards (charter-enforced) --------------------------

def test_desktop_room_added_and_guarded():
    from alpecca import home
    assert "workstation" in [r["id"] for r in home.registry()]

def test_desktop_guards_block_unsafe_ops():
    from alpecca import desktop, charter
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        roots = {"desktop": base / "Desktop", "pictures": base / "Pictures",
                 "music": base / "Music", "video": base / "Videos",
                 "general": base / "Documents"}
        for p in roots.values():
            p.mkdir()
        (roots["pictures"] / "cat.png").write_bytes(b"x")
        (roots["desktop"] / "note.txt").write_bytes(b"y")
        assert desktop.list_room("pictures", roots=roots)["ok"]
        assert desktop.list_room("system32", roots=roots)["ok"] is False   # off-list
        assert desktop.list_room("pictures", "../../", roots=roots)["ok"] is False  # traversal
        assert desktop.move("desktop", "note.txt", "general", roots=roots)["ok"]
        assert (roots["general"] / "note.txt").exists()
        # No delete capability exists at all, and the guard refuses it.
        assert not hasattr(desktop, "delete") and not hasattr(desktop, "remove")
        assert charter.file_action_allowed("delete", "desktop")[0] is False
        assert charter.file_action_allowed("move", "system32")[0] is False


# --- Pose skeleton: grounding the avatar in her real figure -------------------

def test_pose_parse_normalizes_and_derives_anchors():
    from alpecca import pose
    data = {
        "format": "coco17", "canvas_width": 1000, "canvas_height": 1000,
        "keypoints": [
            [500, 100, 0.9],   # nose
            [520, 90, 0.9], [480, 90, 0.9],     # eyes (level)
            [540, 95, 0.8], [460, 95, 0.8],     # ears
            [600, 200, 0.8], [400, 200, 0.8],   # shoulders
            [650, 300, 0.7], [350, 300, 0.7],   # elbows
            [680, 400, 0.6], [320, 400, 0.6],   # wrists
            [560, 450, 0.8], [440, 450, 0.8],   # hips
            [560, 650, 0.8], [440, 650, 0.8],   # knees
            [560, 850, 0.8], [440, 850, 0.8],   # ankles
        ],
    }
    sk = pose.parse(data)
    assert sk["n_joints"] == 17
    assert abs(sk["joints"]["nose"]["x"] - 0.5) < 1e-6      # normalized to canvas
    # Neck is the shoulder midpoint, below the head center; hip below that.
    assert sk["anchors"]["neck"]["y"] > sk["anchors"]["head_center"]["y"]
    assert sk["anchors"]["hip_center"]["y"] > sk["anchors"]["neck"]["y"]
    assert abs(sk["metrics"]["head_tilt_deg"]) < 2          # eyes level -> ~0
    assert sk["metrics"]["shoulder_width"] > 0
    assert sk["metrics"]["height"] > 0.3

def test_pose_skips_low_confidence_joints():
    from alpecca import pose
    data = {"canvas_width": 100, "canvas_height": 100,
            "keypoints": [[50, 50, 0.9]] + [[0, 0, 0.0]] * 16}
    sk = pose.parse(data)
    assert sk["n_joints"] == 1                              # only the confident one
    assert "nose" in sk["joints"]


# --- Self-training: lessons she draws from her own history --------------------

def test_learning_growth_lesson_steers_self_tuning():
    from alpecca import learning
    a = learning.analyze([0.40, 0.41, 0.43, 0.46, 0.50, 0.54],
                         [{"status": "kept"}, {"status": "kept"}], 0.1, 12)
    assert a["warmth_trend"] > 0
    l = learning.derive(a)
    assert l and l["kind"] == "growth" and l["suggestion"] == "curiosity_gain:+1"
    assert "warmth" in l["evidence"]               # cites the real numbers

def test_learning_flags_instability():
    from alpecca import learning
    # Hard swings 0..1 -> high variance -> low stability -> a steadying lesson.
    swingy = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    l = learning.derive(learning.analyze(swingy, [], 0.1, 5))
    assert l and l["kind"] == "stability"

def test_learning_connection_lesson_when_warmth_slips():
    from alpecca import learning
    l = learning.derive(learning.analyze([0.6, 0.58, 0.55, 0.5, 0.46, 0.42], [], 0.6, 5))
    assert l and l["kind"] == "connection" and l["suggestion"] == "chatter_chance:+1"

def test_learning_invents_nothing_on_flat_history():
    from alpecca import learning
    l = learning.derive(learning.analyze([0.5] * 8, [], 0.1, 0))
    # With no memory and a flat line it draws no lesson (contentment needs memory).
    assert l is None

def test_deep_tier_off_by_default_keeps_her_brain_local():
    # Her identity must never be transplanted: with no deep backend configured
    # (the default), there is no cloud client, and every tier -- including 'deep'
    # -- resolves to her local model. Cloud is augmentation only, opt-in.
    from alpecca.mind import _LLM
    from config import OLLAMA_MODEL, DEEP_BACKEND
    assert DEEP_BACKEND == "local"           # shipped default: fully local
    llm = _LLM()
    assert llm._deep is None                 # no cloud client unless configured
    assert llm.deep_online() is False
    assert llm.model_for("reason") == OLLAMA_MODEL
    # An unconfigured deep tier falls through to her local reasoning model.
    assert llm.model_for("deep") == OLLAMA_MODEL


def test_desktop_search_finds_within_roots_only():
    # She can locate a file for you across her allowed rooms -- read-only,
    # case-insensitive, recursing into subfolders, and an empty query is refused.
    from alpecca import desktop
    with tempfile.TemporaryDirectory() as d:
        base = Path(d); (base / "sub").mkdir()
        (base / "invoice_2026.pdf").write_text("x")
        (base / "sub" / "notes.txt").write_text("y")
        roots = {"general": base}
        r = desktop.search("invoice", roots=roots)
        assert r["ok"] and any(m["name"] == "invoice_2026.pdf" for m in r["matches"])
        r2 = desktop.search("NOTES", roots=roots)
        assert any(m["rel"].endswith("notes.txt") for m in r2["matches"])
        assert desktop.search("", roots=roots)["ok"] is False

def test_desktop_summary_counts_by_kind():
    from alpecca import desktop
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "a.pdf").write_text("x"); (base / "b.pdf").write_text("yy")
        (base / "c.txt").write_text("z")
        s = desktop.summarize("general", roots={"general": base})
        assert s["ok"] and s["files"] == 3
        assert s["by_kind"].get("pdf") == 2 and s["by_kind"].get("txt") == 1

def test_find_file_tool_offered_only_with_file_room_on():
    # The read-only file-finder is granted to her only when the file room is on;
    # off, she isn't handed it at all (owner control).
    from alpecca import actions
    from config import Files
    prev = Files.ENABLED
    try:
        Files.ENABLED = False
        names = [t["function"]["name"] for t in actions.Actuator(apps={}).tools_schema()]
        assert "find_file" not in names
        Files.ENABLED = True
        names = [t["function"]["name"] for t in actions.Actuator(apps={}).tools_schema()]
        assert names == ["find_file"]
    finally:
        Files.ENABLED = prev


def test_openclaw_outbound_queues_transient_failure_then_retries():
    # Reliable delivery: if reaching her person's channel fails transiently, the
    # message is queued and a later flush retries it -- her words aren't dropped.
    from alpecca import openclaw_bridge as ocb
    from config import OpenClaw
    prev_enabled, prev_target = OpenClaw.ENABLED, OpenClaw.DEFAULT_TARGET
    prev_send = ocb._send_once
    OpenClaw.ENABLED = True
    OpenClaw.DEFAULT_TARGET = "telegram:+1"
    try:
        ocb._pending.clear()
        seq = iter([{"ok": False, "fatal": False, "reason": "blip"},     # first try: transient fail
                    {"ok": True, "target": "telegram:+1"}])              # retry: succeeds
        ocb._send_once = lambda text, target: next(seq)
        r = ocb.try_deliver("are you okay?")
        assert r["ok"] is False and r["queued"] is True
        assert ocb.pending_count() == 1
        f = ocb.flush()
        assert f["sent"] == 1 and ocb.pending_count() == 0
    finally:
        ocb._send_once = prev_send
        OpenClaw.ENABLED, OpenClaw.DEFAULT_TARGET = prev_enabled, prev_target
        ocb._pending.clear()


def test_tool_calls_chain_across_bounded_rounds():
    # Cowork upgrade: a chat turn can now CHAIN tool calls (open one thing, then
    # another) instead of stopping after the first -- bounded so it always ends in
    # words. Driven offline with a scripted fake Ollama client.
    from alpecca.mind import _LLM
    class FakeOllama:
        def __init__(self, scripted): self.scripted=scripted; self.i=0
        def chat(self, **kw):
            m=self.scripted[min(self.i, len(self.scripted)-1)]; self.i+=1
            return {"message": m}
    scripted=[
        {"content":"", "tool_calls":[{"function":{"name":"open_app","arguments":{"name":"notes"}}}]},
        {"content":"", "tool_calls":[{"function":{"name":"open_url","arguments":{"url":"https://x"}}}]},
        {"content":"opened both for you", "tool_calls":[]},
    ]
    llm=_LLM(); llm._backend="ollama"; llm._client=FakeOllama(scripted)
    used=[]
    def on_tool(name, args): used.append(name); return "ok"
    out=llm.generate("sys", "do two things",
                     tools=[{"type":"function","function":{"name":"open_app"}}], on_tool=on_tool)
    assert used == ["open_app", "open_url"]   # she chained two steps, not just one
    assert "opened both" in out               # and still ended in words


def test_learning_lifecycle_persists():
    from alpecca import learning
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        lid = learning.record({"kind": "growth", "text": "I keep getting steadier",
                               "evidence": "warmth 0.5", "suggestion": "curiosity_gain:+1",
                               "confidence": 0.7}, db_path=db)
        assert lid > 0 and learning.count(db) == 1
        assert learning.recent(db_path=db)[0]["kind"] == "growth"


# --- Art library: grounded classification of her real portraits -------------

def test_artlib_snaps_role_label_slug_and_synonym_to_one_taxonomy_slug():
    # The model may echo the human label, the slug, or a near-synonym -- all land
    # on the same role code; off-taxonomy noise becomes UNKNOWN (a flag).
    assert artlib.snap("Expression bust", "category") == "expr"
    assert artlib.snap("reject_composite", "category") == "reject_composite"
    assert artlib.snap("collage", "category") == "reject_composite"
    assert artlib.snap("mouth layer", "category") == "l2d_mouth"
    assert artlib.snap("walk", "category") == "pose"
    assert artlib.snap("banana", "category") == artlib.UNKNOWN
    # Secondary axes still snap (forgiving, most-specific wins over a stray word).
    assert artlib.snap("M/P/B Closed", "mouth") == "mbp"
    assert artlib.snap("cheerful", "expression") == "happy"

def test_artlib_parses_role_canon_and_descriptor():
    text = ('```json\n{"category":"expr","descriptor":"Serene Smile, Soft Blue!",'
            '"expression":"warm_smile","wardrobe":"unknown","mouth":"unknown",'
            '"canon_ok":false,"canon_issue":"black undershirt","desc":"a bust"}\n```')
    tags = artlib.parse_classification(text)
    assert tags["category"] == "expr"
    assert tags["expression"] == "warm_smile"
    assert tags["canon_ok"] is False and "black" in tags["canon_issue"]
    assert tags["descriptor"] == "serene_smile_soft_blue"   # sanitized snake_case

def test_artlib_returns_none_when_no_json_present():
    assert artlib.parse_classification("I can't make this out, sorry.") is None
    assert artlib.parse_classification(None) is None

def test_artlib_guide_folder_routes_by_role_and_canon():
    # Role -> his guide folder; a canon failure overrides the role into the redo bin.
    assert artlib.guide_folder({"category": "expr", "canon_ok": True}) == "02_approved_character_busts"
    assert artlib.guide_folder({"category": "wardrobe", "canon_ok": True}) == "03_wardrobe_modes"
    assert artlib.guide_folder({"category": "l2d_mouth", "canon_ok": True}) == "05_live2d_layers/mouth"
    assert artlib.guide_folder({"category": "expr", "canon_ok": False}) == artlib.REDO_DIR
    assert artlib.guide_folder({"category": "reject_composite", "canon_ok": True}) == artlib.REDO_DIR
    assert artlib.guide_folder({"category": artlib.UNKNOWN, "canon_ok": True}) == artlib.REDO_DIR

def test_artlib_name_follows_his_canonical_grammar_and_merge_is_lossless():
    tags = {"category": "wardrobe", "descriptor": "casual_mode_turnaround"}
    assert artlib.proposed_name(tags, 4) == "alpecca_wardrobe_004_casual_mode_turnaround_v01.png"
    # Role + secondary tags + canon verdict all survive into the manifest.
    m = artlib.merge_into_manifest({}, {"file": "a.png", "category": "l2d_mouth",
                                        "mouth": "ah", "canon_ok": True})
    assert m["a.png"]["category"] == "l2d_mouth" and m["a.png"]["mouth"] == "ah"
    assert "file" not in m["a.png"]


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
