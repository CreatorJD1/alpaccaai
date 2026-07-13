"""Scoped, grounded preference/favorites storage (Lane Q foundation).

This is the honest seam between *hearing* something and *carrying a taste for
it*. When an authenticated speaker tells Alpecca she likes a song, or reinforces
that a favorite is still a favorite, that fact is recorded here -- with the real
source that supplied it, the scope it belongs to, when it happened, and a
grounded reason ("heard it, reinforced 3x"). Nothing is invented: a preference
row only ever exists because a real, authenticated speaker actually expressed it.

Why a dedicated store rather than a mood dimension: her homeostasis vector
(alpecca/homeostasis.py) is a *felt state* that decays; a preference is a durable
*fact about what she cares for*, closer to a memory or a desire than to a mood.
So this mirrors the desires.py persistence shape (config.DB_PATH + the one
hardened opener in alpecca/db.py, its own append-friendly table) rather than the
state vector.

GROUNDING + SAFETY (the non-negotiables this module enforces):

- **Guarded writes.** A preference can only be *written* by an authenticated,
  authorized source in an allowed scope. The authorization decision is injected
  (``authorize=`` / :class:`PreferenceAuthorizer`) so the hot-path owner supplies
  the real creator-identity check; the default authorizer is conservative and
  only admits the creator scope. An unauthorized write raises
  :class:`PreferenceWriteDenied` and stores nothing. Reads are open (the panel is
  read-only).
- **Every row cites its origin.** ``source`` (who said it), ``scope`` (whose
  preference it is), ``created_at`` / ``last_reinforced`` (when), and a plain
  ``reason`` are required on every row. Reinforcement bumps a real counter and
  refreshes the reason, so "reinforced 3x" is a count of real events, never a
  decoration.
- **No emotion claims.** A preference is a recorded taste, not a feeling. This
  module never asserts subjective experience; a cue may later *suggest* a
  response style through the existing Phase 4/5 envelope, but that wiring lives
  in the hot path, not here.

This module has no model calls, no network, and no hot-path affect mutation.
"""
from __future__ import annotations

import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Iterable, Protocol

from config import DB_PATH


# --- Vocabulary (closed sets keep her tastes legible and groundable) --------

# The kinds of thing she can hold a taste for. A small, closed set keeps the
# store honest and the read-only panel predictable. "song"/"music" are the
# Track F headline (music/favorites); the rest cover the everyday "favorite
# things" a companion picks up from real conversation.
CATEGORIES: tuple[str, ...] = (
    "song",
    "music",
    "artist",
    "food",
    "drink",
    "color",
    "place",
    "activity",
    "topic",
    "thing",
)

# Her stance toward the subject. Grounded, coarse, and symmetric: a companion
# can like, dislike, or hold a neutral/known-but-unfelt relationship to a thing.
SENTIMENTS: tuple[str, ...] = ("liked", "disliked", "neutral")

# The scopes a preference can belong to. "creator" is Jason's own taste that she
# has learned; "shared" is a taste that belongs to the space between them. Writes
# are only ever admitted for scopes in :data:`WRITABLE_SCOPES` below.
SCOPES: tuple[str, ...] = ("creator", "shared")

# Only these scopes may be *written* by the guarded API. Reads are unrestricted.
# The creator scope is the authenticated-owner scope; "shared" is admitted too
# because it still requires an authenticated, authorized source to assert it --
# the guard is on *authorization*, not on the scope label alone.
WRITABLE_SCOPES: frozenset[str] = frozenset({"creator", "shared"})

# The scope an authorization decision must be able to satisfy to write anything
# at all. The default authorizer treats the creator scope as the trust anchor.
CREATOR_SCOPE = "creator"

MAX_SUBJECT_CHARS = 160
MAX_SOURCE_CHARS = 80
MAX_REASON_CHARS = 240
MAX_LIST_ROWS = 500

# Source identifiers are opaque, bounded tokens (an actor id / authenticated
# handle). We never store free text as a source. Mirrors the source grammar used
# by alpecca/affect_evidence.py so an actor id that is valid there is valid here.
_SOURCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}\Z")


class PreferenceError(ValueError):
    """Base error for invalid preference input or a denied write."""


