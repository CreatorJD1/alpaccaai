"""Lane O: the teaching contract -- only authenticated speakers, only genuine
input, never latent model knowledge or a self-prompt."""
from __future__ import annotations

from dataclasses import dataclass

from alpecca import taught_facts as tf
from alpecca import knowledge_blocks as kb


@dataclass
class FakeDecision:
    """Duck-typed stand-in for alpecca.auth.AuthDecision."""

    authorized: bool
    principal: str


def _creator_speaker():
    speaker = tf.authenticate_speaker(FakeDecision(authorized=True, principal="creator"))
    assert speaker.can_teach
    return speaker


def test_creator_can_teach_a_fact(tmp_path):
    db = tmp_path / "alpecca.db"
    fact = tf.teach_fact(
        "Jason's favorite color is teal.", _creator_speaker(),
        section="relationship", confidence=0.7, db_path=db,
    )
    assert fact["id"] > 0
    assert fact["principal"] == "creator"
    assert fact["provenance"] == "spoken"
    assert fact["reinforced"] is False
    # Teaching a fact lights up (populates) its block.
    block = kb.get_block(fact["block_id"], db_path=db)
    assert block is not None
    assert block["state"] == "populated"


def test_plain_value_is_not_a_speaker(tmp_path):
    db = tmp_path / "alpecca.db"
    for bad in ["creator", None, {"principal": "creator"}, 1]:
        try:
            tf.teach_fact("x is y", bad, db_path=db)  # type: ignore[arg-type]
        except tf.TeachingRefused:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"teach_fact accepted a non-speaker: {bad!r}")


def test_forged_speaker_identity_is_refused(tmp_path):
    db = tmp_path / "alpecca.db"
    # The shape a self-prompt could build: verified=True but no private witness.
    forged = tf.SpeakerIdentity(speaker_id="creator", principal="creator", verified=True)
    assert not forged.can_teach
    try:
        tf.teach_fact("the sky is green", forged, db_path=db)
    except tf.TeachingRefused:
        pass
    else:  # pragma: no cover
        raise AssertionError("teach_fact accepted a forged (witness-less) identity")


def test_rejected_decision_yields_unverified_speaker(tmp_path):
    db = tmp_path / "alpecca.db"
    speaker = tf.authenticate_speaker(FakeDecision(authorized=False, principal="creator"))
    assert not speaker.can_teach
    try:
        tf.teach_fact("unauthorized fact", speaker, db_path=db)
    except tf.TeachingRefused:
        pass
    else:  # pragma: no cover
        raise AssertionError("an unauthorized decision was allowed to teach")


def test_guest_and_self_principals_cannot_teach(tmp_path):
    db = tmp_path / "alpecca.db"
    for principal in ["guest", "self", "assistant", "alpecca", "model", "service:discord-bridge"]:
        speaker = tf.authenticate_speaker(FakeDecision(authorized=True, principal=principal))
        assert not speaker.can_teach, principal
        try:
            tf.teach_fact("a fact", speaker, db_path=db)
        except tf.TeachingRefused:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"principal {principal!r} was allowed to teach")


def test_latent_or_self_provenance_is_refused(tmp_path):
    db = tmp_path / "alpecca.db"
    speaker = _creator_speaker()
    for provenance in ["model", "self", "inference", "latent", "pretrained", "generated"]:
        try:
            tf.teach_fact("2+2=4", speaker, provenance=provenance, db_path=db)
        except tf.TeachingRefused:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"provenance {provenance!r} was stored")
    # And nothing was written by any of those refused attempts.
    assert tf.recall("2+2", db_path=db) == []


def test_empty_fact_is_refused(tmp_path):
    db = tmp_path / "alpecca.db"
    try:
        tf.teach_fact("   ", _creator_speaker(), db_path=db)
    except tf.TeachingRefused:
        pass
    else:  # pragma: no cover
        raise AssertionError("an empty fact was stored")


def test_reinforcement_increments_and_lifts_confidence(tmp_path):
    db = tmp_path / "alpecca.db"
    speaker = _creator_speaker()
    first = tf.teach_fact(
        "Rygen is Jason's friend.", speaker, section="relationship",
        confidence=0.5, now=1000.0, db_path=db,
    )
    second = tf.teach_fact(
        "Rygen is Jason's friend!", speaker, section="relationship",
        confidence=0.5, now=2000.0, db_path=db,
    )
    assert second["id"] == first["id"]          # same fact, reinforced not duplicated
    assert second["reinforced"] is True
    assert second["reinforcement_count"] == 2
    assert second["confidence"] > first["confidence"]
    assert len(tf.facts_for_block(first["block_id"], db_path=db)) == 1


def test_taught_fact_is_recallable(tmp_path):
    db = tmp_path / "alpecca.db"
    tf.teach_fact(
        "The cat's name is Mochi.", _creator_speaker(),
        section="relationship", confidence=0.8, now=5000.0, db_path=db,
    )
    hits = tf.recall("what is the cat name", now=5000.0, db_path=db)
    assert hits
    assert "Mochi" in hits[0]["text"]
