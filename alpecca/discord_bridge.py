"""Alpecca's Discord presence: a thin, bounded bridge to her mind.

She runs as a proper Discord **bot** (never a self-bot). A message she is allowed
to hear is forwarded to `POST /channel/inbound` -> her normal chat path (mood +
memory + people + affect) -> her reply is posted back in her own voice.

Phase 1 scope = reactive only, with the locked safety rails from
`docs/ALPECCA_DISCORD_PRESENCE.md`:

  - **Channels:** she replies when *addressed* -- @mentioned, replied-to, or called
    by name -- and then stays "in the conversation" for a short window so follow-ups
    need no re-mention (natural back-and-forth, not an answering machine). She may
    also **chime in unprompted**, but only on relevant openings (a question or a
    substantive message), only sometimes, and behind a long per-channel cooldown
    that *backs off further whenever a chime-in is ignored* -- so butting in stays
    natural, never spammy. An anti-flood cooldown caps her rate per channel.
  - **DMs:** allowlist only. She answers DMs *only* from CreatorJD
    (`ALPECCA_DISCORD_DM_ALLOW` = comma-separated Discord user ids or unique
    usernames). Empty = no DMs. One byte-validated image can enter her vision;
    explicit image requests can attach one item from her closed local catalog.
  - She never replies to herself or to other bots.
  - Everyone in a channel is a guest to her people-layer; her mind stays
    courteously guarded with strangers on its own.

Run it with `python scripts/run_discord_bridge.py` (loads the gitignored token).
Her backend (`server.py`) must be running so `/channel/inbound` is reachable.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import random
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path

import discord

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpecca.auth import AUTHORIZATION_HEADER, load_or_create_authorization_secret
from alpecca import discord_media
from config import HOME, HOST, PORT, PUBLIC_URL


_AUTHORIZATION_SECRET = load_or_create_authorization_secret(HOME)

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
DM_ALLOW = {s.strip() for s in os.environ.get("ALPECCA_DISCORD_DM_ALLOW", "").split(",") if s.strip()}
# The allowlist accepts numeric user ids AND usernames (e.g. "realcreatorjd").
# Usernames resolve to ids lazily on first contact (the DM itself carries the
# author's name) and eagerly on_ready via a guild member query; resolved ids
# are cached so later checks are direct.
DM_ALLOW_IDS = {entry for entry in DM_ALLOW if entry.isdigit()}
DM_ALLOW_NAMES = {entry.casefold() for entry in DM_ALLOW if entry and not entry.isdigit()}


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
        print(f"[discord] dm_allow resolved: {getattr(author, 'name', '?')} -> {author_id}", flush=True)
        return True
    return False
INBOUND_TIMEOUT = float(os.environ.get("ALPECCA_DISCORD_INBOUND_TIMEOUT", "45"))
IMAGE_INBOUND_TIMEOUT = max(
    INBOUND_TIMEOUT,
    float(os.environ.get("ALPECCA_DISCORD_IMAGE_TIMEOUT", "300")),
)
MAX_DISCORD_CHARS = 2000
# How long she stays "in conversation" in a channel after being addressed, so
# follow-ups don't need a re-mention (natural back-and-forth).
ENGAGE_WINDOW = float(os.environ.get("ALPECCA_DISCORD_ENGAGE_WINDOW", "90"))

# Minimum seconds between her messages in one channel (anti-flood safety).
CHANNEL_MIN_INTERVAL = float(os.environ.get("ALPECCA_DISCORD_MIN_INTERVAL", "1.5"))
# Natural, unprompted chime-in ("butting in"): only on relevant openings, only
# sometimes, and with a long per-channel cooldown that backs off further whenever
# a chime-in goes unanswered -- so it reads as a person occasionally joining, not
# a bot reacting to everything.
PROACTIVE_ENABLED = os.environ.get("ALPECCA_DISCORD_PROACTIVE", "0") not in ("", "0", "false", "False")
PROACTIVE_COOLDOWN = float(os.environ.get("ALPECCA_DISCORD_PROACTIVE_COOLDOWN", "480"))
PROACTIVE_CHANCE = float(os.environ.get("ALPECCA_DISCORD_PROACTIVE_CHANCE", "0.3"))
PROACTIVE_MIN_LEN = int(os.environ.get("ALPECCA_DISCORD_PROACTIVE_MIN_LEN", "40"))
# Recursive self-continuation: when the room goes quiet after SHE spoke, she may
# continue her own train of thought a little deeper -- bounded, paced, and it
# yields the instant any human speaks, so it never becomes a monologue/spam.
RECURSIVE_ENABLED = os.environ.get("ALPECCA_DISCORD_RECURSIVE", "0") not in ("", "0", "false", "False")
RECURSIVE_MAX = int(os.environ.get("ALPECCA_DISCORD_RECURSIVE_MAX", "2"))       # self-steps before waiting for a human
RECURSIVE_DELAY = float(os.environ.get("ALPECCA_DISCORD_RECURSIVE_DELAY", "75"))  # quiet seconds before she continues
RECURSIVE_SWEEP = float(os.environ.get("ALPECCA_DISCORD_RECURSIVE_SWEEP", "20"))  # how often the loop checks
DEBUG = os.environ.get("ALPECCA_DISCORD_DEBUG", "1") not in ("", "0", "false", "False")
# Contextual participation: she reads the recent channel conversation and may
# speak WITHOUT being mentioned -- but she decides per message whether she has
# something worth adding (she can choose "(pass)"), throttled so it isn't spam.
PARTICIPATE = os.environ.get("ALPECCA_DISCORD_PARTICIPATE", "0") not in ("", "0", "false", "False")
PARTICIPATE_COOLDOWN = float(os.environ.get("ALPECCA_DISCORD_PARTICIPATE_COOLDOWN", "45"))  # min secs between unprompted weigh-ins
CONTEXT_MESSAGES = int(os.environ.get("ALPECCA_DISCORD_CONTEXT", "8"))                        # recent msgs given as context
# Voice chat: she can join a voice channel (on request) and SPEAK her replies with
# her real TTS voice. Bots stream audio (supported); video/camera is not possible.
VOICE_ENABLED = os.environ.get("ALPECCA_DISCORD_VOICE", "0") not in ("", "0", "false", "False")


def _is_reply_to_me(message: "discord.Message", client: "discord.Client") -> bool:
    """True if `message` is a Discord reply to one of Alpecca's own messages."""
    ref = message.reference
    resolved = getattr(ref, "resolved", None) if ref else None
    author = getattr(resolved, "author", None)
    return bool(author and client.user and author.id == client.user.id)


