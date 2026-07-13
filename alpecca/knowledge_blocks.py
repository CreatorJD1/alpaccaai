"""Brain-section knowledge blocks: the innocence-scaffold's structural layer.

Alpecca's "innocence" is not model surgery -- it is a gate over *what she has
actually been taught*. This module owns the structural half of that gate: named
knowledge blocks arranged into brain-map sections (her memory kinds), each block
carrying a state (locked / unlockable / populated) and unlock metadata
(risk / reward / rate-limit / guarded).

Two deliberate boundaries, both required by the delegation plan:

  - **Unlock metadata is recorded here, never enforced in the hot path.** The
    risk/reward and rate-limit fields describe how costly relearning a section
    would be; actually taxing her energy/focus and requiring parent approval is
    governed learning (Phase 8 integration), wired later by the serial owner.
  - **Facts are not written here.** A block is a section of the brain-map; the
    *content* she was taught lives in :mod:`alpecca.taught_facts`, which links
    each fact to a block. That module also owns the authenticated-speaker
    teaching contract and honest, confidence-hedged recall.

The read-only :func:`brain_map_snapshot` combines both halves into the typed
shape the ``apps/house-hq`` brain-map visualization consumes: sections along a
bright->faded gradient (mirroring hot/warm/cold tiers) with per-node recall
confidence driving brightness and sharpness. It is strictly read-only -- it
never mutates a block, a fact, or her live memory.

Storage reuses the one hardened SQLite opener (:mod:`alpecca.db`) and the same
idempotent-schema / scope-bounding conventions as :mod:`alpecca.memory` and
:mod:`alpecca.mindpage`; it does not invent a new persistence style.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from config import DB_PATH

# --- Sections: her memory kinds arranged along the brain-map gradient -------
# Kept in lockstep with alpecca.memory.MEMORY_KINDS. `depth` orders the sections
# left (bright, sharp -- Active/Working + Episodic) to right (faded, archived --
# Long-Term / Musing); `tier_hint` mirrors the hot/warm/cold Mindpage tiers the
# vision maps the gradient onto. This is presentation metadata, not enforcement.
SECTION_SPEC: tuple[tuple[str, str, int, str], ...] = (
    ("episodic", "Active & Episodic", 0, "hot"),
    ("relationship", "Relational", 1, "hot"),
    ("self_model", "Self-Model", 2, "warm"),
    ("semantic", "Semantic", 3, "cold"),
    ("procedural", "Procedural", 4, "cold"),
    ("musing", "Long-Term / Musing", 5, "archived"),
)
SECTIONS: frozenset[str] = frozenset(kind for kind, _label, _depth, _tier in SECTION_SPEC)
_SECTION_META: dict[str, dict] = {
    kind: {"label": label, "depth": depth, "tier_hint": tier}
    for kind, label, depth, tier in SECTION_SPEC
}
DEFAULT_SECTION = "semantic"

# --- Block state machine ----------------------------------------------------
# locked      -> dark node she has not learned and cannot answer from
# unlockable  -> a candidate section a parent could open (recorded, not auto)
# populated   -> she has been taught at least one fact here and can recall it
STATES: frozenset[str] = frozenset({"locked", "unlockable", "populated"})
DEFAULT_STATE = "locked"
_STATE_RANK = {"locked": 0, "unlockable": 1, "populated": 2}

# Creator scope only in this first slice. Rygen (second parent) and any allowed
# teacher scopes arrive with the deferred identity lane; the column exists so
# that later widening is a data change, not a migration.
DEFAULT_SCOPE = "creator"

_schema_ready_paths: set[str] = set()


def _connect(db_path: Path = DB_PATH):
    """Delegate to the single hardened opener (busy_timeout, commit, close)."""
    from alpecca.db import connect as _db_connect

    return _db_connect(db_path)


def _scope(value: str) -> str:
    """Bound a scope label before it reaches SQLite (memory.py convention)."""
    clean = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", str(value or DEFAULT_SCOPE).strip())
    return (clean.strip("-._:") or DEFAULT_SCOPE)[:160]


def normalize_section(value: str) -> str:
    """Map an arbitrary label onto a known brain-map section, else the default."""
    kind = str(value or "").strip().lower()
    return kind if kind in SECTIONS else DEFAULT_SECTION


def _clamp01(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(0.0, min(1.0, number))


def _clean_name(value: str) -> str:
    name = " ".join(str(value or "").split())
    return name[:160]


def ensure_schema(db_path: Path = DB_PATH) -> None:
    """Create the block table + indexes idempotently; safe to call every time."""
    key = str(Path(db_path).resolve())
    if key in _schema_ready_paths:
        return
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_blocks (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                name               TEXT NOT NULL,
                section            TEXT NOT NULL,
                state              TEXT NOT NULL DEFAULT 'locked',
                scope              TEXT NOT NULL DEFAULT 'creator',
                risk               REAL NOT NULL DEFAULT 0.0,
                reward             REAL NOT NULL DEFAULT 0.0,
                rate_limit_per_day INTEGER NOT NULL DEFAULT 0,
                guarded            INTEGER NOT NULL DEFAULT 0,
                notes              TEXT NOT NULL DEFAULT '',
                created_at         REAL NOT NULL,
                updated_at         REAL NOT NULL,
                unlocked_at        REAL
            )
            """
        )
        # Backfill columns for any pre-existing table (same migration idiom as
        # mindpage.ensure_schema): add-if-missing, never drop.
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(knowledge_blocks)")}
        migrations = {
            "section": "TEXT NOT NULL DEFAULT 'semantic'",
            "state": "TEXT NOT NULL DEFAULT 'locked'",
            "scope": "TEXT NOT NULL DEFAULT 'creator'",
            "risk": "REAL NOT NULL DEFAULT 0.0",
            "reward": "REAL NOT NULL DEFAULT 0.0",
            "rate_limit_per_day": "INTEGER NOT NULL DEFAULT 0",
            "guarded": "INTEGER NOT NULL DEFAULT 0",
            "notes": "TEXT NOT NULL DEFAULT ''",
            "unlocked_at": "REAL",
        }
        for name, definition in migrations.items():
            if name not in cols:
                conn.execute(f"ALTER TABLE knowledge_blocks ADD COLUMN {name} {definition}")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS knowledge_blocks_scope_name_idx "
            "ON knowledge_blocks(scope, name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS knowledge_blocks_section_idx "
            "ON knowledge_blocks(scope, section, state)"
        )
    _schema_ready_paths.add(key)


