"""Encrypted, immutable cloud-recovery records for Alpecca Mindscape.

Mindscape Vault is deliberately a backup boundary, not a remote CoreMind.  The
local host builds a continuity projection or a validated SQLite recovery image,
encrypts it before transport, and keeps a small durable outbox for retries.
The cloud worker sees opaque ciphertext only.  Restoring remains an explicit
local action; this module never starts a second conversational instance.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path
from typing import Any, Callable, Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from alpecca.db import connect
from alpecca.sqlite_backup import SQLiteBackupError, snapshot_database
from config import DB_PATH, HOME


VAULT_SCHEMA = "alpecca.mindscape.vault.v1"
VAULT_ALGORITHM = "AES-256-GCM"
SNAPSHOT_KIND = "snapshot"
ARCHIVE_KIND = "sqlite"
VAULT_KEY_ENV = "ALPECCA_MINDSCAPE_VAULT_KEY"
VAULT_KEY_CREDENTIAL_TARGET = "Alpecca/MindscapeVaultEncryptionKey"
VAULT_TOKEN_ENV = "ALPECCA_MINDSCAPE_VAULT_TOKEN"
VAULT_TOKEN_CREDENTIAL_TARGET = "Alpecca/MindscapeVaultTransportToken"
MAX_SNAPSHOT_PLAINTEXT_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOT_CIPHERTEXT_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_BYTES = 96 * 1024 * 1024
DEFAULT_OUTBOX_LIMIT = 12
DEFAULT_ARCHIVE_OUTBOX_LIMIT = 2
_NONCE_BYTES = 12
_KEY_DOMAIN = b"Alpecca Mindscape Vault AES-256-GCM v1\x00"
_SCOPE_DOMAIN = b"Alpecca Mindscape Vault scope v1\x00"
_MAX_RESPONSE_BYTES = 64 * 1024
_ARCHIVE_FILE_RE = re.compile(r"^archive-[0-9]{20}-[0-9a-f]{16}\.bin$")


class VaultError(ValueError):
    """Raised when a vault record is invalid or cannot be safely handled."""


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VaultError("vault data must be JSON serializable") from exc


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: object, *, field: str, expected_length: int | None = None) -> bytes:
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        raise VaultError(f"vault {field} must be base64url text")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise VaultError(f"vault {field} is not valid base64url") from exc
    if expected_length is not None and len(decoded) != expected_length:
        raise VaultError(f"vault {field} has an invalid length")
    return decoded


def _secret_bytes(secret: str | bytes) -> bytes:
    if isinstance(secret, str):
        raw = secret.encode("utf-8")
    elif isinstance(secret, bytes):
        raw = secret
    else:
        raise VaultError("vault encryption key must be text or bytes")
    if len(raw) < 32:
        raise VaultError("vault encryption key must contain at least 32 bytes")
    return raw


def derive_key(secret: str | bytes) -> bytes:
    """Domain-separate a caller-provided recovery secret into an AES-256 key."""
    return hashlib.sha256(_KEY_DOMAIN + _secret_bytes(secret)).digest()


def scope_id(secret: str | bytes) -> str:
    """Return an opaque stable namespace without exposing the recovery key."""
    return hashlib.sha256(_SCOPE_DOMAIN + derive_key(secret)).hexdigest()[:32]


def key_id(secret: str | bytes) -> str:
    """Short non-secret identifier used only for recovery diagnostics."""
    return hashlib.sha256(b"key-id\x00" + derive_key(secret)).hexdigest()[:24]


def load_or_create_encryption_key(
    environ: Mapping[str, str] | None = None,
    *,
    credential_target: str = VAULT_KEY_CREDENTIAL_TARGET,
) -> tuple[bytes, str]:
    """Load the dedicated recovery key without exposing it in source or logs.

    A supplied base64url environment secret is useful for a new recovery host.
    The normal Windows path stores a generated 32-byte key in Credential
    Manager.  It is intentionally separate from every transport/auth secret.
    """
    env = os.environ if environ is None else environ
    supplied = env.get(VAULT_KEY_ENV)
    if supplied:
        return _b64decode(supplied, field="encryption key", expected_length=32), "environment"
    if os.name != "nt":
        raise VaultError(f"{VAULT_KEY_ENV} is required outside Windows")
    try:
        import win32cred
    except ImportError as exc:  # pragma: no cover - Windows deployment guard
        raise VaultError("Windows Credential Manager support requires pywin32") from exc

    def decode(blob: object) -> str:
        if isinstance(blob, memoryview):
            blob = blob.tobytes()
        if isinstance(blob, bytes):
            encoding = "utf-16-le" if b"\x00" in blob else "utf-8"
            return blob.decode(encoding).rstrip("\x00")
        if isinstance(blob, str):
            return blob
        return ""

    try:
        credential = win32cred.CredRead(credential_target, win32cred.CRED_TYPE_GENERIC, 0)
        stored = decode(credential.get("CredentialBlob"))
        return _b64decode(stored, field="stored encryption key", expected_length=32), "credential_manager"
    except Exception as exc:
        code = getattr(exc, "winerror", None)
        if code not in {2, 1168} and not (getattr(exc, "args", None) and exc.args[0] in {2, 1168}):
            raise VaultError("could not read the Mindscape Vault recovery key") from exc

    generated = _b64encode(os.urandom(32))
    try:
        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": credential_target,
                "CredentialBlob": generated,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                "UserName": "Alpecca",
                "Comment": "Alpecca Mindscape Vault encryption key",
            },
            0,
        )
        credential = win32cred.CredRead(credential_target, win32cred.CRED_TYPE_GENERIC, 0)
        stored = decode(credential.get("CredentialBlob"))
    except Exception as exc:  # pragma: no cover - operating system failure
        raise VaultError("could not store the Mindscape Vault recovery key") from exc
    return _b64decode(stored, field="stored encryption key", expected_length=32), "credential_manager"


def load_or_create_transport_token(
    environ: Mapping[str, str] | None = None,
    *,
    credential_target: str = VAULT_TOKEN_CREDENTIAL_TARGET,
) -> tuple[str, str]:
    """Load the Vault Worker bearer token without placing it in source.

    The token only authorizes writes to the opaque Vault Worker.  It is not a
    recovery key and cannot decrypt any archive.  A recovery machine can pass
    it through its environment; the primary Windows host otherwise retains a
    generated high-entropy token in Credential Manager.
    """
    env = os.environ if environ is None else environ
    supplied = str(env.get(VAULT_TOKEN_ENV) or "").strip()
    if supplied:
        if len(supplied.encode("utf-8")) < 32:
            raise VaultError("vault transport token must contain at least 32 bytes")
        return supplied, "environment"
    if os.name != "nt":
        raise VaultError(f"{VAULT_TOKEN_ENV} is required outside Windows")
    try:
        import win32cred
    except ImportError as exc:  # pragma: no cover - Windows deployment guard
        raise VaultError("Windows Credential Manager support requires pywin32") from exc

    def decode(blob: object) -> str:
        if isinstance(blob, memoryview):
            blob = blob.tobytes()
        if isinstance(blob, bytes):
            encoding = "utf-16-le" if b"\x00" in blob else "utf-8"
            return blob.decode(encoding).rstrip("\x00")
        if isinstance(blob, str):
            return blob
        return ""

    try:
        credential = win32cred.CredRead(credential_target, win32cred.CRED_TYPE_GENERIC, 0)
        stored = decode(credential.get("CredentialBlob"))
        if len(stored.encode("utf-8")) < 32:
            raise VaultError("stored vault transport token is too short")
        return stored, "credential_manager"
    except VaultError:
        raise
    except Exception as exc:
        code = getattr(exc, "winerror", None)
        if code not in {2, 1168} and not (getattr(exc, "args", None) and exc.args[0] in {2, 1168}):
            raise VaultError("could not read the Mindscape Vault transport token") from exc

    generated = secrets.token_urlsafe(48)
    try:
        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": credential_target,
                "CredentialBlob": generated,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                "UserName": "Alpecca",
                "Comment": "Alpecca Mindscape Vault transport token",
            },
            0,
        )
        credential = win32cred.CredRead(credential_target, win32cred.CRED_TYPE_GENERIC, 0)
        stored = decode(credential.get("CredentialBlob"))
    except Exception as exc:  # pragma: no cover - operating system failure
        raise VaultError("could not store the Mindscape Vault transport token") from exc
    if len(stored.encode("utf-8")) < 32:
        raise VaultError("stored vault transport token is too short")
    return stored, "credential_manager"


def _valid_identifier(value: object) -> str:
    if not isinstance(value, str) or len(value) != 32:
        raise VaultError("vault identifier is invalid")
    try:
        int(value, 16)
    except ValueError as exc:
        raise VaultError("vault identifier is invalid") from exc
    return value.lower()


def _positive_sequence(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 9_223_372_036_854_775_807:
        raise VaultError("vault sequence is invalid")
    return value


def _numeric_timestamp(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VaultError(f"vault {field} is invalid")
    number = float(value)
    if number <= 0 or number > 4_102_444_800:
        raise VaultError(f"vault {field} is invalid")
    return number


def _snapshot_header(snapshot: Mapping[str, object], *, secret: str | bytes, writer_id: str,
                     sequence: int, created_at: float | None = None) -> dict[str, object]:
    return {
        "schema": VAULT_SCHEMA,
        "kind": SNAPSHOT_KIND,
        "algorithm": VAULT_ALGORITHM,
        "scope": scope_id(secret),
        "key_id": key_id(secret),
        "writer_id": _valid_identifier(writer_id),
        "sequence": _positive_sequence(sequence),
        "created_at": round(time.time() if created_at is None else float(created_at), 6),
        "snapshot_ts": round(float(snapshot.get("ts") or time.time()), 6),
        "compression": "zlib",
    }


def _snapshot_aad(header: Mapping[str, object]) -> bytes:
    return _canonical_json({
        name: header[name]
        for name in (
            "schema", "kind", "algorithm", "scope", "key_id", "writer_id",
            "sequence", "created_at", "snapshot_ts", "compression",
        )
    })


def seal_snapshot(
    snapshot: Mapping[str, object],
    secret: str | bytes,
    *,
    writer_id: str,
    sequence: int,
    created_at: float | None = None,
) -> dict[str, object]:
    """Encrypt one compact continuity snapshot into a strict opaque envelope."""
    if not isinstance(snapshot, Mapping):
        raise VaultError("Mindscape snapshot must be an object")
    plaintext = _canonical_json(dict(snapshot))
    if len(plaintext) > MAX_SNAPSHOT_PLAINTEXT_BYTES:
        raise VaultError("Mindscape snapshot exceeds the vault plaintext limit")
    header = _snapshot_header(
        snapshot, secret=secret, writer_id=writer_id, sequence=sequence, created_at=created_at
    )
    nonce = os.urandom(_NONCE_BYTES)
    compressed = zlib.compress(plaintext, level=6)
    ciphertext = AESGCM(derive_key(secret)).encrypt(nonce, compressed, _snapshot_aad(header))
    if len(ciphertext) > MAX_SNAPSHOT_CIPHERTEXT_BYTES:
        raise VaultError("Mindscape snapshot exceeds the vault ciphertext limit")
    return {
        **header,
        "nonce": _b64encode(nonce),
        "ciphertext": _b64encode(ciphertext),
        "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest(),
        "plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
    }


def validate_snapshot_envelope(envelope: Mapping[str, object]) -> dict[str, object]:
    """Validate public envelope fields without decrypting the private payload."""
    if not isinstance(envelope, Mapping):
        raise VaultError("vault envelope must be an object")
    expected = {
        "schema", "kind", "algorithm", "scope", "key_id", "writer_id", "sequence",
        "created_at", "snapshot_ts", "compression", "nonce", "ciphertext",
        "ciphertext_sha256", "plaintext_sha256",
    }
    if set(envelope) != expected:
        raise VaultError("vault envelope fields are invalid")
    if envelope.get("schema") != VAULT_SCHEMA or envelope.get("kind") != SNAPSHOT_KIND:
        raise VaultError("vault envelope schema is invalid")
    if envelope.get("algorithm") != VAULT_ALGORITHM or envelope.get("compression") != "zlib":
        raise VaultError("vault envelope algorithm is invalid")
    normalized = dict(envelope)
    normalized["scope"] = _valid_identifier(normalized["scope"])
    if not isinstance(normalized.get("key_id"), str) or len(normalized["key_id"]) != 24:
        raise VaultError("vault key identifier is invalid")
    normalized["writer_id"] = _valid_identifier(normalized["writer_id"])
    normalized["sequence"] = _positive_sequence(normalized["sequence"])
    normalized["created_at"] = _numeric_timestamp(normalized["created_at"], field="created_at")
    normalized["snapshot_ts"] = _numeric_timestamp(normalized["snapshot_ts"], field="snapshot_ts")
    nonce = _b64decode(normalized["nonce"], field="nonce", expected_length=_NONCE_BYTES)
    ciphertext = _b64decode(normalized["ciphertext"], field="ciphertext")
    if len(ciphertext) < 17 or len(ciphertext) > MAX_SNAPSHOT_CIPHERTEXT_BYTES:
        raise VaultError("vault ciphertext has an invalid length")
    for field in ("ciphertext_sha256", "plaintext_sha256"):
        value = normalized.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise VaultError(f"vault {field} is invalid")
        try:
            int(value, 16)
        except ValueError as exc:
            raise VaultError(f"vault {field} is invalid") from exc
    if hashlib.sha256(ciphertext).hexdigest() != normalized["ciphertext_sha256"]:
        raise VaultError("vault ciphertext checksum does not match")
    # Force all binary field validation before returning public metadata.
    normalized["nonce"] = _b64encode(nonce)
    normalized["ciphertext"] = _b64encode(ciphertext)
    return normalized


def _bounded_decompress(value: bytes) -> bytes:
    decompressor = zlib.decompressobj()
    chunks: list[bytes] = []
    remaining = value
    total = 0
    while remaining:
        chunk = decompressor.decompress(remaining, MAX_SNAPSHOT_PLAINTEXT_BYTES - total + 1)
        total += len(chunk)
        if total > MAX_SNAPSHOT_PLAINTEXT_BYTES:
            raise VaultError("vault plaintext exceeds the allowed size")
        chunks.append(chunk)
        remaining = decompressor.unconsumed_tail
        if not remaining:
            break
    tail = decompressor.flush(MAX_SNAPSHOT_PLAINTEXT_BYTES - total + 1)
    total += len(tail)
    if total > MAX_SNAPSHOT_PLAINTEXT_BYTES or decompressor.unused_data:
        raise VaultError("vault plaintext exceeds the allowed size")
    chunks.append(tail)
    return b"".join(chunks)


def unseal_snapshot(envelope: Mapping[str, object], secret: str | bytes) -> dict[str, object]:
    """Decrypt and validate a cloud envelope before it reaches restore logic."""
    normalized = validate_snapshot_envelope(envelope)
    if normalized["scope"] != scope_id(secret) or normalized["key_id"] != key_id(secret):
        raise VaultError("vault envelope belongs to a different recovery key")
    header = {name: normalized[name] for name in (
        "schema", "kind", "algorithm", "scope", "key_id", "writer_id", "sequence",
        "created_at", "snapshot_ts", "compression",
    )}
    ciphertext = _b64decode(normalized["ciphertext"], field="ciphertext")
    nonce = _b64decode(normalized["nonce"], field="nonce", expected_length=_NONCE_BYTES)
    try:
        compressed = AESGCM(derive_key(secret)).decrypt(nonce, ciphertext, _snapshot_aad(header))
    except InvalidTag as exc:
        raise VaultError("vault ciphertext authentication failed") from exc
    plaintext = _bounded_decompress(compressed)
    if hashlib.sha256(plaintext).hexdigest() != normalized["plaintext_sha256"]:
        raise VaultError("vault plaintext checksum does not match")
    try:
        snapshot = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VaultError("vault plaintext is not valid JSON") from exc
    if not isinstance(snapshot, dict) or snapshot.get("name") != "Alpecca Mindscape":
        raise VaultError("vault payload is not an Alpecca Mindscape snapshot")
    return snapshot


def init_db(db_path: Path = DB_PATH) -> None:
    """Create the local writer/outbox state without storing an encryption key."""
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS mindscape_vault_state (
                id                    INTEGER PRIMARY KEY CHECK(id=1),
                writer_id             TEXT NOT NULL,
                next_sequence         INTEGER NOT NULL,
                last_success_sequence INTEGER NOT NULL DEFAULT 0,
                last_success_ts       REAL NOT NULL DEFAULT 0,
                last_archive_ts       REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS mindscape_vault_outbox (
                sequence   INTEGER PRIMARY KEY,
                envelope   TEXT NOT NULL,
                created_at REAL NOT NULL,
                attempts   INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS mindscape_vault_archives (
                sequence   INTEGER PRIMARY KEY,
                path       TEXT NOT NULL,
                metadata   TEXT NOT NULL,
                created_at REAL NOT NULL,
                attempts   INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT ''
            );
            """
        )


