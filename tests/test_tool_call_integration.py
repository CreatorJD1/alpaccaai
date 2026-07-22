"""Integration coverage for Qwen text/native tool calls in the Ollama loop."""

from alpecca.mind import _LLM


class _FakeOllama:
    def __init__(self, messages):
        self.messages = list(messages)
        self.index = 0

    def chat(self, **_kwargs):
        message = self.messages[min(self.index, len(self.messages) - 1)]
        self.index += 1
        return {"message": message}


def _llm(messages) -> _LLM:
    llm = _LLM()
    llm._backend = "ollama"
    llm._client = _FakeOllama(messages)
    return llm


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
