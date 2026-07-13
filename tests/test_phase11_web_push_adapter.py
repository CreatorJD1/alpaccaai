from __future__ import annotations

import base64
import hashlib
import json
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from alpecca import notification_outbox as outbox_mod
from alpecca import web_push_adapter as push_mod


SEAL_KEY = b"phase11-web-push-adapter-test-seal-key"
PRIVATE_RESULT_FIELDS = {
    "auth",
    "claim_handle",
    "endpoint",
    "p256dh",
    "payload_ref",
    "receipt",
    "subscription_id",
    "transport_idempotency_key",
}


class MutableClock:
    def __init__(self, value: float = 100.0) -> None:
        self._value = value
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._value

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value


class FakeRuntimeStore:
    def __init__(
        self,
        subscriptions: tuple[push_mod.PushSubscription, ...] = (),
    ) -> None:
        self._subscriptions = subscriptions
        self._templates: dict[str, push_mod.PushTemplate] = {}
        self._receipts: dict[str, dict[str, object]] = {}
        self._receipt_ordinal = 0
        self._lock = threading.RLock()
        self.issued_receipts: list[str] = []
        self.removed_subscriptions: list[str] = []
        self.discarded_templates: list[str] = []

    def set_subscriptions(
        self, subscriptions: tuple[push_mod.PushSubscription, ...]
    ) -> None:
        with self._lock:
            self._subscriptions = subscriptions

    def put_template(
        self,
        payload_ref: outbox_mod.OpaquePayloadRef,
        template: push_mod.PushTemplate,
    ) -> None:
        with self._lock:
            self._templates[payload_ref.value] = template

    def has_template(self, payload_ref: outbox_mod.OpaquePayloadRef) -> bool:
        with self._lock:
            return payload_ref.value in self._templates

    def subscriptions(self) -> tuple[push_mod.PushSubscription, ...]:
        with self._lock:
            return self._subscriptions

    def resolve_template(
        self, payload_ref: outbox_mod.OpaquePayloadRef
    ) -> push_mod.PushTemplate | None:
        with self._lock:
            return self._templates.get(payload_ref.value)

    def issue_ack_receipt(
        self,
        *,
        event_id: str,
        subscription_id: str,
        transport_idempotency_key: str,
    ) -> str:
        with self._lock:
            self._receipt_ordinal += 1
            material = (
                f"{event_id}:{subscription_id}:{transport_idempotency_key}:"
                f"{self._receipt_ordinal}"
            ).encode("ascii")
            token = base64.urlsafe_b64encode(hashlib.sha256(material).digest())
            receipt = "wpa_" + token.decode("ascii").rstrip("=")
            self._receipts[receipt] = {
                "event_id": event_id,
                "subscription_id": subscription_id,
                "transport_idempotency_key": transport_idempotency_key,
                "reserved": False,
                "consumed": False,
            }
            self.issued_receipts.append(receipt)
            return receipt

    def verify_ack_receipt(self, *, event_id: str, receipt: str) -> bool:
        with self._lock:
            record = self._receipts.get(receipt)
            return (
                record is not None
                and record["event_id"] == event_id
                and record["consumed"] is False
            )

    def reserve_ack_receipt(self, *, event_id: str, receipt: str) -> bool:
        with self._lock:
            record = self._receipts.get(receipt)
            if (
                record is None
                or record["event_id"] != event_id
                or record["consumed"] is True
            ):
                return False
            record["reserved"] = True
            return True

    def consume_ack_receipt(self, *, event_id: str, receipt: str) -> bool:
        with self._lock:
            record = self._receipts.get(receipt)
            if (
                record is None
                or record["event_id"] != event_id
                or record["reserved"] is not True
                or record["consumed"] is True
            ):
                return False
            record["consumed"] = True
            return True

    def receipt_consumed(self, receipt: str) -> bool:
        with self._lock:
            return bool(self._receipts[receipt]["consumed"])

    def receipt_reserved(self, receipt: str) -> bool:
        with self._lock:
            return bool(self._receipts[receipt]["reserved"])

    def remove_subscription(self, subscription_id: str) -> None:
        with self._lock:
            self.removed_subscriptions.append(subscription_id)
            self._subscriptions = tuple(
                item
                for item in self._subscriptions
                if item.subscription_id != subscription_id
            )

    def discard_template(
        self, payload_ref: outbox_mod.OpaquePayloadRef
    ) -> None:
        with self._lock:
            self._templates.pop(payload_ref.value, None)
            self.discarded_templates.append(payload_ref.value)