def _row_to_block(row) -> dict:
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "section": str(row["section"]),
        "state": str(row["state"]),
        "scope": str(row["scope"]),
        "risk": float(row["risk"] or 0.0),
        "reward": float(row["reward"] or 0.0),
        "rate_limit_per_day": int(row["rate_limit_per_day"] or 0),
        "guarded": bool(row["guarded"]),
        "notes": str(row["notes"] or ""),
        "created_at": float(row["created_at"] or 0.0),
        "updated_at": float(row["updated_at"] or 0.0),
        "unlocked_at": (float(row["unlocked_at"]) if row["unlocked_at"] is not None else None),
    }


def create_block(name: str, section: str = DEFAULT_SECTION, *,
                 state: str = DEFAULT_STATE, scope: str = DEFAULT_SCOPE,
                 risk: float = 0.0, reward: float = 0.0,
                 rate_limit_per_day: int = 0, guarded: bool = False,
                 notes: str = "", now: float | None = None,
                 db_path: Path = DB_PATH) -> int:
    """Create (or return the existing) named block within a scope.

    Blocks are unique per ``(scope, name)``; a repeat call is idempotent and
    returns the existing id without disturbing its taught facts. ``risk``,
    ``reward``, ``rate_limit_per_day`` and ``guarded`` are recorded verbatim as
    unlock metadata -- this module never spends them.
    """
    ensure_schema(db_path)
    clean_name = _clean_name(name)
    if not clean_name:
        raise ValueError("knowledge block name must not be empty")
    section = normalize_section(section)
    state = state if state in STATES else DEFAULT_STATE
    scope = _scope(scope)
    stamp = float(time.time() if now is None else now)
    unlocked_at = stamp if state != "locked" else None
    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM knowledge_blocks WHERE scope=? AND name=?",
            (scope, clean_name),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO knowledge_blocks
                (name, section, state, scope, risk, reward, rate_limit_per_day,
                 guarded, notes, created_at, updated_at, unlocked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_name, section, state, scope,
                _clamp01(risk), _clamp01(reward), max(0, int(rate_limit_per_day)),
                1 if guarded else 0, str(notes or "")[:2000], stamp, stamp,
                unlocked_at,
            ),
        )
        return int(cur.lastrowid)


