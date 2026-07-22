"""Encrypted append-only continuity deltas shared by local and cloud Alpecca.

Full Mindscape Vault archives remain the recovery checkpoint.  This module
captures committed memories and chat turns after that checkpoint so failover
and failback can merge both branches without replacing either database.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterable, Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from alpecca.db import connect
from alpecca.mindscape_vault import VaultError, derive_key, key_id, scope_id
from config import DB_PATH


SCHEMA = "alpecca.continuity.events.v1"
KIND = "events"
ALGORITHM = "AES-256-GCM"
MAX_EVENTS_PER_SEGMENT = 128
MAX_PLAINTEXT_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_NONCE_BYTES = 12
_DOMAIN = b"Alpecca continuity event journal v1\x00"
_suppress_capture: ContextVar[bool] = ContextVar("continuity_capture_suppressed", default=False)


def _json(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VaultError("continuity event must be JSON serializable") from exc


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: object, field: str) -> bytes:
    if not isinstance(value, str) or not value or any(ch.isspace() for ch in value):
        raise VaultError(f"continuity {field} must be base64url text")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise VaultError(f"continuity {field} is not valid base64url") from exc


def _origin() -> str:
    explicit = os.environ.get("ALPECCA_CONTINUITY_ROLE", "").strip()
    if os.environ.get("ALPECCA_CONTINUITY_OFFLINE_ISOLATED") == "1":
        return "offline-local"
    if explicit == "cloud-standby" or os.environ.get("SPACE_HOST"):
        return "cloud-primary"
    return "local-primary"


def _epoch() -> int | None:
    raw = os.environ.get("ALPECCA_CONTINUITY_FENCING_EPOCH", "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def init_db(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS continuity_events (
                event_id       TEXT PRIMARY KEY,
                created_at     REAL NOT NULL,
                origin         TEXT NOT NULL,
                fencing_epoch  INTEGER,
                kind           TEXT NOT NULL,
                scope          TEXT NOT NULL,
                payload        TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                uploaded       INTEGER NOT NULL DEFAULT 0,
                imported       INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS continuity_events_pending_idx
                ON continuity_events(uploaded, created_at, event_id);
            CREATE TABLE IF NOT EXISTS continuity_segments (
                sequence   INTEGER PRIMARY KEY AUTOINCREMENT,
                segment_id TEXT UNIQUE NOT NULL,
                event_ids  TEXT NOT NULL DEFAULT '[]',
                envelope   TEXT NOT NULL,
                created_at REAL NOT NULL,
                attempts   INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS continuity_quarantine (
                event_id   TEXT PRIMARY KEY,
                reason     TEXT NOT NULL,
                event_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            """
        )
        columns = {
            str(row["name"]) for row in conn.execute(
                "PRAGMA table_info(continuity_segments)"
            ).fetchall()
        }
        if "event_ids" not in columns:
            conn.execute(
                "ALTER TABLE continuity_segments "
                "ADD COLUMN event_ids TEXT NOT NULL DEFAULT '[]'"
            )
            # Legacy drafts did not retain exact membership. Pending source
            # events are intact and will be safely resealed on the next flush.
            conn.execute("DELETE FROM continuity_segments")


def capture_event(
    kind: str,
    payload: Mapping[str, object],
    *,
    scope: str = "shared",
    db_path: Path = DB_PATH,
    event_id: str | None = None,
    created_at: float | None = None,
    origin: str | None = None,
    fencing_epoch: int | None = None,
    imported: bool = False,
) -> str | None:
    """Persist one immutable committed event; capture failures never undo work."""
    if _suppress_capture.get() and not imported:
        return None
    clean_kind = str(kind or "").strip()[:64]
    clean_scope = str(scope or "shared").strip()[:160] or "shared"
    if clean_kind not in {"memory", "chat_turn", "game_episode"}:
        return None
    raw = _json(dict(payload))
    if len(raw) > 512 * 1024:
        return None
    eid = event_id or secrets.token_hex(16)
    if len(eid) != 32:
        return None
    try:
        int(eid, 16)
    except ValueError:
        return None
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO continuity_events "
            "(event_id, created_at, origin, fencing_epoch, kind, scope, payload, "
            "payload_sha256, uploaded, imported) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                eid, float(created_at or time.time()), origin or _origin(),
                fencing_epoch if fencing_epoch is not None else _epoch(), clean_kind,
                clean_scope, raw.decode("utf-8"), hashlib.sha256(raw).hexdigest(),
                1 if imported else 0, 1 if imported else 0,
            ),
        )
    return eid


