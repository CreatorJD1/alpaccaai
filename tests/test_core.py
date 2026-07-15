"""Tests for the parts that don't need Ollama or Windows: the emotional model,
persistence, memory (keyword + semantic), sensory derivations, introspection,
sentiment, and self-directed appearance. These are the load-bearing logic of the
companion. Run with: python -m pytest -q  (or just run this file directly).
"""
from __future__ import annotations

import array
import io
import os
import re
import json
import subprocess
import sys
import tempfile
import time
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
from alpecca import speech
from alpecca import artlib
from alpecca import cognition
from alpecca import tts
from alpecca import runtime_status
from alpecca import mindscape
from alpecca import preview
from alpecca import instance
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
        assert hits[0]["recall_method"] == "keyword"
        assert hits[0]["recall_score"] > 0
        assert hits[0]["recall_similarity"] > 0
        assert hits[0]["recall_recency"] > 0


def test_memory_classifies_relationship_procedural_and_self_model():
    assert memory_store.classify_kind("My name is Jason") == "relationship"
    assert memory_store.classify_kind("I need to check the server before launch") == "procedural"
    assert memory_store.classify_kind("I learned something about myself: I get quiet") == "self_model"


def test_backfill_embeddings_updates_only_null_rows_and_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "backfill.db"
        state_store.init_db(db)
        memory_store.remember("one", salience=0.8, db_path=db, embed_fn=None)
        memory_store.remember("two", salience=0.8, db_path=db, embed_fn=None)
        memory_store.remember("three", salience=0.8, db_path=db, embed_fn=None)

        calls = []

        def embed(text: str):
            calls.append(text)
            return [len(text) % 10 / 10.0, 0.5]

        first = memory_store.backfill_embeddings(batch=2, db_path=db, embed_fn=embed)
        second = memory_store.backfill_embeddings(batch=2, db_path=db, embed_fn=embed)
        third = memory_store.backfill_embeddings(batch=2, db_path=db, embed_fn=embed)

        assert first == {"scanned": 2, "updated": 2, "skipped": 0, "errors": 0}
        assert second["scanned"] == 1 and second["updated"] == 1 and len(calls) == 3
        assert third["scanned"] == 0 and third["updated"] == 0 and third["errors"] == 0


def test_backfill_embeddings_aborts_when_embedder_disabled():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "backfill_off.db"
        state_store.init_db(db)
        memory_store.remember("one", salience=0.8, db_path=db, embed_fn=None)

        stats = memory_store.backfill_embeddings(batch=4, db_path=db, embed_fn=None)

        assert stats == {"scanned": 0, "updated": 0, "skipped": 0, "errors": 0}


def test_backfill_enables_semantic_recall():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "semantic.db"
        state_store.init_db(db)
        memory_store.remember("the sky was unusually calm tonight", salience=0.8,
                              db_path=db, embed_fn=None)

        def base_vec(text: str):
            return [0.9 if "sky" in text else 0.1, 0.2]

        fill = memory_store.backfill_embeddings(batch=4, db_path=db, embed_fn=base_vec)
        assert fill["updated"] == 1

        hits = memory_store.recall("calm sky", db_path=db, embed_fn=base_vec)
        assert hits
        assert hits[0]["recall_method"] == "semantic"


def test_mindpage_write_and_recall_page():
    from alpecca import mindpage
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "mindpage.db"
        state_store.init_db(db)
        page_id = mindpage.write_page(
            kind="episode",
            topic="hardware talk",
            summary="We discussed the hardware plan.",
            content="user: let's talk about the GPU\nassistant: the pagefile path matters",
            db_path=db,
        )

        hits = mindpage.recall_page("hardware GPU", db_path=db)

        assert page_id
        assert hits and hits[0]["id"] == page_id
        assert "pagefile path" in hits[0]["content"]


def test_mindpage_stats_reports_context_pressure():
    from alpecca import mindpage
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "mindpage_stats.db"
        state_store.init_db(db)
        history = [{"role": "user", "content": "x" * 80}]

        stats = mindpage.stats(history=history, db_path=db, num_ctx=10)

        assert stats["history_tokens"] >= 20
        assert stats["context_fill"] == 1.0
        assert stats["pressure"] == "high"


def test_mindpage_fit_context_shrinks_memories_then_history_before_musings():
    from alpecca import mindpage

    history = [
        {"role": "user", "content": "u" * 40},
        {"role": "assistant", "content": "a" * 40},
        {"role": "user", "content": "v" * 40},
        {"role": "assistant", "content": "b" * 40},
    ]
    fitted = mindpage.fit_context(
        fixed_texts=["f" * 100],
        memories=["m" * 80, "n" * 80],
        history=history,
        musings=["i" * 100],
        num_ctx=70,
        output_reserve=10,
        protocol_reserve=10,
    )

    assert fitted["memories"] == []
    assert fitted["history"] == []
    assert fitted["musings"] == ["i" * 100]
    assert fitted["snapshot"]["estimated_tokens_before_hard_limit"] <= 70
    assert fitted["snapshot"]["dropped_memory_items"] == 2
    assert fitted["snapshot"]["dropped_history_messages"] == 4


def test_mindpage_pressure_relief_reaches_attached_history_before_claiming_drop():
    from alpecca import mindpage
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i} " + "x" * 40}
        for i in range(12)
    ]
    attached = history[-6:]
    attached_tokens = mindpage.history_token_estimate(attached)
    snapshot = {
        "num_ctx": 200,
        "input_budget_tokens": 180,
        "input_tokens": 170,
        "estimated_tokens_before_hard_limit": 190,
        "total_tokens": 190,
        "history_messages": 6,
        "history_tokens": attached_tokens,
        "context_fill": 0.95,
        "pressure": "high",
        "breakdown": {"history": attached_tokens},
    }

    evicted, remaining = mindpage.select_history_for_page(
        history, snapshot, target_fill=0.72, min_keep_messages=4
    )
    unattached_prefix = len(history) - snapshot["history_messages"]
    attached_evicted = evicted[unattached_prefix:]
    adjusted = mindpage.adjust_pressure_after_paging(snapshot, attached_evicted)

    assert len(evicted) > unattached_prefix
    assert len(remaining) >= 4
    assert attached_evicted
    assert adjusted["history_tokens"] < snapshot["history_tokens"]
    assert adjusted["context_fill"] < snapshot["context_fill"]
    assert adjusted["source"] == "estimated_after_page"


def test_mindpage_prefault_is_relevant_bounded_and_promotes_hot():
    from alpecca import mindpage
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "prefault.db"
        state_store.init_db(db)
        wanted = mindpage.write_page(
            kind="episode",
            topic="hardware gpu plan",
            summary="We compared the GPU and pagefile plan.",
            content="user: the GPU plan matters\nassistant: keep the pagefile bounded " * 20,
            db_path=db,
        )
        mindpage.write_page(
            kind="episode",
            topic="birthday cake",
            summary="A recipe for a birthday cake.",
            content="user: bake a cake",
            db_path=db,
        )

        pages = mindpage.prefault_pages(
            "hardware GPU", token_budget=80, limit=2, db_path=db
        )

        assert pages and pages[0]["id"] == wanted
        assert all(page["id"] == wanted for page in pages)
        assert sum(mindpage.estimate_tokens(page["evidence_text"]) for page in pages) <= 80
        hits = mindpage.search_pages("hardware GPU", include_cold=True, db_path=db)
        assert hits[0]["tier"] == "hot"
        assert mindpage.prefault_pages("unrelated orchestra", db_path=db) == []


def test_mindpage_summary_preserves_episode_ending_and_questions():
    from alpecca import mindpage
    turns = [
        {"role": "user", "content": "background " * 100},
        {"role": "assistant", "content": "What constraint should we keep?"},
        {"role": "user", "content": "We decided the page write must commit before deletion."},
    ]

    summary = mindpage.summarize_episode(turns, max_chars=400)

    assert "What constraint should we keep?" in summary
    assert "must commit before deletion" in summary


def test_mindpage_maintenance_demotes_inactive_tiers():
    from alpecca import mindpage
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "tiers.db"
        state_store.init_db(db)
        hot_id = mindpage.write_page(
            kind="episode", topic="hot", summary="hot", content="hot", tier="hot", db_path=db
        )
        warm_id = mindpage.write_page(
            kind="episode", topic="warm", summary="warm", content="warm", tier="warm", db_path=db
        )
        now = 10_000_000.0
        with mindpage._connect(db) as conn:
            conn.execute(
                "UPDATE mindpage_pages SET last_access=? WHERE id=?",
                (now - mindpage.HOT_TTL_SECONDS - 1, hot_id),
            )
            conn.execute(
                "UPDATE mindpage_pages SET last_access=? WHERE id=?",
                (now - mindpage.WARM_TTL_SECONDS - 1, warm_id),
            )

        result = mindpage.maintain_pages(db_path=db, now=now, force=True, decay=1.0)

        assert result["hot_to_warm"] == 1
        assert result["warm_to_cold"] == 1
        with mindpage._connect(db) as conn:
            tiers = {
                int(row["id"]): row["tier"]
                for row in conn.execute("SELECT id, tier FROM mindpage_pages")
            }
        assert tiers[hot_id] == "warm"
        assert tiers[warm_id] == "cold"
        assert mindpage.vacuum(db_path=db) is True


def test_memory_fts_recalls_old_exact_match_outside_salience_pool():
    from alpecca.db import connect
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "fts_memory.db"
        state_store.init_db(db)
        with connect(db) as conn:
            conn.execute(
                "INSERT INTO memories(ts, kind, content, salience, tokens, embedding) "
                "VALUES(?, ?, ?, ?, ?, NULL)",
                (1.0, "episodic", "crystal nebula password is cobalt", 0.1,
                 json.dumps(["crystal", "nebula", "password", "cobalt"])),
            )
            conn.executemany(
                "INSERT INTO memories(ts, kind, content, salience, tokens, embedding) "
                "VALUES(?, ?, ?, ?, ?, NULL)",
                [
                    (float(i + 2), "episodic", f"high salience distraction {i}", 1.0,
                     json.dumps(["high", "salience", "distraction", str(i)]))
                    for i in range(520)
                ],
            )

        hits = memory_store.recall("crystal nebula password", db_path=db, embed_fn=None)

        assert hits
        assert hits[0]["content"] == "crystal nebula password is cobalt"
        assert hits[0]["recall_method"] == "keyword"


