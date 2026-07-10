"""Pure Phase 4 glue for cues, scoped commitments, and completion language."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from alpecca import commitments
from alpecca.commitment_language import (
    CommitmentReceiptState,
    enforce_commitment_language,
)
from alpecca.cues import CueEnvelope


ResolutionKind = Literal["resolved", "not-confirmation", "no-pending", "ambiguous"]
MAX_COMMITMENTS = 100
MAX_RECEIPTS = 32
MAX_METADATA_FIELDS = 16
MAX_METADATA_TEXT = 240


@dataclass(frozen=True, slots=True)
class ConfirmationResolution:
    """A read-only decision about which scoped proposed action to approve."""

    outcome: ResolutionKind
    scope: str
    commitment_id: int | None = None
    action: str = ""
    candidate_ids: tuple[int, ...] = ()
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class ActionClosureStatus:
    """Durable wording plus bounded receipt evidence for one commitment."""

    state: CommitmentReceiptState
    wording: str
    receipt_evidence: dict[str, object]


def _text(value: object, limit: int = MAX_METADATA_TEXT) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _identifier(value: object) -> int | None:
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return None
    return candidate if candidate >= 0 else None


def _bounded_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, object] = {}
    for key, item in value.items():
        if len(result) >= MAX_METADATA_FIELDS:
            break
        clean_key = _text(key, 64)
        if not clean_key:
            continue
        if isinstance(item, str):
            result[clean_key] = _text(item)
        elif isinstance(item, (int, float, bool)) or item is None:
            result[clean_key] = item
    return result


def _record_state(commitment: Mapping[str, object]) -> str:
    return _text(commitment.get("state"), 40).lower().replace("_", "-")


def _language_status(ledger_state: str) -> str:
    if ledger_state == commitments.PROPOSED:
        return "proposed"
    if ledger_state == commitments.APPROVED:
        return "approval-pending"
    if ledger_state == commitments.RUNNING:
        return "running"
    if ledger_state == commitments.SUCCEEDED:
        return "succeeded"
    if ledger_state == commitments.FAILED:
        return "failed"
    if ledger_state == commitments.CANCELLED:
        return "cancelled"
    return "unavailable"


def _terminal_receipt(
    commitment: Mapping[str, object], ledger_state: str,
) -> Mapping[str, object] | None:
    receipts = commitment.get("receipts")
    if not isinstance(receipts, Sequence) or isinstance(receipts, (str, bytes)):
        return None
    for candidate in reversed(receipts[-MAX_RECEIPTS:]):
        if not isinstance(candidate, Mapping):
            continue
        if _text(candidate.get("to_state"), 40).lower() == ledger_state:
            return candidate
    return None


def derive_receipt_evidence(commitment: Mapping[str, object]) -> dict[str, object]:
    """Return bounded, serializable receipt provenance without reading storage."""

    ledger_state = _record_state(commitment)
    event = _terminal_receipt(commitment, ledger_state)
    receipt = _bounded_mapping(event.get("receipt")) if event else {}
    evidence = _bounded_mapping(event.get("evidence")) if event else {}
    event_id = _identifier(event.get("id")) if event else None
    return {
        "commitment_id": _identifier(commitment.get("id")),
        "scope": _text(commitment.get("scope"), 160),
        "action": _text(commitment.get("action"), 160),
        "commitment_state": _language_status(ledger_state),
        "receipt_id": event_id,
        "receipt_transition": _text(event.get("to_state"), 40) if event else "",
        "receipt_present": bool(receipt),
        "receipt": receipt,
        "transition_evidence": evidence,
    }


def commitment_language_state(commitment: Mapping[str, object]) -> CommitmentReceiptState:
    """Adapt a ledger record into the strict state shape used by reply wording."""

    ledger_state = _record_state(commitment)
    evidence = derive_receipt_evidence(commitment)
    receipt_succeeded = (
        ledger_state == commitments.SUCCEEDED
        and evidence["receipt_transition"] == commitments.SUCCEEDED
        and bool(evidence["receipt_present"])
        and evidence["receipt_id"] is not None
    )
    return CommitmentReceiptState(
        status=_language_status(ledger_state),
        receipt_status="succeeded" if receipt_succeeded else "unavailable",
        receipt_id=str(evidence["receipt_id"] or ""),
        action=_text(commitment.get("action"), 160),
    )


def action_closure_status(commitment: Mapping[str, object]) -> ActionClosureStatus:
    """Expose status wording that is constrained by durable receipt evidence."""

    state = commitment_language_state(commitment)
    wording = enforce_commitment_language(
        f"I completed {state.action or 'this action'}.", state
    ).reply
    return ActionClosureStatus(
        state=state,
        wording=wording,
        receipt_evidence=derive_receipt_evidence(commitment),
    )


def resolve_confirmation(
    cues: CueEnvelope,
    commitments_in_scope: Iterable[Mapping[str, object]],
    *,
    scope: str,
) -> ConfirmationResolution:
    """Resolve a confirmation only when exactly one scoped proposal is pending."""

    if not isinstance(cues, CueEnvelope):
        raise TypeError("cues must be a CueEnvelope")
    clean_scope = _text(scope, 160)
    if not clean_scope:
        raise ValueError("scope is required")
    if not cues.confirmation.detected:
        return ConfirmationResolution("not-confirmation", clean_scope)

    candidates: list[tuple[int, str]] = []
    truncated = False
    for index, item in enumerate(commitments_in_scope):
        if index >= MAX_COMMITMENTS:
            truncated = True
            break
        if not isinstance(item, Mapping):
            continue
        if _text(item.get("scope"), 160) != clean_scope:
            continue
        if _record_state(item) != commitments.PROPOSED:
            continue
        commitment_id = _identifier(item.get("id"))
        if commitment_id is None:
            continue
        candidates.append((commitment_id, _text(item.get("action"), 160)))
        if len(candidates) >= 2:
            return ConfirmationResolution(
                "ambiguous",
                clean_scope,
                candidate_ids=tuple(item_id for item_id, _action in candidates),
                truncated=truncated,
            )
    if truncated:
        return ConfirmationResolution(
            "ambiguous",
            clean_scope,
            candidate_ids=tuple(item_id for item_id, _action in candidates),
            truncated=True,
        )
    if not candidates:
        return ConfirmationResolution("no-pending", clean_scope)
    commitment_id, action = candidates[0]
    return ConfirmationResolution(
        "resolved", clean_scope, commitment_id=commitment_id, action=action,
        candidate_ids=(commitment_id,),
    )


__all__ = [
    "ActionClosureStatus",
    "ConfirmationResolution",
    "MAX_COMMITMENTS",
    "MAX_METADATA_FIELDS",
    "MAX_METADATA_TEXT",
    "MAX_RECEIPTS",
    "action_closure_status",
    "commitment_language_state",
    "derive_receipt_evidence",
    "resolve_confirmation",
]
