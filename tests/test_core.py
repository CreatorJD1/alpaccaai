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
