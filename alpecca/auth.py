"""Authorization primitives kept separate from Alpecca's public identity."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


AUTH_ENV_NAME = "ALPECCA_AUTH_SECRET"
CREDENTIAL_TARGET = "Alpecca/ServerAuthorization"
CREATOR_PASSWORD_ENV_NAME = "ALPECCA_CREATOR_PASSWORD"
CREATOR_PASSWORD_CREDENTIAL_TARGET = "Alpecca/CreatorPassword"
AUTHORIZATION_HEADER = "X-Alpecca-Authorization"
SESSION_COOKIE_NAME = "alpecca_authorization"

_SESSION_VERSION = 1
_MAX_BOOTSTRAP_CODES = 32
_MAX_CREDENTIAL_CHARS = 4096
_MAX_PASSWORD_ATTEMPTS = 5
PASSWORD_WINDOW_SECONDS = 60
_PROCESS_SECRET: str | None = None
_PROCESS_SECRET_LOCK = threading.Lock()

_PUBLIC_IDENTITY_HEADERS = frozenset(
    {"authorization", "x-alpecca-identity", "x-alpecca-token"}
)
_PUBLIC_IDENTITY_QUERIES = frozenset(
    {"access_token", "alpecca_token", "identity", "token"}
)
_PUBLIC_IDENTITY_COOKIES = frozenset({"alpecca_token"})


def _new_secret() -> str:
    return secrets.token_urlsafe(48)


def _test_environment(environ: Mapping[str, str]) -> bool:
    return "PYTEST_CURRENT_TEST" in environ or "pytest" in sys.modules


def _process_authorization_secret() -> str:
    global _PROCESS_SECRET
    with _PROCESS_SECRET_LOCK:
        if _PROCESS_SECRET is None:
            _PROCESS_SECRET = _new_secret()
        return _PROCESS_SECRET


def _credential_error_code(exc: BaseException) -> int | None:
    code = getattr(exc, "winerror", None)
    if isinstance(code, int):
        return code
    if exc.args and isinstance(exc.args[0], int):
        return exc.args[0]
    return None


def _decode_credential_blob(blob: Any) -> str:
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    if isinstance(blob, bytes):
        # pywin32's CredWrite stores str blobs as UTF-16-LE; blobs written by
        # other tools are typically UTF-8. For ASCII-range secrets like ours,
        # embedded NUL bytes reliably identify the UTF-16-LE form -- decoding
        # that as UTF-8 would "succeed" and silently NUL-garble the secret.
        encoding = "utf-16-le" if b"\x00" in blob else "utf-8"
        try:
            value = blob.decode(encoding).rstrip("\x00")
        except UnicodeDecodeError as exc:
            raise RuntimeError("The stored authorization credential is invalid.") from exc
    elif isinstance(blob, str):
        value = blob
    else:
        value = ""
    if not value or not value.strip():
        raise RuntimeError("The stored authorization credential is empty.")
    return value


def _load_or_create_windows_credential() -> str:
    try:
        import win32cred
    except ImportError as exc:
        raise RuntimeError(
            "Windows Credential Manager support requires pywin32."
        ) from exc

    try:
        credential = win32cred.CredRead(
            CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0
        )
    except Exception as exc:
        if _credential_error_code(exc) not in {2, 1168}:
            raise RuntimeError("Could not read the authorization credential.") from exc
    else:
        return _decode_credential_blob(credential.get("CredentialBlob"))

    generated = _new_secret()
    try:
        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": CREDENTIAL_TARGET,
                # pywin32 requires a str here (rejects bytes with a TypeError
                # on cold start) and stores it as UTF-16-LE; the reader above
                # detects and reverses that encoding.
                "CredentialBlob": generated,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                "UserName": "Alpecca",
                "Comment": "Alpecca server authorization secret",
            },
            0,
        )
        credential = win32cred.CredRead(
            CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0
        )
    except Exception as exc:
        raise RuntimeError("Could not store the authorization credential.") from exc
    return _decode_credential_blob(credential.get("CredentialBlob"))


def _read_windows_credential(target: str) -> str | None:
    """Read one generic Windows credential without creating or changing it."""
    try:
        import win32cred
    except ImportError as exc:
        raise RuntimeError(
            "Windows Credential Manager support requires pywin32."
        ) from exc
    try:
        credential = win32cred.CredRead(
            target, win32cred.CRED_TYPE_GENERIC, 0
        )
    except Exception as exc:
        if _credential_error_code(exc) in {2, 1168}:
            return None
        raise RuntimeError("Could not read the creator password credential.") from exc
    return _decode_credential_blob(credential.get("CredentialBlob"))


def set_windows_creator_password(password: str) -> None:
    """Store the creator login password in Windows Credential Manager.

    This never changes the separate server authorization secret, so existing
    bearer credentials are not revoked. Callers must obtain the password from
    an interactive prompt or deployment secret, never from source control.
    """
    value = str(password or "")
    if len(value) < 8 or len(value) > 256:
        raise ValueError("creator password must contain 8 to 256 characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError("creator password contains control characters")
    try:
        import win32cred
    except ImportError as exc:
        raise RuntimeError(
            "Windows Credential Manager support requires pywin32."
        ) from exc
    try:
        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": CREATOR_PASSWORD_CREDENTIAL_TARGET,
                "CredentialBlob": value,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                "UserName": "CreatorJD",
                "Comment": "Alpecca creator login password",
            },
            0,
        )
    except Exception as exc:
        raise RuntimeError("Could not store the creator password credential.") from exc


def load_creator_password(
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Load the optional creator login password from a protected provider."""
    env = os.environ if environ is None else environ
    if CREATOR_PASSWORD_ENV_NAME in env:
        supplied = env[CREATOR_PASSWORD_ENV_NAME]
        if not isinstance(supplied, str) or not supplied:
            raise ValueError(f"{CREATOR_PASSWORD_ENV_NAME} must not be empty.")
        return supplied
    if os.name == "nt" and not _test_environment(env):
        return _read_windows_credential(CREATOR_PASSWORD_CREDENTIAL_TARGET)
    return None