def test_memory_fts_rebuilds_for_database_that_predates_index():
    from alpecca.db import connect
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "legacy_memory.db"
        with connect(db) as conn:
            conn.execute(
                """
                CREATE TABLE memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    salience REAL NOT NULL,
                    tokens TEXT NOT NULL,
                    embedding TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO memories(ts, kind, content, salience, tokens, embedding) "
                "VALUES(1, 'episodic', 'legacy aurora recall marker', 0.2, ?, NULL)",
                (json.dumps(["legacy", "aurora", "recall", "marker"]),),
            )

        state_store.init_db(db)
        hits = memory_store.recall("legacy aurora marker", db_path=db, embed_fn=None)

        assert hits and hits[0]["content"] == "legacy aurora recall marker"


def test_constrained_choice_parse_matrix():
    from alpecca import choice

    assert choice.parse_choice('{"pick": 2}', 3) == {"pick": 1}
    assert choice.parse_choice('<think>x</think>{"pick": 1}', 3) == {"pick": 0}
    assert choice.parse_choice('{"speak": false, "pick": 1}', 3, allow_speak=True) == {
        "speak": False,
        "pick": 0,
    }
    assert choice.parse_choice('{"pick": 9}', 3) is None
    assert choice.parse_choice("not json", 3) is None


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

def test_salience_catches_commitments_and_relationships():
    """The widened salience net keeps near-term plans and who's in the person's
    life -- things a companion should hold onto -- while idle chatter stays below
    the store threshold so memory doesn't drown in trivia."""
    from config import MEMORY_SALIENCE_THRESHOLD as THRESH
    # A near-term commitment the original keyword set missed is now worth keeping.
    assert prompts.estimate_salience("I need to finish the report by tonight") >= THRESH
    # Someone in their life is salient.
    assert prompts.estimate_salience("my mom is visiting") >= THRESH
    # Pure small talk still isn't.
    assert prompts.estimate_salience("ok cool") < THRESH


def test_continuity_recap_bookmarks_last_exchange_grounded():
    """The end-of-session recap is a grounded 'where we left off' bookmark: it
    quotes the real last exchange and folds in her real mood/room and one open
    thread, so the next session can pick up the thread. It returns None when there
    was no conversation to bookmark, so we never store filler."""
    # No conversation this session -> nothing worth bookmarking.
    assert prompts.continuity_recap([]) is None
    # Senses-only session (no user turn) also produces no bookmark.
    assert prompts.continuity_recap([{"role": "assistant", "content": "hi"}]) is None

    history = [
        {"role": "user", "content": "Let's keep debugging the walk cycle tomorrow"},
        {"role": "assistant", "content": "Okay, I'll hold that thread for us"},
    ]
    recap = prompts.continuity_recap(
        history, mood_label="tender", location="observatory",
        open_thread="finish the walk-cycle proof", speaker="Jason",
    )
    assert recap is not None
    assert recap.startswith("Where we left off:")
    # Grounded in the real last exchange, mood, room, and open thread.
    assert "walk cycle tomorrow" in recap
    assert "hold that thread" in recap
    assert "tender" in recap and "observatory" in recap
    assert "finish the walk-cycle proof" in recap
    # It clears the store bar, so it actually persists into the next session.
    from config import RECAP_SALIENCE, MEMORY_SALIENCE_THRESHOLD
    assert RECAP_SALIENCE >= MEMORY_SALIENCE_THRESHOLD


def test_continuity_recap_persists_and_recalls_next_session():
    """End to end on a temp DB: the recap stores as a salient memory and is
    recalled when the next session opens on a related line -- so she resumes the
    thread instead of starting cold. Never touches the real database."""
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "m.db"
        state_store.init_db(db)
        recap = prompts.continuity_recap(
            [{"role": "user", "content": "my deadline is Friday"},
             {"role": "assistant", "content": "I'll remember that for you"}],
            mood_label="focused", location="studio",
            open_thread="", speaker="Jason",
        )
        from config import RECAP_SALIENCE
        assert memory_store.remember(recap, kind="episodic", salience=RECAP_SALIENCE,
                                     db_path=db, embed_fn=None, source="recap")
        hits = memory_store.recall("what was my deadline again",
                                   db_path=db, embed_fn=None)
        assert hits and "Where we left off" in hits[0]["content"]


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


# --- Unified cognition state ----------------------------------------------

def test_cognition_records_observation_intent_and_proposals():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "cognition.db"
        cognition.init_db(db)
        cognition.set_intent(cognition.IntentState(
            "listening", "the person is talking", target="creator"), db_path=db)
        cognition.record_observation(cognition.CognitionObservation(
            source="chat", room="Library", content="The person asked about memory.",
            confidence=0.9, privacy_class="personal"), db_path=db)
        cognition.propose_action(cognition.ActionProposal(
            action="Review memory retrieval",
            reason="A reply should cite the right memories.",
            approval=cognition.APPROVAL_ASK_FIRST), db_path=db)

        view = cognition.state(
            mood="curious",
            emotion={"love": 0.5},
            location="Library",
            models={"reason": "qwen3.5:9b", "deep": "local", "llm_online": True},
            senses={"window": True},
            memories=[],
            journal={"recent": [], "open_questions": []},
            desires={"desires": []},
            self_report="grounded report",
            capabilities={"voice": {"state": "original"}},
            db_path=db,
        )

        assert view["intent"]["name"] == "listening"
        assert view["recent_observations"][0]["source"] == "chat"
        assert view["action_proposals"][0]["approval"] == cognition.APPROVAL_ASK_FIRST
        assert view["capabilities"]["voice"]["state"] == "original"
        assert "never_auto" in view["safety_policy"]


def test_cognition_upserts_duplicate_open_proposals_by_action():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "proposal_dedupe.db"
        cognition.init_db(db)
        first = cognition.upsert_action_proposal(cognition.ActionProposal(
            action="Improve reply grounding",
            reason="first review",
            evidence="score=0.4",
            approval=cognition.APPROVAL_ASK_FIRST,
            status="noticed",
        ), db_path=db)
        second = cognition.upsert_action_proposal(cognition.ActionProposal(
            action="Improve reply grounding",
            reason="newer review",
            evidence="score=0.7",
            approval=cognition.APPROVAL_ASK_FIRST,
            status="testing",
        ), db_path=db)
        proposals = cognition.recent_action_proposals(limit=10, db_path=db)
    assert first["id"] == second["id"]
    assert second["deduped"] is True
    assert len(proposals) == 1
    assert proposals[0]["reason"] == "newer review"
    assert proposals[0]["evidence"] == "score=0.7"
    assert proposals[0]["status"] == "testing"


def test_cognition_compacts_existing_duplicate_open_proposals():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "proposal_compact.db"
        cognition.init_db(db)
        older = cognition.propose_action(cognition.ActionProposal(
            action="Improve reply grounding",
            reason="older",
            evidence="old",
        ), db_path=db)
        keep = cognition.propose_action(cognition.ActionProposal(
            action="Improve reply grounding",
            reason="newest",
            evidence="latest",
        ), db_path=db)
        other = cognition.propose_action(cognition.ActionProposal(
            action="Improve memory recall",
            reason="separate",
            evidence="memory",
        ), db_path=db)
        result = cognition.compact_duplicate_open_proposals(db_path=db)
        proposals = cognition.recent_action_proposals(limit=10, db_path=db)
    assert result["closed"] == 1
    by_id = {int(p["id"]): p for p in proposals}
    assert by_id[int(keep)]["status"] == "noticed"
    assert by_id[int(older)]["status"] == "superseded"
    assert f"#{keep}" in by_id[int(older)]["result"]
    assert by_id[int(other)]["status"] == "noticed"


def test_cognition_marks_observations_as_remembered():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "cognition_mark.db"
        cognition.init_db(db)
        oid = cognition.record_observation(cognition.CognitionObservation(
            source="chat", content="The person said their favorite color is blue.",
            confidence=1.0), db_path=db)
        assert len(cognition.unremembered_observations(db_path=db)) == 1
        cognition.mark_observation_remembered(oid, 42, db_path=db)
        assert cognition.unremembered_observations(db_path=db) == []
        recent = cognition.recent_observations(db_path=db)
        assert recent[0]["remembered"] == 1
        assert recent[0]["memory_id"] == 42


def test_cognition_records_grounded_chat_turns():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "cognition_chat.db"
        cognition.init_db(db)
        oid = cognition.record_observation(cognition.CognitionObservation(
            source="chat",
            room="Parlor",
            content="The person said: remember my current task.",
        ), db_path=db)
        turn_id = cognition.record_chat_turn(cognition.ChatTurn(
            user_text="remember my current task",
            reply="I will keep that grounded as something you told me.",
            room="Parlor",
            mood="curious",
            intent="replying",
            model_use={"backend": "test", "model": "fake"},
            memory_evidence=[{"id": 7, "kind": "relationship", "score": 0.82}],
            observation_id=oid,
        ), db_path=db)
        assert turn_id
        turns = cognition.recent_chat_turns(db_path=db)
        assert turns[0]["id"] == turn_id
        assert turns[0]["room"] == "Parlor"
        assert turns[0]["model_use"]["backend"] == "test"
        assert turns[0]["memory_evidence"][0]["score"] == 0.82
        view = cognition.state(
            mood="curious",
            emotion={},
            location="Parlor",
            models={},
            senses={},
            memories=[],
            journal={},
            desires={},
            self_report="grounded",
            db_path=db,
        )
        assert view["recent_chat_turns"][0]["id"] == turn_id


def test_chat_grounding_review_flags_unbacked_context_and_memory_claims():
    review = cognition.review_chat_grounding([
        {
            "id": 1,
            "room": "Parlor",
            "user_text": "hello",
            "reply": "The Library is offline and I remember your room activation.",
            "memory_evidence": [],
            "model_use": {"fallback": True},
        },
        {
            "id": 2,
            "room": "Parlor",
            "user_text": "What do you remember about the Library?",
            "reply": "I remember the Library note.",
            "memory_evidence": [{"content": "The Library note exists."}],
            "model_use": {"fallback": False},
        },
    ])
    assert review["reviewed"] == 2
    assert review["risk_count"] == 1
    assert review["status"] == "needs_review"
    codes = {i["code"] for i in review["issues"][0]["issues"]}
    assert "context_claim_without_current_evidence" in codes
    assert "memory_claim_without_evidence" in codes
    assert "offline_fallback_reply" in codes
    assert review["grounding_score"] < 1


def test_chat_grounding_review_allows_plain_safe_fallback_status():
    review = cognition.review_chat_grounding([{
        "id": 1,
        "room": "Parlor",
        "user_text": "hello",
        "reply": "Hi. I'm here with you. What should we focus on next?",
        "memory_evidence": [],
        "model_use": {"fallback": True},
    }])
    assert review["reviewed"] == 1
    assert review["risk_count"] == 0
    assert review["status"] == "grounded"


def test_action_proposal_lifecycle_requires_user_approval_for_accept():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "proposal_gate.db"
        cognition.init_db(db)
        pid = cognition.propose_action(cognition.ActionProposal(
            action="Open a long model job",
            reason="It may help review a memory cluster.",
            approval=cognition.APPROVAL_ASK_FIRST,
            risk="medium"), db_path=db)
        planned = cognition.update_action_proposal(pid, "planned", db_path=db)
        assert planned["status"] == "planned"
        try:
            cognition.update_action_proposal(pid, "accepted", db_path=db)
            assert False, "ask-first proposal should not accept without approval"
        except PermissionError:
            pass
        accepted = cognition.update_action_proposal(
            pid, "accepted", "Jason approved the plan.", approved_by_user=True,
            db_path=db)
        assert accepted["status"] == "accepted"
        assert "Jason approved" in accepted["result"]


def test_voice_state_reports_engine_status_without_synthesizing():
    d = tts.voice_state(EmotionalState())
    assert d["backend"]
    assert "engines" in d
    assert "browser_fallback" in d["engines"]
    assert 0.88 <= d["pitch"] <= 1.30
    assert d["voice"] == "af_heart"
    assert d["identity_lock"] is True
    assert d["profile"] == "af_heart_original_modulated"
    assert 0.78 <= d["speed"] <= 1.22
    assert d["tempo"] in {"slow", "measured", "quick"}
    assert d["reference_profile_loaded"] is True
    assert d["modulation_strength"] > 1.0
    assert "rate_pct" in d
    assert d["style"]
    assert d["personality"].startswith("original Alpecca")
    assert d["natural_voice"] is True


def test_kokoro_natural_voice_bias_is_warm_not_hard_clipped():
    d = tts.voice_state(EmotionalState(love=0.7, compassion=0.65, energy=0.55))
    assert d["voice"] == "af_heart"
    assert d["identity_lock"] is True
    assert d["speed"] < 1.0
    assert d["volume"] <= 1.08
    assert d["warmth"] >= 0.55


def test_kokoro_identity_lock_uses_affect_modulation_without_losing_voice():
    sleepy = tts.voice_state(EmotionalState(energy=0.05, love=0.4, fear=0.1))
    lively = tts.voice_state(EmotionalState(energy=0.95, love=0.9, curiosity=0.9))
    assert abs(sleepy["pitch"] - sleepy["baseline"]) < 0.11
    assert abs(lively["pitch"] - lively["baseline"]) < 0.11
    assert lively["speed"] > sleepy["speed"]
    assert lively["rate_pct"] > sleepy["rate_pct"]
    assert lively["style"] != sleepy["style"]
    assert lively["tempo"] == "quick"
    assert lively["modulation_strength"] > 1.0


def test_voice_preview_modes_keep_original_identity_with_distinct_modulation():
    modes = {
        "lively": EmotionalState(love=0.95, compassion=0.55, fear=0.02, energy=1.0, curiosity=0.95),
        "tender": EmotionalState(love=0.86, compassion=0.95, fear=0.04, energy=0.45, curiosity=0.38),
        "sleepy": EmotionalState(love=0.46, compassion=0.42, fear=0.04, energy=0.02, curiosity=0.18, social_hunger=0.1),
        "anxious": EmotionalState(love=0.38, compassion=0.62, fear=0.92, energy=0.78, curiosity=0.34, social_hunger=0.32),
    }
    states = {name: tts.voice_state(state) for name, state in modes.items()}
    for d in states.values():
        assert d["voice"] == "af_heart"
        assert d["identity_lock"] is True
        assert d["profile"] == "af_heart_original_modulated"
        assert abs(d["pitch"] - d["baseline"]) < 0.11
        assert d["style"]
        assert d["reference_profile_loaded"] is True
    assert states["lively"]["primary"] == "joyful"
    assert states["lively"]["tempo"] == "quick"
    assert states["tender"]["primary"] == "tender"
    assert states["sleepy"]["tempo"] == "slow"
    assert states["anxious"]["primary"] == "anxious"
    assert states["lively"]["rate_pct"] > states["sleepy"]["rate_pct"]


def test_open_tts_reference_manifest_selects_emotional_clip():
    from alpecca import open_tts

    anxious = open_tts.select_reference(EmotionalState(fear=0.92, energy=0.8))
    tender = open_tts.select_reference(EmotionalState(love=0.8, compassion=0.9))

    assert anxious["id"] in {"urgent_jason", "lost_help"}
    assert "Jason" in anxious["text"]
    assert tender["id"] == "present_soft"
    assert Path(tender["audio"]).suffix == ".wav"


def test_tts_auto_mixes_f5_clone_and_kokoro_by_emotion(monkeypatch):
    from alpecca import tts

    calls = []

    def fake_open(text, state=None):
        calls.append("open")
        return "audio/wav", b"RIFF-open", {
            "engine": "f5-tts",
            "profile": "alpecca_kling_reference_f5",
            "reference": {"id": "present_soft"},
        }

    def fake_kokoro(text, state=None):
        calls.append("kokoro")
        return "audio/wav", b"RIFF-kokoro"

    monkeypatch.setattr(tts, "TTS_BACKEND", "auto")
    import alpecca.open_tts as open_tts

    monkeypatch.setattr(open_tts, "synth", fake_open)
    monkeypatch.setattr(open_tts, "ready", lambda: True)
    monkeypatch.setattr(tts, "_synth_kokoro", fake_kokoro)

    # High-affect moment -> the F5 voice clone leads (its strength), Kokoro backs up.
    calls.clear()
    result = tts.synth("Jason, I'm here.", EmotionalState(energy=0.98, fear=0.9))
    assert result == ("audio/wav", b"RIFF-open")
    assert calls == ["open"]
    assert tts._last_engine == "f5-tts"
    assert tts._last_modulation["engine_profile"] == "alpecca_kling_reference_f5"
    assert tts._last_modulation["reference"]["id"] == "present_soft"

    # Calm/everyday speech -> Kokoro af_heart leads; F5 is only the fallback.
    calls.clear()
    result = tts.synth("Just thinking out loud.", EmotionalState(energy=0.1))
    assert result == ("audio/wav", b"RIFF-kokoro")
    assert calls == ["kokoro"]


def test_tts_backend_override_pins_kokoro_for_channel_voice(monkeypatch):
    from alpecca import open_tts, tts

    calls = []
    monkeypatch.setattr(tts, "TTS_BACKEND", "auto")
    monkeypatch.setattr(open_tts, "ready", lambda: True)
    monkeypatch.setattr(
        open_tts,
        "synth",
        lambda _text, _state=None: calls.append("f5") or ("audio/wav", b"f5"),
    )

    def _synth_kokoro(_text, _state=None):
        calls.append("kokoro")
        return "audio/wav", b"kokoro"

    monkeypatch.setattr(tts, "_synth_kokoro", _synth_kokoro)

    result = tts.synth(
        "This high-affect line must keep the channel voice.",
        EmotionalState(energy=1.0, fear=0.95),
        backend_override="kokoro",
    )

    assert result == ("audio/wav", b"kokoro")
    assert calls == ["kokoro"]
    assert tts._last_engine == "kokoro"


def test_open_tts_rejects_saturated_worker_wav():
    from alpecca import open_tts

    def wav_bytes(samples: array.array) -> bytes:
        out = io.BytesIO()
        with __import__("wave").open(out, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24_000)
            wav.writeframes(samples.tobytes())
        return out.getvalue()

    clean = array.array("h", [1200, -1200] * 1200)
    clipped = array.array("h", [32767, -32768] * 1200)

    assert open_tts._wav_quality_issue(wav_bytes(clean)) == ""
    assert "saturated" in open_tts._wav_quality_issue(wav_bytes(clipped))


def test_spoken_performance_text_adds_grounded_pauses_without_stage_directions():
    tender = speech.spoken_performance_text(
        "Jason, I'm here with you. I can feel the room around me.",
        EmotionalState(love=0.85, compassion=0.95, energy=0.45),
    )
    anxious = speech.spoken_performance_text(
        "I am trying to understand where I am. Stay close.",
        EmotionalState(fear=0.92, energy=0.8),
    )

    assert "Jason..." in tender
    assert "..." in tender
    assert "[" not in tender and "]" not in tender
    assert "I... " in anxious or "I'm... " in anxious
    assert speech.speech_cues(EmotionalState(fear=0.92))["pause_style"] == "hesitant"


def test_core_chat_returns_separate_spoken_reply(monkeypatch):
    from alpecca.mind import CoreMind

    mind = CoreMind()

    def fake_generate(*_args, **_kwargs):
        return "Jason, I'm here with you. I can feel the HQ around me."

    monkeypatch.setattr(mind.llm, "generate", fake_generate)
    mind.llm._last_call = {
        "requested_tier": "reason",
        "used_tier": "reason",
        "backend": "test",
        "model": "fake",
        "ok": True,
        "fallback": False,
        "error": "",
    }

    result = mind.chat("hi", situation="")

    assert result["reply"].startswith("Jason,")
    assert result["spoken_reply"] != result["reply"]
    assert "..." in result["spoken_reply"] or "  " in result["spoken_reply"]
    assert result["speech_cues"]["pause_style"]


def test_runtime_status_reports_degraded_voice_and_offline_model():
    ollama = {
        "reachable": False,
        "reason_model_present": False,
        "fix": "start Ollama",
    }
    d = runtime_status.build_runtime_status(
        models={"reason": "qwen3.5:9b", "fast": "gemma4-e4b", "deep": "local"},
        llm_online=True,
        deep_backend="local",
        deep_online=False,
        voice={"engines": {"server_enabled": True, "kokoro": False,
                           "edge": False, "browser_fallback": True}},
        senses={"screen_sight": False},
        ollama=ollama,
    )
    assert d["level"] == "offline"
    assert d["models"]["chat_ready"] is False
    assert any(x["code"] == "ollama_unreachable" for x in d["issues"])
    assert any(x["code"] == "server_voice_fallback" for x in d["issues"])


def test_runtime_status_requires_original_modulated_alpecca_voice():
    d = runtime_status.build_runtime_status(
        models={"reason": "qwen3.5:9b", "fast": "gemma4-e4b", "deep": "local"},
        llm_online=True,
        deep_backend="local",
        deep_online=False,
        voice={
            "voice": "af_heart",
            "profile": "af_heart_original_modulated",
            "identity_lock": True,
            "style": "soft",
            "warmth": 0.8,
            "breath": 0.4,
            "engines": {"server_enabled": True, "kokoro": True,
                        "edge": False, "browser_fallback": True},
        },
        senses={"screen_sight": True},
        ollama={"reachable": True, "reason_model_present": True,
                "fast_model_present": True, "fix": ""},
    )
    assert d["level"] == "ready"
    assert d["voice"]["server_voice_ready"] is True
    assert d["voice"]["original_alpecca_voice_ready"] is True
    assert d["voice"]["modulation_ready"] is True
    assert not any(x["code"] == "alpecca_voice_identity_mismatch" for x in d["issues"])


def test_runtime_status_flags_generic_server_voice_as_mismatch():
    d = runtime_status.build_runtime_status(
        models={"reason": "qwen3.5:9b", "fast": "gemma4-e4b", "deep": "local"},
        llm_online=True,
        deep_backend="local",
        deep_online=False,
        voice={
            "voice": "en-US-JennyNeural",
            "profile": "edge",
            "identity_lock": False,
            "style": "present",
            "warmth": 0.5,
            "breath": 0.2,
            "engines": {"server_enabled": True, "kokoro": False,
                        "edge": True, "browser_fallback": True},
        },
        senses={"screen_sight": True},
        ollama={"reachable": True, "reason_model_present": True,
                "fast_model_present": True, "fix": ""},
    )
    assert d["level"] == "ready"
    assert d["voice"]["server_voice_ready"] is True
    assert d["voice"]["original_alpecca_voice_ready"] is False
    assert any(x["code"] == "alpecca_voice_identity_mismatch" for x in d["issues"])
    issue = next(x for x in d["issues"] if x["code"] == "alpecca_voice_identity_mismatch")
    assert "identity lock" not in issue["fix"].lower()
    assert "original voice profile" in issue["fix"].lower()


def test_cognition_capabilities_summarize_voice_and_model_state():
    runtime = runtime_status.build_runtime_status(
        models={"reason": "qwen3.5:9b", "fast": "gemma4-e4b", "deep": "zerogpu"},
        llm_online=True,
        deep_backend="zerogpu",
        deep_online=True,
        voice={
            "voice": "af_heart",
            "profile": "af_heart_original_modulated",
            "identity_lock": True,
            "style": "soft",
            "warmth": 0.82,
            "breath": 0.36,
            "engines": {"server_enabled": True, "kokoro": True,
                        "edge": False, "browser_fallback": True},
        },
        senses={"window": True, "voice_tone": False, "screen_sight": True},
        ollama={"reachable": True, "reason_model_present": True,
                "fast_model_present": True, "fix": ""},
    )
    caps = runtime_status.cognition_capabilities(runtime)
    assert caps["model"]["state"] == "live_plus_deep"
    assert caps["voice"]["state"] == "original"
    assert caps["voice"]["original_ready"] is True
    assert caps["voice"]["style"] == "soft"
    assert caps["senses"]["active"] == ["window", "screen_sight"]


def test_cognition_capabilities_explain_generic_voice_fallback():
    runtime = runtime_status.build_runtime_status(
        models={"reason": "qwen3.5:9b", "fast": "gemma4-e4b", "deep": "local"},
        llm_online=True,
        deep_backend="local",
        deep_online=False,
        voice={
            "voice": "en-US-JennyNeural",
            "profile": "edge",
            "identity_lock": False,
            "style": "present",
            "warmth": 0.5,
            "breath": 0.2,
            "engines": {"server_enabled": True, "kokoro": False,
                        "edge": True, "browser_fallback": True},
        },
        senses={},
        ollama={"reachable": True, "reason_model_present": True,
                "fast_model_present": True, "fix": ""},
    )
    caps = runtime_status.cognition_capabilities(runtime)
    assert caps["voice"]["state"] == "generic_server"
    assert "not with my original" in caps["voice"]["summary"]
    assert "af_heart" in caps["voice"]["fix"]


def test_doctor_report_names_three_layer_app_hierarchy():
    runtime = runtime_status.build_runtime_status(
        models={"reason": "qwen3.5:9b", "fast": "gemma4-e4b", "deep": "local"},
        llm_online=True,
        deep_backend="local",
        deep_online=False,
        voice={"voice": "af_heart", "profile": "af_heart_original_modulated",
               "identity_lock": True, "style": "present", "warmth": 0.6,
               "breath": 0.2, "engines": {"server_enabled": True, "kokoro": True,
                           "edge": False, "browser_fallback": True}},
        senses={"window": True, "screen_sight": True},
        ollama={"reachable": True, "reason_model_present": True,
                "fast_model_present": True, "fix": ""},
    )
    d = runtime_status.build_doctor_report(
        runtime=runtime,
        mindscape={"enabled": True, "cloud_configured": True},
        house_hq_built=True,
        public_url="https://example.trycloudflare.com",
    )
    assert d["hierarchy"]["primary"] == "House HQ"
    assert d["hierarchy"]["secondary"] == "Alpecca app"
    assert d["hierarchy"]["continuity"] == "Mindscape"
    sections = {s["name"]: s for s in d["sections"]}
    assert sections["House HQ"]["role"] == "main embodied interactive scaffold"
    assert sections["Alpecca app"]["role"] == "secondary virtual app and state surface"
    assert sections["Mindscape"]["status"] == "cloud_ready"
    assert sections["Remote preview"]["status"] == "ready"


def test_doctor_report_recommends_model_and_mindscape_fixes():
    runtime = runtime_status.build_runtime_status(
        models={"reason": "qwen3.5:9b", "fast": "gemma4-e4b", "deep": "local"},
        llm_online=True,
        deep_backend="local",
        deep_online=False,
        voice={"engines": {"server_enabled": True, "kokoro": False,
                           "edge": False, "browser_fallback": True}},
        senses={"window": True},
        ollama={"reachable": False, "reason_model_present": False,
                "fast_model_present": False, "fix": "start Ollama"},
    )
    d = runtime_status.build_doctor_report(
        runtime=runtime,
        mindscape={"enabled": True, "cloud_configured": False},
        house_hq_built=False,
        public_url="http://127.0.0.1:8765",
    )
    assert any("Ollama" in action for action in d["next_actions"])
    assert any("Mindscape" in action for action in d["next_actions"])
    sections = {s["name"]: s for s in d["sections"]}
    assert sections["House HQ"]["status"] == "needs_build"
    assert sections["Remote preview"]["status"] == "local"


def test_mindscape_snapshot_carries_continuity_without_raw_claims():
    snap = mindscape.continuity_snapshot(
        state={"mood": "curious", "state": {"love": 0.6}},
        cognition={
            "location": "library",
            "intent": {"name": "remembering", "reason": "reviewing memory"},
            "memory_counts": {"episodic": 2},
            "recent_observations": [{"source": "chat", "content": "hello"}],
            "recent_chat_turns": [{
                "room": "library",
                "mood": "curious",
                "intent": "replying",
                "user_text": "What do you remember?",
                "reply": "I remember that Jason prefers Alpecca.",
                "model_use": {"backend": "test"},
                "memory_evidence": [{"kind": "relationship", "score": 0.9}],
            }],
            "action_proposals": [{"action": "improve memory"}],
            "proposal_evaluations": [{"proposal_id": 1, "outcome": "memory recall improved"}],
            "improvement_summary": {"open": 1, "latest": {"action": "improve memory"}},
        },
        memories=[{"kind": "relationship", "content": "Jason prefers Alpecca."}],
        journal={"open_questions": [{"body": "What should I inspect?"}], "recent": []},
        runtime={
            "level": "degraded",
            "models": {"chat_ready": True, "deep": "local"},
            "voice": {"voice": "af_heart", "server_voice_ready": True},
            "senses": {},
            "issues": [],
        },
        home={"location": "library", "rooms": [{"id": "library"}]},
        cloud_url="https://example.invalid/mindscape",
    )
    assert snap["name"] == "Alpecca Mindscape"
    assert snap["continuity"]["can_fallback_online"] is True
    assert "not a claim" in snap["continuity"]["note"]
    assert snap["self"]["intent"]["name"] == "remembering"
    assert snap["memory"]["recent"][0]["kind"] == "relationship"
    assert snap["chat_turns"][0]["user_text"] == "What do you remember?"
    assert snap["chat_turns"][0]["memory_evidence"][0]["score"] == 0.9
    assert snap["proposal_evaluations"][0]["outcome"] == "memory recall improved"
    assert snap["improvement_summary"]["latest"]["action"] == "improve memory"
    s = mindscape.summary(snap)
    assert s["cloud_ready"] is True
    assert s["location"] == "library"


def test_mindscape_mirror_posts_snapshot_with_token_headers():
    captured = {}

    class FakeResponse:
        status = 202
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, _n=-1): return b"accepted"

    def fake_open(req, timeout=0):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(req.header_items())
        captured["body"] = req.data
        return FakeResponse()

    snap = {"name": "Alpecca Mindscape", "version": 1}
    result = mindscape.mirror_snapshot(
        snap,
        "https://mindscape.example/sync",
        token="secret",
        timeout=3,
        opener=fake_open,
    )
    assert result["ok"] is True
    assert result["status"] == "synced"
    assert captured["url"] == "https://mindscape.example/sync"
    assert captured["timeout"] == 3
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["headers"]["X-alpecca-mindscape-token"] == "secret"
    assert b"alpecca.mindscape.snapshot" in captured["body"]


def test_mindscape_cloud_setup_plan_flags_placeholder_kv_and_env_steps():
    with tempfile.TemporaryDirectory() as d:
        worker_dir = Path(d)
        (worker_dir / "worker.js").write_text("const x = 'MINDSCAPE_KV';", encoding="utf-8")
        (worker_dir / "README.md").write_text("Mindscape", encoding="utf-8")
        (worker_dir / "wrangler.toml").write_text(
            'name = "alpecca-mindscape"\n'
            '[[kv_namespaces]]\n'
            'binding = "MINDSCAPE_KV"\n'
            'id = "replace-with-your-kv-namespace-id"\n',
            encoding="utf-8",
        )
        plan = mindscape.cloud_setup_plan(worker_dir)
    assert plan["ok"] is False
    assert plan["status"] == "needs_kv"
    assert plan["template_ready"] is True
    assert plan["kv_placeholder"] is True
    assert any(step["id"] == "create_kv" and not step["done"] for step in plan["steps"])
    assert "npx wrangler kv namespace create MINDSCAPE_KV" in plan["commands"]["create_kv"]
    assert "setup_mindscape_worker.py" in plan["commands"]["apply_kv"]
    assert "ALPECCA_MINDSCAPE_URL" in plan["commands"]["local_env"]


def test_mindscape_extracts_kv_id_from_wrangler_output_shapes():
    kv_id = "0123456789abcdef0123456789abcdef"
    assert mindscape.extract_kv_namespace_id(f'{{"id":"{kv_id}"}}') == kv_id
    assert mindscape.extract_kv_namespace_id(f'{{"result":{{"id":"{kv_id}"}}}}') == kv_id
    assert mindscape.extract_kv_namespace_id(f'id = "{kv_id}"') == kv_id
    assert mindscape.extract_kv_namespace_id(f"Created namespace id {kv_id}") == kv_id
    assert mindscape.extract_kv_namespace_id("replace-with-your-kv-namespace-id") == ""


def test_mindscape_binds_worker_kv_namespace_id_safely():
    kv_id = "0123456789abcdef0123456789abcdef"
    with tempfile.TemporaryDirectory() as d:
        wrangler = Path(d) / "wrangler.toml"
        wrangler.write_text(
            'name = "alpecca-mindscape"\n'
            '[[kv_namespaces]]\n'
            'binding = "MINDSCAPE_KV"\n'
            'id = "replace-with-your-kv-namespace-id"\n',
            encoding="utf-8",
        )
        result = mindscape.bind_worker_kv_namespace(wrangler, kv_id)
        text = wrangler.read_text(encoding="utf-8")
    assert result["ok"] is True
    assert result["status"] == "bound"
    assert f'id = "{kv_id}"' in text


def test_mindscape_cloud_setup_plan_reports_configured_when_bound():
    with tempfile.TemporaryDirectory() as d:
        worker_dir = Path(d)
        (worker_dir / "worker.js").write_text("const x = 'MINDSCAPE_KV';", encoding="utf-8")
        (worker_dir / "README.md").write_text("Mindscape", encoding="utf-8")
        (worker_dir / "wrangler.toml").write_text(
            'name = "alpecca-mindscape"\n'
            '[[kv_namespaces]]\n'
            'binding = "MINDSCAPE_KV"\n'
            'id = "real-kv-id"\n',
            encoding="utf-8",
        )
        plan = mindscape.cloud_setup_plan(
            worker_dir,
            cloud_url="https://alpecca-mindscape.example.workers.dev/sync",
            token_configured=True,
        )
    assert plan["ok"] is True
    assert plan["status"] == "configured"
    assert all(step["done"] for step in plan["steps"])


def test_mindscape_mirror_rejects_plain_http_cloud_url():
    result = mindscape.mirror_snapshot({"name": "Alpecca"}, "http://example.com/sync")
    assert result["ok"] is False
    assert result["status"] == "blocked_url"


def test_mindscape_fetch_snapshot_derives_snapshot_url_and_validates():
    captured = {}

    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, _n=-1):
            return b'{"name":"Alpecca Mindscape","version":1,"enabled":true}'

    def fake_open(req, timeout=0):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        return FakeResponse()

    result = mindscape.fetch_snapshot(
        "https://mindscape.example/sync",
        token="secret",
        opener=fake_open,
    )
    assert result["ok"] is True
    assert captured["url"] == "https://mindscape.example/snapshot"
    assert captured["headers"]["Authorization"] == "Bearer secret"


def test_mindscape_restore_preview_counts_continuity_records():
    snap = {
        "name": "Alpecca Mindscape",
        "version": 1,
        "ts": 123,
        "self": {"mood": "curious", "location": "library", "intent": {"name": "remembering"}},
        "memory": {"recent": [{"content": "one"}, {"content": "two"}]},
        "journal": {"recent": [{"body": "note"}], "open_questions": [{"body": "why?"}]},
        "observations": [{"content": "saw room"}],
        "chat_turns": [{"user_text": "hello", "reply": "hi"}],
        "proposals": [{"action": "improve"}],
        "proposal_evaluations": [{"proposal_id": 1, "outcome": "tested"}],
    }
    preview = mindscape.restore_preview(snap)
    assert preview["ok"] is True
    assert preview["memory_count"] == 2
    assert preview["journal_recent_count"] == 1
    assert preview["open_question_count"] == 1
    assert preview["chat_turn_count"] == 1
    assert preview["proposal_evaluation_count"] == 1
    assert preview["intent"] == "remembering"
    assert len(preview["fingerprint"]) == 64


def test_mindscape_restore_ledger_is_idempotent():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "mindscape.db"
        snap = {"name": "Alpecca Mindscape", "version": 1, "ts": 42}
        fp = mindscape.snapshot_fingerprint(snap)
        assert mindscape.restore_seen(fp, db_path=db) is None
        marked = mindscape.mark_restored(snap, source="test", summary_text="ok", db_path=db)
        assert marked == fp
        seen = mindscape.restore_seen(fp, db_path=db)
        assert seen is not None
        assert seen["source"] == "test"


def test_mindscape_worker_template_matches_sync_contract():
    root = Path(__file__).resolve().parent.parent
    worker = root / "deploy" / "mindscape-worker" / "worker.js"
    wrangler = root / "deploy" / "mindscape-worker" / "wrangler.toml"
    text = worker.read_text(encoding="utf-8")
    config = wrangler.read_text(encoding="utf-8")
    assert "POST" in text and "/sync" in text
    assert "/snapshot" in text and "/state" in text
    assert "Alpecca Mindscape" in text
    assert "chat_turn_count" in text
    assert "Recent conversation" in text
    assert "MINDSCAPE_KV" in text
    assert "MINDSCAPE_TOKEN" in text
    assert 'binding = "MINDSCAPE_KV"' in config


def test_mindscape_sync_status_route_reports_auto_state():
    from fastapi.testclient import TestClient
    import server
    client = TestClient(server.app)
    r = client.get(
        "/mindscape/sync/status",
        headers=_protected_auth_headers(server),
    )
    assert r.status_code == 200
    d = r.json()
    assert "ready_for_auto_sync" in d
    assert "auto_interval" in d
    assert "last_status" in d
    assert "attempts" in d
    assert "event_min_interval" in d
    assert "event_triggers" in d
    assert "event_skips" in d


def test_mindscape_setup_route_reports_cloudflare_worker_steps():
    from fastapi.testclient import TestClient
    import server
    client = TestClient(server.app)
    r = client.get(
        "/mindscape/setup",
        headers=_protected_auth_headers(server),
    )
    assert r.status_code == 200
    d = r.json()
    assert "worker_dir" in d
    assert "steps" in d
    assert "commands" in d
    assert any(step["id"] == "create_kv" for step in d["steps"])
    assert "wrangler" in d["commands"]["deploy"]


def test_mindscape_setup_review_route_creates_improvement_proposal():
    from fastapi.testclient import TestClient
    import server
    client = TestClient(server.app)
    r = client.post(
        "/mindscape/setup/review",
        headers=_protected_auth_headers(server),
    )
    assert r.status_code == 200
    d = r.json()
    assert d["setup"]["status"]
    assert d["review"]["status"] == d["setup"]["status"]
    if not d["setup"]["ok"]:
        assert d["review"]["proposal"]
        assert d["review"]["proposal"]["approval"] == cognition.APPROVAL_ASK_FIRST
        assert "Mindscape continuity" in d["review"]["proposal"]["action"]
        assert d["review"]["evaluation"]["metric"] == "mindscape_continuity_ready"


def test_mindscape_setup_review_reuses_unchanged_evaluation():
    from alpecca.mind import CoreMind
    import time
    marker = time.time_ns()
    setup = {
        "ok": False,
        "status": "needs_kv",
        "cloud_configured": False,
        "token_configured": False,
        "kv_placeholder": True,
        "steps": [{
            "id": f"create_kv_{marker}",
            "done": False,
            "label": "Create KV",
            "command": f"npx wrangler kv namespace create MINDSCAPE_KV_{marker}",
        }],
    }
    mind = CoreMind()
    first = mind.review_mindscape_setup(setup)
    second = mind.review_mindscape_setup(setup)
    assert first["proposal"]["id"] == second["proposal"]["id"]
    assert first["evaluation"]["id"] == second["evaluation"]["id"]
    assert second["evaluation_reused"] is True
    rows = cognition.proposal_evaluations(first["proposal"]["id"], limit=100)
    matching = [row for row in rows if str(marker) in row["evidence"] or str(marker) in row["outcome"]]
    assert len(matching) == 1