def _writer_state(conn) -> dict[str, object]:
    row = conn.execute("SELECT * FROM mindscape_vault_state WHERE id=1").fetchone()
    if row is None:
        writer = secrets.token_hex(16)
        conn.execute(
            "INSERT INTO mindscape_vault_state (id, writer_id, next_sequence) VALUES (1, ?, 1)",
            (writer,),
        )
        return {"writer_id": writer, "next_sequence": 1, "last_success_sequence": 0,
                "last_success_ts": 0.0, "last_archive_ts": 0.0}
    return dict(row)


def _reserve_sequence(conn) -> tuple[str, int]:
    state = _writer_state(conn)
    writer_id = _valid_identifier(state["writer_id"])
    sequence = _positive_sequence(int(state["next_sequence"]))
    conn.execute("UPDATE mindscape_vault_state SET next_sequence=? WHERE id=1", (sequence + 1,))
    return writer_id, sequence


def local_status(db_path: Path = DB_PATH) -> dict[str, object]:
    init_db(db_path)
    with connect(db_path) as conn:
        state = _writer_state(conn)
        pending_snapshots = int(conn.execute("SELECT COUNT(*) FROM mindscape_vault_outbox").fetchone()[0])
        pending_archives = int(conn.execute("SELECT COUNT(*) FROM mindscape_vault_archives").fetchone()[0])
    return {
        "writer_id": state["writer_id"],
        "next_sequence": int(state["next_sequence"]),
        "last_success_sequence": int(state["last_success_sequence"]),
        "last_success_ts": float(state["last_success_ts"]),
        "last_archive_ts": float(state["last_archive_ts"]),
        "pending_snapshots": pending_snapshots,
        "pending_archives": pending_archives,
    }


