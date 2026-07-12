"""Focused Phase 4 authenticated confirmation wiring coverage."""
from __future__ import annotations

from alpecca import turn_context
from alpecca.homeostasis import EmotionalState


def _core_mind(monkeypatch, generate):
    """Build CoreMind without touching shared databases or external systems."""
    from alpecca import mind as mind_mod

    class FakeLLM:
        online = True

        def generate(self, *args, **kwargs):
            return generate(*args, **kwargs)

        def last_call(self):
            return {
                "requested_tier": "reason",
                "used_tier": "reason",
                "backend": "test",
                "model": "fake",
                "ok": True,
                "fallback": False,
                "error": "",
            }

        def is_cloud(self):
            return False

    class FakePortraitWorker:
        def request(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(mind_mod, "_LLM", FakeLLM)
    monkeypatch.setattr(mind_mod, "PortraitWorker", FakePortraitWorker)
    monkeypatch.setattr(mind_mod.state_store, "init_db", lambda: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "init_db", lambda: None)
    monkeypatch.setattr(mind_mod.turn_context_mod, "ensure_history_schema", lambda: None)
    monkeypatch.setattr(mind_mod.state_store, "load_state", lambda: EmotionalState())
    monkeypatch.setattr(mind_mod.state_store, "load_appearance_seed", lambda: 7)
    monkeypatch.setattr(mind_mod.state_store, "load_location", lambda: "parlor")
    monkeypatch.setattr(mind_mod.state_store, "save_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.state_store, "save_location", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.state_store, "mood_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.cognition_mod, "set_intent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "current_intent", lambda: {"name": "waiting"})
    monkeypatch.setattr(mind_mod.cognition_mod, "record_observation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "record_chat_turn", lambda *_args, **_kwargs: 71)
    monkeypatch.setattr(
        mind_mod.cognition_mod,
        "mark_observation_remembered",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(mind_mod.memory_store, "count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(mind_mod.memory_store, "recent", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.memory_store, "recall", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        mind_mod.memory_store,
        "remember_with_id",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(mind_mod.mindpage_mod, "prefault_pages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        mind_mod.mindpage_mod,
        "pressure_snapshot",
        lambda *args, **kwargs: dict(kwargs.get("ledger") or {}),
    )
    monkeypatch.setattr(mind_mod.journal_mod, "open_questions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.people_mod, "who_prompt", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mind_mod.core_mem, "prompt_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        mind_mod.speech_mod,
        "spoken_performance_text",
        lambda text, _state: text,
    )
    monkeypatch.setattr(mind_mod.speech_mod, "speech_cues", lambda _state: {})
    monkeypatch.setattr(mind_mod.turn_context_mod, "load_history", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.turn_context_mod, "save_history", lambda *_args, **_kwargs: None)

    mind = mind_mod.CoreMind()
    monkeypatch.setattr(mind, "try_go_to_room", lambda _message: False)
    monkeypatch.setattr(mind, "_tool_schema", lambda *_args, **_kwargs: None)
    return mind, mind_mod


def _turn(scope: str = "creator-confirmation") -> turn_context.TurnContext:
    return turn_context.TurnContext.create(
        "confirmation-chat",
        principal="creator",
        surface="app",
        privacy_scope=scope,
        portal_epoch="phase4-confirmation",
    )


def _proposal(commitment_id: int, scope: str, action: str = "update terminal") -> dict:
    return {
        "id": commitment_id,
        "scope": scope,
        "state": "proposed",
        "action": action,
        "receipt": None,
        "receipts": [],
    }


def test_exactly_one_scoped_confirmation_transitions_to_approved(monkeypatch):
    active_turn = _turn()
    events: list[str] = []
    captured = {}

    def generate(*_args, **_kwargs):
        events.append("generate")
        assert active_turn.barrier.state == "pending"
        return "I'll handle the approved terminal update."

    mind, mind_mod = _core_mind(monkeypatch, generate)
    pending = _proposal(11, active_turn.memory_scope)

    def list_pending(*, scope, state, limit):
        events.append("list")
        assert active_turn.barrier.state == "committing"
        assert (scope, state, limit) == (
            active_turn.memory_scope,
            mind_mod.commitments_mod.PROPOSED,
            mind_mod.action_closure_mod.MAX_COMMITMENTS,
        )
        return [pending]

    def transition(commitment_id, to_state, *, scope, evidence):
        events.append("transition")
        assert active_turn.barrier.state == "committing"
        captured.update(
            commitment_id=commitment_id,
            to_state=to_state,
            scope=scope,
            evidence=evidence,
        )
        return {**pending, "state": "approved"}

    monkeypatch.setattr(mind_mod.commitments_mod, "list_commitments", list_pending)
    monkeypatch.setattr(mind_mod.commitments_mod, "transition_commitment", transition)
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "create_commitment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("confirmation must not create a duplicate proposal")
        ),
    )

    result = mind.chat("Yes, do it.", turn=active_turn)

    assert events == ["generate", "list", "transition"]
    assert captured["commitment_id"] == 11
    assert captured["to_state"] == mind_mod.commitments_mod.APPROVED
    assert captured["scope"] == active_turn.memory_scope
    assert captured["evidence"]["source"] == "authenticated_confirmation"
    assert captured["evidence"]["turn"]["commit_state"] == "committing"
    assert captured["evidence"]["turn"]["turn_id"] == active_turn.turn_id
    assert len(captured["evidence"]["cues"]) <= 7
    assert all(
        len(snippet) <= 120
        for cue in captured["evidence"]["cues"]
        for snippet in cue["evidence"]
    )
    assert result["confirmation"] == {
        "authenticated": True,
        "detected": True,
        "outcome": "resolved",
        "scope": active_turn.memory_scope,
        "commitment_id": 11,
        "candidate_ids": [11],
        "action": "update terminal",
        "approved": True,
        "state": "approved",
        "truncated": False,
        "error": "",
    }
    assert result["commitment"]["created"] is False
    assert result["commitment"]["approved"] is True
    assert result["commitment"]["source"] == "confirmation"


def test_ambiguous_confirmation_is_not_approved_or_reproposed(monkeypatch):
    active_turn = _turn("guest-ambiguous")

    def generate(*_args, **_kwargs):
        return "I'll do it now."

    mind, mind_mod = _core_mind(monkeypatch, generate)
    transitions = []
    creations = []
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "list_commitments",
        lambda **_kwargs: [
            _proposal(1, active_turn.memory_scope, "update terminal"),
            _proposal(2, active_turn.memory_scope, "send report"),
        ],
    )
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "transition_commitment",
        lambda *args, **kwargs: transitions.append((args, kwargs)),
    )
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "create_commitment",
        lambda *args, **kwargs: creations.append((args, kwargs)),
    )

    result = mind.chat("Yes, proceed.", turn=active_turn)

    assert result["confirmation"]["outcome"] == "ambiguous"
    assert result["confirmation"]["candidate_ids"] == [1, 2]
    assert result["confirmation"]["approved"] is False
    assert transitions == []
    assert creations == []
    assert "i'll" not in result["reply"].lower()
    assert "unavailable" in result["reply"].lower()


