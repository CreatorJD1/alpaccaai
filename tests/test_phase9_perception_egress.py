"""Consent-bound dispatch tests for Phase 9 private perception egress."""
from __future__ import annotations

import base64
import hashlib
import inspect
import json
import ssl
from collections import deque
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from alpecca import egress_consent as consent_mod
from alpecca import attachment_ingress, attachment_perception
from alpecca import perception_egress, vision


ROUTE_ID = "vision-primary"
PROFILE = perception_egress.PrivateImagePromptProfile.DESCRIBE_V1
INGRESS_SCOPE = PROFILE.ingress_scope
REAL_POST_EXACT_HTTPS = perception_egress._post_exact_https


def _png(width: int = 2, height: int = 2, suffix: bytes = b"") -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + suffix
    )


IMAGE_BYTES = _png()


@pytest.fixture(autouse=True)
def _deny_unmocked_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        pytest.fail("test attempted unmocked private-provider network I/O")

    monkeypatch.setattr(perception_egress, "_post_exact_https", fail)


class ManualClock:
    def __init__(self, value: float = 10_000.0) -> None:
        self.value = value

    def now(self) -> float:
        return self.value


class MemoryAnchor:
    def __init__(self) -> None:
        self.state: consent_mod.AnchorState | None = None

    def load(self) -> consent_mod.AnchorState | None:
        return self.state

    def initialize(self, state: consent_mod.AnchorState) -> None:
        if self.state is not None:
            raise RuntimeError("already initialized")
        self.state = state

    def advance(
        self,
        expected: consent_mod.AnchorState,
        updated: consent_mod.AnchorState,
    ) -> None:
        if self.state != expected:
            raise RuntimeError("compare-and-swap failed")
        self.state = updated


class FakeAuthority:
    authority_id = "trusted-creator-ui"
    version = 1
    creator_scope = "creator-private"

    def __init__(self) -> None:
        self.decisions: deque[consent_mod.CreatorDecision] = deque()
        self.requests: list[consent_mod.AuthorityRequest] = []

    def queue(self, allowed: bool) -> None:
        index = len(self.decisions) + len(self.requests) + 1
        self.decisions.append(
            consent_mod.CreatorDecision(
                "decision_" + f"{index:024d}",
                allowed,
            )
        )

    def decide(
        self, request: consent_mod.AuthorityRequest
    ) -> consent_mod.CreatorDecision:
        self.requests.append(request)
        if not self.decisions:
            raise RuntimeError("no queued creator decision")
        return self.decisions.popleft()


def _route(
    *,
    capability: str = "private-image-description",
    purpose: str = "describe-private-image",
    max_uses: int = 1,
    max_bytes: int = 4_096,
    processing_location: str = "us-west-2",
) -> consent_mod.AllowedEgressRoute:
    return consent_mod.AllowedEgressRoute(
        route_id=ROUTE_ID,
        provider="provider-a",
        deployment="vision-deployment-a",
        model="acme/private-vision-v2",
        capability=capability,
        purpose=purpose,
        processing_location=processing_location,
        destination_class="managed-model-api",
        transport_route="https://vision.example.test/v1/infer",
        ttl_seconds=30,
        max_uses=max_uses,
        max_bytes_per_use=max_bytes,
    )


def _ledger(
    tmp_path: Path,
    *,
    route: consent_mod.AllowedEgressRoute | None = None,
) -> tuple[consent_mod.EgressConsentLedger, FakeAuthority]:
    authority = FakeAuthority()
    ledger = consent_mod.EgressConsentLedger(
        tmp_path / "perception-egress.db",
        seal_key=b"phase9-perception-egress-seal-key",
        seal_key_version="perception-seal-v1",
        authority=authority,
        policy=consent_mod.EgressPolicy(
            policy_id="private-perception-egress",
            version=1,
            routes=(route or _route(),),
        ),
        clock=ManualClock(),
        anchor=MemoryAnchor(),
    )
    return ledger, authority


