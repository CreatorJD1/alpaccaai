"""Phase 6 contract: bounded, cancellable page-tier maintenance.

Page-tier maintenance decays salience and demotes inactive pages in bounded
batches. Because the decay and demotion are idempotent, foreground chat or TTS
may reclaim the optional-work slot at a safe row boundary through a cooperative
cancel event. A cancelled pass keeps its partial progress but is never recorded
as a completed run, so it resumes on a later idle window. Maintenance issues no
model call.
"""
from __future__ import annotations

import time
from pathlib import Path

from alpecca import mindpage
from alpecca import state as state_store


def _db(tmp_path: Path, name: str = "mindpage-tier-maintenance.db") -> Path:
    db_path = tmp_path / name
    state_store.init_db(db_path)
    return db_path


def _seed_pages(db_path: Path, count: int, *, tier: str = "warm",
                age_seconds: float = 0.0, salience: float = 0.6) -> list[int]:
    ids = []
    for i in range(count):
        page_id = mindpage.write_page(
            kind="episode", topic=f"session {i}", summary=f"notes {i}",
            content=f"page {i} body content", tier=tier, salience=salience,
            db_path=db_path,
        )
        ids.append(page_id)
    if age_seconds:
        old = time.time() - age_seconds
        with mindpage._connect(db_path) as conn:
            conn.execute("UPDATE mindpage_pages SET last_access=?", (old,))
    return ids


class _CancelAfter:
    """Report not-set for the first ``after`` polls, then set.

    ``maintain_pages`` polls once before the batch and once at the start of each
    row, so ``after=N+1`` lets exactly ``N`` rows process before cancellation.
    """

    def __init__(self, after: int) -> None:
        self.after = int(after)
        self.polls = 0

    def is_set(self) -> bool:
        self.polls += 1
        return self.polls > self.after


def _last_maintenance(db_path: Path):
    with mindpage._connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM mindpage_meta WHERE key='last_maintenance'"
        ).fetchone()
    return row["value"] if row else None


def test_completed_pass_demotes_stale_tiers_and_decays_salience(tmp_path: Path):
    db_path = _db(tmp_path)
    _seed_pages(db_path, 3, tier="hot", age_seconds=7 * 60 * 60, salience=0.8)

    result = mindpage.maintain_pages(db_path=db_path, force=True)

    assert result["ran"] is True
    assert result["hot_to_warm"] == 3
    assert result["updated"] == 3
    with mindpage._connect(db_path) as conn:
        tiers = [r["tier"] for r in conn.execute("SELECT tier FROM mindpage_pages")]
        saliences = [r["salience"] for r in conn.execute("SELECT salience FROM mindpage_pages")]
    assert set(tiers) == {"warm"}
    assert all(s < 0.8 for s in saliences)
    assert _last_maintenance(db_path) is not None


def test_interval_makes_repeat_runs_idempotent(tmp_path: Path):
    db_path = _db(tmp_path)
    _seed_pages(db_path, 2)

    first = mindpage.maintain_pages(db_path=db_path, force=True)
    second = mindpage.maintain_pages(db_path=db_path, min_interval_s=3600.0)

    assert first["ran"] is True
    assert second["ran"] is False


def test_cancel_before_start_runs_nothing_and_leaves_no_stamp(tmp_path: Path):
    db_path = _db(tmp_path)
    _seed_pages(db_path, 3)

    result = mindpage.maintain_pages(
        db_path=db_path, force=True, cancel_event=_CancelAfter(0)
    )

    assert result["ran"] is False
    assert result["cancelled"] is True
    assert result["updated"] == 0
    # A cancelled pass is never recorded as a completed maintenance run.
    assert _last_maintenance(db_path) is None


def test_midbatch_cancel_is_partial_and_resumes_on_next_pass(tmp_path: Path):
    db_path = _db(tmp_path)
    ids = _seed_pages(db_path, 5, tier="hot", age_seconds=7 * 60 * 60)

    # Cancel after two rows are processed: partial, not completed.
    cancelled = mindpage.maintain_pages(
        db_path=db_path, force=True, cancel_event=_CancelAfter(3)
    )
    assert cancelled["ran"] is False
    assert cancelled["cancelled"] is True
    assert 0 < cancelled["updated"] < len(ids)
    # The interval stamp was intentionally left untouched so it resumes.
    assert _last_maintenance(db_path) is None

    # A later idle window with no cancellation completes the remaining pages.
    resumed = mindpage.maintain_pages(db_path=db_path, force=True)
    assert resumed["ran"] is True
    assert _last_maintenance(db_path) is not None
    with mindpage._connect(db_path) as conn:
        tiers = [r["tier"] for r in conn.execute("SELECT tier FROM mindpage_pages")]
    assert set(tiers) == {"warm"}


def test_maintenance_accepts_coordinator_injected_cancel_event(tmp_path: Path):
    # The optional-work coordinator injects a threading.Event as cancel_event;
    # a live (unset) event must permit a normal completed pass.
    import threading

    db_path = _db(tmp_path)
    _seed_pages(db_path, 2)
    event = threading.Event()

    result = mindpage.maintain_pages(db_path=db_path, force=True, cancel_event=event)

    assert result["ran"] is True
    assert "cancelled" not in result
