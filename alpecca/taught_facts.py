"""Taught facts: what Alpecca actually knows, and how honestly she recalls it.

This is the content half of the innocence gate (its structural half -- the
brain-map sections/blocks -- lives in :mod:`alpecca.knowledge_blocks`). Two hard
guarantees define this module:

**The teaching contract.** A fact is written ONLY from an *authenticated
speaker's actual input* -- never from the model's latent knowledge and never
from a self-prompt. This is enforced structurally, not by a trusting string
argument:

  - A :class:`SpeakerIdentity` that authorizes teaching can only be minted by
    :func:`authenticate_speaker` from a positive authorization decision whose
    principal is an allowed teacher (creator scope in this first slice). The
    minted identity carries a module-private witness token; :func:`teach_fact`
    refuses any speaker lacking it. A hand-built ``SpeakerIdentity`` -- the shape
    a self-prompt could fabricate -- has no witness and is rejected.
  - Provenance must be genuine input (``spoken`` / ``typed`` /
    ``authenticated_input``). A provenance of ``model`` / ``self`` /
    ``inference`` / ``latent`` is refused outright, so "I already know this from
    pre-training" can never become a stored fact.

**Honest recall.** Every fact carries a stored confidence and a reinforcement
count. :func:`recall` returns the *effective* confidence -- decayed by age,
lifted by repetition -- so fresh/repeated facts read confident and old/deep
detail reads fuzzy. Crucially, fuzzy is not fabricated: below
:data:`CONFIDENCE_THRESHOLD` the result is flagged so the caller HEDGES ("I
think... not sure of the exact detail"), and a query with no taught match
returns ``disposition == "unknown"`` so the caller says "I haven't learned
that." This module never invents fact text.

Storage reuses the hardened SQLite opener and the keyword-overlap matching style
of :mod:`alpecca.memory`; it introduces no new persistence pattern.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from config import DB_PATH
from alpecca import knowledge_blocks

# --- Teaching contract constants --------------------------------------------
# Creator scope only in this first slice; the second parent (Rygen) and any
# allowed teachers arrive with the deferred identity lane. Widening this set is
# the single change that grants another authenticated teacher.
ALLOWED_TEACHER_PRINCIPALS: frozenset[str] = frozenset({"creator"})
# Principals that must NEVER be able to teach, even if somehow marked authorized.
# "self"/"assistant"/"alpecca"/"model"/"system" close the self-prompt path;
# "guest"/"service:*" are unauthenticated-for-teaching by policy.
_FORBIDDEN_PRINCIPALS: frozenset[str] = frozenset(
    {"", "self", "assistant", "alpecca", "model", "system", "guest"}
)
# Provenance values that represent genuine authenticated input vs. latent model
# knowledge or self-generation. Only the former may be stored.
GENUINE_PROVENANCE: frozenset[str] = frozenset({"spoken", "typed", "authenticated_input"})
_FORBIDDEN_PROVENANCE: frozenset[str] = frozenset(
    {"model", "self", "inference", "latent", "pretrained", "generated"}
)

# Below this effective confidence she must hedge or say she does not remember
# exactly; a query with no match at all is "unknown" (haven't learned that).
CONFIDENCE_THRESHOLD = 0.35
# Recall fades over ~30 days to "fuzzy" unless reinforced; deterministic and
# testable via the injectable `now`.
_CONFIDENCE_HALFLIFE_DAYS = 30.0
# A fact is a candidate only if the query and fact share enough content: at
# least ~a quarter of the question's content words, or a stronger Jaccard/exact
# match. Below this she has not been taught the answer and says so.
_LEXICAL_FLOOR = 0.24

DEFAULT_SCOPE = knowledge_blocks.DEFAULT_SCOPE

_schema_ready_paths: set[str] = set()

# Module-private witness. A SpeakerIdentity is only trusted for teaching if it
# carries THIS exact object, and the only code that stamps it is
# authenticate_speaker below. It is deliberately not exported.
_WITNESS = object()

_WORD = re.compile(r"[a-z0-9']+")
_STOP = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "is",
    "it", "i", "you", "me", "my", "your", "we", "they", "this", "that", "with",
    "was", "are", "be", "as", "at", "so", "do", "did", "have", "has",
}


class TeachingRefused(PermissionError):
    """Raised when a write is not backed by an authenticated speaker + genuine
    input. It is a refusal, not a bug: catching it is how a caller learns that a
    teaching attempt was correctly rejected."""


@dataclass(frozen=True, slots=True)
class SpeakerIdentity:
    """An authenticated speaker, as far as the teaching contract is concerned.

    Only :func:`authenticate_speaker` mints an instance that :func:`teach_fact`
    will trust: it alone sets ``verified=True`` and stamps the private witness.
    Any instance built by other code (the shape a self-prompt could forge) has
    ``verified=False`` and no witness, and is refused.
    """

    speaker_id: str
    principal: str
    verified: bool = False
    _witness: object = field(default=None, repr=False, compare=False)

    @property
    def can_teach(self) -> bool:
        return (
            self.verified
            and self._witness is _WITNESS
            and self.principal in ALLOWED_TEACHER_PRINCIPALS
            and self.principal not in _FORBIDDEN_PRINCIPALS
        )


def authenticate_speaker(decision: object, *, speaker_id: str | None = None) -> SpeakerIdentity:
    """Mint a teaching-authorized speaker from a positive authorization decision.

    ``decision`` is duck-typed against :class:`alpecca.auth.AuthDecision`: it
    must expose a truthy ``authorized`` (or ``allowed``) and a ``principal``
    string. A rejected decision, a non-teacher principal (guest, a bridge
    service, self/model), or a forbidden principal yields an *unverified*
    identity that :func:`teach_fact` will refuse -- this function never raises,
    so callers can safely offer any decision and let the write be the gate.
    """
    authorized = bool(
        getattr(decision, "authorized", None)
        if getattr(decision, "authorized", None) is not None
        else getattr(decision, "allowed", False)
    )
    principal = str(getattr(decision, "principal", "") or "").strip().lower()
    resolved_id = str(speaker_id or principal or "").strip()[:160]
    if (
        authorized
        and principal in ALLOWED_TEACHER_PRINCIPALS
        and principal not in _FORBIDDEN_PRINCIPALS
    ):
        return SpeakerIdentity(
            speaker_id=resolved_id or principal,
            principal=principal,
            verified=True,
            _witness=_WITNESS,
        )
    return SpeakerIdentity(speaker_id=resolved_id, principal=principal, verified=False)


def _connect(db_path: Path = DB_PATH):
    from alpecca.db import connect as _db_connect

    return _db_connect(db_path)


def _tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(str(text or "").lower()) if w not in _STOP and len(w) > 1]


def _normalize(text: str) -> str:
    """A stable key for reinforcement matching: lowercased significant tokens."""
    return " ".join(sorted(set(_tokenize(text))))


def _similarity(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb)


def _coverage(query: list[str], haystack: list[str]) -> float:
    """Fraction of the query's content words present in the fact.

    Jaccard alone under-rates a short question against a longer fact (many fact
    tokens the query lacks); coverage asks the honest question instead -- "how
    much of what she was ASKED about does she actually hold?" A query with no
    shared content word scores 0, so an unrelated question still reads as
    "haven't learned that".
    """
    q = set(query)
    if not q:
        return 0.0
    hs = set(haystack)
    return sum(1 for token in q if token in hs) / len(q)


def ensure_schema(db_path: Path = DB_PATH) -> None:
    """Create the taught_facts table + indexes idempotently."""
    key = str(Path(db_path).resolve())
    if key in _schema_ready_paths:
        return
    knowledge_blocks.ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS taught_facts (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                block_id            INTEGER NOT NULL,
                text                TEXT NOT NULL,
                normalized          TEXT NOT NULL DEFAULT '',
                speaker_id          TEXT NOT NULL,
                principal           TEXT NOT NULL,
                provenance          TEXT NOT NULL DEFAULT 'spoken',
                confidence          REAL NOT NULL DEFAULT 0.6,
                reinforcement_count INTEGER NOT NULL DEFAULT 1,
                scope               TEXT NOT NULL DEFAULT 'creator',
                first_taught        REAL NOT NULL,
                last_taught         REAL NOT NULL
            )
            """
        )
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(taught_facts)")}
        migrations = {
            "normalized": "TEXT NOT NULL DEFAULT ''",
            "provenance": "TEXT NOT NULL DEFAULT 'spoken'",
            "reinforcement_count": "INTEGER NOT NULL DEFAULT 1",
            "scope": "TEXT NOT NULL DEFAULT 'creator'",
        }
        for name, definition in migrations.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE taught_facts ADD COLUMN {name} {definition}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS taught_facts_block_idx ON taught_facts(block_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS taught_facts_scope_idx ON taught_facts(scope, last_taught DESC)"
        )
    _schema_ready_paths.add(key)


