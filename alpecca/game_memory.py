"""Narrow, evidence-backed boundary from games into companion memory."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from alpecca import memory
from config import DB_PATH


EPISODE_CONTRACT = "agentic_frontier.game_episode_candidate.v1"
_KINDS = {"cooperative_handoff", "shared_mission_completion"}


def promote_frontier_episode(
    candidate: Mapping[str, object], *, db_path: Path = DB_PATH
) -> int | None:
    """Store only validated shared events, never raw game state or telemetry."""
    if set(candidate) != {
        "contract_version", "candidate_id", "session_id", "source_revision",
        "kind", "status", "evidence",
    }:
        return None
    if candidate.get("contract_version") != EPISODE_CONTRACT:
        return None
    if candidate.get("status") != "candidate" or candidate.get("kind") not in _KINDS:
        return None
    evidence = candidate.get("evidence")
    if not isinstance(evidence, Mapping):
        return None
    actors = evidence.get("actors")
    if not isinstance(actors, list) or sorted(str(actor) for actor in actors) != ["Alpecca", "Jason"]:
        return None
    session_id = str(candidate.get("session_id") or "")
    candidate_id = str(candidate.get("candidate_id") or "")
    if not session_id or not candidate_id:
        return None
    if candidate["kind"] == "cooperative_handoff":
        content = (
            "In Agentic Frontier, Jason and Alpecca completed a cooperative "
            f"handoff of {evidence.get('component_id', 'a relay component')}."
        )
        salience = 0.72
    else:
        content = (
            "In Agentic Frontier, Jason and Alpecca worked together to complete "
            f"the {evidence.get('mission_id', 'frontier relay')} mission."
        )
        salience = 0.9
    return memory.remember_with_id(
        content,
        kind="episodic",
        salience=salience,
        db_path=db_path,
        embed_fn=None,
        source="agentic_frontier",
        scope=f"game:agentic-frontier:{session_id}"[:160],
    )


__all__ = ["promote_frontier_episode"]
