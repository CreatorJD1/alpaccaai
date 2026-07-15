from __future__ import annotations

import sqlite3

import pytest

from alpecca import sqlite_backup
from alpecca.sqlite_backup import SQLiteBackupError, snapshot_database


def _values(database_path):
    with sqlite3.connect(database_path) as connection:
        return [row[0] for row in connection.execute("SELECT value FROM entries ORDER BY id")]


def _create_database(database_path):
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO entries(value) VALUES ('first')")


def test_snapshot_captures_committed_wal_data(tmp_path):
    source = tmp_path / "state.sqlite3"
    backup_dir = tmp_path / "snapshots"
    _create_database(source)

    writer = sqlite3.connect(source)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO entries(value) VALUES ('in wal')")
        writer.commit()
        assert (tmp_path / "state.sqlite3-wal").exists()

        snapshot = snapshot_database(source, backup_dir, retention=3)
    finally:
        writer.close()

    assert _values(snapshot.path) == ["first", "in wal"]
    with sqlite3.connect(snapshot.path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_snapshot_rotates_only_its_own_label(tmp_path):
    source = tmp_path / "state.sqlite3"
    backup_dir = tmp_path / "snapshots"
    _create_database(source)
    retained = []

    for value in ("second", "third", "fourth"):
        with sqlite3.connect(source) as connection:
            connection.execute("INSERT INTO entries(value) VALUES (?)", (value,))
        retained.append(snapshot_database(source, backup_dir, retention=2, label="alpecca"))

    other = backup_dir / "other-20200101T000000000000Z-0123456789ab.sqlite3"
    other.write_bytes(b"not an alpecca snapshot")
    final = snapshot_database(source, backup_dir, retention=2, label="alpecca")

    snapshots = sorted(backup_dir.glob("alpecca-*.sqlite3"))
    assert snapshots == sorted([retained[-1].path, final.path])
    assert _values(final.path) == ["first", "second", "third", "fourth"]
    assert other.exists()
    assert final.pruned == 1


def test_failed_validation_removes_staging_and_leaves_source_usable(tmp_path, monkeypatch):
    source = tmp_path / "state.sqlite3"
    backup_dir = tmp_path / "snapshots"
    _create_database(source)

    def fail_validation(_connection):
        raise SQLiteBackupError("simulated failed integrity check")

    monkeypatch.setattr(sqlite_backup, "_validate_snapshot", fail_validation)

    with pytest.raises(SQLiteBackupError, match="simulated failed integrity check"):
        snapshot_database(source, backup_dir)

    assert _values(source) == ["first"]
    assert list(backup_dir.glob("*.sqlite3")) == []
    assert list(backup_dir.glob("*.tmp")) == []


def test_invalid_source_is_rejected_without_creating_a_snapshot(tmp_path):
    source = tmp_path / "not-a-database"
    source.mkdir()
    backup_dir = tmp_path / "snapshots"

    with pytest.raises(SQLiteBackupError, match="does not exist"):
        snapshot_database(source, backup_dir)

    assert not backup_dir.exists()
