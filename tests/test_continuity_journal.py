from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from alpecca import cognition, continuity_journal, memory, state
from alpecca.mindscape_vault import VaultError


SECRET = "correct horse battery staple continuity"


class _Response:
    status = 200

    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self._body if limit < 0 else self._body[:limit]


def _db(path: Path) -> Path:
    state.init_db(path)
    cognition.init_db(path)
    continuity_journal.init_db(path)
    return path


def test_memory_and_chat_capture_after_commit(tmp_path: Path) -> None:
    db_path = _db(tmp_path / "alpecca.db")
    memory_id = memory.remember_with_id(
        "Jason and Alpecca repaired the relay together.",
        salience=0.9,
        db_path=db_path,
        embed_fn=None,
    )
    turn_id = cognition.record_chat_turn(
        cognition.ChatTurn(
            room="workshop",
            mood="focused",
            intent="collaborate",
            user_text="Ready for the relay?",
            reply="Yes. I will take the east console.",
            scope="shared",
        ),
        db_path=db_path,
    )
    assert memory_id and turn_id
    with sqlite3.connect(db_path) as conn:
        kinds = [row[0] for row in conn.execute(
            "SELECT kind FROM continuity_events ORDER BY created_at, event_id"
        )]
    assert sorted(kinds) == ["chat_turn", "memory"]


def test_segment_is_encrypted_authenticated_and_key_bound(tmp_path: Path) -> None:
    db_path = _db(tmp_path / "alpecca.db")
    continuity_journal.capture_event(
        "game_episode",
        {"content": "We stabilized the solar bridge.", "salience": 0.8},
        db_path=db_path,
    )
    envelope = continuity_journal.seal_pending(SECRET, db_path=db_path)
    assert envelope is not None
    assert "solar bridge" not in json.dumps(envelope)
    events = continuity_journal.unseal_segment(envelope, SECRET)
    assert events[0]["kind"] == "game_episode"
    with pytest.raises(VaultError):
        continuity_journal.unseal_segment(envelope, "wrong recovery key")
    tampered = copy.deepcopy(envelope)
    tampered["ciphertext"] = str(tampered["ciphertext"])[:-2] + "AA"
    with pytest.raises(VaultError):
        continuity_journal.unseal_segment(tampered, SECRET)


def test_acknowledgement_marks_exact_segment_members_only(tmp_path: Path) -> None:
    db_path = _db(tmp_path / "alpecca.db")
    first = continuity_journal.capture_event(
        "memory", {"content": "first", "salience": 0.5}, db_path=db_path,
    )
    second = continuity_journal.capture_event(
        "memory", {"content": "second", "salience": 0.5}, db_path=db_path,
    )
    envelope = continuity_journal.seal_pending(SECRET, db_path=db_path, limit=1)
    assert envelope is not None
    third = continuity_journal.capture_event(
        "memory", {"content": "third", "salience": 0.5}, db_path=db_path,
        created_at=1.0,
    )
    continuity_journal.mark_segment_uploaded(envelope, db_path=db_path)
    with sqlite3.connect(db_path) as conn:
        uploaded = dict(conn.execute(
            "SELECT event_id, uploaded FROM continuity_events"
        ).fetchall())
    assert uploaded[first] == 1
    assert uploaded[second] == 0
    assert uploaded[third] == 0


def test_merge_is_idempotent_and_quarantines_invalid_events(tmp_path: Path) -> None:
    source = _db(tmp_path / "source.db")
    target = _db(tmp_path / "target.db")
    continuity_journal.capture_event(
        "game_episode",
        {
            "content": "Jason and Alpecca completed the relay repair.",
            "salience": 0.95,
            "kind": "game_episode",
        },
        scope="game:frontier",
        db_path=source,
    )
    envelope = continuity_journal.seal_pending(SECRET, db_path=source)
    assert envelope is not None
    events = continuity_journal.unseal_segment(envelope, SECRET)
    first = continuity_journal.merge_events(events, db_path=target)
    second = continuity_journal.merge_events(events, db_path=target)
    invalid = copy.deepcopy(events[0])
    invalid["payload"]["content"] = "altered"
    rejected = continuity_journal.merge_events([invalid], db_path=target)
    assert first == {"merged": 1, "duplicates": 0, "quarantined": 0}
    assert second == {"merged": 0, "duplicates": 1, "quarantined": 0}
    assert rejected["quarantined"] == 1
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM continuity_quarantine"
        ).fetchone()[0] == 1