def enqueue_snapshot(
    snapshot: Mapping[str, object],
    secret: str | bytes,
    *,
    db_path: Path = DB_PATH,
    max_pending: int = DEFAULT_OUTBOX_LIMIT,
) -> dict[str, object]:
    """Seal and queue a snapshot before any network attempt.

    Retaining an encrypted outbox means a transient outage cannot silently drop
    the most recent continuity state.  Sequence gaps are intentional and safe:
    cloud records are immutable, and retrieval selects the newest sequence.
    """
    bounded = max(1, min(64, int(max_pending)))
    init_db(db_path)
    with connect(db_path) as conn:
        writer_id, sequence = _reserve_sequence(conn)
        envelope = seal_snapshot(snapshot, secret, writer_id=writer_id, sequence=sequence)
        conn.execute(
            "INSERT INTO mindscape_vault_outbox (sequence, envelope, created_at) VALUES (?, ?, ?)",
            (sequence, _canonical_json(envelope).decode("utf-8"), time.time()),
        )
        conn.execute(
            "DELETE FROM mindscape_vault_outbox WHERE sequence NOT IN "
            "(SELECT sequence FROM mindscape_vault_outbox ORDER BY sequence DESC LIMIT ?)",
            (bounded,),
        )
    return envelope


def _vault_base_url(cloud_url: str) -> str:
    url = (cloud_url or "").strip().rstrip("/")
    if not url:
        raise VaultError("Mindscape Vault URL is not configured")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        return url
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}:
        return url
    raise VaultError("Mindscape Vault URLs must use HTTPS, except localhost for testing")


