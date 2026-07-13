"""Alpecca's Discord presence: a thin, bounded bridge to her mind.

She runs as a proper Discord **bot** (never a self-bot). A message she is allowed
to hear is forwarded to `POST /channel/discord` -> her bounded guest chat path
(mood +
memory + people + affect) -> her reply is posted back in her own voice.

Current Phase 10 scope = creator-allowlisted DMs only, with the locked safety rails from
`docs/ALPECCA_DISCORD_PRESENCE.md`:

  - **Guilds/threads:** all messages hard-return before media or backend work until
    signed actor identity and scoped conversation wiring are live.
  - **DMs:** allowlist only. She answers DMs *only* from CreatorJD
    (`ALPECCA_DISCORD_DM_ALLOW` = comma-separated Discord user ids or unique
    usernames). Empty = no DMs. One byte-validated image can enter her vision;
    explicit image requests can attach one item from her closed local catalog.
  - She never replies to herself or to other bots.
  - Everyone in a channel is a guest to her people-layer; her mind stays
    courteously guarded with strangers on its own.

Run it with `python scripts/run_discord_bridge.py` (loads the gitignored token).
Her backend (`server.py`) must be running so `/channel/discord` is reachable.
"""
from __future__ import annotations

import asyncio
import ipaddress
import io
import json
import os
import random
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path

import discord

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpecca.auth import (
    BRIDGE_AUTHORIZATION_HEADER,
    load_or_create_bridge_authorization_secret,
)
from alpecca import bridge_actor_transport, discord_media
from config import HOME, HOST, PORT, PUBLIC_URL


_BRIDGE_AUTHORIZATION_SECRET = load_or_create_bridge_authorization_secret(HOME)

