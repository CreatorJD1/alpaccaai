"""Lane O: honest recall -- confidence returned, fuzzy != fabricated, unknown
queries say "haven't learned that" -- plus the read-only brain-map snapshot."""
from __future__ import annotations

from dataclasses import dataclass

from alpecca import taught_facts as tf
from alpecca import knowledge_blocks as kb


@dataclass
class FakeDecision:
    authorized: bool
    principal: str


def _creator():
    return tf.authenticate_speaker(FakeDecision(authorized=True, principal="creator"))


_DAY = 86400.0


def test_effective_confidence_decays_with_age():
    fresh = {"confidence": 0.8, "last_taught": 1000.0, "reinforcement_count": 1}
    old = {"confidence": 0.8, "last_taught": 1000.0, "reinforcement_count": 1}
    now = 1000.0
    later = 1000.0 + 120 * _DAY
    fresh_conf = tf.effective_confidence(fresh, now=now)
    aged_conf = tf.effective_confidence(old, now=later)
    assert fresh_conf > aged_conf
    assert aged_conf < fresh_conf  # it genuinely faded


def test_reinforcement_resists_decay():
    lonely = {"confidence": 0.8, "last_taught": 0.0, "reinforcement_count": 1}
    drilled = {"confidence": 0.8, "last_taught": 0.0, "reinforcement_count": 8}
    aged = 60 * _DAY
    assert tf.effective_confidence(drilled, now=aged) > tf.effective_confidence(lonely, now=aged)


def test_unknown_query_is_honest_not_fabricated(tmp_path):
    db = tmp_path / "alpecca.db"
    tf.teach_fact("Jason likes tea.", _creator(), section="relationship", db_path=db)
    verdict = tf.recall_answer("what is the capital of France", db_path=db)
    assert verdict["found"] is False
    assert verdict["disposition"] == "unknown"
    assert verdict["text"] is None                # never invents an answer


def test_fresh_repeated_fact_is_confident(tmp_path):
    db = tmp_path / "alpecca.db"
    speaker = _creator()
    for stamp in (1000.0, 1500.0, 2000.0):
        tf.teach_fact(
            "Jason was born in Leeds.", speaker, section="relationship",
            confidence=0.7, now=stamp, db_path=db,
        )
    verdict = tf.recall_answer("where was Jason born", now=2000.0, db_path=db)
    assert verdict["found"] is True
    assert verdict["disposition"] == "confident"
    assert verdict["confident"] is True
    assert "Leeds" in verdict["text"]
    assert verdict["hedge"] is None


def test_old_detail_is_hedged_not_fabricated(tmp_path):
    db = tmp_path / "alpecca.db"
    # A one-off, low-confidence detail taught long ago.
    tf.teach_fact(
        "The picnic was on a Tuesday.", _creator(), section="episodic",
        confidence=0.4, now=0.0, db_path=db,
    )
    verdict = tf.recall_answer("what day was the picnic", now=200 * _DAY, db_path=db)
    assert verdict["found"] is True               # she DID learn it -> not "unknown"
    assert verdict["disposition"] == "hedged"     # ...but recalls it fuzzily
    assert verdict["confident"] is False
    assert verdict["hedge"]                        # a real hedge string to speak
    # The hedged text is still the genuine stored fact, never a confabulation.
    assert "Tuesday" in verdict["text"]


def test_recall_returns_confidence_on_every_hit(tmp_path):
    db = tmp_path / "alpecca.db"
    tf.teach_fact("Alpecca's core emblem glows.", _creator(), section="self_model",
                  confidence=0.9, now=10.0, db_path=db)
    hits = tf.recall("what does the emblem do", now=10.0, db_path=db)
    assert hits
    hit = hits[0]
    assert "effective_confidence" in hit
    assert "confident" in hit
    assert hit["disposition"] in {"confident", "hedged"}


def test_brain_map_snapshot_shape_and_confidence(tmp_path):
    db = tmp_path / "alpecca.db"
    speaker = _creator()
    tf.teach_fact("Jason's favorite color is teal.", speaker, section="relationship",
                  confidence=0.85, now=1000.0, db_path=db)
    # A locked, untaught guarded region she should NOT be able to answer from.
    kb.create_block("world history", "semantic", state="locked", risk=0.9,
                    guarded=True, db_path=db)

    snap = kb.brain_map_snapshot(now=1000.0, db_path=db)
    assert snap["scope"] == "creator"
    assert snap["confidence_threshold"] == tf.CONFIDENCE_THRESHOLD
    # Every memory-kind section is present, even empty ones (honest map).
    kinds = {section["kind"] for section in snap["sections"]}
    assert kinds == set(kb.SECTIONS)
    # Sections are ordered along the bright->faded depth gradient.
    depths = [section["depth"] for section in snap["sections"]]
    assert depths == sorted(depths)

    by_kind = {section["kind"]: section for section in snap["sections"]}
    relational = by_kind["relationship"]
    assert relational["populated"] == 1
    node = relational["nodes"][0]
    assert node["state"] == "populated"
    assert node["confidence"] > 0.5
    assert node["brightness"] > 0.5               # bright: she recalls it well
    assert node["fact_count"] == 1

    semantic = by_kind["semantic"]
    locked_node = next(n for n in semantic["nodes"] if n["name"] == "world history")
    assert locked_node["state"] == "locked"
    assert locked_node["brightness"] < 0.1        # dark: unlearned
    assert locked_node["sharpness"] == 0.0        # fully dissolved
    assert locked_node["guarded"] is True
    assert locked_node["risk"] == 0.9


def test_brain_map_snapshot_is_read_only(tmp_path):
    db = tmp_path / "alpecca.db"
    tf.teach_fact("A fact.", _creator(), section="semantic", db_path=db)
    before_blocks = kb.list_blocks(db_path=db)
    before_facts = [f["id"] for f in tf.facts_for_block(before_blocks[0]["id"], db_path=db)]
    kb.brain_map_snapshot(db_path=db)
    kb.brain_map_snapshot(db_path=db)
    after_blocks = kb.list_blocks(db_path=db)
    after_facts = [f["id"] for f in tf.facts_for_block(before_blocks[0]["id"], db_path=db)]
    assert before_blocks == after_blocks          # snapshot mutated nothing
    assert before_facts == after_facts
