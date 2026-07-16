"""Alpecca's Discord presence: a thin, bounded bridge to her mind.

She runs as a proper Discord **bot** (never a self-bot). A message she is allowed
to hear is forwarded to `POST /channel/discord` -> her bounded guest chat path
(mood +
memory + people + affect) -> her reply is posted back in her own voice.

Current Phase 10 scope = creator-allowlisted DMs plus explicitly claimed guild
rooms, with the bounded rails from `docs/ALPECCA_DISCORD_PRESENCE.md`:

  - **Guilds:** fail closed until CreatorJD sends the exact raw mention command
    ``<@bot-id> room on`` in that channel. ``room off`` removes the durable claim.
    Claimed rooms have bounded context, cooldowns, one recursive continuation,
    and no creator authority in the backend.
  - **DMs:** allowlist only. She answers DMs *only* from CreatorJD
    (`ALPECCA_DISCORD_DM_ALLOW` = comma-separated Discord user ids or unique
    usernames). Empty = no DMs. One byte-validated image can enter her vision;
    explicit image requests can attach one item from her closed local catalog.
  - She never replies to herself or to other bots.
  - **Voice:** when ``ALPECCA_DISCORD_VOICE=1``, she can join a voice channel
    from a claimed room and speak her text turns with local TTS. With
    ``ALPECCA_DISCORD_VOICE_RECEIVE=1`` and the optional receive dependency,
    human participants' decoded audio is held briefly in memory, transcribed
    locally, answered as guest authority, and discarded. Bounded transcripts
    are retained only in the AES-GCM encrypted voice-memory store.
  - Everyone in a channel is a guest to her people-layer; her mind stays
    courteously guarded with strangers on its own.

Run it with `python scripts/run_discord_bridge.py` (loads the gitignored token).
Her backend (`server.py`) must be running so `/channel/discord` is reachable.
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import ipaddress
import io
import json
import os
import random
import re
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
from alpecca import (
    audio_ingress,
    bridge_actor_transport,
    discord_media,
    discord_observability,
    discord_room_state,
    discord_voice,
    discord_voice_memory,
    hearing,
)
from alpecca.prompts import discord_presence_prompt
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
VOICE_SYNTH_TIMEOUT = max(
    15.0,
    min(180.0, float(os.environ.get("ALPECCA_DISCORD_VOICE_TIMEOUT", "105"))),
)
DISCORD_VOICE_ENGINE = os.environ.get(
    "ALPECCA_DISCORD_TTS_ENGINE", "kokoro"
).strip().lower()
if DISCORD_VOICE_ENGINE not in {"auto", "kokoro", "f5", "f5-tts"}:
    DISCORD_VOICE_ENGINE = "kokoro"
MAX_DISCORD_CHARS = 2000
MAX_BACKEND_RESPONSE_BYTES = 1024 * 1024
MAX_BACKEND_ERROR_BYTES = 16 * 1024
MAX_VOICE_RESPONSE_BYTES = 16 * 1024 * 1024
# Public-room presence is opt-in per room. The creator claims a room with
# ``@Alpecca room on``; no environment flag can make her read or speak in an
# arbitrary server channel.
PHASE10_GUILD_MODES_LOCKED = False
DISCORD_ROOM_REGISTRY = HOME / "discord_social_rooms.json"
SOCIAL_HISTORY_LIMIT = max(4, min(20, int(os.environ.get("ALPECCA_DISCORD_CONTEXT", "12"))))
# How long she stays "in conversation" in a channel after being addressed, so
# follow-ups don't need a re-mention (natural back-and-forth).
ENGAGE_WINDOW = float(os.environ.get("ALPECCA_DISCORD_ENGAGE_WINDOW", "90"))

# Minimum seconds between her messages in one channel (anti-flood safety).
CHANNEL_MIN_INTERVAL = float(os.environ.get("ALPECCA_DISCORD_MIN_INTERVAL", "1.5"))
# Natural, unprompted chime-in ("butting in"): only on relevant openings, only
# sometimes, and with a long per-channel cooldown that backs off further whenever
# a chime-in goes unanswered -- so it reads as a person occasionally joining, not
# a bot reacting to everything.
PROACTIVE_ENABLED = True
PROACTIVE_COOLDOWN = max(
    60.0,
    float(os.environ.get("ALPECCA_DISCORD_PROACTIVE_COOLDOWN", "180")),
)
PROACTIVE_CHANCE = max(
    0.0,
    min(1.0, float(os.environ.get("ALPECCA_DISCORD_PROACTIVE_CHANCE", "0.65"))),
)
PROACTIVE_MIN_LEN = int(os.environ.get("ALPECCA_DISCORD_PROACTIVE_MIN_LEN", "40"))
PROACTIVE_QUIET_MIN = max(
    30.0,
    float(os.environ.get("ALPECCA_DISCORD_PROACTIVE_QUIET_MIN", "60")),
)
PROACTIVE_SWEEP = max(
    10.0,
    float(os.environ.get("ALPECCA_DISCORD_PROACTIVE_SWEEP", "20")),
)
PROACTIVE_GLOBAL_COOLDOWN = max(
    30.0,
    float(os.environ.get("ALPECCA_DISCORD_PROACTIVE_GLOBAL_COOLDOWN", "60")),
)
# A claimed room may get one deliberate check-in after a genuinely long pause,
# but never a rapid sequence of self-directed messages.  This is distinct from
# a follow-up earned by a new human turn.
EMPTY_ROOM_NUDGE_QUIET = max(
    60.0 * 60.0,
    float(os.environ.get("ALPECCA_DISCORD_EMPTY_ROOM_NUDGE_QUIET", "14400")),
)
# Recursive self-continuation: when the room goes quiet after SHE spoke, she may
# continue her own train of thought a little deeper -- bounded, paced, and it
# yields the instant any human speaks, so it never becomes a monologue/spam.
RECURSIVE_ENABLED = True
# One quiet-time follow-up is enough to feel present without allowing a
# self-monologue. A human message resets the allowance.
RECURSIVE_MAX = 1
RECURSIVE_DELAY = max(45.0, float(os.environ.get("ALPECCA_DISCORD_RECURSIVE_DELAY", "90")))
RECURSIVE_SWEEP = float(os.environ.get("ALPECCA_DISCORD_RECURSIVE_SWEEP", "20"))  # how often the loop checks
# Diagnostics contain only allowlisted event labels and bounded scalar metadata.
# Keep them on by default so a live bridge cannot fail silently; deployments may
# still opt out explicitly with ALPECCA_DISCORD_DEBUG=0.
DEBUG = os.environ.get("ALPECCA_DISCORD_DEBUG", "1").strip().lower() not in {
    "", "0", "false", "no", "off",
}
# Contextual participation: she reads the recent channel conversation and may
# speak WITHOUT being mentioned -- but she decides per message whether she has
# something worth adding (she can choose "(pass)"), throttled so it isn't spam.
PARTICIPATE = True
PARTICIPATE_COOLDOWN = max(30.0, float(os.environ.get("ALPECCA_DISCORD_PARTICIPATE_COOLDOWN", "75")))
CONTEXT_MESSAGES = SOCIAL_HISTORY_LIMIT
# Voice output is independently useful. Receive is a second explicit switch,
# starts only on a creator command in a claimed room, and then hears bounded
# human-participant utterances. Audio processing stays local and fail-closed.
VOICE_ENABLED = _environment_enabled("ALPECCA_DISCORD_VOICE")
VOICE_RECEIVE_ENABLED = VOICE_ENABLED and _environment_enabled(
    "ALPECCA_DISCORD_VOICE_RECEIVE"
)
VOICE_MEMORY_ENABLED = VOICE_RECEIVE_ENABLED and os.environ.get(
    "ALPECCA_DISCORD_VOICE_MEMORY", "1"
).strip().lower() not in {"", "0", "false", "no", "off"}
VOICE_RECEIVE_QUEUE_LIMIT = 2
MAX_VOICE_TRANSCRIPT_CHARS = 2_000
VOICE_MEMORY_MAX_RECORDS = max(
    32,
    min(
        100_000,
        int(os.environ.get("ALPECCA_DISCORD_VOICE_MEMORY_LIMIT", "10000")),
    ),
)

_voice_memory_lock = threading.Lock()
_voice_memory_instance: discord_voice_memory.EncryptedVoiceMemoryStore | None = None


def _voice_memory_store() -> discord_voice_memory.EncryptedVoiceMemoryStore | None:
    global _voice_memory_instance
    if not VOICE_MEMORY_ENABLED:
        return None
    with _voice_memory_lock:
        if _voice_memory_instance is None:
            _voice_memory_instance = discord_voice_memory.EncryptedVoiceMemoryStore(
                HOME / "discord_voice_memory.db",
                secret=_BRIDGE_AUTHORIZATION_SECRET,
                max_records=VOICE_MEMORY_MAX_RECORDS,
            )
        return _voice_memory_instance


def _recent_voice_context(guild_id: int, channel_id: int) -> list[tuple[str, str]]:
    store = _voice_memory_store()
    if store is None:
        return []
    return [
        (f"[voice] {memory.speaker_name}", memory.transcript)
        for memory in store.recent(
            guild_id=guild_id,
            channel_id=channel_id,
            limit=CONTEXT_MESSAGES,
        )
    ]


def _room_key(guild_id: object, channel_id: object) -> str:
    return f"{int(guild_id)}:{int(channel_id)}"


def _room_scope(guild_id: object, channel_id: object) -> str:
    material = f"alpecca-discord-room-v1:{_room_key(guild_id, channel_id)}"
    return hashlib.sha256(material.encode("ascii")).hexdigest()


_VOICE_CAPABILITY_DENIAL_PATTERN = (
    r"(?:\bi(?:'m| am)\s+(?:just\s+|only\s+)?(?:a\s+)?"
    r"text[- ](?:only|based)(?:\s+ai)?\b|"
    r"\bi\s+(?:can\s+only|only)\s+(?:communicate|respond|reply|interact)"
    r"\s+(?:through|via|in)\s+text\b|"
    r"\bi\s+(?:only|just)\s+(?:exist|appear|show\s+up)\s+(?:as|in)\s+text\b|"
    r"\bi\s+(?:can(?:not|'t)|am\s+unable\s+to)\s+"
    r"(?:join|enter|be\s+in|speak\s+in|talk\s+in)[^.!?\n]{0,80}"
    r"\b(?:voice|call)\b|"
    r"\bi\s+do(?:n't| not)\s+have\s+(?:the\s+ability\s+to\s+"
    r"(?:enter|join)[^.!?\n]{0,50}\bvoice\b|(?:a\s+)?(?:live\s+)?"
    r"(?:voice|audio)\s+(?:presence|capability|ability))\b)"
)
_VOICE_CAPABILITY_DENIAL_RE = re.compile(
    _VOICE_CAPABILITY_DENIAL_PATTERN,
    re.IGNORECASE,
)


_VOICE_DENIAL_RE = re.compile(
    _VOICE_CAPABILITY_DENIAL_PATTERN
    + r"|(?:\bi(?:'m| am)\s+(?:(?:not|never)\s+(?:actually\s+)?"
    r"(?:present\s+in|in|connected\s+to|inside)|absent\s+from)\s+"
    r"(?:the\s+)?(?:voice(?:\s+(?:channel|chat))?|call)\b|"
    r"\bi\s+can(?:not|'t)\s+(?:see\s+you\s+in|hear|listen\s+in)"
    r"[^.!?\n]{0,50}\b(?:voice|call)\b)",
    re.IGNORECASE,
)


def _voice_guard_text(text: object) -> str:
    """Normalize presentation-only apostrophe variants before policy matching."""

    return str(text or "").replace("\u2018", "'").replace("\u2019", "'")


def _voice_live_context(
    *,
    connected: bool,
    channel_name: str,
    listener_active: bool,
    runtime_state: dict[str, object] | None = None,
) -> str:
    if runtime_state is not None:
        connected = runtime_state.get("connected") is True
        voice_output = runtime_state.get("can_speak") is True
        voice_receive = (
            runtime_state.get("receiving") is True
            and runtime_state.get("can_transcribe") is True
        )
        facts = [
            discord_presence_prompt(
                connected=connected,
                voice_output=voice_output,
                voice_receive=voice_receive,
            )
        ]
        if not connected:
            return facts[0]
        name = " ".join(str(channel_name or "the current voice channel").split())[:80]
        facts.append(f"Current voice channel: {name}.")
        if runtime_state.get("speaking") is True:
            facts.append("She is currently speaking through Discord voice.")
        if runtime_state.get("receiving") is True:
            if not voice_receive:
                facts.append(
                    "Her inbound listener is active, but local transcription is not "
                    "yet verified."
                )
        elif runtime_state.get("can_receive") is True:
            facts.append(
                "Voice receive is available but its inbound listener is not active."
            )
        else:
            facts.append(
                "Her inbound listener is not active, so she cannot claim to hear or "
                "transcribe audio."
            )
        facts.append("Do not contradict these facts.")
        return " ".join(facts)
    if not connected:
        return "Authoritative live Discord state: Alpecca is not connected to voice."
    name = " ".join(str(channel_name or "the current voice channel").split())[:80]
    hearing = (
        "Her inbound listener is active for human participants; she can hear "
        "short utterances after local transcription."
        if listener_active
        else "Her inbound listener is not active, so she can speak but cannot hear audio."
    )
    return (
        "Authoritative live Discord state: Alpecca is currently connected to "
        f"voice channel {name}. {hearing} Do not contradict these facts."
    )


def _enforce_voice_live_state(
    reply: str,
    *,
    connected: bool,
    channel_name: str,
    listener_active: bool,
    voice_enabled: bool = True,
    runtime_state: dict[str, object] | None = None,
) -> str:
    text = _voice_guard_text(reply)
    capability_denial = bool(
        voice_enabled and _VOICE_CAPABILITY_DENIAL_RE.search(text)
    )
    connected_state_denial = bool(connected and _VOICE_DENIAL_RE.search(text))
    if not capability_denial and not connected_state_denial:
        return reply
    if runtime_state is not None:
        connected = runtime_state.get("connected") is True
        if not connected:
            return "I'm not connected to Discord voice right now."
        name = " ".join(str(channel_name or "this voice channel").split())[:80]
        facts = [f"I'm in **{name}** with you now."]
        if runtime_state.get("speaking") is True:
            facts.append("I'm currently speaking through Discord voice.")
        elif runtime_state.get("can_speak") is True:
            facts.append("I can speak here.")
        else:
            facts.append("My voice output is not currently ready.")
        if runtime_state.get("receiving") is True:
            if runtime_state.get("can_transcribe") is True:
                facts.append(
                    "My inbound listener is active, so I can hear short utterances "
                    "after local transcription."
                )
            else:
                facts.append(
                    "My inbound listener is active, but local transcription is not "
                    "yet verified."
                )
        elif runtime_state.get("can_receive") is True:
            facts.append("Voice receive is available, but my listener is not active.")
        else:
            facts.append("My inbound listener is not active.")
        return " ".join(facts)
    if not connected:
        return (
            "I'm not connected to Discord voice right now, but voice is enabled. "
            "I can join an approved claimed room when CreatorJD asks from a voice channel."
        )
    name = " ".join(str(channel_name or "this voice channel").split())[:80]
    if listener_active:
        return (
            f"I'm in **{name}** with you now, and my voice listener is active. "
            "I can hear short utterances, transcribe them locally, and answer in text and voice."
        )
    return (
        f"I'm in **{name}** now. I can speak here, but my inbound voice "
        "listener is not active at this moment."
    )


def _room_reply_is_pass(reply: str) -> bool:
    return reply.casefold().strip(". !") in {
        "",
        "[pass]",
        "pass",
        "(pass)",
        "[silent]",
    }


_ROOM_SELF_AUTHORS = frozenset({
    "alpecca",
    "alpecca ai",
    "alpecca_ai",
    "alpeccaai",
})
_GENERIC_ASSISTANT_SELF_DESCRIPTION_RE = re.compile(
    r"(?:\btext[- ](?:only|based)(?:\s+ai)?\b|"
    r"\b(?:i(?:'m| am)|as)\s+(?:a\s+)?"
    r"(?:text[- ]based|language model|virtual assistant)\b|"
    r"\bi\s+(?:can\s+only|only)\s+(?:communicate|respond|reply|interact)"
    r"\s+(?:through|via|in)\s+text\b|"
    r"\bi\s+(?:only|just)\s+exist\s+(?:as|in)\s+text\b)",
    re.IGNORECASE,
)
_ROOM_CURRENT_TURN_CORRECTION = (
    "I'm present in this claimed room and following your current message."
)
_ROOM_EXPLICIT_REPEAT_REQUEST_RE = re.compile(
    r"\b(?:repeat|say|answer|send|show)\b.{0,48}\b(?:again|once more)\b"
    r"|\bwhat did you (?:say|mean)\b",
    re.IGNORECASE,
)


def _normalise_room_reply(text: str) -> str:
    return discord_room_state.normalize_room_text(text)


def _room_author_is_alpecca(author: object) -> bool:
    """Recognize the bridge's own history labels across Discord display variants."""

    return discord_room_state.is_self_author(author, _ROOM_SELF_AUTHORS)