def load_or_create_authorization_secret(
    home: Path,
    environ: MutableMapping[str, str] | None = None,
) -> str:
    """Load the protected server secret without writing plaintext to disk."""

    Path(home)  # Validate the caller's path-like value; it is never a secret store.
    env = os.environ if environ is None else environ
    if AUTH_ENV_NAME in env:
        supplied = env[AUTH_ENV_NAME]
        if not isinstance(supplied, str) or not supplied.strip():
            raise ValueError(f"{AUTH_ENV_NAME} must not be empty.")
        return supplied
    if os.name == "nt" and not _test_environment(env):
        return _load_or_create_windows_credential()
    return _process_authorization_secret()


@dataclass(frozen=True, slots=True)
class AuthDecision:
    """Secret-free result suitable for authorization audit records."""

    allowed: bool
    mechanism: str
    reason: str
    principal: str = ""
    issued_at: int | None = None
    expires_at: int | None = None
    remote_scope: str = "unknown"
    public_identity_ignored: bool = False

    @property
    def authorized(self) -> bool:
        return self.allowed

    @property
    def audit(self) -> dict[str, str | int | bool | None]:
        return {
            "allowed": self.allowed,
            "mechanism": self.mechanism,
            "reason": self.reason,
            "principal": self.principal or None,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "remote_scope": self.remote_scope,
            "public_identity_ignored": self.public_identity_ignored,
        }

    def as_audit_metadata(self) -> dict[str, str | int | bool | None]:
        return self.audit