def get_block(identifier: int | str, *, scope: str = DEFAULT_SCOPE,
              db_path: Path = DB_PATH) -> dict | None:
    """Fetch one block by id (int) or by name within a scope (str)."""
    ensure_schema(db_path)
    scope = _scope(scope)
    with _connect(db_path) as conn:
        if isinstance(identifier, int):
            row = conn.execute(
                "SELECT * FROM knowledge_blocks WHERE id=? AND scope=?",
                (int(identifier), scope),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM knowledge_blocks WHERE scope=? AND name=?",
                (scope, _clean_name(identifier)),
            ).fetchone()
    return _row_to_block(row) if row else None


def list_blocks(*, scope: str = DEFAULT_SCOPE, section: str | None = None,
                db_path: Path = DB_PATH) -> list[dict]:
    """List blocks for a scope, optionally filtered to one section."""
    ensure_schema(db_path)
    scope = _scope(scope)
    with _connect(db_path) as conn:
        if section is None:
            rows = conn.execute(
                "SELECT * FROM knowledge_blocks WHERE scope=? "
                "ORDER BY section, name",
                (scope,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM knowledge_blocks WHERE scope=? AND section=? "
                "ORDER BY name",
                (scope, normalize_section(section)),
            ).fetchall()
    return [_row_to_block(row) for row in rows]


def set_state(block_id: int, state: str, *, now: float | None = None,
              db_path: Path = DB_PATH) -> dict | None:
    """Record a block's state (locked / unlockable / populated).

    This is a metadata write, not hot-path enforcement: it does not tax energy,
    does not check a rate limit, and does not require parent approval here. Those
    are governed-learning concerns wired at Phase 8. ``unlocked_at`` is stamped
    the first time a block leaves ``locked`` so the later governor has a record.
    """
    if state not in STATES:
        raise ValueError(f"unknown block state: {state!r}")
    ensure_schema(db_path)
    stamp = float(time.time() if now is None else now)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM knowledge_blocks WHERE id=?", (int(block_id),)
        ).fetchone()
        if not row:
            return None
        prior = str(row["state"])
        unlocked_at = row["unlocked_at"]
        if state != "locked" and unlocked_at is None:
            unlocked_at = stamp
        conn.execute(
            "UPDATE knowledge_blocks SET state=?, updated_at=?, unlocked_at=? WHERE id=?",
            (state, stamp, unlocked_at, int(block_id)),
        )
        updated = conn.execute(
            "SELECT * FROM knowledge_blocks WHERE id=?", (int(block_id),)
        ).fetchone()
    result = _row_to_block(updated)
    result["prior_state"] = prior
    return result


def mark_populated(block_id: int, *, now: float | None = None,
                   db_path: Path = DB_PATH) -> dict | None:
    """Promote a block to ``populated`` unless it already outranks that.

    Called by the teaching contract when a block first receives an authenticated
    fact: being taught something is exactly what makes a section 'lit'. A block
    already ``populated`` is left as-is (idempotent), and this never demotes.
    """
    ensure_schema(db_path)
    current = get_block(int(block_id), scope=DEFAULT_SCOPE, db_path=db_path)
    if current is None:
        # The block may live in a non-default scope; look it up by id directly.
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_blocks WHERE id=?", (int(block_id),)
            ).fetchone()
        if not row:
            return None
        current = _row_to_block(row)
    if _STATE_RANK.get(current["state"], 0) >= _STATE_RANK["populated"]:
        return current
    return set_state(int(block_id), "populated", now=now, db_path=db_path)


def resolve_block(*, block: int | str | None, section: str | None,
                  scope: str = DEFAULT_SCOPE, now: float | None = None,
                  db_path: Path = DB_PATH) -> int:
    """Resolve a fact's target block, creating a section default if needed.

    Accepts an explicit block id/name, or falls back to a per-section default
    block ("<section> knowledge") so a teacher can teach a bare fact without
    first hand-authoring a block. Used by :mod:`alpecca.taught_facts`.
    """
    ensure_schema(db_path)
    scope = _scope(scope)
    if isinstance(block, int):
        found = get_block(int(block), scope=scope, db_path=db_path)
        if found is None:
            raise ValueError(f"knowledge block id {block} not found in scope {scope!r}")
        return int(found["id"])
    if isinstance(block, str) and block.strip():
        section_for_new = normalize_section(section or DEFAULT_SECTION)
        return create_block(block, section_for_new, scope=scope, now=now, db_path=db_path)
    kind = normalize_section(section or DEFAULT_SECTION)
    return create_block(f"{kind} knowledge", kind, scope=scope, now=now, db_path=db_path)