class FakeTransport:
    def __init__(
        self,
        results: tuple[object, ...] = (),
        *,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self._results = deque(results)
        self._started = started
        self._release = release
        self._lock = threading.Lock()
        self.calls: list[dict[str, object]] = []

    def send(
        self,
        *,
        subscription: push_mod.PushSubscription,
        payload: dict[str, object],
        transport_idempotency_key: str,
    ) -> push_mod.PushTransportResult:
        with self._lock:
            self.calls.append(
                {
                    "subscription": subscription,
                    "payload": dict(payload),
                    "transport_idempotency_key": transport_idempotency_key,
                }
            )
            result = (
                self._results.popleft()
                if self._results
                else push_mod.PushTransportResult(push_mod.ACCEPTED)
            )
        if self._started is not None:
            self._started.set()
        if self._release is not None and not self._release.wait(timeout=5.0):
            raise RuntimeError("test transport was not released")
        if isinstance(result, BaseException):
            raise result
        assert isinstance(result, push_mod.PushTransportResult)
        return result


def _policy(**overrides: object) -> outbox_mod.OutboxPolicy:
    values: dict[str, object] = {
        "policy_id": "web_push_adapter_test",
        "policy_version": 1,
        "category_registry": frozenset({"reminder"}),
        "adapter_registry": frozenset({push_mod.ADAPTER_NAME}),
        "category_quotas": {"reminder": None},
        "channel_quotas": {push_mod.ADAPTER_NAME: None},
        "channel_costs": {push_mod.ADAPTER_NAME: 0},
        "adapter_transport_idempotency": {push_mod.ADAPTER_NAME: True},
        "max_attempts": 3,
        "lease_seconds": 10.0,
        "backoff_initial_seconds": 5.0,
        "backoff_multiplier": 2.0,
        "backoff_max_seconds": 60.0,
        "quota_window_seconds": 100.0,
        "accounting_timezone": "UTC",
    }
    values.update(overrides)
    return outbox_mod.OutboxPolicy(**values)


def _outbox(
    tmp_path: Path,
    *,
    clock: MutableClock | None = None,
    policy: outbox_mod.OutboxPolicy | None = None,
) -> outbox_mod.NotificationOutbox:
    return outbox_mod.NotificationOutbox(
        tmp_path / "web-push-outbox.db",
        seal_key=SEAL_KEY,
        policy=policy or _policy(),
        anchor=outbox_mod.InMemoryMonotonicAnchor(),
        clock=clock or MutableClock(),
    )


def _subscription(number: int = 1) -> push_mod.PushSubscription:
    return push_mod.PushSubscription(
        subscription_id=f"wps_{number:032x}",
        endpoint=f"https://fcm.googleapis.com/fcm/send/subscription-{number}",
        p256dh="B" * 87,
        auth="C" * 22,
    )


def _enqueue(
    outbox: outbox_mod.NotificationOutbox,
    store: FakeRuntimeStore,
    number: int = 1,
    *,
    template: push_mod.PushTemplate | None = None,
    store_template: bool = True,
) -> tuple[dict[str, object], outbox_mod.OpaquePayloadRef]:
    payload_ref = outbox.mint_payload_ref()
    if store_template:
        store.put_template(
            payload_ref,
            template or push_mod.PushTemplate(title="Alpecca", body="Open House HQ"),
        )
    event = outbox.enqueue(
        idempotency_key=f"idem_{number:032x}",
        category="reminder",
        adapter_name=push_mod.ADAPTER_NAME,
        payload_ref=payload_ref,
    )
    return event, payload_ref


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://fcm.googleapis.com/fcm/send/token",
        "https://updates.push.services.mozilla.com/wpush/v2/token",
        "https://wns2.notify.windows.com/w/?token=value",
        "https://web.push.apple.com/QH-token",
    ),
)
def test_subscription_accepts_only_allowlisted_push_service_families(endpoint: str):
    subscription = push_mod.PushSubscription(
        subscription_id="wps_" + "a" * 32,
        endpoint=endpoint,
        p256dh="A" * push_mod.MAX_KEY_CHARS,
        auth="base64url_auth==",
    )

    assert subscription.endpoint == endpoint
    assert len(subscription.p256dh) == push_mod.MAX_KEY_CHARS


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://fcm.googleapis.com/fcm/send/token",
        "https://example.com/push/token",
        "https://fcm.googleapis.com.evil.example/push/token",
        "https://user@fcm.googleapis.com/fcm/send/token",
        "https://password:secret@fcm.googleapis.com/fcm/send/token",
        "https://fcm.googleapis.com/fcm/send/token#fragment",
        "https://push.services.mozilla.com.evil.example/token",
        " https://fcm.googleapis.com/fcm/send/token",
    ),
)
def test_subscription_rejects_non_allowlisted_or_ambiguous_endpoints(endpoint: str):
    with pytest.raises(push_mod.WebPushAdapterError, match="endpoint|allowlisted"):
        push_mod.PushSubscription(
            subscription_id="wps_" + "a" * 32,
            endpoint=endpoint,
            p256dh="valid_key",
            auth="valid_auth",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("p256dh", ""),
        ("auth", "="),
        ("p256dh", "has+plus"),
        ("auth", "has/slash"),
        ("p256dh", "padding=inside=value"),
        ("auth", " leading"),
        ("p256dh", "trailing "),
        ("auth", "line\nbreak"),
        ("p256dh", "A" * (push_mod.MAX_KEY_CHARS + 1)),
    ),
)
def test_subscription_rejects_unbounded_or_non_base64url_keys(
    field: str, value: str
):
    values = {
        "subscription_id": "wps_" + "a" * 32,
        "endpoint": "https://fcm.googleapis.com/fcm/send/token",
        "p256dh": "valid_key",
        "auth": "valid_auth",
    }
    values[field] = value

    with pytest.raises(push_mod.WebPushAdapterError, match=field):
        push_mod.PushSubscription(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("title", ""),
        ("title", " title"),
        ("title", "title "),
        ("title", "A" * (push_mod.MAX_TITLE_CHARS + 1)),
        ("body", ""),
        ("body", "body\nwith control"),
        ("body", "B" * (push_mod.MAX_BODY_CHARS + 1)),
    ),
)
def test_template_rejects_empty_control_padded_or_oversized_text(
    field: str, value: str
):
    values = {"title": "Alpecca", "body": "Open House HQ"}
    values[field] = value

    with pytest.raises(push_mod.WebPushAdapterError, match=field):
        push_mod.PushTemplate(**values)