def test_cross_scope_proposal_cannot_be_approved(monkeypatch):
    active_turn = _turn("guest-current")

    mind, mind_mod = _core_mind(
        monkeypatch,
        lambda *_args, **_kwargs: "I need an unambiguous scoped action first.",
    )
    transitions = []
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "list_commitments",
        lambda **_kwargs: [_proposal(9, "creator-personal")],
    )
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "transition_commitment",
        lambda *args, **kwargs: transitions.append((args, kwargs)),
    )

    result = mind.chat("Yes, do it.", turn=active_turn)

    assert result["confirmation"]["outcome"] == "no-pending"
    assert result["confirmation"]["candidate_ids"] == []
    assert result["confirmation"]["approved"] is False
    assert transitions == []


def test_cancelled_confirmation_performs_no_ledger_work(monkeypatch):
    active_turn = _turn("guest-cancelled")

    def generate(*_args, **_kwargs):
        active_turn.cancel("test cancellation")
        return "I'll do it."

    mind, mind_mod = _core_mind(monkeypatch, generate)
    ledger_calls = []
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "list_commitments",
        lambda **_kwargs: ledger_calls.append("list"),
    )
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "transition_commitment",
        lambda *args, **kwargs: ledger_calls.append("transition"),
    )

    result = mind.chat("Yes, do it.", turn=active_turn)

    assert result["cancelled"] is True
    assert result["turn"]["commit_state"] == "cancelled"
    assert ledger_calls == []


def test_implicit_direct_confirmation_is_not_authenticated(monkeypatch):
    mind, mind_mod = _core_mind(
        monkeypatch,
        lambda *_args, **_kwargs: "I need an authenticated turn to approve that.",
    )
    ledger_calls = []
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "list_commitments",
        lambda **_kwargs: ledger_calls.append("list"),
    )
    monkeypatch.setattr(
        mind_mod.commitments_mod,
        "transition_commitment",
        lambda *args, **kwargs: ledger_calls.append("transition"),
    )

    result = mind.chat("Yes, do it.")

    assert result["confirmation"]["authenticated"] is False
    assert result["confirmation"]["outcome"] == "unauthenticated"
    assert result["confirmation"]["approved"] is False
    assert ledger_calls == []


def test_successful_receipt_preserves_completion_language():
    from alpecca import mind as mind_mod

    state = mind_mod.commitment_language_mod.CommitmentReceiptState(
        status="succeeded",
        receipt_status="succeeded",
        receipt_id="receipt-42",
        action="terminal update",
    )

    result = mind_mod.CoreMind._phase4_enforce_commitment_language(
        "Done. I updated the terminal configuration.", state,
    )

    assert result.rewritten is False
    assert result.reply == "Done. I updated the terminal configuration."
