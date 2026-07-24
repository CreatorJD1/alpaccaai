"""Durability, concurrency, restart and DST guarantees for scheduled routines.

Covers Lane I's deliverables for the atomic routine claim ledger:

* two concurrent pollers execute a due routine EXACTLY ONCE
* deferred / safely-cancelled work REMAINS due (never consumed)
* success OR terminal failure advances the schedule EXACTLY ONCE
* restart recovery of a crashed (expired-lease) claim is deterministic
* retry/backoff on failure, terminal after a bounded attempt budget
* the explicit missed-run policy skips (never backfills a burst)
* DST / timezone behavior is deterministic (fall-back single run, spring-forward skip)

Run with:
    python -m pytest -q tests\\test_routines_ledger.py
"""
from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpecca import routines
from alpecca import routine_ledger as ledger


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _fresh_db(tmp: str) -> Path:
    db = Path(tmp) / "routines.db"
    routines.init_db(db)
    return db


def _add_daily(db: Path, hour: int, kind: str = "consolidate_observations") -> dict:
    return routines.add("R", hour=hour, kind=kind, weekday=-1, db_path=db)


def _struct(year, mon, mday, hour, wday, isdst=0) -> time.struct_time:
    # yday is irrelevant to run_key / matching; 1 is a safe placeholder.
    return time.struct_time((year, mon, mday, hour, 0, 0, wday, 1, isdst))


def _fixed_localtime(mapping):
    """Return a localtime(ts) that looks each ts up in a synthetic calendar."""
    def _localtime(ts: float) -> time.struct_time:
        return mapping[float(ts)]
    return _localtime


