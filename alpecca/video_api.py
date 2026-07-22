"""Source-neutral Video Companion API contracts.

This module contains no transport or runtime integration. House HQ is a native
surface and Discord is represented as an adapter surface using the same
contracts. Payloads are JSON-safe metadata only: raw bytes and secret-bearing
tokens are rejected, and HTTPS media URLs have query and fragment data removed.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import json
import math
import re
from typing import ClassVar, Mapping
from urllib.parse import urlsplit, urlunsplit


SCHEMA = "alpecca.video-companion.api.v1"
MAX_ID_CHARS = 128
MAX_TEXT_CHARS = 4_000
MAX_LABELS = 32
MAX_SCOPES = 32
MAX_EVIDENCE_IDS = 32
MAX_MEDIA_TIMESTAMP_SECONDS = 31_536_000.0

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://[^\s<>\"']+", re.IGNORECASE)
_SECRET_RE = re.compile(
    r"(?:\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password)\s*[:=]\s*\S+|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)
_FORBIDDEN_CONTRACT_KEYS = frozenset(
    {
        "bytes",
        "data_b64",
        "raw_bytes",
        "token",
        "secret",
        "authorization_header",
        "cooldown",
        "cooldown_seconds",
        "rate_limit",
        "rate_cap",
        "reaction_cap",
    }
)


class VideoAPIError(ValueError):
    """A Video Companion contract is malformed or unsafe."""


class ContractType(str, Enum):
    CREATE_SESSION_REQUEST = "create_session.request"
    CREATE_SESSION_RESPONSE = "create_session.response"
    TRANSCRIPT_EVENT = "transcript.event"
    VISUAL_DESCRIPTOR_EVENT = "visual_descriptor.event"
    PLAYBACK_EVENT = "playback.event"
    PLAYBACK_CONTROL_REQUEST = "playback_control.request"
    PLAYBACK_CONTROL_RESPONSE = "playback_control.response"
    STATUS_REQUEST = "status.request"
    STATUS_RESPONSE = "status.response"


class SourceKind(str, Enum):
    FILE = "file"
    LIVE = "live"
    STREAM = "stream"


class Surface(str, Enum):
    HOUSE_HQ = "house_hq"
    DISCORD = "discord"


class ActorKind(str, Enum):
    CREATOR = "creator"
    ALPECCA = "alpecca"
    GUEST = "guest"
    SYSTEM = "system"
    ADAPTER = "adapter"


class AuthorizationState(str, Enum):
    AUTHORIZED = "authorized"
    DENIED = "denied"
    NOT_REQUIRED = "not_required"


class PlaybackState(str, Enum):
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"
    STOPPED = "stopped"
    ENDED = "ended"


class PlaybackControl(str, Enum):
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"


class SessionState(str, Enum):
    CREATING = "creating"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


def _contains_bytes(value: object) -> bool:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return True
    if isinstance(value, Mapping):
        return any(_contains_bytes(key) or _contains_bytes(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_bytes(item) for item in value)
    return False


def _safe_text(
    value: object,
    name: str,
    *,
    maximum: int = MAX_TEXT_CHARS,
    redact_urls: bool = True,
) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)) or not isinstance(value, str):
        raise VideoAPIError(f"{name} must be text, never raw bytes")
    cleaned = " ".join(value.split())
    if not cleaned:
        raise VideoAPIError(f"{name} is required")
    if redact_urls:
        cleaned = _URL_RE.sub("[redacted-url]", cleaned)
    if _SECRET_RE.search(cleaned):
        raise VideoAPIError(f"{name} contains secret-like material")
    if len(cleaned) > maximum:
        raise VideoAPIError(f"{name} exceeds {maximum} characters")
    return cleaned


def _optional_text(value: object, name: str, *, maximum: int = MAX_TEXT_CHARS) -> str | None:
    if value is None:
        return None
    return _safe_text(value, name, maximum=maximum)


def _identifier(value: object, name: str) -> str:
    result = _safe_text(value, name, maximum=MAX_ID_CHARS, redact_urls=False)
    if _ID_RE.fullmatch(result) is None:
        raise VideoAPIError(
            f"{name} must be an opaque identifier containing letters, digits, '.', '_', ':', or '-'"
        )
    return result


def _enum(enum_type: type[Enum], value: object, name: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        raise VideoAPIError(f"invalid {name}: {value!r}") from None


def _number(
    value: object,
    name: str,
    *,
    minimum: float = 0.0,
    maximum: float = MAX_MEDIA_TIMESTAMP_SECONDS,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VideoAPIError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise VideoAPIError(f"{name} must be between {minimum:g} and {maximum:g}")
    return result


def _sequence(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise VideoAPIError("seq must be an integer between 1 and 2147483647")
    return value


def _safe_url(value: object) -> tuple[str, bool]:
    raw = _safe_text(value, "url", maximum=2_048, redact_urls=False)
    if _SECRET_RE.search(raw):
        raise VideoAPIError("url contains secret-like material")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise VideoAPIError("url is malformed") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise VideoAPIError("media URLs must use HTTPS and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise VideoAPIError("media URLs must not contain credentials")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    if _SECRET_RE.search(path):
        raise VideoAPIError("media URL path contains secret-like material")
    redacted = bool(parsed.query or parsed.fragment)
    return urlunsplit(("https", netloc, path, "", "")), redacted


def _bounded_strings(
    values: object, *, name: str, maximum: int
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise VideoAPIError(f"{name} must be a list")
    if len(values) > maximum:
        raise VideoAPIError(f"{name} exceeds {maximum} entries")
    result = tuple(_identifier(value, name) for value in values)
    if len(set(result)) != len(result):
        raise VideoAPIError(f"{name} contains duplicates")
    return result


@dataclass(frozen=True, slots=True)
class Actor:
    actor_id: str
    kind: ActorKind
    display_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor_id", _identifier(self.actor_id, "actor_id"))
        object.__setattr__(self, "kind", _enum(ActorKind, self.kind, "actor kind"))
        object.__setattr__(
            self,
            "display_name",
            _optional_text(self.display_name, "display_name", maximum=160),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "kind": self.kind.value,
            "display_name": self.display_name,
        }


@dataclass(frozen=True, slots=True)
class AuthorizationMetadata:
    state: AuthorizationState
    principal: str | None
    mechanism: str
    scopes: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    expires_at: float | None = None

    def __post_init__(self) -> None:
        state = _enum(AuthorizationState, self.state, "authorization state")
        principal = None if self.principal is None else _identifier(self.principal, "principal")
        mechanism = _identifier(self.mechanism, "authorization mechanism")
        scopes = _bounded_strings(self.scopes, name="scopes", maximum=MAX_SCOPES)
        evidence = _bounded_strings(
            self.evidence_ids, name="evidence_ids", maximum=MAX_EVIDENCE_IDS
        )
        expires = (
            None
            if self.expires_at is None
            else _number(self.expires_at, "authorization expires_at")
        )
        if state is AuthorizationState.AUTHORIZED:
            if principal is None or not scopes or not evidence or expires is None:
                raise VideoAPIError(
                    "authorized metadata requires principal, scopes, evidence_ids, and expires_at"
                )
        elif principal is not None:
            raise VideoAPIError("non-authorized metadata must not assert a principal")
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "principal", principal)
        object.__setattr__(self, "mechanism", mechanism)
        object.__setattr__(self, "scopes", scopes)
        object.__setattr__(self, "evidence_ids", evidence)
        object.__setattr__(self, "expires_at", expires)

    def allows(self, scope: str, *, now: float) -> bool:
        requested = _identifier(scope, "scope")
        current = _number(now, "now")
        return (
            self.state is AuthorizationState.AUTHORIZED
            and requested in self.scopes
            and self.expires_at is not None
            and current < self.expires_at
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "principal": self.principal,
            "mechanism": self.mechanism,
            "scopes": list(self.scopes),
            "evidence_ids": list(self.evidence_ids),
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class MediaReference:
    source_id: str
    source_kind: SourceKind
    label: str | None = None
    url: str | None = None
    url_redacted: bool = False

    def __post_init__(self) -> None:
        if type(self.url_redacted) is not bool:
            raise VideoAPIError("url_redacted must be boolean")
        source_id = _identifier(self.source_id, "source_id")
        kind = _enum(SourceKind, self.source_kind, "source_kind")
        label = _optional_text(self.label, "media label", maximum=256)
        url = self.url
        redacted = False
        if url is not None:
            if kind is SourceKind.FILE:
                raise VideoAPIError("file sources use opaque source_id metadata, not URLs")
            url, redacted = _safe_url(url)
        if self.url_redacted and not redacted:
            redacted = True
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "source_kind", kind)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "url_redacted", redacted)

    def as_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind.value,
            "label": self.label,
            "url": self.url,
            "url_redacted": self.url_redacted,
        }


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise VideoAPIError("contracts must never contain raw bytes")
    return value


class Contract:
    contract_type: ClassVar[ContractType]

    def as_dict(self) -> dict[str, object]:
        body = _json_value(self)
        if not isinstance(body, dict):
            raise TypeError("contract did not serialize to an object")
        return {"schema": SCHEMA, "type": self.contract_type.value, **body}

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class CreateSessionRequest(Contract):
    contract_type: ClassVar[ContractType] = ContractType.CREATE_SESSION_REQUEST

    request_id: str
    source: MediaReference
    surface: Surface
    actor: Actor
    authorization: AuthorizationMetadata

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _identifier(self.request_id, "request_id"))
        if not isinstance(self.source, MediaReference):
            raise VideoAPIError("source must be MediaReference")
        object.__setattr__(self, "surface", _enum(Surface, self.surface, "surface"))
        if not isinstance(self.actor, Actor):
            raise VideoAPIError("actor must be Actor")
        if not isinstance(self.authorization, AuthorizationMetadata):
            raise VideoAPIError("authorization must be AuthorizationMetadata")


@dataclass(frozen=True, slots=True)
class CreateSessionResponse(Contract):
    contract_type: ClassVar[ContractType] = ContractType.CREATE_SESSION_RESPONSE

    request_id: str
    accepted: bool
    session_id: str | None
    source_kind: SourceKind
    surface: Surface
    actor: Actor
    status: SessionState
    authorization: AuthorizationMetadata
    reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _identifier(self.request_id, "request_id"))
        if type(self.accepted) is not bool:
            raise VideoAPIError("accepted must be boolean")
        session_id = None if self.session_id is None else _identifier(self.session_id, "session_id")
        if self.accepted and session_id is None:
            raise VideoAPIError("accepted session response requires session_id")
        if not self.accepted and session_id is not None:
            raise VideoAPIError("rejected session response must not include session_id")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "source_kind", _enum(SourceKind, self.source_kind, "source_kind"))
        object.__setattr__(self, "surface", _enum(Surface, self.surface, "surface"))
        if not isinstance(self.actor, Actor):
            raise VideoAPIError("actor must be Actor")
        object.__setattr__(self, "status", _enum(SessionState, self.status, "status"))
        if not isinstance(self.authorization, AuthorizationMetadata):
            raise VideoAPIError("authorization must be AuthorizationMetadata")
        object.__setattr__(self, "reason", _optional_text(self.reason, "reason", maximum=256))


@dataclass(frozen=True, slots=True)
class EventContract(Contract):
    session_id: str
    seq: int
    turn_id: str
    media_timestamp: float
    source_kind: SourceKind
    surface: Surface
    actor: Actor

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _identifier(self.session_id, "session_id"))
        object.__setattr__(self, "seq", _sequence(self.seq))
        object.__setattr__(self, "turn_id", _identifier(self.turn_id, "turn_id"))
        object.__setattr__(
            self,
            "media_timestamp",
            _number(self.media_timestamp, "media_timestamp"),
        )
        object.__setattr__(self, "source_kind", _enum(SourceKind, self.source_kind, "source_kind"))
        object.__setattr__(self, "surface", _enum(Surface, self.surface, "surface"))
        if not isinstance(self.actor, Actor):
            raise VideoAPIError("actor must be Actor")


@dataclass(frozen=True, slots=True)
class TranscriptEvent(EventContract):
    contract_type: ClassVar[ContractType] = ContractType.TRANSCRIPT_EVENT

    text: str
    final: bool
    language: str | None = None

    def __post_init__(self) -> None:
        super(TranscriptEvent, self).__post_init__()
        object.__setattr__(self, "text", _safe_text(self.text, "transcript text"))
        if type(self.final) is not bool:
            raise VideoAPIError("final must be boolean")
        language = None if self.language is None else _identifier(self.language, "language")
        object.__setattr__(self, "language", language)


@dataclass(frozen=True, slots=True)
class VisualDescriptorEvent(EventContract):
    contract_type: ClassVar[ContractType] = ContractType.VISUAL_DESCRIPTOR_EVENT

    descriptor: str
    confidence: float
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super(VisualDescriptorEvent, self).__post_init__()
        object.__setattr__(self, "descriptor", _safe_text(self.descriptor, "descriptor"))
        object.__setattr__(
            self,
            "confidence",
            _number(self.confidence, "confidence", maximum=1.0),
        )
        object.__setattr__(
            self,
            "labels",
            _bounded_strings(self.labels, name="labels", maximum=MAX_LABELS),
        )


@dataclass(frozen=True, slots=True)
class PlaybackEvent(EventContract):
    contract_type: ClassVar[ContractType] = ContractType.PLAYBACK_EVENT

    position: float
    state: PlaybackState
    duration: float | None = None

    def __post_init__(self) -> None:
        super(PlaybackEvent, self).__post_init__()
        position = _number(self.position, "position")
        if position != self.media_timestamp:
            raise VideoAPIError("position must match media_timestamp")
        duration = None if self.duration is None else _number(self.duration, "duration")
        if duration is not None and position > duration:
            raise VideoAPIError("position must not exceed duration")
        object.__setattr__(self, "position", position)
        object.__setattr__(self, "duration", duration)
        object.__setattr__(self, "state", _enum(PlaybackState, self.state, "playback state"))


@dataclass(frozen=True, slots=True)
class PlaybackControlRequest(EventContract):
    contract_type: ClassVar[ContractType] = ContractType.PLAYBACK_CONTROL_REQUEST

    request_id: str
    action: PlaybackControl
    authorization: AuthorizationMetadata

    def __post_init__(self) -> None:
        super(PlaybackControlRequest, self).__post_init__()
        object.__setattr__(self, "request_id", _identifier(self.request_id, "request_id"))
        object.__setattr__(self, "action", _enum(PlaybackControl, self.action, "action"))
        if not isinstance(self.authorization, AuthorizationMetadata):
            raise VideoAPIError("authorization must be AuthorizationMetadata")


@dataclass(frozen=True, slots=True)
class PlaybackControlResponse(EventContract):
    contract_type: ClassVar[ContractType] = ContractType.PLAYBACK_CONTROL_RESPONSE

    request_id: str
    action: PlaybackControl
    accepted: bool
    state: PlaybackState
    authorization: AuthorizationMetadata
    reason: str | None = None

    def __post_init__(self) -> None:
        super(PlaybackControlResponse, self).__post_init__()
        object.__setattr__(self, "request_id", _identifier(self.request_id, "request_id"))
        object.__setattr__(self, "action", _enum(PlaybackControl, self.action, "action"))
        if type(self.accepted) is not bool:
            raise VideoAPIError("accepted must be boolean")
        object.__setattr__(self, "state", _enum(PlaybackState, self.state, "state"))
        if not isinstance(self.authorization, AuthorizationMetadata):
            raise VideoAPIError("authorization must be AuthorizationMetadata")
        object.__setattr__(self, "reason", _optional_text(self.reason, "reason", maximum=256))


@dataclass(frozen=True, slots=True)
class StatusRequest(EventContract):
    contract_type: ClassVar[ContractType] = ContractType.STATUS_REQUEST

    authorization: AuthorizationMetadata

    def __post_init__(self) -> None:
        super(StatusRequest, self).__post_init__()
        if not isinstance(self.authorization, AuthorizationMetadata):
            raise VideoAPIError("authorization must be AuthorizationMetadata")


@dataclass(frozen=True, slots=True)
class StatusResponse(EventContract):
    contract_type: ClassVar[ContractType] = ContractType.STATUS_RESPONSE

    session_state: SessionState
    playback_state: PlaybackState
    position: float
    authorization: AuthorizationMetadata
    detail: str | None = None

    def __post_init__(self) -> None:
        super(StatusResponse, self).__post_init__()
        object.__setattr__(
            self, "session_state", _enum(SessionState, self.session_state, "session_state")
        )
        object.__setattr__(
            self, "playback_state", _enum(PlaybackState, self.playback_state, "playback_state")
        )
        position = _number(self.position, "position")
        if position != self.media_timestamp:
            raise VideoAPIError("position must match media_timestamp")
        object.__setattr__(self, "position", position)
        if not isinstance(self.authorization, AuthorizationMetadata):
            raise VideoAPIError("authorization must be AuthorizationMetadata")
        object.__setattr__(self, "detail", _optional_text(self.detail, "detail", maximum=512))


def _object(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise VideoAPIError(f"{name} must be an object")
    return value


def _strict(value: Mapping[str, object], allowed: set[str], name: str) -> None:
    keys = set(value)
    forbidden = keys & _FORBIDDEN_CONTRACT_KEYS
    if forbidden:
        raise VideoAPIError(f"{name} contains forbidden field: {sorted(forbidden)[0]}")
    unknown = keys - allowed
    if unknown:
        raise VideoAPIError(f"{name} contains unknown field: {sorted(unknown)[0]}")


def _actor(value: object) -> Actor:
    body = _object(value, "actor")
    _strict(body, {"actor_id", "kind", "display_name"}, "actor")
    return Actor(
        actor_id=body.get("actor_id"),  # type: ignore[arg-type]
        kind=body.get("kind"),  # type: ignore[arg-type]
        display_name=body.get("display_name"),  # type: ignore[arg-type]
    )


def _authorization(value: object) -> AuthorizationMetadata:
    body = _object(value, "authorization")
    _strict(
        body,
        {"state", "principal", "mechanism", "scopes", "evidence_ids", "expires_at"},
        "authorization",
    )
    return AuthorizationMetadata(
        state=body.get("state"),  # type: ignore[arg-type]
        principal=body.get("principal"),  # type: ignore[arg-type]
        mechanism=body.get("mechanism"),  # type: ignore[arg-type]
        scopes=body.get("scopes") or (),  # type: ignore[arg-type]
        evidence_ids=body.get("evidence_ids") or (),  # type: ignore[arg-type]
        expires_at=body.get("expires_at"),  # type: ignore[arg-type]
    )


def _source(value: object) -> MediaReference:
    body = _object(value, "source")
    _strict(body, {"source_id", "source_kind", "label", "url", "url_redacted"}, "source")
    return MediaReference(
        source_id=body.get("source_id"),  # type: ignore[arg-type]
        source_kind=body.get("source_kind"),  # type: ignore[arg-type]
        label=body.get("label"),  # type: ignore[arg-type]
        url=body.get("url"),  # type: ignore[arg-type]
        url_redacted=body.get("url_redacted", False),  # type: ignore[arg-type]
    )


_EVENT_FIELDS = {
    "session_id",
    "seq",
    "turn_id",
    "media_timestamp",
    "source_kind",
    "surface",
    "actor",
}


def _event_args(body: Mapping[str, object]) -> dict[str, object]:
    return {
        "session_id": body.get("session_id"),
        "seq": body.get("seq"),
        "turn_id": body.get("turn_id"),
        "media_timestamp": body.get("media_timestamp"),
        "source_kind": body.get("source_kind"),
        "surface": body.get("surface"),
        "actor": _actor(body.get("actor")),
    }


def contract_from_dict(payload: Mapping[str, object]) -> Contract:
    """Parse one strict JSON-safe contract mapping."""

    if _contains_bytes(payload):
        raise VideoAPIError("contracts must never contain raw bytes")
    body = _object(payload, "contract")
    if body.get("schema") != SCHEMA:
        raise VideoAPIError("contract schema is unsupported")
    kind = _enum(ContractType, body.get("type"), "contract type")
    common = {"schema", "type"}

    if kind is ContractType.CREATE_SESSION_REQUEST:
        _strict(body, common | {"request_id", "source", "surface", "actor", "authorization"}, "contract")
        return CreateSessionRequest(
            request_id=body.get("request_id"),  # type: ignore[arg-type]
            source=_source(body.get("source")),
            surface=body.get("surface"),  # type: ignore[arg-type]
            actor=_actor(body.get("actor")),
            authorization=_authorization(body.get("authorization")),
        )
    if kind is ContractType.CREATE_SESSION_RESPONSE:
        _strict(
            body,
            common
            | {"request_id", "accepted", "session_id", "source_kind", "surface", "actor", "status", "authorization", "reason"},
            "contract",
        )
        return CreateSessionResponse(
            request_id=body.get("request_id"),  # type: ignore[arg-type]
            accepted=body.get("accepted"),  # type: ignore[arg-type]
            session_id=body.get("session_id"),  # type: ignore[arg-type]
            source_kind=body.get("source_kind"),  # type: ignore[arg-type]
            surface=body.get("surface"),  # type: ignore[arg-type]
            actor=_actor(body.get("actor")),
            status=body.get("status"),  # type: ignore[arg-type]
            authorization=_authorization(body.get("authorization")),
            reason=body.get("reason"),  # type: ignore[arg-type]
        )

    event_args = _event_args(body)
    if kind is ContractType.TRANSCRIPT_EVENT:
        _strict(body, common | _EVENT_FIELDS | {"text", "final", "language"}, "contract")
        return TranscriptEvent(
            **event_args,
            text=body.get("text"),
            final=body.get("final"),
            language=body.get("language"),
        )  # type: ignore[arg-type]
    if kind is ContractType.VISUAL_DESCRIPTOR_EVENT:
        _strict(body, common | _EVENT_FIELDS | {"descriptor", "confidence", "labels"}, "contract")
        return VisualDescriptorEvent(
            **event_args,
            descriptor=body.get("descriptor"),
            confidence=body.get("confidence"),
            labels=body.get("labels") or (),
        )  # type: ignore[arg-type]
    if kind is ContractType.PLAYBACK_EVENT:
        _strict(body, common | _EVENT_FIELDS | {"position", "state", "duration"}, "contract")
        return PlaybackEvent(
            **event_args,
            position=body.get("position"),
            state=body.get("state"),
            duration=body.get("duration"),
        )  # type: ignore[arg-type]
    if kind is ContractType.PLAYBACK_CONTROL_REQUEST:
        _strict(body, common | _EVENT_FIELDS | {"request_id", "action", "authorization"}, "contract")
        return PlaybackControlRequest(
            **event_args,
            request_id=body.get("request_id"),
            action=body.get("action"),
            authorization=_authorization(body.get("authorization")),
        )  # type: ignore[arg-type]
    if kind is ContractType.PLAYBACK_CONTROL_RESPONSE:
        _strict(
            body,
            common | _EVENT_FIELDS | {"request_id", "action", "accepted", "state", "authorization", "reason"},
            "contract",
        )
        return PlaybackControlResponse(
            **event_args,
            request_id=body.get("request_id"),
            action=body.get("action"),
            accepted=body.get("accepted"),
            state=body.get("state"),
            authorization=_authorization(body.get("authorization")),
            reason=body.get("reason"),
        )  # type: ignore[arg-type]
    if kind is ContractType.STATUS_REQUEST:
        _strict(body, common | _EVENT_FIELDS | {"authorization"}, "contract")
        return StatusRequest(
            **event_args,
            authorization=_authorization(body.get("authorization")),
        )  # type: ignore[arg-type]
    if kind is ContractType.STATUS_RESPONSE:
        _strict(
            body,
            common | _EVENT_FIELDS | {"session_state", "playback_state", "position", "authorization", "detail"},
            "contract",
        )
        return StatusResponse(
            **event_args,
            session_state=body.get("session_state"),
            playback_state=body.get("playback_state"),
            position=body.get("position"),
            authorization=_authorization(body.get("authorization")),
            detail=body.get("detail"),
        )  # type: ignore[arg-type]
    raise VideoAPIError("contract type is unsupported")


__all__ = [
    "Actor",
    "ActorKind",
    "AuthorizationMetadata",
    "AuthorizationState",
    "Contract",
    "ContractType",
    "CreateSessionRequest",
    "CreateSessionResponse",
    "EventContract",
    "MAX_MEDIA_TIMESTAMP_SECONDS",
    "MediaReference",
    "PlaybackControl",
    "PlaybackControlRequest",
    "PlaybackControlResponse",
    "PlaybackEvent",
    "PlaybackState",
    "SCHEMA",
    "SessionState",
    "SourceKind",
    "StatusRequest",
    "StatusResponse",
    "Surface",
    "TranscriptEvent",
    "VideoAPIError",
    "VisualDescriptorEvent",
    "contract_from_dict",
]
