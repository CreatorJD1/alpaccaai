"""Bounded, fail-closed parsing for local model tool calls.

Ollama normally returns structured ``message.tool_calls``.  Qwen-compatible
servers can instead place the same call in the assistant's text.  This module
normalizes those representations without executing anything or guessing at
partially valid output.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import Any


MAX_CONTENT_CHARS = 32_768
MAX_TOOL_CALLS = 8
MAX_NAME_CHARS = 64
MAX_CALL_ID_CHARS = 128
MAX_ARGUMENT_CHARS = 16_384
MAX_ARGUMENT_DEPTH = 12
MAX_ARGUMENT_NODES = 1_024
MAX_ARGUMENT_STRING_CHARS = 8_192
MAX_ARGUMENT_KEY_CHARS = 256

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_LEADING_THINK_RE = re.compile(
    r"\A\s*<think\s*>.*?</think\s*>", re.IGNORECASE | re.DOTALL
)
_TOOL_WRAPPER_RE = re.compile(
    r"\s*<tool_call\s*>(.*?)</tool_call\s*>\s*",
    re.IGNORECASE | re.DOTALL,
)
_FENCE_RE = re.compile(
    r"\A\s*```(?:json|tool_call)?\s*\n?(.*?)\n?```\s*\Z",
    re.IGNORECASE | re.DOTALL,
)
_LABELED_RE = re.compile(
    r"\A\s*(?:Action|Tool|Function)\s*:\s*([^\r\n]+?)\s*\r?\n"
    r"(?:Action Input|Arguments)\s*:\s*(.+?)\s*\Z",
    re.IGNORECASE | re.DOTALL,
)


class ToolCallSource(str, Enum):
    NONE = "none"
    NATIVE = "native"
    JSON = "json"
    WRAPPED = "wrapped"
    LABELED = "labeled"


class ToolCallError(str, Enum):
    INPUT_TOO_LARGE = "input_too_large"
    TOO_MANY_CALLS = "too_many_calls"
    MALFORMED_PAYLOAD = "malformed_payload"
    EXTRA_PAYLOAD = "extra_payload"
    INVALID_NAME = "invalid_name"
    INVALID_ARGUMENTS = "invalid_arguments"
    ARGUMENTS_TOO_LARGE = "arguments_too_large"
    ARGUMENTS_TOO_DEEP = "arguments_too_deep"
    INVALID_CALL_ID = "invalid_call_id"


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A validated call ready to pass to the local tool dispatcher."""

    name: str
    arguments: dict[str, Any]
    call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCallParseResult:
    calls: tuple[ToolCall, ...] = ()
    source: ToolCallSource = ToolCallSource.NONE
    error: ToolCallError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class _ParseFailure(ValueError):
    def __init__(self, code: ToolCallError):
        super().__init__(code.value)
        self.code = code


def parse_tool_calls(message: Mapping[str, Any]) -> ToolCallParseResult:
    """Parse one Ollama-style assistant message into validated tool calls.

    A present ``tool_calls`` field is authoritative, including an empty list.
    Text fallback is considered only when that field is absent.  This prevents
    malformed native output from being rescued by unrelated assistant prose.
    """

    if not isinstance(message, Mapping):
        return _failure(ToolCallSource.NONE, ToolCallError.MALFORMED_PAYLOAD)

    if "tool_calls" in message:
        try:
            calls = _parse_native(message["tool_calls"])
        except _ParseFailure as exc:
            return _failure(ToolCallSource.NATIVE, exc.code)
        return ToolCallParseResult(calls=calls, source=ToolCallSource.NATIVE)

    content = message.get("content", "")
    if content is None or content == "":
        return ToolCallParseResult()
    if not isinstance(content, str):
        return _failure(ToolCallSource.NONE, ToolCallError.MALFORMED_PAYLOAD)
    if len(content) > MAX_CONTENT_CHARS:
        return _failure(ToolCallSource.NONE, ToolCallError.INPUT_TOO_LARGE)

    try:
        text = _strip_leading_think(content)
        if not text:
            return ToolCallParseResult()

        wrapped = _parse_wrapped_calls(text)
        if wrapped is not None:
            return ToolCallParseResult(
                calls=_normalize_specs(wrapped), source=ToolCallSource.WRAPPED
            )

        fence = _FENCE_RE.fullmatch(text)
        if fence:
            specs = _specs_from_json(_load_json(fence.group(1)))
            return ToolCallParseResult(
                calls=_normalize_specs(specs), source=ToolCallSource.JSON
            )

        labeled = _LABELED_RE.fullmatch(text)
        if labeled:
            spec = {"name": labeled.group(1).strip(), "arguments": _load_json(labeled.group(2))}
            return ToolCallParseResult(
                calls=_normalize_specs([spec]), source=ToolCallSource.LABELED
            )

        if text.lstrip().startswith(("{", "[")):
            specs = _specs_from_json(_load_json(text))
            return ToolCallParseResult(
                calls=_normalize_specs(specs), source=ToolCallSource.JSON
            )

        if _looks_like_tool_payload(text):
            raise _ParseFailure(ToolCallError.EXTRA_PAYLOAD)

        # Ordinary assistant prose is not a parser error and contains no calls.
        return ToolCallParseResult()
    except _ParseFailure as exc:
        return _failure(ToolCallSource.NONE, exc.code)