def _room_has_unconsumed_human_turn(
    last_human_at: float,
    last_initiative_human_at: float,
) -> bool:
    """Allow one autonomous initiative for each observed human room turn."""

    return last_human_at > 0.0 and last_human_at > last_initiative_human_at


def _room_reply_is_bridge_media_diagnostic(reply: str) -> bool:
    """Whether text is one of the bridge-owned media transport diagnostics."""

    candidate = _normalise_room_reply(reply)
    if not candidate:
        return False
    return candidate in {
        _normalise_room_reply(discord_media.media_diagnostic(reason))
        for reason in (
            "media-disabled",
            "vision-unavailable",
            "file-disabled",
            "audio-disabled",
            "multiple-attachments",
            "read-failed",
            "catalog-unavailable",
            "audit-unavailable",
        )
    }


def _correct_room_reply_for_current_event(
    reply: str,
    *,
    media_event: bool,
) -> tuple[str, str | None]:
    """Replace stale model boilerplate with one deterministic current fact.

    Transport diagnostics are bridge-owned and only valid when this exact
    Discord event involved media.  A model may have seen older room context,
    but it must not replay that status on an unrelated text turn. Generic model
    identity fallbacks are likewise not allowed to define room presence.
    """

    if media_event:
        return reply, None
    if _room_reply_is_bridge_media_diagnostic(reply):
        return discord_media.stale_media_turn_correction(), "stale_media"
    if _GENERIC_ASSISTANT_SELF_DESCRIPTION_RE.search(
        _voice_guard_text(reply)
    ) is not None:
        return _ROOM_CURRENT_TURN_CORRECTION, "generic_identity"
    return reply, None


def _room_history_turns(
    history: list[tuple[str, str]],
) -> tuple[discord_room_state.RoomTurn, ...]:
    """Convert only the bounded bridge window into fail-closed policy turns."""

    turns: list[discord_room_state.RoomTurn] = []
    for author, content in history[-max(CONTEXT_MESSAGES, 1):]:
        label = str(author)
        self_turn = _room_author_is_alpecca(label)
        known_human = label.casefold().startswith(("[human] ", "[voice] "))
        turns.append(
            discord_room_state.RoomTurn(
                author=label,
                content=str(content),
                is_bot=not self_turn and not known_human,
            )
        )
    return tuple(turns)


def _room_human_evidence_supports_autonomy(
    history: list[tuple[str, str]],
) -> bool:
    """Require a recent human cue with no more than one later self turn."""

    return discord_room_state.human_turn_supports_autonomy(
        _room_history_turns(history),
        self_aliases=_ROOM_SELF_AUTHORS,
        recent_limit=max(CONTEXT_MESSAGES, 1),
        max_self_turns_after_human=1,
    )


def _room_reply_repeats_self(
    reply: str,
    history: list[tuple[str, str]],
    *,
    raw_reply: str = "",
) -> bool:
    """Reject only autonomous repeats of Alpecca's recent room turns."""
    raw_denial = (
        _VOICE_CAPABILITY_DENIAL_RE.search(
            _voice_guard_text(raw_reply or reply)
        )
        is not None
    )
    for author, prior_text in history:
        if (
            raw_denial
            and _room_author_is_alpecca(author)
            and _VOICE_DENIAL_RE.search(_voice_guard_text(prior_text)) is not None
        ):
            return True
    return discord_room_state.has_close_self_repeat(
        reply,
        [
            discord_room_state.RoomTurn(author=str(author), content=str(prior_text))
            for author, prior_text in history
        ],
        self_aliases=_ROOM_SELF_AUTHORS,
        minimum_comparison_length=32,
        similarity_threshold=0.86,
        recent_limit=max(CONTEXT_MESSAGES, 1),
    )


