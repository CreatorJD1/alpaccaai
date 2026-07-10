"""End-to-end Phase 4 commitment truthfulness through ``CoreMind.chat``."""
from __future__ import annotations

from collections.abc import Callable

from alpecca import commitments, turn_context
from alpecca.commitment_language import classify_action_claims
from alpecca.homeostasis import EmotionalState


def _bind_db(function: Callable, db_path):
    def bound(*args, **kwargs):
        kwargs["db_path"] = db_path
        return function(*args, **kwargs)

    return bound


def _core_mind(monkeypatch, tmp_path, generate):
    """Construct CoreMind with isolated history/commitment stores and no live I/O."""
    commitment_db = tmp_path / "phase4-commitments.db"
    history_db = tmp_path / "phase4-history.db"
    original_commitments = {
        "create": commitments.create_commitment,
        "get": commitments.get_commitment,
        "list": commitments.list_commitments,
        "transition": commitments.transition_commitment,
    }
    original_history = {
        "load": turn_context.load_history,
        "save": turn_context.save_history,
    }
    monkeypatch.setattr(
        commitments, "create_commitment",
        _bind_db(original_commitments["create"], commitment_db),
    )
    monkeypatch.setattr(
        commitments, "get_commitment",
        _bind_db(original_commitments["get"], commitment_db),
    )
    monkeypatch.setattr(
        commitments, "list_commitments",
        _bind_db(original_commitments["list"], commitment_db),
    )
    monkeypatch.setattr(
        commitments, "transition_commitment",
        _bind_db(original_commitments["transition"], commitment_db),
    )
    monkeypatch.setattr(
        turn_context, "load_history",
        _bind_db(original_history["load"], history_db),
    )
    monkeypatch.setattr(
        turn_context, "save_history",
        _bind_db(original_history["save"], history_db),
    )

    from alpecca import mind as mind_mod
    from config import Actions as ActionsCfg

    class FakeLLM:
        def __init__(self):
            self.online = True
            self._last_call = {
                "requested_tier": "reason",
                "used_tier": "reason",
                "backend": "phase4-test",
                "model": "deterministic-fake",
                "ok": True,
                "fallback": False,
                "error": "",
            }

        def generate(self, *args, **kwargs):
            return generate(*args, **kwargs)

        def last_call(self):
            return dict(self._last_call)

        def is_cloud(self):
            return False

    class FakePortraitWorker:
        def request(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(ActionsCfg, "INNATE_TOOLS", False)
    monkeypatch.setattr(mind_mod, "_LLM", FakeLLM)
    monkeypatch.setattr(mind_mod, "PortraitWorker", FakePortraitWorker)
    monkeypatch.setattr(mind_mod.state_store, "init_db", lambda: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "init_db", lambda: None)
    monkeypatch.setattr(mind_mod.state_store, "load_state", lambda: EmotionalState())
    monkeypatch.setattr(mind_mod.state_store, "load_appearance_seed", lambda: 7)
    monkeypatch.setattr(mind_mod.state_store, "load_location", lambda: "parlor")
    monkeypatch.setattr(mind_mod.state_store, "save_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.state_store, "save_location", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.state_store, "mood_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.cognition_mod, "set_intent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "current_intent", lambda: {"name": "waiting"})
    monkeypatch.setattr(mind_mod.cognition_mod, "record_observation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "record_chat_turn", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        mind_mod.cognition_mod, "mark_observation_remembered",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(mind_mod.memory_store, "count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(mind_mod.memory_store, "recent", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.memory_store, "recall", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        mind_mod.memory_store, "remember_with_id", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(mind_mod.mindpage_mod, "prefault_pages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        mind_mod.mindpage_mod, "pressure_snapshot",
        lambda *args, **kwargs: dict(kwargs.get("ledger") or {}),
    )
    monkeypatch.setattr(mind_mod.journal_mod, "open_questions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.people_mod, "who_prompt", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mind_mod.core_mem, "prompt_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        mind_mod.speech_mod, "spoken_performance_text", lambda text, _state: text
    )
    monkeypatch.setattr(mind_mod.speech_mod, "speech_cues", lambda _state: {})

    mind = mind_mod.CoreMind()
    monkeypatch.setattr(mind, "try_go_to_room", lambda _message: False)
    return mind, commitment_db, history_db, original_commitments, original_history


def _turn(scope: str, conversation: str) -> turn_context.TurnContext:
    return turn_context.TurnContext.create(
        conversation,
        principal="guest",
        surface="websocket",
        privacy_scope=scope,
        portal_epoch="phase4-test-epoch",
    )


def test_future_action_reply_creates_scoped_proposal_and_rewrites_promise(
    monkeypatch, tmp_path
):
    raw_reply = "I'll update the terminal configuration now."
    mind, commitment_db, history_db, commitment_api, history_api = _core_mind(
        monkeypatch, tmp_path, lambda *_args, **_kwargs: raw_reply
    )
    turn = _turn("guest-phase4-a", "future-action")

    result = mind.chat("Please update the terminal configuration.", turn=turn)

    scoped = commitment_api["list"](
        scope=turn.memory_scope, db_path=commitment_db
    )
    assert len(scoped) == 1
    assert scoped[0]["state"] == commitments.PROPOSED
    assert scoped[0]["scope"] == turn.memory_scope
    assert scoped[0]["receipt"] is None
    assert "terminal" in scoped[0]["action"].lower()
    assert commitment_api["list"](
        scope="creator-personal", db_path=commitment_db
    ) == []

    delivered = result["reply"]
    assert delivered != raw_reply
    assert "propos" in delivered.lower()
    assert "approved" in delivered.lower()
    assert "i'll" not in delivered.lower()
    history = history_api["load"](turn, db_path=history_db)
    assert history[-1] == {"role": "assistant", "content": delivered}


def test_completion_claim_without_success_receipt_is_not_reported_complete(
    monkeypatch, tmp_path
):
    raw_reply = "Done. I updated the terminal configuration."
    mind, commitment_db, _history_db, commitment_api, _history_api = _core_mind(
        monkeypatch, tmp_path, lambda *_args, **_kwargs: raw_reply
    )
    turn = _turn("guest-phase4-b", "unsupported-completion")

    result = mind.chat("What happened with the terminal configuration?", turn=turn)

    analysis = classify_action_claims(result["reply"])
    assert all(claim.kind != "completion" for claim in analysis.claims)
    assert result["reply"] != raw_reply
    assert "cannot confirm" in result["reply"].lower()
    for item in commitment_api["list"](
        scope=turn.memory_scope, db_path=commitment_db
    ):
        assert not (
            item["state"] == commitments.SUCCEEDED
            and item["receipt"]
            and item["receipt"].get("status") == commitments.SUCCEEDED
        )


def test_cancelled_future_action_turn_creates_no_commitment_or_history(
    monkeypatch, tmp_path
):
    turn = _turn("guest-phase4-c", "cancelled-future-action")

    def cancel_during_generation(*_args, **_kwargs):
        turn.cancel("test cancellation")
        return "I'll update the terminal configuration now."

    mind, commitment_db, history_db, commitment_api, history_api = _core_mind(
        monkeypatch, tmp_path, cancel_during_generation
    )

    result = mind.chat("Please update the terminal configuration.", turn=turn)

    assert result["cancelled"] is True
    assert result["turn"]["commit_state"] == "cancelled"
    assert commitment_api["list"](
        scope=turn.memory_scope, db_path=commitment_db
    ) == []
    assert history_api["load"](turn, db_path=history_db) == []