def _failure(source: ToolCallSource, code: ToolCallError) -> ToolCallParseResult:
    return ToolCallParseResult(source=source, error=code)


def _strip_leading_think(content: str) -> str:
    text = content
    while True:
        match = _LEADING_THINK_RE.match(text)
        if not match:
            break
        text = text[match.end():]
    stripped = text.strip()
    if stripped.lower().startswith("<think"):
        raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)
    return stripped


def _parse_wrapped_calls(text: str) -> list[Any] | None:
    if not text.lstrip().lower().startswith("<tool_call"):
        return None
    specs: list[Any] = []
    position = 0
    while position < len(text):
        match = _TOOL_WRAPPER_RE.match(text, position)
        if not match:
            raise _ParseFailure(ToolCallError.EXTRA_PAYLOAD)
        specs.append(_load_json(match.group(1)))
        position = match.end()
    return specs


def _looks_like_tool_payload(text: str) -> bool:
    lowered = text.lower()
    if "<tool_call" in lowered or "</tool_call" in lowered:
        return True
    if re.match(r"\A\s*```(?:json|tool_call)(?:\s|\Z)", text, re.IGNORECASE):
        return True
    return bool(
        re.match(r"\A\s*(?:Action|Tool|Function)\s*:", text, re.IGNORECASE)
    )


def _parse_native(raw_calls: Any) -> tuple[ToolCall, ...]:
    if not isinstance(raw_calls, Sequence) or isinstance(raw_calls, (str, bytes, bytearray)):
        raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)
    if len(raw_calls) > MAX_TOOL_CALLS:
        raise _ParseFailure(ToolCallError.TOO_MANY_CALLS)

    specs: list[dict[str, Any]] = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, Mapping):
            raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)
        if set(raw_call) - {"id", "type", "function"}:
            raise _ParseFailure(ToolCallError.EXTRA_PAYLOAD)
        if raw_call.get("type", "function") != "function":
            raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)
        if set(function) != {"name", "arguments"}:
            code = ToolCallError.EXTRA_PAYLOAD if set(function) - {"name", "arguments"} else ToolCallError.MALFORMED_PAYLOAD
            raise _ParseFailure(code)
        spec = dict(function)
        if "id" in raw_call:
            spec["id"] = raw_call["id"]
        specs.append(spec)
    return _normalize_specs(specs)


def _specs_from_json(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)
    if set(payload) == {"tool_calls"}:
        calls = payload["tool_calls"]
        if not isinstance(calls, list):
            raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)
        return calls
    return [payload]


