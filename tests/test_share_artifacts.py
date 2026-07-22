from __future__ import annotations

import copy
import inspect

import pytest

from alpecca import share_artifacts


DIGEST = "a" * 64


class Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def service(clock):
    ids = iter(f"receipt:{index}" for index in range(100))
    return share_artifacts.ArtifactShareService(
        clock=clock, receipt_id_factory=lambda: next(ids)
    )


def _descriptor(
    provider: str = "discord",
    *,
    record_id: str = "share:one",
    classification: str = "shared",
    recipient: str = "discord-channel:42",
    permission: str | None = None,
    expiry: float = 1_600.0,
) -> dict[str, object]:
    permissions = {
        "discord": "attach",
        "google-drive": "viewer",
        "r2": "private-object",
    }
    return {
        "schema": (
            share_artifacts.DISCORD_DESCRIPTOR_SCHEMA
            if provider == "discord"
            else share_artifacts.PROPOSAL_DESCRIPTOR_SCHEMA
        ),
        "record_id": record_id,
        "digest": DIGEST,
        "owner": "creatorjd",
        "classification": classification,
        "destination": {
            "discord": "channel:42",
            "google-drive": "folder:artifacts",
            "r2": "bucket:artifacts/object:one",
        }[provider],
        "recipient": recipient,
        "permission": permission or permissions[provider],
        "expiry": expiry,
        "provider": provider,
    }


def _authorization(descriptor: dict[str, object], *, now: float = 1_000.0) -> dict[str, object]:
    return {
        "schema": share_artifacts.AUTHORIZATION_SCHEMA,
        "authorization_id": "authorization:one",
        "record_id": descriptor["record_id"],
        "digest": descriptor["digest"],
        "owner": descriptor["owner"],
        "classification": descriptor["classification"],
        "destination": descriptor["destination"],
        "recipient": descriptor["recipient"],
        "permission": descriptor["permission"],
        "expiry": descriptor["expiry"],
        "provider": descriptor["provider"],
        "authorized_at": now,
        "authorized_by": "creatorjd",
        "decision": "authorize-external-publication",
    }


def _provider_receipt(
    descriptor: dict[str, object], *, outcome: str = "published"
) -> dict[str, object]:
    return {
        "schema": share_artifacts.PROVIDER_RECEIPT_SCHEMA,
        "receipt_id": "provider-receipt:one",
        "record_id": descriptor["record_id"],
        "digest": descriptor["digest"],
        "provider": descriptor["provider"],
        "outcome": outcome,
        "observed_at": 1_000.0,
    }


def test_discord_attachment_proposal_is_metadata_only(service):
    descriptor = _descriptor()

    record = service.propose(descriptor)

    assert record == {
        "schema": share_artifacts.RECORD_SCHEMA,
        "record_id": "share:one",
        "digest": DIGEST,
        "owner": "creatorjd",
        "classification": "shared",
        "destination": "channel:42",
        "recipient": "discord-channel:42",
        "permission": "attach",
        "expiry": 1_600.0,
        "provider": "discord",
        "state": "proposed",
        "receipt": {
            "schema": "alpecca.share-artifact.governance-receipt.v1",
            "receipt_id": "receipt:0",
            "record_id": "share:one",
            "digest": DIGEST,
            "provider": "discord",
            "state": "proposed",
            "at": 1_000.0,
        },
    }
    assert descriptor == _descriptor()


@pytest.mark.parametrize(
    "provider,permission",
    [("google-drive", "viewer"), ("r2", "private-object")],
)
def test_external_proposal_descriptors_share_the_same_record_contract(
    service, provider, permission
):
    record = service.propose(
        _descriptor(
            provider,
            record_id=f"share:{provider}",
            recipient="creatorjd",
            permission=permission,
        )
    )

    assert record["provider"] == provider
    assert record["permission"] == permission
    assert record["state"] == "proposed"
    assert set(record) == {
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
        "state",
        "receipt",
    }


@pytest.mark.parametrize("field", ["payload", "content", "bytes", "token", "secret", "url"])
def test_descriptor_rejects_payload_secret_and_url_fields(service, field):
    descriptor = _descriptor()
    descriptor[field] = "must-not-be-stored"

    with pytest.raises(share_artifacts.ArtifactShareError) as caught:
        service.propose(descriptor)

    assert caught.value.code == "invalid_descriptor"


@pytest.mark.parametrize("field", ["destination", "recipient", "owner"])
def test_descriptor_rejects_permanent_urls_in_metadata(service, field):
    descriptor = _descriptor()
    descriptor[field] = "https://example.invalid/permanent/object"

    with pytest.raises(share_artifacts.ArtifactShareError) as caught:
        service.propose(descriptor)

    assert caught.value.code == "invalid_descriptor"


def test_execution_requires_explicit_exact_authorization(service):
    descriptor = _descriptor()
    service.propose(descriptor)

    with pytest.raises(share_artifacts.ArtifactShareError) as missing:
        service.begin_execution("share:one", authorization_id="authorization:one")

    changed = _authorization(descriptor)
    changed["recipient"] = "someone-else"
    with pytest.raises(share_artifacts.ArtifactShareError) as mismatched:
        service.authorize_execution("share:one", changed)

    assert missing.value.code == "authorization_required"
    assert mismatched.value.code == "authorization_binding_mismatch"
    assert service.get("share:one")["state"] == "proposed"