def _endpoint(
    route: consent_mod.AllowedEgressRoute,
) -> perception_egress.PrivateImageEndpoint:
    return perception_egress.PrivateImageEndpoint(
        perception_egress.ProviderAttestation.from_route(route),
        credential=perception_egress.BearerCredential("unit-test-credential"),
    )


def _ingress(
    image_bytes: bytes = IMAGE_BYTES,
    *,
    scope: str = INGRESS_SCOPE,
) -> attachment_ingress.ImageIngress:
    return attachment_ingress.inspect_image_bytes(
        image_bytes,
        scope=scope,
        authorized_scopes=(scope,),
        source="creator:private-image",
        declared_mime_type="image/png",
    )


def _response(text: str = "A grounded private description.") -> bytes:
    return json.dumps(
        {"choices": [{"message": {"content": text}}]},
        separators=(",", ":"),
    ).encode("utf-8")


class WireRecorder:
    def __init__(
        self,
        response: perception_egress.ProviderWireResponse | BaseException | None = None,
        *,
        ledger: consent_mod.EgressConsentLedger | None = None,
    ) -> None:
        self.response = response or perception_egress.ProviderWireResponse(
            200,
            _response(),
        )
        self.ledger = ledger
        self.calls: list[
            tuple[
                consent_mod.AllowedEgressRoute,
                bytes,
                perception_egress.PrivateImageEndpoint,
            ]
        ] = []
        self.receipt_events_at_send: list[str] = []

    def __call__(
        self,
        route: consent_mod.AllowedEgressRoute,
        payload: bytes,
        endpoint: perception_egress.PrivateImageEndpoint,
    ) -> perception_egress.ProviderWireResponse:
        self.calls.append((route, payload, endpoint))
        if self.ledger is not None:
            self.receipt_events_at_send = [
                str(item["event"])
                for item in self.ledger.status()["receipts"]
            ]
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def _install_wire(
    monkeypatch: pytest.MonkeyPatch,
    recorder: WireRecorder,
) -> None:
    monkeypatch.setattr(perception_egress, "_post_exact_https", recorder)


def _describe(
    ledger: consent_mod.EgressConsentLedger,
    endpoint: perception_egress.PrivateImageEndpoint,
    ingress: attachment_ingress.ImageIngress | None = None,
) -> perception_egress.PrivateImageDescriptionResult:
    return perception_egress.describe_private_image_with_consent(
        ingress or _ingress(),
        ledger=ledger,
        endpoint=endpoint,
    )