# --- Read-only brain-map snapshot -------------------------------------------

def _brightness_from_confidence(confidence: float, state: str) -> float:
    """Map recall confidence + state to node brightness in [0, 1].

    A locked node is dark regardless of any (there shouldn't be) confidence; an
    unlockable node glimmers faintly; a populated node's brightness IS its recall
    confidence, so a well-reinforced fact reads bright and a fuzzy old one dim.
    """
    if state == "locked":
        return 0.06
    if state == "unlockable":
        return max(0.18, 0.18 + 0.12 * confidence)
    return max(0.2, _clamp01(confidence))


def brain_map_snapshot(*, scope: str = DEFAULT_SCOPE, now: float | None = None,
                       db_path: Path = DB_PATH) -> dict:
    """Return the typed, read-only data the brain-map visualization renders.

    Every brain-map section (memory kind) is always present -- even with zero
    blocks -- so the map shows locked/unexplored regions honestly. Per-node
    ``confidence`` comes from the *effective* (age-decayed, reinforcement-boosted)
    confidence of that block's taught facts; ``brightness`` and ``sharpness``
    encode it exactly as the vision's concept art does. This function only reads:
    it never mutates a block, a fact, salience, or memory.
    """
    ensure_schema(db_path)
    scope = _scope(scope)
    stamp = float(time.time() if now is None else now)

    # Lazy import breaks the blocks<->facts cycle (taught_facts imports us).
    from alpecca import taught_facts

    blocks = list_blocks(scope=scope, db_path=db_path)
    confidence_by_block = taught_facts.block_confidence_map(
        scope=scope, now=stamp, db_path=db_path
    )

    by_section: dict[str, list[dict]] = {kind: [] for kind in SECTIONS}
    for block in blocks:
        stats = confidence_by_block.get(block["id"], {"confidence": 0.0, "fact_count": 0})
        confidence = _clamp01(stats.get("confidence", 0.0))
        state = block["state"]
        node = {
            "id": block["id"],
            "name": block["name"],
            "state": state,
            "confidence": round(confidence, 4),
            "brightness": round(_brightness_from_confidence(confidence, state), 4),
            # Sharpness = how crisply she recalls it. Fuzzy/old facts render soft
            # (a low value the renderer turns into blur); a locked node is fully
            # dissolved.
            "sharpness": round(0.0 if state == "locked" else max(0.12, confidence), 4),
            "fact_count": int(stats.get("fact_count", 0)),
            "risk": round(block["risk"], 4),
            "reward": round(block["reward"], 4),
            "guarded": block["guarded"],
            "rate_limit_per_day": block["rate_limit_per_day"],
        }
        by_section.setdefault(block["section"], []).append(node)

    sections = []
    for kind, label, depth, tier in SECTION_SPEC:
        nodes = sorted(by_section.get(kind, []), key=lambda item: item["name"])
        populated = sum(1 for node in nodes if node["state"] == "populated")
        unlockable = sum(1 for node in nodes if node["state"] == "unlockable")
        locked = sum(1 for node in nodes if node["state"] == "locked")
        lit = [node["confidence"] for node in nodes if node["state"] == "populated"]
        section_confidence = round(sum(lit) / len(lit), 4) if lit else 0.0
        sections.append({
            "kind": kind,
            "label": label,
            "depth": depth,
            "tier_hint": tier,
            "block_count": len(nodes),
            "populated": populated,
            "unlockable": unlockable,
            "locked": locked,
            "confidence": section_confidence,
            "nodes": nodes,
        })

    return {
        "scope": scope,
        "generated_at": round(stamp, 3),
        "confidence_threshold": taught_facts.CONFIDENCE_THRESHOLD,
        "sections": sections,
        "legend": {
            "states": ["locked", "unlockable", "populated"],
            "encoding": "brightness+sharpness = recall confidence; sections = memory kinds",
        },
        "totals": {
            "blocks": len(blocks),
            "populated": sum(section["populated"] for section in sections),
            "unlockable": sum(section["unlockable"] for section in sections),
            "locked": sum(section["locked"] for section in sections),
        },
    }


__all__ = [
    "SECTION_SPEC",
    "SECTIONS",
    "STATES",
    "DEFAULT_SECTION",
    "DEFAULT_STATE",
    "DEFAULT_SCOPE",
    "ensure_schema",
    "normalize_section",
    "create_block",
    "get_block",
    "list_blocks",
    "set_state",
    "mark_populated",
    "resolve_block",
    "brain_map_snapshot",
]
