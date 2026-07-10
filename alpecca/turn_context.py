"""Immutable, server-issued chat-turn context for Phase 3 isolation.

The global ``CoreMind`` remains Alpecca's one embodied companion, but a chat
turn may only read or write the conversation scope bound to its authenticated
transport.  This module owns that envelope, its cooperative cancellation gate,
and the durable short-term history store.
"""
from __future__ import annotations

import dataclasses
import json
import re
import threading
import time
import uuid
from pathlib import Path

from config import DB_PATH


_ID_RE = re.compile(r"[^a-zA-Z0-9_.:-]+")
_MAX_ID_LENGTH = 160
_HISTORY_MAX_MESSAGES = 96


def _clean_id(value: str, fallback: str) -> str:
    cleaned = _ID_RE.sub("-", str(value or "").strip()).strip("-._:")
    return (cleaned or fallback)[:_MAX_ID_LENGTH]


class TurnCommitBarrier:
    """Thread-safe cooperative fence for a synchronous worker.

    Python cannot kill an in-flight Ollama call.  The worker therefore checks
    this barrier before every side-effect phase.  A deadline or caller
    cancellation makes the barrier terminal before any late history, memory,
    tool, or chat-record write can begin.
    """

    def __init__(self, deadline_monotonic: float | None = None) -> None:
        self._deadline_monotonic = deadline_monotonic
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._state = "pending"
        self._reason = ""

    @property
    def cancelled(self) -> threading.Event:
        return self._cancelled

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def _deadline_expired_locked(self) -> bool:
        return (
            self._deadline_monotonic is not None
            and time.monotonic() >= self._deadline_monotonic
        )

    def cancel(self, reason: str = "cancelled") -> bool:
        """Fence a still-pending turn. Returns whether this call fenced it."""
        with self._lock:
            if self._state != "pending":
                return False
            self._state = "cancelled"
            self._reason = str(reason or "cancelled")[:80]
            self._cancelled.set()
            return True

    def allow_work(self) -> bool:
        with self._lock:
            if self._state != "pending" or self._cancelled.is_set():
                return False
            if self._deadline_expired_locked():
                self._state = "cancelled"
                self._reason = "deadline"
                self._cancelled.set()
                return False
            return True

    def begin_commit(self) -> bool:
        """Atomically transition a live turn into its final commit phase."""
        with self._lock:
            if self._state != "pending" or self._cancelled.is_set():
                return False
            if self._deadline_expired_locked():
                self._state = "cancelled"
                self._reason = "deadline"
                self._cancelled.set()
                return False
            self._state = "committing"
            return True

    def finish_commit(self) -> None:
        with self._lock:
            if self._state == "committing":
                self._state = "committed"

    def audit(self) -> dict[str, str | bool]:
        return {
            "commit_state": self.state,
            "cancelled": self._cancelled.is_set(),
            "cancel_reason": self.reason,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class TurnContext:
    """Server-owned identity, scope, and cancellation state for one chat turn."""

    turn_id: str
    conversation_id: str
    principal: str
    surface: str
    privacy_scope: str
    portal_epoch: str
    barrier: TurnCommitBarrier = dataclasses.field(repr=False, compare=False)

    @staticmethod
    def create(
        conversation_id: str,
        *,
        principal: str = "creator",
        surface: str = "websocket",
        privacy_scope: str = "",
        portal_epoch: str = "local",
        timeout_s: float | None = None,
    ) -> "TurnContext":
        role = "creator" if principal == "creator" else "guest"
        conversation = _clean_id(conversation_id, "conversation")
        scope = _clean_id(
            privacy_scope or (
                "creator-personal" if role == "creator" else f"guest-{conversation}"
            ),
            "private",
        )
        deadline = None
        if timeout_s is not None:
            deadline = time.monotonic() + max(0.01, float(timeout_s))
        return TurnContext(
            turn_id=uuid.uuid4().hex,
            conversation_id=conversation,
            principal=role,
            surface=_clean_id(surface, "unknown"),
            privacy_scope=scope,
            portal_epoch=_clean_id(portal_epoch, "local"),
            barrier=TurnCommitBarrier(deadline),
        )

    @staticmethod
    def default() -> "TurnContext":
        """Compatibility context for direct core/test callers.

        It is deliberately creator-local, not a route-derived guest context.
        Network entry points must use :meth:`create` with their server-derived
        authorization decision instead.
        """
        return TurnContext.create(
            "default", principal="creator", surface="direct", privacy_scope="shared"
        )

    @property
    def cancelled(self) -> threading.Event:
        return self.barrier.cancelled

    @property
    def scope_key(self) -> str:
        return ":".join((
            "v1", self.privacy_scope, self.principal, self.surface,
            self.portal_epoch, self.conversation_id,
        ))

    @property
    def memory_scope(self) -> str:
        return self.privacy_scope

    def cancel(self, reason: str = "cancelled") -> bool:
        return self.barrier.cancel(reason)

    def allow_work(self) -> bool:
        return self.barrier.allow_work()

    def begin_commit(self) -> bool:
        return self.barrier.begin_commit()

    def finish_commit(self) -> None:
        self.barrier.finish_commit()

    def audit_metadata(self) -> dict[str, str | bool]:
        return {
            "turn_id": self.turn_id,
            "conversation_id": self.conversation_id,
            "principal": self.principal,
            "surface": self.surface,
            "privacy_scope": self.privacy_scope,
            "portal_epoch": self.portal_epoch,
            **self.barrier.audit(),
        }


def ensure_history_schema(db_path: Path = DB_PATH) -> None:
    """Install the compact, scope-keyed rolling-history table idempotently."""
    from alpecca.db import connect

    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversation_histories (
                scope_key       TEXT PRIMARY KEY,
                principal       TEXT NOT NULL,
                surface         TEXT NOT NULL,
                privacy_scope   TEXT NOT NULL,
                portal_epoch    TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                updated_at      REAL NOT NULL,
                history_json    TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS conversation_histories_updated_idx
                ON conversation_histories(updated_at DESC);
            """
        )


def _clean_history(history: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for item in history[-_HISTORY_MAX_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant", "system"} or not content:
            continue
        cleaned.append({"role": role, "content": content[:8000]})
    return cleaned


def load_history(context: TurnContext, db_path: Path = DB_PATH) -> list[dict]:
    ensure_history_schema(db_path)
    from alpecca.db import connect

    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT history_json FROM conversation_histories WHERE scope_key=?",
            (context.scope_key,),
        ).fetchone()
    if not row:
        return []
    try:
        value = json.loads(row["history_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return _clean_history(value if isinstance(value, list) else [])


def save_history(context: TurnContext, history: list[dict], db_path: Path = DB_PATH) -> None:
    """Persist a bounded scope-local history after its turn commits."""
    ensure_history_schema(db_path)
    payload = json.dumps(_clean_history(history), ensure_ascii=True, separators=(",", ":"))
    from alpecca.db import connect

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO conversation_histories
                (scope_key, principal, surface, privacy_scope, portal_epoch,
                 conversation_id, updated_at, history_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scope_key) DO UPDATE SET
                updated_at=excluded.updated_at,
                history_json=excluded.history_json
            """,
            (
                context.scope_key, context.principal, context.surface,
                context.privacy_scope, context.portal_epoch,
                context.conversation_id, time.time(), payload,
            ),
        )


def clear_history(context: TurnContext, db_path: Path = DB_PATH) -> None:
    ensure_history_schema(db_path)
    from alpecca.db import connect

    with connect(db_path) as conn:
        conn.execute("DELETE FROM conversation_histories WHERE scope_key=?", (context.scope_key,))
