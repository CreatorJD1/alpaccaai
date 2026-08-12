"""Source-provenanced temporal facts stored in additive SQLite tables.

This module is a schema and storage foundation only. It does not perform fact
extraction or model-driven conflict resolution. Callers must supply identified
evidence, and every fact remains bound to at least one observation.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


FACTS_TABLE = "temporal_memory_facts"
OBSERVATIONS_TABLE = "temporal_memory_observations"
EVIDENCE_TABLE = "temporal_memory_fact_evidence"
CONTRADICTIONS_TABLE = "temporal_memory_contradictions"
SOURCE_CURSORS_TABLE = "temporal_memory_source_cursors"

MAX_IDENTIFIER_CHARS = 200
MAX_FACT_PART_CHARS = 4_000
MAX_REFERENCE_CHARS = 2_000
MAX_REASON_CHARS = 1_000


class TemporalMemoryError(ValueError):
    """Base class for rejected temporal-memory operations."""


class TemporalMemoryConflict(TemporalMemoryError):
    """An idempotency key was reused for different durable content."""


class TemporalMemoryNotFound(TemporalMemoryError):
    """A referenced fact or observation does not exist."""


@dataclass(frozen=True, slots=True)
class EvidenceObservation:
    id: int
    observation_uid: str
    source: str
    actor_id: str
    surface: str
    scope: str
    observed_at: float
    content_sha256: str
    raw_reference: str
    metadata: dict[str, Any]
    recorded_at: float


@dataclass(frozen=True, slots=True)
class TemporalFact:
    id: int
    fact_uid: str
    subject: str
    predicate: str
    object_text: str
    confidence: float
    actor_id: str
    surface: str
    scope: str
    valid_from: float
    valid_to: float | None
    recorded_at: float
    invalidated_at: float | None
    primary_observation_id: int


@dataclass(frozen=True, slots=True)
class FactEvidence:
    fact_id: int
    observation_id: int
    derivation_kind: str
    linked_at: float


@dataclass(frozen=True, slots=True)
class ContradictionLink:
    id: int
    fact_id: int
    contradicts_fact_id: int
    observation_id: int | None
    reason: str
    linked_at: float


def _clean_text(value: object, *, name: str, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise TemporalMemoryError(f"{name} must not be empty")
    if len(text) > maximum:
        raise TemporalMemoryError(f"{name} exceeds {maximum} characters")
    return text


def _optional_text(value: object, *, name: str, maximum: int) -> str:
    if value is None or value == "":
        return ""
    return _clean_text(value, name=name, maximum=maximum)


def _timestamp(value: object, *, name: str) -> float:
    if isinstance(value, bool):
        raise TemporalMemoryError(f"{name} must be a finite timestamp")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise TemporalMemoryError(f"{name} must be a finite timestamp") from None
    if not math.isfinite(result):
        raise TemporalMemoryError(f"{name} must be a finite timestamp")
    return result


def _confidence(value: object) -> float:
    result = _timestamp(value, name="confidence")
    if not 0.0 <= result <= 1.0:
        raise TemporalMemoryError("confidence must be between 0 and 1")
    return result


def _canonical_metadata(value: Mapping[str, Any] | None) -> str:
    if value is None:
        return "{}"
    if not isinstance(value, Mapping):
        raise TemporalMemoryError("metadata must be a mapping")
    try:
        encoded = json.dumps(
            dict(value), ensure_ascii=True, allow_nan=False,
            separators=(",", ":"), sort_keys=True,
        )
    except (TypeError, ValueError):
        raise TemporalMemoryError("metadata must be JSON serializable") from None
    if len(encoded) > 16_000:
        raise TemporalMemoryError("metadata exceeds 16000 characters")
    return encoded


def _content_digest(content: str | bytes) -> str:
    if isinstance(content, str):
        payload = content.encode("utf-8")
    elif isinstance(content, bytes):
        payload = content
    else:
        raise TemporalMemoryError("content must be text or bytes")
    if not payload:
        raise TemporalMemoryError("content must not be empty")
    return hashlib.sha256(payload).hexdigest()


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_columns(
    conn: sqlite3.Connection,
    table: str,
    definitions: Mapping[str, str],
) -> None:
    existing = _columns(conn, table)
    for name, definition in definitions.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db(db_path: Path) -> None:
    """Create or additively migrate the temporal-memory schema."""

    path = Path(db_path)
    with _connect(path) as conn:
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {OBSERVATIONS_TABLE} (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_uid    TEXT NOT NULL UNIQUE,
                source             TEXT NOT NULL,
                actor_id           TEXT NOT NULL,
                surface            TEXT NOT NULL,
                scope              TEXT NOT NULL,
                observed_at        REAL NOT NULL,
                content_sha256     TEXT NOT NULL,
                raw_reference      TEXT NOT NULL DEFAULT '',
                metadata_json      TEXT NOT NULL DEFAULT '{{}}',
                recorded_at        REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS {FACTS_TABLE} (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                fact_uid               TEXT NOT NULL UNIQUE,
                subject                TEXT NOT NULL,
                predicate              TEXT NOT NULL,
                object_text            TEXT NOT NULL,
                confidence             REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
                actor_id               TEXT NOT NULL,
                surface                TEXT NOT NULL,
                scope                  TEXT NOT NULL,
                valid_from             REAL NOT NULL,
                valid_to               REAL,
                recorded_at            REAL NOT NULL,
                invalidated_at         REAL,
                primary_observation_id INTEGER NOT NULL,
                CHECK(valid_to IS NULL OR valid_to > valid_from),
                FOREIGN KEY(primary_observation_id)
                    REFERENCES {OBSERVATIONS_TABLE}(id)
            );

            CREATE TABLE IF NOT EXISTS {EVIDENCE_TABLE} (
                fact_id          INTEGER NOT NULL,
                observation_id   INTEGER NOT NULL,
                derivation_kind  TEXT NOT NULL,
                linked_at        REAL NOT NULL,
                PRIMARY KEY(fact_id, observation_id),
                FOREIGN KEY(fact_id) REFERENCES {FACTS_TABLE}(id) ON DELETE CASCADE,
                FOREIGN KEY(observation_id) REFERENCES {OBSERVATIONS_TABLE}(id)
            );

            CREATE TABLE IF NOT EXISTS {CONTRADICTIONS_TABLE} (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                fact_id             INTEGER NOT NULL,
                contradicts_fact_id INTEGER NOT NULL,
                observation_id      INTEGER,
                reason              TEXT NOT NULL DEFAULT '',
                linked_at           REAL NOT NULL,
                UNIQUE(fact_id, contradicts_fact_id),
                CHECK(fact_id < contradicts_fact_id),
                FOREIGN KEY(fact_id) REFERENCES {FACTS_TABLE}(id) ON DELETE CASCADE,
                FOREIGN KEY(contradicts_fact_id) REFERENCES {FACTS_TABLE}(id) ON DELETE CASCADE,
                FOREIGN KEY(observation_id) REFERENCES {OBSERVATIONS_TABLE}(id)
            );

            CREATE TABLE IF NOT EXISTS {SOURCE_CURSORS_TABLE} (
                source_name  TEXT PRIMARY KEY,
                last_row_id  INTEGER NOT NULL DEFAULT 0,
                updated_at   REAL NOT NULL
            );
            """
        )

        # Older development snapshots may contain partial versions of these
        # tables. Add missing columns without dropping or replacing any row.
        _add_columns(conn, OBSERVATIONS_TABLE, {
            "observation_uid": "TEXT NOT NULL DEFAULT ''",
            "source": "TEXT NOT NULL DEFAULT ''",
            "actor_id": "TEXT NOT NULL DEFAULT ''",
            "surface": "TEXT NOT NULL DEFAULT ''",
            "scope": "TEXT NOT NULL DEFAULT 'shared'",
            "observed_at": "REAL NOT NULL DEFAULT 0",
            "content_sha256": "TEXT NOT NULL DEFAULT ''",
            "raw_reference": "TEXT NOT NULL DEFAULT ''",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "recorded_at": "REAL NOT NULL DEFAULT 0",
        })
        _add_columns(conn, FACTS_TABLE, {
            "fact_uid": "TEXT NOT NULL DEFAULT ''",
            "subject": "TEXT NOT NULL DEFAULT ''",
            "predicate": "TEXT NOT NULL DEFAULT ''",
            "object_text": "TEXT NOT NULL DEFAULT ''",
            "confidence": "REAL NOT NULL DEFAULT 0",
            "actor_id": "TEXT NOT NULL DEFAULT ''",
            "surface": "TEXT NOT NULL DEFAULT ''",
            "scope": "TEXT NOT NULL DEFAULT 'shared'",
            "valid_from": "REAL NOT NULL DEFAULT 0",
            "valid_to": "REAL",
            "recorded_at": "REAL NOT NULL DEFAULT 0",
            "invalidated_at": "REAL",
            "primary_observation_id": "INTEGER",
        })
        _add_columns(conn, EVIDENCE_TABLE, {
            "fact_id": "INTEGER",
            "observation_id": "INTEGER",
            "derivation_kind": "TEXT NOT NULL DEFAULT 'asserted'",
            "linked_at": "REAL NOT NULL DEFAULT 0",
        })
        _add_columns(conn, CONTRADICTIONS_TABLE, {
            "fact_id": "INTEGER",
            "contradicts_fact_id": "INTEGER",
            "observation_id": "INTEGER",
            "reason": "TEXT NOT NULL DEFAULT ''",
            "linked_at": "REAL NOT NULL DEFAULT 0",
        })

        conn.execute(
            f"UPDATE {OBSERVATIONS_TABLE} SET observation_uid='legacy-observation-' || id "
            "WHERE trim(observation_uid)=''"
        )
        conn.execute(
            f"UPDATE {FACTS_TABLE} SET fact_uid='legacy-fact-' || id "
            "WHERE trim(fact_uid)=''"
        )
        conn.executescript(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS temporal_memory_observation_uid_idx
                ON {OBSERVATIONS_TABLE}(observation_uid);
            CREATE INDEX IF NOT EXISTS temporal_memory_observation_scope_time_idx
                ON {OBSERVATIONS_TABLE}(scope, observed_at DESC, id DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS temporal_memory_fact_uid_idx
                ON {FACTS_TABLE}(fact_uid);
            CREATE INDEX IF NOT EXISTS temporal_memory_fact_validity_idx
                ON {FACTS_TABLE}(scope, subject, predicate, valid_from, valid_to);
            CREATE INDEX IF NOT EXISTS temporal_memory_fact_actor_surface_idx
                ON {FACTS_TABLE}(scope, actor_id, surface, recorded_at DESC);
            CREATE INDEX IF NOT EXISTS temporal_memory_evidence_observation_idx
                ON {EVIDENCE_TABLE}(observation_id, fact_id);
            CREATE INDEX IF NOT EXISTS temporal_memory_contradiction_reverse_idx
                ON {CONTRADICTIONS_TABLE}(contradicts_fact_id, fact_id);
            """
        )


def _observation_from_row(row: sqlite3.Row) -> EvidenceObservation:
    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except (TypeError, ValueError):
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return EvidenceObservation(
        id=int(row["id"]),
        observation_uid=str(row["observation_uid"]),
        source=str(row["source"]),
        actor_id=str(row["actor_id"]),
        surface=str(row["surface"]),
        scope=str(row["scope"]),
        observed_at=float(row["observed_at"]),
        content_sha256=str(row["content_sha256"]),
        raw_reference=str(row["raw_reference"] or ""),
        metadata=metadata,
        recorded_at=float(row["recorded_at"]),
    )


def _fact_from_row(row: sqlite3.Row) -> TemporalFact:
    primary = row["primary_observation_id"]
    if primary is None:
        primary = 0
    return TemporalFact(
        id=int(row["id"]),
        fact_uid=str(row["fact_uid"]),
        subject=str(row["subject"]),
        predicate=str(row["predicate"]),
        object_text=str(row["object_text"]),
        confidence=float(row["confidence"]),
        actor_id=str(row["actor_id"]),
        surface=str(row["surface"]),
        scope=str(row["scope"]),
        valid_from=float(row["valid_from"]),
        valid_to=float(row["valid_to"]) if row["valid_to"] is not None else None,
        recorded_at=float(row["recorded_at"]),
        invalidated_at=(
            float(row["invalidated_at"])
            if row["invalidated_at"] is not None else None
        ),
        primary_observation_id=int(primary),
    )


class TemporalMemoryStore:
    """Small explicit API over the temporal-memory schema."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._transaction_local = threading.local()
        init_db(self.db_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        active = getattr(self._transaction_local, "connection", None)
        if active is not None:
            yield active
            return
        with _connect(self.db_path) as conn:
            yield conn

    @contextmanager
    def transaction(self) -> Iterator["TemporalMemoryStore"]:
        """Make a related set of store operations one SQLite transaction."""

        active = getattr(self._transaction_local, "connection", None)
        if active is not None:
            yield self
            return
        with _connect(self.db_path) as conn:
            self._transaction_local.connection = conn
            try:
                yield self
            finally:
                del self._transaction_local.connection

    def record_observation(
        self,
        *,
        source: str,
        actor_id: str,
        surface: str,
        scope: str,
        observed_at: float,
        content: str | bytes,
        observation_uid: str | None = None,
        raw_reference: str = "",
        metadata: Mapping[str, Any] | None = None,
        recorded_at: float | None = None,
    ) -> EvidenceObservation:
        uid = _clean_text(
            observation_uid or uuid.uuid4().hex,
            name="observation_uid", maximum=MAX_IDENTIFIER_CHARS,
        )
        clean_source = _clean_text(source, name="source", maximum=MAX_IDENTIFIER_CHARS)
        clean_actor = _clean_text(actor_id, name="actor_id", maximum=MAX_IDENTIFIER_CHARS)
        clean_surface = _clean_text(surface, name="surface", maximum=MAX_IDENTIFIER_CHARS)
        clean_scope = _clean_text(scope, name="scope", maximum=MAX_IDENTIFIER_CHARS)
        observed = _timestamp(observed_at, name="observed_at")
        recorded = _timestamp(
            time.time() if recorded_at is None else recorded_at,
            name="recorded_at",
        )
        digest = _content_digest(content)
        reference = _optional_text(
            raw_reference, name="raw_reference", maximum=MAX_REFERENCE_CHARS,
        )
        metadata_json = _canonical_metadata(metadata)
        values = (
            uid, clean_source, clean_actor, clean_surface, clean_scope,
            observed, digest, reference, metadata_json, recorded,
        )
        with self._connection() as conn:
            existing = conn.execute(
                f"SELECT * FROM {OBSERVATIONS_TABLE} WHERE observation_uid=?",
                (uid,),
            ).fetchone()
            if existing is not None:
                current = (
                    existing["observation_uid"], existing["source"],
                    existing["actor_id"], existing["surface"], existing["scope"],
                    existing["observed_at"], existing["content_sha256"],
                    existing["raw_reference"], existing["metadata_json"],
                    existing["recorded_at"],
                )
                if current != values:
                    raise TemporalMemoryConflict(
                        "observation_uid is already bound to different evidence"
                    )
                return _observation_from_row(existing)
            cursor = conn.execute(
                f"""
                INSERT INTO {OBSERVATIONS_TABLE} (
                    observation_uid, source, actor_id, surface, scope,
                    observed_at, content_sha256, raw_reference,
                    metadata_json, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            row = conn.execute(
                f"SELECT * FROM {OBSERVATIONS_TABLE} WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            assert row is not None
            return _observation_from_row(row)

    def record_fact(
        self,
        *,
        subject: str,
        predicate: str,
        object_text: str,
        confidence: float,
        actor_id: str,
        surface: str,
        scope: str,
        valid_from: float,
        evidence_observation_ids: Sequence[int],
        valid_to: float | None = None,
        fact_uid: str | None = None,
        derivation_kind: str = "asserted",
        recorded_at: float | None = None,
    ) -> TemporalFact:
        uid = _clean_text(
            fact_uid or uuid.uuid4().hex,
            name="fact_uid", maximum=MAX_IDENTIFIER_CHARS,
        )
        clean_subject = _clean_text(
            subject, name="subject", maximum=MAX_FACT_PART_CHARS,
        )
        clean_predicate = _clean_text(
            predicate, name="predicate", maximum=MAX_FACT_PART_CHARS,
        )
        clean_object = _clean_text(
            object_text, name="object_text", maximum=MAX_FACT_PART_CHARS,
        )
        clean_actor = _clean_text(actor_id, name="actor_id", maximum=MAX_IDENTIFIER_CHARS)
        clean_surface = _clean_text(surface, name="surface", maximum=MAX_IDENTIFIER_CHARS)
        clean_scope = _clean_text(scope, name="scope", maximum=MAX_IDENTIFIER_CHARS)
        derivation = _clean_text(
            derivation_kind, name="derivation_kind", maximum=MAX_IDENTIFIER_CHARS,
        )
        valid_start = _timestamp(valid_from, name="valid_from")
        valid_end = None if valid_to is None else _timestamp(valid_to, name="valid_to")
        if valid_end is not None and valid_end <= valid_start:
            raise TemporalMemoryError("valid_to must be later than valid_from")
        recorded = _timestamp(
            time.time() if recorded_at is None else recorded_at,
            name="recorded_at",
        )
        confidence_value = _confidence(confidence)
        if isinstance(evidence_observation_ids, (str, bytes)):
            raise TemporalMemoryError("evidence_observation_ids must be integer IDs")
        evidence_ids = tuple(dict.fromkeys(evidence_observation_ids))
        if not evidence_ids or any(type(item) is not int or item <= 0 for item in evidence_ids):
            raise TemporalMemoryError("at least one positive evidence observation ID is required")

        values = (
            uid, clean_subject, clean_predicate, clean_object, confidence_value,
            clean_actor, clean_surface, clean_scope, valid_start, valid_end,
            recorded, evidence_ids[0],
        )
        with self._connection() as conn:
            observations = conn.execute(
                f"SELECT id, scope FROM {OBSERVATIONS_TABLE} "
                f"WHERE id IN ({','.join('?' for _ in evidence_ids)})",
                evidence_ids,
            ).fetchall()
            if len(observations) != len(evidence_ids):
                raise TemporalMemoryNotFound("one or more evidence observations do not exist")
            if any(str(row["scope"]) != clean_scope for row in observations):
                raise TemporalMemoryError("fact evidence must remain within the same scope")
            existing = conn.execute(
                f"SELECT * FROM {FACTS_TABLE} WHERE fact_uid=?", (uid,),
            ).fetchone()
            if existing is not None:
                current = (
                    existing["fact_uid"], existing["subject"], existing["predicate"],
                    existing["object_text"], existing["confidence"],
                    existing["actor_id"], existing["surface"], existing["scope"],
                    existing["valid_from"], existing["valid_to"],
                    existing["recorded_at"], existing["primary_observation_id"],
                )
                if current != values:
                    raise TemporalMemoryConflict(
                        "fact_uid is already bound to a different fact"
                    )
                linked = conn.execute(
                    f"SELECT observation_id, derivation_kind FROM {EVIDENCE_TABLE} "
                    "WHERE fact_id=? ORDER BY observation_id",
                    (existing["id"],),
                ).fetchall()
                current_evidence = {
                    (int(row["observation_id"]), str(row["derivation_kind"]))
                    for row in linked
                }
                expected_evidence = {(item, derivation) for item in evidence_ids}
                if current_evidence != expected_evidence:
                    raise TemporalMemoryConflict(
                        "fact_uid is already bound to different provenance"
                    )
                return _fact_from_row(existing)
            cursor = conn.execute(
                f"""
                INSERT INTO {FACTS_TABLE} (
                    fact_uid, subject, predicate, object_text, confidence,
                    actor_id, surface, scope, valid_from, valid_to,
                    recorded_at, primary_observation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            fact_id = int(cursor.lastrowid)
            conn.executemany(
                f"INSERT INTO {EVIDENCE_TABLE} "
                "(fact_id, observation_id, derivation_kind, linked_at) "
                "VALUES (?, ?, ?, ?)",
                ((fact_id, item, derivation, recorded) for item in evidence_ids),
            )
            row = conn.execute(
                f"SELECT * FROM {FACTS_TABLE} WHERE id=?", (fact_id,),
            ).fetchone()
            assert row is not None
            return _fact_from_row(row)

    def close_validity(
        self,
        fact_id: int,
        *,
        valid_to: float,
        invalidated_at: float | None = None,
    ) -> TemporalFact:
        end = _timestamp(valid_to, name="valid_to")
        invalidated = _timestamp(
            time.time() if invalidated_at is None else invalidated_at,
            name="invalidated_at",
        )
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT * FROM {FACTS_TABLE} WHERE id=?", (fact_id,),
            ).fetchone()
            if row is None:
                raise TemporalMemoryNotFound("fact does not exist")
            if end <= float(row["valid_from"]):
                raise TemporalMemoryError("valid_to must be later than valid_from")
            current_end = row["valid_to"]
            if current_end is not None:
                if float(current_end) != end:
                    raise TemporalMemoryConflict(
                        "a closed validity interval cannot be rewritten"
                    )
                return _fact_from_row(row)
            conn.execute(
                f"UPDATE {FACTS_TABLE} SET valid_to=?, invalidated_at=? WHERE id=?",
                (end, invalidated, fact_id),
            )
            updated = conn.execute(
                f"SELECT * FROM {FACTS_TABLE} WHERE id=?", (fact_id,),
            ).fetchone()
            assert updated is not None
            return _fact_from_row(updated)

    def link_contradiction(
        self,
        first_fact_id: int,
        second_fact_id: int,
        *,
        reason: str = "",
        observation_id: int | None = None,
        linked_at: float | None = None,
    ) -> ContradictionLink:
        if type(first_fact_id) is not int or type(second_fact_id) is not int:
            raise TemporalMemoryError("fact IDs must be integers")
        if first_fact_id <= 0 or second_fact_id <= 0 or first_fact_id == second_fact_id:
            raise TemporalMemoryError("contradiction requires two different positive fact IDs")
        lower, upper = sorted((first_fact_id, second_fact_id))
        clean_reason = _optional_text(reason, name="reason", maximum=MAX_REASON_CHARS)
        stamp = _timestamp(time.time() if linked_at is None else linked_at, name="linked_at")
        with self._connection() as conn:
            facts = conn.execute(
                f"SELECT id, scope FROM {FACTS_TABLE} WHERE id IN (?, ?)",
                (lower, upper),
            ).fetchall()
            if len(facts) != 2:
                raise TemporalMemoryNotFound("one or more contradiction facts do not exist")
            scopes = {str(row["scope"]) for row in facts}
            if len(scopes) != 1:
                raise TemporalMemoryError("contradictions cannot cross memory scopes")
            if observation_id is not None:
                if type(observation_id) is not int or observation_id <= 0:
                    raise TemporalMemoryError("observation_id must be a positive integer")
                observation = conn.execute(
                    f"SELECT scope FROM {OBSERVATIONS_TABLE} WHERE id=?",
                    (observation_id,),
                ).fetchone()
                if observation is None:
                    raise TemporalMemoryNotFound("contradiction observation does not exist")
                if str(observation["scope"]) not in scopes:
                    raise TemporalMemoryError(
                        "contradiction evidence must remain within the same scope"
                    )
            existing = conn.execute(
                f"SELECT * FROM {CONTRADICTIONS_TABLE} "
                "WHERE fact_id=? AND contradicts_fact_id=?",
                (lower, upper),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["reason"] or "") != clean_reason
                    or existing["observation_id"] != observation_id
                ):
                    raise TemporalMemoryConflict(
                        "contradiction pair is already linked with different evidence"
                    )
                return self._contradiction_from_row(existing)
            cursor = conn.execute(
                f"INSERT INTO {CONTRADICTIONS_TABLE} "
                "(fact_id, contradicts_fact_id, observation_id, reason, linked_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (lower, upper, observation_id, clean_reason, stamp),
            )
            row = conn.execute(
                f"SELECT * FROM {CONTRADICTIONS_TABLE} WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            assert row is not None
            return self._contradiction_from_row(row)

    @staticmethod
    def _contradiction_from_row(row: sqlite3.Row) -> ContradictionLink:
        observation_id = row["observation_id"]
        return ContradictionLink(
            id=int(row["id"]),
            fact_id=int(row["fact_id"]),
            contradicts_fact_id=int(row["contradicts_fact_id"]),
            observation_id=int(observation_id) if observation_id is not None else None,
            reason=str(row["reason"] or ""),
            linked_at=float(row["linked_at"]),
        )

    def facts_valid_at(
        self,
        at: float,
        *,
        scope: str,
        subject: str | None = None,
        predicate: str | None = None,
        actor_id: str | None = None,
        surface: str | None = None,
    ) -> list[TemporalFact]:
        stamp = _timestamp(at, name="at")
        clauses = ["scope=?", "valid_from<=?", "(valid_to IS NULL OR ?<valid_to)"]
        parameters: list[object] = [
            _clean_text(scope, name="scope", maximum=MAX_IDENTIFIER_CHARS),
            stamp,
            stamp,
        ]
        for column, value, maximum in (
            ("subject", subject, MAX_FACT_PART_CHARS),
            ("predicate", predicate, MAX_FACT_PART_CHARS),
            ("actor_id", actor_id, MAX_IDENTIFIER_CHARS),
            ("surface", surface, MAX_IDENTIFIER_CHARS),
        ):
            if value is not None:
                clauses.append(f"{column}=?")
                parameters.append(_clean_text(value, name=column, maximum=maximum))
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM {FACTS_TABLE} WHERE {' AND '.join(clauses)} "
                "ORDER BY confidence DESC, valid_from DESC, id DESC",
                parameters,
            ).fetchall()
        return [_fact_from_row(row) for row in rows]

    def evidence_for_fact(self, fact_id: int) -> list[EvidenceObservation]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT observation.* FROM {OBSERVATIONS_TABLE} AS observation "
                f"JOIN {EVIDENCE_TABLE} AS link ON link.observation_id=observation.id "
                "WHERE link.fact_id=? ORDER BY link.linked_at, observation.id",
                (fact_id,),
            ).fetchall()
        return [_observation_from_row(row) for row in rows]

    def contradictions_for_fact(self, fact_id: int) -> list[ContradictionLink]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM {CONTRADICTIONS_TABLE} "
                "WHERE fact_id=? OR contradicts_fact_id=? ORDER BY linked_at, id",
                (fact_id, fact_id),
            ).fetchall()
        return [self._contradiction_from_row(row) for row in rows]

    def source_cursor(self, source_name: str) -> int:
        """Return the durable high-water mark for a committed evidence source."""

        source = _clean_text(
            source_name, name="source_name", maximum=MAX_IDENTIFIER_CHARS,
        )
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT last_row_id FROM {SOURCE_CURSORS_TABLE} WHERE source_name=?",
                (source,),
            ).fetchone()
        return 0 if row is None else int(row["last_row_id"])

    def advance_source_cursor(
        self,
        source_name: str,
        row_id: int,
        *,
        updated_at: float | None = None,
    ) -> int:
        """Monotonically checkpoint a scanned source row, safe under replay."""

        source = _clean_text(
            source_name, name="source_name", maximum=MAX_IDENTIFIER_CHARS,
        )
        if type(row_id) is not int or row_id <= 0:
            raise TemporalMemoryError("row_id must be a positive integer")
        stamp = _timestamp(
            time.time() if updated_at is None else updated_at,
            name="updated_at",
        )
        with self._connection() as conn:
            conn.execute(
                f"INSERT INTO {SOURCE_CURSORS_TABLE} "
                "(source_name, last_row_id, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(source_name) DO UPDATE SET "
                "last_row_id=max(last_row_id, excluded.last_row_id), "
                "updated_at=CASE WHEN excluded.last_row_id>=last_row_id "
                "THEN excluded.updated_at ELSE updated_at END",
                (source, row_id, stamp),
            )
            row = conn.execute(
                f"SELECT last_row_id FROM {SOURCE_CURSORS_TABLE} WHERE source_name=?",
                (source,),
            ).fetchone()
        assert row is not None
        return int(row["last_row_id"])

    def prune_unreferenced_observations(
        self,
        *,
        before: float,
        limit: int = 256,
    ) -> int:
        """Delete old observations only when no fact or contradiction uses them."""

        cutoff = _timestamp(before, name="before")
        if type(limit) is not int or not 1 <= limit <= 1_000:
            raise TemporalMemoryError("limit must be between 1 and 1000")
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT observation.id FROM {OBSERVATIONS_TABLE} AS observation "
                "WHERE observation.recorded_at<? "
                f"AND NOT EXISTS (SELECT 1 FROM {EVIDENCE_TABLE} AS evidence "
                "WHERE evidence.observation_id=observation.id) "
                f"AND NOT EXISTS (SELECT 1 FROM {CONTRADICTIONS_TABLE} AS contradiction "
                "WHERE contradiction.observation_id=observation.id) "
                "ORDER BY observation.recorded_at, observation.id LIMIT ?",
                (cutoff, limit),
            ).fetchall()
            ids = tuple(int(row["id"]) for row in rows)
            if not ids:
                return 0
            cursor = conn.execute(
                f"DELETE FROM {OBSERVATIONS_TABLE} WHERE id IN "
                f"({','.join('?' for _ in ids)})",
                ids,
            )
        return int(cursor.rowcount)


__all__ = [
    "CONTRADICTIONS_TABLE",
    "EVIDENCE_TABLE",
    "FACTS_TABLE",
    "OBSERVATIONS_TABLE",
    "SOURCE_CURSORS_TABLE",
    "ContradictionLink",
    "EvidenceObservation",
    "FactEvidence",
    "TemporalFact",
    "TemporalMemoryConflict",
    "TemporalMemoryError",
    "TemporalMemoryNotFound",
    "TemporalMemoryStore",
    "init_db",
]