def pending_count(db_path: Path = DB_PATH) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM continuity_events WHERE uploaded=0"
        ).fetchone()[0])


def _event_rows(db_path: Path, limit: int) -> list[dict[str, object]]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT event_id, created_at, origin, fencing_epoch, kind, scope, "
            "payload, payload_sha256 FROM continuity_events WHERE uploaded=0 "
            "ORDER BY created_at, event_id LIMIT ?",
            (max(1, min(MAX_EVENTS_PER_SEGMENT, int(limit))),),
        ).fetchall()
    events: list[dict[str, object]] = []
    for row in rows:
        event = dict(row)
        event["payload"] = json.loads(str(event["payload"]))
        events.append(event)
    return events


def _stored_pending_envelope(db_path: Path) -> dict[str, object] | None:
    """Reuse the oldest valid sealed batch and discard only exact duplicates.

    A transport failure must not reseal the same pending events on every retry.
    Besides wasting disk, hundreds of duplicate encrypted envelopes make every
    foreground SQLite write contend with a needlessly large database.
    """
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT sequence, event_ids, envelope FROM continuity_segments "
            "ORDER BY sequence"
        ).fetchall()
        seen_batches: set[str] = set()
        selected: dict[str, object] | None = None
        for row in rows:
            sequence = int(row["sequence"])
            batch = str(row["event_ids"])
            if batch in seen_batches:
                conn.execute(
                    "DELETE FROM continuity_segments WHERE sequence=?", (sequence,)
                )
                continue
            seen_batches.add(batch)
            try:
                event_ids = json.loads(batch)
                envelope = json.loads(str(row["envelope"]))
            except json.JSONDecodeError:
                conn.execute(
                    "DELETE FROM continuity_segments WHERE sequence=?", (sequence,)
                )
                continue
            if not isinstance(event_ids, list) or not event_ids or not isinstance(envelope, dict):
                conn.execute(
                    "DELETE FROM continuity_segments WHERE sequence=?", (sequence,)
                )
                continue
            placeholders = ",".join("?" for _ in event_ids)
            pending = conn.execute(
                f"SELECT COUNT(*) FROM continuity_events "
                f"WHERE uploaded=0 AND event_id IN ({placeholders})",
                tuple(str(event_id) for event_id in event_ids),
            ).fetchone()[0]
            if not pending:
                conn.execute(
                    "DELETE FROM continuity_segments WHERE sequence=?", (sequence,)
                )
                continue
            if selected is None:
                selected = dict(envelope)
        return selected


def _aad(header: Mapping[str, object]) -> bytes:
    return _json({name: header[name] for name in (
        "schema", "kind", "algorithm", "scope", "key_id", "segment_id",
        "created_at", "event_count", "compression",
    )})


def seal_pending(
    secret: str | bytes,
    *,
    db_path: Path = DB_PATH,
    limit: int = MAX_EVENTS_PER_SEGMENT,
) -> dict[str, object] | None:
    stored = _stored_pending_envelope(db_path)
    if stored is not None:
        return stored
    events = _event_rows(db_path, limit)
    if not events:
        return None
    plaintext = _json({"events": events})
    if len(plaintext) > MAX_PLAINTEXT_BYTES:
        raise VaultError("continuity event segment exceeds the plaintext limit")
    segment_id = secrets.token_hex(16)
    header: dict[str, object] = {
        "schema": SCHEMA, "kind": KIND, "algorithm": ALGORITHM,
        "scope": scope_id(secret), "key_id": key_id(secret),
        "segment_id": segment_id, "created_at": round(time.time(), 6),
        "event_count": len(events), "compression": "zlib",
    }
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(derive_key(secret)).encrypt(
        nonce, zlib.compress(plaintext, level=6), _DOMAIN + _aad(header),
    )
    envelope = {
        **header, "nonce": _b64(nonce), "ciphertext": _b64(ciphertext),
        "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest(),
        "plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
    }
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO continuity_segments "
            "(segment_id, event_ids, envelope, created_at) VALUES (?, ?, ?, ?)",
            (
                segment_id,
                _json([str(event["event_id"]) for event in events]).decode("utf-8"),
                _json(envelope).decode("utf-8"),
                time.time(),
            ),
        )
    return envelope


