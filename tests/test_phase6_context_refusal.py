from types import SimpleNamespace

from alpecca import mind as mind_mod
from alpecca import mindpage
from alpecca import turn_context as turn_context_mod


def _outcome(snapshot: dict) -> dict:
    """Exclude telemetry time while comparing the context-fit decision."""
    keys = (
        "num_ctx",
        "input_budget_tokens",
        "input_tokens",
        "total_tokens",
        "estimated_tokens_before_hard_limit",
        "required_context_tokens",
        "minimum_required_tokens",
        "overflow_tokens",
        "fixed_overflow_tokens",
        "context_fits",
        "fit_status",
        "overflow",
        "fixed_overflow",
        "unshrinkable",
        "breakdown",
    )
    return {key: snapshot[key] for key in keys}


def test_fit_request_reports_deterministic_fixed_overflow_without_false_fit():
    history = [
        {"role": "user", "content": "old question" * 8},
        {"role": "assistant", "content": "old answer" * 8},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "large_tool",
                "description": "bounded tool schema " * 24,
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    kwargs = {
        "system_prompt": "fixed system scaffold " * 20,
        "user_message": "current user input " * 20,
        "history": history,
        "tools": tools,
        "num_ctx": 64,
        "output_reserve": 8,
        "protocol_reserve": 4,
    }

    selected, first = mindpage.fit_request(**kwargs)
    selected_again, second = mindpage.fit_request(**kwargs)

    assert selected == selected_again == []
    assert first["total_tokens"] == first["num_ctx"] == 64
    assert first["context_fits"] is False
    assert first["fit_status"] == "fixed_overflow"
    assert first["overflow"] is True
    assert first["fixed_overflow"] is True
    assert first["unshrinkable"] is True
    assert first["required_context_tokens"] == first["estimated_tokens_before_hard_limit"]
    assert first["required_context_tokens"] > first["num_ctx"]
    assert first["minimum_required_tokens"] > first["num_ctx"]
    assert first["input_tokens"] > first["input_budget_tokens"]
    assert first["overflow_tokens"] == first["required_context_tokens"] - first["num_ctx"]
    assert first["fixed_overflow_tokens"] == (
        first["minimum_required_tokens"] - first["num_ctx"]
    )
    assert first["breakdown"]["history"] == 0
    assert _outcome(first) == _outcome(second)


def test_fit_context_keeps_memory_history_musing_shrink_priority():
    history = [
        {"role": "user", "content": "u" * 20},
        {"role": "assistant", "content": "a" * 20},
    ]
    memories = ["m" * 40, "n" * 40]
    musings = ["i" * 40]

    memory_only = mindpage.fit_context(
        fixed_texts=["f" * 40],
        memories=memories,
        history=history,
        musings=musings,
        num_ctx=45,
        output_reserve=0,
        protocol_reserve=0,
    )
    through_history = mindpage.fit_context(
        fixed_texts=["f" * 40],
        memories=memories,
        history=history,
        musings=musings,
        num_ctx=25,
        output_reserve=0,
        protocol_reserve=0,
    )

    assert memory_only["memories"] == ["m" * 40]
    assert memory_only["history"] == history
    assert memory_only["musings"] == musings
    assert memory_only["snapshot"]["fit_status"] == "fit"
    assert memory_only["snapshot"]["context_fits"] is True

    assert through_history["memories"] == []
    assert through_history["history"] == []
    assert through_history["musings"] == musings
    assert through_history["snapshot"]["dropped_memory_items"] == 2
    assert through_history["snapshot"]["dropped_history_messages"] == 2
    assert through_history["snapshot"]["dropped_musing_items"] == 0
    assert through_history["snapshot"]["fit_status"] == "fit"


def test_fit_context_drops_every_optional_component_before_fixed_refusal():
    history = [
        {"role": "user", "content": "past" * 20},
        {"role": "assistant", "content": "reply" * 20},
    ]
    fitted = mindpage.fit_context(
        fixed_texts=["system scaffold " * 20, "current input " * 20],
        memories=["memory " * 20],
        history=history,
        musings=["musing " * 20],
        tools=[{"type": "function", "function": {"name": "status", "description": "x" * 80}}],
        num_ctx=48,
        output_reserve=8,
        protocol_reserve=4,
    )
    snapshot = fitted["snapshot"]

    assert fitted["memories"] == []
    assert fitted["history"] == []
    assert fitted["musings"] == []
    assert snapshot["breakdown"]["memories"] == 0
    assert snapshot["breakdown"]["history"] == 0
    assert snapshot["breakdown"]["musings"] == 0
    assert snapshot["fit_status"] == "fixed_overflow"
    assert snapshot["context_fits"] is False
    assert snapshot["fixed_overflow"] is True
    assert snapshot["unshrinkable"] is True
    assert snapshot["minimum_required_tokens"] == snapshot["required_context_tokens"]
    assert snapshot["fixed_overflow_tokens"] > 0


def _ledger(*, fits: bool, num_ctx: int = 128) -> dict:
    """Create a complete measured ledger without depending on runtime defaults."""
    _, ledger = mindpage.fit_request(
        "test system scaffold",
        "test user message",
        [],
        num_ctx=num_ctx,
        output_reserve=16,
        protocol_reserve=4,
    )
    if fits:
        return ledger

    required = num_ctx + 37
    ledger.update({
        "num_ctx": num_ctx,
        "input_budget_tokens": num_ctx - 20,
        "input_tokens": num_ctx + 17,
        "total_tokens": num_ctx,
        "estimated_tokens_before_hard_limit": required,
        "required_context_tokens": required,
        "minimum_required_tokens": required,
        "overflow_tokens": required - num_ctx,
        "fixed_overflow_tokens": required - num_ctx,
        "context_fits": False,
        "fit_status": "fixed_overflow",
        "overflow": True,
        "fixed_overflow": True,
        "unshrinkable": True,
        "context_fill": 1.0,
        "pressure_score": 1.0,
        "pressure": "high",
    })
    return ledger


def _chat_harness(monkeypatch, fit_plan, *, tool_schema=None, replies=("normal reply",),
                  on_fit=None):
    """Isolate chat control flow while keeping CoreMind's public contract live."""
    mind = mind_mod.CoreMind()
    component_ledger = _ledger(fits=True)
    initial_history = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
    ]
    mind._history = [dict(item) for item in initial_history]
    mind.llm._client = object()
    calls = {
        "fit": [],
        "generations": [],
        "tool_executions": [],
        "streamed": [],
        "memory_writes": [],
        "state_writes": [],
        "commitments": [],
        "observations": [],
        "chat_turns": [],
        "history_saves": [],
        "reply_notes": [],
        "initial_history": [dict(item) for item in initial_history],
    }

    def fake_fit_context(*, history, **_kwargs):
        return {
            "memories": [],
            "history": [dict(item) for item in history],
            "musings": [],
            "dropped_history": [],
            "snapshot": dict(component_ledger),
        }

    def fake_fit_request(system_prompt, user_message, history, tools=None, **_kwargs):
        index = len(calls["fit"])
        if index >= len(fit_plan):
            raise AssertionError("unexpected context fit measurement")
        record = {
            "system_prompt": system_prompt,
            "user_message": user_message,
            "history": [dict(item) for item in history],
            "tools": tools,
        }
        calls["fit"].append(record)
        if on_fit is not None:
            on_fit(index, record)
        selected_history, ledger = fit_plan[index]
        return [dict(item) for item in selected_history], dict(ledger)

    def fake_generate(system_prompt, user_message, history=None, tools=None,
                      on_tool=None, tier="reason", on_token=None, **_kwargs):
        calls["generations"].append({
            "system_prompt": system_prompt,
            "user_message": user_message,
            "history": [dict(item) for item in history or []],
            "tools": tools,
            "tier": tier,
        })
        if on_token is not None:
            on_token("unexpected streamed draft")
        if on_tool is not None:
            on_tool("test_tool", {})
        reply_index = min(len(calls["generations"]) - 1, len(replies) - 1)
        return replies[reply_index]

    def fake_pressure_snapshot(history=None, db_path=None, ledger=None):
        snapshot = dict(ledger or component_ledger)
        snapshot.setdefault("page_count", 0)
        snapshot.setdefault("hot_page_count", 0)
        snapshot.setdefault("hot_page_tokens", 0)
        snapshot.setdefault("page_payload_bytes", 0)
        snapshot.setdefault("disk_fill", 0.0)
        snapshot.setdefault("disk_over_budget", False)
        return snapshot

    monkeypatch.setattr(mind_mod.mindpage_mod, "fit_context", fake_fit_context)
    monkeypatch.setattr(mind_mod.mindpage_mod, "fit_request", fake_fit_request)
    monkeypatch.setattr(mind_mod.mindpage_mod, "pressure_snapshot", fake_pressure_snapshot)
    monkeypatch.setattr(mind_mod.memory_store, "recall", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.memory_store, "recent", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.memory_store, "remember_with_id",
                        lambda *args, **kwargs: calls["memory_writes"].append((args, kwargs)) or 17)
    monkeypatch.setattr(mind_mod.journal_mod, "open_questions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(mind_mod.people_mod, "who_prompt", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mind_mod.core_mem, "prompt_block", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(mind_mod.core_mem, "remember", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.state_store, "save_state",
                        lambda *args, **kwargs: calls["state_writes"].append((args, kwargs)))
    monkeypatch.setattr(mind_mod.state_store, "save_location", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "set_intent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "record_observation",
                        lambda observation: calls["observations"].append(observation) or 11)
    monkeypatch.setattr(mind_mod.cognition_mod, "mark_observation_remembered",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mind_mod.cognition_mod, "record_chat_turn",
                        lambda turn: calls["chat_turns"].append(turn) or 21)
    monkeypatch.setattr(mind_mod.cognition_mod, "current_intent", lambda: {"state": "waiting"})
    monkeypatch.setattr(mind_mod.commitments_mod, "create_commitment",
                        lambda *args, **kwargs: calls["commitments"].append((args, kwargs)) or {
                            "id": 1, "state": "proposed", "scope": kwargs.get("scope", ""),
                            "action": args[0] if args else "",
                        })
    monkeypatch.setattr(mind_mod.turn_context_mod, "load_history", lambda _turn: [])
    monkeypatch.setattr(mind_mod.turn_context_mod, "save_history",
                        lambda turn, history: calls["history_saves"].append((turn, list(history))))
    monkeypatch.setattr(mind_mod.speech_mod, "spoken_performance_text", lambda reply, _state: reply)
    monkeypatch.setattr(mind_mod.speech_mod, "speech_cues", lambda _state: {})
    monkeypatch.setattr(mind, "introspect",
                        lambda: SimpleNamespace(
                            narrate=lambda **_kwargs: "test self-report"
                        ))
    monkeypatch.setattr(mind, "current_appearance",
                        lambda: SimpleNamespace(as_dict=lambda: {}))
    monkeypatch.setattr(mind, "_phase5_affect_metadata", lambda *_args, **_kwargs: {
        "eligible": False,
        "state_changed": False,
        "strategy_changed": False,
        "reason": "test",
        "operational_states": [],
        "response_strategy": "",
        "events": [],
        "ignored_kinds": [],
        "provenance": {},
    })
    monkeypatch.setattr(mind, "_phase6_pressure_bundle", lambda: {
        "metadata": {"available": True, "source": "test"},
    })
    monkeypatch.setattr(mind, "_house_context_room", lambda _situation: ("", ""))
    monkeypatch.setattr(mind, "_prompt_situation", lambda situation: situation)
    monkeypatch.setattr(mind, "_tool_schema", lambda *_args, **_kwargs: tool_schema)
    monkeypatch.setattr(mind, "_execute_turn_tool",
                        lambda *args, **_kwargs: calls["tool_executions"].append(args) or "tool result")
    monkeypatch.setattr(mind, "try_go_to_room", lambda _message: None)
    monkeypatch.setattr(mind, "_note_reply",
                        lambda reply: calls["reply_notes"].append(reply))
    monkeypatch.setattr(mind.llm, "generate", fake_generate)
    monkeypatch.setattr(mind.llm, "last_call", lambda: {
        "requested_tier": "reason",
        "used_tier": "reason",
        "backend": "test",
        "model": "test-model",
        "ok": True,
        "fallback": False,
        "error": "",
    })
    return mind, calls