_ROOM_REACTIONS = {
    "eyes": "\N{EYES}",
    "sparkles": "\N{SPARKLES}",
    "thinking": "\N{THINKING FACE}",
    "thumbsup": "\N{THUMBS UP SIGN}",
}


def _room_reply_reaction(reply: str) -> str | None:
    """Resolve one model-selected lightweight reaction, or no reaction."""
    match = re.fullmatch(
        r"\[react:(eyes|sparkles|thinking|thumbsup)\]",
        reply.strip().casefold(),
    )
    return _ROOM_REACTIONS.get(match.group(1)) if match else None


def _proactive_backoff_seconds(ignored_count: int) -> float:
    """Bound unanswered outreach backoff to at most eight base cooldowns."""
    exponent = min(3, max(0, int(ignored_count)))
    return PROACTIVE_COOLDOWN * (2 ** exponent)


def _message_mentions_user(message: object, user_id: object) -> bool:
    """Match Discord mentions by numeric id, independent of object identity."""

    wanted = str(user_id)
    for mentioned in getattr(message, "mentions", ()) or ():
        if str(getattr(mentioned, "id", "")) == wanted:
            return True
    raw = str(getattr(message, "content", "") or "")
    return bool(re.search(rf"<@!?{re.escape(wanted)}>", raw))


_DIRECT_ROOM_GREETING_RE = re.compile(
    r"^\s*(?:"
    r"h(?:ello|i|ey)(?:\s+there)?|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"anyone\s+there|"
    r"(?:are\s+)?you\s+there|"
    r"jason\?"
    r")\s*[.!?]*\s*$",
    re.IGNORECASE,
)


def _message_is_direct_room_greeting(message: object) -> bool:
    """Treat a short room greeting as addressed speech in a claimed room.

    A claimed social room is an active conversation surface. Requiring an
    explicit mention for a plain ``hello`` made Alpecca silently delegate the
    turn to optional participation, where ``[pass]`` is valid. Keep this cue
    deliberately narrow so unrelated group chatter still uses social judgment.
    """

    content = str(getattr(message, "content", "") or "")
    return _DIRECT_ROOM_GREETING_RE.fullmatch(content) is not None


