"""Pure, transport-neutral governance for sharing artifact metadata.

The service performs no network or filesystem I/O. It never accepts artifact
payloads, credentials, or permanent URLs. House HQ and Discord adapters can
submit the same JSON-compatible descriptors, obtain a one-use execution
descriptor after explicit authorization, and report a bounded provider receipt.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import math
import re
import threading
import time
import uuid


DISCORD_DESCRIPTOR_SCHEMA = "alpecca.share-artifact.discord-attachment.v1"
PROPOSAL_DESCRIPTOR_SCHEMA = "alpecca.share-artifact.publication-proposal.v1"
AUTHORIZATION_SCHEMA = "alpecca.share-artifact.execution-authorization.v1"
EXECUTION_SCHEMA = "alpecca.share-artifact.execution.v1"
PROVIDER_RECEIPT_SCHEMA = "alpecca.share-artifact.provider-receipt.v1"
RECORD_SCHEMA = "alpecca.share-artifact.record.v1"
RECEIPT_SCHEMA = "alpecca.share-artifact.governance-receipt.v1"
STATUS_SCHEMA = "alpecca.share-artifact.status.v1"

MAX_RECORDS = 256
MAX_TTL_SECONDS = 24 * 60 * 60
MAX_TEXT_LENGTH = 512

PROVIDERS = ("discord", "google-drive", "r2")
CLASSIFICATIONS = ("public", "shared", "private", "restricted")
PROVIDER_PERMISSIONS = {
    "discord": frozenset({"attach"}),
    "google-drive": frozenset({"viewer", "commenter", "editor"}),
    "r2": frozenset({"private-object", "public-read"}),
}
TERMINAL_STATES = frozenset({"published", "failed", "cancelled", "expired"})

_DESCRIPTOR_FIELDS = frozenset(
    {
        "schema",
        "record_id",
        "digest",
        "owner",
        "classification",
        "destination",
        "recipient",
        "permission",
        "expiry",
        "provider",
    }
)
_AUTHORIZATION_FIELDS = frozenset(
    {
        "schema",
        "authorization_id",
        "record_id",
        "digest",
        "owner",
        "classification",
        "destination",
        "recipient",
        "permission",
        "expiry",
        "provider",
        "authorized_at",
        "authorized_by",
        "decision",
    }
)
_PROVIDER_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "receipt_id",
        "record_id",
        "digest",
        "provider",
        "outcome",
        "observed_at",
    }
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PERMANENT_URL_RE = re.compile(r"(?:^[a-z][a-z0-9+.-]*://|\bwww\.)", re.IGNORECASE)


class ArtifactShareError(ValueError):
    """A bounded governance error suitable for adapter handling."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _mapping(value: object, *, code: str, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ArtifactShareError(code, f"{name} must be an object")
    return value


def _exact_fields(value: Mapping[str, object], fields: frozenset[str], *, name: str) -> None:
    if set(value) != fields:
        raise ArtifactShareError("invalid_descriptor", f"{name} fields are invalid")


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ArtifactShareError("invalid_descriptor", f"{name} is invalid")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ArtifactShareError("invalid_descriptor", "digest must be lowercase SHA-256 metadata")
    return value