class PreferenceWriteDenied(PreferenceError):
    """A write was attempted without an authenticated, authorized source."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason.replace("_", " "))


# --- Authorization (injected; default is conservative) ----------------------


@dataclass(frozen=True, slots=True)
class WriteRequest:
    """The content-free description of a write, handed to the authorizer.

    The authorizer sees *who* is asking and *into which scope*; it never needs
    the subject text to make its decision, which keeps the trust boundary narrow.
    """

    source: str
    scope: str
    reinforcement: bool


class PreferenceAuthorizer(Protocol):
    """Decides whether one authenticated source may write into one scope."""

    def authorize(self, request: WriteRequest) -> bool: ...


@dataclass(frozen=True, slots=True)
class CreatorScopeAuthorizer:
    """Default guard: admit writes only from a recognized creator source.

    ``creator_sources`` is the set of authenticated actor identifiers the hot
    path has verified as the creator (e.g. the bridge's resolved creator actor
    id). With the default empty set this authorizer denies *every* write -- the
    store is fail-closed until the hot-path owner injects the real creator
    identity, exactly as the delegation plan intends for a foundation lane.
    """

    creator_sources: frozenset[str] = frozenset()

    def authorize(self, request: WriteRequest) -> bool:
        if request.scope not in WRITABLE_SCOPES:
            return False
        return request.source in self.creator_sources


# The one authenticated principal string the rest of the codebase treats as the
# creator (see alpecca/turn_context.py and the ``turn.principal != "creator"``
# gate in alpecca/mind.py). A preference write is authorized when the caller can
# assert this principal for the current turn.
CREATOR_PRINCIPAL = "creator"


@dataclass(frozen=True, slots=True)
class CreatorPrincipalAuthorizer:
    """Guard keyed on the turn's authenticated principal role.

    This mirrors the hot path's own creator gate exactly: a write is admitted
    only when the caller-asserted ``principal`` is ``"creator"`` and the target
    scope is writable. The hot-path owner already computes ``turn.principal``, so
    wiring is a one-liner: ``CreatorPrincipalAuthorizer(turn.principal)``. A guest
    or service principal (``"guest"``, ``"service:discord-bridge"``) is denied.
    """

    principal: str = ""

    def authorize(self, request: WriteRequest) -> bool:
        if request.scope not in WRITABLE_SCOPES:
            return False
        return self.principal == CREATOR_PRINCIPAL


def creator_principal_authorizer(principal: str) -> CreatorPrincipalAuthorizer:
    """Build the principal-keyed authorizer from a turn's principal string."""
    return CreatorPrincipalAuthorizer(principal=principal)


# A convenience alias for callers that want to pass a bare predicate instead of
# an object with ``.authorize``.
AuthorizeCallable = Callable[[WriteRequest], bool]


def _resolve_authorizer(
    authorize: PreferenceAuthorizer | AuthorizeCallable | None,
) -> AuthorizeCallable:
    if authorize is None:
        return CreatorScopeAuthorizer().authorize
    method = getattr(authorize, "authorize", None)
    if callable(method):
        return method  # type: ignore[return-value]
    if callable(authorize):
        return authorize
    raise TypeError("authorize must be a PreferenceAuthorizer or a callable")


# --- Row model --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Preference:
    """One recorded, grounded taste."""

    id: int
    scope: str
    source: str
    category: str
    subject: str
    sentiment: str
    strength: float
    reinforcement: int
    reason: str
    created_at: float
    last_reinforced: float
    status: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


# --- Validation helpers -----------------------------------------------------