def test_template_and_transport_result_contracts_are_closed():
    template = push_mod.PushTemplate(
        title="T" * push_mod.MAX_TITLE_CHARS,
        body="B" * push_mod.MAX_BODY_CHARS,
    )

    assert template.url == "/house-hq"
    with pytest.raises(push_mod.WebPushAdapterError, match="URL"):
        push_mod.PushTemplate(title="Alpecca", body="Open", url="/other")
    with pytest.raises(push_mod.WebPushAdapterError, match="outcome"):
        push_mod.PushTransportResult("redirected")
    with pytest.raises(push_mod.WebPushAdapterError, match="rejected"):
        push_mod.PushTransportResult(push_mod.ACCEPTED, stale_subscription=True)
    with pytest.raises(push_mod.WebPushAdapterError, match="boolean"):
        push_mod.PushTransportResult(push_mod.REJECTED, stale_subscription=1)


def test_idle_delivery_does_not_touch_private_runtime_state(tmp_path: Path):
    outbox = _outbox(tmp_path)
    store = FakeRuntimeStore((_subscription(),))
    transport = FakeTransport()
    adapter = push_mod.WebPushAdapter(outbox, store, transport)

    assert adapter.deliver_one() == {"attempted": False, "state": "idle"}
    assert transport.calls == []
    assert store.issued_receipts == []