# --------------------------------------------------------------------------- #
# 1. EXACTLY ONCE under concurrency
# --------------------------------------------------------------------------- #
def test_two_concurrent_pollers_claim_a_due_routine_exactly_once():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        rid = _add_daily(db, hour=9)["id"]
        winners_per_occurrence = []
        # Each iteration is a distinct occurrence (distinct run_key) contested by
        # many threads at once. SQLite serializes writers, so exactly one wins.
        for occurrence in range(25):
            key = f"2026-07-13-{occurrence:02d}"
            start = threading.Barrier(8)
            wins: list[dict] = []
            lock = threading.Lock()

            def poll():
                start.wait()
                got = ledger.claim(rid, key, now=1000.0, lease_seconds=300.0, db_path=db)
                if got is not None:
                    with lock:
                        wins.append(got)

            threads = [threading.Thread(target=poll) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            winners_per_occurrence.append(len(wins))
            # Distinct claim tokens are impossible if two "won" -- assert the
            # winner set is a single unique token too.
            assert len({w["claim_token"] for w in wins}) == len(wins)

        assert winners_per_occurrence == [1] * 25


def test_claim_due_wrapper_is_single_winner_across_threads():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        _add_daily(db, hour=9)
        _add_daily(db, hour=9)  # two routines both due in this window
        now = 1000.0
        # Use a localtime that puts us in hour 9 so both routines match.
        lt = _fixed_localtime({now: _struct(2026, 7, 13, 9, 0)})
        start = threading.Barrier(6)
        claimed_ids: list[int] = []
        lock = threading.Lock()

        def poll():
            start.wait()
            for row, claim in routines.claim_due(now=now, db_path=db, localtime=lt):
                with lock:
                    claimed_ids.append(int(row["id"]))

        threads = [threading.Thread(target=poll) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Each of the two due routines is claimed exactly once in total.
        assert sorted(claimed_ids) == sorted({rid for rid in claimed_ids})
        assert len(claimed_ids) == 2


# --------------------------------------------------------------------------- #
# 2. Deferred / safely-cancelled work REMAINS due
# --------------------------------------------------------------------------- #
def test_released_claim_remains_due_and_burns_no_attempt():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        rid = _add_daily(db, hour=9)["id"]
        lt = _fixed_localtime({1000.0: _struct(2026, 7, 13, 9, 0)})

        claimed = routines.claim_due(now=1000.0, db_path=db, localtime=lt)
        assert len(claimed) == 1
        row, claim = claimed[0]

        # A refused coordinator lease / cooperative cancel -> release, not consume.
        assert routines.release(claim, now=1000.0, db_path=db) is True

        # Still due in the same window, and re-claimable immediately.
        assert [r["id"] for r in routines.due(now=1000.0, db_path=db, localtime=lt)] == [rid]
        again = routines.claim_due(now=1000.0, db_path=db, localtime=lt)
        assert len(again) == 1
        # No attempt was burned by the deferral.
        state = ledger.state_of(rid, claim["run_key"], db_path=db)
        assert state["attempts"] == 0


def test_release_only_by_current_claimant():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        rid = _add_daily(db, hour=9)["id"]
        key = "2026-07-13-09"
        claim = ledger.claim(rid, key, now=1000.0, lease_seconds=100.0, db_path=db)
        # A stale holder (wrong token) cannot release the occurrence.
        assert ledger.release(rid, key, "not-the-token", now=1000.0, db_path=db) is False
        # The real holder can.
        assert ledger.release(rid, key, claim["claim_token"], now=1000.0, db_path=db) is True


# --------------------------------------------------------------------------- #
# 3. Success OR terminal failure advances the schedule EXACTLY ONCE
# --------------------------------------------------------------------------- #
def test_success_advances_schedule_exactly_once():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        rid = _add_daily(db, hour=9)["id"]
        lt = _fixed_localtime({1000.0: _struct(2026, 7, 13, 9, 0)})

        (row, claim), = routines.claim_due(now=1000.0, db_path=db, localtime=lt)
        assert routines.complete(claim, now=1000.0, db_path=db) is True

        # Not due anymore in the same window; a re-claim finds nothing.
        assert routines.due(now=1000.0, db_path=db, localtime=lt) == []
        assert routines.claim_due(now=1000.0, db_path=db, localtime=lt) == []
        # Completing again is a no-op (cannot advance twice).
        assert routines.complete(claim, now=1000.0, db_path=db) is False
        # The catalog still matches the schedule (it is the occurrence that is done).
        assert [r["id"] for r in routines.candidates(now=1000.0, db_path=db, localtime=lt)] == [rid]


def test_terminal_failure_advances_schedule_exactly_once():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        rid = _add_daily(db, hour=9)["id"]
        key = "2026-07-13-09"

        # max_attempts=1 -> the very first failure is terminal.
        claim = ledger.claim(rid, key, now=1000.0, lease_seconds=100.0, db_path=db)
        outcome = ledger.fail(rid, key, claim["claim_token"], now=1000.0,
                              error="boom", max_attempts=1, db_path=db)
        assert outcome["terminal"] is True
        assert outcome["state"] == ledger.FAILED

        # Terminal: never claimable again, and complete/fail no-op.
        assert ledger.claim(rid, key, now=2000.0, db_path=db) is None
        assert ledger.is_claimable(ledger.state_of(rid, key, db_path=db), 2000.0) is False
        assert ledger.complete(rid, key, claim["claim_token"], now=2000.0, db_path=db) is False


# --------------------------------------------------------------------------- #
# 4. Retry / backoff before the terminal state
# --------------------------------------------------------------------------- #
def test_failure_retries_with_backoff_then_goes_terminal():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        rid = _add_daily(db, hour=9)["id"]
        key = "2026-07-13-09"

        # attempt 1 -> pending behind a 10s gate.
        c1 = ledger.claim(rid, key, now=100.0, lease_seconds=50.0, db_path=db)
        o1 = ledger.fail(rid, key, c1["claim_token"], now=100.0, error="e1",
                         max_attempts=3, base_backoff=10.0, max_backoff=100.0, db_path=db)
        assert (o1["terminal"], o1["attempts"]) == (False, 1)
        assert o1["retry_after"] == 110.0

        # Inside the backoff window the occurrence is NOT claimable.
        assert ledger.claim(rid, key, now=105.0, db_path=db) is None

        # After the gate it is claimable again; attempt 2 -> 20s gate.
        c2 = ledger.claim(rid, key, now=110.0, lease_seconds=50.0, db_path=db)
        assert c2 is not None
        o2 = ledger.fail(rid, key, c2["claim_token"], now=110.0, error="e2",
                         max_attempts=3, base_backoff=10.0, max_backoff=100.0, db_path=db)
        assert (o2["terminal"], o2["attempts"]) == (False, 2)
        assert o2["retry_after"] == 130.0

        # attempt 3 reaches the cap -> terminal.
        c3 = ledger.claim(rid, key, now=130.0, lease_seconds=50.0, db_path=db)
        o3 = ledger.fail(rid, key, c3["claim_token"], now=130.0, error="e3",
                         max_attempts=3, base_backoff=10.0, max_backoff=100.0, db_path=db)
        assert (o3["terminal"], o3["state"], o3["attempts"]) == (True, ledger.FAILED, 3)


def test_only_claimant_may_complete_after_lease_reclaim():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        rid = _add_daily(db, hour=9)["id"]
        key = "2026-07-13-09"

        first = ledger.claim(rid, key, now=1000.0, lease_seconds=100.0, db_path=db)
        # Before expiry the slot cannot be re-claimed.
        assert ledger.claim(rid, key, now=1050.0, lease_seconds=100.0, db_path=db) is None
        # After the lease expires a second poller reclaims it (new token).
        second = ledger.claim(rid, key, now=1200.0, lease_seconds=100.0, db_path=db)
        assert second is not None
        assert second["claim_token"] != first["claim_token"]
        # The stale first holder can no longer complete the run.
        assert ledger.complete(rid, key, first["claim_token"], now=1200.0, db_path=db) is False
        # The current holder can, exactly once.
        assert ledger.complete(rid, key, second["claim_token"], now=1200.0, db_path=db) is True
        assert ledger.complete(rid, key, second["claim_token"], now=1200.0, db_path=db) is False


# --------------------------------------------------------------------------- #
# 5. Restart recovery is deterministic
# --------------------------------------------------------------------------- #
def test_restart_recovers_crashed_claim_exactly_once():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        rid = _add_daily(db, hour=9)["id"]
        key = "2026-07-13-09"

        # A run is claimed then the process "crashes" (never completes).
        crashed = ledger.claim(rid, key, now=1000.0, lease_seconds=100.0, db_path=db)
        assert crashed is not None

        # Mid-lease: nothing to recover yet, and no re-claim possible.
        assert ledger.expired_claims(now=1050.0, db_path=db) == []
        assert ledger.claim(rid, key, now=1050.0, db_path=db) is None

        # After the lease expires the crash is visible and re-offered deterministically.
        stale = routines.recover_stale(now=1200.0, db_path=db)
        assert [s["routine_id"] for s in stale] == [rid]

        reclaimed = ledger.claim(rid, key, now=1200.0, lease_seconds=100.0, db_path=db)
        assert reclaimed is not None
        assert ledger.complete(rid, key, reclaimed["claim_token"], now=1200.0, db_path=db) is True

        # Exactly one terminal completion; no residual recoverable work.
        assert ledger.expired_claims(now=9999.0, db_path=db) == []
        assert ledger.claim(rid, key, now=1300.0, db_path=db) is None


# --------------------------------------------------------------------------- #
# 6. Missed-run policy: skip, never backfill a burst
# --------------------------------------------------------------------------- #
def test_missed_hour_is_skipped_not_backfilled():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        rid = _add_daily(db, hour=8)["id"]

        offline_wake = 20000.0   # app wakes at 11:00, the 08:00 window already gone
        next_day = 30000.0       # next day's 08:00 window
        lt = _fixed_localtime({
            offline_wake: _struct(2026, 7, 13, 11, 0),   # hour 11 -> routine hour 8 misses
            next_day: _struct(2026, 7, 14, 8, 1),        # hour 8 -> matches, new occurrence
        })

        # Waking after the scheduled hour: not due, nothing fires (no burst).
        assert routines.candidates(now=offline_wake, db_path=db, localtime=lt) == []
        assert routines.claim_due(now=offline_wake, db_path=db, localtime=lt) == []

        # The next matching hour is a fresh occurrence and runs once.
        due_next = routines.claim_due(now=next_day, db_path=db, localtime=lt)
        assert [row["id"] for row, _ in due_next] == [rid]


def test_restart_within_the_same_hour_still_runs_the_routine():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        rid = _add_daily(db, hour=8)["id"]
        # Two ticks inside the same 08:00 bucket -> same run_key, still due until run.
        early = 1000.0
        later = 1500.0
        lt = _fixed_localtime({
            early: _struct(2026, 7, 13, 8, 0),
            later: _struct(2026, 7, 13, 8, 0),
        })
        assert routines.run_key(early, localtime=lt) == routines.run_key(later, localtime=lt)
        (row, claim), = routines.claim_due(now=early, db_path=db, localtime=lt)
        assert routines.complete(claim, now=early, db_path=db) is True
        # A restart later in the same hour does not re-run it.
        assert routines.claim_due(now=later, db_path=db, localtime=lt) == []


# --------------------------------------------------------------------------- #
# 7. DST / timezone determinism
# --------------------------------------------------------------------------- #
def test_dst_fall_back_repeated_hour_runs_exactly_once():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        rid = _add_daily(db, hour=1)["id"]

        # US fall-back 2025-11-02: local 01:30 happens twice (EDT then EST).
        edt = 100.0
        est = 4000.0
        lt = _fixed_localtime({
            edt: _struct(2025, 11, 2, 1, 6, isdst=1),   # 01:30 EDT
            est: _struct(2025, 11, 2, 1, 6, isdst=0),   # 01:30 EST (clocks fell back)
        })
        # Both physical hours map to one run_key -> one occurrence.
        assert routines.run_key(edt, localtime=lt) == routines.run_key(est, localtime=lt)

        (row, claim), = routines.claim_due(now=edt, db_path=db, localtime=lt)
        assert routines.complete(claim, now=edt, db_path=db) is True

        # The repeated wall-clock hour does NOT fire a second time.
        assert routines.claim_due(now=est, db_path=db, localtime=lt) == []


def test_dst_spring_forward_skipped_hour_never_fires():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        skipped = _add_daily(db, hour=2)["id"]     # 02:00 does not exist on this day
        valid = _add_daily(db, hour=3)["id"]

        # US spring-forward 2025-03-09: clocks jump 01:59 -> 03:00; hour 2 is skipped.
        moment = 500.0
        lt = _fixed_localtime({moment: _struct(2025, 3, 9, 3, 6, isdst=1)})

        due_ids = [row["id"] for row, _ in routines.claim_due(now=moment, db_path=db, localtime=lt)]
        # Only the routine at the existing hour runs; the skipped hour never matches.
        assert due_ids == [valid]
        assert skipped not in due_ids


# --------------------------------------------------------------------------- #
# 8. Retention pruning stays bounded and never touches live rows
# --------------------------------------------------------------------------- #
def test_prune_removes_old_terminal_rows_only():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        rid = _add_daily(db, hour=9)["id"]

        # An old completed occurrence and a live (claimed) one.
        old = ledger.claim(rid, "2020-01-01-09", now=0.0, lease_seconds=10.0, db_path=db)
        ledger.complete(rid, "2020-01-01-09", old["claim_token"], now=0.0, db_path=db)
        live = ledger.claim(rid, "2026-07-13-09", now=1_000_000.0, lease_seconds=300.0, db_path=db)
        assert live is not None

        removed = ledger.prune(now=1_000_000.0, keep_seconds=1000.0, db_path=db)
        assert removed == 1
        assert ledger.state_of(rid, "2020-01-01-09", db_path=db) is None
        # The live claim is untouched.
        assert ledger.state_of(rid, "2026-07-13-09", db_path=db)["state"] == ledger.CLAIMED


# --------------------------------------------------------------------------- #
# 9. Legacy compatibility surface still behaves (idempotent due/mark_ran)
# --------------------------------------------------------------------------- #
def test_legacy_due_and_mark_ran_are_idempotent():
    now = time.time()
    tm = time.localtime(now)
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)
        row = routines.add("Consolidate", hour=tm.tm_hour, weekday=tm.tm_wday,
                           kind="consolidate_observations", db_path=db)
        assert [r["id"] for r in routines.due(now=now, db_path=db)] == [row["id"]]
        routines.mark_ran(row["id"], now=now, db_path=db)
        assert routines.due(now=now, db_path=db) == []


def test_empty_catalog_bootstraps_internal_maintenance_once():
    with tempfile.TemporaryDirectory() as tmp:
        db = _fresh_db(tmp)

        created = routines.bootstrap_safe_internal(db_path=db)
        replay = routines.bootstrap_safe_internal(db_path=db)

        assert [row["kind"] for row in created] == [
            "consolidate_observations",
            "embed_backfill",
            "vacuum",
        ]
        assert all(row["enabled"] == 1 and row["weekday"] == -1 for row in created)
        assert replay == []
        assert len(routines.list_all(db_path=db)) == 3


def test_cancelled_or_preconfigured_catalog_is_not_bootstrapped():
    with tempfile.TemporaryDirectory() as tmp:
        cancelled_db = _fresh_db(tmp)
        assert routines.bootstrap_safe_internal(
            db_path=cancelled_db,
            cancelled=lambda: True,
        ) == []
        assert routines.list_all(db_path=cancelled_db) == []

    with tempfile.TemporaryDirectory() as tmp:
        configured_db = _fresh_db(tmp)
        existing = _add_daily(configured_db, hour=9)
        assert routines.bootstrap_safe_internal(db_path=configured_db) == []
        assert [row["id"] for row in routines.list_all(db_path=configured_db)] == [
            existing["id"]
        ]