def _bounded_text(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise ArtifactShareError("invalid_descriptor", f"{name} must be text")
    clean = " ".join(value.split())
    if not clean or len(clean) > MAX_TEXT_LENGTH or _PERMANENT_URL_RE.search(clean):
        raise ArtifactShareError("invalid_descriptor", f"{name} is invalid")
    return clean


def _timestamp(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactShareError("invalid_descriptor", f"{name} must be a finite timestamp")
    stamp = float(value)
    if not math.isfinite(stamp) or stamp < 0.0:
        raise ArtifactShareError("invalid_descriptor", f"{name} must be a finite timestamp")
    return stamp


def _receipt_id(factory: Callable[[], str]) -> str:
    return _identifier(factory(), name="receipt id")


def _descriptor(value: object, *, now: float) -> dict[str, object]:
    source = _mapping(value, code="invalid_descriptor", name="descriptor")
    _exact_fields(source, _DESCRIPTOR_FIELDS, name="descriptor")
    schema = source.get("schema")
    provider = source.get("provider")
    if schema == DISCORD_DESCRIPTOR_SCHEMA:
        expected_provider = "discord"
        kind = "discord-attachment"
    elif schema == PROPOSAL_DESCRIPTOR_SCHEMA:
        expected_provider = provider if provider in {"google-drive", "r2"} else None
        kind = "publication-proposal"
    else:
        raise ArtifactShareError("invalid_descriptor", "descriptor schema is unsupported")
    if provider != expected_provider:
        raise ArtifactShareError("invalid_descriptor", "provider does not match descriptor schema")

    classification = source.get("classification")
    if classification not in CLASSIFICATIONS:
        raise ArtifactShareError("invalid_descriptor", "classification is unsupported")
    permission = source.get("permission")
    if permission not in PROVIDER_PERMISSIONS[str(provider)]:
        raise ArtifactShareError("invalid_descriptor", "permission is unsupported for provider")
    recipient = _bounded_text(source.get("recipient"), name="recipient")
    if classification in {"private", "restricted"} and (
        permission == "public-read" or recipient.casefold() in {"public", "anyone"}
    ):
        raise ArtifactShareError(
            "classification_conflict", "private or restricted artifacts cannot be public"
        )
    expiry = _timestamp(source.get("expiry"), name="expiry")
    if expiry <= now or expiry - now > MAX_TTL_SECONDS:
        raise ArtifactShareError("invalid_expiry", "expiry must be future and bounded")
    return {
        "schema": str(schema),
        "kind": kind,
        "record_id": _identifier(source.get("record_id"), name="record id"),
        "digest": _digest(source.get("digest")),
        "owner": _bounded_text(source.get("owner"), name="owner"),
        "classification": str(classification),
        "destination": _bounded_text(source.get("destination"), name="destination"),
        "recipient": recipient,
        "permission": str(permission),
        "expiry": expiry,
        "provider": str(provider),
    }


class ArtifactShareService:
    """In-memory, metadata-only publication governance state machine."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        receipt_id_factory: Callable[[], str] | None = None,
        max_records: int = MAX_RECORDS,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if receipt_id_factory is not None and not callable(receipt_id_factory):
            raise TypeError("receipt_id_factory must be callable")
        if isinstance(max_records, bool) or not isinstance(max_records, int) or not 1 <= max_records <= MAX_RECORDS:
            raise ValueError(f"max_records must be from 1 to {MAX_RECORDS}")
        self._clock = clock
        self._receipt_id_factory = receipt_id_factory or (lambda: "receipt:" + uuid.uuid4().hex)
        self._max_records = max_records
        self._records: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()

    def _now(self) -> float:
        return _timestamp(self._clock(), name="current time")

    def _governance_receipt(
        self, record: Mapping[str, object], state: str, at: float
    ) -> dict[str, object]:
        return {
            "schema": RECEIPT_SCHEMA,
            "receipt_id": _receipt_id(self._receipt_id_factory),
            "record_id": record["record_id"],
            "digest": record["digest"],
            "provider": record["provider"],
            "state": state,
            "at": at,
        }

    @staticmethod
    def _public(record: Mapping[str, object]) -> dict[str, object]:
        return {
            "schema": RECORD_SCHEMA,
            "record_id": record["record_id"],
            "digest": record["digest"],
            "owner": record["owner"],
            "classification": record["classification"],
            "destination": record["destination"],
            "recipient": record["recipient"],
            "permission": record["permission"],
            "expiry": record["expiry"],
            "provider": record["provider"],
            "state": record["state"],
            "receipt": dict(record["receipt"]),
        }

    def _expire_record(self, record: dict[str, object], now: float) -> None:
        if record["state"] in {"proposed", "authorized"} and now >= record["expiry"]:
            record["state"] = "expired"
            record["receipt"] = self._governance_receipt(record, "expired", now)

    def _record(self, record_id: str, *, now: float) -> dict[str, object]:
        key = _identifier(record_id, name="record id")
        try:
            record = self._records[key]
        except KeyError as exc:
            raise ArtifactShareError("record_not_found", "artifact share record was not found") from exc
        self._expire_record(record, now)
        return record

    def propose(self, descriptor: object) -> dict[str, object]:
        """Register metadata only; payload bytes are outside this API."""

        now = self._now()
        validated = _descriptor(descriptor, now=now)
        with self._lock:
            existing = self._records.get(str(validated["record_id"]))
            if existing is not None:
                comparable = {key: existing[key] for key in validated}
                if comparable != validated:
                    raise ArtifactShareError("record_conflict", "record id is already bound")
                return self._public(existing)
            if len(self._records) >= self._max_records:
                raise ArtifactShareError("record_limit", "artifact share record limit reached")
            record = {
                **validated,
                "state": "proposed",
                "authorization": None,
                "receipt": {},
            }
            record["receipt"] = self._governance_receipt(record, "proposed", now)
            self._records[str(record["record_id"])] = record
            return self._public(record)

    def authorize_execution(self, record_id: str, authorization: object) -> dict[str, object]:
        """Bind an explicit, one-use external-publication authorization."""

        now = self._now()
        source = _mapping(
            authorization, code="invalid_authorization", name="execution authorization"
        )
        if set(source) != _AUTHORIZATION_FIELDS:
            raise ArtifactShareError("invalid_authorization", "authorization fields are invalid")
        if source.get("schema") != AUTHORIZATION_SCHEMA:
            raise ArtifactShareError("invalid_authorization", "authorization schema is unsupported")
        if source.get("decision") != "authorize-external-publication":
            raise ArtifactShareError("authorization_required", "external publication was not authorized")

        with self._lock:
            record = self._record(record_id, now=now)
            if record["state"] == "expired":
                raise ArtifactShareError("record_expired", "artifact share record expired")
            if record["state"] != "proposed":
                raise ArtifactShareError("invalid_state", "record is not awaiting authorization")
            for field in (
                "record_id",
                "digest",
                "owner",
                "classification",
                "destination",
                "recipient",
                "permission",
                "expiry",
                "provider",
            ):
                if source.get(field) != record[field]:
                    raise ArtifactShareError(
                        "authorization_binding_mismatch", f"authorization {field} does not match"
                    )
            authorized_at = _timestamp(source.get("authorized_at"), name="authorized_at")
            if authorized_at > now or authorized_at >= record["expiry"]:
                raise ArtifactShareError("invalid_authorization", "authorization time is invalid")
            authorization_id = _identifier(source.get("authorization_id"), name="authorization id")
            authorized_by = _bounded_text(source.get("authorized_by"), name="authorized_by")
            record["authorization"] = {
                "authorization_id": authorization_id,
                "authorized_at": authorized_at,
                "authorized_by": authorized_by,
            }
            record["state"] = "authorized"
            record["receipt"] = self._governance_receipt(record, "authorized", now)
            return self._public(record)

    def begin_execution(self, record_id: str, *, authorization_id: str) -> dict[str, object]:
        """Consume authorization and return metadata for an external adapter."""

        now = self._now()
        supplied_id = _identifier(authorization_id, name="authorization id")
        with self._lock:
            record = self._record(record_id, now=now)
            if record["state"] == "expired":
                raise ArtifactShareError("record_expired", "artifact share record expired")
            if record["state"] != "authorized":
                raise ArtifactShareError("authorization_required", "execution is not authorized")
            authorization = record["authorization"]
            if not isinstance(authorization, Mapping) or authorization.get("authorization_id") != supplied_id:
                raise ArtifactShareError(
                    "authorization_binding_mismatch", "authorization id does not match"
                )
            record["state"] = "executing"
            record["receipt"] = self._governance_receipt(record, "executing", now)
            return {
                "schema": EXECUTION_SCHEMA,
                "record_id": record["record_id"],
                "digest": record["digest"],
                "owner": record["owner"],
                "classification": record["classification"],
                "destination": record["destination"],
                "recipient": record["recipient"],
                "permission": record["permission"],
                "expiry": record["expiry"],
                "provider": record["provider"],
                "authorization_id": supplied_id,
            }

    def record_outcome(self, record_id: str, provider_receipt: object) -> dict[str, object]:
        """Record an adapter result; this method itself performs no publication."""

        now = self._now()
        source = _mapping(provider_receipt, code="invalid_receipt", name="provider receipt")
        if set(source) != _PROVIDER_RECEIPT_FIELDS:
            raise ArtifactShareError("invalid_receipt", "provider receipt fields are invalid")
        if source.get("schema") != PROVIDER_RECEIPT_SCHEMA:
            raise ArtifactShareError("invalid_receipt", "provider receipt schema is unsupported")
        outcome = source.get("outcome")
        if outcome not in {"published", "failed"}:
            raise ArtifactShareError("invalid_receipt", "provider receipt outcome is invalid")

        with self._lock:
            record = self._record(record_id, now=now)
            if record["state"] != "executing":
                raise ArtifactShareError("invalid_state", "record has not begun execution")
            for field in ("record_id", "digest", "provider"):
                if source.get(field) != record[field]:
                    raise ArtifactShareError(
                        "receipt_binding_mismatch", f"provider receipt {field} does not match"
                    )
            observed_at = _timestamp(source.get("observed_at"), name="observed_at")
            if observed_at > now:
                raise ArtifactShareError("invalid_receipt", "provider receipt time is invalid")
            provider_receipt_id = _identifier(source.get("receipt_id"), name="provider receipt id")
            record["state"] = str(outcome)
            receipt = self._governance_receipt(record, str(outcome), now)
            receipt["provider_receipt_id"] = provider_receipt_id
            receipt["provider_observed_at"] = observed_at
            record["receipt"] = receipt
            return self._public(record)

    def cancel(self, record_id: str) -> dict[str, object]:
        now = self._now()
        with self._lock:
            record = self._record(record_id, now=now)
            if record["state"] not in {"proposed", "authorized"}:
                raise ArtifactShareError("invalid_state", "record cannot be cancelled")
            record["state"] = "cancelled"
            record["receipt"] = self._governance_receipt(record, "cancelled", now)
            return self._public(record)

    def get(self, record_id: str) -> dict[str, object]:
        now = self._now()
        with self._lock:
            return self._public(self._record(record_id, now=now))

    def list_records(self) -> list[dict[str, object]]:
        now = self._now()
        with self._lock:
            for record in self._records.values():
                self._expire_record(record, now)
            return [self._public(self._records[key]) for key in sorted(self._records)]

    def status_snapshot(self) -> dict[str, object]:
        records = self.list_records()
        counts = {
            state: sum(record["state"] == state for record in records)
            for state in (
                "proposed",
                "authorized",
                "executing",
                "published",
                "failed",
                "cancelled",
                "expired",
            )
        }
        return {
            "schema": STATUS_SCHEMA,
            "network_egress": False,
            "stores_raw_payloads": False,
            "stores_permanent_urls": False,
            "record_count": len(records),
            "states": counts,
            "providers": list(PROVIDERS),
        }


__all__ = [
    "AUTHORIZATION_SCHEMA",
    "DISCORD_DESCRIPTOR_SCHEMA",
    "EXECUTION_SCHEMA",
    "MAX_RECORDS",
    "MAX_TTL_SECONDS",
    "PROPOSAL_DESCRIPTOR_SCHEMA",
    "PROVIDER_RECEIPT_SCHEMA",
    "RECORD_SCHEMA",
    "STATUS_SCHEMA",
    "ArtifactShareError",
    "ArtifactShareService",
]
