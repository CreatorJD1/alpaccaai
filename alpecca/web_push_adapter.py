"""Bounded Web Push adapter behind the Phase 11 notification outbox.

This module owns no destination, credential, HTTP client, or persistence.  The
server injects a private runtime store and a transport.  Importing it therefore
cannot enroll a browser, open a database, or send a notification.

Provider acceptance and creator acknowledgement are intentionally separate:
``deliver_one`` records only the push service outcome, while ``acknowledge``
requires a one-use receipt created for the exact event and subscription.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable
from urllib.parse import urlsplit

from alpecca import notification_outbox as outbox_mod


ADAPTER_NAME = "app_push"
PAYLOAD_VERSION = 1
MAX_TITLE_CHARS = 80
MAX_BODY_CHARS = 320
MAX_ENDPOINT_CHARS = 2048
MAX_KEY_CHARS = 512
MAX_RECEIPT_CHARS = 512
MAX_EVENT_CHARS = 64

ACCEPTED = "accepted"
REJECTED = "rejected"
UNKNOWN = "unknown"
OUTCOMES = frozenset({ACCEPTED, REJECTED, UNKNOWN})

_EVENT_RE = re.compile(r"^out_[0-9a-f]{32}$")
_SUBSCRIPTION_ID_RE = re.compile(r"^wps_[0-9a-f]{32,64}$")
_RECEIPT_RE = re.compile(r"^wpa_[A-Za-z0-9_-]{43,480}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")
_ALLOWED_PUSH_HOSTS = (
    "fcm.googleapis.com",
    ".push.services.mozilla.com",
    ".notify.windows.com",
    ".push.apple.com",
)


class WebPushAdapterError(ValueError):
    """A Web Push contract value or transition is invalid."""


class WebPushUnavailable(WebPushAdapterError):
    """The private store or transport is not ready for delivery."""


def _bounded_text(value: object, *, name: str, limit: int) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise WebPushAdapterError(f"{name} is invalid")
    if len(value) > limit or any(ord(char) < 32 for char in value):
        raise WebPushAdapterError(f"{name} is invalid")
    return value


def _event_id(value: object) -> str:
    clean = _bounded_text(value, name="event_id", limit=MAX_EVENT_CHARS)
    if _EVENT_RE.fullmatch(clean) is None:
        raise WebPushAdapterError("event_id is invalid")
    return clean


def _subscription_id(value: object) -> str:
    clean = _bounded_text(value, name="subscription_id", limit=80)
    if _SUBSCRIPTION_ID_RE.fullmatch(clean) is None:
        raise WebPushAdapterError("subscription_id is invalid")
    return clean


def _receipt(value: object) -> str:
    clean = _bounded_text(value, name="receipt", limit=MAX_RECEIPT_CHARS)
    if _RECEIPT_RE.fullmatch(clean) is None:
        raise WebPushAdapterError("receipt is invalid")
    return clean


def _push_endpoint(value: object) -> str:
    clean = _bounded_text(value, name="endpoint", limit=MAX_ENDPOINT_CHARS)
    try:
        parsed = urlsplit(clean)
    except ValueError as exc:
        raise WebPushAdapterError("endpoint is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise WebPushAdapterError("endpoint must be an HTTPS push-service URL")
    host = parsed.hostname.lower().rstrip(".")
    if not host.isascii() or not any(
        host == suffix or (suffix.startswith(".") and host.endswith(suffix))
        for suffix in _ALLOWED_PUSH_HOSTS
    ):
        raise WebPushAdapterError("endpoint push service is not allowlisted")
    return clean


def _push_key(value: object, *, name: str) -> str:
    clean = _bounded_text(value, name=name, limit=MAX_KEY_CHARS)
    if _KEY_RE.fullmatch(clean) is None:
        raise WebPushAdapterError(f"{name} is invalid")
    return clean


@dataclass(frozen=True, slots=True)
class PushSubscription:
    """Private browser subscription resolved only after an outbox claim."""

    subscription_id: str
    endpoint: str = field(repr=False)
    p256dh: str = field(repr=False)
    auth: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "subscription_id", _subscription_id(self.subscription_id))
        object.__setattr__(self, "endpoint", _push_endpoint(self.endpoint))
        object.__setattr__(self, "p256dh", _push_key(self.p256dh, name="p256dh"))
        object.__setattr__(self, "auth", _push_key(self.auth, name="auth"))


@dataclass(frozen=True, slots=True)
class PushTemplate:
    """Bounded server-owned notification content stored outside the outbox."""

    title: str
    body: str
    url: str = "/house-hq"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "title",
            _bounded_text(self.title, name="title", limit=MAX_TITLE_CHARS),
        )
        object.__setattr__(
            self,
            "body",
            _bounded_text(self.body, name="body", limit=MAX_BODY_CHARS),
        )
        if self.url != "/house-hq":
            raise WebPushAdapterError("notification URL must be /house-hq")


@dataclass(frozen=True, slots=True)
class PushTransportResult:
    """Sanitized provider result; response bodies and destinations are excluded."""

    outcome: Literal["accepted", "rejected", "unknown"]
    stale_subscription: bool = False

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise WebPushAdapterError("transport outcome is invalid")
        if type(self.stale_subscription) is not bool:
            raise WebPushAdapterError("stale_subscription must be boolean")
        if self.stale_subscription and self.outcome != REJECTED:
            raise WebPushAdapterError("only a rejected subscription can be stale")


@runtime_checkable
class WebPushRuntimeStore(Protocol):
    """Secret-backed storage contract used only by the adapter and server."""

    def subscriptions(self) -> tuple[PushSubscription, ...]: ...

    def resolve_template(
        self, payload_ref: outbox_mod.OpaquePayloadRef
    ) -> PushTemplate | None: ...

    def issue_ack_receipt(
        self,
        *,
        event_id: str,
        subscription_id: str,
        transport_idempotency_key: str,
    ) -> str: ...

    def verify_ack_receipt(self, *, event_id: str, receipt: str) -> bool: ...

    def reserve_ack_receipt(self, *, event_id: str, receipt: str) -> bool: ...

    def consume_ack_receipt(self, *, event_id: str, receipt: str) -> bool: ...

    def remove_subscription(self, subscription_id: str) -> None: ...

    def discard_template(self, payload_ref: outbox_mod.OpaquePayloadRef) -> None: ...


@runtime_checkable
class WebPushTransport(Protocol):
    """One no-redirect HTTPS Web Push attempt."""

    def send(
        self,
        *,
        subscription: PushSubscription,
        payload: dict[str, object],
        transport_idempotency_key: str,
    ) -> PushTransportResult: ...


class WebPushAdapter:
    """Claim one app-push event and record exactly one provider outcome."""

    def __init__(
        self,
        outbox: outbox_mod.NotificationOutbox,
        store: WebPushRuntimeStore,
        transport: WebPushTransport,
    ) -> None:
        if not isinstance(outbox, outbox_mod.NotificationOutbox):
            raise TypeError("outbox must be NotificationOutbox")
        if not isinstance(store, WebPushRuntimeStore):
            raise TypeError("store must implement WebPushRuntimeStore")
        if not isinstance(transport, WebPushTransport):
            raise TypeError("transport must implement WebPushTransport")
        self._outbox = outbox
        self._store = store
        self._transport = transport

    def _record_outcome(
        self,
        claim: outbox_mod.DeliveryClaim,
        outcome: str,
    ) -> dict[str, object]:
        kwargs = {
            "claim_handle": claim.claim_handle,
            "transport_idempotency_key": claim.transport_idempotency_key,
        }
        if outcome == ACCEPTED:
            return self._outbox.mark_sent(claim.event_id, **kwargs)
        if outcome == REJECTED:
            return self._outbox.record_failure(claim.event_id, **kwargs)
        return self._outbox.mark_indeterminate(claim.event_id, **kwargs)

    def _abandon_claim(
        self, claim: outbox_mod.DeliveryClaim
    ) -> dict[str, object]:
        return self._outbox.abandon_claim(
            claim.event_id,
            claim_handle=claim.claim_handle,
            transport_idempotency_key=claim.transport_idempotency_key,
        )

    def deliver_one(self) -> dict[str, object]:
        """Deliver at most one due event without exposing claim or destination facts."""
        claim = self._outbox.claim_next(adapter_name=ADAPTER_NAME)
        if claim is None:
            return {"attempted": False, "state": "idle"}

        try:
            template = self._store.resolve_template(claim.payload_ref)
            subscriptions = self._store.subscriptions()
        except Exception:
            status = self._abandon_claim(claim)
            return {
                "attempted": False,
                "event_id": claim.event_id,
                "state": status["state"],
                "accepted": 0,
                "rejected": 0,
                "unknown": 0,
                "undispatched": 1,
            }
        if template is None or not subscriptions:
            status = self._abandon_claim(claim)
            return {
                "attempted": False,
                "event_id": claim.event_id,
                "state": status["state"],
                "accepted": 0,
                "rejected": 0,
                "unknown": 0,
                "undispatched": 1,
            }

        accepted = 0
        rejected = 0
        unknown = 0
        undispatched = 0
        for subscription in subscriptions:
            try:
                receipt = self._store.issue_ack_receipt(
                    event_id=claim.event_id,
                    subscription_id=subscription.subscription_id,
                    transport_idempotency_key=claim.transport_idempotency_key,
                )
                payload = {
                    "version": PAYLOAD_VERSION,
                    "title": template.title,
                    "body": template.body,
                    "url": template.url,
                    "event_id": claim.event_id,
                    "receipt": _receipt(receipt),
                    "tag": f"alpecca-{claim.event_id}",
                }
            except Exception:
                undispatched += 1
                continue
            try:
                result = self._transport.send(
                    subscription=subscription,
                    payload=payload,
                    transport_idempotency_key=claim.transport_idempotency_key,
                )
            except Exception:
                result = PushTransportResult(UNKNOWN)
            if result.outcome == ACCEPTED:
                accepted += 1
            elif result.outcome == REJECTED:
                rejected += 1
                if result.stale_subscription:
                    try:
                        self._store.remove_subscription(subscription.subscription_id)
                    except Exception:
                        pass
            else:
                unknown += 1

        dispatched = accepted + rejected + unknown
        if dispatched == 0:
            status = self._abandon_claim(claim)
            outcome = "undispatched"
        else:
            outcome = ACCEPTED if accepted else (UNKNOWN if unknown else REJECTED)
            status = self._record_outcome(claim, outcome)
        if outcome == ACCEPTED:
            self._store.discard_template(claim.payload_ref)
        return {
            "attempted": dispatched > 0,
            "event_id": claim.event_id,
            "state": status["state"],
            "accepted": accepted,
            "rejected": rejected,
            "unknown": unknown,
            "undispatched": undispatched,
        }

    def acknowledge(self, *, event_id: str, receipt: str) -> dict[str, object]:
        """Acknowledge a sent event after validating a one-use click receipt."""
        clean_event = _event_id(event_id)
        clean_receipt = _receipt(receipt)
        if not self._store.verify_ack_receipt(
            event_id=clean_event, receipt=clean_receipt
        ):
            raise WebPushAdapterError("acknowledgement receipt is invalid")
        if not self._store.reserve_ack_receipt(
            event_id=clean_event, receipt=clean_receipt
        ):
            raise WebPushAdapterError("acknowledgement receipt could not be reserved")
        status = self._outbox.acknowledge(clean_event)
        if not self._store.consume_ack_receipt(
            event_id=clean_event, receipt=clean_receipt
        ):
            raise WebPushAdapterError("acknowledgement receipt was already consumed")
        return status


__all__ = [
    "ACCEPTED",
    "ADAPTER_NAME",
    "PAYLOAD_VERSION",
    "PushSubscription",
    "PushTemplate",
    "PushTransportResult",
    "REJECTED",
    "UNKNOWN",
    "WebPushAdapter",
    "WebPushAdapterError",
    "WebPushRuntimeStore",
    "WebPushTransport",
    "WebPushUnavailable",
]