def _clean_text(value: object, *, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise PreferenceError(f"{name}_not_text")
    cleaned = " ".join(value.split())
    if not cleaned:
        raise PreferenceError(f"{name}_required")
    if any(ord(char) < 32 for char in cleaned):
        raise PreferenceError(f"{name}_has_control_characters")
    if len(cleaned) > maximum:
        raise PreferenceError(f"{name}_too_long")
    return cleaned


def _source(value: object) -> str:
    if not isinstance(value, str) or _SOURCE_RE.fullmatch(value) is None:
        raise PreferenceError("invalid_source")
    if len(value) > MAX_SOURCE_CHARS:
        raise PreferenceError("source_too_long")
    return value


def _member(value: object, allowed: tuple[str, ...], *, name: str) -> str:
    if value not in allowed:
        raise PreferenceError(f"invalid_{name}")
    return value  # type: ignore[return-value]


def _strength(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PreferenceError("invalid_strength")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise PreferenceError("invalid_strength")
    return max(0.0, min(1.0, number))


# --- Persistence ------------------------------------------------------------


@contextmanager
def _connect(db_path: Path):
    """Delegate to the one hardened opener (see alpecca/db.py)."""
    from alpecca.db import connect as _db_connect

    with _db_connect(db_path) as conn:
        yield conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Create the preferences table if absent. Safe to call on every startup."""
    from alpecca.db import harden

    harden(db_path)
    with _connect(db_path) as conn:
        conn.executescript(
            """
            -- Her recorded tastes. Every row is grounded: `source` is the
            -- authenticated speaker who supplied it, `scope` whose taste it is,
            -- `reason` a plain account of why it's held, `reinforcement` a count
            -- of real repeat expressions. See alpecca/preferences.py.
            CREATE TABLE IF NOT EXISTS preferences (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                scope           TEXT NOT NULL,
                source          TEXT NOT NULL,
                category        TEXT NOT NULL,
                subject         TEXT NOT NULL,
                sentiment       TEXT NOT NULL,
                strength        REAL NOT NULL,
                reinforcement   INTEGER NOT NULL DEFAULT 1,
                reason          TEXT NOT NULL,
                created_at      REAL NOT NULL,
                last_reinforced REAL NOT NULL,
                status          TEXT NOT NULL DEFAULT 'active'
            );

            -- One live taste per (scope, category, subject): a repeat expression
            -- reinforces the existing row rather than piling up duplicates.
            CREATE UNIQUE INDEX IF NOT EXISTS preferences_identity_idx
            ON preferences(scope, category, subject) WHERE status='active';

            CREATE INDEX IF NOT EXISTS preferences_scope_strength_idx
            ON preferences(scope, strength DESC, last_reinforced DESC);
            """
        )


def _row_to_preference(row) -> Preference:
    return Preference(
        id=int(row["id"]),
        scope=str(row["scope"]),
        source=str(row["source"]),
        category=str(row["category"]),
        subject=str(row["subject"]),
        sentiment=str(row["sentiment"]),
        strength=float(row["strength"]),
        reinforcement=int(row["reinforcement"]),
        reason=str(row["reason"]),
        created_at=float(row["created_at"]),
        last_reinforced=float(row["last_reinforced"]),
        status=str(row["status"]),
    )


def record_preference(
    *,
    subject: str,
    category: str,
    sentiment: str,
    source: str,
    scope: str = CREATOR_SCOPE,
    reason: str,
    strength: float = 0.6,
    authorize: PreferenceAuthorizer | AuthorizeCallable | None = None,
    now: float | None = None,
    db_path: Path = DB_PATH,
) -> Preference:
    """Record (or reinforce) one grounded preference through the guarded write.

    The write is admitted only if the injected ``authorize`` decision returns
    True for this ``source``/``scope``; otherwise :class:`PreferenceWriteDenied`
    is raised and nothing is stored. On a repeat of an existing
    (scope, category, subject) the row is *reinforced*: its strength moves toward
    the new strength, its ``reinforcement`` counter increments, ``reason`` is
    refreshed, and ``last_reinforced`` advances -- so "reinforced Nx" is always a
    true count. ``source`` and ``scope`` are re-validated on every reinforcement,
    keeping the origin honest.
    """
    subject = _clean_text(subject, name="subject", maximum=MAX_SUBJECT_CHARS)
    category = _member(category, CATEGORIES, name="category")
    sentiment = _member(sentiment, SENTIMENTS, name="sentiment")
    source = _source(source)
    scope = _member(scope, SCOPES, name="scope")
    reason = _clean_text(reason, name="reason", maximum=MAX_REASON_CHARS)
    strength = _strength(strength)
    stamp = time.time() if now is None else float(now)

    decide = _resolve_authorizer(authorize)

    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT * FROM preferences "
            "WHERE scope=? AND category=? AND subject=? AND status='active'",
            (scope, category, subject),
        ).fetchone()

        request = WriteRequest(
            source=source, scope=scope, reinforcement=existing is not None
        )
        if not decide(request):
            raise PreferenceWriteDenied("unauthorized_source_or_scope")

        if existing is None:
            cur = conn.execute(
                "INSERT INTO preferences "
                "(scope, source, category, subject, sentiment, strength, "
                " reinforcement, reason, created_at, last_reinforced, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 'active')",
                (
                    scope,
                    source,
                    category,
                    subject,
                    sentiment,
                    strength,
                    reason,
                    stamp,
                    stamp,
                ),
            )
            new_id = int(cur.lastrowid)
        else:
            new_count = int(existing["reinforcement"]) + 1
            # Reinforcement nudges strength toward the fresh expression rather
            # than snapping, so a taste firms up over repeated real mentions.
            blended = float(existing["strength"]) + 0.5 * (
                strength - float(existing["strength"])
            )
            conn.execute(
                "UPDATE preferences SET sentiment=?, strength=?, "
                "reinforcement=?, reason=?, source=?, last_reinforced=? "
                "WHERE id=?",
                (
                    sentiment,
                    _strength(blended),
                    new_count,
                    reason,
                    source,
                    stamp,
                    int(existing["id"]),
                ),
            )
            new_id = int(existing["id"])

        row = conn.execute(
            "SELECT * FROM preferences WHERE id=?", (new_id,)
        ).fetchone()
    return _row_to_preference(row)


def retire_preference(
    preference_id: int,
    *,
    source: str,
    scope: str,
    authorize: PreferenceAuthorizer | AuthorizeCallable | None = None,
    now: float | None = None,
    db_path: Path = DB_PATH,
) -> bool:
    """Guarded soft-delete: mark one active preference retired.

    Retiring is a write, so it goes through the same authorization guard. The
    row is never hard-deleted (grounding evidence is preserved); it simply stops
    being an active taste. Returns True if a row was retired.
    """
    source = _source(source)
    scope = _member(scope, SCOPES, name="scope")
    stamp = time.time() if now is None else float(now)
    decide = _resolve_authorizer(authorize)
    if not decide(WriteRequest(source=source, scope=scope, reinforcement=False)):
        raise PreferenceWriteDenied("unauthorized_source_or_scope")
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE preferences SET status='retired', last_reinforced=? "
            "WHERE id=? AND scope=? AND status='active'",
            (stamp, int(preference_id), scope),
        )
        return cur.rowcount > 0


# --- Read API (open; the panel is read-only) --------------------------------


def list_preferences(
    *,
    scope: str | None = None,
    sentiment: str | None = None,
    limit: int = 100,
    db_path: Path = DB_PATH,
) -> list[Preference]:
    """Active tastes, strongest first, optionally filtered by scope/sentiment."""
    limit = max(1, min(int(limit), MAX_LIST_ROWS))
    clauses = ["status='active'"]
    params: list[object] = []
    if scope is not None:
        clauses.append("scope=?")
        params.append(_member(scope, SCOPES, name="scope"))
    if sentiment is not None:
        clauses.append("sentiment=?")
        params.append(_member(sentiment, SENTIMENTS, name="sentiment"))
    where = " AND ".join(clauses)
    params.append(limit)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM preferences WHERE {where} "
            "ORDER BY strength DESC, last_reinforced DESC LIMIT ?",
            params,
        ).fetchall()
    return [_row_to_preference(r) for r in rows]


def favorites(
    *, scope: str | None = None, limit: int = 20, db_path: Path = DB_PATH
) -> list[Preference]:
    """Her liked tastes only -- the "favorites" the read-only panel shows."""
    return [
        p
        for p in list_preferences(
            scope=scope, sentiment="liked", limit=limit, db_path=db_path
        )
    ]


def summary(*, db_path: Path = DB_PATH) -> dict[str, object]:
    """A compact, grounded read of her tastes for introspection and the panel."""
    active = list_preferences(limit=MAX_LIST_ROWS, db_path=db_path)
    liked = [p for p in active if p.sentiment == "liked"]
    disliked = [p for p in active if p.sentiment == "disliked"]
    by_category: dict[str, int] = {}
    for pref in active:
        by_category[pref.category] = by_category.get(pref.category, 0) + 1
    top = max(liked, key=lambda p: p.strength, default=None)
    return {
        "total": len(active),
        "liked": len(liked),
        "disliked": len(disliked),
        "by_category": by_category,
        "top_favorite": top.subject if top is not None else "",
    }


def snapshot(*, limit: int = 20, db_path: Path = DB_PATH) -> dict[str, object]:
    """A read-only, serializable snapshot for the frontend panel.

    Shape is deliberately flat and JSON-friendly so a future read-only endpoint
    (an integration request, not built here) can return it verbatim and the
    preferencesPanel.ts renderer can consume it without transformation.
    """
    favs = favorites(limit=limit, db_path=db_path)
    return {
        "schema": "alpecca.preferences.snapshot.v1",
        "summary": summary(db_path=db_path),
        "favorites": [p.as_dict() for p in favs],
    }


__all__ = [
    "CATEGORIES",
    "CREATOR_PRINCIPAL",
    "CREATOR_SCOPE",
    "CreatorPrincipalAuthorizer",
    "CreatorScopeAuthorizer",
    "Preference",
    "PreferenceAuthorizer",
    "PreferenceError",
    "PreferenceWriteDenied",
    "SCOPES",
    "SENTIMENTS",
    "WRITABLE_SCOPES",
    "WriteRequest",
    "creator_principal_authorizer",
    "favorites",
    "init_db",
    "list_preferences",
    "record_preference",
    "retire_preference",
    "snapshot",
    "summary",
]
