"""Focused coverage for bounded Discord image ingress and egress."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from alpecca import discord_bridge
from alpecca import discord_media
from alpecca.bridge_actor_transport import DiscordActorBindings
from alpecca import vision


ROOT = Path(__file__).resolve().parents[1]


def _discord_launcher_module():
    spec = importlib.util.spec_from_file_location(
        "test_discord_launcher",
        ROOT / "scripts" / "run_discord_bridge.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _png(width: int = 3, height: int = 2) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png())


def test_prepare_inbound_image_sniffs_bytes_and_emits_canonical_data_url():
    prepared = discord_media.prepare_inbound_image(
        _png(),
        declared_mime_type="image/png",
    )

    assert prepared.mime_type == "image/png"
    assert prepared.size_bytes == len(_png())
    assert prepared.width == 3
    assert prepared.height == 2
    assert prepared.data_url.startswith("data:image/png;base64,")
    assert len(prepared.sha256) == 64


@pytest.mark.parametrize(
    ("payload", "declared", "reason"),
    (
        (_png(), "image/jpeg", "mime-mismatch"),
        (b"not an image", "image/png", "mime-mismatch"),
        (b"A" * (discord_media.INBOUND_MAX_BYTES + 1), None, "size-limit"),
    ),
    ids=("mime-mismatch", "invalid-bytes", "size-limit"),
)
def test_prepare_inbound_image_rejects_mismatch_invalid_bytes_and_oversize(
    payload: bytes,
    declared: str | None,
    reason: str,
):
    with pytest.raises(discord_media.DiscordImageRejected) as caught:
        discord_media.prepare_inbound_image(
            payload,
            declared_mime_type=declared,
        )

    assert caught.value.reason == reason


def test_attachment_candidate_metadata_never_substitutes_for_byte_validation():
    assert discord_media.looks_like_image_attachment("photo.png", None) is True
    assert discord_media.looks_like_image_attachment("payload.bin", "image/png") is True
    assert discord_media.looks_like_image_attachment("notes.txt", "text/plain") is False

    with pytest.raises(discord_media.DiscordImageRejected):
        discord_media.prepare_inbound_image(
            b"not a PNG",
            declared_mime_type="image/png",
        )


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("send your portrait", "portrait"),
        ("show me your base model", "base"),
        ("share your character sheet", "reference"),
        ("!image gallery", "gallery"),
        ("can you see this image?", None),
        ("open C:/private/secret.png", None),
    ),
)
def test_requested_media_kind_requires_an_explicit_closed_catalog_request(
    text: str,
    expected: str | None,
):
    assert discord_media.requested_media_kind(text) == expected


def test_outbound_catalog_returns_only_owned_bytes_and_generic_filename(tmp_path):
    avatar_dir = tmp_path / "avatar"
    character_dir = tmp_path / "character"
    _write_png(avatar_dir / "portraits" / "idle.png")
    _write_png(character_dir / "reference" / "base-model.png")
    _write_png(character_dir / "reference" / "master-character-sheet.png")
    older = character_dir / "gallery" / "self-20260712-100000.png"
    newer = character_dir / "gallery" / "self-20260712-110000.png"
    _write_png(older)
    _write_png(newer)
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    portrait = discord_media.resolve_outbound_media(
        "send your portrait",
        avatar_dir=avatar_dir,
        character_dir=character_dir,
    )
    reference = discord_media.resolve_outbound_media(
        "share your character sheet",
        avatar_dir=avatar_dir,
        character_dir=character_dir,
    )
    gallery = discord_media.resolve_outbound_media(
        "!image gallery",
        avatar_dir=avatar_dir,
        character_dir=character_dir,
    )

    assert portrait is not None
    assert portrait.filename == "alpecca-portrait.png"
    assert portrait.image_bytes == _png()
    assert reference is not None and reference.filename == "alpecca-reference.png"
    assert gallery is not None and gallery.filename == "alpecca-gallery.png"
    assert b"private" not in portrait.image_bytes


def test_outbound_catalog_fails_closed_for_missing_or_invalid_assets(tmp_path):
    avatar_dir = tmp_path / "avatar"
    character_dir = tmp_path / "character"

    assert discord_media.resolve_outbound_media(
        "send your portrait",
        avatar_dir=avatar_dir,
        character_dir=character_dir,
    ) is None

    bad = avatar_dir / "portraits" / "idle.png"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"not an image")
    assert discord_media.resolve_outbound_media(
        "send your portrait",
        avatar_dir=avatar_dir,
        character_dir=character_dir,
    ) is None


def test_bridge_posts_only_image_field_and_uses_extended_image_timeout(monkeypatch):
    calls: list[tuple[object, float]] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, *_args):
            if len(calls) == 1:
                return b'{"envelope":"signed-actor-envelope"}'
            return (
                b'{"perception":{"status":"described"},'
                b'"reply":"I can see it."}'
            )

    def fake_open_backend(request, *, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(
        discord_bridge,
        "_open_backend_request",
        fake_open_backend,
    )

    reply = discord_bridge._ask_alpecca(
        "Who is this?",
        "CreatorJD",
        "discord-dm",
        speaker="creator",
        image="data:image/png;base64,AAAA",
        actor_bindings=DiscordActorBindings(
            event_id="1001",
            actor_id="42",
            channel_id="3001",
        ),
    )

    assert reply == "I can see it."
    assert len(calls) == 2
    mint_request, mint_timeout = calls[0]
    request, timeout = calls[1]
    body = json.loads(request.data)
    assert mint_request.full_url.endswith("/channel/discord/actor-envelope")
    assert mint_request.data is request.data
    assert request.full_url.endswith("/channel/discord")
    assert body["image"] == "data:image/png;base64,AAAA"
    assert "file_name" not in body
    assert "file_data" not in body
    assert mint_timeout == discord_bridge.INBOUND_TIMEOUT
    assert timeout == discord_bridge.IMAGE_INBOUND_TIMEOUT
    assert timeout > discord_bridge.INBOUND_TIMEOUT


def test_vision_result_reports_verified_local_metadata_when_cloud_is_configured(
    monkeypatch,
):
    import config

    def reject_cloud(*_args):
        raise AssertionError("generic vision must not call a cloud provider")

    monkeypatch.setattr(config, "VISION_BACKEND", "ollama-cloud")
    monkeypatch.setattr(vision, "_describe_ollama_cloud", reject_cloud)
    monkeypatch.setattr(vision, "_describe_zerogpu", reject_cloud)
    monkeypatch.setattr(vision, "_describe_local", lambda *_args: "local view")

    default_result = vision.describe_image_result(_png())
    ambient_result = vision.describe_image_result(_png(), ambient=True)

    expected = vision.VisionDescription(
        "local view",
        "local-ollama",
        "local-only",
        "denied",
    )
    assert default_result == expected
    assert ambient_result == expected


def test_creator_dm_username_check_never_trusts_spoofable_display_name(monkeypatch):
    class Author:
        id = 42
        name = "someone-else"
        global_name = "realcreatorjd"

    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", set())
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", {"realcreatorjd"})

    assert discord_bridge._dm_author_allowed(Author()) is False
    Author.name = "realcreatorjd"
    assert discord_bridge._dm_author_allowed(Author()) is True
    assert discord_bridge.DM_ALLOW_IDS == {"42"}


def test_media_audit_contains_metadata_but_not_image_bytes(monkeypatch):
    seen = []
    monkeypatch.setattr(
        discord_media.cognition_mod,
        "record_observation",
        lambda observation: seen.append(observation) or 17,
    )

    observation_id = discord_media.record_media_event(
        "outbound",
        status="sent",
        mime_type="image/png",
        size_bytes=123,
        sha256="a" * 64,
        kind="portrait",
    )

    assert observation_id == 17
    assert seen[0].scope == "creator:discord"
    assert seen[0].metadata == {
        "event": "discord_image",
        "direction": "outbound",
        "status": "sent",
        "mime_type": "image/png",
        "size_bytes": 123,
        "sha256": "a" * 64,
        "kind": "portrait",
    }
    assert "base64" not in json.dumps(seen[0].metadata)


def test_media_readiness_is_truthful_bounded_and_secret_free():
    disabled = discord_media.media_readiness(media_enabled=False)
    unverified = discord_media.media_readiness(media_enabled=True)
    ready = discord_media.media_readiness(
        media_enabled=True,
        server_status="ready",
        local_vision_status="ready",
    )

    assert disabled["ready"] is False
    assert disabled["receive"]["image"]["status"] == "disabled"
    assert disabled["send"]["image"]["status"] == "disabled"
    assert unverified["receive"]["image"]["status"] == "unverified"
    assert ready["ready"] is True
    assert ready["receive"]["image"] == {
        "status": "ready",
        "max_bytes": discord_media.INBOUND_MAX_BYTES,
        "mime_types": ["image/gif", "image/jpeg", "image/png"],
        "processing": "verified-local-only",
        "cloud_egress": "denied",
    }
    serialized = json.dumps(ready, sort_keys=True).casefold()
    assert all(
        forbidden not in serialized
        for forbidden in ("token", "secret", "authorization", "endpoint", "path")
    )
    assert ready["receive"]["file"] == {"status": "disabled"}
    assert ready["receive"]["audio"] == {"status": "disabled"}
    assert ready["send"]["file"] == {"status": "disabled"}
    assert ready["send"]["audio"] == {"status": "disabled"}


@pytest.mark.parametrize(
    ("secret_value", "process_value", "expected_status"),
    (
        ("", None, "explicit-closed-catalog"),
        ("ALPECCA_DISCORD_MEDIA=0\n", None, "disabled"),
        ("ALPECCA_DISCORD_MEDIA=1\n", "0", "disabled"),
    ),
    ids=("default-enabled", "secret-false", "process-false-wins"),
)
def test_direct_launcher_media_default_loads_secret_before_selecting_default(
    monkeypatch,
    capsys,
    tmp_path,
    secret_value: str,
    process_value: str | None,
    expected_status: str,
):
    launcher = _discord_launcher_module()
    secret = tmp_path / "alpecca_discord.env"
    secret.write_text(secret_value, encoding="utf-8")
    monkeypatch.setattr(launcher, "SECRET", secret)
    if process_value is None:
        monkeypatch.delenv("ALPECCA_DISCORD_MEDIA", raising=False)
    else:
        monkeypatch.setenv("ALPECCA_DISCORD_MEDIA", process_value)

    assert launcher.main(["--media-readiness"]) == 0

    readiness = json.loads(capsys.readouterr().out)
    assert readiness["send"]["image"]["status"] == expected_status
    assert readiness["receive"]["image"]["status"] == (
        "disabled" if expected_status == "disabled" else "unverified"
    )


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    (
        ("photo.png", "application/octet-stream", "image"),
        ("voice.ogg", "application/octet-stream", "audio"),
        ("notes.pdf", "application/pdf", "file"),
    ),
)
def test_attachment_metadata_classification_never_claims_file_or_audio_support(
    filename: str,
    content_type: str,
    expected: str,
):
    assert discord_media.attachment_media_kind(filename, content_type) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("send me an audio recording", "audio"),
        ("!audio voice-note", "audio"),
        ("attach that PDF document", "file"),
        ("!file report", "file"),
        ("tell me about audio", None),
    ),
)
def test_disabled_outbound_payload_requests_are_explicit_only(
    text: str,
    expected: str | None,
):
    assert discord_media.requested_disabled_media_kind(text) == expected


def test_image_backend_requires_verified_local_perception_metadata(monkeypatch):
    calls = 0

    def fake_post(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"envelope": "signed-actor-envelope"}
        return {
            "reply": "I can definitely see private details.",
            "perception": {"status": "vision-unavailable"},
        }

    monkeypatch.setattr(discord_bridge, "_post_json_once", fake_post)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "_SERVER_MEDIA_STATUS", "unknown")
    monkeypatch.setattr(discord_bridge, "_LOCAL_VISION_STATUS", "unknown")

    with pytest.raises(discord_bridge.DiscordMediaUnavailable) as caught:
        discord_bridge._ask_alpecca(
            "inspect this",
            "Discord guest",
            "discord-dm",
            image="data:image/png;base64,AAAA",
            actor_bindings=DiscordActorBindings(
                event_id="1001",
                actor_id="42",
                channel_id="3001",
            ),
        )

    assert caught.value.reason == "vision-unavailable"
    assert "private details" not in str(caught.value)
    assert discord_bridge.media_readiness()["receive"]["image"]["status"] == (
        "vision-unavailable"
    )


def test_server_media_disablement_maps_only_the_exact_fixed_error(monkeypatch):
    calls = 0

    def fake_post(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"envelope": "signed-actor-envelope"}
        raise discord_bridge._BackendRequestRejected(
            403,
            error_code="capability_disabled",
            capability="discord_media",
        )

    monkeypatch.setattr(discord_bridge, "_post_json_once", fake_post)
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "_SERVER_MEDIA_STATUS", "unknown")
    monkeypatch.setattr(discord_bridge, "_LOCAL_VISION_STATUS", "unknown")

    with pytest.raises(discord_bridge.DiscordMediaUnavailable) as caught:
        discord_bridge._ask_alpecca(
            "inspect this",
            "Discord guest",
            "discord-dm",
            image="data:image/png;base64,AAAA",
            actor_bindings=DiscordActorBindings(
                event_id="1001",
                actor_id="42",
                channel_id="3001",
            ),
        )

    assert caught.value.reason == "media-disabled"
    assert discord_bridge.media_readiness()["receive"]["image"]["status"] == (
        "disabled"
    )


def test_room_media_diagnostic_cannot_leak_from_history_into_later_turns(monkeypatch):
    """A past image request remains model context, never a fresh media action."""

    room = {"guild_id": "777", "channel_id": "3001"}
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: {"777:3001": room})
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "VOICE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "RECURSIVE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "CHANNEL_MIN_INTERVAL", 0.0)
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", {"42"})
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", set())

    model_prompts: list[str] = []

    def ask(text: str, *_args, **_kwargs) -> str:
        model_prompts.append(text)
        return f"ordinary reply {len(model_prompts)}"

    monkeypatch.setattr(discord_bridge, "_ask_alpecca", ask)
    client = discord_bridge.build_client()
    client._connection.user = SimpleNamespace(
        id=9001,
        name="Alpecca",
        display_name="Alpecca",
    )

    class Typing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Channel:
        id = 3001

        def typing(self):
            return Typing()

        async def send(self, _content: str) -> None:
            raise AssertionError("addressed turns should reply, not send directly")

    channel = Channel()
    guild = SimpleNamespace(
        id=777,
        me=SimpleNamespace(display_name="Alpecca"),
        voice_client=None,
    )
    creator = SimpleNamespace(
        id=42,
        name="realcreatorjd",
        display_name="CreatorJD",
        bot=False,
    )

    def message(event_id: int, content: str, clean_content: str):
        replies: list[str] = []

        async def reply(value: str, **_kwargs) -> None:
            replies.append(value)

        return (
            SimpleNamespace(
                id=event_id,
                author=creator,
                guild=guild,
                channel=channel,
                content=content,
                clean_content=clean_content,
                mentions=[SimpleNamespace(id=9001)],
                attachments=[],
                reference=None,
                reply=reply,
            ),
            replies,
        )

    media_turn, media_replies = message(
        1001,
        "<@9001> Can you send me an image of yourself?",
        "@Alpecca Can you send me an image of yourself?",
    )
    name_turn, name_replies = message(
        1002,
        "<@9001> Alpecca",
        "@Alpecca Alpecca",
    )
    hello_turn, hello_replies = message(
        1003,
        "<@9001> Hello",
        "@Alpecca Hello",
    )

    async def scenario() -> None:
        await client.on_message(media_turn)
        await client.on_message(name_turn)
        await client.on_message(hello_turn)

    asyncio.run(scenario())

    media_diagnostic = discord_media.media_diagnostic("media-disabled")
    assert media_replies == [media_diagnostic]
    assert name_replies == ["ordinary reply 1"]
    assert hello_replies == ["ordinary reply 2"]
    assert len(model_prompts) == 2
    # The old request stays visible to the model as room context, but it cannot
    # re-trigger the transport-level media diagnostic.
    assert "Can you send me an image of yourself?" in model_prompts[0]


def test_claimed_room_self_image_request_attaches_once_then_records_sent(monkeypatch):
    """Guild catalog sends preserve the accepted -> Discord -> sent audit order."""

    room = {"guild_id": "777", "channel_id": "3001"}
    monkeypatch.setattr(discord_bridge, "_load_social_rooms", lambda: {"777:3001": room})
    monkeypatch.setattr(discord_bridge, "MEDIA_ENABLED", True)
    monkeypatch.setattr(discord_bridge, "VOICE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "PROACTIVE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "RECURSIVE_ENABLED", False)
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_IDS", {"42"})
    monkeypatch.setattr(discord_bridge, "DM_ALLOW_NAMES", set())
    monkeypatch.setattr(discord_bridge, "_ask_alpecca", lambda *_args, **_kwargs: "Here it is.")

    outbound = discord_media.OutboundDiscordImage(
        kind="portrait",
        filename="alpecca-portrait.png",
        image_bytes=_png(),
        mime_type="image/png",
        size_bytes=len(_png()),
        sha256="a" * 64,
    )
    resolve_calls: list[str] = []
    monkeypatch.setattr(
        discord_bridge.discord_media,
        "resolve_outbound_media",
        lambda text: resolve_calls.append(text) or outbound,
    )
    timeline: list[tuple[str, str]] = []

    def record(direction: str, *, status: str, **_kwargs) -> int:
        timeline.append((direction, status))
        return len(timeline)

    monkeypatch.setattr(discord_bridge.discord_media, "record_media_event", record)
    client = discord_bridge.build_client()
    client._connection.user = SimpleNamespace(
        id=9001,
        name="Alpecca",
        display_name="Alpecca",
    )

    class Typing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Channel:
        id = 3001

        def typing(self):
            return Typing()

    channel = Channel()
    guild = SimpleNamespace(
        id=777,
        me=SimpleNamespace(display_name="Alpecca"),
        voice_client=None,
    )
    creator = SimpleNamespace(
        id=42,
        name="realcreatorjd",
        display_name="CreatorJD",
        bot=False,
    )
    replies: list[tuple[str, dict[str, object]]] = []

    async def reply(content: str, **kwargs: object) -> None:
        replies.append((content, kwargs))
        timeline.append(("discord", "reply"))

    message = SimpleNamespace(
        id=1001,
        author=creator,
        guild=guild,
        channel=channel,
        content="<@9001> Can you send me an image of yourself?",
        clean_content="@Alpecca Can you send me an image of yourself?",
        mentions=[SimpleNamespace(id=9001)],
        attachments=[],
        reference=None,
        reply=reply,
    )

    asyncio.run(client.on_message(message))

    assert resolve_calls == ["Can you send me an image of yourself?"]
    assert len(replies) == 1
    content, kwargs = replies[0]
    assert content == "Here it is."
    assert kwargs["mention_author"] is False
    assert kwargs["file"].filename == "alpecca-portrait.png"
    assert timeline == [
        ("outbound", "accepted"),
        ("discord", "reply"),
        ("outbound", "sent"),
    ]
