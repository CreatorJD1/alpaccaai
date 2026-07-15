"""Cross-host singleton lease client for local/cloud Alpecca runtimes.

The remote authority owns the monotonic fencing epoch. This module deliberately
contains no model or state-transfer logic; it only keeps one runtime entitled
to start conversational side effects at a time.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import socket
import threading
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request


MAX_RESPONSE_BYTES = 64 * 1024
MAX_LEASE_SECONDS = 35
DEFAULT_RENEW_SECONDS = 10.0
LEASE_TOKEN_CREDENTIAL_TARGET = "Alpecca/ContinuityLeaseToken"
_NODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")


class ContinuityLeaseError(RuntimeError):
    """The singleton authority could not produce a trustworthy result."""


@dataclass(frozen=True)
class LeaseGrant:
    lease_id: str
    fencing_epoch: int
    ttl_seconds: int
    holder: str
    role: str


def _base_url(value: str) -> str:
    url = (value or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and parsed.netloc:
        return url
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}:
        return url
    raise ContinuityLeaseError("continuity lease URL must use HTTPS")


def _identifier(value: str, field: str) -> str:
    normalized = (value or "").strip()
    if not _NODE_RE.fullmatch(normalized):
        raise ContinuityLeaseError(f"invalid {field}")
    return normalized


def _grant(body: Mapping[str, Any], *, node_id: str, role: str) -> LeaseGrant:
    payload = body.get("lease") if isinstance(body.get("lease"), Mapping) else body
    lease_id = _identifier(str(payload.get("leaseId") or ""), "lease ID")
    holder = _identifier(
        str(payload.get("holderNodeId") or payload.get("holder") or ""),
        "lease holder",
    )
    epoch = payload.get("fencingEpoch")
    ttl = payload.get("ttlRemainingSeconds", payload.get("ttlSeconds"))
    if holder != node_id:
        raise ContinuityLeaseError("lease authority returned a different holder")
    if type(epoch) is not int or epoch < 1:
        raise ContinuityLeaseError("lease authority returned an invalid fencing epoch")
    if type(ttl) is not int or not 1 <= ttl <= MAX_LEASE_SECONDS:
        raise ContinuityLeaseError("lease authority returned an invalid lifetime")
    return LeaseGrant(lease_id, epoch, ttl, holder, role)


class ContinuityLeaseClient:
    """Small authenticated JSON client for the lease Durable Object."""

    def __init__(
        self,
        base_url: str,
        token: str,
        node_id: str,
        role: str,
        *,
        timeout: float = 5.0,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = _base_url(base_url)
        self.token = (token or "").strip()
        if len(self.token) < 24:
            raise ContinuityLeaseError("continuity lease token is not configured")
        self.node_id = _identifier(node_id, "node ID")
        if role not in {"local-primary", "cloud-standby"}:
            raise ContinuityLeaseError("invalid continuity role")
        self.role = role
        self.timeout = max(1.0, min(15.0, float(timeout)))
        self._opener = opener or urllib.request.urlopen

    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "Alpecca-Continuity-Lease/1",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method,
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                status = int(getattr(response, "status", 200))
        except urllib.error.HTTPError as exc:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
            status = int(exc.code)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise ContinuityLeaseError(f"lease transport failed: {type(exc).__name__}") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ContinuityLeaseError("lease response exceeded the size limit")
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContinuityLeaseError("lease response was not valid JSON") from exc
        if not isinstance(body, dict):
            raise ContinuityLeaseError("lease response was not an object")
        body["httpStatus"] = status
        return body

    def heartbeat(self, endpoint: str = "") -> dict[str, Any]:
        return self._request("POST", "/v1/heartbeat/local", {
            "ownerNodeId": self.node_id,
            "ttlSeconds": MAX_LEASE_SECONDS,
        })

    def acquire(self, ttl_seconds: int = MAX_LEASE_SECONDS) -> LeaseGrant:
        ttl = max(1, min(MAX_LEASE_SECONDS, int(ttl_seconds)))
        body = self._request("POST", "/v1/lease/acquire", {
            "holderNodeId": self.node_id,
            "ttlSeconds": ttl,
        })
        if not bool(body.get("ok")):
            raise ContinuityLeaseError(str(body.get("error") or body.get("status") or "lease denied")[:160])
        return _grant(body, node_id=self.node_id, role=self.role)

    def renew(self, grant: LeaseGrant) -> LeaseGrant:
        body = self._request("POST", "/v1/lease/renew", {
            "holderNodeId": self.node_id,
            "leaseId": grant.lease_id,
            "fencingEpoch": grant.fencing_epoch,
            "ttlSeconds": min(MAX_LEASE_SECONDS, grant.ttl_seconds),
        })
        if not bool(body.get("ok")):
            raise ContinuityLeaseError(str(body.get("error") or body.get("status") or "renewal denied")[:160])
        renewed = _grant(body, node_id=self.node_id, role=self.role)
        if renewed.lease_id != grant.lease_id or renewed.fencing_epoch != grant.fencing_epoch:
            raise ContinuityLeaseError("renewal changed the active lease fence")
        return renewed

    def release(self, grant: LeaseGrant) -> dict[str, Any]:
        return self._request("POST", "/v1/lease/release", {
            "holderNodeId": self.node_id,
            "leaseId": grant.lease_id,
            "fencingEpoch": grant.fencing_epoch,
        })

    def publish_endpoint(self, grant: LeaseGrant, endpoint: str) -> dict[str, Any]:
        return self._request("PUT", "/v1/endpoint", {
            "holderNodeId": self.node_id,
            "leaseId": grant.lease_id,
            "fencingEpoch": grant.fencing_epoch,
            "endpoint": (endpoint or "").strip()[:512],
        })

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/v1/status")

    def publish_active_endpoint(self, endpoint: str) -> dict[str, Any]:
        """Publish against the exact lease currently held by this node.

        Relay discovery happens after the local runtime has acquired its lease,
        so that relay process does not inherit the in-memory ``LeaseGrant``.
        The authenticated authority status is the only acceptable source for
        reconstructing it: ``_grant`` verifies the holder, epoch, ID, and TTL
        before the exact-fence PUT is attempted.
        """
        body = self.status()
        if not bool(body.get("ok")):
            raise ContinuityLeaseError(
                str(body.get("error") or "continuity status unavailable")[:160]
            )
        active = body.get("activeLease")
        if not isinstance(active, Mapping):
            raise ContinuityLeaseError("no active continuity lease")
        grant = _grant(active, node_id=self.node_id, role=self.role)
        published = self.publish_endpoint(grant, endpoint)
        if not bool(published.get("ok")):
            raise ContinuityLeaseError(
                str(published.get("error") or "endpoint publication denied")[:160]
            )
        return published


def _windows_credential_token(
    target: str = LEASE_TOKEN_CREDENTIAL_TARGET,
) -> str:
    """Read the dedicated lease token without writing it to source or logs."""
    if os.name != "nt":
        return ""
    try:
        import win32cred

        credential = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
        blob = credential.get("CredentialBlob", b"")
        if isinstance(blob, memoryview):
            blob = blob.tobytes()
        if isinstance(blob, bytes):
            encoding = "utf-16-le" if b"\x00" in blob else "utf-8"
            return blob.decode(encoding).rstrip("\x00").strip()
        return str(blob or "").strip()
    except Exception:
        return ""


def _windows_user_environment(name: str) -> str:
    """Read a user-scoped environment value even in an older parent process.

    Windows Explorer, Codex, and long-running launchers do not automatically
    receive environment values written after they started. Reading the user
    registry fallback keeps the singleton authority active across those launch
    paths without placing its bearer token in the environment.
    """
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _kind = winreg.QueryValueEx(key, name)
        return str(value or "").strip()
    except Exception:
        return ""


class ContinuityLeaseGuard:
    """Acquire and renew one runtime lease, failing closed before expiry."""

    def __init__(
        self,
        client: ContinuityLeaseClient,
        *,
        renew_seconds: float = DEFAULT_RENEW_SECONDS,
        endpoint: str = "",
        on_loss: Callable[[str], None] | None = None,
    ) -> None:
        self.client = client
        self.renew_seconds = max(1.0, min(15.0, float(renew_seconds)))
        self.endpoint = (endpoint or "").strip()
        self.on_loss = on_loss
        self.grant: LeaseGrant | None = None
        self._deadline = 0.0
        self._safety_margin = 2.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def active(self) -> bool:
        return self.grant is not None and time.monotonic() < self._deadline and not self._stop.is_set()

    def start(self) -> LeaseGrant:
        if self.grant is not None:
            return self.grant
        if self.client.role == "local-primary":
            heartbeat = self.client.heartbeat(self.endpoint)
            if not bool(heartbeat.get("ok")):
                raise ContinuityLeaseError("local heartbeat was rejected")
        self.grant = self.client.acquire()
        self._deadline = time.monotonic() + self.grant.ttl_seconds
        self._safety_margin = min(2.0, max(0.1, self.grant.ttl_seconds * 0.2))
        if self.endpoint:
            published = self.client.publish_endpoint(self.grant, self.endpoint)
            if not bool(published.get("ok")):
                self.client.release(self.grant)
                self.grant = None
                raise ContinuityLeaseError("lease endpoint publication was rejected")
        self._thread = threading.Thread(
            target=self._renew_loop,
            name="AlpeccaContinuityLease",
            daemon=True,
        )
        self._thread.start()
        return self.grant

    def _renew_loop(self) -> None:
        while not self._stop.is_set():
            remaining_to_fence = (
                self._deadline - self._safety_margin - time.monotonic()
            )
            if remaining_to_fence <= 0:
                self._lose("lease renewal safety deadline elapsed")
                return
            if self._stop.wait(min(self.renew_seconds, remaining_to_fence)):
                return
            grant = self.grant
            if grant is None:
                return
            try:
                if self.client.role == "local-primary":
                    heartbeat = self.client.heartbeat(self.endpoint)
                    if not bool(heartbeat.get("ok")):
                        raise ContinuityLeaseError("local heartbeat was rejected")
                self.grant = self.client.renew(grant)
                self._deadline = time.monotonic() + self.grant.ttl_seconds
                self._safety_margin = min(
                    2.0, max(0.1, self.grant.ttl_seconds * 0.2)
                )
            except ContinuityLeaseError as exc:
                if time.monotonic() < self._deadline - self._safety_margin:
                    continue
                self._lose(str(exc))
                return

    def _lose(self, reason: str) -> None:
        self._stop.set()
        self.grant = None
        if self.on_loss:
            self.on_loss(reason)

    def stop(self) -> None:
        self._stop.set()
        grant, self.grant = self.grant, None
        if grant is not None:
            try:
                self.client.release(grant)
            except ContinuityLeaseError:
                pass
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)


def client_from_env(*, role: str | None = None) -> ContinuityLeaseClient | None:
    url = (
        os.environ.get("ALPECCA_CONTINUITY_LEASE_URL", "").strip()
        or _windows_user_environment("ALPECCA_CONTINUITY_LEASE_URL")
    )
    token = (
        os.environ.get("ALPECCA_CONTINUITY_LEASE_TOKEN", "").strip()
        or _windows_credential_token()
    )
    if not url and not token:
        return None
    selected_role = role or os.environ.get("ALPECCA_CONTINUITY_ROLE", "local-primary").strip()
    node_id = os.environ.get("ALPECCA_CONTINUITY_NODE_ID", "").strip()
    if not node_id:
        host = re.sub(r"[^A-Za-z0-9._:-]+", "-", socket.gethostname()).strip("-")
        node_id = f"{selected_role}:{host or 'unknown'}"[:96]
    return ContinuityLeaseClient(url, token, node_id, selected_role)


__all__ = [
    "ContinuityLeaseClient",
    "ContinuityLeaseError",
    "ContinuityLeaseGuard",
    "LEASE_TOKEN_CREDENTIAL_TARGET",
    "LeaseGrant",
    "client_from_env",
]