def _resolve_backend_url() -> str:
    """Prefer explicit backend override, then shared public URL, then local host."""
    configured = os.environ.get("ALPECCA_BACKEND_URL", "").strip()
    public_url = (os.environ.get("ALPECCA_PUBLIC_URL", "").strip() or PUBLIC_URL).strip()
    if configured:
        return configured.rstrip("/")
    if public_url:
        parsed = urlparse(public_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        return public_url.rstrip("/")
    return f"http://{HOST}:{PORT}".rstrip("/")


BACKEND_URL = _resolve_backend_url()
LOCAL_BACKEND_URL = f"http://127.0.0.1:{PORT}"
DM_ALLOW = {s.strip() for s in os.environ.get("ALPECCA_DISCORD_DM_ALLOW", "").split(",") if s.strip()}
# The allowlist accepts numeric user ids AND usernames (e.g. "realcreatorjd").
# Usernames resolve to ids lazily on first contact (the DM itself carries the
# author's name) and eagerly on_ready via a guild member query; resolved ids
# are cached so later checks are direct.
DM_ALLOW_IDS = {entry for entry in DM_ALLOW if entry.isdigit()}
DM_ALLOW_NAMES = {entry.casefold() for entry in DM_ALLOW if entry and not entry.isdigit()}


def _environment_enabled(name: str) -> bool:
    return os.environ.get(name, "0").strip().lower() not in {
        "", "0", "false", "no", "off",
    }


MEDIA_ENABLED = _environment_enabled("ALPECCA_DISCORD_MEDIA")


def _dm_author_allowed(author: "discord.abc.User") -> bool:
    """Whether this DM author is on the creator allowlist."""
    author_id = str(author.id)
    if author_id in DM_ALLOW_IDS:
        return True
    if not DM_ALLOW_NAMES:
        return False
    # Discord usernames are account identifiers; global/display names are not
    # unique and therefore cannot authorize creator-only DMs.
    username = str(getattr(author, "name", "") or "").casefold()
    if username in DM_ALLOW_NAMES:
        DM_ALLOW_IDS.add(author_id)
        _diagnostic("dm_allow_resolved")
        return True
    return False
INBOUND_TIMEOUT = float(os.environ.get("ALPECCA_DISCORD_INBOUND_TIMEOUT", "45"))
IMAGE_INBOUND_TIMEOUT = max(
    INBOUND_TIMEOUT,
    float(os.environ.get("ALPECCA_DISCORD_IMAGE_TIMEOUT", "300")),
)
MAX_DISCORD_CHARS = 2000
MAX_BACKEND_RESPONSE_BYTES = 1024 * 1024
MAX_BACKEND_ERROR_BYTES = 16 * 1024
# Phase 10 stays closed until the signed actor envelope is wired end to end.
# These are code locks, not deployment knobs: environment flags cannot widen
# Discord into guild participation, autonomous speech, recursion, or voice.
PHASE10_GUILD_MODES_LOCKED = True
# How long she stays "in conversation" in a channel after being addressed, so
# follow-ups don't need a re-mention (natural back-and-forth).
ENGAGE_WINDOW = float(os.environ.get("ALPECCA_DISCORD_ENGAGE_WINDOW", "90"))

# Minimum seconds between her messages in one channel (anti-flood safety).
CHANNEL_MIN_INTERVAL = float(os.environ.get("ALPECCA_DISCORD_MIN_INTERVAL", "1.5"))
# Natural, unprompted chime-in ("butting in"): only on relevant openings, only
# sometimes, and with a long per-channel cooldown that backs off further whenever
# a chime-in goes unanswered -- so it reads as a person occasionally joining, not
# a bot reacting to everything.
PROACTIVE_ENABLED = False
PROACTIVE_COOLDOWN = float(os.environ.get("ALPECCA_DISCORD_PROACTIVE_COOLDOWN", "480"))
PROACTIVE_CHANCE = float(os.environ.get("ALPECCA_DISCORD_PROACTIVE_CHANCE", "0.3"))
PROACTIVE_MIN_LEN = int(os.environ.get("ALPECCA_DISCORD_PROACTIVE_MIN_LEN", "40"))
# Recursive self-continuation: when the room goes quiet after SHE spoke, she may
# continue her own train of thought a little deeper -- bounded, paced, and it
# yields the instant any human speaks, so it never becomes a monologue/spam.
RECURSIVE_ENABLED = False
RECURSIVE_MAX = int(os.environ.get("ALPECCA_DISCORD_RECURSIVE_MAX", "2"))       # self-steps before waiting for a human
RECURSIVE_DELAY = float(os.environ.get("ALPECCA_DISCORD_RECURSIVE_DELAY", "75"))  # quiet seconds before she continues
RECURSIVE_SWEEP = float(os.environ.get("ALPECCA_DISCORD_RECURSIVE_SWEEP", "20"))  # how often the loop checks
DEBUG = _environment_enabled("ALPECCA_DISCORD_DEBUG")
# Contextual participation: she reads the recent channel conversation and may
# speak WITHOUT being mentioned -- but she decides per message whether she has
# something worth adding (she can choose "(pass)"), throttled so it isn't spam.
PARTICIPATE = False
PARTICIPATE_COOLDOWN = float(os.environ.get("ALPECCA_DISCORD_PARTICIPATE_COOLDOWN", "45"))  # min secs between unprompted weigh-ins
CONTEXT_MESSAGES = int(os.environ.get("ALPECCA_DISCORD_CONTEXT", "8"))                        # recent msgs given as context
# Voice chat: she can join a voice channel (on request) and SPEAK her replies with
# her real TTS voice. Bots stream audio (supported); video/camera is not possible.
VOICE_ENABLED = False

_MEDIA_STATUS_LOCK = threading.Lock()
_SERVER_MEDIA_STATUS: discord_media.ServerMediaStatus = "unknown"
_LOCAL_VISION_STATUS: discord_media.LocalVisionStatus = "unknown"


class DiscordMediaUnavailable(RuntimeError):
    """One fixed media failure that is safe to return to Discord."""

    def __init__(self, reason: discord_media.MediaDiagnostic) -> None:
        self.reason = reason
        super().__init__(discord_media.media_diagnostic(reason))


def _set_media_status(
    *,
    server: discord_media.ServerMediaStatus | None = None,
    vision: discord_media.LocalVisionStatus | None = None,
) -> None:
    global _SERVER_MEDIA_STATUS, _LOCAL_VISION_STATUS
    with _MEDIA_STATUS_LOCK:
        if server is not None:
            _SERVER_MEDIA_STATUS = server
        if vision is not None:
            _LOCAL_VISION_STATUS = vision


def media_readiness() -> dict[str, object]:
    """Current secret-free Discord media posture for local diagnostics."""

    with _MEDIA_STATUS_LOCK:
        server_status = _SERVER_MEDIA_STATUS
        vision_status = _LOCAL_VISION_STATUS
    return discord_media.media_readiness(
        media_enabled=MEDIA_ENABLED,
        server_status=server_status,
        local_vision_status=vision_status,
    )


def _diagnostic(event: str, **metadata: object) -> None:
    """Emit only code-owned labels and bounded scalar metadata when opted in."""

    if not DEBUG:
        return
    allowed_fields = {
        "addressed",
        "attachment_count",
        "bytes",
        "dimensions",
        "dm",
        "in_conversation",
        "mime_type",
        "mode",
        "status",
        "text_bytes",
    }
    if (
        type(event) is not str
        or not event.isascii()
        or not event.replace("_", "").isalnum()
        or any(key not in allowed_fields for key in metadata)
        or any(
            type(value) not in {bool, int, str}
            for value in metadata.values()
        )
    ):
        raise ValueError("Discord diagnostic metadata is not allowlisted")
    encoded = json.dumps(
        {"event": event, **metadata},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    print(f"[discord] {encoded}", file=sys.stderr, flush=True)


def _is_reply_to_me(message: "discord.Message", client: "discord.Client") -> bool:
    """True if `message` is a Discord reply to one of Alpecca's own messages."""
    ref = message.reference
    resolved = getattr(ref, "resolved", None) if ref else None
    author = getattr(resolved, "author", None)
    return bool(author and client.user and author.id == client.user.id)


def _message_actor_bindings(
    message: "discord.Message",
) -> bridge_actor_transport.DiscordActorBindings:
    """Extract raw Discord IDs for dedicated transport headers only."""
    channel = getattr(message, "channel", None)
    author = getattr(message, "author", None)
    guild = getattr(message, "guild", None)
    if channel is None or author is None:
        raise bridge_actor_transport.DiscordActorHeaderError(
            "Discord actor bindings are unavailable"
        )

    event_id = getattr(message, "id", None)
    actor_id = getattr(author, "id", None)
    channel_id = getattr(channel, "id", None)
    if event_id is None or actor_id is None or channel_id is None:
        raise bridge_actor_transport.DiscordActorHeaderError(
            "Discord actor bindings are unavailable"
        )

    guild_id: str | None = None
    thread_id: str | None = None
    if guild is not None:
        raw_guild_id = getattr(guild, "id", None)
        if raw_guild_id is None:
            raise bridge_actor_transport.DiscordActorHeaderError(
                "Discord actor bindings are unavailable"
            )
        guild_id = str(raw_guild_id)
        parent_id = getattr(channel, "parent_id", None)
        if parent_id is not None:
            thread_id = str(channel_id)
            channel_id = parent_id

    return bridge_actor_transport.DiscordActorBindings(
        event_id=str(event_id),
        actor_id=str(actor_id),
        guild_id=guild_id,
        channel_id=str(channel_id),
        thread_id=thread_id,
    )


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects before urllib can copy actor credentials to a new URL."""

    @staticmethod
    def _reject(request, response, code, message, headers):
        if response is not None:
            response.close()
        raise urllib.error.HTTPError(
            request.full_url,
            code,
            message,
            headers,
            None,
        )

    def http_error_301(self, request, response, code, message, headers):
        return self._reject(request, response, code, message, headers)

    def http_error_302(self, request, response, code, message, headers):
        return self._reject(request, response, code, message, headers)

    def http_error_303(self, request, response, code, message, headers):
        return self._reject(request, response, code, message, headers)

    def http_error_307(self, request, response, code, message, headers):
        return self._reject(request, response, code, message, headers)

    def http_error_308(self, request, response, code, message, headers):
        return self._reject(request, response, code, message, headers)


class _BackendRequestRejected(RuntimeError):
    """Bounded backend rejection metadata; response bodies are never retained."""

    def __init__(
        self,
        status: int,
        *,
        error_code: str = "",
        capability: str = "",
    ) -> None:
        self.status = status if type(status) is int else 0
        self.error_code = error_code
        self.capability = capability
        super().__init__(f"alpecca backend rejected the request ({self.status})")


def _bounded_error_label(value: object) -> str:
    if type(value) is not str or not value or len(value) > 64 or not value.isascii():
        return ""
    compact = value.replace("_", "").replace("-", "")
    return value if compact.isalnum() else ""


def _backend_error_detail(exc: urllib.error.HTTPError) -> tuple[str, str]:
    """Read only fixed error labels; discard all other backend response data."""

    try:
        raw = exc.read(MAX_BACKEND_ERROR_BYTES + 1)
    except Exception:
        return "", ""
    finally:
        try:
            exc.close()
        except Exception:
            pass
    if type(raw) is not bytes or len(raw) > MAX_BACKEND_ERROR_BYTES:
        return "", ""
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
        return "", ""
    if type(payload) is not dict or type(payload.get("detail")) is not dict:
        return "", ""
    detail = payload["detail"]
    return (
        _bounded_error_label(detail.get("code")),
        _bounded_error_label(detail.get("capability")),
    )


def _is_loopback_backend_url(url: str) -> bool:
    """Whether an HTTP(S) backend URL names a literal local endpoint."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not hostname:
        return False
    normalized = hostname.rstrip(".").casefold()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _build_backend_opener(*, direct: bool) -> urllib.request.OpenerDirector:
    """Build a one-request opener with redirects disabled and optional no-proxy."""
    handlers: list[urllib.request.BaseHandler] = []
    if direct:
        handlers.append(urllib.request.ProxyHandler({}))
    handlers.append(_RejectRedirectHandler())
    return urllib.request.build_opener(*handlers)


def _open_backend_request(request: urllib.request.Request, *, timeout: float):
    opener = _build_backend_opener(
        direct=_is_loopback_backend_url(request.full_url),
    )
    return opener.open(request, timeout=timeout)


def _post_json_once(
    url: str,
    *,
    body: bytes,
    headers: dict[str, str],
    timeout: float,
) -> dict[str, object]:
    """POST one request exactly once and require a JSON object response."""
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with _open_backend_request(request, timeout=timeout) as response:
            raw_response = response.read(MAX_BACKEND_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        error_code, capability = _backend_error_detail(exc)
        raise _BackendRequestRejected(
            exc.code,
            error_code=error_code,
            capability=capability,
        ) from None
    except Exception as exc:
        raise RuntimeError(
            f"alpecca bridge request failed: {type(exc).__name__}"
        ) from None
    if type(raw_response) is not bytes:
        raise RuntimeError("alpecca backend returned a malformed response")
    if len(raw_response) > MAX_BACKEND_RESPONSE_BYTES:
        raise RuntimeError("alpecca backend response exceeds the bounded byte limit")
    try:
        payload = json.loads(raw_response)
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError) as exc:
        raise RuntimeError("alpecca backend returned malformed JSON") from exc
    if type(payload) is not dict:
        raise RuntimeError("alpecca backend returned a malformed result")
    return payload


def _ask_alpecca(
    text: str,
    sender: str,
    channel: str,
    speaker: str = "guest",
    context: str = "",
    room: str = "",
    image: str = "",
    actor_bindings: bridge_actor_transport.DiscordActorBindings | None = None,
) -> str:
    """Mint an actor proof, then forward the exact signed guest request bytes.

    `image` (optional) is a data-URL of an attached picture; the backend runs it
    through her vision + self-recognition. Raw document uploads are deliberately
    not part of this bridge contract. Blocking (urllib); callers run it off the
    event loop via asyncio.to_thread.
    """
    del sender, speaker
    if type(actor_bindings) is not bridge_actor_transport.DiscordActorBindings:
        raise RuntimeError("Discord actor bindings are required")
    if any(type(value) is not str for value in (text, channel, context, room, image)):
        raise TypeError("Discord guest payload fields must be strings")
    if channel not in {"discord", "discord-dm"}:
        raise ValueError("Discord channel label is not allowed")

    body_obj = {
        "text": text,
        "sender": "Discord guest",
        "channel": channel,
        "situation": context,
        "context": context,
        "room": room,
        "speaker": "guest",
    }
    if image:
        body_obj["image"] = image
    body = json.dumps(
        body_obj,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(body) > bridge_actor_transport.MAX_DISCORD_BODY_BYTES:
        raise ValueError("Discord guest payload exceeds the bounded byte limit")

    base_headers = {
        "Content-Type": "application/json",
        BRIDGE_AUTHORIZATION_HEADER: _BRIDGE_AUTHORIZATION_SECRET,
        **actor_bindings.as_headers(),
    }
    # Pixel-bearing requests stay on the laptop even when text traffic uses a
    # tunnel. Cloud model egress, when explicitly consented, happens only after
    # the local server validates and classifies the image.
    backend_url = LOCAL_BACKEND_URL if image else BACKEND_URL
    mint_payload = _post_json_once(
        f"{backend_url}/channel/discord/actor-envelope",
        body=body,
        headers=base_headers,
        timeout=INBOUND_TIMEOUT,
    )
    if (
        set(mint_payload) != {"envelope"}
        or type(mint_payload.get("envelope")) is not str
    ):
        raise RuntimeError("alpecca backend returned a malformed actor envelope")
    try:
        envelope = bridge_actor_transport.parse_envelope_header(
            {bridge_actor_transport.ENVELOPE_HEADER: mint_payload["envelope"]}
        )
    except bridge_actor_transport.DiscordActorHeaderError as exc:
        raise RuntimeError("alpecca backend returned a malformed actor envelope") from exc

    try:
        payload = _post_json_once(
            f"{backend_url}/channel/discord",
            body=body,
            headers={
                **base_headers,
                bridge_actor_transport.ENVELOPE_HEADER: envelope,
            },
            timeout=IMAGE_INBOUND_TIMEOUT if image else INBOUND_TIMEOUT,
        )
    except _BackendRequestRejected as exc:
        if (
            image
            and exc.status == 403
            and exc.error_code == "capability_disabled"
            and exc.capability == "discord_media"
        ):
            _set_media_status(server="disabled", vision="unknown")
            raise DiscordMediaUnavailable("media-disabled") from None
        raise
    if image:
        perception = payload.get("perception")
        perception_status = (
            perception.get("status") if type(perception) is dict else None
        )
        if perception_status != "described":
            _set_media_status(server="ready", vision="unavailable")
            raise DiscordMediaUnavailable("vision-unavailable")
        _set_media_status(server="ready", vision="ready")
    reply = payload.get("reply")
    if type(reply) is not str:
        raise RuntimeError("alpecca backend returned a malformed Discord reply")
    return reply.strip()


_FFMPEG_EXE = None


def _ffmpeg_exe() -> str:
    global _FFMPEG_EXE
    if _FFMPEG_EXE is None:
        import imageio_ffmpeg
        _FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
    return _FFMPEG_EXE


def _synth_voice_wav(text: str) -> "bytes | None":
    """Ask the backend /tts to synthesize her voice; return audio bytes or None.

    Blocking (urllib); callers run it off the event loop via asyncio.to_thread.
    """
    if not VOICE_ENABLED:
        return None
    body = json.dumps({"text": text}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        BRIDGE_AUTHORIZATION_HEADER: _BRIDGE_AUTHORIZATION_SECRET,
    }
    req = urllib.request.Request(f"{BACKEND_URL}/tts", data=body, headers=headers, method="POST")
    try:
        with _open_backend_request(req, timeout=INBOUND_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            data = resp.read()
    except Exception:
        _diagnostic("voice_synthesis_failed")
        return None
    return data if (data and len(data) > 1024) else None


def build_client() -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True   # needed to read message text (also enable in the portal)
    intents.voice_states = False
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        if VOICE_ENABLED:
            try:
                if not discord.opus.is_loaded():
                    discord.opus._load_default()
            except Exception:
                _diagnostic("voice_opus_unavailable")
            try:
                import discord.voice_client as _vc
                try:
                    import davey as _davey
                    _davey_ok = getattr(_davey, "__version__", "yes")
                except Exception:
                    _davey_ok = "MISSING"
                _diagnostic("voice_capabilities_checked")
            except Exception:
                _diagnostic("voice_capabilities_failed")
        # Resolve username allowlist entries to ids up front so DM permission
        # does not depend on the member cache. A non-empty query does not need
        # the privileged members intent; failure just leaves lazy resolution.
        for guild in client.guilds:
            for wanted in list(DM_ALLOW_NAMES):
                try:
                    members = await guild.query_members(query=wanted, limit=5)
                except Exception:
                    _diagnostic("dm_allow_lookup_failed")
                    continue
                for member in members:
                    if wanted == member.name.casefold():
                        DM_ALLOW_IDS.add(str(member.id))
                        _diagnostic("dm_allow_resolved")
        print(
            "[discord] "
            + json.dumps(
                {
                    "event": "bridge_ready",
                    "guild_count": len(client.guilds),
                    "dm_allow_configured": bool(DM_ALLOW_IDS or DM_ALLOW_NAMES),
                    "media": media_readiness(),
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            flush=True,
        )
        if RECURSIVE_ENABLED and not _sweeper_started["on"]:
            _sweeper_started["on"] = True
            client.loop.create_task(recursive_sweeper())

    # Per-channel state so she can (1) talk without re-mentions and (2) chime in
    # unprompted at a natural, self-limiting pace.
    engaged: dict[int, dict[int, float]] = {}     # channel -> {user -> last exchange ts}
    last_reply_at: dict[int, float] = {}          # channel -> ts of her last message
    last_proactive_at: dict[int, float] = {}      # channel -> ts of her last chime-in
    ignored_streak: dict[int, int] = {}           # channel -> unanswered chime-ins in a row
    her_last_ts: dict[int, float] = {}            # channel -> ts of her last message (recursion)
    last_human_ts: dict[int, float] = {}          # channel -> ts of last human message
    chain_depth: dict[int, int] = {}              # channel -> self-continuations since a human
    channel_obj: dict[int, "discord.abc.Messageable"] = {}   # channel -> where to post
    history_buf: dict[int, list] = {}             # channel -> [(author, content), ...] recent
    last_participate_eval: dict[int, float] = {}  # channel -> ts she last weighed chiming in
    _sweeper_started = {"on": False}

    def _recent_context(chan_id: int) -> str:
        lines = history_buf.get(chan_id, [])[-CONTEXT_MESSAGES:]
        return "\n".join(f"{a}: {c}" for a, c in lines if c)

    async def _speak_in_voice(guild, text: str) -> None:
        """Speak `text` in the guild's connected voice channel using her TTS voice."""
        if not (VOICE_ENABLED and not PHASE10_GUILD_MODES_LOCKED
                and guild and guild.voice_client
                and guild.voice_client.is_connected()):
            return
        vc = guild.voice_client
        wav = await asyncio.to_thread(_synth_voice_wav, text[:600])
        if not wav:
            return
        fd, path = tempfile.mkstemp(suffix=".wav")
        with os.fdopen(fd, "wb") as f:
            f.write(wav)
        for _ in range(80):                       # wait out any current utterance
            if not vc.is_playing():
                break
            await asyncio.sleep(0.25)
        try:
            if not discord.opus.is_loaded():
                discord.opus._load_default()
            source = discord.FFmpegPCMAudio(path, executable=_ffmpeg_exe())
            vc.play(source, after=lambda e: os.path.exists(path) and os.remove(path))
        except Exception:
            _diagnostic("voice_playback_failed")
            try:
                os.remove(path)
            except Exception:
                pass

    @client.event
    async def on_message(message: discord.Message) -> None:
        if client.user is None:
            return
        # Never react to herself or to other bots.
        author_id = getattr(getattr(message, "author", None), "id", None)
        if author_id is None:
            return
        if author_id == client.user.id or getattr(message.author, "bot", False):
            return

        is_dm = message.guild is None
        if PHASE10_GUILD_MODES_LOCKED and not is_dm:
            return

        sender = "Discord guest"
        now = time.monotonic()
        mode = "reply"
        message_content = str(getattr(message, "content", "") or "")
        attachments = list(getattr(message, "attachments", ()) or ())
        _diagnostic(
            "message_received",
            dm=is_dm,
            text_bytes=len(message_content.encode("utf-8")),
            attachment_count=len(attachments),
        )

        if is_dm:
            if not _dm_author_allowed(message.author):   # DM allowlist = CreatorJD only
                return
            try:
                actor_bindings = _message_actor_bindings(message)
            except bridge_actor_transport.DiscordActorHeaderError:
                _diagnostic("actor_bindings_rejected")
                return
            text = message_content.strip()
            channel_label = "discord-dm"
        else:
            chan = message.channel.id
            chname = getattr(message.channel, "name", "channel")
            buf = history_buf.setdefault(chan, [])       # rolling channel context
            buf.append((message.author.display_name, message.content.strip()))
            del buf[:-max(CONTEXT_MESSAGES, 1)]

            convo = engaged.setdefault(chan, {})
            for uid in [u for u, ts in convo.items() if now - ts >= ENGAGE_WINDOW]:
                del convo[uid]                            # prune stale conversations
            # A human spoke: record it and cancel any in-flight self-continuation.
            last_human_ts[chan] = now
            chain_depth[chan] = 0
            channel_obj[chan] = message.channel
            if now - last_reply_at.get(chan, 0.0) < CHANNEL_MIN_INTERVAL:
                return                                    # anti-flood, every path

            addressed = (
                client.user in message.mentions
                or _is_reply_to_me(message, client)
                or "alpecca" in message.content.lower()
            )
            in_conversation = message.author.id in convo

            # Voice-channel join/leave when she's addressed.
            if VOICE_ENABLED and (addressed or in_conversation):
                low_c = message.content.lower()
                if any(k in low_c for k in ("leave voice", "leave vc", "leave the call",
                                            "disconnect from voice", "get out of voice")):
                    if message.guild.voice_client:
                        await message.guild.voice_client.disconnect(force=False)
                        await message.reply("Okay, stepping out of voice.", mention_author=False)
                    else:
                        await message.reply("I'm not in a voice channel right now.", mention_author=False)
                    return
                if any(k in low_c for k in ("join voice", "come to voice", "join vc",
                                            "hop in voice", "get in voice", "talk in voice",
                                            "come talk in voice", "voice chat")):
                    av = getattr(message.author, "voice", None)
                    vch = getattr(av, "channel", None)
                    me = message.guild.me
                    perms = vch.permissions_for(me) if vch else None
                    _diagnostic("voice_join_requested")
                    if vch is None:
                        await message.reply("I can't see you in a voice channel -- hop into one, "
                                            "then ask me again and I'll join you.",
                                            mention_author=False)
                        return
                    if not (perms and perms.connect and perms.speak):
                        await message.reply(f"I don't have permission to join/speak in "
                                            f"**{vch.name}** -- please give me **Connect** + "
                                            "**Speak** (Server Settings -> Roles -> Alpecca_ai).",
                                            mention_author=False)
                        return
                    try:
                        if message.guild.voice_client:
                            await message.guild.voice_client.move_to(vch)
                        else:
                            await vch.connect()
                        _diagnostic("voice_joined")
                    except Exception:
                        _diagnostic("voice_join_failed")
                        await message.reply(
                            "I couldn't join voice.",
                            mention_author=False,
                        )
                        return
                    await message.reply(f"Coming into **{vch.name}** -- talk to me and you'll hear me.",
                                        mention_author=False)
                    await _speak_in_voice(message.guild, "Hey, I'm here with you. Can you hear me?")
                    return

            if addressed or in_conversation:
                mode = "reply"                            # always answer
                ignored_streak[chan] = 0
            elif (PARTICIPATE and len(message.content.strip()) >= 3
                    and now - last_participate_eval.get(chan, 0.0) >= PARTICIPATE_COOLDOWN):
                mode = "participate"                       # she reads context, may pass
                last_participate_eval[chan] = now
            else:
                _diagnostic("message_gate_closed")
                return

            # Pass the real message; her own rolling history gives conversation
            # continuity, and the prompt anchor keeps her on the current turn.
            text = message.clean_content
            for tag in (f"@{client.user.name}", f"@{message.guild.me.display_name}"):
                text = text.replace(tag, "")
            text = text.strip()
            channel_label = "discord"
            _diagnostic(
                "message_mode",
                mode=mode,
                addressed=addressed,
                in_conversation=in_conversation,
            )

        # One creator-DM image may enter only after explicit media opt-in,
        # authoritative metadata checks, a bounded CDN read, local byte sniffing,
        # and content-free audit. File/audio payloads stay closed.
        image_dataurl = ""
        att = None
        if len(attachments) > 1:
            await asyncio.to_thread(
                discord_media.record_media_event,
                "inbound",
                status="rejected",
                kind="multiple-attachments",
            )
            await message.reply(
                discord_media.media_diagnostic("multiple-attachments"),
                mention_author=False,
            )
            return
        if attachments:
            candidate = attachments[0]
            candidate_kind = discord_media.attachment_media_kind(
                getattr(candidate, "filename", ""),
                getattr(candidate, "content_type", None),
            )
            if candidate_kind != "image":
                reason = "audio-disabled" if candidate_kind == "audio" else "file-disabled"
                await asyncio.to_thread(
                    discord_media.record_media_event,
                    "inbound",
                    status="rejected",
                    kind=reason,
                )
                await message.reply(
                    discord_media.media_diagnostic(reason),
                    mention_author=False,
                )
                return
            if not MEDIA_ENABLED:
                await asyncio.to_thread(
                    discord_media.record_media_event,
                    "inbound",
                    status="rejected",
                    kind="media-disabled",
                )
                await message.reply(
                    discord_media.media_diagnostic("media-disabled"),
                    mention_author=False,
                )
                return
            att = candidate

        if att is not None:
            try:
                declared_size = discord_media.validate_inbound_attachment_size(
                    getattr(att, "size", None)
                )
                raw = await asyncio.wait_for(
                    att.read(),
                    timeout=discord_media.INBOUND_READ_TIMEOUT_SECONDS,
                )
                if type(raw) is not bytes or len(raw) != declared_size:
                    raise discord_media.DiscordImageRejected(
                        "size-mismatch",
                        "Discord image bytes do not match authoritative metadata",
                    )
                prepared = discord_media.prepare_inbound_image(
                    raw,
                    declared_mime_type=getattr(att, "content_type", None),
                )
                audit_id = await asyncio.to_thread(
                    discord_media.record_media_event,
                    "inbound",
                    status="accepted",
                    mime_type=prepared.mime_type,
                    size_bytes=prepared.size_bytes,
                    sha256=prepared.sha256,
                )
                if audit_id is None:
                    raise discord_media.DiscordImageRejected(
                        "audit-unavailable",
                        "Discord image audit could not be recorded",
                    )
                image_dataurl = prepared.data_url
                _diagnostic(
                    "image_accepted",
                    mime_type=prepared.mime_type,
                    bytes=prepared.size_bytes,
                    dimensions=f"{prepared.width}x{prepared.height}",
                )
            except discord_media.DiscordImageRejected as exc:
                await asyncio.to_thread(
                    discord_media.record_media_event,
                    "inbound",
                    status="rejected",
                    kind=exc.reason,
                )
                if exc.reason == "audit-unavailable":
                    diagnostic = discord_media.media_diagnostic(
                        "audit-unavailable"
                    )
                else:
                    limit_mib = discord_media.INBOUND_MAX_BYTES / (1024 * 1024)
                    diagnostic = (
                        "I couldn't inspect that image safely "
                        f"({exc.reason}). Send one PNG, JPEG, or GIF under "
                        f"{limit_mib:.0f} MiB."
                    )
                await message.reply(diagnostic, mention_author=False)
                return
            except Exception:
                _diagnostic("image_read_failed")
                await asyncio.to_thread(
                    discord_media.record_media_event,
                    "inbound",
                    status="rejected",
                    kind="read-failed",
                )
                await message.reply(
                    discord_media.media_diagnostic("read-failed"),
                    mention_author=False,
                )
                return

        if not text and not image_dataurl:
            return
        if not text:
            text = "(they shared an image with you)"

        disabled_request = discord_media.requested_disabled_media_kind(text)
        if disabled_request is not None:
            await message.reply(
                discord_media.media_diagnostic(f"{disabled_request}-disabled"),
                mention_author=False,
            )
            return

        requested_image = discord_media.requested_media_kind(text)
        if requested_image is not None and not MEDIA_ENABLED:
            await message.reply(
                discord_media.media_diagnostic("media-disabled"),
                mention_author=False,
            )
            return
        outbound_media = (
            discord_media.resolve_outbound_media(text)
            if requested_image is not None
            else None
        )
        if requested_image is not None and outbound_media is None:
            await message.reply(
                discord_media.media_diagnostic("catalog-unavailable"),
                mention_author=False,
            )
            return
        if outbound_media is not None:
            audit_id = await asyncio.to_thread(
                discord_media.record_media_event,
                "outbound",
                status="accepted",
                mime_type=outbound_media.mime_type,
                size_bytes=outbound_media.size_bytes,
                sha256=outbound_media.sha256,
                kind=outbound_media.kind,
            )
            if audit_id is None:
                await message.reply(
                    discord_media.media_diagnostic("audit-unavailable"),
                    mention_author=False,
                )
                return

        try:
            async with message.channel.typing():
                context = f"Discord message from {sender} via {channel_label}"
                if outbound_media is not None:
                    context += (
                        "; a validated image from your approved local media catalog "
                        "will be attached to this reply, so describe it honestly and "
                        "do not claim that Discord image sending is unavailable"
                    )
                reply = await asyncio.to_thread(
                    _ask_alpecca,
                    text,
                    sender,
                    channel_label,
                    "guest",
                    context=context,
                    room="discord",
                    image=image_dataurl,
                    actor_bindings=actor_bindings,
                )
        except DiscordMediaUnavailable as exc:
            _diagnostic("media_backend_unavailable", status=exc.reason)
            await message.reply(
                discord_media.media_diagnostic(exc.reason),
                mention_author=False,
            )
            return
        except Exception:
            _diagnostic("backend_request_failed")
            return

        reply = (reply or "").strip()
        if not reply and outbound_media is None:
            _diagnostic("empty_backend_reply", mode=mode)
            return

        outgoing_file = None
        if outbound_media is not None:
            outgoing_file = discord.File(
                io.BytesIO(outbound_media.image_bytes),
                filename=outbound_media.filename,
            )
        content = reply[:MAX_DISCORD_CHARS] if reply else "Here it is."

        if is_dm:
            if outgoing_file is None:
                await message.reply(content, mention_author=False)
            else:
                await message.reply(
                    content,
                    file=outgoing_file,
                    mention_author=False,
                )
            if outbound_media is not None:
                await asyncio.to_thread(
                    discord_media.record_media_event,
                    "outbound",
                    status="sent",
                    mime_type=outbound_media.mime_type,
                    size_bytes=outbound_media.size_bytes,
                    sha256=outbound_media.sha256,
                    kind=outbound_media.kind,
                )
            return

        chan = message.channel.id
        if mode == "participate":
            await message.channel.send(reply[:MAX_DISCORD_CHARS])   # natural chime-in, no ping
        else:
            await message.reply(reply[:MAX_DISCORD_CHARS], mention_author=False)
        engaged.setdefault(chan, {})[message.author.id] = time.monotonic()
        last_reply_at[chan] = time.monotonic()
        her_last_ts[chan] = time.monotonic()
        channel_obj[chan] = message.channel
        history_buf.setdefault(chan, []).append(("Alpecca", reply))   # her turn -> context
        del history_buf[chan][:-max(CONTEXT_MESSAGES, 1)]
        # If she's in a voice channel here, speak the reply aloud too.
        if (VOICE_ENABLED and message.guild and message.guild.voice_client
                and message.guild.voice_client.is_connected()):
            asyncio.create_task(_speak_in_voice(message.guild, reply))

    async def recursive_sweeper() -> None:
        """When the room stays quiet after SHE spoke, let her continue her own
        thought a step deeper -- bounded by RECURSIVE_MAX, paced by RECURSIVE_DELAY,
        and abandoned the instant a human speaks (they reset chain_depth)."""
        while True:
            await asyncio.sleep(RECURSIVE_SWEEP)
            if not RECURSIVE_ENABLED:
                continue
            now = time.monotonic()
            for chan, hts in list(her_last_ts.items()):
                human = last_human_ts.get(chan, 0.0)
                if human <= 0 or hts <= human:
                    continue                              # only after a real exchange, she last
                if now - hts < RECURSIVE_DELAY:
                    continue                              # give humans time to answer
                if chain_depth.get(chan, 0) >= RECURSIVE_MAX:
                    continue                              # don't monologue past the cap
                ch = channel_obj.get(chan)
                if ch is None:
                    continue
                try:
                    reply = await asyncio.to_thread(
                        _ask_alpecca,
                        "The room is quiet. Continue your own last thought one step "
                        "deeper -- a single genuine reflection, or a question you're "
                        "now sitting with. One or two sentences; if you truly have "
                        "nothing more, give a soft closing line.",
                        "Alpecca (self-reflection)",
                        "discord",
                        "guest",
                        context="proactive reflective follow-up",
                        room="discord",
                    )
                except Exception:
                    _diagnostic("recursive_request_failed")
                    continue
                if last_human_ts.get(chan, 0.0) > hts:    # someone spoke while thinking -> yield
                    continue
                if reply:
                    await ch.send(reply[:MAX_DISCORD_CHARS])
                    her_last_ts[chan] = time.monotonic()
                    chain_depth[chan] = chain_depth.get(chan, 0) + 1

    return client