def _ask_alpecca(text: str, sender: str, channel: str,
                 speaker: str = "guest",
                 context: str = "", room: str = "", image: str = "") -> str:
    """Forward one message to her mind via /channel/inbound; return her reply.

    `image` (optional) is a data-URL of an attached picture; the backend runs it
    through her vision + self-recognition. Raw document uploads are deliberately
    not part of this bridge contract. Blocking (urllib); callers run it off the
    event loop via asyncio.to_thread.
    """
    body_obj = {
        "text": text,
        "sender": sender,
        "channel": channel,
        "situation": context,
        "context": context,
        "room": room,
        "speaker": speaker if speaker in {"creator", "guest"} else "guest",
    }
    if image:
        body_obj["image"] = image
    body = json.dumps(body_obj).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        AUTHORIZATION_HEADER: _AUTHORIZATION_SECRET,
    }
    req = urllib.request.Request(
        f"{BACKEND_URL}/channel/discord",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        timeout = IMAGE_INBOUND_TIMEOUT if image else INBOUND_TIMEOUT
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="ignore") if exc.fp else str(exc)
        raise RuntimeError(f"alpecca backend returned {exc.code}: {detail}") from None
    except Exception as exc:
        raise RuntimeError(f"alpecca bridge failed: {type(exc).__name__}: {exc}") from None
    return str(payload.get("reply") or "").strip()


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
    body = json.dumps({"text": text}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        AUTHORIZATION_HEADER: _AUTHORIZATION_SECRET,
    }
    req = urllib.request.Request(f"{BACKEND_URL}/tts", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=INBOUND_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            data = resp.read()
    except Exception as exc:
        print(f"[discord] voice synth failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    return data if (data and len(data) > 1024) else None


def build_client() -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True   # needed to read message text (also enable in the portal)
    intents.voice_states = True      # needed to see which voice channel a member is in
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        try:
            if VOICE_ENABLED and not discord.opus.is_loaded():
                discord.opus._load_default()
        except Exception as exc:
            print(f"[discord] opus load failed (voice off): {exc}", file=sys.stderr)
        try:
            import discord.voice_client as _vc
            try:
                import davey as _davey
                _davey_ok = getattr(_davey, "__version__", "yes")
            except Exception:
                _davey_ok = "MISSING"
            print(f"[discord] voice caps: has_nacl={_vc.has_nacl}, "
                  f"opus_loaded={discord.opus.is_loaded()}, davey={_davey_ok}",
                  file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"[discord] voice caps check failed: {exc}", file=sys.stderr, flush=True)
        # Resolve username allowlist entries to ids up front so DM permission
        # does not depend on the member cache. A non-empty query does not need
        # the privileged members intent; failure just leaves lazy resolution.
        for guild in client.guilds:
            for wanted in list(DM_ALLOW_NAMES):
                try:
                    members = await guild.query_members(query=wanted, limit=5)
                except Exception as exc:
                    print(f"[discord] dm_allow lookup failed for {wanted}: {exc}",
                          file=sys.stderr, flush=True)
                    continue
                for member in members:
                    if wanted == member.name.casefold():
                        DM_ALLOW_IDS.add(str(member.id))
                        print(f"[discord] dm_allow resolved: {wanted} -> {member.id}", flush=True)
        print(f"[discord] online as {client.user} in {len(client.guilds)} server(s); "
              f"backend={BACKEND_URL}; "
              f"dm_allow={sorted(DM_ALLOW_IDS | DM_ALLOW_NAMES) or 'none'}", flush=True)
        if not _sweeper_started["on"]:
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
        if not (VOICE_ENABLED and guild and guild.voice_client
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
        except Exception as exc:
            print(f"[discord] voice play failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            try:
                os.remove(path)
            except Exception:
                pass

    @client.event
    async def on_message(message: discord.Message) -> None:
        if client.user is None:
            return
        # Never react to herself or to other bots.
        if message.author.id == client.user.id or message.author.bot:
            return

        is_dm = message.guild is None
        sender = f"{message.author.name} (discord:{message.author.id})"
        now = time.monotonic()
        mode = "reply"
        if DEBUG:
            print(f"[discord] recv dm={is_dm} from={message.author} "
                  f"content={message.content!r}", file=sys.stderr, flush=True)

        if is_dm:
            if not _dm_author_allowed(message.author):   # DM allowlist = CreatorJD only
                return
            text = message.content.strip()
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
                    print(f"[discord] voice-join req: user_channel={vch}, "
                          f"connect={getattr(perms, 'connect', None)}, "
                          f"speak={getattr(perms, 'speak', None)}", file=sys.stderr, flush=True)
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
                        print(f"[discord] joined voice channel {vch.name}", file=sys.stderr, flush=True)
                    except Exception as exc:
                        print(f"[discord] voice join FAILED: {type(exc).__name__}: {exc}",
                              file=sys.stderr, flush=True)
                        await message.reply(f"I couldn't join voice: {exc}", mention_author=False)
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
                if DEBUG:
                    print("[discord] gate -> stay quiet", file=sys.stderr, flush=True)
                return

            # Pass the real message; her own rolling history gives conversation
            # continuity, and the prompt anchor keeps her on the current turn.
            text = message.clean_content
            for tag in (f"@{client.user.name}", f"@{message.guild.me.display_name}"):
                text = text.replace(tag, "")
            text = text.strip()
            channel_label = "discord"
            if DEBUG:
                print(f"[discord] mode={mode} addressed={addressed} in_convo={in_conversation}",
                      file=sys.stderr, flush=True)

        # Creator DM images are locally sniffed and bounded before her normal
        # vision path sees them. Guild media stays closed until Discord actors
        # have a server-verifiable guest identity instead of the bridge's shared
        # backend credential.
        image_dataurl = ""
        att = next((a for a in message.attachments
                    if discord_media.looks_like_image_attachment(
                        a.filename, a.content_type)), None)
        if att is not None and is_dm:
            try:
                if int(getattr(att, "size", 0) or 0) > discord_media.INBOUND_MAX_BYTES:
                    raise discord_media.DiscordImageRejected(
                        "size-limit",
                        "Discord image exceeds the local perception byte limit",
                    )
                raw = await att.read()
                prepared = discord_media.prepare_inbound_image(
                    raw,
                    declared_mime_type=att.content_type,
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
                if DEBUG:
                    print(
                        f"[discord] image accepted mime={prepared.mime_type} "
                        f"bytes={prepared.size_bytes} dimensions="
                        f"{prepared.width}x{prepared.height}",
                        file=sys.stderr,
                        flush=True,
                    )
            except discord_media.DiscordImageRejected as exc:
                await asyncio.to_thread(
                    discord_media.record_media_event,
                    "inbound",
                    status="rejected",
                    kind=exc.reason,
                )
                limit_mib = discord_media.INBOUND_MAX_BYTES / (1024 * 1024)
                await message.reply(
                    "I couldn't inspect that image safely "
                    f"({exc.reason}). Send one PNG, JPEG, or GIF under "
                    f"{limit_mib:.0f} MiB.",
                    mention_author=False,
                )
                return
            except Exception as exc:
                print(f"[discord] image read failed: {type(exc).__name__}: {exc}",
                      file=sys.stderr)
                await message.reply(
                    "I couldn't read that image from Discord. Please send it again.",
                    mention_author=False,
                )
                return
        elif att is not None and not is_dm:
            if not text:
                await message.reply(
                    "I only inspect images in CreatorJD's direct messages right now.",
                    mention_author=False,
                )
                return

        if not text and not image_dataurl:
            if message.attachments:
                await message.reply(
                    "Discord document uploads are not enabled. I can inspect one "
                    "PNG, JPEG, or GIF in CreatorJD's direct messages; use House "
                    "HQ Files for source documents.",
                    mention_author=False,
                )
            return
        if not text:
            text = "(they shared an image with you)"

        outbound_media = discord_media.resolve_outbound_media(text) if is_dm else None
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
                outbound_media = None

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
                    "creator" if is_dm else "guest",
                    context=context,
                    room="discord",
                    image=image_dataurl,
                )
        except Exception as exc:
            print(f"[discord] backend error: {type(exc).__name__}: {exc}", file=sys.stderr)
            if outbound_media is not None:
                reply = f"Here is my {outbound_media.kind} image."
            elif image_dataurl:
                await message.reply(
                    "I received the image, but my vision pass did not return a "
                    "usable result. I won't pretend I saw details that were not "
                    "returned.",
                    mention_author=False,
                )
                return
            else:
                return

        reply = (reply or "").strip()
        if not reply and outbound_media is None:
            if DEBUG:
                print(f"[discord] -> silent (mode={mode})", file=sys.stderr, flush=True)
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
                except Exception as exc:
                    print(f"[discord] recursive error: {type(exc).__name__}: {exc}", file=sys.stderr)
                    continue
                if last_human_ts.get(chan, 0.0) > hts:    # someone spoke while thinking -> yield
                    continue
                if reply:
                    await ch.send(reply[:MAX_DISCORD_CHARS])
                    her_last_ts[chan] = time.monotonic()
                    chain_depth[chan] = chain_depth.get(chan, 0) + 1

    return client
