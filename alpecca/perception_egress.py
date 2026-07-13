"""Fail-closed private perception dispatch through exact creator consent.

Provider code is not called before consent and does not own the transport.
Alpecca deterministically serializes one supported request format, binds those
exact bytes to the consent ledger, consumes a one-use grant, and performs one
direct HTTPS request.  The transport ignores environment proxies, does not
retry, does not follow redirects, verifies TLS, and sends the bound body
without further transformation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import secrets
import ssl
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import urlsplit

from alpecca.attachment_ingress import ImageIngress
from alpecca.attachment_perception import AttachmentPerceptionEnvelope
from alpecca.egress_consent import (
    AllowedEgressRoute,
    EgressConsentDenied,
    EgressConsentIntegrityError,
    EgressConsentLedger,
)
from alpecca.source_perception import parse_image_header


_IMAGE_CAPABILITY = "private-image-description"
_PAYLOAD_SCHEMA = "alpecca.private-image-egress.v1"
_MAX_PROVIDER_TEXT_CHARS = 8_000
_MAX_PROVIDER_RESPONSE_BYTES = 1024 * 1024


class PerceptionEgressDenied(EgressConsentDenied):
    """The explicit private-perception path was not safe to dispatch."""


class BearerCredential:
    """In-memory credential wrapper with redacted string/deep-copy surfaces."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 8_192
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("invalid bearer token")
        object.__setattr__(self, "_BearerCredential__value", value)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("BearerCredential is immutable")

    def __repr__(self) -> str:
        return "BearerCredential(<redacted>)"

    __str__ = __repr__

    def __deepcopy__(self, _memo: dict[int, object]) -> "BearerCredential":
        return self

    def authorization_header(self) -> str:
        return f"Bearer {self.__value}"


@dataclass(frozen=True, slots=True)
class ProviderAttestation:
    """Consented route identity, not proof of the provider's runtime location."""

    route_id: str
    provider: str
    deployment: str
    model: str
    capability: str
    purpose: str
    processing_location: str
    destination_class: str
    transport_route: str

    @classmethod
    def from_route(cls, route: AllowedEgressRoute) -> "ProviderAttestation":
        return cls(
            route_id=route.route_id,
            provider=route.provider,
            deployment=route.deployment,
            model=route.model,
            capability=route.capability,
            purpose=route.purpose,
            processing_location=route.processing_location,
            destination_class=route.destination_class,
            transport_route=route.transport_route,
        )

    def matches(self, route: AllowedEgressRoute) -> bool:
        return self == ProviderAttestation.from_route(route)


@dataclass(frozen=True, slots=True)
class PrivateImageEndpoint:
    """Immutable inputs for Alpecca's code-owned OpenAI-compatible transport."""

    attestation: ProviderAttestation
    credential: Optional[BearerCredential] = field(
        default=None,
        repr=False,
        compare=False,
    )
    timeout_seconds: float = 45.0
    max_output_tokens: int = 384

    def __post_init__(self) -> None:
        if type(self.attestation) is not ProviderAttestation:
            raise TypeError("attestation must be ProviderAttestation")
        if (
            self.credential is not None
            and type(self.credential) is not BearerCredential
        ):
            raise TypeError("credential must be BearerCredential")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 1 <= float(self.timeout_seconds) <= 120
        ):
            raise ValueError("timeout_seconds must be between 1 and 120")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or not 1 <= self.max_output_tokens <= 2_048
        ):
            raise ValueError("max_output_tokens must be between 1 and 2048")


class PrivateImagePromptProfile(Enum):
    """Finite code-owned prompts allowed to accompany private image bytes."""

    DESCRIBE_V1 = (
        "private-image-description-v1",
        "private-image-egress",
        "describe-private-image",
        "Describe this image in two or three sentences, plainly and concretely: "
        "what it shows, any visible text worth knowing, and the overall feel.",
    )

    @property
    def profile_id(self) -> str:
        return self.value[0]

    @property
    def ingress_scope(self) -> str:
        return self.value[1]

    @property
    def route_purpose(self) -> str:
        return self.value[2]

    @property
    def prompt(self) -> str:
        return self.value[3]


@dataclass(frozen=True, slots=True)
class EgressAttemptEvidence:
    """Content-free proof that consent was consumed before outbound I/O."""

    attempt_id: str
    order: int
    attempt_ordinal: int
    consent_id: str
    byte_count: int
    authorized_at: float
    outcome: str


@dataclass(frozen=True, slots=True)
class PrivateImageDescriptionResult:
    """One attempted provider description and its immutable audit evidence."""

    text: Optional[str]
    route: ProviderAttestation
    attempt: EgressAttemptEvidence
    outcome: str


