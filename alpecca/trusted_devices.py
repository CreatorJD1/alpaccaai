"""Device-bound creator sessions for Alpecca's native phone launcher.

The private signing key never leaves Android Keystore. This module stores only
the public key, a random device id, and bounded single-use challenges.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


CHALLENGE_TTL_SECONDS = 120
MAX_PUBLIC_KEY_BYTES = 1024
MAX_SIGNATURE_BYTES = 256
CHALLENGE_PREFIX = "alpecca-device-auth-v2"


class DeviceAuthError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _decode(value: str, *, limit: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > limit * 2:
        raise DeviceAuthError("malformed")
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii") + b"=" * (-len(value) % 4))
    except (UnicodeError, ValueError) as exc:
        raise DeviceAuthError("malformed") from exc
    if not raw or len(raw) > limit:
        raise DeviceAuthError("malformed")
    return raw


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _normalize_origin(value: str) -> str:
    from urllib.parse import urlparse

    try:
        parsed = urlparse(str(value or ""))
    except ValueError as exc:
        raise DeviceAuthError("origin_invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DeviceAuthError("origin_invalid")
    if parsed.username or parsed.password or parsed.path not in {"", "/"}:
        raise DeviceAuthError("origin_invalid")
    if parsed.params or parsed.query or parsed.fragment:
        raise DeviceAuthError("origin_invalid")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


class TrustedDeviceRegistry:
    def __init__(self, db_path: str | Path, *, now: Callable[[], float] = time.time) -> None:
        self.db_path = str(db_path)
        self._now = now
        self._lock = threading.RLock()
        self._active_created: dict[str, int] = {}
        self._ensure_schema()
        self._load_active_devices()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trusted_creator_devices (
                    device_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    public_key_der BLOB NOT NULL,
                    fingerprint TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL,
                    revoked_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS trusted_device_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    message BLOB NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER,
                    FOREIGN KEY(device_id) REFERENCES trusted_creator_devices(device_id)
                );
                CREATE INDEX IF NOT EXISTS idx_device_challenge_expiry
                    ON trusted_device_challenges(expires_at, used_at);
                """
            )

    def _load_active_devices(self) -> None:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT device_id, created_at FROM trusted_creator_devices WHERE revoked_at IS NULL"
            ).fetchall()
            self._active_created = {
                str(row["device_id"]): int(row["created_at"])
                for row in rows
            }

    def enroll(self, public_key: str, *, label: str = "CreatorJD phone") -> dict[str, str | int]:
        der = _decode(public_key, limit=MAX_PUBLIC_KEY_BYTES)
        try:
            key = serialization.load_der_public_key(der)
        except (TypeError, ValueError) as exc:
            raise DeviceAuthError("public_key_invalid") from exc
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise DeviceAuthError("public_key_unsupported")
        safe_label = " ".join(str(label or "CreatorJD phone").split())[:64] or "CreatorJD phone"
        device_id = secrets.token_urlsafe(18)
        now = int(self._now())
        fingerprint = hashlib.sha256(der).hexdigest()
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT device_id, revoked_at FROM trusted_creator_devices WHERE fingerprint = ? ORDER BY created_at DESC LIMIT 1",
                (fingerprint,),
            ).fetchone()
            if existing:
                if existing["revoked_at"] is not None:
                    raise DeviceAuthError("device_revoked")
                device_id = str(existing["device_id"])
                conn.execute(
                    "UPDATE trusted_creator_devices SET label = ?, last_seen_at = ? WHERE device_id = ?",
                    (safe_label, now, device_id),
                )
            else:
                conn.execute(
                    "INSERT INTO trusted_creator_devices VALUES (?, ?, ?, ?, ?, ?, NULL)",
                    (device_id, safe_label, der, fingerprint, now, now),
                )
            self._active_created[device_id] = now
        return {"device_id": device_id, "fingerprint": fingerprint, "created_at": now}

    def issue_challenge(self, device_id: str, origin: str) -> dict[str, str | int]:
        if not isinstance(device_id, str) or not 12 <= len(device_id) <= 64:
            raise DeviceAuthError("device_unknown")
        normalized_origin = _normalize_origin(origin)
        now = int(self._now())
        challenge_id = secrets.token_urlsafe(18)
        expires_at = now + CHALLENGE_TTL_SECONDS
        nonce = _encode(secrets.token_bytes(32))
        message = "\n".join((
            CHALLENGE_PREFIX,
            device_id,
            challenge_id,
            str(expires_at),
            nonce,
            normalized_origin,
        )).encode("utf-8")
        with self._lock, self._connect() as conn:
            device = conn.execute(
                "SELECT revoked_at FROM trusted_creator_devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            if not device or device["revoked_at"] is not None:
                raise DeviceAuthError("device_unknown")
            conn.execute(
                "DELETE FROM trusted_device_challenges WHERE expires_at < ? OR used_at IS NOT NULL",
                (now,),
            )
            conn.execute(
                "UPDATE trusted_device_challenges SET used_at = ? WHERE device_id = ? AND used_at IS NULL",
                (now, device_id),
            )
            conn.execute(
                "INSERT INTO trusted_device_challenges VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (challenge_id, device_id, normalized_origin, message, now, expires_at),
            )
        return {
            "challenge_id": challenge_id,
            "message": _encode(message),
            "expires_at": expires_at,
        }

    def exchange(self, challenge_id: str, signature: str, origin: str) -> str:
        if not isinstance(challenge_id, str) or not 12 <= len(challenge_id) <= 64:
            raise DeviceAuthError("challenge_invalid")
        normalized_origin = _normalize_origin(origin)
        supplied_signature = _decode(signature, limit=MAX_SIGNATURE_BYTES)
        now = int(self._now())
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """SELECT c.device_id, c.origin, c.message, c.expires_at, c.used_at,
                          d.public_key_der, d.revoked_at
                   FROM trusted_device_challenges c
                   JOIN trusted_creator_devices d ON d.device_id = c.device_id
                   WHERE c.challenge_id = ?""",
                (challenge_id,),
            ).fetchone()
            if not row or row["used_at"] is not None or row["expires_at"] <= now:
                raise DeviceAuthError("challenge_expired")
            if row["revoked_at"] is not None or row["origin"] != normalized_origin:
                raise DeviceAuthError("challenge_rejected")
            try:
                key = serialization.load_der_public_key(bytes(row["public_key_der"]))
                assert isinstance(key, ec.EllipticCurvePublicKey)
                key.verify(supplied_signature, bytes(row["message"]), ec.ECDSA(hashes.SHA256()))
            except (AssertionError, InvalidSignature, TypeError, ValueError) as exc:
                raise DeviceAuthError("signature_invalid") from exc
            consumed = conn.execute(
                "UPDATE trusted_device_challenges SET used_at = ? WHERE challenge_id = ? AND used_at IS NULL",
                (now, challenge_id),
            )
            if consumed.rowcount != 1:
                raise DeviceAuthError("challenge_replayed")
            conn.execute(
                "UPDATE trusted_creator_devices SET last_seen_at = ? WHERE device_id = ?",
                (now, row["device_id"]),
            )
            return str(row["device_id"])

    def revoke(self, device_id: str) -> bool:
        now = int(self._now())
        with self._lock, self._connect() as conn:
            result = conn.execute(
                "UPDATE trusted_creator_devices SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL",
                (now, device_id),
            )
            conn.execute(
                "UPDATE trusted_device_challenges SET used_at = ? WHERE device_id = ? AND used_at IS NULL",
                (now, device_id),
            )
            if result.rowcount == 1:
                self._active_created.pop(device_id, None)
            return result.rowcount == 1

    def active_count(self) -> int:
        with self._lock:
            return len(self._active_created)

    def session_valid(self, device_id: str, issued_at: int | None) -> bool:
        """Validate a device-bound session without blocking the request loop."""
        if not isinstance(device_id, str) or not device_id:
            return False
        if isinstance(issued_at, bool) or not isinstance(issued_at, int):
            return False
        with self._lock:
            created_at = self._active_created.get(device_id)
        return created_at is not None and issued_at >= created_at


__all__ = [
    "CHALLENGE_PREFIX",
    "CHALLENGE_TTL_SECONDS",
    "DeviceAuthError",
    "TrustedDeviceRegistry",
]
