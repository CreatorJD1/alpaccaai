"""HTTP boundary coverage for the Phase 11 creator Web Push routes."""
from __future__ import annotations

import json
import threading
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import PUBLIC_IDENTITY
import server
from alpecca import notification_outbox as outbox_mod
from alpecca import web_push_adapter as push_mod
from alpecca import web_push_runtime as runtime_mod


OUTBOX_SEAL = b"phase11-server-outbox-seal-key-with-test-entropy"
STORE_SEAL = b"phase11-server-private-store-seal-key-with-test-entropy"
PUBLIC_VAPID_KEY = "PUBLIC-APPLICATION-SERVER-KEY"
PRIVATE_VAPID_KEY = "PRIVATE-VAPID-MATERIAL-MUST-NOT-LEAK"
ENDPOINT = "https://fcm.googleapis.com/fcm/send/private-endpoint-token"
P256DH = "B" * 87
AUTH = "C" * 22

CREATOR_HEADERS = {server.auth_mod.AUTHORIZATION_HEADER: server._AUTH_SECRET}
SUBSCRIPTION = {
    "endpoint": ENDPOINT,
    "keys": {"p256dh": P256DH, "auth": AUTH},
}


class _InjectedProcessMutex:
    """Explicit process-local stand-in for the Windows kernel mutex."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @contextmanager
    def locked(self, *, timeout_ms: int | None = None):
        if timeout_ms is None:
            acquired = self._lock.acquire()
        elif timeout_ms == 0:
            acquired = self._lock.acquire(blocking=False)
        else:
            acquired = self._lock.acquire(timeout=timeout_ms / 1000)
        if not acquired:
            raise server.notification_anchor_mod.CrossProcessMutexTimeout
        try:
            yield
        finally:
            self._lock.release()


class MemoryCredentialRecord:
    """Atomic in-memory replacement for the Windows protected record."""

    def __init__(self) -> None:
        self.value: str | None = None
        self.writes: list[str] = []

    def read(self) -> str | None:
        return self.value

    def write(self, value: str) -> None:
        self.value = value
        self.writes.append(value)


class FakeTransport:
    """Deterministic transport that never opens a socket."""

    def __init__(self, outcomes: tuple[object, ...] = ()) -> None:
        self.outcomes = deque(outcomes)
        self.calls: list[dict[str, object]] = []

    def send(
        self,
        *,
        subscription: push_mod.PushSubscription,
        payload: dict[str, object],
        transport_idempotency_key: str,
    ) -> push_mod.PushTransportResult:
        self.calls.append(
            {
                "subscription": subscription,
                "payload": dict(payload),
                "transport_idempotency_key": transport_idempotency_key,
            }
        )
        result = (
            self.outcomes.popleft()
            if self.outcomes
            else push_mod.PushTransportResult(push_mod.ACCEPTED)
        )
        if isinstance(result, BaseException):
            raise result
        assert isinstance(result, push_mod.PushTransportResult)
        return result


@dataclass
class PushServerHarness:
    client: TestClient
    outbox: outbox_mod.NotificationOutbox
    store: runtime_mod.WebPushPrivateStore
    credential: MemoryCredentialRecord
    transport: FakeTransport
    runtime: dict[str, object]


def _policy() -> outbox_mod.OutboxPolicy:
    return outbox_mod.OutboxPolicy(
        policy_id="creator_app_push_test",
        policy_version=1,
        category_registry=frozenset({"connection_test"}),
        adapter_registry=frozenset({push_mod.ADAPTER_NAME}),
        category_quotas={"connection_test": 20},
        channel_quotas={push_mod.ADAPTER_NAME: 20},
        channel_costs={push_mod.ADAPTER_NAME: 0},
        adapter_transport_idempotency={push_mod.ADAPTER_NAME: False},
        max_attempts=2,
        lease_seconds=30.0,
        backoff_initial_seconds=1.0,
        backoff_multiplier=2.0,
        backoff_max_seconds=10.0,
        quota_window_seconds=3600.0,
        global_quota=20,
        daily_cost_cap=0,
        accounting_timezone="UTC",
    )


@pytest.fixture(autouse=True)
def block_real_credentials_and_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Phase 11 server tests reached a real credential or network path")

    monkeypatch.setattr(runtime_mod.WindowsCredentialRecord, "read", forbidden)
    monkeypatch.setattr(runtime_mod.WindowsCredentialRecord, "write", forbidden)
    monkeypatch.setattr(runtime_mod.PyWebPushTransport, "send", forbidden)
    monkeypatch.setattr(
        server, "_NOTIFICATION_RUNTIME_MUTEX", _InjectedProcessMutex()
    )
    monkeypatch.setattr(
        server, "_NOTIFICATION_TEST_OPERATION_MUTEX", _InjectedProcessMutex()
    )


@pytest.fixture
def push_server(tmp_path: Path, monkeypatch) -> PushServerHarness:
    credential = MemoryCredentialRecord()
    outbox = outbox_mod.NotificationOutbox(
        tmp_path / "notification-outbox.sqlite3",
        seal_key=OUTBOX_SEAL,
        policy=_policy(),
        anchor=outbox_mod.InMemoryMonotonicAnchor(),
    )
    store = runtime_mod.WebPushPrivateStore(
        tmp_path / "notification-web-push.sqlite3",
        subscription_record=credential,
        seal_key=STORE_SEAL,
    )
    transport = FakeTransport()
    runtime: dict[str, object] = {
        "outbox": outbox,
        "store": store,
        "vapid": runtime_mod.VapidMaterial(
            private_key=PRIVATE_VAPID_KEY,
            public_key=PUBLIC_VAPID_KEY,
        ),
        "adapter": push_mod.WebPushAdapter(outbox, store, transport),
    }
    monkeypatch.setattr(server, "_NOTIFICATION_RUNTIME", runtime)
    client = TestClient(server.app, base_url="http://testserver")
    harness = PushServerHarness(
        client=client,
        outbox=outbox,
        store=store,
        credential=credential,
        transport=transport,
        runtime=runtime,
    )
    try:
        yield harness
    finally:
        client.close()


def _subscribe(
    harness: PushServerHarness,
    *,
    endpoint: str = ENDPOINT,
) -> dict[str, object]:
    response = harness.client.post(
        "/notifications/push/subscription",
        headers=CREATOR_HEADERS,
        json={
            "subscription": {
                "endpoint": endpoint,
                "keys": {"p256dh": P256DH, "auth": AUTH},
            }
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def _send_test(harness: PushServerHarness):
    response = harness.client.post(
        "/notifications/push/test",
        headers=CREATOR_HEADERS,
        json={},
    )
    assert response.status_code == 200, response.text
    assert harness.transport.calls
    return response, harness.transport.calls[-1]["payload"]


REQUEST_CASES = (
    ("GET", "/notifications/push/status", None),
    (
        "POST",
        "/notifications/push/subscription",
        {"subscription": SUBSCRIPTION},
    ),
    ("DELETE", "/notifications/push/subscription", {"endpoint": ENDPOINT}),
    ("POST", "/notifications/push/test", {}),
    (
        "POST",
        "/notifications/push/ack",
        {"event_id": "out_" + "0" * 32, "receipt": "wpa_" + "A" * 43},
    ),
)


@pytest.mark.parametrize(
    ("identity", "expected_status"),
    (("anonymous", 401), ("public", 401), ("guest", 403)),
)
def test_non_creator_identities_are_denied_before_body_or_runtime(
    monkeypatch,
    identity: str,
    expected_status: int,
):
    body_reads: list[str] = []
    runtime_calls: list[str] = []

    async def unexpected_body_read(*_args, **_kwargs):
        body_reads.append("read")
        raise AssertionError("non-creator denial must precede body ingress")

    def unexpected_runtime():
        runtime_calls.append("runtime")
        raise AssertionError("non-creator denial must precede runtime access")

    monkeypatch.setattr(server, "_read_bounded_json_object", unexpected_body_read)
    monkeypatch.setattr(server, "_notification_runtime", unexpected_runtime)
    if identity == "guest":
        monkeypatch.setattr(
            server._AUTHORITY,
            "authorize_request",
            lambda **_kwargs: server.auth_mod.AuthDecision(
                True,
                "test_guest",
                "accepted",
                principal="guest",
            ),
        )
    headers = (
        {"X-Alpecca-Identity": PUBLIC_IDENTITY}
        if identity == "public"
        else {}
    )

    client = TestClient(server.app, base_url="http://testserver")
    try:
        for method, path, body in REQUEST_CASES:
            kwargs = {"headers": headers}
            if body is not None:
                kwargs["json"] = body
            response = client.request(method, path, **kwargs)
            assert response.status_code == expected_status, (path, response.text)
            assert response.headers["cache-control"] == "no-store"
    finally:
        client.close()

    assert body_reads == []
    assert runtime_calls == []


def test_session_cookie_mutations_require_same_origin_before_body_or_runtime(
    monkeypatch,
):
    runtime_calls: list[str] = []

    def unavailable_runtime():
        runtime_calls.append("runtime")
        raise RuntimeError("injected unavailable runtime")

    monkeypatch.setattr(server, "_notification_runtime", unavailable_runtime)
    session = server._AUTHORITY.issue_session_cookie(secure=False)
    client = TestClient(server.app, base_url="http://testserver")
    client.cookies.set(session.name, session.value)
    mutations = REQUEST_CASES[1:]
    try:
        for method, path, body in mutations:
            without_origin = client.request(method, path, json=body)
            assert without_origin.status_code == 403
            assert without_origin.json() == {
                "detail": "same-origin request required"
            }

            cross_origin = client.request(
                method,
                path,
                headers={"Origin": "https://attacker.invalid"},
                json=body,
            )
            assert cross_origin.status_code == 403
            assert cross_origin.json() == {
                "detail": "same-origin request required"
            }

            same_origin = client.request(
                method,
                path,
                headers={"Origin": "http://testserver"},
                json=body,
            )
            assert same_origin.status_code == 503, (path, same_origin.text)
            assert same_origin.headers["cache-control"] == "no-store"
    finally:
        client.close()

    assert runtime_calls == ["runtime"] * len(mutations)


def test_bearer_mutation_does_not_require_cookie_csrf_origin(monkeypatch):
    calls: list[str] = []

    def unavailable_runtime():
        calls.append("runtime")
        raise RuntimeError("injected unavailable runtime")

    monkeypatch.setattr(server, "_notification_runtime", unavailable_runtime)
    client = TestClient(server.app, base_url="http://testserver")
    try:
        response = client.post(
            "/notifications/push/subscription",
            headers=CREATOR_HEADERS,
            json={"subscription": SUBSCRIPTION},
        )
    finally:
        client.close()

    assert response.status_code == 503
    assert calls == ["runtime"]


def test_status_is_no_store_bounded_and_secret_free(push_server: PushServerHarness):
    _subscribe(push_server)

    response = push_server.client.get(
        "/notifications/push/status",
        headers=CREATOR_HEADERS,
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {
        "available",
        "configured",
        "ready",
        "application_server_key",
        "subscription_count",
        "subscription_cap",
        "template_scope",
        "outbox",
        "acknowledgement",
        "autonomous_triggers",
    }
    assert body == {
        "available": True,
        "configured": True,
        "ready": True,
        "application_server_key": PUBLIC_VAPID_KEY,
        "subscription_count": 1,
        "subscription_cap": runtime_mod.MAX_SUBSCRIPTIONS,
        "template_scope": runtime_mod.TEST_TEMPLATE,
        "outbox": body["outbox"],
        "acknowledgement": "explicit_notification_click",
        "autonomous_triggers": False,
    }
    assert set(body["outbox"]) == {
        "contract_version",
        "policy_id",
        "policy_version",
        "anchored_sequence",
        "total",
        "states",
        "transition_receipts",
        "quarantined",
    }
    serialized = json.dumps(body, sort_keys=True)
    for private_value in (
        ENDPOINT,
        P256DH,
        AUTH,
        PRIVATE_VAPID_KEY,
        OUTBOX_SEAL.decode("ascii"),
        STORE_SEAL.decode("ascii"),
        server._AUTH_SECRET,
    ):
        assert private_value not in serialized


def test_status_reports_unavailable_without_constructing_runtime(
    push_server: PushServerHarness,
    monkeypatch,
):
    monkeypatch.setattr(server, "_NOTIFICATION_RUNTIME", {"invalid": object()})

    response = push_server.client.get(
        "/notifications/push/status",
        headers=CREATOR_HEADERS,
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "available": False,
        "configured": False,
        "reason": "notification runtime unavailable",
    }


@pytest.mark.parametrize(
    ("include_expiration", "expiration"),
    ((False, None), (True, None), (True, 1), (True, 1234.5)),
)
def test_subscribe_accepts_only_the_exact_bounded_browser_shape(
    push_server: PushServerHarness,
    include_expiration: bool,
    expiration: object,
):
    supplied = dict(SUBSCRIPTION)
    supplied["keys"] = dict(SUBSCRIPTION["keys"])
    if include_expiration:
        supplied["expirationTime"] = expiration

    response = push_server.client.post(
        "/notifications/push/subscription",
        headers=CREATOR_HEADERS,
        json={"subscription": supplied},
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"subscribed": True}
    subscriptions = push_server.store.subscriptions()
    assert len(subscriptions) == 1
    assert subscriptions[0].endpoint == ENDPOINT
    assert push_server.credential.value is not None
    assert "expirationTime" not in push_server.credential.value


@pytest.mark.parametrize(
    "body",
    (
        {},
        {"subscription": []},
        {"subscription": SUBSCRIPTION, "extra": True},
        {"subscription": {"endpoint": ENDPOINT}},
        {"subscription": {**SUBSCRIPTION, "extra": True}},
        {
            "subscription": {
                "endpoint": ENDPOINT,
                "keys": {"p256dh": P256DH, "auth": AUTH, "extra": "value"},
            }
        },
        {"subscription": {**SUBSCRIPTION, "expirationTime": False}},
        {"subscription": {**SUBSCRIPTION, "expirationTime": 0}},
        {"subscription": {**SUBSCRIPTION, "expirationTime": -1}},
        {"subscription": {**SUBSCRIPTION, "expirationTime": "never"}},
    ),
)
def test_subscribe_rejects_wrong_shapes_and_expirations(
    push_server: PushServerHarness,
    body: dict[str, object],
):
    response = push_server.client.post(
        "/notifications/push/subscription",
        headers=CREATOR_HEADERS,
        json=body,
    )

    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert push_server.store.subscriptions() == ()


def test_subscribe_rejects_nonfinite_and_oversized_json_before_runtime(
    monkeypatch,
):
    runtime_calls: list[str] = []

    def unexpected_runtime():
        runtime_calls.append("runtime")
        raise AssertionError("invalid bounded input reached the runtime")

    monkeypatch.setattr(server, "_notification_runtime", unexpected_runtime)
    client = TestClient(server.app, base_url="http://testserver")
    try:
        nonfinite = client.post(
            "/notifications/push/subscription",
            headers={**CREATOR_HEADERS, "Content-Type": "application/json"},
            content=(
                '{"subscription":{"endpoint":"%s","keys":{"p256dh":"%s",'
                '"auth":"%s"},"expirationTime":NaN}}'
                % (ENDPOINT, P256DH, AUTH)
            ),
        )
        oversized = client.post(
            "/notifications/push/subscription",
            headers=CREATOR_HEADERS,
            json={"subscription": SUBSCRIPTION, "padding": "x" * 5000},
        )
    finally:
        client.close()

    assert nonfinite.status_code == 400
    assert oversized.status_code == 413
    assert nonfinite.headers["cache-control"] == "no-store"
    assert oversized.headers["cache-control"] == "no-store"
    assert runtime_calls == []


def test_delete_revokes_only_the_exact_endpoint(push_server: PushServerHarness):
    _subscribe(push_server)

    wrong_shape = push_server.client.request(
        "DELETE",
        "/notifications/push/subscription",
        headers=CREATOR_HEADERS,
        json={"endpoint": ENDPOINT, "all": True},
    )
    removed = push_server.client.request(
        "DELETE",
        "/notifications/push/subscription",
        headers=CREATOR_HEADERS,
        json={"endpoint": ENDPOINT},
    )
    repeated = push_server.client.request(
        "DELETE",
        "/notifications/push/subscription",
        headers=CREATOR_HEADERS,
        json={"endpoint": ENDPOINT},
    )

    assert wrong_shape.status_code == 400
    assert removed.status_code == 200
    assert removed.json() == {"subscribed": False, "removed": True}
    assert repeated.status_code == 200
    assert repeated.json() == {"subscribed": False, "removed": False}
    assert push_server.store.subscriptions() == ()


def test_revoke_blocks_a_later_connection_test_send(
    push_server: PushServerHarness,
):
    _subscribe(push_server)

    # The connection test reaches the enrolled device exactly once.
    _send_test(push_server)
    assert len(push_server.transport.calls) == 1

    removed = push_server.client.request(
        "DELETE",
        "/notifications/push/subscription",
        headers=CREATOR_HEADERS,
        json={"endpoint": ENDPOINT},
    )
    assert removed.status_code == 200
    assert removed.json() == {"subscribed": False, "removed": True}
    assert push_server.store.subscriptions() == ()

    # After revocation a later connection test cannot dispatch to any device
    # and does not add a transport send.
    blocked = push_server.client.post(
        "/notifications/push/test",
        headers=CREATOR_HEADERS,
        json={},
    )
    assert blocked.status_code == 409
    assert blocked.json() == {
        "queued": False,
        "reason": "no creator browser subscription",
    }
    assert len(push_server.transport.calls) == 1


def test_connection_test_requires_empty_object_and_a_subscription(
    push_server: PushServerHarness,
):
    empty_bytes = push_server.client.post(
        "/notifications/push/test",
        headers=CREATOR_HEADERS,
        content=b"",
    )
    options = push_server.client.post(
        "/notifications/push/test",
        headers=CREATOR_HEADERS,
        json={"title": "caller-controlled"},
    )
    no_subscription = push_server.client.post(
        "/notifications/push/test",
        headers=CREATOR_HEADERS,
        json={},
    )

    assert empty_bytes.status_code == 400
    assert options.status_code == 400
    assert no_subscription.status_code == 409
    assert no_subscription.json() == {
        "queued": False,
        "reason": "no creator browser subscription",
    }
    assert push_server.transport.calls == []


def test_connection_test_maps_an_accepted_transport_result(
    push_server: PushServerHarness,
):
    _subscribe(push_server)

    response, payload = _send_test(push_server)

    body = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert set(body) == {"queued", "event_id", "delivery"}
    assert body["queued"] is True
    assert body["event_id"].startswith("out_")
    assert body["delivery"] == {
        "attempted": True,
        "event_id": body["event_id"],
        "state": outbox_mod.SENT,
        "accepted": 1,
        "rejected": 0,
        "unknown": 0,
        "undispatched": 0,
    }
    assert payload == {
        "version": push_mod.PAYLOAD_VERSION,
        "title": runtime_mod.TEST_TITLE,
        "body": runtime_mod.TEST_BODY,
        "url": "/house-hq",
        "event_id": body["event_id"],
        "receipt": payload["receipt"],
        "tag": f"alpecca-{body['event_id']}",
    }
    assert str(payload["receipt"]).startswith("wpa_")
    assert ENDPOINT not in json.dumps(body, sort_keys=True)


def test_connection_test_timeout_keeps_exclusive_send_until_worker_exits(
    push_server: PushServerHarness,
    monkeypatch,
):
    _subscribe(push_server)
    delivery_started = threading.Event()
    release_delivery = threading.Event()
    worker_threads: list[threading.Thread] = []
    bounded_calls = 0
    original_deliver_one = push_server.runtime["adapter"].deliver_one

    def slow_deliver_one():
        delivery_started.set()
        assert release_delivery.wait(timeout=5.0)
        return original_deliver_one()

    async def simulated_timeout(_label, fn, *_args, **_kwargs):
        nonlocal bounded_calls
        bounded_calls += 1
        if bounded_calls == 1:
            worker = threading.Thread(target=fn, daemon=True)
            worker_threads.append(worker)
            worker.start()
            assert delivery_started.wait(timeout=2.0)
            return None
        return fn()

    monkeypatch.setattr(push_server.runtime["adapter"], "deliver_one", slow_deliver_one)
    monkeypatch.setattr(server, "_bounded_thread", simulated_timeout)

    first = push_server.client.post(
        "/notifications/push/test", headers=CREATOR_HEADERS, json={}
    )
    second = push_server.client.post(
        "/notifications/push/test", headers=CREATOR_HEADERS, json={}
    )

    assert first.status_code == 202
    assert first.json() == {"queued": False, "in_progress": True}
    assert second.status_code == 409
    assert second.json() == {"queued": False, "in_progress": True}

    release_delivery.set()
    for worker in worker_threads:
        worker.join(timeout=5.0)
        assert not worker.is_alive()
    assert len(push_server.transport.calls) == 1


def test_notification_routes_do_not_reach_model_cognition_or_mindscape(
    push_server: PushServerHarness,
    monkeypatch,
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("notification route reached model, cognition, or Mindscape")

    monkeypatch.setattr(server, "_observe", forbidden)
    monkeypatch.setattr(server.mind, "chat", forbidden)
    monkeypatch.setattr(server.mind, "perceive", forbidden)
    monkeypatch.setattr(server.mind, "cognition_state", forbidden)
    monkeypatch.setattr(server.mind.llm, "generate", forbidden)
    monkeypatch.setattr(server, "_mindscape_request_event_sync", forbidden)
    monkeypatch.setattr(server, "_mindscape_snapshot", forbidden)

    status = push_server.client.get(
        "/notifications/push/status", headers=CREATOR_HEADERS
    )
    subscribed = _subscribe(push_server)
    delivered, payload = _send_test(push_server)
    acknowledged = push_server.client.post(
        "/notifications/push/ack",
        headers=CREATOR_HEADERS,
        json={
            "event_id": delivered.json()["event_id"],
            "receipt": payload["receipt"],
        },
    )
    revoked = push_server.client.request(
        "DELETE",
        "/notifications/push/subscription",
        headers=CREATOR_HEADERS,
        json={"endpoint": ENDPOINT},
    )

    assert status.status_code == 200
    assert subscribed == {"subscribed": True}
    assert delivered.status_code == 200
    assert acknowledged.status_code == 200
    assert revoked.status_code == 200


def test_acknowledgement_requires_bound_signed_receipt_and_rejects_replay(
    push_server: PushServerHarness,
):
    _subscribe(push_server)
    delivered, payload = _send_test(push_server)
    event_id = delivered.json()["event_id"]
    receipt = str(payload["receipt"])

    wrong_event = push_server.client.post(
        "/notifications/push/ack",
        headers=CREATOR_HEADERS,
        json={"event_id": "out_" + "f" * 32, "receipt": receipt},
    )
    tampered_receipt = receipt[:-1] + ("A" if receipt[-1] != "A" else "B")
    tampered = push_server.client.post(
        "/notifications/push/ack",
        headers=CREATOR_HEADERS,
        json={"event_id": event_id, "receipt": tampered_receipt},
    )
    accepted = push_server.client.post(
        "/notifications/push/ack",
        headers=CREATOR_HEADERS,
        json={"event_id": event_id, "receipt": receipt},
    )
    replay = push_server.client.post(
        "/notifications/push/ack",
        headers=CREATOR_HEADERS,
        json={"event_id": event_id, "receipt": receipt},
    )

    assert wrong_event.status_code == 403
    assert tampered.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json() == {"acknowledged": True}
    assert replay.status_code == 403
    assert replay.json() == {"detail": "acknowledgement receipt rejected"}
    for response in (wrong_event, tampered, accepted, replay):
        assert response.headers["cache-control"] == "no-store"


def test_acknowledgement_maps_a_valid_pre_sent_receipt_to_conflict(
    push_server: PushServerHarness,
):
    _subscribe(push_server)
    event = runtime_mod.enqueue_connection_test(push_server.outbox, push_server.store)
    subscription = push_server.store.subscriptions()[0]
    receipt = push_server.store.issue_ack_receipt(
        event_id=str(event["event_id"]),
        subscription_id=subscription.subscription_id,
        transport_idempotency_key="txi_" + "a" * 64,
    )

    response = push_server.client.post(
        "/notifications/push/ack",
        headers=CREATOR_HEADERS,
        json={"event_id": event["event_id"], "receipt": receipt},
    )

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "detail": "notification is not ready for acknowledgement"
    }
    assert push_server.store.verify_ack_receipt(
        event_id=str(event["event_id"]), receipt=receipt
    ) is True


@pytest.mark.parametrize(
    ("method", "path", "body", "detail"),
    (
        (
            "POST",
            "/notifications/push/subscription",
            {"subscription": SUBSCRIPTION},
            "notification runtime unavailable",
        ),
        (
            "DELETE",
            "/notifications/push/subscription",
            {"endpoint": ENDPOINT},
            "notification runtime unavailable",
        ),
        (
            "POST",
            "/notifications/push/test",
            {},
            "notification delivery unavailable",
        ),
        (
            "POST",
            "/notifications/push/ack",
            {"event_id": "out_" + "0" * 32, "receipt": "wpa_" + "A" * 43},
            "notification acknowledgement unavailable",
        ),
    ),
)
def test_runtime_failures_map_to_secret_free_503(
    push_server: PushServerHarness,
    monkeypatch,
    method: str,
    path: str,
    body: dict[str, object],
    detail: str,
):
    def unavailable_runtime():
        raise RuntimeError("PRIVATE-INTERNAL-RUNTIME-FAILURE")

    monkeypatch.setattr(server, "_notification_runtime", unavailable_runtime)

    response = push_server.client.request(
        method,
        path,
        headers=CREATOR_HEADERS,
        json=body,
    )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": detail}
    assert "PRIVATE-INTERNAL-RUNTIME-FAILURE" not in response.text


def test_phase11_web_push_routes_are_registered_with_exact_methods():
    expected = {
        "/notifications/push/status": {"GET"},
        "/notifications/push/subscription": {"POST", "DELETE"},
        "/notifications/push/test": {"POST"},
        "/notifications/push/ack": {"POST"},
    }
    registered = {path: set() for path in expected}
    for route in server.app.routes:
        if route.path in registered:
            registered[route.path].update(route.methods or set())

    assert registered == expected


def test_notification_runtime_wires_a_distinct_ack_consumption_anchor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    backends: list[object] = []
    anchors: list[object] = []
    loaded_secret_targets: list[str] = []
    store_kwargs: dict[str, object] = {}

    class Backend:
        def __init__(self, target: str) -> None:
            self.target = target
            backends.append(self)

    class Anchor:
        def __init__(self, backend: Backend, *, anchor_key: object) -> None:
            self.backend = backend
            self.anchor_key = anchor_key
            anchors.append(self)

    class Store:
        def __init__(self, _path: Path, **kwargs: object) -> None:
            store_kwargs.update(kwargs)

    monkeypatch.setattr(server, "HOME", tmp_path)
    monkeypatch.setattr(server, "_NOTIFICATION_RUNTIME", None)
    monkeypatch.setattr(
        server,
        "_notification_runtime_mutex",
        lambda: _InjectedProcessMutex(),
    )
    monkeypatch.setattr(server.os, "name", "nt")
    monkeypatch.setattr(server.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(
        server,
        "_notification_credential",
        lambda target, _comment: target,
    )
    monkeypatch.setattr(
        server.web_push_runtime_mod,
        "load_or_create_protected_secret",
        lambda target: (
            loaded_secret_targets.append(target)
            or f"secret:{target}".encode("ascii")
        ),
    )
    monkeypatch.setattr(
        server.notification_anchor_mod,
        "WindowsCredentialManagerBackend",
        Backend,
    )
    monkeypatch.setattr(
        server.notification_anchor_mod,
        "CredentialMonotonicAnchor",
        Anchor,
    )
    monkeypatch.setattr(
        server.notification_outbox_mod,
        "NotificationOutbox",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(server.web_push_runtime_mod, "WebPushPrivateStore", Store)
    monkeypatch.setattr(
        server.web_push_runtime_mod,
        "load_or_create_vapid",
        lambda _record: object(),
    )
    monkeypatch.setattr(
        server.web_push_runtime_mod,
        "PyWebPushTransport",
        lambda _vapid: object(),
    )
    monkeypatch.setattr(
        server.web_push_adapter_mod,
        "WebPushAdapter",
        lambda *_args: object(),
    )

    runtime = server._notification_runtime()

    subscription_anchor = store_kwargs["subscription_anchor"]
    ack_anchor = store_kwargs["ack_anchor"]
    assert runtime["store"].__class__ is Store
    assert subscription_anchor is not ack_anchor
    assert isinstance(subscription_anchor, Anchor)
    assert isinstance(ack_anchor, Anchor)
    assert subscription_anchor.anchor_key != ack_anchor.anchor_key
    assert subscription_anchor.backend.target == (
        server._NOTIFICATION_PUSH_SUBSCRIPTIONS_ANCHOR_TARGET
    )
    assert ack_anchor.backend.target == server._NOTIFICATION_PUSH_ACK_ANCHOR_TARGET
    assert server._NOTIFICATION_PUSH_ACK_ANCHOR_TARGET == (
        "Alpecca/NotificationPushAckAnchor"
    )
    assert len({backend.target for backend in backends}) == 3
    assert server._NOTIFICATION_PUSH_ACK_ANCHOR_KEY_TARGET in loaded_secret_targets
    assert len(backends) == 3
    assert len(anchors) == 3
