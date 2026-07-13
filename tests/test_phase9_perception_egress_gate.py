"""Phase 9 wiring tests: private perception provider attempts are gated.

These prove the fail-closed seam that routes EVERY private perception provider
attempt through an exact provider + model + destination + processing-location +
HTTPS-route consent decision. The generic vision wrappers stay verified-local;
the ONLY reachable remote path is ``vision.describe_image_via_consent`` behind a
satisfied ``PerceptionEgressGate`` decision.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from alpecca import egress_consent as consent_mod
from alpecca import vision


NOW = 10_000.0
SEAL_KEY = b"phase9-egress-gate-seal-key"
SEAL_VERSION = "egress-seal-v2"
ANCHOR_KEY = b"phase9-egress-gate-anchor-key"
ANCHOR_KEY_VERSION = "anchor-seal-v1"

PRIMARY_ROUTE = "vision-primary"
ZEROGPU_ROUTE = "vision-zerogpu"
OPERATION_A = "op_" + "A" * 24
OPERATION_B = "op_" + "B" * 24
IMAGE_BYTES = b"private pixels that must never leak without consent"


class ManualClock:
    def __init__(self, value: float = NOW) -> None:
        self.value = value

    def now(self) -> float:
        return self.value


class FakeAuthority:
    """Stands in for the interactive creator-consent UI."""

    authority_id = "trusted-creator-ui"
    version = 1
    creator_scope = "creator-private"

    def __init__(self) -> None:
        self.decisions: deque[consent_mod.CreatorDecision] = deque()
        self.requests: list[consent_mod.AuthorityRequest] = []
        self._counter = 0

    def queue(self, allowed: bool) -> str:
        self._counter += 1
        identifier = "decision_" + f"{self._counter:024d}"
        self.decisions.append(consent_mod.CreatorDecision(identifier, allowed))
        return identifier

    def decide(
        self, request: consent_mod.AuthorityRequest
    ) -> consent_mod.CreatorDecision:
        self.requests.append(request)
        if not self.decisions:
            raise RuntimeError("no queued creator decision")
        return self.decisions.popleft()


def _policy(*, primary_uses: int = 1) -> consent_mod.EgressPolicy:
    return consent_mod.EgressPolicy(
        policy_id="private-perception-egress",
        version=1,
        routes=(
            consent_mod.AllowedEgressRoute(
                route_id=PRIMARY_ROUTE,
                provider="provider-a",
                deployment="vision-deployment-a",
                model="acme/private-vision-v2",
                capability="private-image-description",
                purpose="describe-private-image",
                processing_location="us-west-2",
                destination_class="managed-model-api",
                transport_route="https://vision.example.test/v1/infer",
                ttl_seconds=30,
                max_uses=primary_uses,
                max_bytes_per_use=2 * 1024 * 1024,
            ),
            consent_mod.AllowedEgressRoute(
                route_id=ZEROGPU_ROUTE,
                provider="provider-z",
                deployment="zerogpu-space-a",
                model="qwen/private-vl",
                capability="private-image-description",
                purpose="describe-private-image",
                processing_location="hf-zerogpu-ephemeral",
                destination_class="hosted-space-gpu",
                transport_route="https://space.example.test/vision",
                ttl_seconds=30,
                max_uses=1,
                max_bytes_per_use=2 * 1024 * 1024,
            ),
        ),
    )


def _ledger(
    tmp_path: Path,
    *,
    authority: FakeAuthority | None = None,
    clock: ManualClock | None = None,
    policy: consent_mod.EgressPolicy | None = None,
) -> tuple[consent_mod.EgressConsentLedger, FakeAuthority, ManualClock]:
    active_authority = authority or FakeAuthority()
    active_clock = clock or ManualClock()
    anchor = consent_mod.SQLiteMonotonicAnchor(
        tmp_path / "egress-anchor.db",
        anchor_key=ANCHOR_KEY,
        anchor_key_version=ANCHOR_KEY_VERSION,
    )
    ledger = consent_mod.EgressConsentLedger(
        tmp_path / "egress.db",
        seal_key=SEAL_KEY,
        seal_key_version=SEAL_VERSION,
        authority=active_authority,
        policy=policy or _policy(),
        clock=active_clock,
        anchor=anchor,
    )
    return ledger, active_authority, active_clock


def _gate(
    tmp_path: Path, **kwargs
) -> tuple[consent_mod.PerceptionEgressGate, FakeAuthority, ManualClock]:
    ledger, authority, clock = _ledger(tmp_path, **kwargs)
    return consent_mod.PerceptionEgressGate(ledger), authority, clock


# --- Gate-level contract -----------------------------------------------------


def test_gate_requires_a_real_ledger():
    with pytest.raises(consent_mod.EgressConsentError):
        consent_mod.PerceptionEgressGate(object())  # type: ignore[arg-type]


def test_authorize_attempt_grants_and_attests_the_exact_route(tmp_path: Path):
    gate, authority, _clock = _gate(tmp_path)
    authority.queue(True)

    authorization = gate.authorize_attempt(
        operation_id=OPERATION_A,
        route_id=PRIMARY_ROUTE,
        payload=IMAGE_BYTES,
    )

    assert isinstance(authorization, consent_mod.PerceptionEgressAuthorization)
    assert authorization.route_id == PRIMARY_ROUTE
    assert authorization.provider == "provider-a"
    assert authorization.deployment == "vision-deployment-a"
    assert authorization.model == "acme/private-vision-v2"
    assert authorization.processing_location == "us-west-2"
    assert authorization.destination_class == "managed-model-api"
    assert authorization.transport_route == "https://vision.example.test/v1/infer"
    assert authorization.byte_count == len(IMAGE_BYTES)
    # Exactly one creator decision was consulted for this one attempt.
    assert len(authority.requests) == 1
    request = authority.requests[0]
    assert request.provider == "provider-a"
    assert request.processing_location == "us-west-2"
    assert request.byte_count == len(IMAGE_BYTES)
    # A sealed attempt receipt exists before any egress could occur.
    assert authorization.attempt_evidence


def test_creator_denial_authorizes_nothing(tmp_path: Path):
    gate, authority, _clock = _gate(tmp_path)
    authority.queue(False)

    with pytest.raises(consent_mod.EgressConsentDenied):
        gate.authorize_attempt(
            operation_id=OPERATION_A,
            route_id=PRIMARY_ROUTE,
            payload=IMAGE_BYTES,
        )
    assert len(authority.requests) == 1


def test_unknown_route_is_denied_before_the_authority(tmp_path: Path):
    gate, authority, _clock = _gate(tmp_path)

    with pytest.raises(consent_mod.EgressConsentDenied):
        gate.authorize_attempt(
            operation_id=OPERATION_A,
            route_id="route-not-in-policy",
            payload=IMAGE_BYTES,
        )
    assert authority.requests == []


def test_oversize_payload_fails_closed_without_consulting_the_creator(
    tmp_path: Path,
):
    policy = _policy()
    # A route with a tiny cap so a normal image is over the limit.
    small = consent_mod.EgressPolicy(
        policy_id="private-perception-egress",
        version=1,
        routes=(
            consent_mod.AllowedEgressRoute(
                route_id=PRIMARY_ROUTE,
                provider="provider-a",
                deployment="vision-deployment-a",
                model="acme/private-vision-v2",
                capability="private-image-description",
                purpose="describe-private-image",
                processing_location="us-west-2",
                destination_class="managed-model-api",
                transport_route="https://vision.example.test/v1/infer",
                ttl_seconds=30,
                max_uses=1,
                max_bytes_per_use=8,
            ),
        ),
    )
    assert policy is not small
    gate, authority, _clock = _gate(tmp_path, policy=small)
    authority.queue(True)

    with pytest.raises(consent_mod.EgressConsentDenied):
        gate.authorize_attempt(
            operation_id=OPERATION_A,
            route_id=PRIMARY_ROUTE,
            payload=IMAGE_BYTES,
        )
    # The oversize payload never reached the creator authority.
    assert authority.requests == []


def test_empty_payload_is_denied(tmp_path: Path):
    gate, authority, _clock = _gate(tmp_path)
    with pytest.raises(consent_mod.EgressConsentDenied):
        gate.authorize_attempt(
            operation_id=OPERATION_A, route_id=PRIMARY_ROUTE, payload=b""
        )
    assert authority.requests == []


def test_single_use_grant_needs_a_fresh_decision_to_reauthorize(tmp_path: Path):
    gate, authority, _clock = _gate(tmp_path)  # primary max_uses=1
    authority.queue(True)

    gate.authorize_attempt(
        operation_id=OPERATION_A, route_id=PRIMARY_ROUTE, payload=IMAGE_BYTES
    )
    # No fresh creator decision queued: a second attempt is denied.
    with pytest.raises(consent_mod.EgressConsentDenied):
        gate.authorize_attempt(
            operation_id=OPERATION_A, route_id=PRIMARY_ROUTE, payload=IMAGE_BYTES
        )


# --- Vision integration: the only reachable remote path ----------------------


def _record_transport(calls: list[tuple[bytes, str]], reply: str | None):
    def transport(image_bytes: bytes, prompt: str):
        calls.append((image_bytes, prompt))
        return reply

    return transport


def test_consented_remote_vision_calls_provider_and_reports_it_remote(
    tmp_path: Path, monkeypatch
):
    gate, authority, _clock = _gate(tmp_path)
    authority.queue(True)
    calls: list[tuple[bytes, str]] = []
    monkeypatch.setattr(
        vision, "_describe_ollama_cloud", _record_transport(calls, "a remote view")
    )
    # If anything routes to local, fail loudly.
    monkeypatch.setattr(
        vision,
        "_describe_local",
        lambda *_a, **_k: pytest.fail("consented path must not use local vision"),
    )

    result = vision.describe_image_via_consent(
        IMAGE_BYTES,
        gate=gate,
        route_id=PRIMARY_ROUTE,
        operation_id=OPERATION_A,
        provider="ollama-cloud",
    )

    assert result is not None
    assert result.text == "a remote view"
    assert calls == [(IMAGE_BYTES, vision._DESCRIBE_PROMPT)]
    # Never relabelled local.
    assert result.processing_location == "us-west-2"
    assert result.processing_location != "local-only"
    assert result.backend == "provider-a:vision-deployment-a"
    assert result.backend != "local-ollama"
    assert result.cloud_egress == "managed-model-api"


def test_zerogpu_route_reports_ephemeral_location(tmp_path: Path, monkeypatch):
    gate, authority, _clock = _gate(tmp_path)
    authority.queue(True)
    calls: list[tuple[bytes, str]] = []
    monkeypatch.setattr(
        vision, "_describe_zerogpu", _record_transport(calls, "space view")
    )

    result = vision.describe_image_via_consent(
        IMAGE_BYTES,
        gate=gate,
        route_id=ZEROGPU_ROUTE,
        operation_id=OPERATION_A,
        provider="zerogpu",
    )

    assert result is not None
    assert result.processing_location == "hf-zerogpu-ephemeral"
    assert result.processing_location != "local-only"
    assert result.backend == "provider-z:zerogpu-space-a"
    assert len(calls) == 1


def test_denied_consent_never_calls_the_remote_provider(tmp_path: Path, monkeypatch):
    gate, authority, _clock = _gate(tmp_path)
    authority.queue(False)

    def forbidden(*_a, **_k):
        pytest.fail("remote provider must not run without consent")

    monkeypatch.setattr(vision, "_describe_ollama_cloud", forbidden)
    monkeypatch.setattr(vision, "_describe_zerogpu", forbidden)

    result = vision.describe_image_via_consent(
        IMAGE_BYTES,
        gate=gate,
        route_id=PRIMARY_ROUTE,
        operation_id=OPERATION_A,
        provider="ollama-cloud",
    )

    assert result is None
    assert len(authority.requests) == 1


def test_unknown_provider_never_touches_the_gate(tmp_path: Path, monkeypatch):
    gate, authority, _clock = _gate(tmp_path)

    def forbidden(*_a, **_k):
        pytest.fail("no transport should run for an unknown provider")

    monkeypatch.setattr(vision, "_describe_ollama_cloud", forbidden)
    monkeypatch.setattr(vision, "_describe_zerogpu", forbidden)

    result = vision.describe_image_via_consent(
        IMAGE_BYTES,
        gate=gate,
        route_id=PRIMARY_ROUTE,
        operation_id=OPERATION_A,
        provider="some-unlisted-provider",
    )

    assert result is None
    assert authority.requests == []


def test_transport_failure_after_consent_returns_none(tmp_path: Path, monkeypatch):
    gate, authority, _clock = _gate(tmp_path)
    authority.queue(True)
    calls: list[tuple[bytes, str]] = []
    monkeypatch.setattr(
        vision, "_describe_ollama_cloud", _record_transport(calls, None)
    )

    result = vision.describe_image_via_consent(
        IMAGE_BYTES,
        gate=gate,
        route_id=PRIMARY_ROUTE,
        operation_id=OPERATION_A,
        provider="ollama-cloud",
    )

    assert result is None
    # Consent was consulted and the attempt was authorized before the transport
    # failed; the single-use grant is now spent.
    assert len(authority.requests) == 1
    assert len(calls) == 1


def test_reused_operation_without_new_consent_is_fail_closed(
    tmp_path: Path, monkeypatch
):
    gate, authority, _clock = _gate(tmp_path)  # primary max_uses=1
    authority.queue(True)
    calls: list[tuple[bytes, str]] = []
    monkeypatch.setattr(
        vision, "_describe_ollama_cloud", _record_transport(calls, "one view")
    )

    first = vision.describe_image_via_consent(
        IMAGE_BYTES,
        gate=gate,
        route_id=PRIMARY_ROUTE,
        operation_id=OPERATION_A,
        provider="ollama-cloud",
    )
    second = vision.describe_image_via_consent(
        IMAGE_BYTES,
        gate=gate,
        route_id=PRIMARY_ROUTE,
        operation_id=OPERATION_A,
        provider="ollama-cloud",
    )

    assert first is not None
    assert second is None
    assert len(calls) == 1  # provider ran exactly once


@pytest.mark.parametrize("bad_gate", (None, object(), "not-a-gate"))
def test_missing_or_invalid_gate_falls_back_without_calling_provider(
    monkeypatch, bad_gate
):
    def forbidden(*_a, **_k):
        pytest.fail("a missing/invalid gate must never run a remote transport")

    monkeypatch.setattr(vision, "_describe_ollama_cloud", forbidden)
    monkeypatch.setattr(vision, "_describe_zerogpu", forbidden)

    result = vision.describe_image_via_consent(
        IMAGE_BYTES,
        gate=bad_gate,  # type: ignore[arg-type]
        route_id=PRIMARY_ROUTE,
        operation_id=OPERATION_A,
        provider="ollama-cloud",
    )

    assert result is None


def test_empty_image_never_reaches_gate_or_provider(tmp_path: Path, monkeypatch):
    gate, authority, _clock = _gate(tmp_path)

    def forbidden(*_a, **_k):
        pytest.fail("empty image must not run a transport")

    monkeypatch.setattr(vision, "_describe_ollama_cloud", forbidden)

    result = vision.describe_image_via_consent(
        b"",
        gate=gate,
        route_id=PRIMARY_ROUTE,
        operation_id=OPERATION_A,
        provider="ollama-cloud",
    )

    assert result is None
    assert authority.requests == []