def test_exact_payload_is_consumed_before_one_outbound_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    authority.queue(True)
    endpoint = _endpoint(route)
    wire = WireRecorder(ledger=ledger)
    _install_wire(monkeypatch, wire)

    result = _describe(ledger, endpoint)

    assert result.text == "A grounded private description."
    assert result.outcome == "described"
    assert result.route == endpoint.attestation
    assert result.attempt.outcome == "authorized_before_outbound"
    assert len(wire.calls) == 1
    sent_route, payload, sent_endpoint = wire.calls[0]
    assert sent_route == route
    assert sent_endpoint is endpoint
    assert "use" in wire.receipt_events_at_send

    decoded = json.loads(payload.decode("utf-8"))
    assert decoded["model"] == route.model
    assert decoded["messages"][0]["content"][0]["text"] == PROFILE.prompt
    data_url = decoded["messages"][0]["content"][1]["image_url"]["url"]
    assert data_url.startswith("data:image/png;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]) == IMAGE_BYTES
    assert b"unit-test-credential" not in payload

    request = authority.requests[0]
    assert request.route_id == route.route_id
    assert request.provider == route.provider
    assert request.deployment == route.deployment
    assert request.model == route.model
    assert request.capability == route.capability
    assert request.purpose == route.purpose
    assert request.processing_location == route.processing_location
    assert request.destination_class == route.destination_class
    assert request.transport_route == route.transport_route
    assert request.byte_count == len(payload) == result.attempt.byte_count
    assert "unit-test-credential" not in repr(endpoint)
    assert "unit-test-credential" not in repr(asdict(endpoint))
    assert "ec2_" not in repr(result)
    assert ledger.status()["active"] == []


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("provider", "provider-b"),
        ("deployment", "vision-deployment-b"),
        ("model", "acme/other-model"),
        ("capability", "private-image-analysis"),
        ("purpose", "classify-private-image"),
        ("processing_location", "eu-west-1"),
        ("destination_class", "alternate-model-api"),
        ("transport_route", "https://other.example.test/v1/infer"),
    ),
)
def test_attestation_mismatch_fails_before_authority_or_network(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    attestation = replace(
        perception_egress.ProviderAttestation.from_route(route),
        **{field: replacement},
    )
    endpoint = perception_egress.PrivateImageEndpoint(attestation)

    with pytest.raises(perception_egress.PerceptionEgressDenied) as exc_info:
        _describe(ledger, endpoint)

    assert exc_info.value.reason == "provider_route_mismatch"
    assert authority.requests == []


def test_unknown_attested_route_fails_before_authority_or_network(
    tmp_path: Path,
) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    endpoint = perception_egress.PrivateImageEndpoint(
        replace(
            perception_egress.ProviderAttestation.from_route(route),
            route_id="vision-unregistered",
        )
    )

    with pytest.raises(consent_mod.EgressConsentDenied) as exc_info:
        _describe(ledger, endpoint)

    assert exc_info.value.reason == "route_not_allowed"
    assert authority.requests == []


def test_creator_denial_never_consumes_or_dispatches(tmp_path: Path) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    authority.queue(False)

    with pytest.raises(perception_egress.PerceptionEgressDenied) as exc_info:
        _describe(ledger, _endpoint(route))

    assert exc_info.value.reason == "creator_denied"
    assert [
        item["event"] for item in ledger.status()["receipts"]
    ] == ["deny"]


def test_authority_unavailable_never_consumes_or_dispatches(tmp_path: Path) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)

    with pytest.raises(consent_mod.EgressConsentDenied) as exc_info:
        _describe(ledger, _endpoint(route))

    assert exc_info.value.reason == "authority_unavailable"
    assert len(authority.requests) == 1
    assert ledger.status()["receipts"] == []


def test_invalid_authority_response_never_consumes_or_dispatches(
    tmp_path: Path,
) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    authority.decisions.append(object())  # type: ignore[arg-type]

    with pytest.raises(consent_mod.EgressConsentDenied) as exc_info:
        _describe(ledger, _endpoint(route))

    assert exc_info.value.reason == "authority_response_invalid"
    assert ledger.status()["receipts"] == []


def test_wrong_capability_fails_before_authority_or_network(tmp_path: Path) -> None:
    route = _route(capability="private-audio-transcription")
    ledger, authority = _ledger(tmp_path, route=route)

    with pytest.raises(perception_egress.PerceptionEgressDenied) as exc_info:
        _describe(ledger, _endpoint(route))

    assert exc_info.value.reason == "route_capability_mismatch"
    assert authority.requests == []


def test_wrong_route_purpose_fails_before_authority_or_network(tmp_path: Path) -> None:
    route = _route(purpose="classify-private-image")
    ledger, authority = _ledger(tmp_path, route=route)

    with pytest.raises(perception_egress.PerceptionEgressDenied) as exc_info:
        _describe(ledger, _endpoint(route))

    assert exc_info.value.reason == "route_purpose_mismatch"
    assert authority.requests == []


def test_non_one_shot_route_fails_before_authority_or_network(tmp_path: Path) -> None:
    route = _route(max_uses=2)
    ledger, authority = _ledger(tmp_path, route=route)

    with pytest.raises(perception_egress.PerceptionEgressDenied) as exc_info:
        _describe(ledger, _endpoint(route))

    assert exc_info.value.reason == "provider_route_must_be_one_shot"
    assert authority.requests == []


