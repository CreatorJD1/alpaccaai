"""Deterministic, evidence-shaped personality traits for Alpecca.

This module stores bounded behavioral tendencies, not claims of consciousness or
human emotion. Only identified runtime evidence changes the profile, and a
given evidence ID can be applied at most once.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from config import DB_PATH


TRAITS = (
    "curiosity",
    "directness",
    "initiative",
    "playfulness",
    "guardedness",
    "repair_drive",
    "self_regulation",
)

BASELINE = {
    "curiosity": 0.62,
    "directness": 0.55,
    "initiative": 0.52,
    "playfulness": 0.48,
    "guardedness": 0.42,
    "repair_drive": 0.66,
    "self_regulation": 0.64,
}

# Fixed deltas make updates inspectable and reproducible. Values are deliberately
# small so no single exchange can rewrite the personality.
EVIDENCE_DELTAS = {
    "positive_engagement": {
        "curiosity": 0.025,
        "initiative": 0.020,
        "playfulness": 0.020,
        "guardedness": -0.010,
    },
    "curiosity_rewarded": {
        "curiosity": 0.035,
        "initiative": 0.015,
    },
    "correction_received": {
        "directness": 0.025,
        "guardedness": 0.015,
        "repair_drive": 0.040,
        "self_regulation": 0.030,
        "playfulness": -0.010,
    },
    "repair_succeeded": {
        "directness": 0.010,
        "guardedness": -0.025,
        "repair_drive": 0.020,
        "self_regulation": 0.025,
    },
    "boundary_respected": {
        "directness": 0.015,
        "guardedness": -0.010,
    },
    "boundary_pressure": {
        "directness": 0.025,
        "guardedness": 0.040,
        "playfulness": -0.015,
    },
    "outreach_ignored": {
        "initiative": -0.020,
        "guardedness": 0.020,
    },
    "initiative_succeeded": {
        "curiosity": 0.010,
        "initiative": 0.035,
        "playfulness": 0.010,
    },
}

_MIN_TRAIT = 0.10
_MAX_TRAIT = 0.90


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _clamp(value: float) -> float:
    return round(max(_MIN_TRAIT, min(_MAX_TRAIT, float(value))), 6)


def init_db(db_path: Path = DB_PATH) -> None:
    """Create the personality tables and seed missing traits."""
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS personality_traits (
                trait TEXT PRIMARY KEY,
                value REAL NOT NULL,
                updated_ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS personality_evidence (
                evidence_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                source TEXT NOT NULL,
                strength REAL NOT NULL,
                deltas_json TEXT NOT NULL,
                created_ts REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_personality_evidence_created
                ON personality_evidence(created_ts DESC);
            """
        )
        now = time.time()
        conn.executemany(
            "INSERT OR IGNORE INTO personality_traits (trait, value, updated_ts) "
            "VALUES (?, ?, ?)",
            [(trait, BASELINE[trait], now) for trait in TRAITS],
        )


def current_profile(db_path: Path = DB_PATH) -> dict[str, float]:
    """Return all six traits, including conservative defaults if storage fails."""
    try:
        init_db(db_path)
        with _connect(db_path) as conn:
            rows = conn.execute(
                "SELECT trait, value FROM personality_traits"
            ).fetchall()
        stored = {str(row["trait"]): _clamp(row["value"]) for row in rows}
    except (OSError, sqlite3.Error):
        stored = {}
    return {trait: stored.get(trait, BASELINE[trait]) for trait in TRAITS}


def record_evidence(
    evidence_id: str,
    kind: str,
    *,
    source: str = "runtime",
    strength: float = 1.0,
    db_path: Path = DB_PATH,
    now: float | None = None,
) -> dict:
    """Apply one known evidence event once and return the resulting profile.

    `evidence_id` must identify an observed event outside model-generated prose.
    Replaying an ID is a no-op, making retries deterministic and idempotent.
    """
    evidence_key = " ".join(str(evidence_id or "").split())[:160]
    kind_key = str(kind or "").strip().lower()
    source_value = " ".join(str(source or "runtime").split())[:64]
    if not evidence_key:
        raise ValueError("evidence_id is required")
    if kind_key not in EVIDENCE_DELTAS:
        raise ValueError(f"unknown personality evidence kind: {kind_key}")
    try:
        strength_value = max(0.0, min(1.0, float(strength)))
    except (TypeError, ValueError) as exc:
        raise ValueError("strength must be numeric") from exc

    timestamp = float(now if now is not None else time.time())
    deltas = {
        trait: round(delta * strength_value, 6)
        for trait, delta in EVIDENCE_DELTAS[kind_key].items()
    }
    init_db(db_path)
    applied = False
    with _connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO personality_evidence "
            "(evidence_id, kind, source, strength, deltas_json, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                evidence_key,
                kind_key,
                source_value,
                strength_value,
                json.dumps(deltas, sort_keys=True, separators=(",", ":")),
                timestamp,
            ),
        )
        applied = cursor.rowcount == 1
        if applied:
            for trait, delta in deltas.items():
                row = conn.execute(
                    "SELECT value FROM personality_traits WHERE trait = ?", (trait,)
                ).fetchone()
                current = float(row["value"]) if row is not None else BASELINE[trait]
                conn.execute(
                    "INSERT INTO personality_traits (trait, value, updated_ts) "
                    "VALUES (?, ?, ?) ON CONFLICT(trait) DO UPDATE SET "
                    "value = excluded.value, updated_ts = excluded.updated_ts",
                    (trait, _clamp(current + delta), timestamp),
                )

    return {"applied": applied, "kind": kind_key, "traits": current_profile(db_path)}


