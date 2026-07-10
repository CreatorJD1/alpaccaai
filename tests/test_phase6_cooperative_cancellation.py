"""Phase 6D contracts for cooperative maintenance cancellation.

These tests exercise the public backfill APIs only.  They model the shared
resource coordinator's cancellation event without depending on server helpers
or internal indexing functions.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import zlib
from pathlib import Path

from alpecca import memory as memory_store
from alpecca import mindpage
from alpecca import state as state_store


def _memory_db(tmp_path: Path, name: str = "phase6d-memory.db") -> Path:
    db_path = tmp_path / name
    state_store.init_db(db_path)
    return db_path


def _embedded_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL"
        ).fetchone()[0])


def _seed_unindexed_pages(db_path: Path, count: int) -> list[str]:
    """Seed durable pages that need the public legacy-index backfill."""
    mindpage.ensure_schema(db_path)
    now = time.time()
    markers: list[str] = []
    with sqlite3.connect(db_path) as conn:
        for index in range(count):
            marker = f"phase6dcancelmarker{index}"
            markers.append(marker)
            # A bounded but non-trivial vocabulary keeps the page-body path
            # realistic while the watcher waits for the first public hit.
            padding = " ".join(f"detail{index}_{term}" for term in range(420))
            content = f"{marker} is a legacy Mindpage fact. {padding}"
            conn.execute(
                """
                INSERT INTO mindpage_pages
                    (ts, tier, kind, topic, summary, content_blob, embedding,
                     token_est, last_access, access_count, salience, scope)
                VALUES (?, 'warm', 'episode', 'ordinary session',
                        'ordinary session notes', ?, NULL, ?, ?, 0, 0.5, 'shared')
                """,
                (
                    now,
                    sqlite3.Binary(zlib.compress(content.encode("utf-8"))),
                    mindpage.estimate_tokens(content),
                    now,
                ),
            )
    return markers


def _indexed_page_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM mindpage_content_index_state WHERE status='indexed'"
        ).fetchone()[0])


def test_embedding_backfill_cancels_before_second_embed_or_write(tmp_path: Path):
    db_path = _memory_db(tmp_path)
    for content in ("first maintenance memory", "second maintenance memory"):
        assert memory_store.remember(content, salience=0.8, db_path=db_path, embed_fn=None)

    cancelled = threading.Event()
    calls: list[str] = []

    def embed(text: str):
        calls.append(text)
        cancelled.set()
        return [0.8, 0.2]

    result = memory_store.backfill_embeddings(
        batch=2,
        db_path=db_path,
        embed_fn=embed,
        cancel_event=cancelled,
    )

    assert calls == ["first maintenance memory"]
    assert result["cancelled"] is True
    assert result["errors"] == 0
    assert _embedded_count(db_path) == 0


def test_embedding_backfill_pre_cancel_does_no_model_or_write_work(tmp_path: Path):
    db_path = _memory_db(tmp_path)
    assert memory_store.remember(
        "memory that must remain unembedded", salience=0.8, db_path=db_path, embed_fn=None
    )
    cancelled = threading.Event()
    cancelled.set()
    calls: list[str] = []

    def embed(text: str):
        calls.append(text)
        return [1.0, 0.0]

    result = memory_store.backfill_embeddings(
        batch=1,
        db_path=db_path,
        embed_fn=embed,
        cancel_event=cancelled,
    )

    assert calls == []
    assert result["cancelled"] is True
    assert result["errors"] == 0
    assert _embedded_count(db_path) == 0


def test_mindpage_backfill_cancels_between_pages_then_recovers(tmp_path: Path):
    db_path = tmp_path / "phase6d-mindpage.db"
    state_store.init_db(db_path)
    markers = _seed_unindexed_pages(db_path, count=64)
    cancelled = threading.Event()
    watcher_ready = threading.Event()
    watcher_stop = threading.Event()

    def cancel_when_first_page_is_publicly_searchable() -> None:
        watcher_ready.set()
        deadline = time.monotonic() + 5.0
        while not watcher_stop.is_set() and time.monotonic() < deadline:
            try:
                if mindpage.search_pages(markers[0], db_path=db_path):
                    cancelled.set()
                    return
            except sqlite3.OperationalError:
                # A short writer transaction is expected while the index is
                # committed; retry through the public search surface.
                pass
            time.sleep(0.001)

    watcher = threading.Thread(target=cancel_when_first_page_is_publicly_searchable)
    watcher.start()
    assert watcher_ready.wait(timeout=1.0)
    try:
        result = mindpage.backfill_content_index(
            batch=len(markers),
            db_path=db_path,
            cancel_event=cancelled,
        )
    finally:
        watcher_stop.set()
        watcher.join(timeout=2.0)

    assert cancelled.is_set()
    assert result["cancelled"] is True
    assert result["errors"] == 0
    assert 0 < _indexed_page_count(db_path) < len(markers)

    # A later ordinary pass must finish the durable backlog rather than leave
    # cancellation as an error state or lose the untouched pages.
    for _ in range(4):
        mindpage.backfill_content_index(batch=len(markers), db_path=db_path)
        if all(mindpage.search_pages(marker, db_path=db_path) for marker in markers):
            break
    assert all(mindpage.search_pages(marker, db_path=db_path) for marker in markers)


def test_mindpage_backfill_pre_cancel_does_no_index_work(tmp_path: Path):
    db_path = tmp_path / "phase6d-mindpage-pre-cancel.db"
    state_store.init_db(db_path)
    markers = _seed_unindexed_pages(db_path, count=2)
    cancelled = threading.Event()
    cancelled.set()

    result = mindpage.backfill_content_index(
        batch=2,
        db_path=db_path,
        cancel_event=cancelled,
    )

    assert result["cancelled"] is True
    assert result["errors"] == 0
    assert _indexed_page_count(db_path) == 0
    assert all(not mindpage.search_pages(marker, db_path=db_path) for marker in markers)


def test_non_cancelled_backfills_keep_their_normal_results(tmp_path: Path):
    memory_db = _memory_db(tmp_path, "phase6d-normal-memory.db")
    for content in ("ordinary first memory", "ordinary second memory"):
        assert memory_store.remember(content, salience=0.8, db_path=memory_db, embed_fn=None)

    embed_calls: list[str] = []

    def embed(text: str):
        embed_calls.append(text)
        return [0.6, 0.4]

    memory_result = memory_store.backfill_embeddings(
        batch=2,
        db_path=memory_db,
        embed_fn=embed,
        cancel_event=threading.Event(),
    )
    assert memory_result == {"scanned": 2, "updated": 2, "skipped": 0, "errors": 0}
    assert len(embed_calls) == 2
    assert _embedded_count(memory_db) == 2

    mindpage_db = tmp_path / "phase6d-normal-mindpage.db"
    state_store.init_db(mindpage_db)
    markers = _seed_unindexed_pages(mindpage_db, count=2)
    page_result = mindpage.backfill_content_index(
        batch=2,
        db_path=mindpage_db,
        cancel_event=threading.Event(),
    )
    assert page_result["indexed"] == 2
    assert page_result["errors"] == 0
    assert "cancelled" not in page_result
    assert all(mindpage.search_pages(marker, db_path=mindpage_db) for marker in markers)
