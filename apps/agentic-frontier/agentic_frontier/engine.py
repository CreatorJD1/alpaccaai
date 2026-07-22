"""Persistent server authority for the Agentic Frontier vertical slice.

This package deliberately owns only game state. It neither imports nor writes
Alpecca companion memory, cognition, journal, or CoreMind state.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


ACTION_CONTRACT_VERSION = "agentic_frontier.action.v1"
PERCEPTION_CONTRACT_VERSION = "agentic_frontier.perception.v1"
WORLD_CONTRACT_VERSION = "agentic_frontier.world.v2"
EPISODE_CONTRACT_VERSION = "agentic_frontier.game_episode_candidate.v1"
MEMORY_BOUNDARY = {
    "owner": "agentic_frontier_game",
    "stores": ("world_state", "game_actions", "game_events", "game_episode_candidates"),
    "forbidden": ("companion_memory", "coremind", "journal", "mindscape"),
    "promotion": "validated_external_companion_adapter_required",
}

_ACTORS = ("Jason", "Alpecca")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_RECONNECT_RECEIPTS = 50
_PERCEPTION_RADIUS = 2
_MAX_OBSERVATIONS = 16
_WORLD_WIDTH = 18
_WORLD_HEIGHT = 18
_MAX_ENERGY = 6
_STRUCTURE_KINDS = {"pressure_dome", "lumen_turret", "oxygen_beacon", "power_conduit"}
_RESOURCE_KINDS = {"ferrite_vein": "alloy", "lumen_flora": "lumen"}
_THREAT_KINDS = {"shadow_smoke", "corrupted_robot"}
_COMPANION_INTERACTION_KINDS = {"command_terminal", "pressure_dome"}
_COMPANION_SOLID_KINDS = {
    "command_terminal",
    "damaged_relay",
    "pressure_dome",
    "lumen_turret",
    "oxygen_beacon",
    "power_conduit",
    "corrupted_robot",
}


class ContractError(ValueError):
    """The caller supplied a malformed contract payload."""


class ActionRejected(ContractError):
    """A well-formed action is illegal for the authoritative world state."""


class ActionConflict(ContractError):
    """An idempotency key or expected revision conflicts with durable state."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _require_id(value: object, name: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ContractError(f"{name} must match {_ID.pattern}")
    return value


