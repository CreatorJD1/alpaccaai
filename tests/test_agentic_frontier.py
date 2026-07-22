from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from alpecca import game_memory, state


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "apps" / "agentic-frontier"
sys.path.insert(0, str(APP_ROOT))

from agentic_frontier import (  # noqa: E402
    ACTION_CONTRACT_VERSION,
    ActionConflict,
    ActionRejected,
    AgenticFrontierStore,
    ContractError,
)
from agentic_frontier.app import create_app  # noqa: E402


def action(session: str, actor: str, action_id: str, revision: int, name: str, **parameters):
    return {
        "contract_version": ACTION_CONTRACT_VERSION,
        "session_id": session,
        "actor_id": actor,
        "action_id": action_id,
        "expected_revision": revision,
        "action": name,
        "parameters": parameters,
    }


def test_world_and_perception_are_server_owned_and_bounded(tmp_path: Path) -> None:
    store = AgenticFrontierStore(tmp_path / "frontier.sqlite3")
    state = store.create_session("expedition_1")

    assert state["actors"].keys() == {"Jason", "Alpecca"}
    view = store.perceive("expedition_1", "Jason")
    assert view["bounds"] == {
        "metric": "manhattan",
        "radius": 2,
        "max_observations": 16,
    }
    assert all(item["distance"] <= 2 for item in view["observations"])
    assert "frontier_relay" not in {item["id"] for item in view["observations"]}
    assert set(view["self"]) == {"position", "energy", "inventory"}
    assert "contributions" not in json.dumps(view)


def test_action_validation_rejects_teleports_stale_writes_and_extra_context(tmp_path: Path) -> None:
    store = AgenticFrontierStore(tmp_path / "frontier.sqlite3")
    store.create_session("expedition_2")

    with pytest.raises(ActionRejected, match="adjacent"):
        store.execute_action(action("expedition_2", "Jason", "teleport", 0, "move", to=[4, 4]))
    with pytest.raises(ContractError, match="keys must be exactly"):
        request = action("expedition_2", "Jason", "memory", 0, "rest")
        request["companion_memory"] = "private recollection"
        store.execute_action(request)

    accepted = store.execute_action(action("expedition_2", "Jason", "step_1", 0, "move", to=[1, 0]))
    assert accepted["revision"] == 1
    with pytest.raises(ActionConflict, match="expected_revision"):
        store.execute_action(action("expedition_2", "Alpecca", "stale", 0, "move", to=[1, 1]))


def test_companion_activity_is_authoritative_nearby_and_memory_free(tmp_path: Path) -> None:
    store = AgenticFrontierStore(tmp_path / "frontier.sqlite3")
    store.create_session("companion_activity")

    with pytest.raises(ActionRejected, match="require the Alpecca game actor"):
        store.execute_action(
            action(
                "companion_activity", "Jason", "wrong_actor", 0,
                "companion_move", to=[0, 2],
            )
        )
    with pytest.raises(ActionRejected, match="solid entity"):
        store.execute_action(
            action(
                "companion_activity", "Alpecca", "solid_terminal", 0,
                "companion_move", to=[1, 1],
            )
        )
    with pytest.raises(ActionRejected, match="adjacent"):
        store.execute_action(
            action(
                "companion_activity", "Alpecca", "teleport", 0,
                "companion_move", to=[0, 4],
            )
        )
    with pytest.raises(ActionRejected, match="outside the world"):
        store.execute_action(
            action(
                "companion_activity", "Alpecca", "outside_world", 0,
                "companion_move", to=[-1, 1],
            )
        )
    with pytest.raises(ActionRejected, match="not compatible"):
        store.execute_action(
            action(
                "companion_activity", "Alpecca", "wrong_entity", 0,
                "companion_interact", entity_id="ferrite_1",
            )
        )

    opened = store.execute_action(
        action(
            "companion_activity", "Alpecca", "terminal_use", 0,
            "companion_interact", entity_id="colony_terminal",
        )
    )
    assert opened["event"]["type"] == "companion_interacted"
    assert opened["event"]["facts"]["entity_id"] == "colony_terminal"
    assert opened["event"]["facts"]["kind"] == "terminal"
    assert opened["event"]["facts"]["distance"] == 1

    moved = store.execute_action(
        action(
            "companion_activity", "Alpecca", "walk_away", 1,
            "companion_move", to=[0, 2],
        )
    )
    assert moved["event"]["type"] == "companion_moved"
    state = store.world_state("companion_activity")
    assert state["companion_activity"] == {
        "motion": {"mode": "walk", "from": [0, 1], "to": [0, 2], "revision": 2},
        "interaction": {"status": "none", "entity_id": None, "kind": None, "revision": 2},
    }
    view = store.perceive("companion_activity", "Jason")
    assert view["companion_activity"] == {
        "visible": True,
        "position": [0, 2],
        "distance": 2,
        "motion": {"mode": "walk", "from": [0, 1], "to": [0, 2], "revision": 2},
        "interaction": {"status": "none"},
    }
    assert "memory" not in json.dumps(view["companion_activity"])


