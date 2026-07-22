"""Durable creator decisions for exact private-perception egress requests.

The consent ledger asks its authority synchronously immediately before egress.
This adapter turns that call into a two-step creator workflow without retaining
the private payload: the first exact request is denied and listed as pending;
an authenticated creator can approve or deny its content-free binding; the
same operation and bytes may then consume that decision once.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path

from alpecca.egress_consent import AuthorityRequest, CreatorDecision


REQUEST_TTL_SECONDS = 5 * 60
MAX_PENDING_REQUESTS = 32


def _request_key(request: AuthorityRequest) -> str:
    material = json.dumps(
        asdict(request), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(material).hexdigest()


def _decision_id() -> str:
    return "decision_" + secrets.token_urlsafe(24)


class InteractiveCreatorAuthority:
    """One-use, exact-binding authority controlled by authenticated HTTP routes."""

    authority_id = "creator-egress-ui"
    version = 1
    creator_scope = "creator-private"

    def __init__(self, db_path: Path, *, ttl_seconds: int = REQUEST_TTL_SECONDS) -> None:
        self.db_path = Path(db_path)
        self.ttl_seconds = max(30, min(15 * 60, int(ttl_seconds)))
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS interactive_egress_requests (
                    request_key TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','approved','denied','consumed','expired')),
                    route_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    deployment TEXT NOT NULL,
                    model TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    processing_location TEXT NOT NULL,
                    destination_class TEXT NOT NULL,
                    transport_route TEXT NOT NULL,
                    byte_count INTEGER NOT NULL,
                    operation_hmac TEXT NOT NULL,
                    payload_hmac TEXT NOT NULL,
                    decided_at REAL,
                    consumed_at REAL
                )
                """
            )

    def _expire(self, conn: sqlite3.Connection, now: float) -> None:
        conn.execute(
            "UPDATE interactive_egress_requests SET state='expired' "
            "WHERE state IN ('pending','approved','denied') AND expires_at<?",
            (now,),
        )

    def decide(self, request: AuthorityRequest) -> CreatorDecision:
        now = time.time()
        key = _request_key(request)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._expire(conn, now)
            row = conn.execute(
                "SELECT state,expires_at FROM interactive_egress_requests "
                "WHERE request_key=?",
                (key,),
            ).fetchone()
            if row is not None and row["state"] == "approved" and row["expires_at"] >= now:
                conn.execute(
                    "UPDATE interactive_egress_requests SET state='consumed',consumed_at=? "
                    "WHERE request_key=? AND state='approved'",
                    (now, key),
                )
                return CreatorDecision(_decision_id(), True)
            if row is None or row["state"] == "expired":
                request_id = "request_" + secrets.token_urlsafe(24)
                values = asdict(request)
                conn.execute(
                    """
                    INSERT INTO interactive_egress_requests
                    (request_key,request_id,created_at,expires_at,state,route_id,
                     provider,deployment,model,capability,purpose,processing_location,
                     destination_class,transport_route,byte_count,operation_hmac,payload_hmac)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(request_key) DO UPDATE SET
                      request_id=excluded.request_id,created_at=excluded.created_at,
                      expires_at=excluded.expires_at,state='pending',decided_at=NULL,
                      consumed_at=NULL
                    """,
                    (
                        key, request_id, now, now + self.ttl_seconds, "pending",
                        values["route_id"], values["provider"], values["deployment"],
                        values["model"], values["capability"], values["purpose"],
                        values["processing_location"], values["destination_class"],
                        values["transport_route"], values["byte_count"],
                        values["operation_hmac"], values["payload_hmac"],
                    ),
                )
            return CreatorDecision(_decision_id(), False)

    def resolve(self, request_id: str, *, allowed: bool) -> dict[str, object] | None:
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._expire(conn, now)
            row = conn.execute(
                "SELECT * FROM interactive_egress_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row is None or row["state"] != "pending":
                return None
            state = "approved" if allowed else "denied"
            conn.execute(
                "UPDATE interactive_egress_requests SET state=?,decided_at=? "
                "WHERE request_id=? AND state='pending'",
                (state, now, request_id),
            )
        return self.get(request_id)

    def get(self, request_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM interactive_egress_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            return self._public(row) if row is not None else None

    def list_requests(self, *, limit: int = MAX_PENDING_REQUESTS) -> list[dict[str, object]]:
        now = time.time()
        bounded = max(1, min(MAX_PENDING_REQUESTS, int(limit)))
        with self._lock, self._connect() as conn:
            self._expire(conn, now)
            rows = conn.execute(
                "SELECT * FROM interactive_egress_requests "
                "WHERE state IN ('pending','approved','denied') "
                "ORDER BY created_at DESC LIMIT ?",
                (bounded,),
            ).fetchall()
            return [self._public(row) for row in rows]

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, object]:
        return {
            "request_id": row["request_id"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "state": row["state"],
            "route_id": row["route_id"],
            "provider": row["provider"],
            "deployment": row["deployment"],
            "model": row["model"],
            "capability": row["capability"],
            "purpose": row["purpose"],
            "processing_location": row["processing_location"],
            "destination_class": row["destination_class"],
            "transport_route": row["transport_route"],
            "byte_count": row["byte_count"],
        }


__all__ = ["InteractiveCreatorAuthority", "MAX_PENDING_REQUESTS", "REQUEST_TTL_SECONDS"]