@dataclass(frozen=True, slots=True)
class ProviderWireResponse:
    """Bounded response from the single code-owned HTTPS request."""

    status: int
    body: bytes
    too_large: bool = False


def _serialize_image_request(
    image_bytes: bytes,
    mime_type: str,
    profile: PrivateImagePromptProfile,
    endpoint: PrivateImageEndpoint,
) -> bytes:
    """Create the sole supported provider body with no provider callback."""

    encoded = base64.b64encode(image_bytes).decode("ascii")
    request = {
        "max_tokens": endpoint.max_output_tokens,
        "messages": [
            {
                "content": [
                    {"text": profile.prompt, "type": "text"},
                    {
                        "image_url": {
                            "url": f"data:{mime_type};base64,{encoded}",
                        },
                        "type": "image_url",
                    },
                ],
                "role": "user",
            }
        ],
        "model": endpoint.attestation.model,
        "stream": False,
    }
    return json.dumps(
        request,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _payload_metadata(
    payload: bytes,
    ingress: ImageIngress,
    profile: PrivateImagePromptProfile,
) -> bytes:
    """Describe exact body bytes without retaining private image or prompt data."""

    envelope = ingress.envelope
    return json.dumps(
        {
            "body_sha256": hashlib.sha256(payload).hexdigest(),
            "height": envelope.height,
            "image_sha256": envelope.sha256,
            "kind": "serialized-private-image-request",
            "mime_type": envelope.mime_type,
            "prompt_profile": profile.profile_id,
            "schema": _PAYLOAD_SCHEMA,
            "scope": envelope.scope,
            "source": envelope.source,
            "width": envelope.width,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _validated_ingress(
    ingress: ImageIngress,
    profile: PrivateImagePromptProfile,
) -> tuple[bytes, str]:
    if type(ingress) is not ImageIngress:
        raise TypeError("ingress must be ImageIngress")
    if type(profile) is not PrivateImagePromptProfile:
        raise TypeError("profile must be PrivateImagePromptProfile")
    image_bytes = ingress.image_bytes
    envelope = ingress.envelope
    if type(envelope) is not AttachmentPerceptionEnvelope:
        raise TypeError("ingress envelope must be AttachmentPerceptionEnvelope")
    if type(image_bytes) is not bytes or not image_bytes:
        raise PerceptionEgressDenied("invalid_image_payload")
    if (
        envelope.attachment_type != "image"
        or envelope.scope != profile.ingress_scope
        or envelope.processing_location != "local-only"
        or envelope.cloud_egress != "denied"
    ):
        raise PerceptionEgressDenied("image_ingress_scope_mismatch")
    digest = hashlib.sha256(image_bytes).hexdigest()
    if not hmac.compare_digest(digest, envelope.sha256):
        raise PerceptionEgressDenied("image_ingress_digest_mismatch")
    if envelope.size_bytes != len(image_bytes):
        raise PerceptionEgressDenied("image_ingress_size_mismatch")
    header = parse_image_header(image_bytes)
    if (
        header is None
        or header.mime_type != envelope.mime_type
        or header.width != envelope.width
        or header.height != envelope.height
    ):
        raise PerceptionEgressDenied("image_ingress_metadata_mismatch")
    return image_bytes, envelope.mime_type


def _post_exact_https(
    route: AllowedEgressRoute,
    payload: bytes,
    endpoint: PrivateImageEndpoint,
) -> ProviderWireResponse:
    """Perform exactly one direct TLS request to the consented route."""

    parsed = urlsplit(route.transport_route)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise PerceptionEgressDenied("invalid_transport_route")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Alpecca-private-perception/1",
    }
    if endpoint.credential is not None:
        headers["Authorization"] = endpoint.credential.authorization_header()

    connection = http.client.HTTPSConnection(
        parsed.hostname,
        port=parsed.port or 443,
        timeout=float(endpoint.timeout_seconds),
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "POST",
            parsed.path or "/",
            body=payload,
            headers=headers,
        )
        response = connection.getresponse()
        body = response.read(_MAX_PROVIDER_RESPONSE_BYTES + 1)
        too_large = len(body) > _MAX_PROVIDER_RESPONSE_BYTES
        return ProviderWireResponse(
            status=int(response.status),
            body=(b"" if too_large else body),
            too_large=too_large,
        )
    finally:
        connection.close()


def _response_text(body: bytes) -> Optional[str]:
    try:
        decoded = json.loads(body.decode("utf-8"))
        choices = decoded["choices"]
        message = choices[0]["message"]
        content = message["content"]
    except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        pieces = [
            str(part.get("text", "")).strip()
            for part in content
            if isinstance(part, dict) and part.get("type") in {None, "text"}
        ]
        text = " ".join(piece for piece in pieces if piece).strip()
    else:
        return None
    return text or None


def _attempt_evidence(consumed: dict[str, object]) -> EgressAttemptEvidence:
    raw = consumed.get("attempt_evidence")
    if not isinstance(raw, dict):
        raise EgressConsentIntegrityError("invalid_attempt_evidence")
    try:
        evidence = EgressAttemptEvidence(
            attempt_id=str(raw["attempt_id"]),
            order=int(raw["order"]),
            attempt_ordinal=int(raw["attempt_ordinal"]),
            consent_id=str(raw["consent_id"]),
            byte_count=int(raw["byte_count"]),
            authorized_at=float(raw["authorized_at"]),
            outcome=str(raw["outcome"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EgressConsentIntegrityError("invalid_attempt_evidence") from exc
    if (
        not evidence.attempt_id
        or not evidence.consent_id
        or evidence.order < 1
        or evidence.attempt_ordinal < 1
        or evidence.byte_count < 1
        or evidence.outcome != "authorized_before_outbound"
    ):
        raise EgressConsentIntegrityError("invalid_attempt_evidence")
    return evidence


def describe_private_image_with_consent(
    ingress: ImageIngress,
    *,
    ledger: EgressConsentLedger,
    endpoint: PrivateImageEndpoint,
    profile: PrivateImagePromptProfile = PrivateImagePromptProfile.DESCRIBE_V1,
) -> PrivateImageDescriptionResult:
    """Attempt one exact, creator-approved private image description.

    The operation identifier is minted internally and the route comes only
    from the injected immutable endpoint.  Every invocation requires a fresh
    creator decision; no retry or alternate provider is attempted.
    """

    if type(ledger) is not EgressConsentLedger:
        raise TypeError("ledger must be EgressConsentLedger")
    if type(endpoint) is not PrivateImageEndpoint:
        raise TypeError("endpoint must be PrivateImageEndpoint")
    image_bytes, mime_type = _validated_ingress(ingress, profile)

    attestation = endpoint.attestation
    route = ledger.policy.resolve(attestation.route_id)
    if route.capability != _IMAGE_CAPABILITY:
        raise PerceptionEgressDenied("route_capability_mismatch")
    if route.purpose != profile.route_purpose:
        raise PerceptionEgressDenied("route_purpose_mismatch")
    if not attestation.matches(route):
        raise PerceptionEgressDenied("provider_route_mismatch")
    if route.max_uses != 1:
        raise PerceptionEgressDenied("provider_route_must_be_one_shot")

    payload = _serialize_image_request(image_bytes, mime_type, profile, endpoint)
    if not payload or len(payload) > route.max_bytes_per_use:
        raise PerceptionEgressDenied("provider_payload_too_large")
    metadata = _payload_metadata(payload, ingress, profile)
    operation_id = "op_" + secrets.token_urlsafe(24)
    if ledger.request_consent(
        operation_id=operation_id,
        route_id=route.route_id,
        payload_metadata=metadata,
        byte_count=len(payload),
    ).get("granted") is not True:
        raise PerceptionEgressDenied("creator_denied")

    consumed = ledger.consume_active(
        operation_id=operation_id,
        route_id=route.route_id,
        payload_metadata=metadata,
        byte_count=len(payload),
    )
    try:
        wire = _post_exact_https(route, payload, endpoint)
    except Exception:
        wire = None
        text = None
        outcome = "provider_error"
    else:
        text = None
        if wire.too_large:
            outcome = "response_too_large"
        elif 300 <= wire.status < 400:
            outcome = "provider_redirect_rejected"
        elif not 200 <= wire.status < 300:
            outcome = "provider_http_error"
        else:
            text = _response_text(wire.body)
            if text is None:
                outcome = "invalid_response"
            elif len(text) > _MAX_PROVIDER_TEXT_CHARS:
                text = None
                outcome = "response_too_large"
            else:
                outcome = "described"

    return PrivateImageDescriptionResult(
        text=text,
        route=attestation,
        attempt=_attempt_evidence(consumed),
        outcome=outcome,
    )


__all__ = [
    "BearerCredential",
    "EgressAttemptEvidence",
    "PerceptionEgressDenied",
    "PrivateImageDescriptionResult",
    "PrivateImageEndpoint",
    "PrivateImagePromptProfile",
    "ProviderAttestation",
    "ProviderWireResponse",
    "describe_private_image_with_consent",
]