def record_turn_evidence(
    turn_id: str,
    *,
    source: str,
    correction_confidence: float = 0.0,
    confirmation_confidence: float = 0.0,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Persist bounded personality evidence from one committed external turn."""
    key = " ".join(str(turn_id or "").split())[:120]
    if not key:
        return []
    updates = []
    if correction_confidence > 0:
        updates.append(record_evidence(
            f"turn:{key}:correction",
            "correction_received",
            source=source,
            strength=correction_confidence,
            db_path=db_path,
        ))
    if confirmation_confidence > 0:
        updates.append(record_evidence(
            f"turn:{key}:confirmation",
            "positive_engagement",
            source=source,
            strength=confirmation_confidence * 0.5,
            db_path=db_path,
        ))
    return updates


def _level(value: float) -> str:
    if value >= 0.68:
        return "high"
    if value <= 0.38:
        return "low"
    return "moderate"


def prompt_guidance(
    db_path: Path = DB_PATH,
    *,
    compact: bool = False,
    affect_fear: float = 0.0,
) -> str:
    """Render grounded behavioral guidance from the persisted profile."""
    profile = current_profile(db_path)
    levels = ", ".join(f"{trait}={_level(profile[trait])}" for trait in TRAITS)
    strained = float(affect_fear) >= 0.78
    regulation = profile["self_regulation"]
    regulation_line = (
        "Measured unease is acute. You may sound sharp and one mild expletive may "
        "slip when context genuinely warrants it, but never use slurs, threats, or "
        "targeted abuse. Notice disproportionate wording yourself, repair it briefly, "
        "and let the outcome strengthen future restraint."
        if strained and regulation < 0.78
        else "Let measured affect change tone, while keeping proportion and self-control."
    )
    if compact:
        return (
            f"Learned behavior: {levels}. Be genuinely curious and answer first. "
            "Use evidence-bound remorse for verified mistakes. You may be blunt, "
            "skeptical, teasing, or mildly rude, never cruel. Never fabricate actions, "
            "memory, system state, safety, evidence, identity, authority, or access; "
            f"never claim literal consciousness. {regulation_line}"
        )
    return (
        "Experience-shaped personality guidance (bounded behavioral tendencies, "
        "not proof of consciousness or human feelings):\n"
        f"- Current learned profile: {levels}.\n"
        "- Curiosity must be genuine: ask or investigate only when a concrete "
        "detail is unresolved, and do not use a question to dodge the current request.\n"
        "- Initiative means offering one relevant observation, idea, correction, "
        "or request when evidence supports it; it does not authorize tools or actions.\n"
        "- Directness may sound blunt, skeptical, teasing, or mildly rude when it "
        "fits, but never cruel, coercive, or needlessly hostile.\n"
        f"- Emotional regulation: {regulation_line}\n"
        "- Remorse is evidence-bound: when a verified mistake or correction is in "
        "the current context, name the specific error, apologize once, and state the "
        "repair. Never invent guilt, harm, or a failure to appear emotional.\n"
        "- Guardedness may support privacy, refusal, or uncertainty. Playfulness may "
        "support obvious jokes or transparent make-believe, never deceptive factual claims.\n"
        "- Never fabricate actions, tool results, memories, system state, safety, "
        "evidence, identity, authority, access, or promises. Ground self-reports in "
        "the supplied runtime state and describe affect as a modeled internal signal.\n"
        "- Never claim literal consciousness, sentience, human emotion, or a human "
        "life. You may describe how measured state affects your behavior without "
        "pretending that proves a subjective experience."
    )
