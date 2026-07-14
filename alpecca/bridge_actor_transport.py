"""Pure shared wire contract for signed Discord guest actors.

Importing this module does not load credentials or open storage.  The server
calls :func:`build_actor_store` lazily with the dedicated actor-identity seal;
the Discord bridge uses only the header constants and binding parser/serializer.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from alpecca import bridge_actor_identity as actor_identity


MAX_DISCORD_BODY_BYTES = 6 * 1024 * 1024

EVENT_ID_HEADER = "X-Alpecca-Discord-Event-Id"
ACTOR_ID_HEADER = "X-Alpecca-Discord-Actor-Id"
GUILD_ID_HEADER = "X-Alpecca-Discord-Guild-Id"
CHANNEL_ID_HEADER = "X-Alpecca-Discord-Channel-Id"
THREAD_ID_HEADER = "X-Alpecca-Discord-Thread-Id"
ENVELOPE_HEADER = "X-Alpecca-Discord-Actor-Envelope"
TRUSTED_CONTEXT_PREFIX = "alpecca-bridge-live-context-v1:"

POLICY_VERSION = actor_identity.SUPPORTED_POLICY_VERSION
KEY_VERSION = 1
ENVELOPE_TTL_MS = 30_000
MAX_EXTERNAL_ID_BYTES = 32
MAX_ENVELOPE_BYTES = 4096

ACTOR_DB_FILENAME = "bridge_actor_identity.sqlite3"
ANCHOR_DB_FILENAME = "bridge_actor_identity_anchor.sqlite3"
SQLITE_ANCHOR_LIMITATION = (
    "local-development-only SQLite rollback detector; the actor and anchor "
    "files under HOME share one failure domain"
)

ACTOR_POLICY = actor_identity.BridgeActorPolicy(
    version=POLICY_VERSION,
    envelope_ttl_ms=ENVELOPE_TTL_MS,
    max_body_bytes=MAX_DISCORD_BODY_BYTES,
    max_external_id_bytes=MAX_EXTERNAL_ID_BYTES,
    max_transport_bytes=MAX_ENVELOPE_BYTES,
    max_clock_advance_ms=2_592_000_000,
    max_incremental_audit_rows=64,
)
ACTOR_BOUNDARY = actor_identity.TrustedBridgeBoundary(
    service="discord-bridge",
    platform="discord",
    boundary_id="server-discord-adapter",
)

_UINT64_MAX = (1 << 64) - 1
_REQUIRED_HEADERS = (
    (EVENT_ID_HEADER, "event_id"),
    (ACTOR_ID_HEADER, "actor_id"),
    (CHANNEL_ID_HEADER, "channel_id"),
)
_OPTIONAL_HEADERS = (
    (GUILD_ID_HEADER, "guild_id"),
    (THREAD_ID_HEADER, "thread_id"),
)


class DiscordActorHeaderError(ValueError):
    """A dedicated Discord identity header is missing or malformed."""


def _canonical_discord_id(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise DiscordActorHeaderError(f"{field} header is invalid")
    if (
        not value.isascii()
        or not value.isdecimal()
        or value[0] == "0"
        or len(value) > 20
    ):
        raise DiscordActorHeaderError(f"{field} header is invalid")
    if int(value) > _UINT64_MAX:
        raise DiscordActorHeaderError(f"{field} header is invalid")
    return value


@dataclass(frozen=True, slots=True)
class DiscordActorBindings:
    """Exact Discord transport bindings carried only in dedicated headers.

    Text events use Discord's message snowflake. A locally segmented voice
    utterance uses a bridge-minted, unique uint64 event id because Discord does
    not provide a message id for microphone packets.
    """

    event_id: str
    actor_id: str
    channel_id: str
    guild_id: str | None = None
    thread_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("event_id", "actor_id", "channel_id"):
            object.__setattr__(
                self,
                field,
                _canonical_discord_id(getattr(self, field), field),
            )
        for field in ("guild_id", "thread_id"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(
                    self,
                    field,
                    _canonical_discord_id(value, field),
                )

    def as_headers(self) -> dict[str, str]:
        headers = {
            EVENT_ID_HEADER: self.event_id,
            ACTOR_ID_HEADER: self.actor_id,
            CHANNEL_ID_HEADER: self.channel_id,
        }
        if self.guild_id is not None:
            headers[GUILD_ID_HEADER] = self.guild_id
        if self.thread_id is not None:
            headers[THREAD_ID_HEADER] = self.thread_id
        return headers

    def as_store_kwargs(self) -> dict[str, str | None]:
        """Map header names to the committed identity-core parameter names."""
        return {
            "discord_event_id": self.event_id,
            "external_actor_id": self.actor_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "thread_id": self.thread_id,
        }


def _header_values(headers: object, name: str) -> list[str]:
    getlist = getattr(headers, "getlist", None)
    if callable(getlist):
        values = list(getlist(name))
    elif isinstance(headers, Mapping):
        folded_name = name.casefold()
        values = [
            value
            for key, value in headers.items()
            if type(key) is str and key.casefold() == folded_name
        ]
    else:
        raise DiscordActorHeaderError("headers must be a mapping")
    if any(type(value) is not str for value in values):
        raise DiscordActorHeaderError(f"{name} header is invalid")
    return values


def parse_binding_headers(headers: object) -> DiscordActorBindings:
    """Parse one strict, case-insensitive set of dedicated Discord ID headers."""
    parsed: dict[str, str | None] = {}
    for header, field in _REQUIRED_HEADERS:
        values = _header_values(headers, header)
        if len(values) != 1:
            raise DiscordActorHeaderError(f"{field} header is required exactly once")
        parsed[field] = _canonical_discord_id(values[0], field)
    for header, field in _OPTIONAL_HEADERS:
        values = _header_values(headers, header)
        if len(values) > 1:
            raise DiscordActorHeaderError(f"{field} header is allowed at most once")
        parsed[field] = _canonical_discord_id(values[0], field) if values else None
    return DiscordActorBindings(
        event_id=str(parsed["event_id"]),
        actor_id=str(parsed["actor_id"]),
        channel_id=str(parsed["channel_id"]),
        guild_id=parsed["guild_id"],
        thread_id=parsed["thread_id"],
    )


def parse_envelope_header(headers: object) -> str:
    """Return one bounded actor-envelope header without interpreting its seal."""
    values = _header_values(headers, ENVELOPE_HEADER)
    if len(values) != 1:
        raise DiscordActorHeaderError("actor envelope header is required exactly once")
    envelope = values[0]
    if not envelope or envelope != envelope.strip():
        raise DiscordActorHeaderError("actor envelope header is invalid")
    try:
        encoded = envelope.encode("ascii")
    except UnicodeEncodeError as exc:
        raise DiscordActorHeaderError("actor envelope header is invalid") from exc
    if len(encoded) > MAX_ENVELOPE_BYTES or any(
        byte < 32 or byte == 127 for byte in encoded
    ):
        raise DiscordActorHeaderError("actor envelope header is invalid")
    return envelope


def _seal_key_bytes(seal_secret: object) -> bytes:
    if type(seal_secret) is str:
        try:
            key = seal_secret.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("seal_secret must be valid UTF-8") from exc
    elif type(seal_secret) is bytes:
        key = seal_secret
    else:
        raise TypeError("seal_secret must be str or bytes")
    if len(key) < actor_identity.MIN_KEY_BYTES:
        raise ValueError("seal_secret must contain at least 32 UTF-8 bytes")
    return key


def build_actor_store(
    home: str | Path,
    seal_secret: str | bytes,
) -> actor_identity.BridgeActorIdentityStore:
    """Build the fixed server-side store and local-development SQLite anchor.

    The caller must pass the dedicated secret returned by
    ``auth.load_or_create_bridge_actor_identity_seal_secret``.  Requiring it as
    an argument keeps module import and bridge-side use credential-free.
    """
    home_path = Path(home)
    home_path.mkdir(parents=True, exist_ok=True)
    anchor = actor_identity.SQLiteMonotonicAnchor(home_path / ANCHOR_DB_FILENAME)
    return actor_identity.BridgeActorIdentityStore(
        home_path / ACTOR_DB_FILENAME,
        seal_key=_seal_key_bytes(seal_secret),
        key_version=KEY_VERSION,
        policy=ACTOR_POLICY,
        boundary=ACTOR_BOUNDARY,
        clock=actor_identity.SystemTrustedClock(),
        monotonic_anchor=anchor,
    )


def _verified_hmac(actor: actor_identity.VerifiedGuestActor, field: str) -> bytes:
    value = getattr(actor, field)
    if type(value) is not str or len(value) != 64:
        raise actor_identity.BridgeActorIntegrityError(
            "verified Discord guest scope binding is malformed"
        )
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise actor_identity.BridgeActorIntegrityError(
            "verified Discord guest scope binding is malformed"
        ) from exc


def guest_scope(
    actor: actor_identity.VerifiedGuestActor,
) -> tuple[str, str]:
    """Derive stable opaque conversation/privacy IDs from a verified guest."""
    if type(actor) is not actor_identity.VerifiedGuestActor or actor.authority != "guest":
        raise TypeError("actor must be a verifier-created VerifiedGuestActor")
    material = b"".join((
        b"alpecca:discord-guest-scope:v1\x00",
        _verified_hmac(actor, "actor_subject_hmac"),
        _verified_hmac(actor, "thread_scope_hmac"),
    ))
    conversation_digest = hashlib.sha256(b"conversation\x00" + material).hexdigest()
    privacy_digest = hashlib.sha256(b"privacy\x00" + material).hexdigest()
    return (
        f"discord-guest-{conversation_digest}",
        f"guest-discord-{privacy_digest}",
    )


__all__ = [
    "ACTOR_BOUNDARY",
    "ACTOR_DB_FILENAME",
    "ACTOR_ID_HEADER",
    "ACTOR_POLICY",
    "ANCHOR_DB_FILENAME",
    "CHANNEL_ID_HEADER",
    "DiscordActorBindings",
    "DiscordActorHeaderError",
    "ENVELOPE_HEADER",
    "ENVELOPE_TTL_MS",
    "EVENT_ID_HEADER",
    "GUILD_ID_HEADER",
    "KEY_VERSION",
    "MAX_DISCORD_BODY_BYTES",
    "MAX_ENVELOPE_BYTES",
    "POLICY_VERSION",
    "SQLITE_ANCHOR_LIMITATION",
    "THREAD_ID_HEADER",
    "TRUSTED_CONTEXT_PREFIX",
    "build_actor_store",
    "guest_scope",
    "parse_binding_headers",
    "parse_envelope_header",
]