def test_companion_motion_modes_are_validated_and_durable(tmp_path: Path) -> None:
    store = AgenticFrontierStore(tmp_path / "frontier.sqlite3")
    store.create_session("companion_motion")

    with pytest.raises(ContractError, match="supported companion motion"):
        store.execute_action(
            action(
                "companion_motion", "Alpecca", "hover", 0,
                "companion_motion", to=[0, 2], mode="hover",
            )
        )

    moved = store.execute_action(
        action(
            "companion_motion", "Alpecca", "run_to_relay", 0,
            "companion_motion", to=[0, 2], mode="run",
        )
    )
    assert moved["event"]["type"] == "companion_moved"
    assert moved["event"]["facts"]["motion"] == "run"
    assert moved["event"]["facts"]["energy_cost"] == 2
    state = store.world_state("companion_motion")
    assert state["companion_activity"]["motion"]["mode"] == "run"


def test_replay_is_idempotent_payload_bound_and_survives_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "frontier.sqlite3"
    store = AgenticFrontierStore(db_path)
    store.create_session("expedition_3")
    request = action("expedition_3", "Jason", "durable_step", 0, "move", to=[1, 0])
    first = store.execute_action(request)

    reopened = AgenticFrontierStore(db_path)
    assert reopened.execute_action(request) == first
    assert reopened.world_state("expedition_3")["revision"] == 1
    conflicting = action("expedition_3", "Jason", "durable_step", 1, "move", to=[0, 1])
    with pytest.raises(ActionConflict, match="different request"):
        reopened.execute_action(conflicting)


def test_reconnect_returns_only_callers_durable_receipts(tmp_path: Path) -> None:
    store = AgenticFrontierStore(tmp_path / "frontier.sqlite3")
    store.create_session("expedition_4")
    store.execute_action(action("expedition_4", "Jason", "j1", 0, "move", to=[1, 0]))
    store.execute_action(action("expedition_4", "Alpecca", "a1", 1, "move", to=[1, 1]))

    resumed = AgenticFrontierStore(store.db_path).reconnect("expedition_4", "Jason", 0)
    assert resumed["authoritative_revision"] == 2
    assert [receipt["action_id"] for receipt in resumed["receipts"]] == ["j1"]
    assert resumed["perception"]["revision"] == 2
    with pytest.raises(ActionConflict, match="ahead"):
        store.reconnect("expedition_4", "Jason", 3)


def test_tartarus_survival_harvest_and_colony_build_loop(tmp_path: Path) -> None:
    store = AgenticFrontierStore(tmp_path / "frontier.sqlite3")
    created = store.create_session("tartarus_loop")
    assert created["world"]["name"] == "Tartarus Prime"
    assert created["world"]["visual_style"] == "anime_cel_shaded"

    requests = [
        action("tartarus_loop", "Jason", "south", 0, "move", to=[1, 0]),
        action("tartarus_loop", "Jason", "terminal", 1, "interact", entity_id="colony_terminal"),
        action("tartarus_loop", "Jason", "north", 2, "move", to=[1, 1]),
        action("tartarus_loop", "Jason", "north_again", 3, "move", to=[1, 2]),
        action("tartarus_loop", "Jason", "harvest", 4, "harvest", entity_id="ferrite_1"),
        action(
            "tartarus_loop", "Jason", "build_conduit", 5, "place_structure",
            kind="power_conduit", to=[1, 3],
        ),
    ]
    responses = [store.execute_action(request) for request in requests]
    assert responses[1]["event"]["facts"]["view"] == "orthographic_colony_command"
    assert responses[4]["event"]["facts"]["material"] == "alloy"
    assert responses[5]["event"]["facts"]["kind"] == "power_conduit"
    state = store.world_state("tartarus_loop")
    assert state["entities"]["built_build_conduit"]["owner"] == "Jason"
    assert state["actors"]["Jason"]["oxygen"] < 100
    assert state["clock"] == {"day": 1, "minute": 480, "phase": "day"}
    assert state["settlement"]["name"] == "Vesper Landing"