def test_chat_fixed_overflow_refuses_before_model_stream_or_persistence(monkeypatch):
    overflow = _ledger(fits=False)
    mind, calls = _chat_harness(monkeypatch, [([], overflow), ([], overflow)])
    streamed = []

    result = mind.chat("do not persist this oversized request", on_token=streamed.append)

    assert calls["generations"] == []
    assert calls["tool_executions"] == []
    assert streamed == []
    assert mind._history == calls["initial_history"]
    assert calls["memory_writes"] == []
    assert calls["state_writes"] == []
    assert calls["commitments"] == []
    assert calls["reply_notes"] == []
    assert calls["chat_turns"] == []
    assert calls["observations"] == []
    assert result["context_refusal"] == {
        "reason": "fixed_overflow",
        "overflow_tokens": overflow["overflow_tokens"],
        "num_ctx": overflow["num_ctx"],
    }
    assert result["model_use"]["backend"] == "context_refusal"
    assert "did not send" in result["reply"].lower()
    assert result["mindpage"]["fit_status"] == "fixed_overflow"


def test_chat_fixed_overflow_never_dispatches_an_offered_tool(monkeypatch):
    overflow = _ledger(fits=False)
    tool_schema = [{
        "type": "function",
        "function": {
            "name": "test_tool",
            "description": "test-only tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }]
    mind, calls = _chat_harness(
        monkeypatch,
        [([], overflow), ([], overflow)],
        tool_schema=tool_schema,
    )

    result = mind.chat("please use the test tool")

    assert calls["generations"] == []
    assert calls["tool_executions"] == []
    assert result["context_refusal"]["reason"] == "fixed_overflow"


def test_cancelled_overflow_turn_cannot_commit_an_observation_or_reply(monkeypatch):
    overflow = _ledger(fits=False)
    turn = turn_context_mod.TurnContext.create(
        "phase6c-cancel", principal="creator", surface="test",
    )

    def cancel_after_final_measurement(index, _record):
        if index == 1:
            turn.cancel("test cancellation")

    mind, calls = _chat_harness(
        monkeypatch,
        [([], overflow), ([], overflow)],
        on_fit=cancel_after_final_measurement,
    )

    result = mind.chat("cancel this oversized turn", turn=turn)

    assert result["cancelled"] is True
    assert result["reply"] == ""
    assert calls["observations"] == []
    assert calls["chat_turns"] == []
    assert calls["memory_writes"] == []
    assert calls["history_saves"] == []


def test_fitting_chat_keeps_the_existing_result_contract(monkeypatch):
    fitted = _ledger(fits=True)
    mind, calls = _chat_harness(
        monkeypatch,
        [([], fitted), ([], fitted)],
        replies=("A normal fitting reply.",),
    )

    result = mind.chat("short fitting request")

    assert len(calls["generations"]) == 1
    assert result["reply"] == "A normal fitting reply."
    assert result["model_use"]["backend"] == "test"
    assert "context_refusal" not in result
    assert {"mood", "state", "mindpage", "turn", "chat_turn_id"} <= set(result)
    assert mind._history[-2:] == [
        {"role": "user", "content": "short fitting request"},
        {"role": "assistant", "content": "A normal fitting reply."},
    ]
    assert len(calls["memory_writes"]) == 1
    assert len(calls["state_writes"]) == 1


def test_repetition_retry_remeasures_fresh_prompt_and_uses_trimmed_history(monkeypatch):
    fitted = _ledger(fits=True)
    first_trim = [{"role": "assistant", "content": "first trimmed history"}]
    final_trim = [{"role": "assistant", "content": "final trimmed history"}]
    retry_trim = [{"role": "assistant", "content": "retry trimmed history"}]
    mind, calls = _chat_harness(
        monkeypatch,
        [(first_trim, fitted), (final_trim, fitted), (retry_trim, fitted)],
        replies=("first draft", "fresh revision"),
    )
    repeat_flags = iter([True, False])
    monkeypatch.setattr(mind, "_too_repetitive", lambda _reply: next(repeat_flags, False))

    result = mind.chat("please answer without repeating yourself")

    assert len(calls["fit"]) == 3
    assert calls["fit"][1]["history"] == first_trim
    assert "Your draft was too close" in calls["fit"][2]["system_prompt"]
    assert calls["fit"][2]["history"] == final_trim
    assert len(calls["generations"]) == 2
    assert calls["generations"][0]["history"] == final_trim
    assert calls["generations"][1]["history"] == retry_trim
    assert result["reply"] == "fresh revision"


def test_overflowed_repetition_retry_keeps_first_reply_and_records_skip(monkeypatch):
    fitted = _ledger(fits=True)
    overflow = _ledger(fits=False)
    first_trim = [{"role": "assistant", "content": "first trimmed history"}]
    final_trim = [{"role": "assistant", "content": "final trimmed history"}]
    mind, calls = _chat_harness(
        monkeypatch,
        [(first_trim, fitted), (final_trim, fitted), ([], overflow)],
        replies=("first acceptable draft", "should never be generated"),
    )
    repeat_flags = iter([True, False])
    monkeypatch.setattr(mind, "_too_repetitive", lambda _reply: next(repeat_flags, False))

    result = mind.chat("retry only if the measured prompt still fits")

    assert len(calls["fit"]) == 3
    assert "Your draft was too close" in calls["fit"][2]["system_prompt"]
    assert len(calls["generations"]) == 1
    assert result["reply"] == "first acceptable draft"
    assert result["mindpage"]["retry_skipped"] == "fixed_overflow"
