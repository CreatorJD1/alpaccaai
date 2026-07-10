"""Creator-only execution for payload-backed Phase 4 commitments.

The initial executable surface is intentionally one read-only tool. Text-only
promises and legacy planner proposals cannot enter this path. Every accepted
run moves through the durable commitment state machine and closes with a
terminal receipt.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from alpecca import action_closure
from alpecca import commitments
from alpecca.turn_context import TurnContext
from config import DB_PATH


PAYLOAD_VERSION = 1
SELF_STATUS_TOOL = "self_status"
ALLOWED_TOOLS: dict[str, frozenset[str]] = {
    SELF_STATUS_TOOL: frozenset(),
}
_ERROR_PREFIXES = (
    "error:",
    "tool failed:",
    "unknown tool:",
    "innate tools are currently disabled",
)


class CommitmentExecutionError(ValueError):
    """An approved commitment cannot safely enter execution."""


def build_payload(tool: str, args: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return the canonical payload for the current executable allowlist."""
    clean_tool = str(tool or "").strip()
    if clean_tool not in ALLOWED_TOOLS:
        raise CommitmentExecutionError(f"commitment tool is not executable: {clean_tool or '<empty>'}")
    if args is None:
        clean_args: dict[str, Any] = {}
    elif isinstance(args, Mapping):
        clean_args = dict(args)
    else:
        raise CommitmentExecutionError("commitment args must be an object")
    allowed_args = ALLOWED_TOOLS[clean_tool]
    unexpected = sorted(str(key) for key in clean_args if key not in allowed_args)
    if unexpected:
        raise CommitmentExecutionError(
            f"unexpected args for {clean_tool}: {', '.join(unexpected[:5])}"
        )
    return {
        "version": PAYLOAD_VERSION,
        "tool": clean_tool,
        "args": {key: clean_args[key] for key in allowed_args},
    }


def validate_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CommitmentExecutionError("commitment has no machine payload")
    try:
        version = int(value.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version != PAYLOAD_VERSION:
        raise CommitmentExecutionError("unsupported commitment payload version")
    return build_payload(str(value.get("tool") or ""), value.get("args"))


def _turn_evidence(turn: TurnContext, *, event: str) -> dict[str, object]:
    return {
        "event": event[:48],
        "turn_id": turn.turn_id,
        "conversation_id": turn.conversation_id,
        "principal": turn.principal,
        "surface": turn.surface,
        "privacy_scope": turn.memory_scope,
    }


def _result_failed(result: str) -> bool:
    lowered = result.strip().lower()
    return not lowered or any(lowered.startswith(prefix) for prefix in _ERROR_PREFIXES)


def execute_approved_commitment(
    commitment_id: int,
    *,
    toolkit: Any,
    turn: TurnContext,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Run one approved creator commitment and persist its terminal receipt."""
    if not isinstance(turn, TurnContext):
        raise CommitmentExecutionError("a server-issued TurnContext is required")
    if turn.principal != "creator" or turn.surface != "workshop":
        raise PermissionError("commitment execution requires the creator Workshop surface")
    if not turn.allow_work():
        raise CommitmentExecutionError("execution turn is already cancelled")

    record = commitments.get_commitment(
        int(commitment_id), scope=turn.memory_scope, db_path=db_path,
    )
    if record is None:
        raise commitments.CommitmentNotFound(
            f"commitment {int(commitment_id)} was not found in this creator scope"
        )
    if record.get("state") != commitments.APPROVED:
        raise PermissionError("commitment must be approved before execution")
    payload = validate_payload(record.get("payload"))

    # This compare-and-swap transition is the execution claim. A racing caller
    # loses here and therefore never invokes the tool.
    running = commitments.transition_commitment(
        int(commitment_id),
        commitments.RUNNING,
        scope=turn.memory_scope,
        evidence=_turn_evidence(turn, event="execution_started"),
        db_path=db_path,
    )

    tool = str(payload["tool"])
    args = dict(payload["args"])
    result_text = ""
    failure = ""
    try:
        result_text = str(toolkit.execute(tool, args, turn=turn))[:4000]
    except Exception as exc:  # the ledger still needs a terminal receipt
        failure = f"{type(exc).__name__}: {exc}"[:500]
        result_text = failure

    if not turn.allow_work() or not turn.begin_commit():
        terminal = commitments.CANCELLED
        status = "cancelled"
        if not failure:
            failure = turn.barrier.reason or "execution turn was cancelled"
    elif failure or _result_failed(result_text):
        terminal = commitments.FAILED
        status = "failed"
        if not failure:
            failure = result_text[:500]
    else:
        terminal = commitments.SUCCEEDED
        status = "succeeded"

    receipt = {
        "status": status,
        "tool": tool,
        "result": result_text[:1000],
        "turn_id": turn.turn_id,
    }
    if failure:
        receipt["error"] = failure[:500]
    closed = commitments.transition_commitment(
        int(commitment_id),
        terminal,
        scope=turn.memory_scope,
        evidence=_turn_evidence(turn, event=f"execution_{status}"),
        receipt=receipt,
        db_path=db_path,
    )
    turn.finish_commit()
    closure = action_closure.action_closure_status(closed)
    return {
        "ok": terminal == commitments.SUCCEEDED,
        "commitment": closed,
        "execution": {
            "tool": tool,
            "args": args,
            "result": result_text,
            "status": status,
            "started_state": running.get("state"),
        },
        "closure": {
            "wording": closure.wording,
            "receipt_evidence": closure.receipt_evidence,
        },
    }


__all__ = [
    "ALLOWED_TOOLS",
    "CommitmentExecutionError",
    "PAYLOAD_VERSION",
    "SELF_STATUS_TOOL",
    "build_payload",
    "execute_approved_commitment",
    "validate_payload",
]
