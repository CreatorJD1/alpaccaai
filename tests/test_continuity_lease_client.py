from __future__ import annotations

import json
import threading
import time
import urllib.parse

import pytest

import alpecca.continuity_lease as continuity_module
from alpecca.continuity_lease import (
    ContinuityLeaseClient,
    ContinuityLeaseError,
    ContinuityLeaseGuard,
    LeaseGrant,
)


class _Response:
    def __init__(self, body: dict, status: int = 200):
        self._body = json.dumps(body).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size: int) -> bytes:
        return self._body


class _Opener:
    def __init__(self, *responses: _Response):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, *, timeout):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


def _lease(epoch: int = 7, lease_id: str = "lease-7") -> dict:
    return {
        "ok": True,
        "lease": {
            "leaseId": lease_id,
            "holderNodeId": "local-primary:test",
            "fencingEpoch": epoch,
            "ttlRemainingSeconds": 35,
        },
    }


def _client(opener, *, role="local-primary"):
    return ContinuityLeaseClient(
        "https://lease.example.test",
        "t" * 32,
        "local-primary:test",
        role,
        opener=opener,
    )


def test_lease_url_requires_https_except_loopback():
    with pytest.raises(ContinuityLeaseError, match="HTTPS"):
        ContinuityLeaseClient("http://example.test", "t" * 32, "node", "local-primary")
    assert ContinuityLeaseClient(
        "http://127.0.0.1:8787", "t" * 32, "node", "local-primary"
    ).base_url.endswith(":8787")


def test_acquire_uses_authority_contract_and_parses_fence():
    opener = _Opener(_Response(_lease(), 201))
    grant = _client(opener).acquire()

    assert grant == LeaseGrant("lease-7", 7, 35, "local-primary:test", "local-primary")
    request, timeout = opener.requests[0]
    assert urllib.parse.urlparse(request.full_url).path == "/v1/lease/acquire"
    assert request.method == "POST"
    assert timeout == 5.0
    assert json.loads(request.data) == {
        "holderNodeId": "local-primary:test",
        "ttlSeconds": 35,
    }


def test_renewal_cannot_change_the_active_fence():
    opener = _Opener(_Response(_lease(epoch=8, lease_id="lease-8")))
    client = _client(opener)
    with pytest.raises(ContinuityLeaseError, match="changed the active lease fence"):
        client.renew(LeaseGrant("lease-7", 7, 35, client.node_id, client.role))


def test_relay_can_publish_only_against_this_nodes_active_fence():
    status = {
        "ok": True,
        "activeLease": {
            "leaseId": "lease-7",
            "holderNodeId": "local-primary:test",
            "fencingEpoch": 7,
            "ttlRemainingSeconds": 21,
        },
    }
    opener = _Opener(_Response(status), _Response({"ok": True}))
    client = _client(opener)

    assert client.publish_active_endpoint("https://phone.example.test") == {
        "ok": True,
        "httpStatus": 200,
    }
    status_request, _ = opener.requests[0]
    publish_request, _ = opener.requests[1]
    assert status_request.method == "GET"
    assert urllib.parse.urlparse(status_request.full_url).path == "/v1/status"
    assert publish_request.method == "PUT"
    assert urllib.parse.urlparse(publish_request.full_url).path == "/v1/endpoint"
    assert json.loads(publish_request.data) == {
        "endpoint": "https://phone.example.test",
        "fencingEpoch": 7,
        "holderNodeId": "local-primary:test",
        "leaseId": "lease-7",
    }


def test_relay_refuses_to_publish_another_nodes_active_fence():
    status = {
        "ok": True,
        "activeLease": {
            "leaseId": "lease-9",
            "holderNodeId": "cloud-standby:other",
            "fencingEpoch": 9,
            "ttlRemainingSeconds": 20,
        },
    }
    opener = _Opener(_Response(status))
    with pytest.raises(ContinuityLeaseError, match="different holder"):
        _client(opener).publish_active_endpoint("https://stale.example.test")
    assert len(opener.requests) == 1


def test_client_reads_user_scoped_windows_url_when_parent_env_is_stale(monkeypatch):
    monkeypatch.delenv("ALPECCA_CONTINUITY_LEASE_URL", raising=False)
    monkeypatch.delenv("ALPECCA_CONTINUITY_LEASE_TOKEN", raising=False)
    monkeypatch.setattr(
        continuity_module,
        "_windows_user_environment",
        lambda name: (
            "https://lease.example.test"
            if name == "ALPECCA_CONTINUITY_LEASE_URL"
            else ""
        ),
    )
    monkeypatch.setattr(
        continuity_module,
        "_windows_credential_token",
        lambda: "t" * 32,
    )

    client = continuity_module.client_from_env(role="local-primary")
    assert client is not None
    assert client.base_url == "https://lease.example.test"
    assert client.node_id.startswith("local-primary:")


class _RecordingClient:
    def __init__(self, role: str, *, renewal_error: bool = False):
        self.role = role
        self.calls = []
        self.renewal_error = renewal_error

    def heartbeat(self, endpoint=""):
        self.calls.append("heartbeat")
        return {"ok": True}

    def acquire(self):
        self.calls.append("acquire")
        return LeaseGrant("lease", 1, 1, "node", self.role)

    def renew(self, grant):
        self.calls.append("renew")
        if self.renewal_error:
            raise ContinuityLeaseError("offline")
        return grant

    def release(self, _grant):
        self.calls.append("release")
        return {"ok": True}

    def publish_endpoint(self, _grant, _endpoint):
        self.calls.append("publish")
        return {"ok": True}


def test_local_guard_heartbeats_before_acquiring():
    client = _RecordingClient("local-primary")
    guard = ContinuityLeaseGuard(client, renew_seconds=15)
    try:
        guard.start()
        assert client.calls[:2] == ["heartbeat", "acquire"]
    finally:
        guard.stop()


def test_cloud_guard_does_not_publish_a_local_heartbeat():
    client = _RecordingClient("cloud-standby")
    guard = ContinuityLeaseGuard(client, renew_seconds=15)
    try:
        guard.start()
        assert client.calls[0] == "acquire"
        assert "heartbeat" not in client.calls
    finally:
        guard.stop()


def test_guard_reports_loss_only_after_lease_expiry():
    client = _RecordingClient("cloud-standby", renewal_error=True)
    lost = threading.Event()
    guard = ContinuityLeaseGuard(client, renew_seconds=1, on_loss=lambda _reason: lost.set())
    guard.start()
    try:
        assert not lost.wait(0.25)
        assert lost.wait(2.0)
    finally:
        guard.stop()