def test_accepted_delivery_marks_sent_builds_bounded_payload_and_acknowledges(
    tmp_path: Path,
):
    outbox = _outbox(tmp_path)
    subscription = _subscription()
    store = FakeRuntimeStore((subscription,))
    transport = FakeTransport(
        (push_mod.PushTransportResult(push_mod.ACCEPTED),)
    )
    adapter = push_mod.WebPushAdapter(outbox, store, transport)
    title = "T" * push_mod.MAX_TITLE_CHARS
    body = "B" * push_mod.MAX_BODY_CHARS
    event, payload_ref = _enqueue(
        outbox,
        store,
        template=push_mod.PushTemplate(title=title, body=body),
    )

    result = adapter.deliver_one()

    assert result == {
        "attempted": True,
        "event_id": event["event_id"],
        "state": outbox_mod.SENT,
        "accepted": 1,
        "rejected": 0,
        "unknown": 0,
        "undispatched": 0,
    }
    assert len(transport.calls) == 1
    call = transport.calls[0]
    receipt = store.issued_receipts[0]
    assert call["subscription"] == subscription
    assert call["payload"] == {
        "version": push_mod.PAYLOAD_VERSION,
        "title": title,
        "body": body,
        "url": "/house-hq",
        "event_id": event["event_id"],
        "receipt": receipt,
        "tag": f"alpecca-{event['event_id']}",
    }
    assert call["transport_idempotency_key"].startswith("txi_")
    assert outbox.get_event(event["event_id"])["state"] == outbox_mod.SENT
    assert not store.has_template(payload_ref)
    assert store.discarded_templates == [payload_ref.value]

    public_json = json.dumps((result, outbox.get_event(event["event_id"])))
    assert set(result).isdisjoint(PRIVATE_RESULT_FIELDS)
    assert subscription.endpoint not in public_json
    assert subscription.subscription_id not in public_json
    assert receipt not in public_json
    assert call["transport_idempotency_key"] not in public_json

    acknowledged = adapter.acknowledge(
        event_id=str(event["event_id"]), receipt=receipt
    )
    assert acknowledged["state"] == outbox_mod.ACKNOWLEDGED
    assert set(acknowledged).isdisjoint(PRIVATE_RESULT_FIELDS)
    assert store.receipt_consumed(receipt) is True


def test_rejected_delivery_uses_backoff_and_removes_only_stale_subscription(
    tmp_path: Path,
):
    clock = MutableClock(100.0)
    outbox = _outbox(tmp_path, clock=clock)
    stale = _subscription(1)
    current = _subscription(2)
    store = FakeRuntimeStore((stale, current))
    transport = FakeTransport(
        (
            push_mod.PushTransportResult(
                push_mod.REJECTED, stale_subscription=True
            ),
            push_mod.PushTransportResult(push_mod.REJECTED),
            push_mod.PushTransportResult(push_mod.ACCEPTED),
        )
    )
    adapter = push_mod.WebPushAdapter(outbox, store, transport)
    event, payload_ref = _enqueue(outbox, store)

    rejected = adapter.deliver_one()

    assert rejected == {
        "attempted": True,
        "event_id": event["event_id"],
        "state": outbox_mod.QUEUED,
        "accepted": 0,
        "rejected": 2,
        "unknown": 0,
        "undispatched": 0,
    }
    status = outbox.get_event(event["event_id"])
    assert status["attempt_count"] == 1
    assert status["next_attempt_at"] == 105.0
    assert store.removed_subscriptions == [stale.subscription_id]
    assert store.subscriptions() == (current,)
    assert store.has_template(payload_ref)
    assert adapter.deliver_one() == {"attempted": False, "state": "idle"}
    assert len(transport.calls) == 2

    clock.set(105.0)
    accepted = adapter.deliver_one()
    assert accepted["state"] == outbox_mod.SENT
    assert accepted["accepted"] == 1
    assert len(transport.calls) == 3
    assert transport.calls[-1]["subscription"] == current
    assert not store.has_template(payload_ref)


@pytest.mark.parametrize("missing", ("subscriptions", "template"))
def test_missing_subscriptions_or_template_abandons_before_dispatch(
    tmp_path: Path, missing: str
):
    clock = MutableClock(100.0)
    outbox = _outbox(tmp_path, clock=clock)
    subscriptions = () if missing == "subscriptions" else (_subscription(),)
    store = FakeRuntimeStore(subscriptions)
    transport = FakeTransport()
    adapter = push_mod.WebPushAdapter(outbox, store, transport)
    event, payload_ref = _enqueue(
        outbox, store, store_template=missing != "template"
    )

    result = adapter.deliver_one()

    assert result == {
        "attempted": False,
        "event_id": event["event_id"],
        "state": outbox_mod.QUEUED,
        "accepted": 0,
        "rejected": 0,
        "unknown": 0,
        "undispatched": 1,
    }
    status = outbox.get_event(event["event_id"])
    assert status["next_attempt_at"] == 105.0
    assert status["attempt_count"] == 1
    assert transport.calls == []
    assert store.issued_receipts == []
    assert store.discarded_templates == []
    assert store.has_template(payload_ref) is (missing == "subscriptions")
    assert [
        item["kind"]
        for item in outbox.transition_receipts(event["event_id"])["receipts"]
    ] == ["enqueued", "claimed", "claim_abandoned"]