def test_explicit_authorization_is_one_use_and_returns_no_payload_or_url(service):
    descriptor = _descriptor()
    service.propose(descriptor)
    authorized = service.authorize_execution("share:one", _authorization(descriptor))

    execution = service.begin_execution(
        "share:one", authorization_id="authorization:one"
    )

    assert authorized["state"] == "authorized"
    assert execution == {
        "schema": share_artifacts.EXECUTION_SCHEMA,
        "record_id": "share:one",
        "digest": DIGEST,
        "owner": "creatorjd",
        "classification": "shared",
        "destination": "channel:42",
        "recipient": "discord-channel:42",
        "permission": "attach",
        "expiry": 1_600.0,
        "provider": "discord",
        "authorization_id": "authorization:one",
    }
    assert not any(key in execution for key in ("payload", "content", "bytes", "url", "secret"))
    with pytest.raises(share_artifacts.ArtifactShareError) as replay:
        service.begin_execution("share:one", authorization_id="authorization:one")
    assert replay.value.code == "authorization_required"


@pytest.mark.parametrize("outcome", ["published", "failed"])
def test_provider_outcome_requires_execution_and_produces_bounded_receipt(service, outcome):
    descriptor = _descriptor()
    service.propose(descriptor)
    service.authorize_execution("share:one", _authorization(descriptor))
    service.begin_execution("share:one", authorization_id="authorization:one")

    record = service.record_outcome(
        "share:one", _provider_receipt(descriptor, outcome=outcome)
    )

    assert record["state"] == outcome
    assert record["receipt"]["state"] == outcome
    assert record["receipt"]["provider_receipt_id"] == "provider-receipt:one"
    assert "url" not in record["receipt"]
    assert "payload" not in record["receipt"]


def test_provider_receipt_cannot_be_recorded_before_authorized_execution(service):
    descriptor = _descriptor()
    service.propose(descriptor)

    with pytest.raises(share_artifacts.ArtifactShareError) as caught:
        service.record_outcome("share:one", _provider_receipt(descriptor))

    assert caught.value.code == "invalid_state"


def test_provider_receipt_must_match_record_digest_and_provider(service):
    descriptor = _descriptor()
    service.propose(descriptor)
    service.authorize_execution("share:one", _authorization(descriptor))
    service.begin_execution("share:one", authorization_id="authorization:one")
    receipt = _provider_receipt(descriptor)
    receipt["digest"] = "b" * 64

    with pytest.raises(share_artifacts.ArtifactShareError) as caught:
        service.record_outcome("share:one", receipt)

    assert caught.value.code == "receipt_binding_mismatch"


def test_expiry_fails_closed_before_authorization_or_execution(service, clock):
    descriptor = _descriptor(expiry=1_001.0)
    service.propose(descriptor)
    clock.now = 1_001.0

    assert service.get("share:one")["state"] == "expired"
    with pytest.raises(share_artifacts.ArtifactShareError) as caught:
        service.authorize_execution("share:one", _authorization(descriptor))
    assert caught.value.code == "record_expired"


def test_private_and_restricted_artifacts_cannot_request_public_access(service):
    descriptor = _descriptor(
        "r2",
        classification="restricted",
        recipient="public",
        permission="public-read",
    )

    with pytest.raises(share_artifacts.ArtifactShareError) as caught:
        service.propose(descriptor)

    assert caught.value.code == "classification_conflict"


def test_provider_permissions_and_descriptor_schemas_are_exact(service):
    drive = _descriptor("google-drive", recipient="creatorjd", permission="attach")
    discord = _descriptor()
    discord["schema"] = share_artifacts.PROPOSAL_DESCRIPTOR_SCHEMA

    with pytest.raises(share_artifacts.ArtifactShareError):
        service.propose(drive)
    with pytest.raises(share_artifacts.ArtifactShareError):
        service.propose(discord)


def test_idempotent_proposal_does_not_duplicate_or_replace_receipt(service):
    descriptor = _descriptor()
    first = service.propose(descriptor)
    second = service.propose(copy.deepcopy(descriptor))

    assert second == first
    assert service.status_snapshot()["record_count"] == 1


def test_records_are_sorted_and_status_is_provider_neutral(service):
    service.propose(_descriptor(record_id="share:z"))
    service.propose(
        _descriptor("r2", record_id="share:a", recipient="creatorjd")
    )

    assert [record["record_id"] for record in service.list_records()] == ["share:a", "share:z"]
    assert service.status_snapshot() == {
        "schema": share_artifacts.STATUS_SCHEMA,
        "network_egress": False,
        "stores_raw_payloads": False,
        "stores_permanent_urls": False,
        "record_count": 2,
        "states": {
            "proposed": 2,
            "authorized": 0,
            "executing": 0,
            "published": 0,
            "failed": 0,
            "cancelled": 0,
            "expired": 0,
        },
        "providers": ["discord", "google-drive", "r2"],
    }


def test_module_has_no_network_provider_or_secret_dependencies():
    source = inspect.getsource(share_artifacts)

    assert "requests" not in source
    assert "urllib" not in source
    assert "boto" not in source
    assert "googleapiclient" not in source
    assert "discord.py" not in source
    assert "os.environ" not in source