def test_oversized_serialized_body_fails_before_authority(tmp_path: Path) -> None:
    route = _route(max_bytes=512)
    ledger, authority = _ledger(tmp_path, route=route)
    large_ingress = _ingress(_png(suffix=b"x" * 512))

    with pytest.raises(perception_egress.PerceptionEgressDenied) as exc_info:
        perception_egress.describe_private_image_with_consent(
            large_ingress,
            ledger=ledger,
            endpoint=_endpoint(route),
        )

    assert exc_info.value.reason == "provider_payload_too_large"
    assert authority.requests == []


def test_forged_image_metadata_fails_before_authority(tmp_path: Path) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    disguised = b"\x89PNG\r\n\x1a\nprivate-non-image-data"
    envelope = attachment_perception.create_attachment_envelope(
        scope=INGRESS_SCOPE,
        authorized_scopes=(INGRESS_SCOPE,),
        source="creator:forged-image",
        mime_type="image/png",
        attachment_type="image",
        sha256=hashlib.sha256(disguised).hexdigest(),
        size_bytes=len(disguised),
        width=1,
        height=1,
        processing_location="local-only",
        cloud_egress="denied",
    )
    forged = attachment_ingress.ImageIngress(disguised, envelope)

    with pytest.raises(perception_egress.PerceptionEgressDenied) as exc_info:
        perception_egress.describe_private_image_with_consent(
            forged,
            ledger=ledger,
            endpoint=_endpoint(route),
        )

    assert exc_info.value.reason == "image_ingress_metadata_mismatch"
    assert authority.requests == []


def test_wrong_ingress_scope_fails_before_authority(tmp_path: Path) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)

    with pytest.raises(perception_egress.PerceptionEgressDenied) as exc_info:
        _describe(
            ledger,
            _endpoint(route),
            _ingress(scope="creator-chat-image"),
        )

    assert exc_info.value.reason == "image_ingress_scope_mismatch"
    assert authority.requests == []


def test_tampered_ingress_bytes_fail_digest_binding(tmp_path: Path) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    valid = _ingress()
    tampered = attachment_ingress.ImageIngress(
        image_bytes=valid.image_bytes + b"private-tail",
        envelope=valid.envelope,
    )

    with pytest.raises(perception_egress.PerceptionEgressDenied) as exc_info:
        _describe(ledger, _endpoint(route), tampered)

    assert exc_info.value.reason == "image_ingress_digest_mismatch"
    assert authority.requests == []


def test_private_prompt_is_code_owned_and_not_a_public_argument() -> None:
    adapter_params = inspect.signature(
        perception_egress.describe_private_image_with_consent
    ).parameters
    vision_params = inspect.signature(
        vision.describe_image_result_with_explicit_egress
    ).parameters

    assert "prompt" not in adapter_params
    assert "prompt" not in vision_params
    assert PROFILE.prompt.startswith("Describe this image")


def test_credential_subclasses_are_rejected() -> None:
    class ActiveCredential(perception_egress.BearerCredential):
        def authorization_header(self) -> str:
            raise AssertionError("credential subclass executed")

    route = _route()

    with pytest.raises(TypeError, match="credential must be BearerCredential"):
        perception_egress.PrivateImageEndpoint(
            perception_egress.ProviderAttestation.from_route(route),
            credential=ActiveCredential("unit-test-secret"),
        )


def test_attestation_subclasses_are_rejected() -> None:
    class ActiveAttestation(perception_egress.ProviderAttestation):
        def matches(self, _route: consent_mod.AllowedEgressRoute) -> bool:
            raise AssertionError("attestation subclass executed")

    route = _route()
    base = perception_egress.ProviderAttestation.from_route(route)
    active = ActiveAttestation(
        route_id=base.route_id,
        provider=base.provider,
        deployment=base.deployment,
        model=base.model,
        capability=base.capability,
        purpose=base.purpose,
        processing_location=base.processing_location,
        destination_class=base.destination_class,
        transport_route=base.transport_route,
    )

    with pytest.raises(TypeError, match="attestation must be ProviderAttestation"):
        perception_egress.PrivateImageEndpoint(active)


