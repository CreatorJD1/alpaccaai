import json

import pytest

from alpecca.tool_call_parser import (
    MAX_ARGUMENT_CHARS,
    MAX_ARGUMENT_DEPTH,
    MAX_CONTENT_CHARS,
    MAX_NAME_CHARS,
    MAX_TOOL_CALLS,
    ToolCall,
    ToolCallError,
    ToolCallSource,
    parse_tool_calls,
)


def test_native_ollama_call_is_normalized_to_typed_result():
    result = parse_tool_calls({
        "content": "",
        "tool_calls": [{
            "id": "call-1",
            "type": "function",
            "function": {"name": "open_app", "arguments": {"name": "notes"}},
        }],
    })

    assert result.ok
    assert result.source is ToolCallSource.NATIVE
    assert result.calls == (ToolCall("open_app", {"name": "notes"}, "call-1"),)


def test_native_arguments_may_be_a_json_string():
    result = parse_tool_calls({
        "tool_calls": [{"function": {"name": "search", "arguments": '{"query":"x"}'}}]
    })

    assert result.calls[0].arguments == {"query": "x"}


def test_present_empty_native_calls_are_authoritative_over_text():
    result = parse_tool_calls({
        "tool_calls": [],
        "content": '<tool_call>{"name":"unsafe","arguments":{}}</tool_call>',
    })

    assert result.ok and result.calls == ()
    assert result.source is ToolCallSource.NATIVE


@pytest.mark.parametrize(
    ("content", "source", "names"),
    [
        ('{"name":"status","arguments":{}}', ToolCallSource.JSON, ["status"]),
        ('[{"name":"one","arguments":{}},{"name":"two","arguments":{"x":1}}]', ToolCallSource.JSON, ["one", "two"]),
        ('{"tool_calls":[{"name":"status","arguments":{}}]}', ToolCallSource.JSON, ["status"]),
        ('```json\n{"name":"status","arguments":{}}\n```', ToolCallSource.JSON, ["status"]),
        ('<tool_call>\n{"name":"one","arguments":{}}\n</tool_call>', ToolCallSource.WRAPPED, ["one"]),
        ('<tool_call>{"name":"one","arguments":{}}</tool_call>\n<tool_call>{"name":"two","arguments":{}}</tool_call>', ToolCallSource.WRAPPED, ["one", "two"]),
        ('Action: status\nAction Input: {}', ToolCallSource.LABELED, ["status"]),
        ('Function: search\nArguments: {"query":"local"}', ToolCallSource.LABELED, ["search"]),
    ],
)
def test_qwen_compatible_text_matrix(content, source, names):
    result = parse_tool_calls({"content": content})

    assert result.ok
    assert result.source is source
    assert [call.name for call in result.calls] == names


@pytest.mark.parametrize(
    "think",
    [
        "<think>choose the correct function</think>",
        "  <THINK>private\nreasoning</THINK>\n",
        "<think>first</think><think>second</think>",
    ],
)
def test_leading_think_wrappers_are_ignored(think):
    result = parse_tool_calls({
        "content": think + '<tool_call>{"name":"status","arguments":{}}</tool_call>'
    })

    assert result.ok and result.calls[0].name == "status"


def test_ordinary_text_and_think_only_text_have_no_calls():
    assert parse_tool_calls({"content": "I can help with that."}).calls == ()
    assert parse_tool_calls({"content": "<think>considering</think>"}).calls == ()


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"tool_calls": {}}, ToolCallError.MALFORMED_PAYLOAD),
        ({"tool_calls": [None]}, ToolCallError.MALFORMED_PAYLOAD),
        ({"tool_calls": [{"type": "custom", "function": {"name": "x", "arguments": {}}}]}, ToolCallError.MALFORMED_PAYLOAD),
        ({"tool_calls": [{"function": {"name": "x"}}]}, ToolCallError.MALFORMED_PAYLOAD),
        ({"tool_calls": [{"function": {"name": "x", "arguments": [], "extra": True}}]}, ToolCallError.EXTRA_PAYLOAD),
        ({"tool_calls": [{"function": {"name": "x", "arguments": {}}, "extra": True}]}, ToolCallError.EXTRA_PAYLOAD),
        ({"content": '{"name":"x","arguments":{},"extra":true}'}, ToolCallError.EXTRA_PAYLOAD),
        ({"content": '{"name":"x","arguments":{}} trailing'}, ToolCallError.MALFORMED_PAYLOAD),
        ({"content": '<tool_call>{"name":"x","arguments":{}}</tool_call> trailing'}, ToolCallError.EXTRA_PAYLOAD),
        ({"content": 'I will call it. <tool_call>{"name":"x","arguments":{}}</tool_call>'}, ToolCallError.EXTRA_PAYLOAD),
        ({"content": '```json\n{"name":"x","arguments":{}}\n``` trailing'}, ToolCallError.EXTRA_PAYLOAD),
        ({"content": 'Action: x\nArguments: {}\nexplanation'}, ToolCallError.MALFORMED_PAYLOAD),
        ({"content": "<think>unclosed"}, ToolCallError.MALFORMED_PAYLOAD),
    ],
)
def test_malformed_or_extra_payloads_fail_closed(payload, error):
    result = parse_tool_calls(payload)

    assert not result.ok
    assert result.calls == ()
    assert result.error is error