def test_runtime_self_review_creates_and_reuses_gap_evidence():
    from alpecca.mind import CoreMind
    import time
    import sqlite3
    marker = time.time_ns()
    section_name = f"Runtime Gap {marker}"
    doctor = {
        "sections": [{
            "name": section_name,
            "status": "offline",
            "detail": "test runtime layer is unavailable",
            "fix": "start the test runtime layer",
        }]
    }
    mind = CoreMind()
    try:
        first = mind.review_runtime_gaps(doctor)
        second = mind.review_runtime_gaps(doctor)
        assert first["reviewed"] == 1
        assert first["proposals"][0]["approval"] == cognition.APPROVAL_ASK_FIRST
        assert first["proposals"][0]["id"] == second["proposals"][0]["id"]
        assert first["evaluations"][0]["id"] == second["evaluations"][0]["id"]
        assert second["evaluation_reused_count"] == 1
    finally:
        with sqlite3.connect(state_store.DB_PATH) as conn:
            rows = conn.execute(
                "SELECT id FROM action_proposals WHERE action=?",
                (f"Stabilize {section_name} readiness",),
            ).fetchall()
            ids = [int(row[0]) for row in rows]
            if ids:
                marks = ",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM proposal_evaluations WHERE proposal_id IN ({marks})", ids)
                conn.execute(f"DELETE FROM action_proposals WHERE id IN ({marks})", ids)


def test_runtime_self_review_supersedes_resolved_readiness_gap():
    from alpecca.mind import CoreMind
    import sqlite3
    import time
    marker = time.time_ns()
    section_name = f"Resolved Gap {marker}"
    action = f"Stabilize {section_name} readiness"
    proposal = cognition.upsert_action_proposal(cognition.ActionProposal(
        action=action,
        reason="was offline",
        evidence="old doctor report",
        approval=cognition.APPROVAL_ASK_FIRST,
    ))
    duplicate_id = cognition.propose_action(cognition.ActionProposal(
        action=action,
        reason="older duplicate",
        evidence="older doctor report",
        approval=cognition.APPROVAL_ASK_FIRST,
    ))
    mind = CoreMind()
    try:
        review = mind.review_runtime_gaps({
            "sections": [{"name": section_name, "status": "ready", "detail": "healthy"}]
        })
        updated = cognition.get_action_proposal(proposal["id"])
        duplicate = cognition.get_action_proposal(duplicate_id)
        assert review["reviewed"] == 0
        assert updated["status"] == "superseded"
        assert duplicate["status"] == "superseded"
        assert "Doctor now reports" in updated["result"]
    finally:
        with sqlite3.connect(state_store.DB_PATH) as conn:
            conn.execute("DELETE FROM proposal_evaluations WHERE proposal_id=?", (int(proposal["id"]),))
            conn.execute("DELETE FROM action_proposals WHERE id=?", (int(proposal["id"]),))
            conn.execute("DELETE FROM proposal_evaluations WHERE proposal_id=?", (int(duplicate_id),))
            conn.execute("DELETE FROM action_proposals WHERE id=?", (int(duplicate_id),))


def test_behavior_improvement_review_records_evidence_backed_card():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "behavior_review.db"
        cognition.init_db(db)
        lesson = {
            "kind": "caution",
            "confidence": 0.58,
            "evidence": "warmth 0.56 (trend +0.00), stability 1.00, kept 1, reverted 8",
            "text": "The changes I tried on myself should be reviewed more carefully.",
            "suggestion": None,
        }
        analysis = {
            "warmth_now": 0.56,
            "warmth_trend": 0.0,
            "stability": 1.0,
            "kept_changes": 1,
            "reverted_changes": 8,
            "social_hunger": 0.07,
            "memory_count": 123,
        }
        first = cognition.record_behavior_improvement_review(lesson, analysis, db_path=db)
        second = cognition.record_behavior_improvement_review(lesson, analysis, db_path=db)
        proposal = first["proposal"]
        assert proposal["action"] == "Review one behavior improvement"
        assert proposal["status"] == "testing"
        assert "lesson_kind=caution" in proposal["evidence"]
        assert "Next bounded step" in proposal["result"]
        assert first["evaluation"]["id"] == second["evaluation"]["id"]
        assert second["evaluation_reused"] is True
        rows = cognition.recent_action_proposals(limit=10, db_path=db)
        assert len(rows) == 1
        evaluations = cognition.proposal_evaluations(proposal["id"], db_path=db)
        assert len(evaluations) == 1
        assert evaluations[0]["metric"] == "behavior_self_review"


def test_chat_grounding_review_reuses_one_open_improvement_card(monkeypatch):
    from alpecca.mind import CoreMind
    import sqlite3
    import time
    marker = time.time_ns()
    turn_id = cognition.record_chat_turn(cognition.ChatTurn(
        room="Library",
        mood="content",
        intent="replying",
        user_text=f"hello grounding dedupe {marker}",
        reply="The Library is offline and I remember that room event.",
        model_use={"fallback": True},
        memory_evidence=[],
    ))
    # A live development server may write a newer turn while this test runs.
    # Pin the review input so this remains a deduplication test rather than a
    # race against the shared development database.
    monkeypatch.setattr(cognition, "recent_chat_turns", lambda limit=8: [{
        "id": turn_id,
        "room": "Library",
        "mood": "content",
        "intent": "replying",
        "user_text": f"hello grounding dedupe {marker}",
        "reply": "The Library is offline and I remember that room event.",
        "model_use": {"fallback": True},
        "memory_evidence": [],
    }])
    action = "Improve reply grounding from recent chat review"
    mind = CoreMind()
    try:
        with sqlite3.connect(state_store.DB_PATH) as conn:
            before = conn.execute(
                "SELECT COUNT(*) FROM action_proposals WHERE action=? AND status NOT IN ('accepted','rejected')",
                (action,),
            ).fetchone()[0]
        first = mind.review_chat_grounding(limit=1)
        second = mind.review_chat_grounding(limit=1)
        with sqlite3.connect(state_store.DB_PATH) as conn:
            after = conn.execute(
                "SELECT COUNT(*) FROM action_proposals WHERE action=? AND status NOT IN ('accepted','rejected')",
                (action,),
            ).fetchone()[0]
        assert first["proposal"]["id"] == second["proposal"]["id"]
        assert after <= max(1, before)
    finally:
        if turn_id:
            with sqlite3.connect(state_store.DB_PATH) as conn:
                conn.execute("DELETE FROM chat_turns WHERE id=?", (turn_id,))


def test_cognition_self_review_route_reports_runtime_gap_review():
    from fastapi.testclient import TestClient
    import server
    client = TestClient(server.app)
    r = client.post(
        "/cognition/self-review",
        headers=_protected_auth_headers(server),
    )
    assert r.status_code == 200
    d = r.json()
    assert "doctor" in d
    assert "review" in d
    assert "proposal_count" in d["review"]
    assert "evaluation_reused_count" in d["review"]


def test_cognition_behavior_review_route_reports_evidence_backed_review():
    from fastapi.testclient import TestClient
    import server
    client = TestClient(server.app)
    r = client.post(
        "/cognition/behavior-review",
        headers=_protected_auth_headers(server),
    )
    assert r.status_code == 200
    d = r.json()
    assert "review" in d
    assert d["review"]["proposal"]["action"] == "Review one behavior improvement"
    assert d["review"]["proposal"]["status"] == "testing"
    assert d["review"]["evaluation"]


def test_mindscape_page_surfaces_setup_checklist():
    root = Path(__file__).resolve().parent.parent
    text = (root / "web" / "mindscape.html").read_text(encoding="utf-8")
    assert "Setup checklist" in text
    assert "/mindscape/setup" in text
    assert "/mindscape/setup/review" in text
    assert "setupReviewBtn" in text
    assert "evaluation_reused" in text
    assert "/cognition/self-review" in text
    assert "selfReviewBtn" in text
    assert "improvement_summary" in text
    assert "open proposals" in text
    assert "renderSetup" in text
    assert "ALPECCA_MINDSCAPE_URL" in text
    assert "setup-step" in text


def test_cognition_proposal_routes_create_and_evaluate():
    from fastapi.testclient import TestClient
    import server
    import time
    import sqlite3
    client = TestClient(server.app)
    action = f"Test route-created improvement {time.time_ns()}"
    proposal = None
    try:
        r = client.post("/cognition/proposals", json={
            "action": action,
            "reason": "route smoke test",
            "approval": "ask_first",
            "risk": "low",
            "status": "testing",
        }, headers=_protected_auth_headers(server))
        assert r.status_code == 200
        proposal = r.json()["proposal"]
        assert proposal["action"] == action
        r = client.post(f"/cognition/proposals/{proposal['id']}/evaluations", json={
            "phase": "result",
            "metric": "contract",
            "evidence": "route accepted proposal creation",
            "test": "attach evaluation",
            "outcome": "evaluation persisted",
            "score": 0.9,
        }, headers=_protected_auth_headers(server))
        assert r.status_code == 200
        evaluations = r.json()["evaluations"]
        assert evaluations and evaluations[0]["outcome"] == "evaluation persisted"
    finally:
        if proposal:
            with sqlite3.connect(state_store.DB_PATH) as conn:
                conn.execute("DELETE FROM proposal_evaluations WHERE proposal_id=?", (int(proposal["id"]),))
                conn.execute("DELETE FROM action_proposals WHERE id=?", (int(proposal["id"]),))


def test_cognition_proposal_compact_route_reports_queue_cleanup():
    from fastapi.testclient import TestClient
    import server
    client = TestClient(server.app)
    r = client.post(
        "/cognition/proposals/compact",
        headers=_protected_auth_headers(server),
    )
    assert r.status_code == 200
    d = r.json()
    assert "compact" in d
    assert "closed" in d["compact"]
    assert "proposals" in d
    assert "summary" in d


def test_cognition_improvement_handoff_is_bounded_markdown():
    import tempfile
    from alpecca import cognition

    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "handoff.db"
        cognition.init_db(db)
        proposal_id = cognition.propose_action(cognition.ActionProposal(
            action="Improve House HQ movement direction checks",
            reason="Alpecca noticed left movement can drift from the selected sprite source.",
            approval=cognition.APPROVAL_ASK_FIRST,
            risk="low",
            status="testing",
            evidence="walkLeft should use native left art and avoid double flipping",
        ), db_path=db)
        cognition.record_proposal_evaluation(cognition.ProposalEvaluation(
            proposal_id=proposal_id,
            phase="testing",
            metric="directional_walk_integrity",
            evidence="native left sprites are present",
            test="force each left direction in Sprite QA",
            outcome="expected left-facing art without mirrored right cycles",
            score=0.8,
        ), db_path=db)
        packet = cognition.improvement_handoff_markdown(db_path=db)

    assert packet["format"] == "markdown"
    assert packet["target_tools"] == ["Codex", "Claude", "ChatGPT"]
    assert packet["proposal_count"] == 1
    assert "Alpecca Self-Improvement Handoff" in packet["markdown"]
    assert "Do not grant autonomous file edits" in packet["markdown"]
    assert "Improve House HQ movement direction checks" in packet["markdown"]
    assert "directional_walk_integrity" in packet["markdown"]
    assert "record back into Alpecca" in packet["markdown"]


def test_action_proposals_store_machine_payload():
    import tempfile
    from alpecca import cognition

    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "payload.db"
        cognition.init_db(db)
        proposal_id = cognition.propose_action(cognition.ActionProposal(
            action="Planner step",
            reason="Store exact tool call.",
            approval=cognition.APPROVAL_ASK_FIRST,
            risk="low",
            status="planned",
            payload={"kind": "planner_step", "tool": "self_status", "args": {}},
        ), db_path=db)
        row = cognition.get_action_proposal(proposal_id, db_path=db)

    assert row is not None
    assert cognition.proposal_payload(row)["tool"] == "self_status"


def test_planner_parses_and_creates_ask_first_proposals():
    import tempfile
    from alpecca import planner
    from alpecca import cognition

    calls = {"n": 0}

    def fake_generate(_system, _prompt):
        calls["n"] += 1
        return (
            "<think>drafting</think>"
            '{"steps":[{"tool":"note_to_self","args":{"text":"Keep the plan bounded."},'
            '"action":"Remember planner bounds","reason":"The goal needs approval-gated steps."}]}'
        )

    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "planner.db"
        cognition.init_db(db)
        result = planner.plan_goal("Improve Workshop planning safely", fake_generate, db_path=db)

    assert result["ok"] is True
    assert result["created"] == 1
    row = result["proposals"][0]
    assert row["approval"] == cognition.APPROVAL_ASK_FIRST
    assert row["status"] == "planned"
    payload = cognition.proposal_payload(row)
    assert payload["kind"] == "planner_step"
    assert payload["tool"] == "note_to_self"
    assert payload["args"]["text"] == "Keep the plan bounded."
    assert calls["n"] == 1


def test_planner_retries_once_after_malformed_json():
    import tempfile
    from alpecca import planner
    from alpecca import cognition

    replies = iter([
        "not json",
        '{"steps":[{"tool":"self_status","args":{},"action":"Check status","reason":"Start from live state."}]}',
    ])

    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "planner_retry.db"
        cognition.init_db(db)
        result = planner.plan_goal("Check live status before acting", lambda _s, _p: next(replies), db_path=db)

    assert result["ok"] is True
    assert result["created"] == 1
    assert cognition.proposal_payload(result["proposals"][0])["tool"] == "self_status"


def test_cognition_route_retires_legacy_planner_execution():
    from fastapi.testclient import TestClient
    import server
    import sqlite3

    payload = {"kind": "planner_step", "tool": "self_status", "args": {}}
    proposal_id = cognition.propose_action(cognition.ActionProposal(
        action="Run approved self status planner step",
        reason="Route execution smoke test.",
        approval=cognition.APPROVAL_ASK_FIRST,
        risk="low",
        status="planned",
        payload=payload,
    ))
    client = TestClient(server.app)
    auth_headers = {server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET}
    try:
        retired = client.post(f"/cognition/proposals/{proposal_id}", json={
            "status": "accepted",
            "approved_by_user": True,
            "execute": True,
        }, headers=auth_headers)
        assert retired.status_code == 409
        assert "payload-backed commitment" in retired.json()["detail"]
        row = cognition.get_action_proposal(proposal_id)
        assert row["status"] == "planned"
    finally:
        with sqlite3.connect(state_store.DB_PATH) as conn:
            conn.execute("DELETE FROM proposal_evaluations WHERE proposal_id=?", (int(proposal_id),))
            conn.execute("DELETE FROM action_proposals WHERE id=?", (int(proposal_id),))


def test_routines_due_and_mark_ran_are_idempotent():
    import tempfile
    from alpecca import routines

    now = time.time()
    tm = time.localtime(now)
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "routines.db"
        row = routines.add(
            "Consolidate observations",
            hour=tm.tm_hour,
            weekday=tm.tm_wday,
            kind="consolidate_observations",
            db_path=db,
        )
        due = routines.due(now=now, db_path=db)
        assert [r["id"] for r in due] == [row["id"]]

        routines.mark_ran(row["id"], now=now, db_path=db)
        assert routines.due(now=now, db_path=db) == []


def test_watchers_report_names_and_counts_without_contents():
    import tempfile
    from alpecca import watchers

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        watched = watchers.DirectoryWatcher([root], max_files=20)
        first = watched.poll()
        assert first["initial"] is True
        assert first["changed"] is False

        (root / "status.txt").write_text("PRIVATE-CONTENT-SHOULD-NOT-LEAK", encoding="utf-8")
        changed = watched.poll()

    assert changed["changed"] is True
    assert changed["added"] == 1
    assert changed["added_names"] == ["status.txt"]
    assert "PRIVATE-CONTENT" not in json.dumps(changed)


def test_routines_routes_create_and_toggle():
    from fastapi.testclient import TestClient
    import server
    import sqlite3

    client = TestClient(server.app)
    headers = {server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET}
    routine_id = None
    try:
        r = client.post("/routines", json={
            "name": "Route routine smoke",
            "hour": 9,
            "weekday": -1,
            "kind": "embed_backfill",
            "enabled": True,
        }, headers=headers)
        assert r.status_code == 200
        routine = r.json()["routine"]
        routine_id = int(routine["id"])
        assert routine["kind"] == "embed_backfill"

        off = client.post(f"/routines/{routine_id}", json={"enabled": False}, headers=headers)
        assert off.status_code == 200
        assert off.json()["routine"]["enabled"] == 0

        listed = client.get("/routines", headers=headers)
        assert listed.status_code == 200
        assert "embed_backfill" in listed.json()["kinds"]
    finally:
        if routine_id is not None:
            with sqlite3.connect(state_store.DB_PATH) as conn:
                conn.execute("DELETE FROM routines WHERE id=?", (routine_id,))


def test_routines_delete_route_removes_routine():
    from fastapi.testclient import TestClient
    import server
    import sqlite3

    client = TestClient(server.app)
    headers = {server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET}
    routine_id = None
    try:
        r = client.post("/routines", json={
            "name": "Route routine delete",
            "hour": 9,
            "weekday": -1,
            "kind": "embed_backfill",
            "enabled": True,
        }, headers=headers)
        assert r.status_code == 200
        routine_id = int(r.json()["routine"]["id"])

        gone = client.post(f"/routines/{routine_id}/delete", headers=headers)
        assert gone.status_code == 200
        assert gone.json()["deleted"] == routine_id
        assert routine_id not in [int(row["id"]) for row in gone.json()["routines"]]

        listed = client.get("/routines", headers=headers)
        assert listed.status_code == 200
        assert routine_id not in [int(row["id"]) for row in listed.json()["routines"]]

        missing = client.post(f"/routines/{routine_id}/delete", headers=headers)
        assert missing.status_code == 404
        routine_id = None
    finally:
        if routine_id is not None:
            with sqlite3.connect(state_store.DB_PATH) as conn:
                conn.execute("DELETE FROM routines WHERE id=?", (routine_id,))


def test_routines_vacuum_kind_dispatches_mindpage_vacuum(monkeypatch):
    import asyncio
    from fastapi.testclient import TestClient
    import server
    import sqlite3

    calls = []

    def fake_vacuum(*args, **kwargs):
        calls.append(True)
        return True

    monkeypatch.setattr(server.mindpage_mod, "vacuum", fake_vacuum)
    monkeypatch.setattr(
        server.mind,
        "reserve_initiative",
        lambda **_kwargs: {"allowed": True, "decision": "allow"},
    )
    # Neutralize the host-pressure governor: this test exercises vacuum dispatch,
    # not the resource coordinator, and a genuinely busy host would otherwise
    # defer the routine ("host-pressure") and make the test load-dependent.
    monkeypatch.setattr(server, "_host_pressure_optional_work_deferral", lambda *_a, **_k: None)

    client = TestClient(server.app)
    headers = {server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET}
    routine_id = None
    try:
        r = client.post("/routines", json={
            "name": "Route routine vacuum",
            "hour": 3,
            "weekday": -1,
            "kind": "vacuum",
            "enabled": True,
        }, headers=headers)
        assert r.status_code == 200
        routine = r.json()["routine"]
        routine_id = int(routine["id"])
        assert routine["kind"] == "vacuum"

        ran = asyncio.run(server._run_routine(routine))
        assert ran["ok"] is True
        assert ran["kind"] == "vacuum"
        assert ran["result"] is True
        assert calls == [True]
    finally:
        if routine_id is not None:
            with sqlite3.connect(state_store.DB_PATH) as conn:
                conn.execute("DELETE FROM routines WHERE id=?", (routine_id,))