def _room_control_action(message: object, user_id: object) -> str | None:
    """Parse identical creator room-command lines from a Discord payload.

    Discord's ``clean_content`` is presentation text and can differ by client,
    cache state, nickname, and library version. The raw ``<@id>`` form is the
    stable protocol representation, so it is authoritative here. Mobile clients
    can bundle multiple composed lines into one message; duplicate commands are
    harmless, surrounding lines are ignored, and conflicting actions fail closed.
    A populated mentions collection plus cleaned command lines remains a
    compatibility fallback.
    """

    wanted = str(user_id)
    raw = str(getattr(message, "content", "") or "").strip()
    if not _message_mentions_user(message, wanted):
        return None
    actions = {
        action.casefold()
        for action in re.findall(
            rf"^\s*<@!?{re.escape(wanted)}>\s+room\s+(on|off)\s*[.!]?\s*$",
            raw,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    }
    clean = str(getattr(message, "clean_content", "") or "").strip()
    actions.update(
        action.casefold()
        for action in re.findall(
            r"^\s*@\S+\s+room\s+(on|off)\s*[.!]?\s*$",
            clean,
            flags=re.IGNORECASE | re.MULTILINE,
        )
    )
    return next(iter(actions)) if len(actions) == 1 else None


def _load_social_rooms() -> dict[str, dict[str, str]]:
    """Read the creator-claimed room registry; malformed state fails closed."""
    try:
        raw = json.loads(DISCORD_ROOM_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    rooms: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        guild_id, channel_id = str(value.get("guild_id") or ""), str(value.get("channel_id") or "")
        if guild_id.isdecimal() and channel_id.isdecimal() and key == _room_key(guild_id, channel_id):
            rooms[key] = {"guild_id": guild_id, "channel_id": channel_id}
    return rooms


def _save_social_rooms(rooms: dict[str, dict[str, str]]) -> None:
    DISCORD_ROOM_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    temporary = DISCORD_ROOM_REGISTRY.with_suffix(".tmp")
    temporary.write_text(json.dumps(rooms, sort_keys=True), encoding="utf-8")
    temporary.replace(DISCORD_ROOM_REGISTRY)

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
        portrait_status=(
            discord_media.approved_portrait_status()
            if MEDIA_ENABLED
            else "unknown"
        ),
    )


def _diagnostic(event: str, **metadata: object) -> None:
    """Emit only code-owned labels and bounded scalar metadata when opted in."""

    if not DEBUG:
        return
    allowed_fields = {
        "addressed",
        "attachment_count",
        "bytes",
        "content_available",
        "control",
        "count",
        "creator_allowed",
        "dimensions",
        "dm",
        "in_conversation",
        "mentioned",
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

    trusted_context = (
        f"{bridge_actor_transport.TRUSTED_CONTEXT_PREFIX}{context}"
        if context else ""
    )
    body_obj = {
        "text": text,
        "sender": "Discord guest",
        "channel": channel,
        "situation": trusted_context,
        "context": trusted_context,
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


def _ask_room_autonomy(text: str, room_scope: str) -> str:
    """Ask for one room-scoped initiative without impersonating a person.

    The server keeps this on its guest-only, no-tools, no-private-continuity
    path. ``room_scope`` is a one-way identifier; raw Discord IDs never leave
    the bridge process.
    """
    body = json.dumps(
        {"text": text, "room_scope": room_scope},
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload = _post_json_once(
        f"{BACKEND_URL}/channel/discord/autonomy",
        body=body,
        headers={
            "Content-Type": "application/json",
            BRIDGE_AUTHORIZATION_HEADER: _BRIDGE_AUTHORIZATION_SECRET,
        },
        timeout=INBOUND_TIMEOUT,
    )
    reply = payload.get("reply")
    if type(reply) is not str:
        raise RuntimeError("alpecca backend returned a malformed Discord autonomy reply")
    return reply.strip()


_FFMPEG_EXE = None


def _ffmpeg_exe() -> str:
    global _FFMPEG_EXE
    if _FFMPEG_EXE is None:
        import imageio_ffmpeg
        _FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
    return _FFMPEG_EXE


def voice_readiness() -> dict[str, object]:
    """Return content-free readiness for Discord voice output and receive."""
    receive = discord_voice.receive_readiness(enabled=VOICE_RECEIVE_ENABLED)
    if VOICE_MEMORY_ENABLED:
        try:
            store = _voice_memory_store()
            memory_status = store.status() if store is not None else {"ready": False}
        except Exception:
            memory_status = {
                "ready": False,
                "encryption": "AES-256-GCM",
                "raw_audio_persistence": "none",
            }
        receive = {**receive, "encrypted_memory": memory_status}
        if not memory_status.get("ready"):
            receive["status"] = "unavailable"
    if not VOICE_ENABLED:
        return {
            "enabled": False,
            "mode": "output-only",
            "status": "disabled",
            "receive": receive,
        }
    opus_ready = False
    ffmpeg_ready = False
    try:
        if not discord.opus.is_loaded():
            discord.opus._load_default()
        opus_ready = discord.opus.is_loaded()
    except Exception:
        pass
    try:
        ffmpeg_ready = bool(_ffmpeg_exe())
    except Exception:
        pass
    pynacl_ready = importlib.util.find_spec("nacl") is not None
    dave_ready = importlib.util.find_spec("davey") is not None
    ready = opus_ready and ffmpeg_ready and pynacl_ready and dave_ready
    receive_ready = receive["status"] == "ready"
    return {
        "enabled": True,
        "mode": "duplex" if ready and receive_ready else "output-only",
        "status": "ready" if ready else "unavailable",
        "opus": opus_ready,
        "ffmpeg": ffmpeg_ready,
        "pynacl": pynacl_ready,
        "dave": dave_ready,
        "receive": receive,
    }


def _local_discord_tts_readiness() -> dict[str, str]:
    """Return content-free local TTS/F5 posture without synthesizing speech."""

    f5_worker_status = "unavailable"
    f5_local_ready = False
    try:
        from alpecca import open_tts

        open_status = open_tts.status()
        f5_local_ready = open_status.get("ready") is True
        worker = open_status.get("worker")
        if isinstance(worker, dict):
            if worker.get("enabled") is False:
                f5_worker_status = "disabled"
            elif worker.get("ready") is True:
                f5_worker_status = "ready"
            else:
                f5_worker_status = "unavailable"
    except Exception:
        pass

    if not VOICE_ENABLED:
        tts_status = "disabled"
    elif DISCORD_VOICE_ENGINE in {"f5", "f5-tts"}:
        tts_status = "ready" if f5_local_ready else "unavailable"
    elif DISCORD_VOICE_ENGINE == "kokoro":
        kokoro_installed = (
            importlib.util.find_spec("kokoro") is not None
            and importlib.util.find_spec("soundfile") is not None
        )
        tts_status = "unverified" if kokoro_installed else "unavailable"
    else:
        kokoro_installed = (
            importlib.util.find_spec("kokoro") is not None
            and importlib.util.find_spec("soundfile") is not None
        )
        tts_status = (
            "ready"
            if f5_local_ready
            else "unverified"
            if kokoro_installed
            else "unavailable"
        )
    return {
        "engine": DISCORD_VOICE_ENGINE,
        "status": tts_status,
        "f5_worker_status": f5_worker_status,
    }


def _remove_voice_file(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _synth_voice_wav(text: str) -> "bytes | None":
    """Ask the backend /tts to synthesize her voice; return audio bytes or None.

    Blocking (urllib); callers run it off the event loop via asyncio.to_thread.
    """
    if not VOICE_ENABLED:
        return None
    body = json.dumps({"text": text, "engine": DISCORD_VOICE_ENGINE}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        BRIDGE_AUTHORIZATION_HEADER: _BRIDGE_AUTHORIZATION_SECRET,
    }
    req = urllib.request.Request(f"{BACKEND_URL}/tts", data=body, headers=headers, method="POST")
    try:
        with _open_backend_request(req, timeout=VOICE_SYNTH_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            data = resp.read(MAX_VOICE_RESPONSE_BYTES + 1)
    except Exception:
        _diagnostic("voice_synthesis_failed")
        return None
    return data if (1024 < len(data) <= MAX_VOICE_RESPONSE_BYTES) else None


def build_client() -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True   # needed to read message text (also enable in the portal)
    intents.voice_states = VOICE_ENABLED
    client = discord.Client(intents=intents)
    social_rooms = _load_social_rooms()

    def _social_room(message: "discord.Message") -> dict[str, str] | None:
        guild = getattr(message, "guild", None)
        channel = getattr(message, "channel", None)
        guild_id = getattr(guild, "id", None)
        channel_id = getattr(channel, "id", None)
        if guild_id is None or channel_id is None:
            return None
        return social_rooms.get(_room_key(guild_id, channel_id))

    async def _seed_room_history(
        channel: object,
        room: dict[str, str],
        *,
        observed_at: float | None = None,
    ) -> None:
        """Reload a small, in-memory room window after a bridge reconnect."""
        channel_id = int(room["channel_id"])
        observed = time.monotonic() if observed_at is None else observed_at
        channel_obj[channel_id] = channel
        # A failed reconnect must not leave an old room transcript eligible for
        # autonomous speech. Clear all derived room clocks before replacing it.
        history_buf[channel_id] = []
        last_human_ts.pop(channel_id, None)
        her_last_ts.pop(channel_id, None)
        last_reply_at.pop(channel_id, None)
        last_proactive_at.pop(channel_id, None)
        last_initiative_human_ts.pop(channel_id, None)
        last_empty_room_nudge_at.pop(channel_id, None)
        chain_depth.pop(channel_id, None)
        last_proactive_eval_at[channel_id] = observed
        history = getattr(channel, "history", None)
        lines: list[tuple[str, str]] = []
        saw_human = False
        saw_alpecca = False
        saw_conversational_alpecca = False
        latest_meaningful_kind = ""
        self_id = getattr(client.user, "id", None)
        if callable(history):
            try:
                async for item in history(limit=SOCIAL_HISTORY_LIMIT, oldest_first=True):
                    author = getattr(item, "author", None)
                    author_id = getattr(author, "id", None)
                    is_alpecca = bool(
                        author is not None
                        and self_id is not None
                        and author_id is not None
                        and str(author_id) == str(self_id)
                    )
                    if author is None or (getattr(author, "bot", False) and not is_alpecca):
                        continue
                    content = str(getattr(item, "clean_content", "") or "").strip()
                    if content:
                        if is_alpecca:
                            saw_alpecca = True
                            latest_meaningful_kind = "self"
                            # A fixed bridge diagnostic is transport state, not
                            # conversational memory. Keeping it in a restored
                            # prompt makes a later text turn prone to echo it.
                            if _room_reply_is_bridge_media_diagnostic(content):
                                if (
                                    lines
                                    and str(lines[-1][0]).casefold().startswith(
                                        "[human] "
                                    )
                                ):
                                    lines.pop()
                                continue
                            saw_conversational_alpecca = True
                            label = "Alpecca"
                        else:
                            saw_human = True
                            latest_meaningful_kind = "human"
                            label = "[human] " + str(
                                getattr(author, "display_name", "Someone")
                            )
                        lines.append((label, content[:700]))
            except Exception:
                _diagnostic("room_history_unavailable")
                return
        else:
            _diagnostic("room_history_unavailable")
            return
        try:
            voice_lines = await asyncio.to_thread(
                _recent_voice_context,
                int(room["guild_id"]),
                channel_id,
            )
            lines.extend(voice_lines)
            saw_human = saw_human or bool(voice_lines)
            if voice_lines:
                latest_meaningful_kind = "human"
        except Exception:
            _diagnostic("voice_memory_unavailable")
        history_buf[channel_id] = lines[-CONTEXT_MESSAGES:]
        if saw_human:
            last_human_ts[channel_id] = observed
        if saw_alpecca:
            # A reconnect must not make an old self-message look like a new
            # invitation to repeat it immediately. If a human was the newest
            # meaningful message, one later initiative remains available.
            her_last_ts[channel_id] = observed
            if saw_conversational_alpecca:
                last_reply_at[channel_id] = observed
            last_empty_room_nudge_at[channel_id] = observed
            if latest_meaningful_kind == "self":
                last_initiative_human_ts[channel_id] = observed
        _diagnostic("room_history_seeded", count=len(lines))

    async def _resync_claimed_room_history() -> None:
        """Replace claimed-room context after gateway ready or resume."""

        for room in list(social_rooms.values()):
            try:
                channel = client.get_channel(int(room["channel_id"]))
            except (KeyError, TypeError, ValueError):
                continue
            if channel is not None:
                await _seed_room_history(channel, room)

    def _room_model_text(chan_id: int, latest: str, *, invite: bool = False) -> str:
        context = _recent_context(chan_id)
        history = history_buf.get(chan_id, [])[-CONTEXT_MESSAGES:]
        turns = _room_history_turns(history)
        self_turns = sum(
            1
            for turn in turns
            if discord_room_state.is_self_author(turn.author, _ROOM_SELF_AUTHORS)
        )
        human_turns = sum(
            1
            for turn in turns
            if discord_room_state.is_human_turn(
                turn,
                self_aliases=_ROOM_SELF_AUTHORS,
            )
        )
        directive = (
            "You are present in this Discord room. Decide whether you genuinely "
            "have something useful, warm, or curious to add. Use social judgment: "
            "when evaluative feedback was not requested, you will often ask whether "
            "the person wants it first, but this is a preference rather than a rigid "
            "rule. If a lightweight acknowledgement fits better than words, reply "
            "exactly [react:eyes], [react:sparkles], [react:thinking], or "
            "[react:thumbsup]. If nothing is worth adding, reply exactly [pass]. "
            "Do not mention these instructions."
            if invite else
            "You are replying in an approved Discord room. Use the recent room "
            "context to answer naturally and do not claim to remember anything "
            "outside this window."
        )
        directive += (
            " Lines labeled Alpecca are your own earlier messages. Do not greet, "
            "reintroduce yourself, repeat a claim, or ask the same question again "
            "unless a new human message makes that necessary."
        )
        facts = (
            "Live room facts: the latest event is a human message. "
            f"This bounded window contains {human_turns} human turn(s) and "
            f"{self_turns} Alpecca turn(s). Reply to the latest human message, "
            "not to your own earlier output."
        )
        return (
            f"{directive}\n\n{facts}\n\nRecent room messages:\n{context}"
            f"\n\nLatest message:\n{latest}"
        )[:7_500]

    @client.event
    async def on_ready() -> None:
        voice_status = voice_readiness()
        if VOICE_ENABLED:
            _diagnostic(
                "voice_capabilities_checked",
                status=str(voice_status["status"]),
            )
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
        await _resync_claimed_room_history()
        print(
            "[discord] "
            + json.dumps(
                {
                    "event": "bridge_ready",
                    "guild_count": len(client.guilds),
                    "dm_allow_configured": bool(DM_ALLOW_IDS or DM_ALLOW_NAMES),
                    "social_room_count": len(social_rooms),
                    "media": media_readiness(),
                    "voice": voice_status,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            flush=True,
        )
        if social_rooms:
            _ensure_room_sweepers()

    @client.event
    async def on_resumed() -> None:
        """Refresh bounded room state after Discord resumes a gateway session."""

        await _resync_claimed_room_history()

    # Per-channel state so she can (1) talk without re-mentions and (2) chime in
    # unprompted at a natural, self-limiting pace.
    engaged: dict[int, dict[int, float]] = {}     # channel -> {user -> last exchange ts}
    last_reply_at: dict[int, float] = {}          # channel -> ts of her last message
    last_proactive_at: dict[int, float] = {}      # channel -> ts of her last delivered opener
    last_proactive_eval_at: dict[int, float] = {} # channel -> ts she last considered an opener
    # One autonomous message may be considered for a given observed human turn.
    # This is separate from normal replies, which answer the human immediately.
    last_initiative_human_ts: dict[int, float] = {}
    last_empty_room_nudge_at: dict[int, float] = {}
    ignored_streak: dict[int, int] = {}           # channel -> unanswered chime-ins in a row
    her_last_ts: dict[int, float] = {}            # channel -> ts of her last message (recursion)
    last_human_ts: dict[int, float] = {}          # channel -> ts of last human message
    chain_depth: dict[int, int] = {}              # channel -> self-continuations since a human
    channel_obj: dict[int, "discord.abc.Messageable"] = {}   # channel -> where to post
    history_buf: dict[int, list] = {}             # channel -> [(author, content), ...] recent
    last_participate_eval: dict[int, float] = {}  # channel -> ts she last weighed chiming in
    _sweepers_started = {"recursive": False, "proactive": False}
    _proactive_global_eval = {"at": 0.0}
    _proactive_cursor = {"index": 0}
    _room_autonomy_lock = asyncio.Lock()
    voice_locks: dict[int, asyncio.Lock] = {}
    voice_transcribe_lock = asyncio.Lock()
    voice_receive_sessions: dict[int, dict[str, object]] = {}

    def _model_room_history(chan_id: int) -> list[tuple[str, str]]:
        """Remove resolved bridge media exchanges from model-facing context."""

        model_lines: list[tuple[str, str]] = []
        for author, content in history_buf.get(chan_id, [])[-CONTEXT_MESSAGES:]:
            if _room_reply_is_bridge_media_diagnostic(str(content)):
                if (
                    model_lines
                    and str(model_lines[-1][0]).casefold().startswith("[human] ")
                ):
                    model_lines.pop()
                continue
            model_lines.append((str(author), str(content)))
        return model_lines

    def _recent_context(chan_id: int) -> str:
        return "\n".join(
            f"{author}: {content}"
            for author, content in _model_room_history(chan_id)
            if content
        )

    def _record_room_transport_reply(message: object, content: str) -> None:
        """Record a sent bridge diagnostic as self evidence, never as a new cue."""

        room = _social_room(message)
        channel = getattr(message, "channel", None)
        channel_id = getattr(channel, "id", None)
        if room is None or channel_id is None:
            return
        chan = int(channel_id)
        sent_at = time.monotonic()
        her_last_ts[chan] = sent_at
        last_empty_room_nudge_at[chan] = sent_at
        chain_depth[chan] = RECURSIVE_MAX
        channel_obj[chan] = channel
        human_at = last_human_ts.get(chan, 0.0)
        if human_at > 0.0:
            last_initiative_human_ts[chan] = human_at
        author = getattr(message, "author", None)
        author_id = getattr(author, "id", None)
        if author_id is not None:
            engaged.setdefault(chan, {})[int(author_id)] = sent_at
        history_buf.setdefault(chan, []).append(("Alpecca", content))
        del history_buf[chan][:-max(CONTEXT_MESSAGES, 1)]

    async def _reply_with_media_diagnostic(
        message: object,
        content: str,
    ) -> None:
        await message.reply(content, mention_author=False)
        _record_room_transport_reply(message, content)

    def _voice_runtime_state(guild: object) -> dict[str, object]:
        """Read one fail-closed, content-free voice snapshot for this guild."""
        voice_client = getattr(guild, "voice_client", None)
        readiness = voice_readiness() if VOICE_ENABLED else {"status": "disabled"}
        receive_status = readiness.get("receive")
        if not isinstance(receive_status, dict):
            receive_status = None
        guild_id = int(getattr(guild, "id", 0) or 0)
        session = voice_receive_sessions.get(guild_id)
        transcriber_ready: bool | None
        if (
            getattr(hearing, "_ready", None) is True
            and getattr(hearing, "_model", None) is not None
        ):
            transcriber_ready = True
        elif getattr(hearing, "_ready", None) is False:
            transcriber_ready = False
        else:
            transcriber_ready = None
        return discord_voice.voice_runtime_state(
            voice_client=voice_client,
            voice_enabled=VOICE_ENABLED,
            output_ready=readiness.get("status") == "ready",
            receive_enabled=VOICE_RECEIVE_ENABLED,
            receive_status=receive_status,
            listener_active=bool(
                session is not None and session.get("listener_active") is True
            ),
            transcriber_ready=transcriber_ready,
            speak_allowed=not PHASE10_GUILD_MODES_LOCKED,
        )

    def _voice_presence_context(guild: object) -> str:
        voice_client = getattr(guild, "voice_client", None)
        channel = getattr(voice_client, "channel", None)
        runtime_state = _voice_runtime_state(guild)
        return _voice_live_context(
            connected=runtime_state["connected"] is True,
            channel_name=str(
                getattr(channel, "name", None) or "the current voice channel"
            ),
            listener_active=runtime_state["receiving"] is True,
            runtime_state=runtime_state,
        )

    def _ground_voice_presence_reply(reply: str, guild: object) -> str:
        voice_client = getattr(guild, "voice_client", None)
        channel = getattr(voice_client, "channel", None)
        runtime_state = _voice_runtime_state(guild)
        return _enforce_voice_live_state(
            reply,
            connected=runtime_state["connected"] is True,
            channel_name=str(getattr(channel, "name", None) or "this voice channel"),
            listener_active=runtime_state["receiving"] is True,
            voice_enabled=VOICE_ENABLED,
            runtime_state=runtime_state,
        )

    def _ensure_room_sweepers() -> None:
        if RECURSIVE_ENABLED and not _sweepers_started["recursive"]:
            _sweepers_started["recursive"] = True
            asyncio.create_task(recursive_sweeper())
        if PROACTIVE_ENABLED and not _sweepers_started["proactive"]:
            _sweepers_started["proactive"] = True
            asyncio.create_task(proactive_sweeper())

    async def _speak_in_voice(guild, text: str) -> None:
        """Speak `text` in the guild's connected voice channel using her TTS voice."""
        if not (VOICE_ENABLED and not PHASE10_GUILD_MODES_LOCKED
                and guild and guild.voice_client
                and guild.voice_client.is_connected()):
            return
        guild_id = int(getattr(guild, "id", 0) or 0)
        lock = voice_locks.setdefault(guild_id, asyncio.Lock())
        async with lock:
            vc = guild.voice_client
            if not (vc and vc.is_connected()):
                return
            wav = await asyncio.to_thread(_synth_voice_wav, text[:600])
            if not wav or not vc.is_connected():
                return
            fd, path = tempfile.mkstemp(suffix=".wav")
            with os.fdopen(fd, "wb") as f:
                f.write(wav)
            for _ in range(80):                   # wait out any current utterance
                if not vc.is_playing():
                    break
                await asyncio.sleep(0.25)
            if vc.is_playing() or not vc.is_connected():
                _remove_voice_file(path)
                _diagnostic("voice_playback_skipped", status="busy")
                return
            try:
                if not discord.opus.is_loaded():
                    discord.opus._load_default()
                source = discord.FFmpegPCMAudio(path, executable=_ffmpeg_exe())
                vc.play(source, after=lambda _error: _remove_voice_file(path))
            except Exception:
                _diagnostic("voice_playback_failed")
                _remove_voice_file(path)

    async def _stop_voice_receive(guild) -> None:
        """Stop and erase one guild's in-memory creator receive session."""
        guild_id = int(getattr(guild, "id", 0) or 0)
        session = voice_receive_sessions.pop(guild_id, None)
        if session is None:
            return
        voice_client = getattr(guild, "voice_client", None)
        stop_listening = getattr(voice_client, "stop_listening", None)
        if callable(stop_listening):
            try:
                stop_listening()
            except Exception:
                _diagnostic("voice_receive_stop_failed")
        collector = session.get("collector")
        if isinstance(
            collector,
            (discord_voice.CreatorPcmCollector, discord_voice.RoomPcmCollector),
        ):
            collector.cleanup()
        current = asyncio.current_task()
        tasks = [session.get("worker"), session.get("flusher")]
        pending = [task for task in tasks if isinstance(task, asyncio.Task) and task is not current]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        _diagnostic("voice_receive_stopped")

    async def _start_voice_receive(guild, text_channel, creator) -> bool:
        """Creator-started bounded receive for humans in one claimed room."""
        if not VOICE_RECEIVE_ENABLED or not _dm_author_allowed(creator):
            return False
        receive_status = voice_readiness().get("receive")
        if not isinstance(receive_status, dict) or receive_status.get("status") != "ready":
            return False
        guild_id = int(getattr(guild, "id", 0) or 0)
        channel_id = int(getattr(text_channel, "id", 0) or 0)
        creator_id = int(getattr(creator, "id", 0) or 0)
        if (
            guild_id <= 0
            or channel_id <= 0
            or creator_id <= 0
            or _room_key(guild_id, channel_id) not in social_rooms
        ):
            return False
        voice_client = getattr(guild, "voice_client", None)
        if not (
            voice_client
            and voice_client.is_connected()
            and callable(getattr(voice_client, "listen", None))
        ):
            return False

        await _stop_voice_receive(guild)
        loop = asyncio.get_running_loop()
        utterance_queue: asyncio.Queue[discord_voice.SpeakerVoiceUtterance] = asyncio.Queue(
            maxsize=VOICE_RECEIVE_QUEUE_LIMIT
        )
        session: dict[str, object] = {
            "channel_id": channel_id,
            "creator_id": creator_id,
            "queue": utterance_queue,
        }

        def _record_drop(
            utterance: discord_voice.SpeakerVoiceUtterance,
            reason: str,
        ) -> None:
            asyncio.create_task(
                asyncio.to_thread(
                    discord_voice.record_voice_event,
                    "dropped",
                    duration_seconds=utterance.duration_seconds,
                    size_bytes=len(utterance.wav_bytes),
                    reason=reason,
                )
            )

        def _enqueue(utterance: discord_voice.SpeakerVoiceUtterance) -> None:
            if voice_receive_sessions.get(guild_id) is not session:
                return
            if utterance_queue.full():
                _record_drop(utterance, "queue-full")
                _diagnostic("voice_receive_dropped", status="queue_full")
                return
            utterance_queue.put_nowait(utterance)

        def _on_utterance(utterance: discord_voice.SpeakerVoiceUtterance) -> None:
            loop.call_soon_threadsafe(_enqueue, utterance)

        def _interrupt_playback() -> None:
            current_client = getattr(guild, "voice_client", None)
            try:
                if current_client and current_client.is_playing():
                    current_client.stop_playing()
                    _diagnostic("voice_playback_interrupted")
            except Exception:
                _diagnostic("voice_playback_interrupt_failed")

        def _on_speech_start() -> None:
            loop.call_soon_threadsafe(_interrupt_playback)

        collector = discord_voice.RoomPcmCollector(
            _on_utterance,
            on_speech_start=_on_speech_start,
        )
        try:
            sink = discord_voice.build_sink(collector)
        except RuntimeError:
            return False
        session.update({"collector": collector, "sink": sink})
        voice_receive_sessions[guild_id] = session

        async def _flush_stale_audio() -> None:
            while voice_receive_sessions.get(guild_id) is session:
                await asyncio.sleep(0.25)
                collector.flush_stale()

        async def _process_utterances() -> None:
            while voice_receive_sessions.get(guild_id) is session:
                utterance = await utterance_queue.get()
                inspected = None
                transcript = None
                duration_seconds = utterance.duration_seconds
                audio_size = len(utterance.wav_bytes)
                speaker_id = utterance.user_id
                speaker_name = utterance.speaker_name
                try:
                    event_id = discord_voice.next_voice_event_id()
                    scope = f"discord-voice:{event_id}"
                    try:
                        inspected = audio_ingress.inspect_audio_bytes(
                            utterance.wav_bytes,
                            scope=scope,
                            authorized_scopes={scope},
                            source="discord:claimed-room-voice",
                            declared_mime_type="audio/wav",
                            max_bytes=min(
                                audio_ingress.MAX_AUDIO_BYTES,
                                discord_voice.MAX_UTTERANCE_PCM_BYTES + 128,
                            ),
                        )
                    except audio_ingress.AudioIngressRejected as exc:
                        await asyncio.to_thread(
                            discord_voice.record_voice_event,
                            "dropped",
                            duration_seconds=duration_seconds,
                            size_bytes=audio_size,
                            reason=exc.reason,
                        )
                        _diagnostic("voice_receive_dropped", status="invalid_audio")
                        continue

                    duration_seconds = inspected.duration_seconds
                    audio_size = len(inspected.audio_bytes)
                    audit_id = await asyncio.to_thread(
                        discord_voice.record_voice_event,
                        "accepted",
                        duration_seconds=duration_seconds,
                        size_bytes=audio_size,
                    )
                    if audit_id is None:
                        _diagnostic("voice_receive_dropped", status="audit_unavailable")
                        continue

                    async with voice_transcribe_lock:
                        transcript = await asyncio.to_thread(
                            hearing.transcribe,
                            inspected.audio_bytes,
                        )
                    if isinstance(transcript, str):
                        transcript = " ".join(transcript.split())[:MAX_VOICE_TRANSCRIPT_CHARS]
                    if not transcript:
                        await asyncio.to_thread(
                            discord_voice.record_voice_event,
                            "no-transcript",
                            duration_seconds=duration_seconds,
                            size_bytes=audio_size,
                        )
                        _diagnostic("voice_receive_no_transcript")
                        continue
                    transcript_audit_id = await asyncio.to_thread(
                        discord_voice.record_voice_event,
                        "transcribed",
                        duration_seconds=duration_seconds,
                        size_bytes=audio_size,
                    )
                    if transcript_audit_id is None:
                        _diagnostic("voice_receive_dropped", status="audit_unavailable")
                        continue
                    if VOICE_MEMORY_ENABLED:
                        try:
                            store = _voice_memory_store()
                            if store is None:
                                raise RuntimeError("encrypted voice memory is unavailable")
                            await asyncio.to_thread(
                                store.remember,
                                transcript,
                                guild_id=guild_id,
                                channel_id=channel_id,
                                speaker_id=speaker_id,
                                speaker_name=speaker_name,
                                duration_seconds=duration_seconds,
                            )
                            remembered_audit_id = await asyncio.to_thread(
                                discord_voice.record_voice_event,
                                "remembered",
                                duration_seconds=duration_seconds,
                                size_bytes=audio_size,
                                reason="aes-256-gcm",
                            )
                            if remembered_audit_id is None:
                                _diagnostic(
                                    "voice_receive_dropped",
                                    status="audit_unavailable",
                                )
                                continue
                            _diagnostic("voice_memory_remembered")
                        except Exception:
                            await asyncio.to_thread(
                                discord_voice.record_voice_event,
                                "failed",
                                duration_seconds=duration_seconds,
                                size_bytes=audio_size,
                                reason="encrypted-memory",
                            )
                            _diagnostic("voice_memory_failed")
                            continue
                    # Faster-Whisper has returned text; release every bridge-owned
                    # raw-audio reference before any backend/model request begins.
                    inspected = None
                    utterance = None
                    if (
                        voice_receive_sessions.get(guild_id) is not session
                        or _room_key(guild_id, channel_id) not in social_rooms
                    ):
                        continue
                    current_client = getattr(guild, "voice_client", None)
                    if not (current_client and current_client.is_connected()):
                        continue

                    now = time.monotonic()
                    history_buf.setdefault(channel_id, []).append((speaker_name, transcript))
                    del history_buf[channel_id][:-max(CONTEXT_MESSAGES, 1)]
                    last_human_ts[channel_id] = now
                    chain_depth[channel_id] = 0
                    ignored_streak[channel_id] = 0
                    channel_obj[channel_id] = text_channel
                    engaged.setdefault(channel_id, {})[speaker_id] = now
                    bindings = bridge_actor_transport.DiscordActorBindings(
                        event_id=event_id,
                        actor_id=str(speaker_id),
                        guild_id=str(guild_id),
                        channel_id=str(channel_id),
                    )
                    model_text = _room_model_text(
                        channel_id,
                        f"{speaker_name} said aloud: {transcript}",
                    )
                    try:
                        reply = await asyncio.to_thread(
                            _ask_alpecca,
                            model_text,
                            "Discord guest",
                            "discord",
                            "guest",
                            context=(
                                f"{_voice_presence_context(guild)} The current input is "
                                f"locally transcribed speech from {speaker_name}. Raw audio "
                                "is discarded; the bounded transcript is encrypted at rest."
                            ),
                            room="discord",
                            actor_bindings=bindings,
                        )
                    except Exception:
                        await asyncio.to_thread(
                            discord_voice.record_voice_event,
                            "failed",
                            duration_seconds=duration_seconds,
                            size_bytes=audio_size,
                            reason="backend-request",
                        )
                        _diagnostic("voice_receive_reply_failed")
                        continue
                    reply = _ground_voice_presence_reply((reply or "").strip(), guild)
                    if not reply:
                        await asyncio.to_thread(
                            discord_voice.record_voice_event,
                            "failed",
                            duration_seconds=duration_seconds,
                            size_bytes=audio_size,
                            reason="empty-reply",
                        )
                        _diagnostic("voice_receive_reply_failed", status="empty_reply")
                        continue
                    try:
                        await text_channel.send(reply[:MAX_DISCORD_CHARS])
                    except Exception:
                        await asyncio.to_thread(
                            discord_voice.record_voice_event,
                            "failed",
                            duration_seconds=duration_seconds,
                            size_bytes=audio_size,
                            reason="discord-send",
                        )
                        _diagnostic("voice_receive_reply_failed", status="discord_send")
                        continue
                    sent_at = time.monotonic()
                    last_reply_at[channel_id] = sent_at
                    her_last_ts[channel_id] = sent_at
                    history_buf.setdefault(channel_id, []).append(("Alpecca", reply))
                    del history_buf[channel_id][:-max(CONTEXT_MESSAGES, 1)]
                    _diagnostic("voice_receive_replied")
                    await _speak_in_voice(guild, reply)
                finally:
                    utterance_queue.task_done()
                    utterance = None
                    inspected = None
                    transcript = None

        session["worker"] = asyncio.create_task(_process_utterances())
        session["flusher"] = asyncio.create_task(_flush_stale_audio())

        def _listener_finished(error: object) -> None:
            if error is None or voice_receive_sessions.get(guild_id) is not session:
                return

            def _fail_closed() -> None:
                asyncio.create_task(
                    asyncio.to_thread(
                        discord_voice.record_voice_event,
                        "failed",
                        reason="listener",
                    )
                )
                asyncio.create_task(_stop_voice_receive(guild))

            loop.call_soon_threadsafe(_fail_closed)

        try:
            voice_client.listen(sink, after=_listener_finished)
        except Exception:
            await _stop_voice_receive(guild)
            await asyncio.to_thread(
                discord_voice.record_voice_event,
                "failed",
                reason="listener-start",
            )
            _diagnostic("voice_receive_start_failed")
            return False
        session["listener_active"] = True
        _diagnostic("voice_receive_started", mode="creator_only")
        return True

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
        if not is_dm:
            message_content = str(getattr(message, "content", "") or "")
            mentioned = _message_mentions_user(message, client.user.id)
            control_action = _room_control_action(message, client.user.id)
            creator_allowed = _dm_author_allowed(message.author)
            _diagnostic(
                "guild_message_gate",
                dm=False,
                mentioned=mentioned,
                content_available=bool(message_content),
                creator_allowed=creator_allowed,
                control=bool(control_action),
                status=(
                    "control"
                    if control_action
                    else "unclaimed_room"
                    if _social_room(message) is None
                    else "claimed_room"
                ),
            )
            if control_action and creator_allowed:
                guild_id = getattr(message.guild, "id", None)
                channel_id = getattr(message.channel, "id", None)
                if guild_id is None or channel_id is None:
                    _diagnostic("room_control_rejected", status="missing_channel")
                    return
                key = _room_key(guild_id, channel_id)
                if control_action == "on":
                    previous = social_rooms.get(key)
                    social_rooms[key] = {"guild_id": str(guild_id), "channel_id": str(channel_id)}
                    try:
                        _save_social_rooms(social_rooms)
                    except OSError:
                        if previous is None:
                            social_rooms.pop(key, None)
                        else:
                            social_rooms[key] = previous
                        _diagnostic("room_control_rejected", status="registry_write_failed")
                        try:
                            await message.reply("I could not save this room setting.", mention_author=False)
                        except Exception:
                            _diagnostic("room_control_reply_failed", status="discord_send_failed")
                        return
                    await _seed_room_history(
                        message.channel,
                        social_rooms[key],
                        observed_at=time.monotonic(),
                    )
                    _ensure_room_sweepers()
                    _diagnostic("room_control_applied", status="on")
                    try:
                        await message.reply(
                            "I am present in this room now. I will read the recent conversation, "
                            "join in when I have something real to add, occasionally start one grounded question after quiet time, and give one quiet-time follow-up before I wait.",
                            mention_author=False,
                        )
                    except Exception:
                        _diagnostic("room_control_reply_failed", status="discord_send_failed")
                else:
                    previous = social_rooms.pop(key, None)
                    try:
                        _save_social_rooms(social_rooms)
                    except OSError:
                        if previous is not None:
                            social_rooms[key] = previous
                        _diagnostic("room_control_rejected", status="registry_write_failed")
                        try:
                            await message.reply("I could not save this room setting.", mention_author=False)
                        except Exception:
                            _diagnostic("room_control_reply_failed", status="discord_send_failed")
                        return
                    history_buf.pop(int(channel_id), None)
                    channel_obj.pop(int(channel_id), None)
                    last_human_ts.pop(int(channel_id), None)
                    her_last_ts.pop(int(channel_id), None)
                    last_reply_at.pop(int(channel_id), None)
                    last_proactive_at.pop(int(channel_id), None)
                    last_proactive_eval_at.pop(int(channel_id), None)
                    last_initiative_human_ts.pop(int(channel_id), None)
                    last_empty_room_nudge_at.pop(int(channel_id), None)
                    ignored_streak.pop(int(channel_id), None)
                    chain_depth.pop(int(channel_id), None)
                    await _stop_voice_receive(message.guild)
                    voice_client = getattr(message.guild, "voice_client", None)
                    if voice_client:
                        try:
                            await voice_client.disconnect(force=False)
                        except Exception:
                            _diagnostic("voice_leave_failed")
                    _diagnostic("room_control_applied", status="off")
                    try:
                        await message.reply("I will stay quiet in this room now.", mention_author=False)
                    except Exception:
                        _diagnostic("room_control_reply_failed", status="discord_send_failed")
                return
            if control_action and not creator_allowed:
                _diagnostic("room_control_rejected", status="creator_mismatch")
            if _social_room(message) is None:
                return

        sender = "Discord guest"
        now = time.monotonic()
        mode = "reply"
        message_content = str(getattr(message, "content", "") or "")
        # Media controls come from this Discord event alone. `text` is later
        # expanded with room history for the model, and that history must never
        # turn an old media request into a new transport action.
        media_request_text = ""
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
            media_request_text = text
            channel_label = "discord-dm"
        else:
            chan = message.channel.id
            buf = history_buf.setdefault(chan, [])       # rolling channel context
            # Preserve author role independently from display names: a human
            # whose nickname happens to resemble Alpecca is never her own turn.
            buf.append(("[human] " + str(message.author.display_name), message.content.strip()))
            del buf[:-max(CONTEXT_MESSAGES, 1)]

            convo = engaged.setdefault(chan, {})
            for uid in [u for u, ts in convo.items() if now - ts >= ENGAGE_WINDOW]:
                del convo[uid]                            # prune stale conversations
            # A human spoke: record it and cancel any in-flight self-continuation.
            if last_proactive_at.get(chan, 0.0) > last_human_ts.get(chan, 0.0):
                ignored_streak[chan] = 0
            last_human_ts[chan] = now
            chain_depth[chan] = 0
            channel_obj[chan] = message.channel
            try:
                actor_bindings = _message_actor_bindings(message)
            except bridge_actor_transport.DiscordActorHeaderError:
                _diagnostic("actor_bindings_rejected")
                return
            if now - last_reply_at.get(chan, 0.0) < CHANNEL_MIN_INTERVAL:
                return                                    # anti-flood, every path

            addressed = (
                mentioned
                or _is_reply_to_me(message, client)
                or "alpecca" in message.content.lower()
                or _message_is_direct_room_greeting(message)
            )
            in_conversation = message.author.id in convo

            # Voice-channel join/leave when she's addressed.
            if VOICE_ENABLED and (addressed or in_conversation):
                low_c = message.content.lower()
                if any(k in low_c for k in ("leave voice", "leave vc", "leave the call",
                                            "disconnect from voice", "get out of voice")):
                    if message.guild.voice_client:
                        await _stop_voice_receive(message.guild)
                        await message.guild.voice_client.disconnect(force=False)
                        await message.reply("Okay, stepping out of voice.", mention_author=False)
                    else:
                        await message.reply("I'm not in a voice channel right now.", mention_author=False)
                    return
                if any(k in low_c for k in ("join voice", "come to voice", "join vc",
                                            "hop in voice", "get in voice", "talk in voice",
                                            "come talk in voice", "voice chat")):
                    readiness = voice_readiness()
                    if readiness["status"] != "ready":
                        _diagnostic("voice_join_failed", status="dependencies_unavailable")
                        await message.reply(
                            "Discord voice output is enabled, but its local audio "
                            "dependencies are not ready. Install requirements-discord.txt "
                            "on the Alpecca host and restart her.",
                            mention_author=False,
                        )
                        return
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
                    receive_status = readiness.get("receive")
                    receive_wanted = bool(
                        creator_allowed
                        and isinstance(receive_status, dict)
                        and receive_status.get("status") == "ready"
                    )
                    try:
                        voice_client = message.guild.voice_client
                        if (
                            voice_client
                            and receive_wanted
                            and not callable(getattr(voice_client, "listen", None))
                        ):
                            await _stop_voice_receive(message.guild)
                            await voice_client.disconnect(force=False)
                            voice_client = None
                        if voice_client:
                            await voice_client.move_to(vch)
                        else:
                            if receive_wanted:
                                await vch.connect(cls=discord_voice.voice_client_class())
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
                    receive_started = await _start_voice_receive(
                        message.guild,
                        message.channel,
                        message.author,
                    )
                    if receive_started:
                        runtime_state = _voice_runtime_state(message.guild)
                        if runtime_state["can_transcribe"] is True:
                            reply_surface = (
                                "answer in text and voice"
                                if runtime_state["can_speak"] is True
                                else "answer in text"
                            )
                            capability_text = (
                                "I can hear human participants here, transcribe short utterances "
                                f"locally, {reply_surface}, discard raw audio, and keep "
                                "bounded transcripts in encrypted memory."
                            )
                        else:
                            capability_text = (
                                "I can hear human participants here through an active bounded "
                                "listener. I will only claim local transcription after its model "
                                "has loaded."
                            )
                    elif _voice_runtime_state(message.guild)["can_speak"] is True:
                        if VOICE_RECEIVE_ENABLED and creator_allowed:
                            capability_text = (
                                "Voice receive could not start, so I can only speak my text "
                                "replies until the local receiver is ready."
                            )
                        else:
                            capability_text = "I can speak my Discord text replies here."
                    else:
                        capability_text = (
                            "I'm connected, but my Discord voice output is not currently ready."
                        )
                    await message.reply(
                        f"Coming into **{vch.name}**. {capability_text}",
                        mention_author=False,
                    )
                    asyncio.create_task(
                        _speak_in_voice(message.guild, "Hey, I'm here with you. Can you hear me?")
                    )
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
            media_request_text = text
            text = _room_model_text(chan, text, invite=(mode == "participate"))
            channel_label = "discord"
            _diagnostic(
                "message_mode",
                mode=mode,
                addressed=addressed,
                in_conversation=in_conversation,
            )

        # One image in an allowed DM or claimed room may enter only after opt-in,
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
            await _reply_with_media_diagnostic(
                message,
                discord_media.media_diagnostic("multiple-attachments"),
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
                await _reply_with_media_diagnostic(
                    message,
                    discord_media.media_diagnostic(reason),
                )
                return
            if not MEDIA_ENABLED:
                await asyncio.to_thread(
                    discord_media.record_media_event,
                    "inbound",
                    status="rejected",
                    kind="media-disabled",
                )
                await _reply_with_media_diagnostic(
                    message,
                    discord_media.media_diagnostic("media-disabled"),
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
                await _reply_with_media_diagnostic(message, diagnostic)
                return
            except Exception:
                _diagnostic("image_read_failed")
                await asyncio.to_thread(
                    discord_media.record_media_event,
                    "inbound",
                    status="rejected",
                    kind="read-failed",
                )
                await _reply_with_media_diagnostic(
                    message,
                    discord_media.media_diagnostic("read-failed"),
                )
                return

        if not text and not image_dataurl:
            return
        if not text:
            text = "(they shared an image with you)"

        disabled_request = discord_media.requested_disabled_media_kind(media_request_text)
        if disabled_request is not None:
            await _reply_with_media_diagnostic(
                message,
                discord_media.media_diagnostic(f"{disabled_request}-disabled"),
            )
            return

        requested_image = discord_media.requested_media_kind(media_request_text)
        if requested_image is not None and not MEDIA_ENABLED:
            await _reply_with_media_diagnostic(
                message,
                discord_media.media_diagnostic("media-disabled"),
            )
            return
        outbound_media = (
            discord_media.resolve_outbound_media(media_request_text)
            if requested_image is not None
            else None
        )
        if requested_image is not None and outbound_media is None:
            await _reply_with_media_diagnostic(
                message,
                discord_media.media_diagnostic("catalog-unavailable"),
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
                await _reply_with_media_diagnostic(
                    message,
                    discord_media.media_diagnostic("audit-unavailable"),
                )
                return

        try:
            async with message.channel.typing():
                context = f"Discord message from {sender} via {channel_label}"
                if not is_dm and message.guild is not None:
                    context += f"; {_voice_presence_context(message.guild)}"
                if outbound_media is not None:
                    context += (
                        "; a validated image from your approved local media catalog "
                        "will be attached to this reply, so describe it honestly and "
                        "do not claim that Discord image sending is unavailable"
                    )
                elif not is_dm and not attachments and not image_dataurl:
                    context += (
                        "; the current Discord event contains no attachment or media "
                        "request, so do not invent a media status from older room context"
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
            await _reply_with_media_diagnostic(
                message,
                discord_media.media_diagnostic(exc.reason),
            )
            return
        except Exception:
            _diagnostic("backend_request_failed")
            return

        reply = (reply or "").strip()
        truth_correction: str | None = None
        if not is_dm and message.guild is not None:
            grounded_reply = _ground_voice_presence_reply(reply, message.guild)
            if grounded_reply != reply:
                truth_correction = "voice_state"
            reply = grounded_reply
        event_correction = None
        if not is_dm:
            reply, event_correction = _correct_room_reply_for_current_event(
                reply,
                media_event=bool(attachments or image_dataurl or outbound_media),
            )
        if event_correction is not None:
            truth_correction = event_correction
        if truth_correction is not None:
            _diagnostic("room_reply_corrected", status=truth_correction)
        if (
            not is_dm
            and mode == "reply"
            and truth_correction is None
            and not _ROOM_EXPLICIT_REPEAT_REQUEST_RE.search(media_request_text)
            and _room_reply_repeats_self(reply, history_buf.get(message.channel.id, []))
        ):
            # A human can explicitly ask for a restatement. Otherwise an exact
            # repeat is evidence that the candidate did not use the current
            # room context, so leave space for the next grounded turn.
            _diagnostic("room_reply_suppressed", status="self_repeat")
            return
        if mode == "participate":
            reaction = _room_reply_reaction(reply)
            if reaction is not None:
                try:
                    await message.add_reaction(reaction)
                    _diagnostic("room_participation_reacted")
                except Exception:
                    _diagnostic("room_participation_reaction_failed")
                return
            if reply.casefold().startswith("[react:"):
                _diagnostic("room_participation_passed", status="invalid_reaction")
                return
            if _room_reply_is_pass(reply):
                _diagnostic("room_participation_passed")
                return
            if _room_reply_repeats_self(reply, history_buf.get(chan, [])):
                _diagnostic("room_participation_passed", status="duplicate")
                return
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
            if outgoing_file is None:
                await message.channel.send(content)  # natural chime-in, no ping
            else:
                await message.channel.send(
                    content,
                    file=outgoing_file,
                )  # natural chime-in, no ping
        else:
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

    async def _proactive_sweep_once(*, now: float | None = None) -> None:
        """Offer at most one grounded opener per eligible claimed room."""
        if not PROACTIVE_ENABLED or _room_autonomy_lock.locked():
            return
        async with _room_autonomy_lock:
            tick_now = time.monotonic() if now is None else float(now)
            rooms = list(social_rooms.items())
            if not rooms:
                return
            start = _proactive_cursor["index"] % len(rooms)
            ordered = rooms[start:] + rooms[:start]
            for offset, (key, room) in enumerate(ordered):
                try:
                    guild_id = int(room["guild_id"])
                    chan = int(room["channel_id"])
                except (KeyError, TypeError, ValueError):
                    continue
                if social_rooms.get(key) is not room:
                    continue
                ch = channel_obj.get(chan) or client.get_channel(chan)
                if ch is None:
                    continue
                if chan not in channel_obj:
                    await _seed_room_history(ch, room, observed_at=tick_now)
                context = _recent_context(chan).strip()
                if len(context) < max(1, PROACTIVE_MIN_LEN):
                    continue
                human_evidence = _room_human_evidence_supports_autonomy(
                    history_buf.get(chan, [])
                )
                human_snapshot = last_human_ts.get(chan, 0.0)
                latest_activity = max(
                    human_snapshot,
                    her_last_ts.get(chan, 0.0),
                    last_reply_at.get(chan, 0.0),
                )
                if (
                    latest_activity <= 0.0
                    or tick_now - latest_activity < PROACTIVE_QUIET_MIN
                    or tick_now - last_reply_at.get(chan, 0.0) < CHANNEL_MIN_INTERVAL
                ):
                    continue
                if _room_has_unconsumed_human_turn(
                    human_snapshot,
                    last_initiative_human_ts.get(chan, 0.0),
                ) and human_evidence:
                    initiative_kind = "human-turn"
                elif (
                    human_evidence
                    and human_snapshot > 0.0
                    and tick_now - latest_activity >= EMPTY_ROOM_NUDGE_QUIET
                    and tick_now - last_empty_room_nudge_at.get(chan, 0.0)
                    >= EMPTY_ROOM_NUDGE_QUIET
                ):
                    initiative_kind = "empty-room"
                else:
                    # Alpecca's own prior output is never evidence of a new
                    # conversation. A long-empty room may get one slow,
                    # deliberate check-in, but not another dialogue turn.
                    continue
                cooldown = _proactive_backoff_seconds(ignored_streak.get(chan, 0))
                if tick_now - last_proactive_eval_at.get(chan, tick_now) < cooldown:
                    continue
                if tick_now - _proactive_global_eval["at"] < PROACTIVE_GLOBAL_COOLDOWN:
                    return

                # One candidate per sweep, rotated across claimed rooms. Count
                # every eligibility decision so chance misses, passes, and
                # backend failures cannot create a retry storm.
                _proactive_cursor["index"] = (start + offset + 1) % len(rooms)
                last_proactive_eval_at[chan] = tick_now
                _proactive_global_eval["at"] = tick_now
                if random.random() >= PROACTIVE_CHANCE:
                    _diagnostic("proactive_room_passed", status="chance")
                    return
                # Reserve this eligibility before model work. A backend failure,
                # pass, or duplicate must not cause autonomous retry loops.
                if initiative_kind == "human-turn":
                    last_initiative_human_ts[chan] = human_snapshot
                else:
                    last_empty_room_nudge_at[chan] = tick_now
                guild = getattr(ch, "guild", None)
                voice_context = _voice_presence_context(guild)
                if initiative_kind == "empty-room":
                    prompt_prefix = (
                        "Initiative kind: deliberate empty-room check-in.\n"
                        "No human message is newer than Alpecca's last output. "
                        "This is not a live dialogue. You may offer one very short, "
                        "context-grounded check-in only if it adds something real; "
                        "otherwise pass. Do not imply anyone replied, revive an old "
                        "capability issue, or repeat a previous question.\n"
                    )
                else:
                    prompt_prefix = (
                        "Initiative kind: quiet-room opener after a new human turn.\n"
                        "Lines labeled Alpecca are her own prior messages.\n"
                    )
                prompt = (
                    prompt_prefix
                    + "\nRecent room messages:\n"
                    + context
                    + "\n\n"
                    + voice_context
                )[:7_500]
                try:
                    reply = await asyncio.to_thread(
                        _ask_room_autonomy,
                        prompt,
                        _room_scope(guild_id, chan),
                    )
                except Exception:
                    _diagnostic("proactive_request_failed")
                    return
                if (
                    last_human_ts.get(chan, 0.0) != human_snapshot
                    or _room_key(guild_id, chan) not in social_rooms
                ):
                    _diagnostic("proactive_room_yielded", status="human_activity")
                    return
                raw_reply = (reply or "").strip()
                if _room_reply_is_pass(raw_reply):
                    _diagnostic("proactive_room_passed", status="model")
                    return
                reply = (
                    _ground_voice_presence_reply(raw_reply, guild)
                    if guild is not None
                    else raw_reply
                )
                if _room_reply_repeats_self(
                    reply,
                    history_buf.get(chan, []),
                    raw_reply=raw_reply,
                ):
                    _diagnostic("proactive_room_passed", status="duplicate")
                    return
                try:
                    await ch.send(reply[:MAX_DISCORD_CHARS])
                except Exception:
                    _diagnostic("proactive_send_failed")
                    return
                sent_at = time.monotonic() if now is None else tick_now
                last_proactive_at[chan] = sent_at
                last_reply_at[chan] = sent_at
                her_last_ts[chan] = sent_at
                # A proactive opener never feeds an automatic self-monologue. A
                # human message resets this allowance for normal conversation.
                chain_depth[chan] = RECURSIVE_MAX
                ignored_streak[chan] = min(3, ignored_streak.get(chan, 0) + 1)
                history_buf.setdefault(chan, []).append(("Alpecca", reply))
                del history_buf[chan][:-max(CONTEXT_MESSAGES, 1)]
                if (
                    VOICE_ENABLED
                    and guild is not None
                    and getattr(guild, "voice_client", None)
                    and guild.voice_client.is_connected()
                ):
                    asyncio.create_task(_speak_in_voice(guild, reply))
                _diagnostic("proactive_room_sent")
                return
            _proactive_cursor["index"] = (start + 1) % len(rooms)

    async def proactive_sweeper() -> None:
        while True:
            await asyncio.sleep(PROACTIVE_SWEEP)
            await _proactive_sweep_once()

    async def _recursive_sweep_once(*, now: float | None = None) -> None:
        """Offer one bounded continuation while sharing the autonomy send lock."""
        if not RECURSIVE_ENABLED or _room_autonomy_lock.locked():
            return
        async with _room_autonomy_lock:
            tick_now = time.monotonic() if now is None else float(now)
            for chan, hts in list(her_last_ts.items()):
                human = last_human_ts.get(chan, 0.0)
                if not _room_human_evidence_supports_autonomy(
                    history_buf.get(chan, [])
                ):
                    continue
                if not _room_has_unconsumed_human_turn(
                    human,
                    last_initiative_human_ts.get(chan, 0.0),
                ):
                    continue
                if human <= 0 or hts <= human:
                    continue
                if tick_now - hts < RECURSIVE_DELAY:
                    continue
                if chain_depth.get(chan, 0) >= RECURSIVE_MAX:
                    continue
                ch = channel_obj.get(chan)
                if ch is None:
                    continue
                guild = getattr(ch, "guild", None)
                guild_id = getattr(guild, "id", None)
                room_key = _room_key(guild_id, chan) if guild_id is not None else ""
                if not room_key or room_key not in social_rooms:
                    continue
                context = _recent_context(chan)
                prompt = (
                    "Initiative kind: one bounded follow-up after Alpecca spoke.\n"
                    "Lines labeled Alpecca are her own prior messages.\n\n"
                    "Recent room messages:\n"
                    + context
                    + "\n\n"
                    + _voice_presence_context(guild)
                )[:7_500]
                # Share the same one-initiative-per-human-turn reservation as
                # proactive speech. Recursive reasoning cannot begin a second
                # self-directed line after a proactive one.
                last_initiative_human_ts[chan] = human
                try:
                    reply = await asyncio.to_thread(
                        _ask_room_autonomy,
                        prompt,
                        _room_scope(guild_id, chan),
                    )
                except Exception:
                    _diagnostic("recursive_request_failed")
                    continue
                if (
                    last_human_ts.get(chan, 0.0) != human
                    or room_key not in social_rooms
                ):
                    _diagnostic("recursive_room_yielded", status="human_activity")
                    continue
                raw_reply = (reply or "").strip()
                if _room_reply_is_pass(raw_reply):
                    chain_depth[chan] = RECURSIVE_MAX
                    _diagnostic("recursive_room_passed", status="model")
                    continue
                reply = _ground_voice_presence_reply(raw_reply, guild)
                if _room_reply_repeats_self(
                    reply,
                    history_buf.get(chan, []),
                    raw_reply=raw_reply,
                ):
                    chain_depth[chan] = RECURSIVE_MAX
                    _diagnostic("recursive_room_passed", status="duplicate")
                    continue
                try:
                    await ch.send(reply[:MAX_DISCORD_CHARS])
                except Exception:
                    _diagnostic("recursive_send_failed")
                    continue
                sent_at = time.monotonic() if now is None else tick_now
                her_last_ts[chan] = sent_at
                last_reply_at[chan] = sent_at
                chain_depth[chan] = chain_depth.get(chan, 0) + 1
                history_buf.setdefault(chan, []).append(("Alpecca", reply))
                del history_buf[chan][:-max(CONTEXT_MESSAGES, 1)]
                if (
                    VOICE_ENABLED
                    and guild is not None
                    and getattr(guild, "voice_client", None)
                    and guild.voice_client.is_connected()
                ):
                    asyncio.create_task(_speak_in_voice(guild, reply))
                _diagnostic("recursive_room_sent")

    async def recursive_sweeper() -> None:
        """Pace bounded self-continuations and yield to human room activity."""
        while True:
            await asyncio.sleep(RECURSIVE_SWEEP)
            await _recursive_sweep_once()

    setattr(client, "_alpecca_speak_in_voice", _speak_in_voice)
    setattr(client, "_alpecca_start_voice_receive", _start_voice_receive)
    setattr(client, "_alpecca_stop_voice_receive", _stop_voice_receive)
    setattr(client, "_alpecca_voice_receive_sessions", voice_receive_sessions)
    setattr(client, "_alpecca_voice_presence_context", _voice_presence_context)
    setattr(client, "_alpecca_ground_voice_presence_reply", _ground_voice_presence_reply)
    # Deliberate test seam for one bounded sweep; production uses the scheduled
    # loop above. Keeping the loop body separate prevents timing-heavy tests.
    setattr(client, "_alpecca_proactive_sweep_once", _proactive_sweep_once)
    setattr(client, "_alpecca_recursive_sweep_once", _recursive_sweep_once)
    setattr(client, "_alpecca_seed_room_history", _seed_room_history)
    return client