def endpoint(cloud_url: str, path: str) -> str:
    """Resolve a Worker base URL or an explicit /v1 URL to one endpoint."""
    base = _vault_base_url(cloud_url)
    for suffix in ("/v1/snapshot", "/v1/snapshot/latest", "/v1/archive", "/v1/archive/latest", "/v1/status"):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    if base.endswith("/v1"):
        return base + path
    return base + "/v1" + path


def _headers(token: str, *, content_type: str | None = None) -> dict[str, str]:
    if not isinstance(token, str) or len(token.strip()) < 16:
        raise VaultError("Mindscape Vault token is not configured")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Alpecca-Mindscape-Vault-Token": token,
        "User-Agent": "Alpecca-Mindscape-Vault/1",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _response_json(response, *, limit: int = _MAX_RESPONSE_BYTES) -> tuple[int, dict[str, object]]:
    raw = response.read(limit)
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VaultError("Mindscape Vault response was not valid JSON") from exc
    if not isinstance(body, dict):
        raise VaultError("Mindscape Vault response was not an object")
    return int(getattr(response, "status", 200)), body


def _post_json(url: str, payload: Mapping[str, object], token: str, timeout: float, opener=None) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=_canonical_json(payload),
        headers=_headers(token, content_type="application/json"),
        method="POST",
    )
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(request, timeout=timeout) as response:
            status, body = _response_json(response)
    except (OSError, urllib.error.URLError, TimeoutError, VaultError) as exc:
        return {"ok": False, "status": "transport_failed", "message": type(exc).__name__}
    accepted = 200 <= status < 300 and bool(body.get("ok", True))
    return {
        "ok": accepted,
        "status": str(body.get("status") or ("stored" if accepted else "rejected")),
        "http_status": status,
        "message": "" if accepted else str(body.get("error") or "rejected")[:160],
        "response": body,
    }