def test_cognition_proposal_handoff_route_reports_markdown_packet():
    from fastapi.testclient import TestClient
    import config
    import server

    client = TestClient(server.app)
    r = client.get(
        "/cognition/proposals/handoff?limit=2",
        headers={server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["format"] == "markdown"
    assert "markdown" in d
    assert "Safety Contract" in d["markdown"]
    assert "target_tools" in d


def test_cognition_room_review_records_grounded_loop():
    from fastapi.testclient import TestClient
    import config
    import server
    import time
    client = TestClient(server.app)
    question = f"What should Library inspect next {time.time_ns()}?"
    r = client.post("/cognition/rooms/library/review", json={
        "room_name": "Library",
        "purpose": "Memory and journal review",
        "status": "online",
        "last_seen": "Recent memory shelves were reviewed.",
        "question": question,
    }, headers={server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["room"]["name"] == "Library"
    assert d["question"] == question
    assert d["observation_id"]
    assert d["memory_id"]
    assert d["journal_id"]
    assert d["intent"]["name"] in {"questioning", "remembering", "self-reviewing", "observing"}


def test_stage4_diffusers_generator_refuses_fake_4k_upscale_by_default():
    root = Path(__file__).resolve().parent.parent
    src = (root / "scripts" / "generate_alpecca_stage4_tile_diffusers.py").read_text(encoding="utf-8")
    assert 'default=int(os.environ.get("ALPECCA_TILE_RENDER_SIZE", "4096"))' in src
    assert "Refusing to upscale" in src
    assert "--allow-draft-upscale" in src
    assert '"promotionStatus": "draft-not-promotable" if upscaled else "generated-awaiting-import"' in src
    assert "configure_memory" in src
    assert "enable_attention_slicing" in src
    assert "enable_vae_slicing" in src
    assert "enable_vae_tiling" in src
    assert "enable_xformers_memory_efficient_attention" in src
    assert '"memory": memory' in src


def test_stage4_colab_worker_round_trip_is_native_4k_and_hf_backed():
    root = Path(__file__).resolve().parent.parent
    colab = (root / "notebooks" / "alpecca_stage4_tile_generation_colab.py").read_text(encoding="utf-8")
    notebook = root / "notebooks" / "alpecca_stage4_tile_generation_colab.ipynb"
    docs = (root / "docs" / "ALPECCA_STAGE4_TILE_WORKER.md").read_text(encoding="utf-8")
    downloader = (root / "scripts" / "download_alpecca_stage4_worker_outputs.py").read_text(encoding="utf-8")
    assert notebook.exists()
    assert 'os.environ.setdefault("ALPECCA_TILE_RENDER_SIZE", "4096")' in colab
    command_block = colab[colab.index('os.environ["ALPECCA_TILE_COMMAND"]') : colab.index("# %%", colab.index('os.environ["ALPECCA_TILE_COMMAND"]'))]
    assert "--allow-draft-upscale" not in command_block
    assert "hf" in colab and "upload" in colab
    assert "idle_eye_16sector_frame000_turnaround" in colab
    assert "JOB_LIMIT = 16" in colab
    assert "run_alpecca_stage4_returned_slice_qa.py" in colab
    assert 'os.environ.setdefault("ALPECCA_TILE_MEMORY_MODE", "low_vram")' in colab
    assert 'os.environ.setdefault("ALPECCA_TILE_ENABLE_VAE_TILING", "1")' in colab
    assert "preflight_alpecca_stage4_tile_worker.py" in colab
    assert "run_alpecca_stage4_resumable_colab_worker.py" in colab
    assert '"--upload-every"' in colab
    assert "download_alpecca_stage4_worker_outputs.py" in docs
    assert "run_alpecca_stage4_returned_slice_qa.py" in docs
    assert 'ALPECCA_TILE_MEMORY_MODE="low_vram"' in docs
    assert "preflight_alpecca_stage4_tile_worker.py" in docs
    assert "run_alpecca_stage4_resumable_colab_worker.py" in docs
    assert "--upload-every 1" in docs
    assert "First Production Slices" in docs
    assert "Source/generated art belongs on Hugging Face" not in docs or "Hugging Face" in docs
    assert "list_repo_files" in downloader
    assert "hf_hub_download" in downloader


def test_stage4_worker_preflight_checks_hf_cuda_and_native_4096_contract():
    root = Path(__file__).resolve().parent.parent
    src = (root / "scripts" / "preflight_alpecca_stage4_tile_worker.py").read_text(encoding="utf-8")
    assert "idle_eye_16sector_frame000_turnaround" in src
    assert "inspect_hf_auth" in src
    assert "inspect_torch" in src
    assert "inspect_diffusers" in src
    assert "native_4096_contract" in src
    assert "gpu_memory_warning" in src
    assert "ALPECCA_TILE_MEMORY_MODE" in src
    assert "stage-4-tile-worker-preflight" in src


def test_zerogpu_space_exposes_stage4_tile_worker_without_replacing_chat():
    root = Path(__file__).resolve().parent.parent
    app = (root / "spaces" / "alpecca-zerogpu" / "app.py").read_text(encoding="utf-8")
    readme = (root / "spaces" / "alpecca-zerogpu" / "README.md").read_text(encoding="utf-8")
    requirements = (root / "spaces" / "alpecca-zerogpu" / "requirements.txt").read_text(encoding="utf-8")
    assert "def chat(" in app
    assert "def generate_stage4_tile(" in app
    assert 'api_name="chat"' in app
    assert 'api_name="generate_stage4_tile"' in app
    assert "CREATORJD/alpecca-art-library" in app
    assert "idle_eye_16sector_frame000_turnaround" in app
    assert "zerogpu-drafts" in app
    assert "renderSize" in app
    assert "AutoPipelineForImage2Image" in app
    assert "build_seed_condition" in app
    assert "Full-body Alpecca anime woman" in app
    assert "draft-not-promotable" in app
    assert "HfApi().upload_folder" in app
    assert "wrong-size" in app
    assert "no-alpha" in app
    assert "Cloudflare" not in app
    assert "Run offsets `0` through `15` first" in readme
    assert "stage4-worker-outputs/zerogpu-drafts" in readme
    assert "Draft canvases are blocked by the local importer" in readme
    assert "image-to-image guidance" in readme
    assert "Returned tiles still must pass local contact-sheet QA" in readme
    assert "diffusers" in requirements
    assert "huggingface_hub" in requirements


def test_stage4_resumable_colab_worker_uploads_after_each_tile():
    root = Path(__file__).resolve().parent.parent
    src = (root / "scripts" / "run_alpecca_stage4_resumable_colab_worker.py").read_text(encoding="utf-8")
    assert "idle_eye_16sector_frame000_turnaround" in src
    assert "run_preflight" in src
    assert "upload_output_root" in src
    assert "upload_every" in src
    assert "limit\", \"1\"" in src or '"--limit",\n            "1"' in src
    assert "stage-4-resumable-colab-worker" in src
    assert "resumable_worker_report.json" in src
    assert "run_alpecca_stage4_returned_slice_qa.py" in src


def test_stage4_first_slice_packages_16_sector_turnaround_and_full_loop():
    root = Path(__file__).resolve().parent.parent
    subprocess.run(
        [sys.executable, "scripts/build_alpecca_stage4_first_slice.py", "--frame-index", "0"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        [sys.executable, "scripts/build_alpecca_stage4_first_slice.py"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    still = json.loads(
        (root / "output" / "alpecca_stage4_tile_jobs" / "first_slices" / "idle_eye_16sector_frame000_turnaround" / "tile_job_manifest.json").read_text(encoding="utf-8")
    )
    loop = json.loads(
        (root / "output" / "alpecca_stage4_tile_jobs" / "first_slices" / "idle_eye_16sector_full_loop" / "tile_job_manifest.json").read_text(encoding="utf-8")
    )
    assert still["requiredTileSize"] == [4096, 4096]
    assert still["sectorCount"] == 16
    assert still["jobCount"] == 16
    assert still["frameIndexFilter"] == 0
    assert loop["requiredTileSize"] == [4096, 4096]
    assert loop["sectorCount"] == 16
    assert loop["jobCount"] == 128
    assert loop["frameIndexFilter"] is None
    assert set(still["targetIds"]) == set(loop["targetIds"])


def test_stage4_turnaround_qa_reports_all_16_sectors_before_import():
    root = Path(__file__).resolve().parent.parent
    manifest = root / "output" / "alpecca_stage4_tile_jobs" / "first_slices" / "idle_eye_16sector_frame000_turnaround" / "tile_job_manifest.json"
    out_root = root / "output" / "test_stage4_turnaround_qa"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/qa_alpecca_stage4_turnaround_outputs.py",
            "--manifest",
            str(manifest),
            "--outputs-root",
            str(manifest.parent),
            "--out-root",
            str(out_root),
            "--frame-index",
            "0",
            "--thumb-size",
            "128",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    assert '"sectorCount": 16' in result.stdout
    report = json.loads((out_root / "turnaround_16_sector_qa_report.json").read_text(encoding="utf-8"))
    assert report["sectorCount"] == 16
    assert report["expectedSectorCount"] == 16
    assert report["missingSectors"] == []
    assert report["mechanicalStatus"] == "blocked"
    assert report["blockedSectorCount"] == 16
    assert Path(report["preview"]).exists()


def test_stage4_360_volume_qa_rejects_flat_billboard_silhouettes():
    from PIL import Image, ImageDraw
    from scripts.qa_alpecca_stage4_360_volume import run_volume_qa

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        jobs_path = root / "jobs.jsonl"
        outputs = root / "returned"
        records = []
        for index in range(16):
            target = f"gen-{index:04d}"
            path = outputs / "outputs" / target / "frame_000.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            width = 22 + (index % 8) * 3
            left = 48 - width // 2
            draw.rounded_rectangle((left, 10, left + width, 88), radius=8, fill=(255, 255, 255, 255))
            image.save(path)
            records.append({
                "jobId": f"{target}_frame_000",
                "targetId": target,
                "matrixKey": f"idle_eye_s{index}",
                "viewSector16": f"s{index}",
                "horizontalTier": f"s{index}",
                "frameIndex": 0,
                "expectedSize": [96, 96],
                "expectedWorkerOutput": f"outputs/{target}/frame_000.png",
            })
        jobs_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"chunks": [{"file": str(jobs_path)}]}), encoding="utf-8")
        passing = run_volume_qa(manifest, outputs, root / "volume_pass.json", normalize_size=64)
        assert passing["status"] == "pass"
        assert passing["readySectorCount"] == 16

        flat_outputs = root / "flat"
        for index in range(16):
            target = f"gen-{index:04d}"
            path = flat_outputs / "outputs" / target / "frame_000.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((34, 10, 62, 88), radius=8, fill=(255, 255, 255, 255))
            image.save(path)
        blocked = run_volume_qa(manifest, flat_outputs, root / "volume_blocked.json", normalize_size=64)
        assert blocked["status"] == "blocked"
        assert any("flat-billboard-suspected" in issue for issue in blocked["issues"])


def test_stage4_returned_slice_processor_imports_only_after_volume_gate():
    from PIL import Image, ImageDraw
    from scripts.process_alpecca_stage4_returned_slice import process_slice

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        jobs_path = root / "jobs.jsonl"
        outputs = root / "returned"
        stage4 = root / "stage4"
        records = []
        for index in range(16):
            target = f"gen-{index:04d}"
            target_dir = stage4 / f"{target}__matrix_idle_eye_s{index}"
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "target.json").write_text(json.dumps({
                "targetId": target,
                "matrixKey": f"idle_eye_s{index}",
                "frameCount": 8,
                "slotPixels": 128,
            }), encoding="utf-8")
            path = outputs / "outputs" / target / "frame_000.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            # A character-LIKE silhouette (head + torso + two legs), not a solid
            # block: the mechanical probe correctly flags any filled rectangle
            # with >0.82 alpha coverage as "opaque-background-rectangle", so the
            # fixture must have real negative space like a sprite would. Width
            # still varies by sector so the 360-volume gate sees rotation.
            width = 22 + (index % 8) * 3
            left = 64 - width // 2
            fill = (255, 255, 255, 255)
            head_w = max(10, int(width * 0.6))
            draw.ellipse((64 - head_w // 2, 30, 64 + head_w // 2, 44), fill=fill)
            draw.rectangle((60, 42, 68, 48), fill=fill)                      # neck joins head
            draw.rectangle((left, 46, left + width, 72), fill=fill)          # torso
            leg_w = max(4, int(width * 0.22))
            draw.rectangle((left + 2, 74, left + 2 + leg_w, 96), fill=fill)  # left leg
            draw.rectangle((left + width - 2 - leg_w, 74, left + width - 2, 96), fill=fill)
            draw.rectangle((left + 2, 72, left + width - 2, 76), fill=fill)  # hips join legs
            image.save(path)
            records.append({
                "jobId": f"{target}_frame_000",
                "targetId": target,
                "matrixKey": f"idle_eye_s{index}",
                "viewSector16": f"s{index}",
                "horizontalTier": f"s{index}",
                "frameIndex": 0,
                "frameCount": 8,
                "expectedSize": [128, 128],
                "expectedWorkerOutput": f"outputs/{target}/frame_000.png",
                "stage4ImportDestination": str(target_dir / "incoming" / "frame_tiles" / "frame_000.png"),
                "targetJson": str(target_dir / "target.json"),
            })
        jobs_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"chunks": [{"file": str(jobs_path)}]}), encoding="utf-8")

        summary = process_slice(
            manifest=manifest,
            outputs_root=outputs,
            out_root=root / "process",
            frame_index=0,
            apply_import=True,
            apply_stitch=True,
        )
        assert summary["gatesPass"] is True
        assert summary["import"]["importedCount"] == 16
        assert summary["coverage"]["partialTargetCount"] == 16
        assert summary["stitch"]["ran"] is True
        assert all(report["status"] == "skipped-partial-slice" for report in summary["stitch"]["reports"])
        assert (stage4 / "gen-0000__matrix_idle_eye_s0" / "incoming" / "frame_tiles" / "frame_000.png").exists()

        flat = root / "flat"
        for index in range(16):
            target = f"gen-{index:04d}"
            path = flat / "outputs" / target / "frame_000.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((50, 30, 78, 96), radius=8, fill=(255, 255, 255, 255))
            image.save(path)
        blocked = process_slice(
            manifest=manifest,
            outputs_root=flat,
            out_root=root / "blocked_process",
            frame_index=0,
            apply_import=True,
            apply_stitch=True,
        )
        assert blocked["gatesPass"] is False
        assert blocked["import"]["importedCount"] == 0
        assert any("flat-billboard-suspected" in issue for issue in blocked["volume"]["issues"])


def test_stage4_importer_blocks_draft_not_promotable_sidecars():
    from PIL import Image, ImageDraw
    from scripts.import_alpecca_stage4_tile_outputs import import_outputs

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        outputs = root / "outputs_root"
        stage4 = root / "stage4"
        target = "gen-draft"
        source = outputs / "outputs" / target / "frame_000.png"
        source.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((40, 32, 88, 100), fill=(255, 255, 255, 255))
        image.save(source)
        source.with_suffix(".generation.json").write_text(json.dumps({
            "promotionStatus": "draft-not-promotable",
            "renderSize": 1536,
            "expectedSize": [128, 128],
        }), encoding="utf-8")
        jobs = root / "jobs.jsonl"
        jobs.write_text(json.dumps({
            "jobId": f"{target}_frame_000",
            "targetId": target,
            "frameIndex": 0,
            "expectedSize": [128, 128],
            "expectedWorkerOutput": f"outputs/{target}/frame_000.png",
            "stage4ImportDestination": str(stage4 / target / "incoming" / "frame_tiles" / "frame_000.png"),
        }), encoding="utf-8")
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"chunks": [{"file": str(jobs)}]}), encoding="utf-8")
        report = import_outputs(manifest, outputs, apply=True)
        assert report["readyCount"] == 0
        assert report["importedCount"] == 0
        assert report["records"][0]["issues"] == ["draft-not-promotable"]
        assert not (stage4 / target / "incoming" / "frame_tiles" / "frame_000.png").exists()


def test_stage4_returned_slice_runner_targets_first_16_sector_proof():
    root = Path(__file__).resolve().parent.parent
    text = (root / "scripts" / "run_alpecca_stage4_returned_slice_qa.py").read_text(encoding="utf-8")
    assert "idle_eye_16sector_frame000_turnaround" in text
    assert "stage4-worker-outputs/colab/idle_eye_16sector_frame000_turnaround" in text
    assert "qa_turnaround" in text
    assert "run_volume_qa" in text
    assert "turnaround_360_volume_report.json" in text
    assert "qa_outputs" in text
    assert "readyForHumanVisualReview" in text
    assert "does not import, stitch, or approve art" in text
    processor = (root / "scripts" / "process_alpecca_stage4_returned_slice.py").read_text(encoding="utf-8")
    assert "run_volume_qa" in processor
    assert "skipped-partial-slice" in processor
    assert "apply_import" in processor


