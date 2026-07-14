"""Encrypted-at-rest conversational memory for Discord voice transcripts.

Only bounded text produced by local speech-to-text is retained. Raw audio is
never accepted by this module. Room, speaker, and transcript fields are sealed
together with AES-256-GCM; SQLite keeps only opaque HMAC routing keys and
content-free timing metadata outside the ciphertext.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from alpecca.db import connect, harden


MAX_TRANSCRIPT_CHARS = 2_000
MAX_SPEAKER_NAME_CHARS = 80
MAX_RECENT = 24
DEFAULT_MAX_RECORDS = 10_000
_NONCE_BYTES = 12
_KEY_DOMAIN = b"Alpecca Discord voice memory AES-GCM v1\x00"
_ROUTING_DOMAIN = b"Alpecca Discord voice routing HMAC v1\x00"


@dataclass(frozen=True, slots=True)
class DiscordVoiceMemory:
    id: int
    timestamp: float
    guild_id: int
    channel_id: int
    speaker_id: int
    speaker_name: str
    transcript: str
    duration_seconds: float


class EncryptedVoiceMemoryStore:
    """Small bounded AES-GCM store keyed from protected bridge material."""

    def __init__(
        self,
        db_path: Path,
        *,
        secret: str | bytes,
        max_records: int = DEFAULT_MAX_RECORDS,
    ) -> None:
        if isinstance(secret, str):
            secret_bytes = secret.encode("utf-8")
        elif isinstance(secret, bytes):
            secret_bytes = secret
        else:
            raise TypeError("secret must be str or bytes")
        if len(secret_bytes) < 32:
            raise ValueError("voice memory secret must contain at least 32 bytes")
        self.db_path = Path(db_path)
        self.max_records = max(32, min(100_000, int(max_records)))
        self._key = hashlib.sha256(_KEY_DOMAIN + secret_bytes).digest()
        self._routing_key = hashlib.sha256(_ROUTING_DOMAIN + secret_bytes).digest()
        self._cipher = AESGCM(self._key)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS discord_voice_memories (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts               REAL NOT NULL,
                    room_hmac        TEXT NOT NULL,
                    speaker_hmac     TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    nonce            BLOB NOT NULL,
                    ciphertext       BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS discord_voice_room_recent_idx
                    ON discord_voice_memories(room_hmac, ts DESC, id DESC);
                """
            )
        harden(self.db_path)

    @staticmethod
    def _positive_id(value: object, name: str) -> int:
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
        return value

    def _opaque(self, label: bytes, *values: int) -> str:
        material = label + b"\x00" + b":".join(str(value).encode("ascii") for value in values)
        return hmac.new(self._routing_key, material, hashlib.sha256).hexdigest()

    def _room_hmac(self, guild_id: int, channel_id: int) -> str:
        return self._opaque(b"room", guild_id, channel_id)

    def _speaker_hmac(self, guild_id: int, channel_id: int, speaker_id: int) -> str:
        return self._opaque(b"speaker", guild_id, channel_id, speaker_id)

    @staticmethod
    def _aad(room_hmac: str) -> bytes:
        return f"alpecca-discord-voice-memory-v1:{room_hmac}".encode("ascii")

    def remember(
        self,
        transcript: str,
        *,
        guild_id: int,
        channel_id: int,
        speaker_id: int,
        speaker_name: str,
        duration_seconds: float,
        timestamp: float | None = None,
    ) -> int:
        guild = self._positive_id(guild_id, "guild_id")
        channel = self._positive_id(channel_id, "channel_id")
        speaker = self._positive_id(speaker_id, "speaker_id")
        text = " ".join(str(transcript or "").split())[:MAX_TRANSCRIPT_CHARS]
        name = " ".join(str(speaker_name or "Discord participant").split())[
            :MAX_SPEAKER_NAME_CHARS
        ] or "Discord participant"
        if not text:
            raise ValueError("transcript must not be empty")
        duration = max(0.0, min(60.0, float(duration_seconds)))
        observed_at = time.time() if timestamp is None else float(timestamp)
        if observed_at <= 0:
            raise ValueError("timestamp must be positive")

        room_hmac = self._room_hmac(guild, channel)
        speaker_hmac = self._speaker_hmac(guild, channel, speaker)
        payload = json.dumps(
            {
                "v": 1,
                "guild_id": guild,
                "channel_id": channel,
                "speaker_id": speaker,
                "speaker_name": name,
                "transcript": text,
            },
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._cipher.encrypt(nonce, payload, self._aad(room_hmac))
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO discord_voice_memories
                    (ts, room_hmac, speaker_hmac, duration_seconds, nonce, ciphertext)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (observed_at, room_hmac, speaker_hmac, duration, nonce, ciphertext),
            )
            memory_id = int(cursor.lastrowid)
            conn.execute(
                """
                DELETE FROM discord_voice_memories
                 WHERE id NOT IN (
                    SELECT id FROM discord_voice_memories
                     ORDER BY ts DESC, id DESC LIMIT ?
                 )
                """,
                (self.max_records,),
            )
        return memory_id

    def recent(
        self,
        *,
        guild_id: int,
        channel_id: int,
        limit: int = 12,
    ) -> list[DiscordVoiceMemory]:
        guild = self._positive_id(guild_id, "guild_id")
        channel = self._positive_id(channel_id, "channel_id")
        bounded_limit = max(1, min(MAX_RECENT, int(limit)))
        room_hmac = self._room_hmac(guild, channel)
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, ts, duration_seconds, nonce, ciphertext
                  FROM discord_voice_memories
                 WHERE room_hmac=?
                 ORDER BY ts DESC, id DESC
                 LIMIT ?
                """,
                (room_hmac, bounded_limit),
            ).fetchall()

        memories: list[DiscordVoiceMemory] = []
        for row in rows:
            try:
                plaintext = self._cipher.decrypt(
                    bytes(row["nonce"]),
                    bytes(row["ciphertext"]),
                    self._aad(room_hmac),
                )
                payload = json.loads(plaintext)
                if (
                    type(payload) is not dict
                    or payload.get("v") != 1
                    or payload.get("guild_id") != guild
                    or payload.get("channel_id") != channel
                ):
                    continue
                speaker_id = self._positive_id(payload.get("speaker_id"), "speaker_id")
                speaker_name = str(payload.get("speaker_name") or "")[:MAX_SPEAKER_NAME_CHARS]
                transcript = str(payload.get("transcript") or "")[:MAX_TRANSCRIPT_CHARS]
                if not speaker_name or not transcript:
                    continue
            except (InvalidTag, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            memories.append(
                DiscordVoiceMemory(
                    id=int(row["id"]),
                    timestamp=float(row["ts"]),
                    guild_id=guild,
                    channel_id=channel,
                    speaker_id=speaker_id,
                    speaker_name=speaker_name,
                    transcript=transcript,
                    duration_seconds=float(row["duration_seconds"]),
                )
            )
        memories.reverse()
        return memories

    def status(self) -> dict[str, object]:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count, MAX(ts) AS newest FROM discord_voice_memories"
            ).fetchone()
        return {
            "ready": True,
            "encryption": "AES-256-GCM",
            "raw_audio_persistence": "none",
            "records": int(row["count"] or 0),
            "newest": float(row["newest"]) if row["newest"] is not None else None,
        }


__all__ = [
    "DEFAULT_MAX_RECORDS",
    "DiscordVoiceMemory",
    "EncryptedVoiceMemoryStore",
    "MAX_RECENT",
    "MAX_SPEAKER_NAME_CHARS",
    "MAX_TRANSCRIPT_CHARS",
]