def unseal_segment(envelope: Mapping[str, object], secret: str | bytes) -> list[dict[str, object]]:
    expected = {
        "schema", "kind", "algorithm", "scope", "key_id", "segment_id",
        "created_at", "event_count", "compression", "nonce", "ciphertext",
        "ciphertext_sha256", "plaintext_sha256",
    }
    if set(envelope) != expected or envelope.get("schema") != SCHEMA:
        raise VaultError("continuity segment schema is invalid")
    if envelope.get("kind") != KIND or envelope.get("algorithm") != ALGORITHM:
        raise VaultError("continuity segment algorithm is invalid")
    if envelope.get("scope") != scope_id(secret) or envelope.get("key_id") != key_id(secret):
        raise VaultError("continuity segment belongs to a different recovery key")
    segment_id = str(envelope.get("segment_id") or "")
    if len(segment_id) != 32:
        raise VaultError("continuity segment identifier is invalid")
    nonce = _unb64(envelope.get("nonce"), "nonce")
    ciphertext = _unb64(envelope.get("ciphertext"), "ciphertext")
    if len(nonce) != _NONCE_BYTES or hashlib.sha256(ciphertext).hexdigest() != envelope.get("ciphertext_sha256"):
        raise VaultError("continuity segment ciphertext is invalid")
    header = {name: envelope[name] for name in (
        "schema", "kind", "algorithm", "scope", "key_id", "segment_id",
        "created_at", "event_count", "compression",
    )}
    try:
        compressed = AESGCM(derive_key(secret)).decrypt(
            nonce, ciphertext, _DOMAIN + _aad(header),
        )
        plaintext = zlib.decompress(compressed)
    except (InvalidTag, zlib.error) as exc:
        raise VaultError("continuity segment authentication failed") from exc
    if len(plaintext) > MAX_PLAINTEXT_BYTES or hashlib.sha256(plaintext).hexdigest() != envelope.get("plaintext_sha256"):
        raise VaultError("continuity segment plaintext is invalid")
    try:
        body = json.loads(plaintext)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VaultError("continuity segment plaintext is not JSON") from exc
    events = body.get("events") if isinstance(body, dict) else None
    if not isinstance(events, list) or len(events) != envelope.get("event_count"):
        raise VaultError("continuity segment event count is invalid")
    return [dict(event) for event in events if isinstance(event, dict)]


@contextmanager
def suppress_capture():
    token = _suppress_capture.set(True)
    try:
        yield
    finally:
        _suppress_capture.reset(token)


def _quarantine(event: Mapping[str, object], reason: str, db_path: Path) -> None:
    event_id = str(event.get("event_id") or secrets.token_hex(16))[:32]
    with connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO continuity_quarantine "
            "(event_id, reason, event_json, created_at) VALUES (?, ?, ?, ?)",
            (event_id, reason[:160], _json(dict(event)).decode("utf-8"), time.time()),
        )


def _validate_event(event: Mapping[str, object]) -> tuple[str, str, dict[str, object]]:
    event_id = str(event.get("event_id") or "")
    if len(event_id) != 32:
        raise VaultError("event identifier is invalid")
    int(event_id, 16)
    kind = str(event.get("kind") or "")
    scope = str(event.get("scope") or "shared")[:160]
    payload = event.get("payload")
    if kind not in {"memory", "chat_turn", "game_episode"} or not isinstance(payload, Mapping):
        raise VaultError("event payload is unsupported")
    raw = _json(dict(payload))
    if hashlib.sha256(raw).hexdigest() != event.get("payload_sha256"):
        raise VaultError("event payload checksum does not match")
    return event_id, scope, dict(payload)