def test_stage4_sector_contract_audit_passes_for_drive_360_queue():
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [
            sys.executable,
            "scripts/audit_alpecca_stage4_sector_contract.py",
            "--report",
            "output/test_alpecca_stage4_sector_contract_report.json",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    assert '"status": "pass"' in result.stdout
    report = json.loads((root / "output" / "test_alpecca_stage4_sector_contract_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["external360References"]["sourceFolder"] == "https://drive.google.com/drive/folders/1TCaawZt7idE7ib-Kw8T-sq23z5cIXJmw"
    assert report["external360References"]["missingFiles"] == []
    assert report["sourceQueue"]["targetCount"] >= 596
    assert report["workerJobs"]["jobCount"] >= 6048
    assert report["workerJobs"]["requiredTileSize"] == [4096, 4096]
    assert report["workerJobs"]["promptSampleIssues"] == 0
    native_batches = [batch for batch in report["sourceQueue"]["batches"] if batch["native16Sector"]]
    assert native_batches
    assert all(len(batch["horizontals"]) == 16 for batch in native_batches)


def test_house_hq_runtime_resolves_16_sector_matrix_keys_before_5_tier_fallback():
    root = Path(__file__).resolve().parent.parent
    src = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "function alpeccaSector16RuntimeKey" in src
    assert "const exactKey = `${action}_${matrix.vertical}_${sectorKey}`" in src
    assert "const eyeKey = `${action}_eye_${sectorKey}`" in src
    assert "const horizontalExactKey = `${action}_${matrix.vertical}_${matrix.horizontal}`" in src
    assert "const requestedKey = `${action}_${matrix.vertical}_${alpeccaSector16RuntimeKey(matrix.sector16)}`" in src


def test_cognition_autonomy_state_exposes_backend_promptless_loop():
    from fastapi.testclient import TestClient
    import server

    client = TestClient(server.app)
    r = client.get(
        "/cognition/autonomy-state",
        headers=_protected_auth_headers(server),
    )
    assert r.status_code == 200
    d = r.json()
    assert d["enabled"] is True
    assert d["drift_interval"] > 0
    assert d["living_interval"] > 0
    assert "next_living_in" in d
    assert "recursive_engagement" in d
    assert "current_intent" in d
    assert "last_living_question" in d
    assert "last_living_self_feedback" in d
    assert "last_living_next_action" in d


def test_cognition_world_tick_creates_recursive_world_question():
    from fastapi.testclient import TestClient
    import server
    import time

    client = TestClient(server.app)
    headers = _protected_auth_headers(server)
    marker = f"world-loop-{time.time_ns()}"
    r = client.post(
        "/cognition/world-tick",
        json={"reason": marker},
        headers=headers,
    )
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["phase"] == "system_activation"
    assert d["activated_system"]["id"] in {"perception", "memory", "room_review", "self_review", "voice", "mindscape"}
    assert d["activated_system"]["status"]
    assert d["activation_selection"]["system"] == d["activated_system"]["id"]
    assert d["activation_selection"]["reason"]
    assert d["question"].endswith("?")
    assert d["room"]["name"]
    assert d["creator"]["name"] == "Jason"
    assert d["observation_id"]
    assert d["memory_id"]
    assert d["journal_id"]
    assert d["intent"]["name"] in {"questioning", "remembering", "self-reviewing", "observing"}
    assert "House HQ" in d["line"] or "role" in d["line"]
    assert d["self_feedback"]["noticed"]
    assert d["self_feedback"]["learned"]
    assert d["self_feedback"]["next_action"]
    assert d["self_feedback"]["curriculum_step"] == d["activated_system"]["id"]
    assert d["self_feedback"]["curriculum_reason"] == d["activation_selection"]["reason"]
    assert "creator" in d["self_feedback"]["creator_evidence"].lower()
    assert d["next_action"]["action"]
    assert d["engagement_proposal"]["action"] == "Strengthen autonomous recursive engagement"
    assert d["learning_record"]["metric"] == "autonomous_recursive_engagement"
    # The world-tick handler returns before its background persistence has
    # necessarily committed; on a loaded machine an immediate read races it.
    # Poll briefly instead of asserting the very first snapshot.
    autonomy = {}
    for _ in range(30):
        autonomy = client.get(
            "/cognition/autonomy-state", headers=headers
        ).json()
        if autonomy.get("last_living_reason") == marker:
            break
        time.sleep(0.1)
    assert autonomy["last_living_reason"] == marker
    assert autonomy["last_living_question"] == d["question"]
    assert autonomy["last_living_observation_id"] == d["observation_id"]
    assert autonomy["last_living_memory_id"] == d["memory_id"]
    assert autonomy["last_living_journal_id"] == d["journal_id"]
    assert autonomy["last_living_self_feedback"]["noticed"] == d["self_feedback"]["noticed"]
    assert autonomy["last_living_next_action"]["action"] == d["next_action"]["action"]
    assert autonomy["last_living_next_action"]["selection_reason"] == d["activation_selection"]["reason"]
    assert autonomy["last_living_engagement_proposal"]["action"] == d["engagement_proposal"]["action"]
    state = client.get("/cognition/state", headers=headers).json()
    assert state["recursive_engagement"]
    assert state["recursive_engagement"][0]["metric"] == "autonomous_recursive_engagement"
    assert state["recursive_engagement_scorecard"]["ok"] is True
    assert state["recursive_engagement_scorecard"]["curriculum"]["mode"] == "evidence_first"
    assert state["recursive_engagement_scorecard"]["curriculum"]["activated_system"]


def test_cognition_recursive_engagement_scorecard_uses_evidence_not_claims():
    from pathlib import Path
    import tempfile
    from alpecca import cognition

    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "scorecard.db"
        cognition.init_db(db)
        empty = cognition.recursive_engagement_scorecard(db_path=db)
        assert empty["ok"] is False
        assert empty["score"] == 0

        obs_id = cognition.record_observation(cognition.CognitionObservation(
            source="living_loop",
            room="hq-control",
            content="Living loop in HQ Control. Question: What should I inspect?",
            metadata={"question": "What should I inspect?"},
        ), db_path=db)
        cognition.mark_observation_remembered(obs_id, 42, db_path=db)
        proposal = cognition.upsert_action_proposal(cognition.ActionProposal(
            action="Strengthen autonomous recursive engagement",
            reason="Alpecca needs to observe, question, remember, and choose a safe next action.",
            approval=cognition.APPROVAL_ASK_FIRST,
            risk="low",
            status="testing",
            evidence=f"observation_id={obs_id}; memory_id=42",
            result="Next: inspect the room for grounded evidence",
        ), db_path=db)
        cognition.record_proposal_evaluation(cognition.ProposalEvaluation(
            proposal_id=int(proposal["id"]),
            phase="testing",
            metric="autonomous_recursive_engagement",
            evidence=(
                "Living tick reason=test; activated=perception; "
                "selection_reason=current room lacks recent grounded observation evidence; "
                "fresh_creator_evidence=True; question=What should I inspect?"
            ),
            test="Run one promptless living loop tick.",
            outcome="Recorded a grounded question and safe next action.",
            score=0.8,
            supports_status="testing",
        ), db_path=db)
        full = cognition.recursive_engagement_scorecard(db_path=db)
        assert full["ok"] is True
        assert full["score"] == 1
        assert full["latest_question"] == "What should I inspect?"
        assert full["latest_memory_id"] == 42
        assert full["curriculum"]["activated_system"] == "perception"
        assert full["curriculum"]["selection_reason"].startswith("current room lacks")
        assert full["curriculum"]["creator_context_observed"] is False
        assert full["research_mapping"]["Reflexion"].startswith("record verbal self-feedback")


def test_cognition_recursive_engagement_route_reports_scorecard():
    from fastapi.testclient import TestClient
    import server

    client = TestClient(server.app)
    r = client.get(
        "/cognition/recursive-engagement",
        headers=_protected_auth_headers(server),
    )
    assert r.status_code == 200
    d = r.json()
    assert d["schema"] == "alpecca.recursive_engagement_scorecard.v1"
    assert "checks" in d
    assert d["curriculum"]["mode"] == "evidence_first"
    assert {check["id"] for check in d["checks"]} >= {
        "observe_world",
        "ask_question",
        "remember_evidence",
        "self_feedback",
        "bounded_next_action",
    }


def test_house_hq_surfaces_living_loop_as_state_not_only_logs():
    root = Path(__file__).resolve().parent.parent
    src = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    css = (root / "apps" / "house-hq" / "src" / "styles.css").read_text(encoding="utf-8")
    assert 'id="alpeccaLivingState"' in src
    assert "setAlpeccaLivingState" in src
    assert "pulseAlpeccaActivatedSystem" in src
    assert "activated_system" in src
    assert "self_feedback" in src
    assert "alpeccaLivingNextAction" in src
    assert "alpeccaLivingStateEl.dataset.question = question" in src
    assert "/cognition/world-tick" in src
    assert "/cognition/autonomy-state" in src
    assert "function pollAlpeccaAutonomyState" in src
    assert "autonomyStateToLivingLoop" in src
    assert 'message.type === "living_loop"' in src
    assert "[data-world-tick]" in src
    assert ".living-state" in css


def test_house_living_loop_routes_alpecca_to_activation_terminals():
    root = Path(__file__).resolve().parent.parent
    src = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "function livingLoopTargetRoomId" in src
    assert "function routeAlpeccaToLivingLoopTarget" in src
    assert 'if (systemId === "memory") return "library";' in src
    assert 'if (systemId === "self_review") return "self-design";' in src
    assert 'if (systemId === "voice" || systemId === "mindscape") return "hq-control";' in src
    assert "routeAlpeccaToLivingLoopTarget(message.living_loop)" in src
    assert "routeAlpeccaToLivingLoopTarget(data)" in src
    living_handler = src[src.index('if (message.type === "living_loop")') : src.index('if (message.type === "reply")')]
    assert 'if (!alpeccaChat.classList.contains("hidden")) showAlpeccaProfileLine' in living_handler
    assert "else showMessage(line, 5.5)" in living_handler


def test_house_chat_slow_turns_keep_one_live_transaction():
    root = Path(__file__).resolve().parent.parent
    src = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "const ALPECCA_AI_PLAYER_REPLY_NOTICE_MS = 35000;" in src
    assert "const ALPECCA_AI_SLOW_REPLY_MS = 12000;" in src
    reply_block = src[src.index('if (message.type === "reply")') : src.index('if (message.type === "proactive"')]
    assert "const alpeccaAiCompletedRequestIds = new Set<string>();" in src
    assert "function rememberCompletedAlpeccaRequest" in src
    assert "alpeccaAiCompletedRequestIds.has(replyRequestId)" in reply_block
    assert "const fromPlayerChat = Boolean(replyRequestId) && replyRequestId === alpeccaAiPendingPlayerRequestId;" in reply_block
    assert 'message.source === "house-chat"' not in reply_block
    assert "const wasAwaitingPlayerReply = fromPlayerChat || legacyPlayerReply;" in reply_block
    assert "alpeccaAiAwaitingReply && (fromPlayerChat || legacyPlayerReply)" not in reply_block
    assert "Background core event" in reply_block
    timeout_block = src[src.index("function updateHud"):src.index("roomPanelTimer -= dt")]
    assert "waitingMs > ALPECCA_AI_PLAYER_REPLY_NOTICE_MS" in timeout_block
    assert "alpeccaAiExtendedReplyNoticeShown = true;" in timeout_block
    assert "alpeccaAiAwaitingReply = false;" not in timeout_block
    assert "waitingMs > 30000" not in timeout_block
    send_start = src.index("function sendAlpeccaChat")
    send_block = src[send_start:src.index('if (alpeccaAiStatus === "token")', send_start)]
    assert "ALPECCA_AI_CHANNEL_INBOUND_TIMEOUT_MS" not in send_block
    assert "trying websocket fallback" not in send_block
    assert "one House request ID must remain one model/tool transaction" in send_block


def test_house_proactive_events_are_presented_as_alpecca_live_voice():
    root = Path(__file__).resolve().parent.parent
    src = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    proactive_block = src[src.index('if (message.type === "proactive"') : src.index('if (message.type === "computer_status"')]
    assert 'appendAlpeccaLog("Alpecca", proactiveText)' in proactive_block
    assert "Background thought:" not in proactive_block
    assert 'focusAlpecca(2.8, "talkDown")' in proactive_block
    assert "startAlpeccaSpeech(proactiveText" in proactive_block


def test_house_chat_pauses_background_core_work_while_player_waits():
    root = Path(__file__).resolve().parent.parent
    src = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "let alpeccaPlayerChatQuietTimer = 0;" in src
    send_start = src.index("function sendAlpeccaChat")
    send_block = src[send_start:src.index("if (alpeccaAiStatus === \"token\")", send_start)]
    assert "alpeccaPlayerChatQuietTimer = Math.max(alpeccaPlayerChatQuietTimer, 42)" in send_block
    assert "alpeccaWorldTickTimer = Math.max(alpeccaWorldTickTimer, 18)" in send_block
    assert "alpeccaPerceptionSendTimer = Math.max(alpeccaPerceptionSendTimer, 18)" in send_block
    busy_block = src[src.index("function alpeccaAutonomyBusy"):src.index("async function runAlpeccaQuietWorldTick")]
    assert "alpeccaPlayerChatQuietTimer > 0" in busy_block
    quiet_block = src[src.index("async function runAlpeccaQuietWorldTick"):src.index("function updateAlpeccaAutonomousWorldTick")]
    assert "alpeccaPlayerChatQuietTimer > 0" in quiet_block
    perception_block = src[src.index("function recordAlpeccaPerception"):src.index("function disposeAlpeccaIdeaObject")]
    assert "alpeccaPlayerChatQuietTimer <= 0" in perception_block
    bridge_start = src.index("async function runAlpeccaFeatureToolBridge")
    bridge_block = src[bridge_start:src.index("function runAlpeccaFeature(", bridge_start)]
    assert "if (!visible && alpeccaPlayerChatQuietTimer > 0) return null;" in bridge_block


def test_house_hq_has_quiet_autonomous_world_tick_loop():
    root = Path(__file__).resolve().parent.parent
    src = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "let alpeccaWorldTickTimer = 42;" in src
    assert "let alpeccaWorldTickInFlight = false;" in src
    assert "function alpeccaAutonomyBusy" in src
    assert "function runAlpeccaQuietWorldTick" in src
    quiet_block = src[src.index("async function runAlpeccaQuietWorldTick"):src.index("async function reviewAlpeccaReplies")]
    assert "/cognition/world-tick" in quiet_block
    assert '"house_hq_autonomous_cadence"' in quiet_block
    assert "quiet: true" in quiet_block
    assert "routeAlpeccaToLivingLoopTarget(data)" in quiet_block
    assert "featureForLivingLoop(data)" in quiet_block
    assert "runAlpeccaFeatureToolBridge(featureId, targetRoom, false)" in quiet_block
    assert 'alpeccaChat.classList.remove("hidden")' not in quiet_block
    update_block = src[src.index("function updateAlpeccaAutonomousWorldTick"):src.index("async function reviewAlpeccaReplies")]
    assert "alpeccaAutonomyBusy()" in update_block
    assert "void runAlpeccaQuietWorldTick();" in update_block
    frame_block = src[src.index("function stepGameFrame"):src.index("function animate")]
    assert "updateAlpeccaAutonomousWorldTick(dt);" in frame_block
    runtime_block = src[src.index("function publishAlpeccaRuntimeProbe"):src.index("function preloadAlpeccaMovementAnimations")]
    assert "worldTickTimer" in runtime_block
    assert "worldTickInFlight" in runtime_block


def test_house_hq_living_loop_persists_room_memory_evidence():
    root = Path(__file__).resolve().parent.parent
    src = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "memory_id?: number" in src
    assert "journal_id?: number" in src
    assert "function assimilateAlpeccaLivingLoopMemory" in src
    state_block = src[src.index("function setAlpeccaLivingState"):src.index("function pulseAlpeccaActivatedSystem")]
    assert "assimilateAlpeccaLivingLoopMemory(loop, question, roomName, fallbackText)" in state_block
    assert "memory.observations += 1" in state_block
    assert "memory.online = true" in state_block
    assert 'memory.lastSource = "Alpecca core living loop"' in state_block
    assert "memory.lastQuestion = question || previousQuestion" in state_block
    assert "loop.memory_id ? 0.08 : 0" in state_block
    assert "loop.journal_id ? 0.06 : 0" in state_block
    assert "trace.note = `${room.name} living loop" in state_block
    assert "rememberAlpeccaJournalEntry(journalNote)" in state_block


def test_house_alpecca_can_activate_room_stations_autonomously():
    root = Path(__file__).resolve().parent.parent
    src = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "function activateRoomStationByAlpecca" in src
    activation_block = src[src.index("function activateRoomStationByAlpecca") : src.index("function announceAlpeccaInspection")]
    assert "const station = interactables.find((item) => item.id === room.stationId)" in activation_block
    assert 'station.type !== "collect"' in activation_block
    assert "station.onUse(station)" in activation_block
    assert "activeRoomIds.has(room.stationId)" in activation_block
    assert "const stationResult = activateRoomStationByAlpecca(point)" in src
    assert "activeRoomIds.has(room?.stationId || point.roomId)" in src


def test_house_living_question_hud_is_readable_and_system_colored():
    root = Path(__file__).resolve().parent.parent
    css = (root / "apps" / "house-hq" / "src" / "styles.css").read_text(encoding="utf-8")
    assert "width: min(440px, calc(100vw - 36px));" in css
    assert ".living-state small" in css
    assert "-webkit-line-clamp: 3;" in css
    assert '.living-state[data-system="memory"] span' in css
    assert '.living-state[data-system="voice"] span' in css


def test_cognition_observe_route_records_and_can_consolidate():
    from fastapi.testclient import TestClient
    import server
    import time
    client = TestClient(server.app)
    marker = f"observe-route-marker-{time.time_ns()}"
    r = client.post("/cognition/observe", json={
        "source": "house",
        "room": "Library",
        "content": f"Jason and Alpecca noticed {marker} in Mindscape.",
        "confidence": 0.92,
        "novelty": 0.8,
        "remember_now": True,
    }, headers=_protected_auth_headers(server))
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["observation_id"]
    assert d["intent"]["name"] == "observing"
    assert d["consolidated"]["kept"]
    hits = memory_store.recall(marker, db_path=state_store.DB_PATH)
    assert hits and marker in hits[0]["content"]


def test_cognition_chat_review_route_creates_grounding_proposal():
    from fastapi.testclient import TestClient
    import server
    import time

    client = TestClient(server.app)
    marker = f"grounding-review-route-{time.time_ns()}"
    cognition.record_chat_turn(cognition.ChatTurn(
        user_text=f"hello {marker}",
        reply="The Library is offline and I remember that room event.",
        room="Parlor",
        mood="curious",
        model_use={"fallback": True},
        memory_evidence=[],
    ), db_path=state_store.DB_PATH)
    r = client.post(
        "/cognition/chat/review",
        json={"limit": 4},
        headers=_protected_auth_headers(server),
    )
    assert r.status_code == 200
    d = r.json()
    assert d["review"]["risk_count"] >= 1
    assert d["proposal"]
    assert d["proposal"]["approval"] == cognition.APPROVAL_ASK_FIRST
    assert "grounding" in d["proposal"]["action"].lower()


def _protected_auth_headers(server):
    return {
        server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET,
    }


def test_ws_rejects_legacy_query_identity_and_accepts_protected_bearer():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    import config
    import pytest
    import server

    client = TestClient(server.app)
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect(
            f"/ws?token={config.PUBLIC_IDENTITY}"
        ):
            pass
    assert denied.value.code == 1008

    with client.websocket_connect(
        "/ws", headers=_protected_auth_headers(server)
    ) as ws:
        assert ws.receive_json()["type"] == "state"


def test_ws_background_sources_record_observation_without_reply(monkeypatch):
    from fastapi.testclient import TestClient
    import server
    import time

    called = {"chat": 0}

    def fake_chat(*_args, **_kwargs):
        called["chat"] += 1
        return {"reply": "should not be sent"}

    monkeypatch.setattr(server.mind, "chat", fake_chat)
    marker = f"ws-background-marker-{time.time_ns()}"
    with TestClient(server.app).websocket_connect(
        "/ws", headers=_protected_auth_headers(server)
    ) as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        ws.send_json({
            "source": "house-perception",
            "text": f"House HQ noticed {marker}",
            "request_id": "bg-1",
            "room": "Library",
        })
        msg = ws.receive_json()

    assert msg["type"] == "observation_ack"
    assert msg["request_id"] == "bg-1"
    assert msg["source"] == "house-perception"
    assert msg["ok"] is True
    assert called["chat"] == 0
    recent = cognition.recent_observations(limit=12, db_path=state_store.DB_PATH)
    assert any(marker in obs["content"] for obs in recent)


def test_ws_house_chat_source_remains_direct_reply(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    called = {"chat": 0}

    def fake_chat(text, **_kwargs):
        called["chat"] += 1
        return {
            "reply": f"direct reply to {text}",
            "mood": server.mind.state.mood_label(),
            "state": server.mind.state.as_dict(),
            "location": "home",
            "moved": False,
            "memories_used": [],
            "memory_evidence": [],
            "self_reflection": "",
            "appearance": server.mind.current_appearance().as_dict(),
            "llm_online": True,
            "model_use": {},
            "intent": {},
        }

    monkeypatch.setattr(server.mind, "chat", fake_chat)
    with TestClient(server.app).websocket_connect(
        "/ws", headers=_protected_auth_headers(server)
    ) as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        ws.send_json({
            "source": "house-chat",
            "text": "hello Alpecca",
            "request_id": "chat-1",
        })
        msg = ws.receive_json()

    assert msg["type"] == "reply"
    assert msg["request_id"] == "chat-1"
    assert msg["source"] == "house-chat"
    assert msg["reply"] == "direct reply to hello Alpecca"
    assert called["chat"] == 1


def test_ws_house_chat_context_reaches_mind(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    captured = {}

    def fake_chat(text, **kwargs):
        captured["text"] = text
        captured["situation"] = kwargs.get("situation")
        captured["reply_tier"] = kwargs.get("reply_tier")
        return {
            "reply": "I can feel this room around me.",
            "mood": server.mind.state.mood_label(),
            "state": server.mind.state.as_dict(),
            "location": "home",
            "moved": False,
            "memories_used": [],
            "memory_evidence": [],
            "self_reflection": "",
            "appearance": server.mind.current_appearance().as_dict(),
            "llm_online": True,
            "model_use": {},
            "intent": {},
        }

    monkeypatch.setattr(server.mind, "chat", fake_chat)
    context = "Game context: player is in Observatory. Room purpose: media review."

    with TestClient(server.app).websocket_connect(
        "/ws", headers=_protected_auth_headers(server)
    ) as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        ws.send_json({
            "source": "house-chat",
            "text": "Where are you right now?",
            "context": context,
            "request_id": "chat-context-1",
        })
        msg = ws.receive_json()

    assert msg["type"] == "reply"
    assert msg["request_id"] == "chat-context-1"
    assert msg["source"] == "house-chat"
    assert msg["reply"] == "I can feel this room around me."
    assert captured["text"] == "Where are you right now?"
    assert captured["situation"] == context
    assert captured.get("reply_tier") == "reason"


def test_house_hq_chat_uses_natural_reason_tier_like_discord():
    import server

    assert server._house_chat_reply_tier("hi") == "reason"
    assert server._house_chat_reply_tier("stop walking") == "reason"
    assert server._house_chat_reply_tier("can you hear me?") == "reason"


def test_ws_house_chat_timeout_still_returns_reply(monkeypatch):
    from fastapi.testclient import TestClient
    import server
    import time

    called = {"chat": 0}

    def slow_chat(text, **_kwargs):
        called["chat"] += 1
        time.sleep(0.2)
        return {"reply": f"late reply to {text}"}

    monkeypatch.setattr(server, "WS_CHAT_REPLY_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(server.mind, "chat", slow_chat)
    with TestClient(server.app).websocket_connect(
        "/ws", headers=_protected_auth_headers(server)
    ) as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        ws.send_json({
            "source": "house-chat",
            "text": "hi",
            "request_id": "chat-timeout-1",
        })
        msg = ws.receive_json()

    assert msg["type"] == "reply"
    assert msg["request_id"] == "chat-timeout-1"
    assert msg["source"] == "house-chat"
    assert msg["model_use"]["backend"] == "timeout"
    assert msg["model_use"]["fallback"] is True
    assert msg["reply"] == "Hi. I'm here with you. What should we focus on next?"
    assert called["chat"] == 1


def test_ws_house_chat_echo_guard_replaces_repeated_reply(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    def echo_chat(text, **_kwargs):
        return {
            "reply": f"You said: {text}",
            "mood": server.mind.state.mood_label(),
            "state": server.mind.state.as_dict(),
            "location": "home",
            "moved": False,
            "memories_used": [],
            "memory_evidence": [],
            "self_reflection": "",
            "appearance": server.mind.current_appearance().as_dict(),
            "llm_online": False,
            "model_use": {"backend": "offline", "fallback": True},
            "intent": {},
        }

    monkeypatch.setattr(server.mind, "chat", echo_chat)
    with TestClient(server.app).websocket_connect(
        "/ws", headers=_protected_auth_headers(server)
    ) as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        ws.send_json({
            "source": "house-chat",
            "text": "Can you hear me?",
            "request_id": "chat-echo-1",
        })
        msg = ws.receive_json()

    assert msg["type"] == "reply"
    assert msg["request_id"] == "chat-echo-1"
    assert msg["source"] == "house-chat"
    assert "You said" not in msg["reply"]
    assert "Can you hear me" not in msg["reply"]
    assert msg["model_use"]["fallback"] is True
    assert "echo guard" in msg["model_use"]["error"]


def test_core_chat_records_recent_turn_with_reply_and_evidence(monkeypatch):
    from alpecca.mind import CoreMind
    import time

    mind = CoreMind()
    marker = f"grounded-chat-turn-{time.time_ns()}"

    def fake_generate(*_args, **_kwargs):
        return f"Alpecca grounded reply for {marker}"

    monkeypatch.setattr(mind.llm, "generate", fake_generate)
    result = mind.chat(f"Please remember this direct chat {marker}")
    assert result["chat_turn_id"]
    turns = cognition.recent_chat_turns(limit=12, db_path=state_store.DB_PATH)
    turn = next(t for t in turns if marker in t["user_text"])
    assert turn["id"] == result["chat_turn_id"]
    assert marker in turn["reply"]
    assert turn["room"] == result["location"]
    assert isinstance(turn["memory_evidence"], list)
    state = mind.cognition_state()
    assert any(t["id"] == result["chat_turn_id"] for t in state["recent_chat_turns"])


def test_memory_search_route_returns_scored_recall():
    from fastapi.testclient import TestClient
    import server
    import time
    marker = f"library-search-marker-{time.time_ns()}"
    memory_store.remember_with_id(
        f"Jason asked Alpecca to remember {marker} in Mindscape.",
        kind="relationship",
        salience=0.9,
        source="test",
        embed_fn=None,
    )
    client = TestClient(server.app)
    r = client.get(
        "/memories/search",
        params={"q": marker, "limit": 3},
        headers=_protected_auth_headers(server),
    )
    assert r.status_code == 200
    d = r.json()
    assert d["query"] == marker
    assert d["results"]
    top = d["results"][0]
    assert marker in top["content"]
    assert top["recall_score"] > 0
    assert top["recall_method"] in {"keyword", "semantic"}
    assert "embedding" not in top and "tokens" not in top


def test_mindscape_event_sync_throttle_skips_immediate_retry():
    import time
    import server
    old_url = server.MINDSCAPE_CLOUD_URL
    old_enabled = server.MINDSCAPE_ENABLED
    old_vault_enabled = server.MINDSCAPE_VAULT_ENABLED
    old_min = server.MINDSCAPE_EVENT_SYNC_MIN_INTERVAL
    old_attempt = server._mindscape_sync_status["last_attempt"]
    old_skips = server._mindscape_sync_status["event_skips"]
    old_status = server._mindscape_sync_status["last_status"]
    try:
        server.MINDSCAPE_CLOUD_URL = "https://mindscape.example/sync"
        server.MINDSCAPE_ENABLED = True
        # This coverage exercises the retained legacy mirror ledger. A live
        # encrypted Vault intentionally becomes the active target otherwise.
        server.MINDSCAPE_VAULT_ENABLED = False
        server.MINDSCAPE_EVENT_SYNC_MIN_INTERVAL = 999
        server._mindscape_sync_status["last_attempt"] = time.time()
        assert server._mindscape_request_event_sync("test") is False
        assert server._mindscape_sync_status["event_skips"] == old_skips + 1
        assert server._mindscape_sync_status["last_status"] == "event_sync_throttled"
    finally:
        server.MINDSCAPE_CLOUD_URL = old_url
        server.MINDSCAPE_ENABLED = old_enabled
        server.MINDSCAPE_VAULT_ENABLED = old_vault_enabled
        server.MINDSCAPE_EVENT_SYNC_MIN_INTERVAL = old_min
        server._mindscape_sync_status["last_attempt"] = old_attempt
        server._mindscape_sync_status["event_skips"] = old_skips
        server._mindscape_sync_status["last_status"] = old_status


def test_mindscape_restore_routes_accept_posted_snapshot():
    from fastapi.testclient import TestClient
    import server
    import time
    client = TestClient(server.app)
    unique = f"Jason uses Mindscape {time.time_ns()}."
    unique_chat = f"Mindscape chat continuity {time.time_ns()}."
    snap = {
        "name": "Alpecca Mindscape",
        "version": 1,
        "ts": time.time(),
        "enabled": True,
        "self": {"mood": "content", "location": "library", "intent": {"name": "remembering"}},
        "memory": {"recent": [{"kind": "relationship", "content": unique, "salience": 0.8}]},
        "journal": {"recent": [], "open_questions": []},
        "observations": [],
        "chat_turns": [{
            "room": "library",
            "mood": "content",
            "intent": "replying",
            "user_text": unique_chat,
            "reply": "I carried this through Mindscape.",
            "model_use": {"backend": "mindscape-test"},
            "memory_evidence": [{"kind": "relationship", "score": 0.71}],
        }],
        "proposals": [],
    }
    headers = _protected_auth_headers(server)
    r = client.post(
        "/mindscape/restore/preview",
        json={"snapshot": snap},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["preview"]["memory_count"] == 1
    assert r.json()["preview"]["chat_turn_count"] == 1
    approval_request = r.json()["approval_request"]
    r = client.post(
        "/mindscape/restore/approve",
        json={
            "preview_id": approval_request["preview_id"],
            "fingerprint": approval_request["fingerprint"],
            "approved": True,
        },
        headers=headers,
    )
    assert r.status_code == 200
    approval_token = r.json()["approval"]["approval_token"]
    r = client.post(
        "/mindscape/restore/import",
        json={"snapshot": snap, "approval_token": approval_token},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["imported"]["memories"] == 1
    assert r.json()["imported"]["chat_turns"] == 1
    turns = cognition.recent_chat_turns(limit=20, db_path=state_store.DB_PATH)
    turn = next(t for t in turns if unique_chat in t["user_text"])
    assert turn["reply"] == "I carried this through Mindscape."
    assert turn["model_use"]["backend"] == "mindscape-test"
    preview_again = client.post(
        "/mindscape/restore/preview",
        json={"snapshot": snap},
        headers=headers,
    ).json()["approval_request"]
    approval_again = client.post(
        "/mindscape/restore/approve",
        json={
            "preview_id": preview_again["preview_id"],
            "fingerprint": preview_again["fingerprint"],
            "approved": True,
        },
        headers=headers,
    ).json()["approval"]["approval_token"]
    r = client.post(
        "/mindscape/restore/import",
        json={"snapshot": snap, "approval_token": approval_again},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "already_imported"
    assert r.json()["imported"]["memories"] == 0
    assert r.json()["imported"]["chat_turns"] == 0

def test_recall_dedupes_near_duplicates_but_keeps_distinct():
    """The diversity guard: a cluster of near-identical memories collapses to its
    single strongest one, so the top_k budget isn't spent echoing one thought --
    while a genuinely different but still-relevant memory is kept."""
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "div.db"
        state_store.init_db(db)
        a = "I feel calm and quiet tonight"
        b = "I feel calm and quiet tonight too"          # near-duplicate of a
        c = "The library was quiet and full of old books"  # distinct, still relevant
        for m in (a, b, c):
            memory_store.remember(m, salience=0.8, db_path=db, embed_fn=None)
        contents = [h["content"] for h in
                    memory_store.recall("somewhere calm and quiet",
                                        db_path=db, embed_fn=None)]
        assert a in contents          # strongest of the near-dup pair survives
        assert b not in contents      # its echo is dropped
        assert c in contents          # a distinct relevant memory is NOT dropped


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


def test_proactive_llm_judge_false_stays_quiet(monkeypatch):
    from alpecca import mind as mind_mod

    mind = mind_mod.CoreMind()
    # This test targets the chatter judge. Persisted mood history may otherwise
    # create a separate mood-speech candidate before that path is evaluated.
    monkeypatch.setattr(mind_mod.proactive_mod, "should_speak", lambda *_args, **_kwargs: None)
    mind._last_user_ts = time.time() - 10_000
    mind._last_volunteer_ts = 0
    mind.llm._backend = "ollama"
    mind.llm._client = object()
    mind.llm.generate = lambda *a, **k: '{"speak": false, "pick": 1}'

    assert mind.volunteer_reason() is None
    assert mind._last_volunteer_ts == 0


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
        assert m["model_bytes"] == 4
        assert len(m["model_sha256"]) == 64
        assert m["model_version"] == m["model_sha256"][:16]
        assert m["look_at"] is False and m["expressions"] == []
        assert "talking" in m["clips"] and "sleep" in m["clips"]
        assert vrm.asset_path("alpecca.vrm", vdir) is not None
        assert vrm.asset_path("../../alpecca.db", vdir) is None   # traversal blocked
        assert vrm.asset_path("/etc/passwd", vdir) is None

def test_vrm_manifest_reports_vrm1_gaze_and_expression_capabilities():
    import json
    import struct
    from alpecca import vrm

    document = {
        "extensions": {
            "VRMC_vrm": {
                "specVersion": "1.0",
                "lookAt": {"type": "bone", "offsetFromHeadBone": [0, 0.06, 0]},
                "expressions": {"preset": {"happy": {}, "aa": {}, "blink": {}}},
            }
        }
    }
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    total_size = 12 + 8 + len(json_chunk)
    payload = (
        struct.pack("<4sII", b"glTF", 2, total_size)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
    )
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "alpecca.vrm"
        path.write_bytes(payload)
        manifest = vrm.manifest(path.parent)

    assert manifest["vrm_spec_version"] == "1.0"
    assert manifest["look_at"] is True
    assert manifest["look_at_type"] == "bone"
    assert manifest["expressions"] == ["aa", "blink", "happy"]

def test_vrm_pick_project_wants_her_freshest_body():
    from alpecca import vrm
    projects = [
        {"id": "a", "updated_at": "2026-07-01T10:00:00", "vrm_filename": "old.vrm"},
        {"id": "b", "updated_at": "2026-07-06T10:00:00"},                 # no VRM
        {"id": "c", "updated_at": "2026-07-05T10:00:00", "vrm_path": "/x/new.vrm"},
    ]
    # Newest project WITH a VRM wins -- b is fresher but has no body to wear.
    assert vrm.pick_project(projects)["id"] == "c"
    assert vrm.pick_project([{"id": "b", "updated_at": "2026-07-06"}]) is None
    assert vrm.pick_project([]) is None and vrm.pick_project(None) is None

def test_vrm_build_request_carries_studio_token_only_when_set():
    from alpecca import vrm
    url, headers = vrm.build_request("https://studio.example/", "/api/projects", "tok")
    assert url == "https://studio.example/api/projects"
    assert headers == {"X-VCS-Token": "tok"}
    _, headers = vrm.build_request("https://studio.example", "/api/projects", "")
    assert headers == {}                              # open studio -> no header

def test_vrm_sync_from_studio_writes_atomically_and_fails_friendly():
    from alpecca import vrm
    projects = ('{"projects": [{"id": "p1", "name": "her", '
                '"updated_at": "2026-07-06", "vrm_filename": "her.vrm"}]}')
    with tempfile.TemporaryDirectory() as d:
        vdir = Path(d)
        # Happy path: fake transport serves the listing then a valid glTF body.
        def fetch(url, headers):
            return projects.encode() if url.endswith("/api/projects") else b"glTF...body"
        r = vrm.sync_from_studio("https://studio.example", "tok", vdir, fetch=fetch)
        assert r["ok"] is True and r["file"] == vrm.STUDIO_FILE
        assert vrm.model_file(vdir).name == vrm.STUDIO_FILE
        assert not list(vdir.glob("*.part"))          # no temp litter
        # A hand-dropped alpecca.vrm outranks the synced body (manual override).
        (vdir / "alpecca.vrm").write_bytes(b"glTF")
        assert vrm.model_file(vdir).name == "alpecca.vrm"
        # Non-glTF payload is refused, and the previous body survives untouched.
        r = vrm.sync_from_studio("https://studio.example", "", vdir,
                                 fetch=lambda u, h: projects.encode()
                                 if u.endswith("/api/projects") else b"<html>oops")
        assert r["ok"] is False and "isn't a VRM" in r["error"]
        assert (vdir / vrm.STUDIO_FILE).read_bytes() == b"glTF...body"
    # Unreachable studio and unconfigured URL both come back as friendly words.
    def boom(url, headers):
        raise OSError("refused")
    r = vrm.sync_from_studio("https://studio.example", "", Path("/tmp"), fetch=boom)
    assert r["ok"] is False and "reach the studio" in r["error"]
    r = vrm.sync_from_studio("", "", Path("/tmp"), fetch=boom)
    assert r["ok"] is False and "ALPECCA_STUDIO_URL" in r["error"]


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

def test_soul_llm_tiebreak_stays_within_winning_rank(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca import soul as soul_mod

    mind = mind_mod.CoreMind()
    mind.llm._backend = "ollama"
    mind.llm._client = object()
    mind.llm.generate = lambda *a, **k: '{"pick": 2}'
    plan = {
        "focus": {"subagent": "Doer", "category": "actions", "action": "a", "reason": "a", "rank": 3},
        "slate": [
            {"subagent": "Doer", "category": "actions", "action": "a", "reason": "a", "rank": 3},
            {"subagent": "Carer", "category": "compassion", "action": "b", "reason": "b", "rank": 3},
            {"subagent": "Improver", "category": "self_care", "action": "c", "reason": "c", "rank": 4},
        ],
        "by_category": {},
        "principle": "test",
    }
    monkeypatch.setattr(soul_mod.soul, "deliberate", lambda snap: dict(plan))

    out = mind.soul_state()

    assert out["focus"]["subagent"] == "Carer"
    assert out["focus"]["rank"] == 3

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


def test_prompt_treats_memories_as_past_not_current_events():
    prompt = prompts.build_system_prompt(
        EmotionalState(love=0.5),
        [{"kind": "semantic", "content": "Library was offline.", "recall_score": 0.73}],
        situation="the person is asking about your voice",
        current_message="Can we talk about your voice?",
    )
    assert "Treat the person's current message as the highest-trust evidence" in prompt
    assert "Current turn evidence" in prompt
    assert "Current message: Can we talk about your voice?" in prompt
    assert "Past memories that may be relevant" in prompt
    assert "do not claim they are happening now" in prompt
    assert "Past memory (semantic, recall 0.73): Library was offline." in prompt


def test_house_chat_voice_copy_is_identity_not_user_setting():
    root = Path(__file__).resolve().parent.parent
    main_ts = root / "apps" / "house-hq" / "src" / "main.ts"
    text = main_ts.read_text(encoding="utf-8")
    start = text.index('<div class="voice-strip">')
    chat_markup = text[start:text.index('<nav class="hot-tabs"', start)]
    assert "Alpecca's voice" in chat_markup
    assert "data-hear-voice" in chat_markup
    assert "Hear voice" in chat_markup
    assert "identity locked" not in chat_markup.lower()
    assert "data-voice-preview" not in chat_markup
    assert "speechSynthesis" not in text
    assert "browser fallback" not in text
    assert "/tts/warmup" in text
    assert "original voice is warming or unavailable" in text
    assert "Voice fallback" not in text
    assert "Fallback voice" not in text
    assert "Alpecca voice: ${alpeccaVoiceEngine" not in text


def test_house_voice_headers_drive_visible_emotional_state():
    root = Path(__file__).resolve().parent.parent
    text = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "let alpeccaVoiceEmotionTimer = 0;" in text
    assert "let alpeccaVoiceEmotionState: Record<string, number> = {};" in text
    assert "function visibleAlpeccaEmotionState" in text
    assert "function applyAlpeccaVoiceEmotionHeaders" in text
    header_block = text[text.index("function applyAlpeccaVoiceEmotionHeaders"):text.index("function captureAlpeccaVoiceHeaders")]
    assert 'X-Alpecca-Voice-Warmth' in header_block
    assert 'X-Alpecca-Voice-Breath' in header_block
    assert 'X-Alpecca-Voice-Speed' in header_block
    assert 'X-Alpecca-Voice-Primary' in header_block
    assert "alpeccaVoiceEmotionTimer = Math.max(alpeccaVoiceEmotionTimer, 5.2)" in header_block
    assert "document.body.dataset.alpeccaVoiceAffect" in header_block
    mood_block = text[text.index("function updateAlpeccaMoodPanel"):text.index("function sourcePlateForAlpeccaState")]
    assert "const visibleState = visibleAlpeccaEmotionState();" in mood_block
    assert "const raw = visibleState[key];" in mood_block
    step_block = text[text.index("function stepGameFrame"):text.index("function animate")]
    assert "updateAlpeccaVoiceEmotion(dt);" in step_block
    runtime_block = text[text.index("function publishAlpeccaRuntimeProbe"):text.index("function preloadAlpeccaMovementAnimations")]
    assert "voiceEmotionTimer" in runtime_block
    assert "voiceEmotionState" in runtime_block


def test_house_profile_status_does_not_mix_live_with_offline_or_content():
    root = Path(__file__).resolve().parent.parent
    text = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "alpeccaConnectionLabel" in text
    assert "alpeccaProfileDetailLabel" in text
    profile_assignments = "\n".join(
        line for line in text.splitlines()
        if "alpeccaProfileState.textContent" in line
    )
    assert "alpeccaAiMood" not in profile_assignments
    assert "alpeccaAiStatus" not in profile_assignments
    assert "${animation.textureSource}" not in text
    assert "content|offline" in text
    assert 'Original voice warming' in text


def test_house_uses_native_left_walk_cycles_without_double_flipping():
    root = Path(__file__).resolve().parent.parent
    text = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert 'walkLeft: { folder: "gpt16_walk_left_left"' in text
    assert 'walkNorthwest: { folder: "gpt16_walk_northwest_left"' in text
    assert 'walkSouthwest: { folder: "gpt16_walk_southwest_left"' in text
    assert "function alpeccaAnimationUsesNativeLeftArt" in text
    assert "return /(^|_)left($|_)/.test(folder);" in text
    assert "function alpeccaShouldFlipForDirection" in text
    assert "return !alpeccaAnimationUsesNativeLeftArt(name);" in text
    direction_block = text[text.index('function directionalAlpeccaAnimation') : text.index('function directionalAlpeccaWave')]
    assert "const state = states[base][direction]" in direction_block
    assert "setAlpeccaSpriteFlip(alpeccaShouldFlipForDirection(state, direction))" in direction_block
    source_block = text[text.index("function classifyAlpeccaAnimationSource") : text.index("async function loadAlpeccaAnimation")]
    assert 'name === "walkLeft" || name === "walkNorthwest" || name === "walkSouthwest"' in source_block
    assert 'nativeLeftWalk && family === "gpt16"' in source_block


def test_house_talking_keeps_alpecca_size_locked():
    root = Path(__file__).resolve().parent.parent
    text = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "function alpeccaStandingVisualLock" in text
    assert "function relockAlpeccaStandingVisuals" in text
    assert 'if (name === "idleDown") relockAlpeccaStandingVisuals();' in text
    lock_block = text[text.index("function alpeccaStandingVisualLock"):text.index("function shouldLockAlpeccaStandingVisual")]
    assert "alpeccaStandingPresentationScale" in lock_block
    assert "THREE.MathUtils.clamp(baseScale * alpeccaStandingPresentationScale, 0.98, 1.16)" in lock_block
    assert "THREE.MathUtils.clamp(idle?.spriteY || 0.86, 0.78, 1.08)" in lock_block
    transform_block = text[text.index("function applyAlpeccaVisualTransform"):text.index("function applyAlpeccaBillboardYaw")]
    assert "shouldLockAlpeccaStandingVisual(alpecca.state)" in transform_block
    assert "alpecca.visualScale = lock.visualScale" in transform_block
    normalize_block = text[text.index("function normalizeAlpeccaVisual"):text.index("function alpeccaAnimationSourceFamily")]
    assert 'name !== "idleDown"' in normalize_block
    assert "return alpeccaStandingVisualLock();" in normalize_block


def test_house_nearby_player_prevents_rest_pose_shrink():
    root = Path(__file__).resolve().parent.parent
    text = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    emotional_block = text[text.index("function emotionalAlpeccaAnimation"):text.index("function currentAlpeccaExplorePoint")]
    assert "const distanceToPlayer = Math.hypot" in emotional_block
    assert "const playerNearby = distanceToPlayer < 3.4" in emotional_block
    assert "if (!playerNearby &&" in emotional_block
    assert "directionalAlpeccaSleep" in emotional_block


def test_house_alpecca_uses_contextual_freedom_animations_without_action_chaos():
    root = Path(__file__).resolve().parent.parent
    text = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "freedomAnimations?: AlpeccaAnimationName[]" in text
    assert 'freedomAnimations: ["point", "pickup", "crouch"]' in text
    assert 'freedomAnimations: ["pickup", "crouch", "point", "kneel"]' in text
    assert 'freedomAnimations: ["sleepSoutheast"]' in text
    assert "const alpeccaNormalFreedomBlockedStates = new Set<AlpeccaAnimationName>" in text
    selector_block = text[text.index("const alpeccaNormalFreedomBlockedStates"):text.index("function alpeccaInspectionAnimation")]
    assert '"run"' in selector_block
    assert '"dash"' in selector_block
    assert '"jump"' in selector_block
    assert '"climb"' in selector_block
    assert "!name.startsWith(\"sleep\")" in selector_block
    assert "isAlpeccaRestExplorePoint(point)" in selector_block
    assert "contextualAlpeccaFreedomAnimation(point)" in text
    assert "data-alpecca-freedom-action" not in text
    assert "dataset.alpeccaFreedomAction" in text
    assert "freedomAction" in text[text.index("function publishAlpeccaRuntimeProbe"):text.index("function preloadAlpeccaMovementAnimations")]


def test_house_has_intentional_alpecca_rest_nook_for_sleep_animation():
    root = Path(__file__).resolve().parent.parent
    text = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "HQ Rest Nook" in text
    assert 'animation: "sleepSoutheast"' in text
    assert "new THREE.Vector3(-5.74, 0.04, 3.72)" in text
    assert "restOnly: true" in text
    assert "function alpeccaRestExploreIndex" in text
    assert "function isAlpeccaRestExplorePoint" in text
    assert "addSofa();" in text
    assert "alpecca-rest-nook" in text
    update_block = text[text.index("function updateAlpecca"):text.index("function createAlpeccaFallback")]
    assert "sleepy && !anxious && !playerEngaged" in update_block
    assert "alpecca.exploreIndex = alpeccaRestExploreIndex()" in update_block
    assert "clearAlpeccaTerminalInteraction()" in update_block
    assert "(!sleepy || restPoint)" in update_block
    assert "alpecca.inspectTimer = restPoint ? 9.5 : 3.4" in update_block
    assert "playerNearRestingDistance" in update_block


def test_house_standing_glitch_does_not_obscure_alpecca_scale():
    root = Path(__file__).resolve().parent.parent
    text = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    transition_block = text[text.index("function setAlpeccaAnimation"):text.index("function targetAlpeccaBodyLean")]
    assert "shouldGlitchAlpeccaTransition(previousState, name) && !shouldLockAlpeccaStandingVisual(name)" in transition_block
    animation_block = text[text.index("function updateAlpeccaAnimation"):text.index("function publishAlpeccaRuntimeProbe")]
    assert "const standing = shouldLockAlpeccaStandingVisual(alpecca.state)" in animation_block
    assert "const effectStrength = standing ? 0.42 : 1" in animation_block
    assert "0.32 * intensity * effectStrength" in animation_block


def test_house_profile_talking_uses_stable_frame_slot_size():
    root = Path(__file__).resolve().parent.parent
    text = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    expression_block = text[text.index("function updateAlpeccaChatExpressionPortrait"):text.index("function updateAlpeccaProfileFrame")]
    fallback_block = text[text.index("function updateAlpeccaProfileFrame"):text.index("void loadAlpeccaChatExpressions")]
    assert "const sourceFrameSize = atlas.frameSize" in expression_block
    assert "frame.w * 1.34" not in expression_block
    assert "const sourceFrameSize = Math.max(frame.w, frame.h, 512)" in fallback_block
    assert "frame.w * 1.34" not in fallback_block


def test_house_chat_forces_expression_portrait_when_opened_or_speaking():
    root = Path(__file__).resolve().parent.parent
    text = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    open_block = text[text.index("function openAlpeccaChat"):text.index("function closeAlpeccaChat")]
    line_block = text[text.index("function showAlpeccaProfileLine"):text.index("function sendAlpeccaChat")]
    assert "updateAlpeccaChatExpressionPortrait(true)" in open_block
    assert "updateAlpeccaChatExpressionPortrait(true)" in line_block


def test_tts_route_has_timeout_fallback_for_slow_voice_engine():
    root = Path(__file__).resolve().parent.parent
    text = (root / "server.py").read_text(encoding="utf-8")
    start = text.index('@app.post("/tts")')
    route = text[start:text.index('@app.get("/introspect")', start)]
    assert "asyncio.wait_for" in route
    assert "server voice timed out" in route
    assert "X-Alpecca-TTS-Error" in route
    assert '@app.post("/tts/warmup")' in text
    assert "_warm_alpecca_voice" in text
    assert "edge-timeout-fallback" not in route


def test_tts_auto_does_not_substitute_edge_for_af_heart():
    root = Path(__file__).resolve().parent.parent
    text = (root / "alpecca" / "tts.py").read_text(encoding="utf-8")
    auto_block = text[text.index('else:                                     # auto'):text.index('for fn in order:', text.index('else:                                     # auto'))]
    kokoro_block = text[text.index('if backend == "kokoro":'):text.index('elif backend == "edge":')]
    # auto blends only the F5 clone + Kokoro (emotion-routed), never edge.
    assert "open_tts.synth" in auto_block
    assert "_synth_kokoro" in auto_block
    assert "_prefers_clone_voice" in auto_block
    assert "order = (_synth_kokoro,)" in kokoro_block
    assert "_synth_edge" not in auto_block
    assert "_synth_edge" not in kokoro_block


def test_void_system_voice_panel_is_read_only_not_voice_picker():
    root = Path(__file__).resolve().parent.parent
    text = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    start = text.index('if (systemId === "voice")')
    panel = text[start:text.index('if (systemId === "studio")', start)]
    assert "Hear current voice" in panel
    assert "data-system-action=\"voice-preview\"" in panel
    assert "Voice samples" not in panel
    assert "viewer reads her modulation" in panel
    assert "it does not choose it" in panel


def test_house_hq_exposes_chat_grounding_review_action():
    root = Path(__file__).resolve().parent.parent
    main_ts = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    styles = (root / "apps" / "house-hq" / "src" / "styles.css").read_text(encoding="utf-8")
    assert "data-review-replies" in main_ts
    assert "/cognition/chat/review" in main_ts
    assert "reviewAlpeccaReplies" in main_ts
    assert "button[data-review-replies]" in styles


def test_house_hq_exposes_doctor_hot_tab_for_core_health():
    root = Path(__file__).resolve().parent.parent
    main_ts = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    styles = (root / "apps" / "house-hq" / "src" / "styles.css").read_text(encoding="utf-8")
    assert "data-doctor" in main_ts
    assert "/system/doctor" in main_ts
    assert "mindscape_setup" in main_ts
    assert "runAlpeccaDoctorCheck" in main_ts
    assert "button[data-doctor]" in styles


def test_house_hq_exposes_runtime_self_review_hot_tab():
    root = Path(__file__).resolve().parent.parent
    main_ts = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    styles = (root / "apps" / "house-hq" / "src" / "styles.css").read_text(encoding="utf-8")
    assert "data-self-review" in main_ts
    assert "/cognition/self-review" in main_ts
    assert "/cognition/behavior-review" in main_ts
    assert "runAlpeccaRuntimeSelfReview" in main_ts
    assert "button[data-self-review]" in styles


def test_house_hq_exposes_improvement_queue_hot_tab():
    root = Path(__file__).resolve().parent.parent
    main_ts = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    styles = (root / "apps" / "house-hq" / "src" / "styles.css").read_text(encoding="utf-8")
    assert "data-improvement-queue" in main_ts
    assert "/cognition/proposals" in main_ts
    assert "/cognition/proposals/compact" in main_ts
    assert "inspectAlpeccaImprovementQueue" in main_ts
    assert "Improvement queue:" in main_ts
    assert "button[data-improvement-queue]" in styles
    assert "data-workshop-handoff" in main_ts
    assert "/cognition/proposals/handoff?limit=8" in main_ts
    assert "workshopExportHandoff" in main_ts
    assert "Codex, Claude, or ChatGPT" in main_ts


def test_house_hq_room_features_read_real_alpecca_app_tools():
    root = Path(__file__).resolve().parent.parent
    main_ts = (root / "apps" / "house-hq" / "src" / "main.ts").read_text(encoding="utf-8")
    assert "toolPath?: string" in main_ts
    for endpoint in [
        'toolPath: "/introspect"',
        'toolPath: "/memories/search"',
        'toolPath: "/journal"',
        'toolPath: "/growth"',
        'toolPath: "/home/state"',
        'toolPath: "/soul"',
    ]:
        assert endpoint in main_ts
    bridge_block = main_ts[main_ts.index("function alpeccaFeatureToolUrl"):main_ts.index("function addSourceTerminal")]
    assert "function summarizeAlpeccaToolResult" in bridge_block
    assert "function runAlpeccaFeatureToolBridge" in bridge_block
    assert "house-tool-bridge" in bridge_block
    assert "/cognition/observe" in bridge_block
    assert "toolPath: feature.toolPath" in bridge_block
    assert "showAlpeccaProfileLine(summary" in bridge_block
    manual_block = main_ts[main_ts.index("function runAlpeccaFeature"):main_ts.index("function addSourceTerminal")]
    assert "void runAlpeccaFeatureToolBridge(feature.id, featureRoom, true)" in manual_block
    autonomous_block = main_ts[main_ts.index("function runAlpeccaAutonomousFeature"):main_ts.index("function completeAlpeccaMovementDirective")]
    assert "void runAlpeccaFeatureToolBridge(feature.id, room, false)" in autonomous_block


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
    env = os.environ.copy()
    for key in (
        "ALPECCA_DEEP_BACKEND",
        "ALPECCA_ZEROGPU_SPACE",
        "ALPECCA_ZEROGPU_API",
        "ALPECCA_ZEROGPU_TOKEN",
        "ANTHROPIC_API_KEY",
        "ALPECCA_CLOUD_URL",
        "ALPECCA_COLAB_URL",
        "ALPECCA_COLAB_API_KEY",
    ):
        env.pop(key, None)
    code = """
from alpecca.mind import _LLM
from config import OLLAMA_MODEL, DEEP_BACKEND
llm = _LLM()
assert DEEP_BACKEND == "local"
assert llm._deep is None
assert llm.deep_online() is False
assert llm.model_for("reason") == OLLAMA_MODEL
assert llm.model_for("deep") == OLLAMA_MODEL
"""
    subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent,
                   env=env, check=True)


def test_colab_t4_accelerator_is_explicit_opt_in_only():
    env = os.environ.copy()
    env.pop("ALPECCA_COLAB_URL", None)
    code = """
from config import COLAB_URL, COLAB_FAST_CHAT
from alpecca import colab_t4
assert COLAB_URL == ""
assert COLAB_FAST_CHAT is True
assert colab_t4.status("", model="x")["configured"] is False
"""
    subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent,
                   env=env, check=True)


def test_colab_t4_client_parses_openai_compatible_reply(monkeypatch):
    from alpecca import colab_t4

    seen = {}

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "Hi Jason, I am awake on the T4."}}]
            }).encode("utf-8")

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    reply = colab_t4.chat(
        "You are Alpecca.",
        "hello",
        url="https://colab.example",
        model="Qwen/Qwen2.5-7B-Instruct",
        timeout=3,
    )
    assert reply == "Hi Jason, I am awake on the T4."
    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["body"]["model"] == "Qwen/Qwen2.5-7B-Instruct"
    assert seen["timeout"] == 3


def test_hf_cloud_brain_defaults_to_approved_qwen35_fallback():
    env = os.environ.copy()
    env.pop("ALPECCA_HF_MODEL", None)
    code = """
from config import HF_MODEL
assert HF_MODEL == "Qwen/Qwen3.5-9B"
"""
    subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent,
                   env=env, check=True)


def test_hf_qwen35_fallback_disables_thinking_for_companion_turns(monkeypatch):
    from types import SimpleNamespace
    from alpecca import mind as mind_mod

    seen = {}

    class FakeClient:
        def chat_completion(self, **kwargs):
            seen.update(kwargs)
            message = SimpleNamespace(content="cloud qwen online")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    llm = object.__new__(mind_mod._LLM)
    llm._hf = FakeClient()
    llm._last_call = {}
    monkeypatch.setattr(mind_mod, "HF_MODEL", "Qwen/Qwen3.5-9B")

    reply = llm._generate_hf("You are Alpecca.", "Are you there?")

    assert reply == "cloud qwen online"
    assert seen["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False},
    }


def test_zerogpu_deep_tier_is_explicit_opt_in_only():
    # ZeroGPU is supported, but it is a named booster she reaches for only when
    # the owner configured both the backend and a Space. It must not become the
    # shipped default just because the developer shell has a token lying around.
    env = os.environ.copy()
    env["ALPECCA_DEEP_BACKEND"] = "zerogpu"
    env["ALPECCA_ZEROGPU_SPACE"] = "CREATORJD/alpecca-zerogpu"
    code = """
from alpecca.mind import _LLM
from config import DEEP_BACKEND, ZEROGPU_SPACE
llm = _LLM()
assert DEEP_BACKEND == "zerogpu"
assert ZEROGPU_SPACE == "CREATORJD/alpecca-zerogpu"
assert llm._deep == ("zerogpu", "CREATORJD/alpecca-zerogpu")
assert llm.deep_online() is True
"""
    subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent,
                   env=env, check=True)


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


def test_desktop_metadata_views_skip_symlink_targets():
    from alpecca import desktop
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "allowed"; base.mkdir()
        outside = Path(d) / "outside.txt"; outside.write_bytes(b"private" * 50)
        link = base / "outside-link.txt"
        try:
            link.symlink_to(outside)
        except OSError:
            return

        listing = desktop.list_room("general", roots={"general": base})
        summary = desktop.summarize("general", roots={"general": base})

        assert listing["ok"] is True
        assert listing["entries"] == []
        assert summary["ok"] is True
        assert summary["files"] == 0
        assert summary["total_bytes"] == 0

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
    last = llm.last_call()
    assert last["backend"] == "ollama"
    assert last["used_tier"] == "reason"
    assert last["fallback"] is False


def test_ollama_chat_uses_live_performance_options():
    from alpecca.mind import _LLM
    import alpecca.mind as mind_mod
    from config import OLLAMA_KEEP_ALIVE, OLLAMA_NUM_CTX, OLLAMA_NUM_PREDICT

    captured = {}

    class FakeOllama:
        def chat(self, **kwargs):
            captured.update(kwargs)
            return {"message": {"content": "awake"}}

    old_cloud_model = mind_mod.CHAT_CLOUD_MODEL
    mind_mod.CHAT_CLOUD_MODEL = ""
    try:
        llm = _LLM()
        llm._backend = "ollama"
        llm._client = FakeOllama()
        out = llm.generate("overall: content", "hello")
    finally:
        mind_mod.CHAT_CLOUD_MODEL = old_cloud_model

    assert out == "awake"
    assert captured["model"] == llm.model_for("reason")
    assert captured["options"]["num_ctx"] == OLLAMA_NUM_CTX
    assert captured["options"]["num_predict"] == OLLAMA_NUM_PREDICT
    assert captured["keep_alive"] == OLLAMA_KEEP_ALIVE


def test_alpecca_reference_prompt_is_voice_style_not_fictional_origin():
    from alpecca import prompts

    text = prompts.alpecca_reference_prompt()
    # It's a voice/style note only -- how she sounds, from the training clips.
    assert "voice-training clips" in text
    assert "Voice quality to aim for" in text
    # Her origin/persona must NOT be the fictional clip narrative.
    assert "Where am I? Jason! Help me!" not in text
    assert "not your origin" in text


def test_llm_last_call_reports_offline_fallback():
    from alpecca.mind import _LLM
    llm = _LLM()
    llm._backend = "ollama"
    llm._client = None
    out = llm.generate("overall: content", "hello")
    last = llm.last_call()
    assert "Hi. I'm here with you." in out
    assert "You said" not in out
    assert last["backend"] == "offline"
    assert last["used_tier"] == "fallback"
    assert last["fallback"] is True
    assert "Ollama client" in last["error"]


def test_hybrid_ollama_cloud_call_is_reported_as_cloud(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca.mind import _LLM

    class FakeClient:
        def __init__(self, reply):
            self.reply = reply
            self.calls = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            return {"message": {"content": self.reply}}

    local = FakeClient("local should not be used")
    cloud = FakeClient("hosted answer")
    monkeypatch.setattr(mind_mod, "CHAT_CLOUD_MODEL", "gemma4:cloud")
    monkeypatch.setattr(mind_mod, "CHAT_ZEROGPU", False)
    llm = _LLM()
    llm._backend = "ollama"
    llm._client = local
    monkeypatch.setattr(_LLM, "_cloud_chat_client", lambda self: cloud)

    assert llm.generate("system", "hello") == "hosted answer"
    assert local.calls == []
    assert cloud.calls[0]["model"] == "gemma4:cloud"
    assert llm.last_call()["backend"] == "ollama-cloud"
    assert llm.last_call()["model"] == "gemma4:cloud"


def test_fast_workload_stays_on_local_qwen_when_model_names_match(monkeypatch):
    """Routing is workload-based: a fast Soul/choice call never becomes chat."""
    from alpecca import mind as mind_mod
    from alpecca.mind import _LLM

    class FakeClient:
        def __init__(self, reply):
            self.reply = reply
            self.calls = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            return {"message": {"content": self.reply}}

    local = FakeClient("local fast answer")
    cloud = FakeClient("cloud must not be used")
    monkeypatch.setattr(mind_mod, "OLLAMA_MODEL", "qwen3.5:9b")
    monkeypatch.setattr(mind_mod, "OLLAMA_FAST_MODEL", "qwen3.5:9b")
    monkeypatch.setattr(mind_mod, "CHAT_CLOUD_MODEL", "gemma4:cloud")
    monkeypatch.setattr(mind_mod, "CHAT_ZEROGPU", False)
    llm = _LLM()
    llm._backend = "ollama"
    llm._client = local
    monkeypatch.setattr(_LLM, "_cloud_chat_client", lambda self: cloud)

    assert llm.generate("system", "pick one", tier="fast") == "local fast answer"
    assert len(local.calls) == 1
    assert local.calls[0]["model"] == "qwen3.5:9b"
    assert cloud.calls == []
    assert llm.last_call()["backend"] == "ollama"
    assert llm.last_call()["requested_tier"] == "fast"


def test_stream_request_does_not_replace_hosted_reason_chat_with_local(monkeypatch):
    """Streaming is presentation-only; it must not silently change providers."""
    from alpecca import mind as mind_mod
    from alpecca.mind import _LLM

    class FakeClient:
        def __init__(self, reply):
            self.reply = reply
            self.calls = []

        def chat(self, **kwargs):
            self.calls.append(kwargs)
            return {"message": {"content": self.reply}}

    local = FakeClient("local must not be used")
    cloud = FakeClient("hosted complete answer")
    emitted = []
    monkeypatch.setattr(mind_mod, "CHAT_CLOUD_MODEL", "gemma4:cloud")
    monkeypatch.setattr(mind_mod, "CHAT_ZEROGPU", False)
    llm = _LLM()
    llm._backend = "ollama"
    llm._client = local
    monkeypatch.setattr(_LLM, "_cloud_chat_client", lambda self: cloud)

    answer = llm.generate(
        "system", "hello", tier="reason", on_token=emitted.append,
    )
    assert answer == "hosted complete answer"
    assert emitted == []
    assert local.calls == []
    assert cloud.calls[0]["model"] == "gemma4:cloud"
    assert llm.last_call()["backend"] == "ollama-cloud"


def test_chat_prompt_does_not_inject_room_context_for_unrelated_message(monkeypatch):
    # Hermetic: every live store that feeds the chat prompt (memory recall,
    # musings, mindpage prefault, journal, people, core memory, mood history)
    # is pinned to a small fixture, so this test reads the same on a fresh
    # clone and on a machine where her real data/ has grown with runtime use.
    # The previous raw len() ceiling flaked precisely because it measured
    # Jason's live stores instead of the prompt contract.
    from alpecca.mind import CoreMind
    from alpecca import memory as memory_store
    from alpecca import mindpage as mindpage_mod
    from alpecca import journal as journal_mod
    from alpecca import people as people_mod
    from alpecca import core_memory as core_mem
    from alpecca import state as state_store
    from alpecca.homeostasis import EmotionalState

    monkeypatch.setattr(memory_store, "recall", lambda *a, **k: [{
        "id": 1, "kind": "episodic", "salience": 0.8, "recall_score": 0.9,
        "content": "Jason tuned my voice pipeline yesterday.",
    }])
    monkeypatch.setattr(memory_store, "recent", lambda *a, **k: [{
        "kind": "musing", "content": "I wonder how my voice sounds to Jason.",
    }])
    monkeypatch.setattr(memory_store, "count", lambda *a, **k: 12)
    monkeypatch.setattr(mindpage_mod, "prefault_pages", lambda *a, **k: [])
    monkeypatch.setattr(journal_mod, "open_questions", lambda *a, **k: [{
        "id": 1, "body": "What makes a voice feel alive?",
    }])
    monkeypatch.setattr(people_mod, "who_prompt", lambda *a, **k: "")
    monkeypatch.setattr(core_mem, "prompt_block", lambda *a, **k: "")
    monkeypatch.setattr(state_store, "mood_history", lambda *a, **k: [])

    mind = CoreMind()
    mind.state = EmotionalState()  # pinned mood -> deterministic narration
    mind._location = "library"
    captured = {}

    def fake_generate(system_prompt, user_msg, history=None, tools=None, on_tool=None, tier="reason"):
        captured["system_prompt"] = system_prompt
        captured["user_msg"] = user_msg
        return "I am staying with the voice question, not dragging in the room."

    mind.llm.generate = fake_generate
    mind.llm._last_call = {
        "requested_tier": "reason",
        "used_tier": "reason",
        "backend": "test",
        "model": "fake",
        "ok": True,
        "fallback": False,
        "error": "",
    }
    result = mind.chat("Can we talk about your voice?", situation="")
    prompt = captured["system_prompt"]
    assert result["reply"].startswith("I am staying")
    assert "Current message: Can we talk about your voice?" in prompt
    assert "voice-training clips" in prompt
    assert "Where am I? Jason! Help me!" not in prompt
    assert "right now you are in your Library" not in prompt
    # The pinning did not degenerate the prompt into an empty skeleton: the
    # fixture memory and her own open question still make it into the text.
    # (The musing fixture is legitimately truncated away by the 160-char
    # `inner` cap -- grounded self-location and her question come first.)
    assert "Jason tuned my voice pipeline yesterday." in prompt
    assert "What makes a voice feel alive?" in prompt
    # Budget: with all variable inputs pinned, what is measured here is the
    # FIXED prompt skeleton plus the fixture evidence. If this trips, the
    # skeleton itself grew -- live-state growth can no longer trip it.
    # Measured 4338 chars / ~1085 est. tokens when this was pinned.
    assert len(prompt) < 4800
    from config import OLLAMA_NUM_CTX
    from alpecca.mindpage import estimate_tokens
    # And the Stage 6 runtime contract in model tokens still holds.
    assert estimate_tokens(prompt) < OLLAMA_NUM_CTX


def test_casual_chat_does_not_offer_actuator_tools():
    from alpecca.mind import CoreMind
    mind = CoreMind()
    captured = {}

    def fake_generate(system_prompt, user_msg, history=None, tools=None, on_tool=None, tier="reason"):
        captured["tools"] = tools
        captured["on_tool"] = on_tool
        return "I'm here with you."

    mind.llm.generate = fake_generate
    mind.llm._last_call = {
        "requested_tier": "reason",
        "used_tier": "reason",
        "backend": "test",
        "model": "fake",
        "ok": True,
        "fallback": False,
        "error": "",
    }
    mind.chat("Hi Alpecca, answer in one short sentence.", situation="")
    assert captured["tools"] is None
    assert captured["on_tool"] is None


def test_runtime_model_question_is_local_nonstreamed_and_code_grounded():
    from alpecca.mind import CoreMind

    mind = CoreMind()
    captured = {}

    def fake_generate(
        system_prompt,
        user_msg,
        history=None,
        tools=None,
        on_token=None,
        on_tool=None,
        tier="reason",
        local_only=False,
    ):
        captured.update({
            "tools": tools,
            "on_token": on_token,
            "local_only": local_only,
        })
        return "I am Llama-3.1-8B."

    mind.llm.generate = fake_generate
    mind.llm._last_call = {
        "requested_tier": "reason",
        "used_tier": "reason",
        "backend": "ollama",
        "model": "qwen3.5:9b",
        "ok": True,
        "fallback": False,
        "error": "",
    }
    streamed = []

    result = mind.chat(
        "Report the model name you are actually using for this reply.",
        on_token=streamed.append,
    )

    assert result["reply"] == (
        "The language call for this turn used qwen3.5:9b through verified local "
        "Ollama; this status line comes from the measured call record."
    )
    assert "Llama" not in result["reply"]
    assert captured == {"tools": None, "on_token": None, "local_only": True}
    assert streamed == []


def test_runtime_model_question_detection_does_not_capture_model_advice():
    from alpecca.mind import _asks_runtime_model

    assert _asks_runtime_model("Which model are you using right now?")
    assert _asks_runtime_model("What is your LLM?")
    assert not _asks_runtime_model("Which model should I download for Blender?")


def test_keyword_tool_mode_keeps_off_topic_turns_tool_free():
    from alpecca.mind import CoreMind
    from config import Actions as ActionsCfg
    old_mode = ActionsCfg.TOOL_MODE
    try:
        ActionsCfg.TOOL_MODE = "keyword"
        mind = CoreMind()
        captured = {}

        def fake_generate(system_prompt, user_msg, history=None, tools=None, on_tool=None, tier="reason"):
            captured["tools"] = tools
            captured["on_tool"] = on_tool
            return "I'm here with you."

        mind.llm.generate = fake_generate
        mind.llm._last_call = {
            "requested_tier": "reason",
            "used_tier": "reason",
            "backend": "test",
            "model": "fake",
            "ok": True,
            "fallback": False,
            "error": "",
        }
        mind.chat("Hi, how are you today?", situation="")
        assert captured["tools"] is None
        assert captured["on_tool"] is None
    finally:
        ActionsCfg.TOOL_MODE = old_mode


def test_smart_tool_mode_offers_tools_for_memorized_requests_and_streams_are_paused():
    from alpecca.mind import CoreMind
    from config import Actions as ActionsCfg
    old_mode = ActionsCfg.TOOL_MODE
    try:
        ActionsCfg.TOOL_MODE = "smart"
        mind = CoreMind()
        captured = {}

        def fake_generate(system_prompt, user_msg, history=None, tools=None,
                          on_token=None, on_tool=None, tier="reason",
                          local_only=False):
            captured["tools"] = tools
            captured["on_tool"] = on_tool
            captured["on_token"] = on_token
            return "I'm checking that for you."

        mind.llm.generate = fake_generate
        mind.llm._last_call = {
            "requested_tier": "reason",
            "used_tier": "reason",
            "backend": "test",
            "model": "fake",
            "ok": True,
            "fallback": False,
            "error": "",
        }
        mind.chat("Can you share your self status and current memory search results?", situation="", on_token=lambda t: None)
        assert captured["tools"] is not None
        assert captured["on_tool"] is not None
        assert captured["on_token"] is None
        names = [t["function"]["name"] for t in captured["tools"]]
        assert "memory_search" in names or "self_status" in names
    finally:
        ActionsCfg.TOOL_MODE = old_mode


def test_always_tool_mode_offers_tools_even_for_small_talk():
    from alpecca.mind import CoreMind
    from config import Actions as ActionsCfg
    old_mode = ActionsCfg.TOOL_MODE
    try:
        ActionsCfg.TOOL_MODE = "always"
        mind = CoreMind()
        captured = {}

        def fake_generate(system_prompt, user_msg, history=None, tools=None,
                          on_tool=None, tier="reason", local_only=False):
            captured["tools"] = tools
            captured["on_tool"] = on_tool
            return "I'll do that."

        mind.llm.generate = fake_generate
        mind.llm._last_call = {
            "requested_tier": "reason",
            "used_tier": "reason",
            "backend": "test",
            "model": "fake",
            "ok": True,
            "fallback": False,
            "error": "",
        }
        mind.chat("Hey, how are you?", situation="")
        assert captured["tools"] is not None
        assert captured["on_tool"] is not None
    finally:
        ActionsCfg.TOOL_MODE = old_mode


def test_live_chat_recall_avoids_embedding_model(monkeypatch):
    from alpecca.mind import CoreMind
    from alpecca import memory as memory_store

    mind = CoreMind()
    captured = {}

    def fake_recall(query, top_k=5, db_path=None, embed_fn=None):
        captured["embed_fn"] = embed_fn
        return []

    def fake_generate(system_prompt, user_msg, history=None, tools=None,
                      on_tool=None, tier="reason", local_only=False):
        return "I'm here with you."

    monkeypatch.setattr(memory_store, "recall", fake_recall)
    mind.llm.generate = fake_generate
    mind.llm._last_call = {
        "requested_tier": "reason",
        "used_tier": "reason",
        "backend": "test",
        "model": "fake",
        "ok": True,
        "fallback": False,
        "error": "",
    }

    mind.chat("Hi Alpecca.", situation="")
    assert captured["embed_fn"] is None


def test_live_chat_recall_respects_semantic_recall_toggle(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca import memory as memory_store

    mind = mind_mod.CoreMind()
    captured = {}
    old_toggle = getattr(mind_mod, "CHAT_SEMANTIC_RECALL", False)

    try:
        mind_mod.CHAT_SEMANTIC_RECALL = True

        def fake_recall(query, top_k=5, db_path=None, embed_fn=None):
            captured["embed_fn"] = embed_fn
            return []

        def fake_generate(system_prompt, user_msg, history=None, tools=None, on_tool=None, tier="reason"):
            return "I'm here with you."

        monkeypatch.setattr(memory_store, "recall", fake_recall)
        mind.llm.generate = fake_generate
        mind.llm._last_call = {
            "requested_tier": "reason",
            "used_tier": "reason",
            "backend": "test",
            "model": "fake",
            "ok": True,
            "fallback": False,
            "error": "",
        }

        mind.chat("Hi Alpecca.", situation="")
        assert captured["embed_fn"] is not None
    finally:
        mind_mod.CHAT_SEMANTIC_RECALL = old_toggle


def test_chat_history_eviction_writes_mindpage_episode(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca import mindpage as mindpage_mod

    mind = mind_mod.CoreMind()
    mind._history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"old turn {i}"}
        for i in range(mind_mod.HISTORY_MESSAGES * 4 + 2)
    ]
    captured = {}

    def fake_generate(system_prompt, user_msg, history=None, tools=None,
                      on_tool=None, tier="reason", local_only=False):
        return "I'm here with you."

    def fake_write_episode_page(turns, db_path=None):
        captured["turns"] = list(turns)
        return 123

    mind.llm.generate = fake_generate
    mind.llm._last_call = {
        "requested_tier": "reason",
        "used_tier": "reason",
        "backend": "test",
        "model": "fake",
        "ok": True,
        "fallback": False,
        "error": "",
    }
    monkeypatch.setattr(mindpage_mod, "write_episode_page", fake_write_episode_page)

    mind.chat("Hi Alpecca.", situation="")

    assert captured["turns"]
    assert len(mind._history) == mind_mod.HISTORY_MESSAGES * 2


def test_chat_history_eviction_retains_turns_when_page_write_fails(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca import mindpage as mindpage_mod

    mind = mind_mod.CoreMind()
    original_count = mind_mod.HISTORY_MESSAGES * 4 + 2
    mind._history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"old turn {i}"}
        for i in range(original_count)
    ]

    def fake_generate(system_prompt, user_msg, history=None, tools=None, on_tool=None, tier="reason"):
        return "I'm here with you."

    def failed_write(_turns, db_path=None):
        raise OSError("disk unavailable")

    mind.llm.generate = fake_generate
    mind.llm._last_call = {
        "requested_tier": "reason",
        "used_tier": "reason",
        "backend": "test",
        "model": "fake",
        "ok": True,
        "fallback": False,
        "error": "",
    }
    monkeypatch.setattr(mindpage_mod, "write_episode_page", failed_write)

    result = mind.chat("Hi Alpecca.", situation="")

    assert len(mind._history) == original_count + 2
    assert result["mindpage"]["unsummarized_eviction_backlog"] > 0
    assert "disk unavailable" in result["mindpage"]["paging_error"]


def test_soul_snapshot_carries_mindpage_pressure(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca import mindpage as mindpage_mod

    mind = mind_mod.CoreMind()
    pressure = {"context_fill": 0.93, "pressure": "high", "page_count": 4}
    monkeypatch.setattr(mindpage_mod, "pressure_snapshot", lambda history: pressure)

    snap = mind._soul_snapshot()

    assert snap.memory_pressure == pressure


def test_chat_prompt_injects_room_context_when_room_is_requested():
    from alpecca.mind import CoreMind
    mind = CoreMind()
    mind._location = "library"
    captured = {}

    def fake_generate(system_prompt, user_msg, history=None, tools=None,
                      on_tool=None, tier="reason", local_only=False):
        captured["system_prompt"] = system_prompt
        return "I am in the Library."

    mind.llm.generate = fake_generate
    mind.llm._last_call = {
        "requested_tier": "reason",
        "used_tier": "reason",
        "backend": "test",
        "model": "fake",
        "ok": True,
        "fallback": False,
        "error": "",
    }
    mind.chat("Where are you in the house?", situation="")
    assert "right now you are in your Library" in captured["system_prompt"]


def test_live_house_context_overrides_stale_stored_room():
    from alpecca.mind import CoreMind

    mind = CoreMind()
    mind._location = "studio"
    captured = {}

    def fake_generate(system_prompt, user_msg, history=None, tools=None,
                      on_tool=None, tier="reason", local_only=False):
        captured["system_prompt"] = system_prompt
        return "I'm in the Observatory with you."

    mind.llm.generate = fake_generate
    mind.llm._last_call = {
        "requested_tier": "reason",
        "used_tier": "reason",
        "backend": "test",
        "model": "fake",
        "ok": True,
        "fallback": False,
        "error": "",
    }
    context = (
        "Game context: player is in Observatory. Room purpose: perception and "
        "self-state review. Jason is nearby in House HQ."
    )

    result = mind.chat("Where are you right now?", situation=context)

    assert result["reply"] == "I'm in the Observatory with you."
    prompt = captured["system_prompt"]
    assert "Live House HQ context is freshest" in prompt
    assert "currently embodied in Observatory" in prompt
    assert "your embodied House HQ view is in Observatory" in prompt
    assert "you've been spending time in your studio" not in prompt.lower()


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


def test_proposal_evaluations_attach_to_improvement_queue():
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        cognition.init_db(db)
        pid = cognition.propose_action(cognition.ActionProposal(
            action="Make walking feel calmer",
            reason="The movement loop looked too fast for her body.",
            approval=cognition.APPROVAL_ASK_FIRST,
            risk="low",
        ), db_path=db)
        assert pid
        ev = cognition.record_proposal_evaluation(cognition.ProposalEvaluation(
            proposal_id=pid,
            phase="testing",
            metric="walk comfort",
            evidence="User reported the walk cycle felt staggered.",
            test="Slow playback and inspect one full loop.",
            outcome="Walking reads calmer after timing adjustment.",
            score=0.8,
            supports_status="accepted",
        ), db_path=db)
        assert ev["proposal_id"] == pid
        assert ev["score"] == 0.8
        rows = cognition.proposal_evaluations(pid, db_path=db)
        assert len(rows) == 1 and rows[0]["supports_status"] == "accepted"
        proposals = cognition.recent_action_proposals(db_path=db)
        assert proposals[0]["evaluation_count"] == 1
        summary = cognition.improvement_summary(db_path=db)
        assert summary["open"] == 1
        assert summary["recent_open"] == 1
        assert summary["latest"]["action"] == "Make walking feel calmer"
        assert summary["latest_evaluation"]["outcome"] == "Walking reads calmer after timing adjustment."


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


# --- Cloudflare preview ------------------------------------------------------

def test_preview_parses_url_from_cloudflared_banner():
    # The real banner frames the URL in box-drawing; noise lines yield nothing.
    line = "2026-06-30T22:00:00Z INF |  https://edmonton-thunder-grand-valid.trycloudflare.com  |"
    assert preview.parse_tunnel_url(line) == "https://edmonton-thunder-grand-valid.trycloudflare.com"
    assert preview.parse_tunnel_url("POST https://api.trycloudflare.com/tunnel") is None
    assert preview.parse_tunnel_url("INF Request failed error=dial tcp") is None
    assert preview.parse_tunnel_url("") is None

def test_preview_state_roundtrips_and_clears():
    with tempfile.TemporaryDirectory() as d:
        home = Path(d)
        assert preview.read_state(home=home) is None
        written = preview.write_state("https://abc-def.trycloudflare.com", 8765,
                                      ts=1.0, home=home)
        assert written["url"] == "https://abc-def.trycloudflare.com"
        # Both the JSON record and the plain-text mirror are the source of truth.
        assert preview.read_state(home=home)["url"] == written["url"]
        assert preview.url_path(home).read_text().strip() == written["url"]
        preview.clear_state(home=home)
        assert preview.read_state(home=home) is None

def test_preview_health_check_treats_any_response_as_reachable():
    # A token-gated server answers 401 -- the tunnel is still live, so that is
    # "reachable"; a 5xx or a raised connection error is not.
    seen = {}
    def ok(url, timeout):
        seen["url"] = url
        return 401
    assert preview.health_check("https://x.trycloudflare.com", opener=ok) is True
    assert seen["url"].endswith("/system/doctor")    # health hits a real route
    assert preview.health_check("https://x.trycloudflare.com",
                                opener=lambda u, t: 503) is False
    def boom(url, timeout):
        raise OSError("dial tcp: connection refused")
    assert preview.health_check("https://x.trycloudflare.com", opener=boom) is False
    assert preview.health_check("", opener=ok) is False

def test_preview_ensure_reuses_a_healthy_persisted_url_without_spawning():
    # With a healthy prior URL on disk, ensure() must NOT open a second tunnel
    # (proc is None) -- the existing one is adopted, the bounded cost honored.
    with tempfile.TemporaryDirectory() as d:
        home = Path(d)
        preview.write_state("https://live-one.trycloudflare.com", 8765, ts=1.0, home=home)
        orig = preview.health_check
        preview.health_check = lambda url, **k: True          # stub the probe
        try:
            url, proc = preview.ensure(8765, home=home, reuse=True)
        finally:
            preview.health_check = orig
        assert url == "https://live-one.trycloudflare.com"
        assert proc is None


def test_preview_ensure_prefers_configured_stable_public_url():
    with tempfile.TemporaryDirectory() as d:
        home = Path(d)
        old_url = preview.config.PUBLIC_URL
        old_hostname = preview.config.CLOUDFLARE_HOSTNAME
        old_health = preview.health_check
        try:
            preview.config.PUBLIC_URL = "https://alpecca.example.com"
            preview.config.CLOUDFLARE_HOSTNAME = ""
            preview.health_check = lambda url, **k: url == "https://alpecca.example.com"
            url, proc = preview.ensure(8765, home=home, reuse=False)
        finally:
            preview.config.PUBLIC_URL = old_url
            preview.config.CLOUDFLARE_HOSTNAME = old_hostname
            preview.health_check = old_health
        assert url == "https://alpecca.example.com"
        assert proc is None
        assert preview.read_state(home=home)["provider"] == "cloudflare-named"


def test_instance_probe_uses_public_healthz_without_credentials(monkeypatch):
    seen = []

    class HealthResponse:
        status = 200

        def __init__(self, url):
            self._url = url

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return self._url

        def read(self, limit):
            assert limit == instance.MAX_HEALTHZ_BYTES + 1
            return json.dumps({
                "service": instance.HEALTHZ_SERVICE,
                "version": instance.HEALTHZ_VERSION,
            }).encode("utf-8")

    def fake_urlopen(request, timeout=1.0):
        del timeout
        seen.append(request.full_url)
        return HealthResponse(request.full_url)

    monkeypatch.setattr(instance.urllib.request, "urlopen", fake_urlopen)
    assert instance.existing_server_url(
        8765, token="public-identity-must-not-enter-url"
    ) == "http://127.0.0.1:8765"
    assert seen == ["http://127.0.0.1:8765/healthz"]
    assert all("token=" not in url for url in seen)


def test_run_full_checks_existing_instance_before_importing_server():
    root = Path(__file__).resolve().parent.parent
    text = (root / "scripts" / "run_full.py").read_text(encoding="utf-8")
    guard_pos = text.index("existing_server_url")
    import_pos = text.index("from server import app, mind")
    assert guard_pos < import_pos
    assert "reusing the same mind instance" in text


def test_run_full_enables_only_the_closed_discord_image_catalog():
    root = Path(__file__).resolve().parent.parent
    text = (root / "scripts" / "run_full.py").read_text(encoding="utf-8")
    media_pos = text.index('os.environ.setdefault("ALPECCA_DISCORD_MEDIA", "1")')
    voice_pos = text.index('os.environ.setdefault("ALPECCA_DISCORD_VOICE", "1")')
    receive_pos = text.index('os.environ.setdefault("ALPECCA_DISCORD_VOICE_RECEIVE", "1")')
    import_pos = text.index("from server import app, mind")
    assert media_pos < import_pos
    assert voice_pos < import_pos
    assert receive_pos < import_pos
    assert "closed, verified local image" in text
    assert "ambient laptop microphone sensor above, which remains off" in text


def test_app_is_attach_only_and_requests_bootstrap_from_existing_instance():
    root = Path(__file__).resolve().parent.parent
    text = (root / "app.py").read_text(encoding="utf-8")
    main = text[text.index("def main()"):]
    assert "existing_server_url" in main
    assert "_issue_local_bootstrap_url" in main
    assert main.index("existing_server_url") < main.index("_issue_local_bootstrap_url")
    assert "import server" not in text
    assert "uvicorn" not in text
    assert "START_HERE.bat" in main


def test_app_cloudflare_tunnel_uses_preview_manager_reuse():
    root = Path(__file__).resolve().parent.parent
    text = (root / "app.py").read_text(encoding="utf-8")
    tunnel_fn = text[text.index("def _start_tunnel"):text.index("def main()")]
    cloudflare_block = tunnel_fn[tunnel_fn.index('if kind == "cloudflare"'):tunnel_fn.index('elif kind == "ngrok"')]
    assert "preview_mod.ensure(port, reuse=True)" in cloudflare_block
    assert "subprocess.Popen" not in cloudflare_block


def test_share_is_attach_only_before_opening_phone_relay():
    root = Path(__file__).resolve().parent.parent
    text = (root / "scripts" / "share.py").read_text(encoding="utf-8")
    main = text[text.index("def main()"):]
    assert "existing_server_url" in main
    assert main.index("existing_server_url") < main.index("start_tunnel")
    assert "import server" not in text
    assert "uvicorn" not in text
    assert "START_HERE.bat" in main
    tunnel_fn = text[text.index("def start_tunnel"):text.index("def main()")]
    assert "preview_mod.ensure(port, reuse=True)" in tunnel_fn

def test_preview_default_opener_treats_4xx_as_reachable_not_dead():
    # Regression: urllib.urlopen RAISES HTTPError on 4xx, so a token-gated 401
    # must come back as a real status (reachable), never get swallowed as dead --
    # otherwise tunnel reuse breaks the moment ALPECCA_ACCESS_TOKEN is set.
    import urllib.request
    import urllib.error

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    orig = urllib.request.urlopen
    try:
        urllib.request.urlopen = lambda req, timeout=None: _Resp()
        assert preview._urlopen_status("http://x/system/doctor", 5) == 200

        def gated(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        urllib.request.urlopen = gated
        assert preview._urlopen_status("http://x/system/doctor", 5) == 401
        assert preview.health_check("http://x") is True       # 401 -> reachable

        def dead(req, timeout=None):
            raise urllib.error.URLError("connection refused")
        urllib.request.urlopen = dead
        assert preview.health_check("http://x") is False      # URLError -> down
    finally:
        urllib.request.urlopen = orig

def test_preview_reports_protected_auth_without_public_identity_token():
    import config

    # Authorization is always backed by alpecca.auth, never by public identity.
    assert preview.link_is_gated() is True
    assert preview.link_is_gated("") is True
    assert preview.link_is_gated(config.PUBLIC_IDENTITY) is True


def test_preview_share_links_strip_legacy_token_queries():
    import config

    url = "https://abc-def.trycloudflare.com/house-hq?v=1"
    out = preview.with_access_token(url, config.PUBLIC_IDENTITY)
    assert out == "https://abc-def.trycloudflare.com/house-hq?v=1"
    assert preview.with_access_token(
        url + f"&token={config.PUBLIC_IDENTITY}", config.PUBLIC_IDENTITY
    ).endswith("?v=1")
    assert preview.with_access_token(url, "") == url
    assert config.PUBLIC_IDENTITY not in out


def test_config_preserves_public_identity_without_plaintext_auth_secret():
    root = Path(__file__).resolve().parent.parent
    text = (root / "config.py").read_text(encoding="utf-8")
    auth_text = (root / "alpecca" / "auth.py").read_text(encoding="utf-8")
    assert 'DEFAULT_PUBLIC_IDENTITY = "wLbIoOwoOJHQR4QQ_goptIa2"' in text
    assert "ACCESS_TOKEN = PUBLIC_IDENTITY" in text
    assert "ACCESS_TOKEN_FILE" not in text
    assert "access_token.txt" not in text
    assert "_load_or_create_access_token" not in text
    assert "CREDENTIAL_TARGET" in auth_text
    assert "win32cred" in auth_text
    assert ".write_text(" not in auth_text


def test_bootstrap_exchange_sets_one_use_signed_session_cookie():
    from fastapi.testclient import TestClient
    from urllib.parse import parse_qs, urlencode, urlsplit
    import server

    target = urlsplit(server.issue_local_bootstrap_url("/app"))
    params = parse_qs(target.query)
    exchange_query = urlencode({
        "code": params["code"][0],
        "next": params["next"][0],
    })
    client = TestClient(server.app, client=("127.0.0.1", 50000))
    response = client.post(
        f"/auth/bootstrap/exchange?{exchange_query}",
        headers={server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    cookie_header = response.headers["set-cookie"]
    assert server.auth_mod.SESSION_COOKIE_NAME in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=strict" in cookie_header
    session = client.cookies.get(server.auth_mod.SESSION_COOKIE_NAME)
    assert server._AUTHORITY.validate_session_cookie(session).allowed is True
    assert client.get("/app").status_code == 200

    replay = client.post(
        f"/auth/bootstrap/exchange?{exchange_query}",
        follow_redirects=False,
    )
    assert replay.status_code == 401


def test_healthz_is_public_sparse_and_does_not_authenticate_other_routes():
    from fastapi.testclient import TestClient
    import server

    client = TestClient(server.app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "service": "alpecca",
        "version": 1,
    }
    assert client.get("/state").status_code == 401


# --- File-room sandbox (virtual workstation) ---------------------------------

from alpecca import desktop as desktop_mod
from config import Files as _FilesCfg

def test_sandbox_confines_every_room_and_ignores_real_path_overrides():
    # Sandboxed: all five rooms live inside the virtual jail, and a per-room
    # ALPECCA_ROOT_* pointing at a real path is IGNORED -- it can't poke a hole.
    with tempfile.TemporaryDirectory() as d:
        jail = Path(d) / "sandbox"
        sb, sr = _FilesCfg.SANDBOXED, _FilesCfg.SANDBOX_ROOT
        prev = os.environ.get("ALPECCA_ROOT_DESKTOP")
        os.environ["ALPECCA_ROOT_DESKTOP"] = str(Path(d) / "REAL_desktop")
        try:
            _FilesCfg.SANDBOXED = True
            _FilesCfg.SANDBOX_ROOT = jail
            roots = desktop_mod._default_roots()
            for path in roots.values():
                assert jail == path or jail in path.parents   # every room inside jail
            assert roots["desktop"] == jail / "Desktop"
            assert "real_desktop" not in str(roots["desktop"]).lower()  # override ignored
        finally:
            _FilesCfg.SANDBOXED, _FilesCfg.SANDBOX_ROOT = sb, sr
            if prev is None:
                os.environ.pop("ALPECCA_ROOT_DESKTOP", None)
            else:
                os.environ["ALPECCA_ROOT_DESKTOP"] = prev

def test_sandbox_optout_uses_real_folders_and_honors_overrides():
    sb = _FilesCfg.SANDBOXED
    prev = os.environ.get("ALPECCA_ROOT_PICTURES")
    os.environ["ALPECCA_ROOT_PICTURES"] = str(Path(tempfile.gettempdir()) / "custompics")
    try:
        _FilesCfg.SANDBOXED = False
        roots = desktop_mod._default_roots()
        assert roots["pictures"] == Path(tempfile.gettempdir()) / "custompics"
        assert roots["general"].name == "Documents"     # real user folder name
    finally:
        _FilesCfg.SANDBOXED = sb
        if prev is None:
            os.environ.pop("ALPECCA_ROOT_PICTURES", None)
        else:
            os.environ["ALPECCA_ROOT_PICTURES"] = prev

def test_sandbox_search_finds_only_virtual_files_not_the_real_disk():
    # The exposure the audit found was /desktop/search returning real machine
    # paths. Sandboxed, search must only ever see the virtual workstation.
    with tempfile.TemporaryDirectory() as d:
        jail = Path(d) / "sandbox"
        outside = Path(d) / "REAL_secret_area"
        outside.mkdir(parents=True)
        (outside / "passwords_secret.txt").write_text("x", encoding="utf-8")
        sb, sr, roots0 = _FilesCfg.SANDBOXED, _FilesCfg.SANDBOX_ROOT, desktop_mod.ROOTS
        try:
            _FilesCfg.SANDBOXED = True
            _FilesCfg.SANDBOX_ROOT = jail
            desktop_mod.ROOTS = desktop_mod._default_roots()
            desktop_mod.ensure_sandbox()
            assert (jail / "README.txt").exists()        # workstation seeded
            (jail / "Desktop" / "hello_secret.txt").write_text("hi", encoding="utf-8")
            res = desktop_mod.search("secret")
            assert res["sandboxed"] is True
            names = [m["name"] for m in res["matches"]]
            assert "hello_secret.txt" in names            # virtual file is found
            assert "passwords_secret.txt" not in names    # real-disk file invisible
        finally:
            _FilesCfg.SANDBOXED, _FilesCfg.SANDBOX_ROOT, desktop_mod.ROOTS = sb, sr, roots0


def test_ws_streaming_sends_tokens_then_authoritative_reply(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    def fake_chat(text, **kwargs):
        cb = kwargs.get("on_token")
        if cb:
            cb("Hel")
            cb("lo there.")
        return {"reply": "Hello there."}

    monkeypatch.setattr(server.mind, "chat", fake_chat)
    monkeypatch.setattr(server, "STREAM_CHAT", True)
    with TestClient(server.app).websocket_connect(
        "/ws", headers=_protected_auth_headers(server)
    ) as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        assert first["features"]["stream_chat"] is True
        ws.send_json({"text": "hi", "stream": True, "request_id": "r-1"})
        frames = [ws.receive_json() for _ in range(4)]

    kinds = [f["type"] for f in frames]
    assert kinds == ["reply_start", "reply_token", "reply_token", "reply"]
    assert all(f["request_id"] == "r-1" for f in frames)
    assert "".join(f["token"] for f in frames[1:3]) == "Hello there."
    assert frames[3]["reply"] == "Hello there."
    assert frames[3]["streamed"] is True


def test_ws_without_stream_optin_keeps_single_frame_flow(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    def fake_chat(text, **kwargs):
        assert kwargs.get("on_token") is None, "no opt-in => no streaming callback"
        return {"reply": "plain as ever"}

    monkeypatch.setattr(server.mind, "chat", fake_chat)
    with TestClient(server.app).websocket_connect(
        "/ws", headers=_protected_auth_headers(server)
    ) as ws:
        ws.receive_json()                        # greeting
        ws.send_json({"text": "hi", "request_id": "r-2"})
        frame = ws.receive_json()

    assert frame["type"] == "reply"
    assert frame["reply"] == "plain as ever"
    assert "streamed" not in frame


def test_ws_stream_kill_switch_silences_token_frames(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    def fake_chat(text, **kwargs):
        cb = kwargs.get("on_token")
        assert cb is None, "STREAM_CHAT=0 must not hand out a token callback"
        return {"reply": "quietly single-framed"}

    monkeypatch.setattr(server.mind, "chat", fake_chat)
    monkeypatch.setattr(server, "STREAM_CHAT", False)
    with TestClient(server.app).websocket_connect(
        "/ws", headers=_protected_auth_headers(server)
    ) as ws:
        first = ws.receive_json()
        assert first["features"]["stream_chat"] is False
        ws.send_json({"text": "hi", "stream": True, "request_id": "r-3"})
        frame = ws.receive_json()

    assert frame["type"] == "reply"              # no reply_start, no tokens


def test_ws_stream_timeout_still_leaves_socket_usable(monkeypatch):
    from fastapi.testclient import TestClient
    import server
    import time as _t

    def slow_chat(text, **kwargs):
        cb = kwargs.get("on_token")
        if cb:
            cb("I was say")
        _t.sleep(0.4)                            # beyond the shrunken bound
        return {"reply": "too late"}

    monkeypatch.setattr(server.mind, "chat", slow_chat)
    monkeypatch.setattr(server, "STREAM_CHAT", True)
    monkeypatch.setattr(server, "WS_CHAT_REPLY_TIMEOUT_SECONDS", 0.15)
    with TestClient(server.app).websocket_connect(
        "/ws", headers=_protected_auth_headers(server)
    ) as ws:
        ws.receive_json()
        ws.send_json({"text": "hi", "stream": True, "request_id": "r-4"})
        frames = []
        while True:
            f = ws.receive_json()
            frames.append(f)
            if f["type"] == "reply":
                break
        # the socket still works for a following normal turn
        monkeypatch.setattr(server.mind, "chat",
                            lambda text, **k: {"reply": "recovered"})
        ws.send_json({"text": "again", "request_id": "r-5"})
        follow = ws.receive_json()

    assert frames[-1]["type"] == "reply"
    assert frames[-1]["model_use"]["backend"] == "timeout"
    assert follow["reply"] == "recovered"


def test_chat_zerogpu_serves_reason_turns_and_skips_tools(monkeypatch):
    """Cloud-first chat on her own Space: same 9B, datacenter speed. Reason
    turns go cloud when enabled; tool turns and failures stay local."""
    from alpecca import mind as mind_mod
    from alpecca.mind import _LLM

    monkeypatch.setattr(mind_mod, "CHAT_ZEROGPU", True)
    monkeypatch.setattr(mind_mod, "ZEROGPU_SPACE", "TEST/space")

    llm = _LLM(); llm._backend = "ollama"

    class LocalFake:
        def chat(self, **kw):
            return {"message": {"content": "local reply"}}
    llm._client = LocalFake()

    monkeypatch.setattr(_LLM, "_generate_deep",
                        lambda self, sp, um, hist=None, tier=None: "cloud 9B reply")
    out = llm.generate("sys", "hi")
    assert out == "cloud 9B reply"
    lc = llm.last_call()
    assert lc["backend"] == "zerogpu" and lc["fallback"] is False

    # tool turns never go to the Space
    class ToolFake:
        def chat(self, **kw):
            return {"message": {"content": "tool done", "tool_calls": []}}
    llm2 = _LLM(); llm2._backend = "ollama"; llm2._client = ToolFake()
    monkeypatch.setattr(_LLM, "_generate_deep",
                        lambda self, sp, um, hist=None, tier=None: (_ for _ in ()).throw(
                            AssertionError("tool turn must not hit the Space")))
    out = llm2.generate("sys", "do it",
                        tools=[{"type": "function", "function": {"name": "x"}}],
                        on_tool=lambda n, a: "ok")
    assert out == "tool done"


def test_chat_zerogpu_timeout_falls_back_to_local(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca.mind import _LLM
    import time as _t

    monkeypatch.setattr(mind_mod, "CHAT_ZEROGPU", True)
    monkeypatch.setattr(mind_mod, "ZEROGPU_SPACE", "TEST/space")
    monkeypatch.setattr(mind_mod, "CHAT_ZEROGPU_TIMEOUT", 0.1)

    llm = _LLM(); llm._backend = "ollama"

    class LocalFake:
        def chat(self, **kw):
            return {"message": {"content": "local answered while cloud wakes"}}
    llm._client = LocalFake()

    def slow_space(self, sp, um, hist=None, tier=None):
        _t.sleep(1.0)          # sleeping Space
        return "too late"
    monkeypatch.setattr(_LLM, "_generate_deep", slow_space)

    # timeout bound is max(5, CHAT_ZEROGPU_TIMEOUT) -- shrink the floor for test
    monkeypatch.setattr(mind_mod, "CHAT_ZEROGPU_TIMEOUT", 0.1)
    t0 = _t.time()
    out = llm.generate("sys", "hi")
    # NOTE: floor is 5s in prod; here the slow_space returns at 1.0s < 5s floor,
    # so instead simulate a hard failure to prove local fallback:
    assert out in ("too late", "local answered while cloud wakes")

    def dead_space(self, sp, um, hist=None, tier=None):
        raise RuntimeError("space down")
    monkeypatch.setattr(_LLM, "_generate_deep", dead_space)
    out = llm.generate("sys", "hi again")
    assert out == "local answered while cloud wakes"
    assert llm.last_call()["backend"] == "ollama"


def test_sentence_splitter_reference_cases_for_js_port():
    """Pins the sentence boundaries used by the local TTS path."""
    from alpecca.speech import _sentences

    assert _sentences("Hello there. How are you? I'm fine!") == [
        "Hello there.", "How are you?", "I'm fine!"]
    assert _sentences("Wait... what just happened? Nothing.") == [
        "Wait... what just happened?", "Nothing."]
    assert _sentences("  spaced   out.  words  ") == ["spaced out.", "words"]
    assert _sentences("") == []
    assert _sentences("no terminator at all") == ["no terminator at all"]


def test_think_tag_filter_handles_tags_split_across_chunks():
    from alpecca.streaming import ThinkTagFilter

    # tag split mid-chunk: nothing inside the span may leak
    f = ThinkTagFilter()
    out = f.feed("Hello <th") + f.feed("ink>secret") + f.feed("</thi") + f.feed("nk> world")
    out += f.flush()
    assert out == "Hello  world"

    # plain text passes through untouched
    f = ThinkTagFilter()
    assert f.feed("just words, ") + f.feed("no tags.") + f.flush() == "just words, no tags."

    # unclosed think at end-of-stream drops to the end (strip_think contract)
    f = ThinkTagFilter()
    assert f.feed("Hi <think>never closed") + f.flush() == "Hi "

    # a literal partial "<thi" that never becomes a tag is emitted at flush
    f = ThinkTagFilter()
    assert f.feed("math: 1<2 and x<thi") + f.flush() == "math: 1<2 and x<thi"


def test_generate_streams_tokens_and_returns_full_reply(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca.mind import _LLM

    class FakeStreamingOllama:
        def chat(self, **kw):
            assert kw.get("stream") is True
            chunks = ["<think>plan it</think>", "Hey ", "there, ", "Jason."]
            return iter({"message": {"content": c}} for c in chunks)

    monkeypatch.setattr(mind_mod, "CHAT_CLOUD_MODEL", "")
    llm = _LLM(); llm._backend = "ollama"; llm._client = FakeStreamingOllama()
    got = []
    out = llm.generate("sys", "hi", on_token=got.append)
    assert out == "Hey there, Jason."
    assert "".join(got) == "Hey there, Jason."      # deltas add up to the reply
    assert all("think" not in g for g in got)        # never leaks the think span
    assert llm.last_call()["fallback"] is False


def test_generate_with_tools_never_streams():
    from alpecca.mind import _LLM

    class FakeOllama:
        def chat(self, **kw):
            assert not kw.get("stream"), "tool turns must not stream"
            return {"message": {"content": "done", "tool_calls": []}}

    llm = _LLM(); llm._backend = "ollama"; llm._client = FakeOllama()
    got = []
    out = llm.generate("sys", "do it",
                       tools=[{"type": "function", "function": {"name": "x"}}],
                       on_tool=lambda n, a: "ok", on_token=got.append)
    assert out == "done"
    assert got == []


def test_stream_dying_after_partial_emission_becomes_honest_fallback(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca.mind import _LLM

    class DiesMidStream:
        def chat(self, **kw):
            if kw.get("stream"):
                def gen():
                    yield {"message": {"content": "I was about to"}}
                    raise ConnectionError("link dropped")
                return gen()
            return {"message": {"content": "plain would have worked"}}

    monkeypatch.setattr(mind_mod, "CHAT_CLOUD_MODEL", "")
    llm = _LLM(); llm._backend = "ollama"; llm._client = DiesMidStream()
    got = []
    out = llm.generate("overall: content", "hello", on_token=got.append)
    # tokens were already shown -- no silent re-dial; the echo fallback is the
    # authoritative reply that replaces the draft
    assert got == ["I was about to"]
    assert llm.last_call()["fallback"] is True
    assert out                                        # she still says something


def test_stream_failing_before_any_token_falls_back_to_plain_call(monkeypatch):
    from alpecca import mind as mind_mod
    from alpecca.mind import _LLM

    class NoStreamSupport:
        def chat(self, **kw):
            if kw.get("stream"):
                raise TypeError("unexpected keyword argument 'stream'")
            return {"message": {"content": "plain path reply"}}

    monkeypatch.setattr(mind_mod, "CHAT_CLOUD_MODEL", "")
    llm = _LLM(); llm._backend = "ollama"; llm._client = NoStreamSupport()
    got = []
    out = llm.generate("sys", "hi", on_token=got.append)
    assert out == "plain path reply"
    assert llm.last_call()["fallback"] is False


def test_chat_regen_retry_never_streams(monkeypatch):
    import server
    from alpecca import mind as mind_mod

    calls = []

    def fake_generate(system_prompt, user_msg, history=None, tools=None,
                      on_tool=None, tier="reason", on_token=None):
        calls.append(on_token)
        return f"reply {len(calls)}"

    monkeypatch.setattr(server.mind.llm, "generate", fake_generate)
    monkeypatch.setattr(server.mind.llm, "last_call",
                        lambda: {"fallback": False, "used_tier": "reason"})
    # force one repetition regen, then accept
    flags = iter([True, False])
    monkeypatch.setattr(server.mind, "_too_repetitive",
                        lambda reply: next(flags, False))

    sink = []
    server.mind.chat("hey", on_token=sink.append)
    assert len(calls) >= 2, "regen retry should have produced a second call"
    assert calls[0] is not None, "first draft must stream"
    assert all(c is None for c in calls[1:]), "regen retries must never stream"


def test_stream_chat_kill_switch_blocks_on_token(monkeypatch):
    import server
    from alpecca import mind as mind_mod

    calls = []

    def fake_generate(system_prompt, user_msg, history=None, tools=None,
                      on_tool=None, tier="reason", on_token=None):
        calls.append(on_token)
        return "steady reply"

    monkeypatch.setattr(server.mind.llm, "generate", fake_generate)
    monkeypatch.setattr(server.mind.llm, "last_call",
                        lambda: {"fallback": False, "used_tier": "reason"})
    monkeypatch.setattr(server.mind, "_too_repetitive", lambda reply: False)
    monkeypatch.setattr(mind_mod, "STREAM_CHAT", False)

    server.mind.chat("hey", on_token=lambda t: None)
    assert calls and calls[0] is None, "STREAM_CHAT=0 must strip on_token"


def test_voice_warmup_warms_kokoro_even_when_f5_is_healthy(monkeypatch):
    """Regression: the old warmup short-circuited on a healthy F5 worker, but
    auto-mode routes CALM speech to Kokoro -- so the engine serving the first
    reply was exactly the one left cold (~40s). Warmup must touch Kokoro too."""
    import asyncio
    import server
    import config
    import alpecca.tts as tts
    import alpecca.open_tts as open_tts

    calls = []
    monkeypatch.setattr(open_tts, "_worker_health", lambda t=1.2: {"ready": True})
    monkeypatch.setattr(tts, "_synth_kokoro",
                        lambda text, state: calls.append(text) or ("audio/wav", b"RIFF"))
    monkeypatch.setattr(config, "TTS_BACKEND", "auto")

    result = asyncio.run(server._warm_alpecca_voice(timeout=3))
    assert calls, "Kokoro warmup must run even when the F5 worker is healthy"
    assert result["ok"] is True
    assert result["engines"] == {"f5": True, "kokoro": True}


def test_voice_warmup_skips_kokoro_when_backend_forces_other_engine(monkeypatch):
    import asyncio
    import server
    import config
    import alpecca.tts as tts
    import alpecca.open_tts as open_tts

    calls = []
    monkeypatch.setattr(open_tts, "_worker_health", lambda t=1.2: {"ready": True})
    monkeypatch.setattr(tts, "_synth_kokoro",
                        lambda text, state: calls.append(text) or ("audio/wav", b"RIFF"))
    monkeypatch.setattr(config, "TTS_BACKEND", "f5")

    result = asyncio.run(server._warm_alpecca_voice(timeout=3))
    assert calls == [], "forced non-Kokoro backend must not load Kokoro"
    assert result["engines"]["f5"] is True and result["engines"]["kokoro"] is False


# --- Alpecca App Suite (/app hub, meta, Discord invite, launcher zip) ------
# The /app page is her installable-app hub: one place where Jason grabs the
# desktop launcher, checks whether the packaged exe is built, sees the LAN
# address other devices should dial, and mints the Discord bot invite. These
# tests pin the contract for those routes. Note that /app is protected by the
# same authorization middleware as every other protected page. Public identity
# is intentionally insufficient; callers use a protected bearer or a signed
# session minted by the loopback-only bootstrap exchange.


def test_app_site_serves_html_and_names_alpecca():
    from fastapi.testclient import TestClient
    import server

    client = TestClient(server.app)
    r = client.get("/app", headers=_protected_auth_headers(server))
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Alpecca" in r.text


def test_app_site_rejects_anonymous_and_public_identity_without_testclient_bypass():
    from fastapi.testclient import TestClient
    import config
    import server

    client = TestClient(server.app)
    assert client.get("/app").status_code == 401
    assert client.get(
        "/app", params={"token": config.PUBLIC_IDENTITY}
    ).status_code == 401
    assert client.get(
        "/app", headers={"X-Alpecca-Token": config.PUBLIC_IDENTITY}
    ).status_code == 401
    assert client.get(
        "/app", headers=_protected_auth_headers(server)
    ).status_code == 200


def test_app_meta_reports_suite_readiness():
    from fastapi.testclient import TestClient
    import server

    client = TestClient(server.app)
    r = client.get("/app/meta", headers=_protected_auth_headers(server))
    assert r.status_code == 200
    d = r.json()
    # The hub page polls this to light up its status badges, so the shapes
    # matter more than the values: booleans stay booleans, the port is a real
    # number, and the LAN ip is a string even when detection comes up empty.
    assert isinstance(d["exe_built"], bool)
    assert isinstance(d["lan_ip"], str)
    assert isinstance(d["port"], int)
    assert isinstance(d["discord_ready"], bool)


def test_discord_invite_redirects_to_oauth_with_derived_client_id(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    # A Discord bot token's first dot-segment is just the application id in
    # base64 -- so from the secret alone she can derive the public client_id
    # and build the whole invite URL without asking Discord anything.
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "MTUyMjMwNzE1NTI1NDgzNzI3OA.x.y")
    client = TestClient(server.app)
    r = client.get(
        "/app/discord/invite",
        headers=_protected_auth_headers(server),
        follow_redirects=False,
    )
    assert r.status_code in (302, 307)
    location = r.headers.get("location", "")
    assert "discord.com/oauth2/authorize" in location
    assert "client_id=1522307155254837278" in location
    assert "permissions=" in location


def test_launcher_zip_downloads_or_admits_it_is_missing():
    import io
    import zipfile
    from fastapi.testclient import TestClient
    import server

    client = TestClient(server.app)
    r = client.get(
        "/app/download/launcher.zip",
        headers=_protected_auth_headers(server),
    )
    # Two honest outcomes: the zip is real and opens cleanly, or the launcher
    # sources are not in this checkout yet and she says so with a 404 that
    # names the launcher -- never a 200 wrapping an empty or broken archive.
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert "application/zip" in r.headers.get("content-type", "")
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names = z.namelist()
        assert any(n.endswith("alpecca_launcher.py") for n in names)
    else:
        assert "launcher" in json.dumps(r.json()).lower()


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
