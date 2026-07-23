"""Integration coverage for Qwen text/native tool calls in the Ollama loop."""

import pytest

from alpecca.mind import _LLM
from alpecca.tool_call_parser import MAX_TOOL_CALLS


class _FakeOllama:
    def __init__(self, messages):
        self.messages = list(messages)
        self.index = 0

    def chat(self, **_kwargs):
        message = self.messages[min(self.index, len(self.messages) - 1)]
        self.index += 1
        return {"message": message}


class _HFMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self):
        result = {"content": self.content}
        if self.tool_calls is not None:
            result["tool_calls"] = self.tool_calls
        return result


class _FakeHF:
    def __init__(self, messages):
        self.messages = list(messages)
        self.index = 0

    def chat_completion(self, **_kwargs):
        message = self.messages[min(self.index, len(self.messages) - 1)]
        self.index += 1
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


def _llm(messages) -> _LLM:
    llm = _LLM()
    llm._backend = "ollama"
    llm._client = _FakeOllama(messages)
    return llm


def _hf_llm(messages) -> _LLM:
    llm = _LLM()
    llm._backend = "hf"
    llm._hf = _FakeHF(messages)
    return llm


def _tool_call(name="memory_search", arguments=None, call_id="call-1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": {"query": "hoodie"} if arguments is None else arguments,
        },
    }


_MEMORY_TOOL = [{
    "type": "function",
    "function": {"name": "memory_search"},
}]


def test_qwen_text_tool_call_executes_then_returns_words():
    llm = _llm([
        {
            "content": (
                '<think>use the allowed tool</think>'
                '<tool_call>{"name":"memory_search",'
                '"arguments":{"query":"hoodie"}}</tool_call>'
            )
        },
        {"content": "I found the hoodie memory.", "tool_calls": []},
    ])
    calls = []

    result = llm.generate(
        "system",
        "Find the hoodie memory.",
        tools=[{"type": "function", "function": {"name": "memory_search"}}],
        on_tool=lambda name, args: calls.append((name, args)) or "found",
    )

    assert calls == [("memory_search", {"query": "hoodie"})]
    assert result == "I found the hoodie memory."


def test_malformed_native_call_fails_closed_without_text_rescue():
    llm = _llm([{
        "content": '<tool_call>{"name":"unsafe","arguments":{}}</tool_call>',
        "tool_calls": [{"function": {"name": "unsafe"}}],
    }])
    calls = []

    result = llm.generate(
        "system",
        "Do it.",
        tools=[{"type": "function", "function": {"name": "unsafe"}}],
        on_tool=lambda name, args: calls.append((name, args)) or "ran",
    )

    assert calls == []
    assert "did not run it" in result


def test_hf_valid_tool_call_executes_then_returns_words():
    llm = _hf_llm([
        _HFMessage(tool_calls=[_tool_call()]),
        _HFMessage(content="I found the hoodie memory.", tool_calls=[]),
    ])
    calls = []

    result = llm.generate(
        "system",
        "Find the hoodie memory.",
        tools=_MEMORY_TOOL,
        on_tool=lambda name, args: calls.append((name, args)) or "found",
    )

    assert calls == [("memory_search", {"query": "hoodie"})]
    assert result == "I found the hoodie memory."


@pytest.mark.parametrize("arguments", ["{", "[]", [], "plain text"])
def test_hf_malformed_or_non_object_arguments_fail_closed(arguments):
    llm = _hf_llm([_HFMessage(tool_calls=[_tool_call(arguments=arguments)])])
    calls = []

    result = llm.generate(
        "system",
        "Run it.",
        tools=_MEMORY_TOOL,
        on_tool=lambda name, args: calls.append((name, args)) or "ran",
    )

    assert calls == []
    assert "did not run it" in result


def test_hf_provider_tool_call_batch_is_hard_capped():
    provider_calls = [
        _tool_call(call_id=f"call-{index}")
        for index in range(MAX_TOOL_CALLS + 1)
    ]
    llm = _hf_llm([_HFMessage(tool_calls=provider_calls)])
    calls = []

    result = llm.generate(
        "system",
        "Run all calls.",
        tools=_MEMORY_TOOL,
        on_tool=lambda name, args: calls.append((name, args)) or "ran",
    )

    assert calls == []
    assert "did not run it" in result


def test_hf_valid_then_overlimit_chain_reports_partial_execution_honestly():
    over_limit_round = [
        _tool_call(call_id=f"over-{index}")
        for index in range(MAX_TOOL_CALLS)
    ]
    llm = _hf_llm([
        _HFMessage(tool_calls=[_tool_call(call_id="first-valid")]),
        _HFMessage(tool_calls=over_limit_round),
    ])
    calls = []

    result = llm.generate(
        "system",
        "Keep calling the tool.",
        tools=_MEMORY_TOOL,
        on_tool=lambda name, args: calls.append((name, args)) or "ran",
    )

    assert calls == [("memory_search", {"query": "hoodie"})]
    assert "1 verified tool step ran (memory_search)" in result
    assert "(over-limit)" in result
    assert "did not run it" not in result


@pytest.mark.parametrize(
    ("invalid_call", "expected_reason"),
    [
        (_tool_call(arguments="{", call_id="malformed"), "malformed"),
        (
            _tool_call(name="unknown_tool", arguments={}, call_id="unknown"),
            "unknown or unoffered",
        ),
    ],
)
def test_hf_valid_then_invalid_chain_reports_partial_execution_honestly(
    invalid_call,
    expected_reason,
):
    llm = _hf_llm([
        _HFMessage(tool_calls=[_tool_call(call_id="first-valid")]),
        _HFMessage(tool_calls=[invalid_call]),
    ])
    calls = []

    result = llm.generate(
        "system",
        "Run one valid call, then reject the invalid request.",
        tools=_MEMORY_TOOL,
        on_tool=lambda name, args: calls.append((name, args)) or "receipt-1",
    )

    assert calls == [("memory_search", {"query": "hoodie"})]
    assert "1 verified tool step ran (memory_search)" in result
    assert f"({expected_reason})" in result
    assert "did not run it" not in result


def test_hf_unknown_tool_rejects_entire_batch_without_execution():
    llm = _hf_llm([_HFMessage(tool_calls=[
        _tool_call(),
        _tool_call(name="unknown_tool", arguments={}, call_id="call-2"),
    ])])
    calls = []

    result = llm.generate(
        "system",
        "Run both calls.",
        tools=_MEMORY_TOOL,
        on_tool=lambda name, args: calls.append((name, args)) or "ran",
    )

    assert calls == []
    assert "did not run it" in result