@dataclass(frozen=True, slots=True)
class SessionCookie:
    """Signed session value and the mandatory safe cookie attributes."""

    value: str = field(repr=False)
    expires_at: int
    max_age: int
    name: str = SESSION_COOKIE_NAME
    secure: bool = True
    httponly: bool = True
    samesite: str = "strict"
    path: str = "/"

    def set_cookie_kwargs(self) -> dict[str, str | int | bool]:
        return {
            "max_age": self.max_age,
            "path": self.path,
            "secure": self.secure,
            "httponly": True,
            "samesite": self.samesite,
        }


@dataclass(frozen=True, slots=True)
class _BootstrapRecord:
    created_at: int
    expires_at: int


def _b64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _b64url_decode(payload: str) -> bytes:
    if not payload or len(payload) > _MAX_CREDENTIAL_CHARS:
        raise ValueError("invalid encoded value")
    encoded = payload.encode("ascii")
    encoded += b"=" * (-len(encoded) % 4)
    return base64.b64decode(encoded, altchars=b"-_", validate=True)


def _mapping_value(mapping: Mapping[str, Any] | None, name: str) -> str:
    if not mapping:
        return ""
    wanted = name.casefold()
    for key, value in mapping.items():
        if str(key).casefold() == wanted:
            return value if isinstance(value, str) else str(value)
    return ""


def _contains_named_value(
    mapping: Mapping[str, Any] | None, names: frozenset[str]
) -> bool:
    if not mapping:
        return False
    return any(
        str(key).casefold() in names and value not in (None, "")
        for key, value in mapping.items()
    )


def is_loopback_address(remote_addr: str | tuple[Any, ...] | None) -> bool:
    """Return true only for an explicit loopback peer address."""

    if isinstance(remote_addr, tuple):
        remote_addr = str(remote_addr[0]) if remote_addr else ""
    raw = str(remote_addr or "").strip()
    if not raw:
        return False
    if raw.casefold() == "localhost":
        return True
    if raw.startswith("[") and "]" in raw:
        raw = raw[1 : raw.index("]")]
    elif raw.count(":") == 1 and "." in raw:
        host, possible_port = raw.rsplit(":", 1)
        if possible_port.isdigit():
            raw = host
    raw = raw.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


