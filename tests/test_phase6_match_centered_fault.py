"""Phase 6 contract: a buried indexed fact faults in match-centered.

When a page is larger than the fault token budget, the returned excerpt must be
centered on the matching text so a fact buried deep in the transcript surfaces
with its surrounding context, never an unrelated prefix. Callers without a
query keep the ordinary prefix-bounded behavior, and a non-matching query never
fabricates a window.
"""
from __future__ import annotations

from pathlib import Path

from alpecca import mindpage
from alpecca import state as state_store


def _db(tmp_path: Path, name: str = "mindpage-match-centered.db") -> Path:
    db_path = tmp_path / name
    state_store.init_db(db_path)
    return db_path


def _buried(marker: str, *, before: int = 60, after: int = 60) -> str:
    prefix = "unrelated preamble about weather and logistics. " * before
    suffix = " trailing filler about scheduling and errands." * after
    return f"{prefix}The {marker} calibration belongs to the second terminal.{suffix}"


def test_fault_page_with_query_returns_match_centered_excerpt(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "cinderlattice"
    page_id = mindpage.write_page(
        kind="episode", topic="ordinary session", summary="ordinary notes",
        content=_buried(marker), db_path=db_path,
    )

    faulted = mindpage.fault_page(page_id, max_tokens=60, query=marker, db_path=db_path)

    assert faulted is not None
    excerpt = faulted["content"]
    assert marker in excerpt
    # The excerpt must not be the unrelated prefix of the page.
    assert not excerpt.strip().startswith("unrelated preamble")
    # And it must respect the token budget it was given.
    assert mindpage.estimate_tokens(excerpt) <= 60


def test_fault_page_without_query_keeps_prefix_behavior(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "cinderlattice"
    page_id = mindpage.write_page(
        kind="episode", topic="ordinary session", summary="ordinary notes",
        content=_buried(marker), db_path=db_path,
    )

    faulted = mindpage.fault_page(page_id, max_tokens=60, db_path=db_path)

    assert faulted is not None
    # Backwards-compatible: no query means the honest prefix, not the buried fact.
    assert faulted["content"].strip().startswith("unrelated preamble")
    assert marker not in faulted["content"]


def test_recall_page_surfaces_buried_fact_with_context(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "glaciercipher"
    page_id = mindpage.write_page(
        kind="episode", topic="ordinary session", summary="ordinary notes",
        content=_buried(marker), tier="warm", db_path=db_path,
    )

    recalled = mindpage.recall_page(marker, db_path=db_path)

    assert recalled and recalled[0]["id"] == page_id
    assert marker in recalled[0]["content"]
    assert not recalled[0]["content"].strip().startswith("unrelated preamble")


def test_prefault_evidence_is_centered_on_the_match(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "quartzsignal"
    mindpage.write_page(
        kind="episode", topic="calibration session", summary="calibration notes",
        content=_buried(marker), tier="warm", salience=0.8, db_path=db_path,
    )

    pages = mindpage.prefault_pages(marker, token_budget=320, limit=2, db_path=db_path)

    assert pages, "a strong content match should prefault"
    evidence = "\n".join(str(page.get("evidence_text") or "") for page in pages)
    assert marker in evidence


def test_non_matching_query_does_not_fabricate_a_window(tmp_path: Path):
    db_path = _db(tmp_path)
    content = _buried("realmarker")
    # A query whose terms never occur in the transcript must fall back to the
    # honest prefix, never invent a centered excerpt.
    excerpt = mindpage._match_centered_excerpt(content, "absentterminology", max_tokens=60)
    assert excerpt.strip().startswith("unrelated preamble")


def test_short_page_is_returned_whole_regardless_of_query(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "amberkey"
    content = f"Only line: the {marker} lives here."
    page_id = mindpage.write_page(
        kind="episode", topic="short session", summary="short notes",
        content=content, db_path=db_path,
    )

    faulted = mindpage.fault_page(page_id, max_tokens=1000, query=marker, db_path=db_path)

    assert faulted is not None
    assert faulted["content"] == content
