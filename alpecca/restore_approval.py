"""One-use creator approvals for Mindscape continuity restore imports."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable


PREVIEW_TTL_SECONDS = 10 * 60
APPROVAL_TTL_SECONDS = 5 * 60
_TOKEN_DOMAIN = b"Alpecca restore approval v1\x00"


class RestoreApprovalError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fingerprint(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise RestoreApprovalError("fingerprint_invalid")
    try:
        int(value, 16)
    except ValueError as exc:
        raise RestoreApprovalError("fingerprint_invalid") from exc
    return value.lower()


def _source(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise RestoreApprovalError("source_invalid")
    if any(not (char.isalnum() or char in "_-") for char in value):
        raise RestoreApprovalError("source_invalid")
    return value


def _token_digest(token: str) -> str:
    if not isinstance(token, str) or not 32 <= len(token) <= 256:
        raise RestoreApprovalError("approval_invalid")
    try:
        encoded = token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RestoreApprovalError("approval_invalid") from exc
    return hashlib.sha256(_TOKEN_DOMAIN + encoded).hexdigest()


class RestoreApprovalLedger:
    def __init__(
        self,
        db_path: str | Path,
        *,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.db_path = str(db_path)
        self._now = now
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mindscape_restore_approvals (
                    preview_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    preview_expires_at INTEGER NOT NULL,
                    approval_digest TEXT,
                    approved_at INTEGER,
                    approval_expires_at INTEGER,
                    used_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_restore_approval_expiry
                    ON mindscape_restore_approvals(preview_expires_at, approval_expires_at, used_at);
                """
            )

    def _prune(self, conn: sqlite3.Connection, now: int) -> None:
        conn.execute(
            "DELETE FROM mindscape_restore_approvals "
            "WHERE preview_expires_at < ? OR (used_at IS NOT NULL AND used_at < ?)",
            (now - 60, now - 24 * 60 * 60),
        )

    def issue_preview(self, fingerprint: str, source: str) -> dict[str, str | int | bool]:
        bounded_fingerprint = _fingerprint(fingerprint)
        bounded_source = _source(source)
        now = int(self._now())
        preview_id = secrets.token_urlsafe(18)
        expires_at = now + PREVIEW_TTL_SECONDS
        with self._lock, self._connect() as conn:
            self._prune(conn, now)
            conn.execute(
                "INSERT INTO mindscape_restore_approvals "
                "(preview_id, fingerprint, source, created_at, preview_expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (preview_id, bounded_fingerprint, bounded_source, now, expires_at),
            )
        return {
            "preview_id": preview_id,
            "fingerprint": bounded_fingerprint,
            "expires_at": expires_at,
            "approved": False,
        }

    def approve(
        self,
        preview_id: str,
        fingerprint: str,
        *,
        approved: bool,
    ) -> dict[str, str | int | bool]:
        if approved is not True:
            raise RestoreApprovalError("explicit_approval_required")
        if not isinstance(preview_id, str) or not 12 <= len(preview_id) <= 64:
            raise RestoreApprovalError("preview_invalid")
        bounded_fingerprint = _fingerprint(fingerprint)
        now = int(self._now())
        token = secrets.token_urlsafe(32)
        digest = _token_digest(token)
        approval_expires_at = now + APPROVAL_TTL_SECONDS
        with self._lock, self._connect() as conn:
            self._prune(conn, now)
            row = conn.execute(
                "SELECT fingerprint, preview_expires_at, approval_digest, used_at "
                "FROM mindscape_restore_approvals WHERE preview_id = ?",
                (preview_id,),
            ).fetchone()
            if not row or row["preview_expires_at"] <= now:
                raise RestoreApprovalError("preview_expired")
            if row["fingerprint"] != bounded_fingerprint:
                raise RestoreApprovalError("fingerprint_mismatch")
            if row["used_at"] is not None or row["approval_digest"] is not None:
                raise RestoreApprovalError("preview_already_decided")
            conn.execute(
                "UPDATE mindscape_restore_approvals SET approval_digest = ?, "
                "approved_at = ?, approval_expires_at = ? WHERE preview_id = ?",
                (digest, now, approval_expires_at, preview_id),
            )
        return {
            "approval_token": token,
            "fingerprint": bounded_fingerprint,
            "expires_at": approval_expires_at,
            "approved": True,
        }

    def consume(self, token: str, fingerprint: str, source: str) -> str:
        digest = _token_digest(token)
        bounded_fingerprint = _fingerprint(fingerprint)
        bounded_source = _source(source)
        now = int(self._now())
        with self._lock, self._connect() as conn:
            self._prune(conn, now)
            row = conn.execute(
                "SELECT preview_id, fingerprint, source, approval_expires_at, used_at "
                "FROM mindscape_restore_approvals WHERE approval_digest = ?",
                (digest,),
            ).fetchone()
            if not row or row["approval_expires_at"] is None or row["approval_expires_at"] <= now:
                raise RestoreApprovalError("approval_expired")
            if row["used_at"] is not None:
                raise RestoreApprovalError("approval_replayed")
            if row["fingerprint"] != bounded_fingerprint or row["source"] != bounded_source:
                raise RestoreApprovalError("approval_binding_mismatch")
            consumed = conn.execute(
                "UPDATE mindscape_restore_approvals SET used_at = ? "
                "WHERE preview_id = ? AND used_at IS NULL",
                (now, row["preview_id"]),
            )
            if consumed.rowcount != 1:
                raise RestoreApprovalError("approval_replayed")
            return str(row["preview_id"])


__all__ = [
    "APPROVAL_TTL_SECONDS",
    "PREVIEW_TTL_SECONDS",
    "RestoreApprovalError",
    "RestoreApprovalLedger",
]