def test_tartarus_threat_combat_obeys_range_and_weakness(tmp_path: Path) -> None:
    store = AgenticFrontierStore(tmp_path / "frontier.sqlite3")
    store.create_session("combat_loop")
    with pytest.raises(ActionRejected, match="weapon range"):
        store.execute_action(
            action("combat_loop", "Jason", "too_far", 0, "attack", entity_id="shade_1")
        )
    state = store.world_state("combat_loop")
    state["actors"]["Jason"]["position"] = [5, 4]
    with store._connect() as conn:  # Seed a deterministic combat setup at the authority boundary.
        conn.execute(
            "UPDATE game_sessions SET state_json=? WHERE session_id=?",
            (json.dumps(state, sort_keys=True, separators=(",", ":")), "combat_loop"),
        )
        conn.commit()
    response = store.execute_action(
        action("combat_loop", "Jason", "lumen_hit", 0, "attack", entity_id="shade_1")
    )
    assert response["event"]["facts"]["weakness_exploited"] is True
    assert response["event"]["facts"]["damage"] == 18


def test_legacy_relay_session_is_upgraded_without_losing_progress(tmp_path: Path) -> None:
    store = AgenticFrontierStore(tmp_path / "frontier.sqlite3")
    store.create_session("legacy_run")
    legacy = {
        "contract_version": "agentic_frontier.world.v1",
        "session_id": "legacy_run",
        "revision": 3,
        "status": "active",
        "grid": {"width": 5, "height": 5},
        "actors": {
            "Jason": {"position": [2, 1], "energy": 4, "inventory": ["component_j"]},
            "Alpecca": {"position": [0, 2], "energy": 5, "inventory": []},
        },
        "entities": {},
        "mission": {"id": "restore_frontier_relay", "status": "active"},
        "contributions": {"Jason": ["collected:component_j"], "Alpecca": []},
    }
    with store._connect() as conn:
        conn.execute(
            "UPDATE game_sessions SET revision=3, state_json=? WHERE session_id=?",
            (json.dumps(legacy, sort_keys=True, separators=(",", ":")), "legacy_run"),
        )
        conn.commit()

    upgraded = store.world_state("legacy_run")
    assert upgraded["contract_version"] == "agentic_frontier.world.v2"
    assert upgraded["grid"]["width"] == 18
    assert upgraded["actors"]["Jason"]["position"] == [2, 1]
    assert upgraded["actors"]["Jason"]["health"] == 100
    assert upgraded["entities"]["component_j"]["collected_by"] == "Jason"
    assert upgraded["contributions"]["Jason"] == ["collected:component_j"]
    assert upgraded["world"]["name"] == "Tartarus Prime"


def test_two_distinct_contributors_create_meaningful_completion_candidate(tmp_path: Path) -> None:
    store = AgenticFrontierStore(tmp_path / "frontier.sqlite3")
    store.create_session("coop_run")
    requests = [
        action("coop_run", "Jason", "j-move-1", 0, "move", to=[1, 0]),
        action("coop_run", "Jason", "j-collect", 1, "collect", entity_id="component_j"),
        action("coop_run", "Alpecca", "a-move-1", 2, "move", to=[0, 2]),
        action("coop_run", "Alpecca", "a-collect", 3, "collect", entity_id="component_a"),
        action("coop_run", "Jason", "j-move-2", 4, "move", to=[2, 0]),
        action("coop_run", "Jason", "j-move-3", 5, "move", to=[2, 1]),
        action("coop_run", "Jason", "j-move-4", 6, "move", to=[2, 2]),
        action("coop_run", "Jason", "j-repair", 7, "repair", relay_id="frontier_relay", entity_id="component_j"),
        action("coop_run", "Alpecca", "a-move-2", 8, "move", to=[1, 2]),
        action("coop_run", "Alpecca", "a-move-3", 9, "move", to=[2, 2]),
        action("coop_run", "Alpecca", "a-repair", 10, "repair", relay_id="frontier_relay", entity_id="component_a"),
    ]
    response = None
    for request in requests:
        response = store.execute_action(request)

    assert response is not None
    assert response["event"]["facts"]["mission_completed"] is True
    assert store.world_state("coop_run")["status"] == "active"
    assert store.world_state("coop_run")["relationships"]["Jason_Alpecca"]["bond"] == 5
    candidates = store.list_episode_candidates("coop_run")
    assert [candidate["kind"] for candidate in candidates] == ["shared_mission_completion"]
    assert candidates[0]["evidence"] == {
        "actors": ["Alpecca", "Jason"],
        "game_event": "relay_repaired",
        "installed_components": 2,
        "mission_id": "restore_frontier_relay",
        "required_components": 2,
    }
    assert response["game_episode_candidate_ids"] == [candidates[0]["candidate_id"]]


def test_game_storage_is_explicitly_separate_from_companion_memory(tmp_path: Path) -> None:
    db_path = tmp_path / "frontier.sqlite3"
    store = AgenticFrontierStore(db_path)
    contract = store.storage_contract()

    assert contract["memory_boundary"]["promotion"] == "validated_external_companion_adapter_required"
    assert all(name.startswith("game_") for name in contract["tables"])
    assert all("memory" not in name and "journal" not in name for name in contract["tables"])
    with sqlite3.connect(db_path) as conn:
        boundary = conn.execute(
            "SELECT value_json FROM game_contract_metadata WHERE key='memory_boundary'"
        ).fetchone()[0]
    assert json.loads(boundary)["owner"] == "agentic_frontier_game"

    module = importlib.import_module("agentic_frontier.engine")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "from alpecca" not in source
    assert "import alpecca" not in source