def test_unknown_delivery_becomes_indeterminate_without_automatic_retry(
    tmp_path: Path,
):
    outbox = _outbox(tmp_path)
    store = FakeRuntimeStore((_subscription(),))
    transport = FakeTransport((push_mod.PushTransportResult(push_mod.UNKNOWN),))
    adapter = push_mod.WebPushAdapter(outbox, store, transport)
    event, payload_ref = _enqueue(outbox, store)

    result = adapter.deliver_one()

    assert result == {
        "attempted": True,
        "event_id": event["event_id"],
        "state": outbox_mod.INDETERMINATE,
        "accepted": 0,
        "rejected": 0,
        "unknown": 1,
        "undispatched": 0,
    }
    assert outbox.get_event(event["event_id"])["state"] == outbox_mod.INDETERMINATE
    assert adapter.deliver_one() == {"attempted": False, "state": "idle"}
    assert len(transport.calls) == 1
    assert store.has_template(payload_ref)


def test_mixed_accepted_and_unknown_results_resolve_to_sent(tmp_path: Path):
    outbox = _outbox(tmp_path)
    subscriptions = (_subscription(1), _subscription(2))
    store = FakeRuntimeStore(subscriptions)
    transport = FakeTransport(
        (
            push_mod.PushTransportResult(push_mod.ACCEPTED),
            push_mod.PushTransportResult(push_mod.UNKNOWN),
        )
    )
    adapter = push_mod.WebPushAdapter(outbox, store, transport)
    event, payload_ref = _enqueue(outbox, store)

    result = adapter.deliver_one()

    assert result == {
        "attempted": True,
        "event_id": event["event_id"],
        "state": outbox_mod.SENT,
        "accepted": 1,
        "rejected": 0,
        "unknown": 1,
        "undispatched": 0,
    }
    assert len(transport.calls) == 2
    assert {
        call["transport_idempotency_key"] for call in transport.calls
    } == {transport.calls[0]["transport_idempotency_key"]}
    assert len({call["payload"]["receipt"] for call in transport.calls}) == 2
    assert store.discarded_templates == [payload_ref.value]
    assert outbox.get_event(event["event_id"])["state"] == outbox_mod.SENT


def test_transport_exception_is_sanitized_to_unknown_and_not_retried(
    tmp_path: Path,
):
    outbox = _outbox(tmp_path)
    store = FakeRuntimeStore((_subscription(),))
    transport = FakeTransport(
        (RuntimeError("private provider response and destination"),)
    )
    adapter = push_mod.WebPushAdapter(outbox, store, transport)
    event, payload_ref = _enqueue(outbox, store)

    result = adapter.deliver_one()

    assert result == {
        "attempted": True,
        "event_id": event["event_id"],
        "state": outbox_mod.INDETERMINATE,
        "accepted": 0,
        "rejected": 0,
        "unknown": 1,
        "undispatched": 0,
    }
    assert "private provider" not in json.dumps(result)
    assert adapter.deliver_one() == {"attempted": False, "state": "idle"}
    assert store.has_template(payload_ref)


def test_acknowledgement_rejects_wrong_replayed_and_wrong_event_receipts(
    tmp_path: Path,
):
    outbox = _outbox(tmp_path)
    store = FakeRuntimeStore((_subscription(),))
    transport = FakeTransport()
    adapter = push_mod.WebPushAdapter(outbox, store, transport)
    first, _first_ref = _enqueue(outbox, store, 1)
    second, _second_ref = _enqueue(outbox, store, 2)
    assert adapter.deliver_one()["event_id"] == first["event_id"]
    assert adapter.deliver_one()["event_id"] == second["event_id"]
    first_receipt = str(transport.calls[0]["payload"]["receipt"])
    second_receipt = str(transport.calls[1]["payload"]["receipt"])
    unknown_but_well_formed = "wpa_" + "A" * 43

    with pytest.raises(push_mod.WebPushAdapterError, match="receipt is invalid"):
        adapter.acknowledge(
            event_id=str(first["event_id"]), receipt=unknown_but_well_formed
        )
    with pytest.raises(push_mod.WebPushAdapterError, match="receipt is invalid"):
        adapter.acknowledge(
            event_id=str(second["event_id"]), receipt=first_receipt
        )
    assert outbox.get_event(first["event_id"])["state"] == outbox_mod.SENT
    assert outbox.get_event(second["event_id"])["state"] == outbox_mod.SENT

    assert adapter.acknowledge(
        event_id=str(first["event_id"]), receipt=first_receipt
    )["state"] == outbox_mod.ACKNOWLEDGED
    with pytest.raises(push_mod.WebPushAdapterError, match="receipt is invalid"):
        adapter.acknowledge(
            event_id=str(first["event_id"]), receipt=first_receipt
        )
    assert adapter.acknowledge(
        event_id=str(second["event_id"]), receipt=second_receipt
    )["state"] == outbox_mod.ACKNOWLEDGED