def merge_events(events: Iterable[Mapping[str, object]], *, db_path: Path = DB_PATH) -> dict[str, int]:
    """Idempotently merge supported records; quarantine anything ambiguous."""
    from alpecca import cognition as cognition_mod
    from alpecca import state as state_mod

    state_mod.init_db(db_path)
    cognition_mod.init_db(db_path)
    init_db(db_path)
    merged = duplicate = quarantined = 0
    for event in events:
        try:
            event_id, scope, payload = _validate_event(event)
        except (VaultError, ValueError):
            _quarantine(event, "invalid_event", db_path)
            quarantined += 1
            continue
        with connect(db_path) as conn:
            if conn.execute(
                "SELECT 1 FROM continuity_events WHERE event_id=?", (event_id,)
            ).fetchone():
                duplicate += 1
                continue
        try:
            with suppress_capture(), connect(db_path) as conn:
                if event.get("kind") in {"memory", "game_episode"}:
                    content = str(payload.get("content") or "").strip()
                    if not content:
                        raise VaultError("memory content is empty")
                    kind = "episodic" if event.get("kind") == "game_episode" else str(payload.get("kind") or "episodic")
                    tokens = payload.get("tokens")
                    if not isinstance(tokens, str):
                        tokens = json.dumps(payload.get("token_list") or [])
                    conn.execute(
                        "INSERT INTO memories (ts, kind, content, salience, tokens, embedding, scope) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (float(payload.get("ts") or event.get("created_at") or time.time()),
                         kind[:64], content, max(0.0, min(1.0, float(payload.get("salience") or 0.5))),
                         tokens, payload.get("embedding"), scope),
                    )
                elif event.get("kind") == "chat_turn":
                    user_text = str(payload.get("user_text") or "").strip()
                    reply = str(payload.get("reply") or "").strip()
                    if not user_text or not reply:
                        raise VaultError("chat turn is incomplete")
                    conn.execute(
                        "INSERT INTO chat_turns (ts, room, mood, intent, user_text, reply, "
                        "model_use, memory_evidence, observation_id, privacy_class, scope) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                        (float(payload.get("ts") or event.get("created_at") or time.time()),
                         str(payload.get("room") or "")[:64], str(payload.get("mood") or "")[:64],
                         str(payload.get("intent") or "")[:64], user_text, reply,
                         json.dumps(payload.get("model_use") or {}, ensure_ascii=True),
                         json.dumps(payload.get("memory_evidence") or [], ensure_ascii=True),
                         str(payload.get("privacy_class") or scope)[:160], scope),
                    )
            capture_event(
                str(event.get("kind")), payload, scope=scope, db_path=db_path,
                event_id=event_id, created_at=float(event.get("created_at") or time.time()),
                origin=str(event.get("origin") or "remote")[:64],
                fencing_epoch=event.get("fencing_epoch") if isinstance(event.get("fencing_epoch"), int) else None,
                imported=True,
            )
            merged += 1
        except (VaultError, ValueError, TypeError):
            _quarantine(event, "merge_rejected", db_path)
            quarantined += 1
    return {"merged": merged, "duplicates": duplicate, "quarantined": quarantined}


def mark_segment_uploaded(envelope: Mapping[str, object], *, db_path: Path = DB_PATH) -> None:
    segment_id = str(envelope.get("segment_id") or "")
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT event_ids FROM continuity_segments WHERE segment_id=?", (segment_id,)
        ).fetchone()
        if row is None:
            return
        try:
            event_ids = json.loads(str(row["event_ids"]))
        except json.JSONDecodeError:
            return
        if not isinstance(event_ids, list) or not event_ids:
            return
        placeholders = ",".join("?" for _ in event_ids)
        conn.execute(
            f"UPDATE continuity_events SET uploaded=1 WHERE event_id IN ({placeholders})",
            tuple(str(event_id) for event_id in event_ids),
        )
        # Earlier versions could seal the same event batch again after every
        # failed transport attempt. A successful acknowledgement settles every
        # byte-identical batch row, not just the one envelope that was retried.
        conn.execute("DELETE FROM continuity_segments WHERE event_ids=?", (str(row["event_ids"]),))


