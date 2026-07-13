"""Behavioral contract tests for Mindpage's bounded content index.

These tests intentionally exercise the public page APIs rather than any FTS
table.  Page bodies remain compressed at rest; the implementation may use a
sidecar index, but searching must not inflate every stored transcript.
"""
from __future__ import annotations

import sqlite3
import time
import zlib
from pathlib import Path

import pytest

from alpecca import mindpage
from alpecca import state as state_store


def _db(tmp_path: Path, name: str = "mindpage-content-index.db") -> Path:
    db_path = tmp_path / name
    state_store.init_db(db_path)
    return db_path


def _legacy_db(tmp_path: Path, name: str = "mindpage-content-index-legacy.db") -> Path:
    """Return a new SQLite path before Mindpage has installed current tables."""
    return tmp_path / name


def _write_content_page(
    db_path: Path,
    *,
    content: str,
    topic: str = "ordinary session",
    summary: str = "ordinary session notes",
    tier: str = "warm",
    scope: str = "shared",
) -> int:
    page_id = mindpage.write_page(
        kind="episode",
        topic=topic,
        summary=summary,
        content=content,
        tier=tier,
        scope=scope,
        db_path=db_path,
    )
    assert page_id
    return page_id


def _seed_legacy_pages(db_path: Path, pages: list[dict]) -> list[int]:
    """Seed the pre-content-index durable page shape for migration coverage."""
    ids = []
    now = time.time()
    with mindpage._connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE mindpage_pages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           REAL NOT NULL,
                tier         TEXT NOT NULL,
                kind         TEXT NOT NULL,
                topic        TEXT NOT NULL,
                summary      TEXT NOT NULL,
                content_blob BLOB NOT NULL,
                embedding    TEXT,
                token_est    INTEGER NOT NULL,
                last_access  REAL NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0,
                salience     REAL NOT NULL
            )
            """
        )
        for page in pages:
            content = page.get("content", "")
            blob = page.get("blob", sqlite3.Binary(zlib.compress(content.encode("utf-8"))))
            cur = conn.execute(
                """
                INSERT INTO mindpage_pages
                    (ts, tier, kind, topic, summary, content_blob, embedding,
                     token_est, last_access, access_count, salience)
                VALUES (?, ?, 'episode', ?, ?, ?, NULL, ?, ?, 0, 0.5)
                """,
                (
                    now,
                    page.get("tier", "warm"),
                    page.get("topic", "ordinary session"),
                    page.get("summary", "ordinary session notes"),
                    blob,
                    mindpage.estimate_tokens(content),
                    now,
                ),
            )
            ids.append(int(cur.lastrowid))
    return ids


def _count(result: dict, *names: str) -> int:
    assert isinstance(result, dict)
    for name in names:
        if name in result:
            return int(result[name] or 0)
    raise AssertionError(f"Expected one of {names!r} in compact counters: {result!r}")


def _content_coverage(snapshot: dict) -> dict:
    for name in ("content_index", "content_index_coverage"):
        value = snapshot.get(name)
        if isinstance(value, dict):
            return value
    return snapshot


def test_content_only_fact_is_searchable_and_recallable(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "cinderlattice"
    page_id = _write_content_page(
        db_path,
        content=f"The {marker} calibration belongs to the second terminal.",
    )

    hits = mindpage.search_pages(marker, db_path=db_path)
    recalled = mindpage.recall_page(marker, db_path=db_path)

    assert [hit["id"] for hit in hits] == [page_id]
    assert recalled and recalled[0]["id"] == page_id
    assert marker in recalled[0]["content"]
    if "match_source" in hits[0]:
        assert hits[0]["match_source"] in {"content", "both"}


def test_buried_content_recall_centers_match_and_stays_bounded(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "buriedcinderlattice"
    page_id = _write_content_page(
        db_path,
        content=(
            ("frontpadding " * 700)
            + f"The exact {marker} calibration belongs to terminal two. "
            + ("tailpadding " * 700)
        ),
    )

    prefix = mindpage.fault_page(page_id, max_tokens=80, db_path=db_path)
    recalled = mindpage.recall_page(marker, max_tokens=80, db_path=db_path)

    assert prefix is not None and marker not in prefix["content"]
    assert recalled and recalled[0]["id"] == page_id
    assert marker in recalled[0]["content"]
    assert recalled[0]["content_match_centered"] is True
    assert "earlier page content omitted" in recalled[0]["content"]
    assert "later page content omitted" in recalled[0]["content"]
    assert mindpage.estimate_tokens(recalled[0]["content"]) <= 80


def test_prefault_buried_content_keeps_match_inside_evidence_budget(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "prefaultamberrelay"
    _write_content_page(
        db_path,
        content=(
            ("oldcontext " * 700)
            + f"The {marker} decision must remain available. "
            + ("latercontext " * 700)
        ),
    )

    pages = mindpage.prefault_pages(
        marker,
        token_budget=120,
        limit=1,
        db_path=db_path,
    )

    assert pages and marker in pages[0]["evidence_text"]
    assert pages[0]["content_match_centered"] is True
    assert mindpage.estimate_tokens(pages[0]["evidence_text"]) <= 120


def test_prefault_long_metadata_preserves_buried_match_and_total_budget(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "longsummaryvioletrelay"
    _write_content_page(
        db_path,
        topic="verbose historical conversation metadata " * 12,
        summary="summary material that must yield to matched evidence " * 80,
        content=("old detail " * 500) + marker + (" later detail" * 500),
    )

    pages = mindpage.prefault_pages(
        marker,
        token_budget=80,
        limit=1,
        db_path=db_path,
    )

    assert pages and marker in pages[0]["evidence_text"]
    assert mindpage.estimate_tokens(pages[0]["evidence_text"]) <= 80


def test_small_centered_excerpt_does_not_trim_across_matched_token(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "smallbudgetrelay"
    _write_content_page(
        db_path,
        content=("prefix words " * 80) + marker + (" suffix words" * 80),
    )

    recalled = mindpage.recall_page(marker, max_tokens=12, db_path=db_path)

    assert recalled and marker in recalled[0]["content"]
    assert mindpage.estimate_tokens(recalled[0]["content"]) <= 12


def test_missing_content_match_does_not_return_prefix_or_promote_page(tmp_path: Path):
    db_path = _db(tmp_path)
    page_id = _write_content_page(
        db_path,
        content="This page intentionally lacks the requested marker.",
        tier="warm",
    )
    with mindpage._connect(db_path) as conn:
        before = conn.execute(
            "SELECT tier, access_count FROM mindpage_pages WHERE id=?",
            (page_id,),
        ).fetchone()

    result = mindpage.fault_page(
        page_id,
        query="stalecontentmarker",
        max_tokens=80,
        db_path=db_path,
    )

    with mindpage._connect(db_path) as conn:
        after = conn.execute(
            "SELECT tier, access_count FROM mindpage_pages WHERE id=?",
            (page_id,),
        ).fetchone()
    assert result is None
    assert dict(after) == dict(before)


def test_metadata_only_recall_keeps_prefix_behavior(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "metadatasilverthread"
    page_id = _write_content_page(
        db_path,
        topic=f"Notes about {marker}",
        summary="Metadata-only match",
        content=("prefixbody " * 300) + "unrelated buried ending",
    )

    recalled = mindpage.recall_page(marker, max_tokens=40, db_path=db_path)

    assert recalled and recalled[0]["id"] == page_id
    assert recalled[0]["match_source"] == "metadata"
    assert recalled[0]["content"].startswith("prefixbody")
    assert recalled[0]["content_match_centered"] is False


def test_multiterm_locator_prefers_buried_distinct_term_over_repeated_prefix(
    tmp_path: Path,
):
    db_path = _db(tmp_path)
    common = "repeatedsignal"
    distinct = "violetanchor"
    _write_content_page(
        db_path,
        content=(common + " ") * 500
        + f"The relevant passage joins {common} with {distinct}. "
        + ("tail material " * 500),
    )

    recalled = mindpage.recall_page(
        f"{common} {distinct}",
        max_tokens=60,
        db_path=db_path,
    )

    assert recalled and distinct in recalled[0]["content"]
    assert recalled[0]["content_match_centered"] is True
    assert mindpage.estimate_tokens(recalled[0]["content"]) <= 60


def test_search_does_not_inflate_compressed_page_content(tmp_path: Path, monkeypatch):
    db_path = _db(tmp_path)
    marker = "quartzsignal"
    page_id = _write_content_page(db_path, content=f"Keep the {marker} available.")

    def fail_if_inflated(*_args, **_kwargs):
        raise AssertionError("search_pages must not inflate stored page content")

    monkeypatch.setattr(mindpage, "_inflate", fail_if_inflated)
    hits = mindpage.search_pages(marker, db_path=db_path)

    assert [hit["id"] for hit in hits] == [page_id]


def test_content_search_respects_scope_and_shared_visibility(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "scopevault"
    creator_id = _write_content_page(
        db_path,
        content=f"{marker} belongs to the creator private workspace.",
        scope="creator-device",
    )
    guest_id = _write_content_page(
        db_path,
        content=f"{marker} belongs to the guest private workspace.",
        scope="guest-device",
    )
    shared_id = _write_content_page(
        db_path,
        content=f"{marker} belongs to the shared workspace.",
        scope="shared",
    )

    creator_hits = mindpage.search_pages(
        marker, limit=10, scope="creator-device", include_shared=True, db_path=db_path
    )
    creator_private_hits = mindpage.search_pages(
        marker, limit=10, scope="creator-device", include_shared=False, db_path=db_path
    )
    guest_hits = mindpage.search_pages(
        marker, limit=10, scope="guest-device", include_shared=True, db_path=db_path
    )

    assert {hit["id"] for hit in creator_hits} == {creator_id, shared_id}
    assert {hit["id"] for hit in creator_private_hits} == {creator_id}
    assert {hit["id"] for hit in guest_hits} == {guest_id, shared_id}


def test_cold_content_is_not_prefaulted_but_explicit_recall_can_fault_it(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "glaciercipher"
    page_id = _write_content_page(
        db_path,
        content=f"Archived fact {marker} must only be explicitly recalled.",
        tier="cold",
    )

    assert mindpage.search_pages(marker, db_path=db_path) == []
    assert mindpage.prefault_pages(marker, db_path=db_path) == []

    recalled = mindpage.recall_page(marker, db_path=db_path)
    assert recalled and recalled[0]["id"] == page_id
    assert marker in recalled[0]["content"]


def test_legacy_backfill_is_batched_idempotent_and_never_duplicates_hits(tmp_path: Path):
    db_path = _legacy_db(tmp_path)
    marker = "mosswoodtoken"
    legacy_ids = _seed_legacy_pages(
        db_path,
        [
            {"content": f"Legacy entry one contains {marker}."},
            {"content": f"Legacy entry two contains {marker}."},
            {"content": f"Legacy entry three contains {marker}."},
        ],
    )

    first = mindpage.backfill_content_index(batch=1, db_path=db_path)
    assert _count(first, "scanned", "processed") <= 1
    assert _count(first, "indexed", "updated") == 1

    second = mindpage.backfill_content_index(batch=1, db_path=db_path)
    third = mindpage.backfill_content_index(batch=1, db_path=db_path)
    assert _count(second, "indexed", "updated") == 1
    assert _count(third, "indexed", "updated") == 1

    repeat = mindpage.backfill_content_index(batch=8, db_path=db_path)
    assert _count(repeat, "indexed", "updated") == 0
    hits = mindpage.search_pages(marker, limit=10, db_path=db_path)
    hit_ids = [int(hit["id"]) for hit in hits]
    assert set(hit_ids) == set(legacy_ids)
    assert len(hit_ids) == len(set(hit_ids))


def test_corrupt_legacy_blob_does_not_block_later_page_indexing(tmp_path: Path):
    db_path = _legacy_db(tmp_path)
    marker = "aftercorruptmarker"
    corrupt_id, valid_id = _seed_legacy_pages(
        db_path,
        [
            {"blob": sqlite3.Binary(b"not-a-zlib-page"), "content": "ignored"},
            {"content": f"The later page contains {marker}."},
        ],
    )

    result = mindpage.backfill_content_index(batch=8, db_path=db_path)
    hits = mindpage.search_pages(marker, db_path=db_path)

    assert isinstance(result, dict)
    assert [hit["id"] for hit in hits] == [valid_id]
    assert corrupt_id not in {hit["id"] for hit in hits}


def test_new_pages_are_content_searchable_without_idle_backfill(tmp_path: Path):
    db_path = _db(tmp_path)
    marker = "immediateledger"
    page_id = _write_content_page(db_path, content=f"Fresh page includes {marker} now.")

    hits = mindpage.search_pages(marker, db_path=db_path)

    assert [hit["id"] for hit in hits] == [page_id]


def test_deleted_or_replaced_page_content_cannot_leave_stale_search_hits(tmp_path: Path):
    db_path = _db(tmp_path)
    deleted_marker = "vanishingrelay"
    old_marker = "stalecompass"
    replacement_marker = "freshcompass"
    deleted_id = _write_content_page(
        db_path, content=f"This page will be deleted: {deleted_marker}."
    )
    changed_id = _write_content_page(
        db_path, content=f"This page will be replaced: {old_marker}."
    )

    with mindpage._connect(db_path) as conn:
        conn.execute("DELETE FROM mindpage_pages WHERE id=?", (deleted_id,))
        conn.execute(
            "UPDATE mindpage_pages SET content_blob=? WHERE id=?",
            (sqlite3.Binary(zlib.compress(f"Replacement body: {replacement_marker}.".encode("utf-8"))), changed_id),
        )

    mindpage.backfill_content_index(batch=8, db_path=db_path)

    assert mindpage.search_pages(deleted_marker, db_path=db_path) == []
    assert mindpage.search_pages(old_marker, db_path=db_path) == []
    replacement_hits = mindpage.search_pages(replacement_marker, db_path=db_path)
    assert [hit["id"] for hit in replacement_hits] == [changed_id]


def test_stats_exposes_content_index_coverage_without_claiming_full_recall(tmp_path: Path):
    db_path = _legacy_db(tmp_path)
    _seed_legacy_pages(
        db_path,
        [
            {"content": "Pending historical page contains ambercanary."},
            {"blob": sqlite3.Binary(b"corrupt-page"), "content": "ignored"},
        ],
    )
    _write_content_page(db_path, content="Indexed live page contains coppercanary.")

    mindpage.backfill_content_index(batch=8, db_path=db_path)
    coverage = _content_coverage(mindpage.stats(db_path=db_path))

    assert _count(coverage, "indexed_pages") >= 2
    assert _count(coverage, "pending_pages") >= 0
    assert _count(coverage, "retrying_pages", "corrupt_pages", "error_pages") >= 1
    assert _count(coverage, "indexed_terms", "term_count") >= 1
    assert any(name in coverage for name in ("truncated_pages", "capped_pages", "has_capped_pages"))