def test_validated_shared_episode_crosses_companion_boundary(tmp_path: Path) -> None:
    companion_db = tmp_path / "alpecca.db"
    state.init_db(companion_db)
    candidate = {
        "contract_version": "agentic_frontier.game_episode_candidate.v1",
        "candidate_id": "ep_shared_relay",
        "session_id": "shared-run",
        "source_revision": 12,
        "kind": "shared_mission_completion",
        "status": "candidate",
        "evidence": {
            "actors": ["Jason", "Alpecca"],
            "mission_id": "restore_frontier_relay",
            "installed_components": 2,
            "required_components": 2,
            "game_event": "relay_repaired",
        },
    }
    assert game_memory.promote_frontier_episode(candidate, db_path=companion_db)
    with sqlite3.connect(companion_db) as conn:
        event = conn.execute(
            "SELECT kind, scope FROM continuity_events"
        ).fetchone()
    assert event == ("game_episode", "game:agentic-frontier:shared-run")


def test_unshared_episode_does_not_become_companion_memory(tmp_path: Path) -> None:
    companion_db = tmp_path / "alpecca.db"
    state.init_db(companion_db)
    candidate = {
        "contract_version": "agentic_frontier.game_episode_candidate.v1",
        "candidate_id": "ep_solo",
        "session_id": "solo-run",
        "source_revision": 1,
        "kind": "shared_mission_completion",
        "status": "candidate",
        "evidence": {"actors": ["Alpecca"], "mission_id": "solo"},
    }
    assert game_memory.promote_frontier_episode(candidate, db_path=companion_db) is None


def test_frontier_is_a_standalone_authenticated_app(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    db_path = tmp_path / "standalone-frontier.db"
    app = create_app(db_path=db_path, access_token="frontier-test-token")
    assert not db_path.exists()
    with TestClient(app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json() == {
            "ok": True,
            "appId": "agentic-frontier",
            "kind": "game",
            "coreMind": False,
            "databaseOwner": "agentic-frontier",
            "accessProtected": True,
            "accountAccess": True,
        }
        assert client.post("/api/sessions", json={"session_id": "separate"}).status_code == 401
        created = client.post(
            "/api/sessions",
            json={"session_id": "separate"},
            headers={"authorization": "Bearer frontier-test-token"},
        )
        assert created.status_code == 200
        assert created.json()["session_id"] == "separate"
        assert "entities" not in created.json()
        assert "actors" not in created.json()
    assert db_path.is_file()


def test_frontier_requires_a_player_account_when_no_service_token_is_configured(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = create_app(db_path=tmp_path / "public-frontier.db", access_token="")
    with TestClient(app, client=("203.0.113.8", 443)) as client:
        assert client.get("/healthz").json()["accessProtected"] is True
        assert client.post("/api/sessions", json={"session_id": "public-preview"}).status_code == 401
        registered = client.post(
            "/api/auth/register",
            json={
                "username": "public_player",
                "displayName": "Public Player",
                "password": "correct-horse-47",
            },
        )
        world_id = registered.json()["account"]["worldId"]
        created = client.post("/api/sessions", json={"session_id": world_id})
    assert created.status_code == 200
    assert created.json()["session_id"] == world_id


def test_frontier_exposes_3d_game_config_and_vrm_asset(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    app = create_app(db_path=tmp_path / "frontier.db", access_token="")
    with TestClient(app) as client:
        config = client.get("/api/config")
        assert config.status_code == 200
        assert config.json()["world"] == "Vesper Dome / Tartarus Prime"
        assert config.json()["visualStyle"] == "anime-cel-shaded"
        assert config.json()["modes"] == [
            "first-person-exploration", "orthographic-colony-command"
        ]
        vrm = client.get("/assets/alpecca.vrm", headers={"range": "bytes=0-31"})
        assert vrm.status_code in {200, 206}
        assert int(vrm.headers["content-length"]) > 0


def test_frontier_is_not_mounted_inside_house_or_coremind() -> None:
    manifest = json.loads((APP_ROOT / "app-manifest.json").read_text(encoding="utf-8"))
    assert manifest["appId"] == "agentic-frontier"
    assert manifest["kind"] == "game"
    assert manifest["coreMindEmbedded"] is False
    assert manifest["houseHqEmbedded"] is False
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")
    app_source = (APP_ROOT / "agentic_frontier" / "app.py").read_text(encoding="utf-8")
    assert "agentic_frontier" not in server_source
    assert "from alpecca" not in app_source
    assert "import alpecca" not in app_source
