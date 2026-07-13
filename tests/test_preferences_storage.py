"""Isolated tests for the scoped preference store (Lane Q, guarded writes).

Covers: the guarded write (fail-closed by default, admitted by an injected
creator authorizer, denied for guest/service principals), grounded provenance on
every row, reinforcement counting, input validation, guarded retire, and the
open read API. Every test drives a temp DB via an explicit ``db_path`` so the
real ``config.DB_PATH`` is never touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Robust import whether or not pytest is invoked from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpecca import preferences as prefs  # noqa: E402


def _admit_all(_request: prefs.WriteRequest) -> bool:
    """A permissive authorizer for exercising non-authorization behavior."""
    return True


def _record(db, **kw):
    params = dict(
        subject="Nightcall",
        category="song",
        sentiment="liked",
        source="creator",
        scope="creator",
        reason="heard it, said she loved it",
        authorize=_admit_all,
        db_path=db,
    )
    params.update(kw)
    return prefs.record_preference(**params)


# --- guarded write ----------------------------------------------------------


def test_default_authorizer_is_fail_closed(tmp_path):
    """With no injected authorizer, every write is denied and nothing stores."""
    db = tmp_path / "prefs.db"
    prefs.init_db(db)
    with pytest.raises(prefs.PreferenceWriteDenied):
        prefs.record_preference(
            subject="Nightcall",
            category="song",
            sentiment="liked",
            source="creator",
            scope="creator",
            reason="heard it",
            db_path=db,
        )
    assert prefs.list_preferences(db_path=db) == []


def test_creator_principal_authorizer_admits_creator(tmp_path):
    db = tmp_path / "prefs.db"
    prefs.init_db(db)
    pref = _record(db, authorize=prefs.creator_principal_authorizer("creator"))
    assert pref.subject == "Nightcall"
    assert pref.scope == "creator"
    assert pref.source == "creator"
    assert pref.reason == "heard it, said she loved it"
    assert pref.reinforcement == 1
    assert pref.created_at > 0
    assert pref.last_reinforced == pref.created_at
    assert pref.status == "active"


@pytest.mark.parametrize("principal", ["guest", "service:discord-bridge", ""])
def test_non_creator_principal_is_denied(tmp_path, principal):
    db = tmp_path / "prefs.db"
    prefs.init_db(db)
    with pytest.raises(prefs.PreferenceWriteDenied):
        _record(db, authorize=prefs.creator_principal_authorizer(principal))
    assert prefs.list_preferences(db_path=db) == []


def test_creator_scope_authorizer_matches_known_sources(tmp_path):
    db = tmp_path / "prefs.db"
    prefs.init_db(db)
    authorizer = prefs.CreatorScopeAuthorizer(creator_sources=frozenset({"creator"}))
    pref = _record(db, authorize=authorizer)
    assert pref.reinforcement == 1
    # A source outside the trusted set is denied.
    with pytest.raises(prefs.PreferenceWriteDenied):
        _record(db, subject="Other", source="stranger", authorize=authorizer)


# --- grounded provenance + reinforcement ------------------------------------


def test_reinforcement_counts_real_events(tmp_path):
    db = tmp_path / "prefs.db"
    prefs.init_db(db)
    first = _record(db, strength=0.6, now=100.0)
    assert first.reinforcement == 1
    second = _record(
        db, strength=0.8, reason="heard it again, still loves it", now=200.0
    )
    # Same (scope, category, subject) reinforces the one row rather than dupes.
    assert second.id == first.id
    assert second.reinforcement == 2
    assert second.reason == "heard it again, still loves it"
    assert second.last_reinforced == 200.0
    # Strength blends toward the fresh expression, it does not snap.
    assert 0.6 < second.strength < 0.8
    assert len(prefs.list_preferences(db_path=db)) == 1


def test_distinct_subjects_are_distinct_rows(tmp_path):
    db = tmp_path / "prefs.db"
    prefs.init_db(db)
    _record(db, subject="Nightcall")
    _record(db, subject="Resonance")
    assert len(prefs.list_preferences(db_path=db)) == 2


# --- input validation --------------------------------------------------------


@pytest.mark.parametrize(
    "kw",
    [
        {"category": "not-a-category"},
        {"sentiment": "adores"},
        {"scope": "public"},
        {"source": "bad source!"},
        {"subject": "   "},
        {"reason": ""},
    ],
)
def test_invalid_input_raises_and_stores_nothing(tmp_path, kw):
    db = tmp_path / "prefs.db"
    prefs.init_db(db)
    with pytest.raises(prefs.PreferenceError):
        _record(db, **kw)
    assert prefs.list_preferences(db_path=db) == []


def test_strength_is_clamped(tmp_path):
    db = tmp_path / "prefs.db"
    prefs.init_db(db)
    high = _record(db, subject="Loud", strength=5.0)
    assert high.strength == 1.0
    low = _record(db, subject="Quiet", strength=-3.0)
    assert low.strength == 0.0


# --- guarded retire ----------------------------------------------------------


def test_retire_is_guarded_and_soft(tmp_path):
    db = tmp_path / "prefs.db"
    prefs.init_db(db)
    pref = _record(db)
    # Unauthorized retire is denied and the row stays active.
    with pytest.raises(prefs.PreferenceWriteDenied):
        prefs.retire_preference(
            pref.id,
            source="creator",
            scope="creator",
            authorize=prefs.creator_principal_authorizer("guest"),
            db_path=db,
        )
    assert len(prefs.list_preferences(db_path=db)) == 1
    # Authorized retire removes it from the active view.
    retired = prefs.retire_preference(
        pref.id,
        source="creator",
        scope="creator",
        authorize=_admit_all,
        db_path=db,
    )
    assert retired is True
    assert prefs.list_preferences(db_path=db) == []


# --- open reads --------------------------------------------------------------


def test_reads_need_no_authorization(tmp_path):
    db = tmp_path / "prefs.db"
    prefs.init_db(db)
    _record(db, subject="Nightcall", sentiment="liked", category="song")
    _record(db, subject="Cilantro", sentiment="disliked", category="food")
    favs = prefs.favorites(db_path=db)
    assert [f.subject for f in favs] == ["Nightcall"]
    summary = prefs.summary(db_path=db)
    assert summary["liked"] == 1
    assert summary["disliked"] == 1
    assert summary["total"] == 2
    assert summary["by_category"]["song"] == 1
    snap = prefs.snapshot(db_path=db)
    assert snap["schema"] == "alpecca.preferences.snapshot.v1"
    assert len(snap["favorites"]) == 1
    assert snap["favorites"][0]["subject"] == "Nightcall"