def _normalize_specs(specs: Sequence[Any]) -> tuple[ToolCall, ...]:
    if len(specs) > MAX_TOOL_CALLS:
        raise _ParseFailure(ToolCallError.TOO_MANY_CALLS)
    calls: list[ToolCall] = []
    for spec in specs:
        if not isinstance(spec, Mapping):
            raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)

        # JSON envelopes may use the native nested function shape.
        if "function" in spec:
            if set(spec) - {"id", "type", "function"}:
                raise _ParseFailure(ToolCallError.EXTRA_PAYLOAD)
            if spec.get("type", "function") != "function":
                raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)
            function = spec["function"]
            if not isinstance(function, Mapping):
                raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)
            if set(function) != {"name", "arguments"}:
                code = ToolCallError.EXTRA_PAYLOAD if set(function) - {"name", "arguments"} else ToolCallError.MALFORMED_PAYLOAD
                raise _ParseFailure(code)
            name, arguments = function["name"], function["arguments"]
            call_id = spec.get("id")
        else:
            if set(spec) - {"id", "name", "arguments"}:
                raise _ParseFailure(ToolCallError.EXTRA_PAYLOAD)
            if "name" not in spec or "arguments" not in spec:
                raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)
            name, arguments = spec["name"], spec["arguments"]
            call_id = spec.get("id")

        valid_name = isinstance(name, str) and 0 < len(name) <= MAX_NAME_CHARS and _NAME_RE.fullmatch(name)
        if not valid_name:
            raise _ParseFailure(ToolCallError.INVALID_NAME)
        if call_id is not None and (
            not isinstance(call_id, str)
            or not call_id
            or len(call_id) > MAX_CALL_ID_CHARS
            or any(ord(char) < 0x20 for char in call_id)
        ):
            raise _ParseFailure(ToolCallError.INVALID_CALL_ID)

        if isinstance(arguments, str):
            if len(arguments) > MAX_ARGUMENT_CHARS:
                raise _ParseFailure(ToolCallError.ARGUMENTS_TOO_LARGE)
            try:
                arguments = _load_json(arguments)
            except _ParseFailure as exc:
                if exc.code is ToolCallError.INPUT_TOO_LARGE:
                    raise
                raise _ParseFailure(ToolCallError.INVALID_ARGUMENTS) from None
        if not isinstance(arguments, dict):
            raise _ParseFailure(ToolCallError.INVALID_ARGUMENTS)
        _validate_arguments(arguments)
        calls.append(
            ToolCall(name=name, arguments=_copy_arguments(arguments), call_id=call_id)
        )
    return tuple(calls)


def _load_json(raw: str) -> Any:
    if len(raw) > MAX_CONTENT_CHARS:
        raise _ParseFailure(ToolCallError.INPUT_TOO_LARGE)

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)
            result[key] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=reject_duplicate,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                _ParseFailure(ToolCallError.MALFORMED_PAYLOAD)
            ),
        )
    except _ParseFailure:
        raise
    except (TypeError, ValueError, RecursionError):
        raise _ParseFailure(ToolCallError.MALFORMED_PAYLOAD) from None


def _validate_arguments(arguments: dict[str, Any]) -> None:
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise _ParseFailure(ToolCallError.INVALID_ARGUMENTS) from None
    if len(encoded) > MAX_ARGUMENT_CHARS:
        raise _ParseFailure(ToolCallError.ARGUMENTS_TOO_LARGE)

    nodes = 0
    string_chars = 0
    stack: list[tuple[Any, int]] = [(arguments, 1)]
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_ARGUMENT_NODES:
            raise _ParseFailure(ToolCallError.ARGUMENTS_TOO_LARGE)
        if depth > MAX_ARGUMENT_DEPTH:
            raise _ParseFailure(ToolCallError.ARGUMENTS_TOO_DEEP)
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or len(key) > MAX_ARGUMENT_KEY_CHARS:
                    raise _ParseFailure(ToolCallError.INVALID_ARGUMENTS)
                string_chars += len(key)
                stack.append((child, depth + 1))
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)
        elif isinstance(value, str):
            string_chars += len(value)
        elif value is not None and not isinstance(value, (bool, int, float)):
            raise _ParseFailure(ToolCallError.INVALID_ARGUMENTS)
        if string_chars > MAX_ARGUMENT_STRING_CHARS:
            raise _ParseFailure(ToolCallError.ARGUMENTS_TOO_LARGE)


def _copy_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Copy an already validated JSON tree without recursive Python calls."""

    root: dict[str, Any] = {}
    stack: list[tuple[dict[str, Any] | list[Any], str | int, Any]] = [
        (root, key, value) for key, value in reversed(tuple(arguments.items()))
    ]
    while stack:
        parent, key, value = stack.pop()
        if isinstance(value, dict):
            copied: dict[str, Any] = {}
            parent[key] = copied
            stack.extend(
                (copied, child_key, child)
                for child_key, child in reversed(tuple(value.items()))
            )
        elif isinstance(value, list):
            copied_list: list[Any] = [None] * len(value)
            parent[key] = copied_list
            stack.extend(
                (copied_list, index, child)
                for index, child in reversed(tuple(enumerate(value)))
            )
        else:
            parent[key] = value
    return root


__all__ = [
    "MAX_ARGUMENT_CHARS",
    "MAX_ARGUMENT_DEPTH",
    "MAX_ARGUMENT_NODES",
    "MAX_CONTENT_CHARS",
    "MAX_TOOL_CALLS",
    "ToolCall",
    "ToolCallError",
    "ToolCallParseResult",
    "ToolCallSource",
    "parse_tool_calls",
]