def _mark_snapshot_attempt(conn, sequence: int, error: str) -> None:
    conn.execute(
        "UPDATE mindscape_vault_outbox SET attempts=attempts+1, last_error=? WHERE sequence=?",
        (error[:160], sequence),
    )


def flush_snapshots(
    cloud_url: str,
    token: str,
    *,
    db_path: Path = DB_PATH,
    timeout: float = 8.0,
    opener=None,
    limit: int = 4,
) -> dict[str, object]:
    """Upload queued opaque snapshots in order, keeping failed entries durable."""
    try:
        upload_url = endpoint(cloud_url, "/snapshot")
        _headers(token)
    except VaultError as exc:
        return {"ok": False, "status": "not_configured", "message": str(exc), "accepted": 0}
    bounded = max(1, min(16, int(limit)))
    init_db(db_path)
    accepted = 0
    last: dict[str, object] = {"ok": True, "status": "idle", "message": ""}
    with connect(db_path) as conn:
        records = conn.execute(
            "SELECT sequence, envelope FROM mindscape_vault_outbox ORDER BY sequence ASC LIMIT ?", (bounded,)
        ).fetchall()
    for record in records:
        sequence = int(record["sequence"])
        try:
            envelope = json.loads(record["envelope"])
            validate_snapshot_envelope(envelope)
        except (json.JSONDecodeError, VaultError) as exc:
            with connect(db_path) as conn:
                _mark_snapshot_attempt(conn, sequence, "invalid_local_envelope")
            return {"ok": False, "status": "invalid_local_envelope", "message": type(exc).__name__, "accepted": accepted}
        result = _post_json(upload_url, {"envelope": envelope}, token, timeout, opener=opener)
        last = result
        if result.get("ok"):
            with connect(db_path) as conn:
                conn.execute("DELETE FROM mindscape_vault_outbox WHERE sequence=?", (sequence,))
                conn.execute(
                    "UPDATE mindscape_vault_state SET last_success_sequence=?, last_success_ts=? WHERE id=1",
                    (sequence, time.time()),
                )
            accepted += 1
            continue
        with connect(db_path) as conn:
            _mark_snapshot_attempt(conn, sequence, str(result.get("status") or "failed"))
        break
    status = local_status(db_path)
    return {
        "ok": bool(accepted) and not status["pending_snapshots"],
        "status": "synced" if not status["pending_snapshots"] else str(last.get("status") or "pending"),
        "accepted": accepted,
        "pending": status["pending_snapshots"],
        "last": {key: last.get(key) for key in ("status", "http_status", "message")},
    }


def sync_snapshot(
    snapshot: Mapping[str, object],
    cloud_url: str,
    token: str,
    secret: str | bytes,
    *,
    db_path: Path = DB_PATH,
    timeout: float = 8.0,
    opener=None,
) -> dict[str, object]:
    """Queue first, then attempt a bounded encrypted cloud backup."""
    envelope = enqueue_snapshot(snapshot, secret, db_path=db_path)
    result = flush_snapshots(cloud_url, token, db_path=db_path, timeout=timeout, opener=opener)
    result["sequence"] = envelope["sequence"]
    result["writer_id"] = envelope["writer_id"]
    return result


def fetch_latest_snapshot(
    cloud_url: str,
    token: str,
    secret: str | bytes,
    *,
    timeout: float = 8.0,
    opener=None,
) -> dict[str, object]:
    """Fetch, decrypt, and validate a vault snapshot before local restore."""
    try:
        url = endpoint(cloud_url, "/snapshot/latest")
        headers = _headers(token)
        headers["X-Alpecca-Mindscape-Vault-Scope"] = scope_id(secret)
    except VaultError as exc:
        return {"ok": False, "status": "not_configured", "message": str(exc)}
    request = urllib.request.Request(url, headers=headers, method="GET")
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(request, timeout=timeout) as response:
            status, body = _response_json(response)
    except (OSError, urllib.error.URLError, TimeoutError, VaultError) as exc:
        return {"ok": False, "status": "fetch_failed", "message": type(exc).__name__}
    if not (200 <= status < 300):
        return {"ok": False, "status": "rejected", "http_status": status, "message": "remote vault rejected snapshot fetch"}
    try:
        envelope = body.get("envelope", body)
        snapshot = unseal_snapshot(envelope, secret)
    except VaultError as exc:
        return {"ok": False, "status": "invalid_envelope", "message": str(exc)}
    return {"ok": True, "status": "fetched", "snapshot": snapshot, "envelope": validate_snapshot_envelope(envelope)}