def test_exact_payload_limit_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = _route(max_bytes=4_096)
    payload = perception_egress._serialize_image_request(
        IMAGE_BYTES,
        "image/png",
        PROFILE,
        _endpoint(template),
    )
    route = _route(max_bytes=len(payload))
    ledger, authority = _ledger(tmp_path, route=route)
    authority.queue(True)
    wire = WireRecorder()
    _install_wire(monkeypatch, wire)

    result = _describe(ledger, _endpoint(route))

    assert result.outcome == "described"
    assert authority.requests[0].byte_count == len(payload)
    assert len(wire.calls) == 1


def test_consume_failure_prevents_outbound_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    authority.queue(True)

    def fail_consume(
        _self: consent_mod.EgressConsentLedger,
        **_kwargs: object,
    ) -> dict[str, object]:
        raise consent_mod.EgressConsentQuarantined("test_quarantine")

    monkeypatch.setattr(
        consent_mod.EgressConsentLedger,
        "consume_active",
        fail_consume,
    )

    with pytest.raises(consent_mod.EgressConsentQuarantined) as exc_info:
        _describe(ledger, _endpoint(route))

    assert exc_info.value.reason == "test_quarantine"


def test_provider_failure_is_one_audited_attempt_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    authority.queue(True)
    wire = WireRecorder(RuntimeError("provider unavailable"))
    _install_wire(monkeypatch, wire)

    result = _describe(ledger, _endpoint(route))

    assert result.text is None
    assert result.outcome == "provider_error"
    assert result.attempt.outcome == "authorized_before_outbound"
    assert len(wire.calls) == 1
    events = [item["event"] for item in ledger.status()["receipts"]]
    assert events.count("use") == 1
    assert events.count("grant") == 1


@pytest.mark.parametrize(
    ("response", "outcome"),
    (
        (perception_egress.ProviderWireResponse(307, b"redirect"), "provider_redirect_rejected"),
        (perception_egress.ProviderWireResponse(503, b"unavailable"), "provider_http_error"),
        (perception_egress.ProviderWireResponse(200, b"not-json"), "invalid_response"),
        (perception_egress.ProviderWireResponse(200, _response("")), "invalid_response"),
        (
            perception_egress.ProviderWireResponse(200, _response("x" * 8_001)),
            "response_too_large",
        ),
        (perception_egress.ProviderWireResponse(200, b"", True), "response_too_large"),
    ),
)
def test_provider_response_never_retries_or_falls_through(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: perception_egress.ProviderWireResponse,
    outcome: str,
) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    authority.queue(True)
    wire = WireRecorder(response)
    _install_wire(monkeypatch, wire)

    result = _describe(ledger, _endpoint(route))

    assert result.text is None
    assert result.outcome == outcome
    assert len(wire.calls) == 1


def test_explicit_vision_path_bypasses_egress_when_local_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    monkeypatch.setattr(vision, "_describe_local", lambda *_: "Local description.")

    attempt = vision.describe_image_result_with_explicit_egress(
        _ingress(),
        ledger=ledger,
        endpoint=_endpoint(route),
    )

    assert attempt == vision.ExplicitVisionResult(
        description=vision.VisionDescription(
            text="Local description.",
            backend="local-ollama",
            processing_location="local-only",
            cloud_egress="denied",
        )
    )
    assert attempt.remote_attempt is None
    assert authority.requests == []


def test_explicit_vision_path_reports_consented_not_observed_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    authority.queue(True)
    endpoint = _endpoint(route)
    wire = WireRecorder()
    _install_wire(monkeypatch, wire)
    monkeypatch.setattr(vision, "_describe_local", lambda *_: None)

    attempt = vision.describe_image_result_with_explicit_egress(
        _ingress(),
        ledger=ledger,
        endpoint=endpoint,
    )

    result = attempt.description
    assert result is not None
    assert result.text == "A grounded private description."
    assert (
        result.backend
        == "consented-route:provider-a/vision-deployment-a/acme/private-vision-v2"
    )
    assert result.processing_location == "consented-route-declared:us-west-2"
    assert result.cloud_egress == "creator-approved"
    assert result.egress_route == endpoint.attestation
    assert result.egress_attempt is not None
    assert attempt.remote_attempt is not None
    assert attempt.remote_attempt.outcome == "described"
    assert attempt.remote_attempt.attempt == result.egress_attempt
    assert "A grounded private description" not in repr(attempt.remote_attempt)
    assert "text" not in asdict(attempt.remote_attempt)


