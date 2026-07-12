"""Pure integration contract for the signed Discord actor transport helpers."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from alpecca import bridge_actor_identity as actor_identity
from alpecca import bridge_actor_transport as transport


ROOT = Path(__file__).resolve().parents[1]
SEAL_SECRET = "phase10-transport-dedicated-actor-seal-secret"
BODY = b'{"speaker":"guest","text":"hello"}'


class MultiHeaders:
    def __init__(self, pairs: list[tuple[str, object]]) -> None:
        self._pairs = pairs

    def getlist(self, name: str) -> list[object]:
        folded = name.casefold()
        return [value for key, value in self._pairs if key.casefold() == folded]


def _bindings(**overrides: str | None) -> transport.DiscordActorBindings:
    values: dict[str, str | None] = {
        "event_id": "100000000000000001",
        "actor_id": "200000000000000002",
        "guild_id": None,
        "channel_id": "300000000000000003",
        "thread_id": None,
    }
    values.update(overrides)
    return transport.DiscordActorBindings(**values)  # type: ignore[arg-type]


def _issue_and_verify(
    store: actor_identity.BridgeActorIdentityStore,
    bindings: transport.DiscordActorBindings,
    *,
    body: bytes = BODY,
) -> actor_identity.VerifiedGuestActor:
    envelope = store.issue_envelope(
        request_body=body,
        **bindings.as_store_kwargs(),
    )
    result = store.verify_and_consume(
        envelope.encode(),
        request_body=body,
        **bindings.as_store_kwargs(),
    )
    assert result.accepted is True
    assert result.actor is not None
    return result.actor


def test_public_protocol_constants_and_fixed_store_posture() -> None:
    assert transport.MAX_DISCORD_BODY_BYTES == 6 * 1024 * 1024
    assert transport.EVENT_ID_HEADER == "X-Alpecca-Discord-Event-Id"
    assert transport.ACTOR_ID_HEADER == "X-Alpecca-Discord-Actor-Id"
    assert transport.GUILD_ID_HEADER == "X-Alpecca-Discord-Guild-Id"
    assert transport.CHANNEL_ID_HEADER == "X-Alpecca-Discord-Channel-Id"
    assert transport.THREAD_ID_HEADER == "X-Alpecca-Discord-Thread-Id"
    assert transport.ENVELOPE_HEADER == "X-Alpecca-Discord-Actor-Envelope"

    assert transport.POLICY_VERSION == actor_identity.SUPPORTED_POLICY_VERSION
    assert transport.KEY_VERSION == 1
    assert transport.ENVELOPE_TTL_MS == 30_000
    assert transport.ACTOR_POLICY == actor_identity.BridgeActorPolicy(
        version=actor_identity.SUPPORTED_POLICY_VERSION,
        envelope_ttl_ms=30_000,
        max_body_bytes=6 * 1024 * 1024,
        max_external_id_bytes=32,
        max_transport_bytes=4096,
        max_clock_advance_ms=2_592_000_000,
        max_incremental_audit_rows=64,
    )
    assert transport.ACTOR_BOUNDARY == actor_identity.TrustedBridgeBoundary(
        service="discord-bridge",
        platform="discord",
        boundary_id="server-discord-adapter",
    )
    assert "local-development-only" in transport.SQLITE_ANCHOR_LIMITATION
    assert "share one failure domain" in transport.SQLITE_ANCHOR_LIMITATION


def test_import_is_storage_and_credential_inert(tmp_path: Path) -> None:
    home = tmp_path / "unused-home"
    env = os.environ.copy()
    env["ALPECCA_HOME"] = str(home)
    env["ALPECCA_BRIDGE_ACTOR_IDENTITY_SEAL_SECRET"] = SEAL_SECRET
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from alpecca import bridge_actor_transport as t; "
                "print(t.MAX_DISCORD_BODY_BYTES)"
            ),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == str(6 * 1024 * 1024)
    assert not home.exists()


def test_bindings_emit_exact_required_headers_and_omit_absent_scopes() -> None:
    bindings = _bindings()

    assert bindings.as_headers() == {
        transport.EVENT_ID_HEADER: bindings.event_id,
        transport.ACTOR_ID_HEADER: bindings.actor_id,
        transport.CHANNEL_ID_HEADER: bindings.channel_id,
    }
    assert transport.GUILD_ID_HEADER not in bindings.as_headers()
    assert transport.THREAD_ID_HEADER not in bindings.as_headers()
    assert bindings.as_store_kwargs() == {
        "discord_event_id": bindings.event_id,
        "external_actor_id": bindings.actor_id,
        "guild_id": None,
        "channel_id": bindings.channel_id,
        "thread_id": None,
    }


def test_bindings_emit_present_guild_and_thread_headers() -> None:
    bindings = _bindings(
        guild_id="400000000000000004",
        thread_id="500000000000000005",
    )

    assert bindings.as_headers() == {
        transport.EVENT_ID_HEADER: bindings.event_id,
        transport.ACTOR_ID_HEADER: bindings.actor_id,
        transport.GUILD_ID_HEADER: bindings.guild_id,
        transport.CHANNEL_ID_HEADER: bindings.channel_id,
        transport.THREAD_ID_HEADER: bindings.thread_id,
    }


@pytest.mark.parametrize(
    "bad_id",
    (
        "",
        "0",
        "01",
        " 123",
        "123 ",
        "+123",
        "-123",
        "1.2",
        "actor-123",
        "１２３",
        "18446744073709551616",
        "1" * 21,
        123,
        None,
    ),
)
@pytest.mark.parametrize("field", ("event_id", "actor_id", "channel_id"))
def test_required_bindings_reject_noncanonical_discord_ids(
    field: str,
    bad_id: object,
) -> None:
    values = {
        "event_id": "1",
        "actor_id": "2",
        "channel_id": "3",
        field: bad_id,
    }
    with pytest.raises(transport.DiscordActorHeaderError, match=field):
        transport.DiscordActorBindings(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ("guild_id", "thread_id"))
def test_optional_bindings_accept_only_omission_or_canonical_ids(field: str) -> None:
    assert getattr(_bindings(**{field: None}), field) is None
    assert getattr(_bindings(**{field: "18446744073709551615"}), field) == (
        "18446744073709551615"
    )
    with pytest.raises(transport.DiscordActorHeaderError, match=field):
        _bindings(**{field: ""})


def test_parse_binding_headers_is_case_insensitive_and_round_trips() -> None:
    expected = _bindings(
        guild_id="400000000000000004",
        thread_id="500000000000000005",
    )
    headers = {key.swapcase(): value for key, value in expected.as_headers().items()}

    assert transport.parse_binding_headers(headers) == expected


@pytest.mark.parametrize(
    "missing_header",
    (
        transport.EVENT_ID_HEADER,
        transport.ACTOR_ID_HEADER,
        transport.CHANNEL_ID_HEADER,
    ),
)
def test_parse_binding_headers_requires_each_mandatory_header_once(
    missing_header: str,
) -> None:
    headers = _bindings().as_headers()
    del headers[missing_header]
    with pytest.raises(transport.DiscordActorHeaderError, match="required exactly once"):
        transport.parse_binding_headers(headers)


@pytest.mark.parametrize(
    "duplicate_header",
    (
        transport.EVENT_ID_HEADER,
        transport.ACTOR_ID_HEADER,
        transport.CHANNEL_ID_HEADER,
        transport.GUILD_ID_HEADER,
        transport.THREAD_ID_HEADER,
    ),
)
def test_parse_binding_headers_rejects_duplicate_dedicated_headers(
    duplicate_header: str,
) -> None:
    pairs: list[tuple[str, object]] = list(_bindings().as_headers().items())
    if duplicate_header in {transport.GUILD_ID_HEADER, transport.THREAD_ID_HEADER}:
        pairs.append((duplicate_header, "4"))
    pairs.extend(((duplicate_header.lower(), "5"), (duplicate_header, "6")))

    with pytest.raises(transport.DiscordActorHeaderError):
        transport.parse_binding_headers(MultiHeaders(pairs))


def test_parse_binding_headers_rejects_non_mapping_and_non_string_values() -> None:
    with pytest.raises(transport.DiscordActorHeaderError, match="mapping"):
        transport.parse_binding_headers(object())

    pairs: list[tuple[str, object]] = list(_bindings().as_headers().items())
    pairs[0] = (pairs[0][0], 123)
    with pytest.raises(transport.DiscordActorHeaderError, match="invalid"):
        transport.parse_binding_headers(MultiHeaders(pairs))


def test_parse_envelope_header_accepts_one_bounded_ascii_value() -> None:
    envelope = '{"envelope_version":2,"seal":"' + ("a" * 64) + '"}'
    headers = {transport.ENVELOPE_HEADER.lower(): envelope}

    assert transport.parse_envelope_header(headers) == envelope


@pytest.mark.parametrize(
    "headers",
    (
        {},
        {transport.ENVELOPE_HEADER: ""},
        {transport.ENVELOPE_HEADER: " envelope"},
        {transport.ENVELOPE_HEADER: "envelope "},
        {transport.ENVELOPE_HEADER: "env\nelope"},
        {transport.ENVELOPE_HEADER: "envelop\u00e9"},
        {transport.ENVELOPE_HEADER: "x" * 4097},
    ),
)
def test_parse_envelope_header_rejects_missing_or_malformed_values(
    headers: dict[str, str],
) -> None:
    with pytest.raises(transport.DiscordActorHeaderError):
        transport.parse_envelope_header(headers)


def test_parse_envelope_header_rejects_duplicates() -> None:
    headers = MultiHeaders([
        (transport.ENVELOPE_HEADER, "one"),
        (transport.ENVELOPE_HEADER.lower(), "two"),
    ])
    with pytest.raises(transport.DiscordActorHeaderError, match="exactly once"):
        transport.parse_envelope_header(headers)


@pytest.mark.parametrize("bad_secret", ("x" * 31, "\u00e9" * 15 + "x", b"x" * 31))
def test_build_actor_store_rejects_short_dedicated_seal(
    tmp_path: Path,
    bad_secret: str | bytes,
) -> None:
    with pytest.raises(ValueError, match="at least 32 UTF-8 bytes"):
        transport.build_actor_store(tmp_path, bad_secret)


def test_build_actor_store_rejects_non_text_or_bytes_secret(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="str or bytes"):
        transport.build_actor_store(tmp_path, bytearray(b"x" * 32))  # type: ignore[arg-type]


def test_build_actor_store_uses_fixed_paths_policy_boundary_and_dev_anchor(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    store = transport.build_actor_store(home, SEAL_SECRET)

    assert store.ready is True
    assert store.db_path == home / transport.ACTOR_DB_FILENAME
    assert store.key_version == transport.KEY_VERSION
    assert store.policy == transport.ACTOR_POLICY
    assert store.boundary == transport.ACTOR_BOUNDARY
    assert type(store.clock) is actor_identity.SystemTrustedClock
    assert type(store.monotonic_anchor) is actor_identity.SQLiteMonotonicAnchor
    assert store.monotonic_anchor.db_path == home / transport.ANCHOR_DB_FILENAME
    assert store.monotonic_anchor.db_path != store.db_path
    assert store.db_path.is_file()
    assert store.monotonic_anchor.db_path.is_file()


def test_store_accepts_exact_six_mib_body_and_rejects_one_extra_byte(
    tmp_path: Path,
) -> None:
    store = transport.build_actor_store(tmp_path, SEAL_SECRET)
    body = b"x" * transport.MAX_DISCORD_BODY_BYTES
    bindings = _bindings(event_id="1001")

    envelope = store.issue_envelope(
        request_body=body,
        **bindings.as_store_kwargs(),
    )
    assert len(envelope.encode().encode("ascii")) <= transport.MAX_ENVELOPE_BYTES
    assert transport.parse_envelope_header(
        {transport.ENVELOPE_HEADER: envelope.encode()}
    ) == envelope.encode()
    accepted = store.verify_and_consume(
        envelope.encode(),
        request_body=body,
        **bindings.as_store_kwargs(),
    )
    assert accepted.accepted is True

    with pytest.raises(actor_identity.BridgeActorIdentityError, match="byte limit"):
        store.issue_envelope(
            request_body=body + b"x",
            **_bindings(event_id="1002").as_store_kwargs(),
        )


def test_factory_restart_preserves_issued_envelope(tmp_path: Path) -> None:
    bindings = _bindings(event_id="2001")
    first = transport.build_actor_store(tmp_path, SEAL_SECRET)
    envelope = first.issue_envelope(
        request_body=BODY,
        **bindings.as_store_kwargs(),
    ).encode()

    restarted = transport.build_actor_store(tmp_path, SEAL_SECRET)
    result = restarted.verify_and_consume(
        envelope,
        request_body=BODY,
        **bindings.as_store_kwargs(),
    )

    assert restarted.ready is True
    assert result.accepted is True
    assert result.actor is not None


def test_guest_scope_is_full_stable_opaque_and_domain_separated(
    tmp_path: Path,
) -> None:
    store = transport.build_actor_store(tmp_path, SEAL_SECRET)
    first_bindings = _bindings(event_id="3001")
    same_scope_bindings = _bindings(event_id="3002")
    other_actor_bindings = _bindings(event_id="3003", actor_id="9")
    other_thread_bindings = _bindings(event_id="3004", thread_id="8")

    first = _issue_and_verify(store, first_bindings)
    same_scope = _issue_and_verify(store, same_scope_bindings, body=b'{"text":"next"}')
    other_actor = _issue_and_verify(store, other_actor_bindings)
    other_thread = _issue_and_verify(store, other_thread_bindings)

    first_scope = transport.guest_scope(first)
    assert transport.guest_scope(same_scope) == first_scope
    assert transport.guest_scope(other_actor) != first_scope
    assert transport.guest_scope(other_thread) != first_scope

    conversation_id, privacy_scope = first_scope
    assert re.fullmatch(r"discord-guest-[0-9a-f]{64}", conversation_id)
    assert re.fullmatch(r"guest-discord-[0-9a-f]{64}", privacy_scope)
    assert conversation_id.removeprefix("discord-guest-") != privacy_scope.removeprefix(
        "guest-discord-"
    )
    serialized_scope = "|".join(first_scope)
    for raw_id in first_bindings.as_store_kwargs().values():
        if raw_id is not None:
            assert raw_id not in serialized_scope
    assert first.event_id_hmac not in serialized_scope
    assert first.body_hmac not in serialized_scope

    material = b"".join((
        b"alpecca:discord-guest-scope:v1\x00",
        bytes.fromhex(first.actor_subject_hmac),
        bytes.fromhex(first.thread_scope_hmac),
    ))
    assert conversation_id == (
        "discord-guest-" + hashlib.sha256(b"conversation\x00" + material).hexdigest()
    )
    assert privacy_scope == (
        "guest-discord-" + hashlib.sha256(b"privacy\x00" + material).hexdigest()
    )


def test_guest_scope_rejects_unverified_actor_shapes() -> None:
    fake = SimpleNamespace(
        authority="guest",
        actor_subject_hmac="a" * 64,
        thread_scope_hmac="b" * 64,
    )
    with pytest.raises(TypeError, match="verifier-created"):
        transport.guest_scope(fake)  # type: ignore[arg-type]


def test_guest_scope_fails_closed_if_verified_actor_hmac_is_corrupted(
    tmp_path: Path,
) -> None:
    store = transport.build_actor_store(tmp_path, SEAL_SECRET)
    actor = _issue_and_verify(store, _bindings(event_id="4001"))
    object.__setattr__(actor, "actor_subject_hmac", "not-a-valid-hmac")

    with pytest.raises(actor_identity.BridgeActorIntegrityError, match="malformed"):
        transport.guest_scope(actor)
