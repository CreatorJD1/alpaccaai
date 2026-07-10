from alpecca import mindpage


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