def _archive_header(secret: str | bytes, writer_id: str, sequence: int, *, created_at: float,
                    plaintext: bytes) -> dict[str, object]:
    return {
        "schema": VAULT_SCHEMA,
        "kind": ARCHIVE_KIND,
        "algorithm": VAULT_ALGORITHM,
        "scope": scope_id(secret),
        "key_id": key_id(secret),
        "writer_id": _valid_identifier(writer_id),
        "sequence": _positive_sequence(sequence),
        "created_at": round(created_at, 6),
        "plaintext_bytes": len(plaintext),
        "plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
    }


def _archive_aad(header: Mapping[str, object]) -> bytes:
    return _canonical_json({
        name: header[name]
        for name in (
            "schema", "kind", "algorithm", "scope", "key_id", "writer_id", "sequence",
            "created_at", "plaintext_bytes", "plaintext_sha256",
        )
    })


def _validate_archive_metadata(metadata: Mapping[str, object], *, max_bytes: int) -> dict[str, object]:
    expected = {
        "schema", "kind", "algorithm", "scope", "key_id", "writer_id", "sequence",
        "created_at", "plaintext_bytes", "plaintext_sha256", "nonce", "ciphertext_bytes",
        "ciphertext_sha256",
    }
    if not isinstance(metadata, Mapping) or set(metadata) != expected:
        raise VaultError("vault archive metadata fields are invalid")
    result = dict(metadata)
    if result["schema"] != VAULT_SCHEMA or result["kind"] != ARCHIVE_KIND or result["algorithm"] != VAULT_ALGORITHM:
        raise VaultError("vault archive metadata schema is invalid")
    result["scope"] = _valid_identifier(result["scope"])
    result["writer_id"] = _valid_identifier(result["writer_id"])
    result["sequence"] = _positive_sequence(result["sequence"])
    result["created_at"] = _numeric_timestamp(result["created_at"], field="created_at")
    for field in ("plaintext_bytes", "ciphertext_bytes"):
        value = result[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > max_bytes:
            raise VaultError(f"vault archive {field} is invalid")
    for field in ("plaintext_sha256", "ciphertext_sha256"):
        value = result[field]
        if not isinstance(value, str) or len(value) != 64:
            raise VaultError(f"vault archive {field} is invalid")
        try:
            int(value, 16)
        except ValueError as exc:
            raise VaultError(f"vault archive {field} is invalid") from exc
    result["nonce"] = _b64encode(_b64decode(result["nonce"], field="nonce", expected_length=_NONCE_BYTES))
    return result


def _archive_outbox_dir(path: Path | None = None) -> Path:
    root = Path(path) if path is not None else HOME / "mindscape_vault"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _archive_files(root: Path) -> list[Path]:
    """Return only regular, non-link files created by this Vault writer."""

    try:
        entries = tuple(root.iterdir())
    except FileNotFoundError:
        return []
    return sorted(
        (
            entry
            for entry in entries
            if _ARCHIVE_FILE_RE.fullmatch(entry.name)
            and not entry.is_symlink()
            and entry.is_file()
        ),
        key=lambda entry: entry.name,
    )


def prune_local_archive_files(
    *,
    state_db: Path = DB_PATH,
    outbox_dir: Path | None = None,
    dry_run: bool = True,
    max_files: int = 512,
) -> dict[str, object]:
    """Remove bounded orphan ciphertext files, never indexed recovery work.

    The SQLite outbox is authoritative. Only exact Vault archive filenames in
    its configured directory are eligible, and dry-run is the public default.
    Unknown files and links are deliberately invisible to this cleanup path.
    """

    bounded = max(1, min(int(max_files), 4096))
    root = _archive_outbox_dir(outbox_dir).resolve()
    init_db(state_db)
    with connect(state_db) as conn:
        referenced = {
            str(Path(row[0]).resolve())
            for row in conn.execute("SELECT path FROM mindscape_vault_archives")
        }
    candidates = [
        entry
        for entry in _archive_files(root)
        if str(entry.resolve()) not in referenced
    ][:bounded]
    removed = 0
    removed_bytes = 0
    errors = 0
    for candidate in candidates:
        try:
            size = candidate.stat().st_size
            if not dry_run:
                candidate.unlink()
            removed += 1
            removed_bytes += size
        except (FileNotFoundError, OSError):
            errors += 1
    return {
        "ok": errors == 0,
        "dry_run": bool(dry_run),
        "eligible": len(candidates),
        "removed": 0 if dry_run else removed,
        "bytes": removed_bytes,
        "errors": errors,
        "remaining_indexed": len(referenced),
    }


def queue_database_archive(
    secret: str | bytes,
    *,
    source_db: Path = DB_PATH,
    state_db: Path = DB_PATH,
    outbox_dir: Path | None = None,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
) -> dict[str, object]:
    """Create an encrypted, full SQLite recovery record in the local outbox.

    The temporary raw snapshot is produced through the existing SQLite online
    backup API and removed immediately after encryption.  Art files are not in
    the SQLite database and are deliberately outside this continuity backup.
    """
    bounded_max = max(1 * 1024 * 1024, min(256 * 1024 * 1024, int(max_bytes)))
    root = _archive_outbox_dir(outbox_dir)
    staging = root / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    init_db(state_db)
    with connect(state_db) as conn:
        writer_id, sequence = _reserve_sequence(conn)
    raw_snapshot: Path | None = None
    try:
        local = snapshot_database(source_db, staging, retention=1, label="mindscape-vault")
        raw_snapshot = local.path
        size = raw_snapshot.stat().st_size
        if size < 1 or size > bounded_max:
            raise VaultError("SQLite recovery archive exceeds the configured size limit")
        plaintext = raw_snapshot.read_bytes()
        created_at = time.time()
        header = _archive_header(secret, writer_id, sequence, created_at=created_at, plaintext=plaintext)
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(derive_key(secret)).encrypt(nonce, plaintext, _archive_aad(header))
        metadata = {
            **header,
            "nonce": _b64encode(nonce),
            "ciphertext_bytes": len(ciphertext),
            "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest(),
        }
        archive_path = root / f"archive-{sequence:020d}-{metadata['ciphertext_sha256'][:16]}.bin"
        archive_path.write_bytes(ciphertext)
        with connect(state_db) as conn:
            conn.execute(
                "INSERT INTO mindscape_vault_archives (sequence, path, metadata, created_at) VALUES (?, ?, ?, ?)",
                (sequence, str(archive_path), _canonical_json(metadata).decode("utf-8"), created_at),
            )
            conn.execute(
                "DELETE FROM mindscape_vault_archives WHERE sequence NOT IN "
                "(SELECT sequence FROM mindscape_vault_archives ORDER BY sequence DESC LIMIT ?)",
                (DEFAULT_ARCHIVE_OUTBOX_LIMIT,),
            )
        # The row retention query above cannot atomically unlink filesystem
        # payloads. Sweep only exact, now-unreferenced Vault ciphertext names.
        prune_local_archive_files(
            state_db=state_db,
            outbox_dir=root,
            dry_run=False,
            max_files=DEFAULT_ARCHIVE_OUTBOX_LIMIT + 8,
        )
        return metadata
    except SQLiteBackupError as exc:
        raise VaultError(str(exc)) from exc
    finally:
        if raw_snapshot is not None:
            try:
                raw_snapshot.unlink()
            except FileNotFoundError:
                pass


def _metadata_header(metadata: Mapping[str, object]) -> str:
    return _b64encode(_canonical_json(metadata))


def flush_archives(
    cloud_url: str,
    token: str,
    *,
    state_db: Path = DB_PATH,
    timeout: float = 20.0,
    opener=None,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
) -> dict[str, object]:
    """Upload queued full recovery records, retaining failures for a retry."""
    try:
        upload_url = endpoint(cloud_url, "/archive")
        _headers(token)
    except VaultError as exc:
        return {"ok": False, "status": "not_configured", "message": str(exc), "accepted": 0}
    init_db(state_db)
    accepted = 0
    last: dict[str, object] = {"status": "idle", "message": ""}
    with connect(state_db) as conn:
        records = conn.execute(
            "SELECT sequence, path, metadata FROM mindscape_vault_archives ORDER BY sequence ASC LIMIT 1"
        ).fetchall()
    for record in records:
        sequence = int(record["sequence"])
        path = Path(str(record["path"]))
        try:
            metadata = _validate_archive_metadata(json.loads(record["metadata"]), max_bytes=max_bytes)
            ciphertext = path.read_bytes()
            if len(ciphertext) != int(metadata["ciphertext_bytes"]) or len(ciphertext) > max_bytes:
                raise VaultError("archive file length is invalid")
            if hashlib.sha256(ciphertext).hexdigest() != metadata["ciphertext_sha256"]:
                raise VaultError("archive file checksum does not match")
        except (OSError, json.JSONDecodeError, VaultError) as exc:
            with connect(state_db) as conn:
                conn.execute(
                    "UPDATE mindscape_vault_archives SET attempts=attempts+1, last_error=? WHERE sequence=?",
                    ("invalid_local_archive", sequence),
                )
            return {"ok": False, "status": "invalid_local_archive", "message": type(exc).__name__, "accepted": 0}
        headers = _headers(token, content_type="application/octet-stream")
        headers["X-Alpecca-Mindscape-Vault-Metadata"] = _metadata_header(metadata)
        request = urllib.request.Request(upload_url, data=ciphertext, headers=headers, method="POST")
        open_fn = opener or urllib.request.urlopen
        try:
            with open_fn(request, timeout=timeout) as response:
                code, body = _response_json(response)
            last = {"status": str(body.get("status") or "rejected"), "http_status": code,
                    "message": str(body.get("error") or "")[:160]}
            ok = 200 <= code < 300 and bool(body.get("ok", True))
        except (OSError, urllib.error.URLError, TimeoutError, VaultError) as exc:
            ok = False
            last = {"status": "transport_failed", "message": type(exc).__name__}
        if not ok:
            with connect(state_db) as conn:
                conn.execute(
                    "UPDATE mindscape_vault_archives SET attempts=attempts+1, last_error=? WHERE sequence=?",
                    (str(last.get("status") or "failed")[:160], sequence),
                )
            break
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        with connect(state_db) as conn:
            conn.execute("DELETE FROM mindscape_vault_archives WHERE sequence=?", (sequence,))
            conn.execute("UPDATE mindscape_vault_state SET last_archive_ts=? WHERE id=1", (time.time(),))
        accepted += 1
    status = local_status(state_db)
    return {
        "ok": bool(accepted) and not status["pending_archives"],
        "status": "archived" if not status["pending_archives"] else str(last.get("status") or "pending"),
        "accepted": accepted,
        "pending": status["pending_archives"],
        "last": last,
    }


def archive_due(interval_seconds: float, *, db_path: Path = DB_PATH, now: float | None = None) -> bool:
    """Return whether a new full recovery archive is due; zero disables it."""
    try:
        interval = float(interval_seconds)
    except (TypeError, ValueError):
        return False
    if interval <= 0:
        return False
    status = local_status(db_path)
    last = float(status["last_archive_ts"] or 0.0)
    return (time.time() if now is None else float(now)) - last >= max(300.0, interval)


def fetch_latest_archive(
    cloud_url: str,
    token: str,
    secret: str | bytes,
    destination: Path,
    *,
    timeout: float = 30.0,
    opener=None,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
) -> dict[str, object]:
    """Download a full recovery archive into a *new* verified SQLite file.

    This intentionally never overwrites the live database.  A creator can
    inspect the recovered copy and decide when to start Alpecca from it.
    """
    bounded_max = max(1 * 1024 * 1024, min(256 * 1024 * 1024, int(max_bytes)))
    try:
        url = endpoint(cloud_url, "/archive/latest")
        headers = _headers(token)
        headers["X-Alpecca-Mindscape-Vault-Scope"] = scope_id(secret)
    except VaultError as exc:
        return {"ok": False, "status": "not_configured", "message": str(exc)}
    request = urllib.request.Request(url, headers=headers, method="GET")
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            if not (200 <= status < 300):
                return {"ok": False, "status": "rejected", "http_status": status}
            response_headers = getattr(response, "headers", {})
            encoded_metadata = response_headers.get("X-Alpecca-Mindscape-Vault-Metadata", "")
            metadata = _validate_archive_metadata(
                json.loads(_b64decode(encoded_metadata, field="archive metadata").decode("utf-8")),
                max_bytes=bounded_max,
            )
            ciphertext = response.read(bounded_max + 1)
    except (OSError, urllib.error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, VaultError) as exc:
        return {"ok": False, "status": "fetch_failed", "message": type(exc).__name__}
    if len(ciphertext) != int(metadata["ciphertext_bytes"]) or len(ciphertext) > bounded_max:
        return {"ok": False, "status": "invalid_archive", "message": "ciphertext length"}
    if metadata["scope"] != scope_id(secret) or metadata["key_id"] != key_id(secret):
        return {"ok": False, "status": "invalid_archive", "message": "recovery key"}
    if hashlib.sha256(ciphertext).hexdigest() != metadata["ciphertext_sha256"]:
        return {"ok": False, "status": "invalid_archive", "message": "ciphertext checksum"}
    header = {
        name: metadata[name]
        for name in (
            "schema", "kind", "algorithm", "scope", "key_id", "writer_id", "sequence",
            "created_at", "plaintext_bytes", "plaintext_sha256",
        )
    }
    nonce = _b64decode(metadata["nonce"], field="nonce", expected_length=_NONCE_BYTES)
    try:
        plaintext = AESGCM(derive_key(secret)).decrypt(nonce, ciphertext, _archive_aad(header))
    except InvalidTag:
        return {"ok": False, "status": "invalid_archive", "message": "authentication"}
    if len(plaintext) != int(metadata["plaintext_bytes"]) or hashlib.sha256(plaintext).hexdigest() != metadata["plaintext_sha256"]:
        return {"ok": False, "status": "invalid_archive", "message": "plaintext checksum"}
    output = Path(destination).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_name(f".{output.name}.vault-recovery.tmp")
    try:
        staging.write_bytes(plaintext)
        conn = sqlite3.connect(f"{staging.as_uri()}?mode=ro", uri=True)
        try:
            integrity = [str(row[0]) for row in conn.execute("PRAGMA integrity_check")]
        finally:
            conn.close()
        if integrity != ["ok"]:
            raise VaultError("recovered SQLite integrity check failed")
        os.replace(staging, output)
    except (OSError, sqlite3.Error, VaultError) as exc:
        try:
            staging.unlink()
        except FileNotFoundError:
            pass
        return {"ok": False, "status": "restore_failed", "message": type(exc).__name__}
    return {
        "ok": True,
        "status": "recovered",
        "path": str(output),
        "sequence": metadata["sequence"],
        "created_at": metadata["created_at"],
    }


__all__ = [
    "ARCHIVE_KIND", "DEFAULT_MAX_ARCHIVE_BYTES", "SNAPSHOT_KIND", "VAULT_KEY_CREDENTIAL_TARGET",
    "VAULT_KEY_ENV", "VAULT_SCHEMA", "VAULT_TOKEN_CREDENTIAL_TARGET", "VAULT_TOKEN_ENV", "VaultError", "archive_due", "derive_key", "endpoint",
    "enqueue_snapshot", "fetch_latest_archive", "fetch_latest_snapshot", "flush_archives", "flush_snapshots", "init_db",
    "key_id", "load_or_create_encryption_key", "load_or_create_transport_token", "local_status", "queue_database_archive",
    "prune_local_archive_files",
    "scope_id", "seal_snapshot", "sync_snapshot", "unseal_snapshot", "validate_snapshot_envelope",
]
