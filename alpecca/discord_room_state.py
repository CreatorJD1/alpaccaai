"""Pure helpers for safe, bounded Discord room-state decisions.

Room turns must be supplied oldest-to-newest.  The helpers deliberately do not
depend on Discord objects so that reconnect history, live messages, and tests
all use the same conservative rules.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata


AuthorIdentity = str | int | None


@dataclass(frozen=True, slots=True)
class RoomTurn:
    """One chronological room-history record used by the pure policy helpers."""

    author: AuthorIdentity
    content: str = ""
    is_bot: bool = False


_DISCORD_MENTION_RE = re.compile(r"^<@!?(\d+)>$")
_TEXT_MENTION_RE = re.compile(r"(?:<@!?\d+>|@[a-z0-9_.-]+)", re.IGNORECASE)
_TEXT_SEPARATOR_RE = re.compile(r"[\W_]+", re.UNICODE)


def normalize_author_identity(author: object | None) -> str:
    """Return a conservative comparison key for an author id, mention, or name.

    Only presentation-only differences are normalized: Unicode compatibility,
    case, surrounding ``@``, and whitespace.  Punctuation is intentionally
    retained so distinct aliases cannot match by accident.
    """
    if author is None:
        return ""
    value = unicodedata.normalize("NFKC", str(author)).strip().casefold()
    mention = _DISCORD_MENTION_RE.fullmatch(value)
    if mention:
        return mention.group(1)
    if value.startswith("@"):
        value = value[1:].strip()
    return " ".join(value.split())


def is_self_author(
    author: AuthorIdentity,
    self_aliases: Iterable[AuthorIdentity],
) -> bool:
    """Whether ``author`` exactly matches a normalized self alias."""
    identity = normalize_author_identity(author)
    if not identity:
        return False
    aliases = {
        normalized
        for alias in self_aliases
        if (normalized := normalize_author_identity(alias))
    }
    return identity in aliases


def is_bot_or_self_author(
    author: AuthorIdentity,
    *,
    is_bot: bool,
    self_aliases: Iterable[AuthorIdentity],
) -> bool:
    """Whether an author must not be treated as a human room participant."""
    return is_bot or is_self_author(author, self_aliases)


def is_human_turn(turn: RoomTurn, *, self_aliases: Iterable[AuthorIdentity]) -> bool:
    """Whether a turn is attributable to a known, non-bot, non-self human."""
    return bool(normalize_author_identity(turn.author)) and not is_bot_or_self_author(
        turn.author,
        is_bot=turn.is_bot,
        self_aliases=self_aliases,
    )


def bounded_recent_turns(
    turns: Iterable[RoomTurn],
    *,
    limit: int = 12,
) -> tuple[RoomTurn, ...]:
    """Return only the newest bounded room turns, preserving chronology."""
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    return tuple(deque(turns, maxlen=limit))


def count_human_turns_after_latest_self(
    turns: Iterable[RoomTurn],
    *,
    self_aliases: Iterable[AuthorIdentity],
    recent_limit: int = 12,
) -> int:
    """Count human turns after the latest self turn in oldest-to-newest history.

    A room with no self turn counts its known human turns.  Unknown authors and
    third-party bots never count as human activity, so they cannot authorize an
    autonomous message.
    """
    aliases = frozenset(
        normalized
        for alias in self_aliases
        if (normalized := normalize_author_identity(alias))
    )
    human_count = 0
    for turn in bounded_recent_turns(turns, limit=recent_limit):
        identity = normalize_author_identity(turn.author)
        if identity and identity in aliases:
            human_count = 0
        elif identity and not turn.is_bot:
            human_count += 1
    return human_count


def autonomous_speech_allowed(
    turns: Iterable[RoomTurn],
    *,
    self_aliases: Iterable[AuthorIdentity],
    recent_limit: int = 12,
) -> bool:
    """Allow speech only when a known human turn is newer than the latest self turn."""
    return count_human_turns_after_latest_self(
        turns,
        self_aliases=self_aliases,
        recent_limit=recent_limit,
    ) > 0


def human_turn_supports_autonomy(
    turns: Iterable[RoomTurn],
    *,
    self_aliases: Iterable[AuthorIdentity],
    recent_limit: int = 12,
    max_self_turns_after_human: int = 1,
) -> bool:
    """Whether recent human evidence can support one bounded follow-up.

    A normal reply may sit between the latest human turn and one autonomous
    follow-up. More self turns mean that cue has already been exhausted. Bots,
    unknown authors, and evidence outside the bounded tail cannot authorize it.
    """
    if type(max_self_turns_after_human) is not int or max_self_turns_after_human < 0:
        raise ValueError("max_self_turns_after_human must be a non-negative integer")
    aliases = frozenset(
        normalized
        for alias in self_aliases
        if (normalized := normalize_author_identity(alias))
    )
    saw_human = False
    self_turns_after_human = 0
    for turn in bounded_recent_turns(turns, limit=recent_limit):
        identity = normalize_author_identity(turn.author)
        if identity and identity in aliases:
            if saw_human:
                self_turns_after_human += 1
        elif identity and not turn.is_bot:
            saw_human = True
            self_turns_after_human = 0
    return saw_human and self_turns_after_human <= max_self_turns_after_human


def normalize_room_text(text: object | None) -> str:
    """Normalize a room message for conservative duplicate comparisons."""
    if text is None:
        return ""
    value = unicodedata.normalize("NFKC", str(text)).casefold()
    without_mentions = _TEXT_MENTION_RE.sub(" ", value)
    return " ".join(_TEXT_SEPARATOR_RE.sub(" ", without_mentions).split())


def has_close_self_repeat(
    candidate: str,
    turns: Iterable[RoomTurn],
    *,
    self_aliases: Iterable[AuthorIdentity],
    minimum_comparison_length: int = 32,
    similarity_threshold: float = 0.88,
    recent_limit: int = 12,
) -> bool:
    """Whether a candidate repeats a recent self turn closely enough to suppress.

    Exact normalized matches are always repeats.  Fuzzy matching is reserved for
    substantial messages, using containment or sequence similarity to avoid
    treating short, common acknowledgements as duplicates.
    """
    if minimum_comparison_length < 1:
        raise ValueError("minimum_comparison_length must be at least 1")
    if not 0.0 <= similarity_threshold <= 1.0:
        raise ValueError("similarity_threshold must be between 0.0 and 1.0")

    normalized_candidate = normalize_room_text(candidate)
    if not normalized_candidate:
        return False
    aliases = frozenset(
        normalized
        for alias in self_aliases
        if (normalized := normalize_author_identity(alias))
    )
    if not aliases:
        return False

    for turn in bounded_recent_turns(turns, limit=recent_limit):
        if normalize_author_identity(turn.author) not in aliases:
            continue
        prior = normalize_room_text(turn.content)
        if not prior:
            continue
        if normalized_candidate == prior:
            return True
        shorter, longer = sorted((normalized_candidate, prior), key=len)
        if len(shorter) < minimum_comparison_length:
            continue
        if shorter in longer and len(shorter) / len(longer) >= 0.72:
            return True
        similarity = SequenceMatcher(
            None,
            normalized_candidate,
            prior,
            autojunk=False,
        ).ratio()
        if similarity >= similarity_threshold:
            return True
    return False


__all__ = [
    "AuthorIdentity",
    "RoomTurn",
    "autonomous_speech_allowed",
    "bounded_recent_turns",
    "count_human_turns_after_latest_self",
    "has_close_self_repeat",
    "human_turn_supports_autonomy",
    "is_bot_or_self_author",
    "is_human_turn",
    "is_self_author",
    "normalize_author_identity",
    "normalize_room_text",
]