def _require_authenticated(speaker: object) -> SpeakerIdentity:
    if not isinstance(speaker, SpeakerIdentity):
        raise TeachingRefused(
            "teach_fact requires an authenticated SpeakerIdentity from "
            "authenticate_speaker(); a plain value is not a speaker."
        )
    if not speaker.can_teach:
        raise TeachingRefused(
            f"speaker {speaker.speaker_id or '<unknown>'!r} (principal "
            f"{speaker.principal or '<none>'!r}) is not an authenticated teacher; "
            "facts are written only from an allowed authenticated speaker."
        )
    return speaker


def _check_provenance(provenance: str) -> str:
    value = str(provenance or "").strip().lower()
    if value in _FORBIDDEN_PROVENANCE:
        raise TeachingRefused(
            f"provenance {value!r} is latent/self-sourced; facts must come from "
            "genuine authenticated input, never model knowledge or self-prompt."
        )
    if value not in GENUINE_PROVENANCE:
        raise TeachingRefused(
            f"provenance {value!r} is not a recognized authenticated-input source "
            f"(expected one of {sorted(GENUINE_PROVENANCE)})."
        )
    return value


def teach_fact(text: str, speaker: SpeakerIdentity, *,
               block: int | str | None = None, section: str | None = None,
               confidence: float = 0.6, provenance: str = "spoken",
               scope: str | None = None, now: float | None = None,
               db_path: Path = DB_PATH) -> dict:
    """Store a fact from an authenticated speaker, or refuse.

    Guards, in order: the speaker must be a witnessed :class:`SpeakerIdentity`
    (``TeachingRefused`` otherwise); the provenance must be genuine input; the
    text must be non-empty. Teaching a fact identical (by normalized key) to an
    existing one in the same block *reinforces* it -- bumping its reinforcement
    count, lifting its confidence, and refreshing ``last_taught`` -- rather than
    duplicating. The target block is resolved/created and promoted to
    ``populated``. Returns the stored fact row (with ``reinforced``).
    """
    speaker = _require_authenticated(speaker)
    provenance = _check_provenance(provenance)
    clean = " ".join(str(text or "").split())
    if not clean:
        raise TeachingRefused("cannot teach an empty fact")
    resolved_scope = knowledge_blocks._scope(scope if scope is not None else speaker.principal)
    stamp = float(time.time() if now is None else now)
    base_conf = knowledge_blocks._clamp01(confidence, default=0.6)
    ensure_schema(db_path)

    block_id = knowledge_blocks.resolve_block(
        block=block, section=section, scope=resolved_scope, now=stamp, db_path=db_path
    )
    normalized = _normalize(clean)

    with _connect(db_path) as conn:
        existing = None
        if normalized:
            existing = conn.execute(
                "SELECT * FROM taught_facts WHERE block_id=? AND scope=? AND normalized=? "
                "ORDER BY id LIMIT 1",
                (int(block_id), resolved_scope, normalized),
            ).fetchone()
        if existing:
            count = int(existing["reinforcement_count"] or 1) + 1
            # Reinforcement lifts confidence toward 1 with diminishing returns and
            # never lowers what was already stored.
            lifted = max(
                float(existing["confidence"] or 0.0),
                base_conf,
                1.0 - (1.0 - base_conf) * (0.85 ** (count - 1)),
            )
            conn.execute(
                "UPDATE taught_facts SET reinforcement_count=?, confidence=?, "
                "last_taught=?, text=?, speaker_id=?, principal=?, provenance=? WHERE id=?",
                (
                    count, knowledge_blocks._clamp01(lifted), stamp, clean,
                    speaker.speaker_id, speaker.principal, provenance,
                    int(existing["id"]),
                ),
            )
            fact_id = int(existing["id"])
            reinforced = True
        else:
            cur = conn.execute(
                """
                INSERT INTO taught_facts
                    (block_id, text, normalized, speaker_id, principal, provenance,
                     confidence, reinforcement_count, scope, first_taught, last_taught)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    int(block_id), clean, normalized, speaker.speaker_id,
                    speaker.principal, provenance, base_conf, resolved_scope,
                    stamp, stamp,
                ),
            )
            fact_id = int(cur.lastrowid)
            reinforced = False

    knowledge_blocks.mark_populated(int(block_id), now=stamp, db_path=db_path)
    stored = get_fact(fact_id, db_path=db_path) or {}
    stored["reinforced"] = reinforced
    return stored


def _row_to_fact(row) -> dict:
    return {
        "id": int(row["id"]),
        "block_id": int(row["block_id"]),
        "text": str(row["text"]),
        "normalized": str(row["normalized"] or ""),
        "speaker_id": str(row["speaker_id"]),
        "principal": str(row["principal"]),
        "provenance": str(row["provenance"]),
        "confidence": float(row["confidence"] or 0.0),
        "reinforcement_count": int(row["reinforcement_count"] or 1),
        "scope": str(row["scope"]),
        "first_taught": float(row["first_taught"] or 0.0),
        "last_taught": float(row["last_taught"] or 0.0),
    }


def get_fact(fact_id: int, *, db_path: Path = DB_PATH) -> dict | None:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM taught_facts WHERE id=?", (int(fact_id),)
        ).fetchone()
    return _row_to_fact(row) if row else None


def effective_confidence(fact: dict, *, now: float | None = None) -> float:
    """Age-decayed, reinforcement-boosted recall confidence in [0, 1].

    Fresh + repeated facts stay near their stored confidence; an old fact fades
    toward 0 (fuzzy) unless it was reinforced enough to resist decay. This is a
    pure function of the row so tests can pin ``now`` and assert honest hedging.
    """
    stamp = float(time.time() if now is None else now)
    stored = knowledge_blocks._clamp01(fact.get("confidence", 0.0))
    last = float(fact.get("last_taught", 0.0) or 0.0)
    count = max(1, int(fact.get("reinforcement_count", 1) or 1))
    age_days = max(0.0, (stamp - last) / 86400.0)
    recency = 1.0 / (1.0 + age_days / _CONFIDENCE_HALFLIFE_DAYS)  # 1.0 fresh -> fades
    # Repetition both raises the floor and slows the fade: a fact taught many
    # times stays sharp far longer than a one-off remark.
    reinforce = 1.0 - (1.0 / (1.0 + (count - 1) * 0.75))  # 0 at count 1 -> ->1
    recency_effective = recency + (1.0 - recency) * reinforce
    return knowledge_blocks._clamp01(stored * recency_effective)


def _disposition(effective: float, found: bool) -> str:
    if not found:
        return "unknown"
    return "confident" if effective >= CONFIDENCE_THRESHOLD else "hedged"


def recall(query: str, *, scope: str = DEFAULT_SCOPE, top_k: int = 3,
           now: float | None = None, db_path: Path = DB_PATH) -> list[dict]:
    """Return taught facts relevant to ``query``, each with honest confidence.

    Matching is keyword overlap over the fact text plus its block name, with an
    exact-substring boost -- the same lexical-fallback spirit as memory recall.
    Each result carries ``effective_confidence``, ``confident`` (>= threshold),
    and ``disposition`` (``confident`` / ``hedged``). Results below the floor of
    relevance are dropped; this never fabricates text. An empty list means she
    has not been taught anything matching -- the caller should say so.
    """
    ensure_schema(db_path)
    scope = knowledge_blocks._scope(scope)
    stamp = float(time.time() if now is None else now)
    q_tokens = _tokenize(query)
    q_exact = " ".join(str(query or "").split()).lower()
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT f.*, b.name AS block_name, b.section AS block_section,
                   b.state AS block_state
            FROM taught_facts AS f
            JOIN knowledge_blocks AS b ON b.id = f.block_id
            WHERE f.scope=?
            ORDER BY f.last_taught DESC
            LIMIT 500
            """,
            (scope,),
        ).fetchall()
    scored: list[tuple[float, dict]] = []
    for row in rows:
        fact = _row_to_fact(row)
        haystack_tokens = _tokenize(f"{fact['text']} {row['block_name']}")
        sim = max(_similarity(q_tokens, haystack_tokens), _coverage(q_tokens, haystack_tokens))
        text_l = str(fact["text"]).lower()
        if q_exact and len(q_exact) >= 4 and q_exact in text_l:
            sim = max(sim, 1.0)
        if sim <= _LEXICAL_FLOOR:
            continue
        eff = effective_confidence(fact, now=stamp)
        item = dict(fact)
        item["block_name"] = str(row["block_name"])
        item["section"] = str(row["block_section"])
        item["match"] = round(sim, 4)
        item["effective_confidence"] = round(eff, 4)
        item["confident"] = eff >= CONFIDENCE_THRESHOLD
        item["disposition"] = _disposition(eff, found=True)
        # Relevance orders by lexical match first, then how well she recalls it.
        scored.append((0.7 * sim + 0.3 * eff, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in scored[: max(1, int(top_k))]]


def recall_answer(query: str, *, scope: str = DEFAULT_SCOPE,
                  now: float | None = None, db_path: Path = DB_PATH) -> dict:
    """Answer honestly from taught knowledge only.

    Returns a small verdict the caller can turn into speech without inventing
    anything:

      - ``disposition == "unknown"``  -> no taught match; say "I haven't learned
        that" (``text`` is ``None``).
      - ``disposition == "hedged"``   -> a match she recalls fuzzily; hedge, e.g.
        "I think... but I'm not sure of the exact detail."
      - ``disposition == "confident"``-> a match above threshold; recall plainly.

    ``text`` is only ever a genuinely stored fact -- never a fabrication.
    """
    hits = recall(query, scope=scope, top_k=1, now=now, db_path=db_path)
    if not hits:
        return {
            "found": False,
            "disposition": "unknown",
            "text": None,
            "effective_confidence": 0.0,
            "confident": False,
            "hedge": None,
        }
    best = hits[0]
    disposition = best["disposition"]
    hedge = None
    if disposition == "hedged":
        hedge = "I think so, but I'm not sure of the exact detail."
    return {
        "found": True,
        "disposition": disposition,
        "text": best["text"],
        "block_id": best["block_id"],
        "block_name": best.get("block_name"),
        "section": best.get("section"),
        "effective_confidence": best["effective_confidence"],
        "confident": best["confident"],
        "reinforcement_count": best["reinforcement_count"],
        "hedge": hedge,
    }


def block_confidence_map(*, scope: str = DEFAULT_SCOPE, now: float | None = None,
                         db_path: Path = DB_PATH) -> dict[int, dict]:
    """Per-block recall confidence + fact count for the brain-map snapshot.

    A block's confidence is the MAX effective confidence across its facts -- the
    single fact she recalls most sharply is what makes the node glow. Read-only.
    """
    ensure_schema(db_path)
    scope = knowledge_blocks._scope(scope)
    stamp = float(time.time() if now is None else now)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM taught_facts WHERE scope=?", (scope,)
        ).fetchall()
    out: dict[int, dict] = {}
    for row in rows:
        fact = _row_to_fact(row)
        eff = effective_confidence(fact, now=stamp)
        entry = out.setdefault(fact["block_id"], {"confidence": 0.0, "fact_count": 0})
        entry["fact_count"] += 1
        if eff > entry["confidence"]:
            entry["confidence"] = eff
    return out


def facts_for_block(block_id: int, *, db_path: Path = DB_PATH) -> list[dict]:
    ensure_schema(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM taught_facts WHERE block_id=? ORDER BY last_taught DESC",
            (int(block_id),),
        ).fetchall()
    return [_row_to_fact(row) for row in rows]


__all__ = [
    "ALLOWED_TEACHER_PRINCIPALS",
    "GENUINE_PROVENANCE",
    "CONFIDENCE_THRESHOLD",
    "TeachingRefused",
    "SpeakerIdentity",
    "authenticate_speaker",
    "ensure_schema",
    "teach_fact",
    "get_fact",
    "effective_confidence",
    "recall",
    "recall_answer",
    "block_confidence_map",
    "facts_for_block",
]