def _require_exact_keys(value: object, expected: set[str], name: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise ContractError(f"{name} must be an object")
    actual = set(value)
    if actual != expected:
        raise ContractError(f"{name} keys must be exactly {sorted(expected)}")
    return value


def _position(value: object, name: str) -> list[int]:
    if (
        type(value) is not list
        or len(value) != 2
        or any(type(item) is not int for item in value)
    ):
        raise ContractError(f"{name} must be a two-integer array")
    return list(value)


def _distance(left: list[int], right: list[int]) -> int:
    return abs(left[0] - right[0]) + abs(left[1] - right[1])


class AgenticFrontierStore:
    """SQLite-backed authority; clients receive projections, never mutable state."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS game_contract_metadata (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS game_sessions (
                    session_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS game_actions (
                    session_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    revision_before INTEGER NOT NULL,
                    revision_after INTEGER NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, action_id),
                    FOREIGN KEY (session_id) REFERENCES game_sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS game_actions_reconnect
                    ON game_actions(session_id, actor_id, revision_after);
                CREATE TABLE IF NOT EXISTS game_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES game_sessions(session_id)
                );
                CREATE TABLE IF NOT EXISTS game_episode_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    source_revision INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status = 'candidate'),
                    created_at TEXT NOT NULL,
                    UNIQUE (session_id, source_revision, kind),
                    FOREIGN KEY (session_id) REFERENCES game_sessions(session_id)
                );
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO game_contract_metadata(key, value_json) VALUES (?, ?)",
                ("memory_boundary", _canonical(MEMORY_BOUNDARY)),
            )
            conn.commit()

    def create_session(self, session_id: str) -> dict[str, Any]:
        clean_id = _require_id(session_id, "session_id")
        state = self._initial_state(clean_id)
        created = _now()
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO game_sessions VALUES (?, ?, ?, ?, ?)",
                    (clean_id, 0, _canonical(state), created, created),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise ActionConflict("session_id already exists") from exc
        return deepcopy(state)

    def world_state(self, session_id: str) -> dict[str, Any]:
        """Return the authority's full game state for trusted server tooling."""
        clean_id = _require_id(session_id, "session_id")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM game_sessions WHERE session_id=?", (clean_id,)
            ).fetchone()
        if row is None:
            raise ContractError("unknown session_id")
        return self._upgrade_state(json.loads(row["state_json"]))

    def perceive(self, session_id: str, actor_id: str) -> dict[str, Any]:
        clean_actor = self._actor(actor_id)
        return self._perception(self.world_state(session_id), clean_actor)

    def execute_action(self, request: object) -> dict[str, Any]:
        clean = self._validate_request(request)
        request_hash = _digest(clean)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                replay = conn.execute(
                    "SELECT request_hash, response_json FROM game_actions "
                    "WHERE session_id=? AND action_id=?",
                    (clean["session_id"], clean["action_id"]),
                ).fetchone()
                if replay is not None:
                    if replay["request_hash"] != request_hash:
                        raise ActionConflict(
                            "action_id was already used for a different request"
                        )
                    conn.commit()
                    return json.loads(replay["response_json"])

                row = conn.execute(
                    "SELECT revision, state_json FROM game_sessions WHERE session_id=?",
                    (clean["session_id"],),
                ).fetchone()
                if row is None:
                    raise ContractError("unknown session_id")
                revision_before = int(row["revision"])
                if clean["expected_revision"] != revision_before:
                    raise ActionConflict(
                        f"expected_revision {clean['expected_revision']} does not match "
                        f"authoritative revision {revision_before}"
                    )

                state = self._upgrade_state(json.loads(row["state_json"]))
                event_type, event_payload = self._apply_action(state, clean)
                event_payload["survival"] = self._apply_survival(
                    state, clean["actor_id"]
                )
                event_payload["world_time"] = self._advance_world_clock(
                    state, clean["action"]
                )
                revision_after = revision_before + 1
                state["revision"] = revision_after
                timestamp = _now()
                conn.execute(
                    "INSERT INTO game_events(session_id, revision, event_type, actor_id, "
                    "payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        clean["session_id"],
                        revision_after,
                        event_type,
                        clean["actor_id"],
                        _canonical(event_payload),
                        timestamp,
                    ),
                )
                candidate_ids = self._record_candidates(
                    conn, state, clean, event_type, event_payload, revision_after, timestamp
                )
                response = {
                    "contract_version": ACTION_CONTRACT_VERSION,
                    "session_id": clean["session_id"],
                    "action_id": clean["action_id"],
                    "actor_id": clean["actor_id"],
                    "accepted": True,
                    "revision": revision_after,
                    "event": {"type": event_type, "facts": event_payload},
                    "game_episode_candidate_ids": candidate_ids,
                    "perception": self._perception(state, clean["actor_id"]),
                }
                conn.execute(
                    "UPDATE game_sessions SET revision=?, state_json=?, updated_at=? "
                    "WHERE session_id=?",
                    (revision_after, _canonical(state), timestamp, clean["session_id"]),
                )
                conn.execute(
                    "INSERT INTO game_actions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        clean["session_id"],
                        clean["action_id"],
                        clean["actor_id"],
                        request_hash,
                        revision_before,
                        revision_after,
                        _canonical(response),
                        timestamp,
                    ),
                )
                conn.commit()
                return response
            except Exception:
                conn.rollback()
                raise

    def reconnect(
        self, session_id: str, actor_id: str, last_seen_revision: int
    ) -> dict[str, Any]:
        clean_session = _require_id(session_id, "session_id")
        clean_actor = self._actor(actor_id)
        if type(last_seen_revision) is not int or last_seen_revision < 0:
            raise ContractError("last_seen_revision must be a non-negative integer")
        state = self.world_state(clean_session)
        if last_seen_revision > state["revision"]:
            raise ActionConflict("last_seen_revision is ahead of authoritative state")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT response_json FROM game_actions WHERE session_id=? AND actor_id=? "
                "AND revision_after>? ORDER BY revision_after LIMIT ?",
                (clean_session, clean_actor, last_seen_revision, _MAX_RECONNECT_RECEIPTS + 1),
            ).fetchall()
        return {
            "contract_version": "agentic_frontier.reconnect.v1",
            "session_id": clean_session,
            "actor_id": clean_actor,
            "authoritative_revision": state["revision"],
            "receipts": [json.loads(row["response_json"]) for row in rows[:_MAX_RECONNECT_RECEIPTS]],
            "has_more_receipts": len(rows) > _MAX_RECONNECT_RECEIPTS,
            "perception": self._perception(state, clean_actor),
        }

    def list_episode_candidates(self, session_id: str) -> list[dict[str, Any]]:
        clean_session = _require_id(session_id, "session_id")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM game_episode_candidates WHERE session_id=? "
                "ORDER BY source_revision, candidate_id",
                (clean_session,),
            ).fetchall()
        return [
            {
                "contract_version": EPISODE_CONTRACT_VERSION,
                "candidate_id": row["candidate_id"],
                "session_id": row["session_id"],
                "source_revision": row["source_revision"],
                "kind": row["kind"],
                "status": row["status"],
                "evidence": json.loads(row["evidence_json"]),
            }
            for row in rows
        ]

    def storage_contract(self) -> dict[str, Any]:
        with self._connect() as conn:
            tables = sorted(
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            )
        return {"memory_boundary": deepcopy(MEMORY_BOUNDARY), "tables": tables}

    @staticmethod
    def _initial_state(session_id: str) -> dict[str, Any]:
        return {
            "contract_version": WORLD_CONTRACT_VERSION,
            "session_id": session_id,
            "revision": 0,
            "status": "active",
            "grid": {"width": _WORLD_WIDTH, "height": _WORLD_HEIGHT, "tile_size_m": 2},
            "world": {
                "name": "Tartarus Prime",
                "biome": "venusian_obsidian_frontier",
                "visual_style": "anime_cel_shaded",
                "pressure_kpa": 9200,
                "weather": "acid_rain",
                "storm_intensity": 0.42,
                "terrain_seed": "tartarus-prime-v1",
                "blocked_tiles": [[4, 4], [4, 5], [7, 8], [8, 8], [11, 3]],
                "landmarks": [
                    {"id": "landing_ring", "kind": "spawn", "position": [0, 0]},
                    {"id": "relay_ridge", "kind": "objective", "position": [2, 2]},
                    {"id": "glass_canyon", "kind": "hazard", "position": [8, 8]},
                    {"id": "megadome_site", "kind": "endgame", "position": [15, 15]},
                ],
            },
            "clock": {"day": 1, "minute": 420, "phase": "dawn"},
            "settlement": {
                "name": "Vesper Landing",
                "level": 1,
                "population": 2,
                "prosperity": 0,
                "daily_focus": "restore_frontier_relay",
            },
            "relationships": {
                "Jason_Alpecca": {"bond": 0, "trust": 50, "shared_days": 1}
            },
            "companion_activity": {
                "motion": {
                    "mode": "idle",
                    "from": [0, 1],
                    "to": [0, 1],
                    "revision": 0,
                },
                "interaction": {
                    "status": "none",
                    "entity_id": None,
                    "kind": None,
                    "revision": 0,
                },
            },
            "actors": {
                "Jason": {
                    "position": [0, 0], "facing": [0, 1], "energy": _MAX_ENERGY,
                    "health": 100, "oxygen": 100, "sanity": 100, "shield": 100,
                    "inventory": [], "materials": {"alloy": 2, "lumen": 1},
                },
                "Alpecca": {
                    "position": [0, 1], "facing": [0, 1], "energy": _MAX_ENERGY,
                    "health": 100, "oxygen": 100, "sanity": 100, "shield": 100,
                    "inventory": [], "materials": {"alloy": 2, "lumen": 1},
                },
            },
            "entities": {
                "component_j": {
                    "kind": "relay_component",
                    "position": [1, 0],
                    "collected_by": None,
                },
                "component_a": {
                    "kind": "relay_component",
                    "position": [0, 2],
                    "collected_by": None,
                },
                "frontier_relay": {
                    "kind": "damaged_relay",
                    "position": [2, 2],
                    "installed_components": [],
                    "required_components": 2,
                },
                "colony_terminal": {
                    "kind": "command_terminal",
                    "position": [1, 1],
                    "mode": "online",
                },
                "starter_dome": {
                    "kind": "pressure_dome",
                    "position": [3, 3],
                    "active": True,
                    "integrity": 72,
                    "radius": 2,
                    "owner": "colony",
                },
                "ferrite_1": {
                    "kind": "ferrite_vein", "position": [1, 2], "remaining": 3,
                },
                "ferrite_2": {
                    "kind": "ferrite_vein", "position": [6, 3], "remaining": 4,
                },
                "lumen_1": {
                    "kind": "lumen_flora", "position": [3, 2], "remaining": 2,
                },
                "lumen_2": {
                    "kind": "lumen_flora", "position": [9, 6], "remaining": 3,
                },
                "shade_1": {
                    "kind": "shadow_smoke", "position": [6, 4], "health": 36,
                    "active": True, "weakness": "lumen",
                },
                "robot_1": {
                    "kind": "corrupted_robot", "position": [10, 7], "health": 54,
                    "active": True, "weakness": "energy",
                },
            },
            "mission": {
                "id": "restore_frontier_relay",
                "status": "active",
                "title": "Restore the Frontier Relay",
                "phase": "landfall",
                "installed_components": 0,
                "required_components": 2,
            },
            "contributions": {"Jason": [], "Alpecca": []},
        }

    def _upgrade_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Upgrade prototype sessions without erasing durable progress."""
        template = self._initial_state(state["session_id"])
        state["contract_version"] = WORLD_CONTRACT_VERSION
        state.setdefault("status", "active")
        if state["status"] == "completed":
            state["status"] = "active"
        state.setdefault("revision", 0)
        state["grid"] = deepcopy(template["grid"])
        world = state.setdefault("world", {})
        for key, value in template["world"].items():
            world.setdefault(key, deepcopy(value))
        state.setdefault("clock", deepcopy(template["clock"]))
        settlement = state.setdefault("settlement", {})
        for key, value in template["settlement"].items():
            settlement.setdefault(key, deepcopy(value))
        relationships = state.setdefault("relationships", {})
        for key, value in template["relationships"].items():
            relationships.setdefault(key, deepcopy(value))
        actors = state.setdefault("actors", {})
        for actor_id, actor_template in template["actors"].items():
            actor = actors.setdefault(actor_id, {})
            for key, value in actor_template.items():
                actor.setdefault(key, deepcopy(value))
            materials = actor.setdefault("materials", {})
            for material, amount in actor_template["materials"].items():
                materials.setdefault(material, amount)
        companion_activity = state.setdefault("companion_activity", {})
        for section, value in template["companion_activity"].items():
            companion_activity.setdefault(section, deepcopy(value))
        companion_activity["motion"].setdefault("mode", "idle")
        companion_activity["motion"].setdefault(
            "from", list(actors["Alpecca"]["position"])
        )
        companion_activity["motion"].setdefault(
            "to", list(actors["Alpecca"]["position"])
        )
        companion_activity["motion"].setdefault("revision", state["revision"])
        companion_activity["interaction"].setdefault("status", "none")
        companion_activity["interaction"].setdefault("entity_id", None)
        companion_activity["interaction"].setdefault("kind", None)
        companion_activity["interaction"].setdefault("revision", state["revision"])
        entities = state.setdefault("entities", {})
        for entity_id, entity in template["entities"].items():
            entities.setdefault(entity_id, deepcopy(entity))
        for actor_id, actor in actors.items():
            for entity_id in actor.get("inventory", []):
                if entity_id in entities and entities[entity_id].get("kind") == "relay_component":
                    entities[entity_id]["collected_by"] = actor_id
        relay = entities.get("frontier_relay", {})
        for entity_id in relay.get("installed_components", []):
            if entity_id in entities:
                entities[entity_id]["collected_by"] = "frontier_relay"
        mission = state.setdefault("mission", {})
        for key, value in template["mission"].items():
            mission.setdefault(key, deepcopy(value))
        contributions = state.setdefault("contributions", {})
        for actor_id in _ACTORS:
            contributions.setdefault(actor_id, [])
        return state

    @staticmethod
    def _actor(actor_id: object) -> str:
        if actor_id not in _ACTORS:
            raise ContractError("actor_id must be Jason or Alpecca")
        return str(actor_id)

    def _validate_request(self, request: object) -> dict[str, Any]:
        value = _require_exact_keys(
            request,
            {
                "contract_version",
                "session_id",
                "actor_id",
                "action_id",
                "expected_revision",
                "action",
                "parameters",
            },
            "request",
        )
        if value["contract_version"] != ACTION_CONTRACT_VERSION:
            raise ContractError("unsupported action contract_version")
        action = value["action"]
        if action not in {
            "move", "collect", "transfer", "repair", "rest", "scan", "harvest",
            "attack", "interact", "place_structure", "companion_move", "companion_motion", "companion_interact",
        }:
            raise ContractError("action is not supported by v1")
        if type(value["expected_revision"]) is not int or value["expected_revision"] < 0:
            raise ContractError("expected_revision must be a non-negative integer")
        expected_parameters = {
            "move": {"to"},
            "collect": {"entity_id"},
            "transfer": {"entity_id", "to_actor_id"},
            "repair": {"relay_id", "entity_id"},
            "rest": set(),
            "scan": set(),
            "harvest": {"entity_id"},
            "attack": {"entity_id"},
            "interact": {"entity_id"},
            "place_structure": {"kind", "to"},
            "companion_move": {"to"},
            "companion_motion": {"to", "mode"},
            "companion_interact": {"entity_id"},
        }[action]
        parameters = dict(
            _require_exact_keys(value["parameters"], expected_parameters, "parameters")
        )
        if action in {"move", "place_structure", "companion_move", "companion_motion"}:
            parameters["to"] = _position(parameters["to"], "parameters.to")
            if action == "place_structure":
                parameters["kind"] = _require_id(parameters["kind"], "parameters.kind")
                if parameters["kind"] not in _STRUCTURE_KINDS:
                    raise ContractError("parameters.kind is not a supported structure")
            if action == "companion_motion":
                parameters["mode"] = _require_id(parameters["mode"], "parameters.mode")
                if parameters["mode"] not in {"walk", "run", "crawl", "jump"}:
                    raise ContractError("parameters.mode is not a supported companion motion")
        else:
            for key, item in parameters.items():
                if key == "to_actor_id":
                    parameters[key] = self._actor(item)
                else:
                    parameters[key] = _require_id(item, f"parameters.{key}")
        return {
            **value,
            "session_id": _require_id(value["session_id"], "session_id"),
            "actor_id": self._actor(value["actor_id"]),
            "action_id": _require_id(value["action_id"], "action_id"),
            "parameters": parameters,
        }

    def _apply_action(
        self, state: dict[str, Any], request: Mapping[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        if state["status"] != "active":
            raise ActionRejected("session is not active")
        actor_id = request["actor_id"]
        actor = state["actors"][actor_id]
        action = request["action"]
        parameters = request["parameters"]

        if action in {"companion_move", "companion_motion", "companion_interact"}:
            if actor_id != "Alpecca":
                raise ActionRejected("companion actions require the Alpecca game actor")
            companion_activity = state["companion_activity"]

            if action in {"companion_move", "companion_motion"}:
                destination = parameters["to"]
                motion = "walk" if action == "companion_move" else parameters["mode"]
                if not (
                    0 <= destination[0] < state["grid"]["width"]
                    and 0 <= destination[1] < state["grid"]["height"]
                ):
                    raise ActionRejected("companion destination is outside the world")
                if _distance(actor["position"], destination) != 1:
                    raise ActionRejected("companion move must target one adjacent tile")
                if destination in state["world"]["blocked_tiles"]:
                    raise ActionRejected("companion destination is blocked by obsidian terrain")
                if any(
                    entity.get("position") == destination
                    and entity.get("kind") in _COMPANION_SOLID_KINDS
                    and entity.get("active", True)
                    for entity in state["entities"].values()
                ):
                    raise ActionRejected("companion destination is occupied by a solid entity")
                if any(
                    other_id != actor_id and other["position"] == destination
                    for other_id, other in state["actors"].items()
                ):
                    raise ActionRejected("companion destination is occupied by a co-op actor")
                energy_cost = 2 if motion in {"run", "jump"} else 1
                if actor["energy"] < energy_cost:
                    raise ActionRejected("companion has insufficient energy")
                origin = list(actor["position"])
                actor["position"] = destination
                actor["facing"] = [destination[0] - origin[0], destination[1] - origin[1]]
                actor["energy"] -= energy_cost
                companion_activity["motion"] = {
                    "mode": motion,
                    "from": origin,
                    "to": list(destination),
                    "revision": state["revision"] + 1,
                }
                interaction = companion_activity["interaction"]
                if interaction["entity_id"] is not None:
                    active_entity = state["entities"].get(interaction["entity_id"])
                    if (
                        active_entity is None
                        or _distance(destination, active_entity["position"]) > 1
                    ):
                        companion_activity["interaction"] = {
                            "status": "none",
                            "entity_id": None,
                            "kind": None,
                            "revision": state["revision"] + 1,
                        }
                return "companion_moved", {
                    "from": origin,
                    "to": list(destination),
                    "motion": motion,
                    "energy_cost": energy_cost,
                }

            entity_id = parameters["entity_id"]
            entity = state["entities"].get(entity_id)
            if entity is None:
                raise ActionRejected("unknown companion interaction entity_id")
            if entity.get("kind") not in _COMPANION_INTERACTION_KINDS:
                raise ActionRejected("entity is not compatible with companion interaction")
            if not entity.get("active", True) or entity.get("mode") == "offline":
                raise ActionRejected("companion interaction entity is inactive")
            distance = _distance(actor["position"], entity["position"])
            if distance > 1:
                raise ActionRejected("companion interaction entity is out of reach")
            interaction_kind = (
                "terminal" if entity["kind"] == "command_terminal" else "shelter"
            )
            companion_activity["interaction"] = {
                "status": "active",
                "entity_id": entity_id,
                "kind": interaction_kind,
                "revision": state["revision"] + 1,
            }
            return "companion_interacted", {
                "entity_id": entity_id,
                "kind": interaction_kind,
                "distance": distance,
            }

        if action == "move":
            destination = parameters["to"]
            if not (0 <= destination[0] < state["grid"]["width"] and 0 <= destination[1] < state["grid"]["height"]):
                raise ActionRejected("destination is outside the world")
            if _distance(actor["position"], destination) != 1:
                raise ActionRejected("move must target one adjacent tile")
            if destination in state["world"]["blocked_tiles"]:
                raise ActionRejected("destination is blocked by obsidian terrain")
            if actor["energy"] < 1:
                raise ActionRejected("actor has insufficient energy")
            origin = list(actor["position"])
            actor["position"] = destination
            actor["facing"] = [destination[0] - origin[0], destination[1] - origin[1]]
            actor["energy"] -= 1
            return "actor_moved", {"from": origin, "to": destination, "energy_cost": 1}

        if action == "rest":
            before = actor["energy"]
            actor["energy"] = min(_MAX_ENERGY, before + 2)
            if before == actor["energy"]:
                raise ActionRejected("actor energy is already full")
            return "actor_rested", {"energy_before": before, "energy_after": actor["energy"]}

        if action == "scan":
            if actor["energy"] < 1:
                raise ActionRejected("actor has insufficient energy")
            actor["energy"] -= 1
            threats = [
                entity_id for entity_id, entity in state["entities"].items()
                if entity.get("kind") in _THREAT_KINDS
                and entity.get("active", True)
                and _distance(actor["position"], entity["position"]) <= 5
            ]
            return "frontier_scanned", {
                "origin": list(actor["position"]), "radius": 5, "threat_ids": sorted(threats),
            }

        if action == "place_structure":
            destination = parameters["to"]
            kind = parameters["kind"]
            if not (0 <= destination[0] < state["grid"]["width"] and 0 <= destination[1] < state["grid"]["height"]):
                raise ActionRejected("structure position is outside the world")
            if _distance(actor["position"], destination) > 1:
                raise ActionRejected("structure must be placed on or beside the actor")
            if destination in state["world"]["blocked_tiles"]:
                raise ActionRejected("structure position is blocked by obsidian terrain")
            occupied = any(
                entity.get("position") == destination
                and entity.get("kind") in _STRUCTURE_KINDS | {"command_terminal", "damaged_relay"}
                for entity in state["entities"].values()
            )
            if occupied:
                raise ActionRejected("structure position is occupied")
            costs = {
                "pressure_dome": {"alloy": 4, "lumen": 1},
                "lumen_turret": {"alloy": 2, "lumen": 2},
                "oxygen_beacon": {"alloy": 2, "lumen": 1},
                "power_conduit": {"alloy": 1, "lumen": 0},
            }[kind]
            if any(actor["materials"][material] < amount for material, amount in costs.items()):
                raise ActionRejected("actor lacks the materials for this structure")
            for material, amount in costs.items():
                actor["materials"][material] -= amount
            structure_id = f"built_{request['action_id']}"
            state["entities"][structure_id] = {
                "kind": kind, "position": destination, "active": True,
                "integrity": 100, "owner": actor_id,
                **({"radius": 2} if kind == "pressure_dome" else {}),
            }
            state["contributions"][actor_id].append("built:" + structure_id)
            return "structure_placed", {
                "entity_id": structure_id, "kind": kind, "position": destination,
                "materials_spent": costs,
            }

        entity_id = parameters["entity_id"]
        entity = state["entities"].get(entity_id)
        if entity is None:
            raise ActionRejected("unknown entity_id")

        if action == "harvest":
            material = _RESOURCE_KINDS.get(entity.get("kind"))
            if material is None:
                raise ActionRejected("entity is not harvestable")
            if entity.get("remaining", 0) <= 0:
                raise ActionRejected("resource is depleted")
            if entity["position"] != actor["position"]:
                raise ActionRejected("resource is not at the actor position")
            entity["remaining"] -= 1
            actor["materials"][material] += 1
            state["contributions"][actor_id].append("harvested:" + entity_id)
            return "resource_harvested", {
                "entity_id": entity_id, "material": material,
                "remaining": entity["remaining"],
            }

        if action == "attack":
            if entity.get("kind") not in _THREAT_KINDS or not entity.get("active", True):
                raise ActionRejected("entity is not an active threat")
            distance = _distance(actor["position"], entity["position"])
            if distance > 2:
                raise ActionRejected("threat is outside weapon range")
            if actor["energy"] < 1:
                raise ActionRejected("actor has insufficient energy")
            actor["energy"] -= 1
            lumen_boost = entity["kind"] == "shadow_smoke" and actor["materials"]["lumen"] > 0
            damage = 18 if lumen_boost else 10
            entity["health"] = max(0, entity["health"] - damage)
            defeated = entity["health"] == 0
            if defeated:
                entity["active"] = False
                state["contributions"][actor_id].append("defeated:" + entity_id)
            return "threat_attacked", {
                "entity_id": entity_id, "damage": damage,
                "health_remaining": entity["health"], "defeated": defeated,
                "weakness_exploited": lumen_boost,
            }

        if action == "interact":
            if entity.get("kind") != "command_terminal":
                raise ActionRejected("entity is not an interactive command terminal")
            if _distance(actor["position"], entity["position"]) > 1:
                raise ActionRejected("command terminal is out of reach")
            return "terminal_opened", {
                "entity_id": entity_id,
                "view": "orthographic_colony_command",
                "available_structures": sorted(_STRUCTURE_KINDS),
            }

        if entity.get("kind") != "relay_component":
            raise ActionRejected("entity is not a relay component")

        if action == "collect":
            if entity["collected_by"] is not None:
                raise ActionRejected("component is no longer available")
            if entity["position"] != actor["position"]:
                raise ActionRejected("component is not at the actor position")
            entity["collected_by"] = actor_id
            actor["inventory"].append(entity_id)
            state["contributions"][actor_id].append("collected:" + entity_id)
            return "component_collected", {"entity_id": entity_id, "position": actor["position"]}

        if entity_id not in actor["inventory"]:
            raise ActionRejected("actor does not hold the component")

        if action == "transfer":
            target_id = parameters["to_actor_id"]
            if target_id == actor_id:
                raise ActionRejected("component transfer requires the co-op partner")
            target = state["actors"][target_id]
            if target["position"] != actor["position"]:
                raise ActionRejected("co-op partners must share a tile to transfer")
            actor["inventory"].remove(entity_id)
            target["inventory"].append(entity_id)
            entity["collected_by"] = target_id
            state["contributions"][actor_id].append("transferred:" + entity_id)
            state["contributions"][target_id].append("received:" + entity_id)
            relationship = state["relationships"]["Jason_Alpecca"]
            relationship["bond"] = min(100, relationship["bond"] + 2)
            relationship["trust"] = min(100, relationship["trust"] + 1)
            return "component_transferred", {"entity_id": entity_id, "from": actor_id, "to": target_id}

        relay_id = parameters["relay_id"]
        relay = state["entities"].get(relay_id)
        if relay is None or relay.get("kind") != "damaged_relay":
            raise ActionRejected("relay_id is not repairable")
        if actor["position"] != relay["position"]:
            raise ActionRejected("actor must be at the relay")
        actor["inventory"].remove(entity_id)
        relay["installed_components"].append(entity_id)
        entity["collected_by"] = "frontier_relay"
        state["contributions"][actor_id].append("installed:" + entity_id)
        installed = len(relay["installed_components"])
        state["mission"]["installed_components"] = installed
        completed = installed == relay["required_components"]
        if completed:
            state["mission"]["status"] = "completed"
            state["mission"]["phase"] = "settlement_growth"
            state["settlement"]["prosperity"] += 10
            state["settlement"]["daily_focus"] = "strengthen_vesper_landing"
            relationship = state["relationships"]["Jason_Alpecca"]
            relationship["bond"] = min(100, relationship["bond"] + 5)
            relationship["trust"] = min(100, relationship["trust"] + 3)
        return "relay_repaired", {
            "relay_id": relay_id,
            "entity_id": entity_id,
            "installed_components": installed,
            "required_components": relay["required_components"],
            "mission_completed": completed,
        }

    @staticmethod
    def _advance_world_clock(state: dict[str, Any], action: str) -> dict[str, Any]:
        clock = state["clock"]
        previous_day = clock["day"]
        clock["minute"] += 30 if action == "rest" else 10
        while clock["minute"] >= 1440:
            clock["minute"] -= 1440
            clock["day"] += 1
        minute = clock["minute"]
        if 300 <= minute < 480:
            phase = "dawn"
        elif 480 <= minute < 1020:
            phase = "day"
        elif 1020 <= minute < 1200:
            phase = "dusk"
        else:
            phase = "night"
        clock["phase"] = phase
        relationship = state["relationships"]["Jason_Alpecca"]
        if clock["day"] > previous_day:
            relationship["shared_days"] += clock["day"] - previous_day
        hours, minutes = divmod(minute, 60)
        return {
            "day": clock["day"],
            "minute": minute,
            "phase": phase,
            "label": f"{hours:02d}:{minutes:02d}",
        }

    @staticmethod
    def _apply_survival(state: dict[str, Any], actor_id: str) -> dict[str, Any]:
        """Apply one deterministic environment beat after an accepted action."""
        actor = state["actors"][actor_id]
        before = {
            key: actor[key] for key in ("health", "oxygen", "sanity", "shield")
        }
        sheltered = any(
            entity.get("kind") in {"pressure_dome", "oxygen_beacon"}
            and entity.get("active", True)
            and _distance(actor["position"], entity["position"])
            <= int(entity.get("radius", 1))
            for entity in state["entities"].values()
        )
        if sheltered:
            actor["oxygen"] = min(100, actor["oxygen"] + 2)
            actor["sanity"] = min(100, actor["sanity"] + 1)
        else:
            actor["oxygen"] = max(0, actor["oxygen"] - 1)
            actor["shield"] = max(0, actor["shield"] - 1)
            if sum(actor["position"]) % 4 == 0:
                actor["sanity"] = max(0, actor["sanity"] - 1)

        adjacent_threats = [
            entity for entity in state["entities"].values()
            if entity.get("kind") in _THREAT_KINDS
            and entity.get("active", True)
            and _distance(actor["position"], entity["position"]) <= 1
        ]
        if adjacent_threats:
            actor["health"] = max(0, actor["health"] - 4 * len(adjacent_threats))
            actor["sanity"] = max(0, actor["sanity"] - 2 * len(adjacent_threats))
        if actor["oxygen"] == 0:
            actor["health"] = max(0, actor["health"] - 8)
        if actor["health"] == 0:
            state["status"] = "failed"
            state["mission"]["status"] = "failed"
        return {
            "sheltered": sheltered,
            "nearby_threats": len(adjacent_threats),
            "before": before,
            "after": {
                key: actor[key] for key in ("health", "oxygen", "sanity", "shield")
            },
        }

    def _record_candidates(
        self,
        conn: sqlite3.Connection,
        state: dict[str, Any],
        request: Mapping[str, Any],
        event_type: str,
        payload: dict[str, Any],
        revision: int,
        timestamp: str,
    ) -> list[str]:
        candidates: list[tuple[str, dict[str, Any]]] = []
        if event_type == "component_transferred":
            candidates.append(("cooperative_handoff", {
                "actors": sorted(_ACTORS),
                "component_id": payload["entity_id"],
                "from_actor": payload["from"],
                "to_actor": payload["to"],
                "game_event": event_type,
            }))
        if event_type == "relay_repaired" and payload["mission_completed"]:
            installers = sorted(
                actor_id for actor_id, facts in state["contributions"].items()
                if any(fact.startswith("installed:") for fact in facts)
            )
            if installers == sorted(_ACTORS):
                candidates.append(("shared_mission_completion", {
                    "actors": installers,
                    "mission_id": state["mission"]["id"],
                    "installed_components": payload["installed_components"],
                    "required_components": payload["required_components"],
                    "game_event": event_type,
                }))
        ids: list[str] = []
        for kind, evidence in candidates:
            candidate_id = "ep_" + hashlib.sha256(
                f"{state['session_id']}:{revision}:{kind}".encode("ascii")
            ).hexdigest()[:24]
            conn.execute(
                "INSERT INTO game_episode_candidates VALUES (?, ?, ?, ?, ?, 'candidate', ?)",
                (candidate_id, state["session_id"], revision, kind, _canonical(evidence), timestamp),
            )
            ids.append(candidate_id)
        return ids

    def _perception(self, state: dict[str, Any], actor_id: str) -> dict[str, Any]:
        actor = state["actors"][actor_id]
        origin = actor["position"]
        observations: list[dict[str, Any]] = []
        for other_id in _ACTORS:
            if other_id == actor_id:
                continue
            other = state["actors"][other_id]
            distance = _distance(origin, other["position"])
            if distance <= _PERCEPTION_RADIUS:
                observations.append({
                    "type": "actor",
                    "id": other_id,
                    "position": list(other["position"]),
                    "distance": distance,
                    "energy_band": "low" if other["energy"] <= 2 else "ready",
                })
        for entity_id, entity in sorted(state["entities"].items()):
            if entity.get("collected_by") is not None:
                continue
            distance = _distance(origin, entity["position"])
            if distance <= _PERCEPTION_RADIUS:
                observation = {
                    "type": "entity",
                    "id": entity_id,
                    "kind": entity["kind"],
                    "position": list(entity["position"]),
                    "distance": distance,
                }
                for field in ("active", "health", "remaining", "integrity", "mode"):
                    if field in entity:
                        observation[field] = entity[field]
                observations.append(observation)
        observations.sort(key=lambda item: (item["distance"], item["type"], item["id"]))
        return {
            "contract_version": PERCEPTION_CONTRACT_VERSION,
            "session_id": state["session_id"],
            "actor_id": actor_id,
            "revision": state["revision"],
            "status": state["status"],
            "self": {
                "position": list(origin),
                "energy": actor["energy"],
                "inventory": list(actor["inventory"]),
            },
            "survival": {
                "health": actor["health"],
                "oxygen": actor["oxygen"],
                "sanity": actor["sanity"],
                "shield": actor["shield"],
                "materials": deepcopy(actor["materials"]),
                "sheltered": any(
                    entity.get("kind") in {"pressure_dome", "oxygen_beacon"}
                    and entity.get("active", True)
                    and _distance(origin, entity["position"]) <= int(entity.get("radius", 1))
                    for entity in state["entities"].values()
                ),
            },
            "world": {
                "name": state["world"]["name"],
                "biome": state["world"]["biome"],
                "visual_style": state["world"]["visual_style"],
                "weather": state["world"]["weather"],
                "storm_intensity": state["world"]["storm_intensity"],
                "grid": deepcopy(state["grid"]),
                "clock": deepcopy(state["clock"]),
                "settlement": deepcopy(state["settlement"]),
            },
            "mission": deepcopy(state["mission"]),
            "relationship": deepcopy(state["relationships"]["Jason_Alpecca"]),
            "companion_activity": self._companion_activity_projection(state, actor_id),
            "bounds": {
                "metric": "manhattan",
                "radius": _PERCEPTION_RADIUS,
                "max_observations": _MAX_OBSERVATIONS,
            },
            "observations": observations[:_MAX_OBSERVATIONS],
            "truncated": len(observations) > _MAX_OBSERVATIONS,
        }

    @staticmethod
    def _companion_activity_projection(
        state: dict[str, Any], viewer_actor_id: str
    ) -> dict[str, Any]:
        """Return fixed, nearby game activity without exposing companion internals."""
        companion = state["actors"]["Alpecca"]
        viewer = state["actors"][viewer_actor_id]
        distance = _distance(viewer["position"], companion["position"])
        if distance > _PERCEPTION_RADIUS:
            return {"visible": False}

        activity = state["companion_activity"]
        interaction = activity["interaction"]
        entity = (
            state["entities"].get(interaction["entity_id"])
            if interaction["entity_id"] is not None
            else None
        )
        interaction_visible = entity is not None and _distance(
            viewer["position"], entity["position"]
        ) <= _PERCEPTION_RADIUS
        return {
            "visible": True,
            "position": list(companion["position"]),
            "distance": distance,
            "motion": {
                "mode": activity["motion"]["mode"],
                "from": list(activity["motion"]["from"]),
                "to": list(activity["motion"]["to"]),
                "revision": activity["motion"]["revision"],
            },
            "interaction": (
                {
                    "status": interaction["status"],
                    "entity_id": interaction["entity_id"],
                    "kind": interaction["kind"],
                    "revision": interaction["revision"],
                }
                if interaction_visible
                else {"status": "none"}
            ),
        }