class SessionAuthority:
    """Mint and validate bounded bootstrap grants and signed sessions."""

    authorization_header = AUTHORIZATION_HEADER
    cookie_name = SESSION_COOKIE_NAME

    def __init__(
        self,
        secret: str,
        session_ttl_s: int = 28800,
        bootstrap_ttl_s: int = 60,
        creator_password: str | None = None,
    ) -> None:
        if not isinstance(secret, str) or not secret.strip():
            raise ValueError("Authorization secret must not be empty.")
        if int(session_ttl_s) <= 0 or int(bootstrap_ttl_s) <= 0:
            raise ValueError("Authorization TTLs must be positive.")
        self._secret = secret.encode("utf-8")
        self.session_ttl_s = int(session_ttl_s)
        self.bootstrap_ttl_s = int(bootstrap_ttl_s)
        self._bearer_digest = self._digest(b"bearer", self._secret)
        self._creator_password_digest = (
            self._digest(b"creator-password-v1", creator_password.encode("utf-8"))
            if creator_password else None
        )
        self._bootstrap: OrderedDict[bytes, _BootstrapRecord] = OrderedDict()
        self._bootstrap_lock = threading.RLock()
        self._password_failures: OrderedDict[str, list[int]] = OrderedDict()
        self._password_lock = threading.RLock()

    @staticmethod
    def _now(now: float | int | None = None) -> int:
        return int(time.time() if now is None else now)

    def _digest(self, purpose: bytes, value: bytes) -> bytes:
        return hmac.new(
            self._secret, purpose + b"\x00" + value, hashlib.sha256
        ).digest()

    def _session_signature(self, encoded_payload: str) -> bytes:
        return self._digest(b"session-v1", encoded_payload.encode("ascii"))

    @staticmethod
    def _remote_scope(remote_addr: str | tuple[Any, ...] | None) -> str:
        if not remote_addr:
            return "unknown"
        return "loopback" if is_loopback_address(remote_addr) else "remote"

    def _prune_bootstrap_locked(self, now: int) -> int:
        expired = [
            digest
            for digest, record in self._bootstrap.items()
            if record.expires_at <= now
        ]
        for digest in expired:
            self._bootstrap.pop(digest, None)
        while len(self._bootstrap) > _MAX_BOOTSTRAP_CODES:
            self._bootstrap.popitem(last=False)
        return len(expired)

    def prune_bootstrap_codes(self, now: float | int | None = None) -> int:
        """Remove expired bootstrap grants and return the number removed."""

        with self._bootstrap_lock:
            return self._prune_bootstrap_locked(self._now(now))

    @property
    def active_bootstrap_count(self) -> int:
        self.prune_bootstrap_codes()
        with self._bootstrap_lock:
            return len(self._bootstrap)

    def issue_bootstrap_code(
        self,
        remote_addr: str | tuple[Any, ...] | None = "127.0.0.1",
        *,
        now: float | int | None = None,
    ) -> str:
        """Mint a short-lived code only for a loopback bootstrap flow."""

        if not is_loopback_address(remote_addr):
            raise PermissionError("Bootstrap codes are loopback-only.")
        current = self._now(now)
        with self._bootstrap_lock:
            self._prune_bootstrap_locked(current)
            while len(self._bootstrap) >= _MAX_BOOTSTRAP_CODES:
                self._bootstrap.popitem(last=False)
            while True:
                code = "ab1_" + secrets.token_urlsafe(24)
                digest = self._digest(b"bootstrap-v1", code.encode("ascii"))
                if digest not in self._bootstrap:
                    break
            self._bootstrap[digest] = _BootstrapRecord(
                created_at=current,
                expires_at=current + self.bootstrap_ttl_s,
            )
        return code

    create_bootstrap_code = issue_bootstrap_code

    def consume_bootstrap_code(
        self,
        code: str,
        remote_addr: str | tuple[Any, ...] | None,
        *,
        now: float | int | None = None,
    ) -> AuthDecision:
        """Consume a valid bootstrap code exactly once from a loopback peer."""

        scope = self._remote_scope(remote_addr)
        if scope != "loopback":
            return AuthDecision(False, "bootstrap", "loopback_required", remote_scope=scope)
        if not isinstance(code, str) or not code.startswith("ab1_") or len(code) > 256:
            return AuthDecision(False, "bootstrap", "invalid_code", remote_scope=scope)
        current = self._now(now)
        digest = self._digest(b"bootstrap-v1", code.encode("utf-8"))
        with self._bootstrap_lock:
            self._prune_bootstrap_locked(current)
            record = self._bootstrap.pop(digest, None)
        if record is None:
            return AuthDecision(
                False, "bootstrap", "invalid_or_expired", remote_scope=scope
            )
        return AuthDecision(
            True,
            "bootstrap",
            "accepted",
            principal="creator",
            issued_at=record.created_at,
            expires_at=record.expires_at,
            remote_scope=scope,
        )

    def issue_session_value(self, *, now: float | int | None = None) -> str:
        """Return a signed, opaque-to-the-client authorization session value."""

        issued_at = self._now(now)
        payload = {
            "exp": issued_at + self.session_ttl_s,
            "iat": issued_at,
            "sid": secrets.token_urlsafe(12),
            "typ": "session",
            "v": _SESSION_VERSION,
        }
        encoded = _b64url_encode(
            json.dumps(
                payload, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        )
        signature = _b64url_encode(self._session_signature(encoded))
        return f"{encoded}.{signature}"

    mint_session = issue_session_value

    def issue_session_cookie(
        self,
        *,
        secure: bool = True,
        now: float | int | None = None,
    ) -> SessionCookie:
        """Return a signed value with non-optional HttpOnly cookie metadata."""

        issued_at = self._now(now)
        value = self.issue_session_value(now=issued_at)
        return SessionCookie(
            value=value,
            expires_at=issued_at + self.session_ttl_s,
            max_age=self.session_ttl_s,
            secure=bool(secure),
        )

    mint_session_cookie = issue_session_cookie

    def exchange_bootstrap_code(
        self,
        code: str,
        remote_addr: str | tuple[Any, ...] | None,
        *,
        secure: bool = True,
        now: float | int | None = None,
    ) -> tuple[AuthDecision, SessionCookie | None]:
        """Consume a bootstrap grant and mint its session in one operation."""

        current = self._now(now)
        decision = self.consume_bootstrap_code(
            code, remote_addr, now=current
        )
        if not decision.allowed:
            return decision, None
        return decision, self.issue_session_cookie(secure=secure, now=current)

    def validate_bearer(
        self, headers: Mapping[str, Any] | None
    ) -> AuthDecision:
        """Validate only X-Alpecca-Authorization using a fixed-size digest."""

        supplied = _mapping_value(headers, AUTHORIZATION_HEADER)
        if not supplied:
            return AuthDecision(False, "bearer", "missing")
        if supplied[:7].casefold() == "bearer ":
            supplied = supplied[7:]
        if not supplied or len(supplied) > _MAX_CREDENTIAL_CHARS:
            return AuthDecision(False, "bearer", "malformed")
        candidate = self._digest(b"bearer", supplied.encode("utf-8"))
        if not hmac.compare_digest(candidate, self._bearer_digest):
            return AuthDecision(False, "bearer", "rejected")
        return AuthDecision(True, "bearer", "accepted", principal="creator")

    @property
    def password_configured(self) -> bool:
        return self._creator_password_digest is not None

    @staticmethod
    def _password_remote_key(remote_addr: str | tuple[Any, ...] | None) -> str:
        if isinstance(remote_addr, tuple):
            remote_addr = remote_addr[0] if remote_addr else ""
        return str(remote_addr or "unknown")[:160]

    def validate_password(
        self,
        password: str,
        remote_addr: str | tuple[Any, ...] | None,
        *,
        now: float | int | None = None,
    ) -> AuthDecision:
        """Validate the creator password with bounded per-peer throttling."""
        scope = self._remote_scope(remote_addr)
        if self._creator_password_digest is None:
            return AuthDecision(
                False, "password", "not_configured", remote_scope=scope
            )
        if not isinstance(password, str) or not password or len(password) > 256:
            return AuthDecision(False, "password", "malformed", remote_scope=scope)
        current = self._now(now)
        remote_key = self._password_remote_key(remote_addr)
        with self._password_lock:
            attempts = [
                ts for ts in self._password_failures.get(remote_key, [])
                if current - ts < PASSWORD_WINDOW_SECONDS
            ]
            if len(attempts) >= _MAX_PASSWORD_ATTEMPTS:
                self._password_failures[remote_key] = attempts
                return AuthDecision(
                    False, "password", "rate_limited", remote_scope=scope
                )
        candidate = self._digest(
            b"creator-password-v1", password.encode("utf-8")
        )
        if not hmac.compare_digest(candidate, self._creator_password_digest):
            with self._password_lock:
                attempts.append(current)
                self._password_failures[remote_key] = attempts
                while len(self._password_failures) > 256:
                    self._password_failures.popitem(last=False)
            return AuthDecision(False, "password", "rejected", remote_scope=scope)
        with self._password_lock:
            self._password_failures.pop(remote_key, None)
        return AuthDecision(
            True, "password", "accepted", principal="creator",
            remote_scope=scope,
        )

    def exchange_password(
        self,
        password: str,
        remote_addr: str | tuple[Any, ...] | None,
        *,
        secure: bool = True,
        now: float | int | None = None,
    ) -> tuple[AuthDecision, SessionCookie | None]:
        """Validate a password and mint the same bounded HttpOnly session."""
        current = self._now(now)
        decision = self.validate_password(
            password, remote_addr, now=current
        )
        if not decision.allowed:
            return decision, None
        return decision, self.issue_session_cookie(secure=secure, now=current)

    def validate_session_cookie(
        self,
        value: str,
        *,
        now: float | int | None = None,
    ) -> AuthDecision:
        """Validate signature, shape, issuance time, and session expiration."""

        if not isinstance(value, str) or not value or len(value) > _MAX_CREDENTIAL_CHARS:
            return AuthDecision(False, "session_cookie", "missing_or_malformed")
        parts = value.split(".")
        if len(parts) != 2:
            return AuthDecision(False, "session_cookie", "malformed")
        encoded, encoded_signature = parts
        try:
            supplied_signature = _b64url_decode(encoded_signature)
        except (UnicodeError, ValueError):
            return AuthDecision(False, "session_cookie", "malformed")
        try:
            expected_signature = self._session_signature(encoded)
        except UnicodeError:
            return AuthDecision(False, "session_cookie", "malformed")
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return AuthDecision(False, "session_cookie", "signature_invalid")
        try:
            payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
        except (UnicodeError, ValueError, json.JSONDecodeError):
            return AuthDecision(False, "session_cookie", "payload_invalid")
        if not isinstance(payload, dict):
            return AuthDecision(False, "session_cookie", "payload_invalid")
        issued_at = payload.get("iat")
        expires_at = payload.get("exp")
        if (
            payload.get("v") != _SESSION_VERSION
            or payload.get("typ") != "session"
            or not isinstance(payload.get("sid"), str)
            or not payload["sid"]
            or isinstance(issued_at, bool)
            or not isinstance(issued_at, int)
            or isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
        ):
            return AuthDecision(False, "session_cookie", "payload_invalid")
        current = self._now(now)
        if issued_at > current + 30:
            return AuthDecision(False, "session_cookie", "issued_in_future")
        if expires_at <= current:
            return AuthDecision(
                False,
                "session_cookie",
                "expired",
                issued_at=issued_at,
                expires_at=expires_at,
            )
        if expires_at <= issued_at or expires_at - issued_at > self.session_ttl_s:
            return AuthDecision(False, "session_cookie", "ttl_invalid")
        return AuthDecision(
            True,
            "session_cookie",
            "accepted",
            principal="creator",
            issued_at=issued_at,
            expires_at=expires_at,
        )

    validate_cookie = validate_session_cookie

    def authorize_request(
        self,
        headers: Mapping[str, Any] | None = None,
        cookies: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        *,
        now: float | int | None = None,
    ) -> AuthDecision:
        """Authorize only the protected header or signed session cookie."""

        ignored_public_identity = (
            _contains_named_value(headers, _PUBLIC_IDENTITY_HEADERS)
            or _contains_named_value(query, _PUBLIC_IDENTITY_QUERIES)
            or _contains_named_value(cookies, _PUBLIC_IDENTITY_COOKIES)
        )
        protected_header = _mapping_value(headers, AUTHORIZATION_HEADER)
        if protected_header:
            decision = self.validate_bearer(headers)
        else:
            session = _mapping_value(cookies, SESSION_COOKIE_NAME)
            decision = (
                self.validate_session_cookie(session, now=now)
                if session
                else AuthDecision(False, "none", "credentials_missing")
            )
        if ignored_public_identity:
            decision = replace(decision, public_identity_ignored=True)
        return decision


__all__ = [
    "AUTH_ENV_NAME",
    "AUTHORIZATION_HEADER",
    "CREDENTIAL_TARGET",
    "CREATOR_PASSWORD_CREDENTIAL_TARGET",
    "CREATOR_PASSWORD_ENV_NAME",
    "PASSWORD_WINDOW_SECONDS",
    "SESSION_COOKIE_NAME",
    "AuthDecision",
    "SessionAuthority",
    "SessionCookie",
    "is_loopback_address",
    "load_creator_password",
    "load_or_create_authorization_secret",
    "set_windows_creator_password",
]