def endpoint(cloud_url: str, path: str) -> str:
    base = str(cloud_url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
        raise VaultError("continuity journal URL must use HTTPS")
    for suffix in ("/v1/events", "/v1/events/latest"):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
    if base.endswith("/v1"):
        return base + path
    return base + "/v1" + path


def _headers(token: str, secret: str | bytes, *, lease: Mapping[str, object] | None = None) -> dict[str, str]:
    if len(str(token or "").strip()) < 16:
        raise VaultError("continuity journal token is not configured")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Alpecca-Mindscape-Vault-Token": str(token),
        "X-Alpecca-Mindscape-Vault-Scope": scope_id(secret),
        "Content-Type": "application/json",
    }
    if lease:
        headers.update({
            "X-Alpecca-Lease-Id": str(lease.get("lease_id") or ""),
            "X-Alpecca-Fencing-Epoch": str(lease.get("fencing_epoch") or ""),
            "X-Alpecca-Lease-Holder": str(lease.get("holder") or ""),
        })
    return headers


def flush_pending(
    cloud_url: str, token: str, secret: str | bytes, *,
    lease: Mapping[str, object], db_path: Path = DB_PATH,
    timeout: float = 8.0, opener=None,
) -> dict[str, object]:
    if not lease.get("lease_id") or not lease.get("fencing_epoch") or not lease.get("holder"):
        return {"ok": False, "status": "lease_required", "pending": pending_count(db_path)}
    envelope = seal_pending(secret, db_path=db_path)
    if envelope is None:
        return {"ok": True, "status": "idle", "pending": 0}
    request = urllib.request.Request(
        endpoint(cloud_url, "/events"), data=_json({"envelope": envelope}),
        headers=_headers(token, secret, lease=lease), method="POST",
    )
    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            body = json.loads(response.read(64 * 1024).decode("utf-8") or "{}")
            ok = 200 <= int(getattr(response, "status", 200)) < 300 and body.get("ok") is True
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "status": "transport_failed", "message": type(exc).__name__, "pending": pending_count(db_path)}
    if ok:
        mark_segment_uploaded(envelope, db_path=db_path)
    return {"ok": ok, "status": str(body.get("status") or "rejected"), "pending": pending_count(db_path)}


def fetch_segments(
    cloud_url: str, token: str, secret: str | bytes, *,
    timeout: float = 8.0, opener=None,
) -> dict[str, object]:
    request = urllib.request.Request(
        endpoint(cloud_url, "/events/latest"),
        headers=_headers(token, secret), method="GET",
    )
    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"ok": True, "status": "empty", "envelopes": []}
        return {"ok": False, "status": "rejected", "envelopes": []}
    except (OSError, urllib.error.URLError, TimeoutError):
        return {"ok": False, "status": "transport_failed", "envelopes": []}
    if len(raw) > MAX_RESPONSE_BYTES:
        return {"ok": False, "status": "response_too_large", "envelopes": []}
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
        envelopes = body.get("envelopes")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "status": "invalid_response", "envelopes": []}
    if not isinstance(envelopes, list):
        return {"ok": False, "status": "invalid_response", "envelopes": []}
    return {"ok": True, "status": "fetched", "envelopes": envelopes}


def fetch_and_merge(
    cloud_url: str, token: str, secret: str | bytes, *,
    db_path: Path = DB_PATH, timeout: float = 8.0, opener=None,
) -> dict[str, object]:
    fetched = fetch_segments(cloud_url, token, secret, timeout=timeout, opener=opener)
    if not fetched.get("ok"):
        return fetched
    totals = {"merged": 0, "duplicates": 0, "quarantined": 0}
    for envelope in fetched.get("envelopes", []):
        try:
            events = unseal_segment(envelope, secret)
        except VaultError:
            totals["quarantined"] += 1
            continue
        result = merge_events(events, db_path=db_path)
        for key in totals:
            totals[key] += result[key]
    return {"ok": totals["quarantined"] == 0, "status": "merged", **totals}


__all__ = [
    "SCHEMA", "capture_event", "fetch_and_merge", "fetch_segments", "flush_pending",
    "init_db", "merge_events", "pending_count", "seal_pending", "suppress_capture",
    "unseal_segment",
]