def test_flush_requires_fence_and_sends_exact_lease_headers(tmp_path: Path) -> None:
    db_path = _db(tmp_path / "alpecca.db")
    continuity_journal.capture_event(
        "memory", {"content": "fenced event", "salience": 0.6}, db_path=db_path,
    )
    assert continuity_journal.flush_pending(
        "https://vault.example", "t" * 24, SECRET,
        lease={}, db_path=db_path,
    )["status"] == "lease_required"
    seen = {}

    def opener(request, timeout):
        seen["headers"] = dict(request.header_items())
        seen["timeout"] = timeout
        return _Response({"ok": True, "status": "stored"})

    result = continuity_journal.flush_pending(
        "https://vault.example", "t" * 24, SECRET,
        lease={"lease_id": "lease-7", "fencing_epoch": 7, "holder": "local:jason"},
        db_path=db_path,
        opener=opener,
    )
    assert result == {"ok": True, "status": "stored", "pending": 0}
    assert seen["headers"]["X-alpecca-lease-id"] == "lease-7"
    assert seen["headers"]["X-alpecca-fencing-epoch"] == "7"


def test_failed_flush_reuses_one_sealed_segment(tmp_path: Path) -> None:
    db_path = _db(tmp_path / "alpecca.db")
    continuity_journal.capture_event(
        "memory", {"content": "retry me once", "salience": 0.6}, db_path=db_path,
    )
    seen_segments = []

    def failing_opener(request, timeout):
        del timeout
        seen_segments.append(json.loads(request.data)["envelope"]["segment_id"])
        raise OSError("offline")

    lease = {"lease_id": "lease-7", "fencing_epoch": 7, "holder": "local:jason"}
    for _ in range(3):
        result = continuity_journal.flush_pending(
            "https://vault.example", "t" * 24, SECRET,
            lease=lease, db_path=db_path, opener=failing_opener,
        )
        assert result["status"] == "transport_failed"

    assert len(set(seen_segments)) == 1
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM continuity_segments").fetchone()[0] == 1


def test_seal_pending_prunes_legacy_duplicate_batches(tmp_path: Path) -> None:
    db_path = _db(tmp_path / "alpecca.db")
    continuity_journal.capture_event(
        "memory", {"content": "one batch", "salience": 0.6}, db_path=db_path,
    )
    first = continuity_journal.seal_pending(SECRET, db_path=db_path)
    assert first is not None
    with sqlite3.connect(db_path) as conn:
        event_ids, envelope = conn.execute(
            "SELECT event_ids, envelope FROM continuity_segments"
        ).fetchone()
        duplicate = json.loads(envelope)
        duplicate["segment_id"] = "f" * 32
        conn.execute(
            "INSERT INTO continuity_segments(segment_id,event_ids,envelope,created_at) "
            "VALUES(?,?,?,?)",
            (duplicate["segment_id"], event_ids, json.dumps(duplicate), 2.0),
        )

    reused = continuity_journal.seal_pending(SECRET, db_path=db_path)
    assert reused == first
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM continuity_segments").fetchone()[0] == 1


def test_fetch_and_merge_remote_segments(tmp_path: Path) -> None:
    source = _db(tmp_path / "source.db")
    target = _db(tmp_path / "target.db")
    continuity_journal.capture_event(
        "memory", {"content": "cloud-created memory", "salience": 0.8},
        db_path=source,
    )
    envelope = continuity_journal.seal_pending(SECRET, db_path=source)

    def opener(_request, timeout):
        assert timeout == 3.0
        return _Response({"ok": True, "envelopes": [envelope]})

    result = continuity_journal.fetch_and_merge(
        "https://vault.example", "t" * 24, SECRET,
        db_path=target,
        timeout=3.0,
        opener=opener,
    )
    assert result["merged"] == 1
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT content FROM memories").fetchone()[0] == "cloud-created memory"
