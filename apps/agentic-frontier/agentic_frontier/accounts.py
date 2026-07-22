"""Account and player-avatar storage owned by Alventius Experimentus."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import struct
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SESSION_SECONDS = 30 * 24 * 60 * 60
MAX_AVATAR_BYTES = 32 * 1024 * 1024
USERNAME = re.compile(r"^[A-Za-z0-9_]{3,24}$")
AVATAR_IDS = {"silhouette", "custom"}


class AccountError(ValueError):
    """The account request is invalid or cannot be completed."""


class AuthenticationError(AccountError):
    """The submitted credentials are not valid."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, maxmem=64 * 1024 * 1024
    )


def _clean_password(value: object) -> str:
    if type(value) is not str or not 10 <= len(value) <= 128:
        raise AccountError("Password must contain 10-128 characters.")
    return value


def _clean_username(value: object) -> str:
    if type(value) is not str or not USERNAME.fullmatch(value):
        raise AccountError("Username must use 3-24 letters, numbers, or underscores.")
    return value


def _clean_display_name(value: object) -> str:
    if type(value) is not str:
        raise AccountError("Display name is required.")
    clean = " ".join(value.strip().split())
    if not 1 <= len(clean) <= 32:
        raise AccountError("Display name must contain 1-32 characters.")
    return clean


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _is_vrm1_glb(payload: bytes) -> bool:
    if len(payload) < 20 or payload[:4] != b"glTF":
        return False
    version, declared_length = struct.unpack_from("<II", payload, 4)
    if version != 2 or declared_length != len(payload):
        return False
    offset = 12
    metadata: dict[str, Any] | None = None
    while offset + 8 <= len(payload):
        chunk_length, chunk_type = struct.unpack_from("<II", payload, offset)
        offset += 8
        end = offset + chunk_length
        if end > len(payload):
            return False
        if chunk_type == 0x4E4F534A:
            try:
                metadata = json.loads(payload[offset:end].rstrip(b" \x00").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return False
            break
        offset = end
    if not isinstance(metadata, dict):
        return False
    extensions = metadata.get("extensionsUsed", [])
    root_extensions = metadata.get("extensions", {})
    return "VRMC_vrm" in extensions or (
        isinstance(root_extensions, dict) and "VRMC_vrm" in root_extensions
    )


class GameAccountStore:
    """SQLite accounts, opaque login sessions, and account-owned player VRMs."""

    def __init__(self, db_path: str | Path, avatar_root: str | Path | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.avatar_root = Path(avatar_root or self.db_path.parent / "player-avatars")
        self.avatar_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS game_accounts (
                    account_id TEXT PRIMARY KEY,
                    username_key TEXT NOT NULL UNIQUE,
                    username TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    world_id TEXT NOT NULL UNIQUE,
                    selected_avatar TEXT NOT NULL DEFAULT 'silhouette'
                        CHECK (selected_avatar IN ('silhouette', 'custom')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS game_account_sessions (
                    token_hash TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (account_id) REFERENCES game_accounts(account_id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS game_account_sessions_expiry
                    ON game_account_sessions(expires_at);
                """
            )
            conn.commit()

    def register(self, username: object, display_name: object, password: object) -> tuple[dict[str, Any], str]:
        clean_username = _clean_username(username)
        clean_display = _clean_display_name(display_name)
        clean_password = _clean_password(password)
        account_id = f"usr_{secrets.token_hex(8)}"
        world_id = f"world_{secrets.token_hex(10)}"
        salt = secrets.token_bytes(16)
        digest = _password_hash(clean_password, salt)
        timestamp = _now()
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO game_accounts VALUES (?, ?, ?, ?, ?, ?, ?, 'silhouette', ?, ?)",
                    (
                        account_id,
                        clean_username.casefold(),
                        clean_username,
                        clean_display,
                        salt,
                        digest,
                        world_id,
                        timestamp,
                        timestamp,
                    ),
                )
                token = self._issue_session(conn, account_id)
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise AccountError("That username is already registered.") from exc
        return self.profile(account_id), token

    def login(self, username: object, password: object) -> tuple[dict[str, Any], str]:
        clean_username = _clean_username(username)
        clean_password = _clean_password(password)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM game_accounts WHERE username_key=?",
                (clean_username.casefold(),),
            ).fetchone()
            if row is None:
                _password_hash(clean_password, b"\0" * 16)
                raise AuthenticationError("Username or password is incorrect.")
            supplied = _password_hash(clean_password, bytes(row["password_salt"]))
            if not hmac.compare_digest(supplied, bytes(row["password_hash"])):
                raise AuthenticationError("Username or password is incorrect.")
            conn.execute("BEGIN IMMEDIATE")
            token = self._issue_session(conn, row["account_id"])
            conn.commit()
        return self.profile(row["account_id"]), token

    def _issue_session(self, conn: sqlite3.Connection, account_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        conn.execute("DELETE FROM game_account_sessions WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT INTO game_account_sessions VALUES (?, ?, ?, ?)",
            (_token_hash(token), account_id, now + SESSION_SECONDS, _now()),
        )
        return token

    def authenticate(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        try:
            digest = _token_hash(token)
        except UnicodeEncodeError:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT account_id FROM game_account_sessions "
                "WHERE token_hash=? AND expires_at > ?",
                (digest, int(time.time())),
            ).fetchone()
        return self.profile(row["account_id"]) if row else None

    def logout(self, token: str | None) -> None:
        if not token:
            return
        try:
            digest = _token_hash(token)
        except UnicodeEncodeError:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM game_account_sessions WHERE token_hash=?", (digest,))
            conn.commit()

    def profile(self, account_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT account_id, username, display_name, world_id, selected_avatar "
                "FROM game_accounts WHERE account_id=?",
                (account_id,),
            ).fetchone()
        if row is None:
            raise AuthenticationError("Account no longer exists.")
        custom_available = self._avatar_path(account_id).is_file()
        selected = row["selected_avatar"]
        if selected == "custom" and not custom_available:
            selected = "silhouette"
        return {
            "accountId": row["account_id"],
            "username": row["username"],
            "displayName": row["display_name"],
            "worldId": row["world_id"],
            "selectedAvatar": selected,
            "customAvatarAvailable": custom_available,
        }

    def avatar_catalog(self, account_id: str) -> dict[str, Any]:
        profile = self.profile(account_id)
        return {
            "selectedAvatar": profile["selectedAvatar"],
            "avatars": [
                {
                    "id": "silhouette",
                    "name": "Field Scout",
                    "description": "Built-in cel-shaded explorer",
                    "available": True,
                },
                {
                    "id": "custom",
                    "name": "My VRM 1.0",
                    "description": "Private account avatar",
                    "available": profile["customAvatarAvailable"],
                },
            ],
        }

    def select_avatar(self, account_id: str, avatar_id: object) -> dict[str, Any]:
        if type(avatar_id) is not str or avatar_id not in AVATAR_IDS:
            raise AccountError("Unknown player avatar.")
        if avatar_id == "custom" and not self._avatar_path(account_id).is_file():
            raise AccountError("Upload a VRM 1.0 player model before selecting it.")
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE game_accounts SET selected_avatar=?, updated_at=? WHERE account_id=?",
                (avatar_id, _now(), account_id),
            ).rowcount
            conn.commit()
        if not changed:
            raise AuthenticationError("Account no longer exists.")
        return self.avatar_catalog(account_id)

    def store_custom_avatar(self, account_id: str, payload: bytes) -> dict[str, Any]:
        if not payload or len(payload) > MAX_AVATAR_BYTES:
            raise AccountError("Player VRM must be between 1 byte and 32 MiB.")
        if not _is_vrm1_glb(payload):
            raise AccountError("Player model must be a valid native VRM 1.0 GLB file.")
        target = self._avatar_path(account_id)
        temporary = target.with_suffix(".uploading")
        temporary.write_bytes(payload)
        temporary.replace(target)
        return self.select_avatar(account_id, "custom")

    def avatar_path(self, account_id: str) -> Path:
        target = self._avatar_path(account_id)
        if not target.is_file():
            raise AccountError("No custom player VRM has been uploaded.")
        return target

    def _avatar_path(self, account_id: str) -> Path:
        if not re.fullmatch(r"usr_[0-9a-f]{16}", account_id):
            raise AuthenticationError("Invalid account identity.")
        return self.avatar_root / f"{account_id}.vrm"