@pytest.mark.parametrize("name", ["", "has space", "dot.name", "9starts_wrong", "x" * (MAX_NAME_CHARS + 1)])
def test_invalid_names_are_rejected(name):
    result = parse_tool_calls({"content": json.dumps({"name": name, "arguments": {}})})

    assert result.error is ToolCallError.INVALID_NAME


@pytest.mark.parametrize("arguments", [None, [], "plain text", 3, True])
def test_arguments_must_decode_to_an_object(arguments):
    result = parse_tool_calls({"tool_calls": [{"function": {"name": "x", "arguments": arguments}}]})

    assert result.error is ToolCallError.INVALID_ARGUMENTS


def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected():
    duplicate = parse_tool_calls({"content": '{"name":"x","name":"y","arguments":{}}'})
    nonfinite = parse_tool_calls({"content": '{"name":"x","arguments":{"n":NaN}}'})

    assert duplicate.error is ToolCallError.MALFORMED_PAYLOAD
    assert nonfinite.error is ToolCallError.MALFORMED_PAYLOAD


def test_a_bad_call_rejects_the_entire_batch():
    result = parse_tool_calls({"content": json.dumps([
        {"name": "valid", "arguments": {}},
        {"name": "not valid", "arguments": {}},
    ])})

    assert result.calls == ()
    assert result.error is ToolCallError.INVALID_NAME


def test_hard_caps_reject_oversized_content_call_batches_and_arguments():
    content = parse_tool_calls({"content": "x" * (MAX_CONTENT_CHARS + 1)})
    batch = parse_tool_calls({
        "tool_calls": [
            {"function": {"name": f"t{i}", "arguments": {}}}
            for i in range(MAX_TOOL_CALLS + 1)
        ]
    })
    arguments = parse_tool_calls({
        "tool_calls": [{
            "function": {
                "name": "x",
                "arguments": {"value": "x" * (MAX_ARGUMENT_CHARS + 1)},
            }
        }]
    })

    assert content.error is ToolCallError.INPUT_TOO_LARGE
    assert batch.error is ToolCallError.TOO_MANY_CALLS
    assert arguments.error is ToolCallError.ARGUMENTS_TOO_LARGE


def test_argument_depth_is_bounded_without_recursion():
    value = None
    for _ in range(MAX_ARGUMENT_DEPTH + 1):
        value = {"child": value}

    result = parse_tool_calls({
        "tool_calls": [{"function": {"name": "x", "arguments": value}}]
    })

    assert result.error is ToolCallError.ARGUMENTS_TOO_DEEP


def test_native_call_id_is_validated_and_preserved_only_when_safe():
    invalid = parse_tool_calls({
        "tool_calls": [{
            "id": "bad\nidentifier",
            "function": {"name": "x", "arguments": {}},
        }]
    })

    assert invalid.error is ToolCallError.INVALID_CALL_ID


def test_result_is_deterministic_and_does_not_alias_native_arguments():
    arguments = {"nested": {"value": 1}}
    message = {"tool_calls": [{"function": {"name": "x", "arguments": arguments}}]}
    first = parse_tool_calls(message)
    second = parse_tool_calls(message)
    arguments["new"] = True
    arguments["nested"]["value"] = 2

    assert first == second
    assert "new" not in first.calls[0].arguments
    assert first.calls[0].arguments["nested"]["value"] == 1


def test_non_mapping_message_and_non_string_content_fail_closed():
    assert parse_tool_calls([]).error is ToolCallError.MALFORMED_PAYLOAD
    assert parse_tool_calls({"content": 42}).error is ToolCallError.MALFORMED_PAYLOAD
