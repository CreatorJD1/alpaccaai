"""Local, validated SQLite snapshots for later lifecycle integration.

The helper deliberately has no scheduler, configuration lookup, or network
behavior. A launcher can call :func:`snapshot_database` at a chosen lifecycle
boundary and decide how to report a failed snapshot.
"""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


__all__ = ["SQLiteBackupError", "SQLiteSnapshot", "snapshot_database"]


_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


class SQLiteBackupError(RuntimeError):
    """Raised when a snapshot cannot be safely published."""


@dataclass(frozen=True)
class SQLiteSnapshot:
    """Metadata for one successfully published local SQLite snapshot."""

    path: Path
    created_at: datetime
    pruned: int


def snapshot_database(
    source: str | Path,
    destination: str | Path,
    *,
    retention: int = 7,
    label: str | None = None,
    timeout_seconds: float = 5.0,
) -> SQLiteSnapshot:
    """Create one validated, rotating snapshot without modifying ``source``.

    SQLite's online backup API reads a transactionally consistent view of a
    WAL-mode database, including committed pages still held in its WAL. The
    copied database is checked with ``PRAGMA integrity_check`` before it is
    atomically renamed into ``destination``. Existing snapshots are only
    pruned after the new one has been safely published.

    ``retention`` counts only snapshots made by this helper for the same label
    and must be at least one. Failures leave the source database untouched and
    never replace an existing published snapshot with unvalidated data.
    """
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    _validate_arguments(source_path, retention, label, timeout_seconds)
    snapshot_label = label or source_path.stem
    _validate_label(snapshot_label)
    destination_path.mkdir(parents=True, exist_ok=True)
    if not destination_path.is_dir():
        raise SQLiteBackupError(f"snapshot destination is not a directory: {destination_path}")

    created_at = datetime.now(timezone.utc)
    final_path = destination_path / _snapshot_name(snapshot_label, created_at)
    staging_path = _new_staging_path(destination_path, snapshot_label)
    published = False

    try:
        with closing(_read_only_connection(source_path, timeout_seconds)) as source_conn:
            with closing(sqlite3.connect(staging_path, timeout=timeout_seconds)) as staging_conn:
                staging_conn.execute(f"PRAGMA busy_timeout={int(timeout_seconds * 1000)}")
                source_conn.backup(staging_conn)
                _validate_snapshot(staging_conn)

        # Staging and final paths share a directory, so replace is an atomic
        # filesystem operation. The final name is unique, but replace also
        # keeps the publish operation atomic if a name collision is forced.
        os.replace(staging_path, final_path)
        published = True
        pruned = _prune_snapshots(destination_path, snapshot_label, retention)
        return SQLiteSnapshot(path=final_path, created_at=created_at, pruned=pruned)
    except SQLiteBackupError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise SQLiteBackupError(f"could not create SQLite snapshot for {source_path}: {exc}") from exc
    finally:
        if not published:
            _remove_staging_files(staging_path)


def _validate_arguments(
    source: Path,
    retention: int,
    label: str | None,
    timeout_seconds: float,
) -> None:
    if not source.is_file():
        raise SQLiteBackupError(f"SQLite source database does not exist: {source}")
    if isinstance(retention, bool) or not isinstance(retention, int) or retention < 1:
        raise ValueError("retention must be an integer of at least 1")
    if label is not None:
        _validate_label(label)
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0")


def _validate_label(label: str) -> None:
    if not _LABEL_RE.fullmatch(label):
        raise ValueError("label must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


def _read_only_connection(source: Path, timeout_seconds: float) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=timeout_seconds)
    connection.execute(f"PRAGMA busy_timeout={int(timeout_seconds * 1000)}")
    return connection


def _validate_snapshot(connection: sqlite3.Connection) -> None:
    results = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
    if results != ["ok"]:
        raise SQLiteBackupError(f"snapshot integrity check failed: {'; '.join(results)}")


def _snapshot_name(label: str, created_at: datetime) -> str:
    timestamp = created_at.strftime("%Y%m%dT%H%M%S%fZ")
    return f"{label}-{timestamp}-{uuid.uuid4().hex[:12]}.sqlite3"


def _new_staging_path(destination: Path, label: str) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{label}-", suffix=".sqlite3.tmp", dir=destination)
    os.close(descriptor)
    return Path(raw_path)


def _prune_snapshots(destination: Path, label: str, retention: int) -> int:
    pattern = re.compile(
        rf"{re.escape(label)}-\d{{8}}T\d{{12}}Z-[0-9a-f]{{12}}\.sqlite3\Z"
    )
    snapshots = sorted(
        (path for path in destination.iterdir() if path.is_file() and pattern.fullmatch(path.name)),
        key=lambda path: path.name,
        reverse=True,
    )
    pruned = 0
    for path in snapshots[retention:]:
        try:
            path.unlink()
            pruned += 1
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise SQLiteBackupError(
                f"snapshot published but retention cleanup failed for {path}: {exc}"
            ) from exc
    return pruned


def _remove_staging_files(staging: Path) -> None:
    for path in (staging, Path(f"{staging}-journal"), Path(f"{staging}-shm"), Path(f"{staging}-wal")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # The source is already closed or read-only; cleanup cannot affect it.
            pass
