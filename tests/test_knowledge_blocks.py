"""Lane O: knowledge_blocks table, states, sections, and unlock metadata.

These exercise the structural half of the innocence gate in isolation, against
a temp DB, with no running server and no hot-path wiring.
"""
from __future__ import annotations

from alpecca import knowledge_blocks as kb
from alpecca.memory import MEMORY_KINDS


def test_sections_track_memory_kinds():
    # Every brain-map section is a real memory kind, so the map mirrors how she
    # actually files memories rather than inventing a parallel taxonomy.
    assert kb.SECTIONS <= MEMORY_KINDS
    assert kb.DEFAULT_SECTION in MEMORY_KINDS


def test_create_and_get_block(tmp_path):
    db = tmp_path / "alpecca.db"
    block_id = kb.create_block(
        "arithmetic", "procedural", risk=0.4, reward=0.8,
        rate_limit_per_day=3, guarded=True, notes="counting first", db_path=db,
    )
    assert block_id > 0
    block = kb.get_block(block_id, db_path=db)
    assert block is not None
    assert block["name"] == "arithmetic"
    assert block["section"] == "procedural"
    assert block["state"] == "locked"           # default: dark until taught/opened
    assert block["scope"] == "creator"          # creator scope only in this slice
    # Unlock metadata is recorded verbatim (but NOT enforced here).
    assert block["risk"] == 0.4
    assert block["reward"] == 0.8
    assert block["rate_limit_per_day"] == 3
    assert block["guarded"] is True
    assert block["unlocked_at"] is None


def test_create_block_is_idempotent_per_scope_name(tmp_path):
    db = tmp_path / "alpecca.db"
    first = kb.create_block("colors", "semantic", db_path=db)
    second = kb.create_block("colors", "semantic", db_path=db)
    assert first == second
    assert len(kb.list_blocks(db_path=db)) == 1


def test_unknown_section_falls_back_to_default(tmp_path):
    db = tmp_path / "alpecca.db"
    block_id = kb.create_block("mystery", "world_history", db_path=db)
    block = kb.get_block(block_id, db_path=db)
    assert block is not None
    assert block["section"] == kb.DEFAULT_SECTION


def test_state_transitions_stamp_unlocked_at(tmp_path):
    db = tmp_path / "alpecca.db"
    block_id = kb.create_block("shapes", "semantic", db_path=db)
    opened = kb.set_state(block_id, "unlockable", now=1000.0, db_path=db)
    assert opened is not None
    assert opened["state"] == "unlockable"
    assert opened["prior_state"] == "locked"
    assert opened["unlocked_at"] == 1000.0
    # Re-opening later must not overwrite the original unlock timestamp.
    again = kb.set_state(block_id, "populated", now=2000.0, db_path=db)
    assert again is not None
    assert again["unlocked_at"] == 1000.0


def test_set_state_rejects_unknown_state(tmp_path):
    db = tmp_path / "alpecca.db"
    block_id = kb.create_block("shapes", "semantic", db_path=db)
    try:
        kb.set_state(block_id, "enlightened", db_path=db)
    except ValueError:
        pass
    else:  # pragma: no cover - the guard must raise
        raise AssertionError("set_state accepted an unknown state")


def test_mark_populated_only_advances(tmp_path):
    db = tmp_path / "alpecca.db"
    block_id = kb.create_block("greetings", "relationship", db_path=db)
    kb.mark_populated(block_id, db_path=db)
    assert kb.get_block(block_id, db_path=db)["state"] == "populated"
    # Marking again is a no-op and never demotes.
    kb.mark_populated(block_id, db_path=db)
    assert kb.get_block(block_id, db_path=db)["state"] == "populated"


def test_resolve_block_creates_section_default(tmp_path):
    db = tmp_path / "alpecca.db"
    block_id = kb.resolve_block(block=None, section="semantic", db_path=db)
    block = kb.get_block(block_id, db_path=db)
    assert block is not None
    assert block["section"] == "semantic"
    assert block["name"] == "semantic knowledge"


def test_list_blocks_filters_by_section(tmp_path):
    db = tmp_path / "alpecca.db"
    kb.create_block("a", "semantic", db_path=db)
    kb.create_block("b", "procedural", db_path=db)
    kb.create_block("c", "semantic", db_path=db)
    semantic = kb.list_blocks(section="semantic", db_path=db)
    assert {block["name"] for block in semantic} == {"a", "c"}


def test_ensure_schema_is_idempotent(tmp_path):
    db = tmp_path / "alpecca.db"
    kb.ensure_schema(db)
    kb.ensure_schema(db)  # second call must not raise
    kb.create_block("ok", "semantic", db_path=db)
    assert len(kb.list_blocks(db_path=db)) == 1