def test_acknowledgement_retry_after_reservation_succeeds_once_sent(tmp_path: Path):
    outbox = _outbox(tmp_path)
    subscription = _subscription()
    store = FakeRuntimeStore((subscription,))
    adapter = push_mod.WebPushAdapter(outbox, store, FakeTransport())
    event, _payload_ref = _enqueue(outbox, store)
    claim = outbox.claim_next(adapter_name=push_mod.ADAPTER_NAME)
    assert claim is not None
    receipt = store.issue_ack_receipt(
        event_id=claim.event_id,
        subscription_id=subscription.subscription_id,
        transport_idempotency_key=claim.transport_idempotency_key,
    )

    with pytest.raises(outbox_mod.OutboxStateError, match="sent evidence"):
        adapter.acknowledge(event_id=claim.event_id, receipt=receipt)
    assert store.receipt_reserved(receipt) is True
    assert store.receipt_consumed(receipt) is False
    assert outbox.get_event(event["event_id"])["state"] == outbox_mod.LEASED

    outbox.mark_sent(
        claim.event_id,
        claim_handle=claim.claim_handle,
        transport_idempotency_key=claim.transport_idempotency_key,
    )
    assert adapter.acknowledge(
        event_id=claim.event_id, receipt=receipt
    )["state"] == outbox_mod.ACKNOWLEDGED
    assert store.receipt_consumed(receipt) is True


def test_predispatch_receipt_failure_abandons_but_transport_exception_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clock = MutableClock(100.0)
    outbox = _outbox(tmp_path, clock=clock)
    store = FakeRuntimeStore((_subscription(),))
    transport = FakeTransport((RuntimeError("provider acceptance is unknown"),))
    adapter = push_mod.WebPushAdapter(outbox, store, transport)
    first, first_ref = _enqueue(outbox, store, 1)

    issue_receipt = store.issue_ack_receipt

    def fail_before_dispatch(**_kwargs: object) -> str:
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(store, "issue_ack_receipt", fail_before_dispatch)
    abandoned = adapter.deliver_one()

    assert abandoned == {
        "attempted": False,
        "event_id": first["event_id"],
        "state": outbox_mod.QUEUED,
        "accepted": 0,
        "rejected": 0,
        "unknown": 0,
        "undispatched": 1,
    }
    assert transport.calls == []
    assert store.has_template(first_ref)

    monkeypatch.setattr(store, "issue_ack_receipt", issue_receipt)
    clock.set(105.0)
    unknown = adapter.deliver_one()

    assert unknown == {
        "attempted": True,
        "event_id": first["event_id"],
        "state": outbox_mod.INDETERMINATE,
        "accepted": 0,
        "rejected": 0,
        "unknown": 1,
        "undispatched": 0,
    }
    assert len(transport.calls) == 1
    assert store.has_template(first_ref)


def test_concurrent_delivery_workers_produce_one_claim_and_one_send(tmp_path: Path):
    outbox = _outbox(tmp_path)
    store = FakeRuntimeStore((_subscription(),))
    started = threading.Event()
    release = threading.Event()
    transport = FakeTransport(started=started, release=release)
    first_adapter = push_mod.WebPushAdapter(outbox, store, transport)
    second_adapter = push_mod.WebPushAdapter(outbox, store, transport)
    event, _payload_ref = _enqueue(outbox, store)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(first_adapter.deliver_one)
        assert started.wait(timeout=5.0)
        second_future = pool.submit(second_adapter.deliver_one)
        try:
            second_result = second_future.result(timeout=5.0)
        finally:
            release.set()
        first_result = first_future.result(timeout=5.0)

    assert first_result["event_id"] == event["event_id"]
    assert first_result["state"] == outbox_mod.SENT
    assert second_result == {"attempted": False, "state": "idle"}
    assert len(transport.calls) == 1
    assert len(store.issued_receipts) == 1
    receipts = outbox.transition_receipts(event["event_id"])["receipts"]
    assert [item["kind"] for item in receipts].count("claimed") == 1
    assert [item["kind"] for item in receipts] == ["enqueued", "claimed", "sent"]