def test_explicit_vision_preserves_nondefault_processing_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route(processing_location="eu-central-1")
    ledger, authority = _ledger(tmp_path, route=route)
    authority.queue(True)
    endpoint = _endpoint(route)
    _install_wire(monkeypatch, WireRecorder())
    monkeypatch.setattr(vision, "_describe_local", lambda *_: None)

    attempt = vision.describe_image_result_with_explicit_egress(
        _ingress(),
        ledger=ledger,
        endpoint=endpoint,
    )

    assert attempt.description is not None
    assert (
        attempt.description.processing_location
        == "consented-route-declared:eu-central-1"
    )
    assert authority.requests[0].processing_location == "eu-central-1"
    assert attempt.remote_attempt is not None
    assert attempt.remote_attempt.route.processing_location == "eu-central-1"


def test_explicit_vision_failure_keeps_attempt_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = _route()
    ledger, authority = _ledger(tmp_path, route=route)
    authority.queue(True)
    endpoint = _endpoint(route)
    wire = WireRecorder(RuntimeError("provider unavailable"))
    _install_wire(monkeypatch, wire)
    monkeypatch.setattr(vision, "_describe_local", lambda *_: None)

    attempt = vision.describe_image_result_with_explicit_egress(
        _ingress(),
        ledger=ledger,
        endpoint=endpoint,
    )

    assert attempt.description is None
    assert attempt.remote_attempt is not None
    assert attempt.remote_attempt.outcome == "provider_error"
    assert attempt.remote_attempt.route == endpoint.attestation
    assert attempt.remote_attempt.attempt.outcome == "authorized_before_outbound"
    assert len(wire.calls) == 1


def test_generic_vision_wrapper_never_enters_explicit_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vision, "_describe_local", lambda *_: None)
    monkeypatch.setattr(
        vision,
        "describe_private_image_with_consent",
        lambda *_args, **_kwargs: pytest.fail("generic wrapper attempted egress"),
    )

    assert vision.describe_image_result(IMAGE_BYTES) is None


def test_code_owned_transport_uses_exact_https_route_body_and_no_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeResponse:
        status = 307

        def read(self, amount: int) -> bytes:
            calls.append({"read": amount})
            return b"redirect rejected"

    class FakeConnection:
        def __init__(
            self,
            host: str,
            *,
            port: int,
            timeout: float,
            context: ssl.SSLContext,
        ) -> None:
            calls.append(
                {
                    "connect": host,
                    "port": port,
                    "timeout": timeout,
                    "tls": context,
                }
            )

        def request(
            self,
            method: str,
            path: str,
            *,
            body: bytes,
            headers: dict[str, str],
        ) -> None:
            calls.append(
                {
                    "method": method,
                    "path": path,
                    "body": body,
                    "headers": headers,
                }
            )

        def getresponse(self) -> FakeResponse:
            calls.append({"getresponse": True})
            return FakeResponse()

        def close(self) -> None:
            calls.append({"close": True})

    monkeypatch.setenv("HTTPS_PROXY", "https://proxy.invalid:4443")
    monkeypatch.setattr(
        perception_egress.http.client,
        "HTTPSConnection",
        FakeConnection,
    )
    route = _route()
    endpoint = _endpoint(route)
    payload = b'{"exact":"body"}'

    response = REAL_POST_EXACT_HTTPS(route, payload, endpoint)

    assert response.status == 307
    assert sum("connect" in item for item in calls) == 1
    request = next(item for item in calls if "method" in item)
    assert request["method"] == "POST"
    assert request["path"] == "/v1/infer"
    assert request["body"] == payload
    headers = request["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer unit-test-credential"
    assert headers["Content-Type"] == "application/json"
    assert calls[-1] == {"close": True}
