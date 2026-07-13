"""Phase 6 contract: every tool-result follow-up round is budgeted.

The first model request is budgeted before it is sent, but a tool-calling turn
appends the model's tool calls and the tool outputs to the running message
array and resends it. Each of those follow-up rounds must be re-measured
against the exact resent request: the oldest evictable turns are dropped to fit,
while the system scaffolding, the current user message, and this round's tool
results are protected. When even the protected minimum cannot fit, the round is
refused honestly instead of silently truncating a tool result.
"""
from __future__ import annotations

from alpecca import mindpage


def _msg(role: str, content: str, **extra) -> dict:
    message = {"role": role, "content": content}
    message.update(extra)
    return message


def test_first_round_within_budget_is_untouched():
    messages = [
        _msg("system", "system scaffolding"),
        _msg("user", "please open my notes"),
        _msg("assistant", "", tool_calls=[{"function": {"name": "open", "arguments": {}}}]),
        _msg("tool", "notes opened"),
    ]
    kept, snapshot = mindpage.fit_tool_round(messages, num_ctx=8192)
    assert kept == messages
    assert snapshot["context_fits"] is True
    assert snapshot["dropped_history_messages"] == 0
    assert snapshot["source"] == "estimated_tool_round"


def test_overflow_is_resolved_by_evicting_oldest_history():
    system = _msg("system", "S" * 200)
    # Several older turns that CAN be evicted.
    old = []
    for i in range(6):
        old.append(_msg("user", f"old question {i} " * 30))
        old.append(_msg("assistant", f"old answer {i} " * 30))
    user = _msg("user", "current question that must survive")
    call = _msg("assistant", "", tool_calls=[{"function": {"name": "x", "arguments": {}}}])
    tool = _msg("tool", "tool result the model still needs " * 20)
    messages = [system, *old, user, call, tool]

    kept, snapshot = mindpage.fit_tool_round(
        messages, num_ctx=1024, output_reserve=128, protocol_reserve=64
    )

    assert snapshot["context_fits"] is True
    assert snapshot["fit_status"] == "fit"
    assert snapshot["dropped_history_messages"] > 0
    # Protected content survives.
    assert kept[0]["role"] == "system"
    assert any(m.get("content") == "current question that must survive" for m in kept)
    assert any(m["role"] == "tool" for m in kept)
    # The oldest turn was the first evicted.
    assert old[0] not in kept


def test_protected_minimum_overflow_refuses_honestly():
    system = _msg("system", "S" * 200)
    user = _msg("user", "current question")
    call = _msg("assistant", "", tool_calls=[{"function": {"name": "x", "arguments": {}}}])
    # A single enormous tool result that alone blows the window.
    tool = _msg("tool", "R" * 60000)
    messages = [system, user, call, tool]

    kept, snapshot = mindpage.fit_tool_round(messages, num_ctx=1024)

    assert snapshot["context_fits"] is False
    assert snapshot["fixed_overflow"] is True
    assert snapshot["fit_status"] == "fixed_overflow"
    # It never silently drops the tool result the model still depends on.
    assert any(m["role"] == "tool" for m in kept)
    assert any(m.get("content") == "current question" for m in kept)


def test_each_round_is_budgeted_independently_as_results_accumulate():
    system = _msg("system", "S" * 200)
    user = _msg("user", "current question")
    messages = [system, user]
    num_ctx = 2048
    fit_count = 0
    # Simulate a bounded multi-round tool loop appending results each round.
    for round_index in range(5):
        call = _msg(
            "assistant", "",
            tool_calls=[{"function": {"name": f"t{round_index}", "arguments": {}}}],
        )
        result = _msg("tool", f"round {round_index} result " * 40)
        messages.append(call)
        messages.append(result)
        messages, snapshot = mindpage.fit_tool_round(messages, num_ctx=num_ctx)
        fit_count += 1
        # Every round produces a fresh measurement, never stale.
        assert snapshot["source"] == "estimated_tool_round"
        assert snapshot["num_ctx"] == num_ctx
        # The estimate never exceeds the window once fitted.
        assert snapshot["total_tokens"] <= num_ctx
    assert fit_count == 5
    # The protected user message is still present after five rounds.
    assert any(m.get("content") == "current question" for m in messages)


def test_tool_schema_tokens_are_counted_against_the_window():
    system = _msg("system", "S" * 100)
    user = _msg("user", "current question")
    call = _msg("assistant", "", tool_calls=[{"function": {"name": "x", "arguments": {}}}])
    tool = _msg("tool", "small result")
    messages = [system, user, call, tool]
    big_tools = [
        {"type": "function", "function": {"name": f"tool_{i}", "description": "d" * 400,
                                          "parameters": {"type": "object"}}}
        for i in range(20)
    ]

    _, without = mindpage.fit_tool_round(messages, tools=None, num_ctx=8192)
    _, with_tools = mindpage.fit_tool_round(messages, tools=big_tools, num_ctx=8192)

    assert with_tools["breakdown"]["tools"] > 0
    assert with_tools["total_tokens"] > without["total_tokens"]


def test_system_block_is_never_evicted():
    system_a = _msg("system", "S" * 300)
    system_b = _msg("system", "grounding block " * 30)
    old = [_msg("user", "old " * 50), _msg("assistant", "reply " * 50)]
    user = _msg("user", "current question")
    tool = _msg("tool", "result " * 30)
    messages = [system_a, system_b, *old, user, tool]

    kept, snapshot = mindpage.fit_tool_round(
        messages, num_ctx=768, output_reserve=64, protocol_reserve=64
    )

    # Both leading system messages must remain even under eviction pressure.
    assert kept[0] is system_a
    assert kept[1] is system_b
