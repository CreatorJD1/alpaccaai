"""Strict JSON helpers shared by the dry-run policy evaluators."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class InputError(ValueError):
    """Raised when an untrusted policy input does not match its exact schema."""


def require_object(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise InputError(f"{field} must be an object")
    return value


def require_exact_keys(
    value: dict[str, Any],
    field: str,
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> None:
    required_keys = set(required)
    allowed_keys = required_keys | set(optional)
    actual_keys = set(value)
    missing = sorted(required_keys - actual_keys)
    unknown = sorted(actual_keys - allowed_keys)
    if missing:
        raise InputError(f"{field} is missing keys: {', '.join(missing)}")
    if unknown:
        raise InputError(f"{field} has unknown keys: {', '.join(unknown)}")


def require_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise InputError(f"{field} must be a boolean")
    return value


def require_int(value: Any, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise InputError(f"{field} must be an integer >= {minimum}")
    return value


def require_string(
    value: Any,
    field: str,
    *,
    max_length: int = 512,
    identifier: bool = False,
) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise InputError(f"{field} must be a non-empty string without edge whitespace")
    if len(value) > max_length or any(ord(character) < 32 for character in value):
        raise InputError(f"{field} contains invalid characters or is too long")
    if identifier and not IDENTIFIER_RE.fullmatch(value):
        raise InputError(f"{field} must be a bounded identifier")
    return value


def require_string_list(
    value: Any,
    field: str,
    *,
    allow_empty: bool = True,
) -> list[str]:
    if type(value) is not list:
        raise InputError(f"{field} must be an array")
    result = [require_string(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if not allow_empty and not result:
        raise InputError(f"{field} must not be empty")
    if len(set(result)) != len(result):
        raise InputError(f"{field} must not contain duplicates")
    return result


def require_digest(value: Any, field: str) -> str:
    digest = require_string(value, field, max_length=71)
    if not DIGEST_RE.fullmatch(digest):
        raise InputError(f"{field} must be a sha256 digest")
    return digest


def parse_rfc3339(value: Any, field: str) -> datetime:
    timestamp = require_string(value, field, max_length=40)
    if not RFC3339_RE.fullmatch(timestamp):
        raise InputError(f"{field} must be an RFC3339 timestamp with an offset")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputError(f"{field} is not a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise InputError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def format_rfc3339(value: datetime) -> str:
    utc_value = value.astimezone(timezone.utc)
    timespec = "microseconds" if utc_value.microsecond else "seconds"
    return utc_value.isoformat(timespec=timespec).replace("+00:00", "Z")


def canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def load_json(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def print_json(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True))
